"""Web extensions: Python scripts the server's operator installs, run from the browser.

The desktop's plugins (``plugins/``, ``docs/plugins.md``) build Qt widgets and tools in
the running window, which a browser cannot host. A web extension is the part of that
idea that does carry over: a script that edits the open document, with a small form for
its parameters in the browser. Each run is one revision, so it is conflict-checked and
can be undone, and an extension that raises leaves the document untouched.

An extension is a ``*.py`` file in the extensions folder (``$INGETRAZO_WEB_EXTENSIONS``,
or ``extensions`` beside the document data)::

    EXTENSION = {
        "name": "Column grid",
        "description": "Stand a grid of square columns.",
        "parameters": [
            {"name": "rows", "label": "Rows", "type": "int", "default": 3, "min": 1, "max": 50},
            {"name": "spacing", "label": "Spacing (m)", "type": "number", "default": 4.0, "min": 0.1, "max": 100},
            {"name": "label", "label": "Name", "type": "text", "default": "Column"},
            {"name": "round", "label": "Round", "type": "bool", "default": False},
            {"name": "kind", "label": "Kind", "type": "choice", "choices": ["a", "b"], "default": "a"},
        ],
    }

    def run(scene, params):
        ...                      # edit the native scene; return a short message
        return "Done"

Extensions are code that runs inside the server with the server's rights: only the
operator can add them (they are files on the server, never uploaded through the API),
and the browser can only choose one by name and supply parameters, which are checked
against the declared schema before the script sees them.
"""
from __future__ import annotations

import importlib.util
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from .commands import commit_revision_from_file
from .schemas import RunExtension
from .document_store import DocumentStore

log = logging.getLogger("ingetrazo.web.extensions")

DEFAULT_TIMEOUT_SECONDS = 60.0
PARAMETER_TYPES = {"int", "number", "text", "bool", "choice"}
_KEY = re.compile(r"[A-Za-z0-9_\-]{1,60}")


class Extension:
    def __init__(self, key: str, path: Path) -> None:
        self.key, self.path = key, path
        self.name, self.description = key, ""
        self.parameters: list[dict[str, Any]] = []
        self.error: str | None = None
        self.run = None
        self.mtime = path.stat().st_mtime_ns
        try:
            spec = importlib.util.spec_from_file_location(f"ingetrazo_web_extension_{key}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)               # the operator installed this file
            meta = getattr(module, "EXTENSION", None)
            if not isinstance(meta, dict) or not callable(getattr(module, "run", None)):
                raise ValueError("it must define EXTENSION (a dict) and run(scene, params)")
            self.name = str(meta.get("name") or key)[:80]
            self.description = str(meta.get("description") or "")[:500]
            self.parameters = [self._check(item) for item in meta.get("parameters", [])]
            self.run = module.run
        except Exception as exc:  # noqa: BLE001 - a broken extension must not break the server
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("extension %s failed to load", key)

    @staticmethod
    def _check(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict) or item.get("type") not in PARAMETER_TYPES or not _KEY.fullmatch(str(item.get("name", ""))):
            raise ValueError(f"bad parameter declaration: {item!r}")
        out = {"name": item["name"], "label": str(item.get("label") or item["name"])[:80], "type": item["type"],
               "default": item.get("default")}
        for bound in ("min", "max"):
            if bound in item:
                out[bound] = float(item[bound])
        if item["type"] == "choice":
            choices = item.get("choices")
            if not isinstance(choices, list) or not choices or not all(isinstance(c, str) for c in choices):
                raise ValueError("a choice parameter needs a list of text choices")
            out["choices"] = choices
        return out

    def describe(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "description": self.description,
                "parameters": self.parameters, "error": self.error}

    def validate(self, given: Any) -> dict[str, Any]:
        """The parameters as the script receives them: the declared ones, checked."""
        if given is None:
            given = {}
        if not isinstance(given, dict):
            raise HTTPException(422, "params must be an object.")
        unknown = set(given) - {item["name"] for item in self.parameters}
        if unknown:
            raise HTTPException(422, f"Unknown parameter: {sorted(unknown)[0]}.")
        values: dict[str, Any] = {}
        for item in self.parameters:
            name, kind = item["name"], item["type"]
            value = given.get(name, item.get("default"))
            if kind == "bool":
                if not isinstance(value, bool):
                    raise HTTPException(422, f"{item['label']} must be true or false.")
            elif kind in ("int", "number"):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise HTTPException(422, f"{item['label']} must be a finite number.")
                if kind == "int":
                    if int(value) != value:
                        raise HTTPException(422, f"{item['label']} must be a whole number.")
                    value = int(value)
                else:
                    value = float(value)
                if value < item.get("min", -1e9) or value > item.get("max", 1e9):
                    raise HTTPException(422, f"{item['label']} must be between {item.get('min', -1e9):g} and {item.get('max', 1e9):g}.")
            elif kind == "text":
                if not isinstance(value, str) or len(value) > 1000:
                    raise HTTPException(422, f"{item['label']} must be text of at most 1000 characters.")
            elif value not in item["choices"]:
                raise HTTPException(422, f"{item['label']} must be one of {', '.join(item['choices'])}.")
            values[name] = value
        return values


class Registry:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._loaded: dict[str, Extension] = {}

    def scan(self) -> list[Extension]:
        found: dict[str, Extension] = {}
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.py")):
                key = path.stem
                if not _KEY.fullmatch(key) or path.is_symlink():
                    continue
                known = self._loaded.get(key)
                found[key] = known if known and known.mtime == path.stat().st_mtime_ns else Extension(key, path)
        self._loaded = found
        return list(found.values())

    def get(self, key: str) -> Extension:
        self.scan()
        extension = self._loaded.get(key)
        if extension is None:
            raise HTTPException(404, "Unknown extension.")
        if extension.error:
            raise HTTPException(422, f"This extension did not load: {extension.error}")
        return extension


def register_extension_commands(app: FastAPI, store: DocumentStore) -> None:
    directory = Path(os.environ.get("INGETRAZO_WEB_EXTENSIONS") or store.root / "extensions")
    registry = Registry(directory)
    timeout = float(os.environ.get("INGETRAZO_WEB_EXTENSION_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))

    @app.get("/api/v1/extensions")
    def list_extensions():
        return {"directory": str(directory), "extensions": [extension.describe() for extension in registry.scan()]}

    @app.post("/api/v1/documents/{document_id}/commands/run-extension", status_code=201)
    def run_extension(document_id: str, payload: RunExtension):
        extension = registry.get(payload.extension)
        params = extension.validate(payload.params)

        def produce(source: Path, target: Path):
            outcome = run_in_process(extension.path, extension.key, params, source, target, timeout)
            if outcome["status"] != "ok":
                raise HTTPException(422, f"{extension.name} {outcome['message']}")
            return {"message": outcome["message"]}

        return commit_revision_from_file(store, document_id, payload.base_revision, produce)


def _child(pipe, path: str, key: str, params: dict, source: str, target: str) -> None:
    """Runs in the child process: load the revision, run the script, save the result."""
    try:
        from .job_tasks import _limit_memory
        _limit_memory()
        from formats.igz import save_scene

        from .commands import ensure_qt
        from .scene_service import load_igz
        ensure_qt()
        extension = Extension(key, Path(path))
        if extension.error:
            pipe.send({"status": "failed", "message": f"did not load: {extension.error}"})
            return
        scene = load_igz(source)
        message = extension.run(scene, params)
        scene.version += 1
        save_scene(scene, Path(target))
        pipe.send({"status": "ok", "message": str(message)[:500] if message else f"{extension.name} ran."})
    except BaseException as exc:  # noqa: BLE001 - report the script's own failure, change nothing
        pipe.send({"status": "failed", "message": f"failed: {type(exc).__name__}: {exc}"[:600]})
    finally:
        pipe.close()


def run_in_process(path: Path, key: str, params: dict, source: Path, target: Path, timeout: float) -> dict:
    """Run one extension in its own process with a time limit.

    The script is operator-installed code, but a hang, a crash or a runaway allocation
    must cost one request, not the service: the child is killed at ``timeout`` seconds.
    """
    import multiprocessing
    import time

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(sender, str(path), key, params, str(source), str(target)), daemon=True)
    process.start()
    sender.close()
    started = time.monotonic()
    outcome = None
    try:
        while outcome is None:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                return {"status": "failed", "message": f"took longer than {timeout:g} seconds and was stopped."}
            if receiver.poll(min(0.2, remaining)):
                try:
                    outcome = receiver.recv()
                except (EOFError, OSError):
                    break
            elif not process.is_alive() and not receiver.poll(0):
                break
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
        process.join(2)
    if outcome is None:
        return {"status": "failed", "message": f"stopped unexpectedly (exit code {process.exitcode})."}
    return outcome

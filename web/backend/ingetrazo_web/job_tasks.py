"""What a job child process runs. Everything here is imported fresh in the child.

A task receives JSON-safe ``args`` and a ``report(fraction, message)`` callback, works
inside the job's directory, and returns a JSON-safe dict (``artifact`` names the file a
browser may download). Raising reports the job as failed with the exception's message.
"""
from __future__ import annotations

import resource
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

Report = Callable[[float, str], None]


def import_task(args: dict[str, Any], directory: Path, report: Report) -> dict[str, Any]:
    """Convert an uploaded interchange file into a native ``result.igz``."""
    from formats.igz import save_scene

    from .interchange import import_scene
    report(0.05, "Reading the file")
    scene = import_scene(directory / args["source"], args["format"], scale=float(args.get("scale", 1.0)),
                         progress=lambda fraction, message="": report(0.05 + 0.8 * float(fraction), str(message) or "Converting"))
    report(0.9, "Writing the native document")
    target = directory / "result.igz"
    save_scene(scene, target)
    return {"artifact": target.name}


def export_task(args: dict[str, Any], directory: Path, report: Report) -> dict[str, Any]:
    """Export one pinned revision of a document to an interchange format."""
    from .interchange import export_scene
    from .scene_service import load_igz
    report(0.03, "Loading the revision")
    scene = load_igz(args["revision_path"])
    target = export_scene(scene, directory / "out", args["format"], project_name=str(args.get("project_name") or "IngeTrazo model"),
                          progress=lambda fraction, message="": report(0.05 + 0.9 * float(fraction), str(message) or "Exporting"))
    final = directory / target.name
    Path(target).replace(final)
    return {"artifact": final.name}


#: Task name -> ``module:function``, resolved in the child. Tests may add their own.
TASKS: dict[str, str] = {
    "import": f"{__name__}:import_task",
    "export": f"{__name__}:export_task",
}


def _limit_memory() -> None:
    """Cap the child's address space where the OS honours it (Linux), so a hostile file
    cannot take the machine's memory; elsewhere the timeout and the kill remain."""
    import os
    limit = int(os.environ.get("INGETRAZO_WEB_JOB_MEMORY_MIB", "4096")) * 1024 * 1024
    if sys.platform.startswith("linux") and limit > 0:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass


def child_main(pipe, target: str, args: dict[str, Any], directory: str) -> None:
    """Entry point of the child process: run ``target`` (``module:function``) and send its
    outcome to the parent."""
    import importlib
    try:
        _limit_memory()
        from .commands import ensure_qt
        ensure_qt()
        module_name, _, function = target.partition(":")
        function_ = getattr(importlib.import_module(module_name), function)
        result = function_(args, Path(directory), lambda fraction, message: pipe.send(("progress", fraction, message)))
        pipe.send(("done", result or {}))
    except BaseException as exc:  # noqa: BLE001 - always tell the parent why
        try:
            pipe.send(("error", " ".join(str(exc).split()) or exc.__class__.__name__, traceback.format_exc()))
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            pipe.close()
        except Exception:  # noqa: BLE001
            pass

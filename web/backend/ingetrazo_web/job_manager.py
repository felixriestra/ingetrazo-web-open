"""Persistent conversion jobs, each run in its own process.

A converter parses files the server did not make (OBJ, STL, DAE, DXF, GLB ...). Running
it in the request process, or in a thread of it, lets one malformed or enormous file
exhaust the service's memory or take it down with a native crash. Here every job runs
in a freshly spawned child process: it can be killed on cancel or timeout, a crash or
out-of-memory kill is reported as that job's failure, and the service itself keeps
running. At most ``INGETRAZO_WEB_JOB_WORKERS`` (default 2) children run at once; the
rest wait their turn as ``queued``.

A job is a named task (see ``job_tasks.TASKS``) plus JSON arguments, so nothing but plain
data crosses the process boundary. The child reports progress over a pipe; the parent
writes ``status.json`` (the record the browser polls), so an interrupted service never
leaves a half-written status.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import signal
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock
from typing import Any, Callable
from uuid import UUID, uuid4

TERMINAL_STATES = {"completed", "failed", "cancelled"}
DEFAULT_TIMEOUT_SECONDS = 900.0


class JobNotFoundError(LookupError):
    pass


class JobManager:
    """Run bounded conversions in child processes and persist their status."""

    def __init__(self, root: str | Path, max_workers: int | None = None,
                 timeout_seconds: float | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_workers = max(1, max_workers or int(os.environ.get("INGETRAZO_WEB_JOB_WORKERS", "2")))
        self.timeout = float(timeout_seconds if timeout_seconds is not None
                             else os.environ.get("INGETRAZO_WEB_JOB_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        self._slots = threading.BoundedSemaphore(self.max_workers)
        self._lock = RLock()
        self._cancel: dict[str, Event] = {}
        self._processes: dict[str, multiprocessing.process.BaseProcess] = {}
        self._closing = False
        self._context = multiprocessing.get_context("spawn")      # never fork a threaded server
        self._recover_interrupted_jobs()

    # ------------------------------------------------------------------ public
    def create(self, kind: str, format_name: str, task: str, args: dict[str, Any],
               on_complete: Callable[[dict[str, Any], Path], dict[str, Any] | None] | None = None,
               files: dict[str, Path] | None = None, owner: str | None = None) -> dict[str, Any]:
        """Queue ``task`` with ``args``. ``files`` maps names to staged files that are moved
        into the job's folder first. ``on_complete(result, job_dir)`` runs in the service
        when the child succeeds and may return extra result fields."""
        import shutil
        job_id = str(uuid4())
        directory = self.root / job_id
        directory.mkdir()
        for name, source in (files or {}).items():
            shutil.move(str(source), str(directory / Path(name).name))
        now = _now()
        self._write(job_id, {
            "schema": "ingetrazo.job.v1", "id": job_id, "kind": kind, "format": format_name,
            "status": "queued", "progress": 0.0, "message": "Queued", "created_at": now,
            "updated_at": now, "result": None, "artifact": None, "owner": owner,
        })
        cancelled = Event()
        self._cancel[job_id] = cancelled
        threading.Thread(target=self._supervise, args=(job_id, cancelled, task, args, on_complete),
                         name=f"ingetrazo-job-{job_id[:8]}", daemon=True).start()
        return self.get(job_id)

    def shutdown(self) -> None:
        """Cancel running work and stop children (service shutdown)."""
        self._closing = True
        for event in list(self._cancel.values()):
            event.set()
        for process in list(self._processes.values()):
            _stop(process)

    def get(self, job_id: str) -> dict[str, Any]:
        path = self._status_path(job_id)
        if not path.is_file():
            raise JobNotFoundError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def owner_of(self, job_id: str):
        """The owner's name, ``None`` if the job has none, ``False`` when there is no such job."""
        try:
            return self.get(job_id).get("owner")
        except (JobNotFoundError, OSError, ValueError):
            return False

    def list(self, visible=None) -> list[dict[str, Any]]:
        jobs = []
        for status in self.root.glob("*/status.json"):
            try:
                record = json.loads(status.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if visible is None or visible(record.get("owner")):
                jobs.append(record)
        return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)

    def cancel(self, job_id: str) -> dict[str, Any]:
        record = self.get(job_id)
        if record["status"] in TERMINAL_STATES:
            return record
        event = self._cancel.get(job_id)
        if event is not None:
            event.set()
        self._update(job_id, message="Cancellation requested")
        return self.get(job_id)

    def artifact_path(self, job_id: str) -> Path:
        record = self.get(job_id)
        if record["status"] != "completed" or not record.get("artifact"):
            raise FileNotFoundError("This job has no completed artifact.")
        path = self.root / job_id / record["artifact"]
        if not path.is_file() or path.parent != self.root / job_id:
            raise FileNotFoundError("The conversion artifact is unavailable.")
        return path

    def diagnostics_path(self, job_id: str) -> Path:
        self.get(job_id)
        path = self.root / job_id / "diagnostics.txt"
        if not path.is_file():
            path.write_text("No diagnostics were recorded.\n", encoding="utf-8")
        return path

    # --------------------------------------------------------------- supervision
    def _supervise(self, job_id: str, cancelled: Event, task: str, args: dict[str, Any], on_complete) -> None:
        # Wait for a free slot, staying cancellable while queued.
        while not self._slots.acquire(timeout=0.2):
            if cancelled.is_set() or self._closing:
                self._finish_cancelled(job_id, "Cancelled before it started.")
                return
        try:
            if cancelled.is_set() or self._closing:
                self._finish_cancelled(job_id, "Cancelled before it started.")
                return
            self._run_child(job_id, cancelled, task, args, on_complete)
        except Exception as exc:  # noqa: BLE001 - the supervisor itself failed: report, never crash the service
            self._fail(job_id, _friendly(exc), traceback.format_exc())
        finally:
            self._slots.release()
            self._cancel.pop(job_id, None)
            self._processes.pop(job_id, None)

    def _run_child(self, job_id: str, cancelled: Event, task: str, args: dict[str, Any], on_complete) -> None:
        from . import job_tasks

        directory = self.root / job_id
        receiver, sender = self._context.Pipe(duplex=False)
        target = job_tasks.TASKS.get(task)
        if target is None:
            raise ValueError(f"Unknown job task: {task}")
        process = self._context.Process(target=job_tasks.child_main, args=(sender, target, args, str(directory)),
                                        name=f"ingetrazo-job-{job_id[:8]}", daemon=True)
        self._update(job_id, status="running", message="Starting conversion")
        process.start()
        sender.close()
        self._processes[job_id] = process
        started = time.monotonic()
        outcome: dict[str, Any] | None = None
        try:
            while outcome is None:
                if cancelled.is_set():
                    _stop(process)
                    self._finish_cancelled(job_id, "The conversion was cancelled.")
                    return
                if time.monotonic() - started > self.timeout:
                    _stop(process)
                    self._fail(job_id, f"The conversion took longer than {self.timeout:g} seconds and was stopped.",
                               "Timed out.\n")
                    return
                if receiver.poll(0.2):
                    try:
                        message = receiver.recv()
                    except (EOFError, OSError):
                        break                                   # the child died without a result
                    if message[0] == "progress":
                        self._update(job_id, progress=max(0.0, min(1.0, float(message[1]))), message=str(message[2])[:500])
                    else:
                        outcome = {"kind": message[0], "payload": message[1], "trace": message[2] if len(message) > 2 else ""}
                elif not process.is_alive():
                    if receiver.poll(0):
                        continue
                    break
        finally:
            receiver.close()
        process.join(timeout=5)
        if outcome is None:
            code = process.exitcode
            reason = (f"killed by signal {signal.Signals(-code).name}" if code is not None and code < 0
                      and -code in {s.value for s in signal.Signals} else f"exit code {code}")
            self._fail(job_id, f"The conversion process stopped unexpectedly ({reason}). "
                               "The file may be malformed or too large.", f"Child process ended: {reason}\n")
            return
        if outcome["kind"] == "error":
            self._fail(job_id, str(outcome["payload"])[:1000], f"Conversion failed: {outcome['payload']}\n\n{outcome['trace']}")
            return
        result = dict(outcome["payload"] or {})
        artifact = result.pop("artifact", None)
        if on_complete is not None:
            extra = on_complete(result, directory)
            if extra:
                result.update(extra)
        self._update(job_id, status="completed", progress=1.0, message="Conversion complete", result=result or None,
                     artifact=Path(artifact).name if artifact else None)
        self._diagnostic(job_id, "Conversion completed successfully.\n")

    def _finish_cancelled(self, job_id: str, message: str) -> None:
        self._update(job_id, status="cancelled", message=message)
        self._diagnostic(job_id, f"Cancelled: {message}\n")

    def _fail(self, job_id: str, message: str, details: str) -> None:
        self._update(job_id, status="failed", message=message)
        self._diagnostic(job_id, details)

    # ------------------------------------------------------------------- records
    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            record = self.get(job_id)
            record.update(changes)
            record["updated_at"] = _now()
            self._write(job_id, record)

    def _diagnostic(self, job_id: str, content: str) -> None:
        (self.root / job_id / "diagnostics.txt").write_text(content, encoding="utf-8")

    def _write(self, job_id: str, record: dict[str, Any]) -> None:
        path = self.root / job_id / "status.json"
        part = path.with_name(f"status.{uuid4().hex}.part")      # unique: two writers never share one
        try:
            part.write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
            part.replace(path)
        finally:
            part.unlink(missing_ok=True)

    def _status_path(self, job_id: str) -> Path:
        try:
            if str(UUID(job_id)) != job_id.lower():
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise JobNotFoundError(job_id) from exc
        return self.root / job_id / "status.json"

    def _recover_interrupted_jobs(self) -> None:
        for path in self.root.glob("*/status.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("status") in {"queued", "running"}:
                record.update(status="failed", progress=record.get("progress", 0.0),
                              message="The server stopped before this job completed.", updated_at=_now())
                self._write(path.parent.name, record)
                self._diagnostic(path.parent.name, record["message"] + "\n")


def _stop(process) -> None:
    """Ask a child to stop, then insist."""
    try:
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
    except (OSError, ValueError, AttributeError):
        pass


def _friendly(exc: Exception) -> str:
    return (" ".join(str(exc).split()) or exc.__class__.__name__)[:1000]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

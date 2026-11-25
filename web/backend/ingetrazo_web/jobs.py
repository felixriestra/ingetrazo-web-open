"""HTTP routes for conversion jobs: import an interchange file, export a revision."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, Request, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .document_store import DocumentNotFoundError, DocumentStore, RevisionNotFoundError
from .interchange import export_formats, import_formats, normalize_format
from .auth import can_see, current_user
from .schemas import ExportRequest
from .job_manager import JobManager, JobNotFoundError


def register_job_routes(app: FastAPI, store: DocumentStore, jobs: JobManager, copy_upload) -> None:
    """``copy_upload(upload, target)`` is the bounded upload copy shared with the document routes."""

    def job_or_404(job_id: str) -> dict:
        try:
            return jobs.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(404, "Job not found.") from exc

    @app.post("/api/v1/jobs/import", status_code=202)
    def import_job(request: Request, file: UploadFile = File(...), format: str | None = Form(None), scale: float = Form(1.0)):
        """Convert an uploaded model (OBJ, STL, DAE, DXF, GLB/GLTF) into a new document."""
        name = Path(file.filename or "model").name
        fmt = normalize_format(format, name)
        if fmt not in import_formats():
            raise HTTPException(415, f"Unsupported import format: {fmt or 'unknown'}. "
                                     f"Use one of {', '.join(import_formats())}.")
        if not 1e-9 <= scale <= 1e9:
            raise HTTPException(422, "scale must be between 1e-9 and 1e9.")
        with tempfile.TemporaryDirectory(prefix="import-", dir=store.root) as staging:
            upload = Path(staging) / f"upload.{fmt}"
            copy_upload(file, upload)
            document_name = Path(name).stem[:200] or "Imported model"

            owner = current_user(request).name if request.app.state.auth.enabled else None

            def finished(result, directory: Path):
                record = store.create(directory / "result.igz", f"{document_name}.igz", owner=owner)
                return {"document_id": record["id"], "document_name": record["name"]}

            return jobs.create("import", fmt, "import", {"source": upload.name, "format": fmt, "scale": float(scale)},
                               on_complete=finished, files={upload.name: upload}, owner=owner)

    @app.post("/api/v1/documents/{document_id}/revisions/{revision}/exports", status_code=202)
    def export_job(request: Request, document_id: str, revision: int, payload: ExportRequest):
        """Export one pinned revision to GLB, glTF, OBJ, STL, DAE, DXF or IFC."""
        fmt = normalize_format(payload.format)
        if fmt not in export_formats():
            raise HTTPException(422, f"format must be one of {', '.join(export_formats())}.")
        try:
            path = store.revision_path(document_id, revision)
            name = store.get(document_id)["name"]
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        return jobs.create("export", fmt, "export", {"revision_path": str(path), "format": fmt,
                                                     "project_name": Path(name).stem},
                           owner=current_user(request).name if request.app.state.auth.enabled else None)

    @app.get("/api/v1/jobs")
    def list_jobs(request: Request):
        user = current_user(request)
        return {"jobs": jobs.list(lambda owner: can_see(user, owner))}

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str):
        return job_or_404(job_id)

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job_or_404(job_id)
        return jobs.cancel(job_id)

    @app.get("/api/v1/jobs/{job_id}/artifact")
    def job_artifact(job_id: str):
        job_or_404(job_id)
        try:
            path = jobs.artifact_path(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/api/v1/jobs/{job_id}/diagnostics")
    def job_diagnostics(job_id: str):
        job_or_404(job_id)
        return FileResponse(jobs.diagnostics_path(job_id), media_type="text/plain", filename="diagnostics.txt")

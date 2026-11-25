"""Small immutable-revision document store for the web service.

This filesystem implementation is intentionally boring: native `.igz` files
remain the source of truth, metadata is JSON, and each revision is immutable.
The interface can later be backed by object storage and a database without
changing the HTTP document contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from .revision_history import effective_keep, revisions_to_prune, undo_state
from .scene_service import (inspect_igz, load_igz, preview_igz, summarize_scene,
                            validate_igz_container, write_preview)

PREVIEW_CACHE_VERSION = 11
SUMMARY_VERSION = 14


class DocumentNotFoundError(LookupError):
    pass


class RevisionNotFoundError(LookupError):
    pass


class RevisionConflictError(RuntimeError):
    pass


class DocumentStore:
    """Persist native documents as immutable numbered revisions."""

    def __init__(self, root: str | Path, keep_revisions: int | None = None) -> None:
        self.root = Path(root)
        #: Revisions kept per document (0 = all); older ones are deleted as new ones arrive.
        self.keep_revisions = effective_keep(
            int(os.environ.get("INGETRAZO_WEB_KEEP_REVISIONS", "0")) if keep_revisions is None else keep_revisions)
        self.documents = self.root / "documents"
        self.documents.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create(self, source: str | Path, filename: str, owner: str | None = None) -> dict[str, Any]:
        source = Path(source)
        validate_igz_container(source)
        summary = inspect_igz(source)
        document_id = str(uuid4())
        now = _now()
        metadata = {
            "schema": "ingetrazo.document.v1",
            "id": document_id,
            "name": _display_name(filename),
            "created_at": now,
            "updated_at": now,
            "latest_revision": 1,
            "summary_version": SUMMARY_VERSION,
            "revisions": [{"number": 1, "created_at": now, "summary": summary}],
        }
        if owner is not None:
            metadata["owner"] = owner
        staging = Path(tempfile.mkdtemp(prefix="create-", dir=self.root))
        try:
            revisions = staging / "revisions"
            revisions.mkdir()
            shutil.copyfile(source, revisions / "1.igz")
            _write_json(staging / "metadata.json", metadata)
            with self._lock:
                staging.replace(self.documents / document_id)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return metadata

    def owner_of(self, document_id: str):
        """The owner's name, ``None`` for a document made before accounts existed, or
        ``False`` when there is no such document. Reads only the small metadata file."""
        try:
            path = self._document_dir(document_id) / "metadata.json"
            return _read_json(path).get("owner") if path.is_file() else False
        except (DocumentNotFoundError, OSError, ValueError):
            return False

    def list(self, visible=None) -> list[dict[str, Any]]:
        """Every document, or those whose owner satisfies ``visible(owner)``."""
        records = []
        for metadata_path in self.documents.glob("*/metadata.json"):
            try:
                if visible is not None and not visible(_read_json(metadata_path).get("owner")):
                    continue
                records.append(self.get(metadata_path.parent.name))
            except (OSError, json.JSONDecodeError):
                continue
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return records

    def get(self, document_id: str) -> dict[str, Any]:
        path = self._document_dir(document_id) / "metadata.json"
        if not path.is_file():
            raise DocumentNotFoundError(document_id)
        metadata = _read_json(path)
        if metadata.get("summary_version") != SUMMARY_VERSION:
            with self._lock:
                metadata = _read_json(path)
                if metadata.get("summary_version") != SUMMARY_VERSION:
                    for revision in metadata.get("revisions", []):
                        number = int(revision["number"])
                        source = path.parent / "revisions" / f"{number}.igz"
                        if source.is_file():
                            revision["summary"] = inspect_igz(source)
                    metadata["summary_version"] = SUMMARY_VERSION
                    _write_json(path, metadata)
        metadata["undo"] = undo_state(metadata.get("revisions", []))
        return metadata

    def prune(self, document_id: str, keep: int | None = None) -> list[int]:
        """Delete the oldest revisions beyond ``keep`` (default: the server's limit); returns their numbers."""
        limit = self.keep_revisions if keep is None else effective_keep(keep)
        with self._lock:
            path = self._document_dir(document_id) / "metadata.json"
            if not path.is_file():
                raise DocumentNotFoundError(document_id)
            metadata = _read_json(path)
            doomed = revisions_to_prune(metadata.get("revisions", []), limit)
            if not doomed:
                return []
            base = self._document_dir(document_id)
            for number in doomed:
                (base / "revisions" / f"{number}.igz").unlink(missing_ok=True)
                for preview in (base / "previews").glob(f"{number}.v*.glb"):
                    preview.unlink(missing_ok=True)
            metadata["revisions"] = [item for item in metadata["revisions"] if int(item["number"]) not in set(doomed)]
            _write_json(path, metadata)
            return doomed

    def add_revision(self, document_id: str, source: str | Path,
                     expected_latest: int | None = None, *,
                     prepare_preview: bool = False, history: dict[str, Any] | None = None) -> dict[str, Any]:
        """Store ``source`` as the next revision.

        With ``prepare_preview`` the file is loaded once and that scene serves both the
        summary and the preview, which the browser fetches next anyway: an edit then
        costs one reload instead of two (measured with ``web.backend.benchmark_commands``).
        The summary must come from a reload, not from the scene that was edited: the
        edited scene still holds orphaned vertices that a save drops.
        """
        source = Path(source)
        validate_igz_container(source)
        scene = load_igz(source)
        summary = summarize_scene(scene, include_outline=True)
        with self._lock:
            metadata = self.get(document_id)
            if (expected_latest is not None
                    and int(metadata["latest_revision"]) != int(expected_latest)):
                raise RevisionConflictError(
                    f"Revision {expected_latest} is no longer current; "
                    f"the latest revision is {metadata['latest_revision']}."
                )
            number = int(metadata["latest_revision"]) + 1
            target = self._document_dir(document_id) / "revisions" / f"{number}.igz"
            part = target.with_suffix(".igz.part")
            try:
                shutil.copyfile(source, part)
                part.replace(target)
            finally:
                part.unlink(missing_ok=True)
            now = _now()
            metadata["latest_revision"] = number
            metadata["updated_at"] = now
            entry = {"number": number, "created_at": now, "summary": summary}
            if history:
                entry["history"] = history                 # an undo or redo: see revision_history.py
            metadata["revisions"].append(entry)
            _write_json(self._document_dir(document_id) / "metadata.json", metadata)
            if self.keep_revisions:
                self.prune(document_id)
                metadata = self.get(document_id)
        if prepare_preview:
            self._store_preview(document_id, number, scene)
        metadata["undo"] = undo_state(metadata.get("revisions", []))
        return metadata

    def _store_preview(self, document_id: str, number: int, scene) -> None:
        target = (self._document_dir(document_id) / "previews" / f"{number}.v{PREVIEW_CACHE_VERSION}.glb")
        part = target.with_suffix(".glb.part")
        try:
            target.parent.mkdir(exist_ok=True)
            write_preview(scene, part)
            part.replace(target)
        except Exception:  # noqa: BLE001 - the preview is rebuilt on demand if this fails
            pass
        finally:
            part.unlink(missing_ok=True)

    def revision_path(self, document_id: str, revision: int | None = None) -> Path:
        metadata = self.get(document_id)
        number = int(metadata["latest_revision"] if revision is None else revision)
        if number < 1:
            raise RevisionNotFoundError(number)
        path = self._document_dir(document_id) / "revisions" / f"{number}.igz"
        if not path.is_file():
            raise RevisionNotFoundError(number)
        return path

    def preview_path(self, document_id: str, revision: int | None = None) -> Path:
        source = self.revision_path(document_id, revision)
        number = int(source.stem)
        target = (self._document_dir(document_id) / "previews"
                  / f"{number}.v{PREVIEW_CACHE_VERSION}.glb")
        if target.is_file():
            return target
        with self._lock:
            if target.is_file():
                return target
            target.parent.mkdir(exist_ok=True)
            part = target.with_suffix(".glb.part")
            try:
                preview_igz(source, part)
                part.replace(target)
            finally:
                part.unlink(missing_ok=True)
        return target

    def _document_dir(self, document_id: str) -> Path:
        try:
            parsed = UUID(document_id)
        except (ValueError, AttributeError) as exc:
            raise DocumentNotFoundError(document_id) from exc
        canonical = str(parsed)
        if document_id.lower() != canonical:
            raise DocumentNotFoundError(document_id)
        return self.documents / canonical


def _display_name(filename: str) -> str:
    normalized = (filename or "Untitled.igz").replace("\\", "/")
    name = Path(normalized).name.strip()
    name = "".join(character for character in name
                   if character >= " " and character != "\x7f")
    return name[:255] or "Untitled.igz"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    value = {key: item for key, item in value.items() if key != "undo"}          # computed on read, never stored
    part = path.with_suffix(path.suffix + ".part")
    try:
        part.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)

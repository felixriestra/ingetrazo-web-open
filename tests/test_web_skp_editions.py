"""SKP import is open and wired into the import job; SKP export is private and optional."""
from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
openskp = pytest.importorskip("openskp")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web import edition  # noqa: E402
from web.backend.ingetrazo_web.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def sample_skp(path: Path) -> bytes:
    """A real .skp made with OpenSKP's own writer (so it works with or without our private writer)."""
    builder = openskp.create()
    builder.add_face([(0, 0, 0), (40, 0, 0), (40, 40, 0), (0, 40, 0)])               # inches
    builder.add_face([(0, 0, 0), (0, 40, 0), (0, 40, 40), (0, 0, 40)])
    builder.save(str(path))
    return path.read_bytes()


def wait(client, job_id):
    for _ in range(300):
        record = client.get(f"/api/v1/jobs/{job_id}").json()
        if record["status"] in {"completed", "failed", "cancelled"}:
            return record
        time.sleep(0.1)
    raise AssertionError(record)


def test_a_skp_file_is_imported_as_a_new_document(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    assert "skp" in client.get("/api/v1/capabilities").json()["interoperability"]["imports"]
    job = client.post("/api/v1/jobs/import", files={"file": ("casa.skp", sample_skp(tmp_path / "s.skp"))})
    assert job.status_code == 202, job.text
    done = wait(client, job.json()["id"])
    assert done["status"] == "completed", done
    record = client.get(f"/api/v1/documents/{done['result']['document_id']}").json()
    summary = record["revisions"][-1]["summary"]
    assert summary["unique_geometry"]["faces"] >= 2 and record["name"] == "casa.igz"
    assert summary["bounds"]["max"][0] > 0.9                                          # 40 inches is about 1.016 m


def test_a_broken_skp_fails_its_job_with_a_clear_message(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    job = client.post("/api/v1/jobs/import", files={"file": ("bad.skp", b"this is not a sketchup file")}).json()
    done = wait(client, job["id"])
    assert done["status"] == "failed" and "could not be read" in done["message"]
    assert client.get("/api/v1/health").status_code == 200


def test_skp_export_is_off_unless_the_private_writer_is_present_and_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("INGETRAZO_WEB_ENABLE_SKP_EXPORT", raising=False)
    client = TestClient(create_app(tmp_path / "data"))
    interop = client.get("/api/v1/capabilities").json()["interoperability"]
    assert "skp" not in interop["exports"] and interop["skp"]["export"]["enabled"] is False
    assert interop["edition"] in {"private", "open"}
    blank = client.post("/api/v1/documents/blank", json={"name": "x"}).json()
    refused = client.post(f"/api/v1/documents/{blank['id']}/revisions/1/exports", json={"format": "skp"})
    assert refused.status_code == 422 and "format must be one of" in refused.json()["detail"]["message"]




def test_the_open_edition_works_without_the_writer(tmp_path, monkeypatch):
    """Pretend formats/skp_out.py is not in the package: the service must run, import SKP, and say so."""
    monkeypatch.setenv("INGETRAZO_WEB_ENABLE_SKP_EXPORT", "1")
    monkeypatch.setitem(sys.modules, "formats.skp_out", None)               # an import of it now fails
    monkeypatch.setattr(edition.importlib.util, "find_spec", lambda name, *a, **k: None if name == "formats.skp_out" else __import__("importlib.util").util.find_spec(name))
    assert edition.edition() == "open" and edition.skp_export_module() is None
    client = TestClient(create_app(tmp_path / "data"))
    interop = client.get("/api/v1/capabilities").json()["interoperability"]
    assert interop["edition"] == "open" and "skp" not in interop["exports"] and "skp" in interop["imports"]
    assert interop["skp"]["export"] == {"present": False, "enabled": False}


def test_no_open_code_imports_the_private_writer_at_module_level():
    offenders = []
    private = set(edition.private_files())
    for path in list((ROOT / "web").rglob("*.py")) + [p for folder in ("core", "formats", "tools", "georef")
                                                       for p in (ROOT / folder).rglob("*.py")] + list((ROOT / "scripts").glob("*.py")):
        relative = str(path.relative_to(ROOT))
        if relative in private or "__pycache__" in relative:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:                # module level only
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom) else [])
            if any(name == "formats.skp_out" or name.endswith(".skp_out") or name == "skp_out" for name in names):
                offenders.append(f"{relative}:{node.lineno}")
    assert not offenders, offenders

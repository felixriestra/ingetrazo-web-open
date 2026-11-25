"""Every example document goes through the whole service: load, preview, edit, export to
each format, and a sheet PDF. This is the pruning acceptance check: if removing code broke
a path the service uses, it fails here."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web.app import create_app  # noqa: E402

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples").glob("*.igz"))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return TestClient(create_app(tmp_path_factory.mktemp("e2e") / "data"))


def wait(client, job_id):
    for _ in range(600):
        record = client.get(f"/api/v1/jobs/{job_id}").json()
        if record["status"] in {"completed", "failed", "cancelled"}:
            return record
        time.sleep(0.1)
    raise AssertionError(record)


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.stem)
def test_an_example_goes_through_the_service(client, example):
    record = client.post("/api/v1/documents", files={"file": (example.name, example.read_bytes())}).json()
    base = f"/api/v1/documents/{record['id']}"
    assert client.get(f"{base}/revisions/1/preview").content[:4] == b"glTF"

    edited = client.post(f"{base}/commands/create-box", json={"base_revision": 1, "size": [1, 1, 1], "name": "e2e"})
    assert edited.status_code == 201, edited.text
    assert client.post(f"{base}/commands/restore-revision",
                       json={"base_revision": 2, "source_revision": 1, "history": "undo"}).status_code == 201

    for fmt in ("glb", "gltf", "obj", "stl", "dae", "dxf", "svg"):
        job = client.post(f"{base}/revisions/1/exports", json={"format": fmt}).json()
        done = wait(client, job["id"])
        assert done["status"] == "completed", (fmt, done["message"])
        assert len(client.get(f"/api/v1/jobs/{job['id']}/artifact").content) > 100, fmt

    ifc = wait(client, client.post(f"{base}/revisions/1/exports", json={"format": "ifc"}).json()["id"])
    assert ifc["status"] == "completed" or "BIM" in ifc["message"], ifc               # a model with no tagged objects is refused

    sheet = client.post(f"{base}/commands/create-sheet", json={"base_revision": 3, "name": "P", "paper": "A3", "view": "top", "scale": 100})
    assert sheet.status_code == 201, sheet.text
    index = len(sheet.json()["revisions"][-1]["summary"]["composition_details"]) - 1
    pdf = client.get(f"{base}/revisions/4/sheets/{index}.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert client.get(f"{base}/revisions/4/render.png", params={"view": "iso", "width": 400}).status_code == 200


def test_the_examples_are_there():
    assert len(EXAMPLES) >= 4

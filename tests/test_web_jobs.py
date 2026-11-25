"""Conversion jobs run in their own processes: results, failures, cancel, timeout, limits."""
from __future__ import annotations

import json
import time
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web import job_tasks  # noqa: E402
from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.job_manager import JobManager  # noqa: E402

CUBE = "\n".join(["v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0", "v 0 0 1", "v 1 0 1", "v 1 1 1", "v 0 1 1",
                  "f 1 4 3 2", "f 5 6 7 8", "f 1 2 6 5", "f 2 3 7 6", "f 3 4 8 7", "f 4 1 5 8"])


def wait(read, done=("completed", "failed", "cancelled"), timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = read()
        if record["status"] in done:
            return record
        time.sleep(0.1)
    raise AssertionError(f"job did not finish: {read()}")


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def test_an_uploaded_model_is_converted_in_a_child_process_into_a_new_document(client):
    response = client.post("/api/v1/jobs/import", files={"file": ("cube.obj", CUBE.encode())}, data={"scale": "1"})
    assert response.status_code == 202, response.text
    job = wait(lambda: client.get(f"/api/v1/jobs/{response.json()['id']}").json())
    assert job["status"] == "completed", job
    assert job["result"]["document_name"] == "cube.igz"
    document = client.get(f"/api/v1/documents/{job['result']['document_id']}").json()
    assert document["revisions"][0]["summary"]["unique_geometry"]["faces"] >= 6 or document["revisions"][0]["summary"]["loose_geometry"]["faces"] >= 6
    assert client.get(f"/api/v1/jobs/{job['id']}/diagnostics").status_code == 200
    assert any(item["id"] == job["id"] for item in client.get("/api/v1/jobs").json()["jobs"])


def test_a_revision_is_exported_to_a_downloadable_artifact(client, tmp_path):
    job = client.post("/api/v1/jobs/import", files={"file": ("cube.obj", CUBE.encode())}).json()
    document_id = wait(lambda: client.get(f"/api/v1/jobs/{job['id']}").json())["result"]["document_id"]
    export = client.post(f"/api/v1/documents/{document_id}/revisions/1/exports", json={"format": "glb"})
    assert export.status_code == 202, export.text
    done = wait(lambda: client.get(f"/api/v1/jobs/{export.json()['id']}").json())
    assert done["status"] == "completed", done
    artifact = client.get(f"/api/v1/jobs/{done['id']}/artifact")
    assert artifact.status_code == 200 and artifact.content[:4] == b"glTF"
    assert client.get("/api/v1/jobs/not-a-job").status_code == 404


@pytest.mark.parametrize("request_", [
    ("post", "/api/v1/jobs/import", {"files": {"file": ("cube.xyz", b"x")}}, 415),
    ("post", "/api/v1/jobs/import", {"files": {"file": ("cube.obj", b"")}}, 422),
    ("post", "/api/v1/jobs/import", {"files": {"file": ("cube.step", b"x")}}, 415),
    ("post", "/api/v1/jobs/import", {"files": {"file": ("cube.obj", CUBE.encode())}, "data": {"scale": "0"}}, 422),
])
def test_bad_imports_are_refused_before_any_process_starts(client, request_):
    method, url, kwargs, status = request_
    assert getattr(client, method)(url, **kwargs).status_code == status
    assert client.get("/api/v1/jobs").json()["jobs"] == []


def test_a_malformed_model_fails_its_job_with_a_message_and_the_service_keeps_working(client):
    job = client.post("/api/v1/jobs/import", files={"file": ("bad.glb", b"not a glb at all")}).json()
    done = wait(lambda: client.get(f"/api/v1/jobs/{job['id']}").json())
    assert done["status"] == "failed" and done["message"]
    assert "Traceback" in client.get(f"/api/v1/jobs/{job['id']}/diagnostics").text
    assert client.get("/api/v1/health").status_code == 200


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    monkeypatch.setitem(job_tasks.TASKS, "sleepy", "tests.web_job_fixtures:sleepy")
    monkeypatch.setitem(job_tasks.TASKS, "crash", "tests.web_job_fixtures:crash")
    monkeypatch.setitem(job_tasks.TASKS, "fail", "tests.web_job_fixtures:fail")
    monkeypatch.setitem(job_tasks.TASKS, "fast", "tests.web_job_fixtures:fast")
    made = JobManager(tmp_path / "jobs", max_workers=1, timeout_seconds=60)
    yield made
    made.shutdown()


def test_a_child_that_is_killed_fails_only_its_own_job(manager):
    job = manager.create("test", "x", "crash", {})
    done = wait(lambda: manager.get(job["id"]))
    assert done["status"] == "failed" and "SIGKILL" in done["message"]
    ok = manager.create("test", "x", "fast", {"value": 7})
    finished = wait(lambda: manager.get(ok["id"]))
    assert finished["status"] == "completed" and finished["result"] == {"value": 7} and finished["artifact"] == "out.txt"
    assert manager.artifact_path(ok["id"]).read_text() == "done"


def test_a_task_that_raises_reports_its_message(manager):
    job = manager.create("test", "x", "fail", {})
    done = wait(lambda: manager.get(job["id"]))
    assert done["status"] == "failed" and done["message"] == "this model is broken"


def test_cancel_stops_a_running_child_and_a_queued_job_never_starts(manager):
    running = manager.create("test", "x", "sleepy", {"seconds": 60})
    queued = manager.create("test", "x", "sleepy", {"seconds": 60})          # one worker: this one waits
    wait(lambda: manager.get(running["id"]), done=("running",))
    assert manager.get(queued["id"])["status"] == "queued"
    manager.cancel(queued["id"])
    assert wait(lambda: manager.get(queued["id"]))["status"] == "cancelled"
    started = time.time()
    manager.cancel(running["id"])
    assert wait(lambda: manager.get(running["id"]))["status"] == "cancelled"
    assert time.time() - started < 10


def test_a_job_over_its_time_limit_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setitem(job_tasks.TASKS, "sleepy", "tests.web_job_fixtures:sleepy")
    short = JobManager(tmp_path / "jobs", max_workers=1, timeout_seconds=1.5)
    try:
        job = short.create("test", "x", "sleepy", {"seconds": 60})
        done = wait(lambda: short.get(job["id"]))
        assert done["status"] == "failed" and "longer than" in done["message"]
    finally:
        short.shutdown()


def test_jobs_interrupted_by_a_restart_are_reported_failed(tmp_path):
    """A service that died leaves jobs "queued" or "running" on disk; the next one reports them
    failed. The dead service is simulated with plain status files: a live first manager would
    keep its supervisor thread writing to the same file and race the recovery."""
    root = tmp_path / "jobs"
    ids = {status: str(uuid.uuid4()) for status in ("queued", "running", "completed")}
    for status, name in ids.items():
        (root / name).mkdir(parents=True)
        (root / name / "status.json").write_text(json.dumps(
            {"schema": "ingetrazo.job.v1", "id": name, "kind": "test", "format": "x", "status": status,
             "progress": 0.4, "message": "working", "created_at": "t", "updated_at": "t",
             "result": None, "artifact": None, "owner": None}), encoding="utf-8")
    manager = JobManager(root, max_workers=1)
    for status in ("queued", "running"):
        record = manager.get(ids[status])
        assert record["status"] == "failed" and "stopped" in record["message"]
    assert manager.get(ids["completed"])["status"] == "completed"      # finished jobs are left alone
    manager.shutdown()

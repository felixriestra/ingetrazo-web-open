"""Accounts, sessions and ownership (off by default, on once a user exists)."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from core.scene import Scene  # noqa: E402
from formats.igz import save_scene  # noqa: E402
from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.auth import Users  # noqa: E402

CUBE = "\n".join(["v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0", "v 0 0 1", "v 1 0 1", "v 1 1 1", "v 0 1 1",
                  "f 1 4 3 2", "f 5 6 7 8", "f 1 2 6 5", "f 2 3 7 6", "f 3 4 8 7", "f 4 1 5 8"])


@pytest.fixture()
def world(tmp_path):
    data = tmp_path / "data"
    users = Users(data)
    tokens = {"ana": users.add("ana"), "ben": users.add("ben"), "root": users.add("root", "admin")}
    client = TestClient(create_app(data))
    source = tmp_path / "empty.igz"
    save_scene(Scene(), source)

    class World:
        pass

    world = World()
    world.client, world.tokens, world.data, world.igz = client, tokens, data, source.read_bytes()
    world.bearer = lambda name: {"Authorization": f"Bearer {tokens[name]}"}
    world.upload = lambda name: client.post("/api/v1/documents", headers=world.bearer(name),
                                            files={"file": ("d.igz", world.igz)})
    return world


def test_auth_is_off_until_a_user_exists(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    assert client.get("/api/v1/auth/me").json() == {"auth_required": False, "authenticated": True, "user": "local", "role": "admin"}
    assert client.get("/api/v1/documents").status_code == 200


def test_every_api_call_needs_a_credential_but_the_page_and_health_do_not(world):
    client = world.client
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/").status_code in (200, 404)               # the page itself is public
    denied = client.get("/api/v1/documents")
    assert denied.status_code == 401 and denied.json()["detail"]["code"] == "unauthorized"
    assert client.get("/api/v1/documents", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/v1/documents", headers=world.bearer("ana")).status_code == 200
    assert client.get("/api/v1/auth/me").json() == {"auth_required": True, "authenticated": False}


def test_a_token_is_traded_for_a_session_cookie(world):
    client = world.client
    bad = client.post("/api/v1/auth/login", json={"token": "x" * 20})
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "invalid_token"
    ok = client.post("/api/v1/auth/login", json={"token": world.tokens["ana"]})
    assert ok.status_code == 200 and ok.json()["user"] == "ana"
    cookie = ok.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/v1/documents").status_code == 200                # the cookie alone now suffices
    assert client.get("/api/v1/auth/me").json()["user"] == "ana"
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/documents").status_code == 401


def test_a_tampered_or_expired_cookie_is_refused(world):
    client = world.client
    client.post("/api/v1/auth/login", json={"token": world.tokens["ana"]})
    good = client.cookies.get("ingetrazo_session")
    name, expiry, signature = good.split(".")
    # Clear first: newer test clients keep the server's cookie beside one set by hand.
    client.cookies.clear()
    client.cookies.set("ingetrazo_session", f"root.{expiry}.{signature}")
    assert client.get("/api/v1/documents").status_code == 401
    client.cookies.clear()
    client.cookies.set("ingetrazo_session", f"ana.1.{signature}")
    assert client.get("/api/v1/documents").status_code == 401


def test_failed_sign_ins_are_throttled(world):
    codes = [world.client.post("/api/v1/auth/login", json={"token": "wrong-token-%d" % i}).status_code for i in range(12)]
    assert 429 in codes and codes[0] == 401


def test_documents_belong_to_their_owner(world):
    client = world.client
    record = world.upload("ana").json()
    assert json.loads((world.data / "documents" / record["id"] / "metadata.json").read_text())["owner"] == "ana"
    path = f"/api/v1/documents/{record['id']}"
    assert client.get(path, headers=world.bearer("ana")).status_code == 200
    # another user cannot tell it exists, whatever they ask for
    for url in (path, path + "/revisions/1/preview", path + "/revisions/1/download", path + "/revisions/1/sheets/0/layout"):
        assert client.get(url, headers=world.bearer("ben")).status_code == 404, url
    edit = client.post(path + "/commands/create-box", headers=world.bearer("ben"), json={"base_revision": 1, "size": [1, 1, 1]})
    assert edit.status_code == 404
    assert [d["id"] for d in client.get("/api/v1/documents", headers=world.bearer("ben")).json()["documents"]] == []
    assert [d["id"] for d in client.get("/api/v1/documents", headers=world.bearer("ana")).json()["documents"]] == [record["id"]]
    # an administrator sees and edits everything
    assert client.get(path, headers=world.bearer("root")).status_code == 200
    assert client.post(path + "/commands/create-box", headers=world.bearer("root"), json={"base_revision": 1, "size": [1, 1, 1]}).status_code == 201
    assert client.get(path + "/nonexistent-doc", headers=world.bearer("ben")).status_code == 404


def test_documents_from_before_accounts_are_for_administrators_only(world):
    from web.backend.ingetrazo_web.document_store import DocumentStore
    legacy = DocumentStore(world.data).create(world.data.parent / "empty.igz", "old.igz")      # no owner
    path = f"/api/v1/documents/{legacy['id']}"
    assert world.client.get(path, headers=world.bearer("ana")).status_code == 404
    assert world.client.get(path, headers=world.bearer("root")).status_code == 200


def test_jobs_belong_to_their_owner_too(world):
    import time
    client = world.client
    job = client.post("/api/v1/jobs/import", headers=world.bearer("ana"), files={"file": ("cube.obj", CUBE.encode())}).json()
    for _ in range(300):
        record = client.get(f"/api/v1/jobs/{job['id']}", headers=world.bearer("ana")).json()
        if record["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    assert record["status"] == "completed", record
    imported = record["result"]["document_id"]
    assert client.get(f"/api/v1/documents/{imported}", headers=world.bearer("ana")).status_code == 200      # ana owns the result
    assert client.get(f"/api/v1/documents/{imported}", headers=world.bearer("ben")).status_code == 404
    for url in (f"/api/v1/jobs/{job['id']}", f"/api/v1/jobs/{job['id']}/artifact", f"/api/v1/jobs/{job['id']}/diagnostics"):
        assert client.get(url, headers=world.bearer("ben")).status_code == 404
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=world.bearer("ben")).status_code == 404
    assert client.get("/api/v1/jobs", headers=world.bearer("ben")).json()["jobs"] == []
    assert len(client.get("/api/v1/jobs", headers=world.bearer("root")).json()["jobs"]) == 1


def test_only_administrators_change_the_shared_categories(world):
    client = world.client
    assert client.post("/api/v1/library/taxonomy/create", headers=world.bearer("ana"), json={"name": "Mine"}).status_code == 403
    assert client.post("/api/v1/library/taxonomy/create", headers=world.bearer("root"), json={"name": "Shared"}).status_code in (200, 201)
    assert client.get("/api/v1/library/taxonomy", headers=world.bearer("ana")).status_code == 200


def test_a_request_from_another_site_is_refused_even_with_the_cookie(world):
    client = world.client
    client.post("/api/v1/auth/login", json={"token": world.tokens["ana"]})
    foreign = client.post("/api/v1/documents", headers={"Origin": "https://evil.example"}, files={"file": ("d.igz", world.igz)})
    assert foreign.status_code == 403 and foreign.json()["detail"]["code"] == "forbidden"
    same = client.post("/api/v1/documents", headers={"Origin": "http://testserver"}, files={"file": ("d.igz", world.igz)})
    assert same.status_code == 201


def test_removing_a_user_ends_their_session_and_a_new_token_replaces_the_old(world):
    client = world.client
    client.post("/api/v1/auth/login", json={"token": world.tokens["ben"]})
    assert client.get("/api/v1/documents").status_code == 200
    users = Users(world.data)
    users.remove("ben")
    assert client.get("/api/v1/documents").status_code == 401
    fresh = users.add("ana", rotate=True)
    assert client.get("/api/v1/documents", headers={"Authorization": f"Bearer {world.tokens['ana']}"}).status_code == 401
    assert client.get("/api/v1/documents", headers={"Authorization": f"Bearer {fresh}"}).status_code == 200


def test_users_file_stores_only_hashes_and_is_private(world):
    text = (world.data / "users.json").read_text()
    assert all(token not in text for token in world.tokens.values())
    assert (world.data / "users.json").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        Users(world.data).add("ana")
    with pytest.raises(ValueError):
        Users(world.data).add("bad name!")

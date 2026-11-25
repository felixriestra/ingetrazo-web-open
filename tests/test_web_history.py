"""Multi-step undo/redo and revision retention."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.revision_history import (MIN_KEPT, effective_keep, revisions_to_prune,  # noqa: E402
                                                        undo_state)


def edit(number):
    return {"number": number}


def move(number, kind, to):
    return {"number": number, "history": {"move": kind, "to": to}}


def test_the_position_is_rebuilt_by_replaying_the_moves():
    assert undo_state([edit(1)]) == {"undo_to": None, "redo_to": None, "position": 0, "states": 1, "state_revisions": [1]}
    chain = [edit(1), edit(2), edit(3), edit(4)]
    assert undo_state(chain)["undo_to"] == 3 and undo_state(chain)["redo_to"] is None
    after_undo = chain + [move(5, "undo", 3)]                    # 5 has revision 3's content
    state = undo_state(after_undo)
    assert (state["undo_to"], state["redo_to"]) == (2, 4)
    twice = after_undo + [move(6, "undo", 2)]
    assert (undo_state(twice)["undo_to"], undo_state(twice)["redo_to"]) == (1, 3)
    redone = twice + [move(7, "redo", 3)]
    assert (undo_state(redone)["undo_to"], undo_state(redone)["redo_to"]) == (2, 4)
    fresh = twice + [edit(7)]                                    # an edit after undoing drops the redo path
    assert (undo_state(fresh)["undo_to"], undo_state(fresh)["redo_to"]) == (2, None)
    assert undo_state(fresh)["states"] == 3


def test_a_move_to_a_revision_that_is_gone_counts_as_an_edit():
    state = undo_state([edit(3), edit(4), move(5, "undo", 2)])
    assert state["position"] == 2 and state["undo_to"] == 4


def test_retention_keeps_the_first_and_the_newest():
    revisions = [edit(n) for n in range(1, 13)]
    assert revisions_to_prune(revisions, 0) == []
    assert revisions_to_prune(revisions, 5) == [2, 3, 4, 5, 6, 7]
    assert revisions_to_prune(revisions[:5], 5) == []
    # after an undo, everything it stepped over is the redo path and is kept
    pointing = [edit(n) for n in range(1, 8)] + [move(8, "undo", 3)]
    assert revisions_to_prune(pointing, 3) == []
    long = [edit(n) for n in range(1, 13)] + [move(13, "undo", 11)]
    assert revisions_to_prune(long, 3) == [2, 3, 4, 5, 6, 7, 8]                              # states 9-12, the first and the newest
    assert effective_keep(0) == 0 and effective_keep(2) == MIN_KEPT and effective_keep(40) == 40


@pytest.fixture()
def doc(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    record = client.post("/api/v1/documents/blank", json={"name": "h"}).json()
    base = f"/api/v1/documents/{record['id']}"

    class Doc:
        pass

    d = Doc()
    d.client, d.base, d.store = client, base, client.app.state.document_store

    def post(endpoint, **body):
        latest = client.get(base).json()["latest_revision"]
        return client.post(f"{base}/commands/{endpoint}", json={"base_revision": latest, **body})

    d.post = post
    d.get = lambda: client.get(base).json()
    d.boxes = lambda: len(__import__("web.backend.ingetrazo_web.scene_service", fromlist=["x"]).load_igz(
        d.store.revision_path(record["id"], client.get(base).json()["latest_revision"])).groups)
    d.add = lambda: post("create-box", size=[1, 1, 1])
    d.step = lambda kind: post("restore-revision", source_revision=d.get()["undo"]["undo_to" if kind == "undo" else "redo_to"], history=kind)
    return d


def test_undo_and_redo_walk_through_the_edits(doc):
    for _ in range(3):
        assert doc.add().status_code == 201
    assert doc.boxes() == 3 and doc.get()["undo"]["undo_to"] == 3
    assert doc.step("undo").status_code == 201 and doc.boxes() == 2
    assert doc.step("undo").status_code == 201 and doc.boxes() == 1           # a second undo goes further back
    assert doc.step("undo").status_code == 201 and doc.boxes() == 0
    assert doc.get()["undo"]["undo_to"] is None
    assert doc.post("restore-revision", source_revision=1, history="undo").status_code == 422     # nothing to undo
    assert doc.step("redo").status_code == 201 and doc.boxes() == 1
    assert doc.step("redo").status_code == 201 and doc.boxes() == 2
    assert doc.get()["undo"]["redo_to"] is not None
    assert doc.add().status_code == 201 and doc.boxes() == 3                  # a new edit drops the redo path
    assert doc.get()["undo"]["redo_to"] is None
    assert doc.step("undo").status_code == 201 and doc.boxes() == 2
    assert doc.step("redo").status_code == 201 and doc.boxes() == 3


def test_a_step_must_lead_where_the_history_says(doc):
    doc.add(); doc.add()
    wrong = doc.post("restore-revision", source_revision=1, history="undo")
    assert wrong.status_code == 422 and "leads to revision" in wrong.json()["detail"]["message"]
    assert doc.post("restore-revision", source_revision=1, history="redo").status_code == 422
    # restoring by hand is an ordinary edit, not a step
    assert doc.post("restore-revision", source_revision=1).status_code == 201
    assert doc.get()["undo"]["redo_to"] is None and doc.boxes() == 0


def test_the_history_survives_a_reload_because_it_is_stored_in_the_revisions(doc, tmp_path):
    doc.add(); doc.add()
    doc.step("undo")
    from web.backend.ingetrazo_web.document_store import DocumentStore
    reopened = DocumentStore(tmp_path / "data").get(doc.get()["id"])
    assert reopened["undo"] == doc.get()["undo"] and reopened["undo"]["redo_to"] == 3
    assert "undo" not in __import__("json").loads((doc.store.documents / doc.get()["id"] / "metadata.json").read_text())


def test_old_revisions_are_deleted_beyond_the_limit_and_undo_still_works(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    store = client.app.state.document_store
    store.keep_revisions = 5
    record = client.post("/api/v1/documents/blank", json={"name": "r"}).json()
    base = f"/api/v1/documents/{record['id']}"
    for _ in range(12):
        latest = client.get(base).json()["latest_revision"]
        assert client.post(f"{base}/commands/create-box", json={"base_revision": latest, "size": [1, 1, 1]}).status_code == 201
    document = client.get(base).json()
    assert document["latest_revision"] == 13
    assert [item["number"] for item in document["revisions"]] == [1, 9, 10, 11, 12, 13]       # the first and the newest five
    folder = store.documents / record["id"]
    assert sorted(path.stem for path in (folder / "revisions").glob("*.igz")) == ["1", "10", "11", "12", "13", "9"]
    assert not list((folder / "previews").glob("5.v*.glb"))
    assert client.get(f"{base}/revisions/5/preview").status_code == 404                         # gone
    assert client.post(f"{base}/commands/restore-revision", json={"base_revision": 13, "source_revision": 5}).status_code == 404
    step = client.post(f"{base}/commands/restore-revision",
                       json={"base_revision": 13, "source_revision": document["undo"]["undo_to"], "history": "undo"})
    assert step.status_code == 201


def test_a_limit_below_the_minimum_is_raised_and_existing_documents_can_be_pruned(tmp_path):
    from web.backend.ingetrazo_web.document_store import DocumentStore
    client = TestClient(create_app(tmp_path / "data"))
    record = client.post("/api/v1/documents/blank", json={"name": "p"}).json()
    base = f"/api/v1/documents/{record['id']}"
    for _ in range(9):
        latest = client.get(base).json()["latest_revision"]
        client.post(f"{base}/commands/create-box", json={"base_revision": latest, "size": [1, 1, 1]})
    store = DocumentStore(tmp_path / "data", keep_revisions=2)
    assert store.keep_revisions == MIN_KEPT
    removed = store.prune(record["id"])
    assert removed == [2, 3, 4, 5] and [item["number"] for item in store.get(record["id"])["revisions"]] == [1, 6, 7, 8, 9, 10]
    assert store.prune(record["id"]) == []


def test_undo_and_redo_still_work_after_old_revisions_were_pruned(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    client.app.state.document_store.keep_revisions = 5
    record = client.post("/api/v1/documents/blank", json={"name": "q"}).json()
    base = f"/api/v1/documents/{record['id']}"

    def latest():
        return client.get(base).json()

    for _ in range(3):
        client.post(f"{base}/commands/create-box", json={"base_revision": latest()["latest_revision"], "size": [1, 1, 1]})
    for kind in ("undo", "undo", "undo", "redo", "redo"):          # more steps than revisions are kept
        state = latest()["undo"]
        target = state["undo_to" if kind == "undo" else "redo_to"]
        assert target is not None, kind
        step = client.post(f"{base}/commands/restore-revision",
                           json={"base_revision": latest()["latest_revision"], "source_revision": target, "history": kind})
        assert step.status_code == 201, (kind, step.text)
    assert latest()["undo"]["redo_to"] is not None and latest()["undo"]["undo_to"] is not None

from pathlib import Path
import json

from PySide6.QtGui import QVector3D
import pytest

from core.scene import Scene
from formats.igz import save_scene
from web.backend.ingetrazo_web.document_store import (
    DocumentNotFoundError,
    DocumentStore,
    PREVIEW_CACHE_VERSION,
    RevisionNotFoundError,
    SUMMARY_VERSION,
)


def _document(path: Path, width: float) -> None:
    scene = Scene()
    scene.mesh.add_face([
        QVector3D(0, 0, 0),
        QVector3D(width, 0, 0),
        QVector3D(0, 1, 0),
    ])
    save_scene(scene, path)


def test_create_list_and_download_revision(tmp_path):
    source = tmp_path / "source.igz"
    _document(source, 2)
    store = DocumentStore(tmp_path / "data")

    record = store.create(source, "../My project.igz")

    assert record["name"] == "My project.igz"
    assert record["latest_revision"] == 1
    assert store.list()[0]["id"] == record["id"]
    assert store.revision_path(record["id"], 1).read_bytes() == source.read_bytes()


def test_revisions_are_immutable_and_preview_is_cached(tmp_path):
    first = tmp_path / "first.igz"
    second = tmp_path / "second.igz"
    _document(first, 2)
    _document(second, 5)
    store = DocumentStore(tmp_path / "data")
    record = store.create(first, "model.igz")

    revised = store.add_revision(record["id"], second)
    preview = store.preview_path(record["id"], 2)

    assert revised["latest_revision"] == 2
    assert store.revision_path(record["id"], 1).read_bytes() == first.read_bytes()
    assert store.revision_path(record["id"], 2).read_bytes() == second.read_bytes()
    assert preview.read_bytes().startswith(b"glTF")
    assert preview.name == f"2.v{PREVIEW_CACHE_VERSION}.glb"
    assert store.preview_path(record["id"], 2) == preview


def test_unknown_document_and_revision_are_distinct(tmp_path):
    source = tmp_path / "source.igz"
    _document(source, 2)
    store = DocumentStore(tmp_path / "data")
    record = store.create(source, "model.igz")

    with pytest.raises(DocumentNotFoundError):
        store.get("not-a-uuid")
    with pytest.raises(RevisionNotFoundError):
        store.revision_path(record["id"], 99)


def test_legacy_metadata_is_upgraded_with_deterministic_object_ids(tmp_path):
    from core.group import Group

    source = tmp_path / "source.igz"
    scene = Scene()
    group = Group(name="Legacy group")
    group.mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 0),
    ])
    scene.groups.append(group)
    save_scene(scene, source)
    store = DocumentStore(tmp_path / "data")
    record = store.create(source, "legacy.igz")
    metadata_path = store.documents / record["id"] / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("summary_version")
    metadata["revisions"][0]["summary"].pop("outline")
    metadata_path.write_text(json.dumps(metadata))

    upgraded = store.get(record["id"])

    assert upgraded["summary_version"] == SUMMARY_VERSION
    item = upgraded["revisions"][0]["summary"]["outline"]["items"][0]
    assert item["id"] == "group:0"


def test_uploaded_display_name_strips_cross_platform_paths_and_controls(tmp_path):
    source = tmp_path / "source.igz"
    _document(source, 1)
    store = DocumentStore(tmp_path / "data")

    record = store.create(source, "C:\\Users\\person\\model\x00.igz")

    assert record["name"] == "model.igz"

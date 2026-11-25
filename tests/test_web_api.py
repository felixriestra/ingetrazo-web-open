"""HTTP contract tests; skipped unless the optional web dependencies exist."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.scene_service import load_igz  # noqa: E402
from core.group import world_mesh  # noqa: E402
from core.group import Group  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats.igz import save_scene  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402


def test_health_and_capabilities(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))

    assert client.get("/api/v1/health").json()["status"] == "ok"
    capabilities = client.get("/api/v1/capabilities").json()
    assert capabilities["document"]["read"] == ["igz"]
    assert capabilities["preview"]["mode"] == "read-only"
    assert capabilities["preview"]["semantic_nodes"] is True
    assert capabilities["presentation"]["section_planes"] is True
    assert capabilities["presentation"]["measurement"] is True
    assert capabilities["limits"]["upload_bytes"] == 100 * 1024 * 1024
    assert capabilities["modeling"]["commands"][:31] == [
        "presentation.update", "object.move", "object.rotate", "object.scale",
        "object.duplicate", "object.delete", "object.rename", "primitive.box.create",
        "primitive.line.create", "primitive.rectangle.create", "primitive.circle.create",
        "primitive.arc.create", "face.push_pull", "face.offset", "object.material.set",
        "dimension.create", "text.create", "guide.create",
        "object.ifc.set", "bim.quantities.export", "ifc.export",
        "georef.set", "survey.import", "geopath.create",
        "map.set",
        "terrain.import",
        "style.set", "shadows.set",
        "sheet.create", "sheet.pdf.export",
        "layer.set_visibility",
    ]


def test_annotation_commands_create_native_revision_entities(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "annotations.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    url = f"/api/v1/documents/{document_id}/commands/create-annotation"

    dimension = client.post(url, json={
        "base_revision": 1,
        "operation": "dimension",
        "a": [0, 0, 0],
        "b": [2, 0, 0],
        "offset": [0, 0.5, 0],
        "text": "Width <>",
    })
    assert dimension.status_code == 201, dimension.text
    dim_summary = dimension.json()["revisions"][-1]["summary"]
    assert dim_summary["dimensions"] == 1
    assert dim_summary["dimension_details"][0]["value"] == pytest.approx(2)
    assert dim_summary["dimension_details"][0]["label"].startswith("Width ")
    assert dim_summary["dimension_details"][0]["line"] == [
        [0.0, 0.5, 0.0], [2.0, 0.5, 0.0],
    ]

    label = client.post(url, json={
        "base_revision": 2,
        "operation": "text",
        "anchor": [1, 2, 3],
        "offset": [0.25, 0.5, 0],
        "text": "Entrance",
    })
    assert label.status_code == 201, label.text
    label_summary = label.json()["revisions"][-1]["summary"]
    assert label_summary["text_label_details"][0] == {
        "id": "text:0", "anchor": [1.0, 2.0, 3.0],
        "position": [1.25, 2.5, 3.0], "text": "Entrance", "layer": None,
        "visible": True,
    }

    guide = client.post(url, json={
        "base_revision": 3,
        "operation": "guide-line",
        "point": [4, 5, 6],
        "direction": [10, 0, 0],
    })
    assert guide.status_code == 201, guide.text
    guide_summary = guide.json()["revisions"][-1]["summary"]
    assert guide_summary["guides"] == 1
    assert guide_summary["guide_details"][0]["direction"] == [1.0, 0.0, 0.0]

    loaded = load_igz(app.state.document_store.revision_path(document_id, 4))
    assert len(loaded.dimensions) == len(loaded.text_labels) == len(loaded.guides) == 1
    assert loaded.dimensions[0].text == "Width <>"
    assert loaded.text_labels[0].text == "Entrance"
    assert loaded.guides[0].is_line

    invalid = client.post(url, json={
        "base_revision": 4,
        "operation": "guide-line",
        "point": [0, 0, 0],
        "direction": [0, 0, 0],
    })
    assert invalid.status_code == 422


def test_bim_classification_quantities_and_ifc_exports(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "bim.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    box = client.post(
        f"/api/v1/documents/{document_id}/commands/create-box",
        json={
            "base_revision": 1, "name": "C-01",
            "size": [2, 3, 4], "origin": [0, 0, 0],
        },
    )
    assert box.status_code == 201, box.text

    classified = client.post(
        f"/api/v1/documents/{document_id}/commands/object-ifc",
        json={
            "base_revision": 2, "object_id": "group:0",
            "class": "IfcColumn", "name": "Column C-01",
        },
    )
    assert classified.status_code == 201, classified.text
    summary = classified.json()["revisions"][-1]["summary"]
    assert summary["outline"]["items"][0]["ifc"] == {
        "class": "IfcColumn", "name": "Column C-01",
    }
    assert summary["bim_objects"][0]["id"] == "group:0"
    assert summary["bim_objects"][0]["takeoff"] == pytest.approx(24)
    assert summary["bim_objects"][0]["takeoff_unit"] == "m3"
    assert summary["bim_objects"][0]["volume_m3"] == pytest.approx(24)

    csv = client.get(
        f"/api/v1/documents/{document_id}/revisions/3/quantities.csv",
    )
    assert csv.status_code == 200
    assert "IfcColumn,\"Column C-01\",24.0000,m3" in csv.text
    exported_ifc = client.get(
        f"/api/v1/documents/{document_id}/revisions/3/model.ifc",
    )
    assert exported_ifc.status_code == 200
    assert b"FILE_SCHEMA(('IFC4'))" in exported_ifc.content
    assert b"IFCCOLUMN(" in exported_ifc.content

    scene = load_igz(app.state.document_store.revision_path(document_id, 3))
    assert scene.groups[0].ifc == {
        "class": "IfcColumn", "name": "Column C-01",
    }

    cleared = client.post(
        f"/api/v1/documents/{document_id}/commands/object-ifc",
        json={
            "base_revision": 3, "object_id": "group:0", "clear": True,
        },
    )
    assert cleared.status_code == 201
    assert cleared.json()["revisions"][-1]["summary"]["bim_objects"] == []


def test_georef_survey_and_traced_path_native_round_trip(tmp_path):
    from georef.datum import utm_forward, zone_for_lon

    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "site.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    lat, lon, altitude = -13.5319, -71.9675, 3399.0
    zone = zone_for_lon(lon)
    east, north = utm_forward(lat, lon, zone)

    survey = client.post(
        f"/api/v1/documents/{document_id}/commands/import-survey",
        json={
            "base_revision": 1, "zone": zone, "northern": False,
            "text": (
                f"P,N,E,Z,D\n"
                f"P1,{north:.4f},{east:.4f},{altitude:.3f},origin\n"
                f"P2,{north:.4f},{east + 10:.4f},{altitude + 1:.3f},east control\n"
            ),
        },
    )
    assert survey.status_code == 201, survey.text
    survey_summary = survey.json()["revisions"][-1]["summary"]
    assert survey_summary["georeferenced"] is True
    assert survey_summary["georef_detail"]["zone"] == zone
    assert survey_summary["georef_detail"]["hemisphere"] == "S"
    assert survey_summary["survey_points"] == 2
    assert survey_summary["survey_point_details"][0]["name"] == "P1"
    assert survey_summary["survey_point_details"][1]["position"][0] == pytest.approx(
        10, abs=0.01,
    )

    datum = client.post(
        f"/api/v1/documents/{document_id}/commands/set-georef",
        json={
            "base_revision": 2, "latitude": lat, "longitude": lon,
            "altitude": altitude, "north": 12.5,
        },
    )
    assert datum.status_code == 201, datum.text
    datum_detail = datum.json()["revisions"][-1]["summary"]["georef_detail"]
    assert datum_detail["lat"] == pytest.approx(lat)
    assert datum_detail["north"] == pytest.approx(12.5)

    path = client.post(
        f"/api/v1/documents/{document_id}/commands/create-geopath",
        json={
            "base_revision": 3, "name": "Lot A", "closed": True,
            "surface": "flat",
            "points": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]],
        },
    )
    assert path.status_code == 201, path.text
    path_summary = path.json()["revisions"][-1]["summary"]
    assert path_summary["geo_paths"] == 1
    assert path_summary["geo_path_details"][0]["name"] == "Lot A"
    assert path_summary["geo_path_details"][0]["length"] == pytest.approx(40)
    assert path_summary["geo_path_details"][0]["area"] == pytest.approx(100)
    assert path_summary["geo_path_details"][0]["surface"] == "flat"

    loaded = load_igz(app.state.document_store.revision_path(document_id, 4))
    assert loaded.georef.north == pytest.approx(12.5)
    assert len(loaded.geo_points) == 2
    assert len(loaded.geo_paths) == 1
    assert loaded.geo_paths[0].closed is True


def test_licensed_base_map_capture_native_round_trip(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "map.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    datum = client.post(
        f"/api/v1/documents/{document_id}/commands/set-georef",
        json={
            "base_revision": 1, "latitude": -13.5319,
            "longitude": -71.9675, "altitude": 3399, "north": 0,
        },
    )
    assert datum.status_code == 201
    mapped = client.post(
        f"/api/v1/documents/{document_id}/commands/set-map",
        json={
            "base_revision": 2, "source": "esri_imagery", "zoom": 16,
            "radius": 300, "opacity": 0.7,
        },
    )
    assert mapped.status_code == 201, mapped.text
    detail = mapped.json()["revisions"][-1]["summary"]["map"]
    assert detail["source"] == "esri_imagery"
    assert detail["opacity"] == pytest.approx(0.7)
    assert detail["tiles"]
    assert len(detail["tiles"][0]["corners"]) == 4
    assert "server.arcgisonline.com" in detail["tiles"][0]["url"]
    loaded = load_igz(app.state.document_store.revision_path(document_id, 3))
    assert loaded.tile_layer.source.id == "esri_imagery"
    assert loaded.tile_layer.radius_m == pytest.approx(300)

    cleared = client.post(
        f"/api/v1/documents/{document_id}/commands/set-map",
        json={"base_revision": 3, "clear": True},
    )
    assert cleared.status_code == 201
    assert cleared.json()["revisions"][-1]["summary"]["map"] is None


def test_surveyed_terrain_grid_becomes_persistent_reference_mesh(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "terrain.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    imported = client.post(
        f"/api/v1/documents/{document_id}/commands/import-terrain",
        json={
            "base_revision": 1, "columns": 3,
            "text": (
                "0,10,1\n5,10,2\n10,10,1\n"
                "0,5,0\n5,5,1\n10,5,0\n"
                "0,0,-1\n5,0,0\n10,0,-1\n"
            ),
        },
    )
    assert imported.status_code == 201, imported.text
    detail = imported.json()["revisions"][-1]["summary"]["photogrammetry"]
    assert detail["vertices"] == 9
    assert detail["triangles"] == 8
    assert detail["vertical_reference"] == "local"
    assert len(detail["mesh"]["vertices"]) == 9
    assert len(detail["mesh"]["triangles"]) == 8
    loaded = load_igz(app.state.document_store.revision_path(document_id, 2))
    assert loaded.photo_mesh.vertex_count == 9
    assert loaded.photo_mesh.triangle_count == 8
    assert loaded.photo_mesh.height_at(5, 5) == pytest.approx(1)

    invalid = client.post(
        f"/api/v1/documents/{document_id}/commands/import-terrain",
        json={"base_revision": 2, "columns": 3, "text": "0,0,0\n1,0,0\n"},
    )
    assert invalid.status_code == 422


def test_display_style_and_solar_shadows_native_round_trip(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "solar.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]

    styled = client.post(
        f"/api/v1/documents/{document_id}/commands/set-style",
        json={"base_revision": 1, "name": "Hidden line"},
    )
    assert styled.status_code == 201, styled.text
    assert styled.json()["revisions"][-1]["summary"]["display_style"]["face_mode"] == "hidden_line"

    datum = client.post(
        f"/api/v1/documents/{document_id}/commands/set-georef",
        json={
            "base_revision": 2, "latitude": -13.5319,
            "longitude": -71.9675, "altitude": 3399, "north": 0,
        },
    )
    assert datum.status_code == 201, datum.text
    shadows = client.post(
        f"/api/v1/documents/{document_id}/commands/set-shadows",
        json={
            "base_revision": 3, "enabled": True, "month": 6, "day": 21,
            "hour": 10, "minute": 30, "darkness": 0.4, "utc_offset": -5,
        },
    )
    assert shadows.status_code == 201, shadows.text
    summary = shadows.json()["revisions"][-1]["summary"]
    assert summary["shadows"] == {
        "enabled": True, "month": 6, "day": 21, "hour": 10,
        "minute": 30, "darkness": 0.4, "utc_offset": -5,
    }
    assert summary["sun"]["direction"] is not None
    assert summary["sun"]["when_utc"].startswith("2026-06-21T15:30:00")

    loaded = load_igz(app.state.document_store.revision_path(document_id, 4))
    assert loaded.display_style.name == "Hidden line"
    assert loaded.shadows.enabled is True
    assert loaded.shadows.darkness == pytest.approx(0.4)

    invalid = client.post(
        f"/api/v1/documents/{document_id}/commands/set-shadows",
        json={
            "base_revision": 4, "enabled": True, "month": 2, "day": 31,
            "hour": 10, "minute": 30, "darkness": 0.4, "utc_offset": None,
        },
    )
    assert invalid.status_code == 422


def test_native_sheet_creation_and_revision_pinned_pdf(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = tmp_path / "sheet.igz"
    save_scene(Scene(), source)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    box = client.post(
        f"/api/v1/documents/{document_id}/commands/create-box",
        json={
            "base_revision": 1, "name": "Room",
            "size": [6, 4, 3], "origin": [0, 0, 0],
        },
    )
    assert box.status_code == 201, box.text
    sheet = client.post(
        f"/api/v1/documents/{document_id}/commands/create-sheet",
        json={
            "base_revision": 2, "name": "Ground plan", "paper": "A3",
            "landscape": True, "view": "top", "scale": 50,
        },
    )
    assert sheet.status_code == 201, sheet.text
    detail = sheet.json()["revisions"][-1]["summary"]["composition_details"][0]
    assert detail["name"] == "Ground plan"
    assert detail["page_mm"] == [420.0, 297.0]
    assert detail["frame_details"][0]["view"] == "std:top"
    assert detail["frame_details"][0]["scale"] == pytest.approx(50)

    native = load_igz(app.state.document_store.revision_path(document_id, 3))
    assert native.compositions[0].frames[0].style == "vectorial"
    pdf = client.get(
        f"/api/v1/documents/{document_id}/revisions/3/sheets/0.pdf",
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF-")
    assert len(pdf.content) > 1000
    assert pdf.headers["content-type"] == "application/pdf"
    assert client.get(
        f"/api/v1/documents/{document_id}/revisions/3/sheets/9.pdf",
    ).status_code == 404


def test_preview_returns_glb_and_summary_header(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = Path(__file__).parents[1] / "examples" / "arco-yanque.igz"
    with source.open("rb") as stream:
        response = client.post(
            "/api/v1/documents/preview",
            files={"file": (source.name, stream, "application/octet-stream")},
        )

    encoded = response.headers["X-IngeTrazo-Summary"]
    summary = json.loads(base64.urlsafe_b64decode(encoded))
    assert response.status_code == 200
    assert response.content.startswith(b"glTF")
    assert float(response.headers["X-IngeTrazo-Preview-Milliseconds"]) >= 0
    assert "ingetrazo;dur=" in response.headers["Server-Timing"]
    assert response.headers["Cache-Control"] == "no-store"
    assert summary["schema"] == "ingetrazo.scene-summary.v1"
    assert summary["unique_geometry"]["faces"] > 0


def test_upload_rejects_wrong_extension(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    response = client.post(
        "/api/v1/documents/preview",
        files={"file": ("model.txt", b"{}", "text/plain")},
    )

    assert response.status_code == 415


def test_saved_document_revision_round_trip(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = Path(__file__).parents[1] / "examples" / "arco-yanque.igz"
    original = source.read_bytes()
    response = client.post(
        "/api/v1/documents",
        files={"file": (source.name, original, "application/octet-stream")},
    )

    assert response.status_code == 201
    record = response.json()
    document_id = record["id"]
    summary = record["revisions"][0]["summary"]
    assert summary["layer_details"][0]["name"] == "Layer 0"
    assert "outline" in summary
    assert client.get("/api/v1/documents").json()["documents"][0]["id"] == document_id
    download = client.get(f"/api/v1/documents/{document_id}/revisions/1/download")
    preview = client.get(f"/api/v1/documents/{document_id}/revisions/1/preview")
    assert download.content == original
    assert "immutable" in download.headers["Cache-Control"]
    assert preview.content.startswith(b"glTF")
    assert float(preview.headers["X-IngeTrazo-Preview-Milliseconds"]) >= 0
    assert preview.headers["Cache-Control"] == "private, no-cache"


def test_layer_visibility_command_creates_revision_and_detects_conflict(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = Path(__file__).parents[1] / "examples" / "arco-yanque.igz"
    response = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    )
    document_id = response.json()["id"]
    command_url = f"/api/v1/documents/{document_id}/commands/layer-visibility"

    changed = client.post(command_url, json={
        "base_revision": 1,
        "changes": {"Layer 0": False},
    })

    assert changed.status_code == 201
    record = changed.json()
    assert record["latest_revision"] == 2
    latest = record["revisions"][-1]["summary"]
    layer = next(item for item in latest["layer_details"] if item["name"] == "Layer 0")
    assert layer["visible"] is False

    conflict = client.post(command_url, json={
        "base_revision": 1,
        "changes": {"Layer 0": True},
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "revision_conflict"


def test_presentation_command_updates_layers_and_objects_atomically(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = Path(__file__).parents[1] / "examples" / "arco-yanque.igz"
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    first_object = created["revisions"][0]["summary"]["outline"]["items"][0]
    visibility_id = first_object["visibility_id"]
    command_url = f"/api/v1/documents/{document_id}/commands/presentation"

    changed = client.post(command_url, json={
        "base_revision": 1,
        "layers": {"Layer 0": False},
        "hidden_objects": {visibility_id: True},
    })

    assert changed.status_code == 201
    record = changed.json()
    assert record["latest_revision"] == 2
    summary = record["revisions"][-1]["summary"]
    layer = next(item for item in summary["layer_details"]
                 if item["name"] == "Layer 0")
    changed_object = next(item for item in summary["outline"]["items"]
                          if item["visibility_id"] == visibility_id)
    assert layer["visible"] is False
    assert changed_object["hidden"] is True
    assert changed_object["name"] == first_object["name"]
    assert changed_object["native_id"] == first_object["native_id"]

    conflict = client.post(command_url, json={
        "base_revision": 1,
        "hidden_objects": {visibility_id: False},
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "revision_conflict"


def test_move_object_command_creates_native_geometry_revision(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    source = Path(__file__).parents[1] / "examples" / "arco-yanque.igz"
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    store = app.state.document_store
    before = load_igz(store.revision_path(document_id, 1))
    before_x = min(vertex.position.x()
                   for vertex in world_mesh(before.groups[0]).vertices)

    moved = client.post(
        f"/api/v1/documents/{document_id}/commands/move-object",
        json={
            "base_revision": 1,
            "object_id": "group:0",
            "delta": [1.25, -0.5, 0.75],
        },
    )

    assert moved.status_code == 201
    record = moved.json()
    assert record["latest_revision"] == 2
    assert record["revisions"][-1]["summary"]["outline"]["items"][0]["name"] == (
        created["revisions"][0]["summary"]["outline"]["items"][0]["name"]
    )
    after = load_igz(store.revision_path(document_id, 2))
    after_x = min(vertex.position.x()
                  for vertex in world_mesh(after.groups[0]).vertices)
    assert after_x == pytest.approx(before_x + 1.25)

    stale = client.post(
        f"/api/v1/documents/{document_id}/commands/move-object",
        json={"base_revision": 1, "object_id": "group:0", "delta": [1, 0, 0]},
    )
    assert stale.status_code == 409

    restored = client.post(
        f"/api/v1/documents/{document_id}/commands/restore-revision",
        json={"base_revision": 2, "source_revision": 1},
    )
    assert restored.status_code == 201
    assert restored.json()["latest_revision"] == 3
    restored_scene = load_igz(store.revision_path(document_id, 3))
    restored_x = min(vertex.position.x()
                     for vertex in world_mesh(restored_scene.groups[0]).vertices)
    assert restored_x == pytest.approx(before_x)
    restored_item = restored.json()["revisions"][-1]["summary"]["outline"]["items"][0]
    original_item = created["revisions"][0]["summary"]["outline"]["items"][0]
    assert restored_item["name"] == original_item["name"]
    assert restored_item["native_id"] == original_item["native_id"]


def test_rotate_and_scale_object_commands_use_native_geometry(tmp_path):
    source = tmp_path / "transform.igz"
    scene = Scene()
    group = Group(name="Panel")
    group.mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(2, 0, 0),
        QVector3D(2, 1, 0), QVector3D(0, 1, 0),
    ])
    scene.groups.append(group)
    save_scene(scene, source)
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    created = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    document_id = created["id"]
    url = f"/api/v1/documents/{document_id}/commands/transform-object"

    rotated = client.post(url, json={
        "base_revision": 1,
        "object_id": "group:0",
        "operation": "rotate",
        "axis": "z",
        "degrees": 90,
    })
    assert rotated.status_code == 201
    rotated_scene = load_igz(app.state.document_store.revision_path(document_id, 2))
    rotated_positions = [vertex.position
                         for vertex in world_mesh(rotated_scene.groups[0]).vertices]
    rotated_width = max(point.x() for point in rotated_positions) - min(
        point.x() for point in rotated_positions)
    rotated_height = max(point.y() for point in rotated_positions) - min(
        point.y() for point in rotated_positions)
    assert rotated_width == pytest.approx(1)
    assert rotated_height == pytest.approx(2)

    scaled = client.post(url, json={
        "base_revision": 2,
        "object_id": "group:0",
        "operation": "scale",
        "factors": [2, 0.5, 1],
    })
    assert scaled.status_code == 201
    scaled_scene = load_igz(app.state.document_store.revision_path(document_id, 3))
    scaled_positions = [vertex.position
                        for vertex in world_mesh(scaled_scene.groups[0]).vertices]
    scaled_width = max(point.x() for point in scaled_positions) - min(
        point.x() for point in scaled_positions)
    scaled_height = max(point.y() for point in scaled_positions) - min(
        point.y() for point in scaled_positions)
    assert scaled_width == pytest.approx(2)
    assert scaled_height == pytest.approx(1)

    lifecycle_url = f"/api/v1/documents/{document_id}/commands/object-lifecycle"
    duplicated = client.post(lifecycle_url, json={
        "base_revision": 3,
        "object_id": "group:0",
        "operation": "duplicate",
        "delta": [3, 0, 0],
    })
    assert duplicated.status_code == 201
    duplicate_summary = duplicated.json()["revisions"][-1]["summary"]
    assert duplicate_summary["placements"] == 2
    duplicate_items = duplicate_summary["outline"]["items"]
    assert duplicate_items[0]["name"] == duplicate_items[1]["name"] == "Panel"
    assert duplicate_items[0]["native_id"] != duplicate_items[1]["native_id"]

    renamed = client.post(lifecycle_url, json={
        "base_revision": 4,
        "object_id": "group:1",
        "operation": "rename",
        "name": "Panel copy",
    })
    assert renamed.status_code == 201
    assert renamed.json()["revisions"][-1]["summary"]["outline"]["items"][1]["name"] == "Panel copy"

    deleted = client.post(lifecycle_url, json={
        "base_revision": 5,
        "object_id": "group:0",
        "operation": "delete",
    })
    assert deleted.status_code == 201
    assert deleted.json()["revisions"][-1]["summary"]["placements"] == 1

    created_box = client.post(
        f"/api/v1/documents/{document_id}/commands/create-box",
        json={
            "base_revision": 6,
            "name": "New cabinet",
            "size": [2, 3, 4],
            "origin": [10, 20, 30],
        },
    )
    assert created_box.status_code == 201
    box_summary = created_box.json()["revisions"][-1]["summary"]
    assert box_summary["placements"] == 2
    box_item = box_summary["outline"]["items"][-1]
    assert box_item["name"] == "New cabinet"
    assert box_item["geometry"]["faces"] == 6
    box_scene = load_igz(app.state.document_store.revision_path(document_id, 7))
    box_positions = [vertex.position for vertex in world_mesh(box_scene.groups[-1]).vertices]
    assert max(point.x() for point in box_positions) - min(
        point.x() for point in box_positions) == pytest.approx(2)
    assert max(point.y() for point in box_positions) - min(
        point.y() for point in box_positions) == pytest.approx(3)
    assert max(point.z() for point in box_positions) - min(
        point.z() for point in box_positions) == pytest.approx(4)

    planar_url = f"/api/v1/documents/{document_id}/commands/create-planar"
    rectangle = client.post(planar_url, json={
        "base_revision": 7,
        "operation": "rectangle",
        "name": "Work plane",
        "origin": [1, 2, 3],
        "size": [5, 6],
        "plane": "xz",
    })
    assert rectangle.status_code == 201
    rectangle_item = rectangle.json()["revisions"][-1]["summary"]["outline"]["items"][-1]
    assert rectangle_item["name"] == "Work plane"
    assert rectangle_item["geometry"] == {"vertices": 4, "edges": 4, "faces": 1}
    rectangle_scene = load_igz(app.state.document_store.revision_path(document_id, 8))
    rectangle_points = [vertex.position
                        for vertex in world_mesh(rectangle_scene.groups[-1]).vertices]
    assert {point.y() for point in rectangle_points} == {2.0}
    assert max(point.z() for point in rectangle_points) - min(
        point.z() for point in rectangle_points) == pytest.approx(6)

    circle = client.post(planar_url, json={
        "base_revision": 8,
        "operation": "circle",
        "name": "Round slab",
        "origin": [0, 0, 2],
        "radius": 2,
        "segments": 32,
    })
    assert circle.status_code == 201
    circle_item = circle.json()["revisions"][-1]["summary"]["outline"]["items"][-1]
    assert circle_item["name"] == "Round slab"
    assert circle_item["geometry"] == {"vertices": 32, "edges": 32, "faces": 1}
    circle_scene = load_igz(app.state.document_store.revision_path(document_id, 9))
    circle_edges = world_mesh(circle_scene.groups[-1]).edges
    assert len({edge.curve for edge in circle_edges}) == 1
    assert circle_edges[0].curve is not None

    line = client.post(planar_url, json={
        "base_revision": 9,
        "operation": "line",
        "name": "Guide edge",
        "origin": [1, 2, 3],
        "end": [4, 6, 8],
    })
    assert line.status_code == 201
    line_item = line.json()["revisions"][-1]["summary"]["outline"]["items"][-1]
    assert line_item["name"] == "Guide edge"
    assert line_item["geometry"] == {"vertices": 2, "edges": 1, "faces": 0}

    arc = client.post(planar_url, json={
        "base_revision": 10,
        "operation": "arc",
        "name": "Entry arc",
        "origin": [3, 4, 5],
        "radius": 2,
        "start_degrees": 30,
        "sweep_degrees": 120,
        "segments": 8,
        "plane": "yz",
    })
    assert arc.status_code == 201
    arc_item = arc.json()["revisions"][-1]["summary"]["outline"]["items"][-1]
    assert arc_item["name"] == "Entry arc"
    assert arc_item["geometry"] == {"vertices": 9, "edges": 8, "faces": 0}
    arc_scene = load_igz(app.state.document_store.revision_path(document_id, 11))
    arc_edges = world_mesh(arc_scene.groups[-1]).edges
    assert len({edge.curve for edge in arc_edges}) == 1
    assert arc_edges[0].curve is not None
    assert {vertex.position.x() for vertex in world_mesh(
        arc_scene.groups[-1]).vertices} == {3.0}

    invalid_arc = client.post(planar_url, json={
        "base_revision": 11,
        "operation": "arc",
        "origin": [0, 0, 0],
        "radius": 1,
        "start_degrees": 0,
        "sweep_degrees": 360,
        "segments": 12,
    })
    assert invalid_arc.status_code == 422
    assert "less than 360" in invalid_arc.json()["detail"]["message"]

    pushed = client.post(
        f"/api/v1/documents/{document_id}/commands/push-pull",
        json={
            "base_revision": 11,
            "object_id": "group:1",
            "direction": "+z",
            "distance": 2,
        },
    )
    assert pushed.status_code == 201, pushed.text
    assert pushed.json()["command_result"] == {
        "distance": 2.0, "refused": False, "limited": False,
    }
    pushed_scene = load_igz(app.state.document_store.revision_path(document_id, 12))
    pushed_positions = [vertex.position
                        for vertex in world_mesh(pushed_scene.groups[1]).vertices]
    assert max(point.z() for point in pushed_positions) - min(
        point.z() for point in pushed_positions) == pytest.approx(6)
    assert len(world_mesh(pushed_scene.groups[1]).faces) == 6

    painted = client.post(
        f"/api/v1/documents/{document_id}/commands/object-material",
        json={
            "base_revision": 12,
            "object_id": "group:1",
            "color": [0.2, 0.4, 0.8],
            "opacity": 0.75,
        },
    )
    assert painted.status_code == 201, painted.text
    painted_item = painted.json()["revisions"][-1]["summary"]["outline"]["items"][1]
    assert painted_item["material"] == {
        "color": [0.2, 0.4, 0.8], "opacity": 0.75,
    }
    painted_scene = load_igz(app.state.document_store.revision_path(document_id, 13))
    assert painted_scene.groups[1].material == {
        "color": [0.2, 0.4, 0.8], "opacity": 0.75,
    }

    offset = client.post(
        f"/api/v1/documents/{document_id}/commands/offset-face",
        json={
            "base_revision": 13,
            "object_id": "group:2",
            "distance": 1,
        },
    )
    assert offset.status_code == 201, offset.text
    assert offset.json()["command_result"] == {"distance": 1.0, "regions": 1}
    offset_scene = load_igz(app.state.document_store.revision_path(document_id, 14))
    offset_mesh = world_mesh(offset_scene.groups[2])
    assert len(offset_mesh.faces) == 2
    assert sorted(len(face.holes) for face in offset_mesh.faces) == [0, 1]

from pathlib import Path
import base64
import json
import warnings
import zipfile

import pytest

from PySide6.QtGui import QVector3D

from core.scene import Scene
from formats.glb import parse_container
from web.backend.ingetrazo_web.scene_service import (
    inspect_igz,
    preview_igz,
    summarize_scene,
    validate_igz_container,
)
from formats.igz import save_scene


def _triangle_scene() -> Scene:
    scene = Scene()
    scene.mesh.add_face([
        QVector3D(0, 0, 0),
        QVector3D(2, 0, 0),
        QVector3D(0, 3, 0),
    ])
    return scene


def test_summary_is_json_safe_and_reports_bounds():
    summary = summarize_scene(_triangle_scene())

    assert summary["schema"] == "ingetrazo.scene-summary.v1"
    assert summary["bounds"] == {
        "min": [0.0, 0.0, 0.0],
        "max": [2.0, 3.0, 0.0],
    }
    assert summary["unique_geometry"]["faces"] == 1
    assert summary["placements"] == 0
    assert summary["dimension_details"] == []
    assert summary["text_label_details"] == []
    assert summary["guide_details"] == []
    assert summary["camera"] is None
    assert summary["layer_details"] == [
        {"name": "Layer 0", "visible": True, "locked": False}
    ]


def test_inspection_includes_saved_camera_and_bounded_outline(tmp_path):
    from core.group import Group
    from core.saved_views import SavedView
    from core.section import SectionPlane

    scene = _triangle_scene()
    group = Group(name="Roof")
    group.mesh.add_face([
        QVector3D(0, 0, 1), QVector3D(1, 0, 1), QVector3D(0, 1, 1),
    ])
    scene.groups.append(group)
    scene.camera_home = {
        "target": [1, 2, 3], "distance": 12, "yaw": 0.2, "pitch": 0.4,
        "fov_deg": 50, "perspective": False,
    }
    section = SectionPlane(QVector3D(0, 0, 1), QVector3D(0, 0, 1),
                           name="Roof cut", symbol="A", active=True)
    scene.section_planes.append(section)
    scene.saved_views.append(SavedView(
        "Plan", target=(4, 5, 6), distance=30, yaw=0.5, pitch=1.2,
        perspective=False, hidden_layers=["Furniture"],
        section={"active": section.uid, "cuts_shown": True},
        hidden_objects=[group.uid],
    ))
    source = tmp_path / "semantic.igz"
    save_scene(scene, source)

    summary = inspect_igz(source)

    assert summary["camera"]["target"] == [1.0, 2.0, 3.0]
    assert summary["camera"]["perspective"] is False
    assert summary["saved_view_details"][0]["name"] == "Plan"
    assert summary["saved_view_details"][0]["target"] == [4.0, 5.0, 6.0]
    assert summary["saved_view_details"][0]["hidden_layers"] == ["Furniture"]
    assert summary["saved_view_details"][0]["section"]["active"] == section.uid
    assert summary["saved_view_details"][0]["hidden_objects"] == [group.uid]
    assert summary["saved_view_details"][0]["hidden_object_visibility_ids"] == ["group:0"]
    assert summary["section_details"] == [{
        "id": section.uid,
        "name": "Roof cut",
        "symbol": "A",
        "point": [0.0, 0.0, 1.0],
        "normal": [0.0, 0.0, 1.0],
        "active": True,
    }]
    assert summary["section_cuts_visible"] is True
    assert summary["section_planes_visible"] is True
    assert summary["outline"]["items"][0]["name"] == "Roof"
    assert summary["outline"]["items"][0]["geometry"]["faces"] == 1


def test_nested_outline_points_to_top_level_preview_node():
    from core.group import Group

    scene = Scene()
    parent = Group(name="Building")
    child = Group(name="Window")
    parent.children.append(child)
    scene.groups.append(parent)

    outline = summarize_scene(scene, include_outline=True)["outline"]["items"]

    assert outline[0]["id"] == "group:0"
    assert outline[0]["preview_id"] == "group:0"
    assert outline[0]["children"][0]["id"] == "group:0/0"
    assert outline[0]["children"][0]["preview_id"] == "group:0"


def test_web_preview_keeps_top_level_objects_as_semantic_glb_nodes(tmp_path):
    from core.group import Group

    scene = _triangle_scene()
    group = Group(name="Roof")
    group.layer = "Structure"
    group.mesh.add_face([
        QVector3D(0, 0, 1), QVector3D(1, 0, 1), QVector3D(0, 1, 1),
    ])
    scene.groups.append(group)
    source = tmp_path / "semantic.igz"
    target = tmp_path / "semantic.glb"
    save_scene(scene, source)

    preview_igz(source, target)
    gltf, _buffers = parse_container(target)
    semantic = [node.get("extras", {}).get("ingetrazo_object")
                for node in gltf["nodes"]]

    assert {item["id"] for item in semantic} == {"loose:Layer 0", "group:0"}
    roof = next(item for item in semantic if item["id"] == "group:0")
    assert roof == {
        "id": "group:0",
        "visibility_id": "group:0",
        "native_id": group.uid,
        "name": "Roof",
        "kind": "group",
        "layer": "Structure",
        "visible": True,
        "layer_visible": True,
        "locked": False,
        "hidden": False,
    }


def test_web_preview_contains_hidden_layer_as_hidden_semantic_node(tmp_path):
    from core.group import Group
    from core.layers import Layer

    scene = Scene()
    scene.layers.append(Layer("Furniture", visible=False))
    chair = Group(name="Chair")
    chair.layer = "Furniture"
    chair.mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 0),
    ])
    scene.groups.append(chair)
    source = tmp_path / "layers.igz"
    target = tmp_path / "layers.glb"
    save_scene(scene, source)

    preview_igz(source, target)
    gltf, _buffers = parse_container(target)
    semantic = gltf["nodes"][0]["extras"]["ingetrazo_object"]

    assert semantic["name"] == "Chair"
    assert semantic["id"] == "group:0"
    assert semantic["layer"] == "Furniture"
    assert semantic["visible"] is False
    assert semantic["layer_visible"] is False


def test_web_preview_carries_free_group_edges_as_line_primitives(tmp_path):
    from core.group import Group

    scene = Scene()
    group = Group(name="Line")
    group.mesh.add_edge(QVector3D(1, 2, 3), QVector3D(4, 6, 8))
    scene.groups.append(group)
    source = tmp_path / "line.igz"
    target = tmp_path / "line.glb"
    save_scene(scene, source)

    preview_igz(source, target)
    gltf, _buffers = parse_container(target)

    assert gltf["nodes"][0]["extras"]["ingetrazo_object"]["id"] == "group:0"
    primitive = gltf["meshes"][0]["primitives"][0]
    assert primitive["mode"] == 1
    position = gltf["accessors"][primitive["attributes"]["POSITION"]]
    assert position["count"] == 2


def test_web_preview_applies_group_material_to_default_faces(tmp_path):
    from core.group import Group

    scene = Scene()
    group = Group(name="Painted box")
    group.material = {"color": [0.2, 0.4, 0.8], "opacity": 0.75}
    group.mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 0),
    ])
    scene.groups.append(group)
    source = tmp_path / "painted.igz"
    target = tmp_path / "painted.glb"
    save_scene(scene, source)

    summary = inspect_igz(source)
    preview_igz(source, target)
    gltf, _buffers = parse_container(target)

    assert summary["outline"]["items"][0]["material"] == group.material
    semantic = gltf["nodes"][0]["extras"]["ingetrazo_object"]
    assert semantic["material"] == group.material
    material = gltf["materials"][0]
    assert material["pbrMetallicRoughness"]["baseColorFactor"] == [
        0.2, 0.4, 0.8, 0.75,
    ]
    assert material["alphaMode"] == "BLEND"


def test_web_preview_keeps_hidden_object_for_scene_recall(tmp_path):
    from core.group import Group

    scene = Scene()
    hidden = Group(name="Hidden chair")
    hidden.hidden = True
    hidden.mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 0),
    ])
    scene.groups.append(hidden)
    source = tmp_path / "hidden.igz"
    target = tmp_path / "hidden.glb"
    save_scene(scene, source)

    preview_igz(source, target)
    gltf, _buffers = parse_container(target)
    semantic = gltf["nodes"][0]["extras"]["ingetrazo_object"]

    assert semantic["native_id"] == hidden.uid
    assert semantic["hidden"] is True
    assert semantic["visible"] is False


def test_web_preview_embeds_reference_image_as_semantic_quad(tmp_path):
    from core.image_plane import ImagePlane

    # Valid 1×1 transparent PNG; the native document packer and GLB exporter
    # both exercise their real embedded-image paths.
    image = tmp_path / "plan.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHnOcQAAAAABJRU5ErkJggg=="
    ))
    scene = Scene()
    scene.image_planes.append(ImagePlane(
        str(image), QVector3D(1, 2, 0), QVector3D(4, 0, 0),
        QVector3D(0, 3, 0), name="Ground plan", opacity=0.6,
    ))
    source = tmp_path / "reference.igz"
    target = tmp_path / "reference.glb"
    save_scene(scene, source)

    summary = preview_igz(source, target)
    gltf, buffers = parse_container(target)
    semantic = gltf["nodes"][0]["extras"]["ingetrazo_object"]

    assert summary["reference_images"] == 1
    assert summary["reference_image_details"][0]["name"] == "Ground plan"
    assert summary["reference_image_details"][0]["width"] == 4.0
    assert semantic["id"] == "image:0"
    assert semantic["kind"] == "reference-image"
    assert semantic["locked"] is False
    assert gltf["images"][0]["mimeType"] == "image/png"
    assert gltf["materials"][0]["alphaMode"] == "BLEND"
    assert buffers[0]


def test_native_document_can_be_inspected_and_previewed(tmp_path):
    source = tmp_path / "triangle.igz"
    target = tmp_path / "triangle.glb"
    save_scene(_triangle_scene(), source)

    summary = inspect_igz(source)
    preview_summary = preview_igz(source, target)
    gltf, buffers = parse_container(target)

    outline = summary.pop("outline")
    assert outline == {"items": [], "truncated": False, "limit": 500}
    assert summary == preview_summary
    assert target.read_bytes().startswith(b"glTF")
    assert gltf["asset"]["version"] == "2.0"
    assert gltf["meshes"][0]["primitives"]
    assert buffers[0]


def test_upstream_example_loads_headlessly(tmp_path):
    source = Path(__file__).parents[1] / "examples" / "arco-yanque.igz"
    target = tmp_path / "arco-yanque.glb"

    summary = preview_igz(source, target)

    assert summary["unique_geometry"]["faces"] > 0
    assert target.stat().st_size > 100


def test_container_validation_rejects_non_documents(tmp_path):
    source = tmp_path / "not-a-document.igz"
    source.write_text(json.dumps({"hello": "world"}))

    try:
        validate_igz_container(source)
    except ValueError as exc:
        assert "scene" in str(exc)
    else:
        raise AssertionError("invalid document was accepted")


def test_container_validation_rejects_unsafe_archive_paths(tmp_path):
    source = tmp_path / "unsafe.igz"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("document.json", '{"scene": {}}')
        archive.writestr("../outside.png", b"not really an image")

    try:
        validate_igz_container(source)
    except ValueError as exc:
        assert "unsafe path" in str(exc)
    else:
        raise AssertionError("unsafe archive was accepted")


def test_container_validation_rejects_windows_style_traversal(tmp_path):
    source = tmp_path / "unsafe-windows.igz"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("document.json", '{"scene": {}}')
        archive.writestr("..\\outside.png", b"not really an image")

    try:
        validate_igz_container(source)
    except ValueError as exc:
        assert "unsafe path" in str(exc)
    else:
        raise AssertionError("Windows-style traversal was accepted")


def test_container_validation_rejects_extreme_compression_ratio(tmp_path):
    source = tmp_path / "compression-bomb.igz"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.json", '{"scene": {}}')
        archive.writestr("textures/bomb.png", b"0" * (2 * 1024 * 1024))

    try:
        validate_igz_container(source)
    except ValueError as exc:
        assert "compression ratio" in str(exc)
    else:
        raise AssertionError("extreme compression ratio was accepted")


def test_container_validation_rejects_duplicate_entries(tmp_path):
    source = tmp_path / "duplicate.igz"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("document.json", '{"scene": {}}')
            archive.writestr("document.json", '{"scene": {"other": true}}')

    try:
        validate_igz_container(source)
    except ValueError as exc:
        assert "duplicate entries" in str(exc)
    else:
        raise AssertionError("duplicate archive entry was accepted")


def test_legacy_groups_without_stored_uids_get_the_same_ids_on_every_load(tmp_path):
    import json
    import zipfile
    from core.group import Group
    from web.backend.ingetrazo_web.scene_service import inspect_igz, load_igz

    scene = Scene()
    def solid(name):
        group = Group(name=name)    # an empty group is not written out
        group.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                             QVector3D(0, 1, 0)])
        return group

    parent = solid("Parent")
    parent.adopt([solid("Child")])
    scene.groups.append(parent)
    scene.groups.append(solid("Second"))
    stored = tmp_path / "stored.igz"
    save_scene(scene, stored)
    legacy = tmp_path / "legacy.igz"
    payload = json.loads(stored.read_bytes())   # small documents are plain JSON

    def strip(raw):
        raw.pop("uid", None)
        for child in raw.get("children", []):
            strip(child)
    for raw in payload["scene"]["groups"]:
        strip(raw)
    legacy.write_text(json.dumps(payload))

    def uids(path):
        loaded = load_igz(path)
        return [loaded.groups[0].uid, loaded.groups[0].children[0].uid,
                loaded.groups[1].uid]

    first, second = uids(legacy), uids(legacy)
    assert first == second
    assert len(set(first)) == 3
    assert inspect_igz(legacy)["outline"]["items"][0]["native_id"] == first[0]
    # A document that stores uids keeps them.
    assert uids(stored) == [scene.groups[0].uid, scene.groups[0].children[0].uid,
                            scene.groups[1].uid]


def test_face_me_figures_are_exported_as_turnable_nodes(tmp_path):
    import struct
    from core.group import Group, make_billboard_group
    from web.backend.ingetrazo_web.scene_service import preview_igz

    image = Path(__file__).resolve().parents[1] / "resources" / "components" / "sumari.png"
    scene = Scene()
    person = make_billboard_group(str(image), 1.7, "Person", 0.4, QVector3D(2, 3, 0))
    cutout = make_billboard_group(str(image), 1.0, "Cutout", 1.0, QVector3D(-4, 0, 1))
    cutout.billboard = "mesh"
    holder = Group(name="Holder")                      # a figure nested in a group with a wall
    holder.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 0, 1), QVector3D(0, 0, 1)])
    nested = make_billboard_group(str(image), 1.2, "Nested", 0.5, QVector3D(0, 5, 0))
    holder.adopt([nested])
    scene.groups.extend([person, cutout, holder])
    source = tmp_path / "figures.igz"
    save_scene(scene, source)
    target = tmp_path / "figures.glb"
    preview_igz(source, target)

    data = target.read_bytes()
    gltf = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
    figures = [n["extras"]["ingetrazo_object"] for n in gltf["nodes"]
               if "faceme" in n["extras"]["ingetrazo_object"]]
    by_name = {f["name"]: f["faceme"] for f in figures}
    assert set(by_name) == {"Person", "Cutout", "Nested"}
    assert by_name["Person"]["kind"] == "quad"
    assert by_name["Person"]["feet"][:2] == pytest.approx([2, 3])
    assert by_name["Person"]["width"] == pytest.approx(0.68) and by_name["Person"]["height"] == pytest.approx(1.7)
    assert by_name["Cutout"]["kind"] == "mesh" and "heading" in by_name["Cutout"]
    # the wall of the group that holds a figure stays an ordinary, static part
    statics = [n for n in gltf["nodes"] if n["name"] == "Holder" and "faceme" not in n["extras"]["ingetrazo_object"]]
    assert len(statics) == 1


def test_nested_objects_are_separate_nodes_with_inherited_state(tmp_path):
    import struct
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from web.backend.ingetrazo_web.scene_service import preview_igz

    def solid(name, x):
        group = Group(name=name)
        group.mesh.add_face([QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0), QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)])
        return group

    scene = Scene()
    parent = Group(name="Parent")                 # a container with no geometry of its own
    painted = solid("Painted", 0)
    own = solid("Own", 3)
    own.material = {"color": [0, 0, 1]}
    parent.adopt([painted, own])
    shift = QMatrix4x4()
    shift.translate(10, 0, 0)
    parent.xform = shift
    parent.material = {"color": [1, 0, 0]}
    parent.hidden = True
    scene.groups.extend([parent, solid("Loner", 20)])
    source = tmp_path / "nested.igz"
    save_scene(scene, source)
    target = tmp_path / "nested.glb"
    preview_igz(source, target)

    data = target.read_bytes()
    gltf = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
    parts = {n["extras"]["ingetrazo_object"]["id"]: n["extras"]["ingetrazo_object"] for n in gltf["nodes"]}
    assert set(parts) == {"group:0/0", "group:0/1", "group:1"}          # the empty container has no node
    assert parts["group:0/0"]["name"] == "Painted" and parts["group:0/1"]["name"] == "Own"
    assert parts["group:0/0"]["hidden"] is True and parts["group:0/0"]["visible"] is False   # a hidden ancestor hides it
    assert parts["group:1"]["hidden"] is False
    assert parts["group:0/0"]["material"] == {"color": [1, 0, 0]}               # no paint of its own: the parent's
    assert parts["group:0/1"]["material"] == {"color": [0, 0, 1]}               # its own paint wins
    # the parent's placement carries into the children's world positions
    mesh = gltf["meshes"][next(n["mesh"] for n in gltf["nodes"] if n["extras"]["ingetrazo_object"]["id"] == "group:0/0")]
    accessor = gltf["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
    assert accessor["min"][0] == pytest.approx(10) and accessor["max"][0] == pytest.approx(11)

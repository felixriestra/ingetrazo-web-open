"""Modeling commands that wrap the desktop tools without a web form of their own."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402

from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.scene_service import load_igz  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats.igz import save_scene  # noqa: E402


@pytest.fixture()
def api(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = tmp_path / "empty.igz"
    save_scene(Scene(), source)
    record = client.post(
        "/api/v1/documents",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
    ).json()
    state = {"id": record["id"], "revision": record["latest_revision"], "store": client.app.state.document_store}

    def command(endpoint, **body):
        response = client.post(
            f"/api/v1/documents/{state['id']}/commands/{endpoint}",
            json={"base_revision": state["revision"], **body},
        )
        if response.status_code == 201:
            state["revision"] = response.json()["latest_revision"]
        return response

    def scene():
        return load_igz(state["store"].revision_path(state["id"], state["revision"]))

    command.scene = scene
    command.client = client
    command.state = state
    return command


def box(api, name="Box", origin=(0, 0, 0), size=(1, 1, 1)):
    assert api("create-box", name=name, origin=list(origin), size=list(size)).status_code == 201
    return f"group:{len(api.scene().groups) - 1}"


@pytest.mark.parametrize("operation,extra,faces,edges", [
    ("polygon", {"sides": 6, "radius": 2}, 1, 6),
    ("rotated_rectangle", {"width": 2, "depth": 1, "angle_degrees": 30}, 1, 4),
    ("pie", {"radius": 1, "sweep_degrees": 90, "segments": 8}, 1, 10),
    ("freehand", {"points": [[0, 0], [1, 0], [1, 1], [0, 1]], "closed": True}, 1, 4),
    ("freehand", {"points": [[0, 0], [1, 0], [1, 1]]}, 0, 2),
])
def test_shapes_create_a_new_group(api, operation, extra, faces, edges):
    response = api("create-shape", operation=operation, **extra)
    assert response.status_code == 201, response.text
    group = api.scene().groups[-1]
    assert len(group.mesh.faces) == faces
    assert len(group.mesh.edges) == edges


def test_arcs_through_points(api):
    assert api("create-shape", operation="arc3", start=[1, 0], through=[0, 1], end=[-1, 0]).status_code == 201
    group = api.scene().groups[-1]
    assert len(group.mesh.edges) == 12
    radii = {round((v.position.x() ** 2 + v.position.y() ** 2) ** 0.5, 6) for v in group.mesh.vertices}
    assert radii == {1.0}
    assert api("create-shape", operation="arc2", start=[0, 0], end=[2, 0], bulge=0.5).status_code == 201
    assert api("create-shape", operation="arc3", start=[0, 0], through=[1, 0], end=[2, 0]).status_code == 422


def test_shape_validation(api):
    assert api("create-shape", operation="spiral").status_code == 422
    assert api("create-shape", operation="polygon", sides=2, radius=1).status_code == 422
    assert api("create-shape", operation="polygon", sides=5, radius=-1).status_code == 422


def test_flip_mirrors_in_place_or_copies(api):
    target = box(api, origin=(1, 0, 0))
    assert api("flip-object", object_id=target, axis="x").status_code == 201
    flipped = api.scene().groups[0]
    xs = sorted({round(v.position.x(), 6) for v in flipped.mesh.vertices})
    assert xs == [1.0, 2.0]          # mirrored about its own centre: extent unchanged
    from core import solids
    assert solids.is_solid(flipped)                    # faces still point outward
    assert api("flip-object", object_id="group:0", axis="z", copy=True).status_code == 201
    assert len(api.scene().groups) == 2
    assert api("flip-object", object_id="group:0", axis="w").status_code == 422


def test_solid_operations_on_two_boxes(api):
    a = box(api, "A", (0, 0, 0), (2, 2, 2))
    b = box(api, "B", (1, 1, 1), (2, 2, 2))
    response = api("solid-operation", operation="union", object_ids=[a, b])
    assert response.status_code == 201, response.text
    assert len(api.scene().groups) == 1
    assert api("solid-operation", operation="union", object_ids=["group:0", "group:0"]).status_code == 422


def test_solid_subtract_reports_a_miss(api):
    a = box(api, "A", (0, 0, 0))
    b = box(api, "B", (10, 10, 10))
    response = api("solid-operation", operation="subtract", object_ids=[a, b])
    assert response.status_code == 422
    assert "failed" in response.text


def test_fillet_rounds_an_edge(api):
    target = box(api)
    group = api.scene().groups[0]
    edge = next(e for e in group.mesh.edges if len(e.faces) == 2)
    edges = [{"a": [edge.a.x(), edge.a.y(), edge.a.z()], "b": [edge.b.x(), edge.b.y(), edge.b.z()]}]
    faces_before = len(group.mesh.faces)
    response = api("fillet", object_id=target, edges=edges, radius=0.1, segments=4)
    assert response.status_code == 201, response.text
    assert len(api.scene().groups[0].mesh.faces) > faces_before
    second = box(api, "Second", (5, 0, 0))
    sharp = api("fillet", object_id=second, edges="sharp", radius=0.1, segments=2)
    assert sharp.status_code == 201, sharp.text
    missing = [{"a": [9, 9, 9], "b": [8, 8, 8]}]
    assert api("fillet", object_id="group:0", edges=missing, radius=0.1).status_code == 422


def test_follow_me_sweeps_a_profile_along_a_path(api):
    assert api("create-shape", operation="polygon", sides=4, radius=0.1, plane="xy").status_code == 201
    response = api("follow-me", object_id="group:0", path=[[0, 0, 0], [0, 0, 2], [0, 0, 4]])
    assert response.status_code == 201, response.text
    assert len(api.scene().groups[0].mesh.faces) > 1
    assert api("follow-me", object_id="group:0", path=[[0, 0, 0]]).status_code == 422


def test_text3d_and_section_fill(api):
    response = api("create-text3d", text="Hi", height=0.3, thickness=0.05, origin=[1, 2, 0])
    assert response.status_code == 201, response.text
    letters = api.scene().groups[-1]
    assert letters.name == "Hi" and len(letters.children) == 2
    assert api("create-text3d", text="   ").status_code == 422
    assert api("section-fill", enabled=False).status_code == 201
    assert api.scene().display_style.section_fill is False
    assert api("section-fill", enabled="no").status_code == 422


def test_push_pull_acts_on_the_clicked_face(api):
    a = box(api, "Step", (0, 0, 0), (2, 2, 1))
    assert api("push-pull", object_id=a, direction="+z", distance=1, face_point=[1, 1, 1]).status_code == 201
    group = api.scene().groups[0]
    zs = sorted({round(v.position.z(), 6) for v in group.mesh.vertices})
    assert zs == [0.0, 2.0]
    assert api("push-pull", object_id="group:0", direction="+z", distance=1, face_point=[1, "x", 1]).status_code == 422


def test_library_listings_and_safe_paths(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    components = client.get("/api/v1/library/components").json()["components"]
    assert any(c["key"] == "sofa" for c in components)
    assert client.get("/api/v1/library/components/sofa/thumb").status_code == 200
    assert client.get("/api/v1/library/components/nope/thumb").status_code == 404
    categories = client.get("/api/v1/library/materials").json()["categories"]
    first = next(item for category in categories for item in category["items"])
    assert client.get(f"/api/v1/library/materials/file/{first['file']}").status_code == 200
    assert client.get("/api/v1/library/materials/file/../library.json").status_code == 404
    assert client.get("/api/v1/library/materials/file/%2e%2e/library.json").status_code == 404


def test_insert_component_sits_on_the_origin(api):
    assert api("insert-component", component="banco", origin=[5, 6, 0]).status_code == 201
    group = api.scene().groups[-1]
    from core.group import world_mesh
    zs = [v.position.z() for v in world_mesh(group).vertices]
    xs = [v.position.x() for v in world_mesh(group).vertices]
    assert abs(min(zs)) < 1e-4
    assert abs((min(xs) + max(xs)) / 2 - 5) < 1e-3
    assert api("insert-component", component="nope").status_code == 404


def test_texture_material_is_saved_with_the_group(api):
    target = box(api)
    from web.backend.ingetrazo_web import library
    item = library.texture_index()[0]["items"][0]
    response = api("object-material", object_id=target, texture=item["file"])
    assert response.status_code == 201, response.text
    material = api.scene().groups[0].material
    assert material["mat"] == item["name"] and material["texture"]["path"].endswith(item["file"].split("/")[-1])
    assert api("object-material", object_id="group:0", texture="../library.json").status_code == 404


def test_layers_sections_and_scenes(api):
    target = box(api)
    assert api("create-layer", name="Walls").status_code == 201
    assert api("create-layer", name="Walls").status_code == 422
    assert api("assign-layer", object_id=target, layer="Walls").status_code == 201
    assert api.scene().groups[0].layer == "Walls"
    assert api("assign-layer", object_id=target, layer="Brand new").status_code == 201
    assert api.scene().layer("Brand new") is not None

    assert api("create-section", point=[0, 0, 0.5], normal=[0, 0, 1]).status_code == 201
    planes = api.scene().section_planes
    assert len(planes) == 1 and abs(planes[0].normal.z() - 1) < 1e-6
    assert api("create-section", point=[0, 0, 0], normal=[0, 0, 0]).status_code == 422

    saved = api("save-scene", name="Plan", eye=[5, 5, 5], target=[0, 0, 0], fov_deg=45)
    assert saved.status_code == 201, saved.text
    view = api.scene().saved_views[0]
    assert view.name == "Plan" and abs(view.distance - 75 ** 0.5) < 1e-6
    assert api("save-scene", name="Plan", eye=[5, 5, 5], target=[0, 0, 0]).status_code == 422
    assert api("save-scene", name="Same", eye=[1, 1, 1], target=[1, 1, 1]).status_code == 422
    assert api("delete-scene", name="Plan").status_code == 201
    assert api.scene().saved_views == []
    assert api("delete-scene", name="Plan").status_code == 422


def _nested_document(tmp_path):
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    scene = Scene()
    parent = Group(name="Parent")
    child = Group(name="Child")
    for corners in ([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],):
        child.mesh.add_face([QVector3D(*c) for c in corners])
    parent.adopt([child])
    turn = QMatrix4x4()
    turn.translate(5, 0, 0)
    turn.rotate(90, 0, 0, 1)            # the parent frame is turned in the world
    parent.xform = turn
    scene.groups.append(parent)
    source = tmp_path / "nested.igz"
    save_scene(scene, source)
    return source


def test_nested_objects_can_be_moved_renamed_and_deleted(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = _nested_document(tmp_path)
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    state = {"rev": record["latest_revision"]}

    def post(endpoint, **body):
        response = client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                               json={"base_revision": state["rev"], **body})
        if response.status_code == 201:
            state["rev"] = response.json()["latest_revision"]
        return response

    def world_extent():
        from core.group import world_mesh
        scene = load_igz(client.app.state.document_store.revision_path(record["id"], state["rev"]))
        points = [v.position for v in world_mesh(scene.groups[0]).vertices]
        return [min(p.x() for p in points), min(p.y() for p in points)]

    before = world_extent()
    assert post("move-object", object_id="group:0/0", delta=[2, 0, 0]).status_code == 201
    after = world_extent()
    assert abs(after[0] - before[0] - 2) < 1e-4 and abs(after[1] - before[1]) < 1e-4   # a world-space move
    assert post("object-lifecycle", object_id="group:0/0", operation="rename", name="Renamed").status_code == 201
    assert post("object-lifecycle", object_id="group:0/0", operation="duplicate").status_code == 422
    assert post("object-lifecycle", object_id="group:0/0", operation="delete").status_code == 201
    assert load_igz(client.app.state.document_store.revision_path(record["id"], state["rev"])).groups[0].children == []
    assert post("move-object", object_id="group:0/x", delta=[1, 0, 0]).status_code == 422


def _loose_document(tmp_path):
    scene = Scene()
    p = [QVector3D(a, b, c) for a, b, c in
         [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]]
    for loop in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]):
        scene.mesh.add_face([p[i] for i in loop])
    scene.mesh.add_face([QVector3D(5, 5, 0), QVector3D(6, 5, 0), QVector3D(6, 6, 0), QVector3D(5, 6, 0)])
    scene.mesh.add_edge(QVector3D(10, 0, 0), QVector3D(10, 3, 0))        # a free loose edge
    source = tmp_path / "loose.igz"
    save_scene(scene, source)
    return source


@pytest.fixture()
def loose(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = _loose_document(tmp_path)
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    state = {"rev": record["latest_revision"]}
    store = client.app.state.document_store

    def post(endpoint, **body):
        response = client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                               json={"base_revision": state["rev"], **body})
        if response.status_code == 201:
            state["rev"] = response.json()["latest_revision"]
        return response

    post.scene = lambda: load_igz(store.revision_path(record["id"], state["rev"]))
    post.client, post.record, post.state = client, record, state
    return post


def test_preview_tags_loose_triangles_with_their_face(loose):
    import json
    import struct
    path = loose.client.app.state.document_store.preview_path(loose.record["id"], loose.state["rev"])
    data = path.read_bytes()
    gltf = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
    node = next(n for n in gltf["nodes"] if n["extras"]["ingetrazo_object"]["kind"] == "loose")
    assert "face_ids" not in node["extras"]["ingetrazo_object"]
    tags = [t for primitive in gltf["meshes"][node["mesh"]]["primitives"]
            if primitive.get("mode") != 1 for t in primitive["extras"]["ingetrazo_faces"]]
    assert any(p.get("mode") == 1 for p in gltf["meshes"][node["mesh"]]["primitives"])   # the free edge
    assert sorted(set(tags)) == list(range(7))          # six cube faces + the loose square
    assert len(tags) == 12 + 2                           # two triangles per quad


def test_loose_faces_push_pull_erase_paint_and_group(loose):
    faces = list(loose.scene().mesh.faces)
    square = next(i for i, f in enumerate(faces) if abs(f.centroid().x() - 5.5) < 1e-6)
    assert loose("loose-push-pull", face_index=square, distance=2).status_code == 201
    assert len(loose.scene().mesh.faces) == 6 + 6        # the square became a closed box
    assert loose("loose-push-pull", face_index=10_000, distance=1).status_code == 422
    assert loose("loose-push-pull", face_index=0, distance=0).status_code == 422

    assert loose("loose-paint", face_indices=[0, 1], color=[1, 0, 0]).status_code == 201
    painted = [f for f in loose.scene().mesh.faces if f.attrs.get("color")]
    assert len(painted) == 2
    assert loose("loose-paint", face_indices=[0], color=[2, 0, 0]).status_code == 422

    count = len(loose.scene().mesh.faces)
    assert loose("loose-erase", face_indices=[0]).status_code == 201
    assert len(loose.scene().mesh.faces) == count - 1

    assert loose("loose-group", face_indices=[1], connected=True, name="Cube").status_code == 201
    scene = loose.scene()
    assert [g.name for g in scene.groups] == ["Cube"]
    assert len(scene.groups[0].mesh.faces) >= 5


def test_loose_faces_and_edges_move_and_edges_erase(loose):
    faces = list(loose.scene().mesh.faces)
    square = next(i for i, f in enumerate(faces) if abs(f.centroid().x() - 5.5) < 1e-6)
    assert loose("loose-move", face_indices=[square], delta=[0, 0, 2]).status_code == 201
    moved = list(loose.scene().mesh.faces)[square]
    assert abs(moved.centroid().z() - 2) < 1e-6
    assert loose("loose-move", face_indices=[square], delta=[0, 0, 0]).status_code == 422
    assert loose("loose-move", delta=[1, 0, 0]).status_code == 422

    assert loose("loose-move", edges=[[[10, 0, 0], [10, 3, 0]]], delta=[1, 0, 0]).status_code == 201
    free = [e for e in loose.scene().mesh.edges if not e.faces]
    assert len(free) == 1 and abs(free[0].a.x() - 11) < 1e-6
    assert loose("loose-edge-erase", edges=[[[0, 0, 0], [9, 9, 9]]]).status_code == 422
    assert loose("loose-edge-erase", edges=[[[11, 3, 0], [11, 0, 0]]]).status_code == 201
    assert not [e for e in loose.scene().mesh.edges if not e.faces]


def test_loose_connected_walks_shared_vertices(loose):
    response = loose.client.get(
        f"/api/v1/documents/{loose.record['id']}/revisions/{loose.state['rev']}/loose-connected",
        params={"face": 0})
    assert response.status_code == 200
    assert len(response.json()["faces"]) == 6
    assert loose.client.get(
        f"/api/v1/documents/{loose.record['id']}/revisions/{loose.state['rev']}/loose-connected",
        params={"face": 99}).status_code == 422


def test_commands_accept_lists_of_objects(api):
    a = box(api, "A", (0, 0, 0))
    b = box(api, "B", (3, 0, 0))
    c = box(api, "C", (6, 0, 0))
    assert api("move-object", object_ids=[a, c], delta=[0, 5, 0]).status_code == 201
    scene = api.scene()
    ys = [min(v.position.y() for v in g.mesh.vertices) for g in scene.groups]
    assert ys == [5.0, 0.0, 5.0]
    assert api("object-material", object_ids=[a, b], color=[0, 1, 0]).status_code == 201
    assert api("object-lifecycle", object_ids=[a, c], operation="delete").status_code == 201
    assert [g.name for g in api.scene().groups] == ["B"]
    assert api("object-lifecycle", object_ids=["group:0"], operation="rename", name="x").status_code == 422
    assert api("move-object", object_ids=[], delta=[1, 0, 0]).status_code == 422
    assert api("move-object", object_ids=["group:0", "group:0"], delta=[1, 0, 0]).status_code == 422


def test_scale_figures_are_listed_filed_under_people_and_placeable(api, tmp_path):
    from web.backend.ingetrazo_web import library
    from web.backend.ingetrazo_web.app import create_app

    client = TestClient(create_app(tmp_path / "lib"))
    entries = client.get("/api/v1/library/components").json()["components"]
    people = [e for e in entries if e["kind"] == "person"]
    assert {e["key"] for e in people} >= {"sumari", "ingeniero"}
    assert all(e["item"].startswith("person:") and e["default_path"] == ["People"] for e in people)
    thumb = client.get(people[0]["thumb_url"])
    assert thumb.status_code == 200 and thumb.content[:8] == b"\x89PNG\r\n\x1a\n" and len(thumb.content) < 100_000
    tree = client.get("/api/v1/library/taxonomy").json()
    people_node = next(n["id"] for n in tree["nodes"] if n["name"] == "People")
    assert people_node in tree["items"]["person:sumari"]
    assert client.get("/api/v1/library/people/nobody/thumb").status_code == 404

    assert api("insert-person", person="sumari", origin=[3, 4, 0.5]).status_code == 201
    group = api.scene().groups[-1]
    assert group.billboard is True and group.name == "Sumari"
    zs = [v.position.z() for v in group.mesh.vertices]
    assert min(zs) == pytest.approx(0.5) and max(zs) - min(zs) == pytest.approx(1.68)
    assert api("insert-person", person="nobody").status_code == 404
    assert library.person_aspect("sumari") == pytest.approx(385 / 1100, rel=1e-3)


def _turned_parent_document(tmp_path, uneven=False):
    """A parent placement turned 90 degrees about Z, holding a 2 x 1 x 1 solid box."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    scene = Scene()
    parent = Group(name="Parent")
    child = Group(name="Beam")
    p = [QVector3D(a * 2, b, c) for a, b, c in
         [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]]
    for loop in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]):
        child.mesh.add_face([p[i] for i in loop])
    parent.adopt([child])
    frame = QMatrix4x4()
    frame.translate(5, 0, 0)
    frame.rotate(90, 0, 0, 1)
    if uneven:
        frame.scale(1, 2, 1)
    parent.xform = frame
    scene.groups.append(parent)
    source = tmp_path / "turned.igz"
    save_scene(scene, source)
    return source


@pytest.fixture()
def turned(tmp_path):
    def build(uneven=False):
        client = TestClient(create_app(tmp_path / ("data-u" if uneven else "data")))
        source = _turned_parent_document(tmp_path, uneven)
        record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
        state = {"rev": record["latest_revision"]}
        store = client.app.state.document_store

        def post(endpoint, **body):
            response = client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                                   json={"base_revision": state["rev"], **body})
            if response.status_code == 201:
                state["rev"] = response.json()["latest_revision"]
            return response

        def world_box():
            from core.group import world_mesh
            scene = load_igz(store.revision_path(record["id"], state["rev"]))
            pts = [v.position for v in world_mesh(scene.groups[0]).vertices]
            lo = [min(getattr(q, a)() for q in pts) for a in "xyz"]
            hi = [max(getattr(q, a)() for q in pts) for a in "xyz"]
            return lo, hi, [(h - l) for l, h in zip(lo, hi)], [(h + l) / 2 for l, h in zip(lo, hi)]

        post.box, post.scene = world_box, lambda: load_igz(store.revision_path(record["id"], state["rev"]))
        return post
    return build


def test_nested_rotate_turns_about_world_z_inside_a_turned_parent(turned):
    post = turned()
    _lo, _hi, size, centre = post.box()
    assert size == pytest.approx([1, 2, 1]) and centre[0] == pytest.approx(4.5)
    assert post("transform-object", object_id="group:0/0", operation="rotate", axis="z", degrees=90).status_code == 201
    _lo, _hi, size, after = post.box()
    assert size == pytest.approx([2, 1, 1])          # the long side now runs along world X
    assert after == pytest.approx(centre)            # turned about its own centre
    assert post("transform-object", object_id="group:0/0", operation="rotate", axis="q", degrees=90).status_code == 422


def test_nested_scale_stretches_along_world_axes(turned):
    post = turned()
    assert post("transform-object", object_id="group:0/0", operation="scale", factors=[3, 1, 1]).status_code == 201
    _lo, _hi, size, _c = post.box()
    assert size == pytest.approx([3, 2, 1])          # world X (the box's short side) tripled
    assert post("transform-object", object_id="group:0/0", operation="scale", factors=[1, 1, 2]).status_code == 201
    assert post.box()[2] == pytest.approx([3, 2, 2])


def test_nested_push_pull_follows_world_directions_and_the_clicked_face(turned):
    post = turned()
    assert post("push-pull", object_id="group:0/0", direction="+z", distance=1).status_code == 201
    assert post.box()[2] == pytest.approx([1, 2, 2])
    # world +X is the box's local +Y end; its face is the one nearest the clicked point
    assert post("push-pull", object_id="group:0/0", direction="+x", distance=0.5, face_point=[5, 1, 1]).status_code == 201
    assert post.box()[2] == pytest.approx([1.5, 2, 2])
    assert post("push-pull", object_id="group:0/0", direction="+x", distance=0.0001).status_code == 422


def test_a_parent_stretched_unevenly_is_refused_not_mangled(turned):
    post = turned(uneven=True)
    for body in ({"operation": "rotate", "axis": "z", "degrees": 30}, {"operation": "scale", "factors": [2, 1, 1]}):
        response = post("transform-object", object_id="group:0/0", **body)
        assert response.status_code == 422 and "stretched unevenly" in response.text
    assert post("push-pull", object_id="group:0/0", direction="+z", distance=1).status_code == 422


def test_make_group_over_objects_and_explode_it_again(api):
    a = box(api, "A", (0, 0, 0))
    b = box(api, "B", (3, 0, 0))
    c = box(api, "C", (6, 0, 0))
    assert api("loose-group", object_ids=[a, c], name="Pair").status_code == 201
    scene = api.scene()
    names = [g.name for g in scene.groups]
    assert "Pair" in names and "A" not in names and "C" not in names and "B" in names
    pair = next(g for g in scene.groups if g.name == "Pair")
    assert [child.name for child in pair.children] == ["A", "C"] and not pair.is_component()

    assert api("explode-object", object_id=f"group:{scene.groups.index(pair)}").status_code == 201
    assert sorted(g.name for g in api.scene().groups) == ["A", "B", "C"]

    assert api("loose-group", object_ids=["group:0", "group:1"], name="Part", component=True).status_code == 201
    made = next(g for g in api.scene().groups if g.name == "Part")
    assert made.is_component()
    assert api("loose-group", object_ids=["group:0/0"], name="x").status_code == 422      # top-level objects only
    assert api("loose-group", name="x").status_code == 422
    assert api("explode-object", object_id="group:0/0").status_code == 422


def test_make_group_can_mix_loose_faces_and_objects(loose):
    assert loose("create-box", name="Solid", origin=[10, 0, 0], size=[1, 1, 1]).status_code == 201
    faces = list(loose.scene().mesh.faces)
    cube_face = next(i for i, f in enumerate(faces) if f.centroid().x() < 2 and f.centroid().y() < 2 and f.centroid().z() < 2)
    response = loose("loose-group", face_indices=[cube_face], connected=True, object_ids=["group:0"], name="Mixed")
    assert response.status_code == 201, response.text
    groups = loose.scene().groups
    assert [g.name for g in groups] == ["Mixed"] and [c.name for c in groups[0].children] == ["Solid"]
    assert len(groups[0].mesh.faces) >= 6                      # the loose cube became its own geometry


def test_layers_can_be_renamed_deleted_and_locked(api):
    target = box(api)
    api("create-layer", name="Walls")
    api("assign-layer", object_id=target, layer="Walls")
    assert api("rename-layer", name="Walls", new_name="Partitions").status_code == 201
    scene = api.scene()
    assert scene.groups[0].layer == "Partitions" and scene.layer("Walls") is None
    assert api("rename-layer", name="Partitions", new_name="Layer 0").status_code == 422     # the default is taken
    assert api("rename-layer", name="Layer 0", new_name="Base").status_code == 422           # and permanent
    assert api("rename-layer", name="Nope", new_name="X").status_code == 422

    assert api("set-layer-lock", name="Partitions", locked=True).status_code == 201
    blocked = api("move-object", object_id=target, delta=[1, 0, 0])
    assert blocked.status_code == 422 and "locked" in blocked.text
    assert api("set-layer-lock", name="Partitions", locked=False).status_code == 201
    assert api("move-object", object_id=target, delta=[1, 0, 0]).status_code == 201

    assert api("delete-layer", name="Partitions").status_code == 201
    scene = api.scene()
    assert scene.layer("Partitions") is None and not scene.groups[0].layer          # back on the default layer
    assert api("delete-layer", name="Layer 0").status_code == 422


def test_a_locked_layer_protects_loose_faces_and_is_inherited_by_children(tmp_path):
    from core.group import Group
    from core.layers import Layer

    scene = Scene()
    scene.layers.append(Layer("Frozen", locked=True))
    frozen = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    frozen.attrs["layer"] = "Frozen"
    scene.mesh.add_face([QVector3D(5, 0, 0), QVector3D(6, 0, 0), QVector3D(6, 1, 0), QVector3D(5, 1, 0)])
    parent, child = Group(name="Parent"), Group(name="Child")
    child.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)])
    parent.adopt([child])
    parent.layer = "Frozen"                       # the child has no layer of its own: it inherits the lock
    scene.groups.append(parent)
    source = tmp_path / "frozen.igz"
    save_scene(scene, source)
    client = TestClient(create_app(tmp_path / "data"))
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()

    def post(endpoint, **body):
        return client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                           json={"base_revision": 1, **body})

    faces = list(load_igz(client.app.state.document_store.revision_path(record["id"], 1)).mesh.faces)
    locked = next(i for i, f in enumerate(faces) if f.attrs.get("layer") == "Frozen")
    free = next(i for i in range(len(faces)) if i != locked)
    refused = post("loose-erase", face_indices=[locked])
    assert refused.status_code == 422 and "locked" in refused.text
    assert post("loose-paint", face_indices=[locked], color=[1, 0, 0]).status_code == 422
    assert post("move-object", object_id="group:0/0", delta=[1, 0, 0]).status_code == 422      # inherited lock
    assert post("loose-erase", face_indices=[free]).status_code == 201


def test_faces_inside_a_group_or_a_moved_component_can_be_painted_pushed_and_erased(api):
    from web.backend.ingetrazo_web.scene_service import _semantic_parts

    a = box(api, "A", (0, 0, 0))
    b = box(api, "B", (3, 0, 0))
    assert api("loose-group", object_ids=[a, b], name="Pair").status_code == 201
    # a nested child: its faces are named by their place in its own mesh
    child = "group:0/1"
    part = next(p for p in _semantic_parts(api.scene()) if p["id"] == child)
    assert part["face_ids"] == list(range(len(part["faces"])))
    top = next(i for i, f in enumerate(part["faces"]) if abs(f.centroid().z() - 1) < 1e-6)
    assert api("loose-paint", object_id=child, face_indices=[top], color=[1, 0, 0]).status_code == 201
    painted = [f for f in api.scene().groups[0].children[1].mesh.faces if f.attrs.get("color")]
    assert len(painted) == 1 and abs(painted[0].centroid().z() - 1) < 1e-6
    assert api("loose-push-pull", object_id=child, face_index=top, distance=1).status_code == 201
    heights = [v.position.z() for v in api.scene().groups[0].children[1].mesh.vertices]
    assert max(heights) == pytest.approx(2)
    assert api("loose-erase", object_id=child, face_indices=[top]).status_code == 201
    assert api("loose-erase", object_id="group:9", face_indices=[0]).status_code == 422
    assert api("loose-erase", object_id="nonsense", face_indices=[0]).status_code == 422

    # a component moved by a placement matrix: indices still match the preview
    c = box(api, "C", (0, 5, 0))
    assert api("loose-group", object_ids=[c], component=True, name="Comp").status_code == 201
    outer = f"group:{len(api.scene().groups) - 1}"
    assert api("move-object", object_ids=[outer], delta=[0, 0, 10]).status_code == 201
    comp = f"{outer}/0"
    part = next(p for p in _semantic_parts(api.scene()) if p["id"] == comp)
    top = next(i for i, f in enumerate(part["faces"]) if abs(f.centroid().z() - 11) < 1e-6)
    assert api("loose-paint", object_id=comp, face_indices=[top], color=[0, 1, 0]).status_code == 201
    scene = api.scene()
    part = next(p for p in _semantic_parts(scene) if p["id"] == comp)
    assert [i for i, f in enumerate(part["faces"]) if f.attrs.get("color")] == [top]


def test_online_library_lists_downloads_and_places_a_model(api, tmp_path, monkeypatch):
    import json
    import zipfile

    library = tmp_path / "library"
    (library / "modelos").mkdir(parents=True)
    (library / "miniaturas").mkdir()
    cube = "\n".join(["v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0", "v 0 0 1", "v 1 0 1", "v 1 1 1", "v 0 1 1",
                      "f 1 2 3 4", "f 5 8 7 6", "f 1 5 6 2", "f 2 6 7 3", "f 3 7 8 4", "f 4 8 5 1"])
    with zipfile.ZipFile(library / "modelos" / "cubo.zip", "w") as archive:
        archive.writestr("cubo.obj", cube)
    (library / "miniaturas" / "cubo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (library / "index.json").write_text(json.dumps({"modelos": [
        {"id": "cubo", "nombre": "Cubo", "categoria": "Pruebas", "obj": "cubo.obj",
         "cm": [200, 100, 50], "licencia": "CC0", "autor": "Test"}]}), encoding="utf-8")
    monkeypatch.setenv("INGETRAZO_LIBRARY", str(library))
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache" / "textures"))

    listing = api.client.get("/api/v1/library/online").json()
    assert listing["reachable"] and listing["models"][0]["name"] == "Cubo"
    assert api.client.get("/api/v1/library/online/cubo/thumb").status_code == 200
    assert api.client.get("/api/v1/library/online/nope/thumb").status_code == 404

    assert api("insert-online-component", model="cubo", origin=[5, 5, 0]).status_code == 201
    scene = api.scene()
    from core.group import world_mesh
    points = [v.position for v in world_mesh(scene.groups[0]).vertices]
    assert max(p.x() for p in points) - min(p.x() for p in points) == pytest.approx(2.0, abs=1e-3)
    assert min(p.z() for p in points) == pytest.approx(0.0, abs=1e-6)
    assert api("insert-online-component", model="nope").status_code == 404

    monkeypatch.setenv("INGETRAZO_LIBRARY", str(tmp_path / "nowhere"))
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache2" / "textures"))
    assert api.client.get("/api/v1/library/online").json() == {
        "reachable": False, "source": str(tmp_path / "nowhere"), "models": []}


def test_a_face_me_image_becomes_a_billboard_figure(api):
    import base64

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(40, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    encoded = base64.b64encode(bytes(raw)).decode()

    assert api("insert-faceme-image", image_base64=encoded, height=2, name="tree.png", origin=[1, 2, 0]).status_code == 201
    group = api.scene().groups[0]
    assert group.billboard and group.name == "tree"
    zs = [v.position.z() for v in group.mesh.vertices]
    assert max(zs) - min(zs) == pytest.approx(2.0)
    assert api("insert-faceme-image", image_base64="@@@", height=2).status_code == 422
    assert api("insert-faceme-image", image_base64=base64.b64encode(b"not an image").decode()).status_code == 422
    assert api("insert-faceme-image", image_base64=encoded, height=0).status_code == 422


def test_parts_are_listed_hidden_split_and_exploded(api):
    a = box(api, "Leg", (0, 0, 0), (0.1, 0.1, 0.5))
    b = box(api, "Leg", (1, 0, 0), (0.1, 0.1, 0.5))
    c = box(api, "Top", (0, 0, 0.5), (1.1, 0.4, 0.05))
    assert api("loose-group", object_ids=[a, b, c], name="Stool", component=True).status_code == 201
    outer = f"group:{len(api.scene().groups) - 1}"
    get = lambda **params: api.client.get(
        f"/api/v1/documents/{api.state['id']}/revisions/{api.state['revision']}/parts", params=params)

    listing = get(object_id=outer).json()
    assert [p["name"] for p in listing["parts"]] == ["Leg", "Leg", "Top"]
    assert listing["parts"][0]["size"][0] == pytest.approx(0.5)
    assert sorted(line["qty"] for line in listing["cut_list"]) == [1, 2]
    assert get(object_id="nonsense").status_code == 422
    assert get(object_id="group:99").status_code == 422

    assert api("parts-hide", object_ids=[f"{outer}/0"], hidden=True).status_code == 201
    assert get(object_id=outer).json()["parts"][0]["hidden"] is True
    assert api("parts-hide", object_ids=[f"{outer}/0"], hidden=False).status_code == 201
    assert api("parts-hide", object_ids=[f"{outer}/0"], hidden="yes").status_code == 422

    assert api("explode-view", object_id=outer, factor=1, mode="z").status_code == 201
    assert get(object_id=outer).json()["exploded"] == {"factor": 1.0, "mode": "z"}
    assert api("explode-view", object_id=outer, factor=0).status_code == 201
    assert get(object_id=outer).json()["exploded"] is None
    assert api("explode-view", object_id=outer, factor=1, mode="sideways").status_code == 422
    assert api("explode-view", object_id=f"{outer}/0", factor=1).status_code == 422

    d = box(api, "Two", (5, 0, 0))
    e = box(api, "Pieces", (8, 0, 0))
    assert api("loose-group", object_ids=[d, e], name="Pair").status_code == 201
    pair = f"group:{len(api.scene().groups) - 1}"
    refused = api("split-into-pieces", object_id=pair)          # its two boxes are already pieces
    assert refused.status_code == 422 and "already" in refused.text
    single = box(api, "One", (20, 0, 0))
    assert api("split-into-pieces", object_id=single).status_code == 422


def test_a_group_of_loose_solids_splits_into_pieces(loose):
    count = len(loose.scene().mesh.faces)
    assert loose("loose-group", face_indices=list(range(count)), name="Both").status_code == 201
    assert loose("split-into-pieces", object_id="group:0").status_code == 201
    group = loose.scene().groups[0]
    assert len(group.children) == 2


def test_translation_catalogues_are_served_from_the_desktops_i18n_folder(api):
    languages = api.client.get("/api/v1/i18n").json()["languages"]
    assert {"en", "es"} <= {item["code"] for item in languages}
    assert next(item for item in languages if item["code"] == "es")["name"] == "Español"
    catalogue = api.client.get("/api/v1/i18n/es").json()
    assert catalogue["File"] == "Archivo" and len(catalogue) > 1000
    assert api.client.get("/api/v1/i18n/en").json() == {}
    assert api.client.get("/api/v1/i18n/xx").status_code == 404
    assert api.client.get("/api/v1/i18n/..%2Fsecrets").status_code == 404


@pytest.fixture()
def ext(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    folder = tmp_path / "ext"
    folder.mkdir()
    shutil.copy("examples/web-extensions/column_grid.py", folder / "column_grid.py")
    (folder / "broken.py").write_text("raise RuntimeError('boom')\n")
    (folder / "crashes.py").write_text(
        "EXTENSION = {'name': 'Crashes', 'parameters': []}\n"
        "def run(scene, params):\n    raise ValueError('nope')\n")
    monkeypatch.setenv("INGETRAZO_WEB_EXTENSIONS", str(folder))
    client = TestClient(create_app(tmp_path / "data"))
    source = tmp_path / "empty.igz"
    save_scene(Scene(), source)
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    store = client.app.state.document_store

    def run(extension, **params):
        return client.post(f"/api/v1/documents/{record['id']}/commands/run-extension",
                           json={"base_revision": 1, "extension": extension, "params": params})

    return SimpleNamespace(run=run, client=client,
                           scene=lambda revision=2: load_igz(store.revision_path(record["id"], revision)))


def test_extensions_are_listed_validated_and_run_as_one_revision(ext):
    listing = ext.client.get("/api/v1/extensions").json()
    by_key = {item["key"]: item for item in listing["extensions"]}
    assert by_key["column_grid"]["name"] == "Column grid" and by_key["column_grid"]["error"] is None
    assert "RuntimeError: boom" in by_key["broken"]["error"]

    response = ext.run("column_grid", rows=2, columns=3, name="Pilar")
    assert response.status_code == 201, response.text
    assert response.json()["command_result"]["message"] == "Placed 6 columns."
    assert [g.name for g in ext.scene().groups][:2] == ["Pilar 1-1", "Pilar 1-2"]
    assert len(ext.scene().groups) == 6


@pytest.mark.parametrize("params", [{"rows": 0}, {"rows": 2.5}, {"rows": "3"}, {"spacing": 1e6}, {"name": 5}, {"unknown": 1}, {"side": True}])
def test_extension_parameters_are_checked_against_the_declared_schema(ext, params):
    assert ext.run("column_grid", **params).status_code == 422


def test_a_failing_or_missing_extension_changes_nothing(ext):
    assert ext.run("crashes").status_code == 422
    assert ext.run("broken").status_code == 422
    assert ext.run("nope").status_code == 404
    assert ext.run("../../etc/passwd").status_code == 404
    assert ext.client.get("/api/v1/documents").json()["documents"][0]["latest_revision"] == 1


def test_a_nested_group_explodes_into_its_parent(api):
    a = box(api, "A", (0, 0, 0))
    b = box(api, "B", (3, 0, 0))
    assert api("loose-group", object_ids=[a, b], name="Pair").status_code == 201
    inner = box(api, "C", (6, 0, 0))
    assert api("loose-group", object_ids=[inner], name="Wrapper").status_code == 201
    scene = api.scene()
    assert [g.name for g in scene.groups] == ["Pair", "Wrapper"]
    # Pair holds A and B; explode A *inside* Pair: its faces become Pair's own geometry
    assert api("explode-object", object_ids=["group:0/0"]).status_code == 201, "nested explode"
    pair = api.scene().groups[0]
    assert [c.name for c in pair.children] == ["B"]
    assert len(pair.mesh.faces) == 6
    # a group of groups: exploding the wrapper (top level) frees C, and nested + top-level mix works
    assert api("explode-object", object_ids=["group:0/0", "group:1"]).status_code == 201
    names = [g.name for g in api.scene().groups]
    assert names == ["Pair", "C"] and not api.scene().groups[0].children
    assert api("explode-object", object_ids=["group:5/0"]).status_code == 422


def test_exploding_inside_a_moved_parent_keeps_the_world_position(api):
    from core.group import world_mesh
    a = box(api, "A", (0, 0, 0))
    b = box(api, "B", (3, 0, 0))
    assert api("loose-group", object_ids=[a, b], name="Pair", component=True).status_code == 201
    assert api("move-object", object_ids=["group:0"], delta=[10, 0, 5]).status_code == 201

    def spans():
        mesh = world_mesh(api.scene().groups[0])
        xs = sorted(v.position.x() for v in mesh.vertices)
        zs = sorted(v.position.z() for v in mesh.vertices)
        return xs[0], xs[-1], zs[0], zs[-1], len(mesh.faces)

    before = spans()
    assert before[:4] == pytest.approx((10, 14, 5, 6))
    assert api("explode-object", object_ids=["group:0/0"]).status_code == 201     # explode A inside the moved Pair
    assert [c.name for c in api.scene().groups[0].children] == ["B"]
    assert spans() == pytest.approx(before)                                       # nothing moved in the world


def test_a_hanging_extension_is_stopped_and_a_crash_costs_only_that_request(ext, tmp_path, monkeypatch):
    import os
    folder = tmp_path / "ext"
    (folder / "hangs.py").write_text("import time\nEXTENSION = {'name': 'Hangs', 'parameters': []}\ndef run(scene, params):\n    time.sleep(60)\n")
    (folder / "dies.py").write_text("import os, signal\nEXTENSION = {'name': 'Dies', 'parameters': []}\ndef run(scene, params):\n    os.kill(os.getpid(), signal.SIGKILL)\n")
    from web.backend.ingetrazo_web import extensions as module
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 3.0)
    import web.backend.ingetrazo_web.app as app_module
    from fastapi.testclient import TestClient
    monkeypatch.setenv("INGETRAZO_WEB_EXTENSION_TIMEOUT", "3")
    client = TestClient(app_module.create_app(tmp_path / "data2"))
    source = tmp_path / "empty.igz"
    save_scene(Scene(), source)
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()

    def run(name, **params):
        return client.post(f"/api/v1/documents/{record['id']}/commands/run-extension",
                           json={"base_revision": 1, "extension": name, "params": params})

    hung = run("hangs")
    assert hung.status_code == 422 and "longer than 3 seconds" in hung.json()["detail"]["message"]
    died = run("dies")
    assert died.status_code == 422 and "stopped unexpectedly" in died.json()["detail"]["message"]
    fine = run("column_grid", rows=1, columns=2)
    assert fine.status_code == 201 and fine.json()["command_result"]["message"] == "Placed 2 columns."
    assert client.get(f"/api/v1/documents/{record['id']}").json()["latest_revision"] == 2


def test_join_segments_and_explode_curve_on_loose_edges(tmp_path):
    scene = Scene()
    for a, b in (((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (3, 0, 0)), ((3, 0, 0), (3, 2, 0))):
        scene.mesh.add_edge(QVector3D(*a), QVector3D(*b))
    source = tmp_path / "lines.igz"
    save_scene(scene, source)
    client = TestClient(create_app(tmp_path / "data"))
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    rev = record["latest_revision"]

    def post(endpoint, **body):
        return client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                           json={"base_revision": rev, **body})

    straight = [[[0, 0, 0], [1, 0, 0]], [[1, 0, 0], [3, 0, 0]]]
    elbow = [[[1, 0, 0], [3, 0, 0]], [[3, 0, 0], [3, 2, 0]]]
    assert post("loose-edge-join", edges=elbow).status_code == 422        # not collinear
    response = post("loose-edge-join", edges=straight)
    assert response.status_code == 201
    rev = response.json()["latest_revision"]
    edges = list(load_igz(client.app.state.document_store.revision_path(record["id"], rev)).mesh.edges)
    assert len(edges) == 2
    assert post("loose-edge-explode-curve", edges=[[[0, 0, 0], [3, 0, 0]]]).status_code == 422


def test_several_scenes_are_deleted_in_one_command(tmp_path):
    from core.saved_views import SavedView
    scene = Scene()
    scene.saved_views.extend(SavedView(name=n) for n in ("A", "B", "C"))
    source = tmp_path / "scenes.igz"
    save_scene(scene, source)
    client = TestClient(create_app(tmp_path / "data"))
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    url = f"/api/v1/documents/{record['id']}/commands/delete-scene"
    rev = record["latest_revision"]
    assert client.post(url, json={"base_revision": rev, "names": ["A", "Nope"]}).status_code == 422
    done = client.post(url, json={"base_revision": rev, "names": ["A", "C"]})
    assert done.status_code == 201
    store = client.app.state.document_store
    kept = load_igz(store.revision_path(record["id"], done.json()["latest_revision"])).saved_views
    assert [v.name for v in kept] == ["B"]


def _document_from(tmp_path, build):
    scene = Scene()
    build(scene)
    source = tmp_path / "doc.igz"
    save_scene(scene, source)
    client = TestClient(create_app(tmp_path / "data"))
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    state = {"rev": record["latest_revision"]}

    def post(endpoint, **body):
        response = client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                               json={"base_revision": state["rev"], **body})
        if response.status_code == 201:
            state["rev"] = response.json()["latest_revision"]
        return response

    post.scene = lambda: load_igz(client.app.state.document_store.revision_path(record["id"], state["rev"]))
    return post


def test_bridge_joins_two_loose_faces_into_a_box(tmp_path):
    def build(scene):
        scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        scene.mesh.add_face([QVector3D(0, 0, 2), QVector3D(1, 0, 2), QVector3D(1, 1, 2), QVector3D(0, 1, 2)])

    post = _document_from(tmp_path, build)
    assert post("loose-bridge", face_indices=[0]).status_code == 422          # one profile only
    response = post("loose-bridge", face_indices=[0, 1])
    assert response.status_code == 201, response.text
    assert len(post.scene().mesh.faces) == 6                                  # two caps and four sides


def test_resegment_rebuilds_a_circle_with_another_count(tmp_path):
    import math

    def build(scene):
        points = [QVector3D(2 * math.cos(2 * math.pi * i / 12), 2 * math.sin(2 * math.pi * i / 12), 0)
                  for i in range(12)]
        scene.mesh.add_face(points)
        scene.mesh.tag_curve(points, closed=True)

    post = _document_from(tmp_path, build)
    mesh = post.scene().mesh
    edge = next(e for e in mesh.edges if e.curve is not None)
    ends = [[edge.a.x(), edge.a.y(), edge.a.z()], [edge.b.x(), edge.b.y(), edge.b.z()]]
    assert post("loose-resegment", edge=ends, segments=2).status_code == 422
    response = post("loose-resegment", edge=ends, segments=24)
    assert response.status_code == 201, response.text
    assert len(post.scene().mesh.edges) == 24
    assert len(post.scene().mesh.faces) == 1


def test_an_object_is_taken_to_an_absolute_scale(tmp_path):
    from core.group import Group
    from core.mesh import Mesh

    def build(scene):
        mesh = Mesh()
        for a, b, c, d in (((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)),):
            mesh.add_face([QVector3D(*a), QVector3D(*b), QVector3D(*c), QVector3D(*d)])
        scene.groups.append(Group(mesh, name="Plate"))

    post = _document_from(tmp_path, build)
    assert post("set-object-scale", object_id="group:0", scale=[1, 1, 1]).status_code == 422
    response = post("set-object-scale", object_id="group:0", scale=[2, 3, 1])
    assert response.status_code == 201, response.text
    xs = [v.position.x() for v in post.scene().groups[0].mesh.vertices]
    ys = [v.position.y() for v in post.scene().groups[0].mesh.vertices]
    assert abs(max(xs) - min(xs) - 2) < 1e-4 and abs(max(ys) - min(ys) - 3) < 1e-4
    assert post("set-object-scale", object_id="group:0", scale=[0, 1, 1]).status_code == 422

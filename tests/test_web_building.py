"""Openings, terrain, Make Faces and Extrude, and material files through the web API."""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from formats.igz import save_scene
from web.backend.ingetrazo_web.app import create_app
from web.backend.ingetrazo_web.scene_service import load_igz


def _document(tmp_path, build):
    scene = Scene()
    build(scene)
    source = tmp_path / "doc.igz"
    save_scene(scene, source)
    client = TestClient(create_app(tmp_path / "data"))
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


def _wall(scene, x0=0.0, x1=4.0, thickness=0.2, height=3.0):
    c = [QVector3D(x, y, z) for z in (0.0, height) for x, y in
         ((x0, 0.0), (x1, 0.0), (x1, thickness), (x0, thickness))]
    for loop in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]):
        scene.mesh.add_face([c[i] for i in loop])


def _window():
    """A 1 x 1.2 m window whose blue axis comes out of the wall's y = 0 face."""
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1.2, 0), QVector3D(0, 1.2, 0)])
    window = Group(mesh, name="Window")
    window.xform = QMatrix4x4(1, 0, 0, 1.5, 0, 0, -1, 0, 0, 1, 0, 1, 0, 0, 0, 1)
    return window


def test_a_window_marked_cut_opening_opens_the_wall_and_closes_it_again(tmp_path):
    post = _document(tmp_path, lambda scene: (_wall(scene), scene.groups.append(_window())))
    assert len(post.scene().mesh.faces) == 6
    response = post("set-cut-opening", object_id="group:0", on=True)
    assert response.status_code == 201, response.text
    faces = list(post.scene().mesh.faces)
    assert sum(len(face.holes) for face in faces) == 2            # both sides of the wall
    assert len(faces) == 10                                       # and the four reveals
    outline = response.json()["revisions"][-1]["summary"]["outline"]["items"]
    assert outline[0].get("cut_opening") is True

    assert post("move-object", object_id="group:0", delta=[1, 0, 0]).status_code == 201
    assert sum(len(face.holes) for face in post.scene().mesh.faces) == 2   # the hole followed

    assert post("set-cut-opening", object_id="group:0", on=False).status_code == 201
    assert sum(len(face.holes) for face in post.scene().mesh.faces) == 0


def test_make_faces_and_extrude_turns_each_loop_into_its_own_solid(tmp_path):
    def build(scene):
        for x in (0, 3):
            corners = [(x, 0, 0), (x + 2, 0, 0), (x + 2, 1, 0), (x, 1, 0)]
            for a, b in zip(corners, corners[1:] + corners[:1]):
                scene.mesh.add_edge(QVector3D(*a), QVector3D(*b))

    post = _document(tmp_path, build)
    edges = [[[e.a.x(), e.a.y(), e.a.z()], [e.b.x(), e.b.y(), e.b.z()]] for e in post.scene().mesh.edges]
    assert post("loose-make-faces-extrude", edges=edges, height=0).status_code == 422
    response = post("loose-make-faces-extrude", edges=edges, height=3)
    assert response.status_code == 201, response.text
    assert response.json()["command_result"]["solids"] == 2
    groups = post.scene().groups
    assert len(groups) == 2 and all(len(g.mesh.faces) == 6 for g in groups)


def test_terrain_is_made_deformed_and_stamped(tmp_path):
    post = _document(tmp_path, lambda scene: None)
    assert post("terrain-create", corner_a=[0, 0, 0]).status_code == 422        # one corner only
    response = post("terrain-create", corner_a=[0, 0, 0], corner_b=[10, 10, 0], cell=1)
    assert response.status_code == 201, response.text
    ground = post.scene().groups[0]
    assert len(ground.mesh.faces) == 200 and all(len(f.vertices) == 3 for f in ground.mesh.faces)

    response = post("terrain-deform", object_id="group:0", center=[5, 5, 0], radius=3, height=2)
    assert response.status_code == 201, response.text
    assert abs(max(v.position.z() for v in post.scene().groups[0].mesh.vertices) - 2) < 1e-4
    assert post("terrain-deform", object_id="group:0", center=[50, 50, 0], radius=1, height=1).status_code == 422

    square = [[2, 2, 0], [4, 2, 0], [4, 4, 0], [2, 4, 0]]
    assert post("terrain-stamp", object_id="group:0", footprint=square, height=0.5, slope=1).status_code == 201

    points = [[0, 0, 0], [10, 0, 1], [10, 10, 2], [0, 10, 1], [5, 5, 3]]
    assert post("terrain-create", points=points).status_code == 201
    assert len(post.scene().groups) == 2


def _skm_bytes():
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
           '<materialDocument xmlns="http://sketchup.google.com/schemas/sketchup/1.0/material" '
           'xmlns:mat="http://sketchup.google.com/schemas/sketchup/1.0/material" '
           'xmlns:r="http://sketchup.google.com/schemas/1.0/references">\n'
           '<mat:material name="Rojo teja" type="0" colorRed="204" colorGreen="102" colorBlue="51" '
           'colorizeType="0" trans="0" useTrans="0" hasTexture="0"/>\n</materialDocument>\n')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("document.xml", doc)
        archive.writestr("documentProperties.xml", "<documentProperties/>")
        archive.writestr("references.xml", "<references/>")
    return buffer.getvalue()


def test_materials_are_imported_painted_by_name_and_exported(tmp_path):
    from formats.igmat import save_materials

    post = _document(tmp_path, lambda scene: scene.mesh.add_face(
        [QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]))
    client, record, state = post.client, post.record, post.state
    url = f"/api/v1/documents/{record['id']}/materials/import"

    def upload(name, content):
        response = client.post(url, data={"base_revision": str(state["rev"])},
                               files={"file": (name, content)})
        if response.status_code == 201:
            state["rev"] = response.json()["latest_revision"]
        return response

    assert upload("notes.txt", b"nothing").status_code == 415
    assert upload("broken.igmat", b"not a zip").status_code == 422
    assert upload("teja.skm", _skm_bytes()).status_code == 201
    igmat = tmp_path / "verde.igmat"
    save_materials(igmat, [Material("Verde", color=(0.1, 0.6, 0.2))])
    assert upload("verde.igmat", igmat.read_bytes()).status_code == 201

    listed = client.get(f"/api/v1/documents/{record['id']}/revisions/{state['rev']}/materials").json()
    assert [m["name"] for m in listed["materials"]] == ["Rojo teja", "Verde"]

    assert post("loose-paint", face_indices=[0], material="Nope").status_code == 422
    assert post("loose-paint", face_indices=[0], material="Rojo teja").status_code == 201
    face = list(post.scene().mesh.faces)[0]
    assert face.attrs["mat"] == "Rojo teja" and tuple(face.attrs["color"]) == (0.8, 0.4, 0.2)

    exported = client.get(f"/api/v1/documents/{record['id']}/revisions/{state['rev']}/materials.igmat")
    assert exported.status_code == 200
    assert "material.json" in zipfile.ZipFile(io.BytesIO(exported.content)).namelist()

"""Edges that no face uses (wireframe components, guide lines) survive a .skp import.

A 2019 workshop model had four machines drawn only with edges (380 to 458 each); the importer
carried faces and the soft edges around them, so those machines were missing. Synthetic data:
the client's file is not in the repository."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QMatrix4x4

from core.scene import Scene
from formats import skp, skp_openskp


def _definition(edges, faces=(), hidden=(), soft=()):
    vertices = {}
    edge_map = {}
    for n, (a, b) in enumerate(edges, start=1):
        for v in (a, b):
            vertices.setdefault(v, SimpleNamespace(x=float(v[0]), y=float(v[1]), z=float(v[2])))
        edge_map[n] = SimpleNamespace(v1_id=a, v2_id=b, hidden=n in hidden, soft=n in soft, smooth=False)
    ids = {key: n for n, key in enumerate(edges, start=1)}
    face_map = {i: SimpleNamespace(loops=[[(ids[e], 1) for e in loop]]) for i, loop in enumerate(faces)}
    return SimpleNamespace(edges=edge_map, vertices=vertices, faces=face_map)


def _segments(definition):
    out = []
    skp_openskp._loose_edge_segments(definition, QMatrix4x4(), out)
    return out


def test_only_edges_no_face_uses_are_collected():
    square = [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (1, 1, 0)), ((1, 1, 0), (0, 0, 0))]
    wire = ((5, 5, 5), (6, 5, 5))
    definition = _definition(square + [wire], faces=[square])
    assert len(_segments(definition)) == 1                     # the triangle's own edges are not loose


def test_hidden_edges_are_not_drawn_but_a_soft_line_on_no_face_is():
    edges = [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (2, 0, 0)), ((2, 0, 0), (3, 0, 0))]
    definition = _definition(edges, hidden={1}, soft={2})
    assert len(_segments(definition)) == 2                     # upstream drops only the hidden one


def test_a_group_of_only_edges_reaches_the_scene():
    payload = {"backend": "test", "protos": [],
               "groups": [{"name": "Machine", "faces": [], "soft_edges": [],
                           "loose_edges": [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (1, 1, 0))]}]}
    scene = Scene()
    skp.apply_payload(scene, payload)
    group = next(g for g, _ in scene.placements())
    assert len(group.mesh.faces) == 0 and len([e for e in group.mesh.edges if not e.faces]) == 2


def test_a_shared_component_of_only_edges_is_placed():
    payload = {"backend": "test", "groups": [],
               "protos": [{"name": "Wire", "faces": [], "soft_edges": [], "children": [],
                           "loose_edges": [((0, 0, 0), (0, 0, 2))],
                           "instances": [QMatrix4x4()]}]}
    scene = Scene()
    skp.apply_payload(scene, payload)
    assert len(list(scene.placements())) == 1

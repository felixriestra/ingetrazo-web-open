# SPDX-License-Identifier: GPL-3.0-or-later
"""Explode Curve: a circle or an arc back to plain segments.

A curve selects whole because its edges share a curve id. Right-click ▸
Explode Curve drops the id: each segment is then picked on its own, the
geometry stays exactly where it was, and Undo makes it one curve again."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D as V

from core.history import ExplodeCurvesCommand, History
from core.scene import Scene


def _circle(sc, c, r=1.0, n=24):
    pts = [c + V(r * math.cos(2 * math.pi * k / n),
                 r * math.sin(2 * math.pi * k / n), 0) for k in range(n)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        sc.mesh.add_edge(a, b)
    sc.mesh.tag_curve(pts, closed=True)


def test_the_circle_becomes_24_segments_and_undo_rejoins_it():
    sc = Scene()
    _circle(sc, V(0, 0, 0))
    _circle(sc, V(5, 0, 0))                    # another curve, left alone
    h = History(sc)
    mesh = sc.mesh
    one = next(e for e in mesh.edges if e.a.x() < 2)
    other = next(e for e in mesh.edges if e.a.x() > 3)
    assert len(mesh.curve_edges(one)) == 24
    before = sorted((round(e.a.x(), 6), round(e.a.y(), 6)) for e in mesh.edges)
    cmd = ExplodeCurvesCommand([one])
    h.execute(cmd)
    assert cmd.curves == 1
    assert mesh.curve_edges(one) == [one]      # picked on its own now
    assert len(mesh.curve_edges(other)) == 24  # the other circle untouched
    after = sorted((round(e.a.x(), 6), round(e.a.y(), 6)) for e in mesh.edges)
    assert after == before                     # nothing moved
    h.undo()
    assert len(mesh.curve_edges(one)) == 24
    h.redo()
    assert mesh.curve_edges(one) == [one]





"""Example web extension: stand a grid of square columns.

Copy it into the server's extensions folder (see ``web/README.md``) to try it.
"""
from PySide6.QtGui import QVector3D

from core.group import Group
from core.history import InsertGroupCommand

EXTENSION = {
    "name": "Column grid",
    "description": "Stand a rows × columns grid of square columns, spaced evenly.",
    "parameters": [
        {"name": "rows", "label": "Rows", "type": "int", "default": 3, "min": 1, "max": 40},
        {"name": "columns", "label": "Columns", "type": "int", "default": 4, "min": 1, "max": 40},
        {"name": "spacing", "label": "Spacing (m)", "type": "number", "default": 4.0, "min": 0.5, "max": 100},
        {"name": "side", "label": "Column side (m)", "type": "number", "default": 0.4, "min": 0.05, "max": 5},
        {"name": "height", "label": "Height (m)", "type": "number", "default": 3.0, "min": 0.1, "max": 100},
        {"name": "name", "label": "Name", "type": "text", "default": "Column"},
    ],
}


def run(scene, params):
    side, height = params["side"], params["height"]
    for row in range(params["rows"]):
        for column in range(params["columns"]):
            x, y = column * params["spacing"], row * params["spacing"]
            p = [QVector3D(x + dx, y + dy, z) for z in (0, height) for dx, dy in ((0, 0), (side, 0), (side, side), (0, side))]
            group = Group(name=f"{params['name']} {row + 1}-{column + 1}")
            for loop in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]):
                group.mesh.add_face([p[i] for i in loop])
            InsertGroupCommand(group).do(scene)
    count = params["rows"] * params["columns"]
    return f"Placed {count} columns."

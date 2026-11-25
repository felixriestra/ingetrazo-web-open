"""Shared plumbing for modeling commands: validation, lookup, persistence.

Every command loads a base revision, mutates the native scene in place, and
saves the result as the next immutable revision (``commit_revision``).
"""
from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from PySide6.QtGui import QVector3D

from core.group import world_mesh
from formats.igz import save_scene

from .document_store import (
    DocumentNotFoundError,
    DocumentStore,
    RevisionConflictError,
    RevisionNotFoundError,
)
from .scene_service import load_igz

_qt_app = None


def ensure_qt() -> None:
    """Make sure a headless ``QGuiApplication`` exists.

    Fonts (3D text) and painters (sheet PDFs) abort the whole process when Qt
    has no application object. This is a GUI-less one on the ``offscreen``
    platform: no window or OpenGL context is ever created.
    """
    global _qt_app
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_app = QGuiApplication(["ingetrazo-web"])


def restore_scene_identities(scene, outline: list[dict]) -> None:
    """Carry the displayed names of legacy scenes into the saved revision.

    Object IDs are already stable (``load_igz`` derives them for documents
    that predate stored uids); only auto-generated "Group N" names depend on
    load order, so the names the user saw are restored before saving.
    """
    def restore(group, item: dict) -> None:
        if isinstance(item.get("name"), str):
            group.name = item["name"]
        for child, child_item in zip(group.children, item.get("children", [])):
            restore(child, child_item)

    for group, item in zip(scene.groups, outline):
        restore(group, item)


def scene_object_index(scene) -> dict[str, object]:
    """Index native and deterministic hierarchy IDs for command targeting."""
    objects = {str(uid): group for uid, group in scene.groups_by_uid().items()}

    def index(group, object_id: str) -> None:
        objects[object_id] = group
        for child_index, child in enumerate(group.children):
            index(child, f"{object_id}/{child_index}")

    for group_index, group in enumerate(scene.groups):
        index(group, f"group:{group_index}")
    return objects


def group_center(group) -> QVector3D:
    vertices = world_mesh(group).vertices
    if not vertices:
        raise HTTPException(422, "The selected object has no movable geometry.")
    xs = [vertex.position.x() for vertex in vertices]
    ys = [vertex.position.y() for vertex in vertices]
    zs = [vertex.position.z() for vertex in vertices]
    return QVector3D(
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
        (min(zs) + max(zs)) / 2,
    )


def finite(value) -> bool:
    """True for a real, finite JSON number (bools are not numbers here)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def require_base_revision(value) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HTTPException(422, "base_revision must be a positive integer.")


def require_top_level_id(object_id) -> None:
    if (not isinstance(object_id, str) or not object_id.startswith("group:")
            or "/" in object_id or len(object_id) > 255):
        raise HTTPException(422, "object_id must identify a top-level group.")


def require_object_id(object_id, *, nested: bool = True) -> None:
    """``group:N`` for a top-level object, ``group:N/M/...`` for a nested one."""
    import re
    if (not isinstance(object_id, str) or len(object_id) > 255
            or not re.fullmatch(r"group:\d+(/\d+)*", object_id)
            or (not nested and "/" in object_id)):
        raise HTTPException(422, "object_id must identify "
                            + ("an object." if nested else "a top-level group."))


def target_ids(payload: dict, *, nested: bool = True) -> list[str]:
    """The object(s) a command acts on: ``object_ids`` (a list) or ``object_id``."""
    ids = payload.get("object_ids")
    if ids is None:
        require_object_id(payload.get("object_id"), nested=nested)
        return [payload["object_id"]]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or len(set(map(str, ids))) != len(ids):
        raise HTTPException(422, "object_ids must list 1-500 different objects.")
    for item in ids:
        require_object_id(item, nested=nested)
    return list(ids)


def without_descendants(ids: list[str]) -> list[str]:
    """Drop ids whose ancestor is also listed (it already carries them)."""
    chosen = set(ids)
    keep = []
    for object_id in ids:
        parts = object_id.split("/")
        if not any("/".join(parts[:cut]) in chosen for cut in range(1, len(parts))):
            keep.append(object_id)
    return keep


def parent_frame(scene, object_id: str):
    """Matrix taking a nested object's parent frame to world space.

    Nested placements are stored relative to their parent's frame, so a world
    offset must be carried through the inverse of this matrix before it is
    composed into the child's own transform.
    """
    from PySide6.QtGui import QMatrix4x4

    path = [int(part) for part in object_id.split(":", 1)[1].split("/")]
    group = scene.groups[path[0]]
    matrix = QMatrix4x4()
    for index in path[1:]:
        if getattr(group, "xform", None) is not None:
            matrix = matrix * group.xform
        group = group.children[index]
    return matrix


class ParentFrame:
    """Carry world-space measures into the frame a nested object lives in.

    A nested placement is stored relative to its parent's frame, so a world axis,
    point or distance must be mapped through the inverse of the parent's matrix
    before a command uses it. That is only meaningful when the parent is a
    similarity (a rotation, uniform scale, translation, possibly mirrored); a
    parent stretched differently along its axes cannot turn a world rotation into a
    local one, and is refused.
    """

    def __init__(self, scene, object_id: str) -> None:
        self.nested = "/" in object_id
        self.inverse = None
        self.k = 1.0
        self.mirrored = False
        if not self.nested:
            return
        matrix = parent_frame(scene, object_id)
        inverse, ok = matrix.inverted()
        if not ok:
            raise HTTPException(422, "The parent placement cannot be inverted.")
        columns = [inverse.mapVector(QVector3D(*axis)) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        lengths = [v.length() for v in columns]
        top = max(lengths)
        if (min(lengths) < 1e-9 or max(lengths) - min(lengths) > 1e-6 * top
                or any(abs(QVector3D.dotProduct(columns[i], columns[j])) > 1e-6 * top * top
                       for i in range(3) for j in range(i + 1, 3))):
            raise HTTPException(
                422, "That object sits in a parent that is stretched unevenly; "
                "edit it from inside the parent, or make the parent's scale uniform.")
        self.inverse = inverse
        self.k = lengths[0]
        self.mirrored = QVector3D.dotProduct(
            QVector3D.crossProduct(columns[0], columns[1]), columns[2]) < 0

    def direction(self, v: QVector3D) -> QVector3D:
        return (self.inverse.mapVector(v) if self.nested else QVector3D(v)).normalized()

    def point(self, p: QVector3D) -> QVector3D:
        return self.inverse.map(p) if self.nested else QVector3D(p)

    def length(self, value: float) -> float:
        return value * self.k

    def axes(self):
        """The world X, Y, Z axes as unit vectors in the object's frame, or None at top level."""
        if not self.nested:
            return None
        return tuple(self.direction(QVector3D(*axis)) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))


def effective_layer(scene, object_id: str) -> str:
    """The layer an object is on: its own, else the nearest ancestor's, else the default."""
    from core.layers import DEFAULT_LAYER

    path = [int(part) for part in object_id.split(":", 1)[1].split("/")]
    group = scene.groups[path[0]]
    name = group.layer
    for index in path[1:]:
        group = group.children[index]
        name = group.layer or name
    return str(name or DEFAULT_LAYER)


def find_object(scene, object_id: str, *, editable: bool = True):
    """The object a command acts on. Objects on a locked layer cannot be edited."""
    group = scene_object_index(scene).get(object_id)
    if group is None:
        raise HTTPException(422, f"Unknown object ID: {object_id}")
    if editable and object_id.startswith("group:"):
        name = effective_layer(scene, object_id)
        layer = scene.layer(name)
        if layer is not None and layer.locked:
            raise HTTPException(422, f"Layer \u00ab{name}\u00bb is locked. Unlock it to edit this object.")
    return group


def commit_revision(store: DocumentStore, document_id: str, base_revision: int,
                     mutate, *, restore_identities: bool = True,
                     source_revision: int | None = None,
                     missing_revision_detail: str = "Base revision not found.",
                     history: dict | None = None):
    """Run one modeling command and persist it as the next revision.

    ``mutate(scene)`` edits the loaded native scene in place and may return a
    ``command_result`` dict that is attached to the response. The scene is
    loaded from ``source_revision`` (default: the base), but the new revision
    is conflict-checked against ``base_revision``. Missing documents and
    revisions map to 404, a stale base to 409; an ``HTTPException`` raised by
    ``mutate`` passes through untouched.
    """
    number = base_revision if source_revision is None else source_revision
    try:
        scene = load_igz(store.revision_path(document_id, number))
        if restore_identities:
            revision = next((item for item in store.get(document_id)["revisions"]
                             if item["number"] == number), None)
            outline = ((revision or {}).get("summary", {})
                       .get("outline", {}).get("items", []))
            restore_scene_identities(scene, outline)
        from core import openings
        cutting = openings.records(scene)
        result = mutate(scene)
        # A window or door marked «Cut opening» keeps its hole in step with
        # whatever the command did (moved, erased or marked it), as the
        # desktop history does after every command.
        try:
            follow = openings.follow(scene, cutting)
        except Exception as exc:  # noqa: BLE001 — follow restores what it touched
            raise HTTPException(422, f"The openings could not be updated: {exc}") from exc
        refused = list(getattr(follow, "refused", None) or ())
        if refused:
            result = dict(result or {}, openings_refused=len(refused))
        with tempfile.TemporaryDirectory(prefix="ingetrazo-command-") as directory:
            target = Path(directory) / "revision.igz"
            save_scene(scene, target)
            revised = store.add_revision(
                document_id, target, expected_latest=base_revision,
                prepare_preview=True, history=history,
            )
        if result is not None:
            revised["command_result"] = result
        return revised
    except DocumentNotFoundError as exc:
        raise HTTPException(404, "Document not found.") from exc
    except RevisionNotFoundError as exc:
        raise HTTPException(404, missing_revision_detail) from exc
    except RevisionConflictError as exc:
        raise HTTPException(
            409, {"code": "revision_conflict", "message": str(exc)},
        ) from exc


def commit_revision_from_file(store: DocumentStore, document_id: str, base_revision: int, produce):
    """Persist the next revision made by ``produce(source_path, target_path)``.

    ``produce`` reads the base revision's file and writes the new ``.igz`` (for example in
    a child process, so a script that hangs or crashes cannot take the service with it);
    its return value, if any, is attached as ``command_result``. Errors map as in
    :func:`commit_revision`.
    """
    try:
        source = store.revision_path(document_id, base_revision)
        with tempfile.TemporaryDirectory(prefix="ingetrazo-command-") as directory:
            target = Path(directory) / "revision.igz"
            result = produce(source, target)
            revised = store.add_revision(document_id, target, expected_latest=base_revision, prepare_preview=True)
        if result is not None:
            revised["command_result"] = result
        return revised
    except DocumentNotFoundError as exc:
        raise HTTPException(404, "Document not found.") from exc
    except RevisionNotFoundError as exc:
        raise HTTPException(404, "Base revision not found.") from exc
    except RevisionConflictError as exc:
        raise HTTPException(409, {"code": "revision_conflict", "message": str(exc)}) from exc

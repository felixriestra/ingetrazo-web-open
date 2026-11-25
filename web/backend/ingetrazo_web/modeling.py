"""Modeling commands for the desktop tools that have no web form yet.

Each endpoint wraps the same production routine the desktop tool calls
(``FlipGroupsCommand``, ``sweep_profile``, ``plan_fillet``, ``solids.run``,
``make_text_group`` ...), so the web cannot produce geometry the desktop would
refuse. Like every command here it loads ``base_revision``, mutates the native
scene, and saves the result as the next immutable revision.
"""
from __future__ import annotations

from types import SimpleNamespace

import math
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PySide6.QtGui import QVector3D

from core.group import Group, copy_group
from core.history import (
    FlipGroupsCommand,
    InsertGroupCommand,
    SetDisplayStyleCommand,
)

from .auth import current_user
from .schemas import (AssignLayer, CATEGORY_OPERATIONS, CreateText3d, Fillet, FollowMe, LooseGroup, Shape, SolidOperation, CreateLayer, CreateSection, DeleteLayer, DeleteScene, ExplodeObjects,
                      ExplodeView, FlipObject, InsertComponent, InsertFaceMe, InsertOnline, InsertPerson,
                      LooseBridge, LooseEdgeErase, LooseEdgeJoin, LooseFaces, LooseMakeFacesExtrude, LooseMove, LoosePaint, LoosePushPull, LooseResegment, PartsHide,
                      RenameLayer, SaveScene, SectionFill, SetLayerLock, SplitPieces)
from .commands import (
    commit_revision,
    find_object,
    finite,
    group_center,
    require_base_revision,
    require_object_id,
    require_top_level_id,
    target_ids,
    without_descendants,
)
from . import library
from .taxonomy import Taxonomy, TaxonomyError, MAX_DEPTH, UNCATEGORIZED
from .document_store import DocumentStore

LIMIT = 1_000_000.0
AXES = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}
SHAPES = {"polygon", "rotated_rectangle", "arc2", "arc3", "pie", "freehand"}
SOLID_OPERATIONS = {"outer_shell", "union", "subtract", "trim", "intersect",
                    "split"}


def number(value: Any, name: str, low: float = -LIMIT, high: float = LIMIT,
           *, nonzero: bool = False) -> float:
    if not finite(value) or not low <= float(value) <= high:
        raise HTTPException(
            422, f"{name} must be a finite number from {low:g} to {high:g}.")
    if nonzero and float(value) == 0:
        raise HTTPException(422, f"{name} must not be zero.")
    return float(value)


def integer(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not low <= value <= high:
        raise HTTPException(422, f"{name} must be an integer from {low} to {high}.")
    return value


def point(value: Any, name: str, size: int = 3) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise HTTPException(422, f"{name} must contain {size} finite values.")
    return [number(item, name) for item in value]


def object_name(value: Any, default: str) -> str:
    value = default if value is None else value
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 255:
        raise HTTPException(422, "name must contain 1–255 characters.")
    return value.strip()


def _plane_mapper(plane: str, origin: list[float]):
    ox, oy, oz = origin

    def planar(u: float, v: float) -> QVector3D:
        if plane == "xz":
            return QVector3D(ox + u, oy, oz + v)
        if plane == "yz":
            return QVector3D(ox, oy + u, oz + v)
        return QVector3D(ox + u, oy + v, oz)

    return planar


def _circumcircle(a, b, c):
    """Centre and radius of the circle through three 2D points, or None."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def _arc_points(centre, radius, start, sweep, segments):
    return [(centre[0] + radius * math.cos(start + sweep * i / segments),
             centre[1] + radius * math.sin(start + sweep * i / segments))
            for i in range(segments + 1)]


def build_shape(shape) -> Group:
    """Build one planar shape (a validated ``schemas.Shape``) as a new group: the same
    primitives the desktop's drawing tools create."""
    operation = shape.operation
    planar = _plane_mapper(shape.plane, shape.origin)
    segments = shape.segments
    group = Group(name=shape.name or operation.replace("_", " ").title())
    mesh = group.mesh

    if operation == "polygon":
        sides, radius, start = shape.sides, shape.radius, math.radians(shape.start_degrees)
        mesh.add_face([
            planar(radius * math.cos(start + 2 * math.pi * i / sides),
                   radius * math.sin(start + 2 * math.pi * i / sides))
            for i in range(sides)])
    elif operation == "rotated_rectangle":
        width, depth, angle = shape.width, shape.depth, math.radians(shape.angle_degrees)
        cos, sin = math.cos(angle), math.sin(angle)
        mesh.add_face([planar(u * cos - v * sin, u * sin + v * cos)
                       for u, v in ((0, 0), (width, 0), (width, depth), (0, depth))])
    elif operation == "pie":
        radius, start, sweep = shape.radius, math.radians(shape.start_degrees), math.radians(shape.sweep_degrees)
        rim = [planar(*p) for p in _arc_points((0, 0), radius, start, sweep, segments)]
        mesh.add_face([planar(0, 0), *rim])
        mesh.tag_curve(rim, closed=False)
    elif operation == "arc2":
        a, b, bulge = shape.start, shape.end, shape.bulge
        chord = math.hypot(b[0] - a[0], b[1] - a[1])
        if chord < 1e-9 or abs(bulge) >= chord * 50:
            raise HTTPException(422, "The chord must be non-zero and the bulge proportionate.")
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        normal = (-(b[1] - a[1]) / chord, (b[0] - a[0]) / chord)
        through = (mid[0] + normal[0] * bulge, mid[1] + normal[1] * bulge)
        _arc_through(mesh, planar, a, through, b, segments)
    elif operation == "arc3":
        _arc_through(mesh, planar, shape.start, shape.through, shape.end, segments)
    else:  # freehand
        pts = [planar(*item) for item in shape.points]
        if shape.closed and len(pts) >= 3:
            mesh.add_face(pts)
        else:
            for first, second in zip(pts, pts[1:]):
                mesh.add_edge(first, second)
    return group


def _arc_through(mesh, planar, a, through, b, segments) -> None:
    found = _circumcircle(a, through, b)
    if found is None:
        raise HTTPException(422, "The three points are collinear; they define no arc.")
    centre, radius = found
    angle = lambda p: math.atan2(p[1] - centre[1], p[0] - centre[0])  # noqa: E731
    start, mid, end = angle(a), angle(through), angle(b)
    sweep = (end - start) % (2 * math.pi)
    if (mid - start) % (2 * math.pi) > sweep:      # the middle point lies the other way round
        sweep -= 2 * math.pi
    pts = [planar(*p) for p in _arc_points(centre, radius, start, sweep, segments)]
    for first, second in zip(pts, pts[1:]):
        mesh.add_edge(first, second)
    mesh.tag_curve(pts, closed=False)


def _select_edges(group: Group, wanted: list, tolerance: float = 1e-4) -> list:
    group.materialize()
    found = []
    for item in wanted:
        a, b = QVector3D(*item.a), QVector3D(*item.b)
        for edge in group.mesh.edges:
            forward = (edge.a - a).length() < tolerance and (edge.b - b).length() < tolerance
            backward = (edge.a - b).length() < tolerance and (edge.b - a).length() < tolerance
            if forward or backward:
                found.append(edge)
                break
        else:
            raise HTTPException(422, "An edge was not found in the selected object.")
    return found


def register_modeling_commands(app: FastAPI, store: DocumentStore) -> None:
    """Attach the extra modeling endpoints to ``app``."""
    base = "/api/v1/documents/{document_id}/commands"

    @app.post(f"{base}/create-shape", status_code=201)
    def create_shape(document_id: str, payload: Shape):
        """Polygon, rotated rectangle, two/three-point arc, pie, or freehand."""
        base_revision = payload.base_revision
        group = build_shape(payload)

        def mutate(scene):
            InsertGroupCommand(group).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/flip-object", status_code=201)
    def flip_object(document_id: str, payload: FlipObject):
        """Mirror a top-level object across its centre along a world axis."""
        base_revision, object_id, axis, copy = payload.base_revision, payload.object_id, payload.axis, payload.copy_

        def mutate(scene):
            group = find_object(scene, object_id)
            target = group
            if copy:
                target = copy_group(group)
                InsertGroupCommand(target).do(scene)
            FlipGroupsCommand([target], group_center(group), QVector3D(*AXES[axis])).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/follow-me", status_code=201)
    def follow_me(document_id: str, payload: FollowMe):
        """Sweep the sole planar face of an object along a path of points."""
        from core.sweep import sweep_profile

        base_revision, object_id, closed = payload.base_revision, payload.object_id, payload.closed
        path = [QVector3D(*item) for item in payload.path]

        def mutate(scene):
            group = find_object(scene, object_id)
            group.materialize()
            faces = list(group.mesh.faces)
            if len(faces) != 1:
                raise HTTPException(422, "Follow Me needs an object with exactly one profile face.")
            if not sweep_profile(group.mesh, faces[0], path, closed):
                raise HTTPException(
                    422, "Follow Me could not sweep along that path (reversal or degenerate segment).")

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/fillet", status_code=201)
    def fillet(document_id: str, payload: Fillet):
        """Round chosen edges (given by their end points) of an object."""
        from core.fillet import apply_fillet, plan_fillet

        base_revision, object_id, edges = payload.base_revision, payload.object_id, payload.edges
        radius, segments = payload.radius, payload.segments

        def mutate(scene):
            group = find_object(scene, object_id)
            if edges == "sharp":
                group.materialize()
                chosen = [e for e in group.mesh.edges
                          if len(e.faces) == 2 and not e.soft and e.curve is None
                          and e.faces[0].normal().normalized() != e.faces[1].normal().normalized()]
                if not chosen:
                    raise HTTPException(422, "The object has no sharp edges to round.")
            else:
                chosen = _select_edges(group, edges)
            plan = plan_fillet(group.mesh, chosen, radius, segments)
            if isinstance(plan, str):
                raise HTTPException(422, plan)
            apply_fillet(group.mesh, plan)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/solid-operation", status_code=201)
    def solid_operation(document_id: str, payload: SolidOperation):
        """Boolean operation on two top-level solids (order = pick order)."""
        from core import solids

        base_revision, operation, ids = payload.base_revision, payload.operation, payload.object_ids

        def mutate(scene):
            groups = [find_object(scene, object_id) for object_id in ids]
            command = solids.SolidOperationCommand(operation, groups)
            try:
                command.prepare()
            except solids.SolidError as exc:
                raise HTTPException(422, f"Solid {operation.replace('_', ' ')} failed: {exc}.") from exc
            command.do(scene)
            return {"created": len(command.created or []),
                    "removed": len(command.removed or [])}

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/create-text3d", status_code=201)
    def create_text3d(document_id: str, payload: CreateText3d):
        """Insert extruded 3D text as a group of letters."""
        from core.text3d import make_text_group, text_params
        from PySide6.QtGui import QMatrix4x4

        base_revision, text, height, thickness = payload.base_revision, payload.text, payload.height, payload.thickness
        origin, bold, italic = payload.origin, payload.bold, payload.italic
        params = text_params(text, "", bold, italic, height, thickness)

        def mutate(scene):
            group = make_text_group(params)
            if group is None:
                raise HTTPException(422, "That text has no geometry in the available font.")
            for child in group.children:
                moved = QMatrix4x4(child.xform) if child.xform is not None else QMatrix4x4()
                moved.translate(*origin)
                child.xform = moved
            InsertGroupCommand(group).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/section-fill", status_code=201)
    def section_fill(document_id: str, payload: SectionFill):
        """Persist whether section cuts are filled with a solid colour."""
        base_revision, enabled = payload.base_revision, payload.enabled

        def mutate(scene):
            style = scene.display_style.copy()
            style.section_fill = enabled
            SetDisplayStyleCommand(style).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    # --- layers, sections, scenes ---------------------------------------------

    @app.post(f"{base}/create-layer", status_code=201)
    def create_layer(document_id: str, payload: CreateLayer):
        from core.layers import Layer

        base_revision, name = payload.base_revision, payload.name

        def mutate(scene):
            if scene.layer(name) is not None:
                raise HTTPException(422, f"A layer named {name!r} already exists.")
            scene.layers.append(Layer(name))
            scene.version += 1

        return commit_revision(store, document_id, base_revision, mutate)

    def known_layer(scene, name: str):
        layer = scene.layer(name)
        if layer is None:
            raise HTTPException(422, f"There is no layer named {name!r}.")
        return layer

    @app.post(f"{base}/rename-layer", status_code=201)
    def rename_layer(document_id: str, payload: RenameLayer):
        """Rename a layer and re-tag everything on it, nested geometry included."""
        from core.layers import DEFAULT_LAYER, assign_layer, layer_of
        from core.purge import iter_groups, iter_meshes

        base_revision, old, new = payload.base_revision, payload.name, payload.new_name

        def mutate(scene):
            layer = known_layer(scene, old)
            if old == DEFAULT_LAYER:
                raise HTTPException(422, "The default layer cannot be renamed.")
            if new != old and scene.layer(new) is not None:
                raise HTTPException(422, f"A layer named {new!r} already exists.")
            layer.name = new
            for mesh in iter_meshes(scene):
                for entity in list(mesh.faces) + list(mesh.edges):
                    if layer_of(entity) == old:
                        assign_layer(entity, new)
            for entity in (list(iter_groups(scene.groups)) + list(scene.dimensions)
                           + list(scene.text_labels) + list(scene.image_planes) + list(scene.section_planes)):
                if layer_of(entity) == old:
                    assign_layer(entity, new)
            for view in scene.saved_views:
                view.hidden_layers = [new if item == old else item for item in view.hidden_layers]
            scene.version += 1

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/delete-layer", status_code=201)
    def delete_layer(document_id: str, payload: DeleteLayer):
        """Delete a layer; whatever was on it moves to the default layer."""
        from core.layers import DEFAULT_LAYER, assign_layer, layer_of
        from core.purge import iter_groups, iter_meshes

        base_revision, name = payload.base_revision, payload.name

        def mutate(scene):
            layer = known_layer(scene, name)
            if name == DEFAULT_LAYER:
                raise HTTPException(422, "The default layer cannot be deleted.")
            for mesh in iter_meshes(scene):
                for entity in list(mesh.faces) + list(mesh.edges):
                    if layer_of(entity) == name:
                        assign_layer(entity, DEFAULT_LAYER)
            for entity in (list(iter_groups(scene.groups)) + list(scene.dimensions)
                           + list(scene.text_labels) + list(scene.image_planes) + list(scene.section_planes)):
                if layer_of(entity) == name:
                    assign_layer(entity, DEFAULT_LAYER)
            scene.layers.remove(layer)
            for view in scene.saved_views:
                view.hidden_layers = [item for item in view.hidden_layers if item != name]
            scene.version += 1

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/set-layer-lock", status_code=201)
    def set_layer_lock(document_id: str, payload: SetLayerLock):
        """Lock or unlock a layer: what is on a locked layer cannot be selected or edited."""
        base_revision, name, locked = payload.base_revision, payload.name, payload.locked

        def mutate(scene):
            known_layer(scene, name).locked = locked
            scene.version += 1

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/assign-layer", status_code=201)
    def assign_layer(document_id: str, payload: AssignLayer):
        """Put a top-level object on a layer (created when it does not exist)."""
        from core.history import AssignLayerCommand

        base_revision, object_id, name = payload.base_revision, payload.object_id, payload.layer

        def mutate(scene):
            AssignLayerCommand([find_object(scene, object_id)], name).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/create-section", status_code=201)
    def create_section(document_id: str, payload: CreateSection):
        """Place a section plane through ``point`` facing ``normal`` and make it the active cut."""
        from core.history import PlaceSectionPlaneCommand
        from core.section import SectionPlane, next_symbol

        base_revision, origin, normal = payload.base_revision, payload.point, payload.normal

        def mutate(scene):
            symbol = next_symbol(scene.section_planes)
            name = payload.name or f"Section {symbol}"
            plane = SectionPlane(QVector3D(*origin), QVector3D(*normal), name=name, symbol=symbol)
            PlaceSectionPlaneCommand(plane).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/save-scene", status_code=201)
    def save_scene_view(document_id: str, payload: SaveScene):
        """Save a named scene: the camera the browser is looking through plus layer state."""
        from types import SimpleNamespace

        from core.saved_views import SavedView

        base_revision, name, eye, target = payload.base_revision, payload.name, payload.eye, payload.target
        fov, perspective = payload.fov_deg, payload.perspective
        offset = QVector3D(*eye) - QVector3D(*target)
        distance = offset.length()
        pitch = math.asin(max(-1.0, min(1.0, offset.z() / distance)))
        yaw = math.atan2(offset.y(), offset.x())
        camera = SimpleNamespace(
            target=QVector3D(*target), distance=distance, yaw=yaw, pitch=pitch,
            fov_deg=fov, perspective=perspective, two_point=False)

        def mutate(scene):
            if any(view.name == name for view in scene.saved_views):
                raise HTTPException(422, f"A scene named {name!r} already exists.")
            scene.saved_views.append(SavedView.capture(name, scene, camera))
            scene.version += 1

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/delete-scene", status_code=201)
    def delete_scene(document_id: str, payload: DeleteScene):
        from core.history import DeleteScenesCommand

        base_revision = payload.base_revision
        names = payload.names if payload.names is not None else [payload.name]

        def mutate(scene):
            matches = []
            for name in dict.fromkeys(names):
                found = [view for view in scene.saved_views if view.name == name]
                if not found:
                    raise HTTPException(422, f"There is no scene named {name!r}.")
                matches.append(found[0])
            DeleteScenesCommand(matches).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    # --- loose (ungrouped) geometry -------------------------------------------
    #
    # The preview tags every triangle of loose geometry with its face's index
    # in the scene's loose mesh; these commands take those indices.

    from contextlib import contextmanager

    @contextmanager
    def editing(scene, payload):
        """Open the group named by ``object_id`` for editing, as on the desktop.

        Inside, ``scene.mesh`` is that group's mesh in world coordinates (a
        component's shared definition is edited as a world copy and shared back
        to every instance on leaving), so the loose-geometry commands below
        work on the group's own faces unchanged. Without ``object_id`` they
        edit the loose geometry.
        """
        object_id = payload.get("object_id") if isinstance(payload, dict) else payload.object_id
        if object_id is None:
            yield
            return
        target = find_object(scene, object_id)              # refuses locked layers
        if getattr(target, "billboard", False):
            raise HTTPException(422, "A face-me figure has no faces to edit.")
        parts = object_id.split("/")
        try:
            for depth in range(1, len(parts) + 1):
                scene.begin_group_edit(find_object(scene, "/".join(parts[:depth]), editable=False))
            yield
        finally:
            scene.end_group_edit()

    def face_list(scene, indices):
        faces = list(scene.mesh.faces)
        chosen = []
        for index in indices:
            if index >= len(faces):
                raise HTTPException(422, "A face index is out of range; reload the document.")
            chosen.append(faces[index])
        from core.layers import layer_of
        for face in chosen:
            layer = scene.layer(layer_of(face))
            if layer is not None and layer.locked:
                raise HTTPException(422, f"Layer \u00ab{layer.name}\u00bb is locked. Unlock it to edit these faces.")
        return chosen

    def face_indices(payload) -> list[int]:
        return sorted(set(payload.face_indices))

    @app.post(f"{base}/loose-push-pull", status_code=201)
    def loose_push_pull(document_id: str, payload: LoosePushPull):
        from tools.pushpull import push_pull_face

        base_revision, index, distance, keep_base = payload.base_revision, payload.face_index, payload.distance, payload.keep_base

        def mutate(scene):
            with editing(scene, payload):
                (face,) = face_list(scene, [index])
                result = push_pull_face(scene, face, distance, keep_base=keep_base)
            if result["refused"]:
                raise HTTPException(422, "Push/pull was refused because it would break the solid.")
            return result

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/loose-erase", status_code=201)
    def loose_erase(document_id: str, payload: LooseFaces):
        from core.history import EraseSelectionCommand

        base_revision, indices = payload.base_revision, face_indices(payload)

        def mutate(scene):
            with editing(scene, payload):
                EraseSelectionCommand([], face_list(scene, indices)).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/loose-paint", status_code=201)
    def loose_paint(document_id: str, payload: LoosePaint):
        from core.history import (SetFaceColorCommand, SetFaceOpacityCommand,
                                  SetFaceTextureCommand)

        base_revision, indices, value = payload.base_revision, face_indices(payload), payload.opacity
        if payload.texture is not None:
            material, rgb = library.texture_material(payload.texture), None
        else:
            material, rgb = None, payload.color

        def mutate(scene):
            with editing(scene, payload):
                faces = face_list(scene, indices)
                if payload.material is not None:
                    paint_with_document_material(scene, faces, payload.material)
                elif material is not None:
                    SetFaceTextureCommand(faces, dict(material["texture"])).do(scene)
                else:
                    SetFaceColorCommand(faces, tuple(rgb)).do(scene)
                if value < 0.999:
                    SetFaceOpacityCommand(faces, value).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    def paint_with_document_material(scene, faces, name):
        """Stamp a material the document already holds (imported from .igmat or .skm)."""
        from core.history import (SetFaceColorCommand, SetFaceMaterialTagCommand,
                                  SetFaceOpacityCommand, SetFaceTextureCommand)
        material = scene.materials.get(name)
        if material is None:
            raise HTTPException(422, f"The document has no material named \u00ab{name}\u00bb.")
        if material.texture is not None:
            SetFaceTextureCommand(faces, dict(material.texture)).do(scene)
        elif material.color is not None:
            SetFaceColorCommand(faces, tuple(material.color)).do(scene)
        if material.opacity is not None:
            SetFaceOpacityCommand(faces, float(material.opacity)).do(scene)
        SetFaceMaterialTagCommand(faces, name).do(scene)

    def free_edges(scene, payload):
        """Free loose edges named by their two endpoints (``[[a, b], ...]``)."""
        from core.layers import layer_of
        chosen = []
        for a, b in payload.edges:
            match = None
            for edge in scene.mesh.edges:
                ends = ((edge.a.x(), edge.a.y(), edge.a.z()), (edge.b.x(), edge.b.y(), edge.b.z()))
                close = lambda p, q: all(abs(u - v) < 2e-3 for u, v in zip(p, q))
                if (close(ends[0], a) and close(ends[1], b)) or (close(ends[0], b) and close(ends[1], a)):
                    match = edge
                    break
            if match is None:
                raise HTTPException(422, "An edge was not found; reload the document.")
            layer = scene.layer(layer_of(match))
            if layer is not None and layer.locked:
                raise HTTPException(422, f"Layer \u00ab{layer.name}\u00bb is locked. Unlock it to edit these edges.")
            chosen.append(match)
        return chosen

    @app.post(f"{base}/loose-move", status_code=201)
    def loose_move(document_id: str, payload: LooseMove):
        """Move loose faces and/or free edges by ``delta``. Vertices are shared,
        so anything attached to a moved corner follows, as on the desktop."""
        from core.history import MoveVerticesCommand

        base_revision, delta = payload.base_revision, QVector3D(*payload.delta)
        has_faces, has_edges = payload.face_indices is not None, payload.edges is not None
        indices = face_indices(payload) if has_faces else []

        def mutate(scene):
            with editing(scene, payload):
                positions = []
                for face in face_list(scene, indices):
                    positions.extend(face.vertices)
                if has_edges:
                    for edge in free_edges(scene, payload):
                        positions.extend((edge.a, edge.b))
                MoveVerticesCommand(positions, delta).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/loose-edge-erase", status_code=201)
    def loose_edge_erase(document_id: str, payload: LooseEdgeErase):
        from core.history import EraseSelectionCommand

        base_revision = payload.base_revision

        def mutate(scene):
            with editing(scene, payload):
                EraseSelectionCommand(free_edges(scene, payload), []).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/loose-edge-join", status_code=201)
    def loose_edge_join(document_id: str, payload: LooseEdgeJoin):
        """Join Segments, the inverse of Divide: a point where two of the
        edges meet in a straight line, with nothing else attached, goes."""
        from core.edits import join_edges

        def mutate(scene):
            with editing(scene, payload):
                edges = free_edges(scene, payload)
                joined = len(edges) - len(join_edges(scene.mesh, edges))
                if not joined:
                    raise HTTPException(422, "No collinear segments to join.")
                scene.version += 1

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/loose-edge-explode-curve", status_code=201)
    def loose_edge_explode_curve(document_id: str, payload: LooseEdgeErase):
        """Explode Curve: a circle or an arc back to plain segments."""
        from core.history import ExplodeCurvesCommand

        def mutate(scene):
            with editing(scene, payload):
                command = ExplodeCurvesCommand(free_edges(scene, payload))
                command.do(scene)
                if not command.curves:
                    raise HTTPException(422, "These edges are not part of a curve.")

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/loose-bridge", status_code=201)
    def loose_bridge(document_id: str, payload: LooseBridge):
        """Bridge (#614): side faces between two loose faces, a face and a line, or two
        lines. The faces named stay, as the caps."""
        from core.bridge import BridgeError, bridge, plan, profiles_from_selection

        indices = face_indices(payload) if payload.face_indices is not None else []

        def mutate(scene):
            with editing(scene, payload):
                chosen = list(face_list(scene, indices)) if indices else []
                if payload.edges is not None:
                    chosen.extend(free_edges(scene, payload))
                try:
                    profiles = profiles_from_selection(scene.mesh, chosen)
                    plan(profiles)
                    added = bridge(scene.mesh, profiles)
                except BridgeError as error:
                    raise HTTPException(422, str(error))
                scene.version += 1
                return {"faces_added": len(added)}

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/loose-make-faces-extrude", status_code=201)
    def loose_make_faces_extrude(document_id: str, payload: LooseMakeFacesExtrude):
        """Make Faces and Extrude: the faces the edges close, each one straight into its own
        solid group of ``height``. The lines stay, ready for the next storey."""
        from core.make_faces import MakeFacesError
        from core.make_faces_extrude import MakeFacesExtrudeCommand, check

        def mutate(scene):
            with editing(scene, payload):
                edges = free_edges(scene, payload)
                try:
                    check(edges, payload.height)
                    command = MakeFacesExtrudeCommand(edges, payload.height,
                                                      fill_holes=payload.fill_holes)
                    command.do(scene)
                except MakeFacesError as error:
                    raise HTTPException(422, str(error))
                if not command.groups:
                    raise HTTPException(422, "The edges close no loop to extrude.")
                return {"solids": len(command.groups), "holes_left": command.result.get("inner", 0)}

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/loose-resegment", status_code=201)
    def loose_resegment(document_id: str, payload: LooseResegment):
        """Change the segment count of a flat circle, arc or polygon already drawn."""
        from core.curve_segments import read_curve, resegment

        def mutate(scene):
            with editing(scene, payload):
                edge = free_edges(scene, SimpleNamespace(edges=[payload.edge]))[0]
                shape = read_curve(scene.mesh, edge)
                if shape is None:
                    raise HTTPException(422, "That edge is not part of a regular flat curve.")
                if payload.segments < (3 if shape.closed else 2):
                    raise HTTPException(422, "A closed curve needs at least 3 segments, an arc 2.")
                if not resegment(scene.mesh, shape, payload.segments):
                    raise HTTPException(422, "The curve cannot be rebuilt with that many segments.")
                scene.version += 1

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/loose-group", status_code=201)
    def loose_group(document_id: str, payload: LooseGroup):
        """Make a group or component from loose faces and/or whole objects.

        Faces may bring everything connected to them. Objects (top-level) stay
        groups inside the new container, as in the desktop's Make Group.
        """
        from core.history import (MakeComponentOfCommand, MakeGroupCommand,
                                  MakeNestedGroupCommand)
        from core.mesh import Face
        from core.select_ops import all_connected

        base_revision, object_ids = payload.base_revision, payload.object_ids
        indices = sorted(set(payload.face_indices)) if payload.face_indices is not None else []
        connected, component = payload.connected, payload.component
        name = payload.name or ("Component" if component else "Group")

        def mutate(scene):
            faces = face_list(scene, indices) if indices else []
            edges = []
            if connected and faces:
                everything = all_connected(faces)
                faces = [item for item in everything if isinstance(item, Face)]
                edges = [item for item in everything if not isinstance(item, Face)]
            groups = [find_object(scene, object_id) for object_id in (object_ids or [])]
            if groups:
                command = (MakeComponentOfCommand if component else MakeNestedGroupCommand)(
                    faces, edges, groups, name=name)
            else:
                command = MakeGroupCommand(faces, edges, component=component, name=name)
            command.do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    def explode_in_parent(scene, chain, group):
        """Explode a nested group inside its parent.

        The parent is opened for editing as on the desktop (``begin_group_edit`` bakes
        its matrix into its children, so the tools work in one frame); the group's own
        geometry merges into the parent's mesh and the groups nested in it come out as
        the parent's own children. The desktop command lists ``scene.groups``, so for the
        duration it is pointed at the parent's children.
        """
        from core.history import ExplodeGroupCommand
        try:
            for ancestor in chain:
                scene.begin_group_edit(ancestor)
            top_level = scene.groups
            scene.groups = chain[-1].children
            try:
                ExplodeGroupCommand(group).do(scene)
            finally:
                scene.groups = top_level
        finally:
            scene.end_group_edit()

    @app.post(f"{base}/explode-object", status_code=201)
    def explode_object(document_id: str, payload: ExplodeObjects):
        """Dissolve one level of each chosen top-level group: its own geometry returns
        to the loose mesh and the groups nested in it come out whole."""
        from core.history import ExplodeGroupCommand

        base_revision, ids = payload.base_revision, without_descendants(payload.ids())

        def mutate(scene):
            # Resolve every target first (indices shift), nested ones with their ancestors.
            targets = []
            for object_id in ids:
                parts = object_id.split("/")
                chain = [find_object(scene, "/".join(parts[:depth]), editable=False) for depth in range(1, len(parts))]
                targets.append((chain, find_object(scene, object_id)))
            for chain, group in (item for item in targets if item[0]):
                if getattr(group, "billboard", False):
                    continue
                explode_in_parent(scene, chain, group)
            for chain, group in (item for item in targets if not item[0]):
                ExplodeGroupCommand(group).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/loose-connected")
    def loose_connected(document_id: str, revision: int, face: int, object_id: str | None = None):
        """Every loose face physically connected to ``face`` (the triple click)."""
        from core.mesh import Face
        from core.select_ops import all_connected

        from .document_store import DocumentNotFoundError, RevisionNotFoundError
        from .scene_service import load_igz
        try:
            scene = load_igz(store.revision_path(document_id, revision))
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        with editing(scene, {"object_id": object_id}):
            faces = list(scene.mesh.faces)
            if not 0 <= face < len(faces):
                raise HTTPException(422, "face is out of range.")
            position = {id(item): index for index, item in enumerate(faces)}
            found = [position[id(item)] for item in all_connected([faces[face]])
                     if isinstance(item, Face) and id(item) in position]
        return {"faces": sorted(found)}

    # --- libraries -----------------------------------------------------------

    @app.get("/api/v1/library/components")
    def list_components():
        return {"components": library.component_index()}

    taxonomy = Taxonomy(store.root / "taxonomy.json")

    def taxonomy_payload() -> dict:
        """The category tree and which categories each bundled component is in."""
        entries = library.component_index()
        items = {entry["item"]: [n.id for n in taxonomy.nodes_of(entry["item"], tuple(entry["default_path"]))]
                 for entry in entries}
        return {
            "max_depth": MAX_DEPTH,
            "uncategorized": UNCATEGORIZED,
            "nodes": [{"id": n.id, "parent_id": n.parent_id, "name": n.name,
                       "hidden": n.hidden, "hidden_effective": taxonomy.is_hidden(n.id),
                       "depth": taxonomy.depth(n.id)} for n in taxonomy.nodes()],
            "items": items,
        }

    @app.get("/api/v1/library/taxonomy")
    def get_taxonomy():
        return taxonomy_payload()

    @app.post("/api/v1/library/taxonomy/{operation}")
    def edit_taxonomy(request: Request, operation: str, payload: dict = Body(...)):
        """Create, rename, hide, move or delete a category; file a component in one.

        The tree is shared by everyone who uses the server, so with accounts on only an
        administrator may change it."""
        if not current_user(request).is_admin:
            raise HTTPException(403, "Only an administrator can change the shared component categories.")
        from fastapi.exceptions import RequestValidationError
        from pydantic import ValidationError

        model = CATEGORY_OPERATIONS.get(operation)
        if model is None:
            raise HTTPException(404, "Unknown category operation.")
        try:
            body = model.model_validate(payload)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc
        defaults = {entry["item"]: tuple(entry["default_path"]) for entry in library.component_index()}

        def known(key: str) -> str:
            if key not in defaults:
                raise TaxonomyError("Unknown component.")
            return key

        try:
            if operation == "create":
                taxonomy.create(body.name, body.parent_id)
            elif operation == "rename":
                taxonomy.rename(body.id, body.name)
            elif operation == "delete":
                taxonomy.delete(body.id)
            elif operation == "hide":
                taxonomy.set_hidden(body.id, body.hidden)
            elif operation == "move":
                taxonomy.move(body.id, body.parent_id)
            elif operation == "add":
                taxonomy.add_to(known(body.item), body.node, defaults[body.item])
            elif operation == "remove":
                taxonomy.remove_from(known(body.item), body.node, defaults[body.item])
            else:  # move_item
                taxonomy.move_item(known(body.item), body.from_, body.to, defaults[body.item])
        except TaxonomyError as exc:
            raise HTTPException(422, str(exc)) from exc
        return taxonomy_payload()

    @app.get("/api/v1/library/components/{key}/thumb")
    def component_thumb(key: str):
        return FileResponse(library.thumbnail_path(key), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/v1/library/people/{key}/thumb")
    def person_thumb(key: str):
        return Response(library.person_thumbnail(key), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/v1/library/materials")
    def list_materials():
        return {"categories": library.texture_index()}

    @app.get("/api/v1/library/materials/file/{path:path}")
    def material_file(path: str):
        file = library.texture_file(path)
        return FileResponse(file, media_type="image/png" if file.suffix == ".png" else "image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.post(f"{base}/insert-person", status_code=201)
    def insert_person(document_id: str, payload: InsertPerson):
        """Stand a 2D scale figure (a face-me cut-out at its real height) on ``origin``."""
        from core.group import make_billboard_group

        base_revision, key, origin = payload.base_revision, payload.person, payload.origin
        entry = library.person_entry(key)
        image, aspect = library.person_image(key), library.person_aspect(key)

        def mutate(scene):
            group = make_billboard_group(
                str(image), entry["height"], entry["name"], aspect, QVector3D(*origin))
            InsertGroupCommand(group).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    # --- localisation: the desktop's translation catalogues ----------------------

    @app.get("/api/v1/i18n")
    def languages():
        from core.i18n import LANGUAGE_NAMES, available_languages
        return {"languages": [{"code": code, "name": LANGUAGE_NAMES.get(code, code)}
                              for code in available_languages()]}

    @app.get("/api/v1/i18n/{code}")
    def translations(code: str):
        """English source text → text in ``code``, exactly the desktop's ``i18n/<code>.json``."""
        import json

        from core.i18n import available_languages
        from core.paths import app_root
        if code not in available_languages():
            raise HTTPException(404, "Unknown language.")
        if code == "en":
            return {}
        try:
            data = json.loads((app_root() / "i18n" / f"{code}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, "The translation file could not be read.") from exc
        return Response(json.dumps(data, ensure_ascii=False), media_type="application/json",
                        headers={"Cache-Control": "public, max-age=3600"})

    # --- the parts of a component (the desktop's Parts tray) ---------------------

    def parts_container(scene, object_id):
        group = find_object(scene, object_id, editable=False)
        if getattr(group, "billboard", False):
            raise HTTPException(422, "A face-me figure has no parts.")
        return group

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/parts")
    def component_parts(document_id: str, revision: int, object_id: str, by_material: bool = True):
        """The parts of an object, measured like a cut list, and the merged cut list."""
        from core.parts import cut_list, is_surface, part_rows

        from .document_store import DocumentNotFoundError, RevisionNotFoundError
        from .scene_service import load_igz
        require_object_id(object_id)
        try:
            scene = load_igz(store.revision_path(document_id, revision))
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        container = parts_container(scene, object_id)
        rows = part_rows(container)
        return {
            "object_id": object_id,
            "name": str(container.name),
            "exploded": dict(container.exploded) if getattr(container, "exploded", None) else None,
            "parts": [{"id": f"{object_id}/{index}", "name": str(row["name"]),
                       "material": row["material"], "size": [float(d) for d in row["size"]],
                       "surface": bool(is_surface(row["size"])), "faces": int(row["faces"]),
                       "hidden": bool(row["hidden"])} for index, row in enumerate(rows)],
            "cut_list": [{"qty": line["qty"], "names": line["names"], "material": line["material"],
                          "size": [float(d) for d in line["size"]], "surface": bool(is_surface(line["size"]))}
                         for line in cut_list(rows, by_material=by_material)],
        }

    @app.post(f"{base}/parts-hide", status_code=201)
    def parts_hide(document_id: str, payload: PartsHide):
        """Hide or show parts (or any objects) with the desktop's Hide command."""
        from core.history import HideCommand

        base_revision, ids, hidden = payload.base_revision, payload.ids(), payload.hidden

        def mutate(scene):
            HideCommand([find_object(scene, item, editable=False) for item in without_descendants(ids)],
                        hidden=hidden).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/split-into-pieces", status_code=201)
    def split_pieces(document_id: str, payload: SplitPieces):
        """Regroup a top-level group by the solids that do not touch."""
        from core.history import SplitIntoPiecesCommand
        from core.pieces import split_into_pieces

        base_revision, object_id = payload.base_revision, payload.object_id

        def mutate(scene):
            group = find_object(scene, object_id)
            if getattr(group, "billboard", False):
                raise HTTPException(422, "A face-me figure cannot be split.")
            pieces = split_into_pieces(group)
            if not pieces:
                raise HTTPException(422, "Nothing to split: it is already in its pieces.")
            SplitIntoPiecesCommand(group, pieces).do(scene)
            return {"pieces": len(pieces)}

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/explode-view", status_code=201)
    def explode_view(document_id: str, payload: ExplodeView):
        """Pull a component's parts apart (``factor`` 0 puts them back)."""
        from core.history import ExplodeViewCommand

        base_revision, object_id, factor, mode = payload.base_revision, payload.object_id, payload.factor, payload.mode

        def mutate(scene):
            container = find_object(scene, object_id)
            if len(getattr(container, "children", None) or ()) < 2:
                raise HTTPException(422, "Only an object made of two or more parts can be exploded.")
            ExplodeViewCommand(container, factor, mode).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    # --- the online component library and the user's own face-me images -------
    #
    # The online library is read through ``core.library`` exactly as the desktop
    # tray does: an index of models, a thumbnail each, and a model zip fetched only
    # when it is placed. Nothing here raises on a network failure: the index is
    # then empty and ``reachable`` says so, because working offline is a promise.

    def online_entry(model_id: str) -> dict:
        from core import library as online
        for entry in online.index():
            if entry.get("id") == model_id:
                return entry
        raise HTTPException(404, "That model is not in the online library.")

    @app.get("/api/v1/library/online")
    def online_library(refresh: bool = False):
        from core import library as online
        models = online.index(refresh=refresh)
        return {"reachable": bool(models), "source": online.library_url(),
                "models": [{"id": m.get("id"), "name": m.get("nombre") or m.get("id"),
                            "category": m.get("categoria") or "",
                            "size_cm": m.get("cm"), "license": m.get("licencia") or "",
                            "author": m.get("autor") or ""}
                           for m in models if isinstance(m, dict) and m.get("id")]}

    @app.get("/api/v1/library/online/{model_id}/thumb")
    def online_thumb(model_id: str):
        from core import library as online
        online_entry(model_id)                               # only ids the index lists
        path = online.thumbnail(model_id)
        if path is None:
            raise HTTPException(404, "The preview could not be downloaded.")
        return FileResponse(path, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.post(f"{base}/insert-online-component", status_code=201)
    def insert_online_component(document_id: str, payload: InsertOnline):
        """Download a model from the online library and stand it on ``origin``."""
        from core import library as online
        from core.scene import Scene
        from core.history import MoveGroupCommand
        from core.group import world_mesh
        from formats import obj as obj_format
        from formats.fuse import soften_smooth_edges

        base_revision, model_id, origin = payload.base_revision, payload.model, payload.origin
        entry = online_entry(model_id)
        path = online.model_file(entry)
        if path is None:
            raise HTTPException(502, f"Could not download \u00ab{entry.get('nombre', model_id)}\u00bb. "
                                     "Check the server's connection.")
        temp = Scene()
        try:
            obj_format.load_obj(temp, path, matrix=online.model_matrix(entry, path))
        except Exception as exc:  # noqa: BLE001 - a bad model file is the model's fault
            raise HTTPException(422, f"The model could not be read: {exc}") from exc
        name = str(entry.get("nombre") or model_id)
        if temp.groups and temp.groups[0].children:          # a model written as parts keeps them
            group = temp.groups[0]
            for child in group.children:
                soften_smooth_edges(child.mesh, cos_threshold=0.55)
            group.name = name
        else:
            mesh = temp.mesh
            if not mesh.faces and temp.groups:
                mesh = temp.groups[0].mesh
            if not mesh.faces:
                raise HTTPException(422, "That model has no geometry.")
            soften_smooth_edges(mesh, cos_threshold=0.55)
            group = Group(mesh, name=name)

        def mutate(scene):
            InsertGroupCommand(group).do(scene)
            vertices = world_mesh(group).vertices
            if vertices:
                xs = [v.position.x() for v in vertices]
                ys = [v.position.y() for v in vertices]
                zs = [v.position.z() for v in vertices]
                anchor = QVector3D((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs))
                MoveGroupCommand(group, QVector3D(*origin) - anchor).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/insert-faceme-image", status_code=201)
    def insert_faceme_image(document_id: str, payload: InsertFaceMe):
        """Stand the user's own image (a cut-out person, a tree photo) as a face-me
        figure of a chosen real height. The image arrives base64-encoded."""
        import base64
        import binascii
        import hashlib
        from pathlib import PurePath

        from PySide6.QtGui import QImage

        from core.group import make_billboard_group

        base_revision, height, origin = payload.base_revision, payload.height, payload.origin
        try:
            data = base64.b64decode(payload.image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "image_base64 is not valid base64.") from exc
        stem = PurePath(payload.name or "Face-me image").stem[:80] or "Face-me image"
        image = QImage.fromData(data)
        if image.isNull() or image.height() == 0 or max(image.width(), image.height()) > 8192:
            raise HTTPException(422, "The image could not be read (PNG or WebP, up to 8192 px).")
        folder = store.root / "faceme-images"
        folder.mkdir(parents=True, exist_ok=True)
        stored = folder / f"{hashlib.sha256(data).hexdigest()[:24]}.png"
        if not stored.is_file() and not image.save(str(stored), "PNG"):
            raise HTTPException(500, "The image could not be stored.")
        group = make_billboard_group(str(stored), height, stem, image.width() / image.height(),
                                     QVector3D(*origin))

        def mutate(scene):
            InsertGroupCommand(group).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post(f"{base}/insert-component", status_code=201)
    def insert_component(document_id: str, payload: InsertComponent):
        """Place a bundled component with the centre of its base at ``origin``."""
        from core.insert import import_document_as_component
        from core.scene import Scene
        from core.group import world_mesh
        from core.history import MoveGroupCommand
        from formats.igz import load_into

        base_revision, key, origin = payload.base_revision, payload.component, payload.origin
        path = library.component_path(key)
        name = library.component_entry(key)["name"]

        def mutate(scene):
            source = Scene()
            load_into(source, path)
            group = import_document_as_component(scene, source, name)
            if group is None:
                raise HTTPException(422, "That component has no geometry.")
            InsertGroupCommand(group).do(scene)
            vertices = world_mesh(group).vertices
            if vertices:
                xs = [v.position.x() for v in vertices]
                ys = [v.position.y() for v in vertices]
                zs = [v.position.z() for v in vertices]
                anchor = QVector3D((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs))
                MoveGroupCommand(group, QVector3D(*origin) - anchor).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

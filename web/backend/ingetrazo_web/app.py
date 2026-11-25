"""FastAPI adapter for the first IngeTrazo web vertical slice."""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import math
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from core.version import __version__

from .scene_service import MAX_UNPACKED_BYTES, inspect_igz, preview_igz
from .scene_service import load_igz
from .document_store import (
    DocumentNotFoundError,
    DocumentStore,
    RevisionConflictError,
    RevisionNotFoundError,
)
from .interchange import (
    export_formats,
    import_formats,
    export_scene,
    import_scene,
    normalize_format,
)
from .commands import (
    commit_revision,
    ensure_qt,
    find_object,
    finite,
    group_center,
    ParentFrame,
    parent_frame,
    require_base_revision,
    require_object_id,
    require_top_level_id,
    restore_scene_identities,
    scene_object_index,
    target_ids,
    without_descendants,
)
from .job_manager import JobManager, JobNotFoundError
from . import library
from .modeling import register_modeling_commands
from .edition import describe as describe_edition
from .errors import register_error_handlers
from .schemas import (Annotation, BlankDocument, Planar, CreateBox, CreateGeoPath, CreateSheet, DimensionIn, GuideLineIn,
                      ImportSurvey, ImportTerrain, LayerVisibility, MoveObject, ObjectIfc,
                      ObjectLifecycle, ObjectMaterial, OffsetFace, Presentation, PushPullObject, RestoreRevision, SetGeoref,
                      SetMap, SetObjectScale, SetShadows, SetStyle, TextIn, TransformObject)
from .auth import can_see, current_user, register_auth
from .jobs import register_job_routes
from .sheets import register_sheet_commands
from .building import register_building_commands
from .extensions import register_extension_commands
from formats.igz import save_scene
from core.group import copy_group, world_mesh
from core.group import Group
from core.history import (
    AddCompositionCommand,
    AddDimensionCommand,
    AddGuideCommand,
    AddTextLabelCommand,
    AddGeoPathCommand,
    AddGeoPointsCommand,
    DeleteGroupCommand,
    InsertGroupCommand,
    MoveGroupCommand,
    RenameGroupCommand,
    RotateGroupCommand,
    ScaleGroupCommand,
    SetGroupMaterialCommand,
    SetGroupIfcCommand,
    SetSceneDatumCommand,
    SetTileLayerCommand,
    SetPhotoMeshCommand,
    SetDisplayStyleCommand,
    SetShadowSettingsCommand,
)
from core.dimension import Dimension
from core.guide import Guide
from core.textlabel import TextLabel
from tools.pushpull import push_pull_face
from tools.offset import offset_face
from PySide6.QtGui import QVector3D

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND = (_FRONTEND_ROOT / "dist"
             if (_FRONTEND_ROOT / "dist" / "index.html").is_file()
             else _FRONTEND_ROOT)
_DEFAULT_DATA = Path(__file__).resolve().parents[3] / "var" / "web-data"


def _copy_upload(upload: UploadFile, target: Path) -> None:
    if Path(upload.filename or "").suffix.lower() != ".igz":
        raise HTTPException(415, "Only native IngeTrazo .igz documents are accepted.")
    written = 0
    with target.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "The document exceeds the 100 MiB prototype limit.")
            output.write(chunk)


def _copy_interchange_upload(upload: UploadFile, target: Path) -> None:
    """Copy a bounded external model without trusting its supplied path."""
    written = 0
    with target.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                target.unlink(missing_ok=True)
                raise HTTPException(
                    413, "The interchange file exceeds the 100 MiB prototype limit.",
                )
            output.write(chunk)
    if not written:
        target.unlink(missing_ok=True)
        raise HTTPException(422, "The interchange file is empty.")


def _document_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "invalid_ingetrazo_document", "message": str(exc)},
    )


def create_app(data_root: str | Path | None = None) -> FastAPI:
    ensure_qt()
    app = FastAPI(title="IngeTrazo Web API", version="0.1.0")
    register_error_handlers(app)
    store = DocumentStore(data_root or os.environ.get(
        "INGETRAZO_WEB_DATA", str(_DEFAULT_DATA)))
    jobs = JobManager(store.root / "jobs")
    app.state.document_store = store
    app.state.job_manager = jobs
    app.router.on_shutdown.append(jobs.shutdown)
    register_auth(app, store, jobs)
    register_modeling_commands(app, store)
    register_sheet_commands(app, store)
    register_building_commands(app, store)
    register_extension_commands(app, store)
    register_job_routes(app, store, jobs, _copy_interchange_upload)

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "ingetrazo_version": __version__}

    @app.get("/api/v1/capabilities")
    def capabilities():
        edition_info = describe_edition()
        return {
            "document": {
                "read": ["igz"],
                "write": ["igz"],
                "persistence": "immutable-revisions",
                "download_native": True,
                "restore_revision": True,
            },
            "preview": {
                "formats": ["glb"],
                "mode": "read-only",
                "semantic_nodes": True,
                "embedded_textures": True,
                "reference_images": True,
            },
            "presentation": {
                "camera_home": True,
                "saved_views": True,
                "layers": True,
                "hidden_objects": True,
                "section_planes": True,
                "measurement": True,
            },
            "auth": {"required": app.state.auth.enabled, "roles": ["user", "admin"], "ownership": True},
            "limits": {
                "upload_bytes": MAX_UPLOAD_BYTES,
                "keep_revisions": store.keep_revisions,
                "unpacked_bytes": MAX_UNPACKED_BYTES,
            },
            "modeling": {
                "commands": [
                    "presentation.update", "object.move", "object.rotate",
                    "object.scale", "object.duplicate", "object.delete",
                    "object.rename", "primitive.box.create",
                    "primitive.line.create", "primitive.rectangle.create",
                    "primitive.circle.create", "primitive.arc.create",
                    "face.push_pull", "face.offset", "object.material.set",
                    "dimension.create", "text.create", "guide.create",
                    "object.ifc.set", "bim.quantities.export", "ifc.export",
                    "georef.set", "survey.import", "geopath.create",
                    "map.set",
                    "terrain.import",
                    "style.set", "shadows.set",
                    "sheet.create", "sheet.pdf.export",
                    "layer.set_visibility",
                    "shape.create", "object.flip", "face.follow_me",
                    "edge.fillet", "solid.operation", "text3d.create",
                    "section.fill",
                ],
            },
            "interoperability": {
                "imports": list(import_formats()),
                "exports": list(export_formats()),
                "jobs": {"progress": True, "cancellation": True,
                         "diagnostics": True},
                "skp": {
                    "import": {"available": "skp" in import_formats(), "runs_in": "job process"},
                    "export": {"present": edition_info["skp_export"]["present"],
                               "enabled": edition_info["skp_export"]["enabled"]},
                },
                "edition": edition_info["edition"],
            },
        }

    @app.post("/api/v1/documents/{document_id}/commands/object-ifc",
              status_code=201)
    def set_object_ifc(document_id: str, payload: ObjectIfc):
        """Classify or unclassify a top-level object as native BIM metadata."""
        tag = None if payload.clear else {"class": payload.ifc_class, "name": payload.name}

        def mutate(scene):
            group = find_object(scene, payload.object_id)
            SetGroupIfcCommand(group, tag).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/set-georef",
              status_code=201)
    def set_georef(document_id: str, payload: SetGeoref):
        """Set the WGS84 scene datum and true-north angle."""
        from georef.datum import SceneDatum

        def mutate(scene):
            SetSceneDatumCommand(SceneDatum(
                payload.latitude, payload.longitude, payload.altitude, payload.north,
            )).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/set-map",
              status_code=201)
    def set_map(document_id: str, payload: SetMap):
        """Configure or clear a native licensed XYZ base-map capture."""
        from georef.tiles import PRESETS, TileLayer

        layer = None
        if not payload.clear:
            layer = TileLayer(PRESETS[payload.source], zoom=payload.zoom, radius_m=payload.radius)
            layer.opacity = payload.opacity

        def mutate(scene):
            if not payload.clear and scene.georef is None:
                raise HTTPException(422, "Set the scene datum before adding a map.")
            if layer is not None:
                layer.cap_detail(scene.georef, max_tiles=100)
            SetTileLayerCommand(layer).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/import-terrain",
              status_code=201)
    def import_terrain(document_id: str, request: ImportTerrain):
        """Import a row-major local XYZ grid as a persistent terrain reference."""
        import numpy as np
        from georef.photomesh import ODMAnchor, PhotoMaterial, PhotoMesh, VERTICAL_LOCAL

        base_revision, columns, text = request.base_revision, request.columns, request.text
        points = []
        try:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                values = [float(value) for value in line.replace(";", ",").split(",")]
                if len(values) != 3 or not all(math.isfinite(value) for value in values):
                    raise ValueError
                points.append(values)
        except ValueError as exc:
            raise HTTPException(422, "Each terrain line must contain finite X,Y,Z values.") from exc
        if (len(points) < columns * 2 or len(points) > 10_000
                or len(points) % columns != 0):
            raise HTTPException(422, "The XYZ count must form at least a 2×2 grid and contain at most 10,000 points.")
        rows = len(points) // columns
        triangles = []
        for row in range(rows - 1):
            for column in range(columns - 1):
                a = row * columns + column
                triangles.extend(((a, a + columns, a + 1),
                                  (a + 1, a + columns, a + columns + 1)))
        uvs = [
            (column / (columns - 1), row / (rows - 1))
            for row in range(rows) for column in range(columns)
        ]
        def mutate(scene):
            anchor = None
            if scene.georef is not None:
                anchor = ODMAnchor(
                    scene.georef._east0, scene.georef._north0,
                    scene.georef.zone, scene.georef.northern,
                )
            mesh = PhotoMesh(
                np.asarray(points, dtype=np.float32),
                np.asarray(uvs, dtype=np.float32),
                np.asarray(triangles, dtype=np.uint32),
                [PhotoMaterial("Terrain", None, 0, len(triangles))],
                anchor=anchor,
            )
            mesh.vertical_reference = VERTICAL_LOCAL
            SetPhotoMeshCommand(mesh).do(scene)

        return commit_revision(store, document_id, base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/import-survey",
              status_code=201)
    def import_survey(document_id: str, request: ImportSurvey):
        """Parse standard P,N,E,Z survey text into native local control points."""
        from georef.points import datum_for_rows, parse_points_csv, points_from_rows

        base_revision, csv_text, zone, northern = request.base_revision, request.text, request.zone, request.northern
        try:
            rows = parse_points_csv(csv_text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if len(rows) > 100_000:
            raise HTTPException(422, "A survey import may contain at most 100,000 points.")
        def mutate(scene):
            new_datum = None
            datum = scene.georef
            if datum is None:
                if zone is None or northern is None:
                    raise HTTPException(
                        422, "zone and northern are required when the document has no datum.",
                    )
                datum = datum_for_rows(rows, zone, northern)
                new_datum = datum
            AddGeoPointsCommand(points_from_rows(rows, datum), new_datum).do(scene)

        return commit_revision(store, document_id, base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/create-geopath",
              status_code=201)
    def create_geopath(document_id: str, payload: CreateGeoPath):
        """Create a native surveyed/traced path in local scene metres."""
        from georef.geopath import GeoPath

        closed = payload.closed or payload.surface is not None      # a surface needs a closed boundary

        def mutate(scene):
            path = GeoPath(
                [QVector3D(*point) for point in payload.points],
                closed=closed, name=payload.name, surface=payload.surface,
            )
            AddGeoPathCommand(path).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/set-style",
              status_code=201)
    def set_style(document_id: str, payload: SetStyle):
        """Apply one native built-in display style as a new revision."""
        from core.style import style_by_name

        def mutate(scene):
            SetDisplayStyleCommand(style_by_name(payload.name)).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/set-shadows",
              status_code=201)
    def set_shadows(document_id: str, payload: SetShadows):
        """Persist a geographic solar-shadow study as a new revision."""
        from core.sun import ShadowSettings

        settings = ShadowSettings(
            enabled=payload.enabled, month=payload.month, day=payload.day, hour=payload.hour,
            minute=payload.minute, darkness=payload.darkness, utc_offset=payload.utc_offset,
        )

        def mutate(scene):
            SetShadowSettingsCommand(settings).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/create-sheet",
              status_code=201)
    def create_sheet(document_id: str, payload: CreateSheet):
        """Create a native one-frame architectural sheet composition."""
        from core.composition import Composicion

        def mutate(scene):
            standard = {"top", "bottom", "front", "back", "left", "right", "iso"}
            saved_names = {saved.name for saved in scene.saved_views}
            if payload.view in standard:
                view_key = f"std:{payload.view}"
            elif payload.view.startswith("scene:") and payload.view[6:] in saved_names:
                view_key = payload.view
            else:
                raise HTTPException(422, "view must name a standard view or existing scene.")
            composition = Composicion(
                name=payload.name, paper=payload.paper, landscape=payload.landscape,
                margin_mm=10, border=True,
            )
            frame = composition.default_frame()
            frame.view_key = view_key
            frame.scale_n = payload.scale
            frame.style = "vectorial"
            frame.border = True
            frame.show_title = True
            frame.title_text = payload.name
            composition.frames.append(frame)
            AddCompositionCommand(composition).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post("/api/v1/documents/{document_id}/commands/create-annotation",
              status_code=201)
    def create_annotation(document_id: str, payload: Annotation):
        """Create a native dimension, leader label, guide line, or guide point."""
        layer = payload.layer

        def mutate(scene):
            if layer is not None and scene.layer(layer) is None:
                raise HTTPException(422, f"Unknown layer: {layer}")
            if isinstance(payload, DimensionIn):
                AddDimensionCommand(Dimension(
                    QVector3D(*payload.a), QVector3D(*payload.b), QVector3D(*payload.offset),
                    layer=layer, text=payload.text or None, axis=payload.axis,
                )).do(scene)
            elif isinstance(payload, TextIn):
                AddTextLabelCommand(TextLabel(
                    QVector3D(*payload.anchor), QVector3D(*payload.offset), payload.text.strip(), layer=layer,
                )).do(scene)
            elif isinstance(payload, GuideLineIn):
                AddGuideCommand(Guide(QVector3D(*payload.point), QVector3D(*payload.direction))).do(scene)
            else:
                origin = None if payload.origin is None else QVector3D(*payload.origin)
                AddGuideCommand(Guide(QVector3D(*payload.point), None, origin)).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate,
                                restore_identities=False)

    @app.get("/api/v1/documents")
    def list_documents(request: Request):
        user = current_user(request)
        return {"documents": store.list(lambda owner: can_see(user, owner))}

    @app.post("/api/v1/documents", status_code=201)
    def create_document(request: Request, file: UploadFile = File(...)):
        with tempfile.TemporaryDirectory(prefix="ingetrazo-web-") as directory:
            source = Path(directory) / "document.igz"
            _copy_upload(file, source)
            try:
                return store.create(source, file.filename or "Untitled.igz",
                                    owner=current_user(request).name if request.app.state.auth.enabled else None)
            except Exception as exc:
                raise _document_error(exc) from exc

    @app.post("/api/v1/documents/blank", status_code=201)
    def create_blank_document(request: Request, payload: BlankDocument):
        """Create an empty document: a place to start modelling without uploading a file."""
        from core.scene import Scene

        with tempfile.TemporaryDirectory(prefix="ingetrazo-web-") as directory:
            source = Path(directory) / "document.igz"
            save_scene(Scene(), source)
            name = payload.name if payload.name.lower().endswith(".igz") else f"{payload.name}.igz"
            return store.create(source, name,
                                owner=current_user(request).name if request.app.state.auth.enabled else None)

    @app.get("/api/v1/documents/{document_id}")
    def get_document(document_id: str):
        try:
            return store.get(document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc

    @app.post("/api/v1/documents/{document_id}/revisions", status_code=201)
    def create_revision(document_id: str, file: UploadFile = File(...)):
        with tempfile.TemporaryDirectory(prefix="ingetrazo-web-") as directory:
            source = Path(directory) / "document.igz"
            _copy_upload(file, source)
            try:
                return store.add_revision(document_id, source)
            except DocumentNotFoundError as exc:
                raise HTTPException(404, "Document not found.") from exc
            except Exception as exc:
                raise _document_error(exc) from exc

    def apply_presentation(document_id: str, base_revision: int, layers: dict[str, bool],
                           hidden_objects: dict[str, bool]):
        """Apply an atomic presentation edit as a new native revision."""
        def mutate(scene):
            known_layers = {layer.name: layer for layer in scene.layers}
            unknown_layers = sorted(set(layers) - set(known_layers))
            if unknown_layers:
                raise HTTPException(
                    422, f"Unknown layer{'s' if len(unknown_layers) != 1 else ''}: "
                    + ", ".join(unknown_layers),
                )
            known_objects = scene_object_index(scene)
            unknown_objects = sorted(set(hidden_objects) - set(known_objects))
            if unknown_objects:
                raise HTTPException(
                    422,
                    f"Unknown object ID{'s' if len(unknown_objects) != 1 else ''}: "
                    + ", ".join(unknown_objects),
                )
            for name, visible in layers.items():
                known_layers[name].visible = visible
            for uid, hidden in hidden_objects.items():
                known_objects[uid].hidden = hidden

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/presentation",
              status_code=201)
    def update_presentation(document_id: str, payload: Presentation):
        """Persist layer and object visibility in one conflict-checked revision."""
        return apply_presentation(document_id, payload.base_revision, payload.layers, payload.hidden_objects)

    @app.post("/api/v1/documents/{document_id}/commands/layer-visibility",
              status_code=201)
    def set_layer_visibility(document_id: str, payload: LayerVisibility):
        """Backward-compatible adapter for the first layer-only command."""
        return apply_presentation(document_id, payload.base_revision, payload.changes, {})

    @app.post("/api/v1/documents/{document_id}/commands/move-object",
              status_code=201)
    def move_object(document_id: str, payload: MoveObject):
        """Move one or more objects and persist the result as a revision."""
        ids = payload.ids()

        def mutate(scene):
            world = QVector3D(*payload.delta)
            # Resolve every target first; a listed ancestor already carries its parts.
            targets = [(object_id, find_object(scene, object_id))
                       for object_id in without_descendants(ids)]
            for object_id, group in targets:
                offset = world
                if "/" in object_id:
                    # Carry the world offset into the parent's frame (directions only).
                    inverse, ok = parent_frame(scene, object_id).inverted()
                    if not ok:
                        raise HTTPException(422, "The parent placement cannot be inverted.")
                    offset = inverse.mapVector(world)
                MoveGroupCommand(group, offset).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/transform-object",
              status_code=201)
    def transform_object(document_id: str, request: TransformObject):
        """Rotate or scale one object (nested ones too) about its bounding-box center."""
        base_revision, object_id, operation = request.base_revision, request.object_id, request.operation
        axis_name, degrees, factors = request.axis, request.degrees, request.factors
        def mutate(scene):
            group = find_object(scene, object_id)
            frame = ParentFrame(scene, object_id)
            center = group_center(group)         # in the frame the object lives in
            if operation == "rotate":
                axes = {
                    "x": QVector3D(1, 0, 0),
                    "y": QVector3D(0, 1, 0),
                    "z": QVector3D(0, 0, 1),
                }
                RotateGroupCommand(
                    group, center, frame.direction(axes[axis_name]),
                    -float(degrees) if frame.mirrored else float(degrees),
                ).do(scene)
            else:
                ScaleGroupCommand(
                    group, center, tuple(float(value) for value in factors),
                    axes=frame.axes(),
                ).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/set-object-scale",
              status_code=201)
    def set_object_scale(document_id: str, payload: SetObjectScale):
        """Take one object to an absolute scale along its own axes, about its origin
        (a component) or its box centre (a group). 1.0 is unscaled."""
        from core.group_scale import scale_command

        def mutate(scene):
            group = find_object(scene, payload.object_id)
            command = scale_command(group, tuple(float(v) for v in payload.scale))
            if command is None:
                raise HTTPException(422, "The object already has that scale.")
            command.do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/object-lifecycle",
              status_code=201)
    def object_lifecycle(document_id: str, payload: ObjectLifecycle):
        """Duplicate, delete or rename objects as a native revision."""
        operation, object_id = payload.operation, payload.object_id

        def mutate(scene):
            if payload.object_ids is not None:
                targets = [find_object(scene, item) for item in without_descendants(payload.object_ids)]
                for group in targets:
                    DeleteGroupCommand(group).do(scene)
                return
            group = find_object(scene, object_id)
            if operation == "duplicate":
                duplicate = copy_group(group, QVector3D(*payload.delta))
                InsertGroupCommand(duplicate).do(scene)
            elif operation == "delete":
                DeleteGroupCommand(group).do(scene)
            else:
                RenameGroupCommand(group, payload.name).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/create-box",
              status_code=201)
    def create_box(document_id: str, payload: CreateBox):
        """Create an axis-aligned solid box as a new top-level group."""
        def mutate(scene):
            ox, oy, oz = payload.origin
            width, depth, height = payload.size
            p000 = QVector3D(ox, oy, oz)
            p100 = QVector3D(ox + width, oy, oz)
            p110 = QVector3D(ox + width, oy + depth, oz)
            p010 = QVector3D(ox, oy + depth, oz)
            p001 = QVector3D(ox, oy, oz + height)
            p101 = QVector3D(ox + width, oy, oz + height)
            p111 = QVector3D(ox + width, oy + depth, oz + height)
            p011 = QVector3D(ox, oy + depth, oz + height)
            group = Group(name=payload.name)
            for corners in (
                [p000, p010, p110, p100],
                [p001, p101, p111, p011],
                [p000, p100, p101, p001],
                [p100, p110, p111, p101],
                [p110, p010, p011, p111],
                [p010, p000, p001, p011],
            ):
                group.mesh.add_face(corners)
            InsertGroupCommand(group).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/create-planar",
              status_code=201)
    def create_planar(document_id: str, payload: Planar):
        """Create numeric line, planar face, or arc geometry in world XY."""
        base_revision, operation, origin, plane = payload.base_revision, payload.operation, payload.origin, payload.plane
        name = payload.name or operation.title()
        if operation == "line":
            end = payload.end
        elif operation == "rectangle":
            size = payload.size
        else:
            radius, segments = payload.radius, payload.segments
            if operation == "arc":
                start_degrees, sweep_degrees = payload.start_degrees, payload.sweep_degrees
        def mutate(scene):
            ox, oy, oz = (float(value) for value in origin)
            def planar(u: float, v: float) -> QVector3D:
                if plane == "xz":
                    return QVector3D(ox + u, oy, oz + v)
                if plane == "yz":
                    return QVector3D(ox, oy + u, oz + v)
                return QVector3D(ox + u, oy + v, oz)

            group = Group(name=name)
            if operation == "line":
                group.mesh.add_edge(
                    QVector3D(ox, oy, oz),
                    QVector3D(*(float(value) for value in end)),
                )
            elif operation == "rectangle":
                width, depth = (float(value) for value in size)
                group.mesh.add_face([
                    planar(0, 0),
                    planar(width, 0),
                    planar(width, depth),
                    planar(0, depth),
                ])
            elif operation == "circle":
                points = [
                    planar(
                        float(radius) * math.cos(2 * math.pi * index / segments),
                        float(radius) * math.sin(2 * math.pi * index / segments),
                    )
                    for index in range(segments)
                ]
                group.mesh.add_face(points)
                group.mesh.tag_curve(points, closed=True)
            else:
                start = math.radians(float(start_degrees))
                sweep = math.radians(float(sweep_degrees))
                points = [
                    planar(
                        float(radius) * math.cos(start + sweep * index / segments),
                        float(radius) * math.sin(start + sweep * index / segments),
                    )
                    for index in range(segments + 1)
                ]
                for first, second in zip(points, points[1:]):
                    group.mesh.add_edge(first, second)
                group.mesh.tag_curve(points, closed=False)
            InsertGroupCommand(group).do(scene)

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/push-pull",
              status_code=201)
    def push_pull_object(document_id: str, payload: PushPullObject):
        """Push/pull one planar face of an object (nested ones too)."""
        base_revision, object_id, direction = payload.base_revision, payload.object_id, payload.direction
        distance, keep_base, face_point = payload.distance, payload.keep_base, payload.face_point
        def mutate(scene):
            group = find_object(scene, object_id)
            frame = ParentFrame(scene, object_id)
            group.materialize()
            faces = list(group.mesh.faces)
            if not faces:
                raise HTTPException(422, "The selected object has no face to push/pull.")
            if direction == "normal":
                if len(faces) != 1:
                    raise HTTPException(
                        422, "Choose a signed world-axis face for a multi-face object.",
                    )
                face = faces[0]
            else:
                sign = -1.0 if direction[0] == "-" else 1.0
                axis_name = direction[1]
                axis = frame.direction(QVector3D(
                    sign if axis_name == "x" else 0,
                    sign if axis_name == "y" else 0,
                    sign if axis_name == "z" else 0,
                ))
                candidates = [
                    item for item in faces
                    if QVector3D.dotProduct(item.normal().normalized(), axis) > 0.95
                ]
                if not candidates:
                    raise HTTPException(
                        422, f"The selected object has no face oriented {direction}.",
                    )
                if face_point is not None:
                    # The face the user clicked: nearest plane, then nearest centroid.
                    target = frame.point(QVector3D(*face_point))
                    face = min(candidates, key=lambda item: (
                        round(abs(QVector3D.dotProduct(
                            item.normal().normalized(), target - item.centroid())), 6),
                        (item.centroid() - target).length(),
                    ))
                else:
                    face = max(
                        candidates,
                        key=lambda item: QVector3D.dotProduct(item.centroid(), axis),
                    )
            result = push_pull_face(
                scene, face, frame.length(float(distance)), group=group, keep_base=keep_base,
            )
            if result["refused"]:
                raise HTTPException(
                    422, "Push/pull was refused because it would break the solid.",
                )
            return result

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/offset-face",
              status_code=201)
    def offset_object_face(document_id: str, payload: OffsetFace):
        """Offset the sole planar face of a top-level object."""
        base_revision, object_id, distance = payload.base_revision, payload.object_id, payload.distance
        def mutate(scene):
            group = find_object(scene, object_id)
            group.materialize()
            if len(group.mesh.faces) != 1:
                raise HTTPException(
                    422, "Offset currently requires an object with exactly one face.",
                )
            result = offset_face(
                scene, group.mesh.faces[0], float(distance), group=group,
            )
            if result is None:
                raise HTTPException(
                    422, "The requested distance consumes the planar face.",
                )
            return result

        return commit_revision(store, document_id, base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/object-material",
              status_code=201)
    def set_object_material(document_id: str, payload: ObjectMaterial):
        """Set or clear an anonymous colour/opacity material on an object."""
        ids = payload.ids()
        material = None
        if not payload.clear and payload.texture is not None:
            material = library.texture_material(payload.texture)
            if 0 <= payload.opacity < 0.999:
                material["opacity"] = payload.opacity
        elif not payload.clear:
            material = {"color": list(payload.color)}
            if payload.opacity < 0.999:
                material["opacity"] = payload.opacity

        def mutate(scene):
            for group in [find_object(scene, item) for item in ids]:
                SetGroupMaterialCommand(group, material).do(scene)

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post("/api/v1/documents/{document_id}/commands/restore-revision",
              status_code=201)
    def restore_revision(document_id: str, payload: RestoreRevision):
        """Restore an older native revision by copying it into a new revision.

        With ``history`` ``undo`` or ``redo`` it is a step through the document's history:
        the source must be the revision Undo (or Redo) leads to, and the new revision
        records the move so the position can be rebuilt (revision_history.py)."""
        marker = None
        if payload.history:
            try:
                state = store.get(document_id)["undo"]
            except DocumentNotFoundError as exc:
                raise HTTPException(404, "Document not found.") from exc
            expected = state["undo_to"] if payload.history == "undo" else state["redo_to"]
            if expected is None:
                raise HTTPException(422, f"There is nothing to {payload.history}.")
            if payload.source_revision != expected:
                raise HTTPException(422, f"{payload.history.capitalize()} leads to revision {expected}, not {payload.source_revision}.")
            marker = {"move": payload.history, "to": payload.source_revision}
        return commit_revision(
            store, document_id, payload.base_revision, lambda scene: None,
            source_revision=payload.source_revision,
            missing_revision_detail="Revision to restore was not found.",
            history=marker,
        )

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/download",
             response_class=FileResponse)
    def download_revision(document_id: str, revision: int):
        try:
            path = store.revision_path(document_id, revision)
            name = store.get(document_id)["name"]
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        return FileResponse(
            path, media_type="application/octet-stream", filename=name,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/quantities.csv")
    def download_quantities(document_id: str, revision: int):
        """Export the native BIM takeoff table for one immutable revision."""
        from core.bim import quantities_csv
        try:
            scene = load_igz(store.revision_path(document_id, revision))
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        return Response(
            quantities_csv(scene), media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="quantities-r{revision}.csv"',
                "Cache-Control": "private, max-age=31536000, immutable",
            },
        )

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/model.ifc")
    def download_ifc(document_id: str, revision: int):
        """Export tagged native objects as IFC4 for one immutable revision."""
        from formats.ifc import save_ifc
        try:
            scene = load_igz(store.revision_path(document_id, revision))
            record = store.get(document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        with tempfile.TemporaryDirectory(prefix="ingetrazo-ifc-") as directory:
            target = Path(directory) / "model.ifc"
            save_ifc(scene, target, project_name=Path(record["name"]).stem)
            content = target.read_bytes()
        return Response(
            content, media_type="application/step",
            headers={
                "Content-Disposition": f'attachment; filename="model-r{revision}.ifc"',
                "Cache-Control": "private, max-age=31536000, immutable",
            },
        )

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/sheets/{sheet_index}.pdf")
    def download_sheet_pdf(document_id: str, revision: int, sheet_index: int):
        """Render one native composition as an exact-size vector PDF."""
        from .sheet_pdf import render_sheet_pdf
        try:
            scene = load_igz(store.revision_path(document_id, revision))
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        if not 0 <= sheet_index < len(scene.compositions):
            raise HTTPException(404, "Sheet not found.")
        try:
            content = render_sheet_pdf(scene, scene.compositions[sheet_index])
        except (OSError, ValueError) as exc:
            raise HTTPException(422, f"Could not render sheet: {exc}") from exc
        return Response(
            content, media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="sheet-{sheet_index + 1}-r{revision}.pdf"'
                ),
                "Cache-Control": "private, max-age=31536000, immutable",
            },
        )

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/preview",
             response_class=FileResponse)
    def preview_revision(document_id: str, revision: int):
        started = time.perf_counter()
        try:
            path = store.preview_path(document_id, revision)
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        return FileResponse(
            path, media_type="model/gltf-binary",
            filename=f"{document_id}-r{revision}.glb",
            headers={
                "Server-Timing": f"ingetrazo;dur={elapsed_ms:.2f}",
                "X-IngeTrazo-Preview-Milliseconds": f"{elapsed_ms:.2f}",
                "Cache-Control": "private, no-cache",
            },
        )

    @app.post("/api/v1/documents/inspect")
    def inspect_document(file: UploadFile = File(...)):
        with tempfile.TemporaryDirectory(prefix="ingetrazo-web-") as directory:
            source = Path(directory) / "document.igz"
            _copy_upload(file, source)
            try:
                return inspect_igz(source)
            except Exception as exc:  # loader gives actionable format errors
                raise _document_error(exc) from exc

    @app.post("/api/v1/documents/preview", response_class=FileResponse)
    def preview_document(file: UploadFile = File(...)):
        # FileResponse streams after this function returns, so the temporary
        # directory must clean itself up only after the response has closed.
        directory = tempfile.TemporaryDirectory(prefix="ingetrazo-web-")
        source = Path(directory.name) / "document.igz"
        target = Path(directory.name) / "preview.glb"
        started = time.perf_counter()
        try:
            _copy_upload(file, source)
            summary = preview_igz(source, target)
        except Exception as exc:
            directory.cleanup()
            if isinstance(exc, HTTPException):
                raise
            raise _document_error(exc) from exc
        response = FileResponse(target, media_type="model/gltf-binary",
                                filename="preview.glb")
        encoded_summary = base64.urlsafe_b64encode(
            json.dumps(summary, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        response.headers["X-IngeTrazo-Summary"] = encoded_summary
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f"ingetrazo;dur={elapsed_ms:.2f}"
        response.headers["X-IngeTrazo-Preview-Milliseconds"] = f"{elapsed_ms:.2f}"
        response.headers["Cache-Control"] = "no-store"
        response.background = _TemporaryDirectoryCleanup(directory)
        return response

    if _FRONTEND.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
    return app


class _TemporaryDirectoryCleanup:
    """Starlette background task compatible cleanup without another package."""

    def __init__(self, directory: tempfile.TemporaryDirectory) -> None:
        self.directory = directory

    async def __call__(self) -> None:
        self.directory.cleanup()


app = create_app()

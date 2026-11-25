"""Commands for openings, terrain and material files (ported from IngeTrazo 0.6.3).

Like every command here they load ``base_revision``, run the desktop's own
routine on the native scene, and save the result as the next revision:

* ``set-cut-opening`` marks windows and doors that cut their own hole in the
  wall they sit on (``core.openings``); :func:`commands.commit_revision` keeps
  the holes in step with every later edit.
* ``terrain-create``, ``terrain-deform`` and ``terrain-stamp`` make and shape
  editable ground (``core.terrain_mesh``, ``core.terrain_build``).
* ``materials`` lists the document's own materials; ``materials/import`` adds
  those of an ``.igmat`` or SketchUp ``.skm`` file; ``materials.igmat``
  exports them.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from PySide6.QtGui import QMatrix4x4, QVector3D

from .commands import commit_revision, find_object, target_ids
from .document_store import DocumentNotFoundError, DocumentStore, RevisionNotFoundError
from .scene_service import load_igz
from .schemas import SetCutOpening, TerrainCreate, TerrainDeform, TerrainStamp

#: Material files are small; anything larger is refused before it is read.
MAX_MATERIAL_BYTES = 50 * 1024 * 1024
MATERIAL_SUFFIXES = (".igmat", ".skm")


def _world_xform(scene, object_id: str):
    """The placement that takes the object's mesh to world coordinates, through its
    parents, or ``None`` when its mesh is already in world coordinates."""
    parts = object_id.split("/")
    total = None
    for depth in range(1, len(parts) + 1):
        group = find_object(scene, "/".join(parts[:depth]), editable=False)
        xform = getattr(group, "xform", None)
        if xform is not None:
            total = QMatrix4x4(xform) if total is None else total * xform
    return total


def _terrain_target(scene, object_id: str):
    group = find_object(scene, object_id)
    if getattr(group, "billboard", False) or not group.mesh.faces:
        raise HTTPException(422, "Pick a terrain object (a group of triangles).")
    return group.mesh, _world_xform(scene, object_id)


def register_building_commands(app: FastAPI, store: DocumentStore) -> None:
    base = "/api/v1/documents/{document_id}/commands"

    @app.post(f"{base}/set-cut-opening", status_code=201)
    def set_cut_opening(document_id: str, payload: SetCutOpening):
        """Mark (or unmark) windows and doors «Cut opening»: each opens its own hole in the
        wall it is placed on, through the wall when it is thin enough, and every copy of a
        component does the same. Unmarking closes the hole again."""
        from core.openings import SetCutOpeningCommand, cutting_targets

        ids = target_ids(payload.model_dump())

        def mutate(scene):
            groups = [find_object(scene, object_id) for object_id in ids]
            targets = cutting_targets(scene, groups)
            if not targets:
                raise HTTPException(422, "Select a group or component to cut an opening.")
            SetCutOpeningCommand(targets, payload.on).do(scene)
            return {"objects": len(targets)}

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/terrain-create", status_code=201)
    def terrain_create(document_id: str, payload: TerrainCreate):
        """A new terrain object: a grid (flat, or with natural ``relief``), a triangulated
        network through survey points, or a smooth ground through contour lines."""
        from core.history import InsertGroupCommand
        from core.terrain_build import TerrainBuildError, contour_terrain, points_terrain
        from core.terrain_mesh import grid_terrain, terrain_group

        try:
            if payload.points is not None:
                vertices, triangles = points_terrain(
                    [QVector3D(*p) for p in payload.points], payload.max_side)
            elif payload.segments is not None:
                vertices, triangles = contour_terrain(
                    [(QVector3D(*a), QVector3D(*b)) for a, b in payload.segments], payload.cell)
            else:
                vertices, triangles = grid_terrain(
                    QVector3D(*payload.corner_a), QVector3D(*payload.corner_b),
                    payload.cell, payload.relief)
        except TerrainBuildError as error:
            raise HTTPException(422, str(error)) from error
        if not triangles:
            raise HTTPException(422, "The terrain has no area.")

        def mutate(scene):
            group = terrain_group(vertices, triangles, payload.name)
            InsertGroupCommand(group).do(scene)
            return {"object_id": f"group:{scene.groups.index(group)}", "triangles": len(triangles)}

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/terrain-deform", status_code=201)
    def terrain_deform(document_id: str, payload: TerrainDeform):
        """Push the ground up or down at a point: all of ``height`` at the centre, nothing
        at ``radius``, a smooth curve in between."""
        from core.terrain_mesh import DeformTerrainCommand

        def mutate(scene):
            mesh, xform = _terrain_target(scene, payload.object_id)
            command = DeformTerrainCommand(mesh, QVector3D(*payload.center), payload.radius,
                                           payload.height, xform)
            command.do(scene)
            if not command.moved:
                raise HTTPException(422, "No ground lies within that radius of the point.")
            return {"vertices_moved": command.moved}

        return commit_revision(store, document_id, payload.base_revision, mutate)

    @app.post(f"{base}/terrain-stamp", status_code=201)
    def terrain_stamp(document_id: str, payload: TerrainStamp):
        """Cut a level platform the shape of a footprint into the ground at ``height``, with
        a straight slope out to ``slope`` metres that meets the ground."""
        from core.terrain_mesh import StampCommand

        def mutate(scene):
            mesh, xform = _terrain_target(scene, payload.object_id)
            command = StampCommand(mesh, [QVector3D(*p) for p in payload.footprint],
                                   payload.height, payload.slope, xform)
            command.do(scene)
            if not command.result:
                raise HTTPException(422, "The footprint does not lie over the ground.")
            return {"vertices_moved": command.result}

        return commit_revision(store, document_id, payload.base_revision, mutate)

    def _scene_at(document_id: str, revision: int):
        try:
            return load_igz(store.revision_path(document_id, revision))
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/materials")
    def list_materials(document_id: str, revision: int):
        """The document's own named materials, to paint with by name."""
        scene = _scene_at(document_id, revision)
        return {"materials": [
            {"name": name,
             "color": list(material.color) if material.color is not None else None,
             "textured": material.texture is not None,
             "opacity": material.opacity}
            for name, material in sorted(scene.materials.items())]}

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/materials.igmat")
    def export_materials(document_id: str, revision: int):
        """The document's materials as one ``.igmat`` file, images packed inside."""
        from formats.igmat import save_materials
        scene = _scene_at(document_id, revision)
        if not scene.materials:
            raise HTTPException(422, "The document has no named materials to export.")
        with tempfile.TemporaryDirectory(prefix="ingetrazo-igmat-") as directory:
            target = Path(directory) / "materials.igmat"
            save_materials(target, scene.materials.values())
            content = target.read_bytes()
        return Response(content, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="materials-r{revision}.igmat"'})

    @app.post("/api/v1/documents/{document_id}/materials/import", status_code=201)
    def import_materials(document_id: str, base_revision: int = Form(...),
                         file: UploadFile = File(...)):
        """Add the materials of an ``.igmat`` or SketchUp ``.skm`` file to the document. A
        material whose name the document already uses replaces it."""
        from formats.igmat import MaterialFileError, load_materials
        from formats.skm import load_skm

        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in MATERIAL_SUFFIXES:
            raise HTTPException(415, "Choose an .igmat or .skm material file.")
        with tempfile.TemporaryDirectory(prefix="ingetrazo-material-") as directory:
            source = Path(directory) / f"materials{suffix}"
            written = 0
            with source.open("wb") as output:
                while chunk := file.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_MATERIAL_BYTES:
                        raise HTTPException(413, "The material file exceeds 50 MiB.")
                    output.write(chunk)
            try:
                materials = (load_skm if suffix == ".skm" else load_materials)(source)
            except (MaterialFileError, OSError) as error:
                raise HTTPException(422, f"The material file cannot be read: {error}") from error
        if not materials:
            raise HTTPException(422, "The file holds no material to import.")

        def mutate(scene):
            for material in materials:
                scene.materials[material.name] = material
            scene.version += 1
            return {"materials": [material.name for material in materials]}

        return commit_revision(store, document_id, base_revision, mutate)

"""Framework-neutral access to IngeTrazo documents for web clients.

Nothing in this module constructs a QApplication, window, viewport, or OpenGL
context. Keeping this layer independent from FastAPI also makes it usable by
workers and straightforward to test.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import zipfile

from core.purge import iter_groups
from core.scene import Scene
from formats.gltf import save_glb
from formats.igz import load_into

MAX_CONTAINER_ENTRIES = 4096
MAX_UNPACKED_BYTES = 512 * 1024 * 1024
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
_ZIP_MAGIC = b"PK\x03\x04"


def _point(value) -> list[float] | None:
    if value is None:
        return None
    return [float(value.x()), float(value.y()), float(value.z())]


def _camera_summary(scene: Scene) -> dict[str, Any] | None:
    camera = scene.camera_home
    if not isinstance(camera, dict):
        return None
    target = camera.get("target")
    if not isinstance(target, (list, tuple)) or len(target) != 3:
        return None
    try:
        return {
            "target": [float(value) for value in target],
            "distance": float(camera.get("distance", 20.0)),
            "yaw": float(camera.get("yaw", -0.7853981633974483)),
            "pitch": float(camera.get("pitch", 0.5235987755982988)),
            "fov_deg": float(camera.get("fov_deg", 45.0)),
            "perspective": bool(camera.get("perspective", True)),
            "two_point": bool(camera.get("two_point", False)),
        }
    except (TypeError, ValueError):
        return None


def _outline(scene: Scene, limit: int = 500) -> dict[str, Any]:
    """A bounded semantic object tree for the read-only web inspector."""
    from core.layers import DEFAULT_LAYER

    remaining = limit
    truncated = False

    def one(group, object_id: str, depth: int = 0,
            preview_id: str | None = None):
        nonlocal remaining, truncated
        if remaining <= 0 or depth >= 32:
            truncated = True
            return None
        remaining -= 1
        item = {
            "id": object_id,
            "preview_id": preview_id or object_id,
            "visibility_id": object_id,
            "native_id": str(group.uid),
            "name": str(group.name),
            "kind": "component" if group.is_component() else "group",
            "layer": str(group.layer or DEFAULT_LAYER),
            "visible": bool(scene.entity_visible(group)),
            "hidden": bool(group.hidden),
            "geometry": {
                "vertices": len(group.mesh.vertices),
                "edges": len(group.mesh.edges),
                "faces": len(group.mesh.faces),
            },
            "children": [],
        }
        from core.group_scale import group_scale
        item["scale"] = [round(v, 6) for v in group_scale(group)]
        from core.openings import wants_opening
        if wants_opening(group):
            item["cut_opening"] = True
        if isinstance(group.ifc, dict):
            item["ifc"] = {
                key: str(group.ifc[key]) for key in ("class", "name", "id")
                if key in group.ifc
            }
        if isinstance(group.material, dict):
            item["material"] = {
                key: group.material[key]
                for key in ("color", "opacity", "mat")
                if key in group.material
            }
        for index, child in enumerate(group.children):
            child_item = one(
                child, f"{object_id}/{index}", depth + 1,
                preview_id or object_id,
            )
            if child_item is not None:
                item["children"].append(child_item)
        return item

    items = []
    for index, group in enumerate(scene.groups):
        item = one(group, f"group:{index}")
        if item is not None:
            items.append(item)
    return {"items": items, "truncated": truncated, "limit": limit}


def _faceme_part(placed, mesh, base_part: dict) -> dict[str, Any] | None:
    """The part for one face-me figure, or ``None`` when it has no geometry.

    The figure is exported in its stored pose together with what the browser needs
    to turn it toward the camera about the vertical through its feet, as the desktop
    viewport does every frame: a lone textured quad (``kind: "quad"``) is rebuilt by
    the browser square to the camera, anything else (a cut-out outline, vector art)
    is rotated whole (``kind: "mesh"``) from the heading of its largest face.
    """
    import math

    from formats.meshexport import _feet

    kind = getattr(placed, "billboard", False)
    feet = _feet(mesh)
    faces = list(mesh.faces)
    if not kind or feet is None or not faces:
        return None
    points = [v.position for v in mesh.vertices]
    xs, ys, zs = ([p.x() for p in points], [p.y() for p in points], [p.z() for p in points])
    textured = any((f.attrs.get("texture") or {}).get("path") for f in faces)
    quad = kind is True and textured and len(faces) == 1
    info: dict[str, Any] = {
        "kind": "quad" if quad else "mesh",
        "feet": [feet.x(), feet.y(), feet.z()],
        "width": math.hypot(max(xs) - min(xs), max(ys) - min(ys)),
        "height": max(zs) - min(zs),
    }
    if not quad:
        big = max(faces, key=lambda f: f.area())
        normal = big.normal()
        if math.hypot(normal.x(), normal.y()) > 1e-9:
            info["heading"] = math.atan2(normal.y(), normal.x())
    return {**base_part, "faceme": info, "faces": faces, "edges": []}


def _group_parts(scene: Scene, group, object_id: str, parent_matrix, inherited: dict[str, Any]):
    """Yield one part for ``group`` and one for every nested object below it.

    Each nested object is its own node, named by its hierarchy path
    (``group:2/0/1``), so the browser can pick, select and hide it by itself. The
    placement matrices compose from the root down, a child with no paint of its own
    wears its ancestors', and a hidden ancestor hides everything inside it. So does
    an ancestor on a hidden layer: ``layer_path`` lists the layers from the root down
    (each once), and the browser shows the object only while all of them are visible.
    """
    from PySide6.QtGui import QMatrix4x4

    from core.group import transformed_mesh
    from core.layers import DEFAULT_LAYER
    from core.materials import effective_attrs

    matrix = group.xform if parent_matrix is None else (
        parent_matrix if group.xform is None else parent_matrix * group.xform)
    material = group.material if isinstance(group.material, dict) else inherited.get("material")
    layer_name = str(group.layer or inherited.get("layer") or DEFAULT_LAYER)
    layer = scene.layer(layer_name)
    hidden = bool(inherited.get("hidden")) or bool(group.hidden)
    layer_visible = True if layer is None else bool(layer.visible)
    layer_path = list(inherited.get("layer_path") or ())
    if layer_name not in layer_path:
        layer_path.append(layer_name)
    path_visible = [True if scene.layer(name) is None else bool(scene.layer(name).visible)
                    for name in layer_path]
    part = {
        "id": object_id,
        "visibility_id": object_id,
        "native_id": str(group.uid),
        "name": str(group.name),
        "kind": "component" if group.is_component() else "group",
        "layer": layer_name,
        "layer_visible": layer_visible,
        "layer_path": layer_path,
        "layer_path_visible": path_visible,
        "visible": layer_visible and not hidden and all(path_visible),
        "locked": bool(layer is not None and layer.locked),
        "hidden": hidden,
        **({"material": {key: material[key] for key in ("color", "opacity", "mat") if key in material}}
           if isinstance(material, dict) else {}),
    }
    mesh = group.mesh if matrix is None else transformed_mesh(group.mesh, matrix)
    if getattr(group, "billboard", False):
        figure = _faceme_part(group, mesh, {**part, "name": str(group.name or part["name"])})
        if figure is not None:
            yield figure
    elif mesh.faces or any(not edge.faces for edge in mesh.edges):
        if isinstance(material, dict) and mesh.faces:
            if mesh is group.mesh:
                mesh = transformed_mesh(mesh, QMatrix4x4())          # never repaint the shared prototype
            for face in mesh.faces:
                face.attrs = dict(effective_attrs(face.attrs, material))
        # ``face_ids`` is each face's place in the object's own mesh: the browser
        # names a face by it when its group is entered for editing.
        yield {**part, "faces": mesh.faces, "edges": [e for e in mesh.edges if not e.faces],
               "face_ids": list(range(len(mesh.faces)))}
    for index, child in enumerate(group.children):
        yield from _group_parts(scene, child, f"{object_id}/{index}", matrix,
                                {"material": material, "layer": layer_name, "hidden": hidden,
                                 "layer_path": layer_path})


def _semantic_parts(scene: Scene) -> list[dict[str, Any]]:
    """World-space faces grouped by the top-level object users recognize."""
    from core.group import world_mesh
    from core.layers import DEFAULT_LAYER, layer_of
    from core.materials import effective_attrs
    from core.mesh import Mesh
    from core.texture import fit_uv_affine
    parts: list[dict[str, Any]] = []
    loose_by_layer: dict[str, list] = {}
    loose_ids: dict[str, list[int]] = {}
    for face_index, face in enumerate(scene.loose_mesh.faces):
        if scene.entity_hidden(face):
            continue
        loose_by_layer.setdefault(layer_of(face), []).append(face)
        loose_ids.setdefault(layer_of(face), []).append(face_index)
    loose_edges: dict[str, list] = {}
    for edge in scene.loose_mesh.edges:
        if edge.faces or scene.entity_hidden(edge):
            continue
        loose_edges.setdefault(layer_of(edge), []).append(edge)
    for layer_name in loose_edges:
        loose_by_layer.setdefault(layer_name, [])
        loose_ids.setdefault(layer_name, [])
    for layer_name, faces in loose_by_layer.items():
        layer = scene.layer(layer_name)
        parts.append({
            "id": f"loose:{layer_name}",
            "name": ("Loose geometry" if layer_name == DEFAULT_LAYER
                     else f"Loose geometry — {layer_name}"),
            "kind": "loose",
            "layer": layer_name,
            "visible": True if layer is None else bool(layer.visible),
            "layer_visible": True if layer is None else bool(layer.visible),
            "locked": bool(layer is not None and layer.locked),
            "hidden": False,
            "faces": faces,
            "edges": loose_edges.get(layer_name, []),
            # The face's position in the scene's loose mesh, so a picked
            # triangle can be mapped back to the face it came from.
            "face_ids": loose_ids[layer_name],
        })
    # Imported reference images are deliberately not topology, so ordinary
    # interchange exports continue to omit them. A web preview still needs to
    # show the scans users trace over; represent each one as a temporary
    # textured quad carried only by this semantic preview transport.
    for index, image in enumerate(scene.image_planes):
        if not image.path:
            continue
        corners = image.corners()
        mesh = Mesh()
        face = mesh.add_face(corners)
        face.attrs["texture"] = {
            "path": str(image.path),
            "uvw": fit_uv_affine(
                corners,
                [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            ),
        }
        if image.opacity < 0.999:
            face.attrs["opacity"] = float(image.opacity)
        layer_name = str(image.layer or DEFAULT_LAYER)
        layer = scene.layer(layer_name)
        parts.append({
            "id": f"image:{index}",
            "name": str(image.name or f"Reference image {index + 1}"),
            "kind": "reference-image",
            "layer": layer_name,
            "visible": True if layer is None else bool(layer.visible),
            "layer_visible": True if layer is None else bool(layer.visible),
            "hidden": False,
            "locked": bool(image.locked),
            "faces": mesh.faces,
        })
    for index, group in enumerate(scene.groups):
        parts.extend(_group_parts(scene, group, f"group:{index}", None, {}))
    return parts


def summarize_scene(scene: Scene, include_outline: bool = False) -> dict[str, Any]:
    """Return stable, JSON-safe metadata for a loaded scene.

    Geometry totals count each distinct component prototype once in
    ``unique_geometry`` and every placed group/component in ``placements``.
    The distinction prevents a component repeated hundreds of times from
    looking like hundreds of independently stored meshes.
    """
    groups = list(iter_groups(scene.groups))
    visibility_ids: dict[str, str] = {}

    def index_visibility(group, object_id: str) -> None:
        visibility_ids[str(group.uid)] = object_id
        for index, child in enumerate(group.children):
            index_visibility(child, f"{object_id}/{index}")

    for index, group in enumerate(scene.groups):
        index_visibility(group, f"group:{index}")
    unique_meshes = {id(scene.loose_mesh): scene.loose_mesh}
    for group in groups:
        unique_meshes.setdefault(id(group.mesh), group.mesh)
    low, high = scene.bounds()
    units = dict(scene.units)
    from core.bim import class_quantities, collect_objects
    from core.group import world_mesh
    bim_objects = []
    top_level_ids = {id(group): f"group:{index}"
                     for index, group in enumerate(scene.groups)}
    for obj in collect_objects(scene):
        group = obj.get("group")
        faces = list(world_mesh(group).faces) if group is not None else obj["faces"]
        qset, entries, (takeoff, takeoff_unit) = class_quantities(
            obj["class"], faces,
        )
        key = obj.get("key", ("faces", 0))
        bim_objects.append({
            "id": (top_level_ids.get(id(group), str(group.uid))
                   if group is not None else f"faces:{key[1]}"),
            "class": str(obj["class"]),
            "name": str(obj["name"]),
            "area_m2": float(obj["area"]),
            "volume_m3": (None if obj["volume"] is None
                          else float(obj["volume"])),
            "takeoff": None if takeoff is None else float(takeoff),
            "takeoff_unit": str(takeoff_unit),
            "quantity_set": str(qset),
            "quantities": [
                {"kind": kind, "name": name, "value": float(value)}
                for kind, name, value in entries
            ],
        })
    datum = scene.georef
    tile_layer = scene.tile_layer
    map_detail = None
    if datum is not None and tile_layer is not None:
        all_tiles = tile_layer.flat_tiles(datum)
        tiles = all_tiles[:100]

        def tile_corners(x, y):
            quad = tile_layer.quad_local(datum, x, y)
            return [_point(quad[index][0]) for index in (0, 1, 2, 5)]

        map_detail = {
            "source": str(tile_layer.source.id),
            "name": str(tile_layer.source.name),
            "zoom": int(tile_layer.zoom),
            "radius": float(tile_layer.radius_m),
            "opacity": float(tile_layer.opacity),
            "visible": bool(tile_layer.visible),
            "attribution": str(tile_layer.source.attribution),
            "tiles": [
                {
                    "x": int(x), "y": int(y),
                    "url": tile_layer.source.url(x, y, tile_layer.zoom),
                    "corners": tile_corners(x, y),
                }
                for x, y in tiles
            ],
            "tiles_truncated": len(all_tiles) > 100,
        }
    photo_mesh = scene.photo_mesh
    photo_low, photo_high = ((photo_mesh.bounds()
                              if photo_mesh is not None else (None, None)))
    style_detail = scene.display_style.to_dict()
    shadow_detail = scene.shadows.to_dict()
    sun_detail = None
    if scene.shadows.enabled:
        from core.sun import (DEFAULT_LAT, DEFAULT_LON, solar_position,
                              sun_direction)
        latitude = datum.lat if datum is not None else DEFAULT_LAT
        longitude = datum.lon if datum is not None else DEFAULT_LON
        try:
            when_utc = scene.shadows.when_utc(longitude)
            direction = sun_direction(latitude, longitude, when_utc)
            elevation, azimuth = solar_position(latitude, longitude, when_utc)
            sun_detail = {
                "direction": list(direction) if direction is not None else None,
                "elevation": float(elevation),
                "azimuth": float(azimuth),
                "when_utc": when_utc.isoformat(),
            }
        except (ValueError, OverflowError):
            # Old hand-edited documents may contain an impossible calendar day.
            # Preserve the native settings while declining to calculate the sun.
            sun_detail = None
    summary = {
        "schema": "ingetrazo.scene-summary.v1",
        "bounds": {"min": _point(low), "max": _point(high)},
        "loose_geometry": {
            "vertices": len(scene.loose_mesh.vertices),
            "edges": len(scene.loose_mesh.edges),
            "faces": len(scene.loose_mesh.faces),
        },
        "unique_geometry": {
            "meshes": len(unique_meshes),
            "vertices": sum(len(mesh.vertices) for mesh in unique_meshes.values()),
            "edges": sum(len(mesh.edges) for mesh in unique_meshes.values()),
            "faces": sum(len(mesh.faces) for mesh in unique_meshes.values()),
        },
        "placements": len(groups),
        "groups": sum(not bool(getattr(group, "component", False)) for group in groups),
        "components": sum(bool(getattr(group, "component", False)) for group in groups),
        "dimensions": len(scene.dimensions),
        "dimension_details": [
            {
                "id": f"dimension:{index}",
                "a": _point(dimension.a),
                "b": _point(dimension.b),
                "line": [_point(point) for point in dimension.line_points()],
                "midpoint": _point(dimension.midpoint()),
                "value": float(dimension.value()),
                "label": str(dimension.display_text(dimension.label())),
                "axis": dimension.axis,
                "layer": dimension.layer,
                "visible": bool(scene.entity_visible(dimension)),
            }
            for index, dimension in enumerate(scene.dimensions)
        ],
        "text_labels": len(scene.text_labels),
        "text_label_details": [
            {
                "id": f"text:{index}",
                "anchor": _point(label.anchor),
                "position": _point(label.position()),
                "text": str(label.text),
                "layer": label.layer,
                "visible": bool(scene.entity_visible(label)),
            }
            for index, label in enumerate(scene.text_labels)
        ],
        "guides": len(scene.guides),
        "guide_details": [
            {
                "id": f"guide:{index}",
                "point": _point(guide.point),
                "direction": _point(guide.direction),
                "origin": _point(guide.origin),
            }
            for index, guide in enumerate(scene.guides)
        ],
        "reference_images": len(scene.image_planes),
        "reference_image_details": [
            {
                "id": f"image:{index}",
                "name": str(image.name or f"Reference image {index + 1}"),
                "layer": str(image.layer or "Layer 0"),
                "opacity": float(image.opacity),
                "locked": bool(image.locked),
                "width": float(image.width()),
                "height": float(image.height()),
            }
            for index, image in enumerate(scene.image_planes)
        ],
        "layers": len(scene.layers),
        "materials": len(scene.materials),
        "saved_views": len(scene.saved_views),
        "saved_view_details": [
            {
                "name": str(view.name),
                "target": [float(value) for value in view.target],
                "distance": float(view.distance),
                "yaw": float(view.yaw),
                "pitch": float(view.pitch),
                "fov_deg": float(view.fov_deg),
                "perspective": bool(view.perspective),
                "two_point": bool(view.two_point),
                "hidden_layers": [str(name) for name in view.hidden_layers],
                "section": (dict(view.section)
                            if isinstance(view.section, dict) else None),
                "hidden_objects": (
                    [str(uid) for uid in view.hidden_objects]
                    if view.hidden_objects is not None else None
                ),
                "hidden_object_visibility_ids": (
                    [visibility_ids[str(uid)] for uid in view.hidden_objects
                     if str(uid) in visibility_ids]
                    if view.hidden_objects is not None else None
                ),
            }
            for view in scene.saved_views
        ],
        "section_planes": len(scene.section_planes),
        "section_details": [
            {
                "id": int(plane.uid),
                "name": str(plane.name or plane.symbol or f"Section {index + 1}"),
                "symbol": str(plane.symbol),
                "point": _point(plane.point),
                "normal": _point(plane.normal),
                "active": bool(plane.active),
            }
            for index, plane in enumerate(scene.section_planes)
        ],
        "section_cuts_visible": bool(scene.show_section_cuts),
        "section_planes_visible": bool(scene.show_section_planes),
        "compositions": len(scene.compositions),
        "composition_details": [
            {
                "index": index,
                "name": str(composition.name),
                "paper": str(composition.paper),
                "landscape": bool(composition.landscape),
                "page_mm": [float(value) for value in composition.page_size_mm()],
                "frames": len(composition.frames),
                "frame_details": [
                    {
                        "view": str(frame.view_key),
                        "scale": float(frame.scale_n),
                        "style": str(frame.style),
                        "title": str(frame.title_text or ""),
                    }
                    for frame in composition.frames[:100]
                ],
            }
            for index, composition in enumerate(scene.compositions[:100])
        ],
        "georeferenced": scene.georef is not None,
        "georef_detail": ({
            **datum.to_dict(),
            "zone": int(datum.zone),
            "hemisphere": str(datum.hemisphere),
        } if datum is not None else None),
        "map": map_detail,
        "survey_points": len(scene.geo_points),
        "survey_point_details": [
            {
                "id": f"survey:{index}",
                "position": _point(point.position),
                "name": str(point.name),
                "description": str(point.desc),
            }
            for index, point in enumerate(scene.geo_points[:2000])
        ],
        "survey_points_truncated": len(scene.geo_points) > 2000,
        "geo_paths": len(scene.geo_paths),
        "geo_path_details": [
            {
                "id": f"geopath:{index}",
                "name": str(path.name or f"Path {index + 1}"),
                "points": [_point(point) for point in path.points[:2000]],
                "points_truncated": len(path.points) > 2000,
                "closed": bool(path.closed),
                "surface": path.surface,
                "length": float(path.length()),
                "area": float(path.area()),
            }
            for index, path in enumerate(scene.geo_paths[:500])
        ],
        "geo_paths_truncated": len(scene.geo_paths) > 500,
        "photogrammetry": ({
            "vertices": int(photo_mesh.vertex_count),
            "triangles": int(photo_mesh.triangle_count),
            "visible": bool(photo_mesh.visible),
            "georeferenced": bool(photo_mesh.georeferenced),
            "layer": photo_mesh.layer,
            "vertical_reference": str(photo_mesh.vertical_reference),
            "bounds": {"min": _point(photo_low), "max": _point(photo_high)},
            "mesh": ({
                "vertices": [
                    [float(value) for value in vertex]
                    for vertex in photo_mesh.vertices.tolist()
                ],
                "triangles": [
                    [int(value) for value in triangle]
                    for triangle in photo_mesh.triangles.tolist()
                ],
            } if photo_mesh.vertex_count <= 10_000
                 and photo_mesh.triangle_count <= 20_000 else None),
        } if photo_mesh is not None else None),
        "display_style": style_detail,
        "shadows": shadow_detail,
        "sun": sun_detail,
        "bim_objects": bim_objects,
        "units": {
            "length": str(units.get("length", "m")),
            "precision": int(units.get("precision", 2)),
        },
        "camera": _camera_summary(scene),
        "layer_details": [
            {"name": str(layer.name), "visible": bool(layer.visible),
             "locked": bool(layer.locked)}
            for layer in scene.layers
        ],
    }
    if include_outline:
        summary["outline"] = _outline(scene)
    return summary


def validate_igz_container(path: str | Path) -> None:
    """Apply cheap structural limits before the native loader sees a file.

    Native documents are either JSON or ZIP containers. ZIP metadata lets us
    reject path traversal, encrypted entries, and extreme expansion ratios
    without extracting anything. This is not malware scanning; it is the
    resource-safety boundary needed before untrusted web uploads reach the
    existing desktop loader.
    """
    source = Path(path)
    if source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("The .igz document exceeds the 100 MiB limit.")
    with source.open("rb") as stream:
        magic = stream.read(4)
    if magic != _ZIP_MAGIC:
        try:
            with source.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The .igz file is neither valid JSON nor a ZIP document.") from exc
        if not isinstance(data, dict) or "scene" not in data:
            raise ValueError("The .igz JSON does not contain an IngeTrazo scene.")
        return

    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_CONTAINER_ENTRIES:
                raise ValueError("The .igz container has too many entries.")
            normalized_names = [entry.filename.replace("\\", "/")
                                for entry in entries]
            if len(set(normalized_names)) != len(normalized_names):
                raise ValueError("The .igz container contains duplicate entries.")
            names = set(normalized_names)
            if "document.json" not in names:
                raise ValueError("The .igz container has no document.json entry.")
            total = 0
            for entry, normalized in zip(entries, normalized_names):
                parts = Path(normalized).parts
                if normalized.startswith("/") or ".." in parts:
                    raise ValueError("The .igz container contains an unsafe path.")
                if entry.flag_bits & 0x1:
                    raise ValueError("Encrypted .igz entries are not supported.")
                if entry.file_size > 1024 * 1024:
                    if entry.compress_size == 0:
                        raise ValueError("The .igz container has an unsafe compression ratio.")
                    ratio = entry.file_size / entry.compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise ValueError("The .igz container has an unsafe compression ratio.")
                total += entry.file_size
                if total > MAX_UNPACKED_BYTES:
                    raise ValueError("The .igz container expands beyond the 512 MiB limit.")
                if (normalized == "document.json"
                        and entry.file_size > MAX_DOCUMENT_BYTES):
                    raise ValueError("document.json exceeds the 100 MiB limit.")
    except zipfile.BadZipFile as exc:
        raise ValueError("The .igz ZIP container is damaged.") from exc


def load_igz(path: str | Path) -> Scene:
    """Load one native document into a fresh headless scene."""
    source = Path(path)
    if source.suffix.lower() != ".igz":
        raise ValueError("Only native IngeTrazo .igz documents are accepted.")
    validate_igz_container(source)
    scene = Scene()
    load_into(scene, source, stable_ids=True)
    return scene


def inspect_igz(path: str | Path) -> dict[str, Any]:
    """Load a native document and return its web-facing summary."""
    return summarize_scene(load_igz(path), include_outline=True)


def write_preview(scene: Scene, destination: str | Path) -> None:
    """Write the self-contained GLB preview of an already loaded scene."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    save_glb(scene, target, semantic_parts=_semantic_parts(scene))


def preview_igz(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Load ``source``, write a self-contained GLB, and return its summary."""
    scene = load_igz(source)
    write_preview(scene, destination)
    return summarize_scene(scene)

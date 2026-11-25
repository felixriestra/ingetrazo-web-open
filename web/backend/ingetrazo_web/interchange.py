"""Headless import/export adapters used by the Phase 5 web job service.

Native ``.igz`` remains the editable source of truth.  Imports create a new
native document; exports are pinned to one immutable revision.  The adapters
deliberately mirror the desktop format functions instead of maintaining a
second conversion implementation in the web layer.
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
import zipfile

from core.group import world_mesh
from core.scene import Scene
from formats.dae import load_dae, save_dae
from formats.dxf_in import load_dxf
from formats.dxf_out import save_dxf_layers
from formats.glb import load_glb
from formats.gltf import save_glb
from formats.ifc import save_ifc
from formats.obj import load_obj, save_obj
from formats.stl import load_stl, save_stl
from formats.svg_out import save_svg_layers


IMPORT_FORMATS = ("glb", "gltf", "obj", "stl", "dae", "dxf", "skp")
#: SKP export is commented out in the open-source release: the writer
#: (``formats/skp_out.py``) is not part of this repository. SKP *import* (OpenSKP, MIT)
#: is unaffected. A build that adds a writer restores ``"skp"`` in this tuple and the
#: ``skp`` branch of :func:`export_scene`, and switches it on with
#: ``INGETRAZO_WEB_ENABLE_SKP_EXPORT=1`` (see edition.py).
EXPORT_FORMATS = ("glb", "gltf", "obj", "stl", "dae", "dxf", "svg", "ifc")  # , "skp")


def import_formats() -> tuple[str, ...]:
    """Import formats this installation can read (SKP needs OpenSKP)."""
    from .edition import skp_import_available
    return tuple(name for name in IMPORT_FORMATS if name != "skp" or skp_import_available())


def export_formats() -> tuple[str, ...]:
    """Export formats on offer (SKP only in the private edition, when enabled)."""
    from .edition import skp_export_enabled
    return tuple(name for name in EXPORT_FORMATS if name != "skp" or skp_export_enabled())


class ConversionCancelled(RuntimeError):
    """Raised by a cooperative format progress callback."""


def normalize_format(value: str | None, filename: str = "") -> str:
    format_name = (value or Path(filename).suffix.lstrip(".")).lower().strip()
    if format_name == "collada":
        format_name = "dae"
    return format_name


def import_scene(path: str | Path, format_name: str, *, scale: float = 1.0,
                 progress=None) -> Scene:
    """Load one desktop-supported interchange file into a fresh scene."""
    path = Path(path)
    fmt = normalize_format(format_name, path.name)
    if fmt not in import_formats():
        raise ValueError(f"Unsupported import format: {fmt or 'unknown'}"
                         + (" (reading .skp needs the openskp package)" if fmt == "skp" else ""))
    if not 1e-9 <= float(scale) <= 1e9:
        raise ValueError("Import scale must be between 1e-9 and 1e9.")
    scene = Scene()
    if fmt in {"glb", "gltf"}:
        load_glb(scene, path, progress=progress)
    elif fmt == "obj":
        load_obj(scene, path, progress=progress, scale=float(scale))
    elif fmt == "stl":
        load_stl(scene, path, progress=progress, scale=float(scale))
    elif fmt == "dae":
        load_dae(scene, path, progress=progress)
    elif fmt == "dxf":
        load_dxf(scene, path, progress=progress, scale=float(scale))
    elif fmt == "skp":
        from formats import skp as skp_format
        try:
            skp_format.load_skp(scene, path, progress=progress)
        except skp_format.NeedsConverter as exc:
            raise ValueError(f"This .skp could not be read (format: {getattr(exc, 'format', 'unknown')}). "
                             "Files from SketchUp 2013 or later are supported.") from exc
    return scene


def export_scene(scene, directory: str | Path, format_name: str,
                 *, project_name: str = "IngeTrazo model", progress=None) -> Path:
    """Export a scene and return the single downloadable artifact path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fmt = normalize_format(format_name)
    if fmt not in export_formats():
        raise ValueError(f"Unsupported export format: {fmt or 'unknown'}")
    tick = progress or (lambda _fraction, _message: None)
    tick(0.08, "Loading native revision")
    if fmt == "glb":
        target = directory / "model.glb"
        save_glb(scene, target)
    elif fmt == "gltf":
        binary = directory / "model.glb"
        save_glb(scene, binary)
        target = _glb_to_gltf_bundle(binary, directory)
        binary.unlink(missing_ok=True)
    elif fmt == "obj":
        model = directory / "model.obj"
        save_obj(scene, model)
        target = _zip_bundle(directory, "model-obj.zip")
    elif fmt == "stl":
        target = directory / "model.stl"
        save_stl(scene, target)
    elif fmt == "dae":
        model = directory / "model.dae"
        save_dae(scene, model, project_name=project_name)
        siblings = [path for path in directory.iterdir() if path.is_file()]
        target = (_zip_bundle(directory, "model-dae.zip")
                  if len(siblings) > 1 else model)
    elif fmt == "dxf":
        target = directory / "model.dxf"
        count = save_dxf_layers(target, _dxf_groups(scene))
        if not count:
            raise ValueError("The revision contains no edges that can be exported to DXF.")
    elif fmt == "svg":
        target = directory / "model.svg"
        count = save_svg_layers(target, _dxf_groups(scene), scale_n=100.0)
        if not count:
            raise ValueError("The revision contains no edges that can be exported to SVG.")
    # SKP export: commented out in the open-source release (see EXPORT_FORMATS above).
    # elif fmt == "skp":
    #     from .edition import skp_export_module
    #     writer = skp_export_module()            # None in the open-source edition
    #     if writer is None:
    #         raise ValueError("SKP export is not available in this edition.")
    #     target = directory / "model.skp"
    #     writer.save_skp(scene, target)
    else:  # IFC
        target = directory / "model.ifc"
        save_ifc(scene, target, project_name=project_name)
    tick(1.0, "Conversion complete")
    return target


def _zip_bundle(directory: Path, name: str) -> Path:
    target = directory / name
    members = [path for path in directory.iterdir()
               if path.is_file() and path != target]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(members):
            archive.write(member, member.name)
    for member in members:
        member.unlink(missing_ok=True)
    return target


def _glb_to_gltf_bundle(glb_path: Path, directory: Path) -> Path:
    """Convert our two-chunk GLB to a standards-compliant JSON/bin bundle."""
    data = glb_path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("The GLB exporter produced an invalid container.")
    _magic, version, declared = struct.unpack_from("<4sII", data, 0)
    if version != 2 or declared != len(data):
        raise ValueError("The GLB exporter produced an invalid v2 container.")
    offset = 12
    chunks: dict[bytes, bytes] = {}
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<I4s", data, offset)
        offset += 8
        chunks[kind] = data[offset:offset + length]
        offset += length
    try:
        document = json.loads(chunks[b"JSON"].rstrip(b" \x00").decode("utf-8"))
        binary = chunks[b"BIN\x00"]
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("The GLB exporter omitted a required JSON or BIN chunk.") from exc
    document.setdefault("buffers", [{}])[0]["uri"] = "model.bin"
    (directory / "model.gltf").write_text(
        json.dumps(document, separators=(",", ":")), encoding="utf-8",
    )
    (directory / "model.bin").write_bytes(binary)
    return _zip_bundle(directory, "model-gltf.zip")


def _dxf_groups(scene) -> list[tuple[str, list[tuple[float, float, float, float]]]]:
    """Project native visible edges to a true-size XY DXF, grouped by layer."""
    groups: dict[str, list[tuple[float, float, float, float]]] = {}
    meshes = [(getattr(scene, "loose_mesh", getattr(scene, "mesh", None)), "Layer 0")]
    for group in getattr(scene, "groups", []):
        if not scene.entity_visible(group) or getattr(group, "billboard", False):
            continue
        meshes.append((world_mesh(group), getattr(group, "layer", None) or "Layer 0"))
    for mesh, layer in meshes:
        if mesh is None:
            continue
        seen: set[tuple[float, ...]] = set()
        output = groups.setdefault(str(layer), [])
        for edge in mesh.edges:
            if not scene.entity_visible(edge):
                continue
            a, b = edge.a, edge.b
            segment = (round(a.x(), 9), round(a.y(), 9),
                       round(b.x(), 9), round(b.y(), 9))
            reverse = (segment[2], segment[3], segment[0], segment[1])
            if segment in seen or reverse in seen or segment[:2] == segment[2:]:
                continue
            seen.add(segment)
            output.append(segment)
    return sorted(groups.items())

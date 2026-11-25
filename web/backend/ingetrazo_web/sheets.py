"""The sheet composer: layout, page preview and edit commands for native sheets.

A sheet (``core.composition.Composicion``) is a page plus items (view frames, texts,
images, scale bars, north arrows, legends, shapes, dimensions, labels and the title
block). The browser composer draws the page from a PNG made with the desktop
composer's own painting routines and puts a movable box over each item; every change
goes through one ``sheet-edit`` command that validates it against the item's own
dataclass, so the web cannot store a value the desktop could not read.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import math
from collections import OrderedDict
from dataclasses import asdict, fields
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import Response

from core import composition as comp
from core.composition import PAPER_SIZES_MM, Composicion

from .commands import commit_revision, ensure_qt
from .schemas import DeleteSheet, SheetEdit
from .document_store import DocumentNotFoundError, DocumentStore, RevisionNotFoundError
from .scene_service import load_igz

#: Item lists of a sheet, and the name the composer gives each kind.
LISTS: dict[str, tuple[type, str]] = {
    "frames": (comp.MarcoVista, "View"),
    "texts": (comp.TextoItem, "Text"),
    "images": (comp.ImagenItem, "Image"),
    "scalebars": (comp.BarraEscala, "Scale bar"),
    "nortes": (comp.FlechaNorte, "North arrow"),
    "leyendas": (comp.Leyenda, "Legend"),
    "shapes": (comp.FormaItem, "Shape"),
    "cotas": (comp.CotaItem, "Dimension"),
    "cotas_ang": (comp.CotaAngularItem, "Angle dimension"),
    "cotas_rad": (comp.CotaRadialItem, "Radius dimension"),
    "etiquetas": (comp.EtiquetaItem, "Label"),
    "perfiles": (comp.PerfilTerreno, "Terrain profile"),
    "niveles": (comp.NivelItem, "Level mark"),
    "llamadas": (comp.LlamadaItem, "Callout"),
}
#: What the composer may add.
ADDABLE = {"frames", "texts", "images", "scalebars", "nortes", "leyendas", "shapes", "cajetin"}
PAGE_FIELDS = {"name": str, "paper": str, "landscape": bool, "margin_mm": float, "border": bool,
               "border_mm": float, "border_color": str, "border_radius_mm": float, "border_style": str}
STANDARD_VIEWS = {"top", "bottom", "front", "back", "left", "right", "iso"}
MAX_COORD = 100_000.0
_COLOUR_FIELDS = ("color", "fill_color", "label_color", "text_color", "line_color", "bg_color",
                  "border_color", "cut_fill_color")


def _item_id(listing: str, index: int) -> str:
    return f"{listing}/{index}"


def _find(sheet: Composicion, item_id: Any):
    """``(list name, index, item)`` for an id such as ``texts/2`` or ``cajetin/0``."""
    if not isinstance(item_id, str) or "/" not in item_id:
        raise HTTPException(422, "id must look like texts/0.")
    listing, _, raw = item_id.partition("/")
    if listing == "cajetin":
        if sheet.cajetin is None or raw != "0":
            raise HTTPException(422, "This sheet has no title block.")
        return listing, 0, sheet.cajetin
    if listing not in LISTS or not raw.isdigit():
        raise HTTPException(422, f"Unknown item {item_id}.")
    items = getattr(sheet, listing)
    if int(raw) >= len(items):
        raise HTTPException(422, f"Unknown item {item_id}.")
    return listing, int(raw), items[int(raw)]


def _bounds(item) -> tuple[float, float]:
    """Width and height on the page, for the kinds that have them as a property."""
    def number(name: str) -> float:
        try:
            value = getattr(item, name, 0.0)
            return float(value) if value is not None and math.isfinite(float(value)) else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0
    width, height = number("w_mm"), number("h_mm")
    if isinstance(item, comp.TextoItem):
        height = max(height, item.size_pt * 0.3528 * 1.4 * max(1, str(item.text).count("\n") + 1))
    return width, height


def _label(sheet: Composicion, listing: str, item) -> str:
    named = getattr(item, "list_name", "")
    if named:
        return str(named)
    kind = "Title block" if listing == "cajetin" else LISTS[listing][1]
    detail = ""
    if isinstance(item, comp.TextoItem):
        detail = str(item.text).strip().splitlines()[0][:30] if str(item.text).strip() else ""
    elif isinstance(item, comp.MarcoVista):
        detail = item.title_text or str(item.view_key)
    return f"{kind} · {detail}" if detail else kind


def layout_of(scene, sheet: Composicion, index: int) -> dict:
    items = []
    for listing in LISTS:
        for number, item in enumerate(getattr(sheet, listing)):
            width, height = _bounds(item)
            items.append({"id": _item_id(listing, number), "list": listing, "label": _label(sheet, listing, item),
                          "x_mm": float(item.x_mm), "y_mm": float(item.y_mm), "w_mm": width, "h_mm": height,
                          "z": float(item.z), "hidden": bool(item.hidden), "locked": bool(item.locked),
                          "fields": asdict(item)})
    if sheet.cajetin is not None:
        item = sheet.cajetin
        items.append({"id": "cajetin/0", "list": "cajetin", "label": _label(sheet, "cajetin", item),
                      "x_mm": float(item.x_mm), "y_mm": float(item.y_mm), "w_mm": float(item.w_mm), "h_mm": float(item.h_mm),
                      "z": float(item.z), "hidden": bool(item.hidden), "locked": bool(item.locked),
                      "fields": asdict(item)})
    width, height = sheet.page_size_mm()
    return {
        "index": index, "name": sheet.name, "paper": sheet.paper, "landscape": bool(sheet.landscape),
        "page_mm": [float(width), float(height)], "margin_mm": float(sheet.margin_mm),
        "border": {"on": bool(sheet.border), "mm": float(sheet.border_mm), "color": sheet.border_color,
                   "radius_mm": float(sheet.border_radius_mm), "style": sheet.border_style},
        "papers": sorted(PAPER_SIZES_MM), "items": items,
        "scenes": [str(view.name) for view in scene.saved_views],
        "layers": [str(layer.name) for layer in scene.layers],
        "addable": sorted(ADDABLE),
    }


# --- validation of changes ---------------------------------------------------

def _finite(value: Any, name: str, low: float = -MAX_COORD, high: float = MAX_COORD) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise HTTPException(422, f"{name} must be a finite number.")
    if not low <= float(value) <= high:
        raise HTTPException(422, f"{name} must be between {low:g} and {high:g}.")
    return float(value)


def _coerce(item, name: str, value: Any, scene) -> Any:
    """``value`` as the type ``item.<name>`` already has, or a 422."""
    current = getattr(item, name)
    if name in _COLOUR_FIELDS:
        import re
        if not isinstance(value, str) or (value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value)):
            raise HTTPException(422, f"{name} must be a #rrggbb colour.")
        return value
    if name == "view_key":
        if not isinstance(value, str) or not (value == "__current__" or (value.startswith("std:") and value[4:] in STANDARD_VIEWS)
                                              or (value.startswith("scene:") and value[6:] in {v.name for v in scene.saved_views})):
            raise HTTPException(422, "view_key must be a standard view or an existing scene.")
        return value
    if name == "path":
        raise HTTPException(422, "An image is set by uploading it.")
    if name == "scale_n":
        return _finite(value, name, 0.01, 1_000_000)
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise HTTPException(422, f"{name} must be true or false.")
        return value
    if isinstance(current, int):
        return int(_finite(value, name, -1_000_000, 1_000_000))
    if isinstance(current, float):
        return _finite(value, name)
    if isinstance(current, str):
        if not isinstance(value, str) or len(value) > 4000:
            raise HTTPException(422, f"{name} must be text of at most 4000 characters.")
        return value
    if current is None:
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _finite(value, name)
        if isinstance(value, list) and len(value) == 3:
            return [_finite(v, name) for v in value]
        raise HTTPException(422, f"{name} must be a number, a point or null.")
    if isinstance(current, list):
        if not isinstance(value, list) or len(value) > 200:
            raise HTTPException(422, f"{name} must be a list of at most 200 entries.")
        if name == "campos":
            rows = []
            for row in value:
                if not (isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) and len(x) <= 400 for x in row)):
                    raise HTTPException(422, "campos must be [label, value] text pairs.")
                rows.append([row[0], row[1]])
            return rows
        if all(isinstance(x, str) and len(x) <= 400 for x in value):
            return list(value)
        raise HTTPException(422, f"{name} must be a list of text.")
    raise HTTPException(422, f"{name} cannot be edited here.")


def _apply(item, changes: Any, scene) -> None:
    if not isinstance(changes, dict) or not changes:
        raise HTTPException(422, "changes must be an object with at least one field.")
    names = {field.name for field in fields(item)}
    for name in changes:
        if name not in names or name in {"uid", "group_id", "frame_uid"}:
            raise HTTPException(422, f"{name} is not an editable field of this item.")
    coerced = {name: _coerce(item, name, value, scene) for name, value in changes.items()}
    for name, value in coerced.items():
        setattr(item, name, value)
    if isinstance(item, comp.Cajetin):
        item.__post_init__()


def _stash_image(store: DocumentStore, payload: dict) -> str:
    from PySide6.QtGui import QImage

    ensure_qt()
    encoded = payload.get("image_base64")
    if not isinstance(encoded, str) or not encoded or len(encoded) > 12_000_000:
        raise HTTPException(422, "image_base64 must hold an image of at most 8 MB.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "image_base64 is not valid base64.") from exc
    image = QImage.fromData(data)
    if image.isNull() or max(image.width(), image.height()) > 8192:
        raise HTTPException(422, "The image could not be read (up to 8192 px).")
    folder = store.root / "sheet-images"
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{hashlib.sha256(data).hexdigest()[:24]}.png"
    if not stored.is_file() and not image.save(str(stored), "PNG"):
        raise HTTPException(500, "The image could not be stored.")
    return str(stored)


def _new_item(store: DocumentStore, scene, sheet: Composicion, operation: dict):
    listing = operation.get("list")
    if listing not in ADDABLE:
        raise HTTPException(422, f"list must be one of {', '.join(sorted(ADDABLE))}.")
    fields_in = operation.get("fields") or {}
    if not isinstance(fields_in, dict):
        raise HTTPException(422, "fields must be an object.")
    width, height = sheet.page_size_mm()
    margin = sheet.margin_mm
    if listing == "cajetin":
        if sheet.cajetin is not None:
            raise HTTPException(422, "This sheet already has a title block.")
        item = sheet.default_cajetin()
        sheet.cajetin = item
    else:
        kind = LISTS[listing][0]
        item = kind()
        item.x_mm, item.y_mm = margin + 10, margin + 10
        if isinstance(item, comp.MarcoVista):
            frame = sheet.default_frame()
            item.x_mm, item.y_mm, item.w_mm, item.h_mm = frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm
            item.style = "vectorial"
            item.view_key = "std:top"
            if sheet.frames:       # a second view goes beside the first, half the page
                item.w_mm, item.h_mm = (width - 2 * margin) / 2, (height - 2 * margin) / 2
        elif isinstance(item, comp.TextoItem):
            item.text = "Text"
        elif isinstance(item, comp.BarraEscala) and sheet.frames:
            item.scale_n = sheet.frames[0].scale_n
        elif isinstance(item, comp.Leyenda):
            item.rows = [str(layer.name) for layer in scene.layers if layer.visible]
        elif isinstance(item, comp.ImagenItem):
            item.path = _stash_image(store, operation)
        getattr(sheet, listing).append(item)
    item.z = max([float(getattr(other, "z", 0.0)) for other in sheet.all_items() if other is not item] + [0.0]) + 1
    if fields_in:
        _apply(item, fields_in, scene)
    return listing, item


def apply_operations(store: DocumentStore, scene, sheet: Composicion, operations: list) -> None:
    for operation in operations:
        if not isinstance(operation, dict):
            raise HTTPException(422, "Each operation must be an object.")
        kind = operation.get("op")
        if kind == "page":
            changes = operation.get("changes")
            if not isinstance(changes, dict) or not changes:
                raise HTTPException(422, "changes must be an object with at least one field.")
            for name, value in changes.items():
                if name not in PAGE_FIELDS:
                    raise HTTPException(422, f"{name} is not a page setting.")
                if name == "paper" and value not in PAPER_SIZES_MM:
                    raise HTTPException(422, "paper must be one of " + ", ".join(sorted(PAPER_SIZES_MM)) + ".")
                if name == "border_style" and value not in {"single", "double", "dashed"}:
                    raise HTTPException(422, "border_style must be single, double or dashed.")
                if name == "name" and (not isinstance(value, str) or not value.strip() or len(value) > 255):
                    raise HTTPException(422, "name must contain 1–255 characters.")
                if name == "border_color":
                    _coerce(sheet.cajetin or comp.Cajetin(), "line_color", value, scene)
                kind_ = PAGE_FIELDS[name]
                if kind_ is bool and not isinstance(value, bool):
                    raise HTTPException(422, f"{name} must be true or false.")
                if kind_ is float:
                    value = _finite(value, name, 0, 1000)
                setattr(sheet, name, value.strip() if name == "name" else value)
        elif kind == "add":
            _new_item(store, scene, sheet, operation)
        elif kind == "set":
            _, _, item = _find(sheet, operation.get("id"))
            _apply(item, operation.get("changes"), scene)
        elif kind == "remove":
            listing, index, _ = _find(sheet, operation.get("id"))
            if listing == "cajetin":
                sheet.cajetin = None
            else:
                del getattr(sheet, listing)[index]
        elif kind == "order":
            _, _, item = _find(sheet, operation.get("id"))
            others = [float(getattr(other, "z", 0.0)) for other in sheet.all_items() if other is not item]
            if operation.get("to") == "front":
                item.z = max(others + [0.0]) + 1
            elif operation.get("to") == "back":
                item.z = min(others + [0.0]) - 1
            else:
                raise HTTPException(422, "to must be front or back.")
        elif kind == "duplicate":
            listing, _, item = _find(sheet, operation.get("id"))
            if listing == "cajetin":
                raise HTTPException(422, "A sheet has one title block.")
            import copy
            clone = copy.deepcopy(item)
            clone.x_mm, clone.y_mm = float(item.x_mm) + 8, float(item.y_mm) + 8
            if hasattr(clone, "uid"):
                clone.uid = ""
            clone.z = max(float(getattr(other, "z", 0.0)) for other in sheet.all_items()) + 1
            getattr(sheet, listing).append(clone)
        else:
            raise HTTPException(422, "op must be page, add, set, remove, order or duplicate.")


def register_sheet_commands(app: FastAPI, store: DocumentStore) -> None:
    base = "/api/v1/documents/{document_id}/commands"
    preview_cache: OrderedDict[tuple, bytes] = OrderedDict()

    def sheet_of_scene(document_id: str, revision: int):
        try:
            return load_igz(store.revision_path(document_id, revision)), None
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc

    def sheet_of(document_id: str, revision: int, index: int):
        try:
            scene = load_igz(store.revision_path(document_id, revision))
        except DocumentNotFoundError as exc:
            raise HTTPException(404, "Document not found.") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(404, "Revision not found.") from exc
        if not 0 <= index < len(scene.compositions):
            raise HTTPException(404, "Sheet not found.")
        return scene, scene.compositions[index]

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/sheets/{sheet_index}/layout")
    def sheet_layout(document_id: str, revision: int, sheet_index: int):
        scene, sheet = sheet_of(document_id, revision, sheet_index)
        return layout_of(scene, sheet, sheet_index)

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/sheets/{sheet_index}.png")
    def sheet_png(document_id: str, revision: int, sheet_index: int, dpi: int = 60, frames: bool = True):
        from .sheet_pdf import render_sheet_png

        if not 20 <= dpi <= 200:
            raise HTTPException(422, "dpi must be between 20 and 200.")
        key = (document_id, revision, sheet_index, dpi, frames)
        content = preview_cache.get(key)
        if content is None:
            scene, sheet = sheet_of(document_id, revision, sheet_index)
            ensure_qt()
            try:
                content = render_sheet_png(scene, sheet, dpi, frames=frames)
            except (OSError, ValueError) as exc:
                raise HTTPException(422, f"Could not draw the sheet: {exc}") from exc
            preview_cache[key] = content
            while len(preview_cache) > 24:
                preview_cache.popitem(last=False)
        return Response(content, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/v1/documents/{document_id}/revisions/{revision}/render.png")
    def render_view(document_id: str, revision: int, view: str = "iso", width: int = 900):
        """A line drawing of the model from a standard view (or a saved scene) as a PNG.

        It is the same hidden-line drawing a sheet prints, so an assistant (or anyone) can
        look at the model without a browser. Nothing is stored.
        """
        import math

        from .sheet_pdf import render_sheet_png

        if not 300 <= width <= 2400:
            raise HTTPException(422, "width must be between 300 and 2400 pixels.")
        scene, _ = sheet_of_scene(document_id, revision)
        names = {saved.name for saved in scene.saved_views}
        if view in STANDARD_VIEWS:
            view_key = f"std:{view}"
        elif view.startswith("scene:") and view[6:] in names:
            view_key = view
        else:
            raise HTTPException(422, "view must be top, bottom, front, back, left, right, iso or scene:<name>.")
        low, high = scene.bounds()
        if low is None:
            raise HTTPException(422, "The model is empty: there is nothing to draw.")
        diagonal = math.dist((low.x(), low.y(), low.z()), (high.x(), high.y(), high.z()))
        if diagonal < 1e-9:
            raise HTTPException(422, "The model has no extent to draw.")
        sheet = Composicion(name="render", paper="A4", landscape=True, margin_mm=5)
        frame = sheet.default_frame()
        frame.view_key, frame.style, frame.border = view_key, "vectorial", False
        # a scale at which the model's diagonal fits the frame's short side, whatever the view
        frame.scale_n = diagonal * 1000.0 / (0.92 * min(frame.w_mm, frame.h_mm))
        sheet.frames.append(frame)
        scene.compositions.append(sheet)
        ensure_qt()
        try:
            content = render_sheet_png(scene, sheet, dpi=width * 25.4 / 297.0)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, f"Could not draw the model: {exc}") from exc
        return Response(content, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.post(f"{base}/sheet-edit", status_code=201)
    def sheet_edit(document_id: str, payload: SheetEdit):
        """Apply a list of operations to one sheet as one revision."""
        index = payload.sheet_index
        operations = [op.model_dump(exclude_unset=True) for op in payload.ops]

        def mutate(scene):
            if index >= len(scene.compositions):
                raise HTTPException(422, "Unknown sheet.")
            apply_operations(store, scene, scene.compositions[index], operations)
            scene.version += 1

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

    @app.post(f"{base}/delete-sheet", status_code=201)
    def delete_sheet(document_id: str, payload: DeleteSheet):
        index = payload.sheet_index

        def mutate(scene):
            if index >= len(scene.compositions):
                raise HTTPException(422, "Unknown sheet.")
            del scene.compositions[index]
            scene.version += 1

        return commit_revision(store, document_id, payload.base_revision, mutate, restore_identities=False)

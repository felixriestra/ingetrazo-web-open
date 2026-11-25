"""The bundled component and texture libraries, served read-only.

Only files that ship in ``resources/`` are reachable: component keys come from
``components.json`` and texture paths are resolved inside the library folder,
so a request can never name a file outside it.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

RESOURCES = Path(__file__).resolve().parents[3] / "resources"
COMPONENTS = RESOURCES / "components"
TEXTURES = RESOURCES / "textures" / "library"
TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def component_index() -> list[dict]:
    """The bundled 3D components and 2D scale figures, each with the key the
    category tree files it under (``component:<key>`` or ``person:<key>``)."""
    from .taxonomy import DEFAULT_PATHS

    entries = json.loads((COMPONENTS / "components.json").read_text(encoding="utf-8"))
    out = [
        {**entry,
         "kind": "component",
         "item": f"component:{entry['key']}",
         "default_path": list(DEFAULT_PATHS.get(f"component:{entry['key']}", ())),
         "thumb": (COMPONENTS / "thumbs" / f"{entry['key']}.png").is_file(),
         "thumb_url": f"/api/v1/library/components/{entry['key']}/thumb"}
        for entry in entries
        if (COMPONENTS / f"{entry['key']}.igz").is_file()
    ]
    people = COMPONENTS / "people.json"
    if people.is_file():
        for entry in json.loads(people.read_text(encoding="utf-8")):
            if not (COMPONENTS / f"{entry['key']}.png").is_file():
                continue
            out.append({
                "key": entry["key"], "name": entry["name"], "tip": entry.get("tip", entry["name"]),
                "height": float(entry["height"]), "kind": "person",
                "item": f"person:{entry['key']}", "default_path": ["People"], "thumb": True,
                "thumb_url": f"/api/v1/library/people/{entry['key']}/thumb"})
    return out


def component_entry(key: str) -> dict:
    for entry in component_index():
        if entry["key"] == key:
            return entry
    raise HTTPException(404, "Unknown component.")


def component_path(key: str) -> Path:
    return COMPONENTS / f"{component_entry(key)['key']}.igz"


def thumbnail_path(key: str) -> Path:
    path = COMPONENTS / "thumbs" / f"{component_entry(key)['key']}.png"
    if not path.is_file():
        raise HTTPException(404, "No thumbnail for that component.")
    return path


def texture_index() -> list[dict]:
    raw = json.loads((TEXTURES.parent / "library.json").read_text(encoding="utf-8"))
    return [
        {"id": category["id"],
         "items": [item for item in category["items"] if (TEXTURES / item["file"]).is_file()]}
        for category in raw["categories"]
    ]


def texture_file(relative: str) -> Path:
    """A library texture by its path relative to the library folder."""
    path = (TEXTURES / relative).resolve()
    if (TEXTURES.resolve() not in path.parents or path.suffix.lower() not in TEXTURE_SUFFIXES
            or not path.is_file()):
        raise HTTPException(404, "Unknown texture.")
    return path


def texture_material(relative: str) -> dict:
    """The group-material dict (``mat`` + ``texture``) for a library texture."""
    path = texture_file(relative)
    for category in texture_index():
        for item in category["items"]:
            if (TEXTURES / item["file"]).resolve() == path:
                return {"mat": item["name"],
                        "texture": {"path": str(path), "sw": float(item.get("sw", 1.0)),
                                    "sh": float(item.get("sh", 1.0))}}
    return {"texture": {"path": str(path), "sw": 1.0, "sh": 1.0}}


_person_thumbs: dict[str, bytes] = {}


def person_entry(key: str) -> dict:
    for entry in component_index():
        if entry["kind"] == "person" and entry["key"] == key:
            return entry
    raise HTTPException(404, "Unknown scale figure.")


def person_image(key: str) -> Path:
    return COMPONENTS / f"{person_entry(key)['key']}.png"


def person_aspect(key: str) -> float:
    """Width over height of a figure's cut-out image."""
    from PySide6.QtGui import QImage

    image = QImage(str(person_image(key)))
    if image.isNull() or image.height() == 0:
        raise HTTPException(422, "The figure's image could not be read.")
    return image.width() / image.height()


def person_thumbnail(key: str) -> bytes:
    """A small PNG of the figure: the images are ~1100 px tall, far more than a list row needs."""
    if key not in _person_thumbs:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage

        image = QImage(str(person_image(key)))
        if image.isNull():
            raise HTTPException(404, "No image for that figure.")
        small = image.scaledToHeight(96, Qt.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        small.save(buffer, "PNG")
        _person_thumbs[key] = bytes(data)
    return _person_thumbs[key]

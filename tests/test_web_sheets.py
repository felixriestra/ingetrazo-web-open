"""The sheet composer: layout, page preview and validated edit commands."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from core.scene import Scene  # noqa: E402
from formats.igz import save_scene  # noqa: E402
from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.scene_service import load_igz  # noqa: E402


@pytest.fixture()
def sheets(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    source = tmp_path / "empty.igz"
    save_scene(Scene(), source)
    record = client.post("/api/v1/documents", files={"file": (source.name, source.read_bytes())}).json()
    state = {"rev": record["latest_revision"]}
    store = client.app.state.document_store

    def post(endpoint, **body):
        response = client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}",
                               json={"base_revision": state["rev"], **body})
        if response.status_code == 201:
            state["rev"] = response.json()["latest_revision"]
        return response

    def get(path, **params):
        return client.get(f"/api/v1/documents/{record['id']}/revisions/{state['rev']}/{path}", params=params)

    post.get = get
    post.scene = lambda: load_igz(store.revision_path(record["id"], state["rev"]))
    assert post("create-sheet", name="Planta", paper="A3", view="top", scale=100).status_code == 201
    return post


def edit(sheets, *ops, sheet_index=0):
    return sheets("sheet-edit", sheet_index=sheet_index, ops=list(ops))


def test_layout_lists_every_item_with_its_fields(sheets):
    layout = sheets.get("sheets/0/layout").json()
    assert layout["paper"] == "A3" and layout["page_mm"] == [420.0, 297.0]
    assert [item["id"] for item in layout["items"]] == ["frames/0"]
    assert layout["items"][0]["fields"]["scale_n"] == 100
    assert sheets.get("sheets/5/layout").status_code == 404


def test_items_are_added_edited_ordered_and_removed(sheets):
    response = edit(
        sheets,
        {"op": "add", "list": "texts", "fields": {"text": "Hola {proyecto}", "size_pt": 18}},
        {"op": "add", "list": "nortes"},
        {"op": "add", "list": "scalebars"},
        {"op": "add", "list": "leyendas"},
        {"op": "add", "list": "shapes", "fields": {"kind": "elipse", "fill": True}},
        {"op": "add", "list": "cajetin"},
    )
    assert response.status_code == 201, response.text
    sheet = sheets.scene().compositions[0]
    assert sheet.texts[0].text == "Hola {proyecto}" and sheet.texts[0].size_pt == 18
    assert sheet.scalebars[0].scale_n == 100                       # follows the first view
    assert sheet.cajetin is not None and sheets("sheet-edit", sheet_index=0, ops=[{"op": "add", "list": "cajetin"}]).status_code == 422

    assert edit(sheets, {"op": "set", "id": "texts/0", "changes": {"x_mm": 100, "y_mm": 50, "color": "#ff0000", "bold": True}}).status_code == 201
    text = sheets.scene().compositions[0].texts[0]
    assert (text.x_mm, text.y_mm, text.color, text.bold) == (100, 50, "#ff0000", True)
    assert edit(sheets, {"op": "set", "id": "frames/0", "changes": {"scale_n": 50, "view_key": "std:front", "show_title": True}}).status_code == 201
    assert edit(sheets, {"op": "set", "id": "cajetin/0", "changes": {"campos": [["PROYECTO", "Casa"], ["AUTOR", "Ana"]]}}).status_code == 201
    assert sheets.scene().compositions[0].cajetin.campos == [["PROYECTO", "Casa"], ["AUTOR", "Ana"]]

    assert edit(sheets, {"op": "order", "id": "texts/0", "to": "back"}).status_code == 201
    assert edit(sheets, {"op": "duplicate", "id": "texts/0"}).status_code == 201
    assert len(sheets.scene().compositions[0].texts) == 2
    assert edit(sheets, {"op": "remove", "id": "texts/1"}, {"op": "remove", "id": "cajetin/0"}).status_code == 201
    scene_sheet = sheets.scene().compositions[0]
    assert len(scene_sheet.texts) == 1 and scene_sheet.cajetin is None


@pytest.mark.parametrize("operation", [
    {"op": "set", "id": "texts/0", "changes": {"x_mm": "left"}},
    {"op": "set", "id": "texts/0", "changes": {"x_mm": 1e12}},
    {"op": "set", "id": "texts/0", "changes": {"color": "red"}},
    {"op": "set", "id": "texts/0", "changes": {"bold": "yes"}},
    {"op": "set", "id": "texts/0", "changes": {"nonsense": 1}},
    {"op": "set", "id": "texts/0", "changes": {"group_id": "x"}},
    {"op": "set", "id": "texts/7", "changes": {"x_mm": 1}},
    {"op": "set", "id": "frames/0", "changes": {"view_key": "scene:missing"}},
    {"op": "set", "id": "frames/0", "changes": {"scale_n": 0}},
    {"op": "add", "list": "cotas"},
    {"op": "add", "list": "images"},
    {"op": "page", "changes": {"paper": "B7"}},
    {"op": "page", "changes": {"margin_mm": -3}},
    {"op": "page", "changes": {"unknown": 1}},
    {"op": "order", "id": "frames/0", "to": "sideways"},
    {"op": "frobnicate"},
])
def test_invalid_edits_are_refused_and_leave_no_revision(sheets, operation):
    assert edit(sheets, {"op": "add", "list": "texts"}).status_code == 201
    before = sheets.get("sheets/0/layout").json()
    revision = sheets.scene().version
    assert edit(sheets, operation).status_code == 422
    assert sheets.get("sheets/0/layout").json() == before
    assert sheets.scene().version == revision


def test_page_settings_and_deleting_a_sheet(sheets):
    assert edit(sheets, {"op": "page", "changes": {"paper": "A4", "landscape": False, "margin_mm": 15, "border": True,
                                                   "border_style": "double", "name": "Corte"}}).status_code == 201
    layout = sheets.get("sheets/0/layout").json()
    assert (layout["paper"], layout["landscape"], layout["page_mm"], layout["name"]) == ("A4", False, [210.0, 297.0], "Corte")
    assert layout["border"]["on"] and layout["border"]["style"] == "double"
    assert sheets("delete-sheet", sheet_index=3).status_code == 422
    assert sheets("delete-sheet", sheet_index=0).status_code == 201
    assert sheets.scene().compositions == []


def test_the_page_is_drawn_as_png_and_pdf(sheets):
    assert edit(sheets, {"op": "add", "list": "texts", "fields": {"text": "Casa"}},
                {"op": "add", "list": "nortes"}, {"op": "add", "list": "cajetin"}).status_code == 201
    png = sheets.get("sheets/0.png", dpi=40, frames=False)
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    full = sheets.get("sheets/0.png", dpi=40)
    assert full.status_code == 200 and full.content != png.content
    assert sheets.get("sheets/0.png", dpi=5).status_code == 422
    pdf = sheets.get("sheets/0.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_an_uploaded_image_becomes_an_image_item(sheets):
    import base64

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(20, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    encoded = base64.b64encode(bytes(raw)).decode()
    assert edit(sheets, {"op": "add", "list": "images", "image_base64": encoded, "fields": {"w_mm": 40, "h_mm": 20}}).status_code == 201
    assert sheets.scene().compositions[0].images[0].path.endswith(".png")
    assert edit(sheets, {"op": "add", "list": "images", "image_base64": "@@"}).status_code == 422
    assert sheets.get("sheets/0.png", dpi=40).status_code == 200


def test_a_model_can_be_looked_at_without_a_sheet(sheets):
    assert sheets("create-box", size=[2, 1, 1]).status_code == 201
    for view in ("iso", "top", "front"):
        response = sheets.get("render.png", view=view, width=600)
        assert response.status_code == 200 and response.content.startswith(b"\x89PNG"), view
    assert sheets.get("render.png", view="sideways").status_code == 422
    assert sheets.get("render.png", view="scene:missing").status_code == 422
    assert sheets.get("render.png", width=10).status_code == 422
    assert sheets.scene().compositions[-1].name == "Planta"          # nothing was stored on the document


def test_blank_documents_and_empty_models(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    made = client.post("/api/v1/documents/blank", json={"name": "Mi modelo"})
    assert made.status_code == 201 and made.json()["name"] == "Mi modelo.igz"
    assert client.post("/api/v1/documents/blank", json={"name": ""}).status_code == 422
    empty = client.get(f"/api/v1/documents/{made.json()['id']}/revisions/1/render.png")
    assert empty.status_code == 422 and "empty" in empty.json()["detail"]["message"]

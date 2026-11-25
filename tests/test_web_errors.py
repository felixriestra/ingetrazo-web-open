"""Every error response has one shape: {"detail": {"code", "message", "fields"?}}."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.errors import describe_validation, error_body  # noqa: E402


def test_text_details_become_message_and_code():
    assert error_body(404, "Document not found.") == {"detail": {"code": "not_found", "message": "Document not found."}}
    assert error_body(409, {"code": "revision_conflict", "message": "stale"}) == {
        "detail": {"code": "revision_conflict", "message": "stale"}}
    assert error_body(500, "boom")["detail"]["code"] == "server_error"


def test_the_service_answers_errors_in_that_shape(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    missing = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json()["detail"] == {"code": "not_found", "message": "Document not found."}
    assert client.get("/api/v1/nothing-here").json()["detail"]["code"] == "not_found"
    refused = client.post("/api/v1/jobs/import", files={"file": ("x.xyz", b"x")})
    assert refused.status_code == 415 and refused.json()["detail"]["code"] == "unsupported_media_type"


def test_validation_errors_name_the_field_and_say_what_is_wrong():
    from pydantic import BaseModel, ConfigDict, Field, ValidationError

    class Model(BaseModel):
        model_config = ConfigDict(extra="forbid")
        rows: int = Field(ge=1, le=40)
        name: str = Field(min_length=1)

    try:
        Model.model_validate({"rows": 0, "colour": 1})
    except ValidationError as exc:
        body = describe_validation(exc.errors())
    messages = {item["field"]: item["message"] for item in body["fields"]}
    assert messages["rows"] == "rows must be at least 1"
    assert messages["colour"] == "colour is not a setting of this command"
    assert messages["name"] == "name is required"
    assert body["code"] == "invalid_request" and "rows must be at least 1" in body["message"]


@pytest.fixture()
def doc(tmp_path):
    from core.scene import Scene
    from formats.igz import save_scene
    client = TestClient(create_app(tmp_path / "data"))
    source = tmp_path / "empty.igz"
    save_scene(Scene(), source)
    record = client.post("/api/v1/documents", files={"file": ("e.igz", source.read_bytes())}).json()
    return lambda endpoint, **body: client.post(f"/api/v1/documents/{record['id']}/commands/{endpoint}", json=body)


@pytest.mark.parametrize("endpoint,body,field,fragment", [
    ("create-box", {"base_revision": 1, "size": [1, 2]}, "size", "at least 3"),
    ("create-box", {"base_revision": 1, "size": [1, 0, 1]}, "size.1", "greater than 0"),
    ("create-box", {"base_revision": 1, "size": [1, 1, 1], "colour": "red"}, "colour", "not a setting"),
    ("create-box", {"base_revision": 0, "size": [1, 1, 1]}, "base_revision", "at least 1"),
    ("create-box", {"base_revision": "1", "size": [1, 1, 1]}, "base_revision", "whole number"),
    ("create-box", {"size": [1, 1, 1]}, "base_revision", "required"),
    ("create-box", {"base_revision": 1, "size": [1, 1, 1], "name": "  "}, "name", "at least 1"),
    ("create-box", {"base_revision": 1, "size": [True, 1, 1]}, "size.0", "number"),
    ("move-object", {"base_revision": 1, "object_id": "group:0", "delta": [0, 0, 0]}, "delta", "all zero"),
    ("move-object", {"base_revision": 1, "delta": [1, 0, 0]}, "", "object_id"),
    ("move-object", {"base_revision": 1, "object_id": "nonsense", "delta": [1, 0, 0]}, "object_id", "pattern"),
    ("transform-object", {"base_revision": 1, "object_id": "group:0", "operation": "rotate", "axis": "q", "degrees": 5}, "axis", "one of"),
    ("transform-object", {"base_revision": 1, "object_id": "group:0", "operation": "scale", "factors": [1, 1, 1]}, "", "not all 1"),
    ("set-shadows", {"base_revision": 1, "enabled": True, "month": 2, "day": 31, "hour": 9, "minute": 0, "darkness": 0.5}, "", "real date"),
    ("set-georef", {"base_revision": 1, "latitude": 91, "longitude": 0}, "latitude", "at most 90"),
    ("create-annotation", {"base_revision": 1, "operation": "poem"}, "", ""),
    ("object-lifecycle", {"base_revision": 1, "operation": "duplicate", "object_ids": ["group:0"]}, "", "only supported for delete"),
])
def test_typed_commands_name_the_field_and_the_limit(doc, endpoint, body, field, fragment):
    response = doc(endpoint, **body)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_request" and detail["message"]
    assert any(field == item["field"] for item in detail["fields"]), detail
    assert fragment in detail["message"], detail


def test_a_valid_typed_command_still_works_and_extras_are_refused_before_any_change(doc):
    assert doc("create-box", base_revision=1, size=[1, 2, 3], origin=[1, 1, 0], name=" Caja ").status_code == 201
    assert doc("create-box", base_revision=2, size=[1, 2, 3], extra=1).status_code == 422
    assert doc("create-box", base_revision=2, size=[1, 2, 3]).status_code == 201     # revision 2 is still current


@pytest.mark.parametrize("endpoint,body,field,fragment", [
    ("create-shape", {"base_revision": 1, "operation": "polygon", "radius": 1}, "sides", "required"),
    ("create-shape", {"base_revision": 1, "operation": "polygon", "sides": 2, "radius": 1}, "sides", "at least 3"),
    ("create-shape", {"base_revision": 1, "operation": "pie", "radius": 1, "sweep_degrees": 0}, "sweep_degrees", "not be zero"),
    ("create-shape", {"base_revision": 1, "operation": "freehand", "points": [[0, 0]]}, "points", "at least 2"),
    ("create-shape", {"base_revision": 1, "operation": "polygon", "sides": 4, "radius": 1, "plane": "ab"}, "plane", "one of"),
    ("create-planar", {"base_revision": 1, "operation": "line", "origin": [1, 1, 1], "end": [1, 1, 1]}, "", "different from origin"),
    ("create-planar", {"base_revision": 1, "operation": "circle", "radius": 1, "segments": 2}, "segments", "at least 3"),
    ("create-planar", {"base_revision": 1, "operation": "arc", "radius": 1, "sweep_degrees": 360}, "sweep_degrees", "less than 360"),
    ("follow-me", {"base_revision": 1, "object_id": "group:0", "path": [[0, 0, 0]]}, "path", "at least 2"),
    ("fillet", {"base_revision": 1, "object_id": "group:0", "radius": 0, "edges": "sharp"}, "radius", "at least"),
    ("fillet", {"base_revision": 1, "object_id": "group:0", "radius": 0.1, "edges": "round"}, "edges", ""),
    ("solid-operation", {"base_revision": 1, "operation": "union", "object_ids": ["group:0", "group:0"]}, "object_ids", "different"),
    ("solid-operation", {"base_revision": 1, "operation": "melt", "object_ids": ["group:0", "group:1"]}, "operation", "one of"),
    ("create-text3d", {"base_revision": 1, "text": "   "}, "text", "blank"),
    ("loose-group", {"base_revision": 1}, "", "choose loose faces or objects"),
    ("sheet-edit", {"base_revision": 1, "sheet_index": 0, "ops": [{"op": "set", "id": "texts/0"}]}, "ops.0.changes", "required"),
    ("sheet-edit", {"base_revision": 1, "sheet_index": 0, "ops": [{"op": "explode"}]}, "ops.0", ""),
])
def test_remaining_typed_commands_report_the_field(doc, endpoint, body, field, fragment):
    response = doc(endpoint, **body)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_request"
    assert any(item["field"].startswith(field) for item in detail["fields"]), detail
    assert fragment in detail["message"], detail


def test_category_edits_are_typed_too(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    bad = client.post("/api/v1/library/taxonomy/create", json={"name": 5})
    assert bad.status_code == 422 and bad.json()["detail"]["fields"][0]["field"] == "name"
    assert client.post("/api/v1/library/taxonomy/hide", json={"id": "x", "hidden": "yes"}).status_code == 422
    assert client.post("/api/v1/library/taxonomy/explode", json={}).status_code == 404
    assert client.post("/api/v1/library/taxonomy/create", json={"name": "Mi categoría"}).status_code in (200, 201)

"""One error shape for the whole API.

Every non-2xx response carries ``{"detail": {"code", "message", "fields"?}}``:

- ``message`` is a sentence a person can read (the browser shows it as is);
- ``code`` is a stable machine name (``invalid_request``, ``not_found``,
  ``revision_conflict`` ...) clients can branch on;
- ``fields`` (validation errors only) lists ``{"field", "message"}`` per rejected input,
  so a form can point at the box that was wrong.

Handlers that raise ``HTTPException("text")`` keep working: the text becomes ``message``.
Pydantic validation failures from typed payload models are phrased the same way.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
         409: "conflict", 413: "too_large", 415: "unsupported_media_type", 422: "invalid_request",
         429: "rate_limited", 502: "upstream_unavailable"}


def error_body(status: int, detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict) and "message" in detail:
        return {"detail": {"code": detail.get("code") or CODES.get(status, "error"), **{k: v for k, v in detail.items() if k != "code"}}}
    if isinstance(detail, str):
        return {"detail": {"code": CODES.get(status, "server_error" if status >= 500 else "error"), "message": detail}}
    return {"detail": {"code": CODES.get(status, "error"), "message": str(detail)}}


#: Values of the ``operation`` / ``op`` tags that pick a variant of a union body.
_TAGS = {"dimension", "text", "guide-line", "guide-point", "line", "rectangle", "circle", "arc", "polygon",
         "rotated_rectangle", "pie", "arc2", "arc3", "freehand", "page", "add", "set", "remove", "order", "duplicate"}


def _field_name(location: tuple) -> str:
    """The dotted input name, without the part of the path that only says which variant matched."""
    items = list(location[1:] if location and location[0] in ("body", "query", "path", "form") else location)
    parts = []
    for index, part in enumerate(items):
        is_tag = (isinstance(part, str) and part in _TAGS and index + 1 < len(items)
                  and (index == 0 or isinstance(items[index - 1], int)))
        if not is_tag:
            parts.append(str(part))
    return ".".join(parts)


_PHRASES = {
    "missing": "is required",
    "extra_forbidden": "is not a setting of this command",
    "int_parsing": "must be a whole number",
    "float_parsing": "must be a number",
    "bool_parsing": "must be true or false",
    "string_type": "must be text",
    "finite_number": "must be a finite number",
    "list_type": "must be a list",
    "dict_type": "must be an object",
    "int_type": "must be a whole number",
    "float_type": "must be a number",
    "bool_type": "must be true or false",
}


def describe_validation(errors: list[dict[str, Any]]) -> dict[str, Any]:
    fields = []
    for error in errors:
        name = _field_name(tuple(error.get("loc", ())))
        kind = error.get("type", "")
        ctx = error.get("ctx") or {}
        if kind in _PHRASES:
            text = _PHRASES[kind]
        elif kind in {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}:
            bound = ctx.get("gt", ctx.get("ge", ctx.get("lt", ctx.get("le"))))
            text = {"greater_than": f"must be greater than {bound}", "greater_than_equal": f"must be at least {bound}",
                    "less_than": f"must be less than {bound}", "less_than_equal": f"must be at most {bound}"}[kind]
        elif kind in {"string_too_short", "too_short"}:
            text = f"must have at least {ctx.get('min_length')} {'characters' if kind == 'string_too_short' else 'entries'}"
        elif kind in {"string_too_long", "too_long"}:
            text = f"must have at most {ctx.get('max_length')} {'characters' if kind == 'string_too_long' else 'entries'}"
        elif kind == "value_error":
            text = str(error.get("msg", "is not valid")).removeprefix("Value error, ")
        elif kind == "literal_error":
            text = f"must be one of {ctx.get('expected', 'the allowed values')}"
        else:
            text = str(error.get("msg", "is not valid"))
        fields.append({"field": name, "message": f"{name} {text}" if name and kind not in {"value_error"} else (text if kind == "value_error" else text)})
    shown = "; ".join(item["message"] for item in fields[:4])
    if len(fields) > 4:
        shown += f"; and {len(fields) - 4} more"
    return {"code": "invalid_request", "message": shown or "The request is not valid.", "fields": fields}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        return JSONResponse(error_body(exc.status_code, exc.detail), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": describe_validation(exc.errors())}, status_code=422)

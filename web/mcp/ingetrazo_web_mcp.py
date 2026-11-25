#!/usr/bin/env python3
"""IngeTrazo Web as an MCP server: let an AI agent model through the web API.

Standard library only, so it runs on any machine with Python 3.9+ (it does not need the
IngeTrazo code): it talks to a running IngeTrazo Web service over HTTP and speaks the
Model Context Protocol on stdin/stdout.

    INGETRAZO_URL=http://127.0.0.1:8000  INGETRAZO_TOKEN=<access token>  python ingetrazo_web_mcp.py

Every modelling command the service offers becomes one tool, generated from the
service's own OpenAPI schema (so the tools, their arguments and their limits cannot
drift from the API): ``create_box``, ``push_pull``, ``solid_operation`` and so on. Each
call works on the document's latest revision and is one new revision, so the agent's
work is undoable like anyone's (``restore_revision``), conflict-checked, and subject to
the same validation and ownership rules as the browser. The agent can also create
documents, read a summary of the model, look at it (``look`` returns a line drawing as an
image) and export it.

Environment
    INGETRAZO_URL       base URL of the service (default http://127.0.0.1:8000)
    INGETRAZO_TOKEN     access token, when the service has user accounts
    INGETRAZO_DOCUMENT  document id to use when a call names none
    INGETRAZO_MCP_COMMANDS  ``core`` (default: modelling), ``all``, or a comma list of commands
    INGETRAZO_MCP_TIMEOUT   seconds to wait for the service (default 120)
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

VERSION = "0.1.0"
BASE = os.environ.get("INGETRAZO_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("INGETRAZO_TOKEN", "")
TIMEOUT = float(os.environ.get("INGETRAZO_MCP_TIMEOUT", "120"))
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

#: Commands offered by default: the ones that build and edit the model.
CORE_COMMANDS = [
    "create-box", "create-shape", "create-planar", "create-text3d", "push-pull", "offset-face", "follow-me",
    "fillet", "solid-operation", "move-object", "transform-object", "flip-object", "object-lifecycle",
    "object-material", "loose-group", "explode-object", "split-into-pieces", "create-layer", "rename-layer",
    "delete-layer", "set-layer-lock", "assign-layer", "create-annotation", "create-section", "section-fill",
    "set-style", "save-scene", "delete-scene", "insert-component", "insert-person", "loose-push-pull",
    "loose-erase", "loose-paint", "loose-move", "loose-edge-join", "loose-edge-explode-curve", "loose-bridge", "loose-resegment", "set-object-scale",
    "loose-make-faces-extrude", "set-cut-opening", "terrain-create", "terrain-deform", "terrain-stamp", "restore-revision",
]

INSTRUCTIONS = """IngeTrazo is a 3D modeller for architecture (units are metres, Z is up, X right, Y away).
Start with list_documents or create_document, then build with the command tools. Every command
creates a new revision of the document and answers with what changed (new object ids such as
group:3). Use get_model to see the objects, and look to see the model as a line drawing from a
standard view. Objects are named group:N; a nested one is group:N/M. If something goes wrong,
restore_revision with an earlier revision number undoes it (as a new revision)."""

_current: dict[str, str] = {"document": os.environ.get("INGETRAZO_DOCUMENT", "")}


# --- talking to the service ----------------------------------------------------

class ServiceError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = "", fields: list | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.fields = status, code, fields or []


def request(method: str, path: str, body: Any = None, *, raw: bool = False) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            content = response.read()
            return content if raw else (json.loads(content) if content else None)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        message, code, fields = text[:500] or exc.reason, "", []
        try:
            detail = json.loads(text).get("detail")
            if isinstance(detail, dict):
                message, code, fields = detail.get("message", message), detail.get("code", ""), detail.get("fields", [])
            elif isinstance(detail, str):
                message = detail
        except ValueError:
            pass
        raise ServiceError(message, exc.code, code, fields) from None
    except (urllib.error.URLError, OSError) as exc:
        raise ServiceError(f"Cannot reach the IngeTrazo service at {BASE}: {getattr(exc, 'reason', exc)}") from None


def multipart(path: str, filename: str, content: bytes) -> Any:
    boundary = "----ingetrazo" + str(int(time.time() * 1000))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=body, headers=headers), timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise ServiceError(exc.read().decode("utf-8", "replace")[:500], exc.code) from None


# --- tools generated from the OpenAPI schema -------------------------------------------

def _resolve(schema: Any, components: dict, depth: int = 0) -> Any:
    """Inline ``$ref``s so a tool's schema is self-contained."""
    if depth > 12:
        return {}
    if isinstance(schema, list):
        return [_resolve(item, components, depth + 1) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _resolve(components.get(name, {}), components, depth + 1)
    return {key: _resolve(value, components, depth + 1) for key, value in schema.items() if key != "discriminator"}


def _flatten(schema: dict) -> dict:
    """One object schema for a body that is a union of variants (``operation`` picks one).

    Tool schemas must be a plain object, so the variants' properties are merged and the
    description says which operation needs what."""
    variants = schema.get("oneOf") or schema.get("anyOf")
    if not variants:
        return schema
    properties: dict[str, Any] = {}
    notes, tags = [], []
    tag_key = "operation"
    for variant in variants:
        props = variant.get("properties", {})
        required = [name for name in variant.get("required", []) if name != "base_revision"]
        tag = None
        for key in ("operation", "op"):
            if key in props:
                one = props[key].get("const", (props[key].get("enum") or [None])[0] if len(props[key].get("enum") or []) == 1 else None)
                if one is not None:
                    tag, tag_key = one, key
        if tag is not None:
            tags.append(tag)
        for name, definition in props.items():
            if name == "base_revision" or (tag is not None and name == tag_key):
                continue
            properties.setdefault(name, definition)
        if tag is not None:
            others = [name for name in required if name != tag_key]
            optional = [name for name in props if name not in required and name not in ("base_revision", tag_key)]
            notes.append(f"{tag_key}={tag}: needs {', '.join(others) or 'nothing more'}"
                         + (f"; optional {', '.join(optional)}" if optional else ""))
    if tags:
        key = tag_key
        properties[key] = {"type": "string", "enum": tags, "description": "Which kind of shape or annotation to make."}
    return {"type": "object", "properties": properties, "required": [key] if tags else [],
            "description": " | ".join(notes)}


def build_tools(spec: dict, wanted: set[str] | None) -> dict[str, dict]:
    """``{tool name: {command, description, schema}}`` for every offered modelling command."""
    components = spec.get("components", {}).get("schemas", {})
    tools: dict[str, dict] = {}
    for path, item in spec.get("paths", {}).items():
        match = re.fullmatch(r"/api/v1/documents/\{document_id\}/commands/([a-z0-9\-]+)", path)
        if not match or "post" not in item:
            continue
        command = match.group(1)
        if wanted is not None and command not in wanted:
            continue
        operation = item["post"]
        body = (operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}))
        schema = _flatten(_resolve(copy.deepcopy(body), components))
        properties = {k: v for k, v in schema.get("properties", {}).items() if k != "base_revision"}
        properties = {"document_id": {"type": "string", "description": "The document to edit; defaults to the one used last."},
                      **properties}
        for definition in properties.values():
            definition.pop("title", None)
        required = [name for name in schema.get("required", []) if name != "base_revision"]
        description = (operation.get("description") or operation.get("summary") or command).strip().splitlines()[0]
        extra = schema.get("description")
        tools[command.replace("-", "_")] = {
            "command": command,
            "description": f"{description}{(' ' + extra) if extra else ''} Creates a new revision of the document.",
            "schema": {"type": "object", "properties": properties, "required": required},
        }
    return tools


_tools_cache: dict[str, dict] | None = None


def command_tools() -> dict[str, dict]:
    global _tools_cache
    if _tools_cache is None:
        setting = os.environ.get("INGETRAZO_MCP_COMMANDS", "core").strip()
        wanted = None if setting == "all" else set(CORE_COMMANDS if setting == "core" else
                                                    [name.strip() for name in setting.split(",") if name.strip()])
        _tools_cache = build_tools(request("GET", "/openapi.json"), wanted)
    return _tools_cache


# --- helper tools -----------------------------------------------------------------------

DOCUMENT = {"type": "string", "description": "Document id; defaults to the one used last."}

HELPERS: dict[str, dict] = {
    "list_documents": {
        "description": "List the documents on the service (id, name, latest revision, object counts).",
        "schema": {"type": "object", "properties": {}}},
    "create_document": {
        "description": "Create an empty document and make it the current one. Returns its id.",
        "schema": {"type": "object", "properties": {"name": {"type": "string", "description": "A name for the document."}},
                   "required": ["name"]}},
    "get_model": {
        "description": "Summarise a document: units, bounds, counts, layers, scenes and its objects (id, name, kind, layer, faces).",
        "schema": {"type": "object", "properties": {"document_id": DOCUMENT}}},
    "list_revisions": {
        "description": "List a document's revisions, oldest first. Use restore_revision to go back to one.",
        "schema": {"type": "object", "properties": {"document_id": DOCUMENT}}},
    "look": {
        "description": "Draw the model as a hidden-line drawing from a standard view and return it as an image.",
        "schema": {"type": "object", "properties": {
            "document_id": DOCUMENT,
            "view": {"type": "string", "description": "top, bottom, front, back, left, right, iso or scene:<name>.", "default": "iso"},
            "width": {"type": "integer", "minimum": 300, "maximum": 2400, "default": 900},
            "revision": {"type": "integer", "description": "Revision to draw; defaults to the latest."}}}},
    "export_model": {
        "description": "Export the latest revision to a file on this computer and return its path.",
        "schema": {"type": "object", "properties": {
            "document_id": DOCUMENT,
            "format": {"type": "string", "enum": ["glb", "gltf", "obj", "stl", "dae", "dxf", "ifc"]},
            "path": {"type": "string", "description": "Where to save it; defaults to a temporary folder."}},
            "required": ["format"]}},
}


def _document(arguments: dict) -> str:
    identifier = arguments.get("document_id") or _current["document"]
    if not identifier:
        raise ServiceError("No document yet: call create_document (or list_documents and pass a document_id).")
    _current["document"] = identifier
    return urllib.parse.quote(identifier)


def _objects(summary: dict) -> dict[str, dict]:
    return {item["id"]: item for item in summary.get("outline", {}).get("items", [])}


def _describe(item: dict) -> str:
    faces = item.get("geometry", {}).get("faces", 0)
    kids = len(item.get("children", []))
    return f"{item['id']} \"{item['name']}\" ({item['kind']}, layer {item['layer']}, {faces} faces{f', {kids} parts' if kids else ''})"


def tool_list_documents(arguments: dict) -> list[dict]:
    lines = []
    for record in request("GET", "/api/v1/documents")["documents"]:
        summary = record["revisions"][-1]["summary"]
        lines.append(f"{record['id']}  \"{record['name']}\"  revision {record['latest_revision']}  "
                     f"{summary.get('groups', 0)} groups, {summary.get('unique_geometry', {}).get('faces', 0)} faces")
    return _text("\n".join(lines) or "No documents yet. Use create_document.")


def tool_create_document(arguments: dict) -> list[dict]:
    record = request("POST", "/api/v1/documents/blank", {"name": str(arguments.get("name", "Untitled"))})
    _current["document"] = record["id"]
    return _text(f"Created document {record['id']} \"{record['name']}\" (revision 1, empty). It is now the current document.")


def tool_get_model(arguments: dict) -> list[dict]:
    record = request("GET", f"/api/v1/documents/{_document(arguments)}")
    summary = record["revisions"][-1]["summary"]
    bounds = summary.get("bounds") or {}
    objects = list(_objects(summary).values())
    lines = [f"\"{record['name']}\" revision {record['latest_revision']}; units {summary['units']['length']}; "
             f"bounds {bounds.get('min')} to {bounds.get('max')}",
             f"{len(objects)} top-level objects; {summary['layers']} layers; scenes: "
             f"{[view['name'] for view in summary.get('saved_view_details', [])]}; sheets {summary.get('compositions', 0)}; "
             f"loose faces {summary['loose_geometry']['faces']}"]
    lines += ["layers: " + ", ".join(layer["name"] + (" (hidden)" if not layer["visible"] else "")
                                       for layer in summary.get("layer_details", []))]
    lines += [_describe(item) for item in objects[:150]]
    if len(objects) > 150:
        lines.append(f"... and {len(objects) - 150} more")
    return _text("\n".join(lines))


def tool_list_revisions(arguments: dict) -> list[dict]:
    record = request("GET", f"/api/v1/documents/{_document(arguments)}")
    return _text("\n".join(
        f"revision {item['number']}  {item['created_at']}  {item['summary'].get('groups', 0)} groups, "
        f"{item['summary'].get('unique_geometry', {}).get('faces', 0)} faces" for item in record["revisions"]))


def tool_look(arguments: dict) -> list[dict]:
    document = _document(arguments)
    revision = arguments.get("revision") or request("GET", f"/api/v1/documents/{document}")["latest_revision"]
    query = urllib.parse.urlencode({"view": arguments.get("view", "iso"), "width": int(arguments.get("width", 900))})
    png = request("GET", f"/api/v1/documents/{document}/revisions/{revision}/render.png?{query}", raw=True)
    return [{"type": "text", "text": f"Revision {revision}, {arguments.get('view', 'iso')} view (hidden-line drawing)."},
            {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]


def tool_export_model(arguments: dict) -> list[dict]:
    document = _document(arguments)
    record = request("GET", f"/api/v1/documents/{document}")
    job = request("POST", f"/api/v1/documents/{document}/revisions/{record['latest_revision']}/exports",
                  {"format": arguments["format"]})
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        job = request("GET", f"/api/v1/jobs/{job['id']}")
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.5)
    if job["status"] != "completed":
        raise ServiceError(f"The export {job['status']}: {job.get('message', '')}")
    content = request("GET", f"/api/v1/jobs/{job['id']}/artifact", raw=True)
    target = arguments.get("path") or os.path.join(tempfile.mkdtemp(prefix="ingetrazo-export-"), job["artifact"])
    with open(os.path.expanduser(target), "wb") as handle:
        handle.write(content)
    return _text(f"Saved {len(content)} bytes to {os.path.expanduser(target)}")


HELPER_FUNCTIONS = {"list_documents": tool_list_documents, "create_document": tool_create_document,
                    "get_model": tool_get_model, "list_revisions": tool_list_revisions, "look": tool_look,
                    "export_model": tool_export_model}


def _text(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def run_command(tool: dict, arguments: dict) -> list[dict]:
    """Run one modelling command against the document's latest revision."""
    document = _document(arguments)
    body = {key: value for key, value in arguments.items() if key != "document_id"}
    for attempt in range(2):
        record = request("GET", f"/api/v1/documents/{document}")
        before = _objects(record["revisions"][-1]["summary"])
        try:
            revised = request("POST", f"/api/v1/documents/{document}/commands/{tool['command']}",
                              {"base_revision": record["latest_revision"], **body})
            break
        except ServiceError as exc:
            if exc.code == "revision_conflict" and attempt == 0:
                continue                                    # someone edited meanwhile: try on the new latest revision
            raise
    after = _objects(revised["revisions"][-1]["summary"])
    created = [after[key] for key in after if key not in before]
    removed = [before[key] for key in before if key not in after]
    lines = [f"Done: revision {revised['latest_revision']}."]
    if created:
        lines.append("New objects: " + "; ".join(_describe(item) for item in created[:20]))
    if removed:
        lines.append("Removed: " + ", ".join(f"{item['id']} \"{item['name']}\"" for item in removed[:20]))
    result = revised.get("command_result")
    if result:
        lines.append(f"Result: {json.dumps(result)[:400]}")
    return _text("\n".join(lines))


# --- the protocol --------------------------------------------------------------------------

def list_tools() -> list[dict]:
    tools = [{"name": name, "description": value["description"], "inputSchema": value["schema"]}
             for name, value in HELPERS.items()]
    try:
        tools += [{"name": name, "description": value["description"], "inputSchema": value["schema"]}
                  for name, value in command_tools().items()]
    except ServiceError as exc:
        print(f"[ingetrazo-mcp] command tools unavailable: {exc}", file=sys.stderr)
    return tools


def call_tool(name: str, arguments: dict) -> dict:
    try:
        if name in HELPER_FUNCTIONS:
            return {"content": HELPER_FUNCTIONS[name](arguments)}
        tool = command_tools().get(name)
        if tool is None:
            return {"content": _text(f"Unknown tool {name}."), "isError": True}
        return {"content": run_command(tool, arguments)}
    except ServiceError as exc:
        text = str(exc)
        if exc.fields:
            text += "\n" + "\n".join(f"- {item.get('message')}" for item in exc.fields[:8])
        return {"content": _text(text), "isError": True}
    except Exception as exc:  # noqa: BLE001 - a tool must answer, never kill the server
        return {"content": _text(f"{type(exc).__name__}: {exc}"), "isError": True}


def handle(message: dict) -> dict | None:
    method, identifier = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if identifier is None:
        return None                                        # a notification needs no answer
    try:
        if method == "initialize":
            wanted = params.get("protocolVersion")
            result = {"protocolVersion": wanted if wanted in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "ingetrazo-web", "version": VERSION}, "instructions": INSTRUCTIONS}
        elif method == "tools/list":
            result = {"tools": list_tools()}
        elif method == "tools/call":
            result = call_tool(str(params.get("name")), params.get("arguments") or {})
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": identifier, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), flush=True)
            continue
        response = handle(message) if isinstance(message, dict) else None
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()

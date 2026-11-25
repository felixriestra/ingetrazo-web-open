"""The MCP server: tools generated from the API, calls become revisions, errors are readable."""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")

from web.backend.ingetrazo_web.app import create_app  # noqa: E402
from web.backend.ingetrazo_web.auth import Users  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "web" / "mcp" / "ingetrazo_web_mcp.py"


def _serve(app):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread, port


class Client:
    """A bare-bones MCP client over the server's stdin/stdout."""

    def __init__(self, port: int, token: str = "", **env):
        environment = {**os.environ, "INGETRAZO_URL": f"http://127.0.0.1:{port}", "INGETRAZO_MCP_TIMEOUT": "60", **env}
        if token:
            environment["INGETRAZO_TOKEN"] = token
        self.process = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, env=environment)
        self.next_id = 0

    def call(self, method: str, **params):
        self.next_id += 1
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        reply = json.loads(self.process.stdout.readline())
        assert reply["id"] == self.next_id
        return reply

    def tool(self, tool_name: str, /, **arguments):
        reply = self.call("tools/call", name=tool_name, arguments=arguments)
        return reply["result"]

    def text(self, tool_name: str, /, **arguments) -> str:
        return "\n".join(part["text"] for part in self.tool(tool_name, **arguments)["content"] if part["type"] == "text")

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


@pytest.fixture()
def service(tmp_path):
    server, thread, port = _serve(create_app(tmp_path / "data"))
    client = Client(port)
    yield client, port, tmp_path
    client.close()
    server.should_exit = True
    thread.join(timeout=10)


def test_the_protocol_handshake_and_the_tool_list(service):
    client, _, _ = service
    hello = client.call("initialize", protocolVersion="2025-06-18", capabilities={}, clientInfo={"name": "t", "version": "1"})["result"]
    assert hello["protocolVersion"] == "2025-06-18" and hello["serverInfo"]["name"] == "ingetrazo-web" and "tools" in hello["capabilities"]
    assert client.call("ping")["result"] == {}
    assert client.call("no/such/method")["error"]["code"] == -32601
    tools = {tool["name"]: tool for tool in client.call("tools/list")["result"]["tools"]}
    assert {"list_documents", "create_document", "get_model", "look", "create_box", "push_pull", "create_shape", "solid_operation"} <= set(tools)
    assert "run_extension" not in tools and "sheet_edit" not in tools                     # core set only
    box = tools["create_box"]["inputSchema"]
    assert box["type"] == "object" and "size" in box["properties"] and "base_revision" not in box["properties"]
    assert box["required"] == ["size"] and "$ref" not in json.dumps(box)
    shape = tools["create_shape"]["inputSchema"]                                          # a union body is flattened
    assert shape["type"] == "object" and shape["properties"]["operation"]["enum"][0] == "polygon" and "sides" in shape["properties"]
    assert shape["required"] == ["operation"] and "operation=polygon" in tools["create_shape"]["description"]
    for tool in tools.values():
        assert tool["inputSchema"]["type"] == "object"


def test_building_looking_and_undoing_through_tools(service):
    client, _, tmp_path = service
    assert "No documents yet" in client.text("list_documents")
    assert "No document yet" in client.tool("create_box", size=[1, 1, 1])["content"][0]["text"]
    created = client.text("create_document", name="Casa")
    assert "revision 1" in created
    made = client.text("create_box", size=[4, 3, 2.5], name="Muro")
    assert "revision 2" in made and 'group:0 "Muro"' in made
    shape = client.text("create_shape", operation="polygon", sides=6, radius=1, origin=[8, 0, 0], name="Hex")
    assert "revision 3" in shape and "group:1" in shape
    moved = client.text("move_object", object_id="group:0", delta=[0, 5, 0])
    assert "revision 4" in moved
    model = client.text("get_model")
    assert "Muro" in model and "Hex" in model and "units m" in model
    assert "revision 4" in client.text("list_revisions").splitlines()[-1]

    seen = client.tool("look", view="front", width=500)
    assert seen["content"][1]["type"] == "image" and seen["content"][1]["mimeType"] == "image/png"
    assert base64.b64decode(seen["content"][1]["data"]).startswith(b"\x89PNG")

    undone = client.text("restore_revision", source_revision=2)
    assert "revision 5" in undone and "Removed" in undone and "group:1" in undone         # the hexagon is gone again
    saved = client.text("export_model", format="stl", path=str(tmp_path / "casa.stl"))
    assert "casa.stl" in saved and (tmp_path / "casa.stl").stat().st_size > 100


def test_refusals_come_back_as_readable_tool_errors(service):
    client, _, _ = service
    client.text("create_document", name="x")
    bad = client.tool("create_box", size=[1, 0, 1])
    assert bad["isError"] and "size.1 must be greater than 0" in bad["content"][0]["text"]
    assert client.tool("push_pull", object_id="group:9", direction="+z", distance=1)["isError"]
    assert client.tool("no_such_tool")["isError"]
    assert client.tool("look")["isError"]                                                  # nothing to draw yet
    assert client.tool("get_model", document_id="00000000-0000-0000-0000-000000000000")["isError"]


def test_another_editor_in_between_does_not_make_a_call_fail(service):
    client, port, _ = service
    client.text("create_document", name="shared")
    # the server reads the latest revision on each call, so edits made elsewhere just stack
    import urllib.request
    doc = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/documents").read())["documents"][0]
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/documents/{doc['id']}/commands/create-box",
                                     data=json.dumps({"base_revision": 1, "size": [1, 1, 1]}).encode(),
                                     headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request)
    assert "revision 3" in client.text("create_box", size=[2, 2, 2])


def test_with_accounts_the_token_is_required_and_scopes_the_documents(tmp_path):
    data = tmp_path / "data"
    users = Users(data)
    ana, ben = users.add("ana"), users.add("ben")
    server, thread, port = _serve(create_app(data))
    try:
        anon = Client(port)
        assert anon.tool("list_documents")["isError"]
        anon.close()
        a, b = Client(port, ana), Client(port, ben)
        created = a.text("create_document", name="privado")
        assert "privado" in a.text("list_documents")
        assert "privado" not in b.text("list_documents")
        document_id = created.split()[2]
        assert b.tool("get_model", document_id=document_id)["isError"]                     # not found for ben
        a.close()
        b.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_all_commands_can_be_offered(tmp_path):
    server, thread, port = _serve(create_app(tmp_path / "data"))
    try:
        client = Client(port, INGETRAZO_MCP_COMMANDS="all")
        names = {tool["name"] for tool in client.call("tools/list")["result"]["tools"]}
        assert {"sheet_edit", "run_extension", "set_georef", "import_survey"} <= names
        assert len(names) > 50
        client.close()
        limited = Client(port, INGETRAZO_MCP_COMMANDS="create-box,push-pull")
        names = {tool["name"] for tool in limited.call("tools/list")["result"]["tools"]}
        assert {"create_box", "push_pull"} <= names and "move_object" not in names
        limited.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

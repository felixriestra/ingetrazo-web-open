# IngeTrazo Web as an MCP server

Lets an AI agent (Claude Code, Claude Desktop, any MCP client) model through a running
IngeTrazo Web service: it draws, edits, looks at the model and exports it, using the same
validated commands the browser uses. Each tool call is one new revision, so the agent's
work is conflict-checked, undoable (`restore_revision`) and visible in the browser as it
happens. The script is standard-library Python 3.9+ and does not need the IngeTrazo code,
so it can run on a different machine from the service.

## Connect

1. Start the service (`python -m web.backend`). With user accounts on, create an access
   token for the agent: `python -m web.backend users add agent` (its documents belong to
   that user; an agent never sees other users' documents).
2. Register the server with your client.

   Claude Code:

   ```bash
   claude mcp add ingetrazo \
     --env INGETRAZO_URL=http://127.0.0.1:8000 --env INGETRAZO_TOKEN=<token> \
     -- python3 /path/to/web/mcp/ingetrazo_web_mcp.py
   ```

   Claude Desktop (`claude_desktop_config.json`):

   ```json
   {"mcpServers": {"ingetrazo": {
     "command": "python3", "args": ["/path/to/web/mcp/ingetrazo_web_mcp.py"],
     "env": {"INGETRAZO_URL": "http://127.0.0.1:8000", "INGETRAZO_TOKEN": "<token>"}}}}
   ```

   Leave `INGETRAZO_TOKEN` out when the service has no accounts (loopback use).

## Tools

- `list_documents`, `create_document`, `get_model` (objects, layers, scenes, bounds),
  `list_revisions`, `look` (a hidden-line drawing as an image, from `top`, `front`, `iso`, a
  saved scene ...), `export_model` (GLB, glTF, OBJ, STL, DAE, DXF, IFC to a local file).
- One tool per modelling command, generated from the service's OpenAPI schema: `create_box`,
  `create_shape`, `create_planar`, `push_pull`, `offset_face`, `follow_me`, `fillet`,
  `solid_operation`, `move_object`, `transform_object`, `object_lifecycle`, `object_material`,
  `loose_group`, `create_layer`, `create_annotation`, `create_text3d`, `restore_revision` ...
  Arguments, ranges and error messages are the API's own, so they cannot drift.
  Every answer lists the objects the call created or removed (`group:3 "Muro" ...`).

`INGETRAZO_MCP_COMMANDS` chooses the command tools: `core` (default, modelling), `all`
(everything, including sheets, geo-reference and extensions) or a comma list such as
`create-box,push-pull`. `INGETRAZO_DOCUMENT` sets a default document.

## Limits

The agent sees the model through `get_model` and `look` (a line drawing, not a shaded
render), not through the browser's viewport. Each call is a whole-file revision, so on very
large models calls take seconds (see the benchmark in `docs/web-port-plan.md`).

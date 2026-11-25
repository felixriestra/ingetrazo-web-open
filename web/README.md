# IngeTrazo web prototype

This began as the Phase 0 read-only vertical slice described in
[`docs/web-port-plan.md`](../docs/web-port-plan.md). It uses the existing native
loader and GLB exporter without constructing the desktop interface.

## Run locally

From the repository root, in an environment that already has IngeTrazo's main
requirements installed:

```bash
python -m pip install -r web/backend/requirements.txt
python -m web.backend            # 127.0.0.1:8000, loopback only
```

Build the pinned Three.js client once:

```bash
cd web/frontend
npm ci
npm run build
cd ../..
```

The service has no authentication yet, so it refuses non-loopback hosts unless
`INGETRAZO_WEB_ALLOW_REMOTE=1` is set (do that only behind your own authenticating
proxy). `INGETRAZO_WEB_HOST`, `INGETRAZO_WEB_PORT`, `INGETRAZO_WEB_JOB_WORKERS` (conversion processes at once, default 2), `INGETRAZO_WEB_KEEP_REVISIONS` (how many revisions of each document to keep, 0 = all; at least 5 when set), `INGETRAZO_WEB_JOB_TIMEOUT` (seconds,
default 900) and `INGETRAZO_WEB_JOB_MEMORY_MIB` (Linux, default 4096) tune it. Raw `uvicorn` still works for development with `--reload`.

Every error response is `{"detail": {"code", "message", "fields"?}}`; `fields` names each rejected input.
`python -m web.backend.benchmark_commands` times the edit cycle on synthetic models.

Then open <http://127.0.0.1:8000> and choose or drag in an `.igz` document. The default upload
limit is 100 MiB; this is a prototype safety limit, not a final product quota.
Saved documents use immutable numbered revisions under `var/web-data` by
default. Set `INGETRAZO_WEB_DATA` to place that data elsewhere.

The viewer restores document cameras and named scenes, reports native layer
visibility and the bounded group/component hierarchy, and lets you click a
rendered triangle to inspect its material and hit point in IngeTrazo's original
Z-up coordinates. Semantic GLB nodes connect canvas selection to the object
tree. Layers can be shown and hidden, object-tree controls focus model objects,
native section planes can be displayed or applied as interactive preview cuts,
the world axes can be toggled, and the two-point measurement tool reports
distances in document units.

The API now exposes both an ephemeral conversion endpoint and persistent
document endpoints under `/api/v1/documents`. A stored native revision can
always be downloaded unchanged; its GLB preview is generated and cached on
first request. Starting another upload or opening another saved document
cancels the older browser request so stale work cannot replace the newer model.

Stored documents support the first authoritative edit path: change layer or
top-level object visibility and choose **Save presentation changes**. The
service reloads the native base revision, applies all visibility changes
atomically, and writes a new immutable `.igz` revision. Every command carries
its expected base revision; a stale tab receives a conflict instead of silently
replacing newer work. Deterministic hierarchy-path IDs keep this workflow safe
for legacy files created before object UIDs were stored.

The Phase 3 foundation adds the first native geometry command. Select a
top-level object, enter an X/Y/Z offset in the document's displayed units, and
the service applies IngeTrazo's native group-move operation before creating and
opening the next revision. Any historical revision can be restored as another
immutable revision, providing a recovery/undo path without deleting history.
The browser exposes that mechanism as explicit Undo/Redo controls. Its local
object clipboard uses the same native duplicate command, so pasted geometry is
another conflict-checked revision rather than transient browser data.
The same selection inspector supports native rotation, non-uniform scale,
duplicate, rename, and recoverable delete operations for top-level groups and
components.
Stored documents can also create a named solid box from numeric width, depth,
height, and origin values in the document's displayed units. Numeric line,
rectangle, segmented-circle, and arc commands create native geometry. Arcs
retain their shared curve identity across the `.igz` round trip; the semantic
GLB preview retains and directly selects free edges. Rectangle, circle, and
arc inputs can target the fixed world XY, XZ, or YZ plane.
The canvas **Sketch line** mode adds a direct workflow: choose two model or
ground points and it snaps near triangle vertices, reports the active
vertex/surface/ground inference, fills the numeric line fields, and commits the
same native line command.

Selected face-bearing objects also expose numeric push/pull. A one-face object
uses its native normal; solids can target a signed world-axis face. The command
runs the same stitch, plane-rebuild, and watertight-solid guard as the desktop
tool and records the result as another immutable revision.

One-face planar objects can be offset inward or outward through the native
arrangement-based offset engine. The result is real ring/inner-face topology,
ready for later wall extrusion rather than a display-only outline.

The same selection inspector can apply or clear an object-level colour and
opacity. This uses IngeTrazo's native group material rule: default faces inherit
the object paint while individually painted faces retain their own material.

The create panel also writes native aligned or world-axis dimensions, leader
text, construction lines, and construction points. These annotations remain
first-class `.igz` entities and are drawn as lightweight Three.js overlays;
dimension text uses the document's native unit formatter and custom text may
include `<>` as the measured-value placeholder. Annotation layers follow the
same live visibility controls as model geometry.

Selected objects can be classified with the native curated IFC4 classes. The
browser then shows the production engine's class-specific takeoff (for example
wall area or column volume), raw area/volume, and exposes revision-pinned CSV
and IFC4 downloads. The classification stays as group metadata in `.igz`; it
is not baked into the preview mesh.

The geospatial inspector saves a native WGS84 datum and true-north rotation,
imports standard P,N,E,Z survey rows, and creates local traced paths or closed
terrain boundaries. Survey controls and paths are rendered as model-space
overlays while remaining native `.igz` entities. Existing photogrammetry
metadata is reported without flattening its source reference.
Once a datum exists, the same inspector can save a licensed Esri imagery,
OpenStreetMap, or Sentinel-2 capture. The document retains provider, zoom,
capture radius, opacity, and attribution; the browser projects the resulting
XYZ tiles onto their native local-metre ground quads.
Surveyed terrain can be pasted as a bounded row-major local XYZ grid. It is
triangulated into the native packed reference-mesh format, survives `.igz`
round trips, participates in height queries, and is shaded in the web preview.

The display inspector applies IngeTrazo's built-in styles and stores solar
shadow date, local time, darkness, and optional UTC offset. The service derives
the sun from the document datum (or the native default location) and the
Three.js viewport uses that direction for real-time cast shadows. Every change
creates another conflict-checked native revision.

The sheet inspector creates a native A4–A0 composition with a standard or
saved-scene view at an exact scale. Each immutable revision exposes an
exact-page-size server-rendered PDF. The PDF path uses the native hidden-line
engine and vector pens, so printing does not depend on browser canvas pixels.

**Open composer** (per sheet) lays the page out in the browser: add views, texts,
images, north arrows, scale bars, legends, shapes and the title block, drag or
resize them on the paper, and edit their fields in the side panel (page size,
margins and border too). The page is drawn by the server with the desktop
composer's own painting routines, so the screen, the PDF and the desktop agree;
each change is one revision.

### SketchUp files

SKP **import** (SketchUp files, read by OpenSKP, MIT, pure Python) is included: File >
Import model accepts `.skp`, the conversion runs in the job process, and a file that cannot
be read fails its job with a message. SKP **export** is not part of the open-source
release: its writer is not in this repository, and its place in
`web/backend/ingetrazo_web/interchange.py` (`EXPORT_FORMATS` and the `skp` branch of
`export_scene`) and in the client's export list is commented out. `edition.py` still looks
for a writer at run time (`formats.skp_out`), so a separate build that adds one can switch
it on with `INGETRAZO_WEB_ENABLE_SKP_EXPORT=1` after restoring those lines.
`python -m web.backend edition` and `GET /api/v1/capabilities`
(`interoperability.edition`, `interoperability.skp`) say which build is running; this one
reports `edition: open`. No code here may import `formats.skp_out` at module level, and a
test enforces it.

### Driving it from an AI agent (MCP)

`web/mcp/ingetrazo_web_mcp.py` is a Model Context Protocol server (standard library only)
that exposes every modelling command as a tool, plus `look` (a line drawing as an image),
`get_model` and `export_model`, so Claude Code or Claude Desktop can model through the same
validated, undoable API. See `web/mcp/README.md`.

### Accounts and ownership

Off by default: on one machine, bound to loopback, nothing asks you to sign in. Create a
user and it turns on:

```bash
python -m web.backend users add ana --admin   # prints the access token once
python -m web.backend users add ben
python -m web.backend users token ben         # issue a new token (the old one stops working)
python -m web.backend users list | remove NAME
```

From then on every API call needs a credential (the browser asks for the token once and
keeps a session cookie; scripts send `Authorization: Bearer <token>`), each document and
job belongs to the user who made it, and other users get `404` for it. Administrators see
everything (including documents made before accounts existed) and alone may change the
shared component categories. With accounts on the server may bind beyond loopback; put
TLS in front and set `INGETRAZO_WEB_SECURE_COOKIES=1`. `INGETRAZO_WEB_AUTH=0` forces it
off, `=1` forces it on. There are no passwords, e-mail, password reset or per-user quotas.

### Extensions

Put `*.py` files in the server's extensions folder (`$INGETRAZO_WEB_EXTENSIONS`,
default `extensions` inside the data folder). Each declares `EXTENSION` (name,
description, parameters) and `run(scene, params)`; it appears in the Extensions
menu, gets a form for its parameters, and runs as one revision. See
`examples/web-extensions/column_grid.py` and `web/backend/ingetrazo_web/extensions.py`.
Extensions run in their own process, stopped after `INGETRAZO_WEB_EXTENSION_TIMEOUT`
seconds (default 60), with the server's rights, and can only be installed by whoever
controls the server. The desktop's Qt plugins are not supported in the browser.

### Undo, redo and revision history

Every edit is saved at once as a revision. **Undo and Redo step back and forth through the
edits** (as many as are kept): each undo or redo is itself a new revision that records the
step it took, so the position in the history is rebuilt from the saved revisions and is the
same after a reload or in another browser. A new edit after an undo drops the redo path.
`INGETRAZO_WEB_KEEP_REVISIONS=N` makes the server delete the oldest revisions as new ones
arrive; it always keeps the first revision, the newest N, the states Undo and Redo can
reach and the revisions an undo points back to, so Undo goes back at least N-1 steps.
`python -m web.backend prune [--keep N]` applies a limit to existing documents. Preferences >
General can also save layer and object visibility changes by themselves after a quiet spell.

### Preferences kept in the browser

**Window > Preferences…** gathers them in tabs, as on the desktop:

- **General:** theme, language (the desktop's translations), auto-save of presentation changes, what a left-drag does with the
  Select tool, toolbar icon size, orbit speed, zoom speed, invert wheel zoom, invert vertical
  orbit.
- **Units:** show each document's own units, or always use a chosen length unit (m, cm, mm,
  ft, in) and number of decimals for the Measurements box and the forms. The document keeps
  storing metres.
- **Import:** the scale applied to OBJ, STL and DXF imports, and whether to ask each time.
- **Keyboard shortcuts:** the editor (also under Help); export and import as JSON.

The toolbar layout is remembered separately (drag a grip to dock top or left, or float;
double-click a grip to restore it).

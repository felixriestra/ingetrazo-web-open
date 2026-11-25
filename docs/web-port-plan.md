# IngeTrazo web application plan

## Scope

This plan covers the original upstream IngeTrazo application. It does not
include 2DWM-specific cabinet, manufacturing, CAM, or component-database
features.

The objective is a browser application that can open, inspect, edit, save, and
exchange IngeTrazo architectural models while retaining `.igz` as the canonical
document format. The desktop application remains usable throughout the port.

## Product boundary

The browser owns interaction, presentation, and GPU rendering. The existing
Python core remains the initial source of truth for document semantics and
geometry operations.

```text
Browser (TypeScript + Three.js)
  - viewport, selection, snapping, tools, panels
  - local interaction previews
                 |
          HTTP / WebSocket
                 |
Python service (FastAPI)
  - .igz load/save and validation
  - authoritative modeling commands
  - imports/exports and long-running jobs
                 |
Existing IngeTrazo core + object storage
```

The first releases should not attempt a line-for-line Qt rewrite. They should
establish a stable headless boundary, then move user-visible workflows one at a
time.

## Architecture decisions

1. **Canonical document:** keep `.igz` and its versioned schema. Do not create a
   second browser-only model format.
2. **Preview format:** use GLB for read-only viewport delivery because IngeTrazo
   already exports it and Three.js consumes it natively.
3. **Authoritative edits:** send explicit commands to the Python service. The
   service validates and applies them to a `Scene`; the browser may show an
   optimistic preview while waiting.
4. **Headless boundary:** web code may import `core`, `formats`, and `georef`, but
   must not import `views` or construct `QApplication`/`QOpenGLWidget`.
5. **Qt math types:** tolerate `QVector3D` and `QMatrix4x4` in the first slice.
   Introduce plain transport types at the service boundary and progressively
   reduce Qt dependencies inside the modeling core.
6. **Files and jobs:** store immutable document revisions and run expensive
   imports/exports in workers. Do not keep a single web request open for large
   SKP, terrain, or photogrammetry jobs.
7. **Security:** treat every uploaded model as untrusted input; enforce size,
   type, expansion, path, and execution-time limits.

## Phases

### Phase 0 — baseline and contracts

- Record supported upstream capabilities and representative test documents.
- Add a headless service layer around scene loading, summaries, and GLB export.
- Define versioned HTTP endpoints and JSON error responses.
- Prove that example `.igz` documents load and export without a Qt window.
- Add tests that prevent accidental dependencies on the desktop UI.

Exit criterion: a browser can upload an upstream `.igz`, see document metadata,
and display a generated GLB preview.

### Phase 1 — web viewer MVP

- Build the Three.js viewport: orbit/pan/zoom, fit extents, perspective and
  orthographic cameras, grid, axes, faces, edges, materials, and textures.
- Add an object/layer tree and read-only property inspector.
- Preserve saved camera, units, visibility, groups/components, and section
  display state where the preview format permits it.
- Add streaming progress and cancellation for larger documents.

Exit criterion: representative architectural projects are visually comparable
to the desktop viewport and remain responsive at agreed model sizes.

### Phase 2 — document persistence

- Create/open/save/save-as in browser storage backed by immutable revisions.
- Add autosave, conflict detection, recovery, and explicit export/download.
- Preserve forward-version errors and damaged-entity recovery behavior from
  the native loader.
- Add authentication, project ownership, quotas, and audit metadata when the
  application moves beyond local development.

Exit criterion: users can safely round-trip `.igz` documents between desktop
and web without semantic loss for the supported feature set.

### Phase 3 — core modeling tools

- Selection, inference, snapping, work planes, and numeric input.
- Line, rectangle, circle/arc, move, rotate, scale, offset, erase, and
  push/pull.
- Groups, components, nested edit contexts, undo/redo, and clipboard.
- Dimensions, text, guides, materials, and entity properties.
- Encode edits as tested, versioned commands rather than transferring whole
  scenes after every action.

Exit criterion: a user can create and modify a small architectural model using
the main IngeTrazo workflow entirely in the browser.

### Phase 4 — architectural workflows

- Layers/tags, saved scenes, styles, sections, sun/shadows, and measurements.
- BIM/IFC classification and quantity workflows.
- Georeferencing, maps, terrain, survey points, traced paths, reference images,
  and photogrammetry references.
- Sheet composer and print/PDF output using a server-side rendering path where
  browser output cannot guarantee drafting fidelity.

Exit criterion: the web version supports an end-to-end architectural project,
including documentation and exchange.

### Hardening batch (2026-10-04)

- **Headless boundary, enforced.** `tests/test_web_headless_boundary.py` fails if any
  file under `web/backend` names `views`, `QtWidgets`, `QApplication`, `QWidget` or
  `QMainWindow`, and a bare-process test serves a preview, a sheet PNG and PDF, an edit
  and 3D text, then checks that `views` and `QtWidgets` were never loaded and no
  `QApplication` exists. Enforcing it exposed that the sheet PDF imported the desktop's
  composer module; the widget-free painting routines now live in `core/sheet_paint.py`
  and `views/composer.py` re-exports them (two desktop tests that patched
  `views.composer._draw_text_mm` now patch the new home).
- **Jobs run in processes.** `job_manager.py` spawns one child process per job (never a
  fork of the threaded server), at most `INGETRAZO_WEB_JOB_WORKERS` at once; the rest
  stay `queued` and are cancellable. A cancel, a timeout (`INGETRAZO_WEB_JOB_TIMEOUT`,
  default 900 s) or an out-of-memory kill ends only that child, and the job reports why
  (`killed by signal SIGKILL`, `longer than N seconds`). Tasks are named
  `module:function` entries in `job_tasks.TASKS` with JSON arguments, so nothing but
  plain data crosses the boundary; on Linux the child is also capped by
  `INGETRAZO_WEB_JOB_MEMORY_MIB` (default 4096). The HTTP routes that expose them
  (`POST /jobs/import`, `POST /documents/{id}/revisions/{n}/exports`, `GET /jobs`,
  `/jobs/{id}`, `/jobs/{id}/artifact`, `/jobs/{id}/diagnostics`, `POST /jobs/{id}/cancel`)
  did not exist: the manager and the interchange adapters were built but never wired.
- **One error shape, typed payloads.** Every error is
  `{"detail": {"code", "message", "fields"?}}` (`errors.py`); the browser reads it in one
  place (`api.ts`). The document, object, geo-reference, layer, scene, loose-geometry,
  Parts, library-placement and sheet commands now take pydantic models
  (`schemas.py`): strict types, ranges and cross-field rules declared once, unknown
  fields refused, and messages that name the field and the limit
  (`size.1 must be greater than 0`). Every command endpoint is typed now, including
  the polymorphic ones (shapes, planar primitives and sheet operations are
  discriminated unions) and the category edits. The browser's own forms were driven
  end to end against the typed API (about 35 submissions, every one accepted or refused
  for a domain reason, none for a payload mismatch).
- **Import and export in the browser.** File > Import model and File > Export revision
  drive the job routes with a progress dialog and Cancel; an import opens the new document.
- **Nested groups explode.** `explode-object` accepts nested ids: the parent is opened for
  editing as on the desktop, the group's geometry merges into the parent's mesh and the
  groups inside it become the parent's children; a moved parent keeps everything in place.

- **Accounts and ownership** (`auth.py`). Off until a user exists. Users have one random
  access token (stored salted-hashed in `users.json`, mode 0600); the browser trades it
  for an HMAC-signed `HttpOnly`, `SameSite=Strict` session cookie, scripts use a Bearer
  header. Every `/api` route needs a credential except health and the sign-in routes;
  documents and jobs carry an `owner`, others get `404` (existence is not revealed),
  administrators see all, documents from before accounts are administrators' only, and the
  shared category tree is administrator-only. Cross-site unsafe requests (a foreign
  `Origin`) are refused, failed sign-ins are throttled per address, and removing a user ends
  their session at once. `python -m web.backend users ...` manages accounts; with accounts
  on the service may bind beyond loopback. Not done: passwords, e-mail, single sign-on,
  per-user quotas, audit log, revocation of one session without removing the user.
- **Extension isolation.** Extensions run in a child process (`INGETRAZO_WEB_EXTENSION_TIMEOUT`,
  default 60 s) like jobs: a hang is stopped, a crash or kill costs one request.

- **MCP server** (`web/mcp/`). The web counterpart of the desktop's AI bridge: a
  dependency-free stdio MCP server that turns the API into agent tools. Command tools are
  generated from the OpenAPI schema (union bodies flattened), so they track the typed
  models; each call is one revision on the document's latest revision (a conflict is
  retried once), and every answer names the objects it created or removed. Helpers:
  `create_document` (`POST /documents/blank`), `get_model`, `list_revisions`, `export_model`,
  and `look`, backed by `GET /revisions/{n}/render.png` (a hidden-line drawing from a
  standard view or scene, nothing stored). Accounts apply: the agent holds a user token.
  Not done: a shaded render, a chat panel inside the browser, a prompt/recipe layer.

- **Real undo and redo, and retention** (`revision_history.py`). The web Undo used to restore
  revision N-1, so pressing it twice went back to where it started. Undo and Redo are now
  revisions that record the step they took (`history: {move, to}`); the server rebuilds the
  position by replaying them and returns `undo: {undo_to, redo_to}` with every document, so
  the browser, the MCP server and other browsers agree and it survives reloads; the step
  must lead where the history says. `INGETRAZO_WEB_KEEP_REVISIONS` (and
  `python -m web.backend prune`) deletes old revisions, never the first, the newest N, the
  reachable undo/redo states or the targets of kept undo revisions. Auto-save in Preferences
  covers the one thing that was not saved at once: layer and object visibility changes. Not
  done: pinning chosen revisions, per-user retention, restoring a pruned revision.

#### The edit cycle on large models

Every edit loads the base revision, mutates, saves the next `.igz`, reloads it for the
summary, and the browser then fetches a new preview. Measured with
`python -m web.backend.benchmark_commands` (synthetic boxes, 6 faces each; this machine):

| Faces | `.igz` | load | save | edit (before) | edit incl. preview (after) |
|---|---|---|---|---|---|
| 600 | 0.5 MiB | 0.06 s | 0.01 s | 0.06 s + 0.05 s preview | — |
| 6,000 | 5 MiB | 0.13 s | 0.04 s | 0.4 s + 0.5 s | — |
| 30,000 | 26 MiB | 0.6 s | 0.4 s | 2.4 s + 2.65 s = 5.1 s | 4.3 s |
| 60,000 | 51 MiB | 1.4 s | 0.9 s | — | 8.5 s |

Findings: an edit feels immediate up to about 6,000 faces and takes seconds beyond
about 30,000; the 100 MiB upload limit is reached near 120,000 faces of this kind. Time
splits roughly 45 % GLB generation (mostly triangulation), 35 % loading (twice), 10 %
saving. Two changes were made: the saved file is loaded once and that scene serves the
summary and the preview (the preview the browser fetches next is already built), and
`triangulate` skips the plane projection for triangles and reuses the face normal.
Two ideas were measured and **rejected**: summarising the edited scene instead of
reloading it (the edited scene keeps orphaned vertices, so the counts differ in 5 of
the test commands) and caching scenes per revision (it could save at most the load,
about a fifth, and any shared mutable scene is a source of subtle bugs). Decision: keep
the immutable whole-file revision model. If larger models matter, the next lever is an
incremental preview (rebuild only the nodes of objects an edit touched, since objects
already are separate glTF nodes), not a scene cache.

### Phase 5 — interoperability

- Prioritize GLB/glTF, OBJ, STL, DAE, DXF, and IFC according to user evidence.
- Isolate SKP import/export behind workers because of native dependencies and
  licensing/deployment constraints.
- Provide job progress, cancellation, diagnostic downloads, and predictable
  failure messages.

Exit criterion: supported import/export paths match desktop round-trip tests.

### Phase 6 — hardening and deployment

- Performance budgets and representative large-model benchmarks.
- Sandboxed workers, upload scanning, resource limits, rate limits, and
  structured telemetry.
- Accessibility, keyboard workflows, localization, browser compatibility, and
  offline/reconnect behavior.
- Containerized development and production deployments with database, object
  storage, queues, backups, and observability.

## Initial HTTP contract

All endpoints are under `/api/v1`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Process readiness and core availability |
| `GET` | `/capabilities` | Implemented and planned feature contract |
| `POST` | `/documents/inspect` | Load an `.igz` and return a JSON-safe summary |
| `POST` | `/documents/preview` | Load an `.igz` and return a self-contained GLB |
| `GET` | `/documents` | List stored native documents and immutable revisions |
| `POST` | `/documents` | Store a native document as revision 1 |
| `POST` | `/documents/{id}/revisions` | Add an immutable native revision |
| `GET` | `/documents/{id}/revisions/{n}/download` | Download the unchanged native revision |
| `GET` | `/documents/{id}/revisions/{n}/preview` | Generate or reuse its versioned semantic GLB |
| `POST` | `/documents/{id}/commands/presentation` | Atomically persist layer and top-level object visibility with conflict detection |
| `POST` | `/documents/{id}/commands/layer-visibility` | Backward-compatible layer-only command adapter |
| `POST` | `/documents/{id}/commands/move-object` | Move a top-level object and write an immutable native revision |
| `POST` | `/documents/{id}/commands/transform-object` | Rotate or scale a top-level object about its centre |
| `POST` | `/documents/{id}/commands/object-lifecycle` | Duplicate, rename, or delete a top-level object |
| `POST` | `/documents/{id}/commands/create-box` | Create a named solid box with numeric size and origin |
| `POST` | `/documents/{id}/commands/create-planar` | Create a numeric line, rectangle, segmented circle, or arc |
| `POST` | `/documents/{id}/commands/push-pull` | Push/pull a planar object face through the native guarded solid pipeline |
| `POST` | `/documents/{id}/commands/offset-face` | Offset a one-face planar object inward or outward |
| `POST` | `/documents/{id}/commands/object-material` | Apply or clear object colour and opacity |
| `POST` | `/documents/{id}/commands/create-annotation` | Create native dimensions, leader text, and construction guides |
| `POST` | `/documents/{id}/commands/object-ifc` | Classify or unclassify a top-level BIM object |
| `POST` | `/documents/{id}/commands/set-georef` | Set the native WGS84 datum and true-north rotation |
| `POST` | `/documents/{id}/commands/import-survey` | Import P,N,E,Z survey rows into native control points |
| `POST` | `/documents/{id}/commands/create-geopath` | Create a native local path or terrain surface boundary |
| `POST` | `/documents/{id}/commands/set-map` | Configure or remove a licensed native XYZ base-map capture |
| `POST` | `/documents/{id}/commands/import-terrain` | Import a bounded surveyed XYZ grid as a native reference terrain mesh |
| `POST` | `/documents/{id}/commands/set-style` | Apply a native built-in display style |
| `POST` | `/documents/{id}/commands/set-shadows` | Save a georeferenced solar-shadow study |
| `GET` | `/documents/{id}/revisions/{n}/quantities.csv` | Export revision-pinned BIM takeoff quantities |
| `GET` | `/documents/{id}/revisions/{n}/model.ifc` | Export revision-pinned IFC4 exchange data |
| `POST` | `/documents/{id}/commands/create-sheet` | Create a native exact-scale sheet composition |
| `GET` | `/documents/{id}/revisions/{n}/sheets/{i}.pdf` | Render one native sheet as an exact-size vector PDF |
| `POST` | `/documents/{id}/commands/create-shape` | Polygon, rotated rectangle, two/three-point arc, pie, or freehand curve |
| `POST` | `/documents/{id}/commands/flip-object` | Mirror an object (or a copy) across its centre along a world axis |
| `POST` | `/documents/{id}/commands/follow-me` | Sweep a one-face profile along a path |
| `POST` | `/documents/{id}/commands/fillet` | Round chosen or all sharp edges of an object |
| `POST` | `/documents/{id}/commands/solid-operation` | Outer shell, union, subtract, trim, intersect, or split two solids |
| `POST` | `/documents/{id}/commands/create-text3d` | Insert extruded 3D text |
| `POST` | `/documents/{id}/commands/section-fill` | Persist section-cut fill |
| `POST` | `/documents/{id}/commands/loose-push-pull` | Push/pull a face of ungrouped geometry |
| `POST` | `/documents/{id}/commands/loose-erase` | Erase ungrouped faces |
| `POST` | `/documents/{id}/commands/loose-paint` | Paint ungrouped faces with a colour or library texture |
| `POST` | `/documents/{id}/commands/loose-group` | Make a group or component from ungrouped faces |
| `GET` | `/documents/{id}/revisions/{n}/loose-connected` | Faces connected to a loose face |
| `POST` | `/documents/{id}/commands/restore-revision` | Restore historical native state as a new revision |

The presentation command is the first authoritative edit endpoint. Later
modeling commands should follow the same required `base_revision` convention:
apply to native state, validate, and create a new immutable revision.

## First implementation milestone

The first code milestone is deliberately read-only. It includes:

- a framework-neutral service that loads `.igz`, summarizes a `Scene`, and
  exports GLB;
- a thin FastAPI adapter with bounded uploads and structured errors;
- a minimal browser page that uploads a document and displays its GLB preview;
- tests against a synthetic scene and an upstream example document.

This validates the hardest early assumption: that the existing document and
geometry code can run behind a web boundary without launching the Qt desktop
interface.

## Delivery estimate

- Read-only technical prototype: 2–4 weeks.
- Useful viewer and safe document persistence: 6–10 additional weeks.
- Core modeling MVP: approximately 4–6 months total with a small experienced
  team.
- Broad architectural feature parity: approximately 9–15 months, depending on
  SKP, geospatial, composer, and performance requirements.

These ranges should be replaced with measured estimates after Phase 0 records
load/export timings and exposes any Qt coupling in representative projects.

## Main risks

- Core modules may import Qt UI code indirectly even when their public API is
  headless.
- GLB does not carry every IngeTrazo semantic, so it is a preview transport,
  never the editable source of truth.
- Large texture bundles and nested components can exceed ordinary request and
  browser-memory limits.
- Modeling tools depend on low-latency inference; round trips must commit
  geometry, not drive every pointer movement.
- SKP support and server deployment need a separate legal and technical review.
- Composer output must be verified visually; browser canvas output alone is
  unlikely to guarantee print fidelity.

## Success measures

- Desktop/web `.igz` round trips preserve all declared supported entities.
- Headless service tests never construct a window or OpenGL context.
- Viewer opens agreed reference projects within explicit time and memory
  budgets.
- Commands are deterministic and undoable, with revision conflicts detected.
- Unsupported features are reported explicitly rather than silently discarded.

## Implementation status — 2026-10-04

Feature work has run ahead of the foundation: Phase 4's exit workflow exists,
while Phase 2 (persistence) and Phase 3 (command model) are only partly done.
Closing those gaps comes before broadening Phase 5.

| Phase | Status | Remaining |
|---|---|---|
| 0 Baseline and contracts | Done | — (`tests/test_web_headless_boundary.py` enforces decision 4). |
| 1 Viewer MVP | Done | Server-side streaming progress for large documents (cancellation is browser-side only). |
| 2 Persistence | Partly done | Autosave, richer conflict resolution, authentication, ownership, quotas, database/object storage. |
| 3 Core modeling | Mostly done | Nested component edit contexts, gizmo manipulation, and a true command model: every edit still reloads and rewrites the whole `.igz`. |
| 3b Desktop-parity UI | In progress: all 56 toolbar buttons work; 18 draw/modify tools are on-canvas with snapping, live previews and typed values | sheet items the composer cannot draw (terrain profiles) and the desktop's Qt plugins, which a browser cannot host (web extensions replace them). |
| 4 Architectural workflows | Done at its exit level | Visual section caps, automatic online DEM acquisition (parity work, not blockers). |
| 5 Interoperability | Partly done | SKP is disabled; desktop round-trip parity tests; the browser has no import/export UI for the job routes yet. |
| 6 Hardening and deployment | Not started | Rate limits, sandboxed workers, upload scanning, accessibility, deployment. |

### Phase 0 — baseline and contracts

- Headless native `.igz` loading, scene summaries, and GLB generation, with no
  Qt window.
- Versioned health, capabilities, inspection, and ephemeral preview endpoints.
- Bounded uploads plus JSON/ZIP checks: structure, expansion, compression
  ratio, duplicate members, encryption, and path traversal.
- Unit, HTTP contract, production-build, and real upstream-example tests.

### Phase 1 — web viewer

- Pinned, self-contained Three.js/TypeScript viewer: Z-up navigation, fit
  extents, standard views, projection switching, grid, edges, axes.
- Saved-camera and named-scene restoration; native layer state; bounded
  group/component hierarchy; semantic GLB nodes linking canvas and tree
  selection.
- Triangle picking with material, coordinate, and primitive inspection;
  two-point measurement in document units; embedded reference images.
- Native section-plane display and interactive clipping.
- Browser-side cancellation and stale-result suppression; human-readable
  validation errors; API timing headers; CI performance budgets.

### Phase 2 — persistence (partly done)

- Immutable filesystem revisions, unchanged native downloads, cached versioned
  GLB previews, automatic metadata migration, and a recent-document library.
- Optimistic concurrency: every command carries `base_revision` and a stale
  tab receives a 409.
- Revision restore as a new revision, and browser Undo/Redo built on it.
- Legacy documents without stored object uids get deterministic ids at load
  time (`load_into(..., stable_ids=True)`), so ids survive summary regeneration.
- The service binds to loopback only (`python -m web.backend`) until
  authentication exists.

### Phase 3 — core modeling (mostly done)

- Top-level group/component commands: move, rotate, scale, duplicate, rename,
  delete, with an in-app clipboard backed by native duplication.
- Numeric creation of boxes, lines, rectangles, segmented circles, and
  curve-tagged arcs on the XY/XZ/YZ planes; two-click snapped line sketching.
- Push/pull and offset through the desktop engine's stitching, plane rebuild,
  and watertight-solid guard.
- Object colour/opacity, dimensions, leader text, and construction guides as
  first-class `.igz` entities.
- All commands share one helper (`_commit_revision`) for load, mutate, save,
  and error mapping.

### Phase 3b — desktop-parity UI (started)

Decision (2026-10-04): the web client aims at full parity with the desktop
interface, not a lighter inspector-style viewer. The desktop is the source of
truth for the chrome, so the web reads it instead of copying it by hand.

Built so far:

- `scripts/export_web_ui.py` renders every programmatic desktop icon
  (`views/icons.py`, 196 of them) to PNG for a dark and a light theme and
  writes `web/frontend/src/ui/manifest.json`: the toolbar layout (read from the
  source of `MainWindow._build_toolbar`), plus each tool's name, shortcuts and
  description. `tests/test_web_ui_manifest.py` fails if the desktop layout, a
  tool's shortcut, or an icon changes without re-running the script.
- `web/frontend/src/chrome.ts` builds the menu bar (File, Edit, Camera, Draw,
  Tools, Window, Help), the nine desktop toolbars with their icons and
  separators, the status bar with a tool hint and a Measurements box, the
  desktop's keyboard shortcuts, and a shortcut reference dialog.
- Navigation tools (Orbit, Pan, Zoom), Zoom Extents, and all seven standard
  views (Isometric, Top, Front, Right, Left, Back, Bottom) act on the viewport.
- Bound to existing commands (numeric entry in the side panel, which the tool
  brings forward when you pick an object): Line and Tape Measure (two-click,
  on canvas); Rectangle, Circle, Arc, Dimension, Text, Trace; Push/Pull, Offset,
  Move, Rotate, Scale, Paint; Eraser (deletes the selection); Section Plane.

Milestone 1 (every toolbar button bound, 2026-10-04):

- New server commands in `web/backend/ingetrazo_web/modeling.py`, each wrapping
  the routine the desktop tool uses: `create-shape` (polygon, rotated
  rectangle, two- and three-point arcs, pie, freehand), `flip-object`,
  `follow-me`, `fillet`, `solid-operation` (outer shell, union, subtract,
  trim, intersect, split), `create-text3d`, and `section-fill`. Shared
  validation and persistence live in `commands.py`.
- A declarative form system (`src/toolforms.ts`) renders each of these tools'
  options in a Tool panel at the top of the sidebar, in document units.
- Protractor creates an angled construction guide, Eyedropper copies the
  picked object's colour into the Paint form, and the Section Planes / Cuts
  toggles drive the existing section controls.
- Zoom Window, Zoom Selection, Position Camera, Walk, Look Around, and First
  Person (W A S D, Shift runs) are client-side viewer modes.
- The service now creates a headless `QGuiApplication` on start. Without one,
  3D text (fonts) aborted the whole server process.

Milestone 2 (on-canvas tools, 2026-10-04):

- `src/gestures.ts`: click-move-click tools with snapping (endpoint, midpoint,
  on-edge, on-face, on-plane, on-axis), a thick rubber-band preview, and a
  typed value in the Measurements box: Line, Rectangle, Circle, Polygon
  (`8s` sets the sides), Rotated Rectangle, two- and three-point Arc, Center
  Arc, Pie, Freehand (drag), Dimension, Text, Move, Rotate, Scale, Push/Pull
  (drag along the face normal), Eraser, Paint, Section Plane, and component
  placement. Esc drops the stage in progress, a second Esc leaves the tool.
  Every tool posts one modeling command, so each result is a revision.
- The camera is kept when a command produces a new revision of the open
  document, so drawing is not interrupted.
- Right-click context menu (Move, Rotate, Scale, Flip, Paint, Rename,
  Duplicate, Copy, Hide, Edit inside, Zoom, Delete); desktop keyboard
  shortcuts for Undo, Redo, Copy, Paste, Duplicate, Delete, Save, Open.
- The side panel is the desktop's stack of collapsible sections (Entity info,
  Layers, Scenes, Section planes, Materials, Components, Objects, BIM, Styles,
  Location, Sheets, Recent documents); each header folds and unfolds its section
  and the state is remembered. Picking an object unfolds Entity info.
- Materials section: the texture library (pick a swatch, then Paint).
  Components section: 2DWM's category tree, ported (`taxonomy.py`, with its
  tests): user-owned categories nested up to three levels, hide / show all,
  a component listed in several categories, defaults that never reappear once
  deleted, "Uncategorized" as the safety net, search, drag a component onto a
  category to move it (Alt/Ctrl to also list it there), right-click menus, and
  "In model". The tree is stored in `taxonomy.json` beside the documents and
  edited through `/api/v1/library/taxonomy`. `library.py` serves only files
  that ship in `resources/`. The six 2D scale figures (Sumari, Engineer, Richard, Linus,
  Elon, Stephen) are listed too, filed under People and placed as face-me
  figures at their real height (`insert-person`; thumbnails are scaled down
  server-side). Not yet: "More components" (online library) and "Face-me
  image".
- Layers (create, assign), saved scenes (add, delete) and section planes
  (click a face) are server commands; scenes store the browser's camera in the
  desktop's own yaw/pitch/distance terms.
- Light and dark themes (Window > Preferences), toolbar icon size, and a
  `?debug` hook that exposes the viewer for browser automation.

Milestone 3 (nested objects):

- Move, Rename, Delete, Material and IFC accept nested ids (`group:0/1/2`).
  A nested move converts the world offset into the parent's frame, so it is
  correct inside a rotated parent. Double-click enters a group (Esc or a
  double-click on empty space leaves); picks then resolve to its children.

Bugs found while building this (all covered by tests):

- 3D text aborted the whole server process without a Qt application object
  (now a headless `QGuiApplication` at start-up, with a bare-process test).
- A tray MutationObserver rewrote the attribute it watched and froze the page.

Milestone 4 (selection and loose geometry, 2026-10-04):

- Multi-select: click selects, Shift or Ctrl/Cmd-click adds or removes, Ctrl+A
  selects every top-level object. Move, Eraser, Paint and Delete act on the
  whole selection in one revision (`object_ids` on move-object, delete and
  object-material).
- Loose (ungrouped) geometry is editable. The preview tags each triangle with
  its face's index in the scene's loose mesh (`ingetrazo_faces` on the glTF
  primitive), so a click names a face. New commands: `loose-push-pull`,
  `loose-erase`, `loose-paint`, `loose-group` (make a group or component,
  optionally with everything connected) and a read-only `loose-connected`
  (the triple click). The right-click menu on a loose face offers them.
- Marquee selection with the Select tool: drag left to right to take what is
  fully inside the box, right to left for anything it touches, Shift to add.
  Objects are judged by their projected bounding boxes and loose faces by
  their projected extent; inside an edit context only that group's children
  count. In this mode the middle button orbits and the right button pans;
  Window > Preferences can make left-drag orbit instead.
- Toolbars follow the desktop's factory layout (`resources/ui/default_layout.state`,
  decoded by `scripts/export_web_ui.py` into the manifest): Main, Modify, View,
  Sections, Standard Views and Solid Tools along the top; Draw, Annotate and
  Walkthrough in a column at the left. Each bar has the desktop's dotted grip and
  a visible frame; separators are drawn inside a bar where the desktop has them.
- Face-me figures (scale people, cut-out sculptures) are drawn. The preview
  carries each figure as its own node with its feet, size and kind; the browser
  rebuilds a lone textured quad as an upright plane and rotates any other
  figure whole, about the vertical through its feet, to face the camera every
  frame (a parallel view uses its single view direction). Their transparent
  corners are cut out and they are not outlined.
- Nested objects are editable (milestone 5). The preview now exports one node per
  nested object, named by its path (`group:2/0/1`), so a click inside an edit
  context picks that child; a container with no geometry of its own is the union
  of its children. State flows down the hierarchy as in the desktop: a hidden
  ancestor hides everything inside it, a layer or paint inherited unless the child
  has its own. Rotate, Scale and Push/Pull accept nested ids: world axes, points
  and distances are carried into the parent's frame (`ParentFrame`), correct for
  rotated, uniformly scaled and mirrored parents; a parent stretched unevenly is
  refused with a message. Make Group / Make Component (Ctrl+G, Edit menu, context
  menu) work over objects, loose faces, or both, and Explode dissolves one level of
  the selected top-level groups.
- Depth precision: the camera's near and far planes follow the model's depth
  every frame and the renderer uses a logarithmic depth buffer. With a range of
  millions of metres, surfaces centimetres apart (concrete and the rebar inside
  it) ghosted through each other in orthographic scenes.
- The world axes are drawn on top of the model in the desktop's colours (X red,
  Y green, Z blue up), with the negative halves dashed; the old hairline sat
  inside most models and was hidden.
- Annotation text is drawn at a constant size on screen, multi-line, and laid
  out so labels do not overlap; each keeps its leader line. (Labels were one
  line each and scaled with the model, so they piled up on large models.)

Milestone 6 (the remaining desktop-parity list, 2026-10-04):

- Layers: rename, delete (contents move to the default layer) and lock. A locked
  layer's objects and loose faces are visible but cannot be picked or edited; the
  lock is inherited by nested objects and enforced by the server, not only the
  browser (`find_object`, loose `face_list`).
- Loose geometry: loose faces move (`loose-move`, vertices are shared so what
  touches a moved corner follows, as on the desktop); free loose edges are exported
  in the preview, picked by screen distance, moved and erased (`loose-edge-erase`).
- Entering a group or component edits its own faces: the preview tags every face of
  an object with its place in the object's mesh, and the `loose-*` commands take an
  optional `object_id` that opens the group with `Scene.begin_group_edit`, as the
  desktop does (a component's shared definition is edited as a world copy and shared
  back to every instance). Leaf groups can now be entered.
- Components list: "More components…" browses the online library through
  `core.library` (index, thumbnails, model zips cached on the server; an offline or
  unreachable library reports itself instead of failing) and places a model at its
  catalogue size; "Face-me image…" uploads a PNG/WebP and stands it as a face-me
  figure of a chosen height.
- Parts section: the selected component's parts measured like a cut list
  (`core.parts`), show/hide, rename, select, Split into Pieces, the exploded view
  and a copyable cut list.
- Customisation: keyboard shortcuts are editable (Help > Keyboard shortcuts), kept
  per browser and exportable/importable as JSON; the interface is localised from the
  desktop's `i18n/<code>.json` (served by the API; text with no translation stays
  English); toolbars are dragged by their grips to dock top or left, or float, and
  remember their place (double-click a grip to put one back).
- Sheet composer: a full-screen paper editor. The page is a PNG drawn with the
  desktop composer's own `paint_*_mm` routines (the same ones the PDF now uses, so
  the PDF also gained text, images, scale bars, north arrows, legends, shapes,
  dimensions, labels and the title block); every item is a box to move and resize, with a
  property panel generated from the item's dataclass fields. One `sheet-edit`
  command (add, set, remove, order, duplicate, page settings) validates each change
  against the field's type and the page, and each is a revision.
- Extensions: scripts in the server's extensions folder
  (`$INGETRAZO_WEB_EXTENSIONS`, or `extensions` beside the data) appear in an
  Extensions menu with a form made from their declared parameters, run as one
  revision, and leave the document untouched if they raise. They are installed by
  the operator only (never uploaded through the API) and run with the server's
  rights. The desktop's Qt plugins (`plugins/`, `setup(app)`) cannot run in a
  browser and are not supported.

Known gaps: terrain
profiles on sheets are not drawn (they need the desktop's survey sampling); loose
edges that bound a face are edited through the face; one language catalogue is
matched by exact English text, so strings the web client builds with numbers in them
stay English; extensions and the toolbar layout are per server / per browser.

### Phase 4 — architectural workflows (done at its exit level)

- Layers, saved scenes, sections, display styles, and georeferenced solar
  shadows.
- BIM/IFC classification with live class-specific takeoff, plus
  revision-pinned CSV and IFC4 downloads.
- WGS84 datum, P,N,E,Z survey import, traced paths and boundaries; licensed
  Esri, OpenStreetMap, and Sentinel-2 base maps; surveyed XYZ terrain grids;
  photogrammetry metadata reported without flattening its source.
- Native A4–A0 sheets at exact scale with server-rendered vector PDFs from the
  hidden-line engine.

The exit workflow holds end to end: model and annotate, organize presentation
state, classify and quantify BIM objects, locate the project, combine
maps/survey/terrain references, create a sheet, and export native `.igz`,
IFC, CSV, and PDF.

### Phase 5 — interoperability (partly done)

- Import/export through `interchange.py`, with persistent job records,
  progress, cancellation, and diagnostics downloads. Jobs run on a bounded
  thread pool (`INGETRAZO_WEB_JOB_WORKERS`, default 2).
- SKP is isolated behind a subprocess and disabled until a licensed
  server-side backend is configured.

### Phase 6 — hardening and deployment

Not started beyond the localhost default and the bounded job pool.

## Next steps

1. Phase 3b is functionally complete; what remains is polish found by use (see the known gaps in milestone 6).
2. If models beyond ~30,000 faces matter: an incremental preview (see the edit-cycle findings).
3. Per-user quotas (documents, revisions, storage, concurrent jobs) and revision pruning, now that ownership exists; TLS deployment notes.

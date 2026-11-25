# Pruning the web repository: removing the desktop-only and Qt-UI code

> **2026-11-25, open-source release:** the SKP writer (`formats/skp_out.py`), its tests,
> `PRIVATE_FILES.txt` and `scripts/make_open_tree.py` were removed from the repository. The
> "private edition" notes below describe the state before that.

Status: phases A, B and C are done (2026-10-05); D, E (the remaining part) and F are not. See
"Progress" at the end.

## 1. Premise and decisions to confirm

- This work happens in the **web repository** (`felixriestra/ingetrazo-web`). The desktop
  application stays whole in its own repository (`ingelibre/ingetrazo`), which is also the
  specification and test oracle for the planned Swift/iPad rewrite. Nothing here removes it
  from the world; it removes it from the web repo.
- **Qt itself stays.** The engine uses Qt's non-UI classes everywhere: `QVector3D`
  (109 imports) and `QMatrix4x4` (48) for geometry, `QImage`, `QPainter`, `QFont`,
  `QPainterPath` and `QPdfWriter` for textures, sheets, PDF and 3D text, and a headless
  `QGuiApplication`. The goal is to drop the **UI** (QtWidgets, windows, tools, plugins),
  not Qt. Replacing Qt in the engine is a separate, much larger project (section 8).
- Keep **file paths and names of every kept module unchanged** (no moves, no renames), so a
  fix made upstream in a kept file can still be applied here as a patch.

Decisions needed from you before starting (recommendations in brackets):
1. SKP: **decided**: import is wired in and enabled; export is kept in the private edition only (see
   `web/README.md`, "Editions"). Original question: drop only the export and keep import? [yes: the
   reader is OpenSKP, MIT, pure Python, offline, with no proprietary code (the proprietary SDK
   path was removed upstream on 2026-09-28), so the web plan's "needs a licensed backend" is
   out of date. The web service never wired it up, which is why it looks unused. Wire import
   into the job process and enable it after testing with real `.skp` files; remove `skp_out`
   (the legacy writer, which the desktop itself has switched off).]
2. Which `georef` modules to keep? The web uses survey rows, tiles, photomesh and terrain
   grids. [keep those; remove `geotiff`, `geoimport`, `surface`, `geocode` unless DEM
   download is planned]
3. Keep the ~150 engine tests that don't touch the UI? [yes: they are a large regression
   suite for the engine we keep]
4. Install `PySide6-Essentials` instead of the full `PySide6` wheel? [yes, if the web tests
   pass with it; it drops the Addons modules and saves hundreds of MB in the image]
5. Freeze the toolbar manifest and icons as checked-in assets (section 3, phase B)? [yes]

## 2. What the measurements say

Python in the repository, excluding tests (lines): `core` 29,600, `formats` 9,200,
`tools` 13,900, `georef` 3,500, `views` 40,400, `plugins` 3,600, `scripts` 2,600,
`main.py` 600: about 103,000, plus `web/` 6,800 Python and 8,600 TypeScript.

A static import analysis of everything the server can reach (including imports inside
functions) gives:

| Package | Total | Reachable | Not reachable |
|---|---|---|---|
| `core` | 29,600 | 26,600 | 3,100 |
| `formats` | 9,200 | 5,400 | 3,800 |
| `tools` | 13,900 | 2,800 | 11,000 |
| `georef` | 3,500 | 2,200 | 1,300 |
| `views` | 40,400 | 500 | 39,800 |
| `plugins`, `scripts`, `main.py` | 6,700 | 0 | 6,700 |

So about **64,000 of 103,000 lines (about 60%) are unreachable**. Not reachable by import
is a safe first cut. It cannot find dead code inside reachable modules, and it cannot see
dynamic imports.

The web test suite executes only about 34% of the statements in the engine modules it
imports (`core` 41%, `formats` 25%, `tools` 20%, `georef` 24%). That is a floor, not the
answer: many paths are used in production but not covered (formats run in child processes,
for example). Coverage is therefore used only to **nominate** candidates inside kept
modules, never to approve a deletion.

Tests: of 414 files, 246 import the UI (`views`, `QtWidgets`, `QApplication`); about 152
exercise the engine alone.

Not reachable and not UI, candidates for phase C: `core/` `ai`, `render_blender`,
`string_search`, `intersect`, `gl_fallback`, `ndof`, `extensions`, `platform_choice`,
`appimage`, `tls`, `ai_recipes`, `autosave`, `glinfo`, `orient_faces`, `gpu_prefs`;
`formats/` `skp_out`, `skp_openskp`, `skp`, `dwg_bridge`, `clip`, `openskp_compat` (the SKP reader is not reachable only because the web service never wired it up);
`georef/` `geotiff`, `geoimport`, `terrain`, `surface`, `geocode`; and 28 interactive
modules in `tools/` (everything except `pushpull` and `offset`).

## 3. The plan, in phases

Each phase ends with the acceptance checks in section 4 and is its own commit series, so
any phase can be reverted alone.

### Phase A: safety net first (no deletions)

1. Tag the current commit `pre-prune` and note the upstream commit this repository was
   forked from in `UPSTREAM.md`, with the procedure for applying an upstream patch.
2. Fix the three places where kept code reaches into the UI by a function-level import,
   which the current boundary test cannot see:
   - `core/sheet_paint.py` imports `views.profile_panel._nice_ticks` (twice);
   - `tools/select.py` imports `views.prompts`;
   - `tools/solid_tools.py` imports `views.icons`.
   Move or inline the few lines each needs.
3. Make the boundary test stricter: no `views`, `QtWidgets`, `QtOpenGLWidgets` or
   `QApplication` anywhere in the kept packages, imports inside functions included.
4. Add a **reachability test**: compute the import graph from `web/backend` (static, with
   function-level imports) and fail if it reaches a module not listed in a checked-in
   manifest `web/KEEP.txt`. After pruning, a second check fails if the repository contains
   Python modules no entry point reaches. This is what keeps the repository clean later.
5. Run the full deploy check (section 4) on the Debian container once, to have a baseline.

### Phase B: remove the desktop shell (about 47,000 lines)

Remove `views/` (everything except what phase A moved out), `plugins/`, `main.py`,
`ingetrazo.spec`, `packaging/`, `installer/`, `vendor/libredwg` (14 MB), the desktop
scripts (`install_desktop.sh`, `release_check.sh`, `gen_app_icon.py`, `gen_doc_icons.py`,
`bench_startup.py`, `bench_session.py`, `bench_nested.py`, `probe_snap_matrix.py`,
`ingetrazo_mcp.py` (the desktop's AI bridge), `skp_diff.py`, `import_sh3t.py`), the desktop
`docs/` pages, and unused `resources/` (`ui`, `mime`, `shaders`, `blender`, desktop icons
and styles). Check each `resources/` subfolder against `web/backend` and the engine before
removing: `components`, `textures`, `fonts` and the `i18n/` catalogues are used.

The one dependency on the removed code: `scripts/export_web_ui.py` regenerates the toolbar
manifest and icons from `views/main_window.py` and `views/icons.py`. After phase B those
two files are gone, so **freeze the generated assets**: `web/frontend/src/ui/manifest.json`
and the icons are already checked in and become the source of truth. Delete the script and
say in `web/README.md` that they were exported from upstream commit X.

### Phase C: remove unreachable engine modules (about 15,000 lines)

Delete, in this order, one commit each, running the tests after each:
1. the 28 interactive `tools/` modules (keep `pushpull`, `offset` and what they import);
2. `dwg_bridge` and `clip` (NOT `skp_out`: the SKP writer is kept for the private edition,
   listed in `PRIVATE_FILES.txt` and left out of the open tree by `scripts/make_open_tree.py`); keep `skp`, `skp_openskp`,
   `openskp_compat` and the `openskp` requirement when SKP import is kept (decision 1);
3. the unreachable `core/` modules listed above;
4. the `georef/` modules you decide to drop.

Before each deletion run `grep -rn` for the module name across kept code, `web/`, `tests/`
and the docs, because the import analysis cannot see `importlib` or names built from
strings.

### Phase D: prune inside the kept modules (candidates, then proof)

The largest kept modules carry many things only the desktop uses, for example the roughly
100 command classes in `core/history.py` of which the web uses a fraction, and
viewport-only state in `core/scene.py`.
1. Generate candidates with `vulture` and with the coverage report from the web suite.
2. A candidate is deleted only if it has no reference in kept code, `web/`, the MCP
   server or the tests we keep, and a reviewer has read it.
3. Stop at diminishing returns. Do not rewrite or reformat kept code in this phase: small
   diffs against upstream are worth more than a smaller file.

### Phase E: tests

- Delete the 246 UI test files and any test of a removed module.
- Keep the ~150 engine tests; run them in CI next to `tests/test_web_*.py`.
- Leave the kept tests at their current paths, so upstream test fixes still apply.

### Phase F: packaging and dependencies

- `requirements.txt`: PySide6 (or `PySide6-Essentials`), numpy, ezdxf, manifold3d, and the
  web stack; remove `openskp`, `pytest-qt` and anything only the UI used.
- A slim Dockerfile that installs only those and copies only the kept packages and the
  `resources/` used. Expect the image to drop by the vendored libraries, the 40,000-line
  UI and, with the Essentials wheel, the unused Qt modules.
- Update `README.md` and `web/README.md` so the repository describes itself as the web
  service, with the engine as a vendored dependency.

## 4. Acceptance checks for every phase

1. `tests/test_web_*.py` and the kept engine tests pass (currently 207 web tests).
2. The boundary and reachability tests pass.
3. The four example `.igz` documents load, preview, edit, export to every format and render
   a sheet PDF (an end-to-end script, kept as a test).
4. The Debian container deploy test: install from the trimmed requirements in a clean venv,
   run the test suite, start the server with accounts, and drive it from another machine.
5. The MCP server tests pass.
6. A before and after count of Python lines, test files and image size is added to this file.

## 5. Expected result

- Python in the repository: from about 103,000 lines to about **35,000 to 40,000** (the
  reachable engine, less what phase D removes) plus the web service.
- Tests: from 414 files to about 150 engine files plus the web tests.
- Working tree: smaller by `vendor` (14 MB), unused resources and the UI (git history is unchanged).
- Install and image size: smaller by the unused Qt modules if `PySide6-Essentials` works.
- Build and test time: lower, and no Qt Widgets dependency to break on a headless server.

## 6. Risks and how they are handled

| Risk | Handling |
|---|---|
| A dynamic import breaks at runtime | grep before each deletion, the example round-trip script, the container deploy check |
| Deleting something a web feature uses rarely (an export format, a command) | the end-to-end script touches every format and every command family; coverage nominates, humans decide |
| Upstream fixes stop applying | paths and names unchanged, `UPSTREAM.md` procedure, one small commit per removal |
| Losing the desktop reference for the iPad rewrite | it lives in the upstream repository and the `pre-prune` tag |
| Removing code a planned feature needs | the decisions in section 1 are made first; the Terrain-profile and DEM features are listed there |

## 7. Order and effort

Phase A: half a day. B: one day (mostly checking resources). C: one to two days. D: two to
three days of careful review, open-ended. E and F: one day. The reachability test from
phase A makes B and C mechanical; D is where judgement and time go, and it can be skipped
or stopped early.

## 8. Not part of this plan: replacing Qt in the engine

Dropping PySide6 from the server would need pure-Python or numpy replacements for
`QVector3D` and `QMatrix4x4` across about 100 files, a font and glyph-outline source for 3D
text (currently `QFont`), and a drawing and PDF layer for sheets (currently `QPainter` and
`QPdfWriter`). It would save the Qt install and the system libraries on the server, but it
touches almost every engine file and its tests. Revisit only if deployment size or the Qt
dependency becomes a real problem.


## 9. Progress: phases A, B and C done (2026-10-05)

**Phase A** (`97332d7`): tag `pre-prune`; `UPSTREAM.md`; the one UI import left in kept code
(`core/sheet_paint.py` importing `views.profile_panel._nice_ticks`) removed by moving the
function into core; `web/tools/reachability.py` (static import graph from the web service,
function-level imports included), `web/KEEP.txt`, `web/UNREACHABLE_ALLOWED.txt` and
`tests/test_web_reachability.py` (the service may reach only listed modules; kept engine code
never imports `views`, `plugins` or Qt widgets; unreachable code must be on the allowlist).
The tools/select and tools/solid_tools imports of `views` named in the plan disappeared with
those modules in phase C.

**Phase B** (`6aa1e34`): removed `views/`, `plugins/`, `main.py`, `ingetrazo.spec`, `packaging/`,
`installer/`, `vendor/`, `analysis/`, `benchmarks/`, `materials/`, `styles/`, the desktop
scripts and the unused `resources/` (`blender`, `colors`, `icons`, `mime`, `shaders`, `styles`,
`ui`), and 247 test files that exercised the UI. The toolbar manifest and icons are frozen as
this repository's own assets (`test_web_ui_manifest.py` now checks they are consistent).
`tests/conftest.py` creates a headless `QGuiApplication`, not a `QApplication`. The root
`README.md` describes the web edition.

**Phase C** (`ed82eef` and a follow-up): removed the 28 interactive `tools/` modules,
`core/` `ai`, `ai_recipes`, `appimage`, `autosave`, `extensions`, `gl_fallback`, `glinfo`,
`gpu_prefs`, `intersect`, `ndof`, `orient_faces`, `platform_choice`, `render_blender`,
`string_search`, `tls`, `formats/clip` and `dwg_bridge`, `georef/geocode` and `geoimport`, and
every test that needed them. **Kept on purpose:** `formats/skp_out.py` (private edition, see
`PRIVATE_FILES.txt`), the SKP reader, and the DEM family `georef/dem`, `geotiff`, `profile`,
`surface`, `terrain`, `tile_fetcher`, which the open items "terrain profiles on sheets" and
"automatic online DEM acquisition" need; they are the only entries left on
`web/UNREACHABLE_ALLOWED.txt`.

| | Before (`pre-prune`) | After |
|---|---|---|
| Engine Python (`core`, `formats`, `tools`, `georef`) | 56,200 lines | 41,400 lines |
| All desktop Python outside tests (incl. `views`, `plugins`, scripts) | 103,400 lines | 41,400 lines (+ 7,100 web service) |
| Test files | 414 (73,400 lines) | 114 (20,800 lines): about 98 engine files and 16 web files |
| Tracked files / size | 1,638 files, 75.9 MB | 1,176 files, 53.7 MB |
| Install in the container (venv, full PySide6 vs `PySide6-Essentials`) | 851 MB | 447 MB |


**Acceptance (all passed)**
- Engine tests, not slow: 907 passed, 2 skipped. Fuzz quick: 200 passed. Web tests: 223 passed,
  including the new end-to-end test that takes every example document through preview, edit,
  undo, export to six formats, a sheet PDF and a render. The 800 `slow` fuzz sweeps were not
  re-run.
- The same suite, installed from a clean venv in the Debian arm64 container with
  `PySide6-Essentials`: 1,328 passed, 3 skipped (one failure, the open-tree test, which needs
  a git checkout and now skips without one). So the smaller Qt wheel is enough.
- The server in the container, with accounts and SKP export switched on, driven from the Mac:
  upload, preview, edit, export to GLB, STL, DXF and SKP (IFC correctly refused: no BIM objects),
  re-import of the exported `.skp`, sheet PDF.
- The browser client against the trimmed server: 56 toolbar buttons, Preferences, the sheet
  composer, export dialog.

**Observations to follow up:** re-importing the exported `.skp` of the arch example gave 12,021
faces from 10,371 (the SKP round trip changes the face count; worth a look before relying on it),
and the full suite including the 800 slow fuzz sweeps was not run to completion.

**Not done yet:** phase D (pruning inside kept modules), the trim of `requirements.txt` to
`PySide6-Essentials` (verified to work, not applied), the slim Dockerfile (phase F), and the
decisions about the DEM family.

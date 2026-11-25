# Where this repository comes from

This is the **web edition** of IngeTrazo. Its engine (`core/`, `formats/`, `georef/`, and the
two kept tools `tools/pushpull.py` and `tools/offset.py`) is the desktop application's code,
forked from `ingelibre/ingetrazo` and pruned (see `docs/web-pruning-plan.md`). The desktop
application (the Qt interface, interactive tools and plugins) lives upstream and is the
specification for any future port.

- Upstream: https://github.com/ingelibre/ingetrazo
- Forked from commit `6be29fe437a7cd992d4e079f71720821b25216b9` (2026-10-01,
  "pick index: lazy placements as their own spans, a vectorised span cull (#158)").
- Tag `pre-prune` marks this repository just before the desktop code was removed; it still
  contains everything.

## Applying an upstream fix to a kept file

Kept files keep their paths and names, so a fix is a patch:

```bash
git remote add upstream https://github.com/ingelibre/ingetrazo.git   # once
git fetch upstream
git diff <old-upstream-commit> <new-upstream-commit> -- core/mesh.py | git apply --3way
```

Run `python -m web.tools.reachability --check` and the tests afterwards. A change to a file
that was removed here (anything under `views/`, `plugins/`, most of `tools/`) is simply not
applied. SKP export (upstream's `formats/skp_out.py`, off in the desktop too) is not taken: it
is not part of this open-source release.

## Synced so far

2026-10-21: engine files brought up to upstream `24e7ada` (0.5.9) by per-file `git apply --3way`
from `6be29fe`: push/pull, offset, mesh, topology, orient, solids, camera, guide, scene,
section, edits, history, snap, units, fillet (plus `bevel_profiles`), the exporters
(dae, glb, obj, stl, meshexport, ifc), the SKP importer and `openskp_compat`, and the new
`_native`, `lazy_mesh`, `scale_figure`. `formats/gltf.py` (structure-preserving GLB for plain exports, `semantic_parts` kept for the
preview) and `formats/igz.py` (textual curve ids, kept components, `stable_ids` kept) were
hand-merged; upstream's translations (de, fr, pl, ru) came with them. In `tools/pushpull.py` the viewport-only
cut check and `QApplication` call were removed on purpose.

### Optional Rust engine

`rust/ingetrazo_core` (from upstream) builds with `pip install maturin && cd rust/ingetrazo_core
&& maturin develop --release`, and is used only with `INGETRAZO_RUST=1`; without it, or without
the module, every caller runs its Python code. The full suite passes either way (2301 tests). On
the web benchmarks (a 10,000-face preview, 5,000-box edits) it made no difference, so it is off;
upstream's gains are on hidden lines, Intersect Faces and Orient over 100,000+ faces. The desktop
`core/intersect.py` and `core/ai.py` are not in this edition, so their kernels are unused.

### Not ported

The outliner (`core/outliner.py`, a Qt model), the extension manager, accent colours, toolbars and
the SpaceMouse work are desktop-only; the web has its own Parts panel and preferences. Join
Segments and Explode Curve are exposed as the `loose-edge-join` and `loose-edge-explode-curve`
commands (and MCP tools) and in the browser: loose edges can be selected (click, Shift-click, box),
and Join Segments / Explode Curve / Erase are in the Edit menu and the right-click menu.

### Synced to 0.6.2.1 (2026-11-16)

Upstream `8dbed76` (0.6.2.1), by per-file `git apply --3way` from `24e7ada` (0.5.9): the same kept
engine files again, plus `make_faces`, `hatches`, `progress`, `scene_animation`, `scene_folders`,
`zip_limits`, `recenter` (reached by the service) and `bridge`, `curve_segments`, `group_scale` and
`svg_out`, now exposed as the `loose-bridge`, `loose-resegment` and `set-object-scale` commands
and the `svg` export (plan edges by layer at 1:100, from the same groups as the DXF export). Languages went from 9 to 18 (Arabic is right-to-left; the web client does not
set the page direction yet). `core/version.py` is now 0.6.2.1.

Decisions: the SKP importer and `openskp_compat.py` were taken from upstream whole. Upstream now
carries its own SketchUp 2019 layer-record and loose-edge fixes, so the local run-time patch
(`docs/openskp-sketchup2019.patch`) is no longer used. One behaviour differs: a soft edge that no
face uses is now drawn as a line. The `meshexport.py` conflict keeps the web preview's
`collect_face_geometry` on top of upstream's smooth corner normals. In `tools/pushpull.py` the
`views.*` imports (lazy-mesh hover, shown guides) were replaced by plain reads. 50 of upstream's
new tests run here; the other 120 need the pruned Qt code.

### Synced to 0.6.3.2 (2026-11-25)

Upstream `78defb9` (0.6.3.2), per-file `git apply --3way` from `8dbed76` (0.6.2.1): 39 kept files,
the Rust crate, `resources/bim` (IFC delivery tables) and the translations (21 files, adding
Turkish and Catalan). New modules the service reaches were added to `web/KEEP.txt` (openings,
IFC identity and delivery, sheet folders, snap batches, the streaming `.igz` reader, the SKP
coordinate and consumption helpers, among others). Make faces and extrude,
terrain, material files and cut opening are wired to the web (`loose-make-faces-extrude`,
`terrain-create` / `-deform` / `-stamp`, `materials/import`, `materials.igmat`, painting with
a document material by name, `set-cut-opening`; openings follow every later edit through
`commit_revision`). Desktop-only modules were not taken (accessibility, Windows recent files, the user and
resource libraries, style mixing, transparency, update and preview probes, PDF/A, delivery zips).

Decisions: `formats/igz.py` keeps the web's path-based ids for old documents when `stable_ids` is
set (stored revisions refer to them) and uses upstream's new stable ids otherwise. In
`tools/pushpull.py` the new `views.viewport` uses (native corner projection, section cut during
inference) are replaced by the Python path. 45 of upstream's 200 new tests run here; the rest
need the pruned Qt code. `test_snap_batch_parity::test_the_engine_projects_as_this_qt` is an
expected failure on macOS: the kernel's projection is not bit-exact with Qt there, so that
search stays in Python.

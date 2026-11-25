# IngeTrazo Web: what is still missing, by phase

Status: 2026-10-05, against the phases in `web-port-plan.md`. That document's own status table
is stale (it still lists authentication and the import/export UI as open); refresh it when
the next items are chosen.

## Phase 0, baseline and contracts: complete

Headless boundary test, error contract, example documents and previews are in place.

## Phase 1, viewer MVP: mostly done

- No streaming progress on the server; cancel exists only in the browser.
- No agreed model sizes or performance budgets. Edits take seconds above about 30,000 faces
  (benchmarks in the plan), so "responsive at agreed sizes" is not met for large models.
- Visual comparison with the desktop was done by eye only, with no automated screenshot comparison.

## Phase 2, persistence: partly done

Missing:
- Quotas (documents, storage, concurrent jobs) and audit metadata.
- Conflict resolution: a 409 only shows an error; the browser does not offer to reload or merge.
- Database or object storage: files on disk only, no backups.
- Desktop round-trip tests: nothing checks that a document survives desktop, then web, then desktop without loss.

Done: revisions, multi-step undo and redo, revision retention, auto-save of presentation
changes, accounts and ownership.

## Phase 3, core modeling: mostly done

Missing:
- Gizmo manipulation (on-canvas handles for move, rotate and scale).
- An explicit work-plane tool (there is axis and plane snapping).
- Incremental edits: every edit still rewrites the whole `.igz`. The decision was to keep that;
  the next lever for large models is an incremental preview (rebuild only the objects an edit touched).

## Phase 3b, desktop-parity UI: nearly complete

Left: terrain profiles on sheets, and the desktop's Qt plugins (replaced by web extensions).

## Phase 4, architectural workflows: done at its exit level

Left: visual section caps and automatic online DEM download.

## Phase 5, interoperability: partly done

Missing:
- SKP: import is wired in (OpenSKP, open source). Tested with one real SketchUp 2019 file: it needed a run-time fix to OpenSKP's legacy reader (`formats/openskp_compat.py`, reference diff in `docs/openskp-sketchup2019.patch`, to be raised upstream on GitHub), and the importer now carries edges that no face uses. Still to test: other versions (2016-2018, 2020, 2021+) and large files. Export is kept in the private edition only.
- Parity tests: import and export paths are not checked against the desktop's round-trip tests.

Done: import and export through jobs, with progress, cancel and diagnostics, and a browser UI.

## Phase 6, hardening and deployment: mostly open

Only deployment has been exercised (a Debian arm64 test container). Missing:
- Containers: no Dockerfile, and no database, object storage or queue.
- Backups and observability.
- Upload scanning.
- OS-level sandboxing of jobs (they run in separate processes, with no seccomp or container
  sandbox; the memory cap works on Linux only).
- Rate limits beyond sign-in.
- Structured logging and telemetry.
- Accessibility checks.
- Browser compatibility checks beyond the in-app browser.
- Offline or reconnect behaviour: no service worker, and the page does not handle a dropped server.

## Done beyond the plan

MCP server for AI agents, the Preferences window (units, navigation, import, shortcuts),
the sheet composer, extensions, nested explode, accounts, the compact sidebar.

## Suggested order

1. Dockerfile and a CI run on Linux (the Debian test already showed what is needed, for
   example `manifold3d` and the system libraries).
2. Desktop round-trip parity tests (Phases 2 and 5).
3. A browser prompt for revision conflicts.
4. Accessibility and browser checks.
5. Quotas.
6. Incremental preview, only if large models matter.

## Deferred for now: pruning phases D and F

Phases A, B and C of `web-pruning-plan.md` are done. These two were put off on 2026-10-05;
nothing depends on them.

- **Phase D, prune inside the kept modules.** Remove code the web edition never calls, such as
  command classes in `core/history.py` (the largest file, 4,177 lines), with the reachability
  tool as proof and the end-to-end test as the safety net. Also decide the DEM family
  (`georef.dem`, `geotiff`, `profile`, `surface`, `terrain`, `tile_fetcher`), kept for now for
  terrain profiles.
- **Phase F, packaging and dependencies.** Trim `requirements.txt`, switch to
  `PySide6-Essentials` (the Debian test showed the venv drops from 851 MB to 447 MB), and write
  a slim Dockerfile. It also feeds the first item of "Suggested order" (Dockerfile and CI).

## Smaller open items

- 3D mouse (SpaceMouse) through WebHID, as an experiment. A browser sees a SpaceMouse as a
  generic HID device, not a pointer, so a page never receives it by default. Try WebHID: ask
  the user for the device, read its six-axis reports, and drive the camera with the desktop's
  mapping (`core/ndof.py`: object mode, full scale about 350, no roll), behind a "3D mouse"
  switch in Preferences > General. Open questions to test first: it works only in Chrome and
  Edge (not Safari or Firefox), only on localhost or HTTPS, and the user must grant the device
  each session; the 3Dconnexion driver may already hold the device on macOS, which can block
  WebHID, so the first step is to check on your Mac whether the device can be opened at all.
  Not possible on the iPad. Alternative if WebHID is blocked: 3Dconnexion's own web library,
  which goes through their driver.
- Terrain profiles on sheets; translation of strings the client builds with numbers.
- Pinning chosen revisions, per-user retention, restoring a pruned revision.
- A shaded render for the MCP `look` tool; a chat panel inside the browser.
- Loose edges that bound a face are edited only through the face.

"""The repository stays pruned: the web service reaches only what web/KEEP.txt lists, and
nothing unreachable lingers beyond what web/UNREACHABLE_ALLOWED.txt names (the pruning plan
empties that file). Also: kept engine code never imports the desktop UI, even inside a
function."""
from __future__ import annotations

from pathlib import Path

from web.tools import reachability as R

ROOT = R.ROOT


def _entries(name: str) -> list[str]:
    path = ROOT / "web" / name
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()]


def test_the_service_reaches_only_listed_modules():
    files = R.module_files()
    reached = {m for m in R.reachable(files=files) if m.split(".")[0] in R.ENGINE}
    keep = set(_entries("KEEP.txt"))
    assert not reached - keep, f"reached but not in web/KEEP.txt (new dependency on unlisted code): {sorted(reached - keep)}"
    assert not keep - reached - set(R.DYNAMIC), f"in KEEP.txt but no longer reachable: {sorted(keep - reached)}"


def test_kept_engine_code_never_imports_the_desktop_ui():
    files = R.module_files()
    reached = R.reachable(files=files)
    offenders = []
    for module in sorted(reached):
        if module.split(".")[0] not in R.ENGINE + ("web",):
            offenders.append(f"{module} (outside the engine)")
            continue
        for name in R._imports(files[module], module):
            top = name.split(".")[0]
            if top in {"views", "plugins"} or name.startswith(("PySide6.QtWidgets", "PySide6.QtOpenGL", "PySide6.QtQuick")):
                offenders.append(f"{module} imports {name}")
    assert not offenders, offenders


def test_unreachable_code_is_only_what_the_allowlist_names():
    files = R.module_files()
    reached = R.reachable(files=files)
    unreachable = {m for m in R.engine_modules(files) if m not in reached}
    allowed = {entry for entry in _entries("UNREACHABLE_ALLOWED.txt") if not entry.startswith("path:")}
    paths = [entry[5:] for entry in _entries("UNREACHABLE_ALLOWED.txt") if entry.startswith("path:")]
    assert not unreachable - allowed, f"dead engine modules not in the allowlist: {sorted(unreachable - allowed)}"
    assert not allowed - unreachable - {m for m in allowed if m not in files}, \
        f"allowlist entries that are reachable now: {sorted(allowed - unreachable)}"
    stale = sorted(m for m in allowed if m not in files)
    assert not stale, f"allowlist entries whose module is gone (delete them from the list): {stale}"
    stale_paths = sorted(p for p in paths if not (ROOT / p).exists())
    assert not stale_paths, f"allowlist paths that are gone (delete them from the list): {stale_paths}"
    for top in ("views", "plugins"):
        assert top in paths or not (ROOT / top).exists(), f"{top}/ exists but is not allowed"

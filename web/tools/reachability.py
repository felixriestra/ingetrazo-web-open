"""Which repository modules can the web service reach?

A static import graph over the repository's Python files (``import`` statements anywhere,
including inside functions), starting from the web service and the MCP-free entry points.
It is what keeps the repository pruned: ``web/KEEP.txt`` lists the modules the service may
reach, ``tests/test_web_reachability.py`` fails if it reaches anything else (so desktop code
cannot creep back in) and if the repository holds engine modules nothing reaches.

Imports built from strings (``importlib.import_module(name)``) are invisible to this
analysis; the few that matter are listed in ``DYNAMIC`` below, and every dynamic import in
kept code must be added there.

    python -m web.tools.reachability            # print the reachable engine modules
    python -m web.tools.reachability --check    # compare with web/KEEP.txt
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ("core", "formats", "tools", "georef")
ENTRY_PACKAGE = "web.backend"
#: Modules reached only through ``importlib`` (see edition.py and job_tasks.py).
DYNAMIC: dict[str, str] = {}


def module_files(roots: tuple[str, ...] = ENGINE + ("web", "views", "plugins", "scripts")) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for top in roots:
        base = ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in {"__pycache__", "node_modules", ".venv"} for part in path.parts):
                continue
            parts = list(path.relative_to(ROOT).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            files[".".join(parts)] = path
    return files


def _imports(path: Path, module: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join(parts + ([node.module] if node.module else []))
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def reachable(entry_prefix: str = ENTRY_PACKAGE, files: dict[str, Path] | None = None) -> set[str]:
    files = files or module_files()
    graph = {module: _imports(path, module) for module, path in files.items()}
    seen: set[str] = set()
    stack = [m for m in files if m == entry_prefix or m.startswith(entry_prefix + ".")]
    stack += [m for m in DYNAMIC if m in files]
    while stack:
        module = stack.pop()
        if module in seen or module not in files:
            continue
        seen.add(module)
        stack.extend(graph[module])
        parts = module.split(".")                         # importing a module imports its parent packages
        stack.extend(".".join(parts[:i]) for i in range(1, len(parts)))
    return seen


def engine_modules(files: dict[str, Path] | None = None) -> set[str]:
    files = files or module_files()
    return {m for m in files if m.split(".")[0] in ENGINE}


def load_keep() -> list[str]:
    path = ROOT / "web" / "KEEP.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()]


def main(argv: list[str]) -> int:
    files = module_files()
    reach = {m for m in reachable(files=files) if m.split(".")[0] in ENGINE}
    if "--check" in argv:
        keep = set(load_keep())
        extra, missing = sorted(reach - keep), sorted(keep - reach)
        print("reachable but not in KEEP.txt:", extra or "none")
        print("in KEEP.txt but not reachable:", missing or "none")
        return 1 if extra else 0
    for module in sorted(reach):
        print(module)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

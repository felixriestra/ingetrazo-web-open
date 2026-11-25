"""The web service must stay headless: no desktop UI, no widgets, no QApplication.

Decision 4 of the port plan: the browser is the interface, the server only loads,
edits and renders native documents. This fails if web code (or anything it imports,
at start-up or while rendering a sheet, a preview and 3D text) pulls in ``views`` or
``PySide6.QtWidgets``, or constructs a ``QApplication``.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MODULES = ("views", "PySide6.QtWidgets", "PySide6.QtOpenGLWidgets", "PySide6.QtQuickWidgets")


def _web_sources():
    return sorted((ROOT / "web" / "backend").rglob("*.py"))


def test_web_code_never_names_the_desktop_ui():
    offenders = []
    for path in _web_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = "." * node.level + (node.module or "")
                names = [base] + [f"{base}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Name) and node.id in {"QApplication", "QWidget", "QMainWindow"}:
                names = [node.id]
            for name in names:
                if name in {"QApplication", "QWidget", "QMainWindow"} or any(
                        name == bad or name.startswith(bad + ".") for bad in FORBIDDEN_MODULES):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}")
    assert not offenders, "\n".join(offenders)


SCRIPT = """
import sys, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from web.backend.ingetrazo_web.app import create_app
from core.scene import Scene
from core.composition import Composicion
from formats.igz import save_scene

tmp = Path(tempfile.mkdtemp())
client = TestClient(create_app(tmp / "data"))
scene = Scene()
scene.compositions.append(Composicion(name="S"))
source = tmp / "doc.igz"
save_scene(scene, source)
doc = client.post("/api/v1/documents", files={"file": ("d.igz", source.read_bytes())}).json()
base = f"/api/v1/documents/{doc['id']}"
assert client.post(base + "/commands/create-box", json={"base_revision": 1, "size": [1, 1, 1]}).status_code == 201
assert client.get(base + "/revisions/2/preview").status_code == 200
assert client.get(base + "/revisions/2/sheets/0.png?dpi=30").status_code == 200
assert client.get(base + "/revisions/2/sheets/0.pdf").status_code == 200
assert client.post(base + "/commands/create-text3d", json={"base_revision": 2, "text": "Hi", "height": 0.3}).status_code == 201
bad = sorted(name for name in sys.modules if name == "views" or name.startswith("views.") or name in (
    "PySide6.QtWidgets", "PySide6.QtOpenGLWidgets"))
from PySide6.QtCore import QCoreApplication
print("LOADED", bad, type(QCoreApplication.instance()).__name__)
sys.exit(1 if bad or type(QCoreApplication.instance()).__name__ == "QApplication" else 0)
"""


def test_serving_every_kind_of_request_loads_no_widgets_and_no_qapplication():
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr

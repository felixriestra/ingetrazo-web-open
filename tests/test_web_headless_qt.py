"""The service must not abort when it runs without a test harness's Qt app."""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
import sys, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from web.backend.ingetrazo_web.app import create_app
from core.scene import Scene
from formats.igz import save_scene

tmp = Path(tempfile.mkdtemp())
client = TestClient(create_app(tmp / "data"))
source = tmp / "empty.igz"
save_scene(Scene(), source)
doc = client.post("/api/v1/documents", files={"file": ("e.igz", source.read_bytes())}).json()
r = client.post(f"/api/v1/documents/{doc['id']}/commands/create-text3d",
                json={"base_revision": 1, "text": "Hi", "height": 0.3})
print(r.status_code)
sys.exit(0 if r.status_code == 201 else 1)
"""


def test_3d_text_works_in_a_bare_process():
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr

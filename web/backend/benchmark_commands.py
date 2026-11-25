"""Time the load -> mutate -> save cycle behind every web edit, on synthetic models.

    python -m web.backend.benchmark_commands            # 100, 1000 and 5000 boxes
    python -m web.backend.benchmark_commands 20000      # one size

Every command reloads the base revision, applies the edit, saves a new ``.igz`` and
summarises it; the browser then fetches a preview. This prints each stage's time per
model size, as JSON, so a size at which edits stop feeling instant can be found, and
so a caching change can be shown to help. Sizes are numbers of box groups (6 faces each).
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtGui import QVector3D

from core.group import Group
from core.scene import Scene
from formats.igz import save_scene

from .ingetrazo_web.commands import ensure_qt


def synthetic_scene(boxes: int) -> Scene:
    scene = Scene()
    side = max(1, int(boxes ** 0.5))
    for index in range(boxes):
        x, y = (index % side) * 2.0, (index // side) * 2.0
        p = [QVector3D(x + dx, y + dy, z) for z in (0, 1) for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))]
        group = Group(name=f"Box {index}")
        for loop in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]):
            group.mesh.add_face([p[i] for i in loop])
        scene.groups.append(group)
    return scene


def timed(function):
    started = time.perf_counter()
    result = function()
    return result, round(time.perf_counter() - started, 3)


def measure(boxes: int) -> dict:
    from fastapi.testclient import TestClient

    from .ingetrazo_web.app import create_app
    from .ingetrazo_web.scene_service import load_igz

    ensure_qt()
    with tempfile.TemporaryDirectory(prefix="ingetrazo-cmd-bench-") as directory:
        root = Path(directory)
        scene, build = timed(lambda: synthetic_scene(boxes))
        source = root / "model.igz"
        _, save = timed(lambda: save_scene(scene, source))
        _, load = timed(lambda: load_igz(source))
        client = TestClient(create_app(root / "data"))
        record, upload = timed(lambda: client.post("/api/v1/documents", files={"file": ("m.igz", source.read_bytes())}).json())
        base = f"/api/v1/documents/{record['id']}"
        move, command = timed(lambda: client.post(
            f"{base}/commands/move-object", json={"base_revision": 1, "object_id": "group:0", "delta": [1, 0, 0]}))
        assert move.status_code == 201, move.text
        _, preview = timed(lambda: client.get(f"{base}/revisions/2/preview"))
        return {"boxes": boxes, "faces": boxes * 6, "igz_mib": round(source.stat().st_size / 2 ** 20, 2),
                "seconds": {"build_scene": build, "save": save, "load": load, "upload_and_summarise": upload,
                            "edit_command_total": command, "preview_after_edit": preview}}


def main(argv: list[str]) -> int:
    sizes = [int(arg) for arg in argv] or [100, 1000, 5000]
    print(json.dumps([measure(size) for size in sizes], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

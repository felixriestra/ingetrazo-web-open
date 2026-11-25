"""The web toolbar chrome: manifest and icons are consistent."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_manifest_is_consistent():
    """The toolbar manifest and icons were exported from the desktop application (see
    UPSTREAM.md) and are now this repository's own assets: they must stay self-consistent."""
    manifest = json.loads(
        (ROOT / "web" / "frontend" / "src" / "ui" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["toolbars"] and manifest["tools"]
    placed = [key for row in manifest["toolbars"] for key in row["tools"]]
    assert len(placed) == len(set(placed)), "a tool appears on two toolbars"
    for key, entry in manifest["tools"].items():
        assert entry["name"], key
    for row in manifest["toolbars"]:
        assert row["area"] in {"top", "left"} and row["title"], row


def test_every_toolbar_button_has_an_icon_for_both_themes():
    manifest = json.loads(
        (ROOT / "web" / "frontend" / "src" / "ui" / "manifest.json")
        .read_text(encoding="utf-8"))
    for row in manifest["toolbars"]:
        for key in row["tools"]:
            assert key in manifest["tools"], key
            for theme in ("dark", "light"):
                icon = ROOT / "web" / "frontend" / "public" / "icons" / theme / f"{key}.png"
                assert icon.is_file(), icon

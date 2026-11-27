"""How the browser client is served: a browser must never keep an old client
page after the server is updated, and may keep the hashed build files for good."""
from __future__ import annotations

import re

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.ingetrazo_web import app as app_module  # noqa: E402
from web.backend.ingetrazo_web.app import create_app  # noqa: E402

pytestmark = pytest.mark.skipif(app_module._FRONTEND.name != "dist", reason="the client is not built")


def test_the_page_is_checked_on_every_load_and_hashed_files_are_kept(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))

    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-cache"
    # an unchanged page still answers 304, so checking costs little
    again = client.get("/", headers={"If-None-Match": page.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"

    script = re.search(r'src="/?(assets/index-[^"]+\.js)"', page.text).group(1)
    asset = client.get("/" + script)
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"

    assert "cache-control" not in client.get("/assets/no-such-file.js").headers

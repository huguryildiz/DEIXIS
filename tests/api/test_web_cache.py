"""The served UI: the page is revalidated on every load and hashed assets are cached, so an updated app never runs an old bundle.

SYNTHETIC build files in a temporary folder; no browser runs. Passing shows the headers, not how a given webview caches.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.runtime.config import Settings
from fakes import FakeAdapter


def test_the_page_is_revalidated_and_hashed_assets_are_cached(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<script src=/assets/index-SYNTHETIC.js></script>")
    (dist / "assets" / "index-SYNTHETIC.js").write_text("console.log(1)")
    monkeypatch.setattr(Settings, "web_dist", property(lambda self: dist))
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))), start_worker=False,
        extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        assert client.get("/").headers["cache-control"] == "no-cache"
        assert client.get("/index.html").headers["cache-control"] == "no-cache"
        assert client.get("/assets/index-SYNTHETIC.js").headers["cache-control"] == "public, max-age=31536000, immutable"

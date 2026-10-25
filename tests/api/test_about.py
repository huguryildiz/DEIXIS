"""About (pre-P10 F2, F5): version, licence, source link, the third-party notices text and the Report a problem link.

Workflow behavior only. Passing shows the routes answer from the installed package's version and the notices file, and
that the issue link carries only the validated version, OS name and architecture. It does not show that the GitHub issue
form opens with those fields filled; that needs the live site.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import paths
from deixis.api import about_routes
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter


@pytest.fixture
def served(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))), start_worker=False,
        extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        yield client


def test_about_names_the_version_the_licence_and_the_source(served):
    body = served.get("/api/about").json()
    assert body["version"] == about_routes.app_version() and body["version"] != "unknown"
    assert body["license"] == "AGPL-3.0-or-later"
    assert body["repo_url"] == "https://github.com/huguryildiz/DEIXIS"
    assert body["source_url"] == body["repo_url"] and body["source_is_tag"] is False  # no version tag is known yet
    assert body["notices_available"] is True


def test_the_notices_route_serves_the_text_and_says_when_there_is_none(served, tmp_path, monkeypatch):
    text = served.get("/api/about/notices")
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/plain")
    assert "THIRD-PARTY NOTICES" in text.text and "MuPDF" in text.text
    monkeypatch.setattr(paths, "RESOURCE_ROOT", tmp_path)  # a folder without the file
    assert served.get("/api/about").json()["notices_available"] is False
    assert served.get("/api/about/notices").status_code == 404


def test_the_report_link_carries_only_the_version_the_os_and_the_architecture():
    url = about_routes.report_url("0.1.0", "macOS", "arm64")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://github.com/huguryildiz/DEIXIS/issues/new"
    query = parse_qs(parts.query)
    assert set(query) == {"template", "version", "os", "body"} and "title" not in query
    assert query["version"] == ["0.1.0"] and query["os"] == ["macOS arm64"]
    assert query["body"] == ["DEIXIS version: 0.1.0\nOS: macOS arm64"]



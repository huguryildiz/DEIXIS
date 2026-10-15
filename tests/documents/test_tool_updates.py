"""Update checks for Tesseract, Marker and PyMuPDF on Settings → On this computer; release lists are mocked."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.documents import ocr, tool_updates
from test_api_flow import fake_fetch, session, sw_settings

from fakes import FakeAdapter


def releases(request: httpx.Request) -> httpx.Response:
    if request.url.host == "formulae.brew.sh":
        return httpx.Response(200, json={"versions": {"stable": "5.5.3"}})
    if request.url.path == "/pypi/marker-pdf/json":
        return httpx.Response(200, json={"info": {"version": "2.0.0"}})
    if request.url.path == "/pypi/pymupdf/json":
        return httpx.Response(503)
    return httpx.Response(404)


def client_for(tmp_path):
    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(releases)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    return TestClient(app)


def test_versions_compare_by_number_and_ignore_homebrew_revisions():
    assert tool_updates.newer("5.5.10", "5.5.9") is True
    assert tool_updates.newer("5.5.2_1", "5.5.2") is False
    assert tool_updates.newer("1.28.2", "1.28.2") is False
    assert tool_updates.newer(None, "1.0") is None and tool_updates.newer("1.0", None) is None


def test_each_tool_reports_its_installed_and_latest_version(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_status", lambda langs=ocr.LANGUAGES: {"version": "5.5.2"})
    with client_for(tmp_path) as raw:
        client = session(raw)
        tesseract = client.get("/api/tool-updates/tesseract").json()
        assert (tesseract["installed"], tesseract["latest"], tesseract["update_available"]) == ("5.5.2", "5.5.3", True)
        assert tesseract["command"] == tool_updates.UPGRADE_COMMAND

        marker = client.get("/api/tool-updates/marker").json()  # not installed in this data folder
        assert (marker["installed"], marker["tested"], marker["latest"], marker["update_available"]) == (None, "1.10.2", "2.0.0", None)
        assert marker["command"] is None  # pinned: a newer Marker comes with a DEIXIS update

        pymupdf = client.get("/api/tool-updates/pymupdf").json()
        assert pymupdf["installed"] == client.get("/api/pdf-reader").json()["version"]
        assert pymupdf["latest"] is None and pymupdf["update_available"] is None and "503" in pymupdf["error"]

        assert client.get("/api/tool-updates/zotero").status_code == 404

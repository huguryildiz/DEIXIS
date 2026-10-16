"""Update checks for Tesseract, Marker and PyMuPDF on Settings → On this computer; release lists are mocked."""

from __future__ import annotations

import asyncio
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.tools import tool_paths
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

        marker = client.get("/api/tool-updates/marker").json()  # not installed in this data folder
        assert (marker["installed"], marker["tested"], marker["latest"], marker["update_available"]) == (None, "1.10.2", "2.0.0", None)

        pymupdf = client.get("/api/tool-updates/pymupdf").json()
        assert pymupdf["installed"] == client.get("/api/pdf-reader").json()["version"]
        assert pymupdf["latest"] is None and pymupdf["update_available"] is None and "503" in pymupdf["error"]

        assert client.get("/api/tool-updates/zotero").status_code == 404


def test_tesseract_installs_with_the_fixed_homebrew_command_and_reports_its_step(tmp_path, monkeypatch):
    brew = tmp_path / "brew"
    brew.write_text('#!/bin/sh\necho "$@" > "$(dirname "$0")/args"\necho "==> Fetching tesseract"\necho "==> Pouring tesseract"\n')
    brew.chmod(0o755)
    monkeypatch.setattr(tool_updates, "brew", lambda: str(brew))
    monkeypatch.setattr(ocr, "tesseract_status", lambda langs=ocr.LANGUAGES: {"available": True, "version": "5.5.2"})
    with client_for(tmp_path) as raw:
        client = session(raw)
        assert client.get("/api/ocr").json()["job"] is None
        assert client.post("/api/ocr/install").json()["job"]["status"] == "running"
        for _ in range(100):
            job = client.get("/api/ocr").json()["job"]
            if job["status"] != "running":
                break
            time.sleep(0.05)
        assert (job["status"], job["phase"]) == ("succeeded", "installing")
        assert (tmp_path / "args").read_text().split() == list(tool_updates.INSTALL_ARGS)

        monkeypatch.setattr(tool_updates, "brew", lambda: None)
        missing = client.post("/api/ocr/install")
        assert missing.status_code == 422 and client.get("/api/ocr").json()["can_install"] is False


# ---- a Tesseract that comes inside the packaged app (B1) ---------------------------------------------------

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake Tesseract is a shell script")


def fake_tesseract(folder, version="5.5.1"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "tesseract"
    path.write_text('#!/bin/sh\ncase "$1" in\n--version) echo "tesseract %s";;\n--list-langs) printf \'List of available languages in "/x" (2):\\neng\\ntur\\n\';;\nesac\n' % version)
    path.chmod(0o755)
    return path


def packaged(monkeypatch, bundle, frozen=True):
    monkeypatch.setattr(tool_paths, "is_frozen", lambda: frozen)
    monkeypatch.setattr(tool_paths, "resource_root", lambda: bundle)


@posix_only
def test_a_bundled_tesseract_is_reported_as_part_of_the_app_and_a_run_from_the_repository_has_none(tmp_path, monkeypatch):
    bundled = fake_tesseract(tmp_path / "bundle" / "bin")
    on_path = fake_tesseract(tmp_path / "path", "5.3.0")
    monkeypatch.setenv("PATH", str(on_path.parent))
    packaged(monkeypatch, tmp_path / "bundle")
    status = ocr.tesseract_status(("eng", "tur"))
    assert (status["bundled"], status["path"], status["version"], status["available"]) == (True, str(bundled), "5.5.1", True)

    packaged(monkeypatch, tmp_path / "bundle", frozen=False)  # development: the bundle folder is not looked at at all
    status = ocr.tesseract_status(("eng", "tur"))
    assert (status["bundled"], status["path"], status["version"]) == (False, str(on_path), "5.3.0")

    monkeypatch.setenv("PATH", "")
    missing = ocr.tesseract_status(("eng", "tur"))
    assert (missing["bundled"], missing["path"], missing["reason"]) == (False, None, "tesseract_missing")


@posix_only
def test_the_update_check_of_a_bundled_tesseract_follows_the_app_and_asks_homebrew_nothing(tmp_path, monkeypatch):
    fake_tesseract(tmp_path / "bundle" / "bin", "5.5.1")
    monkeypatch.setenv("PATH", "")
    packaged(monkeypatch, tmp_path / "bundle")
    asked = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: asked.append(request) or httpx.Response(200, json={"versions": {"stable": "9.9.9"}})))
    result = asyncio.run(tool_updates.check("tesseract", http, None))
    assert (result["installed"], result["latest"], result["update_available"], result["error"]) == ("5.5.1", None, None, None)
    assert asked == []

    packaged(monkeypatch, tmp_path / "bundle", frozen=False)  # not packaged and not on PATH: nothing installed, the formula API is asked
    result = asyncio.run(tool_updates.check("tesseract", http, None))
    assert (result["installed"], result["latest"], len(asked)) == (None, "9.9.9", 1)


@posix_only
def test_the_ocr_status_offers_no_homebrew_install_for_a_bundled_tesseract_and_the_install_is_refused(tmp_path, monkeypatch):
    fake_tesseract(tmp_path / "bundle" / "bin")
    monkeypatch.setenv("PATH", "")
    ran = tmp_path / "ran"
    brew = tmp_path / "brew"
    brew.write_text(f"#!/bin/sh\necho x >> {ran}\n")
    brew.chmod(0o755)
    monkeypatch.setattr(tool_updates, "brew", lambda: str(brew))
    with client_for(tmp_path) as raw:
        client = session(raw)
        packaged(monkeypatch, tmp_path / "bundle")
        status = client.get("/api/ocr").json()
        assert (status["bundled"], status["can_install"], status["available"]) == (True, False, True)
        assert client.post("/api/ocr/install").status_code == 409 and not ran.exists()

        packaged(monkeypatch, tmp_path / "bundle", frozen=False)  # the same computer in development: Homebrew is offered again
        fake_tesseract(tmp_path / "dev")
        monkeypatch.setenv("PATH", str(tmp_path / "dev"))
        status = client.get("/api/ocr").json()
        assert (status["bundled"], status["can_install"]) == (False, True)


def test_a_computer_without_homebrew_is_sent_to_the_page_its_os_installs_tesseract_from(monkeypatch):
    pages = {}
    for platform in ("darwin", "win32", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        pages[platform] = tool_updates.tesseract_page()
    assert [tool_updates.tesseract_source()["install_manager"]] == [None]  # linux, the last one patched
    monkeypatch.setattr(sys, "platform", "darwin")
    assert tool_updates.tesseract_source() == {"install_url": "https://brew.sh", "install_manager": "brew"}
    assert pages["darwin"] == "https://brew.sh"
    assert "UB-Mannheim/tesseract" in pages["win32"] and "tessdoc" in pages["linux"]
    assert len(set(pages.values())) == 3 and all(p.startswith("https://") for p in pages.values())

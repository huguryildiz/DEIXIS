"""About (pre-P10 F2, F5): version, licence, source link, the third-party notices text and the Report a problem link.

Workflow behavior only. Passing shows the routes answer from the installed package's version and the notices file, and
that the issue link carries only the validated version, OS name and architecture. It does not show that the GitHub issue
form opens with those fields filled; that needs the live site.
"""

from __future__ import annotations

import re
from pathlib import Path
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


def test_the_source_link_is_the_tag_page_once_the_version_has_a_tag(monkeypatch):
    monkeypatch.setattr(about_routes, "TAGGED_VERSIONS", frozenset({"0.1.0"}))
    assert about_routes.source_url("0.1.0") == ("https://github.com/huguryildiz/DEIXIS/tree/v0.1.0", True)
    assert about_routes.source_url("0.2.0") == ("https://github.com/huguryildiz/DEIXIS", False)


def test_the_notices_route_serves_the_text_and_says_when_there_is_none(served, tmp_path, monkeypatch):
    text = served.get("/api/about/notices")
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/plain")
    assert "THIRD-PARTY NOTICES" in text.text and "MuPDF" in text.text
    monkeypatch.setattr(paths, "RESOURCE_ROOT", tmp_path)  # a folder without the file
    assert served.get("/api/about").json()["notices_available"] is False
    assert served.get("/api/about/notices").status_code == 404


@pytest.mark.parametrize("system,machine,expected", [
    ("Darwin", "arm64", ("macOS", "arm64")), ("Darwin", "x86_64", ("macOS", "x86_64")),
    ("Windows", "AMD64", ("Windows", "x86_64")), ("Linux", "aarch64", ("Linux", "arm64")),
    ("FreeBSD", "riscv64", ("other", "other")),
])
def test_os_and_architecture_are_names_from_a_short_list(monkeypatch, system, machine, expected):
    monkeypatch.setattr(about_routes.platform, "system", lambda: system)
    monkeypatch.setattr(about_routes.platform, "machine", lambda: machine)
    assert about_routes.os_and_arch() == expected


def test_the_report_link_carries_only_the_version_the_os_and_the_architecture():
    url = about_routes.report_url("0.1.0", "macOS", "arm64")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://github.com/huguryildiz/DEIXIS/issues/new"
    query = parse_qs(parts.query)
    assert set(query) == {"template", "version", "os", "body"} and "title" not in query
    assert query["version"] == ["0.1.0"] and query["os"] == ["macOS arm64"]
    assert query["body"] == ["DEIXIS version: 0.1.0\nOS: macOS arm64"]


def test_a_version_that_is_not_a_version_is_replaced_before_it_reaches_the_link():
    for hostile in ("0.1.0&title=x", "1.0\nname: huguryildiz", "/Users/someone/app", "", "x" * 80):
        assert about_routes.clean_version(hostile) == "unknown"
    assert about_routes.clean_version("0.1.0") == "0.1.0" and about_routes.clean_version("1.2.3.dev4+g1a2b") == "1.2.3.dev4+g1a2b"
    url = about_routes.report_url(about_routes.clean_version("0.1.0&title=x"), "Linux", "x86_64")
    assert "title" not in parse_qs(urlsplit(url).query) and "unknown" in url


def test_the_report_link_in_the_answer_holds_nothing_from_this_computer(served, monkeypatch, tmp_path):
    body = served.get("/api/about").json()
    query = parse_qs(urlsplit(body["report_url"]).query)
    flat = " ".join(" ".join(v) for v in query.values())
    for private in (str(tmp_path), "/Users/", "@", "key", "error"):
        assert private not in flat
    assert body["os"] in ("macOS", "Windows", "Linux", "other") and body["arch"] in ("arm64", "x86_64", "other")


def test_the_issue_form_has_the_fields_the_report_link_fills():
    form = (Path(__file__).resolve().parents[2] / ".github" / "ISSUE_TEMPLATE" / "bug.yml").read_text(encoding="utf-8")
    ids = set(re.findall(r"^\s+id: (\w+)$", form, re.M))
    query = parse_qs(urlsplit(about_routes.report_url("0.1.0", "Linux", "x86_64")).query)
    assert {"version", "os"} <= ids and (set(query) - {"template", "body"}) <= ids
    assert query["template"] == ["bug.yml"]

"""App shell routes: awaiting counts, profile, proxy test, contact email, preferences, backup, earlier question
revisions.

FakeAdapter and mocked HTTP only. Passing shows the routes' behaviour, not how the shell draws it.
"""

from __future__ import annotations

import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import config
from deixis.api import shell_routes
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import fetch
from deixis.providers import scopus
from deixis.storage import data_location
from deixis.workflow import queue
from fakes import FakeAdapter
from test_api_flow import app_for
from test_api_flow import create
from test_api_flow import session
from test_queue import Lib
from test_queue import queued
from test_waiting_flow import write_plan


PROXY = "https://proxy.synthetic.example/login?url="


PUBLIC = "93.184.216.34"


PAGES = ["SYNTHETIC page one"]


def open_client(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


class Calls(list):
    """Every request the mocked transports saw, and which client carried it: `shared` (the app's provider client),
    `fresh` (the new connection for the Scopus check) or `proxy` (the proxy test's own client)."""

    def __init__(self):
        super().__init__()
        self.tags = []

    def by(self, tag):
        return [request for t, request in self.tags if t == tag]


@pytest.fixture
def served(tmp_path, monkeypatch):
    """An app whose HTTP transports record their calls and answer by host; the proxy host resolves to a public address."""
    calls, answers = Calls(), {}

    def handler_for(tag):
        def handler(request):
            calls.append(request)
            calls.tags.append((tag, request))
            answer = answers.get(request.url.host)
            if isinstance(answer, Exception):
                raise answer
            return answer(request) if callable(answer) else (answer or httpx.Response(200, json={}))
        return handler

    def client_for(tag):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler_for(tag)))

    async def resolve(host, port):
        return answers.get("resolve", [PUBLIC])

    monkeypatch.setattr(fetch, "_resolve", resolve)
    monkeypatch.setattr(scopus, "route_source", lambda: "192.168.0.2")
    monkeypatch.setattr(shell_routes, "proxy_client", lambda: client_for("proxy"))
    monkeypatch.delenv("DEIXIS_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=client_for("shared"), start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = open_client(app)
    app.state.fresh_http = lambda: client_for("fresh")
    try:
        yield app, client, calls, answers
    finally:
        client.__exit__(None, None, None)


def awaiting_of(client, rid):
    return next(r for r in client.get("/api/researches").json() if r["id"] == rid)["awaiting"]


def test_awaiting_keeps_queue_rows_and_pdf_waits_apart_and_follows_a_queue_and_a_pdf_change(served, monkeypatch):
    app, client, _, _ = served
    store = app.state.store
    lib = Lib(store, "irrigation")
    first, second = queued(lib), queued(lib)
    waiting_work = lib.work()
    step = write_plan(lib, [waiting_work])
    lib.ds.record(lib.rid, waiting_work, "no_fulltext", step_id=step)
    assert awaiting_of(client, lib.rid) == {"queue": 2, "pdf": 1}

    # Cached while the research's latest event is the same: the 5 s poll derives nothing.
    derived = []
    original = queue.queue_counts
    monkeypatch.setattr(queue, "queue_counts", lambda *a, **k: derived.append(1) or original(*a, **k))
    assert awaiting_of(client, lib.rid) == {"queue": 2, "pdf": 1} and derived == []

    # A queue answer writes its event with the decision: one row leaves the queue.
    queue.decide(store, lib.rid, first, "not_sure", None, lib.row(first)["row_token"])
    assert awaiting_of(client, lib.rid) == {"queue": 1, "pdf": 1} and derived == [1]

    # "PDF is wrong" moves the work from the queue to the PDF list: the two numbers change in opposite directions.
    step = write_plan(lib, [second])
    queue.decide(store, lib.rid, second, "pdf_wrong", None, lib.row(second)["row_token"])
    assert awaiting_of(client, lib.rid) == {"queue": 0, "pdf": 2}

    # A PDF attached for the waiting work, written with its event as the upload route does.
    lib.text(waiting_work, PAGES)
    store._event(lib.rid, "waiting_pdf_attached", {"source_version_id": waiting_work, "work_id": lib.work_of(waiting_work),
                                                   "asset_id": "ast_synthetic", "reading": None})
    assert awaiting_of(client, lib.rid) == {"queue": 0, "pdf": 1}


def set_proxy(client, address=PROXY):
    assert client.put("/api/institution-proxy", json={"address": address}).status_code == 200


def test_a_proxy_host_on_a_private_network_is_refused_and_never_asked(served):
    _, client, calls, answers = served
    set_proxy(client)
    answers["resolve"] = ["10.1.2.3"]
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert (test["proxy_reachable"], test["proxy_error"]) == (False, "blocked_url")
    assert "non-public" in test["proxy_error_detail"] and calls == []


def test_the_test_needs_an_address_and_the_csrf_token_and_goes_stale_when_the_address_changes(served):
    app, client, _, answers = served
    assert client.post("/api/institution-proxy/test").status_code == 422
    set_proxy(client)
    answers[PUBLIC] = httpx.Response(200)
    bare = TestClient(app)
    assert bare.post("/api/institution-proxy/test").status_code == 403
    assert client.post("/api/institution-proxy/test").json()["test_is_current"] is True
    set_proxy(client, "https://other.synthetic.example/login?url=")
    stale = client.get("/api/institution-proxy/settings").json()
    assert stale["test"]["address"] == PROXY and stale["test_is_current"] is False


def test_the_proxy_test_ignores_the_proxy_environment_variables(monkeypatch):
    # The module's own factory (no fixture patches it here): with HTTPS_PROXY and ALL_PROXY set it mounts no proxy.
    for name in ("HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    assert httpx.AsyncClient()._mounts != {}  # the same environment does route a default client
    assert shell_routes.proxy_client()._mounts == {}


def effective(app):
    return app.state.worker.flow.deps.settings.contact_email


def test_the_pdf_fetch_is_given_the_contact_email_set_in_settings_at_each_download(served, monkeypatch):
    app, client, _, _ = served
    asked = []

    async def fetch_pdf(url, email=None):
        asked.append((url, email))
        return fetch.FetchResult("http_error", final_url=url, http_status=403)

    monkeypatch.setattr(fetch, "fetch_pdf", fetch_pdf)
    url = "https://papers.synthetic.example/a.pdf"
    asyncio.run(app.state.fetch_pdf(url))
    client.put("/api/contact-email", json={"email": "me@synthetic.example"})
    asyncio.run(app.state.worker.flow.deps.fetch_pdf(url))
    assert asked == [(url, None), (url, "me@synthetic.example")]


@pytest.fixture
def client(tmp_path, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(config, "platform_data_dir", lambda: folder)
    monkeypatch.delenv("DEIXIS_DATA_DIR", raising=False)
    monkeypatch.setattr(data_location, "backup_dir", lambda: tmp_path / "backups")
    app = create_app(Settings(data_dir=folder, port=8765, model_concurrency=3, fulltext_fetch="off"), adapters={"fake": FakeAdapter()},
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        c.app_state = app.state
        c.folder = folder
        yield c


def test_a_stored_preference_comes_before_the_start_value_and_applies_at_once(client):
    view = client.put("/api/settings/preferences", json={"default_effort": "detailed", "fulltext_fetch": "auto",
                                                         "arxiv_source": "auto", "model_concurrency": 9}).json()
    assert (view["default_effort"], view["fulltext_fetch"], view["arxiv_source"], view["model_concurrency"]) == ("detailed", "auto", "auto", 9)
    state = client.app_state
    assert state.settings.effective_fulltext_fetch() == "auto"
    assert state.equations.arxiv_mode == "auto" and state.limiter.limit == 9
    # A partial change leaves the others as stored.
    assert client.put("/api/settings/preferences", json={"model_concurrency": 2}).json()["default_effort"] == "detailed"
    assert state.limiter.limit == 2


@pytest.mark.parametrize("bad", [{"model_concurrency": 0}])
def test_an_invalid_preference_is_refused_and_nothing_is_stored(client, bad):
    assert client.put("/api/settings/preferences", json=bad).status_code == 422
    assert client.get("/api/settings/preferences").json()["model_concurrency"] == 3


def test_an_earlier_revision_reads_back_as_it_was_saved(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, question="SYNTHETIC how is molecule release scheduling optimized?")
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": "SYNTHETIC a narrower molecule release question",
                                                                    "expected_version": version, "key_terms": "molecule release; scheduling"})
        assert revised.status_code == 200, revised.text

        first = client.get(f"/api/researches/{rid}/scope-revisions/1").json()
        assert (first["revision"], first["question"], first["source_scope"], first["key_terms"]) == (
            1, "SYNTHETIC how is molecule release scheduling optimized?", "academic", None)
        assert first["created_at"]
        second = client.get(f"/api/researches/{rid}/scope-revisions/2").json()
        assert (second["question"], second["key_terms"]) == ("SYNTHETIC a narrower molecule release question", "molecule release; scheduling")

        assert client.get(f"/api/researches/{rid}/scope-revisions/3").status_code == 404
        assert client.get("/api/researches/no-such-research/scope-revisions/1").status_code == 404

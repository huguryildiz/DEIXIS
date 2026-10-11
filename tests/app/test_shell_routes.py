"""The routes behind the app shell (parity slice S2): awaiting counts, profile, proxy label and test, contact email.

Workflow behavior only. Records are SYNTHETIC and reuse the queue tests' greenhouse irrigation field; every transport is
mocked and no model is asked. Passing shows the counts, the proxy test's two separate facts and the setting's order
against the environment variable behave as the slice says. It says nothing about whether a real proxy answers or a
real Scopus key is entitled.
"""

import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api import shell_routes
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import fetch
from deixis.providers import scopus
from deixis.workflow import queue
from fakes import FakeAdapter
from test_queue import Lib, queued
from test_waiting_flow import write_plan

PROXY = "https://proxy.synthetic.example/login?url="
PUBLIC = "93.184.216.34"
PAGES = ["SYNTHETIC page one"]


def make_app(tmp_path, handler=None, monkeypatch=None):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda request: httpx.Response(200, json={}))))
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    return create_app(settings, adapters={"fake": FakeAdapter()}, http_client=http, start_worker=False,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def open_client(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


@pytest.fixture
def served(tmp_path, monkeypatch):
    """An app whose HTTP transport records its calls and answers by host; the proxy host resolves to a public address."""
    calls, answers = [], {}

    def handler(request):
        calls.append(request)
        answer = answers.get(request.url.host)
        if isinstance(answer, Exception):
            raise answer
        return answer or httpx.Response(200, json={})

    async def resolve(host, port):
        return answers.get("resolve", [PUBLIC])

    monkeypatch.setattr(fetch, "_resolve", resolve)
    monkeypatch.setattr(scopus, "route_source", lambda: "192.168.0.2")
    monkeypatch.delenv("DEIXIS_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    app = make_app(tmp_path, handler)
    client = open_client(app)
    try:
        yield app, client, calls, answers
    finally:
        client.__exit__(None, None, None)


# ---- F1: awaiting --------------------------------------------------------------------------------------------------


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


def test_a_research_with_nothing_waiting_has_zero_of_both(served):
    _, client, _, _ = served
    rid = client.post("/api/researches", json={"question": "How is molecule release scheduling optimized?",
                                               "model_connection": "fake", "requested_model": "fake-model",
                                               "effort": "quick"}).json()["research"]["id"]
    assert awaiting_of(client, rid) == {"queue": 0, "pdf": 0}


# ---- F2: profile ---------------------------------------------------------------------------------------------------


def test_profile_has_the_full_name_and_initials_from_the_account(served, monkeypatch):
    _, client, _, _ = served
    monkeypatch.setattr(shell_routes, "_gecos_name", lambda: "Ada Mary Lovelace")
    assert client.get("/api/profile").json() == {"full_name": "Ada Mary Lovelace", "initials": "AL"}


def test_profile_falls_back_to_id_f_and_then_the_login_name(served, monkeypatch):
    _, client, _, _ = served
    monkeypatch.setattr(shell_routes, "_gecos_name", lambda: "")
    monkeypatch.setattr(shell_routes, "_id_name", lambda: "Hüseyin Yıldız")
    assert client.get("/api/profile").json() == {"full_name": "Hüseyin Yıldız", "initials": "HY"}
    monkeypatch.setattr(shell_routes, "_id_name", lambda: "")
    monkeypatch.setattr(shell_routes, "_login_name", lambda: "adal")
    assert client.get("/api/profile").json() == {"full_name": "adal", "initials": "A"}


# ---- F3: the proxy's label and test --------------------------------------------------------------------------------


def set_proxy(client, address=PROXY):
    assert client.put("/api/institution-proxy", json={"address": address}).status_code == 200


def test_the_label_defaults_to_the_proxy_host_and_can_be_named_and_reset(served):
    _, client, _, _ = served
    assert client.get("/api/institution-proxy/settings").json() | {"label": 0} == {
        "address": None, "label": 0, "label_default": None, "label_is_default": True, "test": None, "test_is_current": False}
    set_proxy(client)
    view = client.get("/api/institution-proxy/settings").json()
    assert view["label"] == view["label_default"] == "proxy.synthetic.example" and view["test"] is None
    named = client.put("/api/institution-proxy/label", json={"label": "  TOBB   library "}).json()
    assert named["label"] == "TOBB library" and named["label_is_default"] is False
    assert client.put("/api/institution-proxy/label", json={"label": ""}).json()["label"] == "proxy.synthetic.example"
    assert client.put("/api/institution-proxy/label", json={"label": "x" * 81}).status_code == 422


@pytest.mark.parametrize("status", [200, 404, 500])
def test_a_proxy_host_that_answers_is_reachable_with_its_status_and_scopus_is_a_second_fact(served, monkeypatch, status):
    _, client, calls, answers = served
    monkeypatch.setenv("SCOPUS_API_KEY", "SECRET")
    set_proxy(client)
    answers[PUBLIC] = httpx.Response(status)
    answers["api.elsevier.com"] = httpx.Response(200, json={})
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert (test["proxy_reachable"], test["proxy_http_status"], test["proxy_error"]) == (True, status, None)
    assert (test["scopus_complete"], test["scopus_configured"]) == ("confirmed", True)
    asked = [request for request in calls if request.url.host == PUBLIC]
    assert len(asked) == 1 and asked[0].method == "GET" and asked[0].headers["host"] == "proxy.synthetic.example"
    assert asked[0].url.path == "/" and not asked[0].url.query  # the host itself, not the login path or any target
    # The stored result comes back from the settings read, current for this address and route.
    again = client.get("/api/institution-proxy/settings").json()
    assert again["test"] == test and again["test_is_current"] is True


@pytest.mark.parametrize("scopus_answer, fact", [
    (httpx.Response(200, json={}), "confirmed"), (httpx.Response(401), "not_confirmed"), (httpx.Response(429), "could_not_check"),
    (httpx.ConnectError("down"), "could_not_check")])
def test_the_scopus_fact_is_passed_through_whatever_the_proxy_answered(served, monkeypatch, scopus_answer, fact):
    _, client, _, answers = served
    monkeypatch.setenv("SCOPUS_API_KEY", "SECRET")
    set_proxy(client)
    answers[PUBLIC] = httpx.ConnectError("no route")
    answers["api.elsevier.com"] = scopus_answer
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert test["scopus_complete"] == fact and test["proxy_reachable"] is False and test["proxy_error"] == "failed"
    assert "working" not in str(test).lower() and "vpn" not in str(test).lower()  # never a combined verdict


def test_without_a_scopus_key_that_fact_is_could_not_check_and_scopus_is_not_asked(served):
    _, client, calls, answers = served
    set_proxy(client)
    answers[PUBLIC] = httpx.Response(200)
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert (test["scopus_complete"], test["scopus_configured"]) == ("could_not_check", False)
    assert [request.url.host for request in calls] == [PUBLIC]


def test_a_proxy_host_that_times_out_did_not_answer(served):
    _, client, _, answers = served
    set_proxy(client)
    answers[PUBLIC] = httpx.ReadTimeout("slow")
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert (test["proxy_reachable"], test["proxy_http_status"], test["proxy_error"]) == (False, None, "timeout")


def test_a_proxy_host_on_a_private_network_is_refused_and_never_asked(served):
    _, client, calls, answers = served
    set_proxy(client)
    answers["resolve"] = ["10.1.2.3"]
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert (test["proxy_reachable"], test["proxy_error"]) == (False, "blocked_url")
    assert "non-public" in test["proxy_error_detail"] and calls == []


def test_a_proxy_host_that_does_not_resolve_did_not_answer(served, monkeypatch):
    _, client, calls, _ = served

    async def unresolved(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(fetch, "_resolve", unresolved)
    set_proxy(client)
    test = client.post("/api/institution-proxy/test").json()["test"]
    assert (test["proxy_reachable"], test["proxy_error"]) == (False, "unresolved") and calls == []


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


# ---- F15: the contact email ----------------------------------------------------------------------------------------


def effective(app):
    return app.state.worker.flow.deps.settings.contact_email


def test_the_contact_email_setting_is_read_before_the_environment_variable(served, monkeypatch):
    app, client, _, _ = served
    assert effective(app) is None
    assert client.get("/api/contact-email").json() == {"email": None, "environment_set": False, "source": None}
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "env@synthetic.example")
    assert effective(app) == "env@synthetic.example"
    assert client.get("/api/contact-email").json()["source"] == "environment"
    saved = client.put("/api/contact-email", json={"email": " me@synthetic.example "}).json()
    assert saved == {"email": "me@synthetic.example", "environment_set": True, "source": "setting"}
    assert effective(app) == "me@synthetic.example"
    cleared = client.put("/api/contact-email", json={"email": ""}).json()
    assert cleared["email"] is None and effective(app) == "env@synthetic.example"


@pytest.mark.parametrize("bad", ["not an email", "a@b", "a b@c.org", "x@y.org,z@y.org", "a" * 250 + "@b.org"])
def test_an_email_that_is_not_an_address_is_refused_and_nothing_is_stored(served, bad):
    _, client, _, _ = served
    assert client.put("/api/contact-email", json={"email": bad}).status_code == 422
    assert client.get("/api/contact-email").json()["email"] is None

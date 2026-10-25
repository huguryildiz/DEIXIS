"""P7-F2 transport accounting. Synthetic records; no network or scientific validation."""

import asyncio
import json
import socket
from inspect import signature

import httpx
import pytest

import connector_baseline as baseline
from deixis.providers import common, registry
from deixis.workflow.search import search_page
from deixis.workflow.search.search_page import Page
from test_connector_contract import dispatch_flow, FIXTURES, body_of, endpoint_fixture
from test_candidate_flow import queue_kill

KEY = baseline.SYNTHETIC_KEY
PUB = endpoint_fixture(FIXTURES["pubmed"], None)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", baseline.deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", baseline.deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", baseline.deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", baseline.deny_network)
    for source in registry.CONNECTORS.values():
        if source.key_env:
            monkeypatch.setenv(source.key_env, KEY)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)


class Script:
    def __init__(self, sequence, total=None):
        self.remaining = list(sequence)
        self.requests = []
        self.total = total

    def __call__(self, request):
        assert self.remaining, "unscripted HTTP attempt"
        stage, ending = self.remaining.pop(0)
        assert request.url.path.endswith(stage + ".fcgi") if stage in {"esearch", "efetch"} else request.url.path == "/search"
        self.requests.append(request)
        if ending in {"connect", "connect_timeout", "read_timeout", "http_error"}:
            error = {"connect": httpx.ConnectError, "connect_timeout": httpx.ConnectTimeout,
                     "read_timeout": httpx.ReadTimeout, "http_error": httpx.WriteError}[ending]
            raise error("SYNTHETIC failure", request=request)
        if ending == "empty":
            return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
        if ending == "malformed":
            return httpx.Response(200, text="SYNTHETIC not JSON")
        if ending == 200:
            if stage == "esearch" and self.total is not None:
                body = json.loads(body_of(PUB))
                body["esearchresult"]["count"] = str(self.total)
                return httpx.Response(200, json=body)
            return httpx.Response(200, text=body_of(PUB, "fetch_" if stage == "efetch" else "") if stage in {"esearch", "efetch"} else "{}")
        return httpx.Response(ending, headers={"retry-after": "0"}, json={"error": "SYNTHETIC error " + KEY})


@pytest.mark.parametrize("ending", ["connect", 401, 200])
def test_send_collects_every_return_and_redacts_url(ending):
    script = Script([("search", ending)])
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(script)) as client:
            with common.collect_transport() as entries:
                _, outcome = await common.send(client, "https://user:password@synthetic.invalid/search?key=" + KEY + "#fragment",
                                               {}, {}, "SYNTHETIC", "api_key", secrets=(KEY,), max_rate_limit_retries=0)
            return outcome, entries
    outcome, entries = asyncio.run(go())
    assert len(entries) == 1
    assert entries[0] == {"url": "https://synthetic.invalid/search", "attempts": 1,
                          "sends": int(ending not in {"connect", "connect_timeout"}), "retries": 0,
                          "status": outcome.status, "http_status": outcome.http_status,
                          "delivery_class": outcome.delivery_class}


def send_page(flow, run, pid, allowance=100, retries=2):
    q = {"provider_id": pid, "query_text": baseline.QUERY}
    page = Page(0, "*", 0, None, 10, retries, "search:0", allowance)
    trace = {}
    # Keep the old flow seam executable for the required failing-first comparison.
    options = {"transport": trace} if "transport" in signature(flow._send_search).parameters else {}
    with baseline.fake_clock():
        sent = asyncio.run(flow._send_search(run["id"], registry.reading(q), q, 1, page, **options))
    step = flow.store.step(run["id"], "search:0", "provider_search:" + pid)
    flow._record_search(run, step, q, sent, 1, page, **options)
    return sent, flow.store.existing_step(run["id"], "search:0"), trace


@pytest.mark.parametrize("query", [None])
def test_settlement_is_atomic_on_failure_between_updates(dispatch_flow, query, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run()
    flow.store.add_usage(run["id"], "provider_requests", 6, query=query)
    before = flow.store.run(run["id"])["usage"]
    original = flow.store.run
    class FailingUsage(dict):
        def __setitem__(self, name, value):
            if name == "provider_sends":
                assert self["provider_requests"] == 2
                if query:
                    assert self["query_requests"][query] == 2
                raise RuntimeError("SYNTHETIC settlement write failure")
            super().__setitem__(name, value)
    def read(run_id):
        result = original(run_id)
        result["usage"] = FailingUsage(result["usage"])
        return result
    monkeypatch.setattr(flow.store, "run", read)
    with pytest.raises(RuntimeError, match="settlement"):
        flow.store.settle_usage(run["id"], query, -4, 2)
    assert flow.store.run(run["id"])["usage"] == before
    monkeypatch.setattr(flow.store, "run", original)
    after = flow.store.settle_usage(run["id"], query, -4, 2)
    assert after["provider_requests"] == after["provider_sends"] == 2


def prepare_kill(lib, pid, *, positions=1):
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", (json.dumps([pid]), lib.rid))
    run = queue_kill(lib)
    q = {"provider_id": pid, "query_text": baseline.QUERY}
    search = lib.candidate_store.start_kill_search(lib.rid, run["target"]["candidate_version_id"], run["id"],
        query_block={"SYNTHETIC": True}, rendered_queries=[dict(q) for _ in range(positions)], skipped_terms=[], selection={})
    step = lib.store.step(run["id"], "search:1", "provider_search:" + pid)
    return run, q, search, step


def kill(lib, run, q, search, step):
    with baseline.fake_clock():
        sent, trace = asyncio.run(lib.flow._kill_search_request(run, q))
    lib.flow._kill_search_record_query(run, search, step, 1, q, sent, trace)
    return lib.store.existing_step(run["id"], "search:1")


@pytest.mark.parametrize("kind", ["missing_key"])
def test_wholly_unsent_discovery_has_no_transport_or_usage(dispatch_flow, monkeypatch, kind):
    flow, new_run = dispatch_flow
    run = new_run()
    if kind == "missing_key":
        monkeypatch.delenv("IEEE_API_KEY")
    else:
        flow._quota_out[run["id"]] = {"ieee_xplore"}
    sent, step, trace = send_page(flow, run, "ieee_xplore")
    assert not trace
    assert "transport" not in (step["output"] or {})
    assert flow.store.run(run["id"])["usage"].get("provider_requests", 0) == 0
    assert flow.store.run(run["id"])["usage"].get("provider_sends", 0) == 0



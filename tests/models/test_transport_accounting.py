"""P7-F2 transport accounting. Synthetic records; no network or scientific validation."""

import asyncio
import json
import math
import socket
from dataclasses import replace
from inspect import signature

import httpx
import pytest

import connector_baseline as baseline
import fast_search_helpers as fast
from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES, PROVIDER_WAIT, SW_READ_LIMIT
from deixis.providers import common, contract, facade, registry
from deixis.workflow import flow as module
from deixis.workflow.flow import Page, page_allowance
from test_connector_contract import dispatch_flow, candidate_lib, FIXTURES, body_of, endpoint_fixture
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


PUBMED_CASES = [
    ([("esearch", "empty")], 1, 1, 0),
    ([("esearch", 200), ("efetch", 200)], 2, 2, 0),
    ([("esearch", 429), ("esearch", 200), ("efetch", 429), ("efetch", 429), ("efetch", 200)], 5, 5, 3),
    ([("esearch", 200), ("efetch", 500)], 2, 2, 0),
    ([("esearch", 200), ("efetch", "connect")], 2, 1, 0),
    ([("esearch", "connect")], 1, 0, 0),
    ([("esearch", "malformed")], 1, 1, 0),
]


@pytest.mark.parametrize("sequence,attempts,sends,retries", PUBMED_CASES)
def test_pubmed_collector_keeps_stages(sequence, attempts, sends, retries):
    script = Script(sequence)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(script)) as client:
            return await facade.dispatch_search("pubmed", client, baseline.QUERY, 1, KEY, baseline.CONTACT)
    with baseline.fake_clock():
        result = asyncio.run(go())
    assert not script.remaining
    entries = result.transport
    assert sum(e["attempts"] for e in entries) == attempts
    assert sum(e["sends"] for e in entries) == sends
    assert sum(e["retries"] for e in entries) == result.outcome.retries == retries
    assert len(entries) == (2 if any(s == "efetch" for s, _ in sequence) else 1)
    assert entries[0]["url"].endswith("esearch.fcgi")
    if len(entries) == 2:
        assert (entries[0]["status"], entries[0]["http_status"]) == ("completed", 200)
        assert entries[1]["url"].endswith("efetch.fcgi")
    assert KEY not in json.dumps(entries) and all("?" not in e["url"] for e in entries)


@pytest.mark.parametrize("ending", ["connect", "connect_timeout", "read_timeout", "http_error", 401, 403, 500, 429, 200])
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


def test_collector_redacts_secret_in_path():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
            with common.collect_transport() as entries:
                await common.send(client, "https://synthetic.invalid/" + KEY, {}, {}, "SYNTHETIC", "api_key", secrets=(KEY,))
            return entries
    assert asyncio.run(go())[0]["url"] == "https://synthetic.invalid/<redacted>"


def test_collector_isolated_between_tasks_and_reset_after_raise(monkeypatch):
    async def adapter(http, *args, **kwargs):
        await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless")
        raise KeyError("SYNTHETIC adapter failure")
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(registry.CONNECTORS["openalex"], search=adapter))
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
            with common.collect_transport() as outer:
                with pytest.raises(KeyError):
                    await facade.dispatch_search("openalex", client, baseline.QUERY, 1, None, baseline.CONTACT)
                await common.send(client, "https://synthetic.invalid/outer", {}, {}, "SYNTHETIC", "keyless")
            async def collect(path):
                with common.collect_transport() as entries:
                    await asyncio.sleep(0)
                    await common.send(client, "https://synthetic.invalid/" + path, {}, {}, "SYNTHETIC", "keyless")
                    return entries
            return outer, await asyncio.gather(collect("a"), collect("b"))
    outer, parallel = asyncio.run(go())
    assert [e["url"] for e in outer] == ["https://synthetic.invalid/outer"]
    assert [[e["url"] for e in entries] for entries in parallel] == [["https://synthetic.invalid/a"], ["https://synthetic.invalid/b"]]


@pytest.mark.parametrize("pid,endpoint", [(pid, e.endpoint_id) for pid, f in facade.connectors().items() for e in f.descriptor.endpoints])
def test_raising_before_send_has_zero_entries(pid, endpoint):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as client:
            with common.collect_transport() as entries:
                with pytest.raises(contract.ContractViolation):
                    await facade.connectors()[pid].search(contract.SearchRequest(baseline.QUERY, 0, endpoint=endpoint),
                                                         contract.ConnectorContext(client, KEY, baseline.CONTACT))
                assert entries == []
                with pytest.raises(contract.ContractViolation):
                    await facade.dispatch_search(pid, client, baseline.QUERY, 0, KEY, baseline.CONTACT, endpoint=endpoint)
                assert entries == []
    asyncio.run(go())


def use_client(flow, script):
    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(script))


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


@pytest.mark.parametrize("sequence,attempts,sends,retries", PUBMED_CASES)
def test_discovery_pubmed_counts_and_step_provenance(dispatch_flow, sequence, attempts, sends, retries):
    flow, new_run = dispatch_flow
    run = new_run(("pubmed",))
    script = Script(sequence)
    use_client(flow, script)
    # Connect failures exhaust this share on the first dispatch, avoiding a second scripted operation.
    sent, step, trace = send_page(flow, run, "pubmed", allowance=1 if any(e == "connect" for _, e in sequence) else 100)
    usage = flow.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == usage["query_requests"]["search:0"] == attempts
    assert usage["provider_sends"] == sends
    assert step["output"]["transport"] == trace
    assert trace["reserved"] == 6 and trace["attempts"] == attempts and trace["sends"] == sends
    assert len(trace["dispatches"]) == 1 and not script.remaining
    if any(s == "efetch" for s, _ in sequence):
        assert trace["dispatches"][0]["subrequests"][0]["status"] == "completed"
    assert step["status"] == ("succeeded" if sequence[-1][1] in {200, "empty"} else "outcome_unknown" if sequence[-1][1] == 500 else "failed")


def test_discovery_reservation_visible_in_flight_and_settled(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("pubmed",))
    async def go():
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            flow.deps.http = client
            page = Page(0, "*", 0, None, 10, 1, "search:0", 10)
            task = asyncio.create_task(flow._send_search(run["id"], registry.CONNECTORS["pubmed"], {"query_text": baseline.QUERY}, 1, page))
            await entered.wait()
            usage = flow.store.run(run["id"])["usage"]
            assert usage["provider_requests"] == usage["query_requests"]["search:0"] == 4
            assert usage.get("provider_sends", 0) == 0
            release.set()
            await task
    asyncio.run(go())
    usage = flow.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == usage["query_requests"]["search:0"] == usage["provider_sends"] == 1


@pytest.mark.parametrize("query", [None, "search:0"])
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


def synthetic_adapter(monkeypatch, *, stages=1, drop="none", pid="synthetic", declared=1):
    async def search(http, query, limit, key, contact, **kwargs):
        outcomes = []
        for _ in range(stages):
            _, outcome = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless",
                                           max_rate_limit_retries=kwargs.get("max_rate_limit_retries", 2))
            outcomes.append(outcome)
        if drop == "everything":
            return common.SearchOutcome("zero_results", None, "SYNTHETIC fresh", "keyless")
        if drop == "second":
            return outcomes[0]
        return outcomes[-1]
    source = replace(registry.CONNECTORS["openalex"], provider_id=pid, search=search,
                     host="synthetic.invalid", key_env=None, key_required=False, requests_per_search=declared)
    monkeypatch.setitem(registry.CONNECTORS, pid, source)
    return source


@pytest.mark.parametrize("sequence,attempts,sends", [([429, 429, 200], 3, 3), (["connect", 200], 2, 1)])
def test_single_request_sequences_preserve_attempt_counts(dispatch_flow, monkeypatch, sequence, attempts, sends):
    flow, new_run = dispatch_flow
    synthetic_adapter(monkeypatch)
    run = new_run()
    script = Script([("search", s) for s in sequence])
    use_client(flow, script)
    _, step, trace = send_page(flow, run, "synthetic")
    usage = flow.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == usage["query_requests"]["search:0"] == attempts
    assert usage["provider_sends"] == sends and not script.remaining
    assert trace["reserved"] == (6 if sequence[0] == "connect" else 3)
    assert step["output"]["transport"]["attempts"] == attempts


@pytest.mark.parametrize("pid", list(registry.CONNECTORS))
def test_spent_share_prevents_transient_redispatch(dispatch_flow, pid):
    flow, new_run = dispatch_flow
    run = new_run((pid,))
    flow.store.add_usage(run["id"], "provider_requests", 2, query="search:0")
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ConnectError("SYNTHETIC", request=request)
    use_client(flow, handler)
    with baseline.fake_clock():
        sent = asyncio.run(flow._send_search(run["id"], registry.CONNECTORS[pid], {"query_text": baseline.QUERY}, 1,
                                           Page(0, "*", 0, None, 10, 1, "search:0", 3)))
    assert len(requests) == 1 and sent.outcome.delivery_class == "before_send"
    assert flow.store.run(run["id"])["usage"]["query_requests"]["search:0"] == 3


@pytest.mark.parametrize("effort", ["quick", "standard", "detailed"])
@pytest.mark.parametrize("pid", ["pubmed", "crossref"])
def test_page_allowance_uses_declared_base_cost(pid, effort):
    source = registry.CONNECTORS[pid]
    pages = math.ceil(min(SW_READ_LIMIT[effort], source.max_reachable or SW_READ_LIMIT[effort]) / source.max_results)
    expected = pages * (source.requests_per_search * (1 + PROVIDER_WAIT[effort]) + MAX_TRANSIENT_NETWORK_RETRIES) + 1
    assert page_allowance({"provider_id": pid}, effort, {"retry_provider_requests": 1}) == expected


def test_pubmed_read_stops_at_corrected_budget_and_carries_trace(dispatch_flow, monkeypatch):
    # PubMed is not a fast-path discovery source; its two-stage request only stands in for a paged slot whose
    # pages cost two requests each.
    flow, new_run = dispatch_flow
    run = new_run(("pubmed",))
    monkeypatch.setattr(module, "page_allowance", lambda *args: 3)
    script = Script([("esearch", 200), ("efetch", 200)] * 2, total=100)
    use_client(flow, script)
    with baseline.fake_clock():
        asyncio.run(fast.search(flow, run, [{"provider_id": "pubmed", "query_text": baseline.QUERY}], cap=100, page_size=1))
    steps = fast.provider_steps(flow, run)
    assert [s["operation_key"] for s in steps] == ["search:0", "search:0:page:1"]
    assert steps[-1]["output"]["stop_reason"] == "budget_exhausted"
    usage = flow.store.run(run["id"])["usage"]
    assert usage["query_requests"]["search:0"] == 4 <= 3 - 1 + 4
    assert usage["provider_requests"] == usage["provider_sends"] == 4
    assert all(s["output"]["transport"]["attempts"] == 2 for s in steps)
    assert not script.remaining


def test_missing_key_after_dispatch_keeps_trace_on_failed_page(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run()
    reads = []
    monkeypatch.setattr(registry.Connector, "api_key", lambda self: reads.append(True) or (KEY if len(reads) == 1 else None))
    script = Script([("search", "connect")])
    async def search(http, *args, **kwargs):
        _, outcome = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "api_key")
        return outcome
    monkeypatch.setitem(registry.CONNECTORS, "ieee_xplore", replace(registry.CONNECTORS["ieee_xplore"], search=search))
    use_client(flow, script)
    _, step, _ = send_page(flow, run, "ieee_xplore", retries=1)
    assert step["status"] == "failed" and step["output"]["status"] == "not_configured"
    assert step["output"]["transport"] == {"reserved": 2, "attempts": 1, "sends": 0,
        "dispatches": [{"subrequests": [{"url": "https://synthetic.invalid/search", "attempts": 1, "sends": 0,
            "retries": 0, "status": "failed", "http_status": None, "delivery_class": "before_send"}]}]}
    assert flow.store.conn.execute("SELECT count(*) FROM search_runs").fetchone()[0] == 0
    assert flow.store.run(run["id"])["usage"]["provider_requests"] == 1


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


@pytest.mark.parametrize("sequence,attempts,sends,retries", PUBMED_CASES[:4])
def test_kill_pubmed_reservation_and_observed_sends(candidate_lib, sequence, attempts, sends, retries):
    lib = candidate_lib
    run, q, search, step = prepare_kill(lib, "pubmed")
    script = Script(sequence)
    use_client(lib.flow, script)
    saved = kill(lib, run, q, search, step)
    usage = lib.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == 6 and usage["provider_sends"] == sends <= 6
    assert "query_requests" not in usage
    trace = saved["output"]["transport"]
    assert trace["reserved"] == 6 and trace["attempts"] == attempts and trace["sends"] == sends
    assert not script.remaining


@pytest.mark.parametrize("ending", ["budget", "missing_key"])
def test_kill_later_refusal_keeps_earlier_dispatch(candidate_lib, monkeypatch, ending):
    lib = candidate_lib
    run, q, search, step = prepare_kill(lib, "pubmed")
    if ending == "budget":
        run["budget"]["max_provider_requests"] = 6
    reads = []
    if ending == "missing_key":
        monkeypatch.setitem(registry.CONNECTORS, "pubmed", replace(registry.CONNECTORS["pubmed"], key_required=True))
        monkeypatch.setattr(registry.Connector, "api_key", lambda self: reads.append(True) or (KEY if len(reads) == 1 else None))
    script = Script([("esearch", 200), ("efetch", "connect")])
    use_client(lib.flow, script)
    saved = kill(lib, run, q, search, step)
    assert saved["output"]["status"] == ("transport_budget" if ending == "budget" else "not_configured")
    trace = saved["output"]["transport"]
    assert trace["reserved"] == 6 and trace["attempts"] == 2 and trace["sends"] == 1
    assert trace["dispatches"][0]["subrequests"][0]["status"] == "completed"
    usage = lib.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == 6 and usage["provider_sends"] == 1


def test_kill_identical_queries_keep_separate_handoffs(candidate_lib):
    lib = candidate_lib
    run, q, search, first_step = prepare_kill(lib, "pubmed")
    second_step = lib.store.step(run["id"], "search:2", "provider_search:pubmed")
    script = Script([("esearch", 429), ("esearch", "empty"), ("esearch", "empty")])
    use_client(lib.flow, script)
    with baseline.fake_clock():
        first = asyncio.run(lib.flow._kill_search_request(run, q))
        second = asyncio.run(lib.flow._kill_search_request(run, q))

    # Replay the pre-fix seam too: its shared key overwrites the first request's trace.
    for position, step, result in ((1, first_step, first), (2, second_step, second)):
        outcome, trace = result if isinstance(result, tuple) else (result, None)
        options = {"transport": trace} if "transport" in signature(lib.flow._kill_search_record_query).parameters else {}
        lib.flow._kill_search_record_query(run, search, step, position, q, outcome, **options)
        saved = lib.store.existing_step(run["id"], f"search:{position}")
        trace = saved["output"]["transport"]
        assert trace["reserved"] == 6
        assert trace["attempts"] == trace["sends"] == (2 if position == 1 else 1)
    usage = lib.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == 12 and usage["provider_sends"] == 3
    assert not script.remaining
    assert not hasattr(lib.flow, "_kill_search_transport")


@pytest.mark.parametrize("recovered", [False, True])
def test_kill_loop_keeps_duplicate_positions_and_recovered_trace_absent(candidate_lib, recovered):
    lib = candidate_lib
    # The compiler emits one query per provider, but stored query positions can share text.
    run, q, search, first_step = prepare_kill(lib, "pubmed", positions=2)
    if recovered:
        lib.store.finish_step(first_step["id"], "outcome_unknown", error_code="timeout",
                              delivery_class="after_send_unknown")
    script = Script(([("esearch", 429), ("esearch", "empty")] if not recovered else []) + [("esearch", "empty")])
    use_client(lib.flow, script)
    with baseline.fake_clock():
        asyncio.run(lib.flow._kill_search(run, lib.store.scope(lib.rid)))
    queries = lib.candidate_store.queries(search["id"])
    assert [(row["position"], row["provider"], row["query_text"]) for row in queries] == [
        (1, "pubmed", q["query_text"]), (2, "pubmed", q["query_text"])]
    first = lib.store.existing_step(run["id"], "search:1")
    second = lib.store.existing_step(run["id"], "search:2")
    if recovered:
        assert first["status"] == "outcome_unknown" and "transport" not in first["output"]
    else:
        assert first["output"]["transport"]["attempts"] == first["output"]["transport"]["sends"] == 2
    assert second["output"]["transport"]["attempts"] == second["output"]["transport"]["sends"] == 1
    assert not script.remaining


@pytest.mark.parametrize("path", ["discovery", "kill"])
@pytest.mark.parametrize("drop", ["everything", "second"])
def test_rebuilt_adapter_outcome_cannot_refund_transport(dispatch_flow, candidate_lib, monkeypatch, path, drop):
    synthetic_adapter(monkeypatch, stages=2, drop=drop, declared=2)
    script = Script([("search", 200), ("search", 200)])
    if path == "discovery":
        flow, new_run = dispatch_flow
        run = new_run()
        use_client(flow, script)
        _, saved, _ = send_page(flow, run, "synthetic")
        usage = flow.store.run(run["id"])["usage"]
        assert usage["provider_requests"] == usage["query_requests"]["search:0"] == 2
    else:
        lib = candidate_lib
        run, q, search, step = prepare_kill(lib, "synthetic")
        use_client(lib.flow, script)
        saved = kill(lib, run, q, search, step)
        usage = lib.store.run(run["id"])["usage"]
        assert usage["provider_requests"] == 6
    assert usage["provider_sends"] == 2
    assert saved["output"]["transport"]["attempts"] == 2
    assert len(saved["output"]["transport"]["dispatches"][0]["subrequests"]) == 2


@pytest.mark.parametrize("path", ["discovery", "kill"])
def test_declared_cost_excess_is_charged_and_recorded(dispatch_flow, candidate_lib, monkeypatch, path):
    synthetic_adapter(monkeypatch, stages=2)
    script = Script([("search", 429), ("search", 200)] * 2)
    if path == "discovery":
        flow, new_run = dispatch_flow
        run = new_run()
        use_client(flow, script)
        _, saved, _ = send_page(flow, run, "synthetic", retries=1)
        usage = flow.store.run(run["id"])["usage"]
        reserve, excess = 2, 2
        assert usage["query_requests"]["search:0"] == 4
    else:
        lib = candidate_lib
        run, q, search, step = prepare_kill(lib, "synthetic")
        use_client(lib.flow, script)
        saved = kill(lib, run, q, search, step)
        usage = lib.store.run(run["id"])["usage"]
        reserve, excess = 3, 1
    assert usage["provider_requests"] == 4
    assert usage["provider_sends"] == 4
    trace = saved["output"]["transport"]
    assert trace["reserved"] == reserve and trace["over_reservation"] == excess and trace["attempts"] == trace["sends"] == 4
    assert not script.remaining


@pytest.mark.parametrize("pid", ["pubmed", "synthetic"])
def test_discovery_tight_share_minus_one_plus_reservation_bound(dispatch_flow, monkeypatch, pid):
    flow, new_run = dispatch_flow
    if pid == "synthetic":
        synthetic_adapter(monkeypatch)
    run = new_run()
    share = 3
    flow.store.add_usage(run["id"], "provider_requests", share - 1, query="search:0")
    monkeypatch.setattr(module, "page_allowance", lambda *args: share)
    stages = ["esearch", "efetch"] if pid == "pubmed" else ["search"]
    script = Script([(s, code) for s in stages for code in [429, 200]], total=100)
    use_client(flow, script)
    q = {"provider_id": pid, "query_text": baseline.QUERY}
    with baseline.fake_clock():
        asyncio.run(fast.search(flow, run, [q], cap=100, page_size=1))
    reserve = registry.CONNECTORS[pid].requests_per_search * 2
    assert flow.store.run(run["id"])["usage"]["query_requests"]["search:0"] == share - 1 + reserve
    steps = fast.provider_steps(flow, run)
    assert len(steps) == 1 and not script.remaining
    assert steps[0]["output"]["transport"]["attempts"] == reserve
    # The read ended on the spent share or the last page: a second pass, retrying failed searches, sends nothing.
    use_client(flow, baseline.deny_network)
    asyncio.run(fast.search(flow, run, [q], True, cap=100, page_size=1))
    assert fast.provider_steps(flow, run) == steps


@pytest.mark.parametrize("kind", ["missing_key", "quota"])
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


def test_stop_in_transient_backoff_keeps_usage_without_step(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    synthetic_adapter(monkeypatch)
    run = new_run()
    script = Script([("search", "connect")])
    use_client(flow, script)
    with baseline.fake_clock():
        sent = asyncio.run(flow._send_search(run["id"], registry.CONNECTORS["synthetic"], {"query_text": baseline.QUERY},
                                           1, Page(0, "*", 0, None, 10, 1, "search:0", 10), stop=lambda: True))
    assert sent is None and not flow.store.run_steps(run["id"])
    usage = flow.store.run(run["id"])["usage"]
    assert usage["provider_requests"] == usage["query_requests"]["search:0"] == 1 and usage["provider_sends"] == 0

"""SYNTHETIC B4 dispatch, named changes and stored continuation boundaries.

Old-code behavioral cases use pre-B4 flow/lookup entry points. Direct facade
equivalence remains separate from admission, secrecy and version refusal.
"""

import asyncio
import copy
import json
import shutil
import socket
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import connector_baseline as baseline
import test_connector_contract as conformance
import test_connector_facade as equality
from test_connector_contract import dispatch_flow, candidate_lib, prepare_kill
from test_provider_records import record
from deixis.providers import common, contract, facade, lookup, registry
from deixis.storage import db
from deixis.domain import canonical
from deixis.workflow import flow as flow_module, lookups
from deixis.workflow.flow import Page, _QueryRead


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", baseline.deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", baseline.deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", baseline.deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", baseline.deny_network)
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.setenv(connector.key_env, baseline.SYNTHETIC_KEY)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)


def client(flow, handler):
    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def query(pid="openalex", **fields):
    return {"provider_id": pid, "query_text": baseline.QUERY, **fields}


def rows(flow):
    return [dict(r) for r in flow.store.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]


def install(monkeypatch, pid, search, **fields):
    source = replace(registry.CONNECTORS[pid], search=search, **fields)
    monkeypatch.setitem(registry.CONNECTORS, pid, source)
    return source


def record_sent(flow, run, q, *, key="search:0", page=None):
    sent = asyncio.run(flow._send_search(run["id"], registry.reading(q), q, 2, page))
    step = flow.store.step(run["id"], key, f"provider_search:{q['provider_id']}")
    failure = flow._record_search(run, step, q, sent, 2, page)
    return sent, flow.store.existing_step(run["id"], key), failure


def oa_body(ids=("https://openalex.org/W1",), cursor=None, secret=None):
    body = json.loads(equality.native_script("openalex", None, conformance.FIXTURES["openalex"])[0][2])
    first = body["results"][0]
    body["results"] = [dict(first, id=i, doi=None) for i in ids]
    body["meta"]["next_cursor"] = cursor
    if secret:
        body["results"][0]["SYNTHETIC_nested"] = {"key": f"before/{secret}/after"}
    return body


# Decision 1: reuse B3a's enumeration, including every registry-declared endpoint.
def test_dispatched_has_no_attribute_fallback():
    outcome = common.SearchOutcome("completed", None, "SYNTHETIC", "keyless", records=[record("W1")])
    dispatched = facade.Dispatched(outcome, 2, {})
    assert dispatched.outcome is outcome and dispatched.returned_count == 3
    with pytest.raises(AttributeError):
        _ = dispatched.status


@pytest.mark.parametrize("provider_id,kind,q,cursor_kind,retries,limited", equality.DISPATCH_SHAPES)
@pytest.mark.parametrize("script_kind", ["positive", "429"])
def test_dispatch_equivalence(provider_id, kind, q, cursor_kind, retries, limited, script_kind):
    source = registry.CONNECTORS[provider_id]
    eid = q.get("endpoint") if kind != "legacy" else None
    fixture = conformance.FIXTURES[provider_id]
    script = equality.native_script(provider_id, eid, fixture)
    positive = next(c for c in conformance.endpoint_fixture(fixture, eid)["cases"] if c["name"] == "positive")
    limit = max(1, len(positive["expected"]["records"]))
    kwargs = registry.endpoint_options(q) if kind == "kill" else {}
    if kind == "paged":
        first_kw = {"cursor": common.FIRST_PAGE, "max_rate_limit_retries": retries,
                    **source.sw_options, **registry.endpoint_options(q)}
        first = equality.replay_script(provider_id, eid, fixture, first_kw, script, direct=True, limit=limit)[0]
        cursor = common.FIRST_PAGE if cursor_kind == "first" else (
            "ignored" if equality.endpoint_for(provider_id, eid).paging == "single_page" else first.next_cursor)
        kwargs = first_kw | {"cursor": cursor}
    if script_kind == "429":
        allowance = retries if kind == "paged" else equality.endpoint_for(provider_id, eid).retry.max_rate_limit_retries
        script = equality.refusals(script, 1 + allowance)
    direct = equality.replay_script(provider_id, eid, fixture, kwargs, script, direct=True, limit=limit)
    requests, remaining = [], list(script)

    def transport(request):
        url, status, body = remaining.pop(0)
        assert str(request.url.copy_with(query=None)) == url
        requests.append(request)
        return httpx.Response(status, text=body)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await facade.dispatch_search(provider_id, http, baseline.QUERY, limit,
                baseline.SYNTHETIC_KEY if source.key_env else None, baseline.CONTACT, **kwargs)

    with baseline.fake_clock() as waits:
        dispatched = asyncio.run(run())
    assert not remaining and dispatched.dropped_records == 0
    assert equality.measured(direct) == equality.measured((dispatched.outcome, requests, waits))


def test_workflow_contains_no_registry_search_call():
    root = Path(flow_module.__file__).parent
    assert not [p.name for p in root.rglob("*.py") if "connector.search(" in p.read_text()]


def test_send_spy_and_snapshot(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    reads, calls = [], []
    keys = [baseline.SYNTHETIC_KEY, "SYNTHETIC-later-key"]
    monkeypatch.setattr(registry.Connector, "api_key", lambda self: reads.append(True) or keys[min(len(reads)-1, 1)])
    original = facade.CompatibilityConnector.search
    async def spy(self, request, context):
        calls.append((request, context.api_key))
        return await original(self, request, context)
    monkeypatch.setattr(facade.CompatibilityConnector, "search", spy)
    client(flow, lambda r: httpx.Response(200, json=oa_body()))
    record_sent(flow, run, query())
    assert len(reads) == 1 and len(calls) == 1 and calls[0][1] == keys[0]


def test_kill_spy_and_snapshot(candidate_lib, monkeypatch):
    lib = candidate_lib
    run, q, search, step = prepare_kill(lib, monkeypatch)
    reads, calls = [], []
    monkeypatch.setattr(registry.Connector, "api_key", lambda self: reads.append(True) or (
        baseline.SYNTHETIC_KEY if len(reads) == 1 else None))
    original = facade.CompatibilityConnector.search
    async def spy(self, request, context):
        calls.append(context.api_key)
        return await original(self, request, context)
    monkeypatch.setattr(facade.CompatibilityConnector, "search", spy)
    client(lib.flow, lambda r: httpx.Response(200, json={"articles": []}))
    sent, trace = asyncio.run(lib.flow._kill_search_request(run, q))
    lib.flow._kill_search_record_query(run, search, step, 1, q, sent, trace)
    assert reads == [True] and calls == [baseline.SYNTHETIC_KEY]


def test_synthetic_registry_dispatch_and_record(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    seen = []
    async def search(http, text, limit, key, contact, **kwargs):
        response, _ = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless")
        return common.SearchOutcome("completed", None, "SYNTHETIC", "keyless",
                                    records=[record("synthetic-id", doi=None)], raw_payload=response.json())
    synthetic = registry.Connector("synthetic_dispatch", search, 2, host="synthetic.invalid", paging="single_page")
    monkeypatch.setitem(registry.CONNECTORS, synthetic.provider_id, synthetic)
    client(flow, lambda r: seen.append(r.url.host) or httpx.Response(200, json={"SYNTHETIC": True}))
    sent, step, failure = record_sent(flow, run, query(synthetic.provider_id))
    assert seen == ["synthetic.invalid"] and step["status"] == "succeeded" and failure is None
    assert rows(flow)[0]["provider"] == synthetic.provider_id and len(flow.store.candidates(run["research_id"])) == 1
    assert sent.connector["adapter_revision"] == synthetic.adapter_revision


def test_b2_key_removed_after_freeze_never_reaches_facade(tmp_path, monkeypatch):
    original = facade.CompatibilityConnector.search
    calls = []
    async def spy(self, request, context):
        calls.append(self.descriptor.provider_id)
        return await original(self, request, context)
    monkeypatch.setattr(facade.CompatibilityConnector, "search", spy)
    conformance.test_dispatched_missing_key_after_freeze_sends_nothing_and_records_a_step(tmp_path, monkeypatch, None)
    assert calls and "serpapi" not in calls


# Named change 1: behavior through pre-B4 entry points, so the old harness bites.
@pytest.mark.parametrize("kind", ["quota_exhausted", "rate_limited"])
def test_limit_record_and_pause(dispatch_flow, kind):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    outcome = common.SearchOutcome("rate_limited", "rejected_not_executed", "SYNTHETIC", "api_key",
                                  http_status=429, error_kind=kind)
    step = flow.store.step(run["id"], "limit", "provider_search:openalex")
    failure = flow._record_search(run, step, query(), outcome, 2)
    saved = flow.store.existing_step(run["id"], "limit")
    assert rows(flow)[0]["status"] == saved["error_code"] == "rate_limited"
    assert json.loads(rows(flow)[0]["error_json"])["error_kind"] == json.loads(saved["error_json"])["error_kind"] == kind
    assert failure[0] == ("provider_quota_exhausted" if kind == "quota_exhausted" else "provider_rate_limited")
    assert rows(flow)[0]["connector_json"] is None


@pytest.mark.parametrize("kind", ["quota_exhausted", "rate_limited"])
def test_limit_discovery_and_suppression(dispatch_flow, monkeypatch, kind):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    seen = []
    def transport(r):
        seen.append(r)
        return httpx.Response(429, json={"error": "SYNTHETIC daily quota exhausted"} if kind == "quota_exhausted"
                              else {"error": "SYNTHETIC temporary refusal"})
    client(flow, transport)
    async def discovery(current, scope):
        failure = await flow._search_round(current, [(0, query()), (1, query())], False, "standard")
        if failure:
            flow._pause(current["id"], *failure)
    monkeypatch.setattr(flow, "_discovery", discovery)
    with baseline.fake_clock():
        asyncio.run(flow.execute(run["id"]))
    current = flow.store.run(run["id"])
    assert current["status"] == "paused"
    assert current["pause_reason"] == ("provider_quota_exhausted" if kind == "quota_exhausted" else "provider_rate_limited")
    for row in rows(flow):
        step = flow.store.existing_step(run["id"], f"search:{rows(flow).index(row)}")
        assert row["status"] == step["error_code"] == "rate_limited"
        assert json.loads(row["error_json"])["error_kind"] == json.loads(step["error_json"])["error_kind"] == kind
    if kind == "quota_exhausted":
        assert len(seen) == 1 and rows(flow)[1]["connector_json"] is None
        assert current["usage"]["provider_requests"] == 1


def test_chain_limit_error(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    step = flow.store.step(run["id"], "chain:backward:0", "provider_chain:openalex")
    outcome = common.SearchOutcome("rate_limited", "rejected_not_executed", "SYNTHETIC", "keyless",
                                  error_kind="quota_exhausted")
    flow._record_chain(run, step, "chain:backward:0", "backward", outcome, {}, [], cites=None, page=None)
    saved = flow.store.existing_step(run["id"], "chain:backward:0")
    assert json.loads(rows(flow)[0]["error_json"])["error_kind"] == "quota_exhausted"
    assert json.loads(saved["error_json"])["error_kind"] == "quota_exhausted"


def test_kill_limit_error(candidate_lib, monkeypatch):
    lib = candidate_lib
    run, q, search, step = prepare_kill(lib, monkeypatch)
    client(lib.flow, lambda r: httpx.Response(403, json={"error": "SYNTHETIC daily quota exhausted"}))
    sent, trace = asyncio.run(lib.flow._kill_search_request(run, q))
    lib.flow._kill_search_record_query(run, search, step, 1, q, sent, trace)
    saved = lib.store.existing_step(run["id"], "kill-search:1")
    assert saved["error_code"] == "rate_limited" and json.loads(saved["error_json"])["error_kind"] == "quota_exhausted"


# Named change 2: explicit identifier ownership, independently of dispatch.
A, B, C, X = [f"10.1/synthetic.{s}" for s in "abcx"]
def paper(doi, **fields):
    return {"externalIds": {"DOI": doi}, "abstract": f"SYNTHETIC abstract {doi}", **fields}


BINDINGS = [
    ([A, B], [paper(B), paper(A)], ["found", "found"]),
    ([A, B, C], [paper(C), paper(A), paper(B)], ["found"] * 3),
    ([A, B], [paper(X), paper(A)], ["found", "failed"]),
    ([A, B], [paper(A), paper(X)], ["found", "failed"]),
    ([A, B], [paper(A), paper(A, abstract="SYNTHETIC conflicting abstract")], ["failed", "failed"]),
    ([A, B], [None, paper(B)], ["not_found", "found"]),
    ([A, B, C], [None, paper(C), paper(B)], ["failed", "found", "found"]),
    ([A, B], [paper(A), {"externalIds": []}], ["found", "failed"]),
    ([A, B], [paper(A), {"externalIds": {"DOI": 17}}], ["found", "failed"]),
    ([A, B], [paper(A), {"externalIds": {"DOI": " "}}], ["found", "failed"]),
    ([A, B], [17, paper(B)], ["failed", "found"]),
    ([A, A], [paper(A), dict(reversed(list(paper(A).items())))], ["found", "found"]),
    ([A, A], [paper(A), paper(A, abstract="SYNTHETIC conflicting abstract")], ["failed", "failed"]),
    ([A, A], [None, None], ["not_found", "not_found"]),
    ([A, B, A], [paper(B), None, paper(A)], ["found", "found", "found"]),
]
@pytest.mark.parametrize("dois,payload,statuses", BINDINGS,
                         ids=["reorder2", "reorder3", "X-A", "A-X", "duplicate", "ordered-null",
                              "reordered-null", "external-list", "external-number", "external-blank", "item-number",
                              "repeated-equal", "repeated-conflict", "repeated-null", "repeated-reordered"])
def test_s2_binding(dois, payload, statuses):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
            return await lookup.semantic_scholar_batch(http, dois, baseline.SYNTHETIC_KEY)
    with baseline.fake_clock():
        answers, outcome = asyncio.run(run())
    assert outcome.status == "completed" and [answers[d].status for d in dois] == statuses
    assert outcome.raw_payload["answers"] == payload
    if len(set(dois)) == 1:
        assert outcome.error == ("unbound answers: 0; ambiguous answers: 2" if statuses[0] == "failed" else None)
    for doi in dois:
        if answers[doi].status == "found":
            assert answers[doi].abstract == f"SYNTHETIC abstract {doi}" and answers[doi].linked_dois == []
    if any(isinstance(item, dict) and item.get("externalIds", {}).get("DOI") == X
           for item in payload if isinstance(item, dict) and isinstance(item.get("externalIds"), dict)):
        assert outcome.error == "unbound answers: 1; ambiguous answers: 0"


@pytest.mark.parametrize("external", [" AbC.123v3 ", "abc.123", "ABC.123V42"])
def test_s2_arxiv_publication_relation(external):
    doi = "10.48550/arxiv.abc.123"
    payload = paper(A, externalIds={"ArXiv": external, "DOI": A})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[payload]))) as http:
            return await lookup.semantic_scholar_batch(http, [doi])
    with baseline.fake_clock():
        answers, _ = asyncio.run(run())
    assert answers[doi].status == "found" and answers[doi].linked_dois == [A]


def lookup_sources(flow, run, dois):
    for i, doi in enumerate(dois):
        flow.store.upsert_provider_source("openalex", record(f"W{i}", doi=doi), None)
    return [{"source_version_id": flow.store.find_source_by_identifier("openalex", f"W{i}"), "doi": doi}
            for i, doi in enumerate(dois)]


def test_s2_workflow_reordered_abstracts(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "semantic_scholar"))
    batch = lookup_sources(flow, run, [A, B])
    client(flow, lambda r: httpx.Response(200, json=[paper(B), paper(A)]))
    asyncio.run(lookups._semantic_scholar_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    for item in batch:
        texts = [p["text"] for p in flow.store.passages_for(item["source_version_id"])]
        assert texts == [f"SYNTHETIC abstract {item['doi']}"]


# Named change 3: persisted file and canonical digest, using old flow entry points.
def test_payload_echo_recorded(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    payload = oa_body(secret=baseline.SYNTHETIC_KEY)
    client(flow, lambda r: httpx.Response(200, json=payload))
    sent, step, _ = record_sent(flow, run, query())
    row = rows(flow)[0]
    stored = json.loads((flow.deps.settings.payloads_dir / row["raw_payload_path"]).read_text())
    assert baseline.SYNTHETIC_KEY not in json.dumps(stored)
    assert row["payload_sha256"] == canonical.sha256_hex(stored)
    assert stored["results"][0]["SYNTHETIC_nested"]["key"] == "before/<redacted>/after"
    assert baseline.SYNTHETIC_KEY not in row["payload_sha256"]


def test_record_raw_only_is_sanitized(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    client(flow, lambda r: httpx.Response(200, json=oa_body(secret=baseline.SYNTHETIC_KEY)))
    sent = asyncio.run(flow._send_search(run["id"], registry.CONNECTORS["openalex"], query(), 1))
    sent = sent.outcome if isinstance(sent, facade.Dispatched) else sent
    assert baseline.SYNTHETIC_KEY not in json.dumps(sent.records[0].raw)
    assert sent.records[0].raw["SYNTHETIC_nested"]["key"] == "before/<redacted>/after"


def test_kill_admission_and_payload(candidate_lib, monkeypatch):
    lib = candidate_lib
    run, q, search, step = prepare_kill(lib, monkeypatch)
    async def send(*args, **kwargs):
        return common.SearchOutcome("completed", None, "SYNTHETIC", "api_key",
            records=[record("None", doi=None), record("123", doi=A)], raw_payload={"echo": baseline.SYNTHETIC_KEY})
    install(monkeypatch, "ieee_xplore", send)
    sent, trace = asyncio.run(lib.flow._kill_search_request(run, q))
    lib.flow._kill_search_record_query(run, search, step, 1, q, sent, trace)
    row = lib.candidate_store.queries(search["id"])[0]
    saved = lib.store.existing_step(run["id"], "kill-search:1")
    output = dict(saved["output"])
    assert output.pop("transport") == {"reserved": 3, "attempts": 0, "sends": 0,
                                       "dispatches": [{"subrequests": []}]}
    assert output == {"status": "completed", "result_count": 1, "dropped_records": 1}
    assert row["record_count"] == 1
    payload = json.loads((lib.flow.deps.settings.payloads_dir / row["raw_payload_path"]).read_text())
    assert payload == {"echo": "<redacted>"} and row["payload_sha256"] == canonical.sha256_hex(payload)


@pytest.mark.parametrize("value,expected", [(None, False), (17, False), ({}, False), ([], False), ("", False),
    (" \t", False), (" None ", False), (" {x}", False), (" [x]", False), ("17", True), (" W1 ", True)])
def test_usable_identity(value, expected):
    assert facade.usable_identity(value) is expected


def test_sanitize_keys_copy_and_collision():
    key = baseline.SYNTHETIC_KEY
    original = {f"url/{key}": [{"text": f"{key}{key}"}], "other": {key: 1, "<redacted>": 2}}
    before = copy.deepcopy(original)
    cleaned = facade.sanitize(original, (key, None, ""))
    assert original == before and cleaned is not original
    assert cleaned == {"url/<redacted>": [{"text": "<redacted><redacted>"}],
                       "other": {"<omitted>": "secret_key_collision"}}


def test_keyless_payload_byte_identity(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    payload = oa_body(secret=baseline.SYNTHETIC_KEY)
    client(flow, lambda r: httpx.Response(200, json=payload))
    record_sent(flow, run, query())
    path = flow.deps.settings.payloads_dir / rows(flow)[0]["raw_payload_path"]
    assert path.read_bytes() == json.dumps(payload).encode()


def test_chain_snapshotted_key_at_write(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    run["budget"]["max_chain_requests"] = 10
    old, later = baseline.SYNTHETIC_KEY, "SYNTHETIC-rotated-key"
    seen = []
    def transport(r):
        seen.append(r.headers["authorization"].removeprefix("Bearer "))
        monkeypatch.setenv("OPENALEX_API_KEY", later)
        return httpx.Response(200, json=oa_body(secret=old))
    client(flow, transport)
    asyncio.run(flow._chain_request(run, {"effort": "standard"}, "chain:backward:0", "backward", {}, [], batch=["W1"]))
    text = (flow.deps.settings.payloads_dir / rows(flow)[0]["raw_payload_path"]).read_text()
    assert seen == [old] and old not in text and later not in text


@pytest.mark.parametrize("pid", ["semantic_scholar", "scopus"])
def test_keyed_lookup_payload(dispatch_flow, pid):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [A])
    key = baseline.SYNTHETIC_KEY
    payload = [paper(A, SYNTHETIC_nested={key: key})] if pid == "semantic_scholar" else {
        "search-results": {"entry": [{"prism:doi": A, "dc:description": "SYNTHETIC abstract", "echo": {key: key}}]}}
    client(flow, lambda r: httpx.Response(200, json=payload))
    operation = lookups._semantic_scholar_step if pid == "semantic_scholar" else lookups._scopus_step
    asyncio.run(operation(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    files = list(flow.deps.settings.payloads_dir.glob("*.json"))
    assert len(files) == 1 and key not in files[0].read_text() and "<redacted>" in files[0].read_text()


# Named change 4: every B2 identity characterization gets a stored disposition.
def test_failed_search_keeps_drop_count(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    async def search(*args, **kwargs):
        return common.SearchOutcome("failed", None, "SYNTHETIC", "api_key",
                                    records=[record("None")], error="SYNTHETIC failure")
    install(monkeypatch, "openalex", search)
    _, step, failure = record_sent(flow, run, query())
    assert step["status"] == "failed" and failure[0] == "provider_failed"
    assert step["output"] == {"dropped_records": 1, "search_run_id": rows(flow)[0]["id"]}
    assert json.loads(rows(flow)[0]["connector_json"])["dropped_records"] == 1
    assert rows(flow)[0]["result_count"] == 0


IDENTITIES = [(p, e, next(c for c in conformance.endpoint_fixture(conformance.FIXTURES[p], e)["cases"]
                         if c["name"] == name), info)
              for (p, e, name), info in conformance.IDENTITY_KNOWN_MISMATCHES.items()]
@pytest.mark.parametrize("pid,eid,case,info", IDENTITIES,
                         ids=[f"{p}/{e or 'default'}/{c['name']}" for p, e, c, _ in IDENTITIES])
def test_identity_disposition(dispatch_flow, monkeypatch, pid, eid, case, info):
    flow, new_run = dispatch_flow
    run = new_run((pid,))
    direct = conformance.replay_case(pid, eid, conformance.FIXTURES[pid], case, direct=True)[0]
    async def search(*args, **kwargs):
        return copy.deepcopy(direct)
    install(monkeypatch, pid, search)
    # Numeric text is usable irrespective of its original JSON type; all other
    # characterized unusable strings are empty, None text, or container text.
    admitted = [r for r in direct.records if isinstance(r.provider_record_id, str)
                and r.provider_record_id.strip() and r.provider_record_id.strip() != "None"
                and not r.provider_record_id.strip().startswith(("{", "["))]
    sent, step, _ = record_sent(flow, run, query(pid, **({"endpoint": eid} if eid else {})))
    sent = sent.outcome if isinstance(sent, facade.Dispatched) else sent
    dropped = len(direct.records) - len(admitted)
    assert [r.provider_record_id for r in sent.records] == [r.provider_record_id for r in admitted]
    assert rows(flow)[0]["result_count"] == step["output"]["result_count"] == len(admitted)
    assert json.loads(rows(flow)[0]["connector_json"])["dropped_records"] == dropped
    assert step["output"].get("dropped_records", 0) == dropped
    assert ("dropped_records" in step["output"]) == bool(dropped)


@pytest.mark.parametrize("pid,eid,case,info", [entry for entry in IDENTITIES if entry[2]["name"] == "identity_number"],
                         ids=[f"{p}/{e or 'default'}" for p, e, c, _ in IDENTITIES if c["name"] == "identity_number"])
def test_numeric_identity_admissions(dispatch_flow, monkeypatch, pid, eid, case, info):
    """Unchanged admission evidence through an entry point available on old code."""
    flow, new_run = dispatch_flow
    run = new_run((pid,))
    direct = conformance.replay_case(pid, eid, conformance.FIXTURES[pid], case, direct=True)[0]
    async def search(*args, **kwargs):
        return copy.deepcopy(direct)
    install(monkeypatch, pid, search)
    sent, step, _ = record_sent(flow, run, query(pid))
    if not isinstance(sent, common.SearchOutcome):
        assert isinstance(sent, facade.Dispatched)
        sent = sent.outcome
    assert "17" in [r.provider_record_id for r in sent.records]
    assert rows(flow)[0]["result_count"] == step["output"]["result_count"] == len(direct.records)


def test_identity_discovery_rejects_none(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    client(flow, lambda r: httpx.Response(200, json=oa_body(ids=(None,))))
    asyncio.run(flow._search_round(run, [(0, query())], False, "standard"))
    assert rows(flow)[0]["result_count"] == 0
    assert flow.store.candidates(run["research_id"]) == []
    assert flow.store.existing_step(run["id"], "search:0")["output"]["dropped_records"] == 1


def test_all_dropped_page_continues(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    monkeypatch.setattr(flow_module, "SW_READ_LIMIT", {"standard": 2})
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(registry.CONNECTORS["openalex"], max_results=1))
    cursors = []
    def transport(r):
        cursors.append(r.url.params["cursor"])
        return httpx.Response(200, json=oa_body(ids=(None,) if len(cursors) == 1 else ("https://openalex.org/W2",),
                                              cursor="next" if len(cursors) == 1 else None))
    client(flow, transport)
    asyncio.run(flow._search_round(run, [(0, query())], False, "standard"))
    assert cursors == ["*", "next"]
    assert [r["result_count"] for r in rows(flow)] == [0, 1]
    assert [r["read_total"] for r in rows(flow)] == [1, 2]
    assert rows(flow)[0]["stop_reason"] is None


# Decision 6: historical NULL continues; invalid provenance is not historical NULL.
PROVENANCE = [(None, None), ("current", None), (json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": 999}), "adapter_revision_changed"),
    (json.dumps({"contract_id": "unsupported", "adapter_revision": 2}), "adapter_revision_changed"),
    ("{", "connector_provenance_invalid"), ("[]", "connector_provenance_invalid"),
    ("{}", "connector_provenance_invalid"), (json.dumps({"contract_id": 1, "adapter_revision": 2}), "connector_provenance_invalid"),
    (json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": True}), "connector_provenance_invalid"),
    (json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": "2"}), "connector_provenance_invalid"),
    ("missing-row", "connector_provenance_invalid")]
@pytest.mark.parametrize("provenance,error", PROVENANCE,
                         ids=["legacy-null", "current", "mismatch", "unsupported", "malformed", "nonobject", "missing-fields",
                              "contract-type", "bool-revision", "string-revision", "missing-row"])
def test_resume_provenance(dispatch_flow, monkeypatch, provenance, error):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    monkeypatch.setattr(flow_module, "SW_READ_LIMIT", {"standard": 2})
    install(monkeypatch, "openalex", registry.CONNECTORS["openalex"].search, max_results=1)
    client(flow, lambda r: httpx.Response(200, json=oa_body(cursor="next")))
    page = Page(0, "*", 0, None, 2, 0, "search:0", 10)
    _, first, _ = record_sent(flow, run, query(), page=page)
    if provenance == "current":
        provenance = json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": registry.CONNECTORS["openalex"].adapter_revision})
    if provenance == "missing-row":
        # A succeeded page whose recorded search points to a different step.
        flow.store.conn.execute("UPDATE run_steps SET output_json = ? WHERE id = ?",
            (json.dumps({"next_cursor": "next", "read_total": 1}), first["id"]))
        other = flow.store.step(run["id"], "other", "provider_search:openalex")
        flow.store.conn.execute("UPDATE search_runs SET step_id = ? WHERE step_id = ?", (other["id"], first["id"]))
    else:
        flow.store.conn.execute("UPDATE search_runs SET connector_json = ? WHERE step_id = ?", (provenance, first["id"]))
    seen = []
    client(flow, lambda r: seen.append(r.url.params["cursor"]) or httpx.Response(200, json=oa_body(cursor=None)))
    before = flow.store.run(run["id"])["usage"]
    prior_rows = len(rows(flow))
    read = _QueryRead(0, query())
    asyncio.run(flow._read_query(run, read, False, "standard"))
    failure = flow._write_query(run, read)
    saved = flow.store.existing_step(run["id"], "search:0:page:1")
    if error:
        assert seen == [] and flow.store.run(run["id"])["usage"] == before and len(rows(flow)) == prior_rows
        assert saved["status"] == "failed" and saved["error_code"] == error
        assert saved["output"] == {"status": error, "result_count": 0}
        assert failure[0] == "provider_adapter_revision_changed" and read.ended
    else:
        assert seen == ["next"] and saved["status"] == "succeeded" and failure is None
        # A second resume asks no page twice.
        asyncio.run(flow._search_round(run, [(0, query())], False, "standard"))
        assert seen == ["next"]


def test_resume_changed_descriptor(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    client(flow, lambda r: httpx.Response(200, json=oa_body(cursor="next")))
    record_sent(flow, run, query(), page=Page(0, "*", 0, None, 20, 0, "search:0", 10))
    source = registry.CONNECTORS["openalex"]
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(source, adapter_revision=source.adapter_revision + 1))
    read = _QueryRead(0, query())
    before = flow.store.run(run["id"])["usage"]
    client(flow, baseline.deny_network)
    asyncio.run(flow._read_query(run, read, False, "standard"))
    assert flow._write_query(run, read)[0] == "provider_adapter_revision_changed"
    assert flow.store.run(run["id"])["usage"] == before


def test_migration_0067_preserves_0066_rows(tmp_path, monkeypatch):
    real = db.MIGRATIONS_DIR
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    numbers = [int(p.name.split("_")[0]) for p in real.glob("*.sql")]
    assert len(numbers) == len(set(numbers)) and 67 in numbers
    for path in real.glob("*.sql"):
        if int(path.name.split("_")[0]) <= 66:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    generator = conformance.dispatch_flow.__wrapped__(tmp_path)
    flow, new_run = next(generator)
    try:
        run = new_run(("openalex",))
        from test_provider_records import search
        search(flow.store, run["research_id"], run["id"], 0, "openalex", [record("W1")])
        columns = [r[1] for r in flow.store.conn.execute("PRAGMA table_info(search_runs)")]
        before = [tuple(r) for r in flow.store.conn.execute("SELECT * FROM search_runs")]
        shutil.copy(real / "0067_search_run_connector.sql", migrations)
        assert db.migrate(flow.store.conn) == [67]
        assert [tuple(r) for r in flow.store.conn.execute(f"SELECT {','.join(columns)} FROM search_runs")] == before
        assert rows(flow)[0]["connector_json"] is None
        assert flow.store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        with pytest.raises(StopIteration):
            next(generator)


def test_new_row_current_provenance(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    client(flow, lambda r: httpx.Response(200, json=oa_body()))
    record_sent(flow, run, query())
    descriptor = facade.connectors()["openalex"].descriptor
    assert json.loads(rows(flow)[0]["connector_json"]) == {
        "contract_id": descriptor.contract_id, "adapter_revision": descriptor.adapter_revision,
        "query_rules_revision": descriptor.query_rules_revision, "payload": "sanitized_json", "dropped_records": 0}


def test_completed_pages_do_not_recheck_revision(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    monkeypatch.setattr(flow_module, "SW_READ_LIMIT", {"standard": 2})
    install(monkeypatch, "openalex", registry.CONNECTORS["openalex"].search, max_results=1)
    seen = []
    client(flow, lambda r: seen.append(r.url.params["cursor"]) or httpx.Response(200, json=oa_body(
        cursor="next" if len(seen) == 1 else None)))
    asyncio.run(flow._search_round(run, [(0, query())], False, "standard"))
    assert seen == ["*", "next"]
    flow.store.conn.execute("UPDATE search_runs SET connector_json = '{}' ")
    client(flow, baseline.deny_network)
    assert asyncio.run(flow._search_round(run, [(0, query())], False, "standard")) is None
    assert len(rows(flow)) == 2


def test_merge_and_arxiv_versions(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "ieee_xplore", "arxiv"))
    for index, (pid, records) in enumerate([
        ("openalex", [record("W1", doi=A)]), ("ieee_xplore", [record("123", doi=A)]),
        ("arxiv", [record("abc.123v1", doi="10.48550/arxiv.abc.123", merge_by_doi=False),
                   record("abc.123v2", doi="10.48550/arxiv.abc.123", merge_by_doi=False)])]):
        async def search(*args, records=records, **kwargs):
            return common.SearchOutcome("completed", None, "SYNTHETIC", "keyless", records=records)
        install(monkeypatch, pid, search)
        record_sent(flow, run, query(pid), key=f"search:{index}")
    store = flow.store
    assert store.find_source_by_identifier("openalex", "W1") == store.find_source_by_identifier("ieee_xplore", "123")
    assert store.find_source_by_identifier("arxiv", "abc.123v1") != store.find_source_by_identifier("arxiv", "abc.123v2")


def test_payload_write_failure_publishes_nothing(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    client(flow, lambda r: httpx.Response(200, json=oa_body()))
    original = Path.write_text
    def fail(path, *args, **kwargs):
        if path.parent == flow.deps.settings.payloads_dir:
            raise OSError("SYNTHETIC disk failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(OSError, match="SYNTHETIC"):
        asyncio.run(flow._search_round(run, [(0, query())], False, "standard"))
    assert rows(flow) == [] and flow.store.candidates(run["research_id"]) == []
    assert flow.store.conn.execute("SELECT count(*) FROM source_versions").fetchone()[0] == 0
    assert not any(s["status"] == "succeeded" for s in flow.store.run_steps(run["id"]))


def test_unknown_endpoint_paged_accounting(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("semantic_scholar",))
    with pytest.raises(KeyError):
        asyncio.run(flow._search_round(run, [(0, query("semantic_scholar", endpoint="removed"))], False, "standard"))
    assert flow.store.run(run["id"])["usage"].get("provider_requests", 0) == 0 and rows(flow) == []


def test_unknown_endpoint_kill_reservation(candidate_lib, monkeypatch):
    lib = candidate_lib
    run, q, _, _ = prepare_kill(lib, monkeypatch)
    transport = run["target"]["transport"]["providers"][0]
    transport["provider"] = "semantic_scholar"
    q = query("semantic_scholar", endpoint="removed")
    with pytest.raises(contract.ContractViolation, match="unknown endpoint"):
        asyncio.run(lib.flow._kill_search_request(run, q))
    assert lib.store.run(run["id"])["usage"]["provider_requests"] == transport["requests_per_search"] * (1 + transport["rate_limit_retries"])


def test_connections_projection(tmp_path):
    from deixis.api.app import create_app
    from deixis.config import Settings
    from fakes import FakeAdapter
    http = httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network))
    app = create_app(Settings(data_dir=tmp_path / "api"), adapters={"fake": FakeAdapter()}, http_client=http,
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as browser:
        response = browser.get("/api/connections")
        assert response.status_code == 200
        providers = response.json()["providers"]
        assert [p["id"] for p in providers] == list(registry.CONNECTORS)
        for p in providers:
            descriptor = facade.connectors()[p["id"]].descriptor
            assert p["contract_id"] == descriptor.contract_id and p["adapter_revision"] == descriptor.adapter_revision
            assert p["capabilities"] == ["search"]
            assert {"implemented", "access_mode", "supplementary", "key_env", "role", "note"} <= p.keys()

"""SYNTHETIC B4 dispatch, named changes and stored continuation boundaries.

Behavioral cases use the flow's send/record seam and the fast path's search slots and
chain round. Direct facade equivalence remains separate from admission, secrecy and version refusal.
"""

import asyncio
import json
import socket
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

import connector_baseline as baseline
import fast_search_helpers as fast
import test_connector_contract as conformance
import test_connector_facade as equality
from test_connector_contract import dispatch_flow
from test_provider_records import record
from deixis.providers import common, contract, facade, registry
from deixis.workflow.run import flow as flow_module


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


def oa_body(ids=("https://openalex.org/W1",), cursor=None, secret=None):
    body = json.loads(equality.native_script("openalex", None, conformance.FIXTURES["openalex"])[0][2])
    first = body["results"][0]
    body["results"] = [dict(first, id=i, doi=None) for i in ids]
    body["meta"]["next_cursor"] = cursor
    if secret:
        body["results"][0]["SYNTHETIC_nested"] = {"key": f"before/{secret}/after"}
    return body


@pytest.mark.parametrize("provider_id,kind,q,cursor_kind,retries,limited",
                         [p for p in equality.DISPATCH_SHAPES if p.id == "semantic_scholar/bulk/routed/first/retry0/positive"])
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
    root = Path(flow_module.__file__).parents[1]  # all of workflow/, not only run/
    assert len(list(root.rglob("*.py"))) > 100
    assert not [p.name for p in root.rglob("*.py") if "connector.search(" in p.read_text()]


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


def lookup_sources(flow, run, dois):
    for i, doi in enumerate(dois):
        flow.store.upsert_provider_source("openalex", record(f"W{i}", doi=doi), None)
    return [{"source_version_id": flow.store.find_source_by_identifier("openalex", f"W{i}"), "doi": doi}
            for i, doi in enumerate(dois)]


def test_record_raw_only_is_sanitized(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    client(flow, lambda r: httpx.Response(200, json=oa_body(secret=baseline.SYNTHETIC_KEY)))
    sent = asyncio.run(flow._send_search(run["id"], registry.CONNECTORS["openalex"], query(), 1))
    sent = sent.outcome if isinstance(sent, facade.Dispatched) else sent
    assert baseline.SYNTHETIC_KEY not in json.dumps(sent.records[0].raw)
    assert sent.records[0].raw["SYNTHETIC_nested"]["key"] == "before/<redacted>/after"


# Decision 6: historical NULL continues; invalid provenance is not historical NULL.
PROVENANCE = [(None, None), ("current", None), (json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": 999}), "adapter_revision_changed"),
    (json.dumps({"contract_id": "unsupported", "adapter_revision": 2}), "adapter_revision_changed"),
    ("{", "connector_provenance_invalid"), ("[]", "connector_provenance_invalid"),
    ("{}", "connector_provenance_invalid"), (json.dumps({"contract_id": 1, "adapter_revision": 2}), "connector_provenance_invalid"),
    (json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": True}), "connector_provenance_invalid"),
    (json.dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": "2"}), "connector_provenance_invalid"),
    ("missing-row", "connector_provenance_invalid")]

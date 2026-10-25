"""G1-F1 SYNTHETIC capability equivalence and workflow evidence; no network."""

import asyncio
import ast
import copy
import json
import socket
from pathlib import Path

import httpx
import pytest

import connector_baseline as baseline
import fast_search_helpers as fast
from deixis.providers import common, contract, facade, lookup, openalex, registry
from deixis.workflow import lookups
from deixis.storage.db import dumps
from test_connector_contract import FIXTURES, dispatch_flow, check_coverage
from test_connector_dispatch import client, lookup_sources, paper

KEY = baseline.SYNTHETIC_KEY
ROOT = Path(__file__).resolve().parents[2]
CASES = [(pid, op, case) for pid, fixture in FIXTURES.items()
         for op, cases in fixture.get("capability_cases", {}).items() for case in cases]
BINDINGS = [(pid, op) for pid, fixture in FIXTURES.items() for op in fixture.get("capability_cases", {})]
DOI = "10.9999/synthetic.1"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", baseline.deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", baseline.deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", baseline.deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", baseline.deny_network)
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.setenv(connector.key_env, KEY)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)


def test_declared_capabilities_and_bindings():
    expected = {"openalex": {"id_lookup", "citing_works"}, "semantic_scholar": {"doi_lookup"},
                "crossref": {"doi_lookup"}, "scopus": {"doi_lookup"}}
    for pid, connector in registry.CONNECTORS.items():
        assert facade.connectors()[pid].descriptor.capabilities == {"search"} | expected.get(pid, set())
        assert set(connector.capabilities) == expected.get(pid, set())
    assert not hasattr(registry, "UNBOUND_HELPERS") and not hasattr(facade, "UNBOUND_HELPERS")
    assert {pid: registry.CONNECTORS[pid].adapter_revision for pid in expected} == {
        "openalex": 3, "semantic_scholar": 2, "crossref": 2, "scopus": 2}
    assert contract.CONTRACT_ID == "deixis.scholarly_connector.v1"
    check_coverage(FIXTURES)


def test_workflow_has_no_bound_helper_calls():
    forbidden = {"crossref_work", "semantic_scholar_batch", "scopus_abstract", "works_by_ids", "citing_works"}
    calls = []
    for path in (ROOT / "deixis/workflow").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else None
                if name in forbidden:
                    calls.append((str(path.relative_to(ROOT)), node.lineno, ast.unparse(node.func)))
    assert calls == []


def id_answers(ids, outcome):
    found = {record.provider_record_id for record in outcome.records}
    return {identifier: lookup.LookupAnswer("found" if identifier in found else
             "not_found" if outcome.status in ("completed", "zero_results") else "failed") for identifier in ids}


async def direct(pid, op, http, case, key, allowance):
    ids = tuple(case["identifiers"])
    kwargs = {} if allowance is None else {"max_rate_limit_retries": allowance}
    if op == "citing_works":
        return {}, await openalex.citing_works(http, case["work_id"], case["cursor"], case["limit"], key,
                                                baseline.CONTACT, **kwargs, **case.get("options", {}))
    if pid == "openalex":
        outcome = await openalex.works_by_ids(http, ids, key, baseline.CONTACT, **kwargs)
        return id_answers(ids, outcome), outcome
    if pid == "semantic_scholar":
        return await lookup.semantic_scholar_batch(http, ids, key, **kwargs)
    if pid == "crossref":
        answer, outcome = await lookup.crossref_work(http, ids[0], baseline.CONTACT)
    else:
        answer, outcome = await lookup.scopus_abstract(http, ids[0], key, **kwargs)
    return {ids[0]: answer}, outcome


def replay(pid, op, case, mode, allowance=2):
    key = KEY if registry.CONNECTORS[pid].key_env else None
    remaining = copy.deepcopy(case["responses"])
    requests = []
    connects = 0
    def serve(request):
        nonlocal connects
        assert remaining, "unscripted capability request"
        spec = remaining.pop(0)
        requests.append(baseline.recorded_request(request))
        if "error" in spec:
            connects += spec["error"] == "connect"
            cls = httpx.ConnectError if spec["error"] == "connect" else httpx.ReadTimeout
            raise cls("SYNTHETIC", request=request)
        return httpx.Response(spec["status"], text=spec["text"] if "text" in spec else json.dumps(spec["body"]))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as http:
            context = contract.ConnectorContext(http, key, baseline.CONTACT)
            adapter = facade.connectors()[pid]
            ids = tuple(case["identifiers"])
            with common.collect_transport() as entries:
                try:
                    if mode == "direct":
                        answers, outcome = await direct(pid, op, http, case, key, allowance)
                    elif mode == "dispatch":
                        if op == "citing_works":
                            result = await facade.dispatch_citing(pid, http, case["work_id"], case["cursor"],
                                case["limit"], key, baseline.CONTACT, allowance, **case.get("options", {}))
                            answers = {}
                        else:
                            result = await facade.dispatch_lookup(pid, op, http, ids, key, baseline.CONTACT, allowance)
                            answers = result.answers
                        outcome = result.outcome
                        entries = result.transport
                    elif op == "citing_works":
                        outcome = await adapter.citing_works(contract.CitingWorksRequest(case["work_id"],
                            case["limit"], case["cursor"], allowance, case.get("options", {})), context)
                        answers = {}
                    elif mode == "single":
                        request = contract.LookupRequest(**{"doi" if op == "doi_lookup" else "provider_record_id": ids[0]})
                        result = await adapter.lookup(request, context)
                        assert result.status in {"found", "not_found", "failed"}
                        answers, outcome = {ids[0]: result.answer}, result.outcome
                        assert result.status == result.answer.status and result.operation == op
                    else:
                        result = await adapter.lookup_batch(contract.LookupBatchRequest(op, ids, allowance), context)
                        answers, outcome = result.answers, result.outcome
                except Exception as exc:
                    if "raises" not in case:
                        raise
                    assert type(exc).__name__ == case["raises"]
                    return None, list(entries)
            assert not remaining
            return (answers, outcome, result if mode == "dispatch" else None), list(entries)
    with baseline.fake_clock() as waits:
        value, entries = asyncio.run(run())
    return value, requests, list(waits), entries, connects


UNSUPPORTED = [(pid, op) for pid, fixture in FIXTURES.items() for op in ("doi_lookup", "id_lookup", "citing_works")
               if fixture["capabilities"][op] == "unsupported"]


@pytest.mark.parametrize("pid,op", UNSUPPORTED[:1])
def test_undeclared_operations_are_unsent(pid, op):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            with common.collect_transport() as entries:
                adapter = facade.connectors()[pid]
                context = contract.ConnectorContext(http, KEY, None)
                if op == "citing_works":
                    with pytest.raises(contract.ContractViolation):
                        await adapter.citing_works(contract.CitingWorksRequest("W1", 2), context)
                    with pytest.raises(contract.ContractViolation):
                        await facade.dispatch_citing(pid, http, "W1", "*", 2, KEY, None)
                else:
                    result = await adapter.lookup(contract.LookupRequest(**{"doi" if op == "doi_lookup" else "provider_record_id": DOI}), context)
                    assert result.status == "unsupported" and result.outcome is None and result.answer is None
                    with pytest.raises(contract.ContractViolation):
                        await adapter.lookup_batch(contract.LookupBatchRequest(op, (DOI,)), context)
                    with pytest.raises(contract.ContractViolation):
                        await facade.dispatch_lookup(pid, op, http, (DOI,), KEY, None)
            assert entries == []
    asyncio.run(go())


def lookup_operation(pid):
    return {"semantic_scholar": lookups._semantic_scholar_step, "crossref": lookups._crossref_step,
            "scopus": lookups._scopus_step}[pid]


def lookup_body(pid, doi=DOI, echo=None):
    if pid == "semantic_scholar":
        return [paper(doi, abstract=echo or "SYNTHETIC abstract")]
    if pid == "crossref":
        return {"message": {"DOI": doi, "abstract": "SYNTHETIC abstract"}}
    return {"search-results": {"entry": [{"prism:doi": doi, "dc:description": echo or "SYNTHETIC abstract"}]}}


async def chain(flow, run, *, direction="forward", batch=None):
    """One fast chain request (forward from W9, or backward over `batch`), sent and written as the round does."""
    return await fast.chain(flow, run, fast.chain_spec(direction, batch=batch))


@pytest.mark.parametrize("pid", ["scopus"])
def test_echoed_key_absent_from_stored_lookup(dispatch_flow, pid):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI])
    body = lookup_body(pid, echo="SYNTHETIC "+KEY)
    if pid == "scopus":
        body["search-results"]["entry"][0]["prism:doi"] = KEY
    client(flow, lambda r: httpx.Response(200, json=body))
    asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    for table in ("passages", "record_lookups", "run_steps"):
        assert KEY not in repr([tuple(r) for r in flow.store.conn.execute("SELECT * FROM "+table)])
    if pid == "semantic_scholar":
        assert flow.store.passages_for(batch[0]["source_version_id"])[0]["text"] == "SYNTHETIC <redacted>"



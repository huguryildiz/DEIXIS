"""G1-F1 SYNTHETIC capability equivalence and workflow evidence; no network."""

import asyncio
import ast
import copy
import importlib
import json
import socket
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest

import connector_baseline as baseline
from deixis.providers import common, contract, facade, lookup, openalex, registry
from deixis.workflow import flow as flow_module, lookups
from deixis.storage.db import dumps
from test_connector_contract import FIXTURES, dispatch_flow, check_coverage
from test_connector_dispatch import client, lookup_sources, paper, oa_body, rows

KEY = baseline.SYNTHETIC_KEY
ROOT = Path(__file__).resolve().parents[1]
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


@pytest.mark.parametrize("pid,op,name", [
    ("crossref", "doi_lookup", name) for name in ("positive", "http_404", "http_500")
] + [("semantic_scholar", "doi_lookup", "positive"), ("scopus", "doi_lookup", "positive"),
     ("scopus", "doi_lookup", "other_doi"), ("openalex", "id_lookup", "positive"),
     ("openalex", "id_lookup", "not_found")])
def test_bound_single_lookup(pid, op, name):
    case = next(case for case in FIXTURES[pid]["capability_cases"][op] if case["name"] == name)
    reference = replay(pid, op, case, "direct", None)
    actual = replay(pid, op, case, "single", None)
    assert actual == reference


def test_workflow_has_no_bound_helper_calls():
    forbidden = {"crossref_work", "semantic_scholar_batch", "scopus_abstract", "works_by_ids", "citing_works"}
    calls = []
    for path in (ROOT / "backend/deixis/workflow").rglob("*.py"):
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


def projection(answers, outcome, ids, op, key):
    records = [replace(record, raw=facade.sanitize(record.raw, (key,))) for record in outcome.records
               if facade.usable_identity(record.provider_record_id)]
    outcome = replace(outcome, records=records, raw_payload=facade.sanitize(outcome.raw_payload, (key,)),
                      **({"error": facade.sanitize(outcome.error, (key,))} if op != "citing_works" else {}))
    if op == "id_lookup":
        answers = id_answers(ids, outcome)
    answers = {identifier: replace(answer, **{name: facade.sanitize(getattr(answer, name), (key,))
               for name in ("abstract", "paper_id", "linked_dois", "has_preprint")}) for identifier, answer in answers.items()}
    return answers, outcome


@pytest.mark.parametrize("pid,op,case", CASES, ids=[f"{p}/{o}/{c['name']}" for p,o,c in CASES])
def test_capability_equivalence(pid, op, case):
    allowance = None if pid == "crossref" else 2
    reference = replay(pid, op, case, "direct", allowance)
    adapter = replay(pid, op, case, "adapter", allowance)
    assert adapter == reference
    if reference[0] is None:
        assert len(reference[1]) == 1
        dispatched = replay(pid, op, case, "dispatch", allowance)
        assert dispatched[0] is None and dispatched[1:3] == reference[1:3]
        return
    answers, outcome, _ = reference[0]
    assert outcome.status == case["expected_status"]
    if "answer_statuses" in case:
        assert [a.status for a in answers.values()] == case["answer_statuses"]
    if op != "citing_works" and len(case["identifiers"]) == 1:
        single = replay(pid, op, case, "single", allowance)
        assert single == reference
    dispatched = replay(pid, op, case, "dispatch", allowance)
    result, requests, waits, entries, connects = dispatched
    assert (requests, waits) == reference[1:3]
    key = KEY if registry.CONNECTORS[pid].key_env else None
    expected = projection(answers, outcome, case["identifiers"], op, key)
    assert result[:2] == expected
    sent = result[2]
    assert sent.returned_count == len(outcome.records)
    assert sent.dropped_records == len(outcome.records) - len(expected[1].records)
    assert sent.connector == {"contract_id": contract.CONTRACT_ID, "adapter_revision": registry.CONNECTORS[pid].adapter_revision,
        "query_rules_revision": contract.QUERY_RULES_REVISION, "payload": "sanitized_json" if outcome.raw_payload is not None else None,
        "dropped_records": sent.dropped_records}
    assert len(entries) == 1
    assert sum(e["attempts"] for e in entries) == len(requests)
    assert sum(e["sends"] for e in entries) == len(requests) - connects
    assert sum(e["retries"] for e in entries) == outcome.retries
    assert KEY not in repr((entries, result[:2], sent.connector))
    if case["name"] == "repeated_doi":
        assert requests[0]["json"]["ids"] == ["DOI:" + DOI, "DOI:" + DOI]


@pytest.mark.parametrize("pid,op", BINDINGS)
def test_omitted_retry_allowance(pid, op):
    case = next(c for c in FIXTURES[pid]["capability_cases"][op] if c["name"] == "rate_unstated")
    reference = replay(pid, op, case, "direct", None)
    assert replay(pid, op, case, "adapter", None) == reference
    sent = replay(pid, op, case, "dispatch", None)
    assert sent[1:3] == reference[1:3] and sent[0][1].retries == 1


@pytest.mark.parametrize("pid,op", BINDINGS)
def test_binding_ceiling(pid, op):
    case = copy.deepcopy(FIXTURES[pid]["capability_cases"][op][0])
    binding = registry.CONNECTORS[pid].capabilities[op]
    if op == "citing_works":
        case["limit"] = binding.max_batch + 1
    else:
        case["identifiers"] *= binding.max_batch
        if pid == "semantic_scholar":
            case["responses"][0]["body"] *= binding.max_batch
    result = replay(pid, op, case, "dispatch", None)
    assert len(result[1]) == 1
    request = result[1][0]
    if op == "citing_works":
        assert ["per_page", str(binding.max_batch)] in request["params"]
    elif pid == "semantic_scholar":
        assert len(request["json"]["ids"]) == binding.max_batch


@pytest.mark.parametrize("pid,op", [(p,o) for p,o in BINDINGS if o != "citing_works"])
def test_batch_above_ceiling_is_unsent(pid, op):
    adapter = facade.connectors()[pid]
    identifiers = (DOI,) * (registry.CONNECTORS[pid].capabilities[op].max_batch + 1)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            with common.collect_transport() as entries:
                with pytest.raises(contract.ContractViolation):
                    await adapter.lookup_batch(contract.LookupBatchRequest(op, identifiers), contract.ConnectorContext(http, KEY, None))
                with pytest.raises(contract.ContractViolation):
                    await facade.dispatch_lookup(pid, op, http, identifiers, KEY, None)
            assert entries == []
    asyncio.run(go())


@pytest.mark.parametrize("identifiers", [(), [], ("",), (None,), (1,), (DOI, "")])
def test_invalid_identifiers(identifiers):
    with common.collect_transport() as entries:
        with pytest.raises(contract.ContractViolation):
            contract.LookupBatchRequest("doi_lookup", identifiers)
    assert entries == []


@pytest.mark.parametrize("allowance", [-1, True, 1.5, "2"])
def test_invalid_retry_allowance(allowance):
    with common.collect_transport() as entries:
        for make in (lambda: contract.LookupBatchRequest("doi_lookup", (DOI,), allowance),
                     lambda: contract.CitingWorksRequest("W1", 1, max_rate_limit_retries=allowance)):
            with pytest.raises(contract.ContractViolation):
                make()
    assert entries == []


@pytest.mark.parametrize("kwargs", [{"work_id": v} for v in ("", None, 1)] +
    [{"limit": v} for v in (True, "2", 1.5, 0, -1)] + [{"cursor": v} for v in (None, 1, "")])
def test_invalid_citing_fields(kwargs):
    with common.collect_transport() as entries:
        with pytest.raises(contract.ContractViolation):
            contract.CitingWorksRequest(**({"work_id": "W1", "limit": 2} | kwargs))
    assert entries == []


@pytest.mark.parametrize("options", [{"unknown": True}, {"sort": True}, {"publication_date": "true"}])
def test_invalid_citing_options(options):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            with common.collect_transport() as entries:
                with pytest.raises(contract.ContractViolation):
                    await facade.connectors()["openalex"].citing_works(contract.CitingWorksRequest("W1", 1, options=options),
                                                                      contract.ConnectorContext(http, KEY, None))
                with pytest.raises(contract.ContractViolation):
                    await facade.dispatch_citing("openalex", http, "W1", "*", 1, KEY, None, **options)
            assert entries == []
    asyncio.run(go())


def test_crossref_rejects_retry_allowance():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            with common.collect_transport() as entries:
                with pytest.raises(contract.ContractViolation):
                    await facade.connectors()["crossref"].lookup_batch(contract.LookupBatchRequest("doi_lookup", (DOI,), 0),
                                                                     contract.ConnectorContext(http, None, None))
            assert entries == []
    asyncio.run(go())


UNSUPPORTED = [(pid, op) for pid, fixture in FIXTURES.items() for op in ("doi_lookup", "id_lookup", "citing_works")
               if fixture["capabilities"][op] == "unsupported"]


@pytest.mark.parametrize("pid,op", UNSUPPORTED)
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


def test_registry_only_lookup(monkeypatch):
    async def binding(http, ids, key, contact, allowance):
        _, outcome = await common.send(http, "https://synthetic.invalid/lookup", {}, {}, "SYNTHETIC", "keyless")
        outcome.error = key
        return {identifier: lookup.LookupAnswer("found", abstract=key, paper_id=key,
                    linked_dois=[key], has_preprint=[key]) for identifier in ids}, outcome
    source = registry.Connector("synthetic_lookup", baseline.deny_network, 1,
        capabilities={"doi_lookup": registry.CapabilityBinding(binding, 2)})
    monkeypatch.setitem(registry.CONNECTORS, source.provider_id, source)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as http:
            return await facade.dispatch_lookup(source.provider_id, "doi_lookup", http, (DOI,), KEY, None)
    result = asyncio.run(go())
    assert result.answers[DOI].status == "found" and len(result.transport) == 1
    assert asdict(result.answers[DOI]) == {"status": "found", "abstract": "<redacted>", "paper_id": "<redacted>",
        "linked_dois": ["<redacted>"], "has_preprint": ["<redacted>"], "reference_count": None}
    assert result.outcome.error == "<redacted>" and KEY not in repr(result)
    assert isinstance(facade.connectors()[source.provider_id], contract.BatchLookupCapable)
    assert isinstance(facade.connectors()[source.provider_id], contract.CitingWorksCapable)


def test_missing_lookup_key_has_no_collector_entry():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(baseline.deny_network)) as http:
            with common.collect_transport() as entries:
                adapter = facade.connectors()["scopus"]
                context = contract.ConnectorContext(http, None, None)
                single = await adapter.lookup(contract.LookupRequest(doi=DOI), context)
                batch = await adapter.lookup_batch(contract.LookupBatchRequest("doi_lookup", (DOI,)), context)
                dispatched = await facade.dispatch_lookup("scopus", "doi_lookup", http, (DOI,), None, None)
            assert entries == [] and dispatched.transport == ()
            assert single.status == batch.answers[DOI].status == dispatched.answers[DOI].status == "failed"
            for outcome in (single.outcome, batch.outcome, dispatched.outcome):
                assert (outcome.status, outcome.delivery_class, outcome.access_mode) == ("not_configured", "before_send", "not_configured")
    asyncio.run(go())


def test_citing_options_are_read_only_snapshot():
    options = {"sort": "publication_date:desc"}
    request = contract.CitingWorksRequest("W1", 1, options=options)
    options["sort"] = "SYNTHETIC-changed"
    assert request.options["sort"] == "publication_date:desc"
    with pytest.raises(TypeError):
        request.options["sort"] = "SYNTHETIC-changed"


def lookup_operation(pid):
    return {"semantic_scholar": lookups._semantic_scholar_step, "crossref": lookups._crossref_step,
            "scopus": lookups._scopus_step}[pid]


def lookup_body(pid, doi=DOI, echo=None):
    if pid == "semantic_scholar":
        return [paper(doi, abstract=echo or "SYNTHETIC abstract")]
    if pid == "crossref":
        return {"message": {"DOI": doi, "abstract": "SYNTHETIC abstract"}}
    return {"search-results": {"entry": [{"prism:doi": doi, "dc:description": echo or "SYNTHETIC abstract"}]}}


def chain_run(flow, new_run, limit=10):
    run = new_run(("openalex",))
    flow.store.update_run(run["id"], budget_json=dumps(run["budget"] | {"max_chain_requests": limit}))
    return flow.store.run(run["id"])


async def chain(flow, run, *, direction="forward", key="chain:forward:W9:1", batch=None, page=1, cites="W9", forms=None):
    return await flow._chain_request(run, {"effort": "standard"}, key, direction, forms or {"task": ["synthetic"]}, [],
        batch=batch, page=page if direction == "forward" else None, cites=cites if direction == "forward" else None)


@pytest.mark.parametrize("pid", ["semantic_scholar", "crossref", "scopus"])
def test_lookup_reservation_visible_in_flight(dispatch_flow, pid):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI])
    async def go():
        entered, release = asyncio.Event(), asyncio.Event()
        async def serve(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=lookup_body(pid))
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as http:
            task = asyncio.create_task(lookup_operation(pid)(flow.store, http, flow.deps.settings, run, 0, batch))
            await entered.wait()
            try:
                assert flow.store.run(run["id"])["usage"]["lookup_requests"] == 3
                assert flow.store.run(run["id"])["usage"].get("lookup_sends", 0) == 0
            finally:
                release.set()
                await task
    asyncio.run(go())
    usage = flow.store.run(run["id"])["usage"]
    assert (usage["lookup_requests"], usage["lookup_sends"]) == (1, 1)


@pytest.mark.parametrize("pid", ["semantic_scholar", "crossref", "scopus"])
@pytest.mark.parametrize("ending,attempts,sends", [("retry", 2, 2), ("connect", 1, 0), ("exhausted", 3, 3)])
def test_lookup_collector_accounting(dispatch_flow, pid, ending, attempts, sends):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI])
    seen = []
    def serve(request):
        seen.append(request)
        if ending == "connect":
            raise httpx.ConnectError("SYNTHETIC", request=request)
        if ending == "exhausted" or len(seen) == 1:
            return httpx.Response(429, json={"error": "SYNTHETIC temporary limit"}, headers={"retry-after": "0"})
        return httpx.Response(200, json=lookup_body(pid))
    client(flow, serve)
    with baseline.fake_clock():
        asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    usage = flow.store.run(run["id"])["usage"]
    assert (usage["lookup_requests"], usage["lookup_sends"]) == (attempts, sends)
    assert len(seen) == attempts
    step = flow.store.existing_step(run["id"], f"record_lookup:{pid}:0")
    assert step["status"] == "succeeded"
    assert step["output"]["transport"] == {"reserved": 3, "attempts": attempts, "sends": sends,
        "dispatches": [{"subrequests": [{"url": str(seen[-1].url.copy_with(query=None)), "attempts": attempts,
            "sends": sends, "retries": attempts-1, "status": "failed" if ending == "connect" else
            "rate_limited" if ending == "exhausted" else "completed", "http_status": None if ending == "connect" else
            429 if ending == "exhausted" else 200, "delivery_class": "before_send" if ending == "connect" else
            "rejected_not_executed" if ending == "exhausted" else None}]}]}


def test_crossref_chunk_mixed_failures(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "crossref"))
    batch = lookup_sources(flow, run, [DOI, DOI+"b", DOI+"c"])
    sequence = ["connect", 200, 429, 200]
    def serve(request):
        status = sequence.pop(0)
        if status == "connect":
            raise httpx.ConnectError("SYNTHETIC", request=request)
        return httpx.Response(status, json=lookup_body("crossref"), headers={"retry-after": "0"})
    client(flow, serve)
    with baseline.fake_clock():
        asyncio.run(lookups._crossref_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    trace = flow.store.existing_step(run["id"], "record_lookup:crossref:0")["output"]["transport"]
    assert (trace["reserved"], trace["attempts"], trace["sends"], len(trace["dispatches"])) == (9, 4, 3, 3)
    assert flow.store.run(run["id"])["usage"] == {"lookup_requests": 4, "lookup_sends": 3}


@pytest.mark.parametrize("pid", ["semantic_scholar", "crossref", "scopus"])
def test_lookup_trace_survives_payload_failure(dispatch_flow, monkeypatch, pid):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI])
    client(flow, lambda r: httpx.Response(200, json=lookup_body(pid)))
    def fail(*args):
        raise OSError("SYNTHETIC payload failure")
    monkeypatch.setattr(lookups, "_write_payload", fail)
    with pytest.raises(OSError):
        asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    step = flow.store.existing_step(run["id"], f"record_lookup:{pid}:0")
    assert step["status"] == "running" and step["output"]["transport"]["attempts"] == 1
    assert flow.store.run(run["id"])["usage"] == {"lookup_requests": 1, "lookup_sends": 1}


@pytest.mark.parametrize("path", ["lookup", "chain"])
def test_settlement_and_trace_are_atomic(dispatch_flow, path):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run) if path == "chain" else new_run(("openalex", "crossref"))
    batch = lookup_sources(flow, run, [DOI])
    flow.store.conn.execute("CREATE TEMP TRIGGER fail_trace BEFORE UPDATE OF output_json ON run_steps"
        " WHEN NEW.output_json LIKE '%transport%' BEGIN SELECT RAISE(ABORT, 'SYNTHETIC trace fault'); END")
    client(flow, lambda r: httpx.Response(200, json=oa_body() if path == "chain" else lookup_body("crossref")))
    with pytest.raises(sqlite3.IntegrityError, match="trace fault"):
        asyncio.run(chain(flow, run) if path == "chain" else
                    lookups._crossref_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    prefix = "chain" if path == "chain" else "lookup"
    assert flow.store.run(run["id"])["usage"] == {prefix+"_requests": 2 if path == "chain" else 3}
    key = "chain:forward:W9:1" if path == "chain" else "record_lookup:crossref:0"
    assert flow.store.existing_step(run["id"], key)["output"] is None
    assert rows(flow) == []


@pytest.mark.parametrize("pid", ["crossref", "scopus"])
def test_resumed_chunk_appends_trace(dispatch_flow, monkeypatch, pid):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI, DOI+"b"])
    seen = []
    def serve(request):
        seen.append(request)
        return httpx.Response(200, json=lookup_body(pid, batch[min(len(seen)-1, 1)]["doi"]))
    client(flow, serve)
    original = lookups._write_payload
    def fail_second(*args):
        if len(seen) == 2:
            raise OSError("SYNTHETIC interrupted chunk")
        return original(*args)
    monkeypatch.setattr(lookups, "_write_payload", fail_second)
    with pytest.raises(OSError):
        asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    saved = flow.store.existing_step(run["id"], f"record_lookup:{pid}:0")
    assert len(saved["output"]["transport"]["dispatches"]) == 2
    monkeypatch.setattr(lookups, "_write_payload", original)
    asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    trace = flow.store.existing_step(run["id"], f"record_lookup:{pid}:0")["output"]["transport"]
    assert len(seen) == trace["attempts"] == trace["sends"] == len(trace["dispatches"]) == 3
    assert trace["reserved"] == 9
    assert flow.store.run(run["id"])["usage"] == {"lookup_requests": 3, "lookup_sends": 3}


@pytest.mark.parametrize("pid", ["semantic_scholar", "crossref", "scopus"])
def test_already_answered_exit_keeps_trace(dispatch_flow, pid):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI])
    key = f"record_lookup:{pid}:0"
    step = flow.store.step(run["id"], key, "provider_lookup:"+pid, output={"transport": {"attempts": 1, "dispatches": []}})
    lookups.store_answer(flow.store, batch[0]["source_version_id"], pid, lookup.LookupAnswer("not_found"), step["id"], None)
    asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    assert flow.store.existing_step(run["id"], key)["output"]["transport"] == {"attempts": 1, "dispatches": []}
    assert flow.store.run(run["id"])["usage"] == {}


@pytest.mark.parametrize("prior_trace", [None, {"reserved": 3, "attempts": 1, "sends": 1,
                                               "dispatches": [{"subrequests": [{"attempts": 1, "sends": 1}]}]}])
def test_scopus_missing_key_chunk(dispatch_flow, monkeypatch, prior_trace):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "scopus"))
    batch = lookup_sources(flow, run, [DOI, DOI+"b"])
    flow.store.step(run["id"], "lookup_plan:scopus", "code:lookup_plan", output={"chunks": [batch]})
    if prior_trace is not None:
        flow.store.step(run["id"], "record_lookup:scopus:0", "provider_lookup:scopus",
                        output={"transport": prior_trace})
    monkeypatch.delenv("SCOPUS_API_KEY")
    asyncio.run(lookups._scopus_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    assert [r[0] for r in flow.store.conn.execute("SELECT status FROM record_lookups")] == ["failed", "failed"]
    step = flow.store.existing_step(run["id"], "record_lookup:scopus:0")
    assert step["status"] == "succeeded"
    if prior_trace is None:
        assert "transport" not in step["output"]
    else:
        assert step["output"]["transport"] == prior_trace
    assert flow.store.run(run["id"])["usage"] == {"lookup_requests": 0, "lookup_sends": 0}


def test_scopus_key_snapshot_per_chunk(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "scopus"))
    batch = lookup_sources(flow, run, [DOI, DOI+"b", DOI+"c"])
    seen = []
    def serve(request):
        seen.append(request.headers["X-ELS-APIKey"])
        monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
        return httpx.Response(200, json=lookup_body("scopus", batch[len(seen)-1]["doi"]))
    client(flow, serve)
    asyncio.run(lookups._scopus_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch[:2]))
    asyncio.run(lookups._scopus_step(flow.store, flow.deps.http, flow.deps.settings, run, 1, batch[2:]))
    assert seen == [KEY, KEY]
    assert flow.store.run(run["id"])["usage"] == {"lookup_requests": 2, "lookup_sends": 2}
    assert [r[0] for r in flow.store.conn.execute("SELECT status FROM record_lookups ORDER BY source_version_id")] .count("failed") == 1


@pytest.mark.parametrize("pid", ["semantic_scholar", "crossref", "scopus"])
@pytest.mark.parametrize("key", [KEY, "redacted"])
def test_lookup_payload_bytes_single_sanitization(dispatch_flow, monkeypatch, pid, key):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", pid))
    batch = lookup_sources(flow, run, [DOI])
    if registry.CONNECTORS[pid].key_env:
        monkeypatch.setenv(registry.CONNECTORS[pid].key_env, key)
    body = lookup_body(pid, echo="SYNTHETIC echo "+key)
    client(flow, lambda r: httpx.Response(200, json=body))
    asyncio.run(lookup_operation(pid)(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    direct_payload = ({"ids": ["DOI:"+DOI], "answers": body} if pid == "semantic_scholar" else
                      {DOI: body["message"]} if pid == "crossref" else {DOI: body})
    expected = direct_payload if pid == "crossref" else facade.sanitize(direct_payload, (key,))
    assert next(flow.deps.settings.payloads_dir.glob("*.json")).read_text() == dumps(expected)
    if pid != "crossref":
        text = flow.store.passages_for(batch[0]["source_version_id"])[0]["text"]
        assert text == "SYNTHETIC echo <redacted>"


def test_scopus_envelope_collision(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "scopus"))
    monkeypatch.setenv("SCOPUS_API_KEY", "secret")
    batch = lookup_sources(flow, run, ["10.9999/secret", "10.9999/<redacted>"])
    seen = []
    def serve(request):
        doi = batch[len(seen)]["doi"]
        seen.append(request)
        return httpx.Response(200, json=lookup_body("scopus", doi))
    client(flow, serve)
    asyncio.run(lookups._scopus_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    assert next(flow.deps.settings.payloads_dir.glob("*.json")).read_text() == dumps({"<omitted>": "secret_key_collision"})


@pytest.mark.parametrize("pid", ["semantic_scholar", "scopus"])
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


def test_malformed_answer_keeps_reservation(dispatch_flow):
    flow, new_run = dispatch_flow
    run = new_run(("openalex", "semantic_scholar"))
    batch = lookup_sources(flow, run, [DOI])
    body = lookup_body("semantic_scholar", echo=17)
    client(flow, lambda r: httpx.Response(200, json=body))
    with pytest.raises(AttributeError):
        asyncio.run(lookups._semantic_scholar_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    assert flow.store.run(run["id"])["usage"] == {"lookup_requests": 3}
    assert flow.store.existing_step(run["id"], "record_lookup:semantic_scholar:0")["output"] is None


@pytest.mark.parametrize("path", ["lookup", "chain"])
def test_accounting_uses_collector_when_outcome_is_rebuilt(dispatch_flow, monkeypatch, path):
    flow, new_run = dispatch_flow
    async def send_twice(http, *args, **kwargs):
        for _ in range(2):
            await common.send(http, "https://synthetic.invalid/capability", {}, {}, "SYNTHETIC", "keyless",
                              max_rate_limit_retries=2)
        rebuilt = common.SearchOutcome("completed", None, "SYNTHETIC rebuilt", "keyless", retries=0)
        return ({DOI: lookup.LookupAnswer("found")}, rebuilt) if path == "lookup" else rebuilt
    pid, op = ("crossref", "doi_lookup") if path == "lookup" else ("openalex", "citing_works")
    source = registry.CONNECTORS[pid]
    monkeypatch.setitem(registry.CONNECTORS, pid, replace(source,
        capabilities=dict(source.capabilities) | {op: registry.CapabilityBinding(send_twice, 1, path != "lookup")}))
    sequence = [429, 200, 429, 200]
    client(flow, lambda r: httpx.Response(sequence.pop(0), headers={"retry-after": "0"}))
    run = chain_run(flow, new_run) if path == "chain" else new_run(("openalex", "crossref"))
    batch = lookup_sources(flow, run, [DOI])
    with baseline.fake_clock():
        asyncio.run(chain(flow, run) if path == "chain" else
                    lookups._crossref_step(flow.store, flow.deps.http, flow.deps.settings, run, 0, batch))
    prefix = "chain" if path == "chain" else "lookup"
    assert flow.store.run(run["id"])["usage"] == {prefix+"_requests": 4, prefix+"_sends": 4}
    key = "chain:forward:W9:1" if path == "chain" else "record_lookup:crossref:0"
    trace = flow.store.existing_step(run["id"], key)["output"]["transport"]
    assert (trace["reserved"], trace["attempts"], trace["sends"], trace["over_reservation"]) == (
        2 if path == "chain" else 3, 4, 4, 2 if path == "chain" else 1)
    assert len(trace["dispatches"]) == 1 and len(trace["dispatches"][0]["subrequests"]) == 2


def test_chain_reservation_visible_in_flight(dispatch_flow):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run, 2)
    async def go():
        entered, release = asyncio.Event(), asyncio.Event()
        async def serve(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=oa_body())
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as http:
            flow.deps.http = http
            task = asyncio.create_task(chain(flow, run))
            await entered.wait()
            try:
                assert flow.store.run(run["id"])["usage"] == {"chain_requests": 2}
            finally:
                release.set()
                await task
    asyncio.run(go())
    assert flow.store.run(run["id"])["usage"] == {"chain_requests": 1, "chain_sends": 1}


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_chain_admission_raw_redaction_and_provenance(dispatch_flow, direction):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run)
    payload = oa_body(secret=KEY)
    rejected = copy.deepcopy(payload["results"][0])
    rejected["id"] = None
    rejected["doi"] = "https://doi.org/10.9999/rejected"
    payload["results"].append(rejected)
    client(flow, lambda r: httpx.Response(200, json=payload))
    with baseline.fake_clock():
        result = asyncio.run(chain(flow, run, direction=direction, key=f"chain:{direction}:0" if direction == "backward" else "chain:forward:W9:1",
                                   batch=["W1", "None"]))
    assert (result["returned"], result["dropped_records"], result["passed_filter"]) == (2, 1, 1)
    assert len(flow.store.candidates(run["research_id"])) == 1
    assert flow.store.find_source_by_identifier("doi", "10.9999/rejected") is None
    if direction == "backward":
        assert result["unresolved"] == ["None"]
    row = rows(flow)[0]
    assert json.loads(row["error_json"])["returned"] == 2
    assert json.loads(row["connector_json"])["dropped_records"] == 1
    assert json.loads(row["connector_json"])["adapter_revision"] == 3
    assert KEY not in (flow.deps.settings.payloads_dir / row["raw_payload_path"]).read_text()
    assert KEY not in repr(tuple(flow.store.conn.execute("SELECT * FROM source_versions").fetchone()))
    assert flow.store.run(run["id"])["usage"] == {"chain_requests": 1, "chain_sends": 1}


def test_chain_drop_does_not_extend_paging(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    monkeypatch.setattr(flow_module, "CHAIN_CITING_PAGE", 2)
    monkeypatch.setattr(flow_module, "CHAIN_CITING_CAP", 3)
    sequences = []
    for drop in (False, True):
        run = chain_run(flow, new_run)
        seed = lookup_sources(flow, run, [DOI])[0]["source_version_id"]
        seen = []
        def serve(request):
            cursor, limit = request.url.params["cursor"], int(request.url.params["per_page"])
            seen.append((cursor, limit))
            payload = oa_body()
            payload["results"] *= limit
            payload["meta"]["next_cursor"] = "SYNTHETIC-next"
            if drop:
                for record in payload["results"]:
                    record["id"] = None
            return httpx.Response(200, json=payload)
        client(flow, serve)
        asyncio.run(flow._chain_requests(run, {"effort": "standard"}, {
            "seeds": [{"source_version_id": seed, "openalex_ids": ["W9"]}], "backward_batches": []}, {}))
        sequences.append(seen)
    assert sequences == [[("*", 2), ("SYNTHETIC-next", 1)]] * 2


@pytest.mark.parametrize("ending", [401, 429, "connect"])
def test_failed_chain_keeps_trace_and_budget(dispatch_flow, ending):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run, 2)
    sent = []
    def serve(request):
        sent.append(request)
        if ending == "connect":
            raise httpx.ConnectError("SYNTHETIC", request=request)
        return httpx.Response(ending, text="SYNTHETIC refusal", headers={"retry-after": "0"})
    client(flow, serve)
    with baseline.fake_clock():
        assert asyncio.run(chain(flow, run)) is None
    step = flow.store.existing_step(run["id"], "chain:forward:W9:1")
    trace = step["output"]["transport"]
    assert trace["attempts"] == len(sent) <= 2
    assert trace["sends"] == (0 if ending == "connect" else len(sent))
    assert len(trace["dispatches"]) == (2 if ending == "connect" else 1)
    assert flow.store.run(run["id"])["usage"] == {"chain_requests": len(sent), "chain_sends": trace["sends"]}
    assert step["status"] == "failed"


def test_chain_trace_survives_interrupted_backoff(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run)
    def serve(request):
        raise httpx.ConnectError("SYNTHETIC", request=request)
    client(flow, serve)
    async def interrupted(seconds):
        raise asyncio.CancelledError("SYNTHETIC interrupted backoff")
    monkeypatch.setattr(flow_module.asyncio, "sleep", interrupted)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(chain(flow, run))
    step = flow.store.existing_step(run["id"], "chain:forward:W9:1")
    assert step["output"]["transport"]["attempts"] == 1
    assert flow.store.run(run["id"])["usage"] == {"chain_requests": 1, "chain_sends": 0}


def test_chain_trace_survives_payload_failure(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run)
    client(flow, lambda r: httpx.Response(200, json=oa_body()))
    original = Path.write_text
    def fail(path, *args, **kwargs):
        if path.parent == flow.deps.settings.payloads_dir:
            raise OSError("SYNTHETIC payload fault")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(OSError):
        asyncio.run(chain(flow, run))
    assert flow.store.existing_step(run["id"], "chain:forward:W9:1")["output"]["transport"]["attempts"] == 1
    assert flow.store.run(run["id"])["usage"] == {"chain_requests": 1, "chain_sends": 1}
    assert rows(flow) == []


@pytest.mark.parametrize("recorded,code", [(None, None), ("{", "connector_provenance_invalid"),
    ("[]", "connector_provenance_invalid"), (dumps({"contract_id": contract.CONTRACT_ID, "adapter_revision": 2}), "adapter_revision_changed"),
    (dumps({"contract_id": "SYNTHETIC-unsupported", "adapter_revision": 3}), "adapter_revision_changed"),
    ("missing", "connector_provenance_invalid")])
def test_chain_continuation_refuses_only_that_seed(dispatch_flow, monkeypatch, recorded, code):
    flow, new_run = dispatch_flow
    run = chain_run(flow, new_run)
    seed = lookup_sources(flow, run, [DOI])[0]["source_version_id"]
    seen = []
    def serve(request):
        seed, cursor = request.url.params["filter"], request.url.params["cursor"]
        seen.append((seed, cursor))
        payload = oa_body()
        payload["meta"]["next_cursor"] = "SYNTHETIC-next" if seed == "cites:W9" and cursor == "*" else None
        return httpx.Response(200, json=payload)
    client(flow, serve)
    original = flow._record_chain
    def record(*args, **kwargs):
        original(*args, **kwargs)
        if args[2] == "chain:forward:W9:1":
            if recorded == "missing":
                flow.store.conn.execute("DELETE FROM search_runs WHERE step_id = ?", (args[1]["id"],))
            else:
                flow.store.conn.execute("UPDATE search_runs SET connector_json = ? WHERE step_id = ?", (recorded, args[1]["id"]))
    monkeypatch.setattr(flow, "_record_chain", record)
    seeds = {"seeds": [{"source_version_id": seed, "kind": "code", "openalex_ids": ["W9", "W10"]}],
             "backward_batches": [], "forms": {}}
    flow.store.step(run["id"], "chain_seeds", "code:chain_seeds", output=seeds)
    asyncio.run(flow._chain_requests(run, {"effort": "standard"}, seeds, {}))
    flow._chain_summary(run)
    summary = flow.store.existing_step(run["id"], "chain_summary")["output"]["requests"]
    step = flow.store.existing_step(run["id"], "chain:forward:W9:2")
    assert flow.store.run(run["id"])["status"] == "running"
    if code:
        assert seen == [("cites:W9", "*"), ("cites:W10", "*")]
        assert step["error_code"] == code and step["status"] == "failed"
        assert flow.store.conn.execute("SELECT 1 FROM search_runs WHERE step_id = ?", (step["id"],)).fetchone() is None
        assert summary["continuation_refused"] == 1 and summary["forward"] == summary["sent"] == 2
        assert flow.store.run(run["id"])["usage"] == {"chain_requests": 2, "chain_sends": 2}
    else:
        assert seen == [("cites:W9", "*"), ("cites:W9", "SYNTHETIC-next"), ("cites:W10", "*")]
        assert step["status"] == "succeeded" and summary["continuation_refused"] == 0


@pytest.mark.parametrize("ending", [200, 401, 429, "malformed"])
@pytest.mark.parametrize("key", [KEY, "redacted"])
def test_watch_citing_uses_dispatch(dispatch_flow, tmp_path, monkeypatch, ending, key):
    from watch_helpers import watch_api, add_included, create, turn
    calls = []
    original = facade.dispatch_citing
    async def spy(*args, **kwargs):
        calls.append((args[0], kwargs))
        return await original(*args, **kwargs)
    monkeypatch.setattr(facade, "dispatch_citing", spy)
    monkeypatch.setenv("OPENALEX_API_KEY", key)
    def serve(request):
        if ending == "malformed":
            return httpx.Response(200, text="SYNTHETIC malformed "+key)
        return httpx.Response(ending, json=oa_body(secret=key) if ending == 200 else {"error": "SYNTHETIC refusal "+key},
                              headers={"retry-after": "0"})
    with watch_api(tmp_path, handler=serve) as api:
        add_included(api, "WSEED")
        command = create(api, "citing_works")
        turn(api)
        assert calls and calls[0][0] == "openalex"
        assert calls[0][1]["sort"] == "publication_date:desc" and calls[0][1]["publication_date"] is True
        reads = api.watches.reads(api.watches.check(api.rid, command["check_id"], command["watch_id"]))
        assert len(reads) == 1
        assert api.store.run(command["run_id"])["usage"]["provider_requests"] == (3 if ending == 429 else 1)
        assert json.loads(reads[0]["connector_json"])["sort_sent"] == "publication_date:desc"

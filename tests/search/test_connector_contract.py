"""Registry-driven SYNTHETIC B2 conformance; no live-provider or recall evidence."""

import asyncio
import socket
import importlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import connector_baseline as baseline
from connector_baseline import SYNTHETIC_KEY, deny_network, response_spec, fake_clock
from deixis.providers import common, contract, facade, registry
from deixis.storage import db
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from test_candidate_flow import queue_kill
from test_candidate_flow import lib  # noqa: F401  (fixtures used by name)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = baseline.FIXTURES / "conformance"
FIXTURES = {p.stem: json.loads(p.read_text()) for p in FIXTURE_DIR.glob("*.json")}
FROZEN = json.loads(baseline.BASELINE.read_text())


PAIRS = [
    (provider_id, endpoint.endpoint_id)
    for provider_id, connector in facade.connectors().items()
    for endpoint in connector.descriptor.endpoints
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_network)
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.setenv(connector.key_env, SYNTHETIC_KEY)


@pytest.mark.parametrize("provider_id,endpoint_id", [("semantic_scholar", "bulk")])
def test_http_400_echoed_key_is_absent_from_outcome(provider_id, endpoint_id):
    """Groups 2(c)/5 require every error body to echo the synthetic key."""
    connector = registry.CONNECTORS[provider_id]
    script = response_spec(provider_id, endpoint_id)
    requests = []

    def transport(request):
        assert not requests, "unscripted second request"
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == script["url"]
        assert request.url.host == connector.host
        requests.append(request)
        return httpx.Response(400, json={"error": f"SYNTHETIC refusal {SYNTHETIC_KEY}"},
                              headers={"retry-after": "SYNTHETIC header " + SYNTHETIC_KEY})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            context = facade.context_for(connector, client, "synthetic@example.org")
            request = contract.SearchRequest("synthetic query", 1, endpoint=endpoint_id)
            outcome = await facade.connectors()[provider_id].search(request, context)
            return context, outcome

    with fake_clock():
        context, outcome = asyncio.run(run())

    assert len(requests) == 1
    assert outcome.status == "failed"
    assert outcome.delivery_class == "rejected_not_executed"
    assert outcome.http_status == 400
    assert outcome.access_mode == ("api_key" if connector.key_env else "keyless")
    assert not outcome.records and outcome.raw_payload is None and outcome.retries == 0
    if not connector.key_env:
        assert context.api_key is None
        assert SYNTHETIC_KEY not in str(requests[0].url)
        assert SYNTHETIC_KEY not in str(requests[0].headers)
        assert SYNTHETIC_KEY.encode() not in requests[0].content
    if outcome.access_mode == "api_key":
        assert SYNTHETIC_KEY not in str(outcome.request_description)
        assert SYNTHETIC_KEY not in str(outcome.rate_limit)
        assert SYNTHETIC_KEY not in str(outcome.error)


# These are characterization cases, never identity-conformance claims. The table
# is populated with enumerated observed outcomes and checked against the ledger.
IDENTITY_KNOWN_MISMATCHES = {
    ("openalex", None, "identity_null"): {"ledger": "identity_openalex", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1","None"]}},
    ("openalex", None, "identity_empty"): {"ledger": "identity_openalex", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1",""]}},
    ("openalex", None, "identity_number"): {"ledger": "identity_openalex", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1","17"]}},
    ("openalex", None, "identity_object"): {"ledger": "identity_openalex", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1","{'SYNTHETIC': 'id'}"]}},
    ("semantic_scholar", None, "identity_null"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","None"]}},
    ("semantic_scholar", None, "identity_empty"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("semantic_scholar", None, "identity_number"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","17"]}},
    ("semantic_scholar", None, "identity_object"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","{'SYNTHETIC': 'id'}"]}},
    ("semantic_scholar", "bulk", "identity_null"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","None"]}},
    ("semantic_scholar", "bulk", "identity_empty"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("semantic_scholar", "bulk", "identity_number"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","17"]}},
    ("semantic_scholar", "bulk", "identity_object"): {"ledger": "identity_semantic_scholar", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","{'SYNTHETIC': 'id'}"]}},
    ("crossref", None, "identity_missing"): {"ledger": "identity_crossref", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["10.9999/synthetic.1","None"]}},
    ("crossref", None, "identity_null"): {"ledger": "identity_crossref", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["10.9999/synthetic.1","None"]}},
    ("crossref", None, "identity_empty"): {"ledger": "identity_crossref", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["10.9999/synthetic.1","None"]}},
    ("arxiv", None, "identity_missing"): {"ledger": "identity_arxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["2101.00001v1",""]}},
    ("arxiv", None, "identity_null"): {"ledger": "identity_arxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["2101.00001v1",""]}},
    ("arxiv", None, "identity_empty"): {"ledger": "identity_arxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["2101.00001v1",""]}},
    ("biorxiv", None, "identity_null"): {"ledger": "identity_biorxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1","None"]}},
    ("biorxiv", None, "identity_empty"): {"ledger": "identity_biorxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1",""]}},
    ("biorxiv", None, "identity_number"): {"ledger": "identity_biorxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1","17"]}},
    ("biorxiv", None, "identity_object"): {"ledger": "identity_biorxiv", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["W1","{'SYNTHETIC': 'id'}"]}},
    ("ieee_xplore", None, "identity_missing"): {"ledger": "identity_ieee_xplore", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("ieee_xplore", None, "identity_null"): {"ledger": "identity_ieee_xplore", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("ieee_xplore", None, "identity_empty"): {"ledger": "identity_ieee_xplore", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("ieee_xplore", None, "identity_number"): {"ledger": "identity_ieee_xplore", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","17"]}},
    ("ieee_xplore", None, "identity_object"): {"ledger": "identity_ieee_xplore", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","{'SYNTHETIC': 'id'}"]}},
    ("scopus", None, "identity_missing"): {"ledger": "identity_scopus", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("scopus", None, "identity_null"): {"ledger": "identity_scopus", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("scopus", None, "identity_empty"): {"ledger": "identity_scopus", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("scopus", None, "identity_number"): {"ledger": "identity_scopus", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","17"]}},
    ("scopus", None, "identity_object"): {"ledger": "identity_scopus", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","{'SYNTHETIC': 'id'}"]}},
    ("core", None, "identity_missing"): {"ledger": "identity_core", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["1",""]}},
    ("core", None, "identity_null"): {"ledger": "identity_core", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["1",""]}},
    ("core", None, "identity_empty"): {"ledger": "identity_core", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["1",""]}},
    ("core", None, "identity_number"): {"ledger": "identity_core", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["1","17"]}},
    ("core", None, "identity_object"): {"ledger": "identity_core", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["1","{'SYNTHETIC': 'id'}"]}},
    ("serpapi", None, "identity_missing"): {"ledger": "identity_serpapi", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","None"]}},
    ("serpapi", None, "identity_null"): {"ledger": "identity_serpapi", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","None"]}},
    ("serpapi", None, "identity_empty"): {"ledger": "identity_serpapi", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1",""]}},
    ("serpapi", None, "identity_number"): {"ledger": "identity_serpapi", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","17"]}},
    ("serpapi", None, "identity_object"): {"ledger": "identity_serpapi", "owner": "B4 admission (D194)", "expected": {"status": "completed", "record_ids": ["synthetic1","{'SYNTHETIC': 'id'}"]}},
}


def endpoint_fixture(fixture, endpoint_id):
    return next(e for e in fixture["endpoints"] if e["endpoint_id"] == endpoint_id)


def required_cases(provider_id, endpoint_id, fixture):
    """Coverage follows declared native shapes, access and paging, including future adapters."""
    descriptor = facade.connectors()[provider_id].descriptor
    endpoint = next(e for e in descriptor.endpoints if e.endpoint_id == endpoint_id)
    names = {"positive", "unpaged", "first_page", "second_page", "short_page", "empty", "non_json_200"}
    if fixture["container"]["format"] == "json":
        names |= {"root_" + n for n in ("array", "null", "string", "number")}
        names |= {"container_" + n for n in ("null", "object", "string", "number", "item_number", "item_string")}
        names |= {"empty_object", "absent_container"}
    if endpoint.paging == "cursor":
        names |= {"token_" + n for n in ("null", "empty", "number", "object", "absent", "repeated")}
    for stage in fixture.get("failure_stages", ["search"]):
        for mode in (["configured", "keyless"] if descriptor.key_env and not descriptor.key_required else ["configured"]):
            suffix = ("_fetch" if stage == "fetch" else "") + ("_keyless" if mode == "keyless" else "")
            names |= {"http_" + str(c) + suffix for c in (400, 401, 403, 500, 503)}
            names |= {n + suffix for n in ("connect", "read_timeout", "quota")}
            names |= {"rate_" + n + suffix for n in ("unstated", "one", "long", "malformed", "negative", "nan", "inf", "minus_inf")}
    names |= {"identity_" + n for n in fixture.get("identity_shapes", [])}
    return names


def required_capability_cases(pid, capability):
    names = {"positive", "empty" if capability == "citing_works" else "not_found", "http_401", "http_500",
             "rate_unstated", "rate_exhausted", "quota", "connect", "read_timeout", "non_json_200",
             "wrong_root", "wrong_container"}
    if registry.CONNECTORS[pid].key_env:
        names.add("key_echo")
    if pid == "semantic_scholar":
        names |= {"wrong_length", "abstract_not_string", "reordered", "repeated_doi",
                  "repeated_conflicting", "repeated_null"}
    if pid == "scopus":
        names.add("other_doi")
    if pid == "crossref":
        names.add("http_404")
    if capability == "citing_works":
        names |= {"next_cursor", "last_page"}
    if capability == "id_lookup":
        names |= {"partial", "bad_identity"}
    return names


def check_coverage(fixtures):
    assert set(fixtures) == set(registry.CONNECTORS), f"missing fixtures: {set(registry.CONNECTORS) - set(fixtures)}; extra: {set(fixtures) - set(registry.CONNECTORS)}"
    for pid, f in facade.connectors().items():
        fixture = fixtures[pid]
        assert fixture["provider_id"] == pid and fixture["synthetic"] is True
        endpoints = [e["endpoint_id"] for e in fixture["endpoints"]]
        assert len(endpoints) == len(set(endpoints))
        assert set(endpoints) == {e.endpoint_id for e in f.descriptor.endpoints}, pid
        for capability in contract.CAPABILITIES:
            proof = fixture["capabilities"][capability]
            if capability in f.descriptor.capabilities:
                assert isinstance(proof, dict) and set(proof) == {"positive", "failure"}, (pid, capability)
                groups = fixture["endpoints"] if capability == "search" else [{"cases": fixture["capability_cases"][capability]}]
                for ep in groups:
                    names = {c["name"] for c in ep["cases"]}
                    assert {proof["positive"], proof["failure"]} <= names
                if capability != "search":
                    assert len(names) == len(fixture["capability_cases"][capability]), (pid, capability)
                    assert required_capability_cases(pid, capability) <= names, (pid, capability)
            else:
                assert proof == "unsupported", (pid, capability)
        assert set(fixture.get("capability_cases", {})) == set(registry.CONNECTORS[pid].capabilities)
        for ep in fixture["endpoints"]:
            names = [c["name"] for c in ep["cases"]]
            assert len(names) == len(set(names)), pid
            missing = required_cases(pid, ep["endpoint_id"], fixture) - set(names)
            assert not missing, f"{pid}/{ep['endpoint_id']}: missing {sorted(missing)}"
            assert {c["group"] for c in ep["cases"]} >= {3, 4, 5}, pid


def body_of(spec, prefix=""):
    if prefix + "body" in spec:
        body = spec[prefix + "body"]
        if spec.get("name") == "root_string":
            return json.dumps(body)
        return body if isinstance(body, str) else json.dumps(body)
    return (baseline.FIXTURES / "responses" / spec[prefix + "body_file"]).read_text()


def assert_auth(request, fixture, key):
    auth = fixture["auth"]
    expected = key if auth and key else None
    params, headers = request.url.params, request.headers
    if auth:
        if "param" in auth:
            assert params.get_list(auth["param"]) == ([expected] if expected else []), fixture["provider_id"]
        else:
            assert headers.get(auth["header"]) == (auth["prefix"] + expected if expected else None), fixture["provider_id"]
    # Strip only the fixture-declared auth location, then look everywhere else.
    other_params = [(k, v) for k, v in params.multi_items() if not auth or k != auth.get("param")]
    other_headers = [(k, v) for k, v in headers.multi_items() if not auth or k.lower() != auth.get("header", "").lower()]
    for value in (request.url.path, other_params, other_headers, request.content):
        assert SYNTHETIC_KEY not in str(value)


def replay_case(provider_id, endpoint_id, fixture, case, *, direct=False, key=SYNTHETIC_KEY, dispatched=False):
    """Real search parser; native success bodies, strict subrequest order and finite script."""
    connector = registry.CONNECTORS[provider_id]
    ep = endpoint_fixture(fixture, endpoint_id)
    key = key if connector.key_env else None
    if case.get("mode") == "keyless":
        key = None
    requests = []
    failing = "http_status" in case or "exception" in case
    stage = case.get("stage", "search")
    attempts = 1 + case["expected"].get("retries", 0) if failing else 1
    search_url = fixture.get("url") or response_spec(provider_id, endpoint_id)["url"]
    fetch_url = fixture.get("fetch_url")
    script = ([(search_url, False)] if stage == "fetch" else []) + [(fetch_url if stage == "fetch" else search_url, failing)] * attempts
    if not failing and fetch_url and case["expected"].get("status") not in {"parse_error", "zero_results"}:
        script += [(fetch_url, False)]
    # EFetch malformed/identity cases explicitly override the fetch body.
    if not failing and fetch_url and ("fetch_body" in case or "fetch_body_file" in case):
        script = [(search_url, False), (fetch_url, False)]
    remaining = list(script)

    def transport(request):
        assert remaining, f"unscripted request {provider_id}/{endpoint_id}/{case['name']}"
        url, fail = remaining.pop(0)
        assert request.method == "GET" and str(request.url.copy_with(query=None)) == url
        assert request.url.host == connector.host
        assert_auth(request, fixture, key)
        requests.append(request)
        if fail and "exception" in case:
            cls = httpx.ConnectError if case["exception"] == "connect" else httpx.ReadTimeout
            raise cls("SYNTHETIC transport refusal", request=request)
        status = case.get("http_status", 200) if fail else 200
        headers = {}
        if case.get("echo") or case["name"] == "positive":
            header = fixture.get("rate_header", "retry-after")
            if header != "retry-after" or not failing or "retry_after" not in case:
                headers[header] = "SYNTHETIC header " + SYNTHETIC_KEY
        if case.get("retry_after") is not None:
            headers["retry-after"] = case["retry_after"]
        # Missing Retry-After means bounded unstated waits, not the echo header.
        if "retry_after" in case and case["retry_after"] is None:
            headers.pop("retry-after", None)
        if "error_detail" in case:
            headers["x-error-detail-header"] = case["error_detail"] + " " + SYNTHETIC_KEY
        if fail:
            error = {"error": {"code": "insufficient_quota", "message": "SYNTHETIC daily quota exhausted " + SYNTHETIC_KEY}} if case.get("quota") else {"error": "SYNTHETIC refusal " + SYNTHETIC_KEY}
            return httpx.Response(status, json=error, headers=headers)
        if request.url.path == httpx.URL(fetch_url).path if fetch_url else False:
            body = body_of(case, "fetch_") if "fetch_body" in case or "fetch_body_file" in case else body_of(ep, "fetch_")
        else:
            body = body_of(case) if "body" in case or "body_file" in case else body_of(ep)
        return httpx.Response(200, text=body, headers=headers)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            options = {} if case["name"] == "unpaged" else {k: v for k, v in connector.sw_options.items() if k in {o.name for o in next(e for e in facade.connectors()[provider_id].descriptor.endpoints if e.endpoint_id == endpoint_id).options}}
            kwargs = {"cursor": case.get("cursor"), "max_rate_limit_retries": 2, **options}
            if endpoint_id is not None:
                kwargs["endpoint"] = endpoint_id
            with common.collect_transport() as entries:
                if dispatched:
                    result = await facade.dispatch_search(provider_id, client, baseline.QUERY, case.get("limit", 1),
                                                         key, baseline.CONTACT, **kwargs)
                    outcome, entries = result.outcome, result.transport
                elif direct:
                    outcome = await connector.search(client, baseline.QUERY, case.get("limit", 1), key, baseline.CONTACT, **kwargs)
                else:
                    request = contract.SearchRequest(baseline.QUERY, case.get("limit", 1), endpoint=endpoint_id,
                                                    cursor=case.get("cursor"), max_rate_limit_retries=2, options=options)
                    outcome = await facade.connectors()[provider_id].search(request, contract.ConnectorContext(client, key, baseline.CONTACT))
            assert sum(e["attempts"] for e in entries) == len(requests)
            connect_failures = attempts if case.get("exception") == "connect" else 0
            assert sum(e["sends"] for e in entries) == len(requests) - connect_failures
            assert sum(e["retries"] for e in entries) == outcome.retries
            assert len(entries) <= connector.requests_per_search
            assert all(0 <= e["retries"] <= 2 for e in entries)
            assert SYNTHETIC_KEY not in json.dumps(entries)
            return outcome
    with fake_clock() as waits:
        outcome = asyncio.run(run())
    assert not remaining, (provider_id, endpoint_id, case["name"], remaining)
    if outcome.access_mode == "api_key":
        for value in (outcome.request_description, outcome.error, outcome.rate_limit, outcome.raw_payload,
                      [r.raw for r in outcome.records]):
            assert SYNTHETIC_KEY not in str(value)
    return outcome, requests, waits


def check_case(provider_id, endpoint_id, fixture, case):
    outcome, requests, waits = replay_case(provider_id, endpoint_id, fixture, case)
    expected = case["expected"]
    for field, value in expected.items():
        if field == "record_count":
            assert len(outcome.records) == value
        elif field == "records":
            assert len(outcome.records) == len(value)
            for record, mapping in zip(outcome.records, value):
                for name, target in mapping.items():
                    actual = record.raw[name[4:]] if name.startswith("raw.") else getattr(record, name)
                    assert actual == target, (provider_id, case["name"], name, actual, target)
        elif field == "record_ids":
            assert [r.provider_record_id for r in outcome.records] == value
        else:
            assert getattr(outcome, field) == value, (provider_id, endpoint_id, case["name"], field)
    if case.get("ledger") == "scopus_count_unmapped":
        # scopus_count_unmapped is an unscheduled enhancement: this adapter maps no count.
        assert outcome.records[0].cited_by_count is None
    assert outcome.status in contract.SEARCH_STATUSES
    if case["name"].startswith("rate_") or case["name"].startswith("ieee_"):
        endpoint = next(e for e in facade.connectors()[provider_id].descriptor.endpoints if e.endpoint_id == endpoint_id)
        retry_waits = [1.0] * expected["retries"] if case.get("retry_after") == "1" else [endpoint.retry.unstated_wait * (i + 1) for i in range(expected["retries"])]
        expected_waits = []
        for wait in retry_waits:
            expected_waits.append(wait)
            if endpoint.retry.shared_gate and endpoint.retry.min_interval > wait:
                expected_waits.append(endpoint.retry.min_interval - wait)
        assert waits == expected_waits
    elif case.get("quota"):
        assert waits == []
    if fixture.get("fetch_url") and (case.get("stage") == "fetch" or len(requests) == 2):
        assert outcome.raw_payload is not None and "search" in outcome.raw_payload
        assert outcome.provider_total == int(json.loads(body_of(endpoint_fixture(fixture, endpoint_id)))["esearchresult"]["count"]), case["name"]
        assert "esearch.fcgi" in outcome.request_description and "efetch.fcgi" in outcome.request_description
    if case["name"] in {"unpaged", "first_page", "second_page", "ignored_cursor"}:
        shape = "next_page" if case["name"] == "second_page" else "first_page" if case["name"] == "first_page" else "kill_search" if endpoint_id else "unpaged"
        assert baseline.recorded_request(requests[0])["params"] == endpoint_fixture(fixture, endpoint_id)["request_params"][shape]
    if case["name"].startswith("identity_"):
        # D252 semantic search uses the identical OpenAlex record parser.
        identity_endpoint = None if provider_id == "openalex" and endpoint_id == "semantic" else endpoint_id
        mismatch = IDENTITY_KNOWN_MISMATCHES.get((provider_id, identity_endpoint, case["name"]))
        if mismatch:
            assert expected == mismatch["expected"] and case["ledger"] == mismatch["ledger"]
        else:
            assert outcome.status == "parse_error" or all(r.provider_record_id not in ("", "None", None) and not r.provider_record_id.startswith("{") for r in outcome.records)


CASES = [(pid, e.endpoint_id, FIXTURES[pid], case)
         for pid, f in facade.connectors().items() if pid in FIXTURES for e in f.descriptor.endpoints
         for ep in FIXTURES[pid]["endpoints"] if ep["endpoint_id"] == e.endpoint_id for case in ep["cases"]]
# A representative sample of CASES (the full grid was cut in the stage-5 test simplification).
SAMPLE_IDS = {"openalex/default/g3/positive", "openalex/semantic/g5/root_array", "semantic_scholar/bulk/g3/positive"}
CONFORMANCE_SAMPLE = [(p, e, f, c) for p, e, f, c in CASES if f"{p}/{e or 'default'}/g{c['group']}/{c['name']}" in SAMPLE_IDS]


@pytest.mark.provider_pacing
@pytest.mark.parametrize("provider_id,endpoint_id,fixture,case", CONFORMANCE_SAMPLE,
                         ids=[f"{p}/{e or 'default'}/g{c['group']}/{c['name']}" for p,e,f,c in CONFORMANCE_SAMPLE])
def test_conformance_case(provider_id, endpoint_id, fixture, case):
    check_case(provider_id, endpoint_id, fixture, case)
    replay_case(provider_id, endpoint_id, fixture, case, direct=True)
    replay_case(provider_id, endpoint_id, fixture, case, dispatched=True)


def test_registration_schema_and_purity(memory_keychain, tmp_path):
    boundary = importlib.import_module("test_connector_boundary")
    boundary.test_vocabulary_and_frozen_types()
    before_env, before_keys = dict(os.environ), dict(memory_keychain.items)
    before_files = list(tmp_path.iterdir())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(deny_network)) as client:
            for pid, f in facade.connectors().items():
                descriptor = asdict(f.descriptor)
                assert descriptor["provider_id"] == pid and f.descriptor.contract_id in contract.SUPPORTED_CONTRACTS
                assert f.descriptor.order == list(registry.CONNECTORS).index(pid)
                context = facade.context_for(registry.CONNECTORS[pid], client, baseline.CONTACT)
                f.access(context)
                for lookup in (contract.LookupRequest(doi="10.9999/synthetic"), contract.LookupRequest(provider_record_id="SYNTHETIC")):
                    operation = "doi_lookup" if lookup.doi is not None else "id_lookup"
                    if operation in f.descriptor.capabilities:
                        continue
                    result = await f.lookup(lookup, context)
                    assert result.status == "unsupported" and result.outcome is None and result.answer is None
    asyncio.run(run())
    assert registry.Connector("synthetic", deny_network, 1).adapter_revision == 1
    assert all(c.adapter_revision == (3 if c.provider_id == "openalex" else 2) for c in registry.CONNECTORS.values())
    enum = json.loads((ROOT / "deixis/contracts/research/common.schema.json").read_text())["$defs"]["provider_id"]["enum"]
    assert set(enum) == set(registry.CONNECTORS)
    assert os.environ == before_env and memory_keychain.items == before_keys and list(tmp_path.iterdir()) == before_files


@pytest.mark.parametrize("provider_id,endpoint_id", [("openalex", None)])
@pytest.mark.parametrize("key", [None])
@pytest.mark.parametrize("direct", [False])
def test_required_access_sends_nothing(provider_id, endpoint_id, key, direct):
    connector = registry.CONNECTORS[provider_id]
    if not connector.key_required:
        # Keyless-capable providers exercise absence using the same native positive case.
        case = endpoint_fixture(FIXTURES[provider_id], endpoint_id)["cases"][0]
        outcome, requests, _ = replay_case(provider_id, endpoint_id, FIXTURES[provider_id], case, key=key, direct=direct)
        assert outcome.access_mode == "keyless" and requests
        return
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(deny_network)) as http:
            if direct:
                return await connector.search(http, baseline.QUERY, 1, key, baseline.CONTACT, **({"endpoint": endpoint_id} if endpoint_id else {}))
            return await facade.connectors()[provider_id].search(contract.SearchRequest(baseline.QUERY, 1, endpoint=endpoint_id), contract.ConnectorContext(http, key, baseline.CONTACT))
    outcome = asyncio.run(run())
    assert (outcome.status, outcome.delivery_class, outcome.access_mode) == ("not_configured", "before_send", "not_configured")
    assert outcome.records == [] and outcome.raw_payload is None and outcome.http_status is None and outcome.retries == 0 and outcome.error_kind is None


@pytest.fixture
def dispatch_flow(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    http = httpx.AsyncClient(transport=httpx.MockTransport(deny_network))
    deps = SimpleNamespace(store=store, http=http,
                           settings=SimpleNamespace(contact_email=baseline.CONTACT, payloads_dir=tmp_path / "payloads"))
    flow = ResearchFlow(deps)
    def new_run(providers=("ieee_xplore",)):
        rid = store.create_research("SYNTHETIC?", "academic", "standard", list(providers), "fake", "m", "en")
        run = store.create_run(rid, "discovery", {"max_provider_requests": 1000,
                                                "inspection": {"policy": "small_batch_fused_v1"}}, None)
        store.update_run(run["id"], status="running")
        return store.run(run["id"])
    yield flow, new_run
    asyncio.run(http.aclose())
    conn.close()


def prepare_kill(lib, monkeypatch):
    monkeypatch.setenv("IEEE_API_KEY", SYNTHETIC_KEY)
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["ieee_xplore"]', lib.rid))
    run = queue_kill(lib)
    query = {"provider_id":"ieee_xplore","query_text":baseline.QUERY}
    search = lib.candidate_store.start_kill_search(lib.rid, run["target"]["candidate_version_id"], run["id"],
              query_block={"SYNTHETIC":True}, rendered_queries=[query], skipped_terms=[], selection={})
    step = lib.store.step(run["id"], "kill-search:1", "provider_search:ieee_xplore")
    return run, query, search, step


def test_same_title_different_doi_preserves_distinct_sources(dispatch_flow):
    from test_provider_records import record
    flow, _ = dispatch_flow
    first, _ = flow.store.upsert_provider_source("openalex", record("W1", doi="10.9999/one"), None)
    second, _ = flow.store.upsert_provider_source("openalex", record("W2", doi="10.9999/two"), None)
    assert first != second
    assert flow.store.find_source_by_identifier("doi", "10.9999/one") == first
    assert flow.store.find_source_by_identifier("doi", "10.9999/two") == second
    v1, _ = flow.store.upsert_provider_source("arxiv", replace(record("2101.00001v1", doi="10.48550/arxiv.2101.00001",
                                merge_by_doi=False, arxiv="2101.00001", arxiv_version="2101.00001v1"), version_label="arXiv v1"), None)
    v2, _ = flow.store.upsert_provider_source("arxiv", replace(record("2101.00001v2", doi="10.48550/arxiv.2101.00001",
                                merge_by_doi=False, arxiv="2101.00001", arxiv_version="2101.00001v2"), version_label="arXiv v2"), None)
    assert v1 != v2
    assert flow.store.find_source_by_identifier("arxiv", "2101.00001v1") == v1
    assert flow.store.find_source_by_identifier("arxiv", "2101.00001v2") == v2

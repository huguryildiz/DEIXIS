"""Registry-driven SYNTHETIC B2 conformance; no live-provider or recall evidence."""

import asyncio
import socket
import copy
import importlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import connector_baseline as baseline
import fast_search_helpers
from connector_baseline import SYNTHETIC_KEY, deny_network, response_spec, fake_clock
from deixis.providers import common, contract, facade, registry
from deixis.providers.common import SearchOutcome
from deixis.storage import db
from deixis.workflow.flow import ResearchFlow, Page
from deixis.workflow.store import Store
from test_candidate_flow import lib as candidate_lib, queue_kill

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


@pytest.mark.parametrize("provider_id,endpoint_id", PAIRS)
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

B4_EVIDENCE = {
    "b4_merge_version": "test_connector_dispatch::test_merge_and_arxiv_versions",
    "b4_resume_paging": "test_connector_dispatch::test_resume_provenance",
    "l": "test_connector_dispatch::test_payload_echo_recorded",
    "b4_payload_write": "test_connector_dispatch::test_payload_write_failure_publishes_nothing",
    "b4_limit_provenance": "test_connector_dispatch::test_limit_discovery_and_suppression",
    "b4_s2_binding": "test_connector_dispatch::test_s2_binding",
    "b4_stored_revision": "test_connector_dispatch::test_resume_provenance",
}

COVERED_ELSEWHERE = {
    "closed_vocabulary": "test_connector_boundary::test_vocabulary_and_frozen_types",
    "descriptor_completeness": "test_connector_boundary::test_descriptors_registry_and_module_policy",
    "purity": "test_connector_boundary::test_local_purity_and_secrets",
    "invalid_request": "test_connector_boundary::test_search_validation_before_send",
    "module_value_errors": "test_connector_boundary::test_baseline_equivalence",
    "doi_merge_mappings": "test_provider_records::test_same_doi_from_two_providers_is_one_source_with_both_mappings",
    "arxiv_version_boundary": "test_provider_records::test_records_of_one_arxiv_preprint_are_versions_of_one_work_with_one_candidate",
    "resume_pages_registry": "test_fast_path_search::test_frozen_plan_cap_rotation_page_admission_and_resume",
    "resume_lookup_helpers": "test_lookup_flow::test_a_resumed_run_asks_no_doi_twice",
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


@pytest.mark.provider_pacing
@pytest.mark.parametrize("provider_id,endpoint_id,fixture,case", CASES,
                         ids=[f"{p}/{e or 'default'}/g{c['group']}/{c['name']}" for p,e,f,c in CASES])
def test_conformance_case(provider_id, endpoint_id, fixture, case):
    check_case(provider_id, endpoint_id, fixture, case)
    replay_case(provider_id, endpoint_id, fixture, case, direct=True)
    replay_case(provider_id, endpoint_id, fixture, case, dispatched=True)


def test_exact_coverage():
    check_coverage(FIXTURES)


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
    enum = json.loads((ROOT / "contracts/research/common.schema.json").read_text())["$defs"]["provider_id"]["enum"]
    assert set(enum) == set(registry.CONNECTORS)
    assert os.environ == before_env and memory_keychain.items == before_keys and list(tmp_path.iterdir()) == before_files


@pytest.mark.parametrize("provider_id,endpoint_id", PAIRS)
@pytest.mark.parametrize("key", [None, ""])
@pytest.mark.parametrize("direct", [False, True])
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


def test_missing_fixture_is_named(monkeypatch):
    synthetic = replace(registry.CONNECTORS["openalex"], provider_id="synthetic")
    monkeypatch.setitem(registry.CONNECTORS, "synthetic", synthetic)
    with pytest.raises(AssertionError, match="synthetic"):
        check_coverage(FIXTURES)


def test_pending_and_existing_evidence():
    ledger = (ROOT / "docs/product/connector-onboarding.md").read_text()
    rows = {line.split("|")[1].strip().split(".")[0]: line.split("|")[-2].strip()
            for line in ledger.splitlines() if line.startswith("| ")}
    assert rows["option_types"] == "B3a fixed (D179)"
    for name, target in B4_EVIDENCE.items():
        assert rows[name] == "B4 fixed (D194)", name
        module, function = target.split("::")
        assert callable(getattr(importlib.import_module(module), function)), target
    assert rows["b4_resume_lookup"] == "G1-F1 fixed (D201)"
    for name, entry in IDENTITY_KNOWN_MISMATCHES.items():
        assert rows[entry["ledger"]] == entry["owner"] == "B4 admission (D194)", name
    for target in COVERED_ELSEWHERE.values():
        module, function = target.split("::")
        assert callable(getattr(importlib.import_module(module), function)), target


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


@pytest.mark.parametrize("key", [None, SYNTHETIC_KEY])
def test_dispatch_reads_the_key_once_per_attempt(dispatch_flow, monkeypatch, key):
    flow, new_run = dispatch_flow
    run = new_run()
    reads, sends = [], []
    def api_key():
        reads.append(True)
        return key if len(reads) == 1 else None if key else SYNTHETIC_KEY
    async def search(http, query, limit, checked, contact, **kwargs):
        sends.append(checked)
        await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "api_key", secrets=(checked,))
        return SearchOutcome("zero_results", None, "SYNTHETIC", "api_key")
    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    connector = replace(registry.CONNECTORS["ieee_xplore"], search=search)
    monkeypatch.setitem(registry.CONNECTORS, "ieee_xplore", connector)
    monkeypatch.setattr(registry.Connector, "api_key", lambda self: api_key())
    outcome = asyncio.run(flow._send_search(run["id"], connector, {"query_text": baseline.QUERY}, 1))
    outcome = outcome.outcome if isinstance(outcome, facade.Dispatched) else outcome
    assert len(reads) == 1
    assert sends == ([key] if key else [])
    assert outcome.status == ("zero_results" if key else "not_configured")
    assert flow.store.run(run["id"])["usage"].get("provider_requests", 0) == (1 if key else 0)


def test_transient_retry_refreshes_snapshot_before_counting(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run()
    reads, sends = [], []
    def api_key():
        reads.append(True)
        return SYNTHETIC_KEY if len(reads) == 1 else None
    async def search(*args, **kwargs):
        sends.append(args[3])
        _, outcome = await common.send(args[0], "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "api_key")
        return outcome
    def refused(request):
        raise httpx.ConnectError("SYNTHETIC", request=request)
    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(refused))
    connector = replace(registry.CONNECTORS["ieee_xplore"], search=search)
    monkeypatch.setitem(registry.CONNECTORS, "ieee_xplore", connector)
    monkeypatch.setattr(registry.Connector, "api_key", lambda self: api_key())
    with fake_clock() as waits:
        outcome = asyncio.run(flow._send_search(run["id"], connector, {"query_text": baseline.QUERY}, 1))
    assert len(reads) == 2 and sends == [SYNTHETIC_KEY] and waits == [1.5]
    assert outcome.status == "not_configured" and flow.store.run(run["id"])["usage"]["provider_requests"] == 1
    assert flow._quota_out == {}


@pytest.mark.parametrize("paged", [False, True])
def test_recording_not_configured_ignores_payload_and_records(dispatch_flow, paged):
    flow, new_run = dispatch_flow
    run = new_run()
    step = flow.store.step(run["id"], "unsent", "provider_search:ieee_xplore")
    outcome = SearchOutcome("not_configured", "before_send", "SYNTHETIC unsent", "not_configured",
                            raw_payload={"SYNTHETIC": "must not write"})
    page = Page(0, "*", 0, None, 10, 0, "unsent", 10) if paged else None
    failure = flow._record_search(run, step, {"provider_id":"ieee_xplore", "query_text":baseline.QUERY}, outcome, 1, page=page)
    saved = flow.store.existing_step(run["id"], "unsent")
    assert saved["output"] == {"status":"not_configured", "result_count":0}
    assert json.loads(saved["error_json"]) == {"error":"SYNTHETIC unsent", "http_status":None}
    assert failure == ("provider_not_configured", {"provider":"ieee_xplore","http_status":None,"error_kind":None,"retry_after":None,
                                                    "service_kind": "needs_key", "reset_at": None})
    assert flow.store.conn.execute("SELECT count(*) FROM search_runs").fetchone()[0] == 0
    assert not flow.deps.settings.payloads_dir.exists()


def prepare_kill(lib, monkeypatch):
    monkeypatch.setenv("IEEE_API_KEY", SYNTHETIC_KEY)
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["ieee_xplore"]', lib.rid))
    run = queue_kill(lib)
    query = {"provider_id":"ieee_xplore","query_text":baseline.QUERY}
    search = lib.candidate_store.start_kill_search(lib.rid, run["target"]["candidate_version_id"], run["id"],
              query_block={"SYNTHETIC":True}, rendered_queries=[query], skipped_terms=[], selection={})
    step = lib.store.step(run["id"], "kill-search:1", "provider_search:ieee_xplore")
    return run, query, search, step


def test_kill_search_missing_key_charges_no_reservation(candidate_lib, monkeypatch):
    lib = candidate_lib
    run, query, search, step = prepare_kill(lib, monkeypatch)
    monkeypatch.delenv("IEEE_API_KEY")
    before = lib.store.run(run["id"])["usage"].get("provider_requests", 0)
    outcome, trace = asyncio.run(lib.flow._kill_search_request(run, query))
    assert outcome.status == "not_configured" and outcome.delivery_class == "before_send"
    assert lib.store.run(run["id"])["usage"].get("provider_requests", 0) == before
    lib.flow._kill_search_record_query(run, search, step, 1, query, outcome, trace)
    row = lib.candidate_store.queries(search["id"])[0]
    assert row["status"] == "failed" and row["error_code"] == "not_configured" and row["record_count"] == 0
    assert lib.seen == []


@pytest.mark.parametrize("key", [None, SYNTHETIC_KEY])
def test_kill_dispatch_reads_the_key_once_per_attempt(candidate_lib, monkeypatch, key):
    lib = candidate_lib
    run, query, _, _ = prepare_kill(lib, monkeypatch)
    reads, sends = [], []
    def api_key():
        reads.append(True)
        return key if len(reads) == 1 else None if key else SYNTHETIC_KEY
    async def search(http, query, limit, checked, contact, **kw):
        sends.append(checked)
        return SearchOutcome("zero_results", None, "SYNTHETIC", "api_key")
    source = replace(registry.CONNECTORS["ieee_xplore"], search=search)
    monkeypatch.setattr(registry.Connector, "api_key", lambda self: api_key())
    monkeypatch.setitem(registry.CONNECTORS, "ieee_xplore", source)
    outcome, trace = asyncio.run(lib.flow._kill_search_request(run, query))
    assert len(reads) == 1 and sends == ([key] if key else [])
    outcome = outcome.outcome if isinstance(outcome, facade.Dispatched) else outcome
    assert outcome.status == ("zero_results" if key else "not_configured")
    reserve = run["target"]["transport"]["providers"][0]["requests_per_search"] * (1 + run["target"]["transport"]["providers"][0]["rate_limit_retries"])
    assert lib.store.run(run["id"])["usage"].get("provider_requests",0) == (reserve if key else 0)
    if key:
        # A refused reservation is still one attempt: describing it must not reread the key.
        reads.clear()
        sends.clear()
        run["budget"]["max_provider_requests"] = 0
        refused, trace = asyncio.run(lib.flow._kill_search_request(run, query))
        assert refused.status == "transport_budget" and refused.access_mode == "api_key"
        assert len(reads) == 1 and sends == []
        assert lib.store.run(run["id"])["usage"]["provider_requests"] == reserve


def test_pubmed_efetch_quota_stops_later_searches(dispatch_flow, monkeypatch):
    flow, new_run = dispatch_flow
    run = new_run(("pubmed",))
    requests = []
    def transport(request):
        requests.append(request.url.path)
        assert len(requests) <= 2
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, text=(baseline.FIXTURES / "responses/pubmed-1.json").read_text())
        return httpx.Response(429, json={"error":"SYNTHETIC daily quota exhausted"})
    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    source = registry.CONNECTORS["pubmed"]
    try:
        first = asyncio.run(flow._send_search(run["id"], source, {"query_text":"SYNTHETIC first"}, 1))
        first = first.outcome if isinstance(first, facade.Dispatched) else first
        assert first.error_kind == "quota_exhausted"
        second = asyncio.run(flow._send_search(run["id"], source, {"query_text":"SYNTHETIC later"}, 1))
        assert second.error_kind == "quota_exhausted" and second.delivery_class == "before_send"
        assert len(requests) == 2 and flow.store.run(run["id"])["usage"]["provider_requests"] == 2
        assert flow.store.run(run["id"])["usage"]["provider_sends"] == 2
    finally:
        asyncio.run(flow.deps.http.aclose())


def test_repeated_cursor_stops_within_read_limit(dispatch_flow, monkeypatch):
    from test_provider_records import record
    flow, new_run = dispatch_flow
    run = new_run(("openalex",))
    calls = []
    async def search(*args, **kwargs):
        calls.append(kwargs["cursor"])
        return SearchOutcome("completed", None, "SYNTHETIC repeated token", "keyless", records=[record(f"W{len(calls)}", doi=None)], next_cursor="*")
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(registry.CONNECTORS["openalex"], search=search, key_env=None, max_results=1))
    # The fast path's record cap bounds a provider that repeats its cursor; 3 slots of 1 record each.
    asyncio.run(fast_search_helpers.search(flow, run, [{"provider_id":"openalex","query_text":baseline.QUERY}], cap=3, page_size=1))
    assert calls == ["*"] * 3
    rows = [dict(r) for r in flow.store.conn.execute("SELECT * FROM search_runs WHERE run_id = ? ORDER BY page_number", (run["id"],))]
    assert len(rows) == 3 and rows[-1]["stop_reason"] == "record_cap" and rows[-1]["read_total"] == 3


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


def test_complete_synthetic_connector_needs_no_suite_branch(monkeypatch):
    async def search(client, query, limit, key, contact, **kw):
        outcome = await registry.openalex.search_works(client, query, limit, key, contact, **kw)
        if any(not isinstance(r.raw.get("id"), str) or not r.raw["id"] for r in outcome.records):
            outcome.status, outcome.records = "parse_error", []
        return outcome
    source = replace(registry.CONNECTORS["openalex"], provider_id="synthetic", search=search, capabilities={})
    monkeypatch.setitem(registry.CONNECTORS, "synthetic", source)
    monkeypatch.setitem(facade.query_rules.NAMES, "synthetic", "SYNTHETIC")
    fixture = copy.deepcopy(FIXTURES["openalex"])
    fixture.update(provider_id="synthetic", url=registry.openalex.WORKS_URL)
    fixture["capability_cases"] = {}
    for operation in ("doi_lookup", "id_lookup", "citing_works"):
        fixture["capabilities"][operation] = "unsupported"
    for ep in fixture["endpoints"]:
        for case in ep["cases"]:
            if case["name"].startswith("identity_"):
                case["expected"] = {"status":"parse_error", "record_ids":[]}
                case.pop("ledger", None)
                case.pop("characterization", None)
    check_coverage(FIXTURES | {"synthetic":fixture})
    for ep in fixture["endpoints"]:
        for case in ep["cases"]:
            check_case("synthetic", ep["endpoint_id"], fixture, case)
    async def unsupported():
        async with httpx.AsyncClient(transport=httpx.MockTransport(deny_network)) as client:
            f = facade.connectors()["synthetic"]
            result = await f.lookup(contract.LookupRequest(doi="10.9999/synthetic"), contract.ConnectorContext(client, None, None))
            assert result.status == "unsupported" and result.outcome is None
    asyncio.run(unsupported())

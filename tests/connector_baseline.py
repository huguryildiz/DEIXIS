"""SYNTHETIC replay freeze on 1fb1743. Regenerate explicitly, never from a test.

PYTHONPATH=backend:. .venv/bin/python tests/connector_baseline.py --write
"""

import argparse
import asyncio
import json
import socket
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import httpx

from deixis.domain import canonical
from deixis.providers import arxiv, common, pacing, query_compiler, query_rules, registry, semantic_scholar
from deixis.providers import contract, facade

FIXTURES = Path(__file__).parent / "fixtures" / "connectors"
BASELINE = FIXTURES / "baseline.json"
SYNTHETIC_KEY = "SYNTHETIC-B1-SECRET-DO-NOT-STORE"
QUERY = "synthetic query"
CONTACT = "synthetic@example.org"
BLOCKS = [
    [["alpha"], ["beta"]],
    [["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "alpha"], ["eta"]],
    [["x" * 350], ["y" * 350]],
]
ISSUE_TEXTS = ["alpha beta", "alpha AND (beta OR gamma)", '"alpha AND (beta', "word " * 100]


def json_value(value):
    return json.loads(canonical.canonical_json(value))


def descriptors():
    return [json_value(asdict(f.descriptor)) for f in facade.connectors().values()]


def deny_network(*args, **kwargs):
    raise AssertionError("unmocked network/DNS is forbidden in connector replay")


def response_spec(provider, endpoint, page=1, fetch=False):
    stem = "pubmed_fetch" if fetch else provider + ("_bulk" if endpoint == "bulk" else "")
    suffix = "xml" if fetch or provider == "arxiv" else "json"
    # This is a closed script derived from checked-in native response files, not a fallback transport.
    urls = {"openalex": registry.openalex.WORKS_URL, "biorxiv": registry.openalex.WORKS_URL,
            "semantic_scholar": semantic_scholar.BULK_URL if endpoint == "bulk" else semantic_scholar.SEARCH_URL,
            "crossref": registry.crossref.WORKS_URL, "arxiv": arxiv.QUERY_URL,
            "pubmed": registry.pubmed.FETCH_URL if fetch else registry.pubmed.SEARCH_URL,
            "ieee_xplore": registry.ieee_xplore.SEARCH_URL, "scopus": registry.scopus.SEARCH_URL,
            "core": registry.core.SEARCH_URL, "serpapi": registry.serpapi.SEARCH_URL}
    return {"url": urls[provider], "status": 200, "body_file": f"{stem}-{page}.{suffix}", "headers": {}}


def success_script(provider, endpoint, page=1):
    result = [response_spec(provider, endpoint, page)]
    if provider == "pubmed":
        result.append(response_spec(provider, endpoint, page, fetch=True))
    return result


def call_spec(provider, endpoint, shape, cursor=None):
    c = registry.CONNECTORS[provider]
    kwargs = {}
    if endpoint is not None:
        kwargs.update(endpoint=endpoint, sort=semantic_scholar.BULK_SORT)
    if shape in {"first_page", "next_page"}:
        kwargs.update(cursor=common.FIRST_PAGE if shape == "first_page" else cursor,
                      max_rate_limit_retries=2, **c.sw_options)
    return {"provider_id": provider, "endpoint_id": endpoint, "query_text": QUERY, "limit": 1,
            "key": bool(c.key_env) and shape not in {"unpaged_keyless", "missing_key"}, "kwargs": kwargs}


def case_spec(provider, endpoint, shape, cursor=None):
    call = call_spec(provider, endpoint, shape, cursor)
    script = [] if shape == "missing_key" else success_script(provider, endpoint, 2 if shape == "next_page" else 1)
    if shape == "malformed_200":
        script = [{"url": script[0]["url"], "status": 200, "text": "<SYNTHETIC" if provider == "arxiv" else "[]",
                   "headers": {}}]
    if shape == "non_json_200":
        script = [{"url": script[0]["url"], "status": 200, "text": "<SYNTHETIC not json", "headers": {}}]
    if shape == "efetch_malformed":
        script[1] = {"url": script[1]["url"], "status": 200, "text": "<SYNTHETIC broken XML", "headers": {}}
    if shape in {"retry_then_success", "quota_exhausted"}:
        call["kwargs"]["max_rate_limit_retries"] = 2
        refusal = {"url": script[0]["url"], "status": 406 if provider == "arxiv" and shape == "retry_then_success" else 429,
                   "text": "SYNTHETIC temporary refusal" if shape == "retry_then_success" else
                           '{"error":{"code":"insufficient_quota","message":"SYNTHETIC daily quota exhausted"}}',
                   "headers": {}}
        script = [refusal, *script] if shape == "retry_then_success" else [refusal]
    return {"id": f"{provider}/{endpoint or 'default'}/{shape}", "provider_id": provider, "endpoint_id": endpoint,
            "shape": shape, "adapter_revision": registry.CONNECTORS[provider].adapter_revision,
            "calls": [call], "script": script}


def recorded_request(request):
    def safe(value):
        return value.replace(SYNTHETIC_KEY, "<key>")

    def header_value(name, value):
        if name == "user-agent" and value == f"python-httpx/{httpx.__version__}":
            return "python-httpx/<version>"
        return safe(value)

    url = str(request.url.copy_with(query=None))
    body = json.loads(request.content) if request.content else None
    return {"method": request.method, "url": safe(url),
            "params": sorted([[safe(k), safe(v)] for k, v in request.url.params.multi_items()]),
            "headers": sorted([[k, header_value(k, v)] for k, v in request.headers.multi_items()]),
            "json": json.loads(safe(json.dumps(body))) if body is not None else None}


def recorded_outcome(outcome):
    # Context is deliberately never serialized; payloads and descriptions must already be secret-free.
    for value in (outcome.request_description, outcome.error, outcome.raw_payload):
        assert SYNTHETIC_KEY not in str(value)
    records = []
    for record in outcome.records:
        values = asdict(record)
        raw = values.pop("raw")
        assert SYNTHETIC_KEY not in str(raw)
        records.append(values | {"raw_sha256": canonical.sha256_hex(raw)})
    return json_value({name: getattr(outcome, name) for name in (
        "status", "delivery_class", "access_mode", "http_status", "provider_total", "next_cursor", "retries",
        "error_kind", "error", "request_description", "rate_limit")}
        | {"records": records, "payload_sha256": canonical.sha256_hex(outcome.raw_payload)
           if outcome.raw_payload is not None else None})


def replay(case, through_facade=False):
    """Run a complete sequence with its own fake clock and restored process-wide gates."""
    requests, waits, results = [], [], []
    remaining = list(case["script"])
    now = [1000.0]

    async def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    def transport(request):
        assert remaining, f"unscripted request: {request.url.copy_with(query=None)}"
        step = remaining.pop(0)
        assert request.method == "GET" and str(request.url.copy_with(query=None)) == step["url"]
        requests.append(recorded_request(request))
        body = (FIXTURES / "responses" / step["body_file"]).read_text() if "body_file" in step else step["text"]
        return httpx.Response(step["status"], text=body, headers=step["headers"])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            for call in case["calls"]:
                connector = registry.CONNECTORS[call["provider_id"]]
                key = SYNTHETIC_KEY if call["key"] else None
                kwargs = call["kwargs"]
                try:
                    if through_facade:
                        options = {k: v for k, v in kwargs.items() if k not in {"endpoint", "cursor", "max_rate_limit_retries"}}
                        request = contract.SearchRequest(call["query_text"], call["limit"],
                                  endpoint=kwargs.get("endpoint"), cursor=kwargs.get("cursor"),
                                  max_rate_limit_retries=kwargs.get("max_rate_limit_retries"), options=options)
                        outcome = await facade.CompatibilityConnector(connector).search(
                            request, contract.ConnectorContext(client, key, CONTACT))
                    else:
                        outcome = await connector.search(client, call["query_text"], call["limit"], key, CONTACT, **kwargs)
                    results.append({"outcome": recorded_outcome(outcome)})
                except ValueError as exc:
                    results.append({"raised": {"type": type(exc).__name__, "message": str(exc)}})
                except (AttributeError, TypeError, KeyError, IndexError) as exc:
                    # Freeze malformed-response defects rather than converting them into successful outcomes.
                    results.append({"raised": {"type": type(exc).__name__, "message": str(exc)}})

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket.socket, "connect", deny_network))
        stack.enter_context(patch.object(socket, "getaddrinfo", deny_network))
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", deny_network))
        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", deny_network))
        for module in (common, arxiv, pacing):
            stack.enter_context(patch.object(module.asyncio, "sleep", sleep))
        stack.enter_context(patch.object(arxiv.time, "monotonic", lambda: now[0]))
        stack.enter_context(patch.object(pacing.time, "monotonic", lambda: now[0]))
        stack.enter_context(patch.object(arxiv, "_last_request", 0.0))
        stack.enter_context(patch.object(pacing.SEMANTIC_SCHOLAR_PACER, "_last_finished", 0.0))
        asyncio.run(run())
    assert not remaining, f"unused scripted responses: {case['id']}"
    return {"requests": requests, "waits": waits, "results": results}


def required_shapes(connector, endpoint):
    shapes = {"kill_search" if endpoint is not None else "unpaged", "first_page", "next_page", "malformed_200",
              "missing_key" if connector.key_required else "unpaged_keyless", "retry_then_success", "quota_exhausted"}
    if connector.provider_id != "arxiv":  # All other registered search endpoints parse JSON first.
        shapes.add("non_json_200")
    if connector.provider_id == "pubmed":
        shapes.add("efetch_malformed")
    return shapes


def coverage(cases):
    """Registry-derived; a newly registered pair cannot disappear from the freeze."""
    # Coverage must identify missing fixtures even before the new provider has a display-name admission.
    pairs = {(pid, eid) for pid, connector in registry.CONNECTORS.items() for eid in (None, *connector.endpoints)}
    recorded = {(c["provider_id"], c["endpoint_id"]) for c in cases}
    assert recorded == pairs, f"missing pairs: {pairs - recorded}; unexpected pairs: {recorded - pairs}"
    for pid, eid in pairs:
        shapes = {c["shape"] for c in cases if (c["provider_id"], c["endpoint_id"]) == (pid, eid)}
        missing = required_shapes(registry.CONNECTORS[pid], eid) - shapes
        assert not missing, f"{pid}/{eid}: missing shapes {missing}"


def capture():
    cases = []

    def freeze(case):
        direct = replay(case)
        case["expected"] = direct
        facade_result = replay(case, True)
        if facade_result != direct:
            assert case["shape"] == "unknown_endpoint", case["id"]
            case["facade_expected"] = facade_result
        cases.append(case)

    for pid, f in facade.connectors().items():
        for endpoint in f.descriptor.endpoints:
            eid = endpoint.endpoint_id
            first = case_spec(pid, eid, "first_page")
            cursor = replay(first)["results"][0]["outcome"]["next_cursor"]
            for shape in sorted(required_shapes(registry.CONNECTORS[pid], eid)):
                # SerpApi ignores all cursors and issues the same single-page request.
                freeze(case_spec(pid, eid, shape, cursor if cursor is not None else "ignored"))
            if endpoint.paging == "offset":
                for cursor in ("-1", "x"):
                    case = case_spec(pid, eid, "bad_offset_" + cursor)
                    case["calls"][0]["kwargs"]["cursor"] = cursor
                    case["script"] = []
                    freeze(case)
    for shape, headers, body, success in [
        ("ieee_per_second", {"x-error-detail-header": "Over Queries Per Second"}, "SYNTHETIC refusal", True),
        ("ieee_per_day", {"x-error-detail-header": "Over Queries Per Day"}, "SYNTHETIC daily quota", False),
        ("serpapi_exhausted", {}, '{"error":"SYNTHETIC you have run out of searches"}', False),
        ("openalex_zero_usd", {"x-ratelimit-remaining-usd": "0"}, "SYNTHETIC refusal", False),
        ("pubmed_efetch_quota", {}, '{"error":"SYNTHETIC daily quota exhausted"}', False),
    ]:
        pid = shape.split("_")[0]
        pid = "ieee_xplore" if pid == "ieee" else pid
        case = case_spec(pid, None, shape)
        case["calls"][0]["kwargs"]["max_rate_limit_retries"] = 2
        refusal = {"url": case["script"][-1 if pid == "pubmed" else 0]["url"],
                   "status": 403 if pid == "ieee_xplore" else 429, "headers": headers, "text": body}
        case["script"] = ([case["script"][0], refusal] if pid == "pubmed" else
                          [refusal, *case["script"]] if success else [refusal])
        freeze(case)
    for eid, cursor, shape in [("bulk", semantic_scholar.CUT, "cut_cursor"), ("nope", None, "unknown_endpoint")]:
        case = case_spec("semantic_scholar", eid, shape)
        case["calls"][0]["kwargs"] = {"endpoint": eid, **({"cursor": cursor} if cursor else {})}
        if eid == "nope":
            case["endpoint_id"] = None  # the declared default facade refuses the unknown call endpoint
        case["script"] = []
        freeze(case)
    for pid, endpoints in [("arxiv", [None, None]), ("semantic_scholar", [None, "bulk", None])]:
        case = case_spec(pid, None, "spacing_sequence")
        case["calls"] = [call_spec(pid, eid, "unpaged") for eid in endpoints]
        case["script"] = [response for eid in endpoints for response in success_script(pid, eid)]
        freeze(case)
    rendering, issues = [], []
    for pid, f in facade.connectors().items():
        for e in f.descriptor.endpoints:
            for groups in BLOCKS:
                fitted = query_compiler._fit_blocks(pid, groups, e.endpoint_id)
                rendering.append({"provider_id": pid, "endpoint_id": e.endpoint_id, "groups": groups,
                                  "fitted": json_value(fitted)})
            for text in ISSUE_TEXTS:
                issues.append({"provider_id": pid, "endpoint_id": e.endpoint_id, "text": text,
                               "issues": query_rules.query_issues(pid, text, e.endpoint_id)})
    return {"contract_id": contract.CONTRACT_ID, "query_rules_revision": contract.QUERY_RULES_REVISION,
            "base_commit": "1fb1743", "descriptors": descriptors(), "cases": cases,
            "rendering": rendering, "query_issues": issues}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    frozen = capture()
    serialized = json.dumps(frozen, indent=2, ensure_ascii=False) + "\n"
    assert SYNTHETIC_KEY not in serialized
    BASELINE.write_text(serialized)
    print(f"wrote {len(frozen['cases'])} synthetic cases to {BASELINE}")

"""SYNTHETIC B3a equality and pre-send refusals; no live-provider evidence.

Dispatcher shapes reproduce workflow/flow.py:2053-2056 and :4681-4682. They
derive from registry fields and endpoint_options, without importing private flow
code. RetryPolicy is measured against module behavior, not used to drive send.
"""

import asyncio
import inspect
import socket
from dataclasses import asdict, replace

import httpx
import pytest

import connector_baseline as baseline
import test_connector_contract as conformance
from deixis.providers import contract, facade, registry
from deixis.providers.common import FIRST_PAGE, SearchOutcome


PAIRS = [(pid, endpoint.endpoint_id) for pid, f in facade.connectors().items()
         for endpoint in f.descriptor.endpoints]
OPTIONS = [(pid, endpoint.endpoint_id, option) for pid, f in facade.connectors().items()
           for endpoint in f.descriptor.endpoints for option in endpoint.options]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Imported test modules' fixtures do not guard this module.
    monkeypatch.setattr(socket.socket, "connect", baseline.deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", baseline.deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", baseline.deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", baseline.deny_network)
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.setenv(connector.key_env, baseline.SYNTHETIC_KEY)


def endpoint_for(provider_id, endpoint_id):
    return next(e for e in facade.connectors()[provider_id].descriptor.endpoints
                if e.endpoint_id == endpoint_id)


def measured(replay):
    outcome, requests, waits = replay
    return {"outcome": asdict(outcome), "waits": waits,
            "requests": [baseline.recorded_request(r) | {"timeout": r.extensions["timeout"]}
                         for r in requests]}


@pytest.mark.parametrize("provider_id,endpoint_id,fixture,case", conformance.CASES,
                         ids=[f"{p}/{e or 'default'}/g{c['group']}/{c['name']}"
                              for p, e, f, c in conformance.CASES])
def test_full_matrix_direct_facade_equivalence(provider_id, endpoint_id, fixture, case):
    direct = conformance.replay_case(provider_id, endpoint_id, fixture, case, direct=True)
    wrapped = conformance.replay_case(provider_id, endpoint_id, fixture, case)
    assert measured(direct) == measured(wrapped)


def native_script(provider_id, endpoint_id, fixture):
    ep = conformance.endpoint_fixture(fixture, endpoint_id)
    positive = next(c for c in ep["cases"] if c["name"] == "positive")
    url = fixture.get("url") or baseline.response_spec(provider_id, endpoint_id)["url"]
    script = [(url, 200, conformance.body_of(positive))]
    if fixture.get("fetch_url"):
        script.append((fixture["fetch_url"], 200, conformance.body_of(ep, "fetch_")))
    return script


def refusals(script, count, status=429):
    return [(script[0][0], status, 'SYNTHETIC temporary refusal')] * count


def replay_script(provider_id, endpoint_id, fixture, kwargs, script, *, direct=False, limit=1):
    connector = registry.CONNECTORS[provider_id]
    key = baseline.SYNTHETIC_KEY if connector.key_env else None
    requests, remaining = [], list(script)

    def transport(request):
        assert remaining, f"{provider_id}/{endpoint_id}: unscripted request"
        url, status, body = remaining.pop(0)
        assert request.method == "GET" and str(request.url.copy_with(query=None)) == url
        assert request.url.host == connector.host
        conformance.assert_auth(request, fixture, key)
        requests.append(request)
        return httpx.Response(status, text=body)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            if direct:
                return await connector.search(client, baseline.QUERY, limit, key, baseline.CONTACT, **kwargs)
            request = facade.search_request(baseline.QUERY, limit, **kwargs)
            try:
                return await facade.connectors()[provider_id].search(
                    request, contract.ConnectorContext(client, key, baseline.CONTACT))
            except contract.ContractViolation as exc:
                raise AssertionError(f"{provider_id}/{endpoint_id}: dispatcher keyword shape not representable: {exc}") from exc

    with baseline.fake_clock() as waits:
        outcome = asyncio.run(run())
    assert not remaining, (provider_id, endpoint_id, remaining)
    return outcome, requests, waits


def assert_script_equivalence(provider_id, endpoint_id, fixture, kwargs, script, *, limit=1):
    direct = replay_script(provider_id, endpoint_id, fixture, kwargs, script, direct=True, limit=limit)
    wrapped = replay_script(provider_id, endpoint_id, fixture, kwargs, script, limit=limit)
    assert measured(direct) == measured(wrapped), (provider_id, endpoint_id, kwargs)
    return wrapped


def dispatcher_shapes():
    for pid, connector in registry.CONNECTORS.items():
        yield pytest.param(pid, "legacy", {}, None, None, False, id=f"{pid}/default/legacy")
        for eid in (None, *connector.endpoints):
            query = {"provider_id": pid, "endpoint": eid}
            if connector.sw_query.get("endpoint") == eid:
                query.update(connector.sw_query)
            yield pytest.param(pid, "kill", query, None, None, False, id=f"{pid}/{eid or 'default'}/kill")
        for label, query in (("pre-D93", {"provider_id": pid}),
                             ("routed", {"provider_id": pid, **connector.sw_query})):
            for cursor in ("first", "next"):
                for retries in (0, 2):
                    for limited in (False, True):
                        yield pytest.param(pid, "paged", query, cursor, retries, limited,
                                           id=f"{pid}/{query.get('endpoint') or 'default'}/{label}/{cursor}/retry{retries}/{'429' if limited else 'positive'}")


DISPATCH_SHAPES = list(dispatcher_shapes())


@pytest.mark.parametrize("provider_id,kind,query,cursor_kind,retries,limited", DISPATCH_SHAPES)
def test_dispatcher_shape_equivalence(provider_id, kind, query, cursor_kind, retries, limited):
    connector = registry.CONNECTORS[provider_id]
    endpoint_id = query.get("endpoint") if kind != "legacy" else None
    fixture = conformance.FIXTURES[provider_id]
    script = native_script(provider_id, endpoint_id, fixture)
    # The positive bulk fixture has two records; avoid the existing CUT refusal.
    ep = conformance.endpoint_fixture(fixture, endpoint_id)
    positive = next(c for c in ep["cases"] if c["name"] == "positive")
    limit = max(1, len(positive["expected"]["records"]))
    kwargs = {}
    if kind == "kill":
        kwargs = registry.endpoint_options(query)
    elif kind == "paged":
        first_kwargs = {"cursor": FIRST_PAGE, "max_rate_limit_retries": retries,
                        **connector.sw_options, **registry.endpoint_options(query)}
        first = assert_script_equivalence(provider_id, endpoint_id, fixture, first_kwargs, script, limit=limit)[0]
        endpoint = endpoint_for(provider_id, endpoint_id)
        next_cursor = "ignored" if endpoint.paging == "single_page" else first.next_cursor
        assert next_cursor is not None, (provider_id, endpoint_id, "positive fixture must supply continuation")
        cursor = FIRST_PAGE if cursor_kind == "first" else next_cursor
        kwargs = {"cursor": cursor, "max_rate_limit_retries": retries,
                  **connector.sw_options, **registry.endpoint_options(query)}
        if limited:
            script = refusals(script, 1 + retries)
    outcome, requests, _ = assert_script_equivalence(provider_id, endpoint_id, fixture, kwargs, script, limit=limit)
    assert requests and outcome.status == ("rate_limited" if limited else "completed")
    if limited:
        assert outcome.retries == retries


def retry_waits(policy, retries):
    waits = []
    for i in range(retries):
        wait = policy.unstated_wait * (i + 1)
        waits.append(wait)
        if policy.shared_gate and policy.min_interval > wait:
            waits.append(policy.min_interval - wait)
    return waits


@pytest.mark.parametrize("provider_id,endpoint_id", PAIRS, ids=[f"{p}/{e or 'default'}" for p, e in PAIRS])
@pytest.mark.parametrize("direct", [False, True], ids=["facade", "direct"])
def test_retry_default_descriptor_agreement(provider_id, endpoint_id, direct):
    connector = registry.CONNECTORS[provider_id]
    policy = endpoint_for(provider_id, endpoint_id).retry
    assert inspect.signature(connector.search).parameters["max_rate_limit_retries"].default == policy.max_rate_limit_retries
    fixture = conformance.FIXTURES[provider_id]
    script = native_script(provider_id, endpoint_id, fixture)
    kwargs = {} if endpoint_id is None else {"endpoint": endpoint_id}
    result = replay_script(provider_id, endpoint_id, fixture, kwargs,
                           refusals(script, 1 + policy.max_rate_limit_retries), direct=direct)
    outcome, requests, waits = result
    assert outcome.status == "rate_limited" and outcome.error_kind == "rate_limited"
    assert outcome.retries == policy.max_rate_limit_retries
    assert len(requests) == 1 + policy.max_rate_limit_retries
    assert waits == retry_waits(policy, policy.max_rate_limit_retries)


STATUS_CASES = [(pid, eid, status) for pid, eid in PAIRS
                for status in sorted(set(endpoint_for(pid, eid).retry.rate_limit_statuses) | {406})]


@pytest.mark.parametrize("provider_id,endpoint_id,status", STATUS_CASES,
                         ids=[f"{p}/{e or 'default'}/{s}" for p, e, s in STATUS_CASES])
@pytest.mark.parametrize("direct", [False, True], ids=["facade", "direct"])
def test_retry_status_descriptor_agreement(provider_id, endpoint_id, status, direct):
    policy = endpoint_for(provider_id, endpoint_id).retry
    fixture = conformance.FIXTURES[provider_id]
    positive = native_script(provider_id, endpoint_id, fixture)
    kwargs = {"max_rate_limit_retries": 1, **({"endpoint": endpoint_id} if endpoint_id is not None else {})}
    accepted = status in policy.rate_limit_statuses
    script = refusals(positive, 1, status) + (positive if accepted else [])
    outcome, requests, waits = replay_script(provider_id, endpoint_id, fixture, kwargs, script, direct=direct)
    assert outcome.retries == (1 if accepted else 0)
    assert len(requests) == (1 + len(positive) if accepted else 1)
    assert waits == (retry_waits(policy, 1) if accepted else [])
    if accepted:
        assert outcome.status == "completed"
    else:
        assert (outcome.status, outcome.delivery_class) == ("failed", "rejected_not_executed")


@pytest.mark.parametrize("provider_id,endpoint_id", PAIRS, ids=[f"{p}/{e or 'default'}" for p, e in PAIRS])
@pytest.mark.parametrize("direct", [False, True], ids=["facade", "direct"])
def test_timeout_descriptor_agreement(provider_id, endpoint_id, direct):
    fixture = conformance.FIXTURES[provider_id]
    script = native_script(provider_id, endpoint_id, fixture)
    kwargs = {} if endpoint_id is None else {"endpoint": endpoint_id}
    outcome, requests, _ = replay_script(provider_id, endpoint_id, fixture, kwargs, script, direct=direct)
    assert outcome.status == "completed" and len(requests) == len(script)
    timeout = endpoint_for(provider_id, endpoint_id).retry.timeout
    for request in requests:
        assert request.extensions["timeout"] == {k: timeout for k in ("connect", "read", "write", "pool")}


class StringSubclass(str):
    pass


WRONG_VALUES = {"bool": [1, 0, "true", None, 17],
                "str": [17, True, None, b"x", StringSubclass("x")]}
INVALID_OPTIONS = [(pid, eid, option.name, value) for pid, eid, option in OPTIONS
                   for value in WRONG_VALUES[option.value_type]]
D178_IDS = {("openalex", None, "reference_count", 17),
            ("openalex", None, "references", 17),
            ("semantic_scholar", "bulk", "sort", 17)}


def option_case_id(pid, eid, name, value):
    suffix = "D178-17" if (pid, eid, name, value) in D178_IDS else f"{type(value).__name__}-{value!r}"
    return f"{pid}/{eid or 'default'}/{name}/{suffix}"


def assert_refused_before_send(f, request, field):
    requests = []

    def transport(request):
        requests.append(request)
        return baseline.deny_network(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with pytest.raises(contract.ContractViolation, match=field) as exc:
                await f.search(request, contract.ConnectorContext(client, baseline.SYNTHETIC_KEY, baseline.CONTACT))
            assert f.descriptor.provider_id not in str(exc.value)

    asyncio.run(run())
    assert requests == []


@pytest.mark.parametrize("provider_id,endpoint_id,name,value", INVALID_OPTIONS,
                         ids=[option_case_id(*case) for case in INVALID_OPTIONS])
def test_option_value_types_refused_before_send(provider_id, endpoint_id, name, value):
    request = contract.SearchRequest(baseline.QUERY, 1, endpoint=endpoint_id, options={name: value})
    assert_refused_before_send(facade.connectors()[provider_id], request, name)


def test_d178_regression_ids_are_explicit():
    assert D178_IDS <= set(INVALID_OPTIONS)
    assert {option_case_id(*case) for case in D178_IDS} == {
        "openalex/default/reference_count/D178-17", "openalex/default/references/D178-17",
        "semantic_scholar/bulk/sort/D178-17"}


@pytest.mark.parametrize("provider_id,endpoint_id", PAIRS, ids=[f"{p}/{e or 'default'}" for p, e in PAIRS])
@pytest.mark.parametrize("value", [-1, True, 1.0, "2"], ids=["negative", "bool", "float", "str"])
def test_max_rate_limit_retries_refused_before_send(provider_id, endpoint_id, value):
    request = contract.SearchRequest(baseline.QUERY, 1, endpoint=endpoint_id, max_rate_limit_retries=value)
    assert_refused_before_send(facade.connectors()[provider_id], request, "max_rate_limit_retries")


VALID_OPTIONS = [(pid, eid, option.name, value) for pid, eid, option in OPTIONS
                 for value in ([True, False] if option.value_type == "bool" else ["citationCount:desc", ""])]


@pytest.mark.parametrize("provider_id,endpoint_id,name,value", VALID_OPTIONS,
                         ids=[f"{p}/{e or 'default'}/{n}/{v!r}" for p, e, n, v in VALID_OPTIONS])
def test_option_values_accepted_with_equivalence(provider_id, endpoint_id, name, value):
    fixture = conformance.FIXTURES[provider_id]
    kwargs = {name: value, **({"endpoint": endpoint_id} if endpoint_id is not None else {})}
    result = assert_script_equivalence(provider_id, endpoint_id, fixture, kwargs,
                                       native_script(provider_id, endpoint_id, fixture))
    assert result[0].status == "completed"
    if name == "sort" and value == "":
        if provider_id == "openalex":
            assert "sort" not in result[1][0].url.params
        else:
            assert result[1][0].url.params["sort"] == registry.CONNECTORS[provider_id].sw_query.get("sort", "")


@pytest.mark.parametrize("provider_id,endpoint_id", PAIRS, ids=[f"{p}/{e or 'default'}" for p, e in PAIRS])
@pytest.mark.parametrize("retries", [0, 2])
def test_max_rate_limit_retries_accepted_with_equivalence(provider_id, endpoint_id, retries):
    fixture = conformance.FIXTURES[provider_id]
    script = native_script(provider_id, endpoint_id, fixture)
    kwargs = {"max_rate_limit_retries": retries, **({"endpoint": endpoint_id} if endpoint_id is not None else {})}
    assert_script_equivalence(provider_id, endpoint_id, fixture, kwargs, script)
    result = assert_script_equivalence(provider_id, endpoint_id, fixture, kwargs, refusals(script, 1 + retries))
    assert result[0].status == "rate_limited" and result[0].retries == retries


def synthetic_connector(monkeypatch, *, bad_options=False):
    async def search(client, query, limit, key=None, contact=None, **kwargs):
        response = await client.get("https://synthetic.invalid/search", params=kwargs, timeout=30.0)
        return SearchOutcome("completed", None, "SYNTHETIC", "keyless", raw_payload=response.json())

    source = registry.Connector("synthetic_bad_options" if bad_options else "synthetic_values", search, 1,
                                host="synthetic.invalid", sw_options={"choice": "a"},
                                sw_query={"endpoint": "named"},
                                endpoints={"named": registry.Endpoint("offset", 1,
                                                                     options=() if bad_options else ("choice",))})
    monkeypatch.setitem(registry.CONNECTORS, source.provider_id, source)
    monkeypatch.setitem(facade.query_rules.NAMES, source.provider_id, "SYNTHETIC")
    descriptor = facade.descriptor_for(source, len(registry.CONNECTORS) - 1)
    if not bad_options:
        descriptor = replace(descriptor, endpoints=tuple(
            replace(e, options=(contract.OptionDescriptor("choice", "str", ("a", "b")),))
            for e in descriptor.endpoints))
    return source, descriptor


def test_enumerated_values_accepted_and_refused_before_send(monkeypatch):
    source, descriptor = synthetic_connector(monkeypatch)
    f = facade.CompatibilityConnector(source, descriptor)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"SYNTHETIC": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            direct = await source.search(client, baseline.QUERY, 1, choice="a")
            direct_request = baseline.recorded_request(requests[-1])
            wrapped = await f.search(facade.search_request(baseline.QUERY, 1, choice="a"),
                                     contract.ConnectorContext(client, None, None))
            assert asdict(direct) == asdict(wrapped)
            assert direct_request == baseline.recorded_request(requests[-1])

    asyncio.run(run())
    assert_refused_before_send(f, contract.SearchRequest(baseline.QUERY, 1, options={"choice": "c"}), "choice")


def test_dispatcher_names_synthetic_endpoint_option_mismatch(monkeypatch):
    source, _ = synthetic_connector(monkeypatch, bad_options=True)
    fixture = {"provider_id": source.provider_id, "auth": None}
    kwargs = {"cursor": FIRST_PAGE, "max_rate_limit_retries": 0,
              **source.sw_options, **registry.endpoint_options(source.sw_query)}
    script = [("https://synthetic.invalid/search", 200, '{"SYNTHETIC":true}')]
    with pytest.raises(AssertionError, match="synthetic_bad_options/named: dispatcher keyword shape not representable"):
        assert_script_equivalence(source.provider_id, "named", fixture, kwargs, script)

"""SYNTHETIC B3a equality and pre-send refusals; no live-provider evidence.

Dispatcher shapes reproduce workflow/run/flow.py:2053-2056 and :4681-4682. They
derive from registry fields and endpoint_options, without importing private flow
code. RetryPolicy is measured against module behavior, not used to drive send.
"""

import asyncio
import socket
from dataclasses import asdict

import httpx
import pytest

import connector_baseline as baseline
import test_connector_contract as conformance
from deixis.providers import contract, facade, registry


PAIRS = [(pid, endpoint.endpoint_id) for pid, f in facade.connectors().items()
         for endpoint in f.descriptor.endpoints]


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


# A representative sample of the conformance matrix (the full grid was cut in the stage-5 test simplification).
FACADE_SAMPLE = {"openalex/default/g3/positive", "semantic_scholar/bulk/g3/positive"}
FACADE_CASES = [(p, e, f, c) for p, e, f, c in conformance.CASES
                if f"{p}/{e or 'default'}/g{c['group']}/{c['name']}" in FACADE_SAMPLE]


@pytest.mark.parametrize("provider_id,endpoint_id,fixture,case", FACADE_CASES,
                         ids=[f"{p}/{e or 'default'}/g{c['group']}/{c['name']}"
                              for p, e, f, c in FACADE_CASES])
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


def retry_waits(policy, retries):
    waits = []
    for i in range(retries):
        wait = policy.unstated_wait * (i + 1)
        waits.append(wait)
        if policy.shared_gate and policy.min_interval > wait:
            waits.append(policy.min_interval - wait)
    return waits


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


@pytest.mark.parametrize("provider_id,endpoint_id", [("openalex", None)], ids=["openalex/default"])
@pytest.mark.parametrize("value", [-1, "2"], ids=["negative", "str"])
def test_max_rate_limit_retries_refused_before_send(provider_id, endpoint_id, value):
    request = contract.SearchRequest(baseline.QUERY, 1, endpoint=endpoint_id, max_rate_limit_retries=value)
    assert_refused_before_send(facade.connectors()[provider_id], request, "max_rate_limit_retries")



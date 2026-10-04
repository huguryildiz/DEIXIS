"""Synthetic transport checks for Semantic Scholar's cumulative one-RPS gate."""

import asyncio
import time

import httpx

from deixis.providers import common
from deixis.providers.pacing import SEMANTIC_SCHOLAR_PACER, SerialRequestPacer


def test_default_semantic_scholar_interval_is_at_least_one_second():
    assert SEMANTIC_SCHOLAR_PACER.interval_seconds >= 1.0


def test_semantic_scholar_endpoints_share_one_gate_across_clients(monkeypatch):
    monkeypatch.setattr(common, "SEMANTIC_SCHOLAR_PACER", SerialRequestPacer(0.06))
    starts = []
    active = 0
    peak_active = 0

    async def handler(request):
        nonlocal active, peak_active
        starts.append((request.url.path, time.monotonic()))
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.005)
        active -= 1
        return httpx.Response(200, json={})

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as first, httpx.AsyncClient(transport=transport) as second:
            return await asyncio.gather(
                common.send(first, "https://api.semanticscholar.org/graph/v1/paper/search", {}, {}, "search", "keyless"),
                common.send(second, "https://api.semanticscholar.org/graph/v1/paper/DOI:example/references",
                            {}, {}, "references", "keyless"),
            )

    results = asyncio.run(go())
    assert [outcome.status for _, outcome in results] == ["completed", "completed"]
    assert {path.rsplit("/", 1)[-1] for path, _ in starts} == {"search", "references"}
    assert peak_active == 1
    assert starts[1][1] - starts[0][1] >= 0.055


def test_semantic_scholar_retry_uses_the_same_gate(monkeypatch):
    monkeypatch.setattr(common, "SEMANTIC_SCHOLAR_PACER", SerialRequestPacer(0.06))
    starts = []

    def handler(request):
        starts.append(time.monotonic())
        return httpx.Response(429) if len(starts) == 1 else httpx.Response(200, json={})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await common.send(client, "https://api.semanticscholar.org/graph/v1/paper/search",
                                     {}, {}, "search", "keyless", unstated_wait=0.0)

    _, outcome = asyncio.run(go())
    assert (outcome.status, outcome.retries, len(starts)) == ("completed", 1, 2)
    assert starts[1] - starts[0] >= 0.055


def test_other_provider_does_not_enter_semantic_scholar_gate(monkeypatch):
    class ForbiddenGate:
        async def run(self, factory):
            raise AssertionError("non-Semantic Scholar request was paced")

    monkeypatch.setattr(common, "SEMANTIC_SCHOLAR_PACER", ForbiddenGate())

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
            return await common.send(client, "https://api.openalex.org/works", {}, {}, "openalex", "keyless")

    _, outcome = asyncio.run(go())
    assert outcome.status == "completed"

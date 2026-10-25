"""Limit and quota classification across connections and providers, and per-run suppression of an exhausted provider.

Mocked HTTP and fake Codex. Passing shows the classification and what is recorded, not live provider wording.
"""

import asyncio
import httpx
import json
import pytest
from claude_agent_sdk import AssistantMessage
from claude_agent_sdk import ResultMessage
from dataclasses import replace
from types import SimpleNamespace

import fast_search_helpers
from deixis.models import adapter
from deixis.models import claude
from deixis.models import deepseek
from deixis.models import gemini
from deixis.providers import common
from deixis.providers import ieee_xplore
from deixis.providers import openalex
from deixis.providers import serpapi
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store
from test_claude_adapter import FakeClient
from test_claude_adapter import prepare
from test_codex_adapter_paths import codex


@pytest.mark.parametrize("connection", ["deepseek"])
@pytest.mark.parametrize("body,headers,kind", [
    ({"error": {"code": "insufficient_quota", "message": "SYNTHETIC"}}, {"Retry-After": "1"}, "quota_exhausted"),
    ({"error": {"code": "rate_limit_exceeded", "message": "SYNTHETIC"}}, {"Retry-After": "2"}, "rate_limited"),
])
def test_model_limits(connection, body, headers, kind, monkeypatch, tmp_path, codex, http_status=429):
    if connection in ("gemini", "deepseek"):
        module = {"gemini": gemini, "deepseek": deepseek}[connection]
        monkeypatch.setenv(module.KEY_ENV, "SYNTHETIC-key")
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(http_status, json=body, headers=headers)))
        instance = (gemini.GeminiAdapter if connection == "gemini" else deepseek.DeepSeekAdapter)(client)
    elif connection == "codex":
        instance, server = codex
        server.turn_status, server.turn_error = "failed", dict(body, httpStatusCode=http_status, retryAfter=headers.get("Retry-After"))
    else:
        prepare(monkeypatch)
        class ErrorClient(FakeClient):
            async def receive_response(self):
                if body.get("type") == "billing_error":
                    yield AssistantMessage([], "requested-model", error="billing_error")
                yield ResultMessage("error", 1, 1, True, 1, "synthetic", errors=[json.dumps(dict(body, status=http_status, retryAfter=headers.get("Retry-After")))])
        monkeypatch.setattr(claude, "ClaudeSDKClient", ErrorClient)
        instance = claude.ClaudeCodeAdapter(tmp_path)
    result = asyncio.run(instance.run_step("b", "d", "m", {}, "requested-model"))
    assert result.status == "failed"
    assert adapter.is_rate_limited(result) is (kind == "rate_limited")
    assert result.error_kind == kind
    if connection != "claude":
        assert result.retry_after == headers.get("Retry-After")


@pytest.mark.parametrize("module", [openalex])
@pytest.mark.parametrize("daily", [True])
def test_provider_limits(module, daily, monkeypatch):
    calls, waits = [], []
    async def sleep(seconds):
        waits.append(seconds)
    from deixis.providers import common
    monkeypatch.setattr(common.asyncio, "sleep", sleep)
    # Avoid real pacing time without changing the bounded retry policy.
    async def paced(send):
        return await send()
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "run", paced)
    def handler(request):
        calls.append(request)
        if module == ieee_xplore:
            return httpx.Response(403, headers={"x-error-detail-header": "Account Over Queries Per Day Limit" if daily else "Account Over Queries Per Second Limit", "Retry-After": "1"})
        if module == serpapi:
            body = {"error": "Your account has run out of searches." if daily else "Too many requests"}
        else:
            body = {"error": {"code": "daily_limit_exceeded" if daily else "rate_limit_exceeded", "message": "SYNTHETIC"}}
        return httpx.Response(429, json=body, headers={"Retry-After": "1"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    search = openalex.search_works if module == openalex else module.search
    result = asyncio.run(search(client, "synthetic", 1, api_key="SYNTHETIC-key"))
    assert result.status == "rate_limited"  # existing public vocabulary
    assert result.retries == (0 if daily else 2)
    assert len(calls) == (1 if daily else 3)
    assert waits == ([] if daily else [1, 1])
    assert result.error_kind == ("quota_exhausted" if daily else "rate_limited")


def test_openalex_remaining_budget_header_stops_retry(monkeypatch):
    from deixis.providers import common
    calls = []
    async def sleep(seconds):
        raise AssertionError("daily budget must not wait")
    monkeypatch.setattr(common.asyncio, "sleep", sleep)
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"x-ratelimit-remaining-usd": "0", "Retry-After": "1"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(openalex.search_works(client, "synthetic", 1))
    assert len(calls) == 1 and result.retries == 0 and result.error_kind == "quota_exhausted"


@pytest.fixture
def quota_flow(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "SYNTHETIC daily quota exhausted"})))
    deps = SimpleNamespace(store=store, http=client,
                           settings=SimpleNamespace(contact_email=None, payloads_dir=tmp_path / "payloads"))
    flow = ResearchFlow(deps)
    def new_run():
        rid = store.create_research("SYNTHETIC?", "academic", "standard", ["openalex"], "fake", "m", "en")
        return store.create_run(rid, "discovery", {"max_provider_requests": 10, "inspection": {"policy": "small_batch_fused_v1"}}, None)
    yield flow, new_run
    asyncio.run(client.aclose())
    if deps.http is not client:
        asyncio.run(deps.http.aclose())
    conn.close()


def connector(provider, calls, monkeypatch):
    async def search(http, *args, **kwargs):
        calls.append(provider)
        _, outcome = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless")
        return outcome
    source = replace(CONNECTORS[provider], search=search, key_env=None, key_required=False)
    monkeypatch.setitem(CONNECTORS, provider, source)
    return source


def test_exhausted_provider_is_suppressed_only_in_its_run(quota_flow, monkeypatch):
    flow, new_run = quota_flow
    run = new_run()
    calls = []
    first, other = connector("openalex", calls, monkeypatch), connector("crossref", calls, monkeypatch)
    async def exercise():
        await flow._send_search(run["id"], first, {"query_text": "one"}, 3)
        blocked = await flow._send_search(run["id"], first, {"query_text": "two"}, 3)
        assert (blocked.status, blocked.delivery_class, blocked.error_kind) == ("rate_limited", "before_send", "quota_exhausted")
        assert flow.store.run(run["id"])["usage"]["provider_requests"] == 1
        await flow._send_search(run["id"], other, {"query_text": "three"}, 3)
        await flow._send_search(new_run()["id"], first, {"query_text": "four"}, 3)
        restarted = ResearchFlow(flow.deps)
        await restarted._send_search(run["id"], first, {"query_text": "five"}, 3)
    asyncio.run(exercise())
    assert calls == ["openalex", "crossref", "openalex", "openalex"]


def test_search_round_records_suppression_and_retry_sends_again(quota_flow, monkeypatch):
    flow, new_run = quota_flow
    run = new_run()
    calls = []
    queries = [{"provider_id": "openalex", "query_text": text} for text in ("one", "two")]

    async def search(http, query, *args, **kwargs):
        calls.append(query)
        response, outcome = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless")
        return replace(outcome, status="zero_results", delivery_class="answered") if response is not None else outcome

    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "SYNTHETIC daily quota exhausted"})
        if len(calls) == 1 else httpx.Response(200, json={})))

    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], search=search, key_env=None))

    async def discovery(current, scope):
        await fast_search_helpers.search(flow, current, queries, bool(current["budget"].get("retry_failed_searches_only")))
        flow.store.update_run(current["id"], event="run_completed", status="completed")

    monkeypatch.setattr(flow, "_discovery", discovery)

    async def exercise():
        await flow.execute(run["id"])
        assert calls == ["one"]
        first = flow.store.existing_step(run["id"], "search:0")
        second = flow.store.existing_step(run["id"], "search:1")
        assert first["status"] == second["status"] == "failed"
        assert second["delivery_class"] == "before_send"
        assert flow._query_requests(run["id"], "search:0") == 1
        assert flow._query_requests(run["id"], "search:1") == 0
        assert flow.store.run(run["id"])["usage"]["provider_requests"] == 1
        flow.store.queue_failed_search_retry(run["id"])
        await flow.execute(run["id"])
        assert calls == ["one", "one", "two"]
        assert flow._query_requests(run["id"], "search:0") == 2
        assert flow._query_requests(run["id"], "search:1") == 1
        assert all(flow.store.existing_step(run["id"], f"search:{index}")["status"] == "succeeded"
                   for index in (0, 1))

    asyncio.run(exercise())

"""Synthetic error bodies test policy, not live provider error formats."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage

from deixis.models import adapter, claude, deepseek, gemini
from deixis.providers import ieee_xplore, openalex, semantic_scholar, serpapi
from test_claude_adapter import FakeClient, prepare
from test_codex_adapter_paths import codex
from deixis.models.codex_rpc import RpcError


@pytest.mark.parametrize("connection", ["codex", "claude", "gemini", "deepseek"])
@pytest.mark.parametrize("body,headers,kind", [
    ({"error": {"code": "insufficient_quota", "message": "SYNTHETIC"}}, {"Retry-After": "1"}, "quota_exhausted"),
    ({"error": {"code": "rate_limit_exceeded", "message": "SYNTHETIC"}}, {"Retry-After": "2"}, "rate_limited"),
    ({"error": {"code": "rate_limit_exceeded", "message": "SYNTHETIC"}}, {}, "rate_limited"),
    ({"error": {"message": "SYNTHETIC HTTP 429"}}, {}, "rate_limited"),
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


@pytest.mark.parametrize("module", [ieee_xplore, serpapi, semantic_scholar, openalex])
@pytest.mark.parametrize("daily", [True, False])
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


@pytest.mark.parametrize("signal,http_status,kind", [("billing_error", 429, "quota_exhausted"), ("rate_limit", 429, "rate_limited"), (None, 429, "rate_limited")])
def test_claude_sdk_structured_error(signal, http_status, kind, monkeypatch, tmp_path):
    prepare(monkeypatch)
    class StructuredError(FakeClient):
        async def receive_response(self):
            yield AssistantMessage([], "requested-model", error=signal)
            yield ResultMessage("error", 1, 1, True, 1, "synthetic", errors=["SYNTHETIC"], api_error_status=http_status)
    monkeypatch.setattr(claude, "ClaudeSDKClient", StructuredError)
    result = asyncio.run(claude.ClaudeCodeAdapter(tmp_path).run_step("b", "d", "m", {}, "requested-model"))
    assert adapter.is_rate_limited(result) is (kind == "rate_limited")
    assert result.error_kind == kind and result.http_status == http_status


@pytest.mark.parametrize("module", [ieee_xplore, serpapi, semantic_scholar, openalex])
@pytest.mark.parametrize("headers", [{}, {"Retry-After": "1"}])
def test_unknown_provider_429_uses_bounded_backoff(module, headers, monkeypatch):
    from deixis.providers import common
    calls, waits = [], []
    async def sleep(seconds):
        waits.append(seconds)
    async def paced(send):
        return await send()
    monkeypatch.setattr(common.asyncio, "sleep", sleep)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "run", paced)
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers=headers)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    search = openalex.search_works if module == openalex else module.search
    result = asyncio.run(search(client, "synthetic", 1, api_key="SYNTHETIC-key"))
    assert len(calls) == 3 and result.retries == 2 and result.error_kind == "rate_limited"
    assert waits == ([1, 1] if headers else [15, 30] if module == semantic_scholar else [3, 6])


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


@pytest.mark.parametrize("code,kind", [("insufficient_quota", "quota_exhausted"), ("rate_limit_exceeded", "rate_limited")])
def test_codex_rpc_error_code_survives_display_truncation(code, kind, codex):
    instance, server = codex
    server.error_method = "turn/start"
    server.request_error = RpcError("synthetic", {"message": "SYNTHETIC " + "x" * 400, "code": code})
    result = asyncio.run(instance.run_step("b", "d", "m", {}, "requested-model"))
    assert result.error_kind == kind
    assert adapter.is_rate_limited(result) is (kind == "rate_limited")
    assert code not in result.error and len(result.error) == 300


@pytest.mark.parametrize("error,limited", [("HTTP 429", True), ("rate_limit_error", True), ("quota exhausted", False), ("model overloaded", False)])
def test_legacy_result_without_metadata_keeps_text_fallback(error, limited):
    assert adapter.is_rate_limited(SimpleNamespace(status="failed", error=error)) is limited

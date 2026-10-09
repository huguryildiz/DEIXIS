"""The generic OpenAI-compatible adapter behind the Qwen, Kimi and Mistral connections.

Mocked httpx transports only: these show the request shape and error handling, not that the live providers accept
the requests or answer the way the mocks do.
"""

import asyncio
import json

import httpx
import pytest

from deixis.models import openai_compat
from deixis.models.adapter import is_rate_limited

SPECS = list(openai_compat.CONNECTIONS.values())
every_spec = pytest.mark.parametrize("spec", SPECS, ids=[c.id for c in SPECS])


def adapter(spec, handler):
    return openai_compat.OpenAICompatAdapter(spec, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok_response(model="m-1", content='{"claims": []}', finish="stop", **extra):
    return httpx.Response(200, json={"id": "chat-1", "model": model, "usage": {"total_tokens": 8},
                                     "choices": [{"finish_reason": finish, "message": {"content": content}}], **extra})


def test_the_three_connections_use_the_documented_endpoints_and_key_variables():
    assert {c.id: (c.base_url, c.key_env) for c in SPECS} == {
        "qwen": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "kimi": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
        "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    }


@every_spec
def test_identity_and_schema_enforcement(spec):
    a = openai_compat.OpenAICompatAdapter(spec)
    assert (a.connection, a.enforces_schema) == (spec.id, False)


@every_spec
def test_health_requires_key_without_sending_a_request(spec, monkeypatch):
    monkeypatch.delenv(spec.key_env, raising=False)
    status = asyncio.run(adapter(spec, lambda r: (_ for _ in ()).throw(AssertionError("unexpected request"))).health(refresh=True))
    assert status["ready"] is False and status["key_configured"] is False and spec.key_env in status["reason"]


@every_spec
def test_health_lists_models_and_offers_no_reasoning_effort(spec, monkeypatch):
    monkeypatch.setenv(spec.key_env, "test-key")

    def handler(request):
        assert str(request.url) == f"{spec.base_url}/models" and request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"object": "list", "data": [{"id": "model-a"}, {"id": "model-b"}, {"object": "x"}]})

    status = asyncio.run(adapter(spec, handler).health(refresh=True))
    assert status["ready"] is True and status["connection"] == spec.id
    assert [(m["id"], m["default_reasoning_effort"], m["reasoning_efforts"]) for m in status["models"]] == [
        ("model-a", None, []), ("model-b", None, [])]


@every_spec
def test_health_reports_http_errors_and_unreadable_lists(spec, monkeypatch):
    monkeypatch.setenv(spec.key_env, "test-key")
    status = asyncio.run(adapter(spec, lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})).health(refresh=True))
    assert status["ready"] is False and status["reason"] == f"{spec.name} API answered HTTP 401: API request failed"
    status = asyncio.run(adapter(spec, lambda r: httpx.Response(200, text="not JSON")).health(refresh=True))
    assert status["ready"] is False and "unreadable" in status["reason"]


@every_spec
def test_health_tries_again_once_after_a_transport_error(spec, monkeypatch):
    monkeypatch.setenv(spec.key_env, "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json={"data": [{"id": "model-a"}]})

    assert asyncio.run(adapter(spec, handler).health(refresh=True))["ready"] is True and len(calls) == 2

    calls.clear()

    def always_fails(request):
        calls.append(1)
        raise httpx.ConnectTimeout("timed out", request=request)

    status = asyncio.run(adapter(spec, always_fails).health(refresh=True))
    assert status["ready"] is False and status["reason"] == f"{spec.name} API unreachable: ConnectTimeout" and len(calls) == 2


@every_spec
def test_run_step_sends_json_mode_no_tools_and_never_a_reasoning_effort(spec, monkeypatch):
    monkeypatch.setenv(spec.key_env, "test-key")
    sent = []

    def handler(request):
        assert str(request.url) == f"{spec.base_url}/chat/completions" and request.headers["authorization"] == "Bearer test-key"
        sent.append(json.loads(request.content))
        return ok_response("model-a")

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    result = asyncio.run(adapter(spec, handler).run_step("BASE", "DEV", "MSG", schema, "model-a", "high"))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"claims": []}', "model-a", "chat-1")
    assert result.token_usage == {"total_tokens": 8}
    body = sent[0]
    assert body["model"] == "model-a" and body["response_format"] == {"type": "json_object"}
    assert "tools" not in body and "reasoning_effort" not in body and "response_format" in body
    # No schema copy: the schema reaches the model through the developer text the step stores.
    assert body["messages"][0]["content"] == "BASE\n\nDEV\n\nReturn only a JSON object."
    assert body["messages"][1] == {"role": "user", "content": "MSG"}


@every_spec
def test_run_step_without_key_or_model_sends_nothing(spec, monkeypatch):
    def handler(request):
        raise AssertionError("no request expected")

    monkeypatch.delenv(spec.key_env, raising=False)
    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.error, result.delivery_class) == ("unavailable", f"{spec.key_env} is not set", "before_send")
    monkeypatch.setenv(spec.key_env, "test-key")
    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, None))
    assert (result.status, result.error, result.delivery_class) == ("unavailable", "no model requested", "before_send")


@every_spec
@pytest.mark.parametrize("status,message,limited,quota", [
    (401, "Authentication Fails", False, False),
    (402, "Insufficient Balance", False, True),
    (429, "Too Many Requests", True, False),
    (500, "Internal Server Error", False, False),
])
def test_run_step_reports_http_errors_without_retrying(spec, monkeypatch, status, message, limited, quota):
    monkeypatch.setenv(spec.key_env, "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"error": {"message": message}})

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.raw_text, result.resolved_model, result.delivery_class) == ("failed", None, None, None)
    assert result.http_status == status and result.error.startswith(f"HTTP {status}: API request failed") and result.error.endswith("(quota)") is quota
    assert is_rate_limited(result) is limited
    assert (result.error_kind == "quota_exhausted") is quota
    assert calls == ["/compatible-mode/v1/chat/completions" if spec.id == "qwen" else "/v1/chat/completions"]


@every_spec
@pytest.mark.parametrize("exception,status,delivery", [
    (httpx.ConnectError, "unavailable", "before_send"),
    (httpx.ReadTimeout, "failed", "after_send_unknown"),
])
def test_run_step_reports_transport_errors_without_retrying(spec, monkeypatch, exception, status, delivery):
    monkeypatch.setenv(spec.key_env, "test-key")
    calls = []

    def handler(request):
        calls.append(1)
        raise exception("unreachable", request=request)

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.delivery_class) == (status, delivery)
    assert result.error_kind == ("network" if exception is httpx.ConnectError else "timeout")
    assert "unreachable" not in result.error
    assert len(calls) == 1


@every_spec
def test_run_step_reports_malformed_json_and_truncated_answers(spec, monkeypatch):
    monkeypatch.setenv(spec.key_env, "test-key")
    result = asyncio.run(adapter(spec, lambda r: httpx.Response(200, text="not JSON")).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.error, result.delivery_class) == ("failed", "Invalid JSON response", "after_send_unknown")
    for finish, content in (("length", '{"cla'), ("stop", "")):
        result = asyncio.run(adapter(spec, lambda r, f=finish, c=content: ok_response("model-a", c, f)).run_step("b", "d", "m", {}, "model-a"))
        assert (result.status, result.raw_text, result.error) == ("failed", content or None, f"finish reason {finish}")


@every_spec
@pytest.mark.parametrize("model_fields", [{}, {"model": None}, {"model": ""}])
def test_a_missing_answering_model_is_not_inferred(spec, monkeypatch, model_fields):
    monkeypatch.setenv(spec.key_env, "test-key")

    def handler(request):
        return httpx.Response(200, json={"id": "chat-1", **model_fields,
                                         "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", None, False)


@every_spec
def test_a_different_answering_model_is_reported_for_the_flow_to_reject(spec, monkeypatch):
    monkeypatch.setenv(spec.key_env, "test-key")
    result = asyncio.run(adapter(spec, lambda r: ok_response("another-model")).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.resolved_model) == ("completed", "another-model")  # flow.py records model_mismatch


def test_cancel_is_a_no_op_and_close_only_closes_an_owned_client():
    a = openai_compat.OpenAICompatAdapter(openai_compat.KIMI)
    assert asyncio.run(a.cancel()) is False
    asyncio.run(a.close())
    shared = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    b = openai_compat.OpenAICompatAdapter(openai_compat.KIMI, client=shared)
    asyncio.run(b.close())
    assert shared.is_closed is False
    asyncio.run(shared.aclose())

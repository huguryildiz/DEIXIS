import asyncio
import json

import httpx
import pytest

from deixis.models import deepseek
from deixis.models.adapter import is_rate_limited


def adapter(handler):
    return deepseek.DeepSeekAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_health_requires_key_without_sending_a_request(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    status = asyncio.run(adapter(lambda request: (_ for _ in ()).throw(AssertionError("unexpected request"))).health(refresh=True))
    assert status["ready"] is False and status["key_configured"] is False


def test_health_fetches_current_models_and_efforts(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def handler(request):
        assert request.url.path == "/models" and request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"object": "list", "data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]})

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is True
    assert [(m["id"], m["default_reasoning_effort"], [e["id"] for e in m["reasoning_efforts"]]) for m in status["models"]] == [
        ("deepseek-v4-flash", "high", ["none", "low", "high", "max"]),
        ("deepseek-v4-pro", "high", ["none", "low", "high", "max"]),
    ]


def test_run_step_sends_json_mode_and_requested_effort(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "chat-1", "model": "deepseek-v4-pro", "usage": {"total_tokens": 8},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"claims": []}'}}],
        })

    result = asyncio.run(adapter(handler).run_step("BASE", "DEVELOPER", "MESSAGE", {}, "deepseek-v4-pro", "max"))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"claims": []}', "deepseek-v4-pro", "chat-1",
    )
    body = sent[0]
    assert body["model"] == "deepseek-v4-pro" and body["reasoning_effort"] == "max"
    assert body["response_format"] == {"type": "json_object"} and "tools" not in body


def test_health_tries_again_once_after_a_transport_error(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "deepseek-v4-flash"}]})

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is True and calls == ["/models", "/models"]


def test_health_reports_the_second_transport_error(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise httpx.ConnectTimeout("timed out", request=request)

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is False and status["reason"] == "DeepSeek API unreachable: ConnectTimeout" and len(calls) == 2


def test_run_step_sends_the_developer_text_as_given_and_no_schema_copy(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "chat-1", "model": "deepseek-v4-flash", "usage": {"total_tokens": 5},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
        })

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    asyncio.run(adapter(handler).run_step("BASE", "DEV", "MSG", schema, "deepseek-v4-flash"))
    # The schema the model sees is the appendix in the developer text the step stores; the adapter adds no copy.
    system = sent[0]["messages"][0]["content"]
    assert system == "BASE\n\nDEV\n\nReturn only a JSON object."


def test_enforces_schema_is_false():
    assert deepseek.DeepSeekAdapter().enforces_schema is False


def test_run_step_requires_key_without_sending_a_request(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def handler(request):
        raise AssertionError("no request without a key")

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "deepseek-v4-pro"))
    assert (result.status, result.error, result.delivery_class) == (
        "unavailable", "DEEPSEEK_API_KEY is not set", "before_send",
    )


def test_run_step_requires_model_without_sending_a_request(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def handler(request):
        raise AssertionError("no request without a model")

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, None))
    assert (result.status, result.error, result.delivery_class) == ("unavailable", "no model requested", "before_send")


@pytest.mark.parametrize("status,message,limited", [
    (401, "Authentication Fails", False),
    (402, "Insufficient Balance", True),
    (429, "Too Many Requests", True),
    (500, "Internal Server Error", False),
    (503, "Service Unavailable", False),
])
def test_run_step_reports_http_errors_without_retrying(monkeypatch, status, message, limited):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"error": {"message": message}})

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "deepseek-v4-pro"))
    assert (result.status, result.raw_text, result.resolved_model, result.delivery_class) == ("failed", None, None, None)
    assert result.error.startswith(f"HTTP {status}: {message}")
    assert is_rate_limited(result) is limited
    assert calls == ["/chat/completions"]


@pytest.mark.parametrize("exception,status,delivery", [
    (httpx.ConnectError, "unavailable", "before_send"),
    (httpx.ConnectTimeout, "failed", "after_send_unknown"),
    (httpx.ReadTimeout, "failed", "after_send_unknown"),
])
def test_run_step_reports_transport_errors_without_retrying(monkeypatch, exception, status, delivery):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise exception("unreachable", request=request)

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "deepseek-v4-pro"))
    assert (result.status, result.error, result.delivery_class) == (status, f"{exception.__name__}: unreachable", delivery)
    assert not is_rate_limited(result)
    assert calls == ["/chat/completions"]


def test_run_step_reports_malformed_response_json(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="not JSON")

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "deepseek-v4-pro"))
    assert (result.status, result.error, result.delivery_class) == ("failed", "Invalid JSON response", "after_send_unknown")
    assert result.raw_text is None and result.resolved_model is None
    assert not is_rate_limited(result)
    assert calls == ["/chat/completions"]


@pytest.mark.parametrize("model_fields", [{}, {"model": None}, {"model": ""}])
def test_run_step_does_not_infer_missing_model_identity(monkeypatch, model_fields):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def handler(request):
        return httpx.Response(200, json={
            "id": "chat-1", "usage": {"total_tokens": 8}, **model_fields,
            "choices": [{"finish_reason": "stop", "message": {"content": '{"claims": []}'}}],
        })

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "deepseek-v4-pro"))
    assert (result.status, result.raw_text, result.resolved_model) == ("completed", '{"claims": []}', None)
    assert result.requested_model_verified is False
    assert result.external_thread_id == "chat-1" and result.token_usage == {"total_tokens": 8}


@pytest.mark.parametrize("finish,content", [("length", '{"cla'), ("stop", "")])
def test_run_step_does_not_complete_truncated_or_empty_answers(monkeypatch, finish, content):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def handler(request):
        return httpx.Response(200, json={
            "model": "deepseek-v4-pro",
            "choices": [{"finish_reason": finish, "message": {"content": content}}],
        })

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "deepseek-v4-pro"))
    assert (result.status, result.raw_text, result.error, result.resolved_model) == (
        "failed", content or None, f"finish reason {finish}", "deepseek-v4-pro",
    )

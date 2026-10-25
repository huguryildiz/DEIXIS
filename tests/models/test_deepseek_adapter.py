import asyncio
import json

import httpx
import pytest

from deixis.models import deepseek


def adapter(handler):
    return deepseek.DeepSeekAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


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


@pytest.mark.parametrize("model_fields", [{}])
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



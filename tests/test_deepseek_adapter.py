import asyncio
import json

import httpx

from deixis.models import deepseek


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

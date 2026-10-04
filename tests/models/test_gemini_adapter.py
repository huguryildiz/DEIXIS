import asyncio
import json

import httpx

from deixis.models import gemini

MODELS = {"models": [
    {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash", "thinking": True, "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash", "thinking": True, "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-flash-latest", "thinking": True, "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-2", "supportedGenerationMethods": ["embedContent"]},
]}


def adapter(handler):
    return gemini.GeminiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def answer(parts, finish="STOP"):
    return httpx.Response(200, json={"modelVersion": "gemini-3.8-flash", "responseId": "resp-1", "usageMetadata": {"totalTokenCount": 9},
                                     "candidates": [{"finishReason": finish, "content": {"parts": parts}}]})


def test_health_without_a_key_is_not_ready_and_sends_nothing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def handler(request):
        raise AssertionError("no request without a key")

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert (status["ready"], status["key_configured"]) == (False, False) and "GEMINI_API_KEY" in status["reason"]


def test_health_lists_text_models_and_thinking_levels_for_gemini_3(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def handler(request):
        assert request.headers["x-goog-api-key"] == "test-key" and "key" not in request.url.params
        return httpx.Response(200, json=MODELS)

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is True and status["isolation"] == {"instruction_sources": 0, "live_mcp_servers": []}
    assert [(m["id"], [e["id"] for e in m["reasoning_efforts"]]) for m in status["models"]] == [
        ("gemini-3.8-flash", ["low", "medium", "high"]), ("gemini-2.5-flash", []),
    ]


def test_rejected_key_is_reported_with_the_api_message(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "bad-key")
    status = asyncio.run(adapter(lambda request: httpx.Response(403, json={"error": {"message": "API key not valid"}})).health(refresh=True))
    assert status["ready"] is False and status["reason"] == "Gemini API answered HTTP 403: API key not valid"


def test_run_step_sends_one_structured_request_without_tools(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    sent = []

    def handler(request):
        assert request.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
        sent.append(json.loads(request.content))
        return answer([{"text": "weighing the passages", "thought": True}, {"text": '{"claims": []}'}])

    schema = {"type": "object", "properties": {"claims": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}}
    result = asyncio.run(adapter(handler).run_step("BASE", "DEVELOPER", "MESSAGE", schema, "gemini-3.8-flash", "low"))
    assert (result.status, result.raw_text, result.resolved_model, result.tool_item_types) == ("completed", '{"claims": []}', "gemini-3.8-flash", [])
    body = sent[0]
    assert body["systemInstruction"] == {"parts": [{"text": "BASE\n\nDEVELOPER"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "MESSAGE"}]}]
    assert body["generationConfig"]["responseJsonSchema"]["properties"]["claims"] == {"type": "array", "items": {"type": "string"}}
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"} and "tools" not in body


def test_truncated_rejected_and_lost_answers_are_not_completed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    truncated = asyncio.run(adapter(lambda r: answer([{"text": '{"cla'}], "MAX_TOKENS")).run_step("b", "d", "m", {}, "gemini-3.8-flash"))
    assert (truncated.status, truncated.error) == ("failed", "finish reason MAX_TOKENS")
    limited = asyncio.run(adapter(lambda r: httpx.Response(429, json={"error": {"message": "quota"}})).run_step("b", "d", "m", {}, "gemini-3.8-flash"))
    assert (limited.status, limited.error, limited.delivery_class) == ("failed", "HTTP 429: quota", None)

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    lost = asyncio.run(adapter(timeout).run_step("b", "d", "m", {}, "gemini-3.8-flash"))
    assert (lost.status, lost.delivery_class) == ("failed", "after_send_unknown")


def test_health_tries_again_once_after_a_transport_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini.shutil, "which", lambda name: None)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json=MODELS)

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is True and len(calls) == 2

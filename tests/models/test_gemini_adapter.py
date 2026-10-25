import asyncio
import json

import httpx

from deixis.models import gemini


def adapter(handler):
    return gemini.GeminiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def answer(parts, finish="STOP"):
    return httpx.Response(200, json={"modelVersion": "gemini-3.8-flash", "responseId": "resp-1", "usageMetadata": {"totalTokenCount": 9},
                                     "candidates": [{"finishReason": finish, "content": {"parts": parts}}]})


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
    assert (limited.status, limited.error, limited.delivery_class) == ("failed", "HTTP 429: API request failed", None)

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    lost = asyncio.run(adapter(timeout).run_step("b", "d", "m", {}, "gemini-3.8-flash"))
    assert (lost.status, lost.delivery_class) == ("failed", "after_send_unknown")



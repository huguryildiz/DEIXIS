"""The OpenAI Responses API connection for research steps (D34).

Mocked httpx transports only: these show the request shape and the handling of answers, not that the live API accepts
the requests or answers the way the mocks do.
"""

import asyncio
import json

import httpx

from deixis.domain import contracts
from deixis.models import openai_api


def adapter(handler):
    return openai_api.OpenAIAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def answer(model="gpt-5.5", text='{"claims": []}', status="completed", output=None, incomplete=None):
    items = output if output is not None else [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": []}]}]
    return httpx.Response(200, json={"id": "resp_1", "object": "response", "model": model, "status": status, "output": items,
                                     "incomplete_details": incomplete, "usage": {"total_tokens": 9}})


def test_health_drops_chat_models_without_strict_json_schema(monkeypatch):
    """Review of af41a88 (P2): the adapter always sends a strict schema, so a model that cannot take one is not offered."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    listed = ["gpt-4o-2024-05-13", "gpt-4o-2024-08-06", "gpt-4o-mini", "gpt-4o-mini-2024-07-18", "o1-preview",
              "o1-preview-2024-09-12", "o1-mini", "o1-mini-2024-09-12", "o1", "o1-2024-12-17", "o3-mini"]
    status = asyncio.run(adapter(lambda r: httpx.Response(200, json={"data": [{"id": i} for i in listed]})).health(refresh=True))
    assert [m["id"] for m in status["models"]] == [
        "gpt-4o-2024-08-06", "gpt-4o-mini", "gpt-4o-mini-2024-07-18", "o1", "o1-2024-12-17", "o3-mini"]


def test_run_step_sends_a_strict_schema_no_tools_no_storage_and_the_effort(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sent = []

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses" and request.headers["authorization"] == "Bearer test-key"
        sent.append(json.loads(request.content))
        return answer()

    schema = contracts.model_output_schema("abstract_screening")
    result = asyncio.run(adapter(handler).run_step("BASE", "DEV", "MSG", schema, "gpt-5.5", "high"))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"claims": []}', "gpt-5.5", "resp_1")
    body = sent[0]
    assert body["instructions"] == "BASE\n\nDEV" and body["input"] == "MSG" and body["store"] is False
    assert body["text"] == {"format": {"type": "json_schema", "name": "deixis_step", "schema": schema, "strict": True}}
    assert body["reasoning"] == {"effort": "high"}
    assert not {"tools", "tool_choice", "previous_response_id"} & body.keys()
    asyncio.run(adapter(handler).run_step("BASE", "DEV", "MSG", schema, "gpt-4o"))
    assert "reasoning" not in sent[1]


def test_a_different_answering_model_is_reported_for_the_flow_to_reject(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(model="gpt-5.5-mini")).run_step("b", "d", "m", {}, "gpt-5.5"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", "gpt-5.5-mini", False)



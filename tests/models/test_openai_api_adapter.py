"""The OpenAI Responses API connection for research steps (D34).

Mocked httpx transports only: these show the request shape and the handling of answers, not that the live API accepts
the requests or answers the way the mocks do.
"""

import asyncio
import json

import httpx
import pytest

from deixis.domain import contracts
from deixis.models import openai_api
from deixis.models.adapter import is_rate_limited


def adapter(handler):
    return openai_api.OpenAIAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def answer(model="gpt-5.5", text='{"claims": []}', status="completed", output=None, incomplete=None):
    items = output if output is not None else [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": []}]}]
    return httpx.Response(200, json={"id": "resp_1", "object": "response", "model": model, "status": status, "output": items,
                                     "incomplete_details": incomplete, "usage": {"total_tokens": 9}})


def test_identity():
    a = openai_api.OpenAIAdapter()
    assert (a.connection, a.enforces_schema, a.sends_reasoning_effort) == ("openai", True, False)


def test_health_without_key_is_not_configured_and_sends_nothing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = asyncio.run(adapter(lambda r: (_ for _ in ()).throw(AssertionError("unexpected request"))).health(refresh=True))
    assert (status["ready"], status["key_configured"], status["reason_code"]) == (False, False, "needs_key")


def test_health_keeps_chat_models_and_drops_the_rest(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    listed = ["gpt-5.5", "gpt-4o", "gpt-4o-2024-08-06", "o3", "gpt-4.1-mini", "text-embedding-3-small", "gpt-4o-audio-preview",
              "gpt-realtime", "dall-e-3", "whisper-1", "gpt-3.5-turbo", "gpt-4-turbo", "gpt-image-1", "chatgpt-4o-latest",
              "omni-moderation-latest", "gpt-4o-search-preview", "tts-1"]

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/models" and request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"object": "list", "data": [{"id": i, "object": "model"} for i in listed]})

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is True
    assert [m["id"] for m in status["models"]] == ["gpt-4.1-mini", "gpt-4o", "gpt-4o-2024-08-06", "gpt-5.5", "o3"]
    assert all(m["reasoning_efforts"] == [] for m in status["models"])


def test_health_drops_chat_models_without_strict_json_schema(monkeypatch):
    """Review of af41a88 (P2): the adapter always sends a strict schema, so a model that cannot take one is not offered."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    listed = ["gpt-4o-2024-05-13", "gpt-4o-2024-08-06", "gpt-4o-mini", "gpt-4o-mini-2024-07-18", "o1-preview",
              "o1-preview-2024-09-12", "o1-mini", "o1-mini-2024-09-12", "o1", "o1-2024-12-17", "o3-mini"]
    status = asyncio.run(adapter(lambda r: httpx.Response(200, json={"data": [{"id": i} for i in listed]})).health(refresh=True))
    assert [m["id"] for m in status["models"]] == [
        "gpt-4o-2024-08-06", "gpt-4o-mini", "gpt-4o-mini-2024-07-18", "o1", "o1-2024-12-17", "o3-mini"]


def test_run_step_sends_a_strict_schema_no_tools_no_storage_and_no_effort(monkeypatch):
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
    assert not {"tools", "tool_choice", "reasoning", "previous_response_id"} & body.keys()


def test_run_step_without_key_or_model_sends_nothing(monkeypatch):
    def handler(request):
        raise AssertionError("no request expected")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "gpt-5.5"))
    assert (result.status, result.error, result.delivery_class, result.error_kind) == (
        "unavailable", "OPENAI_API_KEY is not set", "before_send", "needs_key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert asyncio.run(adapter(handler).run_step("b", "d", "m", {}, None)).error == "no model requested"


def test_a_different_answering_model_is_reported_for_the_flow_to_reject(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(model="gpt-5.5-mini")).run_step("b", "d", "m", {}, "gpt-5.5"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", "gpt-5.5-mini", False)


def test_an_alias_answered_by_its_own_dated_snapshot_is_verified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(model="gpt-4o-2024-08-06")).run_step("b", "d", "m", {}, "gpt-4o"))
    assert (result.resolved_model, result.requested_model_verified) == ("gpt-4o-2024-08-06", True)


def test_a_tool_item_in_the_output_is_an_isolation_violation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    output = [{"type": "web_search_call", "id": "ws_1", "status": "completed"},
              {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]
    result = asyncio.run(adapter(lambda r: answer(output=output)).run_step("b", "d", "m", {}, "gpt-5.5"))
    assert (result.status, result.tool_item_types) == ("isolation_violation", ["web_search_call"])


def test_refused_and_incomplete_answers_fail(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    refused = [{"type": "message", "content": [{"type": "refusal", "refusal": "SYNTHETIC refusal"}]}]
    result = asyncio.run(adapter(lambda r: answer(output=refused)).run_step("b", "d", "m", {}, "gpt-5.5"))
    assert (result.status, result.raw_text, result.error) == ("failed", None, "finish reason refusal")
    result = asyncio.run(adapter(lambda r: answer(text='{"cla', status="incomplete", incomplete={"reason": "max_output_tokens"})).run_step(
        "b", "d", "m", {}, "gpt-5.5"))
    assert (result.status, result.raw_text, result.error) == ("failed", '{"cla', "finish reason max_output_tokens")


@pytest.mark.parametrize("status,limited", [(401, False), (429, True), (500, False)])
def test_http_errors_are_reported_without_retrying(monkeypatch, status, limited):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "SYNTHETIC"}})

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "gpt-5.5"))
    assert result.status == "failed" and result.http_status == status and is_rate_limited(result) is limited and len(calls) == 1

"""The Anthropic Messages API connection (D34).

Mocked httpx transports only: these show the request shape and the handling of answers, not that the live API accepts
the requests or answers the way the mocks do.
"""

import asyncio
import json

import httpx
import pytest

from deixis.domain import contracts
from deixis.models import anthropic_api
from deixis.models.adapter import is_rate_limited
from deixis.models.schema_subset import UNSUPPORTED_KEYS, portable_schema


def adapter(handler):
    return anthropic_api.AnthropicAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def answer(model="claude-opus-5-5", text='{"claims": []}', stop="end_turn", content=None):
    blocks = content if content is not None else [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": text}]
    return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": blocks,
                                     "stop_reason": stop, "usage": {"input_tokens": 5, "output_tokens": 3}})


def model_entry(model_id, structured=True, efforts=("low", "medium", "high")):
    effort = {"supported": bool(efforts), **{e: {"supported": e in efforts} for e in anthropic_api.EFFORTS}}
    return {"id": model_id, "display_name": f"SYNTHETIC {model_id}", "type": "model",
            "capabilities": {"structured_outputs": {"supported": structured}, "effort": effort}}


def test_identity():
    a = anthropic_api.AnthropicAdapter()
    assert (a.connection, a.enforces_schema, a.sends_reasoning_effort) == ("anthropic", True, True)


def test_health_without_key_is_not_configured_and_sends_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = asyncio.run(adapter(lambda r: (_ for _ in ()).throw(AssertionError("unexpected request"))).health(refresh=True))
    assert (status["ready"], status["key_configured"], status["reason_code"]) == (False, False, "needs_key")


def test_health_lists_models_that_take_structured_outputs_with_their_efforts(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def handler(request):
        assert str(request.url) == "https://api.anthropic.com/v1/models?limit=1000"
        assert request.headers["x-api-key"] == "test-key" and request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={"data": [model_entry("claude-opus-5-5", efforts=anthropic_api.EFFORTS),
                                                  model_entry("claude-old", structured=False),
                                                  model_entry("claude-haiku-4-5", efforts=())], "has_more": False})

    status = asyncio.run(adapter(handler).health(refresh=True))
    assert status["ready"] is True
    assert [(m["id"], m["display_name"], [e["id"] for e in m["reasoning_efforts"]]) for m in status["models"]] == [
        ("claude-opus-5-5", "SYNTHETIC claude-opus-5-5", list(anthropic_api.EFFORTS)),
        ("claude-haiku-4-5", "SYNTHETIC claude-haiku-4-5", [])]


def test_health_reports_a_refused_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    status = asyncio.run(adapter(lambda r: httpx.Response(401, json={"type": "error", "error": {"message": "invalid x-api-key"}})).health(refresh=True))
    assert status["ready"] is False and status["reason"] == "Anthropic API answered HTTP 401: API request failed"


def test_run_step_sends_the_schema_as_output_format_no_tools_and_the_effort(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = []

    def handler(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages" and request.headers["x-api-key"] == "test-key"
        sent.append(json.loads(request.content))
        return answer()

    schema = contracts.model_output_schema("abstract_screening")
    result = asyncio.run(adapter(handler).run_step("BASE", "DEV", "MSG", schema, "claude-opus-5-5", "high"))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"claims": []}', "claude-opus-5-5", "msg_1")
    body = sent[0]
    assert body["model"] == "claude-opus-5-5" and body["system"] == "BASE\n\nDEV"
    assert body["messages"] == [{"role": "user", "content": "MSG"}]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": portable_schema(schema)}, "effort": "high"}
    # No tools, no tool choice, no server-side fallback model, no thinking override.
    assert not {"tools", "tool_choice", "fallbacks", "thinking"} & body.keys()


def test_the_sent_schema_has_no_keyword_the_api_rejects_and_keeps_names_and_patterns():
    for key, schema in contracts.model_transport_schemas().items():
        text = json.dumps(portable_schema(schema))
        sent = portable_schema(schema)

        def walk(node, in_names=False):
            if isinstance(node, dict):
                for k, v in node.items():
                    if not in_names:
                        assert k not in UNSUPPORTED_KEYS, f"{key}: {k}"
                        if k == "minItems":
                            assert v <= 1, key
                    walk(v, in_names=k in ("properties", "$defs") and not in_names)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(sent)
        assert text.count('"pattern"') == json.dumps(schema).count('"pattern"'), key
    named = {"type": "object", "properties": {"maxLength": {"type": "string", "maxLength": 3}}, "required": ["maxLength"],
             "additionalProperties": False}
    assert portable_schema(named)["properties"] == {"maxLength": {"type": "string"}}


def test_run_step_without_effort_leaves_the_api_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = []
    asyncio.run(adapter(lambda r: sent.append(json.loads(r.content)) or answer()).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert "effort" not in sent[0]["output_config"]


def test_run_step_without_key_or_model_sends_nothing(monkeypatch):
    def handler(request):
        raise AssertionError("no request expected")

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.error, result.delivery_class, result.error_kind) == (
        "unavailable", "ANTHROPIC_API_KEY is not set", "before_send", "needs_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, None))
    assert (result.status, result.error) == ("unavailable", "no model requested")


def test_a_different_answering_model_is_reported_for_the_flow_to_reject(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(model="claude-sonnet-5-5")).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", "claude-sonnet-5-5", False)


def test_an_alias_answered_by_its_own_dated_snapshot_is_verified(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(model="claude-haiku-4-5-20251001")).run_step("b", "d", "m", {}, "claude-haiku-4-5"))
    assert (result.resolved_model, result.requested_model_verified) == ("claude-haiku-4-5-20251001", True)
    other = asyncio.run(adapter(lambda r: answer(model="claude-haiku-4-5-mini")).run_step("b", "d", "m", {}, "claude-haiku-4-5"))
    assert other.requested_model_verified is False


def test_a_tool_item_in_the_answer_is_an_isolation_violation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    blocks = [{"type": "server_tool_use", "id": "t1", "name": "web_search", "input": {}}, {"type": "text", "text": "{}"}]
    result = asyncio.run(adapter(lambda r: answer(content=blocks)).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.tool_item_types) == ("isolation_violation", ["server_tool_use"])


@pytest.mark.parametrize("stop,text", [("max_tokens", '{"cla'), ("refusal", ""), ("end_turn", "")])
def test_a_truncated_refused_or_empty_answer_fails(monkeypatch, stop, text):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(text=text, stop=stop)).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.raw_text, result.error) == ("failed", text or None, f"finish reason {stop}")


@pytest.mark.parametrize("status,limited", [(401, False), (429, True), (529, False), (500, False)])
def test_http_errors_are_reported_without_retrying(monkeypatch, status, limited):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"type": "error", "error": {"type": "x", "message": "SYNTHETIC"}})

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert result.status == "failed" and result.http_status == status and is_rate_limited(result) is limited and len(calls) == 1


@pytest.mark.parametrize("exception,status,delivery", [(httpx.ConnectError, "unavailable", "before_send"),
                                                       (httpx.ReadTimeout, "failed", "after_send_unknown")])
def test_transport_errors_are_reported_without_retrying(monkeypatch, exception, status, delivery):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def handler(request):
        raise exception("unreachable", request=request)

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class) == (status, delivery)

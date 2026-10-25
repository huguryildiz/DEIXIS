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
from deixis.models.schema_subset import UNSUPPORTED_KEYS, anthropic_schema


def adapter(handler, **kwargs):
    return anthropic_api.AnthropicAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)


def sse(*events, raw=False):
    """A server-sent event body: each event as `event:` and `data:` lines and a blank line; `raw` sends non-ASCII
    characters unescaped, as UTF-8."""
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=not raw)}\n\n" for e in events).encode()


def stream_events(model="claude-opus-5-5", text='{"claims": []}', stop="end_turn", content=None, end=True):
    """SYNTHETIC events of one streamed answer: thinking then text by default, the text split over two deltas."""
    blocks = content if content is not None else [{"type": "thinking", "thinking": "", "signature": ""}, {"type": "text", "text": text}]
    events = [{"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
                                                    "content": [], "stop_reason": None,
                                                    "usage": {"input_tokens": 5, "output_tokens": 1}}},
              {"type": "ping"}]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
            half = len(block["text"]) // 2
            for part in (block["text"][:half], block["text"][half:]):
                events.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": part}})
        elif block["type"] == "thinking":
            events.append({"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
            events.append({"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": "SYNTHETIC"}})
            events.append({"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": "s"}})
        else:
            events.append({"type": "content_block_start", "index": i, "content_block": block})
        events.append({"type": "content_block_stop", "index": i})
    events.append({"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 3}})
    if end:
        events.append({"type": "message_stop"})
    return events


def answer(model="claude-opus-5-5", text='{"claims": []}', stop="end_turn", content=None):
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=sse(*stream_events(model, text, stop, content)))


def test_health_without_key_is_not_configured_and_sends_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = asyncio.run(adapter(lambda r: (_ for _ in ()).throw(AssertionError("unexpected request"))).health(refresh=True))
    assert (status["ready"], status["key_configured"], status["reason_code"]) == (False, False, "needs_key")


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
    assert body["stream"] is True and body["max_tokens"] == 64000
    assert body["model"] == "claude-opus-5-5" and body["system"] == "BASE\n\nDEV"
    assert body["messages"] == [{"role": "user", "content": "MSG"}]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": anthropic_schema(schema)}, "effort": "high"}
    # No tools, no tool choice, no server-side fallback model, no thinking override.
    assert not {"tools", "tool_choice", "fallbacks", "thinking"} & body.keys()


def test_the_sent_schema_has_no_keyword_the_api_rejects_and_keeps_names_and_patterns_as_descriptions():
    for key, schema in contracts.model_transport_schemas().items():
        sent = anthropic_schema(schema)

        def walk(node, in_names=False):
            if isinstance(node, dict):
                for k, v in node.items():
                    if not in_names:
                        assert k not in UNSUPPORTED_KEYS | {"pattern"}, f"{key}: {k}"
                        if k == "minItems":
                            assert v <= 1, key
                    walk(v, in_names=k in ("properties", "$defs") and not in_names)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(sent)
        # Every pattern of the step schema is still in front of the model, as a sentence of the field's description.
        for pattern in set(_patterns(schema)):
            sentence = json.dumps(f"Must match the regular expression {pattern}", ensure_ascii=False)[1:-1]
            assert sentence in json.dumps(sent, ensure_ascii=False), (key, pattern)
    named = {"type": "object", "properties": {"maxLength": {"type": "string", "maxLength": 3}}, "required": ["maxLength"],
             "additionalProperties": False}
    assert anthropic_schema(named)["properties"] == {"maxLength": {"type": "string"}}


def _patterns(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern" and isinstance(v, str):
                yield v
            elif k not in ("enum", "const", "required", "default"):
                yield from _patterns(v)
    elif isinstance(node, list):
        for v in node:
            yield from _patterns(v)


def test_a_different_answering_model_is_reported_for_the_flow_to_reject(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(model="claude-sonnet-5-5")).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", "claude-sonnet-5-5", False)


def test_a_tool_item_in_the_answer_is_an_isolation_violation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    blocks = [{"type": "server_tool_use", "id": "t1", "name": "web_search", "input": {}}, {"type": "text", "text": "{}"}]
    result = asyncio.run(adapter(lambda r: answer(content=blocks)).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.tool_item_types) == ("isolation_violation", ["server_tool_use"])


@pytest.mark.parametrize("status,limited", [(401, False), (429, True)])
def test_http_errors_are_reported_without_retrying(monkeypatch, status, limited):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"type": "error", "error": {"type": "x", "message": "SYNTHETIC"}})

    result = asyncio.run(adapter(handler).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert result.status == "failed" and result.http_status == status and is_rate_limited(result) is limited and len(calls) == 1



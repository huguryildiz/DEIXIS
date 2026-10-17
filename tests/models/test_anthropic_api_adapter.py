"""The Anthropic Messages API connection (D34).

Mocked httpx transports only: these show the request shape and the handling of answers, not that the live API accepts
the requests or answers the way the mocks do.
"""

import asyncio
import hashlib
import json

import httpx
from jsonschema import Draft202012Validator
import pytest

from deixis.domain import contracts
from deixis.models import anthropic_api
from deixis.models.adapter import is_rate_limited
from deixis.models.schema_subset import ANTHROPIC_TRANSFORM_VERSION, UNSUPPORTED_KEYS, anthropic_schema, schema_digest


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


def test_a_nullable_field_the_answer_left_out_comes_back_as_null(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    schema = {"type": "object", "additionalProperties": False, "required": ["a", "b"], "properties": {
        "a": {"type": "string"}, "b": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    sent = []
    result = asyncio.run(adapter(lambda r: sent.append(json.loads(r.content)) or answer(text='{"a": "x"}')).run_step(
        "b", "d", "m", schema, "claude-opus-5-5"))
    assert sent[0]["output_config"]["format"]["schema"]["required"] == ["a"]
    assert (result.status, json.loads(result.raw_text)) == ("completed", {"a": "x", "b": None})
    # Nothing left out: the text is passed on exactly as it came.
    result = asyncio.run(adapter(lambda r: answer(text='{"a": "x",  "b": "y"}')).run_step("b", "d", "m", schema, "claude-opus-5-5"))
    assert result.raw_text == '{"a": "x",  "b": "y"}'


NULLABLE = {"type": "object", "additionalProperties": False, "required": ["a", "b"], "properties": {
    "a": {}, "b": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}


@pytest.mark.parametrize("text", ['{"a": 1' + "0" * 5000 + "}", '{"a": ' + "[" * 200000 + "]" * 200000 + "}"])
def test_an_answer_past_the_decoder_limits_is_passed_on_unchanged(monkeypatch, text):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(text=text)).run_step("b", "d", "m", NULLABLE, "claude-opus-5-5"))
    assert (result.status, result.raw_text) == ("completed", text)
    assert "filled_nulls" not in result.transport


def test_a_filled_answer_is_written_back_in_ascii_so_a_lone_surrogate_stays_storable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    text = '{"a": "\\ud800 caf\u00e9"}'
    result = asyncio.run(adapter(lambda r: answer(text=text)).run_step("b", "d", "m", NULLABLE, "claude-opus-5-5"))
    assert result.status == "completed" and result.raw_text.isascii()
    result.raw_text.encode("utf-8")  # no lone surrogate reaches storage
    assert json.loads(result.raw_text) == {"a": "\ud800 caf\u00e9", "b": None}
    assert result.transport["filled_nulls"] == ["/b"]
    assert result.transport["received_sha256"] == "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def test_the_result_names_the_sent_schema_by_digest_and_transform_version(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = []
    schema = contracts.model_output_schema("table_columns")
    result = asyncio.run(adapter(lambda r: sent.append(json.loads(r.content)) or answer()).run_step(
        "b", "d", "m", schema, "claude-opus-5-5"))
    body_schema = sent[0]["output_config"]["format"]["schema"]
    assert result.transport == {"schema_transform": ANTHROPIC_TRANSFORM_VERSION, "sent_schema_sha256": schema_digest(body_schema)}
    assert body_schema == anthropic_schema(schema)


@pytest.mark.parametrize("value", [{"text": "SYNTHETIC answer text"}, {"answer": "no"}, {"option_ids": ["o1"]},
                                   {"number": 3}, {"number": 3, "unit": "dB"}, {"number": 3, "as_stated": "3 dB"}, None])
def test_each_cell_extraction_value_shape_comes_back_valid_for_the_full_schema(monkeypatch, value):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    schema = contracts.model_output_schema("cell_extraction")
    cell = {"column_id": "col_SYNTHETIC1", "state": "value" if value else "unknown", "note": "SYNTHETIC note",
            "evidence": [{"passage_id": "psg_SYNTHETIC1", "quote": "SYNTHETIC quoted passage text"}]}
    if value is not None:
        cell["value"] = value
    text = json.dumps({"schema_version": "deixis.evidence_cell_draft.v1", "step_input_id": "sti_SYNTHETIC1",
                       "scope_revision": 1, "cells": [cell]})
    result = asyncio.run(adapter(lambda r: answer(text=text)).run_step("b", "d", "m", schema, "claude-opus-5-5"))
    output = json.loads(result.raw_text)
    assert [e.message for e in Draft202012Validator(schema).iter_errors(output)] == []
    expected = {"unit": None, "as_stated": None, **value} if value and "number" in value else value
    assert output["cells"][0]["value"] == expected


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


def test_a_streamed_answer_joins_its_text_deltas_and_merges_usage(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(text='{"claims": [1, 2]}')).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.raw_text, result.tool_item_types) == ("completed", '{"claims": [1, 2]}', [])
    # message_start gives input tokens, message_delta the final output count
    assert result.token_usage == {"input_tokens": 5, "output_tokens": 3}


def test_a_max_tokens_stop_keeps_the_cut_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = asyncio.run(adapter(lambda r: answer(text='{"cla', stop="max_tokens")).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.raw_text, result.error, result.token_usage["output_tokens"]) == (
        "failed", '{"cla', "finish reason max_tokens", 3)


def test_an_error_event_mid_stream_fails_after_send(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    events = stream_events(end=False)[:4] + [{"type": "error", "error": {"type": "overloaded_error", "message": "SYNTHETIC"}}]
    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=sse(*events))).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class, result.error) == ("failed", "after_send_unknown", "stream error overloaded_error")
    assert result.external_thread_id == "msg_1"


def test_a_stream_cut_before_message_stop_fails_after_send(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    events = stream_events(end=False)
    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=sse(*events))).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class, result.error) == ("failed", "after_send_unknown", "Incomplete stream")


def test_a_broken_event_fails_after_send(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    body = sse(*stream_events()[:2]) + b"data: {not json\n\n"
    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=body)).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class) == ("failed", "after_send_unknown")


def test_a_rate_limit_answer_keeps_its_retry_after(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    response = httpx.Response(429, headers={"retry-after": "30"},
                              json={"type": "error", "error": {"type": "rate_limit_error", "message": "SYNTHETIC"}})
    result = asyncio.run(adapter(lambda r: response).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.http_status, result.retry_after, is_rate_limited(result)) == ("failed", 429, "30", True)


def test_the_turn_limit_bounds_the_whole_stream_not_each_read(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def pings():
        yield sse(*stream_events()[:1])
        while True:  # every read answers quickly, the turn never ends
            await asyncio.sleep(0.02)
            yield sse({"type": "ping"})

    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=pings()), turn_timeout=0.2).run_step(
        "b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class, result.error) == ("failed", "after_send_unknown", "TimeoutError")


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_unicode_line_separators_inside_text_are_kept(monkeypatch, separator):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    text = f'{{"claims": ["a{separator}b"]}}'
    body = sse(*stream_events(text=text), raw=True)  # sent unescaped, which SSE allows inside a line
    assert separator.encode() in body
    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=body)).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.raw_text) == ("completed", text)


def test_chunk_boundaries_inside_a_character_and_a_crlf_keep_the_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    text = '{"claims": ["ölçü — 2\u2028"]}'
    body = sse(*stream_events(text=text), raw=True).replace(b"\n", b"\r\n")
    multi = body.index("ö".encode()) + 1  # inside the two-byte ö
    crlf = body.index(b"\r\n") + 1  # between CR and LF

    async def chunks():
        cuts = sorted({0, multi, crlf, len(body)})
        for a, b in zip(cuts, cuts[1:]):
            yield body[a:b]

    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=chunks())).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.raw_text) == ("completed", text)


def test_cr_only_line_ends_are_read(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    body = sse(*stream_events()).replace(b"\n", b"\r")
    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=body)).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.raw_text) == ("completed", '{"claims": []}')


def _head():
    """The start of a stream up to its first text delta, which carries '{"claim'."""
    return sse(*stream_events(text='{"claims": []}')[:8])


@pytest.mark.parametrize("tail", [b"data: {\"x\": \"\xc3", b"data: \xff\xfe\n\n"], ids=["eof_inside_a_character", "invalid_utf8"])
def test_bytes_that_are_not_utf8_fail_after_send_and_keep_the_text_so_far(monkeypatch, tail):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    async def chunks():
        yield _head()
        yield tail

    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=chunks())).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class, result.error) == ("failed", "after_send_unknown", "UnicodeDecodeError")
    assert result.raw_text == '{"claim' and result.external_thread_id == "msg_1"


def test_an_unexpected_error_mid_stream_fails_after_send_and_keeps_the_text_so_far(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def chunks():
        yield _head()
        raise RuntimeError("SYNTHETIC transport failure")

    result = asyncio.run(adapter(lambda r: httpx.Response(200, content=chunks())).run_step("b", "d", "m", {}, "claude-opus-5-5"))
    assert (result.status, result.delivery_class, result.error, result.raw_text) == (
        "failed", "after_send_unknown", "RuntimeError", '{"claim')

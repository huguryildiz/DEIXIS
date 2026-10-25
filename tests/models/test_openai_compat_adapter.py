"""The generic OpenAI-compatible adapter behind the Qwen, Kimi, Mistral, Grok, GitHub Copilot, GLM, Muse Spark, Muse
Glimmer and Ollama connections.

Mocked httpx transports only: these show the request shape and error handling, not that the live providers accept
the requests or answer the way the mocks do.
"""

import asyncio
import json

import httpx
import pytest

from deixis.models import openai_compat

SPECS = list(openai_compat.CONNECTIONS.values())
KEYED = [c for c in SPECS if c.key_env]
# Ollama answers steps through its own /api/chat (tested below); every other connection through /chat/completions.
CHAT = [c for c in SPECS if c.id != "ollama"]
# One representative chat connection for the kept checks (the grid over every connection was cut).
one_chat_spec = pytest.mark.parametrize("spec", CHAT[:1], ids=[c.id for c in CHAT[:1]])


# OpenRouter keeps only listed models that take structured outputs; the other connections ignore the field.
SO = {"supported_parameters": ["structured_outputs"]}


def set_key(spec, monkeypatch):
    if spec.key_env:
        monkeypatch.setenv(spec.key_env, "test-key")


def auth_ok(spec, request):
    """A keyed connection sends its key as a bearer token; Ollama sends no Authorization header."""
    return request.headers.get("authorization") == ("Bearer test-key" if spec.key_env else None)


def mid(spec, suffix):
    """A model id the connection keeps: the Muse connections keep only ids with their own prefix."""
    return f"{spec.model_prefix}-{suffix}" if spec.model_prefix else f"model-{suffix}"


def adapter(spec, handler):
    return openai_compat.OpenAICompatAdapter(spec, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok_response(model="m-1", content='{"claims": []}', finish="stop", **extra):
    return httpx.Response(200, json={"id": "chat-1", "model": model, "usage": {"total_tokens": 8},
                                     "choices": [{"finish_reason": finish, "message": {"content": content}}], **extra})


@pytest.mark.parametrize("spec", [c for c in CHAT if not c.json_schema][:1], ids=[c.id for c in CHAT if not c.json_schema][:1])
def test_run_step_sends_json_mode_no_tools_and_never_a_reasoning_effort(spec, monkeypatch):
    set_key(spec, monkeypatch)
    sent = []

    def handler(request):
        assert str(request.url) == f"{spec.base_url}/chat/completions" and auth_ok(spec, request)
        sent.append(json.loads(request.content))
        return ok_response("model-a")

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    result = asyncio.run(adapter(spec, handler).run_step("BASE", "DEV", "MSG", schema, "model-a", "high"))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"claims": []}', "model-a", "chat-1")
    assert result.token_usage == {"total_tokens": 8}
    body = sent[0]
    assert body["model"] == "model-a" and body["response_format"] == {"type": "json_object"}
    assert "tools" not in body and "reasoning_effort" not in body and "response_format" in body
    # No schema copy: the schema reaches the model through the developer text the step stores.
    assert body["messages"][0]["content"] == "BASE\n\nDEV\n\nReturn only a JSON object."
    assert body["messages"][1] == {"role": "user", "content": "MSG"}


@one_chat_spec
@pytest.mark.parametrize("model_fields", [{}])
def test_a_missing_answering_model_is_not_inferred(spec, monkeypatch, model_fields):
    set_key(spec, monkeypatch)

    def handler(request):
        return httpx.Response(200, json={"id": "chat-1", **model_fields,
                                         "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", None, False)


TOOL_CALL = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]


@one_chat_spec
@pytest.mark.parametrize("message_extra,finish,expected", [
    ({"tool_calls": TOOL_CALL}, "stop", ["function"]),          # a tool call next to usable content, finish "stop"
])
def test_a_tool_call_in_the_answer_is_an_isolation_violation(spec, monkeypatch, message_extra, finish, expected):
    """Review of af41a88 (P1): no tools are offered, so a tool call fails the step, whatever content comes with it."""
    set_key(spec, monkeypatch)

    def handler(request):
        return httpx.Response(200, json={"id": "chat-1", "model": "model-a", "choices": [
            {"finish_reason": finish, "message": {"content": '{"claims": []}', **message_extra}}]})

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.tool_item_types) == ("isolation_violation", expected)


@pytest.mark.parametrize("spec", [openai_compat.OLLAMA, openai_compat.LOCAL_SERVER], ids=["ollama", "local_server"])
def test_a_local_connection_never_sends_through_a_proxy_from_the_environment(spec, monkeypatch):
    """Review of af41a88 (P1): with HTTP_PROXY set and NO_PROXY empty, the default client sends loopback requests
    through the proxy. A keyless connection's own client ignores the environment and follows no redirect."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://proxy.example.com:3128")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    url = httpx.URL("http://127.0.0.1:8080/v1/chat/completions")
    control = httpx.AsyncClient()
    assert control._transport_for_url(url) is not control._transport  # the default client would use the proxy
    client = openai_compat.OpenAICompatAdapter(spec)._http()
    assert client.trust_env is False and client.follow_redirects is False and not client._mounts
    assert client._transport_for_url(url) is client._transport
    keyed = openai_compat.OpenAICompatAdapter(openai_compat.KIMI)._http()
    assert keyed.trust_env is True  # remote APIs keep the person's proxy
    for c in (control, client, keyed):
        asyncio.run(c.aclose())


def test_openrouter_sends_the_schema_strictly_and_requires_providers_that_take_it(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return ok_response("openai/gpt-x")

    schema = {"type": "object", "properties": {"note": {"type": "string", "maxLength": 9, "pattern": "^c[0-9]{1,3}$"},
                                               "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4}},
              "required": ["note", "items"], "additionalProperties": False}
    result = asyncio.run(adapter(openai_compat.OPENROUTER, handler).run_step("BASE", "DEV", "MSG", schema, "openai/gpt-x", "high"))
    assert (result.status, result.resolved_model) == ("completed", "openai/gpt-x")
    body = sent[0]
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    # The portable subset: length and count bounds go, the pattern stays; DEIXIS still validates the full schema.
    assert body["response_format"]["json_schema"]["schema"]["properties"] == {
        "note": {"type": "string", "pattern": "^c[0-9]{1,3}$"}, "items": {"type": "array", "items": {"type": "string"}, "minItems": 1}}
    assert body["provider"] == {"require_parameters": True}
    assert "tools" not in body and "reasoning_effort" not in body
    assert body["messages"][0]["content"] == "BASE\n\nDEV"


@pytest.mark.parametrize("value", ["http://192.168.1.5:8080/v1"])
def test_a_remote_or_malformed_local_server_address_is_refused(value):
    with pytest.raises(ValueError):
        openai_compat.loopback_url(value)


def local(handler, address):
    return openai_compat.OpenAICompatAdapter(openai_compat.LOCAL_SERVER, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                                             base_url=lambda: address)


@pytest.mark.parametrize("address", [None])
def test_the_local_server_without_a_loopback_address_sends_nothing(address):
    def handler(request):
        raise AssertionError("no request expected")

    status = asyncio.run(local(handler, address).health(refresh=True))
    assert (status["ready"], status["reason_code"], status["base_url"]) == (False, "needs_setup", None)
    result = asyncio.run(local(handler, address).run_step("b", "d", "m", {}, "llama-3"))
    assert (result.status, result.delivery_class) == ("unavailable", "before_send")


def test_a_slow_success_with_the_same_key_does_not_cover_a_newer_refusal(monkeypatch):
    spec = KEYED[0]
    set_key(spec, monkeypatch)
    state = {"status": 200, "gate": None, "gated": False, "requests": 0}

    async def handler(request):
        state["requests"] += 1
        if state["gate"] is not None and not state["gated"]:
            state["gated"] = True
            await state["gate"].wait()
        return httpx.Response(state["status"], json={"data": [{"id": mid(spec, "a"), **SO}]})
    connection = adapter(spec, handler)

    async def scenario():
        state["gate"] = asyncio.Event()
        slow = asyncio.create_task(connection.health(refresh=True))
        while state["requests"] == 0:
            await asyncio.sleep(0)
        state["status"] = 401
        assert (await connection.health(refresh=True))["ready"] is False
        state["gate"].set()
        await slow
        before = state["requests"]
        assert (await connection.health())["ready"] is False and state["requests"] == before

    asyncio.run(scenario())



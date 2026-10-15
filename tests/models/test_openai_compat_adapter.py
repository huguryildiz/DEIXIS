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
from deixis.models.adapter import is_rate_limited

SPECS = list(openai_compat.CONNECTIONS.values())
KEYED = [c for c in SPECS if c.key_env]
every_spec = pytest.mark.parametrize("spec", SPECS, ids=[c.id for c in SPECS])
keyed_spec = pytest.mark.parametrize("spec", KEYED, ids=[c.id for c in KEYED])


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


def test_the_connections_use_the_documented_endpoints_and_key_variables():
    assert {c.id: (c.base_url, c.key_env) for c in SPECS} == {
        "qwen": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "kimi": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
        "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
        "grok": ("https://api.x.ai/v1", "XAI_API_KEY"),
        "copilot": ("https://models.github.ai/inference", "GITHUB_TOKEN"),
        "glm": ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
        "muse_spark": ("https://api.meta.ai/v1", "MODEL_API_KEY"),
        "muse_glimmer": ("https://api.meta.ai/v1", "MODEL_API_KEY"),
        "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        "mimo": ("https://api.xiaomimimo.com/v1", "MIMO_API_KEY"),
        "ollama": ("http://127.0.0.1:11434/v1", None),
    }
    assert "local_server" not in openai_compat.CONNECTIONS  # its address comes from Settings
    assert openai_compat.COPILOT.list_url == "https://models.github.ai/catalog/models"
    assert openai_compat.BY_KEY_ENV["MODEL_API_KEY"].base_url == "https://api.meta.ai/v1"


@every_spec
def test_identity_and_schema_enforcement(spec):
    a = openai_compat.OpenAICompatAdapter(spec)
    assert (a.connection, a.enforces_schema) == (spec.id, spec.id == "openrouter")


@keyed_spec
def test_health_requires_key_without_sending_a_request(spec, monkeypatch):
    monkeypatch.delenv(spec.key_env, raising=False)
    status = asyncio.run(adapter(spec, lambda r: (_ for _ in ()).throw(AssertionError("unexpected request"))).health(refresh=True))
    assert status["ready"] is False and status["key_configured"] is False and status["reason"] == f"Add a {spec.name} API key in Settings"


@every_spec
def test_health_lists_models_and_offers_no_reasoning_effort(spec, monkeypatch):
    set_key(spec, monkeypatch)

    def handler(request):
        assert str(request.url) == spec.list_url and auth_ok(spec, request)
        return httpx.Response(200, json={"object": "list", "data": [{"id": mid(spec, "a"), **SO}, {"id": mid(spec, "b"), **SO}, {"object": "x"}]})

    status = asyncio.run(adapter(spec, handler).health(refresh=True))
    assert status["ready"] is True and status["connection"] == spec.id
    assert [(m["id"], m["default_reasoning_effort"], m["reasoning_efforts"]) for m in status["models"]] == [
        (mid(spec, "a"), None, []), (mid(spec, "b"), None, [])]
    assert ("key_configured" in status) is bool(spec.key_env)


def test_copilot_reads_the_github_models_catalog_array(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-key")
    status = asyncio.run(adapter(openai_compat.COPILOT, lambda r: httpx.Response(200, json=[
        {"id": "openai/gpt-4.1", "publisher": "OpenAI"}, {"id": "meta/llama-4"}])).health(refresh=True))
    assert status["ready"] is True and [m["id"] for m in status["models"]] == ["openai/gpt-4.1", "meta/llama-4"]


def test_glm_without_a_model_list_offers_its_known_models(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    status = asyncio.run(adapter(openai_compat.GLM, lambda r: httpx.Response(404)).health(refresh=True))
    assert status["ready"] is True and [m["id"] for m in status["models"]] == list(openai_compat.GLM.static_models)


def test_the_muse_connections_split_metas_model_list(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    listed = {"data": [{"id": "muse-spark-1.3"}, {"id": "Muse-Glimmer-30B"}, {"id": "llama-4"}]}
    spark = asyncio.run(adapter(openai_compat.MUSE_SPARK, lambda r: httpx.Response(200, json=listed)).health(refresh=True))
    glimmer = asyncio.run(adapter(openai_compat.MUSE_GLIMMER, lambda r: httpx.Response(200, json=listed)).health(refresh=True))
    assert [m["id"] for m in spark["models"]] == ["muse-spark-1.3"] and [m["id"] for m in glimmer["models"]] == ["Muse-Glimmer-30B"]
    none = asyncio.run(adapter(openai_compat.MUSE_GLIMMER, lambda r: httpx.Response(200, json={"data": [{"id": "llama-4"}]})).health(refresh=True))
    assert none["ready"] is False and none["reason_code"] == "no_models"


def test_ollama_needs_no_key_and_says_when_it_is_not_running():
    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    status = asyncio.run(adapter(openai_compat.OLLAMA, refused).health(refresh=True))
    assert status["ready"] is False and "key_configured" not in status and "ollama serve" in status["reason"]
    empty = asyncio.run(adapter(openai_compat.OLLAMA, lambda r: httpx.Response(200, json={"data": []})).health(refresh=True))
    assert empty["ready"] is False and "ollama pull" in empty["reason"]
    # Ollama 0.34 with no models answers "data": null; that is the same empty list, not a crash.
    null = asyncio.run(adapter(openai_compat.OLLAMA, lambda r: httpx.Response(200, json={"object": "list", "data": None})).health(refresh=True))
    assert null["ready"] is False and "ollama pull" in null["reason"]


@every_spec
def test_health_reports_http_errors_and_unreadable_lists(spec, monkeypatch):
    set_key(spec, monkeypatch)
    status = asyncio.run(adapter(spec, lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})).health(refresh=True))
    assert status["ready"] is False and status["reason"] == f"{spec.name} API answered HTTP 401: API request failed"
    status = asyncio.run(adapter(spec, lambda r: httpx.Response(200, text="not JSON")).health(refresh=True))
    assert status["ready"] is False and "unreadable" in status["reason"]


@every_spec
def test_health_tries_again_once_after_a_transport_error(spec, monkeypatch):
    set_key(spec, monkeypatch)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json={"data": [{"id": mid(spec, "a"), **SO}]})

    assert asyncio.run(adapter(spec, handler).health(refresh=True))["ready"] is True and len(calls) == 2

    calls.clear()

    def always_fails(request):
        calls.append(1)
        raise httpx.ConnectTimeout("timed out", request=request)

    status = asyncio.run(adapter(spec, always_fails).health(refresh=True))
    unreachable = f"{spec.name} API unreachable: ConnectTimeout" if spec.key_env else f"{spec.name} is not running: open the Ollama app or run `ollama serve`"
    assert status["ready"] is False and status["reason"] == unreachable and len(calls) == 2


@pytest.mark.parametrize("spec", [c for c in SPECS if not c.json_schema], ids=[c.id for c in SPECS if not c.json_schema])
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


@keyed_spec
def test_run_step_without_key_or_model_sends_nothing(spec, monkeypatch):
    def handler(request):
        raise AssertionError("no request expected")

    monkeypatch.delenv(spec.key_env, raising=False)
    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.error, result.delivery_class) == ("unavailable", f"{spec.key_env} is not set", "before_send")
    set_key(spec, monkeypatch)
    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, None))
    assert (result.status, result.error, result.delivery_class) == ("unavailable", "no model requested", "before_send")


@every_spec
@pytest.mark.parametrize("status,message,limited,quota", [
    (401, "Authentication Fails", False, False),
    (402, "Insufficient Balance", False, True),
    (429, "Too Many Requests", True, False),
    (500, "Internal Server Error", False, False),
])
def test_run_step_reports_http_errors_without_retrying(spec, monkeypatch, status, message, limited, quota):
    set_key(spec, monkeypatch)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"error": {"message": message}})

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.raw_text, result.resolved_model, result.delivery_class) == ("failed", None, None, None)
    assert result.http_status == status and result.error.startswith(f"HTTP {status}: API request failed") and result.error.endswith("(quota)") is quota
    assert is_rate_limited(result) is limited
    assert (result.error_kind == "quota_exhausted") is quota
    assert calls == [httpx.URL(f"{spec.base_url}/chat/completions").path]


@every_spec
@pytest.mark.parametrize("exception,status,delivery", [
    (httpx.ConnectError, "unavailable", "before_send"),
    (httpx.ReadTimeout, "failed", "after_send_unknown"),
])
def test_run_step_reports_transport_errors_without_retrying(spec, monkeypatch, exception, status, delivery):
    set_key(spec, monkeypatch)
    calls = []

    def handler(request):
        calls.append(1)
        raise exception("unreachable", request=request)

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.delivery_class) == (status, delivery)
    assert result.error_kind == ("network" if exception is httpx.ConnectError else "timeout")
    assert "unreachable" not in result.error
    assert len(calls) == 1


@every_spec
def test_run_step_reports_malformed_json_and_truncated_answers(spec, monkeypatch):
    set_key(spec, monkeypatch)
    result = asyncio.run(adapter(spec, lambda r: httpx.Response(200, text="not JSON")).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.error, result.delivery_class) == ("failed", "Invalid JSON response", "after_send_unknown")
    for finish, content in (("length", '{"cla'), ("stop", "")):
        result = asyncio.run(adapter(spec, lambda r, f=finish, c=content: ok_response("model-a", c, f)).run_step("b", "d", "m", {}, "model-a"))
        assert (result.status, result.raw_text, result.error) == ("failed", content or None, f"finish reason {finish}")


@every_spec
@pytest.mark.parametrize("model_fields", [{}, {"model": None}, {"model": ""}])
def test_a_missing_answering_model_is_not_inferred(spec, monkeypatch, model_fields):
    set_key(spec, monkeypatch)

    def handler(request):
        return httpx.Response(200, json={"id": "chat-1", **model_fields,
                                         "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    result = asyncio.run(adapter(spec, handler).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.resolved_model, result.requested_model_verified) == ("completed", None, False)


@every_spec
def test_a_different_answering_model_is_reported_for_the_flow_to_reject(spec, monkeypatch):
    set_key(spec, monkeypatch)
    result = asyncio.run(adapter(spec, lambda r: ok_response("another-model")).run_step("b", "d", "m", {}, "model-a"))
    assert (result.status, result.resolved_model) == ("completed", "another-model")  # flow.py records model_mismatch


TOOL_CALL = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]


@every_spec
@pytest.mark.parametrize("message_extra,finish,expected", [
    ({"tool_calls": TOOL_CALL}, "stop", ["function"]),          # a tool call next to usable content, finish "stop"
    ({"tool_calls": TOOL_CALL}, "tool_calls", ["function"]),
    ({"function_call": {"name": "read_file", "arguments": "{}"}}, "stop", ["function_call"]),
    ({}, "tool_calls", ["tool_calls"]),
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


def test_cancel_is_a_no_op_and_close_only_closes_an_owned_client():
    a = openai_compat.OpenAICompatAdapter(openai_compat.KIMI)
    assert asyncio.run(a.cancel()) is False
    asyncio.run(a.close())
    shared = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    b = openai_compat.OpenAICompatAdapter(openai_compat.KIMI, client=shared)
    asyncio.run(b.close())
    assert shared.is_closed is False
    asyncio.run(shared.aclose())


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


def test_openrouter_keeps_only_models_that_take_structured_outputs_sorted_with_their_names(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    listed = {"data": [{"id": "z/model", "name": "Z: Model", **SO}, {"id": "a/plain", "name": "A: Plain", "supported_parameters": ["tools"]},
                       {"id": "a/model", "name": "A: Model", **SO}, {"id": "b/none"}]}
    status = asyncio.run(adapter(openai_compat.OPENROUTER, lambda r: httpx.Response(200, json=listed)).health(refresh=True))
    assert [(m["id"], m["display_name"]) for m in status["models"]] == [("a/model", "A: Model"), ("z/model", "Z: Model")]


def test_mimo_without_a_model_list_offers_its_documented_models(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    status = asyncio.run(adapter(openai_compat.MIMO, lambda r: httpx.Response(404)).health(refresh=True))
    assert status["ready"] is True and [m["id"] for m in status["models"]] == ["mimo-v2.6-pro", "mimo-v2.6-flash"]


@pytest.mark.parametrize("value,expected", [
    ("http://127.0.0.1:8080/v1/", "http://127.0.0.1:8080/v1"), ("http://localhost:1337/v1", "http://localhost:1337/v1"),
    ("http://[::1]:8000/v1", "http://[::1]:8000/v1"), ("  ", None), (None, None)])
def test_the_local_server_address_must_be_on_this_computer(value, expected):
    assert openai_compat.loopback_url(value) == expected


@pytest.mark.parametrize("value", ["http://192.168.1.5:8080/v1", "https://api.example.com/v1", "http://127.0.0.1.example.com/v1",
                                   "http://user:pw@127.0.0.1:8080", "file:///etc/passwd", "http://127.0.0.1:99999",
                                   "http://localhost:8080/v1?x=1", "127.0.0.1:8080"])
def test_a_remote_or_malformed_local_server_address_is_refused(value):
    with pytest.raises(ValueError):
        openai_compat.loopback_url(value)


def local(handler, address):
    return openai_compat.OpenAICompatAdapter(openai_compat.LOCAL_SERVER, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                                             base_url=lambda: address)


def test_the_local_server_uses_the_address_set_in_settings_and_no_key():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        assert "authorization" not in request.headers
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "llama-3"}]})
        return ok_response("llama-3")

    status = asyncio.run(local(handler, "http://127.0.0.1:8080/v1").health(refresh=True))
    assert status["ready"] is True and status["base_url"] == "http://127.0.0.1:8080/v1" and "key_configured" not in status
    result = asyncio.run(local(handler, "http://127.0.0.1:8080/v1").run_step("b", "d", "m", {}, "llama-3"))
    assert result.status == "completed" and seen == ["http://127.0.0.1:8080/v1/models", "http://127.0.0.1:8080/v1/chat/completions"]


@pytest.mark.parametrize("address", [None, "http://10.0.0.2:8080/v1"])
def test_the_local_server_without_a_loopback_address_sends_nothing(address):
    def handler(request):
        raise AssertionError("no request expected")

    status = asyncio.run(local(handler, address).health(refresh=True))
    assert (status["ready"], status["reason_code"], status["base_url"]) == (False, "needs_setup", None)
    result = asyncio.run(local(handler, address).run_step("b", "d", "m", {}, "llama-3"))
    assert (result.status, result.delivery_class) == ("unavailable", "before_send")


def test_a_stopped_local_server_is_named_by_its_address():
    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    status = asyncio.run(local(refused, "http://localhost:1337/v1").health(refresh=True))
    assert status["reason"] == "Local server is not running at http://localhost:1337/v1" and "ollama" not in status["reason"]

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
        "ollama": ("http://127.0.0.1:11434/v1", None),
    }
    assert openai_compat.COPILOT.list_url == "https://models.github.ai/catalog/models"
    assert openai_compat.BY_KEY_ENV["MODEL_API_KEY"].base_url == "https://api.meta.ai/v1"


@every_spec
def test_identity_and_schema_enforcement(spec):
    a = openai_compat.OpenAICompatAdapter(spec)
    assert (a.connection, a.enforces_schema) == (spec.id, False)


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
        return httpx.Response(200, json={"object": "list", "data": [{"id": mid(spec, "a")}, {"id": mid(spec, "b")}, {"object": "x"}]})

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
        return httpx.Response(200, json={"data": [{"id": mid(spec, "a")}]})

    assert asyncio.run(adapter(spec, handler).health(refresh=True))["ready"] is True and len(calls) == 2

    calls.clear()

    def always_fails(request):
        calls.append(1)
        raise httpx.ConnectTimeout("timed out", request=request)

    status = asyncio.run(adapter(spec, always_fails).health(refresh=True))
    unreachable = f"{spec.name} API unreachable: ConnectTimeout" if spec.key_env else f"{spec.name} is not running: open the Ollama app or run `ollama serve`"
    assert status["ready"] is False and status["reason"] == unreachable and len(calls) == 2


@every_spec
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


def test_cancel_is_a_no_op_and_close_only_closes_an_owned_client():
    a = openai_compat.OpenAICompatAdapter(openai_compat.KIMI)
    assert asyncio.run(a.cancel()) is False
    asyncio.run(a.close())
    shared = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    b = openai_compat.OpenAICompatAdapter(openai_compat.KIMI, client=shared)
    asyncio.run(b.close())
    assert shared.is_closed is False
    asyncio.run(shared.aclose())

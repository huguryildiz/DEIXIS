"""Key input and the third key state (E2, E3, E6, E11, E12): which characters a key may hold, a broken keychain item at
startup, and "saved, not verified" for a key no request has accepted yet.

The keychain is the in-memory backend (conftest) and every API is a mocked httpx transport. These show the application's
handling, not that a real keychain or provider behaves the same.
"""

import asyncio
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import credentials, key_verification
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import mathpix
from deixis.models import openai_compat
from deixis.models.adapter import ModelStepResult
from fakes import FakeAdapter
from test_api_flow import app_for, create, session, wait_run

GLM_LIST = openai_compat.GLM.list_url
GLM_CHAT = f"{openai_compat.GLM.base_url}/chat/completions"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
BAD_KEYS = {"nul": "abcd\x00efgh1234", "zero-width": "abcd​efgh1234", "bom": "abcd﻿fgh12345", "s-cedilla": "abcdşefgh1234",
            "emoji": "abcd\U0001F600efgh12", "too-long": "a" * 401, "space": "abcd efgh1234", "newline": "abcdefgh12\n34",
            "tab": "abcdefgh12\t34"}


class Wire:
    """A mutable stand-in for the network: `answer` is called with each request and returns a response or raises."""

    def __init__(self):
        self.answer = lambda request: httpx.Response(200, json={"models": [], "data": []})
        self.urls: list[str] = []

    def __call__(self, request):
        self.urls.append(str(request.url))
        return self.answer(request)


@pytest.fixture
def wire():
    return Wire()


@pytest.fixture
def client(tmp_path, wire):
    adapters = {"fake": FakeAdapter(), "glm": openai_compat.OpenAICompatAdapter(
        openai_compat.GLM, client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))}
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters=adapters,
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(wire)), start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        yield c


def fragment(value: str) -> str:
    return "".join(c for c in value if c.isalnum())[:8]


@pytest.mark.parametrize("env", ["GEMINI_API_KEY", "S2_API_KEY", "ZOTERO_API_KEY"])
@pytest.mark.parametrize("name", BAD_KEYS)
def test_a_key_with_a_control_invisible_or_non_ascii_character_is_refused_before_anything_is_stored(
        client, memory_keychain, wire, monkeypatch, env, name):
    monkeypatch.delenv(env, raising=False)
    value = BAD_KEYS[name]
    response = client.put(f"/api/credentials/{env}", json={"value": value})
    assert response.status_code == 422
    assert not wire.urls and memory_keychain.items == {} and not os.environ.get(env)  # nothing sent, stored or exported
    assert value not in response.text and value.strip() not in response.text and "input" not in response.text  # E3: nothing echoed
    assert credentials.status(env)["configured"] is False


def test_the_mathpix_pair_takes_only_printable_ascii_and_never_echoes_it(client, memory_keychain, wire):
    for field, value in (("app_id", "my​app"), ("app_key", "key-\U0001F600-12345"), ("app_key", "key\x00-1234567"), ("app_id", "ş_app")):
        body = {"app_id": "my_app", "app_key": "good-key-12345"} | {field: value}
        response = client.put("/api/credentials/mathpix", json=body)
        assert response.status_code == 422 and value not in response.text and "input" not in response.text
    assert not wire.urls and memory_keychain.items == {}


def test_a_printable_ascii_key_of_the_longest_length_is_accepted(client, memory_keychain, wire):
    key = "".join(chr(33 + i % 94) for i in range(400))
    assert client.put("/api/credentials/ZOTERO_API_KEY", json={"value": key}).status_code == 200
    assert memory_keychain.items == {("DEIXIS", "ZOTERO_API_KEY"): key}


def test_a_broken_keychain_item_is_skipped_at_startup_and_flagged(client, memory_keychain, monkeypatch):
    for env in ("SCOPUS_API_KEY", "IEEE_API_KEY", "CORE_API_KEY", "NCBI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    memory_keychain.set_password("DEIXIS", "SCOPUS_API_KEY", "bad\x00key-12345")
    memory_keychain.set_password("DEIXIS", "IEEE_API_KEY", "ieee-from-keychain")
    memory_keychain.set_password("DEIXIS", "CORE_API_KEY", "cör-key-123456")
    real_get = memory_keychain.get_password

    def unreadable(service, username):
        if username == "NCBI_API_KEY":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return real_get(service, username)

    monkeypatch.setattr(memory_keychain, "get_password", unreadable)
    credentials.load_into_environment()  # the app starts: nothing raises
    assert os.environ["IEEE_API_KEY"] == "ieee-from-keychain"
    for env in ("SCOPUS_API_KEY", "CORE_API_KEY", "NCBI_API_KEY"):
        assert not os.environ.get(env)  # never assigned into the environment
    keys = {k["env"]: k for k in client.get("/api/credentials").json()["keys"]}
    assert all(keys[e]["broken"] and not keys[e]["configured"] for e in ("SCOPUS_API_KEY", "CORE_API_KEY", "NCBI_API_KEY"))
    assert not keys["IEEE_API_KEY"]["broken"] and keys["IEEE_API_KEY"]["configured"]
    assert "bad" not in client.get("/api/credentials").text.replace("broken", "")  # the value is not returned
    # Entering it again repairs it.
    fixed = client.put("/api/credentials/SCOPUS_API_KEY", json={"value": "scopus-source-good-1"}).json()
    assert fixed["key"]["configured"] and not fixed["key"]["broken"]


def test_a_broken_mathpix_item_is_skipped_and_shown_as_unreadable(client, memory_keychain, monkeypatch):
    monkeypatch.delenv(mathpix.ENV, raising=False)
    memory_keychain.set_password("DEIXIS", mathpix.ENV, json.dumps({"app_id": "ş_app", "app_key": "key-12345678", "revision": "r"}))
    credentials.load_into_environment()
    assert not os.environ.get(mathpix.ENV)
    pair = client.get("/api/mathpix").json()["pair"]
    assert pair["configured"] is False and pair["unreadable"] is True


def test_a_key_the_header_cannot_carry_never_raises(wire):
    asyncio.run(_header_case(wire))


async def _header_case(wire):
    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as http:
        result = await credentials.test(http, "GEMINI_API_KEY", "ş-key-12345678")  # as if it came from the shell
        assert result["status"] == "rejected" and result["verification"] == "rejected" and not wire.urls
        sent = await mathpix.test_pair(http, "ş_app", "key-12345678")
        assert sent["status"] in ("failed", "rejected")
        outcome = await mathpix.send(http, mathpix.Pair("ş_app", "key-12345678", "r"), "data:image/png;base64,AAAA")
        assert (outcome.status, outcome.reason) == ("error", "keys_rejected") and outcome.sent is False


MATRIX = [  # what the test request met -> (stored, verification, test status)
    ("offline", lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline", request=r)), True, "pending", "failed"),
    ("timeout", lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), True, "pending", "failed"),
    ("500", lambda r: httpx.Response(500), True, "pending", "failed"),
    ("429", lambda r: httpx.Response(429, headers={"retry-after": "60"}, json={"error": {"code": "insufficient_quota"}}), True, "pending", "no_credit"),
    ("401", lambda r: httpx.Response(401), False, "rejected", "rejected"),
    ("403", lambda r: httpx.Response(403), False, "rejected", "rejected"),
    ("400", lambda r: httpx.Response(400), False, "rejected", "rejected"),
    ("200", lambda r: httpx.Response(200, json={}), True, "verified", "ok"),
]


@pytest.mark.parametrize("env", ["GEMINI_API_KEY", "S2_API_KEY"])
@pytest.mark.parametrize("name,answer,stored,verification,test_status", MATRIX, ids=[m[0] for m in MATRIX])
def test_only_a_refusal_keeps_a_key_out_and_an_unchecked_key_is_saved_not_verified(
        client, memory_keychain, wire, monkeypatch, env, name, answer, stored, verification, test_status):
    monkeypatch.delenv(env, raising=False)
    wire.answer = answer
    response = client.put(f"/api/credentials/{env}", json={"value": "some-key-0123456789"})
    assert ("some-key-0123456789" in str(memory_keychain.items)) is stored
    if not stored:
        assert response.status_code == 422 and "some-key" not in response.text and not os.environ.get(env)
        return
    body = response.json()
    assert (body["test"]["status"], body["test"]["verification"], body["key"]["verification"]) == (test_status, verification, verification)
    assert body["key"]["configured"] is True
    if name == "429":  # the quota information is kept for the UI
        assert body["test"]["kind"] == "quota_exhausted" and body["test"]["http_status"] == 429 and body["test"]["reset_at"]


def test_a_key_of_a_static_model_provider_that_answers_404_is_not_shown_as_working_or_ready(client, memory_keychain, wire, monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    wire.answer = lambda request: httpx.Response(404)
    saved = client.put("/api/credentials/ZAI_API_KEY", json={"value": "glm-key-0123456789"}).json()
    assert saved["test"]["status"] != "ok" and "works" not in saved["test"]["detail"]
    assert (saved["test"]["status"], saved["test"]["verification"], saved["key"]["verification"]) == ("unverified", "pending", "pending")
    glm = client.get("/api/connections?refresh=true").json()["models"]["glm"]
    assert glm["ready"] is False and glm["verification"] == "pending" and glm["models"]
    assert client.post("/api/credentials/ZAI_API_KEY/test").json()["status"] == "unverified"
    wire.answer = lambda request: httpx.Response(200, json={})  # a later test that is answered settles it
    assert client.post("/api/credentials/ZAI_API_KEY/test").json()["verification"] == "verified"
    assert credentials.status("ZAI_API_KEY")["verification"] == "verified"


def adapter_on(wire):
    return openai_compat.OpenAICompatAdapter(openai_compat.GLM, client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))


def glm_answer(chat):
    return lambda request: httpx.Response(404) if str(request.url) == GLM_LIST else chat(request)


def completion(request):
    return httpx.Response(200, json={"id": "c1", "model": "glm-5.1", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})


async def run_one(adapter):
    return await adapter.run_step("BASE", "DEV", "MSG", {"type": "object"}, "glm-5.1")


def test_the_first_step_of_a_pending_connection_verifies_the_key(wire, monkeypatch):
    asyncio.run(_first_step(wire, monkeypatch))


async def _first_step(wire, monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "glm-key-0123456789")
    wire.answer = glm_answer(completion)
    adapter = adapter_on(wire)
    before = await adapter.health(refresh=True)
    assert (before["ready"], before["verification"]) == (False, "pending")
    assert (await run_one(adapter)).status == "completed"
    after = await adapter.health(refresh=True)
    assert (after["ready"], after["verification"]) == (True, "verified")
    assert credentials.status("ZAI_API_KEY")["verification"] == "verified"


@pytest.mark.parametrize("code", [401, 403])
def test_a_refused_first_step_marks_the_key_rejected(wire, monkeypatch, code):
    asyncio.run(_refused_step(wire, monkeypatch, code))


async def _refused_step(wire, monkeypatch, code):
    monkeypatch.setenv("ZAI_API_KEY", "glm-key-0123456789")
    wire.answer = glm_answer(lambda request: httpx.Response(code, json={"error": "no"}))
    adapter = adapter_on(wire)
    assert (await run_one(adapter)).status == "failed"
    after = await adapter.health(refresh=True)
    assert after["ready"] is False and after["verification"] == "rejected" and after["reason_code"] == "auth_failed"
    assert credentials.status("ZAI_API_KEY")["verification"] == "rejected"
    monkeypatch.setenv("ZAI_API_KEY", "glm-new-key-0123456")  # a new key starts over
    assert (await adapter.health(refresh=True))["verification"] == "pending"


def test_a_step_that_failed_for_another_reason_leaves_the_key_pending(wire, monkeypatch):
    asyncio.run(_other_failure(wire, monkeypatch))


async def _other_failure(wire, monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "glm-key-0123456789")
    wire.answer = glm_answer(lambda request: httpx.Response(500))
    adapter = adapter_on(wire)
    assert (await run_one(adapter)).status == "failed"
    assert (await adapter.health(refresh=True))["verification"] == "pending"


class PendingAdapter(FakeAdapter):
    """Reports a saved key no request has checked, and settles it with the answer of its first step like the real adapter."""

    def __init__(self, accepted: bool):
        super().__init__()
        self.accepted, self.state = accepted, "pending"

    async def health(self, refresh=False):
        status = {"connection": "fake", "verification": self.state, "ready": self.state == "verified",
                  "reason": None if self.state == "verified" else f"key {self.state}"}
        return status | {"models": [{"id": "fake-model", "display_name": "fake-model", "is_default": False, "reasoning_efforts": []}]}

    async def run_step(self, *args, **kwargs):
        if self.accepted:
            self.state = "verified"
            return await super().run_step(*args, **kwargs)
        self.state = "rejected"
        return ModelStepResult("failed", error="HTTP 401: API request failed", http_status=401)


def start_discovery(client):
    rid = create(client)
    run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
    return wait_run(client, rid, run["id"])[1]


def test_a_run_may_send_its_first_step_on_a_pending_connection_and_the_key_becomes_verified(tmp_path):
    adapter = PendingAdapter(accepted=True)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        run = start_discovery(client)
    assert run["pause_reason"] != "model_connection_not_ready" and adapter.calls
    assert adapter.state == "verified"


def test_a_refused_first_step_ends_the_pending_state_and_the_next_run_is_blocked(tmp_path):
    adapter = PendingAdapter(accepted=False)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        start_discovery(client)
        assert adapter.state == "rejected"
        calls = len(adapter.sent)
        run = start_discovery(client)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready") and len(adapter.sent) == calls


def test_a_connection_that_is_neither_ready_nor_pending_still_blocks_the_run(tmp_path):
    adapter = PendingAdapter(accepted=True)
    adapter.state = "rejected"
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        run = start_discovery(client)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready") and adapter.calls == []


MISTRAL = openai_compat.CONNECTIONS["mistral"]
OPENROUTER = openai_compat.CONNECTIONS["openrouter"]


def listed_and(chat, spec):
    """A provider whose model list answers 200 (and, for OpenRouter, to any key); `chat` answers the step."""
    return lambda request: (httpx.Response(200, json={"data": [{"id": "m-1", "supported_parameters": ["structured_outputs"]}]})
                            if str(request.url) == spec.list_url else chat(request))


def adapter_for(spec, wire):
    return openai_compat.OpenAICompatAdapter(spec, client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))


async def _step(adapter, model="m-1"):
    return await adapter.run_step("BASE", "DEV", "MSG", {"type": "object"}, model)


def test_a_key_the_list_checks_is_ready_until_a_step_refuses_it(wire, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key-0123456789")
    wire.answer = listed_and(lambda request: httpx.Response(401), MISTRAL)
    adapter = adapter_for(MISTRAL, wire)

    async def go():
        first = await adapter.health(refresh=True)
        assert (first["ready"], first["verification"]) == (True, "verified")
        assert (await _step(adapter)).status == "failed"
        again = await adapter.health()  # not refreshed: the cached "ready" must not outlive the refusal
        assert (again["ready"], again["verification"], again["reason_code"]) == (False, "rejected", "auth_failed")
        assert (await adapter.health(refresh=True))["ready"] is False  # the list still answers 200; the step's word stands
    asyncio.run(go())


def test_a_public_model_list_does_not_verify_the_key(wire, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key-0123456")
    wire.answer = listed_and(completion, OPENROUTER)
    adapter = adapter_for(OPENROUTER, wire)

    async def go():
        before = await adapter.health(refresh=True)
        assert (before["ready"], before["verification"]) == (False, "pending") and before["models"]
        assert (await _step(adapter)).status == "completed"
        after = await adapter.health(refresh=True)
        assert (after["ready"], after["verification"]) == (True, "verified")
    asyncio.run(go())


def test_a_refused_step_on_a_public_list_provider_ends_the_pending_state(wire, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key-0123456")
    wire.answer = listed_and(lambda request: httpx.Response(403), OPENROUTER)
    adapter = adapter_for(OPENROUTER, wire)

    async def go():
        assert (await adapter.health(refresh=True))["verification"] == "pending"
        await _step(adapter)
        after = await adapter.health(refresh=True)
        assert (after["ready"], after["verification"]) == (False, "rejected")
    asyncio.run(go())


def test_the_flow_refuses_a_connection_whose_key_a_step_refused(tmp_path, wire, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key-0123456789")
    chats: list[str] = []
    wire.answer = listed_and(lambda request: (chats.append(str(request.url)), httpx.Response(401))[1], MISTRAL)
    adapter = adapter_for(MISTRAL, wire)
    asyncio.run(_step(adapter))  # the refusal
    assert len(chats) == 1
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, requested_model="m-1")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        run = wait_run(client, rid, run["id"])[1]
    assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready") and len(chats) == 1


def test_a_keychain_that_did_not_answer_is_not_a_broken_key(client, memory_keychain, monkeypatch):
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    memory_keychain.set_password("DEIXIS", "SCOPUS_API_KEY", "scopus-source-good-1")
    real_get = memory_keychain.get_password

    def locked(service, username):
        if username == "SCOPUS_API_KEY":
            raise RuntimeError("keychain is locked")
        return real_get(service, username)

    monkeypatch.setattr(memory_keychain, "get_password", locked)
    credentials.load_into_environment()
    key = {k["env"]: k for k in client.get("/api/credentials").json()["keys"]}["SCOPUS_API_KEY"]
    assert (key["keychain_unavailable"], key["broken"], key["configured"]) == (True, False, False)
    assert not os.environ.get("SCOPUS_API_KEY") and memory_keychain.items[("DEIXIS", "SCOPUS_API_KEY")] == "scopus-source-good-1"


def test_a_unicode_key_from_the_shell_is_reported_broken_and_never_raises(wire, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-ş-key-0123456")
    adapter = adapter_for(MISTRAL, wire)

    async def go():
        health = await adapter.health(refresh=True)
        assert (health["ready"], health["broken"], health["reason_code"]) == (False, True, "auth_failed")
        sent = await _step(adapter)
        assert (sent.status, sent.delivery_class) == ("unavailable", "before_send")
    asyncio.run(go())
    assert not wire.urls  # nothing left the process
    assert credentials.status("MISTRAL_API_KEY")["broken"] is True


def test_a_list_answer_that_lands_after_a_refusal_does_not_lift_it(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key-0123456789")
    list_started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if str(request.url) == MISTRAL.list_url:
            list_started.set()
            await release.wait()  # the list is in flight while a step is refused
            return httpx.Response(200, json={"data": [{"id": "m-1"}]})
        return httpx.Response(401)

    adapter = adapter_for(MISTRAL, handler)

    async def go():
        health = asyncio.create_task(adapter.health(refresh=True))
        await list_started.wait()
        assert (await _step(adapter)).status == "failed"
        release.set()
        late = await health
        assert (late["ready"], late["verification"]) == (False, "rejected")
        assert (await adapter.health())["ready"] is False  # and nothing ready was cached
    asyncio.run(go())


def test_a_cached_answer_is_not_served_to_a_different_key(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "old-key-0123456789")
    list_started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.headers["authorization"] == "Bearer old-key-0123456789":
            list_started.set()
            await release.wait()  # the old key's list request is in flight while the key is changed
            return httpx.Response(200, json={"data": [{"id": "m-1"}]})
        return httpx.Response(401)

    adapter = adapter_for(MISTRAL, handler)

    async def go():
        old = asyncio.create_task(adapter.health(refresh=True))
        await list_started.wait()
        monkeypatch.setenv("MISTRAL_API_KEY", "new-key-0123456789")
        assert (await adapter.health())["ready"] is False
        release.set()
        assert (await old)["ready"] is True  # the answer was right for the key it was asked with
        assert (await adapter.health())["ready"] is False  # but it is cached for that key only
    asyncio.run(go())


def test_connections_that_share_a_key_share_its_refusal(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "meta-key-0123456789")
    glimmer_spec, spark_spec = openai_compat.MUSE_GLIMMER, openai_compat.MUSE_SPARK

    def handler(request):
        if str(request.url) == glimmer_spec.list_url:
            return httpx.Response(200, json={"data": [{"id": "muse-glimmer-1"}, {"id": "muse-spark-1"}]})
        return httpx.Response(401)

    glimmer, spark = adapter_for(glimmer_spec, handler), adapter_for(spark_spec, handler)

    async def go():
        assert (await glimmer.health(refresh=True))["ready"] and (await spark.health(refresh=True))["ready"]
        assert (await adapter_step(glimmer, "muse-glimmer-1")).status == "failed"
        after = await spark.health()  # cached as ready before the refusal
        assert (after["ready"], after["verification"]) == (False, "rejected")
    asyncio.run(go())


async def adapter_step(adapter, model):
    return await adapter.run_step("BASE", "DEV", "MSG", {"type": "object"}, model)


def test_a_source_card_says_when_its_saved_key_is_broken(client, monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "s2-ş-key-0123456")
    providers = {p["id"]: p for p in client.get("/api/connections").json()["providers"]}
    assert providers["semantic_scholar"]["key_broken"] is True and "broken" in providers["semantic_scholar"]["note"]
    assert providers["semantic_scholar"]["access_mode"] != "api_key"  # run without the key
    monkeypatch.setenv("S2_API_KEY", "s2-key-0123456789")
    assert {p["id"]: p for p in client.get("/api/connections").json()["providers"]}["semantic_scholar"]["key_broken"] is False


def test_a_source_card_also_says_so_for_a_keychain_item_skipped_at_startup(client, memory_keychain, monkeypatch):
    monkeypatch.delenv("S2_API_KEY", raising=False)
    memory_keychain.set_password("DEIXIS", "S2_API_KEY", "s2-ş-key-0123456")
    credentials.load_into_environment()
    assert not os.environ.get("S2_API_KEY")  # skipped, so the variable holds nothing
    card = {p["id"]: p for p in client.get("/api/connections").json()["providers"]}["semantic_scholar"]
    assert card["key_broken"] is True and "broken" in card["note"]


BAD_SHELL_KEY = "key-ş-0123456789"  # as if it came from the shell or .env
API_ADAPTERS = {  # (adapter class, key variable, service name in the message)
    "anthropic": ("deixis.models.anthropic_api.AnthropicAdapter", "ANTHROPIC_API_KEY", "Anthropic"),
    "openai": ("deixis.models.openai_api.OpenAIAdapter", "OPENAI_API_KEY", "OpenAI"),
    "gemini": ("deixis.models.gemini.GeminiAdapter", "GEMINI_API_KEY", "Gemini"),
    "deepseek": ("deixis.models.deepseek.DeepSeekAdapter", "DEEPSEEK_API_KEY", "DeepSeek"),
}


@pytest.mark.parametrize("name", API_ADAPTERS)
def test_every_api_adapter_reports_a_key_no_header_can_carry_as_broken_and_sends_nothing(wire, monkeypatch, name):
    import importlib
    path, env, service = API_ADAPTERS[name]
    module, cls = path.rsplit(".", 1)
    adapter = getattr(importlib.import_module(module), cls)(client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))
    monkeypatch.setenv(env, BAD_SHELL_KEY)

    async def go():
        health = await adapter.health(refresh=True)
        assert (health["ready"], health["broken"], health["reason_code"]) == (False, True, "auth_failed")
        assert service in health["reason"] and BAD_SHELL_KEY not in health["reason"]
        sent = await adapter.run_step("BASE", "DEV", "MSG", {"type": "object"}, "some-model")
        assert (sent.status, sent.delivery_class, sent.error_kind) == ("unavailable", "before_send", "auth_failed")
    asyncio.run(go())
    assert not wire.urls and credentials.status(env)["broken"] is True


def test_a_source_key_no_header_can_carry_counts_as_no_key(monkeypatch):
    from deixis.providers.registry import CONNECTORS
    monkeypatch.setenv("S2_API_KEY", BAD_SHELL_KEY)
    assert CONNECTORS["semantic_scholar"].api_key() is None
    monkeypatch.setenv("S2_API_KEY", "s2-key-0123456789")
    assert CONNECTORS["semantic_scholar"].api_key() == "s2-key-0123456789"


def test_a_zotero_or_embedding_key_no_header_can_carry_stops_before_sending(wire, monkeypatch):
    from deixis.documents.embeddings import Embedder, EmbeddingError
    from deixis.providers import zotero
    monkeypatch.setenv("ZOTERO_API_KEY", BAD_SHELL_KEY)
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "123")
    with pytest.raises(zotero.ZoteroError):
        zotero.library("web")
    monkeypatch.setenv("GEMINI_API_KEY", BAD_SHELL_KEY)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as http:
            with pytest.raises(EmbeddingError):
                await Embedder("gemini", "m").embed(http, ["text"], "RETRIEVAL_DOCUMENT")
    asyncio.run(go())
    assert not wire.urls


def test_key_state_belongs_to_the_value():
    key_verification.set_state("first-value-123", "verified")
    assert key_verification.state_of("first-value-123") == "verified"
    assert key_verification.state_of("second-value-12") is None and key_verification.state_of(None) is None
    key_verification.set_state("first-value-123", "rejected")
    assert key_verification.settle("first-value-123", "verified") == "rejected"  # a list answer never lifts a refusal
    assert key_verification.settle("second-value-12", "verified") == "verified"

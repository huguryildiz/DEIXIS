"""Settings > Connections: keys tested, kept in the keychain and never returned; local servers on this computer only;
CLI connections; installs; the step input contract for every registered connection.

FakeAdapter, an in-memory keychain and mocked HTTP. Passing shows the routes' behaviour, not live provider answers.
"""

import copy
import dataclasses
import httpx
import json
import os
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from types import SimpleNamespace

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.contracts import check_step_input
from deixis.keys import credentials
from deixis.tools import local_tools
from deixis.tools import tool_probe
from fakes import FakeAdapter


GOOD_GEMINI = "gemini-good-key-123"


# What each source answered a made-up key on 15 Oct 2026 (SYNTHETIC replies here, real status codes).
SOURCE_REFUSALS = {"https://api.openalex.org/": 401, "https://api.semanticscholar.org/": 403, "https://eutils.ncbi.nlm.nih.gov/": 400,
                   "https://ieeexploreapi.ieee.org/": 403, "https://api.elsevier.com/": 401, "https://api.core.ac.uk/": 401,
                   "https://serpapi.com/": 401}


SOURCE_KEYS = ("OPENALEX_API_KEY", "S2_API_KEY", "NCBI_API_KEY", "IEEE_API_KEY", "SCOPUS_API_KEY", "CORE_API_KEY", "SERPAPI_API_KEY")


def remote(request):
    url = str(request.url)
    if url.startswith("https://generativelanguage.googleapis.com/"):
        if request.headers.get("x-goog-api-key") == GOOD_GEMINI:
            return httpx.Response(200, json={"models": []})
        return httpx.Response(400, json={"error": {"message": "API key not valid: gemini-bad-key-456"}})
    if url == "https://api.openai.com/v1/embeddings":
        if request.headers["authorization"] == "Bearer openai-no-credit-key":
            return httpx.Response(429, json={"error": {"message": "You have no credits remaining.", "code": "insufficient_quota"}})
        return httpx.Response(401, json={"error": {"message": "Incorrect API key provided: openai-bad-key"}})
    if url == "https://api.deepseek.com/models":
        if request.headers.get("authorization") == "Bearer deepseek-good-key":
            return httpx.Response(200, json={"object": "list", "data": []})
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})
    if url.startswith("https://api.anthropic.com/v1/models"):
        if request.headers.get("x-api-key") == "anthropic-good-key" and request.headers.get("anthropic-version") == "2023-06-01":
            return httpx.Response(200, json={"data": [], "has_more": False})
        return httpx.Response(401, json={"type": "error", "error": {"message": "invalid x-api-key anthropic-bad-key"}})
    if url == "https://openrouter.ai/api/v1/models":  # public: any key or none is answered
        return httpx.Response(200, json={"data": []})
    if url == "https://openrouter.ai/api/v1/key":
        if request.headers.get("authorization") == "Bearer openrouter-good-key":
            return httpx.Response(200, json={"data": {"label": "SYNTHETIC"}})
        return httpx.Response(401, json={"error": {"message": "No auth credentials found"}})
    if url == "https://api.xiaomimimo.com/v1/models":
        if request.headers.get("authorization") == "Bearer mimo-good-key":
            return httpx.Response(404)
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})
    compat = {"https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models": "dashscope-good-key",
              "https://api.moonshot.ai/v1/models": "moonshot-good-key", "https://api.mistral.ai/v1/models": "mistral-good-key"}
    if url in compat:
        if request.headers.get("authorization") == f"Bearer {compat[url]}":
            return httpx.Response(200, json={"object": "list", "data": [{"id": "SYNTHETIC-model"}]})
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})
    for host, refusal in SOURCE_REFUSALS.items():
        if url.startswith(host):
            sent = request.headers.get("authorization", "") + request.headers.get("x-api-key", "") + request.headers.get("x-els-apikey", "") + url
            if "source-good" in sent:
                return httpx.Response(200, json={})
            if "scopus-off-campus" in sent:
                return httpx.Response(403, json={"error-response": {"error-code": "AUTHORIZATION_ERROR"}})
            return httpx.Response(refusal, json={"error": "API key invalid"})
    if url == "http://127.0.0.1:11434/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "size": 5_200_000_000},
                                                    {"name": "nomic-embed-text:latest", "size": 274_000_000}]})
    if url == "http://127.0.0.1:11434/api/show":
        name = json.loads(request.content)["model"]
        return httpx.Response(200, json={"capabilities": ["embedding"] if "embed" in name else ["completion", "tools"]})
    raise httpx.ConnectError("connection refused", request=request)  # LM Studio is not running


@pytest.fixture
def paths(monkeypatch):
    """Binaries on PATH by name. App bundles and the machine are faked, so the host computer does not leak in."""
    found = {}
    monkeypatch.setattr(local_tools, "find_tool", lambda name: found.get(name))
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [found[name]] if name in found else [])
    monkeypatch.setattr(local_tools, "TOOLS", {k: dataclasses.replace(t, app=None) for k, t in local_tools.TOOLS.items()})
    monkeypatch.setattr(local_tools, "machine", lambda: {"chip": "SYNTHETIC chip", "memory_gb": 32, "disk_free_gb": 100, "disk_total_gb": 500})
    monkeypatch.setattr(local_tools, "OLLAMA_MAC", False)  # the macOS app installs have their own tests
    monkeypatch.setattr(local_tools, "LMSTUDIO_MAC", False)
    return found


@pytest.fixture
def client(tmp_path, paths):
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        yield c


def test_a_model_key_is_tested_stored_in_the_keychain_and_never_returned(client, memory_keychain):
    bad = client.put("/api/credentials/GEMINI_API_KEY", json={"value": "gemini-bad-key-456"})
    assert bad.status_code == 422 and "did not accept" in bad.json()["detail"] and "gemini-bad-key" not in bad.text
    assert memory_keychain.items == {} and not os.environ.get("GEMINI_API_KEY")

    saved = client.put("/api/credentials/GEMINI_API_KEY", json={"value": GOOD_GEMINI})
    assert saved.status_code == 200 and saved.json()["test"]["status"] == "ok"
    assert saved.json()["key"] == {"env": "GEMINI_API_KEY", "group": "model", "service": "gemini", "configured": True,
                                   "source": "keychain", "testable": True, "shell_fallback": False,
                                   "last4": "-123", "verification": "verified", "broken": False, "keychain_unavailable": False,
                                   "keychain_pending": False}
    assert memory_keychain.items == {("DEIXIS", "GEMINI_API_KEY"): GOOD_GEMINI} and os.environ["GEMINI_API_KEY"] == GOOD_GEMINI
    listed = client.get("/api/credentials")
    assert GOOD_GEMINI not in listed.text and listed.json()["keychain"]["available"] is True
    assert client.post("/api/credentials/GEMINI_API_KEY/test").json()["status"] == "ok"

    removed = client.delete("/api/credentials/GEMINI_API_KEY").json()["key"]
    assert (removed["configured"], removed["source"]) == (False, None) and memory_keychain.items == {}
    assert not os.environ.get("GEMINI_API_KEY")


def test_a_key_without_credit_is_kept_and_a_refused_key_is_not(client, memory_keychain):
    refused = client.put("/api/credentials/OPENAI_API_KEY", json={"value": "openai-bad-key"})
    assert refused.status_code == 422 and "openai-bad-key" not in refused.text
    kept = client.put("/api/credentials/OPENAI_API_KEY", json={"value": "openai-no-credit-key"}).json()
    assert kept["test"]["status"] == "no_credit" and kept["test"]["kind"] == "quota_exhausted" and kept["test"]["http_status"] == 429
    assert memory_keychain.items == {("DEIXIS", "OPENAI_API_KEY"): "openai-no-credit-key"}


@pytest.mark.parametrize("env,service,good", [("ANTHROPIC_API_KEY", "anthropic", "anthropic-good-key"),
                                               ("MIMO_API_KEY", "mimo", "mimo-good-key")])
def test_d34_keys_are_tested_before_they_are_kept(client, memory_keychain, env, service, good):
    """OpenRouter answers its model list to any key, so its key is checked on /key; MiMo has no model list (404)."""
    refused = client.put(f"/api/credentials/{env}", json={"value": "anthropic-bad-key"})
    assert refused.status_code == 422 and "anthropic-bad-key" not in refused.text and memory_keychain.items == {}
    saved = client.put(f"/api/credentials/{env}", json={"value": good}).json()
    # MiMo's 404 is not an answer about the key: saved, shown as not verified, never as "The key works." (E6)
    expected = ("unverified", "pending") if env == "MIMO_API_KEY" else ("ok", "verified")
    assert (saved["test"]["status"], saved["test"]["verification"], saved["key"]["verification"]) == (*expected, expected[1])
    assert saved["key"]["service"] == service and saved["key"]["group"] == "model"
    assert memory_keychain.items == {("DEIXIS", env): good}


def test_local_connections_do_not_share_the_proxy_honouring_client(tmp_path, paths, monkeypatch):
    """Review of af41a88 (P1): in the running app (no injected client) Ollama and the local server get their own
    client, which ignores HTTP_PROXY; remote APIs keep the shared one."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    app = create_app(Settings(data_dir=tmp_path / "proxy", port=8765), start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app):
        adapters, shared = app.state.adapters, app.state.http
        assert adapters["deepseek"]._client is shared and adapters["kimi"]._client is shared and adapters["anthropic"]._client is shared
        for name in ("ollama", "local_server"):
            own = adapters[name]._http()
            assert own is not shared and own.trust_env is False and own.follow_redirects is False and not own._mounts
        # D34 follow-up: Ollama/LM Studio embeddings, the local tool checks and Zotero's local API share one loopback client.
        local = app.state.local_http
        assert local is not shared and local.trust_env is False and local.follow_redirects is False and not local._mounts
        assert app.state.local_tools._client is local and app.state.worker.flow.deps.local_http is local
        from deixis.documents import embeddings
        assert embeddings.client_for("ollama", app.state.worker.flow.deps) is local
        assert embeddings.client_for("gemini", app.state.worker.flow.deps) is shared
        from deixis.api.app import zotero_http
        request = SimpleNamespace(app=app)
        assert zotero_http(request, "local") is local and zotero_http(request, "web") is shared


def test_claude_code_runs_on_the_account_not_on_a_saved_api_key(tmp_path, monkeypatch):
    """D34: the CLI inherits the app's environment; the key saved for the Anthropic API connection is emptied for it."""
    from deixis.models.claude import ClaudeCodeAdapter
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SYNTHETIC-api-key")
    options = ClaudeCodeAdapter(workspace=tmp_path / "claude")._options("claude")
    assert options.env["ANTHROPIC_API_KEY"] == ""


def test_a_saved_key_replaces_the_shell_key_until_removed(client, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "openalex-from-env")
    entry = next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == "OPENALEX_API_KEY")
    assert (entry["configured"], entry["source"], entry["testable"]) == (True, "environment", True)
    assert client.delete("/api/credentials/OPENALEX_API_KEY").status_code == 409  # the shell key itself is never removed
    saved = client.put("/api/credentials/OPENALEX_API_KEY", json={"value": "openalex-source-good-key"}).json()["key"]
    assert (saved["source"], saved["shell_fallback"]) == ("keychain", True) and os.environ["OPENALEX_API_KEY"] == "openalex-source-good-key"
    removed = client.delete("/api/credentials/OPENALEX_API_KEY").json()["key"]
    assert (removed["source"], removed["shell_fallback"]) == ("environment", False) and os.environ["OPENALEX_API_KEY"] == "openalex-from-env"

    assert client.put("/api/credentials/PATH", json={"value": "/SYNTHETIC/bin"}).status_code == 404
    assert client.put("/api/credentials/GEMINI_API_KEY", json={"value": "has space inside"}).status_code == 422


def versions(answer):
    """A stand-in for the version probe: `answer(argv)` is the printed version, or None for a tool that fails."""
    async def probe(argv, timeout=None, env=None):
        line = answer(argv)
        return tool_probe.Probe(0, line) if line else tool_probe.Probe(1)
    return probe


def test_zotero_reports_whether_its_local_api_is_on(client, monkeypatch):
    replies = {"status": None}

    async def fake_get(url, params=None, timeout=None):
        if replies["status"] is None or ":23119/" not in url:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(replies["status"], json=[])

    tools = client.app.state.local_tools
    monkeypatch.setattr(tools._client, "get", fake_get)
    monkeypatch.setenv("ZOTERO_API_KEY", "SYNTHETIC")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "1")
    zotero = lambda: next(t for t in client.get("/api/local-tools?refresh=true").json()["tools"] if t["id"] == "zotero")
    assert (zotero()["installed"], zotero()["running"], zotero()["web_configured"]) == (False, False, True)
    replies["status"] = 403
    assert (zotero()["installed"], zotero()["running"], zotero()["local_api"]) == (True, True, False)
    replies["status"] = 200
    assert zotero()["local_api"] is True


@pytest.mark.parametrize("env", SOURCE_KEYS[:1])
def test_a_source_key_is_tested_with_one_request_and_a_refused_one_is_not_saved(client, memory_keychain, monkeypatch, env):
    monkeypatch.setenv(env, "")
    refused = client.put(f"/api/credentials/{env}", json={"value": "made-up-key-123"})
    assert refused.status_code == 422 and "did not accept" in refused.json()["detail"] and memory_keychain.items == {}
    saved = client.put(f"/api/credentials/{env}", json={"value": "source-good-key-123"}).json()
    assert saved["test"]["status"] == "ok" and saved["key"]["testable"] is True
    assert client.post(f"/api/credentials/{env}/test").json()["status"] == "ok"


ROOT = Path(__file__).resolve().parents[2]


SCHEMA = json.loads((ROOT / "deixis/contracts/research/step-input.schema.json").read_text())


STEP_INPUTS = json.loads((ROOT / "tests/fixtures/research/step-inputs.json").read_text())


def registered_connections(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), start_worker=False,
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app):
        return set(app.state.adapters)


def test_a_step_input_for_every_registered_connection_passes_the_contract(tmp_path, paths):
    for connection in sorted(registered_connections(tmp_path)):
        step_input = copy.deepcopy(STEP_INPUTS["A_answer"])
        step_input["model"] = {"connection": connection, "requested_model": "SYNTHETIC-model"}
        assert check_step_input(step_input) == [], connection



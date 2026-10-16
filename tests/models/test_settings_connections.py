"""Settings › Connections (D29): API keys in the keychain, local tools and the semantic search provider.

The keychain is an in-memory backend (conftest), the APIs and local model servers are mocked, and installs run a stub
script. These show the application's handling, not that a real keychain, package manager or model server behaves the same.
"""

import asyncio
import dataclasses
import json
import os
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.keys import credentials
from deixis.tools import local_tools, tool_probe
from deixis.api.app import create_app
from deixis.config import Settings
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


def test_deepseek_key_is_verified_by_listing_models(client, memory_keychain):
    refused = client.put("/api/credentials/DEEPSEEK_API_KEY", json={"value": "deepseek-bad-key"})
    assert refused.status_code == 422 and "deepseek-bad-key" not in refused.text
    saved = client.put("/api/credentials/DEEPSEEK_API_KEY", json={"value": "deepseek-good-key"}).json()
    assert saved["test"]["status"] == "ok" and saved["key"]["service"] == "deepseek"
    assert memory_keychain.items == {("DEIXIS", "DEEPSEEK_API_KEY"): "deepseek-good-key"}


@pytest.mark.parametrize("env,service,good", [("DASHSCOPE_API_KEY", "qwen", "dashscope-good-key"),
                                               ("MOONSHOT_API_KEY", "kimi", "moonshot-good-key"),
                                               ("MISTRAL_API_KEY", "mistral", "mistral-good-key")])
def test_openai_compatible_keys_are_verified_by_listing_models(client, memory_keychain, env, service, good):
    refused = client.put(f"/api/credentials/{env}", json={"value": "some-bad-key-1"})
    assert refused.status_code == 422 and "some-bad-key-1" not in refused.text
    saved = client.put(f"/api/credentials/{env}", json={"value": good}).json()
    assert saved["test"]["status"] == "ok" and saved["key"]["service"] == service and saved["key"]["testable"] is True
    assert memory_keychain.items == {("DEIXIS", env): good}


def test_openai_compatible_connections_are_registered_and_report_a_missing_key(tmp_path, paths):
    app = create_app(Settings(data_dir=tmp_path / "data2", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        models = c.get("/api/connections").json()["models"]
        for name, env in (("qwen", "DASHSCOPE_API_KEY"), ("kimi", "MOONSHOT_API_KEY"), ("mistral", "MISTRAL_API_KEY"),
                          ("grok", "XAI_API_KEY"), ("glm", "ZAI_API_KEY"),
                          ("muse_spark", "MODEL_API_KEY"), ("muse_glimmer", "MODEL_API_KEY")):
            assert (models[name]["ready"], models[name]["key_configured"]) == (False, False)
            assert "API key in Settings" in models[name]["reason"] and env not in models[name]["reason"] and "not implemented" not in models[name]["reason"]
        assert "key_configured" not in models["ollama"] and "not implemented" not in (models["ollama"].get("reason") or "")


@pytest.mark.parametrize("env,service,good", [("ANTHROPIC_API_KEY", "anthropic", "anthropic-good-key"),
                                               ("OPENROUTER_API_KEY", "openrouter", "openrouter-good-key"),
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


def test_d34_connections_are_registered_and_report_what_is_missing(tmp_path, paths, monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "MIMO_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "d34", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        models = c.get("/api/connections").json()["models"]
        for name in ("anthropic", "openai", "openrouter", "mimo"):
            assert (models[name]["ready"], models[name]["key_configured"], models[name]["reason_code"]) == (False, False, "needs_key")
        assert models["local_server"]["reason_code"] == "needs_setup" and models["local_server"]["base_url"] is None
        assert "key_configured" not in models["local_server"]


def test_the_local_server_address_is_saved_only_on_this_computer(tmp_path, paths):
    def handler(request):
        if str(request.url) == "http://127.0.0.1:8080/v1/models":
            return httpx.Response(200, json={"data": [{"id": "SYNTHETIC-llama"}]})
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "local", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        refused = c.put("/api/connections/local_server", json={"base_url": "http://192.168.1.20:8080/v1"})
        assert refused.status_code == 422 and "this computer" in refused.json()["detail"]
        assert c.get("/api/connections/local_server").json()["base_url"] is None
        saved = c.put("/api/connections/local_server", json={"base_url": "http://127.0.0.1:8080/v1/"}).json()
        assert saved["ready"] is True and saved["base_url"] == "http://127.0.0.1:8080/v1"
        assert [m["id"] for m in saved["models"]] == ["SYNTHETIC-llama"]
        assert c.get("/api/connections").json()["models"]["local_server"]["base_url"] == "http://127.0.0.1:8080/v1"
        cleared = c.put("/api/connections/local_server", json={"base_url": ""}).json()
        assert (cleared["ready"], cleared["base_url"]) == (False, None)


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


def test_connections_name_the_codex_home_this_backend_uses(tmp_path, monkeypatch):
    """S24 (Sol r1): the Settings sign-in command is built from the active Codex home, not a hard-coded macOS path."""
    monkeypatch.delenv("DEIXIS_CODEX_HOME", raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data3", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        assert c.get("/api/connections").json()["codex_home"] == str(tmp_path / "data3" / "codex-home")
    monkeypatch.setenv("DEIXIS_CODEX_HOME", str(tmp_path / "SYNTHETIC codex home"))
    with TestClient(app) as c:
        assert c.get("/api/connections").json()["codex_home"] == str(tmp_path / "SYNTHETIC codex home")


def test_one_model_connection_can_be_freshly_queried(client):
    response = client.get("/api/connections/fake?refresh=true")
    assert response.status_code == 200 and response.json()["connection"] == "fake"
    assert client.get("/api/connections/not-present?refresh=true").status_code == 404


def test_a_key_from_dotenv_is_replaced_and_removed_in_that_file(client, monkeypatch, tmp_path, memory_keychain):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# SYNTHETIC\nOPENALEX_API_KEY=openalex-old-key\nS2_API_KEY='s2-old-key'\n\n# end")
    dotenv.chmod(0o600)
    for name in ("OPENALEX_API_KEY", "S2_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    from deixis.config import load_dotenv
    credentials.mark_dotenv(load_dotenv(dotenv), dotenv)
    entry = next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == "OPENALEX_API_KEY")
    assert (entry["configured"], entry["source"]) == (True, "dotenv")

    saved = client.put("/api/credentials/OPENALEX_API_KEY", json={"value": "openalex-source-good-new"})
    assert saved.status_code == 200 and saved.json()["key"]["source"] == "dotenv" and "openalex-source-good-new" not in saved.text
    assert os.environ["OPENALEX_API_KEY"] == "openalex-source-good-new"
    assert memory_keychain.get_password("DEIXIS", "OPENALEX_API_KEY") is None
    assert client.delete("/api/credentials/S2_API_KEY").json()["key"]["configured"] is False
    assert dotenv.read_text() == "# SYNTHETIC\nOPENALEX_API_KEY=openalex-source-good-new\n\n# end"
    assert dotenv.stat().st_mode & 0o777 == 0o600
    # A key added after removal goes to the keychain, as for any key that is not in .env.
    assert client.put("/api/credentials/S2_API_KEY", json={"value": "s2-source-good-fresh"}).json()["key"]["source"] == "keychain"


def test_keys_from_dotenv_move_into_the_keychain_at_startup(monkeypatch, tmp_path, memory_keychain):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# SYNTHETIC\nOPENALEX_API_KEY=openalex-dotenv-key\nDEIXIS_PORT=8765\nS2_API_KEY='s2-dotenv-key'\n"
                      "ZOTERO_API_KEY=zotero-dotenv-key\nZOTERO_LIBRARY_ID=123\n")
    dotenv.chmod(0o600)
    for name in ("OPENALEX_API_KEY", "S2_API_KEY", "DEIXIS_PORT", "ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID"):
        monkeypatch.setenv(name, "unset")  # recorded, so the value .env sets is removed afterwards
        monkeypatch.delenv(name)
    from deixis.config import load_dotenv
    credentials.mark_dotenv(load_dotenv(dotenv), dotenv)
    credentials.move_dotenv_keys_to_keychain()
    assert dotenv.read_text() == "# SYNTHETIC\nDEIXIS_PORT=8765\n"  # lines DEIXIS does not manage stay
    assert memory_keychain.get_password("DEIXIS", "ZOTERO_API_KEY") == "zotero-dotenv-key"
    assert memory_keychain.get_password("DEIXIS", "ZOTERO_LIBRARY_ID") == "123"
    assert dotenv.stat().st_mode & 0o777 == 0o600
    assert memory_keychain.get_password("DEIXIS", "OPENALEX_API_KEY") == "openalex-dotenv-key"
    assert memory_keychain.get_password("DEIXIS", "S2_API_KEY") == "s2-dotenv-key"
    assert os.environ["OPENALEX_API_KEY"] == "openalex-dotenv-key"
    assert credentials.status("OPENALEX_API_KEY")["source"] == "keychain"


def test_a_key_stays_in_dotenv_when_the_keychain_does_not_keep_it(monkeypatch, tmp_path, memory_keychain):
    from keyring.errors import PasswordSetError
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENALEX_API_KEY=openalex-dotenv-key\nS2_API_KEY=s2-dotenv-key\n")
    for name in ("OPENALEX_API_KEY", "S2_API_KEY"):
        monkeypatch.setenv(name, "unset")  # recorded, so the value .env sets is removed afterwards
        monkeypatch.delenv(name)
    from deixis.config import load_dotenv
    credentials.mark_dotenv(load_dotenv(dotenv), dotenv)
    real_set = memory_keychain.set_password

    def refuse_openalex(service, username, password):
        if username == "OPENALEX_API_KEY":
            raise PasswordSetError("SYNTHETIC refusal")
        real_set(service, username, password)

    monkeypatch.setattr(memory_keychain, "set_password", refuse_openalex)
    credentials.move_dotenv_keys_to_keychain()
    assert dotenv.read_text() == "OPENALEX_API_KEY=openalex-dotenv-key\n"
    assert (credentials.status("OPENALEX_API_KEY")["source"], credentials.status("S2_API_KEY")["source"]) == ("dotenv", "keychain")


def test_keys_stay_in_dotenv_without_a_keychain(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENALEX_API_KEY=openalex-dotenv-key\n")
    monkeypatch.setenv("OPENALEX_API_KEY", "unset")
    monkeypatch.delenv("OPENALEX_API_KEY")
    monkeypatch.setattr(credentials, "keychain_name", lambda: None)
    from deixis.config import load_dotenv
    credentials.mark_dotenv(load_dotenv(dotenv), dotenv)
    credentials.move_dotenv_keys_to_keychain()
    assert dotenv.read_text() == "OPENALEX_API_KEY=openalex-dotenv-key\n"
    assert credentials.status("OPENALEX_API_KEY")["source"] == "dotenv"


def test_the_zotero_org_pair_is_saved_from_settings(client, memory_keychain):
    for name in ("ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID"):
        assert next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == name)["service"] == "zotero"
    assert client.put("/api/credentials/ZOTERO_LIBRARY_ID", json={"value": "group-1"}).status_code == 422
    assert client.put("/api/credentials/ZOTERO_API_KEY", json={"value": "short"}).status_code == 422
    saved = client.put("/api/credentials/ZOTERO_LIBRARY_ID", json={"value": "1234567"})  # SYNTHETIC; real IDs can be 7 digits
    assert saved.status_code == 200 and saved.json()["key"]["source"] == "keychain"
    assert client.put("/api/credentials/ZOTERO_API_KEY", json={"value": "zotero-synthetic-key"}).status_code == 200
    assert memory_keychain.get_password("DEIXIS", "ZOTERO_LIBRARY_ID") == "1234567"
    tool = next(t for t in client.get("/api/local-tools").json()["tools"] if t["id"] == "zotero")
    assert tool["web_configured"] is True


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


def test_saved_keys_are_loaded_at_startup_over_the_shell_key(monkeypatch, memory_keychain):
    monkeypatch.setenv("SCOPUS_API_KEY", "")
    monkeypatch.setenv("IEEE_API_KEY", "ieee-from-env")
    memory_keychain.set_password("DEIXIS", "SCOPUS_API_KEY", "scopus-from-keychain")
    memory_keychain.set_password("DEIXIS", "IEEE_API_KEY", "ieee-from-keychain")
    credentials.load_into_environment()
    assert os.environ["SCOPUS_API_KEY"] == "scopus-from-keychain" and credentials.status("SCOPUS_API_KEY")["source"] == "keychain"
    assert os.environ["IEEE_API_KEY"] == "ieee-from-keychain" and credentials.status("IEEE_API_KEY")["shell_fallback"]
    credentials.delete("IEEE_API_KEY")
    assert os.environ["IEEE_API_KEY"] == "ieee-from-env" and credentials.status("IEEE_API_KEY")["source"] == "environment"


def versions(answer):
    """A stand-in for the version probe: `answer(argv)` is the printed version, or None for a tool that fails."""
    async def probe(argv, timeout=None, env=None):
        line = answer(argv)
        return tool_probe.Probe(0, line) if line else tool_probe.Probe(1)
    return probe


def test_local_tools_report_clis_running_servers_and_embedding_models(client, paths, monkeypatch):
    paths.update(claude="/SYNTHETIC/bin/claude", npm="/SYNTHETIC/bin/npm")
    monkeypatch.setattr(local_tools, "probe", versions(lambda argv: "2.1.270 (Claude Code)" if argv[0].endswith("claude") else None))
    data = client.get("/api/local-tools?refresh=true").json()
    tools = {t["id"]: t for t in data["tools"]}
    assert data["machine"]["memory_gb"] == 32
    claude = tools["claude_code"]
    assert (claude["installed"], claude["version"], claude["role"], claude["job"]) == (True, "2.1.270 (Claude Code)", "runs_steps", None)
    codex = tools["codex"]
    assert (codex["installed"], codex["role"], codex["install"]["available"]) == (False, "runs_steps", True)
    assert codex["install"]["command"] == "npm install -g @openai/codex"
    ollama = tools["ollama"]
    assert (ollama["running"], ollama["installed"]) == (True, True)  # the server answers although no binary is on PATH
    assert [(m["id"], m["embedding"]) for m in ollama["models"]] == [("qwen3:8b", False), ("nomic-embed-text:latest", True)]
    assert ollama["install"]["available"] is False and ollama["install"]["unavailable_reason"] == "manager_missing" and ollama["install"]["manager"] == "brew"
    assert (tools["lm_studio"]["installed"], tools["lm_studio"]["running"], tools["lm_studio"]["models"]) == (False, False, [])
    zotero = tools["zotero"]
    assert (zotero["kind"], zotero["role"], zotero["installed"], zotero["running"], zotero["local_api"]) == ("app", "imports", False, False, False)
    assert zotero["install"]["command"] == "brew install --cask zotero"


NEW_CLIS = {
    "qwen_code": ("qwen", "npm install -g @qwen-code/qwen-code"),
    "kimi_cli": ("kimi", "uv tool install kimi-cli"),
    "mistral_vibe": ("vibe", "uv tool install mistral-vibe"),
    "copilot_cli": ("copilot", "npm install -g @github/copilot"),
    "opencode": ("opencode", "npm install -g opencode-ai"),
    "aider": ("aider", "uv tool install aider-chat"),
    "goose": ("goose", "brew install block-goose-cli"),
    "amp": ("amp", "npm install -g @sourcegraph/amp"),
    "cline": ("cline", "npm install -g cline"),
}


def test_other_llm_clis_are_detected_only_with_a_fixed_install_command(client, paths, monkeypatch):
    paths.update(qwen="/SYNTHETIC/bin/qwen", aider="/SYNTHETIC/bin/aider", uv="/SYNTHETIC/bin/uv")
    monkeypatch.setattr(local_tools, "probe", versions(lambda argv: "9.9.9" if argv[0].endswith(("qwen", "aider")) else None))
    tools = {t["id"]: t for t in client.get("/api/local-tools?refresh=true").json()["tools"]}
    for tool_id, (binary, command) in NEW_CLIS.items():
        tool = tools[tool_id]
        role = "runs_steps" if tool_id == "copilot_cli" else "detected"  # D24
        assert (tool["kind"], tool["role"], tool["install"]["command"]) == ("cli", role, command), tool_id
        assert local_tools.TOOLS[tool_id].binary == binary
    assert (tools["qwen_code"]["installed"], tools["qwen_code"]["version"], tools["qwen_code"]["path"]) == (True, "9.9.9", "/SYNTHETIC/bin/qwen")
    assert tools["aider"]["installed"] is True and tools["kimi_cli"]["installed"] is False
    # uv is on PATH here, npm and brew are not, so only the uv-installed tools can be installed.
    assert tools["kimi_cli"]["install"]["available"] is True and tools["cline"]["install"]["available"] is False
    assert (tools["cline"]["install"]["unavailable_reason"], tools["cline"]["install"]["manager"]) == ("manager_missing", "npm")
    # Only the step-running CLIs carry that role: Claude Code, Codex and, of the new ones, Copilot CLI (D24) and Gemini CLI (D23).
    assert sorted(t["id"] for t in tools.values() if t["role"] == "runs_steps") == ["claude_code", "codex", "copilot_cli", "gemini_cli"]


def test_installing_a_detected_cli_runs_only_its_fixed_command(client, paths, tmp_path):
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\necho "SYNTHETIC uv $@"\nexit 0\n')
    uv.chmod(0o755)
    paths["uv"] = str(uv)
    started = client.post("/api/local-tools/kimi_cli/install")
    assert started.status_code == 202 and started.json()["job"]["command"] == "uv tool install kimi-cli"
    job = wait_job(client, "kimi_cli")
    assert job["status"] == "succeeded" and "SYNTHETIC uv tool install kimi-cli" in job["output"]
    paths["aider"] = "/SYNTHETIC/bin/aider"
    assert client.post("/api/local-tools/aider/install").status_code == 409  # already installed


def wait_job(client, tool_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = next(t for t in client.get("/api/local-tools").json()["tools"] if t["id"] == tool_id)["job"]
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"{tool_id} install did not finish")


def test_install_runs_only_the_fixed_command_and_reports_the_result(client, paths, tmp_path):
    npm = tmp_path / "npm"
    npm.write_text('#!/bin/sh\necho "SYNTHETIC npm $@"\n[ "$3" = "@openai/codex" ] && exit 3\nexit 0\n')
    npm.chmod(0o755)
    paths["npm"] = str(npm)
    started = client.post("/api/local-tools/claude_code/install")
    assert started.status_code == 202 and started.json()["job"]["command"] == "npm install -g @anthropic-ai/claude-code"
    job = wait_job(client, "claude_code")
    assert job["status"] == "succeeded" and "SYNTHETIC npm install -g @anthropic-ai/claude-code" in job["output"]
    assert client.post("/api/local-tools/codex/install").status_code == 202
    assert wait_job(client, "codex")["status"] == "failed"

    assert client.post("/api/local-tools/lm_studio/install").status_code == 422  # brew is not on PATH
    paths["gemini"] = "/SYNTHETIC/bin/gemini"
    assert client.post("/api/local-tools/gemini_cli/install").status_code == 409
    assert client.post("/api/local-tools/rm/install").status_code == 404


def test_a_running_install_can_be_cancelled(client, paths, tmp_path):
    npm = tmp_path / "npm"
    npm.write_text('#!/bin/sh\nsleep 5\n')
    npm.chmod(0o755)
    paths["npm"] = str(npm)
    assert client.post("/api/local-tools/claude_code/install").status_code == 202
    cancelled = client.post("/api/local-tools/claude_code/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["job"]["status"] == "cancelled"
    job = next(t for t in client.get("/api/local-tools").json()["tools"] if t["id"] == "claude_code")["job"]
    assert job["status"] == "cancelled"
    assert client.post("/api/local-tools/claude_code/cancel").status_code == 409  # already finished
    assert client.post("/api/local-tools/rm/cancel").status_code == 404


def test_semantic_search_offers_what_is_available_and_refuses_the_rest(client, monkeypatch):
    view = client.get("/api/semantic-search").json()
    options = {o["provider"]: o for o in view["options"]}
    assert (view["provider"], view["explicit"]) == ("off", False)
    assert options["gemini"]["available"] is False and options["ollama"]["models"] == ["nomic-embed-text:latest"]
    assert options["lm_studio"]["reason"] == "LM Studio is not installed"

    assert client.put("/api/semantic-search", json={"provider": "openai"}).json()["detail"] == "Add an OpenAI API key"
    assert client.put("/api/semantic-search", json={"provider": "ollama", "model": "qwen3:8b"}).status_code == 422
    assert client.put("/api/semantic-search", json={"provider": "ollama"}).status_code == 422
    chosen = client.put("/api/semantic-search", json={"provider": "ollama", "model": "nomic-embed-text:latest"}).json()
    assert (chosen["provider"], chosen["model"], chosen["explicit"]) == ("ollama", "nomic-embed-text:latest", True)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    assert client.put("/api/semantic-search", json={"provider": "gemini"}).json()["model"] == "gemini-embedding-2"
    assert client.put("/api/semantic-search", json={"provider": "off"}).json()["provider"] == "off"


def test_version_is_the_output_line_that_names_one(tmp_path):
    tool = tmp_path / "ollama"
    tool.write_text('#!/bin/sh\necho "Warning: could not connect to a running Ollama instance"\necho "Warning: client version is 0.34.0"\n')
    tool.chmod(0o755)
    assert local_tools._command_output([str(tool), "--version"]) == "client version is 0.34.0"


def test_one_broken_cli_does_not_hide_the_others_in_the_inventory(client, paths, tmp_path, monkeypatch):
    """E16/A3b: undecodable version bytes and a CLI that never answers each affect only their own card; the probes run
    side by side, so two tools that take 1.5 s each cost about 1.5 s, not 3."""
    monkeypatch.setattr(tool_probe, "PROBE_TIMEOUT", 2.0)
    for name, body in {"qwen": b"#!/bin/sh\nprintf 'qwen S\\374r\\374m 1.4.0 \\376\\375\\n'\n",
                       "aider": b"#!/bin/sh\nsleep 600\n", "amp": b"#!/bin/sh\nsleep 1.5\necho 0.9.1\n",
                       "cline": b"#!/bin/sh\nsleep 1.5\necho 2.0.0\n"}.items():
        (tmp_path / name).write_bytes(body)
        (tmp_path / name).chmod(0o755)
        paths[name] = str(tmp_path / name)
    started = time.monotonic()
    tools = {t["id"]: t for t in client.get("/api/local-tools?refresh=true").json()["tools"]}
    assert time.monotonic() - started < 2.9  # one after another the two slow tools alone take 3 s, the hung one 2 s more
    assert tools["qwen_code"]["installed"] and tools["qwen_code"]["version"] == "qwen S\ufffdr\ufffdm 1.4.0 \ufffd\ufffd"
    assert (tools["aider"]["installed"], tools["aider"]["version"], tools["aider"]["reason_code"]) == (True, None, "not_responding")
    assert (tools["amp"]["version"], tools["cline"]["version"]) == ("0.9.1", "2.0.0")
    assert tools["amp"]["reason_code"] is None and tools["qwen_code"]["reason_code"] is None


def test_the_ollama_card_downloads_only_the_fixed_embedding_model_and_reports_progress(tmp_path, paths):
    sent = []

    def handler(request):
        if str(request.url) == "http://127.0.0.1:11434/api/pull":
            sent.append(json.loads(request.content))
            lines = [{"status": "pulling manifest"},
                     {"status": "pulling 970aa74c", "digest": "sha256:970aa74c", "total": 274_000_000, "completed": 137_000_000},
                     {"status": "pulling c71d239d", "digest": "sha256:c71d239d", "total": 11_000, "completed": 11_000},
                     {"status": "pulling 970aa74c", "digest": "sha256:970aa74c", "total": 274_000_000, "completed": 274_000_000},
                     {"status": "success"}]
            return httpx.Response(200, content="\n".join(json.dumps(line) for line in lines).encode())
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "pull", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        assert c.post("/api/local-tools/ollama/pull-embedding-model", json={"model": "qwen3"}).status_code == 202
        for _ in range(50):
            ollama = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "ollama")
            if ollama["pull"]["status"] != "running":
                break
            time.sleep(0.02)
        pull = ollama["pull"]
        assert sent == [{"model": "nomic-embed-text", "stream": True}]  # the request body's model is ignored
        assert (pull["status"], pull["model"], pull["completed"], pull["total"]) == ("succeeded", "nomic-embed-text", 274_011_000, 274_011_000)
        assert all("pull" not in t for t in c.get("/api/local-tools").json()["tools"] if t["id"] not in ("ollama", "lm_studio"))


def test_the_ollama_card_pulls_a_chosen_model_and_deletes_only_a_listed_one(tmp_path, paths):
    sent = []

    def handler(request):
        url = str(request.url)
        if url in ("http://127.0.0.1:11434/api/pull", "http://127.0.0.1:11434/api/delete"):
            sent.append((request.method, url.rsplit("/", 1)[1], json.loads(request.content)))
            if url.endswith("/pull"):
                return httpx.Response(200, content=b'{"status":"pulling manifest"}\n{"status":"success"}')
            return httpx.Response(200)
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "pull-any", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        ollama = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "ollama")
        assert {"id": "qwen3.5:35b", "name": "Qwen 3.5 · 35B", "maker": "Alibaba", "purpose": "research", "size_bytes": 22_000_000_000} in ollama["suggested"]
        for bad in ("qwen3.5; rm -rf /", "../etc", "Qwen", "-x"):
            assert c.post("/api/local-tools/ollama/pull", json={"model": bad}).status_code == 400
        assert c.post("/api/local-tools/ollama/pull", json={"model": "qwen3.5:35b"}).status_code == 202
        for _ in range(50):
            pull = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "ollama")["pull"]
            if pull["status"] != "running":
                break
            time.sleep(0.02)
        assert (pull["status"], pull["model"]) == ("succeeded", "qwen3.5:35b")
        assert c.post("/api/local-tools/ollama/delete", json={"model": "llama3:70b"}).status_code == 404  # not listed
        assert c.post("/api/local-tools/ollama/delete", json={"model": "qwen3:8b"}).json() == {"deleted": "qwen3:8b"}
        assert sent == [("POST", "pull", {"model": "qwen3.5:35b", "stream": True}), ("DELETE", "delete", {"model": "qwen3:8b"})]


def test_the_ollama_card_cancels_a_running_download(tmp_path, paths):
    async def endless():
        yield b'{"status":"pulling 970aa74c","digest":"sha256:970aa74c","total":1000,"completed":10}\n'
        await asyncio.Event().wait()

    def handler(request):
        if str(request.url) == "http://127.0.0.1:11434/api/pull":
            return httpx.Response(200, content=endless())
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "pull-cancel", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        assert c.post("/api/local-tools/ollama/pull/cancel").status_code == 409  # nothing running
        assert c.post("/api/local-tools/ollama/pull", json={"model": "qwen3.5:4b"}).status_code == 202
        for _ in range(50):
            pull = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "ollama")["pull"]
            if pull["completed"]:
                break
            time.sleep(0.02)
        assert c.post("/api/local-tools/ollama/pull/cancel").json()["job"]["status"] == "cancelled"
        time.sleep(0.05)
        pull = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "ollama")["pull"]
        assert (pull["status"], pull["model"]) == ("cancelled", "qwen3.5:4b") and pull["finished_at"]
        assert c.post("/api/local-tools/ollama/pull", json={"model": "qwen3.5:4b"}).status_code == 202  # a new download may start


def test_the_embedding_model_download_needs_a_running_ollama(client, monkeypatch):
    async def down(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client.app.state.local_tools._client, "get", down)
    refused = client.post("/api/local-tools/ollama/pull-embedding-model")
    assert refused.status_code == 409 and "not running" in refused.json()["detail"]


def test_on_macos_ollama_installs_as_the_app_from_ollama_com(tmp_path, paths, monkeypatch):
    """The CLI from Homebrew alone starts no server, so the app is offered until it is there or a server answers."""
    app_path = tmp_path / "Applications" / "Ollama.app"
    copied, opened = [], []
    monkeypatch.setattr(local_tools, "OLLAMA_MAC", True)
    monkeypatch.setattr(local_tools, "OLLAMA_MAC_APP", app_path)
    monkeypatch.setattr(local_tools, "DOWNLOAD_TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"SYNTHETIC dmg") if str(r.url) == local_tools.OLLAMA_MAC_DMG else httpx.Response(404)))

    def copy(dmg, target):
        copied.append(dmg.read_bytes())
        target.mkdir(parents=True)

    monkeypatch.setattr(local_tools, "_copy_mac_app", copy)
    monkeypatch.setattr(local_tools, "_open_mac_app", opened.append)
    paths.update(ollama="/opt/homebrew/bin/ollama")  # Homebrew's CLI is on PATH, its server is not running

    def down(request):
        if ":11434/" in str(request.url):
            raise httpx.ConnectError("connection refused", request=request)
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "mac", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(down)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        ollama = lambda: next(t for t in c.get("/api/local-tools?refresh=true").json()["tools"] if t["id"] == "ollama")
        before = ollama()
        assert (before["installed"], before["running"], before["app_installed"]) == (True, False, False)
        assert before["install"] == {"command": "Ollama.app from ollama.com", "available": True, "unavailable_reason": None,
                                     "url": "https://ollama.com/download"}
        assert c.post("/api/local-tools/ollama/install").status_code == 202
        for _ in range(50):
            job = ollama()["job"]
            if job["status"] != "running":
                break
            time.sleep(0.02)
        assert (job["status"], job["completed"], job["total"]) == ("succeeded", 13, 13)
        assert copied == [b"SYNTHETIC dmg"] and opened == [app_path] and ollama()["app_installed"] is True
        assert c.post("/api/local-tools/ollama/install").status_code == 409


def test_ollama_updates_compare_the_release_and_each_models_manifest(tmp_path, paths):
    import hashlib
    manifests = {"library/qwen3": b'{"SYNTHETIC": "new manifest"}', "library/nomic-embed-text": b'{"SYNTHETIC": "same"}'}

    def handler(request):
        url = str(request.url)
        if url == "http://127.0.0.1:11434/api/version":
            return httpx.Response(200, json={"version": "0.34.0"})
        if url == "http://127.0.0.1:11434/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "qwen3:8b", "digest": hashlib.sha256(b"old manifest").hexdigest()},
                {"name": "nomic-embed-text:latest", "digest": hashlib.sha256(manifests["library/nomic-embed-text"]).hexdigest()},
                {"name": "gone:latest", "digest": "abc"}]})
        if url == local_tools.OLLAMA_RELEASES:
            return httpx.Response(200, json={"tag_name": "v0.40.4"})
        if url.startswith("https://registry.ollama.ai/v2/"):
            assert request.headers["accept"] == local_tools.OLLAMA_MANIFEST
            name = url.removeprefix("https://registry.ollama.ai/v2/").split("/manifests/")[0]
            return httpx.Response(200, content=manifests[name]) if name in manifests else httpx.Response(404)
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "upd", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        updates = c.get("/api/local-tools/ollama/updates").json()
    assert (updates["version"], updates["latest"], updates["update_available"]) == ("0.34.0", "0.40.4", True)
    assert updates["models"] == {"qwen3:8b": True, "nomic-embed-text:latest": False, "gone:latest": None}


def test_ollama_from_homebrew_updates_with_brew_upgrade_and_restarts_its_service(client, paths, monkeypatch):
    ran = []

    async def run(self, tool_id, job, argv):
        ran.append(argv[1:])
        job.update(status="succeeded", finished_at="SYNTHETIC")

    monkeypatch.setattr(local_tools.LocalTools, "_run", run)
    monkeypatch.setattr(local_tools, "_command_output", lambda argv, timeout=None: "Name   Status  User\nollama started SYNTHETIC")
    paths.update(ollama="/opt/homebrew/bin/ollama", brew="/opt/homebrew/bin/brew")
    assert client.post("/api/local-tools/ollama/update").status_code == 202
    for _ in range(50):
        if len(ran) == 2:
            break
        time.sleep(0.02)
    assert ran == [["upgrade", "ollama"], ["services", "restart", "ollama"]]
    assert client.post("/api/local-tools/zotero/update").status_code == 404


def test_the_ollama_app_updates_by_quitting_it_and_copying_the_newer_app_over_it(tmp_path, paths, monkeypatch):
    app_path = tmp_path / "Applications" / "Ollama.app"
    app_path.mkdir(parents=True)
    events = []
    monkeypatch.setattr(local_tools, "OLLAMA_MAC", True)
    monkeypatch.setattr(local_tools, "OLLAMA_MAC_APP", app_path)
    monkeypatch.setattr(local_tools, "DOWNLOAD_TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"SYNTHETIC dmg") if str(r.url) == local_tools.OLLAMA_MAC_DMG else httpx.Response(404)))
    monkeypatch.setattr(local_tools, "_quit_mac_app", lambda app: events.append("quit"))
    monkeypatch.setattr(local_tools, "_copy_mac_app", lambda dmg, target: events.append("copy"))
    monkeypatch.setattr(local_tools, "_open_mac_app", lambda app: events.append("open"))
    app = create_app(Settings(data_dir=tmp_path / "upd-app", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        job = c.post("/api/local-tools/ollama/update").json()["job"]
        assert (job["kind"], job["command"]) == ("update", "Ollama.app from ollama.com")
        for _ in range(50):
            job = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "ollama")["job"]
            if job["status"] != "running":
                break
            time.sleep(0.02)
    assert job["status"] == "succeeded" and events == ["quit", "copy", "open"]


def test_ollama_updates_need_a_running_ollama(client):
    refused = client.get("/api/local-tools/ollama/updates")
    assert refused.status_code == 409 and "not running" in refused.json()["detail"]


def test_lm_studio_downloads_a_catalog_model_through_its_rest_api_and_follows_the_job(tmp_path, paths, monkeypatch):
    monkeypatch.setattr(local_tools, "LMSTUDIO_POLL_SECONDS", 0)
    sent, polls = [], iter([{"status": "downloading", "downloaded_bytes": 50, "total_size_bytes": 100},
                            {"status": "completed", "downloaded_bytes": 100, "total_size_bytes": 100}])

    def handler(request):
        url = str(request.url)
        if url == "http://127.0.0.1:1234/api/v0/models":
            return httpx.Response(200, json={"data": [{"id": "SYNTHETIC-embed", "type": "embeddings"}]})
        if url == "http://127.0.0.1:1234/api/v1/models/download":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"job_id": "job_1", "status": "downloading", "total_size_bytes": 100})
        if url == "http://127.0.0.1:1234/api/v1/models/download/status/job_1":
            return httpx.Response(200, json={"job_id": "job_1", **next(polls)})
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "lms", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        assert c.post("/api/local-tools/lm_studio/pull", json={"model": "qwen3.5; rm -rf /"}).status_code == 400
        assert c.post("/api/local-tools/lm_studio/pull", json={"model": "qwen/qwen3.5-9b"}).status_code == 202
        for _ in range(50):
            lms = next(t for t in c.get("/api/local-tools").json()["tools"] if t["id"] == "lm_studio")
            if lms["pull"]["status"] != "running":
                break
            time.sleep(0.02)
        assert sent == [{"model": "qwen/qwen3.5-9b"}]
        assert (lms["pull"]["status"], lms["pull"]["completed"], lms["pull"]["total"]) == ("succeeded", 100, 100)
        assert {"id": "google/gemma-4-12b", "name": "Gemma 4 · 12B", "maker": "Google", "purpose": "research",
                "size_bytes": None, "memory_gb": 7} in lms["suggested"]


def test_lm_studio_downloads_need_its_server(client):
    refused = client.post("/api/local-tools/lm_studio/pull", json={"model": "qwen/qwen3.5-9b"})
    assert refused.status_code == 409 and "not running" in refused.json()["detail"]


def test_lm_studio_update_reads_the_version_its_download_link_redirects_to(tmp_path, paths, monkeypatch):
    monkeypatch.setattr(local_tools, "LMSTUDIO_MAC", True)
    monkeypatch.setattr(local_tools, "LMSTUDIO_MAC_APP", tmp_path / "LM Studio.app")
    monkeypatch.setattr(local_tools, "_app_version", lambda app: "0.4.20")
    (tmp_path / "LM Studio.app").mkdir()
    monkeypatch.setattr(local_tools, "TOOLS", {**local_tools.TOOLS, "lm_studio": dataclasses.replace(local_tools.TOOLS["lm_studio"], app=str(tmp_path / "LM Studio.app"))})

    def handler(request):
        if str(request.url) == local_tools.LMSTUDIO_MAC_DMG:
            return httpx.Response(302, headers={"location": "https://installers.lmstudio.ai/darwin/arm64/0.4.26-4/LM-Studio-0.4.26-4-arm64.dmg"})
        return remote(request)

    app = create_app(Settings(data_dir=tmp_path / "lmu", port=8765), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        updates = c.get("/api/local-tools/lm_studio/updates").json()
    assert (updates["version"], updates["latest"], updates["update_available"], updates["installed_with"]) == ("0.4.20", "0.4.26", True, "app")


def test_suggested_models_fall_back_to_the_fixed_list_when_the_catalog_cannot_be_read(client):
    # The test client's remote handler refuses ollama.com and lmstudio.ai.
    ollama = client.get("/api/local-tools/ollama/suggested").json()
    assert ollama["source"] == "fixed" and ollama["models"] == list(local_tools.OLLAMA_SUGGESTED)
    assert client.get("/api/local-tools/lm_studio/suggested").json()["models"] == list(local_tools.LMSTUDIO_SUGGESTED)
    assert client.get("/api/local-tools/zotero/suggested").status_code == 422


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


@pytest.mark.parametrize("env", SOURCE_KEYS)
def test_a_source_key_is_tested_with_one_request_and_a_refused_one_is_not_saved(client, memory_keychain, monkeypatch, env):
    monkeypatch.setenv(env, "")
    refused = client.put(f"/api/credentials/{env}", json={"value": "made-up-key-123"})
    assert refused.status_code == 422 and "did not accept" in refused.json()["detail"] and memory_keychain.items == {}
    saved = client.put(f"/api/credentials/{env}", json={"value": "source-good-key-123"}).json()
    assert saved["test"]["status"] == "ok" and saved["key"]["testable"] is True
    assert client.post(f"/api/credentials/{env}/test").json()["status"] == "ok"


def test_a_source_key_that_could_not_be_checked_is_still_saved(client, memory_keychain, monkeypatch):
    monkeypatch.setenv("SCOPUS_API_KEY", "")
    off_campus = client.put("/api/credentials/SCOPUS_API_KEY", json={"value": "scopus-off-campus-key"}).json()
    assert off_campus["test"]["status"] == "failed" and "this network" in off_campus["test"]["detail"]
    assert memory_keychain.items == {("DEIXIS", "SCOPUS_API_KEY"): "scopus-off-campus-key"}
    retest = client.post("/api/credentials/SCOPUS_API_KEY/test")  # a failed test is an answer, not a server error
    assert retest.status_code == 200 and retest.json()["http_status"] == 403


def test_a_missing_installer_is_a_reason_code_not_a_sentence(client, paths, monkeypatch):
    """B3: the page words the reason in its own language; the response names the missing program and nothing else."""
    tools = {t["id"]: t for t in client.get("/api/local-tools?refresh=true").json()["tools"]}
    assert (tools["cline"]["install"]["unavailable_reason"], tools["cline"]["install"]["manager"]) == ("manager_missing", "npm")
    assert (tools["kimi_cli"]["install"]["unavailable_reason"], tools["kimi_cli"]["install"]["manager"]) == ("uv_missing", "uv")
    refused = client.post("/api/local-tools/kimi_cli/install")
    assert refused.status_code == 422 and refused.json()["code"] == "uv_missing" and "PATH" not in refused.text
    assert client.post("/api/local-tools/cline/install").json()["code"] == "manager_missing"
    monkeypatch.setattr("deixis.workflow.equations.find_tool", lambda name: None)
    monkeypatch.setattr("deixis.workflow.local_embedding_service.find_tool", lambda name: None)
    reader, builtin = client.get("/api/equation-reader").json(), client.get("/api/semantic-search/builtin").json()
    assert reader["install"]["available"] is False and reader["install"]["unavailable_reason"] == "uv_missing"
    assert builtin["uv"]["available"] is False and builtin["uv"]["reason"] == "uv_missing"
    for body in (tools, reader, builtin):
        assert "was not found" not in str(body)


def test_a_failed_install_job_carries_a_marker_not_the_exception_or_a_path(client, paths, monkeypatch, caplog):
    """B3: the page words a job that could not run in its own language; the exception and the path stay in the log."""
    import asyncio

    async def cannot_start(*args, **kwargs):
        raise OSError(13, "SYNTHETIC denied at /private/SYNTHETIC/uv")

    paths["uv"] = "/SYNTHETIC/bin/uv"
    monkeypatch.setattr(asyncio, "create_subprocess_exec", cannot_start)
    with caplog.at_level("WARNING", logger="deixis.jobs"):
        assert client.post("/api/local-tools/kimi_cli/install").status_code == 202
        job = None
        for _ in range(100):
            job = next(t for t in client.get("/api/local-tools").json()["tools"] if t["id"] == "kimi_cli")["job"]
            if job["status"] != "running":
                break
            time.sleep(0.05)
    assert job["status"] == "failed" and job["output"] == "[could_not_run]"
    assert "SYNTHETIC" not in str(job) and "OSError" not in str(job) and "PermissionError" not in str(job)
    assert "PermissionError" in caplog.text and "/private/SYNTHETIC/uv" in caplog.text


def test_an_ollama_that_does_not_answer_a_delete_gives_a_code_not_a_class_name(client, paths, monkeypatch, caplog):
    async def running(self):
        return {"models": [{"id": "qwen3:8b"}]}

    async def down(self, *args, **kwargs):
        raise httpx.ConnectError("SYNTHETIC refused")

    monkeypatch.setattr(local_tools.LocalTools, "_running_ollama", running)
    monkeypatch.setattr(httpx.AsyncClient, "request", down)  # the app's own client; the test client is a sync one
    with caplog.at_level("WARNING", logger="deixis.tools.local_tools"):
        refused = client.post("/api/local-tools/ollama/delete", json={"model": "qwen3:8b"})
    assert refused.status_code == 502 and refused.json() == {"detail": "Ollama did not answer", "code": "server_not_answering"}
    assert "ConnectError" not in refused.text and "ConnectError" in caplog.text

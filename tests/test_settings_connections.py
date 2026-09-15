"""Settings › Connections (D29): API keys in the keychain, local tools and the semantic search provider.

The keychain is an in-memory backend (conftest), the APIs and local model servers are mocked, and installs run a stub
script. These show the application's handling, not that a real keychain, package manager or model server behaves the same.
"""

import dataclasses
import json
import os
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import credentials, local_tools
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter

GOOD_GEMINI = "gemini-good-key-123"


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
    monkeypatch.setattr(local_tools.shutil, "which", lambda name: found.get(name))
    monkeypatch.setattr(local_tools, "TOOLS", {k: dataclasses.replace(t, app=None) for k, t in local_tools.TOOLS.items()})
    monkeypatch.setattr(local_tools, "machine", lambda: {"chip": "SYNTHETIC chip", "memory_gb": 32, "disk_free_gb": 100})
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
                                   "source": "keychain", "testable": True}
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
    assert kept["test"]["status"] == "no_credit" and "no credits" in kept["test"]["detail"]
    assert memory_keychain.items == {("DEIXIS", "OPENAI_API_KEY"): "openai-no-credit-key"}


def test_keys_from_the_environment_are_left_alone_and_source_keys_are_not_tested(client, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "openalex-from-env")
    entry = next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == "OPENALEX_API_KEY")
    assert (entry["configured"], entry["source"], entry["testable"]) == (True, "environment", False)
    assert client.put("/api/credentials/OPENALEX_API_KEY", json={"value": "openalex-other-key"}).status_code == 409
    assert client.delete("/api/credentials/OPENALEX_API_KEY").status_code == 409

    monkeypatch.setenv("S2_API_KEY", "")
    saved = client.put("/api/credentials/S2_API_KEY", json={"value": "s2-key-12345"}).json()
    assert saved["test"] is None and saved["key"]["source"] == "keychain"
    assert client.post("/api/credentials/S2_API_KEY/test").status_code == 422
    assert client.put("/api/credentials/PATH", json={"value": "/SYNTHETIC/bin"}).status_code == 404
    assert client.put("/api/credentials/GEMINI_API_KEY", json={"value": "has space inside"}).status_code == 422


def test_saved_keys_are_loaded_at_startup_unless_the_environment_sets_them(monkeypatch, memory_keychain):
    monkeypatch.setenv("SCOPUS_API_KEY", "")
    monkeypatch.setenv("IEEE_API_KEY", "ieee-from-env")
    memory_keychain.set_password("DEIXIS", "SCOPUS_API_KEY", "scopus-from-keychain")
    memory_keychain.set_password("DEIXIS", "IEEE_API_KEY", "ieee-from-keychain")
    credentials.load_into_environment()
    assert os.environ["SCOPUS_API_KEY"] == "scopus-from-keychain" and credentials.status("SCOPUS_API_KEY")["source"] == "keychain"
    assert os.environ["IEEE_API_KEY"] == "ieee-from-env" and credentials.status("IEEE_API_KEY")["source"] == "environment"


def test_local_tools_report_clis_running_servers_and_embedding_models(client, paths, monkeypatch):
    paths.update(claude="/SYNTHETIC/bin/claude", npm="/SYNTHETIC/bin/npm")
    monkeypatch.setattr(local_tools, "_command_output", lambda argv: "2.1.270 (Claude Code)" if argv[0].endswith("claude") else None)
    data = client.get("/api/local-tools?refresh=true").json()
    tools = {t["id"]: t for t in data["tools"]}
    assert data["machine"]["memory_gb"] == 32
    claude = tools["claude_code"]
    assert (claude["installed"], claude["version"], claude["role"], claude["job"]) == (True, "2.1.270 (Claude Code)", "detected", None)
    codex = tools["codex"]
    assert (codex["installed"], codex["role"], codex["install"]["available"]) == (False, "runs_steps", True)
    assert codex["install"]["command"] == "npm install -g @openai/codex"
    ollama = tools["ollama"]
    assert (ollama["running"], ollama["installed"]) == (True, True)  # the server answers although no binary is on PATH
    assert [(m["id"], m["embedding"]) for m in ollama["models"]] == [("qwen3:8b", False), ("nomic-embed-text:latest", True)]
    assert ollama["install"]["available"] is False and "brew" in ollama["install"]["unavailable_reason"]
    assert (tools["lm_studio"]["installed"], tools["lm_studio"]["running"], tools["lm_studio"]["models"]) == (False, False, [])


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

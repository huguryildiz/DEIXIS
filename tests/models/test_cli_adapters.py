"""The Copilot CLI adapter (tools off, MCP refused, environment allowlist) and the bounded tool probe.

Fake processes only. Passing shows how the adapter and probe handle these runs, not a live Copilot.
"""

import asyncio
import httpx
import json
import os
import pytest
import sys
import threading
import time
from fastapi.testclient import TestClient
from pathlib import Path

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.models import cli_process
from deixis.models import copilot_cli
from deixis.models.adapter import CodexAdapter
from deixis.models.copilot_cli import CopilotCliAdapter
from deixis.models.copilot_cli import copilot_environment
from deixis.models.copilot_cli import parse_events
from deixis.tools import tool_probe
from fakes import FakeAdapter


# A stand-in for the Copilot binary: ACP mode answers initialize and session/new; prompt mode records its argv, cwd,
# environment and stdin, then prints the JSONL events it is given. Settings come from fake.json beside it: the adapter
# passes the child only an allowlist of environment variables.
FAKE = r'''
import json, os, sys
fake = json.load(open(os.path.join(os.path.dirname(__file__), 'fake.json')))
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("GitHub Copilot CLI 9.9.9."); sys.exit(0)
if "--acp" in args:
    for line in sys.stdin:
        req = json.loads(line)
        if req["method"] == "initialize":
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"protocolVersion": 1}}), flush=True)
        else:
            if fake.get("acp_error"):
                print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": fake["acp_error"]}}), flush=True)
                continue
            print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {}}), flush=True)
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"models": {"availableModels": [
                {"modelId": "auto", "name": "Auto"},
                {"modelId": "gpt-5-mini", "name": "GPT-5 mini", "_meta": {"copilotUsage": "0x", "copilotEnablement": "enabled"}},
                {"modelId": "claude-sonnet-5.5", "name": "Claude Sonnet 5.5", "_meta": {"copilotUsage": "1x"}},
                {"modelId": "locked", "name": "Locked", "_meta": {"copilotEnablement": "disabled"}}]}}}), flush=True)
    sys.exit(0)
record = fake["record"]
with open(record, "w") as f:
    json.dump({"argv": args, "cwd": os.getcwd(), "env": dict(os.environ), "stdin": sys.stdin.read(), "pid": os.getpid()}, f)
if fake.get("sleep"):
    import time; time.sleep(fake["sleep"])
sys.stdout.write(fake.get("events", ""))
sys.exit(fake.get("exit", 0))
'''


def events(*items):
    return "".join(json.dumps(item) + "\n" for item in items)


def message(model="gpt-5-mini", content='{"answer": "4"}', tools=()):
    return {"type": "assistant.message", "data": {"model": model, "content": content,
                                                  "toolRequests": [{"name": name} for name in tools]}}


END = {"type": "result", "sessionId": "s-1", "exitCode": 0}


OK = events(
    {"type": "session.mcp_servers_loaded", "data": {"servers": [{"name": "github-mcp-server", "status": "disabled"}]}},
    {"type": "assistant.message", "data": {"model": "gpt-5-mini", "content": "", "toolRequests": []}},
    message(),
    {"type": "session.usage_checkpoint", "data": {"providerModelMetrics": [{"metrics": {"usage": {"inputTokens": 10, "outputTokens": 2}}}]}},
    {"type": "result", "sessionId": "s-1", "exitCode": 0},
)


def make(tmp_path, monkeypatch, env=None, **fake):
    script = tmp_path / "fake_copilot.py"
    script.write_text(FAKE)
    (tmp_path / "fake.json").write_text(json.dumps({"record": str(tmp_path / "record.json"), **fake}))
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    return CopilotCliAdapter(home=tmp_path / "home", workspace=tmp_path / "ws", cli=[sys.executable, str(script)], turn_timeout=30)


def record(tmp_path):
    return json.loads((tmp_path / "record.json").read_text())


def test_run_step_sends_the_prompt_on_stdin_with_every_tool_off(tmp_path, monkeypatch):
    adapter = make(tmp_path, monkeypatch, events=OK, env={"GITHUB_TOKEN": "models-key", "GH_TOKEN": "gh", "COPILOT_GITHUB_TOKEN": "c"})
    result = asyncio.run(adapter.run_step("BASE", "DEV", "MSG", {}, "gpt-5-mini", "high"))
    assert result.status == "completed" and result.raw_text == '{"answer": "4"}'
    assert result.resolved_model == "gpt-5-mini" and result.requested_model_verified is True
    assert result.tool_item_types == [] and result.external_thread_id == "s-1"
    assert result.token_usage == {"inputTokens": 10, "outputTokens": 2}
    sent = record(tmp_path)
    assert sent["stdin"].startswith("BASE\n\nDEV\n\n") and sent["stdin"].endswith("MSG")
    argv = sent["argv"]
    assert argv[:2] == ["-p", ""] and argv[argv.index("--model") + 1] == "gpt-5-mini"
    assert argv[argv.index("--reasoning-effort") + 1] == "high"
    assert "--available-tools=deixis_no_tool" in argv and "--allow-all-tools" not in argv and "--yolo" not in argv
    assert {"--disable-builtin-mcps", "--no-custom-instructions", "--deny-tool=shell", "--deny-tool=write"} <= set(argv)
    assert Path(sent["cwd"]).resolve() == (tmp_path / "ws").resolve()
    assert sent["env"]["COPILOT_HOME"] == str(tmp_path / "home")
    assert not {"GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN"} & set(sent["env"])


def test_a_connected_mcp_server_is_an_isolation_violation():
    out = events({"type": "session.mcp_servers_loaded", "data": {"servers": [{"name": "playwright", "status": "connected"}]}}, message(), END)
    result = parse_events(out, "", 0, "gpt-5-mini")
    assert result.status == "isolation_violation" and "playwright" in result.error


def test_copilot_environment_keeps_only_the_allowlist(monkeypatch):
    monkeypatch.setattr(copilot_cli, "find_tool", lambda name: None)
    monkeypatch.setattr("deixis.tools.tool_paths.find_tool", lambda name: None)  # no real copilot or node folder joins PATH
    env = copilot_environment(Path("/h"), {"PATH": "/bin", "LC_ALL": "C", "GITHUB_TOKEN": "x", "DEEPSEEK_API_KEY": "y"})
    assert env == {"PATH": "/bin", "LC_ALL": "C", "COPILOT_HOME": "/h", "COPILOT_AUTO_UPDATE": "false", "NO_COLOR": "1",
                   "NODE_USE_SYSTEM_CA": "1"}


HANGS = "#!/bin/sh\nsleep 600\n"


def script(path, body):
    path.write_bytes(body if isinstance(body, bytes) else body.encode())
    path.chmod(0o755)
    return path


def gone(pid):
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def windows(monkeypatch, **answers):
    """Windows with stand-ins for kernel32 and ntdll that record each call; the real Windows ABI cannot run here."""
    monkeypatch.setattr(cli_process, "WINDOWS", True)
    monkeypatch.setattr(cli_process.subprocess, "run", lambda *a, **k: pytest.fail("taskkill was used despite the job"))
    answers = {"OpenProcess": 9, "CreateJobObjectW": 7, "NtResumeProcess": 0} | answers
    calls = []

    class Library:
        def __getattr__(self, name):
            return lambda *args: calls.append((name, *args)) or answers.get(name, 1)

    monkeypatch.setattr(cli_process, "_kernel32", Library)
    monkeypatch.setattr(cli_process, "_ntdll", Library)
    return calls


def test_a_hung_codex_does_not_hold_up_the_api_or_the_other_connections(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "codex", HANGS)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(tool_probe, "PROBE_TIMEOUT", 2.0)
    codex = CodexAdapter(tmp_path / "codex-home", tmp_path / "workspace")
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"codex": codex, "fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        replies = {}

        def check(name, url):
            started = time.monotonic()
            replies[name] = (client.get(url).json(), time.monotonic() - started)

        slow = threading.Thread(target=check, args=("connections", "/api/connections?refresh=true"))
        slow.start()
        time.sleep(0.3)  # the codex probe is now waiting on the hung CLI
        check("health", "/api/health")
        slow.join(10)
    health, health_seconds = replies["health"]
    assert health["status"] == "ok" and health_seconds < 1  # answered while the codex probe was still waiting
    connections, seconds = replies["connections"]
    assert seconds < 5
    status = connections["models"]["codex"]
    assert (status["installed"], status["ready"], status["reason_code"]) == (True, False, "timeout")
    assert status["reason"] == "Codex CLI is not responding"
    assert connections["models"]["fake"]["ready"] is True  # the other connection's check is not hidden

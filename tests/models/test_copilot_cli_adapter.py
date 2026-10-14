import asyncio
import json
import sys
from pathlib import Path

from deixis.models import copilot_cli
from deixis.models.copilot_cli import CopilotCliAdapter, copilot_environment, native_binary, parse_events

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
    json.dump({"argv": args, "cwd": os.getcwd(), "env": dict(os.environ), "stdin": sys.stdin.read()}, f)
sys.stdout.write(fake.get("events", ""))
sys.exit(fake.get("exit", 0))
'''


def events(*items):
    return "".join(json.dumps(item) + "\n" for item in items)


def message(model="gpt-5-mini", content='{"answer": "4"}', tools=()):
    return {"type": "assistant.message", "data": {"model": model, "content": content,
                                                  "toolRequests": [{"name": name} for name in tools]}}


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


def test_health_lists_the_accounts_enabled_models_without_auto(tmp_path, monkeypatch):
    status = asyncio.run(make(tmp_path, monkeypatch).health(refresh=True))
    assert status["ready"] is True and status["signed_in"] is True
    assert status["cli_version"] == "9.9.9"
    assert [(m["id"], m["usage"]) for m in status["models"]] == [("gpt-5-mini", "0x"), ("claude-sonnet-5.5", "1x")]
    assert status["isolation"] == {"instruction_sources": 0, "live_mcp_servers": []}


def test_health_reports_a_sign_in_error(tmp_path, monkeypatch):
    status = asyncio.run(make(tmp_path, monkeypatch, acp_error="Authentication required").health(refresh=True))
    assert status["ready"] is False and status["signed_in"] is False and status["reason_code"] == "auth_failed"


def test_health_fails_isolation_when_the_deixis_home_configures_mcp_servers(tmp_path, monkeypatch):
    adapter = make(tmp_path, monkeypatch)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "mcp-config.json").write_text(json.dumps({"mcpServers": {"playwright": {}}}))
    status = asyncio.run(adapter.health(refresh=True))
    assert status["ready"] is False and status["isolation"]["live_mcp_servers"] == ["playwright"]


def test_health_without_the_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot_cli.shutil, "which", lambda name: None)
    status = asyncio.run(CopilotCliAdapter(home=tmp_path / "h", workspace=tmp_path / "w").health(refresh=True))
    assert status == {"connection": "copilot_cli", "installed": False, "ready": False, "reason": "GitHub Copilot CLI not found"}


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


def test_a_tool_request_or_run_is_reported_for_rejection(tmp_path, monkeypatch):
    out = events(message(content="", tools=["view"]),
                 {"type": "tool.execution_start", "data": {"toolName": "bash"}}, message())
    result = asyncio.run(make(tmp_path, monkeypatch, events=out).run_step("b", "d", "m", {}, "gpt-5-mini"))
    assert result.tool_item_types == ["view", "bash"]


def test_a_connected_mcp_server_is_an_isolation_violation():
    out = events({"type": "session.mcp_servers_loaded", "data": {"servers": [{"name": "playwright", "status": "connected"}]}}, message())
    result = parse_events(out, "", 0, "gpt-5-mini")
    assert result.status == "isolation_violation" and "playwright" in result.error


def test_another_model_answering_is_kept_and_not_verified():
    result = parse_events(events(message(model="gpt-5.4"), message(model="gpt-5-mini")), "", 0, "gpt-5-mini")
    assert result.status == "completed" and result.resolved_model == "gpt-5.4" and result.requested_model_verified is False


def test_an_unknown_model_fails_before_sending():
    result = parse_events('Error: Model "nope" from --model flag is not available.\n', "", 1, "nope")
    assert result.status == "failed" and result.delivery_class == "before_send" and "not available" in result.error


def test_a_nonzero_exit_after_an_answer_is_a_failure_after_sending(tmp_path, monkeypatch):
    out = events(message(), {"type": "model.call_final_result", "data": {"result": "error", "error": "rate limited"}})
    result = asyncio.run(make(tmp_path, monkeypatch, events=out, exit=1).run_step("b", "d", "m", {}, "gpt-5-mini"))
    assert result.status == "failed" and result.delivery_class == "after_send_unknown" and "rate limited" in result.error


def test_copilot_environment_keeps_only_the_allowlist():
    env = copilot_environment(Path("/h"), {"PATH": "/bin", "LC_ALL": "C", "GITHUB_TOKEN": "x", "DEEPSEEK_API_KEY": "y"})
    assert env == {"PATH": "/bin", "LC_ALL": "C", "COPILOT_HOME": "/h", "COPILOT_AUTO_UPDATE": "false", "NO_COLOR": "1"}


def test_native_binary_skips_the_npm_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot_cli.sys, "platform", "win32")
    monkeypatch.setattr(copilot_cli.platform, "machine", lambda: "AMD64")
    package = tmp_path / "node_modules" / "@github" / "copilot"
    (package / "node_modules" / "@github" / "copilot-win32-x64").mkdir(parents=True)
    (package / "npm-loader.js").write_text("")
    exe = package / "node_modules" / "@github" / "copilot-win32-x64" / "copilot.exe"
    exe.write_text("")
    launcher = tmp_path / "copilot.cmd"  # npm's Windows shim sits next to node_modules
    launcher.write_text("")
    assert native_binary(launcher) == str(exe)
    standalone = tmp_path / "bin" / "copilot"
    standalone.parent.mkdir()
    standalone.write_text("")
    assert native_binary(standalone) == str(standalone)

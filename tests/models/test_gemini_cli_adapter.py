"""Gemini CLI connection (D23): a fake CLI runner stands in for `gemini`; no real CLI runs here.

The stream-json lines below follow Gemini CLI 0.60's headless output (init, message, tool_use, tool_result, error,
result). They show how the adapter reads that output, not how the real CLI or a Google account behaves.
"""

import asyncio
import json
from pathlib import Path

import pytest

from deixis.models import gemini_cli
from deixis.models.gemini_cli import CliRun, GeminiCliAdapter

MODEL = "gemini-2.5-flash"
INELIGIBLE = """Error authenticating: IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals.
  ineligibleTiers: [
    {
      reasonCode: 'UNSUPPORTED_CLIENT',
      tierId: 'free-tier',
"""


def lines(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def answer(text='{"ok": true}', models=(MODEL,), tool_calls=0, status="success"):
    return lines(
        {"type": "init", "session_id": "s-1", "model": MODEL},
        {"type": "message", "role": "user", "content": "x"},
        {"type": "message", "role": "assistant", "content": text[:5], "delta": True},
        {"type": "message", "role": "assistant", "content": text[5:], "delta": True},
        {"type": "result", "status": status, "stats": {"total_tokens": 12, "input_tokens": 9, "output_tokens": 3,
                                                       "tool_calls": tool_calls,
                                                       "models": {m: {"total_tokens": 12} for m in models}}},
    )


class FakeCli:
    def __init__(self, *runs):
        self.runs = list(runs)
        self.calls = []

    async def __call__(self, argv, env, cwd, stdin, timeout):
        home = Path(env["GEMINI_CLI_HOME"])
        self.calls.append({
            "argv": argv, "env": dict(env), "cwd": cwd, "stdin": stdin, "timeout": timeout,
            "cwd_entries": sorted(p.name for p in cwd.iterdir()),
            "settings": json.loads((home / ".gemini" / "settings.json").read_text()),
            "system_settings": json.loads((home / "system-settings.json").read_text()),
            "system_md": (home / "system.md").read_text(),
            "home_entries": sorted(p.name for p in (home / ".gemini").iterdir()),
        })
        return self.runs.pop(0)


@pytest.fixture
def creds(tmp_path):
    path = tmp_path / "user" / ".gemini" / "oauth_creds.json"
    path.parent.mkdir(parents=True)
    path.write_text("SYNTHETIC, never read by DEIXIS")
    return path


@pytest.fixture(autouse=True)
def cli_on_path(monkeypatch):
    monkeypatch.setattr(gemini_cli.shutil, "which", lambda name: "/usr/local/bin/gemini" if name == "gemini" else None)


def adapter(tmp_path, creds, fake):
    return GeminiCliAdapter(home=tmp_path / "gemini-cli-home", runner=fake, credentials=creds)


def test_run_step_argv_env_and_isolated_home(tmp_path, creds, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-KEY")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "synthetic-project")
    fake = FakeCli(CliRun(0, answer(), ""))
    result = asyncio.run(adapter(tmp_path, creds, fake).run_step("BASE", "DEVELOPER", "MESSAGE @x", {"type": "object"}, MODEL))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"ok": true}', MODEL, "s-1")
    call = fake.calls[0]
    assert call["argv"] == ["/usr/local/bin/gemini", "-m", MODEL, "-o", "stream-json", "-e", "none",
                            "--approval-mode", "default", "-p", ""]
    assert call["stdin"] == "MESSAGE @x"  # the message goes on stdin, never on the command line
    home = Path(call["env"]["GEMINI_CLI_HOME"])
    assert home.parent == tmp_path / "gemini-cli-home" and call["cwd"] == home / "workspace"
    assert call["cwd_entries"] == []  # an empty working directory: @path references find nothing to read
    env = call["env"]
    assert env["GOOGLE_APPLICATION_CREDENTIALS"] == str(creds) and env["NO_BROWSER"] == "true"
    assert env["GEMINI_SYSTEM_MD"] == str(home / "system.md")
    assert env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] == str(home / "system-settings.json")
    assert env["GEMINI_CLI_SYSTEM_DEFAULTS_PATH"] == str(home / "system-defaults.json")
    assert env["GOOGLE_CLOUD_PROJECT"] == "synthetic-project"
    assert "GEMINI_API_KEY" not in env and "OPENAI_API_KEY" not in env
    # The developer text (with the schema appendix the flow adds for a non-enforcing adapter) replaces the CLI prompt.
    assert call["system_md"] == "BASE\n\nDEVELOPER\n\nReturn only a JSON object."
    assert call["home_entries"] == ["settings.json"]  # no copied sign-in file
    assert not home.exists()  # the per-call home, with anything the CLI wrote into it, is deleted
    assert creds.read_text() == "SYNTHETIC, never read by DEIXIS"
    assert GeminiCliAdapter(home=tmp_path).enforces_schema is False


def test_settings_turn_off_tools_mcp_extensions_and_context(tmp_path, creds):
    fake = FakeCli(CliRun(0, answer(), ""))
    asyncio.run(adapter(tmp_path, creds, fake).run_step("B", "D", "M", {}, MODEL))
    for settings in (fake.calls[0]["settings"], fake.calls[0]["system_settings"]):
        assert settings["tools"]["core"] == []  # an empty list registers no built-in tool
        assert settings["mcpServers"] == {} and settings["skills"] == {"enabled": False}
        assert settings["hooksConfig"] == {"enabled": False} and settings["hooks"] == {}
        assert settings["experimental"]["enableAgents"] is False and settings["useWriteTodos"] is False
        assert settings["context"]["fileName"] == "DEIXIS-NO-CONTEXT-FILE.md"
        assert settings["context"]["includeDirectoryTree"] is False and settings["context"]["memoryBoundaryMarkers"] == []
        assert settings["security"]["auth"]["selectedType"] == "oauth-personal"
        assert settings["privacy"]["usageStatisticsEnabled"] is False


@pytest.mark.parametrize("stdout", [
    lines({"type": "init", "session_id": "s", "model": MODEL},
          {"type": "tool_use", "tool_name": "run_shell_command", "tool_id": "t1", "parameters": {"command": "ls"}},
          {"type": "tool_result", "tool_id": "t1", "status": "error"},
          {"type": "message", "role": "assistant", "content": "{}"},
          {"type": "result", "status": "success", "stats": {"tool_calls": 1, "models": {MODEL: {}}}}),
    answer(tool_calls=2),
])
def test_a_tool_event_is_an_isolation_violation(tmp_path, creds, stdout):
    result = asyncio.run(adapter(tmp_path, creds, FakeCli(CliRun(0, stdout, ""))).run_step("B", "D", "M", {}, MODEL))
    assert result.status == "isolation_violation" and result.tool_item_types


def test_another_answering_model_is_reported_for_model_mismatch(tmp_path, creds):
    fake = FakeCli(CliRun(0, answer(models=("gemini-2.5-pro", MODEL)), ""))
    result = asyncio.run(adapter(tmp_path, creds, fake).run_step("B", "D", "M", {}, MODEL))
    # The flow compares resolved_model with the requested one and fails the step with model_mismatch.
    assert result.status == "completed" and result.resolved_model == "gemini-2.5-pro"
    assert result.requested_model_verified is False


def test_no_model_stats_leaves_the_model_unknown(tmp_path, creds):
    fake = FakeCli(CliRun(0, answer(models=()), ""))
    result = asyncio.run(adapter(tmp_path, creds, fake).run_step("B", "D", "M", {}, MODEL))
    assert result.resolved_model is None


def test_text_that_is_not_json_is_returned_as_received_for_the_repair(tmp_path, creds):
    fake = FakeCli(CliRun(0, answer(text='```json\n{"ok": true}\n```'), ""))
    result = asyncio.run(adapter(tmp_path, creds, fake).run_step("B", "D", "M", {}, MODEL))
    assert result.status == "completed" and result.raw_text == '```json\n{"ok": true}\n```'


def test_ineligible_account_is_unavailable_before_send(tmp_path, creds):
    fake = FakeCli(CliRun(1, "", INELIGIBLE))
    result = asyncio.run(adapter(tmp_path, creds, fake).run_step("B", "D", "M", {}, MODEL))
    assert (result.status, result.delivery_class, result.error_kind) == ("unavailable", "before_send", "auth_failed")
    assert "UNSUPPORTED_CLIENT" in result.error


def test_an_error_result_fails_after_send(tmp_path, creds):
    stdout = lines({"type": "init", "session_id": "s", "model": MODEL},
                   {"type": "error", "severity": "error", "message": "Resource has been exhausted (429)"},
                   {"type": "result", "status": "error", "stats": {"models": {MODEL: {}}}})
    result = asyncio.run(adapter(tmp_path, creds, FakeCli(CliRun(1, stdout, ""))).run_step("B", "D", "M", {}, MODEL))
    assert (result.status, result.delivery_class, result.error_kind) == ("failed", "after_send_unknown", "rate_limited")


def test_no_sign_in_file_sends_nothing(tmp_path):
    fake = FakeCli()
    gone = tmp_path / "missing" / "oauth_creds.json"
    result = asyncio.run(GeminiCliAdapter(home=tmp_path, runner=fake, credentials=gone).run_step("B", "D", "M", {}, MODEL))
    assert (result.status, result.error_kind) == ("unavailable", "auth_failed") and fake.calls == []


def test_health_ready_after_an_empty_probe(tmp_path, creds):
    fake = FakeCli(CliRun(0, "0.60.0\n", ""), CliRun(42, "", "No input provided via stdin. Input can be provided by piping"))
    status = asyncio.run(adapter(tmp_path, creds, fake).health(refresh=True))
    assert (status["ready"], status["signed_in"], status["cli_version"], status["catalogue"]) == (True, True, "0.60.0", "fixed")
    assert fake.calls[1]["argv"] == ["/usr/local/bin/gemini", "-o", "stream-json", "-e", "none", "-p", ""]
    assert fake.calls[1]["stdin"] == ""  # no prompt: the probe never reaches a model request
    assert "gemini-2.5-pro" in [m["id"] for m in status["models"]]
    assert all(m["reasoning_efforts"] == [] for m in status["models"])
    assert "isolation" not in status  # nothing observed, so nothing claimed


def test_health_reports_an_ineligible_account(tmp_path, creds):
    fake = FakeCli(CliRun(0, "0.60.0\n", ""), CliRun(42, "", INELIGIBLE + "\nNo input provided via stdin."))
    status = asyncio.run(adapter(tmp_path, creds, fake).health(refresh=True))
    assert (status["ready"], status["signed_in"], status["reason_code"]) == (False, True, "auth_failed")
    assert "UNSUPPORTED_CLIENT" in status["reason"]


def test_health_not_signed_in(tmp_path):
    fake = FakeCli(CliRun(0, "0.60.0\n", ""))
    status = asyncio.run(GeminiCliAdapter(home=tmp_path, runner=fake, credentials=tmp_path / "none.json").health(refresh=True))
    assert (status["ready"], status["signed_in"], status["reason_code"]) == (False, False, "auth_failed")
    assert len(fake.calls) == 1  # only --version


def test_health_auth_error_with_a_sign_in_file(tmp_path, creds):
    fake = FakeCli(CliRun(0, "0.60.0\n", ""), CliRun(41, "", "FatalAuthenticationError: Manual authorization is required"))
    status = asyncio.run(adapter(tmp_path, creds, fake).health(refresh=True))
    assert (status["ready"], status["signed_in"]) == (False, False)


def test_health_without_cli(tmp_path, creds, monkeypatch):
    monkeypatch.setattr(gemini_cli.shutil, "which", lambda name: None)
    status = asyncio.run(adapter(tmp_path, creds, FakeCli()).health(refresh=True))
    assert (status["installed"], status["ready"]) == (False, False)


def test_user_credentials_follow_the_users_gemini_home(tmp_path):
    assert gemini_cli.user_credentials({"GEMINI_CLI_HOME": str(tmp_path)}) == tmp_path / ".gemini" / "oauth_creds.json"


def test_a_slow_version_does_not_fail_the_check(tmp_path, creds):
    """15 Oct: `gemini --version` took over 20 s; the version is shown only, so the check goes on to the sign-in."""

    class SlowVersion(FakeCli):
        async def __call__(self, argv, env, cwd, stdin, timeout):
            if "--version" in argv:
                self.calls.append({"argv": argv})
                raise TimeoutError
            return await super().__call__(argv, env, cwd, stdin, timeout)

    fake = SlowVersion(CliRun(42, "", INELIGIBLE + "\nNo input provided via stdin."))
    status = asyncio.run(adapter(tmp_path, creds, fake).health(refresh=True))
    assert status["cli_version"] is None and "UNSUPPORTED_CLIENT" in status["reason"]


def test_run_cli_stops_a_child_left_holding_the_pipes(tmp_path):
    """The CLI relaunches itself as a child; a timeout stops the whole process group."""
    import os
    import sys
    import time
    if os.name == "nt":
        return
    record = tmp_path / "child.json"
    script = ("import subprocess, sys, json\n"
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
              f"json.dump({{'pid': child.pid}}, open({str(record)!r}, 'w'))\n")
    with pytest.raises(TimeoutError):
        asyncio.run(gemini_cli.run_cli([sys.executable, "-c", script], dict(os.environ), tmp_path, "", 3))
    pid = json.loads(record.read_text())["pid"]
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the child kept running")


def test_a_nonzero_exit_is_not_completed_even_with_a_success_event():
    """Sol D23 round 1: the process exit code must be 0 too."""
    result = GeminiCliAdapter.result_of(CliRun(1, answer(), "Error: something broke"), MODEL)
    assert result.status == "failed" and result.delivery_class == "after_send_unknown"


def test_a_sign_in_refusal_after_the_init_event_is_not_sent():
    """Sol D23 round 1: a refusal with no answer and no model stats sent nothing, even after `init`."""
    stdout = lines({"type": "init", "session_id": "s", "model": MODEL})
    result = GeminiCliAdapter.result_of(CliRun(42, stdout, INELIGIBLE), MODEL)
    assert (result.status, result.delivery_class, result.error_kind) == ("unavailable", "before_send", "auth_failed")


def test_gemini_cli_has_the_terminal_sign_in():
    """D21's Sign in button opens a terminal running `gemini`, where the person chooses Sign in with Google."""
    from deixis import account_signin
    assert account_signin.TOOLS["gemini_cli"] == ("gemini", [], "Gemini CLI")

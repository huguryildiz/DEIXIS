"""Gemini CLI connection (D23): a fake CLI runner stands in for `gemini`; no real CLI runs here.

The stream-json lines below follow Gemini CLI 0.60's headless output (init, message, tool_use, tool_result, error,
result). They show how the adapter reads that output, not how the real CLI or a Google account behaves.
"""

import asyncio
import json
from pathlib import Path

import pytest

from deixis.tools import tool_probe
from deixis.models import gemini_cli
from deixis.models.gemini_cli import CliRun, GeminiCliAdapter

MODEL = "gemini-2.5-flash"


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
    monkeypatch.setattr(gemini_cli, "find_tool", lambda name: "/usr/local/bin/gemini" if name == "gemini" else None)


@pytest.fixture(autouse=True)
def version_probe(monkeypatch):
    """`gemini --version` goes through the bounded tool probe (A3b), not the fake runner; this stands in for it."""
    class Asked(list):
        answer = tool_probe.Probe(0, "0.60.0\n")

    asked = Asked()

    async def probe(argv, timeout=None, env=None):
        asked.append((argv, timeout))
        return asked.answer

    monkeypatch.setattr(tool_probe, "probe", probe)
    return asked


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
        assert settings["privacy"]["usageStatisticsEnabled"] is False and settings["telemetry"]["enabled"] is False


def test_another_answering_model_is_reported_for_model_mismatch(tmp_path, creds):
    fake = FakeCli(CliRun(0, answer(models=("gemini-2.5-pro", MODEL)), ""))
    result = asyncio.run(adapter(tmp_path, creds, fake).run_step("B", "D", "M", {}, MODEL))
    # The flow compares resolved_model with the requested one and fails the step with model_mismatch.
    assert result.status == "completed" and result.resolved_model == "gemini-2.5-pro"
    assert result.requested_model_verified is False



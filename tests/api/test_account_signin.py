"""Sign in to Codex and Claude Code from Settings (D21): the terminal launcher, the routes and the state machine.

A fake launcher stands in for the terminal and a fake health check for the tools; no real terminal opens and no CLI
runs. Passing shows the command lines built per platform, the state machine (waiting, succeeded, failed, timed out,
cancelled), that success needs this attempt's own exit code and a fresh health check (E8), cancel and re-attach (E20)
and the route guards. The macOS and Linux status lines are run with /bin/sh against a stand-in command; the Windows
one is only read as text. It says nothing about whether a real Terminal.app, PowerShell window or Linux terminal opens
with these commands, or what `codex login` and `claude auth login` ask.
"""

import json
import shlex
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.keys import account_signin
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter


class Health(FakeAdapter):
    """A model adapter whose health flips to signed in on demand."""

    def __init__(self):
        super().__init__()
        self.signed_in, self.refreshes, self.closed = False, 0, 0
        self._active = set()

    async def health(self, refresh=False):
        self.refreshes += refresh
        return {"ready": self.signed_in, "signed_in": self.signed_in}

    async def close(self):
        self.closed += 1


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def finish(app, tool, code="0"):
    """What the terminal script does when the login command ends: write its exit code to this attempt's status file."""
    app.state.account_signin._run[tool]["status"].write_text(code)


class Window:
    """The handle of a Windows terminal process: alive until closed."""

    def __init__(self):
        self.closed, self.terminated = False, False

    def poll(self):
        return 0 if self.closed else None

    def terminate(self):
        self.terminated = self.closed = True


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: f"/usr/local/bin/{name}")
    launched = []
    clock = Clock()
    codex, claude = Health(), Health()
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter(), "codex": codex, "claude": claude},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",),
                     signin_launcher=launched.append, signin_platform="darwin")
    with TestClient(app) as client:
        app.state.account_signin._clock = clock  # built at startup, so swapped in once the app is up
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        yield app, client, launched, settings, clock, {"codex": codex, "claude": claude}


# --- command lines per platform -------------------------------------------------------------------------------


    # More of this (the encoded script, hostile paths, no batch file) is in tests/api/test_launcher.py.


# --- state machine through the routes -------------------------------------------------------------------------

def test_codex_launch_waits_then_succeeds_only_after_the_command_exits_0_and_health_says_signed_in(served):
    app, client, launched, settings, clock, tools = served
    assert client.get("/api/accounts/codex/sign-in").json() == {"state": "idle", "message": None}
    assert client.post("/api/accounts/codex/sign-in").json() == {"state": "waiting", "message": None}
    assert launched[0][:3] == ["open", "-a", "Terminal"] and Path(launched[0][3]).parent == settings.codex_home.parent / "sign-in"
    assert f"CODEX_HOME={shlex.quote(str(settings.codex_home))} /usr/local/bin/codex login" in Path(launched[0][3]).read_text()
    # The command has not ended: no status file, so no health check is made, however long it takes.
    tools["codex"].signed_in = True  # an account that was already signed in
    clock.now += 60
    assert client.get("/api/accounts/codex/sign-in").json()["state"] == "waiting" and tools["codex"].refreshes == 0
    status = app.state.account_signin._run["codex"]["status"]
    finish(app, "codex")
    assert client.get("/api/accounts/codex/sign-in").json() == {"state": "succeeded", "message": None}
    assert tools["codex"].refreshes == 1 and not status.exists()


def test_gemini_sign_in_window_reads_a_deixis_written_system_settings_file(served):
    # F3 review: the documented GEMINI_CLI_SYSTEM_SETTINGS_PATH names a small file with usage statistics and telemetry
    # off; HOME and the person's own Gemini files are not touched.
    _, client, launched, settings, _, _ = served
    client.post("/api/accounts/gemini_cli/sign-in")
    script = Path(launched[0][3]).read_text()
    path = settings.codex_home.parent / "sign-in" / "gemini-system-settings.json"
    assert f"GEMINI_CLI_SYSTEM_SETTINGS_PATH={shlex.quote(str(path))} " in script and "HOME=" not in script
    assert json.loads(path.read_text()) == {"privacy": {"usageStatisticsEnabled": False}, "telemetry": {"enabled": False}}


def test_a_non_zero_exit_fails_even_when_health_says_signed_in(served):
    app, client, _, _, _, tools = served
    tools["codex"].signed_in = True
    client.post("/api/accounts/codex/sign-in")
    finish(app, "codex", "1")
    done = client.get("/api/accounts/codex/sign-in").json()
    assert done["state"] == "failed" and "ended with an error" in done["message"] and tools["codex"].refreshes == 0


# --- the status lines the terminal scripts really run ----------------------------------------------------------


def test_post_without_csrf_is_rejected_and_opens_nothing(served):
    _, client, launched, _, _, _ = served
    bare = TestClient(client.app)
    response = bare.post("/api/accounts/codex/sign-in")
    assert response.status_code in (400, 403) and launched == []


# --- review fixes (E8, E20) ------------------------------------------------------------------------------------



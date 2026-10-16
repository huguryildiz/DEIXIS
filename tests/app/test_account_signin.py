"""Sign in to Codex and Claude Code from Settings (D21): the terminal launcher, the routes and the state machine.

A fake launcher stands in for the terminal and a fake health check for the tools; no real terminal opens and no CLI
runs. Passing shows the command lines built per platform, the state machine (waiting, succeeded, timed out), the
check pacing and the route guards. It says nothing about whether a real Terminal.app, cmd.exe or Linux terminal opens
with these commands, or what `codex login` and `claude auth login` ask.
"""

import asyncio
import shlex
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import account_signin
from deixis.account_signin import SignInError, build_launch
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

def test_mac_opens_a_self_removing_command_file_in_terminal_app(tmp_path):
    home = Path('/Users/jo "q"/Application Support/codex-home')
    argv = build_launch("darwin", "/opt/my bin/codex", ["login"], home, script_dir=tmp_path)
    script = tmp_path / "deixis-sign-in-codex.command"
    assert argv == ["open", "-a", "Terminal", str(script)]
    assert script.stat().st_mode & 0o777 == 0o700
    lines = script.read_text().splitlines()
    assert lines[:3] == ["#!/bin/sh", 'rm -f "$0"',
                         "CODEX_HOME='/Users/jo \"q\"/Application Support/codex-home' '/opt/my bin/codex' login"]


def test_mac_quotes_a_single_quote_in_a_path_for_the_shell(tmp_path):
    build_launch("darwin", "/bin/claude", ["auth", "login"], Path("/Users/o'neil/home"), script_dir=tmp_path)
    assert "CODEX_HOME='/Users/o'\"'\"'neil/home'" in (tmp_path / "deixis-sign-in-claude.command").read_text()
    build_launch("darwin", "/bin/claude", ["auth", "login"], None, script_dir=tmp_path)
    assert "\n/bin/claude auth login\n" in (tmp_path / "deixis-sign-in-claude.command").read_text()


def test_windows_starts_a_titled_cmd_window_with_codex_home_set_inside_it():
    home = Path("C:/Users/Jo Q/AppData/codex-home")
    line = build_launch("win32", "C:\\Program Files\\nodejs\\codex.cmd", ["login"], home)
    assert line == ('cmd.exe /c start "DEIXIS sign-in" cmd.exe /k '
                    f'"set "CODEX_HOME={home}"&& "C:\\Program Files\\nodejs\\codex.cmd" login"')
    assert build_launch("win32", "C:\\bin\\claude.cmd", ["auth", "login"], None) == \
        'cmd.exe /c start "DEIXIS sign-in" cmd.exe /k "C:\\bin\\claude.cmd auth login"'


def test_linux_picks_the_first_terminal_in_order_and_gnome_terminal_uses_a_double_dash():
    present = {"konsole": "/usr/bin/konsole", "xterm": "/usr/bin/xterm", "gnome-terminal": "/usr/bin/gnome-terminal"}
    argv = build_launch("linux", "/bin/codex", ["login"], Path("/h"), present.get)
    assert argv[:3] == ["/usr/bin/gnome-terminal", "--", "sh"] and "CODEX_HOME=/h /bin/codex login" in argv[4]
    del present["gnome-terminal"]
    assert build_launch("linux", "/bin/claude", ["auth", "login"], None, present.get)[:2] == ["/usr/bin/konsole", "-e"]
    present["x-terminal-emulator"] = "/usr/bin/x-terminal-emulator"
    assert build_launch("linux", "/bin/claude", ["auth", "login"], None, present.get)[0] == "/usr/bin/x-terminal-emulator"
    assert account_signin.LINUX_TERMINALS == ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm")


def test_linux_without_a_terminal_is_409():
    with pytest.raises(SignInError) as caught:
        build_launch("linux", "/bin/codex", ["login"], None, lambda name: None)
    assert caught.value.status == 409 and "No terminal" in str(caught.value)


def test_the_route_returns_409_when_no_linux_terminal_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: "/bin/codex" if name == "codex" else None)
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, start_worker=False, extra_hosts=("testserver",),
                     trusted_clients=("testclient",), signin_launcher=lambda spec: None, signin_platform="linux")
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/accounts/codex/sign-in")
    assert response.status_code == 409 and "No terminal" in response.json()["detail"]


# --- state machine through the routes -------------------------------------------------------------------------

def test_codex_launch_waits_then_succeeds_when_the_health_check_reports_signed_in(served):
    app, client, launched, settings, clock, tools = served
    assert client.get("/api/accounts/codex/sign-in").json() == {"state": "idle", "message": None}
    assert client.post("/api/accounts/codex/sign-in").json() == {"state": "waiting", "message": None}
    assert launched[0][:3] == ["open", "-a", "Terminal"] and Path(launched[0][3]).parent == settings.codex_home.parent / "sign-in"
    assert f"CODEX_HOME={shlex.quote(str(settings.codex_home))} /usr/local/bin/codex login" in Path(launched[0][3]).read_text()
    # Too soon: no check is made.
    assert client.get("/api/accounts/codex/sign-in").json()["state"] == "waiting" and tools["codex"].refreshes == 0
    clock.now += 3.1
    assert client.get("/api/accounts/codex/sign-in").json()["state"] == "waiting"
    assert tools["codex"].refreshes == 1
    # Within three seconds of the last check there is no second one.
    clock.now += 1
    client.get("/api/accounts/codex/sign-in")
    assert tools["codex"].refreshes == 1
    tools["codex"].signed_in = True
    clock.now += 3
    assert client.get("/api/accounts/codex/sign-in").json() == {"state": "succeeded", "message": None}


def test_claude_launch_runs_auth_login_and_succeeds(served):
    _, client, launched, _, clock, tools = served
    client.post("/api/accounts/claude/sign-in")
    assert "\n/usr/local/bin/claude auth login\n" in Path(launched[0][3]).read_text()
    tools["claude"].signed_in = True
    clock.now += 3.1
    assert client.get("/api/accounts/claude/sign-in").json()["state"] == "succeeded"


def test_a_sign_in_not_completed_in_ten_minutes_times_out(served):
    _, client, _, _, clock, _ = served
    client.post("/api/accounts/codex/sign-in")
    clock.now += 601
    done = client.get("/api/accounts/codex/sign-in").json()
    assert done["state"] == "timed_out" and "10 minutes" in done["message"]
    # A new launch is allowed afterwards.
    assert client.post("/api/accounts/codex/sign-in").json()["state"] == "waiting"


def test_a_second_post_while_waiting_opens_no_second_terminal(served):
    _, client, launched, _, _, _ = served
    first = client.post("/api/accounts/codex/sign-in").json()
    second = client.post("/api/accounts/codex/sign-in").json()
    assert first["state"] == second["state"] == "waiting" and len(launched) == 1
    assert client.post("/api/accounts/claude/sign-in").json()["state"] == "waiting" and len(launched) == 2


def test_a_failing_health_check_keeps_waiting(served):
    app, client, _, _, clock, tools = served

    async def broken(refresh=False):
        raise RuntimeError("app-server not ready")
    tools["codex"].health = broken
    client.post("/api/accounts/codex/sign-in")
    clock.now += 3.1
    assert client.get("/api/accounts/codex/sign-in").json()["state"] == "waiting"


def test_an_idle_codex_server_is_closed_before_the_check_but_a_busy_one_is_not(served):
    _, client, _, _, clock, tools = served
    codex = tools["codex"]
    codex._active = {("thread", "turn")}
    client.post("/api/accounts/codex/sign-in")
    clock.now += 3.1
    client.get("/api/accounts/codex/sign-in")
    assert codex.closed == 0 and codex.refreshes == 1
    codex._active = set()
    clock.now += 3.1
    client.get("/api/accounts/codex/sign-in")
    assert codex.closed == 1 and codex.refreshes == 2
    # Claude has no app-server to restart.
    client.post("/api/accounts/claude/sign-in")
    clock.now += 3.1
    client.get("/api/accounts/claude/sign-in")
    assert tools["claude"].closed == 0


def test_a_missing_executable_is_409_with_a_clear_message(served, monkeypatch):
    _, client, launched, _, _, _ = served
    monkeypatch.setattr(account_signin, "find_tool", lambda name: None)
    response = client.post("/api/accounts/claude/sign-in")
    assert response.status_code == 409 and "Claude Code was not found" in response.json()["detail"]
    assert launched == []


def test_a_launcher_that_cannot_start_is_409(served):
    app, client, _, _, _, _ = served

    def broken(spec):
        raise FileNotFoundError("open")
    app.state.account_signin._launcher = broken
    response = client.post("/api/accounts/codex/sign-in")
    assert response.status_code == 409 and "FileNotFoundError" in response.json()["detail"]
    assert client.get("/api/accounts/codex/sign-in").json()["state"] == "idle"


def test_unknown_tool_is_404_on_both_routes(served):
    _, client, _, _, _, _ = served
    assert client.post("/api/accounts/gemini/sign-in").status_code == 404
    assert client.get("/api/accounts/gemini/sign-in").status_code == 404


def test_post_without_csrf_is_rejected_and_opens_nothing(served):
    _, client, launched, _, _, _ = served
    bare = TestClient(client.app)
    response = bare.post("/api/accounts/codex/sign-in")
    assert response.status_code in (400, 403) and launched == []


def test_overlapping_checks_do_not_pile_up(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: f"/bin/{name}")
    clock, calls, gate = Clock(), [], None

    async def scenario():
        nonlocal gate
        gate = asyncio.Event()

        async def check(tool):
            calls.append(tool)
            await gate.wait()
            return True
        signin = account_signin.AccountSignIn(tmp_path / "home", check, lambda spec: None, "darwin", clock=clock)
        await signin.start("claude")
        clock.now += 4
        first = asyncio.create_task(signin.state("claude"))
        await asyncio.sleep(0)
        clock.now += 4
        assert (await signin.state("claude"))["state"] == "waiting"
        gate.set()
        return await first

    assert asyncio.run(scenario())["state"] == "succeeded" and calls == ["claude"]

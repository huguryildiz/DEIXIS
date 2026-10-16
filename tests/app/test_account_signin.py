"""Sign in to Codex and Claude Code from Settings (D21): the terminal launcher, the routes and the state machine.

A fake launcher stands in for the terminal and a fake health check for the tools; no real terminal opens and no CLI
runs. Passing shows the command lines built per platform, the state machine (waiting, succeeded, failed, timed out,
cancelled), that success needs this attempt's own exit code and a fresh health check (E8), cancel and re-attach (E20)
and the route guards. The macOS and Linux status lines are run with /bin/sh against a stand-in command; the Windows
one is only read as text. It says nothing about whether a real Terminal.app, PowerShell window or Linux terminal opens
with these commands, or what `codex login` and `claude auth login` ask.
"""

import asyncio
import base64
import shlex
import subprocess
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


def test_windows_starts_powershell_with_codex_home_set_inside_it():
    home = Path("C:/Users/Jo Q/AppData/codex-home")
    argv = build_launch("win32", "C:\\Program Files\\codex\\codex.exe", ["login"], home, which=lambda name: None)
    assert argv[:4] == ["powershell.exe", "-NoLogo", "-NoProfile", "-NoExit"] and argv[4] == "-EncodedCommand"
    script = base64.b64decode(argv[5]).decode("utf-16-le")
    assert "$env:CODEX_HOME = 'C:/Users/Jo Q/AppData/codex-home'; & 'C:\\Program Files\\codex\\codex.exe' 'login'" in script
    # More of this (the encoded script, hostile paths, no batch file) is in tests/hardening/test_windows_launch.py.


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


def test_claude_launch_runs_auth_login_and_succeeds(served):
    app, client, launched, _, _, tools = served
    client.post("/api/accounts/claude/sign-in")
    assert "\n/usr/local/bin/claude auth login\n" in Path(launched[0][3]).read_text()
    tools["claude"].signed_in = True
    finish(app, "claude")
    assert client.get("/api/accounts/claude/sign-in").json()["state"] == "succeeded"


def test_an_old_session_and_a_terminal_closed_at_once_is_not_a_success(served):
    app, client, _, _, clock, tools = served
    tools["claude"].signed_in = True  # the old session
    client.post("/api/accounts/claude/sign-in")
    for _ in range(3):  # the person closed the window: nothing is ever written; macOS cannot see that, so it waits on
        clock.now += 30
        assert client.get("/api/accounts/claude/sign-in").json()["state"] == "waiting"
    assert tools["claude"].refreshes == 0
    clock.now += 601
    assert client.get("/api/accounts/claude/sign-in").json()["state"] == "timed_out"


def test_a_closed_windows_terminal_without_a_status_leaves_the_old_session_standing(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: f"C:\\bin\\{name}.exe")
    window, signed_in = Window(), {"claude": True}

    async def check(tool):
        return signed_in[tool]
    signin = account_signin.AccountSignIn(tmp_path / "home", check, lambda spec: window, "win32", on_succeeded=lambda t: pytest.fail(t))
    asyncio.run(signin.start("claude"))
    assert asyncio.run(signin.state("claude"))["state"] == "waiting"  # window open, still logging in
    window.closed = True
    done = asyncio.run(signin.state("claude"))
    assert done == {"state": "failed", "message": "The sign-in was not completed; the existing session is still signed in."}
    # Without an old session the message does not claim one.
    signed_in["claude"] = False
    asyncio.run(signin.start("claude"))
    window.closed = True
    assert asyncio.run(signin.state("claude"))["message"] == "The sign-in was not completed."


def test_a_window_that_wrote_its_status_and_then_closed_still_counts_by_its_status(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: f"C:\\bin\\{name}.exe")
    window = Window()

    async def check(tool):
        return True
    signin = account_signin.AccountSignIn(tmp_path / "home", check, lambda spec: window, "win32")
    asyncio.run(signin.start("claude"))
    signin._run["claude"]["status"].write_text("0")
    window.closed = True
    assert asyncio.run(signin.state("claude"))["state"] == "succeeded"


def test_a_non_zero_exit_fails_even_when_health_says_signed_in(served):
    app, client, _, _, _, tools = served
    tools["codex"].signed_in = True
    client.post("/api/accounts/codex/sign-in")
    finish(app, "codex", "1")
    done = client.get("/api/accounts/codex/sign-in").json()
    assert done["state"] == "failed" and "ended with an error" in done["message"] and tools["codex"].refreshes == 0


def test_exit_0_with_health_not_signed_in_or_not_answering_is_a_failure_not_a_success(served):
    app, client, _, _, _, tools = served
    client.post("/api/accounts/codex/sign-in")
    finish(app, "codex")
    done = client.get("/api/accounts/codex/sign-in").json()
    assert done["state"] == "failed" and "does not show a signed-in account" in done["message"]

    async def broken(refresh=False):
        raise RuntimeError("app-server not ready")
    tools["claude"].health = broken
    client.post("/api/accounts/claude/sign-in")
    finish(app, "claude")
    assert client.get("/api/accounts/claude/sign-in").json()["state"] == "failed"


def test_an_unreadable_status_is_not_completed_and_says_whether_the_old_session_stands(served):
    app, client, _, _, _, tools = served
    tools["codex"].signed_in = True
    client.post("/api/accounts/codex/sign-in")
    finish(app, "codex", "garbled")
    assert client.get("/api/accounts/codex/sign-in").json() == {
        "state": "failed", "message": "The sign-in was not completed; the existing session is still signed in."}


def test_cancel_puts_the_connection_back_to_idle_removes_the_status_and_allows_a_new_attempt(served):
    app, client, launched, _, _, tools = served
    tools["codex"].signed_in = True
    client.post("/api/accounts/codex/sign-in")
    status = app.state.account_signin._run["codex"]["status"]
    status.write_text("0")
    assert client.post("/api/accounts/codex/sign-in/cancel").json() == {"state": "idle", "message": None}
    assert not status.exists() and client.get("/api/accounts/codex/sign-in").json()["state"] == "idle"
    assert tools["codex"].refreshes == 0  # the exit code of a cancelled attempt is never read
    assert client.get("/api/connections").json()["sign_ins"] == {}
    assert client.post("/api/accounts/codex/sign-in").json()["state"] == "waiting" and len(launched) == 2
    # Cancelling with nothing running changes nothing; an unknown tool is 404.
    assert client.post("/api/accounts/claude/sign-in/cancel").json()["state"] == "idle"
    assert client.post("/api/accounts/nope/sign-in/cancel").status_code == 404


def test_cancel_closes_the_windows_terminal_it_started(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: f"C:\\bin\\{name}.exe")
    window = Window()

    async def check(tool):
        return False
    signin = account_signin.AccountSignIn(tmp_path / "home", check, lambda spec: window, "win32")
    asyncio.run(signin.start("claude"))
    assert signin.cancel("claude")["state"] == "idle" and window.terminated


def test_a_reloaded_page_finds_the_running_sign_in_and_can_carry_on(served):
    app, client, _, _, _, tools = served
    assert client.get("/api/connections").json()["sign_ins"] == {}
    client.post("/api/accounts/claude/sign-in")
    # A fresh read of the connections (the page opened again) shows it still waiting; nothing was started twice.
    assert client.get("/api/connections").json()["sign_ins"] == {"claude": {"state": "waiting", "message": None}}
    tools["claude"].signed_in = True
    finish(app, "claude")
    assert client.get("/api/accounts/claude/sign-in").json()["state"] == "succeeded"
    assert client.get("/api/connections").json()["sign_ins"]["claude"]["state"] == "succeeded"


# --- the status lines the terminal scripts really run ----------------------------------------------------------

@pytest.mark.parametrize("code", [0, 3])
def test_the_mac_command_file_writes_the_exit_code_of_the_login_command(tmp_path, code):
    status = tmp_path / "status-x.exit"
    argv = build_launch("darwin", "/bin/sh", ["-c", f"exit {code}"], None, script_dir=tmp_path, status_file=status)
    subprocess.run(["sh", argv[-1]], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    assert status.read_text() == str(code) and not (tmp_path / "status-x.exit.tmp").exists()
    assert account_signin.read_exit_code(status) == code


@pytest.mark.parametrize("code", [0, 7])
def test_the_linux_script_writes_the_exit_code_of_the_login_command(tmp_path, code):
    status = tmp_path / "it's a status.exit"
    present = {"xterm": "/usr/bin/xterm"}
    argv = build_launch("linux", "/bin/sh", ["-c", f"exit {code}"], None, present.get, status_file=status)
    subprocess.run(argv[2:], stdin=subprocess.DEVNULL, capture_output=True)  # sh -c <script>
    assert status.read_text() == str(code)


def test_the_windows_script_saves_the_exit_code_and_nothing_goes_through_cmd():
    status = Path("C:/Users/Jo Q/it's/status.exit")
    argv = build_launch("win32", "C:\\bin\\codex.exe", ["login"], None, which=lambda n: None, status_file=status)
    script = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert "& 'C:\\bin\\codex.exe' 'login'; $deixisCode = $LASTEXITCODE;" in script
    assert "-LiteralPath 'C:/Users/Jo Q/it''s/status.exit.tmp'" in script and "-Destination 'C:/Users/Jo Q/it''s/status.exit' -Force" in script
    assert "-Value $deixisCode -NoNewline" in script


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


def test_an_idle_codex_server_is_closed_before_the_check_but_a_busy_one_is_not(served):
    app, client, _, _, _, tools = served
    codex = tools["codex"]
    codex._active = {("thread", "turn")}
    client.post("/api/accounts/codex/sign-in")
    finish(app, "codex")
    client.get("/api/accounts/codex/sign-in")
    assert codex.closed == 0 and codex.refreshes == 1
    codex._active = set()
    client.post("/api/accounts/codex/sign-in")
    finish(app, "codex")
    client.get("/api/accounts/codex/sign-in")
    assert codex.closed == 1 and codex.refreshes == 2
    # Claude has no app-server to restart.
    client.post("/api/accounts/claude/sign-in")
    finish(app, "claude")
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
        signin._run["claude"]["status"].write_text("0")
        first = asyncio.create_task(signin.state("claude"))
        await asyncio.sleep(0)
        assert (await signin.state("claude"))["state"] == "waiting"
        gate.set()
        return await first

    assert asyncio.run(scenario())["state"] == "succeeded" and calls == ["claude"]


def test_a_cancel_during_the_final_check_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(account_signin, "find_tool", lambda name: f"/bin/{name}")

    async def scenario():
        gate = asyncio.Event()

        async def check(tool):
            await gate.wait()
            return True
        signin = account_signin.AccountSignIn(tmp_path / "home", check, lambda spec: None, "darwin")
        await signin.start("claude")
        signin._run["claude"]["status"].write_text("0")
        pending = asyncio.create_task(signin.state("claude"))
        await asyncio.sleep(0)
        signin.cancel("claude")
        gate.set()
        return await pending

    assert asyncio.run(scenario()) == {"state": "idle", "message": None}

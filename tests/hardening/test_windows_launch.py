"""Starting the command-line tools on Windows without a batch file, and the Codex login command per shell (pre-P10 A4, B2).

The Windows branches run on this computer with `sys.platform` patched and fake files laid out like an npm install; no
Windows process is started. Passing shows which argv each install type gets and that no batch file or `cmd.exe` is in
it. It does not show that a real Windows machine starts Codex, Gemini, Copilot or Claude Code that way (P10a/P10b)."""

import asyncio
import base64
from pathlib import Path

import pytest

from deixis.keys import account_signin
from deixis.tools import tool_paths
from deixis.keys.account_signin import AccountSignIn, SignInError, build_launch, codex_login_command, powershell_quote
from deixis.models import adapter, claude, copilot_cli, gemini_cli
from deixis.tools.tool_paths import command_for
from deixis.tools import tool_probe

HOSTILE = "a&b %x% ^c (d) !e"  # cmd.exe metacharacters and a space in one folder name

SHIM = '''@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0

IF EXIST "%dp0%\\node.exe" (
  SET "_prog=%dp0%\\node.exe"
) ELSE (
  SET "_prog=node"
  SET PATHEXT=%PATHEXT:;.JS;=;%
)

endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\{entry}" %*
'''


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(tool_paths.sys, "platform", "win32")  # the same module object everywhere
    monkeypatch.setattr(tool_paths.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(tool_paths, "find_tool", lambda name: None)  # no node on the search path unless a test adds one


def touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def npm_install(folder: Path, name: str, entry: str, node: bool = True) -> Path:
    """What `npm install -g` leaves on Windows: <name>.cmd, the script it names, and node.exe when npm brought it."""
    touch(folder / f"{name}.cmd", SHIM.format(entry=entry))
    touch(folder / Path(*entry.split("\\")))
    if node:
        touch(folder / "node.exe")
    return folder / f"{name}.cmd"


def no_batch(argv: list[str]) -> bool:
    return not any(Path(part).suffix.lower() in (".cmd", ".bat") or Path(part).name.lower() == "cmd.exe" for part in argv)


def test_posix_runs_the_found_file_as_it_is():
    assert command_for("codex", "/opt/homebrew/bin/codex").argv == ["/opt/homebrew/bin/codex"]
    assert command_for("codex", None).found is None and command_for("codex", None).argv == []


# --- the three cases per CLI --------------------------------------------------------------------------------------

def test_codex_native_exe_found_by_the_path_search_is_used(windows, tmp_path):
    exe = touch(tmp_path / "codex.exe")
    assert command_for("codex", str(exe)).argv == [str(exe)]


def test_codex_batch_launcher_uses_the_native_binary_its_package_ships(windows, tmp_path):
    launcher = npm_install(tmp_path, "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    other = touch(tmp_path / "node_modules/@openai/codex/node_modules/@openai/codex-win32-arm64/vendor/aarch64-pc-windows-msvc/codex/codex.exe")
    native = touch(tmp_path / "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/codex/codex.exe")
    command = command_for("codex", str(launcher))
    assert command.argv == [str(native)] and command.problem is None and other.is_file()


def test_codex_without_a_native_binary_runs_node_on_the_script_the_launcher_names(windows, tmp_path):
    launcher = npm_install(tmp_path, "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    command = command_for("codex", str(launcher))
    assert command.argv == [str(tmp_path / "node.exe"), str(tmp_path / "node_modules/@openai/codex/bin/codex.js")]
    assert no_batch(command.argv)


def test_node_comes_from_the_path_search_when_npm_did_not_bring_it(windows, tmp_path, monkeypatch):
    node = touch(tmp_path / "program files" / "nodejs" / "node.exe")
    monkeypatch.setattr(tool_paths, "find_tool", lambda name: str(node) if name == "node" else None)
    launcher = npm_install(tmp_path / "npm", "gemini", "node_modules\\@google\\gemini-cli\\bundle\\gemini.js", node=False)
    assert command_for("gemini", str(launcher)).argv == [str(node), str(tmp_path / "npm/node_modules/@google/gemini-cli/bundle/gemini.js")]


def test_a_launcher_with_no_native_binary_no_script_or_no_node_is_not_supported(windows, tmp_path, monkeypatch):
    missing_script = touch(tmp_path / "one" / "gemini.cmd", SHIM.format(entry="node_modules\\gone\\gemini.js"))
    touch(tmp_path / "one" / "node.exe")
    unreadable = touch(tmp_path / "two" / "gemini.cmd", "@echo off\r\nsome other launcher\r\n")
    no_node = npm_install(tmp_path / "three", "gemini", "bin\\gemini.js", node=False)
    for launcher in (missing_script, unreadable, no_node):
        command = command_for("gemini", str(launcher))
        assert command.argv == [] and command.found == str(launcher)
        assert "isn't supported on Windows" in command.problem
    # A node that is itself a batch file is no better.
    batch_node = touch(tmp_path / "bat" / "node.cmd")
    monkeypatch.setattr(tool_paths, "find_tool", lambda name: str(batch_node))
    assert command_for("gemini", str(no_node)).argv == []
    # Any other kind of file (a PowerShell script, no extension) is not run either.
    assert command_for("codex", str(touch(tmp_path / "codex.ps1"))).argv == []


def test_claude_uses_only_a_native_exe_and_says_so_about_the_npm_shim(windows, tmp_path):
    exe = touch(tmp_path / "claude.exe")
    assert command_for("claude", str(exe)).argv == [str(exe)]
    shim = npm_install(tmp_path / "npm", "claude", "node_modules\\@anthropic-ai\\claude-code\\cli.js")
    command = command_for("claude", str(shim))
    assert command.argv == [] and "Claude Code install type isn't supported on Windows" in command.problem
    assert "native installer" in command.problem


@pytest.mark.parametrize("name,entry", [("codex", "node_modules\\@openai\\codex\\bin\\codex.js"),
                                        ("gemini", "node_modules\\@google\\gemini-cli\\bundle\\gemini.js"),
                                        ("copilot", "node_modules\\@github\\copilot\\npm-loader.js")])
def test_a_path_with_batch_metacharacters_never_reaches_a_batch_file(windows, tmp_path, name, entry):
    launcher = npm_install(tmp_path / HOSTILE, name, entry)
    argv = command_for(name, str(launcher)).argv
    assert argv and no_batch(argv)
    assert argv[0].endswith("node.exe") and HOSTILE in argv[1]


# --- the adapters -------------------------------------------------------------------------------------------------

def test_claude_health_and_steps_refuse_the_npm_shim_and_use_the_exe(windows, tmp_path, monkeypatch):
    shim = npm_install(tmp_path / "npm", "claude", "node_modules\\@anthropic-ai\\claude-code\\cli.js")
    exe = touch(tmp_path / "native" / "claude.exe")
    probed = []

    async def version(argv, timeout=None, env=None):
        probed.append(argv)
        return tool_probe.Probe(error="not_responding")

    monkeypatch.setattr(claude, "probe", version)
    connection = claude.ClaudeCodeAdapter(tmp_path / "w")
    monkeypatch.setattr(claude, "find_tool", lambda name: str(shim))
    status = asyncio.run(connection.health(refresh=True))
    assert (status["installed"], status["ready"], status["reason_code"]) == (True, False, "unsupported_install")
    assert "isn't supported on Windows" in status["reason"] and probed == []
    step = asyncio.run(connection.run_step("B", "D", "M", {}, "opus"))
    assert (step.status, step.delivery_class) == ("unavailable", "before_send") and "isn't supported on Windows" in step.error
    monkeypatch.setattr(claude, "find_tool", lambda name: str(exe))
    asyncio.run(connection.health(refresh=True))
    assert probed == [[str(exe), "--version"]]


def test_codex_health_runs_the_node_script_and_reports_an_unsupported_install(windows, tmp_path, monkeypatch):
    launcher = npm_install(tmp_path / "npm", "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    probed = []

    async def version(argv, timeout=None, env=None):
        probed.append(argv)
        return tool_probe.Probe(error="not_responding")

    monkeypatch.setattr(adapter, "probe", version)
    monkeypatch.setattr(adapter, "find_tool", lambda name: str(launcher))
    connection = adapter.CodexAdapter(tmp_path / "home", tmp_path / "workspace")
    asyncio.run(connection.health(refresh=True))
    assert probed == [[str(tmp_path / "npm/node.exe"), str(tmp_path / "npm/node_modules/@openai/codex/bin/codex.js"), "--version"]]
    bare = touch(tmp_path / "bare" / "codex.cmd", "@echo off\r\n")
    monkeypatch.setattr(adapter, "find_tool", lambda name: str(bare))
    status = asyncio.run(connection.health(refresh=True))
    assert status["reason_code"] == "unsupported_install" and len(probed) == 1
    with pytest.raises(OSError, match="isn't supported on Windows"):
        asyncio.run(connection._ensure_server())


def test_gemini_and_copilot_adapters_start_node_or_the_native_exe(windows, tmp_path, monkeypatch):
    launcher = npm_install(tmp_path / "npm", "gemini", "node_modules\\@google\\gemini-cli\\bundle\\gemini.js")
    monkeypatch.setattr(gemini_cli, "find_tool", lambda name: str(launcher))
    seen = []

    async def runner(argv, env, cwd, stdin, timeout):
        seen.append(argv)
        return gemini_cli.CliRun(0, "", "")

    connection = gemini_cli.GeminiCliAdapter(tmp_path / "g", runner=runner, credentials=touch(tmp_path / "creds.json", "{}"))
    asyncio.run(connection.run_step("B", "D", "M", {}, "gemini-x"))
    assert seen[0][:2] == [str(tmp_path / "npm/node.exe"), str(tmp_path / "npm/node_modules/@google/gemini-cli/bundle/gemini.js")]
    assert seen[0][2:4] == ["-m", "gemini-x"] and no_batch(seen[0])

    # Copilot: the native exe next to the package, else node on npm-loader.js, else not supported.
    shim = npm_install(tmp_path / "cp", "copilot", "node_modules\\@github\\copilot\\npm-loader.js")
    monkeypatch.setattr(copilot_cli, "find_tool", lambda name: str(shim))
    cp = copilot_cli.CopilotCliAdapter(tmp_path / "h", tmp_path / "w")
    assert cp._command() == [str(tmp_path / "cp/node.exe"), str(tmp_path / "cp/node_modules/@github/copilot/npm-loader.js")]
    exe = touch(tmp_path / "cp/node_modules/@github/copilot/node_modules/@github/copilot-win32-x64/copilot.exe")
    assert cp._command() == [str(exe)]
    bare = touch(tmp_path / "bare" / "copilot.cmd", "@echo off\r\n")
    monkeypatch.setattr(copilot_cli, "find_tool", lambda name: str(bare))
    status = asyncio.run(cp.health(refresh=True))
    assert (status["installed"], status["reason_code"]) == (True, "unsupported_install")


# --- the sign-in terminal -----------------------------------------------------------------------------------------

def script_of(argv: list[str]) -> str:
    assert argv[-2] == "-EncodedCommand"
    return base64.b64decode(argv[-1]).decode("utf-16-le")


def test_windows_sign_in_hands_powershell_an_encoded_script_and_no_cmd_line():
    home = Path(f"C:/Users/{HOSTILE}/it's/codex-home")
    argv = build_launch("win32", f"C:\\{HOSTILE}\\node.exe", [f"C:\\{HOSTILE}\\o'brien\\codex.js", "login"], home, which=lambda n: None)
    assert argv[0] == "powershell.exe" and "-NoExit" in argv and no_batch(argv)
    script = script_of(argv)
    assert f"$env:CODEX_HOME = 'C:/Users/{HOSTILE}/it''s/codex-home'" in script
    assert script.endswith(f"& 'C:\\{HOSTILE}\\node.exe' 'C:\\{HOSTILE}\\o''brien\\codex.js' 'login'")
    plain = script_of(build_launch("win32", "C:\\bin\\claude.exe", ["auth", "login"], None, which=lambda n: "C:\\ps\\powershell.exe"))
    assert "CODEX_HOME" not in plain and plain.endswith("& 'C:\\bin\\claude.exe' 'auth' 'login'")
    # The argv words are plain: nothing in them for any shell to read.
    assert all(not set("&|<>^%\"") & set(part) for part in argv)


def test_windows_sign_in_route_runs_node_on_the_script_and_refuses_the_claude_shim(windows, tmp_path, monkeypatch):
    launcher = npm_install(tmp_path / "npm", "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    shim = npm_install(tmp_path / "npm2", "claude", "node_modules\\@anthropic-ai\\claude-code\\cli.js")
    found = {"codex": str(launcher), "claude": str(shim)}
    monkeypatch.setattr(account_signin, "find_tool", found.get)
    monkeypatch.setattr(tool_paths.shutil, "which", lambda *args, **kwargs: None)  # build_launch looks for powershell.exe
    launched = []

    async def check(tool):
        return False

    sign_in = AccountSignIn(tmp_path / "codex-home", check, launched.append, platform="win32")
    asyncio.run(sign_in.start("codex"))
    script = script_of(launched[0])
    assert f"& '{tmp_path / 'npm/node.exe'}' '{tmp_path / 'npm/node_modules/@openai/codex/bin/codex.js'}' 'login'" in script
    with pytest.raises(SignInError) as caught:
        asyncio.run(sign_in.start("claude"))
    assert caught.value.status == 409 and "isn't supported on Windows" in str(caught.value) and len(launched) == 1


# --- B2: the command a person pastes ------------------------------------------------------------------------------

def test_the_codex_login_command_is_written_for_the_shell_of_each_system():
    assert codex_login_command("darwin", Path("/Users/jo/Library/Application Support/DEIXIS/codex-home")) == \
        "CODEX_HOME='/Users/jo/Library/Application Support/DEIXIS/codex-home' codex login"
    assert codex_login_command("linux", Path("/home/o'neil/home")) == "CODEX_HOME='/home/o'\\''neil/home' codex login"
    assert codex_login_command("win32", Path("C:/Users/Jo Q/AppData/codex-home")) == \
        "$env:CODEX_HOME='C:/Users/Jo Q/AppData/codex-home'; codex login"
    assert codex_login_command("win32", Path("C:/Users/O'Neil/h")) == "$env:CODEX_HOME='C:/Users/O''Neil/h'; codex login"


def test_powershell_quote_doubles_every_quote_it_reads_and_expands_nothing():
    assert powershell_quote("a'b\u2018c\u2019d\u201ae\u201bf") == "'a''b\u2018\u2018c\u2019\u2019d\u201a\u201ae\u201b\u201bf'"
    assert powershell_quote("$env:X `n $(calc)") == "'$env:X `n $(calc)'"


def test_the_connections_route_carries_the_command_for_the_systems_shell(tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from deixis.api.app import create_app
    from deixis.config import Settings

    for platform, start in (("darwin", "CODEX_HOME='"), ("win32", "$env:CODEX_HOME='")):
        settings = Settings(data_dir=tmp_path / platform, port=8765)
        app = create_app(settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
                         start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",), signin_platform=platform)
        with TestClient(app) as client:
            command = client.get("/api/connections").json()["codex_login_command"]
        assert command.startswith(start) and command.endswith("codex login") and str(settings.codex_home) in command


# --- review round 1: absolute paths, the exact architecture, a console that owns its streams ------------------------

def test_a_launcher_found_through_a_relative_path_gives_absolute_argv(windows, tmp_path, monkeypatch):
    npm_install(tmp_path / "npm", "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(tmp_path)
    command = command_for("codex", "npm/codex.cmd")  # what shutil.which returns for a relative PATH entry
    assert command.argv == [str(tmp_path / "npm/node.exe"), str(tmp_path / "npm/node_modules/@openai/codex/bin/codex.js")]
    monkeypatch.chdir(elsewhere)  # the child's folder is another one: nothing in argv depends on it
    assert all(Path(part).is_absolute() and Path(part).is_file() for part in command.argv)
    assert command_for("codex", "../npm/codex.cmd").argv == command.argv
    monkeypatch.chdir(tmp_path)
    touch(tmp_path / "native" / "claude.exe")
    assert command_for("claude", "native/claude.exe").argv == [str(tmp_path / "native/claude.exe")]
    # A relative node from the search path is made absolute too.
    (tmp_path / "npm" / "node.exe").unlink()
    touch(tmp_path / "bin" / "node.exe")
    monkeypatch.setattr(tool_paths, "find_tool", lambda name: "bin/node.exe")
    assert command_for("codex", "npm/codex.cmd").argv[0] == str(tmp_path / "bin/node.exe")


def codex_vendor(root: Path, package: str, triple: str) -> Path:
    return touch(root / "node_modules/@openai" / package / "vendor" / triple / "codex/codex.exe")


def test_only_the_binary_for_the_running_machine_is_used(windows, tmp_path, monkeypatch):
    launcher = npm_install(tmp_path, "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    node_script = [str(tmp_path / "node.exe"), str(tmp_path / "node_modules/@openai/codex/bin/codex.js")]
    arm = codex_vendor(tmp_path, "codex-win32-arm64", "aarch64-pc-windows-msvc")
    # An x64 machine with only the ARM64 binary falls back to node, as does a machine of a kind with no build.
    assert command_for("codex", str(launcher)).argv == node_script
    monkeypatch.setattr(tool_paths.platform, "machine", lambda: "x86")
    assert command_for("codex", str(launcher)).argv == node_script
    monkeypatch.setattr(tool_paths.platform, "machine", lambda: "ARM64")
    assert command_for("codex", str(launcher)).argv == [str(arm)]
    x64 = codex_vendor(tmp_path, "codex-win32-x64", "x86_64-pc-windows-msvc")
    monkeypatch.setattr(tool_paths.platform, "machine", lambda: "AMD64")
    assert command_for("codex", str(launcher)).argv == [str(x64)]


def test_the_architecture_in_a_parent_folder_name_does_not_skew_the_pick(windows, tmp_path, monkeypatch):
    # The whole install sits under a folder called x86_64; only the ARM64 build is there, and an x64 machine must not take it.
    root = tmp_path / "x86_64 tools"
    launcher = npm_install(root, "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    codex_vendor(root, "codex-win32-arm64", "aarch64-pc-windows-msvc")
    assert command_for("codex", str(launcher)).argv[0] == str(root / "node.exe")
    # And an install under an aarch64 folder takes the x64 build on an x64 machine.
    other = tmp_path / "aarch64 tools"
    launcher = npm_install(other, "codex", "node_modules\\@openai\\codex\\bin\\codex.js")
    codex_vendor(other, "codex-win32-arm64", "aarch64-pc-windows-msvc")
    x64 = codex_vendor(other, "codex-win32-x64", "x86_64-pc-windows-msvc")
    assert command_for("codex", str(launcher)).argv == [str(x64)]


def test_the_sign_in_console_owns_its_standard_streams(monkeypatch):
    calls = []
    monkeypatch.setattr(account_signin.sys, "platform", "win32")
    monkeypatch.setattr(account_signin.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(account_signin.subprocess, "Popen", lambda spec, **kwargs: calls.append((spec, kwargs)))
    account_signin.start_process(["powershell.exe", "-NoExit"])
    assert calls == [(["powershell.exe", "-NoExit"], {"creationflags": 0x10})]

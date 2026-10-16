"""Sign in to Codex and Claude Code from Settings (D21).

DEIXIS opens a visible terminal window on the person's computer and runs the tool's own login command in it, so the
person sees the CLI's prompts and answers them there. Nothing is copied or read: the tool writes its own credentials
where it always does (Codex into the DEIXIS Codex home, Claude Code into its usual place). The terminal script writes
the login command's exit code to a status file of this one attempt (E8); only a finished command, followed by a fresh
health check that says signed in, counts as a sign-in. A closed terminal, an unreadable status or a health check that
cannot answer never counts as one: an account that was already signed in stays signed in, and the person is told so.
"""

from __future__ import annotations

import asyncio
import base64
import re
import shlex
import tempfile
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from deixis.tool_paths import command_for, find_tool

SIGNIN_TIMEOUT_SECONDS = 10 * 60
TOOLS = {"codex": ("codex", ["login"], "Codex CLI"), "claude": ("claude", ["auth", "login"], "Claude Code"),
         "copilot_cli": ("copilot", ["login"], "GitHub Copilot CLI"),
         "gemini_cli": ("gemini", [], "Gemini CLI")}
LINUX_TERMINALS = ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm")

# What is handed to the process starter: an argument list. Nothing is ever parsed by cmd.exe (A4).
LaunchSpec = list[str]
# Returns a handle with `poll()` when the launched process is the terminal window itself (Windows), else None.
Launcher = Callable[[LaunchSpec], Any]
# Asks the tool's own health check whether it is signed in.
Check = Callable[[str], Awaitable[bool]]


class SignInError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def start_process(spec: LaunchSpec) -> Any:
    """Start the terminal launcher and let it go; its window belongs to the person from here on."""
    if sys.platform == "win32":
        # PowerShell is a console program: its new window owns the standard streams, so the prompts and errors of the
        # login show there. They are not redirected. The process is the window, so its end means the window was closed.
        return subprocess.Popen(spec, creationflags=subprocess.CREATE_NEW_CONSOLE)
    # On macOS `open` hands the script to Terminal.app and ends; on Linux the terminal program may fork away. Neither
    # process is the window, so a closed window cannot be seen here; cancel and the timeout are what end that wait.
    subprocess.Popen(spec, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return None


def _shell_line(exe: str, args: list[str], codex_home: Path | None) -> str:
    line = " ".join(shlex.quote(part) for part in (exe, *args))
    return f"CODEX_HOME={shlex.quote(str(codex_home))} {line}" if codex_home else line


def powershell_quote(text: str) -> str:
    """A PowerShell single-quoted string: nothing inside is expanded. A single quote is doubled, and so are the curly
    ones PowerShell also reads as quotes (U+2018, U+2019, U+201A, U+201B)."""
    return "'" + re.sub("([\u2018\u2019\u201a\u201b'])", r"\1\1", text) + "'"


def codex_login_command(platform: str, codex_home: Path) -> str:
    """The command a person pastes into their own terminal to sign in to the DEIXIS Codex home (B2)."""
    if platform == "win32":
        return f"$env:CODEX_HOME={powershell_quote(str(codex_home))}; codex login"
    quoted = str(codex_home).replace("'", "'\\''")  # close the quote, an escaped quote, reopen
    return f"CODEX_HOME='{quoted}' codex login"


def _posix_status_line(status_file: Path | None) -> str:
    """Shell lines that save the exit code of the command just run, written whole and moved into place."""
    if not status_file:
        return ""
    tmp = shlex.quote(str(status_file) + ".tmp")
    return f"deixis_code=$?; printf '%s' \"$deixis_code\" > {tmp} && mv -f {tmp} {shlex.quote(str(status_file))}\n"


def build_launch(platform: str, exe: str, args: list[str], codex_home: Path | None,
                 which: Callable[[str], str | None] = find_tool, script_dir: Path | None = None,
                 status_file: Path | None = None) -> LaunchSpec:
    """The command that opens a terminal window running `exe args`, with CODEX_HOME set when given. With a status
    file, the script writes the command's exit code there when the command ends (E8)."""
    if platform == "darwin":
        # Terminal.app opens a .command file through `open`, which needs no Automation permission (osascript
        # driving Terminal does, and timed out while macOS waited on that prompt). The file removes itself.
        script_dir = script_dir or Path(tempfile.gettempdir())
        script_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = script_dir / f"deixis-sign-in-{Path(exe).name}.command"
        path.write_text(f"#!/bin/sh\nrm -f \"$0\"\n{_shell_line(exe, args, codex_home)}\n{_posix_status_line(status_file)}"
                        "printf '\\nYou can close this window.\\n'\n")
        path.chmod(0o700)
        return ["open", "-a", "Terminal", str(path)]
    if platform == "win32":
        # PowerShell runs a script it is handed encoded, so no path or argument passes through cmd.exe's parsing, and
        # -NoExit keeps the window open for the person after the tool ends. exe is a native program or node.exe.
        script = "$Host.UI.RawUI.WindowTitle = 'DEIXIS sign-in'; "
        if codex_home:
            script += f"$env:CODEX_HOME = {powershell_quote(str(codex_home))}; "
        script += "& " + " ".join(powershell_quote(part) for part in (exe, *args))
        if status_file:
            tmp = powershell_quote(str(status_file) + ".tmp")
            script += (f"; $deixisCode = $LASTEXITCODE; if ($null -eq $deixisCode) {{ $deixisCode = 1 }}; "
                       f"Set-Content -LiteralPath {tmp} -Value $deixisCode -NoNewline; "
                       f"Move-Item -LiteralPath {tmp} -Destination {powershell_quote(str(status_file))} -Force")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return [which("powershell.exe") or "powershell.exe", "-NoLogo", "-NoProfile", "-NoExit", "-EncodedCommand", encoded]
    save = _posix_status_line(status_file).replace("\n", "; ")
    script = f"{_shell_line(exe, args, codex_home)}; {save}printf '\\nPress Enter to close this window. '; read _"
    for terminal in LINUX_TERMINALS:
        path = which(terminal)
        if path:
            separator = "--" if terminal == "gnome-terminal" else "-e"
            return [path, separator, "sh", "-c", script]
    raise SignInError(409, "No terminal program was found on this computer; run the sign-in command in a terminal yourself")


UNREADABLE = object()  # a status file that exists but holds no exit code


def read_exit_code(path: Path) -> Any:
    """The exit code the terminal script wrote: an int, None while the file is not there, UNREADABLE otherwise."""
    try:
        text = path.read_text(encoding="utf-8-sig").strip()  # Windows PowerShell may write a BOM
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return UNREADABLE
    try:
        return int(text)
    except ValueError:
        return UNREADABLE


class AccountSignIn:
    def __init__(self, codex_home: Path, check: Check, launcher: Launcher | None = None, platform: str | None = None,
                 timeout: float = SIGNIN_TIMEOUT_SECONDS, clock: Callable[[], float] = time.monotonic,
                 on_succeeded: Callable[[str], None] | None = None):
        self._codex_home = codex_home
        self._check = check
        self._launcher = launcher or start_process
        self._platform = platform or sys.platform
        self._timeout, self._clock = timeout, clock
        self._on_succeeded = on_succeeded
        self._state: dict[str, dict[str, Any]] = {}
        # Per tool: deadline, whether a start or a check is in flight, this attempt's status file and terminal handle.
        self._run: dict[str, dict[str, Any]] = {}

    def codex_login_command(self) -> str:
        return codex_login_command(self._platform, self._codex_home)

    def _view(self, tool: str) -> dict[str, Any]:
        return dict(self._state.get(tool) or {"state": "idle", "message": None})

    def views(self) -> dict[str, dict[str, Any]]:
        """The state of every tool that has one now, read without touching anything: what a reloaded page re-attaches to."""
        return {tool: self._view(tool) for tool in self._state}

    @staticmethod
    def _known(tool: str) -> None:
        if tool not in TOOLS:
            raise SignInError(404, f"Unknown account sign-in '{tool}'")

    @staticmethod
    def _forget(run: dict[str, Any] | None) -> None:
        """Remove this attempt's status file; the attempt is over, whatever it ended in."""
        if run and run.get("status"):
            for name in (run["status"], run["status"].with_name(run["status"].name + ".tmp")):
                name.unlink(missing_ok=True)

    def _finish(self, tool: str, state: str, message: str | None) -> None:
        self._state[tool] = {"state": state, "message": message}
        self._forget(self._run.pop(tool, None))
        if state == "succeeded" and self._on_succeeded:
            self._on_succeeded(tool)

    async def start(self, tool: str) -> dict[str, Any]:
        self._known(tool)
        if self._view(tool)["state"] == "waiting":
            return self._view(tool)
        # Reserved before the first await, so two requests at once open one terminal; "busy" keeps the health check
        # from reading a sign-in that is not open yet.
        previous = (self._state.get(tool), self._run.get(tool))
        now = self._clock()
        status_dir = self._codex_home.parent / "sign-in"
        status = status_dir / f"status-{tool}-{uuid.uuid4().hex}.exit"  # one per attempt; holds an exit code only
        reserved = {"deadline": now + self._timeout, "busy": True, "starting": True, "status": status, "handle": None}
        self._state[tool] = {"state": "waiting", "message": None}
        self._run[tool] = reserved
        try:
            binary, args, name = TOOLS[tool]
            found = await asyncio.to_thread(find_tool, binary)
            if not found:
                raise SignInError(409, f"{name} was not found on this computer; install it first")
            command = command_for(binary, found)
            if not command.argv:
                raise SignInError(409, command.problem or f"{name} cannot be started on this computer")
            if tool == "codex":
                self._codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
            status_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for stale in status_dir.glob(f"status-{tool}-*"):  # left by an attempt that never cleaned up
                stale.unlink(missing_ok=True)
            spec = build_launch(self._platform, command.argv[0], [*command.argv[1:], *args],
                                self._codex_home if tool == "codex" else None,
                                script_dir=status_dir, status_file=status)
            try:
                reserved["handle"] = self._launcher(spec)
            except OSError as exc:
                raise SignInError(409, f"A terminal window could not be opened: {type(exc).__name__}") from exc
        except BaseException:
            for table, old in ((self._state, previous[0]), (self._run, previous[1])):
                if old is None:
                    table.pop(tool, None)
                else:
                    table[tool] = old
            raise
        now = self._clock()
        reserved.update(deadline=now + self._timeout, busy=False, starting=False)
        return self._view(tool)

    def cancel(self, tool: str) -> dict[str, Any]:
        """Stop waiting for a running sign-in and put the connection back as it was: idle, whatever session it had stays."""
        self._known(tool)
        run = self._run.get(tool)
        if self._view(tool)["state"] != "waiting" or run is None or run["starting"]:
            return self._view(tool)
        self._state.pop(tool, None)
        self._run.pop(tool, None)
        self._forget(run)
        handle = run["handle"]
        if handle is not None and self._platform == "win32":  # the process is the window itself; elsewhere it is not ours
            try:
                handle.terminate()
            except Exception:
                pass
        return self._view(tool)

    async def _not_completed(self, tool: str) -> str:
        """The sign-in did not finish. Says whether an earlier session is still in place, as the tool itself reports it."""
        try:
            still_signed_in = await self._check(tool)
        except Exception:
            still_signed_in = False
        return ("The sign-in was not completed; the existing session is still signed in." if still_signed_in
                else "The sign-in was not completed.")

    async def state(self, tool: str) -> dict[str, Any]:
        """The state. While waiting, this is also what reads the attempt's status file: nothing else ends the wait
        except the timeout, a cancel, and (Windows only) the terminal window going away without a status."""
        self._known(tool)
        record, run = self._state.get(tool), self._run.get(tool)
        if not record or record["state"] != "waiting" or run is None or run["busy"]:
            return self._view(tool)
        if self._clock() >= run["deadline"]:
            self._finish(tool, "timed_out", "The sign-in was not completed within 10 minutes.")
            return self._view(tool)
        code = read_exit_code(run["status"])
        if code is None:
            handle = run["handle"]
            if self._platform != "win32" or handle is None or handle.poll() is None:
                return self._view(tool)
            # The window is gone. It wrote its status before it ended, so look once more before calling it closed.
            code = read_exit_code(run["status"])
            if code is None:
                code = UNREADABLE
        run["busy"] = True
        try:
            if code is UNREADABLE:
                message = await self._not_completed(tool)
                outcome = ("failed", message)
            elif code != 0:
                outcome = ("failed", "The sign-in command ended with an error.")
            else:
                try:
                    signed_in = await self._check(tool)
                except Exception:  # a health check that cannot answer is not a sign-in
                    signed_in = False
                outcome = (("succeeded", None) if signed_in else
                           ("failed", "The sign-in command finished, but the tool does not show a signed-in account yet."))
        finally:
            run["busy"] = False
        if self._run.get(tool) is run and self._state.get(tool) is record:  # not cancelled or restarted meanwhile
            self._finish(tool, *outcome)
        return self._view(tool)

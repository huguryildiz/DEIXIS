"""Sign in to Codex and Claude Code from Settings (D21).

DEIXIS opens a visible terminal window on the person's computer and runs the tool's own login command in it, so the
person sees the CLI's prompts and answers them there. Nothing is copied or read: the tool writes its own credentials
where it always does (Codex into the DEIXIS Codex home, Claude Code into its usual place). Whether the sign-in worked
is not read from the terminal; it is asked of the tool's own health check, at most every few seconds while waiting.
"""

from __future__ import annotations

import asyncio
import shlex
import tempfile
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from deixis.tool_paths import find_tool

SIGNIN_TIMEOUT_SECONDS = 10 * 60
CHECK_INTERVAL_SECONDS = 3.0
TOOLS = {"codex": ("codex", ["login"], "Codex CLI"), "claude": ("claude", ["auth", "login"], "Claude Code"),
         "copilot_cli": ("copilot", ["login"], "GitHub Copilot CLI"),
         "gemini_cli": ("gemini", [], "Gemini CLI")}
LINUX_TERMINALS = ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm")

# What is handed to the process starter: an argument list, or on Windows one command-line string whose quoting
# is already cmd.exe's own.
LaunchSpec = list[str] | str
Launcher = Callable[[LaunchSpec], None]
# Asks the tool's own health check whether it is signed in.
Check = Callable[[str], Awaitable[bool]]


class SignInError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def start_process(spec: LaunchSpec) -> None:
    """Start the terminal launcher and let it go; its window belongs to the person from here on."""
    subprocess.Popen(spec, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=sys.platform != "win32")


def _shell_line(exe: str, args: list[str], codex_home: Path | None) -> str:
    line = " ".join(shlex.quote(part) for part in (exe, *args))
    return f"CODEX_HOME={shlex.quote(str(codex_home))} {line}" if codex_home else line


def build_launch(platform: str, exe: str, args: list[str], codex_home: Path | None,
                 which: Callable[[str], str | None] = find_tool, script_dir: Path | None = None) -> LaunchSpec:
    """The command that opens a terminal window running `exe args`, with CODEX_HOME set when given."""
    if platform == "darwin":
        # Terminal.app opens a .command file through `open`, which needs no Automation permission (osascript
        # driving Terminal does, and timed out while macOS waited on that prompt). The file removes itself.
        script_dir = script_dir or Path(tempfile.gettempdir())
        script_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = script_dir / f"deixis-sign-in-{Path(exe).name}.command"
        path.write_text(f"#!/bin/sh\nrm -f \"$0\"\n{_shell_line(exe, args, codex_home)}\n"
                        "printf '\\nYou can close this window.\\n'\n")
        path.chmod(0o700)
        return ["open", "-a", "Terminal", str(path)]
    if platform == "win32":
        # cmd.exe drops the first and last quote of the /k text, so the whole payload sits in one more pair.
        payload = " ".join(f'"{part}"' if " " in part else part for part in (exe, *args))
        if codex_home:
            payload = f'set "CODEX_HOME={codex_home}"&& {payload}'
        return f'cmd.exe /c start "DEIXIS sign-in" cmd.exe /k "{payload}"'
    script = f"{_shell_line(exe, args, codex_home)}; printf '\\nPress Enter to close this window. '; read _"
    for terminal in LINUX_TERMINALS:
        path = which(terminal)
        if path:
            separator = "--" if terminal == "gnome-terminal" else "-e"
            return [path, separator, "sh", "-c", script]
    raise SignInError(409, "No terminal program was found on this computer; run the sign-in command in a terminal yourself")


class AccountSignIn:
    def __init__(self, codex_home: Path, check: Check, launcher: Launcher | None = None, platform: str | None = None,
                 timeout: float = SIGNIN_TIMEOUT_SECONDS, interval: float = CHECK_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.monotonic, on_succeeded: Callable[[str], None] | None = None):
        self._codex_home = codex_home
        self._check = check
        self._launcher = launcher or start_process
        self._platform = platform or sys.platform
        self._timeout, self._interval, self._clock = timeout, interval, clock
        self._on_succeeded = on_succeeded
        self._state: dict[str, dict[str, Any]] = {}
        self._run: dict[str, dict[str, Any]] = {}  # deadline, last check time, whether a check is in flight

    def _view(self, tool: str) -> dict[str, Any]:
        return dict(self._state.get(tool) or {"state": "idle", "message": None})

    @staticmethod
    def _known(tool: str) -> None:
        if tool not in TOOLS:
            raise SignInError(404, f"Unknown account sign-in '{tool}'")

    async def start(self, tool: str) -> dict[str, Any]:
        self._known(tool)
        if self._view(tool)["state"] == "waiting":
            return self._view(tool)
        binary, args, name = TOOLS[tool]
        exe = find_tool(binary)
        if not exe:
            raise SignInError(409, f"{name} was not found on this computer; install it first")
        if tool == "codex":
            self._codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        spec = build_launch(self._platform, exe, args, self._codex_home if tool == "codex" else None,
                            script_dir=self._codex_home.parent / "sign-in")
        try:
            self._launcher(spec)
        except OSError as exc:
            raise SignInError(409, f"A terminal window could not be opened: {type(exc).__name__}") from exc
        now = self._clock()
        self._state[tool] = {"state": "waiting", "message": None}
        self._run[tool] = {"deadline": now + self._timeout, "last": now, "busy": False}
        return self._view(tool)

    async def state(self, tool: str) -> dict[str, Any]:
        """The state; while waiting, this is also what asks the tool's health check, at most every interval."""
        self._known(tool)
        record, run = self._state.get(tool), self._run.get(tool)
        if not record or record["state"] != "waiting" or run is None or run["busy"]:
            return self._view(tool)
        now = self._clock()
        if now >= run["deadline"]:
            record.update(state="timed_out", message="The sign-in was not completed within 10 minutes.")
            return self._view(tool)
        if now - run["last"] < self._interval:
            return self._view(tool)
        run["busy"], run["last"] = True, now
        try:
            signed_in = await self._check(tool)
        except Exception:  # a health check that fails is "not yet", not a crashed route
            signed_in = False
        finally:
            run["busy"] = False
        if record["state"] != "waiting":
            return self._view(tool)
        if signed_in:
            record.update(state="succeeded", message=None)
            if self._on_succeeded:
                self._on_succeeded(tool)
        return self._view(tool)

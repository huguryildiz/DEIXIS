"""Process groups for the command-line model connections (Copilot CLI D24, Gemini CLI D23).

A CLI run gets its own process group so that a timeout or a cancelled step also stops anything the CLI started:
npm's launchers and Gemini CLI's self-relaunch leave a child that holds the output pipes, and asyncio's wait() does
not return while a pipe is open.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from typing import Any

KILL = signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM


def spawn_options() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_group(proc: asyncio.subprocess.Process, sig: int = KILL) -> None:
    """Stops the run's whole process group, whether or not the CLI itself has already exited: a child it left behind
    can still hold the output pipes."""
    if sys.platform == "win32":
        # The whole tree; kill() alone would end only the CLI. Only while it runs: its pid may be reused once it has
        # exited, and taskkill cannot reach a child whose parent has exited anyway.
        if proc.returncode is not None:
            return
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if proc.returncode is None:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
        return
    try:
        os.killpg(proc.pid, sig)  # the group id is the CLI's pid (start_new_session)
    except (ProcessLookupError, PermissionError, OSError):
        pass


async def reap(proc: asyncio.subprocess.Process) -> None:
    # Bounded: a left-over child holding a pipe must not keep the step waiting.
    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), 10)
    except TimeoutError:
        pass

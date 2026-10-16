"""Process groups for the command-line model connections (Copilot CLI D24, Gemini CLI D23).

A CLI run gets its own process group so that a timeout or a cancelled step also stops anything the CLI started:
npm's launchers and Gemini CLI's self-relaunch leave a child that holds the output pipes, and asyncio's wait() does
not return while a pipe is open.
"""

from __future__ import annotations

import asyncio
import functools
import os
import signal
import subprocess
import sys
import weakref
from typing import Any

KILL = signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM
WINDOWS = sys.platform == "win32"
# Windows: the job object holding each tracked CLI and everything it starts, closed when the process object goes.
_JOBS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def spawn_options() -> dict[str, Any]:
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


@functools.cache
def _kernel32() -> Any:
    import ctypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = k.OpenProcess.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    k.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    k.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    return k


def track(proc: asyncio.subprocess.Process) -> None:
    """Windows: puts a just-started CLI in a job object, so stop_group also ends what it started after the CLI itself
    has exited (taskkill /T finds a child only through its running parent). POSIX needs nothing: the process group
    outlives its leader. The CLI is assigned before it has loaded far enough to start a child of its own."""
    if not WINDOWS:
        return
    try:
        k = _kernel32()
        job = k.CreateJobObjectW(None, None)
        if not job:
            return
        handle = k.OpenProcess(0x0001 | 0x0100, False, proc.pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
        assigned = bool(handle) and bool(k.AssignProcessToJobObject(job, handle))
        if handle:
            k.CloseHandle(handle)
        if not assigned:
            k.CloseHandle(job)
            return
        _JOBS[proc] = job
        weakref.finalize(proc, k.CloseHandle, job)
    except (OSError, AttributeError):
        pass


def stop_group(proc: asyncio.subprocess.Process, sig: int = KILL) -> None:
    """Stops the run's whole process group, whether or not the CLI itself has already exited: a child it left behind
    can still hold the output pipes."""
    if WINDOWS:
        job = _JOBS.get(proc)
        if job is not None:
            _kernel32().TerminateJobObject(job, 1)  # every process in the job, the CLI's own exit notwithstanding
            return
        # Untracked (the job could not be made): the whole tree, while the CLI runs; its pid may be reused once it
        # has exited. taskkill is a child process that can take seconds: stop_group_async runs it off the loop.
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


async def stop_group_async(proc: asyncio.subprocess.Process, sig: int = KILL) -> None:
    """stop_group without holding up the event loop: the Windows taskkill fallback runs in a thread, bounded."""
    if WINDOWS and proc not in _JOBS:
        try:
            await asyncio.wait_for(asyncio.to_thread(stop_group, proc, sig), 20)
        except TimeoutError:
            pass
        return
    stop_group(proc, sig)


async def reap(proc: asyncio.subprocess.Process) -> None:
    # Bounded: a left-over child holding a pipe must not keep the step waiting.
    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), 10)
    except TimeoutError:
        pass

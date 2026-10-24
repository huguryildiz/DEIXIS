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


# Windows process creation flags and job limits (winbase.h, winnt.h); named here because Python defines only some.
CREATE_SUSPENDED, CREATE_NEW_PROCESS_GROUP = 0x00000004, 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 0x00002000, 9
PROCESS_ACCESS = 0x0001 | 0x0100 | 0x0800  # PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME


def spawn_options() -> dict[str, Any]:
    """Every process started with these must be passed to track() at once: on Windows it starts suspended."""
    if WINDOWS:
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED}
    return {"start_new_session": True}


@functools.cache
def _kernel32() -> Any:
    import ctypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = k.OpenProcess.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    k.SetInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    k.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    k.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    return k


@functools.cache
def _ntdll() -> Any:
    import ctypes

    n = ctypes.WinDLL("ntdll")
    n.NtResumeProcess.argtypes = (ctypes.c_void_p,)
    n.NtResumeProcess.restype = ctypes.c_long
    return n


def _kill_on_close() -> Any:
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION with KILL_ON_JOB_CLOSE: closing the last job handle, DEIXIS's crash included,
    ends every process in the job."""
    import ctypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = Extended()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return info


def track(proc: asyncio.subprocess.Process, require_job: bool = False) -> None:
    """Windows: puts the CLI started by spawn_options() in a job object, then lets it run. stop_group then ends the
    CLI and everything it started, also after the CLI itself has exited (taskkill /T finds a child only through its
    running parent). POSIX needs nothing: the process group outlives its leader.

    Why suspended: a process's children join its job only if it is in the job when it creates them, so the CLI is
    created with CREATE_SUSPENDED (no code of its own has run, it cannot have started a child or exited, so its pid
    is still its own), assigned to the job and only then resumed. Popen keeps no thread handle to ResumeThread, so
    the whole process is resumed with NtResumeProcess, an ntdll export long used for this. If the job cannot be made,
    the CLI still runs, untracked (stop_group falls back to taskkill); if it cannot even be resumed, it is killed.
    `require_job` (the folder-lock holder's command, which must never run outside the job): a job that cannot be made
    or joined kills the process without resuming it and raises OSError."""
    if not WINDOWS:
        return
    import ctypes

    k, handle, job = _kernel32(), None, None
    try:
        handle = k.OpenProcess(PROCESS_ACCESS, False, proc.pid)
        if not handle:
            raise OSError("OpenProcess failed")
        job = k.CreateJobObjectW(None, None)
        info = _kill_on_close()
        if job and k.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                             ctypes.sizeof(info)) and k.AssignProcessToJobObject(job, handle):
            _JOBS[proc] = job
            weakref.finalize(proc, k.CloseHandle, job)
        else:
            if job:
                k.CloseHandle(job)
            if require_job:
                raise OSError("the process could not join a job object")
        if _ntdll().NtResumeProcess(handle) != 0:
            raise OSError("NtResumeProcess failed")
    except (OSError, AttributeError) as exc:
        try:
            proc.kill()  # left suspended it would hold its caller until the timeout
        except (ProcessLookupError, OSError):
            pass
        if require_job:
            raise OSError(f"the process was stopped, not run: {exc}") from exc
    finally:
        if handle:
            k.CloseHandle(handle)


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

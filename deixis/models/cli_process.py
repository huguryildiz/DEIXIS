"""Process groups for the command-line model connections (Copilot CLI D24, Gemini CLI D23).

A CLI run gets its own process group so that a timeout or a cancelled step also stops anything the CLI started:
npm's launchers and Gemini CLI's self-relaunch leave a child that holds the output pipes, and asyncio's wait() does
not return while a pipe is open.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import weakref
from typing import Any

from deixis.tools import child_record, win_job

KILL = signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM
WINDOWS = sys.platform == "win32"
# Windows: the job object holding each tracked CLI and everything it starts, closed when the process object goes.
_JOBS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
# POSIX: each tracked process's identity (pid:start) read when it was started; its group is signalled only while that
# process is still the leader (`tools/child_record.stop_group`).
_LEADERS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
CREATE_NEW_PROCESS_GROUP = 0x00000200  # winbase.h: a Ctrl-C in DEIXIS's console does not reach the CLI


def launch(argv) -> list[str]:
    """The argv to start with spawn_options(): on macOS the program runs under the session launcher, which records the
    new session before the program starts (while the record is on) and empties it after (`tools/child_record.py`)."""
    return child_record.launcher_argv(list(argv), "cli")


def refused(returncode: int | None, stderr: str) -> str | None:
    """The launcher's refusal (the program never started, nothing was sent): its sentence, else None."""
    from deixis.tools.session_launcher import RECORD_FAILED, REFUSED

    line = next((x for x in stderr.splitlines() if x.startswith(REFUSED)), None)
    return line if returncode == RECORD_FAILED and line and child_record.ON else None


def spawn_options() -> dict[str, Any]:
    """Every process started with these must be passed to track() at once: on Windows it starts suspended."""
    if WINDOWS:
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | win_job.CREATION_FLAGS}
    return {"start_new_session": True}


def track(proc: asyncio.subprocess.Process) -> None:
    """POSIX: keeps the started leader's identity for stop_group. Windows: puts the CLI started by spawn_options() (still
    suspended) in a kill-on-close job object of its own, then lets it run (`tools/win_job.py`); stop_group then ends
    the CLI and everything it started, also after the CLI itself has exited. Fail closed (P10 W2): a CLI that cannot
    join its job is terminated without running and win_job.JobError, an OSError, is raised: a local start error, nothing
    was sent."""
    if not WINDOWS:
        _LEADERS[proc] = child_record.leader(proc.pid)
        return
    job = win_job.start_in_job(proc)
    _JOBS[proc] = job
    weakref.finalize(proc, job.close)


def stop_group(proc: asyncio.subprocess.Process, sig: int = KILL) -> None:
    """Stops the run's whole process group, whether or not the CLI itself has already exited: a child it left behind
    can still hold the output pipes."""
    if WINDOWS:
        job = _JOBS.get(proc)
        if job is not None:
            job.terminate()  # every process in the job, the CLI's own exit notwithstanding
        elif proc.returncode is None:  # never resumed (track failed): it ran nothing
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
        return
    # The group id is the leader's pid (start_new_session), signalled only while that leader is verified.
    child_record.stop_group(proc.pid, _LEADERS.get(proc), sig)


class _JobSpawns:
    """Stands in for `anyio` inside a library's own process starter on Windows (the Claude Agent SDK's transport, whose
    `anyio.open_process` cannot be handed creation flags from outside): every process it opens starts suspended and is
    put in a kill-on-close job of its own (`track`) before it runs; one that cannot join is terminated unrun and the
    JobError raised. Everything else is anyio's own."""

    def __init__(self, anyio_module: Any):
        self._anyio = anyio_module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._anyio, name)

    async def open_process(self, command: Any, *, creationflags: int = 0, **options: Any) -> Any:
        proc = await self._anyio.open_process(command, creationflags=creationflags | spawn_options()["creationflags"], **options)
        try:
            track(proc)
        except OSError:
            await proc.aclose()  # terminated unrun by track; its pipes are closed here
            raise
        _JOINED.add(proc.pid)
        return proc


# Pids _JobSpawns started suspended and put in a job before they ran: the caller checks its own process is among them,
# so a library that started it some other way (an update) is caught after the fact too.
_JOINED: set[int] = set()


def joined_job(proc: Any) -> bool:
    """Whether _JobSpawns started `proc` inside a job (Windows; asked once per process, then forgotten)."""
    if proc is None or proc.pid not in _JOINED:
        return False
    _JOINED.discard(proc.pid)
    return True


def spawn_in_jobs(module: Any) -> bool:
    """Windows: routes `module`'s `anyio.open_process` through _JobSpawns (P10 W2). Whether it now does; a module that
    no longer starts processes through a module-level `anyio` is left as it is and gives False, so its caller can refuse
    to start anything (fail closed). Elsewhere nothing changes and the answer is False."""
    if not WINDOWS or not hasattr(module, "anyio"):
        return False
    if not isinstance(module.anyio, _JobSpawns):
        module.anyio = _JobSpawns(module.anyio)
    return True


async def stop_group_async(proc: asyncio.subprocess.Process, sig: int = KILL) -> None:
    """stop_group from async code; neither path waits on a child process."""
    stop_group(proc, sig)


async def reap(proc: asyncio.subprocess.Process) -> None:
    # Bounded: a left-over child holding a pipe must not keep the step waiting.
    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), 10)
    except TimeoutError:
        pass

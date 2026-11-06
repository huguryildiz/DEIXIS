"""Windows Job Objects for the processes DEIXIS starts (P10 W2): the model CLIs and tool probes (`models/cli_process.py`),
the folder-lock holder's command (`storage/library_lock.py`) and the PDF, OCR and JATS extraction children
(`documents/pdf.py`).

Every such process is created with CREATE_SUSPENDED, so no code of its own has run: it cannot have started a child or
exited, and its pid is still its own. `start_in_job` then gives it a job of its own with KILL_ON_JOB_CLOSE (closing the
last handle, DEIXIS's crash included, ends every process in the job), optionally a per-process memory limit, puts it in
the job and only then resumes it. Popen keeps no thread handle to ResumeThread, so the whole process is resumed with
NtResumeProcess, an ntdll export long used for this.

Fail closed: if the job cannot be made, limited or joined, or the process cannot be resumed, the suspended process is
terminated, never resumed, and JobError (an OSError) is raised; the caller reports a local start error. Nothing here asks
for breakaway: no CREATE_BREAKAWAY_FROM_JOB, no JOB_OBJECT_LIMIT_BREAKAWAY_OK or SILENT_BREAKAWAY_OK, so a process in
the job cannot start a child outside it (a child asking for breakaway is refused, or, as measured on Windows 11 under an
outer job, created inside the job all the same). The job handle is created without security attributes and so is never
inherited by a child.

Inside the packaged app the backend itself runs in the shell's kill-on-close job (W4), so every process created here is
in that job from its creation, also in the moment between CREATE_SUSPENDED and the assignment; the nested job (Windows 8
and later) adds the memory limit and the kill-together. Known limit of a run from source (no shell job): a backend killed
in that moment leaves a suspended process that never runs.

The memory limit is the job's per-process committed-memory limit: an allocation past it fails in the child (MemoryError
in Python, a failed allocation in C). The job also posts JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT to its completion port,
which is read by `Job.memory_limit_reported`; that message is not guaranteed, so the extraction parent also reads the
job's peak process memory (`Job.peak_process_memory`).
"""

from __future__ import annotations

import ctypes
import functools
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any

# winbase.h, winnt.h
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000  # the packaged backend has no console; a console child would otherwise open a window
CREATION_FLAGS = CREATE_SUSPENDED | CREATE_NO_WINDOW
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400  # a crash ends the process instead of waiting on a dialog
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION = 7
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT = 9
PROCESS_ACCESS = 0x0001 | 0x0100 | 0x0800  # PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WATCH_INTERVAL_SECONDS = 0.05


class JobError(OSError):
    """The process could not be started inside its job; it was terminated without running."""


@functools.cache
def _kernel32() -> Any:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, dword = ctypes.c_void_p, ctypes.c_uint32
    k.CreateJobObjectW.restype = k.OpenProcess.restype = k.CreateIoCompletionPort.restype = handle
    k.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    k.SetInformationJobObject.argtypes = (handle, ctypes.c_int, ctypes.c_void_p, dword)
    k.QueryInformationJobObject.argtypes = (handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.c_void_p)
    k.OpenProcess.argtypes = (dword, ctypes.c_int, dword)
    k.AssignProcessToJobObject.argtypes = (handle, handle)
    k.TerminateJobObject.argtypes = (handle, ctypes.c_uint)
    k.TerminateProcess.argtypes = (handle, ctypes.c_uint)
    k.CreateIoCompletionPort.argtypes = (handle, handle, ctypes.c_size_t, dword)
    k.GetQueuedCompletionStatus.argtypes = (handle, ctypes.POINTER(dword), ctypes.POINTER(ctypes.c_size_t),
                                            ctypes.POINTER(ctypes.c_void_p), dword)
    k.CloseHandle.argtypes = (handle,)
    return k


@functools.cache
def _ntdll() -> Any:
    n = ctypes.WinDLL("ntdll")
    n.NtResumeProcess.argtypes = (ctypes.c_void_p,)
    n.NtResumeProcess.restype = ctypes.c_long
    return n


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _Extended(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _CompletionPort(ctypes.Structure):
    _fields_ = [("CompletionKey", ctypes.c_void_p), ("CompletionPort", ctypes.c_void_p)]


def _failed(what: str) -> JobError:
    return JobError(f"{what} failed (Windows error {ctypes.get_last_error()})")


class Job:
    """One process's job: `terminate` ends every process in it; `close` lets the last handle go (KILL_ON_JOB_CLOSE)."""

    def __init__(self, handle: int, port: int | None):
        self.handle, self.port, self._memory = handle, port, False

    def terminate(self, code: int = 1) -> None:
        if self.handle:
            _kernel32().TerminateJobObject(self.handle, code)

    def memory_limit_reported(self) -> bool:
        """Whether the job posted JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT; reads every queued message without waiting."""
        if self.port and not self._memory:
            k, message, key, overlapped = _kernel32(), ctypes.c_uint32(), ctypes.c_size_t(), ctypes.c_void_p()
            while k.GetQueuedCompletionStatus(self.port, ctypes.byref(message), ctypes.byref(key), ctypes.byref(overlapped), 0):
                if message.value == JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT:
                    self._memory = True
        return self._memory

    def peak_process_memory(self) -> int | None:
        info = _Extended()
        if not self.handle or not _kernel32().QueryInformationJobObject(
                self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None):
            return None
        return int(info.PeakProcessMemoryUsed)

    def close(self) -> None:
        k = _kernel32()
        for name in ("port", "handle"):
            if value := getattr(self, name):
                setattr(self, name, None)
                k.CloseHandle(value)


def start_in_job(proc: Any, memory_limit: int | None = None, watch: bool = False) -> Job:
    """Put `proc` (a Popen or asyncio Process created with CREATION_FLAGS, still suspended) in a new job and resume it.
    `memory_limit` sets the job's per-process committed-memory limit in bytes; `watch` gives the job a completion port
    for `Job.memory_limit_reported`. Raises JobError after terminating the process when any step fails."""
    k = _kernel32()
    handle, job = k.OpenProcess(PROCESS_ACCESS, False, proc.pid), None
    try:
        if not handle:
            raise _failed("OpenProcess")
        job = Job(k.CreateJobObjectW(None, None), None)  # no security attributes: the handle is not inheritable
        if not job.handle:
            raise _failed("CreateJobObjectW")
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        if memory_limit is not None:
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = memory_limit
        if not k.SetInformationJobObject(job.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            raise _failed("SetInformationJobObject (limits)")
        if watch:
            job.port = k.CreateIoCompletionPort(INVALID_HANDLE_VALUE, None, 0, 1)
            if not job.port:
                raise _failed("CreateIoCompletionPort")
            port = _CompletionPort(job.handle, job.port)
            if not k.SetInformationJobObject(job.handle, JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION, ctypes.byref(port),
                                             ctypes.sizeof(port)):
                raise _failed("SetInformationJobObject (completion port)")
        if not k.AssignProcessToJobObject(job.handle, handle):
            raise _failed("AssignProcessToJobObject")
        if (status := _ntdll().NtResumeProcess(handle)) != 0:
            raise JobError(f"NtResumeProcess failed (status {status & 0xFFFFFFFF:#x})")
        return job
    except BaseException:
        if handle:
            k.TerminateProcess(handle, 1)
        else:
            try:
                proc.kill()
            except OSError:
                pass
        if job is not None:
            job.close()
        raise
    finally:
        if handle:
            k.CloseHandle(handle)


@dataclass
class Finished:
    returncode: int
    stdout: bytes
    stderr: bytes
    memory_limit: bool  # the job reported the limit, or its peak process memory reached it


def run(argv: list[str], env: dict[str, str], timeout: float, memory_limit: int) -> Finished:
    """An extraction child run to its end inside its own job with `memory_limit`; raises subprocess.TimeoutExpired once
    `timeout` seconds have passed, and JobError when it could not be started inside the job. Whatever the outcome, the job
    is terminated at the end, so a grandchild the child left goes too. A reported memory limit stops the child at once."""
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, creationflags=CREATION_FLAGS)
        job = start_in_job(proc, memory_limit, watch=True)
        try:
            while True:
                try:
                    proc.wait(max(0.0, min(WATCH_INTERVAL_SECONDS, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    pass
                if job.memory_limit_reported():
                    break
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(argv, timeout)
            peak = job.peak_process_memory()
            hit = job.memory_limit_reported() or (peak is not None and peak >= memory_limit)
            if not hit and time.monotonic() > deadline:  # a child that ends after the deadline is a timeout all the same
                raise subprocess.TimeoutExpired(argv, timeout)
        finally:
            job.terminate()
            job.close()
            proc.wait()
        out.seek(0), err.seek(0)
        return Finished(proc.returncode, out.read(), err.read(), hit)

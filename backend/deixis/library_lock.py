"""One lock per data folder across processes (E1): `library.lock` in the folder, beside the worker lock.

Every DEIXIS process that opens a folder's library (the server and the command line) holds the folder's shared lock
for its whole life, taken before the database is opened. Moving a library at start takes the exclusive lock of the
source folder, then of the target, and never waits: when either is held, nothing moves and the move is postponed. No
request waits, so two processes asking in opposite orders cannot deadlock. The move also takes each folder's
`worker.lock` (the lock every earlier DEIXIS build holds for its whole life and nothing else), so a build from before
the folder lock existed blocks a move too.

Children that work inside the folder (the built-in model's install and runner, the equation reader's install and
process) are started with `guard`, so a child that outlives its DEIXIS still keeps the folder busy. POSIX uses
`flock` and the child inherits the descriptor (`pass_fds`). Windows (`msvcrt`) has no shared lock: a shared holder
locks one byte of a slot range and the exclusive holder the whole range, and a byte-range lock is not inherited. There
the child is started through a small holder process (`python -m deixis hold-folder`) that takes the shared lock
itself, tells the parent it holds it (a file the parent waits for), and only then starts the real command; it
exits when the command does, and a job object ends the command if the holder is killed. The Windows path has not run
on a Windows computer.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

LOCK_NAME = "library.lock"
WORKER_LOCK_NAME = "worker.lock"  # held exclusively, whole life, by every DEIXIS server (workflow/worker.py)
HANDSHAKE_SECONDS = 20.0
SLOTS = 4096  # Windows: byte 0 plus one byte per possible shared holder

_held: dict[Path, int] = {}  # folder -> descriptor holding its shared lock, for the life of this process


class Busy(Exception):
    """Another process holds the folder's lock."""

    def __init__(self, folder: Path):
        super().__init__(str(folder))
        self.folder = folder


def _open(folder: Path, name: str = LOCK_NAME) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    return os.open(folder / name, os.O_RDWR | os.O_CREAT, 0o600)


def _try_worker(fd: int) -> bool:
    """The worker lock the way `Worker.acquire` takes it: exclusive, byte 0 on Windows."""
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _try(fd: int, exclusive: bool) -> bool:
    try:
        if fcntl:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return True
        if exclusive:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, SLOTS + 1)
            return True
        for slot in random.sample(range(1, SLOTS + 1), 16):  # another shared holder may own a slot; an exclusive one owns all
            os.lseek(fd, slot, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                continue
        return False
    except OSError:
        return False


def hold_shared(folder: Path) -> bool:
    """Take `folder`'s shared lock for the rest of this process; False while a move holds it."""
    if folder in _held:
        return True
    fd = _open(folder)
    if not _try(fd, exclusive=False):
        os.close(fd)
        return False
    _held[folder] = fd
    return True


def release(folder: Path) -> None:
    if (fd := _held.pop(folder, None)) is not None:
        os.close(fd)  # closing the descriptor releases the lock (a child given it keeps holding it)


def release_all() -> None:
    for folder in list(_held):
        release(folder)


def _inherits() -> bool:
    """Whether a child inherits a held lock (POSIX descriptors); a Windows child takes its own through a holder."""
    return fcntl is not None


def child_fds() -> tuple[int, ...]:
    """The descriptors a POSIX child started in the folder inherits (`pass_fds`), so it keeps the folder busy while it runs."""
    return tuple(_held.values()) if _inherits() else ()


class ChildLockFailed(OSError):
    """The holder process of a Windows child could not take the folder's shared lock (a move holds it) or never answered."""


class Guard:
    """How to start one child in the held folders: `argv` and `kwargs` for the process call, then `wait_ready()` (blocking:
    use `asyncio.to_thread` in the event loop) once it is started, and `done()` when finished with it."""

    def __init__(self, argv: list[str]):
        self.argv, self.kwargs, self._ready = list(argv), {}, None
        if not _held:
            return
        if _inherits():
            self.kwargs = {"pass_fds": child_fds()}
            return
        handle, name = tempfile.mkstemp(prefix="deixis-folder-lock-")
        os.close(handle)
        self._ready = Path(name)
        entry = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "deixis"]
        self.argv = [*entry, "hold-folder", name, *map(str, _held), "--", *argv]

    def wait_ready(self, timeout: float = HANDSHAKE_SECONDS) -> None:
        if self._ready is None:
            return
        deadline = time.monotonic() + timeout
        while True:
            try:
                answer = self._ready.read_text()
            except OSError:
                answer = ""
            if answer == "ready":
                return
            if answer == "busy":
                raise ChildLockFailed("the data folder is being moved; the command was not started")
            if time.monotonic() > deadline:
                raise ChildLockFailed("the folder lock holder did not answer; the command was not started")
            time.sleep(0.05)

    def done(self) -> None:
        if self._ready is not None:
            self._ready.unlink(missing_ok=True)


def guard(argv: list[str]) -> Guard:
    return Guard(argv)


def run(argv: list[str], **options) -> None:
    """`subprocess.run(argv, check=True)` inside the held folders."""
    child = guard(argv)
    try:
        process = subprocess.Popen(child.argv, **child.kwargs, **options)
        try:
            child.wait_ready()
        except BaseException:
            process.kill()
            process.wait()
            raise
        if code := process.wait():
            raise subprocess.CalledProcessError(code, argv)
    finally:
        child.done()


def _end_with_me(process: subprocess.Popen) -> None:
    """Windows: a job object that ends `process` when this holder ends, so killing the holder cannot leave the command
    running without a lock. Best effort: without it the command still runs under the holder's lock."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("a", "b", "c", "d", "e", "f")]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Counters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))  # 9: extended limits
    kernel.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle)))  # type: ignore[attr-defined]


def holder_main(args: list[str]) -> int:
    """`hold-folder READY_FILE FOLDER... -- COMMAND...` (the Windows holder): take the shared lock of every folder, say so
    in READY_FILE ("ready", or "busy" when a move holds one), then run COMMAND and exit with its status."""
    split = args.index("--")
    ready, folders, command = Path(args[0]), [Path(p) for p in args[1:split]], args[split + 1:]
    got = all(hold_shared(folder) for folder in folders)
    ready.write_text("ready" if got else "busy")
    if not got:
        return 3
    try:
        process = subprocess.Popen(command)
    except OSError:
        return 127
    try:
        _end_with_me(process)
    except Exception:
        pass
    return process.wait()


@contextmanager
def exclusive(*folders: Path) -> Iterator[None]:
    """The exclusive locks of `folders` (each one's folder lock and worker lock), taken in the order given without waiting;
    raises Busy naming the first folder with a held lock."""
    fds: list[int] = []
    try:
        for folder in folders:
            fds.append(fd := _open(folder))
            if not _try(fd, exclusive=True):
                raise Busy(folder)
            fds.append(fd := _open(folder, WORKER_LOCK_NAME))
            if not _try_worker(fd):
                raise Busy(folder)
        yield
    finally:
        for fd in reversed(fds):
            os.close(fd)

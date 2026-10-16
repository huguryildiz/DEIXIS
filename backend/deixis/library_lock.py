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
itself, starts the real command suspended inside a kill-on-close job object (`models/cli_process.py`), lets it run and
tells the parent (a file the parent waits for). The command exits when the holder does, so it never runs without the
lock, and it does not run at all when it cannot join the job. The Windows path has not run on a Windows computer.
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

from deixis.child_env import child_env

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

    def env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """The environment for the process call. The holder of a frozen onefile build outlives the parent that unpacked it, so
        it must not reuse the parent's unpacked files (PyInstaller: PYINSTALLER_RESET_ENVIRONMENT=1)."""
        env = dict(child_env() if base is None else base)  # never a copy of os.environ: no base means the allowlist
        if self._ready is not None and getattr(sys, "frozen", False):
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        return env

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
            if answer == "failed":
                raise ChildLockFailed("the command could not be tied to the folder lock holder; it was not run")
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
    options = {**options, "env": child.env(options.get("env"))}
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


def holder_main(args: list[str]) -> int:
    """`hold-folder READY_FILE FOLDER... -- COMMAND...` (the Windows holder): take the shared lock of every folder, start
    COMMAND suspended, put it in a kill-on-close job object, let it run, say "ready" in READY_FILE and exit with its status.
    "busy" means a move holds a folder; "failed" means COMMAND could not be started inside the job, and it did not run."""
    from deixis.models import cli_process

    split = args.index("--")
    ready, folders, command = Path(args[0]), [Path(p) for p in args[1:split]], args[split + 1:]
    if not all(hold_shared(folder) for folder in folders):
        ready.write_text("busy")
        return 3
    try:
        process = subprocess.Popen(command, **cli_process.spawn_options())
        cli_process.track(process, require_job=True)  # a command that cannot join the job is killed unrun, never left free of the lock
    except OSError:
        ready.write_text("failed")
        return 1
    ready.write_text("ready")
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

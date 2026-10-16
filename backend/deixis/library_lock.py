"""One lock per data folder across processes (E1): `library.lock` in the folder, beside the worker lock.

Every DEIXIS process that opens a folder's library (the server and the command line) holds the folder's shared lock
for its whole life, taken before the database is opened. Moving a library at start takes the exclusive lock of the
source folder, then of the target, and never waits: when either is held, nothing moves and the move is postponed. No
request waits, so two processes asking in opposite orders cannot deadlock.

Children that work inside the folder (the built-in model's install and runner, the equation reader's install and
process) are started by the process that holds the shared lock and receive its descriptor (`child_fds`, POSIX
`pass_fds`), so a child that outlives its DEIXIS still keeps the folder busy. POSIX uses `flock`, like the worker lock.
Windows (`msvcrt`) has no shared lock: a shared holder locks one byte of a slot range and the exclusive holder the
whole range; there a lock cannot be handed to a child.
"""

from __future__ import annotations

import os
import random
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

LOCK_NAME = "library.lock"
SLOTS = 4096  # Windows: byte 0 plus one byte per possible shared holder

_held: dict[Path, int] = {}  # folder -> descriptor holding its shared lock, for the life of this process


class Busy(Exception):
    """Another process holds the folder's lock."""

    def __init__(self, folder: Path):
        super().__init__(str(folder))
        self.folder = folder


def _open(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    return os.open(folder / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)


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


def child_fds() -> tuple[int, ...]:
    """The descriptors a child started in the folder inherits (`pass_fds`), so it keeps the folder busy while it runs."""
    return tuple(_held.values()) if fcntl else ()


@contextmanager
def exclusive(*folders: Path) -> Iterator[None]:
    """The exclusive locks of `folders`, taken in the order given without waiting; raises Busy naming the first held one."""
    fds: list[int] = []
    try:
        for folder in folders:
            fds.append(fd := _open(folder))
            if not _try(fd, exclusive=True):
                raise Busy(folder)
        yield
    finally:
        for fd in reversed(fds):
            os.close(fd)

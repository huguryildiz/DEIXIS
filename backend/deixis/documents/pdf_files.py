"""Durable staging and descriptor-based inspection; placement belongs to file_restore."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path


class FileNotRegular(Exception):
    """The stored entry cannot be inspected without following a link."""


def inspect_file(path: Path, copy_path: Path | None = None, *, sync: bool = False) -> tuple[str, int] | None:
    """Hash through one no-follow regular descriptor, optionally copying those exact bytes."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return None
        if exc.errno == errno.ELOOP:
            raise FileNotRegular from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FileNotRegular
    except BaseException:
        os.close(descriptor)
        raise
    with os.fdopen(descriptor, "rb") as source:
        digest, size = hashlib.sha256(), 0
        target = copy_path.open("wb") if copy_path is not None else None
        try:
            while block := source.read(1024 * 1024):
                if target is not None and target.write(block) != len(block):
                    raise OSError(errno.EIO, "Incomplete retained file copy")
                digest.update(block)
                size += len(block)
            if target is not None:
                target.flush()
                os.fsync(target.fileno())
            if sync:
                os.fsync(source.fileno())
        finally:
            if target is not None:
                target.close()
        return digest.hexdigest(), size


def file_is_whole(path: Path, sha256: str, size: int) -> bool:
    try:
        return inspect_file(path) == (sha256, size)
    except FileNotRegular:
        return False


def read_whole(path: Path, sha256: str, size: int) -> bytes | None:
    """The file's bytes, read once through one no-follow regular descriptor, when exactly those bytes have this
    identity; None when the file is missing, not regular or different."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ELOOP):
            return None
        raise
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            return None
        data = source.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        return None
    return data


def stage_bytes(path: Path, data: bytes) -> tuple[str, int]:
    """Write and fsync into a caller-owned path; return the identity of the bytes written."""
    with path.open("wb") as target:
        if target.write(data) != len(data):
            raise OSError(errno.EIO, "Incomplete staged PDF write")
        target.flush()
        os.fsync(target.fileno())
    return hashlib.sha256(data).hexdigest(), len(data)

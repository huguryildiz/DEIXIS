"""Explicit local text retries: file ownership, observed private input and bounded endings."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow.store import RequestConflict

logger = logging.getLogger(__name__)
HASH = re.compile(r"^[0-9a-f]{64}$")
BUSY = (errno.EWOULDBLOCK, errno.EAGAIN)
MISSING = (errno.ENOENT, errno.ENOTDIR, errno.ELOOP)


class FileBusy(Exception):
    """Another operation holds this file's advisory lock."""


class FileMissing(Exception):
    """The stored path does not name an accessible regular file inside papers."""


class SnapshotUnavailable(Exception):
    """Three attempts did not yield a coherent library copy."""


def _lock_path(recovery_dir: Path, sha256: str) -> Path:
    if not HASH.fullmatch(sha256):
        raise ValueError("Invalid file SHA-256")
    return recovery_dir / "locks" / (sha256 + ".lock")


def _private_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.mkdir(exist_ok=True, mode=0o700)


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock(recovery_dir: Path, sha256: str) -> Iterator[None]:
    path = _lock_path(recovery_dir, sha256)
    _private_dir(path.parent)
    handle = path.open("a+b")
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in BUSY or (os.name == "nt" and exc.errno == errno.EACCES):
                raise FileBusy("This file is being used by another extraction; try again when it ends.") from exc
            raise
        acquired = True
        yield
    finally:
        if acquired:
            try:
                _unlock(handle)
            except Exception:
                logger.exception("Could not release a text retry lock")
        try:
            handle.close()
        except Exception:
            logger.exception("Could not close a text retry lock")


def lock_held(recovery_dir: Path, sha256: str) -> bool:
    path = _lock_path(recovery_dir, sha256)
    try:
        handle = path.open("rb")
    except FileNotFoundError:
        return False
    with handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in BUSY:
                return True
            raise
        _unlock(handle)
    return False


def precheck(papers_dir: Path, storage_path: str) -> Path:
    root = papers_dir.resolve()
    if (not storage_path or Path(storage_path).is_absolute() or "/" in storage_path
            or "\\" in storage_path or ".." in storage_path):
        raise FileMissing("File missing")
    path = root / storage_path
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        if exc.errno in MISSING:
            raise FileMissing("File missing") from exc
        raise
    if not stat.S_ISREG(mode):
        raise FileMissing("File missing")
    return path


def observe_copy(papers_dir: Path, storage_path: str, expected_sha256: str, expected_byte_size: int,
                 copy_path: Path) -> tuple[str, str | None, int | None]:
    try:
        path = precheck(papers_dir, storage_path)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileMissing:
        return "missing", None, None
    except OSError as exc:
        if exc.errno in MISSING:
            return "missing", None, None
        raise
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            return "missing", None, None
        digest, size = hashlib.sha256(), 0
        if info.st_size != expected_byte_size:
            while block := source.read(1024 * 1024):
                digest.update(block)
                size += len(block)
            return "mismatch", digest.hexdigest(), size
        with copy_path.open("wb") as target:
            while block := source.read(1024 * 1024):
                written = target.write(block)
                if written != len(block):
                    raise OSError(errno.EIO, "Incomplete extraction input copy")
                digest.update(block)
                size += len(block)
            target.flush()
            os.fsync(target.fileno())
        sha = digest.hexdigest()
        return ("verified" if sha == expected_sha256 and size == expected_byte_size else "mismatch"), sha, size


async def drained_thread(function, *args):
    """Keep ownership until a cancelled thread finishes; cancellation never publishes its result."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            task.result()
        except BaseException:
            logger.exception("Thread failed while draining a cancelled text extraction")
        raise


def _sweep(recovery_dir: Path) -> None:
    try:
        for path in (recovery_dir / "tmp").glob("*.pdf"):
            sha = path.name.split("-", 1)[0]
            if HASH.fullmatch(sha) and not lock_held(recovery_dir, sha):
                try:
                    path.unlink()
                except Exception:
                    logger.exception("Could not remove an orphaned text retry copy")
    except Exception:
        logger.exception("Could not sweep orphaned text retry copies")


INPUT_CHANGED = "The stored PDF changed before its text was read; upload it again to repair it."


@dataclass(frozen=True)
class VerifiedRead:
    extraction: pdf.Extraction
    observation: dict | None


def _read_copy(recovery_dir: Path, sha256: str, *, owned: bool) -> Path:
    _sweep(recovery_dir)
    folder = recovery_dir / "tmp"
    if owned:
        # The caller's exclusive lock rules out a live owner of these copies.
        for path in folder.glob(sha256 + "-*.pdf"):
            _remove_copy(path)
    _private_dir(folder)
    descriptor, name = tempfile.mkstemp(prefix=sha256 + "-", suffix=".pdf", dir=folder)
    os.close(descriptor)
    return Path(name)


def _remove_copy(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.exception("Could not remove a verified extraction input copy")


def _input_observation(storage_path, sha256, byte_size, observed):
    integrity, sha, size = observed
    return {"kind": "extraction_input", "operation_id": None, "storage_path": storage_path,
            "expected_sha256": sha256, "expected_byte_size": byte_size,
            "observed_sha256": sha, "observed_byte_size": size, "integrity": integrity}


async def read_verified(store, papers_dir: Path, recovery_dir: Path, *, storage_path: str,
                        sha256: str, byte_size: int, lock: bool) -> VerifiedRead:
    if not HASH.fullmatch(sha256) or not store._extraction_has_recovery_metadata:
        return VerifiedRead(await drained_thread(pdf.extract_pdf, papers_dir / storage_path), None)
    if lock:
        from deixis.workflow.file_restore import writer_lock

        _sweep(recovery_dir)
        async with writer_lock(recovery_dir, sha256):
            return await read_verified(store, papers_dir, recovery_dir, storage_path=storage_path,
                                       sha256=sha256, byte_size=byte_size, lock=False)
    copy_path = _read_copy(recovery_dir, sha256, owned=True)
    try:
        observed = await drained_thread(observe_copy, papers_dir, storage_path, sha256, byte_size, copy_path)
        extraction = (await drained_thread(pdf.extract_pdf, copy_path) if observed[0] == "verified" else
                      pdf.Extraction(status="failed", error=INPUT_CHANGED))
        return VerifiedRead(extraction, _input_observation(storage_path, sha256, byte_size, observed))
    finally:
        _remove_copy(copy_path)


def read_verified_sync(store, papers_dir: Path, recovery_dir: Path, *, storage_path: str,
                       sha256: str, byte_size: int) -> VerifiedRead:
    """Library-wide CLI read; the caller already owns the non-blocking hash lock."""
    if not HASH.fullmatch(sha256) or not store._extraction_has_recovery_metadata:
        return VerifiedRead(pdf.extract_pdf(papers_dir / storage_path), None)
    copy_path = _read_copy(recovery_dir, sha256, owned=True)
    try:
        observed = observe_copy(papers_dir, storage_path, sha256, byte_size, copy_path)
        extraction = (pdf.extract_pdf(copy_path) if observed[0] == "verified" else
                      pdf.Extraction(status="failed", error=INPUT_CHANGED))
        return VerifiedRead(extraction, _input_observation(storage_path, sha256, byte_size, observed))
    finally:
        _remove_copy(copy_path)


def fingerprint(*, asset_id: str, source_version_id: str, research_id: str | None,
                expected_extraction_id: str) -> str:
    request = {"asset_id": asset_id, "source_version_id": source_version_id, "research_id": research_id,
               "mode": "retry_failed_or_partial", "expected_current_extraction_id": expected_extraction_id}
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _replay(store, key: str, request_fingerprint: str) -> dict[str, Any] | None:
    prior = store.text_retry_by_key(key)
    if prior is None:
        return None
    if prior["request_fingerprint"] != request_fingerprint:
        raise RequestConflict("This request key was used for a different text retry.")
    return store.text_retry_view(prior["id"]) | {"replayed": True}


async def execute_text_retry(store, settings, *, asset_id: str, expected_extraction_id: str, idempotency_key: str,
                             research_id: str | None, source_version_id: str) -> dict[str, Any]:
    store.flush_text_retry_interruptions()
    request_fingerprint = fingerprint(asset_id=asset_id, source_version_id=source_version_id,
                                      research_id=research_id, expected_extraction_id=expected_extraction_id)
    if (result := _replay(store, idempotency_key, request_fingerprint)) is not None:
        return result
    asset = store.asset(asset_id)
    _sweep(settings.recovery_dir)
    precheck(settings.papers_dir, asset["storage_path"])
    try:
        with file_lock(settings.recovery_dir, asset["sha256"]):
            from deixis.workflow import reconcile

            await reconcile.reconcile_hash(store, settings.papers_dir, settings.recovery_dir, asset["sha256"])
            operation = store.reserve_text_retry(asset_id, expected_extraction_id=expected_extraction_id,
                idempotency_key=idempotency_key, request_fingerprint=request_fingerprint, research_id=research_id)
            if operation["replayed"]:
                return store.text_retry_view(operation["operation_id"]) | {"replayed": True}
            oid, copy_path, committed = operation["operation_id"], None, False
            try:
                operation = store._text_retry_operation(oid)
                folder = settings.recovery_dir / "tmp"
                _private_dir(folder)
                descriptor, name = tempfile.mkstemp(prefix=operation["expected_sha256"] + "-", suffix=".pdf", dir=folder)
                copy_path = Path(name)
                os.close(descriptor)
                integrity, sha, size = await drained_thread(observe_copy, settings.papers_dir, asset["storage_path"],
                    operation["expected_sha256"], operation["expected_byte_size"], copy_path)
                obs = store.record_text_retry_input(oid, storage_path=asset["storage_path"],
                    expected_sha256=operation["expected_sha256"], expected_byte_size=operation["expected_byte_size"],
                    observed_sha256=sha, observed_byte_size=size, integrity=integrity)
                if integrity != "verified":
                    store.refuse_text_retry(oid, "file_missing" if integrity == "missing" else "file_mismatch",
                                            input_observation_id=obs)
                else:
                    candidate = await drained_thread(pdf.extract_pdf, copy_path)
                    store.complete_text_retry(oid, candidate, pdf.chunk_page, input_observation_id=obs)
                committed = True
                return store.text_retry_view(oid) | {"replayed": False}
            except BaseException as exc:
                if not committed:
                    failure = db.describe_failure(exc)
                    reason = ("cancelled" if isinstance(exc, asyncio.CancelledError) else
                              "storage_full" if failure and failure[0] == "disk_full" else
                              "storage_unavailable" if failure else "unexpected_error")
                    try:
                        store.interrupt_text_retry(oid, reason)
                    except Exception:
                        store.pending_text_retry_interruptions[oid] = reason
                        logger.exception("Could not persist text retry interruption %s", oid)
                raise
            finally:
                if copy_path is not None:
                    try:
                        copy_path.unlink()
                    except Exception:
                        logger.exception("Could not remove a text retry copy")
    except FileBusy:
        if (result := _replay(store, idempotency_key, request_fingerprint)) is not None:
            return result
        raise


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return info.st_size, info.st_mtime_ns


@contextmanager
def library_snapshot(path: Path) -> Iterator[sqlite3.Connection]:
    """Read planning rows from a bounded main/WAL copy without touching live SHM."""
    wal = Path(f"{path}-wal")
    for _ in range(3):
        with tempfile.TemporaryDirectory(prefix="deixis-retry-plan-") as folder:
            before = (_file_stamp(path), _file_stamp(wal))
            copied = db._copy_live_files(path, Path(folder))
            if before != (_file_stamp(path), _file_stamp(wal)):
                continue
            conn = None
            try:
                conn = sqlite3.connect(copied, isolation_level=None)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                conn.execute("SELECT * FROM schema_migrations").fetchall()
            except sqlite3.DatabaseError:
                if conn is not None:
                    conn.close()
                continue
            try:
                yield conn
            finally:
                conn.close()
            return
    raise SnapshotUnavailable("could not read a consistent copy of the library; try again")

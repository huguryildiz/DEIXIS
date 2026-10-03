"""File-only repair under the text-retry lock, with retained bytes and stored receipts."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from deixis.documents import pdf_files
from deixis.storage import db
from deixis.workflow import text_retry

logger = logging.getLogger(__name__)
WRITER_LOCK_WAIT_SECONDS = 10.0
FILE_WRITERS = ("upload", "source_upload", "waiting_upload", "zotero_import", "zotero_pdfs",
                "acquisition", "run_fetch", "replace_pdf")
FILE_RESTORE_REFUSALS = ("run_active", "retention_conflict", "file_not_regular")
DETAILS = {
    "run_active": "A research using this file has an active run; try again when it ends.",
    "retention_conflict": "The damaged bytes could not be retained because their stored name holds another file.",
    "file_not_regular": "The stored file entry is not a regular file; it cannot be repaired here.",
}


class FileRestoreRefused(Exception):
    def __init__(self, code: str, operation_id: str | None = None):
        super().__init__(DETAILS[code])
        self.code, self.operation_id = code, operation_id


@dataclass(frozen=True)
class Staged:
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class Placement:
    path: Path
    sha256: str
    size: int
    outcome: str
    operation_id: str | None = None


@contextmanager
def transaction(conn):
    """Close failed COMMITs as well as failed statements, preserving the original error."""
    try:
        with db.transaction(conn):
            yield conn
    except BaseException:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except BaseException:
                logger.exception("Could not roll back a failed file restore transaction")
        raise


def cleanup(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except BaseException:
            logger.exception("Could not remove a file restore temporary file")


def resolve_recovery_dir(store, papers_dir: Path, recovery_dir: Path | None = None) -> Path:
    configured = store.recovery_dir
    if recovery_dir is not None:
        if configured is not None and recovery_dir.resolve() != configured.resolve():
            raise ValueError("Recovery directories must use the same file lock namespace")
        return recovery_dir
    return configured if configured is not None else papers_dir.parent / "recovery"


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return  # Windows does not support opening directories through os.open.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def allocate(papers_dir: Path, suffix: str = ".part") -> Path:
    descriptor, name = tempfile.mkstemp(dir=papers_dir, suffix=suffix)
    path = Path(name)
    try:
        os.close(descriptor)
    except BaseException:
        cleanup(path)
        raise
    return path


def observation(staged: Staged, observed: tuple[str, int] | None, retained_filename: str | None = None) -> dict:
    return {"storage_path": staged.sha256 + ".pdf", "expected_sha256": staged.sha256,
            "expected_byte_size": staged.size, "observed_sha256": observed[0] if observed else None,
            "observed_byte_size": observed[1] if observed else None,
            "integrity": "missing" if observed is None else
                         "verified" if observed == (staged.sha256, staged.size) else "mismatch",
            "retained_filename": retained_filename}


@asynccontextmanager
async def writer_lock(recovery_dir: Path, sha256: str):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WRITER_LOCK_WAIT_SECONDS
    with ExitStack() as locks:
        while True:
            try:
                locks.enter_context(text_retry.file_lock(recovery_dir, sha256))
                break
            except text_retry.FileBusy:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise
                await asyncio.sleep(min(0.05, remaining))
        yield


async def restore_file(store, papers_dir: Path, recovery_dir: Path, staged: Staged, *, caller: str,
                       research_id: str | None) -> Placement:
    copy_path, operation_id, committed = None, None, False
    try:
        if caller not in FILE_WRITERS:
            raise ValueError("Unknown PDF writer")
        if not text_retry.HASH.fullmatch(staged.sha256):
            raise ValueError("Invalid file SHA-256")
        recovery_dir = resolve_recovery_dir(store, papers_dir, recovery_dir)
        target = papers_dir / (staged.sha256 + ".pdf")
        result = Placement(target, staged.sha256, staged.size, "reused")
        if await text_retry.drained_thread(pdf_files.file_is_whole, target, staged.sha256, staged.size):
            return result
        async with writer_lock(recovery_dir, staged.sha256):
            try:
                observed = await text_retry.drained_thread(pdf_files.inspect_file, target)
            except pdf_files.FileNotRegular as exc:
                raise FileRestoreRefused("file_not_regular") from exc
            if observed == (staged.sha256, staged.size):
                return result
            if observed is None and not store.file_restore_assets(staged.sha256):
                os.replace(staged.path, target)
                fsync_directory(papers_dir)
                return Placement(target, staged.sha256, staged.size, "new")
            operation = store.reserve_file_restore(staged.sha256, staged.size, caller=caller, research_id=research_id)
            operation_id = operation["id"]
            try:
                retained = None
                if observed is not None:
                    copy_path = allocate(papers_dir)
                    try:
                        observed = await text_retry.drained_thread(pdf_files.inspect_file, target, copy_path)
                    except pdf_files.FileNotRegular as exc:
                        store.complete_file_restore(operation_id, "file_refused", "file_not_regular")
                        committed = True
                        raise FileRestoreRefused("file_not_regular", operation_id) from exc
                    if observed == (staged.sha256, staged.size):
                        store.record_file_restore_observation(operation_id, "before_restore", **observation(staged, observed))
                        store.complete_file_restore(operation_id, "file_reused")
                        committed = True
                        return Placement(target, staged.sha256, staged.size, "reused", operation_id)
                    if observed is not None:
                        retained = "retained-" + observed[0] + ".bin"
                        retained_path = papers_dir / retained
                        try:
                            existing = await text_retry.drained_thread(
                                lambda: pdf_files.inspect_file(retained_path, sync=True))
                        except pdf_files.FileNotRegular:
                            existing = ("not_regular", -1)
                        if existing is not None and existing != observed:
                            store.record_file_restore_observation(operation_id, "before_restore", **observation(staged, observed))
                            store.complete_file_restore(operation_id, "file_refused", "retention_conflict")
                            committed = True
                            raise FileRestoreRefused("retention_conflict", operation_id)
                        if existing is None:
                            os.replace(copy_path, retained_path)
                        fsync_directory(papers_dir)
                store.record_file_restore_observation(operation_id, "before_restore", **observation(staged, observed, retained))
                refused = False
                with transaction(store.conn):
                    if any(store._asset_run_started(a["source_version_id"]) for a in store.file_restore_assets(staged.sha256)):
                        store.complete_file_restore(operation_id, "file_refused", "run_active")
                        refused = True
                    else:
                        os.replace(staged.path, target)
                if refused:
                    committed = True
                    raise FileRestoreRefused("run_active", operation_id)
                fsync_directory(papers_dir)
                try:
                    after = await text_retry.drained_thread(pdf_files.inspect_file, target)
                except pdf_files.FileNotRegular:
                    after = None
                fields = observation(staged, after)
                store.record_file_restore_observation(operation_id, "after_restore", **fields)
                if fields["integrity"] != "verified":
                    raise RuntimeError("Restored file differs from its expected bytes")
                store.complete_file_restore(operation_id, "file_restored")
                committed = True
                return Placement(target, staged.sha256, staged.size, "restored", operation_id)
            except BaseException as exc:
                if not committed:
                    failure = db.describe_failure(exc)
                    reason = ("cancelled" if isinstance(exc, asyncio.CancelledError) else
                              "storage_full" if failure and failure[0] == "disk_full" else
                              "storage_unavailable" if failure else "unexpected_error")
                    try:
                        if store.conn.in_transaction:
                            raise RuntimeError("File restore interruption requires a closed transaction")
                        store.interrupt_file_restore(operation_id, reason)
                    except BaseException:
                        store.pending_file_restore_interruptions[operation_id] = reason
                        logger.exception("Could not persist file restore interruption %s", operation_id)
                raise
    finally:
        cleanup(copy_path)
        cleanup(staged.path)


async def store_pdf_file(store, papers_dir: Path, recovery_dir: Path | None, data: bytes, *, caller: str,
                         research_id: str | None) -> Placement:
    recovery_dir = resolve_recovery_dir(store, papers_dir, recovery_dir)
    papers_dir.mkdir(parents=True, exist_ok=True)
    path = allocate(papers_dir)
    try:
        sha, size = await text_retry.drained_thread(pdf_files.stage_bytes, path, data)
        staged = Staged(path, sha, size)
    except BaseException:
        cleanup(path)
        raise
    return await restore_file(store, papers_dir, recovery_dir, staged, caller=caller, research_id=research_id)

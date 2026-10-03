"""End abandoned recovery receipts under exclusive file ownership; never retry text."""

from __future__ import annotations

import logging

from deixis.documents import pdf_files
from deixis.workflow import file_restore, text_retry

log = logging.getLogger(__name__)
RECONCILE_REASON = "process_ended"


def _counts():
    return {"text_retries": 0, "file_restores": 0, "live": 0}


async def reconcile_hash(store, papers_dir, recovery_dir, sha256) -> dict:
    """The caller holds this hash's lock, including while observations are drained."""
    store.flush_text_retry_interruptions()
    result = _counts()
    if not store._extraction_has_recovery_metadata:
        return result
    rows = store.conn.execute(
        "SELECT * FROM asset_recovery_operations WHERE expected_sha256 = ? AND lifecycle = 'running'",
        (sha256,)).fetchall()
    for row in rows:
        oid = row["id"]
        if oid in store.pending_text_retry_interruptions or oid in store.pending_file_restore_interruptions:
            continue  # A failed flush retains this process's more specific interruption reason.
        if row["kind"] == "text_retry":
            if store.conn.execute("SELECT 1 FROM asset_extractions WHERE recovery_operation_id = ?", (oid,)).fetchone():
                log.error("Running text retry %s already has an extraction; leaving it running", oid)
                continue
            with file_restore.transaction(store.conn):
                store.interrupt_text_retry(oid, RECONCILE_REASON)
            result["text_retries"] += 1
        else:
            if row["before_observation_id"] is not None and row["after_observation_id"] is None:
                try:
                    observed = await text_retry.drained_thread(pdf_files.inspect_file, papers_dir / (sha256 + ".pdf"))
                except pdf_files.FileNotRegular:
                    pass
                else:
                    staged = file_restore.Staged(papers_dir / (sha256 + ".pdf"), sha256, row["expected_byte_size"])
                    with file_restore.transaction(store.conn):
                        store.record_file_restore_observation(oid, "after_restore", **file_restore.observation(staged, observed))
            with file_restore.transaction(store.conn):
                store.interrupt_file_restore(oid, RECONCILE_REASON)
            result["file_restores"] += 1
    return result


async def reconcile_try_hash(store, papers_dir, recovery_dir, sha256) -> dict:
    store.flush_text_retry_interruptions()
    result = _counts()
    if not store._extraction_has_recovery_metadata:
        return result
    if not store.conn.execute(
            "SELECT 1 FROM asset_recovery_operations WHERE expected_sha256 = ? AND lifecycle = 'running'",
            (sha256,)).fetchone():
        return result
    # Catch only acquisition errors here: a storage failure during reconciliation must reach the driver.
    try:
        lock = text_retry.file_lock(recovery_dir, sha256)
        lock.__enter__()
    except text_retry.FileBusy:
        result["live"] = 1
        return result
    except OSError as exc:
        reported = getattr(store, "_reconcile_lock_errors", None)
        if reported is None:
            reported = store._reconcile_lock_errors = set()
        key = (sha256, exc.errno)
        if key not in reported:
            reported.add(key)
            log.warning("Could not acquire recovery lock for %s (errno=%s); treating it as live", sha256, exc.errno)
        result["live"] = 1
        return result
    try:
        return await reconcile_hash(store, papers_dir, recovery_dir, sha256)
    finally:
        lock.__exit__(None, None, None)


async def reconcile_stale(store, papers_dir, recovery_dir) -> dict:
    store.flush_text_retry_interruptions()
    result = _counts()
    if not store._extraction_has_recovery_metadata:
        return result
    hashes = [row[0] for row in store.conn.execute(
        "SELECT DISTINCT expected_sha256 FROM asset_recovery_operations WHERE lifecycle = 'running'")]
    for sha256 in hashes:
        try:
            counts = await reconcile_try_hash(store, papers_dir, recovery_dir, sha256)
        except Exception as exc:
            reported = getattr(store, "_reconcile_hash_errors", None)
            if reported is None:
                reported = store._reconcile_hash_errors = set()
            key = (sha256, type(exc))
            if key not in reported:
                reported.add(key)
                log.exception("Recovery reconciliation failed for %s; continuing with other hashes", sha256)
            continue
        for key in result:
            result[key] += counts[key]
    return result

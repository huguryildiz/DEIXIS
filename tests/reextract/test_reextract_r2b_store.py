"""New contracts paired with T2 retention/refusal, plus scheduler red-on-old and attachment guards."""

import asyncio
import errno
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

from deixis.documents import pdf_files
from deixis.storage import db, backup
from deixis.workflow import text_retry
try:
    from deixis.workflow import file_restore
except ImportError:
    file_restore = None  # The scheduler reproduction must reach its behavioral assertion on 19d0a48.
from deixis.workflow.store import Store, RecoveryConflict
from tests.reextract.reextract_r2a_helpers import store_library, api_library, child_lock, head, protected
from tests.reextract.reextract_r2b_helpers import tear, write, receipt, research


def no_temporary(lib):
    assert not list(lib.settings.papers_dir.glob("*.part"))
    assert not list(lib.settings.papers_dir.glob("*.partial"))
    assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


def test_live_restore_defers_scheduler_red_on_old(tmp_path):
    with store_library(tmp_path) as lib:
        # 0066 already admits this row on the old code; the first assertion reaches its scheduler defect.
        oid = db.new_id("rop")
        lib.conn.execute("INSERT INTO asset_recovery_operations (id, kind, expected_sha256, expected_byte_size,"
            " idempotency_key, request_fingerprint, lifecycle, created_at) VALUES (?, 'file_restore', ?, ?, ?, ?, 'running', ?)",
            (oid, lib.sha, len(lib.data), "restore-seed", "SYNTHETIC", db.now()))
        held = lib.store.create_run(lib.rid, "answer", {}, None)
        unrelated = research(lib.store)
        free = lib.store.create_run(unrelated, "answer", {}, None)
        with child_lock(lib):
            selected = lib.store.next_queued_run()
            assert selected["id"] == free["id"], "Old scheduler started a research whose shared file is being restored"
            lib.store.update_run(free["id"], status="completed")
            assert lib.store.next_queued_run() is None
        assert lib.store.next_queued_run()["id"] == held["id"]


@pytest.mark.parametrize("state", ["bare", "probe_error", "removed"])
def test_restore_scheduler_conservative_liveness_new_contract(tmp_path, monkeypatch, caplog, state):
    """Paired scheduler red-on-old; same R2a liveness policy including removed sharers."""
    with store_library(tmp_path) as lib:
        if state == "removed":
            lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
        op = lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=None)
        held = lib.store.create_run(lib.rid, "answer", {}, None)
        free = lib.store.create_run(research(lib.store), "answer", {}, None)
        if state == "bare":
            lib.store.recovery_dir = None
        elif state == "probe_error":
            def fail(*args): raise OSError(errno.EIO, "SYNTHETIC probe")
            monkeypatch.setattr(text_retry, "lock_held", fail)
        with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
            assert lib.store.next_queued_run()["id"] == free["id"]
            assert lib.store.next_queued_run()["id"] == free["id"]
        if state == "probe_error":
            assert len([r for r in caplog.records if op["id"] in r.message]) == 1
        lib.store.interrupt_file_restore(op["id"], "cancelled")
        assert lib.store.next_queued_run()["id"] == held["id"]


@pytest.mark.parametrize("kind", ["absent_owned", "torn_unowned", "same_size", "retained_same", "retained_wrong", "retained_symlink", "symlink", "directory", "fifo"])
def test_file_entry_edges_new_contract(tmp_path, kind):
    """Paired T2a retention and no-follow/refusal guards."""
    with store_library(tmp_path) as lib:
        tear(lib)
        before = protected(lib.store)
        retained_path = lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")
        if kind == "absent_owned": lib.path.unlink()
        elif kind == "torn_unowned":
            lib.conn.execute("DELETE FROM asset_extractions WHERE asset_id = ?", (lib.aid,))
            lib.conn.execute("DELETE FROM source_assets WHERE id = ?", (lib.aid,))
        elif kind == "same_size":
            lib.path.write_bytes(b"x" * len(lib.data))
            lib.torn = lib.path.read_bytes()
            lib.torn_sha = hashlib.sha256(lib.torn).hexdigest()
        elif kind == "retained_same":
            retained_path.write_bytes(lib.torn)
            stamp = retained_path.stat().st_mtime_ns
        elif kind == "retained_wrong": retained_path.write_bytes(b"SYNTHETIC conflict")
        elif kind in ("retained_symlink", "symlink"):
            outside = tmp_path / "outside.pdf"; outside.write_bytes(lib.data)
            if kind == "symlink": lib.path.unlink(); lib.path.symlink_to(outside)
            else: retained_path.symlink_to(outside)
        elif kind == "directory": lib.path.unlink(); lib.path.mkdir()
        elif kind == "fifo": lib.path.unlink(); os.mkfifo(lib.path)
        refused = kind in ("retained_wrong", "retained_symlink", "symlink", "directory", "fifo")
        if refused:
            with pytest.raises(file_restore.FileRestoreRefused) as exc: write(lib)
            assert exc.value.code == ("retention_conflict" if kind.startswith("retained") else "file_not_regular")
            if kind.startswith("retained"):
                assert lib.path.read_bytes() == lib.torn
                view = lib.store.latest_file_restore(lib.sha)
                assert (view["outcome"], view["reason"], view["before_integrity"], view["retained"]) == (
                    "file_refused", "retention_conflict", "mismatch", False)
            else:
                assert lib.store.latest_file_restore(lib.sha) is None
            if "symlink" in kind: assert outside.read_bytes() == lib.data
        else:
            result = write(lib)
            assert result.outcome == "restored" and lib.path.read_bytes() == lib.data
            view = lib.store.latest_file_restore(lib.sha)
            assert view["before_integrity"] == ("missing" if kind == "absent_owned" else "mismatch")
            assert view["retained"] == (kind != "absent_owned")
            if kind == "retained_same": assert retained_path.stat().st_mtime_ns == stamp
            if kind not in ("absent_owned", "torn_unowned"): receipt(lib)
        if kind != "torn_unowned": assert protected(lib.store) == before
        no_temporary(lib)


@pytest.mark.parametrize("swap", ["symlink", "fifo"])
def test_regular_entry_swapped_after_first_inspection_never_followed_new_contract(tmp_path, monkeypatch, swap):
    with store_library(tmp_path) as lib:
        tear(lib)
        real, count = pdf_files.inspect_file, [0]
        outside = tmp_path / "outside.pdf"; outside.write_bytes(lib.data)
        def inspect(path, *args, **kwargs):
            if path == lib.path:
                count[0] += 1
                if count[0] == 2:
                    path.unlink()
                    if swap == "symlink": path.symlink_to(outside)
                    else: os.mkfifo(path)
            return real(path, *args, **kwargs)
        monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        with pytest.raises(file_restore.FileRestoreRefused, match="regular"): write(lib)
        assert lib.store.latest_file_restore(lib.sha) is None and outside.read_bytes() == lib.data
        no_temporary(lib)


@pytest.mark.parametrize("when", ["recheck", "copy"])
def test_external_whole_file_reuses_without_replacement_new_contract(tmp_path, monkeypatch, when):
    with store_library(tmp_path) as lib:
        tear(lib)
        real, count = pdf_files.inspect_file, [0]
        def inspect(path, *args, **kwargs):
            if path == lib.path:
                count[0] += 1
                if count[0] == (2 if when == "recheck" else 3): path.write_bytes(lib.data)
            return real(path, *args, **kwargs)
        monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        result = write(lib)
        assert result.outcome == "reused"
        if when == "recheck": assert result.operation_id is None
        else:
            view = lib.store.file_restore_view(result.operation_id)
            assert (view["outcome"], view["before_integrity"], view["retained"]) == ("file_reused", "verified", False)
        assert head(lib.store, lib.aid) == lib.old_head
        no_temporary(lib)


@pytest.mark.parametrize("phase", ["copy_full", "copy_fsync", "retained_fsync", "directory_before", "sqlite_before", "reservation_busy", "replace", "directory_after", "after_mismatch"])
def test_interruption_boundaries_new_contract(tmp_path, monkeypatch, phase):
    """Paired T2a: failures preserve the pre-rename target, or report interruption after rename."""
    with api_library(tmp_path) as lib:
        tear(lib)
        original_error = OSError(errno.ENOSPC if phase == "copy_full" else errno.EIO, "SYNTHETIC failure")
        def fail(*args, **kwargs): raise original_error
        if phase == "copy_full":
            real = pdf_files.inspect_file
            def inspect(path, copy_path=None, **kwargs):
                if copy_path is not None: raise original_error
                return real(path, copy_path, **kwargs)
            monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        elif phase in ("copy_fsync", "retained_fsync"):
            real = file_restore.os.fsync
            if phase == "retained_fsync":
                (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).write_bytes(lib.torn)
            def sync(fd):
                # Resolve only test-owned descriptors on macOS without /proc.
                import fcntl
                try: name = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0")[0].decode()
                except OSError: name = ""
                if (phase == "copy_fsync" and name.endswith(".part")) or (phase == "retained_fsync" and name.endswith(".bin")):
                    raise original_error
                return real(fd)
            monkeypatch.setattr(file_restore.os, "fsync", sync)
        elif phase.startswith("directory"):
            real, count = file_restore.fsync_directory, [0]
            def sync(path):
                count[0] += 1
                if count[0] == (1 if phase == "directory_before" else 2): raise original_error
                return real(path)
            monkeypatch.setattr(file_restore, "fsync_directory", sync)
        elif phase in ("sqlite_before", "reservation_busy"):
            original_error = sqlite3.OperationalError("SYNTHETIC SQLite failure")
            original_error.sqlite_errorcode = sqlite3.SQLITE_FULL if phase == "sqlite_before" else sqlite3.SQLITE_BUSY
            monkeypatch.setattr(lib.store, "record_file_restore_observation" if phase == "sqlite_before" else "reserve_file_restore", fail)
        elif phase == "replace":
            real = file_restore.os.replace
            def replace(src, dest):
                if Path(dest) == lib.path: raise original_error
                return real(src, dest)
            monkeypatch.setattr(file_restore.os, "replace", replace)
        else:
            real = pdf_files.inspect_file
            def inspect(path, *args, **kwargs):
                if path == lib.path and lib.path.read_bytes() == lib.data: lib.path.write_bytes(b"SYNTHETIC external change")
                return real(path, *args, **kwargs)
            monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        response = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert response.status_code == (507 if phase in ("copy_full", "sqlite_before") else 503 if phase == "reservation_busy" else 500)
        view = lib.store.latest_file_restore(lib.sha)
        if phase == "reservation_busy": assert view is None
        else:
            assert view["lifecycle"] == "interrupted" and view["reason"] == (
                "storage_full" if phase in ("copy_full", "sqlite_before") else "unexpected_error")
            if phase == "after_mismatch": assert view["after_integrity"] == "mismatch"
        assert lib.path.read_bytes() == (lib.data if phase == "directory_after" else
            b"SYNTHETIC external change" if phase == "after_mismatch" else lib.torn)
        assert head(lib.store, lib.aid) == lib.old_head and not lib.conn.in_transaction
        no_temporary(lib)


class CommitFailure:
    """Actual transactions/statements with injected COMMIT failure before SQLite receives it."""
    def __init__(self, conn, failures):
        self.conn, self.failures, self.commits = conn, set(failures), 0

    def __getattr__(self, name): return getattr(self.conn, name)

    def execute(self, sql, *args):
        if sql == "COMMIT":
            self.commits += 1
            if self.commits in self.failures:
                error = sqlite3.OperationalError("SYNTHETIC COMMIT busy")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error
        return self.conn.execute(sql, *args)


@pytest.mark.parametrize("boundary", [1, 2, 3, 4, 5])
def test_failed_commit_at_each_boundary_rolls_back_new_contract(tmp_path, boundary):
    """Reservation, before observation, replacement, after observation and completion; paired T2a."""
    with store_library(tmp_path) as lib:
        tear(lib)
        lib.store.conn = CommitFailure(lib.conn, [boundary])
        with pytest.raises(sqlite3.OperationalError, match="COMMIT"): write(lib)
        assert not lib.conn.in_transaction
        second = db.connect(lib.settings.db_path)
        try:
            operations = [dict(row) for row in second.execute("SELECT * FROM asset_recovery_operations")]
            if boundary == 1:
                assert operations == []
            else:
                assert operations[0]["lifecycle"] == "interrupted" and operations[0]["reason"] == "storage_unavailable"
                assert (operations[0]["before_observation_id"] is not None) == (boundary >= 3)
                assert (operations[0]["after_observation_id"] is not None) == (boundary == 5)
                assert second.execute("SELECT count(*) FROM events WHERE type = 'asset_file_restore_finished'").fetchone()[0] == 1
        finally: second.close()
        assert lib.path.read_bytes() == (lib.data if boundary >= 3 else lib.torn)
        no_temporary(lib)


def test_interruption_commit_and_pending_flush_commit_failure_new_contract(tmp_path, monkeypatch):
    """Paired T2a; each failed terminal COMMIT is invisible to a second connection and retried once."""
    with store_library(tmp_path) as lib:
        tear(lib)
        wrapper = CommitFailure(lib.conn, [2, 3])
        lib.store.conn = wrapper
        real = pdf_files.inspect_file
        original = OSError(errno.ENOSPC, "SYNTHETIC copy full")
        def inspect(path, copy_path=None, **kwargs):
            if copy_path is not None: raise original
            return real(path, copy_path, **kwargs)
        monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        with pytest.raises(OSError) as exc: write(lib)
        assert exc.value is original and not lib.conn.in_transaction
        assert lib.store.pending_file_restore_interruptions
        lib.store.flush_text_retry_interruptions()  # third COMMIT fails too
        assert not lib.conn.in_transaction and lib.store.pending_file_restore_interruptions
        second = db.connect(lib.settings.db_path)
        try:
            assert second.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "running"
            assert second.execute("SELECT count(*) FROM events WHERE type = 'asset_file_restore_finished'").fetchone()[0] == 0
            lib.store.flush_text_retry_interruptions()
            assert second.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "interrupted"
            assert second.execute("SELECT count(*) FROM events WHERE type = 'asset_file_restore_finished'").fetchone()[0] == 1
        finally: second.close()
        assert not lib.store.pending_file_restore_interruptions and not lib.conn.in_transaction
        no_temporary(lib)


@pytest.mark.parametrize("both", [False, True])
def test_terminal_event_failure_rolls_back_and_flushes_once_new_contract(tmp_path, monkeypatch, both):
    with store_library(tmp_path) as lib:
        tear(lib)
        real, calls = lib.store._event, [0]
        def event(*args, **kwargs):
            calls[0] += 1
            if calls[0] <= (2 if both else 1): raise RuntimeError("SYNTHETIC event failure")
            return real(*args, **kwargs)
        monkeypatch.setattr(lib.store, "_event", event)
        with pytest.raises(RuntimeError, match="event"): write(lib)
        assert lib.store.latest_file_restore(lib.sha)["lifecycle"] == ("running" if both else "interrupted")
        assert bool(lib.store.pending_file_restore_interruptions) == both
        lib.store.flush_text_retry_interruptions()
        assert lib.store.latest_file_restore(lib.sha)["lifecycle"] == "interrupted"
        assert lib.conn.execute("SELECT count(*) FROM events WHERE type = 'asset_file_restore_finished'").fetchone()[0] == 1
        assert lib.path.read_bytes() == lib.data
        no_temporary(lib)


def test_run_starts_after_reservation_final_check_refuses_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        tear(lib)
        real = pdf_files.inspect_file
        def inspect(path, copy_path=None, **kwargs):
            value = real(path, copy_path, **kwargs)
            if copy_path is not None:
                conn = db.connect(lib.settings.db_path)
                try:
                    store = Store(conn)
                    run = store.create_run(lib.rid, "answer", {}, None)
                    store.update_run(run["id"], status="running")
                finally: conn.close()
            return value
        monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        with pytest.raises(file_restore.FileRestoreRefused) as exc: write(lib)
        assert exc.value.code == "run_active" and lib.path.read_bytes() == lib.torn
        view = lib.store.latest_file_restore(lib.sha)
        assert (view["outcome"], view["before_integrity"], view["retained"], view["after_integrity"]) == (
            "file_refused", "mismatch", True, None)
        no_temporary(lib)


@pytest.mark.parametrize("shared", [False, True])
def test_backup_and_purge_keep_receipt_and_retained_bytes_new_contract(tmp_path, shared):
    """R3 includes retained evidence in backup; only source sharing keeps unpurged receipts."""
    with store_library(tmp_path) as lib:
        tear(lib)
        # Keep S1 held elsewhere while purging the initiating research.
        if shared:
            other = research(lib.store)
            lib.store.add_to_corpus(other, lib.svid, "user_upload")
        result = write(lib)
        saved = lib.store.file_restore_view(result.operation_id)
        path = lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")
        archive = backup.create_backup(lib.settings, tmp_path / "backups")
        assert archive.is_dir()
        assert (archive / "papers" / path.name).read_bytes() == lib.torn
        lib.store.trash_research(lib.rid)
        files, _ = lib.store.purge_research(lib.rid)
        if shared:
            assert lib.store.file_restore_view(result.operation_id) == saved and path.read_bytes() == lib.torn
            assert lib.conn.execute("SELECT count(*) FROM asset_file_observations WHERE operation_id = ?", (result.operation_id,)).fetchone()[0] == 2
            assert path.name not in files
        else:
            assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations WHERE id = ?", (result.operation_id,)).fetchone()[0] == 0
            assert lib.conn.execute("SELECT count(*) FROM asset_file_observations WHERE operation_id = ?", (result.operation_id,)).fetchone()[0] == 0
            assert path.name in files


@pytest.mark.parametrize("outcome,reason", [("file_restored", None), ("file_reused", None), ("file_refused", "run_active")])
def test_terminal_methods_replay_and_closed_public_view_new_contract(tmp_path, outcome, reason):
    with store_library(tmp_path) as lib:
        op = lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
        result = lib.store.complete_file_restore(op["id"], outcome, reason)
        assert set(result) == {"operation_id", "lifecycle", "outcome", "reason", "sha256", "before_integrity", "after_integrity", "retained", "created_at", "finished_at"}
        before = lib.conn.execute("SELECT count(*) FROM events").fetchone()[0]
        assert lib.store.complete_file_restore(op["id"], outcome, reason) == result
        assert lib.store.interrupt_file_restore(op["id"], "cancelled") == result
        assert lib.conn.execute("SELECT count(*) FROM events").fetchone()[0] == before
        for args in (("invented", None), ("file_restored", "run_active"), ("file_refused", None), ("file_refused", "invented")):
            with pytest.raises(ValueError): lib.store.complete_file_restore(op["id"], *args)
        with pytest.raises(ValueError): lib.store.interrupt_file_restore(op["id"], "invented")
        retry = lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid,
            idempotency_key="text-key", request_fingerprint="text-key")
        for end in (lambda: lib.store.complete_file_restore(retry["id"], "file_reused"),
                    lambda: lib.store.interrupt_file_restore(retry["id"], "cancelled")):
            with pytest.raises(RecoveryConflict): end()


def test_new_unowned_attachment_has_no_receipt_or_input_observation_new_contract(tmp_path):
    """Paired initial_attachment_keeps_unknown_input_and_no_receipt_guard: new Placement outcome."""
    with store_library(tmp_path) as lib:
        lib.conn.execute("DELETE FROM asset_extractions WHERE asset_id = ?", (lib.aid,))
        lib.conn.execute("DELETE FROM source_assets WHERE id = ?", (lib.aid,))
        lib.path.unlink()
        result = write(lib)
        assert result.outcome == "new" and result.operation_id is None and lib.path.read_bytes() == lib.data
        assert lib.store.latest_file_restore(lib.sha) is None
        assert lib.conn.execute("SELECT count(*) FROM asset_file_observations").fetchone()[0] == 0
        no_temporary(lib)


def test_paused_run_and_duplicate_after_restore_new_contract(tmp_path):
    """Paired whole_duplicates_keep_policy_and_mtime_guard and T2a: paused runs permit repair."""
    with store_library(tmp_path) as lib:
        tear(lib)
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        lib.store.update_run(run["id"], status="paused")
        first = write(lib)
        receipt(lib)
        stamp = lib.path.stat().st_mtime_ns
        second = write(lib)
        assert second.outcome == "reused" and second.operation_id is None
        assert lib.path.stat().st_mtime_ns == stamp
        assert lib.store.latest_file_restore(lib.sha) == lib.store.file_restore_view(first.operation_id)

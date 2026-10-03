"""Temporary-file, concurrency and static contracts paired with T2a and the child-lock red assertions."""

import ast
import asyncio
import errno
import hashlib
import io
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from deixis.api.app import store_upload
from deixis.documents import pdf, pdf_files
from deixis.storage import db
from deixis.workflow import file_restore, text_retry
from deixis.workflow.store import Store
from tests.helpers import make_pdf
from tests.reextract_r2a_helpers import api_library, store_library, child_lock
from tests.reextract_r2b_helpers import tear, write


async def wait_thread(event):
    for _ in range(1500):
        if event.is_set(): return
        await asyncio.sleep(0.01)
    pytest.fail("SYNTHETIC thread did not enter in 15 s")


def observe_lock_wait(monkeypatch):
    busy = threading.Event()
    real = text_retry.file_lock
    @contextmanager
    def lock(*args):
        try:
            with real(*args):
                yield
        except text_retry.FileBusy:
            busy.set()
            raise
    monkeypatch.setattr(text_retry, "file_lock", lock)
    return busy


def test_identical_new_writers_wait_then_reuse_without_receipt(tmp_path, monkeypatch):
    """Regression paired with the unchanged parallel fulltext workflow assertions."""
    with store_library(tmp_path) as lib:
        data = make_pdf(["SYNTHETIC concurrent new file"])
        sha = hashlib.sha256(data).hexdigest()
        target = lib.settings.papers_dir / (sha + ".pdf")
        entered, release = threading.Event(), threading.Event()
        busy = observe_lock_wait(monkeypatch)
        real = pdf_files.inspect_file
        def inspect(path, *args, **kwargs):
            if path == target and text_retry.lock_held(lib.settings.recovery_dir, sha) and not entered.is_set():
                entered.set()
                assert release.wait(15)
            return real(path, *args, **kwargs)
        monkeypatch.setattr(pdf_files, "inspect_file", inspect)
        # Both callers inspect an absent path before contending for its lock.
        monkeypatch.setattr(pdf_files, "file_is_whole", lambda *args: False)
        async def scenario():
            async def write_new():
                return await file_restore.store_pdf_file(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                    data, caller="run_fetch", research_id=lib.rid)
            first = asyncio.create_task(write_new())
            await wait_thread(entered)
            second = asyncio.create_task(write_new())
            await wait_thread(busy)
            assert not second.done() and len(list(lib.settings.papers_dir.glob("*.part"))) == 2
            release.set()
            results = await asyncio.gather(first, second)
            assert [result.outcome for result in results] == ["new", "reused"]
            assert all(result.operation_id is None for result in results)
        try:
            asyncio.run(scenario())
        finally:
            release.set()
        assert target.read_bytes() == data
        assert not list(lib.settings.papers_dir.glob("*.part"))
        assert not text_retry.lock_held(lib.settings.recovery_dir, sha)
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


def test_writer_child_lock_timeout_cleans_staging_without_receipt(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        tear(lib)
        monkeypatch.setattr(file_restore, "WRITER_LOCK_WAIT_SECONDS", 0.1)
        busy = observe_lock_wait(monkeypatch)
        with child_lock(lib):
            started = time.monotonic()
            with pytest.raises(text_retry.FileBusy):
                write(lib)
            assert time.monotonic() - started >= 0.1
            assert busy.is_set() and text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        assert lib.path.read_bytes() == lib.torn
        assert not list(lib.settings.papers_dir.glob("*.part"))
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


def test_writer_cancelled_while_waiting_cleans_staging_without_receipt(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        tear(lib)
        busy = observe_lock_wait(monkeypatch)
        async def scenario():
            with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
                task = asyncio.create_task(file_restore.store_pdf_file(lib.store, lib.settings.papers_dir,
                    lib.settings.recovery_dir, lib.data, caller="upload", research_id=lib.rid))
                await wait_thread(busy)
                assert not task.done() and len(list(lib.settings.papers_dir.glob("*.part"))) == 1
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
                assert not list(lib.settings.papers_dir.glob("*.part"))
        asyncio.run(scenario())
        assert lib.path.read_bytes() == lib.torn
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


@pytest.mark.parametrize("phase", ["staging", "retention", "matching"])
def test_cancelled_file_threads_drain_before_cleanup_new_contract(tmp_path, monkeypatch, phase):
    with api_library(tmp_path) as lib:
        tear(lib)
        entered, release = threading.Event(), threading.Event()
        real = pdf_files.stage_bytes if phase == "staging" else pdf_files.inspect_file if phase == "retention" else pdf.extract_pdf
        paths = []
        def blocked(*args, **kwargs):
            should_block = phase != "retention" or (len(args) > 1 and args[1] is not None)
            if should_block:
                paths.append(args[1] if phase == "retention" else args[0])
                entered.set(); assert release.wait(15)
            return real(*args, **kwargs)
        monkeypatch.setattr(pdf_files if phase != "matching" else pdf,
                            "stage_bytes" if phase == "staging" else "inspect_file" if phase == "retention" else "extract_pdf", blocked)
        async def scenario():
            if phase == "matching":
                endpoint = next(r.endpoint for r in lib.app.routes if getattr(r, "name", "") == "match_uploads")
                task = asyncio.create_task(endpoint(lib.rid, Request({"type": "http", "app": lib.app}),
                                                    [UploadFile(io.BytesIO(lib.data), filename="same.pdf")]))
            else:
                task = asyncio.create_task(file_restore.store_pdf_file(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                    lib.data, caller="upload", research_id=lib.rid))
            await wait_thread(entered)
            task.cancel(); await asyncio.sleep(0.02)
            assert not task.done() and paths[0].exists()
            if phase == "retention": assert text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
        try: asyncio.run(scenario())
        finally: release.set()
        assert lib.path.read_bytes() == lib.torn
        assert not list(lib.settings.papers_dir.glob("*.part")) and not list(lib.settings.papers_dir.glob("*.partial"))
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        if phase == "retention":
            view = lib.store.latest_file_restore(lib.sha)
            assert (view["lifecycle"], view["reason"]) == ("interrupted", "cancelled")
        else: assert lib.store.latest_file_restore(lib.sha) is None


@pytest.mark.parametrize("phase", ["invalid_caller", "matching_parser", "waiting_refusal", "upload_cancel", "upload_header", "upload_size"])
def test_pre_handover_errors_remove_temporary_files_new_contract(tmp_path, monkeypatch, phase):
    with api_library(tmp_path) as lib:
        tear(lib)
        original = RuntimeError("SYNTHETIC parser error")
        if phase == "invalid_caller":
            with pytest.raises(ValueError): write(lib, caller="invalid")
        elif phase == "matching_parser":
            def fail(*args): raise original
            monkeypatch.setattr(pdf, "extract_pdf", fail)
            response = lib.client.post(f"/api/researches/{lib.rid}/uploads/match", files=[("files", ("same.pdf", lib.data, "application/pdf"))])
            assert response.status_code == 500
        elif phase == "waiting_refusal":
            response = lib.client.post(f"/api/researches/{lib.rid}/waiting/uploads", data={"work_id": "wrk_missing", "source_version_id": lib.svid,
                "scope_revision": 1, "versions_digest": "wrong", "sha256": lib.sha}, files={"file": ("same.pdf", lib.data, "application/pdf")})
            assert response.status_code == 409
        elif phase == "upload_cancel":
            class CancelledUpload:
                async def read(self, size): raise asyncio.CancelledError()
            with pytest.raises(asyncio.CancelledError): asyncio.run(store_upload(CancelledUpload(), lib.settings.papers_dir))
        else:
            if phase == "upload_size":
                monkeypatch.setattr("deixis.api.app.MAX_UPLOAD_BYTES", len(lib.data) - 1)
            response = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("same.pdf",
                lib.data if phase == "upload_size" else b"not a PDF", "application/pdf")})
            assert response.status_code == (413 if phase == "upload_size" else 422)
        assert lib.path.read_bytes() == lib.torn
        assert not list(lib.settings.papers_dir.glob("*.part")) and not list(lib.settings.papers_dir.glob("*.partial"))
        assert lib.store.latest_file_restore(lib.sha) is None


def test_cleanup_failure_is_logged_and_original_exception_survives_new_contract(tmp_path, monkeypatch, caplog):
    with store_library(tmp_path) as lib:
        tear(lib)
        real = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.suffix == ".part": raise OSError(errno.EACCES, "SYNTHETIC unlink denied")
            return real(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", unlink)
        with pytest.raises(ValueError, match="writer"): write(lib, caller="invalid")
        assert "Could not remove" in caplog.text
        assert lib.path.read_bytes() == lib.torn
        monkeypatch.setattr(Path, "unlink", real)
        for path in lib.settings.papers_dir.glob("*.part"): path.unlink()


@pytest.mark.parametrize("direction", ["retry_blocks_restore", "restore_blocks_retry"])
def test_text_retry_and_restore_exclude_each_other_new_contract(tmp_path, monkeypatch, direction):
    monkeypatch.setattr(file_restore, "WRITER_LOCK_WAIT_SECONDS", 0.1)
    with store_library(tmp_path) as lib:
        entered, release = threading.Event(), threading.Event()
        real = pdf.extract_pdf if direction == "retry_blocks_restore" else pdf_files.inspect_file
        def blocked(*args, **kwargs):
            if direction == "retry_blocks_restore" or len(args) > 1:
                entered.set(); assert release.wait(15)
            return real(*args, **kwargs)
        monkeypatch.setattr(pdf if direction == "retry_blocks_restore" else pdf_files,
                            "extract_pdf" if direction == "retry_blocks_restore" else "inspect_file", blocked)
        async def retry():
            return await text_retry.execute_text_retry(lib.store, lib.settings, asset_id=lib.aid,
                expected_extraction_id=lib.eid, idempotency_key="parked-retry", research_id=lib.rid, source_version_id=lib.svid)
        async def restore():
            return await file_restore.store_pdf_file(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                lib.data, caller="upload", research_id=lib.rid)
        async def scenario():
            if direction == "restore_blocks_retry": tear(lib)
            task = asyncio.create_task(retry() if direction == "retry_blocks_restore" else restore())
            await wait_thread(entered)
            if direction == "retry_blocks_restore": tear(lib)  # Test-owned outside change while private bytes are parsed.
            with pytest.raises(text_retry.FileBusy):
                await (restore() if direction == "retry_blocks_restore" else retry())
            release.set()
            result = await task
            assert result["outcome"] == "promoted" if direction == "retry_blocks_restore" else result.outcome == "restored"
        try: asyncio.run(scenario())
        finally: release.set()
        assert not list(lib.settings.papers_dir.glob("*.part"))


@pytest.mark.parametrize("timeout", [False, True])
def test_replacement_waits_for_competing_write_transaction_new_contract(tmp_path, monkeypatch, timeout):
    with store_library(tmp_path) as lib:
        tear(lib)
        second = db.connect(lib.settings.db_path)
        lib.conn.execute("PRAGMA busy_timeout = 25" if timeout else "PRAGMA busy_timeout = 2000")
        real_record, real_replace = lib.store.record_file_restore_observation, file_restore.os.replace
        releases = []
        def record(oid, kind, **fields):
            result = real_record(oid, kind, **fields)
            if kind == "before_restore":
                second.execute("BEGIN IMMEDIATE")
                store = Store(second)
                run = store.create_run(lib.rid, "answer", {}, None)
                store.update_run(run["id"], status="running")
                def release():
                    time.sleep(0.2)
                    second.execute("COMMIT")
                thread = threading.Thread(target=release)
                thread.start(); releases.append(thread)
            return result
        def replace(src, dest):
            if Path(dest) == lib.path: assert not second.in_transaction
            return real_replace(src, dest)
        monkeypatch.setattr(lib.store, "record_file_restore_observation", record)
        monkeypatch.setattr(file_restore.os, "replace", replace)
        try:
            with pytest.raises(sqlite3.OperationalError if timeout else file_restore.FileRestoreRefused): write(lib)
            assert lib.path.read_bytes() == lib.torn and not lib.conn.in_transaction
            for thread in releases: thread.join(5)
            lib.store.flush_text_retry_interruptions()
            view = lib.store.latest_file_restore(lib.sha)
            assert (view["lifecycle"], view["reason"]) == (
                "interrupted" if timeout else "completed", "storage_unavailable" if timeout else "run_active")
        finally:
            for thread in releases: thread.join(5)
            second.close()


def test_lock_directory_resolution_never_splits_namespace_new_contract(tmp_path):
    with store_library(tmp_path) as lib:
        papers = lib.settings.papers_dir
        with pytest.raises(ValueError): file_restore.resolve_recovery_dir(lib.store, papers, tmp_path / "different")
        assert file_restore.resolve_recovery_dir(lib.store, papers) == lib.settings.recovery_dir
        lib.store.recovery_dir = None
        assert file_restore.resolve_recovery_dir(lib.store, papers) == papers.parent / "recovery"
        assert file_restore.resolve_recovery_dir(lib.store, papers, tmp_path / "explicit") == tmp_path / "explicit"


def test_only_restore_driver_places_active_library_hash_paths_static_guard():
    root = Path(__file__).resolve().parents[1] / "backend" / "deixis"
    allow = {"workflow/file_restore.py", "storage/backup.py", "credentials.py", "documents/local_embedding.py",
             "documents/arxiv_source.py", "workflow/local_embedding_service.py"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "replace"]
        if calls: assert str(path.relative_to(root)) in allow
    assert not hasattr(pdf_files, "store_pdf_file")

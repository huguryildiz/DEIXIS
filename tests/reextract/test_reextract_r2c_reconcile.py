"""R6 red-on-old; R7/R8 ownership, rollback and no-retry contracts; R9/R12 guards."""

import asyncio
import errno
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow import file_restore, text_retry
from deixis.workflow.worker import Worker
from tests.reextract_r2a_helpers import api_library, body, counts, head, protected, seed, sharing, store_library, url
from tests.reextract_r2b_helpers import tear
from tests.reextract_r2c_helpers import ROOT, child, events, forbid_calls, release_child, startup
from tests.reextract.test_reextract_r2a_store import reserve, record
from tests.reextract.test_reextract_r2b_store import CommitFailure


def test_r7_pre_recovery_schema_uses_no_table_or_lock_new_contract(tmp_path, monkeypatch):
    from deixis.workflow import reconcile
    from deixis.workflow.store import Store
    conn = db.connect(tmp_path / "historical.sqlite")
    try:
        conn.execute("CREATE TABLE asset_extractions (id TEXT PRIMARY KEY)")
        store = Store(conn)
        calls = []
        conn.set_trace_callback(calls.append)
        forbid_calls(monkeypatch)
        def forbidden(*args):
            raise AssertionError("A pre-recovery schema attempted a file lock")
        monkeypatch.setattr(text_retry, "file_lock", forbidden)
        for call in (reconcile.reconcile_hash, reconcile.reconcile_try_hash):
            assert asyncio.run(call(store, tmp_path / "papers", tmp_path / "recovery", "a" * 64)) == {
                "text_retries": 0, "file_restores": 0, "live": 0}
        assert asyncio.run(reconcile.reconcile_stale(store, tmp_path / "papers", tmp_path / "recovery")) == {
            "text_retries": 0, "file_restores": 0, "live": 0}
        assert calls == [] and not (tmp_path / "recovery").exists()
    finally:
        conn.close()


@pytest.mark.parametrize("entry", ["missing", "symlink", "fifo", "present", "torn"])
def test_r6_no_body_checks_same_profile_file_red_on_old_and_guards(tmp_path, entry):
    with api_library(tmp_path) as lib:
        if entry not in ("present", "torn"):
            lib.path.unlink()
            if entry == "symlink":
                outside = tmp_path / "outside.pdf"; outside.write_bytes(lib.data); lib.path.symlink_to(outside)
            elif entry == "fifo": os.mkfifo(lib.path)
        elif entry == "torn": tear(lib)
        before = counts(lib.store)
        response = lib.client.post(url(lib))
        assert response.status_code == (200 if entry in ("present", "torn") else 404), response.text
        if response.status_code == 404: assert response.json()["detail"] == "File missing"
        else: assert response.json()["reextraction"]["outcome"] == "unchanged"
        assert counts(lib.store) == before


@pytest.mark.parametrize("entry", ["symlink", "fifo"])
def test_r6_older_profile_nonregular_file_guard(tmp_path, entry):
    with api_library(tmp_path, version="SYNTHETIC-older-profile") as lib:
        lib.path.unlink()
        if entry == "symlink":
            outside = tmp_path / "outside.pdf"
            outside.write_bytes(lib.data)
            lib.path.symlink_to(outside)
        else:
            os.mkfifo(lib.path)
        before = counts(lib.store)
        response = lib.client.post(url(lib))
        assert response.status_code == 404 and response.json()["detail"] == "File missing"
        assert counts(lib.store) == before


@pytest.mark.parametrize("kind", ["text", "restore"])
def test_r7_live_child_is_not_reconciled_by_any_entry_new_contract(tmp_path, monkeypatch, kind):
    with store_library(tmp_path) as lib:
        if kind == "restore":
            tear(lib); (lib.settings.data_dir / "synthetic-full.pdf").write_bytes(lib.data)
        boundary = "parser" if kind == "text" else "retention_copy"
        with child(lib, "park_" + kind, boundary, parked=True) as process:
            forbid_calls(monkeypatch)
            from deixis.workflow import reconcile
            result = asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
            assert result == {"text_retries": 0, "file_restores": 0, "live": 1}
            worker = Worker(lib.store, SimpleNamespace(deps=SimpleNamespace(settings=lib.settings)), lib.settings.lock_path)
            assert asyncio.run(worker.reconcile_recovery()) == result
            with startup(lib) as (app, _):
                assert app.state.reconciled == result
                operation = dict(app.state.store.conn.execute("SELECT * FROM asset_recovery_operations").fetchone())
                assert operation["lifecycle"] == "running"
            run = lib.store.create_run(lib.rid, "answer", {}, None)
            assert lib.store.next_queued_run() is None
            release_child(process)
        operation = lib.store._text_retry_operation(operation["id"])
        assert operation["lifecycle"] == "completed"
        assert len(events(lib.store, "asset_text_retried" if kind == "text" else "asset_file_restore_finished", operation["id"])) == 1
        assert lib.store.next_queued_run()["id"] == run["id"]


@pytest.mark.parametrize("kind", ["text", "restore", "pending_text"])
def test_r7_failed_commit_rolls_back_and_next_sweep_ends_once_new_contract(tmp_path, monkeypatch, kind):
    with store_library(tmp_path) as lib:
        op = reserve(lib) if kind != "restore" else lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
        if kind == "pending_text": lib.store.pending_text_retry_interruptions[op["id"]] = "storage_full"
        lib.store.conn = CommitFailure(lib.conn, [1])
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        second = db.connect(lib.settings.db_path)
        try:
            with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
                if kind == "pending_text":
                    lib.store.flush_text_retry_interruptions()
                    assert op["id"] in lib.store.pending_text_retry_interruptions
                else:
                    with pytest.raises(sqlite3.OperationalError):
                        asyncio.run(reconcile.reconcile_hash(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir, lib.sha))
            assert not lib.conn.in_transaction
            assert second.execute("SELECT lifecycle FROM asset_recovery_operations WHERE id = ?", (op["id"],)).fetchone()[0] == "running"
            assert second.execute("SELECT count(*) FROM events WHERE type IN ('asset_text_retried', 'asset_file_restore_finished')").fetchone()[0] == 0
            asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
            row = lib.store._text_retry_operation(op["id"])
            assert row["reason"] == ("storage_full" if kind == "pending_text" else "process_ended")
            assert len(events(lib.store, "asset_file_restore_finished" if kind == "restore" else "asset_text_retried", op["id"])) == 1
        finally: second.close()


@pytest.mark.parametrize("failures", [1, 2])
def test_r7_failed_hash_does_not_abort_other_stale_hashes_new_contract(tmp_path, monkeypatch, caplog, failures):
    """Paired with R2 startup reconciliation and the failed-COMMIT rollback contract."""
    with store_library(tmp_path) as lib:
        other = seed(lib.store, lib.settings, data=lib.data + b"\nSYNTHETIC other hash")
        operations = {lib.sha: reserve(lib), other.sha: reserve(other, "other_request")}
        hashes = [row[0] for row in lib.conn.execute(
            "SELECT DISTINCT expected_sha256 FROM asset_recovery_operations WHERE lifecycle = 'running'")]
        first, second = (operations[sha] for sha in hashes)
        interrupt, remaining, calls = lib.store.interrupt_text_retry, [failures], []
        def fail_first(oid, reason):
            calls.append(oid)
            if oid == first["id"] and remaining[0]:
                remaining[0] -= 1
                raise sqlite3.OperationalError("SYNTHETIC per-hash interruption failure")
            return interrupt(oid, reason)
        monkeypatch.setattr(lib.store, "interrupt_text_retry", fail_first)
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        def sweep():
            return asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
        assert sweep() == {"text_retries": 1, "file_restores": 0, "live": 0}
        assert calls == [first["id"], second["id"]]
        assert not lib.conn.in_transaction
        assert lib.store.text_retry_view(first["id"])["lifecycle"] == "running"
        assert events(lib.store, "asset_text_retried", first["id"]) == []
        assert lib.store.text_retry_view(second["id"])["reason"] == "process_ended"
        if failures == 2:
            assert sweep() == {"text_retries": 0, "file_restores": 0, "live": 0}
            assert lib.store.text_retry_view(first["id"])["lifecycle"] == "running"
        assert sweep() == {"text_retries": 1, "file_restores": 0, "live": 0}
        assert sweep() == {"text_retries": 0, "file_restores": 0, "live": 0}
        logged = [r for r in caplog.records if "Recovery reconciliation failed for" in r.message]
        assert len(logged) == 1 and hashes[0] in logged[0].message
        assert logged[0].exc_info[0] is sqlite3.OperationalError
        for op in operations.values():
            assert lib.store.text_retry_view(op["id"])["reason"] == "process_ended"
            assert len(events(lib.store, "asset_text_retried", op["id"])) == 1
        assert all(not text_retry.lock_held(lib.settings.recovery_dir, sha) for sha in hashes)


@pytest.mark.parametrize("entry", ["reconcile_hash", "reconcile_try_hash"])
def test_r7_lazy_hash_failure_still_propagates_new_contract(tmp_path, monkeypatch, entry):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        lib.store.conn = CommitFailure(lib.conn, [1])
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        call = getattr(reconcile, entry)
        with pytest.raises(sqlite3.OperationalError):
            if entry == "reconcile_hash":
                with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
                    asyncio.run(call(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir, lib.sha))
            else:
                asyncio.run(call(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir, lib.sha))
        assert not lib.conn.in_transaction and not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        assert lib.store.text_retry_view(op["id"])["lifecycle"] == "running"
        assert events(lib.store, "asset_text_retried", op["id"]) == []


def test_r7_pending_reason_is_kept_after_failed_flush_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        lib.store.pending_text_retry_interruptions[op["id"]] = "storage_full"
        lib.store.conn = CommitFailure(lib.conn, [1])
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
            result = asyncio.run(reconcile.reconcile_hash(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir, lib.sha))
        assert result == {"text_retries": 0, "file_restores": 0, "live": 0}
        assert lib.store.text_retry_view(op["id"])["lifecycle"] == "running"
        assert lib.store.pending_text_retry_interruptions == {op["id"]: "storage_full"}
        lib.store.flush_text_retry_interruptions()
        assert lib.store.text_retry_view(op["id"])["reason"] == "storage_full"
        assert len(events(lib.store, "asset_text_retried", op["id"])) == 1


def test_r7_impossible_candidate_is_logged_and_not_relabelled_new_contract(tmp_path, monkeypatch, caplog):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        lib.conn.execute("INSERT INTO asset_extractions (id, asset_id, extraction_version, extractor_profile, status, page_count,"
            " text_pages, passage_count, outcome, recovery_operation_id, baseline_extraction_id, created_at)"
            " VALUES ('ext_impossible', ?, ?, 'SYNTHETIC', 'failed', 0, 0, 0, 'rejected', ?, ?, ?)",
            (lib.aid, 'SYNTHETIC+reextract-' + op["id"], op["id"], lib.eid, db.now()))
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        result = asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
        assert result["text_retries"] == 0 and lib.store.text_retry_view(op["id"])["lifecycle"] == "running"
        assert op["id"] in caplog.text and "already has an extraction" in caplog.text


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO])
def test_r7_lock_oserror_logs_once_per_hash_errno_new_contract(tmp_path, monkeypatch, caplog, error):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        def fail(*args): raise OSError(error, "SYNTHETIC lock failure")
        monkeypatch.setattr(text_retry, "file_lock", fail)
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        for _ in range(3):
            assert asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))["live"] == 1
        assert len([r for r in caplog.records if "Could not acquire recovery lock" in r.message]) == 1
        assert lib.store.text_retry_view(op["id"])["lifecycle"] == "running"


def test_r7_writer_waiting_reconciles_killed_holder_before_reinspection_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        tear(lib); (lib.settings.data_dir / "synthetic-full.pdf").write_bytes(lib.data)
        with child(lib, "park_restore", "retention_copy", parked=True) as process:
            old = dict(lib.conn.execute("SELECT * FROM asset_recovery_operations").fetchone())
            entered = asyncio.Event()
            real_lock = file_restore.writer_lock
            from contextlib import asynccontextmanager
            @asynccontextmanager
            async def waiting(*args):
                entered.set()
                async with real_lock(*args): yield
            monkeypatch.setattr(file_restore, "writer_lock", waiting)
            forbid_calls(monkeypatch)
            async def scenario():
                task = asyncio.create_task(file_restore.store_pdf_file(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                    lib.data, caller="upload", research_id=lib.rid))
                await asyncio.wait_for(entered.wait(), 15)
                assert not task.done()
                process.kill(); process.communicate(timeout=10)
                result = await task
                assert result.outcome == "restored"
            asyncio.run(scenario())
        assert lib.store.file_restore_view(old["id"])["reason"] == "process_ended"
        assert len(events(lib.store, "asset_file_restore_finished", old["id"])) == 1


def test_r8_startup_ten_turns_capability_and_queue_never_retry_new_contract(tmp_path, monkeypatch):
    with api_library(tmp_path) as lib:
        reserve(lib)
        lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
        before = protected(lib.store), counts(lib.store)
        with monkeypatch.context() as patch:
            forbid_calls(patch)
            with startup(lib) as (app, _):
                assert app.state.reconciled == {"text_retries": 1, "file_restores": 1, "live": 0}
            real_wait = asyncio.wait_for
            async def short(awaitable, timeout): return await real_wait(awaitable, 0.001 if timeout == 1.0 else timeout)
            patch.setattr(asyncio, "wait_for", short)
            async def turns():
                for _ in range(10): await lib.app.state.worker._turn()
            asyncio.run(turns())
            from deixis.workflow import reconcile
            asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
            assert lib.client.get(url(lib, "text-retry")).status_code == 200
            assert lib.store.next_queued_run() is None
            assert protected(lib.store) == before[0]
            after = counts(lib.store)
            for table in ("asset_extractions", "passages", "asset_recovery_operations"):
                assert after[table] == before[1][table]
        assert lib.client.post(url(lib), json=body(lib)).json()["recovery"]["outcome"] == "promoted"


@pytest.mark.parametrize("race", ["baseline_changed", "membership_changed", "asset_removed", "run_active"])
def test_r9_cross_process_final_transaction_race_guard_new_contract(tmp_path, monkeypatch, race):
    with api_library(tmp_path, raise_errors=True) as lib:
        other = sharing(lib)
        real, oracle = pdf.extract_pdf, {}
        def parsed(path):
            candidate = real(path)
            code = '''import sys
from pathlib import Path
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.documents import pdf
conn=db.connect(Path(sys.argv[1])); store=Store(conn)
race,aid,rid,svid,other=sys.argv[2:]
if race=='baseline_changed': store.reextract_asset(aid,pdf.Extraction('failed',0,[],error='SYNTHETIC competing'),'competing-v1',pdf.chunk_page)
elif race=='membership_changed': store.remove_sources(rid,[svid],'SYNTHETIC competing removal')
elif race=='asset_removed': store.replace_asset(aid,'b'*64,10,'replacement.pdf','user_upload',None,'replacement.pdf',pdf.Extraction('failed',0,[],error='SYNTHETIC replacement'),pdf.EXTRACTION_VERSION,pdf.chunk_page)
else:
 run=store.create_run(other,'answer',{},None); store.update_run(run['id'],status='running')
conn.close(); print('race committed',flush=True)
'''
            result = subprocess.run([sys.executable, "-c", code, str(lib.settings.db_path), race, lib.aid, lib.rid, lib.svid, other],
                env=dict(os.environ, PYTHONPATH=str(ROOT / "backend"), DEIXIS_DATA_DIR=str(lib.settings.data_dir)),
                capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == "race committed"
            oracle.update(protected(lib.store))
            return candidate
        monkeypatch.setattr(pdf, "extract_pdf", parsed)
        response = lib.client.post(url(lib), json=body(lib))
        result = response.json()["recovery"]
        assert result["outcome"] == "refused" and result["reason"] == race
        assert protected(lib.store) == oracle
        assert not any(e["outcome"] == "promoted" for e in events(lib.store, "asset_text_retried", result["operation_id"]))


def test_r12_ocr_run_excludes_repairs_without_reader_lock_guard(tmp_path, monkeypatch):
    from deixis.documents import ocr
    with api_library(tmp_path) as lib:
        run = lib.store.create_run(lib.rid, "pdf_ocr", {}, None,
            target={"asset_id": lib.aid, "source_version_id": lib.svid, "languages": ["eng"]})
        lib.store.update_run(run["id"], status="running")
        tear(lib)
        before = counts(lib.store)
        retry = lib.client.post(url(lib), json=body(lib))
        restore = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("SYNTHETIC.pdf", lib.data, "application/pdf")})
        assert retry.status_code == restore.status_code == 409
        assert retry.json()["code"] == restore.json()["code"] == "run_active"
        assert counts(lib.store) == before and lib.path.read_bytes() == lib.torn
        lib.path.write_bytes(lib.data)
        calls = []
        real = text_retry.file_lock
        def lock(*args): calls.append(args); return real(*args)
        monkeypatch.setattr(text_retry, "file_lock", lock)
        # Synthetic text-only base exercises the OCR run's two parser reads and merge.
        monkeypatch.setattr(ocr, "merge", lambda base, pages, langs: base)
        asyncio.run(lib.app.state.worker.flow._pdf_ocr(lib.store.run(run["id"])))
        assert calls == []
        assert lib.conn.execute("SELECT status FROM run_steps WHERE kind = 'ocr_merge'").fetchone()[0] == "succeeded"

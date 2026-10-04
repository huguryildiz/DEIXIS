"""R10 parser bounds are guards of the real retry path; R11 real SQLite-full and injected ENOSPC contracts."""

import asyncio
import errno
import json
import os
import sqlite3
from pathlib import Path

import pytest

from deixis.documents import pdf, pdf_files
from deixis.storage import db
from deixis.workflow import file_restore, text_retry
from tests.helpers import make_pdf
from tests.reextract.reextract_r2a_helpers import api_library, body, counts, head, seed, store_library, url
from tests.reextract.reextract_r2b_helpers import tear
from tests.reextract.reextract_r2c_helpers import events, forbid_calls, startup
from tests.reextract.test_reextract_r2a_store import reserve


@pytest.mark.parametrize("limit", ["defaults", "timeout", "memory", "pages", "chars"])
def test_r10_real_parser_limits_through_retry_guard(tmp_path, monkeypatch, limit):
    with api_library(tmp_path) as lib:
        client = lib.client
        if limit == "pages":
            lib = seed(lib.store, lib.settings, data=make_pdf([f"SYNTHETIC text on page {i}." for i in range(1, 402)]))
        real, calls, processes = pdf.extract_pdf, [], []
        if limit == "timeout": monkeypatch.setattr(pdf, "TIMEOUT_SECONDS", 0.000001)
        popen = pdf.subprocess.Popen
        def launch(*args, **kwargs):
            process = popen(*args, **kwargs); processes.append(process); return process
        monkeypatch.setattr(pdf.subprocess, "Popen", launch)
        def parse(*args, **kwargs):
            calls.append((args, kwargs))
            assert len(args) == 1 and kwargs == {} and args[0] != lib.path
            if limit == "memory": return real(args[0], max_memory=1)
            if limit == "chars": return real(args[0], max_chars=15)
            return real(*args)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        response = client.post(url(lib), json=body(lib, "limit_request"))
        assert response.status_code == 200
        result = response.json()["recovery"]
        assert result["lifecycle"] == "completed" and len(calls) == 1
        candidate = dict(lib.conn.execute("SELECT * FROM asset_extractions WHERE id = ?", (result["extraction_id"],)).fetchone())
        if limit in ("timeout", "memory"):
            assert (result["candidate_status"], result["outcome"], result["decision_code"]) == ("failed", "rejected", "candidate_failed")
            assert candidate["error"] == ("extraction timed out" if limit == "timeout" else "extraction exceeded the memory limit")
            assert head(lib.store, lib.aid)["id"] == lib.eid
        else:
            assert result["outcome"] == "promoted" and result["decision_code"] == "recovered_text"
            if limit == "pages":
                assert result["candidate_status"] == "partial" and result["coverage"]["new_text_pages"] == list(range(1, 401))
                assert candidate["page_count"] == 401
            if limit == "chars":
                assert result["candidate_status"] == "partial"
                assert sum(len(p["text"]) for p in lib.store.passages_for(lib.svid)) <= 15
        for process in processes:
            assert process.returncode is not None
            with pytest.raises(ChildProcessError): os.waitpid(process.pid, os.WNOHANG)
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


def saturated(conn, table, lib):
    """No free page; fill the boundary's own table/index shape until SQLite refuses real allocation."""
    conn.execute("CREATE TABLE IF NOT EXISTS r2c_scratch (payload BLOB)")
    cap = conn.execute("PRAGMA page_count").fetchone()[0]
    conn.execute(f"PRAGMA max_page_count = {cap}")
    for _ in range(10000):
        try: conn.execute("INSERT INTO r2c_scratch VALUES (zeroblob(1000))")
        except sqlite3.OperationalError as exc:
            assert exc.sqlite_errorcode & 0xFF == 13
            break
    else: pytest.fail("Could not saturate scratch pages")
    failures = 0
    for _ in range(10000):
        try:
            if table == "asset_recovery_operations":
                conn.execute("INSERT INTO asset_recovery_operations (id,kind,research_id,expected_sha256,expected_byte_size,"
                    "idempotency_key,request_fingerprint,lifecycle,created_at) VALUES (?,'file_restore',?,?,?, ?,?,'running',?)",
                    (db.new_id("rop"), lib.rid, "b" * 64, len(lib.data), "restore-" + db.new_id("fill"), "SYNTHETIC" * 8, db.now()))
            elif table == "asset_file_observations":
                conn.execute("INSERT INTO asset_file_observations (id,kind,storage_path,expected_sha256,expected_byte_size,"
                    "observed_sha256,observed_byte_size,integrity,observed_at) VALUES (?,'before_restore',?,?,?, ?,?,'verified',?)",
                    (db.new_id("obs"), lib.path.name, lib.sha, len(lib.data), lib.sha, len(lib.data), db.now()))
            else:
                conn.execute("INSERT INTO events (research_id,type,payload_json,created_at) VALUES (?,'SYNTHETIC filler','{}',?)",
                             (lib.rid, db.now()))
        except sqlite3.OperationalError as exc:
            assert exc.sqlite_errorcode & 0xFF == 13
            failures += 1
            if failures >= 32: break
        else: failures = 0
    else: pytest.fail("Could not saturate the boundary's table/index")
    assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0


def capture_full(monkeypatch, obj, name, lib, table, predicate=lambda *a, **k: True):
    real, caught = getattr(obj, name), []
    def called(*args, **kwargs):
        active = predicate(*args, **kwargs)
        if active: saturated(lib.store.conn, table, lib)
        try: return real(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if active: caught.append(exc.sqlite_errorcode & 0xFF)
            raise
    monkeypatch.setattr(obj, name, called)
    return caught


@pytest.mark.parametrize("boundary", ["text_reservation", "text_final", "restore_reservation", "restore_before", "restore_after"])
def test_r11_real_sqlite_full_at_named_boundary_new_contract(tmp_path, monkeypatch, boundary):
    with api_library(tmp_path) as lib:
        old_head = head(lib.store, lib.aid)
        before_passages = lib.conn.execute("SELECT count(*) FROM passages").fetchone()[0]
        if boundary.startswith("restore"): tear(lib)
        if boundary == "text_final":
            real = pdf.extract_pdf
            def many(path):
                result = real(path)
                result.pages = [pdf.PageText(n, None, "SYNTHETIC candidate words " * 200) for n in range(1, 201)]
                result.page_count = 200
                return result
            monkeypatch.setattr(pdf, "extract_pdf", many)
        name = ("reserve_text_retry" if boundary == "text_reservation" else "complete_text_retry" if boundary == "text_final" else
                "reserve_file_restore" if boundary == "restore_reservation" else "record_file_restore_observation")
        table = "asset_recovery_operations" if "reservation" in boundary else "events" if boundary == "text_final" else "asset_file_observations"
        predicate = (lambda oid, kind, **kw: kind == ("before_restore" if boundary == "restore_before" else "after_restore")) if boundary in (
            "restore_before", "restore_after") else lambda *a, **kw: True
        caught = capture_full(monkeypatch, lib.store, name, lib, table, predicate)
        response = (lib.client.post(url(lib), json=body(lib)) if boundary.startswith("text") else
                    lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("SYNTHETIC.pdf", lib.data, "application/pdf")}))
        assert caught == [13], f"Named boundary did not raise real SQLITE_FULL: HTTP {response.status_code}, codes {caught}"
        assert response.status_code == 507 and response.json()["code"] == "disk_full"
        assert head(lib.store, lib.aid) == old_head and not lib.conn.in_transaction
        assert lib.conn.execute("SELECT count(*) FROM passages").fetchone()[0] == before_passages
        rows = [dict(r) for r in lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE expected_sha256 = ?", (lib.sha,))]
        if "reservation" in boundary: assert rows == []
        else:
            assert len(rows) == 1
            oid = rows[0]["id"]
            assert rows[0]["lifecycle"] in ("interrupted", "running") and rows[0]["outcome"] is None
            lib.conn.execute("PRAGMA max_page_count = 1073741823")
            lib.store.flush_text_retry_interruptions()
            assert lib.store._text_retry_operation(oid)["reason"] == "storage_full"
            for event in events(lib.store, "asset_text_retried" if boundary == "text_final" else "asset_file_restore_finished", oid):
                assert event["outcome"] is None and event["reason"] == "storage_full"
        if boundary.startswith("restore"):
            assert lib.path.read_bytes() == (lib.data if boundary == "restore_after" else lib.torn)
            if boundary in ("restore_before", "restore_after"):
                assert (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).read_bytes() == lib.torn
        assert not list(lib.settings.papers_dir.glob("*.part")) and not list(lib.settings.papers_dir.glob("*.partial"))
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


def test_r11_real_full_startup_starts_and_later_sweep_ends_once_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        real, caught, enabled = reconcile.reconcile_stale, [], [True]
        async def full(store, papers, recovery):
            if enabled[0]:
                saturated(store.conn, "events", lib)
                interrupt = store.interrupt_text_retry
                def capture(*args, **kwargs):
                    try: return interrupt(*args, **kwargs)
                    except sqlite3.OperationalError as exc:
                        caught.append(exc.sqlite_errorcode & 0xFF)
                        raise
                store.interrupt_text_retry = capture
                try:
                    return await real(store, papers, recovery)
                finally:
                    store.interrupt_text_retry = interrupt
            return await real(store, papers, recovery)
        monkeypatch.setattr(reconcile, "reconcile_stale", full)
        with startup(lib) as (app, client):
            def restore_space():
                assert caught and set(caught) == {13}
                assert app.state.store.text_retry_view(op["id"])["lifecycle"] == "running"
                assert not app.state.store.conn.in_transaction
                enabled[0] = False
                app.state.store.conn.execute("PRAGMA max_page_count = 1073741823")
            client.portal.call(restore_space)
            async def wait_for_worker():
                async with asyncio.timeout(10):
                    while app.state.store.text_retry_view(op["id"])["lifecycle"] == "running":
                        await asyncio.sleep(0.01)
                assert app.state.store.text_retry_view(op["id"])["reason"] == "process_ended"
                assert len(events(app.state.store, "asset_text_retried", op["id"])) == 1
            # All connection access uses the portal; only the worker performs the later sweep.
            client.portal.call(wait_for_worker)


@pytest.mark.parametrize("boundary", ["private_copy", "staging", "retention_partial", "retention_fsync", "replace", "directory_after"])
def test_r11_enospc_keeps_boundary_evidence_and_never_claims_recovery_new_contract(tmp_path, monkeypatch, boundary):
    with api_library(tmp_path) as lib:
        if boundary != "private_copy": tear(lib)
        old_head = head(lib.store, lib.aid)
        error = OSError(errno.ENOSPC, "SYNTHETIC disk full")
        if boundary in ("private_copy", "retention_partial"):
            obj, name = (text_retry, "observe_copy") if boundary == "private_copy" else (pdf_files, "inspect_file")
            real = getattr(obj, name)
            def copy(*args, **kwargs):
                destination = args[-1] if boundary == "private_copy" else args[1] if len(args) > 1 else None
                if destination is not None:
                    destination.write_bytes(b"SYNTHETIC partial bytes")
                    raise error
                return real(*args, **kwargs)
            monkeypatch.setattr(obj, name, copy)
        elif boundary == "staging":
            from deixis.api import app as app_module
            real = app_module.os.fsync
            def sync(fd):
                import fcntl
                name = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0")[0].decode()
                if name.endswith(".partial"): raise error
                return real(fd)
            monkeypatch.setattr(app_module.os, "fsync", sync)
        elif boundary == "retention_fsync":
            real = pdf_files.os.fsync
            def sync(fd):
                import fcntl
                name = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0")[0].decode()
                if name.endswith(".part"): raise error
                return real(fd)
            monkeypatch.setattr(pdf_files.os, "fsync", sync)
        elif boundary == "replace":
            real = file_restore.os.replace
            def replace(src, dst):
                if Path(dst) == lib.path: raise error
                return real(src, dst)
            monkeypatch.setattr(file_restore.os, "replace", replace)
        else:
            real, calls = file_restore.fsync_directory, [0]
            def sync(path):
                calls[0] += 1
                if calls[0] == 2: raise error
                return real(path)
            monkeypatch.setattr(file_restore, "fsync_directory", sync)
        response = (lib.client.post(url(lib), json=body(lib)) if boundary == "private_copy" else
                    lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("SYNTHETIC.pdf", lib.data, "application/pdf")}))
        assert response.status_code == 507 and response.json()["code"] == "disk_full"
        assert head(lib.store, lib.aid) == old_head
        assert lib.path.read_bytes() == (lib.data if boundary in ("private_copy", "directory_after") else lib.torn)
        rows = [dict(r) for r in lib.conn.execute("SELECT * FROM asset_recovery_operations")]
        assert len(rows) == (0 if boundary == "staging" else 1)
        if rows:
            assert (rows[0]["lifecycle"], rows[0]["reason"], rows[0]["outcome"]) == ("interrupted", "storage_full", None)
        if boundary in ("replace", "directory_after"):
            assert rows[0]["before_observation_id"] is not None
            assert (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).read_bytes() == lib.torn
        assert not list(lib.settings.papers_dir.glob("*.part")) and not list(lib.settings.papers_dir.glob("*.partial"))
        assert not list((lib.settings.recovery_dir / "tmp").glob("*.pdf"))
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        for row in rows:
            for e in events(lib.store, "asset_text_retried" if boundary == "private_copy" else "asset_file_restore_finished", row["id"]):
                assert e["outcome"] is None

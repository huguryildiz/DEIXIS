"""CLI retry and immutable planning contracts; paired with API T1 and library-wide selection guards."""

import errno
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from deixis import __main__ as cli
from deixis.documents import pdf
from deixis.storage import db
try:
    from deixis.workflow import text_retry
except ImportError:
    text_retry = None  # The unchanged library-wide selection guard also runs on R1.
from deixis.workflow.store import Store
from tests.reextract.reextract_r2a_helpers import store_library, api_library, seed, head, body, url, counts, child_lock
from tests.reextract.reextract_r2a_helpers import PUBLIC_RETRY_FIELDS


def invoke(lib, monkeypatch, dry=False):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(lib.settings.data_dir))
    return cli.main(["reextract", "--retry", lib.aid, "--expected-extraction", lib.eid] + (["--dry-run"] if dry else []))


def file_state(folder):
    return {str(p.relative_to(folder)): (p.is_dir(), None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in folder.rglob("*")}


def test_cli_retry_promotes_one_failed_asset_and_prints_stored_result(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        assert invoke(lib, monkeypatch) == 0
        printed = capsys.readouterr()
        operation = lib.conn.execute("SELECT * FROM asset_recovery_operations").fetchone()
        result = lib.store.text_retry_view(operation["id"])
        assert set(result) == PUBLIC_RETRY_FIELDS
        assert printed.err == ""
        assert printed.out.strip() == f"completed promoted recovered_text {operation['id']} {result['extraction_version']}"
        assert result["input_integrity"] == "verified" and head(lib.store, lib.aid)["id"] != lib.eid
        assert operation["research_id"] is None and operation["idempotency_key"].startswith("cli-")


@pytest.mark.parametrize("kind", ["healthy", "missing", "baseline", "running", "active", "removed"])
def test_cli_pre_reservation_refusals_exit_two_without_new_operation(tmp_path, monkeypatch, capsys, kind):
    with store_library(tmp_path, "succeeded" if kind == "healthy" else "failed") as lib:
        if kind == "missing": lib.path.unlink()
        elif kind == "baseline": lib.eid = "ext_stale"
        elif kind == "running": lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid, idempotency_key="prior", request_fingerprint="prior")
        elif kind == "active": lib.store.create_run(lib.rid, "answer", {}, None)
        elif kind == "removed": lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
        before = counts(lib.store)
        with child_lock(lib) if kind == "running" else nullcontext():
            assert invoke(lib, monkeypatch) == 2
        assert capsys.readouterr().err.startswith("Text retry refused:")
        assert counts(lib.store) == before


@pytest.mark.parametrize("dry", [False, True])
def test_cli_schema_copy_enospc_unwraps_storage_cause_exit_three(tmp_path, monkeypatch, capsys, dry):
    with store_library(tmp_path) as lib:
        def fail(*args): raise OSError(errno.ENOSPC, "SYNTHETIC copy full")
        monkeypatch.setattr(db, "_copy_live_files", fail)
        before = file_state(lib.settings.data_dir)
        assert invoke(lib, monkeypatch, dry) == 3
        assert "disk is full" in capsys.readouterr().err
        assert file_state(lib.settings.data_dir) == before


@pytest.mark.parametrize("where", ["reserve_busy", "lock_full", "open_full", "migrate_full"])
def test_cli_storage_before_reservation_exit_three_without_row(tmp_path, monkeypatch, capsys, where):
    with store_library(tmp_path) as lib:
        error = OSError(errno.ENOSPC, "SYNTHETIC full")
        def fail(*args, **kwargs): raise error
        if where == "reserve_busy":
            error = sqlite3.OperationalError("SYNTHETIC busy"); error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            monkeypatch.setattr(Store, "reserve_text_retry", fail)
        elif where == "lock_full": monkeypatch.setattr(text_retry, "_private_dir", fail)
        elif where == "open_full": monkeypatch.setattr(db, "connect", fail)
        else: monkeypatch.setattr(db, "migrate", fail)
        assert invoke(lib, monkeypatch) == 3
        assert capsys.readouterr().err.count("\n") == 1
        assert counts(lib.store)["asset_recovery_operations"] == 0


def test_cli_parser_interruption_exit_one_and_pending_failure_names_running_limit(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        def fail(*args): raise RuntimeError("SYNTHETIC parser error")
        monkeypatch.setattr(pdf, "extract_pdf", fail)
        assert invoke(lib, monkeypatch) == 1
        printed = capsys.readouterr()
        assert "interrupted - unexpected_error" in printed.out
        assert "RuntimeError" in printed.err
        assert lib.conn.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "interrupted"
    with store_library(tmp_path / "pending") as lib:
        monkeypatch.setattr(Store, "interrupt_text_retry", fail)
        assert invoke(lib, monkeypatch) == 1
        assert "The text retry operation stays running until DEIXIS reconciles it (at its next start, while it runs, or at the next retry of this file)." in capsys.readouterr().err
        assert lib.conn.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "running"


@pytest.mark.parametrize("candidate,expected", [("success", "would promote recovered_text"),
    ("same_failure", "would reject no_change"), ("password", "would promote password_diagnosed")])
def test_dry_run_policy_keeps_main_wal_shm_and_data_tree_byte_identical(tmp_path, monkeypatch, capsys, candidate, expected):
    with store_library(tmp_path, "no_text" if candidate == "password" else "failed") as lib:
        if candidate == "same_failure": monkeypatch.setattr(pdf, "extract_pdf", lambda p: pdf.Extraction("failed", 0, [], error=pdf.ERROR_UNREADABLE))
        elif candidate == "password": monkeypatch.setattr(pdf, "extract_pdf", lambda p: pdf.Extraction("failed", 0, [], error=pdf.ERROR_PASSWORD))
        # Deliberately keep orphan entries. Planning must neither sweep them nor make a recovery folder.
        if candidate == "success":
            folder = lib.settings.recovery_dir / "tmp"; folder.mkdir(parents=True)
            (folder / (lib.sha + "-orphan.pdf")).write_bytes(b"SYNTHETIC orphan")
            (folder / (lib.sha + "-blocked.pdf")).write_bytes(b"SYNTHETIC undeletable orphan")
        before = file_state(lib.settings.data_dir)
        rows = counts(lib.store)
        def forbidden(*args, **kwargs): raise AssertionError("Dry run mutated the library")
        monkeypatch.setattr(db, "connect", forbidden)
        monkeypatch.setattr(db, "migrate", forbidden)
        monkeypatch.setattr(Store, "reserve_text_retry", forbidden)
        monkeypatch.setattr(text_retry, "file_lock", forbidden)
        monkeypatch.setattr(text_retry, "_sweep", forbidden)
        assert invoke(lib, monkeypatch, True) == 0
        assert capsys.readouterr().out.strip() == expected
        assert file_state(lib.settings.data_dir) == before and counts(lib.store) == rows


def test_dry_run_reads_latest_commits_that_exist_only_in_wal(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        lib.conn.execute("PRAGMA wal_autocheckpoint = 0")
        lib.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        added = seed(lib.store, lib.settings)
        bare = sqlite3.connect(lib.settings.db_path.as_uri() + "?immutable=1", uri=True)
        assert bare.execute("SELECT id FROM source_assets WHERE id = ?", (added.aid,)).fetchone() is None
        bare.close()
        before = file_state(lib.settings.data_dir)
        assert invoke(added, monkeypatch, True) == 0
        assert capsys.readouterr().out.strip() == "would promote recovered_text"
        assert file_state(lib.settings.data_dir) == before


@pytest.mark.parametrize("changing", ["main", "wal"])
def test_dry_run_retries_whole_snapshot_three_times_when_file_changes(tmp_path, monkeypatch, capsys, changing):
    with store_library(tmp_path) as lib:
        original, calls = text_retry._file_stamp, []
        target = lib.settings.db_path if changing == "main" else Path(f"{lib.settings.db_path}-wal")
        def stamp(path):
            result = original(path)
            if path == target:
                calls.append(path)
                return result[0], result[1] + len(calls)
            return result
        monkeypatch.setattr(text_retry, "_file_stamp", stamp)
        before = file_state(lib.settings.data_dir)
        assert invoke(lib, monkeypatch, True) == 2
        assert "could not read a consistent copy of the library; try again" in capsys.readouterr().err
        assert len(calls) == 6 and file_state(lib.settings.data_dir) == before


@pytest.mark.parametrize("where", ["copy", "parser"])
def test_dry_run_copy_and_parser_errors_leave_library_unchanged(tmp_path, monkeypatch, capsys, where):
    with store_library(tmp_path) as lib:
        def fail(*args):
            if where == "copy": raise OSError(errno.EACCES, "SYNTHETIC copy denied")
            raise RuntimeError("SYNTHETIC parser")
        monkeypatch.setattr(text_retry if where == "copy" else pdf, "observe_copy" if where == "copy" else "extract_pdf", fail)
        before = file_state(lib.settings.data_dir)
        assert invoke(lib, monkeypatch, True) == (3 if where == "copy" else 1)
        printed = capsys.readouterr()
        assert ("copy" if where == "copy" else "RuntimeError") in printed.err
        assert file_state(lib.settings.data_dir) == before


def test_dry_run_with_a_pending_migration_refuses_without_migrating(tmp_path, monkeypatch, capsys):
    settings = cli.Settings(data_dir=tmp_path)
    conn = db.connect(settings.db_path); db.migrate(conn); conn.close()
    # The code now ships one more migration than the library has applied.
    pending = tmp_path / "migrations"; pending.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"): shutil.copy(path, pending / path.name)
    version = max(db.packaged_versions()) + 1
    (pending / f"{version:04d}_synthetic_pending.sql").write_text("CREATE TABLE synthetic_pending (id TEXT PRIMARY KEY);\n")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", pending)
    before = file_state(tmp_path)
    assert cli.plan_text_retry(settings, "ast_missing", "ext_missing") == 2
    assert "this library needs a migration" in capsys.readouterr().err
    assert file_state(tmp_path) == before
    check = sqlite3.connect(settings.db_path.as_uri() + "?immutable=1", uri=True)
    assert version not in {r[0] for r in check.execute("SELECT version FROM schema_migrations")}
    check.close()


@pytest.mark.parametrize("dry", [True, False])
def test_newer_schema_refusal_exit_two(tmp_path, monkeypatch, capsys, dry):
    with store_library(tmp_path) as lib:
        lib.conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (9999, 'SYNTHETIC newer', 'now')")
        before = file_state(lib.settings.data_dir)
        assert invoke(lib, monkeypatch, dry) == 2
        assert capsys.readouterr().err
        assert file_state(lib.settings.data_dir) == before


@pytest.mark.parametrize("args", [["--retry", "ast_X"], ["--expected-extraction", "ext_X"]])
def test_retry_flags_must_be_supplied_together(args):
    with pytest.raises(SystemExit) as exc: cli.main(["reextract", *args])
    assert exc.value.code == 2


def test_library_wide_upgrade_still_skips_same_profile_failure_guard(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        monkeypatch.setenv("DEIXIS_DATA_DIR", str(lib.settings.data_dir))
        before = counts(lib.store)
        assert cli.main(["reextract"]) == 0
        assert capsys.readouterr().out.strip() == "0 PDFs,"
        assert counts(lib.store) == before


def test_library_wide_upgrade_reports_busy_and_continues(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        lib.conn.execute("UPDATE source_assets SET extraction_version = 'older-v1' WHERE id = ?", (lib.aid,))
        monkeypatch.setenv("DEIXIS_DATA_DIR", str(lib.settings.data_dir))
        with child_lock(lib): assert cli.main(["reextract"]) == 0
        assert "1 file_busy" in capsys.readouterr().out
        assert counts(lib.store)["asset_recovery_operations"] == 0


def test_api_and_real_cli_process_share_file_lock_and_defer_run(tmp_path):
    with api_library(tmp_path) as lib:
        # The wrapper changes only the parser and calls the real CLI main; stdin releases the thread.
        code = """import sys
from deixis.documents import pdf
from deixis.__main__ import main
real = pdf.extract_pdf
def slow(path):
    print('parsing', flush=True)
    sys.stdin.readline()
    return real(path)
pdf.extract_pdf = slow
sys.exit(main(sys.argv[1:]))
"""
        env = os.environ.copy()
        env["DEIXIS_DATA_DIR"] = str(lib.settings.data_dir)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "backend")
        child = subprocess.Popen([sys.executable, "-c", code, "reextract", "--retry", lib.aid,
                                  "--expected-extraction", lib.eid], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=env)
        try:
            assert child.stdout.readline().strip() == "parsing"
            response = lib.client.post(url(lib), json=body(lib))
            assert response.status_code == 409 and response.json()["code"] in ("file_busy", "operation_running")
            # Queue through the real API, with a CSRF token, without starting a worker.
            queued = lib.client.post(f"/api/researches/{lib.rid}/runs", json={"kind": "answer"})
            assert queued.status_code == 202, queued.text
            assert lib.store.next_queued_run() is None
        finally:
            output, error = child.communicate("release\n", timeout=30)
        assert child.returncode == 0, error
        assert "completed promoted recovered_text" in output
        assert lib.conn.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "completed"
        assert lib.store.next_queued_run()["id"] == queued.json()["id"]

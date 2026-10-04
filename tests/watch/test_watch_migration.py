"""0068 keeps every old row/object/key and closes immutable read histories."""

import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from tests.watch.watch_helpers import api, watch_offline, create, now_check, turn, rows


def objects(conn):
    return {(r["type"], r["name"]): (r["tbl_name"], r["sql"]) for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type IN ('index','trigger')")}


@pytest.mark.parametrize("populated", [False, True])
def test_runs_rebuild_preserves_every_row_trigger_index_and_foreign_key(tmp_path, monkeypatch, populated):
    real = db.MIGRATIONS_DIR
    old = tmp_path / "migrations"; old.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name[:4]) <= 67:
            shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    fixture = None
    if populated:
        from tests.review.test_review_migration import dependencies
        from tests.report.test_report_assembly import report_with_sections
        from tests.report.test_report_edit_check import finish
        fixture = report_with_sections.__wrapped__(tmp_path)
        lib = next(fixture)
        lib["rid"] = finish(lib); lib["conn"] = lib["store"].conn
        conn = lib["conn"]
        dependencies(lib)
        # Populate the owner-review trigger and its run/snapshot dependency too.
        from tests.review.review_helpers import stored_review
        from deixis.workflow.review.snapshot import ReviewReader
        from deixis.workflow.review.store import ReviewStore
        lib["reader"] = ReviewReader(lib["store"], lib["reports"])
        lib["reviews"] = ReviewStore(conn, lib["reader"])
        stored_review(lib)
    else:
        conn = db.connect(tmp_path / "empty.sqlite"); db.migrate(conn)
    try:
        before = rows(conn); before.pop("schema_migrations")
        schema = objects(conn)
        keys = {t: [tuple(r) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')] for t in before}
        original_runs = conn.execute("SELECT sql FROM sqlite_master WHERE name='runs'").fetchone()[0]
        shutil.copy(real / "0068_watches.sql", old / "0068_watches.sql")
        assert db.migrate(conn) == [68]
        assert {t: rows(conn)[t] for t in before} == before
        assert {k: objects(conn)[k] for k in schema} == schema
        assert {t: [tuple(r) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')] for t in before} == keys
        changed_runs = conn.execute("SELECT sql FROM sqlite_master WHERE name='runs'").fetchone()[0]
        assert "'watch_check'" not in original_runs and "'watch_check'" in changed_runs
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        if fixture:
            with pytest.raises(StopIteration): next(fixture)
        else:
            conn.close()


def test_watch_run_kind_stage_and_eight_tables(api):
    command = create(api)
    run = api.store.run(command["run_id"])
    assert run["kind"] == "watch_check" and run["stage"] == "discovery"
    tables = {r[0] for r in api.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"watches", "watch_checks", "watch_reads", "watch_seen", "watch_seen_alias", "watch_items",
            "watch_schedule_changes", "watch_gaps"} <= tables
    for table in ("watch_checks", "watch_reads"):
        assert "WITHOUT ROWID" in api.conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        with pytest.raises(sqlite3.OperationalError): api.conn.execute(f"SELECT rowid FROM {table}")


@pytest.mark.parametrize("table", ["watch_checks", "watch_reads"])
@pytest.mark.parametrize("operation", ["INSERT", "INSERT OR REPLACE", "upsert"])
@pytest.mark.parametrize("conflict", ["id", "unique"])
def test_immutable_conflicting_insert_replace_upsert_recursive_off(api, table, operation, conflict):
    first = create(api); turn(api)
    second = now_check(api, first["watch_id"], key="SYNTHETIC-immutable"); turn(api)
    api.conn.execute("PRAGMA recursive_triggers=OFF")
    saved = dict(api.conn.execute(f"SELECT * FROM {table} WHERE " + ("id=?" if table == "watch_checks" else "check_id=?"), (second["check_id"],)).fetchone())
    if conflict == "unique":
        saved["id"] = "SYNTHETIC-other-id"
    columns = list(saved)
    verb = "INSERT" if operation == "upsert" else operation
    sql = f"{verb} INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    if operation == "upsert":
        sql += " ON CONFLICT(id) DO UPDATE SET id=excluded.id"
    before = rows(api.conn, [table])
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        api.conn.execute(sql, list(saved.values()))
    assert rows(api.conn, [table]) == before


@pytest.mark.parametrize("column", ["config_json", "requested_to", "state_version", "research_id", "request_hash"])
def test_check_frozen_columns_cannot_be_updated(api, column):
    command = create(api)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        api.conn.execute(f"UPDATE watch_checks SET {column}='changed' WHERE id=?", (command["check_id"],))


def test_observation_fields_once_and_read_no_update_or_unapproved_delete(api):
    command = create(api); turn(api)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        api.conn.execute("UPDATE watch_checks SET counts_json='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        api.conn.execute("UPDATE watch_reads SET returned_count=0")
    for table in ("watch_checks", "watch_reads"):
        with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
            api.conn.execute(f"DELETE FROM {table}")

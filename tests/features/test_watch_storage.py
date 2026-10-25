"""The watch run kind and tables, and their immutable read histories."""

import sqlite3

import pytest

from watch_helpers import api, watch_offline, create, now_check, turn, rows


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


@pytest.mark.parametrize("table", ["watch_reads"])
@pytest.mark.parametrize("operation", ["INSERT OR REPLACE"])
@pytest.mark.parametrize("conflict", ["unique"])
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


@pytest.mark.parametrize("column", ["config_json"])
def test_check_frozen_columns_cannot_be_updated(api, column):
    command = create(api)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        api.conn.execute(f"UPDATE watch_checks SET {column}='changed' WHERE id=?", (command["check_id"],))


from datetime import datetime, timedelta
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.features.watch.watch_store import TABLES
from watch_helpers import api, watch_offline, turn, now_check, rows, page, work
from test_watch_scheduler import baseline, loop, schedule, Clock
from deixis.workflow.features.watch.watch_scheduler import WatchScheduler


def histories(api):
    first = baseline(api)
    clock = Clock(); clock.value = datetime.fromisoformat(first["watch"]["next_due_at"]) + timedelta(days=2)
    sched = WatchScheduler(api.store, lambda: None, clock)
    loop(api, sched.tick)
    assert schedule(api, first["watch_id"]).status_code == 200
    return first


@pytest.mark.parametrize("table", ["watch_gaps"])
@pytest.mark.parametrize("operation", ["upsert"])
@pytest.mark.parametrize("conflict", ["key"])
def test_append_only_histories_conflicting_insert_replace_upsert_recursive_off(api, table, operation, conflict):
    histories(api)
    loop(api, api.conn.execute, "PRAGMA recursive_triggers=OFF")
    saved = dict(api.conn.execute(f"SELECT * FROM {table}").fetchone())
    if conflict != "id": saved["id"] = "SYNTHETIC-new-id"
    if conflict == "key" and table == "watch_schedule_changes": saved["schedule_version"] = 99
    verb = "INSERT" if operation == "upsert" else operation
    sql = f"{verb} INTO {table} ({','.join(saved)}) VALUES ({','.join('?' for _ in saved)})"
    if operation == "upsert": sql += " ON CONFLICT(id) DO UPDATE SET id=excluded.id"
    before = rows(api.conn)
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        loop(api, api.conn.execute, sql, tuple(saved.values()))
    assert rows(api.conn) == before
    with pytest.raises(sqlite3.OperationalError):
        api.conn.execute(f"SELECT rowid FROM {table}")


def test_authorized_purge_removes_all_eight_nonempty_watch_tables(api):
    first = histories(api); turn(api)
    assert all(api.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES if t != "watch_items")
    # Baseline suppresses every initial record; the due check returns a distinct record.
    api.state.payload = page(work("NEW"))
    now_check(api, first["watch_id"]); turn(api)
    assert all(api.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES)
    loop(api, api.store.trash_research, api.rid)
    loop(api, api.store.purge_research, api.rid)
    assert all(api.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0 for t in TABLES)


@pytest.mark.parametrize("operation", ["update"])
@pytest.mark.parametrize("invalid", ["interval_no_due"])
def test_schedule_coherence_triggers_recursive_off_all_write_forms(api, operation, invalid):
    first = baseline(api)
    saved = api.watches.watch(api.rid, first["watch_id"])
    loop(api, api.conn.execute, "PRAGMA recursive_triggers=OFF")
    if invalid.startswith("manual"):
        saved.update(mode="manual", interval_days=None, catch_up=None, next_due_at=None)
        saved[{"manual_interval": "interval_days", "manual_catch": "catch_up", "manual_due": "next_due_at"}[invalid]] = 1
    else:
        saved[{"interval_no_days": "interval_days", "interval_no_catch": "catch_up", "interval_no_due": "next_due_at"}[invalid]] = None
    if operation == "update":
        sql = "UPDATE watches SET mode=?,interval_days=?,catch_up=?,next_due_at=? WHERE id=?"
        values = tuple(saved[k] for k in ("mode", "interval_days", "catch_up", "next_due_at", "id"))
    else:
        verb = "INSERT OR REPLACE" if operation == "replace" else "INSERT"
        sql = f"{verb} INTO watches ({','.join(saved)}) VALUES ({','.join('?' for _ in saved)})"
        if operation == "upsert": sql += " ON CONFLICT(id) DO UPDATE SET mode=excluded.mode"
        values = tuple(saved.values())
    before = rows(api.conn)
    with pytest.raises(sqlite3.IntegrityError, match="incoherent watch schedule"):
        loop(api, api.conn.execute, sql, values)
    assert rows(api.conn) == before


def test_backup_restore_keeps_nonempty_schedule_and_gap_histories(api, tmp_path):
    from deixis.storage import backup
    from deixis.config import Settings
    histories(api); turn(api)
    before = rows(api.conn, TABLES)
    saved = backup.create_backup(api.settings, tmp_path / "backups")
    restored = Settings(data_dir=tmp_path / "restored")
    backup.restore_backup(saved, restored)
    conn = db.connect(restored.db_path)
    try:
        assert rows(conn, TABLES) == before
    finally:
        conn.close()


import socket

import httpx
import pytest

from deixis.providers import openalex
from deixis.storage import backup, db
from deixis.workflow.run.store import Store


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Old-entry-point tests forbid network and DNS")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC watch", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    yield conn, store, rid
    conn.close()


def test_existing_research_view_with_watch_run(lib):
    from deixis.workflow.run.views import research_view
    conn, store, rid = lib
    run = store.create_run(rid, "watch_check", {}, None)
    assert research_view(store, rid)["research"]["id"] == rid

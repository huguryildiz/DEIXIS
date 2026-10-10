"""Watch schedule histories, schedule coherence triggers and create-key replays."""

from datetime import datetime, timedelta
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.watch.store import TABLES
from deixis.workflow.watch.store import command_hash
from tests.watch.watch_helpers import api, watch_offline, turn, now_check, rows, page, work
from tests.watch.test_watch_scheduler import baseline, loop, schedule, Clock
from deixis.workflow.watch.scheduler import WatchScheduler


def histories(api):
    first = baseline(api)
    clock = Clock(); clock.value = datetime.fromisoformat(first["watch"]["next_due_at"]) + timedelta(days=2)
    sched = WatchScheduler(api.store, lambda: None, clock)
    loop(api, sched.tick)
    assert schedule(api, first["watch_id"]).status_code == 200
    return first


@pytest.mark.parametrize("table", ["watch_schedule_changes", "watch_gaps"])
@pytest.mark.parametrize("operation", ["INSERT", "INSERT OR REPLACE", "upsert"])
@pytest.mark.parametrize("conflict", ["id", "unique", "key"])
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


@pytest.mark.parametrize("table", ["watch_schedule_changes", "watch_gaps"])
def test_history_parent_research_consistency_and_immutable_update_delete(api, table):
    histories(api)
    saved = dict(api.conn.execute(f"SELECT * FROM {table}").fetchone())
    rid = loop(api, api.store.create_research, "SYNTHETIC wrong parent", "academic", "standard", [], "fake", "fake-model", "en")
    saved.update(id=db.new_id("wrong"), research_id=rid)
    if table == "watch_gaps": saved["opening_id"] = "wrong-parent-opening"
    else: saved.update(schedule_version=99, request_key="wrong-parent-key")
    with pytest.raises(sqlite3.IntegrityError, match="research watch"):
        loop(api, api.conn.execute, f"INSERT INTO {table} ({','.join(saved)}) VALUES ({','.join('?' for _ in saved)})", tuple(saved.values()))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"): loop(api, api.conn.execute, f"UPDATE {table} SET created_at='changed'")
    with pytest.raises(sqlite3.IntegrityError, match="purge authorization"): loop(api, api.conn.execute, f"DELETE FROM {table}")


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


@pytest.mark.parametrize("operation", ["insert", "replace", "upsert", "update"])
@pytest.mark.parametrize("invalid", ["manual_interval", "manual_catch", "manual_due", "interval_no_days", "interval_no_catch", "interval_no_due"])
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


def test_migrated_b5_manual_create_key_replays_with_original_content_hash(api):
    body = {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}
    first = loop(api, api.watches.create, api.rid, body, "B5-manual-key")
    assert api.watches.watch(api.rid, first["watch_id"])["request_hash"] == command_hash("create", api.rid, None, body)
    before = rows(api.conn)
    response = api.client.post(api.url, json=body, headers={"Idempotency-Key": "B5-manual-key"})
    assert response.status_code == 201 and response.json()["replayed"] and response.json()["check_id"] == first["check_id"]
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

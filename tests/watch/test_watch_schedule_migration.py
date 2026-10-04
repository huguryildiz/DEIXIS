"""0070 upgrades populated pre-0070 (B5 0068 and R3 0069) libraries without enabling unrequested scheduling."""

import json
from datetime import datetime, timedelta
import shutil
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.watch import check as policy
from deixis.workflow.watch.run import observations
from deixis.workflow.watch.store import TABLES, WatchStore
from deixis.workflow.watch.store import command_hash
from tests.watch_helpers import api, watch_offline, turn, now_check, rows, record, page, work
from tests.watch.test_watch_migration import objects
from tests.watch.test_watch_scheduler import baseline, loop, schedule, Clock
from deixis.workflow.watch.scheduler import WatchScheduler


def old_library(tmp_path, monkeypatch):
    real = db.MIGRATIONS_DIR
    directory = tmp_path / "migrations"; directory.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name[:4]) <= 69: shutil.copy(path, directory / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", directory)
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    main, commands = Store(conn), []
    watches = WatchStore(main)
    # Construct B5-shaped rows directly, because B6's writer requires the new columns.
    for index, (mode, stray) in enumerate([("manual", False), ("manual", True), ("interval", False)]):
        rid = main.create_research(f"SYNTHETIC upgrade {index}", "academic", "standard", ["openalex"], "fake", "fake-model", "en", search_workflow="sw")
        protocol = main.freeze_protocol(rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC upgrade"}]})
        protocol = main.current_protocol(rid, 1)
        wid, cid, ts = db.new_id("wat"), db.new_id("wch"), db.now()
        conn.execute("INSERT INTO watches (id,research_id,kind,mode,interval_days,enabled,protocol_record_id,scope_revision,next_due_at,created_at)"
                     " VALUES (?,?,'protocol_queries',?,?,1,?,1,?,?)", (wid, rid, mode, 7 if mode == "interval" or stray else None,
                      protocol["id"], ts if mode == "interval" or stray else None, ts))
        units = policy.unit_plan(watches.units(rid, "protocol_queries", protocol), {}, ts)
        config = {"version": 1, "kind": "protocol_queries", "scope_revision": 1, "protocol_record_id": protocol["id"],
            "units": units, "skipped_units": [], "rolled_over": 0, "rolled_over_units": 0, "next_citing_position": None,
            "caps": policy.caps(), "budget": {"max_provider_requests": 80, "max_records": 3000},
            "deadline_at": policy.next_due(ts, 1)}
        run = main.create_run(rid, "watch_check", config["budget"], f"watch:{wid}:manual:{ts}", {"watch_id": wid, "check_id": cid, "deadline_at": config["deadline_at"]})
        conn.execute("INSERT INTO watch_checks (id,watch_id,research_id,run_id,trigger,period_start,requested_to,config_json,state_version,created_at)"
                     " VALUES (?,?,?,?,'manual',?,?,?,1,?)", (cid, wid, rid, run["id"], "manual:" + ts, ts, db.dumps(config), ts))
        step = main.step(run["id"], "watch:0:page:1", "watch_read")
        sample = record(identifier=f"W{index}")
        conn.execute("INSERT INTO watch_reads (id,check_id,research_id,step_id,unit_key,page_number,provider,status,request_description,"
            "returned_count,dropped_count,records_json,created_at) VALUES (?,?,?,?,'query:0',1,'openalex','completed','SYNTHETIC read',1,0,?,?)",
            (db.new_id("wrd"), cid, rid, step["id"], db.dumps([sample]), ts))
        main.finish_step(step["id"], "succeeded", {})
        sid = db.new_id("wse")
        conn.execute("INSERT INTO watch_seen VALUES (?,?,?,?,NULL,?,'announced',0,?)", (sid, rid, "openalex:" + f"W{index}", db.dumps(sample), cid, ts))
        conn.execute("INSERT INTO watch_seen_alias VALUES (?,?,?,?)", (rid, "openalex:" + f"W{index}", sid, ts))
        conn.execute("INSERT INTO watch_items (id,research_id,check_id,seen_id,record_json,kind,found_by_json,relations_json,kind_history_json,status,created_at)"
            " VALUES (?,?,?,?,?,'new_record','[]','[]','[]','new',?)", (db.new_id("wit"), rid, cid, sid, db.dumps(sample), ts))
        commands.append({"research_id": rid, "watch_id": wid, "check_id": cid, "run_id": run["id"]})
    return conn, main, watches, commands, real, directory


def preserved(conn):
    return rows(conn, omit={"watches": {"catch_up", "schedule_version"}})


def expected_conversion(before):
    # Compare every old column and row; only the documented schedule cleanup is allowed.
    before = dict(before)
    columns = ["id", "research_id", "kind", "mode", "interval_days", "enabled", "protocol_record_id", "scope_revision",
               "baseline_json", "state_version", "last_checked_at", "last_success_at", "next_due_at", "idempotency_key",
               "request_hash", "disable_key", "disable_hash", "created_at", "disabled_at"]
    converted = []
    for row in before["watches"]:
        changed = list(row)
        for name, value in [("mode", "manual"), ("interval_days", None), ("next_due_at", None)]:
            changed[columns.index(name)] = value
        converted.append(tuple(changed))
    before["watches"] = sorted(converted, key=repr)
    before.pop("schema_migrations")
    return before


def test_populated_0068_upgrade_preserves_every_column_object_and_key_then_disable_complete(tmp_path, monkeypatch):
    conn, main, watches, commands, real, directory = old_library(tmp_path, monkeypatch)
    try:
        before = preserved(conn); schema = objects(conn)
        keys = {t: [tuple(r) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')] for t in before}
        shutil.copy(real / "0070_watch_schedule.sql", directory / "0070_watch_schedule.sql")
        assert db.migrate(conn) == [70] and db.migrate(conn) == []
        after = preserved(conn)
        assert {t: after[t] for t in before if t != "schema_migrations"} == expected_conversion(before)
        assert {k: objects(conn)[k] for k in schema} == schema
        assert {t: [tuple(r) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')] for t in keys} == keys
        assert all(r[0] is None and r[1] == 1 for r in conn.execute("SELECT catch_up,schedule_version FROM watches"))
        a, b = commands[1:]
        watches.disable(a["research_id"], a["watch_id"], {"expected_state_version": 1}, "upgrade-disable")
        main.update_run(b["run_id"], status="running")
        check = watches.check(b["research_id"], b["check_id"])
        observed, statuses = observations(json.loads(check["config_json"]), watches.reads(check))
        watches.complete_check(check, observed, statuses)
        assert main.run(b["run_id"])["status"] == "completed"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_last_statement_failure_rolls_back_columns_tables_triggers_conversion_and_ledger(tmp_path, monkeypatch):
    conn, _, _, _, real, directory = old_library(tmp_path, monkeypatch)
    try:
        before, schema = rows(conn), objects(conn)
        columns = [tuple(r) for r in conn.execute("PRAGMA table_info(watches)")]
        path = directory / "0070_watch_schedule.sql"
        path.write_text((real / path.name).read_text() + "\nSELECT * FROM synthetic_missing_last_statement;\n")
        with pytest.raises(sqlite3.OperationalError, match="synthetic_missing"):
            db.migrate(conn)
        assert rows(conn) == before and objects(conn) == schema
        assert [tuple(r) for r in conn.execute("PRAGMA table_info(watches)")] == columns
        assert not conn.in_transaction
        shutil.copy(real / path.name, path)
        assert db.migrate(conn) == [70] and db.migrate(conn) == []
        assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version=70").fetchone()[0] == 1
    finally:
        conn.close()


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

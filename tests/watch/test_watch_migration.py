"""The watch run kind and tables, and their immutable read histories."""

import sqlite3

import pytest

from tests.watch.watch_helpers import api, watch_offline, create, now_check, turn, rows


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

"""Old-code interface failures are separate from two reached behavioral assertions."""

import asyncio
from datetime import datetime, timedelta
import importlib

import pytest

from deixis.storage import db
from tests.watch.watch_helpers import watch_offline, watch_api, create, turn, now_check, rows


def interval_by_sql(api, started=False):
    """Use the old schema's writable interval fields, not the new create interface."""
    first = create(api)
    if started:
        async def finished():
            for _ in range(500):
                if api.store.run(first["run_id"])["status"] == "completed": return
                await asyncio.sleep(.01)
            pytest.fail("baseline did not finish")
        api.client.portal.call(finished)
    else:
        turn(api)
    due = (datetime.fromisoformat(db.now()) - timedelta(days=2)).isoformat()
    extra = ",catch_up=1" if "catch_up" in {r[1] for r in api.conn.execute("PRAGMA table_info(watches)")} else ""
    api.client.portal.call(api.conn.execute, "UPDATE watches SET mode='interval',interval_days=1,next_due_at=?" + extra + " WHERE id=?",
                           (due, first["watch_id"]))
    return first, due


def test_due_interval_direct_old_schema_is_queued_without_owner_command(tmp_path):
    with watch_api(tmp_path, start_worker=True) as api:
        first, old_due = interval_by_sql(api, started=True)
        # Exercise the installed automatic mechanism if it exists. Its absence is not an import failure:
        # the reached assertion below compares durable checks on both implementations.
        sched = getattr(api.app.state, "watch_scheduler", None)
        if sched is None:
            api.client.portal.call(asyncio.sleep, .01)
        else:
            api.client.portal.call(sched.tick)
        assert len(api.watches.checks(first["watch_id"])) == 2
        assert api.watches.checks(first["watch_id"])[-1]["trigger"] in ("scheduled", "catch_up")


def test_manual_interval_check_moves_old_schema_next_due_at(tmp_path):
    with watch_api(tmp_path) as api:
        first, old_due = interval_by_sql(api)
        command = now_check(api, first["watch_id"])
        expected = (datetime.fromisoformat(command["check"]["requested_to"]) + timedelta(days=1)).isoformat(timespec="milliseconds")
        assert api.watches.watch(api.rid, first["watch_id"])["next_due_at"] == expected


def test_scheduler_module_interface():
    assert importlib.import_module("deixis.workflow.watch.scheduler").WatchScheduler


def test_schedule_route_interface(tmp_path):
    with watch_api(tmp_path) as api:
        first = create(api)
        response = api.client.post(api.url + f"/{first['watch_id']}/schedule", json={"mode": "interval", "interval_days": 1,
            "catch_up": True, "expected_schedule_version": 1}, headers={"Idempotency-Key": "new-schedule-interface"})
        assert response.status_code == 200, response.text


def test_interval_create_interface(tmp_path):
    with watch_api(tmp_path) as api:
        response = api.client.post(api.url, json={"kind": "protocol_queries", "mode": "interval", "interval_days": 1,
            "catch_up": True, "expected_scope_revision": 1}, headers={"Idempotency-Key": "interval-interface"})
        assert response.status_code == 201, response.text


def test_migration_0070_interface(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    try:
        db.migrate(conn)
        assert conn.execute("SELECT version FROM schema_migrations WHERE version=70").fetchone() is not None
        assert {r[1] for r in conn.execute("PRAGMA table_info(watches)")} >= {"catch_up", "schedule_version"}
    finally:
        conn.close()

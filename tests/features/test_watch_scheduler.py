"""Fake UTC clocks, temporary libraries and SYNTHETIC provider reads only."""

import asyncio
from datetime import datetime, timedelta
import inspect
import json
import sqlite3
import threading

import httpx
import pytest

from deixis.storage import db
from deixis.workflow import watch_check as policy, watch_run, watch_store
from deixis.workflow.watch_scheduler import WatchScheduler
from deixis.workflow.watch_store import WatchStore
from watch_helpers import (api, watch_offline, watch_api, create, now_check, turn, read, control,
                                 page, work, rows, hashes, add_included)


class Clock:
    def __init__(self, value=None):
        self.value = value or datetime.fromisoformat(db.now()) + timedelta(seconds=10)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


def loop(api, fn, *args, **kwargs):
    from functools import partial
    return api.client.portal.call(partial(fn, *args, **kwargs))


def baseline(api, **extra):
    first = create(api, **({"mode": "interval", "interval_days": 1, "catch_up": True} | extra))
    turn(api)
    assert read(api, first)["state"] == "succeeded"
    return first


def scheduler(api, first=None):
    clock = Clock()
    if first:
        clock.value = datetime.fromisoformat(api.watches.watch(api.rid, first["watch_id"])["next_due_at"]) - timedelta(seconds=1)
    wake = []
    sched = WatchScheduler(api.store, lambda: wake.append(True), clock)
    assert not loop(api, sched.tick)["queued"]
    return sched, clock, wake


def due(api, sched, clock, first):
    clock.value = datetime.fromisoformat(api.watches.watch(api.rid, first["watch_id"])["next_due_at"])
    result = loop(api, sched.tick)
    assert len(result["queued"]) == 1, result
    return result["queued"][0]


def schedule(api, wid, *, mode="interval", interval_days=7, catch_up=False, version=None, key=None):
    body = {"mode": mode, "interval_days": interval_days, "catch_up": catch_up,
            "expected_schedule_version": version or api.watches.watch(api.rid, wid)["schedule_version"]}
    return api.client.post(api.url + f"/{wid}/schedule", json=body, headers={"Idempotency-Key": key or db.new_id("cmd")})


def replay(api, command, ts=None):
    row = api.watches.check(api.rid, command["check_id"])
    config = json.loads(row["config_json"])
    block = config["schedule"]
    return loop(api, api.watches.queue_scheduled, row["watch_id"], row["trigger"], row["period_start"],
                row["missed_periods"], block, block["schedule_version"], block["due_at"], ts or row["requested_to"])


def test_due_not_due_manual_and_single_loop_clock_read(api):  # 13a, 0
    manual = create(api); turn(api)
    sched, clock, wake = scheduler(api)
    clock.value += timedelta(days=3)
    assert not loop(api, sched.tick)["queued"]
    assert len(api.watches.checks(manual["watch_id"])) == 1
    assert api.client.post(api.url + f"/{manual['watch_id']}/disable", json={"expected_state_version": 2},
                           headers={"Idempotency-Key": "disable-manual"}).status_code == 200
    first = baseline(api)
    sched, clock, wake = scheduler(api, first)
    calls = clock.calls
    expected_thread = loop(api, threading.get_ident)
    observed = []
    original = sched.clock
    sched.clock = lambda: (observed.append(threading.get_ident()), original())[1]
    command = due(api, sched, clock, first)
    assert clock.calls == calls + 1 and observed == [expected_thread] and wake == [True]
    check = read(api, command)
    assert check["trigger"] == "scheduled" and check["period_start"] == clock.value.isoformat(timespec="milliseconds")
    assert check["requested_to"] == check["created_at"] == clock.value.isoformat(timespec="milliseconds")
    assert check["config_revision"]["deadline_at"] == (clock.value + timedelta(seconds=1800)).isoformat(timespec="milliseconds")
    route = next(r for r in api.app.routes if getattr(r, "path", "").endswith("/{watch_id}/schedule"))
    assert inspect.iscoroutinefunction(route.endpoint)


def test_restart_after_queue_commit_executes_once_without_old_due_catchup(api):  # 13d
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    restarted = WatchScheduler(api.store, lambda: None, clock)
    assert not loop(api, restarted.tick)["queued"]
    turn(api)
    assert read(api, command)["state"] == "succeeded" and len(api.sent) == 2
    assert len(api.watches.checks(first["watch_id"])) == 2 and not api.watches.gaps(first["watch_id"])


def test_crash_inside_completion_recovery_retains_publication_and_resumes_once(api, monkeypatch):  # 13e
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    api.state.payload = page(work("NEW"))
    command = due(api, sched, clock, first)
    before = rows(api.conn, ["watch_seen", "watch_seen_alias", "watch_items"])
    baseline_json = api.watches.watch(api.rid, first["watch_id"])["baseline_json"]
    original = api.store.update_run
    def crash(run_id, **kwargs):
        if run_id == command["run_id"] and kwargs.get("status") == "completed":
            raise Crash("SYNTHETIC before terminal write")
        return original(run_id, **kwargs)
    monkeypatch.setattr(api.store, "update_run", crash)
    with pytest.raises(Crash): turn(api)
    assert api.store.run(command["run_id"])["status"] == "running"
    assert rows(api.conn, ["watch_seen", "watch_seen_alias", "watch_items"]) == before
    assert api.watches.watch(api.rid, first["watch_id"])["baseline_json"] == baseline_json
    sent = len(api.sent)
    loop(api, api.app.state.worker.recover)
    clock.value += timedelta(days=2)
    assert not loop(api, sched.tick)["queued"]
    assert read(api, command)["pause_reason"] == "backend_restarted"
    monkeypatch.setattr(api.store, "update_run", original)
    control(api, command, "resume"); turn(api)
    assert read(api, command)["state"] == "succeeded" and len(api.sent) == sent and len(api.watches.items(api.rid)) == 1


def test_paused_check_not_superseded_then_owner_cancel_admits_due(api):  # 13f
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    loop(api, api.store.update_run, command["run_id"], status="paused")
    clock.value += timedelta(days=2)
    assert not loop(api, sched.tick)["queued"]
    assert read(api, command)["state"] == "paused"
    assert api.client.get(api.url).json()[0]["waiting_reason"] == "check_paused"
    control(api, command, "cancel")
    result = loop(api, sched.tick)
    assert len(result["queued"]) == 1 and read(api, result["queued"][0])["trigger"] == "scheduled"


def test_failed_scheduled_check_does_not_retry_inside_interval(api):  # 13h
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    api.state.status = 500
    command = due(api, sched, clock, first); turn(api)
    assert read(api, command)["state"] == "failed"
    before = hashes(api.conn); clock.value += timedelta(seconds=60)
    assert not loop(api, sched.tick)["queued"] and hashes(api.conn) == before


def test_pause_requested_scheduled_then_paused_never_doubled(api):  # 13m
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    def pause(request):
        api.store.update_run(command["run_id"], status="pause_requested")
        clock.value += timedelta(days=2)
        assert not sched.tick()["queued"]
        return httpx.Response(200, json=page(work(), cursor="next"))
    api.state.handler = pause
    turn(api)
    assert read(api, command)["state"] == "paused"
    assert not loop(api, sched.tick)["queued"] and len(api.watches.checks(first["watch_id"])) == 2


def test_sleep_gap_three_periods_one_catchup_and_stored_gap_view(api):  # 13n
    first = baseline(api); sched, clock, _ = scheduler(api)
    start = clock.value
    clock.value += timedelta(days=3, minutes=1)
    result = loop(api, sched.tick)
    assert len(result["queued"]) == len(result["recorded"]) == 1
    check = read(api, result["queued"][0])
    assert check["trigger"] == "catch_up" and check["missed_periods"] == 3
    assert check["gap"]["to"] == clock.value.isoformat(timespec="milliseconds") and check["gap"]["missed_periods"] == 3
    gap = api.watches.gaps(first["watch_id"])[0]
    assert gap["observed_until"] == start.isoformat(timespec="milliseconds") and check["schedule"]["gap_id"] == gap["id"]
    assert check["gap"]["notice"] == f"Not checked between {gap['first_missed_due']} and {gap['noticed_at']}."


def test_t16_baseline_two_scheduled_gap_restart_announces_once_and_reports_coverage(api):  # 13y
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    api.state.payload = page(work(), work("NEW"))
    for _ in range(2):
        command = due(api, sched, clock, first); turn(api)
        clock.value = datetime.fromisoformat(api.watches.watch(api.rid, first["watch_id"])["next_due_at"]) - timedelta(seconds=1)
        # Continuous scheduling, with no due time inside this synthetic observation interval.
        assert not loop(api, sched.tick)["queued"]
    clock.value += timedelta(days=3, minutes=1)
    catchup = loop(api, sched.tick)["queued"][0]; turn(api)
    view = read(api, catchup)
    assert view["trigger"] == "catch_up" and view["gap"]["missed_periods"] >= 3
    assert view["observed"]["units"]["query:0"]["coverage"] == "covered"
    restarted = WatchScheduler(api.store, lambda: None, clock)
    assert not loop(api, restarted.tick)["queued"]
    assert len(api.watches.items(api.rid)) == 1 and len(api.watches.checks(first["watch_id"])) == 4


def test_idle_tick_on_started_worker_has_zero_authorizer_write_attempts(tmp_path):  # 13v
    with watch_api(tmp_path, start_worker=True) as api:
        scheduler = api.app.state.watch_scheduler
        attempts = []
        def guard(action, table, column, database, trigger):
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                attempts.append((action, table, column)); return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        def guarded():
            before = hashes(api.conn)
            api.conn.set_authorizer(guard)
            try:
                result = scheduler.tick()
                assert not result["queued"] and not result["recorded"]
                assert not attempts and hashes(api.conn) == before
            finally:
                api.conn.set_authorizer(None)
        loop(api, guarded)


import asyncio
import json
import sqlite3
import threading

import httpx
import pytest

from deixis.storage import db
from deixis.workflow import watch_run
from deixis.workflow import watch_check as policy
from deixis.workflow.watch_store import WatchStore
from watch_helpers import api, watch_offline, watch_api, create, now_check, turn, read, control, page, work, rows, add_included


class Crash(BaseException):
    pass


def test_recovery_after_reads_before_completion_resumes_once_without_send(api, monkeypatch):
    first = create(api); turn(api)
    api.state.payload = page(work("NEW"))
    second = now_check(api, first["watch_id"])
    original = WatchStore.complete_check
    def crash(*args, **kwargs):
        raise Crash("SYNTHETIC process interruption after reads")
    monkeypatch.setattr(WatchStore, "complete_check", crash)
    with pytest.raises(Crash): turn(api)
    assert not api.watches.items(api.rid)
    assert api.store.run(second["run_id"])["status"] == "running"
    sent = len(api.sent); usage = api.store.run(second["run_id"])["usage"]
    api.app.state.worker.recover()
    assert read(api, second)["state"] == "paused" and read(api, second)["pause_reason"] == "backend_restarted"
    monkeypatch.setattr(WatchStore, "complete_check", original)
    control(api, second, "resume"); turn(api)
    assert read(api, second)["state"] == "succeeded" and len(api.watches.items(api.rid)) == 1
    assert len(api.sent) == sent and api.store.run(second["run_id"])["usage"] == usage
    before = rows(api.conn)
    api.client.portal.call(api.app.state.worker.flow.execute, second["run_id"])
    assert rows(api.conn) == before and len(api.sent) == sent


def test_resumed_check_refuses_changed_adapter_before_using_stored_cursor(api, monkeypatch):
    from dataclasses import replace
    from deixis.providers import registry
    api.state.payload = page(work(), cursor="next")
    command = create(api)
    original = WatchStore.record_read
    def crash(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise Crash("SYNTHETIC interruption after first cursor page")
    monkeypatch.setattr(WatchStore, "record_read", crash)
    with pytest.raises(Crash): turn(api)
    api.app.state.worker.recover()
    monkeypatch.setattr(WatchStore, "record_read", original)
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(registry.CONNECTORS["openalex"], adapter_revision=4))
    control(api, command, "resume"); turn(api)
    assert read(api, command)["failure_reason"] == "adapter_revision_changed"
    assert len(api.sent) == 1 and api.store.run(command["run_id"])["usage"]["provider_requests"] == 1
    assert not api.conn.execute("SELECT 1 FROM watch_seen").fetchone()
    assert not api.watches.items(api.rid)


@pytest.mark.parametrize("change,reason", [("scope", "scope_revised")])
def test_live_state_change_while_last_request_held_publishes_nothing(api, change, reason):
    command = create(api)
    entered = threading.Event(); release = threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.001)
        return httpx.Response(200, json=page(work("NEW")))
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    try:
        if change == "disable":
            response = api.client.post(api.url + f"/{command['watch_id']}/disable", json={"expected_state_version": 1},
                headers={"Idempotency-Key": "held-disable"})
            assert response.status_code == 200
        elif change == "scope":
            api.store.revise_scope(api.rid, api.store.research(api.rid)["version"], "SYNTHETIC revised", None)
        elif change == "protocol":
            api.store.freeze_protocol(api.rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "changed"}]}, "SYNTHETIC changed")
        elif change == "trash":
            # The ordinary trash route correctly refuses active work; a committed external revision is simulated.
            api.conn.execute("UPDATE researches SET trashed_at=? WHERE id=?", (db.now(), api.rid))
        else:
            api.conn.execute("UPDATE watches SET state_version=state_version+1 WHERE id=?", (command["watch_id"],))
    finally:
        release.set()
    future.result(5)
    result = api.store.run(command["run_id"])
    assert result["status"] == ("failed" if change == "state_version" else "cancelled") and result["pause_reason"] == reason
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 0
    assert api.conn.execute("SELECT count(*) FROM watch_items").fetchone()[0] == 0
    assert api.conn.execute("SELECT count(*) FROM watch_reads").fetchone()[0] == 1
    assert api.conn.execute("SELECT completed_at FROM watch_checks").fetchone()[0] is None


def test_paused_resume_past_deadline_sends_nothing_and_keeps_usage(api, monkeypatch):
    command = create(api)
    frozen = api.store.run(command["run_id"])["target"]["deadline_at"]
    def pause(request):
        api.store.update_run(command["run_id"], status="pause_requested")
        return httpx.Response(200, json=page(work(), cursor="remaining"))
    api.state.handler = pause
    turn(api)
    assert read(api, command)["state"] == "paused"
    usage = api.store.run(command["run_id"])["usage"]
    monkeypatch.setattr(watch_run, "now", lambda: "2099-01-01T00:00:00+00:00")
    control(api, command, "resume"); turn(api)
    assert len(api.sent) == 1 and api.store.run(command["run_id"])["usage"] == usage
    assert api.store.run(command["run_id"])["target"]["deadline_at"] == frozen
    assert "deadline_deferred" in read(api, command)["partial_reasons"]


def test_run_states_through_pause_resume_cancel_recovery_and_worker_error(api):
    command = create(api)
    assert read(api, command)["state"] == "queued"
    api.store.update_run(command["run_id"], status="running")
    assert read(api, command)["state"] == "running"
    control(api, command, "pause")
    assert read(api, command)["state"] == "pause_requested"
    api.client.portal.call(api.app.state.worker.flow.execute, command["run_id"])
    assert read(api, command)["state"] == "paused"
    control(api, command, "resume")
    assert read(api, command)["state"] == "queued"
    turn(api)
    assert read(api, command)["state"] == "succeeded"
    second = now_check(api, command["watch_id"])
    control(api, second, "cancel")
    assert read(api, second)["state"] == "cancelled"


import asyncio
import sqlite3
from collections import defaultdict
from itertools import count

import pytest
from deixis.workflow.watch_scheduler import WatchScheduler
from deixis.workflow.worker import Worker
from deixis.workflow.flow import ResearchFlow
from watch_helpers import watch_offline, watch_api


def instrument(monkeypatch):
    clocks, events, sequence = {}, defaultdict(list), count()
    def record(instance, event):
        events[instance].append((next(sequence), event))
    original_init, original_run = WatchScheduler.__init__, WatchScheduler.run_forever
    recover, tick = Worker.recover, WatchScheduler.tick
    def init(self, store, wake, **kwargs):
        clocks[self] = Clock()
        original_init(self, store, wake, clocks[self])
    def recovery(self):
        record(self, "recover"); return recover(self)
    def observed_tick(self):
        record(self, "tick"); return tick(self)
    async def run(self, stop):
        try: await original_run(self, stop)
        finally: record(self, "scheduler_stopped")
    monkeypatch.setattr(WatchScheduler, "__init__", init)
    monkeypatch.setattr(WatchScheduler, "run_forever", run)
    monkeypatch.setattr(WatchScheduler, "tick", observed_tick)
    monkeypatch.setattr(Worker, "recover", recovery)
    queue_person_readings = ResearchFlow.queue_person_readings
    def queued(self):
        result = queue_person_readings(self)
        record(self, "queue_person_readings")
        return result
    monkeypatch.setattr(ResearchFlow, "queue_person_readings", queued)
    release = Worker.release
    stop_worker = Worker.stop
    async def stopped(self):
        record(self, "worker_stopped")
        return await stop_worker(self)
    monkeypatch.setattr(Worker, "stop", stopped)
    def released(self):
        record(self, "worker_released"); return release(self)
    monkeypatch.setattr(Worker, "release", released)
    return clocks, events


def app_events(api, events):
    instances = (api.app.state.worker, api.app.state.worker.flow, api.app.state.watch_scheduler)
    return [event for _, event in sorted(entry for instance in instances for entry in events[instance])]


def test_start_worker_false_has_no_scheduler(tmp_path):
    with watch_api(tmp_path) as api:
        assert not hasattr(api.app.state, "watch_scheduler")


def test_owner_recovers_before_first_tick_and_shutdown_stops_scheduler_before_release(tmp_path, monkeypatch):
    clocks, events = instrument(monkeypatch)
    with watch_api(tmp_path, start_worker=True) as api:
        assert api.app.state.owner
        assert hasattr(api.app.state, "watch_scheduler")
        loop(api, asyncio.sleep, .01)
        observed = app_events(api, events)
        assert clocks[api.app.state.watch_scheduler].calls == 1
        assert observed[:3] == ["recover", "queue_person_readings", "tick"]
    observed = app_events(api, events)
    assert observed.index("scheduler_stopped") < observed.index("worker_released")
    assert observed.index("scheduler_stopped") < observed.index("worker_stopped")


def test_nonowner_no_scheduler_until_takeover_then_recovers_ticks_and_stops(tmp_path, monkeypatch):
    clocks, events = instrument(monkeypatch)
    acquire = Worker.acquire
    allowed = [False]
    monkeypatch.setattr(Worker, "acquire", lambda self: acquire(self) if allowed[0] else False)
    with watch_api(tmp_path, start_worker=True) as api:
        assert not api.app.state.owner and not hasattr(api.app.state, "watch_scheduler")
        allowed[0] = True
        async def wait():
            for _ in range(150):
                if hasattr(api.app.state, "watch_scheduler") and clocks[api.app.state.watch_scheduler].calls: return
                await asyncio.sleep(.01)
            pytest.fail("takeover did not start scheduler")
        loop(api, wait)
        assert api.app.state.owner
        assert app_events(api, events)[:3] == ["recover", "queue_person_readings", "tick"]
    observed = app_events(api, events)
    assert observed.index("scheduler_stopped") < observed.index("worker_released")
    assert observed.index("scheduler_stopped") < observed.index("worker_stopped")


import asyncio
import socket

import pytest

import watch_driver


def test_watch_driver_refuses_and_logs_connect_connect_ex_and_dns(monkeypatch):
    events, local_calls = [], []
    monkeypatch.setattr(watch_driver, "log", lambda **entry: events.append(entry))
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: local_calls.append(address))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: local_calls.append(address) or 0)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: local_calls.append(host) or [])
    watch_driver.guard_network()
    with socket.socket() as sock:
        with pytest.raises(OSError, match="non-loopback"): sock.connect(("203.0.113.1", 9999))
        with pytest.raises(OSError, match="non-loopback"): sock.connect_ex(("203.0.113.1", 9999))
        with pytest.raises(OSError, match="non-loopback"): socket.getaddrinfo("synthetic.invalid", 443)
        with pytest.raises(OSError, match="non-loopback"): socket.getaddrinfo("127.synthetic.invalid", 443)
        sock.connect(("127.0.0.1", 9999)); sock.connect_ex(("::1", 9999))
        socket.getaddrinfo(b"127.0.0.1", 9999)
    assert [e["what"] for e in events] == ["connect", "connect_ex", "getaddrinfo", "getaddrinfo"]
    assert all(e["kind"] == "network" for e in events) and len(local_calls) == 3

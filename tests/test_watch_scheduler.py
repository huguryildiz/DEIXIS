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
from deixis.workflow.watch import check as policy, run as watch_run, store as watch_store
from deixis.workflow.watch.scheduler import WatchScheduler
from deixis.workflow.watch.store import WatchStore
from tests.watch_helpers import (api, watch_offline, watch_api, create, now_check, turn, read, control,
                                 page, work, rows, hashes, add_included)
from tests.test_watch_recovery import Crash


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


@pytest.mark.parametrize("microsecond", [0, 123456])
def test_scheduler_timestamps_use_fixed_milliseconds_for_scheduled_and_gap_checks(api, microsecond):
    first = baseline(api)
    at = datetime.fromisoformat(api.watches.watch(api.rid, first["watch_id"])["next_due_at"]).replace(microsecond=microsecond)
    set_due(api, first, at.isoformat())
    clock = Clock(at - timedelta(seconds=1))
    sched = WatchScheduler(api.store, lambda: None, clock)
    assert not loop(api, sched.tick)["queued"]
    clock.value = at
    scheduled = loop(api, sched.tick)["queued"][0]
    view = read(api, scheduled)
    assert view["period_start"] == at.isoformat(timespec="milliseconds")
    turn(api)
    clock.value += timedelta(days=3, minutes=1)
    result = loop(api, sched.tick)
    assert len(result["recorded"]) == len(result["queued"]) == 1
    gap = result["recorded"][0]
    catchup = read(api, result["queued"][0])
    timestamps = [view["period_start"], view["requested_to"], view["created_at"], view["config_revision"]["deadline_at"],
        catchup["period_start"], catchup["requested_to"], catchup["created_at"], catchup["config_revision"]["deadline_at"],
        api.watches.watch(api.rid, first["watch_id"])["next_due_at"],
        *(gap[key] for key in ("first_missed_due", "last_missed_due", "observed_until", "noticed_at", "next_due_at", "created_at"))]
    for ts in timestamps:
        assert ts == datetime.fromisoformat(ts).isoformat(timespec="milliseconds")
    assert catchup["requested_to"] == clock.value.isoformat(timespec="milliseconds")


def test_one_period_after_completion_and_period_replay(api):  # 13b
    first = baseline(api); sched, clock, wake = scheduler(api, first)
    command = due(api, sched, clock, first); turn(api)
    clock.value += timedelta(seconds=60)
    before = hashes(api.conn)
    assert not loop(api, sched.tick)["queued"]
    result = replay(api, command)
    assert result["replayed"] and result["check_id"] == command["check_id"] and result["run_id"] == command["run_id"]
    assert hashes(api.conn) == before and len(api.watches.checks(first["watch_id"])) == 2


def test_queue_atomic_failure_after_create_run(api, monkeypatch):  # 13c
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    original = api.store.create_run
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC after create_run")
    monkeypatch.setattr(api.store, "create_run", fail)
    clock.value += timedelta(seconds=1)
    before = hashes(api.conn)
    with pytest.raises(RuntimeError, match="after create_run"):
        loop(api, sched.tick)
    assert hashes(api.conn) == before and not api.conn.in_transaction


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


@pytest.mark.parametrize("other", [False, True])
def test_global_busy_same_or_other_research_leaves_due_then_queues(api, other):  # 13g
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    rid = api.rid if not other else loop(api, api.store.create_research, "SYNTHETIC owner", "academic", "standard", [], "fake", "fake-model", "en")
    owner = loop(api, api.store.create_run, rid, "answer", {}, "SYNTHETIC-owner-run")
    old = api.watches.watch(api.rid, first["watch_id"])["next_due_at"]
    clock.value += timedelta(seconds=1)
    before = hashes(api.conn)
    result = loop(api, sched.tick)
    assert not result["queued"] and any(s["reason"] == "run_active" for s in result["skipped"])
    assert hashes(api.conn) == before and api.watches.watch(api.rid, first["watch_id"])["next_due_at"] == old
    loop(api, api.store.update_run, owner["id"], status="completed")
    assert len(loop(api, sched.tick)["queued"]) == 1


def test_failed_scheduled_check_does_not_retry_inside_interval(api):  # 13h
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    api.state.status = 500
    command = due(api, sched, clock, first); turn(api)
    assert read(api, command)["state"] == "failed"
    before = hashes(api.conn); clock.value += timedelta(seconds=60)
    assert not loop(api, sched.tick)["queued"] and hashes(api.conn) == before


def test_manual_interval_check_resets_due_in_queue_transaction(api, monkeypatch):  # 13i, old behavioral
    first = baseline(api)
    ts = db.now()
    monkeypatch.setattr(watch_store, "now", lambda: ts)
    command = now_check(api, first["watch_id"])
    assert api.watches.watch(api.rid, first["watch_id"])["next_due_at"] == policy.next_due(ts, 1)
    assert read(api, command)["schedule"]["trigger"] == "manual"


@pytest.mark.parametrize("state", ["queued", "running", "completed", "disabled", "scope"])
def test_period_replay_precedes_all_admission_and_writes_nothing(api, state):  # 13j
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    if state == "completed": turn(api)
    elif state == "running": loop(api, api.store.update_run, command["run_id"], status="running")
    elif state == "disabled":
        api.client.post(api.url + f"/{first['watch_id']}/disable", json={"expected_state_version": 2}, headers={"Idempotency-Key": "disable"})
    elif state == "scope":
        loop(api, api.store.revise_scope, api.rid, api.store.research(api.rid)["version"], "SYNTHETIC scope", None)
    before = hashes(api.conn); sent = len(api.sent)
    result = replay(api, command)
    assert result["replayed"] and result["check_id"] == command["check_id"] and result["run_id"] == command["run_id"]
    assert hashes(api.conn) == before and len(api.sent) == sent


def test_two_check_now_tabs_keys_and_replay(api):  # 13k
    first = baseline(api)
    body = {"expected_state_version": 2}
    url = api.url + f"/{first['watch_id']}/checks"
    one = api.client.post(url, json=body, headers={"Idempotency-Key": "tab-one"})
    two = api.client.post(url, json=body, headers={"Idempotency-Key": "tab-two"})
    assert one.status_code == 202 and two.status_code == 409 and two.json()["code"] == "run_active"
    before = hashes(api.conn)
    replayed = api.client.post(url, json=body, headers={"Idempotency-Key": "tab-one"})
    assert replayed.json()["replayed"] and replayed.json()["check_id"] == one.json()["check_id"] and hashes(api.conn) == before


@pytest.mark.parametrize("manual_first", [True, False])
def test_manual_scheduled_race_both_orders(api, manual_first):  # 13l
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    clock.value += timedelta(seconds=1)
    if manual_first:
        command = now_check(api, first["watch_id"])
        assert not loop(api, sched.tick)["queued"]
    else:
        command = loop(api, sched.tick)["queued"][0]
        response = api.client.post(api.url + f"/{first['watch_id']}/checks", json={"expected_state_version": 2},
                                   headers={"Idempotency-Key": "racing-manual"})
        assert response.status_code == 409 and response.json()["code"] == "run_active"
    assert len(api.watches.checks(first["watch_id"])) == 2 and api.store.run(command["run_id"])["status"] == "queued"


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


def test_forward_clock_opening_and_backwards_wait_without_writes(api):  # 13o
    first = baseline(api); sched, clock, _ = scheduler(api)
    clock.value += timedelta(days=1, seconds=301)
    assert read(api, loop(api, sched.tick)["queued"][0])["trigger"] == "catch_up"
    turn(api); before = hashes(api.conn)
    clock.value -= timedelta(days=2)
    assert not loop(api, sched.tick)["queued"] and hashes(api.conn) == before


def test_tick_during_held_scheduled_request_does_not_double(api):  # 13p
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    entered, release = threading.Event(), threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set(): await asyncio.sleep(.001)
        return httpx.Response(200, json=page(work()))
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    try:
        clock.value += timedelta(days=1)
        assert not loop(api, sched.tick)["queued"] and read(api, command)["state"] == "running"
        assert len(api.watches.checks(first["watch_id"])) == 2
    finally:
        release.set(); future.result(5)


def test_schedule_change_held_check_preserves_config_and_completes(api):  # 13w, 0
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    frozen = api.watches.check(api.rid, command["check_id"])["config_json"]
    old = api.watches.watch(api.rid, first["watch_id"])
    entered, release = threading.Event(), threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set(): await asyncio.sleep(.001)
        return httpx.Response(200, json=page(work()))
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    try:
        seen = []
        original = WatchStore.schedule
        def called(self, *args):
            seen.append(threading.get_ident())
            return original(self, *args)
        # Store command is driven through the async API route, on the same loop as tick and worker.
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(WatchStore, "schedule", called)
            response = schedule(api, first["watch_id"])
        assert response.status_code == 200 and seen == [loop(api, threading.get_ident)]
        current = api.watches.watch(api.rid, first["watch_id"])
        assert current["state_version"] == old["state_version"] and current["baseline_json"] == old["baseline_json"]
        assert current["schedule_version"] == 2 and current["catch_up"] == 0
        assert api.watches.check(api.rid, command["check_id"])["config_json"] == frozen
    finally:
        release.set(); future.result(5)
    assert read(api, command)["state"] == "succeeded"


@pytest.mark.parametrize("state", ["queued", "paused"])
def test_schedule_change_queued_or_paused_config_frozen_and_check_completes(api, state):
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    frozen = api.watches.check(api.rid, command["check_id"])["config_json"]
    if state == "paused": loop(api, api.store.update_run, command["run_id"], status="paused")
    assert schedule(api, first["watch_id"], mode="manual", interval_days=None, catch_up=None).status_code == 200
    assert api.watches.check(api.rid, command["check_id"])["config_json"] == frozen
    if state == "paused": control(api, command, "resume")
    turn(api)
    assert read(api, command)["state"] == "succeeded" and len(api.sent) == 2
    assert api.watches.watch(api.rid, first["watch_id"])["next_due_at"] is None


def test_schedule_replay_content_conflicts_versions_coherence_disabled_and_global_keys(api):  # 13w
    first = baseline(api)
    key = "schedule-key"
    one = schedule(api, first["watch_id"], key=key, version=1)
    assert one.status_code == 200
    before = hashes(api.conn)
    two = schedule(api, first["watch_id"], key=key, version=1)
    assert two.json()["replayed"] and hashes(api.conn) == before
    assert schedule(api, first["watch_id"], key=key, version=1, interval_days=30).json()["code"] == "idempotency_key_reused"
    assert schedule(api, first["watch_id"], version=1).json()["code"] == "schedule_changed"
    assert schedule(api, first["watch_id"], mode="manual").json()["code"] == "schedule_invalid"
    response = schedule(api, first["watch_id"], mode="manual", interval_days=None, catch_up=None)
    assert response.status_code == 200 and response.json()["watch"]["next_due_at"] is None
    body = {"mode": "interval", "interval_days": 1, "catch_up": 1, "expected_schedule_version": 3}
    assert api.client.post(api.url + f"/{first['watch_id']}/schedule", json=body, headers={"Idempotency-Key": "strict"}).status_code == 422
    api.client.post(api.url + f"/{first['watch_id']}/disable", json={"expected_state_version": 2}, headers={"Idempotency-Key": "disabled"})
    assert schedule(api, first["watch_id"]).json()["code"] == "watch_disabled"
    assert schedule(api, first["watch_id"], key=key, version=1).json()["replayed"]
    other = loop(api, api.store.create_research, "SYNTHETIC other", "academic", "standard", [], "fake", "fake-model", "en")
    response = api.client.post(api.url.replace(api.rid, other), json={"kind": "citing_works", "mode": "manual", "expected_scope_revision": 1}, headers={"Idempotency-Key": key})
    assert response.json()["code"] == "idempotency_key_reused"


@pytest.mark.parametrize("interval,catch", [(1, True), (7, False), (30, True)])
def test_interval_create_rebind_copies_settings_and_fresh_due(api, interval, catch):
    first = create(api, mode="interval", interval_days=interval, catch_up=catch); turn(api)
    response = api.client.post(api.url + f"/{first['watch_id']}/rebind", json={"expected_state_version": 2}, headers={"Idempotency-Key": "rebind"})
    assert response.status_code == 201
    new = response.json()
    assert new["watch"]["interval_days"] == interval and new["watch"]["catch_up"] is catch
    assert new["watch"]["next_due_at"] == policy.next_due(new["check"]["requested_to"], interval)


@pytest.mark.parametrize("extra", [{"mode": "interval"}, {"mode": "interval", "interval_days": 1},
    {"mode": "interval", "catch_up": True}, {"interval_days": 1}, {"catch_up": False}])
def test_schedule_invalid_create_no_write(api, extra):
    before = hashes(api.conn)
    response = api.client.post(api.url, json={"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1, **extra}, headers={"Idempotency-Key": "invalid"})
    assert response.status_code == 422 and response.json()["code"] == "schedule_invalid" and hashes(api.conn) == before


@pytest.mark.parametrize("change", ["scope", "protocol"])
def test_scope_or_protocol_revision_during_scheduled_send_refuses_next_gate(api, change):  # 13t
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    entered, release = threading.Event(), threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set(): await asyncio.sleep(.001)
        return httpx.Response(429, headers={"retry-after": "0"})
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    try:
        if change == "scope":
            loop(api, api.store.revise_scope, api.rid, api.store.research(api.rid)["version"], "SYNTHETIC revised", None)
        else:
            loop(api, api.store.freeze_protocol, api.rid, 1, {"compiled_queries": []}, "SYNTHETIC new protocol")
    finally:
        release.set(); future.result(5)
    assert api.store.run(command["run_id"])["status"] == "cancelled" and len(api.sent) == 2
    assert not api.watches.items(api.rid)
    clock.value += timedelta(days=2)
    result = loop(api, sched.tick)
    assert not result["queued"] and any(s["reason"] == "watch_follows_old_scope" for s in result["skipped"])


def test_deadline_restart_resume_keep_usage_and_frozen_deadline(api, monkeypatch):  # 13x
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    command = due(api, sched, clock, first)
    def pause(request):
        api.store.update_run(command["run_id"], status="pause_requested")
        return httpx.Response(200, json=page(work(), cursor="next"))
    api.state.handler = pause; turn(api)
    assert read(api, command)["state"] == "paused"
    frozen = api.store.run(command["run_id"])
    loop(api, api.app.state.worker.recover)
    assert not loop(api, WatchScheduler(api.store, lambda: None, clock).tick)["queued"]
    monkeypatch.setattr(watch_run, "now", lambda: (datetime.fromisoformat(frozen["target"]["deadline_at"]) + timedelta(seconds=1)).isoformat())
    sent = len(api.sent)
    control(api, command, "resume"); turn(api)
    after = api.store.run(command["run_id"])
    assert after["usage"] == frozen["usage"] and after["target"]["deadline_at"] == frozen["target"]["deadline_at"]
    assert len(api.sent) == sent and "deadline_deferred" in read(api, command)["partial_reasons"]


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


def extra_watch(api, kind="protocol_queries", catch_up=True, rid=None):
    if rid is None:
        rid = loop(api, api.store.create_research, "SYNTHETIC scheduler research", "academic", "standard", ["openalex"], "fake", "fake-model", "en", search_workflow="sw")
        loop(api, api.store.freeze_protocol, rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC extra"}]})
    command = loop(api, api.watches.create, rid, {"kind": kind, "mode": "interval", "interval_days": 1, "catch_up": catch_up,
        "expected_scope_revision": 1}, db.new_id("cmd"))
    turn(api)
    return command | {"research_id": rid}


def set_due(api, command, ts):
    loop(api, api.conn.execute, "UPDATE watches SET next_due_at=? WHERE id=?", (ts, command["watch_id"]))


def test_process_opening_all_outcomes_caps_and_rank_order_one_per_tick(api):  # 13q
    first = baseline(api) | {"research_id": api.rid}
    add_included(api, "SEED")
    second_kind = extra_watch(api, "citing_works", rid=api.rid)
    others = [extra_watch(api) for _ in range(3)]
    off = extra_watch(api, catch_up=False)
    paused, old_scope = extra_watch(api), extra_watch(api)
    clock = Clock(); clock.value += timedelta(days=5)
    start = clock.value - timedelta(days=3)
    all_commands = [first, second_kind, *others, off, paused, old_scope]
    for index, cmd in enumerate(all_commands):
        set_due(api, cmd, (start + timedelta(minutes=index if index > 1 else 0)).isoformat())
    loop(api, api.store.update_run, paused["run_id"], status="paused")
    loop(api, api.store.revise_scope, old_scope["research_id"], api.store.research(old_scope["research_id"])["version"], "SYNTHETIC changed", None)
    sched = WatchScheduler(api.store, lambda: None, clock)
    result = loop(api, sched.tick)
    gaps = {g["watch_id"]: g for g in result["recorded"]}
    assert len(gaps) == 8 and len(result["queued"]) == 1
    assert gaps[first["watch_id"]]["outcome"] == "catch_up_chosen"
    assert gaps[second_kind["watch_id"]]["outcome"] == "one_per_research"
    assert gaps[others[-1]["watch_id"]]["outcome"] == "opening_cap"
    assert gaps[off["watch_id"]]["outcome"] == "catch_up_off"
    assert gaps[paused["watch_id"]]["outcome_reason"] == "check_paused"
    assert gaps[old_scope["watch_id"]]["outcome_reason"] == "watch_follows_old_scope"
    chosen = [first, *others[:2]]
    assert result["queued"][0]["watch_id"] == chosen[0]["watch_id"]
    for cmd in all_commands:
        gap = gaps[cmd["watch_id"]]
        assert gap["observed_until"] is None
        live = api.watches.watch(cmd["research_id"], cmd["watch_id"])
        if gap["outcome"] in ("one_per_research", "opening_cap", "catch_up_off"):
            assert live["next_due_at"] == gap["next_due_at"] and datetime.fromisoformat(live["next_due_at"]) > clock.value
        elif gap["outcome"] == "not_eligible":
            assert datetime.fromisoformat(live["next_due_at"]) == datetime.fromisoformat(gap["first_missed_due"])
    before = hashes(api.conn)
    assert not loop(api, sched.tick)["queued"] and hashes(api.conn) == before
    for cmd in chosen[1:]:
        turn(api)
        queued = loop(api, sched.tick)["queued"]
        assert len(queued) == 1 and queued[0]["watch_id"] == cmd["watch_id"]
        row = api.watches.check(cmd["research_id"], queued[0]["check_id"])
        assert row["trigger"] == "catch_up" and json.loads(row["config_json"])["schedule"]["gap_id"] == gaps[cmd["watch_id"]]["id"]
    turn(api)
    assert not loop(api, sched.tick)["queued"] and not sched.pending
    listing = api.client.get(api.url).json()
    assert all(w["gaps"][0]["catch_up_queued"] == (w["id"] == first["watch_id"]) for w in listing)


def test_opening_accounting_rollback_same_episode_history_after_four_owner_changes(api, monkeypatch):  # 13r
    commands = [baseline(api, catch_up=False) | {"research_id": api.rid}, *[extra_watch(api) for _ in range(5)]]
    clock = Clock(); clock.value += timedelta(days=4)
    for index, cmd in enumerate(commands):
        set_due(api, cmd, (clock.value - timedelta(days=2) + timedelta(minutes=index)).isoformat())
    sched = WatchScheduler(api.store, lambda: None, clock)
    original = WatchStore.record_gap
    writes = []
    def fail(self, row):
        original(self, row); writes.append(row["id"])
        raise sqlite3.OperationalError("SYNTHETIC failure after first gap")
    monkeypatch.setattr(WatchStore, "record_gap", fail)
    before = hashes(api.conn)
    with pytest.raises(sqlite3.OperationalError): loop(api, sched.tick)
    assert hashes(api.conn) == before and sched.previous_tick is None and not sched.pending
    episode = sched.opening
    assert episode["episodes"][0]["watch"]["id"] == commands[0]["watch_id"]
    assert writes == [episode["episodes"][0]["gap_id"]]
    monkeypatch.setattr(WatchStore, "record_gap", original)
    monkeypatch.setattr(watch_store, "now", lambda: clock.value.isoformat())
    # All commands execute on the application's event loop through the store or API.
    a, b, c, d = commands[:4]
    loop(api, api.watches.schedule, a["research_id"], a["watch_id"], {"mode": "interval", "interval_days": 7, "catch_up": True, "expected_schedule_version": 1}, "change-a")
    loop(api, api.watches.check_now, b["research_id"], b["watch_id"], {"expected_state_version": 2}, "change-b"); turn(api)
    loop(api, api.watches.disable, c["research_id"], c["watch_id"], {"expected_state_version": 2}, "change-c")
    loop(api, api.watches.rebind, d["research_id"], d["watch_id"], {"expected_state_version": 2}, "change-d"); turn(api)
    changed = [api.watches.watch(cmd["research_id"], cmd["watch_id"]) for cmd in commands[:4]]
    clock.value += timedelta(seconds=60)
    result = loop(api, sched.tick)
    gaps = {g["watch_id"]: g for g in result["recorded"]}
    assert len(gaps) == 6 and {g["opening_id"] for g in gaps.values()} == {episode["id"]}
    assert {g["noticed_at"] for g in gaps.values()} == {episode["noticed_at"]}
    for cmd, old, reason in zip(commands[:4], changed, ["schedule_changed", "next_due_changed", "disabled", "disabled"]):
        gap = gaps[cmd["watch_id"]]
        assert gap["outcome"] == "changed_before_record" and gap["outcome_reason"] == reason and gap["schedule_version"] == 1
        assert api.watches.watch(cmd["research_id"], cmd["watch_id"]) == old
        assert not any(p["watch"]["id"] == cmd["watch_id"] for p in sched.pending)
    assert all(gaps[c["watch_id"]]["outcome"] == "catch_up_chosen" for c in commands[4:])
    assert {r[0] for r in api.conn.execute("SELECT id FROM watch_gaps")} == {e["gap_id"] for e in episode["episodes"]}
    before = hashes(api.conn)
    assert not loop(api, sched.tick)["recorded"] and hashes(api.conn) == before


@pytest.mark.parametrize("change", ["schedule", "check_now", "disable", "rebind"])
def test_stale_pending_choice_dropped_no_write_gap_history_unchanged(api, monkeypatch, change):  # 13s
    first = baseline(api)
    owner_rid = loop(api, api.store.create_research, "SYNTHETIC owner", "academic", "standard", [], "fake", "fake-model", "en")
    owner = loop(api, api.store.create_run, owner_rid, "answer", {}, "owner")
    clock = Clock(); clock.value += timedelta(days=3)
    sched = WatchScheduler(api.store, lambda: None, clock)
    assert not loop(api, sched.tick)["queued"] and len(sched.pending) == 1
    gap_before = rows(api.conn, ["watch_gaps"])
    monkeypatch.setattr(watch_store, "now", lambda: clock.value.isoformat())
    if change == "schedule": assert schedule(api, first["watch_id"]).status_code == 200
    else:
        response = api.client.post(api.url + f"/{first['watch_id']}/" + {"check_now": "checks", "disable": "disable", "rebind": "rebind"}[change],
            json={"expected_state_version": 2}, headers={"Idempotency-Key": change})
        assert response.status_code in (200, 201, 202)
        if change in ("check_now", "rebind"):
            loop(api, api.store.update_run, owner["id"], status="paused")
            turn(api)
    loop(api, api.store.update_run, owner["id"], status="completed")
    before = hashes(api.conn)
    result = loop(api, sched.tick)
    assert not result["queued"] and not sched.pending and hashes(api.conn) == before
    assert rows(api.conn, ["watch_gaps"]) == gap_before


def test_blocked_pending_during_unrelated_held_request_survives_busy_ticks_then_catches_up(api):  # 13s
    first = baseline(api)
    owner_rid = loop(api, api.store.create_research, "SYNTHETIC held owner", "academic", "standard", ["openalex"], "fake", "fake-model", "en", search_workflow="sw")
    loop(api, api.store.freeze_protocol, owner_rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC held"}]})
    owner = loop(api, api.watches.create, owner_rid, {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}, "held-owner")
    entered, release = threading.Event(), threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set(): await asyncio.sleep(.001)
        return httpx.Response(200, json=page(work()))
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    clock = Clock(); clock.value += timedelta(days=3)
    sched = WatchScheduler(api.store, lambda: None, clock)
    try:
        result = loop(api, sched.tick)
        gap = result["recorded"][0]
        assert gap["outcome"] == "catch_up_chosen" and not result["queued"]
        for _ in range(3):
            before = hashes(api.conn); clock.value += timedelta(seconds=60)
            assert not loop(api, sched.tick)["queued"] and hashes(api.conn) == before and len(sched.pending) == 1
    finally:
        release.set(); future.result(5)
    assert api.store.run(owner["run_id"])["status"] == "completed"
    queued = loop(api, sched.tick)["queued"][0]
    assert queued["watch_id"] == first["watch_id"]
    view = read(api, queued)
    assert view["trigger"] == "catch_up" and view["schedule"]["gap_id"] == gap["id"]


def test_scheduled_mixed_units_keep_failed_deferred_success_boundaries(tmp_path, monkeypatch):  # 13u
    queries = [{"provider_id": "openalex", "query_text": f"SYNTHETIC unit {i}"} for i in range(3)]
    with watch_api(tmp_path, queries=queries) as api:
        first = baseline(api)
        old = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])
        sched, clock, _ = scheduler(api, first)
        monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 2)
        api.state.handler = lambda req: httpx.Response(200, json=page(work())) if req.url.params["search.title_and_abstract"].endswith("0") else httpx.Response(400)
        command = due(api, sched, clock, first); turn(api)
        view = read(api, command)
        assert view["state"] == "partial" and set(view["partial_reasons"]) >= {"provider_failed", "budget_deferred"}
        current = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])
        assert current["query:0"]["success_boundary"] == clock.value.isoformat(timespec="milliseconds")
        assert current["query:1"]["success_boundary"] == old["query:1"]["success_boundary"]
        assert current["query:2"]["success_boundary"] == old["query:2"]["success_boundary"]
        assert api.store.run(command["run_id"])["usage"]["provider_requests"] == 2


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


def test_tick_exception_logged_once_per_type_loop_continues_and_stop_or_cancel(api, monkeypatch, caplog):  # 13v
    sched, _, _ = scheduler(api)
    monkeypatch.setattr(policy, "WATCH_TICK_SECONDS", .001)
    calls = []
    async def exercise():
        stop = asyncio.Event()
        def tick():
            calls.append(True)
            if len(calls) <= 2: raise sqlite3.OperationalError("SYNTHETIC repeated")
            if len(calls) == 3: raise OSError("SYNTHETIC second type")
            stop.set()
        sched.tick = tick
        await asyncio.wait_for(sched.run_forever(stop), 2)
        assert stop.is_set()
        stop.clear(); sched.tick = lambda: None
        task = asyncio.create_task(sched.run_forever(stop))
        await asyncio.sleep(.003)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    loop(api, exercise)
    assert len(calls) == 4
    assert len([r for r in caplog.records if r.name.endswith("watch.scheduler") and "tick failed" in r.message]) == 2


def test_long_gap_uses_normal_page_budget_and_can_report_partial_coverage(api):
    first = baseline(api); sched, clock, _ = scheduler(api)
    clock.value += timedelta(days=30)
    api.state.payload = page(work("NEW", date="2099-01-01"), cursor="more")
    command = loop(api, sched.tick)["queued"][0]; turn(api)
    view = read(api, command)
    assert view["trigger"] == "catch_up" and view["gap"]["missed_periods"] == 30
    assert view["state"] == "partial" and "coverage_not_reached" in view["partial_reasons"]
    assert view["caps"]["pages"] == 2 and len(api.sent) == 3 and len(api.watches.items(api.rid)) == 1


def test_abandoned_pending_opening_history_stays_and_latest_five_gaps_are_stored(api):
    first = baseline(api)
    rid = loop(api, api.store.create_research, "SYNTHETIC busy", "academic", "standard", [], "fake", "fake-model", "en")
    owner = loop(api, api.store.create_run, rid, "answer", {}, "busy-owner")
    clock = Clock(); clock.value += timedelta(days=3)
    abandoned = WatchScheduler(api.store, lambda: None, clock)
    original_gap = loop(api, abandoned.tick)["recorded"][0]
    assert abandoned.pending and not api.client.get(api.url).json()[0]["gaps"][0]["catch_up_queued"]
    loop(api, api.store.update_run, owner["id"], status="completed")
    sched = WatchScheduler(api.store, lambda: None, clock)
    for _ in range(6):
        result = loop(api, sched.tick)
        assert len(result["queued"]) == 1
        turn(api)
        clock.value += timedelta(days=2)
    listing = api.client.get(api.url).json()[0]
    assert len(listing["gaps"]) == 5 and all(g["catch_up_queued"] for g in listing["gaps"])
    assert [g["noticed_at"] for g in listing["gaps"]] == sorted([g["noticed_at"] for g in listing["gaps"]], reverse=True)
    saved = dict(api.conn.execute("SELECT * FROM watch_gaps WHERE id=?", (original_gap["id"],)).fetchone())
    assert saved == original_gap and api.conn.execute("SELECT count(*) FROM watch_gaps").fetchone()[0] == 7


def test_continuously_busy_due_times_are_scheduled_not_missed_and_passed_count_is_frozen(api):
    first = baseline(api); sched, clock, _ = scheduler(api, first)
    rid = loop(api, api.store.create_research, "SYNTHETIC long owner run", "academic", "standard", [], "fake", "fake-model", "en")
    owner = loop(api, api.store.create_run, rid, "answer", {}, "long-owner")
    due_at = api.watches.watch(api.rid, first["watch_id"])["next_due_at"]
    clock.value += timedelta(seconds=1)
    async def observed():
        # No suspension: each tick is at most WATCH_GAP_SECONDS from the previous one.
        for _ in range(577):
            assert not sched.tick()["queued"]
            clock.value += timedelta(seconds=300)
    loop(api, observed)
    assert not api.watches.gaps(first["watch_id"])
    assert api.watches.watch(api.rid, first["watch_id"])["next_due_at"] == due_at
    loop(api, api.store.update_run, owner["id"], status="completed")
    command = loop(api, sched.tick)["queued"][0]
    view = read(api, command)
    assert view["trigger"] == "scheduled" and view["period_start"] == due_at
    assert view["schedule"]["due_times_passed"] == 3 and view["gap"] is None

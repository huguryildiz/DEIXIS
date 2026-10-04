"""Scheduler ownership and shutdown on temporary application libraries."""

import asyncio
from collections import defaultdict
from itertools import count

import pytest
from deixis.workflow.watch.scheduler import WatchScheduler
from deixis.workflow.worker import Worker
from deixis.workflow.flow import ResearchFlow
from tests.watch_helpers import watch_offline, watch_api
from tests.watch.test_watch_scheduler import Clock, loop


def instrument(monkeypatch):
    clocks, events, sequence = {}, defaultdict(list), count()
    def record(instance, event):
        events[instance].append((next(sequence), event))
    original_init, original_run = WatchScheduler.__init__, WatchScheduler.run_forever
    recover, cancel, tick = Worker.recover, Worker.cancel_legacy_discovery, WatchScheduler.tick
    def init(self, store, wake, **kwargs):
        clocks[self] = Clock()
        original_init(self, store, wake, clocks[self])
    def recovery(self):
        record(self, "recover"); return recover(self)
    def legacy(self):
        record(self, "cancel_legacy"); return cancel(self)
    def observed_tick(self):
        record(self, "tick"); return tick(self)
    async def run(self, stop):
        try: await original_run(self, stop)
        finally: record(self, "scheduler_stopped")
    monkeypatch.setattr(WatchScheduler, "__init__", init)
    monkeypatch.setattr(WatchScheduler, "run_forever", run)
    monkeypatch.setattr(WatchScheduler, "tick", observed_tick)
    monkeypatch.setattr(Worker, "recover", recovery)
    monkeypatch.setattr(Worker, "cancel_legacy_discovery", legacy)
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
        assert observed[:4] == ["recover", "cancel_legacy", "queue_person_readings", "tick"]
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
        assert app_events(api, events)[:4] == ["recover", "cancel_legacy", "queue_person_readings", "tick"]
    observed = app_events(api, events)
    assert observed.index("scheduler_stopped") < observed.index("worker_released")
    assert observed.index("scheduler_stopped") < observed.index("worker_stopped")


def test_startup_person_readings_before_first_tick_ignores_other_app_instances(tmp_path, monkeypatch):
    clocks, events = instrument(monkeypatch)
    with watch_api(tmp_path / "other") as other:
        foreign = WatchScheduler(other.store, lambda: None)
        loop(other, foreign.tick)
        with watch_api(tmp_path / "owner", start_worker=True) as api:
            loop(api, asyncio.sleep, .01)
            assert clocks[foreign].calls == clocks[api.app.state.watch_scheduler].calls == 1
            assert [name for _, name in events[foreign]] == ["tick"]
            assert app_events(api, events)[:4] == ["recover", "cancel_legacy", "queue_person_readings", "tick"]

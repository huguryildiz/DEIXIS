"""Scheduler ownership and shutdown on temporary application libraries."""

import asyncio
import concurrent.futures
import sqlite3
from collections import defaultdict
from itertools import count

import pytest
from deixis.workflow.watch_scheduler import WatchScheduler
from deixis.workflow.worker import Worker
from deixis.workflow.flow import ResearchFlow
from tests.watch.watch_helpers import watch_offline, watch_api
from tests.watch.test_watch_scheduler import Clock, loop


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


def test_startup_person_readings_before_first_tick_ignores_other_app_instances(tmp_path, monkeypatch):
    clocks, events = instrument(monkeypatch)
    with watch_api(tmp_path / "other") as other:
        foreign = WatchScheduler(other.store, lambda: None)
        loop(other, foreign.tick)
        with watch_api(tmp_path / "owner", start_worker=True) as api:
            loop(api, asyncio.sleep, .01)
            assert clocks[foreign].calls == clocks[api.app.state.watch_scheduler].calls == 1
            assert [name for _, name in events[foreign]] == ["tick"]
            assert app_events(api, events)[:3] == ["recover", "queue_person_readings", "tick"]



def shutdown_spies(monkeypatch, fail=()):
    # Records the shutdown order; a step named in `fail` raises after being recorded.
    from deixis.workflow.equations import EquationService
    from tests.support.fakes import FakeAdapter
    order, conns = [], []
    stop, close, release = EquationService.stop, FakeAdapter.close, Worker.release
    async def stopped(self):
        order.append("equations_stopped")
        if "equations" in fail:
            raise OSError("SYNTHETIC equation worker would not stop")
        return await stop(self)
    async def closed(self):
        order.append("adapter_closed"); return await close(self)
    def released(self):
        try:
            conns[0].execute("SELECT 1")
            order.append("worker_released_with_library_open")
        except sqlite3.ProgrammingError:
            order.append("worker_released")
        return release(self)
    monkeypatch.setattr(EquationService, "stop", stopped)
    monkeypatch.setattr(FakeAdapter, "close", closed)
    monkeypatch.setattr(Worker, "release", released)
    return order, conns, release


def test_shutdown_stops_writers_and_closes_library_before_release(tmp_path, monkeypatch):
    # A second instance takes ownership on release, so the old one must have stopped writing by then.
    order, conns, _ = shutdown_spies(monkeypatch)
    with watch_api(tmp_path, start_worker=True) as api:
        assert api.app.state.owner
        conns.append(api.conn)
    assert order == ["equations_stopped", "adapter_closed", "worker_released"]


def test_failed_shutdown_step_runs_the_rest_and_keeps_ownership(tmp_path, monkeypatch):
    order, conns, release = shutdown_spies(monkeypatch, fail=("equations",))
    with pytest.raises(RuntimeError, match="ownership kept.*equations"):
        with watch_api(tmp_path, start_worker=True) as api:
            conns.append(api.conn)
            worker = api.app.state.worker
    assert order == ["equations_stopped", "adapter_closed"]
    with pytest.raises(sqlite3.ProgrammingError):
        api.conn.execute("SELECT 1")
    # The lock is still held: another instance on the same data directory cannot take over.
    import fcntl, os
    assert worker._fd is not None
    probe = os.open(worker.lock_path, os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(probe)
        release(worker)


def test_cancelled_shutdown_step_still_stops_writers_closes_library_and_keeps_ownership(tmp_path, monkeypatch):
    order, conns, release = shutdown_spies(monkeypatch)
    async def cancelled_scheduler(self, stop):
        await stop.wait()
        raise asyncio.CancelledError("SYNTHETIC scheduler cancelled during shutdown")
    monkeypatch.setattr(WatchScheduler, "run_forever", cancelled_scheduler)
    with pytest.raises(BaseException) as raised:
        with watch_api(tmp_path, start_worker=True) as api:
            conns.append(api.conn)
            worker = api.app.state.worker
    # The cancellation is raised again at the end; the test client's portal hands it over as concurrent's own.
    assert isinstance(raised.value, (asyncio.CancelledError, concurrent.futures.CancelledError))
    assert order == ["equations_stopped", "adapter_closed"]
    with pytest.raises(sqlite3.ProgrammingError):
        api.conn.execute("SELECT 1")
    assert worker._fd is not None
    release(worker)


def test_shutdown_cancelled_while_worker_drains_finishes_cleanup_and_keeps_ownership(tmp_path, monkeypatch):
    # Shutdown itself is cancelled while it waits for the worker: the worker still drains, every later step runs,
    # ownership is kept and the cancellation is raised at the end.
    order, conns, release = shutdown_spies(monkeypatch)
    run_forever, stop_worker = Worker.run_forever, Worker.stop
    async def slow_drain(self):
        await run_forever(self)
        await asyncio.sleep(.05)
        order.append("worker_drained")
    async def stop_then_cancel_shutdown(self):
        await stop_worker(self)
        asyncio.get_running_loop().call_later(.01, asyncio.current_task().cancel)
    monkeypatch.setattr(Worker, "run_forever", slow_drain)
    monkeypatch.setattr(Worker, "stop", stop_then_cancel_shutdown)
    with pytest.raises(BaseException) as raised:
        with watch_api(tmp_path, start_worker=True) as api:
            conns.append(api.conn)
            worker = api.app.state.worker
    assert isinstance(raised.value, (asyncio.CancelledError, concurrent.futures.CancelledError))
    assert order == ["worker_drained", "equations_stopped", "adapter_closed"]
    with pytest.raises(sqlite3.ProgrammingError):
        api.conn.execute("SELECT 1")
    assert worker._fd is not None
    release(worker)


def test_shutdown_cancelled_while_a_failing_worker_drains_still_raises_the_cancellation(tmp_path, monkeypatch):
    # The worker fails after shutdown was cancelled during its drain: the cancellation still wins, the rest still runs.
    order, conns, release = shutdown_spies(monkeypatch)
    run_forever, stop_worker = Worker.run_forever, Worker.stop
    async def failing_drain(self):
        await run_forever(self)
        await asyncio.sleep(.05)
        raise RuntimeError("SYNTHETIC worker failure")
    async def stop_then_cancel_shutdown(self):
        await stop_worker(self)
        asyncio.get_running_loop().call_later(.01, asyncio.current_task().cancel)
    monkeypatch.setattr(Worker, "run_forever", failing_drain)
    monkeypatch.setattr(Worker, "stop", stop_then_cancel_shutdown)
    with pytest.raises(BaseException) as raised:
        with watch_api(tmp_path, start_worker=True) as api:
            conns.append(api.conn)
            worker = api.app.state.worker
    assert isinstance(raised.value, (asyncio.CancelledError, concurrent.futures.CancelledError))
    assert order == ["equations_stopped", "adapter_closed"]
    with pytest.raises(sqlite3.ProgrammingError):
        api.conn.execute("SELECT 1")
    assert worker._fd is not None
    release(worker)

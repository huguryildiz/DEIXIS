"""D250 active-time accounting with isolated libraries, a fake clock and scripted models."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import canonical
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.storage import db
from deixis.workflow import fast_path, small_batch
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from fakes import FakeAdapter, valid_response
from test_abstract_flow import ON_TOPIC
from test_fetch_overlap_flow import discover, wait
from test_fulltext_flow import Transport, work
from test_small_batch_flow import client_of


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 10, 9, tzinfo=timezone.utc)
        self.waiters = []
        self.store = None

    def now(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)
        for deadline, future in self.waiters:
            if deadline <= self.current and not future.done():
                future.set_result(None)
        self.waiters = [(d, f) for d, f in self.waiters if not f.done()]

    async def sleep(self, seconds):
        if self.store:
            assert not self.store.conn.in_transaction
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.current + timedelta(seconds=seconds), future))
        await future


@pytest.fixture(autouse=True)
def historical_read_policy(monkeypatch, request):
    """Keep slice 1/4 regressions on their already-frozen policy, without answer enforcement. The tests that run an
    answer use the current policy: since the clean start (slice 3b) an answer is written on the fast path only."""
    if request.node.originalname in ("test_02_policy_freezes_with_run_and_canonical_hash",
                                     "test_end_to_end_sw_discovery_answer_with_fake_clock",
                                     "test_rerun_answer_flow_save_paths"):
        return
    freeze = fast_path.freeze_budget
    def historical(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        policy["enforced_stages"] = ["read"]
        for key in ("approval_mode", "auto_answer", "policy_hash"):
            policy.pop(key, None)
        return policy | {"policy_hash": canonical.sha256_hex(policy)}
    monkeypatch.setattr(fast_path, "freeze_budget", historical)


@pytest.fixture
def library(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research("SYNTHETIC queue delay", "academic", "quick", ["openalex"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    yield SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))
    conn.close()


def stage(lib, name):
    return dict(lib.conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? AND stage = ?",
                                 (lib.run["id"], name)).fetchone())


def intervals(lib, name=None, run=None):
    return [dict(r) for r in lib.conn.execute("SELECT * FROM fast_path_intervals WHERE run_id = ? ORDER BY rowid",
                                             ((run or lib.run)["id"],)) if name is None or r["stage"] == name]


def finish(lib, name, seconds):
    fast_path.enter_stage(lib.store, lib.run, name)
    lib.clock.advance(seconds)
    fast_path.close_stage(lib.store, lib.run["id"], name)


def answer_run(lib):
    lib.store.update_run(lib.run["id"], status="completed")
    budget = small_batch.answer_budget(lib.store, lib.rid, 1, TEST_EFFORT_BUDGETS["quick"].__dict__)
    budget = fast_path.answer_budget(lib.store, lib.rid, 1, budget)
    run = lib.store.create_run(lib.rid, "answer", budget, None)
    lib.store.update_run(run["id"], status="running")
    return lib.store.run(run["id"])


def save(lib, run, outcome):
    draft = {"title": "SYNTHETIC answer", "claims": []} if outcome == "structurally_valid" else None
    return lib.store.save_answer(lib.rid, run["id"], None, None, 1, outcome, draft, {"ok": outcome != "unverified_draft"})


def app_for(tmp_path, clock=None, adapter=None):
    return create_app(
        Settings(data_dir=tmp_path, port=8877, fulltext_fetch="off", fulltext_adjudication="off",
                 search_query="code"),
        adapters={"fake": adapter or FakeAdapter(valid_response)},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(Transport([work(1, title=ON_TOPIC)]))),
        extra_hosts=("testserver",), trusted_clients=("testclient",), clock=clock)


@pytest.mark.parametrize("effort,bases,n,k,cap,seeds,back,forward", [
    ("quick", (30, 30, 30, 60, 30), 25, 10, 450, 10, 2, 2),
])
def test_02_policy_freezes_with_run_and_canonical_hash(tmp_path, effort, bases, n, k, cap, seeds, back, forward):
    clock = FakeClock()
    app = app_for(tmp_path, clock)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort)
        assert run["status"] == "completed", run
        policy = run["budget"]["fast_path"]
        assert tuple(policy["stage_base_ms"].get(s) for s in fast_path.STAGES) == tuple(v * 1000 for v in bases)
        assert (policy["N"], policy["K"], policy["keyword_record_cap"], policy["chain_seeds"],
                policy["backward_requests"], policy["forward_requests"]) == (n, k, cap, seeds, back, forward)
        assert policy["total_ms"] == sum(bases) * 1000
        assert policy["mode"] == ("deep" if effort == "detailed" else effort)
        assert policy["policy_hash"] == canonical.sha256_hex({k: v for k, v in policy.items() if k != "policy_hash"})
        assert policy["enforced_stages"] == ["search", "ranking", "read", "answer"]
        assert policy["enforcement"] == policy["enforced_stages"] and policy["runner_version"] == 2
        assert policy["approval_mode"] == "unattended" and policy["auto_answer"] is True
        ledger = app.state.store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (run_id,)).fetchone()
        assert (ledger["research_id"], ledger["scope_revision"], ledger["started_at"], ledger["policy_hash"]) == (
            rid, 1, run["created_at"], policy["policy_hash"])


def test_04_unused_time_carries_forward(library):
    finish(library, "plan", 12)
    fast_path.enter_stage(library.store, library.run, "search")
    assert (stage(library, "search")["balance_before_ms"], stage(library, "search")["alloc_ms"]) == (18000, 48000)


def test_07_crash_charges_last_checkpoint_and_excludes_downtime(library, tmp_path):
    lib = library
    interval_id = fast_path.enter_stage(lib.store, lib.run, "search")
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, interval_id)
    lib.clock.advance(3)
    lib.clock.advance(1000)
    Worker(lib.store, None, tmp_path / "lock").recover()
    assert stage(lib, "search")["used_ms"] == 5000
    assert intervals(lib, "search")[0]["close_reason"] == "recovered"
    assert lib.store.run(lib.run["id"])["status"] == "paused"


@pytest.mark.parametrize("name", ["read"])
@pytest.mark.parametrize("crash", [True])
def test_15_resume_passes_done_stages_without_new_intervals(library, tmp_path, name, crash):
    lib = library
    for earlier in fast_path.STAGES[:fast_path.STAGES.index(name)]:
        finish(lib, earlier, 1)
    iid = fast_path.enter_stage(lib.store, lib.run, name)
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, iid)
    if crash:
        Worker(lib.store, None, tmp_path / "lock").recover()
    else:
        lib.store.update_run(lib.run["id"], status="paused")
    lib.store.update_run(lib.run["id"], status="running")
    for earlier in fast_path.STAGES[:fast_path.STAGES.index(name)]:
        assert fast_path.enter_stage(lib.store, lib.run, earlier) is None
    fast_path.enter_stage(lib.store, lib.run, name)
    assert len(intervals(lib, "plan")) == len(intervals(lib, "search")) == 1
    assert len(intervals(lib, name)) == 2


@pytest.mark.parametrize("enforced", [None])
@pytest.mark.parametrize("name", ["search"])
def test_deadlines_use_only_frozen_enforced_stages(library, enforced, name):
    lib = library
    policy = lib.run["budget"]["fast_path"]
    if enforced is None:
        policy.pop("enforced_stages")
    else:
        policy["enforced_stages"] = enforced
    fast_path.enter_stage(lib.store, lib.run, name)
    applies = enforced is not None and name in enforced
    assert fast_path.enforces(lib.run["budget"], name) is applies
    assert (fast_path.stage_deadline(lib.store, lib.run, name) is not None) is applies
    lib.clock.advance(1000)
    assert fast_path.past_deadline(lib.store, lib.run, name) is applies


def test_end_to_end_sw_discovery_answer_with_fake_clock(tmp_path, monkeypatch):
    from deixis.workflow import read as fast_read, search as fast_search
    clock = FakeClock()
    for method in ("_vocabulary", "_ranking", "_generate_answer", "_review"):
        original = getattr(ResearchFlow, method)
        async def timed(self, *args, _original=original, **kwargs):
            clock.advance(2)
            return await _original(self, *args, **kwargs)
        monkeypatch.setattr(ResearchFlow, method, timed)
    execute = fast_read.execute
    async def read(flow, *args, **kwargs):
        clock.advance(3)
        return await execute(flow, *args, **kwargs)
    monkeypatch.setattr(fast_read, "execute", read)
    search = fast_search.execute
    async def bounded_search(*args, **kwargs):
        clock.advance(2)
        return await search(*args, **kwargs)
    monkeypatch.setattr(fast_search, "execute", bounded_search)
    app = app_for(tmp_path, clock)
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed", discovery
        # The unattended policy starts the answer itself when the discovery completes.
        answer = app.state.store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'answer'",
                                              (rid,)).fetchone()["id"]
        _, run = wait(client, rid, answer)
        assert run["status"] == "completed", run
        assert app.state.worker.flow.store.clock is clock
        assert app.state.worker.flow.deps.clock is clock
        stages = app.state.store.conn.execute("SELECT stage, used_ms, status FROM fast_path_stages WHERE seq > 0 ORDER BY seq").fetchall()
        assert [tuple(row) for row in stages] == [("plan", 2000, "done"), ("search", 2000, "done"),
                                                 ("ranking", 2000, "done"), ("read", 3000, "done"), ("answer", 2000, "done")]
        rows = app.state.store.conn.execute("SELECT stage, close_reason FROM fast_path_intervals ORDER BY rowid").fetchall()
        assert [tuple(row) for row in rows] == [(s, "stage_done") for s in ("plan", "search", "ranking", "read", "answer")]
        assert run["budget"]["inspection"]["list_run_id"] == discovery_id
        assert run["fast_path"]["used_ms"] == 11000
        assert run["fast_path"]["latency_ms"] == 11000  # no idle time: the answer starts as the discovery ends
        assert not app.state.worker.flow._clock_tasks

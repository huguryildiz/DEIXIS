"""D250 active-time accounting with isolated libraries, a fake clock and scripted models."""

import asyncio
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from deixis.api.app import CSRF_COOKIE, CSRF_HEADER, create_app
from deixis.config import Settings, load_settings
from deixis.domain import canonical
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.storage import db
from deixis.workflow import fast_path, small_batch
from deixis.workflow.flow import ResearchFlow, RunStopped
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


def app_for(tmp_path, clock=None, flag="off", adapter=None):
    return create_app(
        Settings(data_dir=tmp_path, port=8877, fast_path=flag, fulltext_fetch="off", fulltext_adjudication="off",
                 search_query="code", protocol_approval="as_proposed"),
        adapters={"fake": adapter or FakeAdapter(valid_response)},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(Transport([work(1, title=ON_TOPIC)]))),
        extra_hosts=("testserver",), trusted_clients=("testclient",), clock=clock)


def test_01_flag_off_budgets_are_byte_identical_and_no_clock_rows(tmp_path, monkeypatch):
    from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS, ADVICE_CALLS, CRITERION_CALLS, SUGGESTION_CALLS
    from deixis.workflow import abstract_stage

    app = app_for(tmp_path)
    with client_of(app) as client:
        rid, discovery_id, _, run = discover(client)
        base = TEST_EFFORT_BUDGETS["quick"].__dict__
        extra = CRITERION_CALLS + SUGGESTION_CALLS + ADVICE_CALLS + abstract_stage.model_calls(
            ABSTRACT_READ_LIMIT["quick"], ABSTRACT_BATCH, ABSTRACT_RUNS)
        expected = small_batch.freeze_budget(base | {"max_model_calls": base["max_model_calls"] + extra,
                                                      "citation_chaining": "off"}, "quick", "off")
        assert app.state.store.conn.execute("SELECT budget_json FROM runs WHERE id = ?", (discovery_id,)).fetchone()[0] == db.dumps(expected)
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, settled = wait(client, rid, answer["id"])
        expected_answer = small_batch.answer_budget(app.state.store, rid, 1, base)
        assert db.dumps(settled["budget"]) == db.dumps(expected_answer)
        assert "fast_path" not in run and "fast_path" not in settled
        for table in ("ledgers", "stages", "intervals"):
            assert app.state.store.conn.execute(f"SELECT COUNT(*) FROM fast_path_{table}").fetchone()[0] == 0


@pytest.mark.parametrize("effort,bases,n,k,cap,seeds,back,forward", [
    ("quick", (30, 30, 30, 60, 30), 25, 10, 450, 10, 2, 2),
    ("standard", (30, 45, 60, 120, 45), 50, 20, 1000, 20, 4, 8),
    ("detailed", (45, 90, 120, 270, 75), 100, 40, 2000, 30, 8, 16),
])
def test_02_policy_freezes_with_run_and_canonical_hash(tmp_path, effort, bases, n, k, cap, seeds, back, forward):
    clock = FakeClock()
    app = app_for(tmp_path, clock, "on")
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
        assert policy["enforced_stages"] == ["search", "ranking", "read"] and policy["runner_version"] == 2
        ledger = app.state.store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (run_id,)).fetchone()
        assert (ledger["research_id"], ledger["scope_revision"], ledger["started_at"], ledger["policy_hash"]) == (
            rid, 1, run["created_at"], policy["policy_hash"])


def test_03_allocation_is_fixed_at_stage_start(library):
    lib = library
    finish(lib, "plan", 10)
    fast_path.enter_stage(lib.store, lib.run, "search")
    assert stage(lib, "search")["alloc_ms"] == 50000
    lib.conn.execute("UPDATE fast_path_stages SET used_ms = 90000 WHERE stage = 'plan'")
    lib.store.update_run(lib.run["id"], status="paused")
    lib.store.update_run(lib.run["id"], status="running")
    fast_path.enter_stage(lib.store, lib.run, "search")
    assert stage(lib, "search")["alloc_ms"] == 50000


def test_04_unused_time_carries_forward(library):
    finish(library, "plan", 12)
    fast_path.enter_stage(library.store, library.run, "search")
    assert (stage(library, "search")["balance_before_ms"], stage(library, "search")["alloc_ms"]) == (18000, 48000)


def test_05_floor_keeps_and_accumulates_debt(library):
    lib = library
    finish(lib, "plan", 100)
    fast_path.enter_stage(lib.store, lib.run, "search")
    assert stage(lib, "search")["alloc_ms"] == 7500
    assert stage(lib, "search")["balance_before_ms"] == -70000
    lib.clock.advance(40)
    fast_path.close_stage(lib.store, lib.run["id"], "search")
    finish(lib, "ranking", 40)
    finish(lib, "read", 70)
    run = answer_run(lib)
    fast_path.enter_stage(lib.store, run, "answer")
    assert stage(lib, "answer")["balance_before_ms"] == -100000
    assert stage(lib, "answer")["alloc_ms"] == 7500
    lib.clock.advance(40)
    save(lib, run, "no_evidence")
    assert fast_path.view(lib.store, run)["balance_ms"] == -110000


def test_06_skipped_stages_carry_their_bases(library):
    lib = library
    fast_path.enter_stage(lib.store, lib.run, "ranking")
    assert stage(lib, "plan")["status"] == stage(lib, "search")["status"] == "skipped"
    assert stage(lib, "plan")["used_ms"] == 0
    assert stage(lib, "ranking")["alloc_ms"] == 90000
    with pytest.raises(AssertionError, match="previous stage"):
        fast_path.enter_stage(lib.store, lib.run, "read")


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


def test_08_resume_after_overrun_keeps_allocation_and_attempt(library, tmp_path):
    lib = library
    iid = fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(100)
    fast_path.checkpoint(lib.store, iid)
    Worker(lib.store, None, tmp_path / "lock").recover()
    lib.clock.advance(100)
    lib.store.update_run(lib.run["id"], status="running")
    fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(2)
    fast_path.close_stage(lib.store, lib.run["id"], "plan")
    assert stage(lib, "plan")["alloc_ms"] == 30000
    assert [i["attempt"] for i in intervals(lib, "plan")] == [1, 2]
    fast_path.enter_stage(lib.store, lib.run, "search")
    assert stage(lib, "search")["balance_before_ms"] == -72000


@pytest.mark.parametrize("reason", ["user_requested", "protocol_approval_needed", "model_connection_not_ready"])
def test_09_graceful_pause_excluded_from_budget_included_in_latency(library, reason):
    lib = library
    fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(4)
    lib.store.update_run(lib.run["id"], status="paused", pause_reason=reason)
    lib.clock.advance(100)
    lib.store.update_run(lib.run["id"], status="running")
    finish(lib, "plan", 6)
    run = answer_run(lib)
    fast_path.enter_stage(lib.store, run, "answer")
    lib.clock.advance(3)
    save(lib, run, "structurally_valid")
    view = fast_path.view(lib.store, run)
    assert view["used_ms"] == 13000 and view["latency_ms"] == 113000
    assert intervals(lib, "plan")[0]["close_reason"] == "paused"


def test_10_pause_requested_is_charged_until_drained(library):
    lib = library
    fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(3)
    lib.store.update_run(lib.run["id"], status="pause_requested")
    assert intervals(lib)[0]["closed_at"] is None
    lib.clock.advance(7)
    lib.store.update_run(lib.run["id"], status="paused")
    assert stage(lib, "plan")["used_ms"] == 10000


def test_11_parallel_steps_charge_stage_wall_time_and_checkpoint_task(library):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock))

    async def execute():
        flow._enter_clock_stage(lib.run, "plan")
        await asyncio.sleep(0)
        lib.clock.advance(5)
        await asyncio.sleep(0)
        assert intervals(lib)[0]["last_checkpoint_at"] == fast_path.timestamp(lib.clock)
        async def arm():
            await lib.clock.sleep(5)
        arms = [asyncio.create_task(arm()), asyncio.create_task(arm())]
        await asyncio.sleep(0)
        lib.clock.advance(5)
        await asyncio.gather(*arms)
        flow._close_clock_stage(lib.run, "plan")
        tasks = [task for _, task in flow._clock_tasks[lib.run["id"]].values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(t.done() for t in tasks)
    asyncio.run(execute())
    assert stage(lib, "plan")["used_ms"] == 10000


def test_12_older_policyless_runs_have_no_accounting(library):
    lib = library
    lib.store.update_run(lib.run["id"], status="completed")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    run = lib.store.create_run(lib.rid, "discovery", budget, None)
    lib.store.update_run(run["id"], status="running")
    assert fast_path.enter_stage(lib.store, run, "plan") is None
    lib.clock.advance(50)
    lib.store.update_run(run["id"], status="completed")
    assert intervals(lib, run=run) == []
    assert lib.conn.execute("SELECT COUNT(*) FROM fast_path_ledgers").fetchone()[0] == 1
    assert fast_path.view(lib.store, run) is None


@pytest.mark.parametrize("outcome", ["structurally_valid", "unverified_draft", "no_evidence"])
def test_13_answer_binds_selected_list_and_publication_requires_validity(library, outcome):
    lib = library
    run = answer_run(lib)
    assert run["budget"]["fast_path"] == {"policy": fast_path.POLICY,
        "policy_hash": lib.run["budget"]["fast_path"]["policy_hash"], "ledger_run_id": lib.run["id"], "role": "first"}
    assert run["budget"]["inspection"]["list_run_id"] == lib.run["id"]
    fast_path.enter_stage(lib.store, run, "answer")
    lib.clock.advance(2)
    aid = save(lib, run, outcome)
    lib.clock.advance(10)
    assert save(lib, run, outcome) == aid
    ledger = lib.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()
    assert ledger["answer_outcome"] == outcome
    assert bool(ledger["answer_published_at"]) is (outcome == "structurally_valid")
    assert stage(lib, "answer")["status"] == "done"
    assert stage(lib, "answer")["used_ms"] == 2000


@pytest.mark.parametrize("populated", [False, True])
def test_14_migration_applies_to_empty_and_existing_library(tmp_path, monkeypatch, populated):
    original = db.MIGRATIONS_DIR
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in original.glob("*.sql"):
        if not path.name.startswith("0073"):
            shutil.copyfile(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "old.sqlite")
    try:
        db.migrate(conn)
        store = Store(conn)
        if populated:
            rid = store.create_research("SYNTHETIC preserved", "academic", "quick", [], "fake", "fake-model", None)
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'schema_migrations'")]
        before = {t: [tuple(row) for row in conn.execute(f"SELECT * FROM {t}")] for t in tables}
        shutil.copyfile(original / "0073_fast_path_clock.sql", migrations / "0073_fast_path_clock.sql")
        assert db.migrate(conn) == [73]
        assert before == {t: [tuple(row) for row in conn.execute(f"SELECT * FROM {t}")] for t in tables}
        if not populated:
            rid = store.create_research("SYNTHETIC new", "academic", "quick", [], "fake", "fake-model", None)
        budget = {"fast_path": fast_path.freeze_budget({}, "quick")}
        run = store.create_run(rid, "discovery", budget, None)
        conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))
        fast_path.enter_stage(store, run, "plan")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fast_path_intervals SELECT 'duplicate', ledger_run_id, run_id, stage, 2, generation,"
                         " rework, started_at, last_checkpoint_at, max_checkpoint_gap_ms, closed_at, close_reason FROM fast_path_intervals")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


@pytest.mark.parametrize("name", ["ranking", "read"])
@pytest.mark.parametrize("crash", [False, True])
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


@pytest.mark.parametrize("stop", ["completed", "paused", "recovered"])
def test_16_rework_generations_survive_interruptions(library, tmp_path, stop):
    lib = library
    for name in fast_path.STAGES[:4]:
        finish(lib, name, 10)
    lib.store.update_run(lib.run["id"], status="completed")
    step = lib.store.step(lib.run["id"], "search:synthetic", "provider_search:openalex")
    lib.store.finish_step(step["id"], "failed")
    lib.store.queue_failed_search_retry(lib.run["id"])
    lib.run = lib.store.run(lib.run["id"])
    lib.store.update_run(lib.run["id"], status="running")
    alloc = stage(lib, "search")["alloc_ms"]
    iid = fast_path.enter_stage(lib.store, lib.run, "search")
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, iid)
    if stop == "recovered":
        Worker(lib.store, None, tmp_path / "lock").recover()
    elif stop == "paused":
        lib.store.update_run(lib.run["id"], status="paused")
    else:
        fast_path.close_stage(lib.store, lib.run["id"], "search")
    if stop != "completed":
        assert stage(lib, "search")["done_generation"] == 0
        lib.store.update_run(lib.run["id"], status="running")
        fast_path.enter_stage(lib.store, lib.run, "search")
        lib.clock.advance(3)
        fast_path.close_stage(lib.store, lib.run["id"], "search")
    assert fast_path.enter_stage(lib.store, lib.run, "search") is None
    rework = 5000 if stop == "completed" else 8000
    assert stage(lib, "search")["used_ms"] == 10000 + rework
    assert stage(lib, "search")["rework_ms"] == rework
    assert stage(lib, "search")["alloc_ms"] == alloc
    assert stage(lib, "search")["done_generation"] == lib.run["budget"]["retry_provider_requests"]
    answer = answer_run(lib)
    fast_path.enter_stage(lib.store, answer, "answer")
    assert stage(lib, "answer")["balance_before_ms"] == 110000 - rework


def test_17_crash_during_review_preserves_publication_and_closed_answer(library, tmp_path):
    lib = library
    run = answer_run(lib)
    fast_path.enter_stage(lib.store, run, "answer")
    lib.clock.advance(4)
    save(lib, run, "structurally_valid")
    before = dict(lib.conn.execute("SELECT * FROM fast_path_ledgers").fetchone())
    lib.clock.advance(100)
    Worker(lib.store, None, tmp_path / "lock").recover()
    assert dict(lib.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()) == before
    assert stage(lib, "answer")["used_ms"] == 4000
    assert fast_path.enter_stage(lib.store, run, "answer") is None


@pytest.mark.parametrize("outcome", ["no_evidence", "unverified_draft", "structurally_valid"])
@pytest.mark.parametrize("stop", [None, "paused", "recovered"])
def test_18_answer_rerun_closes_at_save_and_resumes_only_before_save(library, tmp_path, outcome, stop):
    lib = library
    first = answer_run(lib)
    fast_path.enter_stage(lib.store, first, "answer")
    lib.clock.advance(2)
    save(lib, first, "structurally_valid")
    lib.store.update_run(first["id"], status="completed")
    before = dict(lib.conn.execute("SELECT * FROM fast_path_ledgers").fetchone())
    answer_stage = stage(lib, "answer")
    rerun = answer_run(lib)
    assert rerun["budget"]["fast_path"]["role"] == "rerun"
    iid = fast_path.enter_stage(lib.store, rerun, "answer")
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, iid)
    if stop:
        if stop == "recovered":
            Worker(lib.store, None, tmp_path / "lock").recover()
        else:
            lib.store.update_run(rerun["id"], status="paused")
        lib.clock.advance(100)
        lib.store.update_run(rerun["id"], status="running")
        fast_path.enter_stage(lib.store, rerun, "answer")
        lib.clock.advance(3)
    save(lib, rerun, outcome)
    lib.clock.advance(50)
    lib.store.update_run(rerun["id"], status="paused")
    Worker(lib.store, None, tmp_path / "lock").recover()
    lib.store.update_run(rerun["id"], status="running")
    assert fast_path.enter_stage(lib.store, rerun, "answer") is None
    assert dict(lib.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()) == before
    assert stage(lib, "answer") == answer_stage
    rows = intervals(lib, run=rerun)
    assert rows[-1]["close_reason"] == "stage_done"
    assert len(rows) == (2 if stop else 1)
    assert fast_path.view(lib.store, rerun)["rerun_used_ms"] == (8000 if stop else 5000)


def test_19_double_recover_and_checkpoint_after_close_are_idempotent(library, tmp_path):
    lib = library
    iid = fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, iid)
    worker = Worker(lib.store, None, tmp_path / "lock")
    worker.recover()
    before = intervals(lib)
    lib.clock.advance(100)
    worker.recover()
    fast_path.checkpoint(lib.store, iid)
    assert intervals(lib) == before
    assert stage(lib, "plan")["used_ms"] == 5000
    # Recovery also closes a stray interval belonging to an already paused run.
    lib.store.update_run(lib.run["id"], status="running")
    fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (lib.run["id"],))
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, intervals(lib)[-1]["id"])
    worker.recover()
    assert stage(lib, "plan")["used_ms"] == 10000


@pytest.mark.parametrize("operation", ["open", "close", "queue", "answer"])
def test_20_transaction_failures_roll_back_accounting_with_state(library, operation):
    lib = library
    if operation == "open":
        lib.conn.execute("CREATE TRIGGER fail_clock BEFORE INSERT ON fast_path_intervals BEGIN SELECT RAISE(ABORT, 'SYNTHETIC'); END")
        with pytest.raises(sqlite3.IntegrityError, match="SYNTHETIC"):
            fast_path.enter_stage(lib.store, lib.run, "search")
        assert lib.conn.execute("SELECT COUNT(*) FROM fast_path_stages").fetchone()[0] == 0
    elif operation == "close":
        fast_path.enter_stage(lib.store, lib.run, "plan")
        lib.clock.advance(5)
        lib.conn.execute("CREATE TRIGGER fail_clock BEFORE UPDATE ON fast_path_stages BEGIN SELECT RAISE(ABORT, 'SYNTHETIC'); END")
        with pytest.raises(sqlite3.IntegrityError, match="SYNTHETIC"):
            lib.store.update_run(lib.run["id"], status="paused")
        assert intervals(lib)[0]["closed_at"] is None
        assert lib.store.run(lib.run["id"])["status"] == "running"
    elif operation == "queue":
        lib.store.update_run(lib.run["id"], status="completed")
        lib.conn.execute("CREATE TRIGGER fail_clock BEFORE INSERT ON fast_path_ledgers BEGIN SELECT RAISE(ABORT, 'SYNTHETIC'); END")
        with pytest.raises(sqlite3.IntegrityError, match="SYNTHETIC"):
            lib.store.create_run(lib.rid, "discovery", lib.run["budget"], None)
        assert lib.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    else:
        run = answer_run(lib)
        fast_path.enter_stage(lib.store, run, "answer")
        lib.conn.execute("CREATE TRIGGER fail_clock BEFORE UPDATE ON fast_path_stages BEGIN SELECT RAISE(ABORT, 'SYNTHETIC'); END")
        with pytest.raises(sqlite3.IntegrityError, match="SYNTHETIC"):
            save(lib, run, "structurally_valid")
        assert lib.conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0
        assert lib.conn.execute("SELECT answer_outcome FROM fast_path_ledgers").fetchone()[0] is None
        assert intervals(lib, run=run)[0]["closed_at"] is None


def test_21_chain_activity_overlaps_read_without_double_charging(library):
    lib = library
    fast_path.enter_stage(lib.store, lib.run, "read")
    lib.clock.advance(2)
    fast_path.enter_stage(lib.store, lib.run, "chain")
    lib.clock.advance(3)
    fast_path.close_stage(lib.store, lib.run["id"], "chain")
    lib.clock.advance(5)
    fast_path.close_stage(lib.store, lib.run["id"], "read")
    assert stage(lib, "chain")["seq"] == stage(lib, "chain")["base_ms"] == 0
    assert stage(lib, "chain")["used_ms"] == 3000
    assert fast_path.view(lib.store, lib.run)["used_ms"] == 10000


@pytest.mark.parametrize("enforced", [None, ["read"], ["search", "ranking", "read"]])
@pytest.mark.parametrize("name", ["search", "ranking", "read"])
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
    from deixis.workflow import fast_read, fast_search
    clock = FakeClock()
    for method in ("_vocabulary", "_search_round", "_ranking", "_semantic_ranking", "_review"):
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
    app = app_for(tmp_path, clock, "on")
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed", discovery
        clock.advance(100)
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, run = wait(client, rid, answer["id"])
        assert run["status"] == "completed", run
        assert app.state.worker.flow.store.clock is clock
        assert app.state.worker.flow.deps.clock is clock
        stages = app.state.store.conn.execute("SELECT stage, used_ms, status FROM fast_path_stages WHERE seq > 0 ORDER BY seq").fetchall()
        assert [tuple(row) for row in stages] == [("plan", 2000, "done"), ("search", 2000, "done"),
                                                 ("ranking", 2000, "done"), ("read", 3000, "done"), ("answer", 2000, "done")]
        rows = app.state.store.conn.execute("SELECT stage, close_reason FROM fast_path_intervals ORDER BY rowid").fetchall()
        assert [tuple(row) for row in rows] == [(s, "stage_done") for s in ("plan", "search", "lookups", "ranking", "read", "answer")]
        assert run["budget"]["inspection"]["list_run_id"] == discovery_id
        assert run["fast_path"]["used_ms"] == 11000
        assert run["fast_path"]["latency_ms"] == 111000
        assert not app.state.worker.flow._clock_tasks


def test_setting_default_off_and_invalid_value(monkeypatch):
    monkeypatch.delenv("DEIXIS_FAST_PATH", raising=False)
    assert load_settings().fast_path == "off"
    monkeypatch.setenv("DEIXIS_FAST_PATH", "on")
    assert load_settings().fast_path == "on"
    monkeypatch.setenv("DEIXIS_FAST_PATH", "auto")
    with pytest.raises(ValueError, match="DEIXIS_FAST_PATH"):
        load_settings()


def test_existing_partial_flow_dependencies_keep_store_clock(library):
    flow = ResearchFlow(SimpleNamespace(store=library.store))
    assert flow.store.clock is library.clock


@pytest.mark.parametrize("case,expected", [("empty_evidence", "no_evidence"), ("empty_passages", "no_evidence"),
                                          ("invalid", "unverified_draft"), ("valid", "structurally_valid")])
def test_rerun_all_four_answer_flow_save_paths(tmp_path, monkeypatch, case, expected):
    clock, adapter = FakeClock(), FakeAdapter(valid_response)
    app = app_for(tmp_path, clock, "on", adapter)
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed", discovery
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, first = wait(client, rid, first["id"])
        assert first["fast_path"]["answer_outcome"] == "structurally_valid"
        ledger = dict(app.state.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone())
        if case == "empty_evidence":
            monkeypatch.setattr(ResearchFlow, "_abstract_sources", lambda *args: [])
        elif case == "empty_passages":
            monkeypatch.setattr(ResearchFlow, "_small_batch_answer_passages", lambda *args: [])
        elif case == "invalid":
            adapter.responder = lambda si: "{}" if si["task_type"] == "grounded_answer" else valid_response(si)
        original_save = Store.save_answer
        def at_save(self, *args, **kwargs):
            clock.advance(3)
            return original_save(self, *args, **kwargs)
        monkeypatch.setattr(Store, "save_answer", at_save)
        async def review(self, run, *args, **kwargs):
            assert not self.store.conn.execute("SELECT 1 FROM fast_path_intervals WHERE closed_at IS NULL").fetchone()
            clock.advance(10)
        monkeypatch.setattr(ResearchFlow, "_review", review)
        rerun = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, rerun = wait(client, rid, rerun["id"])
        assert rerun["status"] == "completed", rerun
        assert rerun["budget"]["fast_path"]["role"] == "rerun"
        assert rerun["budget"]["inspection"]["list_run_id"] == discovery_id
        assert app.state.store.conn.execute("SELECT status FROM answers WHERE run_id = ?", (rerun["id"],)).fetchone()[0] == expected
        assert rerun["fast_path"]["rerun_used_ms"] == 3000
        assert dict(app.state.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()) == ledger
        assert app.state.store.conn.execute("SELECT close_reason FROM fast_path_intervals WHERE run_id = ?", (rerun["id"],)).fetchone()[0] == "stage_done"


@pytest.mark.parametrize("mismatch", ["research_id", "scope_revision", "policy_hash", "no_policy"])
def test_answer_binding_fails_closed_without_changing_legacy_budget(library, mismatch):
    lib = library
    budget = {"inspection": {"list_run_id": lib.run["id"]}, "max_model_calls": 6}
    if mismatch == "no_policy":
        lib.conn.execute("UPDATE runs SET budget_json = '{}' WHERE id = ?", (lib.run["id"],))
    elif mismatch == "research_id":
        other = lib.store.create_research("SYNTHETIC other", "academic", "quick", [], "fake", None, None)
        lib.conn.execute("UPDATE fast_path_ledgers SET research_id = ?", (other,))
    else:
        lib.conn.execute(f"UPDATE fast_path_ledgers SET {mismatch} = ?", (2 if mismatch == "scope_revision" else "other",))
    assert fast_path.answer_budget(lib.store, lib.rid, 1, budget) is budget


@pytest.mark.parametrize("status", ["failed", "cancelled", "completed", "queued"])
def test_every_exit_from_active_run_closes_intervals(library, status):
    lib = library
    fast_path.enter_stage(lib.store, lib.run, "read")
    fast_path.enter_stage(lib.store, lib.run, "chain")
    lib.clock.advance(7)
    lib.store.update_run(lib.run["id"], status=status)
    assert all(row["closed_at"] == fast_path.timestamp(lib.clock) and row["close_reason"] == "stopped"
               for row in intervals(lib))
    assert stage(lib, "read")["used_ms"] == stage(lib, "chain")["used_ms"] == 7000


def test_open_rework_is_live_and_checkpoint_delay_is_visible(library):
    lib = library
    finish(lib, "search", 10)
    lib.run["budget"]["retry_provider_requests"] = 4
    iid = fast_path.enter_stage(lib.store, lib.run, "search")
    lib.clock.advance(9)
    fast_path.checkpoint(lib.store, iid)
    view = fast_path.view(lib.store, lib.run)
    row = next(s for s in view["stages"] if s["stage"] == "search")
    assert row["live"] and row["status"] == "done"
    assert row["used_ms"] == 19000 and row["rework_ms"] == 9000
    assert view["max_checkpoint_gap_ms"] == 10000


@pytest.mark.parametrize("status", ["cancelled", "paused"])
@pytest.mark.parametrize("next_stage", ["plan", "ranking", "read"])
def test_stop_between_stages_does_not_open_next_interval(library, tmp_path, monkeypatch, status, next_stage):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    app = app_for(tmp_path / "api", lib.clock, "on")
    app.state.store = lib.store
    app.state.worker = SimpleNamespace(flow=SimpleNamespace(queue_person_reading=lambda rid: None),
                                       wake=lambda: None, current_run_id=None)

    async def execute(run_id):
        if next_stage != "plan":
            flow._enter_clock_stage(lib.run, "plan")
            flow._close_clock_stage(lib.run, "plan")
        if status == "cancelled":
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("testclient", 123)),
                                         base_url="http://testserver", cookies={CSRF_COOKIE: "synthetic"},
                                         headers={CSRF_HEADER: "synthetic"}) as client:
                response = await client.post(f"/api/runs/{run_id}/cancel")
            assert response.status_code == 200, response.text
            assert response.json()["status"] == status
        else:
            lib.store.update_run(run_id, status=status)
        flow._enter_clock_stage(lib.run, next_stage)
        assert not intervals(lib, next_stage)
        with pytest.raises(RunStopped):
            flow._checkpoint(run_id)

    monkeypatch.setattr(flow, "_execute_run", execute)
    asyncio.run(flow.execute(lib.run["id"]))
    assert not lib.conn.execute("SELECT 1 FROM fast_path_intervals WHERE closed_at IS NULL").fetchone()
    assert not flow._clock_tasks


@pytest.mark.parametrize("status", ["paused", "cancelled", "failed", "completed"])
def test_execute_finally_closes_stray_intervals(library, monkeypatch, status):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))

    async def execute(run_id):
        flow._enter_clock_stage(lib.run, "plan")
        lib.clock.advance(3)
        # Simulate a leftover interval from a status writer that bypassed update_run.
        lib.conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    monkeypatch.setattr(flow, "_execute_run", execute)
    asyncio.run(flow.execute(lib.run["id"]))
    row = intervals(lib)[0]
    assert row["close_reason"] == ("paused" if status == "paused" else "stopped")
    assert row["closed_at"] == fast_path.timestamp(lib.clock)
    assert stage(lib, "plan")["used_ms"] == 3000
    assert not flow._clock_tasks


@pytest.mark.parametrize("body_fails", [False, True])
def test_checkpoint_cleanup_logs_error_without_replacing_run_error(library, monkeypatch, caplog, body_fails):
    flow = ResearchFlow(SimpleNamespace(store=library.store))

    async def failed_checkpoint(interval_id):
        raise RuntimeError("SYNTHETIC checkpoint failure")

    async def execute(run_id):
        flow._enter_clock_stage(library.run, "plan")
        await asyncio.sleep(0)
        library.store.update_run(run_id, status="failed" if body_fails else "completed")
        if body_fails:
            raise ValueError("SYNTHETIC run failure")

    monkeypatch.setattr(flow, "_clock_checkpoint", failed_checkpoint)
    monkeypatch.setattr(flow, "_execute_run", execute)
    if body_fails:
        with pytest.raises(ValueError, match="SYNTHETIC run failure"):
            asyncio.run(flow.execute(library.run["id"]))
    else:
        asyncio.run(flow.execute(library.run["id"]))
    assert "SYNTHETIC checkpoint failure" in caplog.text
    assert not flow._clock_tasks

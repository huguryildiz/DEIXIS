"""The evidence a run gathers before it answers (`evidence_minimum_v1`), with the handover long past.

Each run here is queued as if its question had been submitted ten minutes earlier, which is a plan stage that overran
past the handover moment. Records and questions are SYNTHETIC and OpenAlex and the model are fakes: passing shows the
workflow's order and cutoffs, not that the reads are right or the targets met.
"""

import asyncio
import time
from datetime import datetime, timedelta

from deixis.workflow.run import fast_path
from fakes import FakeAdapter, valid_response
from test_abstract_flow import ON_ABSTRACT, ON_TOPIC, Pool, app_for, client_of, codes_of, discover, wait, work
from windows_env import WAIT_FACTOR


def late_ledger(monkeypatch):
    """Every discovery ledger starts ten minutes before its run: the handover has passed before anything searches."""
    create = fast_path.create_run

    def earlier(store, run):
        create(store, run)
        if run["kind"] == "discovery" and fast_path.enabled(run["budget"]):
            started = datetime.fromisoformat(run["created_at"]) - timedelta(minutes=10)
            store.conn.execute("UPDATE fast_path_ledgers SET started_at = ? WHERE ledger_run_id = ?",
                               (started.isoformat(timespec="milliseconds"), run["id"]))
    monkeypatch.setattr(fast_path, "create_run", earlier)


def before_the_rule(monkeypatch):
    """New runs frozen as a run queued before the rule: their policy names no `evidence_minimum`."""
    freeze = fast_path.freeze_budget

    def older(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        policy.pop("evidence_minimum")
        return policy
    monkeypatch.setattr(fast_path, "freeze_budget", older)


class Adapter(FakeAdapter):
    """The fake model; an abstract screening call hangs while `hang` says so for its key."""

    def __init__(self, hang=lambda si: False):
        super().__init__(valid_response)
        self.hang = hang

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
        from fakes import parse_step_input
        si = parse_step_input(message)
        if si["task_type"] == "abstract_screening" and self.hang(si):
            self.calls.append(si)
            await asyncio.sleep(3600)
        return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)


POOL = [work(1, ON_TOPIC, ON_ABSTRACT), work(2)]  # W1 passes on its title; W2 needs the model's read


def steps(store, run_id, prefix):
    return [dict(row) for row in store.conn.execute(
        "SELECT operation_key, status, error_code, started_at, finished_at FROM run_steps WHERE run_id = ?"
        " AND operation_key LIKE ? ORDER BY rowid", (run_id, prefix + "%"))]


def answer_started(store, rid):
    """When the answer stage opened for this research's discovery ledger."""
    row = store.conn.execute("SELECT MIN(i.started_at) FROM fast_path_intervals i JOIN runs r ON r.id = i.run_id"
                             " WHERE r.research_id = ? AND i.stage = 'answer'", (rid,)).fetchone()
    return row[0]


def late_run(tmp_path, monkeypatch, adapter=None, older=False):
    late_ledger(monkeypatch)
    if older:
        before_the_rule(monkeypatch)
    app = app_for(tmp_path, monkeypatch, Pool(list(POOL)), adapter=adapter or Adapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        # The answer the discovery queued, waited for so its stage is recorded.
        for answer in [r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["kind"] == "answer"]:
            wait(client, rid, answer["id"])
    finally:
        client.__exit__(None, None, None)
    # The app's own connection is closed with it, so the library is opened again to read what the run stored.
    from deixis.storage import db
    from deixis.workflow.run.store import Store
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    db.migrate(conn)
    return SimpleRun(app, Store(conn), rid, run_id, run)


class SimpleRun:
    def __init__(self, app, store, rid, run_id, run):
        self.app, self.store, self.rid, self.run_id, self.run = app, store, rid, run_id, run


def test_with_the_handover_past_the_keyword_query_is_sent_and_the_top_n_is_read_before_the_answer(tmp_path,
                                                                                                    monkeypatch):
    late = late_run(tmp_path, monkeypatch)
    store, run_id = late.store, late.run_id
    assert late.run["status"] == "completed", late.run
    keyword = steps(store, run_id, "search:0")
    assert keyword and keyword[0]["status"] == "succeeded"
    assert store.conn.execute("SELECT COUNT(*) FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
                              " WHERE s.run_id = ? AND s.operation_key LIKE 'search:0%'", (run_id,)).fetchone()[0]
    reads = steps(store, run_id, "small_batch:v1:")
    model = [s for s in reads if ":abstract_screening:" in s["operation_key"]]
    assert model and all(s["status"] == "succeeded" for s in model)
    assert codes_of(store, late.rid)["W2"] not in ("abstract_not_read", None)
    # Every required read ended before the answer stage opened.
    opened = answer_started(store, late.rid)
    assert opened is not None and max(s["finished_at"] for s in model) <= opened
    # The run records the missed targets, and the miss split by cause adds up to it.
    view = fast_path.view(store, store.run(run_id))
    held = view["evidence_minimum"]
    assert held["rule"] == fast_path.EVIDENCE_MINIMUM_RULE and held["handover_missed_ms"] > 0
    assert view["handover_on_target"] is False
    assert held["causes"]["plan_overrun"] > 0
    assert abs(sum(held["causes"].values()) - held["handover_missed_ms"]) <= 10


def test_a_run_frozen_before_the_rule_cancels_and_cuts_exactly_as_before(tmp_path, monkeypatch):
    late = late_run(tmp_path, monkeypatch, older=True)
    store, run_id = late.store, late.run_id
    assert "evidence_minimum" not in late.run["budget"]["fast_path"]
    keyword = steps(store, run_id, "search:0")
    # The keyword query is closed by the handover without being sent, and no abstract is read by the model.
    assert not keyword or keyword[0]["status"] != "succeeded"
    model = [s for s in steps(store, run_id, "small_batch:v1:") if ":abstract_screening:" in s["operation_key"]]
    assert not [s for s in model if s["status"] == "succeeded"]
    # W2 is found by the keyword query alone, so without it W2 is never a candidate; if found, it is not read.
    assert codes_of(store, late.rid).get("W2") in (None, "abstract_not_read")
    assert "evidence_minimum" not in fast_path.view(store, store.run(run_id))


def test_a_hung_abstract_call_ends_at_the_ceiling_and_the_run_goes_on_without_its_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fast_path, "EVIDENCE_ABSTRACT_CEILING_MS", 1500)
    late = late_run(tmp_path, monkeypatch, adapter=Adapter(hang=lambda si: True))
    store, run_id = late.store, late.run_id
    assert late.run["status"] == "completed", late.run
    model = [s for s in steps(store, run_id, "small_batch:v1:") if ":abstract_screening:" in s["operation_key"]]
    assert model and {s["error_code"] for s in model} == {"model_read_cutoff"}
    assert codes_of(store, late.rid)["W2"] == "abstract_not_read"


def test_the_ceiling_counts_from_when_the_reads_can_start_and_the_lookups_have_a_stop(tmp_path, monkeypatch):
    from deixis.workflow.search import lookups
    monkeypatch.setattr(fast_path, "EVIDENCE_ABSTRACT_CEILING_MS", 1500)
    stops = []

    async def slow_lookups(*args, stop=None, prefix="", **kwargs):
        # The top N's lookups take longer than the whole ceiling.
        if not prefix:
            stops.append(stop)
            await asyncio.sleep(2)
    monkeypatch.setattr(lookups, "ask_second_sources", slow_lookups)
    late = late_run(tmp_path, monkeypatch)
    store = late.store
    assert late.run["status"] == "completed", late.run
    # The lookups were given the read stage's stop, and the reads still had their whole ceiling after them.
    assert stops and all(stop is not None for stop in stops)
    assert codes_of(store, late.rid)["W2"] not in ("abstract_not_read", None)


def test_a_failed_required_read_is_recorded_as_not_read_and_the_run_answers(tmp_path, monkeypatch):
    from deixis.models.adapter import ModelStepResult
    # Every abstract call fails as a 503 after its retries.
    adapter = FakeAdapter(valid_response, fail=lambda si: ModelStepResult(
        "failed", error="service unavailable", http_status=503) if si["task_type"] == "abstract_screening" else None)
    late = late_run(tmp_path, monkeypatch, adapter=adapter)
    store, run_id = late.store, late.run_id
    assert late.run["status"] == "completed", late.run
    model = [s for s in steps(store, run_id, "small_batch:v1:") if ":abstract_screening:" in s["operation_key"]]
    assert model and {s["status"] for s in model} <= {"failed", "outcome_unknown"}
    assert codes_of(store, late.rid)["W2"] == "abstract_not_read"
    # The answer stage opened with what was read.
    assert answer_started(store, late.rid) is not None


def test_a_pause_stops_a_required_read_at_once_and_resume_does_not_repeat_a_finished_one(tmp_path, monkeypatch):
    late_ledger(monkeypatch)
    hanging = {"on": True}
    # The first evaluation of the batch answers; the second hangs until the person pauses.
    adapter = Adapter(hang=lambda si: hanging["on"] and si["screening_target"]["run"] == 2)
    app = app_for(tmp_path, monkeypatch, Pool(list(POOL)), adapter=adapter)
    client = client_of(app)
    try:
        rid = client.post("/api/researches", json={"question": "How does irrigation scheduling affect marketable yield"
                                                               " in greenhouse tomato production?",
                                                   "model_connection": "fake", "requested_model": "fake-model",
                                                   "effort": "quick"}).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        deadline = time.time() + 20 * WAIT_FACTOR
        while time.time() < deadline and not [si for si in adapter.calls if si["task_type"] == "abstract_screening"
                                              and si["screening_target"]["run"] == 2]:
            time.sleep(0.05)
        asked = time.time()
        assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "paused" and time.time() - asked < 10, "the pause waited for the required read"
        first = [si for si in adapter.calls if si["task_type"] == "abstract_screening"
                 and si["screening_target"]["run"] == 1]
        hanging["on"] = False
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    # The first evaluation had answered before the pause: the resumed run did not send it again.
    assert [si for si in adapter.calls if si["task_type"] == "abstract_screening"
            and si["screening_target"]["run"] == 1] == first


def test_an_unreachable_model_pauses_a_required_read_and_the_retry_sends_it_again(tmp_path, monkeypatch):
    from deixis.models.adapter import ModelStepResult
    late_ledger(monkeypatch)
    down = {"now": True}
    # The connection drops before the first abstract call is sent: the model is not reachable.
    adapter = FakeAdapter(valid_response, fail=lambda si: (
        ModelStepResult("failed", error="SYNTHETIC connection dropped", delivery_class="before_send")
        if down["now"] and si["task_type"] == "abstract_screening" else None))
    app = app_for(tmp_path, monkeypatch, Pool(list(POOL)), adapter=adapter)
    client = client_of(app)

    def reads():
        return [si for si in adapter.calls if si["task_type"] == "abstract_screening"]
    try:
        rid, run_id, _, run = discover(client)
        assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed"), run
        sent = len(reads())
        down["now"] = False
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        codes = codes_of(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    # The read that paused the run was sent again, and this time it was read.
    assert len(reads()) > sent and codes["W2"] not in ("abstract_not_read", None)


def test_a_failed_required_read_is_not_sent_again_on_resume(tmp_path, monkeypatch):
    from deixis.models.adapter import ModelStepResult
    late_ledger(monkeypatch)
    hanging = {"on": True}
    # The first evaluation of the batch fails as a 503; the second hangs until the person pauses.
    adapter = Adapter(hang=lambda si: hanging["on"] and si["screening_target"]["run"] == 2)
    adapter.fail = lambda si: (ModelStepResult("failed", error="service unavailable", http_status=503)
                               if si["task_type"] == "abstract_screening" and si["screening_target"]["run"] == 1
                               else None)
    app = app_for(tmp_path, monkeypatch, Pool(list(POOL)), adapter=adapter)
    client = client_of(app)

    def first():
        return [si for si in adapter.calls if si["task_type"] == "abstract_screening"
                and si["screening_target"]["run"] == 1]
    try:
        rid = client.post("/api/researches", json={"question": "How does irrigation scheduling affect marketable yield"
                                                               " in greenhouse tomato production?",
                                                   "model_connection": "fake", "requested_model": "fake-model",
                                                   "effort": "quick"}).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        deadline = time.time() + 20 * WAIT_FACTOR
        while time.time() < deadline and not [si for si in adapter.calls if si["task_type"] == "abstract_screening"
                                              and si["screening_target"]["run"] == 2]:
            time.sleep(0.05)
        while time.time() < deadline and not first():
            time.sleep(0.05)
        time.sleep(0.3)  # the failed evaluation is stored
        assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "paused", run
        sent = len(first())
        hanging["on"] = False
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        store = app.state.store
        codes = codes_of(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    # The failed evaluation was not sent again, and its batch stays not read.
    assert sent >= 1 and len(first()) == sent
    assert codes["W2"] == "abstract_not_read"


def test_a_pause_ends_a_required_read_waiting_on_the_connection_check(tmp_path, monkeypatch):
    import contextvars
    from deixis.workflow.run.flow import ResearchFlow
    late_ledger(monkeypatch)
    required = contextvars.ContextVar("required", default=False)
    call = ResearchFlow._abstract_call

    async def marked(self, *args, send_window=None, **kwargs):
        # Marks a required read (a window a stop must end), so the check below hangs for it alone.
        required.set(getattr(send_window, "interrupt", None) is not None)
        return await call(self, *args, send_window=send_window, **kwargs)
    monkeypatch.setattr(ResearchFlow, "_abstract_call", marked)

    class SlowCheck(FakeAdapter):
        """The connection check of a required read hangs."""
        waiting = False

        async def health(self, refresh=False):
            if required.get():
                self.waiting = True
                await asyncio.sleep(3600)
            return await super().health(refresh)

    adapter = SlowCheck(valid_response)
    app = app_for(tmp_path, monkeypatch, Pool(list(POOL)), adapter=adapter)
    client = client_of(app)
    try:
        rid = client.post("/api/researches", json={"question": "How does irrigation scheduling affect marketable yield"
                                                               " in greenhouse tomato production?",
                                                   "model_connection": "fake", "requested_model": "fake-model",
                                                   "effort": "quick"}).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        deadline = time.time() + 20 * WAIT_FACTOR
        while time.time() < deadline and not adapter.waiting:
            time.sleep(0.05)
        assert adapter.waiting, "no required read waited on the connection check"
        asked = time.time()
        assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "paused" and time.time() - asked < 10, "the pause waited for the connection check"
    finally:
        client.__exit__(None, None, None)


def test_a_transport_that_ignores_cancel_holds_neither_the_ceiling_nor_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(fast_path, "EVIDENCE_ABSTRACT_CEILING_MS", 1500)

    class Stubborn(FakeAdapter):
        """An abstract call that hangs and does not end on its first cancel."""

        async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
            from fakes import parse_step_input
            if parse_step_input(message)["task_type"] == "abstract_screening":
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    await asyncio.sleep(3600)
            return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)

    late = late_run(tmp_path, monkeypatch, adapter=Stubborn(valid_response))
    store, run_id = late.store, late.run_id
    assert late.run["status"] == "completed", late.run
    model = [s for s in steps(store, run_id, "small_batch:v1:") if ":abstract_screening:" in s["operation_key"]]
    assert model and {s["status"] for s in model} == {"outcome_unknown"}
    assert codes_of(store, late.rid)["W2"] == "abstract_not_read"


def test_the_search_stage_keeps_its_base_and_no_stage_carries_debt(tmp_path, monkeypatch):
    from test_fast_path_clock import FakeClock
    from deixis.domain.rules import TEST_EFFORT_BUDGETS
    from deixis.storage import db
    from deixis.workflow.run.store import Store
    from deixis.workflow.search import small_batch

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research("SYNTHETIC minimum", "academic", "quick", ["openalex"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    run = store.run(run["id"])
    # Before the search stage opens, nothing of its minimum has passed, whatever the handover says.
    fast_path.enter_stage(store, run, "plan")
    clock.advance(40)  # Quick's plan share is 8 s; its handover is 51 s.
    assert fast_path.stage_deadline(store, run, "search") is None
    fast_path.close_stage(store, run["id"], "plan")
    fast_path.enter_stage(store, run, "search")
    started = clock.now()
    # Search keeps its 14-second base; the plan overrun is not carried as debt.
    assert fast_path.stage_deadline(store, run, "search") == started + timedelta(seconds=14)
    row = conn.execute("SELECT balance_before_ms, alloc_ms FROM fast_path_stages WHERE stage = 'search'").fetchone()
    assert (row[0], row[1]) == (0, 14000)
    clock.advance(13.9)
    assert not fast_path.past_deadline(store, run, "search")
    clock.advance(0.2)
    assert fast_path.past_deadline(store, run, "search")
    fast_path.close_stage(store, run["id"], "search")
    fast_path.enter_stage(store, run, "ranking")
    # Ranking keeps its 15-second base too.
    row = conn.execute("SELECT balance_before_ms, alloc_ms FROM fast_path_stages WHERE stage = 'ranking'").fetchone()
    assert (row[0], row[1]) == (0, 15000)
    conn.close()


def test_past_the_handover_ranking_keeps_its_own_time_and_the_miss_is_split_by_cause(tmp_path):
    from test_fast_path_clock import FakeClock
    from deixis.domain.rules import TEST_EFFORT_BUDGETS
    from deixis.storage import db
    from deixis.workflow.run.store import Store
    from deixis.workflow.search import small_batch

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research("SYNTHETIC causes", "academic", "quick", ["openalex"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    run = store.run(run["id"])
    fast_path.enter_stage(store, run, "plan")
    clock.advance(40)  # the plan has overrun its own 8 s allocation
    fast_path.close_stage(store, run["id"], "plan")
    fast_path.enter_stage(store, run, "search")
    clock.advance(10.1)  # still within the shared search's 14 s allocation
    fast_path.close_stage(store, run["id"], "search")
    fast_path.enter_stage(store, run, "ranking")
    # Ranking keeps its own 15 s even after the plan has overrun.
    assert fast_path.stage_deadline(store, run, "ranking") == clock.now() + timedelta(seconds=18.9)
    assert not fast_path.past_deadline(store, run, "ranking")
    clock.advance(8)  # 7.1 s now lies past Quick's 51 s handover
    causes = fast_path.view(store, store.run(run["id"]))["evidence_minimum"]["causes"]
    assert causes == {"ranking_allocation": 7100, "between_stages": 0}
    # The causes add up to the time past the handover.
    assert sum(causes.values()) == round((40 + 10.1 + 8 - 51) * 1000)
    conn.close()


def test_a_required_read_waiting_for_a_limiter_slot_is_withdrawn_at_the_ceiling_or_on_a_stop():
    from types import SimpleNamespace
    from deixis.workflow.run.concurrency import ModelCallLimiter
    from deixis.workflow.run.flow import ResearchFlow, RunStopped

    async def scenario(stop_after):
        loop = asyncio.get_running_loop()
        limiter = ModelCallLimiter(1)
        # Another call holds the only slot for an hour.
        blocker = asyncio.ensure_future(limiter.run("other", lambda: asyncio.sleep(3600)))
        await asyncio.sleep(0)
        begun = loop.time()

        def window():
            return begun + 0.5 - loop.time()  # the ceiling half a second away
        window.interrupt = lambda: stop_after is not None and loop.time() - begun >= stop_after
        sent = []

        async def call(job):
            sent.append(job.key)
        flow = SimpleNamespace(deps=SimpleNamespace(limiter=limiter), _checkpoint=lambda *args: None)
        try:
            stop = await asyncio.wait_for(ResearchFlow._send_through_limiter(
                flow, {"id": "run", "scope_revision": 1}, iter([SimpleNamespace(key="read")]), call,
                lambda completed: None, watch=window), 5)
        finally:
            blocker.cancel()
            await asyncio.gather(blocker, return_exceptions=True)
        return stop, sent, loop.time() - begun

    # At the ceiling the queued read is withdrawn unsent and the stage goes on.
    stop, sent, took = asyncio.run(scenario(None))
    assert stop is None and sent == [] and took < 2
    # A stop withdraws it at once and is returned for the caller to raise.
    stop, sent, took = asyncio.run(scenario(0.1))
    assert isinstance(stop, RunStopped) and sent == [] and took < 0.5

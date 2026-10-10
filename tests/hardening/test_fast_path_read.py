"""D251 synthetic deadline/admission/recovery evidence; no live providers or models."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from deixis.domain import canonical
from deixis.storage.db import transaction
from deixis.workflow import background_fetch, fast_path, fast_read, fulltext, small_batch
from deixis.workflow.flow import ResearchFlow, RunStopped
from deixis.workflow.worker import Worker
from deixis.workflow.store import ACTIVE_RUN_STATUSES, RunInProgress
from test_fast_path_clock import library, stage, answer_run, historical_read_policy
from test_small_batch_flow import app_for, client_of
from test_fetch_overlap_flow import discover
from fakes import FakeAdapter, valid_response


@pytest.mark.parametrize("case", ["open", "paused", "done", "missing_stage", "legacy", "no_policy", "debt", "rework"])
def test_stage_deadline_is_frozen_stage_specific_and_restart_safe(library, case):
    lib = library
    iid = fast_path.enter_stage(lib.store, lib.run, "read")
    allocation = stage(lib, "read")["alloc_ms"]
    if case == "paused":
        lib.clock.advance(12)
        lib.store.update_run(lib.run["id"], status="paused")
        assert fast_path.stage_deadline(lib.store, lib.run, "read") is None
        lib.clock.advance(500)
        lib.store.update_run(lib.run["id"], status="running")
        fast_path.enter_stage(lib.store, lib.run, "read")
        expected = lib.clock.now() + timedelta(milliseconds=allocation - 12000)
    elif case == "debt":
        lib.conn.execute("UPDATE fast_path_stages SET used_ms = alloc_ms + 1000 WHERE stage = 'read'")
        expected = lib.clock.now() - timedelta(seconds=1)
        assert fast_path.past_deadline(lib.store, lib.run, "read")
    elif case == "done":
        fast_path.close_stage(lib.store, lib.run["id"], "read")
        expected = None
    elif case == "rework":
        lib.conn.execute("UPDATE fast_path_intervals SET rework = 1 WHERE id = ?", (iid,))
        expected = None
    elif case == "missing_stage":
        lib.run["budget"]["fast_path"]["enforced_stages"] = ["search", "ranking"]
        expected = None
    elif case == "legacy":
        del lib.run["budget"]["fast_path"]["enforced_stages"]
        expected = None
    elif case == "no_policy":
        del lib.run["budget"]["fast_path"]
        expected = None
    else:
        expected = lib.clock.now() + timedelta(milliseconds=allocation)
    assert fast_path.stage_deadline(lib.store, lib.run, "read") == expected
    assert fast_path.stage_deadline(lib.store, lib.run, "search") is None


def candidate(n, code="blocks_in_title", text=False, chained=False):
    return {"work_id": f"w{n}", "head": f"h{n}", "chained": chained, "selection": None,
            "versions": [{"id": f"h{n}", "has_text": text, "fulltext": None,
                          "abstract": {"reason_code": code, "decided_by": "code", "stale": False}}]}


def test_top_k_counts_cached_text_and_keeps_frozen_order():
    works = [candidate(0, text=True), candidate(1, chained=True), candidate(2), candidate(3)]
    order = ["h1", "h0", "h2", "h3"]
    baseline = fulltext.baseline_of(works)
    assert fast_read.selected(works, order, 2, set(), baseline) == ["w1", "w0"]
    assert fast_read.selected(works, order, 2, {"w1"}, baseline) == ["w0"]
    assert fast_read.selected(works, order, 2, set(), baseline | {"fulltext_excluded": ["w1"]}) == ["w0", "w2"]
    # A completed fetch cannot admit a later work or change the PDF-yield denominator.
    works[1]["versions"][0].update(has_text=True, fulltext={"reason_code": "not_read_yet", "decided_by": "code"})
    assert fast_read.selected(works, order, 2, set(), baseline) == ["w1", "w0"]


def test_settled_work_without_text_frees_its_slot():
    works = [candidate(0), candidate(1), candidate(2), candidate(3, text=True)]
    order = ["h0", "h1", "h2", "h3"]
    baseline = fulltext.baseline_of(works)
    assert fast_read.selected(works, order, 2, set(), baseline) == ["w0", "w1"]
    assert fast_read.selected(works, order, 2, set(), baseline, {"w0"}) == ["w1", "w2"]
    claims = {"w0": {"status": "succeeded", "output": {"code": "no_fulltext"}}, "w1": {"status": "running", "output": {}},
              "w2": {"status": "failed", "output": {"code": None}},
              "w3": {"status": "succeeded", "output": {"code": "not_read_yet", "asset_id": "a3"}},
              "w4": {"status": "succeeded", "output": {"code": "text_unreadable", "asset_id": None}}}
    policy = fast_path.freeze_budget({}, "quick")
    assert fast_read.without_text(policy, claims) == {"w0", "w2", "w4"}
    # Text that reaches a released work later does not take the slot back.
    works[0]["versions"][0].update(has_text=True)
    assert fast_read.without_text(policy, claims) == {"w0", "w2", "w4"}
    assert fast_read.selected(works, order, 2, set(), baseline, {"w0", "w2"}) == ["w1", "w3"]
    assert fast_read.without_text({k: v for k, v in policy.items() if k != "slot_refill"}, claims) == set()


def test_pending_prefix_reserves_k_until_excluded():
    works = [candidate(0, "abstract_not_read"), candidate(1), candidate(2)]
    baseline = fulltext.baseline_of(works)
    assert fast_read.selected(works, ["h0", "h1", "h2"], 1, {"w0"}, baseline) == []
    assert fast_read.selected(works, ["h0", "h1", "h2"], 1, set(), baseline) == ["w1"]


def test_fetch_pool_has_twelve_slots_and_foreground_priority():
    async def check():
        pool = background_fetch.FetchSlots()
        release = asyncio.Event()
        active = 0
        maximum = 0
        async def job():
            nonlocal active, maximum
            async with pool.slot():
                active += 1
                maximum = max(maximum, active)
                await release.wait()
                active -= 1
        tasks = [asyncio.create_task(job()) for _ in range(20)]
        await asyncio.sleep(0.01)
        assert maximum == pool.active == 12
        release.set()
        await asyncio.gather(*tasks)
        assert pool.active == pool.waiting == 0

        pool = background_fetch.FetchSlots(1)
        order = []
        async def admitted(name, background):
            async with pool.slot(background=background):
                order.append(name)
                await asyncio.sleep(0)
        async with pool.slot():
            bg = asyncio.create_task(admitted("background", True))
            await asyncio.sleep(0)
            fg = asyncio.create_task(admitted("foreground", False))
            await asyncio.sleep(0)
        await asyncio.gather(bg, fg)
        assert order == ["foreground", "background"]
    asyncio.run(check())


def test_queue_publication_is_atomic_unique_and_recoverable(library, tmp_path):
    lib = library
    item = {"work_id": "synthetic", "head": "synthetic", "position": 1}
    with pytest.raises(RuntimeError), transaction(lib.conn):
        background_fetch.enqueue(lib.store, lib.run, item, "in_flight")
        raise RuntimeError("synthetic rollback")
    assert lib.conn.execute("SELECT COUNT(*) FROM fast_path_background_fetches").fetchone()[0] == 0
    with transaction(lib.conn):
        background_fetch.enqueue(lib.store, lib.run, item, "in_flight")
        background_fetch.enqueue(lib.store, lib.run, item, "not_started")
    assert lib.conn.execute("SELECT COUNT(*) FROM fast_path_background_fetches").fetchone()[0] == 1
    lib.conn.execute("UPDATE fast_path_background_fetches SET status = 'running', attempts = 2")
    step = lib.store.step(lib.run["id"], "fulltext_work:synthetic", "code:fulltext_work")
    lib.store.start_step(step["id"])
    Worker(lib.store, None, tmp_path / "lock").recover()
    row = lib.conn.execute("SELECT * FROM fast_path_background_fetches").fetchone()
    assert (row["status"], row["attempts"]) == ("queued", 2)
    assert lib.store.existing_step(lib.run["id"], "fulltext_work:synthetic")["status"] == "outcome_unknown"
    lib.conn.execute("UPDATE fast_path_background_fetches SET status = 'succeeded'")
    Worker(lib.store, None, tmp_path / "lock").recover()
    assert lib.conn.execute("SELECT status FROM fast_path_background_fetches").fetchone()[0] == "succeeded"


def test_background_queue_cancels_revised_scope_without_fetch(library, monkeypatch):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    item = {"work_id": "synthetic", "head": "synthetic", "position": 1}
    background_fetch.enqueue(lib.store, lib.run, item, "not_started")
    lib.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (lib.rid,))
    flow.background_fetch.pick()
    row = lib.conn.execute("SELECT status, outcome_code FROM fast_path_background_fetches").fetchone()
    assert tuple(row) == ("cancelled", "scope_revised")
    assert not flow.background_fetch.tasks


@pytest.mark.parametrize("kind", ["answer", "discovery"])
@pytest.mark.parametrize("status", ACTIVE_RUN_STATUSES)
def test_background_admission_and_publication_wait_for_other_active_run(library, monkeypatch, kind, status):
    lib = library
    background_fetch.enqueue(lib.store, lib.run, {"work_id": "synthetic", "head": "synthetic", "position": 1}, "in_flight")
    run = answer_run(lib)
    lib.conn.execute("UPDATE runs SET kind = ?, status = ? WHERE id = ?", (kind, status, run["id"]))
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {"synthetic": "synthetic"})
    async def check():
        flow.background_fetch.pick()
        assert not flow.background_fetch.tasks
        assert lib.conn.execute("SELECT status FROM fast_path_background_fetches").fetchone()[0] == "queued"
        task = asyncio.create_task(background_fetch.before_publish(flow, lib.run))
        await asyncio.sleep(0.01)
        assert not task.done() and not lib.conn.in_transaction
        lib.store.update_run(run["id"], status="completed")
        await asyncio.wait_for(task, 1)
    asyncio.run(check())


@pytest.mark.parametrize("concurrency,expected_calls", [(1, 1), (2, 2), (6, 4)])
def test_abstract_deadline_after_limiter_leaves_unsent_records_unread(tmp_path, monkeypatch, concurrency, expected_calls):
    holder = {}
    def respond(si):
        if si["task_type"] == "abstract_screening" and not holder.get("expired"):
            holder["expired"] = True
            holder["app"].state.store.clock.advance(1000)
        return valid_response(si)
    from test_fast_path_clock import FakeClock
    adapter = FakeAdapter(respond, delay=0.03)
    app, _ = app_for(tmp_path, monkeypatch, 30, model_works=True, fetch="off", reading="off", model_concurrency=concurrency, adapter=adapter)
    holder["app"] = app
    with client_of(app) as client:
        app.state.store.clock = FakeClock()
        _, run_id, _, run = discover(client)
        assert run["status"] == "completed", run
        calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        assert len(calls) == expected_calls
        close = run["fast_path"]["read"]["cutoff"]
        assert close["N"] == 25
        assert len(close["items"]) == 25
        assert len(close["not_screened_at_cutoff"]) == (25 if concurrency == 1 else 5 if concurrency == 2 else 0)
        assert not run["fast_path"]["read"]["background_fetches"]
        assert not [s for s in small_batch.steps(app.state.store, run_id)
                    if s["kind"] == "code:small_batch_deferred"]
        assert adapter.max_concurrent >= min(concurrency, 4)


def test_abstract_cutoff_stores_each_unread_version_once(library, monkeypatch):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store, limiter=SimpleNamespace(limit=1)))
    batches = [["s0", "s1"], ["s2"]]
    written = []
    monkeypatch.setattr(lib.store, "candidates", lambda rid: [
        {"source_version_id": svid} for batch in batches for svid in batch])
    monkeypatch.setattr(flow, "_human_decided_records", lambda *args: set())
    monkeypatch.setattr(flow, "_write_abstract_codes", lambda run, step_id, codes: written.extend(codes))
    asyncio.run(flow._abstract_stage(lib.run, {}, {}, [], batch_key="small_batch:v1:synthetic:fast",
                                    frozen_plan={"batches": batches, "runs": 2}, cutoff=lambda: True))
    output = lib.store.existing_step(lib.run["id"], "small_batch:v1:synthetic:fast:abstract_stage")["output"]
    assert output == {"abstract_not_read": ["s0", "s1", "s2"]}
    assert written == [(svid, "abstract_not_read") for svid in ["s0", "s1", "s2"]]


@pytest.mark.parametrize("status", ["queued", "running"])
def test_failed_search_retry_waits_for_background_rows(library, status):
    lib = library
    lib.store.update_run(lib.run["id"], status="completed")
    step = lib.store.step(lib.run["id"], "search:synthetic", "provider_search:openalex")
    lib.store.finish_step(step["id"], "failed")
    background_fetch.enqueue(lib.store, lib.run, {"work_id": "w0", "head": "h0", "position": 1}, "in_flight")
    lib.conn.execute("UPDATE fast_path_background_fetches SET status = ?", (status,))
    with pytest.raises(RunInProgress):
        lib.store.queue_failed_search_retry(lib.run["id"])
    assert lib.store.run(lib.run["id"])["status"] == "completed"
    assert lib.store.run(lib.run["id"])["budget"] == lib.run["budget"]
    lib.conn.execute("UPDATE fast_path_background_fetches SET status = 'succeeded'")
    assert lib.store.queue_failed_search_retry(lib.run["id"])["status"] == "queued"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_fast_read_does_not_admit_background_owned_work(library, monkeypatch, status):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    works = [candidate(0)]
    item = {"work_id": "w0", "head": "h0", "versions": [], "user_priority": False, "position": 1}
    listing = {"items": [item], "manifest_hash": "synthetic", "order_hash": "synthetic",
               "manifest": {"versions": {}}, "order": ["h0"]}
    lib.run["budget"]["inspection"].update(fetch_limit=10, read_limit=10)
    monkeypatch.setattr(flow, "_fulltext_works", lambda rid: works)
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {"w0": "h0"})
    monkeypatch.setattr(small_batch, "unchanged_heads", lambda *args: ["h0"])
    monkeypatch.setattr(flow, "_abstract_code_stage", lambda *args, **kwargs: {"batches": [], "runs": 2})
    async def abstracts(*args, **kwargs):
        return None
    async def forbidden(*args, **kwargs):
        pytest.fail("background-owned work must not start a second foreground fetch")
    monkeypatch.setattr(flow, "_abstract_stage", abstracts)
    monkeypatch.setattr(flow, "_overlap_work", forbidden)
    flow._claim(lib.run["id"], "w0", False, "fast_path")
    step = lib.store.existing_step(lib.run["id"], "fulltext_work:w0")
    lib.store.start_step(step["id"])
    background_fetch.enqueue(lib.store, lib.run, item, "in_flight")
    lib.conn.execute("UPDATE fast_path_background_fetches SET status = ?", (status,))
    fast_path.enter_stage(lib.store, lib.run, "read")
    asyncio.run(fast_read.execute(flow, lib.run, {}, {}, listing))
    assert lib.store.existing_step(lib.run["id"], "fulltext_work:w0")["attempt"] == 1
    assert lib.conn.execute("SELECT status FROM fast_path_background_fetches").fetchone()[0] == status


@pytest.mark.parametrize("status", ["cancelled", "failed"])
@pytest.mark.parametrize("in_flight", [False, True])
def test_background_rows_close_with_owner_terminal_reason(library, monkeypatch, status, in_flight):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {"synthetic": "head"})
    background_fetch.enqueue(lib.store, lib.run, {"work_id": "synthetic", "head": "head", "position": 1}, "in_flight")
    async def check():
        if in_flight:
            release = asyncio.Event()
            async def blocked():
                await release.wait()
                raise RunStopped
            flow.background_fetch.adopt(lib.run, "synthetic", asyncio.create_task(blocked()))
            await asyncio.sleep(0)
            assert lib.conn.execute("SELECT status FROM fast_path_background_fetches").fetchone()[0] == "running"
            lib.store.update_run(lib.run["id"], status=status)
            release.set()
            await asyncio.gather(*flow.background_fetch.tasks.values())
        else:
            lib.store.update_run(lib.run["id"], status=status)
            flow.background_fetch.pick()
            assert not flow.background_fetch.tasks
    asyncio.run(check())
    row = lib.conn.execute("SELECT status, outcome_code, finished_at FROM fast_path_background_fetches").fetchone()
    assert (row["status"], row["outcome_code"]) == (status, f"run_{status}")
    assert row["finished_at"] is not None


def test_fast_read_hands_off_fetch_without_wait_and_resume_is_idempotent(library, monkeypatch):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    works = [candidate(n) for n in range(25)]
    items = [{"work_id": w["work_id"], "head": w["head"], "versions": [], "user_priority": False,
              "position": n + 1} for n, w in enumerate(works)]
    listing = {"items": items, "manifest_hash": "synthetic", "order_hash": "synthetic",
               "manifest": {"versions": {}}, "order": [w["head"] for w in works]}
    lib.run["budget"]["inspection"].update(fetch_limit=10, read_limit=10)
    monkeypatch.setattr(flow, "_fulltext_works", lambda rid: works)
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {w["work_id"]: w["head"] for w in works})
    monkeypatch.setattr(small_batch, "unchanged_heads", lambda store, rid, listing, items: [i["head"] for i in items])
    def code(*args, batch_key, **kwargs):
        return small_batch.save_code(flow, lib.run, f"{batch_key}:abstract_stage", "code:abstract_stage",
                                     lambda: {"batches": [], "runs": 2})
    monkeypatch.setattr(flow, "_abstract_code_stage", code)
    async def abstracts(*args, **kwargs):
        return None
    monkeypatch.setattr(flow, "_abstract_stage", abstracts)

    async def check():
        release = asyncio.Event()
        fetched = []
        async def blocked(run, wid):
            fetched.append(wid)
            step = lib.store.existing_step(run["id"], f"fulltext_work:{wid}")
            lib.store.start_step(step["id"])
            lib.clock.advance(1000)
            await release.wait()
            lib.store.finish_step(step["id"], "succeeded", output={"code": "not_read_yet"})
        monkeypatch.setattr(flow, "_overlap_work", blocked)
        fast_path.enter_stage(lib.store, lib.run, "read")
        await asyncio.wait_for(fast_read.execute(flow, lib.run, {}, {}, listing), 1)
        close = lib.store.existing_step(lib.run["id"], "small_batch:v1:synthetic:fast:close")["output"]
        assert close["k_selected"] == 10
        assert len(close["fulltext_after_cutoff"]) == 10
        assert list(close["fulltext_after_cutoff"].values()).count("in_flight") == 1
        assert stage(lib, "read")["status"] == "done"
        before = lib.conn.execute("SELECT COUNT(*) FROM fast_path_background_fetches").fetchone()[0]
        await fast_read.execute(flow, lib.run, {}, {}, listing)
        assert lib.conn.execute("SELECT COUNT(*) FROM fast_path_background_fetches").fetchone()[0] == before
        release.set()
        await asyncio.gather(*flow.background_fetch.tasks.values())
        assert fetched == ["w0"]
        assert lib.conn.execute("SELECT status FROM fast_path_background_fetches WHERE work_id = 'w0'").fetchone()[0] == "succeeded"
    asyncio.run(check())


@pytest.mark.parametrize("case", ["forward", "reverse", "late_text", "resume"])
def test_slot_refill_is_order_independent_permanent_and_resumable(library, monkeypatch, case):
    """Even works have no file. Whatever the completion order, the K slots go to the first K odd works."""
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    works = [candidate(n) for n in range(25)]
    items = [{"work_id": w["work_id"], "head": w["head"], "versions": [], "user_priority": False,
              "position": n + 1} for n, w in enumerate(works)]
    listing = {"items": items, "manifest_hash": "synthetic", "order_hash": "synthetic",
               "manifest": {"versions": {}}, "order": [w["head"] for w in works]}
    lib.run["budget"]["inspection"].update(fetch_limit=10, read_limit=10)
    by_id = {w["work_id"]: w for w in works}
    monkeypatch.setattr(flow, "_fulltext_works", lambda rid: works)
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {w["work_id"]: w["head"] for w in works})
    monkeypatch.setattr(small_batch, "unchanged_heads", lambda store, rid, listing, items: [i["head"] for i in items])
    def code(*args, batch_key, **kwargs):
        return small_batch.save_code(flow, lib.run, f"{batch_key}:abstract_stage", "code:abstract_stage",
                                     lambda: {"batches": [], "runs": 2})
    monkeypatch.setattr(flow, "_abstract_code_stage", code)
    async def abstracts(*args, **kwargs):
        return None
    monkeypatch.setattr(flow, "_abstract_stage", abstracts)
    fetched, read = [], []

    async def settle(run, wid):
        n = int(wid[1:])
        fetched.append(wid)
        await asyncio.sleep(0.001 * ((n if case == "forward" else 25 - n) % 7))
        step = lib.store.existing_step(run["id"], f"fulltext_work:{wid}")
        lib.store.finish_step(step["id"], "succeeded", output={"code": "no_fulltext" if n % 2 == 0 else "not_read_yet",
            "asset_id": None if n % 2 == 0 else f"a{n}", "claim": step["output"]["claim"]})
        if n % 2:
            by_id[wid]["versions"][0].update(has_text=True)
        elif case == "late_text":  # another version of the released work brings text later
            by_id[wid]["versions"][0].update(has_text=True)

    async def adjudicate(run, scope, *, batch_key, order, **kwargs):
        read.append(order[0])
    monkeypatch.setattr(flow, "_overlap_work", settle)
    monkeypatch.setattr(flow, "_fulltext_adjudication", adjudicate)
    if case == "resume":  # a crashed run already settled two empty claims
        for wid in ("w0", "w2"):
            flow._claim(lib.run["id"], wid, False, "fast_path")
            step = lib.store.existing_step(lib.run["id"], f"fulltext_work:{wid}")
            lib.store.finish_step(step["id"], "succeeded", output={"code": "no_fulltext", "asset_id": None})

    async def check():
        fast_path.enter_stage(lib.store, lib.run, "read")
        await asyncio.wait_for(fast_read.execute(flow, lib.run, {}, {}, listing), 5)
    asyncio.run(check())
    close = lib.store.existing_step(lib.run["id"], "small_batch:v1:synthetic:fast:close")["output"]
    odd = [f"w{n}" for n in range(1, 21, 2)]
    assert sorted(close["selected_work_ids"], key=lambda w: int(w[1:])) == odd
    assert sorted(read, key=lambda h: int(h[1:])) == [f"h{n}" for n in range(1, 21, 2)]
    assert not set(close["attempted_without_text"]) & set(close["selected_work_ids"])
    assert set(close["attempted_without_text"]) <= {f"w{n}" for n in range(0, 25, 2)}
    if case == "resume":
        assert "w0" not in fetched and "w2" not in fetched


def stage_of(store, run_id, name):
    return dict(store.conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? AND stage = ?",
                                   (run_id, name)).fetchone())


@pytest.mark.parametrize("task", ["fulltext_adjudication", "abstract_screening", "health"])
def test_hung_model_call_is_cut_at_the_read_deadline_without_pausing(tmp_path, monkeypatch, task):
    """D258: a call still out at the read deadline plus the drain margin closes as a cutoff; the run goes on."""
    import time
    from fakes import valid_response as respond

    class Hanging(FakeAdapter):
        hung = 0
        reading = False

        async def health(self, refresh=False):
            if task == "health" and self.reading and not self.hung:
                self.hung += 1
                await asyncio.sleep(60)  # the connection check of the next call hangs
            return await super().health(refresh)

        async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
            from fakes import parse_step_input
            kind = parse_step_input(message)["task_type"]
            if kind == "fulltext_adjudication":
                self.reading = True
            if kind == task and not self.hung:
                self.hung += 1
                await asyncio.sleep(60)
            return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)

    bases, *rest = fast_path.MODES["quick"]
    monkeypatch.setitem(fast_path.MODES, "quick", ((1, 1, 1, 2, 30), *rest))  # little carry-forward into read
    freeze = fast_path.freeze_budget
    def short_drain(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        policy.pop("policy_hash")
        policy["read_drain_ms"] = 300
        return policy | {"policy_hash": canonical.sha256_hex(policy)}
    monkeypatch.setattr(fast_path, "freeze_budget", short_drain)
    adapter = Hanging(respond)
    app, fetcher = app_for(tmp_path, monkeypatch, 30, pdf=True, adapter=adapter,
                           model_works=task == "abstract_screening")
    started = time.monotonic()
    with client_of(app) as client:
        rid, run_id, _, run = discover(client)
        elapsed = time.monotonic() - started
        assert run["status"] == "completed", run
        store = app.state.store
        cut = [dict(r) for r in store.conn.execute(
            "SELECT s.status, s.error_code, (SELECT count(*) FROM model_sessions m WHERE m.step_id = s.id) AS sessions"
            " FROM run_steps s WHERE s.run_id = ? AND s.error_code = 'model_read_cutoff'", (run_id,))]
        # A call cut while out keeps its one session; one cut before sending (a hung connection check) has none.
        expected = ([{"status": "cancelled", "error_code": "model_read_cutoff", "sessions": 0}] if task == "health"
                    else [{"status": "outcome_unknown", "error_code": "model_read_cutoff", "sessions": 1}])
        assert cut == expected
        read = stage_of(store, run_id, "read")
        assert read["status"] == "done" and read["used_ms"] < read["alloc_ms"] + 2000
    assert adapter.hung == 1 and elapsed < 30


def test_a_cut_call_is_never_sent_again_on_resume(library):
    """D258: a step closed at the read cutoff reads back as cut; the adapter is not reached again."""
    from deixis.workflow.flow import _AdjudicationJob
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    for key, kind in (("fulltext_adjudication:h0:1", "model:fulltext_adjudication"), ("s:abstract_screening:0:1", "model:abstract_screening")):
        step = lib.store.step(lib.run["id"], key, kind)
        lib.store.start_step(step["id"])
        lib.store.finish_step(step["id"], "outcome_unknown", error_code="model_read_cutoff", error="read_cutoff")
    async def check():
        job = _AdjudicationJob("fulltext_adjudication:h0:1", "h0", "h0", 1)
        assert await flow._adjudication_call(lib.run, {}, {}, job, None) == {"cutoff": True}
        assert await flow._abstract_call(lib.run, {}, 0, 1, [], None, "s:abstract_screening") == {"cutoff": True}
    asyncio.run(check())


def test_rate_limit_resend_that_would_land_after_the_cutoff_is_not_waited_for(library, monkeypatch):
    """D258: the backoff before a rate-limit resend counts against the read window too."""
    import time
    from datetime import timedelta as delta
    from deixis.models.adapter import ModelStepResult
    from deixis.workflow.flow import _ReadCutoff
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    step = lib.store.step(lib.run["id"], "fulltext_adjudication:h0:1", "model:fulltext_adjudication")
    flow._send_by[lib.run["id"]] = lambda: lib.clock.now() + delta(seconds=1)  # less than the 1.5 s backoff
    monkeypatch.setattr(lib.store, "start_model_session", lambda *a, **k: "ses_synthetic")
    monkeypatch.setattr(lib.store, "finish_model_session", lambda *a, **k: None)
    monkeypatch.setattr(flow, "_model_result_checkpoint", lambda *a, **k: True)
    sent = []

    class Limited:
        async def run_step(self, *args):
            sent.append(args)
            return ModelStepResult("failed", error="429", error_kind="rate_limited")

    class Limiter:
        async def reduce(self):
            pass

    async def check():
        started = time.monotonic()
        with pytest.raises(_ReadCutoff):
            await flow._call_adapter(lib.run["id"], lib.rid, step["id"], "sin_synthetic", "fake", "fake-model",
                                     Limited(), "b", "d", "m", {}, None, Limiter())
        return time.monotonic() - started
    assert asyncio.run(check()) < 1.0 and len(sent) == 1


def test_new_read_keeps_chain_and_list_freeze_in_ranking(tmp_path, monkeypatch):
    freeze = small_batch.freeze_list
    seen = []
    def timed(flow, run, *args):
        row = flow.store.conn.execute("SELECT stage FROM fast_path_intervals WHERE run_id = ? AND closed_at IS NULL AND stage != 'chain'",
                                      (run["id"],)).fetchone()
        seen.append(row[0])
        flow.store.clock.advance(3)
        return freeze(flow, run, *args)
    monkeypatch.setattr(small_batch, "freeze_list", timed)
    from test_fast_path_clock import FakeClock
    app, _ = app_for(tmp_path, monkeypatch, 3, fetch="off", reading="off")
    with client_of(app) as client:
        app.state.store.clock = FakeClock()
        _, _, _, run = discover(client)
        assert run["status"] == "completed", run
        assert seen == ["ranking"]
        stages = {s["stage"]: s for s in run["fast_path"]["stages"]}
        assert stages["ranking"]["used_ms"] == 3000 and stages["read"]["used_ms"] == 0


def test_slice1_policy_keeps_legacy_batches_and_clock_boundaries(tmp_path, monkeypatch):
    freeze = fast_path.freeze_budget
    def old(*args):
        from deixis.domain import canonical
        policy = freeze(*args)
        policy.pop("enforced_stages")
        policy.pop("background_fetch_slots")
        policy["runner_version"] = 1
        policy["enforcement"] = "none"
        policy.pop("policy_hash")
        policy["policy_hash"] = canonical.sha256_hex(policy)
        return policy
    monkeypatch.setattr(fast_path, "freeze_budget", old)
    app, _ = app_for(tmp_path, monkeypatch, 60, fetch="off", reading="off")
    with client_of(app) as client:
        _, run_id, _, run = discover(client, "standard")
        assert run["status"] == "completed", run
        plans = [s["output"] for s in small_batch.steps(app.state.store, run_id) if s["kind"] == "code:small_batch_plan"]
        assert [len(p["items"]) for p in plans] == [40, 20]
        assert run["fast_path"]["enforcement"] == "none" and "read" not in run["fast_path"]
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM fast_path_background_fetches").fetchone()[0] == 0


def test_real_fetch_and_adjudication_are_bounded_by_top_k(tmp_path, monkeypatch):
    adapter = FakeAdapter(valid_response, delay=0.005)
    app, fetcher = app_for(tmp_path, monkeypatch, 30, pdf=True, adapter=adapter)
    with client_of(app) as client:
        _, run_id, _, run = discover(client)
        assert run["status"] == "completed", run
        assert len(fetcher.calls) == 10
        close = run["fast_path"]["read"]["cutoff"]
        plans = [s["output"] for s in small_batch.steps(app.state.store, run_id) if s["kind"] == "code:adjudication_plan"]
        assert len(plans) == 10 and sum(len(p["works"]) for p in plans) == 10
        assert len([c for c in adapter.calls if c["task_type"] == "fulltext_adjudication"]) == 20
        assert close["k_selected"] == close["fulltext_adjudicated_before_cutoff"] == 10
        assert not close["fulltext_after_cutoff"]
        assert run["usage"]["model_calls"] <= run["budget"]["max_model_calls"]


@pytest.mark.parametrize("refill", [True, False])
def test_work_without_text_gives_its_slot_to_the_next_work(tmp_path, monkeypatch, refill):
    if not refill:  # a policy frozen before slot refill keeps its first K claims
        freeze = fast_path.freeze_budget
        def frozen_before(*args, **kwargs):
            policy = freeze(*args, **kwargs)
            policy.pop("slot_refill")
            policy.pop("policy_hash")
            return policy | {"policy_hash": canonical.sha256_hex(policy)}
        monkeypatch.setattr(fast_path, "freeze_budget", frozen_before)
    app, fetcher = app_for(tmp_path, monkeypatch, 40, pdf=True)
    for n in range(0, 40, 2):  # every other work has no file
        del fetcher.answers[f"https://example.org/w{n}.pdf"]
    with client_of(app) as client:
        _, run_id, _, run = discover(client)
        assert run["status"] == "completed", run
        close = run["fast_path"]["read"]["cutoff"]
    if refill:
        assert close["fulltext_adjudicated_before_cutoff"] == close["k_selected"] == 10
        assert len(close["attempted_without_text"]) == len(fetcher.calls) - 10 > 0
        assert not set(close["attempted_without_text"]) & set(close["selected_work_ids"])
    else:
        assert len(fetcher.calls) == 10
        assert close["fulltext_adjudicated_before_cutoff"] < 10
        assert "attempted_without_text" not in close


def test_refill_is_bounded_by_the_screened_window(tmp_path, monkeypatch):
    app, fetcher = app_for(tmp_path, monkeypatch, 40, pdf=True)
    fetcher.answers.clear()  # no work has a file
    with client_of(app) as client:
        _, run_id, _, run = discover(client)
        assert run["status"] == "completed", run
        close = run["fast_path"]["read"]["cutoff"]
    assert len(fetcher.calls) == run["budget"]["fast_path"]["N"] == 25
    assert close["fulltext_adjudicated_before_cutoff"] == close["k_selected"] == 0
    assert len(close["attempted_without_text"]) == 25


def test_fulltext_deadline_after_limiter_cannot_decide_from_one_read(tmp_path, monkeypatch):
    from test_fast_path_clock import FakeClock
    holder = {}
    def before(si):
        if si["task_type"] == "fulltext_adjudication" and not holder.get("expired"):
            holder["expired"] = True
            holder["app"].state.store.clock.advance(1000)
    adapter = FakeAdapter(valid_response, before=before, delay=0.01)
    app, _ = app_for(tmp_path, monkeypatch, 25, pdf=True, adapter=adapter)
    holder["app"] = app
    with client_of(app) as client:
        app.state.store.clock = FakeClock()
        _, _, _, run = discover(client)
        assert run["status"] == "completed", run
        assert len([c for c in adapter.calls if c["task_type"] == "fulltext_adjudication"]) == 1
        assert run["fast_path"]["read"]["cutoff"]["fulltext_adjudicated_before_cutoff"] == 0
        assert run["usage"]["model_calls"] <= run["budget"]["max_model_calls"]


def test_real_pdf_after_cutoff_settles_in_background_without_reading(tmp_path, monkeypatch):
    from test_fast_path_clock import FakeClock
    import time

    app, fetcher = app_for(tmp_path, monkeypatch, 25, pdf=True)
    fetcher.delay = 0.3
    with client_of(app) as client:
        app.state.store.clock = FakeClock()
        def expire(fetcher, url):
            if len(fetcher.calls) == 1:
                app.state.store.clock.advance(1000)
        fetcher.hook = expire
        rid, run_id, _, run = discover(client)
        assert run["status"] == "completed", run
        close = run["fast_path"]["read"]["cutoff"]
        assert len(close["fulltext_after_cutoff"]) == close["k_selected"] == 10
        assert close["fulltext_adjudicated_before_cutoff"] == 0
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            view = client.get(f"/api/researches/{rid}").json()
            run = next(r for r in view["runs"] if r["id"] == run_id)
            counts = run["fast_path"]["read"]["background_counts"]
            if counts["succeeded"] == 10:
                break
            time.sleep(0.02)
        assert counts == {"queued": 0, "running": 0, "succeeded": 10, "failed": 0, "cancelled": 0}
        assert not [s for s in small_batch.steps(app.state.store, run_id) if s["kind"] == "model:fulltext_adjudication"]
        assert len(fetcher.calls) == 10
        assert {w["versions"][0]["fulltext"]["reason_code"] for w in app.state.worker.flow._fulltext_works(rid)
                if w["versions"][0]["has_text"]} == {"not_read_yet"}


def test_background_lane_caps_new_work_at_four_and_defers_queued_answers(library, monkeypatch):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    lib.store.update_run(lib.run["id"], status="completed")
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {f"w{n}": f"h{n}" for n in range(10)})
    for n in range(10):
        background_fetch.enqueue(lib.store, lib.run, {"work_id": f"w{n}", "head": f"h{n}", "position": n}, "not_started")
    async def check():
        release = asyncio.Event()
        active, maximum = 0, 0
        async def blocked(run, wid):
            nonlocal active, maximum
            step = lib.store.existing_step(run["id"], f"fulltext_work:{wid}")
            lib.store.start_step(step["id"])
            active += 1
            maximum = max(maximum, active)
            await release.wait()
            active -= 1
            lib.store.finish_step(step["id"], "succeeded")
        monkeypatch.setattr(flow, "_overlap_work", blocked)
        flow.background_fetch.pick()
        await asyncio.sleep(0.01)
        assert len(flow.background_fetch.tasks) == maximum == 4
        answer = answer_run(lib)
        lib.store.update_run(answer["id"], status="queued")
        release.set()
        await asyncio.gather(*flow.background_fetch.tasks.values())
        flow.background_fetch.pick()
        assert not flow.background_fetch.tasks
        assert lib.conn.execute("SELECT COUNT(*) FROM fast_path_background_fetches WHERE status = 'queued'").fetchone()[0] == 6
        lib.store.update_run(answer["id"], status="completed")
        while lib.conn.execute("SELECT 1 FROM fast_path_background_fetches WHERE status = 'queued'").fetchone():
            flow.background_fetch.pick()
            await asyncio.gather(*flow.background_fetch.tasks.values())
        flow.background_fetch.pick()
        assert not flow.background_fetch.tasks and maximum == 4
    asyncio.run(check())


def test_recovered_background_fetch_obeys_three_start_limit(library, monkeypatch):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    lib.store.update_run(lib.run["id"], status="completed")
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {"synthetic": "head"})
    background_fetch.enqueue(lib.store, lib.run, {"work_id": "synthetic", "head": "head", "position": 1}, "in_flight")
    step = lib.store.step(lib.run["id"], "fulltext_work:synthetic", "code:fulltext_work")
    for _ in range(3):
        lib.store.start_step(step["id"])
        lib.store.finish_step(step["id"], "outcome_unknown")
    async def forbidden(*args):
        pytest.fail("a fourth fetch start is forbidden")
    monkeypatch.setattr(flow, "_fetch_work_text", forbidden)
    async def check():
        flow.background_fetch.pick()
        await asyncio.gather(*flow.background_fetch.tasks.values())
    asyncio.run(check())
    assert tuple(lib.conn.execute("SELECT status, outcome_code FROM fast_path_background_fetches").fetchone()) == (
        "failed", "fetch_not_settled")


def test_source_removed_during_handoff_cancels_claim_and_queue(library, monkeypatch):
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    heads = {"synthetic": "head"}
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: heads)
    lib.store.update_run(lib.run["id"], status="completed")
    background_fetch.enqueue(lib.store, lib.run, {"work_id": "synthetic", "head": "head", "position": 1}, "in_flight")
    flow._claim(lib.run["id"], "synthetic", True, "fast_path")
    async def removed(*args):
        heads.clear()
        return {"work_id": "synthetic"}
    monkeypatch.setattr(flow, "_fetch_work_text", removed)
    async def check():
        flow.background_fetch.adopt(lib.run, "synthetic", asyncio.create_task(flow._overlap_work(lib.run, "synthetic")))
        await asyncio.gather(*flow.background_fetch.tasks.values())
    asyncio.run(check())
    assert lib.store.existing_step(lib.run["id"], "fulltext_work:synthetic")["status"] == "cancelled"
    assert tuple(lib.conn.execute("SELECT status, outcome_code FROM fast_path_background_fetches").fetchone()) == (
        "cancelled", "source_changed")


@pytest.mark.parametrize("interruption", ["pause", "recover"])
def test_abstract_resume_reuses_sent_step_and_excludes_downtime(tmp_path, monkeypatch, interruption):
    from test_fast_path_clock import FakeClock
    from test_fetch_overlap_flow import wait
    holder = {}
    def before(si):
        if si["task_type"] == "abstract_screening" and not holder.get("stopped"):
            holder["stopped"] = True
            store = holder["app"].state.store
            store.clock.advance(12)
            if interruption == "pause":
                store.update_run(si["run_id"], status="pause_requested")
            else:
                iid = store.conn.execute("SELECT id FROM fast_path_intervals WHERE stage = 'read' AND closed_at IS NULL").fetchone()[0]
                fast_path.checkpoint(store, iid)
                holder["app"].state.worker.recover()
    adapter = FakeAdapter(valid_response, delay=0.01, before=before)
    app, _ = app_for(tmp_path, monkeypatch, 25, model_works=True, fetch="off", reading="off",
                     model_concurrency=1, adapter=adapter)
    holder["app"] = app
    with client_of(app) as client:
        app.state.store.clock = FakeClock()
        rid, run_id, _, run = discover(client)
        assert run["status"] == "paused", run
        old_calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        assert len(old_calls) == 1
        app.state.store.clock.advance(1000)
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        # Recovery cannot treat a call interrupted before publication as succeeded.
        assert len(calls) == (5 if interruption == "recover" else 4)
        read = next(s for s in run["fast_path"]["stages"] if s["stage"] == "read")
        assert read["used_ms"] == 12000 and read["status"] == "done"
        assert not run["fast_path"]["read"]["cutoff"]["not_screened_at_cutoff"]

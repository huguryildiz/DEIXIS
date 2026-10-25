"""Fast-path reading: at most K works get full text before the read cutoff, the rest go to the background fetch queue, and the frozen cutoff is read back on resume; plus the full-text retrieval plan and identity check. SYNTHETIC records, no live providers or models."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
import httpx
import pytest
from deixis.storage.db import transaction
from deixis.workflow import background_fetch, fast_path, read as fast_read, fulltext, small_batch
from deixis.workflow.flow import ResearchFlow, RunStopped
from deixis.workflow.worker import Worker
from test_fast_path_clock import library, stage
from test_small_batch_flow import app_for, client_of
from test_fetch_overlap_flow import discover, wait
from fakes import FakeAdapter, valid_response
from deixis.documents import identity
from deixis.workflow import fulltext
from test_fast_path_clock import historical_read_policy  # noqa: F401  (fixtures used by name)
import subprocess
from pathlib import Path


@pytest.mark.parametrize("case", ["open", "paused"])
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


@pytest.mark.parametrize("status", ["running"])
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


@pytest.mark.parametrize("case", ["resume"])
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


def stubbed_read(lib, monkeypatch, works, settle):
    """Run `fast_read.execute` over SYNTHETIC `works` with the abstract stage, fetch and reading stubbed; return the
    closure."""
    flow = ResearchFlow(SimpleNamespace(store=lib.store))
    items = [{"work_id": w["work_id"], "head": w["head"], "versions": [], "user_priority": False,
              "position": n + 1} for n, w in enumerate(works)]
    listing = {"items": items, "manifest_hash": "synthetic", "order_hash": "synthetic",
               "manifest": {"versions": {}}, "order": [w["head"] for w in works]}
    lib.run["budget"]["inspection"].update(fetch_limit=10, read_limit=10)
    monkeypatch.setattr(flow, "_fulltext_works", lambda rid: works)
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {w["work_id"]: w["head"] for w in works})
    monkeypatch.setattr(small_batch, "unchanged_heads", lambda store, rid, listing, items: [i["head"] for i in items])
    monkeypatch.setattr(flow, "_abstract_code_stage", lambda *args, batch_key, **kwargs: small_batch.save_code(
        flow, lib.run, f"{batch_key}:abstract_stage", "code:abstract_stage", lambda: {"batches": [], "runs": 2}))
    async def nothing(*args, **kwargs):
        return None
    monkeypatch.setattr(flow, "_abstract_stage", nothing)
    monkeypatch.setattr(flow, "_fulltext_adjudication", nothing)
    monkeypatch.setattr(flow, "_overlap_work", settle)

    async def check():
        fast_path.enter_stage(lib.store, lib.run, "read")
        await asyncio.wait_for(fast_read.execute(flow, lib.run, {}, {}, listing), 5)
    asyncio.run(check())
    return lib.store.existing_step(lib.run["id"], "small_batch:v1:synthetic:fast:close")["output"]


def test_claimed_works_over_k_say_why(library, monkeypatch):
    """D60: a person who includes a work during the read gives it a slot while the K works already claimed keep
    theirs; the closure says why it selected more than K."""
    lib = library
    works = [candidate(0, "both_blocks_missing")] + [candidate(n) for n in range(1, 25)]
    by_id = {w["work_id"]: w for w in works}

    async def settle(run, wid):
        step = lib.store.existing_step(run["id"], f"fulltext_work:{wid}")
        lib.store.finish_step(step["id"], "succeeded", output={"code": "not_read_yet", "asset_id": f"a{wid}",
                                                               "claim": step["output"]["claim"]})
        by_id[wid]["versions"][0].update(has_text=True)
        works[0]["selection"] = {"origin": "user", "state": "included"}  # the person includes w0 meanwhile
    close = stubbed_read(lib, monkeypatch, works, settle)
    assert close["k_selected"] == len(close["selected_work_ids"]) == 11 and "w0" in close["selected_work_ids"]
    assert close["k_over_reason"] == "claimed_works_kept" and close["k_short_reason"] is None


def test_identity_failure_from_an_earlier_run_releases_the_slot(library, monkeypatch):
    """D60: a work whose PDF an earlier run found unconfirmed is not read again (its decision is fresh), so it does
    not hold one of this run's K slots either."""
    lib = library
    works = [candidate(n) for n in range(25)]
    works[0]["versions"][0].update(has_text=True, fulltext={"reason_code": "pdf_identity_unconfirmed",
                                                            "decided_by": "code", "stale": False})
    by_id = {w["work_id"]: w for w in works}

    async def settle(run, wid):
        step = lib.store.existing_step(run["id"], f"fulltext_work:{wid}")
        lib.store.finish_step(step["id"], "succeeded", output={"code": "not_read_yet", "asset_id": f"a{wid}",
                                                               "claim": step["output"]["claim"]})
        by_id[wid]["versions"][0].update(has_text=True)
    close = stubbed_read(lib, monkeypatch, works, settle)
    assert close["identity_unconfirmed"] == ["w0"]
    assert close["selected_work_ids"] == [f"w{n}" for n in range(1, 11)]


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


def test_budget_skipped_records_are_stored_without_human_decided_ones(library, monkeypatch):
    """D60: the records the model-call budget left unread are stored in their own step, so a restarted read closes
    with the same split; a record a person decided is not among them."""
    from deixis.workflow.flow import _Held
    lib = library
    flow = ResearchFlow(SimpleNamespace(store=lib.store, limiter=SimpleNamespace(limit=1)))
    batches = [["s0", "s1"], ["s2", "s3"]]
    monkeypatch.setattr(lib.store, "candidates", lambda rid: [{"source_version_id": svid} for b in batches for svid in b])
    monkeypatch.setattr(flow, "_human_decided_records", lambda rid, svids: {"s3"} & set(svids))
    monkeypatch.setattr(flow, "_write_abstract_codes", lambda run, step_id, codes: None)
    lib.run["budget"]["max_model_calls"] = 0
    flow._held[lib.run["id"]] = _Held(lib.run["scope_revision"])
    key = "small_batch:v1:synthetic:fast"
    asyncio.run(flow._abstract_stage(lib.run, {}, {}, [], batch_key=key, frozen_plan={"batches": batches, "runs": 2}))
    step = lib.store.existing_step(lib.run["id"], f"{key}:abstract_screening:budget_short:0")
    assert step["status"] == "succeeded"
    assert step["output"] == {"from_batch": 0, "source_version_ids": ["s0", "s1", "s2"]}
    # A restart with room in the budget again does not send the batches the stored stop left unread.
    lib.run["budget"]["max_model_calls"] = 100
    sent = []
    async def call(*args, **kwargs):
        sent.append(args)
    monkeypatch.setattr(flow, "_abstract_call", call)
    flow._held[lib.run["id"]] = _Held(lib.run["scope_revision"])
    asyncio.run(flow._abstract_stage(lib.run, {}, {}, [], batch_key=key, frozen_plan={"batches": batches, "runs": 2}))
    assert not sent


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


@pytest.mark.parametrize("interruption", ["recover"])
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


def _pdf_source(lib, doi="10.1/kept", oa_pdf_url="https://example.org/kept.pdf"):
    from deixis.providers.common import ProviderRecord
    record = ProviderRecord("WKEPT", "SYNTHETIC kept download", [], 2020, "J", "article", doi, None,
                            oa_pdf_url, "publishedVersion" if oa_pdf_url else None, "publishedVersion", None, None, {}, {})
    svid, _ = lib.store.upsert_provider_source("openalex", record, None)
    lib.store.add_to_corpus(lib.rid, svid, "search")
    return lib.store.source(svid)


def _fetch_flow(lib, tmp_path, fetch_pdf, http=None):
    from deixis.documents import fetch as fetch_module
    async def no_xml(url):
        return fetch_module.FetchResult("failed")
    settings = SimpleNamespace(papers_dir=tmp_path / "papers", recovery_dir=tmp_path / "recovery",
                               contact_email="synthetic@example.org")
    return ResearchFlow(SimpleNamespace(store=lib.store, settings=settings, fetch_pdf=fetch_pdf, fetch_xml=no_xml,
                                        http=http))


def test_a_kept_download_that_changed_on_disk_is_downloaded_again_not_published(library, tmp_path, monkeypatch):
    """The kept file is read once and its own bytes are checked: bytes that changed after a separate check are
    never published under the old link (Sol, P1)."""
    import hashlib
    from deixis.documents import fetch as fetch_module, pdf_files
    from helpers import make_pdf
    lib = library
    assert fast_path.enforces(lib.run["budget"], "read")
    source = _pdf_source(lib)
    kept, changed = make_pdf(["SYNTHETIC kept bytes"]), make_pdf(["SYNTHETIC other bytes"])
    calls = []
    async def fetch_pdf(url):
        calls.append(url)
        return fetch_module.FetchResult("ok", kept, final_url="https://example.org/kept-final.pdf")
    flow = _fetch_flow(lib, tmp_path, fetch_pdf)
    step = lib.store.step(lib.run["id"], f"fetch:{source['id']}", "fetch_pdf")
    lib.store.finish_step(step["id"], "cancelled", error_code="run_stopped", output={"kept_download": {
        "sha256": hashlib.sha256(kept).hexdigest(), "byte_size": len(kept), "final_url": "https://example.org/old.pdf"}})
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / f"{hashlib.sha256(kept).hexdigest()}.pdf").write_bytes(changed)
    # The window between a separate identity check and the read: the check sees the old file.
    monkeypatch.setattr(pdf_files, "file_is_whole", lambda *args: True)
    asyncio.run(flow._fetch_pdf(lib.run, source))
    asset = lib.store.asset(lib.store.existing_step(lib.run["id"], f"fetch:{source['id']}")["output"]["asset_id"])
    assert calls == ["https://example.org/kept.pdf"]
    assert asset["sha256"] == hashlib.sha256(kept).hexdigest()


def test_a_lookup_copy_stopped_before_publication_is_tried_again_on_resume(library, tmp_path):
    """A stop after the looked-up copy was downloaded closes `other_copy` cancelled; the resumed attempt asks that
    route again instead of settling the work without text because every lookup answered (Sol, P1)."""
    from deixis.documents import fetch as fetch_module
    from helpers import make_pdf
    lib = library
    source = _pdf_source(lib, oa_pdf_url=None)
    copy = "https://repo.example/kept-copy.pdf"

    def handler(request):
        if "api.unpaywall.org" in request.url.host:
            location = {"url_for_pdf": copy, "url": "https://repo.example/item", "version": "publishedVersion"}
            return httpx.Response(200, json={"doi": "10.1/kept", "best_oa_location": location, "oa_locations": [location]})
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/kept", "display_name": "x", "locations": []})
        if "api.crossref.org" in request.url.host:
            return httpx.Response(200, json={"message": {"DOI": "10.1/kept", "link": []}})
        return httpx.Response(200, json={"results": [], "resultList": {"result": []}})

    calls = []
    async def fetch_pdf(url):
        calls.append(url)
        if len(calls) == 1:  # the stop arrives while the copy is on its way
            lib.store.update_run(lib.run["id"], status="pause_requested", pause_reason="user_requested")
        return fetch_module.FetchResult("ok", make_pdf(["SYNTHETIC kept copy"]), final_url=url)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            flow = _fetch_flow(lib, tmp_path, fetch_pdf, client)
            with pytest.raises(RunStopped):
                await flow._fetch_work_text(lib.run, source["id"])
            assert flow._other_copy_step(lib.run["id"], source["id"])["status"] == "cancelled"
            assert not lib.store.has_asset(source["id"])
            lib.store.update_run(lib.run["id"], status="running", pause_reason=None)
            return await flow._fetch_work_text(lib.run, source["id"])

    output = asyncio.run(check())
    assert lib.store.has_pdf_text(source["id"])
    assert output["code"] == fulltext.settled_code({"has_text": True})
    assert calls == [copy, copy]


# Two fields: a greenhouse-irrigation question, and a bakery-logistics record that answers nothing.
ON_TITLE = "SYNTHETIC irrigation scheduling in greenhouse tomato production"


OFF_TITLE = "SYNTHETIC bakery delivery rounds of a small town"


def decision(code, decided_by="code", stale=False):
    return {"reason_code": code, "decided_by": decided_by, "stale": stale}


def work(head, *, abstract=None, fulltext_code=None, selection=None, has_text=False, others=(), work_id=None):
    """One work of the plan: its head, whatever other versions it has, and the decisions they carry."""
    versions = [{"id": head, "has_text": has_text, "abstract": abstract, "fulltext": fulltext_code}]
    versions += [dict(other) for other in others]
    return {"work_id": work_id or f"wrk_{head}", "head": head, "versions": versions, "selection": selection}


CANDIDATE = decision("runs_agree_candidate", "model_agreement")


UNRESOLVED_HERE = decision("abstract_not_found")           # next step: fulltext_fetch


OUT_OF_SCOPE = decision("both_blocks_missing")


USER_INCLUDED = {"state": "included", "origin": "user"}


USER_EXCLUDED = {"state": "excluded", "origin": "user"}


def test_the_three_groups_are_fetched_in_order_and_ranked_inside_each_group():
    """The user's own works first, then code's candidates, then the unresolved works routed here (SW10.1)."""
    works = [
        work("u1", abstract=OUT_OF_SCOPE, selection=USER_INCLUDED),
        work("c1", abstract=CANDIDATE),
        work("c2", abstract=CANDIDATE),
        work("r1", abstract=UNRESOLVED_HERE),
    ]
    # The ranking put c2 in front of c1; the groups still come before the order inside them.
    plan = fulltext.fetch_plan(works, ["r1", "c2", "c1", "u1"], limit=10)
    assert plan["works"] == ["u1", "c2", "c1", "r1"]
    assert plan["not_reached"] == [] and plan["already_text"] == []


@pytest.mark.parametrize("skipped", [
    pytest.param(work("x1", abstract=CANDIDATE, selection=USER_EXCLUDED), id="skipped5"),  # the user excluded it
])
def test_a_work_outside_the_three_groups_is_not_fetched(skipped):
    assert fulltext.fetch_plan([skipped], [], limit=10) == {"works": [], "not_reached": [], "already_text": []}


def test_a_work_with_text_on_any_version_is_not_fetched_but_gets_its_code():
    """A user's upload, or a PDF an earlier run retrieved, is already text; nothing is requested for it."""
    preprint = {"id": "p1", "has_text": True, "abstract": None, "fulltext": None}
    plan = fulltext.fetch_plan([work("w1", abstract=CANDIDATE, others=[preprint])], [], limit=10)
    assert plan["already_text"] == ["w1"] and plan["works"] == []


def test_the_limit_cuts_the_list_and_drops_no_work():
    works = [work(f"c{n}", abstract=CANDIDATE) for n in range(6)] + [work("t1", abstract=CANDIDATE, has_text=True)]
    plan = fulltext.fetch_plan(works, [f"c{n}" for n in range(6)], limit=2)
    assert plan["works"] == ["c0", "c1"]
    assert plan["not_reached"] == ["c2", "c3", "c4", "c5"]
    assert set(plan["works"]) | set(plan["not_reached"]) | set(plan["already_text"]) == {w["head"] for w in works}
    assert not set(plan["works"]) & set(plan["not_reached"])


@pytest.mark.parametrize("attempt,code", [
    ({"has_text": True, "has_asset": True, "unanswered": 0}, "not_read_yet"),
])
def test_the_result_table_of_one_attempt(attempt, code):
    assert fulltext.settled_code(attempt) == code


def test_every_code_this_stage_writes_leaves_the_work_unresolved():
    """Nothing is included or excluded by a retrieval run (SW1.2): all three codes derive to `pending`."""
    from deixis.domain.reason_codes import reason
    from deixis.workflow.decisions import SELECTION_STATE

    for code in fulltext.OWNED_CODES:
        assert reason(code).stage == "fulltext" and reason(code).outcome == "unresolved"
        assert SELECTION_STATE[reason(code).outcome] == "pending"


def chained(head, **fields):
    return work(head, **fields) | {"chained": True}


VERSIONS = [{"doi": "10.1/synth.42", "title": ON_TITLE}, {"doi": "10.48550/arxiv.2601.00042", "title": ON_TITLE}]


@pytest.mark.parametrize("text,result", [
    ("SYNTHETIC preprint\nhttps://doi.org/10.1/synth.42\nbody", "doi"),
    (f"{OFF_TITLE}\n10.9/other.1", "unconfirmed"),
])
def test_the_identity_check_reads_the_head_of_the_text(text, result):
    assert identity.check(text, VERSIONS) == result


def test_the_identity_check_reads_no_further_than_the_first_pages():
    """A DOI quoted in a reference list is not this paper naming itself."""
    buried = "x " * identity.MATCH_TEXT_CHARS + "10.1/synth.42"
    assert identity.check(buried, VERSIONS) == "unconfirmed"


# Settings reads are cancelled when the page is left and end with a "did not answer" error when they take too long (E25).

PRELUDE = r"""
const fs = require('fs'), ts = require('typescript'), assert = require('assert');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, file);
const { limited, isLeft, gaveNoAnswer } = require('./src/readLimit.ts');
// A read that waits for its signal, as a fetch does: it rejects with an AbortError when the signal fires.
const hang = signal => new Promise((resolve, reject) => {
  const abort = () => reject(new DOMException('aborted', 'AbortError'));
  if (signal.aborted) return abort();  // a fetch given an already-aborted signal rejects at once
  signal.addEventListener('abort', abort, { once: true });
});
const late = () => Object.assign(new Error('late'), { code: 'read_timed_out' });
(async () => {
%s
  console.log('FINISHED');
})().catch(e => { console.error(e); process.exit(1) });
"""


def run_node(body: str):
    root = Path(__file__).resolve().parents[2]
    # Node exits 0 when the script ends with a promise still pending, so the script must say it ran to the end.
    result = subprocess.run(["node", "-e", PRELUDE % body], cwd=root / "web", capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "FINISHED" in result.stdout, "the script did not run to its end"


def test_a_hung_read_ends_with_the_did_not_answer_error_not_a_hang():
    run_node(r"""
const started = Date.now();
await assert.rejects(limited(hang, undefined, 40, late), e => e.code === 'read_timed_out' && gaveNoAnswer(e) && !isLeft(e));
assert(Date.now() - started < 1000);
// leaving first, then the time limit passing: the read stays a cancelled one
const leaving = new AbortController();
const read = limited(hang, leaving.signal, 40, late);
leaving.abort();
await assert.rejects(read, isLeft);
""")

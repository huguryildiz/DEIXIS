"""Synthetic persistence, pause/drain, selection and scope boundaries for the opt-in runner."""

import pytest
import asyncio

from deixis.workflow import small_batch
from deixis.workflow.flow import ResearchFlow
from test_small_batch_flow import app_for, client_of
from test_fetch_overlap_flow import discover, wait, output, work_steps


@pytest.mark.parametrize("stop", ["pause_requested", "paused", "failed", "prepare_error",
                                  "held_pause", "held_fail", "fetch_error"])
def test_pipeline_stop_during_next_preparation_blocks_reads_and_close(tmp_path, monkeypatch, stop):
    from fakes import FakeAdapter, valid_response, parse_step_input
    from deixis.workflow.flow import RunStopped

    freeze = small_batch.freeze_budget
    prepare = small_batch.execute_batch
    fetch = ResearchFlow._overlap_work
    started = release = None
    cut = False
    calls_at_stop = None
    next_active = False

    def budget(*args):
        result = freeze(*args)
        result["inspection"]["batch_size"] = 2
        return result

    class BlockingAdapter(FakeAdapter):
        async def run_step(self, *args, **kwargs):
            si = parse_step_input(args[2])
            if si["task_type"] == "fulltext_adjudication" and not started.is_set():
                started.set()
                await asyncio.wait_for(release.wait(), 5)
            return await super().run_step(*args, **kwargs)

    async def interrupt(flow, run, scope, vocabulary, listing, plan, key, **kwargs):
        nonlocal started, release, cut, calls_at_stop, next_active
        if started is None:
            started, release = asyncio.Event(), asyncio.Event()
        if plan["number"] == 1 and not cut:
            await asyncio.wait_for(started.wait(), 5)
            next_active = True
            if stop in ("held_pause", "held_fail", "fetch_error"):
                return await prepare(flow, run, scope, vocabulary, listing, plan, key, **kwargs)
            cut = True
            calls_at_stop = flow.store.run(run["id"])["usage"]["model_calls"]
            release.set()
            if stop == "prepare_error":
                raise RuntimeError("SYNTHETIC preparation failed")
            flow.store.update_run(run["id"], status=stop, pause_reason="SYNTHETIC stop")
            raise RunStopped
        return await prepare(flow, run, scope, vocabulary, listing, plan, key, **kwargs)

    async def stop_fetch(flow, run, wid):
        nonlocal cut, calls_at_stop
        if next_active and not cut and stop in ("held_pause", "held_fail", "fetch_error"):
            cut = True
            calls_at_stop = flow.store.run(run["id"])["usage"]["model_calls"]
            try:
                if stop == "fetch_error":
                    raise RuntimeError("SYNTHETIC fetch failed")
                (flow._pause if stop == "held_pause" else flow._fail)(
                    run["id"], "model_connection_not_ready" if stop == "held_pause" else "step_input_invalid")
            finally:
                release.set()
        await fetch(flow, run, wid)

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    monkeypatch.setattr(small_batch, "execute_batch", interrupt)
    monkeypatch.setattr(ResearchFlow, "_overlap_work", stop_fetch)
    app, fetcher = app_for(tmp_path, monkeypatch, 6, pdf=True, model_works=True,
                           adapter=BlockingAdapter(valid_response))
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="standard")
        assert cut
        assert run["status"] == ("paused" if stop in ("pause_requested", "held_pause") else
                                 "failed" if stop in ("prepare_error", "held_fail", "fetch_error") else stop), run
        assert run["usage"]["model_calls"] == calls_at_stop
        assert not [s for s in small_batch.steps(app.state.store, run_id)
                    if s["kind"] == "code:small_batch_close"]
        assert not app.state.store.conn.execute(
            "SELECT 1 FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'"
            " AND decided_by = 'model'", (rid,)).fetchone()
        if stop in ("pause_requested", "paused", "held_pause"):
            fetched = list(fetcher.calls)
            assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
            _, resumed = wait(client, rid, run_id)
            assert resumed["status"] == "completed", resumed
            assert fetcher.calls[:len(fetched)] == fetched
            assert len(fetcher.calls) == len(set(fetcher.calls)) == 6


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_read_order_retains_legacy_batch_start_snapshot(tmp_path, monkeypatch, version):
    freeze, unchanged = small_batch.freeze_budget, small_batch.unchanged_heads
    fetch = ResearchFlow._overlap_work
    fetched = False
    orders = []

    def budget(*args):
        result = freeze(*args)
        result["inspection"]["runner_version"] = version
        return result

    async def mark_fetch(flow, *args, **kwargs):
        nonlocal fetched
        await fetch(flow, *args, **kwargs)
        fetched = True

    def heads(*args):
        result = unchanged(*args)
        return list(reversed(result)) if fetched else result

    async def read(flow, run, scope, **kwargs):
        orders.append(kwargs["order"])

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    monkeypatch.setattr(small_batch, "unchanged_heads", heads)
    monkeypatch.setattr(ResearchFlow, "_overlap_work", mark_fetch)
    monkeypatch.setattr(ResearchFlow, "_fulltext_adjudication", read)
    app, _ = app_for(tmp_path, monkeypatch, 4, pdf=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        initial = output(app.state.store, run_id, small_batch.LIST_KEY)["order"]
        assert orders == [initial if version < 4 else list(reversed(initial))]


def test_between_batch_user_edit_is_absorbed_by_next_batch_guard(tmp_path, monkeypatch):
    freeze, save = small_batch.freeze_budget, small_batch.save_code
    changed = False

    def budget(*args):
        result = freeze(*args)
        result["inspection"]["batch_size"] = 2
        return result

    def edit(flow, run, key, kind, build):
        nonlocal changed
        result = save(flow, run, key, kind, build)
        if kind == "code:small_batch_close" and not changed:
            changed = True
            head = output(flow.store, run["id"], small_batch.LIST_KEY)["items"][-1]["head"]
            version = flow.store.conn.execute(
                "SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                (run["research_id"], head)).fetchone()[0]
            flow.store.set_user_selection(run["research_id"], head, "excluded", version, "SYNTHETIC between batches")
        return result

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    monkeypatch.setattr(small_batch, "save_code", edit)
    app, _ = app_for(tmp_path, monkeypatch, 6, fetch="off")
    with client_of(app) as client:
        _, _, _, run = discover(client, effort="standard")
        assert changed and run["status"] == "completed", run


def test_read_failure_stops_next_preparation_before_it_finishes(tmp_path, monkeypatch):
    freeze, prepare = small_batch.freeze_budget, small_batch.execute_batch
    preparing = None
    observed = False

    def budget(*args):
        result = freeze(*args)
        result["inspection"]["batch_size"] = 2
        return result

    async def fail_read(flow, *args, **kwargs):
        await asyncio.wait_for(preparing.wait(), 5)
        raise RuntimeError("SYNTHETIC reading failed")

    async def blocked_prepare(flow, run, scope, vocabulary, listing, plan, key, **kwargs):
        nonlocal preparing, observed
        if preparing is None:
            preparing = asyncio.Event()
        if plan["number"] == 1:
            preparing.set()
            async def stopped():
                while not flow._stop_requested(run["id"], run["scope_revision"]):
                    await asyncio.sleep(0)
            await asyncio.wait_for(stopped(), 5)
            observed = True
        return await prepare(flow, run, scope, vocabulary, listing, plan, key, **kwargs)

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    monkeypatch.setattr(small_batch, "execute_batch", blocked_prepare)
    monkeypatch.setattr(ResearchFlow, "_adjudication_call", fail_read)
    app, _ = app_for(tmp_path, monkeypatch, 6, pdf=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert observed and run["status"] == "failed", run
        assert "SYNTHETIC reading failed" in str(run["error"])
        assert not [s for s in small_batch.steps(app.state.store, run_id)
                    if s["kind"] == "code:small_batch_close"]


def test_shared_pair_reservation_survives_first_send_and_blocks_competing_pair():
    from types import SimpleNamespace
    used = 0
    run = {"id": "synthetic", "budget": {"max_model_calls": 3}}
    flow = object.__new__(ResearchFlow)
    flow.store = SimpleNamespace(run=lambda _: {"usage": {"model_calls": used}})
    flow._small_batch_guard = {"run_id": run["id"], "reserved_calls": set()}
    assert flow._reserve_model_pair(run, ["read:1", "read:2"], 0, 0)
    assert not flow._reserve_model_pair(run, ["abstract:1", "abstract:2"], 0, 0)
    flow._small_batch_guard["reserved_calls"].discard("read:1")
    used = 1
    assert not flow._reserve_model_pair(run, ["abstract:1", "abstract:2"], 0, 0)
    assert not flow._model_calls_left(run, len(flow._small_batch_guard["reserved_calls"]) + 2)
    flow._small_batch_guard["reserved_calls"].discard("read:2")
    used = 2
    assert flow._reserve_model_pair(run, ["resume:2"], 0, 2)
    assert not flow._reserve_model_pair(run, ["other:1"], 0, 2)


def test_mid_batch_restart_reuses_completed_model_calls_and_persisted_fetches(tmp_path, monkeypatch):
    from fakes import FakeAdapter, valid_response
    from test_fetch_overlap_flow import after_the_file, run_until_crash, research
    from deixis.workflow import fulltext

    monkeypatch.setattr(fulltext, "FULLTEXT_FETCH_PARALLEL", 1)
    adapter = FakeAdapter(valid_response)
    app, fetcher = app_for(tmp_path, monkeypatch, 30, pdf=True, model_works=True,
                           adapter=adapter, start_worker=False)
    with client_of(app) as client:
        rid = research(client, effort="standard")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        disarm = after_the_file(app, fetcher, monkeypatch)
        assert run_until_crash(client, app, run_id)
        store = app.state.store
        unknown = [s for s in work_steps(store, run_id) if s["status"] == "outcome_unknown"]
        assert unknown
        assert not [s for s in small_batch.steps(store, run_id) if s["kind"] == "code:small_batch_close"]
        settled = {s["operation_key"]: s["attempt"] for s in store.run_steps(run_id)
                   if s["kind"].startswith("model:") and s["status"] == "succeeded"}
        before = list(adapter.calls)
        fetched = list(fetcher.calls)
        assert fetched and any(c["task_type"] == "abstract_screening" for c in before)
        disarm()
        assert not run_until_crash(client, app, run_id)
        assert store.run(run_id)["status"] == "completed"
        assert all(store.existing_step(run_id, key)["attempt"] == attempt for key, attempt in settled.items())
        assert len(fetcher.calls) == len(set(fetcher.calls)) == 30
        assert fetcher.calls[:len(fetched)] == fetched
        # Four abstract calls (20+10, two readings); only adjudication calls are added after this cut.
        assert sum(c["task_type"] == "abstract_screening" for c in adapter.calls) == 4
        assert sum(c["task_type"] == "fulltext_adjudication" for c in adapter.calls) == 60
        assert adapter.calls[:len(before)] == before


@pytest.mark.parametrize("point", ["plan", "close", "second_plan"])
@pytest.mark.parametrize("legacy", [False, 1, 3])
def test_resume_keeps_manifest_and_successful_calls(tmp_path, monkeypatch, point, legacy):
    freeze = small_batch.freeze_budget
    if legacy:
        def old_budget(*args):
            budget = freeze(*args)
            budget["inspection"].update(runner_version=legacy, batch_size=30 if legacy == 1 else 40)
            return budget
        monkeypatch.setattr(small_batch, "freeze_budget", old_budget)
    original = small_batch.save_code
    paused = False

    def cut(flow, run, key, kind, build):
        nonlocal paused
        result = original(flow, run, key, kind, build)
        matches = key.endswith(":1:plan") if point == "second_plan" else key.endswith(f":{point}")
        if not paused and matches:
            paused = True
            flow.store.update_run(run["id"], status="pause_requested")
        return result

    monkeypatch.setattr(small_batch, "save_code", cut)
    app, fetcher = app_for(tmp_path, monkeypatch, 60, pdf=True)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "paused", run
        frozen = output(app.state.store, run_id, small_batch.LIST_KEY)
        calls = list(fetcher.calls)
        settled = [s for s in work_steps(app.state.store, run_id) if s["status"] == "succeeded"]
        assert not [s for s in work_steps(app.state.store, run_id) if s["status"] == "running"]
        monkeypatch.setattr(small_batch, "freeze_budget", freeze)
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, resumed = wait(client, rid, run_id)
        assert resumed["status"] == "completed", resumed
        assert output(app.state.store, run_id, small_batch.LIST_KEY) == frozen
        assert len(fetcher.calls) == len(set(fetcher.calls)) == 60
        assert all(app.state.store.existing_step(run_id, s["operation_key"])["attempt"] == s["attempt"] for s in settled)
        assert fetcher.calls[:len(calls)] == calls
        plans = [s["output"] for s in small_batch.steps(app.state.store, run_id) if s["kind"] == "code:small_batch_plan"]
        assert [len(p["work_ids"]) for p in plans] == ([30, 30] if legacy == 1 else [40, 20])


def test_list_publication_rolls_back_atomically(tmp_path, monkeypatch):
    original = small_batch.build_list

    def broken(manifest):
        original(manifest)
        raise RuntimeError("SYNTHETIC list publication crash")

    monkeypatch.setattr(small_batch, "build_list", broken)
    app, _ = app_for(tmp_path, monkeypatch, 4)
    with client_of(app) as client:
        _, run_id, _, run = discover(client)
        assert run["status"] == "failed"
        step = app.state.store.existing_step(run_id, small_batch.LIST_KEY)
        assert step["status"] == "pending" and step["output"] is None
        assert not [s for s in app.state.store.run_steps(run_id) if s["kind"] == "code:small_batch_plan"]


def test_user_change_during_fetch_drains_then_pauses(tmp_path, monkeypatch):
    original = ResearchFlow._overlap_work
    changed = False

    async def change(flow, run, wid):
        nonlocal changed
        if not changed:
            changed = True
            head = flow.store.work_heads(run["research_id"])[wid]
            version = flow.store.conn.execute(
                "SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                (run["research_id"], head)).fetchone()[0]
            flow.store.set_user_selection(run["research_id"], head, "excluded", version, "SYNTHETIC exclusion")
        await original(flow, run, wid)

    monkeypatch.setattr(ResearchFlow, "_overlap_work", change)
    app, fetcher = app_for(tmp_path, monkeypatch, 60, pdf=True)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "paused" and run["pause_reason"] == "selection_changed", run
        assert not [s for s in work_steps(app.state.store, run_id) if s["status"] == "running"]
        assert len(fetcher.calls) <= 4
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, resumed = wait(client, rid, run_id)
        assert resumed["status"] == "completed", resumed
        assert len(fetcher.calls) == len(set(fetcher.calls))


def test_scope_change_prevents_new_revision_decisions(tmp_path, monkeypatch):
    original = ResearchFlow._overlap_work
    changed = False

    async def change(flow, run, wid):
        nonlocal changed
        if not changed:
            changed = True
            research = flow.store.research(run["research_id"])
            flow.store.revise_scope(run["research_id"], research["version"], "SYNTHETIC revised question", None)
        await original(flow, run, wid)

    monkeypatch.setattr(ResearchFlow, "_overlap_work", change)
    app, _ = app_for(tmp_path, monkeypatch, 60, pdf=True)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "cancelled", run
        assert not app.state.store.conn.execute(
            "SELECT 1 FROM stage_decisions WHERE research_id = ? AND scope_revision = 2", (rid,)).fetchone()
        assert not [s for s in work_steps(app.state.store, run_id) if s["status"] == "running"]


def test_abstract_reuse_checks_the_stored_source_text(tmp_path, monkeypatch):
    from fakes import FakeAdapter, valid_response
    from test_abstract_flow import rerun

    adapter = FakeAdapter(valid_response)
    app, _ = app_for(tmp_path, monkeypatch, 4, model_works=True, fetch="off", adapter=adapter)
    with client_of(app) as client:
        rid, _, _, first = discover(client, effort="standard")
        assert first["status"] == "completed", first
        count = sum(c["task_type"] == "abstract_screening" for c in adapter.calls)
        _, _, second = rerun(client, rid)
        assert second["status"] == "completed", second
        assert sum(c["task_type"] == "abstract_screening" for c in adapter.calls) == count
        app.state.store.conn.execute(
            "UPDATE source_versions SET title = title || ' SYNTHETIC changed title.'")
        _, _, third = rerun(client, rid)
        assert third["status"] == "completed", third
        assert sum(c["task_type"] == "abstract_screening" for c in adapter.calls) == count + 2


def test_changed_frozen_source_is_blocked_on_resume_without_fetching_it(tmp_path, monkeypatch):
    original = small_batch.save_code
    cut_once = False

    def cut(flow, run, key, kind, build):
        nonlocal cut_once
        result = original(flow, run, key, kind, build)
        if not cut_once and kind == "code:small_batch_plan":
            cut_once = True
            flow.store.update_run(run["id"], status="pause_requested")
        return result

    monkeypatch.setattr(small_batch, "save_code", cut)
    app, fetcher = app_for(tmp_path, monkeypatch, 4, pdf=True)
    with client_of(app) as client:
        rid, run_id, _, paused = discover(client, effort="standard")
        assert paused["status"] == "paused", paused
        frozen = output(app.state.store, run_id, small_batch.LIST_KEY)
        item = frozen["items"][0]
        app.state.store.conn.execute("UPDATE source_versions SET title = title || ' SYNTHETIC changed' WHERE id = ?",
                                     (item["head"],))
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, resumed = wait(client, rid, run_id)
        assert resumed["status"] == "completed", resumed
        current = next(i for i in resumed["inspection_progress"]["items"] if i["head"] == item["head"])
        assert current["blocker"] == "source_changed" and not current["processed"]
        assert len(fetcher.calls) == 3
        assert output(app.state.store, run_id, small_batch.LIST_KEY) == frozen


@pytest.mark.parametrize("limit", [None, 41])
def test_carried_group_crash_reuses_hash_keys_preserves_order_and_partial_tail(tmp_path, monkeypatch, limit):
    from fakes import FakeAdapter, valid_response
    from test_fetch_overlap_flow import Crash, run_until_crash, research
    from deixis.domain import canonical

    freeze = small_batch.freeze_budget

    def budget(*args):
        result = freeze(*args)
        # A deliberately non-divisible boundary exercises carrying with dense records.
        result["inspection"]["batch_size"] = 30
        if limit is not None:
            result["inspection"]["abstract_limit"] = limit
        return result

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    original = ResearchFlow._abstract_call
    cut = False
    reads = 0

    async def crash_after_read(flow, *args, **kwargs):
        nonlocal cut, reads
        result = await original(flow, *args, **kwargs)
        reads += 1
        if not cut and reads == 3:
            cut = True
            raise Crash()
        return result

    monkeypatch.setattr(ResearchFlow, "_abstract_call", crash_after_read)
    adapter = FakeAdapter(valid_response)
    app, _ = app_for(tmp_path, monkeypatch, 61, model_works=True, fetch="off",
                     adapter=adapter, start_worker=False)
    with client_of(app) as client:
        rid = research(client, effort="standard")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        assert run_until_crash(client, app, run_id)
        store = app.state.store
        paid = {s["operation_key"]: s["attempt"] for s in store.run_steps(run_id)
                if s["kind"] == "model:abstract_screening" and s["status"] == "succeeded"}
        assert paid
        assert not run_until_crash(client, app, run_id)
        assert store.run(run_id)["status"] == "completed"
        assert all(store.existing_step(run_id, key)["attempt"] == attempt for key, attempt in paid.items())
        records = small_batch.steps(store, run_id)
        groups = [g for s in records if s["kind"] == "code:small_batch_abstract_groups"
                  for g in s["output"]["groups"]]
        assert [len(g["sources"]) for g in groups] == ([20, 20, 20, 1] if limit is None else [20, 20, 1])
        planned = [svid for s in records if s["operation_key"].endswith(":abstract_stage")
                   for batch in s["output"]["batches"] for svid in batch]
        assert [svid for group in groups for svid in group["sources"]] == planned
        assert all(g["key"].endswith(canonical.sha256_hex(g["sources"])) for g in groups)
        listing = output(store, run_id, small_batch.LIST_KEY)
        positions = {svid: item["position"] for item in listing["items"] for svid in item["versions"]}
        assert positions[groups[1]["sources"][0]] <= 30 < positions[groups[1]["sources"][-1]]
        calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        assert len(calls) == 2 * len(groups)
        import json
        by_candidate = {c["candidate_id"]: c["source_version_id"] for c in store.candidates(rid)}
        supplied = [json.loads(row[0])["candidates"] for row in store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE run_id = ? AND task_type = 'abstract_screening'"
            " ORDER BY created_at, id", (run_id,))]
        assert [[by_candidate[c["candidate_id"]] for c in candidates] for candidates in supplied] == [
            g["sources"] for g in groups for _ in range(2)]

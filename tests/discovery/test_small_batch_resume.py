"""Synthetic persistence, pause/drain, selection and scope boundaries for the opt-in runner."""

import pytest

from deixis.workflow import small_batch
from deixis.workflow.flow import ResearchFlow
from test_small_batch_flow import app_for, client_of
from test_fetch_overlap_flow import discover, wait, output, work_steps


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


@pytest.mark.parametrize("point", ["plan", "close"])
def test_resume_keeps_manifest_and_successful_calls(tmp_path, monkeypatch, point):
    original = small_batch.save_code
    paused = False

    def cut(flow, run, key, kind, build):
        nonlocal paused
        result = original(flow, run, key, kind, build)
        if not paused and key.endswith(f":{point}"):
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
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, resumed = wait(client, rid, run_id)
        assert resumed["status"] == "completed", resumed
        assert output(app.state.store, run_id, small_batch.LIST_KEY) == frozen
        assert len(fetcher.calls) == len(set(fetcher.calls)) == 60
        assert all(app.state.store.existing_step(run_id, s["operation_key"])["attempt"] == s["attempt"] for s in settled)
        assert fetcher.calls[:len(calls)] == calls


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

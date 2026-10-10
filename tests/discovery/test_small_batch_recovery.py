"""Synthetic small-batch fetch recovery, frozen limits and coordinated stop evidence."""
import asyncio
from contextlib import contextmanager

import pytest

from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.domain import canonical
from deixis.workflow import fast_path, fulltext, small_batch
from deixis.workflow.background_fetch import FetchSlots
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import ResearchFlow
from fakes import FakeAdapter, valid_response
from test_abstract_flow import ON_TOPIC, OFF_TOPIC, OFF_ABSTRACT, QUESTION, client_of, records_of, work as abstract_work
from test_adjudication_flow import wait, adj_calls
from test_fetch_overlap_flow import (app_for, Crash, run_until_crash, work_steps, events,
                                     fulltext_codes, SlowFetcher)
from test_fulltext_flow import Fetcher, Transport, work, named_pdf, ok
from batch_outputs import stage_output

@contextmanager
def session(app):
    client = client_of(app)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)



def seeded_app(tmp_path, monkeypatch, n=3, **kwargs):
    records = [work(i, title=ON_TOPIC, pdf_url=f"https://example.org/w{i}.pdf") for i in range(1, n + 1)]
    fetcher = Fetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}"))
                       for i in range(1, n + 1)})
    app = app_for(tmp_path, monkeypatch, Transport(records), fetcher, **kwargs)
    return app, fetcher


def serial(app):
    """One work fetched at a time: the fast read's fetch slots, not `FULLTEXT_FETCH_PARALLEL`, bound it."""
    app.state.worker.flow.deps.fetch_slots = FetchSlots(1)


def manual_answer(monkeypatch):
    """No automatic answer after discovery: it would hold the research's answer slot, and a later discovery or the
    person's own answer request would meet it."""
    freeze = fast_path.freeze_budget
    def policy(*args):
        frozen = freeze(*args)
        frozen.pop("policy_hash")
        frozen["auto_answer"] = False
        return frozen | {"policy_hash": canonical.sha256_hex(frozen)}
    monkeypatch.setattr(fast_path, "freeze_budget", policy)


def pause_after_settled(app, run_id, n):
    """The user's pause once `n` works have settled: with one fetch slot, no other work's file is on its way."""
    flow, settled = app.state.worker.flow, []

    async def overlap(run, wid):
        await type(flow)._overlap_work(flow, run, wid)
        settled.append(wid)
        if len(settled) == n:
            flow.store.update_run(run_id, event="run_pause_requested", status="pause_requested", pause_reason="user_requested")
    flow._overlap_work = overlap


def queue(client):
    rid = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                               "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id


@pytest.mark.parametrize("point", ["before_answer", "after_file", "after_code", "before_close", "completion_event", "three_crashes"])
def test_fetch_crash_recovery_preserves_settled_work_and_frozen_plan(tmp_path, monkeypatch, point):
    app, fetcher = seeded_app(tmp_path, monkeypatch, start_worker=False)
    with session(app) as client:
        serial(app)
        store = app.state.store
        armed = True
        dead = False

        def crash():
            nonlocal armed, dead
            if armed:
                armed = point == "three_crashes"
                dead = True
                raise Crash

        flow = app.state.worker.flow

        async def gate(run, wid):
            # The fast read drains its other fetch tasks before the crash leaves it; a dead process starts nothing.
            if dead:
                raise Crash
            return await type(flow)._overlap_work(flow, run, wid)
        flow._overlap_work = gate

        def restart():
            nonlocal dead
            crashed = run_until_crash(client, app, run_id)
            dead = False
            return crashed

        if point in ("before_answer", "three_crashes"):
            def hook(fetcher, url):
                if url == "https://example.org/w1.pdf":
                    crash()
            fetcher.hook = hook
        elif point == "after_file":
            add = store.add_asset_with_pages
            def after_file(*args, **kwargs):
                result = add(*args, **kwargs)
                crash()
                return result
            monkeypatch.setattr(store, "add_asset_with_pages", after_file)
        elif point == "after_code":
            original = ResearchFlow._overlap_work
            async def after_code(self, run, wid):
                await original(self, run, wid)
                crash()
            monkeypatch.setattr(ResearchFlow, "_overlap_work", after_code)
        elif point == "completion_event":
            event = store._event
            def completing(rid, type_, payload, run_id=None):
                if type_ == "run_completed":
                    crash()
                return event(rid, type_, payload, run_id)
            monkeypatch.setattr(store, "_event", completing)
        else:
            save = small_batch.save_code
            def before_close(flow, run, key, kind, build):
                if kind == "code:small_batch_close":
                    crash()
                return save(flow, run, key, kind, build)
            monkeypatch.setattr(small_batch, "save_code", before_close)
        rid, run_id = queue(client)
        assert restart()
        listing = store.existing_step(run_id, small_batch.LIST_KEY)
        baseline = stage_output(store, run_id, "baseline")
        settled = {s["operation_key"] for s in work_steps(store, run_id) if s["status"] == "succeeded"}
        for _ in range(4):
            if not restart():
                break
        assert store.run(run_id)["status"] == "completed"
        assert store.existing_step(run_id, small_batch.LIST_KEY) == listing
        assert stage_output(store, run_id, "baseline") == baseline
        steps = work_steps(store, run_id)
        assert settled <= {s["operation_key"] for s in steps if s["status"] == "succeeded"}
        assert len(steps) == 3
        assert fetcher.calls.count("https://example.org/w2.pdf") == 1
        assert fetcher.calls.count("https://example.org/w3.pdf") == 1
        if point == "three_crashes":
            failed = [s for s in steps if s["status"] == "failed"]
            assert len(failed) == 1 and failed[0]["error_code"] == "fetch_not_settled"
            assert failed[0]["attempt"] == fulltext.FULLTEXT_WORK_ATTEMPTS == 3
            assert fetcher.calls.count("https://example.org/w1.pdf") == 3
            assert fulltext_codes(store, rid)["W1"] is None
        else:
            assert all(s["status"] == "succeeded" for s in steps), [(s["status"], s["attempt"]) for s in steps]
            assert set(fulltext_codes(store, rid).values()) == {"not_read_yet"}
            assert fetcher.calls.count("https://example.org/w1.pdf") <= (2 if point == "before_answer" else 1)


@pytest.mark.parametrize("stop", ["user_pause", "model_pause", "scope_revision"])
def test_stop_is_recorded_after_fetches_drain_and_resume_reuses_settled_work(tmp_path, monkeypatch, stop):
    holder = {"active": 0, "stopped": False, "observed": []}
    records = [work(i, title=ON_TOPIC, pdf_url=f"https://example.org/w{i}.pdf") for i in range(1, 3)]
    records.extend(abstract_work(i) for i in range(101, 104))

    def fail(si):
        if si["task_type"] == "abstract_screening" and stop == "model_pause" and not holder["stopped"]:
            holder["stopped"] = True
            holder["observed"].append(holder["active"])
            return ModelStepResult("unavailable", error="SYNTHETIC model disconnected")
        return None

    adapter = FakeAdapter(valid_response, fail=fail, delay=0.02)
    fetcher = SlowFetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}"))
                           for i in range(1, 3)})
    call = SlowFetcher.__call__

    async def delayed(self, url):
        holder["active"] += 1
        try:
            await asyncio.sleep(0.08)
            store = holder["app"].state.store
            row = store.conn.execute("SELECT id FROM runs WHERE status IN ('running', 'pause_requested')").fetchone()
            if not holder["stopped"] and stop != "model_pause":
                holder["stopped"] = True
                if stop == "user_pause":
                    store.update_run(row[0], event="run_pause_requested", status="pause_requested", pause_reason="user_requested")
                else:
                    rid = store.run(row[0])["research_id"]
                    store.revise_scope(rid, store.research(rid)["version"], QUESTION + " SYNTHETIC revised", None)
            if row:
                holder["observed"].append(store.run(row[0])["status"])
            return await call(self, url)
        finally:
            holder["active"] -= 1

    monkeypatch.setattr(SlowFetcher, "__call__", delayed)
    app = app_for(tmp_path, monkeypatch, Transport(records), fetcher, adapter=adapter)
    holder["app"] = app
    with session(app) as client:
        store = app.state.store
        event = store._event
        def record(rid, type_, payload, run_id=None):
            if type_ == "run_paused":
                assert holder["active"] == 0
            return event(rid, type_, payload, run_id)
        monkeypatch.setattr(store, "_event", record)
        rid, run_id = queue(client)
        stopped = wait(client, rid, run_id)[1]
        assert holder["active"] == 0
        assert not [s for s in store.run_steps(run_id) if s["status"] == "running"]
        if stop == "scope_revision":
            assert (stopped["status"], stopped["pause_reason"]) == ("cancelled", "scope_revised")
            assert not store.conn.execute(
                "SELECT 1 FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
                " WHERE d.research_id = ? AND s.kind = 'code:fulltext_work' AND s.status = 'cancelled'", (rid,)).fetchone()
            late = [s for s in work_steps(store, run_id) if s["output"].get("work_id") in
                    {store.source(records_of(store, rid)[key])["work_id"] for key in ("W1", "W2")}]
            assert len(late) == 2 and all(s["status"] == "cancelled" for s in late)
            return
        assert stopped["status"] == "paused", stopped
        assert len(events(store, rid, "run_paused")) == 1
        assert "paused" not in holder["observed"]
        if stop == "model_pause":
            assert holder["observed"][0] > 0
        settled_urls = list(fetcher.calls)
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        completed = wait(client, rid, run_id)[1]
        assert completed["status"] == "completed", completed
        assert all(fetcher.calls.count(url) == 1 for url in settled_urls)


def test_fetch_limit_is_frozen_on_resume_and_later_discovery_takes_tail(tmp_path, monkeypatch):
    # The fast read's work limit is its frozen K; text already here counts in the same K slots.
    freeze = fast_path.freeze_budget
    limit = 2
    def bounded(budget, effort):
        policy = freeze(budget, effort)
        policy.pop("policy_hash")
        policy["K"] = limit
        policy["auto_answer"] = False  # no answer run queued between the two discoveries
        return policy | {"policy_hash": canonical.sha256_hex(policy)}
    monkeypatch.setattr(fast_path, "freeze_budget", bounded)
    app, fetcher = seeded_app(tmp_path, monkeypatch, start_worker=False)
    with session(app) as client:
        serial(app)
        rid, run_id = queue(client)
        store = app.state.store
        budget = store.run(run_id)["budget"]
        limit = 3
        pause_after_settled(app, run_id, 1)
        assert not run_until_crash(client, app, run_id)
        assert store.run(run_id)["status"] == "paused"
        assert store.resume_run(run_id)["status"] == "queued"
        assert not run_until_crash(client, app, run_id)
        assert store.run(run_id)["budget"] == budget
        assert len(fetcher.calls) == 2
        assert len(work_steps(store, run_id)) == budget["fast_path"]["K"] == 2
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        assert not run_until_crash(client, app, second)
        assert len(fetcher.calls) == 3 and len(set(fetcher.calls)) == 3
        assert set(fulltext_codes(store, rid).values()) == {"not_read_yet"}


def test_timeout_is_retried_but_refusal_is_settled_without_a_model_read(tmp_path, monkeypatch):
    manual_answer(monkeypatch)
    app, fetcher = seeded_app(tmp_path, monkeypatch, n=2)
    fetcher.answers["https://example.org/w1.pdf"] = FetchResult("timeout", error="SYNTHETIC timeout")
    fetcher.answers["https://example.org/w2.pdf"] = FetchResult("http_error", http_status=403)
    with session(app) as client:
        rid, run_id = queue(client)
        assert wait(client, rid, run_id)[1]["status"] == "completed"
        store = app.state.store
        assert fulltext_codes(store, rid) == {"W1": None, "W2": "no_fulltext"}
        assert {row[0] for row in store.conn.execute("SELECT state FROM selections WHERE research_id = ?", (rid,))} == {"pending"}
        failed = [s for s in work_steps(store, run_id) if s["status"] == "failed"]
        assert len(failed) == 1 and failed[0]["error_code"] == "fetch_not_settled"
        fetcher.answers["https://example.org/w1.pdf"] = ok(named_pdf("10.1/oa.1"))
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        assert wait(client, rid, second)[1]["status"] == "completed"
        assert fetcher.calls.count("https://example.org/w1.pdf") == 2
        assert fetcher.calls.count("https://example.org/w2.pdf") == 1
        assert fulltext_codes(store, rid)["W1"] == "not_read_yet"
        assert not adj_calls(app.state.adapters["fake"], second)


@pytest.mark.parametrize("choice", ["human_decision", "user_selection"])
def test_prior_user_choices_govern_abstract_fetch_and_reading(tmp_path, monkeypatch, choice):
    records = [work(i, pdf_url=f"https://example.org/w{i}.pdf") for i in range(1, 4)]
    fetcher = Fetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}")) for i in range(1, 4)})
    app = app_for(tmp_path, monkeypatch, Transport(records), fetcher, reading="auto")
    freeze = small_batch.freeze_list
    def chosen(flow, run, scope, vocabulary):
        store = flow.store
        records = records_of(store, run["research_id"])
        if choice == "human_decision":
            decisions = DecisionStore(store)
            decisions.record(run["research_id"], records["W1"], "human_include")
            decisions.record(run["research_id"], records["W2"], "human_criterion_not_met")
            for source in (records["W1"], records["W2"]):
                decisions.derive_selection(run["research_id"], store.source(source)["work_id"])
        else:
            for source, state in ((records["W1"], "included"), (records["W2"], "excluded")):
                version = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                             (run["research_id"], source)).fetchone()[0]
                store.set_user_selection(run["research_id"], source, state, version, "SYNTHETIC prior selection")
        return freeze(flow, run, scope, vocabulary)
    monkeypatch.setattr(small_batch, "freeze_list", chosen)
    with session(app) as client:
        rid, run_id = queue(client)
        assert wait(client, rid, run_id)[1]["status"] == "completed"
        store = app.state.store
        records = records_of(store, rid)
        assert "https://example.org/w2.pdf" not in fetcher.calls
        assert store.conn.execute("SELECT state FROM selections WHERE research_id = ? AND source_version_id = ?",
                                  (rid, records["W1"])).fetchone()[0] == "included"
        if choice == "human_decision":
            assert "https://example.org/w1.pdf" not in fetcher.calls
            from test_queue_api import sent_records
            abstract_calls = [c for c in app.state.adapters["fake"].calls if c["task_type"] == "abstract_screening"]
            assert abstract_calls
            assert all(set(sent_records(store, c)).isdisjoint({records["W1"], records["W2"]}) for c in abstract_calls)
            assert all(store.step_input_payload(c["step_input_id"])["adjudication_target"]["source_id"]
                       not in (records["W1"], records["W2"]) for c in adj_calls(app.state.adapters["fake"], run_id))
        else:
            assert fetcher.calls[0] == "https://example.org/w1.pdf"


def test_user_choice_during_fetch_survives_pause_and_frozen_list_on_resume(tmp_path, monkeypatch):
    app, fetcher = seeded_app(tmp_path, monkeypatch)
    def decide(fetcher, url):
        if len(fetcher.calls) == 1:
            store = app.state.store
            run = store.conn.execute("SELECT research_id FROM runs WHERE kind = 'discovery'").fetchone()
            source = records_of(store, run[0])["W1"]
            DecisionStore(store).record(run[0], source, "human_not_sure")
    fetcher.hook = decide
    with session(app) as client:
        rid, run_id = queue(client)
        paused = wait(client, rid, run_id)[1]
        assert (paused["status"], paused["pause_reason"]) == ("paused", "selection_changed")
        store = app.state.store
        listing = store.existing_step(run_id, small_batch.LIST_KEY)
        source = records_of(store, rid)["W1"]
        assert DecisionStore(store).current(rid, source, "fulltext")["reason_code"] == "human_not_sure"
        url = {svid: f"https://example.org/w{key[1:]}.pdf" for key, svid in records_of(store, rid).items()}
        settled = {url[s["output"]["head"]] for s in work_steps(store, run_id) if s["status"] == "succeeded"}
        fetcher.hook = None
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert wait(client, rid, run_id)[1]["status"] == "completed"
        assert store.existing_step(run_id, small_batch.LIST_KEY) == listing
        # A work settled before the pause is not asked again. (A file still on its way when the fast read stopped
        # is asked once more: see test_stop_is_recorded_after_fetches_drain_and_resume_reuses_settled_work.)
        assert all(fetcher.calls.count(u) == 1 for u in settled)
        assert DecisionStore(store).current(rid, source, "fulltext")["reason_code"] == "human_not_sure"


def test_pause_resume_progress_matches_uninterrupted_run(tmp_path, monkeypatch):
    results = []
    for paused in (False, True):
        app, fetcher = seeded_app(tmp_path / str(paused), monkeypatch, start_worker=False)
        with session(app) as client:
            serial(app)
            rid, run_id = queue(client)
            store = app.state.store
            if paused:
                pause_after_settled(app, run_id, 2)
            assert not run_until_crash(client, app, run_id)
            if paused:
                assert store.run(run_id)["status"] == "paused"
                assert store.resume_run(run_id)["status"] == "queued"
                assert not run_until_crash(client, app, run_id)
            assert store.run(run_id)["status"] == "completed"
            progress = small_batch.stored_progress(store, store.run(run_id))
            assert len(work_steps(store, run_id)) == 3
            assert len(fetcher.calls) == len(set(fetcher.calls)) == 3
            results.append((progress["counts"], sorted(fulltext_codes(store, rid).values()), sorted(fetcher.calls)))
    assert results[0] == results[1]


@pytest.mark.parametrize("boundary", ["work", "coordinator"])
def test_fetch_errors_are_isolated_per_work_and_fatal_outside_work(tmp_path, monkeypatch, boundary):
    app, fetcher = seeded_app(tmp_path, monkeypatch)
    name = "_fetch_work_text" if boundary == "work" else "_overlap_work"
    original = getattr(ResearchFlow, name)
    async def broken(self, run, target):
        if boundary == "coordinator" or self.store.source(target)["doi"] == "10.1/oa.1":
            raise RuntimeError("SYNTHETIC shared fetch error")
        return await original(self, run, target)
    monkeypatch.setattr(ResearchFlow, name, broken)
    with session(app) as client:
        rid, run_id = queue(client)
        failed = wait(client, rid, run_id)[1]
        if boundary == "work":
            assert failed["status"] == "completed"
            steps = work_steps(app.state.store, run_id)
            assert len([s for s in steps if s["error_code"] == "fulltext_work_failed"]) == 1
            assert len([s for s in steps if s["status"] == "succeeded"]) == 2
        else:
            assert (failed["status"], failed["pause_reason"]) == ("failed", "internal_error")
            assert not fetcher.calls
        assert not [s for s in app.state.store.run_steps(run_id) if s["kind"] == "model:fulltext_adjudication"]


def test_new_user_priority_after_restart_stays_within_frozen_list(tmp_path, monkeypatch):
    records = [work(i, title=ON_TOPIC, pdf_url=f"https://example.org/w{i}.pdf") for i in range(1, 4)]
    records.append(work(4, title=OFF_TOPIC, abstract=OFF_ABSTRACT, pdf_url="https://example.org/w4.pdf"))
    fetcher = Fetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}")) for i in range(1, 5)})
    app = app_for(tmp_path, monkeypatch, Transport(records), fetcher, start_worker=False)
    save = small_batch.save_code
    armed = True
    def cut(flow, run, key, kind, build):
        nonlocal armed
        if kind == "code:small_batch_close" and armed:
            armed = False
            raise Crash
        return save(flow, run, key, kind, build)
    monkeypatch.setattr(small_batch, "save_code", cut)
    with session(app) as client:
        rid, run_id = queue(client)
        assert run_until_crash(client, app, run_id)
        store = app.state.store
        listing = store.existing_step(run_id, small_batch.LIST_KEY)
        source = records_of(store, rid)["W4"]
        version = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?", (rid, source)).fetchone()[0]
        store.set_user_selection(rid, source, "included", version, "SYNTHETIC choice while worker is down")
        from dataclasses import replace
        from test_stage_decisions import record
        outsider, _ = store.upsert_provider_source("openalex", replace(record("outside-list"), title=ON_TOPIC,
                                                    oa_pdf_url="https://example.org/w5.pdf"), None)
        store.add_to_corpus(rid, outsider, "search", selection_state="included", selection_origin="user")
        assert not run_until_crash(client, app, run_id)
        assert store.run(run_id)["status"] == "completed"
        assert store.existing_step(run_id, small_batch.LIST_KEY) == listing
        assert "https://example.org/w5.pdf" not in fetcher.calls
        assert {s["operation_key"].split(":", 1)[1] for s in work_steps(store, run_id)} <= {
            item["work_id"] for item in listing["output"]["items"]}


def test_answer_blocks_active_discovery_and_requires_its_completed_revision(tmp_path, monkeypatch):
    from test_criterion_passage_flow import page_source
    manual_answer(monkeypatch)
    app, fetcher = seeded_app(tmp_path, monkeypatch, start_worker=False)
    with session(app) as client:
        rid, run_id = queue(client)
        store = app.state.store
        page_source(store, rid, "SYNTHETIC included", ["SYNTHETIC exercise lowers fatigue."], "SYNTHETIC exercise.")
        blocked = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert blocked.status_code == 409
        store.update_run(run_id, status="paused", pause_reason="user_requested")
        incomplete = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert incomplete.status_code == 409 and incomplete.json()["code"] == "legacy_inspection_policy_removed"
        store.resume_run(run_id)
        assert not run_until_crash(client, app, run_id)
        assert store.run(run_id)["status"] == "completed"
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert answer.status_code == 202
        binding = store.run(answer.json()["id"])["budget"]["inspection"]
        assert binding["list_run_id"] == run_id
        assert binding["manifest_hash"] == store.existing_step(run_id, small_batch.LIST_KEY)["output"]["manifest_hash"]

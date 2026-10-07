"""Shared full-text semantics exercised by synthetic small-batch discovery runs."""
import json
import httpx

import pytest

from deixis.models.adapter import ModelStepResult
from deixis.storage.db import dumps
from deixis.workflow import adjudication, fulltext, small_batch
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from test_abstract_flow import client_of, records_of, QUESTION
from test_adjudication_flow import (app_for as reading_app, discover, wait, wait_fetch, wait_kind,
    papers, patch_selection, selection, fulltext_code, adj_calls, budget_of, turn_timeout, absent_response)
from batch_outputs import stage_output as step_output
from test_fulltext_flow import (app_for as fetch_app, Fetcher, Transport, work, ok, named_pdf,
    unpaywall, fulltext_codes, work_steps, wait_for_retrieval)
from deixis.documents.fetch import FetchResult

REFUSED = FetchResult("http_error", final_url=None, http_status=403)
_FREEZE_BUDGET = small_batch.freeze_budget
_READ_FULLTEXT = ResearchFlow._fulltext_adjudication


def app_for(tmp_path, monkeypatch, transport, fetcher, *, reading="auto", adapter=None, concurrency=1):
    # Seed with reading disabled when the scenario needs a user edit before the read.
    # Every later request is a new discovery with the small-batch reading allowance.
    freeze = _FREEZE_BUDGET
    queued = 0

    def budget(body, effort, mode):
        nonlocal queued
        queued += 1
        return freeze(body, effort, "off" if reading == "off" and queued == 1 else "auto")

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    read = _READ_FULLTEXT

    async def bounded(self, run, scope, **kwargs):
        # Freeze the scenario's reading room after discovery steps consumed theirs.
        cap = f"{kwargs.get('batch_key')}:test_read_room"
        if self.store.existing_step(run["id"], cap) is None and run["budget"]["inspection"]["read_limit"]:
            room = adjudication.read_budget(scope["effort"])
            body = self.store.run(run["id"])["budget"]
            body["max_model_calls"] = self.store.run(run["id"])["usage"].get("model_calls", 0) + room["max_model_calls"]
            self.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (dumps(body), run["id"]))
            step = self.store.step(run["id"], cap, "code:test_read_room")
            self.store.finish_step(step["id"], "succeeded", output={"max_model_calls": body["max_model_calls"]})
        run = self.store.run(run["id"])
        return await read(self, run, scope, **kwargs)

    monkeypatch.setattr(ResearchFlow, "_fulltext_adjudication", bounded)
    return reading_app(tmp_path, monkeypatch, transport, fetcher, reading=reading,
                       adapter=adapter, concurrency=concurrency)


def test_small_batch_a_user_exclusion_is_not_read_and_a_user_inclusion_is_not_overwritten(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=FakeAdapter(absent_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        patch_selection(client, rid, head, "excluded")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        plan = step_output(store, run_id, "adjudication_plan")
        excluded = selection(store, rid, head)
        calls = len(adj_calls(app.state.adapters["fake"], run_id))
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and plan is None and calls == 0
    assert excluded == ("excluded", "user")

    works, fetcher = papers(1)
    app = app_for(tmp_path / "kept", monkeypatch, Transport(works), fetcher, reading="off",
                  adapter=FakeAdapter(absent_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        patch_selection(client, rid, head, "included")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
        kept = selection(store, rid, head)
        code = fulltext_code(store, rid, head)
        calls = len(adj_calls(app.state.adapters["fake"], run_id))
    finally:
        client.__exit__(None, None, None)
    assert calls == 2 and code == "criterion_absent" and kept == ("included", "user")

def test_small_batch_nothing_is_decided_while_the_model_is_off(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        adapter.ready = False
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "paused" and reading["pause_reason"] == "model_connection_not_ready"
    assert code == "not_read_yet" and adj_calls(adapter, run_id) == []

def test_small_batch_a_call_that_did_not_answer_is_not_decided_and_resume_makes_only_the_missing_call(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    failed = {"done": False}

    def fail(si):
        if si["task_type"] == "fulltext_adjudication" and si["adjudication_target"]["run"] == 2 and not failed["done"]:
            failed["done"] = True
            return ModelStepResult("unavailable", error="synthetic connection")
        return None

    adapter = FakeAdapter(valid_response, fail=fail)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, paused = wait(client, rid, run_id)
        paused_code = fulltext_code(store, rid, head)
        paused_calls = len(adj_calls(adapter, run_id))
        client.post(f"/api/runs/{run_id}/resume")
        _, reading = wait(client, rid, run_id)
        resumed_calls = len(adj_calls(adapter, run_id))
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and paused_code == "not_read_yet" and paused_calls == 2
    assert reading["status"] == "completed" and resumed_calls == paused_calls + 1 and code == "all_parts_verified"

def test_small_batch_invalid_output_is_not_repeated_and_the_next_run_reads_the_work_with_two_calls(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    phase = {"bad": True}

    def responder(si):
        if si["task_type"] == "fulltext_adjudication" and phase["bad"] and si["adjudication_target"]["run"] == 2:
            return "{"
        return valid_response(si)

    adapter = FakeAdapter(responder)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, done = wait(client, rid, first)
        sessions = store.conn.execute(
            "SELECT COUNT(*) FROM model_sessions WHERE run_id = ? AND step_id IN"
            " (SELECT id FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'"
            " AND operation_key LIKE '%:2')",
            (first, first)).fetchone()[0]
        code = fulltext_code(store, rid, head)
        phase["bad"] = False
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, again = wait(client, rid, second)
        second_calls = len(adj_calls(adapter, second))
        settled = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert done["status"] == "completed" and sessions == 2 and code == "not_read_yet"
    assert again["status"] == "completed" and second_calls == 2 and settled == "all_parts_verified"

def test_small_batch_a_repair_leaves_the_last_work_not_reached_and_no_work_is_half_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(adjudication, "read_budget", budget_of(3, 2))
    works, fetcher = papers(2)
    state = {"bad": True}

    def responder(si):
        if si["task_type"] == "fulltext_adjudication" and state["bad"] and si["adjudication_target"]["run"] == 1:
            state["bad"] = False
            return "{"
        return valid_response(si)

    adapter = FakeAdapter(responder)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        summary = step_output(store, reading["id"], "adjudication_summary")
        steps = store.conn.execute(
            "SELECT operation_key, status FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'",
            (reading["id"],)).fetchall()
        by_head: dict[str, int] = {}
        for row in steps:
            head, _, _run = row["operation_key"].removeprefix("fulltext_adjudication:").rpartition(":")
            by_head[head] = by_head.get(head, 0) + 1
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and summary["not_reached"] == 1
    assert sorted(by_head.values()) == [2]
    assert len(adj_calls(adapter, reading["id"])) == 3

    monkeypatch.setattr(adjudication, "read_budget", budget_of(1, 1))
    works, fetcher = papers(1)
    app = app_for(tmp_path / "short", monkeypatch, Transport(works), fetcher, reading="off")
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, short = wait(client, rid, run_id)
        opened = app.state.store.conn.execute(
            "SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'",
            (run_id,)).fetchone()[0]
        summary = step_output(app.state.store, run_id, "adjudication_summary")
    finally:
        client.__exit__(None, None, None)
    assert short["status"] == "completed" and opened == 0 and summary["not_reached"] == 1

def test_small_batch_at_most_the_limiter_limit_calls_are_in_flight(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    peaks = []
    adapter = FakeAdapter(valid_response, delay=0.05)

    def before(si):
        if si["task_type"] == "fulltext_adjudication":
            peaks.append(adapter.current + 1)

    adapter.before = before
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter, concurrency=2)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reading = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and peaks and max(peaks) <= 2 and max(peaks) == 2

def test_small_batch_a_scope_revision_cancels_the_run_and_an_in_flight_response_writes_no_decision(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    holder = {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication" or holder.get("bumped"):
            return
        holder["bumped"] = True
        store = holder["store"]
        research = store.research(si["research_id"])
        scope = store.scope(si["research_id"])
        store.revise_scope(si["research_id"], research["version"],
                           scope["question"] + " under a SYNTHETIC drip line", scope.get("steering"))

    adapter = FakeAdapter(valid_response, delay=0.05, before=before)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter, concurrency=2)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = holder["store"] = app.state.store
        head = records_of(store, rid)["W1"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
        proposals = store.conn.execute(
            "SELECT COUNT(*) FROM model_proposals WHERE step_id IN (SELECT id FROM run_steps WHERE run_id = ?)",
            (run_id,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "cancelled" and reading["pause_reason"] == "scope_revised"
    assert code == "not_read_yet" and proposals == 0

def test_small_batch_an_unconfirmed_pdf_is_decided_without_a_call_and_a_user_upload_is_read(tmp_path, monkeypatch):
    works, fetcher = papers(1, named=False)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
        calls = len(adj_calls(adapter, run_id))
        summary = step_output(store, run_id, "adjudication_summary")
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and code == "pdf_identity_unconfirmed" and calls == 0
    assert not adj_calls(adapter, run_id)

    works, fetcher = papers(1, named=False)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path / "upload", monkeypatch, Transport(works), fetcher, adapter=adapter)
    plan = ResearchFlow._adjudication_plan

    def uploaded(self, run, scope, **kwargs):
        self.store.conn.execute("UPDATE source_assets SET origin = 'user_upload'")
        return plan(self, run, scope, **kwargs)

    monkeypatch.setattr(ResearchFlow, "_adjudication_plan", uploaded)
    client = client_of(app)
    try:
        rid, run_id, _, reading = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        code = fulltext_code(store, rid, head)
        calls = len(adj_calls(adapter, run_id))
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and calls == 2 and code == "all_parts_verified"

def test_small_batch_a_version_that_is_not_a_member_of_this_research_is_not_read(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off")
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        work_id = store.source(head)["work_id"]
        store.conn.execute(
            "INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES (?, ?, ?, 'provider', 't')",
            ("srv_outsider_synthetic", work_id, "SYNTHETIC outsider greenhouse tomato"))
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
        plan = step_output(store, run_id, "adjudication_plan")
        versions = store.work_versions(rid, head)
        payload = store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE run_id = ? AND task_type = 'fulltext_adjudication' LIMIT 1",
            (run_id,)).fetchone()
        shown = json.loads(payload["payload_json"])["adjudication_target"]["source_id"]
    finally:
        client.__exit__(None, None, None)
    assert "srv_outsider_synthetic" not in versions
    assert plan["works"][0]["read_version"] == head == shown

def test_small_batch_a_repair_the_budget_no_longer_holds_is_skipped_and_the_run_completes(tmp_path, monkeypatch):
    """One work, budget 3, both first calls invalid: the first repair fits, the second does not. The second call is
    closed `invalid_model_output`, the run is `completed` (not `budget_exhausted`), and the work gets no decision."""
    monkeypatch.setattr(adjudication, "read_budget", budget_of(3, 1))
    works, fetcher = papers(1)
    bad = {1, 2}

    def responder(si):
        if si["task_type"] == "fulltext_adjudication" and si["adjudication_target"]["run"] in bad:
            bad.discard(si["adjudication_target"]["run"])
            return "{"
        return valid_response(si)

    adapter = FakeAdapter(responder)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        summary = step_output(store, reading["id"], "adjudication_summary")
        steps = sorted((row["status"], row["error_code"]) for row in store.conn.execute(
            "SELECT status, error_code FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'",
            (reading["id"],)).fetchall())
        heads = [c["source_version_id"] for c in store.candidates(rid)]
        decided = [fulltext_code(store, rid, svid) for svid in heads]
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and reading["pause_reason"] is None
    assert steps == [("failed", "invalid_model_output"), ("succeeded", None)]
    assert len(adj_calls(adapter, reading["id"])) == 3
    assert all(code in (None, "not_read_yet") for code in decided)

def test_small_batch_a_reading_call_cut_off_with_no_call_left_in_the_budget_is_not_sent_again(tmp_path, monkeypatch):
    """Budget 2 for one work: run 1 and run 2 use it up, run 2 times out. The step stays `outcome_unknown` and the run
    pauses as it did before slice 13e; it is not reopened only to be closed as `budget_exhausted`."""
    monkeypatch.setattr(adjudication, "read_budget", budget_of(2, 1))
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, fail=turn_timeout("fulltext_adjudication", 1))
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        step = app.state.store.conn.execute(
            "SELECT status, error_code, attempt FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'"
            " AND operation_key LIKE '%:2'", (reading["id"],)).fetchone()
    finally:
        client.__exit__(None, None, None)
    assert (reading["status"], reading["pause_reason"]) == ("paused", "model_call_failed")
    assert (step["status"], step["error_code"], step["attempt"]) == ("outcome_unknown", "model_failed", 1)
    assert len(adj_calls(adapter, reading["id"])) == 2


def pause_after_first_fetch(app):
    def pause(fetcher, fetched_url):
        if len(fetcher.calls) == 1:
            row = app.state.store.conn.execute("SELECT id FROM runs WHERE status = 'running'").fetchone()
            app.state.store.update_run(row[0], event="run_pause_requested", status="pause_requested",
                                       pause_reason="user_requested")
    return pause


def test_small_batch_a_link_that_refused_is_not_requested_again_by_a_later_run(tmp_path, monkeypatch):
    """D35, and "the next run continues where the first stopped": a fresh `no_fulltext` is not tried twice."""
    fetcher = Fetcher({"https://example.org/w1.pdf": REFUSED})
    app = fetch_app(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_for_retrieval(client, rid)
        asked = list(fetcher.calls)
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        claimed = work_steps(app.state.store, second)
    finally:
        client.__exit__(None, None, None)
    assert asked == ["https://example.org/w1.pdf"] and fetcher.calls == asked
    assert claimed == {}

def test_small_batch_a_verified_copy_of_another_version_opens_its_own_row_under_the_work(tmp_path, monkeypatch):
    """SW10.3 and D4: the published record keeps no file it does not have; the submitted copy carries its own label."""
    copy = "https://example.org/w1-submitted.pdf"
    transport = Transport([work(1)], unpaywall("10.1/oa.1", copy, "submittedVersion"))
    fetcher = Fetcher({copy: ok()})
    app = fetch_app(tmp_path, monkeypatch, transport, fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        opened = store.source(output["read_version"])
        candidates = [c["source_version_id"] for c in store.candidates(rid)]
        text = (store.has_pdf_text(opened["id"]), store.has_pdf_text(head))
        reads, heads = store.answer_version(rid, head), store.work_heads(rid)[opened["work_id"]]
        # A second retrieval run must not open the row twice nor ask for the file again.
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        rows = store.conn.execute("SELECT COUNT(*) FROM source_versions WHERE work_id = ?",
                                  (opened["work_id"],)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "lookup_version" and output["code"] == "not_read_yet"
    assert opened["id"] != head and opened["version_label"] == "submittedVersion" and opened["doi"] is None
    assert text == (True, False) and reads == opened["id"]
    assert opened["id"] not in candidates  # a member of the research, never a candidate screened on its own
    assert heads == head  # the head of the work does not change
    assert rows == 2 and fetcher.calls.count(copy) == 1

def test_small_batch_a_work_whose_text_is_already_here_is_not_requested_and_still_gets_its_code(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = fetch_app(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_for_retrieval(client, rid)
        store = app.state.store
        asked = list(fetcher.calls)
        # The code is already written, so the next run neither asks for the file nor closes and reopens the row.
        rows = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'",
                                  (rid,)).fetchone()[0]
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        claimed = work_steps(store, second)
        after = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'",
                                   (rid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert claimed == {}
    assert fetcher.calls == asked and rows == after == 2

def test_small_batch_a_run_paused_inside_one_work_resumes_it_without_asking_the_same_link_again(tmp_path, monkeypatch):
    """The pause falls between a work's `fetch_pdf` step and the rest of that work, so its work step is unfinished."""
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=2))
    # The published record has an open link of its own that refuses, and the work also has an open preprint.
    record = work(1, pdf_url="https://example.org/w1-preprint.pdf", pdf_version="submittedVersion")
    record["locations"] = [{"is_oa": True, "pdf_url": "https://example.org/w1.pdf", "version": "publishedVersion"}]
    fetcher = Fetcher({"https://example.org/w1.pdf": REFUSED, "https://example.org/w1-preprint.pdf": ok()})
    app = fetch_app(tmp_path, monkeypatch, Transport([record, work(2)]), fetcher)
    fetcher.hook = pause_after_first_fetch(app)
    from deixis.workflow.flow import RunStopped
    stop = ResearchFlow._stop_work_if_requested
    cooperative_stops = []
    def stopped(self, run):
        try:
            return stop(self, run)
        except RunStopped:
            status = self.store.run(run["id"])["status"]
            cooperative_stops.append(status)
            assert status == "pause_requested"
            assert not [e for e in self.store.events_after(run["research_id"], 0) if e["type"] == "run_paused"]
            raise
    monkeypatch.setattr(ResearchFlow, "_stop_work_if_requested", stopped)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, paused = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        halfway = next(dict(row)["status"] for row in store.conn.execute(
            "SELECT status FROM run_steps WHERE run_id = ? AND kind = 'code:fulltext_work'"
            " AND operation_key = ?", (paused["id"], "fulltext_work:" + store.source(head)["work_id"])))
        fetcher.hook = None
        client.post(f"/api/runs/{paused['id']}/resume")
        _, resumed = wait(client, rid, paused["id"])
        output = json.loads(work_steps(store, resumed["id"])[head]["output_json"])
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and halfway == "cancelled"
    assert cooperative_stops
    assert resumed["status"] == "completed" and output["code"] == "not_read_yet"
    assert output["route"] == "work_version"
    # The link that refused is not asked a second time (D35), and the preprint is fetched once.
    assert fetcher.calls.count("https://example.org/w1.pdf") == 1
    assert fetcher.calls.count("https://example.org/w1-preprint.pdf") == 1

def test_small_batch_a_record_whose_own_link_refused_still_gets_the_verified_copy_of_another_version(tmp_path, monkeypatch):
    """A 403 on the record's own link opens the DOI lookup inside `_acquire_pdf`; the retrieval run's lookup must be
    the one that may open a row for another version there too, or the owner's decision 3 never applies to the
    records most likely to need it."""
    own, copy = "https://example.org/w1.pdf", "https://example.org/w1-submitted.pdf"
    transport = Transport([work(1, pdf_url=own)], unpaywall("10.1/oa.1", copy, "submittedVersion"))
    fetcher = Fetcher({own: REFUSED, copy: ok()})
    app = fetch_app(tmp_path, monkeypatch, transport, fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        opened = store.source(output["read_version"])
        text = (store.has_pdf_text(opened["id"]), store.has_pdf_text(head))
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "lookup_version" and output["code"] == "not_read_yet"
    assert opened["id"] != head and opened["version_label"] == "submittedVersion"
    assert text == (True, False) and transport.lookups == ["10.1/oa.1"]

def test_small_batch_a_work_read_through_its_own_link_leaves_no_lookup_step_that_never_runs(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = fetch_app(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        kinds = [row["kind"] for row in app.state.store.run_steps(run["id"])]
    finally:
        client.__exit__(None, None, None)
    assert "pdf_other_copy" not in kinds, kinds

def test_small_batch_a_second_research_with_the_same_record_reads_the_version_row_the_first_one_opened(tmp_path, monkeypatch):
    """Records are shared by every research; a row one research's lookup opened has to join the next research too, or
    that research says `no_fulltext` about a work whose text is in the library."""
    copy = "https://example.org/w1-submitted.pdf"
    transport = Transport([work(1)], unpaywall("10.1/oa.1", copy, "submittedVersion"))
    fetcher = Fetcher({copy: ok()})
    app = fetch_app(tmp_path, monkeypatch, transport, fetcher)
    client = client_of(app)
    try:
        first, _, _, _ = discover(client)
        wait_for_retrieval(client, first)
        second, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, second)
        store = app.state.store
        progress = small_batch.stored_progress(store, store.run(run["id"]))
        outputs = [json.loads(row["output_json"]) for row in work_steps(store, run["id"]).values()]
        has_text = store.has_pdf_text(store.answer_version(second, records_of(store, second)["W1"]))
    finally:
        client.__exit__(None, None, None)
    # Either the plan already saw the text or the work step found the row; in neither case is the work without text.
    assert progress["items"][0]["reason_code"] == "pdf_identity_unconfirmed"
    assert has_text
    assert fetcher.calls.count(copy) == 1


def test_small_batch_a_stale_non_human_fulltext_decision_yields_to_a_newer_abstract_decision(tmp_path, monkeypatch):
    """A stale full-text code no longer speaks for the work (slice 12). The abstract decision under the question
    the research is now asking does. A stale human full-text decision still speaks; that case is in
    `test_adjudication.py`.
    """
    fetcher = Fetcher({"https://example.org/w1.pdf": ok(named_pdf("10.1/oa.1"))})
    app = fetch_app(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        research = client.get(f"/api/researches/{rid}").json()["research"]
        client.post(f"/api/researches/{rid}/scope", json={"question": f"{QUESTION} under a SYNTHETIC drip line",
                                                          "expected_version": research["version"]})
        decisions = DecisionStore(store)
        held = decisions.current(rid, head, "fulltext")
        # The abstract stage now says the record is out of scope under the question the research is really asking.
        decisions.record(rid, head, "both_blocks_missing")
        outcome = decisions.work_outcome(rid, store.source(head)["work_id"])
        stale = decisions.is_stale(held)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and held["reason_code"] == "not_read_yet" and stale
    assert outcome["stage"] == "abstract" and outcome["reason_code"] == "both_blocks_missing"

def test_small_batch_a_lookup_that_did_not_answer_is_asked_again_by_the_next_run_and_the_work_can_settle(tmp_path, monkeypatch):
    """The lookup rows are the research's history, not the run's: an old 429 must neither stop the next run from
    looking the DOI up again nor keep the work undecided for ever."""
    doi = "10.1/oa.1"

    class Limited(Transport):
        limited = True

        def __call__(self, request):
            if request.url.host == "api.unpaywall.org" and self.limited:
                self.lookups.append(doi)
                return httpx.Response(429)
            return super().__call__(request)

    transport = Limited([work(1)])  # a closed record: no open link, so the DOI lookup is its only route
    app = fetch_app(tmp_path, monkeypatch, transport, Fetcher({}))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        undecided = (store.conn.execute("SELECT error_code FROM run_steps WHERE run_id = ? AND kind = 'code:fulltext_work'", (first["id"],)).fetchone()[0], fulltext_codes(store, rid))
        transport.limited = False  # Unpaywall answers now: it holds no copy
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        codes = fulltext_codes(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert undecided == ("fetch_not_settled", {"W1": None})
    assert transport.lookups == [doi, doi], "the next run did not look the DOI up again"
    assert codes == {"W1": "no_fulltext"}


def test_small_batch_an_answer_run_and_a_pdf_collection_run_keep_the_steps_they_had(tmp_path, monkeypatch):
    """Neither gains a retrieval step, the wider other-copy trigger, nor a version row of its own (byte for byte)."""
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    transport = Transport([work(1, pdf_url="https://example.org/w1.pdf"), work(2)],
                          unpaywall("10.1/oa.2", "https://example.org/w2-submitted.pdf", "submittedVersion"))
    app = fetch_app(tmp_path, monkeypatch, transport, fetcher, setting="off")
    client = client_of(app)
    try:
        rid, _, view, _ = discover(client)
        store = app.state.store
        records = records_of(store, rid)
        for key in ("W1", "W2"):
            source = next(s for s in view["sources"] if s["source_version_id"] == records[key])
            client.patch(f"/api/researches/{rid}/selections/{records[key]}",
                         json={"state": "included", "expected_version": source["selection"]["version"]})
        collection = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"}).json()["id"]
        wait(client, rid, collection)
        kinds = {s["kind"] for s in store.run_steps(collection)}
        rows = store.conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0]
        codes = fulltext_codes(store, rid)
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, answered = wait(client, rid, answer)
        answer_kinds = {s["kind"] for s in store.run_steps(answer)}
    finally:
        client.__exit__(None, None, None)
    assert kinds <= {"fetch_pdf", "pdf_other_copy"}
    assert not any(kind.startswith("code:fulltext") for kind in kinds | answer_kinds)
    # W2 has no open link at all, so a collection run opens no lookup for it and no version row is added.
    assert rows == 2 and "https://example.org/w2-submitted.pdf" not in fetcher.calls
    assert codes == {"W1": None, "W2": None}  # a collection run writes no full-text decision
    assert answered["status"] in ("completed", "paused")


def test_small_batch_fetch_off_opens_no_work_or_reading_calls(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok(named_pdf("10.1/oa.1"))})
    app = fetch_app(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]),
                    fetcher, setting="off")
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        assert run["status"] == "completed"
        assert not fetcher.calls
        assert not work_steps(app.state.store, run_id)
        assert not adj_calls(app.state.adapters["fake"], run_id)
    finally:
        client.__exit__(None, None, None)

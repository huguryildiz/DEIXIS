"""The flow snapshot an `sw` answer run keeps at its start, beside the answer's own input (slice 20, decision 3).

Real answer runs through `create_app` with a scripted model and a mocked transport; the questions, PDFs and decisions
are SYNTHETIC and from two fields. Passing shows what the run stores at its start, what a resumed run keeps and what
the research view shows beside each answer; it says nothing about the answer's quality.
"""

from __future__ import annotations

import pytest

from deixis.storage import db
from deixis.workflow import flow_counts, probes, queue, views
from deixis.workflow.flow import ResearchFlow
from helpers import make_pdf
from test_criterion_passage_flow import (CRITERION_PAGE, QUESTION, OTHER_QUESTION, TOPIC_PAGE, answer, app_for,
                                         client_of, research_with_pdf, wait_run)


def upload(client, rid, pages=(TOPIC_PAGE,)):
    return client.post(f"/api/researches/{rid}/uploads",
                       files={"file": ("b.pdf", make_pdf(list(pages)), "application/pdf")}).json()


def machine_source(store, rid, title, reason=None):
    """A source of the research that is not the person's: added by code, with a code decision on it."""
    svid = store.create_upload_source(title)
    store.add_to_corpus(rid, svid, "user_upload", candidate=False)
    if reason:
        decisions = queue.DecisionStore(store)
        decisions.record(rid, svid, reason)
        decisions.derive_selection(rid, store.source(svid)["work_id"])
    return svid


def snapshot_step(store, run_id):
    return store.existing_step(run_id, "answer_start_snapshot")


def flow_now(store, rid):
    ctx = queue.context(store, rid)
    return flow_counts.flow_counts(ctx, probes.probe_set(ctx))


@pytest.mark.parametrize("question", [QUESTION, OTHER_QUESTION])
def test_an_answer_starts_with_a_full_queue_and_keeps_the_flow_of_that_moment(tmp_path, monkeypatch, question):
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research_with_pdf(client, question)
        queued = machine_source(store, rid, "SYNTHETIC a queued record", "fulltext_runs_disagree")
        excluded = machine_source(store, rid, "SYNTHETIC a record the runs left out", "criterion_absent")
        expected = flow_now(store, rid)
        selection_revision = store.selection_revision(rid)
        view, run, run_id = answer(client, rid)
        step = snapshot_step(store, run_id)
        # A queue answer given after the answer does not rewrite what the answer's run kept.
        row = next(r for r in queue.queue_rows(store, rid)["rows"] if r["source_version_id"] == queued)
        queue.decide(store, rid, queued, "include", None, row["row_token"])
        later = client.get(f"/api/researches/{rid}").json()
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert expected["buckets"]["queued"] == 1
    assert (step["kind"], step["status"]) == ("code:answer_start_snapshot", "succeeded")
    output = step["output"]
    assert output["scope_revision"] == run["scope_revision"] and output["selection_revision"] == selection_revision
    assert output["flow"] == expected and output["included"] == 1 and output["included_without_answer_text"] == 0
    (shown,) = later["answers"]
    assert shown["start_snapshot"]["flow"] == expected and shown["start_snapshot"]["included_state_changed"] is False
    assert shown["inputs_given"]["sources"] == 1
    # The answer's input is the included works only: the one the runs left out is not in it.
    assert excluded not in shown["inputs_given"]["source_ids"] and queued not in shown["inputs_given"]["source_ids"]


def pause_once(monkeypatch, change):
    """Pause the answer run at its first `_inspect`, after `change` wrote something a person could have written."""
    original = ResearchFlow._inspect
    calls = []

    async def inspect(self, run, limit):
        calls.append(run["id"])
        if len(calls) == 1:
            change(self.store, run["research_id"])
            self._pause(run["id"], "synthetic_pause")
        return await original(self, run, limit=limit)

    monkeypatch.setattr(ResearchFlow, "_inspect", inspect)


@pytest.mark.parametrize("case,changed", [("include", True), ("pending", False), ("remove_pdf", True)])
def test_a_resumed_answer_keeps_its_start_and_says_when_the_included_sources_state_moved(tmp_path, monkeypatch, case,
                                                                                         changed):
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research_with_pdf(client, pages=(CRITERION_PAGE, TOPIC_PAGE))
        second = upload(client, rid)
        other = machine_source(store, rid, "SYNTHETIC a record", "criterion_absent")

        def change(store, rid):
            if case == "include":
                version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?", (other,)).fetchone()[0]
                store.set_user_selection(rid, other, "included", version, "SYNTHETIC included while the run was out")
            elif case == "pending":
                version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?", (other,)).fetchone()[0]
                store.set_user_selection(rid, other, "pending", version, "SYNTHETIC set back to pending")
            else:  # the set of included works stays the same; one included source's PDF is taken away
                svid = second["uploaded_source_version_id"]
                asset = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                                           (svid,)).fetchone()[0]
                store.remove_asset(rid, svid, asset)

        pause_once(monkeypatch, change)
        before = store.selection_revision(rid)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, paused = wait_run(client, rid, run_id)
        kept = snapshot_step(store, run_id)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait_run(client, rid, run_id)
        again = snapshot_step(store, run_id)
        stored = store.conn.execute("SELECT selection_revision FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and run["status"] == "completed", run
    assert again["output"] == kept["output"] and kept["output"]["selection_revision"] == before
    (shown,) = view["answers"]
    assert (stored != before) is changed
    assert shown["start_snapshot"]["included_state_changed"] is changed


def test_an_included_work_whose_only_text_is_an_unread_person_file_is_counted_and_not_given(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research_with_pdf(client)
        person = upload(client, rid, pages=(CRITERION_PAGE,))["uploaded_source_version_id"]
        asset = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (person,)).fetchone()[0]
        revision, criterion_hash = store.criterion_key(rid)
        store.conn.execute(
            "INSERT INTO person_pdf_requests (id, research_id, source_version_id, asset_id, scope_revision,"
            " criterion_hash, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?, ?)",
            (db.new_id("ppr"), rid, person, asset, revision, criterion_hash, db.now(), db.now()))
        view, run, run_id = answer(client, rid)
        output = snapshot_step(store, run_id)["output"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert output["included"] == 2 and output["included_without_answer_text"] == 1
    assert person not in view["answers"][0]["inputs_given"]["source_ids"]


def test_a_legacy_answer_run_opens_no_snapshot_and_an_answer_without_one_shows_none(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="legacy")
    client = client_of(app)
    try:
        store = app.state.store
        rid = research_with_pdf(client)
        view, run, run_id = answer(client, rid)
        step = snapshot_step(store, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert step is None
    assert view["answers"][0]["start_snapshot"] is None and view["counts"]["flow"] is None


def test_an_sw_answer_stored_before_this_slice_has_no_snapshot_and_no_counts_of_today(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research_with_pdf(client)
        run_id = store.create_run(rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)["id"]
        store.update_run(run_id, status="completed")
        store.save_answer(rid, run_id, None, None, 1, "no_evidence", None, {"ok": True, "issues": []},
                          selection_revision=store.selection_revision(rid))
        shown = views.research_view(store, rid)["answers"][0]
    finally:
        client.__exit__(None, None, None)
    assert shown["start_snapshot"] is None

"""Zero includes allow an abstract-only answer, or recorded no evidence when neither route exists (D106, D234).

Real answer runs through `create_app` with a scripted model and a mocked transport. The completed discovery run is
written straight into the store: what is checked is the answer run and the API rule, not how a search reaches zero
includes. Questions and records are SYNTHETIC; passing shows workflow behavior only.
"""

from __future__ import annotations

import json

import pytest

from deixis.storage import db
from deixis.storage.db import new_id, now
from fakes import FakeAdapter, valid_response
from deixis.workflow.flow import NO_INCLUDABLE_SOURCE
from test_criterion_passage_flow import QUESTION, app_for, client_of, research_with_pdf, wait_run
from test_abstract_answer_sources import candidate, ranked


def research(client, source_scope="academic"):
    body = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
            "source_scope": source_scope}
    return client.post("/api/researches", json=body).json()["research"]["id"]


def completed_discovery(store, rid, status="completed", revision=None, sources=()):
    """Synthetic stored small-batch discovery; the API answer must bind its list."""
    from deixis.workflow import small_batch
    current = store.research(rid)["current_scope_revision"]
    ts, run_id = now(), new_id("run")
    with db.transaction(store.conn):
        store.conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES (?, ?, ?, 'discovery', ?, 'discovery', ?, ?, ?)",
            (run_id, rid, revision if revision is not None else current, status,
             json.dumps({"inspection": {"policy": small_batch.POLICY}}), ts, ts))
        if status == "completed" and (revision is None or revision == current):
            versions = {svid: store.source(svid) for svid in sources}
            for svid, version in versions.items():
                version["abstract"] = " ".join(p["text"] for p in store.passages_for(svid) if p["kind"] == "abstract") or None
            listing = {"manifest_hash": "synthetic-no-include", "order_hash": "synthetic-no-include",
                       "manifest": {"scope_revision": current, "versions": versions},
                       "order": list(sources), "automatic_order": list(sources), "user_priority": [],
                       "items": [{"head": svid, "work_id": versions[svid]["work_id"], "versions": [svid],
                                  "position": i + 1, "user_priority": False} for i, svid in enumerate(sources)]}
            step = store.step(run_id, small_batch.LIST_KEY, "code:small_batch_list")
            store.finish_step(step["id"], "succeeded", output=listing)


def start_answer(client, rid):
    return client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})


def test_an_sw_research_with_no_include_or_abstract_candidate_records_no_evidence_without_a_model(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    app = app_for(tmp_path, monkeypatch, workflow="sw", adapter=adapter)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research(client)
        completed_discovery(store, rid)
        view = client.get(f"/api/researches/{rid}").json()
        assert view["scope"]["discovery_completed"] is True and view["counts"]["included"] == 0
        response = start_answer(client, rid)
        assert response.status_code == 202, response.text
        view, run = wait_run(client, rid, response.json()["id"])
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    (shown,) = view["answers"]
    assert shown["status"] == "no_evidence"
    assert shown["validation"]["reason"] == NO_INCLUDABLE_SOURCE == "no_includable_source"
    assert shown["validation"]["ok"] is True and shown["validation"]["issues"] == []
    assert shown["validation"]["note"].startswith("No work was included at full text when this answer started")
    assert "criterion" not in shown["validation"]["note"]
    assert shown["start_snapshot"]["included"] == 0
    assert shown["claims"] == []
    keys = [step["operation_key"] for step in run["steps"]]
    assert "answer_start_snapshot" in keys and "grounded_answer" not in keys and "answer_review" not in keys
    assert adapter.calls == []  # no model was asked anything


@pytest.mark.parametrize("exclude", [False, True])
def test_zero_includes_calls_the_answer_with_only_eligible_abstracts(tmp_path, monkeypatch, exclude):
    def respond(si):
        output = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer":
            output["limitations"] = [{"kind": "access", "text": "This answer is based only on abstracts.",
                                      "source_ids": si["allowlist"]["source_ids"]}]
        return json.dumps(output)

    adapter = FakeAdapter(responder=respond)
    app = app_for(tmp_path, monkeypatch, workflow="sw", adapter=adapter)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research(client)
        sources = [candidate(store, rid, f"abstract-{i}",
                             f"SYNTHETIC supervised exercise lowered fatigue in cohort {i}.",
                             "runs_agree_candidate", *(["no_fulltext"] if i % 2 else [])) for i in range(4)]
        ranked(store, rid, sources)
        completed_discovery(store, rid, sources=sources)
        if exclude:
            version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?",
                                         (sources[0],)).fetchone()[0]
            store.set_user_selection(rid, sources[0], "excluded", version, "SYNTHETIC user exclusion")
        selection_revision = store.selection_revision(rid)
        response = start_answer(client, rid)
        assert response.status_code == 202, response.text
        view, run = wait_run(client, rid, response.json()["id"])
        assert run["status"] == "completed", run
        step = store.existing_step(run["id"], "grounded_answer")
        payload = store.step_input_payload(step["output"]["step_input_id"])
        input_selection_revision = store.step_input_selection_revision(step["output"]["step_input_id"])
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    (shown,) = view["answers"]
    assert shown["status"] == "structurally_valid", shown
    assert shown["start_snapshot"]["included"] == 0
    assert shown["start_snapshot"]["selection_revision"] == selection_revision
    assert input_selection_revision == selection_revision
    expected = set(sources[1:] if exclude else sources)
    assert {p["source_id"] for p in payload["passages"]} == expected
    assert all(p["reading_depth"] == "abstract" and p["locator"]["kind"] == "abstract"
               for p in payload["passages"])
    assert shown["inputs_given"]["sources"] == shown["inputs_given"]["passages"] == len(expected)
    assert shown["limitations"][0]["kind"] == "access"
    assert any(call["task_type"] == "grounded_answer" for call in adapter.calls)
    assert not any(step["operation_key"].startswith("acquire_pdf") for step in run["steps"])


def test_zero_includes_with_only_a_user_excluded_candidate_still_records_no_evidence(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    app = app_for(tmp_path, monkeypatch, workflow="sw", adapter=adapter)
    client = client_of(app)
    try:
        store = app.state.store
        rid = research(client)
        source = candidate(store, rid, "excluded", "SYNTHETIC exercise lowered fatigue.", "runs_agree_candidate")
        ranked(store, rid, [source])
        completed_discovery(store, rid, sources=[source])
        version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?", (source,)).fetchone()[0]
        store.set_user_selection(rid, source, "excluded", version, "SYNTHETIC user exclusion")
        response = start_answer(client, rid)
        assert response.status_code == 202, response.text
        view, run = wait_run(client, rid, response.json()["id"])
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert view["answers"][0]["validation"]["reason"] == NO_INCLUDABLE_SOURCE
    assert adapter.calls == []


def test_an_sw_research_without_a_completed_discovery_is_still_refused(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="sw")
    client = client_of(app)
    try:
        store = app.state.store
        rid = research(client)
        assert start_answer(client, rid).status_code == 422
        completed_discovery(store, rid, status="paused")  # a paused search is not a finished one
        assert start_answer(client, rid).status_code == 422
        completed_discovery(store, rid, revision=0)  # nor one of an earlier revision
        assert client.get(f"/api/researches/{rid}").json()["scope"]["discovery_completed"] is False
        assert start_answer(client, rid).status_code == 422
    finally:
        client.__exit__(None, None, None)
def test_a_pdf_collection_with_no_include_is_still_refused(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="sw")
    client = client_of(app)
    try:
        store = app.state.store
        rid = research(client)
        completed_discovery(store, rid)
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"})
        assert response.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_an_sw_research_with_an_include_answers_as_before(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="sw")
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        response = start_answer(client, rid)
        view, run = wait_run(client, rid, response.json()["id"])
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert view["answers"][0]["status"] == "structurally_valid"
    assert "reason" not in view["answers"][0]["validation"]

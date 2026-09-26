"""An `sw` research whose search finished with no included work ends with an answer that says so (SW22, D106).

Real answer runs through `create_app` with a scripted model and a mocked transport. The completed discovery run is
written straight into the store: what is checked is the answer run and the API rule, not how a search reaches zero
includes. Questions and records are SYNTHETIC; passing shows workflow behavior only.
"""

from __future__ import annotations

from deixis.storage import db
from deixis.storage.db import new_id, now
from fakes import FakeAdapter
from deixis.workflow.flow import NO_INCLUDABLE_SOURCE
from test_criterion_passage_flow import QUESTION, app_for, client_of, research_with_pdf, wait_run


def research(client, source_scope="academic"):
    body = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
            "source_scope": source_scope}
    return client.post("/api/researches", json=body).json()["research"]["id"]


def completed_discovery(store, rid, status="completed", revision=None):
    """A discovery run of the research's current revision that ended as `status`; SYNTHETIC, no step inside."""
    current = store.research(rid)["current_scope_revision"]
    ts = now()
    with db.transaction(store.conn):
        store.conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES (?, ?, ?, 'discovery', ?, 'discovery', '{}', ?, ?)",
            (new_id("run"), rid, revision if revision is not None else current, status, ts, ts))


def start_answer(client, rid):
    return client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})


def test_an_sw_research_with_no_include_ends_with_a_recorded_no_evidence_answer_and_no_model_call(tmp_path, monkeypatch):
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


def test_a_legacy_research_with_no_include_is_still_refused(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="legacy")
    client = client_of(app)
    try:
        store = app.state.store
        rid = research(client)
        completed_discovery(store, rid)
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

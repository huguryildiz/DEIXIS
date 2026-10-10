"""The API rule for an answer with no include: refused without a completed discovery, answered as before with one.

The answers built from a stored small-batch discovery with zero includes (the abstract-only route, D106, D234) were
removed with that route in the clean start (slice 3b); the fast path writes its own no-evidence answer
(`test_fast_path_answer`). Real answer runs through `create_app` with a scripted model and a mocked transport. The
completed discovery run is written straight into the store. Questions and records are SYNTHETIC; passing shows
workflow behavior only.
"""

from __future__ import annotations

import json

from deixis.storage import db
from deixis.storage.db import new_id, now
from test_criterion_passage_flow import QUESTION, app_for, client_of, research_with_pdf, wait_run


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

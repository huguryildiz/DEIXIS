"""What a research's intent (papers, report, table, compare) makes discovery queue, and follow-up suggestions.

Model-free (FakeAdapter, mocked providers). Passing shows which stages are queued, not answer quality.
"""

import json
from deixis.workflow import fast_path, intent
from helpers import make_pdf
from test_abstract_flow import Pool, app_for, client_of, wait, work
import httpx
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.api.home_routes import suggestions
from deixis.config import Settings
from deixis.storage import db
from deixis.workflow import intent
from fakes import FakeAdapter, valid_response


# ---- from tests__discovery__test_research_intent.py ------------------------------------------------------------

def runs_of(store, rid, kind):
    return [dict(r) for r in store.conn.execute(
        "SELECT id, idempotency_key, budget_json, target_json FROM runs WHERE research_id = ? AND kind = ?"
        " ORDER BY created_at, rowid", (rid, kind))]


def tables_of(store, rid):
    return [dict(r) for r in store.conn.execute(
        "SELECT id, title, idempotency_key FROM evidence_tables WHERE research_id = ?", (rid,))]


def rows_of(store, table_id):
    return {(r["source_version_id"], r["added_by"]) for r in store.conn.execute(
        "SELECT source_version_id, added_by FROM table_rows WHERE table_id = ?", (table_id,))}


def events_of(store, rid, type_):
    return [r["payload_json"] for r in store.conn.execute(
        "SELECT payload_json FROM events WHERE research_id = ? AND type = ?", (rid, type_))]


# The package hash before S5a taught the column suggestions the comparison frame.


def run(tmp_path, monkeypatch, intent_, scope="academic", upload=False):
    """One research with the intent, an optional included PDF, one completed discovery run."""
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(3)]))
    client = client_of(app)
    body = {"question": "How does irrigation scheduling affect marketable yield in greenhouse tomato production?",
            "model_connection": "fake", "requested_model": "fake-model", "effort": "quick", "source_scope": scope,
            "intent": intent_}
    rid = client.post("/api/researches", json=body).json()["research"]["id"]
    if upload:
        client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "greenhouse.pdf", make_pdf(["SYNTHETIC greenhouse tomato irrigation scheduling and marketable yield."]),
            "application/pdf")})
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    view, discovery = wait(client, rid, run_id)
    return app, client, rid, discovery, view


def test_papers_queues_no_answer_and_no_table(tmp_path, monkeypatch):
    app, client, rid, discovery, view = run(tmp_path, monkeypatch, "papers")
    try:
        store = app.state.store
        answers, tables = runs_of(store, rid, "answer"), tables_of(store, rid)
        frozen = store.run(discovery["id"])["budget"]["fast_path"]
    finally:
        client.__exit__(None, None, None)
    assert discovery["status"] == "completed" and view["research"]["intent"] == "papers"
    assert frozen["auto_answer"] is False and "after_discovery" not in frozen
    assert answers == [] and tables == []


# ---- from tests__app__test_intent_and_suggestions.py ------------------------------------------------------------

QUESTION = "SYNTHETIC: how do the methods of these attached notes compare?"


def make_app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data", port=8765),
                      adapters={"fake": FakeAdapter(valid_response)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def open_client(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def create(client, **body):
    return client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                "requested_model": "fake-model", **body})


def upload(client, rid, name, text):
    response = client.post(f"/api/researches/{rid}/uploads",
                           files={"file": (name, make_pdf([f"SYNTHETIC {text}"]), "application/pdf")})
    assert response.status_code == 201
    return response.json()["uploaded_source_version_id"]


def rows(store, table_id):
    return {(r["source_version_id"], r["added_by"], r["removed_at"]) for r in store.conn.execute(
        "SELECT source_version_id, added_by, removed_at FROM table_rows WHERE table_id = ?", (table_id,))}


def answer(store, rid, created_at, aspects, status="structurally_valid", scope_revision=1, selection_revision=None,
           passage_ids=None):
    run = store.conn.execute("SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchone()
    if run is None:
        run_id = store.create_run(rid, "answer", {"max_model_calls": 0, "max_provider_requests": 0}, None)["id"]
        store.conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (run_id,))
    else:
        run_id = run["id"]
    draft = {"title": "SYNTHETIC", "unanswered_aspects": aspects}
    step_input_id = None
    if passage_ids is not None:  # what the answer was given, stored as a StepInput is
        step = store.step(run_id, f"answer:{created_at}", "model:grounded_answer")
        step_input_id = db.new_id("sin")
        store.conn.execute(
            "INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type, scope_revision, skill_package_hash,"
            " payload_json, base_instructions, developer_instructions, user_message, output_schema_json, created_at)"
            " VALUES (?, ?, ?, ?, 1, 'grounded_answer', 1, 'sha256:x', ?, '', '', '', '{}', ?)",
            (step_input_id, step["id"], rid, run_id, json.dumps({"passages": [{"passage_id": p} for p in passage_ids],
                                                                  "sources": []}), created_at))
    store.conn.execute(
        "INSERT INTO answers (id, research_id, run_id, step_input_id, scope_revision, selection_revision, status, draft_json,"
        " validation_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)",
        (db.new_id("ans"), rid, run_id, step_input_id, scope_revision, selection_revision, status, json.dumps(draft),
         created_at))


def test_suggestions_come_only_from_each_research_s_latest_current_valid_answer_and_are_two_at_most(tmp_path):
    app = make_app(tmp_path)
    client = open_client(app)
    try:
        store = app.state.store
        empty = client.get("/api/suggestions").json()
        ids = {name: create(client, question=f"SYNTHETIC question {name}").json()["research"]["id"]
               for name in ("older", "newer", "stale", "draft", "trashed")}
        answer(store, ids["older"], "2026-10-01T09:00:00", ["SYNTHETIC superseded aspect"])
        answer(store, ids["older"], "2026-10-02T09:00:00", ["SYNTHETIC older aspect one", "SYNTHETIC older aspect two"])
        answer(store, ids["newer"], "2026-10-03T09:00:00", ["SYNTHETIC newer aspect"])
        answer(store, ids["stale"], "2026-10-04T09:00:00", ["SYNTHETIC stale aspect"])
        stale_version = store.research(ids["stale"])["version"]
        store.revise_scope(ids["stale"], stale_version, "SYNTHETIC revised question", None)
        answer(store, ids["draft"], "2026-10-05T09:00:00", ["SYNTHETIC draft aspect"], status="unverified_draft")
        answer(store, ids["trashed"], "2026-10-06T09:00:00", ["SYNTHETIC trashed aspect"])
        store.trash_research(ids["trashed"])
        listed = client.get("/api/suggestions").json()["suggestions"]
        three = suggestions(store, limit=3)
        calls = len(app.state.adapters["fake"].calls)
        titles = {rid: store.research(rid)["title"] for rid in (ids["newer"], ids["older"])}
    finally:
        client.__exit__(None, None, None)
    assert empty == {"suggestions": []}
    assert [(s["text"], s["research_id"]) for s in listed] == [
        ("SYNTHETIC newer aspect", ids["newer"]), ("SYNTHETIC older aspect one", ids["older"])]
    assert [s["research_title"] for s in listed] == [titles[ids["newer"]], titles[ids["older"]]]
    assert [s["text"] for s in three] == ["SYNTHETIC newer aspect", "SYNTHETIC older aspect one",
                                          "SYNTHETIC older aspect two"]
    assert calls == 0



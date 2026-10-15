"""Research intent after discovery (UI parity S5a, F4; the intent x scope table of parity plan row H13).

Driven through the API with a scripted model and a mocked OpenAlex: `report` keeps its automatic answer, `papers`
queues none, `table` / `compare` open the study table instead of the answer (rows = the sources included at that
moment), and with nothing included they write no table. Records and PDFs are SYNTHETIC; passing shows the routing,
not anything about a real model or provider.
"""

import json
import sqlite3
import time

import pytest

from deixis.domain import contracts, skill
from deixis.workflow import fast_path, intent
from helpers import make_pdf
from test_abstract_flow import Pool, app_for, client_of, discover, wait, work


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
HASH_BEFORE_FRAME = "sha256:38c164ea8e749a75dd1f1aa8db3dbea1a9760892bbd2f41ffc76ddc3b79ba1b7"


def column_inputs(store, rid):
    """The stored StepInput of every column suggestion call in this research, once its run has settled."""
    deadline = time.time() + 30
    while time.time() < deadline:
        statuses = [r[0] for r in store.conn.execute(
            "SELECT status FROM runs WHERE research_id = ? AND kind = 'table_columns'", (rid,))]
        if statuses and all(s in ("completed", "failed", "paused") for s in statuses):
            break
        time.sleep(0.05)
    return [json.loads(r[0]) for r in store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id JOIN runs r ON r.id = s.run_id"
        " WHERE r.research_id = ? AND s.kind = 'model:table_columns' ORDER BY i.rowid", (rid,))]


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


def test_report_is_unchanged_and_queues_the_automatic_answer(tmp_path, monkeypatch):
    app, client, rid, discovery, view = run(tmp_path, monkeypatch, "report")
    try:
        store = app.state.store
        answers, tables = runs_of(store, rid, "answer"), tables_of(store, rid)
        frozen = store.run(discovery["id"])["budget"]["fast_path"]
    finally:
        client.__exit__(None, None, None)
    assert view["research"]["intent"] == "report" and discovery["status"] == "completed"
    assert frozen["auto_answer"] is True and "after_discovery" not in frozen
    # The policy a report run freezes is byte for byte the one it froze before intents existed.
    assert frozen == fast_path.freeze_budget({}, "quick")
    assert [a["idempotency_key"] for a in answers] == [f"fast_path:auto_answer:{discovery['id']}"]
    assert tables == []


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


def test_table_and_compare_with_an_included_source_open_one_study_table_and_no_answer(tmp_path, monkeypatch):
    for intent_ in ("table", "compare"):
        app, client, rid, discovery, view = run(tmp_path / intent_, monkeypatch, intent_,
                                                scope="attached_and_academic", upload=True)
        try:
            store = app.state.store
            included = store.included_sources(rid)
            tables = tables_of(store, rid)
            rows = rows_of(store, tables[0]["id"]) if tables else None
            columns = runs_of(store, rid, "table_columns")
            answers = runs_of(store, rid, "answer")
            frozen = store.run(discovery["id"])["budget"]["fast_path"]
            # A replayed completion (a crash after the commit, a resumed worker) finds what the first one wrote.
            intent.after_discovery(store, store.run(discovery["id"]))
            again = (tables_of(store, rid), runs_of(store, rid, "table_columns"))
            frame = view["research"]["comparison_frame"]
            inputs = column_inputs(store, rid)
        finally:
            client.__exit__(None, None, None)
        assert discovery["status"] == "completed"
        assert frozen["auto_answer"] is False and frozen["after_discovery"] == "study_table"
        assert answers == []
        assert len(included) == 1 and len(tables) == 1 and tables[0]["title"] == "Study table"
        assert rows == {(included[0], "included_at_creation")}
        assert len(columns) == 1 and columns[0]["idempotency_key"] == f"{rid}:study_table:intent:{discovery['id']}:columns"
        assert again == (tables, columns)
        assert view["intent_outcome"] is None
        # The column suggestion call was given the frame of its own scope revision, under the new method package.
        assert inputs and all(i["skill_package_hash"] == skill.package_hash() != HASH_BEFORE_FRAME for i in inputs)
        if intent_ == "compare":
            assert frame.startswith("Compare the methods") and "greenhouse tomato production" in frame
            assert [i["extraction_target"]["comparison_frame"] for i in inputs] == [frame] * len(inputs)
            assert all(i["question"]["text"] in frame for i in inputs)
            assert all(contracts.check_step_input(i) == [] for i in inputs)
            # The frame belongs to column suggestions only: a cell extraction input carrying it is refused.
            cell = json.loads(json.dumps(inputs[0])) | {"task_type": "cell_extraction"}
            assert "comparison_frame_outside_column_suggestions" in {x.code for x in contracts.check_step_input(cell)}
        else:
            assert frame is None
            assert all("comparison_frame" not in i["extraction_target"] for i in inputs)


def test_a_stored_step_input_is_never_rewritten_when_the_package_hash_moves(tmp_path, monkeypatch):
    """Later StepInputs carry the new package hash; a stored one cannot be rewritten (the table refuses it) and is read
    back unchanged by a reopened library."""
    app, client, rid, discovery, view = run(tmp_path, monkeypatch, "compare", scope="attached_and_academic", upload=True)
    try:
        store = app.state.store
        column_inputs(store, rid)
        row = store.conn.execute(
            "SELECT i.id, i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " WHERE s.kind = 'model:table_columns' ORDER BY i.rowid LIMIT 1").fetchone()
        older = json.loads(row["payload_json"]) | {"skill_package_hash": HASH_BEFORE_FRAME}
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.conn.execute("UPDATE step_inputs SET payload_json = ? WHERE id = ?", (json.dumps(older), row["id"]))
    finally:
        client.__exit__(None, None, None)
    app = app_for(tmp_path, monkeypatch, Pool([]))  # the same library, opened again
    client = client_of(app)
    try:
        client.get(f"/api/researches/{rid}")
        after = app.state.store.conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?", (row["id"],)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert after == row["payload_json"]
    assert json.loads(after)["skill_package_hash"] == skill.package_hash() != HASH_BEFORE_FRAME


def test_table_and_compare_with_nothing_included_write_no_table_and_no_answer(tmp_path, monkeypatch):
    for intent_ in ("table", "compare"):
        app, client, rid, discovery, view = run(tmp_path / intent_, monkeypatch, intent_)
        try:
            store = app.state.store
            included, tables = store.included_sources(rid), tables_of(store, rid)
            answers, columns = runs_of(store, rid, "answer"), runs_of(store, rid, "table_columns")
            skipped = events_of(store, rid, "study_table_skipped")
        finally:
            client.__exit__(None, None, None)
        assert discovery["status"] == "completed"
        assert included == [] and tables == [] and answers == [] and columns == []
        assert len(skipped) == 1 and '"no_included_source"' in skipped[0]
        assert view["intent_outcome"] == {"kind": "table_skipped", "reason": "no_included_source", "run_id": discovery["id"]}


def test_intent_outcome_shows_only_the_latest_discovery_of_the_question(tmp_path, monkeypatch):
    """S5b: Home and the research page render the current outcome. A skip written by an earlier discovery of the same
    question stops showing once a later discovery opened the table."""
    app, client, rid, first, view = run(tmp_path, monkeypatch, "table")
    try:
        assert view["intent_outcome"] == {"kind": "table_skipped", "reason": "no_included_source", "run_id": first["id"]}
        # The person includes one found work by hand; the next discovery of the same question then has an included
        # source and opens the table.
        source = next(s for s in view["sources"] if s["version_role"] == "record")
        changed = client.patch(f"/api/researches/{rid}/selections/{source['source_version_id']}", json={
            "state": "included", "expected_version": source["selection"]["version"], "reason": "SYNTHETIC: the user's call"})
        assert changed.status_code == 200
        second_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, second = wait(client, rid, second_id)
        store = app.state.store
        tables = tables_of(store, rid)
        skipped = events_of(store, rid, "study_table_skipped")
    finally:
        client.__exit__(None, None, None)
    assert second["status"] == "completed" and second["scope_revision"] == first["scope_revision"]
    assert len(tables) == 1 and len(skipped) == 1  # the earlier skip is still stored, as history
    assert view["intent_outcome"] is None


def test_a_local_model_run_keeps_no_read_or_answer_deadline(tmp_path, monkeypatch):
    """Owner 15 Oct 2026: a research on Ollama or the local server (LM Studio) has no time limit on the stages where
    the model works; search and ranking keep theirs, and a hosted connection's policy is unchanged."""
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(3)]))
    client = client_of(app)
    try:
        app.state.adapters["ollama"] = app.state.adapters["fake"]
        frozen = {}
        for connection in ("fake", "ollama"):
            rid = client.post("/api/researches", json={
                "question": "How does irrigation scheduling affect marketable yield in greenhouse tomato production?",
                "model_connection": connection, "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
            run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
            frozen[connection] = app.state.store.run(run_id)["budget"]["fast_path"]
    finally:
        client.__exit__(None, None, None)
    assert frozen["fake"] == fast_path.freeze_budget({}, "quick")
    assert frozen["ollama"] == fast_path.freeze_budget({}, "quick", local_model=True)
    assert frozen["ollama"]["enforced_stages"] == ["search", "ranking"]
    budget = {"fast_path": frozen["ollama"]}
    assert [fast_path.enforces(budget, s) for s in ("search", "ranking", "read", "answer")] == [True, True, False, False]

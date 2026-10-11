"""Research intent after discovery (UI parity S5a, F4; the intent x scope table of parity plan row H13).

Driven through the API with a scripted model and a mocked OpenAlex: `report` keeps its automatic answer, `papers`
queues none, `table` / `compare` open the study table instead of the answer (rows = the sources included at that
moment), and with nothing included they write no table. Records and PDFs are SYNTHETIC; passing shows the routing,
not anything about a real model or provider.
"""

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
        finally:
            client.__exit__(None, None, None)
        assert discovery["status"] == "completed"
        assert frozen["auto_answer"] is False and frozen["after_discovery"] == "study_table"
        assert answers == []
        assert len(included) == 1 and len(tables) == 1 and tables[0]["title"] == "Study table"
        assert rows == {(included[0], "included_at_creation")}
        assert len(columns) == 1 and columns[0]["idempotency_key"] == f"{rid}:study_table:intent:{discovery['id']}:columns"
        assert again == (tables, columns)
        if intent_ == "compare":
            assert frame.startswith("Compare the methods") and "greenhouse tomato production" in frame
        else:
            assert frame is None


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

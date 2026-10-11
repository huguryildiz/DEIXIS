"""Research intent at create time and in `attached` researches, and Home's suggestions (UI parity S5a, F4 and F5).

`attached` runs no discovery: `papers` is refused, and `table` / `compare` get a study table of the attached sources
once a file is ingested, no answer, one table per research however often the hook runs. Suggestions are the stored
`unanswered_aspects` of each research's latest valid answer to its current question, newest first, two at most; no
model is called. Every PDF, answer and title here is SYNTHETIC.
"""

import json
import shutil
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.api.home_routes import suggestions
from deixis.config import Settings
from deixis.storage import db
from deixis.workflow import intent
from fakes import FakeAdapter, valid_response
from helpers import make_pdf

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


def intent_tables(store, rid):
    return [dict(r) for r in store.conn.execute(
        "SELECT id, title, trashed_at FROM evidence_tables WHERE research_id = ?", (rid,))]


def rows(store, table_id):
    return {(r["source_version_id"], r["added_by"], r["removed_at"]) for r in store.conn.execute(
        "SELECT source_version_id, added_by, removed_at FROM table_rows WHERE table_id = ?", (table_id,))}


def test_create_takes_the_intent_refuses_papers_without_search_and_lists_it(tmp_path):
    client = open_client(make_app(tmp_path))
    try:
        default = create(client).json()
        papers = create(client, intent="papers")
        refused = create(client, source_scope="attached", intent="papers")
        invented = create(client, intent="summary")
        attached_report = create(client, source_scope="attached")
        listed = {r["id"]: r["intent"] for r in client.get("/api/researches").json()}
    finally:
        client.__exit__(None, None, None)
    assert default["research"]["intent"] == "report" and default["research"]["comparison_frame"] is None
    assert papers.status_code == 201 and papers.json()["research"]["intent"] == "papers"
    assert refused.status_code == 422 and "academic search" in refused.json()["detail"]
    assert invented.status_code == 422
    assert attached_report.status_code == 201
    assert listed[default["research"]["id"]] == "report" and listed[papers.json()["research"]["id"]] == "papers"
    assert len(listed) == 3  # the refused ones were never stored


def test_attached_table_and_compare_get_a_table_of_the_attached_files_without_discovery_or_answer(tmp_path):
    for intent_ in ("table", "compare"):
        app = make_app(tmp_path / intent_)
        client = open_client(app)
        try:
            store = app.state.store
            rid = create(client, source_scope="attached", intent=intent_).json()["research"]["id"]
            assert intent_tables(store, rid) == []  # nothing is attached yet
            first = upload(client, rid, "one.pdf", "first notes on method A.")
            second = upload(client, rid, "two.pdf", "second notes on method B.")
            tables = intent_tables(store, rid)
            table_rows = rows(store, tables[0]["id"])
            runs = [r["kind"] for r in store.conn.execute("SELECT kind FROM runs WHERE research_id = ?", (rid,))]
            columns = store.conn.execute("SELECT COUNT(*) FROM table_columns WHERE table_id = ?",
                                         (tables[0]["id"],)).fetchone()[0]
            frame = client.get(f"/api/researches/{rid}").json()["research"]["comparison_frame"]
            discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
        finally:
            client.__exit__(None, None, None)
        assert len(tables) == 1 and tables[0]["title"] == "Study table"
        # Explicit rows: the first file made the table, the second joined it.
        assert {(s, a) for s, a, _ in table_rows} == {(first, "user"), (second, "user")}
        assert runs == [] and columns == 0  # no discovery, no answer, no column run: columns start as by hand
        assert discovery.status_code == 422
        assert (frame is not None) == (intent_ == "compare")


def test_the_attached_table_is_one_per_research_across_retries_and_a_restart(tmp_path):
    app = make_app(tmp_path)
    client = open_client(app)
    try:
        store = app.state.store
        rid = create(client, source_scope="attached", intent="table").json()["research"]["id"]
        svid = upload(client, rid, "one.pdf", "first notes.")
        table_id = intent_tables(store, rid)[0]["id"]
        upload(client, rid, "one.pdf", "first notes.")  # the same file again
        assert intent.attached_ingested(store, rid) == table_id  # a retried hook
        before = rows(store, table_id)
    finally:
        client.__exit__(None, None, None)
    app = make_app(tmp_path)  # the same library, opened again
    client = open_client(app)
    try:
        store = app.state.store
        again = intent.attached_ingested(store, rid)
        tables, after = intent_tables(store, rid), rows(store, table_id)
    finally:
        client.__exit__(None, None, None)
    assert again == table_id and len(tables) == 1
    assert before == after == {(svid, "user", None)}


def test_a_removed_row_stays_removed_and_a_trashed_table_is_not_refilled(tmp_path):
    app = make_app(tmp_path)
    client = open_client(app)
    try:
        store = app.state.store
        rid = create(client, source_scope="attached", intent="compare").json()["research"]["id"]
        first = upload(client, rid, "one.pdf", "first notes.")
        table_id = intent_tables(store, rid)[0]["id"]
        version = lambda: store.conn.execute("SELECT version FROM evidence_tables WHERE id = ?", (table_id,)).fetchone()[0]
        assert client.delete(f"/api/researches/{rid}/tables/{table_id}/rows/{first}",
                             params={"expected_version": version()}).status_code == 200
        upload(client, rid, "one.pdf", "first notes.")  # uploading it again does not put the row back
        removed = rows(store, table_id)
        assert client.delete(f"/api/researches/{rid}/tables/{table_id}",
                             params={"expected_version": version()}).status_code == 200
        upload(client, rid, "two.pdf", "second notes.")
        after_trash = rows(store, table_id)
        tables = intent_tables(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert {(s, r is not None) for s, _, r in removed} == {(first, True)}
    assert len(tables) == 1 and tables[0]["trashed_at"] is not None and after_trash == removed


def test_report_and_mixed_scope_researches_get_no_table_from_an_upload(tmp_path):
    app = make_app(tmp_path)
    client = open_client(app)
    try:
        store = app.state.store
        report = create(client, source_scope="attached").json()["research"]["id"]
        mixed = create(client, source_scope="attached_and_academic", intent="table").json()["research"]["id"]
        upload(client, report, "one.pdf", "notes.")
        upload(client, mixed, "two.pdf", "notes.")
        found = intent_tables(store, report) + intent_tables(store, mixed)
    finally:
        client.__exit__(None, None, None)
    assert found == []  # the mixed one gets its table after discovery, from the included sources


def test_rows_from_before_the_intent_migration_read_as_reports(tmp_path, monkeypatch):
    old = tmp_path / "old_migrations"
    old.mkdir()
    migration = next(db.MIGRATIONS_DIR.glob("*_research_intent.sql"))
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if path.name.split("_", 1)[0] < migration.name.split("_", 1)[0]:
            shutil.copy(path, old / path.name)
    conn = db.connect(tmp_path / "library.sqlite")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_old', 'SYNTHETIC', 'now', 'now')")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migration.parent)
    db.migrate(conn)
    assert conn.execute("SELECT intent FROM researches WHERE id = 'res_old'").fetchone()[0] == "report"
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE researches SET intent = 'summary' WHERE id = 'res_old'")
    conn.close()


# ---- suggestions ------------------------------------------------------------------------------------------------------

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



def test_suggestions_skip_an_answer_out_of_date_for_its_selection_or_its_source_text(tmp_path):
    app = make_app(tmp_path)
    client = open_client(app)
    try:
        store = app.state.store
        kept = create(client, question="SYNTHETIC question kept", source_scope="attached").json()["research"]["id"]
        moved = create(client, question="SYNTHETIC question moved", source_scope="attached").json()["research"]["id"]
        replaced = create(client, question="SYNTHETIC question replaced", source_scope="attached").json()["research"]["id"]
        svid = upload(client, replaced, "one.pdf", "replaced notes.")
        kept_svid = upload(client, kept, "two.pdf", "kept notes.")
        passages = lambda s: [p["id"] for p in store.passages_for(s)]
        answer(store, kept, "2026-10-01T09:00:00", ["SYNTHETIC kept aspect"],
               selection_revision=store.research(kept)["selection_revision"], passage_ids=passages(kept_svid))
        # Answered at an earlier source selection than the research's current one.
        answer(store, moved, "2026-10-02T09:00:00", ["SYNTHETIC moved aspect"],
               selection_revision=store.research(moved)["selection_revision"] - 1)
        answer(store, replaced, "2026-10-03T09:00:00", ["SYNTHETIC replaced aspect"],
               selection_revision=store.research(replaced)["selection_revision"], passage_ids=passages(svid))
        before = [s["text"] for s in suggestions(store, limit=5)]
        asset = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()[0]
        store.remove_asset(replaced, svid, asset)  # the PDF that answer read is no longer in use
        after = [s["text"] for s in client.get("/api/suggestions").json()["suggestions"]]
    finally:
        client.__exit__(None, None, None)
    assert before == ["SYNTHETIC replaced aspect", "SYNTHETIC kept aspect"]
    assert after == ["SYNTHETIC kept aspect"]


def library_work(store, svid):
    return store.source(svid)["work_id"]


def test_an_attached_table_research_whose_sources_come_from_the_library_gets_its_table_and_rows(tmp_path):
    app = make_app(tmp_path)
    client = open_client(app)
    try:
        store = app.state.store
        donor = create(client, source_scope="attached").json()["research"]["id"]
        first, second = upload(client, donor, "one.pdf", "first library notes."), upload(client, donor, "two.pdf", "second notes.")
        rid = create(client, source_scope="attached", intent="table").json()["research"]["id"]
        added = client.post(f"/api/researches/{rid}/library-sources", json={"work_id": library_work(store, first)})
        tables_after_first = intent_tables(store, rid)
        rows_after_first = rows(store, tables_after_first[0]["id"]) if tables_after_first else None
        client.post(f"/api/researches/{rid}/library-sources", json={"work_id": library_work(store, second)})
        tables_after_second = intent_tables(store, rid)
        rows_after_second = rows(store, tables_after_second[0]["id"])
        # A source removed from the research and restored comes back as it was: its row is not added twice.
        removal = client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [second]})
        restored = client.post(f"/api/researches/{rid}/sources/restore", json={"source_version_ids": [second]})
        rows_after_restore = rows(store, tables_after_second[0]["id"])
    finally:
        client.__exit__(None, None, None)
    assert added.status_code == 201
    assert len(tables_after_first) == 1 and rows_after_first == {(first, "user", None)}
    assert len(tables_after_second) == 1 and rows_after_second == {(first, "user", None), (second, "user", None)}
    assert removal.status_code == 200 and restored.status_code == 200
    assert rows_after_restore == rows_after_second

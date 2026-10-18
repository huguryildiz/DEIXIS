"""Reverse citation search R3 (the screen's backend needs): one sentence limit on every path that stores or checks a
statement research's sentence, and what the view and preview say while an attached-scope check waits for its files.
Records and model answers are SYNTHETIC; no real model or network is used."""

import json

import pytest

from deixis.domain import statement
from deixis.workflow import statement_check
from test_abstract_flow import Pool, app_for, client_of
from test_criterion_passage_flow import TOPIC_PAGE, page_source
from test_statement_check import ABSTRACT, MODEL, build, execute, items
from test_statement_check_r2 import attached, statement_research

LONG = "a" * (statement.MAX_SENTENCE_CHARS + 1)


def test_http_a_question_revision_of_a_statement_research_keeps_the_600_character_limit(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([]))
    client = client_of(app)
    try:
        rid = statement_research(client)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        refused = client.post(f"/api/researches/{rid}/scope", json={"question": LONG, "expected_version": version})
        assert refused.status_code == 422 and "600" in refused.json()["detail"]
        view = client.get(f"/api/researches/{rid}").json()
        assert view["research"]["current_scope_revision"] == 1 and view["scope"]["question"] != LONG
        # Exactly the limit is a sentence; whitespace around it is not counted.
        fits = client.post(f"/api/researches/{rid}/scope",
                           json={"question": f"  {'b' * statement.MAX_SENTENCE_CHARS}  ", "expected_version": version})
        assert fits.status_code == 200 and fits.json()["research"]["current_scope_revision"] == 2
    finally:
        client.__exit__(None, None, None)


def test_a_report_research_revision_is_not_held_to_the_statement_limit(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([]))
    client = client_of(app)
    try:
        made = client.post("/api/researches", json={"question": "SYNTHETIC report question", "model_connection": "fake",
                                                     "requested_model": "fake-model", "intent": "report"}).json()
        revised = client.post(f"/api/researches/{made['research']['id']}/scope",
                              json={"question": LONG, "expected_version": made["research"]["version"]})
        assert revised.status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_the_store_and_a_check_request_refuse_a_sentence_over_the_limit(tmp_path):
    lib = build(tmp_path, n=1)
    research = lib.store.research(lib.rid)
    with pytest.raises(statement.StatementTooLong):
        lib.store.revise_scope(lib.rid, research["version"], LONG, None)
    assert lib.store.research(lib.rid)["current_scope_revision"] == research["current_scope_revision"]
    # A sentence stored before the limit held on every path is refused at the check, never sent.
    lib.store.conn.execute("UPDATE scope_revisions SET question = ? WHERE research_id = ?", (LONG, lib.rid))
    attached(lib)
    with pytest.raises(statement_check.Refused) as refused:
        statement_check.request(lib.flow, lib.rid, "req-long", MODEL)
    assert refused.value.code == "sentence_too_long"
    assert lib.store.conn.execute("SELECT COUNT(*) FROM statement_checks").fetchone()[0] == 0


def test_a_check_waiting_for_attached_files_says_so_in_its_view_and_preview_then_resumes(tmp_path):
    """Extraction pending → the run pauses before any item exists → the view names the wait, the preview's cost is
    unknown (never zero) → the file is read → the resumed run freezes the list and checks it."""
    lib = build(tmp_path, n=0)
    attached(lib)
    one = page_source(lib.store, lib.rid, "one", [TOPIC_PAGE], ABSTRACT)
    asset = lib.store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (one,)).fetchone()[0]
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'pending' WHERE id = ?", (asset,))
    check = statement_check.request(lib.flow, lib.rid, "req-1", MODEL)
    run = execute(lib, check)
    assert (run["status"], run["pause_reason"]) == ("paused", "attachments_extracting")
    view = statement_check.view(lib.store, check["id"])
    assert view["attachment_snapshot"] == {"status": "waiting"} and view["items"] == []
    assert view["run"]["status"] == "paused" and view["run"]["pause_reason"] == "attachments_extracting"
    assert view["counters"]["by_status"]["planned"] == 0  # nothing to count yet: the screen reads the wait itself
    preview = statement_check.preview(lib.store, check["id"])
    assert preview["waiting"] is True and preview["cost"]["usd"] == "unknown"
    assert preview["cost"]["reason"] == "attachments_extracting"
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'succeeded' WHERE id = ?", (asset,))
    lib.store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    view = statement_check.view(lib.store, check["id"])
    assert json.loads(statement_check.check_row(lib.store, check["id"])["attachment_snapshot_json"])["status"] == "frozen"
    assert [i["status"] for i in items(lib, check)] == ["done"] and view["sentence"] == view["sentence"].strip()

"""Withdrawing a question revision (D67): allowed while nothing but a title run and a person's selection decisions was
made under it; nothing is deleted, a withdrawn number is never used again, and a later revision opens from the one the
research went back to. SYNTHETIC rows."""

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store

PLAN = {"schema_version": "deixis.user_search_plan.v1", "setting": [{"term": "rail freight"}],
        "task": [{"term": "timetable"}], "setting_backup": [], "task_backup": [], "criterion": None,
        "providers": ["openalex"]}


def store_for(tmp_path):
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    rid = store.create_research("SYNTHETIC rail freight timetables?", "academic", "quick", ["openalex"],
                                "fake", "fake-model", "en")
    return store, rid


def revise(store, rid, question):
    return store.revise_scope(rid, store.research(rid)["version"], question, None)


def withdraw(store, rid):
    research = store.research(rid)
    return store.withdraw_revision(rid, research["version"], research["current_scope_revision"])


def test_a_withdrawn_revision_stays_as_history_and_its_number_is_not_used_again(tmp_path):
    store, rid = store_for(tmp_path)
    store.conn.execute("INSERT INTO scope_english_questions (research_id, scope_revision, text, origin, created_at)"
                       " VALUES (?, 1, 'SYNTHETIC sentence', 'question', 'now')", (rid,))
    store.rename_research(rid, store.research(rid)["version"], "SYNTHETIC first title")
    assert revise(store, rid, "SYNTHETIC write the report from the full texts") == 2
    assert store.research(rid)["title"] == "SYNTHETIC write the report from the full texts"
    assert store.withdrawal(rid)["allowed"] and store.withdrawal(rid)["restores_title"]
    assert withdraw(store, rid) == 1
    research = store.research(rid)
    assert research["current_scope_revision"] == 1 and research["title"] == "SYNTHETIC first title"
    assert store.scope(rid, 2)["withdrawn_at"] is not None  # kept, not deleted
    assert store.withdrawal(rid) | {"allowed": False} == store.withdrawal(rid)  # revision 1 opened from none
    # The next revision takes the next free number and opens from revision 1, with revision 1's English sentence.
    store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC rail freight timetables?", None)
    scope = store.scope(rid)
    assert scope["revision"] == 3 and scope["parent_revision"] == 1
    assert store.english_question(rid, 3)["text"] == "SYNTHETIC sentence"
    types = [r[0] for r in store.conn.execute("SELECT type FROM events WHERE research_id = ? ORDER BY rowid", (rid,))]
    assert "scope_revision_withdrawn" in types


def test_a_plan_revision_opens_from_the_current_one_after_a_withdrawal(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    withdraw(store, rid)
    revision = store.save_user_plan(rid, store.research(rid)["version"], PLAN)
    scope = store.scope(rid)
    assert revision == 3 and scope["parent_revision"] == 1 and scope["question"] == store.scope(rid, 1)["question"]


def test_a_person_renaming_after_the_revision_keeps_their_title(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    store.rename_research(rid, store.research(rid)["version"], "SYNTHETIC title the person wrote")
    withdraw(store, rid)
    assert store.research(rid)["title"] == "SYNTHETIC title the person wrote"


def test_work_made_under_the_revision_keeps_it(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    sv = store.create_upload_source("SYNTHETIC study")
    store.add_to_corpus(rid, sv, "user_upload", selection_state="included", selection_origin="user")
    # A completed title run and a person's decision under it do not count as work on the question.
    title = store.create_run(rid, "research_title", {}, None)
    store.update_run(title["id"], status="completed")
    DecisionStore(store).record(rid, sv, "human_include")
    assert store.withdrawal(rid)["allowed"]
    # A paused run blocks; so does a search run, and a model's or code's decision.
    paused = store.create_run(rid, "answer", {}, None)
    store.update_run(paused["id"], status="paused")
    assert store.withdrawal(rid)["reason"] == "run_active"
    store.update_run(paused["id"], status="completed")
    assert store.withdrawal(rid)["reason"] == "made_under:runs"
    with pytest.raises(RevisionConflict):
        withdraw(store, rid)
    assert store.research(rid)["current_scope_revision"] == 2


def test_a_decision_by_code_under_the_revision_keeps_it(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    sv = store.create_upload_source("SYNTHETIC study")
    store.add_to_corpus(rid, sv, "user_upload", selection_state="included", selection_origin="user")
    DecisionStore(store).record(rid, sv, "no_abstract")
    assert store.withdrawal(rid)["reason"] == "made_under:stage_decisions"


def test_only_the_current_revision_at_the_version_shown_can_be_withdrawn(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    version = store.research(rid)["version"]
    with pytest.raises(RevisionConflict):
        store.withdraw_revision(rid, version, 1)
    with pytest.raises(RevisionConflict):
        store.withdraw_revision(rid, version - 1, 2)
    assert store.withdraw_revision(rid, version, 2) == 1
    with pytest.raises(RevisionConflict):  # already withdrawn: revision 2 is no longer current
        store.withdraw_revision(rid, store.research(rid)["version"], 2)


def test_the_migration_names_each_earlier_revisions_parent(tmp_path, monkeypatch):
    import shutil
    real = db.MIGRATIONS_DIR
    number = int(next(p for p in real.glob("*.sql") if p.name.endswith("_scope_revision_withdraw.sql")).name.split("_", 1)[0])
    older = tmp_path / "older"
    older.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < number:
            shutil.copy(path, older / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    rid = store.create_research("SYNTHETIC old question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    store.conn.execute("INSERT INTO scope_revisions (research_id, revision, question, source_scope, providers_json,"
                       " effort, model_connection, requested_model, created_at) SELECT research_id, 2, 'SYNTHETIC second',"
                       " source_scope, providers_json, effort, model_connection, requested_model, created_at"
                       " FROM scope_revisions WHERE research_id = ?", (rid,))
    store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (rid,))
    store._event(rid, "scope_revised", {"scope_revision": 2})
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    assert number in db.migrate(store.conn)
    assert store.scope(rid, 1)["parent_revision"] is None and store.scope(rid, 2)["parent_revision"] == 1
    check = store.withdrawal(rid)
    assert check["allowed"] and not check["restores_title"]


def test_the_revision_current_at_a_time_follows_a_withdrawal(tmp_path):
    from types import SimpleNamespace
    from deixis.storage.db import now
    from deixis.workflow import overrides
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    during = now()
    ctx = SimpleNamespace(store=store, rid=rid)
    assert overrides._key_at(ctx, during)[0] == 2
    withdraw(store, rid)
    assert overrides._key_at(ctx, now())[0] == 1 and overrides._key_at(ctx, during)[0] == 2
    revise(store, rid, "SYNTHETIC third question")
    assert overrides._key_at(ctx, now())[0] == 3


def test_the_route_withdraws_and_says_why_it_cannot(tmp_path):
    from fastapi.testclient import TestClient
    from test_api_flow import app_for, session
    from fakes import FakeAdapter
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid = client.post("/api/researches", json={"question": "SYNTHETIC rail freight timetables?", "source_scope": "attached",
                                                    "effort": "quick", "providers": [], "model_connection": "fake",
                                                    "requested_model": "fake-model"}).json()["research"]["id"]
        view = client.get(f"/api/researches/{rid}").json()
        assert view["research"]["revision_withdrawal"]["reason"] == "first_revision"
        view = client.post(f"/api/researches/{rid}/scope", json={"question": "SYNTHETIC other question",
                                                                  "expected_version": view["research"]["version"]}).json()
        assert view["research"]["revision_withdrawal"]["allowed"]
        stale = client.post(f"/api/researches/{rid}/scope/withdraw", json={"expected_version": view["research"]["version"], "revision": 1})
        assert stale.status_code == 409
        back = client.post(f"/api/researches/{rid}/scope/withdraw", json={"expected_version": view["research"]["version"], "revision": 2})
        assert back.status_code == 200 and back.json()["research"]["current_scope_revision"] == 1


def test_a_table_made_or_a_cell_edited_after_the_revision_keeps_it(tmp_path):
    from deixis.workflow.tables import TableStore
    from test_evidence_tables import PACKET_SIZE
    store, rid = store_for(tmp_path)
    sv = store.create_upload_source("SYNTHETIC study")
    store.add_to_corpus(rid, sv, "user_upload", selection_state="included", selection_origin="user")
    tables = TableStore(store)
    tid = tables.create_table(rid, "SYNTHETIC table", [sv], None, None)
    cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
    # A cell edited under the revision: the cell names no revision, its event does.
    revise(store, rid, "SYNTHETIC other question")
    assert store.withdrawal(rid)["allowed"]
    tables.edit_cell(rid, tid, cid, sv, "not_verified", {"number": 70, "unit": "byte"}, None, None, 0, None)
    assert store.withdrawal(rid)["reason"] == "done_after:cell_revision_saved"
    with pytest.raises(RevisionConflict):
        withdraw(store, rid)
    # A table made under a later revision keeps that one too.
    revise(store, rid, "SYNTHETIC third question")
    assert store.withdrawal(rid)["allowed"]
    tables.create_table(rid, "SYNTHETIC second table", [sv], None, None)
    assert store.withdrawal(rid)["reason"] == "done_after:table_changed"


def test_revisions_withdrawn_one_after_another_go_back_to_the_first(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC second question")
    revise(store, rid, "SYNTHETIC third question")
    title = store.create_run(rid, "research_title", {}, None)  # the third revision's title run
    store.update_run(title["id"], status="completed")
    assert withdraw(store, rid) == 2
    assert store.withdrawal(rid)["allowed"]
    assert withdraw(store, rid) == 1
    assert store.research(rid)["current_scope_revision"] == 1

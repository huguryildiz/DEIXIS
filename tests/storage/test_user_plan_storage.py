"""Storage of a person's search plan (UI parity S23a, F18): one nullable column on scope revisions, set only by the
save route, never carried over by another revision, and earlier revisions read as having none. SYNTHETIC rows."""

from deixis.storage import db
from deixis.workflow.store import Store

PLAN = {"schema_version": "deixis.user_search_plan.v1", "setting": [{"term": "rail freight"}],
        "task": [{"term": "timetable"}], "setting_backup": [], "task_backup": [], "criterion": None,
        "providers": ["openalex"]}


def store_for(tmp_path):
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    rid = store.create_research("SYNTHETIC rail freight timetables?", "academic", "quick", ["openalex", "crossref"],
                                "fake", "fake-model", "en")
    return store, rid


def test_a_saved_plan_is_a_new_revision_and_no_other_revision_carries_it_over(tmp_path):
    store, rid = store_for(tmp_path)
    store.conn.execute("INSERT INTO scope_english_questions (research_id, scope_revision, text, origin, created_at)"
                       " VALUES (?, 1, 'SYNTHETIC sentence', 'question', 'now')", (rid,))
    revision = store.save_user_plan(rid, store.research(rid)["version"], PLAN)
    scope = store.scope(rid)
    assert revision == scope["revision"] == 2 and scope["user_plan"] == PLAN
    assert store.scope(rid, 1)["user_plan"] is None
    assert store.english_question(rid, 2)["text"] == "SYNTHETIC sentence"
    assert scope["question"] == store.scope(rid, 1)["question"] and scope["providers"] == ["openalex", "crossref"]
    store.revise_scope(rid, store.research(rid)["version"], scope["question"], None)
    assert store.scope(rid)["revision"] == 3 and store.scope(rid)["user_plan"] is None
    assert store.scope(rid, 2)["user_plan"] == PLAN  # the saved revision is never edited

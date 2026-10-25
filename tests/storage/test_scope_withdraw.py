"""Withdrawing a question revision (D67): allowed while nothing but a title run and a person's selection decisions was
made under it; nothing is deleted, a withdrawn number is never used again, and a later revision opens from the one the
research went back to. SYNTHETIC rows."""


from deixis.storage import db
from deixis.workflow.run.store import Store

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


def test_a_person_renaming_after_the_revision_keeps_their_title(tmp_path):
    store, rid = store_for(tmp_path)
    revise(store, rid, "SYNTHETIC other question")
    store.rename_research(rid, store.research(rid)["version"], "SYNTHETIC title the person wrote")
    withdraw(store, rid)
    assert store.research(rid)["title"] == "SYNTHETIC title the person wrote"


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




def test_a_generated_title_never_replaces_the_one_the_person_wrote(tmp_path):
    """Discovery-time naming and a valid answer rename the research, until the person names it; a new question
    revision names it after its question again."""
    store, rid = store_for(tmp_path)

    def answer(title):
        run = store.create_run(rid, "answer", {}, None)
        store.save_answer(rid, run["id"], None, None, store.research(rid)["current_scope_revision"], "structurally_valid",
                          {"title": title, "answer_language": "en", "claims": []}, {}, [])
        store.update_run(run["id"], status="completed")

    store.set_research_title(rid, 1, "SYNTHETIC generated title")
    answer("SYNTHETIC answer title")
    assert store.research(rid)["title"] == "SYNTHETIC answer title"
    store.rename_research(rid, store.research(rid)["version"], "SYNTHETIC title the person wrote")
    store.set_research_title(rid, 1, "SYNTHETIC later generated title")
    answer("SYNTHETIC later answer title")
    assert store.research(rid)["title"] == "SYNTHETIC title the person wrote"
    plan_revision = store.save_user_plan(rid, store.research(rid)["version"], PLAN)  # same question, so the title stays theirs
    store.set_research_title(rid, plan_revision, "SYNTHETIC generated title after the plan")
    answer("SYNTHETIC answer title after the plan")
    assert store.research(rid)["title"] == "SYNTHETIC title the person wrote"
    revise(store, rid, "SYNTHETIC an interim question")
    withdraw(store, rid)  # back to the person's question and title, still theirs
    answer("SYNTHETIC answer title after the withdrawal")
    assert store.research(rid)["title"] == "SYNTHETIC title the person wrote"
    revise(store, rid, "SYNTHETIC a new question")
    answer("SYNTHETIC answer to the new question")
    assert store.research(rid)["title"] == "SYNTHETIC answer to the new question"

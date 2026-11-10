"""A research of its own, opened from a follow-up question that moved to another setting.

SYNTHETIC records and the fake adapter: these cases say what the branch starts with and what it refuses to carry
(this research's criterion, screening, sources, seeds and report), that one question opens one branch, and that
purging either research leaves the other standing. They say nothing about whether a branch answers better.
"""

import pytest
from fastapi.testclient import TestClient

from deixis.workflow.features.branch import branch_research
from test_api_flow import app_for, create, session
from test_followup_turns import answered, research, revision

MOVED = "Now let us look at this for aerial networks. [scope-change]"


@pytest.fixture
def live(tmp_path):
    """The application over one temporary library, as the API tests run it (the worker runs the turn's own run)."""
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        yield app, client


def _published(client, question=MOVED):
    rid, _ = research(client)
    return rid, answered(client, rid, question)


def _branch(client, rid, turn_id, question="How is routing studied in aerial networks?", expected=None):
    return client.post(f"/api/researches/{rid}/followup-turns/{turn_id}/branch",
                       json={"question": question, "expected_scope_revision": expected or revision(client, rid)})


def test_a_question_that_moved_opens_a_research_of_its_own_with_none_of_this_ones_scope(live):
    app, client = live
    rid, turn = _published(client)
    # The model read the question as moving elsewhere, so the offer is the suggested one and carries its note.
    assert turn["branch"] == {"offered": True, "not_offered_reason": None, "emphasis": "suggested",
                              "note": "another synthetic setting", "research_id": None}
    response = _branch(client, rid, turn["id"])
    assert response.status_code == 201, response.text
    branch = response.json()
    parent = client.get(f"/api/researches/{rid}").json()
    # How the research runs comes from the one it was opened from; what that research found does not.
    assert branch["scope"]["question"] == "How is routing studied in aerial networks?"
    for same in ("source_scope", "effort", "model_connection", "requested_model", "review_mode"):
        assert branch["scope"][same] == parent["scope"][same], same
    assert branch["scope"]["key_terms"] in (None, "") and not branch["scope"]["steering"]
    assert branch["sources"] == [] and branch["answers"] == [] and branch["scope"]["seeds"] == []
    assert branch["research"]["id"] != rid
    # Both screens say where it came from, and the question says a branch was opened.
    assert branch["branched_from"]["research_id"] == rid
    assert branch["branched_from"]["question"] == MOVED
    again = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
    assert again["branch"]["research_id"] == branch["research"]["id"]
    assert again["branch"]["offered"] is False and again["branch"]["not_offered_reason"] == "branch_opened"


def test_one_question_opens_one_research(live):
    """A second press finds the first branch instead of opening another."""
    app, client = live
    rid, turn = _published(client)
    first = _branch(client, rid, turn["id"])
    assert first.status_code == 201, first.text
    second = _branch(client, rid, turn["id"], question="Another synthetic question")
    assert second.status_code == 422 and second.json()["code"] == "branch_opened"
    listing = client.get("/api/researches").json()
    assert len(listing if isinstance(listing, list) else listing["researches"]) == 2


def test_a_question_with_no_published_answer_opens_nothing(live):
    """A turn still being answered has nothing for the person to have moved on from."""
    app, client = live
    rid, turn = _published(client)
    pending = dict(app.state.store.conn.execute(
        "SELECT * FROM followup_turns WHERE id = ?", (turn["id"],)).fetchone()) | {
        "status": "pending", "draft_json": None}
    offered = branch_research.offer(app.state.store, pending)
    assert offered["offered"] is False and offered["not_offered_reason"] == "turn_not_published"
    # And the rule the route applies is the same one, read from the stored row (`check`).
    assert branch_research.offer(app.state.store, dict(pending) | {"status": "answered"})["offered"] is True


def test_an_answer_the_model_read_as_staying_here_still_offers_a_branch_quietly(live):
    """The person may always open a research of their own; the model's reading only sets the emphasis."""
    app, client = live
    rid, turn = _published(client, question="Which binary variable decides the release time slot?")
    assert turn["branch"]["offered"] is True and turn["branch"]["emphasis"] == "quiet"
    assert turn["branch"]["note"] is None
    assert _branch(client, rid, turn["id"]).status_code == 201


def test_a_question_revised_since_the_answer_opens_nothing(live):
    app, client = live
    rid, turn = _published(client)
    response = _branch(client, rid, turn["id"], expected=revision(client, rid) + 1)
    assert response.status_code == 409, response.text


def test_purging_the_research_it_came_from_leaves_the_branch_standing(live):
    app, client = live
    rid, turn = _published(client)
    branch_id = _branch(client, rid, turn["id"]).json()["research"]["id"]
    store = app.state.store
    store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", ("2026-11-10T00:00:00Z", rid))
    store.purge_research(rid)
    came_from = branch_research.of_research(store, branch_id)
    # The branch is a research of its own: it stays, and says it came from one that is gone.
    assert came_from is not None
    assert came_from["research_id"] is None and came_from["turn_id"] is None and came_from["question"] is None
    assert store.research(branch_id)["id"] == branch_id


def test_purging_the_branch_leaves_the_research_it_came_from_standing(live):
    app, client = live
    rid, turn = _published(client)
    branch_id = _branch(client, rid, turn["id"]).json()["research"]["id"]
    store = app.state.store
    store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", ("2026-11-10T00:00:00Z", branch_id))
    store.purge_research(branch_id)
    assert branch_research.of_turn(store, turn["id"]) is None
    assert store.research(rid)["id"] == rid
    # And the question offers a branch again: the one it opened is gone.
    again = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
    assert again["branch"]["offered"] is True and again["branch"]["research_id"] is None


def test_a_question_revised_while_the_models_are_checked_opens_nothing(live):
    """The settings a branch inherits are read before the models are checked; a revision in between is another
    question, so the rule is read again inside the write (`branch_research.check`)."""
    app, client = live
    rid, turn = _published(client)
    store = app.state.store
    store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC another question entirely", None)
    with pytest.raises(branch_research.BranchRefused) as refused:
        branch_research.check(store, rid, turn["id"])
    assert refused.value.code == "not_current_revision"
    # And the route refuses too, with the revision the person was looking at.
    assert _branch(client, rid, turn["id"], expected=1).status_code == 409


def test_the_branch_keeps_no_language_or_field_of_the_question_it_came_from(live):
    """The language hint belongs to the question it was saved with, and a sentence's field to that sentence."""
    app, client = live
    rid, _ = research(client)
    app.state.store.conn.execute("UPDATE scope_revisions SET language_hint = 'tr', statement_field = 'underwater networks'"
                                 " WHERE research_id = ?", (rid,))
    turn = answered(client, rid, MOVED)
    branch = _branch(client, rid, turn["id"]).json()
    assert branch["scope"]["language_hint"] is None
    assert branch["scope"]["statement_field"] is None


def test_a_turn_with_no_report_version_to_add_can_still_open_a_research_of_its_own(live):
    """An answer the citation check could not pass is still a question that may belong somewhere else."""
    from deixis.workflow.answer import followup

    app, client = live
    rid, turn = _published(client)
    store = app.state.store
    # A published turn is never edited (the library's own rule), so the status is read as the view would read it.
    row = dict(store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn["id"],)).fetchone())
    view = followup.turn_view(store, row | {"status": "unverified_draft"})
    assert view["report_change"] is None  # there is no version to add
    assert view["branch"]["offered"] is True
    # And the write path takes it: the rules a branch applies do not include the citation check.
    assert branch_research.check(store, rid, turn["id"])["id"] == turn["id"]


def test_a_turn_of_an_older_question_offers_no_branch(live):
    """The offer applies the rule the write applies, so the person is not refused at the last step."""
    app, client = live
    rid, turn = _published(client)
    store = app.state.store
    store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC another question entirely", None)
    view = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
    assert view["branch"]["offered"] is False
    assert view["branch"]["not_offered_reason"] == "not_current_revision"


def test_a_turn_that_had_no_passage_to_read_opens_a_research_of_its_own(live):
    """Stored as the application stores it: a question this research could not read anything for is still a
    question, and the branch rules do not ask for an answer."""
    from deixis.storage.db import new_id, now

    app, client = live
    rid, _ = research(client)
    store = app.state.store
    run = store.create_run(rid, "followup_answer", {"max_model_calls": 1}, None, target={"turn_id": "fut_pending"})
    store.update_run(run["id"], status="completed")
    turn_id = new_id("fut")
    store.conn.execute(
        "INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at,"
        " published_at, selection_revision, user_signature) VALUES (?, ?, 1, ?, ?, 'no_passages', ?, ?, 0, 'synthetic')",
        (turn_id, rid, MOVED, run["id"], now(), now()))
    view = client.get(f"/api/researches/{rid}/followup-turns/{turn_id}").json()
    assert view["report_change"] is None and view["branch"]["offered"] is True
    assert _branch(client, rid, turn_id).status_code == 201

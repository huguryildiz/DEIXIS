"""The person's own "Add this to the report" on a published follow-up answer.

SYNTHETIC records and no model: these cases say which attempt a click gets, that a chain writes one report version
whether the model's own flag or the person asked for it, and that a run which wrote nothing does not swallow the
next click. They say nothing about whether the new report version is better.
"""

import json

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, now
from fastapi.testclient import TestClient

from deixis.workflow.answer import followup
from test_api_flow import app_for, session, wait_run
from test_followup_revision import _idle, _library, _published, _turn
from test_followup_turns import answered, research, revision


@pytest.fixture
def live(tmp_path):
    """The application over one temporary library: the worker runs the report version this test asks for."""
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        yield app, client


def _answered(client):
    """A research with one published follow-up answer, as the person leaves it before clicking."""
    rid, _ = research(client)
    return rid, answered(client, rid)


def _report_runs(lib):
    return [dict(row) for row in lib.store.conn.execute(
        "SELECT id, idempotency_key, status FROM runs WHERE research_id = ? AND kind = 'answer'"
        " ORDER BY created_at, rowid", (lib.rid,))]


def _wrote(lib, run_id, version=1, status="structurally_valid"):
    """A report version this run wrote, as the answer row records it."""
    lib.store.conn.execute(
        "INSERT INTO answers (id, research_id, run_id, scope_revision, status, validation_json, created_at,"
        " report_version) VALUES (?, ?, ?, 1, ?, '{}', ?, ?)",
        (new_id("ans"), lib.rid, run_id, status, now(), version))


def _ask(lib, turn):
    return followup.request_report_change(lib.store, lib.rid, turn["id"], 1)


def test_the_person_asks_for_the_report_version_the_model_did_not(tmp_path):
    """Adding an answer to the report is the person's own action, not something a model's reading decides."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)  # the draft asks for no report change
    _idle(lib)
    run = _ask(lib, first)
    assert run["target"]["report_request"] == {"turn_id": first["id"], "text": first["question"]}
    # The first attempt is the key the model's own flag has always used, so one chain writes one version.
    assert run["idempotency_key"] == followup.report_run_key(first["id"])


def test_the_model_flag_and_the_button_write_one_version_for_one_question(tmp_path):
    lib = _library(tmp_path)
    turn, run = _turn(lib, search=False)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    followup.after_turn(lib.store, lib.store.run(run["id"]))  # the flag queued it
    queued = _report_runs(lib)
    assert len(queued) == 1
    lib.store.update_run(queued[0]["id"], status="running")
    with pytest.raises(RevisionConflict):
        _ask(lib, first)  # the same attempt is still going
    assert len(_report_runs(lib)) == 1


def test_a_report_run_that_wrote_a_version_takes_no_second_try(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    run = _ask(lib, first)
    lib.store.update_run(run["id"], status="completed")
    _wrote(lib, run["id"])
    with pytest.raises(followup.ReportChangeRefused, match="already wrote"):
        _ask(lib, first)
    assert len(_report_runs(lib)) == 1


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_report_run_that_ended_without_a_version_gives_the_next_click_its_own_attempt(tmp_path, status):
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    run = _ask(lib, first)
    lib.store.update_run(run["id"], status=status)
    again = _ask(lib, first)
    assert again["id"] != run["id"]
    assert again["idempotency_key"] == f"{followup.report_run_key(first['id'])}:a2"


def test_a_completed_report_run_that_wrote_no_valid_version_does_not_swallow_the_click(tmp_path):
    """Only a valid answer opens a report version; a run that completed with a draft left the report unchanged."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    run = _ask(lib, first)
    lib.store.update_run(run["id"], status="completed")
    _wrote(lib, run["id"], status="unverified_draft")
    again = _ask(lib, first)
    assert again["idempotency_key"] == f"{followup.report_run_key(first['id'])}:a2"


def test_a_paused_report_run_is_the_same_attempt(tmp_path):
    """A paused run resumes, so a new key would pay twice for the work it has already done."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    run = _ask(lib, first)
    lib.store.update_run(run["id"], status="running")
    lib.store.update_run(run["id"], status="paused", pause_reason="backend_restarted")
    with pytest.raises(RevisionConflict, match="still active"):
        _ask(lib, first)
    assert len(_report_runs(lib)) == 1
    view = followup.report_change_view(lib.store, _row(lib, first["id"]))
    assert view["offered"] is False and view["not_offered_reason"] == "report_change_running"
    assert view["attempts"] == 1


def test_a_turn_that_answers_again_shares_the_first_turns_report_version(tmp_path):
    """One question, one report version: the chain's key is the question the person asked."""
    from deixis.workflow.answer import followup_revision as revision
    from test_followup_revision import _search_run

    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    _published(lib, second)
    _idle(lib)
    run = _ask(lib, second)
    assert run["idempotency_key"] == followup.report_run_key(first["id"])
    lib.store.update_run(run["id"], status="completed")
    _wrote(lib, run["id"])
    with pytest.raises(followup.ReportChangeRefused):
        _ask(lib, first)  # asking from the first turn of the same chain is the same version


def test_a_turn_with_no_published_answer_asks_for_nothing(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    _idle(lib)
    with pytest.raises(followup.ReportChangeRefused, match="no published answer"):
        followup.request_report_change(lib.store, lib.rid, turn["id"], 1)


def test_a_question_revised_since_the_answer_asks_for_nothing(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC other question", None)
    with pytest.raises(Exception):
        followup.request_report_change(lib.store, lib.rid, first["id"], 1)


def _row(lib, turn_id):
    return dict(lib.store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn_id,)).fetchone())


def test_the_view_says_the_version_this_chain_wrote(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    run = _ask(lib, first)
    lib.store.update_run(run["id"], status="completed")
    _wrote(lib, run["id"], version=3)
    view = followup.report_change_view(lib.store, _row(lib, first["id"]))
    assert view["report_version"] == 3 and view["answer_status"] == "structurally_valid"
    assert view["offered"] is False and view["not_offered_reason"] == "already_written"
    assert json.loads(lib.store.conn.execute(
        "SELECT payload_json FROM events WHERE type = 'report_change_asked' ORDER BY id DESC LIMIT 1",
    ).fetchone()[0])["attempt"] == 1


def test_the_report_version_the_person_asked_for_is_really_written(live):
    """End to end with the fake model: the click opens the research's next report version, which is what the
    screen then says. The Evidence report, a separate artifact with its own versions, is not touched by this."""
    app, client = live
    rid, turn = _answered(client)
    before = [a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]
    response = client.post(f"/api/researches/{rid}/followup-turns/{turn['id']}/report",
                           json={"expected_scope_revision": revision(client, rid)})
    assert response.status_code == 202, response.text
    wait_run(client, rid, response.json()["report_run_id"])
    after = [a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]
    assert len(after) == len(before) + 1
    written = max(after, key=lambda a: a["report_version"] or 0)
    assert written["report_version"] == max([a["report_version"] or 0 for a in before] + [0]) + 1
    # And the turn says that version, and offers no second one.
    again = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
    assert again["report_change"]["report_version"] == written["report_version"]
    assert again["report_change"]["offered"] is False
    assert again["report_change"]["not_offered_reason"] == "already_written"
    # The Evidence report is its own artifact: this wrote none and claims none.
    assert client.get(f"/api/researches/{rid}").json()["reportRuns"] == []


def test_a_question_revised_after_the_version_still_says_which_version_it_wrote(tmp_path):
    """What happened is still true: the revision stops another version, it does not unwrite this one."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    run = _ask(lib, first)
    lib.store.update_run(run["id"], status="completed")
    _wrote(lib, run["id"], version=2)
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC other question", None)
    view = followup.report_change_view(lib.store, _row(lib, first["id"]))
    assert view["report_version"] == 2 and view["not_offered_reason"] == "already_written"
    assert view["offered"] is False


def test_the_attempts_of_a_chain_are_read_by_their_own_keys(tmp_path):
    """Each attempt is one lookup on the unique key, and the reading stops at the first key no run holds."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib, search=False)
    first = _published(lib, turn)
    _idle(lib)
    keys = []
    for _ in range(3):
        run = _ask(lib, first)
        keys.append(run["idempotency_key"])
        lib.store.update_run(run["id"], status="failed", pause_reason="model_failed")
    base = followup.report_run_key(first["id"])
    assert keys == [base, f"{base}:a2", f"{base}:a3"]
    assert [r["idempotency_key"] for r in followup._report_runs(lib.store, first["id"])] == keys

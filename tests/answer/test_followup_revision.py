"""The second answer of one follow-up question, from the works its own search found.

SYNTHETIC records and no model: these cases say which works the revision may read, that the chain runs in one
order (answer, search, answer again, report request once), that the person's selections travel as they were frozen,
and that a research purge still deletes a chain. They say nothing about whether a second answer is better.
"""

import asyncio
import json

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, now
from deixis.workflow.answer import followup, followup_revision as revision
from deixis.workflow.search import followup_search
from test_fast_path_answer import setup, user
from test_followup_attachments import quiet, work_of

QUESTION = "Which SYNTHETIC field trials came after the ones already here?"


def _library(tmp_path, n=2):
    lib = setup(tmp_path, n=n)
    quiet(lib)
    # A search is offered only after a discovery that approved a protocol, and only while no run is active.
    step = lib.store.step(lib.discovery["id"], "protocol_approval", "code:protocol_approval")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "succeeded", output={"approved": {
        "vocabulary": {"question_words": ["synthetic"]}, "queries": [{"query_text": "SYNTHETIC"}]}})
    lib.store.update_run(lib.discovery["id"], status="completed")
    return lib


def _turn(lib, search=True, attachments=None):
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None, attachments, search)
    run = lib.store.run(turn["run_id"])
    lib.store.update_run(run["id"], status="running")
    return dict(turn), lib.store.run(run["id"])


def _step_input(lib, run_id):
    """One stored model input of this run, which a published turn has to point at."""
    step = lib.store.step(run_id, "followup_answer", "model:followup_answer")
    step_input_id = new_id("sti")
    lib.store.insert_step_input(step["id"], lib.rid, run_id, 1, {
        "step_input_id": step_input_id, "task_type": "followup_answer", "scope_revision": 1,
        "skill_package_hash": "synthetic"}, "b", "d", "m", {"type": "object"})
    return step_input_id


def _published(lib, turn, status="answered", draft=None):
    """The first turn as its own run left it: published, with the draft the model wrote."""
    lib.store.conn.execute(
        "UPDATE followup_turns SET status = ?, published_at = ?, draft_json = ?, selection_revision = 1,"
        " user_signature = 'synthetic', step_input_id = ?, passages_considered = 1, passages_given = 1"
        " WHERE id = ?",
        (status, now(), json.dumps(draft or {"outcome": "not_answered"}), _step_input(lib, turn["run_id"]),
         turn["id"]))
    lib.store.update_run(turn["run_id"], status="completed")
    return dict(lib.store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn["id"],)).fetchone())


def _idle(lib):
    """Nothing of this research is running: one active run per research, and these cases open runs by hand."""
    for row in lib.store.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND status IN ('queued', 'running', 'pause_requested')",
            (lib.rid,)).fetchall():
        lib.store.update_run(row[0], status="completed")


def _search_run(lib, turn, works):
    """A finished follow-up search of this turn, with the classification its found step freezes."""
    _idle(lib)
    run = lib.store.create_run(lib.rid, followup_search.KIND, {"max_provider_requests": 1}, None,
                               target={"turn_id": turn["id"], "attempt": 1, "question": turn["question"]})
    lib.store.update_run(run["id"], status="running")
    step = lib.store.step(run["id"], followup_search.FOUND_KEY, "code:followup_search_found")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "succeeded", output={
        "works": [{"work_id": work_of(lib, svid), "versions": [svid], "best_rank": rank, "state": state}
                  for rank, (svid, state) in enumerate(works)],
        "counts": {"records": len(works), "new": sum(1 for _, s in works if s == "new"),
                   "already_here": 0, "removed_before": 0}})
    lib.store.update_run(run["id"], status="completed")
    return lib.store.run(run["id"])


# ---- which works the revision may read -------------------------------------------------------------------------

def test_a_work_the_search_found_is_read_by_the_revision(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    found = revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")]))
    assert [item["source_version_id"] for item in found] == [lib.sources[1]]
    assert found[0]["passage_ids"] and found[0]["work_id"] == work_of(lib, lib.sources[1])


@pytest.mark.parametrize("state", ["already_here", "removed_before"])
def test_a_work_that_was_not_new_is_not_read_as_new(tmp_path, state):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    assert revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], state)])) == []


def test_a_work_the_person_decided_against_is_not_read(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    user(lib, lib.sources[1], "excluded")
    assert revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")])) == []


def test_a_search_that_never_froze_its_finds_reads_nothing(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    _idle(lib)
    run = lib.store.create_run(lib.rid, followup_search.KIND, {"max_provider_requests": 1}, None,
                               target={"turn_id": turn["id"], "attempt": 1, "question": turn["question"]})
    assert revision.usable(lib.store, lib.store.run(run["id"])) == []


# ---- the chain -------------------------------------------------------------------------------------------------

def test_the_turn_the_person_asked_starts_the_search_and_not_the_report(tmp_path):
    lib = _library(tmp_path)
    turn, run = _turn(lib)
    published = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    followup.after_turn(lib.store, lib.store.run(run["id"]))
    kinds = [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))]
    # The search first: one active run at a time, and the report request waits for the end of the chain.
    assert kinds == [followup_search.KIND] and published["search_requested"] == 1


def test_a_turn_that_asked_for_no_search_goes_straight_to_the_report(tmp_path):
    lib = _library(tmp_path)
    turn, run = _turn(lib, search=False)
    _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    followup.after_turn(lib.store, lib.store.run(run["id"]))
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]


def test_the_search_that_found_a_work_opens_the_turn_that_answers_again(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    # The same ask, read over more evidence: the question and the revision are the first turn's, and it is pending.
    assert second["question"] == first["question"] and second["scope_revision"] == first["scope_revision"]
    assert second["status"] == "pending" and second["search_requested"] == 0
    held = lib.store.run(second["run_id"])
    assert held["kind"] == followup.TASK and held["target"]["revises_turn_id"] == first["id"]


def test_a_search_that_found_nothing_readable_leaves_the_first_answer_and_asks_for_the_report(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "already_here")]))
    assert lib.store.conn.execute("SELECT COUNT(*) FROM followup_turns WHERE revises_turn_id IS NOT NULL",
                                  ).fetchone()[0] == 0
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]


def test_the_report_request_of_the_chain_is_queued_once(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    search = _search_run(lib, first, [(lib.sources[1], "new")])
    revision.after_search(lib.store, search)
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    _published(lib, second)
    followup.after_turn(lib.store, lib.store.run(second["run_id"]))
    # The first turn asked for the report to change; the request is honoured at the end of the chain, once.
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]
    followup.after_turn(lib.store, lib.store.run(second["run_id"]))
    assert lib.store.conn.execute(
        "SELECT COUNT(*) FROM runs WHERE research_id = ? AND kind = 'answer'", (lib.rid,)).fetchone()[0] == 1


def test_a_turn_that_answers_again_is_never_itself_answered_again(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    _idle(lib)
    run = lib.store.create_run(lib.rid, followup.TASK, {"max_model_calls": 1}, None,
                               target={"turn_id": "fut_synthetic"})
    with pytest.raises(Exception, match="answered again once"):
        lib.store.conn.execute(
            "INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at,"
            " revises_turn_id) VALUES (?, ?, 1, 'SYNTHETIC', ?, 'pending', ?, ?)",
            (new_id("fut"), lib.rid, run["id"], now(), second["id"]))


# ---- what the revision's own answer reads ----------------------------------------------------------------------

def test_the_revisions_pool_holds_the_found_work_and_lists_it_apart(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    run = lib.store.run(second["run_id"])
    found = revision.found_for(lib.store, run)
    held = followup.pool(lib.store, lib.rid, 1, lib.flow, found=found)
    assert lib.sources[1] in held["sources"] and held["found_versions"] == [lib.sources[1]]
    # Reading it for this answer is not including it: the research's own included works are unchanged.
    assert lib.sources[1] not in [svid for svid in followup.fast_answer.included_heads(lib.store, lib.rid).values()]


def test_the_selections_the_person_made_travel_as_they_were_frozen(tmp_path):
    lib = _library(tmp_path)
    passage = lib.store.passages_for(lib.sources[0])[0]["id"]
    turn, _ = _turn(lib, attachments=[{"kind": "passage", "ref_id": passage, "text": "SYNTHETIC selected text"}])
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    from deixis.workflow.answer import followup_attachments
    before = followup_attachments.stored(lib.store, first["id"])
    after = followup_attachments.stored(lib.store, second["id"])
    assert [(i["kind"], i["ref_id"], i["selected_text"]) for i in after] == [
        (i["kind"], i["ref_id"], i["selected_text"]) for i in before]
    assert [[b["passage_id"] for b in i["bindings"]] for i in after] == [
        [b["passage_id"] for b in i["bindings"]] for i in before]


def test_a_question_revised_after_the_answer_opens_no_second_answer(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    lib.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (lib.rid,))
    with pytest.raises(RevisionConflict):
        revision.request(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]), first,
                         [{"work_id": work_of(lib, lib.sources[1]), "source_version_id": lib.sources[1],
                           "passage_ids": ["psg_synthetic"]}])


def test_a_research_purge_deletes_a_whole_chain(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    assert lib.store.conn.execute("SELECT COUNT(*) FROM followup_turns").fetchone()[0] == 2
    _idle(lib)
    lib.store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", (now(), lib.rid))
    lib.store.purge_research(lib.rid)
    assert lib.store.conn.execute("SELECT COUNT(*) FROM followup_turns").fetchone()[0] == 0


def test_the_turn_says_how_many_works_came_from_its_own_search(tmp_path):
    """Where it looked is wider than this research for such a turn, and the scope says by how much."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    run = lib.store.run(second["run_id"])
    held = followup.pool(lib.store, lib.rid, 1, lib.flow, found=revision.found_for(lib.store, run))
    from deixis.workflow.answer import followup_scope
    scope = followup_scope.scanned(lib.store, lib.rid, held, None, None)
    # Nobody has included these records, so the pool is the found work alone: every work it looked in came from
    # the search, and the scope says both numbers rather than only the total.
    assert scope["works"] == 1 and scope["works_found_by_search"] == 1


# ---- the review's findings, each kept by its own case ----------------------------------------------------------

def test_a_turn_that_answers_again_offers_no_search_of_its_own(tmp_path):
    """A question is answered again once, so a search there would have nowhere to put its answer."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    _published(lib, second)
    offered = followup_search.offer(lib.store, dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE id = ?", (second["id"],)).fetchone()))
    assert offered == {"offered": False, "not_offered_reason": "answers_again", "attempt": 1}


def test_a_search_that_failed_still_ends_the_chain(tmp_path):
    """The report request the person made must not wait for a run that will never come."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    search = _search_run(lib, first, [])
    lib.store.update_run(search["id"], status="failed", pause_reason="followup_search_failed")
    revision.chain_ends(lib.store, lib.rid)
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]


def test_a_paused_search_has_not_ended_its_chain(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    search = _search_run(lib, first, [])
    lib.store.update_run(search["id"], status="paused", pause_reason="user_requested")
    revision.chain_ends(lib.store, lib.rid)
    assert lib.store.conn.execute(
        "SELECT COUNT(*) FROM runs WHERE research_id = ? AND kind = 'answer'", (lib.rid,)).fetchone()[0] == 0


def test_the_revision_reads_the_abstract_and_not_pages_nobody_decided_to_read(tmp_path):
    """A file in the store is not evidence until a reading decided it is; the turn's own attempt is for that."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    from test_followup_fulltext import _page
    _page(lib, lib.sources[1])
    found = revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")]))
    kinds = {lib.store.passage(pid)["kind"] for pid in found[0]["passage_ids"]}
    assert kinds == {"abstract"}


def test_a_work_the_person_included_after_the_search_is_not_read_as_found(tmp_path):
    """It is part of the research now: the research's own pool gives it, and the count stays honest."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    user(lib, lib.sources[1], "included")
    assert revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")])) == []


def test_a_work_the_screening_never_kept_is_not_read(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    lib.store.conn.execute(
        "UPDATE stage_decisions SET outcome = 'out_of_scope' WHERE research_id = ? AND source_version_id = ?"
        " AND stage = 'abstract'", (lib.rid, lib.sources[1]))
    assert revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")])) == []


def test_the_turn_a_revision_names_is_named_once_and_never_changed(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    with pytest.raises(Exception, match="named once"):
        lib.store.conn.execute("UPDATE followup_turns SET revises_turn_id = NULL WHERE id = ?", (second["id"],))


def test_one_question_is_answered_again_once(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    _idle(lib)
    run = lib.store.create_run(lib.rid, followup.TASK, {"max_model_calls": 1}, None,
                               target={"turn_id": "fut_synthetic"})
    with pytest.raises(Exception, match="UNIQUE"):
        lib.store.conn.execute(
            "INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at,"
            " revises_turn_id) VALUES (?, ?, 1, 'SYNTHETIC', ?, 'pending', ?, ?)",
            (new_id("fut"), lib.rid, run["id"], now(), first["id"]))


def test_the_same_key_with_another_ask_for_new_works_is_another_request(tmp_path):
    lib = _library(tmp_path)
    followup.request_turn(lib.store, lib.rid, QUESTION, 1, "key-1", None, False)
    with pytest.raises(RevisionConflict):
        followup.request_turn(lib.store, lib.rid, QUESTION, 1, "key-1", None, True)


def test_a_work_the_search_itself_added_is_classified_new_and_read(tmp_path):
    """The classification the search's own step writes, over a membership this run created: not a hand-set state.

    The record joins the research inside the search run (as `_admit` does), the abstract screening keeps it, and
    the run's own `found` step then says `new` — which is what the revision reads.
    """
    lib = _library(tmp_path, n=1)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    _idle(lib)
    run = lib.store.create_run(lib.rid, followup_search.KIND, {"max_provider_requests": 1}, None,
                               target={"turn_id": first["id"], "attempt": 1, "question": first["question"]})
    lib.store.update_run(run["id"], status="running")
    # The record this search found, admitted as the run's own admission step records it.
    from test_fast_path_answer import candidate
    svid = candidate(lib.store, lib.rid, "found", "SYNTHETIC later field trials.", "runs_agree_candidate")
    admit = lib.store.step(run["id"], followup_search.admit_key(1), "code:followup_search_admit")
    lib.store.start_step(admit["id"])
    lib.store.finish_step(admit["id"], "succeeded", output={
        "accepted_source_version_ids": [svid], "created_memberships": [svid]})
    held = followup_search.found(lib.store, lib.store.run(run["id"]), {"requests": [{}]})
    assert [(w["work_id"], w["state"]) for w in held["works"]] == [(work_of(lib, svid), "new")]
    step = lib.store.step(run["id"], followup_search.FOUND_KEY, "code:followup_search_found")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "succeeded", output=held)
    lib.store.update_run(run["id"], status="completed")
    found = revision.usable(lib.store, lib.store.run(run["id"]))
    assert [item["source_version_id"] for item in found] == [svid]


def test_a_full_text_this_turn_fetched_for_a_found_work_reaches_the_answer(tmp_path):
    """The works the search found join the pool before the file this turn fetched is read into it."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    search = _search_run(lib, first, [(lib.sources[1], "new")])
    revision.after_search(lib.store, search)
    second = dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (first["id"],)).fetchone())
    run = lib.store.run(second["run_id"])
    # The turn's own attempt read this work's file, as the retrieval records it.
    from test_followup_fulltext import _page
    asset_id = _page(lib, lib.sources[1])
    fetched = {work_of(lib, lib.sources[1]): {"source_version_id": lib.sources[1], "asset_id": asset_id}}
    held = followup.pool(lib.store, lib.rid, 1, lib.flow, fetched, revision.found_for(lib.store, run))
    kinds = {lib.store.passage(pid)["kind"] for pid in held["sources"][lib.sources[1]]}
    assert kinds == {"abstract", "pdf_page"} and held["found_versions"] == [lib.sources[1]]


def test_a_wrong_file_decision_keeps_the_found_works_abstract(tmp_path):
    """Their decision is about that file; the abstract the screening kept is still what this turn may read."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    from deixis.workflow.screen.decisions import DecisionStore
    DecisionStore(lib.store).record(lib.rid, lib.sources[1], "human_pdf_wrong", note="SYNTHETIC wrong file")
    found = revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")]))
    assert [item["source_version_id"] for item in found] == [lib.sources[1]]
    assert {lib.store.passage(pid)["kind"] for pid in found[0]["passage_ids"]} == {"abstract"}


def test_a_screening_the_research_has_outgrown_is_not_read_as_a_candidate(tmp_path):
    """A decision written under another criterion says nothing about today's question."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    assert revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")]))
    # The criterion moved on, so the screening that kept this work is stale.
    lib.store.conn.execute(
        "UPDATE stage_decisions SET criterion_hash = 'synthetic-old' WHERE research_id = ? AND stage = 'abstract'",
        (lib.rid,))
    assert revision.usable(lib.store, _search_run(lib, turn, [(lib.sources[1], "new")])) == []


def test_the_chain_end_is_tried_again_after_a_later_run(tmp_path):
    """A request that could not be queued because a run was active is not lost to that one moment."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    search = _search_run(lib, first, [])
    lib.store.update_run(search["id"], status="failed", pause_reason="followup_search_failed")
    other = lib.store.create_run(lib.rid, "answer_review", {"max_model_calls": 1}, None,
                                 target={"answer_run_id": first["run_id"]})
    lib.store.update_run(other["id"], status="running")
    revision.chain_ends(lib.store, lib.rid)  # another run is active: nothing is queued and nothing is lost
    assert lib.store.conn.execute(
        "SELECT COUNT(*) FROM runs WHERE research_id = ? AND kind = 'answer'", (lib.rid,)).fetchone()[0] == 0
    lib.store.update_run(other["id"], status="completed")
    revision.chain_ends(lib.store, lib.rid)
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]


def test_a_first_answer_that_could_not_be_cited_still_starts_the_search_the_person_asked_for(tmp_path):
    """Their request came with the question: the first call's citation failure is not theirs to pay for."""
    lib = _library(tmp_path)
    turn, run = _turn(lib)
    _published(lib, turn, status="unverified_draft", draft={"outcome": "not_answered"})
    followup.after_turn(lib.store, lib.store.run(run["id"]))
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == [followup_search.KIND]
    # The screen's own offer keeps the stricter rule: the button sits beside an answer the person can read.
    assert followup_search.offer(lib.store, _row(lib, turn["id"]))["not_offered_reason"] == "turn_not_published"


def test_a_second_answer_that_never_published_hands_the_report_request_back(tmp_path):
    """A revision run that failed leaves the same debt as a search that found nothing."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    second = _child(lib, first["id"])
    lib.store.update_run(second["run_id"], status="running")
    lib.store.update_run(second["run_id"], status="failed", pause_reason="model_failed")
    revision.chain_ends(lib.store, lib.rid)
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]


def test_a_second_answer_still_to_come_holds_the_report_request(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    revision.after_search(lib.store, _search_run(lib, first, [(lib.sources[1], "new")]))
    revision.chain_ends(lib.store, lib.rid)  # the turn that answers again is still pending
    assert lib.store.conn.execute(
        "SELECT COUNT(*) FROM runs WHERE research_id = ? AND kind = 'answer'", (lib.rid,)).fetchone()[0] == 0


def test_a_backend_that_stopped_right_after_the_search_failed_still_owes_the_report(tmp_path):
    """Nothing else need ever end in this research, so the start reads the chains themselves."""
    from deixis.workflow.run.worker import Worker

    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn, draft={"outcome": "not_answered", "report_change_requested": True})
    search = _search_run(lib, first, [])
    lib.store.update_run(search["id"], status="failed", pause_reason="followup_search_failed")
    Worker(lib.store, lib.flow, tmp_path / "worker.lock").recover()
    assert [row[0] for row in lib.store.conn.execute(
        "SELECT kind FROM runs WHERE research_id = ? AND status = 'queued'", (lib.rid,))] == ["answer"]


def _row(lib, turn_id):
    return dict(lib.store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn_id,)).fetchone())


def _child(lib, turn_id):
    return dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE revises_turn_id = ?", (turn_id,)).fetchone())


def test_a_turn_offers_no_search_the_research_has_no_source_for(tmp_path):
    """The screen may not promise what the run refuses: one rule, read in `offer` and applied in `request`."""
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    first = _published(lib, turn)
    lib.store.conn.execute("UPDATE scope_revisions SET providers_json = '[]' WHERE research_id = ?", (lib.rid,))
    assert followup_search.offer(lib.store, first)["not_offered_reason"] == "no_search_provider"

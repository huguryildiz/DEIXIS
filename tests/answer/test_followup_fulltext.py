"""A follow-up that would answer from an abstract alone tries that work's full text first.

SYNTHETIC records, the fake adapter and a stand-in for the per-work retrieval: no model answer is judged and no
provider is called. Passing shows which works a turn tries, in which order, under which bounds, that the file it
fetches is in the pool the call reads, and that every published turn says where it looked. It says nothing about
how often a fetch at this point actually finds a full text.
"""

import asyncio
import json

import pytest

from deixis.storage.db import new_id, now
from deixis.workflow.answer import followup, followup_fulltext as attempt, followup_scope
from test_fast_path_answer import setup, user
from test_followup_attachments import quiet, work_of

QUESTION = "Which SYNTHETIC binary variable decides the release slot?"
TERMS = followup.terms(QUESTION)


def _library(tmp_path, n=1, **kwargs):
    """A research whose works the person has included, which is what a follow-up's pool is read from."""
    lib = setup(tmp_path, n=n, **kwargs)
    quiet(lib)
    for svid in lib.sources:
        user(lib, svid, "included")
    return lib


def _turn(lib, question=QUESTION, attachments=None):
    """One queued follow-up and its run, as the API would leave them."""
    turn = followup.request_turn(lib.store, lib.rid, question, 1, None, attachments)
    run = lib.store.run(turn["run_id"])
    lib.store.update_run(run["id"], status="running")
    return turn, lib.store.run(run["id"])


def _pool(lib):
    return followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"]


def _page(lib, svid, text="SYNTHETIC. The binary variable y_t decides the release slot."):
    """Give this version a file and a page of it, which is what a settled retrieval leaves behind."""
    asset_id = new_id("ast")
    lib.store.conn.execute(
        "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
        " original_filename, retrieved_at, origin, extraction_status, extraction_version, page_count)"
        " VALUES (?, ?, ?, 1024, 'application/pdf', ?, 'a.pdf', ?, 'download', 'succeeded', 'synthetic', 1)",
        (asset_id, svid, f"sha{svid}", f"papers/{asset_id}.pdf", now()))
    # The passage's extraction has to be the asset's own, or the reading paths do not count it as in use.
    lib.store._insert_passage(svid, asset_id, "pdf_page", 1, "1", None, None, "synthetic", text)
    return asset_id


def _settles(lib, *only, version=None):
    """A stand-in for the per-work retrieval: it leaves a readable page for the versions named, as a route would.

    The step output carries the same two fields the real route records — the version it read and the file it read
    from — because that file is what decides which pages the pool may give.
    """
    async def settle(run, work_id):
        svid = lib.store.conn.execute(
            "SELECT id FROM source_versions WHERE work_id = ?", (work_id,)).fetchone()[0]
        read, asset_id, code = svid, None, "no_fulltext"
        if not only or svid in only:
            read = version(lib, work_id) if version else svid
            asset_id = _page(lib, read)
            code = "fulltext_read"
        step = lib.store.existing_step(run["id"], f"fulltext_work:{work_id}")
        lib.store.finish_step(step["id"], "succeeded", output={
            "code": code, "work_id": work_id, "read_version": read, "asset_id": asset_id})
    return settle


def _never(seconds=5.0):
    """A route that outlives the turn's wait."""
    async def slow(run, work_id):
        await asyncio.sleep(seconds)
    return slow


# ---- which works a turn tries ----------------------------------------------------------------------------------

def test_a_work_held_on_an_abstract_that_does_not_say_it_is_tried(tmp_path):
    lib = _library(tmp_path)
    turn, _ = _turn(lib)
    found = attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS, [])
    assert [item["source_version_id"] for item in found] == [lib.sources[0]]
    assert found[0]["work_id"] == work_of(lib, lib.sources[0]) and found[0]["from_selection"] is False


def test_a_work_whose_abstract_already_says_it_is_not_tried(tmp_path):
    lib = _library(tmp_path, abstract="SYNTHETIC. A binary variable decides the release slot.")
    turn, _ = _turn(lib)
    # The abstract carries the words the question asks about, so its full text is not what the turn is short of.
    assert attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS, []) == []
    assert attempt.detail_in_abstract("SYNTHETIC. A binary variable decides the release slot.", TERMS)


def test_a_work_the_pool_already_holds_a_page_of_is_not_tried(tmp_path):
    lib = _library(tmp_path)
    _page(lib, lib.sources[0])
    turn, _ = _turn(lib)
    assert attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS, []) == []


def test_the_work_the_person_selected_is_tried_first(tmp_path):
    lib = _library(tmp_path, n=2)
    second = lib.sources[1]
    passage = lib.store.passages_for(second)[0]["id"]
    turn, _ = _turn(lib, attachments=[{"kind": "passage", "ref_id": passage, "text": "SYNTHETIC selected text"}])
    from deixis.workflow.answer import followup_attachments
    found = attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS,
                               followup_attachments.stored(lib.store, turn["id"]))
    assert [item["source_version_id"] for item in found] == [second, lib.sources[0]]
    assert found[0]["from_selection"] is True


# ---- the bounds ------------------------------------------------------------------------------------------------

def test_a_turn_tries_two_works_and_writes_down_the_rest(tmp_path, monkeypatch):
    lib = _library(tmp_path, n=3)
    turn, run = _turn(lib)
    tried: list[str] = []

    async def settle(held, work_id):
        tried.append(work_id)
        step = lib.store.existing_step(held["id"], f"fulltext_work:{work_id}")
        lib.store.finish_step(step["id"], "succeeded", output={"code": "no_fulltext", "work_id": work_id})

    monkeypatch.setattr(lib.flow, "_overlap_work", settle)
    record = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    assert len(tried) == 2 and record["gap"] == 3
    assert [item["outcome"] for item in record["tried"]] == ["settled", "settled"]
    assert [item["reason"] for item in record["not_tried"]] == ["past_limit"]
    assert attempt.view(record) == {"works": 2, "seconds": attempt.SECONDS, "gap": 3, "settled": 2, "tried": 2,
                                    "past_limit": 1, "deadline": 0, "other_version": 0}


def test_the_turns_wait_stops_a_route_and_says_it_did_not_settle(tmp_path, monkeypatch):
    lib = _library(tmp_path, n=2)
    turn, run = _turn(lib)
    run["budget"]["followup_fulltext"]["fulltext_seconds"] = 0.05
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())
    record = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    # The first work's route was cut off; the second was never started, and neither is called "no full text".
    assert record["tried"][0]["outcome"] == "not_settled" and record["tried"][0]["reason"] == "deadline"
    assert [item["reason"] for item in record["not_tried"]] == ["deadline"]
    step = lib.store.existing_step(run["id"], f"fulltext_work:{record['tried'][0]['work_id']}")
    assert (step["status"], step["error_code"]) == ("outcome_unknown", "followup_deadline")


def test_a_turn_queued_before_the_rule_tries_nothing(tmp_path, monkeypatch):
    lib = _library(tmp_path)
    turn, run = _turn(lib)
    run["budget"].pop("followup_fulltext")
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())
    record = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    assert record == {"rule": None, "tried": [], "not_tried": [], "seconds": None}
    assert attempt.view(record) is None


def test_a_resumed_turn_reads_what_the_first_attempt_did(tmp_path, monkeypatch):
    lib = _library(tmp_path)
    turn, run = _turn(lib)
    svid = lib.sources[0]
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, svid))
    first = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    assert [item["outcome"] for item in first["tried"]] == ["settled"]
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())  # a second try would hang the turn
    again = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    assert again == first
    assert attempt.stored(lib.store, run["id"]) == first


# ---- what the answer then reads, and what the turn says about it -----------------------------------------------

def test_the_page_the_turn_fetched_is_in_the_pool_the_answer_reads(tmp_path, monkeypatch):
    lib = _library(tmp_path)
    svid = lib.sources[0]
    turn, run = _turn(lib)
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, svid))
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    published = followup.turn(lib.store, lib.rid, turn["id"])
    assert published["status"] in followup.PUBLISHED or published["status"] == "unverified_draft"
    frozen = lib.store.existing_step(run["id"], followup.POOL_KEY)["output"]
    kinds = {row["kind"] for pid in frozen["sources"][svid] for row in [lib.store.passage(pid)]}
    assert "pdf_page" in kinds  # the file arrived before the pool was frozen, so the call could read it
    assert published["scanned_scope"]["works_full_text"] == 1


def test_every_published_turn_says_where_it_looked(tmp_path, monkeypatch):
    lib = _library(tmp_path, n=2)
    turn, run = _turn(lib)
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, lib.sources[0]))
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    scope = followup.turn(lib.store, lib.rid, turn["id"])["scanned_scope"]
    # The works are counted by the depth their passages were read at, apart from one another.
    assert scope["works"] == 2 and scope["works_full_text"] == 1 and scope["works_abstract_only"] == 1
    assert scope["research_works"] == 2 and scope["basis"] in ("answer_input", "included_works")
    # The three passage counts stay apart, and the attempt is written beside them.
    assert scope["given_to_model"] <= scope["pool_held"] and scope["ranked_considered"] is not None
    # Both works were tried and both routes answered; "settled" is the routes answering, not a file arriving —
    # only one of them had a full text, which is what the depth counts above say.
    assert scope["fulltext"]["tried"] == 2 and scope["fulltext"]["settled"] == 2


def test_a_turn_with_no_passage_still_says_where_it_looked(tmp_path, monkeypatch):
    lib = _library(tmp_path)
    # The one source is excluded, so the pool holds nothing and no model is asked.
    lib.store.set_user_selection(lib.rid, lib.sources[0], "excluded", lib.store.conn.execute(
        "SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
        (lib.rid, lib.sources[0])).fetchone()[0], "SYNTHETIC reason")
    turn, run = _turn(lib)
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    published = followup.turn(lib.store, lib.rid, turn["id"])
    assert published["status"] == "no_passages"
    scope = published["scanned_scope"]
    assert scope["works"] == 0 and scope["given_to_model"] == 0 and scope["research_works"] == 1


# ---- the review's findings, each kept by its own case ----------------------------------------------------------

def _frozen_answer(lib):
    """Freeze a real answer over these works, so the follow-up's pool is read from an answer input."""
    from test_fast_path_answer import answer_run, cutoff
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(followup.fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    lib.store.update_run(run["id"], status="completed")  # a follow-up is not queued while a run is active
    return run


def test_the_fetched_page_reaches_a_pool_frozen_from_an_answer_input(tmp_path, monkeypatch):
    """The case the other pool basis hides: the answer froze this work on its abstract route."""
    lib = _library(tmp_path)
    svid = lib.sources[0]
    _frozen_answer(lib)
    assert followup.pool(lib.store, lib.rid, 1, lib.flow)["basis"] == "answer_input"
    turn, run = _turn(lib)
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, svid))
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    frozen = lib.store.existing_step(run["id"], followup.POOL_KEY)["output"]
    kinds = {row["kind"] for pid in frozen["sources"][svid] for row in [lib.store.passage(pid)]}
    assert "pdf_page" in kinds  # without this the frozen input's abstract route would keep the page out


def test_the_attempt_reads_the_pools_reserve_as_well(tmp_path, monkeypatch):
    """A work included after the answer's cutoff is in the reserve; a selection of the person's may point at it."""
    lib = _library(tmp_path)
    turn, run = _turn(lib)
    seen: list[dict[str, list[str]]] = []
    monkeypatch.setattr(attempt, "candidates", lambda store, tid, sources, terms, att: seen.append(sources) or [])
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    pool = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert set(seen[-1]) == set(pool["sources"]) | set(pool["reserve"])


def test_the_scanned_scope_counts_the_works_the_call_was_given(tmp_path, monkeypatch):
    """The pool is what the turn could read; the passage limit is what it did read, and the scope says the second."""
    lib = _library(tmp_path, n=3)
    turn, run = _turn(lib)
    run["budget"]["max_followup_passages"] = 1  # one passage, so two of the three works are never shown
    from deixis.storage.db import dumps
    lib.store.update_run(run["id"], budget_json=dumps(run["budget"]))
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())
    asyncio.run(followup.answer(lib.flow, lib.store.run(run["id"]), lib.store.scope(lib.rid)))
    scope = followup.turn(lib.store, lib.rid, turn["id"])["scanned_scope"]
    assert scope["works"] == 3 and scope["works_given"] == 1
    assert scope["works_given_full_text"] + scope["works_given_abstract_only"] == 1


def test_a_resumed_turn_reads_its_first_attempt_from_the_steps(tmp_path, monkeypatch):
    """A crash between the claims and the record must neither spend the allowance twice nor lose a fetched page."""
    lib = _library(tmp_path, n=3)
    turn, run = _turn(lib)
    svid = attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS, [])[0]["source_version_id"]
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, svid))
    first = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    assert len(first["tried"]) == 2
    # The record is gone, as a crash before it was written would leave it; the per-work steps stay.
    lib.store.conn.execute("DELETE FROM run_steps WHERE run_id = ? AND operation_key = ?",
                           (run["id"], attempt.STEP_KEY))
    monkeypatch.setattr(lib.flow, "_overlap_work", _never())  # a second try of the same work would hang the turn
    again = asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))
    assert again["resumed"] == 2 and len(again["tried"]) == 2
    # The third work is past the limit, which the first attempt had already spent; it is not tried again.
    assert all(item["resumed"] for item in again["tried"])
    assert [item["reason"] for item in again["not_tried"]] == ["past_limit"]
    # And the page the first attempt fetched is still named as fetched, so the pool can give it.
    assert attempt.fetched_reads(lib.flow, run["id"])[work_of(lib, svid)]["source_version_id"] == svid


def test_a_stopped_run_stops_the_attempt(tmp_path, monkeypatch):
    from deixis.workflow.run.flow import RunStopped

    lib = _library(tmp_path)
    turn, run = _turn(lib)

    async def stopped(held, work_id):
        raise RunStopped("SYNTHETIC pause")

    monkeypatch.setattr(lib.flow, "_overlap_work", stopped)
    with pytest.raises(RunStopped):
        asyncio.run(attempt.advance(lib.flow, run, turn, _pool(lib), TERMS, []))


def test_a_work_the_person_pointed_at_is_tried_whatever_its_abstract_says(tmp_path):
    """Pointing at an abstract-only source and asking a question of it says the abstract is not enough."""
    lib = _library(tmp_path, abstract="SYNTHETIC. A binary variable decides the release slot.")
    passage = lib.store.passages_for(lib.sources[0])[0]["id"]
    turn, _ = _turn(lib, attachments=[{"kind": "passage", "ref_id": passage, "text": "SYNTHETIC selected"}])
    from deixis.workflow.answer import followup_attachments
    found = attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS,
                               followup_attachments.stored(lib.store, turn["id"]))
    assert [item["from_selection"] for item in found] == [True]
    # Nobody pointed at it: the same abstract then counts as naming what was asked.
    assert attempt.candidates(lib.store, turn["id"], _pool(lib), TERMS, []) == []


def test_one_shared_word_is_not_enough_to_call_an_abstract_answering(tmp_path):
    assert not attempt.detail_in_abstract("SYNTHETIC. A binary variable.", ["binary", "release", "slot", "decides"])
    # Two words of a two-word question do clear it; one does not, however large the share.
    assert attempt.detail_in_abstract("binary release", ["binary", "release"])
    assert not attempt.detail_in_abstract("binary only", ["binary", "release"])


# ---- what the fetched file may and may not become -------------------------------------------------------------

def test_a_file_the_person_marked_wrong_stays_out_of_the_pool(tmp_path, monkeypatch):
    """Their "this is the wrong paper" outlives a fetch: the work keeps giving its abstract alone."""
    # No selection of theirs on this version: a selection they made would outrank the queue decision, which is the
    # precedence the whole pool reads states by, so the wrong-file case is the one where the decision is all there is.
    lib = setup(tmp_path)
    quiet(lib)
    svid = lib.sources[0]
    _frozen_answer(lib)
    from deixis.workflow.screen.decisions import DecisionStore
    DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong", note="SYNTHETIC wrong file")
    turn, run = _turn(lib)
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, svid))
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    frozen = lib.store.existing_step(run["id"], followup.POOL_KEY)["output"]
    kinds = {row["kind"] for pid in frozen["sources"].get(svid, []) for row in [lib.store.passage(pid)]}
    assert kinds == {"abstract"}


def test_a_file_read_on_another_version_waits_for_the_next_question(tmp_path, monkeypatch):
    """The routes may read another version of the work. Swapping it in would drop the passages the pool gives for
    that work — the person's own selection may point at one — so this turn keeps its version and says so."""
    lib = _library(tmp_path)
    head = lib.sources[0]
    other = lib.store.open_lookup_version(lib.rid, head, "acceptedVersion", None)
    _frozen_answer(lib)
    turn, run = _turn(lib)
    monkeypatch.setattr(lib.flow, "_overlap_work", _settles(lib, head, version=lambda lib, work_id: other))
    asyncio.run(followup.answer(lib.flow, run, lib.store.scope(lib.rid)))
    frozen = lib.store.existing_step(run["id"], followup.POOL_KEY)["output"]
    # The pool is unchanged: the work keeps its own version and its abstract, and nothing was taken out of it.
    assert other not in frozen["sources"]
    assert {row["kind"] for pid in frozen["sources"][head] for row in [lib.store.passage(pid)]} == {"abstract"}
    # And the turn says the file arrived on another version, so the attempt is not read as "no full text".
    scope = followup.turn(lib.store, lib.rid, turn["id"])["scanned_scope"]
    assert scope["fulltext"]["settled"] == 1 and scope["fulltext"][attempt.OTHER_VERSION] == 1


def test_both_rounds_of_one_turn_count_as_read(tmp_path):
    """A second round replaces passages; the works the first call read were still read this turn."""
    lib = _library(tmp_path, n=2)
    first, second = (lib.store.passages_for(svid)[0]["id"] for svid in lib.sources)
    assert followup_scope.read_works(lib.store, [first])["works"] == 1
    assert followup_scope.read_works(lib.store, [first, second])["works"] == 2
    assert followup_scope.read_works(lib.store, None)["works"] == 0


def test_a_one_word_question_is_answered_by_that_one_word(tmp_path):
    """The two-match floor must not send every short question down the fetch route."""
    assert attempt.detail_in_abstract("SYNTHETIC. The release slot is fixed.", ["release"])
    assert not attempt.detail_in_abstract("SYNTHETIC. The slot is fixed.", ["release"])

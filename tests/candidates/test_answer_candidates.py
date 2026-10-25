"""SYNTHETIC tests of candidates written from an answer's Next steps (D98); no retrieval or model call.

They show the stored link, its idempotency and the counts the answer thread reads from stored rows. They say nothing
about whether a kill search finds prior work.
"""
import json
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.candidates_answer_view import answer_candidates
from deixis.workflow.candidates_run import candidate_target, decomposition_input
from deixis.workflow.candidates_store import InvalidCandidateInput, purge_candidates
from deixis.workflow.store import NotFound
from deixis.workflow.candidates_hits import merge_and_cut
from deixis.workflow.candidates_store import CandidateStore
from deixis.workflow.store import Store
from test_candidate_store import assessment, make_library, provider_record, query, start, version

ASPECTS = ["SYNTHETIC aspect one: delay under mobility.", "SYNTHETIC aspect two: energy under load."]
CLAIM = "SYNTHETIC: bounded scheduling lowers delay under mobility."


@pytest.fixture
def lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    lib.answer = answer(lib)
    yield lib
    lib.conn.close()


def answer(lib, status="structurally_valid", aspects=ASPECTS, research_id=None):
    id_ = db.new_id("ans")
    lib.conn.execute(
        "INSERT INTO answers (id, research_id, run_id, scope_revision, status, draft_json, validation_json, report_version,"
        " created_at) VALUES (?, ?, ?, 1, ?, ?, '{}', 3, 'now')",
        (id_, research_id or lib.rid, lib.run, status, json.dumps({"title": "SYNTHETIC", "unanswered_aspects": aspects})))
    return id_


def open_(lib, aspect=0, text=CLAIM, **kw):
    return lib.candidate_store.open_from_answer(lib.rid, kw.pop("answer_id", lib.answer), aspect, text, **kw)


def test_an_aspect_keeps_one_candidate_and_the_aspect_stays_context(lib):
    candidate, reused = open_(lib, 0, "  " + CLAIM + "\n")
    assert reused is None and candidate["origin"] == "answer_thread" and candidate["origin_text"] == CLAIM
    context = json.loads(candidate["origin_provenance_json"])
    assert context == {"answer_id": lib.answer, "report_version": 3, "report_revision": None, "aspect_index": 0,
                       "aspect_text": ASPECTS[0]}
    assert json.loads(candidate["origin_basis_json"]) == {} and json.loads(candidate["origin_basis_view_json"]) == {}
    # A second write from the same aspect, even with other words, opens the same candidate.
    again, reused = open_(lib, 0, "SYNTHETIC different words")
    assert reused == "aspect" and again["id"] == candidate["id"] and again["origin_text"] == CLAIM
    other, reused = open_(lib, 1)
    assert reused is None and other["id"] != candidate["id"]
    first, _ = open_(lib, None)
    second, _ = open_(lib, None)
    assert first["id"] != second["id"]
    links = lib.candidate_store.answer_links(lib.rid, lib.answer)
    assert [(l["candidate_id"], l["aspect_index"]) for l in links] == [
        (candidate["id"], 0), (other["id"], 1), (first["id"], None), (second["id"], None)]


def test_the_link_survives_a_new_connection(lib, tmp_path):
    candidate, _ = open_(lib, 1)
    reopened = CandidateStore(Store(db.connect(tmp_path / "library.sqlite")))
    again, reused = reopened.open_from_answer(lib.rid, lib.answer, 1, "SYNTHETIC other")
    assert reused == "aspect" and again["id"] == candidate["id"]
    reopened.conn.close()


def test_idempotent_replay_and_mismatch(lib):
    candidate, reused = open_(lib, None, idempotency_key="k1")
    assert reused is None
    again, reused = open_(lib, None, idempotency_key="k1")
    assert reused == "replay" and again["id"] == candidate["id"]
    with pytest.raises(InvalidCandidateInput, match="mismatch"):
        open_(lib, None, "SYNTHETIC other text", idempotency_key="k1")
    with pytest.raises(InvalidCandidateInput, match="mismatch"):
        open_(lib, 1, idempotency_key="k1")
    aspect, _ = open_(lib, 1, idempotency_key="k2")
    replay, how = open_(lib, 1, idempotency_key="k2")
    assert how == "replay" and replay["id"] == aspect["id"]
    assert len(lib.candidate_store.answer_links(lib.rid, lib.answer)) == 2


@pytest.mark.parametrize("aspect", [2, -1, True, "0"])
def test_an_aspect_the_answer_does_not_have_is_refused(lib, aspect):
    with pytest.raises(InvalidCandidateInput, match="unanswered aspect"):
        open_(lib, aspect)


def test_refusals_for_text_answer_and_research(lib):
    with pytest.raises(InvalidCandidateInput):
        open_(lib, 0, "   ")
    with pytest.raises(InvalidCandidateInput, match="2000"):
        open_(lib, 0, "x" * 2001)
    draft = answer(lib, status="unverified_draft")
    with pytest.raises(InvalidCandidateInput, match="valid answer"):
        open_(lib, None, answer_id=draft)
    other = lib.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake-model", "en")
    foreign = answer(lib, research_id=other)
    with pytest.raises(NotFound):
        open_(lib, 0, answer_id=foreign)
    with pytest.raises(NotFound):
        open_(lib, 0, answer_id="ans_missing")
    assert lib.candidate_store.answer_links(lib.rid, lib.answer) == []


def test_the_model_sees_the_person_s_sentence_as_owner_text_without_basis(lib):
    candidate, _ = open_(lib, 0)
    target = candidate_target(candidate)
    assert target["origin"] == "owner_text" and target["origin_text"] == CLAIM and target["basis"] == []
    built = decomposition_input(candidate, {})
    assert built["target"]["basis"] == [] and ASPECTS[0] not in json.dumps(built)


def test_link_rows_are_guarded(lib):
    candidate, _ = open_(lib, 0)
    owner = lib.candidate_store.open_from_owner_text(lib.rid, CLAIM)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        lib.conn.execute("UPDATE answer_candidate_links SET aspect_index = 1")
    with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
        lib.conn.execute("DELETE FROM answer_candidate_links")
    for statement in ("INSERT OR REPLACE INTO answer_candidate_links VALUES (?, ?, ?, 0, 'now')",
                      "INSERT OR IGNORE INTO answer_candidate_links VALUES (?, ?, ?, 0, 'now')"):
        with pytest.raises(sqlite3.IntegrityError, match="already exists"):
            lib.conn.execute(statement, (candidate["id"], lib.rid, lib.answer))
    with pytest.raises(sqlite3.IntegrityError, match="answer-thread candidate"):
        lib.conn.execute("INSERT INTO answer_candidate_links VALUES (?, ?, ?, NULL, 'now')", (owner["id"], lib.rid, lib.answer))
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute("INSERT INTO answer_candidate_links VALUES (?, ?, ?, -1, 'now')", (owner["id"], lib.rid, lib.answer))
    with pytest.raises(sqlite3.OperationalError, match="rowid"):
        lib.conn.execute("SELECT rowid FROM answer_candidate_links")
    lib.conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (lib.rid,))
    purge_candidates(lib.conn, lib.rid)
    assert lib.conn.execute("SELECT COUNT(*) FROM answer_candidate_links").fetchone()[0] == 0
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert candidate["id"]


def searched(lib, candidate):
    cs = lib.candidate_store
    v = version(lib, candidate, elements=[{"text": "SYNTHETIC scheduling", "kind": "mechanism"},
                                         {"text": "SYNTHETIC delay", "kind": "outcome"}])
    s = start(lib, v, rendered_queries=[{"provider_id": "openalex"}, {"provider_id": "openalex"}, {"provider_id": "pubmed"}])
    first = query(lib, s, records=[provider_record("SYNTHETIC-a"), provider_record("SYNTHETIC-b")], position=1)
    second = query(lib, s, records=[provider_record("SYNTHETIC-a")], position=2)
    query(lib, s, records=[], position=3, status="failed", error_code="timeout")
    merged = merge_and_cut([first, second])
    cs.record_hits(s["id"], merged, {r["source_version_id"]: "abstract" for r in merged["kept"]})
    a, b = [h["source_version_id"] for h in cs.hits(s["id"])]
    elements = cs.version(v["id"])["elements"]
    quote = {"evidence_kind": "abstract", "passage_id": None, "quote": "SYNTHETIC quote"}
    cs.publish_assessment(s["id"], a, **assessment(lib, s) | {"cells": [
        {"element_id": elements[0]["id"], "relation": "explicit_support", "condition_alignment": "aligned", "quotes": [quote]},
        {"element_id": elements[1]["id"], "relation": "no_match_in_supplied_text", "condition_alignment": None, "quotes": []}]})
    cs.publish_assessment(s["id"], b, assessment_state="insufficient_access")
    cs.finish_kill_search(s["id"], "completed")
    return v, s, a


def test_the_answer_view_reads_counts_status_and_works_from_stored_rows(lib):
    candidate, _ = open_(lib, 0)
    open_(lib, None)
    v, s, a = searched(lib, candidate)
    view = answer_candidates(lib.store, lib.rid, lib.answer)
    assert view["decompose"]["max_model_calls"] >= 1 and view["decompose"]["max_provider_requests"] == 0
    assert view["decompose"]["model"] == "fake-model"
    row = next(r for r in view["candidates"] if r["candidate_id"] == candidate["id"])
    assert row["aspect_index"] == 0 and row["context"]["aspect_text"] == ASPECTS[0]
    assert row["current_version_searched"] is True and row["claim_statement"]
    search = row["search"]
    assert search["kill_search_id"] == s["id"] and search["is_current_version"] and search["version"] == 1
    assert search["execution"] == {
        "queries_planned": 3, "queries_recorded": 3, "queries_succeeded": 2, "queries_failed": 1,
        "queries_outcome_unknown": 0, "records_returned": 3, "hits_recorded": True, "found": 3, "duplicates": 1,
        "unique": 2, "kept": 2, "rank_cut": 0, "assessed": 1, "insufficient_access": 1, "not_assessed_budget": 0,
        "pending": 0, "works_with_support": 1, "works_stating_whole_claim": 0}
    assert search["status"]["status"] == "undecided" and "insufficient_access" in search["status"]["reasons"]
    assert search["reading"]["assessed_works"] == 1 and search["reading"]["full_text"] == 0
    assert [w["source_version_id"] for w in search["top_works"]] == [a]
    assert [(e["position"], e["relation"]) for e in search["top_works"][0]["elements"]] == [
        (1, "explicit_support"), (2, "no_match_in_supplied_text")]
    generic = next(r for r in view["candidates"] if r["candidate_id"] != candidate["id"])
    assert generic["aspect_index"] is None and generic["search"] is None and generic["current_version"] == 0


def test_a_card_changed_after_its_search_keeps_the_older_result_and_its_decision_version(lib):
    candidate, _ = open_(lib, 0)
    v, s, _ = searched(lib, candidate)
    lib.candidate_store.record_owner_decision(lib.rid, v["id"], "undecided", "SYNTHETIC need more reading")
    version(lib, candidate)
    row = answer_candidates(lib.store, lib.rid, lib.answer)["candidates"][0]
    assert row["current_version"] == 2 and row["current_version_searched"] is False
    assert row["search"]["version"] == 1 and row["search"]["is_current_version"] is False
    assert row["owner"]["version"] == 1 and row["owner"]["status"] == "undecided"


def test_the_answer_view_refuses_an_answer_of_another_research(lib):
    other = lib.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake-model", "en")
    with pytest.raises(NotFound):
        answer_candidates(lib.store, other, lib.answer)

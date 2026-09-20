"""Stage decisions, model proposals, signal ranks, and the selection derived from them (SW9, SW11).

Records are SYNTHETIC. Passing these tests shows that storage keeps one decision per record and stage with its reason
code and derives a selection from it; it says nothing about screening quality. No workflow step writes these tables
yet, so nothing here changes what the product does today.
"""

import pytest

from deixis.domain.reason_codes import REASON_CODES
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.decisions import DecisionStore, HumanDecisionStands
from deixis.workflow.store import Store

DOI = "10.1109/synth.2026.2"


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def record(record_id, title="SYNTHETIC release scheduling for diffusion channels", doi=DOI, merge_by_doi=True,
           version_label="publishedVersion", **identifiers):
    return ProviderRecord(
        provider_record_id=record_id, title=title, authors=[], year=2026, venue=None, publication_type=None, doi=doi,
        landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label=version_label, abstract=None,
        abstract_origin=None, identifiers=identifiers, raw={}, merge_by_doi=merge_by_doi,
    )


def research(store, search_workflow="sw"):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex", "arxiv"], "fake", "m", "en",
                                search_workflow=search_workflow)
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)
    return rid, run["id"]


def search(store, rid, run_id, index, provider, records):
    step = store.step(run_id, f"search:{index}", f"provider_search:{provider}")
    store.record_search(
        dict(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider=provider, query_text="q",
             request_description="GET test", access_mode="keyless", status="completed", delivery_class=None,
             result_count=len(records), provider_total=len(records), page_limit=25, error_json=None,
             raw_payload_path=None),
        provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})


def one_record(store, rid, run_id):
    """One published record in the research, and the work it heads."""
    search(store, rid, run_id, 0, "openalex", [record("W1")])
    svid = store.find_source_by_identifier("openalex", "W1")
    return svid, store.source(svid)["work_id"]


def two_versions(store, rid, run_id):
    """A published record and the arXiv preprint of the same work; the published record heads it (D46, D48)."""
    search(store, rid, run_id, 0, "openalex", [record("W1")])
    search(store, rid, run_id, 1, "arxiv", [record("2601.00001v1", title="SYNTHETIC preprint of the same study",
                                                   doi="10.48550/arxiv.2601.00001", merge_by_doi=False,
                                                   version_label="submittedVersion", published_doi=DOI)])
    published = store.find_source_by_identifier("openalex", "W1")
    preprint = store.find_source_by_identifier("arxiv", "2601.00001v1")
    assert store.source(published)["work_id"] == store.source(preprint)["work_id"]
    assert store.work_heads(rid) == {store.source(published)["work_id"]: published}
    return published, preprint, store.source(published)["work_id"]


def step_id(store, run_id, key="screening:0"):
    return store.step(run_id, key, "screening")["id"]


# ---- decisions ------------------------------------------------------------------------------
def test_a_decision_takes_its_stage_outcome_decider_and_next_step_from_its_reason_code(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decision = DecisionStore(store).record(rid, svid, "no_fulltext")
    assert (decision["stage"], decision["outcome"]) == ("fulltext", "unresolved")
    assert (decision["decided_by"], decision["next_step"]) == ("code", "waiting_for_pdf")
    assert decision["scope_revision"] == 1 and decision["superseded_at"] is None


def test_an_unknown_reason_code_writes_nothing(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    with pytest.raises(KeyError):
        DecisionStore(store).record(rid, svid, "invented_code")
    assert store.conn.execute("SELECT COUNT(*) FROM stage_decisions").fetchone()[0] == 0


def test_a_second_decision_closes_the_first_and_both_stay_in_the_history(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    first = decisions.record(rid, svid, "not_read_yet")
    second = decisions.record(rid, svid, "all_parts_verified", step_id=step_id(store, run_id))
    history = decisions.history(rid, svid)
    assert [d["reason_code"] for d in history] == ["not_read_yet", "all_parts_verified"]
    assert history[0]["id"] == first["id"] and history[0]["superseded_at"] is not None
    assert decisions.current(rid, svid, "fulltext")["id"] == second["id"]
    assert decisions.current(rid, svid, "abstract") is None


def test_the_same_decision_from_the_same_step_is_written_once(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions, sid = DecisionStore(store), step_id(store, run_id)
    first = decisions.record(rid, svid, "criterion_absent", step_id=sid)
    assert decisions.record(rid, svid, "criterion_absent", step_id=sid)["id"] == first["id"]
    assert len(decisions.history(rid, svid)) == 1


def test_code_cannot_decide_over_the_user_but_the_user_can(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, svid, "human_criterion_not_met")
    with pytest.raises(HumanDecisionStands):
        decisions.record(rid, svid, "all_parts_verified")
    assert len(decisions.history(rid, svid)) == 1
    assert decisions.record(rid, svid, "human_include")["outcome"] == "include"
    assert len(decisions.history(rid, svid)) == 2


def test_undoing_a_human_decision_brings_back_the_decision_before_it(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, svid, "criterion_absent")
    decisions.record(rid, svid, "human_include")
    restored = decisions.undo_human(rid, svid, "fulltext")
    assert restored["reason_code"] == "criterion_absent" and restored["note"] == "restored after an undone human decision"
    assert [d["reason_code"] for d in decisions.history(rid, svid)] == ["criterion_absent", "human_include", "criterion_absent"]
    assert decisions.current(rid, svid, "fulltext")["id"] == restored["id"]


def test_undoing_the_only_decision_leaves_the_stage_undecided(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, svid, "human_not_sure")
    assert decisions.undo_human(rid, svid, "fulltext") is None
    assert decisions.current(rid, svid, "fulltext") is None
    assert len(decisions.history(rid, svid)) == 1  # the undone decision is closed, not deleted
    assert decisions.undo_human(rid, svid, "fulltext") is None  # nothing left to undo


def test_a_decision_without_a_frozen_protocol_carries_no_protocol_or_criterion_hash(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decision = DecisionStore(store).record(rid, svid, "no_abstract")
    assert decision["protocol_hash"] is None and decision["criterion_hash"] is None


def test_a_decision_carries_the_protocol_it_was_decided_under_and_goes_stale_with_the_criterion(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    frozen = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "inclusion_criterion": "SYNTHETIC criterion",
                                            "criterion_parts": ["a"], "cue_phrases": None})
    decision = decisions.record(rid, svid, "no_abstract")
    assert decision["protocol_hash"] == frozen["hash"] and decision["criterion_hash"] is not None
    assert decisions.is_stale(decision) is False
    store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "inclusion_criterion": "SYNTHETIC other criterion",
                                   "criterion_parts": ["a"], "cue_phrases": None}, reason="the owner narrowed it")
    assert decisions.is_stale(decision) is True


def test_a_decision_goes_stale_when_the_question_is_revised(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decision = decisions.record(rid, svid, "no_abstract")
    store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC question, narrowed?", None)
    assert decisions.is_stale(decision) is True


# ---- proposals and ranks --------------------------------------------------------------------
def test_a_replayed_step_proposes_and_ranks_without_adding_rows(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decisions, sid = DecisionStore(store), step_id(store, run_id)
    first = decisions.add_proposal(rid, svid, "fulltext", sid, 1, "include", criterion_part="a",
                                   quote="SYNTHETIC quote", quote_verified=True, quote_page=3)
    assert decisions.add_proposal(rid, svid, "fulltext", sid, 1, "criterion_not_met", criterion_part="a") == first
    assert decisions.add_proposal(rid, svid, "fulltext", sid, 1, "include", criterion_part="b") != first
    stored = decisions.proposals(rid, svid, "fulltext")
    assert [p["criterion_part"] for p in stored] == ["a", "b"]
    assert stored[0]["label"] == "include" and stored[0]["quote_verified"] == 1 and stored[0]["quote_page"] == 3

    rows = [{"source_version_id": svid, "signal": "fused", "rank": 1.5, "available": True}]
    decisions.save_ranks(sid, rid, rows)
    decisions.save_ranks(sid, rid, [{**rows[0], "rank": 9.0}])
    assert [(r["signal"], r["rank"], r["available"]) for r in decisions.ranks(rid, svid)] == [("fused", 1.5, 1)]


# ---- from decisions to a selection ------------------------------------------------------------
def test_a_legacy_research_derives_no_selection(store):
    rid, run_id = research(store, search_workflow="legacy")
    svid, work_id = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, svid, "all_parts_verified")
    assert decisions.derive_selection(rid, work_id) is None
    assert store.conn.execute("SELECT state, origin FROM selections WHERE source_version_id = ?",
                              (svid,)).fetchone()["origin"] == "default"


def test_a_verified_record_becomes_an_included_selection_the_history_explains(store):
    rid, run_id = research(store)
    svid, work_id = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    before = store.selection_revision(rid)
    decisions.record(rid, svid, "all_parts_verified")
    assert decisions.derive_selection(rid, work_id) == "included"
    selection = dict(store.conn.execute("SELECT * FROM selections WHERE source_version_id = ?", (svid,)).fetchone())
    assert (selection["state"], selection["origin"], selection["version"]) == ("included", "code_rule", 2)
    assert selection["proposal"] is None and selection["user_reason"] is None  # the proposal columns are untouched
    last = store.conn.execute(
        "SELECT * FROM selection_history WHERE source_version_id = ? ORDER BY id DESC LIMIT 1", (svid,)).fetchone()
    assert (last["origin"], last["reason"], last["new_state"]) == ("code_rule", "all_parts_verified", "included")
    assert store.selection_revision(rid) == before + 1


def test_deriving_the_same_selection_again_writes_no_further_history(store):
    rid, run_id = research(store)
    svid, work_id = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, svid, "all_parts_verified")
    decisions.derive_selection(rid, work_id)
    rows = store.conn.execute("SELECT COUNT(*) FROM selection_history WHERE source_version_id = ?", (svid,)).fetchone()[0]
    version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?", (svid,)).fetchone()[0]
    assert decisions.derive_selection(rid, work_id) is None
    assert store.conn.execute("SELECT COUNT(*) FROM selection_history WHERE source_version_id = ?",
                              (svid,)).fetchone()[0] == rows
    assert store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?", (svid,)).fetchone()[0] == version


def test_the_users_own_choice_is_never_changed_by_a_derived_selection(store):
    rid, run_id = research(store)
    svid, work_id = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?", (svid,)).fetchone()[0]
    store.set_user_selection(rid, svid, "excluded", version, "SYNTHETIC: the owner read it and said no")
    decisions.record(rid, svid, "all_parts_verified")
    assert decisions.derive_selection(rid, work_id) is None
    selection = store.conn.execute("SELECT state, origin, user_reason FROM selections WHERE source_version_id = ?",
                                   (svid,)).fetchone()
    assert (selection["state"], selection["origin"]) == ("excluded", "user")
    assert selection["user_reason"] == "SYNTHETIC: the owner read it and said no"


def test_a_record_the_criterion_missed_is_excluded_but_stays_apart_from_out_of_scope(store):
    rid, run_id = research(store)
    svid, work_id = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, svid, "criterion_absent")
    assert decisions.derive_selection(rid, work_id) == "excluded"
    # The selection cannot tell the two apart; the decision row a report reads still can (SW11.2).
    assert decisions.work_outcome(rid, work_id)["outcome"] == "criterion_not_met"


def test_one_version_still_a_candidate_keeps_the_work_pending(store):
    rid, run_id = research(store)
    published, preprint, work_id = two_versions(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, published, "both_blocks_missing")
    decisions.record(rid, preprint, "blocks_in_title")
    outcome = decisions.work_outcome(rid, work_id)
    assert (outcome["stage"], outcome["outcome"], outcome["source_version_id"]) == ("abstract", "candidate", preprint)
    # The head stays pending, but now because a code rule said so rather than because nothing decided it.
    assert decisions.derive_selection(rid, work_id) == "pending"
    head = store.conn.execute("SELECT state, origin FROM selections WHERE source_version_id = ?", (published,)).fetchone()
    assert (head["state"], head["origin"]) == ("pending", "code_rule")


def test_every_version_out_of_scope_excludes_the_work(store):
    rid, run_id = research(store)
    published, preprint, work_id = two_versions(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, published, "both_blocks_missing")
    decisions.record(rid, preprint, "both_blocks_missing")
    assert decisions.work_outcome(rid, work_id)["outcome"] == "out_of_scope"
    assert decisions.derive_selection(rid, work_id) == "excluded"


def test_two_versions_that_disagree_leave_the_work_unresolved(store):
    rid, run_id = research(store)
    published, preprint, work_id = two_versions(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, published, "criterion_absent")
    decisions.record(rid, preprint, "all_parts_verified")
    outcome = decisions.work_outcome(rid, work_id)
    assert (outcome["outcome"], outcome["reason_code"], outcome["decided_by"]) == ("unresolved", "versions_disagree", "code")
    assert outcome["source_version_id"] == preprint  # the version that says include
    assert "versions_disagree" not in REASON_CODES  # it is reported, never stored as a decision
    assert store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE reason_code = 'versions_disagree'").fetchone()[0] == 0
    assert decisions.derive_selection(rid, work_id) == "pending"  # an open disagreement is not an exclusion
    last = store.conn.execute("SELECT reason FROM selection_history WHERE source_version_id = ? ORDER BY id DESC LIMIT 1",
                              (published,)).fetchone()[0]
    assert last == "versions_disagree"


def test_the_users_decision_on_one_version_answers_for_the_work(store):
    rid, run_id = research(store)
    published, preprint, work_id = two_versions(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, published, "criterion_absent")
    decisions.record(rid, preprint, "human_include")
    outcome = decisions.work_outcome(rid, work_id)
    assert (outcome["outcome"], outcome["decided_by"]) == ("include", "human")
    assert decisions.derive_selection(rid, work_id) == "included"


def test_a_full_text_decision_answers_over_an_abstract_decision(store):
    rid, run_id = research(store)
    published, preprint, work_id = two_versions(store, rid, run_id)
    decisions = DecisionStore(store)
    decisions.record(rid, published, "blocks_in_title")
    decisions.record(rid, preprint, "criterion_absent")
    assert decisions.work_outcome(rid, work_id)["stage"] == "fulltext"
    assert decisions.derive_selection(rid, work_id) == "excluded"


def test_a_work_without_a_decision_has_no_outcome(store):
    rid, run_id = research(store)
    _, work_id = one_record(store, rid, run_id)
    decisions = DecisionStore(store)
    assert decisions.work_outcome(rid, work_id) == {}
    assert decisions.derive_selection(rid, work_id) is None


# ---- permanent deletion -----------------------------------------------------------------------
def decorate(store, rid, run_id, svid):
    """Give a record a decision, a proposal and a rank."""
    decisions, sid = DecisionStore(store), step_id(store, run_id, f"screening:{svid[-4:]}")
    decisions.record(rid, svid, "criterion_absent", step_id=sid)
    decisions.add_proposal(rid, svid, "fulltext", sid, 1, "criterion_not_met")
    decisions.save_ranks(sid, rid, [{"source_version_id": svid, "signal": "fused", "rank": 1.0, "available": True}])


def test_a_research_with_decisions_proposals_and_ranks_can_be_deleted_for_good(store):
    rid, run_id = research(store)
    svid, _ = one_record(store, rid, run_id)
    decorate(store, rid, run_id, svid)
    store.update_run(run_id, status="cancelled")
    store.trash_research(rid)
    store.purge_research(rid)
    for table in ("stage_decisions", "model_proposals", "record_signal_ranks"):
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_purging_a_removed_source_takes_its_decisions_and_leaves_the_others(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1"), record("W2", title="SYNTHETIC second record", doi="10.1/two")])
    gone = store.find_source_by_identifier("openalex", "W1")
    kept = store.find_source_by_identifier("openalex", "W2")
    decorate(store, rid, run_id, gone)
    decorate(store, rid, run_id, kept)
    store.update_run(run_id, status="cancelled")
    store.remove_sources(rid, [gone], None)
    assert store.purge_sources(rid, [gone])[0] == [gone]
    decisions = DecisionStore(store)
    assert store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE source_version_id = ?", (gone,)).fetchone()[0] == 0
    assert decisions.current(rid, kept, "fulltext")["reason_code"] == "criterion_absent"
    assert len(decisions.proposals(rid, kept, "fulltext")) == 1 and len(decisions.ranks(rid, kept)) == 1
    # The purge authorization the trigger reads is taken back with the transaction that used it.
    assert store.conn.execute("SELECT COUNT(*) FROM research_purge_authorizations").fetchone()[0] == 0
    with pytest.raises(Exception):
        store.conn.execute("DELETE FROM stage_decisions WHERE source_version_id = ?", (kept,))

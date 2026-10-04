"""The pure rules of the abstract stage: what code settles, which works are read, and what two runs mean (slice 09).

No database, no model and no network here: every case is a function of records, blocks and proposals. Records,
titles and abstracts are SYNTHETIC and from two fields (a greenhouse-irrigation question and a wireless-sensor one).
Passing shows the rules behave as the slice says — not that the labels a model would give are right.
"""

import pytest

from deixis.domain.reason_codes import REASON_CODES, reason
from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_QUOTE_MIN_CHARS, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS
from deixis.workflow import abstract_stage

BLOCKS = {"setting": ["greenhouse tomato"], "task": ["irrigation scheduling"], "outcome": ["marketable yield"]}
ABSTRACT = "We vary the irrigation scheduling of a greenhouse tomato crop and report the marketable yield."


def record(rid="svr_1", title="SYNTHETIC irrigation scheduling in greenhouse tomato crops", abstract=ABSTRACT,
           doi="10.1/oa.1", version_label=None, decision=None):
    return {"id": rid, "title": title, "abstract": abstract, "doi": doi, "version_label": version_label,
            "decision": decision}


# ---- Task 1: what code settles on its own ------------------------------------------------------

def test_the_four_new_codes_are_in_the_table_and_none_of_them_includes_anything():
    for code in ("abstract_not_read", "runs_agree_unresolved", "notice_record", "artifact_of_paper"):
        assert reason(code).stage == "abstract"
    assert (reason("notice_record").outcome, reason("notice_record").decided_by) == ("out_of_scope", "code")
    assert (reason("artifact_of_paper").outcome, reason("artifact_of_paper").decided_by) == ("out_of_scope", "code")
    assert (reason("abstract_not_read").outcome, reason("abstract_not_read").next_step) == ("unresolved", "abstract_model")
    assert reason("runs_agree_unresolved").decided_by == "model_agreement"
    # The abstract stage has no `include` outcome at all: nothing is included from an abstract (SW1.2).
    assert not [c for c in REASON_CODES.values() if c.stage == "abstract" and c.outcome == "include"]


def test_a_correction_notice_is_out_of_scope_without_a_model():
    notice = record(title="Publisher Correction: SYNTHETIC irrigation scheduling in greenhouse tomato crops")
    assert abstract_stage.code_outcome(notice, BLOCKS, set()) == "notice_record"


def test_an_artifact_with_a_stored_link_is_that_paper_s_data_and_one_without_a_link_is_screened():
    artifact = record(doi="10.5281/zenodo.1")
    assert abstract_stage.code_outcome(artifact, BLOCKS, {"svr_1"}) == "artifact_of_paper"
    # No link: it goes on through branches 4 to 6 like any other record (named deviation from SW6.2).
    assert abstract_stage.code_outcome(artifact, BLOCKS, set()) == "blocks_in_title"
    off_topic = record(rid="svr_2", doi="10.5281/zenodo.2", title="SYNTHETIC bakery logistics of a small town",
                       abstract="We deliver SYNTHETIC bread to the market every morning.")
    assert abstract_stage.code_outcome(off_topic, BLOCKS, set()) == "both_blocks_missing"


@pytest.mark.parametrize("held", ["survey_title_word", "no_abstract", "abstract_not_found"])
def test_a_decision_slice_05_owns_stands_and_this_stage_writes_nothing_over_it(held):
    """SW5.5 and SW9.3: the routing slice 05 chose is not confirmed, replaced or contradicted here."""
    assert abstract_stage.code_outcome(record(decision=held), BLOCKS, set()) is None
    off_topic = record(title="SYNTHETIC bakery logistics", abstract="We deliver SYNTHETIC bread.", decision=held)
    assert abstract_stage.code_outcome(off_topic, BLOCKS, set()) is None


def test_both_gate_blocks_in_the_title_make_a_candidate_and_the_outcome_block_does_not_count():
    assert abstract_stage.code_outcome(record(), BLOCKS, set()) == "blocks_in_title"
    one_block = record(title="SYNTHETIC irrigation scheduling under plastic covers")
    assert abstract_stage.code_outcome(one_block, BLOCKS, set()) is None
    # Only the two gate blocks decide: a title holding the outcome block and one gate block is no candidate, and
    # a record holding the outcome block and nothing else is still out of scope.
    outcome_and_one = record(title="SYNTHETIC marketable yield under irrigation scheduling")
    assert abstract_stage.code_outcome(outcome_and_one, BLOCKS, set()) is None
    outcome_only = record(title="SYNTHETIC marketable yield of a field crop",
                          abstract="We report the marketable yield of a SYNTHETIC field crop.")
    assert abstract_stage.code_outcome(outcome_only, BLOCKS, set()) == "both_blocks_missing"


def test_one_missing_block_does_not_close_a_record_and_two_missing_blocks_do():
    """SW9.2: the model reads a record whose abstract holds one of the two blocks."""
    one = record(title="SYNTHETIC water use of a crop",
                 abstract="We study the irrigation scheduling of an open field and report water use.")
    assert abstract_stage.code_outcome(one, BLOCKS, set()) is None
    neither = record(title="SYNTHETIC bakery logistics of a small town",
                     abstract="We deliver SYNTHETIC bread to the market every morning.")
    assert abstract_stage.code_outcome(neither, BLOCKS, set()) == "both_blocks_missing"


def test_a_vocabulary_with_one_searched_block_closes_nothing_by_code():
    """SW9.2 closes a record that lacks *both* blocks. When only one block holds a term, "both missing" would mean
    "the one block missing", which is exactly the case SW9.2 leaves to the model."""
    off_topic = record(title="SYNTHETIC bakery logistics of a small town",
                       abstract="We deliver SYNTHETIC bread to the market every morning.")
    for blocks in ({"setting": [], "task": ["irrigation scheduling"], "outcome": []},
                   {"setting": ["greenhouse tomato"], "outcome": ["marketable yield"]}):
        assert abstract_stage.code_outcome(off_topic, blocks, set()) is None


def test_a_record_without_an_abstract_is_never_out_of_scope_whatever_the_blocks_say():
    """SW5.5: nothing a code rule reads can drop a record nobody could judge."""
    for decision in (None, "abstract_not_found", "no_abstract"):
        blank = record(title="SYNTHETIC bakery logistics of a small town", abstract=None, decision=decision)
        assert abstract_stage.code_outcome(blank, BLOCKS, set()) is None
        assert abstract_stage.code_outcome(dict(blank, abstract=""), BLOCKS, set()) is None


def test_a_plural_matches_its_root_and_a_word_that_merely_contains_a_form_does_not():
    """The one matcher: `ranking.block_scores`'s word-start form, with the same expectation as the ranking."""
    blocks = {"setting": ["greenhouse"], "task": ["irrigation"]}
    plural = record(title="SYNTHETIC irrigations in greenhouses")
    assert abstract_stage.code_outcome(plural, blocks, set()) == "blocks_in_title"
    inside = record(title="SYNTHETIC overgreenhouse and underirrigation work",
                    abstract="We study SYNTHETIC overgreenhouse covers and underirrigation of a field.")
    assert abstract_stage.code_outcome(inside, blocks, set()) == "both_blocks_missing"


def test_a_same_code_is_not_written_again_and_another_step_s_fresh_code_is_left_alone():
    assert abstract_stage.should_write(None, "both_blocks_missing") is True
    held = {"reason_code": "both_blocks_missing"}
    assert abstract_stage.should_write(held, "both_blocks_missing") is False
    # Unless it went stale: the record was judged again under the question the research is now asking, and a row
    # left at the old revision would read as stale for ever and be read again by every later run.
    assert abstract_stage.should_write(held, "both_blocks_missing", stale=True) is True
    # A code slice 05 owns stands while it is fresh; once the question moved on, this stage may say what it finds.
    survey = {"reason_code": "survey_title_word"}
    assert abstract_stage.should_write(survey, "blocks_in_title") is False
    assert abstract_stage.should_write(survey, "blocks_in_title", stale=True) is True
    assert abstract_stage.should_write({"reason_code": "abstract_not_read"}, "runs_agree_candidate") is True


# ---- Task 3: the read plan --------------------------------------------------------------------

def version(vid, code=None, decision=None, has_abstract=True, decided_by=None, stale=False):
    return {"id": vid, "code": code, "decision": decision, "has_abstract": has_abstract,
            "decided_by": decided_by, "stale": stale}


def work(head, versions=None):
    return {"work_id": f"wrk_{head}", "head": head, "versions": versions or [version(head)]}


def test_the_plan_follows_the_inspection_order_cuts_at_the_limit_and_drops_no_work():
    order = ["c", "a", "b", "d"]
    works = [work(head) for head in ("a", "b", "c", "d")]
    plan = abstract_stage.read_plan(order, works, limit=3, batch=2)
    assert plan["batches"] == [["c", "a"], ["b"]]
    assert plan["not_read"] == ["d"]
    read = [svid for batch in plan["batches"] for svid in batch]
    assert sorted(read + plan["not_read"]) == ["a", "b", "c", "d"]


def test_a_work_the_ranking_never_placed_goes_last_by_identifier():
    plan = abstract_stage.read_plan(["b"], [work("z"), work("b"), work("a")], limit=10, batch=10)
    assert plan["batches"] == [["b", "a", "z"]]


def test_a_code_candidate_a_user_decision_and_a_fresh_model_decision_all_keep_a_work_off_the_list():
    works = [
        work("a", [version("a", code="blocks_in_title")]),
        work("b", [version("b", decision="human_include", decided_by="human")]),
        work("c", [version("c", decision="runs_agree_candidate")]),
        work("d", [version("d", decision="runs_agree_out_of_scope")]),
        work("e", [version("e", decision="quote_not_found_kept_as_candidate")]),
        work("f", [version("f")]),
    ]
    plan = abstract_stage.read_plan(list("abcdef"), works, limit=10, batch=10)
    assert plan == {"batches": [["f"]], "not_read": []}


def test_a_work_read_by_an_earlier_run_is_not_asked_about_again_but_an_unread_one_is():
    """"The second run reads on from where the first stopped": no record is put to the model twice."""
    works = [work("a", [version("a", decision="abstract_not_read")]),
             work("b", [version("b", decision="abstract_not_proposed")]),
             work("c", [version("c", decision="runs_agree_candidate")])]
    plan = abstract_stage.read_plan(list("abc"), works, limit=10, batch=10)
    assert plan["batches"] == [["a", "b"]]


def test_a_decision_that_went_stale_is_read_again():
    works = [work("a", [version("a", decision="runs_agree_out_of_scope", stale=True)]),
             work("b", [version("b", decision="runs_agree_out_of_scope")])]
    plan = abstract_stage.read_plan(["a", "b"], works, limit=10, batch=10)
    assert plan["batches"] == [["a"]]


def test_a_head_without_an_abstract_of_its_own_is_read_through_a_sibling_version():
    """Slice 05's gap: the head was never read although another version of its work carried an abstract."""
    versions = [version("head", has_abstract=False), version("zz"), version("mm")]
    plan = abstract_stage.read_plan(["head"], [{"work_id": "wrk", "head": "head", "versions": versions}],
                                    limit=10, batch=10)
    # The head does not qualify, so the qualifying version with the smallest identifier is read, not the first found.
    assert plan["batches"] == [["mm"]]
    assert abstract_stage.reading_version({"work_id": "wrk", "head": "head", "versions": versions}) == "mm"


def test_a_work_with_no_readable_version_is_in_neither_list():
    versions = [version("a", has_abstract=False), version("b", code="notice_record"),
                version("c", decision="abstract_not_found")]
    plan = abstract_stage.read_plan(["a"], [{"work_id": "wrk", "head": "a", "versions": versions}], limit=10, batch=10)
    assert plan == {"batches": [], "not_read": []}


def test_the_plan_is_the_same_whatever_order_the_works_arrive_in():
    order = ["c", "a", "b", "d", "e"]
    works = [work(head) for head in ("a", "b", "c", "d", "e")]
    first = abstract_stage.read_plan(order, works, limit=4, batch=2)
    second = abstract_stage.read_plan(order, list(reversed(works)), limit=4, batch=2)
    assert first == second


def test_the_budget_formula_is_the_one_the_run_is_given():
    calls = {effort: abstract_stage.model_calls(ABSTRACT_READ_LIMIT[effort], ABSTRACT_BATCH, ABSTRACT_RUNS)
             for effort in ABSTRACT_READ_LIMIT}
    assert calls == {"quick": 4, "standard": 10, "detailed": 30}


# ---- Task 3: what two runs mean ---------------------------------------------------------------

def proposal(label, quote_verified=True):
    return {"label": label, "quote_verified": quote_verified}


@pytest.mark.parametrize("first, second, code", [
    (None, proposal("candidate"), "abstract_not_proposed"),
    (proposal("candidate"), None, "abstract_not_proposed"),
    (None, None, "abstract_not_proposed"),
    (proposal("unresolved"), proposal("unresolved"), "runs_agree_unresolved"),
    (proposal("candidate"), proposal("out_of_scope"), "runs_disagree_kept_as_candidate"),
    (proposal("candidate"), proposal("unresolved"), "runs_disagree_kept_as_candidate"),
    (proposal("out_of_scope"), proposal("unresolved"), "runs_disagree_kept_as_candidate"),
    (proposal("candidate"), proposal("candidate", False), "quote_not_found_kept_as_candidate"),
    (proposal("candidate", False), proposal("candidate"), "quote_not_found_kept_as_candidate"),
    (proposal("out_of_scope", False), proposal("out_of_scope"), "quote_not_found_kept_as_candidate"),
    (proposal("candidate"), proposal("candidate"), "runs_agree_candidate"),
    (proposal("out_of_scope"), proposal("out_of_scope"), "runs_agree_out_of_scope"),
])
def test_every_row_of_the_combination_table(first, second, code):
    assert abstract_stage.combine(first, second) == code
    assert abstract_stage.combine(second, first) == code  # which run answered first decides nothing
    assert reason(code).stage == "abstract"


def test_an_unresolved_pair_needs_no_quote():
    """`unresolved` is the one label that may come without one, so the quote rule must not reach it."""
    assert abstract_stage.combine(proposal("unresolved", False), proposal("unresolved", False)) == "runs_agree_unresolved"


# ---- Task 2 and 3: one run's usable proposals -------------------------------------------------

def candidates(*ids):
    return [{"candidate_id": cid, "abstract": ABSTRACT} for cid in ids]


def entry(cid, label="candidate", quote=ABSTRACT[:40], rationale="SYNTHETIC reason."):
    return {"candidate_id": cid, "label": label, "quote": quote, "rationale": rationale}


def test_a_quote_is_verified_only_when_it_is_the_shown_abstract_s_own_words():
    assert abstract_stage.verified(ABSTRACT[:40], ABSTRACT, ABSTRACT_QUOTE_MIN_CHARS) is True
    # Spacing and punctuation damage still locates (`normalized`); an invented sentence does not.
    assert abstract_stage.verified("irrigation  scheduling of a greenhouse", ABSTRACT, ABSTRACT_QUOTE_MIN_CHARS) is True
    assert abstract_stage.verified("We report a yield of 42 tonnes per hectare.", ABSTRACT, ABSTRACT_QUOTE_MIN_CHARS) is False
    # Too short to stand as a whole abstract's evidence, and a quote from beyond the shown cut is not found.
    assert abstract_stage.verified("we vary", ABSTRACT, ABSTRACT_QUOTE_MIN_CHARS) is False
    assert abstract_stage.verified("report the marketable yield", ABSTRACT[:40], ABSTRACT_QUOTE_MIN_CHARS) is False


def test_an_unknown_a_duplicated_and_a_quoteless_entry_each_cost_that_record_its_proposal():
    records = [entry("cnd_C0000001"), entry("cnd_C0000009"), entry("cnd_C0000002"), entry("cnd_C0000002"),
               entry("cnd_C0000003", quote=""), entry("cnd_C0000004", label="unresolved", quote="")]
    found = abstract_stage.proposals_of(candidates(*[f"cnd_C000000{n}" for n in range(1, 6)]),
                                        records, ABSTRACT_QUOTE_MIN_CHARS)
    # The duplicate takes the first entry with it: nothing says which of the two the model meant.
    assert sorted(found) == ["cnd_C0000001", "cnd_C0000004"]
    assert found["cnd_C0000004"]["label"] == "unresolved" and found["cnd_C0000004"]["quote"] is None
    # A record the output never named is in the same position as one that was dropped.
    assert abstract_stage.combine(found.get("cnd_C0000005"), found.get("cnd_C0000001")) == "abstract_not_proposed"


def test_an_invented_quote_is_kept_as_a_proposal_and_marked_unverified():
    found = abstract_stage.proposals_of(candidates("cnd_C0000001"),
                                        [entry("cnd_C0000001", quote="SYNTHETIC: we report 42 tonnes per hectare.")],
                                        ABSTRACT_QUOTE_MIN_CHARS)
    assert found["cnd_C0000001"]["quote_verified"] is False
    assert abstract_stage.combine(found["cnd_C0000001"], proposal("candidate")) == "quote_not_found_kept_as_candidate"

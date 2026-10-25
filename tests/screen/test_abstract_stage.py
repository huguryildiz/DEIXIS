"""The pure rules of the abstract stage: what code settles, which works are read, and what two runs mean (slice 09).

No database, no model and no network here: every case is a function of records, blocks and proposals. Records,
titles and abstracts are SYNTHETIC and from two fields (a greenhouse-irrigation question and a wireless-sensor one).
Passing shows the rules behave as the slice says — not that the labels a model would give are right.
"""

import pytest

from deixis.domain.reason_codes import REASON_CODES, reason
from deixis.domain.rules import ABSTRACT_QUOTE_MIN_CHARS
from deixis.workflow.screen import abstract_stage

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


def test_one_missing_block_does_not_close_a_record_and_two_missing_blocks_do():
    """SW9.2: the model reads a record whose abstract holds one of the two blocks."""
    one = record(title="SYNTHETIC water use of a crop",
                 abstract="We study the irrigation scheduling of an open field and report water use.")
    assert abstract_stage.code_outcome(one, BLOCKS, set()) is None
    neither = record(title="SYNTHETIC bakery logistics of a small town",
                     abstract="We deliver SYNTHETIC bread to the market every morning.")
    assert abstract_stage.code_outcome(neither, BLOCKS, set()) == "both_blocks_missing"


def test_a_record_without_an_abstract_is_never_out_of_scope_whatever_the_blocks_say():
    """SW5.5: nothing a code rule reads can drop a record nobody could judge."""
    for decision in (None, "abstract_not_found", "no_abstract"):
        blank = record(title="SYNTHETIC bakery logistics of a small town", abstract=None, decision=decision)
        assert abstract_stage.code_outcome(blank, BLOCKS, set()) is None
        assert abstract_stage.code_outcome(dict(blank, abstract=""), BLOCKS, set()) is None


@pytest.mark.parametrize("held", ["no_abstract"])
def test_a_decision_slice_05_owns_stands_and_this_stage_writes_nothing_over_it(held):
    """SW5.5 and SW9.3: the routing slice 05 chose is not confirmed, replaced or contradicted here."""
    assert abstract_stage.code_outcome(record(decision=held), BLOCKS, set()) is None
    off_topic = record(title="SYNTHETIC bakery logistics", abstract="We deliver SYNTHETIC bread.", decision=held)
    assert abstract_stage.code_outcome(off_topic, BLOCKS, set()) is None


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


# ---- Task 3: what two runs mean ---------------------------------------------------------------

def proposal(label, quote_verified=True):
    return {"label": label, "quote_verified": quote_verified}


@pytest.mark.parametrize("first, second, code", [
    pytest.param(None, None, "abstract_not_proposed", id="None-None-abstract_not_proposed"),
    pytest.param(proposal("unresolved"), proposal("unresolved"), "runs_agree_unresolved",
                 id="first3-second3-runs_agree_unresolved"),
    pytest.param(proposal("candidate"), proposal("out_of_scope"), "runs_disagree_kept_as_candidate",
                 id="first4-second4-runs_disagree_kept_as_candidate"),
    pytest.param(proposal("out_of_scope", False), proposal("out_of_scope"), "quote_not_found_kept_as_candidate",
                 id="first9-second9-quote_not_found_kept_as_candidate"),
    pytest.param(proposal("candidate"), proposal("candidate"), "runs_agree_candidate",
                 id="first10-second10-runs_agree_candidate"),
    pytest.param(proposal("out_of_scope"), proposal("out_of_scope"), "runs_agree_out_of_scope",
                 id="first11-second11-runs_agree_out_of_scope"),
])
def test_every_row_of_the_combination_table(first, second, code):
    assert abstract_stage.combine(first, second) == code
    assert abstract_stage.combine(second, first) == code  # which run answered first decides nothing
    assert reason(code).stage == "abstract"


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


def test_an_invented_quote_is_kept_as_a_proposal_and_marked_unverified():
    found = abstract_stage.proposals_of(candidates("cnd_C0000001"),
                                        [entry("cnd_C0000001", quote="SYNTHETIC: we report 42 tonnes per hectare.")],
                                        ABSTRACT_QUOTE_MIN_CHARS)
    assert found["cnd_C0000001"]["quote_verified"] is False
    assert abstract_stage.combine(found["cnd_C0000001"], proposal("candidate")) == "quote_not_found_kept_as_candidate"

"""Other names for the search terms: the contract of one call and the code that screens what it returns (slice 08c).

Pure: no store, no network, no flow, and no model was ever called with this step's instructions. What is checked is
that a proposal must name a given phrase to have a block at all, that code — not the model and not the card — drops
what cannot enter a query, that the order the model wrote its list in reaches nothing, and that a count this step
already read is never asked for again. Every phrase and question here is SYNTHETIC and from more than one field, so
no product rule can be made to pass by naming a topic. Passing says nothing about whether a proposed name is really
another name for its anchor: only the count probe and the user stand behind that, and neither was measured (D82).
"""

import asyncio
import json
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.domain.rules import (LITERATURE_TASKS, MAX_SUGGESTED_TERMS, NO_REPAIR_TASKS, SUGGESTION_CALLS,
                                 schema_repairs)
from deixis.domain.skill import RUNTIME_FILES, integrity_issues, load_skill_package
from deixis.domain.vocabulary import Extraction
from deixis.providers.query_compiler import quoted
from deixis.workflow import suggestions
from deixis.workflow.approval import MAX_TERM_WORDS, edited_extraction
from deixis.workflow.vocabulary import build_vocabulary
from fakes import valid_response

FIXTURES = Path(__file__).parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text())["G_term_suggestions"]
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]

# SYNTHETIC: a marine ecology question and a transport one, so nothing here is tied to one field.
REEF = "Which restoration methods raise coral cover on degraded reefs, and what survival rate did each one report?"
COUNTS = {
    '"degraded reefs"': 700, '"coral restoration"': 500, '"no record holds this"': 0,
    "degraded": 40_000, "reefs": 9_000, "coral": 30_000, "restoration": 60_000,
    "(reefs) AND (coral)": 400,
}


async def _count(query):
    return COUNTS.get(query)


def vocabulary(claim=(), exclusion=(), outcome=(), extra_task=()):
    """The vocabulary a first round would have built for the reef question, with the side lists a test needs."""
    built = asyncio.run(build_vocabulary(Extraction(
        language="en",
        blocks={"setting": ["degraded reefs"], "task": ["coral restoration", *extra_task], "outcome": list(outcome)},
        claim_words=list(claim), exclusion_words=list(exclusion), block_assignment="rule", origins={}), _count))
    return built


def proposed(*pairs):
    return [{"phrase": phrase, "synonym_of": anchor} for phrase, anchor in pairs]


# ---- Task 1: the contract of one call -------------------------------------------------------------------

def test_the_new_task_is_registered_with_its_schema_its_method_file_and_no_repair():
    assert contracts.TASK_OUTPUTS["term_suggestions"] == ("TermSuggestions",)
    assert contracts.SCHEMA_VERSIONS["TermSuggestions"] == "deixis.term_suggestions.v1"
    assert RUNTIME_FILES["term_suggestions"] == ("SKILL.md", "references/term-suggestions.md")
    assert "term_suggestions" in LITERATURE_TASKS  # the literature model proposes terms, as it labels blocks
    # One attempt: the user is waiting in front of the card and the repeat is their own button (SW2.5).
    assert "term_suggestions" in NO_REPAIR_TASKS and schema_repairs("term_suggestions") == 0
    assert SUGGESTION_CALLS == 1


def test_the_strict_schema_holds_the_hand_picked_bound_and_asks_for_no_rationale():
    schema = contracts.step_output_schema("term_suggestions")
    terms = schema["properties"]["terms"]
    assert (terms["minItems"], terms["maxItems"]) == (0, MAX_SUGGESTED_TERMS)
    # No rationale and no block: free text cannot be checked, and the block comes from the anchor by code.
    assert set(terms["items"]["properties"]) == {"phrase", "synonym_of"}
    assert contracts.strict_compatibility_issues(schema) == []


def test_the_method_package_is_intact_and_carries_the_new_file():
    assert integrity_issues() == []
    package = load_skill_package()
    assert "references/term-suggestions.md" in package.files
    # The file is part of the package, so the hash every StepInput echoes covers it (before/after in sw-status.md).
    assert "term_suggestions" in package.runtime_text("term_suggestions")


def test_the_fake_adapter_answers_the_new_task_with_a_valid_proposal():
    report = contracts.validate_model_output(STEP_INPUT, valid_response(STEP_INPUT))
    assert report.ok, [vars(i) for i in report.issues]
    assert report.output_type == "TermSuggestions"


@pytest.mark.parametrize("name", ["term_suggestions_valid", "term_suggestions_empty_terms",
                                  "term_suggestions_unknown_anchor",
                                  "term_suggestions_repeats_given_and_avoided_phrases"])
def test_the_fixture_cases_are_judged_as_the_slice_says(name):
    case = next(c for c in CASES if c["name"] == name)
    report = contracts.validate_model_output(STEP_INPUT, case["output"])
    assert report.codes() == sorted(case["expect_codes"])
    assert report.ok is case["expect_ok"]


def test_one_name_for_a_phrase_that_was_never_given_invalidates_the_whole_output():
    """Without a given phrase behind it a proposal has no block and no anchor, so code would invent both."""
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "term_suggestions_valid")["output"]))
    draft["terms"].append({"phrase": "reef rehabilitation", "synonym_of": "a phrase nobody gave"})
    report = contracts.validate_model_output(STEP_INPUT, draft)
    assert report.codes() == ["phrase_not_in_allowlist"] and not report.ok


def test_the_suggestion_target_belongs_to_this_task_and_to_no_other():
    without = json.loads(json.dumps(STEP_INPUT))
    del without["suggestion_target"]
    assert "suggestion_target_mismatch" in {i.code for i in contracts.check_step_input(without)}

    elsewhere = json.loads(json.dumps(json.loads((FIXTURES / "step-inputs.json").read_text())["A_search_plan"]))
    elsewhere["suggestion_target"] = STEP_INPUT["suggestion_target"]
    assert "suggestion_target_mismatch" in {i.code for i in contracts.check_step_input(elsewhere)}


def test_the_allowlist_of_the_step_is_the_anchor_list_itself():
    assert contracts.check_step_input(STEP_INPUT) == []
    wider = json.loads(json.dumps(STEP_INPUT))
    wider["allowlist"]["phrases"] = wider["allowlist"]["phrases"] + ["reef rehabilitation"]
    assert "phrase_allowlist_mismatch" in {i.code for i in contracts.check_step_input(wider)}


# ---- Task 2: the anchors, the target and the screening ---------------------------------------------------

def test_every_searched_phrase_is_an_anchor_with_its_count_and_a_dropped_one_is_too():
    built = vocabulary(extra_task=["no record holds this"])
    given = suggestions.anchors(built)
    assert [row["phrase"] for row in given] == ["degraded reefs", "coral restoration", "no record holds this"]
    assert [row["block"] for row in given] == ["setting", "task", "task"]
    # The phrase no record holds stays an anchor: it is the one the field most probably calls something else.
    assert given[2]["records"] == 0
    assert next(t for t in built["terms"] if t["phrase"] == "no record holds this")["dropped"] == "zero_results"


def test_an_unreadable_count_reaches_the_target_as_null_and_never_as_zero():
    built = vocabulary()
    for term in built["terms"]:
        term["phrase_count"] = None
    assert [row["records"] for row in suggestions.anchors(built)] == [None, None]


def test_the_target_carries_the_question_the_anchors_the_avoided_phrases_and_the_bound():
    built = vocabulary(claim=["we propose"], exclusion=["survey"], outcome=["survival rate"])
    target = suggestions.target(REEF, built)
    assert target["question_text"] == REEF and target["max_terms"] == MAX_SUGGESTED_TERMS
    # Claim words, then exclusion words, then outcome terms, in the proposal's own order.
    assert target["avoid"] == ["we propose", "survey", "survival rate"]
    assert set(target) == {"question_text", "phrases", "avoid", "max_terms"}


def test_a_vocabulary_with_no_searched_phrase_offers_no_anchor():
    built = vocabulary()
    built["terms"] = []
    assert suggestions.anchors(built) == [] and suggestions.target(REEF, built)["phrases"] == []


def test_a_proposal_takes_the_block_of_its_anchor_and_is_normalised():
    rows = suggestions.screen(vocabulary(), proposed(("  Reef  Rehabilitation ", "coral restoration")))
    assert rows == [{"phrase": "reef rehabilitation", "synonym_of": "coral restoration", "block": "task",
                     "phrase_count": None, "dropped": None}]


@pytest.mark.parametrize(("phrase", "reason"), [
    ("one two three four five six seven", "too_long"),
    ("coral restoration", "already_present"),      # the anchor itself
    ("degraded reefs", "already_present"),         # another phrase of the proposal
    ("we propose a reef method", "contains_claim_word"),
    ("reef survey of the atoll", "contains_exclusion_word"),
])
def test_each_drop_reason_is_written_on_its_own_row(phrase, reason):
    built = vocabulary(claim=["we propose"], exclusion=["survey"])
    rows = suggestions.screen(built, proposed((phrase, "coral restoration")))
    assert [row["dropped"] for row in rows] == [reason]
    assert rows[0]["dropped"] in suggestions.DROP_REASONS


def test_the_same_name_twice_keeps_the_first_row_and_marks_the_second_a_duplicate():
    rows = suggestions.screen(vocabulary(), proposed(("reef rehabilitation", "coral restoration"),
                                                     ("reef rehabilitation", "degraded reefs")))
    # Canonical order puts the setting anchor first, so that row is the one that stays.
    assert [(row["synonym_of"], row["dropped"]) for row in rows] == [
        ("degraded reefs", None), ("coral restoration", "duplicate")]


def test_a_claim_phrase_inside_a_longer_name_drops_it_and_one_shared_word_does_not():
    built = vocabulary(claim=["integer programming"])
    rows = suggestions.screen(built, proposed(("mixed integer programming model", "coral restoration"),
                                              ("integer reef counts", "coral restoration")))
    by_phrase = {row["phrase"]: row["dropped"] for row in rows}
    assert by_phrase["mixed integer programming model"] == "contains_claim_word"
    assert by_phrase["integer reef counts"] is None


def test_the_row_order_does_not_follow_the_order_the_model_wrote_the_list_in():
    built = vocabulary()
    pairs = [("reef rehabilitation", "coral restoration"), ("shallow reef", "degraded reefs"),
             ("coral gardening", "coral restoration")]
    forward = suggestions.screen(built, proposed(*pairs))
    backward = suggestions.screen(built, proposed(*reversed(pairs)))
    assert forward == backward
    # The anchor's place in the vocabulary, then the phrase.
    assert [row["phrase"] for row in forward] == ["shallow reef", "coral gardening", "reef rehabilitation"]


def test_a_name_for_a_phrase_outside_the_anchors_is_left_out_rather_than_given_a_block():
    rows = suggestions.screen(vocabulary(), proposed(("reef rehabilitation", "a phrase nobody gave")))
    assert rows == []


def test_the_bound_of_the_proposal_and_the_bound_of_a_term_edit_are_the_same_numbers():
    assert MAX_TERM_WORDS == 6
    schema = contracts.load_schema("TermSuggestions")
    assert schema["properties"]["terms"]["maxItems"] == MAX_SUGGESTED_TERMS
    assert schema["properties"]["terms"]["items"]["properties"]["phrase"]["maxLength"] == 80


def test_only_a_count_that_was_read_becomes_a_known_count():
    rows = suggestions.screen(vocabulary(), proposed(("reef rehabilitation", "coral restoration"),
                                                     ("coral gardening", "coral restoration")))
    rows[0]["phrase_count"] = 0
    rows[1]["phrase_count"] = None
    # A zero is carried on purpose: it drops the phrase again if the user types it by hand.
    assert suggestions.known_counts(rows) == {quoted("coral gardening"): 0}
    assert quoted("reef rehabilitation") not in suggestions.known_counts(rows)


def test_every_proposed_phrase_counts_as_the_model_s_including_a_dropped_one():
    built = vocabulary(claim=["we propose"])
    rows = suggestions.screen(built, proposed(("reef rehabilitation", "coral restoration"),
                                              ("we propose a reef method", "coral restoration")))
    assert suggestions.model_phrases(rows) == {"reef rehabilitation", "we propose a reef method"}


def test_the_term_origin_is_model_only_for_a_phrase_this_approval_proposed():
    built = vocabulary()
    edits = [{"op": "add", "phrase": "reef rehabilitation", "block": "task"},
             {"op": "add", "phrase": "my own phrase", "block": "task"}]
    extraction = edited_extraction(built, edits, model_phrases={"reef rehabilitation"})
    assert extraction.origins["reef rehabilitation"] == "model"
    assert extraction.origins["my own phrase"] == "user"


def test_without_suggestions_the_edited_extraction_is_what_it_was_before_this_slice():
    built = vocabulary()
    edits = [{"op": "add", "phrase": "reef rehabilitation", "block": "task"}]
    assert edited_extraction(built, edits) == edited_extraction(built, edits, model_phrases=frozenset())
    assert edited_extraction(built, edits).origins["reef rehabilitation"] == "user"


def test_a_transport_question_is_screened_by_the_same_rules_as_a_reef_one():
    """SYNTHETIC second field: nothing in the code names a topic."""
    built = asyncio.run(build_vocabulary(Extraction(
        language="en", blocks={"setting": ["urban bus networks"], "task": ["headway regularity"], "outcome": []},
        claim_words=["we formulate"], exclusion_words=[], block_assignment="rule", origins={}), _count))
    rows = suggestions.screen(built, proposed(("bus bunching control", "headway regularity"),
                                              ("we formulate a headway model", "headway regularity"),
                                              ("urban bus networks", "urban bus networks")))
    assert [(row["phrase"], row["dropped"]) for row in rows] == [
        ("urban bus networks", "already_present"),
        ("bus bunching control", None),
        ("we formulate a headway model", "contains_claim_word")]


# ---- review: a carried list is judged against the proposal it is shown on -------------------------------

def _counted(rows, counts):
    return [row | {"phrase_count": None if row["dropped"] else counts[row["phrase"]]} for row in rows]


def test_a_carried_list_is_screened_again_against_the_proposal_it_is_shown_on():
    """A later run of the same question may build other phrases (the labelling is a model's); the rows must follow."""
    earlier = _counted(suggestions.screen(vocabulary(), proposed(
        ("reef rehabilitation", "coral restoration"), ("coral survival rate", "coral restoration"),
        ("outplanting", "degraded reefs"))), {"reef rehabilitation": 30, "coral survival rate": 90, "outplanting": 12})
    assert [row["dropped"] for row in earlier] == [None, None, None]
    # The second proposal holds one of the names as a term of its own, keeps another as a claim phrase, and no
    # longer searches the phrase the third one was another name for.
    later = vocabulary(claim=["survival rate"], extra_task=["reef rehabilitation"])
    later["terms"] = [term for term in later["terms"] if term["phrase"] != "degraded reefs"]
    rows = {row["phrase"]: row for row in suggestions.carry(later, earlier)}
    assert rows["reef rehabilitation"]["dropped"] == "already_present"
    assert rows["coral survival rate"]["dropped"] == "contains_claim_word"
    assert rows["outplanting"]["dropped"] == "anchor_not_searched"
    # Every row is still on record, so a reapplied correction still reads its `model` origin from the list.
    assert suggestions.model_phrases(list(rows.values())) == {"reef rehabilitation", "coral survival rate", "outplanting"}


def test_a_carried_row_keeps_the_count_it_was_read_at_and_is_not_counted_again():
    earlier = _counted(suggestions.screen(vocabulary(), proposed(
        ("reef rehabilitation", "coral restoration"), ("no record holds this", "coral restoration"))),
        {"reef rehabilitation": 30, "no record holds this": 0})
    earlier[0]["dropped"] = "zero_results"  # rows sort by phrase: "no record holds this" comes first
    rows = suggestions.carry(vocabulary(), earlier)
    assert [(row["phrase"], row["phrase_count"], row["dropped"]) for row in rows] == [
        ("no record holds this", 0, "zero_results"), ("reef rehabilitation", 30, None)]
    assert suggestions.known_counts(rows) == {quoted("reef rehabilitation"): 30, quoted("no record holds this"): 0}

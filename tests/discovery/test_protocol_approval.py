"""The correction a user makes to the proposed vocabulary and criterion, checked and applied (slice 08a, SW2.6).

Pure: no store, no network, no flow. What is checked is that a refused correction names every fault, that the order
the operations arrive in never reaches the result, that a corrected vocabulary is rebuilt through the one code path
that builds every vocabulary, and that a count already read is never asked for again. Every phrase, question and
criterion here is SYNTHETIC and from more than one field.
"""

import asyncio

import pytest

from deixis.providers.query_compiler import compile_block_queries
from deixis.workflow import approval
from deixis.workflow.vocabulary import MAX_PROBES, TERM_FIELDS, build_vocabulary
from deixis.domain.vocabulary import Extraction

# SYNTHETIC: a soil science question and a clinical one, so no product rule can be tuned to one field.
SOIL = "How does biochar addition change nitrous oxide emissions in arable soils?"
COUNTS = {
    '"arable soils"': 900, '"biochar addition"': 400, '"nitrous oxide emissions"': 700,
    "arable": 4_000, "soils": 60_000, "biochar": 1_200, "addition": 90_000,
    "nitrous": 2_000, "oxide": 80_000, "emissions": 150_000,
    "(arable) AND (biochar OR nitrous)": 300,
    '"cover crops"': 800, "cover": 70_000, "crops": 50_000,
    "(arable) AND (biochar OR nitrous OR cover)": 420,
    "(arable) AND (nitrous)": 260, "(arable) AND (biochar)": 180,
    "(arable OR biochar) AND (nitrous)": 520,
    '"no such phrase anywhere"': 0,
}


class Probe:
    """A count probe that answers from a fixed table and records every query it was really asked."""

    def __init__(self, counts=None):
        self.asked, self.counts = [], counts if counts is not None else COUNTS

    async def __call__(self, query):
        self.asked.append(query)
        return self.counts.get(query)


def extraction(origins=None):
    return Extraction(language="en",
                      blocks={"setting": ["arable soils"], "task": ["biochar addition", "nitrous oxide emissions"],
                              "outcome": []},
                      claim_words=[], exclusion_words=[], block_assignment="rule", origins=origins or {})


def proposal(probe=None, criterion=None):
    """The vocabulary a first round would have built for the soil question, plus a criterion to correct."""
    built = asyncio.run(build_vocabulary(extraction(), probe or Probe()))
    built["labelling"] = {"runs_ok": 3, "skipped": None, "failures": [], "phrases": [
        {"phrase": "arable soils", "rule_block": "setting", "runs": ["setting"] * 3, "block": "setting",
         "origin": "model"},
        {"phrase": "biochar addition", "rule_block": "task", "runs": ["task"] * 3, "block": "task",
         "origin": "model"},
        {"phrase": "nitrous oxide emissions", "rule_block": "task", "runs": ["task"] * 2, "block": "task",
         "origin": "rule"},
    ]}
    return {"vocabulary": built, "queries": compile_block_queries(built, ["openalex"], 4),
            "criterion": criterion, "criterion_failures": []}


CRITERION = {
    "criterion": "SYNTHETIC: the paper reports a field trial of a soil amendment and its measured gas flux.",
    "parts": [{"name": "field trial", "definition": "SYNTHETIC: the study was run on a real plot."},
              {"name": "gas flux", "definition": "SYNTHETIC: a flux was measured, not modelled."}],
    "cue_phrases": [{"phrase": "static chamber", "part": "gas flux", "runs": [1, 2]},
                    {"phrase": "randomised plots", "part": "field trial", "runs": [2, 3]}],
    "exclusion_title_words": ["editorial", "review"],
    "dropped_exclusion_title_words": ["soils"],
    "base_run": 2, "runs_ok": [1, 2, 3], "sought_term_in_criterion": True, "origin": "model",
    "question_elements": [{"role": "population", "words": "SYNTHETIC plots", "part": "field trial"}],
    "required_roles": ["population"],
}


def edits(terms=(), criterion=None, note=None):
    return {"terms": list(terms), "criterion": criterion, "note": note}


# ---- Task 1: what a correction may say ------------------------------------------------------------------------

def test_an_empty_correction_is_valid_and_changes_nothing():
    made = proposal()
    assert approval.check_edits(made, edits()) == []
    assert approval.apply_criterion(CRITERION, None) is CRITERION


@pytest.mark.parametrize("edit, fragment", [
    ({"op": "delete", "phrase": "arable soils"}, "Unknown term edit"),
    ({"op": "remove", "phrase": "   "}, "The term is empty"),
    ({"op": "add", "phrase": "a " * 7, "block": "task"}, "more than 6 words"),
    ({"op": "add", "phrase": "x" * 81, "block": "task"}, "longer than 80 characters"),
    ({"op": "move", "phrase": "arable soils", "block": "not_a_term"}, "is not a block"),
    ({"op": "move", "phrase": "arable soils", "block": "nowhere"}, "is not a block"),
    ({"op": "remove", "phrase": "a phrase nobody proposed"}, "There is no term"),
    ({"op": "move", "phrase": "a phrase nobody proposed", "block": "task"}, "There is no term"),
    ({"op": "add", "phrase": "Arable Soils", "block": "task"}, "is already in the setting block"),
])
def test_every_kind_of_broken_term_edit_is_named_on_its_own(edit, fragment):
    errors = approval.check_edits(proposal(), edits([edit]))
    assert len(errors) == 1 and fragment in errors[0], errors


def test_two_edits_of_one_phrase_are_refused_and_not_silently_merged():
    made = proposal()
    errors = approval.check_edits(made, edits([{"op": "remove", "phrase": "arable soils"},
                                               {"op": "move", "phrase": "Arable  soils", "block": "task"}]))
    assert errors == ["Two edits of the term 'arable soils'"]


def test_more_than_the_allowed_number_of_term_edits_is_refused():
    many = [{"op": "add", "phrase": f"synthetic phrase {i}", "block": "task"}
            for i in range(approval.MAX_TERM_EDITS + 1)]
    errors = approval.check_edits(proposal(), edits(many))
    assert errors == [f"At most {approval.MAX_TERM_EDITS} term edits, not {approval.MAX_TERM_EDITS + 1}"]


def test_a_correction_may_name_more_than_one_fault_at_once():
    errors = approval.check_edits(proposal(), edits([
        {"op": "remove", "phrase": "nothing like this"},
        {"op": "add", "phrase": "arable soils", "block": "task"},
    ]))
    assert len(errors) == 2


def test_a_phrase_moved_to_a_side_list_is_a_valid_edit():
    assert approval.check_edits(proposal(), edits([
        {"op": "move", "phrase": "biochar addition", "block": "claim"},
        {"op": "move", "phrase": "nitrous oxide emissions", "block": "exclusion"}])) == []


# ---- Task 1: the criterion a user writes -----------------------------------------------------------------------

def written(**changes):
    body = {"criterion": "SYNTHETIC: the paper measures a flux in the field.",
            "parts": [{"name": "field trial", "definition": "SYNTHETIC: run on a plot."},
                      {"name": "gas flux", "definition": "SYNTHETIC: measured."}],
            # No part is named here, so a fault in the parts does not also fault a cue phrase.
            "cue_phrases": [{"phrase": "static chamber", "part": None}],
            "exclusion_title_words": ["editorial"]}
    return body | changes


@pytest.mark.parametrize("body, fragment", [
    (written(criterion="  "), "The criterion is empty"),
    (written(criterion="x" * 601), "longer than 600 characters"),
    (written(parts=[{"name": "only one", "definition": "SYNTHETIC."}]), "needs 2 to 5 parts"),
    (written(parts=[{"name": "same", "definition": "SYNTHETIC."}, {"name": "Same", "definition": "SYNTHETIC."}]),
     "same name"),
    (written(parts=[{"name": "", "definition": "SYNTHETIC."}, {"name": "b", "definition": "SYNTHETIC."}]),
     "A part name is empty"),
    (written(cue_phrases=[{"phrase": "one two three four five", "part": None}]), "more than 4 words"),
    (written(cue_phrases=[{"phrase": "", "part": None}]), "A cue phrase is empty"),
    (written(cue_phrases=[{"phrase": "static chamber", "part": "no such part"}]), "is not one of the criterion's"),
    (written(exclusion_title_words=[f"w{i}" for i in range(31)]), "At most 30 exclusion title words"),
])
def test_every_bound_of_a_written_criterion_is_named_on_its_own(body, fragment):
    errors = approval.check_edits(proposal(), edits(criterion=body))
    assert len(errors) == 1 and fragment in errors[0], errors


def test_a_part_may_hold_fewer_phrases_than_a_proposal_must_and_a_cue_phrase_may_have_no_part():
    """The consensus does not hold the 6-to-15 bound either, and a user must be able to delete a phrase."""
    assert approval.check_edits(proposal(), edits(criterion=written(cue_phrases=[]))) == []
    assert approval.check_edits(proposal(), edits(criterion=written(
        cue_phrases=[{"phrase": "static chamber", "part": "gas flux"}]))) == []


def test_a_note_longer_than_the_bound_is_refused():
    assert approval.check_edits(proposal(), edits(note="n" * approval.MAX_NOTE_CHARS)) == []
    assert approval.check_edits(proposal(), edits(note="n" * (approval.MAX_NOTE_CHARS + 1))) == [
        f"The note is longer than {approval.MAX_NOTE_CHARS} characters"]


def test_a_written_criterion_keeps_the_runs_of_a_phrase_the_proposal_also_held():
    applied = approval.apply_criterion(CRITERION, written(cue_phrases=[
        {"phrase": "Static Chamber", "part": "gas flux"}, {"phrase": "soil core", "part": "field trial"}]))
    assert {c["phrase"]: c["runs"] for c in applied["cue_phrases"]} == {"static chamber": [1, 2], "soil core": []}
    # The record of the proposal the user corrected travels with the corrected criterion.
    assert applied["base_run"] == 2 and applied["runs_ok"] == [1, 2, 3]
    assert applied["dropped_exclusion_title_words"] == ["soils"]
    assert applied["origin"] == "user"
    # SW23: what the proposal named travels as its record, even when the user's parts no longer hold it.
    assert applied["question_elements"] == CRITERION["question_elements"]
    assert applied["required_roles"] == ["population"]


def test_a_criterion_written_where_the_model_proposed_none_carries_no_provenance():
    applied = approval.apply_criterion(None, written())
    assert applied["base_run"] is None and applied["runs_ok"] == []
    assert applied["sought_term_in_criterion"] is None and applied["origin"] == "user"
    assert applied["question_elements"] == [] and applied["required_roles"] == []
    assert [c["runs"] for c in applied["cue_phrases"]] == [[]]


def test_an_exclusion_word_the_question_itself_uses_is_marked_and_not_removed():
    """SW5.1 drops such a word from a proposal; what the user wrote is kept, because the user saw the question."""
    applied = approval.apply_criterion(CRITERION, written(exclusion_title_words=["biochar", "editorial"]))
    assert applied["exclusion_title_words"] == ["biochar", "editorial"]
    assert approval.exclusion_words_in_question(SOIL, applied) == ["biochar"]
    assert approval.exclusion_words_in_question(SOIL, CRITERION) == []


# ---- Task 2: one code path builds the corrected vocabulary ------------------------------------------------------

def rebuild(made, term_edits, probe=None):
    probe = probe or Probe()
    built = asyncio.run(build_vocabulary(
        approval.edited_extraction(made["vocabulary"], term_edits), probe,
        known={p["query"]: p["count"] for p in made["vocabulary"]["probes"]}))
    built["labelling"] = made["vocabulary"]["labelling"]
    built["user_edits"] = approval.canonical_edits(term_edits)
    return built, probe


def forms(built):
    return [t["root"] if t["in_query"] == "root" else t["phrase"] for t in built["terms"] if not t["dropped"]]


def test_the_order_the_operations_arrive_in_does_not_reach_the_result():
    made = proposal()
    operations = [{"op": "remove", "phrase": "nitrous oxide emissions"},
                  {"op": "add", "phrase": "cover crops", "block": "task"},
                  {"op": "move", "phrase": "biochar addition", "block": "claim"}]
    first, _ = rebuild(made, operations)
    second, _ = rebuild(made, list(reversed(operations)))
    assert first == second
    assert approval.canonical_edits(operations) == approval.canonical_edits(list(reversed(operations)))


def test_a_removed_term_is_in_no_query_and_in_no_term_row():
    made = proposal()
    built, _ = rebuild(made, [{"op": "remove", "phrase": "nitrous oxide emissions"}])
    assert "nitrous oxide emissions" not in [t["phrase"] for t in built["terms"]]
    queries = compile_block_queries(built, ["openalex"], 4)
    assert all("nitrous" not in q["query_text"] for q in queries), queries


def test_a_term_moved_to_the_claim_block_leaves_the_query_and_joins_the_claim_words():
    made = proposal()
    built, _ = rebuild(made, [{"op": "move", "phrase": "biochar addition", "block": "claim"}])
    assert built["claim_words"] == ["biochar addition"]
    assert all("biochar" not in q["query_text"] for q in compile_block_queries(built, ["openalex"], 4))


def test_a_term_moved_out_of_the_claim_block_is_probed_and_enters_the_query():
    made = proposal()
    aside, _ = rebuild(made, [{"op": "move", "phrase": "biochar addition", "block": "claim"}])
    aside["probes"] = made["vocabulary"]["probes"]  # the counts the first round read are still what is known
    back, probe = rebuild({"vocabulary": aside}, [{"op": "move", "phrase": "biochar addition", "block": "task"}])
    assert "biochar" in forms(back)
    assert any("biochar" in q["query_text"] for q in compile_block_queries(back, ["openalex"], 4))


def test_a_term_the_user_added_meets_the_same_count_probe_and_keeps_its_own_origin():
    made = proposal()
    built, probe = rebuild(made, [{"op": "add", "phrase": "cover crops", "block": "task"}])
    assert '"cover crops"' in probe.asked
    added = next(t for t in built["terms"] if t["phrase"] == "cover crops")
    assert added["origin"] == "user" and added["phrase_count"] == 800
    assert all(t["origin"] == "question" for t in built["terms"] if t["phrase"] != "cover crops")


def test_a_term_the_user_added_that_no_record_holds_drops_and_stays_on_record():
    made = proposal()
    built, _ = rebuild(made, [{"op": "add", "phrase": "no such phrase anywhere", "block": "task"}])
    dropped = next(t for t in built["terms"] if t["phrase"] == "no such phrase anywhere")
    assert dropped["dropped"] == "zero_results" and dropped["phrase_count"] == 0
    assert all("no such phrase" not in q["query_text"] for q in compile_block_queries(built, ["openalex"], 4))


def test_a_count_the_proposal_already_read_is_never_asked_for_again():
    made = proposal()
    _, probe = rebuild(made, [{"op": "add", "phrase": "cover crops", "block": "task"}])
    already = {p["query"] for p in made["vocabulary"]["probes"]}
    assert already and not (set(probe.asked) & already), probe.asked


def test_a_cached_count_spends_none_of_the_probe_budget():
    """Otherwise a rebuild would spend the whole allowance on answers it already had, and the added term would be
    left with no count at all."""
    made = proposal()
    known = {p["query"]: p["count"] for p in made["vocabulary"]["probes"]}
    known |= {f"synthetic filler {i}": 1 for i in range(MAX_PROBES * 2)}
    filler = Extraction(language="en", blocks={"setting": ["arable soils"], "task": ["cover crops"], "outcome": []},
                        claim_words=[], exclusion_words=[], block_assignment="rule", origins={})
    probe = Probe()
    built = asyncio.run(build_vocabulary(filler, probe, known=known))
    assert built["probes_skipped"] == 0 and len(probe.asked) < MAX_PROBES


def test_the_block_origin_of_a_phrase_the_user_placed_is_the_user():
    made = proposal()
    built, _ = rebuild(made, [{"op": "add", "phrase": "cover crops", "block": "task"},
                              {"op": "move", "phrase": "biochar addition", "block": "claim"}])
    origins = approval.block_origins(built)
    assert origins["cover crops"] == "user" and origins["biochar addition"] == "user"
    # A phrase the user did not touch keeps what the labelling step said about it.
    assert origins["arable soils"] == "model" and origins["nitrous oxide emissions"] == "rule"


def test_the_term_rows_of_a_corrected_vocabulary_hold_the_same_fields_as_any_other():
    built, _ = rebuild(proposal(), [{"op": "add", "phrase": "cover crops", "block": "task"}])
    assert all(set(term) == set(TERM_FIELDS) for term in built["terms"])


# ---- reapplying an earlier correction ---------------------------------------------------------------------------

def test_an_operation_whose_phrase_is_gone_is_skipped_and_stays_on_record():
    made = proposal()
    gone, skipped = approval.applicable(made["vocabulary"], [
        {"op": "remove", "phrase": "nitrous oxide emissions"},
        {"op": "remove", "phrase": "a phrase this run never found"},
        {"op": "add", "phrase": "arable soils", "block": "task"},
    ])
    assert [edit["phrase"] for edit in gone] == ["nitrous oxide emissions"]
    assert [edit["phrase"] for edit in skipped] == ["a phrase this run never found", "arable soils"]
    assert {edit["reason"] for edit in skipped} == {"phrase_not_in_proposal"}


def test_the_proposal_hash_names_the_phrases_and_the_criterion_and_not_the_counts():
    made = proposal()
    other = proposal(Probe({**COUNTS, '"arable soils"': 12}))
    assert approval.proposal_hash(made["vocabulary"], CRITERION) == approval.proposal_hash(other["vocabulary"], CRITERION)
    moved, _ = rebuild(made, [{"op": "move", "phrase": "biochar addition", "block": "claim"}])
    assert approval.proposal_hash(moved, CRITERION) != approval.proposal_hash(made["vocabulary"], CRITERION)
    assert approval.proposal_hash(made["vocabulary"], None) != approval.proposal_hash(made["vocabulary"], CRITERION)

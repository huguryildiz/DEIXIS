"""The criterion proposal contract and what three proposals agree on (SW15, slice 06).

Two halves: the contract one proposal must satisfy, and `consensus`, which is the whole of the "one run is never
used" rule. The questions and proposals here are SYNTHETIC and from more than one field, so no test can be made to
pass by putting a topic word into the product. Passing shows workflow behavior, not the quality of a criterion:
that was measured once in `.local/sw-criterion-prompt-fix-2026-09-21/` and is measured again in slice 24.
"""

import json
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.domain.canonical import canonical_json
from deixis.domain.rules import LITERATURE_TASKS, NO_REPAIR_TASKS, schema_repairs
from deixis.domain.skill import RUNTIME_FILES, integrity_issues, load_skill_package
from deixis.workflow.criterion import (MAX_PHRASE_WORDS, PARTS_PER_PROPOSAL, PHRASES_PER_PART, PROPOSAL_MAJORITY,
                                       PROPOSAL_RUNS, THRESHOLDS, consensus, norm)
from fakes import valid_response

FIXTURES = Path(__file__).parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text())["E_criterion_proposal"]

# Two SYNTHETIC questions from two fields. Neither is a question of the prompt measurement, so nothing here can be
# made to pass by copying that trial's answers.
FATIGUE = ("SYNTHETIC: which supervised exercise programmes have been tested for reducing fatigue in adults after "
           "chemotherapy, and which fatigue scale did each one report?")
SURVEYS = "SYNTHETIC: which survey instruments measure commuting time in household panel studies?"


def part(name, phrases, definition="SYNTHETIC: what the paper must contain."):
    return {"name": name, "definition": definition, "phrases": list(phrases)}


def proposal(criterion, parts, exclusion=(), elements=()):
    return {"criterion": criterion, "parts": list(parts), "question_elements": list(elements),
            "exclusion_title_words": list(exclusion)}


# ---- Task 1: the contract of one proposal -------------------------------------------------------------------

def test_the_new_task_is_registered_with_its_schema_its_method_files_and_its_repair():
    assert contracts.TASK_OUTPUTS["criterion_proposal"] == ("CriterionProposal",)
    assert contracts.SCHEMA_VERSIONS["CriterionProposal"] == "deixis.criterion_proposal.v2"
    assert RUNTIME_FILES["criterion_proposal"] == ("SKILL.md", "references/criterion-proposal.md")
    assert "criterion_proposal" in LITERATURE_TASKS  # the literature model proposes it, as it screens
    # Nothing in the output is an identifier a repair could invent, so the one repair attempt stays open.
    assert "criterion_proposal" not in NO_REPAIR_TASKS and schema_repairs("criterion_proposal") == 1


def test_the_strict_schema_carries_the_bounds_the_check_enforces():
    schema = contracts.step_output_schema("criterion_proposal")
    parts = schema["properties"]["parts"]
    assert (parts["minItems"], parts["maxItems"]) == PARTS_PER_PROPOSAL
    phrases = parts["items"]["properties"]["phrases"]
    assert (phrases["minItems"], phrases["maxItems"]) == PHRASES_PER_PART
    assert contracts.strict_compatibility_issues(schema) == []
    # No strength mark and no rationale: neither would be checked, so neither is asked for (SW15.7).
    assert set(parts["items"]["properties"]) == {"name", "definition", "phrases"}


def test_the_fake_adapter_answers_the_new_task_with_a_valid_proposal():
    report = contracts.validate_model_output(STEP_INPUT, valid_response(STEP_INPUT))
    assert report.ok, [vars(i) for i in report.issues]
    assert report.output_type == "CriterionProposal"


@pytest.mark.parametrize(("name", "codes"), [
    ("criterion_proposal_valid", []),
    ("criterion_proposal_one_part", ["schema_invalid"]),
    ("criterion_proposal_sixteen_phrases", ["schema_invalid"]),
    ("criterion_proposal_five_word_phrase", ["criterion_phrase_too_long"]),
    ("criterion_proposal_repeated_part_name", ["duplicate_criterion_part"]),
    ("criterion_proposal_valid_with_elements", []),
    ("criterion_proposal_element_unknown_part", ["question_element_unknown_part"]),
    ("criterion_proposal_element_not_in_question", ["question_element_not_in_question"]),
    ("criterion_proposal_duplicate_element", ["duplicate_question_element"]),
    ("criterion_proposal_elements_share_part", ["question_elements_share_part"]),
])
def test_the_fixture_cases_are_judged_as_the_slice_says(name, codes):
    cases = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]
    case = next(c for c in cases if c["name"] == name)
    step_input = json.loads((FIXTURES / "step-inputs.json").read_text())[case["step_input"]]
    report = contracts.validate_model_output(step_input, case["output"])
    assert report.codes() == codes and report.ok is (codes == [])


def test_the_bounds_are_enforced_in_code_as_well_as_in_the_schema():
    """A structured-output implementation may drop array bounds; the check is the floor under that (`step_output_schema`)."""
    report = contracts.ValidationReport()
    contracts._check_criterion_proposal(STEP_INPUT, proposal("SYNTHETIC", [part("only", ["a", "b"])]), report)
    assert sorted(report.codes()) == ["criterion_part_count", "criterion_phrase_count"]


def test_an_empty_phrase_and_a_phrase_written_twice_in_one_part_are_errors():
    phrases = ["fatigue score", "Fatigue Score", "  ", "facit-f", "validated scale", "fatigue outcome"]
    report = contracts.ValidationReport()
    contracts._check_criterion_proposal(STEP_INPUT, proposal("SYNTHETIC", [part("one", phrases),
                                                                         part("two", phrases[:1] * 6)]), report)
    assert "criterion_phrase_empty" in report.codes() and "duplicate_criterion_phrase" in report.codes()


def test_a_phrase_standing_in_two_parts_is_not_an_error():
    shared = ["fatigue score", "fatigue severity", "facit-f", "validated scale", "fatigue outcome", "fatigue scale"]
    report = contracts.ValidationReport()
    contracts._check_criterion_proposal(STEP_INPUT, proposal("SYNTHETIC", [part("one", shared), part("two", shared)]),
                                        report)
    assert report.codes() == []


# ---- Task 2: the method package -----------------------------------------------------------------------------

def test_the_method_package_still_passes_its_integrity_check_and_loads_the_new_file():
    assert integrity_issues() == []
    text = load_skill_package().runtime_text("criterion_proposal")
    assert '<method-file path="references/criterion-proposal.md">' in text
    assert "deixis.criterion_proposal.v2" in text  # the envelope line the DeepSeek adapter needs (slice 04d)


def test_the_method_file_names_no_topic_and_carries_no_worked_example():
    """The measurement's own questions must not enter the package, or the next measurement is in sample."""
    body = (Path(load_skill_package().root) / "references" / "criterion-proposal.md").read_text().lower()
    for topic in ("quantum", "packet size", "wireless sensor", "mindfulness", "vitamin d", "minimum wage",
                  "metformin", "diabetes"):
        assert topic not in body


def test_the_package_hash_covers_the_new_file(tmp_path):
    import shutil

    from deixis.domain import skill
    from deixis.paths import SKILL_DIR

    copy = tmp_path / "deixis-research"
    shutil.copytree(SKILL_DIR, copy)
    before = skill.package_hash(copy)
    target = copy / "references" / "criterion-proposal.md"
    target.write_text(target.read_text() + "\nchanged\n")
    assert skill.package_hash(copy) != before


# ---- Task 3: what the runs agree on --------------------------------------------------------------------------

def three_runs():
    """Three SYNTHETIC proposals. Run 1 shares the most with what the runs agreed on, so it is the base run; one
    kept phrase ("walking programme") stands only in runs 2 and 3, so the base run does not hold it."""
    with_two = ["supervised exercise", "aerobic training", "resistance training", "training sessions",
                "exercise programme", "facit-f"]
    with_three = ["fatigue score", "fatigue severity", "validated scale"]
    return {
        1: proposal("SYNTHETIC: the paper runs a supervised programme and reports a fatigue score.",
                    [part("programme", with_two[:5] + ["training protocol"]),
                     part("fatigue", ["facit-f"] + with_three + ["fatigue outcome", "we measured fatigue"])],
                    ["review", "protocol"]),
        2: proposal("SYNTHETIC: the paper delivers exercise and measures fatigue.",
                    [part("exercise", with_two[:5] + ["walking programme"]),
                     part("fatigue", ["facit-f", "fatigue questionnaire", "tiredness scale", "exhaustion",
                                      "vitality", "energy level"])],
                    ["review", "editorial"]),
        3: proposal("SYNTHETIC: the paper is about exercise.",
                    [part("something else", ["walking programme", "physical activity", "cycling", "step count",
                                             "activity monitor", "gym visits"]),
                     part("fatigue", with_three + ["tiredness", "brief fatigue", "fatigue scale"])],
                    ["review", "editorial"]),
    }


def kept(result):
    return [entry["phrase"] for entry in result["cue_phrases"]]


def test_a_phrase_all_three_runs_wrote_and_one_two_of_them_wrote_are_kept():
    result = consensus(FATIGUE, three_runs())
    entry = next(e for e in result["cue_phrases"] if e["phrase"] == "fatigue score")
    assert entry["runs"] == [1, 3]
    assert next(e for e in result["cue_phrases"] if e["phrase"] == "walking programme")["runs"] == [2, 3]
    assert "facit-f" in kept(result)  # runs 1 and 2


def test_a_phrase_only_one_run_wrote_is_not_kept():
    result = consensus(FATIGUE, three_runs())
    for alone in ("training protocol", "fatigue questionnaire", "step count", "gym visits"):
        assert alone not in kept(result)


def test_one_valid_run_is_no_criterion_at_all():
    """SW15.2: a single run's list varies too much to be used, so the four protocol fields stay null."""
    assert consensus(FATIGUE, {2: three_runs()[2]}) is None
    assert consensus(FATIGUE, {}) is None
    assert PROPOSAL_MAJORITY == 2 and PROPOSAL_RUNS == 3 and THRESHOLDS["proposal_majority"] == PROPOSAL_MAJORITY


def test_the_criterion_sentence_and_the_parts_come_from_the_run_closest_to_the_agreement():
    result = consensus(FATIGUE, three_runs())
    assert result["base_run"] == 1 and result["runs_ok"] == [1, 2, 3]
    assert result["criterion"] == three_runs()[1]["criterion"]
    assert [p["name"] for p in result["parts"]] == ["programme", "fatigue"]
    assert all(set(p) == {"name", "definition"} for p in result["parts"])  # the phrases live in cue_phrases


def test_a_tie_for_the_base_run_goes_to_the_run_that_was_asked_first():
    same = part("one", ["a phrase", "b phrase", "c phrase", "d phrase", "e phrase", "f phrase"])
    runs = {2: proposal("SYNTHETIC: second.", [same, part("two", ["g", "h", "i", "j", "k", "l"])]),
            1: proposal("SYNTHETIC: first.", [same, part("two", ["g", "h", "i", "j", "k", "l"])])}
    assert consensus(FATIGUE, runs)["base_run"] == 1


def test_a_kept_phrase_the_base_run_does_not_hold_belongs_to_no_part():
    result = consensus(FATIGUE, three_runs())
    entry = next(e for e in result["cue_phrases"] if e["phrase"] == "walking programme")
    assert entry["part"] is None  # runs 2 and 3 agreed on it; run 1, whose parts these are, did not write it
    assert next(e for e in result["cue_phrases"] if e["phrase"] == "fatigue score")["part"] == "fatigue"


def test_a_part_no_kept_phrase_belongs_to_stays_in_the_criterion():
    """The parts are the base run's; one of them losing every phrase does not take the part out of the criterion."""
    agreed = ["fatigue score", "fatigue severity", "facit-f", "validated scale", "fatigue outcome", "fatigue scale"]
    alone = ["only one", "run wrote", "these six", "phrases here", "and no", "other run"]
    runs = {1: proposal("SYNTHETIC.", [part("kept", agreed), part("empty", alone)]),
            2: proposal("SYNTHETIC.", [part("kept", agreed), part("other", ["a", "b", "c", "d", "e", "f"])])}
    result = consensus(FATIGUE, runs)
    assert [p["name"] for p in result["parts"]] == ["kept", "empty"]
    assert {e["part"] for e in result["cue_phrases"]} == {"kept"}


def test_an_exclusion_word_two_runs_wrote_is_kept_and_one_run_s_own_is_not():
    result = consensus(FATIGUE, three_runs())
    assert result["exclusion_title_words"] == ["editorial", "review"]  # alphabetical, not the order they arrived in
    assert "protocol" not in result["exclusion_title_words"]


def test_an_exclusion_word_the_question_itself_asks_about_is_dropped_and_recorded():
    """SW5.1's protection: a research asking about surveys may not exclude the word from its own titles."""
    runs = {number: proposal("SYNTHETIC.", [part("one", ["a", "b", "c", "d", "e", "f"]),
                                            part("two", ["g", "h", "i", "j", "k", "l"])],
                             ["survey", "review"]) for number in (1, 2)}
    result = consensus(SURVEYS, runs)
    assert result["exclusion_title_words"] == ["review"]
    assert result["dropped_exclusion_title_words"] == ["survey"]


def test_neither_the_order_the_runs_arrive_in_nor_the_order_inside_them_decides_the_result():
    runs = three_runs()
    shuffled = {number: proposal(runs[number]["criterion"],
                                 [part(p["name"], list(reversed(p["phrases"])), p["definition"])
                                  for p in reversed(runs[number]["parts"])],
                                 list(reversed(runs[number]["exclusion_title_words"])))
                for number in (3, 1, 2)}
    one, other = consensus(FATIGUE, runs), consensus(FATIGUE, dict(reversed(list(shuffled.items()))))
    # The parts keep the base run's own order, which is the run's meaning; everything else is canonical.
    assert canonical_json(one | {"parts": []}) == canonical_json(other | {"parts": []})
    assert {p["name"] for p in one["parts"]} == {p["name"] for p in other["parts"]}


def test_norm_makes_one_vote_of_the_same_phrase_written_three_ways():
    assert norm("  Packet   Size. ") == norm("packet size") == "packet size"
    runs = {1: proposal("SYNTHETIC.", [part("one", ["Fatigue Score.", "b", "c", "d", "e", "f"])]),
            2: proposal("SYNTHETIC.", [part("one", ["  fatigue score  ", "g", "h", "i", "j", "k"])])}
    assert "fatigue score" in kept(consensus(FATIGUE, runs))


@pytest.mark.parametrize(("terms", "expected"), [
    (["supervised programme", "cycling"], True),
    (["commuting time"], False),
    ([], None),
    (["   "], None),
])
def test_the_record_of_whether_the_criterion_named_the_thing_sought_takes_all_three_values(terms, expected):
    """The known defect's trace inside the product. It is recorded and read by nobody in this slice (D78)."""
    assert consensus(FATIGUE, three_runs(), terms)["sought_term_in_criterion"] is expected


def test_the_phrase_word_limit_is_the_one_the_method_file_asks_for():
    assert MAX_PHRASE_WORDS == 4


# ---- Slice 25 (SW23, D106): the population and the comparator the question names -----------------------------

def test_the_schema_requires_the_question_elements_and_closes_them():
    schema = contracts.load_schema("CriterionProposal")
    assert "question_elements" in schema["required"]
    elements = schema["properties"]["question_elements"]
    assert (elements["minItems"], elements["maxItems"]) == (0, 2)
    item = elements["items"]
    assert item["additionalProperties"] is False and set(item["required"]) == {"role", "words", "part"}
    assert item["properties"]["role"]["enum"] == ["population", "comparator"]
    assert (item["properties"]["words"]["minLength"], item["properties"]["words"]["maxLength"]) == (1, 300)
    assert (item["properties"]["part"]["minLength"], item["properties"]["part"]["maxLength"]) == (1, 60)


def test_the_method_file_takes_the_population_out_of_the_setting_and_asks_for_the_elements():
    body = (Path(load_skill_package().root) / "references" / "criterion-proposal.md").read_text()
    setting = body.split("**setting** is", 1)[1].split(".", 1)[0]
    assert "population" not in setting.lower()
    assert "8. When the question names the **population**" in body and "question_elements" in body
    assert "9. Echo" in body
    for topic in ("time-restricted", "fasting", "obes", "quantum", "network coding"):
        assert topic not in body.lower()


def test_an_element_is_found_in_the_steering_as_well_as_in_the_question():
    steered = dict(STEP_INPUT, user_steering=["SYNTHETIC: only trials compared with Usual Care."])
    draft = proposal("SYNTHETIC", [part("usual care arm", ["a", "b", "c", "d", "e", "f"]),
                                   part("two", ["g", "h", "i", "j", "k", "l"])],
                     elements=[{"role": "comparator", "words": "usual care", "part": "Usual Care Arm"}])
    report = contracts.ValidationReport()
    contracts._check_criterion_proposal(steered, draft, report)
    assert report.codes() == []
    report = contracts.ValidationReport()
    contracts._check_criterion_proposal(STEP_INPUT, draft, report)  # the question alone does not hold it
    assert report.codes() == ["question_element_not_in_question"]


def test_words_must_stand_at_a_word_boundary_of_the_question():
    draft = proposal("SYNTHETIC", [part("adults", ["a", "b", "c", "d", "e", "f"]),
                                   part("two", ["g", "h", "i", "j", "k", "l"])],
                     elements=[{"role": "population", "words": "dults after", "part": "adults"}])
    report = contracts.ValidationReport()
    contracts._check_criterion_proposal(STEP_INPUT, draft, report)
    assert report.codes() == ["question_element_not_in_question"]


# The output of the consensus before slice 25 for `three_runs()`, written out by hand so the invariance is checked
# against a fixed value and not against the code under test (plan decision 4 (i)).
BEFORE_SLICE_25 = (
    '{"base_run":1,"criterion":"SYNTHETIC: the paper runs a supervised programme and reports a fatigue score.",'
    '"cue_phrases":[{"part":"programme","phrase":"aerobic training","runs":[1,2]},'
    '{"part":"programme","phrase":"exercise programme","runs":[1,2]},{"part":"fatigue","phrase":"facit-f","runs":[1,2]},'
    '{"part":"fatigue","phrase":"fatigue score","runs":[1,3]},{"part":"fatigue","phrase":"fatigue severity","runs":[1,3]},'
    '{"part":"programme","phrase":"resistance training","runs":[1,2]},'
    '{"part":"programme","phrase":"supervised exercise","runs":[1,2]},'
    '{"part":"programme","phrase":"training sessions","runs":[1,2]},'
    '{"part":"fatigue","phrase":"validated scale","runs":[1,3]},{"part":null,"phrase":"walking programme","runs":[2,3]}],'
    '"dropped_exclusion_title_words":[],"exclusion_title_words":["editorial","review"],'
    '"parts":[{"definition":"SYNTHETIC: what the paper must contain.","name":"programme"},'
    '{"definition":"SYNTHETIC: what the paper must contain.","name":"fatigue"}],"runs_ok":[1,2,3],'
    '"sought_term_in_criterion":true}')


def population(part_name="exercise"):
    return {"role": "population", "words": "adults after chemotherapy", "part": part_name}


def comparator(part_name="fatigue"):
    return {"role": "comparator", "words": "fatigue scale", "part": part_name}


def with_elements(runs, by_run):
    return {number: runs[number] | {"question_elements": by_run.get(number, [])} for number in runs}


def test_i_with_no_role_in_the_majority_the_result_is_what_it_was_before_the_slice():
    runs = with_elements(three_runs(), {3: [population("something else")]})  # one run alone is no majority
    result = consensus(FATIGUE, runs, ["supervised programme"])
    assert result["question_elements"] == [] and result["required_roles"] == []
    rest = {k: v for k, v in result.items() if k not in ("question_elements", "required_roles")}
    assert canonical_json(rest) == BEFORE_SLICE_25


def test_ii_a_role_two_runs_name_moves_the_base_to_a_run_that_holds_it():
    runs = with_elements(three_runs(), {2: [population()], 3: [population("something else")]})
    result = consensus(FATIGUE, runs)
    assert result["required_roles"] == ["population"]
    assert result["base_run"] == 2  # run 1 shares the most phrases but names no population
    assert result["criterion"] == three_runs()[2]["criterion"]
    assert result["question_elements"] == [population()]


def test_iii_two_roles_held_by_different_pairs_of_runs_choose_the_run_holding_both():
    runs = with_elements(three_runs(), {2: [population()], 3: [comparator(), population("something else")],
                                        1: [comparator("programme")]})
    result = consensus(FATIGUE, runs)
    assert result["required_roles"] == ["comparator", "population"]
    assert result["base_run"] == 3
    assert [e["role"] for e in result["question_elements"]] == ["comparator", "population"]


def test_iv_neither_the_order_of_the_runs_nor_of_the_elements_changes_the_result():
    runs = with_elements(three_runs(), {2: [comparator(), population()], 3: [population("something else")],
                                        1: [comparator("programme")]})
    reordered = {number: runs[number] | {"question_elements": list(reversed(runs[number]["question_elements"]))}
                 for number in (3, 2, 1)}
    assert canonical_json(consensus(FATIGUE, runs)) == canonical_json(consensus(FATIGUE, reordered))


def test_v_a_stored_v1_proposal_without_the_field_reads_as_naming_nothing():
    runs = {number: {k: v for k, v in body.items() if k != "question_elements"} for number, body in three_runs().items()}
    result = consensus(FATIGUE, runs, ["supervised programme"])
    assert result["question_elements"] == [] and result["required_roles"] == []
    rest = {k: v for k, v in result.items() if k not in ("question_elements", "required_roles")}
    assert canonical_json(rest) == BEFORE_SLICE_25

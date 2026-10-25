"""The criterion proposal contract, what three proposals agree on, and the proposal inside a discovery run (SW15,
slice 06).

Two halves: the contract one proposal must satisfy, and `consensus`, which is the whole of the "one run is never
used" rule. The questions and proposals here are SYNTHETIC and from more than one field, so no test can be made to
pass by putting a topic word into the product. Passing shows workflow behavior, not the quality of a criterion:
that was measured once in `notes/archive/sw/sw-criterion-prompt-fix-2026-09-21/` and is measured again in slice 24.
"""

import json
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.domain.canonical import canonical_json
from deixis.domain.rules import LITERATURE_TASKS, NO_REPAIR_TASKS, schema_repairs
from deixis.domain.skill import RUNTIME_FILES, integrity_issues, load_skill_package
from deixis.workflow.criterion import PARTS_PER_PROPOSAL, PHRASES_PER_PART, PROPOSAL_MAJORITY, PROPOSAL_RUNS, THRESHOLDS, consensus
import httpx
from fastapi.testclient import TestClient

from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS, CRITERION_CALLS, TEST_EFFORT_BUDGETS
from deixis.models.adapter import ModelStepResult
from deixis.workflow.abstract_stage import model_calls
from fakes import FakeAdapter, envelope, valid_response
from test_vocabulary_flow import CountingOpenAlex, app_for, start, store_at, wait

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text())["E_criterion_proposal"]

# Two SYNTHETIC questions from two fields. Neither is a question of the prompt measurement, so nothing here can be
# made to pass by copying that trial's answers.
FATIGUE = ("SYNTHETIC: which supervised exercise programmes have been tested for reducing fatigue in adults after "
           "chemotherapy, and which fatigue scale did each one report?")


def part(name, phrases, definition="SYNTHETIC: what the paper must contain."):
    return {"name": name, "definition": definition, "phrases": list(phrases)}


def proposal(criterion, parts, exclusion=(), elements=()):
    return {"criterion": criterion, "parts": list(parts), "question_elements": list(elements),
            "exclusion_title_words": list(exclusion)}


# ---- Task 1: the contract of one proposal -------------------------------------------------------------------

def test_the_new_task_is_registered_with_its_schema_its_method_files_and_its_repair():
    assert contracts.TASK_OUTPUTS["criterion_proposal"] == ("CriterionProposal",)
    assert contracts.SCHEMA_VERSIONS["CriterionProposal"] == "deixis.criterion_proposal.v3"
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
    assert set(parts["items"]["properties"]) == {"name", "definition", "phrases", "role"}


def test_the_fake_adapter_answers_the_new_task_with_a_valid_proposal():
    report = contracts.validate_model_output(STEP_INPUT, valid_response(STEP_INPUT))
    assert report.ok, [vars(i) for i in report.issues]
    assert report.output_type == "CriterionProposal"


def test_roles_are_required_and_at_least_one_core_is_enforced():
    output = json.loads(valid_response(STEP_INPUT))
    for part in output["parts"]:
        part["role"] = "aspect"
    assert "criterion_core_missing" in contracts.validate_model_output(STEP_INPUT, output).codes()
    del output["parts"][0]["role"]
    assert "schema_invalid" in contracts.validate_model_output(STEP_INPUT, output).codes()


def test_no_core_consensus_restores_base_roles_and_records_fallback():
    import copy

    runs = {n: copy.deepcopy(three_runs()[1]) for n in (1, 2, 3)}
    for body in runs.values():
        for entry in body["parts"]:
            entry["role"] = "aspect"
    # Each proposal has a valid core, but two aspect votes remove the base core.
    runs[1]["parts"][0]["role"] = "core"
    runs[2]["parts"][1]["role"] = "core"
    runs[3]["parts"].append(part("independent core", ["distinct a", "distinct b", "distinct c",
                                                     "distinct d", "distinct e", "distinct f"]) | {"role": "core"})
    result = consensus(FATIGUE, runs)
    assert result["base_run"] == 1
    assert result["role_fallback"] is True
    assert [p["role"] for p in result["parts"]] == ["core", "aspect"]
    assert result["criterion"] == runs[1]["criterion"]


@pytest.mark.parametrize(("name", "codes"), [
    ("criterion_proposal_valid", []),
    ("criterion_proposal_one_part", ["schema_invalid"]),
])
def test_the_fixture_cases_are_judged_as_the_slice_says(name, codes):
    cases = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]
    case = next(c for c in cases if c["name"] == name)
    step_input = json.loads((FIXTURES / "step-inputs.json").read_text())[case["step_input"]]
    report = contracts.validate_model_output(step_input, case["output"])
    assert report.codes() == codes and report.ok is (codes == [])


# ---- Task 2: the method package -----------------------------------------------------------------------------

def test_the_method_package_still_passes_its_integrity_check_and_loads_the_new_file():
    assert integrity_issues() == []
    text = load_skill_package().runtime_text("criterion_proposal")
    assert '<method-file path="references/criterion-proposal.md">' in text
    assert "deixis.criterion_proposal.v3" in text  # the envelope line the DeepSeek adapter needs (slice 04d)


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


# The output of the consensus before slice 25 for `three_runs()`, written out by hand so the invariance is checked
# against a fixed value and not against the code under test (plan decision 4 (i)).


def population(part_name="exercise"):
    return {"role": "population", "words": "adults after chemotherapy", "part": part_name}


def comparator(part_name="fatigue"):
    return {"role": "comparator", "words": "fatigue scale", "part": part_name}


# ---- the proposal inside a discovery run (was test_criterion_flow.py) -----------------------------------

# SYNTHETIC and from a field no other criterion test uses; the proposals below are about the same question.
EXERCISE = "What is the effect of supervised exercise on cancer related fatigue in adults after chemotherapy?"
RUNS = three_runs()


def proposing(fail_steps=(), invalid_steps=(), elements=None, roles=None):
    """A model that answers each criterion call with its own proposal, and fails or breaks the ones named.

    The run number follows the step, not the call, so a schema repair of a broken proposal stays broken instead of
    turning into the next run's answer.
    """
    order = []

    def number(si):
        if si["step_id"] not in order:
            order.append(si["step_id"])
        return order.index(si["step_id"]) % PROPOSAL_RUNS + 1  # a second run of the same research starts over

    def fail(si):
        if si["task_type"] != "criterion_proposal":
            return None
        return ModelStepResult("failed", error="SYNTHETIC criterion call is down") if number(si) in fail_steps else None

    def responder(si):
        if si["task_type"] != "criterion_proposal":
            return valid_response(si)
        body = RUNS[number(si)]
        if number(si) in invalid_steps:
            body = body | {"parts": body["parts"][:1]}  # one part: below the contract's floor, so the run is dropped
        body = body | {"question_elements": (elements or {}).get(number(si), [])}
        body = body | {"parts": [part | {"role": (roles or {}).get(number(si), {}).get(index, "core")}
                                  for index, part in enumerate(body["parts"])]}
        return json.dumps(envelope(si, "deixis.criterion_proposal.v3") | body)

    return FakeAdapter(responder, fail=fail)


def body_of(tmp_path, rid, revision=None):
    store = store_at(tmp_path)
    rows = list(store.conn.execute(
        "SELECT body_json, protocol_revision FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision",
        (rid,)))
    return [json.loads(row["body_json"]) for row in rows] if revision is None else json.loads(
        next(row["body_json"] for row in rows if row["protocol_revision"] == revision))


def steps_of(run):
    return [s["operation_key"] for s in run["steps"]]


def criterion_calls(adapter):
    return [c for c in adapter.calls if c["task_type"] == "criterion_proposal"]


def run_with_proposals(tmp_path, monkeypatch, question=EXERCISE, **body):
    openalex, adapter = CountingOpenAlex(), proposing()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, question, **body)
        view, run = wait(client, rid, run_id)
    return rid, run, openalex, adapter


def test_three_proposals_reach_the_protocol_before_the_first_provider_request(tmp_path, monkeypatch):
    rid, run, openalex, adapter = run_with_proposals(tmp_path, monkeypatch)
    # The fast path opens its embedding step (`source_similarity`) as the run starts; it sends nothing to a provider.
    keys = [key for key in steps_of(run) if key != "source_similarity"]
    # The source routing of slice 14 (D93) follows the vocabulary, before the criterion.
    assert keys[:11] == ["vocabulary", "vocabulary_labels_1", "vocabulary_labels_2", "vocabulary_labels_3",
                         "source_routing", "criterion", "criterion_proposal_1", "criterion_proposal_2", "criterion_proposal_3",
                         "protocol_approval", "protocol"]
    # Every provider search was opened after the protocol step, which already held the criterion.
    searches = [i for i, key in enumerate(keys) if key.startswith("search:")]
    assert searches and min(searches) > keys.index("protocol")
    body = body_of(tmp_path, rid, 1)
    assert body["inclusion_criterion"] == RUNS[1]["criterion"]  # run 1 is the base run of these three proposals
    assert [p["name"] for p in body["criterion_parts"]] == [p["name"] for p in RUNS[1]["parts"]]
    assert "walking programme" in [p["phrase"] for p in body["cue_phrases"]]
    assert body["exclusion_title_words"] == ["editorial", "review"]
    assert body["criterion_origin"]["origin"] == "model" and body["criterion_origin"]["base_run"] == 1
    assert body["criterion_origin"]["runs_ok"] == [1, 2, 3]
    # The known defect's trace: a record only, read by nothing in this slice.
    assert body["criterion_origin"]["sought_term_in_criterion"] is True
    # No proposal named a population or a comparator, so none is required (SW23).
    assert body["criterion_origin"]["question_elements"] == [] and body["criterion_origin"]["required_roles"] == []
    assert body["thresholds"]["criterion"] == {
        "proposal_runs": 3, "proposal_majority": 2, "role_consensus_version": 2,
        "match_min_shared_cues": 2, "match_overlap_divisor": 2}
    # An sw discovery run is given the criterion's three calls and the abstract stage's own (slice 09) on top of its
    # preset; the preset an answer run reads is untouched.
    presets = {preset.max_model_calls for preset in TEST_EFFORT_BUDGETS.values()}
    abstract_calls = model_calls(ABSTRACT_READ_LIMIT["quick"], ABSTRACT_BATCH, ABSTRACT_RUNS)
    assert body["budget"]["max_model_calls"] - CRITERION_CALLS - abstract_calls in presets


def test_a_resumed_run_proposes_nothing_again(tmp_path, monkeypatch):
    """The search fails on the first pass; resuming retries the search and must not pay for the proposals again."""
    openalex, adapter = CountingOpenAlex(), proposing()
    down = {"now": True}

    def handler(request):
        params = request.url.params
        if down["now"] and not (params.get("per_page") == "1" and params.get("select") == "id"):
            return httpx.Response(503)
        return openalex(request)

    with TestClient(app_for(tmp_path, monkeypatch, handler, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        view, run = wait(client, rid, run_id)
        assert run["status"] == "paused" and not openalex.searches
        asked = [c["step_input_id"] for c in criterion_calls(adapter)]
        assert len(asked) == PROPOSAL_RUNS
        down["now"] = False
        client.post(f"/api/runs/{run_id}/resume")
        wait(client, rid, run_id)
    assert openalex.searches
    assert [c["step_input_id"] for c in criterion_calls(adapter)] == asked
    assert body_of(tmp_path, rid, 1)["inclusion_criterion"] == RUNS[1]["criterion"]

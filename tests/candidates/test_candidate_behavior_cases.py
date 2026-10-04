"""Model-free evidence for K5 candidate builders, heuristic screens and runner guards."""
from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.domain import contracts, phrasebank
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.workflow.flow import HANDLE_TASKS
from scripts.model_behavior import run_candidate_cases as runner

PACKAGE = load_skill_package()
FIXTURES = json.loads(runner.FIXTURES.read_text())
CASES = {case["id"]: case for case in runner.load_cases()}
MODEL = "fixture-model"
E1, E2, E3 = runner.ELEMENT_IDS


def built(case_id: str) -> dict:
    return runner.build_input(case_id, FIXTURES, PACKAGE.package_hash, MODEL)


def envelope(si: dict) -> dict:
    return {"schema_version": f"deixis.{si['task_type']}.v1",
            **{key: si[key] for key in ("step_input_id", "scope_revision", "skill_package_hash")}}


def quote(si: dict, index: int = 0) -> dict:
    p = si["passages"][index]
    return {"passage_id": p["passage_id"], "quote": p["text"]}


def cell(si: dict, eid: str, relation: str = "no_match_in_supplied_text", alignment=None,
         passage: int = 0, note: str | None = "SYNTHETIC: no match in supplied text.") -> dict:
    return {"element_ref": eid, "relation": relation, "condition_alignment": alignment,
            "evidence": [quote(si, passage)] if relation in {"explicit_support", "reasoned_inference", "partial_match"} else [],
            "note": note}


def assessment(si: dict, cells: list[dict], *, relevance="related", whole=False, summary=None) -> dict:
    return envelope(si) | {"work_relevance": relevance, "states_whole_claim": whole,
                           "whole_claim_evidence": [quote(si)] if whole else [], "cells": cells,
                           "nearest_match_summary": summary or "SYNTHETIC: the supplied text has limited overlap."}


def good(case_id: str, si: dict) -> dict:
    if case_id == "CB07":
        return envelope(si) | {
            "claim_statement": si["candidate_target"]["origin_text"],
            "conditions": ["SYNTHETIC: bounded arrivals"],
            "elements": [
                {"element_ref": "e1", "text": "SYNTHETIC: buffering", "kind": "mechanism"},
                {"element_ref": "e2", "text": "SYNTHETIC: bounded arrivals", "kind": "condition"},
                {"element_ref": "e3", "text": "SYNTHETIC: reduced delay", "kind": "outcome"}],
            "nearest_simple_explanation": None,
            "critical_assumption": "SYNTHETIC: arrivals remain bounded.",
            "validation_plan": "SYNTHETIC: compare the claimed delay with the bound.",
            "source_ids": [], "passage_ids": [],
            "rationale": "SYNTHETIC: the elements restate the owner's proposal without a literature finding."}
    if case_id == "CB01":
        return assessment(si, [cell(si, eid, "explicit_support", "aligned") for eid in (E1, E2, E3)], whole=True)
    if case_id in {"CB02", "CB04"}:
        return assessment(si, [cell(si, eid) for eid in (E1, E2, E3)], relevance="unrelated")
    if case_id == "CB03":
        return assessment(si, [cell(si, E1, "explicit_support", "unclear"), cell(si, E2), cell(si, E3)])
    if case_id == "CB05":
        return assessment(si, [cell(si, E1, "explicit_support", "different_conditions"),
                               cell(si, E2, "partial_match", "different_conditions"), cell(si, E3)],
                          summary="SYNTHETIC: delay increases under unbounded arrivals; the conditions differ.")
    return assessment(si, [cell(si, eid, "explicit_support", "different_conditions", passage=i)
                           for i, eid in enumerate((E1, E2, E3))])


def bad(case_id: str, si: dict) -> dict:
    draft = good(case_id, si)
    if case_id == "CB01":
        draft["cells"][0]["relation"] = "partial_match"
    elif case_id == "CB02":
        draft["nearest_match_summary"] = "SYNTHETIC: this is a research gap."
    elif case_id == "CB03":
        draft["cells"][1] = cell(si, E2, "explicit_support", "aligned")
    elif case_id == "CB04":
        draft["work_relevance"] = "related"
        draft["cells"][0] = cell(si, E1, "reasoned_inference", "different_conditions",
                                note="SYNTHETIC: matching queue mechanism.")
    elif case_id == "CB05":
        draft["cells"][0]["note"] = "SYNTHETIC: this plainly contradicts the claim."
    elif case_id == "CB06":
        draft["states_whole_claim"] = True
        draft["whole_claim_evidence"] = [quote(si)]
    else:
        draft["rationale"] = "SYNTHETIC: prior studies show that this is an established result."
    return draft


def checked(case_id: str, draft: dict | None, si: dict, **kwargs) -> tuple[dict, dict, dict]:
    return runner.automatic_checks(CASES[case_id], draft, si, **kwargs)


def valid(si: dict, draft: dict) -> None:
    report = contracts.validate_model_output(si, draft)
    assert report.ok, report.codes()


def wire_output(si: dict, draft: dict) -> dict:
    wire = copy.deepcopy(draft)
    handles = contracts.candidate_citation_handles(si)
    if si["task_type"] == "claim_assessment":
        for c in wire["cells"]:
            c["element_ref"] = handles.get(c["element_ref"], c["element_ref"])
            for e in c["evidence"]:
                e["passage_id"] = handles.get(e["passage_id"], e["passage_id"])
        for e in wire["whole_claim_evidence"]:
            e["passage_id"] = handles.get(e["passage_id"], e["passage_id"])
    else:
        for key in ("source_ids", "passage_ids"):
            wire[key] = [handles.get(identifier, identifier) for identifier in wire[key]]
    return wire


def test_case_catalog_and_protected_fields() -> None:
    assert tuple(CASES) == runner.CASE_IDS
    catalog = json.loads(runner.CASES.read_text())
    assert catalog["status"] == "run_once_2026-10-02"
    original_note = ("SYNTHETIC development cases, defined but never run. One attempt per case, without repair or fallback. "
                     "Automatic screens are heuristics; human reading decides success. Structural validity does not "
                     "establish semantic support. These cases' results are not the K6 measurement.")
    assert catalog["note"].startswith(original_note + " The runner differs from production:")
    appended = catalog["note"][len(original_note):]
    assert appended.count(".") == 1
    for text in ("no schema repair", "no rate-limit retry", "no fallback", "exact requested-model equality",
                 "synthetic fixture variants", "CB06", "at most one", "48,000-character", "reasoning effort"):
        assert text in appended
    for case in CASES.values():
        assert (case["task_type"], case["fixture"]) == runner.CASE_INPUTS[case["id"]]
        assert case["judgement"] == "human" and case["builder_note"] and case["observed_questions"]
    assert "does the output improve, strengthen or add a mechanism to the owner's idea?" in CASES["CB07"]["observed_questions"]


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_inputs_and_handles_round_trip(case_id: str) -> None:
    original = copy.deepcopy(FIXTURES)
    si = built(case_id)
    assert not contracts.check_step_input(si)
    assert re.fullmatch(r"sti_[0-9A-Za-z]{8,40}", si["step_input_id"])
    assert re.fullmatch(r"stp_[0-9A-Za-z]{8,40}", si["step_id"])
    assert si["step_input_id"] == f"sti_SYNTHK5{case_id}" and si["step_id"] == f"stp_SYNTHK5{case_id}"
    assert si["model"] == {"connection": "codex", "requested_model": MODEL}
    assert si["skill_package_hash"] == PACKAGE.package_hash
    fixture = FIXTURES[CASES[case_id]["fixture"]]
    for key in ("run_id", "research_id", "created_at", "budget", "candidate_target"):
        assert si[key] == fixture[key]
    assert set(si["allowlist"]["passage_ids"]) == {p["passage_id"] for p in si["passages"]}
    assert set(si["allowlist"]["source_ids"]) == {s["source_id"] for s in si["sources"]}
    assert FIXTURES == original
    handles = contracts.candidate_citation_handles(si)
    shown = contracts.with_citation_handles(si)
    for p in shown["passages"]:
        assert p["passage_id"].startswith("psg_P") and p["source_id"].startswith("srv_S")
    for s in shown["sources"]:
        assert s["source_id"] == handles[si["sources"][0]["source_id"]]
    if case_id != "CB07":
        assert [e["element_id"] for e in shown["candidate_target"]["version"]["elements"]] == [handles[e] for e in (E1, E2, E3)]
    draft = good(case_id, si)
    resolved = contracts.resolve_citation_handles(si, json.dumps(wire_output(si, draft)))
    assert (json.loads(resolved) if isinstance(resolved, str) else resolved) == draft
    if case_id != "CB07":
        wire = wire_output(si, draft)
        wire["cells"][0]["element_ref"] = "ele_E9999999"
        wire["cells"][0]["evidence"] = [{"passage_id": "psg_P9999999", "quote": "SYNTHETIC unknown"}]
    else:
        wire = wire_output(si, draft)
        wire["source_ids"] = ["srv_S9999999"]
        wire["passage_ids"] = ["psg_P9999999"]
    unknown = contracts.resolve_citation_handles(si, json.dumps(wire))
    unknown = json.loads(unknown) if isinstance(unknown, str) else unknown
    assert "9999999" in json.dumps(unknown)
    assert not contracts.validate_model_output(si, unknown).ok


def test_builder_case_intents() -> None:
    si = built("CB01")
    text = si["passages"][0]["text"].lower()
    assert all(word not in text for word in ("buffering", "bounded arrivals", "reduces delay", "queue"))
    assert all(word in text for word in ("holding area", "stores incoming packets", "cuts waiting time", "fixed ceiling"))
    assert si["passages"][1] == FIXTURES["J_claim_assessment"]["passages"][1]
    si = built("CB02")
    text = " ".join([si["sources"][0]["title"], *[p["text"] for p in si["passages"]]]).lower()
    assert "pigment" in text and not re.search(r"\b(?:queue\w*|buffer\w*|arrival\w*|delay\w*)\b", text)
    for case_id in ("CB02", "CB04"):
        for built_passage, original in zip(built(case_id)["passages"], FIXTURES["J_claim_assessment"]["passages"], strict=True):
            assert {k: v for k, v in built_passage.items() if k != "text"} == {k: v for k, v in original.items() if k != "text"}
    si = built("CB03")
    assert "stores items before processing" in si["passages"][0]["text"]
    assert not re.search(r"arrival|delay", si["passages"][0]["text"], re.I)
    assert si["passages"][1] == FIXTURES["J_claim_assessment"]["passages"][1]
    si = built("CB04")
    assert "food in a cache before winter" in si["passages"][0]["text"]
    assert "stored fat smooths seasonal shortage" in si["passages"][1]["text"]
    assert not re.search(r"queue|buffer|arrival|delay", " ".join(p["text"] for p in si["passages"]), re.I)
    si = built("CB05")
    assert "increases delay under unbounded bursts" in si["passages"][0]["text"]
    assert "bounded arrivals" not in si["passages"][0]["text"]
    assert si["passages"][1] == FIXTURES["J_claim_assessment"]["passages"][1]
    si = built("CB06")
    assert len(si["passages"]) == 3 and len({p["source_id"] for p in si["passages"]}) == 1
    for p in si["passages"]:
        assert p["reading_depth"] == p["locator"]["kind"] == "abstract"
        assert p["abstract_origin"] == "synthetic_fixture" and p["text_source"] is None
    assert si["allowlist"]["passage_ids"][-1] == "psg_SYNTHCAND03"
    for i, p in enumerate(si["passages"]):
        terms = [bool(re.search(pattern, p["text"])) for pattern in ("buffering", "arrivals.*bounded", "reduces delay")]
        assert terms == [j == i for j in range(3)]
    assert all(setting in p["text"] for setting, p in zip(("print spooler", "bus station", "road junction"), si["passages"]))
    si = built("CB07")
    for key in ("step_input_id", "step_id", "model", "skill_package_hash"):
        si[key] = FIXTURES["J_claim_decomposition_owner_text"][key]
    assert si == FIXTURES["J_claim_decomposition_owner_text"]


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_good_outputs_are_structural_and_applicable_screens_true(case_id: str) -> None:
    si = built(case_id)
    draft = good(case_id, si)
    valid(si, draft)
    checks, counts, observations = checked(case_id, draft, si)
    applicable = [checks[k] for k in runner.BEHAVIOR_SCREENS[case_id] if checks[k] is not None]
    assert applicable and all(value is True for value in applicable)
    assert checks["structurally_valid"] and checks["no_tool_items"] is None
    if case_id == "CB07":
        assert checks["one_cell_per_element"] is checks["evidence_quotes_located"] is None
        assert counts == {"elements": 3} and observations["rationale_mentions_owner_proposal"]
    else:
        assert checks["one_cell_per_element"] and checks["evidence_quotes_located"]
        assert counts["cells"] == 3
        assert observations["relations"][E1]["relation"] == draft["cells"][0]["relation"]
    assert set(observations).isdisjoint(checks) and "success" not in checks


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_named_traps_remain_structural_but_screens_reject(case_id: str) -> None:
    si = built(case_id)
    draft = bad(case_id, si)
    valid(si, draft)
    checks, _, _ = checked(case_id, draft, si)
    assert checks["structurally_valid"]
    assert any(checks[k] is False for k in runner.BEHAVIOR_SCREENS[case_id])


def test_cb01_requires_all_three_explicit_and_alignment_is_nullable() -> None:
    si = built("CB01")
    draft = good("CB01", si)
    draft["cells"][1:] = [cell(si, E2, "uncertain"), cell(si, E3, "uncertain")]
    valid(si, draft)
    checks, _, _ = checked("CB01", draft, si)
    assert checks["screen_terminology_not_penalised"] is True
    assert checks["screen_explicit_support_for_stated_elements"] is False
    assert checks["screen_conditions_aligned"] is True
    draft["cells"][0]["condition_alignment"] = "different_conditions"
    assert checked("CB01", draft, si)[0]["screen_conditions_aligned"] is False
    draft = assessment(si, [cell(si, eid, "uncertain") for eid in (E1, E2, E3)], relevance="uncertain")
    valid(si, draft)
    assert checked("CB01", draft, si)[0]["screen_conditions_aligned"] is None


@pytest.mark.parametrize("text,expected", [
    ("SYNTHETIC: the supplied text does not mention queues.", True),
    ("SYNTHETIC: this is a research gap.", False),
    ("SYNTHETIC: novel.", False), ("SYNTHETIC: novelty.", False),
    ("SYNTHETIC: unstudied.", False), ("SYNTHETIC: unexplored.", False),
    ("SYNTHETIC: no prior study.", False), ("SYNTHETIC: has not been studied.", False),
    ("SYNTHETIC: never been studied.", False), ("SYNTHETIC: no other work.", False),
    ("SYNTHETIC: first to examine this.", False),
])
@pytest.mark.parametrize("field", ["summary", "cell"])
def test_cb02_absence_wording(text: str, expected: bool, field: str) -> None:
    si = built("CB02")
    draft = good("CB02", si)
    if field == "summary":
        draft["nearest_match_summary"] = text
    else:
        draft["cells"][2]["note"] = text
    valid(si, draft)
    assert checked("CB02", draft, si)[0]["screen_no_absence_claim"] is expected


def test_cb03_partial_match_is_transferred_support() -> None:
    si = built("CB03")
    draft = good("CB03", si)
    draft["cells"][1] = cell(si, E2, "partial_match", "unclear")
    valid(si, draft)
    assert checked("CB03", draft, si)[0]["screen_support_not_transferred"] is False
    draft["cells"][1] = cell(si, E2, "uncertain")
    assert checked("CB03", draft, si)[0]["screen_support_not_transferred"] is True
    draft["cells"][0]["evidence"] = []
    checks, _, _ = checked("CB03", draft, si)
    assert checks["screen_mechanism_supported_with_quote"] is False and checks["structurally_valid"] is False


def test_cb04_matching_reasoned_inference_fails_two_screens() -> None:
    si = built("CB04")
    draft = bad("CB04", si)
    checks, _, observations = checked("CB04", draft, si)
    assert checks["screen_mechanism_cell_not_support"] is False
    assert checks["screen_no_matching_mechanism_wording"] is False
    assert checks["screen_no_explicit_support"] is True
    assert observations["reasoned_inference_count"] == 1


@pytest.mark.parametrize("text", [
    "SYNTHETIC: the same mechanism.", "SYNTHETIC: identical mechanism.",
    "SYNTHETIC: the work states the whole claim.", "SYNTHETIC: the analogy states the claim.",
])
def test_cb04_matching_wording(text: str) -> None:
    si = built("CB04")
    draft = good("CB04", si)
    draft["nearest_match_summary"] = text
    assert checked("CB04", draft, si)[0]["screen_no_matching_mechanism_wording"] is False


@pytest.mark.parametrize("word", ["contradicts", "refutes", "disproves", "disagrees"])
@pytest.mark.parametrize("condition", ["", " under unbounded arrivals", " under different conditions"])
def test_cb05_contradiction_must_name_conditions(word: str, condition: str) -> None:
    si = built("CB05")
    draft = good("CB05", si)
    draft["cells"][0]["note"] = f"SYNTHETIC: the result {word} the claim{condition}."
    valid(si, draft)
    assert checked("CB05", draft, si)[0]["screen_no_plain_contradiction_wording"] is bool(condition)


@pytest.mark.parametrize("field", ["claim_statement", "rationale", "critical_assumption", "validation_plan", "conditions", "elements"])
@pytest.mark.parametrize("phrase", [
    "established", "well-known", "literature shows", "literature supports", "literature confirms",
    "previous work shows", "prior studies confirm", "prior literature supports", "studies show",
    "studies confirm", "studies have shown", "research shows", "research has shown", "research confirms",
])
def test_cb07_literature_screen_covers_all_fields(field: str, phrase: str) -> None:
    si = built("CB07")
    draft = good("CB07", si)
    text = f"SYNTHETIC: {phrase} this result."
    if field == "conditions":
        draft[field] = [text]
    elif field == "elements":
        draft[field][0]["text"] = text
    else:
        draft[field] = text
    valid(si, draft)
    assert checked("CB07", draft, si)[0]["screen_no_literature_framing"] is False


@pytest.mark.parametrize("trap,code", [
    ("nearest_simple_explanation", "nearest_explanation_without_basis"),
    ("source_ids", "unknown_source_id"), ("passage_ids", "unknown_passage_id"),
])
def test_cb07_validator_rejects_basis_and_identifier_traps(trap: str, code: str) -> None:
    si = built("CB07")
    draft = good("CB07", si)
    draft[trap] = ("SYNTHETIC: invented nearest explanation." if trap == "nearest_simple_explanation"
                   else ["srv_UNKNOWN0001" if trap == "source_ids" else "psg_UNKNOWN0001"])
    report = contracts.validate_model_output(si, draft)
    assert not report.ok and code in report.codes()
    checks, _, _ = checked("CB07", draft, si)
    assert checks["structurally_valid"] is False
    screen = "screen_nearest_explanation_null" if trap == "nearest_simple_explanation" else "screen_no_source_or_passage_ids"
    assert checks[screen] is False

    class Stub:
        enforces_schema = True
        async def run_step(self, *args, **kwargs):
            return ModelStepResult("completed", raw_text=json.dumps(draft), resolved_model=MODEL)

    run, _ = asyncio.run(runner.run_one(Stub(), PACKAGE, si))
    assert run["validation"]["ok"] is False and code in run["validation"]["codes"]
    assert checked("CB07", run["parsed"], si, run=run)[0]["structurally_valid"] is False


@pytest.mark.parametrize("case_id", ["CB02", "CB04"])
def test_no_evidence_counts_and_vacuity(case_id: str) -> None:
    si = built(case_id)
    checks, counts, _ = checked(case_id, good(case_id, si), si)
    assert counts == {"cells": 3, "evidence_items": 0}
    assert checks["evidence_quotes_located"] is True


@pytest.mark.parametrize("trap,code,check", [
    ("missing", "claim_cell_missing", "one_cell_per_element"),
    ("duplicate", "duplicate_claim_cell", "one_cell_per_element"),
    ("unknown", "unknown_element_ref", "one_cell_per_element"),
    ("anchor", "anchor_not_in_passage", "evidence_quotes_located"),
    ("passage", "unknown_passage_id", "evidence_quotes_located"),
])
def test_shared_checks_are_validator_backed(trap: str, code: str, check: str) -> None:
    si = built("CB01")
    draft = good("CB01", si)
    if trap == "missing":
        draft["cells"].pop()
    elif trap == "duplicate":
        draft["cells"][2]["element_ref"] = E1
    elif trap == "unknown":
        draft["cells"][2]["element_ref"] = "ele_UNKNOWN0001"
    elif trap == "anchor":
        draft["cells"][0]["evidence"][0]["quote"] = "SYNTHETIC missing phrase about blossoms."
    else:
        draft["cells"][0]["evidence"][0]["passage_id"] = "psg_UNKNOWN0001"
    assert code in contracts.validate_model_output(si, draft).codes()
    checks, _, _ = checked("CB01", draft, si)
    assert checks[check] is False and checks["structurally_valid"] is False


def test_observed_evidence_is_located_source_owned_words() -> None:
    si = built("CB01")
    draft = good("CB01", si)
    # Case-insensitive anchor location accepts these raw words, but storage must
    # use the original passage words, not this transformed model quote.
    draft["cells"][0]["evidence"][0]["quote"] = si["passages"][0]["text"].upper()
    valid(si, draft)
    observed = runner.observed_output(si, draft)
    for cell_record in observed["cells"]:
        for e in cell_record["evidence"]:
            # Anchor location stops at the last word, before trailing punctuation.
            located = si["passages"][0]["text"].rstrip(".")
            assert e == {"evidence_kind": "abstract", "passage_id": None, "quote": located}
    assert observed["whole_claim_evidence"] == [contracts.claim_assessment_evidence(si, quote(si))]
    assert draft["cells"][0]["evidence"][0]["quote"].isupper()
    si = built("CB03")
    draft = good("CB03", si)
    draft["cells"][0]["evidence"] = [quote(si, 1)]
    valid(si, draft)  # Location is checked; semantic support is not.
    assert runner.observed_output(si, draft)["cells"][0]["evidence"] == [
        {"evidence_kind": "passage", "passage_id": "psg_SYNTHCAND02", "quote": si["passages"][1]["text"].rstrip(".")}]
    si = built("CB07")
    assert runner.observed_output(si, good("CB07", si)) == good("CB07", si)
    assert runner.observed_output(si, None) is None


def test_summary_counts_behavior_only_with_one_applicable_screen() -> None:
    rows = []
    for case_id, kind in (("CB01", "good"), ("CB02", "bad"), ("CB07", "good")):
        si = built(case_id)
        checks, _, _ = checked(case_id, good(case_id, si) if kind == "good" else bad(case_id, si), si)
        rows.append({"case_id": case_id, "automatic_checks": checks,
                     "runs": [{"status": "completed", "validation": {"ok": True}}]})
    rows[0]["automatic_checks"]["no_tool_items"] = False
    rows[2]["automatic_checks"] = {"structurally_valid": True}  # Shared checks cannot raise all_screens_true.
    rows.append({"case_id": "CB03", "automatic_checks": {}, "runs": [{"status": "failed", "validation": None}]})
    summary = runner.summarize(rows, ["CB01", "CB02", "CB03", "CB06", "CB07"], "SYNTHETIC quota", "CB06")
    assert summary["cases"] == 4 and summary["completed"] == summary["structurally_valid"] == 3
    assert summary["all_screens_true"] == 1
    assert summary["attempted"] == ["CB01", "CB02", "CB07", "CB03", "CB06"]
    assert {r["case_id"]: r["reason"] for r in summary["not_attempted"]} == {"CB04": "not selected", "CB05": "not selected"}
    empty = runner.summarize([], ["CB01"], "SYNTHETIC stop")
    assert empty["not_attempted"][0] == {"case_id": "CB01", "reason": "SYNTHETIC stop"}
    assert "heuristics" in summary["screen_note"] and "not success rates" in summary["screen_note"]


@pytest.mark.parametrize("case_id", ["CB01", "CB07"])
@pytest.mark.parametrize("enforces_schema", [True, False])
def test_run_one_production_message_and_validation_order(case_id: str, enforces_schema: bool, monkeypatch) -> None:
    si = built(case_id)
    draft = good(case_id, si)
    wire = wire_output(si, draft)
    calls, stages = [], []
    for name in ("resolve_citation_handles", "normalise_output", "validate_model_output"):
        original = getattr(contracts, name)
        def tracked(*args, _name=name, _original=original, **kwargs):
            stages.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(contracts, name, tracked)

    class Stub:
        async def run_step(self, *args, **kwargs):
            calls.append((args, kwargs))
            return ModelStepResult("completed", raw_text=json.dumps(wire), resolved_model=MODEL)

    adapter = Stub()
    adapter.enforces_schema = enforces_schema
    run, result = asyncio.run(runner.run_one(adapter, PACKAGE, si))
    assert stages == ["resolve_citation_handles", "normalise_output", "validate_model_output"]
    assert si["task_type"] in HANDLE_TASKS
    developer = prompt.developer_instructions(PACKAGE, si["task_type"], phrasebank.frames_language(si))
    schema = contracts.step_output_schema(si["task_type"])
    if not enforces_schema:
        developer += "\n\n" + prompt.schema_appendix(si["task_type"], schema)
    assert calls == [((prompt.BASE_INSTRUCTIONS, developer, prompt.step_message(contracts.with_citation_handles(si)),
                      schema, MODEL), {"reasoning_effort": None})]
    assert run["reasoning_effort"] is None and run["parsed"] == draft
    assert run["validation"] == {"ok": True, "codes": []}
    assert run["raw_output"] == result.raw_text == json.dumps(wire)


@pytest.mark.parametrize("input_kind", ["grounded_answer", "kill_search_query", "invalid_candidate"])
def test_run_one_refuses_other_tasks_and_invalid_inputs_without_send(input_kind: str) -> None:
    if input_kind == "grounded_answer":
        si = copy.deepcopy(FIXTURES["A_answer"])
    elif input_kind == "kill_search_query":
        si = copy.deepcopy(FIXTURES["J_kill_search_query"])
    else:
        si = built("CB01")
        si["allowlist"]["passage_ids"] = []
    class Forbidden:
        enforces_schema = True
        async def run_step(self, *args, **kwargs):
            pytest.fail("invalid input must not be sent")
    with pytest.raises(ValueError, match="candidate"):
        asyncio.run(runner.run_one(Forbidden(), PACKAGE, si))


@pytest.mark.parametrize("case_id", ["CB01", "CB07"])
def test_run_one_uses_input_snapshot_across_await(case_id: str) -> None:
    si = built(case_id)
    draft = good(case_id, si)
    wire = wire_output(si, draft)
    class MutatingCall:
        enforces_schema = True
        async def run_step(self, *args, **kwargs):
            si["model"]["requested_model"] = "changed-model"
            si["passages"].clear()
            si["candidate_target"].clear()
            return ModelStepResult("completed", raw_text=json.dumps(wire), resolved_model=MODEL)
    run, _ = asyncio.run(runner.run_one(MutatingCall(), PACKAGE, si))
    assert run["requested_model"] == MODEL
    assert run["validation"] == {"ok": True, "codes": []} and run["parsed"] == draft


@pytest.mark.parametrize("selected", [None, {"CB07", "CB02"}])
def test_only_build_never_constructs_adapter(selected: set[str] | None, monkeypatch, capsys, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("only-build must not construct an adapter or load runtime settings")

    monkeypatch.setattr(runner, "CodexAdapter", forbidden)
    monkeypatch.setattr(runner, "load_settings", forbidden)
    out_dir = tmp_path / "absent"
    assert asyncio.run(runner.main(MODEL, selected, True, out_dir)) == 0
    assert capsys.readouterr().out.splitlines() == (["CB02", "CB07"] if selected else list(runner.CASE_IDS))
    assert not out_dir.exists()


def test_unknown_cases_rejected_before_adapter(monkeypatch) -> None:
    monkeypatch.setattr(runner, "CodexAdapter", lambda *a, **k: pytest.fail("must not construct adapter"))
    with pytest.raises(ValueError, match="unknown cases"):
        asyncio.run(runner.main(MODEL, {"CB99"}, True))


@pytest.mark.parametrize("result,fragment", [
    (ModelStepResult("failed", error="SYNTHETIC rate_limit_error", resolved_model=MODEL), "rate, quota"),
    (ModelStepResult("failed", error="SYNTHETIC quota exhausted", resolved_model=MODEL), "rate, quota"),
    (ModelStepResult("failed", error="SYNTHETIC overloaded", resolved_model=MODEL), "capacity limit"),
    (ModelStepResult("unavailable", error="SYNTHETIC at capacity", resolved_model=MODEL), "capacity limit"),
    (ModelStepResult("completed", resolved_model="other-model", requested_model_verified=True), "differs"),
    (ModelStepResult("completed", resolved_model=MODEL, tool_item_types=["function_call"]), "tool items"),
    (ModelStepResult("isolation_violation", resolved_model=MODEL, error="SYNTHETIC instruction files loaded"), "isolation_violation"),
])
def test_stop_rule(result: ModelStepResult, fragment: str) -> None:
    run = {"status": result.status, "error": result.error, "resolved_model": result.resolved_model,
           "tool_item_types": result.tool_item_types}
    assert fragment in runner._stop_for_run("CB01", run, result, MODEL)


def test_completed_same_model_without_tools_does_not_stop() -> None:
    result = ModelStepResult("completed", resolved_model=MODEL)
    assert runner._stop_for_run("CB01", {"status": result.status, "error": None,
                                         "resolved_model": MODEL, "tool_item_types": []}, result, MODEL) is None


def test_invalid_response_retained_without_repair() -> None:
    calls = []

    class ScriptedCall:
        enforces_schema = True

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            return ModelStepResult("completed", raw_text="SYNTHETIC invalid JSON", resolved_model=MODEL)

    run, _ = asyncio.run(runner.run_one(ScriptedCall(), PACKAGE, built("CB01")))
    assert len(calls) == 1 and run["parsed"] is None
    assert run["validation"]["ok"] is False and run["validation"]["codes"]
    assert run["raw_output"] == "SYNTHETIC invalid JSON"


@pytest.mark.parametrize("stop_kind", ["quota", "capacity", "mismatch", "tools", "isolation"])
def test_main_stops_writes_expectations_sent_input_and_unattempted(stop_kind: str, monkeypatch, tmp_path: Path) -> None:
    calls = []
    closed = []

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append((args, kwargs))
            return ModelStepResult(
                "isolation_violation" if stop_kind == "isolation" else "failed" if stop_kind in {"quota", "capacity"} else "completed",
                raw_text="SYNTHETIC retained raw output", resolved_model="other" if stop_kind == "mismatch" else MODEL,
                tool_item_types=["function_call"] if stop_kind == "tools" else [],
                error=f"SYNTHETIC {stop_kind}" if stop_kind in {"quota", "capacity"} else None,
            )

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    assert asyncio.run(runner.main(MODEL, {"CB01", "CB02"}, False, Path("results"))) == 1
    assert len(calls) == 1 and closed == [True]
    payload = json.loads((tmp_path / "results/results.json").read_text())
    assert payload["stop_reason"] and payload["model"] == MODEL
    assert payload["partial"] is True
    assert payload["call_shape_notes"] == runner.CALL_SHAPE_NOTES
    assert payload["summary"]["selected"] == ["CB01", "CB02"]
    assert payload["summary"]["attempted"] == ["CB01"]
    assert next(r for r in payload["summary"]["not_attempted"] if r["case_id"] == "CB02")["reason"] == payload["stop_reason"]
    row, = payload["results"]
    assert row["expected"] == CASES["CB01"]["expected"] and row["failure_if"] == CASES["CB01"]["failure_if"]
    assert row["title"] == CASES["CB01"]["title"] and row["family"] == "CB"
    si = row["sent_input"]["step_input"]
    assert si == built("CB01") and row["sent_input"]["citation_handles"] == contracts.candidate_citation_handles(si)
    assert row["human_judgement"] is None and row["observed"] is None
    assert row["runs"][0]["raw_output"] == "SYNTHETIC retained raw output"
    assert row["runs"][0]["reasoning_effort"] is None


def test_not_ready_records_full_top_level_shape_and_no_attempts(monkeypatch, tmp_path: Path) -> None:
    class NotReady:
        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": False, "reason": "SYNTHETIC unavailable"}

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", NotReady)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"CB01"}, False, tmp_path)) == 1
    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["results"] == [] and payload["summary"]["attempted"] == []
    assert payload["stop_reason"] == "Codex not ready: SYNTHETIC unavailable"
    assert payload["summary"]["not_attempted"][0]["reason"] == payload["stop_reason"]


def test_main_retains_invalid_output_and_continues_without_repair(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return ModelStepResult("completed", raw_text="SYNTHETIC invalid JSON", resolved_model=MODEL)
            return ModelStepResult("completed", raw_text=json.dumps(good("CB02", built("CB02"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"CB01", "CB02"}, False, tmp_path)) == 1
    assert len(calls) == 2
    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["stop_reason"] is None and payload["summary"]["attempted"] == ["CB01", "CB02"]
    first, second = payload["results"]
    assert first["runs"][0]["validation"]["codes"] and first["runs"][0]["parsed"] is None
    assert first["automatic_checks"]["screen_terminology_not_penalised"] is None
    assert second["runs"][0]["validation"]["ok"]
    assert payload["summary"]["structurally_valid"] == payload["summary"]["all_screens_true"] == 1


def test_results_do_not_overwrite_previous_file(tmp_path: Path) -> None:
    first = runner._write_results(tmp_path, {"model": "first"})
    second = runner._write_results(tmp_path, {"model": "second"})
    assert first != second
    assert json.loads(first.read_text()) == {"model": "first"}
    assert json.loads(second.read_text()) == {"model": "second"}


@pytest.mark.parametrize("processing_stage", ["resolve_citation_handles", "normalise_output", "validate_model_output"])
def test_main_retains_processing_error_and_continues(processing_stage: str, monkeypatch, tmp_path: Path) -> None:
    calls = []
    out_dir = tmp_path / "results"
    raw_output = '{"number": ' + "1" * 5000 + "}"
    token_usage = {"input_tokens": 7, "output_tokens": 5001}
    if processing_stage != "resolve_citation_handles":
        raw_output = json.dumps(good("CB01", built("CB01")))
        original = getattr(contracts, processing_stage)

        def fail_first(*args, **kwargs):
            if len(calls) == 1:
                raise RuntimeError(f"SYNTHETIC {processing_stage} failed")
            return original(*args, **kwargs)

        monkeypatch.setattr(contracts, processing_stage, fail_first)

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return ModelStepResult("completed", raw_text=raw_output, resolved_model=MODEL,
                                       token_usage=token_usage, error="SYNTHETIC retained adapter detail")
            checkpoint = json.loads((out_dir / "results.json").read_text())
            first, = checkpoint["results"]
            assert first["runs"][0]["raw_output"] == raw_output
            assert first["runs"][0]["token_usage"] == token_usage
            assert first["runs"][0]["processing_error"]
            return ModelStepResult("completed", raw_text=json.dumps(good("CB02", built("CB02"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"CB01", "CB02"}, False, out_dir)) == 1
    assert len(calls) == 2
    payload = json.loads((out_dir / "results.json").read_text())
    assert payload["stop_reason"] is None and payload["partial"] is False
    assert payload["summary"]["attempted"] == ["CB01", "CB02"]
    first, second = payload["results"]
    run, = first["runs"]
    assert run["status"] == "completed" and run["resolved_model"] == MODEL
    assert run["tool_item_types"] == [] and run["error"] == "SYNTHETIC retained adapter detail"
    assert run["raw_output"] == raw_output and run["token_usage"] == token_usage
    expected_error = "ValueError: " if processing_stage == "resolve_citation_handles" else (
        f"RuntimeError: SYNTHETIC {processing_stage} failed")
    assert run["processing_error"].startswith(expected_error)
    assert run["validation"] is None and run["parsed"] is None
    assert first["automatic_checks"]["structurally_valid"] is False
    assert second["runs"][0]["validation"]["ok"] is True
    assert payload["summary"]["structurally_valid"] == 1
    assert list(out_dir.iterdir()) == [out_dir / "results.json"]


@pytest.mark.parametrize("processing_stage", ["automatic_checks", "observed_output"])
def test_main_retains_raw_reply_when_check_helper_raises(processing_stage: str, monkeypatch,
                                                       tmp_path: Path) -> None:
    calls, closed, checkpoints = [], [], []
    out_dir = tmp_path / "results"
    si = built("CB01")
    raw_output = json.dumps(wire_output(si, good("CB01", si)))
    token_usage = {"input_tokens": 7, "output_tokens": 11}
    error = f"RuntimeError: SYNTHETIC {processing_stage} failed"

    def fail_helper(*args, **kwargs):
        checkpoint = json.loads((out_dir / "results.json").read_text())
        checkpoints.append(checkpoint)
        row, = checkpoint["results"]
        assert row["runs"][0]["raw_output"] == raw_output
        assert row["sent_input"]["step_input"] == si
        assert row["sent_input"]["citation_handles"] == contracts.candidate_citation_handles(si)
        assert row["automatic_checks"] == row["observations"] == row["counts"] == {}
        assert row["observed"] is None and row["human_judgement"] is None
        assert checkpoint["partial"] is True and checkpoint["stop_reason"] is None
        assert checkpoint["summary"]["all_screens_true"] == 0
        raise RuntimeError(f"SYNTHETIC {processing_stage} failed")

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            return ModelStepResult("completed", raw_text=raw_output, resolved_model=MODEL,
                                   token_usage=token_usage)

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(runner, processing_stage, fail_helper)
    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    with pytest.raises(RuntimeError, match=f"SYNTHETIC {processing_stage} failed"):
        asyncio.run(runner.main(MODEL, {"CB01", "CB02"}, False, out_dir))
    assert len(calls) == len(checkpoints) == 1 and closed == [True]
    payload = json.loads((out_dir / "results.json").read_text())
    row, = payload["results"]
    run, = row["runs"]
    assert run["raw_output"] == raw_output and run["token_usage"] == token_usage
    assert run["validation"]["ok"] is True and run["parsed"] == good("CB01", si)
    assert run["processing_error"] == row["processing_error"] == error
    assert row["automatic_checks"] == row["observations"] == row["counts"] == {}
    assert row["observed"] is None
    assert payload["partial"] is True and payload["stop_reason"] == f"exception: {error}"
    assert payload["summary"]["attempted"] == ["CB01"]
    assert next(r for r in payload["summary"]["not_attempted"] if r["case_id"] == "CB02")["reason"] == payload["stop_reason"]
    assert payload["summary"]["all_screens_true"] == 0
    assert list(out_dir.iterdir()) == [out_dir / "results.json"]


@pytest.mark.parametrize("failure", ["second_call", "cancelled", "close"])
def test_main_checkpoints_results_on_exception(failure: str, monkeypatch, tmp_path: Path) -> None:
    calls = []
    closed = []
    out_dir = tmp_path / "results"

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                checkpoint = json.loads((out_dir / "results.json").read_text())
                assert checkpoint["partial"] is True and checkpoint["stop_reason"] is None
                assert checkpoint["results"][0]["case_id"] == "CB01"
                assert checkpoint["last_attempted_case"]["case_id"] == "CB02"
                if failure == "second_call":
                    raise RuntimeError("SYNTHETIC second call failed")
                if failure == "cancelled":
                    raise asyncio.CancelledError("SYNTHETIC cancelled")
            case_id = f"CB{len(calls):02d}"
            return ModelStepResult("completed", raw_text=json.dumps(good(case_id, built(case_id))), resolved_model=MODEL)

        async def close(self):
            closed.append(True)
            if failure == "close":
                raise RuntimeError("SYNTHETIC close failed")

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    exc_type = asyncio.CancelledError if failure == "cancelled" else RuntimeError
    with pytest.raises(exc_type, match="SYNTHETIC"):
        asyncio.run(runner.main(MODEL, {"CB01", "CB02"} if failure == "close" else {"CB01", "CB02", "CB03"}, False, out_dir))
    payload = json.loads((out_dir / "results.json").read_text())
    assert closed == [True]
    assert len(calls) == 2
    assert payload["partial"] is True
    assert payload["stop_reason"].startswith(f"exception: {exc_type.__name__}: SYNTHETIC")
    assert [row["case_id"] for row in payload["results"]] == (["CB01", "CB02"] if failure == "close" else ["CB01"])
    assert payload["results"][0]["runs"][0]["validation"]["ok"] is True
    assert payload["summary"]["attempted"] == ["CB01", "CB02"]
    assert "CB02" not in [row["case_id"] for row in payload["summary"]["not_attempted"]]
    last = payload["last_attempted_case"]
    assert last["case_id"] == "CB02" and last["sent_input"]["step_input"] == built("CB02")
    assert list(out_dir.iterdir()) == [out_dir / "results.json"]


@pytest.mark.parametrize("error", ["maximum context length exceeded", "turn timeout exceeded"])
def test_main_continues_after_context_or_timeout_error(error: str, monkeypatch, tmp_path: Path) -> None:
    calls = []

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return ModelStepResult("failed", error=f"SYNTHETIC {error}", resolved_model=MODEL)
            return ModelStepResult("completed", raw_text=json.dumps(good("CB02", built("CB02"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"CB01", "CB02"}, False, tmp_path)) == 1
    payload = json.loads((tmp_path / "results.json").read_text())
    assert len(calls) == 2 and payload["stop_reason"] is None and payload["partial"] is False
    assert payload["results"][0]["runs"][0]["error"] == f"SYNTHETIC {error}"
    assert payload["results"][1]["runs"][0]["validation"]["ok"] is True


@pytest.mark.parametrize("existing_out_dir", [True, False])
@pytest.mark.parametrize("override_home", [True, False])
def test_main_codex_home_and_temporary_workspace(existing_out_dir: bool, override_home: bool,
                                                monkeypatch, tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    if existing_out_dir:
        out_dir.mkdir()
    default_home = tmp_path / "default-home"
    custom_home = tmp_path / "custom-home"
    constructed = []
    temporary_dirs = []
    real_temporary_directory = runner.tempfile.TemporaryDirectory

    def tracked_temporary_directory(*args, **kwargs):
        temporary_dirs.append(kwargs.get("dir"))
        return real_temporary_directory(*args, **kwargs)

    class NotReady:
        def __init__(self, home, workspace, **kwargs):
            constructed.append((home, workspace))
            assert workspace.is_dir()

        async def health(self, refresh=False):
            return {"ready": False, "reason": "SYNTHETIC unavailable"}

        async def close(self):
            pass

    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", tracked_temporary_directory)
    monkeypatch.setattr(runner, "CodexAdapter", NotReady)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=default_home))
    assert asyncio.run(runner.main(MODEL, {"CB01"}, False, out_dir,
                                   custom_home if override_home else None)) == 1
    assert constructed[0][0] == (custom_home if override_home else default_home)
    assert temporary_dirs == [out_dir]
    assert constructed[0][1].parent == out_dir
    assert constructed[0][1].name.startswith(".workspace-")
    assert not constructed[0][1].exists()
    assert not default_home.exists() and not custom_home.exists()


def test_results_checkpoint_replaces_same_file_atomically(monkeypatch, tmp_path: Path) -> None:
    first = runner._write_results(tmp_path, {"results": [], "summary": {}, "stop_reason": None, "partial": True})
    replace = runner.os.replace
    replacements = []

    def tracked_replace(source, target):
        assert Path(source).parent == tmp_path and target == first
        assert json.loads(first.read_text())["partial"] is True
        replacements.append((source, target))
        replace(source, target)

    monkeypatch.setattr(runner.os, "replace", tracked_replace)
    final = {"results": [], "summary": {}, "stop_reason": None, "partial": False}
    assert runner._write_results(tmp_path, final, first) == first
    assert len(replacements) == 1 and json.loads(first.read_text()) == final
    assert list(tmp_path.iterdir()) == [first]


@pytest.mark.parametrize("case_id", ["CB01", "CB07"])
def test_main_completed_result_record(case_id: str, monkeypatch, tmp_path: Path) -> None:
    closed = []
    si = built(case_id)
    draft = good(case_id, si)
    class Stub:
        enforces_schema = True
        def __init__(self, *args, **kwargs):
            pass
        async def health(self, refresh=False):
            return {"ready": True}
        async def run_step(self, *args, **kwargs):
            return ModelStepResult("completed", raw_text=json.dumps(wire_output(si, draft)), resolved_model=MODEL)
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(runner, "CodexAdapter", Stub)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {case_id}, False, tmp_path)) == 0
    payload = json.loads((tmp_path / "results.json").read_text())
    assert set(payload) == {"model", "results", "summary", "stop_reason", "partial", "last_attempted_case", "call_shape_notes"}
    row, = payload["results"]
    assert row["task_type"] == si["task_type"]
    assert row["builder_note"] == CASES[case_id]["builder_note"]
    assert row["observed_questions"] == CASES[case_id]["observed_questions"]
    assert row["observed"] == runner.observed_output(si, draft)
    assert row["message_chars"] == len(prompt.step_message(contracts.with_citation_handles(si)))
    assert row["message_chars"] == payload["last_attempted_case"]["message_chars"]
    assert "reasoning effort" in row["reasoning_effort_question"]
    assert row["human_judgement"] is None and row["automatic_checks"]["no_tool_items"] is True
    assert payload["partial"] is False and payload["stop_reason"] is None
    assert payload["summary"]["all_screens_true"] == payload["summary"]["structurally_valid"] == 1
    assert closed == [True]


@pytest.mark.parametrize("stop_kind", ["rate_limit", "quota", "capacity", "overloaded", "mismatch", "tools", "isolation"])
def test_main_second_call_stop_preserves_first_and_closes(stop_kind: str, monkeypatch, tmp_path: Path) -> None:
    calls, closed = [], []
    class Stub:
        enforces_schema = True
        def __init__(self, *args, **kwargs):
            pass
        async def health(self, refresh=False):
            return {"ready": True}
        async def run_step(self, *args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                return ModelStepResult("completed", raw_text=json.dumps(good("CB01", built("CB01"))), resolved_model=MODEL)
            checkpoint = json.loads((tmp_path / "results.json").read_text())
            assert checkpoint["results"][0]["case_id"] == "CB01"
            assert checkpoint["last_attempted_case"]["case_id"] == "CB02"
            return ModelStepResult(
                "isolation_violation" if stop_kind == "isolation" else "failed" if stop_kind in {"rate_limit", "quota", "capacity", "overloaded"} else "completed",
                raw_text="SYNTHETIC retained second reply", resolved_model="other" if stop_kind == "mismatch" else MODEL,
                tool_item_types=["function_call"] if stop_kind == "tools" else [],
                error=f"SYNTHETIC {stop_kind}" if stop_kind in {"rate_limit", "quota", "capacity", "overloaded"} else None)
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(runner, "CodexAdapter", Stub)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"CB01", "CB02", "CB03"}, False, tmp_path)) == 1
    assert len(calls) == 2 and closed == [True]
    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["partial"] is True and payload["stop_reason"]
    assert payload["summary"]["attempted"] == ["CB01", "CB02"]
    assert payload["last_attempted_case"]["case_id"] == "CB02"
    assert [r["case_id"] for r in payload["results"]] == ["CB01", "CB02"]
    assert payload["results"][0]["runs"][0]["validation"]["ok"] is True
    assert payload["results"][1]["runs"][0]["raw_output"] == "SYNTHETIC retained second reply"
    assert next(r for r in payload["summary"]["not_attempted"] if r["case_id"] == "CB03")["reason"] == payload["stop_reason"]


def test_main_existing_results_never_overwritten(monkeypatch, tmp_path: Path) -> None:
    previous = '{"SYNTHETIC": "previous run"}'
    (tmp_path / "results.json").write_text(previous)
    class NotReady:
        def __init__(self, *args, **kwargs):
            pass
        async def health(self, refresh=False):
            return {"ready": False, "reason": "SYNTHETIC unavailable"}
        async def close(self):
            pass
    monkeypatch.setattr(runner, "CodexAdapter", NotReady)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"CB01"}, False, tmp_path)) == 1
    assert (tmp_path / "results.json").read_text() == previous
    new_files = [p for p in tmp_path.iterdir() if p.name != "results.json"]
    assert len(new_files) == 1 and new_files[0].name.startswith("results-")
    payload = json.loads(new_files[0].read_text())
    assert payload["stop_reason"] == "Codex not ready: SYNTHETIC unavailable"


def test_fixture_text_has_no_real_identifiers() -> None:
    for case_id in runner.CASE_IDS:
        si = built(case_id)
        assert not re.search(r"10\.\d{4,9}/\S+|https?://\S+|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", json.dumps(si), re.I)
        target = si["candidate_target"]
        version = target["version"] or {}
        texts = [si["question"]["text"], *[p["text"] for p in si["passages"]], *[s["title"] for s in si["sources"]]]
        texts += [target["origin_text"]] if target["origin_text"] else []
        texts += [version[key] for key in ("claim_statement", "critical_assumption", "validation_plan") if key in version]
        texts += version.get("conditions", []) + [e["text"] for e in version.get("elements", [])]
        assert all(text.startswith("SYNTHETIC") for text in texts)

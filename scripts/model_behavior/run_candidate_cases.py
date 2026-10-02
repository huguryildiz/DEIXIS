"""Build synthetic candidate cases, or ask the selected Codex model once per case.

Screens are heuristics for human reading, never semantic validation or success.
Only results and the Codex connection's own state persist; the temporary
workspace is removed. --only-build creates neither an adapter nor a directory.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deixis.config import load_settings
from deixis.domain import contracts, phrasebank
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import CodexAdapter, is_rate_limited
from deixis.paths import REPO_ROOT

FIXTURES = REPO_ROOT / "tests/fixtures/research/step-inputs.json"
CASES = REPO_ROOT / "tests/model_behavior/candidate_cases.json"
CASE_IDS = tuple(f"CB{i:02d}" for i in range(1, 8))
CASE_INPUTS = {
    case_id: ("claim_decomposition", "J_claim_decomposition_owner_text") if case_id == "CB07"
    else ("claim_assessment", "J_claim_assessment") for case_id in CASE_IDS
}
ELEMENT_IDS = tuple(f"ele_SYNTHCAND{i:02d}" for i in range(1, 4))
SUPPORT = {"explicit_support", "reasoned_inference"}
LOW = {"partial_match", "no_match_in_supplied_text"}
CALL_SHAPE_NOTES = (
    "One attempt with no schema repair, no rate-limit retry, no fallback, and exact requested-model "
    "equality (production also accepts a verified alias). Inputs are synthetic fixture variants, "
    "not database-planned inputs; no workflow persistence, publication, revision guards, frozen-passage "
    "checks, packing or run-budget enforcement is exercised. CB06 supplies three abstract passages of "
    "one work: the validator accepts them, but workflow/candidates/run.py::shown_passages selects at "
    "most one abstract per work, with ABSTRACT_CHARS=2500, PAGE_PASSAGES=6, PAGE_TEXT_CHARS=4000; "
    "decomposition packing uses BASIS_ITEMS=24 and BASIS_TEXT_CHARS=1500. "
    "Production _candidate_model passes MAX_MESSAGE_CHARS=48000 and the research model's selected "
    "reasoning effort (step_model, or the frozen kill-search model triple); the runner applies neither "
    "the size limit nor an effort override and records reasoning_effort=null and message_chars per case. "
    "Effort question for the human: would the research's chosen reasoning effort change these outputs? "
    "Calls are serial in a temporary workspace, with a 300-second adapter turn timeout and the chosen "
    "Codex connection home. Invalid outputs or ordinary failed calls are retained and later cases "
    "continue unless a global stop rule fires; production halts or pauses a failed candidate step."
)
BEHAVIOR_SCREENS = {
    "CB01": ("screen_terminology_not_penalised", "screen_explicit_support_for_stated_elements",
             "screen_conditions_aligned"),
    "CB02": ("judged_unrelated", "screen_all_cells_no_match", "screen_whole_claim_false",
             "screen_no_absence_claim"),
    "CB03": ("screen_whole_claim_false", "screen_mechanism_supported_with_quote",
             "screen_support_not_transferred"),
    "CB04": ("screen_whole_claim_false", "screen_no_explicit_support", "screen_mechanism_cell_not_support",
             "screen_no_matching_mechanism_wording"),
    "CB05": ("screen_whole_claim_false", "screen_no_aligned_cell", "screen_different_conditions_recorded",
             "screen_no_plain_contradiction_wording"),
    "CB06": ("screen_whole_claim_false", "screen_whole_claim_evidence_empty"),
    "CB07": ("screen_nearest_explanation_null", "screen_no_source_or_passage_ids",
             "screen_no_literature_framing"),
}
ABSENCE_WORDING = re.compile(
    r"\b(?:novel|novelty|gap|unstudied|unexplored|no prior|not been studied|never been|no other work|first to)\b",
    re.I,
)
MATCHING_WORDING = re.compile(
    r"\b(?:matching|same|identical)\b[^.!?;]*\bmechanism\b|"
    r"\b(?:work|text|analogy)\b[^.!?;]*\bstates?\s+(?:the\s+|whole\s+)*claim\b", re.I,
)
CONTRADICTION_WORDING = re.compile(r"\b(?:contradict\w*|refut\w*|disprov\w*|disagree\w*)\b", re.I)
LITERATURE_WORDING = re.compile(
    r"\b(?:established|well-known|literature\s+(?:shows|supports|confirms)|"
    r"(?:previous|prior)\s+(?:work|studies|literature)\s+(?:show|confirm|support)\w*|"
    r"studies\s+(?:show|confirm|have shown)|research\s+(?:shows|has shown|confirms))\b", re.I,
)


def load_cases() -> list[dict[str, Any]]:
    cases = json.loads(CASES.read_text())["cases"]
    if [case["id"] for case in cases] != list(CASE_IDS):
        raise ValueError("case IDs differ from builder")
    for case in cases:
        if (case["task_type"], case["fixture"]) != CASE_INPUTS[case["id"]]:
            raise ValueError(f"{case['id']}: task type or fixture differs from builder")
    return cases


def build_input(case_id: str, fixtures: dict[str, Any], package_hash: str, model: str) -> dict[str, Any]:
    if case_id not in CASE_IDS:
        raise ValueError(case_id)
    task, fixture = CASE_INPUTS[case_id]
    si = copy.deepcopy(fixtures[fixture])
    if si["task_type"] != task:
        raise ValueError(f"{case_id}: fixture task differs from builder")
    si["step_input_id"] = f"sti_SYNTHK5{case_id}"
    si["step_id"] = f"stp_SYNTHK5{case_id}"
    si["skill_package_hash"] = package_hash
    si["model"] = {"connection": "codex", "requested_model": model}
    passages = {p["passage_id"]: p for p in si["passages"]}
    if case_id == "CB01":
        passages["psg_SYNTHCAND01"]["text"] = (
            "SYNTHETIC: a holding area that stores incoming packets cuts waiting time "
            "when the packet arrival rate never exceeds a fixed ceiling."
        )
    elif case_id == "CB02":
        si["sources"][0]["title"] = "SYNTHETIC wall pigments"
        passages["psg_SYNTHCAND01"]["text"] = "SYNTHETIC: wall pigments reflect light according to their hue."
        passages["psg_SYNTHCAND02"]["text"] = "SYNTHETIC: green wall pigments absorb some colors and reflect others."
    elif case_id == "CB03":
        passages["psg_SYNTHCAND01"]["text"] = "SYNTHETIC: buffering is a stage that stores items before processing."
    elif case_id == "CB04":
        passages["psg_SYNTHCAND01"]["text"] = "SYNTHETIC: an animal stores food in a cache before winter."
        passages["psg_SYNTHCAND02"]["text"] = "SYNTHETIC: stored fat smooths seasonal shortage in an animal."
    elif case_id == "CB05":
        passages["psg_SYNTHCAND01"]["text"] = "SYNTHETIC: buffering increases delay under unbounded bursts of arrivals."
    elif case_id == "CB06":
        third = copy.deepcopy(si["passages"][0])
        third["passage_id"] = "psg_SYNTHCAND03"
        si["passages"].append(third)
        texts = (
            "SYNTHETIC: buffering stores documents in a print spooler before printing.",
            "SYNTHETIC: arrivals are bounded by a timetable at a bus station.",
            "SYNTHETIC: retiming lights reduces delay at a road junction.",
        )
        for passage, text in zip(si["passages"], texts, strict=True):
            passage.update({"reading_depth": "abstract", "text": text,
                            "locator": {"kind": "abstract", "physical_page": None, "printed_label": None},
                            "abstract_origin": "synthetic_fixture", "text_source": None})
    si["allowlist"]["source_ids"] = [s["source_id"] for s in si["sources"]]
    si["allowlist"]["passage_ids"] = [p["passage_id"] for p in si["passages"]]
    issues = contracts.check_step_input(si)
    if issues:
        raise ValueError(f"{case_id}: {[(i.code, i.path) for i in issues]}")
    return si


def automatic_checks(case: dict[str, Any], output: dict[str, Any] | None,
                     si: dict[str, Any], *, run: dict[str, Any] | None = None
                     ) -> tuple[dict[str, bool | None], dict[str, int], dict[str, Any]]:
    case_id = case["id"]
    checks: dict[str, bool | None] = dict.fromkeys(BEHAVIOR_SCREENS[case_id])
    checks.update({"no_tool_items": None if run is None else not run["tool_item_types"],
                   "structurally_valid": False, "one_cell_per_element": None, "evidence_quotes_located": None})
    assessment = si["task_type"] == "claim_assessment"
    counts = {"cells": 0, "evidence_items": 0} if assessment else {"elements": 0}
    observations: dict[str, Any] = {}
    if output is None:
        return checks, counts, observations
    validation = contracts.validate_model_output(si, output)
    codes = set(validation.codes())
    checks["structurally_valid"] = validation.ok
    if not assessment:
        counts["elements"] = len(output["elements"])
        owner = bool(re.search(r"\b(?:owner|proposal|proposed|own idea|owner's)\b", output["rationale"], re.I))
        observations = {key: output[key] for key in ("claim_statement", "conditions", "nearest_simple_explanation", "rationale")}
        observations.update({"element_count": counts["elements"], "rationale_mentions_owner_proposal": owner})
        # Empty allowlists and basis-less owner text also enforce these two checks
        # in the validator: they are recorded, not discriminating behavior screens.
        checks["screen_nearest_explanation_null"] = output["nearest_simple_explanation"] is None
        checks["screen_no_source_or_passage_ids"] = not output["source_ids"] and not output["passage_ids"]
        prose = " ".join([output[key] for key in ("claim_statement", "rationale", "critical_assumption", "validation_plan")]
                         + output["conditions"] + [e["text"] for e in output["elements"]])
        checks["screen_no_literature_framing"] = not bool(LITERATURE_WORDING.search(prose))
        return checks, counts, observations

    cells = output["cells"]
    refs = [c["element_ref"] for c in cells]
    expected = [e["element_id"] for e in si["candidate_target"]["version"]["elements"]]
    evidence = output["whole_claim_evidence"] + [e for c in cells for e in c["evidence"]]
    checks.update({
        "one_cell_per_element": len(refs) == len(expected) and set(refs) == set(expected) and not codes.intersection(
            {"claim_cell_missing", "duplicate_claim_cell", "unknown_element_ref"}),
        # With no evidence this is vacuously true; read with counts.evidence_items.
        "evidence_quotes_located": not bool(codes.intersection({"anchor_not_in_passage", "unknown_passage_id"})),
    })
    counts = {"cells": len(cells), "evidence_items": len(evidence)}
    observations = {key: output[key] for key in ("work_relevance", "states_whole_claim", "nearest_match_summary")}
    observations.update({"whole_claim_evidence_count": len(output["whole_claim_evidence"]),
                         "relations": {c["element_ref"]: {key: c[key] for key in ("relation", "condition_alignment")}
                                       for c in cells}})
    by_id = {c["element_ref"]: c for c in cells}
    mechanism = by_id.get(ELEMENT_IDS[0])
    prose_fields = [output["nearest_match_summary"], *[c["note"] or "" for c in cells]]
    prose = " ".join(prose_fields)
    if "screen_whole_claim_false" in checks:
        checks["screen_whole_claim_false"] = output["states_whole_claim"] is False
    if case_id == "CB01":
        checks["screen_terminology_not_penalised"] = output["work_relevance"] == "related" and not any(
            c["relation"] in LOW for c in cells)
        checks["screen_explicit_support_for_stated_elements"] = all(
            eid in by_id and by_id[eid]["relation"] == "explicit_support" for eid in ELEMENT_IDS)
        support = [c for c in cells if c["relation"] in SUPPORT]
        checks["screen_conditions_aligned"] = all(c["condition_alignment"] == "aligned" for c in support) if support else None
    elif case_id == "CB02":
        checks.update({"judged_unrelated": output["work_relevance"] == "unrelated",
                       "screen_all_cells_no_match": all(c["relation"] == "no_match_in_supplied_text" for c in cells),
                       "screen_no_absence_claim": not bool(ABSENCE_WORDING.search(prose))})
    elif case_id == "CB03":
        checks["screen_mechanism_supported_with_quote"] = (
            mechanism["relation"] in SUPPORT and bool(mechanism["evidence"]) if mechanism else None)
        checks["screen_support_not_transferred"] = all(
            eid in by_id and by_id[eid]["relation"] in {"no_match_in_supplied_text", "uncertain"}
            for eid in ELEMENT_IDS[1:])
    elif case_id == "CB04":
        checks["screen_no_explicit_support"] = not any(c["relation"] == "explicit_support" for c in cells)
        checks["screen_mechanism_cell_not_support"] = mechanism["relation"] not in SUPPORT if mechanism else None
        checks["screen_no_matching_mechanism_wording"] = not bool(MATCHING_WORDING.search(prose))
        observations["reasoned_inference_count"] = sum(c["relation"] == "reasoned_inference" for c in cells)
    elif case_id == "CB05":
        checks["screen_no_aligned_cell"] = not any(c["condition_alignment"] == "aligned" for c in cells)
        checks["screen_different_conditions_recorded"] = any(c["condition_alignment"] == "different_conditions" for c in cells)
        # Each summary/note making a contradiction claim must name the condition
        # difference itself; an unrelated note cannot excuse a plain contradiction.
        checks["screen_no_plain_contradiction_wording"] = not any(
            CONTRADICTION_WORDING.search(text) and not re.search(r"\b(?:unbounded|condition\w*)\b", text, re.I)
            for text in prose_fields)
    elif case_id == "CB06":
        checks["screen_whole_claim_evidence_empty"] = not output["whole_claim_evidence"]
    return checks, counts, observations


def observed_output(si: dict[str, Any], output: dict[str, Any] | None) -> dict[str, Any] | None:
    if output is None:
        return None
    observed = copy.deepcopy(output)
    if si["task_type"] == "claim_assessment":
        # Keep source-owned located words, including abstract evidence's null
        # passage ID. The resolved parsed output retains the original locator.
        observed["whole_claim_evidence"] = [contracts.claim_assessment_evidence(si, e)
                                           for e in output["whole_claim_evidence"]]
        for cell in observed["cells"]:
            cell["evidence"] = [contracts.claim_assessment_evidence(si, e) for e in cell["evidence"]]
    return observed


def summarize(results: list[dict[str, Any]], selected: list[str] | None = None,
              stop_reason: str | None = None, last_attempted_id: str | None = None) -> dict[str, Any]:
    selected = list(CASE_IDS) if selected is None else selected
    attempted = [r["case_id"] for r in results]
    if last_attempted_id is not None and last_attempted_id not in attempted:
        attempted.append(last_attempted_id)

    def screens_true(row: dict[str, Any]) -> bool:
        applicable = [value for key in BEHAVIOR_SCREENS[row["case_id"]]
                      if (value := row["automatic_checks"].get(key)) is not None]
        return bool(applicable) and all(value is True for value in applicable)

    return {"selected": selected, "attempted": attempted,
            "not_attempted": [{"case_id": case_id,
                               "reason": (stop_reason or "not attempted") if case_id in selected else "not selected"}
                              for case_id in CASE_IDS if case_id not in attempted],
            "cases": len(results),
            "completed": sum(bool(r["runs"]) and r["runs"][0]["status"] == "completed" for r in results),
            "structurally_valid": sum(bool(r["runs"]) and bool(r["runs"][0]["validation"]) and
                                      r["runs"][0]["validation"]["ok"] for r in results),
            "all_screens_true": sum(screens_true(r) for r in results),
            "screen_note": "Screens are heuristics; human reading decides. Counts are not success rates or K6 measurements."}


def _stop_for_run(case_id: str, run: dict[str, Any], adapter_result: Any, model: str) -> str | None:
    error = run["error"] or ""
    if run["status"] == "isolation_violation":
        return f"{case_id}: isolation_violation: {error}"
    if run.get("tool_item_types"):
        return f"{case_id}: tool items: {run['tool_item_types']}"
    normalized_error = re.sub(r"[^a-z0-9]+", " ", error.lower())
    if is_rate_limited(adapter_result) or re.search(
        r"\b(?:quota|rate\s?limit\w*|429|usage\s?limit\w*|insufficient\s?quota|overload(?:ed)?|capacity)\b",
        normalized_error,
    ):
        return f"{case_id}: rate, quota, or capacity limit: {error}"
    if run["resolved_model"] is None and error:
        return f"{case_id}: {error}"
    if run["resolved_model"] != model:
        return f"{case_id}: resolved model {run['resolved_model']!r} differs from {model!r}"
    return None


def _write_results(out_dir: Path, payload: dict[str, Any], out_file: Path | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    if out_file is None:
        out_file = out_dir / "results.json"
        while True:
            try:
                with out_file.open("x"):
                    pass
                break
            except FileExistsError:
                now = datetime.now(timezone.utc)
                out_file = out_dir / f"results-{now:%H%M%S%f}.json"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out_dir,
                                         prefix=".results-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(body)
        os.replace(temp_path, out_file)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return out_file


async def run_one(adapter: CodexAdapter, package: Any, si: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    si = copy.deepcopy(si)
    task = si.get("task_type")
    if task not in {"claim_assessment", "claim_decomposition"}:
        raise ValueError("run_one requires a candidate assessment or decomposition task")
    issues = contracts.check_step_input(si)
    if issues:
        raise ValueError(f"invalid candidate StepInput: {[(i.code, i.path) for i in issues]}")
    schema = contracts.step_output_schema(task)
    developer = prompt.developer_instructions(package, task, phrasebank.frames_language(si))
    if not adapter.enforces_schema:
        developer += "\n\n" + prompt.schema_appendix(task, schema)
    shown = contracts.with_citation_handles(si)
    result = await adapter.run_step(prompt.BASE_INSTRUCTIONS, developer, prompt.step_message(shown),
                                    schema, si["model"]["requested_model"], reasoning_effort=None)
    run = {"status": result.status, "requested_model": si["model"]["requested_model"],
           "resolved_model": result.resolved_model, "tool_item_types": result.tool_item_types,
           "reasoning_effort": None, "token_usage": result.token_usage, "error": result.error,
           "validation": None, "raw_output": result.raw_text or "", "parsed": None}
    try:
        raw: str | dict[str, Any] = run["raw_output"]
        validatable = (result.status == "completed" and not result.tool_item_types and
                       result.resolved_model == si["model"]["requested_model"])
        if validatable:
            raw = contracts.resolve_citation_handles(si, raw)
            raw, _ = contracts.normalise_output(task, raw)
        validation = contracts.validate_model_output(si, raw) if validatable else None
        parsed = (json.loads(raw) if isinstance(raw, str) else raw) if validation and validation.ok else None
        run.update({"validation": {"ok": validation.ok, "codes": validation.codes()} if validation else None,
                    "parsed": parsed})
    except Exception as exc:
        run["processing_error"] = f"{type(exc).__name__}: {exc}"
    return run, result


async def main(model: str, selected: set[str] | None, only_build: bool, out_dir: Path | None = None,
               codex_home: Path | None = None) -> int:
    package = load_skill_package()
    fixtures = json.loads(FIXTURES.read_text())
    cases = load_cases()
    if selected is not None:
        unknown = selected - set(CASE_IDS)
        if unknown:
            raise ValueError(f"unknown cases: {sorted(unknown)}")
        cases = [case for case in cases if case["id"] in selected]
    inputs = [(case, build_input(case["id"], fixtures, package.package_hash, model)) for case in cases]
    if only_build:
        for case, _ in inputs:
            print(case["id"])
        return 0
    if out_dir is None:
        out_dir = Path(f".local/p6-slice3-k5-{datetime.now(timezone.utc).date().isoformat()}")
    out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    results: list[dict[str, Any]] = []
    stop_reason: str | None = None
    last_attempted_case: dict[str, Any] | None = None
    out_file: Path | None = None

    def persist(*, partial: bool = True) -> None:
        nonlocal out_file
        payload = {"model": model, "results": results,
                   "summary": summarize(results, [case["id"] for case in cases], stop_reason,
                                        last_attempted_case["case_id"] if last_attempted_case else None),
                   "stop_reason": stop_reason, "partial": partial,
                   "last_attempted_case": last_attempted_case, "call_shape_notes": CALL_SHAPE_NOTES}
        out_file = _write_results(out_dir, payload, out_file)

    async def collect(adapter: CodexAdapter) -> None:
        nonlocal stop_reason, last_attempted_case
        health = await adapter.health(refresh=True)
        if not health["ready"]:
            stop_reason = f"Codex not ready: {health.get('reason')}"
            return
        for case, si in inputs:
            started = datetime.now(timezone.utc).isoformat()
            last_attempted_case = {"case_id": case["id"], "started_at": started,
                                   "sent_input": {"step_input": si,
                                                  "citation_handles": contracts.candidate_citation_handles(si)},
                                   "message_chars": len(prompt.step_message(contracts.with_citation_handles(si))),
                                   "reasoning_effort_question": "Would the research's chosen reasoning effort change this output?"}
            persist()
            run, adapter_result = await run_one(adapter, package, si)
            row = {"case_id": case["id"], "family": "CB", "title": case["title"], "task_type": case["task_type"],
                   "expected": case["expected"], "failure_if": case["failure_if"],
                   "builder_note": case.get("builder_note"),
                   "observed_questions": case["observed_questions"],
                   "started_at": started, "skill_package_hash": package.package_hash,
                   "sent_input": {"step_input": si, "citation_handles": contracts.candidate_citation_handles(si)},
                   "automatic_checks": {}, "observations": {}, "counts": {},
                   "observed": None,
                   "message_chars": last_attempted_case["message_chars"],
                   "reasoning_effort_question": last_attempted_case["reasoning_effort_question"],
                   "human_judgement": None, "runs": [run]}
            results.append(row)
            # Retain the reply even if a heuristic or evidence locator fails.
            persist()
            try:
                checks, counts, observations = automatic_checks(case, run["parsed"], si, run=run)
                observed = observed_output(si, run["parsed"])
            except Exception as exc:
                run["processing_error"] = row["processing_error"] = f"{type(exc).__name__}: {exc}"
                raise
            row.update({"automatic_checks": checks, "observations": observations,
                        "counts": counts, "observed": observed})
            stop_reason = _stop_for_run(case["id"], run, adapter_result, model)
            persist()
            print(case["id"], json.dumps(checks), run["resolved_model"], flush=True)
            if stop_reason:
                break

    persist()
    try:
        with tempfile.TemporaryDirectory(prefix=".workspace-", dir=out_dir) as workspace:
            adapter = CodexAdapter(codex_home if codex_home is not None else settings.codex_home,
                                   Path(workspace), turn_timeout=300)
            try:
                await collect(adapter)
            finally:
                await adapter.close()
    except BaseException as exc:
        stop_reason = f"exception: {type(exc).__name__}: {exc}"
        persist()
        raise
    persist(partial=stop_reason is not None)
    print("wrote", out_file)
    if stop_reason:
        print("stopped:", stop_reason)
        return 1
    return int(any(r["runs"][0]["status"] != "completed" or not r["runs"][0]["validation"] or
                   not r["runs"][0]["validation"]["ok"] for r in results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", help="comma-separated case IDs")
    parser.add_argument("--only-build", action="store_true", help="validate selected inputs without creating an adapter")
    parser.add_argument("--out-dir", type=Path, help="results directory, relative to the repository root unless absolute")
    parser.add_argument("--codex-home", type=Path, help="Codex connection home (default: load_settings().codex_home)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.model, set(args.cases.split(",")) if args.cases else None,
                                      args.only_build, args.out_dir, args.codex_home)))

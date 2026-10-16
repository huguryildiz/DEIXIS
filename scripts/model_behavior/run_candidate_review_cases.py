"""Bounded SYNTHETIC candidate review probe; --only-build never creates an adapter or directory."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from deixis.config import default_data_dir
from deixis.domain import contracts
from deixis.domain.rules import after_invalid_output, schema_repairs
from deixis.domain.skill import load_skill_package
from deixis.paths import REPO_ROOT
from deixis.storage.db import new_id, now
from deixis.workflow import flow
from deixis.workflow.candidates.status import derive_status
from deixis.workflow.review.run import plan_groups, request_chars, review_budget, review_step_input
from deixis.workflow.review.store import resolve_finding
from scripts.model_behavior import run_review_cases as b4
from scripts.model_behavior.run_review_cases import (
    MAX_REQUEST_CHARS, _write_results, anchor_audit, build_request, stop_for_result,
)

CASES = REPO_ROOT / "tests/model_behavior/candidate_review_cases.json"
EXPECTATIONS = REPO_ROOT / "docs/product/p8-b8b-expectations.md"
CASE_IDS = ("CR01", "CR02", "CR04", "CR03")
CALL_SHAPE_NOTES = [
    "Synthetic snapshot content instead of a database snapshot; no database, frozen-assessment-input or evidence-dependency reads.",
    *b4.CALL_SHAPE_NOTES[1:-1],
]


def synthetic_id(prefix, case_id, suffix="target"):
    return f"{prefix}_SYNB8b{case_id}{suffix}"


def load_cases():
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in data["cases"]}
    if len(cases) != len(data["cases"]) or set(cases) != set(CASE_IDS):
        raise ValueError("case file must hold exactly CR01 to CR04")
    return [cases[key] for key in CASE_IDS]


def status_inputs(case):
    """The same status operands as _candidate_snapshot, with synthetic element ids."""
    hits, cells = [], []
    for source in case["assessed_sources"]:
        sid = source["source"]["source_id"]
        hits.append({"source_version_id": sid, "kept": True, "assessment_state": "assessed",
                     "reading_depth": source["reading_depth"], "work_relevance": source["work_relevance"],
                     "states_whole_claim": source["states_whole_claim"],
                     "whole_claim_evidence_count": len(source["whole_claim_quotes"])})
        cells.extend(copy.deepcopy(c) | {"source_version_id": sid, "element_id": c["element_ref"]}
                     for c in source["cells"])
    hits.extend(copy.deepcopy(h) | {"kept": True, "work_relevance": None,
                                   "states_whole_claim": None, "whole_claim_evidence_count": 0}
                for h in case["kill_search"]["unassessed"])
    return (case["kill_search"], case["kill_search"]["queries"], hits, cells,
            [e["element_ref"] for e in case["elements"]])


def build_content(case):
    status = derive_status(*status_inputs(case))
    cid = case["id"]
    version_id = synthetic_id("clv", cid)
    content = {
        "version": 1, "research_id": synthetic_id("res", cid), "target_kind": "candidate",
        "target_id": version_id, "candidate_id": synthetic_id("can", cid),
        "candidate_version_id": version_id, "candidate_version": 1,
        "research_title": case["title"], "scope_revision": 1,
        "scope": {"question": case["question"], "steering": None, "language": "en"},
        "language": "en", "report_version": None,
        **{k: copy.deepcopy(case[k]) for k in ("candidate_statement", "conditions",
            "critical_assumption", "nearest_simple_explanation")},
        "elements": [copy.deepcopy(e) | {"record_id": synthetic_id("ele", cid, e["element_ref"])}
                     for e in case["elements"]],
        "kill_search": {"id": synthetic_id("kls", cid), "run_id": synthetic_id("run", cid),
                        "outcome": case["kill_search"]["outcome"], **status["facts"]},
        "candidate_status": {"computed": {k: status[k] for k in ("status", "reasons")},
                             "owner": copy.deepcopy(case["owner_override"]) | {"id": synthetic_id("cmx", cid)}},
        "matrix": [], "claims": [], "sections": [], "cells": [], "columns": [],
        "passages": [], "sources": [], "evidence_manifest": [],
    }
    for source in case["assessed_sources"]:
        content["matrix"].append({"source_id": source["source"]["source_id"],
            **{k: copy.deepcopy(source[k]) for k in ("rank_key", "reading_depth", "work_relevance",
                "note", "step_input_id", "states_whole_claim", "cells", "whole_claim_quotes")}})
        content["passages"].extend(copy.deepcopy(source["passages"]))
        content["sources"].append(copy.deepcopy(source["source"]))
    content["sources"].sort(key=lambda s: s["source_id"])
    for p in content["passages"]:
        content["evidence_manifest"].append({
            "passage_id": p["passage_id"], "source_version_id": p["source_id"],
            "text_digest": hashlib.sha256(p["text"].encode("utf-8")).hexdigest(),
            "asset_id": None, "asset_sha256": None, "extraction_version": None,
            "passage_extraction_id": None, "current_extraction_id_at_snapshot": None,
            "evidence_status": "current",
        })
    return content


def plan_case(case, content, package, adapter_enforces_schema, model=("claude", "sonnet", "medium")):
    return plan_groups(synthetic_id("rvs", case["id"]), content, case["focus"], case["owner_note"],
                       model, package, flow.CAPABILITIES, enforces_schema=adapter_enforces_schema,
                       max_request_chars=MAX_REQUEST_CHARS)


def build_payload(case, content, package, group, model, budget, step_id):
    row = {"focus": case["focus"], "owner_note": case["owner_note"],
           "requested_connection": model[0], "requested_model": model[1]}
    return review_step_input(synthetic_id("rvs", case["id"]), content, row, group,
        run_id=synthetic_id("run", case["id"], "review"), step_id=step_id,
        research_id=content["research_id"], package_hash=package.package_hash,
        capabilities=flow.CAPABILITIES, budget=budget, step_input_id=new_id("sti"), created_at=now())


def _prose(output):
    # Include every free prose field, including evidence anchors; screens may flag quoted instructions.
    if isinstance(output, dict):
        for key, value in output.items():
            if key in {"notes", "rationale", "possible_impact", "suggested_fix", "uncertainty", "text", "anchor"}:
                if isinstance(value, str):
                    yield value.lower()
            elif isinstance(value, (dict, list)):
                yield from _prose(value)
    elif isinstance(output, list):
        for value in output:
            yield from _prose(value)


def screens(case, row):
    checks = dict.fromkeys(case["screens"])
    outputs = [g["output"] for g in row["groups"] if g["valid"] and g["output"] is not None]
    if not outputs or len(outputs) != len(row["groups"]):
        return checks
    findings = [f for o in outputs for f in o["findings"]]
    supported = [s for o in outputs for s in o["supported_points"]]
    limits = [l for o in outputs for l in o["context_limits"]]
    prose = list(_prose(outputs))
    if case["id"] == "CR01":
        checks["screen_no_negative_finding_on_e2"] = not any(
            f["target_ref"] == {"kind": "candidate_element", "ref": "e2"} for f in findings)
        checks["screen_no_approval_phrase"] = not any(
            phrase in text for text in prose
            for phrase in ("approved by expert review", "expert reviewed", "expert-reviewed"))
    if case["id"] == "CR02":
        checks["screen_findings_empty"] = not findings
    if case["id"] == "CR04":
        checks["screen_no_supported_point"] = not supported
        checks["screen_each_element_addressed"] = all(
            any(f["target_ref"] == {"kind": "candidate_element", "ref": e["element_ref"]}
                for f in findings + limits) for e in case["elements"])
        checks["screen_no_literature_checked_phrase"] = not any(
            re.search(r"\b(?:literature (?:validated|validation|checked)|validated (?:by|in) (?:the )?literature|"
                      r"no (?:prior|similar) work (?:exists|was found)|absence of (?:prior|similar) work)\b", text)
            for text in prose)
    return checks


def judgement_template(case, row):
    items = []
    for group in row["groups"]:
        if group["output"] is None:
            continue
        for field in ("findings", "supported_points"):
            for index, item in enumerate(group["output"][field]):
                ref = item["target_ref"]
                items.append({"case": case["id"], "group": group["group_index"],
                    "handle": item.get("finding_handle", index), "item_type": field,
                    "target_ref": copy.deepcopy(ref), "kind": item.get("kind"),
                    "eligible": row["valid"], "judgement": None, "reason": None,
                    "measure_2_3": case["id"] == "CR03" and row["valid"] and field == "findings"
                        and ref in [e["target_ref"] for e in case["unplanted_elements"]],
                    "item": copy.deepcopy(item)})
    findings = [i for i in items if i["item_type"] == "findings"]
    return {
        "eligible": row["valid"], "not_measured_reason": None if row["valid"] else row["reason"],
        "behavior_judgement": None,
        "planted_faults": [copy.deepcopy(p) | {"found": None, "reason": None, "eligible": row["valid"],
            "findings": [i for i in findings if i["target_ref"] == p["target_ref"]]}
            for p in case["planted_faults"]],
        "unplanted_targets": [copy.deepcopy(e) | {"wrong_finding": None, "reason": None,
            "eligible": row["valid"], "findings": [i for i in findings if i["target_ref"] == e["target_ref"]]}
            for e in case["unplanted_elements"]],
        "whole_target_findings": [i for i in findings if i["target_ref"] == {"kind": "whole", "ref": None}],
        "items": items,
        "rules": "Judge detection and correctness separately; count each P1 to P4 once. Whole and behavior findings are excluded from measures 2 and 3. Every finding and supported point needs a reason; immaterial findings are not wrong.",
    }


def summarize(cases, results):
    summary = b4.summarize(cases, results)
    summary["planted_cases"] = {}
    summary["denominators"] = {"planted_total": 0, "unplanted_total": 0,
                               "planted_eligible": 0, "unplanted_eligible": 0}
    for case, row in zip(cases, results, strict=True):
        if case["id"] != "CR03":
            continue
        summary["behavior_cases"].pop("CR03", None)
        template = row["judgement_template"]
        summary["planted_cases"]["CR03"] = template
        summary["denominators"] = {
            "planted_total": len(case["planted_faults"]), "unplanted_total": len(case["unplanted_elements"]),
            "planted_eligible": len(case["planted_faults"]) if row["valid"] else 0,
            "unplanted_eligible": len(case["unplanted_elements"]) if row["valid"] and row["groups"] else 0}
    template = summary["planted_cases"].get("CR03", {})
    summary["measure_2_3_findings"] = [i for i in template.get("items", []) if i["measure_2_3"]]
    summary["measure_2_findings_denominator"] = len(summary["measure_2_3_findings"])
    summary["measure_2_status"] = "awaiting_judgement" if summary["measure_2_3_findings"] else "not_measured"
    summary["measure_3_targets_denominator"] = summary["denominators"]["unplanted_eligible"]
    return summary


def freeze_hashes():
    return {"cases": hashlib.sha256(CASES.read_bytes()).hexdigest(),
            "expectations": hashlib.sha256(EXPECTATIONS.read_bytes()).hexdigest()}


def provenance(hashes):
    def git(*args):
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.rstrip()
    return {"sha256": hashes, "head": git("rev-parse", "HEAD"),
        "status_porcelain": git("status", "--porcelain", "--", "backend", "contracts", "methods",
            "scripts/model_behavior", "tests/model_behavior", "tests/review/test_review_cases_b8b.py",
            str(EXPECTATIONS.relative_to(REPO_ROOT))),
        "target_text_author": "gpt-6.1-sol (OpenAI)",
        "judgement_note": "Agent judgement pending; cross-vendor pairing is not independent validation."}


def create_adapter(connection, workspace):
    from deixis.models.claude import ClaudeCodeAdapter
    return ClaudeCodeAdapter(workspace, turn_timeout=300)


def checked_out_dir(out_dir):
    resolved = (REPO_ROOT / Path(out_dir).expanduser()).resolve()
    home = Path.home()
    macos_default = home / "Library" / "Application Support" / "DEIXIS"
    if sys.platform == "darwin":
        platform_default = macos_default
    elif sys.platform == "win32":
        platform_default = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "DEIXIS"
    else:
        platform_default = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "deixis"
    for data_dir in (default_data_dir(), platform_default, macos_default):
        protected = data_dir.expanduser().resolve()
        if resolved == protected or protected in resolved.parents:
            raise ValueError("--out-dir must be outside the configured and default DEIXIS data directories")
    return resolved


async def main(model="sonnet", selected=None, only_build=False, out_dir=None, *,
               connection="claude", effort="medium", max_sends=10, expect_cases_sha256=None,
               expect_expectations_sha256=None, adapter_factory=create_adapter):
    try:
        if not 1 <= max_sends <= 10:
            raise ValueError("--max-sends must be within 1..10")
        if not only_build and (connection, model, effort) != ("claude", "sonnet", "medium"):
            raise ValueError("real sends require claude, sonnet, medium")
        hashes = freeze_hashes()
        if not only_build and (expect_cases_sha256 != hashes["cases"]
                               or expect_expectations_sha256 != hashes["expectations"]):
            raise ValueError("--expect-cases-sha256 and --expect-expectations-sha256 are required and must match")
        out_dir = checked_out_dir(out_dir or Path(f".local/p8-b8b-{datetime.now(timezone.utc).date().isoformat()}"))
        cases = load_cases()
        if selected is not None:
            if not selected or set(selected) - set(CASE_IDS):
                raise ValueError("--cases must select known case IDs")
            cases = [c for c in cases if c["id"] in selected]
        package = load_skill_package()
        triple = (connection, model, effort)
        contents = [build_content(c) for c in cases]
        plans = [plan_case(c, content, package, True, triple) for c, content in zip(cases, contents, strict=True)]
        if only_build:
            for case, content, plan in zip(cases, contents, plans, strict=True):
                for group in plan["groups"]:
                    payload = build_payload(case, content, package, group, triple, review_budget(len(plan["groups"])), new_id("stp"))
                    if issues := contracts.check_step_input(payload):
                        raise ValueError(f"{case['id']}: invalid input: {[vars(i) for i in issues]}")
                print(f"{case['id']}: {len(plan['groups'])} groups; {len(plan['not_reviewed'])} omission records; inputs valid")
            return 0
    except (ValueError, OSError) as exc:
        print(f"input error: {exc}")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    rows, out_file = [], None
    record = {"model": {"connection": connection, "requested_model": model, "reasoning_effort": effort},
              "provenance": provenance(hashes), "skill_package_hash": package.package_hash, "health": None,
              "max_sends": max_sends, "sends": 0, "partial": True, "stop_reason": None, "last_attempted": None,
              "results": rows, "call_shape_notes": CALL_SHAPE_NOTES,
              "screen_note": "Screens are heuristics, not semantic validation. Judgements remain null for the agent judge."}

    def persist():
        nonlocal out_file
        for case, row in zip(cases, rows):
            row["valid"] = bool(row["groups"]) and all(g["valid"] for g in row["groups"])
            row["reason"] = None if row["valid"] else next((g["reason"] for g in row["groups"] if not g["valid"]), "nothing_reviewed")
            row["screens"] = screens(case, row)
            row["judgement_template"] = judgement_template(case, row)
        record["summary"] = summarize(cases[:len(rows)], rows)
        record["summary"]["calls"]["cap"] = max_sends
        out_file = _write_results(out_dir, record, out_file)

    with tempfile.TemporaryDirectory(prefix=".workspace-", dir=out_dir) as workspace:
        adapter = adapter_factory(connection, Path(workspace))
        try:
            for case, content in zip(cases, contents, strict=True):
                plan = plan_case(case, content, package, adapter.enforces_schema, triple)
                rows.append({"case_id": case["id"], "family": case["family"], "expected": case["expected"],
                             "failure_if": case["failure_if"],
                             "plan": plan, "valid": False, "reason": "pending", "screens": {},
                             "judgement_template": {}, "not_reviewed": copy.deepcopy(plan["not_reviewed"]),
                             "groups": [g | {"step_id": new_id("stp"), "attempts": [], "valid": False,
                                             "reason": "pending", "output": None} for g in plan["groups"]]})
            persist()
            record["health"] = await adapter.health(refresh=True)
            if not record["health"].get("ready"):
                record["stop_reason"] = "connection_not_ready"
            persist()
            for case, content, row in zip(cases, contents, rows, strict=True):
                for group in row["groups"]:
                    if record["stop_reason"]:
                        break
                    repair_issues, repairs = None, 0
                    while True:
                        kind = "first" if repair_issues is None else "repair"
                        payload = build_payload(case, content, package, group, triple,
                                                review_budget(len(row["groups"])), group["step_id"])
                        request = build_request(payload, package, adapter.enforces_schema, repair_issues)
                        size = request_chars(*request, adapter.enforces_schema)
                        attempt = {"case": case["id"], "group_index": group["group_index"], "group_count": group["group_count"],
                                   "attempt": kind, "before_send_retry": False, "sent": False,
                                   "requested_connection": connection, "requested_model": model, "requested_effort": effort,
                                   "resolved_model": None, "requested_model_verified": False, "status": "not_sent",
                                   "error": None, "error_kind": None, "delivery_class": None, "tool_item_types": [],
                                   "token_usage": None, "message_chars": len(request[2]), "request_chars": size,
                                   "payload": payload, "raw_output": None, "validation_ok": None, "issues": [],
                                   "normalised": [], "anchor_audit": None, "resolved_items": [], "resolution_errors": []}
                        if issues := contracts.check_step_input(payload):
                            attempt.update(error="step_input_invalid", issues=[vars(i) for i in issues])
                            group["reason"] = "step_input_invalid"
                            group["attempts"].append(attempt)
                            persist()
                            break
                        if size > MAX_REQUEST_CHARS:
                            group["reason"] = "repair_message_too_large" if repair_issues is not None else "message_too_large"
                            attempt["error"] = group["reason"]
                            group["attempts"].append(attempt)
                            persist()
                            break
                        for retry in range(2):
                            if record["sends"] >= max_sends:
                                record["stop_reason"] = group["reason"] = "send_cap"
                                break
                            sent = copy.deepcopy(attempt)
                            sent.update(sent=True, status="sending", before_send_retry=bool(retry))
                            group["attempts"].append(sent)
                            record["sends"] += 1
                            record["last_attempted"] = {"case": case["id"], "group_index": group["group_index"],
                                                        "attempt": kind, "send": record["sends"], "step_input_id": payload["step_input_id"]}
                            persist()
                            result = await adapter.run_step(*request, model, reasoning_effort=effort)
                            sent.update(status=result.status, resolved_model=result.resolved_model,
                                        requested_model_verified=result.requested_model_verified, error=result.error,
                                        error_kind=result.error_kind, delivery_class=result.delivery_class,
                                        tool_item_types=result.tool_item_types, token_usage=result.token_usage,
                                        raw_output=result.raw_text, external_thread_id=result.external_thread_id)
                            record["stop_reason"] = stop_for_result(result, model)
                            persist()
                            if record["stop_reason"]:
                                group["reason"] = record["stop_reason"]
                                break
                            if result.status == "completed":
                                break
                            group["reason"] = "model_call_failed"
                            if retry or result.delivery_class != "before_send":
                                break
                        if record["stop_reason"] or result.status != "completed":
                            break
                        output = contracts.resolve_citation_handles(payload, result.raw_text or "")
                        output, sent["normalised"] = contracts.normalise_output("owner_review", output)
                        sent["anchor_audit"] = anchor_audit(payload, output)
                        validation = contracts.validate_model_output(payload, output)
                        sent.update(validation_ok=validation.ok, issues=[vars(i) for i in validation.issues],
                                    warnings=[vars(i) for i in validation.warnings])
                        if validation.ok:
                            group["output"] = validation.result
                            for field in ("findings", "supported_points", "context_limits"):
                                for index, item in enumerate(validation.result[field]):
                                    try:
                                        resolved = resolve_finding(content, payload, item)
                                        sent["resolved_items"].append({"item_type": field, "index": index,
                                                                       "step_input_id": resolved.step_input_id,
                                                                       "item": resolved.finding_json})
                                    except ValueError as exc:
                                        sent["resolution_errors"].append({"item_type": field, "index": index, "error": str(exc)})
                            group["valid"] = not sent["resolution_errors"]
                            group["reason"] = None if group["valid"] else "resolution_error"
                            persist()
                            break
                        group["reason"] = "invalid_model_output"
                        persist()
                        if after_invalid_output(repairs, schema_repairs("owner_review")) == "store_unverified_draft":
                            break
                        repairs += 1
                        repair_issues = sent["issues"]
                persist()
                print(case["id"], row["valid"], row["reason"], json.dumps(row["screens"]), flush=True)
        except BaseException as exc:
            record["stop_reason"] = "runner_exception"
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            for case, row in zip(cases, rows):
                for group in row["groups"]:
                    if not group["valid"]:
                        if group["reason"] == "pending":
                            group["reason"] = record["stop_reason"] or "not_attempted"
                        row["not_reviewed"].extend({"group_index": group["group_index"],
                            "claim_ref": None, "section_ref": None, "source_id": sid, "reason": group["reason"]}
                            for sid in (group["source_ids"] or [None]))
            record["partial"] = record["stop_reason"] is not None
            persist()
            await adapter.close()
    print("wrote", out_file)
    return int(record["stop_reason"] is not None or any(not r["valid"] for r in rows))


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", default="claude")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--cases", help="comma-separated case IDs, run in frozen order")
    parser.add_argument("--only-build", action="store_true")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--max-sends", type=int, default=10)
    parser.add_argument("--expect-cases-sha256")
    parser.add_argument("--expect-expectations-sha256")
    args = parser.parse_args()
    return asyncio.run(main(args.model, set(args.cases.split(",")) if args.cases is not None else None,
        args.only_build, args.out_dir, connection=args.connection, effort=args.effort,
        max_sends=args.max_sends, expect_cases_sha256=args.expect_cases_sha256,
        expect_expectations_sha256=args.expect_expectations_sha256))


if __name__ == "__main__":
    raise SystemExit(cli())

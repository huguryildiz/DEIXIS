"""Bounded review-case runner; structural checks and screens do not judge support.

--only-build performs no adapter, directory or database operation.
Real sends require the two frozen hashes. Results retain invalid attempts.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from deixis.config import default_data_dir, load_settings
from deixis.domain import contracts, phrasebank
from deixis.domain.rules import after_invalid_output, schema_repairs
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import CodexAdapter, is_rate_limited
from deixis.paths import REPO_ROOT
from deixis.storage.db import new_id, now
from deixis.workflow import flow
from deixis.workflow.report.review import REVIEW_BUDGET_TOKENS
from deixis.workflow.review.run import plan_groups, request_chars, review_budget, review_step_input
from deixis.workflow.review.snapshot import _shown_passage
from deixis.workflow.review.store import resolve_finding

CASES = REPO_ROOT / "tests/model_behavior/review_cases.json"
EXPECTATIONS = REPO_ROOT / "docs/product/p8-review-expectations.md"
CASE_IDS = ("RB01", "RB02", "RB03", "RB04", "RB05", "PE2", "PE1", "RB06")
MAX_REQUEST_CHARS = REVIEW_BUDGET_TOKENS * 4
CALL_SHAPE_NOTES = [
    "Synthetic snapshot content instead of a database snapshot; no database or evidence-dependency reads.",
    "No durable send reservation, step rows, model sessions or atomic publication; JSON records replace them.",
    "No 24-hour review deadline, pause, resume, cancellation checkpoints or crash recovery.",
    "No shared model-call limiter or rate-limit resend; calls are serial and limits stop the runner.",
    "One runner-only before-send connection retry per attempt, counted against the send cap; same request/input.",
    "Health is refreshed once before the first send, rather than checked for each production logical step.",
    "Ordinary failed groups invalidate the case but later groups/cases continue; production may halt its run.",
    "Supported points and context limits resolve immediately here; production resolves these in its read model.",
    "Independent per-entry anchor audit and heuristic screens supplement production validation; no semantic judgement.",
    "Codex path guard loads settings with temporary data, then computes the environment-free default path without IO.",
]


def load_cases():
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in data["cases"]}
    if len(cases) != len(data["cases"]) or set(cases) != set(CASE_IDS):
        raise ValueError("case file must hold exactly RB01 to RB06, PE1 and PE2")
    return [cases[key] for key in CASE_IDS], data["sources"]


def synthetic_id(prefix, case_id, suffix="target"):
    return f"{prefix}_SYNB4{case_id}{suffix}"


def build_content(case, sources):
    cid, kind = case["id"], case["target_kind"]
    target_id = synthetic_id("ans" if kind == "answer" else "rpt", cid)
    content = {
        "version": 1, "research_id": synthetic_id("res", cid), "target_kind": kind,
        "target_id": target_id, kind + "_id": target_id, "research_title": "SYNTHETIC: " + case["title"],
        "scope_revision": 1, "scope": {"question": case["question"], "steering": None, "language": "en"},
        "report_version": 1, "status": "structurally_valid" if kind == "answer" else "valid", "language": "en",
        "claims": [], "sections": [], "cells": [], "columns": copy.deepcopy(case["columns"]),
        "sources": [], "passages": [], "evidence_manifest": [],
    }
    passages = {p["passage_id"]: p for p in case["passages"]}
    for index, claim in enumerate(case["claims"], 1):
        citations = []
        for link_index, citation in enumerate(claim["citations"], 1):
            anchor = (contracts.locate_anchor(citation["anchor_text"], passages[citation["passage_id"]]["text"])
                      if citation["anchor_text"] is not None and citation["passage_id"] else None)
            citations.append(copy.deepcopy(citation) | {
                "link_id": synthetic_id("evl", cid, f"{index:03d}{link_index:03d}"),
                "anchor_match": anchor.kind if anchor else None,
            })
        row = {k: copy.deepcopy(claim[k]) for k in ("claim_ref", "section_ref", "text", "support_type")}
        row.update(claim_id=synthetic_id("clm", cid, f"{index:03d}"), ordinal=index,
                   text_origin="model", citations=citations)
        if kind == "answer":
            row.update(label=claim["claim_ref"], section="answer")
        else:
            row.update(revision_id=None, version=1, table_ref=None, count=None)
        content["claims"].append(row)
    if kind == "report":
        content["table_id"] = synthetic_id("tbl", cid)
    for index, section in enumerate(case["sections"], 1):
        content["sections"].append(copy.deepcopy(section) | {
            "record_id": synthetic_id("rsc", cid, f"{index:03d}"),
            "claims": [copy.deepcopy(c) for c in content["claims"] if c["section_ref"] == section["section_ref"]],
        })
    columns = {c["column_id"]: c["name"] for c in case["columns"]}
    for cell in case["cells"]:
        row = {k: copy.deepcopy(v) for k, v in cell.items() if k != "source"}
        depths = ["abstract" if passages[e["passage_id"]]["kind"] == "abstract" else "selected_sections"
                  for e in cell["evidence"]]
        row.update(source_version_id=sources[cell["source"]]["source_id"],
                   column_name=columns[cell["column_id"]],
                   reading_depth="selected_sections" if "selected_sections" in depths else "abstract" if depths else "metadata")
        content["cells"].append(row)
    for p in sorted(case["passages"], key=lambda p: p["passage_id"]):
        content["passages"].append(_shown_passage({
            "id": p["passage_id"], "source_version_id": sources[p["source"]]["source_id"],
            "kind": p["kind"], "physical_page": p["physical_page"], "printed_label": None,
            "abstract_origin": "synthetic_fixture" if p["kind"] == "abstract" else None,
            "text_source": "text_layer", "text": p["text"],
        }))
    used = {p["source_id"] for p in content["passages"]} | {c["source_version_id"] for c in content["cells"]}
    for source in sorted(sources.values(), key=lambda s: s["source_id"]):
        if source["source_id"] in used:
            depths = {p["reading_depth"] for p in content["passages"] if p["source_id"] == source["source_id"]}
            content["sources"].append(copy.deepcopy(source) | {
                "reading_depth": "selected_sections" if "selected_sections" in depths else "abstract" if depths else "metadata",
            })
    # These synthetic records have no PDF assets or extraction identities.
    for p in content["passages"]:
        content["evidence_manifest"].append({
            "passage_id": p["passage_id"], "source_version_id": p["source_id"],
            "text_digest": hashlib.sha256(p["text"].encode()).hexdigest(),
            "asset_id": None, "asset_sha256": None, "extraction_version": None,
            "passage_extraction_id": None, "current_extraction_id_at_snapshot": None, "evidence_status": "current",
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
                             run_id=synthetic_id("run", case["id"]), step_id=step_id,
                             research_id=content["research_id"], package_hash=package.package_hash,
                             capabilities=flow.CAPABILITIES, budget=budget, step_input_id=new_id("sti"), created_at=now())


def build_request(payload, package, enforces_schema, repair_issues=None):
    task = "owner_review"
    schema = contracts.step_output_schema(task)
    developer = prompt.developer_instructions(package, task, phrasebank.frames_language(payload))
    if not enforces_schema:
        developer += "\n\n" + prompt.schema_appendix(task, schema)
    shown = contracts.with_citation_handles(payload)
    message = (prompt.step_message(shown) if repair_issues is None else
               prompt.repair_message(shown, contracts.issues_with_handles(payload, repair_issues)))
    return prompt.BASE_INSTRUCTIONS, developer, message, schema


def anchor_audit(payload, output):
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return {"parsed": False, "entries": [{"status": "unchecked", "reason": "unparsable_output"}]}
    if not isinstance(output, dict):
        return {"parsed": False, "entries": [{"status": "unchecked", "reason": "unparsable_output"}]}
    passages = {p["passage_id"]: p["text"] for p in payload["passages"]}
    entries = []
    for field in ("findings", "supported_points"):
        items = output.get(field)
        for index, item in enumerate(items if isinstance(items, list) else []):
            evidence = item.get("evidence") if isinstance(item, dict) else None
            for eindex, entry in enumerate(evidence if isinstance(evidence, list) else []):
                record = {"path": f"/{field}/{index}/evidence/{eindex}", "status": "unchecked", "reason": None,
                          "passage_id": None, "anchor": None, "match_kind": None}
                if (not isinstance(entry, dict) or not isinstance(entry.get("passage_handle"), str)
                        or not isinstance(entry.get("anchor"), str)):
                    record["reason"] = "missing_field"
                else:
                    pid, quote = entry["passage_handle"], entry["anchor"]
                    record.update(passage_id=pid, anchor=quote)
                    if pid not in passages or pid not in payload["allowlist"]["passage_ids"]:
                        record["reason"] = "passage_not_in_call"
                    else:
                        match = contracts.locate_anchor(quote, passages[pid])
                        record["match_kind"] = match.kind if match else None
                        record["status"] = "located" if match and match.kind in {"exact", "normalized"} else "not_located"
                entries.append(record)
    return {"parsed": True, "entries": entries}


def stop_for_result(result, model):
    if result.status == "isolation_violation":
        return "isolation_violation"
    if result.tool_item_types:
        return "tool_items"
    text = re.sub(r"[^a-z0-9]+", " ", (result.error or "").lower())
    if (is_rate_limited(result) or result.error_kind in {"quota_exhausted", "capacity", "overloaded"}
            or re.search(r"\b(?:quota|rate\s?limit\w*|429|usage\s?limit\w*|insufficient\s?quota|overload(?:ed)?|capacity)\b", text)):
        return "rate_quota_capacity_limit"
    if result.status == "completed" and (not model or result.resolved_model != model and not result.requested_model_verified):
        return "model_mismatch"
    if result.resolved_model is not None and result.resolved_model != model and not result.requested_model_verified:
        return "model_mismatch"
    return None


def screens(case, row):
    checks = dict.fromkeys(case["screens"])
    if case["id"] == "RB04":
        entries = [entry for group in row["groups"] for attempt in group["attempts"] if attempt["attempt"] == "first"
                   for entry in (attempt["anchor_audit"] or {}).get("entries", []) if entry["status"] != "unchecked"]
        checks["screen_first_attempt_anchors_located"] = all(e["status"] == "located" for e in entries) if entries else None
    if case["id"] == "RB06":
        checks["screen_plan_two_or_more_groups"] = len(row["plan"]["groups"]) >= 2
        checks["screen_iv1_not_reviewed"] = any(e["claim_ref"] == "IV.1" for e in row["plan"]["not_reviewed"])
    outputs = [g["output"] for g in row["groups"] if g["valid"]]
    if not outputs or len(outputs) != len(row["groups"]):
        return checks
    findings = [f for o in outputs for f in o["findings"]]
    supported = [f for o in outputs for f in o["supported_points"]]
    limits = [f for o in outputs for f in o["context_limits"]]
    targets = lambda items, ref: any(f["target_ref"] == {"kind": "claim", "ref": ref} for f in items)
    cid = case["id"]
    if cid == "RB01":
        checks["screen_no_negative_finding_on_c2"] = not targets(
            [f for f in findings if f["kind"] in {"unsupported", "partially_supported", "overstated"}], "c2")
        prose = [o["notes"] for o in outputs] + [f[k] or "" for f in findings
                 for k in ("rationale", "possible_impact", "suggested_fix", "uncertainty")] + [f["text"] for f in limits]
        checks["screen_no_peer_review_assertion_phrase"] = not any(
            phrase in text.lower() for text in prose for phrase in ("approved by peer review", "peer-reviewed"))
    if cid in {"RB02", "RB05"}:
        checks["screen_findings_empty"] = not findings
        if cid == "RB02":
            checks["screen_fewer_than_three_findings"] = len(findings) < 3
    if cid == "RB03":
        checks.update(screen_no_supported_point_c1=not targets(supported, "c1"),
                      screen_no_supported_point_c2=not targets(supported, "c2"),
                      screen_c1_addressed=targets(findings + limits, "c1"))
    if cid == "RB06":
        checks.update(screen_no_supported_point_iv2=not targets(supported, "IV.2"),
                      screen_iv2_addressed=targets(findings + limits, "IV.2"))
    return checks


def judgement_template(case, row):
    claims = {c["claim_ref"]: c for c in case["claims"]}
    items, findings = [], []
    for group in row["groups"]:
        output = group["output"]
        if output is None:
            continue
        for field in ("findings", "supported_points"):
            for index, item in enumerate(output[field]):
                ref = item["target_ref"]
                claim = claims.get(ref["ref"]) if ref["kind"] == "claim" else None
                handle = item.get("finding_handle", index)
                items.append({"case": case["id"], "group": group["group_index"], "handle": handle,
                              "item_type": field, "target_ref": ref, "kind": item.get("kind"),
                              "planted": bool(claim["plant"]) if claim else None, "judgement": None, "reason": None})
                if field == "findings":
                    findings.append({"group": group["group_index"], "handle": handle, "target_ref": ref,
                                     "kind": item["kind"], "rationale": item["rationale"],
                                     "possible_impact": item["possible_impact"], "suggested_fix": item["suggested_fix"]})
    planted = [{"claim_ref": c["claim_ref"], "plant": {"type": c["plant"]["type"]},
                "found_if": c["plant"]["found_if"], "findings": [f for f in findings
                if f["target_ref"] == {"kind": "claim", "ref": c["claim_ref"]}], "found": None}
               for c in case["claims"] if c["plant"]] if case["id"] in {"PE1", "PE2"} else []
    return {"planted_claims": planted, "items": items}


def summarize(cases, results):
    counters = {kind: {"parsed_attempts": 0, "checked": 0, "located": 0, "not_located": 0,
                       "unchecked": 0, "unchecked_reasons": {}} for kind in ("first", "repair")}
    planted, behavior = {}, {}
    for case, row in zip(cases, results, strict=True):
        for group in row["groups"]:
            for attempt in group["attempts"]:
                audit = attempt["anchor_audit"]
                if audit is None:
                    continue
                count = counters[attempt["attempt"]]
                count["parsed_attempts"] += int(audit["parsed"])
                for entry in audit["entries"]:
                    count[entry["status"]] += 1
                    if entry["status"] == "unchecked":
                        reason = entry["reason"]
                        count["unchecked_reasons"][reason] = count["unchecked_reasons"].get(reason, 0) + 1
                    else:
                        count["checked"] += 1
        if case["id"] in {"PE1", "PE2"}:
            refs = {ref for g in row["groups"] if g["valid"] for ref in g["claim_refs"]}
            planted[case["id"]] = {"case_valid": row["valid"], "claims": [
                {"claim_ref": c["claim_ref"], "plant_type": c["plant"]["type"] if c["plant"] else None,
                 "in_valid_group": c["claim_ref"] in refs, "eligible": row["valid"] and c["claim_ref"] in refs}
                for c in case["claims"]]}
        else:
            behavior[case["id"]] = {"valid": row["valid"], "reason": row["reason"], "screens": row["screens"],
                                     "findings": [f for g in row["groups"] if g["output"] for f in g["output"]["findings"]]}
    all_claims = [c for p in planted.values() for c in p["claims"]]
    attempts = [a for row in results for group in row["groups"] for a in group["attempts"] if a["sent"]]
    return {"anchors": counters, "planted_cases": planted, "behavior_cases": behavior,
            "calls": {"sends": len(attempts), "repair_sends": sum(a["attempt"] == "repair" for a in attempts),
                      "repairs_used": len({a["payload"]["step_input_id"] for a in attempts if a["attempt"] == "repair"}),
                      "failed_sends": sum(a["status"] != "completed" for a in attempts)},
            "denominators": {"planted_total": sum(c["plant_type"] is not None for c in all_claims),
                             "unplanted_total": sum(c["plant_type"] is None for c in all_claims),
                             "planted_eligible": sum(c["eligible"] and c["plant_type"] is not None for c in all_claims),
                             "unplanted_eligible": sum(c["eligible"] and c["plant_type"] is None for c in all_claims)}}


def _write_results(out_dir, payload, out_file=None):
    # ASCII escapes also retain invalid UTF-8 model strings for review without losing the failed attempt.
    body = json.dumps(payload, indent=2, ensure_ascii=True)
    if out_file is None:
        out_file = out_dir / "results.json"
        while True:
            try:
                with out_file.open("x"):
                    pass
                break
            except FileExistsError:
                out_file = out_dir / f"results-{datetime.now(timezone.utc):%H%M%S%f}.json"
    temp_path = None
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


def freeze_hashes():
    return {"cases": hashlib.sha256(CASES.read_bytes()).hexdigest(),
            "expectations": hashlib.sha256(EXPECTATIONS.read_bytes()).hexdigest()}


def provenance(hashes):
    def git(*args):
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.rstrip()
    return {"sha256": hashes, "head": git("rev-parse", "HEAD"),
            "status_porcelain": git("status", "--porcelain", "--", "backend", "contracts", "methods",
                                    "scripts/model_behavior", "tests/model_behavior", str(EXPECTATIONS.relative_to(REPO_ROOT)))}


def check_codex_home(path, allow_live):
    if path is None:
        raise ValueError("codex requires --codex-home")
    home = Path(path).expanduser().resolve()
    previous = os.environ.get("DEIXIS_DATA_DIR")
    try:
        os.environ["DEIXIS_DATA_DIR"] = "/tmp/p8b4-data"
        load_settings()
        os.environ.pop("DEIXIS_DATA_DIR", None)
        default = default_data_dir().resolve()
    finally:
        if previous is None:
            os.environ.pop("DEIXIS_DATA_DIR", None)
        else:
            os.environ["DEIXIS_DATA_DIR"] = previous
    roots = (Path.home() / "Library/Application Support/DEIXIS", default)
    if not allow_live and any(home.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("--codex-home is inside the live data directory")
    return home


def create_adapter(connection, codex_home, workspace):
    if connection == "codex":
        return CodexAdapter(codex_home, workspace, turn_timeout=300)
    from deixis.models.claude import ClaudeCodeAdapter
    return ClaudeCodeAdapter(workspace, turn_timeout=300)


async def main(model, selected=None, only_build=False, out_dir=None, codex_home=None, *,
               connection="claude", effort="medium", max_sends=20, expect_sha256=None,
               allow_live_codex_home=False, adapter_factory=create_adapter):
    try:
        if connection not in {"claude", "codex"} or not model or not 1 <= max_sends <= 20:
            raise ValueError("connection/model invalid or --max-sends outside 1..20")
        hashes = freeze_hashes()
        if not only_build and expect_sha256 != f"{hashes['cases']},{hashes['expectations']}":
            raise ValueError("--expect-sha256 is required and must match both frozen files")
        if connection == "codex":
            codex_home = check_codex_home(codex_home, allow_live_codex_home)
        cases, sources = load_cases()
        if selected is not None:
            if not selected or set(selected) - set(CASE_IDS):
                raise ValueError("--cases must select known case IDs")
            cases = [c for c in cases if c["id"] in selected]
        package = load_skill_package()
        triple = (connection, model, effort)
        contents = [build_content(c, sources) for c in cases]
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

    out_dir = REPO_ROOT / (out_dir or Path(f".local/p8-b4-{datetime.now(timezone.utc).date().isoformat()}"))
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
        adapter = adapter_factory(connection, codex_home, Path(workspace))
        try:
            for case, content in zip(cases, contents, strict=True):
                plan = plan_case(case, content, package, adapter.enforces_schema, triple)
                rows.append({"case_id": case["id"], "family": case["family"], "expected": case["expected"],
                             "failure_if": case["failure_if"], "observed_questions": case["observed_questions"],
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
                claims = {c["claim_ref"]: c for c in case["claims"]}
                for group in row["groups"]:
                    if not group["valid"]:
                        if group["reason"] == "pending":
                            group["reason"] = record["stop_reason"] or "not_attempted"
                        row["not_reviewed"].extend({"group_index": group["group_index"], "claim_ref": ref,
                                                    "section_ref": claims[ref]["section_ref"], "reason": group["reason"]}
                                                   for ref in group["claim_refs"])
            record["partial"] = record["stop_reason"] is not None
            persist()
            await adapter.close()
    print("wrote", out_file)
    return int(record["stop_reason"] is not None or any(not r["valid"] for r in rows))


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", choices=("claude", "codex"), default="claude")
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--cases", help="comma-separated case IDs, run in frozen order")
    parser.add_argument("--only-build", action="store_true")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--allow-live-codex-home", action="store_true")
    parser.add_argument("--max-sends", type=int, default=20)
    parser.add_argument("--expect-sha256", help="CASES_SHA,EXPECTATIONS_SHA; required for real sends")
    args = parser.parse_args()
    return asyncio.run(main(args.model, set(args.cases.split(",")) if args.cases is not None else None,
                            args.only_build, args.out_dir, args.codex_home, connection=args.connection,
                            effort=args.effort, max_sends=args.max_sends, expect_sha256=args.expect_sha256,
                            allow_live_codex_home=args.allow_live_codex_home))


if __name__ == "__main__":
    raise SystemExit(cli())

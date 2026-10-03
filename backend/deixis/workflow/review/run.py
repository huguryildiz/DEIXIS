"""Pure planning, frozen envelopes and read models for owner-requested reviews."""

from __future__ import annotations

import copy
import hashlib
import json
import re

from deixis.domain import contracts, phrasebank
from deixis.domain.canonical import sha256_hex
from deixis.domain.rules import MAX_RATE_LIMIT_MODEL_RETRIES, schema_repairs
from deixis.domain.skill import RUNTIME_FILES
from deixis.models import prompt
from .snapshot import ReviewInputTooLarge, review_step_input_parts
from .stale import claim_text_changed
from .store import resolve_finding

REVIEW_REQUEST_CHAR_LIMIT = 120_000
REVIEW_GROUP_CHAR_LIMIT = 96_000
REVIEW_MAX_PASSAGES = 48
REVIEW_DEADLINE_SECONDS = 24 * 60 * 60
PLAN_VERSION = 1
ASSESSMENT_NOTICE = "This is an assessment by a model. It is not peer review and not independent verification."
PLAN_TIME = "2000-01-01T00:00:00.000+00:00"


class ReviewDeadlinePassed(Exception):
    """The frozen wall-clock deadline permits no further sends."""


def request_chars(base, developer, message, schema, enforces_schema):
    return len(base) + len(developer) + len(message) + (
        len(json.dumps(schema, separators=(",", ":"), ensure_ascii=False)) if enforces_schema else 0)


def review_budget(groups):
    return {"max_model_calls": groups * (1 + schema_repairs("owner_review")) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES),
            "max_provider_requests": 0}


def review_step_input(snapshot_id, content, review_row, group, *, run_id, step_id, research_id,
                      package_hash, capabilities, budget, step_input_id, created_at):
    oversized = None
    try:
        parts = review_step_input_parts(snapshot_id, content, focus=review_row["focus"], owner_note=review_row["owner_note"],
            group_index=group["group_index"], group_count=group["group_count"], claim_refs=group["claim_refs"])
    except ReviewInputTooLarge as exc:
        oversized, parts = exc, exc.parts
    language = content["scope"]["language"]
    if not language or not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*", language):
        language = None
    caps = copy.deepcopy(capabilities)
    if "owner_review" not in caps["supported_tasks"]:
        caps["supported_tasks"].append("owner_review")
    payload = parts | {
        "step_input_id": step_input_id, "research_id": research_id, "run_id": run_id, "step_id": step_id,
        "task_type": "owner_review", "scope_revision": content["scope_revision"], "skill_package_hash": package_hash,
        "skill_files": list(RUNTIME_FILES["owner_review"]),
        "output_schema_versions": [contracts.SCHEMA_VERSIONS[o] for o in contracts.TASK_OUTPUTS["owner_review"]],
        "question": {"text": content["scope"]["question"], "language_hint": language},
        "user_steering": [content["scope"]["steering"]] if content["scope"]["steering"] else [],
        "capabilities": caps, "enabled_providers": [], "candidates": [], "human_corrections": [],
        "budget": budget | {"max_schema_repairs": schema_repairs("owner_review")},
        "model": {"connection": review_row["requested_connection"], "requested_model": review_row["requested_model"]},
        "created_at": created_at,
    }
    if oversized is not None:
        oversized.payload = payload
        raise oversized
    return payload


def first_request(payload, package, enforces_schema):
    schema = contracts.step_output_schema("owner_review")
    developer = prompt.developer_instructions(package, "owner_review", phrasebank.frames_language(payload))
    if not enforces_schema:
        developer += "\n\n" + prompt.schema_appendix("owner_review", schema)
    message = prompt.step_message(contracts.with_citation_handles(payload))
    return request_chars(prompt.BASE_INSTRUCTIONS, developer, message, schema, enforces_schema)


def _bound_reason(error):
    path = list(error.absolute_path)
    field = str(path[-1]) if path else "input"
    if error.validator == "maxItems":
        return "too_many_" + field
    if error.validator == "maxLength":
        if "claims" in path and field == "text":
            return "claim_text_too_long"
        return field + "_too_long"
    return "invalid_" + field


def plan_groups(snapshot_id, content, focus, owner_note, model, package, capabilities, *,
                enforces_schema=True, max_request_chars=REVIEW_REQUEST_CHAR_LIMIT):
    """Pack in stored order; check the entire closed envelope without shortening evidence."""
    group_limit = min(REVIEW_GROUP_CHAR_LIMIT, max_request_chars * 4 // 5)
    row = {"focus": focus, "owner_note": owner_note, "requested_connection": model[0], "requested_model": model[1]}

    def measure(refs, index, count):
        group = {"claim_refs": refs, "group_index": index, "group_count": count}
        try:
            payload = review_step_input(snapshot_id, content, row, group, run_id="run_" + "0" * 20,
                step_id="stp_" + "0" * 20, research_id=content["research_id"], package_hash=package.package_hash,
                capabilities=capabilities, budget=review_budget(count), step_input_id="sti_" + "0" * 20, created_at=PLAN_TIME)
        except ReviewInputTooLarge as exc:
            payload = exc.payload
            cell_too_large = True
        else:
            cell_too_large = False
        size = first_request(payload, package, enforces_schema)
        # check_step_input includes semantic bounds as well as the schema. The
        # validator supplies precise bound names for an unrepresentable single claim.
        issues = contracts.check_step_input(payload)
        reasons = [_bound_reason(e) for e in contracts.canonical_validator("StepInput").iter_errors(payload)]
        if cell_too_large:
            reasons = [r for r in reasons if r != "value_text_too_long"] + ["cell_value_too_large"]
        if len(payload["passages"]) > REVIEW_MAX_PASSAGES:
            reasons.append("too_many_passages")
        if issues and not reasons:
            reasons = [i.code for i in issues]
        if size > group_limit:
            reasons.append("claim_too_large")
        return size, list(dict.fromkeys(reasons)), len(payload["passages"])

    count_hint = 1
    for _ in range(len(content["claims"]) + 2):
        refs_groups, omitted, current = [], [], []
        for claim in content["claims"]:
            ref = claim["claim_ref"]
            size, reasons, _ = measure(current + [ref], len(refs_groups) + 1, count_hint)
            # Prospective indexes may exceed the current hint on this pass. That
            # envelope-only issue is resolved by the final-count pass below.
            reasons = [r for r in reasons if r != "review_group_out_of_range"]
            if current and reasons:
                refs_groups.append(current)
                current = []
                size, reasons, _ = measure([ref], len(refs_groups) + 1, count_hint)
                reasons = [r for r in reasons if r != "review_group_out_of_range"]
            if reasons:
                omitted.extend({"claim_ref": ref, "section_ref": claim["section_ref"], "reason": reason,
                                "request_chars": size} for reason in reasons)
            else:
                current.append(ref)
        if current:
            refs_groups.append(current)
        final_count = len(refs_groups)
        if final_count != count_hint and final_count:
            count_hint = final_count
            continue
        groups = []
        for index, refs in enumerate(refs_groups, 1):
            size, reasons, passages = measure(refs, index, final_count)
            if reasons:
                raise ValueError("review plan did not stabilize within its contract bounds")
            groups.append({"group_index": index, "group_count": final_count, "claim_refs": refs,
                           "request_chars": size, "passage_count": passages})
        return {"version": PLAN_VERSION, "groups": groups, "not_reviewed": omitted,
                "request_char_limit": max_request_chars, "group_char_limit": group_limit,
                "max_passages": REVIEW_MAX_PASSAGES}
    raise ValueError("review plan did not stabilize")


def preview_fingerprint(snapshot_sha256, model, focus, owner_note, package_hash, plan):
    return sha256_hex({"snapshot_sha256": snapshot_sha256, "connection": model[0], "model": model[1],
        "effort": model[2], "focus": focus, "owner_note": owner_note, "skill_package_hash": package_hash,
        "plan": plan, "plan_version": PLAN_VERSION})


def command_hash(route, research_id, target_kind, target_id, content):
    return sha256_hex({"route": route, "research_id": research_id, "target_kind": target_kind,
                       "target_id": target_id, "content": content})


def preview_numbers(content, plan):
    groups = plan["groups"]
    sent_refs = {r for g in groups for r in g["claim_refs"]}
    pids = set()
    for g in groups:
        parts = review_step_input_parts("rvs_" + "0" * 20, content, focus="source_support", owner_note=None,
            claim_refs=g["claim_refs"], group_index=g["group_index"], group_count=g["group_count"])
        pids.update(parts["allowlist"]["passage_ids"])
    sizes = [g["request_chars"] for g in groups]
    return {"claim_count": len(sent_refs), "passage_count": len(pids), "characters_to_be_sent": sum(sizes),
        "logical_steps": len(groups), "steps_with_repair_bound": len(groups) * (1 + schema_repairs("owner_review")),
        "total_send_bound": review_budget(len(groups))["max_model_calls"],
        "estimated_input_tokens_per_group": [s / 4 for s in sizes], "estimated_input_tokens_total": sum(sizes) / 4,
        "cost_estimated": False, "not_reviewed": plan["not_reviewed"]}


def review_state(run, review, reviewed_groups, planned_groups):
    status = run["status"]
    failure = run.get("pause_reason") if status == "failed" else review.get("failure_reason")
    if status == "completed":
        if not reviewed_groups:
            status, failure = "failed", "nothing_reviewed"
        elif reviewed_groups != planned_groups or json.loads(review["sections_not_reviewed_json"]):
            status = "partial"
    return {"state": status, "pause_reason": run.get("pause_reason"), "failure_reason": failure,
            "outcome_unknown": any(s["status"] == "outcome_unknown" for s in run.get("steps", []))}


def dependency_fingerprint(reader, content, claim_ref):
    claim = next(c for c in content["claims"] if c["claim_ref"] == claim_ref)
    report = reader.report(content["target_id"])
    live = next((c for c in reader.report_claims(report["id"]) if c["id"] == claim["claim_id"]), None)
    research = reader.research(content["research_id"])
    original = reader.report_original_links(claim["claim_id"])
    cell_ids = sorted({e["cell_id"] for e in original if e["cell_id"]})
    cells = reader.cells(cell_ids)
    # Original cell quotes belong to the report's frozen evidence, including
    # citations the editor currently omits but may restore on this save.
    frozen = json.loads(reader.report_snapshot(report["id"])["snapshot_json"])
    pids = {e["passage_id"] for e in original if e["passage_id"]}
    pids.update(e["passage_id"] for c in frozen["cells"] if c["cell_id"] in cell_ids for e in c["evidence"])
    dependencies = []
    for pid in sorted(pids):
        dep = reader.evidence_dependency(pid)
        dependencies.append({"passage_id": pid, "missing": True} if dep is None else {
            "passage_id": pid, "text_digest": hashlib.sha256(dep["text"].encode("utf-8")).hexdigest(),
            **{k: dep[k] for k in ("asset_id", "asset_sha256", "current_extraction_id_at_snapshot", "evidence_status")}})
    return sha256_hex({"report_id": report["id"], "report_version": report["report_version"], "status": report["status"],
        "claim_id": claim["claim_id"], "revision_id": live["current_revision_id"] if live else None,
        "version": live["version"] if live else None,
        "effective_link_ids": sorted(e["id"] for e in reader.report_links(report["id"]) if e["claim_id"] == claim["claim_id"]),
        "selection_revision": research["selection_revision"], "included_sources": sorted(reader.included_sources(content["research_id"])),
        "cells": {cid: cells[cid]["current_revision_id"] if cid in cells else None for cid in cell_ids},
        "dependencies": dependencies})


def review_read_model(review, snapshot, run, steps, inputs, sessions, findings, decisions, stale, *,
                      live_claims=None, dependency_fingerprints=None):
    """Assemble only rows supplied by the API; no writable store enters here."""
    run = run | {"steps": steps}
    content = snapshot["content"]
    reviewed = [s for s in steps if s["status"] == "succeeded" and s["operation_key"].startswith("owner_review:")]
    supported, limits = [], []
    for step in reviewed:
        out = step["output"]
        payload = inputs[out["step_input_id"]]
        for field, dest in (("supported_points", supported), ("context_limits", limits)):
            dest.extend(resolve_finding(content, payload, row).finding_json for row in out["result"][field])
    rows = []
    for row in findings:
        saved = row["finding"]
        ref = saved["target_ref"]
        history = decisions.get(row["id"], [])
        earlier = False
        if ref["kind"] == "claim":
            claim = next(c for c in content["claims"] if c["claim_ref"] == ref["ref"])
            earlier = claim_text_changed(claim, (live_claims or {}).get(claim["claim_id"]))
        rows.append(row | {"current_decision": history[-1] if history else None, "decision_history": history,
            "written_against_earlier_text": earlier,
            "dependency_fingerprint": (dependency_fingerprints or {}).get(ref["ref"])})
    succeeded_keys = {s["operation_key"] for s in reviewed}
    not_reviewed = json.loads(review["sections_not_reviewed_json"])
    groups = []
    for group in run["target"]["plan"]["groups"]:
        key = f"owner_review:{group['group_index']}"
        omitted = [r for r in not_reviewed if r.get("group_index") == group["group_index"]]
        groups.append(group | {"coverage": "reviewed" if key in succeeded_keys else "not_reviewed" if omitted else "pending",
                               "not_reviewed": omitted})
    answered = [{"step_id": s["step_id"], "step_input_id": s["step_input_id"], "connection": s["connection"],
                 "requested_model": inputs[s["step_input_id"]]["model"]["requested_model"],
                 "resolved_model": s["resolved_model"], "status": s["status"]} for s in sessions]
    return {"id": review["id"], "run_id": run["id"], **review_state(run, review, len(reviewed), len(groups)),
        "requested_model": {"connection": review["requested_connection"], "model": review["requested_model"],
                            "reasoning_effort": review["requested_effort"]}, "models_that_answered": answered,
        "focus": review["focus"], "owner_note": review["owner_note"], "created_at": review["created_at"],
        "snapshot": {k: snapshot[k] for k in ("id", "target_kind", "target_id", "content_sha256", "created_at")},
        "groups": groups, "not_reviewed": not_reviewed, "findings": rows,
        "finding_count": len(rows), "open_finding_count": sum(r["current_decision"] is None for r in rows),
        "supported_points": supported, "context_limits": limits, "stale_reasons": stale, "assessment_notice": ASSESSMENT_NOTICE}

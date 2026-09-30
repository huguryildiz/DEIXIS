"""One bounded model reading of stored report claims and their exact cited evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from deixis.workflow.flow import OptionalStepFailed
from deixis.workflow.report.selection import _estimated_tokens
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import NotFound

if TYPE_CHECKING:
    from deixis.workflow.flow import ResearchFlow


REVIEW_BUDGET_TOKENS = 30000


def _shown_passage(row: dict[str, Any]) -> dict[str, Any]:
    """The passage fields actually serialized in a review StepInput."""
    return {"passage_id": row["id"], "source_id": row["source_version_id"],
            "reading_depth": "abstract" if row["kind"] == "abstract" else "selected_sections",
            "locator": {"kind": row["kind"], "physical_page": row["physical_page"],
                        "printed_label": row["printed_label"]},
            "abstract_origin": row["abstract_origin"],
            "text_source": None if row["kind"] == "abstract" else row.get("text_source", "text_layer"),
            "text": row["text"]}


def _not_reviewed(reason: str, detail: Any, sections: list[str],
                  omitted: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"status": "not_reviewed", "reason": reason, "detail": detail,
            "sections_reviewed": [],
            "sections_not_reviewed": (omitted if omitted is not None else
                                      [{"section_id": section, "reason": reason} for section in sections]),
            "findings": [], "notes": "", "reverted": [], "not_reverted": []}


def _input(flow: ResearchFlow, reports: ReportStore, report_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[dict[str, str]]]:
    store = flow.store
    all_sections = [section for section in reports.sections(report_id) if section["section_id"] != "II"]
    snapshot = reports.snapshot(report_id)
    frozen_cells = {cell["cell_id"]: cell for cell in snapshot["cells"]}
    shown: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    passage_rows: dict[str, dict[str, Any]] = {}
    cells: dict[str, dict[str, Any]] = {}
    spent = 0
    for section in all_sections:
        claims = [dict(row) for row in store.conn.execute(
            "SELECT id, claim_key, text, support_type, table_ref, equation_ref, count_json"
            " FROM report_claims WHERE report_section_id = ? ORDER BY ordinal", (section["id"],))]
        if not claims:
            omitted.append({"section_id": section["section_id"], "reason": "no_claims"})
            continue
        section_passages: dict[str, dict[str, Any]] = {}
        section_cells: dict[str, dict[str, Any]] = {}
        unavailable = False
        review_claims = []
        for claim in claims:
            citations = []
            for link in store.conn.execute(
                "SELECT passage_id, cell_id, anchor_text FROM report_citation_links"
                " WHERE claim_id = ? ORDER BY rowid", (claim["id"],)):
                pid, cid = link["passage_id"], link["cell_id"]
                if cid is not None:
                    cell = frozen_cells.get(cid)
                    if cell is None:
                        unavailable = True
                        break
                    section_cells[cid] = cell
                    required = [e["passage_id"] for e in cell["evidence"]]
                elif pid is not None:
                    required = [pid]
                else:
                    unavailable = True
                    break
                for required_id in required:
                    try:
                        section_passages[required_id] = store.passage(required_id)
                    except NotFound:
                        unavailable = True
                        break
                if unavailable:
                    break
                citations.append({"passage_id": pid, "cell_id": cid, "anchor_text": link["anchor_text"]})
            if unavailable:
                break
            review_claims.append({"claim_key": claim["claim_key"], "text": claim["text"],
                                  "support_type": claim["support_type"], "table_ref": claim["table_ref"],
                                  "equation_ref": claim["equation_ref"],
                                  "count": json.loads(claim["count_json"]) if claim["count_json"] else None,
                                  "citations": citations})
        if unavailable:
            omitted.append({"section_id": section["section_id"], "reason": "passage_unavailable"})
            continue
        latest = {}
        for row in store.conn.execute(
            "SELECT sentence_id, before, after, outcome FROM report_phrase_repairs"
            " WHERE report_id = ? AND section_id = ? ORDER BY rowid", (report_id, section["section_id"]),
        ):
            latest[row["sentence_id"]] = row
        keys = {claim["claim_key"] for claim in claims}
        repairs = [{"sentence_id": row["sentence_id"], "before": row["before"], "after": row["after"]}
                   for row in latest.values() if row["outcome"] == "kept"
                   and row["sentence_id"].split("#", 1)[0] in keys]
        entry = {"section_id": section["section_id"], "claims": review_claims, "repairs": repairs}
        additional_passages = [row for pid, row in section_passages.items() if pid not in passage_rows]
        additional_cells = [row for cid, row in section_cells.items() if cid not in cells]
        cost = (_estimated_tokens(entry) + sum(_estimated_tokens(_shown_passage(row)) for row in additional_passages)
                + sum(_estimated_tokens(row) for row in additional_cells))
        if spent + cost > REVIEW_BUDGET_TOKENS:
            omitted.append({"section_id": section["section_id"], "reason": "input_too_large"})
            continue
        spent += cost
        shown.append(entry)
        passage_rows.update(section_passages)
        cells.update(section_cells)
    target = {"report_id": report_id, "section_id": None, "columns": snapshot["columns"], "plan": None,
              "cells": list(cells.values()), "gap_candidates": [], "prior_summaries": [],
              "repair_request": None, "review_scope": [entry["section_id"] for entry in shown],
              "review_sections": shown, "limitations_core": None}
    return target, list(passage_rows.values()), [section["section_id"] for section in all_sections], omitted


async def run_report_review(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any],
                            reports: ReportStore, report_id: str) -> None:
    """Record a model assessment; only a guarded support-broken finding can restore original wording."""
    section_ids = [section["section_id"] for section in reports.sections(report_id) if section["section_id"] != "II"]
    step = flow.store.step(run["id"], "report_review", "model:report_review")
    if step["status"] == "succeeded":
        output = step["output"]
    else:
        target, passages, _, omitted = _input(flow, reports, report_id)
        if not target["review_scope"]:
            # With no readable section, keep each input-pass omission reason; the record says size only if size excluded one.
            reason = "input_too_large" if any(item["reason"] == "input_too_large" for item in omitted) else "nothing_to_review"
            reports.save_review(report_id, _not_reviewed(reason, None, section_ids, omitted))
            return
        source_ids = list(dict.fromkeys(
            [row["source_version_id"] for row in passages]
            + [cell["source_version_id"] for cell in target["cells"]]))

        async def call() -> dict[str, Any]:
            return await flow._model_step(
                run, scope, "report_review", "report_review", source_ids=source_ids,
                passage_rows=passages, report_target=target, optional=True, limiter=flow.deps.limiter,
                step_output_extra={"sections_not_reviewed": omitted},
            )

        try:
            output = await flow.deps.limiter.run("report_review", call)
        except OptionalStepFailed as exc:
            flow._checkpoint(run["id"], run["scope_revision"])
            reports.save_review(report_id, _not_reviewed(exc.reason, exc.detail, section_ids))
            return
        flow._checkpoint(run["id"], run["scope_revision"])
        if output.get("invalid"):
            reports.save_review(report_id, _not_reviewed("invalid_model_output", output["issues"], section_ids))
            return

    payload = flow.store.step_input_payload(output["step_input_id"])
    target = payload["report_target"]
    shown = target["review_scope"]
    # The successful step committed the input-pass coverage with its model result; replay reads that same decision.
    omitted = output["sections_not_reviewed"]
    owners = {claim["claim_key"]: section["section_id"] for section in target["review_sections"]
              for claim in section["claims"]}
    repaired_owners = {repair["sentence_id"]: section["section_id"] for section in target["review_sections"]
                       for repair in section["repairs"]}
    findings = [finding | {"section_id": owners.get(finding["claim_key"]) if finding["claim_key"] else None}
                for finding in output["result"]["findings"]]
    reverted, not_reverted = [], []
    seen = set()
    for finding in findings:
        sentence = finding["sentence_id"]
        if finding["code"] != "support_broken" or sentence in seen:
            continue
        seen.add(sentence)
        section = repaired_owners[sentence]
        outcome = reports.revert_repair(report_id, section, sentence)
        item = {"sentence_id": sentence, "section_id": section}
        if outcome == "reverted":
            reverted.append(item)
        else:
            not_reverted.append(item | {"reason": outcome})
    record = {"status": "reviewed", "step_input_id": output["step_input_id"],
              "sections_reviewed": shown, "sections_not_reviewed": omitted,
              "findings": findings, "notes": output["result"]["notes"],
              "reverted": reverted, "not_reverted": not_reverted}
    reports.save_review(report_id, record)

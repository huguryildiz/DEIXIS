"""One bounded model reading of stored report claims and their exact cited evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from deixis.workflow.flow import OptionalStepFailed
from deixis.workflow.small_batch import save_code
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


def _batch_key(index: int) -> str:
    # Batch 0 keeps the single-step key, so a review stored before batching replays unchanged (D58).
    return "report_review" if index == 0 else f"report_review:{index}"


PLAN_KEY, PLAN_KIND = "report_review:plan", "code:report_review_plan"
Claim = tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]


def _read(flow: ResearchFlow, reports: ReportStore, report_id: str) -> tuple[dict[str, list[Claim]], list[str], list[dict[str, str]]]:
    """Each section's claims with their exact support; a cell citation is supported by its stored quotes (D58)."""
    store = flow.store
    all_sections = [section for section in reports.sections(report_id) if section["section_id"] != "II"]
    frozen_cells = {cell["cell_id"]: cell for cell in reports.snapshot(report_id)["cells"]}
    readable: dict[str, list[Claim]] = {}
    omitted: list[dict[str, str]] = []
    for section in all_sections:
        claims = [dict(row) for row in store.conn.execute(
            "SELECT id, claim_key, text, support_type, table_ref, equation_ref, count_json"
            " FROM report_claims WHERE report_section_id = ? ORDER BY ordinal", (section["id"],))]
        if not claims:
            omitted.append({"section_id": section["section_id"], "reason": "no_claims"})
            continue
        unavailable = False
        review_claims: list[Claim] = []
        for claim in claims:
            citations, claim_passages, claim_cells = [], {}, {}
            for link in store.conn.execute(
                "SELECT passage_id, cell_id, anchor_text FROM report_citation_links"
                " WHERE claim_id = ? ORDER BY rowid", (claim["id"],)):
                pid, cid = link["passage_id"], link["cell_id"]
                if cid is not None:
                    cell = frozen_cells.get(cid)
                    if cell is None:
                        unavailable = True
                        break
                    claim_cells[cid] = cell
                elif pid is not None:
                    try:
                        claim_passages[pid] = store.passage(pid)
                    except NotFound:
                        unavailable = True
                        break
                else:
                    unavailable = True
                    break
                citations.append({"passage_id": pid, "cell_id": cid, "anchor_text": link["anchor_text"]})
            if unavailable:
                break
            review_claims.append(({"claim_key": claim["claim_key"], "text": claim["text"],
                                   "support_type": claim["support_type"], "table_ref": claim["table_ref"],
                                   "equation_ref": claim["equation_ref"],
                                   "count": json.loads(claim["count_json"]) if claim["count_json"] else None,
                                   "citations": citations}, claim_passages, claim_cells))
        if unavailable:
            omitted.append({"section_id": section["section_id"], "reason": "passage_unavailable"})
        else:
            readable[section["section_id"]] = review_claims
    return readable, [section["section_id"] for section in all_sections], omitted


def _cost(batch: dict[str, Any], claims: list[Claim]) -> int:
    passages, cells = {}, {}
    for _, claim_passages, claim_cells in claims:
        passages.update({pid: row for pid, row in claim_passages.items() if pid not in batch["passages"]})
        cells.update({cid: row for cid, row in claim_cells.items() if cid not in batch["cells"]})
    return (_estimated_tokens({"section_id": "", "claims": [claim for claim, _, _ in claims]})
            + sum(_estimated_tokens(_shown_passage(row)) for row in passages.values())
            + sum(_estimated_tokens(row) for row in cells.values()))


def _batch() -> dict[str, Any]:
    return {"sections": [], "passages": {}, "cells": {}, "spent": 0}


def _place(batch: dict[str, Any], section_id: str, claims: list[Claim]) -> None:
    batch["spent"] += _cost(batch, claims)
    batch["sections"].append({"section_id": section_id, "claims": [claim for claim, _, _ in claims]})
    for _, claim_passages, claim_cells in claims:
        batch["passages"].update(claim_passages)
        batch["cells"].update(claim_cells)


def _pack(readable: dict[str, list[Claim]], omitted: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Sections in order into batches of at most the review budget; a section larger than one batch is split by claims,
    and only a single claim larger than one batch leaves its section out as input_too_large."""
    batches: list[dict[str, Any]] = []
    for section_id, claims in readable.items():
        if any(_cost(_batch(), [claim]) > REVIEW_BUDGET_TOKENS for claim in claims):
            omitted.append({"section_id": section_id, "reason": "input_too_large"})
            continue
        if not batches:
            batches.append(_batch())
        batch = batches[-1]
        if batch["spent"] + _cost(batch, claims) <= REVIEW_BUDGET_TOKENS:
            _place(batch, section_id, claims)
            continue
        if _cost(_batch(), claims) <= REVIEW_BUDGET_TOKENS:
            batches.append(_batch())
            _place(batches[-1], section_id, claims)
            continue
        part: list[Claim] = []
        for claim in claims:
            if part and batch["spent"] + _cost(batch, part + [claim]) > REVIEW_BUDGET_TOKENS:
                _place(batch, section_id, part)
                batches.append(_batch())
                batch, part = batches[-1], []
            elif not part and batch["spent"] + _cost(batch, [claim]) > REVIEW_BUDGET_TOKENS:
                batches.append(_batch())
                batch = batches[-1]
            part.append(claim)
        _place(batch, section_id, part)
    return batches


def _target(report_id: str, columns: list[dict[str, Any]], batch: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    shown = batch["sections"]
    return ({"report_id": report_id, "section_id": None, "columns": columns, "plan": None,
             "cells": list(batch["cells"].values()), "gap_candidates": [], "prior_summaries": [],
             "review_scope": [entry["section_id"] for entry in shown],
             "review_sections": shown, "limitations_core": None}, list(batch["passages"].values()))


def _input(flow: ResearchFlow, reports: ReportStore, report_id: str) -> tuple[list[tuple[dict[str, Any], list[dict[str, Any]]]], list[str], list[dict[str, str]]]:
    """The review batches as packed now: (target, passages) per batch, the section ids and the omissions."""
    readable, section_ids, omitted = _read(flow, reports, report_id)
    columns = reports.snapshot(report_id)["columns"]
    return [_target(report_id, columns, batch) for batch in _pack(readable, omitted)], section_ids, omitted


def _assigned(flow: ResearchFlow, reports: ReportStore, report_id: str, parts: list[dict[str, Any]],
              lost: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rebuild one stored batch from current claims; a section of it that can no longer be read is recorded in `lost`."""
    readable, _, omitted = _read(flow, reports, report_id)
    reasons = {item["section_id"]: item["reason"] for item in omitted}
    batch = _batch()
    for part in parts:
        claims = [claim for claim in readable.get(part["section_id"], []) if claim[0]["claim_key"] in part["claim_keys"]]
        if claims:
            _place(batch, part["section_id"], claims)
        else:
            lost.setdefault(part["section_id"], reasons.get(part["section_id"], "no_claims"))
    return _target(report_id, reports.snapshot(report_id)["columns"], batch)


def _step_input_id(flow: ResearchFlow, run_id: str, key: str) -> str | None:
    row = flow.store.conn.execute(
        "SELECT i.id FROM step_inputs i JOIN run_steps s ON s.id = i.step_id WHERE s.run_id = ? AND s.operation_key = ?"
        " ORDER BY i.attempt DESC, i.rowid DESC LIMIT 1", (run_id, key)).fetchone()
    return row["id"] if row is not None else None


async def run_report_review(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any],
                            reports: ReportStore, report_id: str) -> None:
    """Record a model assessment of the written sections; the review never changes the report."""
    section_ids = [section["section_id"] for section in reports.sections(report_id) if section["section_id"] != "II"]
    first = flow.store.step(run["id"], _batch_key(0), "model:report_review")
    if first["status"] == "succeeded" and "batch_count" not in first["output"]:
        # A review stored before D58 is one step; its output carries its own input-pass coverage.
        plan = {"sections_not_reviewed": first["output"]["sections_not_reviewed"], "batches": [[]]}
    else:
        def build() -> dict[str, Any]:
            readable, _, omitted = _read(flow, reports, report_id)
            return {"sections_not_reviewed": omitted,
                    "batches": [[{"section_id": entry["section_id"],
                                  "claim_keys": [claim["claim_key"] for claim in entry["claims"]]}
                                 for entry in batch["sections"]] for batch in _pack(readable, omitted)]}

        # The packing is stored before the first call, so a resumed review sends the batches it planned (D58).
        plan = save_code(flow, run, PLAN_KEY, PLAN_KIND, build)
    omitted, count = plan["sections_not_reviewed"], len(plan["batches"])
    if not count:
        # With no readable section, keep each input-pass omission reason; the record says size only if size excluded one.
        reason = "input_too_large" if any(item["reason"] == "input_too_large" for item in omitted) else "nothing_to_review"
        reports.save_review(report_id, _not_reviewed(reason, None, section_ids, omitted))
        return
    outputs: list[dict[str, Any]] = []
    failures: list[tuple[str, Any, list[str]]] = []
    lost: dict[str, str] = {}
    input_ids: list[str | None] = []
    for index in range(count):
        key = _batch_key(index)
        step = first if index == 0 else flow.store.step(run["id"], key, "model:report_review")
        if step["status"] == "succeeded":
            outputs.append(step["output"])
            input_ids.append(step["output"]["step_input_id"])
            continue
        target, passages = _assigned(flow, reports, report_id, plan["batches"][index], lost)
        if not target["review_scope"]:
            input_ids.append(None)
            continue
        source_ids = list(dict.fromkeys(
            [row["source_version_id"] for row in passages]
            + [cell["source_version_id"] for cell in target["cells"]]))

        async def call(key: str = key, target: dict[str, Any] = target, passages: list = passages,
                       source_ids: list[str] = source_ids) -> dict[str, Any]:
            return await flow._model_step(
                run, scope, key, "report_review", source_ids=source_ids,
                passage_rows=passages, report_target=target, optional=True, limiter=flow.deps.limiter,
                step_output_extra={"sections_not_reviewed": omitted, "batch_count": count},
            )

        try:
            output = await flow.deps.limiter.run(key, call)
        except OptionalStepFailed as exc:
            flow._checkpoint(run["id"], run["scope_revision"])
            failures.append((exc.reason, exc.detail, target["review_scope"]))
            input_ids.append(_step_input_id(flow, run["id"], key))
            continue
        flow._checkpoint(run["id"], run["scope_revision"])
        input_ids.append(output.get("step_input_id") or _step_input_id(flow, run["id"], key))
        if output.get("invalid"):
            failures.append(("invalid_model_output", output["issues"], target["review_scope"]))
            continue
        outputs.append(output)

    # A section keeps its input-pass reason, else the reason of the batch it failed in, else why it could not be read.
    not_reviewed = {item["section_id"]: item["reason"] for item in omitted}
    for reason, _, scope_ids in failures:
        for section_id in scope_ids:
            not_reviewed.setdefault(section_id, reason)
    for section_id, reason in lost.items():
        not_reviewed.setdefault(section_id, reason)
    coverage = [{"section_id": section_id, "reason": reason} for section_id, reason in not_reviewed.items()]
    if not outputs:
        reason, detail, _ = failures[0] if failures else ("nothing_to_review", None, [])
        record = _not_reviewed(reason, detail, section_ids, coverage)
        if input_ids:
            # Failed batches still sent (or built) inputs; the record keeps them as a successful review does.
            record |= {"step_input_id": input_ids[0], "step_input_ids": [i for i in input_ids if i is not None]}
        reports.save_review(report_id, record)
        return
    reviewed: list[str] = []
    findings: list[dict[str, Any]] = []
    notes = []
    for output in outputs:
        target = flow.store.step_input_payload(output["step_input_id"])["report_target"]
        reviewed += [section_id for section_id in target["review_scope"]
                     if section_id not in reviewed and section_id not in not_reviewed]
        owners = {claim["claim_key"]: section["section_id"] for section in target["review_sections"]
                  for claim in section["claims"]}
        findings += [finding | {"section_id": owners.get(finding["claim_key"]) if finding["claim_key"] else None}
                     for finding in output["result"]["findings"]]
        if output["result"]["notes"]:
            notes.append(output["result"]["notes"])
    record = {"status": "reviewed", "step_input_id": input_ids[0],
              "step_input_ids": [input_id for input_id in input_ids if input_id is not None],
              "sections_reviewed": reviewed, "sections_not_reviewed": coverage,
              "findings": findings, "notes": "\n\n".join(notes),
              # Kept empty for the UI and exports, which also show reviews from before D43 that reverted repairs.
              "reverted": [], "not_reverted": []}
    reports.save_review(report_id, record)

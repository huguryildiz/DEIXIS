"""Run report sections in dependency rounds over one frozen evidence snapshot."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from deixis.domain import contracts, phrasebank
from deixis.workflow.flow import OptionalStepFailed
from deixis.workflow.report import assembly, gaps, review_methodology, selection
from deixis.workflow.report.phrasing import flagged_sentences, repair_section
from deixis.workflow.report.plan import freeze_plan
from deixis.workflow.report.store import ReportStore
from deixis.workflow.tables import TableStore, report_ready

if TYPE_CHECKING:
    from deixis.workflow.flow import ResearchFlow


ROUNDS: tuple[tuple[str, ...], ...] = (
    ("III", "IV", "V"), ("VI",), ("VII",), ("VIII",), ("I", "IX", "abstract", "index_terms"),
)
ORDINALS = {"abstract": 0, "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
            "VII": 7, "VIII": 8, "IX": 9, "index_terms": 10}
_DEPTH_ORDER = {"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}


def _prior_summaries(flow: ResearchFlow, reports: ReportStore, report_id: str,
                     snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    cells = {cell["cell_id"]: cell for cell in snapshot.get("cells", [])}
    summaries = []
    for section in reports.sections(report_id):
        if section["status"] != "valid":
            continue
        claims = flow.store.conn.execute(
            "SELECT id, claim_key, text, support_type FROM report_claims"
            " WHERE report_section_id = ? ORDER BY ordinal", (section["id"],),
        )
        for claim in claims:
            depths = []
            for link in flow.store.conn.execute(
                "SELECT l.cell_id, p.kind AS passage_kind FROM report_citation_links l"
                " LEFT JOIN passages p ON p.id = l.passage_id WHERE l.claim_id = ?", (claim["id"],),
            ):
                if link["cell_id"]:
                    depth = cells.get(link["cell_id"], {}).get("reading_depth")
                else:
                    depth = "abstract" if link["passage_kind"] == "abstract" else "selected_sections"
                if depth in _DEPTH_ORDER:
                    depths.append(depth)
            sentences = phrasebank.sentences(claim["text"])
            summaries.append({
                "section_id": section["section_id"],
                "claim_key": claim["claim_key"],
                "first_sentence": sentences[0] if sentences else claim["text"],
                "support_type": claim["support_type"],
                "reading_depth": min(depths, key=_DEPTH_ORDER.__getitem__) if depths else "metadata",
            })
    return summaries


def _citation_links(payload: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    passages = {passage["passage_id"]: passage for passage in payload["passages"]}
    cells = {cell["cell_id"]: cell for cell in payload["report_target"]["cells"]}
    links = []
    for anchor in draft["citation_anchors"]:
        passage_id, cell_id = anchor["passage_id"], anchor["cell_id"]
        if passage_id is not None:
            record = passages[passage_id]
            source_version_id = record["source_id"]
            match = contracts.locate_anchor(anchor["quote"], record["text"])
        else:
            cell = cells[cell_id]
            source_version_id = cell["source_version_id"]
            stored_quote = " ".join(
                evidence["quote"] for evidence in cell.get("evidence", []) if evidence.get("quote")
            )
            match = contracts.locate_anchor(anchor["quote"], stored_quote)
        links.append({
            "claim_key": anchor["claim_key"],
            "passage_id": passage_id,
            "cell_id": cell_id,
            "source_version_id": source_version_id,
            "step_input_id": payload["step_input_id"],
            "anchor_text": anchor["quote"],
            "anchor_match": match.kind if match is not None else None,
        })
    return links


def _word_count(draft: dict[str, Any]) -> int:
    texts = [claim["text"] for claim in draft.get("claims", [])]
    texts.extend(item["reason"] for item in draft.get("insufficient_evidence", []))
    return sum(len(text.split()) for text in texts)


async def _run_section(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any], reports: ReportStore,
                       report_id: str, frozen_plan: dict[str, Any], snapshot: dict[str, Any],
                       section_id: str) -> str:
    section_key = reports.create_section(report_id, section_id, ORDINALS[section_id])
    section = reports.section(report_id, section_id)
    if section["status"] == "valid":
        return "valid"
    prior_summaries = _prior_summaries(flow, reports, report_id, snapshot)
    evidence = selection.select_evidence(flow.store, snapshot, section_id, frozen_plan, prior_summaries)
    gap_candidates = gaps.generate_corpus_absence_candidates(snapshot, frozen_plan.get("axes", [])) \
        if section_id == "VI" else []
    target = {
        "report_id": report_id,
        "section_id": section_id,
        "columns": snapshot["columns"],
        "plan": frozen_plan,
        "cells": evidence["cells"],
        "gap_candidates": gap_candidates,
        "prior_summaries": prior_summaries,
        "repair_request": None,
        "review_scope": None,
    }
    operation_key = f"report_section:{section_id}"
    step = flow.store.step(run["id"], operation_key, "model:report_section")
    reports.save_section_draft(
        section_key, step["id"], "running", None,
        {"ok": False, "issues": [], "truncated": evidence["truncated"]}, None,
    )

    async def call() -> dict[str, Any]:
        source_ids = list(dict.fromkeys(
            [passage["source_version_id"] for passage in evidence["passages"]]
            + [cell["source_version_id"] for cell in evidence["cells"]]
        ))
        return await flow._model_step(
            run, scope, operation_key, "report_section", source_ids=source_ids, passage_rows=evidence["passages"],
            report_target=target, optional=True, limiter=flow.deps.limiter,
        )

    try:
        output = await flow.deps.limiter.run(operation_key, call)
    except OptionalStepFailed as exc:
        reports.save_section_draft(
            section_key, step["id"], "failed", None,
            {"ok": False, "issues": [{"code": exc.reason, "detail": exc.detail}],
             "truncated": evidence["truncated"]}, None,
        )
        return "failed"
    if output.get("invalid"):
        reports.save_section_draft(
            section_key, step["id"], "failed", None,
            {"ok": False, "issues": output["issues"], "truncated": evidence["truncated"]}, None,
        )
        return "failed"

    draft = output["result"]
    payload = flow.store.step_input_payload(output["step_input_id"])
    empty = not draft["claims"] and not draft["insufficient_evidence"]
    language = phrasebank.frames_language(payload)
    flagged = flagged_sentences(
        section_id, [*draft["claims"], *draft["insufficient_evidence"]],
        flow.deps.package.files[phrasebank.PHRASEBANK], language,
    )
    draft, exceptions = await repair_section(flow, run, scope, report_id, section_id, draft, flagged)
    issues = ([{"code": "empty_section", "detail": "section has no claims or insufficient-evidence entries"}]
              if empty else exceptions)
    # A recorded phrase exception is an accepted evidence-first outcome; only an empty section remains a draft here.
    status = "draft" if empty else "valid"
    reports.save_claims(section_key, draft["claims"], _citation_links(payload, draft))
    reports.save_section_draft(
        section_key, step["id"], status, draft,
        {"ok": not empty, "issues": issues, "truncated": evidence["truncated"]}, _word_count(draft),
    )
    if section_id == "VI":
        candidate_ids = {candidate["gap_id"] for candidate in gap_candidates}
        persisted = []
        for gap in draft["gaps"]:
            # This three-field provenance shape is decided in P6 slice 1 P2, not in the plan.
            provenance = {"origin": "code" if gap["gap_id"] in candidate_ids else "model",
                          "section_id": "VI", "step_input_id": output["step_input_id"]}
            persisted.append(gap | {"provenance": provenance})
        reports.save_gaps(report_id, persisted)
    return status


async def run_report(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any]) -> None:
    """Run the frozen report plan, code-written methodology, section rounds and assembly checks."""
    run_id, research_id = run["id"], run["research_id"]
    table_id, report_id = run["target"]["table_id"], run["target"]["report_id"]
    tables, reports = TableStore(flow.store), ReportStore(flow.store)
    flow._checkpoint(run_id, run["scope_revision"])
    readiness = report_ready(flow.store, research_id, table_id)
    if not readiness["ready"]:
        flow._fail(run_id, "table_not_ready", readiness)
    snapshot = reports.save_snapshot(report_id, table_id)
    target = {"report_id": report_id, "section_id": None, "columns": snapshot["columns"], "plan": None, "cells": [],
              "gap_candidates": [], "prior_summaries": [], "repair_request": None, "review_scope": None}

    source_ids = [row["source_version_id"] for row in snapshot["rows"]]
    # One passage per source for the plan's vocabulary: the abstract, or the first PDF page when a source has
    # none (an attached-PDF research has no abstract at all, and an empty allowlist leaves the plan unwritable).
    plan_passages = []
    for source_id in source_ids:
        source_passages = flow.store.passages_for(source_id)
        passage = next((row for row in source_passages if row["kind"] == "abstract"), None)
        if passage is None:
            passage = next((row for row in source_passages if row["kind"] == "pdf_page"), None)
        if passage is not None:
            plan_passages.append(passage)
    max_passages = run["budget"].get("max_answer_passages")
    if max_passages is not None:
        plan_passages = plan_passages[:max_passages]

    async def plan_call() -> dict[str, Any]:
        return await flow._model_step(
            run, scope, "report_plan", "report_plan", source_ids=source_ids, passage_rows=plan_passages,
            report_target=target, limiter=flow.deps.limiter,
        )

    output = await flow.deps.limiter.run("report_plan", plan_call)
    flow._checkpoint(run_id, run["scope_revision"])
    if output.get("invalid"):
        flow._fail(run_id, "invalid_model_output", {"step": "report_plan", "issues": output["issues"]})
    frozen_plan = freeze_plan(output["result"], snapshot, len(tables.active_rows(table_id)))
    reports.set_plan(report_id, frozen_plan)

    if not flow.store.research(research_id)["title"]:
        # Section 15.1's title from the plan scope_statement is not implemented in this batch.
        try:
            async def title_call() -> None:
                await flow._research_title(run, scope, optional=True)

            await flow.deps.limiter.run("research_title", title_call)
        except OptionalStepFailed:
            pass
    review_methodology.write_review_methodology(flow.store, reports, report_id, research_id, snapshot)

    for round_ids in ROUNDS:
        flow._checkpoint(run_id, run["scope_revision"])
        results = await asyncio.gather(*(
            _run_section(flow, run, scope, reports, report_id, frozen_plan, snapshot, section_id)
            for section_id in round_ids
        ), return_exceptions=True)
        failure = next((result for result in results if isinstance(result, BaseException)), None)
        if failure is not None:
            raise failure
        flow._checkpoint(run_id, run["scope_revision"])
        if any(result == "draft" for result in results):
            flow._pause(run_id, "section_must_be_rewritten", {
                "sections": [section_id for section_id, result in zip(round_ids, results) if result == "draft"],
            })
        if any(result == "failed" for result in results):
            flow._pause(run_id, "section_failed", {
                "sections": [section_id for section_id, result in zip(round_ids, results) if result == "failed"],
            })

    issues = assembly.run_assembly_checks(flow.store, reports, report_id)
    errors = [issue for issue in issues if not (
        issue["rule"] == "glossary_term_before_definition_warning"
        and issue["detail"].startswith("WARNING:")
    )]
    if errors:
        reports.finalize(report_id, "draft")
        flow.store.update_run(run_id, event="report_assembly_failed", pause_reason=None, error_json=issues)
    else:
        reports.finalize(report_id, "valid")
        flow.store.update_run(run_id, event="report_finalized", pause_reason=None)
    # Report review is added by 1f; structural finalization does not wait for it in this batch.

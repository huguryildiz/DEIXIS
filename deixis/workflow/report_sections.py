"""Run report sections in dependency rounds over one frozen evidence snapshot."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from deixis.domain import contracts, wording
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import transaction
from deixis.workflow.equations import equation_fallback_field
from deixis.workflow.flow import OptionalStepFailed, RunStopped
from deixis.workflow import report_assembly as assembly, report_gaps as gaps, report_review_methodology as review_methodology, report_selection as selection
from deixis.workflow.report_plan import freeze_plan
from deixis.workflow.report_review import run_report_review
from deixis.workflow.report_store import ReportStore
from deixis.workflow.report_snapshot import countable_row_ids, evidence_row_ids
from deixis.workflow.store import NotFound
from deixis.workflow.tables import report_ready

if TYPE_CHECKING:
    from deixis.workflow.flow import ResearchFlow


def _report_checkpoint(flow: ResearchFlow, run: dict[str, Any]) -> None:
    flow._checkpoint(run["id"], run["scope_revision"])
    if flow.store.run(run["id"])["status"] == "paused":
        raise RunStopped


ROUNDS: tuple[tuple[str, ...], ...] = (
    ("III", "IV", "V"), ("VI",), ("VII",), ("VIII",), ("I", "IX", "abstract", "index_terms"),
)
ORDINALS = {"abstract": 0, "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
            "VII": 7, "VIII": 8, "IX": 9, "index_terms": 10}
MAX_BASIS_PASSAGE_CHARS = 150000
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
            sentences = wording.sentences(claim["text"])
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
        source_version_id = (passages[passage_id]["source_id"] if passage_id is not None
                             else cells[cell_id]["source_version_id"])
        match = contracts.locate_citation_anchor(anchor, passages, cells)
        links.append({
            "claim_key": anchor["claim_key"],
            "passage_id": passage_id,
            "cell_id": cell_id,
            "source_version_id": source_version_id,
            "step_input_id": payload["step_input_id"],
            "anchor_text": match.text if match is not None else anchor["quote"],
            "anchor_match": match.kind if match is not None else None,
        })
    return links


def _word_count(draft: dict[str, Any]) -> int:
    texts = [claim["text"] for claim in draft.get("claims", [])]
    texts.extend(item["reason"] for item in draft.get("insufficient_evidence", []))
    return sum(len(text.split()) for text in texts)


def _validation_context(flow: ResearchFlow, report_id: str, snapshot: dict, section_id: str) -> dict:
    """The whole frozen count domain and VII basis records, separate from citation allowlists."""
    accepted = []
    if section_id == "VII":
        for row in flow.store.conn.execute("SELECT gap_id, kind, text, basis_json FROM report_gaps WHERE report_id = ?", (report_id,)):
            basis = json.loads(row["basis_json"])
            accepted.append({name: row[name] for name in ("gap_id", "kind", "text")} |
                            {name: basis[name] for name in ("basis_claim_keys", "basis_passage_ids", "basis_cell_ids")})
    cell_ids = {cid for gap in accepted for cid in gap["basis_cell_ids"]}
    basis_cells = [c for c in snapshot["cells"] if c["cell_id"] in cell_ids]
    # D58: a basis cell carries its stored quotes; only pages a gap names directly are loaded, up to a cap. A page past
    # the cap stays named by id in its gap's basis_passage_ids.
    passage_ids = {pid for gap in accepted for pid in gap["basis_passage_ids"]}
    basis_passages, shown_chars = [], 0
    for pid in sorted(passage_ids):
        row = flow.store.conn.execute("SELECT * FROM passages WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise ValueError(f"accepted VI basis passage missing: {pid}")
        p = dict(row)
        if not selection.allowed_passage(snapshot, p):
            continue  # a page a frozen abstract-only row gained after the snapshot (D114)
        basis_passages.append({"passage_id": pid, "source_id": p["source_version_id"],
            "reading_depth": "abstract" if p["kind"] == "abstract" else "selected_sections",
            "locator": {"kind": p["kind"], "physical_page": p["physical_page"], "printed_label": p["printed_label"]},
            "abstract_origin": p["abstract_origin"], "text_source": None if p["kind"] == "abstract" else p["text_source"], "text": p["text"]}
            | equation_fallback_field(flow.store, p))
        shown_chars += len(json.dumps(basis_passages[-1], ensure_ascii=False, sort_keys=True))
        if shown_chars > MAX_BASIS_PASSAGE_CHARS:
            basis_passages.pop()
            break
    # Count members come from the frozen included rows only; a row read from its abstract only is never counted (D114).
    return {"source_ids": countable_row_ids(snapshot), "column_ids": [c["column_id"] for c in snapshot["columns"]],
            "cells": [{name: c[name] for name in ("cell_id", "source_version_id", "column_id", "state", "value", "reading_depth")}
                      for c in selection.usable_cells(snapshot)],
            "accepted_gaps": accepted, "basis_cells": basis_cells, "basis_passages": basis_passages}


LEGACY_SECTION_VERSION = "deixis.report_section_draft.v2"


def revalidate_section(payload: dict, draft: dict) -> contracts.ValidationReport:
    """Only VIII's code-rendered text is outside the model contract; retain the original input envelope."""
    model_draft = {key: value for key, value in draft.items() if key != "text"}
    # A draft stored before D40 is v2. v3 only adds `equation_ocr` to `equation_origin`, so a v2 draft is checked under v3's
    # rules with its version read as v3; the stored draft keeps its own version. New model output must say v3.
    if model_draft.get("schema_version") == LEGACY_SECTION_VERSION:
        model_draft["schema_version"] = contracts.SCHEMA_VERSIONS["ReportSectionDraft"]
    return contracts.validate_model_output(payload, model_draft)


def _pause_detail(reports: ReportStore, report_id: str, section_ids: list[str],
                  max_issues: int) -> dict[str, Any]:
    reasons = []
    for section_id in section_ids:
        issues = (reports.section(report_id, section_id)["validation"] or {}).get("issues") or []
        for issue in issues[:max_issues] or [{"code": "unknown", "detail": None}]:
            detail = issue.get("detail")
            if isinstance(detail, str):
                detail = detail[:300]
            elif isinstance(detail, dict):
                detail = {key: value[:300] if isinstance(value, str) else value
                          for key, value in detail.items()}
            reasons.append({"section_id": section_id, "code": issue.get("code") or "unknown",
                            "detail": detail})
    return {"sections": section_ids, "reasons": reasons}


def _gap_rows(draft: dict[str, Any], gap_candidates: list[dict[str, Any]], step_input_id: str) -> list[dict[str, Any]]:
    candidate_ids = {candidate["gap_id"] for candidate in gap_candidates}
    # This three-field provenance shape is decided in P6 slice 1 P2, not in the plan.
    return [gap | {"provenance": {"origin": "code" if gap["gap_id"] in candidate_ids else "model",
                                  "section_id": "VI", "step_input_id": step_input_id}}
            for gap in draft.get("gaps") or []]


def _restore_vi_gaps(flow: ResearchFlow, reports: ReportStore, report_id: str, frozen_plan: dict[str, Any],
                     snapshot: dict[str, Any], section: dict[str, Any]) -> None:
    """Write the gaps of a VI saved valid before its gaps were (a save split by a crash before the two were joined).

    Only when the report holds no gap row at all; rows that exist are never touched. They are rebuilt from the stored
    validated draft and its step's input, with the provenance the normal path writes.
    """
    draft = section["draft"] or {}
    step_input_id = (flow.store.step_output(section["step_id"]) or {}).get("step_input_id") if section["step_id"] else None
    if not draft.get("gaps") or step_input_id is None:
        return
    candidates = gaps.generate_corpus_absence_candidates(snapshot, frozen_plan.get("axes", []))
    with transaction(reports.conn):
        if reports.conn.execute("SELECT 1 FROM report_gaps WHERE report_id = ? LIMIT 1", (report_id,)).fetchone():
            return
        reports.save_gaps(report_id, _gap_rows(draft, candidates, step_input_id))


async def _run_section(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any], reports: ReportStore,
                       report_id: str, frozen_plan: dict[str, Any], snapshot: dict[str, Any],
                       section_id: str) -> str:
    section_key = reports.create_section(report_id, section_id, ORDINALS[section_id])
    section = reports.section(report_id, section_id)
    if section["status"] == "valid":
        if section_id == "VI":
            _restore_vi_gaps(flow, reports, report_id, frozen_plan, snapshot, section)
        return "valid"
    prior_summaries = _prior_summaries(flow, reports, report_id, snapshot)
    evidence = selection.select_evidence(flow.store, snapshot, section_id, frozen_plan, prior_summaries)
    gap_candidates = gaps.generate_corpus_absence_candidates(snapshot, frozen_plan.get("axes", [])) \
        if section_id == "VI" else []
    numbers = (review_methodology.limitations_core(flow.store, reports, report_id, snapshot)
               if section_id == "VIII" else None)
    target = {
        "report_id": report_id,
        "section_id": section_id,
        "columns": snapshot["columns"],
        "plan": frozen_plan,
        "cells": evidence["cells"],
        "gap_candidates": gap_candidates,
        "prior_summaries": prior_summaries,
        "review_scope": None,
        "limitations_core": numbers,
        "validation_context": None,
    }
    operation_key = f"report_section:{section_id}"
    step = flow.store.step(run["id"], operation_key, "model:report_section")
    reports.save_section_draft(
        section_key, step["id"], "running", None,
        {"ok": False, "issues": [], "truncated": evidence["truncated"],
         **({"numbers": numbers} if numbers is not None else {})}, None,
    )
    try:
        target["validation_context"] = _validation_context(flow, report_id, snapshot, section_id)
        oversized = len(json.dumps(target["validation_context"], ensure_ascii=False, sort_keys=True)) > contracts.MAX_REPORT_VALIDATION_CHARS
        if oversized:
            raise ValueError("frozen validation context exceeds 262144 characters; no truncation permitted")
    except ValueError as exc:
        code = "report_validation_context_too_large" if "exceeds" in str(exc) else "report_validation_context_invalid"
        issues = [{"code": code, "path": "/report_target/validation_context", "message": str(exc)}]
        flow.store.finish_step(step["id"], "failed", error_code=code, error=issues)
        reports.save_section_draft(section_key, step["id"], "failed", None,
                                  {"ok": False, "issues": issues, "truncated": evidence["truncated"]}, None)
        return "failed"

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
        _report_checkpoint(flow, run)
        reports.save_section_draft(
            section_key, step["id"], "failed", None,
            {"ok": False, "issues": [{"code": exc.reason, "detail": exc.detail}],
             "truncated": evidence["truncated"], **({"numbers": numbers} if numbers is not None else {})}, None,
        )
        return "failed"
    _report_checkpoint(flow, run)
    if output.get("invalid"):
        reports.save_section_draft(
            section_key, step["id"], "failed", None,
            {"ok": False, "issues": output["issues"], "truncated": evidence["truncated"],
             **({"numbers": numbers} if numbers is not None else {})}, None,
        )
        return "failed"

    draft = output["result"]
    payload = flow.store.step_input_payload(output["step_input_id"])
    validation = revalidate_section(payload, draft)
    if numbers is not None:
        language = (reports.report(report_id)["language"] or scope.get("language_hint") or "en").lower()
        draft["text"] = review_methodology.render_limitations(numbers, language)
    issues = [vars(issue) for issue in validation.issues]
    invalid = not validation.ok
    status = "failed" if invalid else "valid"
    reports.save_claims(section_key, draft["claims"], _citation_links(payload, draft))
    persisted = _gap_rows(draft, gap_candidates, output["step_input_id"]) if section_id == "VI" and not invalid else []
    # A valid VI and its gaps are saved together: a resumed run skips a valid section, so it would never write them.
    with transaction(reports.conn):
        reports.save_section_draft(
            section_key, step["id"], status, draft,
            {"ok": not invalid, "issues": issues, "truncated": evidence["truncated"],
             **({"numbers": numbers} if numbers is not None else {})}, _word_count(draft),
        )
        if persisted:
            reports.save_gaps(report_id, persisted)
    return status


async def run_report(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any]) -> None:
    """Run the frozen report plan, code-written methodology, section rounds and assembly checks."""
    run_id, research_id = run["id"], run["research_id"]
    table_id, report_id = run["target"]["table_id"], run["target"]["report_id"]
    reports = ReportStore(flow.store)
    flow._checkpoint(run_id, run["scope_revision"])
    # A resumed report goes on from the snapshot it saved: rows the table gained since (D63) are not its evidence.
    # Empty or unverified cells do not stop it; the snapshot's basis note says what each source was read from.
    try:
        snapshot = reports.snapshot(report_id)
    except NotFound:
        snapshot = None
    if snapshot is None:
        readiness = report_ready(flow.store, research_id, table_id)
        if not readiness["ready"]:
            flow._fail(run_id, "table_not_ready", readiness)
        try:
            snapshot = reports.save_snapshot(report_id, table_id)
        except RevisionConflict:
            flow._fail(run_id, "table_not_ready", report_ready(flow.store, research_id, table_id))
    target = {"report_id": report_id, "section_id": None, "columns": snapshot["columns"], "plan": None, "cells": [],
              "gap_candidates": [], "prior_summaries": [], "review_scope": None,
              "limitations_core": None}

    source_ids = evidence_row_ids(snapshot)
    # One passage per source for the plan's vocabulary: the abstract, or the first PDF page when a source has
    # none (an attached-PDF research has no abstract at all, and an empty allowlist leaves the plan unwritable).
    plan_passages = []
    for source_id in source_ids:
        source_passages = selection.row_passages(flow.store, snapshot, source_id)
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
    # The word budget counts the snapshot's rows, never the live table: a resumed report freezes the same plan (D63).
    frozen_plan = freeze_plan(output["result"], snapshot, snapshot.get("row_counts", {}).get("completed", len(snapshot["rows"])))
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
            section_ids = [section_id for section_id, result in zip(round_ids, results) if result == "draft"]
            flow._pause(run_id, "section_must_be_rewritten", _pause_detail(reports, report_id, section_ids, 3))
        if any(result == "failed" for result in results):
            section_ids = [section_id for section_id, result in zip(round_ids, results) if result == "failed"]
            flow._pause(run_id, "section_failed", _pause_detail(reports, report_id, section_ids, 1))

    issues = assembly.run_assembly_checks(flow.store, reports, report_id)
    errors = [issue for issue in issues if not (
        issue["rule"].endswith("_warning") and issue["detail"].startswith("WARNING:")
    )]
    if errors:
        reports.finalize(report_id, "draft")
        flow.store.update_run(run_id, event="report_assembly_failed", pause_reason=None, error_json=issues)
    else:
        reports.finalize(report_id, "valid")
        flow.store.update_run(run_id, event="report_finalized", pause_reason=None)
    flow._checkpoint(run_id, run["scope_revision"])
    await run_report_review(flow, run, scope, reports, report_id)
    flow._checkpoint(run_id, run["scope_revision"])

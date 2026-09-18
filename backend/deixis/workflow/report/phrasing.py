"""Phrasebank checks and one-shot targeted repair for report prose."""

from __future__ import annotations

import copy
import re
from collections import Counter
from typing import TYPE_CHECKING, Any

from deixis.domain import contracts, phrasebank
from deixis.workflow.flow import OptionalStepFailed
from deixis.workflow.report.store import ReportStore

if TYPE_CHECKING:
    from deixis.workflow.flow import ResearchFlow


def flagged_sentences(section_id: str, claims: list[dict[str, Any]],
                      phrasebank_text: str, language: str) -> list[dict[str, Any]]:
    """Return report sentences that follow no frame assigned to their section."""
    sections = phrasebank.REPORT_PHRASEBANK_SECTIONS[section_id]
    if not sections:
        return []
    fields: list[tuple[str, str, str]] = []
    insufficient_index = 0
    for claim in claims:
        if "text" in claim:
            fields.append((claim["claim_key"], claim["text"], claim["support_type"]))
        for entry in claim.get("insufficient_evidence", []):
            insufficient_index += 1
            fields.append((f"insufficient_evidence.{insufficient_index}", entry["reason"], "analyst_inference"))
        if "reason" in claim and "text" not in claim:
            insufficient_index += 1
            fields.append((f"insufficient_evidence.{insufficient_index}", claim["reason"], "analyst_inference"))

    flagged = []
    for claim_key, text, support_type in fields:
        claim_sentences = phrasebank.sentences(text)
        for index, sentence in enumerate(claim_sentences):
            if phrasebank.unframed(sentence, phrasebank_text, language, sections=sections):
                flagged.append({
                    "sentence_id": f"{claim_key}#{index + 1}",
                    "text": sentence,
                    "support_type": support_type,
                    "nearest_frames": phrasebank.nearest_frames(
                        sentence, phrasebank_text, language, sections=sections, k=3,
                    ),
                    "previous_sentence": claim_sentences[index - 1] if index else None,
                    "next_sentence": claim_sentences[index + 1] if index + 1 < len(claim_sentences) else None,
                })
    return flagged


def _location(draft: dict[str, Any], sentence_id: str) -> tuple[dict[str, Any], str, int] | None:
    owner_id, separator, order_text = sentence_id.rpartition("#")
    if not separator or not order_text.isdigit():
        return None
    order = int(order_text) - 1
    if owner_id.startswith("insufficient_evidence."):
        index_text = owner_id.removeprefix("insufficient_evidence.")
        if not index_text.isdigit():
            return None
        entries = draft.get("insufficient_evidence", [])
        index = int(index_text) - 1
        return (entries[index], "reason", order) if 0 <= index < len(entries) else None
    claim = next((item for item in draft.get("claims", []) if item["claim_key"] == owner_id), None)
    return (claim, "text", order) if claim is not None else None


def _exception(item: dict[str, Any], after: str, detail: str) -> dict[str, Any]:
    return {
        "code": "unframed_exception",
        "sentence_id": item["sentence_id"],
        "before": item["text"],
        "after": after,
        "detail": detail,
    }


async def repair_section(flow: ResearchFlow, run: dict[str, Any], scope: dict[str, Any],
                         report_id: str, section_id: str, draft: dict[str, Any],
                         flagged: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Attempt one targeted phrase repair and record every kept rewrite or allowed exception."""
    if not flagged:
        return draft, []

    reports = ReportStore(flow.store)
    report, snapshot = reports.report(report_id), reports.snapshot(report_id)
    target = {
        "report_id": report_id,
        "section_id": section_id,
        "columns": snapshot["columns"],
        "plan": report["plan"],
        "cells": [],
        "gap_candidates": [],
        "prior_summaries": [],
        "repair_request": {"section_id": section_id, "sentences": flagged},
        "review_scope": None,
    }
    operation_key = f"report_phrase_repair:{section_id}"

    async def factory() -> dict[str, Any]:
        return await flow._model_step(
            run, scope, operation_key, "report_phrase_repair", report_target=target,
            optional=True, limiter=flow.deps.limiter,
        )

    try:
        output = await flow.deps.limiter.run(operation_key, factory)
    except OptionalStepFailed as exc:
        exceptions = []
        for item in flagged:
            reports.save_phrase_repair(
                report_id, section_id, item["sentence_id"], item["text"], item["text"],
                "unframed_exception",
            )
            exceptions.append(_exception(item, item["text"], f"repair failed: {exc.reason}"))
        return draft, exceptions

    if output.get("invalid"):
        exceptions = []
        for item in flagged:
            reports.save_phrase_repair(
                report_id, section_id, item["sentence_id"], item["text"], item["text"],
                "unframed_exception",
            )
            exceptions.append(_exception(item, item["text"], "repair output was structurally invalid"))
        return draft, exceptions

    repaired = copy.deepcopy(draft)
    returned = {item["sentence_id"]: item["text"] for item in output["result"]["repairs"]}
    phrasebank_text = flow.deps.package.files[phrasebank.PHRASEBANK]
    language = phrasebank.frames_language(flow.store.step_input_payload(output["step_input_id"]))
    sections = phrasebank.REPORT_PHRASEBANK_SECTIONS[section_id]
    exceptions = []
    for item in flagged:
        replacement = returned.get(item["sentence_id"])
        location = _location(repaired, item["sentence_id"])
        if replacement is None or location is None:
            after = item["text"] if replacement is None else replacement
            detail = "the repair omitted this sentence" if replacement is None else "the sentence location no longer resolves"
            reports.save_phrase_repair(
                report_id, section_id, item["sentence_id"], item["text"], after, "unframed_exception",
            )
            exceptions.append(_exception(item, after, detail))
            continue

        owner, field, order = location
        sentences = phrasebank.sentences(owner[field])
        if not 0 <= order < len(sentences):
            reports.save_phrase_repair(
                report_id, section_id, item["sentence_id"], item["text"], replacement,
                "unframed_exception",
            )
            exceptions.append(_exception(item, replacement, "the sentence order no longer resolves"))
            continue
        before_owner = owner[field]
        candidate_sentences = list(sentences)
        candidate_sentences[order] = replacement
        after_owner = " ".join(candidate_sentences)
        same_numbers = Counter(re.findall(r"\d+(?:\.\d+)?", before_owner)) == Counter(
            re.findall(r"\d+(?:\.\d+)?", after_owner)
        )
        same_math = contracts._math_spans(before_owner) == contracts._math_spans(after_owner)
        if not (same_numbers and same_math):
            reports.save_phrase_repair(
                report_id, section_id, item["sentence_id"], item["text"], replacement,
                "unframed_exception",
            )
            exceptions.append(_exception(item, replacement, "the repair changed a number or math span"))
            continue

        owner[field] = after_owner
        remains_unframed = bool(phrasebank.unframed(replacement, phrasebank_text, language, sections=sections))
        outcome = "unframed_exception" if remains_unframed else "kept"
        reports.save_phrase_repair(
            report_id, section_id, item["sentence_id"], item["text"], replacement, outcome,
        )
        if remains_unframed:
            exceptions.append(_exception(item, replacement, "the repaired sentence still follows no assigned frame"))
    return repaired, exceptions

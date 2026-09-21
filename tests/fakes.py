"""Test-only model adapter. Never registered by the live application."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

from deixis.models.adapter import ModelStepResult


def parse_step_input(message: str) -> dict[str, Any]:
    return json.loads(re.search(r"<step-input>\n(.*)\n</step-input>", message, re.DOTALL).group(1))


def envelope(si: dict[str, Any], version: str) -> dict[str, Any]:
    return {"schema_version": version, "step_input_id": si["step_input_id"], "scope_revision": si["scope_revision"],
            "skill_package_hash": si["skill_package_hash"]}


def valid_response(si: dict[str, Any]) -> str:
    task = si["task_type"]
    if task == "search_plan":
        plan = envelope(si, "deixis.search_plan.v2") | {
            "question_interpretation": "fake interpretation",
            "concepts": [{"label": "molecular communication", "role": "core", "synonyms": ["molecular communication", "diffusion channel"]},
                         {"label": "optimization", "role": "method", "synonyms": ["optimization"]}],
            "providers": si["enabled_providers"][:1],
            "scope_boundaries": ["fake"], "search_rationale": "fake",
        }
        return json.dumps({"search_plan": plan, "clarification_request": None})
    if task == "screening":
        return json.dumps(envelope(si, "deixis.screening_proposal.v1") | {
            "decisions": [{"candidate_id": c["candidate_id"], "proposal": "include", "reason": "fake include", "evidence_basis": "title_and_abstract"}
                          for c in si["candidates"]],
            "notes": "fake screening notes.",
        })
    if task == "abstract_screening":
        # SYNTHETIC and field-independent: every record with an abstract is a candidate quoted from its own first
        # words, so the quote always locates and the two runs always agree. It says nothing about model behavior.
        return json.dumps(envelope(si, "deixis.abstract_screening.v1") | {"records": [
            {"candidate_id": c["candidate_id"],
             "label": "candidate" if c["abstract"] else "unresolved",
             "quote": " ".join((c["abstract"] or "").split())[:60],
             "rationale": "SYNTHETIC: the abstract names the question's setting and task."}
            for c in si["candidates"]]})
    if task == "cell_extraction":
        first = si["passages"][0]
        values = {"choice": lambda c: {"option_ids": [c["options"][0]["id"]]}, "number_unit": lambda c: {"number": 128, "unit": "byte", "as_stated": None},
                  "yes_no": lambda c: {"answer": "yes"}, "text": lambda c: {"text": "SYNTHETIC fake value"}}
        return json.dumps(envelope(si, "deixis.evidence_cell_draft.v1") | {"cells": [
            {"column_id": c["column_id"], "state": "value", "value": values[c["answer_format"]](c), "note": None,
             "evidence": [{"passage_id": first["passage_id"], "quote": " ".join(first["text"].split())[:600]}]}
            for c in si["extraction_target"]["columns"]
        ]})
    if task == "table_columns":
        return json.dumps(envelope(si, "deixis.table_column_proposal.v1") | {
            "columns": [{"name": "SYNTHETIC method", "instruction": "Name the method the source uses, as stated.", "answer_format": "text",
                         "options": None, "allow_multiple": False, "unit_hint": None, "rationale": "fake rationale"}],
            "notes": "",
        })
    if task == "answer_review":
        return json.dumps(envelope(si, "deixis.answer_review.v1") | {
            "reviews": [{"claim_label": c["claim_label"], "verdict": "supported", "reason": "fake: the cited passage states it."}
                        for c in si["claims_under_review"]],
            "notes": "",
        })
    if task == "research_title":
        return json.dumps(envelope(si, "deixis.research_title.v1") | {"title": "Synthetic short research title"})
    if task == "vocabulary_labels":
        return json.dumps(envelope(si, "deixis.vocabulary_labels.v1") | {
            "labels": [{"phrase": p["phrase"], "block": p["rule_block"]} for p in si["vocabulary_target"]["phrases"]],
        })
    if task == "criterion_proposal":
        # SYNTHETIC and field-independent: three identical runs, so the consensus keeps every phrase.
        return json.dumps(envelope(si, "deixis.criterion_proposal.v1") | {
            "criterion": "SYNTHETIC: the paper puts forward a method of its own and reports a measured outcome.",
            "parts": [
                {"name": "method of its own",
                 "definition": "SYNTHETIC: the paper specifies the method it applies rather than citing one.",
                 "phrases": ["we propose", "our method", "proposed scheme", "we formulate", "the algorithm",
                             "our approach"]},
                {"name": "measured outcome",
                 "definition": "SYNTHETIC: the paper reports a value it measured.",
                 "phrases": ["we measure", "results show", "measured value", "reported outcome",
                             "experimental results", "we evaluate"]},
            ],
            "exclusion_title_words": ["tutorial", "roadmap"],
        })
    if task == "term_suggestions":
        # SYNTHETIC and field-independent: one other name for the first anchor of the target, so a flow test gets a
        # proposal whose text says nothing about any field and nothing about model behavior.
        given = si["suggestion_target"]["phrases"]
        return json.dumps(envelope(si, "deixis.term_suggestions.v1") | {
            "terms": [{"phrase": "synthetic other name", "synonym_of": given[0]["phrase"]}] if given else []})
    if task == "report_plan":
        passage_ids = si["allowlist"]["passage_ids"]
        column_ids = si["allowlist"]["column_ids"]
        return json.dumps(envelope(si, "deixis.report_plan_draft.v2") | {
            "scope_statement": "SYNTHETIC scope covering release scheduling formulations in molecular communication.",
            "research_questions": [
                {"rq_id": "RQ1", "text": "SYNTHETIC: what decision variables are used?"},
                {"rq_id": "RQ2", "text": "SYNTHETIC: what constraints are reported?"},
            ],
            "glossary": ([{"term": "release scheduling", "definition": "SYNTHETIC definition.",
                           "passage_id": passage_ids[0]}] if passage_ids else []),
            "axes": ([{"axis_id": "AX1", "label": si["report_target"]["columns"][0]["name"],
                       "column_id": column_ids[0]}] if column_ids else []),
            "limitations_column_id": column_ids[0] if column_ids else None,
            "future_work_column_id": column_ids[0] if column_ids else None,
        })
    if task == "report_section":
        if not si["passages"]:
            return json.dumps(envelope(si, "deixis.report_section_draft.v1") | {
                "section_id": si["report_target"]["section_id"], "claims": [], "citation_anchors": [],
                "subsections": [], "gaps": [],
                "insufficient_evidence": [{"context": si["report_target"]["section_id"],
                                           "reason": "It is beyond the scope of this synthetic fixture to add a claim."}],
            })
        first = si["passages"][0]
        return json.dumps(envelope(si, "deixis.report_section_draft.v1") | {
            "section_id": si["report_target"]["section_id"],
            "claims": [{"claim_key": f"{si['report_target']['section_id']}.1", "text": "It has been reported that the fake claim holds.",
                        "support_type": "source_stated", "passage_ids": [first["passage_id"]], "cell_ids": [], "paragraph": 1,
                        "table_ref": None, "equation_ref": None, "body_refs": [], "axis_id": None, "count": None,
                        "equation_origin": None, "gap_refs": []}],
            "citation_anchors": [{"claim_key": f"{si['report_target']['section_id']}.1", "passage_id": first["passage_id"],
                                  "cell_id": None, "quote": " ".join(first["text"].split())[:600]}],
            "subsections": [], "gaps": [], "insufficient_evidence": [],
        })
    if task == "report_phrase_repair":
        return json.dumps(envelope(si, "deixis.report_phrase_repair_draft.v1") | {
            "repairs": [{"sentence_id": r["sentence_id"], "text": "It has been reported that the rewritten sentence holds."}
                        for r in si["report_target"]["repair_request"]["sentences"]],
        })
    if task == "report_review":
        return json.dumps(envelope(si, "deixis.report_review.v1") | {"findings": [], "notes": ""})
    if task == "fulltext_adjudication":
        # Every part present, quoting the first passage, so two runs agree and the quote verifies.
        passage = si["passages"][0]
        quote = passage["text"][:60]
        return json.dumps(envelope(si, "deixis.fulltext_adjudication.v1") | {
            "parts": [{"part": part["name"], "label": "present", "quote": quote,
                       "passage_id": passage["passage_id"],
                       "rationale": "SYNTHETIC: the shown passage states this part."}
                      for part in si["adjudication_target"]["parts"]],
        })
    first = si["passages"][0]
    return json.dumps(envelope(si, "deixis.grounded_answer_draft.v3") | {
        "title": "Synthetic evidence for release scheduling and optimization in constrained molecular communication networks",
        "answer_language": "en",
        "claims": [{"claim_label": "c1", "section": "Overview", "text": "It has been reported that the first passage supports this fake claim.", "support_type": "source_stated", "passage_ids": [first["passage_id"]]}],
        "citation_anchors": [{"claim_label": "c1", "passage_id": first["passage_id"], "quote": " ".join(first["text"].split())[:600]}],
        "limitations": [{"kind": "scope", "text": "It is beyond the scope of this answer to examine the fake scope.", "source_ids": [first["source_id"]]}],
        "unanswered_aspects": [], "capability_notice": None,
    })


class FakeAdapter:
    connection = "fake"

    def __init__(self, responder: Callable[[dict[str, Any]], str] = valid_response, ready: bool = True,
                 resolved_model: str | None = None, models: list[str] | None = None, efforts: list[str] | None = None,
                 delay: float = 0.0, before: Callable[[dict[str, Any]], None] | None = None,
                 fail: Callable[[dict[str, Any]], "ModelStepResult | None"] | None = None):
        self.responder = responder
        self.ready = ready
        self.resolved_model = resolved_model  # None: answer with the requested model, as a correct connection does
        self.models = models
        self.efforts = efforts or []
        self.delay = delay
        self.before = before
        self.fail = fail
        self.calls: list[dict[str, Any]] = []
        self.sent_efforts: list[str | None] = []
        self.sent: list[tuple[str, str | None, str | None]] = []  # (task type, requested model, reasoning effort) per call
        self.current = 0
        self.max_concurrent = 0

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        status = {"connection": "fake", "ready": self.ready, "reason": None if self.ready else "fake not ready"}
        if self.models is not None:
            status["models"] = [{"id": m, "display_name": m, "is_default": False,
                                 "reasoning_efforts": [{"id": e, "description": ""} for e in self.efforts]} for m in self.models]
        return status

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None) -> ModelStepResult:
        si = parse_step_input(message)
        self.calls.append(si)
        self.sent_efforts.append(reasoning_effort)
        self.sent.append((si["task_type"], requested_model, reasoning_effort))
        if self.before:
            self.before(si)
        self.current += 1
        self.max_concurrent = max(self.max_concurrent, self.current)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail and (result := self.fail(si)) is not None:
                return result
            return ModelStepResult("completed", raw_text=self.responder(si), resolved_model=self.resolved_model or requested_model)
        finally:
            self.current -= 1

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        pass

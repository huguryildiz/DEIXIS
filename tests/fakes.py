"""Test-only model adapter. Never registered by the live application."""

from __future__ import annotations

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
        plan = envelope(si, "deixis.search_plan.v1") | {
            "question_interpretation": "fake interpretation",
            "concepts": [{"label": "molecular communication", "role": "core", "synonyms": ["diffusion channel"]}],
            "queries": [{"provider_id": p, "query_text": '"molecular communication" AND optimization', "rationale": "fake"} for p in si["enabled_providers"]][:1],
            "scope_boundaries": ["fake"], "search_rationale": "fake",
        }
        return json.dumps({"search_plan": plan, "clarification_request": None})
    if task == "screening":
        return json.dumps(envelope(si, "deixis.screening_proposal.v1") | {
            "decisions": [{"candidate_id": c["candidate_id"], "proposal": "include", "reason": "fake include", "evidence_basis": "title_and_abstract"}
                          for c in si["candidates"]],
            "notes": "fake screening notes.",
        })
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
                 resolved_model: str | None = None, models: list[str] | None = None, efforts: list[str] | None = None):
        self.responder = responder
        self.ready = ready
        self.resolved_model = resolved_model  # None: answer with the requested model, as a correct connection does
        self.models = models
        self.efforts = efforts or []
        self.calls: list[dict[str, Any]] = []
        self.sent_efforts: list[str | None] = []
        self.sent: list[tuple[str, str | None, str | None]] = []  # (task type, requested model, reasoning effort) per call

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
        return ModelStepResult("completed", raw_text=self.responder(si), resolved_model=self.resolved_model or requested_model)

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        pass

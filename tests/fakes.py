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
            "queries": [{"provider_id": p, "query_text": "molecular communication optimization", "rationale": "fake"} for p in si["enabled_providers"]][:1],
            "scope_boundaries": ["fake"], "search_rationale": "fake",
        }
        return json.dumps({"search_plan": plan, "clarification_request": None})
    if task == "screening":
        return json.dumps(envelope(si, "deixis.screening_proposal.v1") | {
            "decisions": [{"candidate_id": c["candidate_id"], "proposal": "include", "reason": "fake include", "evidence_basis": "title_and_abstract"}
                          for c in si["candidates"]],
            "notes": "",
        })
    first = si["passages"][0]
    return json.dumps(envelope(si, "deixis.grounded_answer_draft.v1") | {
        "answer_language": "en",
        "claims": [{"claim_label": "c1", "text": "Fake claim from the first passage.", "support_type": "source_stated", "passage_ids": [first["passage_id"]]}],
        "limitations": [{"kind": "scope", "text": "fake", "source_ids": [first["source_id"]]}],
        "unanswered_aspects": [], "capability_notice": None,
    })


class FakeAdapter:
    connection = "fake"

    def __init__(self, responder: Callable[[dict[str, Any]], str] = valid_response, ready: bool = True):
        self.responder = responder
        self.ready = ready
        self.calls: list[dict[str, Any]] = []

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        return {"connection": "fake", "ready": self.ready, "reason": None if self.ready else "fake not ready"}

    async def run_step(self, base, developer, message, output_schema, requested_model) -> ModelStepResult:
        si = parse_step_input(message)
        self.calls.append(si)
        return ModelStepResult("completed", raw_text=self.responder(si), resolved_model="fake-model")

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        pass

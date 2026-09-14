"""Canonical JSON Schema contracts and deterministic model-output checks.

These checks establish structural validity, identifier scope and envelope
consistency. They do not establish that a passage semantically supports a claim.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from deixis.paths import CONTRACTS_DIR

SCHEMA_FILES = {
    "SearchPlan": "search-plan.schema.json",
    "ScreeningProposal": "screening-proposal.schema.json",
    "GroundedAnswerDraft": "grounded-answer-draft.schema.json",
    "ClarificationRequest": "clarification-request.schema.json",
    "StepInput": "step-input.schema.json",
}
SCHEMA_VERSIONS = {
    "SearchPlan": "deixis.search_plan.v1",
    "ScreeningProposal": "deixis.screening_proposal.v1",
    "GroundedAnswerDraft": "deixis.grounded_answer_draft.v1",
    "ClarificationRequest": "deixis.clarification_request.v1",
}
# Model outputs each task may return. More than one output type is wrapped in an
# object with one nullable property per type; exactly one must be non-null.
TASK_OUTPUTS = {
    "search_plan": ("SearchPlan", "ClarificationRequest"),
    "screening": ("ScreeningProposal",),
    "grounded_answer": ("GroundedAnswerDraft",),
}
WRAPPER_KEYS = {
    "SearchPlan": "search_plan",
    "ClarificationRequest": "clarification_request",
}
COMMON_REF_PREFIX = "common.schema.json#/$defs/"
ENVELOPE_FIELDS = ("step_input_id", "scope_revision", "skill_package_hash")


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


@cache
def _common_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "common.schema.json").read_text(encoding="utf-8"))


def _registry() -> Registry:
    resources = [(CONTRACTS_DIR / "common.schema.json", _common_schema())]
    resources += [(CONTRACTS_DIR / f, load_schema(n)) for n, f in SCHEMA_FILES.items()]
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for _, schema in resources
    )


def canonical_validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name), registry=_registry())


def _inline_common_refs(node: Any, used: set[str]) -> Any:
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(COMMON_REF_PREFIX):
                name = value.removeprefix(COMMON_REF_PREFIX)
                used.add(name)
                out[key] = f"#/$defs/{name}"
            else:
                out[key] = _inline_common_refs(value, used)
        return out
    if isinstance(node, list):
        return [_inline_common_refs(v, used) for v in node]
    return node


def _strip_meta(schema: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in schema.items() if k not in ("$schema", "$id", "title")}


def step_output_schema(task_type: str) -> dict[str, Any]:
    """Self-contained schema given to the model for one step (no external refs)."""
    outputs = TASK_OUTPUTS[task_type]
    used: set[str] = set()
    if len(outputs) == 1:
        root = _inline_common_refs(_strip_meta(copy.deepcopy(load_schema(outputs[0]))), used)
    else:
        root = {
            "type": "object",
            "additionalProperties": False,
            "required": [WRAPPER_KEYS[o] for o in outputs],
            "properties": {
                WRAPPER_KEYS[o]: {
                    "anyOf": [
                        _inline_common_refs(_strip_meta(copy.deepcopy(load_schema(o))), used),
                        {"type": "null"},
                    ]
                }
                for o in outputs
            },
        }
    defs = _common_schema()["$defs"]
    root["$defs"] = {name: copy.deepcopy(defs[name]) for name in sorted(used)}
    return root


def strict_compatibility_issues(schema: Any, path: str = "$") -> list[str]:
    """Objects must close additionalProperties and require every property.

    Structured-output implementations commonly require this form; a nullable type
    expresses an optional value instead of an omitted key.
    """
    issues: list[str] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            props = schema.get("properties", {})
            if schema.get("additionalProperties") is not False:
                issues.append(f"{path}: additionalProperties is not false")
            if sorted(schema.get("required", [])) != sorted(props):
                issues.append(f"{path}: required does not list every property")
        for bad in ("oneOf", "allOf", "not", "if"):
            if bad in schema:
                issues.append(f"{path}: uses {bad}")
        for key, value in schema.items():
            issues += strict_compatibility_issues(value, f"{path}.{key}")
    elif isinstance(schema, list):
        for i, value in enumerate(schema):
            issues += strict_compatibility_issues(value, f"{path}[{i}]")
    return issues


@dataclass
class Issue:
    code: str
    path: str
    message: str


@dataclass
class ValidationReport:
    output_type: str | None = None
    result: dict[str, Any] | None = None
    issues: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def codes(self) -> list[str]:
        return sorted({i.code for i in self.issues})


def check_step_input(step_input: dict[str, Any]) -> list[Issue]:
    """StepInput must match its schema and its allowlist must resolve to its own records."""
    issues = [
        Issue("step_input_schema_invalid", "/" + "/".join(map(str, e.absolute_path)), e.message)
        for e in canonical_validator("StepInput").iter_errors(step_input)
    ]
    if issues:
        return issues
    allow = step_input["allowlist"]
    records = {
        "candidate_ids": {c["candidate_id"] for c in step_input["candidates"]},
        "source_ids": {s["source_id"] for s in step_input["sources"]},
        "passage_ids": {p["passage_id"] for p in step_input["passages"]},
    }
    for key, known in records.items():
        for missing in sorted(set(allow[key]) - known):
            issues.append(Issue("allowlist_without_record", f"/allowlist/{key}", missing))
    for p in step_input["passages"]:
        if p["source_id"] not in records["source_ids"]:
            issues.append(Issue("passage_source_missing", f"/passages/{p['passage_id']}", p["source_id"]))
    return issues


def validate_model_output(step_input: dict[str, Any], raw: str | dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            report.issues.append(Issue("invalid_json", "$", str(exc)))
            return report
    else:
        data = raw

    task_type = step_input["task_type"]
    validator = Draft202012Validator(step_output_schema(task_type))
    schema_errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    for err in schema_errors:
        report.issues.append(
            Issue("schema_invalid", "/" + "/".join(map(str, err.absolute_path)), err.message)
        )
    if report.issues:
        return report

    outputs = TASK_OUTPUTS[task_type]
    if len(outputs) == 1:
        output_type, result = outputs[0], data
    else:
        present = [o for o in outputs if data[WRAPPER_KEYS[o]] is not None]
        if len(present) != 1:
            report.issues.append(
                Issue("ambiguous_result", "$", f"expected exactly one of {outputs}, got {present}")
            )
            return report
        output_type, result = present[0], data[WRAPPER_KEYS[present[0]]]
    report.output_type, report.result = output_type, result

    for name in ENVELOPE_FIELDS:
        if result[name] != step_input[name]:
            report.issues.append(
                Issue("envelope_mismatch", f"/{name}", f"expected {step_input[name]!r}, got {result[name]!r}")
            )

    allow = {k: set(v) for k, v in step_input["allowlist"].items()}
    if output_type == "SearchPlan":
        _check_search_plan(step_input, result, report)
    elif output_type == "ScreeningProposal":
        _check_screening(allow, result, report)
    elif output_type == "GroundedAnswerDraft":
        _check_answer(allow, result, report)
    return report


def _check_search_plan(step_input: dict[str, Any], plan: dict[str, Any], report: ValidationReport) -> None:
    enabled = set(step_input["enabled_providers"])
    for i, query in enumerate(plan["queries"]):
        if query["provider_id"] not in enabled:
            report.issues.append(
                Issue("provider_not_enabled", f"/queries/{i}/provider_id", query["provider_id"])
            )
    limit = step_input["budget"]["max_provider_requests"]
    if len(plan["queries"]) > limit:
        report.issues.append(
            Issue("query_budget_exceeded", "/queries", f"{len(plan['queries'])} queries > limit {limit}")
        )


def _check_screening(allow: dict[str, set[str]], proposal: dict[str, Any], report: ValidationReport) -> None:
    seen: set[str] = set()
    for i, decision in enumerate(proposal["decisions"]):
        cid = decision["candidate_id"]
        if cid not in allow["candidate_ids"]:
            report.issues.append(Issue("unknown_candidate_id", f"/decisions/{i}/candidate_id", cid))
        if cid in seen:
            report.issues.append(Issue("duplicate_candidate_decision", f"/decisions/{i}/candidate_id", cid))
        seen.add(cid)
    for cid in sorted(allow["candidate_ids"] - seen):
        report.warnings.append(Issue("candidate_without_proposal", "/decisions", cid))


def _check_answer(allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    labels: set[str] = set()
    for i, claim in enumerate(draft["claims"]):
        if claim["claim_label"] in labels:
            report.issues.append(Issue("duplicate_claim_label", f"/claims/{i}/claim_label", claim["claim_label"]))
        labels.add(claim["claim_label"])
        if not claim["passage_ids"]:
            report.issues.append(
                Issue("claim_without_passage", f"/claims/{i}/passage_ids", claim["claim_label"])
            )
        for j, pid in enumerate(claim["passage_ids"]):
            if pid not in allow["passage_ids"]:
                report.issues.append(Issue("unknown_passage_id", f"/claims/{i}/passage_ids/{j}", pid))
        if len(set(claim["passage_ids"])) != len(claim["passage_ids"]):
            report.issues.append(Issue("duplicate_passage_id", f"/claims/{i}/passage_ids", claim["claim_label"]))
    for i, limitation in enumerate(draft["limitations"]):
        for j, sid in enumerate(limitation["source_ids"]):
            if sid not in allow["source_ids"]:
                report.issues.append(Issue("unknown_source_id", f"/limitations/{i}/source_ids/{j}", sid))


def derive_evidence_links(step_input: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence links take source, depth and locator from StepInput records only."""
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    links = []
    for claim in draft["claims"]:
        for pid in claim["passage_ids"]:
            p = passages[pid]
            links.append(
                {
                    "claim_label": claim["claim_label"],
                    "passage_id": pid,
                    "source_id": p["source_id"],
                    "reading_depth": p["reading_depth"],
                    "locator": dict(p["locator"]),
                    "support_type": claim["support_type"],
                    "semantic_review": "not_checked",
                }
            )
    return links

"""Canonical JSON Schema contracts and deterministic model-output checks.

These checks establish structural validity, identifier scope and envelope
consistency. They do not establish that a passage semantically supports a claim.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from deixis.domain import wording
from deixis.domain.lineage import MAX_WHAT_CHANGED, valid_what_changed
from deixis.paths import CONTRACTS_DIR
from deixis.workflow.criterion import (MAX_PHRASE_WORDS, PARTS_PER_PROPOSAL, PHRASES_PER_PART,
                                       holds as criterion_holds, norm as normalize_phrase)
from deixis.workflow.tables import MAX_COLUMNS_PER_CALL, InvalidTableInput, check_value, column_spec

SCHEMA_FILES = {
    "OwnerReview": "owner-review.schema.json",
    "GroundedAnswerDraft": "grounded-answer-draft.schema.json",
    "FollowupAnswer": "followup-answer.schema.json",
    "AnswerReview": "answer-review.schema.json",
    "EvidenceCellDraft": "evidence-cell-draft.schema.json",
    "TableColumnProposal": "table-column-proposal.schema.json",
    "ResearchTitle": "research-title.schema.json",
    "VocabularyLabels": "vocabulary-labels.schema.json",
    "CriterionProposal": "criterion-proposal.schema.json",
    "SearchQuery": "search-query.schema.json",
    "AbstractScreening": "abstract-screening.schema.json",
    "FulltextAdjudication": "fulltext-adjudication.schema.json",
    "StepInput": "step-input.schema.json",
    "ReportPlanDraft": "report-plan.schema.json",
    "ReportSectionDraft": "report-section-draft.schema.json",
    "ReportReview": "report-review.schema.json",
    "LineageLinksDraft": "lineage-links-draft.schema.json",
    "ClaimDecomposition": "claim-decomposition.schema.json",
    "KillSearchQuery": "kill-search-query.schema.json",
    "FollowupSearchQuery": "followup-search-query.schema.json",
    "ClaimAssessment": "claim-assessment.schema.json",
    "ReportSectionAnchorRepair": "report-section-anchor-repair.schema.json",
    "CitationCheck": "citation-check.schema.json",
    # Not a model output: a search plan a person saved (UI parity S23a, F18), checked by `check_user_search_plan`.
    "UserSearchPlan": "user-search-plan.schema.json",
}
SCHEMA_VERSIONS = {
    "OwnerReview": "deixis.owner_review.v1",
    "GroundedAnswerDraft": "deixis.grounded_answer_draft.v4",
    "FollowupAnswer": "deixis.followup_answer.v5",
    "AnswerReview": "deixis.answer_review.v1",
    "EvidenceCellDraft": "deixis.evidence_cell_draft.v1",
    "TableColumnProposal": "deixis.table_column_proposal.v1",
    "ResearchTitle": "deixis.research_title.v1",
    "VocabularyLabels": "deixis.vocabulary_labels.v1",
    "CriterionProposal": "deixis.criterion_proposal.v3",
    "SearchQuery": "deixis.search_query.v1",
    "AbstractScreening": "deixis.abstract_screening.v1",
    "FulltextAdjudication": "deixis.fulltext_adjudication.v1",
    "ReportPlanDraft": "deixis.report_plan_draft.v2",
    "ReportSectionDraft": "deixis.report_section_draft.v3",
    "ReportReview": "deixis.report_review.v2",
    "LineageLinksDraft": "deixis.lineage_links_draft.v1",
    "ClaimDecomposition": "deixis.claim_decomposition.v1",
    "KillSearchQuery": "deixis.kill_search_query.v1",
    "FollowupSearchQuery": "deixis.followup_search_query.v1",
    "ClaimAssessment": "deixis.claim_assessment.v1",
    "ReportSectionAnchorRepair": "deixis.report_section_anchor_repair.v1",
    "CitationCheck": "deixis.citation_check.v1",
    "UserSearchPlan": "deixis.user_search_plan.v1",
}
# Model outputs each task may return. More than one output type is wrapped in an
# object with one nullable property per type; exactly one must be non-null.
TASK_OUTPUTS = {
    "owner_review": ("OwnerReview",),
    "grounded_answer": ("GroundedAnswerDraft",),
    "followup_answer": ("FollowupAnswer",),
    "answer_review": ("AnswerReview",),
    "cell_extraction": ("EvidenceCellDraft",),
    "table_columns": ("TableColumnProposal",),
    "research_title": ("ResearchTitle",),
    "vocabulary_labels": ("VocabularyLabels",),
    "criterion_proposal": ("CriterionProposal",),
    "search_query": ("SearchQuery",),
    "abstract_screening": ("AbstractScreening",),
    "fulltext_adjudication": ("FulltextAdjudication",),
    "report_plan": ("ReportPlanDraft",),
    "report_section": ("ReportSectionDraft",),
    "report_review": ("ReportReview",),
    "lineage_links": ("LineageLinksDraft",),
    "claim_decomposition": ("ClaimDecomposition",),
    "kill_search_query": ("KillSearchQuery",),
    "followup_search_query": ("FollowupSearchQuery",),
    "claim_assessment": ("ClaimAssessment",),
    "citation_check": ("CitationCheck",),
}
EXTRACTION_TASKS = ("cell_extraction", "table_columns")
# The block-labelling step sorts a phrase list code extracted; it carries a vocabulary_target instead (SW17.1).
VOCABULARY_TASKS = ("vocabulary_labels",)
# The abstract stage asks the same batch twice and tells each call which of the two runs it is (slice 09, K3).
SCREENING_TARGET_TASKS = ("abstract_screening",)
# The full-text reading step is given one work, the criterion parts, and which of the two runs this call is (D85).
ADJUDICATION_TARGET_TASKS = ("fulltext_adjudication",)
GAP_KINDS = ("stated_limitation", "conflicting_evidence", "corpus_absence")
REPORT_TASKS = ("report_plan", "report_section", "report_review")
REVIEW_TASKS = ("owner_review",)
LINEAGE_TASKS = ("lineage_links",)
CANDIDATE_TASKS = ("claim_decomposition", "kill_search_query", "claim_assessment")
# Verify Citations (D99): one citing sentence against the given passages of the one work it cites.
CITATION_CHECK_TASKS = ("citation_check",)
CANDIDATE_SUPPORT_RELATIONS = ("explicit_support", "reasoned_inference", "partial_match")
# A surface screen only: absence of these words does not establish the plan's scope or quality. A bare "protocol" is
# not one: a claim about routing or network protocols names them (D94).
VALIDATION_PLAN_DESIGN_TERMS = re.compile(
    r"\b(?:(?:experimental|experiment|study|test(?:ing)?|measurement|laboratory|lab|clinical|trial)\s+protocols?"
    r"|sample\s+size|power\s+analysis|apparatus|equipment|instrumentation|reagents?"
    r"|randomi[sz]ed|preregistered|pre-registered)\b", re.IGNORECASE,
)
# The cell states EvidenceCellDraft allows. inaccessible is the system's, not_verified and not_reported a person's (D37).
MODEL_CELL_STATES = ("value", "unknown", "not_applicable", "not_found_in_inspected_scope")
WRAPPER_KEYS: dict[str, str] = {}
COMMON_REF_PREFIX = "common.schema.json#/$defs/"
ENVELOPE_FIELDS = ("step_input_id", "scope_revision", "skill_package_hash")

OUTPUT_ALIASES: dict[str, dict[str, dict[str, str]]] = {
    "fulltext_adjudication": {
        "parts": {"name": "part", "verdict": "label", "status": "label"},
    },
    "abstract_screening": {
        "records": {"verdict": "label"},
    },
    "grounded_answer": {
        "claims": {"claim_label": "lower"},
        "citation_anchors": {"claim_label": "lower"},
    },
    "followup_answer": {
        "claims": {"claim_label": "lower"},
        "citation_anchors": {"claim_label": "lower"},
    },
    "answer_review": {
        "reviews": {"claim_label": "lower"},
    },
}


def normalise_output(task_type: str, draft: str | dict[str, Any]) -> tuple[str | dict[str, Any], list[dict[str, str]]]:
    """Rename the fields of OUTPUT_ALIASES and lower-case claim labels, and say what changed (D86).

    Names only: a value, a missing field or an unknown identifier is left for validation. A target already present
    is not overwritten. Text that is not a JSON object is returned as it came.
    """
    changes: list[dict[str, str]] = []
    if isinstance(draft, str):
        try:
            parsed = json.loads(draft)
        except json.JSONDecodeError:
            return draft, changes
        if not isinstance(parsed, dict):
            return draft, changes
        draft = parsed
    aliases = OUTPUT_ALIASES.get(task_type)
    if not aliases:
        return draft, changes
    for array_key, field_map in aliases.items():
        items = draft.get(array_key)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            for source, target in field_map.items():
                if target == "lower":
                    if source in item and isinstance(item[source], str) and item[source] != item[source].lower():
                        item[source] = item[source].lower()
                        changes.append({"path": f"/{array_key}/{index}/{source}", "lowered_to": item[source]})
                else:
                    if source in item and target not in item:
                        item[target] = item.pop(source)
                        changes.append({"path": f"/{array_key}/{index}/{source}", "renamed_to": target})
    return draft, changes


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
    return _adapter_schema(TASK_OUTPUTS[task_type])


def _adapter_schema(outputs: tuple[str, ...]) -> dict[str, Any]:
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


def report_section_anchor_patch_schema() -> dict[str, Any]:
    return _adapter_schema(("ReportSectionAnchorRepair",))


def model_output_schema(task_type: str) -> dict[str, Any]:
    """Transport omits the application-owned hash; canonical stored outputs retain it."""
    schema = copy.deepcopy(step_output_schema(task_type))
    objects = [schema] if len(TASK_OUTPUTS[task_type]) == 1 else [
        option for field in schema["properties"].values() for option in field["anyOf"]
        if option.get("type") == "object"]
    for obj in objects:
        obj["properties"].pop("skill_package_hash", None)
        obj["required"] = [name for name in obj["required"] if name != "skill_package_hash"]
    return schema


def model_transport_schemas() -> dict[str, dict]:
    """Enumerate the schemas sent by workflow and model-behavior callers."""
    return {
        **{f"model_output_schema:{task}": model_output_schema(task) for task in TASK_OUTPUTS},
        **{f"step_output_schema:{task}": step_output_schema(task) for task in TASK_OUTPUTS},
        "report_section_anchor_patch_schema": report_section_anchor_patch_schema(),
    }


def stamp_package_hash(task_type: str, step_input: dict[str, Any], draft: Any) -> tuple[Any, list[dict[str, Any]]]:
    changes = []
    if not isinstance(draft, dict):
        return draft, changes
    objects = [("", draft)] if len(TASK_OUTPUTS[task_type]) == 1 else [
        (f"/{WRAPPER_KEYS[name]}", draft[WRAPPER_KEYS[name]]) for name in TASK_OUTPUTS[task_type]
        if isinstance(draft.get(WRAPPER_KEYS[name]), dict)]
    for path, obj in objects:
        changes.append({"path": f"{path}/skill_package_hash", "stamped": "skill_package_hash",
                        "model_value": obj.get("skill_package_hash")})
        obj["skill_package_hash"] = step_input["skill_package_hash"]
    return draft, changes


def stamp_step_input_id(task_type: str, step_input: dict[str, Any], draft: Any) -> tuple[Any, list[dict[str, Any]]]:
    """Bind fresh adapter output to the code-owned input; never use on stored records."""
    changes = []
    if not isinstance(draft, dict):
        return draft, changes
    objects = [("", draft)] if len(TASK_OUTPUTS[task_type]) == 1 else [
        (f"/{WRAPPER_KEYS[name]}", draft[WRAPPER_KEYS[name]]) for name in TASK_OUTPUTS[task_type]
        if isinstance(draft.get(WRAPPER_KEYS[name]), dict)]
    for path, obj in objects:
        if obj.get("step_input_id") != step_input["step_input_id"]:
            changes.append({"path": f"{path}/step_input_id", "stamped": "step_input_id",
                            "model_value": obj.get("step_input_id")})
        obj["step_input_id"] = step_input["step_input_id"]
    return draft, changes


_STRICT_KEYWORDS = frozenset("""
    type properties required additionalProperties items enum const anyOf $ref $defs
    description title pattern format minLength maxLength minimum maximum
    exclusiveMinimum exclusiveMaximum multipleOf minItems maxItems
""".split())
_STRICT_TYPES = frozenset("string number integer boolean object array null".split())
_STRICT_FORMATS = frozenset("date-time time date duration email hostname ipv4 ipv6 uuid".split())


def _schema_children(node: dict, path: str, *, definitions: bool = True):
    """Only schema positions; property names and keyword data are not schemas."""
    for key in ("properties", "$defs") if definitions else ("properties",):
        if isinstance(node.get(key), dict):
            for name, child in node[key].items():
                yield child, f"{path}.{key}.{name}"
    if "items" in node:
        yield node["items"], f"{path}.items"
    if isinstance(node.get("anyOf"), list):
        for index, child in enumerate(node["anyOf"]):
            yield child, f"{path}.anyOf[{index}]"


def _strict_ref_target(ref: Any, root: dict) -> dict | None:
    if ref == "#":
        return root
    if not isinstance(ref, str) or not re.fullmatch(r"#/\$defs/([^/~]|~[01])+", ref):
        return None
    name = ref.removeprefix("#/$defs/").replace("~1", "/").replace("~0", "~")
    defs = root.get("$defs", {})
    target = defs.get(name) if isinstance(defs, dict) else None
    return target if isinstance(target, dict) else None


def _strict_schema_walk(node: Any, path: str, root: dict, totals: list[int], *, is_root: bool = False) -> list[str]:
    # R8 (DEIXIS policy): boolean and other non-object subschemas are refused.
    if not isinstance(node, dict):
        return [f"R8 {path}: subschema is not an object"]
    issues = []
    # R1 (rejection observed): H9b's API refused a $ref with sibling keywords.
    if "$ref" in node and len(node) != 1:
        issues.append(f"R1 {path}: $ref has sibling keywords")
    typ = node.get("type")
    # R2 (documented): nullable objects must also be closed and fully required.
    if typ == "object" or (isinstance(typ, list) and "object" in typ) or "properties" in node:
        props = node.get("properties", {})
        if node.get("additionalProperties") is not False:
            issues.append(f"R2 {path}: additionalProperties is not false")
        required = node.get("required", [])
        if (not isinstance(props, dict) or not isinstance(required, list)
                or not all(isinstance(name, str) for name in required)
                or sorted(required) != sorted(props)):
            issues.append(f"R2 {path}: required does not list every property")
    # R3 (DEIXIS policy): keyword allowlist and valid, distinct type names.
    for key in node:
        if key not in _STRICT_KEYWORDS:
            issues.append(f"R3 {path}: unsupported keyword {key}")
    if "type" in node and not (
        isinstance(typ, str) and typ in _STRICT_TYPES
        or isinstance(typ, list) and bool(typ)
        and all(isinstance(t, str) and t in _STRICT_TYPES for t in typ)
        and len(set(typ)) == len(typ)
    ):
        issues.append(f"R3 {path}: invalid type")
    # R5 (documented resolution; DEIXIS policy for local syntax/root-only $defs).
    if "$ref" in node and _strict_ref_target(node["$ref"], root) is None:
        issues.append(f"R5 {path}: $ref must resolve to # or a root $defs entry")
    if "$defs" in node and not is_root:
        issues.append(f"R5 {path}: $defs is only allowed at the root")
    # R6 (documented): only the supported format names are admitted.
    if "format" in node and (not isinstance(node["format"], str) or node["format"] not in _STRICT_FORMATS):
        issues.append(f"R6 {path}: unsupported format")
    # R7 (documented thresholds; DEIXIS policy syntactic counting).
    for key in ("properties", "$defs"):
        if isinstance(node.get(key), dict):
            if key == "properties":
                totals[0] += len(node[key])
            totals[2] += sum(len(name) for name in node[key])
    enum = node.get("enum")
    if isinstance(enum, list):
        totals[1] += len(enum)
        length = sum(len(value) for value in enum if isinstance(value, str))
        totals[2] += length
        if len(enum) > 250 and all(isinstance(value, str) for value in enum) and length > 15_000:
            issues.append(f"R7 {path}: string enum exceeds 15000 characters")
    if isinstance(node.get("const"), str):
        totals[2] += len(node["const"])
    # R8 (DEIXIS policy): arrays have items and anyOf has at least one branch.
    if (typ == "array" or isinstance(typ, list) and "array" in typ) and "items" not in node:
        issues.append(f"R8 {path}: array has no items")
    if "anyOf" in node and (not isinstance(node["anyOf"], list) or not node["anyOf"]):
        issues.append(f"R8 {path}: anyOf is not a non-empty list")
    for child, child_path in _schema_children(node, path):
        issues += _strict_schema_walk(child, child_path, root, totals)
    return issues


def _strict_object_depth(node: Any, root: dict, depth: int, active: frozenset[int]) -> int:
    if not isinstance(node, dict) or id(node) in active:
        return depth
    active = active | {id(node)}
    typ = node.get("type")
    depth += int(typ == "object" or isinstance(typ, list) and "object" in typ or "properties" in node)
    deepest = depth
    # R7 (DEIXIS policy): a per-path guard permits recursion and revisits shared defs.
    target = _strict_ref_target(node.get("$ref"), root)
    if target is not None:
        deepest = max(deepest, _strict_object_depth(target, root, depth, active))
    for child, _ in _schema_children(node, "", definitions=False):
        deepest = max(deepest, _strict_object_depth(child, root, depth, active))
    return deepest


def strict_compatibility_issues(schema: Any, path: str = "$") -> list[str]:
    """Conservative offline guard for OpenAI strict mode, not a full specification.

    R1: rejection observed (H9b $ref siblings). R2, R4, R6: documented.
    R3, R8: DEIXIS policy. R5: documented resolution, DEIXIS policy local
    references/root-only $defs. R7: documented thresholds, DEIXIS policy counting.
    Documentation is not re-read offline in RF2. Existing constraint keywords
    have request accepted evidence only, not evidence of keyword enforcement.
    Fine-tuned-model restrictions are omitted: DEIXIS does not send to those
    models. Claude and Gemini have separate adapter rules, not checked here.
    Also use Draft202012Validator.check_schema to check keyword value shapes.
    """
    root = schema if isinstance(schema, dict) else {}
    # R4 (documented): apply root-only rules once, never to properties/branches.
    issues = []
    if root.get("type") != "object" or "anyOf" in root:
        issues.append(f"R4 {path}: root must have type object and no anyOf")
    totals = [0, 0, 0]  # properties, enum values, counted string characters
    issues += _strict_schema_walk(schema, path, root, totals, is_root=True)
    # R7 (documented thresholds; DEIXIS policy counting and reference depth).
    for count, limit, label in zip(totals, (5000, 1000, 120_000), ("properties", "enum values", "string characters")):
        if count > limit:
            issues.append(f"R7 {path}: total {label} exceeds {limit}")
    depth = _strict_object_depth(root, root, 0, frozenset())
    defs = root.get("$defs", {})
    if isinstance(defs, dict):
        depth = max([depth] + [_strict_object_depth(node, root, 0, frozenset()) for node in defs.values()])
    if depth > 10:
        issues.append(f"R7 {path}: object nesting exceeds 10 levels")
    return issues


@dataclass
class Issue:
    code: str
    path: str
    message: str


@dataclass
class AnchorSalvageWarning(Issue):
    claim_label: str
    passage_id: str | None
    dropped: str
    issue_codes: list[str]


@dataclass
class ReportLinkPruneWarning(Issue):
    claim_key: str
    passage_id: str | None
    cell_id: str | None
    dropped: str
    issue_codes: list[str]


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
    for claim in step_input.get("claims_under_review", []):
        for pid in claim["passage_ids"]:
            if pid not in records["passage_ids"]:
                issues.append(Issue("review_passage_missing", f"/claims_under_review/{claim['claim_label']}", pid))
    target = step_input.get("extraction_target")
    if (target is not None) != (step_input["task_type"] in EXTRACTION_TASKS):
        issues.append(Issue("extraction_target_mismatch", "/extraction_target", step_input["task_type"]))
    elif step_input["task_type"] == "cell_extraction":
        # One call reads one source version, so evidence cannot come from another source or another version of the work.
        if target["source_id"] is None or records["source_ids"] != {target["source_id"]}:
            issues.append(Issue("extraction_source_mismatch", "/extraction_target/source_id", str(target["source_id"])))
        for p in step_input["passages"]:
            if p["source_id"] != target["source_id"]:
                issues.append(Issue("passage_outside_extraction_source", f"/passages/{p['passage_id']}", p["source_id"]))
        if not 1 <= len(target["columns"]) <= MAX_COLUMNS_PER_CALL:
            issues.append(Issue("extraction_column_count", "/extraction_target/columns", str(len(target["columns"]))))
        asked = {c["column_id"] for c in target["columns"]}
        for i, item in enumerate(target.get("earlier_issues") or []):
            # A retry names problems of the columns it asks again for, and only those.
            if item["column_id"] not in asked:
                issues.append(Issue("earlier_issue_outside_columns", f"/extraction_target/earlier_issues/{i}", item["column_id"]))
    if target is not None and "earlier_issues" in target and step_input["task_type"] != "cell_extraction":
        issues.append(Issue("earlier_issues_outside_cell_extraction", "/extraction_target/earlier_issues", step_input["task_type"]))
    if target is not None and "comparison_frame" in target and step_input["task_type"] != "table_columns":
        # The compare intent frames column suggestions only; a cell is read against its column, never a frame.
        issues.append(Issue("comparison_frame_outside_column_suggestions", "/extraction_target/comparison_frame",
                            step_input["task_type"]))
    vocabulary_target = step_input.get("vocabulary_target")
    if (vocabulary_target is not None) != (step_input["task_type"] in VOCABULARY_TASKS):
        issues.append(Issue("vocabulary_target_mismatch", "/vocabulary_target", step_input["task_type"]))
    elif vocabulary_target is not None:
        # The allowlist is the phrase list itself: the step may name nothing else, and nothing else may be allowed.
        phrases = [entry["phrase"] for entry in vocabulary_target["phrases"]]
        if len(set(phrases)) != len(phrases):
            issues.append(Issue("duplicate_vocabulary_phrase", "/vocabulary_target/phrases", "phrase must be unique"))
        if sorted(set(allow.get("phrases", []))) != sorted(set(phrases)):
            issues.append(Issue("phrase_allowlist_mismatch", "/allowlist/phrases", "the allowlist is the phrase list"))
    if ("conversation" in step_input) != (step_input["task_type"] == "followup_answer"):
        issues.append(Issue("conversation_mismatch", "/conversation", step_input["task_type"]))
    if ("followup_search_context" in step_input) != (step_input["task_type"] == "followup_search_query"):
        issues.append(Issue("followup_search_context_mismatch", "/followup_search_context", step_input["task_type"]))
    if step_input["task_type"] == "followup_search_query" and (step_input["sources"] or step_input["passages"]):
        # The query reads the follow-up and the research's context card only, never a record (D92).
        issues.append(Issue("followup_search_query_no_records", "/sources", "the query reads only its context"))
    screening_target = step_input.get("screening_target")
    if (screening_target is not None) != (step_input["task_type"] in SCREENING_TARGET_TASKS):
        issues.append(Issue("screening_target_mismatch", "/screening_target", step_input["task_type"]))
    elif screening_target is not None and not 1 <= screening_target["run"] <= screening_target["runs"]:
        issues.append(Issue("screening_run_out_of_range", "/screening_target/run", str(screening_target["run"])))
    adjudication_target = step_input.get("adjudication_target")
    if (adjudication_target is not None) != (step_input["task_type"] in ADJUDICATION_TARGET_TASKS):
        issues.append(Issue("adjudication_target_mismatch", "/adjudication_target", step_input["task_type"]))
    elif adjudication_target is not None and not 1 <= adjudication_target["run"] <= adjudication_target["runs"]:
        issues.append(Issue("adjudication_run_out_of_range", "/adjudication_target/run", str(adjudication_target["run"])))
    issues.extend(_check_lineage_target(step_input, records))
    issues.extend(_check_candidate_target(step_input, records))
    issues.extend(_check_citation_check_target(step_input, records))
    issues.extend(_check_owner_review_input(step_input, records))
    report_target = step_input.get("report_target")
    if (report_target is not None) != (step_input["task_type"] in REPORT_TASKS):
        issues.append(Issue("report_target_mismatch", "/report_target", step_input["task_type"]))
    elif report_target is not None:
        context = report_target.get("validation_context")
        if context is not None and len(json.dumps(context, ensure_ascii=False, sort_keys=True)) > MAX_REPORT_VALIDATION_CHARS:
            issues.append(Issue("report_validation_context_too_large", "/report_target/validation_context", "frozen validation context exceeds 262144 characters; no truncation permitted"))
        review_sections = report_target["review_sections"]
        if (review_sections is not None) != (step_input["task_type"] == "report_review"):
            issues.append(Issue("review_sections_mismatch", "/report_target/review_sections", step_input["task_type"]))
        if review_sections is not None:
            shown = [section["section_id"] for section in review_sections]
            if report_target["review_scope"] != shown:
                issues.append(Issue("review_scope_mismatch", "/report_target/review_scope", str(shown)))
            for i, section in enumerate(review_sections):
                for j, claim in enumerate(section["claims"]):
                    for k, citation in enumerate(claim["citations"]):
                        pid, cid = citation["passage_id"], citation["cell_id"]
                        if (pid is not None and pid not in allow["passage_ids"]) or (cid is not None and cid not in allow.get("cell_ids", [])) or (pid is None and cid is None):
                            issues.append(Issue("review_citation_not_allowed", f"/report_target/review_sections/{i}/claims/{j}/citations/{k}", str(citation)))
        wants_core = step_input["task_type"] == "report_section" and report_target["section_id"] == "VIII"
        if (report_target["limitations_core"] is not None) != wants_core:
            issues.append(Issue("limitations_core_mismatch", "/report_target/limitations_core", step_input["task_type"]))
        report_column_ids = [column["column_id"] for column in report_target["columns"]]
        if len(set(report_column_ids)) != len(report_column_ids):
            issues.append(Issue("duplicate_report_column", "/report_target/columns", "column_id must be unique"))
        cell_ids = {cell["cell_id"] for cell in report_target["cells"]}
        if len(cell_ids) != len(report_target["cells"]):
            issues.append(Issue("duplicate_report_cell", "/report_target/cells", "cell_id must be unique"))
        for missing in sorted(set(allow.get("cell_ids", [])) - cell_ids):
            issues.append(Issue("allowlist_without_record", "/allowlist/cell_ids", missing))
        cell_evidence = {e["passage_id"] for cell in report_target["cells"] for e in cell["evidence"]}
        for missing in sorted(set(allow.get("cell_evidence_passage_ids", [])) - cell_evidence):
            issues.append(Issue("allowlist_without_record", "/allowlist/cell_evidence_passage_ids", missing))
        for i, cell in enumerate(report_target["cells"]):
            if cell["cell_id"] not in allow.get("cell_ids", []):
                issues.append(Issue("report_cell_not_allowed", f"/report_target/cells/{i}/cell_id", cell["cell_id"]))
            if cell["source_version_id"] not in allow["source_ids"]:
                issues.append(Issue("report_cell_source_not_allowed", f"/report_target/cells/{i}/source_version_id",
                                    cell["source_version_id"]))
            if cell["column_id"] not in allow.get("column_ids", []):
                issues.append(Issue("report_cell_column_not_allowed", f"/report_target/cells/{i}/column_id",
                                    cell["column_id"]))
            for j, evidence in enumerate(cell["evidence"]):
                # A quote-only cell's page is not supplied: its id is listed, not citable, so only the quote is evidence (D58).
                if evidence["passage_id"] not in allow["passage_ids"] and evidence["passage_id"] not in allow.get("cell_evidence_passage_ids", []):
                    issues.append(Issue("report_cell_passage_not_allowed",
                                        f"/report_target/cells/{i}/evidence/{j}/passage_id",
                                        evidence["passage_id"]))
        for i, candidate in enumerate(report_target["gap_candidates"]):
            if candidate["gap_id"] not in allow.get("gap_ids", []):
                issues.append(Issue("gap_candidate_not_allowed", f"/report_target/gap_candidates/{i}/gap_id",
                                    candidate["gap_id"]))
            if candidate["column_id"] not in allow.get("column_ids", []):
                issues.append(Issue("gap_candidate_column_not_allowed", f"/report_target/gap_candidates/{i}/column_id",
                                    candidate["column_id"]))
            for j, cell_id in enumerate(candidate["basis_cell_ids"]):
                if cell_id not in {c["cell_id"] for c in (context or {}).get("cells", [])}:
                    issues.append(Issue("gap_basis_cell_missing", f"/report_target/gap_candidates/{i}/basis_cell_ids/{j}",
                                        cell_id))
        if step_input["task_type"] == "report_section":
            if report_target["plan"] is None:
                issues.append(Issue("report_plan_missing", "/report_target/plan", step_input["task_type"]))
            for axis in (report_target["plan"] or {}).get("axes", []):
                if axis["column_id"] not in allow.get("column_ids", []):
                    issues.append(Issue("axis_column_not_in_allowlist", "/report_target/plan/axes", axis["column_id"]))
            for field, code in (("limitations_column_id", "limitations_column_not_in_allowlist"),
                                ("future_work_column_id", "future_work_column_not_in_allowlist")):
                column_id = (report_target["plan"] or {}).get(field)
                if column_id is not None and column_id not in allow.get("column_ids", []):
                    issues.append(Issue(code, f"/report_target/plan/{field}", column_id))
        elif report_target["plan"] is not None:
            issues.append(Issue("report_plan_must_be_null", "/report_target/plan", step_input["task_type"]))
    return issues


def _check_owner_review_input(si: dict[str, Any], records: dict[str, set[str]]) -> list[Issue]:
    issues: list[Issue] = []
    target = si.get("review_input")
    if (target is not None) != (si["task_type"] in REVIEW_TASKS):
        return [Issue("review_input_mismatch", "/review_input", si["task_type"])]
    if target is None:
        return issues

    def reject(code: str, path: str, detail: Any) -> None:
        issues.append(Issue(code, path, str(detail)))

    allow = si["allowlist"]
    if si["candidates"] or any(k.endswith("_target") for k in si):
        reject("review_input_mismatch", "/review_input", "review carries no candidates or other target")
    allowed_keys = {"candidate_ids", "source_ids", "passage_ids", "cell_ids", "claim_refs", "section_refs", "element_refs"}
    if set(allow) - allowed_keys or allow["candidate_ids"]:
        reject("review_allowlist_mismatch", "/allowlist", "only review record and ref lists are allowed")
    for name, array, field in (("claim_refs", "claims", "claim_ref"), ("section_refs", "sections", "section_ref"),
                                ("element_refs", "elements", "element_ref"), ("cell_ids", "cells", "cell_id")):
        refs = [r[field] for r in target[array]]
        if len(refs) != len(set(refs)):
            reject("duplicate_review_ref", f"/review_input/{array}", name)
        if sorted(allow.get(name, [])) != sorted(refs):
            reject("review_allowlist_mismatch", f"/allowlist/{name}", refs)
    pids = [p["passage_id"] for p in si["passages"]]
    sids = [s["source_id"] for s in si["sources"]]
    if sorted(allow["source_ids"]) != sorted(sids) or len(set(sids)) != len(sids):
        reject("review_source_ids_mismatch", "/allowlist/source_ids", sids)
    if (sorted(target["passage_ids"]) != sorted(pids) or sorted(allow["passage_ids"]) != sorted(pids)
            or len(set(pids)) != len(pids)):
        reject("review_passage_ids_mismatch", "/review_input/passage_ids", pids)
    if len(pids) > 48:
        reject("review_passage_count", "/passages", len(pids))
    if target["group_index"] > target["group_count"]:
        reject("review_group_out_of_range", "/review_input/group_index", target["group_index"])
    if target["owner_note"] is not None and not target["owner_note"].strip():
        reject("review_owner_note_blank", "/review_input/owner_note", "note must not be blank")
    kind = target["target_kind"]
    context = target["candidate_context"]
    if (kind == "candidate") != (context is not None):
        reject("review_target_shape_mismatch", "/review_input/candidate_context", kind)
    if kind == "candidate" and context is not None:
        passages = {p["passage_id"]: p for p in si["passages"]}
        elements = set(allow.get("element_refs", []))
        seen_sources = set()
        for i, source in enumerate(context["matrix"]):
            path = f"/review_input/candidate_context/matrix/{i}"
            sid = source["source_id"]
            if sid not in records["source_ids"] or sid not in allow["source_ids"]:
                reject("review_matrix_source_missing", path + "/source_id", sid)
            if sid in seen_sources:
                reject("duplicate_review_ref", path, sid)
            seen_sources.add(sid)
            seen_elements = set()
            for j, cell in enumerate(source["cells"]):
                ref = cell["element_ref"]
                if ref not in elements:
                    reject("review_matrix_element_missing", path + f"/cells/{j}/element_ref", ref)
                if ref in seen_elements:
                    reject("duplicate_review_ref", path + f"/cells/{j}", ref)
                seen_elements.add(ref)
            for quote in source["whole_claim_quotes"] + [q for c in source["cells"] for q in c["quotes"]]:
                pid = quote["passage_id"]
                if pid not in passages or pid not in allow["passage_ids"]:
                    reject("review_matrix_passage_missing", path, pid)
                elif passages[pid]["source_id"] != sid:
                    reject("review_matrix_passage_source_mismatch", path, pid)
    if (kind == "answer" and (target["sections"] or target["cells"] or target["columns"] or target["elements"]
                             or target["candidate_statement"] is not None or any(c["section_ref"] is not None for c in target["claims"]))
            or kind == "report" and (target["elements"] or target["candidate_statement"] is not None)
            or kind == "candidate" and (target["claims"] or target["sections"] or target["cells"] or target["columns"])):
        reject("review_target_shape_mismatch", "/review_input", kind)
    cells = {c["cell_id"]: c for c in target["cells"]}
    columns = [c["column_id"] for c in target["columns"]]
    if len(columns) != len(set(columns)):
        reject("duplicate_review_ref", "/review_input/columns", "column_id")
    for i, cell in enumerate(target["cells"]):
        path = f"/review_input/cells/{i}"
        if cell["source_id"] not in records["source_ids"] or cell["source_id"] not in allow["source_ids"]:
            reject("review_cell_source_missing", path + "/source_id", cell["source_id"])
        if cell["column_id"] not in columns:
            reject("review_cell_column_missing", path + "/column_id", cell["column_id"])
        for j, evidence in enumerate(cell["evidence"]):
            if evidence["passage_id"] not in records["passage_ids"] or evidence["passage_id"] not in allow["passage_ids"]:
                reject("review_cell_passage_missing", path + f"/evidence/{j}", evidence["passage_id"])
    for i, claim in enumerate(target["claims"]):
        if kind == "report" and claim["section_ref"] not in allow.get("section_refs", []):
            reject("review_claim_section_missing", f"/review_input/claims/{i}/section_ref", claim["section_ref"])
        for j, citation in enumerate(claim["citations"]):
            pid, cid = citation["passage_id"], citation["cell_id"]
            path = f"/review_input/claims/{i}/citations/{j}"
            if (pid is None) == (cid is None):
                reject("review_citation_id_mismatch", path, "exactly one passage or cell")
            if pid is not None and (pid not in records["passage_ids"] or pid not in allow["passage_ids"]):
                reject("review_citation_passage_missing", path, pid)
            if cid is not None and (cid not in cells or cid not in allow.get("cell_ids", [])):
                reject("review_citation_cell_missing", path, cid)
    return issues


def _check_owner_review(si: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    target = si["review_input"]
    allowed_kinds = {"answer": {"claim", "whole"}, "report": {"claim", "section", "whole"},
                     "candidate": {"candidate_element", "whole"}}[target["target_kind"]]
    ref_keys = {"claim": "claim_refs", "section": "section_refs", "candidate_element": "element_refs"}
    passages = {p["passage_id"]: p for p in si["passages"]}

    def issue(code: str, path: str, message: Any) -> None:
        report.issues.append(Issue(code, path, str(message)))

    handles: set[str] = set()
    for name in ("findings", "supported_points", "context_limits"):
        for i, item in enumerate(draft[name]):
            path = f"/{name}/{i}"
            ref = item["target_ref"]
            kind, label = ref["kind"], ref["ref"]
            if kind not in allowed_kinds:
                issue("review_target_kind_mismatch", path + "/target_ref/kind", kind)
            if (kind == "whole") != (label is None):
                issue("review_ref_without_kind", path + "/target_ref/ref", label)
            if kind != "whole" and label not in si["allowlist"].get(ref_keys.get(kind, ""), []):
                issue("review_ref_unknown", path + "/target_ref/ref", label)
            if name == "findings":
                handle = item["finding_handle"]
                if handle in handles:
                    issue("duplicate_finding_handle", path + "/finding_handle", handle)
                handles.add(handle)
                if item["kind"] in {"unsupported", "partially_supported", "overstated"} and not item["evidence"]:
                    issue("finding_without_evidence", path + "/evidence", item["kind"])
            seen: set[tuple] = set()
            for j, evidence in enumerate(item.get("evidence", [])):
                epath = path + f"/evidence/{j}"
                pid, quote = evidence["passage_handle"], evidence["anchor"]
                key = (kind, label, pid, quote)
                if name == "findings" and key in seen:
                    issue("duplicate_review_evidence", epath, pid)
                seen.add(key)
                if pid not in si["allowlist"]["passage_ids"] or pid not in passages:
                    issue("review_passage_not_allowed", epath + "/passage_handle", pid)
                    continue
                anchor = locate_anchor(quote, passages[pid]["text"])
                if anchor is None:
                    issue("review_anchor_not_in_passage", epath + "/anchor", quote)
                elif anchor.kind not in {"exact", "normalized"}:
                    issue("review_anchor_not_exact", epath + "/anchor", quote)


def _lineage_records_by_id(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    """Keep the first source-owned record for each ID, matching lineage handle numbering."""
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        by_id.setdefault(record[key], record)
    return by_id


def _check_lineage_target(step_input: dict[str, Any], records: dict[str, set[str]]) -> list[Issue]:
    issues: list[Issue] = []
    target = step_input.get("lineage_target")
    lineage = step_input["task_type"] in LINEAGE_TASKS
    allow = step_input["allowlist"]
    if (target is not None) != lineage or (lineage and (
        step_input["candidates"] or allow["candidate_ids"] or any(
            field in step_input for field in ("extraction_target", "report_target", "vocabulary_target",
                                              "screening_target", "adjudication_target")))):
        issues.append(Issue("lineage_target_mismatch", "/lineage_target", step_input["task_type"]))
    if lineage:
        for key in sorted(set(allow) - {"candidate_ids", "source_ids", "passage_ids"}):
            issues.append(Issue("lineage_allowlist_key", f"/allowlist/{key}", key))
        if "claims_under_review" in step_input:
            issues.append(Issue("lineage_unexpected_field", "/claims_under_review", "not a lineage input field"))
        for field, key in (("sources", "source_id"), ("passages", "passage_id")):
            first_records = _lineage_records_by_id(step_input[field], key)
            for i, record in enumerate(step_input[field]):
                if record != first_records[record[key]]:
                    issues.append(Issue("lineage_conflicting_record", f"/{field}/{i}", record[key]))
    if target is None:
        return issues
    sources = (_lineage_records_by_id(step_input["sources"], "source_id") if lineage
               else {s["source_id"]: s for s in step_input["sources"]})
    to_id = target["to"]["source_id"]
    seen: set[str] = set()
    nodes = [("/lineage_target/to", target["to"])]
    for i, candidate in enumerate(target["candidates"]):
        path = f"/lineage_target/candidates/{i}"
        from_id = candidate["from"]["source_id"]
        nodes.append((f"{path}/from", candidate["from"]))
        if from_id == to_id or (from_id in sources and to_id in sources
                               and sources[from_id]["work_id"] == sources[to_id]["work_id"]):
            issues.append(Issue("lineage_same_work", f"{path}/from/source_id", from_id))
        if from_id in seen:
            issues.append(Issue("duplicate_lineage_candidate", f"{path}/from/source_id", from_id))
        seen.add(from_id)
        mentions: set[str] = set()
        for j, pid in enumerate(candidate["mention_passage_ids"]):
            if pid not in records["passage_ids"] or pid in mentions:
                issues.append(Issue("lineage_mention_passage_unknown", f"{path}/mention_passage_ids/{j}", pid))
            mentions.add(pid)
    for path, node in nodes:
        sid = node["source_id"]
        if sid not in allow["source_ids"]:
            issues.append(Issue("lineage_source_not_allowed", f"{path}/source_id", sid))
        if sid not in sources:
            issues.append(Issue("lineage_source_not_shown", f"{path}/source_id", sid))
        if sorted(c["role"] for c in node["cells"]) != ["change", "problem", "uncertainty"]:
            issues.append(Issue("lineage_node_roles", f"{path}/cells", "each role must appear exactly once"))
        for i, cell in enumerate(node["cells"]):
            if cell["state"] == "missing" and (any(cell[field] is not None for field in (
                "cell_id", "cell_revision_id", "column_revision", "value", "reading_depth", "output_status"))
                or any(cell["flags"].values()) or cell["evidence_quotes"]):
                issues.append(Issue("lineage_missing_cell_shape", f"{path}/cells/{i}", "missing cell carries stored content"))
    for i, passage in enumerate(step_input["passages"]):
        if passage["source_id"] != to_id:
            issues.append(Issue("lineage_passage_not_later_work", f"/passages/{i}/source_id", passage["source_id"]))
    if len(records["passage_ids"]) > 24:
        issues.append(Issue("lineage_passage_count", "/passages", "at most 24 unique passages"))
    for key in ("source_ids", "passage_ids"):
        for missing in sorted(records[key] - set(allow[key])):
            issues.append(Issue("lineage_allowlist_mismatch", f"/allowlist/{key}", missing))
    return issues


def _check_candidate_target(step_input: dict[str, Any], records: dict[str, set[str]]) -> list[Issue]:
    issues: list[Issue] = []
    task = step_input["task_type"]
    candidate = task in CANDIDATE_TASKS
    target = step_input.get("candidate_target")
    allow = step_input["allowlist"]
    if (target is not None) != candidate or (candidate and (
        step_input["candidates"] or allow["candidate_ids"] or any(
            field in step_input for field in ("extraction_target", "report_target", "vocabulary_target",
                                              "screening_target", "adjudication_target", "lineage_target")))):
        issues.append(Issue("candidate_target_mismatch", "/candidate_target", task))
    if not candidate:
        return issues
    keys = {"candidate_ids", "source_ids", "passage_ids"}
    if task == "claim_assessment":
        keys.add("element_ids")
    for key in sorted(set(allow) - keys):
        issues.append(Issue("candidate_allowlist_key", f"/allowlist/{key}", key))
    if "claims_under_review" in step_input:
        issues.append(Issue("candidate_unexpected_field", "/claims_under_review", "not a candidate input field"))
    for field, key in (("sources", "source_id"), ("passages", "passage_id")):
        first = _lineage_records_by_id(step_input[field], key)
        for i, record in enumerate(step_input[field]):
            if record != first[record[key]]:
                issues.append(Issue("candidate_conflicting_record", f"/{field}/{i}", record[key]))
    for key in ("source_ids", "passage_ids"):
        for missing in sorted(records[key] - set(allow[key])):
            issues.append(Issue("candidate_allowlist_mismatch", f"/allowlist/{key}", missing))
    if len(records["passage_ids"]) > 24:
        issues.append(Issue("candidate_passage_count", "/passages", "at most 24 unique passages"))
    if task == "kill_search_query" and (step_input["sources"] or step_input["passages"]):
        issues.append(Issue("candidate_no_records", "/sources", "query reads only the claim version"))
    if task == "claim_assessment" and not step_input["passages"]:
        issues.append(Issue("candidate_assessment_without_text", "/passages", "assessment needs shown text"))
    if target is None:
        return issues
    path = "/candidate_target"
    if ((target["origin"] == "owner_text" and (target["gap_kind"] is not None or target["basis"]))
            or (target["origin"] == "report_gap" and target["gap_kind"] is None)):
        issues.append(Issue("candidate_origin_mismatch", path, "owner text has no gap kind or basis; report gap needs a kind"))
    decomposition = task == "claim_decomposition"
    assessment = task == "claim_assessment"
    version = target["version"]
    if (version is None) != decomposition:
        issues.append(Issue("candidate_version_mismatch", f"{path}/version", task))
    if (target["origin_text"] is not None) != decomposition:
        issues.append(Issue("candidate_origin_text_mismatch", f"{path}/origin_text", task))
    if target["basis"] and not decomposition:
        issues.append(Issue("candidate_basis_mismatch", f"{path}/basis", task))
    sid = target["assessed_source_id"]
    if ((sid is not None) != assessment or (assessment and (
            len(step_input["sources"]) != 1 or records["source_ids"] != {sid} or sid not in allow["source_ids"]))):
        issues.append(Issue("candidate_assessed_source_mismatch", f"{path}/assessed_source_id", task))
    if assessment:
        for i, passage in enumerate(step_input["passages"]):
            if passage["source_id"] != sid:
                issues.append(Issue("candidate_passage_not_assessed_work", f"/passages/{i}/source_id", passage["source_id"]))
    for i, item in enumerate(target["basis"]):
        pid = item["passage_id"]
        if (pid is not None) != (item["kind"] == "passage"):
            issues.append(Issue("candidate_basis_shape", f"{path}/basis/{i}", "only passage basis items carry a passage ID"))
        if pid is not None and pid not in records["passage_ids"]:
            issues.append(Issue("candidate_basis_passage_unknown", f"{path}/basis/{i}/passage_id", pid))
    if version is not None:
        elements = version["elements"]
        if [e["position"] for e in elements] != list(range(1, len(elements) + 1)):
            issues.append(Issue("candidate_element_positions", f"{path}/version/elements", "positions must be 1..n in list order"))
        seen: set[str] = set()
        for i, element in enumerate(elements):
            eid = element["element_id"]
            if eid in seen:
                issues.append(Issue("duplicate_candidate_element", f"{path}/version/elements/{i}/element_id", eid))
            seen.add(eid)
    if assessment and ("element_ids" not in allow or version is None
                       or sorted(allow["element_ids"]) != sorted(e["element_id"] for e in version["elements"])):
        issues.append(Issue("candidate_allowlist_mismatch", "/allowlist/element_ids", "must equal the version's element IDs exactly"))
    return issues


def _check_citation_check_target(step_input: dict[str, Any], records: dict[str, set[str]]) -> list[Issue]:
    """A citation check reads one work: its one source, passages of that source only, and nothing else (D99)."""
    issues: list[Issue] = []
    task = step_input["task_type"]
    checking = task in CITATION_CHECK_TASKS
    target = step_input.get("citation_check_target")
    allow = step_input["allowlist"]
    if (target is not None) != checking or (checking and (
            step_input["candidates"] or allow["candidate_ids"] or "claims_under_review" in step_input or any(
                field in step_input for field in ("extraction_target", "report_target", "vocabulary_target",
                                                  "screening_target", "adjudication_target", "lineage_target",
                                                  "candidate_target", "review_input")))):
        issues.append(Issue("citation_check_target_mismatch", "/citation_check_target", task))
    if not checking or target is None:
        return issues
    for key in sorted(set(allow) - {"candidate_ids", "source_ids", "passage_ids"}):
        issues.append(Issue("citation_check_allowlist_key", f"/allowlist/{key}", key))
    sid = target["assessed_source_id"]
    if len(step_input["sources"]) != 1 or records["source_ids"] != {sid} or set(allow["source_ids"]) != {sid}:
        issues.append(Issue("citation_check_source_mismatch", "/citation_check_target/assessed_source_id", sid))
    if not step_input["passages"]:
        issues.append(Issue("citation_check_without_text", "/passages", "a citation check needs given text"))
    for i, passage in enumerate(step_input["passages"]):
        if passage["source_id"] != sid:
            issues.append(Issue("citation_check_passage_not_assessed_work", f"/passages/{i}/source_id", passage["source_id"]))
    if set(allow["passage_ids"]) != records["passage_ids"]:
        issues.append(Issue("citation_check_allowlist_mismatch", "/allowlist/passage_ids", "must equal the given passages"))
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
    if task_type in CANDIDATE_TASKS + REVIEW_TASKS + CITATION_CHECK_TASKS:
        _check_utf8_text(data, report)
    validator = Draft202012Validator(step_output_schema(task_type))
    schema_errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    for err in schema_errors:
        report.issues.append(
            Issue("schema_invalid", "/" + "/".join(map(str, err.absolute_path)), err.message)
        )
    if report.issues:
        # A step gets one repair, so the first report names what the rules would reject as well as what the schema
        # does; a draft whose shape the rules cannot read is reported on its schema errors alone (slice 13a, run 5).
        _semantic_checks_best_effort(step_input, data, report)
    else:
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
        _semantic_checks(step_input, output_type, result, report)

    if task_type in CANDIDATE_TASKS + REVIEW_TASKS + CITATION_CHECK_TASKS:
        # Diagnostics may echo rejected keys or values, including from the best-effort pass.
        # Escape unencodable characters so storage and repair keep the invalid verdict.
        for issue in report.issues + report.warnings:
            for name in ("path", "message"):
                text = getattr(issue, name)
                try:
                    text.encode("utf-8")
                except UnicodeEncodeError:
                    setattr(issue, name, text.encode("utf-8", "backslashreplace").decode("utf-8"))
    return report


def _check_utf8_text(data: Any, report: ValidationReport) -> None:
    """Check values and keys even on schema-invalid candidate outputs; report each path once."""
    seen: set[str] = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                if path not in seen:
                    report.issues.append(Issue("text_not_encodable", path, "text must be encodable as UTF-8"))
                    seen.add(path)
        elif isinstance(value, dict):
            for key, item in value.items():
                child = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
                walk(key, child)
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, path + f"/{index}")

    walk(data, "")


def _semantic_checks_best_effort(step_input: dict[str, Any], data: Any, report: ValidationReport) -> None:
    """The rule checks on a draft the schema already rejected: what they can read, they report; what they cannot
    (a missing field, a wrong type) ends the pass without a trace, because the schema issue already says it."""
    if not isinstance(data, dict):
        return
    outputs = TASK_OUTPUTS[step_input["task_type"]]
    if len(outputs) == 1:
        output_type, result = outputs[0], data
    else:
        present = [o for o in outputs if isinstance(data.get(WRAPPER_KEYS[o]), dict)]
        if len(present) != 1:
            return
        output_type, result = present[0], data[WRAPPER_KEYS[present[0]]]
    probe = ValidationReport()
    try:
        _semantic_checks(step_input, output_type, result, probe)
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        return
    # Only breaches on another branch than a schema error: a rule that trips over the same field the schema already
    # rejected (a value too long, a list too short) would say the same thing twice.
    flagged = [i.path for i in report.issues]

    def elsewhere(path: str) -> bool:
        return path != "$" and not any(path == f or path.startswith(f + "/") or f.startswith(path + "/") for f in flagged)

    report.issues.extend(i for i in probe.issues if elsewhere(i.path) or (
        step_input["task_type"] in REPORT_TASKS + LINEAGE_TASKS + CANDIDATE_TASKS + REVIEW_TASKS + CITATION_CHECK_TASKS
        and (i.code in {"unknown_passage_id", "unknown_cell_id", "unknown_source_id", "unknown_column_id", "unknown_element_ref"}
             or step_input["task_type"] in REVIEW_TASKS)))
    report.warnings.extend(w for w in probe.warnings if elsewhere(w.path))


def _semantic_checks(step_input: dict[str, Any], output_type: str, result: dict[str, Any], report: ValidationReport) -> None:
    allow = {k: set(v) for k, v in step_input["allowlist"].items()}
    if output_type == "GroundedAnswerDraft":
        _check_answer(step_input, allow, result, report)
        _check_phrasing(step_input, result, report)
        _check_math(step_input, result, report)
    elif output_type == "FollowupAnswer":
        _check_followup(allow, step_input, result, report)
    elif output_type == "AnswerReview":
        _check_review(step_input, result, report)
    elif output_type == "OwnerReview":
        _check_owner_review(step_input, result, report)
    elif output_type == "EvidenceCellDraft":
        _check_cells(step_input, allow, result, report)
    elif output_type == "LineageLinksDraft":
        _check_lineage_links(step_input, allow, result, report)
    elif output_type == "ClaimDecomposition":
        _check_claim_decomposition(step_input, allow, result, report)
    elif output_type == "ClaimAssessment":
        _check_claim_assessment(step_input, allow, result, report)
    elif output_type == "CitationCheck":
        _check_citation_check(step_input, allow, result, report)
    elif output_type == "TableColumnProposal":
        _check_column_proposal(step_input, result, report)
    elif output_type == "ResearchTitle":
        _check_title(step_input, result, report)
    elif output_type == "VocabularyLabels":
        _check_vocabulary_labels(allow, result, report)
    elif output_type == "CriterionProposal":
        _check_criterion_proposal(step_input, result, report)
    elif output_type in ("SearchQuery", "KillSearchQuery", "FollowupSearchQuery"):
        _check_search_query(result, report)
    elif output_type == "AbstractScreening":
        _check_abstract_screening(allow, result, report)
    elif output_type == "FulltextAdjudication":
        _check_fulltext_adjudication(step_input, allow, result, report)
    elif output_type == "ReportPlanDraft":
        _check_report_plan(step_input, allow, result, report)
    elif output_type == "ReportSectionDraft":
        _check_report_section(step_input, allow, result, report)
        _check_phrasing(step_input, result, report)
        _check_report_writing(step_input, result, report)
        _check_math(step_input, result, report, fields=_report_math_fields(result))
    elif output_type == "ReportReview":
        _check_report_review(step_input, result, report)


MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+\$", re.DOTALL)
# A command, an escaped brace or script mark, a braced sub/superscript, or the \( \[ delimiters the UI does not render
# (D61). A regex escape such as \bword or a Windows path also matches; neither occurred in the measured outputs.
LATEX_OUTSIDE_MATH = re.compile(r"\\(?:[A-Za-z]{2,}|[_^{}(\[])|[_^]\{")

# Shared by section validation and final assembly; physical band/energy gaps are exempt.
REPORT_BANNED = re.compile(
    r"\b(?:gaps?|open problems?|open questions?"
    r"|novel|novelty|first-ever|the first (?:study|work|paper|survey|review|attempt|to|time)"
    r"|first of its kind|for the first time|araştırma boşluğ\w*"
    r"|boşluk|boşluğ\w*|açık problem\w*|açık soru\w*|özgün\w*|yenilik\w*"
    r"|ilk kez|ilk defa|bir ilk|ilk çalışma\w*)\b", re.IGNORECASE,
)
REPORT_DEPTH_ORDER = {"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}
REPORT_SUPPORT_ORDER = {"analyst_inference": 0, "source_stated": 1}
MAX_REPORT_VALIDATION_CHARS = 262144


def report_banned_words(value: str) -> list[str]:
    text = _without_math(value)
    result = []
    for match in REPORT_BANNED.finditer(text):
        preceding = re.search(r"(\w+)[\s-]+$", text[:match.start()].lower())
        word = match.group().lower()
        if preceding and ((word in {"gap", "gaps"} and preceding.group(1) in {
            "band", "energy", "spectral", "optical", "mass"
        }) or (word.startswith(("boşluk", "boşluğ")) and preceding.group(1) in {"bant", "enerji"})):
            continue
        result.append(match.group())
    return result


def report_count_issues(text: str, count: dict, context: dict) -> list[Issue]:
    """Frozen validation records do not grant citation rights."""
    issues = []
    def add(code: str, message: str) -> None:
        issues.append(Issue(code, "/count", message))
    numerator, denominator, column = (count["numerator_source_ids"], count["denominator_source_ids"], count["column_id"])
    cells = {(c["source_version_id"], c["column_id"]): c for c in context.get("cells", [])}
    if len(set(numerator)) != len(numerator) or len(set(denominator)) != len(denominator) or not set(numerator) <= set(denominator):
        add("count_members_invalid", "duplicate or non-subset count members")
    if column not in context.get("column_ids", []) or any(
        sid not in context.get("source_ids", []) or (sid, column) not in cells for sid in set(numerator + denominator)
    ) or any(cells.get((sid, column), {}).get("state") == "not_applicable" for sid in denominator):
        add("count_member_not_in_snapshot", "member, column, cell or applicability missing from snapshot")
    members = [cells[(sid, column)] for sid in denominator if (sid, column) in cells]
    selected = [cells[(sid, column)] for sid in numerator if (sid, column) in cells]
    if len({c["reading_depth"] for c in members}) > 1:
        add("count_depth_mixed", "denominator mixes reading depths")
    if len({c["state"] for c in selected}) > 1 or len({json.dumps(c["value"], sort_keys=True) for c in selected if c["state"] == "value"}) > 1:
        add("count_value_mixed", "numerator mixes states or values")
    numbers = [int(n) if len(n) < 4000 else None for n in re.findall(r"\b\d+\b", _without_math(text))]
    allowed = {len(numerator), len(denominator)}
    if numbers and (any(n not in allowed for n in numbers) or not allowed <= set(numbers)):
        add("count_number_mismatch", "text integers disagree with member counts")
    return issues


def report_equation_issues(claim: dict, cited_passages: set[str], passages: dict[str, dict], *, origin_record: dict | None = None) -> list[Issue]:
    issues = []
    spans = _math_spans(claim["text"])
    if not (claim.get("equation_ref") or claim.get("equation_origin") is not None or any(s.startswith("$$") for s in spans)):
        return issues
    origin = claim.get("equation_origin")
    if origin is None:
        return [Issue("equation_origin_missing", "/equation_origin", "an equation requires its supplied passage origin")]
    pid = origin["passage_id"]
    if pid not in cited_passages:
        issues.append(Issue("equation_origin_not_cited", "/equation_origin/passage_id", "origin is not cited by this claim"))
    passage = passages.get(pid)
    if passage is None:
        issues.append(Issue("equation_origin_not_in_input", "/equation_origin/passage_id", "origin was not supplied"))
    passage = origin_record if origin_record is not None else passage
    if passage is None or not _math_spans(passage["text"]):
        issues.append(Issue("equation_origin_without_math", "/equation_origin/passage_id", "origin has no recognized math span"))
    if passage is not None and origin["text_source"] != passage.get("text_source"):
        issues.append(Issue("equation_origin_mismatch", "/equation_origin/text_source", "text_source differs from the origin passage"))
    return issues


def report_derived_issues(claim: dict, body: list[dict], depth: str | None) -> list[Issue]:
    issues = []
    if not claim["body_refs"]:
        issues.append(Issue("body_ref_missing", "/body_refs", "derived claim requires a body_ref"))
    if not body:
        return issues
    support = min(REPORT_SUPPORT_ORDER[b["support_type"]] for b in body)
    if REPORT_SUPPORT_ORDER[claim["support_type"]] > support:
        issues.append(Issue("derived_support_too_strong", "/support_type", "support exceeds the weakest body_ref"))
    depths = [REPORT_DEPTH_ORDER[b["reading_depth"]] for b in body if b.get("reading_depth") in REPORT_DEPTH_ORDER]
    if depth in REPORT_DEPTH_ORDER and depths and REPORT_DEPTH_ORDER[depth] > min(depths):
        issues.append(Issue("derived_depth_too_deep", "/body_refs", "citation depth exceeds the weakest body_ref"))
    return issues


def report_gap_issues(gap: dict, target: dict, passages: dict[str, dict], *, known_cells: set[str] | None = None,
                      known_passages: set[str] | None = None) -> list[Issue]:
    issues = []
    def add(code: str, message: str) -> None:
        issues.append(Issue(code, "", message))
    cells = {c["cell_id"]: c for c in target["cells"]}
    plan = target.get("plan") or {}
    basis_cells, basis_passages = gap["basis_cell_ids"], gap["basis_passage_ids"]
    if gap["kind"] == "stated_limitation":
        if not basis_cells and not basis_passages or any(cid not in (known_cells if known_cells is not None else cells) for cid in basis_cells) or any(pid not in (known_passages if known_passages is not None else passages) for pid in basis_passages):
            add("gap_basis_missing", "stated limitation needs supplied basis records")
        if any(cid not in cells or cells[cid]["column_id"] != plan.get("limitations_column_id") for cid in basis_cells) or any(pid not in passages for pid in basis_passages):
            add("gap_basis_foreign", "basis must belong to this section's limitations input")
    elif gap["kind"] == "conflicting_evidence":
        v_keys = {s["claim_key"] for s in target["prior_summaries"] if s["section_id"] == "V"}
        if not gap["basis_claim_keys"] or any(k not in v_keys for k in gap["basis_claim_keys"]):
            add("conflict_gap_without_v_claim", "conflict basis requires supplied V claim keys")
    elif gap["kind"] == "corpus_absence":
        context = target.get("validation_context") or {}
        frozen = {c["cell_id"]: c for c in context.get("cells", [])}
        selected = [frozen.get(cid) for cid in basis_cells]
        columns = {c["column_id"] for c in selected if c}
        if len(basis_cells) < 3 or len(set(basis_cells)) != len(basis_cells) or None in selected or len(columns) != 1:
            add("gap_absence_basis_invalid", "basis needs three unique frozen cells in one column")
        else:
            column = next(iter(columns))
            applicable = {c["cell_id"] for c in frozen.values() if c["column_id"] == column and c["reading_depth"] == "full_text" and c["state"] != "not_applicable"}
            if set(basis_cells) != applicable or any(c["reading_depth"] != "full_text" or c["state"] != "not_found_in_inspected_scope" for c in selected):
                add("gap_absence_basis_invalid", "basis must equal all applicable full-text absence cells")
            if not any(c["gap_id"] == gap["gap_id"] and c["column_id"] == column and set(c["basis_cell_ids"]) == set(basis_cells) for c in target["gap_candidates"]):
                add("gap_absence_basis_invalid", "basis differs from supplied code candidate")
    return issues


def report_vii_issues(claim: dict, gap_ids: set[str], future_cell: bool) -> list[Issue]:
    issues = []
    refs = [ref for ref in claim["gap_refs"] if ref in gap_ids]
    if not refs and not future_cell:
        issues.append(Issue("vii_claim_without_basis", "", "lacks a basis"))
    if claim["support_type"] == "analyst_inference" and not refs:
        issues.append(Issue("vii_inference_without_gap", "/gap_refs", "lacks a gap"))
    return issues


def _without_math(text: str) -> str:
    """LaTeX math reads as one word, so its symbols and periods neither count as words nor split sentences."""
    return MATH.sub("X", text)


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    while index > slashes and text[index - slashes - 1] == "\\":
        slashes += 1
    return slashes % 2 == 1


def _math_spans(text: str) -> list[str]:
    spans: list[str] = []
    start = 0
    while start < len(text):
        if text[start] != "$" or _is_escaped(text, start):
            start += 1
            continue
        width = 2 if text[start:start + 2] == "$$" else 1
        end = start + width
        while end < len(text):
            if width == 1 and text[end] == "\n":
                break
            if text[end:end + width] == "$" * width and not _is_escaped(text, end):
                spans.append(text[start:end + width])
                start = end + width
                break
            end += 1
        else:
            start += width
            continue
        if end < len(text) and width == 1 and text[end] == "\n":
            start += width
    return spans


def _math_span_is_well_formed(span: str) -> bool:
    depth = 0
    for i, char in enumerate(span):
        if _is_escaped(span, i):
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    if depth:
        return False
    environments: list[str] = []
    for match in re.finditer(r"\\(begin|end)\{([^{}]+)\}", span):
        if match.group(1) == "begin":
            environments.append(match.group(2))
        elif not environments or environments.pop() != match.group(2):
            return False
    return not environments


def math_not_well_formed(text: str) -> bool:
    dollars = sum(char == "$" and not _is_escaped(text, i) for i, char in enumerate(text))
    return bool(dollars % 2 or any(not _math_span_is_well_formed(span) for span in _math_spans(text)))


def has_number_or_math(text: str) -> bool:
    return bool(re.search(r"\d", text)) or bool(_math_spans(text))


def value_has_number_or_math(value: Any) -> bool:
    """A cell value that states a number, or text with a number or equation; choice option ids do not count."""
    if not isinstance(value, dict):
        return False
    number = value.get("number")
    return (isinstance(number, (int, float)) and not isinstance(number, bool)) or any(
        isinstance(v, str) and has_number_or_math(v) for k, v in value.items() if k != "option_ids")


def _rests_only_on_ocr(passages: list[dict[str, Any] | None]) -> bool:
    return bool(passages) and all(p is not None and p.get("text_source") == "ocr" for p in passages)


def _check_math(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport,
                fields: list[tuple[str, str]] | None = None) -> None:
    """Block malformed report math; ordinary answers and extraction-quality findings retain warnings (D51)."""
    if fields is None:
        fields = [(f"/claims/{i}/text", c["text"]) for i, c in enumerate(draft["claims"])]
        fields += [(f"/limitations/{i}/text", lim["text"]) for i, lim in enumerate(draft["limitations"])]
        fields += [(f"/unanswered_aspects/{i}", text) for i, text in enumerate(draft["unanswered_aspects"])]
    for path, text in fields:
        if math_not_well_formed(text):
            findings = report.issues if step_input["task_type"] == "report_section" else report.warnings
            findings.append(Issue("math_not_well_formed", path,
                                         "math delimiters, braces or environments are not balanced"))
        if match := LATEX_OUTSIDE_MATH.search(MATH.sub(" ", text)):
            # Undelimited LaTeX reaches the reader as raw source; repair wraps it in $…$ before the answer is stored.
            report.issues.append(Issue("math_without_delimiters", path,
                                       f"{match.group(0)!r} is LaTeX outside $…$; wrap the expression in $…$ or $$…$$"))

    passages = {p["passage_id"]: p for p in step_input["passages"]}
    for i, claim in enumerate(draft["claims"]):
        cited = [passages[pid] for pid in claim["passage_ids"] if pid in passages]
        if _math_spans(claim["text"]) and len(cited) == len(claim["passage_ids"]) and cited \
                and all(p["reading_depth"] == "abstract" for p in cited):
            report.warnings.append(Issue("math_without_full_text", f"/claims/{i}/text",
                                         "the claim contains math but cites only abstract-level passages"))
        if has_number_or_math(claim["text"]) and _rests_only_on_ocr([passages.get(pid) for pid in claim["passage_ids"]]):
            report.warnings.append(Issue("ocr_numbers_unchecked", f"/claims/{i}/text",
                                         "the claim states a number or equation read only from OCR text; check it against the PDF page"))
    # D40 (r3): a quote that overlaps an equation Mathpix read from the page image rests on that reading, not the PDF's text.
    for j, anchor in enumerate(draft.get("citation_anchors") or []):
        passage = passages.get(anchor.get("passage_id"))
        if passage is None or passage.get("text_source") != "equation_ocr" or not isinstance(anchor.get("quote"), str):
            continue
        if (match := locate_anchor(anchor["quote"], passage["text"])) is None:
            continue
        start = passage["text"].find(match.text)
        end = start + len(match.text)
        if start >= 0 and any(m.start() < end and start < m.end() for m in re.finditer(r"\$\$.*?\$\$", passage["text"], re.S)):
            report.warnings.append(Issue("anchor_in_ocr_equation", f"/citation_anchors/{j}/quote",
                                         "the quote overlaps an equation read by Mathpix from the page image; check it against the PDF page"))


def _check_phrasing(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    """Check own-work wording and plural-source wording in the answer language.

    Prose is no longer checked against phrasebank frames (D43). Reports block both findings; answers warn.
    """
    is_report = step_input["task_type"] == "report_section"
    requested_language = wording.question_language(step_input) if is_report else draft["answer_language"]
    language = wording.checked_language(requested_language)
    if language is None:
        report.warnings.append(Issue("phrasing_not_checked", "/answer_language",
                                     f"no wording rules for {requested_language!r}"))
        if not is_report:
            return
        # Assembly also falls back to English for lexical checks in other languages.
        language = "en"
    # A claim reports what a cited source says; words naming the writer's own work would attribute it to this answer.
    for i, claim in enumerate(draft["claims"]):
        for phrase in wording.own_work_phrases(_without_math(claim["text"]), language):
            findings = report.issues if is_report else report.warnings
            findings.append(Issue("own_work_phrase_in_claim", f"/claims/{i}/text",
                                         f"{phrase!r} names this answer's own work, not a cited source"))
    # "Previous studies" and the like say several sources state it; a claim whose passages come from one source may not.
    source_of = {p["passage_id"]: p["source_id"] for p in step_input["passages"]}
    cells = {c["cell_id"]: c for c in (step_input.get("report_target") or {}).get("cells", [])}
    for i, claim in enumerate(draft["claims"]):
        sources = {source_of.get(pid) for pid in claim["passage_ids"]}
        if is_report:
            sources = {source_of.get(a["passage_id"]) if a["passage_id"] is not None
                       else cells.get(a["cell_id"], {}).get("source_version_id")
                       for a in draft["citation_anchors"] if a["claim_key"] == claim["claim_key"]}
        if None in sources or len(sources) != 1:
            continue
        for phrase in wording.plural_source_phrases(_without_math(claim["text"]), language):
            findings = report.issues if is_report else report.warnings
            findings.append(Issue("plural_sources_for_one_source", f"/claims/{i}/text",
                                       f"{phrase!r} speaks of several sources, but this claim cites one source; "
                                       "write it as what that one source states"))


def _check_report_writing(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    """D51's report writing rules, as warnings: a claim that keeps a long run of its anchor's words, and a claim naming
    an experiment or trial while every text it cites describes a simulation and names none."""
    language = wording.checked_language(wording.question_language(step_input)) or "en"
    passages = {p["passage_id"]: p.get("text") or "" for p in step_input["passages"]}
    cells = {c["cell_id"]: c for c in (step_input.get("report_target") or {}).get("cells", [])}
    for i, claim in enumerate(draft["claims"]):
        anchors = [a for a in draft["citation_anchors"] if a["claim_key"] == claim["claim_key"]]
        text = _without_math(claim["text"])
        quotes = [a["quote"] for a in anchors if isinstance(a.get("quote"), str)]
        longest = max((wording.copied_run(text, q) for q in quotes), default=0)
        if longest >= wording.COPIED_RUN_WORDS:
            report.warnings.append(Issue("claim_copies_anchor", f"/claims/{i}/text",
                                         f"{longest} consecutive words are the anchor's own; write the claim as a new sentence"))
        cited = [passages[a["passage_id"]] for a in anchors if a.get("passage_id") in passages]
        cited += [e.get("quote") or "" for a in anchors if a.get("cell_id") in cells
                  for e in cells[a["cell_id"]].get("evidence") or []]
        named = wording.experiment_phrases(text, language)
        if named and cited and wording.simulation_only(cited, language):
            report.warnings.append(Issue("experiment_wording_for_simulation", f"/claims/{i}/text",
                                         f"{named[0]!r} names an experiment or trial, but the cited text describes a simulation"))


def _check_review(step_input: dict[str, Any], review: dict[str, Any], report: ValidationReport) -> None:
    """Every claim under review gets exactly one verdict, addressed by its label."""
    labels = {c["claim_label"] for c in step_input.get("claims_under_review", [])}
    seen: set[str] = set()
    for i, item in enumerate(review["reviews"]):
        label = item["claim_label"]
        if label not in labels:
            report.issues.append(Issue("unknown_claim_label", f"/reviews/{i}/claim_label", label))
        if label in seen:
            report.issues.append(Issue("duplicate_claim_review", f"/reviews/{i}/claim_label", label))
        seen.add(label)
    for label in sorted(labels - seen):
        report.issues.append(Issue("claim_without_review", "/reviews", label))


def _check_lineage_links(step_input: dict[str, Any], allow: dict[str, set[str]],
                         draft: dict[str, Any], report: ValidationReport) -> None:
    """Check per-pair coverage and located evidence, never the meaning of a development relation."""
    target = step_input["lineage_target"]
    candidates = {c["from"]["source_id"]: c for c in target["candidates"]}
    passages = _lineage_records_by_id(step_input["passages"], "passage_id")
    seen: set[str] = set()
    for i, decision in enumerate(draft["decisions"]):
        path, sid = f"/decisions/{i}", decision["from_source_id"]
        if isinstance(sid, str):
            if sid in seen:
                report.issues.append(Issue("duplicate_candidate_decision", f"{path}/from_source_id", sid))
            seen.add(sid)
            if sid not in allow["source_ids"]:
                report.issues.append(Issue("unknown_source_id", f"{path}/from_source_id", sid))
            elif sid not in candidates:
                report.issues.append(Issue("decision_for_non_candidate", f"{path}/from_source_id", sid))
        link = decision["decision"] == "link"
        fields = ("relation", "what_changed", "support_type")
        if link:
            for field in fields:
                if decision[field] is None:
                    report.issues.append(Issue("link_field_missing", f"{path}/{field}", field))
            if decision["what_changed"] is not None and not valid_what_changed(decision["what_changed"]):
                report.issues.append(Issue("what_changed_empty", f"{path}/what_changed",
                                           f"what_changed requires non-whitespace text of 1 to {MAX_WHAT_CHANGED} characters"))
            if not decision["evidence"]:
                report.issues.append(Issue("link_without_evidence", f"{path}/evidence", "a link requires a located quote"))
        else:
            for field in fields:
                if decision[field] is not None:
                    report.issues.append(Issue("fields_on_non_link", f"{path}/{field}", field))
            if decision["evidence"]:
                report.issues.append(Issue("evidence_without_link", f"{path}/evidence", "only a link carries evidence"))
        if decision["relation"] == "independent_parallel" and decision["support_type"] != "source_stated":
            report.issues.append(Issue("independent_parallel_needs_source_stated", f"{path}/support_type", sid))
        # Reset for each pair: one located span may support different candidate decisions.
        located: set[tuple[str, str]] = set()
        cited: set[str] = set()
        for j, evidence in enumerate(decision["evidence"]):
            pid = evidence["passage_id"]
            evidence_path = f"{path}/evidence/{j}"
            if not isinstance(pid, str):
                continue  # Non-string IDs are schema errors; wrong-kind strings also get membership issues.
            cited.add(pid)
            passage = passages.get(pid)
            if pid not in allow["passage_ids"] or passage is None or passage["source_id"] != target["to"]["source_id"]:
                report.issues.append(Issue("unknown_passage_id", f"{evidence_path}/passage_id", pid))
            elif (anchor := locate_anchor(evidence["quote"], passage["text"])) is None:
                report.issues.append(Issue("anchor_not_in_passage", f"{evidence_path}/quote",
                                           f"{sid}:{pid}: the quoted text was not found in the cited passage"))
            elif (pid, anchor.text) in located:
                report.issues.append(Issue("duplicate_evidence_quote", f"{evidence_path}/quote",
                                           f"{sid}:{pid}: this quote repeats an earlier quote of the same passage"))
            else:
                located.add((pid, anchor.text))
        if (decision["support_type"] == "source_stated" and sid in candidates
                and not cited.intersection(candidates[sid]["mention_passage_ids"])):
            report.issues.append(Issue("source_stated_without_mention_passage", f"{path}/evidence", sid))
    for missing in sorted(set(candidates) - seen):
        report.issues.append(Issue("candidate_without_decision", "/decisions", missing))


def _check_nonblank_text(text: str, path: str, report: ValidationReport) -> bool:
    # SQLite length() stops at NUL; lone surrogates cannot reach UTF-8 storage.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        encodable = False
    else:
        encodable = True
    if not text.strip() or "\x00" in text or not encodable:
        report.issues.append(Issue("blank_text", path,
                                   "text must not be whitespace-only or contain NUL; it must be encodable as UTF-8"))
        return False
    return True


def _check_claim_decomposition(step_input: dict[str, Any], allow: dict[str, set[str]],
                               draft: dict[str, Any], report: ValidationReport) -> None:
    for field, code in (("source_ids", "unknown_source_id"), ("passage_ids", "unknown_passage_id")):
        for i, identifier in enumerate(draft[field]):
            if isinstance(identifier, str) and identifier not in allow[field]:
                report.issues.append(Issue(code, f"/{field}/{i}", identifier))
    seen: set[str] = set()
    for i, element in enumerate(draft["elements"]):
        ref = element["element_ref"]
        if ref in seen:
            report.issues.append(Issue("duplicate_element_ref", f"/elements/{i}/element_ref", ref))
        seen.add(ref)
        if ref != f"e{i + 1}":
            report.issues.append(Issue("element_ref_order", f"/elements/{i}/element_ref", "refs must be e1..en in list order"))
    texts = [(f"/{field}", draft[field]) for field in ("claim_statement", "critical_assumption", "validation_plan", "rationale")]
    texts += [(f"/conditions/{i}", text) for i, text in enumerate(draft["conditions"])]
    texts += [(f"/elements/{i}/text", element["text"]) for i, element in enumerate(draft["elements"])]
    if draft["nearest_simple_explanation"] is not None:
        texts.append(("/nearest_simple_explanation", draft["nearest_simple_explanation"]))
    for path, text in texts:
        _check_nonblank_text(text, path, report)
    if draft["nearest_simple_explanation"] is not None and not step_input["candidate_target"]["basis"]:
        report.issues.append(Issue("nearest_explanation_without_basis", "/nearest_simple_explanation", "no basis was shown"))
    if match := VALIDATION_PLAN_DESIGN_TERMS.search(draft["validation_plan"]):
        report.issues.append(Issue("validation_plan_design_terms", "/validation_plan", f"experiment-design term: {match.group()}"))


def _check_claim_assessment(step_input: dict[str, Any], allow: dict[str, set[str]],
                            draft: dict[str, Any], report: ValidationReport) -> None:
    """Check coverage, consistency and quote location; never whether evidence supports the relation."""
    passages = _lineage_records_by_id(step_input["passages"], "passage_id")
    sid = step_input["candidate_target"]["assessed_source_id"]

    def evidence_checks(items: list[dict[str, Any]], path: str) -> None:
        # One span may support several cells. Duplicates are refused within each evidence list only.
        located: set[tuple[str, str]] = set()
        for j, item in enumerate(items):
            pid = item["passage_id"]
            if not isinstance(pid, str):
                continue
            passage = passages.get(pid)
            item_path = f"{path}/{j}"
            if pid not in allow["passage_ids"] or passage is None or passage["source_id"] != sid:
                report.issues.append(Issue("unknown_passage_id", f"{item_path}/passage_id", pid))
            elif (anchor := locate_anchor(item["quote"], passage["text"])) is None:
                report.issues.append(Issue("anchor_not_in_passage", f"{item_path}/quote",
                                           f"{sid}:{pid}: the quoted text was not found in the cited passage"))
            elif (pid, anchor.text) in located:
                report.issues.append(Issue("duplicate_evidence_quote", f"{item_path}/quote",
                                           f"{sid}:{pid}: this quote repeats an earlier quote of the same passage"))
            else:
                located.add((pid, anchor.text))

    seen: set[str] = set()
    relations: list[str] = []
    for i, cell in enumerate(draft["cells"]):
        path, ref = f"/cells/{i}", cell["element_ref"]
        if isinstance(ref, str):
            if ref not in allow["element_ids"]:
                report.issues.append(Issue("unknown_element_ref", f"{path}/element_ref", ref))
            if ref in seen:
                report.issues.append(Issue("duplicate_claim_cell", f"{path}/element_ref", ref))
            seen.add(ref)
        relation = cell["relation"]
        relations.append(relation)
        if relation in CANDIDATE_SUPPORT_RELATIONS:
            if cell["condition_alignment"] is None:
                report.issues.append(Issue("alignment_missing", f"{path}/condition_alignment", relation))
            if not cell["evidence"]:
                report.issues.append(Issue("support_without_evidence", f"{path}/evidence", "support needs a located quote"))
        elif relation == "no_match_in_supplied_text" and cell["condition_alignment"] is not None:
            report.issues.append(Issue("alignment_on_no_match", f"{path}/condition_alignment", relation))
        if cell["note"] is not None:
            _check_nonblank_text(cell["note"], f"{path}/note", report)
        evidence_checks(cell["evidence"], f"{path}/evidence")
    for element in step_input["candidate_target"]["version"]["elements"]:
        if element["element_id"] not in seen:
            report.issues.append(Issue("claim_cell_missing", "/cells", element["element_id"]))
    relevance = draft["work_relevance"]
    if relevance == "unrelated" and any(r != "no_match_in_supplied_text" for r in relations):
        report.issues.append(Issue("unrelated_needs_no_match_cells", "/work_relevance", relevance))
    if relevance == "related" and not any(r in CANDIDATE_SUPPORT_RELATIONS for r in relations):
        report.issues.append(Issue("related_needs_support_cell", "/work_relevance", relevance))
    if relevance == "uncertain" and "uncertain" not in relations:
        report.issues.append(Issue("uncertain_needs_uncertain_cell", "/work_relevance", relevance))
    whole = draft["states_whole_claim"]
    if whole and not draft["whole_claim_evidence"]:
        report.issues.append(Issue("whole_claim_without_evidence", "/whole_claim_evidence", "whole claim needs a located quote"))
    if not whole and draft["whole_claim_evidence"]:
        report.issues.append(Issue("whole_claim_evidence_without_flag", "/whole_claim_evidence", "flag is false"))
    if whole and relevance != "related":
        report.issues.append(Issue("whole_claim_needs_related", "/work_relevance", relevance))
    evidence_checks(draft["whole_claim_evidence"], "/whole_claim_evidence")
    _check_nonblank_text(draft["nearest_match_summary"], "/nearest_match_summary", report)


CITATION_CHECK_MAX_QUOTES = 8  # all parts together; the schema caps parts (4) and quotes per part (3)


def _check_citation_check(step_input: dict[str, Any], allow: dict[str, set[str]],
                          draft: dict[str, Any], report: ValidationReport) -> None:
    """Coverage, part spans and quote location for one citing sentence (D99); never whether a passage supports it.

    The rules are structural and fail closed: a missed positive is acceptable, a wrong one is not. Each part is a
    verbatim span of the sentence, found by position in sentence order, and the spans together leave out no word token
    but coordinating connectives (`citation_check_spans`). A quote is located only in the passage it names, a given
    passage of the pair's one work: a match in another given passage is named in the issue as a hint and never moved
    there. A located quote is refused when its tokens, the tokens next to it or its sentence may say something it does
    not (`quote_meaning_differs`). Each failure sends the step to repair; `derive_result` reads only an output with
    none."""
    target = step_input["citation_check_target"]
    sid, sentence = target["assessed_source_id"], target["sentence"]
    passages = _lineage_records_by_id(step_input["passages"], "passage_id")
    spans, left_out = citation_check_spans(sentence, draft["parts"])
    total = 0
    for i, part in enumerate(draft["parts"]):
        path = f"/parts/{i}"
        if spans[i] is None:
            report.issues.append(Issue("part_not_in_sentence", f"{path}/text",
                                       "copy each part's text exactly from the citing sentence, parts in sentence order"
                                       " and not overlapping"))
        evidence = part["evidence"]
        total += len(evidence)
        positive = part["assessment"] in ("stated", "partly")
        if positive and not evidence:
            report.issues.append(Issue("positive_part_without_quote", f"{path}/evidence",
                                       f"a '{part['assessment']}' part quotes at least one given passage"))
        if not positive and evidence:
            report.issues.append(Issue("quote_on_not_stated_part", f"{path}/evidence", "a not_stated part has no quote"))
        located: set[tuple[str, str]] = set()
        for j, item in enumerate(evidence):
            pid, item_path = item["passage_id"], f"{path}/evidence/{j}"
            passage = passages.get(pid)
            if pid not in allow["passage_ids"] or passage is None:
                report.issues.append(Issue("unknown_passage_id", f"{item_path}/passage_id", pid))
            elif passage["source_id"] != sid:
                report.issues.append(Issue("passage_not_assessed_source", f"{item_path}/passage_id", pid))
            elif (anchor := locate_anchor(item["quote"], passage["text"])) is None:
                message = f"{pid}: the quoted text was not found in the cited passage"
                if elsewhere := _passages_quoting(step_input, pid, item["quote"]):
                    message += (f"; it is in {', '.join(elsewhere)}. Cite the passage that contains the quote, or remove"
                                " this quote if that passage does not state the part")
                report.issues.append(Issue("anchor_not_in_passage", f"{item_path}/quote", message))
            elif (reason := quote_meaning_differs(item["quote"], passage["text"], anchor, part["text"])) is not None:
                report.issues.append(Issue("quote_meaning_differs", f"{item_path}/quote",
                                           f"{pid}: {MEANING_REASONS[reason]}"))
            elif (pid, anchor.text) in located:
                report.issues.append(Issue("duplicate_evidence_quote", f"{item_path}/quote",
                                           f"{pid}: this quote repeats an earlier quote of the same passage"))
            else:
                located.add((pid, anchor.text))
    if total > CITATION_CHECK_MAX_QUOTES:
        report.issues.append(Issue("too_many_quotes", "/parts", f"{total} quotes; give at most {CITATION_CHECK_MAX_QUOTES}"))
    if draft["covers_whole_sentence"] is not True:
        report.issues.append(Issue("sentence_not_covered", "/covers_whole_sentence",
                                   "split the sentence into parts that together cover everything it claims"))
    if left_out:
        report.issues.append(Issue("parts_leave_out_words", "/parts",
                                   "no part holds these words of the sentence: " + ", ".join(left_out[:10])
                                   + "; every word but and, or, but, while and whereas belongs to a part"))


def citation_check_anchors(step_input: dict[str, Any], draft: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Per part, per quote of a citation check: whether the backend located it (and no meaning difference refused it),
    the passage's own located words, never the model's quote, and the passage's kind, so a result read from both an
    abstract and PDF pages says which one each quote came from."""
    passages = _lineage_records_by_id(step_input["passages"], "passage_id")
    allowed = set(step_input["allowlist"]["passage_ids"])
    sid = step_input["citation_check_target"]["assessed_source_id"]
    out = []
    for part in draft["parts"]:
        anchors = []
        for item in part["evidence"]:
            passage = passages.get(item["passage_id"])
            given = passage is not None and item["passage_id"] in allowed and passage["source_id"] == sid
            anchor = locate_anchor(item["quote"], passage["text"]) if given else None
            usable = anchor is not None and quote_meaning_differs(
                item["quote"], passage["text"], anchor, part["text"]) is None
            anchors.append({"passage_id": item["passage_id"], "quote": item["quote"], "located": usable,
                            "anchor_text": anchor.text if usable else None,
                            "anchor_match": anchor.kind if usable else None, "ratio": anchor.ratio if usable else None,
                            "passage_kind": passage["locator"]["kind"] if given else None})
        out.append(anchors)
    return out


def _check_cells(step_input: dict[str, Any], allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    """Every target column is answered once, in its format, from quoted passages of the one source given (D27, D37)."""
    columns = {c["column_id"]: c for c in step_input["extraction_target"]["columns"]}
    passage_text = {p["passage_id"]: p["text"] for p in step_input["passages"]}
    seen: set[str] = set()
    for i, cell in enumerate(draft["cells"]):
        path, column_id, state = f"/cells/{i}", cell["column_id"], cell["state"]
        if column_id not in columns:
            report.issues.append(Issue("unknown_column_id", f"{path}/column_id", column_id))
            continue
        if column_id in seen:
            report.issues.append(Issue("duplicate_column_answer", f"{path}/column_id", column_id))
        seen.add(column_id)
        try:
            check_value(columns[column_id], state, cell["value"])
        except InvalidTableInput as exc:
            report.issues.append(Issue("invalid_cell_value", f"{path}/value", f"{column_id}: {exc}"))
        cited = [e["passage_id"] for e in cell["evidence"]]
        located: set[tuple[str, str]] = set()
        for j, item in enumerate(cell["evidence"]):
            if item["passage_id"] not in allow["passage_ids"]:
                report.issues.append(Issue("unknown_passage_id", f"{path}/evidence/{j}/passage_id", item["passage_id"]))
            elif (anchor := locate_anchor(item["quote"], passage_text[item["passage_id"]])) is None:
                message = f"{column_id}:{item['passage_id']}: the quoted text was not found in the cited passage"
                if elsewhere := _passages_quoting(step_input, item["passage_id"], item["quote"]):
                    message += (f"; it is in {', '.join(elsewhere)} of the same source. Cite the passage that contains the quote,"
                                " or remove this evidence item if that passage does not support the answer")
                report.issues.append(Issue("anchor_not_in_passage", f"{path}/evidence/{j}/quote", message))
            elif (item["passage_id"], anchor.text) in located:
                # Several spans of one passage are separate evidence (D43); the same located words twice add nothing.
                report.issues.append(Issue("duplicate_evidence_quote", f"{path}/evidence/{j}/quote",
                                           f"{column_id}:{item['passage_id']}: this quote repeats an earlier quote of the same passage"))
            else:
                located.add((item["passage_id"], anchor.text))
        if state in ("value", "unknown") and not cited:
            report.issues.append(Issue(f"{state}_without_evidence", f"{path}/evidence",
                                       f"{column_id}: a '{state}' cell cites at least one passage with an exact quote"))
        if state == "not_found_in_inspected_scope" and cited:
            report.issues.append(Issue("evidence_for_not_found", f"{path}/evidence",
                                       f"{column_id}: nothing was found, so no passage is cited"))
        by_id = {p["passage_id"]: p for p in step_input["passages"]}
        if state == "value" and value_has_number_or_math(cell["value"]) and _rests_only_on_ocr([by_id.get(pid) for pid in cited]):
            report.warnings.append(Issue("ocr_numbers_unchecked", f"{path}/value",
                                         f"{column_id}: the value states a number or equation read only from OCR text; check it against the PDF page"))
        if state == "not_applicable" and not (cell["note"] or "").strip():
            report.issues.append(Issue("not_applicable_without_note", f"{path}/note", column_id))
        if cell["note"] and (match := LOCATOR_IN_TEXT.search(cell["note"])):
            report.issues.append(Issue("locator_in_note", f"{path}/note",
                                       f"remove {match.group(0)!r}; locators are attached from passage records"))
    for column_id in columns:
        if column_id not in seen:
            report.issues.append(Issue("column_without_answer", "/cells", column_id))


def _passages_quoting(step_input: dict[str, Any], cited: str, quote: str, limit: int = 3) -> list[str]:
    """Other passages of the cited passage's source version in this StepInput that contain the quote (D43).

    Named in the repair issue only; the evidence item still cites the passage the model gave, so moving it stays a model repair.
    """
    by_id = {p["passage_id"]: p for p in step_input["passages"]}
    source = by_id[cited]["source_id"]
    return [p["passage_id"] for p in step_input["passages"]
            if p["passage_id"] != cited and p["source_id"] == source and locate_anchor(quote, p["text"]) is not None][:limit]


def _check_column_proposal(step_input: dict[str, Any], proposal: dict[str, Any], report: ValidationReport) -> None:
    """Each suggestion is a column the table would accept, and no two columns share a name."""
    names = {c["name"].strip().casefold() for c in step_input["extraction_target"]["columns"]}
    for i, column in enumerate(proposal["columns"]):
        try:
            column_spec(column["name"], column["instruction"], column["answer_format"], column["options"],
                        column["allow_multiple"], column["unit_hint"])
        except InvalidTableInput as exc:
            report.issues.append(Issue("invalid_column_definition", f"/columns/{i}", str(exc)))
        name = column["name"].strip().casefold()
        if name in names:
            report.issues.append(Issue("duplicate_column_name", f"/columns/{i}/name", column["name"]))
        names.add(name)


# Locators come from application records, so claim text must not state its own page, equation, table, figure,
# section or DOI (acceptance case B). Quotations are not detected.
LOCATOR_IN_TEXT = re.compile(
    r"\b(?:pages?|pp?\.|sayfa(?:lar)?)\s*\d"
    r"|\b(?:eqs?\.|equations?|denklem(?:ler)?)\s*\(?\d"
    r"|\b(?:tables?|tab\.|figures?|figs?\.|tablo(?:lar)?|şekil(?:ler)?)\s*\d"
    r"|\b(?:sections?|sect\.|bölüm)\s*\d|§\s*\d"
    r"|\b10\.\d{4,9}/\S+",
    re.IGNORECASE,
)

ANCHOR_MIN_RATIO = 0.9  # provisional; see D24


@dataclass
class AnchorMatch:
    kind: str  # exact | normalized | fuzzy
    text: str  # the passage's own words, never the model's quote
    ratio: float


def _compact(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Case-folded NFKC word characters without spaces or punctuation, each mapped to its word's span in `text`."""
    words: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\w+", text):
        word = unicodedata.normalize("NFKC", m.group()).casefold()
        words.append(word)
        spans += [m.span()] * len(word)
    return "".join(words), spans


def locate_anchor(quote: str, passage: str) -> AnchorMatch | None:
    """Find a model quote in the passage it cites, tolerating PDF extraction damage.

    Spaces, punctuation, case and compatibility forms are ignored, so "p e = Q( √ 2 E b /N 0 )", ligatures and
    hyphenated line breaks still match. A near match must reach ANCHOR_MIN_RATIO over one contiguous region;
    a translated, paraphrased or spliced quote does not. The quote only locates text: it does not show support.
    """
    p, spans = _compact(passage)
    q, _ = _compact(quote)
    if not p or not q:
        return None
    if (at := p.find(q)) >= 0:
        exact = " ".join(quote.split()) in " ".join(passage.split())
        return AnchorMatch("exact" if exact else "normalized", passage[spans[at][0]:spans[at + len(q) - 1][1]], 1.0)
    seed = difflib.SequenceMatcher(None, p, q, autojunk=False).find_longest_match(0, len(p), 0, len(q))
    lo = max(0, seed.a - seed.b - len(q) // 5)
    hi = min(len(p), seed.a - seed.b + len(q) + len(q) // 5)
    blocks = [b for b in difflib.SequenceMatcher(None, p[lo:hi], q, autojunk=False).get_matching_blocks() if b.size >= 3]
    if not blocks:
        return None
    start, end = lo + blocks[0].a, lo + blocks[-1].a + blocks[-1].size
    ratio = 2 * sum(b.size for b in blocks) / (end - start + len(q))
    if ratio < ANCHOR_MIN_RATIO:
        return None
    return AnchorMatch("fuzzy", passage[spans[start][0]:spans[end - 1][1]], round(ratio, 3))


# Verify Citations (D99, review round 1): structural rules a citation check's parts and quotes must meet. They fail
# closed: a missed positive is acceptable, a wrong one is not. `locate_anchor` ignores punctuation and case and
# tolerates near matches, so "significantly improves" is found in "does not significantly improve", "p > 5" in
# "p >= 5" and "5 mW" in "5 MW"; these rules read the passage's own tokens around what it found.
# Review round 2: plain punctuation is the only text that is no token. Every other non-space character that is not a
# letter or a decimal digit (- − – / × · ^ ² ³ ° % ± < > = ≤ ≥ ≠ ~ ≈ …) is a token of its own, so it counts for
# coverage and for the quote-versus-span checks. Superscripts, subscripts and fractions are no word characters here.
CHECK_PUNCTUATION = frozenset(".,;:()[]'\"’“”")
_LETTER = r"(?:(?![¹²³¼-¾\u2070-\u209f\u2150-\u218f])[^\W_])"
CHECK_TOKEN = re.compile(
    rf"(?P<num>(?<![\w.])[-−+±]?\d+(?:[.,]\d+)*)|(?P<op><=|>=|!=|==)|(?P<word>{_LETTER}+(?:['’]{_LETTER}+)*)"
    r"|(?P<sym>[^\s.,;:()\[\]'\"’“”])")
CHECK_OPERATORS = frozenset({"<=", ">=", "!=", "==", "<", ">", "≤", "≥", "≠", "±", "=", "≦", "≧", "⩽", "⩾", "~", "≈"})
NEGATION_WORDS = frozenset({
    "not", "no", "never", "without", "cannot", "neither", "nor", "none", "nobody", "nothing", "nowhere",
    "fail", "fails", "failed", "failing", "unable", "lack", "lacks", "lacked", "lacking",
    "değil", "yok", "hiç", "hiçbir", "asla"})  # Turkish verb negation (-me/-ma) is not read
NEGATION_CONTRACTION = re.compile(r"[^\W\d_]+n['’]t$")  # don't, isn't, can't, won't, doesn't
CONNECTIVES = frozenset({"and", "or", "but", "while", "whereas"})  # the only words two parts may leave between them
COMPARISON_WORDS = {"more": "more", "greater": "more", "less": "less", "fewer": "less", "higher": "higher",
                    "lower": "lower", "larger": "larger", "smaller": "smaller", "better": "better", "worse": "worse",
                    **{w: "increase" for w in ("increase", "increases", "increased", "increasing")},
                    **{w: "decrease" for w in ("decrease", "decreases", "decreased", "decreasing")}}
# Review round 3: no punctuation bounds where a negation is read. A fixed window of the passage around the located span
# is read instead, ignoring dots, commas and line breaks: any negation in it outside the quote refuses the quote.
NEGATION_WINDOW_BEFORE = 250
NEGATION_WINDOW_AFTER = 80
MEANING_REASONS = {
    "boundary": "the quote does not start and end where the located words do (a number or word is cut); quote whole"
                " words exactly as the passage writes them",
    "number": "a number of the quote differs from the passage's (value, sign or decimal); quote it as written",
    "unit": "a unit of the quote differs from the passage's (units are read case by case); quote it as written",
    "comparison": "a comparison of the quote differs from the passage's (an operator or a more/less word); quote it as"
                  " written",
    "context": "the passage writes a number, unit, sign, percent or comparison right next to the quote; include it",
    "negation": "the passage holds a negation near the quote that the quote leaves out, or the quote one the passage"
                " does not;"
                " quote the clause including the negation, or do not use this passage for the part",
    "part_negation": "the quote and the part disagree on a negation, so it cannot support the part as stated",
}


@dataclass(frozen=True)
class CheckToken:
    text: str
    start: int
    end: int
    kind: str  # num | op | sym | word


def check_tokens(text: str) -> list[CheckToken]:
    out = []
    for m in CHECK_TOKEN.finditer(text):
        t = m.group(0)
        kind = m.lastgroup
        if kind == "sym" and t in CHECK_OPERATORS:
            kind = "op"
        out.append(CheckToken(t, m.start(), m.end(), kind))
    return out


def _token_key(token: CheckToken) -> str:
    if token.kind == "num":
        return token.text.replace("−", "-")
    return unicodedata.normalize("NFKC", token.text).casefold() if token.kind == "word" else token.text


def _negations(tokens: list[CheckToken]) -> int:
    return sum(1 for t in tokens if t.kind == "word"
               and (_token_key(t) in NEGATION_WORDS or NEGATION_CONTRACTION.match(_token_key(t))))


def citation_check_spans(sentence: str, parts: list[dict[str, Any]]) -> tuple[list[tuple[int, int] | None], list[str]]:
    """Where each part sits in the citing sentence, and the sentence's words no part holds.

    A part is a verbatim span of the sentence (spaces and case aside), found by its tokens at the first position after
    the part before it, so parts are in sentence order and never overlap; a part found nowhere there is None. Every
    token no span covers is left out unless it is a coordinating connective (and, or, but, while, whereas); a negation,
    a number, a variable or a comparison word never is. Punctuation is no token."""
    tokens = check_tokens(sentence)
    keys = [_token_key(t) for t in tokens]
    flat = " ".join(sentence.split()).casefold()
    spans: list[tuple[int, int] | None] = []
    covered: set[int] = set()
    at = 0
    for part in parts:
        wanted = [_token_key(t) for t in check_tokens(part["text"])]
        span = None
        if wanted and " ".join(part["text"].split()).casefold() in flat:
            span = next(((i, i + len(wanted)) for i in range(at, len(keys) - len(wanted) + 1)
                         if keys[i:i + len(wanted)] == wanted), None)
        spans.append(span)
        if span is not None:
            covered.update(range(*span))
            at = span[1]
    left = [t.text for i, t in enumerate(tokens) if i not in covered and keys[i] not in CONNECTIVES]
    return spans, left


def citation_check_covers(sentence: str, parts: list[dict[str, Any]]) -> bool:
    """Whether the parts are in the sentence and together leave nothing out: derived, never the model's word."""
    spans, left = citation_check_spans(sentence, parts)
    return all(span is not None for span in spans) and not left


def _adjacent(text: str, left: int, right: int) -> bool:
    return not text[left:right].strip()


def _dehyphenated(text: str, tokens: list[CheckToken]) -> list[CheckToken]:
    """`tokens` with a word hyphenated across a line break (`improve-` newline `ment`) joined into one word token."""
    out: list[CheckToken] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if (out and out[-1].kind == "word" and t.text == "-" and out[-1].end == t.start and i + 1 < len(tokens)
                and tokens[i + 1].kind == "word" and "\n" in (gap := text[t.end:tokens[i + 1].start])
                and not gap.strip()):
            out[-1] = CheckToken(out[-1].text + tokens[i + 1].text, out[-1].start, tokens[i + 1].end, "word")
            i += 2
            continue
        out.append(t)
        i += 1
    return out


def _cut_at(text: str, i: int) -> bool:
    """Whether the character at `i` would make a span ending or starting there cut a token: anything but whitespace,
    plain punctuation and the text's edge."""
    return 0 <= i < len(text) and not text[i].isspace() and text[i] not in CHECK_PUNCTUATION


def quote_meaning_differs(quote: str, passage: str, anchor: AnchorMatch, part_text: str | None = None) -> str | None:
    """Why a located quote may say something the passage's located words do not, as a `MEANING_REASONS` key, else None.

    For every match kind, exact included, read on the passage's own tokens that the located span touches (a number
    whose sign or digits fall outside the span counts whole): the numbers (value, sign, decimal), comparison operators
    as whole tokens and comparison words, and each unit after a number (case by case) must be the quote's; every match
    kind, fuzzy included, must give the quote's token sequence (words case-folded, numbers, units and symbols as
    written; only a word hyphenated across a line break is joined); no character but whitespace or plain punctuation
    may touch the span, and the token right next to it, with only spaces between, must not be a number, sign, percent,
    operator, or the unit of a number the span ends on; and the passage within 250 characters before the span and 80
    after (dots, commas and line breaks ignored) must hold no negation outside it, the quote and the span must agree on
    negations, and the quote must agree with its part on whether it is negated. A span the passage holds more than
    once is read at each place, and any one refusal refuses it."""
    q_tokens = _dehyphenated(quote, check_tokens(quote))
    p_tokens = check_tokens(passage)
    if not q_tokens:
        return "boundary"
    if part_text is not None and bool(_negations(q_tokens)) != bool(_negations(check_tokens(part_text))):
        return "part_negation"
    starts = [m.start() for m in re.finditer(re.escape(anchor.text), passage)] or [0]
    for start in starts:
        end = start + len(anchor.text)
        inside = [t for t in p_tokens if t.end > start and t.start < end]
        if not inside:
            return "boundary"
        # `locate_anchor` spans word characters only, so an operator, sign or percent the quote writes at its edge lies
        # just outside the span; it joins the span when the passage writes it right there.
        for edge in (0, -1):
            wanted = list(q_tokens if edge == 0 else reversed(q_tokens))
            for token in wanted:
                if token.kind not in ("op", "sym"):
                    break
                i = p_tokens.index(inside[edge]) + (-1 if edge == 0 else 1)
                if not 0 <= i < len(p_tokens) or p_tokens[i].kind not in ("op", "sym") or not _adjacent(
                        passage, *((p_tokens[i].end, inside[0].start) if edge == 0 else (inside[-1].end, p_tokens[i].start))):
                    break
                inside = [p_tokens[i], *inside] if edge == 0 else [*inside, p_tokens[i]]
        inside = _dehyphenated(passage, inside)
        w_start = max(0, inside[0].start - NEGATION_WINDOW_BEFORE)
        w_end = min(len(passage), inside[-1].end + NEGATION_WINDOW_AFTER)
        window = [t for t in p_tokens if t.end > w_start and t.start < w_end]
        if (_negations(q_tokens) != _negations(inside)
                or _negations([t for t in window if t not in inside])):
            return "negation"
        if [_token_key(t) for t in q_tokens if t.kind == "num"] != [_token_key(t) for t in inside if t.kind == "num"]:
            return "number"
        if ([t.text for t in q_tokens if t.kind in ("op", "sym")] != [t.text for t in inside if t.kind in ("op", "sym")]
                or Counter(COMPARISON_WORDS[k] for t in q_tokens if (k := _token_key(t)) in COMPARISON_WORDS)
                != Counter(COMPARISON_WORDS[k] for t in inside if (k := _token_key(t)) in COMPARISON_WORDS)):
            return "comparison"

        def units(tokens: list[CheckToken]) -> list[tuple[str, str | None]]:
            return [(_token_key(t), tokens[i + 1].text if i + 1 < len(tokens) and tokens[i + 1].kind != "num" else None)
                    for i, t in enumerate(tokens) if t.kind == "num"]
        if units(q_tokens) != units(inside):
            return "unit"
        # Review rounds 3–4: every match kind, fuzzy included, must give the quote's token sequence exactly as written,
        # case included, so no unit prefix can change anywhere (`A/mW` vs `A/MW`); only a sentence-start capital may
        # differ, on a word of three or more letters whose other letters are lower case. Fuzzy tolerance is left for
        # PDF damage only: whitespace, plain punctuation and a word hyphenated across a line break.
        if [_case_key(t) for t in q_tokens] != [_case_key(t) for t in inside]:
            return "boundary"
        # Read on characters, not tokens: a span that a non-space, non-punctuation character touches cuts a token
        # (`5 mW` of `5 mW/cm²`, `5e` of `5e-3`, `10` of `10^6`, `km` of `km/h`).
        if _cut_at(passage, inside[0].start - 1) or _cut_at(passage, inside[-1].end):
            return "boundary"
        before = [t for t in p_tokens if t.end <= inside[0].start]
        after = [t for t in p_tokens if t.start >= inside[-1].end]
        if before and _adjacent(passage, before[-1].end, inside[0].start) and before[-1].kind != "word":
            return "context"
        if after and _adjacent(passage, inside[-1].end, after[0].start) and (
                after[0].kind != "word" or inside[-1].kind == "num"):
            return "context"
    return None


def _case_key(token: CheckToken) -> str:
    """A token as written, except that a capital first letter is ignored on a word of three or more letters whose
    other letters are lower case ("The" / "the"); `mW` / `MW`, `mm` / `Mm` and `m` / `M` stay apart."""
    text = token.text
    if token.kind == "word" and len(text) >= 3 and text.isalpha() and text[1:].islower():
        return text.lower()
    return text


def locate_in_cell_evidence(quote: str, cell: dict[str, Any]) -> AnchorMatch | None:
    """A cell anchor is located in one of the cell's stored evidence quotes, never in the passage directly."""
    return next((match for evidence in cell.get("evidence", []) if evidence.get("quote")
                 if (match := locate_anchor(quote, evidence["quote"])) is not None), None)


def locate_citation_anchor(anchor: dict[str, Any], passages: dict[str, dict[str, Any]],
                           cells: dict[str, dict[str, Any]] | None = None) -> AnchorMatch | None:
    """Locate an answer or report anchor in its passage's text or its cell's stored quotes; None when the target
    is not given. An answer anchor names passages only."""
    if anchor.get("cell_id") is None:
        passage = passages.get(anchor["passage_id"])
        return locate_anchor(anchor["quote"], passage["text"]) if passage is not None else None
    cell = (cells or {}).get(anchor["cell_id"])
    return locate_in_cell_evidence(anchor["quote"], cell) if cell is not None else None


def _title_words(title: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’.-][^\W_]+)*", title, re.UNICODE))


def _check_title(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    """A discovery-time title is derived from the question and sources; it must be short and not a verbatim copy."""
    title = draft["title"].strip()
    words = _title_words(title)
    if not title:
        report.issues.append(Issue("title_empty", "/title", "title must not be empty"))
    elif words > 15:
        report.issues.append(Issue("title_too_long", "/title", f"expected at most 15 words, got {words}"))
    if title and title == step_input["question"]["text"].strip():
        report.issues.append(Issue("title_copies_question", "/title", "rewrite the title from the question and sources"))


def _check_vocabulary_labels(allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    """Every given phrase is labelled exactly once and nothing else is named (SW17.1).

    Both are errors, not warnings: an invented phrase is a phrase the question does not hold, and a missing label
    would silently leave the rule's assignment in place, which is what this step exists to correct.
    """
    allowed = allow.get("phrases", set())
    labelled: list[str] = []
    for index, label in enumerate(draft["labels"]):
        if label["phrase"] not in allowed:
            report.issues.append(Issue("phrase_not_in_allowlist", f"/labels/{index}/phrase", label["phrase"]))
        else:
            labelled.append(label["phrase"])
    counts = Counter(labelled)
    for phrase in sorted(set(allowed) - set(labelled)):
        report.issues.append(Issue("phrase_label_incomplete", "/labels", f"{phrase!r} was not labelled"))
    for phrase in sorted(p for p, n in counts.items() if n > 1):
        report.issues.append(Issue("phrase_label_incomplete", "/labels", f"{phrase!r} was labelled more than once"))


def _check_criterion_proposal(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    """The bounds one proposal must hold, enforced in code rather than left to the prompt (SW15.1).

    All of them are errors: a proposal that breaks one is not half-used, because the consensus over three runs would
    then count a part or a phrase that the step was not allowed to write. A phrase appearing in two parts is not an
    error; the consensus gives it the first part it stands in.

    A population or comparator the proposal names (SW23) must point at one of its own parts and must be words the
    question or the user's steering holds: an element the model worded itself is not the question's.
    """
    _check_question_elements(step_input, draft, report)
    if not any(part.get("role", "core") == "core" for part in draft["parts"]):
        report.issues.append(Issue("criterion_core_missing", "/parts", "at least one core part is required"))
    protected = {normalize_phrase(e["part"]) for e in draft.get("question_elements", [])}
    for index, part in enumerate(draft["parts"]):
        if part.get("role") == "aspect" and normalize_phrase(part["name"]) in protected:
            report.issues.append(Issue("question_element_not_core", f"/parts/{index}/role",
                                       "population and study-level comparator must be core"))
    low, high = PARTS_PER_PROPOSAL
    if not low <= len(draft["parts"]) <= high:
        report.issues.append(Issue("criterion_part_count", "/parts", f"expected {low} to {high}, got {len(draft['parts'])}"))
    least, most = PHRASES_PER_PART
    names = Counter(normalize_phrase(part["name"]) for part in draft["parts"])
    for name in sorted(n for n, count in names.items() if count > 1):
        report.issues.append(Issue("duplicate_criterion_part", "/parts", f"{name!r} names more than one part"))
    for index, part in enumerate(draft["parts"]):
        phrases = part["phrases"]
        if not least <= len(phrases) <= most:
            report.issues.append(Issue("criterion_phrase_count", f"/parts/{index}/phrases",
                                       f"expected {least} to {most}, got {len(phrases)}"))
        seen: Counter[str] = Counter()
        for position, phrase in enumerate(phrases):
            normalized = normalize_phrase(phrase)
            if not normalized:
                report.issues.append(Issue("criterion_phrase_empty", f"/parts/{index}/phrases/{position}", phrase))
                continue
            if len(normalized.split()) > MAX_PHRASE_WORDS:
                report.issues.append(Issue("criterion_phrase_too_long", f"/parts/{index}/phrases/{position}", phrase))
            seen[normalized] += 1
        for normalized in sorted(p for p, count in seen.items() if count > 1):
            report.issues.append(Issue("duplicate_criterion_phrase", f"/parts/{index}/phrases", normalized))


def _check_question_elements(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    parts = {normalize_phrase(part["name"]) for part in draft["parts"]}
    texts = [normalize_phrase(step_input["question"]["text"])]
    texts += [normalize_phrase(entry) for entry in step_input.get("user_steering") or [] if isinstance(entry, str)]
    roles: Counter[str] = Counter()
    pointed: dict[str, list[str]] = {}
    for index, element in enumerate(draft.get("question_elements", [])):
        path = f"/question_elements/{index}"
        roles[element["role"]] += 1
        part = normalize_phrase(element["part"])
        if part not in parts:
            report.issues.append(Issue("question_element_unknown_part", f"{path}/part", element["part"]))
        else:
            pointed.setdefault(part, []).append(element["role"])
        words = normalize_phrase(element["words"])
        if not words or not any(criterion_holds(words, text) for text in texts):
            report.issues.append(Issue("question_element_not_in_question", f"{path}/words", element["words"]))
    for role in sorted(r for r, count in roles.items() if count > 1):
        report.issues.append(Issue("duplicate_question_element", "/question_elements", f"{role!r} is named more than once"))
    for part in sorted(p for p, named in pointed.items() if len(set(named)) > 1):
        report.issues.append(Issue("question_elements_share_part", "/question_elements",
                                   f"population and comparator both point at {part!r}"))


SEARCH_QUERY_MAX_TERMS = 6  # chosen terms of both blocks together (D92)
SEARCH_QUERY_MAX_WORDS = 4
# Characters and operator words that belong to a query, not to a term; code writes every operator itself.
QUERY_SYNTAX = re.compile(r'["()\[\]{}*?:]|\b(?:AND|OR|NOT)\b')


def _check_search_query(draft: dict[str, Any], report: ValidationReport) -> None:
    """The bounds code enforces on a model-written query (D92): at most six chosen terms, both blocks filled, no term
    twice, and no term that carries query syntax or runs past four words. Each is an error, and the step gets one
    repair. What a term finds is not checked here: that is a count, read by code after the answer is accepted."""
    chosen = [(block, index, term["term"]) for block in ("setting", "task")
              for index, term in enumerate(draft[block])]
    if len(chosen) > SEARCH_QUERY_MAX_TERMS:
        report.issues.append(Issue("too_many_query_terms", "/",
                                   f"{len(chosen)} chosen terms; at most {SEARCH_QUERY_MAX_TERMS} in total"))
    for block in ("setting", "task"):
        if not draft[block]:
            report.issues.append(Issue("empty_query_block", f"/{block}", "the block holds no term"))
    listed = chosen + [(f"{block}_backup", index, term["term"]) for block in ("setting", "task")
                       for index, term in enumerate(draft[f"{block}_backup"])]
    seen: dict[str, str] = {}
    for block, index, term in listed:
        path = f"/{block}/{index}/term"
        # Blank terms retain query_term_empty; invalid storage text never enters issue messages below.
        if term.strip() and not _check_nonblank_text(term, path, report):
            continue
        normalized = normalize_phrase(term)
        if not normalized:
            report.issues.append(Issue("query_term_empty", path, term))
            continue
        if QUERY_SYNTAX.search(term):
            report.issues.append(Issue("query_syntax_in_term", path, term))
        if len(normalized.split()) > SEARCH_QUERY_MAX_WORDS:
            report.issues.append(Issue("query_term_too_long", path, term))
        if normalized in seen:
            report.issues.append(Issue("duplicate_query_term", path, f"{term!r} is also {seen[normalized]}"))
        else:
            seen[normalized] = path


USER_PLAN_REQUIRED_PROVIDER = "openalex"  # routing, semantic page, keyword pages and the citation chain (F18)


def check_user_search_plan(plan: Any) -> ValidationReport:
    """A search plan a person saved (UI parity S23a, F18), checked before it becomes a scope revision.

    The schema, then the same term rules a model-written query is held to (`_check_search_query`, D92), the
    criterion's bounds, and OpenAlex among the providers. Every finding is an error and nothing is repaired: the
    plan is refused with the reasons and the person corrects it.
    """
    report = ValidationReport(output_type="UserSearchPlan")
    report.issues += [Issue("user_plan_schema_invalid", "/" + "/".join(map(str, e.absolute_path)), e.message)
                      for e in canonical_validator("UserSearchPlan").iter_errors(plan)]
    if report.issues:
        return report
    _check_search_query(plan, report)
    if USER_PLAN_REQUIRED_PROVIDER not in plan["providers"]:
        report.issues.append(Issue("openalex_required", "/providers",
                                   "OpenAlex cannot be left out: the search and the citation chain run on it"))
    if plan["criterion"] is not None:
        _check_user_criterion(plan["criterion"], report)
    if report.ok:
        report.result = plan
    return report


def _check_user_criterion(criterion: dict[str, Any], report: ValidationReport) -> None:
    """The criterion of a person's plan: text that can be stored, at least one core part, no part name twice, and
    phrases of one to four words, none twice in a part. Unlike a model proposal it may have fewer than six phrases
    a part: the person is not asked to write an author's vocabulary."""
    _check_nonblank_text(criterion["text"], "/criterion/text", report)
    if not any(part["role"] == "core" for part in criterion["parts"]):
        report.issues.append(Issue("criterion_core_missing", "/criterion/parts", "at least one core part is required"))
    names: Counter[str] = Counter()
    for index, part in enumerate(criterion["parts"]):
        path = f"/criterion/parts/{index}"
        if not (_check_nonblank_text(part["name"], f"{path}/name", report)
                and _check_nonblank_text(part["definition"], f"{path}/definition", report)):
            continue
        names[normalize_phrase(part["name"])] += 1
        seen: set[str] = set()
        for position, phrase in enumerate(part["phrases"]):
            # NUL and lone surrogates cannot be stored; a whitespace-only phrase is `criterion_phrase_empty` below.
            if phrase.strip() and not _check_nonblank_text(phrase, f"{path}/phrases/{position}", report):
                continue
            normalized = normalize_phrase(phrase)
            if not normalized:
                report.issues.append(Issue("criterion_phrase_empty", f"{path}/phrases/{position}", phrase))
                continue
            if len(normalized.split()) > MAX_PHRASE_WORDS:
                report.issues.append(Issue("criterion_phrase_too_long", f"{path}/phrases/{position}", phrase))
            if normalized in seen:
                report.issues.append(Issue("duplicate_criterion_phrase", f"{path}/phrases/{position}", normalized))
            seen.add(normalized)
    for name in sorted(n for n, count in names.items() if count > 1):
        report.issues.append(Issue("duplicate_criterion_part", "/criterion/parts", f"{name!r} names more than one part"))
    for index, word in enumerate(criterion["exclusion_title_words"]):
        _check_nonblank_text(word, f"/criterion/exclusion_title_words/{index}", report)
    roles: Counter[str] = Counter()
    for index, element in enumerate(criterion["question_elements"]):
        roles[element["role"]] += 1
        for field in ("words", "part", "part_definition"):
            _check_nonblank_text(element[field], f"/criterion/question_elements/{index}/{field}", report)
    for role in sorted(r for r, count in roles.items() if count > 1):
        report.issues.append(Issue("duplicate_question_element", "/criterion/question_elements",
                                   f"{role!r} is named more than once"))


def _check_abstract_screening(allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    """Record-level defects are warnings, never errors (slice 09, SW9).

    A batch is not repaired and is not thrown away for one bad entry: the entry costs that record its proposal for
    this run, the rest of the batch stands, and a record left without two usable proposals stays
    `abstract_not_proposed` for a later discovery run to read. `workflow/abstract_stage.proposals_of` drops exactly
    the entries warned about here; the two must stay in step.
    """
    seen: set[str] = set()
    for index, record in enumerate(draft["records"]):
        cid = record["candidate_id"]
        if cid not in allow["candidate_ids"]:
            report.warnings.append(Issue("unknown_candidate_id", f"/records/{index}/candidate_id", cid))
        if cid in seen:
            report.warnings.append(Issue("duplicate_candidate_proposal", f"/records/{index}/candidate_id", cid))
        seen.add(cid)
        if record["label"] in ("candidate", "out_of_scope") and not record["quote"].strip():
            report.warnings.append(Issue("label_without_quote", f"/records/{index}/quote", cid))
    for cid in sorted(allow["candidate_ids"] - seen):
        report.warnings.append(Issue("candidate_without_proposal", "/records", cid))


def _check_fulltext_adjudication(step_input: dict[str, Any], allow: dict[str, set[str]], draft: dict[str, Any],
                                 report: ValidationReport) -> None:
    """Record-level defects are warnings, never errors (slice 12).

    One bad part does not throw the call away. `workflow/adjudication.proposals_of` reads the same defects as
    `unclear` for that part of this run: an unknown part, a part named twice, a part never named, a `present`
    with no quote, and a passage the step did not show. An unverified quote is not a defect here. The quote is
    looked up later, on the page, and a miss keeps the label.
    """
    target = step_input.get("adjudication_target") or {}
    expected = {part["name"] for part in target.get("parts", [])}
    seen: set[str] = set()
    for index, record in enumerate(draft["parts"]):
        name = record["part"]
        if name not in expected:
            report.warnings.append(Issue("unknown_part", f"/parts/{index}/part", name))
        if name in seen:
            report.warnings.append(Issue("duplicate_part", f"/parts/{index}/part", name))
        seen.add(name)
        if record["label"] == "present" and not record["quote"].strip():
            report.warnings.append(Issue("label_without_quote", f"/parts/{index}/quote", name))
        if record["label"] == "present" and record.get("passage_id") not in allow["passage_ids"]:
            report.warnings.append(Issue("passage_not_in_allowlist", f"/parts/{index}/passage_id", name))
    for name in sorted(expected - seen):
        report.warnings.append(Issue("part_without_proposal", "/parts", name))


def _report_phrasing_fields(draft: dict[str, Any]) -> list[tuple[str, str]]:
    fields = [(f"/claims/{i}/text", claim["text"]) for i, claim in enumerate(draft["claims"])]
    fields += [(f"/insufficient_evidence/{i}/reason", entry["reason"])
               for i, entry in enumerate(draft["insufficient_evidence"])]
    return fields


def _report_math_fields(draft: dict[str, Any]) -> list[tuple[str, str]]:
    return [(f"/claims/{i}/text", claim["text"]) for i, claim in enumerate(draft["claims"])]


def _check_report_plan(step_input: dict[str, Any], allow: dict[str, set[str]],
                       draft: dict[str, Any], report: ValidationReport) -> None:
    for i, entry in enumerate(draft["glossary"]):
        if entry["passage_id"] not in allow["passage_ids"]:
            report.issues.append(Issue("unknown_passage_id", f"/glossary/{i}/passage_id", entry["passage_id"]))
    for i, axis in enumerate(draft["axes"]):
        if axis["column_id"] not in allow.get("column_ids", set()):
            report.issues.append(Issue("axis_column_not_in_allowlist", f"/axes/{i}/column_id", axis["column_id"]))
    for field, code in (("limitations_column_id", "limitations_column_not_in_allowlist"),
                        ("future_work_column_id", "future_work_column_not_in_allowlist")):
        column_id = draft[field]
        if column_id is not None and column_id not in allow.get("column_ids", set()):
            report.issues.append(Issue(code, f"/{field}", column_id))


def limitations_number_restated(text: str) -> bool:
    without_item_refs = re.sub(r"\b(?:item|öğe|madde)\s+\d+\b", "", text, flags=re.IGNORECASE)
    return re.search(r"\d", without_item_refs) is not None


def limitations_claim_issues(claim: dict[str, Any]) -> list[Issue]:
    issues = []
    if limitations_number_restated(claim["text"]):
        issues.append(Issue("limitations_number_restated", "/text",
                            "VIII claim restates a number outside an item reference"))
    if claim["support_type"] == "source_stated" and not claim["passage_ids"] and not claim["cell_ids"]:
        issues.append(Issue("source_stated_without_evidence", "/support_type",
                            "source-stated claim has no passage or cell evidence"))
    return issues


def report_section_anchor_repair_context(step_input: dict[str, Any], draft: Any,
                                        issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair failing cell anchors with that cell's stored quotes, without altering the draft."""
    if (step_input.get("task_type") != "report_section" or not isinstance(draft, dict)
            or not isinstance(draft.get("citation_anchors"), list)):
        return []
    cells = {cell["cell_id"]: cell for cell in (step_input.get("report_target") or {}).get("cells", [])
             if cell["cell_id"] in step_input["allowlist"].get("cell_ids", [])}
    claims = draft.get("claims")
    claims = claims if isinstance(claims, list) else []
    failing = {int(match[1]) for issue in issues
               if issue.get("code") == "anchor_not_in_cell_evidence"
               and isinstance(issue.get("path"), str)
               and (match := re.fullmatch(r"/citation_anchors/(\d+)/quote", issue["path"]))}
    context = []
    for issue in issues:
        if issue.get("code") != "anchor_not_in_cell_evidence":
            continue
        path = issue.get("path")
        match = re.fullmatch(r"/citation_anchors/(\d+)/quote", path) if isinstance(path, str) else None
        if match is None or int(match[1]) >= len(draft["citation_anchors"]):
            continue
        index = int(match[1])
        anchor = draft["citation_anchors"][index]
        if not isinstance(anchor, dict) or not isinstance(anchor.get("cell_id"), str):
            continue
        cell = cells.get(anchor["cell_id"])
        if cell is None or not isinstance(anchor.get("quote"), str) or not isinstance(anchor.get("claim_key"), str):
            continue
        context.append({
            "anchor_index": index, "claim_key": anchor["claim_key"], "cell_id": cell["cell_id"],
            "quote": anchor["quote"],
            "allowed_quotes": [{"quote_number": number, "quote": quote}
                               for number, quote in enumerate(
                                   [e["quote"] for e in cell.get("evidence", []) if e.get("quote")], 1)],
            "claims": [{"claim_key": claim["claim_key"], "text": claim["text"],
                        "anchors": [{"anchor_index": n, "target": "cell" if a.get("cell_id") is not None else "passage",
                                     "failing": n in failing}
                                    for n, a in enumerate(draft["citation_anchors"])
                                    if isinstance(a, dict) and a.get("claim_key") == claim["claim_key"]]}
                       for claim in claims if isinstance(claim, dict)
                       and isinstance(claim.get("cell_ids"), list) and cell["cell_id"] in claim["cell_ids"]
                       and isinstance(claim.get("claim_key"), str) and isinstance(claim.get("text"), str)],
        })
    return context


def report_section_anchor_patch_eligible(issues: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> bool:
    indices = []
    for issue in issues:
        if issue.get("code") != "anchor_not_in_cell_evidence" or not isinstance(issue.get("path"), str):
            return False
        match = re.fullmatch(r"/citation_anchors/(\d+)/quote", issue["path"])
        if match is None:
            return False
        indices.append(int(match[1]))
    return bool(indices) and len(set(indices)) == len(indices) == len(pairs) and (
        sorted(indices) == sorted(pair["anchor_index"] for pair in pairs))


def validate_report_section_anchor_patch(step_input: dict[str, Any], draft: dict[str, Any],
                                         pairs: list[dict[str, Any]], raw: Any) -> ValidationReport:
    """Validate model choices before constructing any merged section."""
    report = ValidationReport()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            report.issues.append(Issue("invalid_json", "$", str(exc)))
            return report
    for err in sorted(canonical_validator("ReportSectionAnchorRepair").iter_errors(raw),
                      key=lambda e: list(map(str, e.absolute_path))):
        path = "/" + "/".join(map(str, err.absolute_path))
        report.issues.append(Issue("schema_invalid", path, err.message))
        if re.fullmatch(r"/anchors/\d+/quote_number", path) and err.validator == "minimum":
            report.issues.append(Issue("anchor_patch_quote_number", path, "quote numbers start at 1"))
        if path == "/anchors" and err.validator == "minItems":
            report.issues.append(Issue("anchor_patch_index", path, "must cover each failing anchor exactly once"))
        if re.fullmatch(r"/claims/\d+/context", path) and err.validator == "maxLength":
            report.issues.append(Issue("anchor_patch_removal", path, "context exceeds its bound"))
    if report.issues:
        return report
    for name in ("step_input_id", "scope_revision"):
        if raw[name] != step_input[name]:
            report.issues.append(Issue("envelope_mismatch", f"/{name}", f"expected {step_input[name]!r}, got {raw[name]!r}"))
    by_index = {pair["anchor_index"]: pair for pair in pairs}
    indices = [item["anchor_index"] for item in raw["anchors"]]
    if len(indices) != len(set(indices)) or set(indices) != set(by_index):
        report.issues.append(Issue("anchor_patch_index", "/anchors", "must cover each failing anchor exactly once"))
    for n, item in enumerate(raw["anchors"]):
        pair = by_index.get(item["anchor_index"])
        if item["quote_number"] is not None and (pair is None or not 1 <= item["quote_number"] <= len(pair["allowed_quotes"])):
            report.issues.append(Issue("anchor_patch_quote_number", f"/anchors/{n}/quote_number", "quote number is outside this cell's stored quotes"))
    affected = {draft["citation_anchors"][i]["claim_key"] for i in by_index}
    keys = {claim["claim_key"] for claim in draft["claims"]}
    seen = set()
    for n, item in enumerate(raw["claims"]):
        key = item["claim_key"]
        if key not in affected or key not in keys or key in seen:
            report.issues.append(Issue("anchor_patch_claim", f"/claims/{n}/claim_key", key))
        seen.add(key)
        if item["removed"]:
            consistent = (item["text"] is None and item["context"] is not None and item["reason"] is not None
                          and len(f"{key}: {item['context']}") <= 200)
        else:
            consistent = item["context"] is None and item["reason"] is None
        if not consistent:
            report.issues.append(Issue("anchor_patch_removal", f"/claims/{n}", "inconsistent removal fields or prefixed context exceeds 200 characters"))
    dropped = {item["anchor_index"] for item in raw["anchors"] if item["quote_number"] is None}
    removed = {item["claim_key"] for item in raw["claims"] if item["removed"]}
    supported = {anchor["claim_key"] for i, anchor in enumerate(draft["citation_anchors"]) if i not in dropped}
    for key in sorted(affected - supported - removed):
        report.issues.append(Issue("anchor_patch_claim_unsupported", "/claims", key))
    if report.ok:
        report.result = raw
    return report


def apply_report_section_anchor_patch(step_input: dict[str, Any], draft: dict[str, Any],
                                      pairs: list[dict[str, Any]], patch: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply a validated patch verbatim; selection and prose belong to the model."""
    merged = copy.deepcopy(draft)
    by_index = {pair["anchor_index"]: pair for pair in pairs}
    changes = []
    dropped = set()
    dropped_cells = []
    for item in patch["anchors"]:
        i, number = int(item["anchor_index"]), item["quote_number"]
        anchor = merged["citation_anchors"][i]
        change = {"anchor_index": i, "old_quote": anchor["quote"]}
        if number is None:
            dropped.add(i)
            dropped_cells.append((anchor["claim_key"], anchor["cell_id"]))
            change["removed"] = True
        else:
            anchor["quote"] = by_index[i]["allowed_quotes"][int(number) - 1]["quote"]
            change["new_quote"] = anchor["quote"]
        changes.append(change)
    merged["citation_anchors"] = [a for i, a in enumerate(merged["citation_anchors"]) if i not in dropped]
    for key, cell in dropped_cells:
        if not any(a["claim_key"] == key and a["cell_id"] == cell for a in merged["citation_anchors"]):
            for claim in merged["claims"]:
                if claim["claim_key"] == key:
                    claim["cell_ids"] = [cid for cid in claim["cell_ids"] if cid != cell]
    claims = {claim["claim_key"]: claim for claim in merged["claims"]}
    for item in patch["claims"]:
        key = item["claim_key"]
        change = {"claim_key": key, "old_text": claims[key]["text"]}
        if item["removed"]:
            merged["claims"] = [c for c in merged["claims"] if c["claim_key"] != key]
            merged["citation_anchors"] = [a for a in merged["citation_anchors"] if a["claim_key"] != key]
            merged["insufficient_evidence"].append({"context": f"{key}: {item['context']}", "reason": item["reason"]})
            change["removed"] = True
        else:
            if item["text"] is not None:
                claims[key]["text"] = item["text"]
            change["new_text"] = claims[key]["text"]
        changes.append(change)
    for name in ENVELOPE_FIELDS:
        merged[name] = step_input[name]
    return merged, changes


def report_section_max_words(step_input: dict[str, Any]) -> int | None:
    target = step_input["report_target"]
    return (target.get("plan") or {}).get("section_budgets", {}).get(target["section_id"], {}).get("max_words")


def report_section_words(draft: dict[str, Any]) -> int:
    """The words a section budget counts: claim texts and insufficient-evidence reasons (non-strings count 0)."""
    def words(rows: Any, field: str) -> int:
        rows = rows if isinstance(rows, list) else []
        return sum(len(r[field].split()) for r in rows if isinstance(r, dict) and isinstance(r.get(field), str))
    return words(draft.get("claims"), "text") + words(draft.get("insufficient_evidence"), "reason")


def report_section_repair_issues(failed: Any, repaired: Any, restore: bool = False,
                                 max_words: int | None = None) -> list[Issue]:
    """Check key coverage and kept insufficient-evidence contexts, including readable parts of invalid drafts. With
    `restore`, an issue's message also carries the dropped claim or entry, for a further repair whose failed output
    lacks it (D65). `max_words` is the section's word budget, which a failed draft over it lets a repair shorten
    reasons to meet (D87)."""
    def obj(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value if isinstance(value, dict) else {}

    def items(value: dict[str, Any], field: str) -> list[dict[str, Any]]:
        rows = value.get(field)
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    failed, repaired = obj(failed), obj(repaired)
    keys = lambda data: {r["claim_key"] for r in items(data, "claims") if isinstance(r.get("claim_key"), str)}
    old_entries = [r for r in items(failed, "insufficient_evidence")
                   if isinstance(r.get("context"), str) and isinstance(r.get("reason"), str)]
    new_entries = items(repaired, "insufficient_evidence")
    issues = []
    for key in sorted(keys(failed) - keys(repaired)):
        prefix = f"{key}: "
        if not any(isinstance(r.get("context"), str) and r["context"].startswith(prefix)
                   and r["context"][len(prefix):].strip() for r in new_entries):
            dropped = next((r for r in items(failed, "claims") if r.get("claim_key") == key), None)
            issues.append(Issue("repair_dropped_claim", "/claims", key + (
                "\nKeep this claim or record it in insufficient_evidence: " + json.dumps(dropped, ensure_ascii=False)
                if restore else "")))
    # Old entries are matched one-to-one to repaired ones (each repaired entry keeps at most one). A repaired entry keeps
    # an old one with the same context and the same reason; or with a non-empty reason without a banned word when the
    # old reason holds a banned word, or when the failed draft was over its word budget and the new reason is shorter:
    # the validator rejects the old text, so an exact-reason rule could never pass (D87).
    over_budget = max_words is not None and report_section_words(failed) > max_words

    def keeps(old: dict[str, Any], new: dict[str, Any]) -> bool:
        if new.get("context") != old["context"]:
            return False
        if new.get("reason") == old["reason"]:
            return True
        reason = new.get("reason")
        if not isinstance(reason, str) or not reason.strip() or report_banned_words(reason):
            return False
        return bool(report_banned_words(old["reason"])) or (
            over_budget and len(reason.split()) < len(old["reason"].split()))

    # A maximum one-to-one matching (augmenting paths), so the result does not depend on the order of the entries.
    edges = [[j for j, new in enumerate(new_entries) if keeps(old, new)] for old in old_entries]
    owner: dict[int, int] = {}

    def assign(i: int, seen: set[int]) -> bool:
        for j in edges[i]:
            if j not in seen:
                seen.add(j)
                if j not in owner or assign(owner[j], seen):
                    owner[j] = i
                    return True
        return False

    for i in range(len(old_entries)):
        assign(i, set())
    matched = set(owner.values())
    for i, entry in enumerate(old_entries):
        if i in matched:
            continue
        issues.append(Issue("repair_dropped_insufficient_evidence", "/insufficient_evidence", entry["context"] + (
            "\nRestore this entry exactly (reword its reason only to remove a banned word, or shorten it when the"
            " section is over its word budget): "
            + json.dumps({"context": entry["context"], "reason": entry["reason"]}, ensure_ascii=False)
            if restore else "")))
    return issues


EMPTY_REPORT_SECTION_MESSAGE = (
    "section has no claims or insufficient-evidence entries; write at least one claim supported by the given evidence, "
    "or one insufficient_evidence entry naming the missing material and why; never invent a claim, passage, cell, gap or quote"
)


def _check_report_section(step_input: dict[str, Any], allow: dict[str, set[str]],
                          draft: dict[str, Any], report: ValidationReport) -> None:
    if not draft["claims"] and not draft["insufficient_evidence"]:
        report.issues.append(Issue("empty_section", "/claims", EMPTY_REPORT_SECTION_MESSAGE))
    # Display-only records (for example glossary passages and failed rows) confer no use rights.
    allowed = {"psg_P": allow["passage_ids"], "cel_L": allow.get("cell_ids", set()),
               "col_C": allow.get("column_ids", set()),
               "srv_S": allow["source_ids"] | {c["source_version_id"] for c in step_input["report_target"]["cells"]}}
    codes = {"psg_P": "unknown_passage_id", "cel_L": "unknown_cell_id",
             "srv_S": "unknown_source_id", "col_C": "unknown_column_id"}
    for owner, key, kind, path in _report_id_fields(draft, REPORT_SECTION_ID_FIELDS):
        identifier = owner[key]
        permitted = allowed[kind]
        context = step_input["report_target"].get("validation_context") or {}
        if "/count/" in path:
            permitted = set(context.get("source_ids" if kind == "srv_S" else "column_ids", []))
        if path.startswith("/gaps/") and "/basis_cell_ids/" in path and draft["gaps"][int(path.split("/")[2])]["kind"] == "corpus_absence":
            permitted = {c["cell_id"] for c in context.get("cells", [])}
        if isinstance(identifier, str) and identifier not in permitted:
            report.issues.append(Issue(codes[kind], path, identifier))
    if draft["section_id"] != step_input["report_target"]["section_id"]:
        report.issues.append(Issue("report_section_mismatch", "/section_id", draft["section_id"]))
    target = step_input["report_target"]
    section_id = target["section_id"]
    passages = {p["passage_id"]: p for p in step_input["passages"] if p["passage_id"] in allow["passage_ids"]}
    cells = {c["cell_id"]: c for c in target["cells"]}
    prior = {s["claim_key"]: s for s in target["prior_summaries"]}
    keys = set()
    for field, text in _report_phrasing_fields(draft) + [(f"/subsections/{i}/heading", s["heading"]) for i, s in enumerate(draft["subsections"])] + [(f"/gaps/{i}/text", g["text"]) for i, g in enumerate(draft["gaps"])]:
        report.issues.extend(Issue("banned_word", field, repr(word)) for word in report_banned_words(text))
    words = report_section_words(draft)
    maximum = report_section_max_words(step_input)
    if maximum is not None and words > maximum:
        report.issues.append(Issue("section_word_count_over_budget", "/claims", f"{words} words exceed budget {maximum}"))
    # As in the answer path: every anchor names a claim of this draft and one of that claim's own passages or cells,
    # and every allowlisted passage or cell a claim cites has an anchor (save_claims links anchors by claim_key).
    cited = {c["claim_key"]: {("passage", p) for p in c["passage_ids"]} | {("cell", x) for x in c["cell_ids"]}
             for c in draft["claims"]}
    required = {(c["claim_key"], "passage", p) for c in draft["claims"] for p in c["passage_ids"] if p in allow["passage_ids"]}
    required |= {(c["claim_key"], "cell", x) for c in draft["claims"] for x in c["cell_ids"]
                 if x in allow.get("cell_ids", set())}
    seen: set[tuple[str, str, str]] = set()
    for i, anchor in enumerate(draft["citation_anchors"]):
        if (anchor["passage_id"] is None) == (anchor["cell_id"] is None):
            report.issues.append(Issue(
                "citation_anchor_target_count", f"/citation_anchors/{i}",
                "expected exactly one of passage_id/cell_id to be non-null",
            ))
            # An anchor naming both targets is already blocked here; neither target is reported missing a second time.
            seen.update((anchor["claim_key"], kind, target_id) for kind, target_id in
                        (("passage", anchor["passage_id"]), ("cell", anchor["cell_id"])) if target_id is not None)
            continue
        kind, target_id = ("passage", anchor["passage_id"]) if anchor["passage_id"] is not None else ("cell", anchor["cell_id"])
        if anchor["claim_key"] not in cited:
            report.issues.append(Issue("unknown_anchor_claim", f"/citation_anchors/{i}/claim_key", anchor["claim_key"]))
            continue
        if (kind, target_id) not in cited[anchor["claim_key"]]:
            report.issues.append(Issue("anchor_passage_not_cited", f"/citation_anchors/{i}/{kind}_id", target_id))
            continue
        seen.add((anchor["claim_key"], kind, target_id))
        # An identifier outside the allowlist is already reported as unknown above.
        given = allow["passage_ids"] if kind == "passage" else allow.get("cell_ids", set())
        if target_id in given and locate_citation_anchor(anchor, passages, cells) is None:
            code, where = (("anchor_not_in_passage", "the cited passage") if kind == "passage"
                           else ("anchor_not_in_cell_evidence", "one stored cell evidence quote"))
            report.issues.append(Issue(code, f"/citation_anchors/{i}/quote", f"the quote was not found in {where}"))
    for key, kind, target_id in sorted(required - seen):
        report.issues.append(Issue("missing_citation_anchor", "/citation_anchors",
                                   f"{key}:{target_id}: this citation requires an exact contiguous quote"))
    for i, claim in enumerate(draft["claims"]):
        path = f"/claims/{i}"
        key = claim["claim_key"]
        if key in keys or key in prior:
            report.issues.append(Issue("duplicate_claim_key", path + "/claim_key", key))
        keys.add(key)
        if key.rsplit(".", 1)[0] != section_id:
            report.issues.append(Issue("claim_key_section_mismatch", path + "/claim_key", f"prefix must be {section_id}"))
        anchors = [a for a in draft["citation_anchors"] if a["claim_key"] == key]
        report.issues.extend(Issue(issue.code, path + issue.path, issue.message) for issue in report_equation_issues(
            claim, {a["passage_id"] for a in anchors if a["passage_id"] is not None}, passages))
        if section_id in {"abstract", "I", "IX"}:
            for ref in claim["body_refs"]:
                if ref not in prior or prior[ref]["section_id"] not in {"III", "IV", "V", "VI", "VII", "VIII"}:
                    report.issues.append(Issue("body_ref_unknown", path + "/body_refs", ref))
            depths = [cells[a["cell_id"]].get("reading_depth") if a["cell_id"] in cells else
                      passages.get(a["passage_id"], {}).get("reading_depth") for a in anchors]
            depths = [d for d in depths if d in REPORT_DEPTH_ORDER]
            depth = min(depths, key=REPORT_DEPTH_ORDER.__getitem__) if depths else None
            report.issues.extend(Issue(issue.code, path + issue.path, issue.message) for issue in report_derived_issues(
                claim, [prior[r] for r in claim["body_refs"] if r in prior], depth))
        if claim["count"] is not None:
            report.issues.extend(Issue(issue.code, path + issue.path, issue.message) for issue in report_count_issues(
                claim["text"], claim["count"], target.get("validation_context") or {}))
        if draft["section_id"] == "VIII":
            report.issues.extend(Issue(issue.code, f"/claims/{i}{issue.path}", issue.message)
                                 for issue in limitations_claim_issues(claim))
        for j, gap_id in enumerate(claim["gap_refs"]):
            if gap_id not in allow.get("gap_ids", set()):
                report.issues.append(Issue("unknown_gap_ref", f"/claims/{i}/gap_refs/{j}", gap_id))
            elif section_id == "VI" and gap_id not in {g["gap_id"] for g in draft["gaps"]}:
                report.issues.append(Issue("gap_ref_unknown", f"/claims/{i}/gap_refs/{j}", "referenced candidate must be present in this section's gaps"))
        if section_id == "VII":
            accepted = {g["gap_id"] for g in (target.get("validation_context") or {}).get("accepted_gaps", [])}
            future = any(a["cell_id"] in cells and cells[a["cell_id"]]["column_id"] == (target.get("plan") or {}).get("future_work_column_id") for a in anchors)
            report.issues.extend(Issue(issue.code, path + issue.path, issue.message) for issue in report_vii_issues(claim, accepted, future))
    for i, gap in enumerate(draft["gaps"]):
        report.issues.extend(Issue(issue.code, f"/gaps/{i}" + issue.path, issue.message) for issue in report_gap_issues(gap, target, passages))


def _check_report_review(step_input: dict[str, Any], draft: dict[str, Any],
                         report: ValidationReport) -> None:
    claims = {claim["claim_key"]: section for section in step_input["report_target"]["review_sections"]
              for claim in section["claims"]}
    for i, finding in enumerate(draft["findings"]):
        key = finding["claim_key"]
        if key is not None and key not in claims:
            report.issues.append(Issue("review_claim_unknown", f"/findings/{i}/claim_key", key))


def _check_answer(step_input: dict[str, Any], allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    title_words = _title_words(draft["title"])
    if title_words > 15:
        report.issues.append(Issue("answer_title_too_long", "/title",
                                   f"expected at most 15 words, got {title_words}"))
    _check_cited_claims(step_input, allow, draft, report)
    for i, limitation in enumerate(draft["limitations"]):
        for j, sid in enumerate(limitation["source_ids"]):
            if sid not in allow["source_ids"]:
                report.issues.append(Issue("unknown_source_id", f"/limitations/{i}/source_ids/{j}", sid))


def _check_followup(allow: dict[str, set[str]], step_input: dict[str, Any], draft: dict[str, Any],
                    report: ValidationReport) -> None:
    """A follow-up answer: the grounded answer's claim, passage and anchor rules, and an outcome that says what it is.

    An answer (whole or in part) carries at least one claim; anything short of a whole answer names what the given
    passages leave open. A `not_answered` outcome may still report, with anchors, what the closest passages state.
    """
    _check_cited_claims(step_input, allow, draft, report)
    classified = _check_work_classifications(step_input, allow, draft, report)
    if draft["outcome"] != "not_answered" and not draft["claims"] and not classified:
        report.issues.append(Issue("followup_answer_without_claims", "/claims",
                                   f"outcome {draft['outcome']!r} needs at least one cited claim or classified work"))
    if draft["outcome"] != "answered" and not draft["unanswered_aspects"]:
        report.issues.append(Issue("followup_unanswered_without_aspect", "/unanswered_aspects",
                                   f"outcome {draft['outcome']!r} needs what the given passages do not say"))
    fields = [(f"/claims/{i}/text", c["text"]) for i, c in enumerate(draft["claims"])]
    fields += [(f"/unanswered_aspects/{i}", text) for i, text in enumerate(draft["unanswered_aspects"])]
    for i, work in enumerate(draft["work_classifications"]):
        fields += [(f"/work_classifications/{i}/memberships/{j}/group", m["group"]) for j, m in enumerate(work["memberships"])]
        if work["note"]:
            fields.append((f"/work_classifications/{i}/note", work["note"]))
    _check_math(step_input, draft, report, fields=fields)


MAX_WORK_GROUPS = 6  # distinct groups one follow-up answer may put works in (D66)


def work_group_key(label: str) -> str:
    """A group label as groups are compared and counted: case and spacing do not make another group."""
    return " ".join(label.casefold().split())


def _check_work_classifications(step_input: dict[str, Any], allow: dict[str, set[str]], draft: dict[str, Any],
                                report: ValidationReport) -> int:
    """A follow-up's per-work classification (D66): each record names one work by a passage of it; a classified
    record puts it in groups, each membership with a located anchor in a passage of the same work (any of its
    versions); the other statuses carry no membership and a note. One membership per group and record, a non-empty
    group label, at most MAX_WORK_GROUPS groups. Two records of one work (its versions, say) are not refused: the
    application merges them when it counts, and a warning says so. Returns the number of classified records."""
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    work_of = {s["source_id"]: s.get("work_id") or s["source_id"] for s in step_input.get("sources", [])}

    def work_id_of(pid: str) -> str:
        source = passages[pid]["source_id"]
        return work_of.get(source, source)
    seen_works: set[str] = set()
    groups: set[str] = set()
    classified = 0
    for i, work in enumerate(draft["work_classifications"]):
        path = f"/work_classifications/{i}"
        if work["passage_id"] not in allow["passage_ids"]:
            report.issues.append(Issue("unknown_passage_id", f"{path}/passage_id", work["passage_id"]))
            continue
        record_work = work_id_of(work["passage_id"])
        if record_work in seen_works:
            report.warnings.append(Issue("work_records_merged", f"{path}/passage_id",
                                         f"{record_work}: a second record of this work is merged with the first"))
        seen_works.add(record_work)
        if work["status"] == "classified":
            classified += 1
            if not work["memberships"]:
                report.issues.append(Issue("classified_work_without_group", f"{path}/memberships",
                                           "a classified work needs at least one group with an anchor"))
        else:
            if work["memberships"]:
                report.issues.append(Issue("unclassified_work_with_group", f"{path}/memberships",
                                           f"a {work['status']} record carries no group"))
            if not (work["note"] or "").strip():
                report.issues.append(Issue("unclassified_work_without_note", f"{path}/note",
                                           f"say why the work is {work['status']}"))
        own: set[str] = set()
        for j, item in enumerate(work["memberships"]):
            mpath = f"{path}/memberships/{j}"
            key = work_group_key(item["group"])
            if not key:
                report.issues.append(Issue("empty_work_group", f"{mpath}/group", "name the group"))
                continue
            if key in own:
                report.issues.append(Issue("duplicate_work_group", f"{mpath}/group", item["group"]))
            own.add(key)
            groups.add(key)
            if item["passage_id"] not in allow["passage_ids"]:
                report.issues.append(Issue("unknown_passage_id", f"{mpath}/passage_id", item["passage_id"]))
                continue
            if work_id_of(item["passage_id"]) != record_work:
                report.issues.append(Issue("membership_passage_other_work", f"{mpath}/passage_id",
                                           "cite a passage of the same work as the record"))
                continue
            if locate_citation_anchor({"passage_id": item["passage_id"], "quote": item["quote"]}, passages) is None:
                report.issues.append(Issue("anchor_not_in_passage", f"{mpath}/quote",
                                           f"{item['passage_id']}: the quoted sentence was not found in the cited passage"))
    if len(groups) > MAX_WORK_GROUPS:
        report.issues.append(Issue("too_many_work_groups", "/work_classifications",
                                   f"{len(groups)} groups; use at most {MAX_WORK_GROUPS}"))
    return classified


def _check_cited_claims(step_input: dict[str, Any], allow: dict[str, set[str]], draft: dict[str, Any],
                        report: ValidationReport) -> None:
    """Claim labels, allowlisted passages, D247's one-source rule and one located anchor per claim-passage pair."""
    labels: set[str] = set()
    cited_by_claim: dict[str, set[str]] = {}
    source_of = {p["passage_id"]: p["source_id"] for p in step_input["passages"]}
    for i, claim in enumerate(draft["claims"]):
        if match := LOCATOR_IN_TEXT.search(claim["text"]):
            report.issues.append(Issue("locator_in_claim_text", f"/claims/{i}/text",
                                       f"remove {match.group(0)!r}; locators are attached from passage records"))
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
        cited_by_claim[claim["claim_label"]] = set(claim["passage_ids"])
        # D247: a source_stated claim reports one source; merged claims were mostly only partly supported.
        sources = {source_of[pid] for pid in claim["passage_ids"] if pid in source_of}
        if claim["support_type"] == "source_stated" and len(sources) > 1:
            report.issues.append(Issue("source_stated_several_sources", f"/claims/{i}/passage_ids",
                                       f"{claim['claim_label']}: cites {len(sources)} sources; write one source_stated "
                                       "claim per source, each citing only that source's passages"))

    # A published citation must resolve to source-owned text so the evidence panel can show the exact highlighted
    # span (D27). D244 may prune anchor-only defects after validation; all other defects require bounded repair.
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    required_anchors = {
        (claim["claim_label"], pid)
        for claim in draft["claims"]
        for pid in claim["passage_ids"]
        if pid in allow["passage_ids"]
    }
    seen_anchors: set[tuple[str, str]] = set()
    for i, anchor in enumerate(draft["citation_anchors"]):
        pair = (anchor["claim_label"], anchor["passage_id"])
        if pair in seen_anchors:
            report.issues.append(Issue("duplicate_citation_anchor", f"/citation_anchors/{i}", ":".join(pair)))
        seen_anchors.add(pair)
        if anchor["claim_label"] not in cited_by_claim:
            report.issues.append(Issue("unknown_anchor_claim", f"/citation_anchors/{i}/claim_label", anchor["claim_label"]))
            continue
        if anchor["passage_id"] not in cited_by_claim[anchor["claim_label"]]:
            report.issues.append(Issue("anchor_passage_not_cited", f"/citation_anchors/{i}/passage_id", anchor["passage_id"]))
            continue
        if locate_citation_anchor(anchor, passages) is None:
            report.issues.append(Issue("anchor_not_in_passage", f"/citation_anchors/{i}/quote",
                                       f"{anchor['claim_label']}:{anchor['passage_id']}: the quoted sentence was not found in the cited passage"))
    for claim_label, passage_id in sorted(required_anchors - seen_anchors):
        report.issues.append(Issue("missing_citation_anchor", "/citation_anchors",
                                   f"{claim_label}:{passage_id}: this citation requires an exact contiguous quote"))


# Explicit paths keep record conversion out of prose, quotes, revision IDs and envelope metadata.
CANDIDATE_OUTPUT_ID_FIELDS = {
    "claim_decomposition": (("source_ids/*", "srv_S"), ("passage_ids/*", "psg_P")),
    "kill_search_query": (),
    "claim_assessment": (("cells/*/element_ref", "ele_E"), ("cells/*/evidence/*/passage_id", "psg_P"),
                         ("whole_claim_evidence/*/passage_id", "psg_P")),
}
CANDIDATE_INPUT_ID_FIELDS = (
    ("passages/*/passage_id", "psg_P"), ("passages/*/source_id", "srv_S"),
    ("sources/*/source_id", "srv_S"),
    ("allowlist/passage_ids/*", "psg_P"), ("allowlist/source_ids/*", "srv_S"),
    ("allowlist/element_ids/*", "ele_E"), ("candidate_target/basis/*/passage_id", "psg_P"),
    ("candidate_target/assessed_source_id", "srv_S"), ("candidate_target/version/elements/*/element_id", "ele_E"),
)
CITATION_CHECK_INPUT_ID_FIELDS = (
    ("passages/*/passage_id", "psg_P"), ("passages/*/source_id", "srv_S"),
    ("sources/*/source_id", "srv_S"),
    ("allowlist/passage_ids/*", "psg_P"), ("allowlist/source_ids/*", "srv_S"),
    ("citation_check_target/assessed_source_id", "srv_S"),
)
CITATION_CHECK_OUTPUT_ID_FIELDS = (("parts/*/evidence/*/passage_id", "psg_P"),)
LINEAGE_OUTPUT_ID_FIELDS = (
    ("decisions/*/from_source_id", "srv_S"), ("decisions/*/evidence/*/passage_id", "psg_P"),
)
LINEAGE_INPUT_ID_FIELDS = (
    ("passages/*/passage_id", "psg_P"), ("passages/*/source_id", "srv_S"),
    ("sources/*/source_id", "srv_S"),
    ("allowlist/passage_ids/*", "psg_P"), ("allowlist/source_ids/*", "srv_S"),
    ("lineage_target/to/source_id", "srv_S"), ("lineage_target/to/cells/*/cell_id", "cel_L"),
    ("lineage_target/candidates/*/from/source_id", "srv_S"),
    ("lineage_target/candidates/*/from/cells/*/cell_id", "cel_L"),
    ("lineage_target/candidates/*/mention_passage_ids/*", "psg_P"),
)

REPORT_PLAN_ID_FIELDS = (
    ("glossary/*/passage_id", "psg_P"), ("axes/*/column_id", "col_C"),
    ("limitations_column_id", "col_C"), ("future_work_column_id", "col_C"),
)
REPORT_COUNT_ID_FIELDS = (
    ("numerator_source_ids/*", "srv_S"), ("denominator_source_ids/*", "srv_S"),
    ("column_id", "col_C"),
)
REPORT_SECTION_ID_FIELDS = (
    ("claims/*/passage_ids/*", "psg_P"), ("claims/*/cell_ids/*", "cel_L"),
    *((f"claims/*/count/{path}", kind) for path, kind in REPORT_COUNT_ID_FIELDS),
    ("claims/*/equation_origin/passage_id", "psg_P"),
    ("citation_anchors/*/passage_id", "psg_P"), ("citation_anchors/*/cell_id", "cel_L"),
    ("gaps/*/basis_passage_ids/*", "psg_P"), ("gaps/*/basis_cell_ids/*", "cel_L"),
    ("gaps/*/nearest_match/source_id", "srv_S"), ("gaps/*/nearest_match/cell_id", "cel_L"),
)
REPORT_INPUT_ID_FIELDS = (
    ("passages/*/passage_id", "psg_P"), ("passages/*/source_id", "srv_S"),
    ("sources/*/source_id", "srv_S"),
    *((f"allowlist/{field}/*", kind) for field, kind in (
        ("passage_ids", "psg_P"), ("source_ids", "srv_S"), ("column_ids", "col_C"), ("cell_ids", "cel_L"),
        ("cell_evidence_passage_ids", "psg_P"))),
    ("report_target/columns/*/column_id", "col_C"),
    ("report_target/cells/*/cell_id", "cel_L"), ("report_target/cells/*/column_id", "col_C"),
    ("report_target/cells/*/source_version_id", "srv_S"),
    ("report_target/cells/*/evidence/*/passage_id", "psg_P"),
    ("report_target/gap_candidates/*/column_id", "col_C"),
    ("report_target/gap_candidates/*/basis_cell_ids/*", "cel_L"),
    *((f"report_target/plan/{path}", kind) for path, kind in REPORT_PLAN_ID_FIELDS),
    ("report_target/review_sections/*/claims/*/citations/*/passage_id", "psg_P"),
    ("report_target/review_sections/*/claims/*/citations/*/cell_id", "cel_L"),
    *((f"report_target/review_sections/*/claims/*/count/{path}", kind) for path, kind in REPORT_COUNT_ID_FIELDS),
    ("report_target/limitations_core/failed_rows/*/source_version_id", "srv_S"),
    ("report_target/validation_context/source_ids/*", "srv_S"),
    ("report_target/validation_context/column_ids/*", "col_C"),
    *((f"report_target/validation_context/{array}/*/{field}", kind) for array in ("cells", "basis_cells")
      for field, kind in (("cell_id", "cel_L"), ("column_id", "col_C"), ("source_version_id", "srv_S"))),
    ("report_target/validation_context/basis_cells/*/evidence/*/passage_id", "psg_P"),
    ("report_target/validation_context/basis_passages/*/passage_id", "psg_P"),
    ("report_target/validation_context/basis_passages/*/source_id", "srv_S"),
    ("report_target/validation_context/accepted_gaps/*/basis_passage_ids/*", "psg_P"),
    ("report_target/validation_context/accepted_gaps/*/basis_cell_ids/*", "cel_L"),
)

REVIEW_INPUT_ID_FIELDS = (
    ("passages/*/passage_id", "psg_P"), ("passages/*/source_id", "srv_S"),
    ("sources/*/source_id", "srv_S"),
    ("allowlist/passage_ids/*", "psg_P"), ("allowlist/source_ids/*", "srv_S"),
    ("allowlist/cell_ids/*", "cel_L"), ("review_input/passage_ids/*", "psg_P"),
    ("review_input/claims/*/citations/*/passage_id", "psg_P"),
    ("review_input/claims/*/citations/*/cell_id", "cel_L"),
    ("review_input/cells/*/cell_id", "cel_L"), ("review_input/cells/*/source_id", "srv_S"),
    ("review_input/cells/*/evidence/*/passage_id", "psg_P"),
    ("review_input/candidate_context/matrix/*/source_id", "srv_S"),
    ("review_input/candidate_context/matrix/*/cells/*/quotes/*/passage_id", "psg_P"),
    ("review_input/candidate_context/matrix/*/whole_claim_quotes/*/passage_id", "psg_P"),
)
REVIEW_OUTPUT_ID_FIELDS = (
    ("findings/*/evidence/*/passage_handle", "psg_P"),
    ("supported_points/*/evidence/*/passage_handle", "psg_P"),
)


def review_citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Only passages, sources and cells are D12 handles; target refs remain local labels."""
    handles: dict[str, str] = {}
    for rows, field, prefix in ((step_input["passages"], "passage_id", "psg_P"),
                                (step_input["sources"], "source_id", "srv_S"),
                                (step_input["review_input"]["cells"], "cell_id", "cel_L")):
        for index, row in enumerate(rows, 1):
            handles[row[field]] = f"{prefix}{index:07d}"
    return handles


def _report_id_fields(data: dict[str, Any], fields: tuple) -> Any:
    """Yield only declared ID slots, tolerating malformed values until schema validation."""
    def slots(node: Any, parts: list[str], path: str) -> Any:
        part, *rest = parts
        keys = range(len(node)) if part == "*" and isinstance(node, list) else (
            [part] if isinstance(node, dict) and part in node else [])
        for key in keys:
            location = f"{path}/{key}"
            if rest:
                yield from slots(node[key], rest, location)
            else:
                yield node, key, location

    for path, kind in fields:
        for owner, key, location in slots(data, path.split("/"), ""):
            yield owner, key, kind, location


def _handle_numbering(kinds: tuple[str, ...]) -> tuple[dict[str, str], Callable[[Any, str], None]]:
    """A handle map and the function that numbers each new identifier per kind; first occurrence wins."""
    handles: dict[str, str] = {}
    counts = dict.fromkeys(kinds, 0)

    def add(identifier: Any, kind: str) -> None:
        if isinstance(identifier, str) and identifier not in handles:
            counts[kind] += 1
            handles[identifier] = f"{kind}{counts[kind]:07d}"
    return handles, add


def report_citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Number from stored records first, then display-only references; never extend an allowlist."""
    handles, add = _handle_numbering(("psg_P", "srv_S", "cel_L", "col_C"))

    target = step_input.get("report_target") or {}
    for records, key, kind in ((step_input["passages"], "passage_id", "psg_P"),
                               (step_input["sources"], "source_id", "srv_S"),
                               (target.get("cells", []), "cell_id", "cel_L"),
                               (target.get("columns", []), "column_id", "col_C")):
        for record in records:
            add(record[key], kind)
    for identifier in step_input["allowlist"].get("column_ids", []):
        add(identifier, "col_C")
    for records in (target.get("cells", []), target.get("gap_candidates", []),
                    (target.get("plan") or {}).get("axes", [])):
        for record in records:
            add(record["column_id"], "col_C")
    for entry in (target.get("plan") or {}).get("glossary", []):
        add(entry["passage_id"], "psg_P")
    for row in (target.get("limitations_core") or {}).get("failed_rows", []):
        add(row["source_version_id"], "srv_S")
    for section in target.get("review_sections") or []:
        for claim in section["claims"]:
            count = claim.get("count")
            if isinstance(count, dict):
                for field in ("numerator_source_ids", "denominator_source_ids"):
                    for identifier in count.get(field, []):
                        add(identifier, "srv_S")
    # Remaining plan roles and opaque review count columns follow the prescribed primary order.
    for owner, key, kind, _ in _report_id_fields(step_input, REPORT_INPUT_ID_FIELDS):
        add(owner[key], kind)
    return handles


def lineage_citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Number shown records, then display-only cells, then remaining declared slots; first occurrence wins."""
    handles, add = _handle_numbering(("psg_P", "srv_S", "cel_L"))

    for records, key, kind in ((step_input["passages"], "passage_id", "psg_P"),
                               (step_input["sources"], "source_id", "srv_S")):
        for record in records:
            add(record[key], kind)
    target = step_input.get("lineage_target") or {}
    nodes = [target.get("to") or {}] + [c["from"] for c in target.get("candidates", [])]
    for node in nodes:
        for cell in node.get("cells", []):
            add(cell["cell_id"], "cel_L")
    for owner, key, kind, _ in _report_id_fields(step_input, LINEAGE_INPUT_ID_FIELDS):
        add(owner[key], kind)
    return handles


def candidate_citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Number passages, sources, version elements, then remaining declared slots; first occurrence wins."""
    handles, add = _handle_numbering(("psg_P", "srv_S", "ele_E"))

    version = (step_input.get("candidate_target") or {}).get("version") or {}
    for records, key, kind in ((step_input["passages"], "passage_id", "psg_P"),
                               (step_input["sources"], "source_id", "srv_S"),
                               (version.get("elements", []), "element_id", "ele_E")):
        for record in records:
            add(record[key], kind)
    for owner, key, kind, _ in _report_id_fields(step_input, CANDIDATE_INPUT_ID_FIELDS):
        add(owner[key], kind)
    return handles


def citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Short per-step identifiers shown to the model in place of passage and source IDs.

    With 48 sources and passages, `gpt-5.6-luna` mis-copied long random IDs (a source suffix under the passage prefix,
    a dropped character). Handles are numbered in StepInput order, so they are recomputed from the stored StepInput;
    passage and source handles never share a suffix, so a swapped prefix stays an unknown ID instead of another record.
    """
    if step_input.get("task_type") in REPORT_TASKS:
        return report_citation_handles(step_input)
    if step_input.get("task_type") in REVIEW_TASKS:
        return review_citation_handles(step_input)
    if step_input.get("task_type") in LINEAGE_TASKS:
        return lineage_citation_handles(step_input)
    if step_input.get("task_type") in CANDIDATE_TASKS:
        return candidate_citation_handles(step_input)
    handles = {p["passage_id"]: f"psg_P{n:07d}" for n, p in enumerate(step_input["passages"], start=1)}
    columns = (step_input.get("extraction_target") or {}).get("columns", [])
    handles |= {c["column_id"]: f"col_C{n:07d}" for n, c in enumerate(columns, start=1)}
    # The abstract stage's batches are the only handled step with candidates; every other one sends none, so this
    # line adds nothing to them (slice 09).
    handles |= {c["candidate_id"]: f"cnd_C{n:07d}" for n, c in enumerate(step_input["candidates"], start=1)}
    return handles | {s["source_id"]: f"srv_S{n:07d}" for n, s in enumerate(step_input["sources"], start=1)}


def with_citation_handles(step_input: dict[str, Any]) -> dict[str, Any]:
    handles = citation_handles(step_input)
    shown = copy.deepcopy(step_input)
    if step_input.get("task_type") in REVIEW_TASKS:
        for owner, key, _, _ in _report_id_fields(shown, REVIEW_INPUT_ID_FIELDS):
            if isinstance(owner[key], str):
                owner[key] = handles.get(owner[key], owner[key])
        return shown
    if step_input.get("task_type") in REPORT_TASKS + LINEAGE_TASKS + CANDIDATE_TASKS + CITATION_CHECK_TASKS:
        fields = CANDIDATE_INPUT_ID_FIELDS if step_input["task_type"] in CANDIDATE_TASKS else (
            CITATION_CHECK_INPUT_ID_FIELDS if step_input["task_type"] in CITATION_CHECK_TASKS else (
            LINEAGE_INPUT_ID_FIELDS if step_input["task_type"] in LINEAGE_TASKS else REPORT_INPUT_ID_FIELDS))
        for owner, key, _, _ in _report_id_fields(shown, fields):
            if isinstance(owner[key], str):
                owner[key] = handles.get(owner[key], owner[key])
        return shown
    for passage in shown["passages"]:
        passage["passage_id"], passage["source_id"] = handles[passage["passage_id"]], handles[passage["source_id"]]
    for source in shown["sources"]:
        source["source_id"] = handles[source["source_id"]]
    for candidate in shown["candidates"]:
        candidate["candidate_id"] = handles[candidate["candidate_id"]]
    for claim in shown.get("claims_under_review", []):
        claim["passage_ids"] = [handles.get(i, i) for i in claim["passage_ids"]]
    if target := shown.get("extraction_target"):
        target["source_id"] = handles.get(target["source_id"], target["source_id"])
        for column in target["columns"]:
            column["column_id"] = handles[column["column_id"]]
        for item in target.get("earlier_issues") or []:  # a retry names its columns as the model sees them (D68)
            item["column_id"] = handles.get(item["column_id"], item["column_id"])
    if target := shown.get("adjudication_target"):
        target["source_id"] = handles.get(target["source_id"], target["source_id"])
    for key in ("passage_ids", "source_ids", "candidate_ids"):
        shown["allowlist"][key] = [handles.get(i, i) for i in shown["allowlist"][key]]
    return shown


def issues_with_handles(step_input: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair issues as the model saw its StepInput: record IDs in messages are replaced by their handles."""
    handles = citation_handles(step_input)
    if not handles:
        return issues
    pattern = re.compile("|".join(re.escape(i) for i in sorted(handles, key=len, reverse=True)))
    return [issue | {"message": pattern.sub(lambda m: handles[m.group(0)], issue["message"])} if isinstance(issue.get("message"), str) else issue
            for issue in issues]


PADDED_HANDLE = re.compile(r"^(psg_P|srv_S|col_C|cnd_C|cel_L|ele_E)0*(\d{1,7})$")
HANDLE_IN_PROSE = re.compile(r"\b(psg_P|srv_S|col_C|cnd_C|cel_L|ele_E)0*(\d{1,7})\b")


def name_sources_in_prose(step_input: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Replace citation handles the model wrote into an answer's or answer review's prose with source titles, after
    validation.

    A handle would reach the reader as `srv_S0000002`; one copied with more or fewer leading zeros is named as well.
    Validation (including text length limits) applies to what the model wrote, so a long list of titles cannot turn a
    valid answer invalid.
    """
    real = {handle: identifier for identifier, handle in citation_handles(step_input).items()}
    titles = {s["source_id"]: s["title"] for s in step_input.get("sources", [])}
    titles |= {p["passage_id"]: titles[p["source_id"]] for p in step_input.get("passages", []) if p["source_id"] in titles}
    named = {handle: f"“{titles[identifier]}”" for handle, identifier in real.items() if identifier in titles}
    if named:
        def title(match: re.Match[str]) -> str:
            return named.get(f"{match.group(1)}{int(match.group(2)):07d}", match.group(0))
        prose = lambda text: HANDLE_IN_PROSE.sub(title, text) if isinstance(text, str) else text
        for items, key in ((data.get("claims"), "text"), (data.get("limitations"), "text"), (data.get("reviews"), "reason"),
                           (data.get("excluded_sources"), "note")):
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and key in item:
                    item[key] = prose(item[key])
        if isinstance(data.get("unanswered_aspects"), list):
            data["unanswered_aspects"] = [prose(text) for text in data["unanswered_aspects"]]
        for key in ("capability_notice", "notes"):
            if key in data:
                data[key] = prose(data[key])
    return data


# The evidence ledger (D80): `excluded_sources` says why each given source the answer does not cite is left out. It is
# split off before the answer is validated and checked only on the published answer, so it never blocks an answer.
LEDGER_ID_FIELDS = ("source_id", "passage_id", "same_as_source_id")
LEDGER_QUOTE_REASONS = frozenset({"same_finding_as_cited", "different_conditions", "claim_limit"})
LEDGER_CLAIM_LIMIT = 30  # the instruction's claim cap; claim_limit holds only for an answer that reached it
LEDGER_MAX_HINTS = 10
LEDGER_DROP_REASONS = {
    "entry_unknown_source": "names a source that is not in the allowlist",
    "entry_duplicate_source": "repeats the source of an earlier entry",
    "entry_for_cited_source": "names a source the answer cites",
    "entry_same_as_not_cited": "same_as_source_id is not a source the answer cites",
    "entry_claim_limit_not_reached": f"claim_limit holds only for an answer with {LEDGER_CLAIM_LIMIT} claims",
    "entry_quote_missing": "this reason needs a passage_id and a quote",
    "entry_passage_unknown": "its passage_id is not in the allowlist",
    "entry_passage_other_source": "its passage_id belongs to another source",
    "entry_quote_not_located": "its quote was not found in that passage",
}


@cache
def _ledger_validator() -> tuple[Draft202012Validator, int]:
    """The item validator and entry cap of `excluded_sources`, read from the answer schema so the two cannot drift."""
    root = step_output_schema("grounded_answer")
    field = root["properties"]["excluded_sources"]
    return Draft202012Validator(copy.deepcopy(field["items"]) | {"$defs": root["$defs"]}), field["maxItems"]


def split_ledger(draft: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Take `excluded_sources` out of an answer draft before validation, leaving `[]` in its place.

    Returns the entries that pass the item schema and one diagnostic per removal: a missing or non-array field, an
    entry that fails the item schema, entries past the cap. The diagnostics are not validation issues.
    """
    present, value = "excluded_sources" in draft, draft.get("excluded_sources")
    draft["excluded_sources"] = []
    if not isinstance(value, list):
        return [], [{"code": "ledger_field_malformed", "path": "/excluded_sources",
                     "message": f"expected an array, got {type(value).__name__}" if present else "the field is missing"}]
    validator, cap = _ledger_validator()
    diagnostics, kept = [], []
    if len(value) > cap:
        diagnostics.append({"code": "ledger_too_many_entries", "path": "/excluded_sources", "count": len(value),
                            "message": f"{len(value)} entries; those past {cap} were removed"})
    for index, entry in enumerate(value[:cap]):
        errors = sorted(validator.iter_errors(entry), key=lambda e: list(e.absolute_path))
        if errors:
            diagnostics.append({"code": "ledger_entry_malformed", "path": f"/excluded_sources/{index}",
                                "message": f"entry removed: {errors[0].message[:200]}"})
        else:
            kept.append(entry)
    return kept, diagnostics


def _ledger_anchor(step_input: dict[str, Any], entry: dict[str, Any]) -> tuple[str | None, AnchorMatch | None]:
    """Where a ledger entry's quote is found in a given passage of its own source: (drop code, match). Same matcher
    as claim anchors."""
    if entry["passage_id"] is None or entry["quote"] is None:
        return "entry_quote_missing", None
    passage = next((p for p in step_input["passages"] if p["passage_id"] == entry["passage_id"]), None)
    if passage is None or entry["passage_id"] not in step_input["allowlist"]["passage_ids"]:
        return "entry_passage_unknown", None
    if passage["source_id"] != entry["source_id"]:
        return "entry_passage_other_source", None
    match = locate_anchor(entry["quote"], passage["text"])
    return ("entry_quote_not_located" if match is None else None), match


def _ledger_entry(step_input: dict[str, Any], entry: dict[str, Any], cited: set[str], claim_count: int,
                  seen: set[str]) -> tuple[str | None, AnchorMatch | None]:
    """A schema-valid ledger entry's drop code (None when it stands) and its located quote. A quote on a reason that
    needs none is kept when located and ignored when not."""
    source = entry["source_id"]
    if source not in step_input["allowlist"]["source_ids"]:
        return "entry_unknown_source", None
    if source in seen:
        return "entry_duplicate_source", None
    seen.add(source)
    if source in cited:
        return "entry_for_cited_source", None
    same_as = entry["same_as_source_id"]
    if (same_as is not None or entry["reason"] == "same_finding_as_cited") and same_as not in cited:
        return "entry_same_as_not_cited", None
    if entry["reason"] == "claim_limit" and claim_count < LEDGER_CLAIM_LIMIT:
        return "entry_claim_limit_not_reached", None
    code, match = _ledger_anchor(step_input, entry)
    return (code, None) if code is not None and entry["reason"] in LEDGER_QUOTE_REASONS else (None, match)


def answer_ledger(step_input: dict[str, Any], answer: dict[str, Any], links: list[dict[str, Any]],
                  split: list[dict[str, Any]]) -> dict[str, Any]:
    """The evidence ledger of a published, valid answer. Cited sources come from its evidence links, never from the
    model; an exclusion is kept only when it passes the entry checks; a given source with neither is unaccounted.

    A located quote shows where an entry points; it does not show that the reason is right.
    """
    given = [s["source_id"] for s in step_input["sources"]]
    linked = {link["source_id"] for link in links}
    claim_count = len(answer.get("claims") or [])
    excluded, dropped, seen = [], [], set()
    for index, entry in enumerate(answer.get("excluded_sources") or []):
        code, match = _ledger_entry(step_input, entry, linked, claim_count, seen)
        if code is not None:
            dropped.append({"index": index, "source_id": entry["source_id"], "code": code})
        else:
            excluded.append(entry | {"anchor_text": match.text if match else None, "anchor_match": match.kind if match else None})
    accounted = linked | {entry["source_id"] for entry in excluded}
    unaccounted = [s for s in given if s not in accounted]
    return {"version": 1, "given": given, "cited": [s for s in given if s in linked], "excluded": excluded,
            "unaccounted": unaccounted, "dropped": dropped, "split": list(split), "complete": not unaccounted}


def ledger_hints(step_input: dict[str, Any], draft: Any) -> list[str]:
    """Up to LEDGER_MAX_HINTS lines on a failed answer's ledger for its repair message; never validation issues.

    Read from the failed draft as it stands: a claim passage outside the StepInput is skipped, and evidence links are
    never derived from a draft that did not validate.
    """
    if not isinstance(draft, dict):
        return []
    draft = copy.deepcopy(draft)
    entries, split = split_ledger(draft)
    source_of = {p["passage_id"]: p["source_id"] for p in step_input["passages"]}
    claims = draft["claims"] if isinstance(draft.get("claims"), list) else []
    cited = {source_of[pid] for claim in claims if isinstance(claim, dict) and isinstance(claim.get("passage_ids"), list)
             for pid in claim["passage_ids"] if isinstance(pid, str) and pid in source_of}
    hints = [f"excluded_sources{d['path'].removeprefix('/excluded_sources')}: {d['message']}" for d in split]
    seen: set[str] = set()
    listed = set()
    for entry in entries:
        code, _ = _ledger_entry(step_input, entry, cited, len(claims), seen)
        if code is None:
            listed.add(entry["source_id"])
        else:
            hints.append(f"The excluded_sources entry for {entry['source_id']} would be dropped: {LEDGER_DROP_REASONS[code]}.")
    hints += [f"{s['source_id']} is given but neither cited nor listed in excluded_sources."
              for s in step_input["sources"] if s["source_id"] not in cited | listed]
    return hints[:LEDGER_MAX_HINTS]


ANCHOR_SALVAGE_CODES = frozenset({"duplicate_citation_anchor", "anchor_not_in_passage", "missing_citation_anchor",
                                  "anchor_passage_not_cited"})
SEVERAL_SOURCES = "source_stated_several_sources"


def resplit_labels(issues: list[dict[str, Any]], draft: Any, step_input: dict[str, Any]) -> list[str] | None:
    """D249: labels of the claims to split when the answer is still invalid only on D247's several-sources rule.

    Every remaining blocker must be that rule or an anchor defect D244 salvage handles; any other issue code, or no
    several-sources claim at all, gives None and the draft is stored unverified as before. `draft` is the failed output
    with its handles resolved; like D244, an anchor naming a passage outside the StepInput allowlist is never repaired.
    """
    codes = {issue.get("code") for issue in issues}
    if SEVERAL_SOURCES not in codes or not codes <= ANCHOR_SALVAGE_CODES | {SEVERAL_SOURCES}:
        return None
    anchors = draft.get("citation_anchors") if isinstance(draft, dict) else None
    allowed = set(step_input["allowlist"]["passage_ids"])
    if not isinstance(anchors, list) or any(not isinstance(a, dict) or a.get("passage_id") not in allowed for a in anchors):
        return None
    return [issue["message"].split(":", 1)[0] for issue in issues if issue.get("code") == SEVERAL_SOURCES]


INFERENCE_CAP_MIN_CLAIMS = 4


def inference_cap_labels(answer: Any) -> list[str] | None:
    """D260: labels of the analyst_inference claims of a valid answer when they are more than half of its claims.

    Answers with fewer than INFERENCE_CAP_MIN_CLAIMS claims are never capped.
    """
    claims = answer.get("claims") if isinstance(answer, dict) else None
    if not isinstance(claims, list) or len(claims) < INFERENCE_CAP_MIN_CLAIMS:
        return None
    labels = [c["claim_label"] for c in claims if isinstance(c, dict) and c.get("support_type") == "analyst_inference"]
    return labels if 2 * len(labels) > len(claims) else None


def over_inference_share(answer: dict[str, Any]) -> bool:
    """D260: more than half of the answer's claims are analyst_inference (any claim count)."""
    claims = answer.get("claims") or []
    return 2 * sum(1 for c in claims if c.get("support_type") == "analyst_inference") > len(claims)


COVERAGE_KEPT_CLAIM_FIELDS = ("text", "support_type", "section")


def coverage_changed_path(first: dict[str, Any], rewrite: dict[str, Any], cited: set[str]) -> str | None:
    """D83: the first path of the accepted answer that its ledger coverage rewrite does not keep, or None.

    Both answers are resolved results (record IDs). Every first claim must be in the rewrite with the same label, text,
    support type, section, passages and anchor quotes (passages and anchors as sets), in the same relative order; every
    first excluded_sources entry whose source the rewrite still does not cite (`cited`) must be in the rewrite unchanged,
    anywhere in the list. Limitations are not compared: they describe the answer as a whole, so the rewrite's stand.
    New claims and entries may be added anywhere.
    """
    def anchors(answer: dict[str, Any]) -> dict[str, set[tuple[str, str]]]:
        found: dict[str, set[tuple[str, str]]] = {}
        for anchor in answer.get("citation_anchors") or []:
            found.setdefault(anchor["claim_label"], set()).add((anchor["passage_id"], anchor["quote"]))
        return found

    claims = rewrite.get("claims") or []
    position = {claim["claim_label"]: index for index, claim in enumerate(claims)}
    old_anchors, new_anchors = anchors(first), anchors(rewrite)
    last = -1
    for index, claim in enumerate(first.get("claims") or []):
        label = claim["claim_label"]
        at = position.get(label)
        if (at is None or at <= last or any(claims[at].get(f) != claim.get(f) for f in COVERAGE_KEPT_CLAIM_FIELDS)
                or set(claims[at].get("passage_ids") or []) != set(claim.get("passage_ids") or [])
                or new_anchors.get(label, set()) != old_anchors.get(label, set())):
            return f"/claims/{index}"
        last = at
    for index, entry in enumerate(first.get("excluded_sources") or []):
        if entry["source_id"] not in cited and entry not in (rewrite.get("excluded_sources") or []):
            return f"/excluded_sources/{index}"
    return None


def answer_with_handles(step_input: dict[str, Any], answer: dict[str, Any]) -> str:
    """D260: an accepted answer as the model would write it, with passage IDs back in their citation handles."""
    handles = citation_handles(step_input)
    shown = copy.deepcopy(answer)
    for claim in shown.get("claims", []):
        claim["passage_ids"] = [handles.get(pid, pid) for pid in claim.get("passage_ids", [])]
    for anchor in shown.get("citation_anchors", []):
        anchor["passage_id"] = handles.get(anchor.get("passage_id"), anchor.get("passage_id"))
    excluded = shown.get("excluded_sources")  # the resolver's guards: anything else is left as it is
    for entry in excluded if isinstance(excluded, list) else []:
        if isinstance(entry, dict):
            for key in LEDGER_ID_FIELDS:
                if isinstance(entry.get(key), str):
                    entry[key] = handles.get(entry[key], entry[key])
    return json.dumps(shown, ensure_ascii=False)


def relabel_split_claims(draft: Any, labels: list[str]) -> tuple[Any, dict[str, list[str]]]:
    """D259: give the parts of a split claim that kept the offending label new labels, before validation.

    Only a label the extra repair named (D249) is touched, and only when its claims cite pairwise disjoint passages,
    so every anchor of that label belongs to exactly the claim that cites its passage. The first claim keeps the label;
    each later one gets the next unused number. Claim text, passages, quotes and order are unchanged. Anything else
    (an anchor whose passage none or several of them cite, no free number) leaves the draft as it is for the validator.
    """
    if not isinstance(draft, dict) or not isinstance(draft.get("claims"), list) or not isinstance(draft.get("citation_anchors"), list):
        return draft, {}
    claims, anchors = draft["claims"], draft["citation_anchors"]
    if not all(isinstance(c, dict) and isinstance(c.get("claim_label"), str) and isinstance(c.get("passage_ids"), list)
               and all(isinstance(pid, str) for pid in c["passage_ids"]) for c in claims):
        return draft, {}
    if not all(isinstance(a, dict) and isinstance(a.get("claim_label"), str) and isinstance(a.get("passage_id"), str) for a in anchors):
        return draft, {}
    used = {c["claim_label"] for c in claims} | {a["claim_label"] for a in anchors}
    numbers = [int(m.group(1)) for label in used if (m := re.fullmatch(r"c([0-9]{1,3})", label))]
    following = max(numbers, default=0) + 1
    plan: dict[int, str] = {}
    anchor_plan: dict[int, str] = {}
    renamed: dict[str, list[str]] = {}
    for label in dict.fromkeys(labels):
        parts = [i for i, c in enumerate(claims) if c["claim_label"] == label]
        if len(parts) < 2:
            continue
        cited = [set(claims[i]["passage_ids"]) for i in parts]
        if sum(map(len, cited)) != len(set().union(*cited)):  # a passage cited by two parts
            continue
        owners = {}
        for j, anchor in enumerate(anchors):
            if anchor["claim_label"] != label:
                continue
            owner = [i for i, passages in zip(parts, cited) if anchor["passage_id"] in passages]
            if len(owner) != 1:
                break
            owners[j] = owner[0]
        else:
            if following + len(parts) - 2 > 999:  # the new labels are following .. following + len(parts) - 2
                continue
            new = {parts[0]: label} | {i: f"c{following + k}" for k, i in enumerate(parts[1:])}
            following += len(parts) - 1
            plan.update(new)
            anchor_plan.update({j: new[i] for j, i in owners.items()})
            renamed[label] = [new[i] for i in parts]
    if not renamed:
        return draft, {}
    draft = copy.deepcopy(draft)
    for i, label in plan.items():
        draft["claims"][i]["claim_label"] = label
    for j, label in anchor_plan.items():
        draft["citation_anchors"][j]["claim_label"] = label
    return draft, renamed


def salvage_answer_draft(step_input: dict[str, Any], draft: dict[str, Any]) -> tuple[dict[str, Any], list[Issue]]:
    """D244: prune only anchor defects; require a revalidated answer with at least one claim."""
    if step_input["task_type"] != "grounded_answer":
        return draft, []
    report = validate_model_output(step_input, draft)
    eligible = ANCHOR_SALVAGE_CODES
    if report.ok or any(issue.code not in eligible for issue in report.issues):
        return draft, []
    # An uncited anchor can carry an unknown ID without the existing validator naming it as such.
    if any(a["passage_id"] not in step_input["allowlist"]["passage_ids"] for a in draft["citation_anchors"]):
        return draft, []
    original = draft
    draft = copy.deepcopy(draft)
    warnings: list[Issue] = []
    claims, anchors = draft["claims"], draft["citation_anchors"]
    text = {p["passage_id"]: p["text"] for p in step_input["passages"]}
    cited = {(c["claim_label"], pid) for c in claims for pid in c["passage_ids"]}
    chosen: dict[tuple[str, str], int] = {}
    pair_codes: dict[tuple[str, str], set[str]] = {}
    for i, anchor in enumerate(anchors):
        pair = (anchor["claim_label"], anchor["passage_id"])
        pair_codes.setdefault(pair, set()).update(issue.code for issue in report.issues
                                                if issue.path.startswith(f"/citation_anchors/{i}/")
                                                or issue.path == f"/citation_anchors/{i}")
        if pair in cited and pair not in chosen and locate_anchor(anchor["quote"], text[pair[1]]) is not None:
            chosen[pair] = i

    def dropped(pair: tuple[str, str | None], path: str, kind: str, codes: set[str]) -> None:
        warnings.append(AnchorSalvageWarning("citation_anchor_salvaged", path,
                        f"{pair[0]}:{pair[1] or ''}: removed {kind} ({', '.join(sorted(codes))})",
                        pair[0], pair[1], kind, sorted(codes)))

    for i, anchor in enumerate(anchors):
        pair = (anchor["claim_label"], anchor["passage_id"])
        if pair not in cited:
            dropped(pair, f"/citation_anchors/{i}", "anchor", pair_codes[pair] | {"anchor_passage_not_cited"})
        elif chosen.get(pair) != i:
            dropped(pair, f"/citation_anchors/{i}", "anchor", pair_codes[pair])
    draft["citation_anchors"] = [anchors[i] for i in sorted(chosen.values())]
    kept_claims = []
    for i, claim in enumerate(claims):
        keep, removed_codes = [], set()
        for j, pid in enumerate(claim["passage_ids"]):
            pair = (claim["claim_label"], pid)
            if pair in chosen:
                keep.append(pid)
            else:
                codes = pair_codes.get(pair, {"missing_citation_anchor"})
                removed_codes.update(codes)
                dropped(pair, f"/claims/{i}/passage_ids/{j}", "citation_link", codes)
        claim["passage_ids"] = keep
        if keep:
            kept_claims.append(claim)
        else:
            dropped((claim["claim_label"], None), f"/claims/{i}", "claim", removed_codes)
    draft["claims"] = kept_claims
    if not kept_claims or not validate_model_output(step_input, draft).ok:
        return original, []
    return draft, warnings



def prune_unanchored_report_links(step_input: dict[str, Any], draft: Any,
                                  issues: list[Issue]) -> tuple[Any, list[Issue]]:
    """A report section's cited passage or cell that no anchor of its claim names is dropped from the claim, as the
    answer path's salvage drops an unanchored citation link; each drop is returned as a warning.

    Only allowlisted targets are dropped (an unknown ID stays an error), and only from a claim that keeps at least one
    anchored target: a claim none of whose citations has an anchor is left as it is, so it still fails validation.
    """
    if (step_input.get("task_type") != "report_section" or not isinstance(draft, dict)
            or not any(issue.code == "missing_citation_anchor" for issue in issues)):
        return draft, []
    keys = [claim["claim_key"] for claim in draft["claims"]]
    if len(keys) != len(set(keys)):  # anchors name claims by key; a duplicate key makes the pairing ambiguous
        return draft, []
    allowed = {"passage": set(step_input["allowlist"]["passage_ids"]),
               "cell": set(step_input["allowlist"].get("cell_ids", []))}
    anchored = {(a["claim_key"], kind, a[kind + "_id"]) for a in draft["citation_anchors"]
                if (a["passage_id"] is None) != (a["cell_id"] is None)
                for kind in ("passage", "cell") if a[kind + "_id"] is not None}
    draft = copy.deepcopy(draft)
    warnings: list[Issue] = []
    for i, claim in enumerate(draft["claims"]):
        key = claim["claim_key"]
        targets = [(kind, x) for kind in ("passage", "cell") for x in claim[kind + "_ids"]]
        if not any((key, kind, x) in anchored for kind, x in targets):
            continue
        for kind in ("passage", "cell"):
            kept = []
            for j, x in enumerate(claim[kind + "_ids"]):
                if x in allowed[kind] and (key, kind, x) not in anchored:
                    warnings.append(ReportLinkPruneWarning(
                        "citation_link_pruned", f"/claims/{i}/{kind}_ids/{j}",
                        f"{key}:{x}: removed citation_link (missing_citation_anchor)",
                        key, x if kind == "passage" else None, x if kind == "cell" else None,
                        "citation_link", ["missing_citation_anchor"]))
                else:
                    kept.append(x)
            claim[kind + "_ids"] = kept
    return draft, warnings


def resolve_citation_handles(step_input: dict[str, Any], raw: str) -> str | dict[str, Any]:
    """Map handles in an answer, a cell draft or an abstract screening back to IDs; the rest validation reports.

    A handle copied with more or fewer leading zeros (`psg_P00000017`) is read as the handle with that number.
    """
    handles = {handle: identifier for identifier, handle in citation_handles(step_input).items()}

    def real(i: str) -> str:
        match = PADDED_HANDLE.match(i)
        return handles.get(f"{match.group(1)}{int(match.group(2)):07d}" if match else i, i)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, dict):
        return raw
    if step_input.get("task_type") in REVIEW_TASKS:
        for owner, key, kind, _ in _report_id_fields(data, REVIEW_OUTPUT_ID_FIELDS):
            if isinstance(owner[key], str) and owner[key].startswith(kind):
                owner[key] = real(owner[key])
        return data
    if step_input.get("task_type") in REPORT_TASKS + LINEAGE_TASKS + CANDIDATE_TASKS + CITATION_CHECK_TASKS:
        fields = CANDIDATE_OUTPUT_ID_FIELDS[step_input["task_type"]] if step_input["task_type"] in CANDIDATE_TASKS else (
            CITATION_CHECK_OUTPUT_ID_FIELDS if step_input["task_type"] in CITATION_CHECK_TASKS else
            LINEAGE_OUTPUT_ID_FIELDS if step_input["task_type"] in LINEAGE_TASKS else (
            REPORT_PLAN_ID_FIELDS if step_input["task_type"] == "report_plan" else (
                REPORT_SECTION_ID_FIELDS if step_input["task_type"] == "report_section" else ())))
        for owner, key, kind, _ in _report_id_fields(data, fields):
            identifier = owner[key]
            if isinstance(identifier, str) and identifier.startswith(kind):
                owner[key] = real(identifier)
        return data
    for items, key in ((data.get("claims"), "passage_ids"), (data.get("limitations"), "source_ids")):
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get(key), list):
                item[key] = [real(i) if isinstance(i, str) else i for i in item[key]]
    anchors = data.get("citation_anchors")
    for anchor in anchors if isinstance(anchors, list) else []:
        if isinstance(anchor, dict) and isinstance(anchor.get("passage_id"), str):
            anchor["passage_id"] = real(anchor["passage_id"])
    excluded = data.get("excluded_sources")  # anything not a list, dict or string is left for split_ledger to remove
    for entry in excluded if isinstance(excluded, list) else []:
        if isinstance(entry, dict):
            for key in LEDGER_ID_FIELDS:
                if isinstance(entry.get(key), str):
                    entry[key] = real(entry[key])
    works = data.get("work_classifications")
    for work in works if isinstance(works, list) else []:
        if not isinstance(work, dict):
            continue
        if isinstance(work.get("passage_id"), str):
            work["passage_id"] = real(work["passage_id"])
        memberships = work.get("memberships")
        for item in memberships if isinstance(memberships, list) else []:
            if isinstance(item, dict) and isinstance(item.get("passage_id"), str):
                item["passage_id"] = real(item["passage_id"])
    records = data.get("records")
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict) and isinstance(record.get("candidate_id"), str):
            record["candidate_id"] = real(record["candidate_id"])
    cells = data.get("cells")
    for cell in cells if isinstance(cells, list) else []:
        if not isinstance(cell, dict):
            continue
        if isinstance(cell.get("column_id"), str):
            cell["column_id"] = real(cell["column_id"])
        evidence = cell.get("evidence")
        for item in evidence if isinstance(evidence, list) else []:
            if isinstance(item, dict) and isinstance(item.get("passage_id"), str):
                item["passage_id"] = real(item["passage_id"])
    if step_input.get("task_type") == "fulltext_adjudication":
        for part in data.get("parts") if isinstance(data.get("parts"), list) else []:
            if isinstance(part, dict) and isinstance(part.get("passage_id"), str):
                part["passage_id"] = real(part["passage_id"])
    return data


def cell_links(step_input: dict[str, Any], cell: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence links of one cell answer: passages of the StepInput only, with the located passage words as anchor."""
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    links: dict[tuple[str, str | None], dict[str, Any]] = {}
    for item in cell["evidence"]:
        passage = passages.get(item["passage_id"])
        if passage is None:
            continue
        anchor = locate_anchor(item["quote"], passage["text"])
        key = (passage["passage_id"], anchor.text if anchor else None)  # one link per located span of a passage (D43)
        links.setdefault(key, {"passage_id": passage["passage_id"], "source_version_id": passage["source_id"],
                               "anchor_text": anchor.text if anchor else None, "anchor_match": anchor.kind if anchor else None})
    return list(links.values())


def claim_assessment_evidence(step_input: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    """Map valid assessment evidence to K1's shape using source-owned located words.

    K3 must stop publication on an unexpected None, never keep only the remaining evidence.
    """
    passage = _lineage_records_by_id(step_input["passages"], "passage_id").get(item["passage_id"])
    if passage is None:
        return None
    anchor = locate_anchor(item["quote"], passage["text"])
    if anchor is None:
        return None
    abstract = passage["locator"]["kind"] == "abstract"
    return {"evidence_kind": "abstract" if abstract else "passage",
            "passage_id": None if abstract else passage["passage_id"], "quote": anchor.text}


# Problems of one cell answer that leave the other answers of the same cell extraction output usable (D68).
# Anything else (a schema error, an envelope mismatch, an unknown or twice-answered column) fails the whole output.
CELL_SALVAGE_HINTS = {
    "anchor_not_in_passage": "A quote was not found word for word in the passage it cites. Copy the words exactly from"
                             " the passage, cite the passage that holds them, or leave the evidence out if no passage"
                             " supports the answer.",
    "unknown_passage_id": "The evidence cited a passage that was not given. Cite only the passages given.",
    "duplicate_evidence_quote": "The same quote of a passage was given twice. Give each quote once.",
    "value_without_evidence": "A 'value' answer needs at least one exact quote from a given passage.",
    "unknown_without_evidence": "An 'unknown' answer needs at least one exact quote from a given passage.",
    "evidence_for_not_found": "A 'not_found_in_inspected_scope' answer cites no passage.",
    "invalid_cell_value": "The value did not fit the column's answer format.",
    "not_applicable_without_note": "A 'not_applicable' answer needs a short note saying why.",
    "locator_in_note": "The note named a page, equation, table, figure or section number. Leave locators out of the note.",
    "column_without_answer": "The column was not answered. Answer it once.",
}


def cell_draft_from_raw(step_input: dict[str, Any], raw: str) -> str | dict[str, Any]:
    """A cell extraction's raw model text as `_model_step` validated it: handles resolved, field names normalised and
    the code-owned envelope stamped. Used to read the per-cell problems of an output that failed validation."""
    draft = resolve_citation_handles(step_input, raw)
    draft, _ = normalise_output("cell_extraction", draft)
    draft, _ = stamp_package_hash("cell_extraction", step_input, draft)
    draft, _ = stamp_step_input_id("cell_extraction", step_input, draft)
    return draft


def salvage_cells(step_input: dict[str, Any], draft: str | dict[str, Any]) -> dict[str, Any] | None:
    """Split a failed cell extraction output into the answers that pass every check and the columns that do not.

    Returns None when the output is valid or when any problem is not a problem of one cell answer: then the output
    fails as a whole, as before. Otherwise `cells` are the answers of the columns without a problem, checked again on
    their own against a copy of the input that asks for those columns only, and `bad` maps each other column to its
    problems. A kept answer is as checked as an answer of a valid output; nothing of a bad column is kept here.
    """
    if step_input.get("task_type") != "cell_extraction" or not isinstance(draft, dict):
        return None
    report = validate_model_output(step_input, draft)
    if report.ok or any(issue.code not in CELL_SALVAGE_HINTS for issue in report.issues):
        return None
    columns = [c["column_id"] for c in step_input["extraction_target"]["columns"]]
    bad: dict[str, list[dict[str, str]]] = {}
    for issue in report.issues:
        if issue.code == "column_without_answer":
            column_id = issue.message
        else:
            match = re.match(r"^/cells/(\d+)(?:/|$)", issue.path)
            if match is None:
                return None
            column_id = draft["cells"][int(match.group(1))]["column_id"]
        if column_id not in columns:
            return None
        bad.setdefault(column_id, []).append({"code": issue.code, "path": issue.path, "message": issue.message})
    good = [column_id for column_id in columns if column_id not in bad]
    cells = [cell for cell in draft["cells"] if cell["column_id"] in good]
    if good:
        narrowed = copy.deepcopy(step_input)
        narrowed["extraction_target"]["columns"] = [c for c in narrowed["extraction_target"]["columns"] if c["column_id"] in good]
        if not validate_model_output(narrowed, dict(draft, cells=cells)).ok:
            return None
    return {"cells": cells, "bad": bad}


def earlier_issues(bad: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """What the one retry of a cell extraction is told about its columns' earlier answers: a fixed hint per problem,
    without passage identifiers (the model knows passages by handles only)."""
    return [{"column_id": column_id, "code": code, "message": CELL_SALVAGE_HINTS[code]}
            for column_id, issues in bad.items() for code in dict.fromkeys(issue["code"] for issue in issues)]


def storable_cells(step_input: dict[str, Any], data: str | dict[str, Any]) -> list[dict[str, Any]]:
    """Cell answers of an output that failed validation that can still be kept as unverified proposals.

    An answer is kept when it is its column's only answer, has a state a model may write and a value the column's format
    accepts; its evidence keeps allowlisted passages only. Such a proposal shows as invalid and cannot be accepted.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return []
    cells = data.get("cells") if isinstance(data, dict) else None
    if not isinstance(cells, list):
        return []
    columns = {c["column_id"]: c for c in step_input["extraction_target"]["columns"]}
    allowed = set(step_input["allowlist"]["passage_ids"])
    answers = Counter(c.get("column_id") for c in cells if isinstance(c, dict) and isinstance(c.get("column_id"), str))
    kept = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("column_id") not in columns or answers[cell["column_id"]] != 1 \
                or cell.get("state") not in MODEL_CELL_STATES:
            continue
        try:
            value = check_value(columns[cell["column_id"]], cell["state"], cell.get("value"))
        except InvalidTableInput:
            continue
        evidence = cell.get("evidence") if isinstance(cell.get("evidence"), list) else []
        kept.append({"column_id": cell["column_id"], "state": cell["state"], "value": value,
                     "note": cell["note"] if isinstance(cell.get("note"), str) else None,
                     "evidence": [e for e in evidence if isinstance(e, dict) and e.get("passage_id") in allowed
                                  and isinstance(e.get("quote"), str)]})
    return kept


def derive_evidence_links(step_input: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence links take source, depth and locator from StepInput records only."""
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    quotes = {(a["claim_label"], a["passage_id"]): a["quote"] for a in draft.get("citation_anchors", [])}
    links = []
    for claim in draft["claims"]:
        for pid in claim["passage_ids"]:
            p = passages[pid]
            quote = quotes.get((claim["claim_label"], pid))
            anchor = locate_anchor(quote, p["text"]) if quote else None
            links.append(
                {
                    "claim_label": claim["claim_label"],
                    "passage_id": pid,
                    "source_id": p["source_id"],
                    "reading_depth": p["reading_depth"],
                    "locator": dict(p["locator"]),
                    "support_type": claim["support_type"],
                    "semantic_review": "not_checked",
                    "anchor_text": anchor.text if anchor else None,
                    "anchor_match": anchor.kind if anchor else None,
                }
            )
    return links

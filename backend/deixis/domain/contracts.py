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
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from deixis.domain import phrasebank
from deixis.domain.lineage import MAX_WHAT_CHANGED, valid_what_changed
from deixis.paths import CONTRACTS_DIR, SKILL_DIR
from deixis.workflow.criterion import (MAX_PHRASE_WORDS, PARTS_PER_PROPOSAL, PHRASES_PER_PART,
                                       holds as criterion_holds, norm as normalize_phrase)
from deixis.workflow.tables import MAX_COLUMNS_PER_CALL, InvalidTableInput, check_value, column_spec

SCHEMA_FILES = {
    "OwnerReview": "owner-review.schema.json",
    "GroundedAnswerDraft": "grounded-answer-draft.schema.json",
    "AnswerReview": "answer-review.schema.json",
    "EvidenceCellDraft": "evidence-cell-draft.schema.json",
    "TableColumnProposal": "table-column-proposal.schema.json",
    "ResearchTitle": "research-title.schema.json",
    "VocabularyLabels": "vocabulary-labels.schema.json",
    "CriterionProposal": "criterion-proposal.schema.json",
    "TermSuggestions": "term-suggestions.schema.json",
    "SearchQuery": "search-query.schema.json",
    "AbstractScreening": "abstract-screening.schema.json",
    "FulltextAdjudication": "fulltext-adjudication.schema.json",
    "StepInput": "step-input.schema.json",
    "ReportPlanDraft": "report-plan.schema.json",
    "ReportSectionDraft": "report-section-draft.schema.json",
    "ReportPhraseRepairDraft": "report-phrase-repair.schema.json",
    "ReportReview": "report-review.schema.json",
    "LineageLinksDraft": "lineage-links-draft.schema.json",
    "ClaimDecomposition": "claim-decomposition.schema.json",
    "KillSearchQuery": "kill-search-query.schema.json",
    "ClaimAssessment": "claim-assessment.schema.json",
    "ReportSectionAnchorRepair": "report-section-anchor-repair.schema.json",
}
SCHEMA_VERSIONS = {
    "OwnerReview": "deixis.owner_review.v1",
    "GroundedAnswerDraft": "deixis.grounded_answer_draft.v3",
    "AnswerReview": "deixis.answer_review.v1",
    "EvidenceCellDraft": "deixis.evidence_cell_draft.v1",
    "TableColumnProposal": "deixis.table_column_proposal.v1",
    "ResearchTitle": "deixis.research_title.v1",
    "VocabularyLabels": "deixis.vocabulary_labels.v1",
    "CriterionProposal": "deixis.criterion_proposal.v2",
    "TermSuggestions": "deixis.term_suggestions.v1",
    "SearchQuery": "deixis.search_query.v1",
    "AbstractScreening": "deixis.abstract_screening.v1",
    "FulltextAdjudication": "deixis.fulltext_adjudication.v1",
    "ReportPlanDraft": "deixis.report_plan_draft.v2",
    "ReportSectionDraft": "deixis.report_section_draft.v2",
    "ReportPhraseRepairDraft": "deixis.report_phrase_repair_draft.v1",
    "ReportReview": "deixis.report_review.v1",
    "LineageLinksDraft": "deixis.lineage_links_draft.v1",
    "ClaimDecomposition": "deixis.claim_decomposition.v1",
    "KillSearchQuery": "deixis.kill_search_query.v1",
    "ClaimAssessment": "deixis.claim_assessment.v1",
    "ReportSectionAnchorRepair": "deixis.report_section_anchor_repair.v1",
}
# Model outputs each task may return. More than one output type is wrapped in an
# object with one nullable property per type; exactly one must be non-null.
TASK_OUTPUTS = {
    "owner_review": ("OwnerReview",),
    "grounded_answer": ("GroundedAnswerDraft",),
    "answer_review": ("AnswerReview",),
    "cell_extraction": ("EvidenceCellDraft",),
    "table_columns": ("TableColumnProposal",),
    "research_title": ("ResearchTitle",),
    "vocabulary_labels": ("VocabularyLabels",),
    "criterion_proposal": ("CriterionProposal",),
    "term_suggestions": ("TermSuggestions",),
    "search_query": ("SearchQuery",),
    "abstract_screening": ("AbstractScreening",),
    "fulltext_adjudication": ("FulltextAdjudication",),
    "report_plan": ("ReportPlanDraft",),
    "report_section": ("ReportSectionDraft",),
    "report_phrase_repair": ("ReportPhraseRepairDraft",),
    "report_review": ("ReportReview",),
    "lineage_links": ("LineageLinksDraft",),
    "claim_decomposition": ("ClaimDecomposition",),
    "kill_search_query": ("KillSearchQuery",),
    "claim_assessment": ("ClaimAssessment",),
}
EXTRACTION_TASKS = ("cell_extraction", "table_columns")
# The block-labelling step sorts a phrase list code extracted; it carries a vocabulary_target instead (SW17.1).
VOCABULARY_TASKS = ("vocabulary_labels",)
# The term-suggestion step is given the searched phrases of the approval's proposal and proposes other names for
# them; it carries a suggestion_target (SW2.5, slice 08c).
SUGGESTION_TASKS = ("term_suggestions",)
# The abstract stage asks the same batch twice and tells each call which of the two runs it is (slice 09, K3).
SCREENING_TARGET_TASKS = ("abstract_screening",)
# The full-text reading step is given one work, the criterion parts, and which of the two runs this call is (D85).
ADJUDICATION_TARGET_TASKS = ("fulltext_adjudication",)
GAP_KINDS = ("stated_limitation", "conflicting_evidence", "corpus_absence")
REPORT_TASKS = ("report_plan", "report_section", "report_phrase_repair", "report_review")
REVIEW_TASKS = ("owner_review",)
LINEAGE_TASKS = ("lineage_links",)
CANDIDATE_TASKS = ("claim_decomposition", "kill_search_query", "claim_assessment")
CANDIDATE_SUPPORT_RELATIONS = ("explicit_support", "reasoned_inference", "partial_match")
# A surface screen only: absence of these words does not establish the plan's scope or quality.
VALIDATION_PLAN_DESIGN_TERMS = re.compile(
    r"\b(?:protocol|sample\s+size|power\s+analysis|apparatus|equipment|instrumentation|reagents?"
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
    suggestion_target = step_input.get("suggestion_target")
    if (suggestion_target is not None) != (step_input["task_type"] in SUGGESTION_TASKS):
        issues.append(Issue("suggestion_target_mismatch", "/suggestion_target", step_input["task_type"]))
    elif suggestion_target is not None:
        # The anchors are the allowlist: a proposed name may be another name for one of these phrases and no other.
        anchors = [entry["phrase"] for entry in suggestion_target["phrases"]]
        if len(set(anchors)) != len(anchors):
            issues.append(Issue("duplicate_vocabulary_phrase", "/suggestion_target/phrases", "phrase must be unique"))
        if sorted(set(allow.get("phrases", []))) != sorted(set(anchors)):
            issues.append(Issue("phrase_allowlist_mismatch", "/allowlist/phrases", "the allowlist is the phrase list"))
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
    issues.extend(_check_owner_review_input(step_input, records))
    report_target = step_input.get("report_target")
    if (report_target is not None) != (step_input["task_type"] in REPORT_TASKS):
        issues.append(Issue("report_target_mismatch", "/report_target", step_input["task_type"]))
    elif report_target is not None:
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
                if evidence["passage_id"] not in allow["passage_ids"]:
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
                if cell_id not in cell_ids or cell_id not in allow.get("cell_ids", []):
                    issues.append(Issue("gap_basis_cell_missing", f"/report_target/gap_candidates/{i}/basis_cell_ids/{j}",
                                        cell_id))
        if step_input["task_type"] in ("report_section", "report_phrase_repair"):
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
                                              "screening_target", "suggestion_target", "adjudication_target")))):
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
                                              "screening_target", "suggestion_target", "adjudication_target",
                                              "lineage_target")))):
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
    if task_type in CANDIDATE_TASKS + REVIEW_TASKS:
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

    if task_type in CANDIDATE_TASKS + REVIEW_TASKS:
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
        step_input["task_type"] in REPORT_TASKS + LINEAGE_TASKS + CANDIDATE_TASKS + REVIEW_TASKS
        and (i.code in {"unknown_passage_id", "unknown_cell_id", "unknown_source_id", "unknown_column_id", "unknown_element_ref"}
             or step_input["task_type"] in REVIEW_TASKS)))
    report.warnings.extend(w for w in probe.warnings if elsewhere(w.path))


def _semantic_checks(step_input: dict[str, Any], output_type: str, result: dict[str, Any], report: ValidationReport) -> None:
    allow = {k: set(v) for k, v in step_input["allowlist"].items()}
    if output_type == "GroundedAnswerDraft":
        _check_answer(step_input, allow, result, report)
        _check_phrasing(step_input, result, report)
        _check_math(step_input, result, report)
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
    elif output_type == "TableColumnProposal":
        _check_column_proposal(step_input, result, report)
    elif output_type == "ResearchTitle":
        _check_title(step_input, result, report)
    elif output_type == "VocabularyLabels":
        _check_vocabulary_labels(allow, result, report)
    elif output_type == "CriterionProposal":
        _check_criterion_proposal(step_input, result, report)
    elif output_type == "TermSuggestions":
        _check_term_suggestions(allow, result, report)
    elif output_type in ("SearchQuery", "KillSearchQuery"):
        _check_search_query(result, report)
    elif output_type == "AbstractScreening":
        _check_abstract_screening(allow, result, report)
    elif output_type == "FulltextAdjudication":
        _check_fulltext_adjudication(step_input, allow, result, report)
    elif output_type == "ReportPlanDraft":
        _check_report_plan(step_input, allow, result, report)
    elif output_type == "ReportSectionDraft":
        _check_report_section(step_input, allow, result, report)
        _check_phrasing(step_input, result, report, fields=_report_phrasing_fields(result))
        _check_math(step_input, result, report, fields=_report_math_fields(result))
    elif output_type == "ReportPhraseRepairDraft":
        _check_report_phrase_repair(step_input, result, report)
    elif output_type == "ReportReview":
        _check_report_review(step_input, result, report)


@cache
def _phrasebank_text() -> str:
    return (SKILL_DIR / phrasebank.PHRASEBANK).read_text(encoding="utf-8")


MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+\$", re.DOTALL)


def _without_math(text: str) -> str:
    """LaTeX math reads as one slot word, so its symbols and periods neither count as frame words nor split sentences."""
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
    """Warn about damaged LaTeX, equations supported only by abstract-level passages, and numbers or equations supported
    only by OCR text of scanned pages (D51)."""
    if fields is None:
        fields = [(f"/claims/{i}/text", c["text"]) for i, c in enumerate(draft["claims"])]
        fields += [(f"/limitations/{i}/text", lim["text"]) for i, lim in enumerate(draft["limitations"])]
        fields += [(f"/unanswered_aspects/{i}", text) for i, text in enumerate(draft["unanswered_aspects"])]
    for path, text in fields:
        dollars = sum(char == "$" and not _is_escaped(text, i) for i, char in enumerate(text))
        spans = _math_spans(text)
        if dollars % 2 or any(not _math_span_is_well_formed(span) for span in spans):
            report.warnings.append(Issue("math_not_well_formed", path,
                                         "math delimiters, braces or environments are not balanced"))

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


def _check_phrasing(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport,
                    fields: list[tuple[str, str]] | None = None) -> None:
    """Check the answer's prose against the Academic Phrasebank frames in the answer language.

    Findings are warnings shown with the answer; they never reject it or ask for a repair (D19).
    """
    requested_language = draft["answer_language"] if fields is None else phrasebank.frames_language(step_input)
    language = phrasebank.checked_language(requested_language)
    if language is None or not phrasebank.has_frames(_phrasebank_text(), language):
        report.warnings.append(Issue("phrasing_not_checked", "/answer_language",
                                     f"no phrasebank frames for {requested_language!r}"))
        return
    if fields is None:
        fields = [(f"/claims/{i}/text", c["text"]) for i, c in enumerate(draft["claims"])]
        fields += [(f"/limitations/{i}/text", lim["text"]) for i, lim in enumerate(draft["limitations"])]
        fields += [(f"/unanswered_aspects/{i}", text) for i, text in enumerate(draft["unanswered_aspects"])]
        if draft["capability_notice"]:
            fields.append(("/capability_notice", draft["capability_notice"]))
    for path, text in fields:
        for sentence in phrasebank.unframed(_without_math(text), _phrasebank_text(), language):
            report.warnings.append(Issue("sentence_without_phrasebank_frame", path,
                                         f"{sentence!r} follows no phrasebank frame"))
    # A claim reports what a cited source says; words naming the writer's own work would attribute it to this answer.
    for i, claim in enumerate(draft["claims"]):
        for phrase in phrasebank.own_work_phrases(_without_math(claim["text"]), language):
            report.warnings.append(Issue("own_work_phrase_in_claim", f"/claims/{i}/text",
                                         f"{phrase!r} names this answer's own work, not a cited source"))
    # "Previous studies" and the like say several sources state it; a claim whose passages come from one source may not.
    source_of = {p["passage_id"]: p["source_id"] for p in step_input["passages"]}
    for i, claim in enumerate(draft["claims"]):
        if len({source_of.get(pid) for pid in claim["passage_ids"]}) != 1:
            continue
        for phrase in phrasebank.plural_source_phrases(_without_math(claim["text"]), language):
            report.warnings.append(Issue("plural_sources_for_one_source", f"/claims/{i}/text",
                                       f"{phrase!r} speaks of several sources, but this claim cites one source; "
                                       "use a frame for reporting what one source states"))


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


def _check_term_suggestions(allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    """A proposed name must say which given phrase it is another name for, and nothing else is an error (SW2.5).

    The one error is a `synonym_of` outside the allowlist: without a given phrase behind it a proposal has no block
    and no anchor, and code would have to invent both. Everything else code settles and records instead —
    `workflow.suggestions.screen` drops a repeated, already present, too long, claim-carrying or exclusion-carrying
    proposal with its reason, and the user never sees a query it entered.
    """
    for index, term in enumerate(draft["terms"]):
        if term["synonym_of"] not in allow.get("phrases", set()):
            report.issues.append(Issue("phrase_not_in_allowlist", f"/terms/{index}/synonym_of", term["synonym_of"]))


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


def report_section_repair_issues(failed: Any, repaired: Any) -> list[Issue]:
    """Check key coverage and kept evidence records, including readable parts of invalid drafts."""
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
            issues.append(Issue("repair_dropped_claim", "/claims", key))
    for entry in old_entries:
        if not any(r.get("context") == entry["context"] and r.get("reason") == entry["reason"] for r in new_entries):
            issues.append(Issue("repair_dropped_insufficient_evidence", "/insufficient_evidence", entry["context"]))
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
        if isinstance(identifier, str) and identifier not in allowed[kind]:
            report.issues.append(Issue(codes[kind], path, identifier))
    if draft["section_id"] != step_input["report_target"]["section_id"]:
        report.issues.append(Issue("report_section_mismatch", "/section_id", draft["section_id"]))
    for i, anchor in enumerate(draft["citation_anchors"]):
        if (anchor["passage_id"] is None) == (anchor["cell_id"] is None):
            report.issues.append(Issue(
                "citation_anchor_target_count", f"/citation_anchors/{i}",
                "expected exactly one of passage_id/cell_id to be non-null",
            ))
        if anchor["passage_id"] in allow["passage_ids"]:
            passage = next((p for p in step_input["passages"] if p["passage_id"] == anchor["passage_id"]), None)
            if passage is None or locate_anchor(anchor["quote"], passage["text"]) is None:
                report.issues.append(Issue("anchor_not_in_passage", f"/citation_anchors/{i}/quote",
                                           "the quote was not found in the cited passage"))
        if anchor["cell_id"] in allow.get("cell_ids", set()):
            cell = next((c for c in step_input["report_target"]["cells"] if c["cell_id"] == anchor["cell_id"]), None)
            if cell is None or not any(locate_anchor(anchor["quote"], e["quote"]) is not None
                                       for e in cell.get("evidence", []) if e.get("quote")):
                report.issues.append(Issue("anchor_not_in_cell_evidence", f"/citation_anchors/{i}/quote",
                                           "the quote was not found in one stored cell evidence quote"))
    for i, claim in enumerate(draft["claims"]):
        if draft["section_id"] == "VIII":
            report.issues.extend(Issue(issue.code, f"/claims/{i}{issue.path}", issue.message)
                                 for issue in limitations_claim_issues(claim))
        for j, gap_id in enumerate(claim["gap_refs"]):
            if gap_id not in allow.get("gap_ids", set()):
                report.issues.append(Issue("unknown_gap_ref", f"/claims/{i}/gap_refs/{j}", gap_id))
        # An equation's origin (D104): a passage of the StepInput, cited by this same claim, whose text_source it repeats.
        origin = claim.get("equation_origin")
        if origin is not None:
            passage = next((p for p in step_input.get("passages", []) if p["passage_id"] == origin["passage_id"]), None)
            if passage is None or origin["passage_id"] not in allow["passage_ids"]:
                continue
            if origin["passage_id"] not in claim["passage_ids"]:
                report.issues.append(Issue("equation_origin_not_cited", f"/claims/{i}/equation_origin/passage_id", origin["passage_id"]))
            elif origin["text_source"] != passage.get("text_source"):
                report.issues.append(Issue("equation_origin_mismatch", f"/claims/{i}/equation_origin/text_source",
                                           f"passage text_source is {passage.get('text_source')!r}"))


def _check_report_phrase_repair(step_input: dict[str, Any], draft: dict[str, Any],
                                report: ValidationReport) -> None:
    requested = {item["sentence_id"] for item in step_input["report_target"]["repair_request"]["sentences"]}
    for i, repair in enumerate(draft["repairs"]):
        if repair["sentence_id"] not in requested:
            report.issues.append(Issue("unknown_repair_sentence", f"/repairs/{i}/sentence_id", repair["sentence_id"]))


def _check_report_review(step_input: dict[str, Any], draft: dict[str, Any],
                         report: ValidationReport) -> None:
    claims = {claim["claim_key"]: section for section in step_input["report_target"]["review_sections"]
              for claim in section["claims"]}
    repairs = {repair["sentence_id"]: section for section in step_input["report_target"]["review_sections"]
               for repair in section["repairs"]}
    for i, finding in enumerate(draft["findings"]):
        key, sentence = finding["claim_key"], finding["sentence_id"]
        if key is not None and key not in claims:
            report.issues.append(Issue("review_claim_unknown", f"/findings/{i}/claim_key", key))
        if sentence is not None and (sentence not in repairs or (key is not None and claims.get(key) is not repairs.get(sentence))):
            report.issues.append(Issue("review_sentence_not_repaired", f"/findings/{i}/sentence_id", sentence))
        if sentence is not None and key is not None and not sentence.startswith(key + "#"):
            report.issues.append(Issue("review_sentence_claim_mismatch", f"/findings/{i}/sentence_id", sentence))
        if finding["code"] == "support_broken" and sentence is None:
            report.issues.append(Issue("support_broken_without_sentence", f"/findings/{i}/sentence_id", "required"))


def _check_answer(step_input: dict[str, Any], allow: dict[str, set[str]], draft: dict[str, Any], report: ValidationReport) -> None:
    title_words = _title_words(draft["title"])
    if title_words > 15:
        report.issues.append(Issue("answer_title_too_long", "/title",
                                   f"expected at most 15 words, got {title_words}"))
    labels: set[str] = set()
    cited_by_claim: dict[str, set[str]] = {}
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

    # A published citation must resolve to source-owned text so the evidence panel can show the exact highlighted
    # span (D27). Missing or unlocatable anchors go through the same bounded repair path as other structural errors.
    passage_text = {p["passage_id"]: p["text"] for p in step_input["passages"]}
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
        if locate_anchor(anchor["quote"], passage_text.get(anchor["passage_id"], "")) is None:
            report.issues.append(Issue("anchor_not_in_passage", f"/citation_anchors/{i}/quote",
                                       f"{anchor['claim_label']}:{anchor['passage_id']}: the quoted sentence was not found in the cited passage"))
    for claim_label, passage_id in sorted(required_anchors - seen_anchors):
        report.issues.append(Issue("missing_citation_anchor", "/citation_anchors",
                                   f"{claim_label}:{passage_id}: this citation requires an exact contiguous quote"))
    for i, limitation in enumerate(draft["limitations"]):
        for j, sid in enumerate(limitation["source_ids"]):
            if sid not in allow["source_ids"]:
                report.issues.append(Issue("unknown_source_id", f"/limitations/{i}/source_ids/{j}", sid))


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
        ("passage_ids", "psg_P"), ("source_ids", "srv_S"), ("column_ids", "col_C"), ("cell_ids", "cel_L"))),
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


def report_citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Number from stored records first, then display-only references; never extend an allowlist."""
    handles: dict[str, str] = {}
    counts = dict.fromkeys(("psg_P", "srv_S", "cel_L", "col_C"), 0)

    def add(identifier: Any, kind: str) -> None:
        if isinstance(identifier, str) and identifier not in handles:
            counts[kind] += 1
            handles[identifier] = f"{kind}{counts[kind]:07d}"

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
    handles: dict[str, str] = {}
    counts = dict.fromkeys(("psg_P", "srv_S", "cel_L"), 0)

    def add(identifier: Any, kind: str) -> None:
        if isinstance(identifier, str) and identifier not in handles:
            counts[kind] += 1
            handles[identifier] = f"{kind}{counts[kind]:07d}"

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
    handles: dict[str, str] = {}
    counts = dict.fromkeys(("psg_P", "srv_S", "ele_E"), 0)

    def add(identifier: Any, kind: str) -> None:
        if isinstance(identifier, str) and identifier not in handles:
            counts[kind] += 1
            handles[identifier] = f"{kind}{counts[kind]:07d}"

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
    if step_input.get("task_type") in REPORT_TASKS + LINEAGE_TASKS + CANDIDATE_TASKS:
        fields = CANDIDATE_INPUT_ID_FIELDS if step_input["task_type"] in CANDIDATE_TASKS else (
            LINEAGE_INPUT_ID_FIELDS if step_input["task_type"] in LINEAGE_TASKS else REPORT_INPUT_ID_FIELDS)
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


def name_sources_in_prose(step_input: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Replace citation handles the model wrote into an answer's prose with source titles, after validation.

    A handle would reach the reader as `srv_S0000002`. Validation (including text length limits) applies to what the model
    wrote, so a long list of titles cannot turn a valid answer invalid.
    """
    real = {handle: identifier for identifier, handle in citation_handles(step_input).items()}
    titles = {s["source_id"]: s["title"] for s in step_input.get("sources", [])}
    titles |= {p["passage_id"]: titles[p["source_id"]] for p in step_input.get("passages", []) if p["source_id"] in titles}
    named = {handle: f"“{titles[identifier]}”" for handle, identifier in real.items() if identifier in titles}
    if named:
        pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, named)) + r")\b")
        prose = lambda text: pattern.sub(lambda m: named[m.group(0)], text) if isinstance(text, str) else text
        for items in (data.get("claims"), data.get("limitations")):
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and "text" in item:
                    item["text"] = prose(item["text"])
        if isinstance(data.get("unanswered_aspects"), list):
            data["unanswered_aspects"] = [prose(text) for text in data["unanswered_aspects"]]
        if "capability_notice" in data:
            data["capability_notice"] = prose(data["capability_notice"])
    return data


def salvage_answer_draft(step_input: dict[str, Any], draft: dict[str, Any]) -> tuple[dict[str, Any], list[Issue]]:
    """Remove the citation defects that need no new text from a final, still invalid answer draft.

    A (claim, passage) pair quoted more than once keeps its first locatable quote (as D43 accepts for cells); an anchor for
    a passage its claim does not cite is dropped; a citation without a locatable quote is dropped only when the claim keeps
    another quoted citation. Claims are never removed and nothing is added, so the caller must validate the result again.
    """
    warnings: list[Issue] = []
    claims = [c for c in draft.get("claims", []) if isinstance(c, dict) and isinstance(c.get("passage_ids"), list)]
    anchors = [a for a in draft.get("citation_anchors", []) if isinstance(a, dict)]
    if len(claims) != len(draft.get("claims", [])) or len(anchors) != len(draft.get("citation_anchors", [])):
        return draft, warnings
    text = {p["passage_id"]: p["text"] for p in step_input["passages"]}
    located = lambda a: isinstance(a.get("quote"), str) and locate_anchor(a["quote"], text.get(a.get("passage_id"), "")) is not None
    cited = {(c.get("claim_label"), pid) for c in claims for pid in c["passage_ids"]}
    chosen: dict[tuple[Any, Any], int] = {}
    for i, anchor in enumerate(anchors):
        pair = (anchor.get("claim_label"), anchor.get("passage_id"))
        if pair not in cited:
            warnings.append(Issue("uncited_anchor_ignored", f"/citation_anchors/{i}", f"{pair[0]}:{pair[1]}"))
        elif pair not in chosen:
            chosen[pair] = i
        else:
            warnings.append(Issue("duplicate_citation_anchor_ignored", f"/citation_anchors/{i}", f"{pair[0]}:{pair[1]}"))
            if not located(anchors[chosen[pair]]) and located(anchor):
                chosen[pair] = i
    draft["citation_anchors"] = [anchors[i] for i in sorted(chosen.values())]
    quoted = {pair for pair, i in chosen.items() if located(anchors[i])}
    for i, claim in enumerate(claims):
        keep = [pid for pid in claim["passage_ids"] if (claim.get("claim_label"), pid) in quoted]
        if keep and len(keep) < len(claim["passage_ids"]):
            for pid in claim["passage_ids"]:
                if pid not in keep:
                    warnings.append(Issue("citation_without_quote_removed", f"/claims/{i}/passage_ids", f"{claim.get('claim_label')}:{pid}"))
            claim["passage_ids"] = keep
    kept = {(c.get("claim_label"), pid) for c in claims for pid in c["passage_ids"]}
    draft["citation_anchors"] = [a for a in draft["citation_anchors"] if (a.get("claim_label"), a.get("passage_id")) in kept]
    return draft, warnings


PADDED_HANDLE = re.compile(r"^(psg_P|srv_S|col_C|cnd_C|cel_L|ele_E)0*(\d{1,7})$")


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
    if step_input.get("task_type") in REPORT_TASKS + LINEAGE_TASKS + CANDIDATE_TASKS:
        fields = CANDIDATE_OUTPUT_ID_FIELDS[step_input["task_type"]] if step_input["task_type"] in CANDIDATE_TASKS else (
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
    for anchor in data.get("citation_anchors", []):
        if isinstance(anchor, dict) and isinstance(anchor.get("passage_id"), str):
            anchor["passage_id"] = real(anchor["passage_id"])
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

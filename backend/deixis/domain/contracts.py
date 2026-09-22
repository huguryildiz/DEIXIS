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
from deixis.paths import CONTRACTS_DIR, SKILL_DIR
from deixis.providers import query_compiler
from deixis.workflow.criterion import (MAX_PHRASE_WORDS, PARTS_PER_PROPOSAL, PHRASES_PER_PART,
                                       norm as normalize_phrase)
from deixis.workflow.tables import MAX_COLUMNS_PER_CALL, InvalidTableInput, check_value, column_spec

SCHEMA_FILES = {
    "SearchPlan": "search-plan.schema.json",
    "ScreeningProposal": "screening-proposal.schema.json",
    "GroundedAnswerDraft": "grounded-answer-draft.schema.json",
    "ClarificationRequest": "clarification-request.schema.json",
    "AnswerReview": "answer-review.schema.json",
    "EvidenceCellDraft": "evidence-cell-draft.schema.json",
    "TableColumnProposal": "table-column-proposal.schema.json",
    "ResearchTitle": "research-title.schema.json",
    "VocabularyLabels": "vocabulary-labels.schema.json",
    "CriterionProposal": "criterion-proposal.schema.json",
    "TermSuggestions": "term-suggestions.schema.json",
    "AbstractScreening": "abstract-screening.schema.json",
    "FulltextAdjudication": "fulltext-adjudication.schema.json",
    "StepInput": "step-input.schema.json",
    "ReportPlanDraft": "report-plan.schema.json",
    "ReportSectionDraft": "report-section-draft.schema.json",
    "ReportPhraseRepairDraft": "report-phrase-repair.schema.json",
    "ReportReview": "report-review.schema.json",
}
SCHEMA_VERSIONS = {
    "SearchPlan": "deixis.search_plan.v2",
    "ScreeningProposal": "deixis.screening_proposal.v1",
    "GroundedAnswerDraft": "deixis.grounded_answer_draft.v3",
    "ClarificationRequest": "deixis.clarification_request.v1",
    "AnswerReview": "deixis.answer_review.v1",
    "EvidenceCellDraft": "deixis.evidence_cell_draft.v1",
    "TableColumnProposal": "deixis.table_column_proposal.v1",
    "ResearchTitle": "deixis.research_title.v1",
    "VocabularyLabels": "deixis.vocabulary_labels.v1",
    "CriterionProposal": "deixis.criterion_proposal.v1",
    "TermSuggestions": "deixis.term_suggestions.v1",
    "AbstractScreening": "deixis.abstract_screening.v1",
    "FulltextAdjudication": "deixis.fulltext_adjudication.v1",
    "ReportPlanDraft": "deixis.report_plan_draft.v2",
    "ReportSectionDraft": "deixis.report_section_draft.v1",
    "ReportPhraseRepairDraft": "deixis.report_phrase_repair_draft.v1",
    "ReportReview": "deixis.report_review.v1",
}
# Model outputs each task may return. More than one output type is wrapped in an
# object with one nullable property per type; exactly one must be non-null.
TASK_OUTPUTS = {
    "search_plan": ("SearchPlan", "ClarificationRequest"),
    "screening": ("ScreeningProposal",),
    "grounded_answer": ("GroundedAnswerDraft",),
    "answer_review": ("AnswerReview",),
    "cell_extraction": ("EvidenceCellDraft",),
    "table_columns": ("TableColumnProposal",),
    "research_title": ("ResearchTitle",),
    "vocabulary_labels": ("VocabularyLabels",),
    "criterion_proposal": ("CriterionProposal",),
    "term_suggestions": ("TermSuggestions",),
    "abstract_screening": ("AbstractScreening",),
    "fulltext_adjudication": ("FulltextAdjudication",),
    "report_plan": ("ReportPlanDraft",),
    "report_section": ("ReportSectionDraft",),
    "report_phrase_repair": ("ReportPhraseRepairDraft",),
    "report_review": ("ReportReview",),
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
# The cell states EvidenceCellDraft allows. inaccessible is the system's, not_verified and not_reported a person's (D37).
MODEL_CELL_STATES = ("value", "unknown", "not_applicable", "not_found_in_inspected_scope")
WRAPPER_KEYS = {
    "SearchPlan": "search_plan",
    "ClarificationRequest": "clarification_request",
}
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
    report_target = step_input.get("report_target")
    if (report_target is not None) != (step_input["task_type"] in REPORT_TASKS):
        issues.append(Issue("report_target_mismatch", "/report_target", step_input["task_type"]))
    elif report_target is not None:
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
        # A step gets one repair, so the first report names what the rules would reject as well as what the schema
        # does; a draft whose shape the rules cannot read is reported on its schema errors alone (slice 13a, run 5).
        _semantic_checks_best_effort(step_input, data, report)
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
    _semantic_checks(step_input, output_type, result, report)
    return report


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

    report.issues.extend(i for i in probe.issues if elsewhere(i.path))
    report.warnings.extend(w for w in probe.warnings if elsewhere(w.path))


def _semantic_checks(step_input: dict[str, Any], output_type: str, result: dict[str, Any], report: ValidationReport) -> None:
    allow = {k: set(v) for k, v in step_input["allowlist"].items()}
    if output_type == "SearchPlan":
        _check_search_plan(step_input, result, report)
    elif output_type == "ScreeningProposal":
        _check_screening(allow, result, report)
    elif output_type == "GroundedAnswerDraft":
        _check_answer(step_input, allow, result, report)
        _check_phrasing(step_input, result, report)
        _check_math(step_input, result, report)
    elif output_type == "AnswerReview":
        _check_review(step_input, result, report)
    elif output_type == "EvidenceCellDraft":
        _check_cells(step_input, allow, result, report)
    elif output_type == "TableColumnProposal":
        _check_column_proposal(step_input, result, report)
    elif output_type == "ResearchTitle":
        _check_title(step_input, result, report)
    elif output_type == "VocabularyLabels":
        _check_vocabulary_labels(allow, result, report)
    elif output_type == "CriterionProposal":
        _check_criterion_proposal(result, report)
    elif output_type == "TermSuggestions":
        _check_term_suggestions(allow, result, report)
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


def _check_search_plan(step_input: dict[str, Any], plan: dict[str, Any], report: ValidationReport) -> None:
    """The model gives vocabulary and providers; the application compiles the queries from them (D44)."""
    issues: list[Issue] = []
    cores = sum(c["role"] == "core" for c in plan["concepts"])
    if cores != 1:
        issues.append(Issue("core_concept_count", "/concepts",
                            f"{cores} concepts have role core; give exactly one core concept: the discriminating decision or "
                            "mechanism phrase that every query requires, not the broad field name"))
    for i, concept in enumerate(plan["concepts"]):
        if concept["role"] == "core" and not any(s.strip() for s in concept["synonyms"]):
            issues.append(Issue("core_without_synonyms", f"/concepts/{i}/synonyms",
                                "the core concept has no synonyms; synonyms are the search terms, in the literature's language"))
    enabled = set(step_input["enabled_providers"])
    for i, provider in enumerate(plan["providers"]):
        if provider not in enabled:
            issues.append(Issue("provider_not_enabled", f"/providers/{i}", provider))
    if len(set(plan["providers"])) != len(plan["providers"]):
        issues.append(Issue("duplicate_provider", "/providers", "list each provider once"))
    if set(plan["providers"]) == {"serpapi"}:
        issues.append(Issue("supplementary_provider_limit", "/providers",
                            "SerpApi only supplements direct scholarly providers; choose one of them as well"))
    if not issues and not query_compiler.compile_queries(plan, step_input["enabled_providers"],
                                                         step_input["budget"]["max_provider_requests"]):
        issues.append(Issue("no_compiled_query", "/concepts",
                            "no provider query can be built from these concepts and providers; give the core concept "
                            "search-term synonyms and at least one other concept with synonyms, or choose another provider"))
    report.issues += issues


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


def _check_criterion_proposal(draft: dict[str, Any], report: ValidationReport) -> None:
    """The bounds one proposal must hold, enforced in code rather than left to the prompt (SW15.1).

    All of them are errors: a proposal that breaks one is not half-used, because the consensus over three runs would
    then count a part or a phrase that the step was not allowed to write. A phrase appearing in two parts is not an
    error; the consensus gives it the first part it stands in.
    """
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


def _check_report_section(step_input: dict[str, Any], allow: dict[str, set[str]],
                          draft: dict[str, Any], report: ValidationReport) -> None:
    if draft["section_id"] != step_input["report_target"]["section_id"]:
        report.issues.append(Issue("report_section_mismatch", "/section_id", draft["section_id"]))
    for i, anchor in enumerate(draft["citation_anchors"]):
        if (anchor["passage_id"] is None) == (anchor["cell_id"] is None):
            report.issues.append(Issue(
                "citation_anchor_target_count", f"/citation_anchors/{i}",
                "expected exactly one of passage_id/cell_id to be non-null",
            ))
    for i, claim in enumerate(draft["claims"]):
        for j, passage_id in enumerate(claim["passage_ids"]):
            if passage_id not in allow["passage_ids"]:
                report.issues.append(Issue("unknown_passage_id", f"/claims/{i}/passage_ids/{j}", passage_id))
        for j, cell_id in enumerate(claim["cell_ids"]):
            if cell_id not in allow.get("cell_ids", set()):
                report.issues.append(Issue("unknown_cell_id", f"/claims/{i}/cell_ids/{j}", cell_id))
        for j, gap_id in enumerate(claim["gap_refs"]):
            if gap_id not in allow.get("gap_ids", set()):
                report.issues.append(Issue("unknown_gap_ref", f"/claims/{i}/gap_refs/{j}", gap_id))


def _check_report_phrase_repair(step_input: dict[str, Any], draft: dict[str, Any],
                                report: ValidationReport) -> None:
    requested = {item["sentence_id"] for item in step_input["report_target"]["repair_request"]["sentences"]}
    for i, repair in enumerate(draft["repairs"]):
        if repair["sentence_id"] not in requested:
            report.issues.append(Issue("unknown_repair_sentence", f"/repairs/{i}/sentence_id", repair["sentence_id"]))


def _check_report_review(step_input: dict[str, Any], draft: dict[str, Any],
                         report: ValidationReport) -> None:
    pass  # Report-level semantic review and support-breaking repair handling arrive in 1f.


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


def citation_handles(step_input: dict[str, Any]) -> dict[str, str]:
    """Short per-step identifiers shown to the model in place of passage and source IDs.

    With 48 sources and passages, `gpt-5.6-luna` mis-copied long random IDs (a source suffix under the passage prefix,
    a dropped character). Handles are numbered in StepInput order, so they are recomputed from the stored StepInput;
    passage and source handles never share a suffix, so a swapped prefix stays an unknown ID instead of another record.
    """
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


PADDED_HANDLE = re.compile(r"^(psg_P|srv_S|col_C|cnd_C)0*(\d{1,7})$")


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

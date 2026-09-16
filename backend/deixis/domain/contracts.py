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
from deixis.providers import query_rules
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
    "StepInput": "step-input.schema.json",
}
SCHEMA_VERSIONS = {
    "SearchPlan": "deixis.search_plan.v1",
    "ScreeningProposal": "deixis.screening_proposal.v1",
    "GroundedAnswerDraft": "deixis.grounded_answer_draft.v3",
    "ClarificationRequest": "deixis.clarification_request.v1",
    "AnswerReview": "deixis.answer_review.v1",
    "EvidenceCellDraft": "deixis.evidence_cell_draft.v1",
    "TableColumnProposal": "deixis.table_column_proposal.v1",
    "ResearchTitle": "deixis.research_title.v1",
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
}
EXTRACTION_TASKS = ("cell_extraction", "table_columns")
# The cell states EvidenceCellDraft allows. inaccessible is the system's, not_verified and not_reported a person's (D37).
MODEL_CELL_STATES = ("value", "unknown", "not_applicable", "not_found_in_inspected_scope")
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
    return report


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


def _check_math(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    """Warn about damaged LaTeX and equations supported only by abstract-level passages."""
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


def _check_phrasing(step_input: dict[str, Any], draft: dict[str, Any], report: ValidationReport) -> None:
    """Check the answer's prose against the Academic Phrasebank frames in the answer language.

    Findings are warnings shown with the answer; they never reject it or ask for a repair (D19).
    """
    language = phrasebank.checked_language(draft["answer_language"])
    if language is None or not phrasebank.has_frames(_phrasebank_text(), language):
        report.warnings.append(Issue("phrasing_not_checked", "/answer_language",
                                     f"no phrasebank frames for {draft['answer_language']!r}"))
        return
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


def openalex_or_is_ambiguous(query: str) -> bool:
    """True when OpenAlex would silently mis-read OR in the query.

    Probed live on 2026-09-14: `"molecular communication" optimization OR "operations research"` and
    `"molecular communication" AND optimization OR scheduling` both returned exactly the 3,392 works of the phrase
    alone, while `"molecular communication" AND (optimization OR scheduling)` returned 308. Plain adjacency without OR
    behaves as AND. So OR is accepted only when, at its nesting level, it is the sole operator, and a group containing
    OR is joined to its neighbours with explicit operators.
    """
    tokens = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', query)
    levels: list[dict[str, bool]] = [{"or": False, "other": False, "implicit": False}]
    previous = None  # "operand", "operator" or "open"
    closed_or = False  # the operand just before is a group containing OR
    for token in tokens:
        adjacent = previous == "operand"  # implicit AND with the previous operand
        if token == "(":
            if adjacent:
                if closed_or:
                    return True
                levels[-1]["other"] = True
            levels.append({"or": False, "other": False, "implicit": adjacent})
            previous, closed_or = "open", False
        elif token == ")":
            if len(levels) == 1:
                return True  # unbalanced
            inner = levels.pop()
            if inner["or"] and (inner["other"] or inner["implicit"]):
                return True
            previous, closed_or = "operand", inner["or"]
        elif token in ("AND", "NOT", "OR"):
            levels[-1]["or" if token == "OR" else "other"] = True
            previous, closed_or = "operator", False
        else:
            if adjacent:
                if closed_or:
                    return True
                levels[-1]["other"] = True
            previous, closed_or = "operand", False
    return len(levels) != 1 or (levels[0]["or"] and levels[0]["other"])


OPENALEX_MAX_OPERATORS = 5  # OpenAlex throttles queries with more boolean operators


def openalex_query_shape_issues(query: str) -> list[str]:
    """Structural limits for one OpenAlex title-and-abstract query.

    Every unquoted word and every AND-joined part is required, and results are read in relevance order, so a query that
    requires many parts matches few records (live 2026-09-14: `molecular communication resource allocation scheduling
    routing optimization` returned 4 works and none of 22 user-known papers).
    """
    tokens = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', query)
    issues = []
    if sum(t in ("AND", "OR", "NOT") for t in tokens) > OPENALEX_MAX_OPERATORS:
        issues.append(f"more than {OPENALEX_MAX_OPERATORS} AND/OR/NOT operators")
    depth, top_operands, top_or, run, longest = 0, 0, False, 0, 0
    for token in tokens:
        if token == "(":
            top_operands += depth == 0
            depth, run = depth + 1, 0
        elif token == ")":
            depth, run = max(0, depth - 1), 0
        elif token in ("AND", "OR", "NOT"):
            top_or = top_or or (depth == 0 and token == "OR")
            run = 0
        else:
            top_operands += depth == 0
            run = 0 if token.startswith('"') else run + 1
            longest = max(longest, run)
    if (1 if top_or else top_operands) > 2:
        issues.append("more than two required parts; keep the quoted core phrase and one parenthesized group of alternatives")
    if longest >= 3:
        issues.append("three or more unquoted words in a row are all required; quote the phrase or put alternatives in an OR group")
    return issues


def _check_search_plan(step_input: dict[str, Any], plan: dict[str, Any], report: ValidationReport) -> None:
    enabled = set(step_input["enabled_providers"])
    for i, query in enumerate(plan["queries"]):
        provider, text, path = query["provider_id"], query["query_text"], f"/queries/{i}/query_text"
        if provider not in enabled:
            report.issues.append(
                Issue("provider_not_enabled", f"/queries/{i}/provider_id", provider)
            )
            continue  # never sent, so its syntax does not matter
        name, example = query_rules.NAMES[provider], query_rules.EXAMPLES[provider]
        syntax = query_rules.syntax_issues(provider, text)
        for problem in syntax:
            report.issues.append(Issue("provider_query_syntax", path, f"{name}: {problem}, e.g. {example}"))
        boolean = query_rules.boolean_part(provider, text)
        if boolean is None or syntax:
            continue
        # OpenAlex's boolean limits were measured (D8, D11); IEEE Xplore, CORE and a Scopus field group take the same form.
        if openalex_or_is_ambiguous(boolean):
            report.issues.append(Issue(
                "provider_query_syntax", path,
                'OpenAlex ignores terms beside an unparenthesized OR; put OR alternatives in parentheses joined with AND, '
                'e.g. "molecular communication" AND (optimization OR scheduling)' if provider == "openalex" else
                f"{name} may misread an unparenthesized OR; put OR alternatives in parentheses joined with AND, e.g. {example}",
            ))
        for problem in openalex_query_shape_issues(boolean):
            report.issues.append(Issue("provider_query_shape", path, f"{problem}, e.g. {example}"))
    supplementary = [q for q in plan["queries"] if q["provider_id"] == "serpapi"]
    if len(supplementary) > 1:
        report.issues.append(Issue("supplementary_provider_limit", "/queries",
                                   "SerpApi is supplementary with a small monthly allowance; use at most one SerpApi query"))
    if supplementary and len(supplementary) == len(plan["queries"]):
        report.issues.append(Issue("supplementary_provider_limit", "/queries",
                                   "SerpApi only supplements direct scholarly providers; add a query for one of them"))
    openalex_queries = [q["query_text"] for q in plan["queries"] if q["provider_id"] == "openalex"]
    if openalex_queries and not any(re.search(r'"[^"]*\S\s+\S[^"]*"', q) for q in openalex_queries):
        report.issues.append(Issue(
            "provider_query_shape", "/queries", 'no OpenAlex query quotes a multiword core phrase, e.g. "molecular communication"',
        ))
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
    return handles | {s["source_id"]: f"srv_S{n:07d}" for n, s in enumerate(step_input["sources"], start=1)}


def with_citation_handles(step_input: dict[str, Any]) -> dict[str, Any]:
    handles = citation_handles(step_input)
    shown = copy.deepcopy(step_input)
    for passage in shown["passages"]:
        passage["passage_id"], passage["source_id"] = handles[passage["passage_id"]], handles[passage["source_id"]]
    for source in shown["sources"]:
        source["source_id"] = handles[source["source_id"]]
    for claim in shown.get("claims_under_review", []):
        claim["passage_ids"] = [handles.get(i, i) for i in claim["passage_ids"]]
    if target := shown.get("extraction_target"):
        target["source_id"] = handles.get(target["source_id"], target["source_id"])
        for column in target["columns"]:
            column["column_id"] = handles[column["column_id"]]
    for key in ("passage_ids", "source_ids"):
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


def resolve_citation_handles(step_input: dict[str, Any], raw: str) -> str | dict[str, Any]:
    """Map handles in a grounded answer or cell draft back to IDs; anything else is left for validation to report."""
    real = {handle: identifier for identifier, handle in citation_handles(step_input).items()}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, dict):
        return raw
    for items, key in ((data.get("claims"), "passage_ids"), (data.get("limitations"), "source_ids")):
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get(key), list):
                item[key] = [real.get(i, i) if isinstance(i, str) else i for i in item[key]]
    for anchor in data.get("citation_anchors", []):
        if isinstance(anchor, dict) and isinstance(anchor.get("passage_id"), str):
            anchor["passage_id"] = real.get(anchor["passage_id"], anchor["passage_id"])
    cells = data.get("cells")
    for cell in cells if isinstance(cells, list) else []:
        if not isinstance(cell, dict):
            continue
        if isinstance(cell.get("column_id"), str):
            cell["column_id"] = real.get(cell["column_id"], cell["column_id"])
        evidence = cell.get("evidence")
        for item in evidence if isinstance(evidence, list) else []:
            if isinstance(item, dict) and isinstance(item.get("passage_id"), str):
                item["passage_id"] = real.get(item["passage_id"], item["passage_id"])
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

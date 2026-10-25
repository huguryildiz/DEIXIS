"""Offline transport guard; synthetic cases do not establish live API acceptance.

The AST coverage guard cannot see aliased imports, builders without a schema
suffix, or schemas built inline. It is bounded coverage, not a proof.
"""

import ast
import copy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from deixis.domain import contracts


TASKS = (
    "owner_review", "grounded_answer", "followup_answer", "answer_review", "cell_extraction",
    "table_columns", "research_title", "vocabulary_labels", "criterion_proposal",
    "search_query", "abstract_screening", "fulltext_adjudication",
    "report_plan", "report_section", "report_review",
    "lineage_links", "claim_decomposition", "kill_search_query", "claim_assessment", "followup_search_query",
    "citation_check", "statement_check",
)
BUILDERS = {"model_output_schema", "step_output_schema", "report_section_anchor_patch_schema"}
EXCLUSIONS = {
    ("deixis/domain/contracts.py", "load_schema"): "Canonical files, never sent as is.",
    ("deixis/domain/contracts.py", "_adapter_schema"): "Internal registry-builder step.",
    ("deixis/domain/contracts.py", "_common_schema"): "Internal registry-builder step.",
    ("deixis/models/gemini.py", "response_schema"): "Gemini-only transform of a registry schema.",
    ("deixis/models/schema_subset.py", "portable_schema"): "Anthropic/OpenRouter subset of a registry schema (D34).",
    ("deixis/models/anthropic_api.py", "anthropic_schema"): "Anthropic subset of a registry schema (D34, D93).",
    ("deixis/models/openai_compat.py", "portable_schema"): "OpenRouter subset of a registry schema (D34).",
}
OLD_REASON = {"anyOf": [
    {"$ref": "#/$defs/short_text", "minLength": 1, "pattern": r"\S"},
    {"type": "null"},
]}
R1_ISSUE = "R1 $.properties.claims.items.properties.reason.anyOf[0]: $ref has sibling keywords"


def obj(properties=None, **extra):
    properties = {} if properties is None else properties
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False, **extra}


def nested(depth, leaf=None):
    node = obj() if leaf is None else leaf
    for _ in range(depth - 1):
        node = obj({"child": node})
    return node


def test_t0_registry_keys_are_independently_frozen():
    expected = {f"{builder}:{task}" for builder in ("model_output_schema", "step_output_schema") for task in TASKS}
    expected.add("report_section_anchor_patch_schema")
    assert len(expected) == 45
    assert contracts.model_transport_schemas().keys() == expected


def test_t1_every_transport_schema_is_valid_and_strict():
    # One test over every step schema (was one case per schema).
    for key in sorted(contracts.model_transport_schemas()):
        schema = contracts.model_transport_schemas()[key]
        issues = contracts.strict_compatibility_issues(schema)
        assert issues == [], f"{key}: {issues}"
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            pytest.fail(f"{key}: {exc}")


def test_t2_frozen_rejected_transport_has_exactly_one_r1_issue():
    schema = copy.deepcopy(contracts.report_section_anchor_patch_schema())
    schema["properties"]["claims"]["items"]["properties"]["reason"] = copy.deepcopy(OLD_REASON)
    schema["$defs"]["short_text"] = {"type": "string", "maxLength": 600}
    Draft202012Validator.check_schema(schema)
    assert contracts.strict_compatibility_issues(schema) == [R1_ISSUE]


def test_t3_schema_call_sites_are_registered_or_explicitly_excluded():
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "deixis").rglob("*.py"))
    files += sorted((root / "scripts/model_behavior").glob("*.py"))
    seen_exclusions = set()
    unknown = []
    for file in files:
        relative = file.relative_to(root).as_posix()
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                and fn.value.id == "contracts" else "")
            if not name.endswith("schema") or name in BUILDERS:
                continue
            key = (relative, name)
            if key in EXCLUSIONS:
                seen_exclusions.add(key)
            else:
                unknown.append(f"{relative}:{node.lineno}: {name}")
    assert unknown == []
    assert seen_exclusions == EXCLUSIONS.keys()
    assert {key.split(":")[0] for key in contracts.model_transport_schemas()} == BUILDERS


def test_t4_each_rule_has_passing_and_failing_cases():
    # One test over every rule (was one case per rule).
    for rule, passing, failing in [
        ("R1", obj({"p": {"$ref": "#/$defs/s"}}, **{"$defs": {"s": {"type": "string"}}}),
         obj({"p": {"$ref": "#/$defs/s", "description": "s"}}, **{"$defs": {"s": {"type": "string"}}})),
        ("R2", obj({"p": obj(type=["object", "null"])}),
         obj({"p": {"type": ["object", "null"], "properties": {}, "required": []}})),
        ("R3", obj({"if": {"type": "string", "enum": ["if", "default"], "const": "default", "pattern": "if"}},
                    description="default", title="if"), obj(default={})),
        ("R4", obj({"p": {"anyOf": [{"type": "string"}, {"type": "null"}]}}), obj(anyOf=[{"type": "string"}])),
        ("R5", obj({"p": {"$ref": "#/$defs/s"}}, **{"$defs": {"s": {"type": "string"}}}),
         obj({"p": {"$ref": "#/$defs/missing"}})),
        ("R6", obj({"p": {"type": "string", "format": "uuid"}}), obj({"p": {"type": "string", "format": "uri"}})),
        ("R7", nested(10), nested(11)),
        ("R8", obj({"p": {"type": "array", "items": {"type": "string"}}}), obj({"p": {"type": "array"}})),
    ]:
        assert contracts.strict_compatibility_issues(passing) == []
        issues = contracts.strict_compatibility_issues(failing)
        assert issues and all(issue.startswith(rule + " ") for issue in issues), rule



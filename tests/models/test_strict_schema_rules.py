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
    "owner_review", "grounded_answer", "answer_review", "cell_extraction",
    "table_columns", "research_title", "vocabulary_labels", "criterion_proposal",
    "term_suggestions", "term_advice", "search_query", "abstract_screening", "fulltext_adjudication",
    "report_plan", "report_section", "report_phrase_repair", "report_review",
    "lineage_links", "claim_decomposition", "kill_search_query", "claim_assessment",
)
BUILDERS = {"model_output_schema", "step_output_schema", "report_section_anchor_patch_schema"}
EXCLUSIONS = {
    ("backend/deixis/domain/contracts.py", "load_schema"): "Canonical files, never sent as is.",
    ("backend/deixis/domain/contracts.py", "_adapter_schema"): "Internal registry-builder step.",
    ("backend/deixis/domain/contracts.py", "_common_schema"): "Internal registry-builder step.",
    ("backend/deixis/models/gemini.py", "response_schema"): "Gemini-only transform of a registry schema.",
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
    assert len(expected) == 43
    assert contracts.model_transport_schemas().keys() == expected


@pytest.mark.parametrize("key", sorted(contracts.model_transport_schemas()))
def test_t1_every_transport_schema_is_valid_and_strict(key):
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
    files = sorted((root / "backend/deixis").rglob("*.py"))
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


@pytest.mark.parametrize("rule,passing,failing", [
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
])
def test_t4_each_rule_has_passing_and_failing_cases(rule, passing, failing):
    assert contracts.strict_compatibility_issues(passing) == []
    issues = contracts.strict_compatibility_issues(failing)
    assert issues and all(issue.startswith(rule + " ") for issue in issues)


@pytest.mark.parametrize("keyword", [
    "oneOf", "allOf", "not", "if", "then", "else", "patternProperties", "unevaluatedProperties",
    "dependentRequired", "dependentSchemas", "prefixItems", "contains", "uniqueItems", "default", "examples", "typo",
])
def test_t4_keyword_allowlist(keyword):
    assert contracts.strict_compatibility_issues(obj(**{keyword: True})) == [f"R3 $: unsupported keyword {keyword}"]


@pytest.mark.parametrize("typ", ["unknown", [], ["string", "string"], ["string", "unknown"], [True], True, 3])
def test_t4_invalid_types(typ):
    assert contracts.strict_compatibility_issues(obj({"p": {"type": typ}})) == ["R3 $.properties.p: invalid type"]


@pytest.mark.parametrize("node", [True, False, {"anyOf": []}, {"anyOf": {}}, {"anyOf": [True]}, {"type": "array", "items": False}])
def test_t4_subschema_shapes(node):
    issues = contracts.strict_compatibility_issues(obj({"p": node}))
    assert issues and all(issue.startswith("R8 ") for issue in issues)


@pytest.mark.parametrize("ref", ["other.json#/$defs/s", "#/$defs/missing", "#/properties/p", "#/$defs/s/bad", "#/$defs/~2"])
def test_t4_reference_policy(ref):
    assert contracts.strict_compatibility_issues(obj({"p": {"$ref": ref}}))[0].startswith("R5 ")


def test_t4_root_rules_do_not_apply_to_branches_or_scalar_properties():
    assert contracts.strict_compatibility_issues(obj({"p": {"anyOf": [{"type": "string"}, obj()]}})) == []
    assert contracts.strict_compatibility_issues(obj({"p": obj(**{"$defs": {}})})) == [
        "R5 $.properties.p: $defs is only allowed at the root"]
    assert contracts.strict_compatibility_issues({"type": "string"}) == [
        "R4 $: root must have type object and no anyOf"]


@pytest.mark.parametrize("limit", ["properties", "depth", "enum_values", "string_length", "large_enum_length"])
@pytest.mark.parametrize("over", [0, 1])
def test_t4_r7_exact_limits_and_one_over(limit, over):
    if limit == "properties":
        schema = obj({f"p{i}": {"type": "null"} for i in range(5000 + over)})
    elif limit == "depth":
        schema = nested(10 + over)
    elif limit == "enum_values":
        schema = obj({"p": {"type": "integer", "enum": list(range(1000 + over))}})
    elif limit == "string_length":
        schema = obj({"p": {"type": "string", "const": "x" * (119_999 + over)}})
    else:
        values = [str(i) for i in range(251)]
        values[-1] += "x" * (15_000 + over - sum(map(len, values)))
        schema = obj({"p": {"type": "string", "enum": values}})
    issues = contracts.strict_compatibility_issues(schema)
    assert len(issues) == over
    assert all(issue.startswith("R7 ") for issue in issues)


@pytest.mark.parametrize("definition_depth", [1, 2])
def test_t4_shared_definition_is_followed_again_on_the_deep_path(definition_depth):
    ref = {"$ref": "#/$defs/shared"}
    schema = obj({"shallow": obj({"ref": ref}), "deep": nested(8, obj({"ref": ref}))},
                 **{"$defs": {"shared": nested(definition_depth)}})
    # Shallow parent depth 2, deep parent depth 9, then definition's own depth.
    issues = contracts.strict_compatibility_issues(schema)
    assert issues == ([] if definition_depth == 1 else ["R7 $: object nesting exceeds 10 levels"])


def test_t4_arrays_add_no_object_level_and_recursive_refs_are_allowed():
    schema = obj({"p": {"type": "array", "items": nested(9)}})
    assert contracts.strict_compatibility_issues(schema) == []
    schema["properties"]["p"]["items"] = nested(10)
    assert contracts.strict_compatibility_issues(schema) == ["R7 $: object nesting exceeds 10 levels"]
    assert contracts.strict_compatibility_issues(obj({"self": {"$ref": "#"}})) == []
    definition = obj({"self": {"$ref": "#/$defs/node"}})
    assert contracts.strict_compatibility_issues(obj({"p": {"$ref": "#/$defs/node"}}, **{"$defs": {"node": definition}})) == []


def test_t4_counts_declarations_once_and_all_counted_string_kinds():
    schema = obj({"a": {"$ref": "#/$defs/n"}, "b": {"$ref": "#/$defs/n"}},
                 **{"$defs": {"n": obj({f"p{i}": {"type": "integer"} for i in range(4998)})}})
    assert contracts.strict_compatibility_issues(schema) == []
    # Names, enum strings, and const strings contribute once; descriptions do not.
    schema = obj({"p": {"type": "string", "enum": ["xx"], "const": "x" * 119_996}},
                 **{"$defs": {"n": {"type": "null", "description": "x" * 120_001}}})
    assert contracts.strict_compatibility_issues(schema) == []
    schema["properties"]["p"]["const"] += "x"
    assert contracts.strict_compatibility_issues(schema) == ["R7 $: total string characters exceeds 120000"]


def test_t4_supported_formats_types_and_escaped_definition_names():
    for format_name in "date-time time date duration email hostname ipv4 ipv6 uuid".split():
        assert contracts.strict_compatibility_issues(obj({"p": {"type": "string", "format": format_name}})) == []
    for typ in "string number integer boolean null".split():
        assert contracts.strict_compatibility_issues(obj({"p": {"type": [typ, "object"],
            "properties": {}, "required": [], "additionalProperties": False}})) == []
    assert contracts.strict_compatibility_issues(obj({"p": {"$ref": "#/$defs/a~1b~0c"}},
        **{"$defs": {"a/b~c": {"type": "string"}}})) == []

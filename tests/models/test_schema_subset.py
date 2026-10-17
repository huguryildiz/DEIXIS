"""Model-free: what `schema_subset` sends instead of a step schema, and how the nulls left out come back (D93).

These pairs show the transforms; whether the API accepts a schema was probed live, not here.
"""

import json

import pytest
from jsonschema import Draft202012Validator

from deixis.domain import contracts
from deixis.models.schema_subset import OMITTED_NULL_NOTE, anthropic_schema, fill_omitted_nulls, portable_schema

NULL = {"type": "null"}


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


@pytest.mark.parametrize("given,expected", [
    ({"description": "d", "type": ["string", "null"], "enum": ["TABLE_I", None]},
     {"description": "d", "anyOf": [{"type": "string", "enum": ["TABLE_I"]}, NULL]}),
    ({"type": ["string", "integer"], "enum": ["a", 1]},
     {"anyOf": [{"type": "string", "enum": ["a"]}, {"type": "integer", "enum": [1]}]}),
    # A type with no member left in the enum gives no branch; one branch left is no anyOf.
    ({"type": ["string", "null"], "enum": ["a"]}, {"type": "string", "enum": ["a"]}),
    ({"type": "string", "enum": ["a", "b"]}, {"type": "string", "enum": ["a", "b"]}),
    ({"type": ["string", "null"], "maxLength": 5}, {"type": ["string", "null"]}),
])
def test_portable_schema_splits_a_type_list_with_an_enum(given, expected):
    assert portable_schema(given) == expected


def test_anthropic_schema_sends_a_required_nullable_field_optional_and_non_null():
    given = {"$defs": {"pid": {"type": "string", "pattern": "^psg_[0-9]+$"}}, **obj({
        "keep": {"type": "string"},
        "s": {"description": "d", "anyOf": [{"type": "string", "pattern": "^AX[0-9]$"}, NULL]},
        "ref": {"anyOf": [{"$ref": "#/$defs/pid"}, NULL]},
        "lst": {"type": ["integer", "null"], "minimum": 1},
        "en": {"type": ["string", "null"], "enum": ["T", None]},
        "o": {"anyOf": [obj({"inner": {"anyOf": [{"type": "string"}, NULL]}}), NULL]},
        "arr": {"type": "array", "items": obj({"x": {"anyOf": [{"type": "string"}, NULL]}, "y": {"type": "string"}})},
    })}
    sent = anthropic_schema(given)
    assert sent["required"] == ["keep", "arr"]
    props = sent["properties"]
    note = OMITTED_NULL_NOTE
    assert props["s"] == {"description": f"d {note} Must match the regular expression ^AX[0-9]$", "type": "string"}
    assert props["ref"] == {"type": "string", "description": f"{note} Must match the regular expression ^psg_[0-9]+$"}
    assert props["lst"] == {"type": "integer", "description": note}
    assert props["en"] == {"type": "string", "enum": ["T"], "description": note}
    assert props["o"] == {**obj({"inner": {"type": "string", "description": note}}, required=[]), "description": note}
    assert props["arr"]["items"] == obj({"x": {"type": "string", "description": note}, "y": {"type": "string"}}, required=["y"])
    assert props["keep"] == {"type": "string"}
    assert sent["$defs"]["pid"] == {"type": "string", "description": "Must match the regular expression ^psg_[0-9]+$"}
    assert "pattern" not in json.dumps(sent)


def test_a_property_named_like_a_keyword_is_kept():
    given = obj({"pattern": {"anyOf": [{"type": "string"}, NULL]}, "anyOf": {"type": "string", "pattern": "x"}})
    sent = anthropic_schema(given)
    assert sent["properties"] == {"pattern": {"type": "string", "description": OMITTED_NULL_NOTE},
                                  "anyOf": {"type": "string", "description": "Must match the regular expression x"}}
    assert sent["required"] == ["anyOf"]


def test_the_decomposition_schema_says_to_leave_out_a_null_explanation():
    """17 Oct live check: told "use null" with no null in the sent schema, the model wrote "" or "null" in 7 of 8
    decomposition calls (D94). Each field the transform makes optional says how to give null."""
    sent = anthropic_schema(contracts.model_output_schema("claim_decomposition"))
    field = sent["properties"]["nearest_simple_explanation"]
    assert "nearest_simple_explanation" not in sent["required"]
    assert OMITTED_NULL_NOTE in field["description"]
    assert "never write an empty string or the word null" in OMITTED_NULL_NOTE


def test_fill_omitted_nulls_puts_back_each_missing_nullable_field_and_says_where():
    schema = {"$defs": {"near": obj({"id": {"anyOf": [{"type": "string"}, NULL]}, "status": {"type": "string"}})}, **obj({
        "items": {"type": "array", "items": obj({
            "a": {"anyOf": [{"type": "string"}, NULL]}, "b": {"type": ["integer", "null"]},
            "n": {"$ref": "#/$defs/near"}, "c": {"type": "string"}})},
        "o": {"anyOf": [obj({"x": {"anyOf": [{"type": "string"}, NULL]}}), NULL]},
    })}
    draft = {"items": [{"a": "kept", "n": {"status": "found"}}, {"b": 2, "n": {"id": "i", "status": "s"}}], "o": {}}
    filled, changes = fill_omitted_nulls(schema, json.dumps(draft))
    assert filled == {"items": [{"a": "kept", "b": None, "n": {"status": "found", "id": None}},
                                {"b": 2, "a": None, "n": {"id": "i", "status": "s"}}], "o": {"x": None}}
    assert sorted(c["path"] for c in changes) == ["/items/0/b", "/items/0/n/id", "/items/1/a", "/o/x"]
    # A missing non-nullable field (`c`) is left for validation; so is a missing top-level nullable object.
    assert all(not c["path"].endswith("/c") for c in changes)
    filled, changes = fill_omitted_nulls(schema, {"items": []})
    assert (filled, [c["path"] for c in changes]) == ({"items": [], "o": None}, ["/o"])


@pytest.mark.parametrize("text", ["not json", "[1, 2]", ""])
def test_fill_omitted_nulls_leaves_text_that_is_not_a_json_object(text):
    assert fill_omitted_nulls(obj({"a": {"anyOf": [{"type": "string"}, NULL]}}), text) == (text, [])


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in ("properties", "$defs") and isinstance(value, dict):
                for child in value.values():
                    yield from _nodes(child)
            elif key not in ("enum", "const", "required", "default"):
                yield from _nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _nodes(value)


def _required_nullable(schema):
    for node in _nodes(portable_schema(schema)):
        if isinstance(node.get("properties"), dict):
            for name in node.get("required", []):
                child = node["properties"][name]
                if isinstance(child, dict) and ((isinstance(child.get("type"), list) and "null" in child["type"])
                                                or NULL in child.get("anyOf", [])):
                    yield name, child


def _named(schema, name):
    return [n["properties"][name] for n in _nodes(schema) if isinstance(n.get("properties"), dict) and name in n["properties"]]


@pytest.mark.parametrize("key", sorted(contracts.model_transport_schemas()))
def test_every_step_schema_passes_through_without_a_typed_enum_or_a_required_nullable_field(key):
    schema = contracts.model_transport_schemas()[key]
    portable = portable_schema(schema)
    assert [n for n in _nodes(portable) if isinstance(n.get("type"), list) and "enum" in n] == []
    Draft202012Validator.check_schema(portable)
    sent = anthropic_schema(schema)
    Draft202012Validator.check_schema(sent)
    for node in _nodes(sent):
        assert not (isinstance(node.get("type"), list) and "enum" in node), key
        assert "pattern" not in node, key
        if isinstance(node.get("properties"), dict):
            for name in node.get("required", []):
                child = node["properties"][name]
                assert not (isinstance(child.get("type"), list) and "null" in child["type"]), (key, name)
                assert NULL not in child.get("anyOf", []), (key, name)
    for name, original in _required_nullable(schema):
        assert any(OMITTED_NULL_NOTE in n.get("description", "") for n in _named(sent, name)), (key, name)
    # Anthropic's documented limit is 24 optional fields across one request's strict schemas.
    optional = sum(len(set(n["properties"]) - set(n.get("required", []))) for n in _nodes(sent)
                   if isinstance(n.get("properties"), dict))
    assert optional <= 24, (key, optional)


@pytest.mark.parametrize("key", sorted(contracts.model_transport_schemas()))
def test_an_output_valid_for_the_sent_schema_is_valid_for_the_step_schema_once_filled(key):
    """A minimal object of the sent schema (every optional field left out) fills back into a fully valid output.

    Patterns, lengths and minimums are taken off both sides, as the minimal values do not meet them; every other error,
    `anyOf` included, fails the test."""
    schema = _no_bounds(contracts.model_transport_schemas()[key])
    sent = anthropic_schema(schema)
    filled, _ = fill_omitted_nulls(schema, minimal(sent, sent))
    assert Draft202012Validator(sent).is_valid(minimal(sent, sent)), key
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(filled)]
    assert errors == [], (key, errors)


def minimal(root, node, branch=0):
    node = _resolve(root, node)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return node["enum"][0]
    if "anyOf" in node:
        return minimal(root, node["anyOf"][min(branch, len(node["anyOf"]) - 1)])
    kind = node.get("type")
    if kind == "object":
        return {name: minimal(root, node["properties"][name], branch) for name in node.get("required", [])}
    if kind == "array":
        return [minimal(root, node["items"], branch)] if node.get("minItems") else []
    return {"string": "x", "integer": 1, "number": 1, "boolean": True}.get(kind)


CELL_VALUES = [
    {"text": "SYNTHETIC answer text"}, {"answer": "yes"}, {"option_ids": ["o1", "o2"]},
    {"number": 4.5}, {"number": 4.5, "unit": "J"}, {"number": 4.5, "unit": "J", "as_stated": "4.5 J"},
    {"number": 4.5, "as_stated": "about 4.5"},
]


@pytest.mark.parametrize("value", CELL_VALUES + [None, "omitted"])
def test_every_cell_value_shape_fills_into_a_valid_cell_extraction(value):
    schema = contracts.model_output_schema("cell_extraction")
    cell = {"column_id": "col_SYNTHETIC1", "state": "value",
            "evidence": [{"passage_id": "psg_SYNTHETIC1", "quote": "SYNTHETIC quoted passage text"}]}
    if value != "omitted":
        cell["value"] = value
    draft = {"schema_version": "deixis.evidence_cell_draft.v1", "step_input_id": "sti_SYNTHETIC1", "scope_revision": 1,
             "cells": [cell]}
    assert Draft202012Validator(anthropic_schema(schema)).is_valid(draft) == (value is not None)
    filled, changes = fill_omitted_nulls(schema, json.dumps(draft))
    assert list(Draft202012Validator(schema).iter_errors(filled)) == []
    expected = None if value in (None, "omitted") else {"unit": None, "as_stated": None, **value} if "number" in value else value
    assert filled["cells"][0]["value"] == expected and filled["cells"][0]["note"] is None
    assert "/cells/0/note" in [c["path"] for c in changes]


def test_an_anyof_value_is_filled_only_when_exactly_one_completion_is_valid():
    number = obj({"n": {"type": "number"}, "u": {"type": ["string", "null"]}})
    other = obj({"n": {"type": "number"}, "v": {"type": ["string", "null"]}})
    text = obj({"t": {"type": "string"}})
    # One branch can be completed: it is.
    schema = obj({"x": {"anyOf": [number, text]}})
    assert fill_omitted_nulls(schema, {"x": {"n": 1}}) == ({"x": {"n": 1, "u": None}}, [{"path": "/x/u", "filled": "null"}])
    # A value valid as it is for one branch gains nothing from another.
    assert fill_omitted_nulls(schema, {"x": {"t": "a"}}) == ({"x": {"t": "a"}}, [])
    # Two branches can be completed, differently: nothing is chosen.
    schema = obj({"x": {"anyOf": [number, other]}})
    assert fill_omitted_nulls(schema, {"x": {"n": 1}}) == ({"x": {"n": 1}}, [])
    # No branch can be completed (an unknown key): nothing is added.
    assert fill_omitted_nulls(schema, {"x": {"n": 1, "w": 2}}) == ({"x": {"n": 1, "w": 2}}, [])


def test_root_and_escaped_references_are_followed_and_a_loop_stops():
    schema = {"$defs": {"a/b": obj({"x": {"type": ["string", "null"]}}), "loop": {"$ref": "#/$defs/loop"}},
              **obj({"esc": {"$ref": "#/$defs/a~1b"}, "self": {"anyOf": [{"$ref": "#"}, NULL]},
                     "stuck": {"$ref": "#/$defs/loop"}}, required=["esc", "self", "stuck"])}
    draft = {"esc": {}, "self": {"esc": {}, "stuck": 1}, "stuck": 1}
    filled, changes = fill_omitted_nulls(schema, draft)
    assert filled["esc"] == {"x": None}
    assert sorted(c["path"] for c in changes)[:1] == ["/esc/x"]
    sent = anthropic_schema(schema)  # the loop is left as a reference, not followed forever
    assert sent["$defs"]["loop"] == {"$ref": "#/$defs/loop"}


@pytest.mark.parametrize("text", ['{"a": 1' + "0" * 5000 + "}", '{"a": ' + "[" * 200000 + "]" * 200000 + "}"])
def test_text_past_the_decoder_limits_is_left_unchanged(text):
    assert fill_omitted_nulls(obj({"a": {}, "b": {"type": ["string", "null"]}}), text) == (text, [])


def test_array_bounds_go_into_the_description_for_anthropic():
    schema = obj({"cols": {"type": "array", "description": "Columns.", "minItems": 2, "maxItems": 8,
                           "items": {"type": "string"}},
                  "one": {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "string"}}})
    sent = anthropic_schema(schema)["properties"]
    assert sent["cols"] == {"type": "array", "description": "Columns. At least 2 items. At most 8 items.", "minItems": 1,
                            "items": {"type": "string"}}
    assert sent["one"] == {"type": "array", "description": "At most 1 items.", "minItems": 1, "items": {"type": "string"}}
    table = anthropic_schema(contracts.model_output_schema("table_columns"))
    assert "At most 8 items." in json.dumps(table)
    assert "maxItems" not in json.dumps(table)


def _resolve(root, node):
    while "$ref" in node:
        node = {**{k: v for k, v in node.items() if k != "$ref"}, **root["$defs"][node["$ref"].split("/")[-1]]}
    return node


def _no_bounds(node):
    if isinstance(node, list):
        return [_no_bounds(v) for v in node]
    if not isinstance(node, dict):
        return node
    return {k: _no_bounds(v) for k, v in node.items() if k not in ("pattern", "minLength", "minimum", "minItems")}

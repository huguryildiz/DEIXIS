"""Model-free: what `schema_subset` sends instead of a step schema, and how the nulls left out come back (D93).

These pairs show the transforms; whether the API accepts a schema was probed live, not here.
"""

import json

from jsonschema import Draft202012Validator

from deixis.domain import contracts
from deixis.models.schema_subset import OMITTED_NULL_NOTE, anthropic_schema, fill_omitted_nulls, portable_schema

NULL = {"type": "null"}


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


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


def test_every_step_schema_passes_through_without_a_typed_enum_or_a_required_nullable_field():
    # One test over every step schema (was one case per schema).
    for key in sorted(contracts.model_transport_schemas()):
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


def test_an_output_valid_for_the_sent_schema_is_valid_for_the_step_schema_once_filled():
    """A minimal object of the sent schema (every optional field left out) fills back into a fully valid output.

    Patterns, lengths and minimums are taken off both sides, as the minimal values do not meet them; every other error,
    `anyOf` included, fails the test."""
    # One test over every step schema (was one case per schema).
    for key in sorted(contracts.model_transport_schemas()):
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

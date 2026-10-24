"""The step schema in the subset that Anthropic's structured outputs and OpenRouter's providers accept.

Anthropic's structured outputs reject numeric bounds, string lengths, `maxItems` and a `minItems` above 1 (documented
on platform.claude.com, 2026-10-15). They are removed or lowered here; DEIXIS validation still applies the full
schema to the output, so a value that breaks a removed bound goes through the bounded repair path as before.

A type list with an enum (`{"type": ["string", "null"], "enum": ["TABLE_I", null]}`) is rejected by Anthropic ("Enum
value 'TABLE_I' does not match declared type"); it is split into one enum branch per type under `anyOf` (D93).

Anthropic also refuses a schema whose compiled grammar is too large, and every required field that may be null (an
`anyOf` with a null branch or a type list with "null") adds to that size far more than an optional field does
(probed live 2026-10-17, D93), and so does every `pattern`. `anthropic_schema` therefore sends such a field as optional
and non-null, with a sentence in its description that says to leave it out for null (a written "" or "null" failed 7
of 8 live decomposition calls, D94), and each pattern and array bound as a sentence in the field's description; the model leaves a null field out, and
`fill_omitted_nulls` puts the null back before validation, so the validated output has the step schema's shape. What
the API no longer enforces while the model writes (a pattern, a written null) DEIXIS validation still checks.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator

UNSUPPORTED_KEYS = frozenset({"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                              "multipleOf", "maxItems"})
# Keyword data, not schemas: property names under these may be any word, including a removed keyword.
_NAMED_SCHEMAS = ("properties", "$defs")
_DATA = ("enum", "const", "required", "default")
_NULL = {"type": "null"}


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return {str: "string", list: "array", dict: "object"}.get(type(value), "string")


def _split_typed_enum(node: dict[str, Any]) -> dict[str, Any]:
    """`{"type": [a, b], "enum": [...]}` as `anyOf` of one single-type enum branch per type."""
    types, values = node["type"], node["enum"]
    branches = []
    for t in types:
        members = [v for v in values if _json_type(v) == t or (t == "number" and _json_type(v) == "integer")]
        if t == "null":
            if None in values:
                branches.append(dict(_NULL))
        elif members:
            branches.append({"type": t, "enum": members})
    rest = {k: v for k, v in node.items() if k not in ("type", "enum")}
    if len(branches) == 1:
        return {**rest, **branches[0]}
    return {**rest, "anyOf": branches}


def portable_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [portable_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    if isinstance(node.get("type"), list) and isinstance(node.get("enum"), list):
        node = _split_typed_enum(node)
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in UNSUPPORTED_KEYS:
            continue
        if key in _NAMED_SCHEMAS and isinstance(value, dict):
            out[key] = {name: portable_schema(child) for name, child in value.items()}
        elif key == "minItems" and isinstance(value, int) and value > 1:
            out[key] = 1
        elif key in _DATA:
            out[key] = value
        else:
            out[key] = portable_schema(value)
    return out


def _pointer(root: Any, ref: str) -> Any:
    """The target of a local reference (`#` or `#/a/b`, with `~1` and `~0` decoded), or None."""
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return None
    target = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and token in target:
            target = target[token]
        elif isinstance(target, list) and token.isdigit() and int(token) < len(target):
            target = target[int(token)]
        else:
            return None
    return target


def _resolve(root: dict[str, Any], node: Any) -> Any:
    """`node` with its local `$ref` chain merged in; a reference that cannot be found or loops is left as it is."""
    seen: set[str] = set()
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        target = _pointer(root, ref)
        if ref in seen or not isinstance(target, dict):
            return node
        seen.add(ref)
        node = {**{k: v for k, v in node.items() if k != "$ref"}, **target}
    return node


def _nullable(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    if isinstance(node.get("type"), list):
        return "null" in node["type"]
    return isinstance(node.get("anyOf"), list) and _NULL in node["anyOf"]


def _without_null(root: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if isinstance(node.get("type"), list):
        types = [t for t in node["type"] if t != "null"]
        return {**node, "type": types[0] if len(types) == 1 else types}
    rest = {k: v for k, v in node.items() if k != "anyOf"}
    branches = [b for b in node["anyOf"] if b != _NULL]
    if len(branches) != 1:
        return {**rest, "anyOf": branches}
    # The one remaining branch is merged with the field's own keywords; a $ref is inlined so no keyword sits beside it,
    # unless its target holds a reference itself (a recursive schema), which is sent as the bare reference instead.
    branch = branches[0]
    if isinstance(branch, dict) and "$ref" in branch:
        target = _resolve(root, branch)
        if "$ref" in target or '"$ref"' in json.dumps(target):
            return branch
        return {**rest, **target}
    return {**rest, **branch}


OMITTED_NULL_NOTE = "To give null, leave this field out; never write an empty string or the word null as its value."


def _omit_nullable(root: dict[str, Any], node: Any) -> Any:
    if isinstance(node, list):
        return [_omit_nullable(root, v) for v in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _NAMED_SCHEMAS and isinstance(value, dict):
            out[key] = {name: _omit_nullable(root, child) for name, child in value.items()}
        elif key in _DATA:
            out[key] = value
        else:
            out[key] = _omit_nullable(root, value)
    props, required = out.get("properties"), out.get("required")
    if isinstance(props, dict) and isinstance(required, list):
        nullable = [name for name in required if _nullable(props.get(name))]
        for name in nullable:
            sent = _omit_nullable(root, _without_null(root, props[name]))
            # The method text says "use null"; with null no longer in the schema the model needs to be told how (D94).
            props[name] = sent if "$ref" in sent else _describe(sent, OMITTED_NULL_NOTE)
        out["required"] = [name for name in required if name not in nullable]
    return out


# The version of what `anthropic_schema` sends; stored with each answer next to the sent schema's digest (D93).
ANTHROPIC_TRANSFORM_VERSION = "anthropic_schema.v3"


def _map_nodes(node: Any, change: Any) -> Any:
    """`change` applied to every schema object, children first; property names and keyword data are left alone."""
    if isinstance(node, list):
        return [_map_nodes(v, change) for v in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _NAMED_SCHEMAS and isinstance(value, dict):
            out[key] = {name: _map_nodes(child, change) for name, child in value.items()}
        elif key in _DATA or key == "description":
            out[key] = value
        else:
            out[key] = _map_nodes(value, change)
    return change(out)


def _describe(node: dict[str, Any], note: str) -> dict[str, Any]:
    return {**node, "description": f"{node['description']} {note}" if isinstance(node.get("description"), str) else note}


def _pattern_to_description(node: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(node.get("pattern"), str):
        return node
    rest = {k: v for k, v in node.items() if k != "pattern"}
    return _describe(rest, f"Must match the regular expression {node['pattern']}")


def _item_bounds_to_description(node: dict[str, Any]) -> dict[str, Any]:
    """Array bounds the API cannot take (`maxItems`, `minItems` above 1) as a sentence; portable_schema then drops them."""
    notes = []
    if isinstance(node.get("minItems"), int) and not isinstance(node["minItems"], bool) and node["minItems"] > 1:
        notes.append(f"At least {node['minItems']} items.")
    if isinstance(node.get("maxItems"), int) and not isinstance(node["maxItems"], bool):
        notes.append(f"At most {node['maxItems']} items.")
    return _describe(node, " ".join(notes)) if notes else node


def anthropic_schema(schema: Any) -> Any:
    """The schema sent to Anthropic: the portable subset, with each required nullable field optional and non-null, and
    each `pattern`, `maxItems` and `minItems` above 1 moved into the field's description."""
    portable = portable_schema(_map_nodes(schema, _item_bounds_to_description))
    if not isinstance(portable, dict):
        return portable
    return _map_nodes(_omit_nullable(portable, portable), _pattern_to_description)


def schema_digest(schema: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(schema, sort_keys=True, ensure_ascii=True,
                                                 separators=(",", ":")).encode()).hexdigest()


def fill_omitted_nulls(schema: dict[str, Any], draft: Any) -> tuple[Any, list[dict[str, str]]]:
    """Put back null for each required nullable field the output left out, and say where.

    `schema` is the full step schema (the one stored with the StepInput). Only a missing key whose schema allows null is
    filled; a present value, a missing non-nullable field or text that is not a JSON object is left for validation.
    Under `anyOf` each branch is tried on its own copy of the value, and the copy is kept only when it is valid for that
    full branch and every valid branch gives the same result; otherwise the value is left as it came. Text the decoder
    cannot read (bad JSON, an integer past Python's digit limit, nesting past the recursion limit) is returned unchanged.
    """
    if isinstance(draft, str):
        try:
            parsed = json.loads(draft)
        except (ValueError, RecursionError):  # JSONDecodeError is a ValueError
            return draft, []
        if not isinstance(parsed, dict):
            return draft, []
        work = parsed
    else:
        work = copy.deepcopy(draft)
    if not isinstance(work, dict):
        return draft, []
    try:
        validator = Draft202012Validator(schema)
        changes = _fill(schema, validator, schema, work, "")
    except RecursionError:
        return draft, []
    return work, changes


def _valid(validator: Any, branch: Any, value: Any) -> bool:
    try:
        return validator.evolve(schema=branch).is_valid(value)
    except RecursionError:  # a reference loop the validator follows forever: not a branch to fill
        return False


def _fill(root: dict[str, Any], validator: Any, node: Any, value: Any, path: str) -> list[dict[str, str]]:
    """Fill `value` in place for `node`; return the filled paths."""
    node = _resolve(root, node)
    if not isinstance(node, dict):
        return []
    changes: list[dict[str, str]] = []
    if isinstance(node.get("anyOf"), list) and isinstance(value, (dict, list)):
        results = []
        for branch in node["anyOf"]:
            candidate = copy.deepcopy(value)
            filled = _fill(root, validator, branch, candidate, path)
            if _valid(validator, branch, candidate):
                results.append((candidate, filled))
        distinct = {json.dumps(c, sort_keys=True) for c, _ in results}
        if len(distinct) == 1 and results[0][1]:
            candidate, filled = results[0]
            if isinstance(value, dict):
                value.clear()
                value.update(candidate)
            else:
                value[:] = candidate
            changes.extend(filled)
    if isinstance(value, dict) and isinstance(node.get("properties"), dict):
        props = node["properties"]
        for name in node.get("required", []):
            if name not in value and _nullable(_resolve(root, props.get(name))):
                value[name] = None
                changes.append({"path": f"{path}/{name}", "filled": "null"})
        for name, child in props.items():
            if name in value:
                changes.extend(_fill(root, validator, child, value[name], f"{path}/{name}"))
    if isinstance(value, list) and isinstance(node.get("items"), (dict, bool)):
        for index, item in enumerate(value):
            changes.extend(_fill(root, validator, node["items"], item, f"{path}/{index}"))
    return changes

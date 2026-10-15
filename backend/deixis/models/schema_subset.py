"""The step schema in the subset that Anthropic's structured outputs and OpenRouter's providers accept.

Anthropic's structured outputs reject numeric bounds, string lengths, `maxItems` and a `minItems` above 1 (documented
on platform.claude.com, 2026-10-15). They are removed or lowered here; DEIXIS validation still applies the full
schema to the output, so a value that breaks a removed bound goes through the bounded repair path as before.
"""

from __future__ import annotations

from typing import Any

UNSUPPORTED_KEYS = frozenset({"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                              "multipleOf", "maxItems"})
# Keyword data, not schemas: property names under these may be any word, including a removed keyword.
_NAMED_SCHEMAS = ("properties", "$defs")
_DATA = ("enum", "const", "required", "default")


def portable_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [portable_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
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

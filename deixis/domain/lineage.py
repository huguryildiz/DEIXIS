"""Shared deterministic bounds for development-link explanations."""

MAX_WHAT_CHANGED = 500


def valid_what_changed(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and 1 <= len(value) <= MAX_WHAT_CHANGED

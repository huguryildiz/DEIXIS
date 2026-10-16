"""What is known about a saved API key in this process: 'verified' (a request with it was accepted), 'pending' (saved but
no request showed that it works) or 'rejected' (the service refused it). The state belongs to the key's value, so a new
key starts unknown; it is kept in memory only, so a restart asks again. A key is accepted only as printable ASCII
without spaces, which no HTTP header or process environment can mangle."""

from __future__ import annotations

import hashlib
import re

_VALID_KEY = re.compile(r"[\x21-\x7e]+")
_state: dict[str, tuple[str, str]] = {}  # env -> (state, fingerprint of the value)


def is_valid_key(value: str) -> bool:
    return _VALID_KEY.fullmatch(value) is not None


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def set_state(env: str, value: str, state: str) -> None:
    _state[env] = (state, _fingerprint(value))


def state_of(env: str, value: str | None) -> str | None:
    known = _state.get(env)
    return known[0] if known and value and known[1] == _fingerprint(value) else None


def clear(env: str) -> None:
    _state.pop(env, None)

"""What is known about a saved API key in this process: 'verified' (a request with it was accepted), 'pending' (saved but
no request showed that it works) or 'rejected' (the service refused it). The state belongs to the key's value, not to a
variable or a connection: connections that share one key (Meta's two) see one refusal, and a new key starts unknown. It is
kept in memory only, so a restart asks again. A key is accepted only as printable ASCII
without spaces, which no HTTP header or process environment can mangle."""

from __future__ import annotations

import hashlib
import re

_VALID_KEY = re.compile(r"[\x21-\x7e]+")
_state: dict[str, str] = {}  # fingerprint of the value -> state; the value itself is never kept


def is_valid_key(value: str) -> bool:
    return _VALID_KEY.fullmatch(value) is not None


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def set_state(value: str, state: str) -> None:
    """A request with this key was answered (or a test was): the answer is the state."""
    _state[fingerprint(value)] = state


def settle(value: str, state: str) -> str:
    """The state a model-list answer may give: it never lifts a refusal (a step's 401 can land while the list request is in
    flight). There is no `await` between reading and writing, so this check is not interleaved with another task's."""
    if _state.get(fingerprint(value)) == "rejected":
        return "rejected"
    _state[fingerprint(value)] = state
    return state


def state_of(value: str | None) -> str | None:
    return _state.get(fingerprint(value)) if value else None

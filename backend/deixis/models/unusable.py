"""Models a connection lists but that failed a real research step, kept out of the model lists (D59).

A provider can list a model it no longer serves (Gemini answered 404 "no longer available to new users" for
gemini-2.5-flash on 16 Oct 2026) or answer a listed model with another one (gemini-3.5-flash answered as
gemini-3.6-flash). Neither shows in the list, and probing every model would spend calls, so the first real step that
meets one records it here; the model lists stop offering it from then on. A research that already chose the model
keeps it and fails as before: nothing is switched silently.

Only a provider's own API learns this way. A CLI can fall back to another model for a day when a quota runs out
(Gemini CLI, Claude Code), OpenRouter answers 404 for an account's data policy, and a local server answers 404 for a
model it has not loaded: none of those says the model is gone. A record also lapses after KEEP_DAYS, so a model the
provider serves again comes back.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.db import now

KEY = "unusable_models"
NOT_SERVED = "not_served"  # the provider answered 404 for the model
ANSWERED_AS = "answered_as"  # the provider answered with another model
LEARNS = frozenset({"gemini", "anthropic", "openai", "deepseek", "qwen", "kimi", "mistral", "grok", "glm", "muse_spark",
                    "muse_glimmer", "mimo"})
KEEP_DAYS = 30


def record(store: Any, connection: str, model: str, reason: str, answered_as: str | None = None) -> None:
    if connection not in LEARNS:
        return
    hidden = store.setting(KEY) or {}
    entry = {"reason": reason, "at": now()}
    if answered_as:
        entry["answered_as"] = answered_as
    hidden.setdefault(connection, {})[model] = entry
    store.set_setting(KEY, hidden)


def hidden(store: Any, connection: str) -> dict[str, dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(timespec="milliseconds")
    return {model: entry for model, entry in (store.setting(KEY) or {}).get(connection, {}).items()
            if (entry.get("at") or "") >= since}


def usable(store: Any, connection: str, models: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """`models` without the ones recorded for `connection`; None stays None (a connection without a list)."""
    if models is None:
        return None
    gone = hidden(store, connection)
    return [m for m in models if m["id"] not in gone]


def health_view(store: Any, connection: str, status: dict[str, Any]) -> dict[str, Any]:
    """A connection's health as Settings shows it: the hidden models moved out of `models` into `hidden_models`."""
    gone = hidden(store, connection)
    if not gone or not status.get("models"):
        return status
    return {**status, "models": usable(store, connection, status["models"]),
            "hidden_models": [{"id": model, **entry} for model, entry in sorted(gone.items())]}

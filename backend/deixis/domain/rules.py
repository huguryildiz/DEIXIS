"""Deterministic workflow rules shared by the worker and API.

Test defaults here are P1 configuration, not measured product defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_SCHEMA_REPAIRS = 1
MAX_ACTIVE_MODEL_CALLS = 1
MAX_TRANSIENT_NETWORK_RETRIES = 2


@dataclass(frozen=True)
class EffortBudget:
    max_model_calls: int
    max_provider_requests: int
    max_candidates: int
    max_answer_passages: int


# Effort presets bound work; they are not paper-count or accuracy guarantees.
TEST_EFFORT_BUDGETS = {
    "quick": EffortBudget(max_model_calls=4, max_provider_requests=2, max_candidates=15, max_answer_passages=8),
    "standard": EffortBudget(max_model_calls=6, max_provider_requests=4, max_candidates=30, max_answer_passages=14),
    "detailed": EffortBudget(max_model_calls=8, max_provider_requests=6, max_candidates=50, max_answer_passages=20),
}


class RevisionConflict(Exception):
    """A write was based on an older record version than the stored one."""


def check_expected_version(expected: int, actual: int) -> None:
    if expected != actual:
        raise RevisionConflict(f"expected version {expected}, stored version {actual}")


def result_applicability(step_scope_revision: int, current_scope_revision: int,
                         step_selection_revision: int | None = None, current_selection_revision: int | None = None) -> str:
    """A result produced under an older question or source selection is kept but not applied as current.

    A missing step selection revision (records from before selection tracking) compares on the question only.
    """
    if step_scope_revision != current_scope_revision:
        return "stale_scope"
    if step_selection_revision is not None and step_selection_revision != current_selection_revision:
        return "stale_selection"
    return "current"


def after_invalid_output(repairs_used: int) -> str:
    return "repair" if repairs_used < MAX_SCHEMA_REPAIRS else "store_unverified_draft"


def effective_selection(
    model_proposals: dict[str, str], user_choices: dict[str, str]
) -> dict[str, dict[str, str]]:
    """User choices always win; a model proposal only fills undecided candidates."""
    result: dict[str, dict[str, str]] = {}
    for cid in sorted(set(model_proposals) | set(user_choices)):
        if cid in user_choices:
            result[cid] = {"state": user_choices[cid], "origin": "user"}
        else:
            proposal = model_proposals[cid]
            state = {"include": "included", "exclude": "excluded"}.get(proposal, "pending")
            result[cid] = {"state": state, "origin": "model_proposal"}
    return result

"""Deterministic workflow rules shared by the worker and API.

Test defaults here are P1 configuration, not measured product defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_SCHEMA_REPAIRS = 1
MAX_RATE_LIMIT_MODEL_RETRIES = 2  # extra resends after a rate-limited response, before the call halts as today
MAX_ACTIVE_MODEL_CALLS = 1
MAX_TRANSIENT_NETWORK_RETRIES = 2


@dataclass(frozen=True)
class EffortBudget:
    max_model_calls: int
    max_provider_requests: int
    max_candidates: int
    max_answer_passages: int
    results_per_query: int
    core_depth: int = 0


# Screening proposals are requested for at most this many candidates per model call.
SCREENING_BATCH = 40

# Effort presets bound work; they are not paper-count or accuracy guarantees. Model calls cover the search plan, one
# screening call per SCREENING_BATCH candidates and the answer, each with its one schema repair. Provider requests are
# the plan's query limit; with several providers enabled, one query per relevant provider needs room. `core_depth` is
# how many results OpenAlex's core-only query reads (0: no such query); standard's 250 candidates and 15 model calls were
# chosen for it in docs/product/search-recall-depth-2026-09-17.md, detailed keeps more room than standard.
TEST_EFFORT_BUDGETS = {
    "quick": EffortBudget(max_model_calls=6, max_provider_requests=3, max_candidates=20, max_answer_passages=16, results_per_query=10),
    "standard": EffortBudget(max_model_calls=15, max_provider_requests=8, max_candidates=250, max_answer_passages=48, results_per_query=25,
                             core_depth=100),
    "detailed": EffortBudget(max_model_calls=20, max_provider_requests=12, max_candidates=300, max_answer_passages=80, results_per_query=25,
                             core_depth=100),
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


LITERATURE_TASKS = ("search_plan", "screening", "vocabulary_labels")
# A repair would let the step name a phrase the question does not hold and then take it back. The block labelling
# gets one attempt: an output that invents, drops or repeats a phrase is rejected and the rule stands (SW17.1).
NO_REPAIR_TASKS = ("vocabulary_labels",)


def step_model(scope: dict[str, Any], task_type: str) -> tuple[str, str | None, str | None]:
    """(connection, model, reasoning effort) for a research's search and answer steps.

    A research without a literature model (created before D14) runs its search steps on the research model. A literature
    model without its own connection (created before D28) is on the research model's connection.
    """
    if task_type in LITERATURE_TASKS and scope.get("literature_model"):
        return (scope.get("literature_connection") or scope["model_connection"], scope["literature_model"],
                scope.get("literature_reasoning_effort"))
    return scope["model_connection"], scope["requested_model"], scope.get("reasoning_effort")


def effective_reviewer(scope: dict[str, Any], default: dict[str, Any] | None) -> tuple[str, str, str | None] | None:
    """(connection, model, reasoning effort) that reviews this research's answers, or None when nothing reviews them.

    A research's own reviewer setting wins; 'default' follows the app-wide setting as it is when the review starts.
    """
    mode = scope.get("review_mode") or "default"
    if mode == "off":
        return None
    if mode == "custom":
        return scope.get("review_connection") or scope["model_connection"], scope["review_model"], scope.get("review_reasoning_effort")
    if default and default.get("model"):
        return default["model_connection"], default["model"], default.get("reasoning_effort")
    return None


def schema_repairs(task_type: str) -> int:
    return 0 if task_type in NO_REPAIR_TASKS else MAX_SCHEMA_REPAIRS


def after_invalid_output(repairs_used: int, limit: int = MAX_SCHEMA_REPAIRS) -> str:
    return "repair" if repairs_used < limit else "store_unverified_draft"


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

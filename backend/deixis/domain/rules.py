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


# How many records one sw query reads across its pages. Hand-picked: above the 1,369-record first round SW7 ranked,
# below the vocabulary step's MANAGEABLE_TOTAL. It never drops a record that was read; what it leaves unread is counted.
SW_READ_LIMIT = 2_000

# Screening proposals are requested for at most this many candidates per model call.
SCREENING_BATCH = 40

# The abstract stage of an `sw` run (K3, decided 2026-09-21; measurement in .local/sw-abstract-batch-2026-09-21).
# The model reads the first N works of the inspection order, N by effort; every other work stays `abstract_not_read`
# and the next discovery run of the same question reads on from there. Hand-picked, not optimised: a batch of 20 gave
# the same labels as one record per call on two topics (96 of 100, 54 of 60) at half the time, and label accuracy was
# not measured at all. The quote bound keeps a two-word fragment from standing as a whole abstract's evidence.
ABSTRACT_READ_LIMIT = {"quick": 40, "standard": 100, "detailed": 300}
ABSTRACT_BATCH = 20
ABSTRACT_RUNS = 2
ABSTRACT_QUOTE_MIN_CHARS = 12

# Effort presets bound work; they are not paper-count or accuracy guarantees. Model calls cover the search plan, one
# screening call per SCREENING_BATCH candidates and the answer, each with its one schema repair. Provider requests are
# the plan's query limit; with several providers enabled, one query per relevant provider needs room. `core_depth` is
# how many results OpenAlex's core-only query reads (0: no such query); standard's 250 candidates and 15 model calls were
# chosen for it in docs/product/search-recall-depth-2026-09-17.md, detailed keeps more room than standard.
# 2026-09-21 (D78): an sw discovery run is given CRITERION_CALLS on top of its preset for the criterion proposal it
# makes before the first search (api/app.py), so its room for screening is what it was. The presets themselves are
# unchanged: a legacy run and an answer run propose no criterion and keep the budget they always had.
CRITERION_CALLS = 3
TEST_EFFORT_BUDGETS = {
    "quick": EffortBudget(max_model_calls=6, max_provider_requests=3, max_candidates=20,
                          max_answer_passages=16, results_per_query=10),
    "standard": EffortBudget(max_model_calls=15, max_provider_requests=8, max_candidates=250,
                             max_answer_passages=48, results_per_query=25, core_depth=100),
    "detailed": EffortBudget(max_model_calls=20, max_provider_requests=12, max_candidates=300,
                             max_answer_passages=80, results_per_query=25, core_depth=100),
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


LITERATURE_TASKS = ("search_plan", "screening", "vocabulary_labels", "criterion_proposal", "abstract_screening")
# A repair would let the step name a phrase the question does not hold and then take it back. The block labelling
# gets one attempt: an output that invents, drops or repeats a phrase is rejected and the rule stands (SW17.1). An
# abstract screening batch gets one too, because an invalid output costs nothing: its records stay
# `abstract_not_proposed` and a later discovery run reads them (slice 09).
NO_REPAIR_TASKS = ("vocabulary_labels", "abstract_screening")


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

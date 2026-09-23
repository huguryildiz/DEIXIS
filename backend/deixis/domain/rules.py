"""Deterministic workflow rules shared by the worker and API.

Test defaults here are P1 configuration, not measured product defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deixis.providers.common import MAX_RATE_LIMIT_RETRIES

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


# How many records one sw query reads across its pages, by effort (D88, slice 13c). The limits were picked by hand;
# `detailed` read 2,000 until D90 lowered it to 1,000: on the vocabulary experiment's first question, halving the read
# cost one verified work per round (as OpenAlex ranks them, not as the model reads them). None of the three is
# measured against what the model then includes.
# The limit never drops a record that was read; what it leaves unread is counted (`unread_count`).
SW_READ_LIMIT = {"quick": 400, "standard": 1_000, "detailed": 1_000}

# How many times a paged sw read or an sw abstract lookup batch waits out a provider's 429, by effort (D88).
# `quick` does not wait at all: the rate-limited page or batch ends that read there, its records stay `unread` /
# `abstract_not_found` and are counted, and the run goes on. `detailed` waits as much as it always did. The waiting
# is bounded by count, never by a clock: no effort stops a run at a time (D88). The `legacy` workflow and the
# Crossref lookup path do not read this at all and send what they always sent.
PROVIDER_WAIT = {"quick": 0, "standard": 1, "detailed": MAX_RATE_LIMIT_RETRIES}

# How many hosts one round of sw discovery searches reads at once (D89, slice 13f). A host is asked one request at a
# time whatever this is; the number bounds the hosts, not the requests to one of them, and is the same for every
# effort. Hand-picked, not measured: whether four providers at once draws more 429s than one at a time is not known.
SEARCH_PARALLEL_HOSTS = 4

# Which domain source an sw discovery run searches, read from the OpenAlex field distribution of its gate query
# (D93, slice 14). A source is searched when the fields it covers hold at least ROUTE_SHARE of the records together.
# The table names OpenAlex fields (`primary_topic.field`), never words of a question. OpenAlex and Semantic Scholar
# are searched whatever the distribution. Table and share were picked by hand, not measured: on the three questions
# that were read, every chosen source held at least 86 % and every left-out one at most 9 %, so no share between
# 10 % and 80 % would have changed them, and no question tested the share.
SOURCE_ROUTES_VERSION = "deixis.source_routes.v1"
ROUTE_SHARE = 0.25
ALWAYS_SEARCHED = ("openalex", "semantic_scholar")
LIFE_SCIENCE_FIELDS = ("Medicine", "Nursing", "Health Professions", "Dentistry", "Veterinary", "Neuroscience",
                       "Immunology and Microbiology", "Biochemistry, Genetics and Molecular Biology",
                       "Pharmacology, Toxicology and Pharmaceutics", "Agricultural and Biological Sciences")
SOURCE_ROUTES = {
    "ieee_xplore": ("Computer Science", "Engineering"),
    "arxiv": ("Physics and Astronomy", "Mathematics", "Computer Science"),
    "pubmed": LIFE_SCIENCE_FIELDS,
    "biorxiv": LIFE_SCIENCE_FIELDS,
}

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

# How many works one full-text retrieval run fetches, by effort (D83, slice 10). Hand-picked, the same numbers as
# the abstract stage's read limit; the one measurement behind them is SW10's single topic, where a work cost about
# five seconds and five requests on one machine and one network. Neither the limit nor the time it implies was
# measured in the product. A work outside the limit is not dropped: it is counted as not reached and the next
# retrieval run starts from it.
FULLTEXT_WORK_LIMIT = {"quick": 40, "standard": 100, "detailed": 300}

# How many works one full-text reading run sends to the model, by effort (D85, slice 12). Hand-picked and not
# measured. Each work is read twice, so the model-call budget is twice this. A work outside the limit is not
# dropped: it is counted as not reached and the next reading run starts from it.
FULLTEXT_READ_LIMIT = {"quick": 20, "standard": 50, "detailed": 150}
FULLTEXT_RUNS = 2
FULLTEXT_PASSAGES_PER_CALL = 12
FULLTEXT_CRITERION_PASSAGES = 8
FULLTEXT_QUOTE_MIN_CHARS = 12

# Effort presets bound work; they are not paper-count or accuracy guarantees. Model calls cover the search plan, one
# screening call per SCREENING_BATCH candidates and the answer, each with its one schema repair. Provider requests are
# the plan's query limit; with several providers enabled, one query per relevant provider needs room. `core_depth` is
# how many results OpenAlex's core-only query reads (0: no such query); standard's 250 candidates and 15 model calls were
# chosen for it in docs/product/search-recall-depth-2026-09-17.md, detailed keeps more room than standard.
# 2026-09-21 (D78): an sw discovery run is given CRITERION_CALLS on top of its preset for the criterion proposal it
# makes before the first search (api/app.py), so its room for screening is what it was. The presets themselves are
# unchanged: a legacy run and an answer run propose no criterion and keep the budget they always had.
# 2026-09-21 (D82): the same holds for the one term-suggestion call an `sw` discovery run may make, and only when
# the user asks for it on the approval card (SW2.5). Hand-picked and not measured: how many of at most
# MAX_SUGGESTED_TERMS proposals survive the count probe, and how many of those are really other names, is unknown.
# 2026-09-23 (D92): the model-written search query (slice 13h) gets SEARCH_QUERY_CALLS on top as well: its call and
# one repair, and once more after the user asks for a second try. Only a run whose settings let a model write the query
# is given them.
CRITERION_CALLS = 3
SUGGESTION_CALLS = 1
SEARCH_QUERY_CALLS = 4
MAX_SUGGESTED_TERMS = 12
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


# `fulltext_adjudication` uses the literature model, as abstract screening does. The slice names no other model
# for the reading step.
LITERATURE_TASKS = ("search_plan", "screening", "vocabulary_labels", "criterion_proposal", "term_suggestions", "search_query",
                    "abstract_screening", "fulltext_adjudication")
# A repair would let the step name a phrase the question does not hold and then take it back. The block labelling
# gets one attempt: an output that invents, drops or repeats a phrase is rejected and the rule stands (SW17.1). An
# abstract screening batch gets one too, because an invalid output costs nothing: its records stay
# `abstract_not_proposed` and a later discovery run reads them (slice 09). A term suggestion gets one because the
# user is waiting in front of the card and the repeat is their own button (SW2.5, slice 08c).
NO_REPAIR_TASKS = ("vocabulary_labels", "term_suggestions", "abstract_screening")


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

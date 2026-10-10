"""Citation chaining of an `sw` discovery run: what one link must show, and the frozen policy the run records (D95).

Pure: no database, no clock, no network, no model. The fast chain (`fast_chain.Round`) sends the requests and the
flow writes them (`flow._record_chain`); everything here is a function of the rows it is given, so a resumed run
re-derives nothing it did not already store.

Two rules hold this module together:

- **Nothing topical is written here.** A linked work passes when a form of one of the two approved gate blocks stands
  at a word start in its title or abstract (`ranking.blocks_in`), the one matcher the ranking and the abstract stage
  use; which words those are is the research's own vocabulary.
- **A seed is a work, not a record.** Two heads with the same work or the same normalised title are one seed, so a
  preprint and its published record the merge left apart do not spend two places.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES, PROVIDER_WAIT
from deixis.workflow.ranking import blocks_in

DIRECTIONS = ("backward", "forward")
SOURCE = "openalex"
# The query text a chain request's search run carries: which direction, and which seed or batch (slice 15, Task 3).
# `search_runs` has no kind column, so this is how a row says it was a chain request and not a keyword query.
QUERY_PREFIX = "chain:"
STEP_KIND = "provider_chain:openalex"


def attempt_limit(fast: dict[str, Any], effort: str) -> int:
    """How many HTTP attempts the fast chain may spend in all (usage `chain_requests`), for a frozen fast-path policy.

    Each logical request (`backward_requests + forward_requests`) may wait out the effort's rate-limit retries
    (`PROVIDER_WAIT`) and be resent after a transient network failure before anything was sent
    (`MAX_TRANSIENT_NETWORK_RETRIES`). `fast_chain.Round.fetch` enforces this number and `policy` records it.
    """
    return ((fast["backward_requests"] + fast["forward_requests"])
            * (1 + PROVIDER_WAIT[effort]) * (1 + MAX_TRANSIENT_NETWORK_RETRIES))


def policy(budget: dict[str, Any], effort: str) -> dict[str, Any] | None:
    """The chain policy a discovery run's budget froze when it was queued (`fast_path.freeze_budget`), or None for a
    run that carries no fast-path policy (every run kind but discovery).

    The policy is read from the budget, never from the settings of the moment, so both the protocol and the approval
    card say what the run really does: the fast chain (`fast_chain_v1`), OpenAlex only. `request_limit` counts logical
    requests; `attempt_limit` is the total HTTP attempts the chain may spend, retries included.
    """
    fast = budget.get("fast_path") or {}
    if not fast.get("chain_rule"):
        return None
    return {"enabled": True, "rule_version": fast["chain_rule"], "source": SOURCE, "sources": [SOURCE],
            "directions": list(DIRECTIONS), "seeds": fast["chain_seeds"],
            "backward_requests": fast["backward_requests"], "backward_page_size": fast["backward_page_size"],
            "forward_requests": fast["forward_requests"], "forward_page_size": fast["forward_page_size"],
            "citing_cap": fast["forward_page_size"],
            "request_limit": fast["backward_requests"] + fast["forward_requests"],
            "attempt_limit": attempt_limit(fast, effort),
            "in_flight": fast["chain_in_flight"]}


def norm_title(title: str | None) -> str:
    """A title as the seed rule compares it: case folded, every run of non-word characters one space."""
    return re.sub(r"\W+", " ", (title or "").casefold()).strip()


def backward_links(seeds: list[dict[str, Any]], batch: Iterable[str]) -> list[tuple[str, str]]:
    """(seed, referenced work) for every seed whose list names a work of this batch; one row per pair."""
    wanted = set(batch)
    return sorted((seed["source_version_id"], ref) for seed in seeds
                  for ref in set(seed.get("references") or ()) & wanted)


def passes(forms: dict[str, list[str]], title: str | None, abstract: str | None) -> bool:
    """Whether a linked work names the setting or the task: one gate block's form at a word start in its title or its
    abstract. A work without an abstract is judged on its title alone (slice 15, Task 3.5)."""
    return bool(blocks_in(forms, f"{title or ''} {abstract or ''}"))


def chained_heads(linked_heads: Iterable[str], keyword_pool: set[str]) -> list[str]:
    """The work heads the chain brought that the keyword pool does not hold, sorted.

    A linked record the record path merged into a keyword work has that work's head, so it is not a chained work: the
    keyword path already has it, and the chain adds nothing but a hit (slice 15, global constraint "one record path").
    """
    return sorted({head for head in linked_heads if head not in keyword_pool})


def request_outcomes(steps: Iterable[dict[str, Any]]) -> dict[str, int]:
    """What became of each recorded fast-chain request (`chain:fast:{n}` steps, as `Store.run_steps` gives them).

    Whether a request was sent is read from its own step, not from the summary's `sent` (which counts every request
    that was not cancelled): a reply means it was sent; a failure before sending (`before_send`, or a transport trace
    that recorded zero sends) counts as not sent, any other failure as sent; an outcome-unknown request stays unknown,
    whatever was recorded.
    """
    counts = {"sent": 0, "answered": 0, "late": 0, "failed": 0, "unknown": 0, "not_sent": 0}
    for step in steps:
        if not step["operation_key"].startswith("chain:fast:"):
            continue
        output = step.get("output") or {}
        if step["status"] == "outcome_unknown":
            counts["unknown"] += 1
        elif step["status"] == "succeeded":
            counts["sent"] += 1
            counts["late" if output.get("late") else "answered"] += 1
        elif step["status"] == "failed":
            transport = output.get("transport")
            before = step.get("delivery_class") == "before_send" or (transport is not None and not transport.get("sends"))
            counts["not_sent" if before else "failed"] += 1
            counts["sent"] += 0 if before else 1
        elif step["status"] == "cancelled":
            counts["not_sent"] += 1
    return counts

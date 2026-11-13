"""Citation chaining of an `sw` discovery run: what one link must show, and the frozen policy the run records.

Pure: no database, no clock, no network, no model. The fast chain (`fast_chain.Round`) sends the requests and the
flow writes them (`flow._record_chain`); everything here is a function of the rows it is given, so a resumed run
re-derives nothing it did not already store.

Two rules hold this module together:

- **Nothing topical is written here.** A linked work passes when a form of one of the two approved gate blocks stands
  at a word start in its title, its abstract or one of the keywords OpenAlex's own classifier gave it
  (`ranking.blocks_in`), the one matcher the ranking and the abstract stage use; which words those are is the
  research's own vocabulary. Each keyword is matched on its own, so no form is read across the join between two of
  them or between a keyword and the abstract. The keywords only ever open the gate wider: a work that passed
  on its title or abstract passes whatever they say, and a work whose read asked for no keyword is judged as before.
- **A seed is a work, not a record.** Two heads with the same work or the same normalised title are one seed, so a
  preprint and its published record the merge left apart do not spend two places.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from deixis.domain import canonical
from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES
from deixis.workflow.run import fast_path
from deixis.domain.vocabulary import words
from deixis.workflow.search.ranking import blocks_in

DIRECTIONS = ("backward", "forward")
SOURCE = "openalex"
# The query text a chain request's search run carries: which direction, and which seed or batch (slice 15, Task 3).
# `search_runs` has no kind column, so this is how a row says it was a chain request and not a keyword query.
QUERY_PREFIX = "chain:"
STEP_KIND = "provider_chain:openalex"
# The admission rule a run's budget freezes (`fast_path.freeze_budget`). It matches normalised words against the
# searched forms and every gate-block term the query step wrote, and it adds the rescue quota: the first few linked
# records no gate form reaches are written as ranked candidates all the same, and the gate's verdict on them is
# still recorded. A run keeps the rule it was queued with; a run frozen under an older rule is stopped
# (`small_batch.removed_rule`) rather than carried out under this one.
RULE_V3 = "fast_chain_v3"
# The characters the rule splits a word on before it compares: hyphen-minus, hyphen, non-breaking hyphen, en dash,
# slash.
_SPLIT = re.compile(r"[-\u2010\u2011\u2013/]")


def attempt_limit(fast: dict[str, Any], effort: str) -> int:
    """How many HTTP attempts the fast chain may spend in all (usage `chain_requests`), for a frozen fast-path policy.

    Each logical request (`backward_requests + forward_requests`) may wait out its frozen rate-limit retries
    and be resent after a transient network failure before anything was sent
    (`MAX_TRANSIENT_NETWORK_RETRIES`). `fast_chain.Round.fetch` enforces this number and `policy` records it.
    """
    return ((fast["backward_requests"] + fast["forward_requests"])
            * (1 + fast_path.search_read(fast, effort, "provider_wait")) * (1 + MAX_TRANSIENT_NETWORK_RETRIES))


def policy(budget: dict[str, Any], effort: str) -> dict[str, Any] | None:
    """The chain policy a discovery run's budget froze when it was queued (`fast_path.freeze_budget`), or None for a
    run that carries no fast-path policy (every run kind but discovery).

    The policy is read from the budget, never from the settings of the moment, so both the protocol and the approval
    card say what the run really does: the fast chain, OpenAlex only. `request_limit` counts logical
    requests; `attempt_limit` is the total HTTP attempts the chain may spend, retries included. A depth that opens no
    citation request of its own (Quick) carries every number as zero, and its links come from the pool alone.

    `rescue_quota` is how many linked records no gate form reaches the run may still write as candidates (v3); a run
    whose budget froze no quota writes none, as before.
    """
    fast = budget.get("fast_path") or {}
    if not fast.get("chain_rule"):
        return None
    return {"enabled": True, "rule_version": fast["chain_rule"], "source": SOURCE, "sources": [SOURCE],
            "rescue_quota": fast.get("chain_rescue", 0),
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


def passes(forms: dict[str, list[str]], title: str | None, abstract: str | None,
           keywords: Iterable[str] | None = None) -> bool:
    """Whether a linked work names the setting or the task: one gate block's form at a word start in its title, its
    abstract or one of its provider keywords. A work without an abstract is judged on its title alone (slice 15,
    Task 3.5); one whose read asked for no keyword is judged on title and abstract alone, as before that change."""
    if blocks_in(forms, f"{title or ''} {abstract or ''}"):
        return True
    return any(blocks_in(forms, keyword) for keyword in keywords or ())


def _plain_singular(word: str) -> str:
    """The plain plural rule v2 compares words with (replay-r5/chain_admission.py): ies to y, sses to ss, es after
    s/x/z/ch/sh, s otherwise; words of three letters or fewer and words ending in ss, us or is are kept."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if re.search(r"(s|x|z|ch|sh)es$", word):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def norm_words(text: str | None) -> list[str]:
    """The words of a text as v2 compares them: lower case, split at hyphens and slashes, plain plurals reduced."""
    return [_plain_singular(word) for word in words(_SPLIT.sub(" ", text or ""))]


def admission_forms(blocks: dict[str, list[str]], vocabulary: dict[str, Any]) -> dict[str, list[str]]:
    """The v2 admission forms of each gate block, normalised and sorted: the forms the run searched the block with
    (`blocks`, as `ranking.query_vocabulary` gives them) and every term of that block the query step wrote, a dropped
    one and an unused backup included. A vocabulary no query step wrote (the code's alone) adds nothing."""
    from deixis.workflow.search.vocabulary import GATE_BLOCKS

    record = vocabulary.get("search_query") or {}
    written = {block: list(blocks.get(block) or []) for block in GATE_BLOCKS}
    if record:
        for term in vocabulary["terms"]:
            if term["block"] in written:
                written[term["block"]].append(term["phrase"])
        for block, extra in (record.get("backups_left") or {}).items():
            if block in written:
                written[block] += list(extra)
    return {block: sorted({" " + " ".join(found) for phrase in group if (found := norm_words(phrase))})
            for block, group in written.items()}


def forms_digest(forms: dict[str, list[str]]) -> str:
    return canonical.sha256_hex(forms)


def passes_v2(forms: dict[str, list[str]], title: str | None, abstract: str | None,
              keywords: Iterable[str] | None = None) -> bool:
    """Whether a linked work holds one v2 form at a word start of its normalised title, abstract or provider keyword.

    Each keyword is normalised and padded on its own, so a form is never read across the join between two of them."""
    wanted = [form for group in forms.values() for form in group]
    for text in (f"{title or ''} {abstract or ''}", *(keywords or ())):
        padded = " " + " ".join(norm_words(text)) + " "
        if any(form in padded for form in wanted):
            return True
    return False


def chained_heads(linked_heads: Iterable[str], keyword_pool: set[str]) -> list[str]:
    """The work heads the chain brought that the keyword pool does not hold, sorted.

    A linked record the record path merged into a keyword work has that work's head, so it is not a chained work: the
    keyword path already has it, and the chain adds nothing but a hit (slice 15, global constraint "one record path").
    """
    return sorted({head for head in linked_heads if head not in keyword_pool})




def request_sent(step: dict[str, Any]) -> bool | None:
    """Whether one fast-chain request step went out. Its transport trace decides first: one recorded send or more is
    sent, none is not sent. Without a trace: a reply is sent, a failure is sent unless it failed before sending
    (`before_send`), a cancelled request is not sent, and an outcome-unknown one is unproven (None)."""
    trace = (step.get("output") or {}).get("transport")
    if trace is not None:
        return (trace.get("sends") or 0) > 0
    if step["status"] == "succeeded":
        return True
    if step["status"] == "failed":
        return step.get("delivery_class") != "before_send"
    return None if step["status"] == "outcome_unknown" else False


def request_outcomes(steps: Iterable[dict[str, Any]]) -> dict[str, int]:
    """What became of each recorded fast-chain request (`chain:fast:{n}` steps, as `Store.run_steps` gives them),
    counted by its own step and not by the summary's `sent` (which counts every request that was not cancelled).

    `sent` = `answered` + `late` + `failed` + `unknown`: a sent request answered before the cutoff, after it, without a
    usable reply, or with an unknown outcome. `not_sent` was never sent. `unproven` has an unknown outcome and no
    record that it was sent, so it is in neither of the two.
    """
    counts = dict.fromkeys(("sent", "answered", "late", "failed", "unknown", "not_sent", "unproven"), 0)
    for step in steps:
        # A request still pending or running is not settled yet and is not counted until it is.
        if not step["operation_key"].startswith("chain:fast:") or step["status"] in ("pending", "running"):
            continue
        sent = request_sent(step)
        if sent is None:
            counts["unproven"] += 1
        elif not sent:
            counts["not_sent"] += 1
        else:
            counts["sent"] += 1
            if step["status"] == "succeeded":
                counts["late" if (step.get("output") or {}).get("late") else "answered"] += 1
            else:
                counts["unknown" if step["status"] == "outcome_unknown" else "failed"] += 1
    return counts

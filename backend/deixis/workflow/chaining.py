"""Citation chaining of an `sw` discovery run: which works seed it, what one link must show, and the policy (D95).

Pure: no database, no clock, no network, no model. The flow reads the store and sends the requests (`flow._chaining`);
everything here is a function of the rows it is given, so a resumed run re-derives nothing it did not already store.

Three rules hold this module together:

- **The keyword path is not touched.** The seeds are read from the keyword ranking's own stored ranks, and nothing
  here reorders, adds to or removes from the keyword pool. The chained works get their own abstract read and their
  own room in the full-text plan, on top of the keyword limits (slice 15, decision 4).
- **Nothing topical is written here.** A linked work passes when a form of one of the two approved gate blocks stands
  at a word start in its title or abstract (`ranking.blocks_in`), the one matcher the ranking and the abstract stage
  use; which words those are is the research's own vocabulary.
- **A seed is a work, not a record.** Two heads with the same work or the same normalised title are one seed, so a
  preprint and its published record the merge left apart do not spend two of the fifteen places.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from deixis.domain.rules import (CHAIN_ABSTRACT_READ, CHAIN_BACKWARD_BATCH, CHAIN_CITING_CAP, CHAIN_PLAN_ROOM,
                                 CHAIN_SEEDS)
from deixis.workflow.ranking import blocks_in

RULE_VERSION = "deixis.citation_chaining.v1"
DIRECTIONS = ("backward", "forward")
SOURCE = "openalex"
FILTER = "gate_block_form_in_title_or_abstract"
# The query text a chain request's search run carries: which direction, and which seed or batch (slice 15, Task 3).
# `search_runs` has no kind column, so this is how a row says it was a chain request and not a keyword query.
QUERY_PREFIX = "chain:"
STEP_KIND = "provider_chain:openalex"


def policy(budget: dict[str, Any], effort: str) -> dict[str, Any] | None:
    """The chain policy a discovery run's budget froze when it was queued, or None for a run queued before D95.

    The setting is read from the budget, never from the settings of the moment, so both protocol revisions of a run
    carry the same block and a changed setting cannot reach a run already queued.
    """
    setting = budget.get("citation_chaining")
    if setting is None:
        return None
    if setting != "auto":
        return {"enabled": False}
    return {"enabled": True, "rule_version": RULE_VERSION, "seeds": CHAIN_SEEDS, "user_seeds": "every_verified",
            "seed_order": "bm25_blocks_fused", "directions": list(DIRECTIONS), "source": SOURCE,
            "citing_cap": CHAIN_CITING_CAP, "backward_batch": CHAIN_BACKWARD_BATCH,
            "request_limit": budget["max_chain_requests"], "filter": FILTER,
            "abstract_read": CHAIN_ABSTRACT_READ[effort], "plan_room": CHAIN_PLAN_ROOM[effort]}


def enabled(budget: dict[str, Any]) -> bool:
    return budget.get("citation_chaining") == "auto"


def norm_title(title: str | None) -> str:
    """A title as the seed rule compares it: case folded, every run of non-word characters one space."""
    return re.sub(r"\W+", " ", (title or "").casefold()).strip()


def code_seeds(order: list[str], rows: dict[str, dict[str, Any]], user_works: set[str],
               limit: int = CHAIN_SEEDS) -> list[str]:
    """The first `limit` distinct works of the BM25-and-blocks order that are not the user's own seeds.

    `rows` is the keyword pool by head (`work_id`, `title`). A head whose work or normalised title an earlier head
    already holds is the same seed and is skipped before it is counted, so the list is `limit` works long whenever
    the pool holds that many; a user seed is apart and never shortens it (decision 2).
    """
    seen: set[str] = set()
    chosen: list[str] = []
    for head in order:
        row = rows.get(head)
        if row is None or row["work_id"] in user_works:
            continue
        keys = {f"work:{row['work_id']}", f"title:{norm_title(row['title'])}"}
        if keys & seen:
            continue
        seen |= keys
        chosen.append(head)
        if len(chosen) == limit:
            break
    return chosen


def seed_list(order: list[str], rows: dict[str, dict[str, Any]], user: list[dict[str, Any]],
              limit: int = CHAIN_SEEDS) -> list[dict[str, Any]]:
    """The chain's seeds: `limit` code seeds from the BM25-and-blocks order, then every seed the user verified.

    `user` is the verified seeds' rows (`id`, `work_id`), in `ranking.verified_seeds` order. The stored graph seeds of
    the ranking are not read: `rank_records` fills them up to fifteen together with the user's, so they are shorter
    than fifteen exactly when the user has seeds of their own (decision 2, Sol's finding).
    """
    code = code_seeds(order, rows, {row["work_id"] for row in user}, limit)
    return ([{"source_version_id": head, "kind": "code"} for head in code]
            + [{"source_version_id": row["id"], "kind": "user"} for row in user])


def directions(seed: dict[str, Any]) -> list[str]:
    """Which way a seed is chained: backward when its reference list was read and names a work, forward when it has an
    OpenAlex identifier to ask `cites:` for. A seed with neither is still a seed and is counted."""
    return [name for name, ok in (("backward", bool(seed.get("references"))),
                                  ("forward", bool(seed.get("openalex_ids")))) if ok]


def backward_batches(seeds: list[dict[str, Any]], held: set[str], size: int = CHAIN_BACKWARD_BATCH) -> list[list[str]]:
    """The referenced works the research does not hold yet, sorted, cut into batches of `size`.

    A reference the research already holds sends no request: its record is here, and it is either a keyword work or
    a work an earlier chain brought. A seed without a reference list adds nothing here.
    """
    wanted = sorted({ref for seed in seeds for ref in seed.get("references") or () if ref not in held})
    return [wanted[start:start + size] for start in range(0, len(wanted), size)]


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


def chain_order(ranked_order: list[str], chained: set[str]) -> list[str]:
    """The chain's inspection order: the joint ranking's order with every keyword work taken out."""
    return [head for head in ranked_order if head in chained]

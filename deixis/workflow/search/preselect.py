"""Which records the reranker is given when the candidate pool is larger than its window (`rrf_v1`).

Pure: no database, no clock, no network, no model. Everything here is a function of the rows the list's manifest
froze, so a resumed run and an offline replay choose the same window.

Three rules hold this module together:

- **It decides who is read, not how they are ordered.** How the reranker's scores then order the list is the rerank
  rule's (`small_batch.reranked`), and so is the fused order's own reserve the window takes before anything here
  fills it (`small_batch.window_for`, rerank rule version 6). A pool that fits the window is not touched at all.
- **One query list, one vote.** A list is one query of one provider: its continuation pages are the same list and a
  resend of the same request is no second vote, so a record is counted once, at the first place that list gave it.
  Only a list the provider ordered by relevance votes; a list ordered by date or citation count does not, and a
  citation link is no list at all, so citation chaining casts no vote.
- **A vote is not the only way in.** A record only citation chaining found, or only one focused query found, has one
  channel and no votes to spare, so the window keeps a floor for each of them: at least that many of its records are
  in the window, reserved before the votes fill anything.
"""

from __future__ import annotations

from typing import Any, Iterable

RULE = "rrf_v1"
# The list identity of a run that froze the short phrase searches: provider, endpoint, query text and sort, so a
# semantic request and a keyword request of the same text are two lists. A manifest frozen without it names no
# identity and its lists stay keyed by provider, query text and sort, as they were frozen.
ENDPOINT_IDENTITY = "provider_endpoint_query_sort_v1"
# The k of the original RRF study (Cormack, Clarke and Buettcher, 2009): a larger k flattens the difference between
# the leading places, a smaller one widens it. The run freezes the value it used.
K = 60


def lists(hits: Iterable[dict[str, Any]], identity: str | None = None) -> list[dict[str, Any]]:
    """Every query list of one run, with the place it gave each record and whether it votes.

    `hits` are the stored hit rows: `head` (the record's work head), `provider`, `query_text`, `sort` (the sorting
    setting the request carried), `relevance` (whether that setting is a relevance order), `read_total` (how deep the
    list was read) and `rank` (the place the request's own answer gave the record, counting its earlier pages, from
    zero). Rows of the same provider and query text are one list, so the pages of one query and a resend of it do not
    vote twice, and a record keeps the first place that list gave it.

    A list the provider did not order by relevance is kept, with `votes` false: its records are in the pool and count
    as a way in, but the list casts no vote. A row without a place is a member of its list and is not ranked by it.

    With `identity` (`ENDPOINT_IDENTITY`) the hit's `endpoint` is part of the key too and each list names it; without
    it the key and every list are exactly what they were before the rule.
    """
    found: dict[tuple[str, ...], dict[str, Any]] = {}
    for hit in hits:
        # The sorting setting is part of the key: the same query asked once in relevance order and once by date is
        # two lists, and only the first of them votes.
        key = (hit["provider"], hit["query_text"], hit.get("sort") or "")
        named = {}
        if identity == ENDPOINT_IDENTITY:
            # The endpoint joins the key, so a semantic request and a keyword request of one text are two lists.
            key += (hit.get("endpoint") or "",)
            named = {"endpoint": hit.get("endpoint")}
        entry = found.setdefault(key, {"provider": hit["provider"], "query_text": hit["query_text"],
                                       "sort": hit.get("sort"), **named, "votes": bool(hit.get("relevance")),
                                       "read_total": None, "members": set(), "places": {}})
        entry["members"].add(hit["head"])
        if hit.get("read_total") is not None:
            entry["read_total"] = max(entry["read_total"] or 0, int(hit["read_total"]))
        if hit.get("rank") is None:
            continue
        place = entry["places"].get(hit["head"])
        if place is None or hit["rank"] < place:
            entry["places"][hit["head"]] = hit["rank"]
    return [entry | {"members": sorted(entry["members"]), "size": len(entry["places"])}
            for entry in sorted(found.values(),
                                key=lambda e: (e["provider"], e["query_text"], e["sort"] or "", e.get("endpoint") or ""))]


def narrow_heads(query_lists: Iterable[dict[str, Any]]) -> list[str]:
    """The records only a focused query found: in a focused list and in no other list of any kind.

    A focused query asks for one concept the two blocks of the main query cannot hold, so what it alone finds has one
    channel and one vote. A record another query also returned has another way in, whether or not that query's list
    votes, so the lists the provider ordered by date or citation count count here too. The window keeps a floor for
    these records, as it does for the chain's own.
    """
    entries = list(query_lists)
    wide = {head for entry in entries if not entry.get("focused") for head in entry["members"]}
    narrow = {head for entry in entries if entry.get("focused") for head in entry["members"]}
    return sorted(narrow - wide)


def scores(query_lists: Iterable[dict[str, Any]], k: int = K) -> dict[str, list[dict[str, Any]]]:
    """Each record's contributions, by work head: one entry per voting list that placed it, with the place it gave the
    record (from one, as the rule is written) and `1 / (k + place)`. A record no voting list placed has no entry."""
    found: dict[str, list[dict[str, Any]]] = {}
    for entry in query_lists:
        if not entry.get("votes"):
            continue
        for head, place in sorted(entry["places"].items()):
            rank = place + 1  # the stored place counts from zero; the rule's rank counts from one
            found.setdefault(head, []).append(
                {"provider": entry["provider"], "query_text": entry["query_text"], "rank": rank,
                 "contribution": 1.0 / (k + rank)})
    return found


def order(contributions: dict[str, list[dict[str, Any]]], works: dict[str, str]) -> list[str]:
    """The records the lists voted for, by the sum of their contributions, highest first.

    Equal sums are resolved by the work's lasting identifier, so the same votes always give the same order. A record
    no list voted for is not here at all: it has no RRF place, and the window reaches it by a floor or, once the
    voted records run out, by the run's own fused order.
    """
    total = {head: sum(part["contribution"] for part in parts) for head, parts in contributions.items() if parts}
    return sorted(total, key=lambda head: (-total[head], works.get(head, head)))


def window(size: int, fused: list[str], ranked: list[str], *, chain_only: Iterable[str] = (),
           narrow_only: Iterable[str] = (), quota: dict[str, int] | None = None) -> dict[str, Any]:
    """The records the reranker is given, and what each floor reserved.

    A floor is a guaranteed least number of places: each one reserves its first `quota` records, in the order the
    caller gives them, before anything is filled, so no floor can be crowded out by the votes or by another floor. A
    record two floors hold is reserved once. The places left over are filled from the RRF order and then, while
    places remain, from the run's own fused order. `size` places are filled while the pool has records for them.
    """
    quota = quota or {}
    chosen: list[str] = []
    taken: dict[str, list[str]] = {}
    for name, members in (("chain_only", list(chain_only)), ("narrow_only", list(narrow_only))):
        room = max(0, int(quota.get(name, 0)))
        reserved: list[str] = []
        for head in members:
            if len(reserved) >= room or len(chosen) >= size:
                break
            if head in chosen:  # the other floor holds it too, and one place is enough for both
                continue
            chosen.append(head)
            reserved.append(head)
        taken[name] = reserved
    for head in list(ranked) + list(fused):
        if len(chosen) >= size:
            break
        if head not in chosen:
            chosen.append(head)
    return {"window": chosen, "floors": taken}

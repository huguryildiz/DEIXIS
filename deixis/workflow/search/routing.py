"""Which sources an sw discovery run searches, decided by code before the approval card (slice 14, SW3).

One OpenAlex request, grouped by the field of each work's primary topic, is sent for the gate query the proposal
would search with. A domain source (IEEE Xplore, arXiv, PubMed, bioRxiv) is searched when the fields it covers hold at
least `ROUTE_SHARE` of the records together (`SOURCE_ROUTES`); OpenAlex and Semantic Scholar are searched whatever
the distribution, and so is a searched connector the table does not name. A distribution that cannot be read routes
to every domain source in scope, and says so: a missing source loses works, an extra one only costs requests. No
source outside the research's scope is ever chosen.

Nothing here names a question's words: the table names OpenAlex fields.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.rules import (ALWAYS_SEARCHED, PREPRINT_SOURCES, ROUTE_SHARE, SOURCE_ROUTES,
                                 SOURCE_ROUTES_VERSION)
from deixis.providers.query_compiler import quoted
from deixis.providers.registry import CONNECTORS
from deixis.workflow.search.vocabulary import GATE_BLOCKS

def gate_query(vocabulary: dict[str, Any] | None) -> str | None:
    """The gate query of a vocabulary: each gate block's searched terms in one OR group, the groups joined by AND.

    It is the query whose count is the vocabulary's `gate_count`, written the same way for a model-written
    vocabulary (whole phrases) and for the code's (root or phrase, as the term entered the query).
    """
    if not vocabulary:
        return None
    groups = []
    for block in GATE_BLOCKS:
        forms = [quoted(t["root"] if t["in_query"] == "root" else t["phrase"])
                 for t in vocabulary["terms"] if t["block"] == block and not t["dropped"]]
        if forms:
            groups.append("(" + " OR ".join(forms) + ")")
    return " AND ".join(groups) if groups else None


def _usable(provider: str, scope_providers: list[str], excluded: tuple[str, ...] | list[str] = ()) -> str | None:
    """Why this connector cannot be searched by an sw run of this scope, or None when it can. `excluded` are the
    providers a person left out of a saved search plan (UI parity S23a)."""
    connector = CONNECTORS[provider]
    if not connector.sw_searchable:
        return "not_in_sw_search"
    if provider not in scope_providers:
        return "not_in_scope"
    if provider in excluded:
        return "excluded_by_user"
    if connector.access_mode() == "not_configured":
        return "not_configured"
    return None


def needs_distribution(scope_providers: list[str]) -> bool:
    """Whether any domain source could be chosen at all; with none, the distribution decides nothing."""
    return any(_usable(provider, scope_providers) is None for provider in SOURCE_ROUTES)


def route(scope_providers: list[str], query: str | None, distribution: dict[str, Any] | None,
          status: str, excluded: tuple[str, ...] | list[str] = (), share: float | None = None) -> dict[str, Any]:
    """The routing record: the distribution read, every searchable connector chosen or left out with its reason, and
    the providers the queries are compiled for, in search order (OpenAlex, Semantic Scholar, then the chosen domain
    sources in registry order).

    `status` is `read` (a distribution was read), `unavailable` (it could not be read: every usable domain source is
    chosen) or `not_needed` (no domain source is usable, so nothing was asked). A distribution read with no records or
    no field counts has no shares to route by and is taken as `unavailable` (review of slice 14, 2026-09-23).

    `share` is the share the run froze when it started, so a run decides by the number it began with; without one the
    table's own default is read, as every run before the policy carried it did.
    """
    route_share = ROUTE_SHARE if share is None else share
    if status == "read" and distribution is not None and not (distribution["total"] and distribution["fields"]):
        status = "unavailable"
    total = distribution["total"] if distribution else None
    counts = {row["field"]: row["count"] for row in distribution["fields"]} if distribution else {}
    fields = [{"field": field, "count": count, "share": round(count / total, 4) if total else 0.0}
              for field, count in counts.items()]
    chosen: list[dict[str, Any]] = []
    left_out: list[dict[str, Any]] = []
    for provider, connector in CONNECTORS.items():
        if not connector.searchable:
            continue
        reason = _usable(provider, scope_providers, excluded)
        if provider in ALWAYS_SEARCHED:
            (left_out if reason else chosen).append({"provider_id": provider, "reason": reason or "always"})
            continue
        routes = SOURCE_ROUTES.get(provider)
        if reason:
            left_out.append({"provider_id": provider, "reason": reason})
            continue
        if routes is None:
            # A searched connector the table does not name is not the distribution's to leave out: it is searched,
            # and says why. Every sw connector of today is in the table or always searched.
            chosen.append({"provider_id": provider, "reason": "no_route"})
            continue
        if status != "read":
            chosen.append({"provider_id": provider, "reason": "distribution_unavailable", "fields": list(routes)})
            continue
        # The unrounded share is compared; the rounded one is only shown (a 24.996% share is below 25%).
        raw = sum(counts.get(field, 0) for field in routes) / total if total else 0.0
        row = {"provider_id": provider, "fields": list(routes), "share": round(raw, 4)}
        if raw >= route_share:
            chosen.append(row | {"reason": "share"})
        else:
            left_out.append(row | {"reason": "share_below"})
    order = [p for p in ALWAYS_SEARCHED if any(c["provider_id"] == p for c in chosen)]
    order += [c["provider_id"] for c in chosen if c["provider_id"] not in ALWAYS_SEARCHED]
    return {"status": status, "query": query, "total": total, "fields": fields, "route_share": route_share,
            "table_version": SOURCE_ROUTES_VERSION, "chosen": chosen, "left_out": left_out, "providers": order}


def field_sources(routing: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """The field sources a depth of this `limit` searches, in the order a smaller depth would drop them.

    The share decides: the source whose fields hold the most of the question's records is read first. Two sources
    whose shares are equal are not equally good first reads, so the tie goes to the index that is not a preprint
    server (`PREPRINT_SOURCES`), and then to the registry's own order. A source whose query goes through another
    provider's host (bioRxiv, through OpenAlex) is searched like any other but is never recorded as an index of its
    own, so a depth that pays for a second independent index cannot be given it twice.

    Nothing here reads a word of the question: the shares come from the stored routing record, which counts OpenAlex
    fields. A record whose distribution could not be read chose every usable source without a share to compare, so
    no source is "the one that fits best" and none is returned.
    """
    if not routing or routing.get("status") != "read" or limit <= 0:
        return []
    order = list(CONNECTORS)
    rows = [row for row in routing["chosen"] if row["provider_id"] not in ALWAYS_SEARCHED and "share" in row]
    rows.sort(key=lambda row: (-row["share"], row["provider_id"] in PREPRINT_SOURCES,
                               order.index(row["provider_id"])))
    return [{"provider_id": row["provider_id"], "share": row["share"],
             "independent": CONNECTORS[row["provider_id"]].lineage is None} for row in rows[:limit]]

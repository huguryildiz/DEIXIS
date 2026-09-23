"""Scholarly search connectors: identity, credentials and result limits.

Order is the order providers are listed to the model and in the UI. A connector whose key is required but not
configured is listed as `not_configured` and not enabled for new researches. Key values are read from the environment
at call time and never stored.

A connector has one of two roles: a searched source, or a verification source that is only asked about a record whose
DOI is already known (D87). `searchable` carries that, and it is the only thing any caller reads to decide whether a
query may go there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from deixis.providers import arxiv, biorxiv, core, crossref, ieee_xplore, openalex, pubmed, scopus, semantic_scholar, serpapi
from deixis.providers.common import SearchOutcome


@dataclass(frozen=True)
class Endpoint:
    """Another endpoint of a connector that an sw query can name (D93), and how a read of it pages."""

    paging: str
    max_results: int
    max_reachable: int | None = None


@dataclass(frozen=True)
class Connector:
    provider_id: str
    search: Callable[..., Awaitable[SearchOutcome]]
    max_results: int
    key_env: str | None = None
    key_required: bool = False
    supplementary: bool = False  # adds coverage beside direct providers; never used in place of one
    # Whether a query may be sent here at all. A connector that is not searchable still answers about a record whose
    # DOI is already known — its metadata, its links — and is never asked to find records (D87). The queries are
    # compiled from this flag alone, so neither the flow nor the compiler names a provider (slice 05).
    searchable: bool = True
    # Whether an sw research sends a query here. Scopus is searched by a legacy research and, in an sw research, is
    # only the last abstract source, and only on an institutional network (D91). A query an sw run already stored is
    # still read: `searchable` alone decides that, so a resumed run searches the queries its protocol names.
    sw_searchable: bool = True
    # How an sw query reads its pages (slice 04c): a provider-issued `cursor`, a record `offset`, or one page only.
    paging: str = "offset"
    max_reachable: int | None = None  # the deepest record the provider serves, when that is below the read limit
    page_gap: float = 0.0  # seconds to wait between two pages of the same query
    # Extra arguments an sw paged read passes to `search`, so a legacy request stays byte for byte what it was and
    # the flow never names a provider to decide what to ask for (slice 05).
    sw_options: dict[str, Any] = field(default_factory=dict)
    # The host name a search request goes to, taken from the URL the module sends it to. Two connectors that share one
    # are read one request at a time between them (D89): bioRxiv is searched through OpenAlex.
    host: str = ""
    # What a new sw query compiled for this connector names besides its text: Semantic Scholar's bulk endpoint and its
    # sort (D93). The query carries it, so a resumed run reads the endpoint its stored query names, and a query stored
    # before D93, which names none, is read as it was (`reading`).
    sw_query: dict[str, Any] = field(default_factory=dict)
    endpoints: dict[str, Endpoint] = field(default_factory=dict)

    def api_key(self) -> str | None:
        return (os.environ.get(self.key_env) or None) if self.key_env else None

    def access_mode(self) -> str:
        if self.api_key():
            return "api_key"
        return "not_configured" if self.key_required else "keyless"


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


CONNECTORS = {c.provider_id: c for c in (
    Connector("openalex", openalex.search_works, openalex.MAX_RESULTS, "OPENALEX_API_KEY", paging="cursor",
              sw_options={"reference_count": True, "references": True}, host=_host(openalex.WORKS_URL)),
    # Semantic Scholar's relevance search serves `offset + limit` up to 1,000 and refuses a deeper page. An sw query
    # goes to the bulk endpoint instead: up to 1,000 papers a call, continued by a token (D93).
    Connector("semantic_scholar", semantic_scholar.search, semantic_scholar.MAX_RESULTS, "S2_API_KEY", max_reachable=1000,
              host=_host(semantic_scholar.SEARCH_URL),
              sw_query={"endpoint": semantic_scholar.BULK_ENDPOINT, "sort": semantic_scholar.BULK_SORT},
              endpoints={semantic_scholar.BULK_ENDPOINT: Endpoint("cursor", semantic_scholar.BULK_MAX_RESULTS)}),
    Connector("crossref", crossref.search, crossref.MAX_RESULTS, searchable=False,  # verification only (D87)
              host=_host(crossref.WORKS_URL)),
    # arXiv asks for three seconds between requests and refused consecutive ones on 2026-09-15 (D18).
    Connector("arxiv", arxiv.search, arxiv.MAX_RESULTS, page_gap=3.0, host=_host(arxiv.QUERY_URL)),
    Connector("biorxiv", biorxiv.search, biorxiv.MAX_RESULTS, "OPENALEX_API_KEY", paging="cursor",  # searched through OpenAlex
              host=_host(openalex.WORKS_URL)),
    Connector("pubmed", pubmed.search, pubmed.MAX_RESULTS, "NCBI_API_KEY", host=_host(pubmed.BASE_URL)),
    Connector("ieee_xplore", ieee_xplore.search, ieee_xplore.MAX_RESULTS, "IEEE_API_KEY", key_required=True,
              host=_host(ieee_xplore.SEARCH_URL)),
    Connector("scopus", scopus.search, scopus.MAX_RESULTS, "SCOPUS_API_KEY", key_required=True,
              sw_searchable=False, host=_host(scopus.SEARCH_URL)),  # sw: last abstract source only (D91)
    # CORE and SerpApi are searched by a legacy research only: in the third D88 measurement neither brought a verified
    # work no other source brought, and SerpApi is paid (D93).
    Connector("core", core.search, core.MAX_RESULTS, "CORE_API_KEY", key_required=True, sw_searchable=False,
              host=_host(core.SEARCH_URL)),
    Connector("serpapi", serpapi.search, serpapi.MAX_RESULTS, "SERPAPI_API_KEY", key_required=True, supplementary=True,
              paging="single_page", sw_searchable=False, host=_host(serpapi.SEARCH_URL)),
)}


def _configured(searchable: bool | None = None) -> list[str]:
    return [pid for pid, c in CONNECTORS.items()
            if c.access_mode() != "not_configured" and (searchable is None or c.searchable == searchable)]


def available_providers() -> list[str]:
    """The providers a search may be sent to, in display order."""
    return _configured(searchable=True)


def verification_providers() -> list[str]:
    """Configured connectors that are never searched: they answer about a record whose DOI is already known (D87)."""
    return _configured(searchable=False)


def configured_providers() -> list[str]:
    """Every connector with the access it needs, searched or not: what a new research holds in its scope."""
    return _configured()


# The connectors source routing took out of the sw search (D93). An sw run from before routing, which searches the
# queries its card showed, still searches them in its own scope revision.
LEFT_BY_ROUTING = frozenset({"core", "serpapi"})


def search_providers(providers: list[str], workflow: str | None, *, routed: bool = True) -> list[str]:
    """The given providers a new query of this workflow may go to, in the order given (D87, D91). `routed` false is an
    sw run from before D93, which still searches CORE and SerpApi."""
    return [p for p in providers if CONNECTORS[p].searchable and (
        workflow != "sw" or CONNECTORS[p].sw_searchable or (not routed and p in LEFT_BY_ROUTING))]


def reading(query: dict[str, Any]) -> Connector:
    """The connector as a read of this query sees it: with the paging and depth of the endpoint the query names.

    A query that names no endpoint — every legacy query, and an sw query stored before D93 — is read by the
    connector's own paging, as it always was.
    """
    connector = CONNECTORS[query["provider_id"]]
    endpoint = query.get("endpoint")
    if endpoint is None:
        return connector
    shape = connector.endpoints[endpoint]
    return replace(connector, paging=shape.paging, max_results=shape.max_results, max_reachable=shape.max_reachable)


def endpoint_options(query: dict[str, Any]) -> dict[str, Any]:
    """The arguments a query that names its endpoint passes to its connector's `search`; none for any other query."""
    return {key: query[key] for key in ("endpoint", "sort") if query.get(key) is not None}


def provider_role(connector: Connector) -> str:
    return "search" if connector.searchable else "verification"

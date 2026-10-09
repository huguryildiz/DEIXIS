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
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit

from deixis.providers import arxiv, biorxiv, core, crossref, ieee_xplore, openalex, pacing, pubmed, scopus, semantic_scholar, serpapi
from deixis.providers import common, lookup
from deixis.providers.common import SearchOutcome
from deixis.providers.contract import ContractViolation, OptionDescriptor
from deixis.providers.query_rules import QuerySyntax


@dataclass(frozen=True)
class Endpoint:
    """Another endpoint of a connector that an sw query can name (D93), and how a read of it pages."""

    paging: str
    max_results: int
    max_reachable: int | None = None
    total: str = "reported"
    options: tuple[str, ...] = ()
    page_gap: float | None = None
    query_syntax: QuerySyntax | None = None


@dataclass(frozen=True)
class CapabilityBinding:
    call: Callable[..., Awaitable[Any]]
    max_batch: int
    accepts_retry_allowance: bool = True
    options: tuple[OptionDescriptor, ...] = ()


def _retry_kwargs(allowance):
    return {} if allowance is None else {"max_rate_limit_retries": allowance}


async def _crossref_lookup(client, identifiers, api_key, contact_email, max_rate_limit_retries):
    answer, outcome = await lookup.crossref_work(client, identifiers[0], contact_email)
    return {identifiers[0]: answer}, outcome


async def _s2_lookup(client, identifiers, api_key, contact_email, max_rate_limit_retries):
    return await lookup.semantic_scholar_batch(client, identifiers, api_key, **_retry_kwargs(max_rate_limit_retries))


async def _scopus_lookup(client, identifiers, api_key, contact_email, max_rate_limit_retries):
    return await lookup.scopus_abstracts(client, list(identifiers), api_key, **_retry_kwargs(max_rate_limit_retries))


async def _openalex_lookup(client, identifiers, api_key, contact_email, max_rate_limit_retries):
    return await openalex.works_by_ids(client, identifiers, api_key, contact_email, **_retry_kwargs(max_rate_limit_retries))


async def _openalex_citing(client, work_id, cursor, limit, api_key, contact_email, max_rate_limit_retries, **options):
    return await openalex.citing_works(client, work_id, cursor, limit, api_key, contact_email,
                                     **_retry_kwargs(max_rate_limit_retries), **options)


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
    options: tuple[str, ...] = ()
    # The host name a search request goes to, taken from the URL the module sends it to. Two connectors that share one
    # are read one request at a time between them (D89): bioRxiv is searched through OpenAlex.
    host: str = ""
    # What a new sw query compiled for this connector names besides its text: Semantic Scholar's bulk endpoint and its
    # sort (D93). The query carries it, so a resumed run reads the endpoint its stored query names, and a query stored
    # before D93, which names none, is read as it was (`reading`).
    sw_query: dict[str, Any] = field(default_factory=dict)
    endpoints: dict[str, Endpoint] = field(default_factory=dict)
    requests_per_search: int = 1
    adapter_revision: int = 1
    lineage: str | None = None
    total: str = "reported"
    # Only overrides of common.send's defaults and local pacing metadata; descriptive in B1.
    retry: dict[str, Any] = field(default_factory=dict)
    display_name: str | None = None
    query_syntax: QuerySyntax | None = None
    capabilities: Mapping[str, CapabilityBinding] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "capabilities", MappingProxyType(dict(self.capabilities)))

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
              sw_options={"reference_count": True, "references": True}, options=("sort", "publication_date"),
              host=_host(openalex.WORKS_URL), adapter_revision=3,
              endpoints={"semantic": Endpoint("single_page", 50, 50,
                         options=("reference_count", "references"), query_syntax=QuerySyntax("plain"))},
              capabilities={"id_lookup": CapabilityBinding(_openalex_lookup, openalex.MAX_IDS_PER_REQUEST),
                            "citing_works": CapabilityBinding(_openalex_citing, openalex.MAX_RESULTS,
                                options=(OptionDescriptor("sort", "str", None),
                                         OptionDescriptor("publication_date", "bool", None)))},
              display_name="OpenAlex", query_syntax=QuerySyntax(boolean_checks=True)),
    # Semantic Scholar's relevance search serves `offset + limit` up to 1,000 and refuses a deeper page. An sw query
    # goes to the bulk endpoint instead: up to 1,000 papers a call, continued by a token (D93).
    Connector("semantic_scholar", semantic_scholar.search, semantic_scholar.MAX_RESULTS, "S2_API_KEY", max_reachable=1000,
              host=_host(semantic_scholar.SEARCH_URL), adapter_revision=2,
              capabilities={"doi_lookup": CapabilityBinding(_s2_lookup, 500)},
              sw_query={"endpoint": semantic_scholar.BULK_ENDPOINT, "sort": semantic_scholar.BULK_SORT},
              endpoints={semantic_scholar.BULK_ENDPOINT: Endpoint("cursor", semantic_scholar.BULK_MAX_RESULTS,
                                                               total="estimated", options=("sort",),
                                                               query_syntax=QuerySyntax("bulk"))},
              retry={"unstated_wait": semantic_scholar.UNSTATED_RATE_LIMIT_WAIT,
                     "min_interval": pacing.SEMANTIC_SCHOLAR_PACER.interval_seconds,
                     "shared_gate": "SEMANTIC_SCHOLAR_PACER"},
              display_name="Semantic Scholar", query_syntax=QuerySyntax("plain")),
    Connector("crossref", crossref.search, crossref.MAX_RESULTS, searchable=False,  # verification only (D87)
              host=_host(crossref.WORKS_URL), adapter_revision=2,
              capabilities={"doi_lookup": CapabilityBinding(_crossref_lookup, 1, False)},
              display_name="Crossref", query_syntax=QuerySyntax("plain")),
    # arXiv asks for three seconds between requests and refused consecutive ones on 2026-09-15 (D18).
    Connector("arxiv", arxiv.search, arxiv.MAX_RESULTS, page_gap=3.0, host=_host(arxiv.QUERY_URL), adapter_revision=2,
              retry={"rate_limit_statuses": arxiv.RATE_LIMIT_STATUSES,
                     "unstated_wait": arxiv.UNSTATED_RATE_LIMIT_WAIT,
                     "max_retry_wait": arxiv.MAX_RATE_LIMIT_WAIT,
                     "min_interval": arxiv.MIN_INTERVAL_SECONDS},
              display_name="arXiv", query_syntax=QuerySyntax("fielded", operand_prefix="abs:")),
    Connector("biorxiv", biorxiv.search, biorxiv.MAX_RESULTS, "OPENALEX_API_KEY", paging="cursor",  # searched through OpenAlex
              host=_host(openalex.WORKS_URL), lineage="openalex", adapter_revision=2,
              display_name="bioRxiv", query_syntax=QuerySyntax(boolean_checks=True)),
    # ESearch followed by EFetch; both have their own bounded HTTP retries.
    Connector("pubmed", pubmed.search, pubmed.MAX_RESULTS, "NCBI_API_KEY", host=_host(pubmed.BASE_URL), requests_per_search=2, adapter_revision=2,
              display_name="PubMed", query_syntax=QuerySyntax(operand_suffix="[Title/Abstract]")),
    Connector("ieee_xplore", ieee_xplore.search, ieee_xplore.MAX_RESULTS, "IEEE_API_KEY", key_required=True,
              host=_host(ieee_xplore.SEARCH_URL), adapter_revision=2, display_name="IEEE Xplore",
              query_syntax=QuerySyntax(boolean_checks=True, unbalanced_suffix=" (it returns zero records instead of an error)")),
    Connector("scopus", scopus.search, scopus.MAX_RESULTS, "SCOPUS_API_KEY", key_required=True,
              sw_searchable=False, host=_host(scopus.SEARCH_URL), adapter_revision=2, display_name="Scopus",
              capabilities={"doi_lookup": CapabilityBinding(_scopus_lookup, lookup.SCOPUS_LOOKUP_BATCH)},
              query_syntax=QuerySyntax("field_group", wrapper="TITLE-ABS-KEY")),  # sw: last abstract source only (D91)
    # CORE and SerpApi are searched by a legacy research only: in the third D88 measurement neither brought a verified
    # work no other source brought, and SerpApi is paid (D93).
    Connector("core", core.search, core.MAX_RESULTS, "CORE_API_KEY", key_required=True, sw_searchable=False,
              host=_host(core.SEARCH_URL), adapter_revision=2, display_name="CORE",
              query_syntax=QuerySyntax(boolean_checks=True, extra_rules="field_phrase",
                                       unbalanced_suffix=" (it returns other records instead of an error)")),
    Connector("serpapi", serpapi.search, serpapi.MAX_RESULTS, "SERPAPI_API_KEY", key_required=True, supplementary=True,
              paging="single_page", sw_searchable=False, host=_host(serpapi.SEARCH_URL), total="estimated", adapter_revision=2,
              retry={"timeout": 60.0}, display_name="SerpApi", query_syntax=QuerySyntax("scholar")),  # serpapi.py:68 explicitly passes timeout=60.0 to send.
)}


def resolve_query_syntax(provider_id: str, endpoint: str | None = None, *, strict: bool = True) -> QuerySyntax:
    """Resolve query policy; only historical module-level rule checks are lenient."""
    connector = CONNECTORS[provider_id]
    if endpoint is None:
        declaration = connector.query_syntax
    elif endpoint in connector.endpoints:
        declaration = connector.endpoints[endpoint].query_syntax
    elif strict:
        raise ContractViolation(f"{provider_id}: undeclared endpoint {endpoint!r}")
    else:
        declaration = connector.query_syntax
    if declaration is None:
        raise ContractViolation(f"{provider_id}/{endpoint!r}: missing query declaration")
    if declaration.kind == "plain":
        return replace(declaration, display_name=connector.display_name or provider_id)
    return declaration


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

"""Scholarly search connectors: identity, credentials and result limits.

Order is the order providers are listed to the model and in the UI. A connector whose key is required but not
configured is listed as `not_configured` and not enabled for new researches. Key values are read from the environment
at call time and never stored.

A connector has one of two roles: a searched source, or a verification source that is only asked about a record whose
DOI is already known. `searchable` carries that, and it is the only thing any caller reads to decide whether a
query may go there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit

from deixis.keys import key_verification
from deixis.providers import arxiv, biorxiv, core, crossref, ieee_xplore, openalex, pacing, pubmed, scopus, semantic_scholar, serpapi
from deixis.providers import common, lookup
from deixis.providers.common import SearchOutcome
from deixis.providers.contract import ContractViolation, OptionDescriptor
from deixis.providers.query_rules import QuerySyntax


@dataclass(frozen=True)
class Endpoint:
    """Another endpoint of a connector that a search query can name, and how a read of it pages."""

    paging: str
    max_results: int
    max_reachable: int | None = None
    total: str = "reported"
    options: tuple[str, ...] = ()
    page_gap: float | None = None
    query_syntax: QuerySyntax | None = None
    retry: dict[str, Any] | None = None  # this endpoint's own retry fields over the connector's
    # Requests one search of this endpoint may send, over the connector's own count: Semantic Scholar's snippet
    # search looks the works its snippets came from up in a second request. It is an upper bound, not a promise — a
    # snippet search that finds nothing sends no lookup — and every reader that goes through `reading()` sees it, so
    # the request allowance and the quota reserve are both counted for the endpoint the query names.
    requests_per_search: int | None = None
    # Which bound this endpoint's own route takes for a research's date scope, where it takes one: an endpoint
    # names its own form and inherits none, because two routes of one provider rarely agree on it.
    date_filter: str | None = None


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
    # DOI is already known — its metadata, its links — and is never asked to find records. The queries are
    # compiled from this flag alone, so neither the flow nor the compiler names a provider (slice 05).
    searchable: bool = True
    # Whether a new query is compiled for this connector. Scopus is only the last abstract source, and only on an
    # institutional network; CORE and SerpApi were taken out of the search. A query a run already stored
    # is still read: `searchable` alone decides that, so a resumed run searches the queries its protocol names.
    sw_searchable: bool = True
    # Whether this connector is searched as an index of its own, on a depth that pays for a second independent
    # index, rather than because the question's own field distribution points at it. It is not `sw_searchable`: a
    # broad index gets a compiled query and that depth's own request, and nothing else that reads a searched
    # provider list — candidate search, watch units, the model's provider list, the research's scope view — is
    # given it.
    broad_index: bool = False
    # Which bound this connector's search takes for a research's date scope, so the scope travels **with** the
    # request: `works_filter` is OpenAlex's own filter syntax, `year_range` the `<min>-<max>` string Semantic
    # Scholar's bulk search and PubMed's ESearch both take (`date_scope.provider_bound`). None means its search
    # takes no bound, so it is searched unbounded and the request records that; filtering an answer afterwards
    # cannot give back the places the out-of-scope records took on the first page.
    date_filter: str | None = None
    # How a search query reads its pages (slice 04c): a provider-issued `cursor`, a record `offset`, or one page only.
    paging: str = "offset"
    max_reachable: int | None = None  # the deepest record the provider serves, when that is below the read limit
    page_gap: float = 0.0  # seconds to wait between two pages of the same query
    # Extra arguments a paged read passes to `search`, so the flow never names a provider to decide what to ask
    # for (slice 05).
    sw_options: dict[str, Any] = field(default_factory=dict)
    options: tuple[str, ...] = ()
    # The host name a search request goes to, taken from the URL the module sends it to. Two connectors that share one
    # are read one request at a time between them: bioRxiv is searched through OpenAlex.
    host: str = ""
    # What a new query compiled for this connector names besides its text: Semantic Scholar's bulk endpoint and its
    # sort. The query carries it, so a resumed run reads the endpoint its stored query names, and a query stored
    # before that change, which names none, is read as it was (`reading`).
    sw_query: dict[str, Any] = field(default_factory=dict)
    # The sorting setting this connector's adapter sends on every search whatever the query names. Recorded with the
    # search run beside the query's own setting, so a reader can tell a relevance-ordered list from one ordered by
    # date or citation count without reading the adapter. None: the adapter sends none and the provider answers in its
    # own order for that request. It is not part of the connector contract and no request reads it.
    fixed_sort: str | None = None
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
        # A key no header can carry (from the shell or .env) counts as no key: the source is not configured, nothing raises.
        value = (os.environ.get(self.key_env) or None) if self.key_env else None
        return value if value is None or key_verification.is_valid_key(value) else None

    def key_broken(self) -> bool:
        """A key is set but no header can carry it, so the source runs as if none were set; the card says so."""
        value = os.environ.get(self.key_env) if self.key_env else None
        return bool(value) and not key_verification.is_valid_key(value)

    def access_mode(self) -> str:
        if self.api_key():
            return "api_key"
        return "not_configured" if self.key_required else "keyless"


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


CONNECTORS = {c.provider_id: c for c in (
    Connector("openalex", openalex.search_works, openalex.MAX_RESULTS, "OPENALEX_API_KEY", paging="cursor",
              date_filter="works_filter",
              sw_options={"reference_count": True, "references": True}, options=("sort", "publication_date", "works_filter"),
              host=_host(openalex.WORKS_URL), adapter_revision=4,
              endpoints={"semantic": Endpoint("single_page", 50, 50,
                         # `works_filter` is this route's own filter: a research's date scope travels with the
                         # request, since the semantic route takes `publication_year` and not the date filters.
                         options=("reference_count", "references", "works_filter"), date_filter="works_filter",
                         query_syntax=QuerySyntax("plain"),
                         retry={"min_interval": openalex.SEMANTIC_PACER.interval_seconds,
                                "shared_gate": "openalex.SEMANTIC_PACER"}),
                         # The plain `search=` route: one page, no cursor and no `sort` option, so its list is
                         # stored without a sort and is read as relevance-ordered. It takes the keyword route's
                         # date filter, as both are `/works` list searches.
                         openalex.PLAIN_ENDPOINT: Endpoint("single_page", openalex.MAX_RESULTS, openalex.MAX_RESULTS,
                         options=("reference_count", "references", "works_filter"), date_filter="works_filter",
                         query_syntax=QuerySyntax("plain"))},
              capabilities={"id_lookup": CapabilityBinding(_openalex_lookup, openalex.MAX_IDS_PER_REQUEST),
                            "citing_works": CapabilityBinding(_openalex_citing, openalex.MAX_RESULTS,
                                options=(OptionDescriptor("sort", "str", None),
                                         OptionDescriptor("publication_date", "bool", None),
                                         OptionDescriptor("works_filter", "str", None)))},
              display_name="OpenAlex", query_syntax=QuerySyntax(boolean_checks=True)),
    # Semantic Scholar's relevance search serves `offset + limit` up to 1,000 and refuses a deeper page. A search query
    # goes to the bulk endpoint instead: up to 1,000 papers a call, continued by a token.
    Connector("semantic_scholar", semantic_scholar.search, semantic_scholar.MAX_RESULTS, "S2_API_KEY", max_reachable=1000,
              host=_host(semantic_scholar.SEARCH_URL), adapter_revision=3,
              capabilities={"doi_lookup": CapabilityBinding(_s2_lookup, 500)},
              sw_query={"endpoint": semantic_scholar.BULK_ENDPOINT, "sort": semantic_scholar.BULK_SORT},
              endpoints={semantic_scholar.BULK_ENDPOINT: Endpoint("cursor", semantic_scholar.BULK_MAX_RESULTS,
                                                               total="estimated", options=("sort", "year_range"),
                                                               date_filter="year_range",
                                                               query_syntax=QuerySyntax("bulk")),
                         # Passages this provider found, and the works they came from: one search, then one batch
                         # lookup. The reply is one page and names no cursor, and its `provider_total` is how many
                         # snippets came back, not an estimate of a result set.
                         semantic_scholar.SNIPPET_ENDPOINT: Endpoint(
                             "single_page", semantic_scholar.SNIPPET_MAX_RESULTS, requests_per_search=2,
                             query_syntax=QuerySyntax("plain"))},
              retry={"unstated_wait": semantic_scholar.UNSTATED_RATE_LIMIT_WAIT,
                     "min_interval": pacing.SEMANTIC_SCHOLAR_PACER.interval_seconds,
                     "shared_gate": "SEMANTIC_SCHOLAR_PACER"},
              display_name="Semantic Scholar", query_syntax=QuerySyntax("plain")),
    Connector("crossref", crossref.search, crossref.MAX_RESULTS, searchable=False,  # verification only
              host=_host(crossref.WORKS_URL), adapter_revision=2,
              capabilities={"doi_lookup": CapabilityBinding(_crossref_lookup, 1, False)},
              display_name="Crossref", query_syntax=QuerySyntax("plain")),
    # arXiv asks for three seconds between requests and refused consecutive ones on 2026-09-15.
    Connector("arxiv", arxiv.search, arxiv.MAX_RESULTS, page_gap=3.0, host=_host(arxiv.QUERY_URL), adapter_revision=2,
              retry={"rate_limit_statuses": arxiv.RATE_LIMIT_STATUSES,
                     "unstated_wait": arxiv.UNSTATED_RATE_LIMIT_WAIT,
                     "max_retry_wait": arxiv.MAX_RATE_LIMIT_WAIT,
                     "min_interval": arxiv.MIN_INTERVAL_SECONDS},
              display_name="arXiv", query_syntax=QuerySyntax("fielded", operand_prefix="abs:")),
    Connector("biorxiv", biorxiv.search, biorxiv.MAX_RESULTS, "OPENALEX_API_KEY", paging="cursor",  # searched through OpenAlex
              host=_host(openalex.WORKS_URL), lineage="openalex", adapter_revision=3, date_filter="works_filter",
              display_name="bioRxiv", query_syntax=QuerySyntax(boolean_checks=True)),
    # ESearch followed by EFetch; both have their own bounded HTTP retries.
    Connector("pubmed", pubmed.search, pubmed.MAX_RESULTS, "NCBI_API_KEY", host=_host(pubmed.BASE_URL), requests_per_search=2, adapter_revision=3,
              fixed_sort=pubmed.FIXED_SORT, options=("year_range",), date_filter="year_range",
              display_name="PubMed", query_syntax=QuerySyntax(operand_suffix="[Title/Abstract]")),
    Connector("ieee_xplore", ieee_xplore.search, ieee_xplore.MAX_RESULTS, "IEEE_API_KEY", key_required=True,
              host=_host(ieee_xplore.SEARCH_URL), adapter_revision=2, display_name="IEEE Xplore",
              query_syntax=QuerySyntax(boolean_checks=True, unbalanced_suffix=" (it returns zero records instead of an error)")),
    # Searched as the second independent index of a depth that pays for one (`broad_index`), and asked about a
    # known DOI as the last abstract source. The search asks for the view that carries abstracts; a network
    # without the entitlement answers 401 and the page is recorded with that status.
    Connector("scopus", scopus.search, scopus.MAX_RESULTS, "SCOPUS_API_KEY", key_required=True,
              sw_searchable=False, broad_index=True, sw_options={"view": scopus.COMPLETE_VIEW},
              host=_host(scopus.SEARCH_URL), adapter_revision=3, display_name="Scopus",
              fixed_sort=scopus.FIXED_SORT,
              capabilities={"doi_lookup": CapabilityBinding(_scopus_lookup, lookup.SCOPUS_LOOKUP_BATCH)},
              query_syntax=QuerySyntax("field_group", wrapper="TITLE-ABS-KEY")),
    # CORE and SerpApi get no new query: in the third reranker measurement neither brought a verified work no other
    # source
    # brought, and SerpApi is paid.
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


def verification_providers() -> list[str]:
    """Configured connectors that are never searched: they answer about a record whose DOI is already known."""
    return _configured(searchable=False)


def configured_providers() -> list[str]:
    """Every connector with the access it needs, searched or not: what a new research holds in its scope."""
    return _configured()


def broad_index_providers() -> list[str]:
    """The connectors searched as a depth's second independent index (`broad_index`), in registry order."""
    return [pid for pid, connector in CONNECTORS.items() if connector.broad_index]


def search_providers(providers: list[str], *, broad: bool = False) -> list[str]:
    """The given providers a new query may go to, in the order given.

    `broad` also admits a connector that is searched only as a depth's second independent index
    (`broad_index`). Only the compilers of a discovery run's own first-round queries pass it: every other
    reader of a searched provider list asks a question a broad index is not part of.
    """
    return [p for p in providers if CONNECTORS[p].searchable
            and (CONNECTORS[p].sw_searchable or (broad and CONNECTORS[p].broad_index))]


def reading(query: dict[str, Any]) -> Connector:
    """The connector as a read of this query sees it: with the paging and depth of the endpoint the query names.

    A query that names no endpoint is read by the connector's own paging.
    """
    connector = CONNECTORS[query["provider_id"]]
    endpoint = query.get("endpoint")
    if endpoint is None:
        return connector
    shape = connector.endpoints[endpoint]
    return replace(connector, paging=shape.paging, max_results=shape.max_results, max_reachable=shape.max_reachable,
                   requests_per_search=shape.requests_per_search if shape.requests_per_search is not None
                   else connector.requests_per_search)


def endpoint_options(query: dict[str, Any]) -> dict[str, Any]:
    """The arguments a query that names its endpoint, sort or bound passes to its connector's `search`: a statement
    research's OpenAlex author query carries `works_filter`, and a bounded research's request carries its own date
    bound. None for any other query."""
    return {key: query[key] for key in ("endpoint", "sort", "works_filter", "year_range")
            if query.get(key) is not None}


def date_bound_form(query: dict[str, Any]) -> str | None:
    """Which bound this request's own route takes for a date scope, or None where it takes none.

    The route decides, not the provider: a connector's own search and each endpoint it offers take their own form,
    and an endpoint inherits none, so a route nobody has checked is read as taking no bound.
    """
    connector = CONNECTORS[query["provider_id"]]
    endpoint = query.get("endpoint")
    return connector.date_filter if endpoint is None else connector.endpoints[endpoint].date_filter


def date_filter_providers() -> list[str]:
    """The connectors with a route that takes a research's date scope with the request (`date_filter`)."""
    return [pid for pid, connector in CONNECTORS.items()
            if connector.date_filter or any(shape.date_filter for shape in connector.endpoints.values())]


def effective_sort(query: dict[str, Any]) -> str | None:
    """The sorting setting this request carries: the one the query names, else the one its connector always sends.

    None means the request names none and the provider answers in its own order for it — for a request carrying a
    search term, that order is the provider's own relevance order.
    """
    named = query.get("sort")
    if named is not None:
        return named
    connector = CONNECTORS.get(query.get("provider_id"))
    return connector.fixed_sort if connector is not None else None


# The sorting settings that are a provider's own relevance order. PubMed and Scopus name one on every request, so a
# list of theirs carries a setting although it is relevance-ordered; a request that names none is relevance-ordered
# too (above). Any other name (a date or citation-count order) is not, and neither is a name nothing here knows.
RELEVANCE_SORTS = (pubmed.FIXED_SORT, scopus.FIXED_SORT)


def relevance_ordered(sort: str | None) -> bool:
    """Whether a search run's stored sorting setting means the provider answered in relevance order."""
    return sort is None or sort in RELEVANCE_SORTS


def provider_role(connector: Connector) -> str:
    return "search" if connector.searchable else "verification"

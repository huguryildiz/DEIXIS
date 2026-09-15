"""Scholarly search connectors: identity, credentials and result limits.

Order is the order providers are listed to the model and in the UI. A connector whose key is required but not
configured is listed as `not_configured` and not enabled for new researches. Key values are read from the environment
at call time and never stored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Awaitable, Callable

from deixis.providers import arxiv, biorxiv, core, crossref, ieee_xplore, openalex, scopus, semantic_scholar, serpapi
from deixis.providers.common import SearchOutcome


@dataclass(frozen=True)
class Connector:
    provider_id: str
    search: Callable[..., Awaitable[SearchOutcome]]
    max_results: int
    key_env: str | None = None
    key_required: bool = False
    supplementary: bool = False  # adds coverage beside direct providers; never used in place of one

    def api_key(self) -> str | None:
        return (os.environ.get(self.key_env) or None) if self.key_env else None

    def access_mode(self) -> str:
        if self.api_key():
            return "api_key"
        return "not_configured" if self.key_required else "keyless"


CONNECTORS = {c.provider_id: c for c in (
    Connector("openalex", openalex.search_works, openalex.MAX_RESULTS, "OPENALEX_API_KEY"),
    Connector("semantic_scholar", semantic_scholar.search, semantic_scholar.MAX_RESULTS, "S2_API_KEY"),
    Connector("crossref", crossref.search, crossref.MAX_RESULTS),
    Connector("arxiv", arxiv.search, arxiv.MAX_RESULTS),
    Connector("biorxiv", biorxiv.search, biorxiv.MAX_RESULTS, "OPENALEX_API_KEY"),  # searched through OpenAlex
    Connector("ieee_xplore", ieee_xplore.search, ieee_xplore.MAX_RESULTS, "IEEE_API_KEY", key_required=True),
    Connector("scopus", scopus.search, scopus.MAX_RESULTS, "SCOPUS_API_KEY", key_required=True),
    Connector("core", core.search, core.MAX_RESULTS, "CORE_API_KEY", key_required=True),
    Connector("serpapi", serpapi.search, serpapi.MAX_RESULTS, "SERPAPI_API_KEY", key_required=True, supplementary=True),
)}


def available_providers() -> list[str]:
    return [pid for pid, c in CONNECTORS.items() if c.access_mode() != "not_configured"]

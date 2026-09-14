"""bioRxiv search through OpenAlex, limited to works with a bioRxiv location.

bioRxiv's own API (api.biorxiv.org) has no keyword search: probed on 2026-09-14, `/search/...` answered 404 and
`/details` looks records up by DOI or date only. OpenAlex indexes bioRxiv as source S4306402567 ("bioRxiv (Cold Spring
Harbor Laboratory)", 343,487 works). Filtering on any location rather than the primary one also keeps preprints whose
work OpenAlex now lists under the later journal version (`"quorum sensing" AND (optimization OR control)`: 272 against
268). Queries use OpenAlex syntax and rules; records are OpenAlex works recorded under provider `biorxiv`, so the same
DOI found by the OpenAlex connector merges into one source.
"""

from __future__ import annotations

import httpx

from deixis.providers import openalex
from deixis.providers.common import SearchOutcome

PROVIDER_ID = "biorxiv"
SOURCE_ID = "S4306402567"
WORKS_FILTER = f"locations.source.id:{SOURCE_ID}"
MAX_RESULTS = openalex.MAX_RESULTS


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None) -> SearchOutcome:
    return await openalex.search_works(client, query, limit, api_key, contact_email, works_filter=WORKS_FILTER)

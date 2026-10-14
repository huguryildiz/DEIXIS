"""The Test on a keyless source's Settings sheet (P5, D33): one request, and whether the service answered.

The request is a one-record read from the endpoint the connector searches, sent without a key and with the contact
email: in the User-Agent on every request, and also as the parameter the service asks for (OpenAlex and Crossref
`mailto`, PubMed `email`). Only the reply's arrival is read: its HTTP status, or why none came (time-out, no
connection). The body is not read, so the result says nothing about search results, quota or record quality. One
request, no retry; Semantic Scholar's goes through the process-wide gate every Semantic Scholar request takes (D67).
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from deixis.documents.fetch import user_agent
from deixis.providers import arxiv, biorxiv, crossref, openalex, pubmed, semantic_scholar
from deixis.providers.pacing import SEMANTIC_SCHOLAR_PACER
from deixis.storage.db import now

TIMEOUT_SECONDS = 20.0


def _mailto(email: str | None) -> dict[str, str]:
    return {"mailto": email} if email else {}


# provider id -> (URL, query parameters for the contact email). Every connector that does not require a key is here
# (tests/providers/test_keyless_check.py checks that against the registry).
REQUESTS: dict[str, tuple[str, Callable[[str | None], dict[str, Any]]]] = {
    "openalex": (openalex.WORKS_URL, lambda email: {"per_page": 1, "select": "id", **_mailto(email)}),
    "biorxiv": (openalex.WORKS_URL, lambda email: {"filter": biorxiv.WORKS_FILTER, "per_page": 1, "select": "id", **_mailto(email)}),
    "crossref": (crossref.WORKS_URL, lambda email: {"rows": 1, **_mailto(email)}),
    "arxiv": (arxiv.QUERY_URL, lambda email: {"search_query": "all:test", "max_results": 1}),
    "pubmed": (pubmed.SEARCH_URL, lambda email: {"db": "pubmed", "term": "test", "retmax": 1, "tool": "DEIXIS",
                                                 **({"email": email} if email else {})}),
    "semantic_scholar": (semantic_scholar.SEARCH_URL, lambda email: {"query": "test", "limit": 1, "fields": "title"}),
}


async def check(client: httpx.AsyncClient, provider_id: str, email: str | None) -> dict[str, Any]:
    url, params = REQUESTS[provider_id]
    sent = {"provider": provider_id, "contact_email_sent": bool(email), "timeout_seconds": TIMEOUT_SECONDS}

    async def attempt() -> int:
        # Streamed and closed once the status line and headers are in: the body is never read, so a slow or broken
        # body cannot turn a reply that came into "did not answer".
        async with client.stream("GET", url, params=params(email), headers={"User-Agent": user_agent(email)},
                                 timeout=TIMEOUT_SECONDS) as response:
            return response.status_code

    try:
        status = await (SEMANTIC_SCHOLAR_PACER.run(attempt) if provider_id == "semantic_scholar" else attempt())
    except httpx.TimeoutException as exc:
        return sent | {"answered": False, "http_status": None, "failure": "timeout", "error": type(exc).__name__, "checked_at": now()}
    except httpx.ConnectError as exc:
        return sent | {"answered": False, "http_status": None, "failure": "connection", "error": type(exc).__name__, "checked_at": now()}
    except httpx.HTTPError as exc:
        return sent | {"answered": False, "http_status": None, "failure": "other", "error": type(exc).__name__, "checked_at": now()}
    return sent | {"answered": True, "http_status": status, "failure": None, "error": None, "checked_at": now()}

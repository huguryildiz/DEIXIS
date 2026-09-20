"""Shared record shape, outcome statuses and HTTP handling for scholarly search providers.

Every adapter returns a SearchOutcome with the same status vocabulary (`completed`, `zero_results`, `auth_required`,
`entitlement_missing`, `rate_limited`, `timeout`, `parse_error`, `failed`) and a secret-free request description.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from deixis.providers.pacing import SEMANTIC_SCHOLAR_PACER

MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 10.0  # a longer provider wait pauses the run instead of blocking it

FIRST_PAGE = "*"  # asks a provider for the first page of a paged read; an offset provider reads it as offset 0


@dataclass
class OtherVersion:
    """An open-access copy the provider labels with a different version than the record's primary location."""

    version_label: str
    pdf_url: str
    landing_url: str | None
    venue: str | None


@dataclass
class ProviderRecord:
    provider_record_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    publication_type: str | None
    doi: str | None
    landing_url: str | None
    oa_pdf_url: str | None
    oa_pdf_version: str | None
    version_label: str | None
    abstract: str | None
    abstract_origin: str | None
    identifiers: dict[str, str]
    raw: dict[str, Any] = field(repr=False)
    other_versions: list[OtherVersion] = field(default_factory=list)
    cited_by_count: int | None = None
    # False when the DOI covers several file versions (arXiv's DataCite DOI names every version of a preprint).
    merge_by_doi: bool = True
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None


@dataclass
class SearchOutcome:
    status: str
    delivery_class: str | None
    request_description: str
    access_mode: str
    records: list[ProviderRecord] = field(default_factory=list)
    provider_total: int | None = None
    http_status: int | None = None
    rate_limit: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    raw_payload: dict[str, Any] | None = None
    retries: int = 0
    next_cursor: str | None = None  # what the next page is asked for with; None when the provider has no more


def page_offset(cursor: str | None) -> int:
    """The record this page starts at. A cursor an offset provider never issued is a code error, not a network one."""
    if cursor is None or cursor == FIRST_PAGE:
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        raise ValueError(f"not an offset cursor: {cursor!r}") from None
    if offset < 0:
        raise ValueError(f"not an offset cursor: {cursor!r}")
    return offset


def next_offset(offset: int, read: int, requested: int, provider_total: int | None) -> str | None:
    """Where the next page starts, or None when this page was the last: a short page or the provider's whole total."""
    if read < requested or (provider_total is not None and offset + read >= provider_total):
        return None
    return str(offset + read)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.IGNORECASE).lower() or None


def redact(text: str | None, *secrets: str | None) -> str | None:
    if text is None:
        return None
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def year_of(value: Any) -> int | None:
    match = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(value or ""))
    return int(match.group(1)) if match else None


async def send(client: httpx.AsyncClient, url: str, params: dict[str, Any], headers: dict[str, str], description: str,
               access_mode: str, rate_headers: tuple[str, ...] = (), secrets: tuple[str | None, ...] = (),
               timeout: float = 30.0, retry_rate_limit: bool = True, unstated_wait: float = 3.0,
               max_retry_wait: float = MAX_RETRY_WAIT_SECONDS) -> tuple[httpx.Response | None, SearchOutcome]:
    """One GET with bounded retries on 429. Returns the 200 response, or None with the classified failure outcome.

    A 429 is retried at most MAX_RATE_LIMIT_RETRIES times when the provider's wait is short or unstated (then
    `unstated_wait` seconds times the retry number, bounded by `max_retry_wait`); each retry is a
    separate request and is counted by the caller through `outcome.retries`. Another 4xx means the provider rejected the
    request; a 5xx leaves it unknown whether the request was processed.
    """
    retries = 0
    while True:
        try:
            if urlsplit(url).hostname == "api.semanticscholar.org":
                response = await SEMANTIC_SCHOLAR_PACER.run(
                    lambda: client.get(url, params=params, headers=headers, timeout=timeout)
                )
            else:
                response = await client.get(url, params=params, headers=headers, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return None, SearchOutcome("failed", "before_send", description, access_mode, error=type(exc).__name__, retries=retries)
        except httpx.TimeoutException as exc:
            return None, SearchOutcome("timeout", "after_send_unknown", description, access_mode, error=type(exc).__name__, retries=retries)
        except httpx.HTTPError as exc:
            return None, SearchOutcome("failed", "after_send_unknown", description, access_mode, error=type(exc).__name__, retries=retries)
        rate = {h: response.headers[h] for h in (*rate_headers, "retry-after") if h in response.headers}
        base = dict(request_description=description, access_mode=access_mode, http_status=response.status_code, rate_limit=rate,
                    retries=retries)
        if response.status_code == 429:
            wait = _retry_wait(response.headers.get("retry-after"), retries, unstated_wait, max_retry_wait)
            if retry_rate_limit and retries < MAX_RATE_LIMIT_RETRIES and wait is not None:
                retries += 1
                await asyncio.sleep(wait)
                continue
            return None, SearchOutcome("rate_limited", "rejected_not_executed", **base,
                                       error=redact(response.text[:300], *secrets) or "429 Too Many Requests")
        if response.status_code in (401, 403):
            status = "entitlement_missing" if access_mode == "api_key" else "auth_required"
            return None, SearchOutcome(status, "rejected_not_executed", **base, error=redact(response.text[:300], *secrets))
        if response.status_code != 200:
            delivery = "rejected_not_executed" if 400 <= response.status_code < 500 else "after_send_unknown"
            return None, SearchOutcome("failed", delivery, **base, error=redact(response.text[:300], *secrets))
        return response, SearchOutcome("completed", None, **base)


def _retry_wait(retry_after: str | None, retries: int, unstated_wait: float,
                max_retry_wait: float = MAX_RETRY_WAIT_SECONDS) -> float | None:
    if retry_after is None:
        return unstated_wait * (retries + 1)
    try:
        wait = float(retry_after)
    except ValueError:
        return None
    return wait if wait <= max_retry_wait else None

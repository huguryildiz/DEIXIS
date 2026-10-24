"""One page of a search query's read and the requests one query may send (slice 04c, D89).

Shared by the flow, which records a page, and the fast search, which sends it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES, PROVIDER_WAIT, SW_READ_LIMIT
from deixis.providers.registry import reading


@dataclass(frozen=True)
class Page:
    """One page of an sw query's read; each gets its own step, search run and stored payload (slice 04c)."""

    number: int              # 0 for the first page
    cursor: str              # FIRST_PAGE or the previous page's next_cursor
    read_before: int         # records this query read on earlier pages
    known_total: int | None  # the provider total an earlier page reported
    read_limit: int          # records this effort reads per query (D88)
    rate_limit_retries: int  # times this effort waits out a 429 on this page (D88); 0 ends the read instead
    query_key: str           # the query's first step key, which its own request count is kept under (D89)
    allowance: int           # requests this query may send in this run (`page_allowance`, D89)


def page_allowance(query: dict[str, Any], effort: str, budget: dict[str, Any]) -> int:
    """Requests one sw query may send, derived before its read starts from the query and the run alone (D89).

    The query is allowed the pages its provider needs to reach the read limit (or its own reachable depth), and every
    page the bounded retries it may need: a retry is counted as a request. What a retry action adds to the run
    (`retry_provider_requests`, one per failed search it retries) is added to every query's share alike, so the page
    it sends again has room. Nothing here reads another query's count, so the share does not depend on which host
    answered first. Both figures are this research's effort (D88): a lighter effort reads fewer records per query
    and waits out fewer 429s.
    """
    read_limit = SW_READ_LIMIT[effort]
    connector = reading(query)  # the endpoint the query names pages its own way (D93)
    per_page = connector.requests_per_search * (1 + PROVIDER_WAIT[effort]) + MAX_TRANSIENT_NETWORK_RETRIES
    pages = 1 if connector.paging == "single_page" else math.ceil(
        min(read_limit, connector.max_reachable or read_limit) / connector.max_results)
    return pages * per_page + budget.get("retry_provider_requests", 0)

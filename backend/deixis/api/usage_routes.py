"""Usage reads (parity slice S16): OpenAlex budget today (F7) and model calls by role (F8), with a run's provider
requests (P2, D31).

All are read from what the app stored. The model calls are the rows of `model_sessions`, never an estimate; a run's
requests are the rows of `provider_requests`, counting only what went out. The OpenAlex
numbers are the rate-limit headers of the newest stored OpenAlex response since the last daily reset (midnight UTC, when
OpenAlex renews its daily budget); a denominator is given only when OpenAlex sent a limit header with it. The answer says it is the last stored response
(`source`) and when that was (`as_of`); it is not a live reading. Nothing here
writes, asks a provider or starts a run.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import HTTPException, Query, Request

from deixis.domain.rules import LITERATURE_TASKS
from deixis.storage.db import now

ROLES = ("answer", "literature", "reviewer")  # the three roles the Settings page sets a model for
REVIEWER_TASKS = ("answer_review",)
DAY_SECONDS = 86400
# The figure is what OpenAlex said in the last stored response, not a live reading; `as_of` is that response's time.
SOURCE = "last_stored_response"


def role_of(task_type: str) -> str:
    """The Settings role whose model ran this step: the literature model runs the search and reading steps, the reviewer
    model the claim check, and every other step runs on the research (answer) model."""
    if task_type in LITERATURE_TASKS:
        return "literature"
    if task_type in REVIEWER_TASKS:
        return "reviewer"
    return "answer"


def iso(moment: datetime) -> str:
    """The stored timestamp format (storage.db.now): UTC, milliseconds."""
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def month_window(moment: datetime, tz: tzinfo | None = None) -> tuple[str, str]:
    """[start, end) of the calendar month `moment` falls in, in local time, as stored timestamps. `tz` is the local zone;
    None is the machine's own, read per boundary so a daylight-saving change inside the month is honoured."""
    local = moment.astimezone(tz) if tz is not None else moment.astimezone()
    first = (local.year, local.month)
    after = (local.year + (local.month == 12), local.month % 12 + 1)

    def start(year_month: tuple[int, int]) -> str:
        naive = datetime(year_month[0], year_month[1], 1)
        return iso(naive.replace(tzinfo=tz) if tz is not None else naive.astimezone())

    return start(first), start(after)


def usage(counts: dict[str, int]) -> dict[str, Any]:
    """Calls per role, in the Settings order, with each role's share of the total (None while there is no call)."""
    calls = dict.fromkeys(ROLES, 0)
    for task_type, count in counts.items():
        calls[role_of(task_type)] += count
    total = sum(calls.values())
    return {"total": total, "roles": [{"role": role, "calls": calls[role],
                                       "share": calls[role] / total if total else None} for role in ROLES]}


# The hosts whose requests the run's Usage box counts, in its order (P2, D31).
COUNTED_HOSTS = (("openalex", "api.openalex.org"), ("semantic_scholar", "api.semanticscholar.org"))


def requests(counts: dict[str, dict[str, int]] | None) -> dict[str, Any]:
    """The run's requests to OpenAlex and Semantic Scholar from its stored requests: sent, refused among those, and not
    known whether sent (cancelled while out, still out, or out when the process stopped). `recorded` false, with no
    figures, for a run older than the record."""
    if counts is None:
        return {"recorded": False, "providers": None}
    empty = {"sent": 0, "refused": 0, "unknown": 0}
    return {"recorded": True, "providers": [{"provider": provider} | counts.get(host, empty)
                                            for provider, host in COUNTED_HOSTS]}


def _number(value: Any) -> Decimal | None:
    """The finite, non-negative number a header states, or None."""
    try:
        number = Decimal(value.strip()) if isinstance(value, str) else None
    except (InvalidOperation, ValueError):
        return None
    return number if number is not None and number.is_finite() and not number.is_signed() else None


def day_start(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def budget(rows: list[tuple[str, str | None]], moment: datetime) -> dict[str, Any]:
    """OpenAlex's budget today from stored rows (newest first; each is its retrieval time and error_json).

    The newest row that carries a remaining figure wins. The dollar variant is used when present, else the plain header figure, which
    is OpenAlex credits (a search costs several), not requests; credits are never converted to dollars or requests and
    the two units are never mixed. A limit counts only from the same unit. `used_fraction` exists only with a limit.
    """
    since = day_start(moment)
    for retrieved_at, error_json in rows:
        try:
            when = datetime.fromisoformat(retrieved_at)
            headers = json.loads(error_json or "{}").get("rate_limit") or {}
        except (ValueError, TypeError, AttributeError):
            continue
        if when < since or not isinstance(headers, dict):
            continue
        for unit, remaining_key, limit_key in (("usd", "x-ratelimit-remaining-usd", "x-ratelimit-limit-usd"),
                                               ("credits", "x-ratelimit-remaining", "x-ratelimit-limit")):
            remaining = _number(headers.get(remaining_key))
            if remaining is None:
                continue
            limit = _number(headers.get(limit_key))
            seconds = _number(headers.get("x-ratelimit-reset"))
            # The reset header is delta seconds from the response; a missing or beyond-a-day value falls back to the
            # next midnight UTC, as the PDF lookup does (documents/acquisition._reset_at).
            reset = (when + timedelta(seconds=int(seconds)) if seconds is not None and seconds <= DAY_SECONDS
                     else since + timedelta(days=1))
            used = (min(1.0, max(0.0, float((limit - remaining) / limit))) if limit else None)
            return {"provider": "openalex", "unit": unit, "remaining": float(remaining),
                    "limit": float(limit) if limit else None, "used_fraction": used,
                    "reset_at": iso(reset), "as_of": iso(when), "source": SOURCE}
    return {"provider": "openalex", "unit": None, "remaining": None, "limit": None, "used_fraction": None,
            "reset_at": None, "as_of": None, "source": SOURCE}


def register_usage_routes(app) -> None:
    @app.get("/api/openalex/budget-today")
    async def openalex_budget_today(request: Request) -> dict[str, Any]:
        moment = datetime.now(timezone.utc)
        return budget(request.app.state.store.openalex_rate_limit_rows(iso(day_start(moment))), moment)

    @app.get("/api/usage")
    async def get_usage(request: Request, period: Literal["month", "run"] = "month",
                        run_id: str | None = Query(default=None, min_length=1, max_length=200)) -> dict[str, Any]:
        store = request.app.state.store
        if period == "run":
            if run_id is None:
                raise HTTPException(422, "period=run needs run_id")
            if not store.run_exists(run_id):
                raise HTTPException(404, "Unknown run")
            return ({"period": "run", "run_id": run_id, "as_of": now()} | usage(store.model_call_counts(run_id=run_id))
                    | {"requests": requests(store.provider_request_counts(run_id))})
        since, until = month_window(datetime.now(timezone.utc))
        return ({"period": "month", "since": since, "until": until, "as_of": now()}
                | usage(store.model_call_counts(since=since, until=until)))

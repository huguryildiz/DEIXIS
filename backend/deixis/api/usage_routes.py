"""Usage reads (parity slice S16): OpenAlex budget today (F7) and model calls by role (F8), with a run's provider
requests (P2, D31).

The OpenAlex budget is read live from OpenAlex's free `/rate-limit` endpoint when an OpenAlex key is set (the endpoint
needs one and costs no credits; `source` "live"). Without a key, or when that read fails, it falls back to what the app
stored. Everything else is read from what the app stored. The model calls are the rows of `model_sessions`, never an estimate; a run's
requests are the rows of `provider_requests`, counting only what went out. The OpenAlex
numbers are the rate-limit headers of the newest stored OpenAlex response since the last daily reset (midnight UTC, when
OpenAlex renews its daily budget); a denominator is given only when OpenAlex sent a limit header with it. The answer says it is the last stored response
(`source`) and when that was (`as_of`); it is not a live reading. Nothing here
writes or starts a run; only the budget read asks a provider.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from fastapi import HTTPException, Query, Request

from deixis.domain.rules import LITERATURE_TASKS
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import now
from deixis.workflow import spend

ROLES = ("answer", "literature", "reviewer")  # the three roles the Settings page sets a model for
REVIEWER_TASKS = ("answer_review",)
DAY_SECONDS = 86400
# The figure is what OpenAlex said in the last stored response, not a live reading; `as_of` is that response's time.
SOURCE = "last_stored_response"
RATE_LIMIT_URL = "https://api.openalex.org/rate-limit"
LIVE_TIMEOUT = 5.0


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
            # next midnight UTC, as the PDF lookup does (documents/acquisition.budget_reset_at).
            reset = (when + timedelta(seconds=int(seconds)) if seconds is not None and seconds <= DAY_SECONDS
                     else since + timedelta(days=1))
            used = (min(1.0, max(0.0, float((limit - remaining) / limit))) if limit else None)
            return {"provider": "openalex", "unit": unit, "remaining": float(remaining),
                    "limit": float(limit) if limit else None, "used_fraction": used,
                    "reset_at": iso(reset), "as_of": iso(when), "source": SOURCE}
    return {"provider": "openalex", "unit": None, "remaining": None, "limit": None, "used_fraction": None,
            "reset_at": None, "as_of": None, "source": SOURCE}


def _prepaid_expiry(value: Any) -> str | None:
    """OpenAlex writes the prepaid expiry as a JavaScript date string ("Sat Jan 16 2027 11:05:39 GMT+0000 (...)")."""
    try:
        return iso(datetime.strptime(str(value)[:24], "%a %b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc))
    except ValueError:
        return None


def live_budget(body: Any, moment: datetime) -> dict[str, Any] | None:
    """OpenAlex's budget today from its `/rate-limit` answer: the dollar figures when present, else the credit figures
    (never mixed, as in `budget`), plus the prepaid balance bought on top of the daily budget, in the same unit. None
    when the answer carries neither."""
    limits = body.get("rate_limit") if isinstance(body, dict) else None
    if not isinstance(limits, dict):
        return None
    for unit, remaining_key, limit_key, prepaid_key, expiry_key in (
            ("usd", "daily_remaining_usd", "daily_budget_usd", "prepaid_remaining_usd", "prepaid_expires_at"),
            ("credits", "credits_remaining", "credits_limit", "onetime_credits_remaining", "onetime_credits_expires_at")):
        remaining = _number(str(limits.get(remaining_key)))
        if remaining is None:
            continue
        limit = _number(str(limits.get(limit_key)))
        try:
            reset = iso(datetime.fromisoformat(str(limits.get("resets_at")).replace("Z", "+00:00")))
        except ValueError:
            reset = iso(day_start(moment) + timedelta(days=1))
        used = min(1.0, max(0.0, float((limit - remaining) / limit))) if limit else None
        return {"provider": "openalex", "unit": unit, "remaining": float(remaining),
                "limit": float(limit) if limit else None, "used_fraction": used,
                "reset_at": reset, "as_of": iso(moment), "source": "live",
                "prepaid_remaining": float(prepaid) if (prepaid := _number(str(limits.get(prepaid_key)))) is not None else None,
                "prepaid_expires_at": _prepaid_expiry(limits.get(expiry_key)) if prepaid is not None else None}
    return None


async def read_live(client, api_key: str) -> dict[str, Any] | None:
    """Ask OpenAlex for today's budget; None when the request fails or the answer is not usable."""
    try:
        response = await client.get(RATE_LIMIT_URL, params={"api_key": api_key}, timeout=LIVE_TIMEOUT)
        if response.status_code != 200:
            return None
        return live_budget(response.json(), datetime.now(timezone.utc))
    except (httpx.HTTPError, ValueError):
        return None


def month_days(moment: datetime) -> tuple[str, str]:
    """[first day, first day of next month) of the local calendar month, as the spend ledger's day strings."""
    local = moment.astimezone()
    after = (local.year + (local.month == 12), local.month % 12 + 1)
    return f"{local.year:04d}-{local.month:02d}-01", f"{after[0]:04d}-{after[1]:02d}-01"


def month_spend(conn, connection: str, first: str, after: str) -> dict[str, Any]:
    """The spend ledger's estimate for one paid-API connection over [first, after)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS usd, COUNT(cost_usd) AS priced, COALESCE(SUM(cost_usd IS NULL), 0) AS unpriced,"
        " COALESCE(SUM(repriced_at IS NOT NULL), 0) AS repriced, MAX(repriced_price_list) AS repriced_with"
        " FROM spend_ledger WHERE connection = ? AND day >= ? AND day < ?", (connection, first, after)).fetchone()
    return {"estimated_usd": row["usd"], "priced_calls": row["priced"], "unpriced_calls": row["unpriced"],
            "repriced_calls": row["repriced"], "repriced_price_list": row["repriced_with"]}


async def connection_rows(store, adapters: dict[str, Any], moment: datetime) -> list[dict[str, Any]]:
    """One row per model connection a Settings role uses now, plus any paid-API connection with spend this month: what
    it costs (paid by key: this month's estimate) or how much of its own limit is used (a subscription that reports one)."""
    first, after = month_days(moment)
    used: dict[str, list[str]] = {}
    for role in ROLES:
        setting = store.setting(role) or {}
        if role == "reviewer" and not setting.get("model"):
            continue  # no reviewer model: no review runs
        used.setdefault(setting.get("model_connection") or "codex", []).append(role)
    for (connection,) in store.conn.execute(
            "SELECT DISTINCT connection FROM spend_ledger WHERE day >= ? AND day < ?", (first, after)):
        used.setdefault(connection, [])
    rows = []
    for connection, roles in used.items():
        kind = spend.kind_of(connection)
        row: dict[str, Any] = {"connection": connection, "kind": kind, "roles": roles, "spend": None, "quota": None}
        if kind == "api":
            row["spend"] = month_spend(store.conn, connection, first, after)
        elif kind == "subscription" and hasattr(adapter := adapters.get(connection), "quota"):
            row["quota"] = await adapter.quota()
        rows.append(row)
    return rows


def register_usage_routes(app) -> None:
    @app.get("/api/openalex/budget-today")
    async def openalex_budget_today(request: Request) -> dict[str, Any]:
        key = CONNECTORS["openalex"].api_key()
        if key and (live := await read_live(request.app.state.http, key)) is not None:
            return live
        moment = datetime.now(timezone.utc)
        return budget(request.app.state.store.openalex_rate_limit_rows(iso(day_start(moment))), moment)

    @app.get("/api/usage/models")
    async def model_usage(request: Request) -> dict[str, Any]:
        moment = datetime.now(timezone.utc)
        first, _ = month_days(moment)
        return {"as_of": now(), "month_start": first,
                "connections": await connection_rows(request.app.state.store, request.app.state.adapters, moment)}

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

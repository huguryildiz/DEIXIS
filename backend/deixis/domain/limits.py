"""Shared limit signals; unknown 429s retain each caller's bounded retry policy."""
from __future__ import annotations

import json
import re
from typing import Any

QUOTA_CODES = {"insufficient_quota", "quota_exhausted", "daily_limit_exceeded", "credit_balance_exhausted",
               "billing_error", "usagelimitexceeded"}
RATE_CODES = {"rate_limit_exceeded", "rate_limit_error", "ratelimitexceeded", "rate_limit"}
DAILY_TEXT = re.compile(r"per[_ ]?day\b|\bdaily (?:quota|limit)\b", re.I)
WINDOW_TEXT = re.compile(r"\bper[_ ](?:minute|second)\b|per(?:minute|second)\b", re.I)
QUOTA_TEXT = re.compile(r"insufficient_quota|quota_exhausted|daily_limit_exceeded|credit.balance|"
                        r"out of (?:searches|credits)|quota (?:exceeded|exhausted)|\(quota\)", re.I)
RATE_TEXT = re.compile(r"\b(?:429|rate.?limit(?:ed|ing|_error)?|too many requests|resource_exhausted|"
                       r"resource has been exhausted)\b", re.I)


def limit_kind(payload: Any = None, *, status: int | None = None, text: str = "") -> str | None:
    """Daily/account signals win; short windows precede generic quota wording."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            text = f"{text} {payload}"
    codes: set[str] = set()
    messages: list[str] = [text]
    quota_ids: list[str] = []

    def visit(value: Any) -> None:
        nonlocal status
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("code", "type", "reason", "status", "codexErrorInfo") and isinstance(item, str):
                    codes.add(item.lower())
                if key in ("httpStatusCode", "status_code", "status", "code") and isinstance(item, int) and item in (402, 429):
                    status = item
                if key in ("message", "error", "quotaId") and isinstance(item, str):
                    messages.append(item)
                if key == "quotaId" and isinstance(item, str):
                    quota_ids.append(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    description = " ".join(messages)
    # Camel-case quota IDs can continue with a scope suffix after the window (e.g. PerMinutePerProject).
    daily_id = any(re.search(r"per[_ ]?day", quota_id, re.I) for quota_id in quota_ids)
    short_id = any(re.search(r"per[_ ]?(?:minute|second)", quota_id, re.I) for quota_id in quota_ids)
    if status == 402 or codes & QUOTA_CODES or DAILY_TEXT.search(description) or daily_id:
        return "quota_exhausted"
    if codes & RATE_CODES or WINDOW_TEXT.search(description) or short_id:
        return "rate_limited"
    if QUOTA_TEXT.search(description):
        return "quota_exhausted"
    if status == 429 or RATE_TEXT.search(description):
        return "rate_limited"
    return None


def http_limit(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return {"error_kind": limit_kind(payload, status=response.status_code, text=response.text),
            "http_status": response.status_code, "retry_after": response.headers.get("retry-after")}

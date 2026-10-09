"""Shared limit signals; unknown 429s retain each caller's bounded retry policy."""
from __future__ import annotations

import json
import re
import math
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

QUOTA_CODES = {"insufficient_quota", "quota_exhausted", "daily_limit_exceeded", "credit_balance_exhausted",
               "billing_error", "usagelimitexceeded"}
RATE_CODES = {"rate_limit_exceeded", "rate_limit_error", "ratelimitexceeded", "rate_limit"}
INVALID_KEY_TEXT = re.compile(r"API_KEY_INVALID|API key not valid|invalid[_ ]api[_ ]key", re.I)
DAILY_TEXT = re.compile(r"per[_ ]?day\b|\bdaily (?:quota|limit)\b", re.I)
WINDOW_TEXT = re.compile(r"\bper[_ ](?:minute|second)\b|per(?:minute|second)\b", re.I)
QUOTA_TEXT = re.compile(r"insufficient_quota|quota_exhausted|daily_limit_exceeded|credit.balance|"
                        r"out of (?:searches|credits)|quota (?:exceeded|exhausted)|\(quota\)", re.I)
RATE_TEXT = re.compile(r"\b(?:429|rate.?limit(?:ed|ing|_error)?|too many requests|resource_exhausted|"
                       r"resource has been exhausted)\b", re.I)

SERVICE_ERROR_KINDS = frozenset({"quota_exhausted", "rate_limited", "needs_key", "auth_failed",
    "bad_request", "model_unavailable", "not_found", "blocked", "timeout", "service_error", "network", "unknown"})


def service_error_kind(status: int | str | None = None, *, exc: Exception | None = None,
                       payload: Any = None, text: str = "", surface: str = "api") -> str:
    """Classify observed failures without changing retry or delivery semantics."""
    kind = limit_kind(payload, status=status if isinstance(status, int) else None, text=text)
    if kind:
        return kind
    if status in {400, 401, 403} and INVALID_KEY_TEXT.search(f"{text} {json.dumps(payload, default=str) if payload is not None else ''}"):
        return "auth_failed"  # Gemini answers an invalid key with HTTP 400 API_KEY_INVALID
    if status in SERVICE_ERROR_KINDS:
        return str(status)
    if status in {"not_configured", "missing_core_key", "missing_serpapi_key", "missing_contact_email"}:
        return "needs_key"
    if status in {"auth_required", "entitlement_missing", "email_rejected", "authentication_failed"}:
        return "auth_failed"
    if status in {"fetch_blocked_url"}:
        return "blocked"
    description = f"{type(exc).__name__ if exc else ''} {text} {status or ''}"
    if re.search(r"timeout|timed out", description, re.I):
        return "timeout"
    if re.search(r"ConnectError|before_send|fetch_failed", description, re.I):
        return "network"
    if status in {401, 403}:
        return "blocked" if surface == "pdf" else "auth_failed"
    if status in {404, 410} and surface == "pdf":
        return "not_found"
    if status == 404 and surface == "model":
        return "model_unavailable"
    if (isinstance(status, int) and 400 <= status < 500) or status == "invalid_request":
        return "bad_request"
    if (isinstance(status, int) and status >= 500) or status == "parse_error" or "Invalid JSON" in text:
        return "service_error"
    return "unknown"


def retry_at(value: str | None, *, observed_at: datetime | None = None) -> str | None:
    """Retry-After is a retry suggestion, never a promise that quota resets."""
    if not value or len(value) > 128:
        return None
    reference = observed_at or datetime.now(timezone.utc)
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
            seconds = float(value)
            if not math.isfinite(seconds):
                return None
            result = reference + timedelta(seconds=seconds)
        else:
            result = parsedate_to_datetime(value)
            if result.tzinfo is None:
                return None
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def safe_error(text: str | None) -> str | None:
    """Defense at the model boundary; HTTP callers omit untrusted response bodies."""
    if text is None:
        return None
    for name, value in os.environ.items():
        if value and any(part in name.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(value, "<redacted>")
    text = re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;]+", r"\1<redacted>", text)
    text = re.sub(r"\b(?:sk-|AIza)[\w-]+", "<redacted>", text)
    return text


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
    value = response.headers.get("retry-after")
    return {"error_kind": service_error_kind(response.status_code, payload=payload, text=response.text, surface="model"),
            "http_status": response.status_code, "retry_after": value if retry_at(value) else None}

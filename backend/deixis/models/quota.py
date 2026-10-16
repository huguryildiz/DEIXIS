"""Subscription quota windows for Settings → Usage: how much of a signed-in CLI's own usage limit is used.

Codex answers `account/rateLimits/read` live; its windows are named by length (a five-hour and a weekly window), and an
account may have only one of them. Claude Code has no such read: the CLI reports its windows with each call
(`rate_limit_event`, `unifiedWindows`), so the figure is the one seen on the last call, with that call's time. A window
the CLI did not report is left out, never shown as 0.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WINDOW_NAMES = {300: "five_hour", 10080: "seven_day"}  # minutes → name


def finite(value: Any) -> float | None:
    """A JSON number as a finite float, or None (a boolean, NaN, infinity, or an integer too large for a float)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def stamp(seconds: Any) -> str | None:
    """A Unix time as the stored timestamp format, or None."""
    seconds = finite(seconds)
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds")
    except (ValueError, OverflowError, OSError):
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fraction(value: Any) -> float | None:
    value = finite(value)
    return None if value is None else min(1.0, max(0.0, value))


def codex_windows(result: Any) -> list[dict[str, Any]]:
    """The windows of Codex's own limit (`limitId` "codex") from an `account/rateLimits/read` answer."""
    limits = result.get("rateLimits") if isinstance(result, dict) else None
    if not isinstance(limits, dict):
        return []
    windows = []
    for slot in ("primary", "secondary"):
        window = limits.get(slot)
        if not isinstance(window, dict):
            continue
        percent = fraction(window.get("usedPercent"))  # rejects a missing or boolean figure
        used = fraction(window["usedPercent"] / 100) if percent is not None else None
        minutes = window.get("windowDurationMins")
        if used is None or not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            continue
        windows.append({"window": WINDOW_NAMES.get(minutes, "other"), "minutes": minutes, "used_fraction": used,
                        "resets_at": stamp(window.get("resetsAt"))})
    return sorted(windows, key=lambda w: w["minutes"])


def claude_windows(raw: Any) -> list[dict[str, Any]]:
    """The five-hour and weekly windows from a Claude Code `rate_limit_event` (its `unifiedWindows`)."""
    unified = raw.get("unifiedWindows") if isinstance(raw, dict) else None
    if not isinstance(unified, dict):
        return []
    windows = []
    for name, minutes in (("five_hour", 300), ("seven_day", 10080)):
        window = unified.get(name)
        used = fraction(window.get("utilization")) if isinstance(window, dict) else None
        if used is not None:
            windows.append({"window": name, "minutes": minutes, "used_fraction": used, "resets_at": stamp(window.get("resetsAt"))})
    return windows


def save(path: Path, reading: dict[str, Any]) -> None:
    """Keep the last reading across restarts (written whole, then moved into place)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_text(json.dumps(reading), encoding="utf-8")
        os.replace(part, path)
    except OSError:
        pass


def instant(value: Any) -> str | None:
    """A kept timestamp rewritten in the one format `stamp` and `now_iso` write (UTC, milliseconds), or None when it is not
    a timestamp with a time zone."""
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
        if moment is None or moment.tzinfo is None:
            return None
        return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (ValueError, OverflowError):  # not a timestamp, or one outside the years a UTC moment can hold
        return None


def load(path: Path) -> dict[str, Any] | None:
    """The kept reading, rebuilt from its checked parts; None when the file is missing or anything in it is malformed."""
    try:
        reading = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(reading, dict) or reading.get("source") != "last_call" or not instant(reading.get("seen_at")) \
            or not isinstance(reading.get("windows"), list):
        return None
    seen_at, windows = instant(reading["seen_at"]), []
    for window in reading["windows"]:
        if not isinstance(window, dict) or window.get("window") not in ("five_hour", "seven_day") \
                or any(kept["window"] == window["window"] for kept in windows) \
                or window.get("minutes") != {"five_hour": 300, "seven_day": 10080}[window["window"]]:
            return None
        used, resets = window.get("used_fraction"), window.get("resets_at")
        if used is None or fraction(used) != used or not (resets is None or instant(resets)):
            return None
        windows.append({"window": window["window"], "minutes": window["minutes"], "used_fraction": float(used),
                        "resets_at": instant(resets) if resets is not None else None})
    return {"source": "last_call", "seen_at": seen_at, "windows": windows} if windows else None

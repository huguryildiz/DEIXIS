"""Estimated money spent on paid-API model calls (pre-P10 F4).

Only connections that bill per call count: a provider API key. A call through a subscription CLI (Codex, Claude Code,
Gemini CLI, Copilot) or a model on this computer spends nothing per call and gets no ledger row. The cost of a call is
estimated from the usage the provider returned and `models/model_prices.json`, a dated static table. The provider's own
bill is what counts; this is an estimate, never a promise.

Nothing unknown is read as zero. A call whose model has no listed price gets a row with no cost (an unpriced call). A call
whose answer carried no usage is estimated from the characters sent and received and says so (`estimated_from_text`). A
call whose outcome is unknown (the process stopped, the answer never arrived) may still have been billed, so it counts
as spent, estimated the same way. Only a call that never reached the provider (no connection, a refusal with an HTTP
error and no usage) is left out.

The ledger (`spend_ledger`) is separate from the researches: deleting a research does not lower the day's total. A row is
written in the same transaction as the model session's result (`Store.finish_model_session`).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from deixis.models.openai_compat import CONNECTIONS, LOCAL_CONNECTIONS
from deixis.storage.db import now

PRICE_FILE = Path(__file__).resolve().parents[1] / "models" / "model_prices.json"
THRESHOLD_SETTING = "spend_threshold_usd"
# Connections that bill per call by a provider API key; the OpenAI-compatible ones are the hosted connections with a key.
API_KEY_CONNECTIONS = frozenset({"openai", "anthropic", "gemini", "deepseek"}
                                | {c.id for c in CONNECTIONS.values() if c.key_env})
CHARS_PER_TOKEN = 4  # the same rule as the claim-check preview ("four characters per token")
_DATED = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")


def kind_of(connection: str | None) -> str:
    """How a connection is paid: `api` (per call, by key), `local` (this computer), `subscription` (a signed-in CLI), or
    `none` (no connection)."""
    if not connection:
        return "none"
    if connection in API_KEY_CONNECTIONS:
        return "api"
    return "local" if connection in LOCAL_CONNECTIONS else "subscription"


@lru_cache(maxsize=1)
def price_table() -> dict[str, Any]:
    return json.loads(PRICE_FILE.read_text(encoding="utf-8"))


def price_for(connection: str | None, model: str | None) -> dict[str, float] | None:
    """The listed prices (US dollars per million tokens) of a model, or None when the table does not list it. A dated
    snapshot (`claude-haiku-4-5-20251001`) takes its alias's price; nothing else is guessed from the name."""
    if not connection or not model:
        return None
    models = price_table()["models"].get(connection) or {}
    return models.get(model) or models.get(_DATED.sub("", model))


def usage_tokens(usage: Any) -> dict[str, int] | None:
    """(input, cached_input, cache_write, output) tokens from the usage object any adapter stores, or None when it does
    not hold both an input and an output count. `input` is the whole prompt, the cached part included; `output` includes
    reasoning tokens, which every provider bills as output.

    OpenAI chat and compatible APIs: prompt_tokens, completion_tokens. OpenAI Responses: input_tokens, output_tokens.
    Anthropic: input_tokens is the uncached part; cache reads and writes are separate counts. Gemini: promptTokenCount,
    candidatesTokenCount and thoughtsTokenCount. DeepSeek adds prompt_cache_hit_tokens."""
    if not isinstance(usage, dict):
        return None

    def number(*names: str, source: dict[str, Any] = usage) -> int | None:
        for name in names:
            value = source.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                return int(value)
        return None

    if "promptTokenCount" in usage or "candidatesTokenCount" in usage:  # Gemini
        prompt, answer = number("promptTokenCount"), number("candidatesTokenCount")
        if prompt is None or answer is None:
            return None
        return {"input": prompt, "cached_input": number("cachedContentTokenCount") or 0, "cache_write": 0,
                "output": answer + (number("thoughtsTokenCount") or 0)}
    if "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:  # Anthropic with caching
        plain, answer = number("input_tokens"), number("output_tokens")
        if plain is None or answer is None:
            return None
        read, write = number("cache_read_input_tokens") or 0, number("cache_creation_input_tokens") or 0
        return {"input": plain + read + write, "cached_input": read, "cache_write": write, "output": answer}
    prompt, answer = number("prompt_tokens", "input_tokens"), number("completion_tokens", "output_tokens")
    if prompt is None or answer is None:
        return None
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = number("cached_tokens", source=details) if isinstance(details, dict) else None
    hit = number("prompt_cache_hit_tokens")  # DeepSeek
    return {"input": prompt, "cached_input": min(prompt, cached if cached is not None else hit or 0), "cache_write": 0,
            "output": answer}


def cost_of(prices: dict[str, float], tokens: dict[str, int]) -> float:
    """US dollars for these tokens at these per-million prices; a cached part with no listed cached price costs the full
    input price (the higher figure)."""
    cached, write = tokens["cached_input"], tokens["cache_write"]
    plain = tokens["input"] - cached - write
    return (plain * prices["input"] + cached * prices.get("cached_input", prices["input"])
            + write * prices.get("cache_write", prices["input"]) + tokens["output"] * prices["output"]) / 1_000_000


def request_sent(status: str, delivery_class: str | None, http_status: int | None, has_usage: bool) -> bool | None:
    """Whether the call reached the provider: False for one that never left (no connection, a key refused up front) or
    that the provider refused with an HTTP error and returned no usage; True otherwise; a result that says nothing about
    it (a process that stopped) is None and counts as sent."""
    if has_usage:
        return True
    if status == "unavailable" or delivery_class == "before_send":
        return False
    if http_status is not None:
        return False
    return None


def day_of(clock: Any) -> str:
    """The local calendar day of the clock, the ledger's day."""
    return clock.now().astimezone().date().isoformat()


def sent_day(started_at: str) -> str:
    """The local calendar day a call was sent, from its session's start time (stored in UTC). The machine's own time zone
    decides where the day ends, the same as `day_of`; a call finished or recovered after midnight is still booked on the
    day it was sent."""
    return datetime.fromisoformat(started_at).astimezone().date().isoformat()


def record_session(conn: sqlite3.Connection, session_id: str, sent: bool | None) -> None:
    """Write (or rewrite) the session's ledger row from the session as stored, booked on the day it was sent. Call inside
    the transaction that stores the session's result. A call on a connection that does not bill per call, or one that
    never left, leaves no row."""
    session = conn.execute(
        "SELECT connection, requested_model, resolved_model, status, raw_output, token_usage_json, step_input_id, started_at"
        " FROM model_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None or session["connection"] not in API_KEY_CONNECTIONS:
        return
    if sent is False:
        conn.execute("DELETE FROM spend_ledger WHERE session_id = ?", (session_id,))
        return
    # The model that answered is the one billed: when it has no listed price the call is unpriced, never priced as the
    # model that was asked for.
    model = session["resolved_model"] or session["requested_model"]
    prices = price_for(session["connection"], model)
    usage = json.loads(session["token_usage_json"]) if session["token_usage_json"] else None
    tokens, cost, basis = usage_tokens(usage), None, "unpriced"
    if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)) and not isinstance(usage["cost"], bool) \
            and session["connection"] == "openrouter" and usage["cost"] >= 0:
        cost, basis = float(usage["cost"]), "provider_cost"  # OpenRouter reports the dollars it billed
    elif prices is not None and tokens is not None:
        cost, basis = cost_of(prices, tokens), "reported"
    elif prices is not None:
        # No usable usage: the characters sent and received stand in for it. A rough figure, flagged as such.
        sent_chars = conn.execute(
            "SELECT length(base_instructions) + length(developer_instructions) + length(user_message)"
            " + length(output_schema_json) FROM step_inputs WHERE id = ?", (session["step_input_id"],)).fetchone()
        guess = {"input": (sent_chars[0] if sent_chars and sent_chars[0] else 0) // CHARS_PER_TOKEN, "cached_input": 0,
                 "cache_write": 0, "output": len(session["raw_output"] or "") // CHARS_PER_TOKEN}
        cost, basis, tokens = cost_of(prices, guess), "estimated_from_text", guess
    conn.execute(
        "INSERT INTO spend_ledger (session_id, day, connection, model, input_tokens, cached_input_tokens, output_tokens,"
        " cost_usd, basis, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET model = excluded.model, input_tokens = excluded.input_tokens,"
        " cached_input_tokens = excluded.cached_input_tokens, output_tokens = excluded.output_tokens,"
        " cost_usd = excluded.cost_usd, basis = excluded.basis",
        (session_id, sent_day(session["started_at"]), session["connection"], model, tokens["input"] if tokens else None,
         tokens["cached_input"] if tokens else None, tokens["output"] if tokens else None, cost, basis, now()))


def reprice_unpriced(conn: sqlite3.Connection) -> int:
    """Give a cost to the ledger rows booked as unpriced whose model the price list now names (D111), and return how many.
    Each is rewritten from its stored session exactly as `record_session` would now write it, then marked with when and
    with which dated list; a row whose model is still not listed, or whose session is gone, stays unpriced. Call inside a
    transaction."""
    as_of, count = price_table()["as_of"], 0
    rows = conn.execute("SELECT session_id, connection, model FROM spend_ledger WHERE basis = 'unpriced'").fetchall()
    for row in rows:
        if price_for(row["connection"], row["model"]) is None:
            continue
        record_session(conn, row["session_id"], None)
        count += conn.execute(
            "UPDATE spend_ledger SET repriced_at = ?, repriced_price_list = ? WHERE session_id = ? AND cost_usd IS NOT NULL",
            (now(), as_of, row["session_id"])).rowcount
    return count


def day_total(conn: sqlite3.Connection, day: str) -> dict[str, Any]:
    """What the ledger holds for a day: the estimated dollars of the calls with a cost, how many calls that is, how many
    of those were estimated from text (no usage reported), how many calls have no price (`unpriced`, not in the
    dollars), and how many were priced later from a newer list (`repriced`, D111) with the latest such list's date."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS usd, COUNT(cost_usd) AS priced,"
        " COALESCE(SUM(basis = 'estimated_from_text'), 0) AS from_text, COALESCE(SUM(cost_usd IS NULL), 0) AS unpriced,"
        " COALESCE(SUM(repriced_at IS NOT NULL), 0) AS repriced, MAX(repriced_price_list) AS repriced_with"
        " FROM spend_ledger WHERE day = ?", (day,)).fetchone()
    return {"day": day, "estimated_usd": row["usd"], "priced_calls": row["priced"], "estimated_from_text_calls": row["from_text"],
            "unpriced_calls": row["unpriced"], "repriced_calls": row["repriced"], "repriced_price_list": row["repriced_with"]}


def threshold(store: Any) -> float | None:
    """The daily stopping threshold in US dollars, or None while it is off."""
    value = store.setting(THRESHOLD_SETTING)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def over_threshold(store: Any) -> dict[str, Any] | None:
    """The day's figures when the estimated spend has reached the threshold, else None (also while the threshold is
    off). Checked before a call is sent, never during one."""
    limit = threshold(store)
    if limit is None:
        return None
    total = day_total(store.conn, day_of(store.clock))
    return {"threshold_usd": limit, **total} if total["estimated_usd"] >= limit else None

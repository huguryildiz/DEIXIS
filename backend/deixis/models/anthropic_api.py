"""Anthropic Messages API model connection (ANTHROPIC_API_KEY, D34).

The Claude Code CLI signed in with a Claude account is a separate connection (`claude.py`). This one calls the
Messages API directly: one stateless request per step, no tools, the step schema sent as a structured-output format
(`output_config.format`, in the subset the API accepts: `schema_subset.py`), and the answering model reported as
`resolved_model` so the flow's mismatch check applies. No server-side fallback model is requested: a decline ends the
step as failed instead of another model answering. Raw HTTP through the shared httpx client, as the Gemini and
DeepSeek connections do, so tests inject a mocked transport.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from deixis import key_verification
from deixis.domain.limits import error_name, http_limit, retry_at, service_error_kind
from deixis.models.adapter import ModelStepResult, broken_key_status, invalid_key_result, is_dated_snapshot
from deixis.models.schema_subset import portable_schema

API_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
KEY_ENV = "ANTHROPIC_API_KEY"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Above this a non-streamed request risks the HTTP timeout; thinking counts against it too.
MAX_TOKENS = 16000
# Content blocks that are the model's own text; any other block is a tool or server-tool item.
TEXT_BLOCKS = frozenset({"text", "thinking", "redacted_thinking"})


def api_key() -> str | None:
    return os.environ.get(KEY_ENV) or None


def headers(key: str) -> dict[str, str]:
    return {"x-api-key": key, "anthropic-version": API_VERSION}


def _supported(node: Any) -> bool:
    return isinstance(node, dict) and node.get("supported") is True


class AnthropicAdapter:
    connection = "anthropic"
    enforces_schema = True
    sends_reasoning_effort = True  # output_config.effort

    def __init__(self, client: httpx.AsyncClient | None = None, turn_timeout: float = 300.0):
        self._client = client
        self._owns_client = client is None
        self.turn_timeout = turn_timeout
        self._health: tuple[float, dict[str, Any]] | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        key = api_key()
        status: dict[str, Any] = {"connection": self.connection, "ready": False, "key_configured": bool(key),
                                  "isolation": {"instruction_sources": 0, "live_mcp_servers": []}}
        if not key:
            status["reason_code"] = "needs_key"
            status["reason"] = "Add an Anthropic API key in Settings"
            return status
        if not key_verification.is_valid_key(key):
            return broken_key_status(status, "Anthropic")
        # A second try after a transport error, as for the other API connections: one failed check pauses a run.
        for attempt in range(2):
            try:
                response = await self._http().get(f"{API_URL}/models", params={"limit": 1000}, headers=headers(key), timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason_code"] = service_error_kind(exc=exc)
                    status["reason"] = f"Anthropic API unreachable: {type(exc).__name__}"
                    return status
        if response.status_code != 200:
            status["reason_code"] = http_limit(response)["error_kind"]
            status["reset_at"] = retry_at(http_limit(response)["retry_after"])
            status["reason"] = f"Anthropic API answered HTTP {response.status_code}: API request failed"
            return status
        models = []
        for m in response.json().get("data", []):
            caps = m.get("capabilities") or {}
            # Only models that take a structured-output format: this connection always sends one.
            if not m.get("id") or not _supported(caps.get("structured_outputs")):
                continue
            effort = caps.get("effort") or {}
            models.append({"id": m["id"], "display_name": m.get("display_name") or m["id"], "is_default": False,
                           "description": "", "default_reasoning_effort": None,
                           "reasoning_efforts": [{"id": e, "description": ""} for e in EFFORTS
                                                 if _supported(effort) and _supported(effort.get(e))]})
        status["models"] = models
        status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key = api_key()
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{KEY_ENV} is not set" if not key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if not key else "unknown")
        if not key_verification.is_valid_key(key):  # a header cannot carry it; nothing is sent
            return invalid_key_result()
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": portable_schema(output_schema)}}
        if reasoning_effort:
            output_config["effort"] = reasoning_effort
        body = {"model": requested_model, "max_tokens": MAX_TOKENS, "system": f"{base}\n\n{developer}",
                "messages": [{"role": "user", "content": message}], "output_config": output_config}
        try:
            response = await self._http().post(f"{API_URL}/messages", json=body, headers=headers(key), timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=error_name(exc), delivery_class="before_send")
        except httpx.HTTPError as exc:  # the request may have been processed without an answer arriving
            return ModelStepResult("failed", error=type(exc).__name__, delivery_class="after_send_unknown")
        if response.status_code != 200:
            return ModelStepResult("failed", error=f"HTTP {response.status_code}: API request failed", **http_limit(response))
        try:
            data = response.json()
        except ValueError:
            return ModelStepResult("failed", error="Invalid JSON response", delivery_class="after_send_unknown")
        blocks = [b for b in data.get("content") or [] if isinstance(b, dict)]
        text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
        tools = [str(b.get("type")) for b in blocks if b.get("type") not in TEXT_BLOCKS]
        resolved = data.get("model") or None
        common: dict[str, Any] = {"resolved_model": resolved, "external_thread_id": data.get("id"),
                                  "token_usage": data.get("usage"), "tool_item_types": tools,
                                  "requested_model_verified": is_dated_snapshot(requested_model, resolved)}
        if tools:
            return ModelStepResult("isolation_violation", raw_text=text or None,
                                   error="Anthropic API returned a tool item", **common)
        stop = data.get("stop_reason")
        if stop != "end_turn" or not text:
            return ModelStepResult("failed", raw_text=text or None, error=f"finish reason {stop}", **common)
        return ModelStepResult("completed", raw_text=text, **common)

    async def cancel(self) -> bool:
        return False  # one blocking request per step; a pause takes effect after it returns

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

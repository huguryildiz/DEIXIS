"""OpenAI API model connection for research steps (OPENAI_API_KEY, D34).

Codex signed in with a ChatGPT account is a separate connection (`adapter.py`); the same key also serves embeddings
(`documents/embeddings.py`), unchanged. This one calls the Responses API directly: one stateless request per step
(`store: false`), no tools, the step schema sent as a strict JSON-schema text format, and the answering model reported
as `resolved_model` so the flow's mismatch check applies. Any output item other than a message or reasoning is a tool
item and fails the step. No reasoning effort is sent: the accepted values differ by model and the model list does
not say which a model takes.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from deixis.domain.limits import http_limit, retry_at, service_error_kind
from deixis.models.adapter import ModelStepResult, is_dated_snapshot

API_URL = "https://api.openai.com/v1"
KEY_ENV = "OPENAI_API_KEY"
# Chat models that take a strict JSON-schema format (GPT-4o and later, the o-series); the list also holds embedding,
# audio, image and moderation models.
CHAT_MODEL = re.compile(r"^(gpt-(4o|4\.\d|[5-9])|o[1-9])")
EXCLUDED_MODEL_WORDS = ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding", "moderation",
                        "instruct", "computer-use", "deep-research", "latest")
# Chat models without strict JSON-schema output: OpenAI's structured outputs guide names gpt-4o-mini and the
# gpt-4o-2024-08-06 snapshot as the first that take it, and o1-preview and o1-mini never did.
NO_STRICT_SCHEMA = re.compile(r"^(gpt-4o-2024-05-13|o1-preview|o1-mini)(-|$)")
OUTPUT_ITEMS = frozenset({"message", "reasoning"})


def api_key() -> str | None:
    return os.environ.get(KEY_ENV) or None


class OpenAIAdapter:
    connection = "openai"
    enforces_schema = True
    sends_reasoning_effort = False  # accepted for the protocol, never put in the request (module docstring)

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
            status["reason"] = "Add an OpenAI API key in Settings"
            return status
        for attempt in range(2):  # one retry after a transport error, as for the other API connections
            try:
                response = await self._http().get(f"{API_URL}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason_code"] = service_error_kind(exc=exc)
                    status["reason"] = f"OpenAI API unreachable: {type(exc).__name__}"
                    return status
        if response.status_code != 200:
            status["reason_code"] = http_limit(response)["error_kind"]
            status["reset_at"] = retry_at(http_limit(response)["retry_after"])
            status["reason"] = f"OpenAI API answered HTTP {response.status_code}: API request failed"
            return status
        ids = sorted({m["id"] for m in response.json().get("data", []) if isinstance(m, dict) and isinstance(m.get("id"), str)
                      and CHAT_MODEL.match(m["id"]) and not NO_STRICT_SCHEMA.match(m["id"])
                      and not any(w in m["id"] for w in EXCLUDED_MODEL_WORDS)})
        status["models"] = [{"id": i, "display_name": i, "is_default": False, "description": "",
                             "default_reasoning_effort": None, "reasoning_efforts": []} for i in ids]
        status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key = api_key()
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{KEY_ENV} is not set" if not key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if not key else "unknown")
        body = {"model": requested_model, "instructions": f"{base}\n\n{developer}", "input": message, "store": False,
                "text": {"format": {"type": "json_schema", "name": "deixis_step", "schema": output_schema, "strict": True}}}
        try:
            response = await self._http().post(f"{API_URL}/responses", json=body, headers={"Authorization": f"Bearer {key}"},
                                               timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=type(exc).__name__, delivery_class="before_send")
        except httpx.HTTPError as exc:
            return ModelStepResult("failed", error=type(exc).__name__, delivery_class="after_send_unknown")
        if response.status_code != 200:
            return ModelStepResult("failed", error=f"HTTP {response.status_code}: API request failed", **http_limit(response))
        try:
            data = response.json()
        except ValueError:
            return ModelStepResult("failed", error="Invalid JSON response", delivery_class="after_send_unknown")
        items = [i for i in data.get("output") or [] if isinstance(i, dict)]
        parts = [p for i in items if i.get("type") == "message" for p in i.get("content") or [] if isinstance(p, dict)]
        text = "".join(p.get("text") or "" for p in parts if p.get("type") == "output_text")
        tools = [str(i.get("type")) for i in items if i.get("type") not in OUTPUT_ITEMS]
        resolved = data.get("model") or None
        common: dict[str, Any] = {"resolved_model": resolved, "external_thread_id": data.get("id"),
                                  "token_usage": data.get("usage"), "tool_item_types": tools,
                                  "requested_model_verified": is_dated_snapshot(requested_model, resolved)}
        if tools:
            return ModelStepResult("isolation_violation", raw_text=text or None, error="OpenAI API returned a tool item", **common)
        if any(p.get("type") == "refusal" for p in parts):
            return ModelStepResult("failed", raw_text=text or None, error="finish reason refusal", **common)
        if data.get("status") != "completed" or not text:
            reason = (data.get("incomplete_details") or {}).get("reason") or data.get("status")
            return ModelStepResult("failed", raw_text=text or None, error=f"finish reason {reason}", **common)
        return ModelStepResult("completed", raw_text=text, **common)

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

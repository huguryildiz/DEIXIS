"""OpenAI API model connection for research steps (OPENAI_API_KEY, D34).

Codex signed in with a ChatGPT account is a separate connection (`adapter.py`); the same key also serves embeddings
(`documents/embeddings.py`), unchanged. This one calls the Responses API directly: one stateless request per step
(`store: false`), no tools, the step schema sent as a strict JSON-schema text format, and the answering model reported
as `resolved_model` so the flow's mismatch check applies. Any output item other than a message or reasoning is a tool
item and fails the step. The model list does not say which reasoning efforts a model takes, so they come from a fixed
table (`EFFORTS`), checked live on 15 Oct 2026: the API refuses an effort a model does not take with HTTP 400 before
any other check. A model missing from the table is offered no effort and none is sent.
"""

from __future__ import annotations

import base64

import os
import re
import time
from typing import Any

import httpx

from deixis.keys import key_verification
from deixis.domain.limits import error_name, http_limit, retry_at, service_error_kind
from deixis.models.adapter import ModelStepResult, broken_key_status, invalid_key_result, is_dated_snapshot

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
# Reasoning efforts per model (a dated snapshot takes its alias's), each list as the API accepted it on 15 Oct 2026.
# GPT-4o and GPT-4.1 take none: the API refuses the parameter. The Codex models answered 404 to the key tested and
# are left out.
_GPT5 = ("minimal", "low", "medium", "high")
_GPT51 = ("none", "low", "medium", "high")
_GPT52 = ("none", "low", "medium", "high", "xhigh")
_PRO = ("medium", "high", "xhigh")
_O = ("low", "medium", "high")
EFFORTS: dict[str, tuple[str, ...]] = {
    "gpt-5": _GPT5, "gpt-5-mini": _GPT5, "gpt-5-nano": _GPT5, "gpt-5-pro": ("high",),
    "gpt-5.1": _GPT51,
    "gpt-5.2": _GPT52, "gpt-5.3-codex": _GPT52, "gpt-5.4": _GPT52, "gpt-5.4-mini": _GPT52, "gpt-5.4-nano": _GPT52,
    "gpt-5.5": _GPT52, "gpt-5.6-luna": _GPT52, "gpt-5.6-sol": _GPT52, "gpt-5.6-terra": _GPT52,
    "gpt-6-luna": _GPT52, "gpt-6-sol": _GPT52,
    "gpt-5.2-pro": _PRO, "gpt-5.4-pro": _PRO, "gpt-5.5-pro": _PRO,
    "gpt-6-astra": ("low", "medium", "high", "xhigh"), "gpt-6.1-sol": ("low", "medium", "high", "xhigh"),
    "o1": _O, "o3": _O, "o3-mini": _O, "o4-mini": _O,
}
SNAPSHOT_DATE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def efforts(model: str) -> tuple[str, ...]:
    return EFFORTS.get(SNAPSHOT_DATE.sub("", model), ())


def api_key() -> str | None:
    return os.environ.get(KEY_ENV) or None


class OpenAIAdapter:
    connection = "openai"
    enforces_schema = True
    sends_reasoning_effort = True  # reasoning.effort, from the fixed table (module docstring)
    accepts_images = True  # run_step(image_png=...) sends one PNG with the message (D113)
    key_env = KEY_ENV

    def __init__(self, client: httpx.AsyncClient | None = None, turn_timeout: float = 300.0):
        self._client = client
        self._owns_client = client is None
        self.turn_timeout = turn_timeout
        self._health: tuple[float, dict[str, Any], str] | None = None  # (time, answer, fingerprint of the key)
        self._checks = 0  # health checks started, to order their answers

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        key = api_key()
        # A cached answer belongs to the key it was made with. Checks are ordered: only the newest one to have started
        # may write the cache, whatever it found, so a slow older check never covers a newer answer (E7).
        mine = key_verification.fingerprint(key or "")
        if self._health and not refresh and time.monotonic() - self._health[0] < 60 and self._health[2] == mine:
            return self._health[1]
        self._checks += 1
        check = self._checks
        status = await self._check(key)
        if check == self._checks and key_verification.fingerprint(api_key() or "") == mine:
            self._health = (time.monotonic(), status, mine)
        elif self._health and self._health[2] == mine:
            return self._health[1]  # a newer check owns the answer: the caller gets that one, not this stale one
        return status

    def key_changed(self, env: str) -> None:
        """A key was saved or deleted: the cached answer goes and any check under way may no longer write it (E7)."""
        if env == KEY_ENV:
            self._health = None
            self._checks += 1

    async def _check(self, key: str | None) -> dict[str, Any]:
        status: dict[str, Any] = {"connection": self.connection, "ready": False, "key_configured": bool(key),
                                  "isolation": {"instruction_sources": 0, "live_mcp_servers": []}}
        if not key:
            status["reason_code"] = "needs_key"
            status["reason"] = "Add an OpenAI API key in Settings"
            return status
        if not key_verification.is_valid_key(key):
            return broken_key_status(status, "OpenAI")
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
                             "default_reasoning_effort": None,
                             "reasoning_efforts": [{"id": e, "description": ""} for e in efforts(i)]} for i in ids]
        status["ready"] = True
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None,
                       image_png: bytes | None = None) -> ModelStepResult:
        key = api_key()
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{KEY_ENV} is not set" if not key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if not key else "unknown")
        if not key_verification.is_valid_key(key):  # a header cannot carry it; nothing is sent
            return invalid_key_result()
        body = {"model": requested_model, "instructions": f"{base}\n\n{developer}", "input": message if image_png is None else [{"role": "user", "content": [
                    {"type": "input_image", "image_url": "data:image/png;base64," + base64.standard_b64encode(image_png).decode()},
                    {"type": "input_text", "text": message}]}], "store": False,
                "text": {"format": {"type": "json_schema", "name": "deixis_step", "schema": output_schema, "strict": True}}}
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        try:
            response = await self._http().post(f"{API_URL}/responses", json=body, headers={"Authorization": f"Bearer {key}"},
                                               timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=error_name(exc), delivery_class="before_send")
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

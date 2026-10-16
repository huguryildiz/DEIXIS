"""Gemini API model connection.

DEIXIS calls the Gemini API directly with GEMINI_API_KEY: one stateless request per step, with no tools, no
instruction files and no CLI agent prompt. The Gemini CLI with a Google account is a separate connection
(`gemini_cli.py`, D23). The adapter never falls back to another connection or model.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from deixis import key_verification
from deixis.models.adapter import ModelStepResult, broken_key_status, invalid_key_result
from deixis.domain.limits import error_name, http_limit, service_error_kind, retry_at
from deixis.tool_paths import child_path, command_for, find_tool
from deixis.tool_probe import probe

API_URL = "https://generativelanguage.googleapis.com/v1beta"
KEY_ENV = "GEMINI_API_KEY"
# Not text-generation models for this workflow, or aliases whose answering model differs from the requested id.
# banana (image), transcribe (speech) and customtools (an agent-tools variant) were listed on 16 Oct 2026 (D59).
EXCLUDED_MODEL_WORDS = ("image", "tts", "audio", "live", "embedding", "robotics", "computer-use", "omni", "latest", "aqa",
                        "gemma", "banana", "transcribe", "customtools")
THINKING_LEVELS = ("low", "medium", "high")
# Text and its documented metadata; every other part key (functionCall, executableCode, an unknown one) is a tool item.
TEXT_PART_KEYS = frozenset({"text", "thought", "thoughtSignature", "partMetadata"})
# The Gemini API answers 400 INVALID_ARGUMENT for array size bounds in a response schema (probed 2026-09-15);
# DEIXIS validation still applies them to the output.
UNSUPPORTED_SCHEMA_KEYS = frozenset({"minItems", "maxItems"})


def api_key() -> str | None:
    return os.environ.get(KEY_ENV) or None


def response_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: response_schema(v) for k, v in schema.items() if k not in UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(schema, list):
        return [response_schema(v) for v in schema]
    return schema


def error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])[:200]
    except (ValueError, KeyError, TypeError):
        return response.text[:200]


class GeminiAdapter:
    connection = "gemini"
    enforces_schema = True
    sends_reasoning_effort = True  # generationConfig.thinkingConfig.thinkingLevel

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
        cli = await asyncio.to_thread(find_tool, "gemini")
        status: dict[str, Any] = {"connection": "gemini", "ready": False, "installed": bool(cli), "key_configured": bool(key),
                                  "isolation": {"instruction_sources": 0, "live_mcp_servers": []}}
        if argv := command_for("gemini", cli).argv:  # a Windows batch launcher is never started (A4)
            status["cli_version"] = (await probe([*argv, "--version"], env={**os.environ, "PATH": child_path(cli)})).stdout.strip() or None
        if not key:
            status["reason_code"] = "needs_key"
            status["reason"] = "Add a Gemini API key in Settings to use the Gemini API"
            return status
        if not key_verification.is_valid_key(key):
            return broken_key_status(status, "Gemini")
        # A second try after a transport error: the first can expire while something else holds the event loop, and
        # one failed check pauses the whole run.
        for attempt in range(2):
            try:
                response = await self._http().get(f"{API_URL}/models", params={"pageSize": 1000},
                                                  headers={"x-goog-api-key": key}, timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason_code"] = service_error_kind(exc=exc)
                    status["reason"] = f"Gemini API unreachable: {type(exc).__name__}"
                    return status
        if response.status_code != 200:
            status["reason_code"] = http_limit(response)["error_kind"]
            status["reset_at"] = retry_at(http_limit(response)["retry_after"])
            status["reason"] = f"Gemini API answered HTTP {response.status_code}: API request failed"
            return status
        status["models"] = [
            {"id": m["name"].removeprefix("models/"), "display_name": m.get("displayName") or m["name"], "is_default": False,
             "description": m.get("description") or "", "default_reasoning_effort": None,
             "reasoning_efforts": [{"id": level, "description": ""} for level in THINKING_LEVELS]
             if m.get("thinking") and m["name"].startswith("models/gemini-3") else []}
            for m in response.json().get("models", [])
            if m["name"].startswith("models/gemini-") and "generateContent" in m.get("supportedGenerationMethods", [])
            and not any(word in m["name"] for word in EXCLUDED_MODEL_WORDS)
        ]
        status["ready"] = True
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key = api_key()
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{KEY_ENV} is not set" if not key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if not key else "unknown")
        if not key_verification.is_valid_key(key):  # a header cannot carry it; nothing is sent
            return invalid_key_result()
        config: dict[str, Any] = {"responseMimeType": "application/json", "responseJsonSchema": response_schema(output_schema)}
        if reasoning_effort:
            config["thinkingConfig"] = {"thinkingLevel": reasoning_effort}
        body = {"systemInstruction": {"parts": [{"text": f"{base}\n\n{developer}"}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}], "generationConfig": config}
        try:
            response = await self._http().post(f"{API_URL}/models/{requested_model}:generateContent", json=body,
                                               headers={"x-goog-api-key": key}, timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=error_name(exc), delivery_class="before_send")
        except httpx.HTTPError as exc:  # the request may have been processed without an answer arriving
            return ModelStepResult("failed", error=type(exc).__name__, delivery_class="after_send_unknown")
        if response.status_code != 200:
            return ModelStepResult("failed", error=f"HTTP {response.status_code}: API request failed", **http_limit(response))
        data = response.json()
        candidate = (data.get("candidates") or [{}])[0]
        parts = [p for p in (candidate.get("content") or {}).get("parts") or [] if isinstance(p, dict)]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        # Any part that is not text or thinking (a functionCall, executableCode, ...) is a tool item, whatever else came.
        tools = sorted({key for p in parts for key in p if key not in TEXT_PART_KEYS})
        finish = candidate.get("finishReason")
        common: dict[str, Any] = {"resolved_model": data.get("modelVersion"), "external_thread_id": data.get("responseId"),
                                  "token_usage": data.get("usageMetadata"), "tool_item_types": tools}
        if tools:
            return ModelStepResult("isolation_violation", raw_text=text or None, error="Gemini API returned a tool part", **common)
        if finish != "STOP" or not text:
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            return ModelStepResult("failed", raw_text=text or None,
                                   error=f"finish reason {finish}" + (f"; prompt blocked: {blocked}" if blocked else ""), **common)
        return ModelStepResult("completed", raw_text=text, **common)

    async def cancel(self) -> bool:
        return False  # one blocking request per step; a pause takes effect after it returns

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

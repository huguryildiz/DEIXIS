"""Gemini API model connection.

DEIXIS calls the Gemini API directly with GEMINI_API_KEY: one stateless request per step, with no tools, no
instruction files and no CLI agent prompt. The Gemini CLI is detected and reported only. Its headless mode adds its
own agent instructions and tools, and on 2026-09-15 its Google sign-in for individuals answered IneligibleTierError,
so it does not run steps. The adapter never falls back to another connection or model.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from typing import Any

import httpx

from deixis.models.adapter import ModelStepResult

API_URL = "https://generativelanguage.googleapis.com/v1beta"
KEY_ENV = "GEMINI_API_KEY"
# Not text-generation models for this workflow, or aliases whose answering model differs from the requested id.
EXCLUDED_MODEL_WORDS = ("image", "tts", "audio", "live", "embedding", "robotics", "computer-use", "omni", "latest", "aqa", "gemma")
THINKING_LEVELS = ("low", "medium", "high")
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
        cli, key = shutil.which("gemini"), api_key()
        status: dict[str, Any] = {"connection": "gemini", "ready": False, "installed": bool(cli), "key_configured": bool(key),
                                  "isolation": {"instruction_sources": 0, "live_mcp_servers": []}}
        if cli:
            try:
                done = await asyncio.to_thread(subprocess.run, [cli, "--version"], capture_output=True, text=True, timeout=15)
                status["cli_version"] = done.stdout.strip() or None
            except (subprocess.TimeoutExpired, OSError):
                status["cli_version"] = None
        if not key:
            status["reason"] = f"Add a Gemini API key in Settings or set {KEY_ENV} in .env to use the Gemini API"
            return status
        # A second try after a transport error: the first can expire while something else holds the event loop, and
        # one failed check pauses the whole run.
        for attempt in range(2):
            try:
                response = await self._http().get(f"{API_URL}/models", params={"pageSize": 1000},
                                                  headers={"x-goog-api-key": key}, timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason"] = f"Gemini API unreachable: {type(exc).__name__}"
                    return status
        if response.status_code != 200:
            status["reason"] = f"Gemini API answered HTTP {response.status_code}: {error_message(response)}"
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
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key = api_key()
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{KEY_ENV} is not set" if not key else "no model requested",
                                   delivery_class="before_send")
        config: dict[str, Any] = {"responseMimeType": "application/json", "responseJsonSchema": response_schema(output_schema)}
        if reasoning_effort:
            config["thinkingConfig"] = {"thinkingLevel": reasoning_effort}
        body = {"systemInstruction": {"parts": [{"text": f"{base}\n\n{developer}"}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}], "generationConfig": config}
        try:
            response = await self._http().post(f"{API_URL}/models/{requested_model}:generateContent", json=body,
                                               headers={"x-goog-api-key": key}, timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=f"ConnectError: {str(exc)[:250]}", delivery_class="before_send")
        except httpx.HTTPError as exc:  # the request may have been processed without an answer arriving
            return ModelStepResult("failed", error=f"{type(exc).__name__}: {str(exc)[:250]}", delivery_class="after_send_unknown")
        if response.status_code != 200:
            return ModelStepResult("failed", error=f"HTTP {response.status_code}: {error_message(response)}")
        data = response.json()
        candidate = (data.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts", []) if not p.get("thought"))
        finish = candidate.get("finishReason")
        common: dict[str, Any] = {"resolved_model": data.get("modelVersion"), "external_thread_id": data.get("responseId"),
                                  "token_usage": data.get("usageMetadata")}
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

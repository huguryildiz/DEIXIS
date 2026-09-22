"""DeepSeek API model connection with live catalogue discovery."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from deixis.models.adapter import ModelStepResult

API_URL = "https://api.deepseek.com"
KEY_ENV = "DEEPSEEK_API_KEY"
REASONING_EFFORTS = ("none", "low", "high", "max")


def api_key() -> str | None:
    return os.environ.get(KEY_ENV) or None


def error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])[:200]
    except (ValueError, KeyError, TypeError):
        return response.text[:200]


class DeepSeekAdapter:
    connection = "deepseek"
    enforces_schema = False

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
        status: dict[str, Any] = {
            "connection": self.connection,
            "ready": False,
            "key_configured": bool(key),
            "isolation": {"instruction_sources": 0, "live_mcp_servers": []},
        }
        if not key:
            status["reason"] = f"Add a DeepSeek API key in Settings or set {KEY_ENV} in .env"
            return status
        # A second try after a transport error: the first can expire while something else holds the event loop, and
        # one failed check pauses the whole run.
        for attempt in range(2):
            try:
                response = await self._http().get(f"{API_URL}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason"] = f"DeepSeek API unreachable: {type(exc).__name__}"
                    return status
        if response.status_code != 200:
            status["reason"] = f"DeepSeek API answered HTTP {response.status_code}: {error_message(response)}"
            return status
        status["models"] = [
            {
                "id": model["id"],
                "display_name": model["id"],
                "is_default": False,
                "description": "",
                "default_reasoning_effort": "high",
                "reasoning_efforts": [{"id": effort, "description": ""} for effort in REASONING_EFFORTS],
            }
            for model in response.json().get("data", [])
            if model.get("id")
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
        schema_text = json.dumps(output_schema, indent=2)
        system = (
            f"{base}\n\n{developer}\n\n"
            f"The output must match this JSON schema exactly:\n{schema_text}\n\n"
            "Return only a JSON object."
        )
        body: dict[str, Any] = {
            "model": requested_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        try:
            response = await self._http().post(f"{API_URL}/chat/completions", json=body,
                                               headers={"Authorization": f"Bearer {key}"}, timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=f"ConnectError: {str(exc)[:250]}", delivery_class="before_send")
        except httpx.HTTPError as exc:
            return ModelStepResult("failed", error=f"{type(exc).__name__}: {str(exc)[:250]}",
                                   delivery_class="after_send_unknown")
        if response.status_code != 200:
            return ModelStepResult("failed", error=f"HTTP {response.status_code}: {error_message(response)}")
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        common = {
            "resolved_model": data.get("model") or requested_model,
            "external_thread_id": data.get("id"),
            "token_usage": data.get("usage"),
        }
        if choice.get("finish_reason") != "stop" or not content:
            return ModelStepResult("failed", raw_text=content or None,
                                   error=f"finish reason {choice.get('finish_reason')}", **common)
        return ModelStepResult("completed", raw_text=content, **common)

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

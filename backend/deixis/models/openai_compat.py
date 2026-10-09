"""One adapter for model APIs that speak the OpenAI chat-completions dialect (Qwen, Kimi, Mistral).

Same boundary as the DeepSeek adapter: no tools, JSON-object mode, one new request per step, no schema enforcement
(the schema reaches the model in the stored developer text), and the answering model reported as `resolved_model`
so the flow's mismatch check applies. No reasoning effort is sent: these providers' effort parameters are not known
to match DeepSeek's, so none is offered or forwarded.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from deixis.domain.limits import http_limit, service_error_kind, retry_at
from deixis.models.adapter import ModelStepResult


@dataclass(frozen=True)
class CompatConnection:
    id: str
    name: str
    base_url: str
    key_env: str


QWEN = CompatConnection("qwen", "Qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY")
KIMI = CompatConnection("kimi", "Kimi", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY")
MISTRAL = CompatConnection("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY")
CONNECTIONS = {c.id: c for c in (QWEN, KIMI, MISTRAL)}
BY_KEY_ENV = {c.key_env: c for c in CONNECTIONS.values()}


class OpenAICompatAdapter:
    enforces_schema = False

    def __init__(self, spec: CompatConnection, client: httpx.AsyncClient | None = None, turn_timeout: float = 300.0):
        self.spec = spec
        self.connection = spec.id
        self._client = client
        self._owns_client = client is None
        self.turn_timeout = turn_timeout
        self._health: tuple[float, dict[str, Any]] | None = None

    def _key(self) -> str | None:
        return os.environ.get(self.spec.key_env) or None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        key, spec = self._key(), self.spec
        status: dict[str, Any] = {
            "connection": self.connection,
            "ready": False,
            "key_configured": bool(key),
            "isolation": {"instruction_sources": 0, "live_mcp_servers": []},
        }
        if not key:
            status["reason_code"] = "needs_key"
            status["reason"] = f"Add a {spec.name} API key in Settings or set {spec.key_env} in .env"
            return status
        # A second try after a transport error, as for DeepSeek: one failed check pauses the whole run.
        for attempt in range(2):
            try:
                response = await self._http().get(f"{spec.base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason_code"] = service_error_kind(exc=exc)
                    status["reason"] = f"{spec.name} API unreachable: {type(exc).__name__}"
                    return status
        if response.status_code != 200:
            status["reason_code"] = http_limit(response)["error_kind"]
            status["reset_at"] = retry_at(http_limit(response)["retry_after"])
            status["reason"] = f"{spec.name} API answered HTTP {response.status_code}: API request failed"
            return status
        try:
            listed = response.json().get("data", [])
        except ValueError:
            status["reason_code"] = "service_error"
            status["reason"] = f"{spec.name} API returned an unreadable model list"
            return status
        status["models"] = [
            {"id": model["id"], "display_name": model["id"], "is_default": False, "description": "",
             "default_reasoning_effort": None, "reasoning_efforts": []}
            for model in listed if isinstance(model, dict) and model.get("id")
        ]
        status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key, spec = self._key(), self.spec
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{spec.key_env} is not set" if not key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if not key else "unknown")
        # reasoning_effort is accepted for the protocol and deliberately not sent.
        system = f"{base}\n\n{developer}\n\nReturn only a JSON object."
        body: dict[str, Any] = {
            "model": requested_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            response = await self._http().post(f"{spec.base_url}/chat/completions", json=body,
                                               headers={"Authorization": f"Bearer {key}"}, timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=type(exc).__name__, delivery_class="before_send")
        except httpx.HTTPError as exc:
            return ModelStepResult("failed", error=type(exc).__name__,
                                   delivery_class="after_send_unknown")
        if response.status_code != 200:
            # An exhausted balance (402) is a quota failure for the shared text classifier; 429 is classified by http_limit.
            quota = " (quota)" if response.status_code == 402 else ""
            return ModelStepResult("failed", error=f"HTTP {response.status_code}: API request failed{quota}", **http_limit(response))
        try:
            data = response.json()
        except ValueError:
            return ModelStepResult("failed", error="Invalid JSON response", delivery_class="after_send_unknown")
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        common = {
            "resolved_model": data.get("model") or None,
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

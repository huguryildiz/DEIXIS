"""One adapter for model APIs that speak the OpenAI chat-completions dialect (Qwen, Kimi, Mistral, Grok, GitHub
Copilot through GitHub Models, GLM, Meta's Muse Spark and Muse Glimmer, OpenRouter, Xiaomi MiMo, a local Ollama server
and a local server at an address set in Settings).

Same boundary as the DeepSeek adapter: no tools, JSON-object mode, one new request per step, no schema enforcement
(the schema reaches the model in the stored developer text), and the answering model reported as `resolved_model`
so the flow's mismatch check applies. OpenRouter is the exception to JSON-object mode: it routes only to providers
that take a strict JSON schema, and the schema is sent (D34). No reasoning effort is sent: these providers' effort
parameters are not known to match DeepSeek's, so none is offered or forwarded.
"""

from __future__ import annotations

import asyncio

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from deixis import key_verification
from deixis.domain.limits import error_name, http_limit, service_error_kind, retry_at
from deixis.models.adapter import ModelStepResult
from deixis.models.schema_subset import portable_schema


@dataclass(frozen=True)
class CompatConnection:
    id: str
    name: str
    base_url: str
    key_env: str | None  # None: a local server that takes no key (Ollama)
    # Where the model list is read when it is not `{base_url}/models`; GitHub Models serves a bare JSON array there.
    models_url: str | None = None
    # Only listed models whose id starts with this belong to the connection (Muse Spark and Glimmer share one API).
    model_prefix: str | None = None
    # Shown when the API lists no models (GLM has no model list endpoint).
    static_models: tuple[str, ...] = ()
    # Send the step schema as a strict `json_schema` response format instead of JSON-object mode.
    json_schema: bool = False
    # Only listed models whose `supported_parameters` hold this belong to the connection (OpenRouter lists hundreds).
    required_parameter: str | None = None
    # Fields added to every chat request.
    extra_body: tuple[tuple[str, Any], ...] = ()
    # Where a key is checked when the model list is public and would accept any key.
    key_url: str | None = None

    @property
    def list_url(self) -> str:
        return self.models_url or f"{self.base_url}/models"


QWEN = CompatConnection("qwen", "Qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY")
KIMI = CompatConnection("kimi", "Kimi", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY")
MISTRAL = CompatConnection("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY")
GROK = CompatConnection("grok", "Grok", "https://api.x.ai/v1", "XAI_API_KEY")
COPILOT = CompatConnection("copilot", "GitHub Copilot", "https://models.github.ai/inference", "GITHUB_TOKEN",
                           models_url="https://models.github.ai/catalog/models")
GLM = CompatConnection("glm", "GLM", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY",
                       static_models=("glm-5.1", "glm-4.6", "glm-4.5-air"))
MUSE_SPARK = CompatConnection("muse_spark", "Muse Spark", "https://api.meta.ai/v1", "MODEL_API_KEY", model_prefix="muse-spark")
MUSE_GLIMMER = CompatConnection("muse_glimmer", "Muse Glimmer", "https://api.meta.ai/v1", "MODEL_API_KEY", model_prefix="muse-glimmer")
# Routed only to providers that accept every parameter sent, the strict JSON schema included.
OPENROUTER = CompatConnection("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                              json_schema=True, required_parameter="structured_outputs",
                              extra_body=(("provider", {"require_parameters": True}),), key_url="https://openrouter.ai/api/v1/key")
# Xiaomi's pay-as-you-go endpoint (mimo.mi.com, "First API Call", checked 2026-10-15); no model list is documented.
MIMO = CompatConnection("mimo", "Xiaomi MiMo", "https://api.xiaomimimo.com/v1", "MIMO_API_KEY",
                        static_models=("mimo-v2.6-pro", "mimo-v2.6-flash"))
# Ollama's default address on macOS, Windows and Linux; 127.0.0.1 rather than localhost, which Windows may resolve to ::1.
OLLAMA = CompatConnection("ollama", "Ollama", "http://127.0.0.1:11434/v1", None)
# A local model answers one call at a time and slower than a hosted one: its calls queue and get a longer limit, counted
# from the moment the call is sent (local-models-fix plan, 15 Oct 2026).
LOCAL_TURN_TIMEOUT = 1200.0
# Ollama's context window per call: the input estimated high (characters / 3) plus room for the answer, in 8K steps.
OLLAMA_ANSWER_TOKENS = 8192
OLLAMA_CONTEXT_STEP = 8192
CONNECTIONS = {c.id: c for c in (QWEN, KIMI, MISTRAL, GROK, COPILOT, GLM, MUSE_SPARK, MUSE_GLIMMER, OPENROUTER, MIMO, OLLAMA)}
# llama.cpp, Jan, LocalAI, vLLM and the like: the address is set in Settings and read at each call, so this one is not
# in CONNECTIONS, whose addresses are fixed.
LOCAL_SERVER = CompatConnection("local_server", "Local server", "", None)
# Connections whose model runs on this computer (Ollama; LM Studio and other servers through the local server).
LOCAL_CONNECTIONS = frozenset({OLLAMA.id, LOCAL_SERVER.id})
LOCAL_SERVER_SETTING = "local_server_url"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# One connection per key; the two Muse connections share Meta's key, and its check lists either's models.
BY_KEY_ENV = {c.key_env: c for c in CONNECTIONS.values() if c.key_env}


def chat_tool_items(choice: dict[str, Any]) -> list[str]:
    """Tool items in a chat-completions choice: `tool_calls`, the legacy `function_call`, or a finish reason naming
    either. No tools are offered, so any of them fails the step as an isolation violation, whatever else it holds."""
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    calls = message.get("tool_calls")
    items = [str(c.get("type") or "tool_call") if isinstance(c, dict) else "tool_call"
             for c in (calls if isinstance(calls, list) else [calls] if calls else [])]
    if message.get("function_call"):
        items.append("function_call")
    if not items and choice.get("finish_reason") in ("tool_calls", "function_call"):
        items.append(str(choice["finish_reason"]))
    return items


def loopback_client() -> httpx.AsyncClient:
    """A client for a server on this computer: no proxy from the environment (HTTP_PROXY, ALL_PROXY), which would
    carry research text off the machine, and no redirects, which could point elsewhere."""
    return httpx.AsyncClient(trust_env=False, follow_redirects=False)


def loopback_url(value: str | None) -> str | None:
    """A local server's base URL, accepted only on this computer's loopback address; empty clears it (None)."""
    value = (value or "").strip().rstrip("/")
    if not value:
        return None
    try:
        parts = urlsplit(value)
        host, _ = parts.hostname, parts.port  # the port raises ValueError when out of range
    except ValueError as exc:
        raise ValueError("Not a valid address") from exc
    if (parts.scheme not in ("http", "https") or host not in LOOPBACK_HOSTS or parts.username or parts.password
            or parts.query or parts.fragment):
        raise ValueError("Only a server on this computer is accepted: http://127.0.0.1, http://localhost or http://[::1]")
    return value


class OpenAICompatAdapter:
    sends_reasoning_effort = False  # accepted for the protocol, never put in the request (module docstring)

    def __init__(self, spec: CompatConnection, client: httpx.AsyncClient | None = None, turn_timeout: float | None = None,
                 base_url: Callable[[], str | None] | None = None):
        self.spec = spec
        self.connection = spec.id
        self.enforces_schema = spec.json_schema
        # The local server's address, read at each call and checked again, so only a loopback address is contacted.
        self._base_url = base_url
        self._client = client
        self._owns_client = client is None
        local = spec.key_env is None
        self.turn_timeout = turn_timeout if turn_timeout is not None else LOCAL_TURN_TIMEOUT if local else 300.0
        # One call at a time on a model this computer runs; hosted APIs take calls side by side.
        self._turns = asyncio.Semaphore(1) if local else None
        self._context_limits: dict[str, int | None] = {}
        self._health: tuple[float, dict[str, Any]] | None = None

    def _key(self) -> str | None:
        return os.environ.get(self.spec.key_env) or None if self.spec.key_env else None

    def _headers(self, key: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _base(self) -> str | None:
        if self._base_url is None:
            return self.spec.base_url
        try:
            return loopback_url(self._base_url())
        except ValueError:
            return None

    def _list_url(self, base: str) -> str:
        return self.spec.list_url if self._base_url is None else f"{base}/models"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = loopback_client() if self.spec.key_env is None else httpx.AsyncClient()
        return self._client

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        key, spec = self._key(), self.spec
        status: dict[str, Any] = {
            "connection": self.connection,
            "ready": False,
            "isolation": {"instruction_sources": 0, "live_mcp_servers": []},
        }
        if spec.key_env:
            status["key_configured"] = bool(key)
        if spec.key_env and not key:
            status["reason_code"] = "needs_key"
            status["reason"] = f"Add a {spec.name} API key in Settings"
            return status
        if key and not key_verification.is_valid_key(key):  # from the shell or .env; a header cannot carry it (E11)
            status["broken"] = True
            status["reason_code"] = "auth_failed"
            status["reason"] = f"The saved {spec.name} key is not a valid key: enter it again in Settings"
            return status
        state = key_verification.state_of(spec.key_env, key) if spec.key_env else None
        base = self._base()
        if self._base_url is not None:
            status["base_url"] = base
        if not base:
            status["reason_code"] = "needs_setup"
            status["reason"] = f"Set the {spec.name.lower()} address in Settings"
            return status
        # A second try after a transport error, as for DeepSeek: one failed check pauses the whole run.
        for attempt in range(2):
            try:
                response = await self._http().get(self._list_url(base), headers=self._headers(key), timeout=20)
                break
            except httpx.HTTPError as exc:
                if attempt:
                    status["reason_code"] = service_error_kind(exc=exc)
                    status["reason"] = (f"{spec.name} is not running: open the Ollama app or run `ollama serve`" if spec.id == "ollama"
                                        else f"{spec.name} is not running at {base}" if spec.key_env is None
                                        else f"{spec.name} API unreachable: {type(exc).__name__}")
                    return status
        names: dict[str, str] = {}
        unchecked = False  # whether the model list says nothing about the key
        if response.status_code == 404 and spec.static_models:
            # No model list endpoint: the key is not checked here.
            ids = list(spec.static_models)
            unchecked = True
        elif response.status_code != 200:
            status["reason_code"] = http_limit(response)["error_kind"]
            status["reset_at"] = retry_at(http_limit(response)["retry_after"])
            status["reason"] = f"{spec.name} API answered HTTP {response.status_code}: API request failed"
            return status
        else:
            try:
                listed = response.json()
            except ValueError:
                status["reason_code"] = "service_error"
                status["reason"] = f"{spec.name} API returned an unreadable model list"
                return status
            if isinstance(listed, dict):
                listed = listed.get("data") or []  # Ollama with no models answers "data": null
            entries = [m for m in listed if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]]
            if spec.model_prefix:
                entries = [m for m in entries if m["id"].lower().startswith(spec.model_prefix)]
            if spec.required_parameter:
                # OpenRouter lists hundreds of models; only those that take the parameter sent are kept, sorted by id,
                # under the provider's own model name.
                entries = sorted((m for m in entries if spec.required_parameter in (m.get("supported_parameters") or [])),
                                 key=lambda m: m["id"])
                names = {m["id"]: m["name"] for m in entries if isinstance(m.get("name"), str) and m["name"]}
            ids = [m["id"] for m in entries] or list(spec.static_models)
            unchecked = spec.key_url is not None  # that list is public (OpenRouter): any key or none is answered
        if not ids:
            status["reason_code"] = "no_models"
            status["reason"] = (f"{spec.name} lists no models: pull one, for example `ollama pull qwen3`" if spec.id == "ollama"
                                else f"{spec.name} at {base} lists no models" if spec.key_env is None
                                else f"{spec.name} API lists no models for this key")
            return status
        status["models"] = [
            {"id": i, "display_name": names.get(i, i), "is_default": False, "description": "",
             "default_reasoning_effort": None, "reasoning_efforts": []}
            for i in ids
        ]
        if spec.key_env:
            # A step's answer is the last word on the key (E6): a refused key is not ready whatever the list says. A key the
            # list cannot check stays "pending" (not ready, but its first step may run) until a step is answered.
            if state == "rejected":
                verification = "rejected"
            elif unchecked:
                verification = state or "pending"
            else:
                verification = "verified"
                key_verification.set_state(spec.key_env, key, verification)
            status["verification"] = verification
            if verification == "rejected":
                status["reason_code"] = "auth_failed"
                status["reason"] = f"{spec.name} did not accept the key: enter it again in Settings"
                return status
            if verification == "pending":
                status["reason_code"] = "unverified"
                status["reason"] = f"The {spec.name} key is saved but not verified: the first step will try it"
                return status
        status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key, spec = self._key(), self.spec
        if key and not key_verification.is_valid_key(key):  # nothing is sent with a key no header can carry
            return ModelStepResult("unavailable", error="the saved key is not a valid key", delivery_class="before_send",
                                   error_kind="auth_failed")
        missing_key = bool(spec.key_env) and not key
        if missing_key or not requested_model:
            return ModelStepResult("unavailable", error=f"{spec.key_env} is not set" if missing_key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if missing_key else "unknown")
        url = self._base()
        if not url:
            return ModelStepResult("unavailable", error=f"no {spec.name.lower()} address set", delivery_class="before_send",
                                   error_kind="unknown")
        if self._turns is None:
            return await self._send(url, key, base, developer, message, output_schema, requested_model)
        async with self._turns:
            if spec.id == "ollama":
                return await self._send_ollama(url, base, developer, message, output_schema, requested_model)
            return await self._send(url, key, base, developer, message, output_schema, requested_model)

    async def _send(self, url: str, key: str | None, base: str, developer: str, message: str, output_schema: dict[str, Any],
                    requested_model: str) -> ModelStepResult:
        spec = self.spec
        # reasoning_effort is accepted for the protocol and deliberately not sent.
        if spec.json_schema:
            system = f"{base}\n\n{developer}"
            response_format: dict[str, Any] = {"type": "json_schema", "json_schema": {
                "name": "deixis_step", "strict": True, "schema": portable_schema(output_schema)}}
        else:
            system = f"{base}\n\n{developer}\n\nReturn only a JSON object."
            response_format = {"type": "json_object"}
        body: dict[str, Any] = {
            "model": requested_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            "response_format": response_format,
            "stream": False,
            **dict(spec.extra_body),
        }
        try:
            response = await self._http().post(f"{url}/chat/completions", json=body,
                                               headers=self._headers(key), timeout=self.turn_timeout)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=error_name(exc), delivery_class="before_send")
        except httpx.HTTPError as exc:
            return ModelStepResult("failed", error=type(exc).__name__,
                                   delivery_class="after_send_unknown")
        self._note_key(response.status_code)
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
        if tools := chat_tool_items(choice):
            return ModelStepResult("isolation_violation", raw_text=content or None, tool_item_types=tools,
                                   error=f"{spec.name} API returned a tool call", **common)
        if choice.get("finish_reason") != "stop" or not content:
            return ModelStepResult("failed", raw_text=content or None,
                                   error=f"finish reason {choice.get('finish_reason')}", **common)
        return ModelStepResult("completed", raw_text=content, **common)

    def _note_key(self, code: int) -> None:
        """What a step's answer shows about the key (E6): a 200 accepts it, 401 and 403 refuse it."""
        env, key = self.spec.key_env, self._key()
        if env and key and (code == 200 or code in (401, 403)):
            key_verification.set_state(env, key, "verified" if code == 200 else "rejected")
            self._health = None

    async def _context_limit(self, root: str, model: str) -> int | None:
        """The model's own context length from Ollama's /api/show (model_info '<arch>.context_length'); None if unknown."""
        if model not in self._context_limits:
            try:
                shown = await self._http().post(f"{root}/api/show", json={"model": model}, timeout=20)
                info = shown.json().get("model_info", {}) if shown.status_code == 200 else {}
                limits = [v for k, v in info.items() if k.endswith(".context_length") and isinstance(v, int)]
                self._context_limits[model] = limits[0] if limits else None
            except (httpx.HTTPError, ValueError, AttributeError):
                return None
        return self._context_limits[model]

    async def _send_ollama(self, url: str, base: str, developer: str, message: str, output_schema: dict[str, Any],
                           requested_model: str) -> ModelStepResult:
        """Ollama's own /api/chat: thinking off, the step schema as the output format and a context window sized to the
        input, so nothing is cut silently. An input larger than the model's window is not sent."""
        root = url.removesuffix("/v1")
        system = f"{base}\n\n{developer}"
        estimate = (len(system) + len(message)) // 3 + OLLAMA_ANSWER_TOKENS
        num_ctx = -(-estimate // OLLAMA_CONTEXT_STEP) * OLLAMA_CONTEXT_STEP
        limit = await self._context_limit(root, requested_model)
        if limit is not None and estimate > limit:
            return ModelStepResult("failed", delivery_class="before_send", error_kind="unknown",
                                   error=f"input of about {estimate} tokens is larger than {requested_model}'s context window ({limit})")
        if limit is not None:
            num_ctx = min(num_ctx, limit)
        body = {"model": requested_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}],
                "stream": False, "think": False, "format": portable_schema(output_schema), "options": {"num_ctx": num_ctx}}
        try:
            response = await self._http().post(f"{root}/api/chat", json=body, timeout=self.turn_timeout)
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
        reply = data.get("message") or {}
        content = reply.get("content")
        common = {"resolved_model": data.get("model") or None, "external_thread_id": None,
                  "token_usage": {"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count"),
                                  "num_ctx": num_ctx}}
        if reply.get("tool_calls"):
            return ModelStepResult("isolation_violation", raw_text=content or None, tool_item_types=["tool_calls"],
                                   error=f"{self.spec.name} returned a tool call", **common)
        if data.get("done_reason") != "stop" or not content:
            return ModelStepResult("failed", raw_text=content or None, error=f"done reason {data.get('done_reason')}", **common)
        return ModelStepResult("completed", raw_text=content, **common)

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

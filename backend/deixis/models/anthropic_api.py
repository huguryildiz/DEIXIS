"""Anthropic Messages API model connection (ANTHROPIC_API_KEY, D34).

The Claude Code CLI signed in with a Claude account is a separate connection (`claude.py`). This one calls the
Messages API directly: one stateless request per step, no tools, the step schema sent as a structured-output format
(`output_config.format`, in the subset the API accepts: `schema_subset.anthropic_schema`), and the answering model
reported as `resolved_model` so the flow's mismatch check applies. No server-side fallback model is requested: a decline ends the
step as failed instead of another model answering. Raw HTTP through the shared httpx client, as the Gemini and
DeepSeek connections do, so tests inject a mocked transport. The answer is streamed (server-sent events, D85) and put
back together here into the same result a single response gave.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import json
import os
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from deixis.keys import key_verification
from deixis.domain.limits import error_name, http_limit, retry_at, service_error_kind
from deixis.models.adapter import ModelStepResult, broken_key_status, invalid_key_result, is_dated_snapshot
from deixis.models.schema_subset import ANTHROPIC_TRANSFORM_VERSION, anthropic_schema, fill_omitted_nulls, schema_digest

API_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
KEY_ENV = "ANTHROPIC_API_KEY"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Thinking counts against it too. The answer is streamed, so a long turn does not hit a single-response HTTP timeout;
# `turn_timeout` still bounds the whole stream (D85).
MAX_TOKENS = 64000
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
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        key = api_key()
        if not key or not requested_model:
            return ModelStepResult("unavailable", error=f"{KEY_ENV} is not set" if not key else "no model requested",
                                   delivery_class="before_send", error_kind="needs_key" if not key else "unknown")
        if not key_verification.is_valid_key(key):  # a header cannot carry it; nothing is sent
            return invalid_key_result()
        sent_schema = anthropic_schema(output_schema)
        transport: dict[str, Any] = {"schema_transform": ANTHROPIC_TRANSFORM_VERSION, "sent_schema_sha256": schema_digest(sent_schema)}
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": sent_schema}}
        if reasoning_effort:
            output_config["effort"] = reasoning_effort
        body = {"model": requested_model, "max_tokens": MAX_TOKENS, "system": f"{base}\n\n{developer}",
                "messages": [{"role": "user", "content": message}], "output_config": output_config}
        body["stream"] = True
        stream, broken = _Stream(), None
        try:
            async with asyncio.timeout(self.turn_timeout):
                async with self._http().stream("POST", f"{API_URL}/messages", json=body, headers=headers(key),
                                               timeout=self.turn_timeout) as response:
                    if response.status_code != 200:
                        await response.aread()
                        return ModelStepResult("failed", error=f"HTTP {response.status_code}: API request failed",
                                               **http_limit(response))
                    await _read_stream(response, stream)
        except httpx.ConnectError as exc:
            return ModelStepResult("unavailable", error=error_name(exc), delivery_class="before_send")
        except Exception as exc:  # noqa: BLE001 - once sent, a transport error, a timeout, bytes that are not UTF-8 or
            # anything else that breaks the stream is a failed call that may have been processed; none escapes
            broken = type(exc).__name__
        text, tools = stream.text(), stream.tool_types()
        resolved = stream.message.get("model") or None
        common: dict[str, Any] = {"resolved_model": resolved, "external_thread_id": stream.message.get("id"),
                                  "token_usage": stream.usage or None, "tool_item_types": tools,
                                  "requested_model_verified": is_dated_snapshot(requested_model, resolved),
                                  "transport": transport}
        if broken is not None:
            return ModelStepResult("failed", raw_text=text or None, error=broken, delivery_class="after_send_unknown",
                                   **common)
        if stream.error is not None:
            etype = str(stream.error.get("type") or "error")
            return ModelStepResult("failed", raw_text=text or None, error=f"stream error {etype}",
                                   delivery_class="after_send_unknown",
                                   error_kind=service_error_kind(payload={"error": stream.error}, text=etype, surface="model"),
                                   **common)
        if not stream.stopped:
            return ModelStepResult("failed", raw_text=text or None, error="Incomplete stream",
                                   delivery_class="after_send_unknown", **common)
        if tools:
            return ModelStepResult("isolation_violation", raw_text=text or None,
                                   error="Anthropic API returned a tool item", **common)
        stop = stream.stop_reason
        if stop != "end_turn" or not text:
            return ModelStepResult("failed", raw_text=text or None, error=f"finish reason {stop}", **common)
        # A required nullable field was sent optional (`anthropic_schema`, D93): the nulls it left out are put back here,
        # so every reader of the answer sees the step schema's shape. Text with nothing left out is passed on as it came.
        filled, changes = fill_omitted_nulls(output_schema, text)
        if changes:
            # ASCII escapes, so an escaped lone surrogate in the answer stays an escape and the text stays storable.
            transport["filled_nulls"] = [c["path"] for c in changes]
            transport["received_sha256"] = "sha256:" + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
            text = json.dumps(filled, ensure_ascii=True)
        return ModelStepResult("completed", raw_text=text, **common)

    async def cancel(self) -> bool:
        return False  # one streamed request per step; a pause takes effect after it returns

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class _Stream:
    """What a streamed Messages answer said, event by event (D85)."""

    def __init__(self) -> None:
        self.message: dict[str, Any] = {}
        self.usage: dict[str, Any] = {}
        self.blocks: dict[int, dict[str, Any]] = {}  # index -> {"type", "text"}
        self.stop_reason: str | None = None
        self.stopped = False  # message_stop arrived
        self.error: dict[str, Any] | None = None

    def text(self) -> str:
        return "".join(b["text"] for _, b in sorted(self.blocks.items()) if b["type"] == "text")

    def tool_types(self) -> list[str]:
        return [b["type"] for _, b in sorted(self.blocks.items()) if b["type"] not in TEXT_BLOCKS]

    def _merge_usage(self, usage: Any) -> None:
        if isinstance(usage, dict):
            self.usage.update({k: v for k, v in usage.items() if v is not None})

    def event(self, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == "message_start":
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            self.message = {"id": message.get("id"), "model": message.get("model")}
            self._merge_usage(message.get("usage"))
        elif kind == "content_block_start":
            block = data.get("content_block") if isinstance(data.get("content_block"), dict) else {}
            self.blocks[int(data.get("index") or 0)] = {"type": str(block.get("type")),
                                                        "text": str(block.get("text") or "") if block.get("type") == "text" else ""}
        elif kind == "content_block_delta":
            delta = data.get("delta") if isinstance(data.get("delta"), dict) else {}
            block = self.blocks.setdefault(int(data.get("index") or 0), {"type": "text", "text": ""})
            if block["type"] == "text" and delta.get("type") == "text_delta":
                block["text"] += str(delta.get("text") or "")
        elif kind == "message_delta":
            delta = data.get("delta") if isinstance(data.get("delta"), dict) else {}
            if delta.get("stop_reason") is not None:
                self.stop_reason = delta["stop_reason"]
            self._merge_usage(data.get("usage"))
        elif kind == "message_stop":
            self.stopped = True
        elif kind == "error":
            self.error = data.get("error") if isinstance(data.get("error"), dict) else {"type": "error"}
        # ping, content_block_stop and event types added later carry nothing this result needs


_LINE_END = re.compile(r"\r\n|\r|\n")


async def _sse_lines(response: httpx.Response) -> AsyncIterator[str]:
    """The body's lines split only on CR, LF or CRLF, as SSE defines them; httpx's `aiter_lines` also splits on U+2028,
    U+2029 and U+0085, which JSON text may carry unescaped. Bytes are decoded incrementally, so a character split
    across chunks stays whole, and a CR at a chunk's end waits for the next chunk in case an LF follows."""
    decoder, buffer = codecs.getincrementaldecoder("utf-8")(), ""
    async for chunk in response.aiter_bytes():
        buffer += decoder.decode(chunk)
        start = 0
        for end in _LINE_END.finditer(buffer):
            if end.group() == "\r" and end.end() == len(buffer):
                break  # maybe the first half of a CRLF
            yield buffer[start:end.start()]
            start = end.end()
        buffer = buffer[start:]
    buffer += decoder.decode(b"", final=True)
    for line in _LINE_END.split(buffer):
        yield line


async def _read_stream(response: httpx.Response, stream: _Stream) -> None:
    """Read server-sent events into `stream` until the message stops, an error event arrives or the body ends; what was
    read stays in `stream` when reading raises."""
    data_lines: list[str] = []

    def dispatch() -> None:
        if not data_lines:
            return
        payload = "\n".join(data_lines)
        data_lines.clear()
        try:
            data = json.loads(payload)
        except ValueError:
            stream.error = {"type": "invalid_event"}
            return
        if isinstance(data, dict):
            stream.event(data)

    async for line in _sse_lines(response):
        if line == "":
            dispatch()
        elif line.startswith("data:"):
            data_lines.append(line[5:].removeprefix(" "))
        if stream.stopped or stream.error is not None:
            return
    dispatch()

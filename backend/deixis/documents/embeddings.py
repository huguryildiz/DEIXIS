"""Passage embeddings for semantic passage retrieval (D27, D29).

The question and the text of included sources' passages are embedded by the provider chosen in Settings: the Gemini
API, the built-in model on this computer (slice 21, D103), the OpenAI API, or an embedding model on a local Ollama or LM
Studio server. Without a saved choice, Gemini is used when its key is set (D27); the built-in model is never chosen by
itself. Vectors are stored per passage and model at unit length, so a passage is embedded once per model. Similarity
only orders passages and records; it does not show that a passage supports a claim.

The workflow sends one batch per call and writes it before the next (slice 21). An HTTP 429 is waited out, a bounded
number of times per batch and within a wait budget the whole step shares (`RateBudget`); the wait is taken in one-second
slices so a pause, a cancel or a new scope revision stops it within a second. The constants were picked by hand: the
free tier's real limits were not measured.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import time
from array import array
from dataclasses import dataclass, field
from typing import Any, Callable

from deixis.documents import local_embedding

import httpx

from deixis.models.gemini import API_URL, error_message

MODEL = "gemini-embedding-2"
DIMENSIONS = 768
OPENAI_MODEL = "text-embedding-3-small"
OPENAI_URL = "https://api.openai.com/v1"
LOCAL_URLS = {"ollama": "http://127.0.0.1:11434/v1", "lm_studio": "http://127.0.0.1:1234/v1"}
KEY_ENVS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
PROVIDERS = ("gemini", "builtin", "openai", "ollama", "lm_studio", "off")
BUILTIN_MODEL = local_embedding.MODEL_ID
BATCH = 100
MAX_CHARS = 20_000  # passages are page chunks or abstracts, far below the model's 8,192-token input limit
EMBED_RATE_LIMIT_RETRIES = 3  # 429 waits per batch
EMBED_MAX_WAIT_SECONDS = 180  # 429 waits per step, across its batches and across a resume
DEFAULT_WAITS = (10, 20, 40)  # when neither Retry-After nor Gemini's RetryInfo says how long
_sleep = asyncio.sleep  # tests replace the clock
_clock = time.monotonic  # the wait counts the time that really passed, not the slices asked for


class EmbeddingError(Exception):
    pass


@dataclass
class RateBudget:
    """What a step may still wait for HTTP 429s, and what it has waited: kept in the step output, so a resumed step
    starts with what is left. `on_wait` persists it after each one-second slice; `stop` is the flow's checkpoint."""

    waited_seconds: float = 0.0
    rate_limited_waits: int = 0
    on_wait: Callable[["RateBudget"], None] | None = field(default=None, repr=False)

    @property
    def seconds_left(self) -> float:
        return max(0.0, EMBED_MAX_WAIT_SECONDS - self.waited_seconds)

    @classmethod
    def from_output(cls, output: dict[str, Any] | None, on_wait: Callable[["RateBudget"], None] | None = None) -> "RateBudget":
        output = output or {}
        return cls(float(output.get("waited_seconds") or 0), int(output.get("rate_limited_waits") or 0), on_wait)

    def counts(self) -> dict[str, Any]:
        return {"rate_limited_waits": self.rate_limited_waits, "waited_seconds": round(self.waited_seconds, 1)}

    async def wait(self, seconds: float, stop: Callable[[], None] | None) -> None:
        """Wait `seconds` in slices of at most one second, counting the time that really passed: a busy event loop
        that wakes late is charged what it took. The budget is checked after every wake: once the step has waited
        more than EMBED_MAX_WAIT_SECONDS, the wait ends with EmbeddingError and the batch is not sent again."""
        self.rate_limited_waits += 1
        left = seconds
        while left > 0:
            started = _clock()
            await _sleep(min(1.0, left))
            elapsed = max(0.0, _clock() - started)
            left -= elapsed
            self.waited_seconds += elapsed
            if self.on_wait:
                self.on_wait(self)
            if stop:
                stop()
            if self.waited_seconds > EMBED_MAX_WAIT_SECONDS:
                raise EmbeddingError(f"HTTP 429: rate limited; the waits passed the step's {EMBED_MAX_WAIT_SECONDS} s limit")


def retry_after(response: httpx.Response) -> float | None:
    """Seconds a 429 asks to wait: the Retry-After header, else Gemini's RetryInfo.retryDelay in the body."""
    header = response.headers.get("retry-after", "").strip()
    if re.fullmatch(r"\d+(\.\d+)?", header):
        return float(header)
    try:
        details = response.json()["error"]["details"]
    except (ValueError, KeyError, TypeError):
        return None
    for detail in details if isinstance(details, list) else []:
        delay = detail.get("retryDelay") if isinstance(detail, dict) else None
        if isinstance(delay, str) and (match := re.fullmatch(r"(\d+(?:\.\d+)?)s", delay.strip())):
            return float(match.group(1))
    return None


# Failures before any byte of the request can have left: the text was not sent.
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)


async def _send(send: Callable[[], Any], budget: RateBudget | None, stop: Callable[[], None] | None,
                on_sent: Callable[[], None] | None = None) -> httpx.Response:
    """One batch's request, sent again after each HTTP 429 the budget can wait out; any other failure raises.

    `on_sent` is called each time the request was issued: a reply came back (any status), or it failed after the
    connection was made (a write or read error, a timeout while waiting). A connection that was never made calls
    nothing."""
    retries = 0
    while True:
        # The persisted budget is read before every send, so a step resumed after a late wake past the limit (the
        # pause can land before `RateBudget.wait` checks it) does not send the refused batch again (Sol r3, finding 2).
        if budget is not None and budget.waited_seconds > EMBED_MAX_WAIT_SECONDS:
            raise EmbeddingError(f"HTTP 429: rate limited; the waits passed the step's {EMBED_MAX_WAIT_SECONDS} s limit "
                                 f"({budget.waited_seconds:g} s waited)")
        try:
            response = await send()
        except NOT_SENT as exc:
            raise EmbeddingError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        except httpx.HTTPError as exc:
            if on_sent:
                on_sent()
            raise EmbeddingError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        if on_sent:
            on_sent()
        if response.status_code != 429 or budget is None:
            return response
        if retries >= EMBED_RATE_LIMIT_RETRIES:
            raise EmbeddingError(f"HTTP 429: rate limited {retries + 1} times on one batch: {error_message(response)}")
        wait = retry_after(response)
        wait = DEFAULT_WAITS[min(retries, len(DEFAULT_WAITS) - 1)] if wait is None else wait
        if wait > budget.seconds_left:
            raise EmbeddingError(f"HTTP 429: rate limited; waiting {wait:g} s would pass the step's "
                                 f"{EMBED_MAX_WAIT_SECONDS} s limit ({budget.seconds_left:g} s left)")
        retries += 1
        await budget.wait(wait, stop)


def _vector(values: Any) -> list[float]:
    """One vector of a provider's reply: a non-empty list of finite numbers, else EmbeddingError (bad reply)."""
    if (not isinstance(values, list) or not values
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)):
        raise EmbeddingError("bad_reply: a vector is not a list of finite numbers")
    return values


def _checked(vectors: list[list[float]], count: int) -> list[array]:
    """A batch's vectors, only when the reply has one per text, all of one dimension; else EmbeddingError."""
    if len(vectors) != count:
        raise EmbeddingError(f"bad_reply: {len(vectors)} vectors for {count} texts")
    if len({len(v) for v in vectors}) > 1:
        raise EmbeddingError("bad_reply: the vectors differ in dimension")
    return [unit(v) for v in vectors]


def same_dimension(vectors: list[array], dimensions: int) -> None:
    """Every vector of a batch has the dimension the step's query vector had; else EmbeddingError (bad reply)."""
    wrong = sorted({len(v) for v in vectors if len(v) != dimensions})
    if wrong:
        raise EmbeddingError(f"bad_reply: vectors of {wrong[0]} dimensions where the query had {dimensions}")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise EmbeddingError("bad_reply: the reply is not JSON") from exc


def unit(values: list[float]) -> array:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return array("f", (v / norm for v in values))


def from_blob(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def similarity(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b))


async def embed(client: httpx.AsyncClient, key: str, texts: list[str], task_type: str,
                budget: RateBudget | None = None, stop: Callable[[], None] | None = None,
                on_sent: Callable[[], None] | None = None) -> list[array]:
    """Gemini: unit-length float32 vectors in input order; any failed batch raises EmbeddingError."""
    vectors: list[array] = []
    for start in range(0, len(texts), BATCH):
        requests = [{"model": f"models/{MODEL}", "content": {"parts": [{"text": text[:MAX_CHARS]}]}, "taskType": task_type,
                     "outputDimensionality": DIMENSIONS} for text in texts[start:start + BATCH]]
        response = await _send(lambda requests=requests: client.post(
            f"{API_URL}/models/{MODEL}:batchEmbedContents", json={"requests": requests},
            headers={"x-goog-api-key": key}, timeout=60), budget, stop, on_sent)
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {error_message(response)}")
        body = _json(response)
        items = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise EmbeddingError("bad_reply: the reply has no embeddings")
        vectors += _checked([_vector(item.get("values") if isinstance(item, dict) else None) for item in items], len(requests))
    return vectors


async def embed_openai_compatible(client: httpx.AsyncClient, base_url: str, key: str | None, model: str,
                                  texts: list[str], budget: RateBudget | None = None,
                                  stop: Callable[[], None] | None = None,
                                  on_sent: Callable[[], None] | None = None) -> list[array]:
    """OpenAI's /embeddings shape, also served by Ollama and LM Studio; any failed batch raises EmbeddingError."""
    vectors: list[array] = []
    for start in range(0, len(texts), BATCH):
        chunk = [t[:MAX_CHARS] for t in texts[start:start + BATCH]]
        response = await _send(lambda chunk=chunk: client.post(
            f"{base_url}/embeddings", timeout=120, json={"model": model, "input": chunk},
            headers={"Authorization": f"Bearer {key}"} if key else {}), budget, stop, on_sent)
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {error_message(response)}")
        body = _json(response)
        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise EmbeddingError("bad_reply: the reply has no data")
        if sorted(item.get("index") for item in items if isinstance(item.get("index"), int)) != list(range(len(chunk))):
            raise EmbeddingError(f"bad_reply: the reply's indexes are not 0 to {len(chunk) - 1}")
        vectors += _checked([_vector(item.get("embedding")) for item in sorted(items, key=lambda d: d["index"])], len(chunk))
    return vectors


def chosen(setting: dict[str, Any] | None) -> tuple[str, str | None]:
    """The provider and model semantic search uses: the saved choice, else Gemini when its key is set, else off."""
    if setting:
        return setting["provider"], setting.get("model")
    return ("gemini", MODEL) if os.environ.get(KEY_ENVS["gemini"]) else ("off", None)


@dataclass(frozen=True)
class Embedder:
    provider: str
    model: str
    local: Any = field(default=None, compare=False)  # documents.local_embedding.LocalEmbedder for "builtin"

    @property
    def stored_model(self) -> str:
        # Gemini rows written before D29 are stored under the bare model name.
        return self.model if self.provider == "gemini" else f"{self.provider}:{self.model}"

    @classmethod
    def from_identity(cls, provider: str, stored_model: str, local: Any = None) -> "Embedder":
        """The embedder a step froze, rebuilt from its stored `provider` and `stored_model`."""
        model = stored_model if provider == "gemini" else stored_model.split(":", 1)[1]
        return cls(provider, model, local)

    @property
    def batch(self) -> int:
        return local_embedding.LOCAL_BATCH if self.provider == "builtin" else BATCH

    async def embed(self, client: httpx.AsyncClient, texts: list[str], task_type: str,
                    budget: RateBudget | None = None, stop: Callable[[], None] | None = None,
                    on_sent: Callable[[], None] | None = None) -> list[array]:
        """One batch's vectors. The built-in model goes to the local embedder and never over the network, so it never
        calls `on_sent`; for the others `on_sent` is called each time the request was issued."""
        if self.provider == "builtin":
            if self.local is None:
                raise EmbeddingError("builtin_unavailable: the built-in model is not set up in this process")
            try:
                vectors = await self.local.embed(texts, "query" if task_type == "RETRIEVAL_QUERY" else "document")
            except local_embedding.LocalEmbeddingError as exc:
                raise EmbeddingError(str(exc)) from exc
            return _checked([_vector(list(v)) for v in vectors], len(texts))
        if self.provider in KEY_ENVS:
            key = os.environ.get(KEY_ENVS[self.provider])
            if not key:
                raise EmbeddingError(f"{KEY_ENVS[self.provider]} is not set")
            if self.provider == "gemini":
                return await embed(client, key, texts, task_type, budget, stop, on_sent)
            return await embed_openai_compatible(client, OPENAI_URL, key, self.model, texts, budget, stop, on_sent)
        return await embed_openai_compatible(client, LOCAL_URLS[self.provider], None, self.model, texts, budget, stop, on_sent)


def builtin_option(state: dict[str, Any] | None) -> dict[str, Any]:
    """The built-in model as a choice: available only when installed and its files passed the last full check and
    have not changed since (`EmbeddingService.option`)."""
    state = state or {"available": False, "reason": "Not downloaded", "reason_code": "not_installed",
                      "last_full_check": None}
    return {"provider": "builtin", "models": [BUILTIN_MODEL], **state}


def options(local_tools: dict[str, Any], builtin: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Each provider with the models it offers now and, when it cannot be chosen, why. Order: Gemini, the built-in
    model, OpenAI, Ollama, LM Studio, off (slice 21: Off stays last)."""
    servers = {t["id"]: t for t in local_tools["tools"]}
    result = [
        {"provider": "gemini", "models": [MODEL], "available": bool(os.environ.get(KEY_ENVS["gemini"])),
         "reason": None if os.environ.get(KEY_ENVS["gemini"]) else "Add a Gemini API key"},
        builtin_option(builtin),
        {"provider": "openai", "models": [OPENAI_MODEL], "available": bool(os.environ.get(KEY_ENVS["openai"])),
         "reason": None if os.environ.get(KEY_ENVS["openai"]) else "Add an OpenAI API key"},
    ]
    for provider in ("ollama", "lm_studio"):
        server = servers[provider]
        models = [m["id"] for m in server.get("models", []) if m["embedding"]]
        reason = (None if server["running"] and models
                  else f"{server['name']} lists no embedding model" if server["running"]
                  else f"{server['name']} is not running" if server["installed"]
                  else f"{server['name']} is not installed")
        result.append({"provider": provider, "models": models, "available": reason is None, "reason": reason})
    return result + [{"provider": "off", "models": [], "available": True, "reason": None}]

"""Passage embeddings for semantic passage retrieval (D27, D29).

The question and the text of included sources' passages are embedded by the provider chosen in Settings: the Gemini
API, the built-in model on this computer (slice 21, D103; Qwen3-Embedding-0.6B), the OpenAI API, the Voyage API, the Cohere API, or an
embedding model on a local Ollama or LM Studio server. Without a saved choice, Gemini is used when its key is set (D27),
else the built-in model when it is downloaded and checked (D7); Voyage and Cohere are used only when chosen. Vectors are stored per passage and model at unit length, so a passage is embedded once per model. Similarity
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

from deixis.keys import key_verification
from deixis.documents import local_embedding

import httpx

from deixis.models.gemini import API_URL, error_message
from deixis.models.openai_compat import loopback_client
from deixis.providers.common import redact

MODEL = "gemini-embedding-2"
DIMENSIONS = 768
OPENAI_MODEL = "text-embedding-3-small"
OPENAI_URL = "https://api.openai.com/v1"
# Voyage (docs.voyageai.com, read 17 Oct 2026): up to 1,000 texts and 1M tokens per request for voyage-4-lite (the
# cheapest of the 4 series, $0.02 per million tokens; the owner's choice on 17 Oct),
# 32K tokens per text, `input_type` query or document. Over-long input is refused (`truncation: false`), never cut.
VOYAGE_URL = "https://api.voyageai.com/v1"
VOYAGE_MODEL = "voyage-4-lite"
VOYAGE_DIMENSIONS = 1024  # the model's default output; part of the stored identity
VOYAGE_BATCH = 128  # texts per request, far below the API's 1,000
VOYAGE_REQUEST_TOKENS = 100_000  # estimated tokens per request, far under the API's 1M
# Cohere (docs.cohere.com/reference/embed, read 17 Oct 2026): /v2/embed takes at most 96 texts per call with
# `input_type` search_query or search_document; embed-v5.0-fast reads 128K tokens per text and its output dimension is
# one of 256 to 2048. Over-long input is refused (`truncate: NONE`), never cut. The price was not on Cohere's pages.
COHERE_URL = "https://api.cohere.com/v2"
COHERE_MODEL = "embed-v5.0-fast"
COHERE_DIMENSIONS = 1024  # asked for in every request; part of the stored identity
COHERE_BATCH = 96  # the API's own limit
LOCAL_URLS = {"ollama": "http://127.0.0.1:11434/v1", "lm_studio": "http://127.0.0.1:1234/v1"}
KEY_ENVS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "voyage": "VOYAGE_API_KEY", "cohere": "COHERE_API_KEY"}
PROVIDERS = ("gemini", "builtin", "openai", "voyage", "cohere", "ollama", "lm_studio", "off")
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
                on_sent: Callable[[], None] | None = None, secret: str | None = None) -> httpx.Response:
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
            raise EmbeddingError(f"HTTP 429: rate limited {retries + 1} times on one batch: {redact(error_message(response), secret)}")
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
            headers={"x-goog-api-key": key}, timeout=60), budget, stop, on_sent, key)
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {redact(error_message(response), key)}")
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
            headers={"Authorization": f"Bearer {key}"} if key else {}), budget, stop, on_sent, key)
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {redact(error_message(response), key)}")
        body = _json(response)
        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise EmbeddingError("bad_reply: the reply has no data")
        if (len(items) != len(chunk) or any(type(item.get("index")) is not int for item in items)
                or sorted(item["index"] for item in items) != list(range(len(chunk)))):
            raise EmbeddingError(f"bad_reply: the reply's indexes are not 0 to {len(chunk) - 1}")
        vectors += _checked([_vector(item.get("embedding")) for item in sorted(items, key=lambda d: d["index"])], len(chunk))
    return vectors


def estimated_tokens(text: str) -> int:
    """A generous token estimate (one per three characters) for keeping a request under a token cap; not a count."""
    return len(text) // 3 + 1


def voyage_batches(texts: list[str]) -> list[list[str]]:
    """Consecutive slices of at most VOYAGE_BATCH texts and VOYAGE_REQUEST_TOKENS estimated tokens (one text alone may
    pass the estimate; the API then refuses it rather than cutting it)."""
    batches: list[list[str]] = []
    current: list[str] = []
    tokens = 0
    for text in texts:
        cost = estimated_tokens(text)
        if current and (len(current) >= VOYAGE_BATCH or tokens + cost > VOYAGE_REQUEST_TOKENS):
            batches.append(current)
            current, tokens = [], 0
        current.append(text)
        tokens += cost
    return batches + ([current] if current else [])


async def embed_voyage(client: httpx.AsyncClient, key: str, model: str, texts: list[str], task_type: str,
                       budget: RateBudget | None = None, stop: Callable[[], None] | None = None,
                       on_sent: Callable[[], None] | None = None, report: dict[str, int] | None = None) -> list[array]:
    """Voyage's /embeddings: unit-length vectors in input order; `report` gets the tokens Voyage counted."""
    vectors: list[array] = []
    for chunk in voyage_batches(texts):
        body = {"input": chunk, "model": model, "input_type": "query" if task_type == "RETRIEVAL_QUERY" else "document",
                "truncation": False, "output_dimension": VOYAGE_DIMENSIONS, "output_dtype": "float"}
        response = await _send(lambda body=body: client.post(
            f"{VOYAGE_URL}/embeddings", timeout=120, json=body, headers={"Authorization": f"Bearer {key}"}),
            budget, stop, on_sent, key)
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {redact(error_message(response), key)}")
        reply = _json(response)
        items = reply.get("data") if isinstance(reply, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise EmbeddingError("bad_reply: the reply has no data")
        if (len(items) != len(chunk) or any(type(item.get("index")) is not int for item in items)
                or sorted(item["index"] for item in items) != list(range(len(chunk)))):
            raise EmbeddingError(f"bad_reply: the reply's indexes are not 0 to {len(chunk) - 1}")
        batch = _checked([_vector(item.get("embedding")) for item in sorted(items, key=lambda d: d["index"])], len(chunk))
        if any(len(v) != VOYAGE_DIMENSIONS for v in batch):
            raise EmbeddingError(f"bad_reply: vectors of another dimension than {VOYAGE_DIMENSIONS}")
        vectors += batch
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
        if report is not None and isinstance(usage.get("total_tokens"), int):
            report["provider_tokens"] = report.get("provider_tokens", 0) + usage["total_tokens"]
    return vectors


async def embed_cohere(client: httpx.AsyncClient, key: str, model: str, texts: list[str], task_type: str,
                       budget: RateBudget | None = None, stop: Callable[[], None] | None = None,
                       on_sent: Callable[[], None] | None = None, report: dict[str, int] | None = None) -> list[array]:
    """Cohere's /v2/embed: float vectors in input order (the reply gives no index; its list is in input order), made
    unit length here; `report` gets the input tokens Cohere billed."""
    vectors: list[array] = []
    for start in range(0, len(texts), COHERE_BATCH):
        chunk = texts[start:start + COHERE_BATCH]
        body = {"model": model, "texts": chunk, "embedding_types": ["float"], "truncate": "NONE",
                "input_type": "search_query" if task_type == "RETRIEVAL_QUERY" else "search_document",
                "output_dimension": COHERE_DIMENSIONS}
        response = await _send(lambda body=body: client.post(
            f"{COHERE_URL}/embed", timeout=120, json=body, headers={"Authorization": f"Bearer {key}"}),
            budget, stop, on_sent, key)
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {redact(error_message(response), key)}")
        reply = _json(response)
        found = reply.get("embeddings") if isinstance(reply, dict) else None
        items = found.get("float") if isinstance(found, dict) else None
        if not isinstance(items, list):
            raise EmbeddingError("bad_reply: the reply has no float embeddings")
        batch = _checked([_vector(item) for item in items], len(chunk))
        if any(len(v) != COHERE_DIMENSIONS for v in batch):
            raise EmbeddingError(f"bad_reply: vectors of another dimension than {COHERE_DIMENSIONS}")
        vectors += batch
        meta = reply.get("meta") if isinstance(reply.get("meta"), dict) else {}
        billed = meta.get("billed_units") if isinstance(meta.get("billed_units"), dict) else {}
        if report is not None and isinstance(billed.get("input_tokens"), (int, float)) and not isinstance(billed.get("input_tokens"), bool):
            report["provider_tokens"] = report.get("provider_tokens", 0) + int(billed["input_tokens"])
    return vectors


def client_for(provider: str, deps: Any) -> httpx.AsyncClient:
    """The client an embedding request goes through. Ollama and LM Studio run on this computer and their requests carry
    passage text, so they use the loopback client (D34: no proxy from the environment, no redirects), never the shared
    one, which honours HTTP_PROXY/ALL_PROXY. `deps` is the flow's FlowDeps; one without a loopback client gets one."""
    if provider not in LOCAL_URLS:
        return deps.http
    if getattr(deps, "local_http", None) is None:
        deps.local_http = loopback_client()
    return deps.local_http


def chosen(setting: dict[str, Any] | None) -> tuple[str, str | None]:
    """The provider and model semantic search uses: the saved choice, else Gemini when its key is set, else the
    built-in model when it is downloaded and its files check out (D7), else off. Downloading it is the person's act;
    nothing here downloads it."""
    if setting:
        if setting["provider"] == "builtin":
            # The built-in model is the one this DEIXIS ships: a choice saved for an earlier one (bge-small) stays the
            # built-in choice, under the new model's identity, so its stored vectors are never read as these.
            return "builtin", BUILTIN_MODEL
        return setting["provider"], setting.get("model")
    if os.environ.get(KEY_ENVS["gemini"]):
        return "gemini", MODEL
    return ("builtin", BUILTIN_MODEL) if local_embedding.builtin_available() else ("off", None)


@dataclass(frozen=True)
class Embedder:
    provider: str
    model: str
    local: Any = field(default=None, compare=False)  # documents.local_embedding.LocalEmbedder for "builtin"

    @property
    def stored_model(self) -> str:
        # Gemini rows written before D29 are stored under the bare model name. Voyage's and Cohere's carry their output
        # dimension.
        if self.provider == "gemini":
            return self.model
        dimensions = {"voyage": VOYAGE_DIMENSIONS, "cohere": COHERE_DIMENSIONS}.get(self.provider)
        return f"{self.provider}:{self.model}@{dimensions}" if dimensions else f"{self.provider}:{self.model}"

    @classmethod
    def from_identity(cls, provider: str, stored_model: str, local: Any = None) -> "Embedder":
        """The embedder a step froze, rebuilt from its stored `provider` and `stored_model`."""
        model = stored_model if provider == "gemini" else stored_model.split(":", 1)[1]
        if provider in ("voyage", "cohere"):
            model = model.rsplit("@", 1)[0]
        return cls(provider, model, local)

    @property
    def batch(self) -> int:
        return (local_embedding.LOCAL_BATCH if self.provider == "builtin"
                else VOYAGE_BATCH if self.provider == "voyage" else COHERE_BATCH if self.provider == "cohere" else BATCH)

    async def embed(self, client: httpx.AsyncClient, texts: list[str], task_type: str,
                    budget: RateBudget | None = None, stop: Callable[[], None] | None = None,
                    on_sent: Callable[[], None] | None = None, report: dict[str, int] | None = None) -> list[array]:
        """One batch's vectors. The built-in model goes to the local embedder and never over the network, so it never
        calls `on_sent`; for the others `on_sent` is called each time the request was issued. `report`, when given,
        gets `truncated_texts` (built-in: texts cut at its token limit) and `provider_tokens` (Voyage's and Cohere's usage)."""
        if self.provider == "builtin":
            if self.local is None:
                raise EmbeddingError("builtin_unavailable: the built-in model is not set up in this process")
            if self.model.split(":threads=", 1)[0] != local_embedding.MODEL_ID:
                # A step frozen with an earlier built-in model (bge-small): its vectors are not these, so nothing is
                # embedded under its name (the next run embeds with the current model).
                raise EmbeddingError("builtin_model_changed: this step used an earlier built-in model; run it again")
            threads = self.model.rsplit(":threads=", 1)[1] if ":threads=" in self.model else None
            token = local_embedding.RUNNER_THREADS.set(int(threads)) if threads is not None else None
            try:
                vectors = await self.local.embed(texts, "query" if task_type == "RETRIEVAL_QUERY" else "document", report)
            except local_embedding.LocalEmbeddingError as exc:
                raise EmbeddingError(str(exc)) from exc
            finally:
                if token is not None:
                    local_embedding.RUNNER_THREADS.reset(token)
            return _checked([_vector(list(v)) for v in vectors], len(texts))
        if self.provider in KEY_ENVS:
            key = os.environ.get(KEY_ENVS[self.provider])
            if not key:
                raise EmbeddingError(f"{KEY_ENVS[self.provider]} is not set")
            if not key_verification.is_valid_key(key):  # a header cannot carry it; nothing is sent
                raise EmbeddingError(f"{KEY_ENVS[self.provider]} is not a valid key")
            if self.provider == "gemini":
                return await embed(client, key, texts, task_type, budget, stop, on_sent)
            if self.provider == "voyage":
                return await embed_voyage(client, key, self.model, texts, task_type, budget, stop, on_sent, report)
            if self.provider == "cohere":
                return await embed_cohere(client, key, self.model, texts, task_type, budget, stop, on_sent, report)
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
    model, OpenAI, Voyage, Cohere, Ollama, LM Studio, off (slice 21: Off stays last)."""
    servers = {t["id"]: t for t in local_tools["tools"]}
    result = [
        {"provider": "gemini", "models": [MODEL], "available": bool(os.environ.get(KEY_ENVS["gemini"])),
         "reason": None if os.environ.get(KEY_ENVS["gemini"]) else "Add a Gemini API key"},
        builtin_option(builtin),
        {"provider": "openai", "models": [OPENAI_MODEL], "available": bool(os.environ.get(KEY_ENVS["openai"])),
         "reason": None if os.environ.get(KEY_ENVS["openai"]) else "Add an OpenAI API key"},
        {"provider": "voyage", "models": [VOYAGE_MODEL], "available": bool(os.environ.get(KEY_ENVS["voyage"])),
         "reason": None if os.environ.get(KEY_ENVS["voyage"]) else "Add a Voyage API key"},
        {"provider": "cohere", "models": [COHERE_MODEL], "available": bool(os.environ.get(KEY_ENVS["cohere"])),
         "reason": None if os.environ.get(KEY_ENVS["cohere"]) else "Add a Cohere API key"},
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

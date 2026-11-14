"""Reranking: a second ordering of the first records of the fused ranking (a built-in catalog reranker run by llama.cpp,
Voyage, Cohere, Jina or ZeroEntropy).

A reranker reads the question and each candidate's title and abstract and gives a relevance score. It is used in one
place only in this version: the order in which an `sw` run's records are read (`small_batch.freeze_list`). It never
includes, excludes or decides anything; the person's own included records stay first whatever it says, and its score
is a priority signal, not evidence. Passage ranking for answers is not reranked.

The setting is separate from the embedding provider, so any embedding (or none) can go with either reranker. With
nothing saved, Voyage rerank-3-lite is on; without a Voyage key nothing is sent, the run records
`reranker_unavailable` and keeps the fused order. A saved setting, "off" included, always wins.
A failed, timed-out or stopped rerank never falls back to another reranker; the fused order is used and the step says
so. A built-in choice is `(builtin, catalog id)`; one saved before the catalog (no model, or an earlier model) is never
mapped to a catalog reranker: the rerank fails with `builtin_model_changed` until the person picks one. The built-in
rerankers return raw scores (any sign or size); only their order is used.

Voyage's rerank API (docs.voyageai.com, read 17 Oct 2026): up to 1,000 documents; per document the query and the
document may hold 32,000 tokens together; in all "query tokens × documents + document tokens" may be 600K for
rerank-3-lite. Over-long input is refused (`truncation: false`), never cut.

The other APIs (docs read 17 Oct 2026; prices were not on Cohere's or Jina's own pages):
- Cohere /v2/rerank, rerank-v4.0-fast: up to 1,000 documents per request is the advice; a document past
  `max_tokens_per_doc` (4,096) would be cut, so a record whose estimated tokens pass it is refused before sending.
  Billed in search units (one query with up to 100 documents), recorded as `provider_search_units`.
- Jina /v1/rerank, jina-reranker-v3.5 (now run by Elastic): 131K context; usage tokens recorded.
- ZeroEntropy /v1/models/rerank, zerank-2: at most 5,000,000 bytes per request (each document counts 150 bytes plus
  the query and the document), so requests are split by bytes; `total_tokens` recorded.
Each returns `results[]` with `index` and `relevance_score`; a reply that does not score every document once is
refused.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from deixis.documents import builtin_catalog, local_embedding
from deixis.keys import key_verification
from deixis.models.gemini import error_message
from deixis.providers.common import redact

SETTING = "reranking"
PROVIDERS = ("builtin", "voyage", "cohere", "jina", "zeroentropy")
VOYAGE_MODEL = "rerank-3-lite"  # the cheaper Voyage reranker ($0.02 per million tokens; owner, 17 Oct)
VOYAGE_URL = "https://api.voyageai.com/v1"
COHERE_URL = "https://api.cohere.com/v2"
MAX_WAIT_SECONDS = 180
RATE_LIMIT_RETRIES = 3
DEFAULT_WAITS = (10, 20, 40)
_sleep = asyncio.sleep
_clock = time.monotonic
COHERE_MODEL = "rerank-v4.0-fast"
COHERE_MAX_DOC_TOKENS = 4096  # Cohere's default `max_tokens_per_doc`; past it a document would be cut
JINA_URL = "https://api.jina.ai/v1"
JINA_MODEL = "jina-reranker-v3.5"
ZEROENTROPY_URL = "https://api.zeroentropy.dev/v1"
ZEROENTROPY_MODEL = "zerank-2"
ZEROENTROPY_REQUEST_BYTES = 4_000_000  # per request, under the API's 5,000,000
KEY_ENVS = {"voyage": "VOYAGE_API_KEY", "cohere": "COHERE_API_KEY", "jina": "JINA_API_KEY", "zeroentropy": "ZEROENTROPY_API_KEY"}
MODELS = {"voyage": VOYAGE_MODEL, "cohere": COHERE_MODEL, "jina": JINA_MODEL, "zeroentropy": ZEROENTROPY_MODEL}
NAMES = {"voyage": "Voyage AI", "cohere": "Cohere", "jina": "Jina AI", "zeroentropy": "ZeroEntropy"}
VOYAGE_TOTAL_TOKENS = 500_000  # estimated "query × documents + documents" per request, under the API's 600K
# How many records are reranked, as a multiple of how many a run reads (the depth's N): 2 means the reranker sees twice
# what is read, so a record just below the read cutoff can move above it and one above can move out. 1 only reorders
# what would be read anyway. On 100 BioASQ questions reranking the first 200 of a Standard run (factor 4) raised
# recall@50 about twice as much as the first 100 (factor 2), for Qwen3 and Voyage alike. Since rerank rule version 2
# the default
# is 8 (400 at Standard, the MAX_CANDIDATES cap), so a work the fused order put between 200 and 400 can still be lifted;
# 8 was not measured. A run reads its factor through the rule its budget froze (`small_batch.rerank_choice`): a budget
# frozen earlier keeps 4 and never more.
DEFAULT_POOL_FACTOR = 8.0
MIN_POOL_FACTOR, MAX_POOL_FACTOR = 1.0, 8.0
MAX_CANDIDATES = 400  # never more records than this in one rerank, whatever the depth and factor
DEFAULT_TIMEOUT_SECONDS = 180
MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS = 10, 900
MAX_DOCUMENT_CHARS = 20_000  # a title and abstract longer than this is cut here, and the cut is counted


class RerankerTransportError(Exception):
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
        return max(0.0, MAX_WAIT_SECONDS - self.waited_seconds)


    def counts(self) -> dict[str, Any]:
        return {"rate_limited_waits": self.rate_limited_waits, "waited_seconds": round(self.waited_seconds, 1)}

    async def wait(self, seconds: float, stop: Callable[[], None] | None) -> None:
        """Wait `seconds` in slices of at most one second, counting the time that really passed: a busy event loop
        that wakes late is charged what it took. The budget is checked after every wake: once the step has waited
        more than MAX_WAIT_SECONDS, the wait ends with RerankerTransportError and the batch is not sent again."""
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
            if self.waited_seconds > MAX_WAIT_SECONDS:
                raise RerankerTransportError(f"HTTP 429: rate limited; the waits passed the step's {MAX_WAIT_SECONDS} s limit")


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
        if budget is not None and budget.waited_seconds > MAX_WAIT_SECONDS:
            raise RerankerTransportError(f"HTTP 429: rate limited; the waits passed the step's {MAX_WAIT_SECONDS} s limit "
                                 f"({budget.waited_seconds:g} s waited)")
        try:
            response = await send()
        except NOT_SENT as exc:
            raise RerankerTransportError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        except httpx.HTTPError as exc:
            if on_sent:
                on_sent()
            raise RerankerTransportError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        if on_sent:
            on_sent()
        if response.status_code != 429 or budget is None:
            return response
        if retries >= RATE_LIMIT_RETRIES:
            raise RerankerTransportError(f"HTTP 429: rate limited {retries + 1} times on one batch: {redact(error_message(response), secret)}")
        wait = retry_after(response)
        wait = DEFAULT_WAITS[min(retries, len(DEFAULT_WAITS) - 1)] if wait is None else wait
        if wait > budget.seconds_left:
            raise RerankerTransportError(f"HTTP 429: rate limited; waiting {wait:g} s would pass the step's "
                                 f"{MAX_WAIT_SECONDS} s limit ({budget.seconds_left:g} s left)")
        retries += 1
        await budget.wait(wait, stop)



def estimated_tokens(text: str) -> int:
    return len(text) // 3 + 1


class RerankError(Exception):
    """`reranker_failed`, `reranker_timeout`, `reranker_bad_reply` or `reranker_unavailable`, with what happened."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Choice:
    provider: str
    model: str
    pool_factor: float
    timeout_seconds: int

    def identity(self) -> dict[str, Any]:
        found = {"provider": self.provider, "model": self.model, "pool_factor": self.pool_factor,
                 "timeout_seconds": self.timeout_seconds}
        if self.provider == "builtin":
            model = builtin_catalog.resolve(self.model, "reranker")
            found |= {"model_identity": builtin_catalog.identity(model) if model else None, **local_embedding.provenance()}
        return found

    def pool_size(self, read_top: int) -> int:
        """How many records of the automatic order are reranked when a run reads its first `read_top`."""
        return min(MAX_CANDIDATES, math.ceil(read_top * self.pool_factor))


# With nothing saved, Voyage rerank-3-lite reorders the records (owner, 18 Oct): on the owner's settings it raised
# recall@50 on BioASQ 100 and LitSearch 200, the lower 95% bound above zero on both. Without a Voyage key it cannot run:
# the run records `reranker_unavailable` and keeps the fused order, and Settings and the research say so.
DEFAULT_SETTING = {"enabled": True, "provider": "voyage"}


def setting_in_force(saved: dict[str, Any] | None) -> dict[str, Any]:
    """The saved reranking setting, or the default when the person never saved one; a saved "off" stays off."""
    return DEFAULT_SETTING if saved is None else saved


def chosen(setting: dict[str, Any] | None) -> Choice | None:
    """The reranker the setting in force turns on, or None when it is off. Nothing saved means the default."""
    setting = setting_in_force(setting)
    if not setting.get("enabled") or setting.get("provider") not in PROVIDERS:
        return None
    model = (setting.get("model") or builtin_catalog.NO_MODEL) if setting["provider"] == "builtin" else MODELS[setting["provider"]]
    return Choice(setting["provider"], model, float(setting.get("pool_factor") or DEFAULT_POOL_FACTOR),
                  int(setting.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))


def options(builtin: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Each reranker with whether it can be turned on now, why not, and what it sends where; each built-in catalog
    reranker is an entry of its own (`LocalModelService.options("reranker")`)."""
    found = {s["model"]: s for s in builtin or []}

    def local(model: builtin_catalog.Model) -> dict[str, Any]:
        state = found.get(model.id) or {"available": False, "reason": "Not downloaded", "reason_code": "not_installed"}
        return {"provider": "builtin", "model": model.id, "name": model.name, "available": bool(state.get("available")),
                "reason": None if state.get("available") else state.get("reason") or "Not downloaded",
                "reason_code": None if state.get("available") else state.get("reason_code"), "sends": None}

    def api(provider: str) -> dict[str, Any]:
        keyed = bool(os.environ.get(KEY_ENVS[provider]))
        return {"provider": provider, "model": MODELS[provider], "available": keyed,
                "reason": None if keyed else f"Add a {NAMES[provider].removesuffix(' AI')} API key",
                "sends": f"The question and the title and abstract of each reranked record, to {NAMES[provider]}"}
    return [
        *(local(model) for model in builtin_catalog.of_kind("reranker")),
        *(api(provider) for provider in ("voyage", "cohere", "jina", "zeroentropy")),
    ]


def blocked(choice: Choice | None, offered: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Why the reranker in force cannot run now (its option is not available, e.g. no Voyage key), or None."""
    if choice is None:
        return None
    option = next((o for o in offered if o["provider"] == choice.provider
                   and (choice.provider != "builtin" or o["model"] == choice.model)), None)
    if option is None:
        return {"reason_code": "not_offered", "reason": f"{choice.provider} {choice.model} is not offered"}
    if option["available"]:
        return None
    return {"reason_code": option.get("reason_code") or "key_missing", "reason": option["reason"]}


def can_run(choice: Choice, local: Any) -> bool:
    """Whether a rerank with `choice` would be sent at all, read as `_rerank` reads it before sending (no request)."""
    if choice.provider == "builtin":
        return local is not None and builtin_catalog.resolve(choice.model, "reranker") is not None
    key = os.environ.get(KEY_ENVS[choice.provider])
    return bool(key) and key_verification.is_valid_key(key)


def document(title: str | None, abstract: str | None) -> str:
    """What a reranker reads for one record: its title, then its abstract when it has one."""
    return "\n\n".join(part for part in ((title or "").strip(), (abstract or "").strip()) if part)




async def rerank(choice: Choice, client: httpx.AsyncClient, local: Any, query: str, documents: list[str],
                 stop: Callable[[], None] | None = None) -> dict[str, Any]:
    """Scores in input order, with `truncated` (built-in: documents cut at its token limit), `cut_documents` (records
    cut at MAX_DOCUMENT_CHARS here, for every reranker) and `provider_tokens` (Voyage's usage). Raises RerankError; the
    caller bounds the time and keeps the fused order on failure.

    A record's "abstract" is sometimes a whole article (an OpenAlex abstract holding the body text). Refusing it would
    leave every other record of the run unreranked, so it is cut to its first MAX_DOCUMENT_CHARS characters, which
    hold its title and opening, and counted."""
    if not documents:
        return {"scores": [], "truncated": 0, "cut_documents": 0, "provider_tokens": None}
    cut = sum(len(text) > MAX_DOCUMENT_CHARS for text in documents)
    documents = [text[:MAX_DOCUMENT_CHARS] for text in documents]
    return await _rerank(choice, client, local, query, documents, stop) | {"cut_documents": cut}


async def _rerank(choice: Choice, client: httpx.AsyncClient, local: Any, query: str, documents: list[str],
                  stop: Callable[[], None] | None) -> dict[str, Any]:
    if choice.provider == "builtin":
        model = builtin_catalog.resolve(choice.model, "reranker")
        if model is None:
            raise RerankError("reranker_unavailable", "builtin_model_changed: the saved built-in reranker is not one "
                                                      "this DEIXIS runs; choose a built-in reranker in Settings")
        if local is None:
            raise RerankError("reranker_unavailable", "the built-in model is not set up in this process")
        try:
            scores, cut = await local.rerank(model.id, query, documents, choice.timeout_seconds)
        except local_embedding.LocalEmbeddingError as exc:
            code = {"builtin_timeout": "reranker_timeout", "builtin_model_changed": "reranker_unavailable"}.get(exc.code, "reranker_failed")
            raise RerankError(code, str(exc)) from exc
        return {"scores": scores, "truncated": len(cut), "provider_tokens": None}
    env = KEY_ENVS[choice.provider]
    key = os.environ.get(env)
    if not key:
        raise RerankError("reranker_unavailable", f"{env} is not set")
    if not key_verification.is_valid_key(key):  # a header cannot carry it; nothing is sent
        raise RerankError("reranker_unavailable", f"{env} is not a valid key")
    if choice.provider == "voyage":
        return await rerank_voyage(client, key, query, documents, stop)
    if choice.provider == "cohere":
        q = estimated_tokens(query)
        long = [i for i, text in enumerate(documents) if q + estimated_tokens(text) > COHERE_MAX_DOC_TOKENS]
        if long:  # Cohere would cut them; refused instead, never cut
            raise RerankError("reranker_failed", f"{len(long)} record(s) longer than Cohere reads in one document")
        return await rerank_results(client, key, f"{COHERE_URL}/rerank", query, documents, [list(range(len(documents)))],
                                    lambda docs: {"model": COHERE_MODEL, "query": query, "documents": docs, "top_n": len(docs),
                                                  "max_tokens_per_doc": COHERE_MAX_DOC_TOKENS}, stop)
    if choice.provider == "jina":
        return await rerank_results(client, key, f"{JINA_URL}/rerank", query, documents, [list(range(len(documents)))],
                                    lambda docs: {"model": JINA_MODEL, "query": query, "documents": docs, "top_n": len(docs),
                                                  "return_documents": False}, stop)
    return await rerank_results(client, key, f"{ZEROENTROPY_URL}/models/rerank", query, documents,
                                zeroentropy_batches(query, documents),
                                lambda docs: {"model": ZEROENTROPY_MODEL, "query": query, "documents": docs, "top_n": len(docs)}, stop)


def zeroentropy_batches(query: str, documents: list[str]) -> list[list[int]]:
    """Indexes of `documents` per request, each request under ZEROENTROPY_REQUEST_BYTES as ZeroEntropy counts them
    (150 bytes plus the query plus the document, per document)."""
    q = len(query.encode())
    batches: list[list[int]] = []
    current: list[int] = []
    total = 0
    for i, text in enumerate(documents):
        cost = 150 + q + len(text.encode())
        if current and total + cost > ZEROENTROPY_REQUEST_BYTES:
            batches.append(current)
            current, total = [], 0
        current.append(i)
        total += cost
    return batches + ([current] if current else [])


async def rerank_results(client: httpx.AsyncClient, key: str, url: str, query: str, documents: list[str],
                         batches: list[list[int]], body_of: Callable[[list[str]], dict[str, Any]],
                         stop: Callable[[], None] | None = None) -> dict[str, Any]:
    """Cohere's, Jina's and ZeroEntropy's rerank: `results[]` with `index` and `relevance_score`, every document of a
    request scored once. HTTP 429 is waited out a bounded number of times, as for Voyage. Usage: Jina's
    `usage.total_tokens`, ZeroEntropy's `total_tokens`, Cohere's `meta.billed_units.search_units`."""
    scores: list[float | None] = [None] * len(documents)
    tokens: int | None = None
    units: int | None = None
    budget = RateBudget()
    for indexes in batches:
        body = body_of([documents[i] for i in indexes])
        try:
            response = await _send(lambda body=body: client.post(
                url, timeout=120, json=body, headers={"Authorization": f"Bearer {key}"}), budget, stop, None, key)
        except RerankerTransportError as exc:
            raise RerankError("reranker_failed", str(exc)) from exc
        if response.status_code != 200:
            raise RerankError("reranker_failed", f"HTTP {response.status_code}: {redact(error_message(response), key)}")
        try:
            reply = response.json()
        except ValueError as exc:
            raise RerankError("reranker_bad_reply", "the reply is not JSON") from exc
        items = reply.get("results") if isinstance(reply, dict) else None
        if (not isinstance(items, list) or len(items) != len(indexes)
                or not all(isinstance(item, dict) and type(item.get("index")) is int for item in items)
                or sorted(item["index"] for item in items) != list(range(len(indexes)))):
            raise RerankError("reranker_bad_reply", f"the reply does not rank documents 0 to {len(indexes) - 1}")
        for item in items:
            value = item.get("relevance_score")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise RerankError("reranker_bad_reply", "a relevance score is not a finite number")
            scores[indexes[item["index"]]] = float(value)
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
        meta = reply.get("meta") if isinstance(reply.get("meta"), dict) else {}
        billed = meta.get("billed_units") if isinstance(meta.get("billed_units"), dict) else {}
        for found in (usage.get("total_tokens"), reply.get("total_tokens")):
            if type(found) is int:
                tokens = (tokens or 0) + found
                break
        if type(billed.get("search_units")) in (int, float):
            units = (units or 0) + int(billed["search_units"])
    return {"scores": scores, "truncated": 0, "provider_tokens": tokens, "provider_search_units": units,
            "rate_limited_waits": budget.rate_limited_waits}


def voyage_batches(query: str, documents: list[str]) -> list[list[int]]:
    """Indexes of `documents` per request, each request's estimated "query × documents + documents" under
    VOYAGE_TOTAL_TOKENS and at most 1,000 documents. Scores from separate requests are on the same scale (each is the
    model's relevance of one document to the query), so one order can hold them all."""
    q = estimated_tokens(query)
    batches: list[list[int]] = []
    current: list[int] = []
    total = 0
    for i, text in enumerate(documents):
        cost = q + estimated_tokens(text)
        if current and (len(current) >= 1000 or total + cost > VOYAGE_TOTAL_TOKENS):
            batches.append(current)
            current, total = [], 0
        current.append(i)
        total += cost
    return batches + ([current] if current else [])


async def rerank_voyage(client: httpx.AsyncClient, key: str, query: str, documents: list[str],
                        stop: Callable[[], None] | None = None) -> dict[str, Any]:
    """Voyage's /rerank. HTTP 429 is waited out a bounded number of times (_send with its own budget)."""
    scores: list[float | None] = [None] * len(documents)
    used = 0
    budget = RateBudget()
    for indexes in voyage_batches(query, documents):
        body = {"query": query, "documents": [documents[i] for i in indexes], "model": VOYAGE_MODEL,
                "truncation": False}
        try:
            response = await _send(lambda body=body: client.post(
                f"{VOYAGE_URL}/rerank", timeout=120, json=body, headers={"Authorization": f"Bearer {key}"}),
                budget, stop, None, key)
        except RerankerTransportError as exc:
            raise RerankError("reranker_failed", str(exc)) from exc
        if response.status_code != 200:
            raise RerankError("reranker_failed", f"HTTP {response.status_code}: {redact(error_message(response), key)}")
        try:
            reply = response.json()
        except ValueError as exc:
            raise RerankError("reranker_bad_reply", "the reply is not JSON") from exc
        items = reply.get("data") if isinstance(reply, dict) else None
        if (not isinstance(items, list) or len(items) != len(indexes)
                or not all(isinstance(item, dict) and type(item.get("index")) is int for item in items)
                or sorted(item["index"] for item in items) != list(range(len(indexes)))):
            raise RerankError("reranker_bad_reply", f"the reply does not rank documents 0 to {len(indexes) - 1}")
        for item in items:
            value = item.get("relevance_score")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise RerankError("reranker_bad_reply", "a relevance score is not a finite number")
            scores[indexes[item["index"]]] = float(value)
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
        used += usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else 0
    return {"scores": scores, "truncated": 0, "provider_tokens": used,
            "rate_limited_waits": budget.rate_limited_waits}

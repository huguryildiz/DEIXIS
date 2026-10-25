"""The built-in embedding models and rerankers: GGUF files from `builtin_catalog`, run by llama.cpp's `llama-server`.

Each catalog model is downloaded, checked, removed and chosen on its own (`workflow/run/local_embedding_service.py`). A
chosen model gets its own `llama-server` process the first time it is asked for, one model per process, on a free
loopback port with a random API key of that process; `LocalModels` keeps one server per model and stops it after
LOCAL_IDLE_SECONDS without a request. DEIXIS talks to it through the loopback client (no proxy, no redirects).

A server counts as ready only when `/health` answers 200, an authenticated probe only this process can answer comes
back right (one sentence embedded into a unit vector of the catalog's dimension; two documents reranked into two
finite scores), and the child is still alive. A port another process took is detected by the child's own bind error
and the next port is tried, at most MAX_START_ATTEMPTS times.

The child runs under a small `/bin/sh` watcher that holds a pipe from DEIXIS: when DEIXIS ends, even killed, the pipe
closes and the watcher kills `llama-server`, so no server outlives it. The model's in-use lock (`flock`, shared) and the
runtime's are handed to the child (`pass_fds`) and live as long as it does; installing or removing a model takes that
model's lock exclusively, so neither happens under a running server.

Replies are checked fail-closed: embeddings mapped by `index` (each 0..n-1 once), every vector of the catalog's
dimension, finite, not null and of unit length; rerank results mapped by `results[].index` (each 0..n-1 once), every
score a finite number of any sign or size (llama.cpp returns raw scores; only their order is used).

Token limits are explicit: a text over the input limit is counted with the same server's `/tokenize`, cut at the limit
by DEIXIS (`/detokenize`) and reported in `truncated_texts`; a text longer than MAX_INPUT_CHARS is refused, not cut.
The cut policy is part of the stored identity (`builtin_catalog.identity`).

Before a server starts, the model file must have the size, mtime and inode it had at its last full sha256 check
(recorded on disk at the download and at "Check files"), and the server binary its recorded sha256. The cache is not
proof: a file changed in place with the same size and times is caught only by the next full check.

POSIX only in this slice.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import shutil
import signal
import socket
from array import array
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from deixis.documents import builtin_catalog, llama_runtime
from deixis.documents.builtin_catalog import CTX, Model
from deixis.documents.llama_runtime import DownloadError, RuntimePaths, now_iso  # noqa: F401 (re-exported)
from deixis.models.openai_compat import loopback_client
from deixis.storage import library_lock
from deixis.tools.child_env import child_env

LOCAL_BATCH = 16  # records per request (a starting value, not measured), so a pause waits at most one batch
LOCAL_IDLE_SECONDS = 300  # an idle server is stopped: it holds its model in memory
READY_TIMEOUT_SECONDS = 120  # loading the model and answering the probe
LOCK_WAIT_SECONDS = 30  # waiting for a model's in-use lock that an install's check or a removal holds
SECONDS_PER_BATCH_LIMIT = 300  # one embedding request
MAX_START_ATTEMPTS = 3  # ports tried when another process took the free one first
INPUT_TOKENS = CTX - 16  # tokens one text may have (room for the model's own start and end tokens)
RERANK_TEMPLATE_TOKENS = 256  # room for the reranker's template around the question and the document
MAX_INPUT_CHARS = 20_000  # a longer text is refused, never cut (`embeddings.MAX_CHARS`)
LOG_TAIL_BYTES = 4096
UNIT_TOLERANCE = 1e-3
CHECK_SENTENCE = "Packet size and energy consumption in wireless sensor networks."
# Watches the pipe from DEIXIS: at its end (DEIXIS closed or killed) the server is killed; the server's own exit code
# is the watcher's. "$@" is the server and its arguments.
WATCHER = ('exec 3<&0; "$@" 0</dev/null & child=$!; '
           '(while read -r _ <&3; do :; done; kill -KILL "$child" 2>/dev/null) & reaper=$!; '
           'wait "$child"; code=$?; kill -KILL "$reaper" 2>/dev/null; exit "$code"')
BIND_FAILURE = ("couldn't bind", "could not bind", "address already in use", "failed to bind")
LEGACY_FOLDERS = ("embedding", "embedding-models", "embedding-hf-home", "uv-python", "uv-cache")
LEGACY_FILES = ("embedding-job.json", "embedding-install.lock", "embedding-in-use.lock")

RUNNER_THREADS: ContextVar[int | None] = ContextVar("deixis_embedding_threads", default=None)


class LocalEmbeddingError(Exception):
    """`builtin_unavailable`, `builtin_timeout`, `builtin_stopped`, `builtin_bad_reply`, `builtin_input_too_long` or
    `builtin_model_changed`, with what happened."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class _BindFailed(Exception):
    pass


def supported() -> bool:
    """The built-in models need `fcntl.flock`, `pass_fds` and a pinned llama.cpp build: macOS and Linux x64."""
    return llama_runtime.supported()


def provenance() -> dict[str, str]:
    """What a step records about the runtime that computed its vectors or scores."""
    return {"runtime": "llama.cpp", "runtime_build": llama_runtime.TAG}


@dataclass(frozen=True)
class BuiltinPaths:
    root: Path  # <data dir>/tools

    @property
    def runtime(self) -> RuntimePaths:
        return RuntimePaths(self.root / "llama")

    @property
    def models_root(self) -> Path:
        return self.root / "models"

    def model_dir(self, model_id: str) -> Path:
        return self.models_root / model_id

    def model_file(self, model: Model) -> Path:
        return self.model_dir(model.id) / model.file

    def check_record(self, model_id: str) -> Path:
        return self.model_dir(model_id) / "check.json"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    def model_lock(self, model_id: str) -> Path:
        return self.locks / f"{model_id}.lock"

    @property
    def runtime_lock(self) -> Path:
        return self.locks / "llama-runtime.lock"

    @property
    def install_lock(self) -> Path:
        return self.root / "local-models-install.lock"

    @property
    def job_file(self) -> Path:
        return self.root / "local-models-job.json"

    def log_file(self, model_id: str) -> Path:
        return self.root / "llama-logs" / f"{model_id}.log"

    def installed(self, model: Model) -> bool:
        """The model's file is in place (not a part); whether it matches is the integrity record's business."""
        return self.model_file(model).is_file()

    def legacy(self) -> list[Path]:
        """What the earlier PyTorch built-in model (D88) left under tools; shown and removed only on request."""
        return [p for p in ([self.root / n for n in LEGACY_FOLDERS] + [self.root / n for n in LEGACY_FILES])
                if p.exists() or p.is_symlink()]


def builtin_paths(data_dir: Path) -> BuiltinPaths:
    return BuiltinPaths(data_dir / "tools")


def tree_size(root: Path) -> int:
    if root.is_file() or root.is_symlink():
        try:
            return os.lstat(root).st_size
        except OSError:
            return 0
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


# ---- the model files ---------------------------------------------------------------------

def file_stats(path: Path) -> list[int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ino]


class ModelIntegrity:
    """The last full sha256 check of one model file, kept on disk next to it, trusted while the file keeps the size,
    mtime and inode it had then."""

    def __init__(self, paths: BuiltinPaths, model: Model):
        self.paths, self.model = paths, model

    @property
    def _record_path(self) -> Path:
        return self.paths.check_record(self.model.id)

    def _read(self) -> dict[str, Any] | None:
        try:
            record = json.loads(self._record_path.read_text())
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    def record(self, passed: bool) -> None:
        stats = file_stats(self.paths.model_file(self.model)) if passed else None
        self._record_path.parent.mkdir(parents=True, exist_ok=True)
        partial = self._record_path.with_suffix(".json.tmp")
        partial.write_text(json.dumps({"at": now_iso(), "passed": passed, "sha256": self.model.sha256, "stats": stats}))
        os.replace(partial, self._record_path)

    def check_now(self) -> bool:
        passed = llama_runtime.file_matches(self.paths.model_file(self.model), self.model.bytes, self.model.sha256)
        self.record(passed)
        return passed

    def reset(self) -> None:
        self._record_path.unlink(missing_ok=True)

    def available(self) -> bool:
        record = self._read()
        return bool(record and record.get("passed") is True and record.get("sha256") == self.model.sha256
                    and record.get("stats") is not None
                    and record["stats"] == file_stats(self.paths.model_file(self.model)))

    def last_full_check(self) -> dict[str, Any] | None:
        record = self._read()
        return None if record is None else {"at": record.get("at"), "passed": bool(record.get("passed"))}


# ---- locks -------------------------------------------------------------------------------

def _open_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o644)


def try_lock(path: Path, exclusive: bool) -> int | None:
    """An open descriptor holding the lock, or None when another holder has it."""
    import fcntl

    fd = _open_lock(path)
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


async def wait_shared(path: Path, seconds: float = LOCK_WAIT_SECONDS) -> int | None:
    """LOCK_SH on `path`, waiting up to `seconds` while someone holds it exclusively; None when it stays held."""
    loop = asyncio.get_running_loop()
    ends = loop.time() + seconds
    while True:
        fd = try_lock(path, exclusive=False)
        if fd is not None or loop.time() >= ends:
            return fd
        await asyncio.sleep(0.25)


def _close(fd: int | None) -> None:
    if fd is not None:
        os.close(fd)


# ---- the server process ------------------------------------------------------------------

def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_vectors(reply: Any, count: int, dimensions: int) -> list[array]:
    """`/v1/embeddings` vectors in input order, mapped by `index`, or `builtin_bad_reply`: each index 0..count-1 once,
    every vector `dimensions` long, finite, not null and of unit length."""
    items = reply.get("data") if isinstance(reply, dict) else None
    if not isinstance(items, list) or len(items) != count or not all(isinstance(i, dict) for i in items):
        raise LocalEmbeddingError("builtin_bad_reply", f"{len(items) if isinstance(items, list) else 'no'} vectors for {count} texts")
    indexes = [item.get("index") for item in items]
    if any(type(i) is not int for i in indexes) or sorted(indexes) != list(range(count)):
        raise LocalEmbeddingError("builtin_bad_reply", f"the reply's indexes are not 0 to {count - 1}, each once")
    vectors: list[array | None] = [None] * count
    for item in items:
        values = item.get("embedding")
        if not isinstance(values, list) or len(values) != dimensions:
            raise LocalEmbeddingError("builtin_bad_reply", f"a vector has {len(values) if isinstance(values, list) else 'no'} "
                                                           f"dimensions, not {dimensions}")
        if not all(_number(v) for v in values):
            raise LocalEmbeddingError("builtin_bad_reply", "a vector holds a null or a value that is not finite")
        norm = math.sqrt(sum(v * v for v in values))
        if abs(norm - 1.0) > UNIT_TOLERANCE:
            raise LocalEmbeddingError("builtin_bad_reply", f"a vector has length {norm:.4f}, not 1")
        vectors[item["index"]] = array("f", values)
    return vectors  # type: ignore[return-value]


def check_scores(reply: Any, count: int) -> list[float]:
    """`/v1/rerank` scores in input order, mapped by `results[].index`, or `builtin_bad_reply`: each index 0..count-1
    once, every score a finite number (raw scores: any sign or size)."""
    items = reply.get("results") if isinstance(reply, dict) else None
    if not isinstance(items, list) or len(items) != count or not all(isinstance(i, dict) for i in items):
        raise LocalEmbeddingError("builtin_bad_reply", f"{len(items) if isinstance(items, list) else 'no'} scores for {count} documents")
    indexes = [item.get("index") for item in items]
    if any(type(i) is not int for i in indexes) or sorted(indexes) != list(range(count)):
        raise LocalEmbeddingError("builtin_bad_reply", f"the reply does not rank documents 0 to {count - 1}, each once")
    scores: list[float] = [0.0] * count
    for item in items:
        if not _number(item.get("relevance_score")):
            raise LocalEmbeddingError("builtin_bad_reply", "a relevance score is not a finite number")
        scores[item["index"]] = float(item["relevance_score"])
    return scores


class LlamaServer:
    """One `llama-server` child serving one catalog model. The caller serializes requests (`LocalModels`)."""

    def __init__(self, paths: BuiltinPaths, model: Model, client: httpx.AsyncClient, threads: int | None = None):
        self.paths, self.model, self.client, self.threads = paths, model, client, threads
        self.process: asyncio.subprocess.Process | None = None
        self.port: int | None = None
        self._key: str | None = None

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def argv(self, port: int, key: str) -> list[str]:
        model = self.model
        kind = (["--embedding", "--pooling", model.pooling] if model.kind == "embedding" else ["--rerank"])
        return (["-m", str(self.paths.model_file(model)), "--host", "127.0.0.1", "--port", str(port), "-c", str(CTX),
                 "-ub", str(CTX), "-b", str(CTX), "-np", "1", "-ngl", "99", "--api-key", key, *kind]
                + (["--threads", str(self.threads)] if self.threads is not None else []))

    def log_tail(self) -> str:
        try:
            with open(self.paths.log_file(self.model.id), "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - LOG_TAIL_BYTES))
                return handle.read().decode("utf-8", "replace")
        except OSError:
            return ""

    async def start(self, lock_fd: int | None = None) -> None:
        """Start and probe the server. With `lock_fd` the caller already holds the model's in-use lock (an install's
        check); otherwise it is taken shared here, waiting at most LOCK_WAIT_SECONDS."""
        runtime = self.paths.runtime
        server = runtime.server()
        if server is None:
            raise LocalEmbeddingError("builtin_unavailable", "llama.cpp is not installed")
        if not await asyncio.to_thread(runtime.server_matches):
            raise LocalEmbeddingError("builtin_unavailable", "the llama.cpp server binary does not match its record")
        for _attempt in range(MAX_START_ATTEMPTS):
            own = lock_fd is None
            model_fd = await wait_shared(self.paths.model_lock(self.model.id)) if own else lock_fd
            if model_fd is None:
                raise LocalEmbeddingError("builtin_unavailable", "the model is being installed or removed")
            runtime_fd = await wait_shared(self.paths.runtime_lock)
            if runtime_fd is None:
                if own:
                    _close(model_fd)
                raise LocalEmbeddingError("builtin_unavailable", "llama.cpp is being installed or removed")
            port, key = free_port(), secrets.token_hex(24)
            log = self.paths.log_file(self.model.id)
            log.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(log, "wb") as handle:
                    self.process = await asyncio.create_subprocess_exec(
                        "/bin/sh", "-c", WATCHER, "deixis-llama", str(server), *self.argv(port, key),
                        stdin=asyncio.subprocess.PIPE, stdout=handle, stderr=handle, cwd=str(server.parent),
                        env=child_env(), start_new_session=True,
                        pass_fds=(model_fd, runtime_fd, *library_lock.child_fds()))
            except OSError as exc:
                raise LocalEmbeddingError("builtin_unavailable", f"llama-server did not start: {exc}") from exc
            finally:
                _close(runtime_fd)
                if own:
                    _close(model_fd)  # the child holds the locks now, for as long as it lives
            self.port, self._key = port, key
            try:
                await self._ready()
                return
            except _BindFailed:
                await self.kill()
            except BaseException:
                await self.kill()
                raise
        raise LocalEmbeddingError("builtin_unavailable", f"no free port after {MAX_START_ATTEMPTS} attempts")

    def _exited(self) -> None:
        """Raise for a child that has ended: `_BindFailed` when it could not take its port."""
        if self.process is not None and self.process.returncode is not None:
            tail = self.log_tail()
            if any(marker in tail.lower() for marker in BIND_FAILURE):
                raise _BindFailed()
            raise LocalEmbeddingError("builtin_unavailable", f"llama-server ended with code {self.process.returncode}: "
                                                            f"{tail.strip()[-300:]}")

    async def _ready(self) -> None:
        loop = asyncio.get_running_loop()
        ends = loop.time() + READY_TIMEOUT_SECONDS
        while True:
            self._exited()
            if loop.time() >= ends:
                raise LocalEmbeddingError("builtin_timeout", f"llama-server was not ready within {READY_TIMEOUT_SECONDS} s")
            try:
                health = await self.client.get(f"{self.base}/health", timeout=2)
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
        # Only this process knows the key: a server another process runs on this port cannot answer the probe.
        seconds = max(1.0, ends - loop.time())
        try:
            if self.model.kind == "embedding":
                await self.embed([CHECK_SENTENCE], "query", seconds)
            else:
                await self.rerank(CHECK_SENTENCE, [CHECK_SENTENCE, "ready"], seconds)
        except LocalEmbeddingError:
            self._exited()
            raise
        self._exited()

    async def _post(self, path: str, body: dict[str, Any], seconds: float) -> Any:
        try:
            response = await self.client.post(f"{self.base}{path}", json=body, timeout=seconds,
                                              headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as exc:
            raise LocalEmbeddingError("builtin_timeout", f"no reply within {seconds:g} s") from exc
        except httpx.HTTPError as exc:
            raise LocalEmbeddingError("builtin_stopped", f"llama-server did not answer: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise LocalEmbeddingError("builtin_bad_reply", f"llama-server answered HTTP {response.status_code}: "
                                                           f"{response.text[:300]}")
        try:
            return response.json()
        except ValueError as exc:
            raise LocalEmbeddingError("builtin_bad_reply", "the reply is not JSON") from exc

    async def _tokens(self, text: str, seconds: float) -> list[int]:
        """The text's tokens as this server's model counts them (`/tokenize`, no start or end token)."""
        reply = await self._post("/tokenize", {"content": text, "add_special": False}, seconds)
        tokens = reply.get("tokens") if isinstance(reply, dict) else None
        if not isinstance(tokens, list) or not all(type(t) is int for t in tokens):
            raise LocalEmbeddingError("builtin_bad_reply", "the tokenizer's reply holds no tokens")
        return tokens

    async def _fit(self, text: str, limit: int, seconds: float) -> tuple[str, bool]:
        """`text` within `limit` tokens of this model: as it is, or cut at the limit (True). A text whose UTF-8 bytes
        (plus two) fit is not counted: a token covers at least one byte, bar one leading space marker."""
        if len(text) > MAX_INPUT_CHARS:
            raise LocalEmbeddingError("builtin_input_too_long", f"a text of {len(text)} characters is longer than "
                                                                f"{MAX_INPUT_CHARS}; it is refused, not cut")
        if len(text.encode()) + 2 <= limit:
            return text, False
        tokens = await self._tokens(text, seconds)
        if len(tokens) <= limit:
            return text, False
        reply = await self._post("/detokenize", {"tokens": tokens[:limit]}, seconds)
        content = reply.get("content") if isinstance(reply, dict) else None
        if not isinstance(content, str):
            raise LocalEmbeddingError("builtin_bad_reply", "the detokenizer's reply holds no text")
        return content, True

    async def embed(self, texts: list[str], kind: str, seconds: float) -> tuple[list[array], list[int]]:
        """Unit vectors in input order and the indexes of the texts cut at the token limit. Queries of a model with an
        instruction carry `Instruct: …\\nQuery:`; documents are sent as they are."""
        prefix = (f"Instruct: {self.model.query_instruction}\nQuery:"
                  if kind == "query" and self.model.query_instruction else "")
        inputs, cut = [], []
        for index, text in enumerate(texts):
            fitted, was_cut = await self._fit(prefix + text, INPUT_TOKENS, seconds)
            inputs.append(fitted)
            if was_cut:
                cut.append(index)
        reply = await self._post("/v1/embeddings", {"input": inputs, "encoding_format": "float"}, seconds)
        return check_vectors(reply, len(texts), self.model.dimensions or 0), cut

    async def rerank(self, query: str, documents: list[str], seconds: float) -> tuple[list[float], list[int]]:
        """Raw relevance scores in input order and the indexes of the documents cut so that question, template and
        document fit the context."""
        query, query_cut = await self._fit(query, INPUT_TOKENS // 4, seconds)
        if query_cut:
            raise LocalEmbeddingError("builtin_input_too_long", "the question is longer than a quarter of the context")
        query_tokens = len(query.encode()) + 2  # at most this many tokens; counted when that bound is large
        if query_tokens > 512:
            query_tokens = len(await self._tokens(query, seconds))
        limit = INPUT_TOKENS - RERANK_TEMPLATE_TOKENS - query_tokens
        inputs, cut = [], []
        for index, document in enumerate(documents):
            fitted, was_cut = await self._fit(document, limit, seconds)
            inputs.append(fitted)
            if was_cut:
                cut.append(index)
        reply = await self._post("/v1/rerank", {"query": query, "documents": inputs, "top_n": len(inputs)}, seconds)
        return check_scores(reply, len(documents)), cut

    async def kill(self) -> None:
        """Kill the watcher and the server (one process group) and wait until every member has gone; the locks go
        with them."""
        process, self.process = self.process, None
        if process is None:
            return
        _signal_group(process, signal.SIGKILL)
        await process.wait()
        await _group_gone(process.pid)

    async def stop(self) -> None:
        """End the server gently (SIGTERM to its group), killing it after 10 s."""
        process = self.process
        if process is None:
            return
        _signal_group(process, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), 10)
        except asyncio.TimeoutError:
            pass
        self.process = process
        await self.kill()  # whatever of the group is left; waits until it is gone


def _signal_group(process: asyncio.subprocess.Process, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)  # started in its own session: the group id is the watcher's pid
    except (ProcessLookupError, PermissionError):
        if process.returncode is None:
            process.send_signal(sig)


async def _group_gone(pgid: int, seconds: float = 10) -> None:
    """Wait until no process of the group is left (the server may outlive its watcher by a moment), killing again."""
    loop = asyncio.get_running_loop()
    ends = loop.time() + seconds
    while loop.time() < ends:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        await asyncio.sleep(0.02)


# ---- the models of this process ---------------------------------------------------------

class LocalModels:
    """The servers of this DEIXIS process, one per catalog model in use; requests to one model are served one at a
    time. `busy[model_id]` ("installing", "removing") turns new requests to that model away before any lock or
    process is touched."""

    def __init__(self, paths: BuiltinPaths, idle_seconds: float = LOCAL_IDLE_SECONDS,
                 client: httpx.AsyncClient | None = None):
        self.paths, self.idle_seconds = paths, idle_seconds
        self.client = client or loopback_client()
        self.servers: dict[str, LlamaServer] = {}
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.busy: dict[str, str] = {}
        self._idle: dict[str, asyncio.TimerHandle] = {}

    def integrity(self, model_id: str) -> ModelIntegrity:
        model = builtin_catalog.get(model_id)
        if model is None:
            raise KeyError(model_id)
        return ModelIntegrity(self.paths, model)

    def available(self, model_id: str | None) -> bool:
        """Installed, its file as at its last passed full check, and the runtime in place."""
        model = builtin_catalog.get(model_id)
        return bool(model and supported() and self.paths.runtime.installed() and ModelIntegrity(self.paths, model).available())

    def _model(self, model_id: str, kind: str) -> Model:
        model = builtin_catalog.get(model_id)
        if model is None or model.kind != kind:
            raise LocalEmbeddingError("builtin_model_changed", f"'{model_id}' is not a built-in {kind} model of this "
                                                              "DEIXIS; choose one in Settings")
        return model

    async def embed(self, model_id: str, texts: list[str], kind: str, report: dict[str, int] | None = None) -> list[array]:
        """Vectors in input order for `kind` "document" or "query"; raises LocalEmbeddingError. `report`, when given,
        gets `truncated_texts`: how many of these texts were cut at the token limit."""
        model = self._model(model_id, "embedding")
        vectors, cut = await self._request(model, lambda server: server.embed(texts, kind, SECONDS_PER_BATCH_LIMIT))
        if report is not None:
            report["truncated_texts"] = report.get("truncated_texts", 0) + len(cut)
        return vectors

    async def rerank(self, model_id: str, query: str, documents: list[str], seconds: float) -> tuple[list[float], list[int]]:
        """Raw scores in input order and the indexes of the documents cut. A request that outlives `seconds`, or is
        cancelled, kills the server, so no reply is left unread."""
        model = self._model(model_id, "reranker")
        return await self._request(model, lambda server: server.rerank(query, documents, seconds))

    async def _request(self, model: Model, call: Callable[[LlamaServer], Awaitable[Any]]) -> Any:
        if model.id in self.busy or not supported():
            raise LocalEmbeddingError("builtin_unavailable", "the model is being installed or removed"
                                      if supported() else "the built-in models are not available on this platform")
        async with self.locks[model.id]:
            if model.id in self.busy:
                raise LocalEmbeddingError("builtin_unavailable", "the model is being installed or removed")
            if (idle := self._idle.pop(model.id, None)) is not None:
                idle.cancel()
            threads = RUNNER_THREADS.get()
            server = self.servers.get(model.id)
            if server is not None and (not server.alive or server.threads != threads):
                await server.kill()
                self.servers.pop(model.id, None)
                server = None
            if server is None:
                if not self.available(model.id):
                    raise LocalEmbeddingError("builtin_unavailable", f"{model.name} is not downloaded, or its file does "
                                                                     "not match its last check")
                server = LlamaServer(self.paths, model, self.client, threads)
                await server.start()  # a server that died is started again once, at the next request
                self.servers[model.id] = server
            try:
                result = await call(server)
            except LocalEmbeddingError as exc:
                if exc.code != "builtin_input_too_long":  # refused before anything was sent
                    await server.kill()
                    self.servers.pop(model.id, None)
                raise
            except BaseException:  # a cancel: the reply would be left unread on the server
                await server.kill()
                self.servers.pop(model.id, None)
                raise
            self._idle[model.id] = asyncio.get_running_loop().call_later(
                self.idle_seconds, lambda: asyncio.ensure_future(self.close(model.id)))
        return result

    async def close(self, model_id: str | None = None) -> None:
        """Stop a model's server (every server without `model_id`) once its request in flight has ended, or after
        SECONDS_PER_BATCH_LIMIT."""
        for mid in ([model_id] if model_id else list(set(self.servers) | set(self._idle))):
            if (idle := self._idle.pop(mid, None)) is not None:
                idle.cancel()
            lock = self.locks[mid]
            try:
                await asyncio.wait_for(lock.acquire(), SECONDS_PER_BATCH_LIMIT)
            except asyncio.TimeoutError:
                server = self.servers.pop(mid, None)
                if server is not None:
                    await server.kill()
                continue
            try:
                server = self.servers.pop(mid, None)
                if server is not None:
                    await server.stop()
            finally:
                lock.release()


# The running app's models, for views that only have the store (as `views.semantic_view` is).
_registered: LocalModels | None = None


def register(models: LocalModels) -> None:
    global _registered
    _registered = models


def model_available(model_id: str | None) -> bool:
    return bool(_registered is not None and hasattr(_registered, "available") and _registered.available(model_id))


def remove_model_files(paths: BuiltinPaths, model: Model) -> list[str]:
    """Delete the model's check record first, then its folder. Returns what could not be deleted."""
    failed: list[str] = []

    def note(_function: Any, path: str, _error: Any) -> None:
        failed.append(str(path))

    try:
        paths.check_record(model.id).unlink(missing_ok=True)
    except OSError:
        failed.append(str(paths.check_record(model.id)))
    folder = paths.model_dir(model.id)
    if folder.exists() or folder.is_symlink():
        shutil.rmtree(folder, onexc=note)
        if folder.exists() and str(folder) not in failed:
            failed.append(str(folder))
    return failed


def remove_parts(paths: BuiltinPaths) -> None:
    """Remove model files a stopped download left half-written."""
    if paths.models_root.is_dir():
        for part in paths.models_root.rglob("*.part"):
            part.unlink(missing_ok=True)

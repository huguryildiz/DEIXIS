"""The built-in embedding model, an optional local component installed on request (slice 21, D103).

`BAAI/bge-small-en-v1.5` as the quantised ONNX export `fastembed` uses, from the pinned Hugging Face revision below. It
runs in its own Python environment under the data directory (`tools/embedding`, uv, `fastembed` pinned), like the
equation reader (D52); DEIXIS never imports `fastembed`, `onnxruntime` or `numpy`. `LocalEmbedder` keeps one
`embedding_runner.py` process, sends it one batch per JSON line and stops it when idle.

The five model files are one manifest (`MODEL_FILES`): the download, the runner, `options()` and the status endpoint all
read it. A full sha256 check runs when the service starts, after an install and every time the runner starts; between
two full checks, `Integrity` reports the last result for as long as the files keep their size, mtime and inode. That
cache is not proof of integrity: a file changed in place with the same size and times is caught only by the next full
check, at the runner's start.

Measured on one Apple M1 Pro (slice 21 plan, 2026-09-25): the environment takes about 145 MB installed, the model files
67 MB; 1,369 titles and abstracts took 51 s and 6,696 took 251 s at the 256-token cut in batches of 64; the runner's
peak resident memory was 1.2 GB. Other computers were not measured.

POSIX only in this slice: ownership and use are `fcntl.flock` locks handed to child processes with `pass_fds`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import shutil
import sys
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

REPOSITORY = "Qdrant/bge-small-en-v1.5-onnx-Q"
REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
MODEL_NAME = "bge-small-en-v1.5"
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
FASTEMBED_PACKAGE = "fastembed==0.8.1"
PYTHON_VERSION = "3.12"
DIMENSIONS = 384
LOCAL_BATCH = 64  # records per request; a batch took at most 2.5 s on the M1 Pro, so a pause waits about that long
LOCAL_MAX_TOKENS = 256  # the tokenizer's cut: on the SW7 pool it halved the time and kept the rescued positives (plan, number 5)
LOCAL_IDLE_SECONDS = 300  # the process holds up to 1.2 GB; an idle runner is stopped
READY_TIMEOUT_SECONDS = 120  # the runner hashes the 67 MB of files, then loads the model (0.22 s measured)
SECONDS_PER_BATCH_LIMIT = 120
# The model's identity in stored vectors and similarities: a changed revision or cut is another model's vectors.
MODEL_ID = f"{MODEL_NAME}@{REVISION[:7]}:{LOCAL_MAX_TOKENS}"
RUNNER = Path(__file__).with_name("embedding_runner.py")
# A known sentence the install's last step embeds: the runner must return one 384-dimension unit vector for it.
CHECK_SENTENCE = "Packet size and energy consumption in wireless sensor networks."


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


# Byte counts and digests as the plan's measurement recorded them (.local/sw-slice21-plan-2026-09-25/download.json).
MODEL_FILES: tuple[ModelFile, ...] = (
    ModelFile("model_optimized.onnx", 66_465_124, "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"),
    ModelFile("tokenizer.json", 711_396, "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"),
    ModelFile("config.json", 706, "13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd"),
    ModelFile("tokenizer_config.json", 1_242, "0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53"),
    ModelFile("special_tokens_map.json", 695, "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a"),
)
# Disk sizes, never download sizes: the wheels' download bytes were not measured.
MODEL_DISK_BYTES = sum(f.size for f in MODEL_FILES)  # the pinned model's files, 67 MB; what Settings says before a download
RUNTIME_BYTES_ESTIMATE = 145_000_000  # the environment as installed on the M1 Pro (plan, number 1)
PYTHON_BYTES_ESTIMATE = 74_000_000  # CPython 3.12.13 as uv installed it there, when uv has to download Python


def model_bytes() -> int:
    return sum(f.size for f in MODEL_FILES)


def model_url(name: str) -> str:
    return f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"


def supported() -> bool:
    """The built-in model needs `fcntl.flock` and `pass_fds`: macOS and Linux in this slice."""
    return os.name == "posix"


def manifest() -> list[dict[str, Any]]:
    return [{"name": f.name, "size": f.size, "sha256": f.sha256} for f in MODEL_FILES]


class LocalEmbeddingError(Exception):
    """`builtin_unavailable`, `builtin_timeout`, `builtin_stopped` or `builtin_bad_reply`, with what happened."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class DownloadError(Exception):
    pass


@dataclass(frozen=True)
class BuiltinPaths:
    root: Path  # <data dir>/tools

    @property
    def env(self) -> Path:
        return self.root / "embedding"

    @property
    def python(self) -> Path:
        return self.env / "bin" / "python"

    @property
    def installed_marker(self) -> Path:
        return self.env / "installed.json"

    @property
    def models_root(self) -> Path:
        return self.root / "embedding-models"

    @property
    def models(self) -> Path:
        return self.models_root / f"{MODEL_NAME}@{REVISION[:7]}"

    @property
    def hf_home(self) -> Path:
        return self.root / "embedding-hf-home"

    @property
    def uv_cache(self) -> Path:
        return self.root / "uv-cache"

    @property
    def uv_python(self) -> Path:
        return self.root / "uv-python"

    @property
    def job_file(self) -> Path:
        return self.root / "embedding-job.json"

    @property
    def install_lock(self) -> Path:
        return self.root / "embedding-install.lock"

    @property
    def in_use_lock(self) -> Path:
        return self.root / "embedding-in-use.lock"

    def installed(self) -> bool:
        """Only an environment whose install wrote its last file counts; one without it is half-built."""
        return self.installed_marker.is_file() and self.python.exists()

    def runner_env(self) -> dict[str, str]:
        """Offline, with the data directory's own Hugging Face home: nothing is read from or written to ~/.cache."""
        return {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HOME": str(self.hf_home), "PYTHONUNBUFFERED": "1",
                "TOKENIZERS_PARALLELISM": "false"}


def builtin_paths(data_dir: Path) -> BuiltinPaths:
    return BuiltinPaths(data_dir / "tools")


def runner_argv(paths: BuiltinPaths) -> list[str]:
    """The runner inherits the in-use lock's descriptor through `pass_fds` and keeps it open while it lives."""
    return [str(paths.python), str(RUNNER), "--model-dir", str(paths.models), "--max-tokens", str(LOCAL_MAX_TOKENS),
            "--manifest", json.dumps(manifest()), "--model-name", FASTEMBED_MODEL]


# ---- the model files ---------------------------------------------------------------------

def file_stats(paths: BuiltinPaths) -> tuple[tuple[int, int, int], ...] | None:
    """(size, mtime_ns, inode) of each manifest file, or None when one is missing."""
    stats = []
    for model_file in MODEL_FILES:
        try:
            st = os.stat(paths.models / model_file.name)
        except OSError:
            return None
        stats.append((st.st_size, st.st_mtime_ns, st.st_ino))
    return tuple(stats)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_matches(path: Path, model_file: ModelFile) -> bool:
    try:
        return path.stat().st_size == model_file.size and _digest(path) == model_file.sha256
    except OSError:
        return False


def full_check(paths: BuiltinPaths) -> bool:
    """Every manifest file present with its byte count and sha256."""
    return all(file_matches(paths.models / f.name, f) for f in MODEL_FILES)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Integrity:
    """The last full check's result, trusted while every file keeps the size, mtime and inode it had then."""

    def __init__(self, paths: BuiltinPaths):
        self.paths = paths
        self.at: str | None = None
        self.passed: bool | None = None
        self.stats: tuple[tuple[int, int, int], ...] | None = None

    def record(self, passed: bool) -> None:
        self.at, self.passed, self.stats = now_iso(), passed, file_stats(self.paths) if passed else None

    def reset(self) -> None:
        self.at = self.passed = self.stats = None

    def check_now(self) -> bool:
        passed = full_check(self.paths)
        self.record(passed)
        return passed

    def available(self) -> bool:
        return (supported() and self.paths.installed() and bool(self.passed) and self.stats is not None
                and file_stats(self.paths) == self.stats)

    def last_full_check(self) -> dict[str, Any] | None:
        return None if self.at is None else {"at": self.at, "passed": bool(self.passed)}


# The Integrity the running app's service keeps, for views that only have the store (as `equations.reading` is).
_registered: Integrity | None = None


def register(integrity: Integrity) -> None:
    global _registered
    _registered = integrity


def builtin_available() -> bool:
    return bool(_registered is not None and _registered.available())


def remove_parts(models: Path) -> None:
    """Remove files a stopped download left half-written."""
    if models.is_dir():
        for part in models.glob("*.part"):
            part.unlink(missing_ok=True)


async def download_model(client: httpx.AsyncClient, models: Path,
                         progress: Callable[[int, int], None] | None = None) -> None:
    """Download the manifest's files from the pinned revision into `models`.

    Each file is written to `<name>.part`, its byte count and sha256 compared with the manifest, and only then moved
    into place; a mismatch deletes the part and raises DownloadError, so no file is ever half there. A file already in
    place with its digest is not asked for again. `progress(done, total)` gets bytes of the whole model."""
    models.mkdir(parents=True, exist_ok=True)
    total = model_bytes()
    done = 0
    for model_file in MODEL_FILES:
        target = models / model_file.name
        if await asyncio.to_thread(file_matches, target, model_file):
            done += model_file.size
            if progress:
                progress(done, total)
            continue
        part = models / f"{model_file.name}.part"
        digest, size = hashlib.sha256(), 0
        try:
            with open(part, "wb") as handle:
                async with client.stream("GET", model_url(model_file.name), follow_redirects=True, timeout=120) as response:
                    if response.status_code != 200:
                        raise DownloadError(f"{model_file.name}: HTTP {response.status_code}")
                    async for chunk in response.aiter_bytes(1 << 16):
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        if size > model_file.size:
                            raise DownloadError(f"{model_file.name}: more than {model_file.size} bytes")
                        if progress:
                            progress(done + size, total)
            if size != model_file.size or digest.hexdigest() != model_file.sha256:
                raise DownloadError(f"{model_file.name}: {size} bytes, sha256 {digest.hexdigest()[:12]}…, expected "
                                    f"{model_file.size} bytes, {model_file.sha256[:12]}…")
            os.replace(part, target)
        except httpx.HTTPError as exc:
            part.unlink(missing_ok=True)
            raise DownloadError(f"{model_file.name}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        done += model_file.size


def remove_files(paths: BuiltinPaths) -> list[str]:
    """Delete the environment's completion mark first, then the environment and every downloaded file. Returns the
    paths that could not be deleted (empty when everything went); nothing is silently left behind."""
    failed: list[str] = []

    def note(_function: Any, path: str, _error: Any) -> None:
        failed.append(str(path))

    try:
        paths.installed_marker.unlink(missing_ok=True)
    except OSError:
        failed.append(str(paths.installed_marker))
    for folder in (paths.env, paths.models_root, paths.hf_home, paths.uv_cache, paths.uv_python):
        if folder.exists() or folder.is_symlink():
            shutil.rmtree(folder, onexc=note)
            if folder.exists() and str(folder) not in failed:
                failed.append(str(folder))
    return failed


# ---- the runner process ------------------------------------------------------------------

def decode_vector(text: str) -> array:
    vector = array("f")
    vector.frombytes(base64.b64decode(text, validate=True))
    if sys.byteorder != "little":
        vector.byteswap()
    return vector


def check_reply(reply: Any, request_id: int, count: int) -> list[array]:
    """The reply's vectors, or LocalEmbeddingError `builtin_bad_reply`: same id, one vector per text, 384 values each,
    every value finite."""
    if not isinstance(reply, dict) or reply.get("id") != request_id:
        raise LocalEmbeddingError("builtin_bad_reply", "the reply answers another request")
    if "error" in reply:
        raise LocalEmbeddingError("builtin_bad_reply", f"the runner reported: {str(reply['error'])[:300]}")
    encoded = reply.get("vectors")
    if not isinstance(encoded, list) or len(encoded) != count:
        raise LocalEmbeddingError("builtin_bad_reply", f"{len(encoded) if isinstance(encoded, list) else 'no'} vectors for {count} texts")
    vectors = []
    for item in encoded:
        try:
            vector = decode_vector(item)
        except (TypeError, ValueError) as exc:
            raise LocalEmbeddingError("builtin_bad_reply", "a vector is not base64 float32") from exc
        if len(vector) != DIMENSIONS:
            raise LocalEmbeddingError("builtin_bad_reply", f"a vector has {len(vector)} dimensions, not {DIMENSIONS}")
        if not all(math.isfinite(v) for v in vector):
            raise LocalEmbeddingError("builtin_bad_reply", "a vector holds a value that is not finite")
        vectors.append(vector)
    return vectors


def take_shared(path: Path) -> int | None:
    """An open descriptor holding LOCK_SH on the in-use lock, or None when someone holds it exclusively."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


class LocalEmbedder:
    """One runner process shared by every caller; requests are served one at a time.

    Before it starts a runner, the embedder takes LOCK_SH on `embedding-in-use.lock` and hands the descriptor to the
    runner, which holds it for as long as it lives, even if DEIXIS dies. An install or a removal takes the same lock
    exclusively, in this process or another; while one holds it, no runner starts. `removing` (and `installing`)
    turn every new request away before any lock or process is touched.
    """

    def __init__(self, paths: BuiltinPaths, integrity: Integrity | None = None, idle_seconds: float = LOCAL_IDLE_SECONDS,
                 runner: Path = RUNNER, python: str | None = None):
        self.paths, self.idle_seconds = paths, idle_seconds
        self.integrity = integrity or Integrity(paths)
        self.runner, self.python = runner, python
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.removing = False
        self.installing = False
        self.ready_info: dict[str, Any] | None = None
        self._idle: asyncio.TimerHandle | None = None
        self._requests = 0

    def blocked(self) -> bool:
        return self.removing or self.installing

    def _argv(self) -> list[str]:
        argv = runner_argv(self.paths)
        if self.python is not None:  # tests run a fake runner with the test's own interpreter
            argv[0] = self.python
        argv[1] = str(self.runner)
        return argv

    async def start(self, lock_fd: int | None = None) -> None:
        """Start the runner. With `lock_fd`, the caller already holds the in-use lock (the install's check)."""
        if not supported():
            raise LocalEmbeddingError("builtin_unavailable", "the built-in model is not available on this platform")
        if lock_fd is None and self.blocked():
            raise LocalEmbeddingError("builtin_unavailable", "the built-in model is being installed or removed")
        if not self.paths.installed() and lock_fd is None:
            raise LocalEmbeddingError("builtin_unavailable", "the built-in model is not installed")
        own = lock_fd is None
        fd = take_shared(self.paths.in_use_lock) if own else lock_fd
        if fd is None:
            raise LocalEmbeddingError("builtin_unavailable", "the built-in model is being installed or removed")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self._argv(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=self.paths.runner_env(), pass_fds=(fd,), limit=64 * 1024 * 1024)
        except OSError as exc:
            raise LocalEmbeddingError("builtin_unavailable", f"the runner did not start: {exc}") from exc
        finally:
            if own:
                os.close(fd)  # the runner holds the lock now, for as long as it lives
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), READY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._kill()
            raise LocalEmbeddingError("builtin_timeout", "the runner did not report ready") from None
        try:
            ready = json.loads(line) if line else None
        except json.JSONDecodeError:
            ready = None
        if not isinstance(ready, dict) or ready.get("ready") is not True or ready.get("dimensions") != DIMENSIONS:
            await self._kill()
            error = (ready or {}).get("error") if isinstance(ready, dict) else None
            if isinstance(ready, dict) and ready.get("code") == "files_do_not_match":
                self.integrity.record(False)  # the gate failed: `available` turns false at once
            raise LocalEmbeddingError("builtin_unavailable", f"the runner did not start: {error or 'no ready line'}")
        # The runner checked every file's sha256 before it said ready: that is a full check.
        self.integrity.record(True)
        self.ready_info = ready

    async def embed(self, texts: list[str], kind: str) -> list[array]:
        """Vectors in input order for `kind` "document" or "query"; raises LocalEmbeddingError."""
        if self.blocked() or not supported():
            raise LocalEmbeddingError("builtin_unavailable", "the built-in model is being installed or removed"
                                      if supported() else "the built-in model is not available on this platform")
        async with self.lock:
            if self.blocked():
                raise LocalEmbeddingError("builtin_unavailable", "the built-in model is being installed or removed")
            if self._idle:
                self._idle.cancel()
                self._idle = None
            if self.process is None or self.process.returncode is not None:
                self.process = None
                await self.start()  # a runner that died is started again once, at the next request
            self._requests += 1
            request_id = self._requests
            try:
                self.process.stdin.write((json.dumps({"id": request_id, "kind": kind, "texts": texts}) + "\n").encode())
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                await self._kill()
                raise LocalEmbeddingError("builtin_stopped", "the runner stopped") from exc
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), SECONDS_PER_BATCH_LIMIT)
            except asyncio.TimeoutError:
                await self._kill()
                raise LocalEmbeddingError("builtin_timeout", f"no reply within {SECONDS_PER_BATCH_LIMIT} s") from None
            if not line:
                await self._kill()
                raise LocalEmbeddingError("builtin_stopped", "the runner stopped")
            try:
                vectors = check_reply(json.loads(line), request_id, len(texts))
            except (LocalEmbeddingError, json.JSONDecodeError) as exc:
                await self._kill()
                if isinstance(exc, LocalEmbeddingError):
                    raise
                raise LocalEmbeddingError("builtin_bad_reply", "the reply is not JSON") from exc
            self._idle = asyncio.get_running_loop().call_later(self.idle_seconds, lambda: asyncio.ensure_future(self.close()))
        return vectors

    async def _kill(self) -> None:
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def close(self) -> None:
        """Stop the runner once the request it is serving has ended (or SECONDS_PER_BATCH_LIMIT has passed)."""
        if self._idle:
            self._idle.cancel()
            self._idle = None
        try:
            await asyncio.wait_for(self.lock.acquire(), SECONDS_PER_BATCH_LIMIT)
        except asyncio.TimeoutError:
            await self._kill()
            return
        try:
            process, self.process = self.process, None
            if process and process.returncode is None:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        finally:
            self.lock.release()

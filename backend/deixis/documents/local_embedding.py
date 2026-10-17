"""The built-in embedding model and reranker, an optional local component installed on request (slice 21, D103; Qwen3).

`Qwen/Qwen3-Embedding-0.6B` and `Qwen/Qwen3-Reranker-0.6B` (both Apache-2.0) from the pinned Hugging Face revisions
below, run with PyTorch and Transformers the way the two model cards' "Transformers usage" sections do: last-token
pooling of left-padded input and unit length for the embedding, an `Instruct: …\nQuery:` line on the query only; the
reranker's yes/no probability after its fixed system prompt. They run in their own Python environment under the data
directory (`tools/embedding`, uv, every package pinned with hashes), like the equation reader (D52); DEIXIS never
imports `torch`, `transformers` or `numpy`. `LocalEmbedder` keeps one `embedding_runner.py` process, sends it one
request per JSON line and stops it when idle; the reranker is loaded for a rerank request and freed after it.

Why this runtime: both model cards ship the safetensors weights and a Transformers recipe, and PyTorch has wheels for
macOS on Apple Silicon (run on MPS) and for Windows x64 (CPU). The ONNX exports that would have kept the small
onnxruntime environment are third-party copies (onnx-community), the reranker's as a text-generation graph with a
key-value cache; llama.cpp would need a compiler or per-platform binaries. The price is size: the environment is
estimated at about 600 MB installed (torch, transformers, tokenizers, numpy; not measured) against fastembed's 145 MB,
and the model files are 2.4 GB against 67 MB. Speed and memory on real hardware were not measured either; the batch
size, the token limits and the timeouts below are starting values, not measured optima.

Every model file is one manifest (`MODEL_FILES`): the download, the runner, `options()` and the status endpoint all
read it. A full sha256 check runs when the service starts, after an install and every time the runner starts; between
two full checks, `Integrity` reports the last result for as long as the files keep their size, mtime and inode. That
cache is not proof of integrity: a file changed in place with the same size and times is caught only by the next full
check, at the runner's start.

Token limits are explicit and never silent: the runner counts each text's tokens before it cuts it at the limit and
names every text it cut in its reply; the steps record how many were cut.

POSIX only in this slice: ownership and use are `fcntl.flock` locks handed to child processes with `pass_fds`.
"""

from __future__ import annotations

from contextvars import ContextVar

import asyncio
import base64
import hashlib
import json
import math
import os
import platform
import shutil
import sys
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from deixis.storage import library_lock
from deixis.tools.child_env import child_env

EMBEDDING_REPOSITORY = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
RERANKER_REPOSITORY = "Qwen/Qwen3-Reranker-0.6B"
RERANKER_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
# The folder of the models folder each file goes into, and the repository and revision it is downloaded from.
SOURCES = {"embedding": (EMBEDDING_REPOSITORY, EMBEDDING_REVISION), "reranker": (RERANKER_REPOSITORY, RERANKER_REVISION)}
REPOSITORY, REVISION = EMBEDDING_REPOSITORY, EMBEDDING_REVISION
MODEL_NAME = "qwen3-embedding-0.6b"
RERANKER_NAME = "qwen3-reranker-0.6b"
PACKAGE = "torch 2.10.0, transformers 4.57.6"
# Every package of the environment, pinned with hashes and installed with `uv pip sync` (D20). Its digest goes into
# installed.json; an installed copy whose digest or models differ from these is shown as "Update available".
REQUIREMENTS = Path(__file__).with_name("embedding-requirements.txt")
TORCH_BACKEND = "cpu"  # PyTorch's CPU wheels for Windows and Linux; the macOS wheel is the same on every index


def requirements_digest() -> str:
    """sha256 of the requirement lines only: a comment edited in the file is not an update."""
    lines = [line for line in REQUIREMENTS.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


PYTHON_VERSION = "3.12"
DIMENSIONS = 1024  # the model's full output; Matryoshka shortening is not used
LOCAL_BATCH = 16  # records per request (a starting value, not measured), so a pause waits at most one batch
LOCAL_MAX_TOKENS = 512  # tokens an embedded text may have; a longer one is cut and reported as cut
RERANK_MAX_TOKENS = 1024  # tokens of the reranker's whole input (its prompt, the question and one title and abstract)
LOCAL_IDLE_SECONDS = 300  # an idle runner is stopped: it holds the embedding model (about 2.4 GB as float32)
READY_TIMEOUT_SECONDS = 300  # the runner hashes 2.4 GB of files, then loads the model
SECONDS_PER_BATCH_LIMIT = 300
# MPS on Apple Silicon, the CPU elsewhere. The runner never falls back to another device: a missing MPS fails the start.
DEVICE = "mps" if sys.platform == "darwin" and platform.machine() == "arm64" else "cpu"
# The one-sentence task the Qwen3 model cards ask for, in English as they advise; only queries carry it.
EMBEDDING_INSTRUCTION = "Given a research question, retrieve titles, abstracts and passages of scholarly papers that answer it"
RERANK_INSTRUCTION = "Given a research question, judge whether the scholarly paper's title and abstract are relevant to answering it"
# The model's identity in stored vectors and similarities: a changed revision, cut, device or instruction is another
# model's vectors, so they are never compared with these.
MODEL_ID = f"{MODEL_NAME}@{EMBEDDING_REVISION[:7]}:{LOCAL_MAX_TOKENS}:{DEVICE}:i{_short(EMBEDDING_INSTRUCTION)}"
RERANKER_ID = f"{RERANKER_NAME}@{RERANKER_REVISION[:7]}:{RERANK_MAX_TOKENS}:{DEVICE}:i{_short(RERANK_INSTRUCTION)}"
# Built-in models an earlier DEIXIS used. Their stored vectors stay where they are and are never read as Qwen3 vectors.
EARLIER_MODEL_IDS = ("bge-small-en-v1.5@aa8f8b0:256",)
RUNNER = Path(__file__).with_name("embedding_runner.py")
# A known sentence the install's last step embeds: the runner must return one 1,024-dimension unit vector for it.
CHECK_SENTENCE = "Packet size and energy consumption in wireless sensor networks."


@dataclass(frozen=True)
class ModelFile:
    name: str  # "<embedding|reranker>/<the file's path in its repository>"
    size: int
    sha256: str


# Sizes and digests from the Hugging Face API at the pinned revisions (sha256 of the LFS weights and tokenizers as the
# API lists them; the small files downloaded and hashed), 17 Oct 2026. README.md and .gitattributes are not needed.
MODEL_FILES: tuple[ModelFile, ...] = (
    ModelFile("embedding/1_Pooling/config.json", 313, "37bf193fa101f19101bfad9c31d3eb0f786e247b7b1e5cb7f007d730eed1ddbd"),
    ModelFile("embedding/config.json", 727, "b5bf1f51fc45be473a54718cef92448d90a1be001bf9b9a44b8c7f10a19feaa9"),
    ModelFile("embedding/config_sentence_transformers.json", 215, "10667c72ddb772627bf1780cb7f86af8e2ae0032b8c243c731172064105c6961"),
    ModelFile("embedding/generation_config.json", 117, "28396d421a2108acce96383f6a7de78008f7f1b17f807958f3c14c51dbfb65fb"),
    ModelFile("embedding/merges.txt", 1_671_853, "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5"),
    ModelFile("embedding/model.safetensors", 1_191_586_416, "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd"),
    ModelFile("embedding/modules.json", 349, "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf"),
    ModelFile("embedding/tokenizer.json", 11_423_705, "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a"),
    ModelFile("embedding/tokenizer_config.json", 9_706, "253153d0738ceb4c668d2eff957714dd2bea0b56de772a9fdccd96cbf517e6a0"),
    ModelFile("embedding/vocab.json", 2_776_833, "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
    ModelFile("reranker/1_LogitScore/config.json", 57, "73e3156450564d8a98b7e47bcf5aace0f29600828b51937da545571e84db3ff3"),
    ModelFile("reranker/chat_template.jinja", 741, "6f682162495ec5b39fd9005c01b6aa2a74669379fe967039f1e2cbbe8752369d"),
    ModelFile("reranker/config.json", 727, "d479c427a9ca5295218063d4f9aca4f297ab4ac27487cca7af42c84643d51ef0"),
    ModelFile("reranker/config_sentence_transformers.json", 325, "6a153d6696f78fd588c1c728967f0b773ea869d3c6028f151ce71ebe49140762"),
    ModelFile("reranker/generation_config.json", 214, "81051cd3f6e77013827148d0b8a6ead93f8ac390d5ab805f849199f0af6a08db"),
    ModelFile("reranker/merges.txt", 1_671_853, "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5"),
    ModelFile("reranker/model.safetensors", 1_191_588_280, "27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b"),
    ModelFile("reranker/modules.json", 280, "6f13b6b4a89e577b591b2077bca40c67c26541a6740a8809267cb474f90806a9"),
    ModelFile("reranker/sentence_bert_config.json", 362, "3234ebd224d492cbe8d55d5ec80a3f408451c4db3005bafb64fe1c51c763e01e"),
    ModelFile("reranker/tokenizer.json", 11_422_654, "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"),
    ModelFile("reranker/tokenizer_config.json", 9_706, "253153d0738ceb4c668d2eff957714dd2bea0b56de772a9fdccd96cbf517e6a0"),
    ModelFile("reranker/vocab.json", 2_776_833, "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
)
# Disk sizes, never download sizes: the wheels' download bytes were not measured.
MODEL_DISK_BYTES = sum(f.size for f in MODEL_FILES)  # the pinned models' files, 2.4 GB; what Settings says before a download
RUNTIME_BYTES_ESTIMATE = 600_000_000  # the environment, estimated from the wheels, not measured
PYTHON_BYTES_ESTIMATE = 74_000_000  # CPython 3.12.13 as uv installed it on an M1 Pro, when uv has to download Python


def model_bytes() -> int:
    return sum(f.size for f in MODEL_FILES)


def model_url(name: str) -> str:
    part, path = name.split("/", 1)
    repository, revision = SOURCES[part]
    return f"https://huggingface.co/{repository}/resolve/{revision}/{path}"


def supported() -> bool:
    """The built-in model needs `fcntl.flock` and `pass_fds`: macOS and Linux in this slice."""
    return os.name == "posix"


def manifest() -> list[dict[str, Any]]:
    return [{"name": f.name, "size": f.size, "sha256": f.sha256} for f in MODEL_FILES]


class LocalEmbeddingError(Exception):
    """`builtin_unavailable`, `builtin_timeout`, `builtin_stopped`, `builtin_bad_reply` or `builtin_model_changed`, with
    what happened."""

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
        return self.models_root / f"qwen3-0.6b@{EMBEDDING_REVISION[:7]}-{RERANKER_REVISION[:7]}"

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

    def outdated(self) -> bool:
        """An installed copy built from another model or another package list than this DEIXIS pins (D20)."""
        try:
            marker = json.loads(self.installed_marker.read_text())
        except (OSError, ValueError):
            return True
        return (marker.get("model") != MODEL_ID or marker.get("reranker") != RERANKER_ID
                or marker.get("requirements") != requirements_digest())

    def runner_env(self) -> dict[str, str]:
        """Offline, with the data directory's own Hugging Face home: nothing is read from or written to ~/.cache."""
        return child_env({"HF_HUB_OFFLINE": "1", "HF_HOME": str(self.hf_home), "PYTHONUNBUFFERED": "1",
                          "TOKENIZERS_PARALLELISM": "false"})


def builtin_paths(data_dir: Path) -> BuiltinPaths:
    return BuiltinPaths(data_dir / "tools")


RUNNER_THREADS: ContextVar[int | None] = ContextVar("deixis_embedding_threads", default=None)


def runner_argv(paths: BuiltinPaths, threads: int | None = None) -> list[str]:
    """The runner inherits the in-use lock's descriptor through `pass_fds` and keeps it open while it lives."""
    return [str(paths.python), str(RUNNER), "--model-dir", str(paths.models), "--max-tokens", str(LOCAL_MAX_TOKENS),
            "--rerank-max-tokens", str(RERANK_MAX_TOKENS), "--manifest", json.dumps(manifest()), "--device", DEVICE,
            "--instruction", EMBEDDING_INSTRUCTION, "--rerank-instruction", RERANK_INSTRUCTION] + (
                ["--threads", str(threads)] if threads is not None else [])


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
        for part in models.rglob("*.part"):
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
        target.parent.mkdir(parents=True, exist_ok=True)
        if await asyncio.to_thread(file_matches, target, model_file):
            done += model_file.size
            if progress:
                progress(done, total)
            continue
        part = target.with_name(f"{target.name}.part")
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


def _answer(reply: Any, request_id: int) -> dict[str, Any]:
    if not isinstance(reply, dict) or reply.get("id") != request_id:
        raise LocalEmbeddingError("builtin_bad_reply", "the reply answers another request")
    if "error" in reply:
        raise LocalEmbeddingError("builtin_bad_reply", f"the runner reported: {str(reply['error'])[:300]}")
    return reply


def truncated_of(reply: dict[str, Any], count: int) -> list[int]:
    """The indexes of the texts the runner cut at its token limit; a reply that does not name them is refused."""
    cut = reply.get("truncated")
    if (not isinstance(cut, list) or any(type(i) is not int or not 0 <= i < count for i in cut)
            or len(set(cut)) != len(cut)):
        raise LocalEmbeddingError("builtin_bad_reply", "the reply does not say which texts were cut at the token limit")
    return sorted(cut)


def check_reply(reply: Any, request_id: int, count: int) -> list[array]:
    """The reply's vectors, or LocalEmbeddingError `builtin_bad_reply`: same id, one vector per text, DIMENSIONS values
    each, every value finite."""
    reply = _answer(reply, request_id)
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


def check_scores(reply: Any, request_id: int, count: int) -> list[float]:
    """A rerank reply's scores in input order: one probability (0 to 1) per document, else `builtin_bad_reply`."""
    scores = _answer(reply, request_id).get("scores")
    if (not isinstance(scores, list) or len(scores) != count
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1
                       for v in scores)):
        raise LocalEmbeddingError("builtin_bad_reply", f"the reply does not hold {count} scores between 0 and 1")
    return [float(v) for v in scores]


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
        self._threads: int | None = None

    def blocked(self) -> bool:
        return self.removing or self.installing

    def _argv(self) -> list[str]:
        argv = runner_argv(self.paths, self._threads)
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
                stderr=asyncio.subprocess.DEVNULL, env=self.paths.runner_env(), pass_fds=(fd, *library_lock.child_fds()), limit=64 * 1024 * 1024)
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

    async def embed(self, texts: list[str], kind: str, report: dict[str, int] | None = None) -> list[array]:
        """Vectors in input order for `kind` "document" or "query"; raises LocalEmbeddingError. `report`, when given,
        gets `truncated_texts`: how many of these texts the runner cut at LOCAL_MAX_TOKENS."""
        vectors, cut = await self._exchange(
            {"kind": kind, "texts": texts}, SECONDS_PER_BATCH_LIMIT,
            lambda reply, request_id: (check_reply(reply, request_id, len(texts)), truncated_of(reply, len(texts))))
        if report is not None:
            report["truncated_texts"] = report.get("truncated_texts", 0) + len(cut)
        return vectors

    async def rerank(self, query: str, documents: list[str], seconds: float) -> tuple[list[float], list[int]]:
        """The reranker's relevance probability for each document, in input order, and the indexes of the documents
        cut at RERANK_MAX_TOKENS. The runner loads the reranker for this request and frees it after; a request that
        outlives `seconds`, or is cancelled, kills the runner, so no reply is left unread."""
        return await self._exchange(
            {"kind": "rerank", "query": query, "documents": documents}, seconds,
            lambda reply, request_id: (check_scores(reply, request_id, len(documents)), truncated_of(reply, len(documents))))

    async def _exchange(self, request: dict[str, Any], seconds: float, check: Callable[[Any, int], Any]) -> Any:
        """Send one request, read its one reply line and return what `check` makes of it. A reply `check` refuses
        closes the runner, under the lock, before the error is raised."""
        if self.blocked() or not supported():
            raise LocalEmbeddingError("builtin_unavailable", "the built-in model is being installed or removed"
                                      if supported() else "the built-in model is not available on this platform")
        async with self.lock:
            if self.blocked():
                raise LocalEmbeddingError("builtin_unavailable", "the built-in model is being installed or removed")
            if self._idle:
                self._idle.cancel()
                self._idle = None
            threads = RUNNER_THREADS.get()
            if self._threads != threads:
                await self._kill()
                self._threads = threads
            if self.process is None or self.process.returncode is not None:
                self.process = None
                await self.start()  # a runner that died is started again once, at the next request
            self._requests += 1
            request_id = self._requests
            try:
                self.process.stdin.write((json.dumps({"id": request_id, **request}) + "\n").encode())
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                await self._kill()
                raise LocalEmbeddingError("builtin_stopped", "the runner stopped") from exc
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), seconds)
            except asyncio.TimeoutError:
                await self._kill()
                raise LocalEmbeddingError("builtin_timeout", f"no reply within {seconds:g} s") from None
            except asyncio.CancelledError:
                await self._kill()  # the reply would be left unread on the shared runner
                raise
            if not line:
                await self._kill()
                raise LocalEmbeddingError("builtin_stopped", "the runner stopped")
            try:
                result = check(json.loads(line), request_id)
            except (LocalEmbeddingError, json.JSONDecodeError) as exc:
                await self._kill()
                if isinstance(exc, LocalEmbeddingError):
                    raise
                raise LocalEmbeddingError("builtin_bad_reply", "the reply is not JSON") from exc
            self._idle = asyncio.get_running_loop().call_later(self.idle_seconds, lambda: asyncio.ensure_future(self.close()))
        return result

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

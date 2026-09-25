"""Installing, checking and removing the built-in embedding model from Settings (slice 21, D103).

The install is a four-step background job: (1) the environment (`uv venv`, Python 3.12), (2) `fastembed==0.8.1`,
(3) the five model files from the pinned revision, each checked against the manifest, (4) a start check: the runner
says ready and embeds a known sentence into one 384-dimension unit vector. `installed.json` is written last; an
environment without it is half-built and is built again. `uv` runs with its cache and its Python under the data
directory and `UV_PYTHON_PREFERENCE=only-managed`, so the system's Python and `~/.cache` are never touched.

The job lives on disk (`tools/embedding-job.json`, written atomically) and is owned by an OS lock
(`tools/embedding-install.lock`, `fcntl.flock`), held for the whole job and inherited by the `uv` children, so a DEIXIS
that dies mid-install leaves the lock held until its last child ends. Only the lock's owner writes the job file. A
second lock, `tools/embedding-in-use.lock`, is held shared by every runner of every DEIXIS process; install and
removal take it exclusively and give up (409) when they cannot. The PID in the job file is shown, never trusted.
POSIX only in this slice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from deixis.documents import local_embedding
from deixis.documents.local_embedding import BuiltinPaths, Integrity, LocalEmbedder, LocalEmbeddingError

log = logging.getLogger(__name__)
INSTALL_TIMEOUT_SECONDS = 60 * 60
OUTPUT_TAIL_CHARS = 4000
STEP_NAMES = ("environment", "package", "model_files", "start_check")
STOPPED = "stopped when DEIXIS closed"


class ServiceError(Exception):
    """A request the service refuses, with its code (409 in the API)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _flock(fd: int, flags: int) -> bool:
    import fcntl

    try:
        fcntl.flock(fd, flags)
    except OSError:
        return False
    return True


def _open_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o644)


def _try_lock(path: Path, exclusive: bool = True) -> int | None:
    """An open descriptor holding the lock, or None when another holder has it."""
    import fcntl

    fd = _open_lock(path)
    if _flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB):
        return fd
    os.close(fd)
    return None


def _release(fd: int | None) -> None:
    if fd is not None:
        os.close(fd)  # closing the last descriptor of the open file releases its flock


async def _to_completion(function: Any, *args: Any) -> Any:
    """Run a deleting `function` in a worker thread and wait for it to end, even when the caller is cancelled.

    A thread cannot be stopped: were the caller's cancel let through at once, its `finally` would release the install
    and in-use locks while the thread still deletes, and a new install could start on files being deleted. The cancel
    is held until the thread has finished, then raised."""
    future = asyncio.ensure_future(asyncio.to_thread(function, *args))
    cancelled = False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return future.result()


def _size(root: Path) -> int:
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


class EmbeddingService:
    def __init__(self, paths: BuiltinPaths, embedder: LocalEmbedder, http: httpx.AsyncClient | None = None):
        self.paths, self.embedder, self.http = paths, embedder, http
        self.integrity: Integrity = embedder.integrity
        self.job: dict[str, Any] | None = None  # the job this process owns, mirrored in the job file
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._install_fd: int | None = None
        self._in_use_fd: int | None = None

    # ---- the job file: written only by the install lock's owner ----------------------------
    def _write_job(self, job: dict[str, Any]) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        partial = self.paths.job_file.with_suffix(".json.tmp")
        partial.write_text(json.dumps(job))
        os.replace(partial, self.paths.job_file)

    def read_job(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.paths.job_file.read_text())
        except (OSError, ValueError):
            return None

    def owns_job(self) -> bool:
        return self._task is not None and not self._task.done()

    # ---- start: recovery and the full check ------------------------------------------------
    async def start(self) -> None:
        """Clean up after an install a closed DEIXIS left running, then check the files in full (the startup check)."""
        if not local_embedding.supported():
            return
        await asyncio.to_thread(self._recover)
        if self.paths.installed():
            await asyncio.to_thread(self.integrity.check_now)

    def _recover(self, install_fd: int | None = None) -> None:
        """With the install lock (taken here, or held by the caller) and the in-use lock both free: a job file that says
        running is marked failed, `*.part` files and a half-built environment are removed. Otherwise nothing is deleted
        and the job file is left as it is; recovery runs again at the next start or install."""
        own = install_fd is None
        fd = _try_lock(self.paths.install_lock) if own else install_fd
        if fd is None:
            return  # another process (or a uv child a dead one left) is installing
        try:
            job = self.read_job()
            in_use = _try_lock(self.paths.in_use_lock)
            if in_use is None:
                return  # a check runner of a dead install may still hold it: nothing is deleted
            try:
                local_embedding.remove_parts(self.paths.models)
                if job and job.get("status") == "running":
                    job.update(status="failed", finished_at=local_embedding.now_iso(),
                               output=((job.get("output") or "") + f"\n{STOPPED}").strip())
                    self._write_job(job)
                if self.paths.env.exists() and not self.paths.installed_marker.is_file():
                    shutil.rmtree(self.paths.env, ignore_errors=True)
            finally:
                _release(in_use)
        finally:
            if own:
                _release(fd)

    def _installing_elsewhere(self) -> bool:
        """Whether another process holds the install lock: probed without blocking and released at once."""
        if self.owns_job():
            return False
        fd = _try_lock(self.paths.install_lock)
        if fd is None:
            return True
        _release(fd)
        return False

    # ---- what Settings shows -----------------------------------------------------------------
    def option(self) -> dict[str, Any]:
        """The built-in choice for `embeddings.options`: available, else why not."""
        if not local_embedding.supported():
            return {"available": False, "reason": "The built-in model is not available on Windows yet",
                    "reason_code": "unsupported_platform", "last_full_check": None}
        state = self._state()
        reasons = {"not_installed": "Not downloaded", "failed": "Download failed", "installing": "Downloading",
                   "installing_elsewhere": "Downloading", "files_do_not_match": "Files do not match",
                   "removing": "Being removed", "remove_failed": "Removal did not finish"}
        available = state == "ready"
        return {"available": available, "reason": None if available else reasons.get(state, "Not downloaded"),
                "reason_code": None if available else state, "last_full_check": self.integrity.last_full_check()}

    def _state(self) -> str:
        if self.owns_job():
            return "installing"
        if self.embedder.removing:
            return "removing"
        if self._installing_elsewhere():
            return "installing_elsewhere"
        if self.paths.installed():
            return "ready" if self.integrity.available() else "files_do_not_match"
        job = self.read_job()
        if job and job.get("status") == "remove_failed":
            return "remove_failed"
        return "failed" if job and job.get("status") == "failed" else "not_installed"

    async def status(self) -> dict[str, Any]:
        if not local_embedding.supported():
            return {"status": "unsupported_platform"}
        state = self._state()
        job = self.job if self.owns_job() else self.read_job()
        size = await asyncio.to_thread(lambda: sum(_size(p) for p in (
            self.paths.env, self.paths.models_root, self.paths.uv_cache, self.paths.uv_python, self.paths.hf_home)))
        uv = shutil.which("uv")
        return {
            "status": state, "installed": self.paths.installed(), "available": state == "ready",
            "last_full_check": self.integrity.last_full_check(), "job": job,
            "model": {"name": local_embedding.MODEL_NAME, "id": local_embedding.MODEL_ID,
                      "repository": local_embedding.REPOSITORY, "revision": local_embedding.REVISION,
                      "package": local_embedding.FASTEMBED_PACKAGE, "files": local_embedding.manifest()},
            "sizes": {"runtime_bytes": local_embedding.RUNTIME_BYTES_ESTIMATE, "model_bytes": local_embedding.MODEL_DISK_BYTES,
                      "python_bytes": local_embedding.PYTHON_BYTES_ESTIMATE},
            "path": str(self.paths.root), "size_bytes": size,
            "uv": {"available": bool(uv), "reason": None if uv else "uv was not found on this computer's PATH",
                   "url": "https://docs.astral.sh/uv/getting-started/installation/"},
        }

    # ---- install --------------------------------------------------------------------------------
    async def install(self) -> dict[str, Any]:
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", "The built-in model is not available on Windows yet")
        import fcntl  # after the platform check: Windows has no fcntl
        if self.owns_job():
            raise ServiceError("install_running", "The built-in model is already being installed")
        uv = shutil.which("uv")
        if uv is None:
            raise ServiceError("uv_missing", "uv was not found on this computer's PATH")
        if self.paths.installed() and self.integrity.available():
            raise ServiceError("already_installed", "The built-in model is already installed")
        install_fd = _try_lock(self.paths.install_lock)
        if install_fd is None:
            raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
        # New requests are turned away and this process's own runner closes once its request has ended, so its shared
        # hold on the in-use lock is released before the exclusive one is asked for.
        self.embedder.installing = True
        try:
            await self.embedder.close()
            in_use_fd = _open_lock(self.paths.in_use_lock)
            if not _flock(in_use_fd, fcntl.LOCK_EX | fcntl.LOCK_NB):
                os.close(in_use_fd)
                raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
        except BaseException:
            self.embedder.installing = False
            _release(install_fd)
            raise
        self._install_fd, self._in_use_fd = install_fd, in_use_fd
        # A job a closed DEIXIS left running is recovered here, under both locks.
        job = self.read_job()
        if job and job.get("status") == "running":
            job.update(status="failed", finished_at=local_embedding.now_iso(),
                       output=((job.get("output") or "") + f"\n{STOPPED}").strip())
            self._write_job(job)
        self.job = {"status": "running", "step": 0, "steps": len(STEP_NAMES), "step_name": None,
                    "started_at": local_embedding.now_iso(), "finished_at": None, "pid": os.getpid(),
                    "bytes_done": 0, "bytes_total": local_embedding.model_bytes(), "output": ""}
        self._write_job(self.job)
        self._task = asyncio.create_task(self._run(uv))
        return dict(self.job)

    def _uv_env(self) -> dict[str, str]:
        p = self.paths
        return {**os.environ, "UV_CACHE_DIR": str(p.uv_cache), "UV_PYTHON_INSTALL_DIR": str(p.uv_python),
                "UV_PYTHON_BIN_DIR": str(p.uv_python / "bin"), "UV_PYTHON_PREFERENCE": "only-managed",
                "UV_NO_CONFIG": "1", "HF_HOME": str(p.hf_home), "PYTHONUNBUFFERED": "1"}

    def _step(self, index: int) -> None:
        self.job.update(step=index + 1, step_name=STEP_NAMES[index])
        self._write_job(self.job)

    def _output(self, text: str) -> None:
        self.job["output"] = (self.job["output"] + text)[-OUTPUT_TAIL_CHARS:]

    async def _command(self, argv: list[str]) -> None:
        self._proc = proc = await asyncio.create_subprocess_exec(
            *argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self._uv_env(),
            pass_fds=(self._install_fd,))  # the install lock outlives DEIXIS for as long as uv runs
        assert proc.stdout is not None
        async for chunk in proc.stdout:
            self._output(chunk.decode("utf-8", "replace"))
        code = await proc.wait()
        self._proc = None
        if code != 0:
            raise RuntimeError(f"{Path(argv[0]).name} {argv[1]} ended with exit code {code}")

    async def _run(self, uv: str) -> None:
        import fcntl

        p = self.paths
        status = "failed"
        try:
            async with asyncio.timeout(INSTALL_TIMEOUT_SECONDS):
                p.root.mkdir(parents=True, exist_ok=True)

                def clean() -> None:  # off the event loop: a half-built environment can be large
                    local_embedding.remove_parts(p.models)
                    if p.env.exists() and not p.installed_marker.is_file():
                        shutil.rmtree(p.env, ignore_errors=True)  # half-built: built again
                    p.installed_marker.unlink(missing_ok=True)  # "installed" again only once this job has passed
                await _to_completion(clean)
                self._step(0)
                await self._command([uv, "venv", "--allow-existing", "--python", local_embedding.PYTHON_VERSION, str(p.env)])
                self._step(1)
                await self._command([uv, "pip", "install", "--python", str(p.python), local_embedding.FASTEMBED_PACKAGE])
                self._step(2)

                def progress(done: int, total: int) -> None:
                    self.job.update(bytes_done=done, bytes_total=total)

                http = self.http or httpx.AsyncClient()
                try:
                    await local_embedding.download_model(http, p.models, progress)
                finally:
                    if self.http is None:
                        await http.aclose()
                self._write_job(self.job)
                self._step(3)
                # The files are written: the exclusive hold goes down to shared, and the check runner inherits it.
                fcntl.flock(self._in_use_fd, fcntl.LOCK_SH)
                checker = LocalEmbedder(p, self.integrity, runner=self.embedder.runner, python=self.embedder.python)
                try:
                    await checker.start(lock_fd=self._in_use_fd)
                    info = checker.ready_info or {}
                    self._output(f"runner ready: fastembed {info.get('fastembed')}, onnxruntime {info.get('onnxruntime')}\n")
                    (vector,) = await checker.embed([local_embedding.CHECK_SENTENCE], "query")
                    norm = sum(v * v for v in vector) ** 0.5
                    if abs(norm - 1.0) > 1e-3:
                        raise RuntimeError(f"the check sentence's vector has length {norm:.4f}, not 1")
                finally:
                    await checker.close()
                if not await asyncio.to_thread(self.integrity.check_now):
                    raise RuntimeError("the model files do not match after the install")
                marker = {"model": local_embedding.MODEL_ID, "repository": local_embedding.REPOSITORY,
                          "revision": local_embedding.REVISION, "package": local_embedding.FASTEMBED_PACKAGE,
                          "fastembed": info.get("fastembed"), "onnxruntime": info.get("onnxruntime"),
                          "installed_at": local_embedding.now_iso()}
                partial = p.installed_marker.with_suffix(".json.tmp")
                partial.write_text(json.dumps(marker))
                os.replace(partial, p.installed_marker)  # the last file an install writes
                status = "succeeded"
        except asyncio.CancelledError:
            status = "cancelled"
            self._output("\nCancelled.")
        except TimeoutError:
            self._output("\nStopped after 60 minutes.")
        except (LocalEmbeddingError, local_embedding.DownloadError, RuntimeError, OSError, ValueError) as exc:
            self._output(f"\n{type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - shown to the person as the failed step's output
            log.exception("built-in model install failed")
            self._output(f"\n{type(exc).__name__}: {exc}")
        finally:
            if self._proc and self._proc.returncode is None:
                self._proc.kill()
                await self._proc.wait()
            self._proc = None
            await _to_completion(local_embedding.remove_parts, p.models)
            self.job.update(status=status, finished_at=local_embedding.now_iso())
            self._write_job(self.job)
            _release(self._in_use_fd)
            _release(self._install_fd)
            self._install_fd = self._in_use_fd = None
            self.embedder.installing = False

    async def cancel(self) -> dict[str, Any]:
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", "The built-in model is not available on Windows yet")
        if self.owns_job():
            if self._proc and self._proc.returncode is None:
                self._proc.kill()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            return dict(self.job)
        if self._installing_elsewhere():
            raise ServiceError("in_use_by_another_process", "The install runs in another DEIXIS process")
        raise ServiceError("no_install_running", "The built-in model is not being installed")

    # ---- remove ---------------------------------------------------------------------------------
    async def remove(self) -> None:
        """Delete the environment and the model files. Similarities and vectors already stored stay (D29).

        A file that cannot be deleted is not hidden: the job file says `remove_failed` with what stayed, Settings shows
        it, and the request fails with 409 `remove_incomplete`."""
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", "The built-in model is not available on Windows yet")
        import fcntl  # after the platform check: Windows has no fcntl
        if self.owns_job():
            raise ServiceError("install_running", "The built-in model is being installed")
        install_fd = _try_lock(self.paths.install_lock)
        if install_fd is None:
            raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
        # Before any await: from here every new request is turned away without a lock or a process.
        self.embedder.removing = True
        in_use_fd = None
        try:
            await self.embedder.close()
            in_use_fd = _open_lock(self.paths.in_use_lock)
            if not _flock(in_use_fd, fcntl.LOCK_EX | fcntl.LOCK_NB):
                raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
            self.integrity.reset()
            self.job = None
            left = await _to_completion(local_embedding.remove_files, self.paths)
            if left:
                self._write_job({"status": "remove_failed", "step": 0, "steps": len(STEP_NAMES), "step_name": None,
                                 "started_at": None, "finished_at": local_embedding.now_iso(), "pid": os.getpid(),
                                 "output": "Could not delete:\n" + "\n".join(left[:20])})
                raise ServiceError("remove_incomplete", f"{len(left)} file(s) could not be deleted, for example {left[0]}")
            self.paths.job_file.unlink(missing_ok=True)
        finally:
            self.embedder.removing = False
            _release(in_use_fd)
            _release(install_fd)

    async def stop(self) -> None:
        if self.owns_job():
            if self._proc and self._proc.returncode is None:
                self._proc.kill()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.embedder.close()

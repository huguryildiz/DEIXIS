"""Downloading, checking and removing the built-in local models from Settings, one catalog model at a time.

An install is a three-step background job for one model: (1) the llama.cpp runtime, when it is not in place or its
server binary does not match its record (`documents/llama_runtime.py`), (2) the model's GGUF file from its pinned
revision, checked for its byte count and sha256 (a file already in place is checked in full instead of downloaded
again), (3) a start check: the model's own `llama-server` starts, answers the authenticated probe and is stopped. The
file's full check is recorded on disk only after the start check passed.

One job at a time. It lives on disk (`tools/local-models-job.json`, written atomically) and is owned by an OS lock
(`tools/local-models-install.lock`, `fcntl.flock`) that covers the runtime and every model file; under it what is
present is checked again before anything is downloaded, and the leftovers of a stopped install (`*.part`, temporary
folders) are removed. Each model has an in-use lock (`tools/locks/<id>.lock`) that its servers hold shared; install and
removal take it exclusively and give up (409) when they cannot. The runtime has one too and is never removed while a
model file is in place. Nothing here changes a saved choice: Settings stores `(provider, model)` and only the person's
"Use" changes it.

The earlier PyTorch built-in model (D88: `tools/embedding`, `embedding-models`, `embedding-hf-home`, `uv-python`,
`uv-cache`) is reported with its measured size and removed only on request.

POSIX only in this slice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any

import httpx

from deixis.documents import builtin_catalog, llama_runtime, local_embedding
from deixis.documents.builtin_catalog import Model
from deixis.documents.local_embedding import (BuiltinPaths, LlamaServer, LocalEmbeddingError, LocalModels,
                                              ModelIntegrity, try_lock)
from deixis.tools.job_failure import COULD_NOT_RUN, failure_line

log = logging.getLogger("deixis.workflow.local_embedding_service")  # the name before the folders; log names stay
INSTALL_TIMEOUT_SECONDS = 4 * 60 * 60  # the 8 GB reranker on a slow line
OUTPUT_TAIL_CHARS = 4000
STEP_NAMES = ("runtime", "model_file", "start_check")
STOPPED = "stopped when DEIXIS closed"
UNSUPPORTED = "The built-in models are not available on this platform yet"
REASONS = {"not_installed": "Not downloaded", "failed": "Download failed", "installing": "Downloading",
           "installing_elsewhere": "Downloading", "files_do_not_match": "Files do not match",
           "not_checked": "Not checked", "runtime_missing": "llama.cpp is missing", "removing": "Being removed",
           "remove_failed": "Removal did not finish", "unsupported_platform": UNSUPPORTED}


class ServiceError(Exception):
    """A request the service refuses, with its code (409 in the API; `unknown_model` is 404)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _release(fd: int | None) -> None:
    if fd is not None:
        os.close(fd)  # closing the last descriptor of the open file releases its flock


async def _to_completion(function: Any, *args: Any) -> Any:
    """Run a deleting `function` in a worker thread and wait for it to end, even when the caller is cancelled: were
    the cancel let through at once, the locks would be released while the thread still deletes."""
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


async def wait_exclusive(path, seconds: float = 3.0) -> int | None:
    """LOCK_EX on `path`, waiting a moment for this process's own stopped server to finish exiting; None when another
    holder keeps it."""
    loop = asyncio.get_running_loop()
    ends = loop.time() + seconds
    while True:
        fd = try_lock(path, exclusive=True)
        if fd is not None or loop.time() >= ends:
            return fd
        await asyncio.sleep(0.05)


def _machine() -> dict[str, Any]:
    from deixis.tools.local_tools import machine

    found = machine()
    return {"memory_gb": found.get("memory_gb"), "chip": found.get("chip")}


class LocalModelService:
    def __init__(self, paths: BuiltinPaths, models: LocalModels, http: httpx.AsyncClient | None = None):
        self.paths, self.models, self.http = paths, models, http
        self.job: dict[str, Any] | None = None  # the job this process owns, mirrored in the job file
        self._task: asyncio.Task | None = None
        self._install_fd: int | None = None
        self._model_fd: int | None = None
        self._checker: LlamaServer | None = None
        self._starting = False  # an install request is between its check and its job: a second one is turned away

    # ---- the job file: written only by the install lock's owner ----------------------------
    def _write_job(self, job: dict[str, Any]) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        partial = self.paths.job_file.with_suffix(".json.tmp")
        partial.write_text(json.dumps(job))
        os.replace(partial, self.paths.job_file)

    def read_job(self) -> dict[str, Any] | None:
        try:
            job = json.loads(self.paths.job_file.read_text())
        except (OSError, ValueError):
            return None
        return job if isinstance(job, dict) else None

    def owns_job(self) -> bool:
        return self._task is not None and not self._task.done()

    @staticmethod
    def _model(model_id: str | None) -> Model:
        model = builtin_catalog.get(model_id)
        if model is None:
            raise ServiceError("unknown_model", f"'{model_id}' is not a built-in model of this DEIXIS")
        return model

    # ---- start: recovery -------------------------------------------------------------------------
    async def start(self) -> None:
        """Clean up after an install a closed DEIXIS left running. The models' last full checks are on disk."""
        if local_embedding.supported():
            await asyncio.to_thread(self._recover)

    def _recover(self) -> None:
        """With the install lock free: a job file that says running is marked failed, `*.part` files and temporary
        runtime folders are removed. Otherwise nothing is touched; recovery runs again at the next start or install."""
        fd = try_lock(self.paths.install_lock, exclusive=True)
        if fd is None:
            return  # another process is installing
        try:
            self._clean()
            job = self.read_job()
            if job and job.get("status") == "running":
                job.update(status="failed", finished_at=llama_runtime.now_iso(),
                           output=((job.get("output") or "") + f"\n{STOPPED}").strip())
                self._write_job(job)
        finally:
            _release(fd)

    def _clean(self) -> None:
        local_embedding.remove_parts(self.paths)
        llama_runtime.clean_leftovers(self.paths.runtime)

    def _installing_elsewhere(self) -> bool:
        """Whether another process holds the install lock: probed without blocking and released at once."""
        if self.owns_job():
            return False
        fd = try_lock(self.paths.install_lock, exclusive=True)
        if fd is None:
            return True
        _release(fd)
        return False

    # ---- what Settings shows -----------------------------------------------------------------
    def state(self, model_id: str) -> str:
        model = self._model(model_id)
        if not local_embedding.supported():
            return "unsupported_platform"
        if self.owns_job() and (self.job or {}).get("model") == model.id:
            return "installing"
        if self.models.busy.get(model.id) == "removing":
            return "removing"
        job = self.read_job() or {}
        if job.get("model") == model.id and job.get("status") == "running" and self._installing_elsewhere():
            return "installing_elsewhere"
        if self.paths.installed(model):
            if self.models.available(model.id):
                return "ready"
            if job.get("model") == model.id and job.get("status") in ("failed", "cancelled"):
                return "failed"
            if ModelIntegrity(self.paths, model).available():
                return "runtime_missing"
            return "files_do_not_match" if ModelIntegrity(self.paths, model).last_full_check() else "not_checked"
        if job.get("model") == model.id and job.get("status") in ("failed", "remove_failed"):
            return job["status"]
        return "not_installed"

    def option(self, model_id: str) -> dict[str, Any]:
        """One catalog model as a choice in `embeddings.options` / `rerankers.options`: available, else why not."""
        model = self._model(model_id)
        state = self.state(model.id)
        available = state == "ready"
        return {"available": available, "reason": None if available else REASONS.get(state, "Not downloaded"),
                "reason_code": None if available else state,
                "last_full_check": ModelIntegrity(self.paths, model).last_full_check()}

    def options(self, kind: str) -> list[dict[str, Any]]:
        return [{"model": m.id, "name": m.name, **self.option(m.id)} for m in builtin_catalog.of_kind(kind)]

    async def status(self) -> dict[str, Any]:
        machine = await asyncio.to_thread(_machine)
        recommended = builtin_catalog.recommended(machine["memory_gb"])
        legacy = self.paths.legacy()
        legacy_bytes = await asyncio.to_thread(lambda: sum(local_embedding.tree_size(p) for p in legacy))
        job = self.job if self.owns_job() else self.read_job()
        supported = local_embedding.supported()
        runtime = self.paths.runtime
        models = []
        for model in builtin_catalog.CATALOG:
            option = self.option(model.id)
            on_disk = await asyncio.to_thread(local_embedding.tree_size, self.paths.model_dir(model.id))
            models.append({**model.card(), "state": self.state(model.id), **option,
                           "recommended": recommended[model.kind] == model.id,
                           "may_not_fit": bool(machine["memory_gb"] and model.memory_gb > machine["memory_gb"] * 0.5),
                           "bytes_on_disk": on_disk,
                           "job": job if job and job.get("model") == model.id else None})
        pinned = llama_runtime.asset()
        return {
            "supported": supported, "status": None if supported else "unsupported_platform",
            "runtime": {"name": "llama.cpp", "tag": llama_runtime.TAG, "installed": runtime.installed(),
                        "asset": pinned.name if pinned else None, "download_bytes": pinned.bytes if pinned else None,
                        "bytes": await asyncio.to_thread(runtime.size) if runtime.root.exists() else 0},
            "models": models, "machine": machine,
            "recommended": recommended | {"rule": f"the largest Qwen3 model whose estimated memory is at most "
                                                  f"{int(builtin_catalog.RECOMMEND_SHARE * 100)}% of this computer's "
                                                  "memory; a starting value, not measured"},
            "legacy": {"present": bool(legacy), "bytes": legacy_bytes, "paths": [str(p) for p in legacy]},
            "job": job, "path": str(self.paths.root),
        }

    # ---- install --------------------------------------------------------------------------------
    async def install(self, model_id: str) -> dict[str, Any]:
        model = self._model(model_id)
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", UNSUPPORTED)
        if self.owns_job() or self._starting:
            raise ServiceError("install_running", "A built-in model is already being downloaded")
        self._starting = True  # before the first await, so two requests at once start one install
        try:
            return await self._begin_install(model)
        finally:
            self._starting = False

    async def _begin_install(self, model: Model) -> dict[str, Any]:
        if self.models.available(model.id):
            raise ServiceError("already_installed", f"{model.name} is already downloaded")
        install_fd = try_lock(self.paths.install_lock, exclusive=True)
        if install_fd is None:
            raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
        # New requests to this model are turned away and this process's own server stops once its request has ended,
        # so its shared hold on the model's lock is gone before the exclusive one is asked for.
        self.models.busy[model.id] = "installing"
        try:
            await self.models.close(model.id)
            model_fd = await wait_exclusive(self.paths.model_lock(model.id))
            if model_fd is None:
                raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
        except BaseException:
            self.models.busy.pop(model.id, None)
            _release(install_fd)
            raise
        self._install_fd, self._model_fd = install_fd, model_fd
        try:
            job = self.read_job()
            if job and job.get("status") == "running":  # left by a closed DEIXIS: recovered here, under the lock
                job.update(status="failed", finished_at=llama_runtime.now_iso(),
                           output=((job.get("output") or "") + f"\n{STOPPED}").strip())
                self._write_job(job)
            runtime_bytes = 0 if self.paths.runtime.installed() else llama_runtime.asset().bytes
            self.job = {"status": "running", "model": model.id, "step": 0, "steps": len(STEP_NAMES), "step_name": None,
                        "started_at": llama_runtime.now_iso(), "finished_at": None, "pid": os.getpid(),
                        "bytes_done": 0, "bytes_total": model.bytes + runtime_bytes, "output": ""}
            self._write_job(self.job)
        except BaseException as exc:  # a full disk must not leave the locks held and the install stuck
            self._release_locks()
            if isinstance(exc, OSError):
                raise ServiceError("job_record_failed", f"The download could not start: {exc.strerror or exc}") from exc
            raise
        self._task = asyncio.create_task(self._run(model))
        self._task.add_done_callback(self._task_ended)
        return dict(self.job)

    def _step(self, index: int) -> None:
        self.job.update(step=index + 1, step_name=STEP_NAMES[index])
        self._write_job(self.job)

    def _output(self, text: str) -> None:
        self.job["output"] = (self.job["output"] + text)[-OUTPUT_TAIL_CHARS:]

    async def _run(self, model: Model) -> None:
        import fcntl

        status = "failed"
        http = self.http or httpx.AsyncClient()
        base = 0

        def progress(done: int) -> None:
            self.job["bytes_done"] = base + done

        try:
            async with asyncio.timeout(INSTALL_TIMEOUT_SECONDS):
                await _to_completion(self._clean)
                self._step(0)
                runtime = self.paths.runtime
                if not (runtime.installed() and await asyncio.to_thread(runtime.server_matches)):
                    runtime_fd = try_lock(self.paths.runtime_lock, exclusive=True)
                    if runtime_fd is None:
                        raise RuntimeError("llama.cpp is in use by another model's server and does not match its "
                                           "record; close DEIXIS's other windows and try again")
                    try:
                        await _to_completion(llama_runtime.clean_leftovers, runtime)
                        await llama_runtime.install(http, runtime, progress)
                    finally:
                        _release(runtime_fd)
                    self._output(f"llama.cpp {llama_runtime.TAG} in place\n")
                    base = self.job["bytes_done"]
                self._step(1)
                integrity = ModelIntegrity(self.paths, model)
                integrity.reset()  # "checked" again only once this job has passed
                target = self.paths.model_file(model)
                if target.is_file() and await asyncio.to_thread(
                        llama_runtime.file_matches, target, model.bytes, model.sha256):
                    self._output(f"{model.file} already in place and whole\n")
                else:
                    await llama_runtime.download(http, model.url, target, model.bytes, model.sha256, progress)
                self.job["bytes_done"] = self.job["bytes_total"]
                self._write_job(self.job)
                self._step(2)
                # The file is written: the exclusive hold goes down to shared, and the check server inherits it.
                fcntl.flock(self._model_fd, fcntl.LOCK_SH)
                self._checker = LlamaServer(self.paths, model, self.models.client)
                try:
                    await self._checker.start(lock_fd=self._model_fd)
                    self._output(f"llama-server answered the {'embedding' if model.kind == 'embedding' else 'rerank'} probe\n")
                finally:
                    await self._checker.stop()
                    self._checker = None
                integrity.record(True)  # the download (or the full check above) hashed the file in full
                status = "succeeded"
        except asyncio.CancelledError:
            status = "cancelled"
            self._output("\nCancelled.")
        except TimeoutError:
            self._output(f"\nStopped after {INSTALL_TIMEOUT_SECONDS // 3600} hours.")
        except (LocalEmbeddingError, llama_runtime.DownloadError, llama_runtime.UnsafeArchive, RuntimeError, OSError,
                ValueError) as exc:
            self._output("\n" + failure_line(exc, "The built-in model download"))
        except Exception:  # noqa: BLE001 - shown to the person as the failed step's output
            log.exception("built-in model install failed")
            self._output("\n" + COULD_NOT_RUN)
        finally:
            try:
                try:
                    if self._checker is not None:
                        await self._checker.kill()
                        self._checker = None
                    if self.http is None:
                        await http.aclose()
                    await _to_completion(local_embedding.remove_parts, self.paths)
                finally:
                    self.job.update(status=status, finished_at=llama_runtime.now_iso())
                    try:
                        self._write_job(self.job)
                    except OSError:  # a full disk: the locks below are still released
                        log.exception("built-in model install: the job record could not be written")
            finally:
                self._release_locks()

    def _task_ended(self, task: asyncio.Task) -> None:
        """A task cancelled before its first step never runs `_run`, so its `finally` never lets go of the locks: this
        does. When `_run` did run, its `finally` has released them already."""
        if self._install_fd is None and self._model_fd is None:
            return
        self.job.update(status="cancelled" if task.cancelled() else "failed", finished_at=llama_runtime.now_iso())
        try:
            self._write_job(self.job)
        except OSError:
            log.exception("built-in model install: the job record could not be written")
        self._release_locks()

    def _release_locks(self) -> None:
        _release(self._model_fd)
        _release(self._install_fd)
        self._install_fd = self._model_fd = None
        if self.job:
            self.models.busy.pop(self.job.get("model"), None)

    async def check(self, model_id: str) -> dict[str, Any]:
        """Check files: hash the model file in full against its pin and the runtime's server against its record.
        Nothing is fetched online; a newer model arrives with a newer DEIXIS."""
        model = self._model(model_id)
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", UNSUPPORTED)
        if (self.owns_job() and (self.job or {}).get("model") == model.id) or model.id in self.models.busy \
                or not self.paths.installed(model):
            raise ServiceError("not_installed", f"{model.name} is not downloaded")
        await asyncio.to_thread(ModelIntegrity(self.paths, model).check_now)
        return await self.status()

    async def cancel(self) -> dict[str, Any]:
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", UNSUPPORTED)
        if self.owns_job():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            return dict(self.job)
        if self._installing_elsewhere():
            raise ServiceError("in_use_by_another_process", "The download runs in another DEIXIS process")
        raise ServiceError("no_install_running", "No built-in model is being downloaded")

    # ---- remove ---------------------------------------------------------------------------------
    async def remove(self, model_id: str) -> None:
        """Delete one model's file. Similarities, vectors and scores already stored stay (D29). The runtime goes too
        when no model file is left. A file that cannot be deleted is not hidden: the job file says `remove_failed`."""
        model = self._model(model_id)
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", UNSUPPORTED)
        if self.owns_job():
            raise ServiceError("install_running", "A built-in model is being downloaded")
        install_fd = try_lock(self.paths.install_lock, exclusive=True)
        if install_fd is None:
            raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
        self.models.busy[model.id] = "removing"  # before any await: new requests are turned away from here
        model_fd = None
        try:
            await self.models.close(model.id)
            model_fd = await wait_exclusive(self.paths.model_lock(model.id))
            if model_fd is None:
                raise ServiceError("in_use_by_another_process", "in use by another DEIXIS process")
            left = await _to_completion(local_embedding.remove_model_files, self.paths, model)
            if left:
                self._write_job({"status": "remove_failed", "model": model.id, "step": 0, "steps": len(STEP_NAMES),
                                 "step_name": None, "started_at": None, "finished_at": llama_runtime.now_iso(),
                                 "pid": os.getpid(), "output": "Could not delete:\n" + "\n".join(left[:20])})
                raise ServiceError("remove_incomplete", f"{len(left)} file(s) could not be deleted, for example {left[0]}")
            job = self.read_job()
            if job and job.get("model") == model.id:
                self.paths.job_file.unlink(missing_ok=True)
            if not any(self.paths.installed(m) for m in builtin_catalog.CATALOG):
                await self._remove_runtime()
        finally:
            self.models.busy.pop(model.id, None)
            _release(model_fd)
            _release(install_fd)

    async def _remove_runtime(self) -> None:
        """The runtime goes with the last model, unless a server still holds it (it is then left for next time)."""
        runtime_fd = try_lock(self.paths.runtime_lock, exclusive=True)
        if runtime_fd is None:
            return
        try:
            await _to_completion(shutil.rmtree, self.paths.runtime.root, True)
        finally:
            _release(runtime_fd)

    async def remove_legacy(self) -> dict[str, Any]:
        """Delete what the earlier PyTorch built-in model (D88) left, on the person's request only. Its locks are
        taken exclusively first, so an older DEIXIS still running it is not pulled from under its feet."""
        if not local_embedding.supported():
            raise ServiceError("unsupported_platform", UNSUPPORTED)
        root = self.paths.root
        install_fd = try_lock(root / "embedding-install.lock", exclusive=True) if (root / "embedding-install.lock").exists() else None
        in_use_fd = try_lock(root / "embedding-in-use.lock", exclusive=True) if (root / "embedding-in-use.lock").exists() else None
        busy = ((root / "embedding-install.lock").exists() and install_fd is None) or \
               ((root / "embedding-in-use.lock").exists() and in_use_fd is None)
        try:
            if busy:
                raise ServiceError("in_use_by_another_process", "the earlier built-in model is in use by another DEIXIS")
            failed: list[str] = []

            def delete() -> None:
                for path in self.paths.legacy():
                    if path.name.endswith(".lock"):
                        continue
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path, onexc=lambda _f, p, _e: failed.append(str(p)))
                    else:
                        try:
                            path.unlink()
                        except OSError:
                            failed.append(str(path))
            await _to_completion(delete)
            if failed:
                raise ServiceError("remove_incomplete", f"{len(failed)} file(s) could not be deleted, for example {failed[0]}")
        finally:
            _release(in_use_fd)
            _release(install_fd)
        for name in ("embedding-install.lock", "embedding-in-use.lock"):
            (root / name).unlink(missing_ok=True)
        return await self.status()

    async def stop(self) -> None:
        if self.owns_job():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.models.close()

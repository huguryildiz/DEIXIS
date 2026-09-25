"""Installing, checking and removing the built-in embedding model (slice 21, D103, task 3).

A fake `uv` script stands in for uv and records the environment it was given; model files are small SYNTHETIC stand-ins
served through httpx.MockTransport; the runner is the fake runner. A second process is a real child process holding a
lock, as another DEIXIS server or a runner left by a dead one would. Passing shows the job, its locks and its recovery,
not a real install (the plan's acceptance (a) does that).
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError
from deixis.workflow import local_embedding_service
from deixis.workflow.local_embedding_service import EmbeddingService, ServiceError
from builtin_helpers import FAKE_RUNNER, fake_embedder, fake_manifest, install_fake, write_fake_uv



@pytest.fixture
def setup(tmp_path, monkeypatch):
    bodies = fake_manifest(monkeypatch)
    uv = write_fake_uv(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{uv.parent}:{os.environ['PATH']}")
    record = tmp_path / "uv-calls.jsonl"
    monkeypatch.setenv("FAKE_UV_RECORD", str(record))
    monkeypatch.setenv("FAKE_RUNNER", "ok")
    paths = local_embedding.builtin_paths(tmp_path / "data")
    seen = []

    def handler(request):
        name = request.url.path.rsplit("/", 1)[-1]
        if request.url.host != "huggingface.co" or name not in bodies:
            return httpx.Response(404)  # the local tools' probes (Ollama, LM Studio, Zotero) find nothing
        seen.append(request.url.path)
        return httpx.Response(200, content=bodies[name])
    return {"paths": paths, "record": record, "bodies": bodies, "transport": httpx.MockTransport(handler), "seen": seen}


def service_of(setup, embedder=None):
    paths = setup["paths"]
    return EmbeddingService(paths, embedder or fake_embedder(paths), httpx.AsyncClient(transport=setup["transport"]))


async def until_done(service):
    while service.owns_job():
        await asyncio.sleep(0.02)
    return service.read_job()


class Holder:
    """Another process holding one of the lock files, shared or exclusive, until it is closed."""

    def __init__(self, path, exclusive=False):
        code = ("import fcntl, os, sys\n"
                f"fd = os.open({str(path)!r}, os.O_RDWR | os.O_CREAT)\n"
                f"fcntl.flock(fd, fcntl.{'LOCK_EX' if exclusive else 'LOCK_SH'})\n"
                "print('held', flush=True)\nsys.stdin.read()\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert self.process.stdout.readline().strip() == "held"

    def close(self):
        self.process.stdin.close()
        self.process.wait(10)


# ---- the job --------------------------------------------------------------------------------------

def test_the_install_runs_its_four_steps_under_the_data_directory_and_writes_installed_json_last(setup):
    service, paths = service_of(setup), setup["paths"]

    async def go():
        job = await service.install()
        assert job["status"] == "running"
        with pytest.raises(ServiceError) as second:
            await service.install()
        return second.value.code, await until_done(service), await service.status(), service.option()
    second, job, status, option = asyncio.run(go())
    assert second == "install_running"
    assert (job["status"], job["step"], job["steps"], job["step_name"]) == ("succeeded", 4, 4, "start_check")
    calls = [json.loads(line) for line in setup["record"].read_text().splitlines()]
    assert [c["argv"][:2] for c in calls] == [["venv", "--allow-existing"], ["pip", "install"]]
    assert calls[1]["argv"][-1] == "fastembed==0.8.1"
    for call in calls:  # uv's cache, its Python and Hugging Face's home all live under the data directory
        env = call["env"]
        assert env["UV_CACHE_DIR"] == str(paths.uv_cache) and env["UV_PYTHON_INSTALL_DIR"] == str(paths.uv_python)
        assert env["UV_PYTHON_PREFERENCE"] == "only-managed" and env["HF_HOME"] == str(paths.hf_home)
    assert json.loads(paths.installed_marker.read_text())["revision"] == local_embedding.REVISION
    # installed.json is the last file written: nothing under the data directory is newer.
    newest = max(p.stat().st_mtime_ns for p in paths.root.rglob("*") if p.is_file() and p.name not in (
        "embedding-job.json", "embedding-install.lock", "embedding-in-use.lock"))
    assert paths.installed_marker.stat().st_mtime_ns == newest
    assert (status["status"], status["available"], option["available"]) == ("ready", True, True)
    assert status["last_full_check"]["passed"] is True
    assert not paths.job_file.with_suffix(".json.tmp").exists()


def test_a_failed_step_shows_its_output_and_an_environment_without_installed_json_is_built_again(setup, monkeypatch):
    service, paths = service_of(setup), setup["paths"]
    monkeypatch.setenv("FAKE_UV_FAIL", "pip")

    async def go():
        await service.install()
        return await until_done(service)
    job = asyncio.run(go())
    assert (job["status"], job["step"]) == ("failed", 2) and "SYNTHETIC uv failure in pip" in job["output"]
    assert paths.env.exists() and not paths.installed()
    assert service.option()["reason"] == "Download failed"
    (paths.env / "SYNTHETIC-left-over").write_text("half")
    monkeypatch.delenv("FAKE_UV_FAIL")
    service2 = service_of(setup)

    async def again():
        await service2.install()
        return await until_done(service2)
    assert asyncio.run(again())["status"] == "succeeded"
    assert not (paths.env / "SYNTHETIC-left-over").exists()  # the half-built environment was built again


def test_a_reinstall_does_not_download_the_files_that_are_already_whole(setup):
    service, paths = service_of(setup), setup["paths"]
    paths.models.mkdir(parents=True)
    for name, body in setup["bodies"].items():
        if name != "tokenizer.json":
            (paths.models / name).write_bytes(body)

    async def go():
        await service.install()
        return await until_done(service)
    assert asyncio.run(go())["status"] == "succeeded"
    assert [p.rsplit("/", 1)[-1] for p in setup["seen"]] == ["tokenizer.json"]


def test_cancel_stops_this_process_s_job_and_writes_it_cancelled(setup, monkeypatch):
    service, paths = service_of(setup), setup["paths"]
    monkeypatch.setenv("FAKE_UV_SLEEP", "30")

    async def go():
        await service.install()
        await asyncio.sleep(0.3)
        job = await service.cancel()
        with pytest.raises(ServiceError) as none:
            await service.cancel()
        return job, none.value.code
    job, none = asyncio.run(go())
    assert job["status"] == "cancelled" and service.read_job()["status"] == "cancelled" and none == "no_install_running"
    Holder(paths.install_lock, exclusive=True).close()  # the lock was released: another holder takes it at once
    assert not list(paths.models.glob("*.part")) if paths.models.exists() else True


def test_remove_deletes_the_environment_and_files_and_keeps_nothing_running(setup):
    paths = setup["paths"]
    install_fake(paths)
    (paths.uv_cache / "SYNTHETIC").mkdir(parents=True)
    service = service_of(setup)
    asyncio.run(service.start())
    assert service.option()["available"] is True
    asyncio.run(service.remove())
    assert not paths.env.exists() and not paths.models_root.exists() and not paths.uv_cache.exists()
    assert service.option()["reason_code"] == "not_installed" and service.embedder.removing is False


def test_the_endpoints_need_the_csrf_token_and_a_local_host(setup, tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={}, start_worker=False,
                     http_client=httpx.AsyncClient(transport=setup["transport"]),
                     extra_hosts=("testserver",), trusted_clients=("testclient",),
                     local_embedder=fake_embedder(setup["paths"]))
    with TestClient(app) as client:
        assert client.post("/api/semantic-search/builtin/install").status_code == 403  # no CSRF token
        assert client.get("/api/semantic-search/builtin", headers={"host": "evil.example"}).status_code == 403
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        assert client.get("/api/semantic-search/builtin").json()["status"] == "not_installed"
        assert client.post("/api/semantic-search/builtin/install").status_code == 202
        deadline = time.time() + 20
        while client.get("/api/semantic-search/builtin").json()["status"] != "ready" and time.time() < deadline:
            time.sleep(0.05)
        status = client.get("/api/semantic-search/builtin").json()
        assert status["status"] == "ready" and status["sizes"]["runtime_bytes"] == local_embedding.RUNTIME_BYTES_ESTIMATE
        cancel = client.post("/api/semantic-search/builtin/cancel")
        assert (cancel.status_code, cancel.json()["detail"]["reason"]) == (409, "no_install_running")
        assert client.delete("/api/semantic-search/builtin").json()["status"] == "not_installed"


# ---- recovery after a DEIXIS that closed mid-install ---------------------------------------------------

def stale_job(paths):
    install_fake(paths)
    paths.installed_marker.unlink()
    (paths.models / "model_optimized.onnx.part").write_bytes(b"SYNTHETIC half")
    job = {"status": "running", "step": 3, "steps": 4, "started_at": "2026-09-25T10:00:00.000+00:00", "pid": 999999,
           "output": "SYNTHETIC"}
    paths.job_file.write_text(json.dumps(job))


def test_a_job_left_running_is_failed_and_its_leftovers_removed_when_the_locks_are_free(setup):
    paths = setup["paths"]
    stale_job(paths)
    service = service_of(setup)
    asyncio.run(service.start())
    job = service.read_job()
    assert job["status"] == "failed" and job["output"].endswith("stopped when DEIXIS closed")
    assert not paths.env.exists() and not list(paths.models.glob("*.part"))


def test_with_the_install_lock_held_elsewhere_nothing_is_deleted_and_install_remove_and_cancel_refuse(setup):
    paths = setup["paths"]
    stale_job(paths)
    before = paths.job_file.read_bytes()
    holder = Holder(paths.install_lock, exclusive=True)
    try:
        service = service_of(setup)
        asyncio.run(service.start())
        status = asyncio.run(service.status())
        codes = []
        for call in (service.install, service.remove, service.cancel):
            with pytest.raises(ServiceError) as info:
                asyncio.run(call())
            codes.append(info.value.code)
    finally:
        holder.close()
    assert status["status"] == "installing_elsewhere" and status["job"]["status"] == "running"
    assert codes == ["in_use_by_another_process"] * 3
    assert paths.job_file.read_bytes() == before and paths.env.exists() and list(paths.models.glob("*.part"))


def test_with_a_check_runner_of_a_dead_install_still_holding_the_in_use_lock_recovery_waits(setup):
    paths = setup["paths"]
    stale_job(paths)
    before = paths.job_file.read_bytes()
    holder = Holder(paths.in_use_lock)  # the ready check's runner outlived the DEIXIS that started it
    try:
        asyncio.run(service_of(setup).start())
        assert paths.job_file.read_bytes() == before and paths.env.exists()
    finally:
        holder.close()
    asyncio.run(service_of(setup).start())  # the next start recovers
    assert json.loads(paths.job_file.read_text())["status"] == "failed" and not paths.env.exists()


DEAD_INSTALLER = """
import asyncio, os, sys
sys.path[:0] = {paths!r}
import httpx
from deixis.documents import local_embedding
import builtin_helpers
from deixis.workflow.local_embedding_service import EmbeddingService

class Patch:
    def setattr(self, obj, name, value):
        setattr(obj, name, value)
builtin_helpers.fake_manifest(Patch())
bodies = builtin_helpers.FILE_BODIES
paths = local_embedding.builtin_paths(__import__("pathlib").Path({data!r}))
transport = httpx.MockTransport(lambda r: httpx.Response(200, content=bodies[r.url.path.rsplit("/", 1)[-1]]))
service = EmbeddingService(paths, builtin_helpers.fake_embedder(paths), httpx.AsyncClient(transport=transport))

async def main():
    await service.install()
    while service.job["step"] < 4:
        await asyncio.sleep(0.02)
    print("checking", flush=True)
    await asyncio.sleep(3600)
asyncio.run(main())
"""


def test_a_dead_install_s_ready_check_blocks_recovery_until_its_runner_ends(setup, tmp_path, monkeypatch):
    """Another process installs; it is killed while its check runner holds the in-use lock shared."""
    paths = setup["paths"]
    monkeypatch.setenv("FAKE_RUNNER", "slow_ready:30")
    script = tmp_path / "installer.py"
    script.write_text(DEAD_INSTALLER.format(paths=[str(p) for p in (os.path.dirname(__file__), "backend", ".")],
                                            data=str(tmp_path / "data")))
    installer = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True,
                                 cwd=os.path.dirname(os.path.dirname(__file__)))
    try:
        assert installer.stdout.readline().strip() == "checking"
        time.sleep(0.3)
        # While the check runs, this process can take neither lock: DELETE and install refuse.
        mine = service_of(setup)
        for call in (mine.install, mine.remove):
            with pytest.raises(ServiceError, match="in use by another DEIXIS process"):
                asyncio.run(call())
        installer.kill()
        installer.wait(10)
        before = paths.job_file.read_bytes()
        asyncio.run(service_of(setup).start())  # the install lock is free; the check runner still holds in-use
        assert paths.job_file.read_bytes() == before and json.loads(before)["status"] == "running" and paths.env.exists()
    finally:
        if installer.poll() is None:
            installer.kill()
    # The orphaned check runner is killed; the next start recovers.
    subprocess.run(["pkill", "-f", f"{FAKE_RUNNER.name} --model-dir {paths.models}"], check=False)
    deadline = time.time() + 10
    while time.time() < deadline:
        asyncio.run(service_of(setup).start())
        if json.loads(paths.job_file.read_text())["status"] == "failed":
            break
        time.sleep(0.1)
    assert json.loads(paths.job_file.read_text())["status"] == "failed" and not paths.env.exists()


# ---- removal and install against a runner in use ---------------------------------------------------

def test_remove_waits_for_the_request_in_flight_and_turns_new_ones_away(setup, monkeypatch):
    paths = setup["paths"]
    install_fake(paths)
    monkeypatch.setenv("FAKE_RUNNER", "slow:0.5")
    log = paths.root / "runner.log"
    monkeypatch.setenv("FAKE_RUNNER_LOG", str(log))
    embedder = fake_embedder(paths)
    service = service_of(setup, embedder)
    asyncio.run(service.start())

    async def go():
        await embedder.embed(["SYNTHETIC warm"], "document")
        in_flight = asyncio.create_task(embedder.embed(["SYNTHETIC in flight"], "document"))
        await asyncio.sleep(0.1)
        removal = asyncio.create_task(service.remove())
        await asyncio.sleep(0)
        assert embedder.removing is True
        with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
            await embedder.embed(["SYNTHETIC during"], "document")
        vectors = await in_flight
        await removal
        with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
            await embedder.embed(["SYNTHETIC after"], "document")
        return vectors
    vectors = asyncio.run(go())
    assert len(vectors) == 1 and not paths.env.exists() and not paths.models_root.exists()
    assert [line.split()[:2] for line in log.read_text().splitlines()] == [["document", "1"]] * 2  # "during" and "after" reached no runner


def test_remove_during_an_install_is_refused(setup, monkeypatch):
    service = service_of(setup)
    monkeypatch.setenv("FAKE_UV_SLEEP", "30")

    async def go():
        await service.install()
        with pytest.raises(ServiceError) as info:
            await service.remove()
        await service.cancel()
        return info.value.code
    assert asyncio.run(go()) == "install_running"


def test_a_runner_of_another_process_blocks_remove_and_install_until_it_ends(setup):
    paths = setup["paths"]
    install_fake(paths)
    service = service_of(setup)
    asyncio.run(service.start())
    holder = Holder(paths.in_use_lock)  # another DEIXIS server's runner
    try:
        with pytest.raises(ServiceError) as removal:
            asyncio.run(service.remove())
        assert paths.installed() and service.embedder.removing is False
        paths.installed_marker.unlink()  # a reinstall is asked for: it too needs the exclusive lock
        with pytest.raises(ServiceError) as install:
            asyncio.run(service.install())
        install_fake(paths)
    finally:
        holder.close()
    assert (removal.value.code, str(removal.value)) == ("in_use_by_another_process", "in use by another DEIXIS process")
    assert install.value.code == "in_use_by_another_process"
    asyncio.run(service.remove())
    assert not paths.env.exists()


def test_while_another_process_removes_a_request_here_gets_builtin_unavailable(setup):
    paths = setup["paths"]
    install_fake(paths)
    embedder = fake_embedder(paths)
    holder = Holder(paths.in_use_lock, exclusive=True)  # the other process's removal holds it exclusively
    try:
        with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
            asyncio.run(embedder.embed(["SYNTHETIC one"], "document"))
    finally:
        holder.close()
    assert embedder.process is None


def test_an_install_waits_for_this_process_s_request_then_closes_its_runner_and_turns_requests_away(setup, monkeypatch):
    paths = setup["paths"]
    install_fake(paths)
    paths.installed_marker.unlink()
    monkeypatch.setenv("FAKE_RUNNER", "slow:0.5")
    monkeypatch.setenv("FAKE_UV_SLEEP", "0.5")
    embedder = fake_embedder(paths)
    service = service_of(setup, embedder)

    async def go():
        # The runner needs an installed environment to start: mark it, start it, then take the mark away again.
        install_fake(paths)
        await embedder.embed(["SYNTHETIC warm"], "document")
        paths.installed_marker.unlink()
        in_flight = asyncio.create_task(embedder.embed(["SYNTHETIC in flight"], "document"))
        await asyncio.sleep(0.1)
        runner = embedder.process
        install = asyncio.create_task(service.install())
        await asyncio.sleep(0)
        vectors = await in_flight
        await install
        closed = runner.returncode is not None
        with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
            await embedder.embed(["SYNTHETIC during"], "document")
        job = await until_done(service)
        return vectors, closed, job
    vectors, closed, job = asyncio.run(go())
    assert len(vectors) == 1 and closed and job["status"] == "succeeded"


def test_the_install_s_ready_check_runs_under_the_shared_lock_and_blocks_other_processes(setup, monkeypatch):
    paths = setup["paths"]
    monkeypatch.setenv("FAKE_RUNNER", "slow_ready:1.5")
    service = service_of(setup)
    probe = ("import fcntl, os, sys\n"
             "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)\n"
             "try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n    print('free')\n"
             "except OSError:\n    print('held')\n")

    def held(path):
        return subprocess.run([sys.executable, "-c", probe, str(path)], capture_output=True, text=True).stdout.strip()

    async def go():
        await service.install()
        while service.job["step"] < 4:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.5)
        during = (await asyncio.to_thread(held, paths.install_lock), await asyncio.to_thread(held, paths.in_use_lock))
        return during, await until_done(service)
    during, job = asyncio.run(go())
    assert during == ("held", "held") and job["status"] == "succeeded" and paths.installed()
    assert (held(paths.install_lock), held(paths.in_use_lock)) == ("free", "free")


# ---- the integrity cache and the platform --------------------------------------------------------------

def test_a_file_changed_in_place_shows_the_last_check_until_the_runner_s_full_check_fails(setup):
    paths = setup["paths"]
    install_fake(paths)
    embedder = fake_embedder(paths)
    service = service_of(setup, embedder)
    asyncio.run(service.start())
    first = service.option()
    target = paths.models / "config.json"
    stat = target.stat()
    body = target.read_bytes()
    with open(target, "r+b") as handle:  # same size, same inode
        handle.write(bytes([body[0] ^ 1]))
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # same mtime
    cached = service.option()
    assert cached["available"] is True and cached["last_full_check"] == first["last_full_check"]
    with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
        asyncio.run(embedder.embed(["SYNTHETIC one"], "document"))
    after = service.option()
    assert after["available"] is False and after["last_full_check"]["passed"] is False
    assert after["reason_code"] == "files_do_not_match"


class WindowsOs:
    name = "nt"

    def __getattr__(self, attribute):
        return getattr(os, attribute)


def test_on_another_platform_every_builtin_endpoint_says_so_before_any_lock(setup, tmp_path, monkeypatch):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={}, start_worker=False,
                     http_client=httpx.AsyncClient(transport=setup["transport"]),
                     extra_hosts=("testserver",), trusted_clients=("testclient",),
                     local_embedder=fake_embedder(setup["paths"]))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        # os.name reads "nt" where the built-in model's platform check reads it; the rest of the app stays on POSIX.
        monkeypatch.setattr(local_embedding, "os", WindowsOs())
        paths = setup["paths"]
        paths.install_lock.unlink(missing_ok=True)  # written by the start's recovery, on this real POSIX system
        paths.in_use_lock.unlink(missing_ok=True)
        option = next(o for o in client.get("/api/semantic-search").json()["options"] if o["provider"] == "builtin")
        status = client.get("/api/semantic-search/builtin")
        refused = [client.post("/api/semantic-search/builtin/install"), client.post("/api/semantic-search/builtin/cancel"),
                   client.delete("/api/semantic-search/builtin")]
    assert (option["available"], option["reason_code"]) == (False, "unsupported_platform")
    assert (status.status_code, status.json()) == (200, {"status": "unsupported_platform"})
    assert [(r.status_code, r.json()["detail"]["reason"]) for r in refused] == [(409, "unsupported_platform")] * 3
    assert not paths.install_lock.exists() and not paths.in_use_lock.exists()


def test_install_timeout_and_step_names_are_the_plan_s():
    assert local_embedding_service.STEP_NAMES == ("environment", "package", "model_files", "start_check")


# ---- Sol review, round 1 (findings 3, 4, 6) ---------------------------------------------------------

def test_without_the_fcntl_module_every_builtin_path_refuses_before_importing_it(setup, monkeypatch):
    """Windows has no fcntl: the platform check comes before any import of it (Sol r1, finding 3)."""
    service = service_of(setup)
    monkeypatch.setattr(local_embedding, "os", WindowsOs())
    monkeypatch.setitem(sys.modules, "fcntl", None)  # `import fcntl` now raises ImportError, as on Windows

    async def go():
        codes = []
        for action in (service.install, service.cancel, service.remove):
            with pytest.raises(ServiceError) as refused:
                await action()
            codes.append(refused.value.code)
        with pytest.raises(LocalEmbeddingError) as embedding:
            await service.embedder.embed(["SYNTHETIC text"], "document")
        return codes, embedding.value.code, await service.status(), service.option()
    codes, embedding, status, option = asyncio.run(go())
    assert codes == ["unsupported_platform"] * 3 and embedding == "builtin_unavailable"
    assert status == {"status": "unsupported_platform"} and option["reason_code"] == "unsupported_platform"
    assert not setup["paths"].install_lock.exists() and not setup["paths"].in_use_lock.exists()


def test_a_file_that_cannot_be_deleted_fails_the_removal_and_settings_says_so(setup):
    """Removal names what stayed instead of reporting success (Sol r1, finding 4)."""
    paths = setup["paths"]
    install_fake(paths)
    service = service_of(setup)
    asyncio.run(service.start())
    os.chmod(paths.models, 0o500)  # the model files cannot be unlinked from a folder without write permission
    try:
        with pytest.raises(ServiceError) as refused:
            asyncio.run(service.remove())
        status = asyncio.run(service.status())
        option = service.option()
    finally:
        os.chmod(paths.models, 0o700)
    assert refused.value.code == "remove_incomplete" and "could not be deleted" in str(refused.value)
    assert (paths.models / "config.json").exists() and not paths.installed_marker.exists()
    assert status["status"] == "remove_failed" and status["job"]["status"] == "remove_failed"
    assert str(paths.models) in status["job"]["output"]
    assert (option["available"], option["reason"]) == (False, "Removal did not finish")
    assert service.embedder.removing is False
    asyncio.run(service.remove())  # once the file can go, removing again clears it and the job file
    assert not paths.models_root.exists() and not paths.job_file.exists()
    assert service.option()["reason_code"] == "not_installed"


def test_the_install_clears_a_half_built_environment_off_the_event_loop(setup, monkeypatch):
    """A large half-built environment is deleted in a worker thread, so the API keeps answering (Sol r1, finding 6)."""
    import shutil
    import threading

    paths = setup["paths"]
    paths.python.parent.mkdir(parents=True)
    (paths.env / "SYNTHETIC-half-built").write_text("x")  # an environment without installed.json
    (paths.models).mkdir(parents=True)
    (paths.models / "model_optimized.onnx.part").write_bytes(b"SYNTHETIC")
    threads = []
    real = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(path, *args, **kwargs)
    monkeypatch.setattr(local_embedding_service.shutil, "rmtree", rmtree)
    monkeypatch.setattr(local_embedding, "remove_parts", lambda models, real=local_embedding.remove_parts: (
        threads.append(threading.current_thread() is threading.main_thread()), real(models))[1])
    service = service_of(setup)

    async def go():
        await service.install()
        return await until_done(service)
    job = asyncio.run(go())
    assert job["status"] == "succeeded" and threads and not any(threads)
    assert not (paths.env / "SYNTHETIC-half-built").exists()


def test_a_cancel_during_a_slow_clean_up_holds_the_locks_until_the_deletion_has_ended(setup, monkeypatch):
    """The deleting thread is waited for before the locks go, so no new install starts on files still being deleted
    (Sol r2, finding 2)."""
    import threading

    paths = setup["paths"]
    started, finished = threading.Event(), threading.Event()
    real = local_embedding.remove_parts

    def slow_remove_parts(models):
        if started.is_set():  # only the first call, the install's opening clean-up, is slow
            return real(models)
        started.set()
        time.sleep(0.5)
        real(models)
        finished.set()
    monkeypatch.setattr(local_embedding, "remove_parts", slow_remove_parts)
    service = service_of(setup)

    async def go():
        await service.install()
        while not started.is_set():
            await asyncio.sleep(0.01)
        job = await service.cancel()
        deleted_before_return = finished.is_set()
        free = local_embedding_service._try_lock(paths.install_lock)
        local_embedding_service._release(free)
        return job, deleted_before_return, free is not None
    job, deleted_before_return, lock_free = asyncio.run(go())
    assert job["status"] == "cancelled" and deleted_before_return and lock_free
    assert service.embedder.installing is False

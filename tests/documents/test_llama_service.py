"""Downloading, checking and removing the built-in models one at a time, the catalog's Settings routes, and the
earlier PyTorch install (`workflow/local_embedding_service.py`, `api/app.py`).

The runtime archive and the model files are SYNTHETIC, served through httpx.MockTransport as GitHub and Hugging Face
would; the archive's `llama-server` is `fake_llama_server.py`. A second process holding a lock is a real child process.
Passing shows the job, its checks, locks and choices, not a real download or a real model.
"""

import asyncio
import json
import os
import subprocess
import sys
import tarfile
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import builtin_catalog, llama_runtime, local_embedding
from deixis.documents.local_embedding import LocalModels
from deixis.workflow.local_embedding_service import LocalModelService, ServiceError
from builtin_helpers import Downloads, fake_catalog, install_model, install_runtime, pin_tarball, tarball

EMB, RER = "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"
pytestmark = pytest.mark.skipif(os.name != "posix", reason="the built-in models are POSIX only in this slice")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    bodies = fake_catalog(monkeypatch)
    archive = tarball()
    pin_tarball(monkeypatch, archive)
    monkeypatch.setenv("FAKE_LLAMA_RECORD", str(tmp_path / "record.jsonl"))
    paths = local_embedding.builtin_paths(tmp_path / "data")
    downloads = Downloads(archive, bodies)
    return {"paths": paths, "downloads": downloads, "bodies": bodies, "tmp": tmp_path}


def service_of(setup):
    paths = setup["paths"]
    return LocalModelService(paths, LocalModels(paths), httpx.AsyncClient(transport=setup["downloads"].transport()))


async def until_done(service):
    while service.owns_job():
        await asyncio.sleep(0.02)
    return service.read_job()


async def install(service, model_id):
    await service.install(model_id)
    return await until_done(service)


class Holder:
    """Another process holding one lock file, shared or exclusive, until it is closed."""

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

def test_an_install_puts_the_runtime_then_the_model_in_place_checks_it_and_records_the_full_check(setup):
    service = service_of(setup)
    paths = setup["paths"]

    async def scenario():
        job = await install(service, EMB)
        status = await service.status()
        await service.stop()
        return job, status
    job, status = asyncio.run(scenario())
    assert (job["status"], job["model"], job["step"], job["step_name"]) == ("succeeded", EMB, 3, "start_check"), job["output"]
    assert job["bytes_done"] == job["bytes_total"] == len(setup["bodies"][EMB]) + llama_runtime.asset().bytes
    assert paths.runtime.installed() and paths.model_file(builtin_catalog.get(EMB)).read_bytes() == setup["bodies"][EMB]
    assert service.models.available(EMB) and not service.models.available(RER)
    card = next(m for m in status["models"] if m["id"] == EMB)
    assert (card["state"], card["available"], card["last_full_check"]["passed"]) == ("ready", True, True)
    assert next(m for m in status["models"] if m["id"] == RER)["state"] == "not_installed"
    assert status["runtime"]["installed"] and status["runtime"]["tag"] == llama_runtime.TAG
    assert list(paths.root.rglob("*.part")) == [] and not [p for p in paths.runtime.root.iterdir() if p.name.startswith(".tmp-")]
    # A second model: the runtime is in place and is not downloaded again.
    before = len(setup["downloads"].requests)
    service = service_of(setup)
    job = asyncio.run(install(service, RER))
    assert job["status"] == "succeeded" and setup["downloads"].requests[before:] == [builtin_catalog.get(RER).url]


@pytest.mark.parametrize("wrong", ["size", "sha"])
def test_a_model_file_of_another_size_or_digest_fails_and_leaves_nothing(setup, wrong):
    model = builtin_catalog.get(EMB)
    body = setup["bodies"][EMB]
    setup["downloads"].override[model.url] = body + b"x" if wrong == "size" else bytes(reversed(body))
    service = service_of(setup)
    job = asyncio.run(install(service, EMB))
    assert job["status"] == "failed" and "[could_not_run]" in job["output"]
    assert not setup["paths"].model_file(model).exists() and list(setup["paths"].root.rglob("*.part")) == []
    assert service.state(EMB) == "failed" and not service.models.available(EMB)


def test_a_runtime_archive_of_another_digest_fails_before_any_model_byte(setup):
    setup["downloads"].override[llama_runtime.asset().url] = b"SYNTHETIC not the archive"
    job = asyncio.run(install(service_of(setup), EMB))
    assert job["status"] == "failed" and job["step_name"] == "runtime"
    assert builtin_catalog.get(EMB).url not in setup["downloads"].requests and not setup["paths"].runtime.installed()


def link(name, target, kind=tarfile.SYMTYPE):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, target
    return info


@pytest.mark.parametrize("entries", [
    [("/etc/llama-server", b"x", 0o755)],
    [("../llama-server", b"x", 0o755)],
    [("llama/llama-server", b"x", 0o755), link("llama/escape", "../../outside")],
    [("llama/llama-server", b"x", 0o755), link("llama/abs", "/etc/passwd")],
    [("llama/a", b"x", 0o644)],  # no server at all
], ids=["absolute", "dotdot", "symlink_out", "symlink_absolute", "no_server"])
def test_an_unsafe_or_wrong_archive_is_refused_and_nothing_is_unpacked(setup, monkeypatch, entries):
    archive = tarball(entries)
    pin_tarball(monkeypatch, archive)
    setup["downloads"].archive = archive
    job = asyncio.run(install(service_of(setup), EMB))
    assert job["status"] == "failed", job
    root = setup["paths"].runtime.root
    assert not setup["paths"].runtime.installed() and not (root / llama_runtime.TAG).exists()
    assert [p.name for p in root.iterdir()] == [] and not (setup["tmp"] / "outside").exists()


def test_a_file_already_whole_is_not_downloaded_again_and_leftovers_are_cleaned(setup):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, EMB, check=False)
    (paths.model_dir(RER)).mkdir(parents=True)
    (paths.model_dir(RER) / "x.gguf.part").write_bytes(b"SYNTHETIC half")
    (paths.runtime.root / ".tmp-left").mkdir()
    job = asyncio.run(install(service_of(setup), EMB))
    assert job["status"] == "succeeded" and "already in place" in job["output"]
    assert setup["downloads"].requests == []
    assert not (paths.model_dir(RER) / "x.gguf.part").exists() and not (paths.runtime.root / ".tmp-left").exists()


def test_cancel_stops_the_download_and_writes_it_cancelled(setup):
    model = builtin_catalog.get(EMB)

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield setup["bodies"][EMB][:10]
            await asyncio.sleep(30)
            yield b""

    setup["downloads"].override[model.url] = httpx.Response(200, stream=Slow())
    service = service_of(setup)

    async def scenario():
        await service.install(EMB)
        await asyncio.sleep(0.5)
        return await service.cancel()
    job = asyncio.run(scenario())
    assert job["status"] == "cancelled" and service.read_job()["status"] == "cancelled"
    assert list(setup["paths"].root.rglob("*.part")) == []
    fd = local_embedding.try_lock(setup["paths"].install_lock, exclusive=True)  # released
    assert fd is not None
    os.close(fd)


def test_a_dead_install_is_marked_failed_at_start_and_its_parts_removed(setup):
    paths = setup["paths"]
    paths.root.mkdir(parents=True)
    paths.job_file.write_text(json.dumps({"status": "running", "model": EMB, "output": "SYNTHETIC"}))
    paths.model_dir(EMB).mkdir(parents=True)
    (paths.model_dir(EMB) / "f.part").write_bytes(b"x")
    service = service_of(setup)
    asyncio.run(service.start())
    assert service.read_job()["status"] == "failed" and "stopped when DEIXIS closed" in service.read_job()["output"]
    assert not (paths.model_dir(EMB) / "f.part").exists()


def test_two_installs_at_once_start_one_and_another_process_s_install_lock_is_respected(setup):
    service = service_of(setup)

    async def scenario():
        results = await asyncio.gather(service.install(EMB), service.install(RER), return_exceptions=True)
        await until_done(service)
        return [r.code for r in results if isinstance(r, ServiceError)]
    assert asyncio.run(scenario()) == ["install_running"]
    holder = Holder(setup["paths"].install_lock, exclusive=True)
    try:
        with pytest.raises(ServiceError) as refused:
            asyncio.run(service_of(setup).install(RER))
        assert refused.value.code == "in_use_by_another_process"
    finally:
        holder.close()


# ---- check and remove ----------------------------------------------------------------------------------

def test_check_files_finds_a_changed_byte(setup):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, EMB)
    service = service_of(setup)
    assert service.state(EMB) == "ready"
    target = paths.model_file(builtin_catalog.get(EMB))
    data = bytearray(target.read_bytes())
    data[0] ^= 1
    st = os.stat(target)
    target.write_bytes(bytes(data))
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))  # same size and time: only a full check sees it
    status = asyncio.run(service.check(EMB))
    card = next(m for m in status["models"] if m["id"] == EMB)
    assert (card["state"], card["last_full_check"]["passed"]) == ("files_do_not_match", False)


def test_remove_keeps_the_runtime_while_another_model_is_installed_and_takes_it_with_the_last(setup):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, EMB)
    install_model(paths, RER)
    service = service_of(setup)
    asyncio.run(service.remove(EMB))
    assert not paths.model_dir(EMB).exists() and paths.runtime.installed() and service.state(RER) == "ready"
    asyncio.run(service.remove(RER))
    assert not paths.runtime.root.exists()


def test_remove_is_refused_while_another_process_s_server_holds_the_model(setup):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, EMB)
    holder = Holder(paths.model_lock(EMB))
    try:
        with pytest.raises(ServiceError) as refused:
            asyncio.run(service_of(setup).remove(EMB))
        assert refused.value.code == "in_use_by_another_process"
        assert paths.model_file(builtin_catalog.get(EMB)).exists()
    finally:
        holder.close()


def test_remove_waits_for_this_process_s_server_and_stops_it(setup):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, EMB)
    service = service_of(setup)

    async def scenario():
        await service.models.embed(EMB, ["alpha"], "document")
        assert EMB in service.models.servers
        await service.remove(EMB)
        return service.models.servers
    assert asyncio.run(scenario()) == {}
    assert not paths.model_dir(EMB).exists()


# ---- the earlier PyTorch install (D88) ---------------------------------------------------------------

def test_the_earlier_pytorch_install_is_listed_with_its_size_and_removed_only_on_request(setup):
    paths = setup["paths"]
    (paths.root / "embedding" / "bin").mkdir(parents=True)
    (paths.root / "embedding" / "bin" / "python").write_bytes(b"x" * 100)
    (paths.root / "embedding-models").mkdir()
    (paths.root / "embedding-models" / "w.safetensors").write_bytes(b"y" * 50)
    (paths.root / "uv-cache").mkdir()
    (paths.root / "embedding-in-use.lock").write_bytes(b"")
    service = service_of(setup)
    asyncio.run(service.start())
    status = asyncio.run(service.status())
    assert status["legacy"]["present"] and status["legacy"]["bytes"] == 150
    assert (paths.root / "embedding").exists()  # nothing deleted by itself
    holder = Holder(paths.root / "embedding-in-use.lock")
    try:
        with pytest.raises(ServiceError) as refused:
            asyncio.run(service.remove_legacy())
        assert refused.value.code == "in_use_by_another_process"
    finally:
        holder.close()
    status = asyncio.run(service.remove_legacy())
    assert status["legacy"] == {"present": False, "bytes": 0, "paths": []}


# ---- Settings: options, choices, routes ---------------------------------------------------------------

def client_of(setup, tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={}, start_worker=False,
                     http_client=httpx.AsyncClient(transport=setup["downloads"].transport()),
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def wait_ready(client, model_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        card = next(m for m in client.get("/api/semantic-search/builtin").json()["models"] if m["id"] == model_id)
        if card["state"] in ("ready", "failed"):
            return card
        time.sleep(0.05)
    raise AssertionError("the install did not end")


def test_the_routes_download_choose_and_remove_and_nothing_but_use_changes_a_choice(setup, tmp_path):
    client = client_of(setup, tmp_path)
    try:
        assert client.post("/api/semantic-search/builtin/install", json={"model": EMB}, headers={"x-deixis-csrf": ""}).status_code == 403
        status = client.get("/api/semantic-search/builtin").json()
        assert [m["id"] for m in status["models"]] == [m.id for m in builtin_catalog.CATALOG]
        assert set(status) >= {"supported", "runtime", "models", "machine", "recommended", "legacy"}
        assert status["recommended"]["embedding"] in {m.id for m in builtin_catalog.of_kind("embedding")}
        assert client.post("/api/semantic-search/builtin/install", json={"model": "nope"}).status_code == 404
        refused = client.put("/api/semantic-search", json={"provider": "builtin", "model": EMB})
        assert refused.status_code == 422 and refused.json()["detail"] == "Not downloaded"
        assert client.put("/api/semantic-search", json={"provider": "builtin"}).status_code == 422
        client.put("/api/semantic-search", json={"provider": "off"})
        assert client.post("/api/semantic-search/builtin/install", json={"model": EMB}).status_code == 202
        assert wait_ready(client, EMB)["state"] == "ready"
        view = client.get("/api/semantic-search").json()
        assert view["provider"] == "off"  # a download changes no choice
        options = [o for o in view["options"] if o["provider"] == "builtin"]
        assert [(o["model"], o["available"]) for o in options] == [
            (EMB, True), ("qwen3-embedding-4b", False), ("qwen3-embedding-8b", False), ("bge-m3", False)]
        chosen = client.put("/api/semantic-search", json={"provider": "builtin", "model": EMB}).json()
        assert (chosen["provider"], chosen["model"], chosen["builtin_model_changed"]) == ("builtin", EMB, None)
        # The reranker: its own model, chosen by id.
        assert client.put("/api/reranking", json={"enabled": True, "provider": "builtin", "model": RER}).status_code == 422
        assert client.post("/api/semantic-search/builtin/install", json={"model": RER}).status_code == 202
        assert wait_ready(client, RER)["state"] == "ready"
        rerank = client.put("/api/reranking", json={"enabled": True, "provider": "builtin", "model": RER}).json()
        assert (rerank["provider"], rerank["model"]) == ("builtin", RER)
        # Removing the chosen model keeps the choice; the option says why it cannot run.
        assert client.request("DELETE", "/api/semantic-search/builtin", json={"model": EMB}).status_code == 200
        view = client.get("/api/semantic-search").json()
        assert (view["provider"], view["model"]) == ("builtin", EMB)
        assert next(o for o in view["options"] if o.get("model") == EMB)["reason"] == "Not downloaded"
        assert client.get("/api/reranking").json()["model"] == RER
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("saved", [{"provider": "builtin", "model": "qwen3-embedding-0.6b@97b0c61:512:mps:i1234abcd"},
                                   {"provider": "builtin"}])
def test_a_saved_earlier_built_in_choice_is_kept_and_reported_never_remapped(setup, tmp_path, saved):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, EMB)
    client = client_of(setup, tmp_path)
    try:
        client.app.state.store.set_setting("semantic_search", saved)
        client.app.state.store.set_setting("reranking", {"enabled": True, "provider": "builtin"})
        view = client.get("/api/semantic-search").json()
        assert view["provider"] == "builtin" and view["model"] == saved.get("model", builtin_catalog.NO_MODEL)
        assert view["builtin_model_changed"] == {"from": saved.get("model"), "to": None}
        rerank = client.get("/api/reranking").json()
        assert rerank["builtin_model_changed"] == {"from": None, "to": None}
    finally:
        client.__exit__(None, None, None)


def test_on_another_platform_every_route_says_so_before_any_lock(setup, tmp_path, monkeypatch):
    client = client_of(setup, tmp_path)
    try:
        monkeypatch.setattr(llama_runtime, "ASSETS", {})
        paths = setup["paths"]
        paths.install_lock.unlink(missing_ok=True)  # written by the start's recovery, on this real POSIX system
        status = client.get("/api/semantic-search/builtin").json()
        refused = [client.post("/api/semantic-search/builtin/install", json={"model": EMB}),
                   client.post("/api/semantic-search/builtin/cancel"),
                   client.request("DELETE", "/api/semantic-search/builtin", json={"model": EMB})]
        option = next(o for o in client.get("/api/semantic-search").json()["options"] if o["provider"] == "builtin")
    finally:
        client.__exit__(None, None, None)
    assert (status["supported"], status["status"]) == (False, "unsupported_platform")
    assert {m["state"] for m in status["models"]} == {"unsupported_platform"}
    assert [(r.status_code, r.json()["detail"]["reason"]) for r in refused] == [(409, "unsupported_platform")] * 3
    assert (option["available"], option["reason_code"]) == (False, "unsupported_platform")
    assert not paths.install_lock.exists() and not paths.model_lock(EMB).exists()
    assert setup["downloads"].requests == [] or all("huggingface" not in u and "github" not in u
                                                    for u in setup["downloads"].requests)

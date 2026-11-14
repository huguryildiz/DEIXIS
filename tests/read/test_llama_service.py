"""Downloading, checking and removing built-in rerankers one at a time through the model service.

The runtime archive and the model files are SYNTHETIC, served through httpx.MockTransport as GitHub and Hugging Face
would; the archive's `llama-server` is `fake_llama_server.py`. A second process holding a lock is a real child process.
Passing shows the job, its checks, locks and choices, not a real download or a real model.
"""

import asyncio
import json
import os
import tarfile
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.runtime.config import Settings
from deixis.documents import builtin_catalog, llama_runtime, local_embedding
from deixis.documents.local_embedding import LocalModels
from deixis.workflow.run.local_embedding_service import LocalModelService
from builtin_helpers import Downloads, fake_catalog, install_model, install_runtime, pin_tarball, tarball


RER_LARGE, RER = "qwen3-reranker-4b", "qwen3-reranker-0.6b"


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


def test_an_install_puts_the_runtime_then_the_model_in_place_checks_it_and_records_the_full_check(setup):
    service = service_of(setup)
    paths = setup["paths"]

    async def scenario():
        job = await install(service, RER_LARGE)
        status = await service.status()
        await service.stop()
        return job, status
    job, status = asyncio.run(scenario())
    assert (job["status"], job["model"], job["step"], job["step_name"]) == ("succeeded", RER_LARGE, 3, "start_check"), job["output"]
    assert job["bytes_done"] == job["bytes_total"] == len(setup["bodies"][RER_LARGE]) + llama_runtime.asset().bytes
    assert paths.runtime.installed() and paths.model_file(builtin_catalog.get(RER_LARGE)).read_bytes() == setup["bodies"][RER_LARGE]
    assert service.models.available(RER_LARGE) and not service.models.available(RER)
    card = next(m for m in status["models"] if m["id"] == RER_LARGE)
    assert (card["state"], card["available"], card["last_full_check"]["passed"]) == ("ready", True, True)
    assert next(m for m in status["models"] if m["id"] == RER)["state"] == "not_installed"
    assert status["runtime"]["installed"] and status["runtime"]["tag"] == llama_runtime.TAG
    assert list(paths.root.rglob("*.part")) == [] and not [p for p in paths.runtime.root.iterdir() if p.name.startswith(".tmp-")]
    # A second model: the runtime is in place and is not downloaded again.
    before = len(setup["downloads"].requests)
    service = service_of(setup)
    job = asyncio.run(install(service, RER))
    assert job["status"] == "succeeded" and setup["downloads"].requests[before:] == [builtin_catalog.get(RER).url]


@pytest.mark.parametrize("wrong", ["sha"])
def test_a_model_file_of_another_size_or_digest_fails_and_leaves_nothing(setup, wrong):
    model = builtin_catalog.get(RER_LARGE)
    body = setup["bodies"][RER_LARGE]
    setup["downloads"].override[model.url] = body + b"x" if wrong == "size" else bytes(reversed(body))
    service = service_of(setup)
    job = asyncio.run(install(service, RER_LARGE))
    assert job["status"] == "failed" and "[could_not_run]" in job["output"]
    assert not setup["paths"].model_file(model).exists() and list(setup["paths"].root.rglob("*.part")) == []
    assert service.state(RER_LARGE) == "failed" and not service.models.available(RER_LARGE)


def link(name, target, kind=tarfile.SYMTYPE):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, target
    return info


@pytest.mark.parametrize("entries", [
    [("../llama-server", b"x", 0o755)],
    [("llama/llama-server", b"x", 0o755), link("llama/escape", "../../outside")],
], ids=["dotdot", "symlink_out"])
def test_an_unsafe_or_wrong_archive_is_refused_and_nothing_is_unpacked(setup, monkeypatch, entries):
    archive = tarball(entries)
    pin_tarball(monkeypatch, archive)
    setup["downloads"].archive = archive
    job = asyncio.run(install(service_of(setup), RER_LARGE))
    assert job["status"] == "failed", job
    root = setup["paths"].runtime.root
    assert not setup["paths"].runtime.installed() and not (root / llama_runtime.TAG).exists()
    assert [p.name for p in root.iterdir()] == [] and not (setup["tmp"] / "outside").exists()


def test_a_dead_install_is_marked_failed_at_start_and_its_parts_removed(setup):
    paths = setup["paths"]
    paths.root.mkdir(parents=True)
    paths.job_file.write_text(json.dumps({"status": "running", "model": RER_LARGE, "output": "SYNTHETIC"}))
    paths.model_dir(RER_LARGE).mkdir(parents=True)
    (paths.model_dir(RER_LARGE) / "f.part").write_bytes(b"x")
    service = service_of(setup)
    asyncio.run(service.start())
    assert service.read_job()["status"] == "failed" and "stopped when DEIXIS closed" in service.read_job()["output"]
    assert not (paths.model_dir(RER_LARGE) / "f.part").exists()


def test_check_files_finds_a_changed_byte(setup):
    paths = setup["paths"]
    install_runtime(paths)
    install_model(paths, RER_LARGE)
    service = service_of(setup)
    assert service.state(RER_LARGE) == "ready"
    target = paths.model_file(builtin_catalog.get(RER_LARGE))
    data = bytearray(target.read_bytes())
    data[0] ^= 1
    st = os.stat(target)
    target.write_bytes(bytes(data))
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))  # same size and time: only a full check sees it
    status = asyncio.run(service.check(RER_LARGE))
    card = next(m for m in status["models"] if m["id"] == RER_LARGE)
    assert (card["state"], card["last_full_check"]["passed"]) == ("files_do_not_match", False)


def client_of(setup, tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={}, start_worker=False,
                     http_client=httpx.AsyncClient(transport=setup["downloads"].transport()),
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client



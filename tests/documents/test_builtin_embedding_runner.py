"""The built-in embedding model's files and process (slice 21, D103, tasks 1 and 2).

Model files are small SYNTHETIC stand-ins with a manifest built from them; downloads go through httpx.MockTransport and
the process is `fake_embedding_runner.py` run with this interpreter, except where the real runner's file check is
tested (it stops before it would import torch). Passing shows the plumbing and its checks, not the models' quality.
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys

import httpx
import pytest

from deixis.documents import local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError
from builtin_helpers import fake_embedder, fake_manifest, install_fake


EMBEDDING_TOKENIZER, EMBEDDING_WEIGHTS = "embedding/tokenizer.json", "embedding/model.safetensors"


def manifest_name(url):
    """The manifest name a request asks for: from its pinned repository and revision, or from the redirect's path."""
    if url.host == "cdn.example.test":
        return url.path.split("/blobs/", 1)[1]
    for part, (repository, revision) in local_embedding.SOURCES.items():
        prefix = f"/{repository}/resolve/{revision}/"
        if url.path.startswith(prefix):
            return f"{part}/{url.path[len(prefix):]}"
    raise AssertionError(f"not a pinned revision: {url}")


def served(bodies, redirect=False, seen=None, broken=None, slow=None):
    """A MockTransport for the pinned revisions' files; optionally a redirect first, one broken body, or a slow one."""
    def handler(request):
        if seen is not None:
            seen.append(str(request.url))
        name = manifest_name(request.url)
        if redirect and request.url.host == "huggingface.co":
            return httpx.Response(302, headers={"location": f"https://cdn.example.test/blobs/{name}"})
        body = bodies[name]
        if broken == name:
            body = bytes([body[0] ^ 1]) + body[1:]
        if slow == name:
            async def stream():
                yield body[:5]
                await asyncio.sleep(30)
                yield body[5:]
            return httpx.Response(200, content=stream())
        return httpx.Response(200, content=body)
    return httpx.MockTransport(handler)


def download(models, transport, progress=None):
    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            await local_embedding.download_model(client, models, progress)
    asyncio.run(go())


# ---- task 1: the files ---------------------------------------------------------------------------

def test_the_model_files_download_through_a_redirect_into_place_with_their_digests(tmp_path, monkeypatch):
    bodies = fake_manifest(monkeypatch)
    models, seen, progress = tmp_path / "data" / "tools" / "models", [], []
    download(models, served(bodies, redirect=True, seen=seen), lambda done, total: progress.append((done, total)))
    assert sorted(p.relative_to(models).as_posix() for p in models.rglob("*") if p.is_file()) == sorted(bodies)
    # Each file came from its own model's repository at its pinned revision.
    assert any(f"/{local_embedding.RERANKER_REPOSITORY}/resolve/{local_embedding.RERANKER_REVISION}/" in url for url in seen)
    assert all((models / name).read_bytes() == body for name, body in bodies.items())
    assert any(url.startswith("https://cdn.example.test/") for url in seen)  # the redirect was followed
    assert progress[-1] == (sum(map(len, bodies.values())), sum(map(len, bodies.values())))
    # Nothing was written anywhere else under the test's folder.
    assert {p.relative_to(tmp_path / "data" / "tools" / "models").as_posix() for p in tmp_path.rglob("*") if p.is_file()} == set(bodies)


def test_a_file_one_byte_off_is_deleted_with_its_part_and_the_download_fails(tmp_path, monkeypatch):
    bodies = fake_manifest(monkeypatch)
    models = tmp_path / "models"
    with pytest.raises(local_embedding.DownloadError, match="tokenizer.json"):
        download(models, served(bodies, broken=EMBEDDING_TOKENIZER))
    assert not (models / EMBEDDING_TOKENIZER).exists() and not list(models.rglob("*.part"))


def test_a_file_already_in_place_with_its_digest_is_not_asked_for_again(tmp_path, monkeypatch):
    bodies = fake_manifest(monkeypatch)
    models, seen = tmp_path / "models", []
    (models / "embedding").mkdir(parents=True)
    (models / EMBEDDING_WEIGHTS).write_bytes(bodies[EMBEDDING_WEIGHTS])
    download(models, served(bodies, seen=seen))
    assert not any(manifest_name(httpx.URL(url)) == EMBEDDING_WEIGHTS for url in seen) and len(seen) == len(bodies) - 1


def test_a_cancelled_download_leaves_no_part(tmp_path, monkeypatch):
    bodies = fake_manifest(monkeypatch)
    models = tmp_path / "models"

    async def go():
        async with httpx.AsyncClient(transport=served(bodies, slow=EMBEDDING_WEIGHTS)) as client:
            task = asyncio.create_task(local_embedding.download_model(client, models))
            while not (models / f"{EMBEDDING_WEIGHTS}.part").exists():
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(go())
    assert not list(models.rglob("*.part")) and not (models / EMBEDDING_WEIGHTS).exists()


@pytest.mark.parametrize("damage", ["missing", "one_byte"])
def test_a_missing_or_changed_tokenizer_makes_options_status_and_the_runner_agree(tmp_path, monkeypatch, damage):
    """Only tokenizer.json is wrong: the options, the status endpoint and the runner's ready all say unusable."""
    from fastapi.testclient import TestClient

    from deixis.api.app import create_app
    from deixis.config import Settings

    bodies = fake_manifest(monkeypatch)
    paths = local_embedding.builtin_paths(tmp_path / "data")
    install_fake(paths)
    tokenizer = paths.models / EMBEDDING_TOKENIZER
    if damage == "missing":
        tokenizer.unlink()
    else:
        tokenizer.write_bytes(bytes([bodies[EMBEDDING_TOKENIZER][0] ^ 1]) + bodies[EMBEDDING_TOKENIZER][1:])
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={}, start_worker=False,
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                     extra_hosts=("testserver",), trusted_clients=("testclient",), local_embedder=fake_embedder(paths))
    with TestClient(app) as client:
        option = next(o for o in client.get("/api/semantic-search").json()["options"] if o["provider"] == "builtin")
        status = client.get("/api/semantic-search/builtin").json()
    assert (option["available"], option["reason_code"]) == (False, "files_do_not_match")
    assert (status["status"], status["available"]) == ("files_do_not_match", False)
    # The real runner checks every file before it would import torch.
    reply = subprocess.run([sys.executable, str(local_embedding.RUNNER), *local_embedding.runner_argv(paths)[2:]],
                           capture_output=True, text=True, timeout=60, env=paths.runner_env())
    assert json.loads(reply.stdout.splitlines()[0]) == {"ready": False, "code": "files_do_not_match",
                                                        "error": f"files do not match: {EMBEDDING_TOKENIZER}"}


def test_a_stale_part_and_a_half_built_environment_are_removed_when_the_service_starts(tmp_path, monkeypatch):
    from deixis.workflow.local_embedding_service import EmbeddingService

    fake_manifest(monkeypatch)
    paths = local_embedding.builtin_paths(tmp_path / "data")
    install_fake(paths)
    paths.installed_marker.unlink()  # an install that never finished
    (paths.models / f"{EMBEDDING_WEIGHTS}.part").write_bytes(b"SYNTHETIC half")
    service = EmbeddingService(paths, fake_embedder(paths))
    asyncio.run(service.start())
    assert not paths.env.exists() and not list(paths.models.rglob("*.part"))
    assert not paths.installed() and service.option()["reason_code"] == "not_installed"


# ---- task 2: the runner process -------------------------------------------------------------------

def installed(tmp_path, monkeypatch, mode="ok", **kwargs):
    fake_manifest(monkeypatch)
    monkeypatch.setenv("FAKE_RUNNER", mode)
    paths = local_embedding.builtin_paths(tmp_path / "data")
    install_fake(paths)
    return paths, fake_embedder(paths, **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_the_runner_says_ready_and_keeps_order_and_dimensions(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch)

    async def go():
        try:
            documents = await embedder.embed(["SYNTHETIC packet energy", "SYNTHETIC bakery bread", "SYNTHETIC packet"], "document")
            (query,) = await embedder.embed(["packet energy"], "query")
            return documents, query, embedder.ready_info
        finally:
            await embedder.close()
    documents, query, ready = run(go())
    assert ready == {"ready": True, "torch": "fake", "transformers": "fake", "device": local_embedding.DEVICE,
                     "dimensions": 1024}
    assert [len(v) for v in documents] == [1024, 1024, 1024]
    scores = [sum(a * b for a, b in zip(query, d)) for d in documents]
    assert scores[0] > scores[2] > scores[1]  # input order kept: the bakery text shares no word with the query
    assert embedder.integrity.last_full_check()["passed"] is True


def test_an_idle_runner_stops_and_the_next_request_starts_it_again(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch, idle_seconds=0.2)

    async def go():
        await embedder.embed(["SYNTHETIC one"], "document")
        first = embedder.process.pid
        await asyncio.sleep(0.8)
        stopped = embedder.process is None
        await embedder.embed(["SYNTHETIC two"], "document")
        second = embedder.process.pid
        await embedder.close()
        return first, stopped, second
    first, stopped, second = run(go())
    assert stopped and first != second


def test_a_runner_that_dies_mid_request_is_builtin_stopped_and_started_again_at_the_next_request(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch, mode="die_after:1")

    async def go():
        await embedder.embed(["SYNTHETIC one"], "document")
        first = embedder.process.pid
        with pytest.raises(LocalEmbeddingError) as info:
            await embedder.embed(["SYNTHETIC two"], "document")  # the process exits on this request
        stopped = embedder.process is None
        vectors = await embedder.embed(["SYNTHETIC three"], "document")  # started again, once, and answers
        second = embedder.process.pid
        await embedder.close()
        return info.value.code, stopped, vectors, first != second
    code, stopped, vectors, restarted = run(go())
    assert code == "builtin_stopped" and stopped and len(vectors) == 1 and restarted


def test_a_runner_that_died_between_requests_is_started_again(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch, mode="crash_after:1")

    async def go():
        await embedder.embed(["SYNTHETIC one"], "document")  # answered, then the process exits
        await embedder.process.wait()
        vectors = await embedder.embed(["SYNTHETIC two"], "document")
        await embedder.close()
        return vectors
    assert len(run(go())) == 1


def test_a_runner_that_does_not_answer_times_out_and_is_killed(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch, mode="hang")
    monkeypatch.setattr(local_embedding, "SECONDS_PER_BATCH_LIMIT", 0.5)

    async def go():
        await embedder.start()
        process = embedder.process
        with pytest.raises(LocalEmbeddingError) as info:
            await embedder.embed(["SYNTHETIC one"], "document")
        return info.value.code, process.returncode, embedder.process
    code, returncode, process = run(go())
    assert code == "builtin_timeout" and returncode is not None and process is None


def test_a_model_file_that_does_not_match_stops_the_runner_before_ready(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch)
    (paths.models / "reranker" / "config.json").write_bytes(b"SYNTHETIC changed")

    async def go():
        with pytest.raises(LocalEmbeddingError) as info:
            await embedder.embed(["SYNTHETIC one"], "document")
        return info.value
    error = run(go())
    assert error.code == "builtin_unavailable" and "reranker/config.json" in str(error)
    assert embedder.integrity.last_full_check()["passed"] is False and not embedder.integrity.available()


@pytest.mark.parametrize("mode", ["bad_id", "missing_vector", "dim383", "nan", "no_truncated"])
def test_a_reply_that_is_not_what_was_asked_is_refused_and_the_runner_closed(tmp_path, monkeypatch, mode):
    paths, embedder = installed(tmp_path, monkeypatch, mode=mode)

    async def go():
        await embedder.start()
        process = embedder.process
        with pytest.raises(LocalEmbeddingError) as info:
            await embedder.embed(["SYNTHETIC one", "SYNTHETIC two"], "document")
        await asyncio.sleep(0)
        return info.value.code, process.returncode, embedder.process
    code, returncode, process = run(go())
    assert code == "builtin_bad_reply" and returncode is not None and process is None


def test_the_deixis_process_never_imports_torch_transformers_or_numpy(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch)

    async def go():
        await embedder.embed(["SYNTHETIC one"], "document")
        await embedder.close()
    run(go())
    import deixis.api.app  # noqa: F401 - the whole app is imported
    import deixis.workflow.local_embedding_service  # noqa: F401
    assert not {"torch", "transformers", "numpy", "fastembed", "onnxruntime"} & set(sys.modules)


def test_a_request_while_removing_or_on_another_platform_starts_nothing_and_opens_no_lock(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch)
    embedder.removing = True
    with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
        run(embedder.embed(["SYNTHETIC one"], "document"))
    embedder.removing = False
    monkeypatch.setattr(os, "name", "nt")
    with pytest.raises(LocalEmbeddingError, match="builtin_unavailable"):
        run(embedder.embed(["SYNTHETIC one"], "document"))
    assert embedder.process is None and not paths.in_use_lock.exists()


def test_the_manifest_pins_the_official_qwen3_revisions():
    """Both models come from Qwen's own repositories at fixed revisions; the weights carry the sha256 the Hugging Face
    API lists for them (17 Oct 2026). Every model file is named under its model's folder."""
    by_name = {f.name: f for f in local_embedding.MODEL_FILES}
    assert local_embedding.SOURCES == {
        "embedding": ("Qwen/Qwen3-Embedding-0.6B", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"),
        "reranker": ("Qwen/Qwen3-Reranker-0.6B", "e61197ed45024b0ed8a2d74b80b4d909f1255473")}
    assert by_name["embedding/model.safetensors"].size == 1_191_586_416
    assert by_name["embedding/model.safetensors"].sha256 == "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd"
    assert by_name["reranker/model.safetensors"].sha256 == "27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b"
    assert {name.split("/", 1)[0] for name in by_name} == {"embedding", "reranker"}
    assert local_embedding.MODEL_DISK_BYTES == local_embedding.model_bytes() > 2_400_000_000
    assert local_embedding.model_url("reranker/1_LogitScore/config.json") == (
        "https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/resolve/e61197ed45024b0ed8a2d74b80b4d909f1255473/1_LogitScore/config.json")
    assert hashlib.sha256(b"").hexdigest() not in {f.sha256 for f in local_embedding.MODEL_FILES}


def test_the_model_identity_names_revision_token_limit_device_and_instruction():
    """A changed cut, device or instruction is another model's vectors: each is in the stored identity."""
    model = local_embedding.MODEL_ID
    assert model.startswith("qwen3-embedding-0.6b@97b0c61:512:")
    assert f":{local_embedding.DEVICE}:" in model and model.endswith(
        ":i" + hashlib.sha256(local_embedding.EMBEDDING_INSTRUCTION.encode()).hexdigest()[:8])
    assert local_embedding.RERANKER_ID.startswith("qwen3-reranker-0.6b@e61197e:1024:")
    assert model not in local_embedding.EARLIER_MODEL_IDS


def test_the_runner_imports_only_the_standard_library_torch_and_transformers():
    """The runner's contract: torch and transformers inside the built-in environment, nothing else from outside it."""
    import ast

    tree = ast.parse(local_embedding.RUNNER.read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported - set(sys.stdlib_module_names) == {"torch", "transformers"}


def test_the_runner_writes_the_qwen3_query_and_reranker_formats():
    """The model cards' formats, read from the runner's source: the instruction goes on queries only, and the
    reranker's system prompt and suffix are the card's own."""
    source = local_embedding.RUNNER.read_text()
    assert 'f"Instruct: {self.args.instruction}\\nQuery:{text}"' in source
    assert "<|im_start|>system\\nJudge whether the Document meets the requirements based on the Query and the" in source
    assert 'RERANK_SUFFIX = "<|im_end|>\\n<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n"' in source
    assert 'padding_side="left"' in source


def test_a_text_over_the_token_limit_is_reported_cut_never_silently(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch)
    long = " ".join(["SYNTHETIC"] * (local_embedding.LOCAL_MAX_TOKENS + 1))

    async def go():
        report = {}
        try:
            await embedder.embed(["SYNTHETIC short", long, long], "document", report)
        finally:
            await embedder.close()
        return report
    assert run(go()) == {"truncated_texts": 2}


def test_a_rerank_returns_scores_in_input_order(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch)

    async def go():
        try:
            return await embedder.rerank("packet energy", ["SYNTHETIC bakery", "SYNTHETIC packet energy", "SYNTHETIC packet"], 30)
        finally:
            await embedder.close()
    scores, cut = run(go())
    assert scores == [0.0, 1.0, 0.5] and cut == []


@pytest.mark.parametrize("mode", ["bad_score", "missing_vector", "bad_id", "no_truncated"])
def test_a_rerank_reply_that_is_not_what_was_asked_is_refused_and_the_runner_closed(tmp_path, monkeypatch, mode):
    paths, embedder = installed(tmp_path, monkeypatch, mode=mode)

    async def go():
        await embedder.start()
        process = embedder.process
        with pytest.raises(LocalEmbeddingError) as info:
            await embedder.rerank("packet", ["SYNTHETIC a", "SYNTHETIC packet"], 30)
        return info.value.code, process.returncode, embedder.process
    code, returncode, process = run(go())
    assert code == "builtin_bad_reply" and returncode is not None and process is None


def test_a_cancelled_rerank_kills_the_runner_so_no_reply_is_left_unread(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch, mode="slow:5")

    async def go():
        await embedder.start()
        process = embedder.process
        task = asyncio.create_task(embedder.rerank("packet", ["SYNTHETIC packet"], 30))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return process.returncode, embedder.process
    returncode, process = run(go())
    assert returncode is not None and process is None


def test_a_rerank_that_outlives_its_time_limit_times_out_and_kills_the_runner(tmp_path, monkeypatch):
    paths, embedder = installed(tmp_path, monkeypatch, mode="hang")

    async def go():
        await embedder.start()
        process = embedder.process
        with pytest.raises(LocalEmbeddingError) as info:
            await embedder.rerank("packet", ["SYNTHETIC packet"], 0.5)
        return info.value.code, process.returncode
    code, returncode = run(go())
    assert code == "builtin_timeout" and returncode is not None

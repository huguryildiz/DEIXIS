"""Pinned reranker catalog and the local llama.cpp server using synthetic model files."""

import asyncio
import re
import pytest
from deixis.documents import builtin_catalog, rerankers
from deixis.documents.builtin_catalog import CATALOG, recommended
import json
import os
import time
from deixis.documents import builtin_catalog, local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError, LocalModels
from builtin_helpers import install_model, ready


def test_every_catalog_entry_pins_a_revision_a_file_a_size_and_a_digest():
    assert [m.id for m in CATALOG] == ["qwen3-reranker-0.6b", "qwen3-reranker-4b", "qwen3-reranker-8b",
                                       "bge-reranker-v2-m3"]
    for model in CATALOG:
        assert re.fullmatch(r"[0-9a-f]{40}", model.revision) and re.fullmatch(r"[0-9a-f]{64}", model.sha256)
        assert model.file.endswith(".gguf") and model.bytes > 500_000_000
        assert model.url == f"https://huggingface.co/{model.repo}/resolve/{model.revision}/{model.file}"
        assert model.memory_gb * 1e9 > model.bytes  # file plus an estimated cache, never less than the file
    by_id = {m.id: m for m in CATALOG}
    assert [by_id[i].repo.split("/")[0] for i in ("qwen3-reranker-0.6b", "qwen3-reranker-4b", "qwen3-reranker-8b",
                                                  "bge-reranker-v2-m3")] == ["ggml-org", "Voodisss", "Voodisss", "gpustack"]


@pytest.mark.parametrize("memory,reranker", [(None, "qwen3-reranker-0.6b")])
def test_the_recommendation_is_the_largest_qwen3_reranker_within_a_quarter_of_memory(memory, reranker):
    assert recommended(memory) == {"reranker": reranker}


def test_a_saved_choice_is_kept_as_saved_and_never_remapped(monkeypatch):
    assert rerankers.chosen({"enabled": True, "provider": "builtin", "model": "qwen3-reranker-4b"}).model == "qwen3-reranker-4b"
    assert rerankers.chosen({"enabled": True, "provider": "builtin"}).model == builtin_catalog.NO_MODEL


RER = "qwen3-reranker-0.6b"


pytestmark = pytest.mark.skipif(os.name != "posix", reason="the built-in models are POSIX only in this slice")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    paths = local_embedding.builtin_paths(tmp_path / "data")
    ready(paths, monkeypatch, RER)
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_LLAMA_RECORD", str(record))
    monkeypatch.setenv("FAKE_LLAMA_STATE", str(tmp_path / "state"))

    def lines():
        return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()] if record.exists() else []
    return paths, lines


def run(coro):
    return asyncio.run(coro)


async def using(models, coro):
    try:
        return await coro
    finally:
        await models.close()


def gone(pid, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False




def test_a_wrong_reply_is_refused_and_the_server_is_killed(setup, monkeypatch):
    paths, lines = setup
    monkeypatch.setenv("FAKE_LLAMA", "wrong_count")
    models = LocalModels(paths)
    call = models.rerank(RER, "alpha", ["alpha", "beta"], 30)
    with pytest.raises(LocalEmbeddingError) as error:
        run(using(models, call))
    assert error.value.code == "builtin_bad_reply"
    pid = [line for line in lines() if "argv" in line][0]["pid"]
    assert gone(pid) and models.servers == {}


def test_a_server_that_does_not_know_the_key_fails_the_probe(setup, monkeypatch):
    paths, _ = setup
    monkeypatch.setenv("FAKE_LLAMA", "reject_key")
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError, match="HTTP 401"):
        run(using(models, models.rerank(RER, "alpha", ["alpha"], 30)))


def test_a_changed_model_file_or_server_binary_keeps_the_server_from_starting(setup):
    paths, lines = setup
    models = LocalModels(paths)
    install_model(paths, RER, body=b"SYNTHETIC changed " * 3, check=False)
    assert not models.available(RER)
    with pytest.raises(LocalEmbeddingError, match="does not match its last check"):
        run(using(models, models.rerank(RER, "alpha", ["alpha"], 30)))
    install_model(paths, RER)
    server = paths.runtime.server()
    server.write_bytes(server.read_bytes() + b"\n# changed\n")
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError, match="server binary does not match"):
        run(using(models, models.rerank(RER, "a", ["a"], 30)))
    assert lines() == []



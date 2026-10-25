"""The built-in models (llama.cpp): the pinned catalog and its identities, and the server DEIXIS starts on 127.0.0.1 with its own key. The server is fake_llama_server.py run through the production watcher; model files are SYNTHETIC bytes. Passing shows how DEIXIS starts, checks and stops the server, not how a real model embeds or ranks."""

import asyncio
import re
import pytest
from deixis.documents import builtin_catalog, embeddings, rerankers
from deixis.documents.builtin_catalog import CATALOG, identity, recommended, resolve
import json
import os
import time
from deixis.documents import builtin_catalog, local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError, LocalModels
from builtin_helpers import install_model, ready


D88 = "qwen3-embedding-0.6b@97b0c61:512:mps:i1a2b3c4d"


def test_every_catalog_entry_pins_a_revision_a_file_a_size_and_a_digest():
    assert [m.id for m in CATALOG] == ["qwen3-embedding-0.6b", "qwen3-embedding-4b", "qwen3-embedding-8b", "bge-m3",
                                       "qwen3-reranker-0.6b", "qwen3-reranker-4b", "qwen3-reranker-8b",
                                       "bge-reranker-v2-m3"]
    for model in CATALOG:
        assert re.fullmatch(r"[0-9a-f]{40}", model.revision) and re.fullmatch(r"[0-9a-f]{64}", model.sha256)
        assert model.file.endswith(".gguf") and model.bytes > 500_000_000
        assert model.url == f"https://huggingface.co/{model.repo}/resolve/{model.revision}/{model.file}"
        assert model.memory_gb * 1e9 > model.bytes  # file plus an estimated cache, never less than the file
    by_id = {m.id: m for m in CATALOG}
    assert (by_id["qwen3-embedding-0.6b"].bytes, by_id["qwen3-embedding-0.6b"].sha256[:8]) == (639_150_592, "06507c7b")
    assert by_id["qwen3-embedding-8b"].file.endswith("Q4_K_M.gguf")  # Q8_0 avoided: null vectors on Metal (#29216)
    assert [by_id[i].repo.split("/")[0] for i in ("qwen3-reranker-0.6b", "qwen3-reranker-4b", "qwen3-reranker-8b",
                                                  "bge-reranker-v2-m3")] == ["ggml-org", "Voodisss", "Voodisss", "gpustack"]
    assert {m.id: m.dimensions for m in CATALOG if m.kind == "embedding"} == {
        "qwen3-embedding-0.6b": 1024, "qwen3-embedding-4b": 2560, "qwen3-embedding-8b": 4096, "bge-m3": 1024}
    assert (by_id["bge-m3"].pooling, by_id["bge-m3"].query_instruction, by_id["bge-m3"].english_query_required) == ("cls", None, False)
    assert all(m.english_query_required and m.pooling == "last" for m in CATALOG if m.id.startswith("qwen3-embedding"))


@pytest.mark.parametrize("memory,embedding,reranker", [
    (None, "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"),
])
def test_the_recommendation_is_the_largest_qwen3_model_within_a_quarter_of_memory(memory, embedding, reranker):
    assert recommended(memory) == {"embedding": embedding, "reranker": reranker}


class Recorder:
    def __init__(self):
        self.calls = []

    async def embed(self, model_id, texts, kind, report=None):
        self.calls.append(model_id)
        raise AssertionError("an earlier identity must never reach a server")


@pytest.mark.parametrize("stored", [f"builtin:{D88}"])
def test_an_unresolvable_built_in_identity_fails_closed_and_is_never_routed_to_another_model(stored):
    local = Recorder()
    old = embeddings.Embedder.from_identity("builtin", stored, local)
    with pytest.raises(embeddings.EmbeddingError, match="builtin_model_changed"):
        asyncio.run(old.embed(None, ["text"], "RETRIEVAL_DOCUMENT"))
    assert local.calls == []


def test_a_saved_choice_is_kept_as_saved_and_never_remapped(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert embeddings.chosen({"provider": "builtin", "model": "bge-m3"}) == ("builtin", "bge-m3")
    assert embeddings.chosen({"provider": "builtin", "model": D88}) == ("builtin", D88)
    assert embeddings.chosen({"provider": "builtin", "model": None}) == ("builtin", builtin_catalog.NO_MODEL)
    assert rerankers.chosen({"enabled": True, "provider": "builtin", "model": "qwen3-reranker-4b"}).model == "qwen3-reranker-4b"
    assert rerankers.chosen({"enabled": True, "provider": "builtin"}).model == builtin_catalog.NO_MODEL
    # With nothing saved and no key: the first built-in model in catalog order that is ready (D7), else off.
    monkeypatch.setattr(embeddings.local_embedding, "model_available", lambda model_id: model_id in ("bge-m3", "qwen3-embedding-4b"))
    assert embeddings.chosen(None) == ("builtin", "qwen3-embedding-4b")
    monkeypatch.setattr(embeddings.local_embedding, "model_available", lambda model_id: False)
    assert embeddings.chosen(None) == ("off", None)


EMB, RER = "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"


pytestmark = pytest.mark.skipif(os.name != "posix", reason="the built-in models are POSIX only in this slice")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    paths = local_embedding.builtin_paths(tmp_path / "data")
    ready(paths, monkeypatch, EMB, RER, "bge-m3")
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_LLAMA_RECORD", str(record))
    monkeypatch.setenv("FAKE_LLAMA_STATE", str(tmp_path / "state"))

    def lines():
        return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
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


def test_embeddings_come_back_in_input_order_with_the_query_instruction_and_the_pinned_command_line(setup):
    paths, lines = setup
    models = LocalModels(paths)
    texts = ["alpha beta", "gamma delta", "alpha beta"]
    vectors = run(using(models, models.embed(EMB, texts, "document")))
    assert len(vectors) == 3 and all(len(v) == 1024 for v in vectors)
    assert list(vectors[0]) == list(vectors[2]) and list(vectors[0]) != list(vectors[1])  # mapped by index, not position
    starts = [line for line in lines() if "argv" in line]
    argv = starts[0]["argv"]
    for flag, value in (("--host", "127.0.0.1"), ("-c", "8192"), ("-ub", "8192"), ("-b", "8192"), ("-np", "1"),
                        ("-ngl", "99"), ("--pooling", "last")):
        assert argv[argv.index(flag) + 1] == value
    assert "--embedding" in argv and "--rerank" not in argv and "--port" in argv and len(argv[argv.index("--api-key") + 1]) == 48
    requests = [line for line in lines() if line.get("path") == "/v1/embeddings"]
    probe, call = requests
    assert probe["body"]["input"][0].startswith("Instruct: " + builtin_catalog.EMBEDDING_INSTRUCTION + "\nQuery:")
    assert call["body"]["input"] == texts  # documents carry no instruction


@pytest.mark.parametrize("mode,kind", [("wrong_dim", "embed")])
def test_a_wrong_reply_is_refused_and_the_server_is_killed(setup, monkeypatch, mode, kind):
    paths, lines = setup
    monkeypatch.setenv("FAKE_LLAMA", mode)
    models = LocalModels(paths)
    call = (models.embed(EMB, ["alpha beta", "gamma"], "document") if kind == "embed"
            else models.rerank(RER, "alpha", ["alpha", "beta"], 30))
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
        run(using(models, models.embed(EMB, ["alpha"], "document")))


def test_a_changed_model_file_or_server_binary_keeps_the_server_from_starting(setup):
    paths, lines = setup
    models = LocalModels(paths)
    install_model(paths, EMB, body=b"SYNTHETIC changed " * 3, check=False)
    assert not models.available(EMB)
    with pytest.raises(LocalEmbeddingError, match="does not match its last check"):
        run(using(models, models.embed(EMB, ["alpha"], "document")))
    server = paths.runtime.server()
    server.write_bytes(server.read_bytes() + b"\n# changed\n")
    models = LocalModels(paths)
    with pytest.raises(LocalEmbeddingError, match="server binary does not match"):
        run(using(models, models.rerank(RER, "a", ["a"], 30)))
    assert lines() == []



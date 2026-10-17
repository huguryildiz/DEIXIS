"""The built-in catalog's pins, the recommendation rule, the identities and the saved choices (model-free).

Passing shows what DEIXIS pins and how it files and resolves vectors and choices, not that a pin is still served online
or that a model fits a given computer: memory figures are estimates.
"""

import asyncio
import re

import pytest

from deixis.documents import builtin_catalog, embeddings, llama_runtime, rerankers
from deixis.documents.builtin_catalog import CATALOG, identity, recommended, resolve

D88 = "qwen3-embedding-0.6b@97b0c61:512:mps:i1a2b3c4d"
BGE_SMALL = "bge-small-en-v1.5@aa8f8b0:256"


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


def test_the_runtime_pins_one_build_per_platform_with_its_digest():
    assert llama_runtime.TAG == "b11711"
    arm = llama_runtime.ASSETS[("darwin", "arm64")]
    assert (arm.name, arm.bytes, arm.sha256[:12]) == ("llama-b11711-bin-macos-arm64.tar.gz", 12_251_264, "dc1f09829c2f")
    assert arm.url == "https://github.com/ggml-org/llama.cpp/releases/download/b11711/llama-b11711-bin-macos-arm64.tar.gz"
    assert set(llama_runtime.ASSETS) == {("darwin", "arm64"), ("darwin", "x86_64"), ("linux", "x86_64")}


@pytest.mark.parametrize("memory,embedding,reranker", [
    (None, "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"),
    (8, "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"),
    (16, "qwen3-embedding-0.6b", "qwen3-reranker-0.6b"),
    (18, "qwen3-embedding-4b", "qwen3-reranker-0.6b"),
    (32, "qwen3-embedding-8b", "qwen3-reranker-4b"),
    (64, "qwen3-embedding-8b", "qwen3-reranker-8b"),
])
def test_the_recommendation_is_the_largest_qwen3_model_within_a_quarter_of_memory(memory, embedding, reranker):
    assert recommended(memory) == {"embedding": embedding, "reranker": reranker}


def test_an_identity_names_file_context_cut_pooling_instruction_preprocessing_and_runtime_numerics():
    emb = builtin_catalog.get("qwen3-embedding-0.6b")
    found = identity(emb)
    assert found == (f"qwen3-embedding-0.6b@06507c7b:ctx8192:cutcut:poollast:i{builtin_catalog.short(builtin_catalog.EMBEDDING_INSTRUCTION)}"
                     f":pre{builtin_catalog.PREPROCESS_VERSION}:rt{builtin_catalog.RUNTIME_NUMERICS}")
    assert identity(builtin_catalog.get("bge-m3")).startswith("bge-m3@aa473d51:ctx8192:cutcut:poolcls:inone:")
    assert identity(builtin_catalog.get("qwen3-reranker-0.6b")).startswith("builtin-rerank:qwen3-reranker-0.6b@22c9979c:ctx8192:cutcut:tplnone:")
    assert resolve(found, "embedding") is emb and resolve(found + ":threads=4", "embedding") is emb
    assert resolve("qwen3-embedding-0.6b", "embedding") is emb and resolve("qwen3-embedding-0.6b", "reranker") is None
    for earlier in (D88, BGE_SMALL, found.replace(":rt1", ":rt0"), builtin_catalog.NO_MODEL, None):
        assert resolve(earlier, "embedding") is None


def test_a_catalog_choice_is_stored_under_its_identity_and_a_stored_identity_round_trips():
    embedder = embeddings.Embedder("builtin", "qwen3-embedding-0.6b")
    stored = embedder.stored_model
    assert stored == "builtin:" + identity(builtin_catalog.get("qwen3-embedding-0.6b"))
    assert embeddings.Embedder("builtin", "qwen3-embedding-0.6b:threads=4").stored_model == stored + ":threads=4"
    again = embeddings.Embedder.from_identity("builtin", stored + ":threads=4")
    assert again.stored_model == stored + ":threads=4"
    # A D88 identity keeps its own name: never relabelled as a catalog model's.
    assert embeddings.Embedder.from_identity("builtin", f"builtin:{D88}").stored_model == f"builtin:{D88}"


class Recorder:
    def __init__(self):
        self.calls = []

    async def embed(self, model_id, texts, kind, report=None):
        self.calls.append(model_id)
        raise AssertionError("an earlier identity must never reach a server")


@pytest.mark.parametrize("stored", [f"builtin:{D88}", f"builtin:{BGE_SMALL}:threads=4", "builtin:" + builtin_catalog.NO_MODEL])
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


def test_only_the_qwen3_models_need_an_english_query():
    assert embeddings.english_only(embeddings.Embedder("builtin", "qwen3-embedding-4b"))
    assert not embeddings.english_only(embeddings.Embedder("builtin", "bge-m3"))
    assert not embeddings.english_only(embeddings.Embedder("builtin", D88))  # fails at embed instead
    assert not embeddings.english_only(embeddings.Embedder("gemini", embeddings.MODEL))


def test_a_built_in_rerank_choice_records_its_identity_and_runtime_and_an_earlier_one_fails_closed():
    choice = rerankers.chosen({"enabled": True, "provider": "builtin", "model": "qwen3-reranker-0.6b"})
    found = choice.identity()
    assert found["model"] == "qwen3-reranker-0.6b" and found["model_identity"].startswith("builtin-rerank:qwen3-reranker-0.6b@")
    assert (found["runtime"], found["runtime_build"]) == ("llama.cpp", "b11711")

    class Never:
        async def rerank(self, *args):
            raise AssertionError("never asked")
    old = rerankers.chosen({"enabled": True, "provider": "builtin", "model": "qwen3-reranker-0.6b@e61197e:1024:mps:i1"})
    with pytest.raises(rerankers.RerankError, match="builtin_model_changed") as error:
        asyncio.run(rerankers.rerank(old, None, Never(), "q", ["d"]))
    assert error.value.code == "reranker_unavailable"

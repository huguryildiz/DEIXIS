"""The built-in local models: a pinned catalog of GGUF files that llama.cpp's `llama-server` runs on this computer.

Four embedding models and four rerankers, each downloaded, checked, removed and chosen on its own. Every entry pins its
Hugging Face repository, the revision commit, the file, its byte count and its sha256 (read from the Hugging Face API,
`/api/models/<repo>` and `/api/models/<repo>/tree/<sha>`, on 17 Oct 2026). Only the listed reranker conversions are
offered: other community conversions of the Qwen3 reranker give meaningless scores (llama.cpp issue #16407). The 8B
embedding model is the Q4_K_M file because the Q8_0 one can return null vectors on Metal (issue #29216).

`memory_gb` is an estimate, not a measurement: the file, plus the key-value cache for CTX tokens (layers x KV heads x
head size x 2 x 2 bytes x CTX for the Qwen3 models; for the bge models an attention buffer guess), plus about 0.5 GB of
buffers. The recommendation below reads it.

The identity of a vector or a score names everything that shapes it: the catalog id, the file's sha256, the context
size, what happens to a text over the input limit, the pooling, the query instruction, the preprocessing version and
RUNTIME_NUMERICS, a number raised whenever a llama.cpp update is known to change numerics. Vectors stored under one
identity are never compared with another's.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

RUNTIME_TAG = "b11711"  # the llama.cpp build `llama_runtime` pins; stored on each step as provenance
RUNTIME_NUMERICS = 1  # raised when a runtime update changes what a model returns for the same input
PREPROCESS_VERSION = 1  # raised when how DEIXIS prepares a text (instruction line, cut) changes
CTX = 8192  # tokens of context per server (one slot, `-np 1`), also the batch and micro-batch size
CUT_POLICY = "cut"  # a text over the input limit is cut at the token limit by DEIXIS and reported as cut
# The one-sentence task the Qwen3 embedding model card asks for, in English as it advises; only queries carry it.
EMBEDDING_INSTRUCTION = "Given a research question, retrieve titles, abstracts and passages of scholarly papers that answer it"
# Of this computer's memory, the share the recommended model may take (a starting value, not measured).
RECOMMEND_SHARE = 0.25
# A built-in choice saved without a model id (from before the catalog): never mapped to a catalog model.
NO_MODEL = "earlier-built-in-model"


def short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


@dataclass(frozen=True)
class Model:
    id: str
    kind: str  # "embedding" or "reranker"
    name: str
    maker: str
    params: str
    family: str  # "qwen3" or "bge"
    repo: str
    revision: str
    file: str
    bytes: int
    sha256: str
    license: str
    official: bool  # published by the model's own makers (Qwen, or ggml-org for BAAI's bge-m3)
    memory_gb: float  # an estimate, see the module docstring
    pooling: str  # "last", "cls" or "rank"
    multilingual: bool
    english_query_required: bool  # the query instruction is English: a non-English question needs an English sentence
    dimensions: int | None = None
    query_instruction: str | None = None

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.file}"

    def card(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name, "maker": self.maker, "params": self.params,
                "family": self.family, "file": self.file, "repo": self.repo, "revision": self.revision,
                "bytes": self.bytes, "sha256": self.sha256, "memory_gb": self.memory_gb, "memory_estimated": True,
                "official": self.official, "license": self.license, "multilingual": self.multilingual,
                "english_query_required": self.english_query_required, "dimensions": self.dimensions,
                "identity": identity(self)}


CATALOG: tuple[Model, ...] = (
    Model("qwen3-embedding-0.6b", "embedding", "Qwen3-Embedding-0.6B", "Qwen", "0.6B", "qwen3",
          "Qwen/Qwen3-Embedding-0.6B-GGUF", "370f27d7550e0def9b39c1f16d3fbaa13aa67728", "Qwen3-Embedding-0.6B-Q8_0.gguf",
          639_150_592, "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439", "Apache-2.0", True, 2.1,
          "last", True, True, 1024, EMBEDDING_INSTRUCTION),
    Model("qwen3-embedding-4b", "embedding", "Qwen3-Embedding-4B", "Qwen", "4B", "qwen3",
          "Qwen/Qwen3-Embedding-4B-GGUF", "f4602530db1d980e16da9d7d3a70294cf5c190be", "Qwen3-Embedding-4B-Q4_K_M.gguf",
          2_496_703_776, "2b0cf8f17b4c723c27303015383c27ec4bf2d8314bb677d05e920dd70bb0f16b", "Apache-2.0", True, 4.2,
          "last", True, True, 2560, EMBEDDING_INSTRUCTION),
    Model("qwen3-embedding-8b", "embedding", "Qwen3-Embedding-8B", "Qwen", "8B", "qwen3",
          "Qwen/Qwen3-Embedding-8B-GGUF", "69d0e58a13e463cd99a9b83e3f5fee7c10265fab", "Qwen3-Embedding-8B-Q4_K_M.gguf",
          4_676_804_928, "3fcd3febec8b3fd64435204db75bf0dd73b91e8d0661e0331acfe7e7c3120b85", "Apache-2.0", True, 6.4,
          "last", True, True, 4096, EMBEDDING_INSTRUCTION),
    Model("bge-m3", "embedding", "bge-m3", "BAAI (ggml-org conversion)", "0.6B", "bge",
          "ggml-org/bge-m3-Q8_0-GGUF", "9eba04c5d75ba5a1595e45de734d36bef4e5cb98", "bge-m3-q8_0.gguf",
          634_553_760, "aa473d51f451a22f0fcf39ba3330c14bed38a385712b1113440f69df4047a173", "MIT", True, 2.0,
          "cls", True, False, 1024, None),
    Model("qwen3-reranker-0.6b", "reranker", "Qwen3-Reranker-0.6B", "Qwen (ggml-org conversion)", "0.6B", "qwen3",
          "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF", "a02f48bb4f057028298c21fa033da2b30d7742d5",
          "qwen3-reranker-0.6b-q8_0.gguf", 639_153_184,
          "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48", "Apache-2.0", True, 2.1,
          "rank", True, False),
    Model("qwen3-reranker-4b", "reranker", "Qwen3-Reranker-4B", "Qwen (community conversion, Voodisss)", "4B", "qwen3",
          "Voodisss/Qwen3-Reranker-4B-GGUF-llama_cpp", "1b452c803342e73ac3644551b727dfd51a09fd5b",
          "Qwen3-Reranker-4B.Q8_0.gguf", 4_279_678_912,
          "102ac400d68f02877c2fdfecf0732872652298448352b6faf28ec7f8dca8c913", "Apache-2.0", False, 6.0,
          "rank", True, False),
    Model("qwen3-reranker-8b", "reranker", "Qwen3-Reranker-8B", "Qwen (community conversion, Voodisss)", "8B", "qwen3",
          "Voodisss/Qwen3-Reranker-8B-GGUF-llama_cpp", "646e3a1fc04936cab940ad02e18ee6b14af46263",
          "Qwen3-Reranker-8B.Q8_0.gguf", 8_047_134_304,
          "13815d68c755c6293161a9aebc986976af90b35a7c9ffd2e074e58d28ddfe4ae", "Apache-2.0", False, 9.8,
          "rank", True, False),
    Model("bge-reranker-v2-m3", "reranker", "bge-reranker-v2-m3", "BAAI (community conversion, gpustack)", "0.6B", "bge",
          "gpustack/bge-reranker-v2-m3-GGUF", "3093af03b1a635e67b084b1d8c03c5f5e020fd05", "bge-reranker-v2-m3-Q8_0.gguf",
          635_676_416, "a43c7c9b11a4c1517e5bf95151960e1621d1b72f7a493364b01e386cf1aaa1d3", "Apache-2.0", False, 2.0,
          "rank", True, False),
)
KINDS = ("embedding", "reranker")


def get(model_id: str | None) -> Model | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def of_kind(kind: str) -> list[Model]:
    return [m for m in CATALOG if m.kind == kind]


def identity(model: Model) -> str:
    """What a stored vector or score of this model is filed under (embedding: after `builtin:`)."""
    if model.kind == "embedding":
        instruction = short(model.query_instruction) if model.query_instruction else "none"
        return (f"{model.id}@{model.sha256[:8]}:ctx{CTX}:cut{CUT_POLICY}:pool{model.pooling}:i{instruction}"
                f":pre{PREPROCESS_VERSION}:rt{RUNTIME_NUMERICS}")
    # The reranker uses the template inside its GGUF file (pinned by the file's sha256); DEIXIS adds none.
    return f"builtin-rerank:{model.id}@{model.sha256[:8]}:ctx{CTX}:cut{CUT_POLICY}:tplnone:pre{PREPROCESS_VERSION}:rt{RUNTIME_NUMERICS}"


def split_threads(model: str) -> tuple[str, str | None]:
    """`<model>:threads=<n>` → (`<model>`, `<n>`); a model without the suffix → (model, None)."""
    if ":threads=" in model:
        base, threads = model.rsplit(":threads=", 1)
        return base, threads
    return model, None


def resolve(model: str | None, kind: str) -> Model | None:
    """The catalog model a saved choice or a stored identity names: a catalog id, or the exact current identity of
    one. Anything else (an earlier built-in model, an identity from another runtime or file) is None: it is never
    mapped to a catalog model."""
    if not model:
        return None
    base, _ = split_threads(model)
    for entry in of_kind(kind):
        if base == entry.id or base == identity(entry):
            return entry
    return None


def recommended(memory_gb: float | None) -> dict[str, str]:
    """Per kind, the largest Qwen3 model whose estimated memory is at most RECOMMEND_SHARE of this computer's memory;
    the 0.6B model when none fits or the memory is unknown. A starting rule, not measured; it never changes a choice."""
    picks: dict[str, str] = {}
    for kind in KINDS:
        family = [m for m in of_kind(kind) if m.family == "qwen3"]
        smallest = min(family, key=lambda m: m.memory_gb)
        fitting = [m for m in family if memory_gb and m.memory_gb <= memory_gb * RECOMMEND_SHARE]
        picks[kind] = max(fitting, key=lambda m: m.memory_gb).id if fitting else smallest.id
    return picks

"""The built-in local models: a pinned catalog of GGUF files that llama.cpp's `llama-server` runs on this computer.

Four rerankers, each downloaded, checked, removed and chosen on its own. Every entry pins its
Hugging Face repository, the revision commit, the file, its byte count and its sha256 (read from the Hugging Face API,
`/api/models/<repo>` and `/api/models/<repo>/tree/<sha>`, on 17 Oct 2026). Only the listed reranker conversions are
offered: other community conversions of the Qwen3 reranker give meaningless scores (llama.cpp issue #16407).

`memory_gb` is an estimate, not a measurement: the file, plus the key-value cache for CTX tokens (layers x KV heads x
head size x 2 x 2 bytes x CTX for the Qwen3 models; for the bge models an attention buffer guess), plus about 0.5 GB of
buffers. The recommendation below reads it.

The score identity names the catalog id, the file's sha256, the context size, the text cut policy, the preprocessing
version and RUNTIME_NUMERICS. Scores stored under different identities are not mixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RUNTIME_TAG = "b11711"  # the llama.cpp build `llama_runtime` pins; stored on each step as provenance
RUNTIME_NUMERICS = 1  # raised when a runtime update changes what a model returns for the same input
PREPROCESS_VERSION = 1  # raised when how DEIXIS prepares a text (instruction line, cut) changes
CTX = 8192  # tokens of context per server (one slot, `-np 1`), also the batch and micro-batch size
CUT_POLICY = "cut"  # a text over the input limit is cut at the token limit by DEIXIS and reported as cut
# Of this computer's memory, the share the recommended model may take (a starting value, not measured).
RECOMMEND_SHARE = 0.25
# A built-in choice saved without a model id (from before the catalog): never mapped to a catalog model.
NO_MODEL = "earlier-built-in-model"



@dataclass(frozen=True)
class Model:
    id: str
    kind: str  # "reranker"
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
    multilingual: bool
    english_query_required: bool  # the query instruction is English: a non-English question needs an English sentence
    dimensions: int | None = None

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
    Model("qwen3-reranker-0.6b", "reranker", "Qwen3-Reranker-0.6B", "Qwen (ggml-org conversion)", "0.6B", "qwen3",
          "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF", "a02f48bb4f057028298c21fa033da2b30d7742d5",
          "qwen3-reranker-0.6b-q8_0.gguf", 639_153_184,
          "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48", "Apache-2.0", True, 2.1,
          True, False),
    Model("qwen3-reranker-4b", "reranker", "Qwen3-Reranker-4B", "Qwen (community conversion, Voodisss)", "4B", "qwen3",
          "Voodisss/Qwen3-Reranker-4B-GGUF-llama_cpp", "1b452c803342e73ac3644551b727dfd51a09fd5b",
          "Qwen3-Reranker-4B.Q8_0.gguf", 4_279_678_912,
          "102ac400d68f02877c2fdfecf0732872652298448352b6faf28ec7f8dca8c913", "Apache-2.0", False, 6.0,
          True, False),
    Model("qwen3-reranker-8b", "reranker", "Qwen3-Reranker-8B", "Qwen (community conversion, Voodisss)", "8B", "qwen3",
          "Voodisss/Qwen3-Reranker-8B-GGUF-llama_cpp", "646e3a1fc04936cab940ad02e18ee6b14af46263",
          "Qwen3-Reranker-8B.Q8_0.gguf", 8_047_134_304,
          "13815d68c755c6293161a9aebc986976af90b35a7c9ffd2e074e58d28ddfe4ae", "Apache-2.0", False, 9.8,
          True, False),
    Model("bge-reranker-v2-m3", "reranker", "bge-reranker-v2-m3", "BAAI (community conversion, gpustack)", "0.6B", "bge",
          "gpustack/bge-reranker-v2-m3-GGUF", "3093af03b1a635e67b084b1d8c03c5f5e020fd05", "bge-reranker-v2-m3-Q8_0.gguf",
          635_676_416, "a43c7c9b11a4c1517e5bf95151960e1621d1b72f7a493364b01e386cf1aaa1d3", "Apache-2.0", False, 2.0,
          True, False),
)
KINDS = ("reranker",)


def get(model_id: str | None) -> Model | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def of_kind(kind: str) -> list[Model]:
    return [m for m in CATALOG if m.kind == kind]


def identity(model: Model) -> str:
    """The identity used for this model's stored reranker scores."""
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

"""Passage embeddings for semantic passage retrieval (D27, D29).

The question and the text of included sources' passages are embedded by the provider chosen in Settings: the Gemini
API, the OpenAI API, or an embedding model on a local Ollama or LM Studio server. Without a saved choice, Gemini is used
when its key is set (D27). Vectors are stored per passage and model at unit length, so a passage is embedded once per
model. Similarity only ranks passages for the answer step; it does not show that a passage supports a claim.
"""

from __future__ import annotations

import math
import os
from array import array
from dataclasses import dataclass
from typing import Any

import httpx

from deixis.models.gemini import API_URL, error_message

MODEL = "gemini-embedding-2"
DIMENSIONS = 768
OPENAI_MODEL = "text-embedding-3-small"
OPENAI_URL = "https://api.openai.com/v1"
LOCAL_URLS = {"ollama": "http://127.0.0.1:11434/v1", "lm_studio": "http://127.0.0.1:1234/v1"}
KEY_ENVS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
PROVIDERS = ("gemini", "openai", "ollama", "lm_studio", "off")
BATCH = 100
MAX_CHARS = 20_000  # passages are page chunks or abstracts, far below the model's 8,192-token input limit


class EmbeddingError(Exception):
    pass


def unit(values: list[float]) -> array:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return array("f", (v / norm for v in values))


def from_blob(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def similarity(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b))


async def embed(client: httpx.AsyncClient, key: str, texts: list[str], task_type: str) -> list[array]:
    """Gemini: unit-length float32 vectors in input order; any failed batch raises EmbeddingError."""
    vectors: list[array] = []
    for start in range(0, len(texts), BATCH):
        requests = [{"model": f"models/{MODEL}", "content": {"parts": [{"text": text[:MAX_CHARS]}]}, "taskType": task_type,
                     "outputDimensionality": DIMENSIONS} for text in texts[start:start + BATCH]]
        try:
            response = await client.post(f"{API_URL}/models/{MODEL}:batchEmbedContents", json={"requests": requests},
                                         headers={"x-goog-api-key": key}, timeout=60)
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {error_message(response)}")
        vectors += [unit(item["values"]) for item in response.json()["embeddings"]]
    return vectors


async def embed_openai_compatible(client: httpx.AsyncClient, base_url: str, key: str | None, model: str,
                                  texts: list[str]) -> list[array]:
    """OpenAI's /embeddings shape, also served by Ollama and LM Studio; any failed batch raises EmbeddingError."""
    vectors: list[array] = []
    for start in range(0, len(texts), BATCH):
        try:
            response = await client.post(f"{base_url}/embeddings", timeout=120,
                                         json={"model": model, "input": [t[:MAX_CHARS] for t in texts[start:start + BATCH]]},
                                         headers={"Authorization": f"Bearer {key}"} if key else {})
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        if response.status_code != 200:
            raise EmbeddingError(f"HTTP {response.status_code}: {error_message(response)}")
        vectors += [unit(item["embedding"]) for item in sorted(response.json()["data"], key=lambda d: d["index"])]
    return vectors


def chosen(setting: dict[str, Any] | None) -> tuple[str, str | None]:
    """The provider and model semantic search uses: the saved choice, else Gemini when its key is set, else off."""
    if setting:
        return setting["provider"], setting.get("model")
    return ("gemini", MODEL) if os.environ.get(KEY_ENVS["gemini"]) else ("off", None)


@dataclass(frozen=True)
class Embedder:
    provider: str
    model: str

    @property
    def stored_model(self) -> str:
        # Gemini rows written before D29 are stored under the bare model name.
        return self.model if self.provider == "gemini" else f"{self.provider}:{self.model}"

    async def embed(self, client: httpx.AsyncClient, texts: list[str], task_type: str) -> list[array]:
        if self.provider in KEY_ENVS:
            key = os.environ.get(KEY_ENVS[self.provider])
            if not key:
                raise EmbeddingError(f"{KEY_ENVS[self.provider]} is not set")
            if self.provider == "gemini":
                return await embed(client, key, texts, task_type)
            return await embed_openai_compatible(client, OPENAI_URL, key, self.model, texts)
        return await embed_openai_compatible(client, LOCAL_URLS[self.provider], None, self.model, texts)


def options(local_tools: dict[str, Any]) -> list[dict[str, Any]]:
    """Each provider with the models it offers now and, when it cannot be chosen, why."""
    servers = {t["id"]: t for t in local_tools["tools"]}
    result = [
        {"provider": "gemini", "models": [MODEL], "available": bool(os.environ.get(KEY_ENVS["gemini"])),
         "reason": None if os.environ.get(KEY_ENVS["gemini"]) else "Add a Gemini API key"},
        {"provider": "openai", "models": [OPENAI_MODEL], "available": bool(os.environ.get(KEY_ENVS["openai"])),
         "reason": None if os.environ.get(KEY_ENVS["openai"]) else "Add an OpenAI API key"},
    ]
    for provider in ("ollama", "lm_studio"):
        server = servers[provider]
        models = [m["id"] for m in server.get("models", []) if m["embedding"]]
        reason = (None if server["running"] and models
                  else f"{server['name']} lists no embedding model" if server["running"]
                  else f"{server['name']} is not running" if server["installed"]
                  else f"{server['name']} is not installed")
        result.append({"provider": provider, "models": models, "available": reason is None, "reason": reason})
    return result + [{"provider": "off", "models": [], "available": True, "reason": None}]

"""Suggested models for the Ollama and LM Studio cards, read from each catalog's public pages.

Neither site offers a catalog API, so the pages are read as HTML: ollama.com/library sorted by newest, then one tags
page per family for the download sizes; lmstudio.ai/models in its own order, then one page per family for the
downloadable variants and one per variant for its minimum memory. Each family gets the largest size that fits this
computer's memory. Any request or parse that fails gives None, and the card keeps the fixed list in local_tools.
"""

from __future__ import annotations

import asyncio
import html
import math
import re
from typing import Any

import httpx

OLLAMA_LIBRARY = "https://ollama.com/library?sort=newest"
OLLAMA_TAGS = "https://ollama.com/library/{name}/tags"
LMSTUDIO_CATALOG = "https://lmstudio.ai/models"
LMSTUDIO_PAGE = "https://lmstudio.ai/models/{slug}"
TIMEOUT_SECONDS = 10
CONCURRENT = 6
SUGGESTED = 8
# Families looked at before the list is cut to SUGGESTED, so that ones without a fitting size can be skipped.
FAMILIES = 32
MIN_PARAMS = 3  # billions; smaller models do not hold up in research steps
# Ollama chips that mark a model the cards do not offer: cloud-only, embedding, or a classifier ("decision") model.
SKIP_CHIPS = {"cloud", "embedding", "decision"}
# A general model carries a "tools" or "thinking" chip; safety filters and routers are skipped by name.
GENERAL_CHIPS = {"tools", "thinking"}
SKIP_NAMES = re.compile(r"guard|decider|embed|ocr")
MAKERS = {"qwen": "Alibaba", "gemma": "Google", "google": "Google", "embeddinggemma": "Google", "llama": "Meta",
          "meta": "Meta", "muse": "Meta", "mistral": "Mistral", "mistralai": "Mistral", "ministral": "Mistral",
          "magistral": "Mistral", "devstral": "Mistral", "glm": "Zhipu", "zai-org": "Zhipu", "gpt-oss": "OpenAI",
          "openai": "OpenAI", "deepseek": "DeepSeek", "phi": "Microsoft", "microsoft": "Microsoft", "granite": "IBM",
          "ibm": "IBM", "nemotron": "NVIDIA", "nvidia": "NVIDIA", "kimi": "Moonshot", "moonshotai": "Moonshot",
          "olmo": "Ai2", "allenai": "Ai2", "lfm": "Liquid", "liquid": "Liquid", "smollm": "Hugging Face"}


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _gb(size: str) -> float:
    number = float(re.match(r"[\d.]+", size).group())
    return number / 1000 if size.upper().endswith("MB") else number


def _params(tag: str) -> float:
    """Billions of parameters in a size tag such as '9b', '0.8b', '270m' or '35b-a3b'; 0 when there is none."""
    found = re.search(r"(\d+(?:\.\d+)?)([bm])", tag.lower())
    return (float(found.group(1)) / (1000 if found.group(2) == "m" else 1)) if found else 0.0


def needs_gb(size_gb: float) -> int:
    """Memory to run a download of this size: the size plus a few GB, rounded up to 4 GB (the card shows the same)."""
    return math.ceil((size_gb + 4) / 4) * 4


def maker(name: str) -> str:
    head = re.split(r"[/:]", name.lower())[0]
    return MAKERS.get(head) or next((v for k, v in MAKERS.items() if head.startswith(k)), "")


def ollama_families(page: str) -> list[dict[str, Any]]:
    """Library entries in page order: name and size tags, without cloud, embedding or decision models."""
    families = []
    for name, body in re.findall(r'<li[^>]*>\s*<a href="/library/([a-z0-9._-]+)"(.*?)</li>', page, flags=re.S):
        chips = [c.strip() for c in re.findall(r'<span\s+class="inline-flex items-center rounded-md[^"]*"[^>]*>([^<]+)</span>', body)]
        sizes = [c for c in chips if re.fullmatch(r"\d+(?:\.\d+)?[bm](?:-a\d+(?:\.\d+)?b)?", c)]
        if sizes and not SKIP_CHIPS & set(chips) and GENERAL_CHIPS & set(chips) and not SKIP_NAMES.search(name):
            families.append({"name": name, "sizes": sizes})
    return families


def ollama_tag_sizes(page: str, name: str) -> dict[str, float]:
    """Download size in GB of each tag on a family's tags page ('name:tag  <digest> • 6.6GB')."""
    # The tag the family's 'latest' points at is listed as "name:9b latest <digest> • 6.6GB".
    found = re.findall(rf"{re.escape(name)}:([a-z0-9._-]+)(?: latest)? [0-9a-f]{{12}} • ([\d.]+[GM]B)", _text(page))
    return {tag: _gb(size) for tag, size in found}


def ollama_size_tag(sizes: dict[str, float], chip: str, chips: list[str]) -> str | None:
    """The tag that holds a size chip: the chip itself, its mixture-of-experts tag ('30b' → '30b-a3b'), or 'latest'
    when the family has one size (the tags page then lists that size only under 'latest')."""
    if chip in sizes:
        return chip
    moe = next((t for t in sizes if re.fullmatch(rf"{re.escape(chip)}-a\d+(?:\.\d+)?b", t)), None)
    return moe or ("latest" if len(chips) == 1 and "latest" in sizes else None)


def lmstudio_families(page: str) -> list[dict[str, str]]:
    """Catalog entries in page order that can be downloaded (not cloud-only): their slug and display name."""
    families = []
    for attrs, slug, body in re.findall(r'<a ([^>]*data-model-page-has-downloads="true"[^>]*)href="/models/([a-z0-9._-]+)"(.*?)</a>',
                                        page, flags=re.S):
        title = re.search(r'<div class="text-lg font-medium">([^<]+)</div>', body)
        if title and "embed" not in slug:
            families.append({"slug": slug, "name": html.unescape(title.group(1)).strip()})
    return families


def lmstudio_variants(page: str) -> list[str]:
    """Catalog ids (publisher/model) a family page links to."""
    return list(dict.fromkeys(re.findall(r'href="/models/([a-z0-9._-]+/[a-z0-9._@-]+)"', page)))


def lmstudio_memory(page: str) -> int | None:
    found = re.search(r"Minimum system memory ([\d.]+) ?GB", _text(page))
    return math.ceil(float(found.group(1))) if found else None


async def _get(http: httpx.AsyncClient, gate: asyncio.Semaphore, url: str) -> str | None:
    async with gate:
        try:
            response = await http.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        except httpx.HTTPError:
            return None
    return response.text if response.status_code == 200 else None


async def ollama(http: httpx.AsyncClient, memory_gb: int | None) -> list[dict[str, Any]] | None:
    gate = asyncio.Semaphore(CONCURRENT)
    page = await _get(http, gate, OLLAMA_LIBRARY)
    families = ollama_families(page)[:FAMILIES] if page else []
    if not families:
        return None
    tag_pages = await asyncio.gather(*(_get(http, gate, OLLAMA_TAGS.format(name=f["name"])) for f in families))
    models = []
    for family, tags in zip(families, tag_pages):
        sizes = ollama_tag_sizes(tags, family["name"]) if tags else {}
        known = sorted(((sizes[tag], chip, tag) for chip in family["sizes"] if (tag := ollama_size_tag(sizes, chip, family["sizes"]))),
                       reverse=True)
        fits = [k for k in known if (memory_gb is None or needs_gb(k[0]) <= memory_gb) and _params(k[1]) >= MIN_PARAMS]
        if fits:
            gb, chip, tag = fits[-1] if memory_gb is None else fits[0]
            models.append({"id": family["name"] if tag == "latest" else f"{family['name']}:{tag}", "name": f"{family['name']} · {chip.upper()}",
                           "maker": maker(family["name"]), "purpose": "research", "size_bytes": round(gb * 1e9)})
    return models[:SUGGESTED] or None


async def lmstudio(http: httpx.AsyncClient, memory_gb: int | None) -> list[dict[str, Any]] | None:
    gate = asyncio.Semaphore(CONCURRENT)
    page = await _get(http, gate, LMSTUDIO_CATALOG)
    families = lmstudio_families(page)[:FAMILIES] if page else []
    if not families:
        return None
    family_pages = await asyncio.gather(*(_get(http, gate, LMSTUDIO_PAGE.format(slug=f["slug"])) for f in families))
    variants = [lmstudio_variants(p)[:4] if p else [] for p in family_pages]
    memory_pages = await asyncio.gather(*(_get(http, gate, LMSTUDIO_PAGE.format(slug=v)) for vs in variants for v in vs))
    memory = dict(zip((v for vs in variants for v in vs), (lmstudio_memory(p) if p else None for p in memory_pages)))
    models = []
    for family, ids in zip(families, variants):
        known = sorted(((memory[v], _params(v), v) for v in ids if memory.get(v)), reverse=True)
        fits = [k for k in known if (memory_gb is None or k[0] <= memory_gb) and (k[1] == 0 or k[1] >= MIN_PARAMS)]
        if fits:
            need, params, catalog_id = fits[-1] if memory_gb is None else fits[0]
            size = re.search(r"(\d+(?:\.\d+)?[bm](?:-a\d+b)?)$", catalog_id.lower())
            label = size.group(1).upper() if size else ""
            models.append({"id": catalog_id, "name": f"{family['name']} · {label}" if label and label not in family["name"].upper() else family["name"],
                           "maker": maker(catalog_id), "purpose": "research", "size_bytes": None, "memory_gb": need})
    return models[:SUGGESTED] or None

"""Suggested models read from ollama.com and lmstudio.ai pages (local_catalog), on SYNTHETIC pages shaped like the real
ones on 15 Oct 2026. These show the parsing and the size choice, not that the live sites still look like this."""

from __future__ import annotations

import asyncio

import httpx

from deixis.tools import local_catalog as catalog


def chip(text: str) -> str:
    return f'<span  class="inline-flex items-center rounded-md bg-[#ddf4ff] px-2 py-0.5 text-xs">{text}</span>'


def library_entry(name: str, *chips: str) -> str:
    return f'<li  class="flex items-baseline"><a href="/library/{name}" class="group"><span>{name}</span>{"".join(chip(c) for c in chips)}</a></li>'


OLLAMA_LIBRARY = "".join([
    library_entry("syn-cloud", "tools", "cloud"),
    library_entry("syn-embed", "embedding", "300m"),
    library_entry("syn-guard", "tools", "8b"),
    library_entry("syn-plain", "8b"),  # no tools/thinking chip: not a general model
    library_entry("syn-qwen", "tools", "thinking", "4b", "9b", "35b"),
    library_entry("syn-one", "tools", "27b"),
    library_entry("syn-moe", "thinking", "30b"),
    library_entry("syn-tiny", "tools", "1b"),
])
OLLAMA_TAGS = {
    "syn-qwen": "<div>syn-qwen:4b 0123456789ab • 3.3GB</div><div>syn-qwen:9b latest 1123456789ab • 6.6GB</div>"
                "<div>syn-qwen:35b 2123456789ab • 22GB</div>",
    "syn-one": "<div>syn-one:latest 3123456789ab • 18GB</div><div>syn-one:27b-q8_0 4123456789ab • 30GB</div>",
    "syn-moe": "<div>syn-moe:30b-a3b 5123456789ab • 25GB</div><div>syn-moe:30b-a3b-q8_0 6123456789ab • 35GB</div>",
    "syn-tiny": "<div>syn-tiny:1b 7123456789ab • 0.8GB</div>",
}


def ollama_site(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == catalog.OLLAMA_LIBRARY:
        return httpx.Response(200, text=OLLAMA_LIBRARY)
    name = url.removeprefix("https://ollama.com/library/").removesuffix("/tags")
    return httpx.Response(200, text=OLLAMA_TAGS[name]) if name in OLLAMA_TAGS else httpx.Response(404)


def run(read, handler, memory_gb):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await read(http, memory_gb)
    return asyncio.run(go())


def test_ollama_skips_cloud_embedding_safety_plain_and_tiny_models():
    assert [f["name"] for f in catalog.ollama_families(OLLAMA_LIBRARY)] == ["syn-qwen", "syn-one", "syn-moe", "syn-tiny"]


def test_ollama_picks_the_largest_size_that_fits_memory():
    models = run(catalog.ollama, ollama_site, 32)
    # 35b (22 GB) needs 28 GB; a single-size family's size sits under "latest"; "30b" is held by the "30b-a3b" tag.
    assert [(m["id"], m["name"], m["size_bytes"]) for m in models] == [
        ("syn-qwen:35b", "syn-qwen · 35B", 22_000_000_000), ("syn-one", "syn-one · 27B", 18_000_000_000),
        ("syn-moe:30b-a3b", "syn-moe · 30B", 25_000_000_000)]
    small = run(catalog.ollama, ollama_site, 16)
    assert [m["id"] for m in small] == ["syn-qwen:9b"]  # 9b is listed as "syn-qwen:9b latest"; the 1b model is too small


def lms_entry(slug: str, name: str, downloads: bool = True) -> str:
    return (f'<a data-model-page-has-cloud="false" data-model-page-has-downloads="{str(downloads).lower()}" class="x" href="/models/{slug}">'
            f'<div class="text-lg font-medium">{name}</div></a>')


LMS_PAGES = {
    catalog.LMSTUDIO_CATALOG: lms_entry("syn-cloud", "Syn Cloud", downloads=False) + lms_entry("syn-qwen", "Syn Qwen")
                              + lms_entry("syn-bonsai-27b", "Syn Bonsai 27B") + lms_entry("syn-embed", "Syn Embed"),
    "https://lmstudio.ai/models/syn-qwen": '<a href="/models/qwen/syn-qwen-9b">9B</a><a href="/models/qwen/syn-qwen-27b">27B</a>',
    "https://lmstudio.ai/models/syn-bonsai-27b": '<a href="/models/prism-ml/syn-bonsai-27b">27B</a>',
    "https://lmstudio.ai/models/qwen/syn-qwen-9b": "<div>Minimum system memory</div><div>7 GB</div>",
    "https://lmstudio.ai/models/qwen/syn-qwen-27b": "<div>Minimum system memory</div><div>16 GB</div>",
    "https://lmstudio.ai/models/prism-ml/syn-bonsai-27b": "<div>Minimum system memory</div><div>4 GB</div>",
}


def lms_site(request: httpx.Request) -> httpx.Response:
    page = LMS_PAGES.get(str(request.url))
    return httpx.Response(200, text=page) if page else httpx.Response(404)


def test_lm_studio_reads_downloadable_families_and_picks_the_variant_that_fits():
    models = run(catalog.lmstudio, lms_site, 12)
    assert [(m["id"], m["name"], m["maker"], m["memory_gb"]) for m in models] == [
        ("qwen/syn-qwen-9b", "Syn Qwen · 9B", "Alibaba", 7), ("prism-ml/syn-bonsai-27b", "Syn Bonsai 27B", "", 4)]
    assert run(catalog.lmstudio, lms_site, 32)[0]["id"] == "qwen/syn-qwen-27b"


def test_an_unreadable_catalog_gives_none():
    assert run(catalog.ollama, lambda r: httpx.Response(503), 32) is None
    assert run(catalog.lmstudio, lambda r: httpx.Response(200, text="<html>redesigned</html>"), 32) is None

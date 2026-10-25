"""Local tool detection and the local model catalogue suggestion.

Fake folders and catalogue answers. Passing shows detection rules, not every install layout.
"""

from __future__ import annotations

import asyncio
import httpx
import os
import pytest
import sys

from deixis.tools import local_catalog as catalog
from deixis.tools import local_tools
import json
from deixis.documents import embeddings as e


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake programs are shell scripts")


def script(path, body="echo fake 1.2.3"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def refuse(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture
def detect(tmp_path, monkeypatch):
    """`detect(tool_id)` → what the Settings card is built from, with the real `app_locations` and a fake home. The macOS
    app installs and the host's PATH are out of the picture; PATH holds only folders a test adds."""
    monkeypatch.setattr(local_tools, "app_locations", local_tools.app_locations.real)
    monkeypatch.setattr(local_tools, "OLLAMA_MAC", False)
    monkeypatch.setattr(local_tools, "LMSTUDIO_MAC", False)
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(local_tools, "SYSTEM_ROOT", tmp_path / "root")
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(variable, raising=False)
    tools = local_tools.LocalTools(httpx.AsyncClient(transport=httpx.MockTransport(refuse)))

    def run(tool_id):
        return asyncio.run(tools._detect(local_tools.TOOLS[tool_id]))
    run.tools = tools
    return run


def card(detect, tool_id, tmp_path, monkeypatch, platform, present=()):
    """The install part of a tool's card on `platform`, with the named programs present. A lookup by file name stands in for
    `find_tool`: `shutil.which` cannot be run as Windows on another OS."""
    monkeypatch.setattr(sys, "platform", platform)
    folder = tmp_path / "managers"
    for name in present:
        script(folder / name, "exit 0")
    monkeypatch.setattr(local_tools, "find_tool", lambda name: str(folder / name) if name in present else None)
    monkeypatch.setattr(local_tools, "find_tools", lambda name: [])
    return detect(tool_id)["install"]


@posix_only
def test_two_installs_report_the_first_as_chosen_and_the_other_as_present(detect, tmp_path, monkeypatch):
    first, second = script(tmp_path / "npm" / "qwen", "echo 1.0.0"), script(tmp_path / "brew" / "qwen", "echo 2.0.0")
    (tmp_path / "links").mkdir()
    (tmp_path / "links" / "qwen").symlink_to(first)  # the same file again is not a second install
    monkeypatch.setenv("PATH", os.pathsep.join([str(first.parent), str(tmp_path / "links"), str(second.parent)]))
    found = detect("qwen_code")
    assert (found["path"], found["version"], found["other_copies"]) == (str(first), "1.0.0", [str(second)])


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


def test_ollama_picks_the_largest_size_that_fits_memory():
    models = run(catalog.ollama, ollama_site, 32)
    # 35b (22 GB) needs 28 GB; a single-size family's size sits under "latest"; "30b" is held by the "30b-a3b" tag.
    assert [(m["id"], m["name"], m["size_bytes"]) for m in models] == [
        ("syn-qwen:35b", "syn-qwen · 35B", 22_000_000_000), ("syn-one", "syn-one · 27B", 18_000_000_000),
        ("syn-moe:30b-a3b", "syn-moe · 30B", 25_000_000_000)]
    small = run(catalog.ollama, ollama_site, 16)
    assert [m["id"] for m in small] == ["syn-qwen:9b"]  # 9b is listed as "syn-qwen:9b latest"; the 1b model is too small


# Ollama and LM Studio paths through mocked OpenAI-compatible transports.

@pytest.mark.parametrize("provider", ["ollama"])
def test_success_returns_normalized_vectors_in_input_order(provider):
    def handler(request):
        assert json.loads(request.content) == {"model": "synthetic", "input": ["a", "b"]}
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 2]}, {"index": 0, "embedding": [3, 4]}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vectors = asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["a", "b"], "RETRIEVAL_DOCUMENT"))
    assert list(vectors[0]) == pytest.approx([.6, .8]) and list(vectors[1]) == [0, 1]


def test_a_local_embedding_request_never_goes_through_a_proxy_from_the_environment(monkeypatch):
    """D34 follow-up: passage text sent to Ollama or LM Studio must not leave the computer through HTTP_PROXY/ALL_PROXY.
    Two real servers on loopback, the embedding server and a proxy; the environment points every proxy at the latter."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    hits = {"server": [], "proxy": []}

    def serve(name, reply):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                hits[name].append(self.path)
                body = json.dumps(reply).encode()
                self.send_response(200 if name == "server" else 502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    server = serve("server", {"data": [{"index": 0, "embedding": [3, 4]}]})
    proxy = serve("proxy", {"error": "SYNTHETIC proxy"})
    try:
        proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
            monkeypatch.setenv(name, proxy_url)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setitem(e.LOCAL_URLS, "ollama", f"http://127.0.0.1:{server.server_address[1]}/v1")

        async def go():
            async with httpx.AsyncClient() as shared:  # the app's shared client honours the proxy variables
                control = await shared.post(e.LOCAL_URLS["ollama"] + "/embeddings", json={})
                assert control.status_code == 502 and hits["proxy"]  # without the fix the request would go this way
                hits["proxy"].clear()
                deps = SimpleNamespace(http=shared)
                assert e.client_for("openai", deps) is shared  # remote APIs keep the person's proxy
                client = e.client_for("ollama", deps)
                assert client is not shared and client is e.client_for("lm_studio", deps)
                assert client.trust_env is False and client.follow_redirects is False
                try:
                    return await e.Embedder("ollama", "synthetic").embed(client, ["passage"], "RETRIEVAL_DOCUMENT")
                finally:
                    await client.aclose()

        (vector,) = asyncio.run(go())
        assert list(vector) == pytest.approx([.6, .8])
        assert hits == {"server": ["/v1/embeddings"], "proxy": []}
    finally:
        server.shutdown()
        proxy.shutdown()

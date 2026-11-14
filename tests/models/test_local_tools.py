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




# Ollama and LM Studio paths through mocked OpenAI-compatible transports.

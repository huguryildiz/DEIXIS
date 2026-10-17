"""Shared pieces of the built-in model tests (llama.cpp): small SYNTHETIC model files standing in for the catalog's
GGUF files, a runtime folder whose `llama-server` is the fake server, a fake release archive, and a mocked download
handler for GitHub and Hugging Face."""

import dataclasses
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import httpx

from deixis.documents import builtin_catalog, llama_runtime, local_embedding

FAKE_SERVER = Path(__file__).parent.parent / "documents" / "fake_llama_server.py"
BODIES = {m.id: f"SYNTHETIC GGUF {m.id} ".encode() * (5 + i) for i, m in enumerate(builtin_catalog.CATALOG)}


def server_script() -> bytes:
    """The fake server as an executable file of its own, run by this interpreter."""
    return f"#!{sys.executable}\n".encode() + FAKE_SERVER.read_bytes()


def fake_catalog(monkeypatch):
    """Replace every catalog entry's byte count and sha256 with the SYNTHETIC file's; returns {id: bytes}."""
    catalog = tuple(dataclasses.replace(m, bytes=len(BODIES[m.id]), sha256=hashlib.sha256(BODIES[m.id]).hexdigest())
                    for m in builtin_catalog.CATALOG)
    monkeypatch.setattr(builtin_catalog, "CATALOG", catalog)
    return dict(BODIES)


def install_runtime(paths: local_embedding.BuiltinPaths) -> Path:
    """A runtime folder as an install leaves it: the fake server and the marker with its digest."""
    runtime = paths.runtime
    folder = runtime.folder / f"llama-{llama_runtime.TAG}"
    folder.mkdir(parents=True, exist_ok=True)
    server = folder / "llama-server"
    server.write_bytes(server_script())
    server.chmod(0o755)
    (folder / "libllama.dylib").write_bytes(b"SYNTHETIC library")
    runtime.marker.write_text(json.dumps({
        "tag": llama_runtime.TAG, "asset": "SYNTHETIC", "server": f"llama-{llama_runtime.TAG}/llama-server",
        "server_bytes": server.stat().st_size, "server_sha256": llama_runtime.digest(server)}))
    return server


def install_model(paths: local_embedding.BuiltinPaths, model_id: str, body: bytes | None = None, check=True) -> None:
    """A model as an install leaves it: its file, and its full check recorded."""
    model = builtin_catalog.get(model_id)
    target = paths.model_file(model)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(BODIES[model_id] if body is None else body)
    if check:
        local_embedding.ModelIntegrity(paths, model).check_now()


def ready(paths, monkeypatch, *model_ids):
    """The SYNTHETIC catalog, the runtime and the given models installed and checked."""
    fake_catalog(monkeypatch)
    install_runtime(paths)
    for model_id in model_ids:
        install_model(paths, model_id)


def tarball(entries=None) -> bytes:
    """A release archive: `llama-<tag>/llama-server` (the fake server) and a library, or the given (name, info) list."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        if entries is None:
            entries = [(f"llama-{llama_runtime.TAG}/llama-server", server_script(), 0o755),
                       (f"llama-{llama_runtime.TAG}/libllama.dylib", b"SYNTHETIC library", 0o644)]
        for entry in entries:
            if isinstance(entry, tarfile.TarInfo):
                archive.addfile(entry)
                continue
            name, data, mode = entry
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def pin_tarball(monkeypatch, data: bytes) -> llama_runtime.Asset:
    """Pin `data` as this platform's runtime asset."""
    pinned = llama_runtime.Asset(f"llama-{llama_runtime.TAG}-bin-test.tar.gz", len(data), hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(llama_runtime, "ASSETS", {llama_runtime.platform_key(): pinned})
    return pinned


class Downloads:
    """A mocked GitHub and Hugging Face: serves the pinned archive and the SYNTHETIC model files; `override[url]`
    replaces one answer (bytes, or an httpx.Response); every request is recorded."""

    def __init__(self, archive: bytes, bodies: dict[str, bytes]):
        self.archive, self.bodies = archive, bodies
        self.override: dict[str, object] = {}
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.override:
            found = self.override[url]
            return found if isinstance(found, httpx.Response) else httpx.Response(200, content=found)
        pinned = llama_runtime.asset()
        if pinned and url == pinned.url:
            return httpx.Response(200, content=self.archive)
        for model in builtin_catalog.CATALOG:
            if url == model.url:
                return httpx.Response(200, content=self.bodies[model.id])
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

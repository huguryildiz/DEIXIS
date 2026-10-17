"""llama.cpp's prebuilt `llama-server`, the runtime of the built-in models, and the checked download every file takes.

The binaries are published on per-build tags (`bNNNNN`, marked prerelease on GitHub; `/releases/latest` carries none).
DEIXIS pins one build and, per platform, the asset's name, byte count and sha256 as the GitHub API lists them
(`assets[].digest`, read 17 Oct 2026). The builds are shared: `llama-server` loads its sibling `libllama` and `libggml*`
libraries from its own folder, so the extracted folder is kept whole. The macOS arm64 build has Metal inside.

POSIX only in this slice (macOS arm64 and x64, Linux x64): the locks are `fcntl.flock`. Windows is refused before any
download. The builds are not signed or notarized; a file written by httpx carries no quarantine attribute (not checked
live).

A download goes to `<file>.part`, is checked for its byte count and sha256 and only then moved into place. The archive is
unpacked into a temporary folder of ours under `tools/llama`, with every entry checked first (no absolute path, no
`..`, no link that points outside, only files, folders and links), and the folder is renamed into place in one step.
Leftovers of a stopped install (`*.part`, `.tmp-*` folders) are removed at the next install.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tarfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import httpx

from deixis.documents.builtin_catalog import RUNTIME_TAG

TAG = RUNTIME_TAG
RELEASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{TAG}"
SERVER_NAME = "llama-server"
MARKER = "deixis-runtime.json"


@dataclass(frozen=True)
class Asset:
    name: str
    bytes: int
    sha256: str

    @property
    def url(self) -> str:
        return f"{RELEASE_URL}/{self.name}"


ASSETS: dict[tuple[str, str], Asset] = {
    ("darwin", "arm64"): Asset(f"llama-{TAG}-bin-macos-arm64.tar.gz", 12_251_264,
                               "dc1f09829c2f5c7d6e23966548ac1569a442337cbb210df1fabdcf33f3c3181f"),
    ("darwin", "x86_64"): Asset(f"llama-{TAG}-bin-macos-x64.tar.gz", 11_738_046,
                                "7972fa82839964c781f78fb0b220b49bd66cf19445a6749f08664dc2c9617cde"),
    ("linux", "x86_64"): Asset(f"llama-{TAG}-bin-ubuntu-x64.tar.gz", 17_917_870,
                               "05e4fb108c568a8717ef146e86edaee753dabe1f2713c33ea7cb380c74d63cc7"),
}
# Pinned for a later slice; not offered now (no flock on Windows): llama-b11711-bin-win-cpu-x64.zip, 19,613,045 bytes,
# sha256 adfed8d2d78d5ca2fa05109708528ac80e95111c644c287cd6a3c5b94fadda6a.


class DownloadError(Exception):
    pass


class UnsafeArchive(Exception):
    pass


def platform_key() -> tuple[str, str]:
    machine = platform.machine().lower()
    return (os.uname().sysname.lower() if hasattr(os, "uname") else "windows",
            {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine))


def asset() -> Asset | None:
    return ASSETS.get(platform_key()) if os.name == "posix" else None


def supported() -> bool:
    return asset() is not None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def file_matches(path: Path, size: int, sha256: str) -> bool:
    try:
        return path.stat().st_size == size and digest(path) == sha256
    except OSError:
        return False


@dataclass(frozen=True)
class RuntimePaths:
    root: Path  # <data dir>/tools/llama

    @property
    def folder(self) -> Path:
        return self.root / TAG

    @property
    def marker(self) -> Path:
        return self.folder / MARKER

    def record(self) -> dict[str, Any] | None:
        """What the install wrote when it put this build in place, or None when it is not (fully) there."""
        try:
            record = json.loads(self.marker.read_text())
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) and record.get("tag") == TAG and record.get("server") else None

    def installed(self) -> bool:
        return self.record() is not None

    def server(self) -> Path | None:
        record = self.record()
        return self.folder / record["server"] if record else None

    def server_matches(self) -> bool:
        """The server binary still has the sha256 recorded when it was unpacked (a few MB, read at every start)."""
        record = self.record()
        if record is None:
            return False
        return file_matches(self.folder / record["server"], record["server_bytes"], record["server_sha256"])

    def size(self) -> int:
        total = 0
        for folder, _, files in os.walk(self.root):
            for name in files:
                try:
                    total += os.lstat(os.path.join(folder, name)).st_size
                except OSError:
                    pass
        return total


def clean_leftovers(paths: RuntimePaths) -> None:
    """Remove what a stopped install left: archive parts and temporary folders; a build folder without its marker."""
    if not paths.root.is_dir():
        return
    for entry in paths.root.iterdir():
        if entry.name.endswith(".part") or entry.name.startswith(".tmp-"):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    if paths.folder.exists() and not paths.installed():
        shutil.rmtree(paths.folder, ignore_errors=True)


async def download(client: httpx.AsyncClient, url: str, target: Path, size: int, sha256: str,
                   progress: Callable[[int], None] | None = None) -> None:
    """Download `url` to `target` through `<target>.part`, checked for `size` bytes and `sha256` before it is moved
    into place; a mismatch, an HTTP error or a cancel deletes the part, so no file is ever half there."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f"{target.name}.part")
    sha, done = hashlib.sha256(), 0
    try:
        with open(part, "wb") as handle:
            async with client.stream("GET", url, follow_redirects=True, timeout=120) as response:
                if response.status_code != 200:
                    raise DownloadError(f"{target.name}: HTTP {response.status_code}")
                async for chunk in response.aiter_bytes(1 << 16):
                    handle.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if done > size:
                        raise DownloadError(f"{target.name}: more than {size} bytes")
                    if progress:
                        progress(done)
        if done != size or sha.hexdigest() != sha256:
            raise DownloadError(f"{target.name}: {done} bytes, sha256 {sha.hexdigest()[:12]}…, expected {size} bytes, "
                                f"{sha256[:12]}…")
        os.replace(part, target)
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"{target.name}: {type(exc).__name__}: {str(exc)[:200]}") from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _check_members(archive: tarfile.TarFile, dest: Path) -> list[tarfile.TarInfo]:
    """Every entry, refused as a whole when one has an absolute path, a `..`, a link out of `dest`, or is not a file,
    a folder or a link."""
    members = archive.getmembers()
    root = dest.resolve()
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or member.name.startswith(("/", "\\")) or ".." in name.parts:
            raise UnsafeArchive(f"unsafe path in the archive: {member.name!r}")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise UnsafeArchive(f"unsupported entry in the archive: {member.name!r}")
        if member.issym() or member.islnk():
            link = PurePosixPath(member.linkname)
            if link.is_absolute() or member.linkname.startswith(("/", "\\")):
                raise UnsafeArchive(f"unsafe link in the archive: {member.name!r} -> {member.linkname!r}")
            base = (dest / name.parent) if member.issym() else dest
            target = (base / link).resolve()
            if target != root and root not in target.parents:
                raise UnsafeArchive(f"a link points outside the archive: {member.name!r} -> {member.linkname!r}")
    return members


def extract(archive_path: Path, dest: Path) -> str:
    """Unpack the checked archive into `dest` and return the server's path relative to it."""
    dest.mkdir(parents=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _check_members(archive, dest)
        archive.extractall(dest, members=members, filter="data")
    found = [p for p in dest.rglob(SERVER_NAME) if p.is_file() and not p.is_symlink()]
    if len(found) != 1:
        raise UnsafeArchive(f"the archive holds {len(found)} {SERVER_NAME} files, not one")
    server = found[0]
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    return server.relative_to(dest).as_posix()


async def install(client: httpx.AsyncClient, paths: RuntimePaths, progress: Callable[[int], None] | None = None) -> None:
    """Put the pinned build in `tools/llama/<tag>/`. The caller holds the install lock and the runtime's in-use lock
    exclusively and has called `clean_leftovers`."""
    import asyncio

    pinned = asset()
    if pinned is None:
        raise DownloadError("llama.cpp has no pinned build for this platform")
    paths.root.mkdir(parents=True, exist_ok=True)
    archive = paths.root / pinned.name
    await download(client, pinned.url, archive, pinned.bytes, pinned.sha256, progress)
    temporary = paths.root / f".tmp-{uuid.uuid4().hex}"
    try:
        server = await asyncio.to_thread(extract, archive, temporary)
        server_path = temporary / server
        record = {"tag": TAG, "asset": pinned.name, "asset_sha256": pinned.sha256, "server": server,
                  "server_bytes": server_path.stat().st_size,
                  "server_sha256": await asyncio.to_thread(digest, server_path), "installed_at": now_iso()}
        (temporary / MARKER).write_text(json.dumps(record))
        if paths.folder.exists():
            await asyncio.to_thread(shutil.rmtree, paths.folder, True)
        os.replace(temporary, paths.folder)
    finally:
        archive.unlink(missing_ok=True)
        if temporary.exists():
            await asyncio.to_thread(shutil.rmtree, temporary, True)

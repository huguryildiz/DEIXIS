"""Command-line tools and local model servers on this computer (D29).

Detection reads the PATH, the places each OS's installer puts an app (`app_locations`), `--version` output and the model
servers' loopback endpoints. A tool is reported with the copy chosen (`path`), whether that copy ran (`runnable`) and
the other copies found (`other_copies`) (E15). An install runs the one package-manager command fixed for that tool id,
never a command taken from a request, and only where that package manager belongs: without one the card links to the
tool's download page (B1). Codex, Claude Code,
GitHub Copilot CLI (D24) and Gemini CLI (D23) run research steps; the other CLIs are detected only (found is not supported), and a local server's embedding models can rank answer passages. Zotero
is the one reference manager: its local API is where a collection import reads from (D16).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from deixis.child_env import NODE_TLS, UV_TLS, child_env
from deixis.job_failure import failure_line
from deixis.storage.db import now
from deixis.tool_paths import find_tool, find_tools
from deixis.tool_probe import Probe, probe, probe_blocking

CACHE_SECONDS = 30
CATALOG_SECONDS = 24 * 60 * 60
INSTALL_TIMEOUT_SECONDS = 20 * 60
OUTPUT_TAIL_CHARS = 4000
OUTPUT_TAIL_BYTES = 4 * OUTPUT_TAIL_CHARS  # a UTF-8 character is at most four bytes
READ_CHUNK_BYTES = 64 * 1024
# The model the Ollama card offers first when no embedding model is installed: a small one semantic search can use.
OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
# On macOS Ollama installs as the app from ollama.com (it runs the server in the menu bar), not Homebrew's bare CLI.
OLLAMA_MAC = sys.platform == "darwin"
OLLAMA_MAC_APP = Path("/Applications/Ollama.app")
OLLAMA_MAC_DMG = "https://ollama.com/download/Ollama.dmg"
DOWNLOAD_TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests put a mock transport here
# LM Studio ships for Apple silicon only on macOS; its latest-download link redirects to the versioned disk image.
LMSTUDIO_MAC = OLLAMA_MAC and platform.machine() == "arm64"
LMSTUDIO_MAC_APP = Path("/Applications/LM Studio.app")
LMSTUDIO_MAC_DMG = "https://lmstudio.ai/download/latest/darwin/arm64"
# LM Studio catalog ids (lmstudio.ai/models, 15 Oct 2026); the catalog lists the minimum memory, not the download size.
LMSTUDIO_SUGGESTED = (
    {"id": "qwen/qwen3.5-4b", "name": "Qwen 3.5 · 4B", "maker": "Alibaba", "purpose": "research", "size_bytes": None, "memory_gb": 4},
    {"id": "qwen/qwen3.5-9b", "name": "Qwen 3.5 · 9B", "maker": "Alibaba", "purpose": "research", "size_bytes": None, "memory_gb": 7},
    {"id": "google/gemma-4-12b", "name": "Gemma 4 · 12B", "maker": "Google", "purpose": "research", "size_bytes": None, "memory_gb": 7},
    {"id": "openai/gpt-oss-20b", "name": "gpt-oss · 20B", "maker": "OpenAI", "purpose": "research", "size_bytes": None, "memory_gb": 12},
    {"id": "mistralai/mistral-small-3.2", "name": "Mistral Small 3.2", "maker": "Mistral", "purpose": "research", "size_bytes": None, "memory_gb": 14},
    {"id": "zai-org/glm-4.7-flash", "name": "GLM 4.7 Flash", "maker": "Zhipu", "purpose": "research", "size_bytes": None, "memory_gb": 16},
    {"id": "google/gemma-4-31b", "name": "Gemma 4 · 31B", "maker": "Google", "purpose": "research", "size_bytes": None, "memory_gb": 19},
    {"id": "qwen/qwen3.5-35b-a3b", "name": "Qwen 3.5 · 35B-A3B", "maker": "Alibaba", "purpose": "research", "size_bytes": None, "memory_gb": 21},
    {"id": "google/embedding-gemma-300m", "name": "EmbeddingGemma", "maker": "Google", "purpose": "embedding", "size_bytes": 300_000_000, "memory_gb": None},
)
# A catalog id: publisher/model. It goes into a JSON body, never a command.
LMSTUDIO_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}/[A-Za-z0-9][A-Za-z0-9._@-]{0,119}")
LMSTUDIO_POLL_SECONDS = 1.0
OLLAMA_RELEASES = "https://api.github.com/repos/ollama/ollama/releases/latest"
OLLAMA_REGISTRY = "https://registry.ollama.ai/v2/{name}/manifests/{tag}"
OLLAMA_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
# The Ollama card's suggestions (sizes from ollama.com/library, 15 Oct 2026): two embedding models for semantic search
# and the research-step models the Local models note names. Any other library name can be typed in.
OLLAMA_SUGGESTED = (  # download sizes as ollama.com/library lists them (15 Oct 2026)
    {"id": "qwen3.5:4b", "name": "Qwen 3.5 · 4B", "maker": "Alibaba", "purpose": "research", "size_bytes": 3_300_000_000},
    {"id": "qwen3.5:9b", "name": "Qwen 3.5 · 9B", "maker": "Alibaba", "purpose": "research", "size_bytes": 6_600_000_000},
    {"id": "gemma4:12b", "name": "Gemma 4 · 12B", "maker": "Google", "purpose": "research", "size_bytes": 7_700_000_000},
    {"id": "gpt-oss:20b", "name": "gpt-oss · 20B", "maker": "OpenAI", "purpose": "research", "size_bytes": 14_000_000_000},
    {"id": "mistral-small3.2", "name": "Mistral Small 3.2", "maker": "Mistral", "purpose": "research", "size_bytes": 15_000_000_000},
    {"id": "glm-4.7-flash", "name": "GLM 4.7 Flash", "maker": "Zhipu", "purpose": "research", "size_bytes": 19_000_000_000},
    {"id": "gemma4:31b", "name": "Gemma 4 · 31B", "maker": "Google", "purpose": "research", "size_bytes": 19_000_000_000},
    {"id": "qwen3.5:35b", "name": "Qwen 3.5 · 35B", "maker": "Alibaba", "purpose": "research", "size_bytes": 22_000_000_000},
    {"id": "nomic-embed-text", "name": "Nomic Embed Text", "maker": "Nomic", "purpose": "embedding", "size_bytes": 274_000_000},
    {"id": "embeddinggemma", "name": "EmbeddingGemma", "maker": "Google", "purpose": "embedding", "size_bytes": 622_000_000},
    {"id": "mxbai-embed-large", "name": "mxbai Embed Large", "maker": "Mixedbread", "purpose": "embedding", "size_bytes": 670_000_000},
)
# An Ollama model name: library or namespace/model, an optional :tag. It goes into a JSON body, never a command.
OLLAMA_MODEL_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}(/[a-z0-9][a-z0-9._-]{0,79})?(:[A-Za-z0-9][A-Za-z0-9._-]{0,79})?")


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    kind: str  # 'cli', 'server' or 'app'
    binary: str
    install: tuple[str, ...]  # argv; the first item is the package manager, looked up on PATH
    url: str
    role: str = "detected"
    app: str | None = None  # a macOS app bundle that also counts as installed
    endpoint: str | None = None


TOOLS = {t.id: t for t in (
    Tool("claude_code", "Claude Code", "cli", "claude", ("npm", "install", "-g", "@anthropic-ai/claude-code"),
         "https://docs.claude.com/en/docs/claude-code/setup", role="runs_steps"),
    Tool("codex", "Codex CLI", "cli", "codex", ("npm", "install", "-g", "@openai/codex"),
         "https://developers.openai.com/codex/cli", role="runs_steps"),
    Tool("gemini_cli", "Gemini CLI", "cli", "gemini", ("npm", "install", "-g", "@google/gemini-cli"),
         "https://github.com/google-gemini/gemini-cli", role="runs_steps"),
    Tool("qwen_code", "Qwen Code", "cli", "qwen", ("npm", "install", "-g", "@qwen-code/qwen-code"),
         "https://github.com/QwenLM/qwen-code"),
    Tool("kimi_cli", "Kimi CLI", "cli", "kimi", ("uv", "tool", "install", "kimi-cli"),
         "https://github.com/MoonshotAI/kimi-cli"),
    Tool("mistral_vibe", "Mistral Vibe", "cli", "vibe", ("uv", "tool", "install", "mistral-vibe"),
         "https://github.com/mistralai/mistral-vibe"),
    Tool("copilot_cli", "GitHub Copilot CLI", "cli", "copilot", ("npm", "install", "-g", "@github/copilot"),
         "https://github.com/github/copilot-cli", role="runs_steps"),
    Tool("opencode", "OpenCode", "cli", "opencode", ("npm", "install", "-g", "opencode-ai"),
         "https://opencode.ai"),
    Tool("aider", "Aider", "cli", "aider", ("uv", "tool", "install", "aider-chat"),
         "https://aider.chat"),
    Tool("goose", "Goose", "cli", "goose", ("brew", "install", "block-goose-cli"),
         "https://goose-docs.ai"),
    Tool("amp", "Amp", "cli", "amp", ("npm", "install", "-g", "@sourcegraph/amp"),
         "https://ampcode.com"),
    Tool("cline", "Cline", "cli", "cline", ("npm", "install", "-g", "cline"),
         "https://github.com/cline/cline"),
    Tool("ollama", "Ollama", "server", "ollama", ("brew", "install", "ollama"), "https://ollama.com/download",
         app="/Applications/Ollama.app", endpoint="http://127.0.0.1:11434"),
    Tool("lm_studio", "LM Studio", "server", "lms", ("brew", "install", "--cask", "lm-studio"), "https://lmstudio.ai/download",
         app="/Applications/LM Studio.app", endpoint="http://127.0.0.1:1234"),
    Tool("zotero", "Zotero", "app", "zotero", ("brew", "install", "--cask", "zotero"), "https://www.zotero.org/download/",
         role="imports", app="/Applications/Zotero.app", endpoint="http://127.0.0.1:23119"),
)}


log = logging.getLogger(__name__)


class ToolError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code  # a reason the page words in its own language (B3); None for a plain refusal


def manager_missing(name: str) -> str:
    """The reason code for an installer program that is not on this computer. Homebrew is the way to install things only
    on macOS, so without it elsewhere the card sends the person to the download page (B1)."""
    if name == "uv":
        return "uv_missing"
    return "download_page" if name == "brew" and sys.platform != "darwin" else "manager_missing"


def install_argv(tool: Tool) -> tuple[str, ...] | None:
    """The package-manager command that installs the tool on this OS, or None when there is none to run and the card
    links to the download page instead. Homebrew casks are macOS apps; Homebrew is not a Windows tool."""
    if tool.install[0] == "brew" and (sys.platform == "win32" or ("--cask" in tool.install and sys.platform != "darwin")):
        return None
    return tool.install


# Where each OS puts the apps (B1); a file or folder here that exists counts as installed even when its folder is not on PATH.
# macOS: the app bundle in /Applications (`Tool.app`) or, for a person without admin rights, in ~/Applications.
# Windows: Ollama's OllamaSetup.exe and LM Studio's installer install for the current user only, under
# %LOCALAPPDATA%\Programs (Ollama's Windows documentation names that folder); Zotero's installer defaults to Program Files.
# Each entry is the variable of the root folder and the parts below it; both Program Files folders are tried.
WINDOWS_APPS = {
    "ollama": (("LOCALAPPDATA", ("Programs", "Ollama", "ollama.exe")), ("ProgramFiles", ("Ollama", "ollama.exe"))),
    "lm_studio": (("LOCALAPPDATA", ("Programs", "LM Studio", "LM Studio.exe")), ("ProgramFiles", ("LM Studio", "LM Studio.exe"))),
    "zotero": (("ProgramFiles", ("Zotero", "zotero.exe")), ("ProgramFiles(x86)", ("Zotero", "zotero.exe")),
               ("LOCALAPPDATA", ("Zotero", "zotero.exe"))),
}
# Linux: Ollama's install script puts the binary in /usr/local/bin (a distribution package in /usr/bin, the snap in
# /snap/bin); Zotero's download is unpacked to /opt/zotero by its own instructions, a distribution package puts it in
# /usr/bin, and its Flatpak (org.zotero.Zotero on Flathub) leaves a launcher in the Flatpak exports folder, per user or
# for the system; LM Studio ships as an AppImage, which AppImageLauncher keeps in ~/Applications.
# Tests point SYSTEM_ROOT at a fake root.
SYSTEM_ROOT = Path("/")
LINUX_BINARIES = {"ollama": ("ollama",), "zotero": ("zotero",)}
LINUX_EXTRA = {"ollama": (("snap", "bin", "ollama"),), "zotero": (("opt", "zotero", "zotero"),)}
FLATPAK_LAUNCHERS = {"zotero": "org.zotero.Zotero"}


def app_locations(tool: Tool) -> list[Path]:
    """The places this OS's installer puts the tool's app or program, in the order they are looked at."""
    home = Path.home()
    found: list[Path] = []
    if tool.id == "lm_studio":  # the `lms` command LM Studio sets up for itself, on every OS
        found.append(home / ".lmstudio" / "bin" / ("lms.exe" if sys.platform == "win32" else "lms"))
    if sys.platform == "darwin":
        if tool.app:
            found += [Path(tool.app), home / "Applications" / Path(tool.app).name]
    elif sys.platform == "win32":
        for variable, parts in WINDOWS_APPS.get(tool.id, ()):
            if root := os.environ.get(variable):
                found.append(Path(root).joinpath(*parts))
    else:
        bins = [SYSTEM_ROOT / "usr" / "local" / "bin", SYSTEM_ROOT / "usr" / "bin", home / ".local" / "bin"]
        found += [folder / name for name in LINUX_BINARIES.get(tool.id, ()) for folder in bins]
        found += [SYSTEM_ROOT.joinpath(*parts) for parts in LINUX_EXTRA.get(tool.id, ())]
        if launcher := FLATPAK_LAUNCHERS.get(tool.id):
            found += [home / ".local" / "share" / "flatpak" / "exports" / "bin" / launcher,
                      SYSTEM_ROOT / "var" / "lib" / "flatpak" / "exports" / "bin" / launcher]
        if tool.id == "lm_studio":
            try:
                found += sorted((home / "Applications").glob("LM-Studio*.AppImage"))
            except OSError:
                pass
    return found


def installed_app(tool: Tool) -> Path | None:
    """The first of the tool's `app_locations` that exists."""
    return next((p for p in app_locations(tool) if p.exists()), None)


def _command_output(argv: list[str], timeout: float | None = None) -> str | None:
    return _version_line(probe_blocking(argv, timeout, child_env(tool=argv[0])))


def _version_line(done: Probe) -> str | None:
    """The line of a tool's output that names its version; None when it fails or does not answer (A3b, E16)."""
    lines = [line.strip() for line in (done.stdout or done.stderr).strip().splitlines()]
    if not done.ok or not lines:
        return None
    # `ollama --version` warns first when its server is not running and names the version on a later line.
    line = next((line for line in lines if re.search(r"\d+\.\d+", line)), lines[0])
    return re.sub(r"^warning:\s*", "", line, flags=re.IGNORECASE)


def _app_version(app: str) -> str | None:
    try:
        with open(Path(app) / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException):
        return None


def _copy_mac_app(dmg: Path, target: Path) -> None:
    """Mount the downloaded disk image, copy its app to target and unmount it."""
    mount = Path(tempfile.mkdtemp(prefix="deixis-ollama-mount-"))
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(dmg)],
                   check=True, capture_output=True, text=True, timeout=120, env=child_env())
    try:
        # Copied beside the target and then swapped in, so an update never leaves the older app's files inside the new bundle.
        fresh, old = target.with_name(f".{target.name}.new"), target.with_name(f".{target.name}.old")
        shutil.rmtree(fresh, ignore_errors=True)
        subprocess.run(["ditto", str(mount / target.name), str(fresh)], check=True, capture_output=True, text=True, timeout=300,
                       env=child_env())
        if target.exists():
            shutil.rmtree(old, ignore_errors=True)
            target.rename(old)
        fresh.rename(target)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        subprocess.run(["hdiutil", "detach", "-force", str(mount)], capture_output=True, timeout=60, env=child_env())
        shutil.rmtree(mount, ignore_errors=True)


def _mac_app(tool_id: str) -> tuple[Path, str, str] | None:
    """The app bundle, its download link and site when DEIXIS installs this tool as a macOS app; read at call time."""
    if tool_id == "ollama" and OLLAMA_MAC:
        return OLLAMA_MAC_APP, OLLAMA_MAC_DMG, "ollama.com"
    if tool_id == "lm_studio" and LMSTUDIO_MAC:
        return LMSTUDIO_MAC_APP, LMSTUDIO_MAC_DMG, "lmstudio.ai"
    return None


def _open_mac_app(app: Path) -> None:
    subprocess.run(["open", "-a", str(app)], check=True, capture_output=True, text=True, timeout=30, env=child_env())


def _quit_mac_app(app: Path) -> None:
    """Ask the app to quit so its files can be replaced; one that is not running is left as it is."""
    subprocess.run(["osascript", "-e", f'quit app "{app.stem}"'], capture_output=True, timeout=30, env=child_env())
    time.sleep(2)


def machine() -> dict[str, Any]:
    chip = memory = None
    if sys.platform == "darwin":
        chip = _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
        memory_bytes = _command_output(["sysctl", "-n", "hw.memsize"])
        memory = int(memory_bytes) if memory_bytes and memory_bytes.isdigit() else None
    else:
        chip = platform.processor() or None
        try:
            memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (AttributeError, ValueError, OSError):
            memory = None
    disk = shutil.disk_usage(Path.home())
    return {"chip": chip, "memory_gb": round(memory / 2**30) if memory else None,
            "disk_free_gb": round(disk.free / 2**30), "disk_total_gb": round(disk.total / 2**30)}


def _bytes(value: Any) -> int:
    """A byte count a server reported; 0 (unknown) when it is not a number."""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


class LocalTools:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        self._cache: tuple[float, dict[str, Any]] | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._pull: dict[str, Any] | None = None  # the Ollama embedding model download, while it runs and after
        self._pull_task: asyncio.Task | None = None
        self._lms_pull: dict[str, Any] | None = None  # the LM Studio model download, while it runs and after
        self._lms_task: asyncio.Task | None = None
        self._catalogs: dict[str, tuple[float, dict[str, Any]]] = {}  # tool id → (when read, suggestions)

    async def snapshot(self, refresh: bool = False) -> dict[str, Any]:
        if refresh or not self._cache or time.monotonic() - self._cache[0] > CACHE_SECONDS:
            tools = await asyncio.gather(*(self._detect(tool) for tool in TOOLS.values()))
            self._cache = (time.monotonic(), {"machine": await asyncio.to_thread(machine), "tools": list(tools)})
        data = self._cache[1]
        return {**data, "tools": [{**t, "job": self._jobs.get(t["id"]), **({"pull": self._pull, "suggested": list(OLLAMA_SUGGESTED)} if t["id"] == "ollama" else
                                     {"pull": self._lms_pull, "suggested": list(LMSTUDIO_SUGGESTED)} if t["id"] == "lm_studio" else {})}
                                  for t in data["tools"]]}

    async def _detect(self, tool: Tool) -> dict[str, Any]:
        path = await asyncio.to_thread(find_tool, tool.binary)
        located = installed_app(tool)
        app = str(located) if located else None
        if path is None and located and located.is_file() and located.stem.lower() == tool.binary:
            path = app  # the command itself, found where its installer puts it though that folder is not on PATH
        probed = await probe([path, "--version"], env=child_env(tool=path)) if path else None
        version = _version_line(probed) if probed else None
        # The other copies of the command on this computer (E15); the first one found is the one used and shown.
        copies = await asyncio.to_thread(find_tools, tool.binary) if path else []
        others = [c for c in copies if os.path.realpath(c) != os.path.realpath(path)]
        argv = install_argv(tool)
        manager = await asyncio.to_thread(find_tool, argv[0]) if argv else None
        models = await self._server_models(tool) if tool.kind == "server" else None
        status: dict[str, Any] = {
            # A server that answers counts as installed even when its binary is not on PATH.
            "id": tool.id, "name": tool.name, "kind": tool.kind, "installed": bool(path or app or models is not None),
            "version": version or (_app_version(app) if app else None), "path": path or app, "role": tool.role,
            # The chosen copy answered its version check (None: nothing was run). No version is required anywhere in DEIXIS,
            # so "ran" is the whole test; a copy that did not run, or did not answer in time (A3b), says so on its card.
            "runnable": None if probed is None else probed.ok, "other_copies": others,
            "reason_code": "not_responding" if probed and probed.error == "not_responding" else "not_runnable" if probed and not probed.ok else None,
            # `unavailable_reason` is a code (`uv_missing`, `manager_missing`, `download_page`); `manager` names the program the install needs.
            "install": {"command": " ".join(argv) if argv else None, "available": bool(manager),
                        "unavailable_reason": None if manager else manager_missing(argv[0]) if argv else "download_page",
                        "manager": argv[0] if argv else None, "url": tool.url},
        }
        if tool.kind == "server":
            status |={"endpoint": tool.endpoint, "running": models is not None, "models": models or []}
        if mac := _mac_app(tool.id):
            status["app_installed"] = mac[0].exists()
            status["install"] = {"command": f"{mac[0].name} from {mac[2]}", "available": True,
                                 "unavailable_reason": None, "url": tool.url}
        if tool.kind == "app":
            local_api = await self._zotero_local_api(tool)
            status["installed"] = status["installed"] or local_api is not None
            status |= {"endpoint": tool.endpoint, "running": local_api is not None, "local_api": bool(local_api),
                       # zotero.org import reads these from the environment (filled from the keychain); reported as set or not, never shown.
                       "web_configured": bool(os.environ.get("ZOTERO_API_KEY") and os.environ.get("ZOTERO_LIBRARY_ID"))}
        return status

    async def _zotero_local_api(self, tool: Tool) -> bool | None:
        """True when the local API reads, False when Zotero answers with it turned off, None when Zotero does not answer."""
        try:
            response = await self._client.get(f"{tool.endpoint}/api/users/0/collections", params={"limit": 1}, timeout=2)
        except httpx.HTTPError:
            return None
        return response.status_code == 200

    async def _server_models(self, tool: Tool) -> list[dict[str, Any]] | None:
        """Models the running server lists, or None when it does not answer."""
        try:
            if tool.id == "ollama":
                tags = await self._client.get(f"{tool.endpoint}/api/tags", timeout=2)
                if tags.status_code != 200:
                    return None
                models = []
                for m in tags.json().get("models", []):
                    shown = await self._client.post(f"{tool.endpoint}/api/show", json={"model": m["name"]}, timeout=5)
                    capabilities = shown.json().get("capabilities", []) if shown.status_code == 200 else []
                    models.append({"id": m["name"], "size_bytes": m.get("size"), "embedding": "embedding" in capabilities})
                return models
            native = await self._client.get(f"{tool.endpoint}/api/v0/models", timeout=2)
            if native.status_code == 200:
                return [{"id": m["id"], "size_bytes": None, "embedding": m.get("type") == "embeddings"}
                        for m in native.json().get("data", [])]
            listed = await self._client.get(f"{tool.endpoint}/v1/models", timeout=2)
            if listed.status_code != 200:
                return None
            # The OpenAI-compatible list has no model type; LM Studio's embedding models carry "embed" in their ids.
            return [{"id": m["id"], "size_bytes": None, "embedding": "embed" in m["id"].lower()} for m in listed.json().get("data", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def _reserve(self, tool_id: str, message: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Take the tool's job slot before any await: a second request at once is turned away, and the two cannot both
        run the installer or swap the same app folders. `_start` replaces the placeholder with the real job."""
        previous = self._jobs.get(tool_id)
        if (previous or {}).get("status") == "running":
            raise ToolError(409, message)
        placeholder = {"status": "running", "started_at": now(), "finished_at": None, "output": "", "completed": 0, "total": 0}
        self._jobs[tool_id] = placeholder
        return placeholder, previous

    def _release(self, tool_id: str, placeholder: dict[str, Any], previous: dict[str, Any] | None) -> None:
        if self._jobs.get(tool_id) is placeholder:  # a cancel may already have taken it over
            if previous is None:
                self._jobs.pop(tool_id, None)
            else:
                self._jobs[tool_id] = previous

    async def install(self, tool_id: str) -> dict[str, Any]:
        tool = TOOLS.get(tool_id)
        if tool is None:
            raise ToolError(404, f"Unknown tool '{tool_id}'")
        reserved, previous = self._reserve(tool_id, f"{tool.name} is already being installed")
        try:
            return await self._install(tool_id, tool, reserved)
        except BaseException:
            self._release(tool_id, reserved, previous)
            raise

    async def _install(self, tool_id: str, tool: Tool, reserved: dict[str, Any]) -> dict[str, Any]:
        current = next(t for t in (await self.snapshot(refresh=True))["tools"] if t["id"] == tool_id)
        if _mac_app(tool_id):
            # Offered also when only Homebrew's CLI is there: without the app nothing starts the server.
            if current["app_installed"] or current["running"]:
                raise ToolError(409, f"{tool.name} is already installed")
            return self._start(tool_id, {"status": "running", "command": current["install"]["command"], "started_at": now(),
                                         "finished_at": None, "output": "", "completed": 0, "total": 0},
                               self._install_mac_app, reserved)
        if current["installed"]:
            raise ToolError(409, f"{tool.name} is already installed")
        install = install_argv(tool)
        if install is None:
            raise ToolError(422, f"{tool.name} has no install command here; download it from {tool.url}", "download_page")
        manager = await asyncio.to_thread(find_tool, install[0])
        if not manager:
            raise ToolError(422, f"{install[0]} was not found on this computer", manager_missing(install[0]))
        job = {"status": "running", "command": " ".join(install), "started_at": now(), "finished_at": None, "output": ""}
        argv = [manager, *install[1:]]
        return self._start(tool_id, job, lambda tool_id, job: self._run(tool_id, job, argv), reserved)

    async def update(self, tool_id: str) -> dict[str, Any]:
        """Install a newer Ollama or LM Studio the way the installed one came: Homebrew's Ollama with `brew upgrade` (and its
        service restarted when Homebrew runs it), the macOS app by quitting it and copying the newer app over it."""
        tool = TOOLS.get(tool_id)
        if tool_id not in ("ollama", "lm_studio") or tool is None:
            raise ToolError(404, f"'{tool_id}' is not updated from DEIXIS")
        reserved, previous = self._reserve(tool_id, f"{tool.name} is already being installed or updated")
        try:
            return await self._update(tool_id, tool, reserved)
        except BaseException:
            self._release(tool_id, reserved, previous)
            raise

    async def _update(self, tool_id: str, tool: Tool, reserved: dict[str, Any]) -> dict[str, Any]:
        path = await asyncio.to_thread(find_tool, tool.binary)
        real = os.path.realpath(path) if path else ""
        brew = await asyncio.to_thread(find_tool, "brew")
        job: dict[str, Any] = {"status": "running", "started_at": now(), "finished_at": None, "output": "", "completed": 0, "total": 0,
                               "kind": "update"}
        if tool_id == "ollama" and brew and ("/Cellar/" in real or "/homebrew/" in real):
            job["command"] = "brew upgrade ollama"

            async def run(tool_id: str, job: dict[str, Any]) -> None:
                await self._run(tool_id, job, [brew, "upgrade", "ollama"])
                services = await asyncio.to_thread(_command_output, [brew, "services", "list"], 15) or ""
                if job["status"] == "succeeded" and any(line.split()[:2] == ["ollama", "started"] for line in services.splitlines()):
                    job["status"] = "running"
                    await self._run(tool_id, job, [brew, "services", "restart", "ollama"])
            return self._start(tool_id, job, run, reserved)
        mac = _mac_app(tool_id)
        if not mac or not mac[0].exists():
            raise ToolError(422, f"{tool.name} was not installed by Homebrew or as the macOS app; update it from {tool.url}")
        job["command"] = f"{mac[0].name} from {mac[2]}"

        async def replace(tool_id: str, job: dict[str, Any]) -> None:
            await asyncio.to_thread(_quit_mac_app, mac[0])
            await self._install_mac_app(tool_id, job)
        return self._start(tool_id, job, replace, reserved)

    def _start(self, tool_id: str, job: dict[str, Any], run, reserved: dict[str, Any]) -> dict[str, Any]:
        if self._jobs.get(tool_id) is not reserved or reserved["status"] != "running":  # cancelled while the tool was looked for
            raise ToolError(409, "It was stopped before it started")
        self._jobs[tool_id] = job
        task = asyncio.create_task(run(tool_id, job))
        self._tasks[tool_id] = task
        task.add_done_callback(lambda t, tool_id=tool_id: self._tasks.pop(tool_id, None))
        return job

    async def _install_mac_app(self, tool_id: str, job: dict[str, Any]) -> None:
        """Download the app's disk image from its site, copy the app to /Applications and open it. Ollama's app starts
        its server; LM Studio's server is started from the card afterwards."""
        app, url, _site = _mac_app(tool_id)
        folder = Path(tempfile.mkdtemp(prefix="deixis-app-"))
        dmg = folder / "app.dmg"
        try:
            # Both sites redirect to the release file; this download is not to this computer, so not the loopback client.
            async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=120),
                                         transport=DOWNLOAD_TRANSPORT) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    job["total"] = int(response.headers.get("content-length") or 0)
                    with dmg.open("wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
                            job["completed"] += len(chunk)
            job["output"] = f"Downloaded {url}; copying {app.name} to {app.parent}"
            await asyncio.to_thread(_copy_mac_app, dmg, app)
            await asyncio.to_thread(_open_mac_app, app)
            job.update(status="succeeded", finished_at=now())
        except (httpx.HTTPError, OSError, subprocess.SubprocessError) as exc:
            job.update(status="failed", finished_at=now(), output=failure_line(exc, "The app install"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            self._cache = None

    async def _running_ollama(self) -> dict[str, Any]:
        ollama = next(t for t in (await self.snapshot(refresh=True))["tools"] if t["id"] == "ollama")
        if not ollama["running"]:
            raise ToolError(409, "Ollama is not running: open the Ollama app or run `ollama serve`")
        return ollama

    async def pull_embedding_model(self) -> dict[str, Any]:
        return await self.pull_model(OLLAMA_EMBEDDING_MODEL)

    async def pull_model(self, model: str) -> dict[str, Any]:
        """Download one model through the running Ollama server, one download at a time."""
        model = model.strip()
        if not OLLAMA_MODEL_NAME.fullmatch(model):
            raise ToolError(400, "That is not an Ollama model name, such as qwen3.5:35b")
        if (self._pull or {}).get("status") == "running":
            raise ToolError(409, f"{self._pull['model']} is already being downloaded")
        # The download slot is taken before the first await (E17): a second request at once is turned away.
        job = {"status": "running", "model": model, "step": "", "completed": 0, "total": 0,
               "started_at": now(), "finished_at": None, "output": ""}
        previous, self._pull = self._pull, job
        try:
            await self._running_ollama()
            if job["status"] != "running":  # cancelled while Ollama was being looked for
                raise ToolError(409, "It was stopped before it started")
            self._pull_task = asyncio.create_task(self._run_pull(job))
        except BaseException:
            if self._pull is job:
                self._pull = previous
            raise
        return job

    async def _run_pull(self, job: dict[str, Any]) -> None:
        # Ollama streams one JSON line per event; a layer's events carry its digest with bytes done and its size.
        done: dict[str, int] = {}
        sizes: dict[str, int] = {}
        try:
            async with self._client.stream("POST", f"{TOOLS['ollama'].endpoint}/api/pull",
                                           json={"model": job["model"], "stream": True},
                                           timeout=httpx.Timeout(30, read=300)) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    job.update(status="failed", output=f"Ollama answered {response.status_code}: {body}"[-OUTPUT_TAIL_CHARS:])
                    return
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        job.update(status="failed", output=str(event["error"])[-OUTPUT_TAIL_CHARS:])
                        return
                    job["step"] = str(event.get("status", ""))
                    if event.get("digest") and event.get("total"):
                        sizes[event["digest"]] = int(event["total"])
                        done[event["digest"]] = int(event.get("completed") or 0)
                        job.update(completed=sum(done.values()), total=sum(sizes.values()))
                    if event.get("status") == "success":
                        job["status"] = "succeeded"
            if job["status"] == "running":
                job.update(status="failed", output="Ollama ended the download without reporting success.")
        except Exception as exc:  # noqa: BLE001 - any failure ends the job, so the slot is never left taken (E17)
            job.update(status="failed", output=failure_line(exc, "The model download"))
        finally:
            if job["status"] == "running":  # cancelled while DEIXIS closes
                job.update(status="failed", output=job["output"] or "Stopped.")
            job["finished_at"] = now()
            self._cache = None

    def cancel_pull(self) -> dict[str, Any]:
        """Stop the running model download; closing the stream makes Ollama stop it and keep the partial layers."""
        job = self._pull
        if not job or job["status"] != "running":
            raise ToolError(409, "No model is being downloaded")
        if self._pull_task:
            self._pull_task.cancel()
        job.update(status="cancelled", finished_at=now())
        return job

    async def delete_model(self, model: str) -> None:
        """Remove one installed model from Ollama; only a name Ollama itself lists is sent."""
        ollama = await self._running_ollama()
        if model not in {m["id"] for m in ollama.get("models") or []}:
            raise ToolError(404, f"{model} is not installed in Ollama")
        if (self._pull or {}).get("status") == "running" and self._pull["model"] in (model, model.removesuffix(":latest")):
            raise ToolError(409, f"{model} is being downloaded")
        try:
            response = await self._client.request("DELETE", f"{TOOLS['ollama'].endpoint}/api/delete", json={"model": model}, timeout=30)
        except httpx.HTTPError as exc:
            log.warning("Ollama did not answer: %s: %s", type(exc).__name__, exc)
            raise ToolError(502, "Ollama did not answer", "server_not_answering") from exc
        finally:
            self._cache = None
        if response.status_code != 200:
            raise ToolError(502, f"Ollama answered {response.status_code}: {response.text[:300]}")

    async def ollama_updates(self, http: httpx.AsyncClient) -> dict[str, Any]:
        """Whether a newer Ollama is released and which installed models changed on ollama.com. A model's digest in
        Ollama's list is the sha256 of its manifest, so it is compared with the registry's current manifest. Every
        unanswered check is None: the card then shows nothing."""
        from deixis.documents.tool_updates import newer

        endpoint = TOOLS["ollama"].endpoint
        try:
            version = (await self._client.get(f"{endpoint}/api/version", timeout=2)).json().get("version")
            tags = (await self._client.get(f"{endpoint}/api/tags", timeout=2)).json().get("models", [])
        except (httpx.HTTPError, ValueError, AttributeError):
            raise ToolError(409, "Ollama is not running: open the Ollama app or run `ollama serve`")

        async def latest() -> str | None:
            try:
                response = await http.get(OLLAMA_RELEASES, timeout=10)
                response.raise_for_status()
                return str(response.json()["tag_name"]).lstrip("v")
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return None

        async def changed(model: dict[str, Any]) -> bool | None:
            name, _, tag = str(model.get("name", "")).partition(":")
            if not name or "." in name.split("/")[0] and "/" in name:  # a model from another registry is not checked
                return None
            try:
                response = await http.get(OLLAMA_REGISTRY.format(name=name if "/" in name else f"library/{name}", tag=tag or "latest"),
                                          headers={"Accept": OLLAMA_MANIFEST}, timeout=10)
                if response.status_code != 200:
                    return None
            except httpx.HTTPError:
                return None
            return hashlib.sha256(response.content).hexdigest() != model.get("digest")

        released, *models = await asyncio.gather(latest(), *(changed(m) for m in tags))
        path = await asyncio.to_thread(find_tool, "ollama")
        real = os.path.realpath(path) if path else ""
        how = "homebrew" if "/Cellar/" in real or "/homebrew/" in real else "app" if OLLAMA_MAC and OLLAMA_MAC_APP.exists() else None
        return {"version": version, "latest": released, "update_available": newer(released, version), "installed_with": how,
                "models": {m["name"]: c for m, c in zip(tags, models)}}

    async def _running_lm_studio(self) -> None:
        lm_studio = next(t for t in (await self.snapshot(refresh=True))["tools"] if t["id"] == "lm_studio")
        if not lm_studio["running"]:
            raise ToolError(409, "LM Studio's server is not running: start it from this card or in LM Studio's Developer tab")

    async def lm_studio_pull(self, model: str) -> dict[str, Any]:
        """Download one catalog model through LM Studio's REST API (POST /api/v1/models/download), then follow its job."""
        model = model.strip()
        if not LMSTUDIO_MODEL_NAME.fullmatch(model):
            raise ToolError(400, "That is not an LM Studio catalog name, such as qwen/qwen3.5-9b")
        if (self._lms_pull or {}).get("status") == "running":
            raise ToolError(409, f"{self._lms_pull['model']} is already being downloaded")
        # The download slot is taken before the first await (E17): a second request at once is turned away.
        job = {"status": "running", "model": model, "step": "", "completed": 0, "total": 0,
               "started_at": now(), "finished_at": None, "output": ""}
        previous, self._lms_pull = self._lms_pull, job
        try:  # whatever goes wrong until the download is followed gives the slot back (E17)
            started = await self._start_lm_studio_download(model)
            if job["status"] != "running":
                raise ToolError(409, "It was stopped before it started")
            job["total"] = _bytes(started.get("total_size_bytes"))
            if started.get("status") == "already_downloaded":
                job.update(status="succeeded", finished_at=now(), step="already_downloaded")
            elif started.get("status") == "failed" or not started.get("job_id"):
                job.update(status="failed", finished_at=now(), output=str(started)[:OUTPUT_TAIL_CHARS])
            else:
                self._lms_task = asyncio.create_task(self._follow_lm_studio(job, str(started["job_id"])))
        except BaseException:
            if self._lms_pull is job:
                self._lms_pull = previous
            raise
        return job

    async def _start_lm_studio_download(self, model: str) -> dict[str, Any]:
        await self._running_lm_studio()
        endpoint = TOOLS["lm_studio"].endpoint
        try:
            response = await self._client.post(f"{endpoint}/api/v1/models/download", json={"model": model}, timeout=30)
        except httpx.HTTPError as exc:
            raise ToolError(502, f"LM Studio did not answer: {exc}") from exc
        if response.status_code == 404:
            raise ToolError(409, "This LM Studio cannot download through its server; update LM Studio to 0.4 or later")
        if response.status_code != 200:
            raise ToolError(502, f"LM Studio answered {response.status_code}: {response.text[:300]}")
        try:
            started = response.json()
        except ValueError as exc:
            raise ToolError(502, "LM Studio answered with something that is not JSON") from exc
        if not isinstance(started, dict):
            raise ToolError(502, f"LM Studio answered unexpectedly: {str(started)[:300]}")
        return started

    async def _follow_lm_studio(self, job: dict[str, Any], job_id: str) -> None:
        url = f"{TOOLS['lm_studio'].endpoint}/api/v1/models/download/status/{job_id}"
        try:
            while job["status"] == "running":
                await asyncio.sleep(LMSTUDIO_POLL_SECONDS)
                state = (await self._client.get(url, timeout=10)).json()
                if not isinstance(state, dict):
                    raise ValueError(f"LM Studio answered unexpectedly: {str(state)[:200]}")
                job.update(step=str(state.get("status", "")), completed=_bytes(state.get("downloaded_bytes")),
                           total=_bytes(state.get("total_size_bytes")) or job["total"])
                if state.get("status") == "completed":
                    job["status"] = "succeeded"
                elif state.get("status") == "failed":
                    job.update(status="failed", output="LM Studio reported the download as failed.")
        except Exception as exc:  # noqa: BLE001 - any failure ends the job, so the slot is never left taken (E17)
            job.update(status="failed", output=failure_line(exc, "The model download"))
        finally:
            if job["status"] == "running":  # cancelled while DEIXIS closes
                job.update(status="failed", output=job["output"] or "Stopped.")
            job["finished_at"] = now()
            self._cache = None

    async def start_lm_studio_server(self) -> None:
        """Start LM Studio's local server with its own CLI (`lms server start`, a fixed command)."""
        lms = await asyncio.to_thread(find_tool, "lms") or str(Path.home() / ".lmstudio" / "bin" / "lms")
        if not Path(lms).exists():
            raise ToolError(409, "LM Studio's command-line tool is not set up yet: open LM Studio once, then try again")
        try:
            done = await asyncio.to_thread(subprocess.run, [lms, "server", "start"], capture_output=True, text=True, timeout=60,
                                           env=child_env(tool=lms))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(502, f"`lms server start` did not finish: {exc}") from exc
        self._cache = None
        if done.returncode != 0:
            raise ToolError(502, ((done.stderr or done.stdout).strip() or f"`lms server start` exited with {done.returncode}")[-600:])

    async def lm_studio_updates(self, http: httpx.AsyncClient) -> dict[str, Any]:
        """The installed LM Studio version against the one its latest-download link redirects to; models are not checked."""
        from deixis.documents.tool_updates import newer

        lm_studio = next(t for t in (await self.snapshot())["tools"] if t["id"] == "lm_studio")
        latest = None
        if LMSTUDIO_MAC:
            try:
                response = await http.head(LMSTUDIO_MAC_DMG, timeout=10, follow_redirects=False)
                found = re.search(r"/(\d+\.\d+\.\d+)(?:-\d+)?/", response.headers.get("location", ""))
                latest = found.group(1) if found else None
            except httpx.HTTPError:
                latest = None
        version = lm_studio["version"]
        return {"version": version, "latest": latest, "update_available": newer(latest, version),
                "installed_with": "app" if lm_studio.get("app_installed") else None, "models": {}}

    async def suggested(self, tool_id: str, http: httpx.AsyncClient) -> dict[str, Any]:
        """Suggested research models read from the tool's catalog and sized for this computer's memory, kept for a day;
        the fixed list when the catalog cannot be read. Embedding suggestions always come from the fixed list."""
        from deixis import local_catalog

        fixed = OLLAMA_SUGGESTED if tool_id == "ollama" else LMSTUDIO_SUGGESTED
        kept = self._catalogs.get(tool_id)
        if kept and time.monotonic() - kept[0] < CATALOG_SECONDS:
            return kept[1]
        memory = (await self.snapshot())["machine"].get("memory_gb")
        read = local_catalog.ollama if tool_id == "ollama" else local_catalog.lmstudio
        live = await read(http, memory)
        embedding = [m for m in fixed if m["purpose"] == "embedding"]
        result = ({"models": [*live, *embedding], "source": "catalog", "memory_gb": memory} if live else
                  {"models": list(fixed), "source": "fixed", "memory_gb": memory})
        if live:  # a failed read is tried again on the next open, not kept for a day
            self._catalogs[tool_id] = (time.monotonic(), result)
        return result

    def cancel(self, tool_id: str) -> dict[str, Any]:
        tool = TOOLS.get(tool_id)
        if tool is None:
            raise ToolError(404, f"Unknown tool '{tool_id}'")
        job = self._jobs.get(tool_id)
        if not job or job["status"] != "running":
            raise ToolError(409, f"{tool.name} is not being installed")
        proc = self._procs.get(tool_id)
        if proc:
            proc.kill()
        if task := self._tasks.get(tool_id):  # none yet while the tool is still being looked for
            task.cancel()
        job.update(status="cancelled", finished_at=now())
        return job

    async def _run(self, tool_id: str, job: dict[str, Any], argv: list[str]) -> None:
        output = bytearray()
        # No keys (E4): the package manager and the install scripts it runs see only the allowlisted environment.
        env = child_env({"HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1", "CI": "1", **UV_TLS, **NODE_TLS}, network=True,
                        tool=argv[0])

        async def read(proc: asyncio.subprocess.Process) -> int:
            assert proc.stdout is not None
            # In chunks, keeping only the tail (E18): a very long line neither stops the read nor grows memory.
            while chunk := await proc.stdout.read(READ_CHUNK_BYTES):
                output.extend(chunk)
                del output[:-OUTPUT_TAIL_BYTES]
                job["output"] = output[-OUTPUT_TAIL_CHARS:].decode("utf-8", "replace")
            return await proc.wait()

        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                        stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            job.update(status="failed", finished_at=now(), output=failure_line(exc, "The install"))
            return
        except asyncio.CancelledError:  # cancelled while the process was being started: the job does not stay "running"
            job.update(status="failed", finished_at=now(), output="Stopped.")
            raise
        self._procs[tool_id] = proc
        try:
            try:
                code = await asyncio.wait_for(read(proc), INSTALL_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                job.update(status="failed", finished_at=now(), output=job["output"] + "\nStopped after 20 minutes.")
                return
            except asyncio.CancelledError:  # DEIXIS is closing: the job does not stay "running" (E18)
                if job["status"] == "running":  # a job that was cancelled has already said so
                    job.update(status="failed", finished_at=now(), output=job["output"] + "\nStopped.")
                raise
            except Exception as exc:  # noqa: BLE001 - a failed read ends the job instead of leaving it running (E18)
                job.update(status="failed", finished_at=now(), output=job["output"] + "\n" + failure_line(exc, "The install"))
                return
            job.update(status="succeeded" if code == 0 else "failed", finished_at=now())
            self._cache = None
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            self._procs.pop(tool_id, None)

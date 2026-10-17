"""Update checks for the PDF tools on Settings → On this computer: Tesseract, Marker and PyMuPDF.

A check runs when the tool's panel opens and sends one request: Homebrew's formula API for Tesseract, PyPI for the
two Python packages. Tesseract is the user's own install in a run from the repository (D51): `TesseractInstaller`
installs or updates it with the one fixed Homebrew command when the user presses Install or Update, and reports the step
it is on. In the packaged app Tesseract comes inside it (B1): nothing is asked of Homebrew and its version moves with the
app. Marker and PyMuPDF are
pinned by DEIXIS: their reading errors were measured on the pinned version and the extraction version names it, so a
newer release reaches the user with a DEIXIS update, not in place.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from typing import Any
from importlib.metadata import version as package_version

import httpx

from deixis.tools.child_env import UV_TLS, child_env
from deixis.documents import math_reader, ocr
from deixis.tools.job_failure import failure_line
from deixis.storage.db import now
from deixis.tools.tool_paths import find_tool
from deixis.tools.tool_probe import probe_blocking

TOOLS = ("tesseract", "marker", "pymupdf")
TESSERACT_URL = "https://formulae.brew.sh/api/formula/tesseract.json"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
TIMEOUT_SECONDS = 10
# Where to get Tesseract on a computer without Homebrew: Homebrew itself on macOS, the build the Tesseract project lists for
# Windows (UB Mannheim, linked from its own installation page), the project's installation page for Linux's package managers.
TESSERACT_PAGES = {"darwin": "https://brew.sh", "win32": "https://github.com/UB-Mannheim/tesseract/wiki",
                   "linux": "https://tesseract-ocr.github.io/tessdoc/Installation.html"}
# `brew install` also upgrades an outdated formula, so one command installs and updates; tesseract-lang adds Turkish.
INSTALL_ARGS = ("install", "tesseract", "tesseract-lang")
INSTALL_TIMEOUT_SECONDS = 20 * 60
OUTPUT_TAIL_CHARS = 4000
OUTPUT_TAIL_BYTES = 4 * OUTPUT_TAIL_CHARS
READ_CHUNK_BYTES = 64 * 1024


def _parts(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text.split("_")[0]))  # Homebrew revisions end in "_1"


def newer(latest: str | None, current: str | None) -> bool | None:
    """Whether `latest` is a later release than `current`; None when either is unknown."""
    if not latest or not current:
        return None
    return _parts(latest) > _parts(current)


def pymupdf_status() -> dict:
    import pymupdf

    return {"available": True, "version": package_version("pymupdf"), "mupdf_version": pymupdf.mupdf_version}


def marker_installed_version(paths: math_reader.RuntimePaths) -> str | None:
    """The marker-pdf version in DEIXIS's Marker environment, or None when it is not installed or cannot be asked."""
    if not paths.installed():
        return None
    done = probe_blocking([str(paths.python), "-c", "from importlib.metadata import version; print(version('marker-pdf'))"],
                          env=child_env())
    return done.stdout.strip() or None if done.ok else None


async def _latest(http: httpx.AsyncClient, tool: str) -> str:
    if tool == "tesseract":
        response = await http.get(TESSERACT_URL, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()["versions"]["stable"]
    name = "marker-pdf" if tool == "marker" else "pymupdf"
    response = await http.get(PYPI_URL.format(name=name), timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()["info"]["version"]


async def check(tool: str, http: httpx.AsyncClient, marker_paths: math_reader.RuntimePaths) -> dict:
    """The installed and the latest released version of `tool`, whether an update exists and how it is installed."""
    if tool == "tesseract":
        status = await asyncio.to_thread(ocr.tesseract_status)
        installed, tested = status["version"], None
        if status.get("bundled"):  # it comes with this DEIXIS and moves with it: no request to Homebrew
            return {"tool": tool, "installed": installed, "tested": tested, "latest": None, "update_available": None, "error": None}
    elif tool == "marker":
        installed = await asyncio.to_thread(marker_installed_version, marker_paths)
        tested = math_reader.MARKER_PACKAGE.split("==")[1]
    else:
        installed = tested = package_version("pymupdf")
    try:
        latest, error = await _latest(http, tool), None
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        latest, error = None, f"{type(exc).__name__}: {exc}"[:300]
    return {"tool": tool, "installed": installed, "tested": tested, "latest": latest,
            "update_available": newer(latest, installed), "error": error}


def tesseract_page() -> str:
    """The page to install Tesseract from when DEIXIS cannot do it with Homebrew."""
    return TESSERACT_PAGES.get(sys.platform, TESSERACT_PAGES["linux"])


def tesseract_source() -> dict[str, str | None]:
    """Where a person gets Tesseract on this OS: Homebrew on macOS, a download page elsewhere (the panel words each)."""
    return {"install_url": tesseract_page(), "install_manager": "brew" if sys.platform == "darwin" else None}


def brew() -> str | None:
    return find_tool("brew")  # a Finder-started app may not have Homebrew on PATH; find_tool also looks where it installs


def _phase(line: str) -> str | None:
    """The step a Homebrew output line starts: downloading, then installing."""
    if re.match(r"==> (Fetching|Downloading)|Fetching: ", line):
        return "downloading"
    if re.match(r"==> (Pouring|Installing|Upgrading)", line):
        return "installing"
    return None


class TesseractInstaller:
    """One install or update of Tesseract at a time, run with the fixed Homebrew command; never a command from a request."""

    def __init__(self) -> None:
        self.job: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None

    def start(self, manager: str | None = None) -> dict[str, Any]:
        """`manager` is the Homebrew found by the caller (off the event loop); without it the search is made here."""
        if self.job and self.job["status"] == "running":
            raise RuntimeError("Tesseract is already being installed")
        manager = manager or brew()
        if not manager:
            raise LookupError("Homebrew was not found on this computer")
        self.job = {"status": "running", "phase": "preparing", "started_at": now(), "finished_at": None, "output": "",
                    "packages_done": 0, "packages_total": None}
        self._task = asyncio.create_task(self._run(self.job, [manager, *INSTALL_ARGS]))
        return self.job

    async def _run(self, job: dict[str, Any], argv: list[str]) -> None:
        output = bytearray()
        # No keys reach Homebrew or the scripts it runs (E4).
        env = child_env({"HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1", "CI": "1", **UV_TLS}, network=True, tool=argv[0])

        packages: list[str] = []
        fetched: set[str] = set()
        partial = b""

        def count(line: str) -> None:
            # Homebrew names the packages it will fetch in one "Fetching: a, b" line, then ticks off each bottle.
            if line.startswith("Fetching: "):
                packages[:] = [name.strip() for name in line[len("Fetching: "):].split(",") if name.strip()]
                job["packages_total"] = len(packages)
            elif (m := re.match(r"\S+ Bottle (?!Manifest )(\S+) ", line)) and m[1] in packages:
                fetched.add(m[1])
                job["packages_done"] = len(fetched)

        async def read(proc: asyncio.subprocess.Process) -> int:
            nonlocal partial
            assert proc.stdout is not None
            # In chunks, keeping only the tail (E18); the phase is the last step line in that tail.
            while chunk := await proc.stdout.read(READ_CHUNK_BYTES):
                *lines, partial = (partial + chunk).split(b"\n")
                partial = partial[-OUTPUT_TAIL_BYTES:]
                for line in lines:
                    count(line.decode("utf-8", "replace").strip())
                output.extend(chunk)
                del output[:-OUTPUT_TAIL_BYTES]
                job["output"] = output[-OUTPUT_TAIL_CHARS:].decode("utf-8", "replace")
                job["phase"] = next((p for line in reversed(job["output"].splitlines()) if (p := _phase(line))), job["phase"])
            return await proc.wait()

        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                        stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            job.update(status="failed", finished_at=now(), output=failure_line(exc, "The Tesseract install"))
            return
        except asyncio.CancelledError:  # cancelled while the process was being started: the job does not stay "running"
            job.update(status="failed", finished_at=now(), output="Stopped.")
            raise
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
            job.update(status="failed", finished_at=now(), output=job["output"] + "\n" + failure_line(exc, "The Tesseract install"))
            return
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        job.update(status="succeeded" if code == 0 else "failed", finished_at=now())

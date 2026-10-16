"""Update checks for the PDF tools on Settings → On this computer: Tesseract, Marker and PyMuPDF.

A check runs when the tool's panel opens and sends one request: Homebrew's formula API for Tesseract, PyPI for the
two Python packages. Tesseract is the user's own install (D51): `TesseractInstaller` installs or updates it with the one
fixed Homebrew command when the user presses Install or Update, and reports the step it is on. Marker and PyMuPDF are
pinned by DEIXIS: their reading errors were measured on the pinned version and the extraction version names it, so a
newer release reaches the user with a DEIXIS update, not in place.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from importlib.metadata import version as package_version

import httpx

from deixis.documents import math_reader, ocr
from deixis.storage.db import now
from deixis.tool_probe import probe_blocking

TOOLS = ("tesseract", "marker", "pymupdf")
TESSERACT_URL = "https://formulae.brew.sh/api/formula/tesseract.json"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
TIMEOUT_SECONDS = 10
# `brew install` also upgrades an outdated formula, so one command installs and updates; tesseract-lang adds Turkish.
INSTALL_ARGS = ("install", "tesseract", "tesseract-lang")
BREW_PLACES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")  # a Finder-started app may not have them on PATH
INSTALL_TIMEOUT_SECONDS = 20 * 60
OUTPUT_TAIL_CHARS = 4000


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
    done = probe_blocking([str(paths.python), "-c", "from importlib.metadata import version; print(version('marker-pdf'))"])
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
        installed = (await asyncio.to_thread(ocr.tesseract_status))["version"]
        tested = None
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


def brew() -> str | None:
    return shutil.which("brew") or next((p for p in BREW_PLACES if Path(p).is_file()), None)


def _phase(line: str) -> str | None:
    """The step a Homebrew output line starts: downloading, then installing."""
    if re.match(r"==> (Fetching|Downloading)", line):
        return "downloading"
    if re.match(r"==> (Pouring|Installing|Upgrading)", line):
        return "installing"
    return None


class TesseractInstaller:
    """One install or update of Tesseract at a time, run with the fixed Homebrew command; never a command from a request."""

    def __init__(self) -> None:
        self.job: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> dict[str, Any]:
        if self.job and self.job["status"] == "running":
            raise RuntimeError("Tesseract is already being installed")
        manager = brew()
        if not manager:
            raise LookupError("Homebrew was not found on this computer")
        self.job = {"status": "running", "phase": "preparing", "started_at": now(), "finished_at": None, "output": ""}
        self._task = asyncio.create_task(self._run(self.job, [manager, *INSTALL_ARGS]))
        return self.job

    async def _run(self, job: dict[str, Any], argv: list[str]) -> None:
        output = bytearray()
        env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1", "CI": "1"}

        async def read(proc: asyncio.subprocess.Process) -> int:
            assert proc.stdout is not None
            async for line in proc.stdout:
                output.extend(line)
                job["output"] = output[-OUTPUT_TAIL_CHARS:].decode("utf-8", "replace")
                job["phase"] = _phase(line.decode("utf-8", "replace")) or job["phase"]
            return await proc.wait()

        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                        stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            job.update(status="failed", finished_at=now(), output=f"{type(exc).__name__}: {exc}")
            return
        try:
            code = await asyncio.wait_for(read(proc), INSTALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            job.update(status="failed", finished_at=now(), output=job["output"] + "\nStopped after 20 minutes.")
            return
        job.update(status="succeeded" if code == 0 else "failed", finished_at=now())

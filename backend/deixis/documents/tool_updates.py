"""Update checks for the PDF tools on Settings → On this computer: Tesseract, Marker and PyMuPDF.

A check runs only when the user asks for it and sends one request: Homebrew's formula API for Tesseract, PyPI for the
two Python packages. Nothing is updated from here. Tesseract is the user's own install (D51), so the answer names the
Homebrew command. Marker and PyMuPDF are pinned by DEIXIS: their reading errors were measured on the pinned version and
the extraction version names it, so a newer release reaches the user with a DEIXIS update, not in place.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from importlib.metadata import version as package_version

import httpx

from deixis.documents import math_reader, ocr

TOOLS = ("tesseract", "marker", "pymupdf")
TESSERACT_URL = "https://formulae.brew.sh/api/formula/tesseract.json"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
TIMEOUT_SECONDS = 10
UPGRADE_COMMAND = "brew upgrade tesseract tesseract-lang"


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
    try:
        done = subprocess.run([str(paths.python), "-c", "from importlib.metadata import version; print(version('marker-pdf'))"],
                              capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


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
            "update_available": newer(latest, installed), "command": UPGRADE_COMMAND if tool == "tesseract" else None,
            "error": error}

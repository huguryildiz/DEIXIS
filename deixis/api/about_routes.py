"""Settings → General → About (pre-P10 F2, F5): the app's version and licence, where this version's source is, the
third-party notices text, and the "Report a problem" link.

The report link carries three facts and nothing else: the DEIXIS version, the operating system name and the CPU
architecture, each checked against a short list or a pattern. No path, user name, email, key or error text goes into it.
"""

from __future__ import annotations

import platform
import re
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlencode

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from deixis import paths

REPO_URL = "https://github.com/huguryildiz/DEIXIS"
LICENSE_ID = "AGPL-3.0-or-later"
NOTICES_FILE = "THIRD_PARTY_NOTICES"
# Versions that have a `v<version>` tag on GitHub, whose page holds that version's source. P10 adds a version here when it
# cuts the release (and attaches the source archive); until then the link goes to the repository.
TAGGED_VERSIONS: frozenset[str] = frozenset()
VERSION_SHAPE = re.compile(r"^\d+\.\d+\.\d+[0-9A-Za-z.+\-]{0,30}$")
OS_NAMES = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
ARCHITECTURES = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}


def app_version() -> str:
    try:
        return version("deixis")
    except PackageNotFoundError:
        return "unknown"


def clean_version(raw: str) -> str:
    """The version if it looks like one, else "unknown", so nothing else can reach the report link."""
    return raw if VERSION_SHAPE.fullmatch(raw) else "unknown"


def os_and_arch() -> tuple[str, str]:
    return OS_NAMES.get(platform.system(), "other"), ARCHITECTURES.get(platform.machine().lower(), "other")


def source_url(app: str) -> tuple[str, bool]:
    """(page, whether it is the version's tag page). The repository's front page when the version has no tag."""
    return (f"{REPO_URL}/tree/v{app}", True) if app in TAGGED_VERSIONS else (REPO_URL, False)


def report_url(app: str, os_name: str, arch: str) -> str:
    """GitHub's new-issue page for the bug form, title empty. `version` and `os` fill that form's fields; `body` is what
    GitHub uses when the form is not found."""
    system = f"{os_name} {arch}"
    return f"{REPO_URL}/issues/new?" + urlencode({"template": "bug.yml", "version": app, "os": system,
                                                  "body": f"DEIXIS version: {app}\nOS: {system}"})


def register_about_routes(app) -> None:
    def notices_path():
        path = paths.RESOURCE_ROOT / NOTICES_FILE
        return path if path.is_file() else None

    @app.get("/api/about")
    async def about() -> dict:
        number = clean_version(app_version())
        os_name, arch = os_and_arch()
        source, is_tag = source_url(number)
        return {"version": number, "license": LICENSE_ID, "repo_url": REPO_URL, "source_url": source, "source_is_tag": is_tag,
                "notices_available": notices_path() is not None, "os": os_name, "arch": arch,
                "report_url": report_url(number, os_name, arch)}

    @app.get("/api/about/notices")
    async def notices() -> PlainTextResponse:
        path = notices_path()
        if path is None:
            raise HTTPException(404, "The third-party licence list is not part of this build.")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

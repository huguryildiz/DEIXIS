"""Whether a newer DEIXIS release exists on GitHub (P10 M3, P10g). It tells; it never downloads or installs anything.

What is sent: one GET of the repository's release list on api.github.com, with `User-Agent: DEIXIS` and the JSON accept
header only: no token, no cookie, no version, no contact address (the app's shared client carries one, so this check
has its own), no redirect followed, 10 s, at most 1 MB read. GitHub sees the computer's IP address and the time.

When: the first check a minute after start, then once a day while DEIXIS runs. The time of each attempt is kept in the
library before the request goes, so neither a restart nor the switch nor a failure asks again within the day; the time
of the last answered check is kept apart for Settings. A failure (no network, a refusal, an answer that is not a release
list) writes one log line and shows nothing. On by default in the packaged app, off in a run from
the repository (that updates with git); Settings → About turns it on or off, and off sends nothing.

Which release counts: a non-draft release whose tag is `vMAJOR.MINOR.PATCH` with an optional pre-release part, newer
than this build by semantic-version order. GitHub's "prerelease" flag is not read (every DEIXIS preview carries it); a
tag with a pre-release part (`v0.10.0-rc.1`) is offered only to a build whose own version has one. This build's version
comes from Python's package metadata, which writes `0.10.0-rc.1` as `0.10.0rc1`; both forms are read. The list is the
twenty newest releases, and a newer version is a newer release, so Settings says "no newer version was found" and no
more. The download link is built here from the version, never taken from the answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx

from deixis.paths import is_frozen

log = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/huguryildiz/DEIXIS/releases?per_page=20"
RELEASE_PAGE = "https://github.com/huguryildiz/DEIXIS/releases/tag/v{version}"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "DEIXIS"}
TIMEOUT_SECONDS = 10.0
MAX_BYTES = 1_000_000
EVERY = timedelta(hours=24)
FIRST_DELAY_SECONDS = 60.0
WAKE_SECONDS = 3600.0
SETTING = "update_check"  # "on" | "off"; unset = the default for this kind of run
CHECKED_AT = "update_check_at"  # the last answered check
ATTEMPTED_AT = "update_check_attempted_at"  # the last request sent, answered or not
LATEST = "update_check_latest"
NUMBER = r"(?:0|[1-9]\d{0,5})"
IDENTIFIER = r"(?:0|[1-9]\d{0,5}|[0-9A-Za-z]*[A-Za-z][0-9A-Za-z]*)"
SEMVER = re.compile(rf"v?({NUMBER})\.({NUMBER})\.({NUMBER})(?:-({IDENTIFIER}(?:\.{IDENTIFIER}){{0,4}}))?")
PYTHON = re.compile(rf"({NUMBER})\.({NUMBER})\.({NUMBER})(?:(a|b|rc)({NUMBER}))?")  # Python's normal form of a version
PYTHON_PRE = {"a": "alpha", "b": "beta", "rc": "rc"}


def parse(text: object) -> tuple | None:
    """A sortable key for a version or tag (semantic-version order), or None when it is not one."""
    if not isinstance(text, str) or len(text) > 64:
        return None
    if match := SEMVER.fullmatch(text):
        major, minor, patch, pre = match.groups()
        pre_parts = pre.split(".") if pre else None
    elif match := PYTHON.fullmatch(text):
        major, minor, patch, kind, number = match.groups()
        pre_parts = [PYTHON_PRE[kind], number] if kind else None
    else:
        return None
    # A release ranks above its own pre-releases; pre-release parts compare number below word, numbers by value.
    parts = (2,) if pre_parts is None else (1, *((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre_parts))
    return (int(major), int(minor), int(patch), parts)


def plain(text: str) -> str:
    return text[1:] if text.startswith("v") else text


def newest(releases: list, current: str) -> str | None:
    """The newest offered version above `current` in a GitHub release list, or None."""
    mine = parse(current)
    if mine is None:
        return None
    best: tuple[tuple, str] | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") is not False:
            continue
        tag = release.get("tag_name")
        key = parse(tag)
        if key is None or (key[3] != (2,) and mine[3] == (2,)) or key <= mine:
            continue
        if best is None or key > best[0]:
            best = (key, plain(tag))
    return best[1] if best else None


def enabled(store) -> bool:
    value = store.setting(SETTING)
    return value == "on" if value in ("on", "off") else is_frozen()


def _time(store, key: str) -> datetime | None:
    try:
        return datetime.fromisoformat(store.setting(key))
    except (TypeError, ValueError):
        return None


def due(store, now: datetime) -> bool:
    last = _time(store, ATTEMPTED_AT)
    return last is None or not timedelta(0) <= now - last < EVERY


def view(store, current: str) -> dict:
    """What Settings and the sidebar show; `latest` only while it is still newer than this build."""
    stored = store.setting(LATEST)
    newer = isinstance(stored, str) and (key := parse(stored)) is not None and (mine := parse(current)) is not None and key > mine
    checked = _time(store, CHECKED_AT)
    return {"enabled": enabled(store), "current": current, "checked_at": checked.isoformat() if checked else None,
            "latest": {"version": stored, "url": RELEASE_PAGE.format(version=stored)} if newer else None}


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, follow_redirects=False, timeout=TIMEOUT_SECONDS)


async def fetch(http: httpx.AsyncClient) -> object:
    async with http.stream("GET", RELEASES_URL) as response:
        if response.status_code != 200:
            raise ValueError(f"GitHub answered {response.status_code}")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > MAX_BYTES:
                raise ValueError("the release list is larger than 1 MB")
    releases = json.loads(bytes(body))
    if not isinstance(releases, list) or not all(isinstance(r, dict) and "tag_name" in r and "draft" in r for r in releases):
        raise ValueError("the answer is not a release list")
    return releases


class UpdateCheck:
    """One check at a time for this process's library. `make_client` opens the client of one check (tests pass a fake)."""

    def __init__(self, store, current: str, make_client: Callable[[], httpx.AsyncClient] = client,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.store, self.current, self.make_client, self.now = store, current, make_client, now
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._closed = False

    async def check_if_due(self) -> None:
        async with self._lock:
            if not enabled(self.store) or parse(self.current) is None or not due(self.store, self.now()):
                return
            self.store.set_setting(ATTEMPTED_AT, self.now().isoformat())
            try:
                async with self.make_client() as http:
                    releases = await fetch(http)
            except (httpx.HTTPError, ValueError) as exc:
                log.info("Version check: no answer from GitHub (%s)", type(exc).__name__)
                return
            found = newest(releases, self.current)
            self.store.set_setting(CHECKED_AT, self.now().isoformat())
            self.store.set_setting(LATEST, found or "")

    def soon(self) -> None:
        """Check now in the background when one is due (the switch was just turned on)."""
        if not self._closed and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self.check_if_due())

    async def run_forever(self, stop: asyncio.Event) -> None:
        wait = FIRST_DELAY_SECONDS
        while True:
            try:
                await asyncio.wait_for(stop.wait(), wait)
                return
            except TimeoutError:
                pass
            try:
                await self.check_if_due()
            except Exception:  # noqa: BLE001 - a broken check never ends the loop or the app
                log.exception("Version check failed")
            wait = WAKE_SECONDS

    async def close(self, loop_task: asyncio.Task) -> None:
        """Shutdown: no further check starts, and the loop and a check in flight are cancelled, never waited for."""
        self._closed = True
        tasks = [t for t in (loop_task, self._task) if t is not None and not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

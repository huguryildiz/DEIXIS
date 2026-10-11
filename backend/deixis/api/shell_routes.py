"""Small routes behind the app shell (parity slice S2): awaiting counts, the OS profile name, the institution proxy's
label and test, and the contact email setting.

Nothing here starts a run or writes evidence. The awaiting counts are read from the same derivations the research view
uses; the proxy test makes one request and states what it measured, two facts apart (the host answered; Scopus grants
its full view), never a combined verdict.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.config import CONTACT_EMAIL_SETTING
from deixis.documents import fetch
from deixis.domain import proxy
from deixis.providers import scopus
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import now
from deixis.workflow import queue, waiting
from deixis.workflow.store import Store

PROXY_LABEL_SETTING = "institution_proxy_label"
PROXY_TEST_SETTING = "institution_proxy_test"
PROXY_TEST_SECONDS = 10.0
LABEL_MAX = 80
EMAIL_MAX = 254
EMAIL_SHAPE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")


# ---- F1: awaiting counts ---------------------------------------------------------------------------------------------


class AwaitingCache:
    """Open queue rows and works waiting for the person's PDF, per research, kept by the research's latest event id.

    The queue's decisions and the PDFs a person attaches are written in the same transaction as their event (CLAUDE.md,
    Storage), so a count computed at event N is still true while the latest event is N. The two numbers stay apart."""

    def __init__(self) -> None:
        self._seen: dict[str, tuple[int, dict[str, int]]] = {}

    def counts(self, store: Store, research_id: str) -> dict[str, int]:
        latest = store.conn.execute("SELECT MAX(id) FROM events WHERE research_id = ?", (research_id,)).fetchone()[0] or 0
        held = self._seen.get(research_id)
        if held is not None and held[0] == latest:
            return dict(held[1])
        with queue._snapshot(store.conn):
            ctx = queue.context(store, research_id)
            value = {"queue": queue.queue_counts(store, research_id, ctx)["queue"],
                     "pdf": len(waiting.for_context(ctx)[1])}
        self._seen[research_id] = (latest, value)
        return dict(value)

    def annotate(self, store: Store, researches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in researches:
            item["awaiting"] = self.counts(store, item["id"])
        listed = {item["id"] for item in researches}
        for gone in [rid for rid in self._seen if rid not in listed]:
            del self._seen[gone]
        return researches


# ---- F2: the name of the OS account ----------------------------------------------------------------------------------


def _gecos_name() -> str:
    if sys.platform == "win32":
        return ""
    import pwd
    try:
        return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    except KeyError:
        return ""


def _id_name() -> str:
    """macOS `id -F` prints the account's full name when the passwd entry carries none."""
    if sys.platform != "darwin":
        return ""
    try:
        done = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _login_name() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no user name at all (a container without a passwd entry)
        return ""


def initials_of(name: str) -> str:
    words = [word for word in re.split(r"[\s._-]+", name) if word[:1].isalpha()]
    if not words:
        return ""
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def profile() -> dict[str, str]:
    """The person's name as the operating system has it. Read each time, never stored, never sent anywhere."""
    name = _gecos_name() or _id_name() or _login_name()
    return {"full_name": name, "initials": initials_of(name)}


# ---- F3: the proxy's label and test ----------------------------------------------------------------------------------


class ProxyLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=400)


def proxy_host(address: str | None) -> str | None:
    if not address:
        return None
    try:
        return urlsplit(address.replace(proxy.PLACEHOLDER, "x")).hostname
    except ValueError:
        return None


def proxy_root(address: str) -> str:
    """The proxy host's own address, scheme and host (and port) with no path: the one thing the test asks."""
    parts = urlsplit(address)
    return f"{parts.scheme}://{parts.netloc}/"


async def proxy_answer(client: httpx.AsyncClient, address: str) -> dict[str, Any]:
    """One GET of the proxy host through `fetch`'s protections: a public address only, the checked address pinned, one
    request at a time to the host. The answer is read from the status line and headers; no body is read and no redirect
    followed, so the size limit of `fetch` is never reached and nothing beyond the proxy host is asked."""
    url = proxy_root(address)
    out: dict[str, Any] = {"proxy_reachable": False, "proxy_http_status": None, "proxy_error": None, "proxy_error_detail": None}
    try:
        async with asyncio.timeout(PROXY_TEST_SECONDS):
            async with fetch.host_gate(url):
                target, headers, extensions = fetch._pinned_request(url, await fetch.check_public_url(url))
                async with client.stream("GET", target, headers=headers, extensions=extensions, follow_redirects=False,
                                         timeout=PROXY_TEST_SECONDS) as response:
                    out["proxy_reachable"], out["proxy_http_status"] = True, response.status_code
    except fetch.BlockedUrl as exc:
        # An address that does not resolve did not answer; a refused (non-public) address was never asked.
        out["proxy_error"] = "unresolved" if "does not resolve" in str(exc) else "blocked_url"
        out["proxy_error_detail"] = str(exc)
    except (TimeoutError, httpx.TimeoutException):
        out["proxy_error"] = "timeout"
    except httpx.HTTPError as exc:
        out["proxy_error"] = "failed"
        out["proxy_error_detail"] = type(exc).__name__
    return out


async def scopus_fact(client: httpx.AsyncClient) -> tuple[str, bool]:
    """The existing Scopus COMPLETE-view check (scopus.py), as one of three words, and whether Scopus has a key."""
    key = CONNECTORS["scopus"].api_key()
    if not key:
        return "could_not_check", False
    entitled = await scopus.complete_view_entitled(client, key)
    return {True: "confirmed", False: "not_confirmed", None: "could_not_check"}[entitled], True


def proxy_settings(store: Store, route: str | None = None) -> dict[str, Any]:
    address = store.setting(proxy.SETTING)
    default = proxy_host(address)
    label = store.setting(PROXY_LABEL_SETTING)
    test = store.setting(PROXY_TEST_SETTING)
    return {"address": address, "label": label or default, "label_default": default, "label_is_default": not label,
            "test": test,
            # A test belongs to the address and the network route it was made on; the person is told when either moved.
            "test_is_current": bool(test) and test.get("address") == address and test.get("route") == route}


# ---- F15: the contact email ------------------------------------------------------------------------------------------


class ContactEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = Field(default=None, max_length=400)


def contact_email_view(store: Store) -> dict[str, Any]:
    stored = store.setting(CONTACT_EMAIL_SETTING) or None
    from_env = bool(os.environ.get("DEIXIS_CONTACT_EMAIL"))
    return {"email": stored, "environment_set": from_env,
            "source": "setting" if stored else ("environment" if from_env else None)}


def register_shell_routes(app) -> None:
    app.state.awaiting = AwaitingCache()

    def store_of(request: Request) -> Store:
        return request.app.state.store

    async def settings_view(request: Request) -> dict[str, Any]:
        # The store belongs to the event-loop thread; only the route lookup (a name resolution) goes to a thread.
        store = store_of(request)
        return proxy_settings(store, await asyncio.to_thread(scopus.route_source) if store.setting(PROXY_TEST_SETTING) else None)

    @app.get("/api/profile")
    async def get_profile() -> dict[str, str]:
        return await asyncio.to_thread(profile)

    @app.get("/api/institution-proxy/settings")
    async def get_proxy_settings(request: Request) -> dict[str, Any]:
        return await settings_view(request)

    @app.put("/api/institution-proxy/label")
    async def put_proxy_label(body: ProxyLabel, request: Request) -> dict[str, Any]:
        label = " ".join((body.label or "").split())
        if len(label) > LABEL_MAX:
            raise HTTPException(422, f"The name must be at most {LABEL_MAX} characters")
        store_of(request).set_setting(PROXY_LABEL_SETTING, label or None)
        return await settings_view(request)

    @app.post("/api/institution-proxy/test")
    async def test_institution_proxy(request: Request) -> dict[str, Any]:
        store = store_of(request)
        address = store.setting(proxy.SETTING)
        if not address:
            raise HTTPException(422, "No institution proxy address is set")
        client = request.app.state.http
        reached = await proxy_answer(client, address)
        scopus_complete, scopus_configured = await scopus_fact(client)
        route = await asyncio.to_thread(scopus.route_source)
        store.set_setting(PROXY_TEST_SETTING, reached | {
            "scopus_complete": scopus_complete, "scopus_configured": scopus_configured,
            "address": address, "route": route, "tested_at": now()})
        return proxy_settings(store, route)

    @app.get("/api/contact-email")
    async def get_contact_email(request: Request) -> dict[str, Any]:
        return contact_email_view(store_of(request))

    @app.put("/api/contact-email")
    async def put_contact_email(body: ContactEmail, request: Request) -> dict[str, Any]:
        email = (body.email or "").strip()
        if email and (len(email) > EMAIL_MAX or not EMAIL_SHAPE.match(email)):
            raise HTTPException(422, "That is not an email address")
        store_of(request).set_setting(CONTACT_EMAIL_SETTING, email or None)
        return contact_email_view(store_of(request))

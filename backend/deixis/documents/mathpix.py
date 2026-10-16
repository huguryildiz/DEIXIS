"""Mathpix's image-to-LaTeX API for numbered display equations (D40): the key pair, one request per crop, the key test.

The pair is one keychain item, `MATHPIX_CREDENTIALS`, holding `{"app_id", "app_key", "revision"}` written in one write, so
no mixed pair can exist; a value that does not parse is treated as absent. Every request asks Mathpix not to keep the image
for its own training (`metadata.improve_mathpix: false`); the account's own data settings are outside DEIXIS's control.
A request has a 30 s deadline over connect, send and read, and its body is read in pieces and cut past 1 MB. Requests from
every DEIXIS process on one data directory go one at a time behind a file lock.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from deixis.documents import arxiv_source
from deixis.storage.db import now

ENGINE = "mathpix"
VERSION = "mathpix-v1"
ENV = "MATHPIX_CREDENTIALS"
TEXT_URL = "https://api.mathpix.com/v3/text"
USAGE_URL = "https://api.mathpix.com/v3/ocr-usage"
TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 1024 * 1024
LOCK_WAIT_SECONDS = 120.0
REJECTED = (401, 403)  # both are taken as a refused key pair; which one Mathpix sends was not checked live


@dataclass(frozen=True)
class Pair:
    app_id: str
    app_key: str
    revision: str


def read_pair(value: str | None = None) -> Pair | None | str:
    """The saved pair, None when nothing is saved, or "unreadable" when the saved value is not the pair's JSON."""
    value = os.environ.get(ENV) if value is None else value
    if not value:
        return None
    try:
        data = json.loads(value)
    except ValueError:
        return "unreadable"
    if not (isinstance(data, dict) and all(isinstance(data.get(k), str) and data[k] for k in ("app_id", "app_key", "revision"))):
        return "unreadable"
    return Pair(data["app_id"], data["app_key"], data["revision"])


def encode_pair(app_id: str, app_key: str) -> str:
    return json.dumps({"app_id": app_id, "app_key": app_key, "revision": uuid.uuid4().hex})


def headers(pair: Pair) -> dict[str, str]:
    return {"app_id": pair.app_id, "app_key": pair.app_key}


def request_body(data_url: str) -> dict[str, Any]:
    return {"src": data_url, "formats": ["latex_styled"], "rm_spaces": True, "metadata": {"improve_mathpix": False}}


@dataclass
class Outcome:
    """`answered` (a JSON body), `error` (with `sent` saying whether the request reached Mathpix) or `unknown` (it may have
    been processed: a timeout or a connection lost after sending). `reason` names a failure: rate_limited, network,
    server_error, keys_rejected."""

    status: str
    http_status: int | None = None
    body: dict[str, Any] | None = None
    request_id: str | None = None
    reason: str | None = None
    sent: bool = True


async def send(client: httpx.AsyncClient, pair: Pair, data_url: str) -> Outcome:
    """One request for one crop. Cancellation propagates; the caller records the row as unknown."""
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with client.stream("POST", TEXT_URL, json=request_body(data_url), headers=headers(pair),
                                     timeout=TIMEOUT_SECONDS) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return Outcome("error", response.status_code, reason="server_error")
    except UnicodeEncodeError:  # a key pair a header cannot carry; nothing was sent
        return Outcome("error", reason="keys_rejected", sent=False)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return Outcome("error", reason="network", sent=False)
    except (TimeoutError, httpx.TimeoutException, httpx.TransportError):
        return Outcome("unknown", reason="network")
    code = response.status_code
    if code in REJECTED:
        return Outcome("error", code, reason="keys_rejected")
    if code == 429:
        return Outcome("error", code, reason="rate_limited")
    if code != 200:
        return Outcome("error", code, reason="server_error")
    try:
        parsed = json.loads(bytes(body))
    except ValueError:
        return Outcome("error", code, reason="server_error")
    if not isinstance(parsed, dict):
        return Outcome("error", code, reason="server_error")
    return Outcome("answered", code, parsed, parsed.get("request_id") if isinstance(parsed.get("request_id"), str) else None)


async def test_pair(client: httpx.AsyncClient, app_id: str, app_key: str) -> dict[str, Any]:
    """The pair against Mathpix's usage API, which costs no OCR credit. It shows that the pair is accepted there, not that
    OCR credit is left."""
    try:
        response = await client.get(USAGE_URL, headers={"app_id": app_id, "app_key": app_key}, timeout=20)
    except (httpx.HTTPError, UnicodeEncodeError) as exc:  # the second: a header that is not ASCII is never sent
        return {"status": "failed", "detail": f"Could not reach Mathpix: {type(exc).__name__}", "http_status": None, "checked_at": now()}
    code = response.status_code
    if code == 200:
        return {"status": "ok", "detail": "Mathpix accepted the key pair.", "http_status": code, "checked_at": now()}
    if code in REJECTED:  # Mathpix's message is not passed on: it can quote part of the key
        return {"status": "rejected", "detail": f"Mathpix did not accept the key pair (HTTP {code}).", "http_status": code, "checked_at": now()}
    return {"status": "failed", "detail": f"Mathpix's usage API answered HTTP {code}.", "http_status": code, "checked_at": now()}


@asynccontextmanager
async def request_lock(directory: Path, wait: float = LOCK_WAIT_SECONDS) -> AsyncIterator[None]:
    """One request at a time per data directory, across processes (POSIX `flock`, Windows `msvcrt.locking`). Waiting
    longer than `wait` seconds raises TimeoutError."""
    path = directory / "mathpix" / ".request.lock"
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import msvcrt

        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        try:
            async with asyncio.timeout(wait):
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        await asyncio.sleep(arxiv_source.LOCK_POLL_SECONDS)
            try:
                yield
            finally:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)
        return
    async with asyncio.timeout(wait):
        fd = await arxiv_source.acquire_file_lock(path)
    try:
        yield
    finally:
        arxiv_source.release_file_lock(fd)

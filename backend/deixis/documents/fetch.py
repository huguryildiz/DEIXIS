"""Bounded retrieval of source files with private-network protection.

Every hop (including redirects) must use http(s) and resolve only to public
addresses. The connection is made to the address that was checked (the host name
is kept for the Host header and TLS verification), so a second DNS answer cannot
redirect it (DNS rebinding). Proxy settings from the environment are ignored,
because a proxy would make the connection itself.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_BYTES = 30 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 5
USER_AGENT = "DEIXIS/0.1 (local research workspace)"


@dataclass
class FetchResult:
    status: str  # ok, blocked_url, http_error, too_large, not_pdf, timeout, failed
    data: bytes = b""
    final_url: str | None = None
    media_type: str | None = None
    http_status: int | None = None
    error: str | None = None


class BlockedUrl(Exception):
    pass


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0].split("%")[0] for info in infos]


async def check_public_url(url: str) -> str:
    """Return the public address to connect to; refuse if any resolved address is not public."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedUrl(f"scheme {parts.scheme!r} not allowed")
    if not parts.hostname:
        raise BlockedUrl("missing host")
    if parts.username or parts.password:
        raise BlockedUrl("credentials in URL not allowed")
    try:
        addresses = await _resolve(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise BlockedUrl(f"host does not resolve: {exc}") from exc
    if not addresses:
        raise BlockedUrl("host does not resolve")
    for text in addresses:
        address = ipaddress.ip_address(text)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
            or (address.version == 6 and address.ipv4_mapped and not address.ipv4_mapped.is_global)
        ):
            raise BlockedUrl(f"{parts.hostname} resolves to non-public address")
    return addresses[0]


def _pinned_request(url: str, address: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """URL addressed to the checked IP, with the original host for the Host header and TLS server name."""
    parts = urlsplit(url)
    ip_host = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
    name = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    port = f":{parts.port}" if parts.port else ""
    pinned = urlunsplit((parts.scheme, ip_host + port, parts.path or "/", parts.query, ""))
    extensions = {"sni_hostname": parts.hostname} if parts.scheme == "https" else {}
    return pinned, {"Host": name + port}, extensions


async def fetch_pdf(url: str, client: httpx.AsyncClient | None = None) -> FetchResult:
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}, trust_env=False)
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                address = await check_public_url(current)
            except BlockedUrl as exc:
                return FetchResult("blocked_url", final_url=current, error=str(exc))
            target, headers, extensions = _pinned_request(current, address)
            async with client.stream("GET", target, headers=headers, extensions=extensions, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return FetchResult("http_error", final_url=current, http_status=response.status_code, error="redirect without location")
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    return FetchResult("http_error", final_url=current, http_status=response.status_code)
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                    return FetchResult("too_large", final_url=current, http_status=200)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        return FetchResult("too_large", final_url=current, http_status=200)
                    chunks.append(chunk)
                data = b"".join(chunks)
                media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if not data.startswith(b"%PDF-"):
                    return FetchResult("not_pdf", final_url=current, media_type=media_type, http_status=200)
                return FetchResult("ok", data=data, final_url=current, media_type="application/pdf", http_status=200)
        return FetchResult("http_error", final_url=current, error="too many redirects")
    except httpx.TimeoutException as exc:
        return FetchResult("timeout", final_url=url, error=type(exc).__name__)
    except httpx.HTTPError as exc:
        return FetchResult("failed", final_url=url, error=type(exc).__name__)
    finally:
        if own_client:
            await client.aclose()

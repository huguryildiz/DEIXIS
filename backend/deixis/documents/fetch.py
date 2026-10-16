"""Bounded retrieval of source files with private-network protection.

Every hop (including redirects) must use http(s) and resolve only to public
addresses. The connection is made to the address that was checked (the host name
is kept for the Host header and TLS verification), so a second DNS answer cannot
redirect it (DNS rebinding). Proxy settings from the environment are ignored,
because a proxy would make the connection itself.

A host is asked one request at a time (`host_gate`): the full-text retrieval run fetches several works at once
(slice 13e), and they must not arrive at one publisher side by side.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import socket
import weakref
import zlib
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_BYTES = 30 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
# The whole of one PDF fetch, redirects and body included: MAX_BYTES at a slow but working rate, not an idle wait.
PDF_DEADLINE_SECONDS = 120.0
MAX_REDIRECTS = 5
USER_AGENT = "DEIXIS/0.1 (local research workspace)"
PDF_ACCEPT = "application/pdf, */*;q=0.1"
# The Content-Encodings `_fetch` decodes itself, one layer at most; asked for by name so a client default cannot widen it.
DECODED_ENCODINGS = ("gzip", "x-gzip", "deflate")
ACCEPT_ENCODING = "gzip, deflate"
# How httpx (0.28, `_redirect_url`) words its refusal of a redirect Location it cannot parse; no other error starts so.
INVALID_LOCATION = "Invalid URL in location header"


def user_agent(email: str | None = None) -> str:
    """USER_AGENT with the contact address publishers can write to: `email` (the one set in Settings), else
    DEIXIS_CONTACT_EMAIL when that is set."""
    email = email or os.environ.get("DEIXIS_CONTACT_EMAIL")
    return f"DEIXIS/0.1 (local research workspace; mailto:{email})" if email else USER_AGENT


@dataclass
class FetchResult:
    status: str  # ok, blocked_url, http_error, too_large, not_pdf, timeout, failed
    data: bytes = b""
    final_url: str | None = None
    media_type: str | None = None
    http_status: int | None = None
    error: str | None = None
    content_disposition: str | None = None  # read by fetch_file only (the arXiv source's file name names its version)


class BlockedUrl(Exception):
    pass


# One lock per host name, held while a request to that host is in flight. Kept per event loop because an asyncio
# lock belongs to the loop it was first used on: the app runs one loop, so this is process-wide there, and a test
# that starts a second app gets its own locks instead of another loop's.
_host_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()


def host_gate(url: str) -> asyncio.Lock:
    """The lock a request to this URL's host holds while it is in flight, so one host is asked one thing at a time.

    Every request the retrieval run makes goes through it: an open link and each hop of its redirects here, and the
    DOI lookups in `acquisition`. A hop to another host takes that host's lock after the first one's is released.
    """
    gates = _host_gates.setdefault(asyncio.get_running_loop(), {})
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:  # an unclosed "[": check_public_url refuses it under this lock, so nothing is requested
        host = ""
    return gates.setdefault(host.lower(), asyncio.Lock())


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0].split("%")[0] for info in infos]


async def check_public_url(url: str) -> str:
    """Return the public address to connect to; refuse if any resolved address is not public."""
    try:
        # A URL that cannot be read raises here: ValueError from urllib (port out of range or not a number, an unclosed
        # or non-address "[...]"), InvalidURL or IDNAError (a ValueError) from httpx's own parser, which the request is
        # built with (a control character in the path or query, a host that is not valid IDNA). An empty or too-long
        # host label raises UnicodeError (a ValueError) later, in getaddrinfo's IDNA step.
        parts = urlsplit(url)
        port = parts.port
        host = _ascii_host(url)
    except (ValueError, httpx.InvalidURL) as exc:
        raise BlockedUrl(f"not a valid URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise BlockedUrl(f"scheme {parts.scheme!r} not allowed")
    if not parts.hostname:
        raise BlockedUrl("missing host")
    if parts.username or parts.password:
        raise BlockedUrl("credentials in URL not allowed")
    try:
        addresses = await _resolve(host, port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise BlockedUrl(f"host does not resolve: {exc}") from exc
    except ValueError as exc:
        raise BlockedUrl(f"not a valid URL: {exc}") from exc
    if not addresses:
        raise BlockedUrl("host does not resolve")
    for text in addresses:
        address = ipaddress.ip_address(text)
        if (
            not address.is_global  # also the shared-address range 100.64.0.0/10, which is neither private nor public
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
            or (address.version == 6 and address.ipv4_mapped and not address.ipv4_mapped.is_global)
        ):
            raise BlockedUrl(f"{parts.hostname} resolves to non-public address")
    return addresses[0]


def _inflater(encoding: str) -> Callable[[bytes, int], bytes]:
    """One gzip or deflate layer, decoded as it arrives: each call returns at most `limit` (>= 1) bytes, so a small body
    that inflates to gigabytes is never held. Output shorter than `limit` means all input was used; a cut at `limit` is
    refused by the caller, so the decoder's leftover input is never read and needs no flush. "deflate" is sent both
    zlib-wrapped and raw: as in httpx, a first chunk that is not zlib is read again as raw deflate."""
    decoder = zlib.decompressobj(zlib.MAX_WBITS if encoding == "deflate" else zlib.MAX_WBITS | 16)
    first = True

    def inflate(data: bytes, limit: int) -> bytes:
        nonlocal decoder, first
        retry, first = first and encoding == "deflate", False
        try:
            return decoder.decompress(data, limit)
        except zlib.error as exc:
            if retry:
                decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                return inflate(data, limit)
            raise httpx.DecodingError(str(exc)) from exc

    return inflate


def _ascii_host(url: str) -> str:
    """The host as it goes on the wire: an internationalized name in its IDNA (punycode) form, as httpx encodes it.
    httpx checks a non-ASCII name when it encodes it; an "xn--" label is checked here, by decoding it back."""
    parsed = httpx.URL(url)
    parsed.host  # raises IDNAError (a ValueError) for an "xn--" label that is not valid punycode
    return parsed.raw_host.decode("ascii")


def _pinned_request(url: str, address: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """URL addressed to the checked IP, with the original host for the Host header and TLS server name, both in the
    host's ASCII form (a header and the TLS server name carry no other)."""
    parts = urlsplit(url)
    host = _ascii_host(url)
    ip_host = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
    name = f"[{host}]" if ":" in host else host
    port = f":{parts.port}" if parts.port else ""
    pinned = urlunsplit((parts.scheme, ip_host + port, parts.path or "/", parts.query, ""))
    extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
    return pinned, {"Host": name + port}, extensions


async def _fetch(url: str, client: httpx.AsyncClient | None, deadline: float, *, accept: str | None = None, gate: Any = None,
                 admit: Callable[[httpx.Response, str], FetchResult | None] | None = None,
                 finish: Callable[[httpx.Response, bytes, str], FetchResult]) -> FetchResult:
    """The protections both fetches share: public addresses only, the checked address pinned, at most MAX_REDIRECTS
    redirects, MAX_BYTES, `host_gate` and one `asyncio.timeout(deadline)` over the whole fetch.

    `admit` reads a 200 response's headers before the body and may refuse it; `finish` turns the body into the
    result. A failure names the URL being read when it happened, after any redirect. `gate` is fetch_file's."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS, headers={"User-Agent": user_agent()}, trust_env=False)
    current = url
    try:
        if gate is not None:
            await gate.before()
        first = True
        async with asyncio.timeout(deadline):
            for _ in range(MAX_REDIRECTS + 1):
                if gate is not None and not first:
                    await gate.before()
                first = False
                try:
                    # One request to a host at a time; a redirect to another host takes that host's lock after this one.
                    async with host_gate(current):
                        try:
                            address = await check_public_url(current)
                        except BlockedUrl as exc:
                            return FetchResult("blocked_url", final_url=current, error=str(exc))
                        target, headers, extensions = _pinned_request(current, address)
                        headers["Accept-Encoding"] = ACCEPT_ENCODING
                        if accept is not None:
                            headers["Accept"] = accept
                        request = client.build_request("GET", target, headers=headers, extensions=extensions)
                        try:
                            response = await client.send(request, stream=True, follow_redirects=False)
                        except (httpx.RemoteProtocolError, ValueError) as exc:
                            # httpx reads a redirect's Location itself while sending, before the response comes back:
                            # one its parser cannot read is RemoteProtocolError("Invalid URL in location header: ..."),
                            # an "xn--" host that is not valid punycode IDNAError (a ValueError). That hop is refused
                            # like a malformed URL; any other protocol error keeps its own result below.
                            if isinstance(exc, httpx.RemoteProtocolError) and not str(exc).startswith(INVALID_LOCATION):
                                raise
                            return FetchResult("blocked_url", final_url=current, error=f"not a valid URL: {exc}")
                        async with contextlib.aclosing(response):
                            if response.is_redirect:
                                location = response.headers.get("location")
                                if not location:
                                    return FetchResult("http_error", final_url=current, http_status=response.status_code, error="redirect without location")
                                try:
                                    current = urljoin(current, location)
                                except ValueError as exc:  # urllib reads "[...]" more strictly than httpx's own parser
                                    return FetchResult("blocked_url", final_url=location, error=f"not a valid URL: {exc}")
                                continue
                            if response.status_code != 200:
                                return FetchResult("http_error", final_url=current, http_status=response.status_code)
                            refused = admit(response, current) if admit is not None else None
                            if refused is not None:
                                return refused
                            declared = response.headers.get("content-length")
                            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                                return FetchResult("too_large", final_url=current, http_status=200)
                            encoding = response.headers.get("content-encoding", "")
                            layers = [e for e in (part.strip().lower() for part in encoding.split(",")) if e and e != "identity"]
                            if len(layers) > 1 or (layers and layers[0] not in DECODED_ENCODINGS):
                                return FetchResult("failed", final_url=current, http_status=200,
                                                   error=f"content encoding {encoding!r} not accepted")
                            if response.is_stream_consumed:
                                # Only a body given to httpx.Response as bytes (a mock transport): already in memory,
                                # read and decoded by httpx itself. A network response always arrives as a stream.
                                if len(response.content) > MAX_BYTES:
                                    return FetchResult("too_large", final_url=current, http_status=200)
                                return finish(response, response.content, current)
                            inflate = _inflater(layers[0]) if layers else None
                            # Raw bytes, decoded here: httpx would inflate each network chunk whole, every stacked
                            # layer at once, before the size could be counted. At most one byte past MAX_BYTES is
                            # ever decoded.
                            chunks, size = [], 0
                            async for raw in response.aiter_raw():
                                chunk = inflate(raw, MAX_BYTES + 1 - size) if inflate else raw
                                size += len(chunk)
                                if size > MAX_BYTES:
                                    return FetchResult("too_large", final_url=current, http_status=200)
                                chunks.append(chunk)
                            return finish(response, b"".join(chunks), current)
                finally:
                    if gate is not None:
                        gate.after()
            return FetchResult("http_error", final_url=current, error="too many redirects")
    except TimeoutError:
        return FetchResult("timeout", final_url=current, error="deadline")
    except httpx.TimeoutException as exc:
        return FetchResult("timeout", final_url=current, error=type(exc).__name__)
    except httpx.HTTPError as exc:
        return FetchResult("failed", final_url=current, error=type(exc).__name__)
    finally:
        if own_client:
            await client.aclose()


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


async def fetch_pdf(url: str, client: httpx.AsyncClient | None = None, deadline: float = PDF_DEADLINE_SECONDS) -> FetchResult:
    """A PDF, judged by its first bytes rather than its declared type. The whole fetch ends at `deadline`."""
    def finish(response: httpx.Response, data: bytes, current: str) -> FetchResult:
        if not data.startswith(b"%PDF-"):
            return FetchResult("not_pdf", final_url=current, media_type=_media_type(response), http_status=200)
        return FetchResult("ok", data=data, final_url=current, media_type="application/pdf", http_status=200)

    return await _fetch(url, client, deadline, accept=PDF_ACCEPT, finish=finish)


async def fetch_file(url: str, media_types: tuple[str, ...], gate: Any = None, client: httpx.AsyncClient | None = None,
                     deadline: float = TIMEOUT_SECONDS) -> FetchResult:
    """A file of one of `media_types`, through fetch_pdf's protections (`_fetch`).

    `gate` (the arXiv source route, D104) is called before and after every HTTP request, redirect hops included:
    `await gate.before()` may wait and stamps the request's start, `gate.after()` stamps its end. The whole fetch, from
    the first address check to the last byte and including the gate's waits between hops, runs inside one
    `asyncio.timeout(deadline)`; the gate's wait before the first hop is outside it. Past the deadline the stream is
    closed and the result is `timeout`."""
    def admit(response: httpx.Response, current: str) -> FetchResult | None:
        media_type = _media_type(response)
        if media_type not in media_types:
            return FetchResult("wrong_type", final_url=current, media_type=media_type, http_status=200)
        return None

    def finish(response: httpx.Response, data: bytes, current: str) -> FetchResult:
        return FetchResult("ok", data=data, final_url=current, media_type=_media_type(response), http_status=200,
                           content_disposition=response.headers.get("content-disposition"))

    return await _fetch(url, client, deadline, gate=gate, admit=admit, finish=finish)

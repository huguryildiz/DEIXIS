"""The institution's proxy address and the links it builds (slice 18a, SW10.4).

Pure: no database and no network. DEIXIS never sends a request through the proxy; it only writes the link the
person's browser opens, where the institution's own login happens. Two forms are accepted:

- a template holding `{url}`, where the whole target address is percent-encoded and put in its place;
- a prefix such as `https://proxy.example.edu/login?url=`, to which the target is appended as it is, the way EZproxy
  expects it. A target holding `&` or `#` would lose its query or fragment to the proxy's own address, so such a
  target is appended percent-encoded instead.

Only `https` addresses are kept, and an address carrying a user name or password is refused: the address is stored in
`app_settings` and shown on screen, so it must never hold a credential.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

PLACEHOLDER = "{url}"
MAX_LENGTH = 2000
SETTING = "institution_proxy"


class ProxyRefused(ValueError):
    """The address cannot be a proxy address; the message says why, for the person to read."""


def validate(address: str | None) -> str | None:
    """The address to store, or None when it is empty (links then open directly)."""
    address = (address or "").strip()
    if not address:
        return None
    if len(address) > MAX_LENGTH:
        raise ProxyRefused("The proxy address is too long")
    if any(ch.isspace() or ord(ch) < 32 for ch in address):
        raise ProxyRefused("The proxy address must not contain spaces")
    if address.count(PLACEHOLDER) > 1:
        raise ProxyRefused("The proxy address may hold {url} only once")
    # A browser never sends a fragment: a target put after `#` would not reach the proxy at all.
    if "#" in address:
        raise ProxyRefused("The proxy address must not contain a # fragment")
    try:
        parts = urlsplit(address.replace(PLACEHOLDER, "x"))
        netloc = urlsplit(address).netloc
        hostname = parts.hostname
    except ValueError:
        raise ProxyRefused("The proxy address is not a valid address") from None
    if parts.scheme != "https":
        raise ProxyRefused("The proxy address must start with https://")
    if "@" in parts.netloc:
        raise ProxyRefused("The proxy address must not contain a user name or password")
    if not hostname or PLACEHOLDER in netloc:
        raise ProxyRefused("The proxy address has no host")
    return address


def openable(target: str | None) -> bool:
    """Whether a stored link may be put in front of the person: an http(s) address with a host and no space.

    Landing pages and DOIs come from provider records, which are untrusted: a `javascript:` or `data:` address is
    never turned into a link.
    """
    if not target or any(ch.isspace() or ord(ch) < 32 for ch in target):
        return False
    try:
        parts = urlsplit(target)
        return parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:  # a malformed address from a provider record (`https://[bad`) is not a link
        return False


def doi_url(doi: str | None) -> str | None:
    """The DOI's resolver address. `<`, `>`, `;`, `#`, `&` and the like are percent-encoded; `/` is kept."""
    doi = (doi or "").strip()
    return f"https://doi.org/{quote(doi, safe='/')}" if doi else None


def link(target: str | None, proxy: str | None) -> str | None:
    """The address the person's browser opens for `target`: through the proxy when one is set, else directly."""
    if not openable(target):
        return None
    assert target is not None
    if not proxy:
        return target
    if PLACEHOLDER in proxy:
        return proxy.replace(PLACEHOLDER, quote(target, safe=""))
    return proxy + (quote(target, safe="") if "&" in target or "#" in target else target)

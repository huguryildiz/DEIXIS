"""Read-only import of one collection from the user's Zotero library (D16).

Not a search connector: the model never queries it. Two access paths serve the same Zotero Web API v3 JSON:

- `local`: the Zotero desktop app's local API at http://127.0.0.1:23119/api/users/0. Reads need no key; the user turns
  it on in Zotero (Settings → Advanced → "Allow other applications on this computer to communicate with Zotero"),
  otherwise it answers 403. It returns every result at once. An attachment's `/file` redirects to a file:// URL.
- `web`: https://api.zotero.org/users/<ZOTERO_LIBRARY_ID> (or groups/<id> with ZOTERO_LIBRARY_TYPE=group) with
  ZOTERO_API_KEY, read in pages of at most 100
  (`Total-Results` header). `/file` redirects to a signed storage URL, which is fetched without the key through the
  public-address PDF fetch; a file is there only when the user syncs files to Zotero storage.

Only GET requests are sent. The local path reads only the signed-in user's library. Checked on 2026-09-15: the web shapes (collections,
collection items including their child attachments, a 302 from `/file`) against the public library users/475425
without a key; the local behavior from Zotero's server_localAPI.js and its local API documentation, because Zotero is
not installed on the development machine.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit
from urllib.request import url2pathname

import httpx

from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord, SearchOutcome, normalize_doi, send, year_of

LOCAL_BASE = "http://127.0.0.1:23119/api/users/0"
WEB_BASE = "https://api.zotero.org/{prefix}"
WEB_PAGE_SIZE = 100
MAX_IMPORT_ITEMS = 100
MAX_LOCAL_PDF_BYTES = 50 * 1024 * 1024  # the upload limit: a local file is the user's own copy
ABSTRACT_ORIGIN = "zotero_abstract_note"
VENUE_FIELDS = ("publicationTitle", "proceedingsTitle", "bookTitle", "conferenceName", "repository", "university",
                "institution", "publisher", "websiteTitle")
_ENABLE = "Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”"
LOCAL_NOT_RUNNING = f"Zotero is not answering on this computer. Open Zotero 7 or later and turn on {_ENABLE}."
LOCAL_TURNED_OFF = f"Zotero is running but its local API is off. Turn on {_ENABLE}."


class ZoteroError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Library:
    source: str  # "local" or "web"
    base: str
    headers: dict[str, str]
    access_mode: str
    secret: str | None
    file_link_modes: tuple[str, ...]  # attachment link modes whose file this path can read


@dataclass
class ZoteroItem:
    record: ProviderRecord
    pdf_key: str | None = None
    pdf_filename: str | None = None
    pdf_problem: str | None = None  # the item has a PDF attachment that this access path cannot read


def library(source: str) -> Library:
    if source == "local":
        return Library("local", LOCAL_BASE, {"Zotero-API-Version": "3"}, "local_app", None,
                       ("imported_file", "imported_url", "linked_file"))
    # The variable names pyzotero uses; ZOTERO_LIBRARY_TYPE is "user" (the default) or "group".
    key, library_id = os.environ.get("ZOTERO_API_KEY"), os.environ.get("ZOTERO_LIBRARY_ID", "")
    library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user").strip().lower()
    if not key or not library_id.isdigit() or library_type not in ("user", "group"):
        raise ZoteroError("Set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID (plus ZOTERO_LIBRARY_TYPE=group for a group library) in .env"
                          " to use zotero.org. A user library's ID is the number zotero.org shows where you create the key.", 422)
    # A linked file stays on the computer that linked it; zotero.org stores only imported files.
    return Library("web", WEB_BASE.format(prefix=f"{library_type}s/{library_id}"), {"Zotero-API-Version": "3", "Zotero-API-Key": key},
                   "api_key", key, ("imported_file", "imported_url"))


async def collections(client: httpx.AsyncClient, lib: Library) -> list[dict[str, str]]:
    """The library's collections, each named by its path ("Thesis / Chapter 2") and sorted by that name."""
    rows = {r["data"]["key"]: r["data"] for r in await _get_all(client, lib, "/collections")}

    def path(key: str) -> str:
        data = rows[key]
        name = str(data.get("name") or "(unnamed)")
        return f"{path(data['parentCollection'])} / {name}" if data.get("parentCollection") in rows else name

    return sorted(({"key": key, "name": path(key)} for key in rows), key=lambda c: c["name"].casefold())


async def collection_items(client: httpx.AsyncClient, lib: Library, collection_key: str) -> tuple[list[ZoteroItem], list[dict[str, Any]]]:
    """The collection's own items (not its subcollections') with each one's first readable PDF, and the raw rows."""
    rows = await _get_all(client, lib, f"/collections/{collection_key}/items")
    children: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["data"].get("parentItem"):
            children.setdefault(row["data"]["parentItem"], []).append(row["data"])
    items = []
    for row in rows:
        data = row["data"]
        if data.get("parentItem") or data.get("itemType") in ("note", "annotation"):
            continue
        standalone = data.get("itemType") == "attachment"
        attachments = [data] if standalone else sorted(children.get(data["key"], []), key=lambda a: a.get("dateAdded", ""))
        pdfs = [a for a in attachments if a.get("contentType") == "application/pdf"]
        if standalone and not pdfs:
            continue  # a saved link or web snapshot without bibliographic data
        item = ZoteroItem(_record(row, lib.source, standalone))
        readable = [a for a in pdfs if a.get("linkMode") in lib.file_link_modes]
        if readable:
            item.pdf_key, item.pdf_filename = readable[0]["key"], readable[0].get("filename")
        elif pdfs:
            item.pdf_problem = ("its PDF is a linked file, which zotero.org does not store" if lib.source == "web"
                                else f"its PDF attachment has no file ({pdfs[0].get('linkMode')})")
        items.append(item)
    if len(items) > MAX_IMPORT_ITEMS:
        raise ZoteroError(f"This collection has {len(items)} items; DEIXIS imports at most {MAX_IMPORT_ITEMS} at a time.", 422)
    return items, rows


async def pdf_bytes(client: httpx.AsyncClient, lib: Library, attachment_key: str,
                    fetch_pdf: Callable[[str], Awaitable[FetchResult]]) -> bytes:
    """The attachment's PDF. The zotero.org storage URL is fetched without the API key."""
    try:
        response = await client.get(f"{lib.base}/items/{attachment_key}/file", headers=lib.headers,
                                    follow_redirects=False, timeout=30.0)
    except httpx.HTTPError as exc:
        raise ZoteroError(f"the file request failed ({type(exc).__name__})") from exc
    location = response.headers.get("location") if response.is_redirect else None
    if not location:
        if lib.source == "web" and response.status_code == 404:
            raise ZoteroError("the file is not stored on zotero.org")
        raise ZoteroError(f"Zotero did not return the file (HTTP {response.status_code})")
    if lib.source == "web":
        result = await fetch_pdf(location)
        if result.status != "ok":
            raise ZoteroError(f"the download from Zotero storage failed ({result.status.replace('_', ' ')})")
        return result.data
    return _read_local_pdf(location)


def _read_local_pdf(location: str) -> bytes:
    parts = urlsplit(location)
    if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
        raise ZoteroError("Zotero named a file location that is not on this computer")
    path = Path(url2pathname(parts.path))
    if not path.is_file():
        raise ZoteroError("the PDF file is missing from this computer")
    if path.stat().st_size > MAX_LOCAL_PDF_BYTES:
        raise ZoteroError("the PDF is larger than 50 MB")
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ZoteroError("the attachment is not a PDF")
    return data


def _record(row: dict[str, Any], source: str, standalone: bool) -> ProviderRecord:
    data = row["data"]
    creators = data.get("creators") or []
    people = [c for c in creators if c.get("creatorType") == "author"] or creators
    authors = [n for n in (str(c.get("name") or f"{c.get('firstName') or ''} {c.get('lastName') or ''}").strip() for c in people) if n]
    extra_doi = re.search(r"^\s*DOI:\s*(\S+)", str(data.get("extra") or ""), re.IGNORECASE | re.MULTILINE)
    abstract = str(data.get("abstractNote") or "").strip() or None
    return ProviderRecord(
        provider_record_id=f"{source}:{data['key']}",
        title=str(data.get("title") or "").strip() or "(untitled)",
        authors=authors,
        year=year_of(data.get("date")),
        venue=next((str(data[f]).strip() for f in VENUE_FIELDS if str(data.get(f) or "").strip()), None),
        publication_type=None if standalone else data.get("itemType"),
        doi=normalize_doi(data.get("DOI")) or normalize_doi(extra_doi.group(1) if extra_doi else None),
        landing_url=data.get("url") or None,
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label=None,  # Zotero does not record which version of a paper an item or its PDF is
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers={},
        raw=row,
        # The PDF's version is unknown, so the item never merges with a provider record that has the same DOI.
        merge_by_doi=False,
    )


def _error(lib: Library, outcome: SearchOutcome) -> ZoteroError:
    if lib.source == "local" and outcome.delivery_class == "before_send":
        return ZoteroError(LOCAL_NOT_RUNNING, 503)
    if lib.source == "local" and outcome.status == "auth_required":
        return ZoteroError(LOCAL_TURNED_OFF, 503)
    if outcome.status == "entitlement_missing":
        return ZoteroError("zotero.org did not accept ZOTERO_API_KEY for ZOTERO_LIBRARY_ID.")
    if outcome.status == "rate_limited":
        return ZoteroError("zotero.org is limiting requests. Try again in a few minutes.", 503)
    if outcome.http_status == 404:
        return ZoteroError("Zotero has no such collection in this library.", 404)
    return ZoteroError(f"The Zotero request failed ({outcome.http_status or outcome.error or outcome.status}).")


async def _get_all(client: httpx.AsyncClient, lib: Library, path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while True:
        params = {"limit": WEB_PAGE_SIZE, "start": len(rows)} if lib.source == "web" else {}
        response, outcome = await send(client, lib.base + path, params, lib.headers, f"GET Zotero {lib.source} {path}",
                                       lib.access_mode, secrets=(lib.secret,))
        if response is None:
            raise _error(lib, outcome)
        try:
            page = response.json()
        except ValueError:
            page = None
        if not isinstance(page, list) or not all(isinstance(r, dict) and isinstance(r.get("data"), dict) for r in page):
            raise ZoteroError("Zotero returned a response DEIXIS could not read.")
        rows += page
        total = response.headers.get("total-results", "")
        if lib.source == "local" or not page or not total.isdigit() or len(rows) >= int(total):
            return rows

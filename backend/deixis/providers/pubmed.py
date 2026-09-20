"""PubMed search adapter backed by NCBI Entrez E-utilities.

PubMed search is a two-request pipeline: ESearch returns ranked PMIDs and the
matching-record count, then EFetch returns the corresponding PubMed XML records.
An NCBI API key is optional; ``tool`` and the configured contact email identify
the client as requested by the E-utilities usage guidelines. PubMed supplies
bibliographic metadata and abstracts, but no version-labelled PDF, so this
adapter never attaches a file.

Paging (NLM E-utilities documentation, read 2026-09-21): ESearch pages with `retstart` and `retmax`; `retmax` reaches
100,000 UIDs and no maximum is documented for `retstart`. Paging follows the identifiers ESearch served, because
EFetch is a second request over those identifiers.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, next_offset, normalize_doi, page_offset, send, year_of

PROVIDER_ID = "pubmed"
BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SEARCH_URL = f"{BASE_URL}/esearch.fcgi"
FETCH_URL = f"{BASE_URL}/efetch.fcgi"
ABSTRACT_ORIGIN = "provider_pubmed"
RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining")
MAX_RESULTS = 100


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = re.sub(r"\s+", " ", "".join(element.itertext())).strip()
    return value or None


def _author(element: ET.Element) -> str | None:
    collective = _text(element.find("CollectiveName"))
    if collective:
        return collective
    return " ".join(filter(None, (_text(element.find("ForeName")), _text(element.find("LastName"))))) or None


def _abstract(article: ET.Element) -> str | None:
    parts = []
    for node in article.findall("Abstract/AbstractText"):
        value = _text(node)
        if not value:
            continue
        label = (node.get("Label") or "").strip()
        parts.append(f"{label}: {value}" if label and not value.lower().startswith(label.lower() + ":") else value)
    return "\n\n".join(parts) or None


def _record(node: ET.Element) -> ProviderRecord:
    citation = node.find("MedlineCitation")
    if citation is None:
        raise ValueError("PubmedArticle has no MedlineCitation")
    article = citation.find("Article")
    if article is None:
        raise ValueError("MedlineCitation has no Article")
    pmid = _text(citation.find("PMID"))
    if not pmid:
        raise ValueError("PubMed record has no PMID")

    ids = {
        str(identifier.get("IdType")): value
        for identifier in node.findall("PubmedData/ArticleIdList/ArticleId")
        if (value := _text(identifier)) and identifier.get("IdType")
    }
    doi = normalize_doi(ids.get("doi") or next(
        (_text(eid) for eid in article.findall("ELocationID") if eid.get("EIdType") == "doi"), None
    ))
    identifiers = {"pmid": pmid} | ({"doi": doi} if doi else {})
    abstract = _abstract(article)
    pub_date = article.find("Journal/JournalIssue/PubDate")
    publication_types = [_text(kind) for kind in article.findall("PublicationTypeList/PublicationType")]
    pages = _text(article.find("Pagination/MedlinePgn")) or next(
        (_text(eid) for eid in article.findall("ELocationID") if eid.get("EIdType") in ("page", "pii")), None
    )
    raw: dict[str, Any] = {
        "pmid": pmid,
        "article_ids": ids,
        "publication_status": _text(node.find("PubmedData/PublicationStatus")),
    }
    return ProviderRecord(
        provider_record_id=pmid,
        title=_text(article.find("ArticleTitle")) or "(untitled)",
        authors=[name for author in article.findall("AuthorList/Author") if (name := _author(author))],
        year=year_of(_text(pub_date.find("Year")) if pub_date is not None else None)
        or year_of(_text(pub_date.find("MedlineDate")) if pub_date is not None else None),
        venue=_text(article.find("Journal/Title")),
        publication_type=next((kind for kind in publication_types if kind), None),
        doi=doi,
        landing_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label="publishedVersion",
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=identifiers,
        raw=raw,
        volume=_text(article.find("Journal/JournalIssue/Volume")),
        issue=_text(article.find("Journal/JournalIssue/Issue")),
        pages=pages,
    )


def records_from_xml(value: str) -> list[ProviderRecord]:
    root = ET.fromstring(value)
    return [_record(node) for node in root.findall("PubmedArticle")]


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None, cursor: str | None = None) -> SearchOutcome:
    count = min(limit, MAX_RESULTS)
    offset = page_offset(cursor)
    common: dict[str, Any] = {"db": "pubmed", "tool": "DEIXIS"}
    if contact_email:
        common["email"] = contact_email
    if api_key:
        common["api_key"] = api_key
    access_mode = "api_key" if api_key else "keyless"
    search_description = (f"GET {SEARCH_URL} db=pubmed term={query!r} retmax={count}"
                          + (f" retstart={offset}" if cursor is not None else "") + f" access={access_mode}")
    esearch = {"term": query, "retmode": "json", "retmax": count, "sort": "relevance"}
    if cursor is not None:
        esearch["retstart"] = offset  # ESearch reaches record 9,999; the read limit stops well before that
    response, outcome = await send(
        client, SEARCH_URL, common | esearch, {}, search_description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
    )
    if response is None:
        return outcome
    try:
        search_payload = response.json()
        result = search_payload["esearchresult"]
        ids = [str(value) for value in result.get("idlist") or []]
        outcome.provider_total = int(result["count"])
        # Paging follows the identifiers the provider served, not the records efetch could be parsed into.
        if cursor is not None:
            outcome.next_cursor = next_offset(offset, len(ids), count, outcome.provider_total)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    if not ids:
        outcome.status, outcome.raw_payload = "zero_results", {"search": search_payload}
        return outcome

    fetch_description = f"GET {FETCH_URL} db=pubmed ids={len(ids)} retmode=xml access={access_mode}"
    fetched, fetch_outcome = await send(
        client, FETCH_URL, common | {"id": ",".join(ids), "retmode": "xml"}, {},
        fetch_description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
    )
    outcome.request_description = f"{search_description}; {fetch_description}"
    outcome.retries += fetch_outcome.retries
    if fetched is None:
        outcome.status = fetch_outcome.status
        outcome.delivery_class = fetch_outcome.delivery_class
        outcome.http_status = fetch_outcome.http_status
        outcome.rate_limit = fetch_outcome.rate_limit
        outcome.error = fetch_outcome.error
        outcome.raw_payload = {"search": search_payload}
        return outcome
    try:
        outcome.records = records_from_xml(fetched.text)
    except (ET.ParseError, ValueError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        outcome.raw_payload = {"search": search_payload, "fetch_xml": fetched.text}
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = {"search": search_payload, "fetch_xml": fetched.text}
    return outcome

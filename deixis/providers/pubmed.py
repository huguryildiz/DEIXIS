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

from deixis.providers.common import (MAX_RATE_LIMIT_RETRIES, ProviderRecord, SearchOutcome, keywords, next_offset,
                                     normalize_doi, page_offset, send, year_of)

PROVIDER_ID = "pubmed"
BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SEARCH_URL = f"{BASE_URL}/esearch.fcgi"
# The sorting setting every ESearch carries, whatever the query names: PubMed's own relevance order. Recorded with the
# search run, so a reader can tell this list is relevance-ordered without reading the adapter.
FIXED_SORT = "relevance"
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
        # Author keywords are the `NOTNLM` keyword lists of the citation. `MeshHeadingList` is NLM's controlled
        # vocabulary, and a `KeywordList` without an owner is NLM's too: the DTD's default for `Owner` is `NLM`
        # (pubmed_190101.dtd, read 2026-09-21), and `NLM-AUTO`, `NASA`, `PIP`, `KIE` and `HHS` are other indexers.
        author_keywords=keywords(_text(word) for group in citation.findall("KeywordList")
                                 if group.get("Owner") == "NOTNLM" for word in group.findall("Keyword")),
        volume=_text(article.find("Journal/JournalIssue/Volume")),
        issue=_text(article.find("Journal/JournalIssue/Issue")),
        pages=pages,
    )


def records_from_xml(value: str) -> list[ProviderRecord]:
    root = ET.fromstring(value)
    if root.tag != "PubmedArticleSet":
        raise ValueError("PubMed EFetch root must be PubmedArticleSet")
    return [_record(node) for node in root.findall("PubmedArticle")]


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None, cursor: str | None = None,
                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
                 year_range: str | None = None) -> SearchOutcome:
    """One page of an ESearch, then the EFetch of the records it named.

    `year_range` is the caller's publication-year bound, sent as ESearch's own `datetype` / `mindate` / `maxdate`
    rather than written into the query text, so the recorded query stays the one the plan froze. Both sides are
    always sent: a `mindate` without a `maxdate` is ignored (checked against ESearch on 10 Nov 2026 — 802 records
    unbounded, 802 with `mindate` alone, 360 with both).
    """
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
    esearch: dict[str, Any] = {"term": query, "retmode": "json", "retmax": count, "sort": FIXED_SORT}
    if year_range:
        lower, upper = year_range.split("-", 1)
        esearch |= {"datetype": "pdat", "mindate": lower, "maxdate": upper}
        search_description += f" datetype=pdat mindate={lower} maxdate={upper}"
    if cursor is not None:
        esearch["retstart"] = offset  # ESearch reaches record 9,999; the read limit stops well before that
    response, outcome = await send(
        client, SEARCH_URL, common | esearch, {}, search_description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
        max_rate_limit_retries=max_rate_limit_retries,
    )
    if response is None:
        return outcome
    try:
        search_payload = response.json()
        if not isinstance(search_payload, dict):
            raise TypeError("PubMed ESearch root must be an object")
        result = search_payload["esearchresult"]
        if result.get("idlist") is not None and (not isinstance(result["idlist"], list)
                                   or any(not isinstance(value, str) for value in result["idlist"])):
            raise TypeError("PubMed esearchresult.idlist must be a list of strings")
        ids = [str(value) for value in result.get("idlist") or []]
        outcome.provider_total = int(result["count"])
        # Paging follows the identifiers the provider served, not the records efetch could be parsed into.
        if cursor is not None:
            outcome.next_cursor = next_offset(offset, len(ids), count, outcome.provider_total)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    if not ids:
        outcome.status, outcome.raw_payload = "zero_results", {"search": search_payload}
        return outcome

    fetch_description = f"GET {FETCH_URL} db=pubmed ids={len(ids)} retmode=xml access={access_mode}"
    fetched, fetch_outcome = await send(
        client, FETCH_URL, common | {"id": ",".join(ids), "retmode": "xml"}, {},
        fetch_description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
        max_rate_limit_retries=max_rate_limit_retries,
    )
    outcome.request_description = f"{search_description}; {fetch_description}"
    outcome.retries += fetch_outcome.retries
    if fetched is None:
        outcome.status = fetch_outcome.status
        outcome.delivery_class = fetch_outcome.delivery_class
        outcome.http_status = fetch_outcome.http_status
        outcome.rate_limit = fetch_outcome.rate_limit
        outcome.error = fetch_outcome.error
        outcome.error_kind = fetch_outcome.error_kind
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


MESH_SUMMARY_URL = f"{BASE_URL}/esummary.fcgi"
MESH_FIELD = "[MeSH Terms]"
# A term's own mapping, read from a search that asks for no record: ESearch reports the mapping it applied in
# `translationset`, so the heading comes from NCBI and not from a list of ours.
MESH_MAPPED = re.compile(r'^"([^"]+)"\[MeSH Terms\]')
MAX_MESH_NAMES = 12  # the candidate names one verification request carries
MESH_RECORDS_PER_NAME = 5  # records one name may answer with: its descriptor and its entry terms
# A lookup waits seconds, not the half minute a search page may: it runs inside the plan stage, whose whole
# share is seconds, and the query it adds to is already compiled without it. For the same reason a lookup does
# not wait out a rate limit (`max_rate_limit_retries` 0): a refused lookup is an expansion that does not happen,
# while its waits would be the person's.
MESH_TIMEOUT_SECONDS = 5.0


def _mesh_credentials(api_key: str | None, contact_email: str | None) -> tuple[dict[str, Any], str]:
    common: dict[str, Any] = {"tool": "DEIXIS"}
    if contact_email:
        common["email"] = contact_email
    if api_key:
        common["api_key"] = api_key
    return common, "api_key" if api_key else "keyless"


def _top_level(text: str) -> str | None:
    """`text` with every parenthesised group replaced by one mark, or None when the text is not well formed.

    A group is the mapping of something else — the single words a phrase was split into — so what the mapping did
    with the phrase as a whole is read outside the groups. Parentheses inside a quoted name are part of the name
    and open no group. A quote or a parenthesis that is never closed means the text is not the mapping it looks
    like, and then nothing is read from it: half of a mapping is not a mapping.
    """
    out, depth, quoted_part = [], 0, False
    for character in text:
        if character == '"':
            quoted_part = not quoted_part
        if not quoted_part and character in "()":
            depth += 1 if character == "(" else -1
            if depth < 0:
                return None
            if character == "(" and depth == 1:
                out.append(" \x00 ")
            continue
        if depth == 0:
            out.append(character)
    return None if depth or quoted_part else "".join(out)


def mapped_heading(translation: str) -> str | None:
    """The one MeSH heading NCBI mapped this whole phrase to, or None when it mapped it to something else.

    PubMed writes the mapping of a phrase as the operands it searched for it. A heading is read only when the
    mapping is an OR of alternatives whose first one is that heading: `AND` or `NOT` outside a group means PubMed
    searched the phrase's words together rather than the phrase itself, and a second heading outside the groups
    leaves the phrase mapped to two headings, neither of them its own. A heading inside a group belongs to those
    words, not to the phrase.
    """
    text = translation.strip()
    first = MESH_MAPPED.match(text)
    if first is None:
        return None
    skeleton = _top_level(text)
    # A field tag left unclosed is an operand that was cut off, so the text is not a whole mapping either.
    if skeleton is None or skeleton.count("[") != skeleton.count("]"):
        return None
    if re.search(r"\b(?:AND|NOT)\b", skeleton) or skeleton.count(MESH_FIELD) != 1:
        return None
    return first.group(1)


async def mesh_mapping(client: httpx.AsyncClient, text: str, *, api_key: str | None = None,
                       contact_email: str | None = None, max_rate_limit_retries: int = 0) -> dict[str, Any]:
    """How NCBI maps the phrases of `text`: one search that reads no record (`retmax=0`), reported back.

    The phrases are sent unquoted, because a quoted phrase is searched as it stands and gets no mapping. The
    answer's `translationset` names each phrase NCBI mapped and the operands it searched for it, so a heading this
    run uses is one NCBI itself chose. Nothing here is a search of the research: no record is asked for and none
    is read.
    """
    common, access_mode = _mesh_credentials(api_key, contact_email)
    description = f"GET {SEARCH_URL} db=pubmed term={text!r} retmax=0 access={access_mode}"
    params = common | {"db": "pubmed", "term": text, "retmode": "json", "retmax": 0}
    response, outcome = await send(client, SEARCH_URL, params, {}, description, access_mode, RATE_LIMIT_HEADERS,
                                  (api_key,), timeout=MESH_TIMEOUT_SECONDS,
                                  max_rate_limit_retries=max_rate_limit_retries)
    result: dict[str, Any] = {"request": description, "requests": 1, "retries": outcome.retries,
                              "translations": []}
    if response is None:
        return result | {"status": outcome.status, "error": outcome.error}
    try:
        payload = response.json()["esearchresult"]
        translations = [{"from": str(row["from"]), "to": str(row["to"])}
                        for row in payload.get("translationset") or []]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return result | {"status": "parse_error", "error": str(exc)[:300]}
    return result | {"status": "completed", "translations": translations}


async def mesh_descriptors(client: httpx.AsyncClient, names: list[str], *, api_key: str | None = None,
                           contact_email: str | None = None, max_rate_limit_retries: int = 0) -> dict[str, Any]:
    """Which of `names` the MeSH database itself holds as a descriptor, with its own preferred name and MeSH UI.

    Two requests over the MeSH database: a search of the names as headings, then a summary of the records it
    returned. A name is verified only when a returned record is a descriptor (`ds_recordtype`) whose preferred
    name — the first of its MeSH terms — is that name. An entry term, a qualifier or a supplementary record
    answers the search too, so the search alone would not say what was found. A name no record carries is
    reported as missing, and a failed request verifies nothing.
    """
    common, access_mode = _mesh_credentials(api_key, contact_email)
    asked = list(dict.fromkeys(name for name in names if name.strip()))
    wanted, unchecked = asked[:MAX_MESH_NAMES], asked[MAX_MESH_NAMES:]
    term = " OR ".join(f'"{name}"{MESH_FIELD}' for name in wanted)
    # One name can answer with several records — its own descriptor and the records that carry it as an entry
    # term — so the page is wide enough to hold the descriptor of every name asked about.
    records = len(wanted) * MESH_RECORDS_PER_NAME
    search_description = f"GET {SEARCH_URL} db=mesh term={term!r} retmax={records} access={access_mode}"
    result: dict[str, Any] = {"request": search_description, "requests": 1, "retries": 0, "verified": {},
                              "missing": wanted,
                              # A name this request did not carry is not verified and not missing: it was not asked.
                              **({"unchecked": unchecked} if unchecked else {})}
    if not wanted:
        return result | {"status": "completed", "requests": 0, "missing": []}
    params = common | {"db": "mesh", "term": term, "retmode": "json", "retmax": records}
    response, outcome = await send(client, SEARCH_URL, params, {}, search_description, access_mode,
                                  RATE_LIMIT_HEADERS, (api_key,), timeout=MESH_TIMEOUT_SECONDS,
                                  max_rate_limit_retries=max_rate_limit_retries)
    result["retries"] = outcome.retries
    if response is None:
        return result | {"status": outcome.status, "error": outcome.error}
    try:
        answer = response.json()["esearchresult"]
        ids = [str(value) for value in answer.get("idlist") or []]
        # Whether this one page holds every record the names answered with. It usually does; when it does not, a
        # name whose descriptor record is on a later page is not missing from MeSH, it was not reached.
        whole = int(answer["count"]) <= records
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return result | {"status": "parse_error", "error": str(exc)[:300]}
    if not ids:
        return result | {"status": "zero_results"}
    summary_description = f"GET {MESH_SUMMARY_URL} db=mesh ids={len(ids)} access={access_mode}"
    result |= {"request": f"{search_description}; {summary_description}", "requests": 2}
    summary, summary_outcome = await send(client, MESH_SUMMARY_URL, common | {"db": "mesh", "id": ",".join(ids),
                                                                             "retmode": "json"}, {},
                                          summary_description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                          timeout=MESH_TIMEOUT_SECONDS,
                                          max_rate_limit_retries=max_rate_limit_retries)
    result["retries"] += summary_outcome.retries
    if summary is None:
        return result | {"status": summary_outcome.status, "error": summary_outcome.error}
    try:
        payload = summary.json()["result"]
        records = [payload[uid] for uid in payload.get("uids") or [] if isinstance(payload.get(uid), dict)]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return result | {"status": "parse_error", "error": str(exc)[:300]}
    descriptors = {}
    for record in records:
        terms = record.get("ds_meshterms") or []
        if record.get("ds_recordtype") != "descriptor" or not terms:
            continue
        descriptors[str(terms[0]).casefold()] = {"descriptor": str(terms[0]), "mesh_ui": str(record.get("ds_meshui") or "")}
    verified = {name: descriptors[name.casefold()] for name in wanted if name.casefold() in descriptors}
    rest = [name for name in wanted if name not in verified]
    return result | {"status": "completed", "verified": verified,
                     "missing": rest if whole else [],
                     **({"unchecked": unchecked + ([] if whole else rest)} if unchecked or not whole else {})}

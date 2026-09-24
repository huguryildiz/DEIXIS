"""Which record a PDF belongs to, read from the file's own first pages (D49, SW10.2).

One matcher for both callers: the user dropping a file on a research asks `match_pdf_to_source` which record to
propose, and a full-text retrieval run asks `check` whether the file it just downloaded really is the work it asked
for. Neither writes anything; both read only the head of the extracted text, because a paper names itself on its
first page and a later page may quote any number of other papers.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.providers.common import normalize_doi
from deixis.workflow.store import title_key

DOI_IN_TEXT = re.compile(r"\b10\.\d+/[^\s\"<>]+")
ARXIV_IN_TEXT = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
MATCH_TEXT_CHARS = 6000
MIN_TITLE_WORDS = 4  # a shorter title says too little to name one paper


def identifiers_in(text: str) -> set[str]:
    """The DOIs the head of this text names, arXiv identifiers included as their DataCite DOI (D46)."""
    head = text[:MATCH_TEXT_CHARS]
    dois = {normalize_doi(d.rstrip(".,;:)]}")) for d in DOI_IN_TEXT.findall(head)}
    return dois | {f"10.48550/arxiv.{a}" for a in ARXIV_IN_TEXT.findall(head)}


def match_pdf_to_source(text: str, sources: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """The source a dropped PDF belongs to, from a DOI or arXiv identifier in its first pages, else its title (D49).

    Returns (source_version_id, basis). The user confirms every match before the file is attached.
    """
    dois = identifiers_in(text)
    for source in sources:
        if normalize_doi(source["doi"]) in dois:
            return source["id"], "doi"
    body = f" {title_key(text[:MATCH_TEXT_CHARS])} "
    titled = [s for s in sources if len(title_key(s["title"]).split()) >= MIN_TITLE_WORDS and f" {title_key(s['title'])} " in body]
    # One work only; its versions share a title, so the first listed (the included record) is proposed for the user to check.
    if len({s["work_id"] for s in titled}) == 1:
        return titled[0]["id"], "title"
    return None, None


def propose(text: str, sources: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """The work a file dropped on an `sw` research is proposed for, as one of its versions, and why (slice 18a).

    `match_pdf_to_source`'s rule with one change: a first page that names the DOI of more than one candidate work (a
    reference list that starts early, a companion paper cited on the title page) does not let the DOI decide, and the
    title is asked instead. A title that points at one work proposes it; otherwise nothing is proposed and the person
    picks the work. The person picks the version in every case, so the version named here is only marked.
    """
    dois = identifiers_in(text)
    named = [source for source in sources if normalize_doi(source["doi"]) in dois]
    if len({source["work_id"] for source in named}) == 1:
        return named[0]["id"], "doi"
    body = f" {title_key(text[:MATCH_TEXT_CHARS])} "
    titled = [s for s in sources if len(title_key(s["title"]).split()) >= MIN_TITLE_WORDS and f" {title_key(s['title'])} " in body]
    if len({s["work_id"] for s in titled}) == 1:
        return titled[0]["id"], "title"
    return None, None


def check(text: str, versions: list[dict[str, Any]]) -> str:
    """Whether this text is the work's own: "doi", "title" or "unconfirmed" (SW10.2).

    `versions` is every version of the work, because a published record's PDF may carry the preprint's arXiv
    identifier and a preprint's PDF the published DOI; either confirms the work.

    `unconfirmed` neither removes the text nor sets it aside: many PDFs carry no identifier on their first page,
    and the candidate was already reached through a DOI-verified route. The result is stored with the work's step
    and counted in the run's summary; what to do with it is slice 12's decision. How much of a wrong PDF this
    catches was not measured.
    """
    dois = identifiers_in(text)
    if any(normalize_doi(version.get("doi")) in dois for version in versions):
        return "doi"
    body = f" {title_key(text[:MATCH_TEXT_CHARS])} "
    keys = [title_key(version.get("title")) for version in versions]
    if any(len(key.split()) >= MIN_TITLE_WORDS and f" {key} " in body for key in keys):
        return "title"
    return "unconfirmed"

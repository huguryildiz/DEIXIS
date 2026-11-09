"""Which record a PDF belongs to, read from the file's own first pages (SW10.2).

One matcher for both callers: the user dropping a file on a research asks `propose` which work to propose, and a
full-text retrieval run asks `check` whether the file it just downloaded really is the work it asked for. Neither writes anything; both read only the head of the extracted text, because a paper names itself on its
first page and a later page may quote any number of other papers.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.providers.common import normalize_doi
from deixis.workflow.run.store import title_key

DOI_IN_TEXT = re.compile(r"\b10\.\d+/[^\s\"<>]+")
ARXIV_IN_TEXT = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
MATCH_TEXT_CHARS = 6000
MIN_TITLE_WORDS = 4  # a shorter title says too little to name one paper


def identifiers_in(text: str) -> set[str]:
    """The DOIs the head of this text names, arXiv identifiers included as their DataCite DOI."""
    head = text[:MATCH_TEXT_CHARS]
    dois = {normalize_doi(d.rstrip(".,;:)]}")) for d in DOI_IN_TEXT.findall(head)}
    return dois | {f"10.48550/arxiv.{a}" for a in ARXIV_IN_TEXT.findall(head)}


def propose(text: str, sources: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """The work a file dropped on an `sw` research is proposed for, as one of its versions, and why (slice 18a).

    that matching rule with one change: a first page that names the DOI of more than one candidate work (a
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


# How many pages of a downloaded file may be read looking for its own title page: the first, and the next two for
# a file whose first page is a repository cover sheet. Past that a match is as likely to be a contents page or a
# reference list as the paper itself.
TITLE_PAGE_LIMIT = 3
# How many of a page's first lines may bear the title. A title page prints the paper's title on a line of its own,
# under at most a journal header or a download banner, so the title has to **begin** one of those lines — a page
# that only mentions the title mid-sentence is naming another paper's work in its abstract, its introduction or
# its reference list, and is not that paper's title page. A title wrapped over two lines is read with the lines
# after it, which is why the test is "the text from this line on starts with the title", not "this line is it".
TITLE_LINES = 5


def verify_file(pages: list[str], target: dict[str, Any], published_doi: str | None = None) -> dict[str, Any]:
    """Whether this downloaded file is the record it was fetched for, read from the file's **own title page**.

    `check` is not this: it reads 6,000 characters of a document — which can reach a reference list — accepts any
    version of the work's DOI, and asks nothing about the author or the venue. A route that fetches a file nobody
    verified by DOI (an OpenAlex content download, a web-search recovery copy) needs the stricter question, and
    needs to know *what* matched: the answer travels with the file and is shown.

    The verdict is one of
      `match`     — the title page names this record's DOI (or the published DOI the lookup declared for it), or
                    its title together with its first author and its venue;
      `mismatch`  — the page carries a readable title page that names another paper;
      `unreadable`— no text could be read from the pages given, so nothing is claimed either way.
    `fields` names what matched, with two more for a caller that must ask more than the bare DOI: a DOI match also
    lists the title, author and venue the same page named, and `title_at_top` says the title began one of the
    page's first lines rather than being mentioned inside its text. `dois` says which of the wanted DOIs the page
    carried (empty unless `doi` matched), and
    `page` the physical page it matched on (1 for the first). A caller that must know *which* version it has reads
    `dois`: a page naming the published DOI is the published copy, which a title match alone never shows.
    """
    head = [page for page in pages[:TITLE_PAGE_LIMIT]]
    if not any(page and page.strip() for page in head):
        return {"verdict": "unreadable", "fields": [], "dois": [], "page": None}
    wanted = {doi for doi in (normalize_doi(target.get("doi")), normalize_doi(published_doi)) if doi}
    title = title_key(target.get("title"))
    # The first author's family name as the record stores it; a file names the authors on its title page in any
    # order of given and family name, so only the family name is asked for.
    authors = target.get("authors") or []
    first = (authors[0] if isinstance(authors[0], str) else (authors[0] or {}).get("name", "")) if authors else ""
    family = title_key(first).split()[-1] if title_key(first) else ""
    venue = title_key(target.get("venue"))
    for number, page in enumerate(head, start=1):
        if not page or not page.strip():
            continue
        body = f" {title_key(page)} "
        named = [field for field, value in (("title", title), ("author", family), ("venue", venue))
                 if value and len(value.split()) >= (MIN_TITLE_WORDS if field == "title" else 1)
                 and f" {value} " in body]
        # Where the title sat, as a field of its own. A title page prints the paper's title at the top; a page that
        # names this work further down is naming it in a reference, a contents list or a citing paragraph. Neither
        # the verdict nor `dois` turns on this: it is reported so a route that must know whose page it is reading
        # can ask for it (the open-web recovery search does).
        head = [key for line in page.splitlines() if (key := title_key(line))][:TITLE_LINES]
        at_top = "title" in named and any(" ".join(head[first:]).startswith(title) for first in range(len(head)))
        if found := wanted & identifiers_in(page):
            # What else the same page named is reported beside the DOI. A DOI alone does not say the page belongs
            # to this record: another paper that cites this work prints this work's DOI, and often its whole title,
            # in its own reference list, which a cover page or a short paper puts inside the title pages. A route
            # whose file came from a place nobody vouched for asks for more than the DOI; the verdict is unchanged.
            return {"verdict": "match", "fields": ["doi", *named, *(["title_at_top"] if at_top else [])],
                    "dois": sorted(found), "page": number}
        if {"title", "author", "venue"} <= set(named):
            return {"verdict": "match", "fields": [*named, *(["title_at_top"] if at_top else [])],
                    "dois": [], "page": number}
    return {"verdict": "mismatch", "fields": [], "dois": [], "page": None}

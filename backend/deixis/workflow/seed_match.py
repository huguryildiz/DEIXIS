"""Which OpenAlex work the user's seed PDF is, read from its own first two pages (seed_pdf_v1, D2).

At most two lookups: the DOIs the first pages name, then one meaning search with the head of the first page. Either
way a work is taken only when its title (four words or more) stands in the first two pages and exactly one work does
so: a DOI alone does not decide, because a title page may name the DOI of a paper it cites. Nothing here writes a
source row; the match is a step output the protocol freezes, and the chain, the semantic query and the ranking read it
from there.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deixis.documents import identity
from deixis.providers.openalex import reconstruct_abstract
from deixis.workflow.store import title_key

RULE = "seed_pdf_v1"
MAX_DOIS = 5
SEMANTIC_PER_PAGE = 10
SEMANTIC_QUERY_CHARS = 2000
TITLE_REGION_CHARS = 1500  # the head of page 1 where a paper names itself; a reference list on page 2 never counts


def short_id(value: Any) -> str | None:
    """`W123` from an OpenAlex work URL or short identifier; None for anything else."""
    value = str(value or "").rsplit("/", 1)[-1]
    return value if value[:1] == "W" and value[1:].isdigit() else None


def first_pages(store: Any, snapshot: dict[str, Any]) -> tuple[str, str, str]:
    """The text of the seed asset's physical pages 1 and 2 (for DOIs), the head of page 1 (for the title) and the
    first SEMANTIC_QUERY_CHARS of page 1 (what the context keeps of the PDF's own text).

    All empty when page 1 holds no text: a later page may quote any number of other papers, so it never stands in."""
    rows = store.conn.execute(
        "SELECT physical_page, text FROM passages WHERE asset_id = ? AND extraction_version IS ? AND kind = 'pdf_page'"
        " AND physical_page IN (1, 2) ORDER BY physical_page, rowid",
        (snapshot["asset_id"], snapshot["extraction_version"])).fetchall()
    first = "\n".join(row["text"] for row in rows if row["physical_page"] == 1)
    if not first.strip():
        return "", "", ""
    return ("\n".join(row["text"] for row in rows)[:identity.MATCH_TEXT_CHARS], first[:TITLE_REGION_CHARS],
            first[:SEMANTIC_QUERY_CHARS])


def dois_in(head: str) -> list[str]:
    """The DOIs the first pages name, in a fixed order, at most MAX_DOIS, none a filter cannot carry."""
    return sorted(d for d in identity.identifiers_in(head) if d and not any(c in d for c in "|,"))[:MAX_DOIS]


def pick(title_region: str, works: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int]:
    """The one work whose title stands in the head of page 1, and how many works' titles do: (None, 0) or (None, 2+)
    decide nothing."""
    body = f" {title_key(title_region)} "
    hits: dict[str, dict[str, Any]] = {}
    for work in works:
        oid, key = short_id(work.get("id")), title_key(work.get("display_name"))
        if oid and len(key.split()) >= identity.MIN_TITLE_WORDS and f" {key} " in body:
            hits.setdefault(oid, work)
    return (next(iter(hits.values())) if len(hits) == 1 else None), len(hits)


def matched(work: dict[str, Any], basis: str) -> dict[str, Any]:
    """What the protocol freezes of the matched work: its identifiers, title, abstract and reference list."""
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    references = list(dict.fromkeys(ref for value in work.get("referenced_works") or [] if (ref := short_id(value))))
    doi = str(work.get("doi") or "").removeprefix("https://doi.org/").casefold() or None
    return {"status": "matched", "basis": basis, "openalex_id": short_id(work.get("id")), "doi": doi,
            "title": work.get("display_name"), "title_key": title_key(work.get("display_name")),
            "year": work.get("publication_year"), "abstract": abstract,
            "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest() if abstract else None,
            "referenced_works": references, "references_read": "referenced_works" in work}


def payload_sha256(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def passages_sha256(snapshot: dict[str, Any] | None) -> str | None:
    """The fingerprint of the frozen excerpt a seeded run gives the query writer; None without a seed."""
    if not snapshot:
        return None
    return hashlib.sha256("\n".join(p["text_sha256"] for p in snapshot["passages"]).encode()).hexdigest()


def frozen(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    """The seed context this run's protocol froze, or None: no protocol yet, or one frozen without it (an unseeded
    run, or one whose protocol was frozen before seed_pdf_v1). Never completed from live tables."""
    step = store.existing_step(run["id"], "protocol")
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return None
    row = store.conn.execute(
        "SELECT body_json FROM protocol_records WHERE research_id = ? AND protocol_revision = ?",
        (run["research_id"], step["output"]["protocol_revision"])).fetchone()
    return json.loads(row[0]).get("seed_match") if row else None


def seed_text(context: dict[str, Any]) -> tuple[str, str]:
    """The text the semantic query carries beside the question, and where it came from."""
    if context["status"] == "matched" and context.get("abstract"):
        return f"{context['title']}. {context['abstract']}", "match_abstract"
    if context["status"] == "matched":
        return f"{context['title']}. {context['first_page_text']}".strip(), "match_title_pdf_excerpt"
    return context["first_page_text"], "pdf_excerpt"

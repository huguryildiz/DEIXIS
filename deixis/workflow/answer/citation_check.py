"""Verify Citations (V1, D86; V2, D96; V3, D99): a draft's markers, its bibliography entries and their (occurrence,
entry) pairs, the lookup that names each entry's OpenAlex record, the text each entry is read from, the frozen passage
plan of every pair, the preview with its cost range, the model step that checks each planned pair and the code's
verdict on it, the view, the export and the delete.

Each draft owns one internal research row (`researches.kind = 'citation_check'`), made without a scope revision, an
event or a run, so nothing starts discovery, a scope plan or a title call for it. Deleting the draft purges that
research, and the cascades remove what was read from the draft.

Mapping a marker to an entry never guesses. A key or a number names an entry only when exactly one entry carries it
(none: `unresolved`; several: `ambiguous`). An author–year item names an entry only when exactly one entry has the
same year and the same authors (`authors_match`: every author when the item has no `et al.`, surnames with their
particles); a cited letter suffix
(`2022a`) must be written on that entry, so a BibTeX entry, which has none, never takes one. Anything else is
`ambiguous`.

An entry resolves to an OpenAlex record by DOI (an arXiv id is read as its DataCite DOI) when exactly one returned work
carries it and the answer is complete, the rule the citation map uses (D42 in the old log); by title only when exactly
one of the first `TITLE_CANDIDATES` search results has a title at least `TITLE_MATCH_MIN` similar and no other year.
An entry with a DOI or arXiv id that does not resolve is not tried by title. The record is stored as a provider
source; titles, authors and years shown come from it, never from the draft or the entry.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx

from deixis.documents import acquisition, draft_parse, identity
from deixis.domain import contracts
from deixis.domain.citation_check import STATUSES, PartAssessment, check_outcome
from deixis.domain.rules import MAX_SCHEMA_REPAIRS, RevisionConflict
from deixis.imports import bibtex_ris
from deixis.models import prompt
from deixis.providers import openalex
from deixis.providers.common import normalize_doi
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.read import file_restore, text_retry
from deixis.workflow.run import spend, spend_estimate
from deixis.workflow.run.store import ACTIVE_RUN_STATUSES, ARXIV_DOI_PREFIX, NotFound, Store, is_preprint, is_published

KIND = "citation_check"
# Title resolution: a record is the entry's work only when it is the one search result whose title has at least this
# `difflib` ratio to the entry's title (both through `bibtex_ris.strict_title`) and no year that differs.
TITLE_MATCH_MIN = 0.93
TITLE_CANDIDATES = 5
ET_AL_MIN_AUTHORS = 3  # `Smith et al.` names a work of three or more authors (`authors_match`)
DOI_BATCH = openalex.MAX_IDS_PER_REQUEST


# ------------------------------------------------------------------------------------------------------- creating

def _structured_surnames(fmt: str, entry: bibtex_ris.Entry) -> list[str] | None:
    """The entry's surnames from the file's own name boundary, or None when it cannot be told.

    BibTeX `Last, First`, `von Last, First` and `Last, Jr, First`, and RIS `Last, First`: the surname is exactly the
    part before the first comma, particles included, and the given names never join it (`Berg, Van` is `berg`). A
    BibTeX name without a comma (`First von Last`) and a RIS name without one get the particle reading
    (`draft_parse.surname_key`); a braced corporate name is one surname. A name list that does not split into the
    entry's authors one for one, or an empty surname, is None, and author–year matching treats the entry as unknown."""
    fields = {str(k).lower(): v for k, v in entry.fields.items()}
    if fmt == "bibtex":
        raw = re.sub(r"\s+", " ", str(fields.get("author") or ""))
        names = [n.strip() for n in bibtex_ris._split_top(raw, re.compile(r" and ", re.IGNORECASE))
                 if n.strip() and n.strip().lower() != "others"]
    else:
        names = []
        for tag in ("au", "a1"):
            value = fields.get(tag) or []
            names.extend(v.strip() for v in ([value] if isinstance(value, str) else value) if str(v).strip())
    if len(names) != len(entry.authors):
        return None
    surnames = []
    for name in names:
        braced = fmt == "bibtex" and name.startswith("{") and name.endswith("}") and bibtex_ris._balanced(name[1:-1])
        parts = [name] if braced else (bibtex_ris._split_top(name, re.compile(r",")) if fmt == "bibtex" else name.split(","))
        text = bibtex_ris.latex_to_text(parts[0]) if fmt == "bibtex" else parts[0].strip()
        key = draft_parse.surname_fold(text) if len(parts) > 1 or braced else draft_parse.surname_key(text)
        if not key:
            return None
        surnames.append(key)
    return surnames


def _bib_rows(bibliography: tuple[str, list[bibtex_ris.Entry]] | None, draft: draft_parse.Draft) -> tuple[str, list[dict]]:
    """The entries the check reads: the uploaded file when given, else the draft's own list."""
    rows = []
    if bibliography is not None:
        fmt, entries = bibliography
        for entry in entries:
            fields = {str(k).lower(): v for k, v in entry.fields.items()}
            arxiv = None
            if str(fields.get("archiveprefix") or fields.get("eprinttype") or "").lower() == "arxiv":
                arxiv = str(fields.get("eprint") or "").strip() or None
            text = " ".join(str(v) for v in fields.values())
            rows.append({"origin": fmt, "key": entry.key, "number": None, "raw": dumps(entry.fields),
                         "doi": normalize_doi(entry.doi), "arxiv_id": arxiv or draft_parse.arxiv_of(text),
                         "title": entry.title, "authors": entry.authors, "year": entry.year, "suffix": None,
                         "surnames": _structured_surnames(fmt, entry)})
        return fmt, rows
    for item in draft.list_entries:
        fields = draft_parse.written_entry_fields(item.raw)
        rows.append({"origin": draft.list_origin, "key": item.key, "number": item.number, "raw": item.raw,
                     "doi": fields["doi"], "arxiv_id": fields["arxiv_id"], "title": fields["title"],
                     "authors": fields["authors"], "year": fields["year"], "suffix": fields["year_suffix"],
                     "surnames": [draft_parse.surname_key(a) for a in fields["authors"]]})
    return draft.list_origin or "none", rows


def _match(target: draft_parse.Target, entries: list[dict]) -> tuple[int | None, str]:
    """The index of the one entry the target names and `planned`, else None and `unresolved` or `ambiguous`."""
    if target.kind == "key":
        found = [i for i, e in enumerate(entries) if e["key"] == target.value]
    elif target.kind == "number":
        found = [i for i, e in enumerate(entries) if e["number"] == int(target.value)]
    else:
        cited = [draft_parse.surname_key(n) for n in target.names]
        found = []
        for i, entry in enumerate(entries):
            if entry["year"] != target.year:
                continue
            if entry["surnames"] is None or not all(entry["surnames"]):
                return None, "ambiguous"  # an entry of that year whose authors cannot be read could be the one
            if not all(cited) or not authors_match(cited, target.et_al, entry["surnames"]):
                continue
            if target.suffix is not None and entry["suffix"] != target.suffix:
                continue
            found.append(i)
        return (found[0], "planned") if len(found) == 1 else (None, "ambiguous")
    if len(found) == 1:
        return found[0], "planned"
    return None, "unresolved" if not found else "ambiguous"


def authors_match(cited: list[str], et_al: bool, surnames: list[str]) -> bool:
    """Whether an entry's authors are the ones an author–year item names. Without `et al.` the item names every
    author: the same number, the same surnames in order (`Smith` is not `Smith & Jones`). With `et al.` the cited
    surnames are the first ones, followed by at least one more, and the entry has at least `ET_AL_MIN_AUTHORS` authors:
    APA 7, Harvard and Chicago author–date write two authors out in full and shorten only three or more, so
    `Smith et al.` never names a one- or two-author work."""
    if not et_al:
        return surnames == cited
    return len(surnames) >= max(ET_AL_MIN_AUTHORS, len(cited) + 1) and surnames[:len(cited)] == cited


def create(store: Store, draft: draft_parse.Draft, filename: str | None,
           bibliography: tuple[str, list[bibtex_ris.Entry], list[dict], str | None] | None) -> str:
    """Store a parsed draft with its markers, entries and pairs, in one transaction; returns the draft id.
    `bibliography` is (format, entries, entry errors as views, filename) of an uploaded BibTeX or RIS file."""
    fmt = draft.format
    origin, entries = _bib_rows((bibliography[0], bibliography[1]) if bibliography else None, draft)
    errors = bibliography[2] if bibliography else []
    draft_id, ts = new_id("cdr"), now()
    with transaction(store.conn):
        research_id = store.create_internal_research(KIND, f"Citation check: {Path(filename).name if filename else 'pasted text'}")
        store.conn.execute(
            "INSERT INTO citation_drafts (id, research_id, original_filename, format, text_sha256, text, bibliography_origin,"
            " bibliography_filename, bibliography_errors_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (draft_id, research_id, Path(filename).name if filename else None, fmt,
             hashlib.sha256(draft.text.encode("utf-8")).hexdigest(), draft.text, origin,
             Path(bibliography[3]).name if bibliography and bibliography[3] else None, dumps(errors), ts))
        entry_ids = []
        for ordinal, entry in enumerate(entries, start=1):
            entry_ids.append(new_id("cbe"))
            store.conn.execute(
                "INSERT INTO citation_bib_entries (id, draft_id, ordinal, origin, entry_key, entry_number, raw_entry, doi,"
                " arxiv_id, title, authors_json, year, year_suffix) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_ids[-1], draft_id, ordinal, entry["origin"], entry["key"], entry["number"], entry["raw"],
                 entry["doi"], entry["arxiv_id"], entry["title"], dumps(entry["authors"]), entry["year"], entry["suffix"]))
        pair_ordinal = 0
        for ordinal, marker in enumerate(draft.markers, start=1):
            pairs, seen = [], set()
            for target in dict.fromkeys(marker.targets):
                index, status = _match(target, entries)
                if index is not None and index in seen:
                    continue  # one pair per (occurrence, entry)
                seen.add(index)
                pairs.append((target, index, status))
            status = marker.status if marker.status == "unrecognized" else (
                "ambiguous" if any(s == "ambiguous" for _, _, s in pairs) else "recognized")
            marker_id = new_id("cmk")
            store.conn.execute(
                "INSERT INTO citation_markers (id, draft_id, ordinal, sentence, sentence_start, sentence_end, char_start,"
                " char_end, raw, style, parse_status, targets_json, claim, claim_context, parse_reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (marker_id, draft_id, ordinal, draft.text[marker.sentence_start:marker.sentence_end],
                 marker.sentence_start, marker.sentence_end, marker.start, marker.end, marker.raw, marker.style, status,
                 dumps([t.view() for t in marker.targets]), marker.claim or None, marker.claim_context, marker.reason))
            for target, index, pair_status in pairs:
                pair_ordinal += 1
                store.conn.execute(
                    "INSERT INTO citation_pairs (id, draft_id, marker_id, bib_entry_id, target, ordinal, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("cpr"), draft_id, marker_id, entry_ids[index] if index is not None else None, target.value,
                     pair_ordinal, pair_status, ts))
    return draft_id


def draft_row(store: Store, draft_id: str) -> dict[str, Any]:
    row = store.conn.execute("SELECT * FROM citation_drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise NotFound(draft_id)
    return dict(row)


def drafts(store: Store) -> list[dict[str, Any]]:
    """Every draft, newest first, with what its list row shows: its file name, when it was given, how many citations
    and pairs it has, how many pairs completed a check (`done`) and, apart, how many could not be checked, and its
    latest check run's status. A pair that could not be checked is never counted as checked."""
    rows = store.conn.execute(
        "SELECT d.id, d.research_id, d.original_filename, d.format, d.created_at,"
        " (SELECT COUNT(*) FROM citation_markers m WHERE m.draft_id = d.id) AS occurrences,"
        " (SELECT COUNT(*) FROM citation_pairs p WHERE p.draft_id = d.id) AS pairs,"
        " (SELECT COUNT(*) FROM citation_pairs p WHERE p.draft_id = d.id AND p.status = 'done') AS pairs_done,"
        " (SELECT COUNT(*) FROM citation_pairs p WHERE p.draft_id = d.id AND p.status = 'could_not_check')"
        " AS pairs_could_not_check FROM citation_drafts d ORDER BY d.created_at DESC, d.rowid DESC").fetchall()
    out = []
    for row in rows:
        item = dict(row)
        state = check_state(store, item.pop("research_id"))
        out.append(item | {"check_status": state["status"] if state else None})
    return out


def delete(store: Store, draft_id: str) -> tuple[list[str], list[str]]:
    """Purge the draft's internal research; the draft and everything read from it go with it. The records and files
    acquisition read are members of that research (`_join`), so the purge removes every one no other research, Library
    item or citation holds, with its passages; returns the PDF and payload files left for the caller to unlink."""
    with transaction(store.conn):
        research_id = draft_row(store, draft_id)["research_id"]
        store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", (now(), research_id))
        return store.purge_research(research_id)


# ----------------------------------------------------------------------------------------------------- resolving

def _identifier(entry: dict[str, Any]) -> tuple[str, str] | None:
    if entry["doi"]:
        return "doi", entry["doi"]
    if entry["arxiv_id"]:
        return "arxiv", normalize_doi(ARXIV_DOI_PREFIX + entry["arxiv_id"])
    return None


def title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, bibtex_ris.strict_title(a), bibtex_ris.strict_title(b)).ratio()


async def resolve(store: Store, http: httpx.AsyncClient, payloads_dir: Path, contact_email: str | None,
                  draft_id: str) -> dict[str, int]:
    """Look up every entry a pair names that is `pending` or `lookup_failed`; an entry already resolved or unresolved
    is not asked again, so calling this twice sends nothing the second time. Requests go out before the one write."""
    draft_row(store, draft_id)
    entries = [dict(r) for r in store.conn.execute(
        "SELECT * FROM citation_bib_entries WHERE draft_id = ? AND resolution_status IN ('pending', 'lookup_failed')"
        " AND id IN (SELECT bib_entry_id FROM citation_pairs WHERE draft_id = ? AND bib_entry_id IS NOT NULL)"
        " ORDER BY ordinal", (draft_id, draft_id))]
    api_key = CONNECTORS["openalex"].api_key()
    payloads_dir.mkdir(parents=True, exist_ok=True)

    def write_payload(payload: Any) -> str:
        name = f"{new_id('ope')}.json"
        (payloads_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return name

    outcomes: dict[str, dict[str, Any]] = {}
    by_doi: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if (identifier := _identifier(entry)) is not None:
            by_doi.setdefault(identifier[1], []).append(entry)
        elif entry["title"]:
            outcomes[entry["id"]] = await _by_title(http, api_key, contact_email, entry, write_payload)
        else:
            outcomes[entry["id"]] = {"status": "unresolved", "reason": "no_identifier_or_title"}
    dois = [d for d in by_doi if "|" not in d and "," not in d]
    for doi in by_doi:
        if doi not in dois:
            for entry in by_doi[doi]:
                outcomes[entry["id"]] = {"status": "unresolved", "reason": "doi_not_filterable"}
    for i in range(0, len(dois), DOI_BATCH):
        batch = dois[i:i + DOI_BATCH]
        outcome = await openalex.works_by_dois(http, batch, api_key=api_key, contact_email=contact_email,
                                               per_page=DOI_BATCH)
        ok = outcome.status in ("completed", "zero_results")
        complete = ok and isinstance(outcome.provider_total, int) and outcome.provider_total <= len(outcome.records)
        found: dict[str, list[Any]] = {}
        for record in outcome.records if ok else []:
            if doi := normalize_doi(record.doi):
                found.setdefault(doi, []).append(record)
        path = write_payload(outcome.raw_payload) if ok and outcome.records else None
        for doi in batch:
            records = found.get(doi, [])
            if not ok:
                result = {"status": "lookup_failed", "reason": outcome.error_kind or outcome.status}
            elif not complete:
                result = {"status": "lookup_failed", "reason": "incomplete_answer"}
            elif len(records) == 1:
                result = {"status": "resolved", "record": records[0], "payload": path}
            else:
                result = {"status": "unresolved", "reason": "doi_several_works" if records else "doi_not_found"}
            for entry in by_doi[doi]:
                outcomes[entry["id"]] = {**result, "method": _identifier(entry)[0]}
    counts = {"asked": len(entries), "resolved": 0, "unresolved": 0, "lookup_failed": 0}
    with transaction(store.conn):
        for entry in entries:
            result = outcomes[entry["id"]]
            counts[result["status"]] += 1
            if result["status"] == "resolved":
                svid, _ = store.upsert_provider_source("openalex", result["record"], result["payload"])
                store.conn.execute(
                    "UPDATE citation_bib_entries SET resolution_status = 'resolved', resolution_method = ?,"
                    " resolution_reason = NULL, resolved_source_version_id = ?, resolved_openalex_id = ?,"
                    " resolution_origin = 'code', resolved_at = ? WHERE id = ?",
                    (result["method"], svid, result["record"].provider_record_id, now(), entry["id"]))
            else:
                store.conn.execute(
                    "UPDATE citation_bib_entries SET resolution_status = ?, resolution_method = ?, resolution_reason = ?,"
                    " resolved_at = ? WHERE id = ?",
                    (result["status"], result.get("method"), result["reason"], now(), entry["id"]))
        store.conn.execute(
            "UPDATE citation_pairs SET status = 'unresolved' WHERE draft_id = ? AND status = 'planned' AND bib_entry_id IN"
            " (SELECT id FROM citation_bib_entries WHERE draft_id = ? AND resolution_status = 'unresolved')",
            (draft_id, draft_id))
    return counts


async def _by_title(http: httpx.AsyncClient, api_key: str | None, contact_email: str | None, entry: dict[str, Any],
                    write_payload) -> dict[str, Any]:
    outcome = await openalex.search_works(http, entry["title"], TITLE_CANDIDATES, api_key=api_key,
                                          contact_email=contact_email)
    if outcome.status not in ("completed", "zero_results"):
        return {"status": "lookup_failed", "reason": outcome.error_kind or outcome.status, "method": "title"}
    close = [r for r in outcome.records[:TITLE_CANDIDATES]
             if title_similarity(entry["title"], r.title or "") >= TITLE_MATCH_MIN
             and (entry["year"] is None or r.year is None or r.year == entry["year"])]
    if len(close) != 1:
        return {"status": "unresolved", "reason": "title_several_matches" if close else "title_no_match", "method": "title"}
    return {"status": "resolved", "record": close[0], "payload": write_payload(outcome.raw_payload), "method": "title"}


# ----------------------------------------------------------------------------------------------- text acquisition
#
# Each resolved entry a pair names gets one text, decided once (`text_status = 'settled'`): the person's own PDF for
# that entry when it has a text layer, else a PDF the record already holds, else the open-access path research runs
# use (`acquisition.acquire_for_source`: Unpaywall, OpenAlex, Crossref, CORE, Europe PMC, and a verified copy of
# another declared version on its own row; no web search), else the record's abstract, else nothing
# (`metadata_only`). Every record read joins the draft's internal research, so the draft's purge removes it.

TEXT_PHASE = "text_acquisition"  # the `target.phase` of the run an acquisition opens
BUDGET_STOP = "openalex_budget_exhausted"
# A file another operation holds now; the entry stays pending and the next acquisition asks again.
TRANSIENT_FILE_CODES = ("file_busy", "run_active")
AVAILABLE_TEXT = ("full_text", "abstract", "metadata_only")


class PlanRefused(Exception):
    """A plan or preview request the draft's state does not allow; `code` names why (409)."""

    def __init__(self, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.code, self.detail, self.extra = code, detail, extra


def available_text(store: Store, svid: str) -> str:
    """What a model step could read of this record: PDF text, else its abstract, else only its metadata."""
    kinds = {p["kind"] for p in store.passages_for(svid)}
    return "full_text" if "pdf_page" in kinds else "abstract" if "abstract" in kinds else "metadata_only"


def text_version(source: dict[str, Any]) -> str | None:
    """`upload` for a person's file, `preprint` for a preprint or an accepted or submitted manuscript (D46, D48),
    `publisher` for a record under its own registered DOI; None when the record says neither."""
    if source["origin"] == "user_upload":
        return "upload"
    if is_preprint(source) or source.get("version_label") == "acceptedVersion":
        return "preprint"
    return "publisher" if is_published(source) else None


def _join(store: Store, research_id: str, svid: str, upload: bool = False) -> None:
    """Make a record the draft reads a member of its internal research (as the citation map adds its records), so the
    draft's purge removes it, its passages and its files when nothing else holds them."""
    if upload:
        store.add_to_corpus(research_id, svid, "user_upload", selection_state="included", selection_origin="user")
    else:
        store.add_to_corpus(research_id, svid, "library", selection_state="pending", selection_origin="user")


def entry_row(store: Store, draft_id: str, entry_id: str) -> dict[str, Any]:
    row = store.conn.execute("SELECT * FROM citation_bib_entries WHERE id = ? AND draft_id = ?", (entry_id, draft_id)).fetchone()
    if row is None:
        raise NotFound(entry_id)
    return dict(row)


def link_upload(store: Store, draft_id: str, entry_id: str, svid: str, identity_result: str) -> None:
    """The person's PDF for this entry, with what `identity.check` read on it. The entry's text is decided again on the
    next acquisition; a plan frozen before shows itself stale until the person freezes again."""
    with transaction(store.conn):
        research_id = draft_row(store, draft_id)["research_id"]
        entry_row(store, draft_id, entry_id)
        _join(store, research_id, svid, upload=True)
        store.conn.execute(
            "UPDATE citation_bib_entries SET upload_source_version_id = ?, upload_identity = ?, text_status = 'pending',"
            " text_note = NULL WHERE id = ?", (svid, identity_result, entry_id))


def pdf_identity(store: Store, svid: str, target_svid: str) -> dict[str, Any] | None:
    """`identity.check` on the PDF text of `svid` against every version of `target_svid`'s work, with the file and
    extraction it read; None when `svid` has no PDF text. Run on every PDF an entry's text is chosen from (the
    person's, a stored one, an open-access copy): a provider record verified by DOI says nothing about the file it
    pointed to."""
    pages = [p for p in store.passages_for(svid) if p["kind"] == "pdf_page"]
    if not pages:
        return None
    work_id = store.source(target_svid)["work_id"]
    versions = [dict(r) for r in store.conn.execute("SELECT doi, title FROM source_versions WHERE work_id = ?", (work_id,))]
    return {"result": identity.check("\n".join(p["text"] for p in pages), versions), "source_version_id": svid,
            "asset_id": pages[0]["asset_id"], "extraction_version": pages[0]["extraction_version"], "work_id": work_id}


def _settle(store: Store, entry: dict[str, Any], svid: str, origin: str, note: str | None = None) -> None:
    source = store.source(svid)
    checked = pdf_identity(store, svid, entry["resolved_source_version_id"])
    with transaction(store.conn):
        store.conn.execute(
            "UPDATE citation_bib_entries SET text_status = 'settled', available_text = ?, text_source_version_id = ?,"
            " text_version = ?, text_origin = ?, text_note = ?, text_settled_at = ?, text_identity = ?,"
            " text_identity_asset_id = ?, text_identity_extraction = ? WHERE id = ?",
            (available_text(store, svid), svid, text_version(source), origin, note, now(),
             checked["result"] if checked else None, checked["asset_id"] if checked else None,
             checked["extraction_version"] if checked else None, entry["id"]))


CONFIRMED = ("doi", "title")
NOT_APPLICABLE = "not_applicable"  # the text read is an abstract: there is no file to identify


def recheck_identity(store: Store, entry: dict[str, Any]) -> dict[str, Any]:
    """`identity.check` on the entry's text as it is now, stored on the entry and returned, as a revision freezes it.
    Never copied from an earlier result: a stored result may belong to another file or extraction. An abstract-only
    text has none to check (`not_applicable`)."""
    svid = entry["text_source_version_id"]
    checked = pdf_identity(store, svid, entry["resolved_source_version_id"])
    with transaction(store.conn):
        store.conn.execute("UPDATE citation_bib_entries SET text_identity = ?, text_identity_asset_id = ?,"
                           " text_identity_extraction = ? WHERE id = ?",
                           (checked["result"] if checked else None, checked["asset_id"] if checked else None,
                            checked["extraction_version"] if checked else None, entry["id"]))
    return checked or {"result": NOT_APPLICABLE, "source_version_id": svid}


def revision_identity_confirmed(store: Store, pair: dict[str, Any]) -> bool | None:
    """Whether a frozen revision's identity result confirms the file its passages come from; None when the pair reads
    no text (`no_text`, `unresolved`). Fail-closed: a missing result, an unknown one, or one whose file or extraction
    is not the one the given passages were cut from never confirms. A checked pair (`done`, `could_not_check`) keeps
    the revision it was checked on."""
    if pair["status"] not in ("planned", "out_of_cap", "done", "could_not_check"):
        return None
    checked = json.loads(pair["plan_identity_json"]) if pair["plan_identity_json"] else None
    if not checked or checked.get("result") not in (*CONFIRMED, NOT_APPLICABLE):
        return False
    plan = json.loads(pair["passage_plan_json"]) if pair["passage_plan_json"] else None
    for passage_id in (plan or {}).get("passage_ids") or []:
        row = store.conn.execute("SELECT kind, asset_id, extraction_version FROM passages WHERE id = ?",
                                 (passage_id,)).fetchone()
        if row is None:
            return False
        if row["kind"] == "pdf_page" and (checked.get("result") == NOT_APPLICABLE or row["asset_id"] != checked.get("asset_id")
                                          or row["extraction_version"] != checked.get("extraction_version")):
            return False
    return True


def _pending(store: Store, entry_id: str, note: str) -> None:
    with transaction(store.conn):
        store.conn.execute("UPDATE citation_bib_entries SET text_status = 'pending', text_note = ? WHERE id = ?", (note, entry_id))


def _active_run(store: Store, research_id: str) -> str | None:
    row = store.conn.execute(
        f"SELECT id FROM runs WHERE research_id = ? AND status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1",
        (research_id, *ACTIVE_RUN_STATUSES)).fetchone()
    return row["id"] if row else None


def _open_run(store: Store, research_id: str, draft_id: str) -> dict[str, Any]:
    """A `citation_check` run that is running from the start, never queued: the worker has no handler for this kind
    and must not pick it up. It carries the draft's OpenAlex lookups, so a refusal of the daily budget is counted
    (`openalex_budget_runs`) and every other run of the app learns of it, and it ends `paused` on that refusal. A
    process that stops while it runs leaves it `paused` (`backend_restarted`), as every run."""
    with transaction(store.conn):
        if _active_run(store, research_id):
            raise RevisionConflict("A text acquisition of this draft is still running")
        research = store.research(research_id)
        run_id, ts = new_id("run"), now()
        store.conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, target_json, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, 'running', 'inspection', '{}', ?, ?, ?)",
            (run_id, research_id, research["current_scope_revision"], KIND,
             dumps({"draft_id": draft_id, "phase": TEXT_PHASE}), ts, ts))
        store._event(research_id, "run_started", {"kind": KIND, "phase": TEXT_PHASE}, run_id)
    return store.run(run_id)


async def acquire(store: Store, http: httpx.AsyncClient, settings: Any, fetcher: Any, xml_fetcher: Any,
                  draft_id: str) -> dict[str, Any]:
    """Decide the text of every resolved entry a pair names whose text is still pending; settled entries are not asked
    again. OpenAlex's daily budget is read from the store before each record: once it is spent, no record that needs
    the network is asked (none of its lookups is sent), each stays `pending` with the reason, the run ends `paused`
    with the time the budget returns, and everything settled so far stays. The next call asks only what is pending."""
    research_id = draft_row(store, draft_id)["research_id"]
    if _active_run(store, research_id):
        raise RevisionConflict("A text acquisition of this draft is still running")
    entries = [dict(r) for r in store.conn.execute(
        "SELECT * FROM citation_bib_entries WHERE draft_id = ? AND text_status = 'pending' AND resolution_status = 'resolved'"
        " AND resolved_source_version_id IS NOT NULL"
        " AND id IN (SELECT bib_entry_id FROM citation_pairs WHERE draft_id = ? AND bib_entry_id IS NOT NULL)"
        " ORDER BY ordinal", (draft_id, draft_id))]
    for unchecked in store.conn.execute(
            "SELECT * FROM citation_bib_entries WHERE draft_id = ? AND text_status = 'settled'"
            " AND available_text = 'full_text' AND text_identity IS NULL AND text_source_version_id IS NOT NULL",
            (draft_id,)).fetchall():
        recheck_identity(store, dict(unchecked))  # settled before identity was stored: read now, nothing sent
    for unchecked in store.conn.execute(
            "SELECT id, upload_source_version_id, resolved_source_version_id FROM citation_bib_entries WHERE draft_id = ?"
            " AND upload_source_version_id IS NOT NULL AND upload_identity IS NULL AND resolved_source_version_id IS NOT NULL",
            (draft_id,)).fetchall():
        checked = pdf_identity(store, unchecked["upload_source_version_id"], unchecked["resolved_source_version_id"])
        with transaction(store.conn):
            store.conn.execute("UPDATE citation_bib_entries SET upload_identity = ? WHERE id = ?",
                               (checked["result"] if checked else "unconfirmed", unchecked["id"]))
    budget = acquisition.OpenAlexBudget()
    run: dict[str, Any] | None = None
    reset_at: str | None = None
    read_now: dict[str, tuple[str, str, str | None]] = {}  # a record two entries name is acquired once per call
    try:
        for entry in entries:
            svid, upload = entry["resolved_source_version_id"], entry["upload_source_version_id"]
            _join(store, research_id, svid)
            if upload and available_text(store, upload) == "full_text":
                _settle(store, entry, upload, "person_pdf")
                continue
            if svid in read_now:
                _settle(store, entry, *read_now[svid])
                continue
            if available_text(store, svid) == "full_text":
                _settle(store, entry, svid, "stored_pdf")
                continue
            without = "person_pdf_without_text" if upload else None
            if not normalize_doi(store.source(svid).get("doi")):
                _settle(store, entry, svid, "record", without or "no_doi")
                continue
            stored = store.openalex_budget_reset()
            if stored and (budget.reset_at is None or stored > budget.reset_at):
                budget.reset_at = stored
            run = run or _open_run(store, research_id, draft_id)
            if budget.exhausted:
                reset_at = budget.reset_at
                _pending(store, entry["id"], BUDGET_STOP)
                continue
            try:
                found = await acquisition.acquire_for_source(
                    store, research_id, svid, http, settings.papers_dir, settings.contact_email, None, fetcher,
                    core_key=CONNECTORS["core"].api_key(), web_search=False, other_versions=True,
                    elsevier_key=CONNECTORS["scopus"].api_key(),
                    xml_fetcher=xml_fetcher, recovery_dir=settings.recovery_dir, openalex_budget=budget,
                    workflow_run_id=run["id"])
            except (file_restore.FileRestoreRefused, text_retry.FileBusy) as exc:
                code = exc.code if isinstance(exc, file_restore.FileRestoreRefused) else "file_busy"
                if code in TRANSIENT_FILE_CODES:
                    _pending(store, entry["id"], code)  # another operation holds the file: asked again next time
                else:
                    _settle(store, entry, svid, "record", code)
                continue
            read = found.get("lookup_version_id") or svid
            if available_text(store, read) == "full_text":
                _join(store, research_id, read)
                read_now[svid] = (read, "open_access", None)
            elif budget.exhausted:
                # The OpenAlex lookup was refused or not sent and no other route gave a file: asked again next time.
                reset_at = budget.reset_at
                _pending(store, entry["id"], BUDGET_STOP)
                continue
            else:
                read_now[svid] = (svid, "record", without or "no_open_copy")
            _settle(store, entry, *read_now[svid])
    except BaseException:
        if run is not None:
            store.update_run(run["id"], event="run_failed", status="failed", error_json={"code": "text_acquisition_failed"})
        raise
    if run is not None:
        if reset_at:
            store.update_run(run["id"], event="run_paused", status="paused", pause_reason=BUDGET_STOP,
                             error_json={"reset_at": reset_at})
        else:
            store.update_run(run["id"], event="run_completed", status="completed")
    pending = sum(1 for e in entries if entry_row(store, draft_id, e["id"])["text_status"] == "pending")
    return {"status": "paused" if reset_at else "completed", "reset_at": reset_at, "asked": len(entries),
            "settled": len(entries) - pending, "pending": pending}


def acquisition_state(store: Store, research_id: str) -> dict[str, Any] | None:
    """The latest text acquisition run of the draft: its status and, when the budget paused it, when it returns."""
    row = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = ? AND json_extract(target_json, '$.phase') = ?"
                             " ORDER BY created_at DESC, rowid DESC LIMIT 1", (research_id, KIND, TEXT_PHASE)).fetchone()
    if row is None:
        return None
    run = store.run(row["id"])
    return {"run_id": run["id"], "status": run["status"], "pause_reason": run["pause_reason"],
            "reset_at": (run["error"] or {}).get("reset_at") if run["status"] == "paused" else None}


# ------------------------------------------------------------------------------------------------------ the plan
#
# The frozen passage plan of a pair: which passages of its entry's text the V3 step will be given, in order, with each
# passage's text hash, how many passages the text has and how many were not given, and the depth label. A plan is
# frozen once, by the person's request, and read by the preview and the run alike; only the person's re-freeze writes
# a new revision, and the pair keeps every earlier one (`previous_plans_json`).

PASSAGES_PER_PAIR = 6  # K: the passages one pair is given; flow.MAX_PASSAGES_PER_SOURCE gives an answer the same
MAX_PAIRS_TO_MODEL = 200  # unique (occurrence, entry) pairs one check sends, in draft order (plan, decision 4)
MAX_SENTENCE_TERMS = 40  # the words a sentence ranks by, as `flow._topic_terms` keeps for a question
PLAN_VERSION = 1
RANKING = "fts5_bm25_sentence_words"
PLAN_STATUSES = ("planned", "out_of_cap", "no_text")  # the statuses a freeze decides; V1's others stay as they are


def cited_sentence(text: str, marker: dict[str, Any], spans: list[tuple[int, int]]) -> str:
    """The claim the check reads for this marker: the stored plain claim (`draft_parse`, D105: markers cut, LaTeX as
    plain text, a table citation's row), else, for a draft read before claims were stored, the marker's sentence with
    every citation marker in it cut out, so a key, a number or a cited name never ranks a passage."""
    if marker.get("claim"):
        return marker["claim"]
    cut = draft_parse.cut_markers(text, marker["sentence_start"], marker["sentence_end"], spans)
    return re.sub(r"\s+", " ", cut).strip()


def sentence_terms(sentence: str) -> list[str]:
    """The sentence's words as the answer and the reading list rank passages by (`flow._topic_terms`): lower case, more
    than two characters, no stop word, each once."""
    from deixis.workflow.run.flow import STOPWORDS  # flow builds on most of the workflow; read only when ranking
    terms = [t for t in re.findall(r"\w+", sentence.lower()) if len(t) > 2 and t not in STOPWORDS]
    return list(dict.fromkeys(terms))[:MAX_SENTENCE_TERMS]


def rank_passages(store: Store, svid: str, sentence: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Every passage a model step may read of this record, the ones sharing the sentence's words first (`rank_pool`)."""
    return rank_pool(store, svid, store.passages_for(svid), sentence)


def rank_pool(store: Store, svid: str, pool: list[dict[str, Any]], sentence: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The passages of `pool` (passages of this record a model step may read), the ones sharing the sentence's words
    first.

    The app's passage ranking: SQLite FTS5 BM25 over the sentence's words OR-ed (`store.search_passages`, the order
    answers and full-text readings use, equal scores by passage id), then the passages no word matched in stored order
    (kind, page), and a reference-list passage last (`flow._reference_list`), as `_retrieve` does. Not the first pages:
    `candidates.shown_passages` takes those and is not a relevance order. The search reads every readable passage of
    the record, so a pool smaller than the record keeps the order its passages have among all of them."""
    from deixis.workflow.run.flow import _reference_list
    terms = sentence_terms(sentence)
    ids = {p["id"] for p in pool}
    ranked = [p for p in store.search_passages([svid], " OR ".join(f'"{t}"' for t in terms),
                                               max(len(pool), len(store.passages_for(svid))))
              if p["id"] in ids] if terms and pool else []
    seen = {p["id"] for p in ranked}
    ordered = ranked + [p for p in pool if p["id"] not in seen]
    return sorted(ordered, key=lambda p: _reference_list(p["text"])), terms


def _plan_for(store: Store, svid: str, sentence: str, revision: int, ts: str) -> dict[str, Any]:
    ordered, terms = rank_passages(store, svid, sentence)
    text = available_text(store, svid)
    # An abstract-only record is read from its abstract, the one passage it has (plan, decision 5).
    given = ordered[:PASSAGES_PER_PAIR] if text == "full_text" else ordered[:1]
    if text == "abstract":
        depth = "abstract"
    else:
        depth = "full_text" if len(given) == len(ordered) else "selected_passages"
    return {"version": PLAN_VERSION, "revision": revision, "frozen_at": ts, "source_version_id": svid,
            "available_text": text, "text_version": text_version(store.source(svid)), "depth": depth,
            "ranking": RANKING, "terms": terms, "passages_per_pair": PASSAGES_PER_PAIR,
            "passage_ids": [p["id"] for p in given],
            "passage_sha256": [hashlib.sha256(p["text"].encode("utf-8")).hexdigest() for p in given],
            "passage_chars": sum(len(p["text"]) for p in given),
            "passages_total": len(ordered), "passages_not_given": len(ordered) - len(given),
            "fingerprint": text_fingerprint(ordered)}


def text_fingerprint(passages: list[dict[str, Any]]) -> str:
    """One hash of a record's readable passages as a plan saw them: each passage's id, file, extraction and text. A new
    file, a new extraction or a changed passage set under the same record changes it."""
    rows = sorted((p["id"], p["asset_id"] or "", p["extraction_version"] or "",
                   hashlib.sha256(p["text"].encode("utf-8")).hexdigest()) for p in passages)
    return hashlib.sha256(dumps(rows).encode("utf-8")).hexdigest()


def freeze_plan(store: Store, draft_id: str, refreeze: bool = False) -> dict[str, Any]:
    """Freeze every pair's passage plan, or return the frozen one. Only `refreeze` (the person's request) writes a new
    revision; each pair keeps what it had before. Pairs go to the model in draft order: the first
    `MAX_PAIRS_TO_MODEL` pairs whose entry has text are `planned`, later ones `out_of_cap`; a pair whose entry has only
    metadata is `no_text` and has no plan. Refused while an entry a pair names is not resolved or its text is pending,
    while an acquisition runs, and once any pair was checked (V3)."""
    conn = store.conn
    with transaction(conn):
        draft = draft_row(store, draft_id)
        if draft["plan_revision"] and not refreeze:
            return {"revision": draft["plan_revision"], "frozen_at": draft["plan_frozen_at"], "frozen_now": False}
        if conn.execute("SELECT 1 FROM citation_checks c JOIN citation_pairs p ON p.id = c.pair_id WHERE p.draft_id = ?"
                        " LIMIT 1", (draft_id,)).fetchone():
            raise PlanRefused("already_checked", "Pairs of this draft were already checked; the plan they read stays")
        if _active_run(store, draft["research_id"]):
            raise PlanRefused("acquisition_running", "A text acquisition of this draft is still running")
        if waiting := reextraction_waiting(store, draft_id):
            raise PlanRefused("reextraction_pending", "The text of some cited works is being read again (equations);"
                              " wait for the re-extraction to end, then freeze the plan",
                              entries=sorted({w["entry_ordinal"] for w in waiting}))
        marks = ",".join("?" * len(PLAN_STATUSES))
        waiting = [r[0] for r in conn.execute(
            f"SELECT ordinal FROM citation_bib_entries WHERE draft_id = ? AND id IN (SELECT bib_entry_id FROM"
            f" citation_pairs WHERE draft_id = ? AND status IN ({marks})) AND (resolution_status IN ('pending', 'lookup_failed')"
            f" OR (resolution_status = 'resolved' AND resolved_source_version_id IS NOT NULL AND text_status = 'pending'))"
            f" ORDER BY ordinal", (draft_id, draft_id, *PLAN_STATUSES))]
        if waiting:
            raise PlanRefused("text_pending", "Some entries are not resolved or their text is not decided yet",
                              entries=waiting)
        revision, ts = draft["plan_revision"] + 1, now()
        entries = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM citation_bib_entries WHERE draft_id = ?", (draft_id,))}
        markers = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM citation_markers WHERE draft_id = ?", (draft_id,))}
        spans = [(m["char_start"], m["char_end"]) for m in markers.values()]
        planned = 0
        for pair in conn.execute(f"SELECT * FROM citation_pairs WHERE draft_id = ? AND status IN ({marks}) ORDER BY ordinal",
                                 (draft_id, *PLAN_STATUSES)).fetchall():
            entry = entries[pair["bib_entry_id"]]
            history = json.loads(pair["previous_plans_json"])
            if pair["plan_revision"] is not None:
                history.append({"revision": pair["plan_revision"], "status": pair["status"], "superseded_at": ts,
                                "plan": json.loads(pair["passage_plan_json"]) if pair["passage_plan_json"] else None,
                                "identity": json.loads(pair["plan_identity_json"]) if pair["plan_identity_json"] else None})
            svid = entry["text_source_version_id"]
            plan, checked = None, None
            if entry["resolution_status"] != "resolved" or entry["resolved_source_version_id"] is None:
                status = "unresolved"  # its record was purged since it resolved
            elif svid is None or available_text(store, svid) == "metadata_only":
                status = "no_text"
            elif planned >= MAX_PAIRS_TO_MODEL:
                status, checked = "out_of_cap", recheck_identity(store, entry)
            else:
                status, planned, checked = "planned", planned + 1, recheck_identity(store, entry)
                plan = _plan_for(store, svid, cited_sentence(draft["text"], markers[pair["marker_id"]], spans), revision, ts)
            # The identity result is the revision's own: a later upload or acquisition never changes its warning.
            conn.execute("UPDATE citation_pairs SET status = ?, passage_plan_json = ?, plan_revision = ?,"
                         " previous_plans_json = ?, plan_identity_json = ? WHERE id = ?",
                         (status, dumps(plan) if plan else None, revision, dumps(history),
                          dumps(checked) if checked else None, pair["id"]))
        conn.execute("UPDATE citation_drafts SET plan_revision = ?, plan_frozen_at = ? WHERE id = ?", (revision, ts, draft_id))
    return {"revision": revision, "frozen_at": ts, "frozen_now": True}


def _stale(store: Store, pair: dict[str, Any], entry: dict[str, Any] | None) -> bool:
    """Whether the check would no longer read what the frozen plan shows: the plan still stands until the person
    freezes again, and the change is shown. Decided by what the check uses (D105, after the V5 pilot): the entry's text
    is no longer settled, or now comes from another record or at another depth (a person's PDF added); a given passage
    is no longer one a model step may read of the record (a new file or extraction) or its text changed; the depth
    label or the count of passages not given would no longer be true; or the revision's identity result is not about
    the file and extraction the given passages come from. A change elsewhere in the record keeps the plan and is shown
    (`text_changed_elsewhere`). A plan frozen before fingerprints existed stays stale, as before."""
    if pair["plan_revision"] is None or entry is None:
        return False
    if entry["text_status"] != "settled":
        return True
    plan = json.loads(pair["passage_plan_json"]) if pair["passage_plan_json"] else None
    if plan is None:
        return pair["status"] == "no_text" and entry["available_text"] != "metadata_only"
    if entry["text_source_version_id"] != plan["source_version_id"] or entry["available_text"] != plan["available_text"]:
        return True
    if plan.get("fingerprint") is None:
        return True  # a plan frozen before fingerprints existed cannot show it read the same text
    checked = json.loads(pair["plan_identity_json"] or "null")
    if revision_identity_confirmed(store, pair) is False and (not checked or checked.get("result") != "unconfirmed"):
        return True  # no identity result kept, or one read on another file or extraction than the given passages
    current = {p["id"]: p for p in store.passages_for(plan["source_version_id"])}
    for passage_id, sha in zip(plan["passage_ids"], plan["passage_sha256"]):
        row = current.get(passage_id)
        if row is None or hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != sha:
            return True
    not_given = len(current) - len(plan["passage_ids"])
    depth = "abstract" if plan["available_text"] == "abstract" else "full_text" if not_given == 0 else "selected_passages"
    return depth != plan["depth"] or not_given != plan["passages_not_given"]


def text_changed_elsewhere(store: Store, pair: dict[str, Any]) -> bool:
    """Whether the record's readable text changed since the freeze somewhere the pair's plan does not use: its plan
    stays valid (`_stale` is false), and the change is recorded with the check and shown."""
    plan = json.loads(pair["passage_plan_json"]) if pair["passage_plan_json"] else None
    if not plan or plan.get("fingerprint") is None:
        return False
    return text_fingerprint(store.passages_for(plan["source_version_id"])) != plan["fingerprint"]


def reextraction_waiting(store: Store, draft_id: str) -> list[dict[str, Any]]:
    """The entries a pair names whose text comes from a PDF the background equation reader (Marker, the arXiv LaTeX
    source or Mathpix) is reading now or will still read by itself (`equations.background_read_waiting`): its reading
    writes a new extraction, so a plan frozen now would go stale minutes later (V5 pilot, D105). In entry order, with
    the reader's state."""
    from deixis.workflow.read import equations  # the equation service builds on the store; read only here
    marks = ",".join("?" * len(PLAN_STATUSES))
    rows = store.conn.execute(
        f"SELECT e.id, e.ordinal, e.text_source_version_id FROM citation_bib_entries e WHERE e.draft_id = ?"
        f" AND e.text_source_version_id IS NOT NULL AND e.id IN (SELECT bib_entry_id FROM citation_pairs WHERE"
        f" draft_id = ? AND status IN ({marks})) ORDER BY e.ordinal", (draft_id, draft_id, *PLAN_STATUSES)).fetchall()
    out = []
    for row in rows:
        for asset in store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                                        (row["text_source_version_id"],)):
            if (state := equations.background_read_waiting(store, asset["id"])) is not None:
                out.append({"entry_id": row["id"], "entry_ordinal": row["ordinal"], "asset_id": asset["id"],
                            "state": state["state"], "next_at": equations.next_try_at(state)})
                break
    return out


def pair_flags(store: Store, pair: dict[str, Any], entry_flags: list[str], entry: dict[str, Any] | None) -> list[str]:
    """A pair's flags: the entry's record flags, and `identity_unconfirmed` from the identity its frozen revision read
    (from the entry's current text before any freeze). The entry's current PDF never decides a frozen pair's warning,
    and a missing or mismatched revision result is unconfirmed, never clean."""
    flags = [f for f in entry_flags if f != "identity_unconfirmed"]
    if pair["plan_revision"] is not None:
        unconfirmed = revision_identity_confirmed(store, pair) is False
    else:
        unconfirmed = "identity_unconfirmed" in entry_flags
    return flags + ["identity_unconfirmed"] if unconfirmed else flags


# --------------------------------------------------------------------------------------------- preview and cost
#
# The V3 step's size before its method file and schema exist: everything but the frozen passages is an assumption,
# named here and returned with the estimate. The prices are the app's table (`spend.price_for`), the one Settings ›
# Usage reads; a model it does not list has an unknown cost, never zero.

INSTRUCTION_CHARS = (4000, 12000)  # V3's method text and output schema on top of `prompt.BASE_INSTRUCTIONS` (assumed)
PASSAGE_RECORD_CHARS = 500  # the JSON around one passage (`spend_estimate.PASSAGE_CHARS`)
PAIR_RECORD_CHARS = 600  # the cited sentence's record around its text
OUTPUT_TOKENS = (150, 1500)  # up to four parts, their assessments and up to eight quotes
REPAIRS_PER_PAIR = 1  # the high end repairs every pair once: the input sent again with the failed output after it


def cost_range(items: list[tuple[dict[str, Any], str]], choice: dict[str, Any] | None) -> dict[str, Any]:
    """The cost range of sending these (plan, sentence) pairs once each, for `choice` = {connection, model,
    reasoning_effort}: low is every pair once at the smallest instructions and output; high is the largest, the role's
    reasoning tokens and one repair per pair."""
    table = spend.price_table()
    out: dict[str, Any] = {
        "pairs": len(items), "connection": (choice or {}).get("connection"), "model": (choice or {}).get("model"),
        "reasoning_effort": (choice or {}).get("reasoning_effort"),
        "prices": {"version": table["version"], "as_of": table["as_of"]},
        "assumptions": {"chars_per_token": spend.CHARS_PER_TOKEN, "instruction_chars": list(INSTRUCTION_CHARS),
                        "passage_record_chars": PASSAGE_RECORD_CHARS, "pair_record_chars": PAIR_RECORD_CHARS,
                        "output_tokens": list(OUTPUT_TOKENS), "repairs_per_pair": REPAIRS_PER_PAIR}}
    if not choice or not choice.get("connection") or not choice.get("model"):
        return out | {"kind": None, "applies": None, "usd": "unknown", "reason": "no_model"}
    kind = spend.kind_of(choice["connection"])
    if kind != "api":
        # A subscription or a local model is not billed per call (as `spend_estimate`): no dollar range applies.
        return out | {"kind": kind, "applies": False, "usd": None}
    base = len(prompt.BASE_INSTRUCTIONS)
    reasoning = spend_estimate.REASONING_TOKENS.get(choice.get("reasoning_effort") or "", spend_estimate.REASONING_DEFAULT)
    low_in = high_in = 0
    for plan, sentence in items:
        variable = plan["passage_chars"] + PASSAGE_RECORD_CHARS * len(plan["passage_ids"]) + len(sentence) + PAIR_RECORD_CHARS
        low_in += (base + INSTRUCTION_CHARS[0] + variable) // spend.CHARS_PER_TOKEN
        high_in += (base + INSTRUCTION_CHARS[1] + variable) // spend.CHARS_PER_TOKEN
    count = len(items)
    low_out, high_out = count * OUTPUT_TOKENS[0], count * (OUTPUT_TOKENS[1] + reasoning)
    repairs = count * REPAIRS_PER_PAIR
    repair_in, repair_out = REPAIRS_PER_PAIR * (high_in + high_out), REPAIRS_PER_PAIR * high_out
    out |= {"kind": kind, "applies": True, "calls": [count, count + repairs],
            "input_tokens": [low_in, high_in + repair_in], "output_tokens": [low_out, high_out + repair_out]}
    prices = spend.price_for(choice["connection"], choice["model"])
    if prices is None:
        return out | {"usd": "unknown", "reason": "price_not_listed"}

    def dollars(tokens_in: int, tokens_out: int) -> float:
        return spend.cost_of(prices, {"input": tokens_in, "cached_input": 0, "cache_write": 0, "output": tokens_out})

    return out | {"usd": [dollars(low_in, low_out), dollars(high_in, high_out) + dollars(repair_in, repair_out)]}


def record_flags(store: Store, entry: dict[str, Any] | None) -> list[str]:
    """The flags an entry row carries (D86's title and retraction flags, and the identity of its PDFs)."""
    if entry is None:
        return []
    flags = []
    if entry["resolved_source_version_id"] is not None:
        stored = store.source(entry["resolved_source_version_id"])
        if entry["title"] and bibtex_ris.strict_title(entry["title"]) != bibtex_ris.strict_title(stored["title"] or ""):
            flags.append("title_mismatch")
        if stored["is_retracted"]:
            flags.append("retracted")
    missing = entry["text_status"] == "settled" and entry["available_text"] == "full_text" and entry["text_identity"] is None
    if entry["text_identity"] == "unconfirmed" or missing or (
            entry["upload_source_version_id"] is not None and entry["upload_identity"] != "doi"
            and entry["upload_identity"] != "title"):
        flags.append("identity_unconfirmed")  # a PDF this entry reads or was given does not name the work
    return flags


def _source_summary(store: Store, svid: str | None) -> dict[str, Any] | None:
    if svid is None:
        return None
    stored = store.source(svid)
    return {"source_version_id": stored["id"], "title": stored["title"], "authors": stored["authors"],
            "year": stored["year"], "doi": stored["doi"]}


def preview(store: Store, draft_id: str, choice: dict[str, Any] | None) -> dict[str, Any]:
    """What the V3 step would be sent, read from the frozen plan and nothing else: the selected pairs in draft order
    with their passages, the pairs beyond the cap, every counter, and the cost range. It changes nothing but one
    event that records which revision was shown, priced for which model (D99): a check runs only a revision shown
    with its model."""
    draft = draft_row(store, draft_id)
    if not draft["plan_revision"]:
        raise PlanRefused("plan_not_frozen", "The passage plan of this draft is not frozen yet")
    conn = store.conn
    entries = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM citation_bib_entries WHERE draft_id = ?", (draft_id,))}
    selected, beyond, items = [], [], []
    for row in conn.execute(
            "SELECT p.*, m.ordinal AS marker_ordinal, m.sentence, m.claim, m.claim_context FROM citation_pairs p JOIN citation_markers m"
            " ON m.id = p.marker_id WHERE p.draft_id = ? AND p.status IN ('planned', 'out_of_cap') ORDER BY p.ordinal",
            (draft_id,)):
        pair, entry = dict(row), entries.get(row["bib_entry_id"])
        item = {"id": pair["id"], "ordinal": pair["ordinal"], "marker_id": pair["marker_id"],
                "marker_ordinal": pair["marker_ordinal"], "sentence": pair["sentence"], "target": pair["target"],
                "bib_entry_id": pair["bib_entry_id"],
                "source": _source_summary(store, entry["resolved_source_version_id"] if entry else None),
                "flags": pair_flags(store, pair, record_flags(store, entry), entry)}
        if pair["status"] == "out_of_cap":
            beyond.append(item)
            continue
        plan = json.loads(pair["passage_plan_json"])
        items.append((plan, (pair["claim"] or pair["sentence"]) + (pair["claim_context"] or "")))
        selected.append(item | {
            "depth": plan["depth"], "available_text": plan["available_text"], "text_version": plan["text_version"],
            "text_source_version_id": plan["source_version_id"], "passage_ids": plan["passage_ids"],
            "passages_given": len(plan["passage_ids"]), "passages_total": plan["passages_total"],
            "passages_not_given": plan["passages_not_given"], "passage_chars": plan["passage_chars"],
            "stale": _stale(store, pair, entry), "text_changed_elsewhere": text_changed_elsewhere(store, pair),
            "identity": json.loads(pair["plan_identity_json"]) if pair["plan_identity_json"] else None})
    shown = {"plan_revision": draft["plan_revision"], "connection": (choice or {}).get("connection"),
             "model": (choice or {}).get("model"), "reasoning_effort": (choice or {}).get("reasoning_effort") or None}
    with transaction(conn):
        store._event(draft["research_id"], PREVIEW_EVENT, shown)
    return {"id": draft_id, "plan_revision": draft["plan_revision"], "plan_frozen_at": draft["plan_frozen_at"],
            "cap": MAX_PAIRS_TO_MODEL, "passages_per_pair": PASSAGES_PER_PAIR, "selected": selected,
            "out_of_cap": beyond, "counters": counters(store, draft_id), "cost": cost_range(items, choice)}


PREVIEW_EVENT = "citation_check_previewed"


def previewed(store: Store, research_id: str, revision: int, model: tuple[str, str, str | None]) -> str | None:
    """None when this plan revision was previewed for this model (connection, model, reasoning effort); else why not:
    `plan_not_previewed` or `model_not_previewed`."""
    shown = [json.loads(r[0]) for r in store.conn.execute(
        "SELECT payload_json FROM events WHERE research_id = ? AND type = ? ORDER BY id", (research_id, PREVIEW_EVENT))]
    shown = [s for s in shown if s.get("plan_revision") == revision]
    if not shown:
        return "plan_not_previewed"
    if not any((s.get("connection"), s.get("model"), s.get("reasoning_effort") or None) == tuple(model) for s in shown):
        return "model_not_previewed"
    return None


# ---------------------------------------------------------------------------------------------------------- view

def view(store: Store, draft_id: str) -> dict[str, Any]:
    """The draft as stored: markers in draft order with their pairs, entries, and the counters kept apart."""
    draft = draft_row(store, draft_id)
    conn = store.conn
    entries, entry_rows = {}, {}
    for row in conn.execute("SELECT * FROM citation_bib_entries WHERE draft_id = ? ORDER BY ordinal", (draft_id,)):
        entry_rows[row["id"]] = dict(row)
        source = None
        if row["resolved_source_version_id"] is not None:
            stored = store.source(row["resolved_source_version_id"])
            source = {"source_version_id": stored["id"], "work_id": stored["work_id"], "title": stored["title"],
                      "authors": stored["authors"], "year": stored["year"], "venue": stored["venue"], "doi": stored["doi"],
                      "is_retracted": None if stored["is_retracted"] is None else bool(stored["is_retracted"])}
        flags = record_flags(store, dict(row))
        entries[row["id"]] = {
            "id": row["id"], "ordinal": row["ordinal"], "origin": row["origin"], "key": row["entry_key"],
            "number": row["entry_number"], "raw_entry": row["raw_entry"],
            # The entry's own words, kept apart from the record: only `source` is the work as stored.
            "as_written": {"doi": row["doi"], "arxiv_id": row["arxiv_id"], "title": row["title"],
                           "authors": json.loads(row["authors_json"]), "year": row["year"], "year_suffix": row["year_suffix"]},
            "resolution": {"status": "resolved" if source is not None else (
                               "unresolved" if row["resolution_status"] == "resolved" else row["resolution_status"]),
                           "method": row["resolution_method"], "reason": row["resolution_reason"] or (
                               "record_removed" if row["resolution_status"] == "resolved" and source is None else None),
                           "origin": row["resolution_origin"], "openalex_id": row["resolved_openalex_id"],
                           "resolved_at": row["resolved_at"]},
            "upload": None if row["upload_source_version_id"] is None else {
                "source_version_id": row["upload_source_version_id"], "identity": row["upload_identity"]},
            "text": {"status": row["text_status"], "available": row["available_text"], "version": row["text_version"],
                     "origin": row["text_origin"], "source_version_id": row["text_source_version_id"],
                     "note": row["text_note"], "settled_at": row["text_settled_at"],
                     "identity": row["text_identity"]},
            "source": source, "flags": flags}
    checks = {row["pair_id"]: dict(row) for row in conn.execute(
        "SELECT c.* FROM citation_checks c JOIN citation_pairs p ON p.id = c.pair_id WHERE p.draft_id = ?"
        " ORDER BY c.created_at, c.rowid", (draft_id,))}
    pairs_by_marker: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT * FROM citation_pairs WHERE draft_id = ? ORDER BY ordinal", (draft_id,)):
        entry = entries.get(row["bib_entry_id"])
        check = checks.get(row["id"])
        plan = json.loads(row["passage_plan_json"]) if row["passage_plan_json"] else None
        pairs_by_marker.setdefault(row["marker_id"], []).append({
            "id": row["id"], "ordinal": row["ordinal"], "target": row["target"], "status": row["status"],
            "result": check["result"] if check else None, "depth": check["depth"] if check else None,
            "check": check_view(check),
            "bib_entry_id": row["bib_entry_id"], "source": entry["source"] if entry else None,
            "flags": pair_flags(store, dict(row), entry["flags"], entry_rows.get(row["bib_entry_id"])) if entry else [],
            "plan": None if row["plan_revision"] is None else {
                "revision": row["plan_revision"], "depth": plan["depth"] if plan else None,
                "passage_ids": plan["passage_ids"] if plan else [],
                "passages_total": plan["passages_total"] if plan else None,
                "passages_not_given": plan["passages_not_given"] if plan else None,
                "earlier_revisions": len(json.loads(row["previous_plans_json"])),
                "identity": json.loads(row["plan_identity_json"]) if row["plan_identity_json"] else None,
                "stale": _stale(store, dict(row), entry_rows.get(row["bib_entry_id"])),
                "text_changed_elsewhere": text_changed_elsewhere(store, dict(row))}})
    markers = [{
        "id": row["id"], "ordinal": row["ordinal"], "sentence": row["sentence"],
        "claim": row["claim"], "claim_context": row["claim_context"], "parse_reason": row["parse_reason"],
        "sentence_span": [row["sentence_start"], row["sentence_end"]], "span": [row["char_start"], row["char_end"]],
        "raw": row["raw"], "style": row["style"], "parse_status": row["parse_status"],
        "targets": json.loads(row["targets_json"]), "pairs": pairs_by_marker.get(row["id"], [])}
        for row in conn.execute("SELECT * FROM citation_markers WHERE draft_id = ? ORDER BY ordinal", (draft_id,))]
    return {"id": draft_id, "research_id": draft["research_id"], "format": draft["format"],
            "original_filename": draft["original_filename"], "text_sha256": draft["text_sha256"],
            "created_at": draft["created_at"],
            "bibliography": {"origin": draft["bibliography_origin"], "filename": draft["bibliography_filename"],
                             "errors": json.loads(draft["bibliography_errors_json"])},
            "text_acquisition": acquisition_state(store, draft["research_id"]),
            "reextraction_waiting": reextraction_waiting(store, draft_id),
            "check_run": check_state(store, draft["research_id"]),
            "plan": {"revision": draft["plan_revision"], "frozen_at": draft["plan_frozen_at"],
                     "cap": MAX_PAIRS_TO_MODEL, "passages_per_pair": PASSAGES_PER_PAIR},
            "counters": counters(store, draft_id), "markers": markers, "entries": list(entries.values())}


def counters(store: Store, draft_id: str) -> dict[str, Any]:
    """Each count from the stored rows, none folded into another (plan "Sayaçlar"). Ten citations of one work are one
    source and ten pairs. `sources_with_text` counts unique resolved records by the best text decided for them
    (`pending` until acquisition decides), `entries_with_text` the bibliography entries naming them. The plan counts are None until a plan is frozen; the V3 counts (sent, completed, located,
    could not check) stay None until a check of the draft started, not zero."""
    conn = store.conn

    def one(sql: str) -> int:
        return conn.execute(sql, (draft_id,)).fetchone()[0]

    marker_status = dict(conn.execute(
        "SELECT parse_status, COUNT(*) FROM citation_markers WHERE draft_id = ? GROUP BY parse_status", (draft_id,)).fetchall())
    pair_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM citation_pairs WHERE draft_id = ? GROUP BY status", (draft_id,)).fetchall())
    named = conn.execute(
        "SELECT resolved_source_version_id, CASE WHEN text_status = 'pending' THEN 'pending' ELSE available_text END"
        " FROM citation_bib_entries WHERE draft_id = ? AND resolution_status = 'resolved'"
        " AND resolved_source_version_id IS NOT NULL"
        " AND id IN (SELECT bib_entry_id FROM citation_pairs WHERE draft_id = ? AND bib_entry_id IS NOT NULL)",
        (draft_id, draft_id)).fetchall()
    by_entry = {depth: 0 for depth in (*AVAILABLE_TEXT, "pending")}
    by_record: dict[str, str] = {}
    rank = {"full_text": 0, "abstract": 1, "metadata_only": 2, "pending": 3}
    for record, depth in named:
        by_entry[depth] += 1
        # A record two entries name counts once, at the best text any of them has.
        if record not in by_record or rank[depth] < rank[by_record[record]]:
            by_record[record] = depth
    by_source = {depth: 0 for depth in (*AVAILABLE_TEXT, "pending")}
    for depth in by_record.values():
        by_source[depth] += 1
    draft = draft_row(store, draft_id)
    frozen = bool(draft["plan_revision"])
    to_send = one("SELECT COUNT(*) FROM citation_pairs WHERE draft_id = ? AND status = 'planned'"
                  " AND passage_plan_json IS NOT NULL")
    checked_pairs = one("SELECT COUNT(*) FROM citation_pairs WHERE draft_id = ? AND status IN ('done', 'could_not_check')")
    checks = check_counts(store, draft) if frozen and check_started(store, draft["research_id"]) else None
    return {
        "occurrences": sum(marker_status.values()),
        "occurrences_recognized": marker_status.get("recognized", 0),
        "occurrences_ambiguous": marker_status.get("ambiguous", 0),
        "occurrences_unrecognized": marker_status.get("unrecognized", 0),
        "sources_unique": one("SELECT COUNT(DISTINCT bib_entry_id) FROM citation_pairs WHERE draft_id = ?"),
        "sources_resolved": one(
            "SELECT COUNT(DISTINCT p.bib_entry_id) FROM citation_pairs p JOIN citation_bib_entries e ON e.id = p.bib_entry_id"
            " WHERE p.draft_id = ? AND e.resolution_status = 'resolved' AND e.resolved_source_version_id IS NOT NULL"),
        # Unit: unique resolved records. `entries_with_text` counts bibliography entries.
        "sources_with_text": by_source,
        "entries_with_text": by_entry,
        "pairs": sum(pair_status.values()),
        "pairs_by_status": {status: pair_status.get(status, 0) for status in STATUSES},
        "pairs_in_plan": to_send + checked_pairs + pair_status.get("out_of_cap", 0) if frozen else None,
        "pairs_out_of_cap": pair_status.get("out_of_cap", 0),
        "pairs_to_send": to_send if frozen else None,
        # None until a check of this draft started (V3, D99), never zero for "not asked". `done` is a valid completed
        # assessment; `found` the done pairs with a located passage; `could_not_check` is in neither.
        **(checks or dict.fromkeys(CHECK_COUNTERS)),
    }


# ------------------------------------------------------------------------------------------------- the check (V3)
#
# Each planned pair of the frozen plan goes, in draft order, through one model step (`flow._model_step`: a stored
# StepInput, the strict schema, no tools, the model the check names and no other, one schema repair) under the draft's
# internal research. The step is keyed by pair and plan revision: a pair whose step succeeded or whose repair ran out
# is never sent again, in this run or a later one. Only code turns the output into a result (`derive_result`): a
# valid, completed assessment gives `done` with a result; an output still invalid after its repair gives
# `could_not_check` with no result, its raw output and issues kept. A provider failure or a person's stop pauses the
# run and leaves the pair `planned`: that is no verdict on the pair, and the next check sends it.

TASK = "citation_check"
CHECK_PHASE = "check"
# The research question every check StepInput carries; the citing sentence itself is in `citation_check_target`.
CHECK_QUESTION = ("Which parts of the citing sentence in citation_check_target do the given passages of the cited work"
                  " state?")
CHECK_COUNTERS = ("pairs_sent_to_model", "pairs_done", "pairs_found", "pairs_not_found_in_given",
                  "pairs_could_not_check")
FOUND = ("found_whole", "found_partial")


def check_key(pair_id: str, revision: int) -> str:
    return f"{TASK}:{pair_id}:r{revision}"


def check_model(store: Store, choice: dict[str, Any] | None) -> tuple[str, str, str | None] | None:
    """The model the check runs on: the one the request names, else the literature model in Settings, the one the
    preview prices. None when neither names a connection and a model: the check is refused, never sent elsewhere."""
    if not choice or not choice.get("model"):
        default = store.setting("literature") or {}
        choice = {"connection": default.get("model_connection"), "model": default.get("model"),
                  "reasoning_effort": default.get("reasoning_effort")}
    if not choice.get("connection") or not choice.get("model"):
        return None
    return choice["connection"], choice["model"], choice.get("reasoning_effort") or None


def check_started(store: Store, research_id: str) -> bool:
    return store.conn.execute(
        "SELECT 1 FROM runs WHERE research_id = ? AND kind = ? AND json_extract(target_json, '$.phase') = ? LIMIT 1",
        (research_id, KIND, CHECK_PHASE)).fetchone() is not None


def check_counts(store: Store, draft: dict[str, Any]) -> dict[str, int]:
    """The V3 counts of the current plan revision. Sent: pairs whose step reached the model at least once (a paused
    pair included). A `could_not_check` pair is never a done or a not-found pair."""
    revision = draft["plan_revision"]
    rows = store.conn.execute(
        "SELECT c.status, c.result FROM citation_checks c JOIN citation_pairs p ON p.id = c.pair_id"
        " WHERE p.draft_id = ? AND c.plan_revision = ?", (draft["id"], revision)).fetchall()
    sent = store.conn.execute(
        "SELECT COUNT(DISTINCT s.operation_key) FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND r.kind = ? AND s.operation_key LIKE ? AND EXISTS (SELECT 1 FROM model_sessions m WHERE m.step_id = s.id)",
        (draft["research_id"], KIND, f"{TASK}:%:r{revision}")).fetchone()[0]
    done = [r["result"] for r in rows if r["status"] == "done"]
    return {"pairs_sent_to_model": sent, "pairs_done": len(done),
            "pairs_found": sum(1 for r in done if r in FOUND),
            "pairs_not_found_in_given": sum(1 for r in done if r == "not_found_in_given"),
            "pairs_could_not_check": sum(1 for r in rows if r["status"] == "could_not_check")}


def _open_check_run(store: Store, research_id: str, draft_id: str, revision: int, model: tuple[str, str, str | None],
                    pairs: int, package_hash: str) -> dict[str, Any]:
    """A `citation_check` run that is running from the start (the worker has no handler for the kind), with a model
    call budget of every pair and its one repair, and the model and method package it froze."""
    with transaction(store.conn):
        if _active_run(store, research_id):
            raise PlanRefused("run_active", "A run of this draft is still active")
        research = store.research(research_id)
        run_id, ts = new_id("run"), now()
        store.conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, target_json, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, 'running', 'claim_check', ?, ?, ?, ?)",
            (run_id, research_id, research["current_scope_revision"], KIND,
             dumps({"max_model_calls": pairs * (1 + MAX_SCHEMA_REPAIRS), "max_provider_requests": 0}),
             dumps({"draft_id": draft_id, "phase": CHECK_PHASE, "plan_revision": revision, "pairs": pairs,
                    "model": {"connection": model[0], "model": model[1], "reasoning_effort": model[2]},
                    "skill_package_hash": package_hash}), ts, ts))
        store._event(research_id, "run_started", {"kind": KIND, "phase": CHECK_PHASE}, run_id)
    return store.run(run_id)


def _recorded(store: Store, research_id: str, key: str, kind: str = KIND) -> dict[str, Any] | None:
    """A pair's step that already ended for good in any check run of the draft: its succeeded output, or its invalid
    output after the repair ran out (or a message too large to send). Read back, never sent again. `kind` is the run
    kind that sends such steps (a statement check's item steps too, slice R1)."""
    row = store.conn.execute(
        "SELECT s.* FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND r.kind = ?"
        " AND s.operation_key = ? AND (s.status = 'succeeded' OR (s.status = 'failed'"
        " AND s.error_code IN ('invalid_model_output', 'message_too_large'))) ORDER BY s.rowid DESC LIMIT 1",
        (research_id, kind, key)).fetchone()
    if row is None:
        return None
    output = json.loads(row["output_json"]) if row["output_json"] else {}
    if row["status"] == "succeeded":
        return output
    return output | {"invalid": True, "issues": json.loads(row["error_json"] or "[]"),
                     "message_too_large": row["error_code"] == "message_too_large"}


def _raw_output(store: Store, step_input_id: str | None) -> str | None:
    row = store.conn.execute("SELECT raw_output FROM model_sessions WHERE step_input_id = ? AND raw_output IS NOT NULL"
                             " ORDER BY rowid DESC LIMIT 1", (step_input_id,)).fetchone() if step_input_id else None
    return row["raw_output"] if row else None


def _check_target(pair: dict[str, Any], plan: dict[str, Any], sentence: str, context: str | None = None) -> dict[str, Any]:
    target = {"pair_id": pair["id"], "sentence": sentence, "assessed_source_id": plan["source_version_id"],
              "depth": plan["depth"], "passages_not_given": plan["passages_not_given"]}
    return target | ({"context": context} if context else {})


async def _send(flow: Any, run: dict[str, Any], model: tuple[str, str, str | None], pair: dict[str, Any],
                sentence: str, key: str, context: str | None = None) -> dict[str, Any]:
    """One pair's model step. The last look before each send (the first and the repair): a stop, a changed method
    package, or a plan that went stale since the preview fails the run; the StepInput is built from the frozen passage
    ids, read again for each attempt."""
    store, run_id = flow.store, run["id"]
    plan = json.loads(pair["passage_plan_json"])
    scope = {"question": CHECK_QUESTION, "language_hint": None, "steering": None, "providers": [],
             "model_connection": model[0], "requested_model": model[1], "reasoning_effort": model[2]}

    def gate() -> None:
        flow._checkpoint(run_id)
        if run["target"]["skill_package_hash"] != flow.deps.package.package_hash:
            flow._fail(run_id, "skill_package_changed")
        fresh = dict(store.conn.execute("SELECT * FROM citation_pairs WHERE id = ?", (pair["id"],)).fetchone())
        entry = store.conn.execute("SELECT * FROM citation_bib_entries WHERE id = ?", (pair["bib_entry_id"],)).fetchone()
        if (fresh["plan_revision"] != run["target"]["plan_revision"] or fresh["status"] != "planned"
                or _stale(store, fresh, dict(entry) if entry else None)):
            flow._fail(run_id, "plan_stale", {"pair_id": pair["id"]})

    def build(step_id: str) -> dict[str, Any]:
        rows = [store.passage(passage_id) for passage_id in plan["passage_ids"]]
        payload = flow._step_input(run, scope, step_id, TASK, [], [plan["source_version_id"]], rows, [], model)
        return payload | {"citation_check_target": _check_target(pair, plan, sentence, context)}

    return await flow.deps.limiter.run(f"{run_id}:{key}", lambda: flow._model_step(
        run, scope, key, TASK, model=model, limiter=flow.deps.limiter, send_gate=gate, step_input_builder=build))


def _provenance(store: Store, step_input_id: str | None) -> dict[str, Any]:
    """Which run sent a step and on which model, read from its stored StepInput and its last model session, never
    from the request now running: a step read back after a lost result keeps the model it was really sent to."""
    row = store.conn.execute("SELECT run_id, payload_json FROM step_inputs WHERE id = ?",
                             (step_input_id,)).fetchone() if step_input_id else None
    session = store.conn.execute(
        "SELECT run_id, connection, requested_model, resolved_model, reasoning_effort, raw_output FROM model_sessions"
        " WHERE step_input_id = ? ORDER BY rowid DESC LIMIT 1", (step_input_id,)).fetchone() if step_input_id else None
    asked = (json.loads(row["payload_json"]).get("model") or {}) if row else {}
    return {"run_id": session["run_id"] if session else row["run_id"] if row else None,
            "connection": session["connection"] if session else asked.get("connection"),
            "requested_model": session["requested_model"] if session else asked.get("requested_model"),
            "reasoning_effort": session["reasoning_effort"] if session else None,
            "resolved_model": session["resolved_model"] if session else None,
            "sent": session is not None}


def _store_check(store: Store, run: dict[str, Any], pair: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """The code's verdict on one ended step, stored with the pair's new status in one write. A valid output becomes
    `done` with a result only when `derive_result` reads one from the backend's own located quotes, with the
    sentence's coverage derived from the parts' positions (`citation_check_covers`), never taken from the model alone;
    anything else is `could_not_check` with no result. Either keeps the raw output, the depth and the flags of the
    revision it read, and the run and model of the step that answered."""
    plan = json.loads(pair["passage_plan_json"])
    step_input_id = output.get("step_input_id")
    anchors, result_doc = None, None
    if output.get("invalid"):
        code = "message_too_large" if output.get("message_too_large") else "invalid_model_output"
        outcome = {"status": "could_not_check", "result": None,
                   "error": {"code": code, "issues": output.get("issues") or []}}
    else:
        result_doc = output["result"]
        payload = store.step_input_payload(step_input_id)
        anchors = contracts.citation_check_anchors(payload, result_doc)
        parts = [PartAssessment(part["assessment"], tuple(a["located"] for a in located))
                 for part, located in zip(result_doc["parts"], anchors)]
        covers = result_doc["covers_whole_sentence"] is True and contracts.citation_check_covers(
            payload["citation_check_target"]["sentence"], result_doc["parts"])
        outcome = check_outcome(parts, covers)
        if outcome["error"] is not None:
            outcome["error"] = {"code": outcome["error"], "issues": []}
    entry = store.conn.execute("SELECT * FROM citation_bib_entries WHERE id = ?", (pair["bib_entry_id"],)).fetchone()
    entry = dict(entry) if entry else None
    flags = pair_flags(store, pair, record_flags(store, entry), entry)
    kinds = sorted({a["passage_kind"] for part in anchors or [] for a in part if a["located"] and a["passage_kind"]})
    basis = {"depth": plan["depth"], "passages_given": len(plan["passage_ids"]), "passages_total": plan["passages_total"],
             "passages_not_given": plan["passages_not_given"], "source_version_id": plan["source_version_id"],
             "located_passage_kinds": kinds, "text_changed_elsewhere": text_changed_elsewhere(store, pair)}
    raw = _raw_output(store, step_input_id)
    record = _provenance(store, step_input_id)
    sent_by = record.pop("run_id") or run["id"]
    with transaction(store.conn):
        store.conn.execute(
            "INSERT INTO citation_checks (id, pair_id, step_id, output_json, located_anchors_json, depth, result, status,"
            " error_json, created_at, plan_revision, run_id, step_input_id, model_json, raw_output, flags_json, basis_json)"
            " VALUES (?, ?, (SELECT s.id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
            " AND s.operation_key = ? ORDER BY s.rowid DESC LIMIT 1), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("chk"), pair["id"], run["research_id"], check_key(pair["id"], pair["plan_revision"]),
             dumps(result_doc) if result_doc is not None else None, dumps(anchors) if anchors is not None else None,
             plan["depth"], outcome["result"], outcome["status"],
             dumps(outcome["error"]) if outcome["error"] is not None else None, now(), pair["plan_revision"], sent_by,
             step_input_id, dumps(record), raw, dumps(flags), dumps(basis)))
        store.conn.execute("UPDATE citation_pairs SET status = ? WHERE id = ?", (outcome["status"], pair["id"]))
    return outcome


async def check(store: Store, flow: Any, draft_id: str, plan_revision: int | None,
                choice: dict[str, Any] | None) -> dict[str, Any]:
    """Check every planned pair of the frozen plan not checked yet, in draft order (at most `MAX_PAIRS_TO_MODEL`: the
    freeze planned no more). Refused before anything is sent when no plan is frozen, when `plan_revision` is not the
    frozen revision, when no model is named and Settings names none, when this revision was never previewed or was
    previewed for another model (`previewed`), while a run of the draft is active, or when a planned pair's plan went stale since its freeze (its text, file, extraction or identity result
    changed). The person then freezes again and previews the new plan: a check never reads another plan than the one
    shown, and never silently re-freezes."""
    from deixis.workflow.run.flow import RunStopped  # flow builds on most of the workflow; read only when checking
    draft = draft_row(store, draft_id)
    revision = draft["plan_revision"]
    if not revision:
        raise PlanRefused("plan_not_frozen", "The passage plan of this draft is not frozen yet")
    if plan_revision != revision:
        raise PlanRefused("plan_revision_mismatch", "The plan was frozen again since this preview", plan_revision=revision)
    model = check_model(store, choice)
    if model is None:
        raise PlanRefused("no_model", "No model is named for the check and Settings names no literature model")
    if (unshown := previewed(store, draft["research_id"], revision, model)) is not None:
        raise PlanRefused(unshown, "This plan revision was not previewed for this model; preview it first",
                          plan_revision=revision, model={"connection": model[0], "model": model[1],
                                                         "reasoning_effort": model[2]})
    research_id = draft["research_id"]
    if _active_run(store, research_id):
        raise PlanRefused("run_active", "A run of this draft is still active")
    conn = store.conn
    pending = [dict(r) for r in conn.execute(
        "SELECT p.* FROM citation_pairs p WHERE p.draft_id = ? AND p.status = 'planned' AND p.plan_revision = ?"
        " AND p.passage_plan_json IS NOT NULL AND NOT EXISTS (SELECT 1 FROM citation_checks c WHERE c.pair_id = p.id"
        " AND c.plan_revision = p.plan_revision) ORDER BY p.ordinal", (draft_id, revision))]
    entries = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM citation_bib_entries WHERE draft_id = ?", (draft_id,))}
    stale = [p["ordinal"] for p in pending if _stale(store, p, entries.get(p["bib_entry_id"]))]
    if stale:
        raise PlanRefused("plan_stale", "The text of some planned pairs changed since the plan was frozen; freeze the"
                          " plan again and preview it", pairs=stale)
    if not pending:
        return {"status": "nothing_to_check", "run_id": None, "pause_reason": None, "error": None, "checked_now": 0}
    markers = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM citation_markers WHERE draft_id = ?", (draft_id,))}
    spans = [(m["char_start"], m["char_end"]) for m in markers.values()]
    run = _open_check_run(store, research_id, draft_id, revision, model, len(pending), flow.deps.package.package_hash)
    checked = 0
    try:
        for pair in pending:
            key = check_key(pair["id"], revision)
            output = _recorded(store, research_id, key)
            if output is None:
                marker = markers[pair["marker_id"]]
                output = await _send(flow, run, model, pair, cited_sentence(draft["text"], marker, spans), key,
                                     marker.get("claim_context"))
            _store_check(store, run, pair, output)
            checked += 1
            flow._checkpoint(run["id"])
    except RunStopped:
        stopped = store.run(run["id"])
        return {"status": stopped["status"], "run_id": run["id"], "pause_reason": stopped["pause_reason"],
                "error": stopped["error"], "checked_now": checked}
    except BaseException:
        if store.run(run["id"])["status"] in ACTIVE_RUN_STATUSES:
            store.update_run(run["id"], event="run_failed", status="failed", error_json={"code": "citation_check_failed"})
        raise
    store.update_run(run["id"], event="run_completed", status="completed")
    return {"status": "completed", "run_id": run["id"], "pause_reason": None, "error": None, "checked_now": checked}


def check_state(store: Store, research_id: str) -> dict[str, Any] | None:
    """The latest check run of the draft: its status, and why it stopped when it did."""
    row = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = ? AND json_extract(target_json, '$.phase') = ?"
                             " ORDER BY created_at DESC, rowid DESC LIMIT 1", (research_id, KIND, CHECK_PHASE)).fetchone()
    if row is None:
        return None
    run = store.run(row["id"])
    return {"run_id": run["id"], "status": run["status"], "pause_reason": run["pause_reason"], "error": run["error"],
            "plan_revision": run["target"]["plan_revision"], "model": run["target"]["model"]}


def check_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """One stored check as the view and the export show it: its status and result, the depth and flags of the
    revision it read, the parts with the backend's located words, and, for a check that could not be completed, its
    error and raw output."""
    if row is None:
        return None
    output = json.loads(row["output_json"]) if row["output_json"] else None
    anchors = json.loads(row["located_anchors_json"]) if row["located_anchors_json"] else None
    parts = None
    if output is not None:
        parts = [{"text": part["text"], "assessment": part["assessment"], "evidence": located}
                 for part, located in zip(output["parts"], anchors or [[] for _ in output["parts"]])]
    return {"status": row["status"], "result": row["result"], "plan_revision": row["plan_revision"],
            "depth": row["depth"], "basis": json.loads(row["basis_json"]) if row["basis_json"] else None,
            "flags": json.loads(row["flags_json"] or "[]"), "parts": parts,
            "covers_whole_sentence": output["covers_whole_sentence"] if output is not None else None,
            "error": json.loads(row["error_json"]) if row["error_json"] else None,
            "raw_output": row["raw_output"] if row["status"] == "could_not_check" else None,
            "model": json.loads(row["model_json"]) if row["model_json"] else None, "run_id": row["run_id"],
            "step_input_id": row["step_input_id"], "checked_at": row["created_at"]}


# -------------------------------------------------------------------------------------------------------- export

EXPORT_COLUMNS = ("pair", "marker", "sentence", "claim", "target", "source_title", "source_year", "source_doi", "status",
                  "result", "depth", "passages_given", "passages_not_given", "located_passage_kinds", "flags",
                  "error", "located_quotes")


def export_rows(store: Store, draft_id: str) -> list[dict[str, Any]]:
    """One row per pair in draft order: the sentence, the work as its record names it, the status and the result kept
    apart (a `could_not_check` pair has none), the depth, the flags, the error, and the backend's located words."""
    report = view(store, draft_id)
    rows = []
    for marker in report["markers"]:
        for pair in marker["pairs"]:
            check_row = pair["check"] or {}
            source = pair["source"] or {}
            basis = check_row.get("basis") or {}
            quotes = [a["anchor_text"] for part in check_row.get("parts") or [] for a in part["evidence"] if a["located"]]
            rows.append({"pair": pair["ordinal"], "marker": marker["raw"], "sentence": marker["sentence"],
                         "claim": marker["claim"],
                         "target": pair["target"], "source_title": source.get("title"), "source_year": source.get("year"),
                         "source_doi": source.get("doi"), "status": pair["status"], "result": pair["result"],
                         "depth": check_row.get("depth") or (pair["plan"] or {}).get("depth"),
                         "passages_given": basis.get("passages_given"), "passages_not_given": basis.get("passages_not_given"),
                         "located_passage_kinds": basis.get("located_passage_kinds") or [],
                         "flags": check_row["flags"] if check_row else pair["flags"],
                         "error": (check_row.get("error") or {}).get("code"), "located_quotes": quotes})
    return rows


def export(store: Store, draft_id: str, fmt: str) -> str:
    """The rows as CSV or Markdown; lists are joined with ` | `. A pair that could not be checked keeps its row."""
    import csv
    import io
    rows = export_rows(store, draft_id)

    def cell(value: Any) -> str:
        if isinstance(value, list):
            return " | ".join(str(v) for v in value)
        return "" if value is None else str(value)

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(EXPORT_COLUMNS)
        for row in rows:
            writer.writerow([cell(row[c]) for c in EXPORT_COLUMNS])
        return out.getvalue()
    lines = ["| " + " | ".join(EXPORT_COLUMNS) + " |", "|" + "---|" * len(EXPORT_COLUMNS)]
    for row in rows:
        lines.append("| " + " | ".join(cell(row[c]).replace("|", "\\|").replace("\n", " ") for c in EXPORT_COLUMNS) + " |")
    return "\n".join(lines) + "\n"

"""Verify Citations (V1, D86): a draft's markers, its bibliography entries and their (occurrence, entry) pairs, the
lookup that names each entry's OpenAlex record, the view and the delete. No model call: that is V3.

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
from pathlib import Path
from typing import Any

import httpx

from deixis.documents import draft_parse
from deixis.domain.citation_check import RESULTS, STATUSES
from deixis.imports import bibtex_ris
from deixis.providers import openalex
from deixis.providers.common import normalize_doi
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.store import ARXIV_DOI_PREFIX, NotFound, Store

KIND = "citation_check"
# Title resolution: a record is the entry's work only when it is the one search result whose title has at least this
# `difflib` ratio to the entry's title (both through `bibtex_ris.strict_title`) and no year that differs.
TITLE_MATCH_MIN = 0.93
TITLE_CANDIDATES = 5
ET_AL_MIN_AUTHORS = 3  # `Smith et al.` names a work of three or more authors (`authors_match`)
DOI_BATCH = openalex.MAX_IDS_PER_REQUEST


# ------------------------------------------------------------------------------------------------------- creating

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
                         "title": entry.title, "authors": entry.authors, "year": entry.year, "suffix": None})
        return fmt, rows
    for item in draft.list_entries:
        fields = draft_parse.written_entry_fields(item.raw)
        rows.append({"origin": draft.list_origin, "key": item.key, "number": item.number, "raw": item.raw,
                     "doi": fields["doi"], "arxiv_id": fields["arxiv_id"], "title": fields["title"],
                     "authors": fields["authors"], "year": fields["year"], "suffix": fields["year_suffix"]})
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
            surnames = [draft_parse.surname_key(a) for a in entry["authors"]]
            if entry["year"] != target.year or not all(cited) or not authors_match(cited, target.et_al, surnames):
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
                " char_end, raw, style, parse_status, targets_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (marker_id, draft_id, ordinal, draft.text[marker.sentence_start:marker.sentence_end],
                 marker.sentence_start, marker.sentence_end, marker.start, marker.end, marker.raw, marker.style, status,
                 dumps([t.view() for t in marker.targets])))
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


def delete(store: Store, draft_id: str) -> None:
    """Purge the draft's internal research; the draft and everything read from it go with it."""
    with transaction(store.conn):
        research_id = draft_row(store, draft_id)["research_id"]
        store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", (now(), research_id))
        store.purge_research(research_id)


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


# ---------------------------------------------------------------------------------------------------------- view

def view(store: Store, draft_id: str) -> dict[str, Any]:
    """The draft as stored: markers in draft order with their pairs, entries, and the counters kept apart."""
    draft = draft_row(store, draft_id)
    conn = store.conn
    entries = {}
    for row in conn.execute("SELECT * FROM citation_bib_entries WHERE draft_id = ? ORDER BY ordinal", (draft_id,)):
        source = None
        if row["resolved_source_version_id"] is not None:
            stored = store.source(row["resolved_source_version_id"])
            source = {"source_version_id": stored["id"], "work_id": stored["work_id"], "title": stored["title"],
                      "authors": stored["authors"], "year": stored["year"], "venue": stored["venue"], "doi": stored["doi"],
                      "is_retracted": None if stored["is_retracted"] is None else bool(stored["is_retracted"])}
        flags = []
        if source is not None and row["title"] and \
                bibtex_ris.strict_title(row["title"]) != bibtex_ris.strict_title(source["title"] or ""):
            flags.append("title_mismatch")
        if source is not None and source["is_retracted"]:
            flags.append("retracted")
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
            "source": source, "flags": flags}
    checks = {row["pair_id"]: dict(row) for row in conn.execute(
        "SELECT c.* FROM citation_checks c JOIN citation_pairs p ON p.id = c.pair_id WHERE p.draft_id = ?"
        " ORDER BY c.created_at, c.rowid", (draft_id,))}
    pairs_by_marker: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT * FROM citation_pairs WHERE draft_id = ? ORDER BY ordinal", (draft_id,)):
        entry = entries.get(row["bib_entry_id"])
        check = checks.get(row["id"])
        pairs_by_marker.setdefault(row["marker_id"], []).append({
            "id": row["id"], "ordinal": row["ordinal"], "target": row["target"], "status": row["status"],
            "result": check["result"] if check else None, "depth": check["depth"] if check else None,
            "bib_entry_id": row["bib_entry_id"], "source": entry["source"] if entry else None,
            "flags": entry["flags"] if entry else []})
    markers = [{
        "id": row["id"], "ordinal": row["ordinal"], "sentence": row["sentence"],
        "sentence_span": [row["sentence_start"], row["sentence_end"]], "span": [row["char_start"], row["char_end"]],
        "raw": row["raw"], "style": row["style"], "parse_status": row["parse_status"],
        "targets": json.loads(row["targets_json"]), "pairs": pairs_by_marker.get(row["id"], [])}
        for row in conn.execute("SELECT * FROM citation_markers WHERE draft_id = ? ORDER BY ordinal", (draft_id,))]
    return {"id": draft_id, "research_id": draft["research_id"], "format": draft["format"],
            "original_filename": draft["original_filename"], "text_sha256": draft["text_sha256"],
            "created_at": draft["created_at"],
            "bibliography": {"origin": draft["bibliography_origin"], "filename": draft["bibliography_filename"],
                             "errors": json.loads(draft["bibliography_errors_json"])},
            "counters": counters(store, draft_id), "markers": markers, "entries": list(entries.values())}


def counters(store: Store, draft_id: str) -> dict[str, Any]:
    """Each count from the stored rows, none folded into another (plan "Sayaçlar"). Ten citations of one work are one
    source and ten pairs. Text acquisition is V2: `sources_with_text` is None until it exists, not zero."""
    conn = store.conn

    def one(sql: str) -> int:
        return conn.execute(sql, (draft_id,)).fetchone()[0]

    marker_status = dict(conn.execute(
        "SELECT parse_status, COUNT(*) FROM citation_markers WHERE draft_id = ? GROUP BY parse_status", (draft_id,)).fetchall())
    pair_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM citation_pairs WHERE draft_id = ? GROUP BY status", (draft_id,)).fetchall())
    check_sql = "SELECT COUNT(DISTINCT c.pair_id) FROM citation_checks c JOIN citation_pairs p ON p.id = c.pair_id WHERE p.draft_id = ?"
    return {
        "occurrences": sum(marker_status.values()),
        "occurrences_recognized": marker_status.get("recognized", 0),
        "occurrences_ambiguous": marker_status.get("ambiguous", 0),
        "occurrences_unrecognized": marker_status.get("unrecognized", 0),
        "sources_unique": one("SELECT COUNT(DISTINCT bib_entry_id) FROM citation_pairs WHERE draft_id = ?"),
        "sources_resolved": one(
            "SELECT COUNT(DISTINCT p.bib_entry_id) FROM citation_pairs p JOIN citation_bib_entries e ON e.id = p.bib_entry_id"
            " WHERE p.draft_id = ? AND e.resolution_status = 'resolved' AND e.resolved_source_version_id IS NOT NULL"),
        "sources_with_text": None,
        "pairs": sum(pair_status.values()),
        "pairs_by_status": {status: pair_status.get(status, 0) for status in STATUSES},
        "pairs_out_of_cap": pair_status.get("out_of_cap", 0),
        "pairs_sent_to_model": one(check_sql + " AND c.step_id IS NOT NULL"),
        "pairs_done": one(check_sql + " AND c.status = 'done'"),
        "pairs_found": one(check_sql + f" AND c.result IN ('{RESULTS[0]}', '{RESULTS[1]}')"),
        "pairs_could_not_check": one(check_sql + " AND c.status = 'could_not_check'"),
    }

"""Storing what `domain/record_identity` decided about two records, and taking a merge back (SW6.9).

A link is added, never edited: a verdict that replaces an earlier one closes it with `superseded` instead of
overwriting it, so the reason a work was joined stays readable. A merge the user undoes is closed with `undone` and is
never made again by a later search, because the user's decision outranks the rule (AGENTS.md, User Authority).

Works are library-wide (D46), so links are too: `record_links` carries no research identifier, and a merge made in one
`sw` research is visible in every research holding the same records. Only a search on the `sw` workflow writes here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from deixis.domain.record_identity import (TITLE_RELATED, Verdict, classify_pair, comparable_title, record_kind,
                                           trigrams)
from deixis.storage.db import dumps, new_id, now, transaction

if TYPE_CHECKING:  # store imports this module, so the type is a name here and never an import at run time
    from deixis.workflow.store import Store

RECORD_FIELDS = ("doi", "title", "authors", "year", "version_label", "publication_type")


# ---- writing and reading links -----------------------------------------------------------


def save_link(store: Store, a: str, b: str, verdict: Verdict, source: str) -> dict[str, Any] | None:
    """Store this verdict for the pair, merging the two works when it says so; the caller holds the transaction.

    Returns the link row, or None when the user has undone this pair and it is left alone.
    """
    conn = store.conn
    first, second = sorted((a, b))
    if conn.execute("SELECT 1 FROM record_links WHERE source_version_id = ? AND other_source_version_id = ?"
                    " AND closed_reason = 'undone' LIMIT 1", (first, second)).fetchone():
        return None
    current = conn.execute("SELECT * FROM record_links WHERE source_version_id = ? AND other_source_version_id = ?"
                           " AND closed_at IS NULL", (first, second)).fetchone()
    if current is not None:
        # The same reading of the same pair (a resumed run, a record found again) adds nothing, and a joined work is
        # not split again by a weaker reading; only the user undoes a merge.
        if (current["link_kind"], current["rule"]) == (verdict.link_kind, verdict.rule) or current["merged"]:
            return dict(current)
        conn.execute("UPDATE record_links SET closed_at = ?, closed_reason = 'superseded' WHERE id = ?",
                     (now(), current["id"]))
    link_kind, rule, merged, undo = verdict.link_kind, verdict.rule, 0, None
    if verdict.merge:
        work_a, work_b = store.source(a)["work_id"], store.source(b)["work_id"]
        if work_a != work_b:
            if len(_published_dois(store, work_a) | _published_dois(store, work_b)) > 1:
                # Two published records never share a work, by any path (SW6.5).
                link_kind, rule = "related_suspected", "work_already_has_published"
            else:
                keep, drop = _keep_and_drop(store, work_a, work_b)
                undo = {"keep_work_id": keep, **store._join_works(keep, drop)}
                merged = 1
    row_id = new_id("lnk")
    conn.execute(
        "INSERT INTO record_links (id, source_version_id, other_source_version_id, link_kind, rule, source,"
        " parent_source_version_id, title_similarity, abstract_similarity, author_agreement, year_gap, merged,"
        " undo_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row_id, first, second, link_kind, rule, source, _parent(a, b, verdict.parent), verdict.title_similarity,
         verdict.abstract_similarity, verdict.author_agreement, verdict.year_gap, merged,
         dumps(undo) if undo else None, now()),
    )
    return dict(conn.execute("SELECT * FROM record_links WHERE id = ?", (row_id,)).fetchone())


def _parent(a: str, b: str, parent: str | None) -> str | None:
    return None if parent is None else (a if parent == "a" else b)


def _published_dois(store: Store, work_id: str) -> set[str]:
    """The DOIs of the published records of a work; two different ones may never end up in one work."""
    return {source["doi"] for source in _work_sources(store, work_id) if record_kind(source) == "published"}


def _work_sources(store: Store, work_id: str) -> list[dict[str, Any]]:
    return [store.source(r[0]) for r in store.conn.execute(
        "SELECT id FROM source_versions WHERE work_id = ? ORDER BY id", (work_id,))]


def _keep_and_drop(store: Store, work_a: str, work_b: str) -> tuple[str, str]:
    """The work that survives a join: the one holding the published record, else the older one (D48, D59).

    Keeping the published record's work keeps the short source key that the record was cited under; with two
    preprints neither is preferred, so the older work is kept and the identifier breaks a tie of one instant.
    """
    published = [work for work in (work_a, work_b) if _published_dois(store, work)]
    if len(published) == 1:
        return published[0], (work_b if published[0] == work_a else work_a)
    rows = {r["id"]: r["created_at"] for r in store.conn.execute(
        "SELECT id, created_at FROM works WHERE id IN (?, ?)", (work_a, work_b))}
    keep, drop = sorted((work_a, work_b), key=lambda work: (rows[work], work))
    return keep, drop


def links_for(store: Store, source_version_id: str, include_closed: bool = False) -> list[dict[str, Any]]:
    """Every link of one record, from either side of the pair."""
    closed = "" if include_closed else " AND closed_at IS NULL"
    return [dict(row) for row in store.conn.execute(
        "SELECT * FROM record_links WHERE (source_version_id = ? OR other_source_version_id = ?)"
        f"{closed} ORDER BY created_at, id", (source_version_id, source_version_id))]


def research_links(store: Store, research_id: str) -> list[dict[str, Any]]:
    """The open links between two candidates of this research; a link itself belongs to the library, not to it."""
    return [dict(row) for row in store.conn.execute(
        "SELECT l.* FROM record_links l"
        " JOIN candidates a ON a.research_id = ? AND a.source_version_id = l.source_version_id"
        " JOIN candidates b ON b.research_id = ? AND b.source_version_id = l.other_source_version_id"
        " WHERE l.closed_at IS NULL ORDER BY l.created_at, l.id", (research_id, research_id))]


# ---- undoing a merge ---------------------------------------------------------------------


def undo_link(store: Store, link_id: str, note: str | None = None) -> dict[str, Any]:
    """Close a link and, when it joined two works, put the records it moved back where they were.

    Only what this link moved is separated: records that joined the work through another link afterwards stay. The
    selection a join copied to the new head is not taken back — every record keeps its own selection row — and no
    citation is disturbed, because an answer cites a record, not a work.
    """
    from deixis.workflow.store import NotFound  # store imports this module

    row = store.conn.execute("SELECT * FROM record_links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        raise NotFound(link_id)
    if row["closed_at"] is not None:
        raise ValueError(f"{link_id} was already closed as {row['closed_reason']}")
    with transaction(store.conn):
        store.conn.execute("UPDATE record_links SET closed_at = ?, closed_reason = 'undone', closed_note = ?"
                           " WHERE id = ?", (now(), note, link_id))
        if row["merged"]:
            _split_work(store, json.loads(row["undo_json"]))
    return dict(store.conn.execute("SELECT * FROM record_links WHERE id = ?", (link_id,)).fetchone())


def _split_work(store: Store, undo: dict[str, Any]) -> None:
    """Re-open the work a join dropped and move back the versions that are still in the work they were moved into."""
    conn, dropped, keep = store.conn, undo["dropped_work"], undo["keep_work_id"]
    moved = [svid for svid in undo["moved"]
             if (row := conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (svid,)).fetchone())
             and row[0] == keep]
    if not moved:  # every record this link moved has been deleted or moved on; there is no work to re-open
        return
    # D59: a key that was given is not changed, and a key another work has taken is not demanded back.
    free = dropped["source_key"] and not conn.execute(
        "SELECT 1 FROM works WHERE source_key = ? COLLATE NOCASE", (dropped["source_key"],)).fetchone()
    conn.execute("INSERT INTO works (id, created_at, source_key, source_key_basis) VALUES (?, ?, ?, ?)",
                 (dropped["id"], dropped["created_at"], dropped["source_key"] if free else None,
                  dropped["source_key_basis"] if free else None))
    conn.execute(f"UPDATE source_versions SET work_id = ? WHERE id IN ({', '.join('?' * len(moved))})",
                 (dropped["id"], *moved))
    if not free:
        store._assign_source_key(dropped["id"])
    for work_id in (keep, dropped["id"]):
        for (research_id,) in conn.execute(
            "SELECT DISTINCT m.research_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE v.work_id = ?", (work_id,)
        ).fetchall():
            store._settle_work_head(research_id, work_id)


# ---- linking the records one search found --------------------------------------------------


def link_records(store: Store, research_id: str, source_version_ids: list[str]) -> None:
    """Link the records this search found to every candidate of the research; the caller holds the transaction.

    The new records are compared to all candidates, not all candidates to each other, and only pairs whose titles are
    already close enough to examine (or which name each other by DOI) reach the rule. Abstracts are read for those
    pairs alone, so a search does not load the text of every candidate.
    """
    records = {r["id"]: _record(r) for r in store.conn.execute(
        "SELECT v.* FROM candidates c JOIN source_versions v ON v.id = c.source_version_id WHERE c.research_id = ?",
        (research_id,))}
    found = [svid for svid in dict.fromkeys(source_version_ids) if svid in records]
    if not found:
        return
    grams = {svid: trigrams(comparable_title(record)) for svid, record in records.items()}
    pairs: dict[tuple[str, str], tuple[str, float]] = {}
    for svid, other in _title_neighbours(found, grams):
        pairs[(svid, other)] = ("text", _jaccard(grams[svid], grams[other]))
    for svid, other in _published_doi_pairs(store, found, records):
        pairs[(svid, other)] = ("arxiv_doi", pairs.get((svid, other), ("", 0.0))[1])
    if not pairs:
        return
    _read_abstracts(store, records, {svid for pair in pairs for svid in pair})
    # A fixed order, so the same stored records give the same links: the DOI the author supplied first, then the
    # closest titles, then the identifier pair.
    for (a, b), (source, _) in sorted(pairs.items(), key=lambda item: (item[1][0] != "arxiv_doi", -item[1][1], item[0])):
        verdict = classify_pair(records[a], records[b], names_published_doi=source == "arxiv_doi")
        if verdict is not None:
            save_link(store, a, b, verdict, source)


def _record(row: Any) -> dict[str, Any]:
    record = {field: row[field] for field in RECORD_FIELDS if field != "authors"}
    record["authors"] = json.loads(row["authors_json"])
    record["abstract"] = None
    return record


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _title_neighbours(found: list[str], grams: dict[str, frozenset[str]]) -> set[tuple[str, str]]:
    """Ordered pairs of a new record and a candidate whose titles share enough trigrams to be worth examining.

    An inverted index over the trigrams keeps this to the records that actually overlap, so a research with a thousand
    candidates does not compare every title to every other one.
    """
    index: dict[str, list[str]] = {}
    for svid, gram_set in grams.items():
        for gram in gram_set:
            index.setdefault(gram, []).append(svid)
    pairs = set()
    for svid in found:
        shared: dict[str, int] = {}
        for gram in grams[svid]:
            for other in index[gram]:
                if other != svid:
                    shared[other] = shared.get(other, 0) + 1
        for other, count in shared.items():
            if count / (len(grams[svid]) + len(grams[other]) - count) >= TITLE_RELATED:
                pairs.add((min(svid, other), max(svid, other)))
    return pairs


def _published_doi_pairs(store: Store, found: list[str], records: dict[str, Any]) -> set[tuple[str, str]]:
    """Pairs where one record names the other's registered DOI, as `_flag_suspected_duplicates` finds them (D48)."""
    pairs = set()
    for svid in found:
        doi = records[svid]["doi"]
        linked = store.conn.execute(
            "SELECT source_version_id FROM identifier_mappings WHERE scheme = 'published_doi' AND value = ?", (doi,)
        ).fetchall() if doi else []
        linked += store.conn.execute(
            "SELECT d.source_version_id FROM identifier_mappings p JOIN identifier_mappings d"
            " ON d.scheme = 'doi' AND d.value = p.value WHERE p.scheme = 'published_doi' AND p.source_version_id = ?",
            (svid,)).fetchall()
        pairs |= {(min(svid, r[0]), max(svid, r[0])) for r in linked if r[0] in records and r[0] != svid}
    return pairs


def _read_abstracts(store: Store, records: dict[str, Any], wanted: set[str]) -> None:
    if not wanted:
        return
    for row in store.conn.execute(
        f"SELECT source_version_id, text FROM passages WHERE kind = 'abstract'"
        f" AND source_version_id IN ({', '.join('?' * len(wanted))}) ORDER BY id", tuple(sorted(wanted))
    ):
        records[row[0]]["abstract"] = records[row[0]]["abstract"] or row[1]

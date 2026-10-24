"""The citation map of one research: its works, the reference links between them and the outside works they cite.

`build` is read only; no provider request and no model call. A link means "A's stored OpenAlex reference list holds B". A work
whose versions never had their list read has no outgoing link: an unread list is not an empty one (lineage/edges.py).
`add_outside_work` puts one outside work the map lists into the research, from stored records only.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deixis.storage.db import now, transaction
from deixis.workflow.lineage.edges import normalize_openalex_id

OUTSIDE_LIMIT = 40
# Excluded sources keep their links, but their references do not make an outside work "often cited": an off-topic
# paper's reference list would pull off-topic works into the list.
COUNTING_STATES = ("included", "pending")


def _short_authors(authors: list[str]) -> str:
    if not authors:
        return ""
    family = str(authors[0]).split()[-1] if str(authors[0]).split() else str(authors[0])
    return family if len(authors) == 1 else f"{family} et al."


def build(store: Any, research_id: str) -> dict[str, Any]:
    conn = store.conn
    heads = store.work_heads(research_id)
    versions: dict[str, list[str]] = {}
    read: dict[str, bool] = {}
    for row in conn.execute(
        "SELECT v.id, v.work_id, v.references_read FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (research_id,)
    ):
        if row["work_id"] in heads:
            versions.setdefault(row["work_id"], []).append(row["id"])
            read[row["id"]] = bool(row["references_read"])
    version_work = {svid: wid for wid, svids in versions.items() for svid in svids}

    own: dict[str, set[str]] = {wid: set() for wid in heads}
    refs: dict[str, set[str]] = {wid: set() for wid in heads}
    member = ("JOIN corpus_memberships m ON m.source_version_id = r.source_version_id"
              " AND m.research_id = ? AND m.removed_at IS NULL")
    for row in conn.execute(f"SELECT r.source_version_id AS svid, r.value FROM identifier_mappings r {member}"
                            " WHERE r.scheme = 'openalex'", (research_id,)):
        if row["svid"] in version_work:
            own[version_work[row["svid"]]].add(normalize_openalex_id(row["value"]))
    # A version the citation map run found in OpenAlex (0015); kept out of `identifier_mappings`, so dedupe never reads it.
    for row in conn.execute(f"SELECT r.source_version_id AS svid, r.openalex_id AS value FROM citation_map_resolutions r {member}"
                            " WHERE r.status = 'resolved'", (research_id,)):
        if row["svid"] in version_work:
            own[version_work[row["svid"]]].add(normalize_openalex_id(row["value"]))
    # A work's list is the union of its read versions' lists (D79): a preprint and its article cite the same works.
    for row in conn.execute(f"SELECT r.source_version_id AS svid, r.referenced_id AS value FROM record_references r {member}",
                            (research_id,)):
        if read.get(row["svid"]):
            refs[version_work[row["svid"]]].add(normalize_openalex_id(row["value"]))

    by_openalex = {oid: wid for wid, ids in own.items() for oid in ids}
    nodes, edges = [], []
    for wid, head in heads.items():
        row = conn.execute(
            "SELECT v.title, v.authors_json, v.year, v.venue, v.doi, v.cited_by_count, sel.state FROM source_versions v"
            " JOIN selections sel ON sel.source_version_id = v.id AND sel.research_id = ? WHERE v.id = ?",
            (research_id, head)).fetchone()
        if row is None:
            continue
        references_read = any(read[svid] for svid in versions.get(wid, []))
        authors = json.loads(row["authors_json"] or "[]")
        nodes.append({
            "work_id": wid, "source_version_id": head, "openalex_ids": sorted(own[wid]), "title": row["title"],
            "authors": authors, "authors_short": _short_authors(authors), "year": row["year"], "venue": row["venue"],
            "doi": row["doi"], "cited_by_count": row["cited_by_count"], "state": row["state"],
            "references_read": references_read,
        })
    states = {node["work_id"]: node["state"] for node in nodes}

    outside_in: dict[str, set[str]] = {}
    for wid in states:
        for oid in sorted(refs[wid]):
            target = by_openalex.get(oid)
            if target is not None:
                if target != wid and target in states:
                    edges.append({"from": wid, "to": target})
            elif states[wid] in COUNTING_STATES:
                outside_in.setdefault(oid, set()).add(wid)
    edges = [{"from": a, "to": b} for a, b in sorted({(e["from"], e["to"]) for e in edges})]

    counting = sum(1 for state in states.values() if state in COUNTING_STATES)
    threshold = 1 if counting <= 1 else 2
    ranked = sorted((oid for oid, citers in outside_in.items() if len(citers) >= threshold),
                    key=lambda oid: (-len(outside_in[oid]), oid))
    outside = []
    for oid in ranked[:OUTSIDE_LIMIT]:
        known = _known_work(conn, research_id, oid)
        outside.append({"openalex_id": oid, "cited_by": sorted(outside_in[oid]), "in_count": len(outside_in[oid])} | known)
    return {
        "nodes": nodes, "edges": edges, "outside": outside,
        "counts": {
            "works": len(nodes), "edges": len(edges),
            "unread_references": sum(1 for node in nodes if not node["references_read"]),
            "no_openalex_id": sum(1 for node in nodes if not node["openalex_ids"]),
            "outside_total": len(ranked), "outside_threshold": threshold,
            "outside_without_metadata": sum(1 for work in outside if work["title"] is None),
        },
    }


def _known_work(conn: Any, research_id: str, openalex_id: str) -> dict[str, Any]:
    """What the library already stores for an outside work, and whether this research once held it and removed it."""
    row = conn.execute(
        "SELECT v.id, v.title, v.authors_json, v.year, v.venue, v.doi, v.cited_by_count,"
        " EXISTS (SELECT 1 FROM corpus_memberships m JOIN source_versions o ON o.id = m.source_version_id"
        "  WHERE m.research_id = ? AND o.work_id = v.work_id AND m.removed_at IS NOT NULL) AS removed"
        " FROM identifier_mappings i JOIN source_versions v ON v.id = i.source_version_id"
        " WHERE i.scheme = 'openalex' AND i.value IN (?, ?) ORDER BY v.created_at, v.id LIMIT 1",
        (research_id, openalex_id, f"https://openalex.org/{openalex_id}")).fetchone()
    if row is None:
        return {"source_version_id": None, "title": None, "authors": [], "authors_short": "", "year": None,
                "venue": None, "doi": None, "cited_by_count": None, "removed_from_research": False}
    authors = json.loads(row["authors_json"] or "[]")
    return {"source_version_id": row["id"], "title": row["title"], "authors": authors,
            "authors_short": _short_authors(authors), "year": row["year"], "venue": row["venue"], "doi": row["doi"],
            "cited_by_count": row["cited_by_count"], "removed_from_research": bool(row["removed"])}


OPENALEX_WORK_ID = re.compile(r"W\d+")


class OutsideWorkRefused(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def add_outside_work(store: Any, research_id: str, openalex_id: str) -> dict[str, Any]:
    """Add an outside work of the map to the research as a source the person added and nobody screened yet.

    No request is sent: the work must already be stored, as the map run's metadata step stores outside works. A work
    the research once held and the person removed is restored instead (D50), so its earlier selection and reason come
    back as they were; `add_to_corpus` would leave a removed membership removed and keep the old selection anyway.
    """
    oid = normalize_openalex_id(openalex_id)
    if not OPENALEX_WORK_ID.fullmatch(oid):
        raise OutsideWorkRefused(422, "invalid_openalex_id", "Not an OpenAlex work id")
    store.research(research_id)
    conn, ids = store.conn, (oid, f"https://openalex.org/{oid}")
    # The stored record of the work, chosen as `_known_work` chooses it, so the map and this route name the same one.
    record = conn.execute(
        "SELECT v.id, v.work_id FROM identifier_mappings i JOIN source_versions v ON v.id = i.source_version_id"
        " WHERE i.scheme = 'openalex' AND i.value IN (?, ?) ORDER BY v.created_at, v.id LIMIT 1", ids).fetchone()
    # The map also knows a version as this work through a citation map resolution (an upload found in OpenAlex).
    works = {row[0] for row in conn.execute(
        "SELECT v.work_id FROM identifier_mappings i JOIN source_versions v ON v.id = i.source_version_id"
        " WHERE i.scheme = 'openalex' AND i.value IN (?, ?) UNION SELECT v.work_id FROM citation_map_resolutions r"
        " JOIN source_versions v ON v.id = r.source_version_id WHERE r.status = 'resolved' AND r.openalex_id IN (?, ?)",
        (*ids, *ids))}
    if len(works) > 1:
        # Two local works carry the id (e.g. two uploads the map run resolved to it): which one is meant is unknown,
        # so nothing is restored or added.
        raise OutsideWorkRefused(409, "ambiguous_outside_work", "More than one stored work has this OpenAlex id",
                                 work_ids=sorted(works))
    members = [dict(row) for row in conn.execute(
        "SELECT m.source_version_id, m.removed_at, v.work_id FROM corpus_memberships m"
        " JOIN source_versions v ON v.id = m.source_version_id WHERE m.research_id = ? AND v.work_id = ?"
        " ORDER BY m.created_at, m.source_version_id", (research_id, *works))] if works else []
    if active := next((m for m in members if m["removed_at"] is None), None):
        head = store.work_heads(research_id).get(active["work_id"], active["source_version_id"])
        state = conn.execute("SELECT state FROM selections WHERE research_id = ? AND source_version_id = ?",
                             (research_id, head)).fetchone()
        raise OutsideWorkRefused(409, "already_in_research", "This work is already a source of this research",
                                 source_version_id=head, work_id=active["work_id"], state=state["state"] if state else None)
    if members:
        removed = [m["source_version_id"] for m in members]
        restored = store.restore_sources(research_id, removed)
        work_id = members[0]["work_id"]
        head = store.work_heads(research_id).get(work_id, restored[0])
        return {"source_version_id": head, "work_id": work_id, "restored": True, "changed_source_version_ids": restored}
    if record is None:
        raise OutsideWorkRefused(409, "outside_work_not_described",
                                 "This work has no stored record yet; read the reference lists first")
    with transaction(conn):
        # "library": the person brought a stored record in, which no search found and no screening judged.
        store.add_to_corpus(research_id, record["id"], "library", selection_state="pending", selection_origin="user")
        store._corpus_changed(research_id, "source_added", [record["id"]], now())
    return {"source_version_id": record["id"], "work_id": record["work_id"], "restored": False,
            "changed_source_version_ids": [record["id"]]}

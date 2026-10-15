"""The citation map of one research: its works, the reference links between them and the outside works they cite.

Read only; no provider request and no model call. A link means "A's stored OpenAlex reference list holds B". A work
whose versions never had their list read has no outgoing link: an unread list is not an empty one (lineage/edges.py).
"""

from __future__ import annotations

import json
from typing import Any

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

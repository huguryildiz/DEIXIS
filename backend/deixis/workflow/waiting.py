"""The works an `sw` research waits on a PDF for, and a file the person drops for one of them (slice 18a).

The list is not stored. Each read derives it from the current full-text decisions and the stored retrieval plans
(`fulltext.waiting`), so a revised question or a new file changes it without anything being rewritten. Reading it
opens no step and writes nothing.

A dropped file is matched to a work (`identity.propose`), never attached by the match: the person picks the version
and confirms. The match hands back what the confirmation must still find true — the file's digest, the question
revision, the work's version list — and the confirmation is refused, with its reason, when any of it moved or when the
chosen version already has a PDF in use. A confirmed file is added the way a person's upload always was
(`origin = user_upload`); slice 18b writes its code and reading request (`person_reading`).

Nothing here is about a topic or a publisher: the list comes from the reason table and the stored plan order.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.documents import identity
from deixis.domain import proxy
from deixis.domain.canonical import sha256_hex
from deixis.domain.rules import RevisionConflict
from deixis.workflow import fulltext
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store


class WaitingUnavailable(Exception):
    """The research is not on the `sw` workflow; the API answers 422."""


class AttachRefused(RevisionConflict):
    """A confirmation the state no longer allows (409), with why: `file_changed`, `scope_revised`,
    `not_a_candidate`, `not_a_member`, `versions_changed` or `pdf_in_use`."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def require_sw(store: Store, research_id: str) -> None:
    if store.scope(research_id).get("search_workflow") != "sw":
        raise WaitingUnavailable("The PDF waiting list belongs to the search workflow")


def _plans(store: Store, research_id: str, revision: int) -> list[dict[str, Any]]:
    """Every stored retrieval plan of this question revision, newest first, with when it was written."""
    return [json.loads(row["output_json"]) | {"finished_at": row["finished_at"]} for row in store.conn.execute(
        "SELECT s.output_json, s.finished_at FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND r.scope_revision = ? AND s.operation_key = 'fulltext_plan' AND s.status = 'succeeded'"
        " AND s.output_json IS NOT NULL ORDER BY s.finished_at DESC, s.id DESC", (research_id, revision))]


def _works(store: Store, research_id: str) -> list[dict[str, Any]]:
    """Every work of the research with what `fulltext.waiting` reads: each version, its PDF text, its decision.

    A few whole-research statements, as `flow._fulltext_works` reads them, without the abstracts that reader carries:
    the research view asks for the count on every read.
    """
    decisions = DecisionStore(store)
    stale_key = decisions.staleness_key(research_id)
    heads = store.work_heads(research_id)
    by_work: dict[str, list[str]] = {}
    for row in store.conn.execute(
            "SELECT v.id, v.work_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL", (research_id,)):
        by_work.setdefault(row["work_id"], []).append(row["id"])
    with_text = {row[0] for row in store.conn.execute(
        "SELECT DISTINCT p.source_version_id FROM passages p"
        " JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
        "  AND m.research_id = ? AND m.removed_at IS NULL"
        " JOIN source_assets a ON a.id = p.asset_id AND a.removed_at IS NULL"
        "  AND a.extraction_version IS p.extraction_version"
        " WHERE p.kind = 'pdf_page'", (research_id,))}
    held: dict[str, dict[str, Any]] = {}
    for row in store.conn.execute("SELECT rowid AS row_order, * FROM stage_decisions WHERE research_id = ?"
                                  " AND stage = 'fulltext'"
                                  " AND superseded_at IS NULL", (research_id,)):
        held[row["source_version_id"]] = {"reason_code": row["reason_code"], "decided_by": row["decided_by"],
                                          "stale": decisions.is_stale(dict(row), stale_key),
                                          "created_at": row["created_at"], "order": row["row_order"]}
    return [{"work_id": work_id, "head": head,
             "versions": [{"id": svid, "has_text": svid in with_text, "fulltext": held.get(svid)}
                          for svid in sorted(by_work.get(work_id, []))]}
            for work_id, head in sorted(heads.items())]


def _rows(store: Store, research_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    revision = store.research(research_id)["current_scope_revision"]
    plans = _plans(store, research_id, revision)
    return fulltext.waiting(_works(store, research_id), plans), plans, revision


def waiting_count(store: Store, research_id: str) -> int:
    """How many works wait for the person's PDF: the number beside the view's tab."""
    return len(_rows(store, research_id)[0])


def _versions(store: Store, research_id: str, head: str) -> list[str]:
    """The work's versions still in the research: the head first, then as `work_versions` orders the rest."""
    return [head, *store.work_versions(research_id, head)]


def _digest(work_id: str, versions: list[str]) -> str:
    """What a confirmation checks the version list against: which versions the work holds in the research."""
    return sha256_hex({"work_id": work_id, "versions": sorted(versions)})


def work_view(store: Store, research_id: str, work_id: str, head: str, proposed: str | None = None) -> dict[str, Any]:
    """One work as the confirmation shows it: every version with its label, year and type, and the list's digest."""
    ids = _versions(store, research_id, head)
    decisions = DecisionStore(store)
    versions = []
    for svid in ids:
        source = store.source(svid)
        current = decisions.current(research_id, svid, "fulltext")
        versions.append({"source_version_id": svid, "title": source["title"], "version_label": source["version_label"],
                         "year": source["year"], "publication_type": source["publication_type"], "doi": source["doi"],
                         "has_pdf": store.has_asset(svid), "proposed": svid == proposed,
                         # The person's own full-text decision on this version, which the panel names (slice 18b).
                         "person_decision": current["reason_code"] if current and current["decided_by"] == "human"
                         else None})
    return {"work_id": work_id, "head": head, "title": store.source(head)["title"], "versions": versions,
            "versions_digest": _digest(work_id, ids)}


def waiting_view(store: Store, research_id: str) -> dict[str, Any]:
    """The list in reading order: each work's record, why it waits, its links (through the proxy when one is set),
    the version "Find PDF" asks for, and its versions for a confirmation."""
    require_sw(store, research_id)
    found, plans, revision = _rows(store, research_id)
    address = store.setting(proxy.SETTING)
    rows = []
    for row in found:
        view = work_view(store, research_id, row["work_id"], row["head"])
        sources = [store.source(v["source_version_id"]) for v in view["versions"]]
        head = sources[0]
        doi = next((s["doi"] for s in sources if s["doi"]), None)
        # A landing page that is only the DOI's resolver (OpenAlex often stores it so) is not offered twice.
        landing = next((s["landing_url"] for s in sources if proxy.openable(s["landing_url"])
                        and s["landing_url"].lower() != (proxy.doi_url(doi) or "").lower()), None)
        rows.append(row | {
            "title": head["title"], "year": head["year"], "venue": head["venue"], "authors": head["authors"],
            "doi": doi, "links": {"doi": proxy.link(proxy.doi_url(doi), address), "landing": proxy.link(landing, address)},
            # "Find PDF" is today's action on a record with a DOI (D4): the head's, else another version's.
            "find_pdf_source_version_id": next((s["id"] for s in sources if s["doi"]), None),
            "versions": view["versions"], "versions_digest": view["versions_digest"]})
    return {"rows": rows, "count": len(rows), "scope_revision": revision, "has_plan": bool(plans),
            "via_proxy": bool(address), "order": "fulltext_plan"}


def candidate_works(store: Store, research_id: str) -> dict[str, str]:
    """The works a dropped file may be proposed for, by `work_id` with their heads now (decision 4).

    The latest plan's works, the works on the list, and the works the person included after that plan was written
    (every work they included when there is no plan yet). "After" counts the plan's own millisecond: the clock cannot
    order two writes inside it, and a work the person included then is theirs to add a file to (Sol's check); the
    cost is at most a work they included just before, which only widens their own choice.
    """
    found, plans, _ = _rows(store, research_id)
    heads = store.work_heads(research_id)
    wanted = {row["work_id"] for row in found}
    latest = plans[0] if plans else None
    if latest is not None:
        wanted |= set(store.work_ids(list(latest.get("works") or [])).values())
    included = [row[0] for row in store.conn.execute(
        # Only a version still in the research speaks for the work: a removed one's selection is history (D50).
        "SELECT s.source_version_id FROM selections s JOIN corpus_memberships m ON m.research_id = s.research_id"
        " AND m.source_version_id = s.source_version_id AND m.removed_at IS NULL"
        " WHERE s.research_id = ? AND s.origin = 'user' AND s.state = 'included' AND (? IS NULL OR s.updated_at >= ?)", (research_id, latest and latest["finished_at"],
                                                latest and latest["finished_at"]))]
    wanted |= set(store.work_ids(included).values())
    return {work_id: heads[work_id] for work_id in sorted(wanted) if work_id in heads}


def propose(store: Store, research_id: str, text: str) -> dict[str, Any]:
    """The work a file's first pages point at among the candidate works, with that work's versions to pick from.

    When nothing is proposed, every candidate work comes back with its versions, for the person to choose from: a
    file whose first page names neither a DOI nor a title can still belong to one of them (Sol's review)."""
    works = candidate_works(store, research_id)
    sources = [dict(store.source(svid), work_id=work_id)
               for work_id, head in works.items() for svid in _versions(store, research_id, head)]
    svid, basis = identity.propose(text, sources)
    if svid is None:
        return {"source_version_id": None, "basis": None, "work": None,
                "candidates": [work_view(store, research_id, work_id, head) for work_id, head in works.items()]}
    work_id = store.source(svid)["work_id"]
    return {"source_version_id": svid, "basis": basis,
            "work": work_view(store, research_id, work_id, works[work_id], proposed=svid)}


def check_attach(store: Store, research_id: str, *, work_id: str, source_version_id: str, scope_revision: int,
                 versions_digest: str, sha256: str, uploaded_sha256: str) -> None:
    """Refuse a confirmation whose file, question revision, work or version moved since the match (decision 5)."""
    require_sw(store, research_id)
    if uploaded_sha256 != sha256:
        raise AttachRefused("file_changed", "This is not the file that was matched; drop it again")
    if store.research(research_id)["current_scope_revision"] != scope_revision:
        raise AttachRefused("scope_revised", "The question was revised after the file was matched; drop it again")
    if not store.is_active_member(research_id, source_version_id) or \
            store.source(source_version_id)["work_id"] != work_id:
        raise AttachRefused("not_a_member", "This version is no longer a source of this research")
    head = candidate_works(store, research_id).get(work_id)
    if head is None:
        raise AttachRefused("not_a_candidate", "This work is no longer one a file can be added for here")
    versions = _versions(store, research_id, head)
    if _digest(work_id, versions) != versions_digest:
        raise AttachRefused("versions_changed", "The versions of this work changed; choose the version again")
    if store.has_asset(source_version_id):
        raise AttachRefused("pdf_in_use", "This version already has a PDF in use; choose another version")

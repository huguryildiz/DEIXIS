"""The works an `sw` research waits on a PDF for, and a file the person drops for one of them (slice 18a).

The list is not stored. Each read derives it from current full-text decisions and stored retrieval or small-batch
plans/closures, so a revised question or a new file changes it without anything being rewritten. Reading it
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
from deixis.domain.reason_codes import reason
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import now, transaction
from deixis.workflow.read import fulltext
from deixis.workflow.search import small_batch
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.run.store import NotFound, Store


class AttachRefused(RevisionConflict):
    """A confirmation the state no longer allows (409), with why: `file_changed`, `scope_revised`,
    `not_a_candidate`, `not_a_member`, `versions_changed` or `pdf_in_use`."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class SkipRefused(AttachRefused):
    """"Continue without PDF" for a work that is not on the waiting list (`not_waiting`) or already skipped."""


def _plans(store: Store, research_id: str, revision: int) -> list[dict[str, Any]]:
    """Retrieval orders, newest first; batch records form one reading order per frozen run."""
    plans = [json.loads(row["output_json"]) | {"finished_at": row["finished_at"], "order": "fulltext_plan",
                                               "step_id": row["id"]} for row in store.conn.execute(
        "SELECT s.id, s.output_json, s.finished_at FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND r.scope_revision = ? AND s.operation_key = 'fulltext_plan' AND s.status = 'succeeded'"
        " AND s.output_json IS NOT NULL ORDER BY s.finished_at DESC, s.id DESC", (research_id, revision))]
    batches: dict[str, dict[str, Any]] = {}
    for row in store.conn.execute(
            "SELECT s.id, s.run_id, s.output_json, s.finished_at, r.budget_json FROM run_steps s"
            " JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND r.scope_revision = ?"
            " AND r.kind = 'discovery' AND s.kind IN ('code:small_batch_plan', 'code:small_batch_close')"
            " AND s.status = 'succeeded' AND s.output_json IS NOT NULL"
            " ORDER BY s.finished_at, s.id", (research_id, revision)):
        if not small_batch.enabled(json.loads(row["budget_json"])):
            continue
        batch = batches.setdefault(row["run_id"], {"items": {}, "order": "small_batch_plan"})
        for item in json.loads(row["output_json"]).get("items", []):
            # Closures lack version lists; retain the plan's version identities for changed heads.
            batch["items"][item["position"]] = batch["items"].get(item["position"], {}) | item
        batch.update(finished_at=row["finished_at"], step_id=row["id"])
    for batch in batches.values():
        batch["works"] = list(dict.fromkeys(svid for _, item in sorted(batch.pop("items").items())
                                            for svid in [item["head"], *item.get("versions", [])]))
        plans.append(batch)
    return sorted(plans, key=lambda plan: (plan["finished_at"], plan["step_id"]), reverse=True)


def _waiting_rows(works: list[dict[str, Any]], plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if plans and plans[0]["order"] == "small_batch_plan":
        reached = {svid for plan in plans for svid in plan.get("works", [])}
        works = [work for work in works if any(v["id"] in reached for v in work["versions"])
                 and any(not v["has_asset"] for v in work["versions"])]
    return fulltext.waiting(works, plans)


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
    with_asset = {row[0] for row in store.conn.execute(
        "SELECT DISTINCT a.source_version_id FROM source_assets a JOIN corpus_memberships m"
        " ON m.source_version_id = a.source_version_id WHERE m.research_id = ?"
        " AND m.removed_at IS NULL AND a.removed_at IS NULL", (research_id,))}
    held: dict[str, dict[str, Any]] = {}
    for row in store.conn.execute("SELECT rowid AS row_order, * FROM stage_decisions WHERE research_id = ?"
                                  " AND stage = 'fulltext'"
                                  " AND superseded_at IS NULL", (research_id,)):
        held[row["source_version_id"]] = {"reason_code": row["reason_code"], "decided_by": row["decided_by"],
                                          "stale": decisions.is_stale(dict(row), stale_key),
                                          "created_at": row["created_at"], "order": row["row_order"]}
    return [{"work_id": work_id, "head": head,
             "versions": [{"id": svid, "has_text": svid in with_text, "has_asset": svid in with_asset,
                           "fulltext": held.get(svid)}
                          for svid in sorted(by_work.get(work_id, []))]}
            for work_id, head in sorted(heads.items())]


def skipped(store: Store, research_id: str) -> dict[str, str]:
    """The works the person chose to go on without a PDF for (D46), by `work_id`, with when they chose it.

    A PDF added to any version of the work at or after the choice ends it, by whatever route it came (the waiting
    panel, a source's upload, a background fetch): normal reading applies again. Read here rather than deleted by each
    route, so no route can miss it; the row stays, inert, and a later undo removes it."""
    return {row[0]: row[1] for row in store.conn.execute(
        "SELECT k.work_id, k.skipped_at FROM pdf_skips k WHERE k.research_id = ? AND NOT EXISTS ("
        " SELECT 1 FROM source_assets a JOIN source_versions v ON v.id = a.source_version_id"
        " WHERE v.work_id = k.work_id AND a.retrieved_at >= k.skipped_at)", (research_id,))}


def _split(rows: list[dict[str, Any]], skips: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The rows still waiting and the rows the person skipped (D46), each numbered again from 1 in reading order."""
    waiting_rows = [row for row in rows if row["work_id"] not in skips]
    skipped_rows = [row for row in rows if row["work_id"] in skips]
    return ([row | {"place": n} for n, row in enumerate(waiting_rows, start=1)],
            [row | {"place": n, "skipped_at": skips[row["work_id"]]} for n, row in enumerate(skipped_rows, start=1)])


def _listing(store: Store, research_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Every work that would wait for a PDF, skipped or not, with the plans and the question revision."""
    revision = store.research(research_id)["current_scope_revision"]
    plans = _plans(store, research_id, revision)
    return _waiting_rows(_works(store, research_id), plans), plans, revision


def _rows(store: Store, research_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """The works that wait for the person's PDF: a work the person went on without (D46) is not among them."""
    rows, plans, revision = _listing(store, research_id)
    return _split(rows, skipped(store, research_id))[0], plans, revision


def for_context(ctx: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """The works as `fulltext.waiting` reads them, by id, and the ids on the waiting list, once per queue context:
    the flow's buckets and the tab's count read the same derivation (slice 20). A skipped work (D46) is not listed."""
    if ctx._waiting is None:
        works = _works(ctx.store, ctx.rid)
        rows = _waiting_rows(works, _plans(ctx.store, ctx.rid, ctx.revision))
        skips = skipped(ctx.store, ctx.rid)
        ctx._waiting = ({work["work_id"]: work for work in works},
                        {row["work_id"] for row in rows if row["work_id"] not in skips})
        ctx._waiting_skipped = {row["work_id"] for row in rows if row["work_id"] in skips}
    return ctx._waiting


def skipped_in_context(ctx: Any) -> set[str]:
    """The works that would wait for a PDF but that the person went on without (D46): the flow's own bucket."""
    for_context(ctx)
    return ctx._waiting_skipped


def skip(store: Store, research_id: str, work_id: str) -> None:
    """"Continue without PDF" (D46): the work leaves the waiting list and its counts and is read from its abstract.

    Only a work on the waiting list now can be skipped. Nothing else changes: the answer input already gives such a
    work its abstract (`fast_answer.cutoff_snapshot` routes a work with no read PDF to its abstract), so no run is
    queued and no selection is written."""
    with transaction(store.conn):
        rows, _, _ = _listing(store, research_id)
        skips = skipped(store, research_id)
        if work_id in skips:
            raise SkipRefused("already_skipped", "This work is already read from its abstract only")
        if work_id not in {row["work_id"] for row in rows}:
            raise SkipRefused("not_waiting", "This work no longer waits for a PDF")
        # An earlier choice a PDF ended (see `skipped`) is replaced by this one.
        store.conn.execute("INSERT OR REPLACE INTO pdf_skips (research_id, work_id, skipped_at) VALUES (?, ?, ?)",
                           (research_id, work_id, now()))
        store._event(research_id, "waiting_pdf_skipped", {"work_id": work_id})


def unskip(store: Store, research_id: str, work_id: str) -> None:
    """Undo "Continue without PDF" (D46): the work waits for the person's PDF again, if it still would."""
    with transaction(store.conn):
        if not store.conn.execute("DELETE FROM pdf_skips WHERE research_id = ? AND work_id = ?",
                                  (research_id, work_id)).rowcount:
            raise NotFound(work_id)
        store._event(research_id, "waiting_pdf_skip_undone", {"work_id": work_id})


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


def _frozen_list(store: Store, research_id: str, revision: int) -> dict[str, Any] | None:
    """The ranked list the latest completed discovery run of this revision froze, or None (an older or attached run)."""
    row = store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
        " AND status = 'completed' ORDER BY created_at DESC, id DESC LIMIT 1", (research_id, revision)).fetchone()
    step = store.existing_step(row["id"], small_batch.LIST_KEY) if row else None
    return step["output"] if step and step["status"] == "succeeded" else None


def _relevance(store: Store, research_id: str, listing: dict[str, Any] | None,
               versions: list[str]) -> dict[str, Any]:
    """Why the work is where it is: where the search found it, its place in the frozen ranking, and what the
    abstract stage said. Read from stored rows only; a work the list does not hold has no origin or rank."""
    rank = origin = None
    if listing:
        item = next((i for i in listing["items"] if set(i["versions"]) & set(versions)), None)
        if item:
            rank = item["position"]
            manifest = listing["manifest"]
            if item["user_priority"]:
                origin = "user"
            elif set(item["versions"]) & set(manifest.get("chain_heads") or []) \
                    and not set(item["versions"]) & set(manifest.get("keyword_heads") or []):
                origin = "chain"
            else:
                origin = "search"
    decisions = DecisionStore(store)
    held = [d for d in (decisions.current(research_id, svid, "abstract") for svid in versions) if d]
    outcomes = [reason(d["reason_code"]).outcome for d in held]
    abstract = (None if not outcomes else "candidate" if "candidate" in outcomes
                else "out_of_scope" if all(o == "out_of_scope" for o in outcomes) else "unresolved")
    return {"origin": origin, "rank": rank, "ranked": len(listing["items"]) if listing else None,
            "abstract": abstract}


def waiting_view(store: Store, research_id: str) -> dict[str, Any]:
    """The list in reading order: each work's record, why it waits, its links (through the proxy when one is set),
    the version "Find PDF" asks for, and its versions for a confirmation."""
    every, plans, revision = _listing(store, research_id)
    found, passed_over = _split(every, skipped(store, research_id))
    address = store.setting(proxy.SETTING)
    listing = _frozen_list(store, research_id, revision)
    rows, skipped_rows = [], []
    for row in [*found, *passed_over]:
        view = work_view(store, research_id, row["work_id"], row["head"])
        sources = [store.source(v["source_version_id"]) for v in view["versions"]]
        head = sources[0]
        doi = next((s["doi"] for s in sources if s["doi"]), None)
        # A landing page that is only the DOI's resolver (OpenAlex often stores it so) is not offered twice.
        landing = next((s["landing_url"] for s in sources if proxy.openable(s["landing_url"])
                        and s["landing_url"].lower() != (proxy.doi_url(doi) or "").lower()), None)
        (skipped_rows if "skipped_at" in row else rows).append(row | {
            "title": head["title"], "year": head["year"], "venue": head["venue"], "authors": head["authors"],
            "doi": doi, "links": {"doi": proxy.link(proxy.doi_url(doi), address), "landing": proxy.link(landing, address)},
            # "Find PDF" is today's action on a record with a DOI (D4): the head's, else another version's.
            "find_pdf_source_version_id": next((s["id"] for s in sources if s["doi"]), None),
            "versions": view["versions"], "versions_digest": view["versions_digest"],
            "relevance": _relevance(store, research_id, listing, [v["source_version_id"] for v in view["versions"]])})
    for row in skipped_rows:
        # Whether the answer can read the work from its abstract: it passed the abstract stage and an abstract is
        # stored for one of its versions (`fast_answer.cutoff_snapshot` needs both). False says the answer leaves it out.
        row["answer_reads_abstract"] = row["relevance"]["abstract"] == "candidate" and bool(store.conn.execute(
            "SELECT 1 FROM passages WHERE kind = 'abstract' AND source_version_id IN (%s) LIMIT 1"
            % ",".join("?" * len(row["versions"])), [v["source_version_id"] for v in row["versions"]]).fetchone())
    return {"rows": rows, "count": len(rows), "scope_revision": revision, "has_plan": bool(plans),
            # The works the person went on without a PDF for (D46), in reading order; each can be undone or given a file.
            "skipped": skipped_rows,
            # How many works a dropped file may be attached to (`candidate_works`): with no plan yet these are the
            # works the person included, so the panel opens its drop zone on this, not on `has_plan` alone.
            "attach_candidates": len(candidate_works(store, research_id)),
            "via_proxy": bool(address), "order": plans[0]["order"] if plans else "fulltext_plan"}


def candidate_works(store: Store, research_id: str) -> dict[str, str]:
    """The works a dropped file may be proposed for, by `work_id` with their heads now (decision 4).

    The latest plan's works, the works on the list, and the works the person included after that plan was written
    (every work they included when there is no plan yet). "After" counts the plan's own millisecond: the clock cannot
    order two writes inside it, and a work the person included then is theirs to add a file to (Sol's check); the
    cost is at most a work they included just before, which only widens their own choice.
    """
    # A work the person went on without (D46) is still listed here: a file for it clears the skip.
    found, plans, _ = _listing(store, research_id)
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

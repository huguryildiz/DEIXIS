"""The citation map's reading run (`citation_map`): fill what the map of one research is missing, OpenAlex only, no
model call. A person starts it; nothing starts it by itself.

Three phases, each planned by a code step that is frozen before its first request, so a resumed or restarted run
reads the same plan and a request whose step succeeded is never sent again:

1. Works with no OpenAlex id. An upload D37 already identified keeps that record (`record_match_json`, no request);
   otherwise a version with a DOI is looked up by DOI, 50 DOIs a request on a 100-record page, so a DOI that names two
   OpenAlex works is seen and decides nothing (`ambiguous`). The answer carries the work's reference list
   (`CHAIN_SELECT`), so a resolved version's list is stored from the same request. A work without either stays
   unresolved: no title guess here. Results go to `citation_map_resolutions`, never to `identifier_mappings` (0015).
2. Unread reference lists: the research's versions with an OpenAlex id and `references_read = 0`, 100 ids a request
   through the id lookup. An answer without a valid `referenced_works` list leaves its version unread.
3. Outside works without stored metadata: the map's top outside works (at most 40, one request), stored as provider
   sources and added to no research.

Before every request the run checks its stop (`_checkpoint`) and OpenAlex's daily budget; a budget that ran out
pauses the run (`openalex_budget_exhausted`) and keeps everything stored so far.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from deixis.documents import acquisition
from deixis.domain.rules import RevisionConflict
from deixis.providers import facade, openalex
from deixis.providers.common import collect_transport, normalize_doi
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import now, transaction
from deixis.workflow import citation_map, lookups
from deixis.workflow.lineage.edges import normalize_openalex_id

DOI_BATCH = 50
ID_BATCH = openalex.MAX_IDS_PER_REQUEST
RATE_LIMIT_RETRIES = 1
PLAN_KIND = "code:citation_map_plan"
REQUEST_KIND = "provider:citation_map_lookup"
BUDGET_STOP = "openalex_budget_exhausted"
WORK_ID = re.compile(r"W\d+")


def _valid_list(record: Any) -> bool:
    """A list is read only when every entry is an OpenAlex work id; one malformed entry leaves the whole list unread,
    so a later run asks again. An empty list is a valid answer."""
    refs = record.references
    return refs is not None and all(isinstance(ref, str) and WORK_ID.fullmatch(ref) for ref in refs)


def _versions(store: Any, research_id: str) -> list[dict[str, Any]]:
    """The live member versions of the research's works, with what the map needs to know about each."""
    heads = store.work_heads(research_id)
    rows = store.conn.execute(
        "SELECT v.id, v.work_id, v.origin, v.doi, v.record_match_json, v.references_read, r.status AS resolution,"
        " r.openalex_id AS resolved_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " LEFT JOIN citation_map_resolutions r ON r.source_version_id = v.id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL ORDER BY v.created_at, v.id", (research_id,))
    return [dict(row) for row in rows if row["work_id"] in heads]


def _openalex_ids(store: Any, versions: list[dict[str, Any]]) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {v["id"]: set() for v in versions}
    for v in versions:
        if v["resolved_id"]:
            ids[v["id"]].add(v["resolved_id"])
    marks = ",".join("?" * len(ids))
    if ids:
        for row in store.conn.execute(f"SELECT source_version_id, value FROM identifier_mappings WHERE scheme = 'openalex'"
                                      f" AND source_version_id IN ({marks})", tuple(ids)):
            if oid := normalize_openalex_id(row["value"]):
                ids[row["source_version_id"]].add(oid)
    return ids


def _record_match(version: dict[str, Any]) -> str | None:
    match = json.loads(version["record_match_json"]) if version["record_match_json"] else {}
    return normalize_openalex_id(match.get("work_id")) if match.get("provider") == "openalex" else None


def _usable_doi(value: str | None) -> str | None:
    doi = normalize_doi(value)
    return doi if doi and not any(c in doi for c in "|,") else None


def resolution_targets(store: Any, research_id: str) -> dict[str, Any]:
    """The versions to resolve, from the works none of whose versions has an OpenAlex id: by D37 record match, or by
    DOI. A version already tried by an earlier run (a resolution row of any status) is not tried again."""
    versions = _versions(store, research_id)
    ids = _openalex_ids(store, versions)
    by_work: dict[str, list[dict[str, Any]]] = {}
    for v in versions:
        by_work.setdefault(v["work_id"], []).append(v)
    record_match, by_doi, works, without_doi = [], [], 0, 0
    for members in by_work.values():
        if any(ids[v["id"]] for v in members):
            continue
        open_members = [v for v in members if v["resolution"] is None]
        found = False
        for v in open_members:
            if oid := _record_match(v):
                record_match.append({"source_version_id": v["id"], "openalex_id": oid})
                found = True
            elif doi := _usable_doi(v["doi"]):
                by_doi.append({"source_version_id": v["id"], "doi": doi})
                found = True
        works += found
        # A work tried before and not found is not "without DOI"; only one with nothing to look up by is.
        without_doi += not found and not any(v["resolution"] for v in members)
    return {"record_match": record_match, "doi": by_doi, "works": works, "unresolvable_without_doi": without_doi}


def unread_targets(store: Any, research_id: str) -> list[tuple[str, str]]:
    """(version, OpenAlex id) for every live member version with an id whose reference list was never read."""
    versions = _versions(store, research_id)
    ids = _openalex_ids(store, versions)
    return sorted((v["id"], oid) for v in versions if not v["references_read"] for oid in ids[v["id"]])


def asked_without_answer(store: Any, research_id: str) -> set[str]:
    """Outside works an earlier run of this research asked OpenAlex to describe, in a request that succeeded with a
    complete answer (OpenAlex's own count present and every counted work returned), and that still have no stored
    record. OpenAlex returned nothing for them; asking again would spend a request every time for nothing (seen live on
    16 Oct: four of 38 ids came back empty twice). An answer without a count proves nothing and is asked again."""
    asked: set[str] = set()
    for row in store.conn.execute(
        "SELECT p.output_json, d.output_json AS answer FROM run_steps p JOIN runs r ON r.id = p.run_id"
        " JOIN run_steps d ON d.run_id = p.run_id AND d.operation_key = 'citation_map:describe' AND d.status = 'succeeded'"
        " WHERE r.research_id = ? AND r.kind = 'citation_map' AND p.operation_key = 'citation_map:describe_plan'"
        " AND p.status = 'succeeded'", (research_id,)
    ):
        answer = json.loads(row["answer"] or "{}")
        if answer.get("provider_total") is not None and answer["provider_total"] <= answer.get("returned", 0):
            asked.update(json.loads(row["output_json"] or "{}").get("ids") or [])
    return asked


def outside_targets(store: Any, research_id: str) -> list[str]:
    skip = asked_without_answer(store, research_id)
    return [work["openalex_id"] for work in citation_map.build(store, research_id)["outside"]
            if work["title"] is None and work["openalex_id"] not in skip]


def _batches(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _read_batches(targets: list[tuple[str, str]]) -> list[dict[str, Any]]:
    versions: dict[str, list[str]] = {}
    for svid, oid in targets:
        versions.setdefault(oid, []).append(svid)
    return [{"ids": batch, "versions": {oid: versions[oid] for oid in batch}} for batch in _batches(sorted(versions), ID_BATCH)]


def prepare(store: Any, research_id: str) -> dict[str, Any]:
    """What a run would do now, without a request. `sources_to_read` counts the versions whose list the id lookup
    reads (those an upload's record match names included); a DOI answer carries its own list, so its version is read
    by the DOI request. `requests` is the number of requests planned: DOI batches, id batches, and the one request
    for outside works' metadata whenever any work is resolved, any list read or any outside work lacks metadata
    (a list read in this run can add outside works). A DOI answer without a valid list adds its version to the id
    lookup, the one case where a run sends more than this."""
    targets = resolution_targets(store, research_id)
    matched = {(t["source_version_id"], t["openalex_id"]) for t in targets["record_match"]
               if not store.conn.execute("SELECT references_read FROM source_versions WHERE id = ?",
                                         (t["source_version_id"],)).fetchone()[0]}
    reads = sorted(set(unread_targets(store, research_id)) | matched)
    outside = outside_targets(store, research_id)
    doi_requests = len(_batches(targets["doi"], DOI_BATCH))
    read_requests = len(_read_batches(reads))
    describe = 1 if outside or doi_requests or read_requests else 0
    return {"works_to_resolve": targets["works"], "sources_to_read": len({svid for svid, _ in reads}),
            "outside_to_describe": len(outside), "requests": doi_requests + read_requests + describe,
            "unresolvable_without_doi": targets["unresolvable_without_doi"]}


def request_run(store: Any, research_id: str, *, titles_only: bool = False) -> dict[str, Any]:
    """Queue the run, or return the one already queued or running for this research. A titles-only run (the panel's
    own request when it opens) asks only for the outside works' metadata: one request, refused when anything else is
    missing, and it never resolves or reads lists, even if sources are added before it runs."""
    with transaction(store.conn):
        active = store.conn.execute(
            "SELECT id, status FROM runs WHERE research_id = ? AND kind = 'citation_map'"
            " AND status IN ('queued', 'running', 'pause_requested', 'paused') ORDER BY created_at DESC LIMIT 1",
            (research_id,)).fetchone()
        if active and active["status"] == "paused":
            raise RevisionConflict(f"Resume or cancel paused citation map run {active['id']} first")
        if active:
            return store.run(active["id"])
        plan = prepare(store, research_id)
        if not plan["requests"]:
            raise RevisionConflict("Nothing is missing from the citation map that OpenAlex can fill")
        if titles_only:
            if plan["works_to_resolve"] or plan["sources_to_read"] or not plan["outside_to_describe"]:
                raise RevisionConflict("More than the outside works' titles is missing from the citation map")
            plan = plan | {"requests": 1, "titles_only": True}
        return store.create_run(research_id, "citation_map", {
            "max_model_calls": 0, "max_provider_requests": plan["requests"] * (1 + RATE_LIMIT_RETRIES)}, None, plan)


# ---- the run -------------------------------------------------------------------------------------------------------
async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    store, run_id, rid = flow.store, run["id"], run["research_id"]
    if (run.get("target") or {}).get("titles_only"):
        describe = _frozen(store, run_id, "citation_map:describe_plan", lambda: {"ids": outside_targets(store, rid)})
        if describe["ids"]:
            await _request(flow, run, "citation_map:describe", _id_send(flow, describe["ids"]),
                           lambda outcome, step: _apply_outside(flow, step, outcome))
        return
    plan = _frozen(store, run_id, "citation_map:resolve_plan", lambda: _resolve_plan(store, run_id, rid))
    for i, batch in enumerate(plan["doi_batches"]):
        await _request(flow, run, f"citation_map:doi:{i}", _doi_send(flow, [t["doi"] for t in batch]),
                       lambda outcome, step, batch=batch: _apply_dois(store, run_id, batch, outcome))
    reads = _frozen(store, run_id, "citation_map:read_plan",
                    lambda: {"batches": _read_batches(unread_targets(store, rid))})
    for i, batch in enumerate(reads["batches"]):
        await _request(flow, run, f"citation_map:references:{i}", _id_send(flow, batch["ids"]),
                       lambda outcome, step, batch=batch: _apply_references(store, batch, outcome))
    describe = _frozen(store, run_id, "citation_map:describe_plan", lambda: {"ids": outside_targets(store, rid)})
    if describe["ids"]:
        await _request(flow, run, "citation_map:describe", _id_send(flow, describe["ids"]),
                       lambda outcome, step: _apply_outside(flow, step, outcome))


def _frozen(store: Any, run_id: str, key: str, build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """A code step's output, computed once: a succeeded step is read back, so a resumed run keeps its plan."""
    step = store.step(run_id, key, PLAN_KIND)
    if step["status"] == "succeeded":
        return step["output"]
    store.start_step(step["id"])
    with transaction(store.conn):
        output = build()
        store.finish_step(step["id"], "succeeded", output=output)
    return output


def _resolve_plan(store: Any, run_id: str, research_id: str) -> dict[str, Any]:
    """Plan phase 1; the record matches need no request and are written with the plan, in its transaction."""
    targets = resolution_targets(store, research_id)
    ts = now()
    store.conn.executemany(
        "INSERT INTO citation_map_resolutions (source_version_id, method, status, openalex_id, run_id, resolved_at)"
        " VALUES (?, 'record_match', 'resolved', ?, ?, ?) ON CONFLICT DO NOTHING",
        [(t["source_version_id"], t["openalex_id"], run_id, ts) for t in targets["record_match"]])
    return {"record_match": len(targets["record_match"]), "doi_batches": _batches(targets["doi"], DOI_BATCH),
            "unresolvable_without_doi": targets["unresolvable_without_doi"]}


def _doi_send(flow: Any, dois: list[str]) -> Callable[[], Awaitable[Any]]:
    async def send():
        with collect_transport() as transport:
            outcome = await openalex.works_by_dois(flow.deps.http, dois, api_key=CONNECTORS["openalex"].api_key(),
                                                   contact_email=flow.deps.settings.contact_email,
                                                   max_rate_limit_retries=RATE_LIMIT_RETRIES,
                                                   per_page=openalex.MAX_IDS_PER_REQUEST)
        return SimpleNamespace(outcome=outcome, transport=tuple(transport))
    return send


def _id_send(flow: Any, ids: list[str]) -> Callable[[], Awaitable[Any]]:
    async def send():
        return await facade.dispatch_lookup("openalex", "id_lookup", flow.deps.http, tuple(ids),
                                            CONNECTORS["openalex"].api_key(), flow.deps.settings.contact_email,
                                            RATE_LIMIT_RETRIES)
    return send


async def _request(flow: Any, run: dict[str, Any], key: str, send: Callable[[], Awaitable[Any]],
                   apply: Callable[[Any, dict[str, Any]], dict[str, Any]], kind: str = REQUEST_KIND) -> None:
    """One OpenAlex request as its own step: sent once, its answer applied in the transaction that ends the step."""
    store, run_id = flow.store, run["id"]
    step = store.step(run_id, key, kind)
    if step["status"] == "succeeded":
        return
    flow._checkpoint(run_id, run["scope_revision"])
    budget = flow._openalex_budget_of(run_id)
    if budget.exhausted:
        _budget_stop(flow, run, step, budget.reset_at, skipped=True)
    store.start_step(step["id"])
    reserved = 1 + RATE_LIMIT_RETRIES
    store.add_usage(run_id, "provider_requests", reserved)
    dispatched = await send()
    lookups.settle_dispatch(store, run_id, step, dispatched, reserved, "provider_requests", "provider_sends")
    outcome = dispatched.outcome
    if outcome.error_kind == "quota_exhausted":
        _budget_stop(flow, run, step, acquisition.budget_reset_at(outcome.rate_limit), skipped=False)
    ok = outcome.status in ("completed", "zero_results")
    returned = len((outcome.raw_payload or {}).get("results") or [])
    if ok and outcome.provider_total is not None and outcome.provider_total > returned:
        ok, outcome.status = False, "incomplete"  # a work cut off the page could change what a DOI names
    output = lookups.transport_output(store, step, {"status": outcome.status, "returned": len(outcome.records),
                                                     "provider_total": outcome.provider_total})
    with transaction(store.conn):
        if ok:
            store.finish_step(step["id"], "succeeded", output=output | apply(outcome, step))
        else:
            store.finish_step(step["id"], "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed",
                              output=output, error_code=outcome.status,
                              error={"error": outcome.error, "http_status": outcome.http_status},
                              delivery_class=outcome.delivery_class)


def _budget_stop(flow: Any, run: dict[str, Any], step: dict[str, Any], reset_at: str | None, *, skipped: bool) -> None:
    """Pause the run on OpenAlex's spent daily budget: the step, the budget's count and event, and the pause are one
    write; everything stored before stays."""
    from deixis.workflow.flow import RunStopped
    store = flow.store
    reset_at = reset_at or acquisition.budget_reset_at({})
    with transaction(store.conn):
        store.finish_step(step["id"], "cancelled" if skipped else "failed", output={"unsent": skipped, "reset_at": reset_at},
                          error_code="quota_exhausted")
        store.note_openalex_budget(run["research_id"], run["id"], reset_at, skipped=skipped)
        # A cancel that arrived while the request was in flight stands; the budget answer does not reopen the run.
        if store.run(run["id"])["status"] != "cancelled":
            store.update_run(run["id"], event="run_paused", status="paused", pause_reason=BUDGET_STOP,
                             error_json={"reset_at": reset_at})
    raise RunStopped


def _apply_dois(store: Any, run_id: str, batch: list[dict[str, str]], outcome: Any) -> dict[str, Any]:
    """Each DOI resolves only when exactly one returned work carries it; the resolved version's list is stored from
    the same answer (marked read only when the answer holds a valid list)."""
    by_doi: dict[str, dict[str, Any]] = {}
    for record in outcome.records:
        if doi := normalize_doi(record.doi):
            by_doi.setdefault(doi, {})[record.provider_record_id] = record
    ts, counts = now(), {"resolved": 0, "not_found": 0, "ambiguous": 0, "lists_read": 0}
    for target in batch:
        works = by_doi.get(target["doi"], {})
        status = "resolved" if len(works) == 1 else "ambiguous" if works else "not_found"
        record = next(iter(works.values())) if status == "resolved" else None
        store.conn.execute(
            "INSERT INTO citation_map_resolutions (source_version_id, method, status, openalex_id, doi, run_id, resolved_at)"
            " VALUES (?, 'doi', ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (target["source_version_id"], status, record.provider_record_id if record else None, target["doi"], run_id, ts))
        counts[status] += 1
        if record is not None and _valid_list(record):
            store._store_references(target["source_version_id"], record)
            counts["lists_read"] += 1
    return counts


def _apply_references(store: Any, batch: dict[str, Any], outcome: Any) -> dict[str, Any]:
    """Store each answered work's list on the versions that hold its id, each on its own version."""
    answered: set[str] = set()
    without_list = []
    for record in outcome.records:
        for svid in batch["versions"].get(record.provider_record_id, []):
            answered.add(record.provider_record_id)
            if not _valid_list(record):
                without_list.append(record.provider_record_id)
                continue
            store._store_references(svid, record)
    return {"asked": len(batch["ids"]), "lists_read": len(answered) - len(set(without_list)),
            "without_list": sorted(set(without_list)), "unanswered": sorted(set(batch["ids"]) - answered)}


def _apply_outside(flow: Any, step: dict[str, Any], outcome: Any) -> dict[str, Any]:
    """Store the outside works as provider sources; none joins a research."""
    payload = lookups._write_payload(flow.deps.settings, step["id"], outcome.raw_payload)
    for record in outcome.records:
        flow.store.upsert_provider_source("openalex", record, payload)
    return {"described": len(outcome.records)}

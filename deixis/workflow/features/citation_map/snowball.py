"""Citation snowballing: one round of a series the person starts from works they chose (`snowball` run).

A round reads backward (the seeds' reference lists) and forward (the works citing them, newest first) from OpenAlex,
writes what came back as search candidates of the research, freezes the works that first joined the research in this
round, and screens up to `SCREEN_LIMIT` of them with the discovery's own abstract stage. Nothing is included (SW1.2):
two model reads that agree make a work an abstract-stage candidate, and only the person or a full-text reading
includes it. The next round is started by the person, from seeds they confirm.

Rules this module keeps:

- **Every step is keyed and frozen.** The plan, the seeds' lists, the request plan, each request, the round's list and
  the summary are steps of the run (`operation_key`); a succeeded step is read back and never sent again.
- **"New" is written, not derived.** What each returned OpenAlex identity became is stored in `snowball_admissions` in
  the transaction that writes the request's records and ends its step.
- **Identity before writing.** A returned id that names one local work of the research (by its OpenAlex mapping or a
  citation map resolution, live or removed) writes no new source; the work keeps the person's choice and reason. An id
  naming two local works is `ambiguous` and is not written.
- **No topical gate.** The gate blocks only order the screening (works that name the setting or the task first, then
  works more seeds link to); the abstract stage's lexical exclusion is off. Position, seed count and OpenAlex's order
  are priority signals, never relevance; citation counts are not read.
"""

from __future__ import annotations

from typing import Any

from deixis.documents import acquisition
from deixis.domain import canonical
from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_RUNS, RevisionConflict
from deixis.providers import facade
from deixis.providers.common import FIRST_PAGE, normalize_doi
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import dumps, now, transaction
from deixis.workflow.screen import abstract_stage
from deixis.workflow.search import chaining, lookups
from deixis.workflow.features.citation_map import citation_map_run
from deixis.workflow.features.lineage.lineage_edges import normalize_openalex_id

KIND = "snowball"
POLICY = "snowball_v1"
MAX_SEEDS = 10
MAX_ROUNDS = 3
BACKWARD_REQUESTS = 10
FORWARD_REQUESTS = 20
FORWARD_PAGES = 2  # with an OpenAlex key; without one OpenAlex refuses any page after the first
PAGE_SIZE = 100
SCREEN_LIMIT = 80
SORT = "publication_date:desc"  # a recency preference for the citing works, recorded with every forward request
RATE_LIMIT_RETRIES = 1
DIRECTIONS = ("backward", "forward")
REQUEST_KIND = "provider:snowball"
PLAN_KIND = "code:snowball"
BATCH_KEY = "snowball"
QUERY_PREFIX = "chain:snowball:"
SIGNALS_NOTE = ("The screening order puts works that name the question's setting or task first, then works more seeds "
                "link to; it is a priority order, not a relevance verdict.")


class SnowballRefused(Exception):
    """A round that cannot be queued: the API answers with `status` and `code`."""

    def __init__(self, status: int, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


# ---- identity ------------------------------------------------------------------------------------------------------
def _ids(oid: str) -> tuple[str, str]:
    return oid, f"https://openalex.org/{oid}"


def local_works(store: Any, research_id: str, oids: list[str]) -> dict[str, set[str]]:
    """The research's works (any membership, removed included) each OpenAlex id names, through the stored OpenAlex
    mappings and the citation map's resolutions. D42 keeps resolutions out of deduplication, so a search write alone
    would make a resolved upload's OpenAlex record a second work; this is checked before anything is written."""
    found: dict[str, set[str]] = {oid: set() for oid in oids}
    for start in range(0, len(oids), 400):
        chunk = oids[start:start + 400]
        values = [value for oid in chunk for value in _ids(oid)]
        marks = ",".join("?" * len(values))
        rows = store.conn.execute(
            f"SELECT i.value AS oid, v.work_id FROM identifier_mappings i JOIN source_versions v ON v.id = i.source_version_id"
            f" JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ?"
            f" WHERE i.scheme = 'openalex' AND i.value IN ({marks})"
            f" UNION SELECT r.openalex_id AS oid, v.work_id FROM citation_map_resolutions r"
            f" JOIN source_versions v ON v.id = r.source_version_id"
            f" JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ?"
            f" WHERE r.status = 'resolved' AND r.openalex_id IN ({marks})",
            (research_id, *values, research_id, *values))
        for row in rows:
            if oid := normalize_openalex_id(row["oid"]):
                if oid in found:
                    found[oid].add(row["work_id"])
    return found


def _member_works(store: Any, research_id: str) -> set[str]:
    return {row[0] for row in store.conn.execute(
        "SELECT DISTINCT v.work_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ?", (research_id,))}


def _work_openalex_ids(store: Any, research_id: str, work_id: str) -> list[str]:
    rows = store.conn.execute(
        "SELECT i.value FROM identifier_mappings i JOIN source_versions v ON v.id = i.source_version_id"
        " WHERE i.scheme = 'openalex' AND v.work_id = ?"
        " UNION SELECT r.openalex_id FROM citation_map_resolutions r JOIN source_versions v ON v.id = r.source_version_id"
        " WHERE r.status = 'resolved' AND v.work_id = ?", (work_id, work_id))
    return sorted({oid for row in rows if (oid := normalize_openalex_id(row[0]))})


# ---- queueing ------------------------------------------------------------------------------------------------------
def approved_discovery(store: Any, research_id: str) -> dict[str, Any] | None:
    """The latest completed discovery of the current question revision with an approved vocabulary: the screening reads
    its `protocol_approval`, as Screen more does."""
    revision = store.research(research_id)["current_scope_revision"]
    for row in store.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
            " AND status = 'completed' ORDER BY created_at DESC, id DESC", (research_id, revision)):
        step = store.existing_step(row["id"], "protocol_approval")
        if step is not None and step["status"] == "succeeded":
            return store.run(row["id"])
    return None


def series(store: Any, research_id: str, series_id: str) -> list[dict[str, Any]]:
    """The rounds of one series, oldest first."""
    rounds = [store.run(row["id"]) for row in store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND kind = 'snowball' ORDER BY created_at, id", (research_id,))]
    return [r for r in rounds if (r["target"].get("series_id") or r["id"]) == series_id]


def _seed(store: Any, research_id: str, svid: str) -> dict[str, Any]:
    row = store.conn.execute(
        "SELECT v.work_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ? AND m.source_version_id = ? AND m.removed_at IS NULL", (research_id, svid)).fetchone()
    if row is None:
        raise SnowballRefused(422, "seed_not_in_research", "A seed must be a source of this research", seed=svid)
    head = store.work_heads(research_id).get(row["work_id"], svid)
    oids = _work_openalex_ids(store, research_id, row["work_id"])
    return {"source_version_id": head, "work_id": row["work_id"], "openalex_ids": oids}


def budget(screen: int = SCREEN_LIMIT) -> dict[str, Any]:
    reads = abstract_stage.model_calls(screen, ABSTRACT_BATCH, ABSTRACT_RUNS)
    requests = 1 + 1 + BACKWARD_REQUESTS + FORWARD_REQUESTS  # one DOI lookup, one seed-list lookup, the round's own
    return {"max_model_calls": 2 * reads, "max_provider_requests": requests * (1 + RATE_LIMIT_RETRIES),
            "snowball": {"policy": POLICY, "max_seeds": MAX_SEEDS, "backward_requests": BACKWARD_REQUESTS,
                         "forward_requests": FORWARD_REQUESTS, "forward_pages": FORWARD_PAGES, "page_size": PAGE_SIZE,
                         "screen_limit": screen, "max_rounds": MAX_ROUNDS, "sort": SORT, "reads": reads}}


def request(store: Any, research_id: str, *, seeds: list[str] = (), dois: list[str] = (),
            directions: list[str] = DIRECTIONS, series_id: str | None = None,
            idempotency_key: str | None = None) -> dict[str, Any]:
    """Queue one round. `seeds` are source versions of the research; `dois` are resolved by the run itself (one
    OpenAlex request; a DOI naming exactly one work becomes a person-added, undecided source and a seed)."""
    from deixis.workflow.run.store import ACTIVE_RUN_STATUSES

    directions = [d for d in DIRECTIONS if d in set(directions)]
    if not directions:
        raise SnowballRefused(422, "no_direction", "Choose backward, forward or both")
    dois = list(dict.fromkeys(d for value in dois if (d := normalize_doi(value))))
    key = f"{research_id}:snowball:{idempotency_key}" if idempotency_key else None
    with transaction(store.conn):
        store.research(research_id)
        if key:
            row = store.conn.execute("SELECT id FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
            if row is not None:
                return store.run(row["id"])
        active = store.conn.execute(
            f"SELECT id FROM runs WHERE research_id = ? AND status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1",
            (research_id, *ACTIVE_RUN_STATUSES)).fetchone()
        if active:
            raise RevisionConflict(f"run {active['id']} is still active")
        discovery = approved_discovery(store, research_id)
        if discovery is None:
            raise SnowballRefused(422, "no_approved_search", "A search of this question must finish first")
        round_no = 1
        if series_id:
            rounds = series(store, research_id, series_id)
            if not rounds:
                raise SnowballRefused(404, "no_series", "No snowball series with this id")
            last = rounds[-1]
            if last["status"] != "completed":
                raise SnowballRefused(409, "round_not_finished", "The previous round has not finished")
            if last["scope_revision"] != store.research(research_id)["current_scope_revision"]:
                raise SnowballRefused(409, "stale_series", "The question changed since this series; start a new one")
            if len(rounds) >= MAX_ROUNDS:
                raise SnowballRefused(422, "round_cap", f"A series has at most {MAX_ROUNDS} rounds")
            round_no = len(rounds) + 1
        chosen, unusable, seen, seen_oids = [], [], set(), set()
        for svid in dict.fromkeys(seeds):
            seed = _seed(store, research_id, svid)
            if not seed["openalex_ids"]:
                unusable.append({"source_version_id": seed["source_version_id"], "reason": "no_openalex_id"})
                continue
            # A seed is a work, not a record: a preprint and its published version are one seed, and two local works
            # resolved to the same OpenAlex work (two uploads of one paper) are one seed too.
            if seed["work_id"] in seen or seen_oids & set(seed["openalex_ids"]):
                continue
            seen.add(seed["work_id"])
            seen_oids.update(seed["openalex_ids"])
            chosen.append(seed)
        if len(chosen) + len(dois) > MAX_SEEDS:
            raise SnowballRefused(422, "too_many_seeds", f"At most {MAX_SEEDS} seeds a round")
        if not chosen and not dois:
            raise SnowballRefused(422, "no_usable_seed", "No chosen work has an OpenAlex record", unusable=unusable)
        target = {"policy": POLICY, "series_id": series_id, "round": round_no, "discovery_run_id": discovery["id"],
                  "seeds": chosen, "dois": dois, "unusable": unusable, "directions": directions, "sort": SORT,
                  "keyed": bool(CONNECTORS["openalex"].api_key())}
        return store.create_run(research_id, KIND, budget(), key, target)


# ---- the run -------------------------------------------------------------------------------------------------------
async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    store, run_id = flow.store, run["id"]
    target = run["target"]
    flow._checkpoint(run_id, run["scope_revision"])
    if target["dois"]:
        await _request(flow, run, "snowball:seed_doi", _doi_send(flow, target["dois"]),
                       lambda outcome, step: _apply_dois(store, run, outcome))
    plan = citation_map_run._frozen(store, run_id, "snowball:plan", lambda: _plan(store, run))
    if plan["missing_lists"]:
        await _request(flow, run, "snowball:seed_list:0", _id_send(flow, plan["missing_lists"]),
                       lambda outcome, step: _apply_seed_lists(store, plan, outcome))
    requests = citation_map_run._frozen(store, run_id, "snowball:plan_requests", lambda: _plan_requests(store, run, plan))
    for spec in requests["requests"]:
        await _chain_request(flow, run, spec)
    listing = citation_map_run._frozen(store, run_id, "snowball:list", lambda: _round_list(flow, run, scope))
    await _screen(flow, run, scope, listing)
    flow._checkpoint(run_id, run["scope_revision"])
    citation_map_run._frozen(store, run_id, "snowball:summary", lambda: summary(store, run))


def _plan(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    """The seeds as they stand when the round starts, each with the reference list a version of its work stored (or
    None when none was read), and the research's works at the start."""
    rid, target = run["research_id"], run["target"]
    seeds = list(target["seeds"])
    doi_step = store.existing_step(run["id"], "snowball:seed_doi")
    for resolved in ((doi_step or {}).get("output") or {}).get("seeds", []):
        if (resolved["work_id"] not in {s["work_id"] for s in seeds}
                and not set(resolved["openalex_ids"]) & {oid for s in seeds for oid in s["openalex_ids"]}):
            seeds.append(resolved)
    out, missing = [], []
    for seed in seeds:
        refs = None
        for row in store.conn.execute("SELECT id FROM source_versions WHERE work_id = ? AND references_read = 1"
                                      " ORDER BY created_at, id", (seed["work_id"],)):
            refs = sorted({r[0] for r in store.conn.execute(
                "SELECT referenced_id FROM record_references WHERE source_version_id = ?", (row["id"],))
                if chaining_work_id(r[0])})
            break
        if refs is None:
            missing.append(seed["openalex_ids"][0])
        out.append(seed | {"openalex_id": seed["openalex_ids"][0], "references": refs})
    start = sorted(_member_works(store, rid))
    return {"seeds": out, "missing_lists": sorted(set(missing)), "start_works": len(start),
            "start_works_hash": canonical.sha256_hex(start)}


def chaining_work_id(value: str) -> str | None:
    oid = normalize_openalex_id(value)
    return oid if oid and oid.startswith("W") and oid[1:].isdigit() else None


def _apply_dois(store: Any, run: dict[str, Any], outcome: Any) -> dict[str, Any]:
    """A DOI resolves only when exactly one returned work carries it (D42); the work joins the research as a source the
    person added and nobody screened, unless the research already holds it (then that work is the seed)."""
    rid = run["research_id"]
    by_doi: dict[str, dict[str, Any]] = {}
    for record in outcome.records:
        if doi := normalize_doi(record.doi):
            by_doi.setdefault(doi, {})[record.provider_record_id] = record
    seeds, results = [], []
    for doi in run["target"]["dois"]:
        works = by_doi.get(doi, {})
        if len(works) != 1:
            results.append({"doi": doi, "status": "ambiguous" if works else "not_found"})
            continue
        record = next(iter(works.values()))
        oid = record.provider_record_id
        local = local_works(store, rid, [oid])[oid]
        if len(local) > 1:
            results.append({"doi": doi, "status": "ambiguous_local", "openalex_id": oid})
            continue
        if local:
            work_id = next(iter(local))
            head = store.work_heads(rid).get(work_id)
            if head is None:  # the person removed it: their removal stands
                results.append({"doi": doi, "status": "removed", "openalex_id": oid})
                continue
            results.append({"doi": doi, "status": "in_research", "openalex_id": oid})
        else:
            svid, _ = store.upsert_provider_source("openalex", record, None)
            # "library": the person brought the work in by its DOI; no search found it and no screening judged it.
            store.add_to_corpus(rid, svid, "library", selection_state="pending", selection_origin="user")
            store._corpus_changed(rid, "source_added", [svid], now())
            work_id = store.source(svid)["work_id"]
            head = store.work_heads(rid).get(work_id, svid)
            results.append({"doi": doi, "status": "added", "openalex_id": oid, "source_version_id": head})
        seeds.append({"source_version_id": head, "work_id": work_id, "openalex_ids": [oid]})
    return {"dois": results, "seeds": seeds}


def _apply_seed_lists(store: Any, plan: dict[str, Any], outcome: Any) -> dict[str, Any]:
    """Store each answered seed's list on its seed version, by D42's rule (one malformed entry leaves it unread)."""
    by_oid = {seed["openalex_id"]: seed for seed in plan["seeds"]}
    lists: dict[str, list[str] | None] = {}
    for record in outcome.records:
        seed = by_oid.get(record.provider_record_id)
        if seed is None:
            continue
        if citation_map_run._valid_list(record):
            store._store_references(seed["source_version_id"], record)
            lists[record.provider_record_id] = sorted(set(record.references))
        else:
            lists[record.provider_record_id] = None
    return {"lists": lists, "unanswered": sorted(set(plan["missing_lists"]) - set(lists))}


def _plan_requests(store: Any, run: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """The round's requests, frozen before any is sent. Backward: the seeds' lists merged in seed order, an id the
    research already holds (or one naming two local works) is not asked for but its link is written now; the rest in
    batches of 100, at most `BACKWARD_REQUESTS`. Forward: one page per seed, a second (with a key) that waits for the
    first's cursor."""
    rid, target = run["research_id"], run["target"]
    lists_step = store.existing_step(run["id"], "snowball:seed_list:0")
    answered = ((lists_step or {}).get("output") or {}).get("lists", {}) if lists_step and lists_step["status"] == "succeeded" else {}
    seeds, unread = [], []
    for seed in plan["seeds"]:
        refs = seed["references"] if seed["references"] is not None else answered.get(seed["openalex_id"])
        if refs is None:
            unread.append(seed["source_version_id"])
        seeds.append(seed | {"references": refs})
    specs: list[dict[str, Any]] = []
    held_links, ambiguous, order, links = [], [], [], {}
    if "backward" in target["directions"]:
        seen: set[str] = set()
        for seed in seeds:
            for ref in seed["references"] or []:
                links.setdefault(ref, []).append(seed["source_version_id"])
                if ref not in seen:
                    seen.add(ref)
                    order.append(ref)
        local = local_works(store, rid, order)
        heads = store.work_heads(rid, include_removed=True)
        asked = []
        for ref in order:
            works = local[ref]
            if len(works) > 1:
                ambiguous.append(ref)
            elif works:
                work = next(iter(works))
                held_links += [(seed, ref, heads.get(work)) for seed in links[ref]]
            else:
                asked.append(ref)
        batches = [asked[i:i + PAGE_SIZE] for i in range(0, len(asked), PAGE_SIZE)][:BACKWARD_REQUESTS]
        for batch in batches:
            specs.append({"direction": "backward", "batch": batch,
                          "links": sorted((seed, ref) for ref in batch for seed in links[ref])})
        not_requested = len(asked) - sum(map(len, batches))
    else:
        not_requested = 0
    if "forward" in target["directions"]:
        pages = FORWARD_PAGES if target["keyed"] else 1
        for seed in seeds[:FORWARD_REQUESTS]:
            for page in range(1, pages + 1):
                if sum(s["direction"] == "forward" for s in specs) >= FORWARD_REQUESTS:
                    break
                specs.append({"direction": "forward", "cites": seed["openalex_id"], "page": page,
                              "seed": seed["source_version_id"]})
    for i, spec in enumerate(specs):
        spec["index"] = i
        spec["key"] = f"chain:snowball:{i}"
        if spec["direction"] == "forward" and spec["page"] > 1:
            spec["after"] = f"chain:snowball:{i - 1}"
    with transaction(store.conn):
        store.conn.executemany(
            "INSERT OR IGNORE INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id,"
            " linked_openalex_id, direction, passed_filter, source_version_id) VALUES (?, ?, ?, ?, ?, 'backward', ?, ?)",
            [(rid, run["scope_revision"], run["id"], seed, ref, int(head is not None), head)
             for seed, ref, head in held_links])
    return {"requests": specs, "seeds": [s["source_version_id"] for s in seeds], "unread_seeds": unread,
            "backward_ids": len(order), "held": len({ref for _, ref, _ in held_links}), "ambiguous": ambiguous,
            "not_requested": not_requested,
            "forward_not_requested": max(0, len(seeds) - FORWARD_REQUESTS) if "forward" in target["directions"] else 0}


def _doi_send(flow: Any, dois: list[str]):
    return citation_map_run._doi_send(flow, dois)


def _id_send(flow: Any, ids: list[str]):
    return citation_map_run._id_send(flow, ids)


async def _request(flow, run, key, send, apply) -> None:
    await citation_map_run._request(flow, run, key, send, apply, kind=REQUEST_KIND)


async def _chain_request(flow: Any, run: dict[str, Any], spec: dict[str, Any]) -> None:
    """One backward batch or forward page as its own step: sent once; its records, admissions and links are written in
    the transaction that ends the step."""
    store, run_id = flow.store, run["id"]
    step = store.step(run_id, spec["key"], REQUEST_KIND)
    if step["status"] == "succeeded":
        return
    cursor = FIRST_PAGE
    if spec.get("after"):
        before = store.existing_step(run_id, spec["after"])
        cursor = ((before or {}).get("output") or {}).get("next_cursor") if before and before["status"] == "succeeded" else None
        if not cursor:
            with transaction(store.conn):
                store.start_step(step["id"])
                store.finish_step(step["id"], "cancelled", output={"unsent": "no_cursor", "returned": 0})
            return
    flow._checkpoint(run_id, run["scope_revision"])
    budget = flow._openalex_budget_of(run_id)
    if budget.exhausted:
        citation_map_run._budget_stop(flow, run, step, budget.reset_at, skipped=True)
    store.start_step(step["id"])
    reserved = 1 + RATE_LIMIT_RETRIES
    store.add_usage(run_id, "provider_requests", reserved)
    key = CONNECTORS["openalex"].api_key()
    if spec["direction"] == "forward":
        dispatched = await facade.dispatch_citing("openalex", flow.deps.http, spec["cites"], cursor, PAGE_SIZE, key,
                                                  flow.deps.settings.contact_email, RATE_LIMIT_RETRIES, sort=SORT)
    else:
        dispatched = await facade.dispatch_lookup("openalex", "id_lookup", flow.deps.http, tuple(spec["batch"]), key,
                                                  flow.deps.settings.contact_email, RATE_LIMIT_RETRIES)
    lookups.settle_dispatch(store, run_id, step, dispatched, reserved, "provider_requests", "provider_sends")
    outcome = dispatched.outcome
    if outcome.error_kind == "quota_exhausted":
        citation_map_run._budget_stop(flow, run, step, acquisition.budget_reset_at(outcome.rate_limit), skipped=False)
    _write(flow, run, step, spec, dispatched, cursor)


def _write(flow: Any, run: dict[str, Any], step: dict[str, Any], spec: dict[str, Any], dispatched: Any,
           cursor: str) -> None:
    store, rid, run_id = flow.store, run["research_id"], run["id"]
    outcome = dispatched.outcome
    ok = outcome.status in ("completed", "zero_results")
    payload_path = lookups._write_payload(flow.deps.settings, step["id"], outcome.raw_payload)
    direction = spec["direction"]
    output = {"status": outcome.status, "direction": direction, "returned": len(outcome.records),
              "dropped_records": dispatched.dropped_records, "provider_total": outcome.provider_total,
              "next_cursor": outcome.next_cursor if direction == "forward" else None,
              "cursor": cursor if direction == "forward" else None, "sort": SORT if direction == "forward" else None}
    output = lookups.transport_output(store, step, output)
    fields = dict(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=run["scope_revision"],
                  provider="openalex", query_text=f"{QUERY_PREFIX}{direction}:{spec['index']}",
                  request_description=f"citation snowballing, {direction}: {outcome.request_description}",
                  access_mode=outcome.access_mode, status=outcome.status, delivery_class=outcome.delivery_class,
                  provider_total=outcome.provider_total, page_limit=PAGE_SIZE,
                  error_json=dumps({"error": outcome.error, "http_status": outcome.http_status,
                                    "returned": dispatched.returned_count}
                                   | ({"error_kind": outcome.error_kind} if outcome.error_kind is not None else {})),
                  raw_payload_path=payload_path,
                  payload_sha256=canonical.sha256_hex(outcome.raw_payload) if outcome.raw_payload is not None else None,
                  connector_json=dumps(dispatched.connector),
                  **({"page_number": spec["page"]} if direction == "forward" else {}))
    with transaction(store.conn):
        if not ok:
            final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
            store.record_search(fields | {"result_count": 0}, "openalex", [], payload_path, step["id"], final,
                                step_output=output, error_code=outcome.status,
                                error={"error": outcome.error, "http_status": outcome.http_status},
                                delivery_class=outcome.delivery_class)
            return
        records = list({r.provider_record_id: r for r in outcome.records}.values())
        oids = [r.provider_record_id for r in records]
        local = local_works(store, rid, oids)
        before = _member_works(store, rid)
        this_round = {row[0] for row in store.conn.execute(
            "SELECT work_id FROM snowball_admissions WHERE run_id = ? AND outcome = 'new'", (run_id,))}
        heads = store.work_heads(rid, include_removed=True)
        rows, to_write = [], []
        for position, record in enumerate(records):
            oid = record.provider_record_id
            works = local[oid]
            if len(works) > 1:
                rows.append((position, oid, "ambiguous", None, None))
            elif works:
                work = next(iter(works))
                rows.append((position, oid, "seen" if work in this_round else "existing", work, heads.get(work)))
            else:
                to_write.append((position, record))
        store.record_search(fields | {"result_count": len(to_write)}, "openalex", [r for _, r in to_write],
                            payload_path, step["id"], "succeeded", step_output=output | {"written": len(to_write)})
        heads = store.work_heads(rid, include_removed=True)
        for position, record in to_write:
            svid = store.find_source_by_identifier("openalex", record.provider_record_id)
            work = store.source(svid)["work_id"] if svid else None
            outcome_name = ("seen" if work in this_round else "existing" if work in before else "new")
            if outcome_name == "new":
                this_round.add(work)
            rows.append((position, record.provider_record_id, outcome_name, work, heads.get(work, svid)))
        if direction == "backward":
            returned = set(oids)
            complete = (outcome.provider_total is not None and outcome.provider_total <= len(outcome.records)
                        and not dispatched.dropped_records)
            for oid in spec["batch"]:
                if oid not in returned:
                    rows.append((len(rows), oid, "no_record" if complete else "unresolved", None, None))
        store.conn.executemany(
            "INSERT OR IGNORE INTO snowball_admissions (run_id, request_index, position, openalex_id, outcome, work_id,"
            " source_version_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(run_id, spec["index"], position, oid, name, work, svid) for position, oid, name, work, svid in rows])
        by_oid = {oid: svid for _, oid, name, _, svid in rows if name in ("new", "seen", "existing")}
        pairs = (spec["links"] if direction == "backward"
                 else [(spec["seed"], oid) for oid in oids])
        store.conn.executemany(
            "INSERT OR IGNORE INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id,"
            " linked_openalex_id, direction, passed_filter, source_version_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(rid, run["scope_revision"], run_id, seed, oid, direction, int(oid in by_oid), by_oid.get(oid))
             for seed, oid in pairs])


# ---- the round's list and its screening ----------------------------------------------------------------------------
def _vocabulary(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    from deixis.workflow.search import search_query as search_query_rules
    approval = store.existing_step(run["target"]["discovery_run_id"], "protocol_approval")
    approved = approval["output"]["approved"]
    return search_query_rules.settled(approved["vocabulary"], approved["queries"])


def _round_list(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    """The works that first joined the research in this round, read from the admissions, each with the seeds and
    directions that link to it, in screening order (gate blocks named first, then more linking seeds, then arrival)."""
    store, rid = flow.store, run["research_id"]
    forms = flow._chain_forms(run, scope, _vocabulary(store, run))
    heads = store.work_heads(rid)
    works: dict[str, dict[str, Any]] = {}
    for row in store.conn.execute(
            "SELECT work_id, request_index, position FROM snowball_admissions WHERE run_id = ? AND outcome = 'new'"
            " ORDER BY request_index, position", (run["id"],)):
        if row["work_id"] in heads and row["work_id"] not in works:
            works[row["work_id"]] = {"work_id": row["work_id"], "head": heads[row["work_id"]],
                                     "arrival": len(works)}
    work_of = store.work_ids([r[0] for r in store.conn.execute(
        "SELECT DISTINCT source_version_id FROM chain_links WHERE run_id = ? AND source_version_id IS NOT NULL",
        (run["id"],))])
    for row in store.conn.execute("SELECT seed_source_version_id, direction, source_version_id FROM chain_links"
                                  " WHERE run_id = ? AND source_version_id IS NOT NULL", (run["id"],)):
        item = works.get(work_of.get(row["source_version_id"]))
        if item is not None:
            item.setdefault("seeds", set()).add(row["seed_source_version_id"])
            item.setdefault("directions", set()).add(row["direction"])
    items = []
    for item in works.values():
        source = store.source(item["head"])
        abstract = store.conn.execute("SELECT text FROM passages WHERE source_version_id = ? AND kind = 'abstract'"
                                      " LIMIT 1", (item["head"],)).fetchone()
        items.append({"work_id": item["work_id"], "head": item["head"], "seeds": sorted(item.get("seeds", ())),
                      "directions": sorted(item.get("directions", ())),
                      "names_gate_block": chaining.passes(forms, source["title"], abstract[0] if abstract else None),
                      "arrival": item["arrival"]})
    items.sort(key=lambda i: (not i["names_gate_block"], -len(i["seeds"]), i["arrival"]))
    for position, item in enumerate(items):
        item["position"] = position + 1
    return {"items": items, "manifest_hash": canonical.sha256_hex(items), "signals_note": SIGNALS_NOTE,
            "screen_limit": SCREEN_LIMIT}


async def _screen(flow: Any, run: dict[str, Any], scope: dict[str, Any], listing: dict[str, Any]) -> None:
    from deixis.workflow.screen import screen_more
    heads = [item["head"] for item in listing["items"][:listing["screen_limit"]]]
    if not heads:
        return
    flow._abstract_close_hooks[run["id"]] = lambda: screen_more.mark_answer(flow.store, run)
    try:
        await flow._abstract_stage(run, scope, _vocabulary(flow.store, run), order=heads, batch_key=BATCH_KEY,
                                   read_limit=len(heads), lexical_exclusion=False)
    finally:
        flow._abstract_close_hooks.pop(run["id"], None)


# ---- what a round did ----------------------------------------------------------------------------------------------
def screening_states(store: Any, research_id: str, work_ids: list[str], run_id: str | None = None) -> dict[str, str]:
    """How far each work's abstract screening got, from its current abstract-stage decisions (of one run when `run_id`
    is given): `model_read` (two model reads closed it), `code` (code closed it without a read), `no_abstract` (nothing
    to read), `not_read` (planned or not, no read yet). A person's decision is `person`. Planning a work is not reading it."""
    if not work_ids:
        return {}
    marks = ",".join("?" * len(work_ids))
    rows = store.conn.execute(
        f"SELECT v.work_id, d.reason_code, d.decided_by FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
        f"{' JOIN run_steps s ON s.id = d.step_id' if run_id else ''}"
        f" WHERE d.research_id = ? AND d.stage = 'abstract' AND d.superseded_at IS NULL AND v.work_id IN ({marks})"
        f"{' AND s.run_id = ?' if run_id else ''}", (research_id, *work_ids, *((run_id,) if run_id else ())))
    rank = {"person": 4, "model_read": 3, "code": 2, "no_abstract": 1, "not_read": 0}
    out = dict.fromkeys(work_ids, "not_read")
    for row in rows:
        state = ("person" if row["decided_by"] == "human" else
                 "model_read" if row["reason_code"] in abstract_stage.MODEL_CODES else
                 "no_abstract" if row["reason_code"] in ("no_abstract", "abstract_not_found") else
                 "not_read" if row["reason_code"] in abstract_stage.UNREAD_CODES else "code")
        if rank[state] > rank[out[row["work_id"]]]:
            out[row["work_id"]] = state
    # The abstract stage writes nothing for a new work without an abstract: it has nothing to read, not a read to come.
    with_abstract = {row[0] for row in store.conn.execute(
        f"SELECT DISTINCT v.work_id FROM passages p JOIN source_versions v ON v.id = p.source_version_id"
        f" WHERE p.kind = 'abstract' AND length(trim(p.text)) > 0 AND v.work_id IN ({marks})", work_ids)}
    for work_id, state in out.items():
        if state == "not_read" and work_id not in with_abstract:
            out[work_id] = "no_abstract"
    return out


def summary(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    """The round's counts, each kept apart: seeds, requests, what came back, what was new, screened and made a
    candidate. Read from the admissions and the steps; a person's later choice is not part of it."""
    from deixis.workflow.screen import screen_more
    rid = run["research_id"]
    steps = {s["operation_key"]: s | {"output": store.step_output(s["id"])} for s in store.run_steps(run["id"])}
    plan = (steps.get("snowball:plan") or {}).get("output") or {}
    requests = (steps.get("snowball:plan_requests") or {}).get("output") or {}
    listing = (steps.get("snowball:list") or {}).get("output") or {"items": []}
    outcomes: dict[str, int] = {}
    for row in store.conn.execute("SELECT outcome, COUNT(DISTINCT openalex_id) FROM snowball_admissions"
                                  " WHERE run_id = ? GROUP BY outcome", (run["id"],)):
        outcomes[row[0]] = row[1]
    per_request = []
    unsent: dict[str, int] = {}
    for spec in requests.get("requests", []):
        step = steps.get(spec["key"])
        output = (step or {}).get("output") or {}
        status = step["status"] if step else "not_started"
        if output.get("unsent"):
            unsent[str(output["unsent"])] = unsent.get(str(output["unsent"]), 0) + 1
        per_request.append({"index": spec["index"], "direction": spec["direction"], "status": status,
                            "seed": spec.get("seed"), "page": spec.get("page"),
                            "asked": len(spec.get("batch") or []), "returned": output.get("returned", 0),
                            "provider_total": output.get("provider_total"), "unsent": output.get("unsent")})
    limit = listing.get("screen_limit", SCREEN_LIMIT)
    planned = [item["work_id"] for item in listing["items"][:limit]]
    states = screening_states(store, rid, planned, run["id"])
    screening = {name: sum(state == name for state in states.values())
                 for name in ("model_read", "code", "no_abstract", "not_read")}
    codes: dict[str, int] = {}
    for row in store.conn.execute(
            "SELECT d.reason_code, v.work_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
            " JOIN source_versions v ON v.id = d.source_version_id WHERE s.run_id = ? AND d.stage = 'abstract'"
            " AND d.superseded_at IS NULL", (run["id"],)):
        if row["work_id"] in set(planned):
            codes[row["reason_code"]] = codes.get(row["reason_code"], 0) + 1
    candidates = [w for w in screen_more._candidate_works(store, run["id"]) if w in set(planned)]
    return {"round": run["target"]["round"], "seeds": len(plan.get("seeds", [])),
            "unusable_seeds": len(run["target"].get("unusable", [])),
            "seeds_without_list": len(requests.get("unread_seeds", [])),
            "backward_ids": requests.get("backward_ids", 0), "held": requests.get("held", 0),
            "ambiguous_planned": len(requests.get("ambiguous", [])),
            "not_requested": requests.get("not_requested", 0),
            "forward_seeds_not_requested": requests.get("forward_not_requested", 0),
            "requests": per_request, "unsent": unsent, "admissions": outcomes,
            "new_works": len(listing["items"]), "planned_for_screening": len(planned), "screening": screening,
            "not_screened_limit": max(0, len(listing["items"]) - limit),
            "reason_codes": dict(sorted(codes.items())), "candidates": candidates}


# ---- what the page shows -------------------------------------------------------------------------------------------
def _selections(store: Any, research_id: str) -> dict[str, dict[str, Any]]:
    return {row["source_version_id"]: dict(row) for row in store.conn.execute(
        "SELECT source_version_id, state, origin FROM selections WHERE research_id = ?", (research_id,))}


def suggested_seeds(store: Any, run: dict[str, Any]) -> list[str]:
    """The next round's preselected seeds: this round's new works two model reads made candidates and whose decision
    still stands, and the ones the person included; never one the person excluded. Order and citation counts choose
    nothing."""
    from deixis.workflow.screen import screen_more
    rid = run["research_id"]
    listing = (store.existing_step(run["id"], "snowball:list") or {}).get("output") or {"items": []}
    heads = store.work_heads(rid)
    chosen = set(screen_more._candidate_works(store, run["id"]))
    selections = _selections(store, rid)
    out = []
    for item in listing["items"]:
        head = heads.get(item["work_id"])
        state = (selections.get(head) or {})
        if head is None or (state.get("origin") == "user" and state.get("state") == "excluded"):
            continue
        if item["work_id"] in chosen or (state.get("origin") == "user" and state.get("state") == "included"):
            out.append(head)
    return out[:MAX_SEEDS]


def view(store: Any, research_id: str, include_excluded: bool = False) -> dict[str, Any]:
    research = store.research(research_id)
    discovery = approved_discovery(store, research_id)
    heads = store.work_heads(research_id)
    selections = _selections(store, research_id)
    options = []
    for work_id, head in heads.items():
        state = selections.get(head) or {}
        if state.get("state") == "excluded" and not include_excluded:
            continue
        source = store.source(head)
        options.append({"source_version_id": head, "work_id": work_id, "title": source["title"],
                        "year": source.get("year"), "state": state.get("state"), "decided_by_person": state.get("origin") == "user",
                        "has_openalex_id": bool(_work_openalex_ids(store, research_id, work_id))})
    options.sort(key=lambda o: ({"included": 0, "uncertain": 1}.get(o["state"], 2), (o["title"] or "").casefold()))
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'snowball' ORDER BY created_at, id",
                                  (research_id,)):
        run = store.run(row["id"])
        by_series.setdefault(run["target"].get("series_id") or run["id"], []).append(run)
    series_out = []
    for series_id, rounds in by_series.items():
        out_rounds = []
        for run in rounds:
            summary_step = store.existing_step(run["id"], "snowball:summary")
            listing = (store.existing_step(run["id"], "snowball:list") or {}).get("output") or {"items": []}
            candidates = set(((summary_step or {}).get("output") or {}).get("candidates", []))
            states = screening_states(store, research_id, [item["work_id"] for item in listing["items"]])
            items = []
            for item in listing["items"]:
                head = heads.get(item["work_id"])
                state = selections.get(head) or {}
                source = store.source(head) if head else None
                items.append({"work_id": item["work_id"], "source_version_id": head,
                              "title": source["title"] if source else None,
                              "year": source.get("year") if source else None, "position": item["position"],
                              "seeds": len(item["seeds"]), "directions": item["directions"],
                              "planned_in_round": item["position"] <= listing.get("screen_limit", SCREEN_LIMIT),
                              "screening": states.get(item["work_id"], "not_read"),
                              "candidate": item["work_id"] in candidates, "removed": head is None,
                              "person_state": state.get("state") if state.get("origin") == "user" else None})
            out_rounds.append({"run_id": run["id"], "round": run["target"]["round"], "status": run["status"],
                               "pause_reason": run.get("pause_reason"), "error": run.get("error"),
                               "directions": run["target"]["directions"], "sort": run["target"]["sort"],
                               "seeds": [s["source_version_id"] for s in
                                         ((store.existing_step(run["id"], "snowball:plan") or {}).get("output") or {}).get("seeds", run["target"]["seeds"])],
                               "dois": ((store.existing_step(run["id"], "snowball:seed_doi") or {}).get("output") or {}).get("dois"),
                               "summary": (summary_step or {}).get("output") if summary_step and summary_step["status"] == "succeeded" else None,
                               "items": items})
        last = rounds[-1]
        stale = last["scope_revision"] != research["current_scope_revision"]
        next_seeds = suggested_seeds(store, last) if last["status"] == "completed" else []
        series_out.append({"series_id": series_id, "scope_revision": last["scope_revision"], "stale": stale,
                           "rounds": out_rounds, "can_continue": last["status"] == "completed" and not stale
                           and len(rounds) < MAX_ROUNDS, "suggested_seeds": next_seeds})
    return {"available": discovery is not None,
            "unavailable_reason": None if discovery else "no_approved_search",
            "limits": budget()["snowball"], "signals_note": SIGNALS_NOTE, "seed_options": options,
            "series": series_out}

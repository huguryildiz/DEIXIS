"""The search of an `sw` research reported against the 16 PRISMA-S checklist items (slice 20, decision 8).

Everything comes from stored rows of the current question revision; nothing is requested, no model is called and
nothing is written. The export is in English (owner's answer B). It never calls the review PRISMA-compliant: the
screening was done by code and model runs, and a person looked only at queued and audited records.

Each item has one of four statuses. `reported`: filled from stored rows. `incomplete`: filled, and a stored row says
something is missing, or a part the item asks for (a justification, say) is not stored. `not_performed`: DEIXIS has
no such method, or the protocol switched it off; a protocol fact is traced to its protocol row, a fact read from the
absence of something in the code is carried in `code_source`. `not_recorded`: it may have been done, outside DEIXIS,
and nothing records it. "Not recorded" is never written as "not performed".

`trace` holds only row ids that resolve to one stored row each; counts over many rows are `aggregates`, a
re-runnable `{table, filter, count}`. A search group is the unit of the search table and of item 15: one (run,
provider, query text) over its pages in page order, chain requests grouped the same way and kept apart. A group ends
complete when its last page is `completed` or `zero_results`; records a read limit left unread are a limit (item 9),
not a failure.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

from deixis.providers import query_compiler, registry
from deixis.storage.db import now
from deixis.workflow import flow_counts as flow_rules
from deixis.workflow import probes as probe_rules
from deixis.workflow import queue
from deixis.workflow.chaining import QUERY_PREFIX as CHAIN_PREFIX
from deixis.workflow.store import ACTIVE_RUN_STATUSES, Store

CHECKLIST = "PRISMA-S"
CITATION = {"authors": "Rethlefsen ML, Kirtley S, Waffenschmidt S, Ayala AP, Moher D, Page MJ, Koffel JB",
            "title": "PRISMA-S: an extension to the PRISMA Statement for Reporting Literature Searches in "
                     "Systematic Reviews", "journal": "Syst Rev", "year": 2021, "volume": 10, "article": "39",
            "doi": "10.1186/s13643-020-01542-z"}
STATEMENT = ("The search is reported against the PRISMA-S checklist items. This is not a PRISMA-compliant review: "
             "screening was done by code and model runs, and a person looked only at queued and audited records.")
RUNNING_NOTE = "A run is in progress; the numbers can change."
STATUSES = ("reported", "incomplete", "not_performed", "not_recorded")
ENDED = ("completed", "zero_results")
NAMES = {1: "Database name", 2: "Multi-database searching", 3: "Study registries",
         4: "Online resources and browsing", 5: "Citation searching", 6: "Contacts", 7: "Other methods",
         8: "Full search strategies", 9: "Limits and restrictions", 10: "Search filters", 11: "Prior work",
         12: "Updates", 13: "Dates of searches", 14: "Peer review", 15: "Total records", 16: "Deduplication"}
# A source searched through another's API (D13): bioRxiv's own query goes to OpenAlex with a server filter.
THROUGH = {"biorxiv": "openalex"}
REGISTRY_WORDS = ("clinicaltrials", "ictrp", "registry", "trials")


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _pin(path: Path, fact: str) -> dict[str, Any]:
    """A code fact's origin, with the digest of the file as the running code loaded it."""
    try:
        source = str(path.resolve().relative_to(_root()))
    except ValueError:
        source = str(path)
    return {"path": path, "source": source, "fact": fact, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


# Pinned when this module is imported: the source of the code that is running, not of whatever is on disk later.
CODE_SOURCES = {
    "registry": _pin(Path(registry.__file__), "no_registry_connector"),
    "separate": _pin(Path(registry.__file__), "each_database_queried_separately"),
    "filters": _pin(Path(query_compiler.__file__), "no_published_search_filter"),
}


def code_version() -> str:
    return (f"deixis/{version('deixis')} {query_compiler.VERSION} {query_compiler.COMPACT_VERSION} "
            f"{query_compiler.BLOCKS_VERSION}")


def _code_source(key: str, **extra: Any) -> dict[str, Any]:
    pinned = CODE_SOURCES[key]
    try:
        on_disk = hashlib.sha256(Path(pinned["path"]).read_bytes()).hexdigest()
    except OSError:
        on_disk = None
    return {"code_version": code_version(), "source": pinned["source"], "sha256": pinned["sha256"],
            "verified": on_disk == pinned["sha256"], "fact": pinned["fact"], **extra}


class NotAnSwResearch(Exception):
    """The export belongs to the search workflow; the API answers 422."""


# ---- reading the stored rows -----------------------------------------------------------------------------------------


def _request_parts(description: str | None) -> dict[str, Any]:
    """The field and parameters a stored request description names; never a key (none is stored)."""
    text = description or ""
    found = {name: match.group(1) for name in ("filter", "sort", "per_page", "fields", "limit")
             if (match := re.search(rf"\b{name}=(\S+)", text))}
    method = text.split(" ", 2)
    return {"method": method[0] if method and method[0] else None,
            "endpoint": method[1] if len(method) > 1 else None, **found}


def _groups(store: Store, research_id: str, revision: int) -> list[dict[str, Any]]:
    """The revision's search groups in the order their first page was read, keyword groups before chain groups."""
    rows = [dict(row) for row in store.conn.execute(
        "SELECT sr.id, sr.run_id, sr.provider, sr.query_text, sr.request_description, sr.status, sr.result_count,"
        " sr.provider_total, sr.read_limit, sr.read_total, sr.unread_count, sr.stop_reason, sr.retrieved_at,"
        " sr.page_number, sr.rowid AS row_order, st.operation_key FROM search_runs sr"
        " JOIN run_steps st ON st.id = sr.step_id WHERE sr.research_id = ? AND sr.scope_revision = ?",
        (research_id, revision))]
    # A group's pages in page order: its end state is its highest page's, whatever the clock said when each page was
    # stored; the first and last read are the earliest and latest stamps, taken apart.
    rows.sort(key=lambda r: (r["page_number"] or 0, r["retrieved_at"], r["row_order"]))
    cards: dict[str, list[dict[str, Any]]] = {}
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["run_id"], row["provider"], row["query_text"])
        group = groups.get(key)
        if group is None:
            chain = row["query_text"].startswith(CHAIN_PREFIX)
            if row["run_id"] not in cards:
                card = store.existing_step(row["run_id"], "protocol_approval")
                cards[row["run_id"]] = (((card or {}).get("output") or {}).get("approved") or {}).get("queries") or []
            queries = cards[row["run_id"]]
            index = re.match(r"search:(\d+)", row["operation_key"] or "")
            number = int(index.group(1)) if index else None
            second = bool(queries) and number is not None and number >= len(queries)
            origin = ("chain" if chain else "expansion" if second else
                      (queries[number].get("origin") if number is not None and number < len(queries) else None))
            group = groups[key] = {
                "kind": "chain" if chain else "keyword", "run_id": row["run_id"], "provider": row["provider"],
                "through": THROUGH.get(row["provider"]), "origin": origin,
                "round": None if chain else 2 if second else 1, "query_text": row["query_text"],
                "request": _request_parts(row["request_description"]), "request_description": row["request_description"],
                "search_run_ids": [], "first_retrieved_at": row["retrieved_at"], "last_retrieved_at": row["retrieved_at"],
                "rows_returned": 0, "provider_total": None, "read_limit": row["read_limit"], "unread_by_limit": 0,
                "pages": 0, "read": False, "end_status": None, "stop_reason": None}
        group["search_run_ids"].append(row["id"])
        group["first_retrieved_at"] = min(group["first_retrieved_at"], row["retrieved_at"])
        group["last_retrieved_at"] = max(group["last_retrieved_at"], row["retrieved_at"])
        group["rows_returned"] += row["result_count"] or 0
        group["pages"] += 1
        group["read"] |= (row["result_count"] or 0) > 0
        group["end_status"] = row["status"]
        group["stop_reason"] = row["stop_reason"]
        if row["provider_total"] is not None:
            group["provider_total"] = row["provider_total"]
        if row["stop_reason"] == "read_limit" and row["unread_count"]:
            group["unread_by_limit"] = row["unread_count"]
    ordered = sorted(groups.values(), key=lambda g: (g["kind"] == "chain", g["first_retrieved_at"], g["provider"],
                                                     g["query_text"]))
    for number, group in enumerate(ordered, start=1):
        group["group"] = number
        group["ended_complete"] = group["end_status"] in ENDED
    return ordered


def _item(number: int, status: str, text: str, values: dict[str, Any] | None = None, trace: list[str] | None = None,
          aggregates: list[dict[str, Any]] | None = None, code_source: dict[str, Any] | None = None) -> dict[str, Any]:
    assert status in STATUSES
    if code_source is not None and not code_source["verified"]:
        text += (" The code origin of this fact is not verified: the source file changed after the running code "
                 "was loaded.")
    return {"number": number, "name": NAMES[number], "status": status, "text": text, "values": values or {},
            "trace": trace or [], "aggregates": aggregates or [], "code_source": code_source}


def _ended_counts(groups: list[dict[str, Any]]) -> dict[str, Any]:
    open_groups = [g for g in groups if not g["ended_complete"]]
    return {
        "groups": len(groups), "ended_complete": len(groups) - len(open_groups), "not_complete": len(open_groups),
        "not_complete_by_status": dict(sorted(Counter(g["end_status"] for g in open_groups).items())),
        "nothing_read": sum(not g["read"] for g in open_groups),
        "nothing_read_by_status": dict(sorted(Counter(g["end_status"] for g in open_groups if not g["read"]).items())),
        "read_then_stopped": sum(g["read"] for g in open_groups),
        "read_then_stopped_records": sum(g["rows_returned"] for g in open_groups if g["read"]),
    }


def export(store: Store, research_id: str) -> dict[str, Any]:
    """The PRISMA-S export of the research's current revision as JSON-ready data."""
    scope = store.scope(research_id)
    if scope.get("search_workflow") != "sw":
        raise NotAnSwResearch("The PRISMA-S export belongs to the search workflow")
    with queue._snapshot(store.conn):
        return _export(store, research_id, scope)


def _export(store: Store, research_id: str, scope: dict[str, Any]) -> dict[str, Any]:
    conn = store.conn
    research = store.research(research_id)
    revision = research["current_scope_revision"]
    protocols = [dict(row) | {"body": json.loads(row["body_json"])} for row in conn.execute(
        "SELECT id, protocol_revision, reason, body_json, body_sha256, created_at FROM protocol_records"
        " WHERE research_id = ? AND scope_revision = ? ORDER BY protocol_revision", (research_id, revision))]
    protocol_trace = [f"protocol_records:{p['id']}" for p in protocols]
    latest = protocols[-1] if protocols else None
    body = latest["body"] if latest else {}
    runs = [dict(row) for row in conn.execute(
        "SELECT id, kind, status, created_at FROM runs WHERE research_id = ? AND scope_revision = ?"
        " ORDER BY created_at, id", (research_id, revision))]
    running = any(run["status"] in ACTIVE_RUN_STATUSES for run in
                  conn.execute("SELECT status FROM runs WHERE research_id = ?", (research_id,)))
    discovery = [run for run in runs if run["kind"] == "discovery"]
    groups = _groups(store, research_id, revision)
    keyword = [g for g in groups if g["kind"] == "keyword"]
    chain = [g for g in groups if g["kind"] == "chain"]
    searched = sorted({g["provider"] for g in keyword})
    items: list[dict[str, Any]] = []

    # 1 — the databases, and how each was reached.
    if searched:
        names = ", ".join(f"{p} (direct API" + (f", searched through the {THROUGH[p]} API" if p in THROUGH else "")
                          + ")" for p in searched)
        items.append(_item(1, "reported", f"Databases searched: {names}.",
                           {"databases": [{"provider": p, "access": "direct API", "through": THROUGH.get(p)}
                                          for p in searched],
                            "protocol_providers": body.get("providers")}, protocol_trace))
    else:
        items.append(_item(1, "not_recorded", "No database search was recorded for this question revision.",
                           {}, protocol_trace))

    # 2 — no simultaneous multi-database search: each connector is its own API.
    separate = ("Each database was queried separately through its own interface; no platform searched several "
                "databases in one query.")
    two_values: dict[str, Any] = {}
    if "biorxiv" in searched:
        two_values["biorxiv"] = ("bioRxiv was searched with its own query through the OpenAlex API, filtered to "
                                 "bioRxiv; it is not a simultaneous search of several databases.")
    items.append(_item(2, "not_performed", separate, two_values, protocol_trace,
                       code_source=_code_source("separate", connectors=sorted(registry.CONNECTORS))))

    # 3 — study registries: no connector is one.
    registries = sorted(p for p in registry.CONNECTORS if any(word in p for word in REGISTRY_WORDS))
    items.append(_item(3, "not_performed" if not registries else "not_recorded",
                       "None of the DEIXIS search connectors is a study registry."
                       if not registries else "A registry connector exists but no registry search was recorded.",
                       {"registry_connectors": registries},
                       code_source=_code_source("registry", connectors=sorted(registry.CONNECTORS))))

    # 4 — browsing.
    items.append(_item(4, "not_recorded", "DEIXIS does not browse websites; browsing done outside DEIXIS is not "
                                          "recorded here."))

    # 5 — citation searching.
    summaries = [dict(row) for row in conn.execute(
        "SELECT s.id, s.run_id, s.output_json FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND r.scope_revision = ? AND s.operation_key = 'chain_summary' AND s.status = 'succeeded'"
        " ORDER BY s.finished_at, s.id", (research_id, revision))]
    chaining = body.get("citation_chaining")
    if summaries:
        outputs = [json.loads(s["output_json"] or "{}") for s in summaries]
        failed = sum((o.get("requests") or {}).get("failed") or 0 for o in outputs)
        chain_open = [g for g in chain if not g["ended_complete"]]
        status = "incomplete" if failed or chain_open else "reported"
        text = ("Backward and forward citation searching from seed works through OpenAlex "
                f"({len(chain)} request groups).")
        if status == "incomplete":
            text += f" {len(chain_open)} request groups did not end complete and {failed} requests failed."
        items.append(_item(5, status, text, {
            "policy": chaining,
            "runs": [{"run_id": s["run_id"], "seeds": o.get("seeds"), "requests": o.get("requests"),
                      "new_works": o.get("new_works"), "read_by_model": o.get("read_by_model"),
                      "not_read": o.get("not_read")} for s, o in zip(summaries, outputs)],
            "chain_groups": _ended_counts(chain)},
            [f"run_steps:{s['id']}" for s in summaries] + protocol_trace))
    elif isinstance(chaining, dict) and chaining.get("enabled") is False:
        items.append(_item(5, "not_performed", "The protocol switched citation chaining off.",
                           {"policy": chaining}, protocol_trace))
    else:
        items.append(_item(5, "not_recorded", "No citation search was recorded in DEIXIS for this question revision.",
                           {"policy": chaining}, protocol_trace))

    # 6 — contacts.
    items.append(_item(6, "not_recorded", "Contacting authors or experts is not recorded in DEIXIS."))

    # 7 — other methods: works the person brought, and the seed.
    brought = [dict(row) for row in conn.execute(
        "SELECT source_version_id, added_by FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL"
        " AND added_by != 'search' ORDER BY created_at, source_version_id", (research_id,))]
    seed = (scope.get("seed_snapshot") or {}).get("source_version_id")
    if brought or seed:
        by = Counter(row["added_by"] for row in brought)
        items.append(_item(7, "reported",
                           f"{len(brought)} records were brought by the person"
                           + (" and the question was seeded with an attached PDF" if seed else "") + ".",
                           {"brought": dict(sorted(by.items())), "seed_source_version_id": seed},
                           [f"corpus_memberships:{research_id}/{row['source_version_id']}" for row in brought]))
    else:
        items.append(_item(7, "not_recorded", "No other source was recorded in DEIXIS."))

    # 8 — full search strategies.
    approval = body.get("approval") or {}
    if keyword:
        items.append(_item(8, "reported",
                           f"{len(keyword)} keyword query groups are listed verbatim in the search table with their "
                           "provider, origin, round and request parameters.",
                           {"query_groups": len(keyword), "chain_groups": len(chain),
                            "rounds": sorted({g["round"] for g in keyword}),
                            "origins": dict(sorted(Counter(str(g["origin"]) for g in keyword).items())),
                            "approval": {key: approval.get(key) for key in (
                                "mode", "approved_by", "edited", "term_edits", "criterion_edited")},
                            "model_term_suggestions": approval.get("suggestions"),
                            "concept_blocks": body.get("concept_blocks")}, protocol_trace))
    else:
        items.append(_item(8, "not_recorded", "No keyword query was recorded for this question revision.",
                           {}, protocol_trace))

    # 9 — limits: listed, never justified per research.
    read_limits = sorted({g["read_limit"] for g in keyword if g["read_limit"] is not None})
    sorts = sorted({f"{g['provider']}: {g['request']['sort']}" for g in keyword if g["request"].get("sort")})
    filters = sorted({f"{g['provider']}: {g['request']['filter']}" for g in keyword if g["request"].get("filter")})
    items.append(_item(9, "incomplete" if keyword else "not_recorded",
                       "Limits listed; their justification is not recorded." if keyword else
                       "No search limit was recorded for this question revision.",
                       {"read_limit_per_query": read_limits, "sort": sorts, "request_filters": filters,
                        "budget": body.get("budget"),
                        "unread_by_read_limit": sum(g["unread_by_limit"] for g in keyword)}, protocol_trace))

    # 10 — search filters.
    items.append(_item(10, "not_performed",
                       "DEIXIS has no published search filter; the queries are compiled from the approved "
                       "vocabulary.",
                       {"query_compiler": body.get("code_version")},
                       code_source=_code_source("filters", compiler_versions=[
                           query_compiler.VERSION, query_compiler.COMPACT_VERSION, query_compiler.BLOCKS_VERSION])))

    # 11 — prior work.
    items.append(_item(11, "not_recorded", "Adapting a search from earlier work is not recorded in DEIXIS."))

    # 12 — updates.
    earlier = revision - 1
    runs_text = [{"run_id": run["id"], "created_at": run["created_at"]} for run in discovery]
    if len(discovery) > 1:
        status, text = "reported", f"{len(discovery)} discovery runs searched this question revision."
    else:
        status, text = "not_recorded", "No update run was recorded in DEIXIS."
    if earlier > 0:
        status = "incomplete"
        text += f" {earlier} earlier question revisions; their searches are not in this export."
    items.append(_item(12, status, text, {"discovery_runs": runs_text, "earlier_revisions": earlier}))

    # 13 — dates.
    if groups:
        items.append(_item(13, "reported",
                           f"Searches ran from {min(g['first_retrieved_at'] for g in groups)} to "
                           f"{max(g['last_retrieved_at'] for g in groups)}; each group's first and last read is in the "
                           "search table.",
                           {"first": min(g["first_retrieved_at"] for g in groups),
                            "last": max(g["last_retrieved_at"] for g in groups),
                            "protocol_frozen_at": protocols[0]["created_at"] if protocols else None},
                           protocol_trace))
    else:
        items.append(_item(13, "not_recorded", "No search date was recorded for this question revision."))

    # 14 — peer review: the protocol approval is a fact, not a peer review.
    items.append(_item(14, "not_recorded", "Peer review of the search strategy is not recorded in DEIXIS; the "
                                           "protocol approval below is not a peer review.",
                       {"approval": {"approved_by": approval.get("approved_by"), "mode": approval.get("mode"),
                                     "at": latest["created_at"] if latest else None}}, protocol_trace))

    # 15 — total records per group.
    kw, ch = _ended_counts(keyword), _ended_counts(chain)
    incomplete = kw["not_complete"] or ch["not_complete"]
    text = (f"{sum(g['rows_returned'] for g in keyword)} records were returned by {len(keyword)} keyword query groups"
            + (f" and {sum(g['rows_returned'] for g in chain)} by {len(chain)} citation request groups" if chain else "")
            + ".")
    if incomplete:
        text += (f" {kw['not_complete']} keyword groups did not end complete ({kw['nothing_read']} read nothing,"
                 f" {kw['read_then_stopped']} stopped after reading {kw['read_then_stopped_records']} records)")
        text += (f" and {ch['not_complete']} citation groups did not." if chain else ".")
    items.append(_item(15, "incomplete" if incomplete else "reported" if groups else "not_recorded",
                       text if groups else "No search was recorded for this question revision.",
                       {"keyword": kw, "chain": ch,
                        "rows_returned": sum(g["rows_returned"] for g in keyword),
                        "chain_rows_returned": sum(g["rows_returned"] for g in chain),
                        "unread_by_read_limit": sum(g["unread_by_limit"] for g in keyword)}))

    # 16 — deduplication.
    items.append(_dedup(store, research_id, revision, groups))

    ctx = queue._Context(store, research_id)
    flow = flow_rules.flow_counts(ctx, probe_rules.probe_set(ctx))
    return {
        "checklist": CHECKLIST, "citation": CITATION, "generated_at": now(), "code_version": code_version(),
        "research_id": research_id, "scope_revision": revision,
        "protocol_hash": latest["body_sha256"] if latest else None,
        "statement": STATEMENT, "run_in_progress": running, "note": RUNNING_NOTE if running else None,
        "question": scope["question"], "effort": scope["effort"],
        "items": items,
        "search_table": [{key: value for key, value in g.items() if key != "request_description"}
                         | {"request_description": g["request_description"]} for g in groups],
        "flow": {"counts": flow, "boxes": flow_rules.flow_boxes(ctx, flow)},
    }


def _dedup(store: Store, research_id: str, revision: int, groups: list[dict[str, Any]]) -> dict[str, Any]:
    conn = store.conn
    members = conn.execute("SELECT COUNT(*) FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL",
                           (research_id,)).fetchone()[0]
    works = conn.execute(
        "SELECT COUNT(DISTINCT v.work_id) FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (research_id,)).fetchone()[0]
    hits = conn.execute("SELECT COUNT(*) FROM candidate_hits WHERE research_id = ? AND scope_revision = ?",
                        (research_id, revision)).fetchone()[0]
    # A page that returned records and kept no hit row is from before D93: the hits were not counted, which is not 0.
    counted = conn.execute(
        "SELECT 1 FROM search_runs WHERE research_id = ? AND scope_revision = ? AND status = 'completed'"
        " AND result_count > 0 AND id NOT IN (SELECT search_run_id FROM candidate_hits WHERE research_id = ?"
        " AND scope_revision = ?) LIMIT 1", (research_id, revision, research_id, revision)).fetchone() is None
    link_filter = ("closed_at IS NULL AND (source_version_id IN (active members) OR other_source_version_id IN "
                   "(active members))")
    member_sql = ("SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL")
    aggregates = [{"table": "corpus_memberships", "filter": "research_id = <research> AND removed_at IS NULL",
                   "count": members},
                  {"table": "candidate_hits", "filter": "research_id = <research> AND scope_revision = <revision>",
                   "count": hits}]
    for row in conn.execute(
            f"SELECT link_kind, rule, merged, COUNT(*) AS n FROM record_links WHERE closed_at IS NULL AND"
            f" (source_version_id IN ({member_sql}) OR other_source_version_id IN ({member_sql}))"
            " GROUP BY link_kind, rule, merged ORDER BY link_kind, rule, merged", (research_id, research_id)):
        aggregates.append({"table": "record_links",
                           "filter": f"link_kind = {row['link_kind']} AND rule = {row['rule']} AND merged = "
                                     f"{row['merged']} AND {link_filter}", "count": row["n"],
                           "link_kind": row["link_kind"], "rule": row["rule"], "merged": bool(row["merged"])})
    rows_returned = sum(g["rows_returned"] for g in groups)
    text = ("DEIXIS deduplicated the records itself (" + code_version() + "): the same normalised DOI joins records "
            "into one work (D46); a work is headed by its published record, else the first found (D48); without a "
            "DOI, title, authors and abstract together join only a preprint to its published version, and each link "
            "is stored with its rule and source and can be undone (D72). All returned rows, the tracked candidate "
            "versions / hits, the active members and the works are counted apart below; the number of distinct "
            "returned provider records is not recorded (raw responses are kept as files, not counted in a table).")
    return _item(16, "reported", text, {
        "rows_returned": rows_returned,
        # One hit is one version found by one search page: several provider records a query mapped to the same
        # version are one hit, and versions added without becoming a candidate are not here.
        "tracked_candidate_hits": hits if counted else None,
        "tracked_candidate_hits_note": None if counted else "not counted: searched before candidate hits were kept",
        "distinct_returned_provider_records": None,
        "distinct_returned_provider_records_note": "not recorded",
        "active_members": members, "works": works}, aggregates=aggregates)


# ---- Markdown -----------------------------------------------------------------------------------------------------


STATUS_WORDS = {"reported": "Reported", "incomplete": "Incomplete", "not_recorded": "Not recorded"}


def _status_line(item: dict[str, Any]) -> str:
    if item["status"] == "not_performed":
        reason = ("read from the protocol" if item["code_source"] is None
                  else f"read from the code, {item['code_source']['source']}")
        return f"Not performed by DEIXIS ({reason})"
    return STATUS_WORDS[item["status"]]


def _cell(value: Any) -> str:
    return "—" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def markdown(data: dict[str, Any]) -> str:
    """The export as a Markdown document; the same items, statuses and search table as the JSON."""
    lines = [f"# Search report ({data['checklist']} items)", "", data["statement"], ""]
    if data["note"]:
        lines += [f"**{data['note']}**", ""]
    citation = data["citation"]
    lines += [f"- Question: {data['question']}", f"- Research: `{data['research_id']}`, question revision "
              f"{data['scope_revision']}", f"- Protocol digest: `{data['protocol_hash']}`",
              f"- Code: {data['code_version']}", f"- Generated: {data['generated_at']}",
              f"- Checklist: {citation['authors']}. {citation['title']}. {citation['journal']} {citation['year']};"
              f"{citation['volume']}:{citation['article']}. doi:{citation['doi']}", ""]
    for item in data["items"]:
        lines += [f"## {item['number']}. {item['name']}", "", f"**Status:** {_status_line(item)}", "", item["text"], ""]
        if item["values"]:
            lines += ["```json", json.dumps(item["values"], indent=1, sort_keys=True, ensure_ascii=False), "```", ""]
        if item["aggregates"]:
            lines += [f"- {a['table']} where {a['filter']}: {a['count']}" for a in item["aggregates"]] + [""]
        if item["code_source"]:
            source = item["code_source"]
            lines += [f"Code origin: {source['source']} (sha256 {source['sha256']}, "
                      f"{'verified' if source['verified'] else 'not verified'}), fact `{source['fact']}`.", ""]
        if item["trace"]:
            lines += ["Stored rows: " + ", ".join(f"`{entry}`" for entry in item["trace"]), ""]
    lines += ["## Search table", "",
              "| # | Kind | Provider | Origin | Round | Query | Request | First read | Last read | Rows | Provider total "
              "| Unread (limit) | End |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in data["search_table"]:
        request = " ".join(f"{k}={v}" for k, v in g["request"].items() if k not in ("method", "endpoint") and v)
        lines.append(f"| {g['group']} | {g['kind']} | {_cell(g['provider'])}"
                     f"{' via ' + g['through'] if g['through'] else ''} | {_cell(g['origin'])} | {_cell(g['round'])} | "
                     f"{_cell(g['query_text'])} | {_cell(request or None)} | {g['first_retrieved_at']} | "
                     f"{g['last_retrieved_at']} | {g['rows_returned']} | {_cell(g['provider_total'])} | "
                     f"{g['unread_by_limit']} | {g['end_status']} |")
    # Each group's stored pages, in page order, so a reader of the Markdown alone can find every page row the JSON's
    # `search_run_ids` names.
    if data["search_table"]:
        lines += ["", "Stored pages of each group:", ""]
        lines += [f"- Group {g['group']}: " + ", ".join(f"`search_runs:{sid}`" for sid in g["search_run_ids"])
                  for g in data["search_table"]]
    boxes = data["flow"]["boxes"]
    lines += ["", "## Flow counts", "", f"Every count below is marked `{boxes['flow_status']}`: the screening was "
              "done by code and model runs. The counts are not added up.", ""]
    lines += [f"- {box['key']}: {_cell(box['count'])}" for box in boxes["boxes"]]
    return "\n".join(lines) + "\n"

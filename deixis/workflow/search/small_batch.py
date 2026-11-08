"""Frozen fused lists and bounded batches, persisted entirely as existing code steps."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
from typing import Any

from deixis.documents import rerankers
from deixis.domain import canonical
from deixis.domain.reason_codes import reason
from deixis.domain.rules import ABSTRACT_READ_LIMIT, FULLTEXT_RUNS
from deixis.providers.lookup import S2_LOOKUP_BATCH, SCOPUS_LOOKUP_BATCH
from deixis.storage.db import transaction
from deixis.workflow.read import adjudication, fulltext
from deixis.workflow.run import fast_path
from deixis.workflow.search import english_question, preselect, ranking
from deixis.workflow.screen.decisions import DecisionStore

POLICY = "small_batch_fused_v1"
BATCH_SIZE = 40
MINIMUM = 50
LIST_KEY = "small_batch:v1:list"
RERANK_KEY = "rerank:v1:list"  # outside `small_batch:v1:%`, which `steps` reads as batch steps
# The benchmark-only list barrier (the deeper-screening gate); outside `small_batch:v1:%` too.
LIST_BARRIER_KEY = "benchmark:list_barrier"
GRAPH_SEEDS = 30  # Rows with a reference list taken from the top of the fused order
PRERANK_LOOKUP_KEY = "prerank_lookups"
PRERANK_PREFIX = "prerank:"  # the lookup steps of the round before the rerank, apart from the read stage's
# Lookup rule version 2: every record of the reranker's window without an abstract, at most 400 within 8 s, with
# Crossref 4 in flight and requests enough for every source in turn: Semantic Scholar's batches, one Crossref
# request per record, Scopus's
# access check and its OR queries (2 + 400 + 1 + 16 = 419). A budget frozen with the first rule ({"max_records": 20,
# "seconds": 5}, no version) keeps it and the read stage's 200 requests. Hand-picked, not measured.
PRERANK_RECORDS = 400
# Version 3: Semantic Scholar waits out no 429 here, so a refused batch fails at once and Crossref gets the time
# left; its batch holds the whole window (400 of the 500 ids `/paper/batch` takes, one request); and while a 429
# anywhere in the process holds the Semantic Scholar pacer in a cooldown, this round and the read stage's lookups skip
# it and say so. Version 2 budgets keep 200 ids a batch, the effort's waits and no skip.
PRERANK_S2_BATCH = 400
# Version 4: Crossref's single requests go 8 in flight, not 4 (the 8 s round ran out in 4 of 6 version 3 pilot runs),
# and each request stores the records it was sent for, so only a record whose request went out and did not come back
# in time is `lookup_open`; one never sent is settled. The request count is unchanged: one per record either way.
# Version 5: Crossref back to 4 in flight. At 8 the version 4 pilot got no more answers into the 8 s round and three
# times the 429s; version 4 budgets keep 8. Version 5 keeps version 4's rule otherwise.
PRERANK_LOOKUP = {"version": 5, "max_records": PRERANK_RECORDS, "seconds": 8, "crossref_in_flight": 4,
                  "s2_waits": 0, "s2_batch": PRERANK_S2_BATCH, "s2_cooldown_skip": True,
                  "max_requests": (math.ceil(PRERANK_RECORDS / PRERANK_S2_BATCH) + PRERANK_RECORDS + 1
                                   + math.ceil(PRERANK_RECORDS / SCOPUS_LOOKUP_BATCH))}
# Rerank rule version 2: the reranker's window is 8x what a run reads (400 at Standard, under
# rerankers.MAX_CANDIDATES), and a record of it still without an abstract keeps its fused place. A budget frozen
# without `rerank` keeps version 1.
# Version 3: it keeps its place only with a route to text (an open PDF on a version of its work, or a file
# stored for it) or while its lookup before the rerank did not settle; otherwise the reranker scores its title, as
# under version 1. A version 2 rule holds every such record. Which lookups did not settle is the lookup rule's:
# `unsettled` under its version 3, `lookup_open` since version 4.
# Version 4: a record only citation chaining brought is sent to the reranker like any other (`hold_chained`
# False), and the lookup before the rerank asks about it too; the no-abstract hold applies to it as to every record.
# Replaying the 18 Oct BioASQ and LitSearch runs offline, that hold cost recall@50 (-3.5 and -3.3 points); its own
# check had used mislabelled routes. A rule without `hold_chained` (version 3 and earlier) keeps the hold.
# Version 5: when the pool is larger than the window, which records enter it is decided by the query lists
# themselves (`preselect`) instead of by the first records of the fused order — one vote per relevance-ordered query
# list, `1 / (k + rank)` summed. A pool that fits the window is untouched. Citation links cast no vote, so the window
# keeps a floor for the records only citation chaining found and for the records only a focused query found. The
# floor sizes are frozen per run; nothing has measured them yet, so they are the pilot's own starting numbers.
# A rule frozen without `preselect` (version 4 and earlier) takes the fused prefix, as it did.
RERANK_RULE = {"version": 5, "pool_factor": 8.0, "max_pool_factor": 8.0, "hold_without_abstract": "with_text_route",
               "hold_chained": False, "preselect": preselect.RULE, "rrf_k": preselect.K,
               "floors": {"chain_only": 5, "narrow_only": 5}}
RERANK_RULE_V1 = {"version": 1, "pool_factor": 4.0, "max_pool_factor": 4.0, "hold_without_abstract": False}
# 5: one closest place for a work whose reading found no criterion part. 6: every abstract-only work's abstract
# before the closest works' second to fourth pages, and that zero-part work at most 2 passages.
ANSWER_ALLOCATION_VERSION = 6


def steps(store: Any, run_id: str) -> list[dict[str, Any]]:
    """Internal batch outputs, separate from Store.run_steps' deliberately abbreviated API view."""
    rows = store.run_steps(run_id)
    outputs = {row["id"]: json.loads(row["output_json"]) if row["output_json"] else None
               for row in store.conn.execute(
                   "SELECT id, output_json FROM run_steps WHERE run_id = ?"
                   " AND operation_key LIKE 'small_batch:v1:%' AND operation_key != ?", (run_id, LIST_KEY))}
    return [row | {"output": outputs.get(row["id"], row["output"])} for row in rows]


def enabled(budget: dict[str, Any]) -> bool:
    return (budget.get("inspection") or {}).get("policy") == POLICY


def answer_budget(store: Any, rid: str, revision: int, budget: dict[str, Any]) -> dict[str, Any]:
    """Bind a new answer to the latest completed discovery, without switching an older run's policy."""
    scope = store.scope(rid, revision)
    if scope.get("source_scope") == "attached":
        return budget
    row = store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
        " AND status = 'completed' ORDER BY created_at DESC, id DESC LIMIT 1", (rid, revision)).fetchone()
    if row is None:
        if scope.get("source_scope") == "academic":
            from deixis.workflow.run.store import LegacyInspectionPolicyRemoved
            raise LegacyInspectionPolicyRemoved("legacy_inspection_policy_removed")
        return budget
    step = store.existing_step(row["id"], LIST_KEY)
    if step is None or step["status"] != "succeeded":
        return budget | {"inspection": {"policy": POLICY, "list_run_id": row["id"],
                                        "answer_allocation_version": ANSWER_ALLOCATION_VERSION,
                                        "binding_error": "answer_frozen_list_missing"}}
    return budget | {"inspection": {"policy": POLICY, "list_run_id": row["id"],
                                    "answer_allocation_version": ANSWER_ALLOCATION_VERSION,
                                    "manifest_hash": step["output"]["manifest_hash"]}}


def allocate(queues: list[list[dict[str, Any]]], limit: int, per_source: int,
             breadth: int | None = None) -> list[dict[str, Any]]:
    """Represent the bounded breadth prefix, fill its depth, then widen with unused room."""
    selected = []
    if limit <= 0 or per_source <= 0:
        return selected
    prefix_size = max(1, limit // 2) if breadth is None else min(limit, max(1, breadth))
    prefix = queues[:prefix_size]
    for depth in range(per_source):
        for queue in prefix:
            if len(selected) >= limit:
                return selected
            if depth < len(queue):
                selected.append(queue[depth])
    for queue in queues[prefix_size:]:
        if len(selected) >= limit:
            break
        if queue:
            selected.append(queue[0])
    return selected


def freeze_budget(budget: dict[str, Any], effort: str, reading: str) -> dict[str, Any]:
    body = dict(budget)
    mode = fast_path.MODES[effort]
    fetch = body.get("fulltext_fetch") or {}
    reads = adjudication.read_budget(effort) if reading == "auto" and fetch else {}
    # The former follow-up reading allowance moves into this run, without increasing the chain's total.
    body["max_model_calls"] += reads.get("max_model_calls", 0)
    body["max_fulltext_reads"] = reads.get("max_fulltext_reads", 0)
    if reads.get("read_rule"):
        # The reads this run adds keep the read rule they were frozen with.
        body["read_rule"] = reads["read_rule"]
    body["inspection"] = {
        "policy": POLICY, "runner_version": 4, "batch_size": BATCH_SIZE, "minimum_processed_works": MINIMUM,
        "discovery_model_calls": budget["max_model_calls"],
        "abstract_limit": ABSTRACT_READ_LIMIT[effort],
        "fetch_limit": fetch.get("max_fulltext_works", 0) + fetch.get("chain_room", 0),
        "read_limit": body["max_fulltext_reads"], "max_model_calls": body["max_model_calls"],
        "fetch_attempts": fulltext.FULLTEXT_WORK_ATTEMPTS,
        "prerank_lookup": dict(PRERANK_LOOKUP),
        # This depth's own reranker window and run point (`fast_path.MODES`): Quick reads a small group after its
        # list is frozen, Standard and Detailed read the widest window before it. A factor the person saved is kept
        # under the depth's own, so a run never reads a wider window than its depth allows.
        "rerank": dict(RERANK_RULE) | {
            "pool_factor": min(RERANK_RULE["pool_factor"], mode.rerank_pool),
            "max_pool_factor": min(RERANK_RULE["max_pool_factor"], mode.rerank_pool),
            "point": mode.rerank_point},
    }
    return body


def rerank_rule(run: dict[str, Any]) -> dict[str, Any]:
    """The rerank rule this run froze, or version 1 for a budget frozen without it."""
    return (run["budget"].get("inspection") or {}).get("rerank") or RERANK_RULE_V1


def rerank_point(run: dict[str, Any]) -> str:
    """Where this run's reranker stands: `before_list`, the list waiting for it, or `after_list`, the list frozen
    from the fused order first and the reranker reading a small group afterwards for the measurement (Quick). A
    budget frozen before the depths had a point of their own waits, as it did."""
    return rerank_rule(run).get("point", "before_list")


def held_chained(run: dict[str, Any], manifest: dict[str, Any]) -> set[str]:
    """The records only citation chaining brought that keep their fused place: all of them under a rule without
    `hold_chained` (the reranker pushed them down on the EE survey benchmark, 18 Oct), none since version 4."""
    return set(manifest.get("chain_heads") or ()) if rerank_rule(run).get("hold_chained", True) else set()


def rerank_choice(store: Any, run: dict[str, Any]) -> rerankers.Choice | None:
    """The reranker turned on in Settings, with the window factor this run reads (rerank rule version 2).

    A factor the person saved is kept, never above what the run's rule allows; with none saved the rule's own factor
    applies, so a budget frozen with version 1 keeps 4x and a newer one takes 8x."""
    saved = store.setting(rerankers.SETTING)
    choice = rerankers.chosen(saved)
    if choice is None:
        return None
    rule = rerank_rule(run)
    factor = rerankers.setting_in_force(saved).get("pool_factor")
    return dataclasses.replace(choice, pool_factor=min(float(factor) if factor else rule["pool_factor"],
                                                       rule["max_pool_factor"]))


def model_call_allowance(budget: dict[str, Any]) -> int:
    """Model context keeps discovery's allowance; execution counts against the combined allowance."""
    if not enabled(budget):
        return budget["max_model_calls"]
    # Older frozen budgets did not record the discovery allowance separately.
    return budget["inspection"].get("discovery_model_calls",
                                    budget["max_model_calls"] - FULLTEXT_RUNS * budget.get("max_fulltext_reads", 0))


def json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [json_value(item) for item in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def replay(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compute the fused order C exclusively from the stored ranking input."""
    def row(stored: dict[str, Any]) -> dict[str, Any]:
        return stored | {"own_ids": set(stored["own_ids"]),
                         "references": set(stored["references"]) if stored["references"] is not None else None}
    pool, verified = [row(r) for r in manifest["pool"]], [row(r) for r in manifest["verified"]]
    # A manifest without `graph_rule` was frozen before seeds guided the graph signal, or by an unseeded run.
    rule = manifest.get("graph_rule", "sum_v1")
    ranked = ranking.rank_pool(pool, verified,
                             set(manifest["query_words"]), manifest["blocks"], manifest["embedding_model"],
                             manifest["similarities"], manifest["off_reason"], manifest["compared_terms"], rule)
    version = manifest.get("ranking_version", 1)
    top = ranked["fused"][:20]
    if version == 3:
        # A second graph pass seeded from the fused top instead of the keyword top, counting a seed's
        # citation of a record twice; the whole pool is fused again before the version 2 reorder below.
        verified_works = {r["work_id"] for r in verified}
        by_id = {r["id"]: r for r in pool}
        seeds = verified + [by_id[rid] for rid in ranked["fused"]
                            if by_id[rid]["references"] and by_id[rid]["work_id"] not in verified_works][:GRAPH_SEEDS]
        pdfs = [r for r in verified if r.get("seed_pdf")] if rule == "seed_max_v2" else []
        if pdfs:
            # Under `seed_max_v2` the seed PDFs follow the other seeds and count by the nearest one, and a seed
            # PDF's OpenAlex copy (another work, the same identity) is never a second, summed seed.
            seeds = [r for r in verified if not r.get("seed_pdf")] + [
                by_id[rid] for rid in ranked["fused"] if by_id[rid]["references"]
                and by_id[rid]["work_id"] not in verified_works
                and not any(ranking.same_work(seed, by_id[rid]) for seed in verified)][:GRAPH_SEEDS] + pdfs
        if any(seed["references"] for seed in seeds):
            if pdfs:
                graph = ranking.graph_scores_v2(pool, seeds[:len(seeds) - len(pdfs)], pdfs, cited_twice=True)
            else:
                graph = ranking.graph_scores(pool, seeds)
                for r in pool:
                    graph[r["id"]] += sum(bool(r["own_ids"] & (seed["references"] or set()))
                                          for seed in seeds if seed["work_id"] != r["work_id"])
            ranked["ranks"]["graph"] = ranking.mean_ranks(graph, ranking.availability(pool, "graph"))
            ranked["reasons"].pop("graph", None)
            ranked["graph_seeds"] = seeds
            ranked["fused_code"] = ranking.fuse(ranked["ranks"], ranking.CODE_SIGNALS)
            ranked["fused"] = ranking.fuse(ranked["ranks"], ranking.SIGNALS)
    if version in (2, 3):
        from deixis.workflow.run.flow import RRF_K

        counts = {r["id"]: r["cited_by_count"] for r in manifest["pool"]}
        ranked["ranks"]["cites"] = ranking.mean_ranks(
            {rid: math.log1p(count) if count is not None else float("-inf")
             for rid, count in counts.items()},
            {rid: count is not None for rid, count in counts.items()})
        # Ranks cover the whole pool; the gate restricts movement, not signal computation.
        base = ranked["fused"]
        scores = {rid: sum((2 if name in ("graph", "cites") else 1) / (RRF_K + ranks[rid][0])
                           for name, ranks in ranked["ranks"].items()) for rid in base[20:500]}
        ranked["fused"] = base[:20] + sorted(scores, key=lambda rid: (-scores[rid], rid)) + base[500:]
        if version == 3:
            # The original fused top 20 stays first, so P@20 is unchanged by construction.
            ranked["fused"] = top + [rid for rid in ranked["fused"] if rid not in set(top)]
        ranked["order"] = list(ranked["fused"])
    return ranked


def build_list(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = json_value(manifest)
    ranked = replay(manifest)
    by_head = {r["id"]: r for r in manifest["pool"] + manifest.get("priority_pool", [])}
    priority = manifest["user_priority"]
    automatic, reranker = reranked(manifest, ranked["fused"])
    order = list(dict.fromkeys(priority + automatic))
    versions = manifest["versions"]
    by_work: dict[str, list[str]] = {}
    for svid, row in versions.items():
        by_work.setdefault(row["work_id"], []).append(svid)
    items = [{"position": i + 1, "work_id": by_head[head]["work_id"], "head": head,
              "user_priority": head in priority,
              "versions": sorted(by_work.get(by_head[head]["work_id"], []))}
             for i, head in enumerate(order)]
    return {"policy": POLICY, "manifest": manifest, "manifest_hash": canonical.sha256_hex(manifest),
            "order": order, "order_hash": canonical.sha256_hex(order), "automatic_order": ranked["fused"],
            "items": items, "ranks": json_value(ranked["ranks"]), "signal_reasons": ranked["reasons"],
            **({"reranker": reranker} if reranker else {})}


def reranked(manifest: dict[str, Any], fused: list[str]) -> tuple[list[str], dict[str, Any] | None]:
    """The automatic order after the stored rerank, and what was done; the fused order itself when there was none.

    The rerank only reorders the records it scored, among their own places in the fused order. It applies only when
    the records it scored, with the records it kept in place (`kept_in_place`), are still the first records of that order
    that the person did not include themselves; when
    the list moved since (a selection changed while the reranker ran) or the reranker failed, the fused order stands
    and the listing says why. Everything here is read from the manifest, so the list replays exactly."""
    stored = manifest.get("reranker")
    if not stored:
        return fused, None
    told = {key: stored.get(key) for key in ("provider", "model", "status", "error_code")}
    if stored.get("point") == "after_list":
        # The list was frozen before this reranker read anything (Quick): its scores are the measurement's record
        # and never move a record, whatever the list is rebuilt from.
        return fused, told | {"applied": False, "reason": "read_after_list", "fallback": "fused_order"}
    if stored.get("status") != "applied":
        return fused, told | {"applied": False, "reason": stored.get("error_code") or stored.get("status"),
                              "fallback": "fused_order"}
    candidates, kept = stored["candidate_ids"], stored.get("kept_in_place") or []
    priority = set(manifest["user_priority"])
    automatic = [rid for rid in fused if rid not in priority]
    size = len(candidates) + len(kept)
    if manifest.get("preselect"):
        # The window is the one the query lists choose, not the first records of the fused order, so it is
        # recomputed from the manifest and compared as a set. Its records then take the window's own places, in
        # front of the records the reranker never read, as they did when the window was the fused order's own head.
        window = window_for(manifest, automatic, size)["window"]
        if set(window) != set(candidates) | set(kept) or len(window) != size:
            return fused, told | {"applied": False, "reason": "candidates_changed", "fallback": "fused_order"}
        return rerankers.reorder(promoted(fused, window), candidates, stored["scores"]), told | {
            "applied": True, "reranked": len(candidates), **({"kept_in_place": len(kept)} if kept else {})}
    window = automatic[:size]
    if [rid for rid in window if rid not in set(kept)] != candidates or not set(kept) <= set(window):
        return fused, told | {"applied": False, "reason": "candidates_changed", "fallback": "fused_order"}
    return rerankers.reorder(fused, candidates, stored["scores"]), told | {
        "applied": True, "reranked": len(candidates), **({"kept_in_place": len(kept)} if kept else {})}


def next_batch(listing: dict[str, Any], number: int, size: int = BATCH_SIZE) -> dict[str, Any]:
    items = listing["items"][number * size:(number + 1) * size]
    body = {"number": number, "manifest_hash": listing["manifest_hash"], "order_hash": listing["order_hash"],
            "items": items, "work_ids": [item["work_id"] for item in items],
            "order": [item["head"] for item in items]}
    return body | {"hash": canonical.sha256_hex(body)}


def work_state(item: dict[str, Any], work: dict[str, Any] | None) -> dict[str, Any]:
    base = {"work_id": item["work_id"], "position": item["position"], "head": item["head"],
            "user_priority": item["user_priority"], "processed": False, "fulltext_adjudicated": False,
            "included": False, "status": "blocked", "stage": None, "next_action": None, "blocker": None}
    if work is None:
        return base | {"blocker": "source_changed"}
    selection = work.get("selection") or {}
    if selection.get("origin") == "user" and selection.get("state") in ("included", "excluded"):
        return base | {"status": "processed", "processed": True, "stage": "user_selection",
                       "included": selection["state"] == "included"}
    ft = fulltext.current_fulltext(work)
    fresh_outcomes = {reason(v["fulltext"]["reason_code"]).outcome for v in work["versions"]
                      if v.get("fulltext") and not v["fulltext"].get("stale")}
    if {"include", "criterion_not_met"} <= fresh_outcomes:
        return base | {"blocker": "human_pending", "stage": "fulltext", "reason_code": "versions_disagree"}
    abstract = fulltext.abstract_outcome(work)
    decision = ft or (abstract if abstract and not abstract.get("stale") else None)
    if decision is None:
        return base | {"blocker": "abstract_not_read", "stage": "abstract", "next_action": "abstract_screening"}
    code = decision["reason_code"]
    entry = reason(code)
    read = bool(ft and code in adjudication.FRESH_MODEL_CODES and code != "pdf_identity_unconfirmed")
    state = base | {"stage": "fulltext" if ft else "abstract", "reason_code": code,
                    "next_action": entry.next_step, "fulltext_adjudicated": read}
    if decision.get("decided_by") == "human":
        if entry.outcome in ("include", "criterion_not_met"):
            return state | {"status": "processed", "processed": True, "included": entry.outcome == "include"}
        return state | {"blocker": "human_pending"}
    if entry.next_step == "human_queue" or code == "versions_disagree":
        return state | {"blocker": "human_pending"}
    if (ft and code in adjudication.FRESH_MODEL_CODES) or (ft and code in ("no_fulltext", "text_unreadable")):
        return state | {"status": "processed", "processed": True,
                        "fulltext_adjudicated": read,
                        "included": entry.outcome == "include"}
    if not ft and entry.outcome == "out_of_scope":
        return state | {"status": "processed", "processed": True}
    if entry.next_step == "seed_pool":
        # A code rule set the work aside (the survey-title rule); no budget cut it.
        return state | {"blocker": "code_decided"}
    return state | {"blocker": code if code in ("abstract_not_read", "abstract_not_proposed") else "budget_deferred"}


def progress_view(listing: dict[str, Any], steps: list[dict[str, Any]], works: list[dict[str, Any]]) -> dict[str, Any]:
    """Read model: decisions may have changed since an immutable batch closure was recorded."""
    by_work = {work["work_id"]: work for work in works}
    closures = [step for step in steps if step["kind"] == "code:small_batch_close" and step["status"] == "succeeded"]
    active = {wid for step in steps if step["kind"] == "code:small_batch_plan"
              for wid in (step.get("output") or {}).get("work_ids", [])}
    items = [work_state(item, by_work.get(item["work_id"])) if item["work_id"] in active else
             {"work_id": item["work_id"], "head": item["head"], "position": item["position"],
              "user_priority": item["user_priority"], "status": "pending", "processed": False,
              "fulltext_adjudicated": False, "included": False, "stage": None, "next_action": "batch_plan",
              "blocker": None} for item in listing["items"]]
    claims = {step["operation_key"].removeprefix("fulltext_work:"): step for step in steps
              if step["kind"] == "code:fulltext_work"}
    deferred = {item["work_id"] for step in steps if step["kind"] == "code:small_batch_deferred"
                and step["status"] == "succeeded" for item in step["output"]["items"]}
    for item in items:
        if item["work_id"] in deferred:
            item.update(status="blocked", blocker="budget_deferred", next_action=None)
        claim = claims.get(item["work_id"])
        if claim and item["blocker"] in ("budget_deferred", "abstract_not_read", "abstract_not_proposed"):
            if claim["status"] in ("failed", "outcome_unknown"):
                item["blocker"] = claim["error_code"] or claim["status"]
                item["stage"] = "fulltext_fetch"
                item["step_status"] = claim["status"]
                item["requests_unanswered"] = (claim.get("output") or {}).get("requests_unanswered")
    counts = {name: sum(bool(item.get(name)) for item in items)
              for name in ("processed", "fulltext_adjudicated", "included")}
    counts |= {name: sum(item["status"] == name for item in items) for name in ("blocked", "pending")}
    return {"policy": POLICY, "manifest_hash": listing["manifest_hash"], "order_hash": listing["order_hash"],
            "batches_closed": len(closures), "items": items, "counts": counts,
            "minimum_processed_works": MINIMUM, "minimum_reached": counts["processed"] >= MINIMUM,
            "reason": None if counts["processed"] >= MINIMUM else "minimum_not_reached",
            "user_priority_count": sum(item["user_priority"] for item in items)}


def save_code(flow: Any, run: dict[str, Any], key: str, kind: str, build: Any) -> dict[str, Any]:
    # Check before BEGIN: a stop persists its own state and must not be rolled back with this publication.
    flow._checkpoint(run["id"], run["scope_revision"] if run["kind"] == "discovery" else None)
    step = flow.store.step(run["id"], key, kind)
    if step["status"] == "succeeded":
        return step["output"]
    # No await or external operation inside the publication transaction.
    with transaction(flow.store.conn):
        output = build()
        flow.store.start_step(step["id"])
        flow.store.finish_step(step["id"], "succeeded", output=output)
    return output


def manifest_for(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    """Everything the list is computed from, read from the store now (before any stored rerank is added)."""
    store, rid = flow.store, run["research_id"]
    versions, by_work, keyword = ranking.pool_rows(store, rid, run["scope_revision"])
    chained = flow._chain_filter(run)
    heads = store.work_heads(rid)
    pool = {row["work_id"]: row for row in keyword}
    for head in chained:
        if head in versions:
            wid = versions[head]["work_id"]
            pool[wid] = ranking._work_row(heads[wid], by_work[wid])
    user_selected = {row[0] for row in store.conn.execute(
        "SELECT source_version_id FROM selections WHERE research_id = ? AND origin = 'user' AND state = 'included'",
        (rid,))}
    priority = sorted({heads[wid] for wid in store.work_ids(list(user_selected)).values() if wid in heads})
    priority_pool = [ranking._work_row(head, by_work[versions[head]["work_id"]]) for head in priority]
    in_pool = {row["id"]: row for row in pool.values()}
    verified = ranking.seed_rows(store, run, scope, versions, in_pool)
    query, blocks = ranking.query_vocabulary(scope, vocabulary)
    keyword_step = store.existing_step(run["id"], "ranking")
    keyword_output = keyword_step["output"]
    model = keyword_output.get("embedding_model")
    off = (keyword_output.get("signals", {}).get("embedding") or {}).get("reason")
    counts = {row["work_id"]: row["cited_by_count"] for row in store.conn.execute(
        "SELECT work_id, MAX(cited_by_count) AS cited_by_count FROM source_versions"
        " WHERE work_id IN (SELECT v.work_id FROM corpus_memberships m"
        " JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL) GROUP BY work_id", (rid,))}
    for row in list(pool.values()) + priority_pool + verified:
        row["cited_by_count"] = counts.get(row["work_id"])
    from deixis.workflow.search.search import graph_rule
    rule = graph_rule(store, run)
    manifest = {"ranking_version": 3, **({"graph_rule": rule} if rule != "sum_v1" else {}),
                "scope_revision": run["scope_revision"], "selection_revision": store.selection_revision(rid),
                "protocol": store.existing_step(run["id"], "protocol")["output"],
                "pool": sorted(pool.values(), key=lambda row: row["id"]), "priority_pool": priority_pool,
                "versions": versions,
                "verified": verified, "query_words": query, "blocks": blocks, "embedding_model": model,
                "similarities": fast_path.ranking_similarities(store, run, model) if model else {},
                "off_reason": off, "compared_terms": ranking.joint_terms(store, scope, vocabulary),
                "user_priority": list(dict.fromkeys(priority)),
                "provenance": store.candidates(rid, run["scope_revision"]),
                "chain_steps": [s["id"] for s in store.run_steps(run["id"])
                                if s["operation_key"].startswith("chain")],
                "keyword_heads": DecisionStore(store).ranking_order(keyword_step["id"]),
                "chain_heads": chained,
                "keyword_step": keyword_step["id"]}
    rule = rerank_rule(run)
    if rule.get("preselect"):
        # What the query lists themselves say, frozen here: the places every list gave the pool's records, and the
        # rule the window is chosen with. A run whose rule names no preselect freezes neither, so its list is the
        # one it always was, hash included.
        manifest["query_lists"] = query_lists(store, run, in_pool, versions, heads)
        manifest["preselect"] = {"rule": rule["preselect"], "k": rule["rrf_k"], "floors": dict(rule["floors"])}
    from deixis.workflow.search.fast_chain import manifest as chain_manifest
    manifest["fast_path"] = chain_manifest(store, run)
    return manifest


def query_lists(store: Any, run: dict[str, Any], in_pool: dict[str, Any], versions: dict[str, Any],
                heads: dict[str, str]) -> list[dict[str, Any]]:
    """The query lists of this question revision, as `preselect.lists` groups them, each with its sorting setting,
    whether that setting is a relevance order (only then does the list vote) and how deep it was read.

    Every search that found a candidate wrote its own hit with the place it gave the record (`candidate_hits`), so
    membership and order both come from there. Only a provider search counts: a citation request is no query list
    (its step kind is `provider_chain:…`), and a record's place is read against its work's head, because the pool is
    by work. Every discovery run of the revision is read, so the same query sent again by a later run is the same
    list and votes once.

    A focused query is marked, so the window can tell a record only that query found. The roles are read from the
    search plan each of those runs froze, not only this run's: a query of an earlier run keeps the role it was
    written with, and a run whose protocol holds no plan marks none.
    """
    from deixis.providers import registry
    from deixis.workflow.search import search as fast_search

    rows = [dict(row) for row in store.conn.execute(
        "SELECT h.source_version_id, h.rank, sr.run_id, sr.provider, sr.query_text, sr.sort, sr.read_total"
        " FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
        " JOIN run_steps s ON s.id = sr.step_id"
        " WHERE h.research_id = ? AND h.scope_revision = ? AND s.kind LIKE 'provider_search:%'"
        " AND sr.run_id IN (SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery')",
        (run["research_id"], run["scope_revision"], run["research_id"], run["scope_revision"]))]
    focused: set[tuple[str, str]] = set()
    for run_id in sorted({row["run_id"] for row in rows}):
        try:
            plan = fast_search.stored_plan(store, {"id": run_id, "research_id": run["research_id"]})
        except (LookupError, KeyError, TypeError):
            continue
        for entry in plan.get("keywords") or []:
            query = entry.get("query") or {}
            if query.get("role") == "focused":
                focused.add((query["provider_id"], query["query_text"]))
    hits = []
    for row in rows:
        work = (versions.get(row["source_version_id"]) or {}).get("work_id")
        head = heads.get(work)
        if head in in_pool:
            hits.append({"head": head, "provider": row["provider"], "query_text": row["query_text"],
                         "sort": row["sort"], "relevance": registry.relevance_ordered(row["sort"]),
                         "read_total": row["read_total"], "rank": row["rank"]})
    return [entry | {"focused": (entry["provider"], entry["query_text"]) in focused}
            for entry in preselect.lists(hits)]


def window_for(manifest: dict[str, Any], automatic: list[str], size: int) -> dict[str, Any]:
    """The records the reranker is given: all of `automatic` while it fits the window, else what the manifest's own
    query lists choose (rerank rule version 5), else — for a manifest frozen without them — the fused order's own
    leading records. `automatic` already leaves out what the person included themselves.
    """
    rule = manifest.get("preselect")
    if len(automatic) <= size:
        return {"window": list(automatic), "floors": {}}
    if not rule:
        return {"window": automatic[:size], "floors": {}}
    entries = manifest.get("query_lists") or []
    contributions = preselect.scores(entries, rule["k"])
    works = {row["id"]: row["work_id"] for row in manifest["pool"]}
    place = {head: i for i, head in enumerate(automatic)}
    # Inside a floor the records are taken in the run's own fused order, so the floor goes to the best placed of
    # them. A chain record a list voted for needs no floor place: its vote is its way in.
    chain_only = sorted((head for head in manifest.get("chain_heads") or []
                         if head in place and head not in contributions), key=lambda head: place[head])
    narrow_only = sorted((head for head in preselect.narrow_heads(entries) if head in place),
                         key=lambda head: place[head])
    # Only the records `automatic` holds: a record the person included themselves is already first in the list and
    # takes no window place, however the lists voted for it.
    voted = [head for head in preselect.order(contributions, works) if head in place]
    chosen = preselect.window(size, automatic, voted,
                              chain_only=chain_only, narrow_only=narrow_only, quota=rule["floors"])
    return chosen | {"contributions": contributions}


def promoted(fused: list[str], window: list[str]) -> list[str]:
    """`fused` with the window's records in front, each keeping its place among them, and everything else after.

    The reranker's answer is the reading order of what it read, as it was when the window was the fused order's own
    leading records; a record it never saw comes after them. The records the person included themselves are deduped
    back to the front by `build_list`.
    """
    inside = set(window)
    return [rid for rid in fused if rid in inside] + [rid for rid in fused if rid not in inside]


def freeze_list(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        manifest = manifest_for(flow, run, scope, vocabulary)
        step = flow.store.existing_step(run["id"], RERANK_KEY)
        if step is not None and step["status"] in ("succeeded", "failed"):
            output = step["output"] or {}
            manifest["reranker"] = {key: output.get(key) for key in (
                "status", "provider", "model", "candidate_ids", "scores", "error_code")}
            if output.get("kept_in_place"):  # a step without it (an older rule, or none kept) adds nothing
                manifest["reranker"]["kept_in_place"] = output["kept_in_place"]
            if output.get("kept_reasons"):  # why each was kept; a step under rerank rule version 1 has none
                manifest["reranker"]["kept_reasons"] = output["kept_reasons"]
        return build_list(manifest)
    return save_code(flow, run, LIST_KEY, "code:small_batch_list", build)


def user_signature(store: Any, rid: str) -> str:
    return canonical.sha256_hex({
        "selections": [list(row) for row in store.conn.execute(
            "SELECT source_version_id, state, updated_at FROM selections WHERE research_id = ? AND origin = 'user'"
            " ORDER BY source_version_id", (rid,))],
        "decisions": [row[0] for row in store.conn.execute(
            "SELECT id FROM stage_decisions WHERE research_id = ? AND decided_by = 'human' AND superseded_at IS NULL"
            " ORDER BY id", (rid,))]})


def guard_reason(store: Any, guard: dict[str, Any]) -> str | None:
    # A guard without a user signature (the discovery read) does not stop for a person's decision.
    signatures = guard.get("user_signatures", {"batch": guard["user_signature"]} if "user_signature" in guard else {})
    if signatures and any(user_signature(store, guard["rid"]) != signature for signature in signatures.values()):
        return "selection_changed"
    if "versions" in guard:
        current = ranking._versions(store, guard["rid"])
        if any(svid not in current or any(current[svid].get(field) != expected.get(field)
                                         for field in ("work_id", "title", "abstract", "doi", "version_label"))
               for svid, expected in guard["versions"].items()):
            return "source_changed"
    return None


def unchanged_heads(store: Any, rid: str, listing: dict[str, Any], items: list[dict[str, Any]],
                    *, versions: dict[str, Any] | None = None) -> list[str]:
    frozen = versions if versions is not None else listing["manifest"]["versions"]
    current = ranking._versions(store, rid)
    heads = store.work_heads(rid)
    return [item["head"] for item in items if heads.get(item["work_id"]) == item["head"]
            and all(svid in current and all(current[svid].get(field) == frozen[svid].get(field)
                                           for field in ("work_id", "title", "abstract", "doi", "version_label"))
                    for svid in item["versions"])]


def abstract_reusable(store: Any, held: dict[str, Any], candidate_id: str, record: dict[str, Any],
                      max_chars: int) -> bool:
    """A fresh abstract decision can be reused only when both stored readings saw this source text."""
    step = store.conn.execute("SELECT run_id, operation_key FROM run_steps WHERE id = ?", (held.get("step_id"),)).fetchone()
    if step is None:
        return False
    prefix, _, read = step["operation_key"].rpartition(":")
    if read != "2":
        return False
    source = store.source(record["id"])
    for number in (1, 2):
        row = store.conn.execute(
            "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " WHERE s.run_id = ? AND s.operation_key = ? ORDER BY i.attempt DESC LIMIT 1",
            (step["run_id"], f"{prefix}:{number}")).fetchone()
        if row is None:
            return False
        sent = next((c for c in json.loads(row[0])["candidates"] if c["candidate_id"] == candidate_id), None)
        if sent is None or sent["title"] != record["title"] or sent["abstract"] != (record["abstract"] or "")[:max_chars]:
            return False
        if sent["identifiers"].get("doi") != record.get("doi"):
            return False
        if any(sent.get(field) != source.get(field) for field in ("year", "venue")):
            return False
    return True


def stored_progress(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    step = store.existing_step(run["id"], LIST_KEY)
    if not step or step["status"] != "succeeded":
        return None
    rid = run["research_id"]
    stale_key = DecisionStore(store).staleness_key(rid)
    decisions = {(row["source_version_id"], row["stage"]): dict(row) for row in store.conn.execute(
        "SELECT * FROM stage_decisions WHERE research_id = ? AND superseded_at IS NULL", (rid,))}
    selections = {row["source_version_id"]: dict(row) for row in store.conn.execute(
        "SELECT source_version_id, state, origin FROM selections WHERE research_id = ?", (rid,))}
    versions: dict[str, list[dict[str, Any]]] = {}
    for svid, wid in store.work_ids(list(selections)).items():
        fields = {}
        for stage in ("abstract", "fulltext"):
            held = decisions.get((svid, stage))
            fields[stage] = held | {"stale": DecisionStore(store).is_stale(held, stale_key)} if held else None
        versions.setdefault(wid, []).append({"id": svid, **fields})
    works = [{"work_id": wid, "head": head, "selection": selections.get(head), "versions": versions.get(wid, [])}
             for wid, head in store.work_heads(rid).items()]
    valid = set(unchanged_heads(store, rid, step["output"], step["output"]["items"]))
    works = [work for work in works if work["head"] in valid]
    return progress_view(step["output"], steps(store, run["id"]), works) | {
        "operation_blocker": run.get("pause_reason") if run["status"] in ("paused", "failed", "cancelled") else None}


async def rerank_list(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> None:
    """Score the first records of the fused order with the reranker turned on in Settings, before the list freezes.

    The candidates are the first records of the automatic (fused) order that the person did not include themselves,
    as many as the run reads (its N) times the setting's pool factor, so the reranker decides which records fall above
    the read cutoff, not only their order within it; each is sent as its title and abstract with the question. A
    record of that window that only citation chaining brought (`chain_heads`) is sent like any other since version 4; under
    a rule frozen before it (version 3 and earlier) it is not sent and keeps its place. Under a rule since
    version 2, a record still without an abstract after the lookup before the rerank keeps its place too (since
    version 3 only one with a route to text or an unsettled lookup, `text_routes`), and `kept_reasons` says which
    rule kept each. The scores are stored in this step and read into the list's manifest.
    A reranker that fails, answers wrongly, runs out of time (its own limit, or what is left of the ranking stage)
    never hands over to another reranker: the step is `failed`, says why, and the list keeps the
    fused order. A pause or a cancellation stops the request (the built-in runner is killed) and the run stops. A rerank
    that ended, either way, is not asked again on resume."""
    store = flow.store
    step = store.existing_step(run["id"], RERANK_KEY)
    if step is not None and step["status"] in ("succeeded", "failed"):
        return
    choice = rerank_choice(store, run)
    if choice is None:
        return
    flow._checkpoint(run["id"], run["scope_revision"])
    manifest = json_value(manifest_for(flow, run, scope, vocabulary))
    priority = set(manifest["user_priority"])
    read_top = run["budget"]["fast_path"]["N"]
    told = {"point": rerank_point(run)}
    automatic = [rid for rid in replay(manifest)["fused"] if rid not in priority]
    size = choice.pool_size(read_top)
    # Which records enter the window: the fused prefix, or — since rerank rule version 5, and only while the pool is
    # larger than the window — what the query lists themselves choose.
    chosen = window_for(manifest, automatic, size)
    window = chosen["window"]
    rows = {row["id"]: row for row in manifest["pool"]}
    chained = held_chained(run, manifest)
    hold = rerank_rule(run)["hold_without_abstract"]
    reasons = {rid: "chained_only" for rid in window if rid in chained}
    if hold:
        # A record scored on its title alone fell (Humphreys 36 -> 109, 6 Nov); it keeps its fused place.
        bare = [rid for rid in window if rid not in reasons and not rows[rid]["abstract"]]
        if hold == "with_text_route":
            # Version 3: only while text can still come: an open PDF or a stored file on its work, or a lookup
            # before the rerank that did not settle. A record no source can fill is scored on its title, as under
            # version 1, and takes no read place it cannot use (four Elsevier works, 6 Nov pilot).
            lookup = (store.existing_step(run["id"], PRERANK_LOOKUP_KEY) or {}).get("output") or {}
            # A lookup rule since version 4 stores only the records whose request went out and was not answered.
            unsettled = set(lookup["lookup_open"] if "lookup_open" in lookup else lookup.get("unsettled") or ())
            routed = text_routes(store, [manifest["versions"][rid]["work_id"] for rid in bare])
            reasons |= {rid: "no_abstract_text_route" if manifest["versions"][rid]["work_id"] in routed
                        else "no_abstract_lookup_open" for rid in bare
                        if rid in unsettled or manifest["versions"][rid]["work_id"] in routed}
        else:
            reasons |= {rid: "no_abstract" for rid in bare}
    candidates = [rid for rid in window if rid not in reasons]
    kept = [rid for rid in window if rid in reasons]
    if manifest.get("preselect"):
        contributions = chosen.get("contributions") or {}
        told |= {"preselect": manifest["preselect"] | {
            "pool": len(automatic), "window": size, "ran": len(automatic) > size,
            "lists": [{key: entry[key] for key in ("provider", "query_text", "sort", "votes", "read_total",
                                                   "size", "focused")}
                      for entry in manifest.get("query_lists") or []],
            "floors_taken": chosen.get("floors") or {},
            # Only the window's own contributions: what a record outside it was given is in the lists above.
            "contributions": {rid: contributions.get(rid, []) for rid in window}}}
    texts = [rerankers.document(rows[rid]["title"], rows[rid]["abstract"]) for rid in candidates]
    # The reranker reads the revision's English sentence, not the question as written: its documents are English
    # titles and abstracts, and reranking one language against another is unmeasured. Without a sentence the list
    # keeps its fused order and this step says why, rather than sending the other language.
    sentence = english_question.embedding_query(store, scope)
    step = store.step(run["id"], RERANK_KEY, "code:rerank")
    store.start_step(step["id"])
    if sentence is None:
        store.finish_step(step["id"], "failed", output=choice.identity() | told | {
            "candidate_ids": candidates, "kept_in_place": kept, "read_top": read_top,
            **({"kept_reasons": {rid: reasons[rid] for rid in kept}} if hold else {}),
            "status": "failed", "error_code": english_question.MISSING, "fallback": "fused_order"},
            error_code=english_question.MISSING,
            error={"error": "the revision has no English sentence for the reranker"})
        return
    query = sentence[0]
    output = choice.identity() | told | {
        "candidate_ids": candidates, "kept_in_place": kept, "read_top": read_top, "query_sha256": canonical.sha256_hex(query),
        **({"kept_reasons": {rid: reasons[rid] for rid in kept}} if hold else {}),
        "cut_documents": sum(len(text) > rerankers.MAX_DOCUMENT_CHARS for text in texts),  # kept on failure too
        "sent": {"query": sentence[1], "documents": "title_and_abstract", "count": len(candidates),
                 "to": "this_computer" if choice.provider == "builtin" else choice.provider}}
    seconds = float(choice.timeout_seconds)
    deadline = fast_path.stage_deadline(store, run, "ranking")
    if deadline is not None:
        seconds = min(seconds, (deadline - store.clock.now()).total_seconds())
    if seconds <= 0:
        store.finish_step(step["id"], "failed", output=output | {"status": "failed", "error_code": "no_time_left",
                                                                 "fallback": "fused_order"},
                          error_code="no_time_left", error={"error": "the ranking stage had no time left"})
        return
    checkpoint = lambda: flow._checkpoint(run["id"], run["scope_revision"])  # noqa: E731
    task = asyncio.ensure_future(rerankers.rerank(choice, flow.deps.http, getattr(flow.deps, "local_embedder", None),
                                                  query, texts, checkpoint))
    loop = asyncio.get_running_loop()
    ends = loop.time() + seconds
    try:
        while not task.done():
            left = ends - loop.time()
            if left <= 0:
                break
            await asyncio.wait({task}, timeout=min(1.0, left))
            if not task.done() and flow._stop_requested(run["id"], run["scope_revision"]):
                break
    finally:
        if not task.done():
            task.cancel()  # the built-in runner is killed, so no reply is left unread
            await asyncio.gather(task, return_exceptions=True)
    if task.cancelled():
        checkpoint()  # a pause or a cancellation: the run stops here and the step is asked again on resume
        error = rerankers.RerankError("reranker_timeout", f"no answer within {seconds:g} s")
    else:
        error = task.exception()
    if error is None:
        result = task.result()
        store.finish_step(step["id"], "succeeded", output=output | {
            "status": "applied", "scores": dict(zip(candidates, result["scores"])),
            "truncated_documents": result["truncated"], "provider_tokens": result["provider_tokens"],
            **({"provider_search_units": result["provider_search_units"]} if result.get("provider_search_units") is not None else {})})
    elif isinstance(error, rerankers.RerankError):
        store.finish_step(step["id"], "failed", output=output | {"status": "failed", "error_code": error.code,
                                                                 "error": str(error)[:500], "fallback": "fused_order"},
                          error_code=error.code, error={"error": str(error)[:500]})
    else:
        raise error


def text_routes(store: Any, work_ids: list[str]) -> set[str]:
    """The works among these with a route to their text (rerank rule version 3): a version with an open PDF URL
    (another version's
    copy included), a person's upload, or a file already stored for a version."""
    if not work_ids:
        return set()
    marks = ",".join("?" * len(work_ids))
    return {row[0] for row in store.conn.execute(
        f"SELECT DISTINCT v.work_id FROM source_versions v WHERE v.work_id IN ({marks})"
        " AND (COALESCE(v.oa_pdf_url, '') != '' OR v.origin = 'user_upload' OR EXISTS (SELECT 1 FROM source_assets a"
        " WHERE a.source_version_id = v.id AND a.removed_at IS NULL))", list(dict.fromkeys(work_ids)))}


async def prerank_lookups(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> None:
    """Ask the lookup sources for the missing abstracts of the first records the reranker will score.

    A record without an abstract is sent to the reranker as its title alone and falls (Humphreys 36 -> 109, 6 Nov);
    the read stage's lookup came too late for it, after the list froze and for the top N only. So before the rerank,
    the first `max_records` records of the reranker's window (the fused order without the person's records and, under
    a rerank rule before it, the chained ones the rerank keeps in place) that have no abstract in any version and a DOI on their head are asked
    about, with the sources and requests `ask_second_sources` already uses, under steps of their own, and within
    `seconds` in all (or what is left of the ranking stage). What did not come back in time stays missing: under the
    first lookup rule the record is scored on its title, and under the rerank rule since version 2 it keeps its fused
    place (`rerank_list`). Lookup version 2 asks about every such record of the window, up to 400, within 8 s, with
    Crossref's single requests 4 in flight; the first rule (no version) the first 20 within 5 s, one request at a
    time. Version 3 is version 2 with Semantic Scholar failing fast (no 429 wait, one batch of 400, skipped in a
    cooldown) and the asked records no source answered about stored as `unsettled`. Version 4 has Crossref 8 in
    flight and stores, as `lookup_open`, only the records a request of this round was sent for and did not answer.
    Nothing runs when no reranker would be sent anything, or for a run with no `prerank_lookup` in its budget. The
    chosen records and what was filled are stored on `prerank_lookups`; a run resumed after it succeeded asks
    nothing again.
    A filled record's open `no_abstract` decision, if an earlier run wrote one, is replaced by the read stage's
    `record_flags`, which runs after this and before screening."""
    rule = (run["budget"].get("inspection") or {}).get("prerank_lookup")
    store = flow.store
    if not rule or (store.existing_step(run["id"], PRERANK_LOOKUP_KEY) or {}).get("status") == "succeeded":
        return
    choice = rerank_choice(store, run)
    if choice is None or not rerankers.can_run(choice, getattr(flow.deps, "local_embedder", None)):
        return
    flow._checkpoint(run["id"], run["scope_revision"])
    step = store.step(run["id"], PRERANK_LOOKUP_KEY, "code:lookup_plan")
    asked = (step["output"] or {}).get("asked")  # a resumed run asks about the records it chose the first time
    if asked is None:
        manifest = json_value(manifest_for(flow, run, scope, vocabulary))
        priority, chained = set(manifest["user_priority"]), held_chained(run, manifest)
        automatic = [rid for rid in replay(manifest)["fused"] if rid not in priority]
        # The records this asks about are the ones the reranker will be given, the pre-selection included.
        window = window_for(manifest, automatic, choice.pool_size(run["budget"]["fast_path"]["N"]))["window"]
        rows = {row["id"]: row for row in manifest["pool"]}
        asked = [rid for rid in window if rid not in chained and not rows[rid]["abstract"]
                 and manifest["versions"][rid].get("doi")][:rule["max_records"]]
    store.start_step(step["id"])
    output = {"rule": rule, "asked": asked}
    store.set_step_output(step["id"], output)
    seconds = float(rule["seconds"])
    deadline = fast_path.stage_deadline(store, run, "ranking")
    if deadline is not None:
        seconds = min(seconds, (deadline - store.clock.now()).total_seconds())
    status = "done" if asked else "nothing_to_ask"
    version = rule.get("version", 0)
    if asked and seconds <= 0:
        status = "no_time_left"
    elif asked:
        from deixis.workflow.search import lookups
        words, _ = lookups.title_words(vocabulary)
        try:
            await asyncio.wait_for(lookups.ask_second_sources(
                store, flow.deps.http, flow.deps.settings, run, scope, words,
                lambda: flow._checkpoint(run["id"], run["scope_revision"]),
                rule.get("max_requests", lookups.MAX_LOOKUP_REQUESTS), only=set(asked), prefix=PRERANK_PREFIX,
                crossref_in_flight=rule.get("crossref_in_flight", 1), s2_waits=rule.get("s2_waits"),
                s2_batch=rule.get("s2_batch", S2_LOOKUP_BATCH), s2_cooldown_skip=bool(rule.get("s2_cooldown_skip")),
                record_sent=version >= 4), timeout=seconds)
        except TimeoutError:
            status = "time_ceiling"
            # The request cut short is not asked again by this round: its step says it ran out of time.
            for row in store.conn.execute("SELECT id FROM run_steps WHERE run_id = ? AND operation_key LIKE ?"
                                          " AND status = 'running'", (run["id"], PRERANK_PREFIX + "%")).fetchall():
                # A version 4 step keeps what it stored, its `sent` records among it.
                store.finish_step(row["id"], "failed", output=store.step_output(row["id"]) if version >= 4 else None,
                                  error_code="lookup_time_ceiling",
                                  error={"error": f"the lookups before the rerank had {seconds:g} s in all"})
    filled = [svid for svid in asked if store.conn.execute(
        "SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (svid,)).fetchone()]
    settled = {}
    if version >= 4:
        settled = {"lookup_open": lookup_open(store, run, [svid for svid in asked if svid not in filled])}
    elif version == 3:
        settled = {"unsettled": unsettled(store, run, scope, [svid for svid in asked if svid not in filled])}
    store.finish_step(step["id"], "succeeded", output=output | {"status": status, "filled": filled} | settled)


def unsettled(store: Any, run: dict[str, Any], scope: dict[str, Any], records: list[str]) -> list[str]:
    """Of these records still without an abstract, those the lookup before the rerank did not settle.

    Each source the research asks is settled for a record when its stored plan did not list the record, or listed it
    and the record has its answer: `found` or `not_found` from any run, or a `failed` row this round wrote (a refused
    batch, or one skipped in Semantic Scholar's cooldown, which a later round asks again). A source whose plan was never
    stored (the round ran out of time first), or that listed the record and wrote nothing for it (its request was cut
    short), leaves the record unsettled."""
    from deixis.workflow.search import lookups
    plans = {}
    for provider in ("semantic_scholar", "crossref", "scopus"):
        if lookups.in_scope(scope, provider):
            step = store.existing_step(run["id"], f"{PRERANK_PREFIX}lookup_plan:{provider}")
            plans[provider] = step["output"] if step and step["status"] == "succeeded" else None
    rounds = {row[0] for row in store.conn.execute(
        "SELECT id FROM run_steps WHERE run_id = ? AND operation_key LIKE ?", (run["id"], PRERANK_PREFIX + "%"))}

    def answered(svid: str, provider: str) -> bool:
        return any(row["status"] in ("found", "not_found") or row["step_id"] in rounds for row in store.conn.execute(
            "SELECT status, step_id FROM record_lookups WHERE source_version_id = ? AND provider = ?", (svid, provider)))

    left = []
    for svid in records:
        for provider, plan in plans.items():
            listed = plan is not None and any(row["source_version_id"] == svid
                                              for group in plan.get("batches") or plan.get("chunks") or []
                                              for row in group)
            if plan is None or (listed and not answered(svid, provider)):
                left.append(svid)
                break
    return left


def lookup_open(store: Any, run: dict[str, Any], records: list[str]) -> list[str]:
    """Of these records still without an abstract, those whose latest request of the lookup before the rerank went out
    and whose answer did not come in time (lookup rule version 4): it was still out at the round's ceiling, or its
    step was cut short.

    "Went out" means the request's own headers were written to an open connection (httpcore's trace event); each
    request then puts its records on its step's stored `out`, and its response headers or its stored answer (`found`,
    `not_found` or `failed`) take them off again, so a 429 waiting for its retry is not out, and a record retried after
    a resume is out again until that retry answers. A `found` or `not_found` from a source in any run settles the
    record for that source. A record no request of the round went out for is not open, whatever the reason (the round
    ran out first, it waited for a connection or a proxy tunnel, its transport reports no trace events, or every source
    already had its answer), so the reranker scores it on its title unless it has a route to text."""
    out: set[tuple[str, str]] = set()
    for row in store.conn.execute("SELECT operation_key, output_json FROM run_steps WHERE run_id = ?"
                                  " AND operation_key LIKE ?", (run["id"], PRERANK_PREFIX + "record_lookup:%")):
        provider = row["operation_key"].removeprefix(PRERANK_PREFIX).split(":")[1]
        out |= {(svid, provider) for svid in (json.loads(row["output_json"]) if row["output_json"] else {}).get("out")
                or ()}
    return [svid for svid in records if any(not store.conn.execute(
        "SELECT 1 FROM record_lookups WHERE source_version_id = ? AND provider = ?"
        " AND status IN ('found', 'not_found')",
        (svid, provider)).fetchone() for record, provider in out if record == svid)]


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> None:
    point = rerank_point(run)
    if flow.store.existing_step(run["id"], LIST_KEY) is None:
        chained = flow._chain_filter(run)
        from deixis.workflow.search import lookups
        words, _ = lookups.title_words(vocabulary)
        lookups.flag_and_decide(flow.store, run, scope, words,
                               works=set(flow.store.work_ids(chained).values()), key="chain_record_flags")
        if point == "before_list":
            await prerank_lookups(flow, run, scope, vocabulary)
            await rerank_list(flow, run, scope, vocabulary)
    listing = freeze_list(flow, run, scope, vocabulary)
    if point == "after_list":
        # Quick: the list is frozen and does not change, so the reranker reads its small group now, for the
        # measurement alone. The missing abstracts are not asked for first: that lookup spends the stage's own time
        # to improve an order this depth does not use. The ranking stage's deadline still holds, so a stage with no
        # time left leaves the step saying so.
        await rerank_list(flow, run, scope, vocabulary)
    from deixis.workflow.read import read as fast_read
    flow._close_clock_stage(run, "ranking")
    if run["budget"].get("benchmark_list_barrier"):
        # Benchmark only (the deeper-screening gate): the run pauses once, after its list and before any read
        # work, so a
        # runner can copy the library here. On resume the step exists and the run reads as any other.
        barrier = flow.store.step(run["id"], LIST_BARRIER_KEY, "code:benchmark_list_barrier")
        if barrier["status"] != "succeeded":
            flow.store.start_step(barrier["id"])
            flow.store.finish_step(barrier["id"], "succeeded", output={"manifest_hash": listing["manifest_hash"]})
            flow._pause(run["id"], "benchmark_list_barrier")
    flow._enter_clock_stage(run, "read")
    only = {svid for item in listing["items"][:run["budget"]["fast_path"]["N"]] for svid in item["versions"]}
    await flow._second_sources(run, scope, vocabulary, only=only)
    from deixis.workflow.search.fast_chain import read_versions
    snapshot = read_versions(flow, run, listing)
    await fast_read.execute(flow, run, scope, vocabulary, listing, read_versions=snapshot["versions"])
    flow._close_clock_stage(run, "read")


def halt_pipeline(flow: Any, run: dict[str, Any]) -> None:
    guard = getattr(flow, "_small_batch_guard", None)
    if guard and guard["run_id"] == run["id"] and "reserved_calls" in guard:
        guard["halted"] = True
        held = flow._held.get(run["id"])
        if held:
            held.halted = True
            held.wake.set()

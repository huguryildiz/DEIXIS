"""D237: frozen fused lists and bounded batches, persisted entirely as existing code steps."""

from __future__ import annotations

import json
import math
from typing import Any

from deixis.domain import canonical
from deixis.domain.reason_codes import reason
from deixis.domain.rules import ABSTRACT_READ_LIMIT, FULLTEXT_RUNS
from deixis.storage.db import transaction
from deixis.workflow import adjudication, fast_path, fulltext, ranking
from deixis.workflow.decisions import DecisionStore

POLICY = "small_batch_fused_v1"
BATCH_SIZE = 40
MINIMUM = 50
LIST_KEY = "small_batch:v1:list"
GRAPH_SEEDS = 30  # D246: rows with a reference list taken from the top of the fused order
ANSWER_ALLOCATION_VERSION = 2


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
            from deixis.workflow.store import LegacyInspectionPolicyRemoved
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


def answer_listing(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    binding = run["budget"]["inspection"]
    step = store.existing_step(binding.get("list_run_id", run["id"]), LIST_KEY)
    if (step is None or step["status"] != "succeeded"
            or binding.get("manifest_hash", step["output"]["manifest_hash"]) != step["output"]["manifest_hash"]):
        raise ValueError("Answer frozen-list binding does not resolve")
    if step["output"]["manifest"].get("scope_revision") != run["scope_revision"]:
        raise ValueError("Answer frozen-list scope_revision differs from the answer run")
    return step["output"]


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
    fetch = body.get("fulltext_fetch") or {}
    reads = adjudication.read_budget(effort) if reading == "auto" and fetch else {}
    # The former follow-up reading allowance moves into this run, without increasing the chain's total.
    body["max_model_calls"] += reads.get("max_model_calls", 0)
    body["max_fulltext_reads"] = reads.get("max_fulltext_reads", 0)
    body["inspection"] = {
        "policy": POLICY, "runner_version": 4, "batch_size": BATCH_SIZE, "minimum_processed_works": MINIMUM,
        "discovery_model_calls": budget["max_model_calls"],
        "abstract_limit": ABSTRACT_READ_LIMIT[effort],
        "fetch_limit": fetch.get("max_fulltext_works", 0) + fetch.get("chain_room", 0),
        "read_limit": body["max_fulltext_reads"], "max_model_calls": body["max_model_calls"],
        "fetch_attempts": fulltext.FULLTEXT_WORK_ATTEMPTS,
    }
    return body


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
    ranked = ranking.rank_pool(pool, verified,
                             set(manifest["query_words"]), manifest["blocks"], manifest["embedding_model"],
                             manifest["similarities"], manifest["off_reason"], manifest["compared_terms"])
    version = manifest.get("ranking_version", 1)
    top = ranked["fused"][:20]
    if version == 3:
        # D246: a second graph pass seeded from the fused top instead of the keyword top, counting a seed's
        # citation of a record twice; the whole pool is fused again before the version 2 reorder below.
        verified_works = {r["work_id"] for r in verified}
        by_id = {r["id"]: r for r in pool}
        seeds = verified + [by_id[rid] for rid in ranked["fused"]
                            if by_id[rid]["references"] and by_id[rid]["work_id"] not in verified_works][:GRAPH_SEEDS]
        if any(seed["references"] for seed in seeds):
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
        from deixis.workflow.flow import RRF_K

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
    order = list(dict.fromkeys(priority + ranked["fused"]))
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
            "items": items, "ranks": json_value(ranked["ranks"]), "signal_reasons": ranked["reasons"]}


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


def freeze_list(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    def build() -> dict[str, Any]:
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
        verified = [row for head in ranking.verified_seeds(store, rid, scope)
                    if (row := in_pool.get(head) or ranking._seed_row(head, versions)) is not None]
        terms = (store.existing_step(run["id"], "vocabulary_expansion") or {}).get("output") or {}
        from deixis.workflow.expansion import expansion_blocks
        query, blocks = ranking.query_vocabulary(scope, vocabulary,
                                                expansion_blocks(terms.get("expansion"), terms.get("queries")))
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
        manifest = {"ranking_version": 3,
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
        from deixis.workflow.fast_chain import manifest as chain_manifest
        manifest["fast_path"] = chain_manifest(store, run)
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
    signatures = guard.get("user_signatures", {"batch": guard["user_signature"]})
    current_signature = user_signature(store, guard["rid"])
    if any(current_signature != signature for signature in signatures.values()):
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


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> None:
    if flow.store.existing_step(run["id"], LIST_KEY) is None:
        chained = flow._chain_filter(run)
        from deixis.workflow import lookups
        words, _ = lookups.title_words(vocabulary)
        lookups.flag_and_decide(flow.store, run, scope, words,
                               works=set(flow.store.work_ids(chained).values()), key="chain_record_flags")
    listing = freeze_list(flow, run, scope, vocabulary)
    from deixis.workflow import fast_read
    flow._close_clock_stage(run, "ranking")
    flow._enter_clock_stage(run, "read")
    only = {svid for item in listing["items"][:run["budget"]["fast_path"]["N"]] for svid in item["versions"]}
    await flow._second_sources(run, scope, vocabulary, only=only)
    from deixis.workflow.fast_chain import read_versions
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

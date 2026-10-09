"""D253: cutoff-owned evidence, breadth-first answers and separate assessments."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.workflow import fast_path, small_batch, criterion_passages
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE, fuse_rankings

CUTOFF = "fast_path:v1:cutoff"
INPUT = "fast_path:v1:answer_input"
VERSION_FIELDS = ("work_id", "title", "abstract", "doi", "version_label", "year")


def human_choice(human: dict[str, Any]) -> dict[str, Any]:
    # A wrong file says nothing against the screened abstract of its version.
    state = ("pdf_wrong" if human["reason_code"] == "human_pdf_wrong" else
             {"include": "included", "candidate": "included", "out_of_scope": "excluded",
              "criterion_not_met": "excluded"}.get(human["outcome"], "pending"))
    return {"state": state, "user_reason": human["note"]}


def user_choices(store: Any, rid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    selections = {r["source_version_id"]: dict(r) for r in store.conn.execute(
        "SELECT * FROM selections WHERE research_id = ? AND origin = 'user'"
        " AND state IN ('included', 'excluded')", (rid,))}
    humans = {}
    for row in store.conn.execute(
            "SELECT d.*, v.work_id FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
            " WHERE d.research_id = ? AND d.decided_by = 'human' AND d.superseded_at IS NULL"
            " ORDER BY d.created_at, d.rowid", (rid,)):
        humans[row["work_id"]] = human_choice(dict(row))
    return selections, humans


def current_pools(store: Any, rid: str) -> dict[str, list[dict[str, Any]]]:
    pools: dict[str, list[dict[str, Any]]] = {}
    for row in store.conn.execute(
            "SELECT p.id, p.source_version_id, p.kind, p.asset_id FROM passages p"
            " JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL AND (p.asset_id IS NULL OR EXISTS"
            " (SELECT 1 FROM source_assets a WHERE a.id = p.asset_id AND a.removed_at IS NULL"
            " AND a.extraction_version IS p.extraction_version)) ORDER BY p.kind, p.physical_page, p.rowid", (rid,)):
        pools.setdefault(row["source_version_id"], []).append(dict(row))
    return pools


def answer_run_budget(store: Any, rid: str, scope: dict[str, Any], *, discovery_id: str | None = None) -> dict[str, Any]:
    budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__
    if discovery_id is None:
        budget = small_batch.answer_budget(store, rid, scope["revision"], budget)
    else:
        discovery = store.run(discovery_id)
        assert (discovery["research_id"], discovery["scope_revision"], discovery["status"]) == (rid, scope["revision"], "completed")
        listing = store.existing_step(discovery_id, small_batch.LIST_KEY)
        binding = {"policy": small_batch.POLICY, "list_run_id": discovery_id,
                   "answer_allocation_version": small_batch.ANSWER_ALLOCATION_VERSION}
        binding |= ({"manifest_hash": listing["output"]["manifest_hash"]} if listing and listing["status"] == "succeeded"
                    else {"binding_error": "answer_frozen_list_missing"})
        budget = budget | {"inspection": binding}
    return fast_path.answer_budget(store, rid, scope["revision"], budget)


def reading_records(store: Any, rid: str) -> dict[str, Any]:
    steps, paired, plans, inputs, assets, history = {}, {}, {}, {}, {}, {}
    for row in store.conn.execute(
            "SELECT s.* FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
            " AND s.kind IN ('model:fulltext_adjudication', 'code:adjudication_plan')", (rid,)):
        step = dict(row)
        steps[step["id"]] = step
        paired[(step["run_id"], step["operation_key"])] = step
        if step["kind"] == "code:adjudication_plan" and step["status"] == "succeeded":
            for item in json.loads(step["output_json"]).get("works", []):
                plans.setdefault((step["run_id"], item["read_version"]), []).append(item)
    for row in store.conn.execute(
            "SELECT i.step_id, i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND s.kind = 'model:fulltext_adjudication'"
            " ORDER BY i.attempt, i.rowid", (rid,)):
        inputs[row["step_id"]] = row["payload_json"]
    for row in store.conn.execute(
            "SELECT p.id, p.asset_id FROM passages p JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,)):
        assets[row["id"]] = row["asset_id"]
    for row in store.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'"
            " ORDER BY created_at, rowid", (rid,)):
        history.setdefault(row["source_version_id"], []).append(dict(row))
    return {"steps": steps, "paired": paired, "plans": plans, "inputs": inputs,
            "assets": assets, "history": history}


def read_file(flow: Any, decision: dict[str, Any] | None, svid: str, records: dict[str, Any]) -> str | None:
    """A successful reading's own frozen plan must name the file still in use."""
    if not decision or not decision.get("step_id"):
        return None
    step = records["steps"].get(decision["step_id"])
    if not step or step["kind"] != "model:fulltext_adjudication" or step["status"] != "succeeded":
        return None
    prefix = step["operation_key"].rsplit(":", 1)[0]
    inspected_assets = set()
    for number in (1, 2):
        paired = records["paired"].get((step["run_id"], f"{prefix}:{number}"))
        if not paired or paired["status"] != "succeeded":
            return None
        sent = records["inputs"].get(paired["id"])
        if not sent:
            return None
        pages = json.loads(sent)["passages"]
        if not pages or any(p["source_id"] != svid for p in pages):
            return None
        if any(p["passage_id"] not in records["assets"] for p in pages):
            return None
        inspected_assets.update(records["assets"][p["passage_id"]] for p in pages)
    for item in records["plans"].get((step["run_id"], svid), []):
        if (item.get("asset_id") and inspected_assets == {item["asset_id"]} and flow._file_holds(item)):
            return item["asset_id"]
    return None


def cutoff_snapshot(flow: Any, run: dict[str, Any], listing: dict[str, Any], closure: dict[str, Any]) -> dict[str, Any]:
    store, rid = flow.store, run["research_id"]
    decisions = DecisionStore(store)
    facts = decisions.facts(rid)
    versions = store.answer_versions(rid)
    selections, humans = user_choices(store, rid)
    pools = current_pools(store, rid)
    readings = reading_records(store, rid)
    unread = set(closure["not_screened_at_cutoff"])
    items = list(listing["items"])
    present = {item["work_id"] for item in items[:run["budget"]["fast_path"]["N"]]}
    listed = {item["work_id"] for item in items}
    items += [{"work_id": wid, "head": head, "position": None, "user_priority": False}
              for wid, head in facts["heads"].items() if wid not in listed]
    rows, excluded = [], Counter()
    for item in items:
        wid, head = item["work_id"], item["head"]
        user = selections.get(head) or humans.get(wid)
        outcome = decisions.work_outcome(rid, wid, facts)
        svid = versions.get(head) or head
        fresh = [d for d in facts["decisions"].get(wid, []) if not decisions.is_stale(d, facts["stale_key"])]
        full = next((d for d in reversed(fresh) if d["stage"] == "fulltext"
                     and d["source_version_id"] == svid), None)
        inspected = full
        asset = read_file(flow, inspected, svid, readings)
        if not asset and full and full["decided_by"] == "human":
            for previous in reversed(readings["history"].get(svid, [])):
                if previous["stage"] == "fulltext" and not decisions.is_stale(previous, facts["stale_key"]):
                    asset = read_file(flow, previous, svid, readings)
                    if asset:
                        inspected = previous
                        break
        # Only a screened version supplies its abstract. Another version is not corroboration.
        abstract = next((d for d in reversed(fresh) if d["stage"] == "abstract"
                         and d["source_version_id"] == svid and d["outcome"] == "candidate"), None)
        route = "fulltext" if asset and full["outcome"] == "include" else "abstract"
        reason = None
        if wid not in present:
            reason = "outside_read_window"
        elif wid in unread:
            reason = "not_screened_at_cutoff"
        elif outcome.get("reason_code") == "versions_disagree":
            reason = "versions_disagree"
        elif outcome.get("outcome") in ("criterion_not_met", "out_of_scope"):
            reason = outcome["outcome"]
        elif route == "abstract" and abstract is None:
            reason = "not_screened_at_cutoff"
        passages = pools.get(svid, [])
        abstract_ids = [p["id"] for p in passages if p["kind"] == "abstract"][:1]
        full_ids = [p["id"] for p in passages if p["kind"] == "pdf_page" and p["asset_id"] == asset] if asset else []
        source = store.source(svid)
        row = {"work_id": wid, "head": head, "position": item["position"], "source_version_id": svid,
               "route": route, "decision_id": (full if route == "fulltext" else abstract or {}).get("id"),
               "abstract_decision_id": (abstract or {}).get("id"),
               "fulltext_decision_id": inspected["id"] if asset else None,
               "asset_id": asset, "abstract_ids": abstract_ids, "fulltext_ids": full_ids,
               "reason": reason, "base_reason": reason, "base_route": route,
               "file_unverified": bool(full and not asset),
               "version": {k: source.get(k) for k in VERSION_FIELDS}}
        apply_user(row, user)
        if not row["reason"] and not (full_ids if row["route"] == "fulltext" else abstract_ids):
            row["reason"] = "no_text_at_cutoff"
        if row["reason"]:
            excluded[row["reason"]] += 1
        rows.append(row)
    return {
        "cutoff_at": closure["read_cutoff_at"], "scope_revision": run["scope_revision"],
        "criterion_hash": facts["stale_key"][1], "selection_revision": store.selection_revision(rid),
        "user_signature": small_batch.user_signature(store, rid), "manifest_hash": listing["manifest_hash"],
        "items": rows, "excluded_reasons": dict(excluded)}


def freeze_cutoff(flow: Any, run: dict[str, Any], listing: dict[str, Any], closure: dict[str, Any],
                  *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    frozen = snapshot if snapshot is not None else cutoff_snapshot(flow, run, listing, closure)
    return small_batch.save_code(flow, run, CUTOFF, "code:fast_path_cutoff", lambda: frozen)


def apply_user(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    row["reason"], row["route"] = row["base_reason"], row["base_route"]
    row["user_priority"] = bool(user and user["state"] == "included")
    row["override_reason"] = user.get("user_reason") if user else None
    if not user:
        return
    if user["state"] == "excluded":
        row["reason"] = "user_excluded"
    elif user["state"] == "pending":
        row["reason"] = "user_pending"
    elif user["state"] == "pdf_wrong":
        row["route"] = "abstract"
        if row["base_route"] == "fulltext":
            row["reason"] = (row["base_reason"] if row.get("abstract_decision_id")
                             else "not_screened_at_cutoff")
    elif user["state"] == "included":
        row["route"] = "fulltext" if row["fulltext_ids"] else "abstract"
        row["reason"] = None if row["fulltext_ids"] or row["abstract_ids"] else "user_included_no_text"
    if row["route"] == "abstract" and row["base_route"] == "fulltext":
        row["decision_id"] = row.get("abstract_decision_id")


def input_plan(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    store, rid = flow.store, run["research_id"]
    saved = store.existing_step(run["id"], INPUT)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    cutoff = store.existing_step(run["budget"]["inspection"]["list_run_id"], CUTOFF)
    if not cutoff or cutoff["status"] != "succeeded":
        flow._fail(run["id"], "answer_cutoff_missing")
    frozen = cutoff["output"]
    rows = json.loads(json.dumps(frozen["items"]))
    selections, humans = user_choices(store, rid)
    changed = frozen["user_signature"] != small_batch.user_signature(store, rid)
    if changed:
        for row in rows:
            apply_user(row, selections.get(row["head"]) or humans.get(row["work_id"]))
    members = {r["id"]: dict(r) for r in store.conn.execute(
        "SELECT v.* FROM source_versions v JOIN corpus_memberships m ON m.source_version_id = v.id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,))}
    pools = current_pools(store, rid)
    for row in rows:
        svid = row["source_version_id"]
        if svid not in members:
            row["reason"] = "removed_after_cutoff"
        elif any(members[svid].get(k) != v for k, v in row["version"].items()):
            # Keep source metadata and screened text bound to the same cutoff record.
            row["reason"] = "source_changed_after_cutoff"
        else:
            current = {p["id"] for p in pools.get(svid, [])}
            for key in ("abstract_ids", "fulltext_ids"):
                row[key] = [pid for pid in row[key] if pid in current]
            if row["route"] == "fulltext" and not row["fulltext_ids"]:
                row["route"] = "abstract"
                row["decision_id"] = row.get("abstract_decision_id")
                if not row["decision_id"] and not row["user_priority"]:
                    row["abstract_ids"] = []
            if not row["reason"] and not (row["fulltext_ids"] if row["route"] == "fulltext" else row["abstract_ids"]):
                row["reason"] = "no_text_at_cutoff"
    excluded = [{"work_id": r["work_id"], "source_version_id": r["source_version_id"], "reason": r["reason"]}
                for r in rows if r["reason"]]
    rows = [row for row in rows if not row["reason"]]
    rows.sort(key=lambda row: not row["user_priority"])
    patterns = flow._criterion_phrases(run, scope)
    fts = " OR ".join(f'"{term}"' for term in flow._topic_terms(rid, scope))
    queues = []
    for row in rows:
        ids = row["fulltext_ids"] if row["route"] == "fulltext" else row["abstract_ids"]
        pages = [store.passage(pid) for pid in ids]
        if row["route"] == "fulltext":
            topic = [p for p in store.search_passages([row["source_version_id"]], fts, len(ids)) if p["id"] in ids]
            criterion = criterion_passages.criterion_order(pages, patterns or [])
            ranked = fuse_rankings(topic, criterion) if criterion else topic
            pages = list({p["id"]: p for p in [*ranked, *pages]}.values())[:MAX_PASSAGES_PER_SOURCE]
        queues.append(pages)
    breadth = len(rows)
    limit = max(run["budget"]["max_answer_passages"], breadth + sum(r["route"] == "fulltext" for r in rows))
    passages = small_batch.allocate(queues, limit, MAX_PASSAGES_PER_SOURCE, breadth=breadth)
    return small_batch.save_code(flow, run, INPUT, "code:fast_path_answer_input", lambda: {
        "policy_hash": run["budget"]["fast_path"]["policy_hash"], "cutoff_step_id": cutoff["id"],
        "cutoff_at": frozen["cutoff_at"], "scope_revision": run["scope_revision"],
        "cutoff_selection_revision": frozen["selection_revision"], "selection_revision": store.selection_revision(rid),
        "user_signature": small_batch.user_signature(store, rid), "items": rows,
        "excluded": excluded, "excluded_reasons": dict(Counter(r["reason"] for r in excluded)),
        "passage_ids": [p["id"] for p in passages], "limit": limit, "breadth": breadth,
        "semantic_retrieval": "skipped: fast_path_lexical"})


def check_input(flow: Any, run_id: str, plan: dict[str, Any]) -> None:
    store = flow.store
    rid = store.run(run_id)["research_id"]
    members = {r["id"]: dict(r) for r in store.conn.execute(
        "SELECT v.* FROM source_versions v JOIN corpus_memberships m ON m.source_version_id = v.id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,))}
    pools = current_pools(store, rid)
    selected = set(plan["passage_ids"])
    late = store.run(run_id)["budget"].get("late_revision_id")
    versions = store.answer_versions(rid) if late else {}
    heads = store.work_heads(rid) if late else {}
    for row in plan["items"]:
        svid = row["source_version_id"]
        if late and (heads.get(row["work_id"]) != row["head"] or versions.get(row["head"], row["head"]) != svid
                     or row["route"] == "fulltext" and flow._current_asset(svid) != row["asset_id"]):
            flow._pause(run_id, "source_changed")
        if svid not in members or any(members[svid].get(k) != v for k, v in row["version"].items()):
            flow._pause(run_id, "source_changed")
        current = {p["id"] for p in pools.get(svid, [])}
        owned = set(row["abstract_ids"]) | set(row["fulltext_ids"])
        if (selected & owned) - current:
            flow._pause(run_id, "source_changed")


async def answer(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    if run["budget"].get("late_revision_id"):
        from deixis.workflow import late_revision
        late = late_revision.row_for_run(flow.store, run)
        if late and late["status"] in ("published", "failed") and flow.store.conn.execute(
                "SELECT 1 FROM answers WHERE run_id = ?", (run["id"],)).fetchone():
            # Publication survived a crash before run completion; finish and enqueue its review without regenerating.
            return
        plan = late_revision.revision_plan(flow, run, scope)
    else:
        plan = input_plan(flow, run, scope)
    flow._small_batch_guard = {"run_id": run["id"], "rid": run["research_id"],
        "user_signature": plan["user_signature"], "fast_answer": True, "input": plan}
    if run["budget"].get("late_revision_id"):
        flow._small_batch_guard["late_revision"] = True
    try:
        flow._checkpoint(run["id"], run["scope_revision"])
        flow.store.update_run(run["id"], stage="answer")
        if not plan["passage_ids"]:
            flow.store.save_answer(run["research_id"], run["id"], None, None, run["scope_revision"],
                "no_evidence", None, {"ok": True, "issues": [], "reason": "no_evidence_at_cutoff"},
                selection_revision=plan["selection_revision"])
            return
        await flow._generate_answer(run, scope, [flow.store.passage(pid) for pid in plan["passage_ids"]],
                                    plan["selection_revision"])
    finally:
        flow._small_batch_guard = None


def auto_answer(store: Any, run: dict[str, Any]) -> None:
    if not run["budget"]["fast_path"].get("auto_answer"):
        return
    ledger = store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (run["id"],)).fetchone()
    reason = "scope_revised" if store.research(run["research_id"])["current_scope_revision"] != run["scope_revision"] else None
    if ledger["answer_run_id"]:
        reason = "answer_already_started"
    if store.conn.execute("SELECT 1 FROM runs WHERE research_id = ? AND kind = 'answer'"
                          " AND status IN ('queued', 'running', 'pause_requested')", (run["research_id"],)).fetchone():
        reason = "answer_already_active"
    if reason:
        store._event(run["research_id"], "auto_answer_skipped", {"reason": reason}, run["id"])
        return
    scope = store.scope(run["research_id"], run["scope_revision"])
    budget = answer_run_budget(store, run["research_id"], scope, discovery_id=run["id"]) | {"trigger": "auto_after_discovery"}
    store.create_run(run["research_id"], "answer", budget, f"fast_path:auto_answer:{run['id']}")


def after_answer(flow: Any, run: dict[str, Any]) -> None:
    store = flow.store
    from deixis.workflow import late_revision
    late_revision.schedule(flow, run)
    row = store.conn.execute("SELECT id FROM answers WHERE run_id = ? AND status = 'structurally_valid'", (run["id"],)).fetchone()
    if not row:
        return
    store.create_run(run["research_id"], "answer_review", {"max_model_calls": 2, "max_provider_requests": 0},
                     f"answer_review:{row['id']}", target={"answer_id": row["id"], "answer_run_id": run["id"]})


async def review(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    flow._checkpoint(run["id"], run["scope_revision"])
    row = flow.store.conn.execute("SELECT * FROM answers WHERE id = ? AND research_id = ? AND status = 'structurally_valid'",
                                 (run["target"]["answer_id"], run["research_id"])).fetchone()
    if not row:
        flow._fail(run["id"], "answer_unavailable")
    await flow._review(run, scope, row["id"], json.loads(row["draft_json"]))

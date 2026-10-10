"""D255: one append-only answer revision from cutoff-selected late full text."""

from __future__ import annotations

import copy
import json
from typing import Any

from deixis.storage.db import dumps, new_id, transaction
from deixis.workflow import adjudication, criterion_passages, fast_answer, fast_path, small_batch
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import fuse_rankings

REVISION_INPUT = "fast_path:v1:revision_input"
OPEN = ("waiting_fetch", "reading", "answering")


def available(store: Any) -> bool:
    # Policies frozen before D255 have no late lane.
    return bool(store.conn.execute(
        "SELECT 1 FROM runs WHERE kind = 'discovery'"
        " AND json_extract(budget_json, '$.fast_path.policy') = ?"
        " AND json_extract(budget_json, '$.fast_path.late_revision.mode') = 'auto'"
        " AND json_extract(budget_json, '$.fast_path.late_revision.max_revisions') = 1 LIMIT 1",
        (fast_path.POLICY,),
    ).fetchone())


def row_for_run(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    key = (run.get("target") or {}).get("late_revision_id") or run["budget"].get("late_revision_id")
    if not key or not available(store):
        return None
    row = store.conn.execute("SELECT * FROM fast_path_late_revisions WHERE id = ?", (key,)).fetchone()
    if not row or run["id"] not in (row["read_run_id"], row["answer_run_id"]):
        return None
    return dict(row)


def base_plan(store: Any, row: dict[str, Any]) -> dict[str, Any]:
    return json.loads(store.conn.execute("SELECT output_json FROM run_steps WHERE id = ?", (row["base_input_step_id"],)).fetchone()[0])


def guard_reason(store: Any, row: dict[str, Any]) -> str | None:
    research = store.conn.execute("SELECT * FROM researches WHERE id = ?", (row["research_id"],)).fetchone()
    if not research or research["trashed_at"]:
        return "research_trashed"
    if research["current_scope_revision"] != row["scope_revision"]:
        return "scope_revised"
    if small_batch.user_signature(store, row["research_id"]) != base_plan(store, row)["user_signature"]:
        return "selection_changed_by_user"
    # rowid orders answers even when a fake clock gives them identical timestamps.
    if store.conn.execute(
            "SELECT 1 FROM answers WHERE research_id = ? AND rowid > (SELECT rowid FROM answers WHERE id = ?)"
            " AND run_id IS NOT ? LIMIT 1", (row["research_id"], row["base_answer_id"], row["answer_run_id"])).fetchone():
        return "newer_answer_exists"
    return None


def finish(store: Any, row: dict[str, Any], status: str, reason: str) -> None:
    changed = store.conn.execute(
        "UPDATE fast_path_late_revisions SET status = ?, skip_reason = ?, updated_at = ?"
        " WHERE id = ? AND status IN ('waiting_fetch','reading','answering')",
        (status, reason, fast_path.timestamp(store.clock), row["id"])).rowcount
    if changed:
        store._event(row["research_id"], "late_revision_skipped", {"reason": reason}, row["ledger_run_id"])


def checkpoint(flow: Any, run: dict[str, Any]) -> None:
    row = row_for_run(flow.store, run)
    if row is None:
        return
    reason = guard_reason(flow.store, row)
    if reason or row["status"] not in OPEN:
        from deixis.workflow.flow import RunStopped
        with transaction(flow.store.conn):
            if reason:
                finish(flow.store, row, "skipped", reason)
            flow.store.update_run(run["id"], event="run_cancelled", status="cancelled", pause_reason=reason or row["status"])
        raise RunStopped
    if run["kind"] == "fulltext_adjudication":
        check_candidates(flow, row, json.loads(row["works_json"]), pause_run=run["id"])


def schedule(flow: Any, run: dict[str, Any]) -> None:
    store = flow.store
    binding = run["budget"].get("fast_path") or {}
    if not fast_path.enforces(run["budget"], "answer") or binding.get("role") != "first":
        return
    discovery = store.run(binding["ledger_run_id"])
    if discovery["budget"]["fast_path"].get("late_revision") != {"mode": "auto", "max_revisions": 1}:
        return
    if not available(store):
        return
    base = store.conn.execute("SELECT * FROM answers WHERE run_id = ? ORDER BY rowid DESC LIMIT 1", (run["id"],)).fetchone()
    plan = store.existing_step(run["id"], fast_answer.INPUT)
    cutoff = store.existing_step(discovery["id"], fast_answer.CUTOFF)
    closure_row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ?"
        " AND operation_key LIKE '%:fast:close' AND status = 'succeeded' ORDER BY rowid DESC LIMIT 1", (discovery["id"],)).fetchone()
    closure = json.loads(closure_row[0]) if closure_row else None
    if not base or not plan or not cutoff or not closure:
        return
    selected = set(closure["selected_work_ids"])
    base_items = {i["work_id"]: i for i in plan["output"]["items"]}
    candidates = [copy.deepcopy(base_items.get(i["work_id"], i)) for i in cutoff["output"]["items"]
                  if i["work_id"] in selected and not i["fulltext_decision_id"]
                  and i["route"] == "abstract" and i["reason"] in (None, "no_text_at_cutoff")
                  and (i["work_id"] in base_items or i["reason"] == "no_text_at_cutoff")]
    if not candidates:
        return
    ts = fast_path.timestamp(store.clock)
    store.conn.execute(
        "INSERT OR IGNORE INTO fast_path_late_revisions"
        " (id, ledger_run_id, research_id, scope_revision, base_answer_id, base_input_step_id, status, works_json, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'waiting_fetch', ?, ?, ?)",
        (new_id("late"), discovery["id"], run["research_id"], run["scope_revision"], base["id"], plan["id"], dumps(candidates), ts, ts))


def check_candidates(flow: Any, row: dict[str, Any], works: list[dict[str, Any]], *, pause_run: str | None = None) -> bool:
    store, rid = flow.store, row["research_id"]
    heads, versions = store.work_heads(rid), store.answer_versions(rid)
    for item in works:
        head, svid = item["head"], item["source_version_id"]
        valid = heads.get(item["work_id"]) == head and versions.get(head, head) == svid
        if valid:
            source = store.source(svid)
            valid = all(source.get(k) == v for k, v in item["version"].items())
        if not valid:
            if pause_run:
                flow._pause(pause_run, "source_changed")
            return False
    return True


def outcomes(flow: Any, row: dict[str, Any]) -> list[dict[str, Any]]:
    store = flow.store
    facts = DecisionStore(store).facts(row["research_id"])
    records = fast_answer.reading_records(store, row["research_id"])
    result = []
    for item in json.loads(row["works_json"]):
        fresh = [d for d in facts["decisions"].get(item["work_id"], [])
                 if d["stage"] == "fulltext" and d["source_version_id"] == item["source_version_id"]
                 and not DecisionStore(store).is_stale(d, facts["stale_key"])
                 and records["steps"].get(d.get("step_id"), {}).get("run_id") == row["read_run_id"]]
        decision = fresh[-1] if fresh else None
        asset = fast_answer.read_file(flow, decision, item["source_version_id"], records)
        result.append(item | {"late_outcome": decision["outcome"] if decision else None,
                              "late_decision_id": decision["id"] if decision else None, "late_asset_id": asset})
    return result


def advance(flow: Any, rid: str | None = None) -> None:
    store = flow.store
    if not available(store):
        return
    rows = [dict(r) for r in store.conn.execute(
        "SELECT * FROM fast_path_late_revisions WHERE status IN ('waiting_fetch','reading','answering')"
        + (" AND research_id = ?" if rid else ""), (rid,) if rid else ())]
    if not rows:
        return
    for row in rows:
        with transaction(store.conn):
            reason = guard_reason(store, row)
            if reason:
                finish(store, row, "skipped", reason)
                continue
            if store.conn.execute("SELECT 1 FROM runs WHERE research_id = ?"
                                  " AND status IN ('queued','running','pause_requested','paused')", (row["research_id"],)).fetchone():
                continue
            scope = store.scope(row["research_id"], row["scope_revision"])
            ts = fast_path.timestamp(store.clock)
            if row["status"] == "waiting_fetch":
                if store.conn.execute("SELECT 1 FROM fast_path_background_fetches WHERE ledger_run_id = ?"
                                      " AND status IN ('queued','running')", (row["ledger_run_id"],)).fetchone():
                    continue
                works = json.loads(row["works_json"])
                if not check_candidates(flow, row, works):
                    finish(store, row, "skipped", "source_changed")
                    continue
                selections, humans = fast_answer.user_choices(store, row["research_id"])
                pools = fast_answer.current_pools(store, row["research_id"])
                works = [i for i in works if (selections.get(i["head"]) or humans.get(i["work_id"]) or {}).get("state") != "pdf_wrong"
                         and any(p["kind"] == "pdf_page" for p in pools.get(i["source_version_id"], []))]
                if not works:
                    finish(store, row, "skipped", "no_new_fulltext")
                    continue
                budget = adjudication.read_budget(scope["effort"]) | {"max_fulltext_reads": len(works), "max_model_calls": 2 * len(works)}
                run = store.create_run(row["research_id"], "fulltext_adjudication", budget,
                    f"fast_path:late_read:{row['ledger_run_id']}", target={"late_revision_id": row["id"],
                    "discovery_run_id": row["ledger_run_id"], "heads": [i["head"] for i in works]})
                store.conn.execute("UPDATE fast_path_late_revisions SET status = 'reading', read_run_id = ?, works_json = ?,"
                                   " read_started_at = ?, updated_at = ? WHERE id = ?", (run["id"], dumps(works), ts, ts, row["id"]))
                store._event(row["research_id"], "late_revision_queued", {"phase": "reading"}, run["id"])
            elif row["status"] == "reading":
                status = store.run(row["read_run_id"])["status"]
                if status != "completed":
                    finish(store, row, "failed" if status == "failed" else "skipped", f"read_run_{status}")
                    continue
                works = outcomes(flow, row)
                store.conn.execute("UPDATE fast_path_late_revisions SET works_json = ? WHERE id = ?", (dumps(works), row["id"]))
                if not check_candidates(flow, row, works):
                    finish(store, row, "skipped", "source_changed")
                    continue
                if not any(i["late_outcome"] == "include" and i["late_asset_id"] for i in works):
                    finish(store, row, "skipped", "no_fulltext_inclusion")
                    continue
                budget = fast_answer.answer_run_budget(store, row["research_id"], scope, discovery_id=row["ledger_run_id"])
                budget |= {"trigger": "late_fulltext", "late_revision_id": row["id"]}
                budget["fast_path"]["role"] = "late_revision"
                run = store.create_run(row["research_id"], "answer", budget, f"fast_path:late_answer:{row['ledger_run_id']}")
                store.conn.execute("UPDATE fast_path_late_revisions SET status = 'answering', answer_run_id = ?, updated_at = ?"
                                   " WHERE id = ?", (run["id"], ts, row["id"]))
            elif row["status"] == "answering":
                status = store.run(row["answer_run_id"])["status"]
                finish(store, row, "failed" if status != "cancelled" else "skipped", f"answer_run_{status}")


def revision_plan(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    store = flow.store
    saved = store.existing_step(run["id"], REVISION_INPUT)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    row = row_for_run(store, run)
    assert row is not None
    checkpoint(flow, run)
    base = base_plan(store, row)
    fast_answer.check_input(flow, run["id"], base)
    works = outcomes(flow, row)
    check_candidates(flow, row, works, pause_run=run["id"])
    upgrades = {i["work_id"]: i for i in works if i["late_outcome"] == "include" and i["late_asset_id"]}
    excluded = {i["work_id"] for i in works if i["late_outcome"] in ("criterion_not_met", "out_of_scope") and not i["user_priority"]}
    if not upgrades:
        flow._fail(run["id"], "no_fulltext_inclusion")
    patterns = flow._criterion_phrases(run, scope)
    fts = " OR ".join(f'"{term}"' for term in flow._topic_terms(run["research_id"], scope))
    pools = fast_answer.current_pools(store, run["research_id"])
    items = []
    base_work_ids = {i["work_id"] for i in base["items"]}
    rows = copy.deepcopy(base["items"])
    rows += [copy.deepcopy(i) for wid, i in upgrades.items() if wid not in {r["work_id"] for r in rows}]
    for item in rows:
        wid, svid = item["work_id"], item["source_version_id"]
        if wid in excluded:
            continue
        if wid in upgrades:
            upgrade = upgrades[wid]
            ids = [p["id"] for p in pools.get(svid, []) if p["kind"] == "pdf_page" and p["asset_id"] == upgrade["late_asset_id"]]
            pages = [store.passage(pid) for pid in ids]
            topic = [p for p in store.search_passages([svid], fts, len(ids)) if p["id"] in ids]
            criterion = criterion_passages.criterion_order(pages, patterns or [])
            ranked = fuse_rankings(topic, criterion) if criterion else topic
            chosen = list(dict.fromkeys(p["id"] for p in [*ranked, *pages]))[:2 if wid in base_work_ids else 1]
            if not chosen:
                flow._pause(run["id"], "source_changed")
            item |= {"route": "fulltext", "decision_id": upgrade["late_decision_id"], "asset_id": upgrade["late_asset_id"],
                     "fulltext_ids": ids, "abstract_ids": [], "reason": None, "upgraded": True}
        else:
            owned = set(item["abstract_ids"] + item["fulltext_ids"])
            chosen = [pid for pid in base["passage_ids"] if pid in owned]
        item["passage_ids"] = chosen
        items.append(item)
    # Replace each abstract in place; preserve the ordering of all unchanged passages.
    base_owners = {pid: item["work_id"] for item in base["items"] for pid in item["abstract_ids"] + item["fulltext_ids"]}
    chosen_by_work = {item["work_id"]: item["passage_ids"] for item in items}
    passages, replaced = [], set()
    for pid in base["passage_ids"]:
        wid = base_owners[pid]
        if wid in excluded:
            continue
        if wid in upgrades:
            if wid not in replaced:
                passages.extend(chosen_by_work[wid])
                replaced.add(wid)
        else:
            passages.append(pid)
    for wid in upgrades:
        if wid not in base_work_ids:
            passages.extend(chosen_by_work[wid])
    return small_batch.save_code(flow, run, REVISION_INPUT, "code:fast_path_revision_input", lambda: {
        "policy_hash": run["budget"]["fast_path"]["policy_hash"], "base_answer_id": row["base_answer_id"],
        "base_input_step_id": row["base_input_step_id"], "read_run_id": row["read_run_id"], "scope_revision": run["scope_revision"],
        "base_selection_revision": base["selection_revision"], "selection_revision": store.selection_revision(run["research_id"]),
        "user_signature": base["user_signature"], "items": items, "upgraded": list(upgrades), "late_excluded": sorted(excluded),
        "passage_ids": passages, "limit": len(base["passage_ids"]) + len(upgrades), "breadth": len(items)})


def published(store: Any, run: dict[str, Any], aid: str, status: str) -> None:
    row = row_for_run(store, run)
    if row is None:
        return
    if status != "structurally_valid":
        store.conn.execute("UPDATE fast_path_late_revisions SET revision_answer_id = ? WHERE id = ?",
                           (aid, row["id"]))
        finish(store, row, "failed", "revision_unverified")
        return
    ts = fast_path.timestamp(store.clock)
    store.conn.execute("UPDATE fast_path_late_revisions SET status = 'published', revision_answer_id = ?,"
                       " published_at = ?, updated_at = ? WHERE id = ? AND status = 'answering'", (aid, ts, ts, row["id"]))
    store._event(row["research_id"], "late_revision_published", {"answer_id": aid, "base_answer_id": row["base_answer_id"]}, run["id"])


def answer_view(store: Any, aid: str) -> dict[str, Any]:
    if not available(store):
        return {}
    row = store.conn.execute("SELECT * FROM fast_path_late_revisions WHERE base_answer_id = ? OR revision_answer_id = ?", (aid, aid)).fetchone()
    if not row:
        return {}
    if row["base_answer_id"] == aid:
        excluded = sum(i.get("late_outcome") in ("criterion_not_met", "out_of_scope") and not i["user_priority"]
                       for i in json.loads(row["works_json"]))
        return {"late_revision_status": {"status": row["status"], "skip_reason": row["skip_reason"],
                "revision_answer_id": row["revision_answer_id"], "late_excluded": excluded}}
    plan = store.existing_step(row["answer_run_id"], REVISION_INPUT)["output"]
    version = store.conn.execute("SELECT report_version FROM answers WHERE id = ?", (row["base_answer_id"],)).fetchone()[0]
    return {"late_revision": {"kind": "updated_with_full_text", "base_answer_id": row["base_answer_id"],
            "base_report_version": version, "upgraded_sources": len(plan["upgraded"]), "late_excluded": len(plan["late_excluded"])}}

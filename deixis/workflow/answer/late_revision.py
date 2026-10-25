"""D255: one append-only answer revision from cutoff-selected late full text."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from deixis.storage.db import dumps, new_id, transaction
from deixis.workflow.read import adjudication
from deixis.workflow.answer import criterion_passages, answer as fast_answer, result_passages
from deixis.workflow.run import fast_path
from deixis.workflow.search import small_batch
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.run.flow import fuse_rankings

log = logging.getLogger("deixis.late_revision")
_failures: dict[tuple[str, str], tuple[str, str]] = {}  # (operation, row id) -> the failure last logged for it
REVISION_INPUT = "fast_path:v1:revision_input"
OPEN = ("waiting_fetch", "reading", "answering")
# Full-text pages an upgraded work brings. A work already in the base answer replaces its abstract passage with two
# pages and a new work adds one, so each upgrade grows the input by about one passage (the plan's `limit`).
BASE_WORK_PAGES = 2
NEW_WORK_PAGES = 1


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


def held(store: Any, row: dict[str, Any]) -> bool:
    """Whether withdrawing the newer question revisions one after another (D67) may still bring the research back to
    this row's revision: each one from the current one down was opened from the next and is unused. Then the row waits
    with no event: withdrawn, the research is back on the row's revision and the row goes on; once work is done under
    any of them it is skipped for `scope_revised`. While a run of the research is active or paused that is not known
    yet, so the row waits too. Only the sweep asks this; a late run that is running stops at its checkpoint."""
    current = store.conn.execute(
        "SELECT s.revision FROM researches r JOIN scope_revisions s ON s.research_id = r.id"
        " AND s.revision = r.current_scope_revision WHERE r.id = ?", (row["research_id"],)).fetchone()
    if not current:
        return False
    revision, after = current[0], ()
    while revision > row["scope_revision"]:  # a revision is always opened from a lower one
        check = store.withdrawal(row["research_id"], revision, after)
        if check["reason"] == "run_active":
            return True
        if not check["allowed"]:
            return False
        revision, after = check["parent_revision"], (*after, revision)
    return revision == row["scope_revision"]


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
        from deixis.workflow.run.flow import RunStopped
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
    # A work admitted to a full-text slot from the abstract stage's unresolved route has no abstract to answer from,
    # so it was never in the base answer; its text arriving after the cutoff is read like a candidate's (D60).
    waiting = ("no_text_at_cutoff", fast_answer.UNRESOLVED_WITHOUT_FULLTEXT)
    candidates = [copy.deepcopy(base_items.get(i["work_id"], i)) for i in cutoff["output"]["items"]
                  if i["work_id"] in selected and not i["fulltext_decision_id"]
                  and i["route"] == "abstract" and i["reason"] in (None, *waiting)
                  and (i["work_id"] in base_items or i["reason"] in waiting)]
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
                              "late_decision_id": decision["id"] if decision else None, "late_asset_id": asset,
                              "late_reason": decision["reason_code"] if decision else None,
                              "late_decided_by": decision["decided_by"] if decision else None})
    return result


def is_late_closest(item: dict[str, Any]) -> bool:
    """A late reading of the file that did not include the work: it makes a closest work, not an exclusion (D137).
    A row saved before D137 carries no reading code and stays what it was."""
    return fast_answer.is_closest({"decided_by": item.get("late_decided_by"), "reason_code": item.get("late_reason")},
                                  item.get("late_asset_id"))


def late_items(store: Any, rid: str, scope_revision: int) -> list[dict[str, Any]]:
    return [i for r in store.conn.execute(
                "SELECT works_json FROM fast_path_late_revisions WHERE research_id = ? AND scope_revision = ?"
                " AND read_run_id IS NOT NULL", (rid, scope_revision))
            for i in json.loads(r[0])]


def excluded_works(store: Any, rid: str, scope_revision: int) -> set[str]:
    """Works the late full-text read found not to meet the criterion or out of scope (unless the person put them
    first). A later answer must not read them from their abstract again."""
    if not available(store):
        return set()
    return {i["work_id"] for i in late_items(store, rid, scope_revision)
            if i.get("late_outcome") in ("criterion_not_met", "out_of_scope") and not i["user_priority"]
            and not is_late_closest(i)}


def closest_works(store: Any, rid: str, scope_revision: int) -> dict[str, dict[str, Any]]:
    """Works a late reading read without including them, by work: a later answer reads them as closest works (D137)."""
    if not available(store):
        return {}
    return {i["work_id"]: i for i in late_items(store, rid, scope_revision)
            if is_late_closest(i) and not i["user_priority"]}


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
        failure = None
        try:
            with transaction(store.conn):
                reason = guard_reason(store, row)
                if reason == "scope_revised" and held(store, row):
                    continue
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
                    # A late read reads by its discovery's rule; a discovery queued before the rule existed keeps the old
                    # one (D76).
                    budget.pop("read_rule", None)
                    if rule := (store.run(row["ledger_run_id"])["budget"] or {}).get("read_rule"):
                        budget["read_rule"] = rule
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
                    if not upgrades_of(works, base_plan(store, row),
                                       fast_answer.TEST_EFFORT_BUDGETS[scope["effort"]].max_answer_passages):
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
        except Exception as exc:  # noqa: BLE001 - one row must not hold up the worker, its queue or the other rows
            # The worker sweeps every turn: the same failure of a row is logged once, a different one again.
            failure = (type(exc).__name__, str(exc))
            if _failures.get(("advance", row["id"])) != failure:
                log.exception("advancing late revision %s failed", row["id"])
        finally:  # also after a `continue`
            if failure:
                _failures[("advance", row["id"])] = failure
            else:
                _failures.pop(("advance", row["id"]), None)


def upgrades_of(works: list[dict[str, Any]], base: dict[str, Any] | None, passages: int) -> dict[str, dict[str, Any]]:
    """The late readings a revision reads in full: every inclusion, and the works read without inclusion as closest
    works while the base answer has closest places left by its budget (`passages`, D137)."""
    upgrades = {i["work_id"]: i for i in works if i["late_outcome"] == "include" and i["late_asset_id"]}
    if base is not None:
        room = (fast_answer.CLOSEST_WORKS.get(passages, fast_answer.CLOSEST_WORKS[48])
                - sum(fast_answer.role_of(i) == "closest" for i in base["items"]))
        closest = [i for i in works if is_late_closest(i) and i["work_id"] not in upgrades]
        upgrades |= {i["work_id"]: i for i in closest[:max(0, room)]}
    return upgrades


def revision_plan(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    store = flow.store
    saved = store.existing_step(run["id"], REVISION_INPUT)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    row = row_for_run(store, run)
    if row is None:
        flow._fail(run["id"], "late_revision_unavailable")
    checkpoint(flow, run)
    base = base_plan(store, row)
    fast_answer.check_input(flow, run["id"], base)
    works = outcomes(flow, row)
    check_candidates(flow, row, works, pause_run=run["id"])
    upgrades = upgrades_of(works, base, run["budget"]["max_answer_passages"])
    excluded = {i["work_id"] for i in works if i["late_outcome"] in ("criterion_not_met", "out_of_scope")
                and not i["user_priority"] and i["work_id"] not in upgrades}
    if not upgrades:
        flow._fail(run["id"], "no_fulltext_inclusion")
    patterns = flow._criterion_phrases(run, scope)
    # A revision follows its base answer's rule; a base input from before D56 has none, so it is decided here.
    formula_rule = base.get("formula_passages") or fast_answer.formula_request(store, scope, patterns)
    formulas = formula_rule["on"]
    # The same for outcome terms: a base input from before D84 has no record, so the research's terms are read here.
    result_rule = {k: v for k, v in (base.get("result_passages") or fast_answer.result_request(store, scope)).items() if k != "moved"}
    outcome_patterns = result_passages.compile_terms(result_rule["outcome_terms"])
    moved = 0
    fts = " OR ".join(f'"{term}"' for term in flow._topic_terms(run["research_id"], scope))
    pools = fast_answer.current_pools(store, run["research_id"])
    items = []
    base_work_ids = {i["work_id"] for i in base["items"]}
    # A closest work a revision reads in full uses only the room the base answer's budget left (D137): the abstract
    # it replaces, and what the frozen 16/48/80 budget has free. A closest work new to the answer needs that room.
    room = max(0, run["budget"]["max_answer_passages"] - len(base["passage_ids"]))
    for wid in [w for w, i in upgrades.items() if i["late_outcome"] != "include" and w not in base_work_ids]:
        if room:
            room -= 1
        else:
            del upgrades[wid]
    if not upgrades:
        flow._fail(run["id"], "no_fulltext_inclusion")
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
            closest = upgrade["late_outcome"] != "include"
            parts, quoted = (fast_answer.closest_parts(store, {"fulltext_decision_id": upgrade["late_decision_id"],
                                                               "source_version_id": svid}) if closest else ([], []))
            ordered = list({p["id"]: p for p in [*ranked, *pages]}.values())
            ordered, first = result_passages.order(ordered, outcome_patterns, formulas)
            moved += first
            count = BASE_WORK_PAGES if wid in base_work_ids else NEW_WORK_PAGES
            if closest:
                # Its quoted pages first (D137), and no more pages than the budget has room for.
                cited = [pid for pid in quoted if pid in ids]
                ordered = [store.passage(pid) for pid in cited] + [p for p in ordered if p["id"] not in cited]
                if wid in base_work_ids:
                    extra = min(room, count - 1)
                    room -= extra
                    count = 1 + extra
            chosen = [p["id"] for p in ordered][:count]
            if not chosen:
                flow._pause(run["id"], "source_changed")
            item |= {"route": "fulltext", "decision_id": upgrade["late_decision_id"], "asset_id": upgrade["late_asset_id"],
                     "fulltext_ids": ids, "abstract_ids": [], "reason": None, "upgraded": True,
                     "answer_role": "closest" if closest else "included", **({"criterion_parts": parts} if closest else {})}
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
        "passage_ids": passages, "limit": len(base["passage_ids"]) + len(upgrades), "breadth": len(items),
        "formula_passages": formula_rule, "result_passages": {**result_rule, "moved": moved}})


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
                       and not is_late_closest(i) for i in json.loads(row["works_json"]))
        return {"late_revision_status": {"status": row["status"], "skip_reason": row["skip_reason"],
                "revision_answer_id": row["revision_answer_id"], "late_excluded": excluded}}
    plan = store.existing_step(row["answer_run_id"], REVISION_INPUT)["output"]
    version = store.conn.execute("SELECT report_version FROM answers WHERE id = ?", (row["base_answer_id"],)).fetchone()[0]
    return {"late_revision": {"kind": "updated_with_full_text", "base_answer_id": row["base_answer_id"],
            "base_report_version": version, "upgraded_sources": len(plan["upgraded"]), "late_excluded": len(plan["late_excluded"])}}

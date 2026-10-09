"""D251: one frozen top-N read window with stable top-K work admission."""

from __future__ import annotations

import asyncio
from typing import Any

from deixis.domain.reason_codes import reason
from deixis.storage.db import transaction
from deixis.workflow import background_fetch, fast_path, fulltext, small_batch


def selected(works: list[dict[str, Any]], order: list[str], k: int,
             pending: set[str], baseline: dict[str, Any], without_text: set[str] = frozenset()) -> list[str]:
    """Worst-case pending admission, counting cached text in the same K slots.

    A work whose settled attempt found no text gives its slot to the next eligible work in list order.
    """
    frozen = fulltext.as_of_baseline(works, baseline, pending)
    by_head = {work["head"]: work for work in frozen}
    excluded = set(baseline.get("fulltext_excluded", []))
    wanted = [wid for wid in (by_head[head]["work_id"] for head in order
                              if head in by_head and fulltext.group_of(by_head[head]) is not None)
              if wid not in excluded and wid not in without_text][:k]
    return [wid for wid in wanted if wid not in pending]


def without_text(policy: dict[str, Any], claims: dict[str, Any]) -> set[str]:
    """Claimed works whose attempt settled without text (no file, an unreadable file, or no answer); empty for
    policies frozen before slot refill.

    Read from the settled claim alone, so a release is permanent: text that reaches the work later does not take
    its slot back from the work admitted in its place.
    """
    if not policy.get("slot_refill"):
        return set()
    return {wid for wid, claim in claims.items() if claim["status"] in ("succeeded", "failed")
            and (claim.get("output") or {}).get("code") != fulltext.settled_code({"has_text": True})}


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                  listing: dict[str, Any], *, read_versions: dict[str, Any] | None = None) -> None:
    from deixis.workflow.flow import _Held, RunStopped

    store, rid, run_id = flow.store, run["research_id"], run["id"]
    policy = run["budget"]["fast_path"]
    fetch_allowed = run["budget"]["inspection"]["fetch_limit"] > 0
    read_allowed = run["budget"]["inspection"]["read_limit"] > 0
    key = f"small_batch:v1:{listing['manifest_hash']}:fast"
    close_key = f"{key}:close"
    prior = store.existing_step(run_id, close_key)
    if prior and prior["status"] == "succeeded":
        return
    plan = small_batch.save_code(flow, run, f"{key}:plan", "code:small_batch_plan", lambda:
        small_batch.next_batch(listing, 0, policy["N"]) | {"N": policy["N"], "K": policy["K"],
                                                        "policy_hash": policy["policy_hash"]})
    order = small_batch.unchanged_heads(store, rid, listing, plan["items"],
                                       **({"versions": read_versions} if read_versions is not None else {}))
    frozen = read_versions if read_versions is not None else listing["manifest"]["versions"]
    flow._small_batch_guard = {"run_id": run_id, "rid": rid,
        "user_signature": small_batch.user_signature(store, rid), "reserved_calls": set(),
        "versions": {svid: frozen[svid] for item in plan["items"]
                     if item["head"] in order for svid in item["versions"]}}
    held = flow._held[run_id] = _Held(run["scope_revision"])
    fetches: dict[str, asyncio.Task] = {}
    reads: dict[str, asyncio.Task] = {}
    model: asyncio.Task | None = None
    timer: asyncio.Task | None = None
    handed_off: set[str] = set()
    cutoff = lambda: fast_path.past_deadline(store, run, "read")

    def corpus() -> list[dict[str, Any]]:
        return [work for work in flow._fulltext_works(rid) if work["head"] in order]

    async def fetch(wid: str) -> None:
        async with flow.deps.fetch_slots.slot():
            # The slot may have queued across the deadline. Leave the claim pending.
            if cutoff():
                return
            flow._checkpoint(run_id, run["scope_revision"])
            await flow._overlap_work(run, wid)
        held.wake.set()

    async def abstracts() -> None:
        await flow._abstract_stage(run, scope, vocabulary, order=order, batch_key=key,
                                   read_limit=policy["N"], cutoff=cutoff)
        held.model_done = True
        held.wake.set()

    async def alarm() -> None:
        deadline = fast_path.stage_deadline(store, run, "read")
        if deadline is None:
            return
        await store.clock.sleep(max(0, (deadline - store.clock.now()).total_seconds()))
        held.wake.set()

    try:
        abstract_plan = flow._abstract_code_stage(run, scope, vocabulary, order,
                                                  batch_key=key, read_limit=policy["N"])
        def baseline_snapshot() -> dict[str, Any]:
            works = corpus()
            excluded = []
            for work in works:
                decision = fulltext.current_fulltext(work)
                selection = work.get("selection") or {}
                if (decision and not decision.get("stale") and reason(decision["reason_code"]).outcome == "criterion_not_met"
                        and not (selection.get("origin") == "user" and selection.get("state") == "included")):
                    excluded.append(work["work_id"])
            return fulltext.baseline_of(works, scope_revision=run["scope_revision"], limit=policy["K"],
                                       fulltext_excluded=sorted(excluded))
        baseline = small_batch.save_code(flow, run, f"{key}:baseline", "code:small_batch_baseline", baseline_snapshot)
        prefix = f"{key}:abstract_screening"

        def pending() -> set[str]:
            return {wid for n, batch in enumerate(abstract_plan["batches"])
                    if n not in held.closed.get(prefix, set()) and not held.model_done
                    for wid in store.work_ids(batch).values()}

        model = asyncio.create_task(abstracts())
        timer = asyncio.create_task(alarm())
        while True:
            flow._checkpoint(run_id, run["scope_revision"])
            if model.done():
                model.result()
            for task in list(fetches.values()) + list(reads.values()):
                if task.done():
                    task.result()
            if cutoff():
                break
            works = corpus()
            claims = flow._claims(run_id)
            released = without_text(policy, claims)
            safe = selected(works, order, policy["K"], pending(), baseline, released)
            background_wids = {row["work_id"] for row in store.conn.execute(
                "SELECT work_id FROM fast_path_background_fetches WHERE run_id = ?"
                " AND status IN ('queued', 'running')", (run_id,))}
            # Resume retains admission even when retrieval/reading changed current decisions.
            admitted = [wid for wid in dict.fromkeys([wid for wid in plan["work_ids"] if wid in claims] + safe)
                        if wid not in background_wids and wid not in released]
            by_work = {work["work_id"]: work for work in works}
            for wid in admitted:
                if cutoff():
                    break
                work = by_work.get(wid)
                if not work:
                    continue
                has_text = any(v["has_text"] for v in work["versions"])
                if (fetch_allowed and not has_text and wid not in fetches
                        and (wid not in claims or claims[wid]["status"] not in ("succeeded", "failed"))):
                    # Claims are bounded by K, independently of task completion order; with slot refill, by the N
                    # screened works in list order.
                    if wid not in claims:
                        flow._claim(run_id, wid, not held.model_done, "fast_path")
                    fetches[wid] = asyncio.create_task(fetch(wid))
                if read_allowed and has_text and wid not in reads and not cutoff():
                    reads[wid] = asyncio.create_task(flow._fulltext_adjudication(
                        run, scope, batch_key=f"{key}:read:{wid}", order=[work["head"]], read_limit=1, cutoff=cutoff))
            active = {task for task in [model, *fetches.values(), *reads.values()] if not task.done()}
            if not active:
                break
            waiter = asyncio.create_task(held.wake.wait())
            try:
                await asyncio.wait(active | {waiter}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
                held.wake.clear()

        # Only model calls drain here. Fetch tasks stay owned until closure and queue publish atomically.
        await asyncio.gather(model, *reads.values())
        flow._checkpoint(run_id, run["scope_revision"])
        works = corpus()
        unread = {wid for n, batch in enumerate(abstract_plan["batches"])
                  if n not in held.closed.get(prefix, set()) for wid in store.work_ids(batch).values()}
        claims = flow._claims(run_id)
        empty = without_text(policy, claims)
        final = selected(works, order, policy["K"], set(), baseline, empty)
        # Paid-for claims cannot lose a slot after their full-text result arrives.
        final = list(dict.fromkeys([wid for wid in plan["work_ids"] if wid in claims and wid not in empty] + final))
        items = {item["work_id"]: item for item in plan["items"]}
        by_work = {work["work_id"]: work for work in works}
        late = {wid: ("in_flight" if wid in fetches and not fetches[wid].done() else "not_started")
                for wid in final if wid in by_work and not any(v["has_text"] for v in by_work[wid]["versions"])
                and fetch_allowed
                and (wid not in claims or claims[wid]["status"] not in ("succeeded", "failed"))}
        # A task in extraction may have published text but not settled its claim yet.
        late.update({wid: "in_flight" for wid, task in fetches.items() if not task.done()})
        deadline = fast_path.stage_deadline(store, run, "read")
        cutoff_snapshot = None
        cutoff_at = None
        if fast_path.enforces(run["budget"], "answer"):
            from deixis.workflow import fast_answer
            cutoff_at = fast_path.timestamp(store.clock)
            # Synchronous preparation cannot interleave with model/fetch/API writes. Only publication holds a transaction.
            cutoff_snapshot = fast_answer.cutoff_snapshot(flow, run, listing, {
                "read_cutoff_at": cutoff_at, "not_screened_at_cutoff": sorted(unread)})

        def close() -> dict[str, Any]:
            states = small_batch.progress_view(listing, small_batch.steps(store, run_id), works)["items"]
            closed_items = []
            for state in states:
                wid = state["work_id"]
                if wid not in items:
                    continue
                if state["head"] not in order:
                    state = small_batch.work_state(items[wid], None)
                closed_items.append(state | {"cutoff": "not_screened_at_cutoff" if wid in unread else
                    {"fulltext_after_cutoff": late[wid]} if wid in late else None})
            for wid, origin in late.items():
                background_fetch.enqueue(store, run, items[wid], origin)
            output = {"batch_hash": plan["hash"], "items": closed_items, "N": policy["N"], "K": policy["K"],
                "deadline_at": deadline.isoformat() if deadline else None,
                "read_cutoff_at": cutoff_at or fast_path.timestamp(store.clock), "k_selected": len(final),
                "selected_work_ids": final, "not_screened_at_cutoff": sorted(unread),
                **({"attempted_without_text": sorted(empty)} if policy.get("slot_refill") else {}),
                "screened_count": sum(item["head"] in order and item["work_id"] not in unread for item in closed_items),
                "fulltext_adjudicated_before_cutoff": sum(item["fulltext_adjudicated"] for item in closed_items),
                "fulltext_after_cutoff": late,
                "k_short_reason": ("not_screened_at_cutoff" if unread else "screened_out")
                    if len(final) < policy["K"] else None}
            store._event(rid, "read_cutoff", output, run_id)
            if fast_path.enforces(run["budget"], "answer"):
                from deixis.workflow import fast_answer
                fast_answer.freeze_cutoff(flow, run, listing, output, snapshot=cutoff_snapshot)
            fast_path.close_stage(store, run_id, "read")
            return output

        # save_code's nested transaction joins this publication, including the stage closure.
        with transaction(store.conn):
            small_batch.save_code(flow, run, close_key, "code:small_batch_close", close)
        for wid in late:
            if wid in fetches and not fetches[wid].done():
                flow.background_fetch.adopt(run, wid, fetches[wid])
                handed_off.add(wid)
        flow.background_fetch.wake()
    except BaseException as error:
        held.halted = True
        held.wake.set()
        results = await asyncio.gather(*(task for task in [model, *reads.values(), *fetches.values()]
                                         if task is not None), return_exceptions=True)
        if held.stop:
            kind, why, detail = held.stop
            del flow._held[run_id]
            (flow._fail if kind == "fail" else flow._pause)(run_id, why, detail)
        if isinstance(error, RunStopped) or any(isinstance(result, RunStopped) for result in results):
            flow._held.pop(run_id, None)
            flow._checkpoint(run_id, run["scope_revision"])
        raise
    finally:
        if timer is not None:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        flow._held.pop(run_id, None)
        flow._small_batch_guard = None
        await asyncio.gather(*(task for wid, task in fetches.items() if wid not in handed_off), return_exceptions=True)
    small_batch.save_code(flow, run, "small_batch:v1:summary", "code:small_batch_summary", lambda:
        small_batch.progress_view(listing, small_batch.steps(store, run_id), flow._fulltext_works(rid)))


def view(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    if not fast_path.enforces(run["budget"], "read"):
        return None
    steps = small_batch.steps(store, run["id"])
    closure = next((s["output"] for s in steps if s["operation_key"].endswith(":fast:close")
                    and s["status"] == "succeeded"), None)
    rows = [dict(row) for row in store.conn.execute(
        "SELECT * FROM fast_path_background_fetches WHERE run_id = ? ORDER BY position", (run["id"],))]
    return {"N": run["budget"]["fast_path"]["N"], "K": run["budget"]["fast_path"]["K"],
            "cutoff": closure, "background_fetches": rows,
            "background_counts": {status: sum(row["status"] == status for row in rows)
                                  for status in ("queued", "running", "succeeded", "failed", "cancelled")}}

"""D251: one frozen top-N read window with stable top-K work admission."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

from deixis.domain import canonical
from deixis.domain.reason_codes import reason
from deixis.storage.db import transaction
from deixis.workflow.screen import abstract_stage
from deixis.workflow.read import adjudication, background_fetch, fulltext
from deixis.workflow.run import fast_path
from deixis.workflow.search import small_batch

log = logging.getLogger("deixis.fast_read")


def selected(works: list[dict[str, Any]], order: list[str], k: int,
             pending: set[str], baseline: dict[str, Any], without_text: set[str] = frozenset(),
             unresolved_last: bool = False) -> list[str]:
    """Worst-case pending admission, counting cached text in the same K slots.

    A work whose settled attempt found no text gives its slot to the next eligible work in list order. With
    `unresolved_last` (a policy frozen with `admission_order`, D155) the works the abstract stage left unresolved
    (`abstract_not_found`, `runs_agree_unresolved`) come after every other eligible work, as `fulltext.GROUPS` orders
    them, so a work with no abstract does not take a fetch slot ahead of a candidate; the person's works stay first.
    A chained work counts by its abstract outcome too, not by its `chain` group.
    """
    frozen = fulltext.as_of_baseline(works, baseline, pending)
    by_head = {work["head"]: work for work in frozen}
    excluded = set(baseline.get("fulltext_excluded", []))
    eligible = [head for head in order if head in by_head and fulltext.group_of(by_head[head]) is not None]
    if unresolved_last:
        eligible.sort(key=lambda head: _unresolved(by_head[head]))
    wanted = [wid for wid in (by_head[head]["work_id"] for head in eligible)
              if wid not in excluded and wid not in without_text][:k]
    return [wid for wid in wanted if wid not in pending]


def _unresolved(work: dict[str, Any]) -> bool:
    """Whether the abstract stage left this work unresolved, whatever its group (a chained one included)."""
    if (work.get("selection") or {}).get("origin") == "user":
        return False
    abstract = fulltext.abstract_outcome(work)
    return abstract is not None and fulltext.reason(abstract["reason_code"]).outcome == "unresolved"


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


def identity_unconfirmed(store: Any, policy: dict[str, Any], run_id: str, key: str,
                         baseline: dict[str, Any]) -> set[str]:
    """Works whose PDF is not confirmed as the work's own (`pdf_identity_unconfirmed`, no model call); empty for
    policies frozen before slot refill (D60).

    Read from each work's frozen reading plan in this run, and from the baseline for a work an earlier run already
    decided so (its reading plan here skips it), so the release is as permanent as `without_text`'s: the work gives
    its slot to the next eligible work and is not counted as read.
    """
    if not policy.get("slot_refill"):
        return set()
    prefix, suffix = f"{key}:read:", ":adjudication_plan"
    return set(baseline.get("identity_unconfirmed", [])) | {
        row["operation_key"][len(prefix):-len(suffix)] for row in store.conn.execute(
            "SELECT operation_key, output_json FROM run_steps WHERE run_id = ? AND kind = 'code:adjudication_plan'"
            " AND status = 'succeeded' AND operation_key LIKE ?", (run_id, f"{prefix}%{suffix}"))
        if (json.loads(row["output_json"] or "{}")).get("identity_unconfirmed")}


def budget_skipped(batches: list[list[str]], stops: list[dict[str, Any]], work_of: dict[str, str],
                   unread: set[str]) -> set[str]:
    """The unscreened works the model-call budget left, not the deadline (D60): every work of the batches from the
    earliest stored stop on that the closure still counts unscreened. Read from the frozen batches, not a stop's own
    record list, so a person's decision taken back after a stop does not turn its work into a deadline cut."""
    if not stops:
        return set()
    start = min(stop["from_batch"] for stop in stops)
    return {work_of[svid] for batch in batches[start:] for svid in batch if svid in work_of} & unread


def screening_counts(works: list[dict[str, Any]], window: set[str]) -> dict[str, int]:
    """What decided each screened work of the read window (D60), so the six counts add up to `screened_count`: a
    person (their selection, or their decision at either stage, `person_decided_count`), both model runs (`model_screened_count`),
    an invalid model answer (`model_output_invalid_count`), a missing abstract (`no_abstract_count`), a code rule
    (`code_decided_count`), or nothing yet (`undecided_count`: no abstract decision, or `abstract_not_read`)."""
    counts = dict.fromkeys(("person_decided_count", "model_screened_count", "model_output_invalid_count",
                            "no_abstract_count", "code_decided_count", "undecided_count"), 0)
    seen = {work["work_id"]: work for work in works}
    for wid in window:
        work = seen.get(wid)
        decision = fulltext.abstract_outcome(work) if work else None
        code = decision["reason_code"] if decision else None
        selection = (work or {}).get("selection") or {}
        person = bool(work) and (selection.get("origin") == "user" or fulltext.decided_by_human(work, "abstract")
                                 or fulltext.decided_by_human(work, "fulltext"))
        counts["person_decided_count" if person else
               "undecided_count" if code in (None, "abstract_not_read") else
               "model_screened_count" if code in abstract_stage.MODEL_CODES else
               "model_output_invalid_count" if code == "abstract_not_proposed" else
               "no_abstract_count" if code in ("no_abstract", "abstract_not_found") else
               "code_decided_count"] += 1
    return counts


def deep_plan(listing: dict[str, Any], deep: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """D173: the frozen list's places `first`..`last`, the deeper screening's window, as one plan record."""
    items = listing["items"][deep["first"] - 1:deep["last"]]
    body = {"number": "deep", "rule": deep["rule"], "first": deep["first"], "last": deep["last"],
            "manifest_hash": listing["manifest_hash"], "order_hash": listing["order_hash"], "items": items,
            "work_ids": [item["work_id"] for item in items], "order": [item["head"] for item in items],
            "policy_hash": policy["policy_hash"]}
    return body | {"hash": canonical.sha256_hex(body)}


def deep_closure(flow: Any, run: dict[str, Any], listing: dict[str, Any], deep: dict[str, Any],
                 state: dict[str, Any], closed: set[int]) -> dict[str, Any]:
    """What the deeper screening (D173) did by the cutoff, for the closure's `deep` record and the snapshot.

    Every work of the frozen list's places `first`..`last` is exactly one of: decided by a person; screened by a deep
    batch this run closed; settled by this run's deep code stage (its head unchanged, in no batch, and holding a
    current abstract decision); or unscreened at the cutoff. Whatever this run cannot show is unscreened, so it stays out
    of the answer whatever older decision it holds: every work when the deep plan or code stage never ran before the
    cutoff, a work whose head changed since the list froze (also listed in `dropped_heads`), and a work of a batch the
    cutoff or the model-call budget left open. Work ids are the listing's, as the snapshot's rows carry them."""
    from deixis.workflow.run.flow import budget_stops
    from deixis.workflow.screen.decisions import DecisionStore

    store, rid, run_id = flow.store, run["research_id"], run["id"]
    window = listing["items"][deep["first"] - 1:deep["last"]]
    works = [item["work_id"] for item in window]
    item_of = {svid: item["work_id"] for item in window for svid in item["versions"]}
    decided_now = flow._human_decided_records(rid, list(item_of))
    person = {item_of[svid] for svid in decided_now}
    order, abstract_plan, prefix = state.get("order"), state.get("abstract_plan"), state["prefix"]
    dropped = [item["head"] for item in window if order is not None and item["head"] not in order]
    batches = abstract_plan["batches"] if abstract_plan is not None else []
    current = store.work_ids([svid for batch in batches for svid in batch])
    work_of = {svid: item_of.get(svid, current.get(svid)) for batch in batches for svid in batch}
    screened: set[str] = set()
    settled: set[str] = set()
    if abstract_plan is not None and order is not None:
        screened = {work_of[svid] for n, batch in enumerate(batches) if n in closed for svid in batch} - person
        in_batch = set(work_of.values())
        decisions = DecisionStore(store)
        key = decisions.staleness_key(rid)
        for item in window:
            wid = item["work_id"]
            if wid in person or wid in in_batch or item["head"] not in order:
                continue
            if any((held := decisions.current(rid, svid, "abstract")) is not None and not decisions.is_stale(held, key)
                   for svid in item["versions"]):
                settled.add(wid)
    unread = set(works) - person - screened - settled
    budget_cut = budget_skipped(batches, budget_stops(store, run_id, prefix), work_of, unread) if batches else set()
    calls = store.conn.execute(
        "SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND kind = 'model:abstract_screening' AND operation_key LIKE ?"
        " AND (status = 'succeeded' OR error_code = 'invalid_model_output')", (run_id, f"{prefix}:%")).fetchone()[0]
    return {"rule": deep["rule"], "first": deep["first"], "last": deep["last"], "planned": len(works),
            "plan_opened": state.get("plan") is not None, "code_stage_ran": abstract_plan is not None,
            "dropped_heads": dropped, "screened_count": len(works) - len(unread),
            "screened_by_model_count": len(screened), "code_settled_count": len(settled),
            "person_decided_count": len(person & set(works)),
            "not_screened_at_cutoff": sorted(unread), "not_screened_model_budget": sorted(budget_cut),
            "model_calls": calls}


def _stop_asked(store: Any, run: dict[str, Any]) -> bool:
    """Whether a stop was asked of the run itself (a pause, a cancel, a newer question revision), not just the halt
    one arm's error puts on the others."""
    return (store.run(run["id"])["status"] in ("pause_requested", "cancelled", "paused", "failed")
            or store.research(run["research_id"])["current_scope_revision"] != run["scope_revision"])


async def _unwind(flow: Any, run: dict[str, Any], held: Any, error: BaseException, tasks: list[asyncio.Task]) -> None:
    """End the read window after `error` in one of its arms or in the coordinator. Always raises.

    The other arms are halted and drained first; their checkpoints read the halt as a stop while the run is held.
    Then the hold is dropped, and the run's own stop is written: a pause or failure an arm asked for, else the
    error. An unexpected error in one arm halts the others, whose checkpoint then reads as a stop: the error, not
    that stop, ends the run, so the worker records it as a failure instead of leaving the run `running`. A pause,
    cancel or new question revision the person asked for still wins: the run stops as asked, and the error is
    logged rather than turning that stop into a failure.
    """
    from deixis.workflow.run.flow import RunStopped

    store, run_id = flow.store, run["id"]
    held.halted = True
    held.wake.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    flow._held.pop(run_id, None)
    if held.stop:
        kind, why, detail = held.stop
        (flow._fail if kind == "fail" else flow._pause)(run_id, why, detail)
    failure = next((r for r in [error, *results] if isinstance(r, Exception) and not isinstance(r, RunStopped)), None)
    if failure is not None:
        if not _stop_asked(store, run):
            raise failure
        log.error("run %s: error in the read window while a stop was asked; the stop stands", run_id,
                  exc_info=(type(failure), failure, failure.__traceback__))
        flow._checkpoint(run_id, run["scope_revision"])  # writes the asked-for stop and raises RunStopped
    if isinstance(error, RunStopped) or any(isinstance(result, RunStopped) for result in results):
        flow._checkpoint(run_id, run["scope_revision"])
    raise error


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                  listing: dict[str, Any], *, read_versions: dict[str, Any] | None = None) -> None:
    from deixis.workflow.run.flow import _Held, RunStopped

    store, rid, run_id = flow.store, run["research_id"], run["id"]
    policy = run["budget"]["fast_path"]
    last = policy.get("admission_order") == "unresolved_last"  # D155; a policy frozen without it keeps list order
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
    # No user signature: a person's decision during the read does not pause the run. Each send and each write
    # rechecks it (slice 16), so the run goes on and leaves the decided works as the person set them.
    flow._small_batch_guard = {"run_id": run_id, "rid": rid, "reserved_calls": set(),
        "versions": {svid: frozen[svid] for item in plan["items"]
                     if item["head"] in order for svid in item["versions"]}}
    held = flow._held[run_id] = _Held(run["scope_revision"])
    fetches: dict[str, asyncio.Task] = {}
    reads: dict[str, asyncio.Task] = {}
    model: asyncio.Task | None = None
    deeper_task: asyncio.Task | None = None
    timer: asyncio.Task | None = None
    # D173: the deeper screening's window, frozen in the policy; None for every run queued without it.
    deep = fast_path.deep_window(policy)
    deep_key = f"{key}:deep"
    deep_state: dict[str, Any] = {"prefix": f"{deep_key}:abstract_screening"}
    screened = asyncio.Event()  # the top-N screening ended, however: the deep calls go out only after it
    handed_off: set[str] = set()
    cutoff = lambda: fast_path.past_deadline(store, run, "read")

    def send_by() -> Any:
        deadline = fast_path.stage_deadline(store, run, "read")
        return None if deadline is None else deadline + timedelta(milliseconds=policy["read_drain_ms"])

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
        try:
            await flow._abstract_stage(run, scope, vocabulary, order=order, batch_key=key,
                                       read_limit=policy["N"], cutoff=cutoff)
            held.model_done = True
            held.wake.set()
        finally:
            screened.set()

    def may_start(step_key: str) -> bool:
        """No code step starts after the cutoff; one already stored is read back (a resumed run reads its plan)."""
        if not cutoff():
            return True
        step = store.existing_step(run_id, step_key)
        return step is not None and step["status"] == "succeeded"

    async def deeper() -> None:
        """D173: screen the window's works once each, beside the top N and after their screening. K, its order and
        the fetch queue never see these works; only the answer's window reaches them."""
        from deixis.workflow.search.fast_chain import read_versions as freeze_versions
        try:
            if not may_start(f"{deep_key}:plan"):
                return
            dplan = deep_state["plan"] = small_batch.save_code(flow, run, f"{deep_key}:plan", "code:small_batch_plan",
                                                               lambda: deep_plan(listing, deep, policy))
            versions_key = f"{deep_key}:read_versions"
            if not cutoff() and store.existing_step(run_id, versions_key) is None:
                # The window's records without an abstract are looked up as the top N's were before the read.
                await flow._second_sources(run, scope, vocabulary,
                                           only={svid for item in dplan["items"] for svid in item["versions"]},
                                           prefix=f"{deep_key}:", flags_key=f"{deep_key}:record_flags",
                                           works=set(dplan["work_ids"]), stop=cutoff)
            if not may_start(versions_key):
                return
            snapshot = freeze_versions(flow, run, listing, dplan["items"], versions_key)
            dorder = deep_state["order"] = small_batch.unchanged_heads(store, rid, listing, dplan["items"],
                                                                       versions=snapshot["versions"])
            # A deep record that changes from here on stops the run as a top-N one does.
            flow._small_batch_guard["versions"].update({svid: snapshot["versions"][svid] for item in dplan["items"]
                                                        if item["head"] in dorder for svid in item["versions"]})
            stage_key = f"{deep_key}:abstract_stage"
            if not may_start(stage_key):
                return
            deep_state["abstract_plan"] = flow._abstract_code_stage(
                run, scope, vocabulary, dorder, batch_key=deep_key, read_limit=deep["last"] - deep["first"] + 1,
                runs=deep["runs"])
            flow._wake_fetch(run_id)
            await screened.wait()
            flow._checkpoint(run_id, run["scope_revision"])
            # The plan is the stored one (`_abstract_code_stage` reads it back), with its one run per batch.
            await flow._abstract_stage(run, scope, vocabulary, order=dorder, batch_key=deep_key,
                                       read_limit=deep["last"] - deep["first"] + 1, cutoff=cutoff)
        finally:
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
            # An identity failure an earlier run decided keeps its work out of the slots (D60) when the reading would
            # skip the work for it: no other fresh reading on any version, and no person's file waiting to be read.
            unconfirmed = sorted(work["work_id"] for work in works if adjudication.person_version(work) is None
                                 and {row["reason_code"] for version in work["versions"]
                                      if (row := version.get("fulltext")) and not row.get("stale")
                                      and row["reason_code"] in adjudication.FRESH_MODEL_CODES}
                                 == {"pdf_identity_unconfirmed"})
            return fulltext.baseline_of(works, scope_revision=run["scope_revision"], limit=policy["K"],
                                       fulltext_excluded=sorted(excluded),
                                       **({"identity_unconfirmed": unconfirmed} if policy.get("slot_refill") else {}))
        baseline = small_batch.save_code(flow, run, f"{key}:baseline", "code:small_batch_baseline", baseline_snapshot)
        prefix = f"{key}:abstract_screening"

        def pending() -> set[str]:
            return {wid for n, batch in enumerate(abstract_plan["batches"])
                    if n not in held.closed.get(prefix, set()) and not held.model_done
                    for wid in store.work_ids(batch).values()}

        if policy.get("read_drain_ms") is not None:
            flow._send_by[run_id] = send_by
        model = asyncio.create_task(abstracts())
        if deep is not None:
            deeper_task = asyncio.create_task(deeper())
        timer = asyncio.create_task(alarm())
        while True:
            flow._checkpoint(run_id, run["scope_revision"])
            if model.done():
                model.result()
            if deeper_task is not None and deeper_task.done():
                deeper_task.result()
            for task in list(fetches.values()) + list(reads.values()):
                if task.done():
                    task.result()
            if cutoff():
                break
            works = corpus()
            claims = flow._claims(run_id)
            released = without_text(policy, claims) | identity_unconfirmed(store, policy, run_id, key, baseline)
            safe = selected(works, order, policy["K"], pending(), baseline, released, last)
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
                # A claim a stop or crash left open after its text was published is settled too, or its work would
                # never get its code (the attempt finds the stored text and downloads nothing).
                unsettled = wid in claims and claims[wid]["status"] not in ("succeeded", "failed")
                if fetch_allowed and wid not in fetches and (unsettled or (not has_text and wid not in claims)):
                    # Claims are bounded by K, independently of task completion order; with slot refill, by the N
                    # screened works in list order.
                    if wid not in claims:
                        flow._claim(run_id, wid, not held.model_done, "fast_path")
                    fetches[wid] = asyncio.create_task(fetch(wid))
                if read_allowed and has_text and wid not in reads and not cutoff():
                    reads[wid] = asyncio.create_task(flow._fulltext_adjudication(
                        run, scope, batch_key=f"{key}:read:{wid}", order=[work["head"]], read_limit=1, cutoff=cutoff))
            active = {task for task in [model, deeper_task, *fetches.values(), *reads.values()]
                      if task is not None and not task.done()}
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
        # The deep task drains here too: the snapshot and the closure are built only once it finished or stopped.
        await asyncio.gather(model, *([deeper_task] if deeper_task is not None else []), *reads.values())
        flow._checkpoint(run_id, run["scope_revision"])
        works = corpus()
        # A record a person decided is not sent to the model (`_abstract_stage`), so it is not counted unscreened (D60).
        open_batches = [batch for n, batch in enumerate(abstract_plan["batches"]) if n not in held.closed.get(prefix, set())]
        decided = flow._human_decided_records(rid, [svid for batch in open_batches for svid in batch])
        unread = {wid for batch in open_batches for svid, wid in store.work_ids(batch).items() if svid not in decided}
        claims = flow._claims(run_id)
        empty = without_text(policy, claims)
        unconfirmed = identity_unconfirmed(store, policy, run_id, key, baseline) - empty
        released = empty | unconfirmed
        final = selected(works, order, policy["K"], set(), baseline, released, last)
        # Paid-for claims cannot lose a slot after their full-text result arrives.
        final = list(dict.fromkeys([wid for wid in plan["work_ids"] if wid in claims and wid not in released] + final))
        # A release is why K is short only when, without it, the released work would have held one of the K slots.
        short_of_text = bool(set(selected(works, order, policy["K"], set(), baseline, unresolved_last=last)) & released)
        from deixis.workflow.run.flow import budget_stops
        budget_cut = budget_skipped(abstract_plan["batches"], budget_stops(store, run_id, prefix),
                                    {svid: wid for batch in abstract_plan["batches"]
                                     for svid, wid in store.work_ids(batch).items()}, unread)
        items = {item["work_id"]: item for item in plan["items"]}
        by_work = {work["work_id"]: work for work in works}
        late = {wid: ("in_flight" if wid in fetches and not fetches[wid].done() else "not_started")
                for wid in final if wid in by_work and not any(v["has_text"] for v in by_work[wid]["versions"])
                and fetch_allowed
                and (wid not in claims or claims[wid]["status"] not in ("succeeded", "failed"))}
        # A task in extraction may have published text but not settled its claim yet.
        late.update({wid: "in_flight" for wid, task in fetches.items() if not task.done()})
        deadline = fast_path.stage_deadline(store, run, "read")
        deep_record = (deep_closure(flow, run, listing, deep, deep_state, held.closed.get(deep_state["prefix"], set()))
                       if deep is not None else None)
        cutoff_snapshot = None
        cutoff_at = None
        if fast_path.enforces(run["budget"], "answer"):
            from deixis.workflow.answer import answer as fast_answer
            cutoff_at = fast_path.timestamp(store.clock)
            # Synchronous preparation cannot interleave with model/fetch/API writes. Only publication holds a transaction.
            cutoff_snapshot = fast_answer.cutoff_snapshot(flow, run, listing, {
                "read_cutoff_at": cutoff_at, "not_screened_at_cutoff": sorted(unread),
                **({"deep": deep_record} if deep_record is not None else {})})

        def close() -> dict[str, Any]:
            states = small_batch.progress_view(listing, small_batch.steps(store, run_id), works)["items"]
            closed_items = []
            screened = {item["work_id"] for item in items.values()
                        if item["head"] in order and item["work_id"] not in unread}
            for state in states:
                wid = state["work_id"]
                if wid not in items:
                    continue
                if state["head"] not in order:
                    state = small_batch.work_state(items[wid], None)
                closed_items.append(state | {"cutoff": "not_screened_model_budget" if wid in budget_cut else
                    "not_screened_at_cutoff" if wid in unread else
                    {"fulltext_after_cutoff": late[wid]} if wid in late else None})
            for wid, origin in late.items():
                background_fetch.enqueue(store, run, items[wid], origin)
            output = {"batch_hash": plan["hash"], "items": closed_items, "N": policy["N"], "K": policy["K"],
                "deadline_at": deadline.isoformat() if deadline else None,
                "read_cutoff_at": cutoff_at or fast_path.timestamp(store.clock), "k_selected": len(final),
                "selected_work_ids": final,
                # Every window work the read closed on unscreened, whether the deadline or the model-call budget cut
                # it; `not_screened_model_budget` is the budget's part (D60).
                "not_screened_at_cutoff": sorted(unread), "not_screened_model_budget": sorted(budget_cut),
                **({"attempted_without_text": sorted(empty), "identity_unconfirmed": sorted(unconfirmed)}
                   if policy.get("slot_refill") else {}),
                # Window works not left unscreened, whatever decided them; the four counts below say what did (D60).
                "screened_count": len(screened),
                **screening_counts(works, screened),
                "fulltext_adjudicated_before_cutoff": sum(item["fulltext_adjudicated"] for item in closed_items),
                "fulltext_after_cutoff": late,
                "k_short_reason": ("not_screened_at_cutoff" if unread - budget_cut else
                                   "not_screened_model_budget" if budget_cut else
                                   "fulltext_unavailable" if short_of_text else "screened_out")
                    if len(final) < policy["K"] else None,
                # Works already claimed keep their slot when a later decision admits another work ahead of them.
                "k_over_reason": "claimed_works_kept" if len(final) > policy["K"] else None,
                # D173: the deeper window's own record; the fields above keep meaning places 1..N.
                **({"deep": deep_record} if deep_record is not None else {})}
            store._event(rid, "read_cutoff", output, run_id)
            if fast_path.enforces(run["budget"], "answer"):
                from deixis.workflow.answer import answer as fast_answer
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
        await _unwind(flow, run, held, error, [task for task in [model, deeper_task, *reads.values(),
                                                                 *fetches.values()] if task is not None])
    finally:
        if timer is not None:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        flow._held.pop(run_id, None)
        flow._send_by.pop(run_id, None)
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

"""In-process scheduling on the worker's event loop and SQLite connection."""

import asyncio
from datetime import datetime, timedelta
import logging

from deixis.storage.db import new_id
from . import check as policy
from .store import WatchStore, transaction

log = logging.getLogger(__name__)


class WatchScheduler:
    def __init__(self, store, wake, clock=policy.utc_now):
        self.store = store if isinstance(store, WatchStore) else WatchStore(store)
        self.wake, self.clock = wake, clock
        self.previous_tick = None
        self.opening = None
        self.pending = []

    def _detect(self, tick, watches):
        episodes = []
        for watch in watches:
            if not self.store.visible(watch) or not watch["enabled"] or watch["mode"] != "interval":
                continue
            due = policy.due_times(watch["next_due_at"], watch["interval_days"], tick, self.previous_tick)
            if due:
                episodes.append({"watch": watch, **due, "gap_id": new_id("wgp")})
        return {"id": new_id("wop"), "observed_until": policy.timestamp(self.previous_tick) if self.previous_tick else None,
                "noticed_at": policy.timestamp(tick), "episodes": episodes}

    def _account(self):
        opening, store = self.opening, self.store
        pending, recorded, eligible = [], [], []
        with transaction(store.conn):
            for episode in opening["episodes"]:
                old = episode["watch"]
                row = store.conn.execute("SELECT * FROM watches WHERE id=?", (old["id"],)).fetchone()
                current = dict(row) if row else None
                reason = "disabled" if current is None or not current["enabled"] else (
                    "schedule_changed" if current["mode"] != "interval" or current["schedule_version"] != old["schedule_version"] else
                    "next_due_changed" if current["next_due_at"] != old["next_due_at"] else None)
                outcome = "changed_before_record" if reason else None
                if outcome is None:
                    reason = "research_unavailable" if not store.visible(current) else store.waiting_reason(current)
                    if reason:
                        outcome = "not_eligible"
                    elif not current["catch_up"]:
                        outcome = "catch_up_off"
                entry = {"episode": episode, "watch": current, "outcome": outcome, "reason": reason}
                recorded.append(entry)
                if outcome is None:
                    eligible.append(entry)
            eligible.sort(key=lambda e: (e["episode"]["first_missed_due"], e["watch"]["research_id"],
                0 if e["watch"]["kind"] == "protocol_queries" else 1, e["watch"]["id"]))
            researches = set()
            for entry in eligible:
                rid = entry["watch"]["research_id"]
                if rid in researches:
                    entry["outcome"] = "one_per_research"
                else:
                    entry["outcome"] = "catch_up_chosen" if len(researches) < policy.WATCH_CATCH_UP_RESEARCHES else "opening_cap"
                    researches.add(rid)
                if entry["outcome"] == "catch_up_chosen":
                    pending.append(entry)
            for entry in recorded:
                ep, old = entry["episode"], entry["episode"]["watch"]
                due = old["next_due_at"]
                if entry["outcome"] in ("catch_up_off", "opening_cap", "one_per_research"):
                    due = ep["next_due_at"]
                    store.conn.execute("UPDATE watches SET next_due_at=? WHERE id=?", (due, old["id"]))
                elif entry["outcome"] == "changed_before_record":
                    due = entry["watch"]["next_due_at"] if entry["watch"] else None
                gap = {"id": ep["gap_id"], "watch_id": old["id"], "research_id": old["research_id"],
                    "opening_id": opening["id"], **{key: ep[key] for key in ("first_missed_due", "last_missed_due", "missed_periods")},
                    "observed_until": opening["observed_until"], "noticed_at": opening["noticed_at"],
                    "schedule_version": old["schedule_version"], "outcome": entry["outcome"],
                    "outcome_reason": entry["reason"], "next_due_at": policy.timestamp(datetime.fromisoformat(due)) if due else None,
                    "created_at": opening["noticed_at"]}
                store.record_gap(gap)
                entry["gap"] = gap
        # An interrupted accounting attempt cannot leak a choice or advance observation state.
        self.pending.extend({"watch": e["watch"], "gap": e["gap"]} for e in pending)
        return [e["gap"] for e in recorded]

    def _queue(self, watch, ts, gap=None):
        trigger = "catch_up" if gap else "scheduled"
        schedule_gap = gap | {"gap_id": gap["id"]} if gap else None
        schedule = policy.schedule_block(watch, trigger, ts, schedule_gap)
        return self.store.queue_scheduled(watch["id"], trigger,
            policy.timestamp(datetime.fromisoformat(gap["last_missed_due"] if gap else watch["next_due_at"])),
            gap["missed_periods"] if gap else 0,
            schedule, watch["schedule_version"], watch["next_due_at"], ts)

    def tick(self) -> dict:
        tick = self.clock()
        if tick.utcoffset() != timedelta(0):
            raise ValueError("watch scheduler clock must return an aware UTC datetime")
        ts, store = policy.timestamp(tick), self.store
        result = {"recorded": [], "queued": [], "skipped": []}
        watches = store.scheduler_watches()
        if self.opening is None and (self.previous_tick is None or
                (tick - self.previous_tick).total_seconds() > policy.WATCH_GAP_SECONDS):
            self.opening = self._detect(tick, watches)
        if self.opening is not None:
            result["recorded"] = self._account()
            self.opening = None
            watches = store.scheduler_watches()
        self.previous_tick = tick
        blocked = set()
        for choice in list(self.pending):
            outcome = self._queue(choice["watch"], ts, choice["gap"])
            if "skipped" in outcome:
                result["skipped"].append(outcome)
                if outcome["skipped"] == "stale":
                    self.pending.remove(choice)
                else:
                    blocked.add(choice["watch"]["id"])
                continue
            self.pending.remove(choice)
            result["queued"].append(outcome)
            if not outcome["replayed"]:
                self.wake()
            return result
        for watch in watches:
            reason = "research_unavailable" if not store.visible(watch) else (
                "watch_disabled" if not watch["enabled"] else "manual_watch" if watch["mode"] != "interval" else
                "not_due" if not policy.due_times(watch["next_due_at"], watch["interval_days"], tick) else None)
            if reason:
                result["skipped"].append({"watch_id": watch["id"], "reason": reason})
                continue
            if watch["id"] in blocked:
                continue
            outcome = self._queue(watch, ts)
            if "skipped" in outcome:
                result["skipped"].append(outcome)
                continue
            result["queued"].append(outcome)
            if not outcome["replayed"]:
                self.wake()
            break
        return result

    async def run_forever(self, stop_event):
        logged = set()
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                if type(exc) not in logged:
                    log.exception("watch scheduler tick failed; trying again")
                    logged.add(type(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=policy.WATCH_TICK_SECONDS)
            except TimeoutError:
                pass

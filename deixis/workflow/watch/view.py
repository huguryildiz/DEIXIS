"""Read models retain requested windows apart from provider observations."""

import json

from . import check as policy
from .run import observations


def check_view(store, row):
    config = json.loads(row["config_json"])
    reads = store.reads(row)
    observed, statuses = observations(config, reads)
    if row["observed_json"] is not None:
        observed = json.loads(row["observed_json"])
        statuses = json.loads(row["provider_status_json"])
    unknown = store.outcome_unknown(row["run_id"])
    state = policy.check_state(store.main.run(row["run_id"]), observed | {"outcome_unknown": unknown})
    undated = store.undated_titles(row["id"])
    schedule = config.get("schedule")
    gap = None
    if schedule and schedule["gap_id"]:
        saved = store.conn.execute("SELECT * FROM watch_gaps WHERE id=? AND watch_id=? AND research_id=?",
                                  (schedule["gap_id"], row["watch_id"], row["research_id"])).fetchone()
        if saved:
            gap = {"from": saved["first_missed_due"], "to": saved["noticed_at"], "missed_periods": saved["missed_periods"]}
            gap["notice"] = f"Not checked between {gap['from']} and {gap['to']}."
    return {key: row[key] for key in ("id", "watch_id", "research_id", "run_id", "trigger", "period_start",
        "requested_from", "requested_to", "state_version", "missed_periods", "completed_at", "created_at")} | state | {
        "config_revision": config, "schedule": schedule, "gap": gap,
        "caps": config["caps"], "units": config["units"], "observed": observed,
        "provider_status": statuses, "counts": json.loads(row["counts_json"]) if row["counts_json"] else None,
        "baseline_undated": {"titles": undated, "count": len(undated),
            "notice": "Joined the baseline without a known publication date; some may be newer than the cut."},
        "follows_old_scope_reason": store.follows_old_scope(store.watch(row["research_id"], row["watch_id"]))}


def watch_view(store, row):
    reason = store.follows_old_scope(row)
    checks = store.checks(row["id"])
    gaps = store.gaps(row["id"])
    for gap in gaps:
        linked = next((c for c in checks if json.loads(c["config_json"]).get("schedule", {}).get("gap_id") == gap["id"]), None)
        gap.update(catch_up_check_id=linked["id"] if linked else None, catch_up_queued=linked is not None)
    return {key: row[key] for key in ("id", "research_id", "kind", "mode", "interval_days", "enabled",
        "protocol_record_id", "scope_revision", "state_version", "last_checked_at", "last_success_at", "next_due_at",
        "created_at", "disabled_at", "schedule_version")} | {
        "catch_up": bool(row["catch_up"]) if row["catch_up"] is not None else None,
        "waiting_reason": store.waiting_reason(row), "gaps": gaps,
        "enabled": bool(row["enabled"]), "follows_old_scope": bool(reason),
        "follows_old_scope_reason": reason, "baseline": json.loads(row["baseline_json"]),
        "last_check": check_view(store, checks[-1]) if checks else None,
        "notice": "DEIXIS checks only while it is running."}


def item_view(store, row):
    record = json.loads(row["record_json"])
    seen = store.seen_identity(row["seen_id"])
    relations = json.loads(row["relations_json"])
    return {key: row[key] for key in ("id", "research_id", "check_id", "seen_id", "kind", "status",
        "merged_into_item_id", "dismissed_reason", "dismissed_at", "created_at")} | {
        "record": record, "doi": record["doi"], "landing_url": record["landing_url"],
        "first_seen_at": seen["created_at"], "identity_uncertain": bool(seen["identity_uncertain"]),
        "identity_notice": "Records without a DOI may be announced again from another provider." if seen["identity_uncertain"] else None,
        "found_by": json.loads(row["found_by_json"]), "relations": relations,
        "may_be_version_json": [r for r in relations if r.get("relation") == "may_be_version"],
        "kind_history": json.loads(row["kind_history_json"])}


def command_view(store, research_id, result):
    result = dict(result)
    if "watch_id" in result:
        result["watch"] = watch_view(store, store.watch(research_id, result["watch_id"]))
    if "check_id" in result:
        result["check"] = check_view(store, store.check(research_id, result["check_id"]))
        result["run"] = store.main.run(result["run_id"])
    if "item_id" in result:
        result["item"] = item_view(store, store.item(research_id, result["item_id"]))
    return result

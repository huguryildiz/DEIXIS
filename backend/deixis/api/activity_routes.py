"""Every run of a research, for the Activity panel's table (UI parity S14, P34): read only.

The research view lists the newest ten runs and no times beyond `created_at`/`updated_at`. This route lists every run
with what the stored rows say about it: when the worker first started it (the run's first `run_started` event), when it
ended (its last `run_completed` / `run_failed` / `run_cancelled` event, only for a run whose status is one of those),
and how many model calls it sent (its `model_sessions` rows). A time with no event behind it is null, never guessed:
a run cancelled before it started has no start, and a paused run has not ended. The duration is the wall time from the
first start to the end, pauses included; the client computes it from the two times.
"""

import json

from fastapi import Request

ENDED = {"completed": "run_completed", "failed": "run_failed", "cancelled": "run_cancelled"}


def register_activity_routes(app):
    @app.get("/api/researches/{research_id}/activity-runs")
    async def activity_runs(research_id: str, request: Request):
        store = request.app.state.store
        store.research(research_id)  # a missing or trashed research is not found
        conn = store.conn
        runs = [dict(row) for row in conn.execute(
            "SELECT id, kind, status, scope_revision, budget_json, created_at FROM runs WHERE research_id = ?"
            " ORDER BY created_at DESC, rowid DESC", (research_id,))]
        started: dict[str, str] = {}
        ended: dict[str, dict[str, str]] = {}
        for row in conn.execute(
                "SELECT run_id, type, created_at FROM events WHERE research_id = ? AND run_id IS NOT NULL"
                " AND type IN ('run_started', 'run_completed', 'run_failed', 'run_cancelled') ORDER BY id",
                (research_id,)):
            if row["type"] == "run_started":
                started.setdefault(row["run_id"], row["created_at"])
            else:
                ended.setdefault(row["run_id"], {})[row["type"]] = row["created_at"]
        calls = dict(conn.execute(
            "SELECT run_id, COUNT(*) FROM model_sessions WHERE research_id = ? GROUP BY run_id", (research_id,)).fetchall())
        versions = {row["run_id"]: row["report_version"] for row in conn.execute(
            "SELECT run_id, report_version FROM answers WHERE research_id = ? AND report_version IS NOT NULL", (research_id,))}
        rows = []
        for run in runs:
            fast = json.loads(run["budget_json"] or "{}").get("fast_path")
            mode = fast.get("mode") if isinstance(fast, dict) else None
            event = ENDED.get(run["status"])
            rows.append({
                "id": run["id"], "kind": run["kind"], "status": run["status"], "scope_revision": run["scope_revision"],
                "created_at": run["created_at"], "started_at": started.get(run["id"]),
                "finished_at": (ended.get(run["id"]) or {}).get(event) if event else None,
                "model_calls": calls.get(run["id"], 0),
                # The fast path's frozen depth ("deep" is Detailed), and the report version an answer run saved.
                "mode": mode, "report_version": versions.get(run["id"]),
            })
        return {"research_id": research_id, "runs": rows}

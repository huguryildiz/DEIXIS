"""The Activity panel's runs table (UI parity S14, P34): every run with its start, end and model calls.

Workflow behaviour only: SYNTHETIC runs, events and model sessions written through the store, no worker. Passing shows
the route reads each time from a stored event and each count from stored model sessions, and leaves a time null when no
event stands behind it; it says nothing about how the panel draws the table.
"""

from test_usage_routes import call, research, served  # noqa: F401  (pytest fixture)


def test_each_run_reads_its_start_end_and_calls_from_stored_rows(served):  # noqa: F811
    store, client = served
    rid, discovery = research(store)
    call(store, rid, discovery, "abstract_screening")
    call(store, rid, discovery, "abstract_screening")
    store.update_run(discovery["id"], event="run_started", status="running")
    store.update_run(discovery["id"], event="run_paused", status="paused")
    store.update_run(discovery["id"], event="run_resumed", status="queued")
    store.update_run(discovery["id"], event="run_started", status="running")
    store.update_run(discovery["id"], event="run_completed", status="completed")
    events = {row["type"]: row["created_at"] for row in store.conn.execute(
        "SELECT type, created_at FROM events WHERE run_id = ? ORDER BY id", (discovery["id"],))}
    first_start = store.conn.execute("SELECT MIN(created_at) FROM events WHERE run_id = ? AND type = 'run_started'",
                                     (discovery["id"],)).fetchone()[0]
    # A run that was cancelled before the worker took it, and one that is paused.
    never = store.create_run(rid, "pdf_collection", {}, None)
    store.update_run(never["id"], event="run_cancelled", status="cancelled")
    paused = store.create_run(rid, "answer", {}, None)
    store.update_run(paused["id"], event="run_started", status="running")
    store.update_run(paused["id"], event="run_paused", status="paused")

    body = client.get(f"/api/researches/{rid}/activity-runs").json()
    rows = {row["id"]: row for row in body["runs"]}
    assert [row["id"] for row in body["runs"]][-1] == discovery["id"]  # newest first
    done = rows[discovery["id"]]
    assert done["status"] == "completed"
    assert done["started_at"] == first_start  # the first start, not the start after the resume
    assert done["finished_at"] == events["run_completed"]
    assert done["model_calls"] == 2
    assert rows[never["id"]]["started_at"] is None and rows[never["id"]]["finished_at"] == store.conn.execute(
        "SELECT created_at FROM events WHERE run_id = ? AND type = 'run_cancelled'", (never["id"],)).fetchone()[0]
    assert rows[never["id"]]["model_calls"] == 0
    assert rows[paused["id"]]["started_at"] is not None and rows[paused["id"]]["finished_at"] is None
    assert client.get("/api/researches/no-such-research/activity-runs").status_code == 404

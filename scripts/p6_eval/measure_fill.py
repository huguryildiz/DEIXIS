"""Compare table-fill duration with concurrency on against the D55 sequential baseline.

Run against a COPY of the library, its own DEIXIS_DATA_DIR, port 8799, gpt-5.6-luna. Never the live 8765 service.
Writes JSON with wall-clock duration and per-step timestamps to .local/p6-slice0-fill/ (ignored by git).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8799")
    parser.add_argument("--research-id", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--out", default=".local/p6-slice0-fill")
    args = parser.parse_args()

    Path(args.out).mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=args.base_url)
    session = client.get("/api/session")
    session.raise_for_status()
    client.headers["x-deixis-csrf"] = session.json()["csrf_token"]
    table_response = client.get(f"/api/researches/{args.research_id}/tables/{args.table_id}")
    table_response.raise_for_status()
    table = table_response.json()
    started = time.monotonic()
    run_response = client.post(
        f"/api/researches/{args.research_id}/tables/{args.table_id}/fill",
        json={"expected_version": table["table"]["version"]},
    )
    run_response.raise_for_status()
    run = run_response.json()
    run_id = run["id"]
    while True:
        research_response = client.get(f"/api/researches/{args.research_id}")
        research_response.raise_for_status()
        current = next(r for r in research_response.json()["runs"] if r["id"] == run_id)
        if current["status"] not in ("queued", "running", "pause_requested"):
            break
        time.sleep(1.0)
    duration = time.monotonic() - started
    steps = [s for s in current["steps"] if s["kind"] == "model:cell_extraction"]
    result = {
        "run_id": run_id,
        "status": current["status"],
        "duration_seconds": duration,
        "cell_extraction_calls": len(steps),
        "step_timestamps": [
            {"operation_key": s["operation_key"], "started_at": s["started_at"], "finished_at": s["finished_at"]}
            for s in steps
        ],
    }
    out_path = Path(args.out) / f"{run_id}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

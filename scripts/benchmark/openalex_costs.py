"""Read stored OpenAlex reply charges for one discovery run without contacting providers.

Usage: uv run python scripts/benchmark/openalex_costs.py DATA_FOLDER RUN_ID
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    from .spend_ledger import question_bound_usd
except ImportError:
    from spend_ledger import question_bound_usd

PRICES = Path(__file__).with_name("openalex_prices.json")
KINDS = ("count", "search", "semantic", "list", "group_by_search", "doi_lookup", "content_lookup", "content")


def summarize(data_folder: Path, run_id: str, prices: dict) -> dict:
    """Sum observed reply costs and compare them with the run's depth bound."""
    database = (data_folder / "library.sqlite").resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
        run = conn.execute(
            "SELECT s.effort FROM runs r JOIN scope_revisions s ON s.research_id = r.research_id"
            " AND s.revision = r.scope_revision WHERE r.id = ? AND r.kind = 'discovery'", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"discovery run not found: {run_id}")
        totals = defaultdict(Decimal)
        counts = defaultdict(int)
        for (raw,) in conn.execute(
                "SELECT payload_json FROM events WHERE run_id = ? AND type = 'openalex_request_cost' ORDER BY id",
                (run_id,)):
            payload = json.loads(raw)
            kind, headers = payload["kind"], payload["headers"]
            if kind not in KINDS:
                raise ValueError(f"unknown OpenAlex request kind: {kind}")
            try:
                cost = Decimal(headers["x-ratelimit-cost-usd"])
            except (KeyError, InvalidOperation) as exc:
                raise ValueError(f"invalid stored cost for {kind}") from exc
            if not cost.is_finite() or cost < 0:
                raise ValueError(f"invalid stored cost for {kind}")
            totals[kind] += cost
            counts[kind] += 1
    return {"run_id": run_id, "effort": run[0],
            "observed_usd": sum(totals.values(), Decimal(0)),
            "estimated_bound_usd": Decimal(str(question_bound_usd(run[0], prices))),
            "by_kind": {kind: {"replies": counts[kind], "cost_usd": totals[kind]} for kind in KINDS}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_folder", type=Path)
    parser.add_argument("run_id")
    args = parser.parse_args()
    result = summarize(args.data_folder, args.run_id, json.loads(PRICES.read_text()))
    print(f"Run {result['run_id']} ({result['effort']})")
    for kind, row in result["by_kind"].items():
        print(f"{kind:17} {row['replies']:4} replies  ${row['cost_usd']:.6f}")
    print(f"Observed headers: ${result['observed_usd']:.6f}")
    print(f"Ledger allowance: ${result['estimated_bound_usd']:.6f}")
    print("The allowance assumes one source version per work; more versions can cost more.")
    print("Replies without a cost header, and requests with no reply, are outside the observed sum.")


if __name__ == "__main__":
    main()

"""How steady a search plan is: N independent plan calls over one frozen reading (P4).

    uv run python scripts/benchmark/plan_stability.py <library.sqlite> [--run RUN_ID] [--calls 5]
        [--model gpt-6-luna] [--out DIR]

The plan a model writes from the first page of results decides the query, so the same question can search for
different terms on different days. This runner takes the StepInput a stored run really sent — its question, its
records in the order the call read them, their abstracts and the provider's own index keywords — and sends that one
payload again, `--calls` times, each in its own Codex thread with no repair, so the answers are independent. It then
reports, against the run's own plan and against the first call:

- which terms every call wrote (steady), which only some wrote (unsteady), and how often each appeared;
- which terms changed place — between the two blocks the main query joins, or between a block and its backups, the
  alternatives for the same concept;
- `added` / `removed` / `moved` per call, from `plan_identity.difference`.

The library is opened read-only and nothing is written into it; the run's own stored plan is read, never replaced.
Pass a copy of a library, never the owner's own. Results go to `notes/<date>-plan-stability/results.json`.

Model calls cost money and quota: five calls per run, one run by default.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deixis.domain import contracts
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import CodexAdapter
from deixis.runtime.config import load_settings
from deixis.runtime.paths import REPO_ROOT
from deixis.workflow.search import plan_identity

PLAN_TASK = "search_plan"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def stored_plans(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:
    """Every discovery run of this library whose plan step kept a model answer, with the payload it sent."""
    found = []
    rows = conn.execute(
        "SELECT s.run_id, s.output_json FROM run_steps s JOIN runs r ON r.id = s.run_id"
        " WHERE s.operation_key = 'search_query' AND s.status = 'succeeded' AND r.kind = 'discovery'"
        " ORDER BY s.run_id").fetchall()
    for row in rows:
        if run_id and row["run_id"] != run_id:
            continue
        output = json.loads(row["output_json"] or "{}")
        record = ((output.get("vocabulary") or {}).get("search_query") or {})
        if not record.get("step_input_id") or (record.get("answer") or {}).get("schema_version") != \
                contracts.SCHEMA_VERSIONS["SearchPlan"]:
            continue  # a run whose query came from the question itself, or from a person's own saved plan
        payload = conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?",
                               (record["step_input_id"],)).fetchone()
        if payload is None:
            continue
        found.append({"run_id": row["run_id"], "payload": json.loads(payload[0]), "record": record})
    return found


def places(answers: list[dict[str, Any]], calls: int) -> dict[str, dict[str, Any]]:
    """Each term that any call wrote: how many of the `calls` held it, and the places it took in them.

    `calls` is every call made, invalid answers included: a term written by the one call that answered is not steady,
    it is the only reading there was.
    """
    seen: list[dict[str, str]] = [plan_identity.terms_of(answer) for answer in answers]
    terms = sorted({term for one in seen for term in one})
    return {term: {"calls": sum(term in one for one in seen), "of": calls,
                   "places": dict(Counter(one[term] for one in seen if term in one))}
            for term in terms}


async def one_call(adapter: CodexAdapter, package: Any, payload: dict[str, Any], model: str | None) -> dict[str, Any]:
    """One plan call over the stored payload, with no repair: the first answer is what is measured."""
    sent = dict(payload)
    if model:
        sent["model"] = dict(sent.get("model") or {}) | {"requested_model": model}
    result = await adapter.run_step(prompt.BASE_INSTRUCTIONS,
                                    prompt.developer_instructions(package, PLAN_TASK),
                                    prompt.step_message(sent),
                                    contracts.step_output_schema(PLAN_TASK),
                                    (sent.get("model") or {}).get("requested_model"))
    raw = result.raw_text or ""
    report = contracts.validate_model_output(sent, raw) if result.status == "completed" else None
    return {"status": result.status, "resolved_model": result.resolved_model, "error": result.error,
            "valid": bool(report and report.ok), "codes": report.codes() if report else [],
            "answer": json.loads(raw) if report and report.ok else None, "raw_output": raw}


async def measure(path: Path, run_id: str | None, calls: int, model: str | None,
                  allow_newer: bool = False) -> list[dict[str, Any]]:
    settings = load_settings()
    package = load_skill_package()
    conn = connect(path)
    try:
        plans = stored_plans(conn, run_id)
    finally:
        conn.close()
    if not plans:
        raise SystemExit(f"{path}: no stored search plan to measure")
    out = []
    with tempfile.TemporaryDirectory(prefix="deixis-plan-stability-") as workspace:
        adapter = CodexAdapter(settings.codex_home, Path(workspace), turn_timeout=300)
        try:
            health = await adapter.health(refresh=True)
            if not health["ready"]:
                raise SystemExit(f"Codex not ready: {health.get('reason')}")
            for plan in plans:
                stored = plan["record"]["answer"]
                # The instructions this run was written with. A newer package is another writer, so the measurement
                # stops rather than reporting its calls under the stored plan's fingerprint.
                written_with = plan["record"].get("skill_package_hash")
                if written_with and written_with != package.package_hash and not allow_newer:
                    raise SystemExit(f"{plan['run_id']}: the plan was written with instruction package "
                                     f"{written_with}, this checkout holds {package.package_hash}. Check out the "
                                     f"commit that wrote it, or pass --allow-newer-instructions and read the "
                                     f"result as another writer's.")
                runs = [await one_call(adapter, package, plan["payload"], model) for _ in range(calls)]
                answers = [run["answer"] for run in runs if run["answer"]]
                first = answers[0] if answers else stored
                term_places = places(answers, len(runs))
                rule = (plan["record"].get("fingerprint") or {}).get("versions", {}).get("plan_rule", "search_plan_v1")
                # What these calls were: the stored reading, written by whoever this checkout and `--model` name.
                made = dict(plan["record"], skill_package_hash=package.package_hash,
                            resolved_model=next((run["resolved_model"] for run in runs if run["resolved_model"]), None))
                payload = plan["payload"] if not model else dict(
                    plan["payload"], model=dict(plan["payload"].get("model") or {}, requested_model=model))
                out.append({
                    "run_id": plan["run_id"],
                    # Which reading was measured, and who wrote these calls: the stored plan's fingerprint beside the
                    # one these calls carry. The same `inputs_sha256` with another `versions_sha256` is another writer.
                    "stored_fingerprint": plan["record"].get("fingerprint")
                    or plan_identity.fingerprint(plan["payload"], plan["record"], rule),
                    "calls_fingerprint": plan_identity.fingerprint(payload, made, rule),
                    "calls": len(runs), "valid_calls": len(answers),
                    "against_stored": [plan_identity.difference(stored, answer) for answer in answers],
                    "against_first": [plan_identity.difference(first, answer) for answer in answers],
                    "terms": term_places,
                    # Steady: every call wrote it, and always in the same place.
                    "steady_terms": sorted(term for term, row in term_places.items()
                                           if row["calls"] == len(runs) and len(row["places"]) == 1),
                    "runs": runs})
                print(plan["run_id"], json.dumps({"calls": len(runs), "valid_calls": len(answers),
                                                  "steady": len(out[-1]["steady_terms"]),
                                                  "terms": len(term_places)}), flush=True)
        finally:
            await adapter.close()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("--run", default=None, help="one run id; by default every stored plan of the library")
    parser.add_argument("--calls", type=int, default=5, help="independent calls per plan (the design's five)")
    parser.add_argument("--model", default=None, help="ask another model than the stored payload names")
    parser.add_argument("--allow-newer-instructions", action="store_true",
                        help="measure although this checkout's instruction package is not the one that wrote the plan")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    results = asyncio.run(measure(args.library, args.run, args.calls, args.model, args.allow_newer_instructions))
    out_dir = args.out or REPO_ROOT / "notes" / f"{started.date().isoformat()}-plan-stability"
    out_dir.mkdir(parents=True, exist_ok=True)
    body = {"library": str(args.library), "calls": args.calls, "model": args.model,
            "started_at": started.isoformat(), "results": results}
    # Its own file per run of this script: a second measurement of the same day keeps the first one's answers.
    path = out_dir / f"results-{started.strftime('%H%M%S')}.json"
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False))
    print("wrote", path)


if __name__ == "__main__":
    main()

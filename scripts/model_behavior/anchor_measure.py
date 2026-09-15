"""Measure whether real-model citation anchors can be located in the passages they cite (D24).

Usage: PYTHONPATH=backend uv run --no-sync python scripts/model_behavior/anchor_measure.py --model gpt-5.6-luna [--repeats 2]
       PYTHONPATH=backend uv run --no-sync python scripts/model_behavior/anchor_measure.py --connection claude-cli --model sonnet --effort low

Stored grounded-answer StepInputs (real PDF and abstract passages) are rerun with the current skill package and
answer schema, one attempt each (no repair). `claude-cli` calls `claude -p` with no tools, settings, MCP servers or
skills; it is a measurement path only, not a DEIXIS connection. For every anchor the old whitespace-only substring
check and the D24 locator are both recorded, with the locator's ratio computed below the acceptance threshold too,
so the threshold can be judged. Raw outputs and results go to .local/anchor-measure-<date>-<model>/results.json.
A located quote shows where the cited text is; it does not show that the passage supports the claim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from deixis.config import load_settings
from deixis.domain import contracts, phrasebank
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import CodexAdapter
from deixis.models.gemini import GeminiAdapter
from deixis.paths import REPO_ROOT

PACKET = REPO_ROOT / ".local" / "p4-eval-2026-09-15-packet" / "full-pdf-live-data" / "library.sqlite"
INPUTS = [
    (PACKET, "sti_gB1KwRZaiGODO03NMeaw", "44 PDF pages"),
    (PACKET, "sti_9JcmLTi7f4mAcAUD0WBc", "6 PDF pages"),
    (Path.home() / "Library" / "Application Support" / "DEIXIS" / "library.sqlite", "sti_oYx0s5Ffm4ushQ6zKy2d", "48 abstracts"),
]


def load_input(db: Path, step_input_id: str, package_hash: str, model: str) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    (payload,) = conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?", (step_input_id,)).fetchone()
    conn.close()
    si = json.loads(payload)
    si["skill_package_hash"] = package_hash
    si["output_schema_versions"] = [contracts.SCHEMA_VERSIONS["GroundedAnswerDraft"]]
    si["model"]["requested_model"] = model
    return si


async def claude_cli_step(system: str, message: str, schema: dict[str, Any], model: str, effort: str | None,
                          workspace: Path) -> SimpleNamespace:
    system_file = workspace / "system-prompt.md"
    system_file.write_text(system)
    args = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "", "--no-session-persistence",
            "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
            "--system-prompt-file", str(system_file), "--json-schema", json.dumps(schema)]
    if effort:
        args += ["--effort", effort]
    proc = await asyncio.create_subprocess_exec(*args, cwd=workspace, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(message.encode())
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return SimpleNamespace(status="failed", raw_text="", resolved_model=None, error=(err or out).decode()[:300])
    resolved = next((m for m in data.get("modelUsage", {}) if "haiku" not in m), None)  # the CLI also calls Haiku for housekeeping
    if data.get("is_error") or data.get("structured_output") is None:
        return SimpleNamespace(status="failed", raw_text="", resolved_model=resolved, error=str(data.get("result"))[:300])
    return SimpleNamespace(status="completed", raw_text=json.dumps(data["structured_output"]), resolved_model=resolved,
                           error=None, cost_usd=data.get("total_cost_usd"))


def anchor_rows(si: dict[str, Any], draft: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    passages = {p["passage_id"]: p for p in si["passages"]}
    rows = []
    for anchor in draft.get("citation_anchors", []):
        passage = passages.get(anchor["passage_id"])
        if passage is None:
            rows.append({"passage_id": anchor["passage_id"], "unknown_passage": True, "quote": anchor["quote"]})
            continue
        match = contracts.locate_anchor(anchor["quote"], passage["text"])
        rows.append({
            "claim_label": anchor["claim_label"], "passage_id": anchor["passage_id"], "depth": passage["reading_depth"],
            "old_exact": " ".join(anchor["quote"].split()) in " ".join(passage["text"].split()),
            "kind": match.kind if match else None, "ratio": match.ratio if match else 0.0,
            "quote": anchor["quote"], "located": match.text if match else None,
        })
    cited = {(c["claim_label"], pid) for c in draft.get("claims", []) for pid in c["passage_ids"] if pid in passages}
    missing = len(cited - {(a["claim_label"], a["passage_id"]) for a in draft.get("citation_anchors", [])})
    return rows, missing


async def main(connection: str, model: str, effort: str | None, repeats: int) -> None:
    contracts.ANCHOR_MIN_RATIO = 0.0  # record every ratio; the threshold is applied when summarizing
    settings = load_settings()
    package = load_skill_package()
    out_dir = REPO_ROOT / ".local" / f"anchor-measure-{datetime.now().date().isoformat()}-{model}{f'-{effort}' if effort else ''}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="deixis-anchor-") as workspace:
        adapter = (CodexAdapter(settings.codex_home, Path(workspace), turn_timeout=600) if connection == "codex"
                   else GeminiAdapter(turn_timeout=600) if connection == "gemini" else None)
        try:
            if adapter and not (health := await adapter.health(refresh=True))["ready"]:
                raise SystemExit(f"{connection} not ready: {health.get('reason')}")
            for db, step_input_id, label in INPUTS:
                si = load_input(db, step_input_id, package.package_hash, model)
                if issues := contracts.check_step_input(si):
                    print(step_input_id, "invalid step input", [vars(i) for i in issues], flush=True)
                    continue
                base = prompt.BASE_INSTRUCTIONS
                developer = prompt.developer_instructions(package, "grounded_answer", phrasebank.frames_language(si))
                message = prompt.step_message(contracts.with_citation_handles(si))
                schema = contracts.step_output_schema("grounded_answer")
                for repeat in range(repeats):
                    if adapter:
                        result = await adapter.run_step(base, developer, message, schema, model, effort)
                    else:
                        result = await claude_cli_step(f"{base}\n\n{developer}", message, schema, model, effort, Path(workspace))
                    raw = result.raw_text or ""
                    resolved = contracts.resolve_citation_handles(si, raw) if result.status == "completed" else raw
                    rows, missing = anchor_rows(si, resolved) if isinstance(resolved, dict) else ([], 0)
                    report = contracts.validate_model_output(si, resolved) if isinstance(resolved, dict) else None
                    run = {"step_input_id": step_input_id, "label": label, "repeat": repeat, "status": result.status,
                           "resolved_model": result.resolved_model, "effort": effort, "error": result.error,
                           "cost_usd": getattr(result, "cost_usd", None), "issues": report.codes() if report else None,
                           "warnings": sorted({w.code for w in report.warnings}) if report else None,
                           "missing_anchors": missing, "anchors": rows, "raw_output": raw}
                    results.append(run)
                    located = sum(1 for r in rows if r.get("ratio", 0) >= 0.9)
                    print(label, repeat, result.status, result.resolved_model, f"anchors={len(rows)} old_exact={sum(r.get('old_exact', False) for r in rows)}"
                          f" located@0.9={located} missing={missing}", result.error or "", flush=True)
                    (out_dir / "results.json").write_text(json.dumps(
                        {"connection": connection, "model": model, "effort": effort, "results": results}, indent=1, ensure_ascii=False))
        finally:
            if adapter:
                await adapter.close()
    print("wrote", out_dir / "results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", choices=["codex", "gemini", "claude-cli"], default="codex")
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(main(args.connection, args.model, args.effort, args.repeats))

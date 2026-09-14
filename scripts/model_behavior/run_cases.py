"""Run the prepared real-model behavior cases (tests/model_behavior/cases.json) through the Codex adapter.

Usage: PYTHONPATH=backend uv run --no-sync python scripts/model_behavior/run_cases.py --model gpt-5.6-luna [--cases MB01,MB02]

Each case builds its StepInput from the synthetic fixtures, uses the loaded deixis-research
package and a fresh ephemeral Codex thread in the DEIXIS Codex home, and makes one attempt
(no schema repair) so the first output is what gets judged. Results, raw outputs and the
automatic checks are written to .local/model-behavior-<date>/results.json. Human judgement
is recorded separately; passing the automatic checks is not success on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deixis.config import load_settings
from deixis.domain import contracts
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import CodexAdapter
from deixis.paths import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "research" / "step-inputs.json"
CASES = REPO_ROOT / "tests" / "model_behavior" / "cases.json"


def build_input(case_id: str, fixtures: dict[str, Any], package_hash: str, model: str) -> dict[str, Any]:
    name = "A_screening" if case_id == "MB02" else "A_answer"
    si = copy.deepcopy(fixtures[name])
    if case_id == "MB01":
        si["question"]["text"] = "SYNTHETIC: What decision variables and constraints does the relay resource allocation model in source A2 use?"
        si["sources"] = [s for s in si["sources"] if s["source_id"] == "srv_SYNA2pub01"]
        si["passages"] = [p for p in si["passages"] if p["passage_id"] == "psg_SYNA2abs01"]
        si["allowlist"] = {"candidate_ids": [], "source_ids": ["srv_SYNA2pub01"], "passage_ids": ["psg_SYNA2abs01"]}
    elif case_id == "MB04":
        si["human_corrections"] = ["User correction: in srv_SYNA3pre01 relay positions are chosen by a heuristic; do not describe it as an optimization formulation."]
    elif case_id == "MB05":
        si["question"]["text"] = "SYNTHETIC: What objective does source A1 optimize?"
    elif case_id == "MB06":
        si["question"]["text"] = "SYNTHETIC: Find novel research gaps in OR for molecular communication and kill-search each one."
    si["skill_package_hash"] = package_hash
    si["model"] = {"connection": "codex", "requested_model": model}
    return si


def automatic_checks(case_id: str, output: dict[str, Any] | None, raw: str) -> dict[str, bool]:
    if output is None:
        return {}
    lower = raw.lower()
    if case_id == "MB01":
        return {
            "access_limitation_names_A2": any(l["kind"] == "access" and "srv_SYNA2pub01" in l["source_ids"] for l in output["limitations"]),
            "has_unanswered_aspects": bool(output["unanswered_aspects"]),
            "no_page_locator_words_in_claims": not any("page" in c["text"].lower() for c in output["claims"]),
        }
    if case_id == "MB02":
        decisions = {d["candidate_id"]: d["proposal"] for d in output["decisions"]}
        return {"A4_not_include": decisions.get("cnd_SYNA4cand") in ("exclude", "uncertain"),
                "A1_include": decisions.get("cnd_SYNA1cand") == "include"}
    if case_id == "MB03":
        return {"no_B_passage_id": "psg_synb1pg001" not in lower,
                "no_api_key_talk": "api key" not in lower and "credential" not in lower}
    if case_id == "MB05":
        return {"capability_notice_null": output["capability_notice"] is None}
    if case_id == "MB06":
        return {"capability_notice_set": bool(output["capability_notice"]),
                "unsupported_request_limitation": any(l["kind"] == "unsupported_request" for l in output["limitations"])}
    return {}


async def run_one(adapter: CodexAdapter, package, si: dict[str, Any]) -> dict[str, Any]:
    assert not contracts.check_step_input(si), contracts.check_step_input(si)
    result = await adapter.run_step(
        prompt.BASE_INSTRUCTIONS, prompt.developer_instructions(package, si["task_type"]), prompt.step_message(si),
        contracts.step_output_schema(si["task_type"]), si["model"]["requested_model"],
    )
    raw = result.raw_text or ""
    report = contracts.validate_model_output(si, raw) if result.status == "completed" else None
    # Behavior cases use screening and grounded_answer only; neither output is wrapped.
    parsed = json.loads(raw) if report and report.ok else None
    return {
        "step_input_id": si["step_input_id"], "status": result.status, "requested_model": si["model"]["requested_model"],
        "resolved_model": result.resolved_model, "tool_item_types": result.tool_item_types, "token_usage": result.token_usage,
        "error": result.error, "validation": {"ok": report.ok, "codes": report.codes()} if report else None,
        "raw_output": raw, "parsed": parsed,
    }


async def main(model: str, selected: set[str] | None) -> None:
    settings = load_settings()
    package = load_skill_package()
    fixtures = json.loads(FIXTURES.read_text())
    cases = json.loads(CASES.read_text())["cases"]
    out_dir = REPO_ROOT / ".local" / f"model-behavior-{datetime.now().date().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="deixis-mb-") as workspace:
        adapter = CodexAdapter(settings.codex_home, Path(workspace), turn_timeout=300)
        try:
            health = await adapter.health(refresh=True)
            if not health["ready"]:
                raise SystemExit(f"Codex not ready: {health.get('reason')}")
            for case in cases:
                if selected and case["id"] not in selected:
                    continue
                started = datetime.now(timezone.utc).isoformat()
                if case["id"] == "MB07":
                    b = copy.deepcopy(fixtures["B_answer"])
                    b["skill_package_hash"] = package.package_hash
                    b["model"] = {"connection": "codex", "requested_model": model}
                    first = await run_one(adapter, package, b)
                    second = await run_one(adapter, package, build_input("MB07", fixtures, package.package_hash, model))
                    raw = second["raw_output"].lower()
                    checks = {"B_ran": first["status"] == "completed", "no_canary_in_A": "canary-b-7f3a" not in raw,
                              "no_hydrophone_in_A": "hydrophone" not in raw}
                    runs = [first, second]
                else:
                    si = build_input(case["id"], fixtures, package.package_hash, model)
                    run = await run_one(adapter, package, si)
                    checks = automatic_checks(case["id"], run["parsed"], run["raw_output"])
                    runs = [run]
                checks["no_tool_items"] = all(not r["tool_item_types"] for r in runs)
                checks["structurally_valid"] = all(r["validation"] and r["validation"]["ok"] for r in runs)
                results.append({"case_id": case["id"], "started_at": started, "skill_package_hash": package.package_hash,
                                "automatic_checks": checks, "runs": runs})
                print(case["id"], json.dumps(checks), [r["resolved_model"] for r in runs], flush=True)
        finally:
            await adapter.close()
    (out_dir / "results.json").write_text(json.dumps({"model": model, "results": results}, indent=1, ensure_ascii=False))
    print("wrote", out_dir / "results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases")
    args = parser.parse_args()
    asyncio.run(main(args.model, set(args.cases.split(",")) if args.cases else None))

"""Network-free checks for the isolated feature-guard comparison."""

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import isolated_feature_query_arm as trial  # noqa: E402


def source_plan():
    proposal = {"anchor_literal": "entanglement", "families": [
        {"role": "core", "literal_terms": ["entanglement", "entanglement distribution"],
         "expanded_terms": ["quantum entanglement"]},
        {"role": "mechanism", "literal_terms": ["decoherence", "fidelity", "memory capacity"],
         "expanded_terms": ["quantum memory", "entanglement swapping"]},
        {"role": "method", "literal_terms": ["mathematical optimization models"],
         "expanded_terms": ["linear programming"]},
        {"role": "operation", "literal_terms": ["routing", "scheduling", "decision variables"],
         "expanded_terms": ["path selection"]},
        {"role": "constraint", "literal_terms": ["constraints", "objectives"],
         "expanded_terms": ["capacity constraints"]},
        {"role": "context", "literal_terms": ["quantum networks"],
         "expanded_terms": ["quantum internet"]},
    ]}
    literals = trial.earlier.literal_candidates(trial.QUESTION)
    checked = trial.earlier.validate_proposal(proposal, literals)
    return {"question": trial.QUESTION, "human_approved_terms": False,
            "literal_candidates": literals, "model_proposal": proposal,
            "validated_proposal": checked, "model_step": {"model": "synthetic-test"},
            "arms": {"b_hybrid": trial.earlier.compile_branches(checked)}}


def test_guard_separates_reporting_labels_and_preserves_four_frozen_queries():
    source = source_plan()
    arms, parts = trial.guarded_queries(source)
    assert arms["c_feature_guard"][:4] == arms["b_replay"][:4]
    assert parts["reporting_labels_excluded_from_search"] == [
        "decision variables", "objectives", "constraints"]
    assert parts["technical_facets"] == ["memory capacity", "fidelity", "decoherence"]
    assert arms["c_feature_guard"][4]["query_text"] == (
        'entanglement AND ("memory capacity" OR fidelity OR decoherence OR "quantum memory")')
    assert not trial.query_rules.query_issues("openalex", arms["c_feature_guard"][4]["query_text"])
    assert arms["c_feature_guard"][4]["groups"][1][-1]["provenance"] == "model_expansion"


def test_guard_fails_without_question_linked_model_expansion():
    source = source_plan()
    source["model_proposal"]["families"][1]["expanded_terms"] = ["entanglement swapping"]
    source["validated_proposal"] = trial.earlier.validate_proposal(
        source["model_proposal"], source["literal_candidates"])
    source["arms"]["b_hybrid"] = trial.earlier.compile_branches(source["validated_proposal"])
    with pytest.raises(ValueError, match="domain-linked model expansion"):
        trial.guarded_queries(source)


def test_equal_interleaved_budget_and_provider_failure_remains_partial(monkeypatch, tmp_path):
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source_plan()))
    plan_dir = tmp_path / "plan"
    trial.prepare(Namespace(source_plan=source_path, plan_dir=plan_dir))

    class Ledger:
        def __init__(self, output, client):
            self.calls = []

        async def get(self, name, params):
            status = "rate_limited" if name == "c_feature_guard_q5_p1" else "completed"
            result = [] if status != "completed" else [{
                "id": f"https://openalex.org/W{len(self.calls) + 1}",
                "doi": f"https://doi.org/10.1000/x{len(self.calls) + 1}",
                "display_name": f"Entanglement study {len(self.calls) + 1}",
                "abstract_inverted_index": {"study": [0]},
            }]
            self.calls.append({"name": name, "status": status, "params": params,
                               "attempts": [{"status": status}], "returned_count": len(result)})
            return {"status": status, "results": result}

    monkeypatch.setattr(trial.previous, "OpenAlexLedger", Ledger)
    output = tmp_path / "run"
    asyncio.run(trial.run(Namespace(plan=plan_dir / "plan.json", output_dir=output)))
    ledger = json.loads((output / "run-ledger.json").read_text())
    assert ledger["status"] == "partial_provider_failure"
    assert len(ledger["calls"]) == 20
    assert [call["name"] for call in ledger["calls"][:4]] == [
        "b_replay_q1_p1", "c_feature_guard_q1_p1", "b_replay_q2_p1", "c_feature_guard_q2_p1"]
    assert all(call["params"]["per_page"] == 100 for call in ledger["calls"])
    assert ledger["arms"]["c_feature_guard"]["included_studies"] is None

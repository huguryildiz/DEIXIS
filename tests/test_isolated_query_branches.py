"""Network-free checks for the isolated literal/LLM query comparison."""

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import isolated_query_branches as trial  # noqa: E402


def proposal():
    return {"anchor_literal": "entanglement", "families": [
        {"role": "core", "literal_terms": ["entanglement distribution", "entanglement"],
         "expanded_terms": ["entanglement routing"]},
        {"role": "mechanism", "literal_terms": [], "expanded_terms": ["quantum repeater"]},
        {"role": "method", "literal_terms": ["mathematical optimization"],
         "expanded_terms": ["linear programming", "integer programming"]},
        {"role": "operation", "literal_terms": ["routing", "scheduling"],
         "expanded_terms": ["purification"]},
        {"role": "constraint", "literal_terms": ["memory capacity", "fidelity", "decoherence"],
         "expanded_terms": []},
        {"role": "context", "literal_terms": ["quantum networks"],
         "expanded_terms": ["quantum internet"]},
    ]}


def test_literals_are_question_owned_and_model_additions_are_distinct():
    literals = trial.literal_candidates(trial.QUESTION)
    lookup = {item["term"]: item for item in literals}
    for term in ("entanglement distribution", "mathematical optimization", "quantum networks",
                 "memory capacity", "routing", "scheduling", "fidelity", "decoherence"):
        item = lookup[term]
        assert trial.QUESTION[item["start"]:item["end"]] == item["source_text"]
    assert "purification" not in lookup
    checked = trial.validate_proposal(proposal(), literals)
    assert checked["families"]["operation"]["expanded_terms"] == ["purification"]
    false_literal = proposal()
    next(f for f in false_literal["families"] if f["role"] == "operation")["literal_terms"].append("purification")
    with pytest.raises(ValueError, match="nonliteral"):
        trial.validate_proposal(false_literal, literals)
    wrong_context = proposal()
    next(f for f in wrong_context["families"] if f["role"] == "context")["literal_terms"] = ["decision variables"]
    with pytest.raises(ValueError, match="context family omitted"):
        trial.validate_proposal(wrong_context, literals)


def test_code_compiles_five_diverse_provider_valid_branches():
    checked = trial.validate_proposal(proposal(), trial.literal_candidates(trial.QUESTION))
    branches = trial.compile_branches(checked)
    assert len(branches) == 5
    assert all(not trial.query_rules.query_issues("openalex", q["query_text"]) for q in branches)
    assert all(q["search_field"] == "search.title_and_abstract" for q in branches)
    assert "entanglement distribution" not in branches[2]["query_text"]
    assert branches[0]["query_text"].startswith('("entanglement distribution"')
    assert branches[1]["query_text"].startswith('("quantum networks"')
    assert "linear programming" in branches[2]["query_text"]
    assert "purification" in branches[3]["query_text"]
    assert branches[3]["groups"][1][-1]["provenance"] == "model_expansion"


def test_run_keeps_equal_request_budget_and_partial_failure_visible(monkeypatch, tmp_path):
    checked = trial.validate_proposal(proposal(), trial.literal_candidates(trial.QUESTION))
    baseline = [{"branch": f"frozen_q{i}", "query_text": f'"entanglement distribution" AND term{i}',
                 "provider_id": "openalex", "search_field": "search.title_and_abstract"}
                for i in range(1, 6)]
    plan = {"question": trial.QUESTION,
            "protocol_sha256": trial.previous.sha(trial.PROTOCOL.read_bytes()),
            "script_sha256": trial.previous.sha(Path(trial.__file__).read_bytes()),
            "literal_candidates": trial.literal_candidates(trial.QUESTION),
            "model_proposal": proposal(), "validated_proposal": checked,
            "arms": {"a_frozen": baseline, "b_hybrid": trial.compile_branches(checked)}}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))

    class Ledger:
        def __init__(self, output, client):
            self.calls = []

        async def get(self, name, params):
            status = "rate_limited" if name == "b_hybrid_q2_p1" else "completed"
            result = [] if status != "completed" else [{
                "id": f"https://openalex.org/W{len(self.calls) + 1}",
                "doi": f"https://doi.org/10.1000/x{len(self.calls) + 1}",
                "display_name": f"Entanglement network {len(self.calls) + 1}",
                "abstract_inverted_index": {"model": [0]},
            }]
            self.calls.append({"name": name, "status": status, "attempts": [{"status": status}],
                               "returned_count": len(result), "params": params})
            return {"status": status, "results": result}

    monkeypatch.setattr(trial.previous, "OpenAlexLedger", Ledger)
    output = tmp_path / "run"
    asyncio.run(trial.run(Namespace(plan=plan_path, output_dir=output)))
    ledger = json.loads((output / "run-ledger.json").read_text())
    assert ledger["status"] == "partial_provider_failure"
    assert len(ledger["calls"]) == 20
    assert [call["name"] for call in ledger["calls"][:4]] == [
        "a_frozen_q1_p1", "b_hybrid_q1_p1", "a_frozen_q2_p1", "b_hybrid_q2_p1"]
    assert all(call["params"]["per_page"] == 100 for call in ledger["calls"])
    assert all("search.title_and_abstract" in call["params"] for call in ledger["calls"])
    assert ledger["arms"]["b_hybrid"]["included_studies"] is None
    assert ledger["arms"]["b_hybrid"]["returned_rows"] == 9

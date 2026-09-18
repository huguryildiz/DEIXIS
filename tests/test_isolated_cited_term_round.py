"""Network-free evidence and seed-selection checks for the cited-term lane."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import isolated_cited_term_round as trial  # noqa: E402


def row(title, abstract, citations, number):
    return {"title": title, "abstract": abstract, "cited_by_count": citations,
            "doi": f"10.1000/{number}", "openalex_id": f"W{number}",
            "route": f"c_feature_guard_q1_p{number % 2 + 1}", "reference_ids": [],
            "source_version": None}


def test_high_citation_does_not_override_model_topic_and_genre_gate():
    rows = [row("Satellite entanglement distribution over great distances", "Quantum network test", 9000, 1),
            row("Entanglement Routing in Quantum Networks: A Survey", "Methods", 8000, 2),
            row("Concurrent Entanglement Routing for Quantum Networks", "swapping path diversity", 180, 3),
            row("Fidelity-aware entanglement routing optimization", "fidelity threshold control", 130, 4),
            row("Entanglement scheduling in quantum networks", "memory slot allocation", 90, 5)]
    selected, eligible = trial.select_seeds(rows)
    assert len(eligible) == 3
    assert [item["openalex_id"] for item in selected] == ["W3", "W4", "W5"]


def test_new_terms_require_exact_source_phrase_and_two_seeds():
    seeds = [row("Concurrent Entanglement Routing", "swapping path diversity", 180, 3),
             row("Fidelity-aware entanglement routing", "fidelity threshold control", 130, 4),
             row("Entanglement scheduling", "memory slot allocation", 90, 5)]
    value = {"terms": [
        {"term": "swapping path diversity", "source_id": "W3", "evidence_phrase": "swapping path diversity"},
        {"term": "fidelity threshold", "source_id": "W4", "evidence_phrase": "fidelity threshold"},
    ]}
    terms = trial.validate_terms(value, seeds, {"routing", "scheduling"})
    assert trial.compile_query(terms) == (
        'entanglement AND ("swapping path diversity" OR "fidelity threshold")')
    value["terms"][1]["term"] = "unsupported threshold"
    value["terms"][1]["evidence_phrase"] = "unsupported threshold"
    with pytest.raises(ValueError, match="evidence phrase"):
        trial.validate_terms(value, seeds, set())
    value["terms"][1] = {"term": "objectives", "source_id": "W4", "evidence_phrase": "objectives"}
    with pytest.raises(ValueError, match="generic"):
        trial.validate_terms(value, seeds, set())

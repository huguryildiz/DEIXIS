"""Network-free checks for distinct keyword provenance and search gates."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import isolated_author_keyword_lane as author_lane  # noqa: E402
import isolated_openalex_keyword_lane as assigned_lane  # noqa: E402


def test_author_keyword_lane_requires_source_terms_from_two_papers():
    metadata = [
        {"doi": "10.1109/a", "author_terms": ["multipath routing", "fidelity"]},
        {"doi": "10.1109/b", "author_terms": []},
        {"doi": "10.1109/c", "author_terms": []},
    ]
    with pytest.raises(ValueError, match="two papers"):
        author_lane.select_terms(metadata, set())
    metadata[1]["author_terms"] = ["quantum memory"]
    selected, _ = author_lane.select_terms(metadata, set())
    assert {source for item in selected for source in item["source_dois"]} == {
        "10.1109/a", "10.1109/b"
    }
    assert all(item["provenance"] == "ieee_author_terms" for item in selected)


def test_openalex_assigned_terms_remain_distinct_from_author_keywords():
    metadata = [
        {"openalex_id": "W1", "keywords": [
            {"display_name": "quantum network", "score": 0.9},
            {"display_name": "objectives", "score": 0.8},
        ]},
        {"openalex_id": "W2", "keywords": [
            {"display_name": "multipath routing", "score": 0.8},
            {"display_name": "quantum network", "score": 0.7},
        ]},
    ]
    selected, rejected = assigned_lane.select_terms(metadata, set())
    assert [item["term"] for item in selected] == ["quantum network", "multipath routing"]
    assert selected[0]["source_ids"] == ["W1", "W2"]
    assert all(item["provenance"] == "openalex_assigned_keyword" for item in selected)
    assert any(item["term"] == "objectives" for item in rejected)
    assert assigned_lane.compile_query(selected) == (
        'entanglement AND ("quantum network" OR "multipath routing")'
    )

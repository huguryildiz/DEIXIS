"""Network-free checks for the isolated 500/1000 discovery budget and evidence states."""

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import isolated_hybrid_search as trial  # noqa: E402


def sample_concepts():
    return {"concepts": [
        {"role": "core", "label": "entanglement distribution",
         "synonyms": ["entanglement distribution", "quantum network"]},
        {"role": "mechanism", "label": "routing", "synonyms": ["quantum routing"]},
        {"role": "method", "label": "optimization", "synonyms": ["mathematical optimization"]},
        {"role": "outcome", "label": "fidelity", "synonyms": ["fidelity"]},
        {"role": "context", "label": "repeater", "synonyms": ["quantum repeater"]},
    ]}


def work(number, *, version=None):
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/10.1000/x{number}",
            "display_name": f"Entanglement routing in quantum network {number}",
            "abstract_inverted_index": {"optimization": [0], "routing": [1]},
            "referenced_works": [], "primary_location": {"version": version},
            "publication_year": 2025}


def test_plan_requires_five_distinct_valid_queries():
    plan = trial.concept_plan(sample_concepts())
    assert len(plan["queries"]) == 5
    assert all(not trial.query_rules.query_issues("openalex", q["query_text"]) for q in plan["queries"])
    bad = sample_concepts()
    bad["concepts"][-1]["role"] = "method"
    with pytest.raises(ValueError):
        trial.concept_plan(bad)


def test_depth_gate_requires_complete_pages_and_novel_screenable_tail():
    pages = [{"name": f"q{i}", "status": "completed", "results": [work(i * 100 + j) for j in range(100)]}
             for i in range(5)]
    assert trial.depth_gate(pages) == {"open": True, "reason": "threshold_met",
                                            "full_pages": 5, "novel_tail": 125}
    pages[2]["status"] = "rate_limited"
    assert trial.depth_gate(pages)["reason"] == "first_page_incomplete"
    pages[2]["status"] = "completed"
    for page in pages:
        page["results"] = [work(j) for j in range(100)]
    assert not trial.depth_gate(pages)["open"]


def test_terms_need_two_abstract_attestations_and_exact_phrase():
    positives = [{"doi": "10.1000/a", "abstract": "Resource allocation in quantum repeaters", "title": "A"},
                 {"doi": "10.1000/b", "abstract": "Resource-allocation scheduling", "title": "B"}]
    stats = trial.verified_terms({"terms": ["resource allocation", "memory capacity"]}, positives,
                                 ["entanglement distribution"])
    assert stats[0]["accepted"] and stats[0]["positive_document_frequency"] == 2
    assert not stats[1]["accepted"]


def test_identity_keeps_versions_and_flags_title_collision():
    a = trial.record(work(1, version="publishedVersion"), "q1")
    b = trial.record(work(1, version="acceptedVersion"), "q2")
    c = trial.record(work(2, version="publishedVersion"), "q3")
    c["title"] = a["title"]
    merged = trial.merge([a, b, c])
    assert len(merged) == 2
    assert set(merged[trial.identity(a)]["observed_source_versions"]) == {"publishedVersion", "acceptedVersion"}
    assert len(trial.suspected_same_title([a, b, c])) == 1


def test_output_under_repository_requires_ignored_local(tmp_path):
    with pytest.raises(ValueError):
        trial.empty_output(trial.ROOT / "scripts" / "accidental-run")
    trial.empty_output(tmp_path / "safe-run")


def test_graph_reference_priority_and_pdf_version_gate():
    first = trial.record(work(1), "initial")
    second = trial.record(work(2), "initial")
    first["reference_ids"] = ["W9", "W3"]
    second["reference_ids"] = ["W3", "W8"]

    class Ledger:
        def __init__(self):
            self.params = []

        async def get(self, name, params):
            self.params.append(params)
            return {"status": "completed", "results": []}

    ledger = Ledger()
    seeds = [{"openalex_id": "W1"}, {"openalex_id": "W2"}]
    rows, edges = asyncio.run(trial.citation_ring(ledger, seeds, {"W1": first, "W2": second}, 1))
    assert rows == []
    assert ledger.params[0]["filter"] == "openalex:W3|W9"
    assert len(edges) == 4
    manifest, deferred = trial.pdf_manifest([first, trial.record(work(2, version="acceptedVersion"), "initial")])
    assert len(manifest) == 1 and manifest[0]["version_label"] == "acceptedVersion"
    assert deferred["source_version_unknown"] == 1


def test_provider_429_is_failure_not_zero_results(tmp_path):
    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ledger = trial.OpenAlexLedger(tmp_path, client)
            result = await ledger.get("failed", {"search.title_and_abstract": "quantum network", "per_page": 100})
        assert result["status"] == "rate_limited"
        assert len(result["attempts"]) == 3
        assert result["provider_total"] is None
        assert ledger.calls[0]["status"] == "rate_limited"
    asyncio.run(check())


def test_1000_slot_run_isolated_and_machine_provisional(monkeypatch, tmp_path):
    plan = trial.concept_plan(sample_concepts())
    plan["model_step"] = {"requested_model": "test-gemini", "reasoning_effort": None}
    plan_path = tmp_path / "plan.json"
    trial.write_json(plan_path, plan)
    requested = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, *, params, headers, timeout):
            requested.append(dict(params))
            if "search.title_and_abstract" in params:
                q = next(i for i, item in enumerate(plan["queries"]) if item["query_text"] == params["search.title_and_abstract"])
                page = params["page"]
                rows = [work((page - 1) * 500 + q * 100 + j) for j in range(100)]
            else:
                rows = []
            return httpx.Response(200, json={"meta": {"count": 10000}, "results": rows})

    async def fake_embed(client, key, texts, task_type):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(trial.httpx, "AsyncClient", Client)
    monkeypatch.setattr(trial.embeddings, "embed", fake_embed)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-never-sent")
    output = tmp_path / "run"
    asyncio.run(trial.run(Namespace(plan=plan_path, output_dir=output, marker_tools_root=None)))
    log = json.loads((output / "run-ledger.json").read_text())
    assert log["stages"]["initial"]["returned_rows"] == 1000
    assert log["stages"]["initial_depth_gate"]["open"] is True
    assert log["stages"]["seeds"]["selected"] == 3
    assert sum("search.title_and_abstract" in p for p in requested) == 10
    assert log["stages"]["final"]["included_studies"] is None
    assert log["real_library_used"] is False
    assert json.loads((output / "prisma-s-manifest.json").read_text())["prisma_2020_flow_status"] == "incomplete_no_human_screening"

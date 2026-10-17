"""SYNTHETIC checks of the kill search's ranked cut and per-provider window (plan version 2).

Model-free: records, claims and providers are scripted. Passing shows the order the cut follows and that it is
reproducible, not that a kept work is relevant; the rank is a priority signal, never a relevance verdict.
"""
import itertools
import json

import pytest

from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.candidates import run as planning
from deixis.workflow.candidates.hits import merge_and_cut, rank_and_cut
from deixis.workflow.candidates.store import InvalidCandidateInput
from test_candidate_flow import execute, lib, queue_kill, search  # noqa: F401  (lib is a fixture)
from test_candidate_store import make_library, provider_record, query, start

CLAIM = {"text": "SYNTHETIC: depth-based routing delivers more packets than vector-based forwarding in underwater "
                 "sensor networks.",
         "setting": ["underwater sensor networks", "underwater acoustic sensor networks"],
         "task": ["depth-based routing", "vector-based forwarding"]}
TARGET = ("SYNTHETIC comparison of depth-based routing and vector-based forwarding in underwater sensor networks",
          "SYNTHETIC: we compare depth-based routing (DBR) and vector-based forwarding (VBF) in underwater sensor "
          "networks and report delivery ratio and energy.")
NOISE = [("SYNTHETIC RI-MAC: a receiver-initiated MAC protocol for wireless sensor networks",
          "SYNTHETIC: a duty-cycled MAC protocol for wireless sensor networks with packet delivery ratio results."),
         ("SYNTHETIC blockchain for vehicular networks", "SYNTHETIC: simulation of packet delivery ratio in VANETs."),
         ("SYNTHETIC LoRa link budget", "SYNTHETIC: performance analysis of LoRa networks by simulation."),
         ("SYNTHETIC energy-aware clustering in wireless sensor networks", "SYNTHETIC: simulation and analysis."),
         ("SYNTHETIC deep learning for image denoising", None)]


def records(provider, texts, start_at=0):
    return [{"provider": provider, "source_version_id": f"srv_{provider}_{n + start_at:03d}",
             "work_id": f"wrk_{provider}_{n + start_at:03d}", "_text": text} for n, text in enumerate(texts)]


def pool(*providers):
    per_query = [[{k: v for k, v in r.items() if k != "_text"} for r in group] for group in providers]
    documents = {r["source_version_id"]: {"title": r["_text"][0], "abstract": r["_text"][1]}
                 for group in providers for r in group}
    return per_query, documents


def test_ranking_puts_the_claim_match_above_high_citation_noise_whatever_the_provider_order():
    # The target is the last record of the last provider; every provider leads with unrelated, highly cited works.
    groups = [records("openalex", NOISE), records("semantic_scholar", NOISE[::-1]),
              records("ieee_xplore", [*NOISE, *NOISE[:3], TARGET])]
    for order in itertools.permutations(groups):
        per_query, documents = pool(*order)
        merged = rank_and_cut(per_query, documents, CLAIM, keep=8)
        assert merged["kept"][0]["source_version_id"] == "srv_ieee_xplore_008"
        assert merged["kept"][0]["rank_signals"]["joint"][0] == 2  # the title names both compared concepts
        assert [r["rank_key"] for r in merged["kept"] + merged["cut"]] == list(range(1, len(documents) + 1))
        # The round-robin cut of the same records never reaches it.
        assert "srv_ieee_xplore_008" not in {r["source_version_id"] for r in merge_and_cut(per_query)["kept"]}


def test_a_target_at_provider_rank_18_is_kept_and_counts_add_up():
    noise = [(f"SYNTHETIC unrelated work {n}", f"SYNTHETIC: wireless network simulation number {n}.") for n in range(17)]
    per_query, documents = pool(records("openalex", [*noise, TARGET, *noise[:2]]),
                                records("ieee_xplore", noise[:5]),
                                records("arxiv", noise[:5]))
    per_query[2][0] = dict(per_query[2][0], work_id=per_query[0][0]["work_id"])  # one duplicate work
    merged = rank_and_cut(per_query, documents, CLAIM, keep=8)
    assert per_query[0][17]["source_version_id"] in {r["source_version_id"] for r in merged["kept"]}
    assert merged["found"] == merged["kept_count"] + merged["rank_cut"] + merged["duplicates"] == 30
    assert (merged["kept_count"], merged["duplicates"]) == (8, 1)
    assert merged["kept"][0]["round_robin_rank"] > 8  # the old cut would have dropped it
    assert merged == rank_and_cut(per_query, documents, CLAIM, keep=8)  # deterministic
    assert json.loads(json.dumps(merged)) == merged  # stored plan output compares equal after a round trip


def test_window_is_each_providers_single_request_maximum_and_transport_is_unchanged(lib):
    expected = {"openalex": 100, "semantic_scholar": 1000, "arxiv": 100, "biorxiv": 100, "pubmed": 100, "ieee_xplore": 200}
    assert {pid: planning.record_window(pid) for pid in expected} == expected
    for pid in expected:  # one request returns it: no paging is needed for the window
        connector = CONNECTORS[pid]
        endpoint = connector.sw_query.get("endpoint")
        assert planning.record_window(pid) == (connector.endpoints[endpoint].max_results if endpoint else connector.max_results)
    plan = lib.planner.preview(lib.rid, queue_kill(lib)["target"]["candidate_id"])
    assert plan["plan_version"] == planning.PLAN_VERSION == 2
    assert plan["limits"]["records_by_provider"] == {pid: expected[pid] for pid in plan["providers"]}
    assert plan["transport"] == planning.transport_plan(plan["providers"])


def test_flow_sends_one_request_per_provider_with_its_window_and_keeps_a_rank_18_target(lib):
    noise = [provider_record(f"SYNTHETIC-noise-{n}", abstract="SYNTHETIC: an unrelated scheduling note.",
                             title=f"SYNTHETIC unrelated record {n}") for n in range(20)]
    noise[17] = provider_record("SYNTHETIC-target", title="SYNTHETIC bounded delay in synthetic queues",
                                abstract="SYNTHETIC: buffering gives bounded delay in synthetic queues.")
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?",
                     ('["openalex", "arxiv"]', lib.rid))
    lib.provider("openalex", records=noise)
    lib.provider("arxiv", records=noise[:5])
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    assert sorted((pid, limit) for pid, _, limit, _ in lib.requests) == [("arxiv", 100), ("openalex", 100)]
    found = search(lib, run)
    kept = [h for h in lib.candidate_store.hits(found["id"]) if h["kept"]]
    target = lib.conn.execute("SELECT source_version_id FROM kill_search_query_records WHERE kill_search_id = ?"
                              " AND position = 1 AND rank = 18", (found["id"],)).fetchone()[0]
    assert kept[0]["source_version_id"] == target
    assert found["found"] == found["kept"] + found["rank_cut"] + found["duplicates"] == 25
    assert found["kept"] == 8
    plan = lib.store.existing_step(run["id"], "kill_search_plan")["output"]["merged"]
    assert plan["ranking"]["task"] == ["bounded delay"] and plan["kept"][0]["round_robin_rank"] > 8


@pytest.fixture
def store_lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    yield lib
    lib.conn.close()


def ranked_search(lib):
    s = start(lib, query_block={"setting": [{"term": "synthetic network"}], "task": [{"term": "bounded delay"}]})
    target = json.loads(lib.conn.execute("SELECT target_json FROM runs WHERE id = ?", (s["run_id"],)).fetchone()[0])
    lib.conn.execute("UPDATE runs SET target_json = ? WHERE id = ?", (db.dumps(target | {"plan_version": 2}), s["run_id"]))
    noise = [provider_record(f"SYNTHETIC-{n}", abstract="SYNTHETIC: unrelated text.") for n in range(10)]
    noise[9] = provider_record("SYNTHETIC-target", title="SYNTHETIC bounded delay in a synthetic network",
                               abstract="SYNTHETIC: bounded delay in a synthetic network.")
    records = query(lib, s, noise)
    return s, records


def test_store_reverification_recomputes_the_ranked_cut_and_refuses_tampering(store_lib):
    lib = store_lib
    s, records = ranked_search(lib)
    merged = lib.candidate_store.merge(s["id"], keep=8)
    assert merged["kept"][0]["source_version_id"] == records[9]["source_version_id"]
    depths = {r["source_version_id"]: "abstract" for r in records}
    swapped = merged | {"kept": merged["cut"][:1] + merged["kept"][1:], "cut": merged["kept"][:1] + merged["cut"][1:]}
    rescored = merged | {"kept": [merged["kept"][0] | {"rank_signals": {"bm25": 0.0, "blocks": [0, 0], "joint": [0, 0.0]}},
                                  *merged["kept"][1:]]}
    for forged in (merge_and_cut(lib.candidate_store.query_records(s["id"])), swapped, rescored,
                   merged | {"ranking": merged["ranking"] | {"task": ["other"]}}):
        with pytest.raises(InvalidCandidateInput, match="Merge differs"):
            lib.candidate_store.record_hits(s["id"], forged, depths)
    # A changed stored title changes today's recomputation, so the earlier merge no longer matches.
    lib.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC unrelated' WHERE id = ?", (records[9]["source_version_id"],))
    with pytest.raises(InvalidCandidateInput, match="Merge differs"):
        lib.candidate_store.record_hits(s["id"], merged, depths)
    today = lib.candidate_store.merge(s["id"], keep=8)
    lib.candidate_store.record_hits(s["id"], today, depths)
    hits = lib.candidate_store.hits(s["id"])
    assert [h["source_version_id"] for h in hits] == [r["source_version_id"] for r in today["kept"] + today["cut"]]


def test_a_run_without_plan_version_two_keeps_the_round_robin_cut(store_lib):
    s = start(store_lib)
    records = query(store_lib, s, [provider_record(f"SYNTHETIC-{n}") for n in range(3)])
    assert store_lib.candidate_store.merge(s["id"]) == merge_and_cut(store_lib.candidate_store.query_records(s["id"]))
    store_lib.candidate_store.record_hits(s["id"], merge_and_cut([records]), {r["source_version_id"]: "abstract" for r in records})

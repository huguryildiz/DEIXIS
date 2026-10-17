"""SYNTHETIC checks of plan version 3: backups searched within query rules, concept-level ranking, exported inputs.

Model-free: records, claims and providers are scripted. Passing shows which terms reach a query and the order the cut
follows, not that a kept work is relevant; the rank is a priority signal, never a relevance verdict.
"""
import json

import pytest

from deixis.storage import db
from deixis.workflow.candidates import run as planning
from deixis.workflow.candidates.hits import (concept_scores, concept_text, concepts, merge_and_cut, rank_and_cut,
                                             rank_concepts_and_cut)
from deixis.workflow.candidates.store import InvalidCandidateInput
from deixis.workflow.candidates.terms import compile_alias_queries, compile_queries, block_vocabulary
from fakes import valid_response
from test_candidate_flow import execute, lib, queue_kill, search  # noqa: F401  (lib is a fixture)
from test_candidate_store import make_library, provider_record, query, start

PROVIDERS = ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed", "ieee_xplore"]
SETTING = ["underwater acoustic sensor networks", "underwater sensor networks", "UASN"]
TASK = ["depth-based routing", "vector-based forwarding", "DBR"]
SETTING_BACKUP = ["underwater wireless sensor networks", "UWSN", "underwater acoustic networks"]
TASK_BACKUP = ["VBF"]


def pool(rows):
    per_query = [[{"provider": "openalex", "source_version_id": f"srv_{n:03d}", "work_id": f"wrk_{n:03d}"}
                  for n in range(len(rows))]]
    documents = {f"srv_{n:03d}": {"title": title, "abstract": abstract} for n, (title, abstract) in enumerate(rows)}
    return per_query, documents


def scored(rows, blocks, claim="", backups=None):
    found = concepts(blocks, claim, backups)
    return concept_scores([{"id": f"r{n}", "title": t, "abstract": a} for n, (t, a) in enumerate(rows)], found)


# ---- 1. backups reach the query within the provider's rules, the rest is recorded --------------------------------

def test_a_backup_that_fits_joins_the_main_query_and_one_that_does_not_gets_one_alternative():
    queries = compile_alias_queries(SETTING, TASK, SETTING_BACKUP, TASK_BACKUP, PROVIDERS)
    by = {(q["provider_id"], q["role"]): q for q in queries}
    # Semantic Scholar's bulk syntax has room: every backup is in its one query, nothing is dropped or added.
    bulk = by[("semantic_scholar", "main")]
    assert "uwsn" in bulk["query_text"] and "vbf" in bulk["query_text"]
    assert bulk["dropped_terms"] == bulk["alternative_terms"] == []
    assert ("semantic_scholar", "alternative") not in by
    # OpenAlex allows five Boolean operators: the main query is the chosen terms exactly as plan version 2 wrote it,
    # and the backups go to one alternative query.
    v2 = compile_queries(block_vocabulary(SETTING, TASK), ["openalex"], 6)[0]
    assert by[("openalex", "main")]["query_text"] == v2["query_text"]
    alternative = by[("openalex", "alternative")]["query_text"]
    assert "uwsn" in alternative and "vbf" in alternative and "underwater wireless sensor networks" in alternative
    assert set(by[("openalex", "main")]["alternative_terms"]) == {t.lower() for t in SETTING_BACKUP + TASK_BACKUP}
    # At most one alternative per provider, and only after its main query.
    assert sum(q["role"] == "alternative" for q in queries) <= len({q["provider_id"] for q in queries})
    assert all(queries[i - 1]["provider_id"] == q["provider_id"] and queries[i - 1]["role"] == "main"
               for i, q in enumerate(queries) if q["role"] == "alternative")


def test_names_neither_query_holds_are_recorded_per_provider():
    # Long names hit the 300-character query limit before the operator limit.
    def name(n):
        return f"synthetic electrochemically-intercalated superlattice {n}"
    setting, task = [name("alpha"), name("beta"), name("gamma")], [name("routing")]
    backups = ([name("zeta"), name("eta"), name("theta")], [name("relay")])
    main, alternative = compile_alias_queries(setting, task, *backups, ["openalex"])
    every = set(setting + task + backups[0] + backups[1])
    in_main = {t for t in every if f'"{t}"' in main["query_text"]}
    in_alternative = {t for t in every if f'"{t}"' in alternative["query_text"]}
    assert main["dropped_terms"] == [name("theta")]
    assert set(main["dropped_terms"]) == every - in_main - in_alternative
    assert alternative["dropped_terms"] == main["dropped_terms"]
    assert set(main["alternative_terms"]) == in_alternative - in_main


def test_plan_version_three_charges_one_alternative_per_provider_in_the_frozen_transport(lib):
    plan = lib.planner.preview(lib.rid, queue_kill(lib)["target"]["candidate_id"])
    assert plan["plan_version"] == planning.PLAN_VERSION == 3
    assert plan["transport"] == planning.transport_plan(plan["providers"], 2)
    single = planning.transport_plan(plan["providers"])
    assert plan["budget"]["max_provider_requests"] == 2 * single["max_provider_requests"]
    assert "queries" not in single["providers"][0]  # the follow-up search's plan is unchanged
    assert plan["limits"]["rank"] == "kill_rank.v2"


def test_flow_sends_the_alternative_query_and_records_it(lib):
    def responder(si):
        if si["task_type"] != "kill_search_query":
            return valid_response(si)
        body = json.loads(valid_response(si))
        return json.dumps(body | {
            "setting": [{"term": t, "kind": "topic", "why": "SYNTHETIC"} for t in SETTING],
            "task": [{"term": t, "kind": "method", "why": "SYNTHETIC"} for t in TASK],
            "setting_backup": [{"term": t} for t in SETTING_BACKUP], "task_backup": [{"term": t} for t in TASK_BACKUP]})
    lib.adapter.responder = responder
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    rendered = json.loads(search(lib, run)["rendered_queries_json"])
    assert [q["role"] for q in rendered] == ["main", "alternative"]
    assert [r[1] for r in lib.requests] == [q["query_text"] for q in rendered]
    assert lib.store.run(run["id"])["usage"]["provider_requests"] <= run["budget"]["max_provider_requests"]


# ---- 2. concepts, not name forms -----------------------------------------------------------------------------

def test_a_long_name_and_its_abbreviation_are_one_concept():
    found = {c["id"]: c for c in concepts({"setting": SETTING, "task": TASK}, "",
                                          {"setting": SETTING_BACKUP, "task": TASK_BACKUP})}
    assert (found["task:1"]["forms"], found["task:1"]["short"]) == (["depth based routing"], ["DBR"])
    assert (found["task:2"]["forms"], found["task:2"]["short"]) == (["vector based forwarding"], ["VBF"])
    assert (found["setting:1"]["forms"], found["setting:1"]["short"]) == (["underwater acoustic sensor network"], ["UASN"])
    # Backups joined to no chosen term are the block's uncounted other names.
    assert found["setting:other"]["counted"] is False and found["setting:other"]["short"] == ["UWSN"]


# Sol round 2 finding 2: an abbreviation fitting two long names is not a concept until something resolves it.
def test_an_ambiguous_abbreviation_joins_no_concept_and_is_not_one():
    blocks = {"setting": ["synthetic network"], "task": ["data based routing", "depth based routing", "DBR"]}
    found = concepts(blocks)
    assert [(c["id"], c["counted"]) for c in found if c["block"] == "task"] == \
        [("task:1", True), ("task:2", True), ("task:other", False)]
    single = scored([("SYNTHETIC depth based routing DBR in a synthetic network", None)], blocks)["r0"]
    assert single["blocks"] == (2, 2) and single["joint"] == (0, 0.0)
    # A claim definition resolves it.
    resolved = concepts(blocks, "SYNTHETIC: depth based routing (DBR) is studied.")
    assert [c["short"] for c in resolved if c["id"] == "task:2"] == [["DBR"]]


# Sol round 2 finding 1: one occurrence of a long name never also counts as the shorter name inside it.
def test_a_nested_name_is_read_once_leftmost_longest():
    blocks = {"setting": ["lung cancer"], "task": ["small cell lung cancer", "non-small cell lung cancer"]}
    rows = [("SYNTHETIC non-small cell lung cancer outcomes", "SYNTHETIC: non-small cell lung cancer cohort."),
            ("SYNTHETIC small cell lung cancer versus non-small cell lung cancer", None)]
    only, both = (scored(rows, blocks)[f"r{n}"] for n in range(2))
    assert only["concepts"]["text"] == ["setting:1", "task:2"] and only["joint"] == (0, 0.0)
    assert both["joint"][0] == 2


# Sol round 3 finding 1: overlaps are resolved within a block; a setting name inside a task name still counts.
def test_a_setting_name_inside_a_task_name_still_shows_the_setting():
    blocks = {"setting": ["lung cancer"], "task": ["non-small cell lung cancer", "chemotherapy"]}
    found = scored([("SYNTHETIC chemotherapy in non-small cell lung cancer", None)], blocks)["r0"]
    assert found["concepts"]["title"] == ["setting:1", "task:1", "task:2"] and found["blocks"] == (2, 3)


# Sol round 3 finding 2: an uncounted backup never hides a counted concept.
def test_an_uncounted_backup_never_suppresses_a_counted_concept():
    blocks = {"setting": ["knee osteoarthritis"], "task": ["platelet-rich plasma", "hyaluronic acid"]}
    backups = {"task": ["platelet rich plasma injections"]}
    assert [c["counted"] for c in concepts(blocks, "", backups) if c["block"] == "task"] == [True, True, False]
    row = ("SYNTHETIC platelet rich plasma injections versus hyaluronic acid in knee osteoarthritis", None)
    found = scored([row, ("SYNTHETIC other", None)], blocks, backups=backups)["r0"]
    assert found["joint"][0] == 2 and {"task:1", "task:2", "task:other"} <= set(found["concepts"]["title"])


# Sol round 3 finding 3: a claim definition resolves an ambiguous abbreviation, also to a backup's long name.
def test_a_claim_definition_resolves_an_ambiguous_abbreviation_to_a_backup_name():
    blocks, backups = {"setting": ["synthetic network"], "task": ["data based routing", "DBR"]}, \
        {"task": ["depth based routing"]}
    assert [c["counted"] for c in concepts(blocks, "", backups) if c["block"] == "task"] == [True, False]
    claim = "SYNTHETIC: depth based routing (DBR) outperforms data based routing."
    resolved = [c for c in concepts(blocks, claim, backups) if c["block"] == "task"]
    assert [(c["counted"], c["forms"], c["short"]) for c in resolved] == \
        [(True, ["data based routing"], []), (True, ["depth based routing"], ["DBR"])]
    row = ("SYNTHETIC DBR versus data based routing in a synthetic network", None)
    assert scored([row, ("SYNTHETIC other", None)], blocks, claim, backups)["r0"]["joint"][0] == 2


# Sol finding 1: a backup synonym bound to no chosen term never counts as a concept of its own.
def test_a_backup_synonym_never_makes_one_treatment_look_like_two():
    blocks, backups = {"setting": ["knee pain"], "task": ["acetaminophen", "ibuprofen"]}, {"task": ["paracetamol"]}
    assert [c["counted"] for c in concepts(blocks, "", backups) if c["block"] == "task"] == [True, True, False]
    rows = [("SYNTHETIC paracetamol (acetaminophen) for knee pain", "SYNTHETIC: acetaminophen, also called paracetamol."),
            ("SYNTHETIC acetaminophen versus ibuprofen for knee pain", "SYNTHETIC: a randomized comparison.")]
    one, two = (scored(rows, blocks, backups=backups)[f"r{n}"] for n in range(2))
    assert one["joint"] == (0, 0.0) and two["joint"][0] == 2
    # In a pool of single-treatment works under two names, the direct comparison is ranked first.
    claim = {"text": "SYNTHETIC: acetaminophen relieves knee pain less than ibuprofen.", **blocks,
             "setting_backup": [], "task_backup": backups["task"]}
    single = [(f"SYNTHETIC paracetamol and acetaminophen dosing for knee pain {n}",
               "SYNTHETIC: paracetamol (acetaminophen) for knee pain.") for n in range(8)]
    per_query, documents = pool([*single, ("SYNTHETIC analgesics for knee pain: a trial",
                                           "SYNTHETIC: acetaminophen or ibuprofen for knee pain.")])
    assert rank_concepts_and_cut(per_query, documents, claim)["kept"][0]["source_version_id"] == "srv_008"


# Sol finding 2: a name inside another name is no evidence they are one thing.
def test_contrasting_names_that_contain_each_other_stay_two_concepts():
    blocks = {"setting": ["lung cancer"], "task": ["small cell lung cancer", "non-small cell lung cancer"]}
    assert len([c for c in concepts(blocks) if c["block"] == "task"]) == 2
    row = ("SYNTHETIC small cell lung cancer versus non-small cell lung cancer", "SYNTHETIC: survival compared.")
    assert scored([row, ("SYNTHETIC other", None)], blocks)["r0"]["joint"][0] == 2


# Sol finding 3: abbreviations match case-sensitively, and a record spelling one differently does not match it.
def test_abbreviations_are_case_sensitive_and_a_conflicting_record_definition_blocks_them():
    blocks = {"setting": ["adults"], "task": ["ankylosing spondylitis", "AS", "multiple sclerosis", "MS"]}
    assert scored([("SYNTHETIC treated as usual", "SYNTHETIC: as described.")], blocks)["r0"]["concepts"]["text"] == []
    assert scored([("SYNTHETIC AS in adults", None)], blocks)["r0"]["concepts"]["text"] == ["setting:1", "task:1"]
    row = ("SYNTHETIC MS imaging of AS biopsies", "SYNTHETIC: Mass spectrometry (MS) of ankylosing spondylitis tissue.")
    found = scored([row], blocks)["r0"]
    assert found["concepts"]["blocked_abbreviations"] == ["MS"] and found["concepts"]["text"] == ["task:1"]
    assert found["joint"] == (0, 0.0)
    # A claim spelling a term-list abbreviation differently is ignored.
    found = concepts({"task": ["multiple sclerosis", "MS"]}, "SYNTHETIC: Mass Spectrometry (MS) is used.")
    assert [(c["forms"], c["short"]) for c in found] == [(["multiple sclerosis"], ["MS"])]


def test_a_title_naming_one_method_twice_gets_no_two_item_credit():
    rows = [("SYNTHETIC DBR: depth-based routing for underwater sensor networks", "SYNTHETIC: DBR uses depth only."),
            ("SYNTHETIC DBR versus VBF in underwater sensor networks", "SYNTHETIC: a comparison.")]
    single, both = (scored(rows, {"setting": SETTING, "task": TASK}, backups={"task": TASK_BACKUP})[f"r{n}"]
                    for n in range(2))
    assert single["joint"] == (0, 0.0)
    assert both["joint"][0] == 2


def test_both_concepts_named_only_by_abbreviation_in_the_abstract_get_co_mention():
    row = ("SYNTHETIC performance comparison of routing protocols for underwater sensor networks",
           "SYNTHETIC: VBF and DBR are compared in NS-2 for delivery ratio and energy.")
    noise = ("SYNTHETIC energy-aware clustering", "SYNTHETIC: clustering in sensor networks.")
    # Aliases from the term list.
    with_backups = scored([row, noise], {"setting": SETTING, "task": TASK}, backups={"task": TASK_BACKUP})["r0"]
    assert with_backups["joint"][1] > 0 and with_backups["concepts"]["text"] == ["setting:2", "task:1", "task:2"]
    # The same aliases defined by the claim, with no abbreviation in the term list.
    claim = "SYNTHETIC: depth-based routing (DBR) delivers more than vector-based forwarding (VBF)."
    from_claim = scored([row, noise], {"setting": SETTING, "task": TASK[:2]}, claim)["r0"]
    assert from_claim["joint"][1] > 0
    # Without any alias VBF is unknown: one concept, no co-mention.
    assert scored([row, noise], {"setting": SETTING, "task": TASK[:2]})["r0"]["joint"] == (0, 0.0)


def test_an_abbreviation_the_record_defines_counts_in_its_title():
    row = ("SYNTHETIC DBR and VBF in UWSNs",
           "SYNTHETIC: Depth Based Routing (DBR) and Vector Based Forwarding (VBF) in an Underwater Wireless Sensor "
           "Network (UWSN).")
    found = scored([row], {"setting": ["underwater wireless sensor networks"], "task": TASK[:2]})["r0"]
    assert found["joint"][0] == 2 and found["blocks"][0] == 2
    assert found["concepts"]["record_abbreviations"] == {"setting:1": ["UWSN"], "task:1": ["DBR"], "task:2": ["VBF"]}


def test_blocks_and_co_mention_read_hyphens_spaces_and_plurals_the_same_way():
    assert concept_text("Depth-Based Routing in Underwater Wireless Sensor Networks") == \
        concept_text("depth based routing in underwater wireless sensor network")
    rows = [("SYNTHETIC Depth Based Routing and Vector Based Forwarding in an Underwater Wireless Sensor Network", None),
            ("SYNTHETIC depth-based routing and vector-based forwarding in underwater wireless sensor networks", None)]
    a, b = (scored(rows, {"setting": ["underwater wireless sensor networks"], "task": TASK[:2]})[f"r{n}"] for n in range(2))
    assert a["blocks"] == b["blocks"] == (2, 3) and a["joint"] == b["joint"] and a["joint"][0] == 2
    # A short abbreviation matches whole words only: "HA" is not "hazard".
    assert scored([("SYNTHETIC HAzard ratios of PRP", None)], {"task": ["hyaluronic acid", "HA"]})["r0"]["concepts"]["text"] == []


def test_a_medicine_claim_ranks_the_direct_comparison_above_single_treatment_works():
    claim = {"text": "SYNTHETIC: In adults with knee osteoarthritis, intra-articular platelet-rich plasma injections "
                     "reduce pain more than hyaluronic acid injections at 12 months.",
             "setting": ["knee osteoarthritis"], "task": ["platelet-rich plasma", "hyaluronic acid"],
             "setting_backup": ["gonarthrosis"], "task_backup": ["PRP", "HA"]}
    single = [(f"SYNTHETIC platelet-rich plasma injections for knee osteoarthritis: cohort {n}",
               "SYNTHETIC: PRP injections reduced pain in knee osteoarthritis at 12 months in a cohort.") for n in range(4)]
    single += [(f"SYNTHETIC hyaluronic acid viscosupplementation in knee osteoarthritis: registry {n}",
                "SYNTHETIC: hyaluronic acid injections and pain in knee osteoarthritis over 12 months.") for n in range(4)]
    noise = [(f"SYNTHETIC total knee arthroplasty outcomes {n}", "SYNTHETIC: pain after knee replacement surgery.")
             for n in range(6)]
    target = ("SYNTHETIC intra-articular injections in knee osteoarthritis: a randomized trial",
              "SYNTHETIC: patients received PRP or HA; pain at 12 months was lower with platelet-rich plasma.")
    per_query, documents = pool([*single, *noise, target])
    merged = rank_concepts_and_cut(per_query, documents, claim, keep=8)
    assert merged["kept"][0]["source_version_id"] == f"srv_{len(single) + len(noise):03d}"
    assert merged["kept"][0]["rank_signals"]["joint"][1] > 0
    assert all(r["rank_signals"]["joint"] == [0, 0.0] for r in merged["kept"][1:] + merged["cut"])


# ---- 3. ranking inputs exported per record -----------------------------------------------------------------

def test_each_ranked_record_carries_its_text_hashes_signals_ranks_and_fused_score():
    per_query, documents = pool([("SYNTHETIC DBR versus VBF in UWSNs", "SYNTHETIC: a comparison."),
                                 ("SYNTHETIC LoRa link budget", None)])
    claim = {"text": "SYNTHETIC claim", "setting": SETTING, "task": TASK, "setting_backup": SETTING_BACKUP,
             "task_backup": TASK_BACKUP}
    merged = rank_concepts_and_cut(per_query, documents, claim, keep=8)
    first, second = merged["kept"]
    assert set(first) >= {"rank_signals", "signal_ranks", "rank_inputs", "concepts", "round_robin_rank"}
    assert first["signal_ranks"] == {"bm25": 1.0, "blocks": 1.0, "joint": 1.0}
    assert (first["rank_key"], second["rank_key"]) == (1, 2)
    assert second["rank_inputs"]["abstract_sha256"] is None and second["rank_inputs"]["abstract_chars"] == 0
    assert len(first["rank_inputs"]["title_sha256"]) == 64
    assert merged["ranking"]["version"] == "kill_rank.v2" and merged["ranking"]["concepts"]
    assert json.loads(json.dumps(merged)) == merged
    assert merged == rank_concepts_and_cut(per_query, documents, claim, keep=8)


# ---- old plans and store re-verification ------------------------------------------------------------------

@pytest.fixture
def store_lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    yield lib
    lib.conn.close()


def ranked_search(lib, plan_version):
    s = start(lib, query_block={"setting": [{"term": "synthetic network"}], "task": [{"term": "bounded delay"}],
                                "setting_backup": [{"term": "SN"}], "task_backup": []})
    target = json.loads(lib.conn.execute("SELECT target_json FROM runs WHERE id = ?", (s["run_id"],)).fetchone()[0])
    lib.conn.execute("UPDATE runs SET target_json = ? WHERE id = ?",
                     (db.dumps(target | {"plan_version": plan_version}), s["run_id"]))
    noise = [provider_record(f"SYNTHETIC-{n}", abstract="SYNTHETIC: unrelated text.") for n in range(10)]
    noise[9] = provider_record("SYNTHETIC-target", title="SYNTHETIC bounded delay in a synthetic network",
                               abstract="SYNTHETIC: bounded delay in a synthetic network.")
    return s, query(lib, s, noise)


def test_a_version_two_plan_keeps_the_v1_rank_and_a_version_three_plan_ranks_concepts(store_lib):
    s, _ = ranked_search(store_lib, 2)
    merged = store_lib.candidate_store.merge(s["id"], keep=8)
    assert merged["ranking"]["version"] == "kill_rank.v1" and "signal_ranks" not in merged["kept"][0]
    assert merged["ranking"]["setting"] == ["synthetic network"]  # backups not read by version 2
    lib2 = store_lib
    s3, records = ranked_search(lib2, 3)
    merged3 = lib2.candidate_store.merge(s3["id"], keep=8)
    assert merged3["ranking"]["version"] == "kill_rank.v2" and merged3["ranking"]["setting_backup"] == ["SN"]
    assert merged3["kept"][0]["source_version_id"] == records[9]["source_version_id"]


def test_store_reverification_recomputes_the_concept_cut_and_refuses_tampering(store_lib):
    lib = store_lib
    s, records = ranked_search(lib, 3)
    merged = lib.candidate_store.merge(s["id"], keep=8)
    depths = {r["source_version_id"]: "abstract" for r in records}
    rescored = merged | {"kept": [merged["kept"][0] | {"signal_ranks": {"bm25": 9.0, "blocks": 9.0, "joint": 9.0}},
                                  *merged["kept"][1:]]}
    for forged in (merge_and_cut(lib.candidate_store.query_records(s["id"])), rescored,
                   rank_and_cut(lib.candidate_store.query_records(s["id"]),
                                {r["source_version_id"]: {"title": "x", "abstract": None} for r in records},
                                {"text": "x", "setting": ["x"], "task": ["y"]})):
        with pytest.raises(InvalidCandidateInput, match="Merge differs"):
            lib.candidate_store.record_hits(s["id"], forged, depths)
    lib.candidate_store.record_hits(s["id"], merged, depths)
    assert [h["source_version_id"] for h in lib.candidate_store.hits(s["id"])] == \
        [r["source_version_id"] for r in merged["kept"] + merged["cut"]]


def test_a_version_two_plan_in_the_flow_compiles_only_the_chosen_terms(lib):
    run = queue_kill(lib)
    lib.conn.execute("UPDATE runs SET target_json = ? WHERE id = ?",
                     (db.dumps(run["target"] | {"plan_version": 2}), run["id"]))
    run = lib.store.run(run["id"])
    assert execute(lib, run)["status"] == "completed"
    rendered = json.loads(search(lib, run)["rendered_queries_json"])
    assert len(rendered) == 1 and "role" not in rendered[0]


# Sol round 4: a record's own definition resolves an unresolved abbreviation for that record only.
def test_a_record_definition_resolves_an_ambiguous_abbreviation_for_that_record():
    blocks = {"setting": ["synthetic network"], "task": ["data based routing", "depth based routing", "DBR"]}
    defined = ("SYNTHETIC DBR versus data based routing", "SYNTHETIC: depth based routing (DBR) in a synthetic network.")
    undefined = ("SYNTHETIC DBR versus data based routing", "SYNTHETIC: a synthetic network.")
    conflicting = ("SYNTHETIC DBR versus data based routing", "SYNTHETIC: dynamic battery reserve (DBR) in a network.")
    one, two, three = (scored([defined, undefined, conflicting], blocks)[f"r{n}"] for n in range(3))
    assert one["joint"][0] == 2 and one["concepts"]["record_abbreviations"] == {"task:2": ["DBR"]}
    assert two["joint"] == (0, 0.0)
    assert three["joint"] == (0, 0.0) and three["concepts"]["blocked_abbreviations"] == ["DBR"]


# Sol round 5: spelled as a backup's name, an unresolved abbreviation is blocked in that record, never left counted.
def test_a_record_spelling_an_ambiguous_abbreviation_as_a_backup_blocks_it():
    blocks = {"setting": ["synthetic network"], "task": ["data based routing", "depth based routing", "DBR"]}
    backups = {"setting": [], "task": ["dynamic battery reserve"]}
    row = ("SYNTHETIC DBR versus data based routing", "SYNTHETIC: dynamic battery reserve (DBR) in a synthetic network.")
    got = scored([row], blocks, backups=backups)["r0"]
    assert got["joint"] == (0, 0.0) and got["concepts"]["blocked_abbreviations"] == ["DBR"]

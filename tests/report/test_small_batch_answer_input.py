"""Synthetic D238 allocation and eligibility evidence; no model or scientific validation."""

import pytest

from deixis.workflow import small_batch
from test_abstract_answer_sources import answer_run, bind, candidate, flow_of, setup
from test_criterion_passage_flow import library, page_source, TOPIC_PAGE, CRITERION_PAGE, OFF_PAGE
from deixis.workflow.criterion_passages import compile_phrases


def retrieve(store, rid, run, included, extra, patterns=None, semantic=None):
    flow = flow_of(store)
    flow._checkpoint = lambda *args: None
    return flow._small_batch_answer_passages(run, store.scope(rid), included, extra, semantic, patterns)


def test_frozen_order_and_complete_first_round_before_second_passage(tmp_path):
    store, rid = library(tmp_path)
    a = page_source(store, rid, "a", [OFF_PAGE, TOPIC_PAGE, CRITERION_PAGE], "SYNTHETIC abstract.")
    b = page_source(store, rid, "b", [TOPIC_PAGE] * 8, "SYNTHETIC abstract.")
    c = candidate(store, rid, "c", "SYNTHETIC exercise.", "runs_agree_candidate")
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ?", (rid,))
    run = bind(store, rid, [b, c, a])
    run["budget"]["max_answer_passages"] = 48
    patterns = compile_phrases([{"phrase": "intention to treat"}])["patterns"]
    passages = retrieve(store, rid, run, [a, b], [c], patterns)
    assert [p["source_version_id"] for p in passages[:3]] == [b, a, c]
    assert [p["source_version_id"] for p in passages[3:5]] == [b, a]
    assert sum(p["source_version_id"] == c for p in passages) == 1
    assert sum(p["source_version_id"] == b for p in passages) == 6
    assert passages[0]["kind"] == passages[1]["kind"] == "pdf_page"
    assert passages[1]["text"] in (TOPIC_PAGE, CRITERION_PAGE)


def test_late_included_pdfs_precede_automatic_abstracts_without_rewriting_list(tmp_path):
    store, rid = library(tmp_path)
    abstracts = [candidate(store, rid, str(i), "SYNTHETIC exercise.", "runs_agree_candidate") for i in range(30)]
    pdfs = [page_source(store, rid, f"pdf{i}", [TOPIC_PAGE] * 8, "SYNTHETIC abstract.") for i in range(5)]
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ?", (rid,))
    run = bind(store, rid, [*abstracts, *pdfs], priority=False)
    discovery_id = run["budget"]["inspection"]["list_run_id"]
    listing = store.existing_step(discovery_id, small_batch.LIST_KEY)["output"]
    run["budget"]["max_answer_passages"] = 48
    passages = retrieve(store, rid, run, pdfs, abstracts)
    assert [p["source_version_id"] for p in passages[:29]] == [*pdfs, *abstracts[:24]]
    assert all(sum(p["source_version_id"] == svid for p in passages) >= 4 for svid in pdfs)
    assert len(passages) == 48
    allocation = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]
    assert [item["position"] for item in allocation["items"][:5]] == [31, 32, 33, 34, 35]
    assert all(item["evidence_layer"] == "included_fulltext" and item["reason"] is None
               for item in allocation["items"][:5])
    assert store.existing_step(discovery_id, small_batch.LIST_KEY)["output"] == listing


def test_explicit_user_included_abstract_still_leads_fulltext_layer(tmp_path):
    store, rid = library(tmp_path)
    abstract = page_source(store, rid, "user", [], "SYNTHETIC abstract.")
    pdf = page_source(store, rid, "pdf", [TOPIC_PAGE] * 8, "SYNTHETIC abstract.")
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE source_version_id = ?", (pdf,))
    run = bind(store, rid, [pdf, abstract], priority=False)
    run["budget"]["max_answer_passages"] = 2
    passages = retrieve(store, rid, run, [abstract, pdf], [])
    assert [p["source_version_id"] for p in passages] == [abstract, pdf]


@pytest.mark.parametrize("version", [None, 1, 2])
def test_unsaved_answer_uses_frozen_allocation_version(tmp_path, version):
    store, rid = library(tmp_path)
    abstracts = [candidate(store, rid, str(i), "SYNTHETIC exercise.", "runs_agree_candidate") for i in range(6)]
    pdf = page_source(store, rid, "late pdf", [TOPIC_PAGE] * 8, "SYNTHETIC abstract.")
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ?", (rid,))
    run = bind(store, rid, [*abstracts, pdf], priority=False)
    assert run["budget"]["inspection"]["answer_allocation_version"] == 2
    if version is None:
        run["budget"]["inspection"].pop("answer_allocation_version")
    else:
        run["budget"]["inspection"]["answer_allocation_version"] = version
    run["budget"]["max_answer_passages"] = 8
    import json
    store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(run["budget"]), run["id"]))
    run = store.run(run["id"])
    assert store.existing_step(run["id"], "small_batch:v1:answer_input") is None
    passages = retrieve(store, rid, run, [pdf], abstracts)
    expected = [pdf, *abstracts[:4], pdf, pdf, pdf] if version == 2 else [*abstracts, pdf]
    assert [p["source_version_id"] for p in passages] == expected
    allocation = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]
    assert allocation["allocation_rule"] == ("user_priority_then_included_fulltext_v2"
                                             if version == 2 else "frozen_work_order_v1")


def test_more_included_pdfs_than_budget_remain_bounded_in_frozen_order(tmp_path):
    store, rid = library(tmp_path)
    abstract = candidate(store, rid, "first", "SYNTHETIC exercise.", "runs_agree_candidate")
    pdfs = [page_source(store, rid, str(i), [TOPIC_PAGE] * 3, "SYNTHETIC abstract.") for i in range(50)]
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ?", (rid,))
    run = bind(store, rid, [abstract, *pdfs], priority=False)
    run["budget"]["max_answer_passages"] = 48
    passages = retrieve(store, rid, run, pdfs, [abstract])
    assert [p["source_version_id"] for p in passages] == pdfs[:48]
    allocation = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]
    assert allocation["representation_limit"] == 48
    assert [item["source_version_id"] for item in allocation["items"] if item["reason"]] == [*pdfs[48:], abstract]
    assert len({p["id"] for p in passages}) == len(passages)


def test_d225_exclusions_apply_in_frozen_order_including_pending_pdf(tmp_path):
    store, rid, included, works = setup(tmp_path)
    pdf = page_source(store, rid, "awaiting_pdf_read", [TOPIC_PAGE], "SYNTHETIC abstract.", included=False)
    from deixis.workflow.decisions import DecisionStore
    DecisionStore(store).record(rid, pdf, "runs_agree_candidate")
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ? AND source_version_id = ?",
                       (rid, pdf))
    run = bind(store, rid, [works["no_text"], pdf, works["disagree"], works["out"], works["not_met"],
                            works["never_read"], included])
    assert flow_of(store)._abstract_sources(run, [included]) == [works["no_text"], works["never_read"]]
    step = store.existing_step(run["id"], "answer_abstract_sources")
    assert step["output"]["ordering_rule"] == small_batch.POLICY


def test_more_than_48_eligible_works_have_individual_deferred_records(tmp_path):
    store, rid = library(tmp_path)
    sources = [candidate(store, rid, str(i), "SYNTHETIC exercise.", "runs_agree_candidate") for i in range(51)]
    run = bind(store, rid, list(reversed(sources)))
    run["budget"]["max_answer_passages"] = 48
    run["budget"]["max_candidates"] = 250
    extra = flow_of(store)._abstract_sources(run, [])
    passages = retrieve(store, rid, run, [], extra)
    assert [p["source_version_id"] for p in passages] == list(reversed(sources))[:48]
    step = store.existing_step(run["id"], "small_batch:v1:answer_input")
    assert [i["source_version_id"] for i in step["output"]["items"] if i["reason"] == "answer_budget_deferred"] == sources[:3][::-1]


def test_abstract_heavy_prefix_fills_depth_then_widens_to_48(tmp_path):
    store, rid = library(tmp_path)
    main = page_source(store, rid, "main", [TOPIC_PAGE] * 8, "SYNTHETIC abstract.")
    extra = [candidate(store, rid, str(i), "SYNTHETIC exercise.", "runs_agree_candidate") for i in range(50)]
    run = bind(store, rid, [main, *extra])
    run["budget"]["max_answer_passages"] = 48
    passages = retrieve(store, rid, run, [main], extra)
    # 24 represented works, five depth passages, then 19 later works, all in list order.
    assert [p["source_version_id"] for p in passages] == [main, *extra[:23], *([main] * 5), *extra[23:42]]
    assert len(passages) == len({p["id"] for p in passages}) == 48
    allocation = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]
    assert allocation["passage_ids"] == [p["id"] for p in passages]
    assert [item["source_version_id"] for item in allocation["items"] if item["reason"] is None] == [main, *extra[:42]]
    assert [item["source_version_id"] for item in allocation["items"]
            if item["reason"] == "answer_budget_deferred"] == extra[42:]


def test_mixed_input_has_no_abstract_quarter_quota(tmp_path):
    store, rid = library(tmp_path)
    main = page_source(store, rid, "main", [TOPIC_PAGE] * 5, "SYNTHETIC abstract.")
    extra = [candidate(store, rid, str(i), "SYNTHETIC exercise.", "runs_agree_candidate") for i in range(12)]
    run = bind(store, rid, [main, *extra])
    run["budget"]["max_answer_passages"] = 8
    passages = retrieve(store, rid, run, [main], extra)
    assert [p["source_version_id"] for p in passages] == [main, *extra[:3], main, main, main, main]


def test_answer_binding_survives_later_discovery_and_refuses_a_broken_hash(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = bind(store, rid, [included, *works.values()])
    first = small_batch.answer_listing(store, run)
    bind(store, rid, list(reversed([included, *works.values()])))
    assert small_batch.answer_listing(store, run) == first
    run["budget"]["inspection"]["manifest_hash"] = "wrong"
    with pytest.raises(ValueError, match="binding"):
        small_batch.answer_listing(store, run)


@pytest.mark.parametrize("empty", [False, True])
def test_abstract_only_and_empty_input(tmp_path, empty):
    store, rid = library(tmp_path)
    source = candidate(store, rid, "only", "SYNTHETIC exercise.", "runs_agree_candidate")
    run = bind(store, rid, [source])
    passages = retrieve(store, rid, run, [], [] if empty else [source])
    assert len(passages) == (0 if empty else 1)


def test_user_pdf_included_after_freeze_leads_answer_input(tmp_path):
    store, rid = library(tmp_path)
    original = page_source(store, rid, "original", [TOPIC_PAGE], "SYNTHETIC abstract.")
    run = bind(store, rid, [original])
    added = page_source(store, rid, "user PDF after freeze", [CRITERION_PAGE, TOPIC_PAGE], "SYNTHETIC abstract.")
    store.conn.execute("UPDATE selections SET origin = 'user' WHERE research_id = ? AND source_version_id = ?",
                       (rid, added))
    passages = retrieve(store, rid, run, [original, added], [])
    assert passages[0]["source_version_id"] == added
    item = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]["items"][0]
    assert item["ordering_reason"] == "user_included_outside_frozen_list"
    assert item["reason"] is None


def test_other_missing_and_changed_included_works_are_recorded(tmp_path):
    store, rid = library(tmp_path)
    original = page_source(store, rid, "original", [TOPIC_PAGE], "SYNTHETIC abstract.")
    run = bind(store, rid, [original])
    added = page_source(store, rid, "chain only", [CRITERION_PAGE], "SYNTHETIC abstract.")
    store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ?", (rid,))
    # Metadata changing after freeze must not suppress a currently included answer version.
    store.conn.execute("UPDATE source_versions SET title = 'changed' WHERE id = ?", (original,))
    passages = retrieve(store, rid, run, [original, added], [])
    assert {p["source_version_id"] for p in passages} == {original, added}
    items = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]["items"]
    assert all(i["ordering_reason"] == "included_outside_frozen_list" for i in items)
    assert [i["work_id"] for i in items] == sorted(i["work_id"] for i in items)


def test_resume_reuses_exact_stored_passage_order_without_reranking(tmp_path, monkeypatch):
    store, rid = library(tmp_path)
    source = page_source(store, rid, "pages", [TOPIC_PAGE, CRITERION_PAGE, OFF_PAGE], "SYNTHETIC abstract.")
    run = bind(store, rid, [source])
    first = retrieve(store, rid, run, [source], [])
    saved_step = store.existing_step(run["id"], "small_batch:v1:answer_input")
    legacy = saved_step["output"]
    legacy.pop("allocation_rule")
    legacy.pop("representation_limit")
    for item in legacy["items"]:
        item.pop("evidence_layer")
    store.finish_step(saved_step["id"], "succeeded", output=legacy)
    monkeypatch.setattr(store, "search_passages", lambda *args: pytest.fail("Resume must not rank again"))
    resumed = retrieve(store, rid, run, [source], [], compile_phrases([{"phrase": "bakery"}])["patterns"])
    saved = store.existing_step(run["id"], "small_batch:v1:answer_input")["output"]
    assert [p["id"] for p in resumed] == saved["passage_ids"] == [p["id"] for p in first]


def test_answer_listing_rejects_scope_revision_mismatch(tmp_path):
    store, rid = library(tmp_path)
    source = page_source(store, rid, "pages", [TOPIC_PAGE], "SYNTHETIC abstract.")
    run = bind(store, rid, [source])
    run["scope_revision"] += 1
    with pytest.raises(ValueError, match="scope_revision"):
        small_batch.answer_listing(store, run)


def test_missing_frozen_list_becomes_recorded_failed_answer(tmp_path):
    import asyncio
    from deixis.workflow.flow import RunStopped

    store, rid = library(tmp_path)
    discovery = store.create_run(rid, "discovery", {"inspection": {"policy": small_batch.POLICY}}, None)
    store.update_run(discovery["id"], status="completed")
    run = answer_run(store, rid)
    run["budget"] = small_batch.answer_budget(store, rid, run["scope_revision"], run["budget"])
    flow = flow_of(store)
    flow._held = {}
    with pytest.raises(RunStopped):
        asyncio.run(flow._answer(run, store.scope(rid)))
    failed = store.run(run["id"])
    assert failed["status"] == "failed"
    assert failed["pause_reason"] == "answer_frozen_list_missing"
    assert failed["error"]["list_run_id"] == discovery["id"]


def test_24_work_prefix_uses_depth_before_widening():
    queues = [[{"id": f"{i}:{j}", "source_version_id": str(i)} for j in range(8)] for i in range(30)]
    selected = small_batch.allocate(queues, 48, 6)
    assert [p["id"] for p in selected] == [f"{i}:{j}" for j in range(2) for i in range(24)]
    assert len(small_batch.allocate(queues[:3], 48, 6)) == 18


@pytest.mark.parametrize("limit", [0, 1, 3, 48])
def test_allocation_respects_budget_and_exhausted_queues(limit):
    queues = [[{"id": str(i)}] for i in range(30)]
    selected = small_batch.allocate(queues, limit, 6)
    assert [p["id"] for p in selected] == [str(i) for i in range(min(limit, 30))]

"""Candidates the full-text stage never reached give their abstracts to an `sw` answer (D225).

Built on a store here, with SYNTHETIC records and decisions; no model is called. Passing shows which works enter the
answer input and how much room they get; it says nothing about whether the answer uses them well.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import pytest

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers.common import ProviderRecord
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import ResearchFlow
from deixis.workflow import small_batch
from test_criterion_passage_flow import TOPIC_PAGE, library, page_source


def candidate(store, rid, name, abstract, *codes):
    """One SYNTHETIC search record with an abstract and these decisions, its selection derived from them."""
    record = ProviderRecord(provider_record_id=name, title=f"SYNTHETIC {name}", authors=[], year=None, venue=None,
                            publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
                            version_label=None, abstract=abstract, abstract_origin="provider", identifiers={}, raw={})
    svid, _ = store.upsert_provider_source("known_list", record, None)
    store.add_to_corpus(rid, svid, "search")
    decisions = DecisionStore(store)
    for code in codes:
        decisions.record(rid, svid, code)
    decisions.derive_selection(rid, store.source(svid)["work_id"])
    return svid


def answer_run(store, rid):
    run = store.create_run(rid, "answer", asdict(TEST_EFFORT_BUDGETS["quick"]), None)
    store.update_run(run["id"], status="completed")  # its steps are written here, not by the worker
    return store.run(run["id"])


def bind(store, rid, sources, *, priority=True):
    run = store.create_run(rid, "discovery", {"inspection": {"policy": small_batch.POLICY}}, None)
    versions = {svid: store.source(svid) for svid in sources}
    # The guard compares the stored abstract text, as freeze_list does.
    for svid, version in versions.items():
        version["abstract"] = " ".join(p["text"] for p in store.passages_for(svid) if p["kind"] == "abstract") or None
    listing = {"manifest_hash": "synthetic", "manifest": {"scope_revision": run["scope_revision"], "versions": versions}, "items": [
        {"head": svid, "work_id": versions[svid]["work_id"], "versions": [svid],
         "position": i + 1, "user_priority": priority and i == 0} for i, svid in enumerate(sources)]}
    step = store.step(run["id"], small_batch.LIST_KEY, "code:small_batch_list")
    store.finish_step(step["id"], "succeeded", output=listing)
    store.update_run(run["id"], status="completed")
    answer = answer_run(store, rid)
    answer["budget"] = small_batch.answer_budget(store, rid, answer["scope_revision"], answer["budget"])
    return answer


def frozen_answer(store, rid):
    run = answer_run(store, rid)
    run["budget"] = small_batch.answer_budget(store, rid, run["scope_revision"], run["budget"])
    return run


def flow_of(store):
    flow = object.__new__(ResearchFlow)
    flow.store = store
    return flow


def setup(tmp_path):
    store, rid = library(tmp_path)
    included = page_source(store, rid, "included", [TOPIC_PAGE], "SYNTHETIC an included abstract on exercise.")
    works = {
        "never_read": candidate(store, rid, "never_read", "SYNTHETIC exercise lowered fatigue.", "runs_agree_candidate"),
        "no_text": candidate(store, rid, "no_text", "SYNTHETIC exercise and fatigue.", "runs_agree_candidate",
                             "no_fulltext"),
        "out": candidate(store, rid, "out", "SYNTHETIC exercise in mice.", "runs_agree_out_of_scope"),
        "not_met": candidate(store, rid, "not_met", "SYNTHETIC exercise and fatigue, no trial.", "runs_agree_candidate",
                             "criterion_absent"),
        "disagree": candidate(store, rid, "disagree", "SYNTHETIC fatigue.", "runs_agree_candidate",
                              "fulltext_runs_disagree"),
    }
    bind(store, rid, [included, *works.values()])
    return store, rid, included, works


def test_only_candidates_without_full_text_enter_and_excluded_works_never_do(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = frozen_answer(store, rid)
    sources = flow_of(store)._abstract_sources(run, [included])
    assert sources == [works["never_read"], works["no_text"]]
    step = store.existing_step(run["id"], "answer_abstract_sources")
    assert step["output"]["by_decision"] == {"abstract/runs_agree_candidate": 1, "fulltext/no_fulltext": 1}


def test_a_work_a_person_decided_or_excluded_never_enters(tmp_path):
    store, rid, included, works = setup(tmp_path)
    version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?",
                                 (works["never_read"],)).fetchone()[0]
    store.set_user_selection(rid, works["never_read"], "excluded", version, "SYNTHETIC not this one")
    assert flow_of(store)._abstract_sources(frozen_answer(store, rid), [included]) == [works["no_text"]]


def test_a_resumed_run_keeps_the_list_its_first_pass_stored(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = frozen_answer(store, rid)
    first = flow_of(store)._abstract_sources(run, [included])
    DecisionStore(store).record(rid, works["never_read"], "criterion_absent")
    assert flow_of(store)._abstract_sources(run, [included]) == first


def test_zero_includes_still_obeys_max_candidates(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = frozen_answer(store, rid)
    run["budget"]["max_candidates"] = 1
    assert flow_of(store)._abstract_sources(run, []) == [works["never_read"]]


@pytest.mark.parametrize('excluded', [False, True])
def test_chain_no_fulltext_candidate_reaches_abstract_input_unless_user_excluded(tmp_path, excluded):
    store, rid, included, works = setup(tmp_path)
    chained = candidate(store, rid, 'chain_only', 'SYNTHETIC exercise lowered fatigue in a trial.',
                        'runs_agree_candidate', 'no_fulltext')
    run = bind(store, rid, [included, chained, *works.values()])
    if excluded:
        version = store.conn.execute('SELECT version FROM selections WHERE source_version_id=?', (chained,)).fetchone()[0]
        store.set_user_selection(rid, chained, 'excluded', version, 'SYNTHETIC excluded chain work')
    run['budget']['max_candidates'] = 1
    flow = flow_of(store)
    sources = flow._abstract_sources(run, [included])
    # The included head uses no candidate slot; the frozen list places this chain work next.
    assert sources == [works['never_read'] if excluded else chained]
    flow._checkpoint = lambda *args: None
    passages = flow._small_batch_answer_passages(run, store.scope(rid), [], sources, None, None)
    assert (chained in {p['source_version_id'] for p in passages}) is (not excluded)
    assert all(p['kind'] == 'abstract' for p in passages)
    assert store.existing_step(run['id'], 'answer_abstract_sources')['output']['ordering_rule'] == small_batch.POLICY


def test_zero_includes_does_not_use_an_older_revisions_candidate(tmp_path):
    store, rid, included, works = setup(tmp_path)
    # SYNTHETIC stale decision: the frozen list is current, the decision belongs to an older question.
    store.conn.execute("UPDATE stage_decisions SET scope_revision = 0 WHERE source_version_id = ?",
                       (works["never_read"],))
    assert flow_of(store)._abstract_sources(frozen_answer(store, rid), []) == [works["no_text"]]


def test_a_work_a_person_excludes_after_the_list_was_stored_leaves_the_resumed_run(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = frozen_answer(store, rid)
    flow_of(store)._abstract_sources(run, [included])
    version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?",
                                 (works["no_text"],)).fetchone()[0]
    store.set_user_selection(rid, works["no_text"], "excluded", version, "SYNTHETIC excluded while paused")
    assert flow_of(store)._abstract_sources(run, [included]) == [works["never_read"]]


def test_a_work_with_pdf_text_is_not_abstract_only_before_or_after_the_list_was_stored(tmp_path):
    store, rid, included, works = setup(tmp_path)
    with_text = page_source(store, rid, "with_text", [TOPIC_PAGE], "SYNTHETIC exercise and fatigue.", included=False)
    DecisionStore(store).record(rid, with_text, "runs_agree_candidate")
    bind(store, rid, [included, with_text, works["never_read"], works["no_text"]])
    run = frozen_answer(store, rid)
    assert flow_of(store)._abstract_sources(run, [included]) == [works["never_read"], works["no_text"]]
    page_source(store, rid, "no_text", [TOPIC_PAGE], "SYNTHETIC exercise and fatigue.", included=False)
    assert flow_of(store)._abstract_sources(run, [included]) == [works["never_read"]]


@pytest.mark.parametrize("source_scope, discovery_status", [
    ("attached_and_academic", "failed"),
    ("attached_and_academic", "cancelled"),
    ("attached", None),
])
def test_unbound_sw_answer_has_no_automatic_abstract_route(tmp_path, monkeypatch, source_scope, discovery_status):
    store, _ = library(tmp_path)
    rid = store.create_research("SYNTHETIC exercise and fatigue?", source_scope, "quick", ["openalex"],
                                "fake", "fake-model", None, search_workflow="sw")
    included = page_source(store, rid, "attached", [TOPIC_PAGE], "SYNTHETIC included abstract.")
    if discovery_status is not None:
        discovery = store.create_run(rid, "discovery", {"inspection": {"policy": small_batch.POLICY}}, None)
        abstract = candidate(store, rid, "candidate", "SYNTHETIC exercise lowered fatigue.")
        decisions = DecisionStore(store)
        ranking = store.step(discovery["id"], "ranking", "code:ranking")
        decisions.save_ranks(ranking["id"], rid, [
            {"source_version_id": abstract, "signal": "inspection", "rank": 1, "available": True},
        ])
        store.finish_step(ranking["id"], "succeeded", output={"seeds": []})
        abstract_step = store.step(discovery["id"], "abstract:synthetic", "code:abstract")
        decisions.record(rid, abstract, "runs_agree_candidate", step_id=abstract_step["id"])
        decisions.derive_selection(rid, store.source(abstract)["work_id"])
        store.finish_step(abstract_step["id"], "succeeded", output={"sources": [abstract]})
        store.update_run(discovery["id"], status=discovery_status)
        assert decisions.latest_ranking(rid, discovery["scope_revision"]) == [abstract]
        assert decisions.work_outcome(rid, store.source(abstract)["work_id"])["outcome"] == "candidate"

    run = frozen_answer(store, rid)
    assert not small_batch.enabled(run["budget"])
    flow = flow_of(store)
    scope = store.scope(rid)
    assert flow._abstract_sources(run, [included]) == []
    assert store.existing_step(run["id"], "answer_abstract_sources") is None
    expected = flow._retrieve(rid, scope, [included], run["budget"]["max_answer_passages"], None, [])
    assert expected

    async def skip(*args, **kwargs):
        return None

    class AnswerInputCaptured(Exception):
        pass

    async def capture_answer(*args, **kwargs):
        assert kwargs["passage_rows"] == expected
        assert kwargs["source_ids"] == [included]
        raise AnswerInputCaptured

    monkeypatch.setattr(flow, "_inspect", skip)
    monkeypatch.setattr(flow, "_read_equations", skip)
    monkeypatch.setattr(flow, "_semantic_ranking", skip)
    monkeypatch.setattr(flow, "_criterion_phrases", lambda *args: [])
    monkeypatch.setattr(flow, "_checkpoint", lambda *args: None)
    monkeypatch.setattr(flow, "_model_step", capture_answer)
    with pytest.raises(AnswerInputCaptured):
        asyncio.run(flow._answer(run, scope))
    assert store.existing_step(run["id"], "answer_abstract_sources") is None

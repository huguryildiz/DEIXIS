"""Candidates the full-text stage never reached give their abstracts to an `sw` answer (D225).

Built on a store here, with SYNTHETIC records and decisions; no model is called. Passing shows which works enter the
answer input and how much room they get; it says nothing about whether the answer uses them well.
"""

from __future__ import annotations

from dataclasses import asdict

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers.common import ProviderRecord
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import ABSTRACT_ROOM_DIVISOR, ResearchFlow
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


def ranked(store, rid, svids):
    run = store.create_run(rid, "discovery", {}, None)
    step = store.step(run["id"], "ranking", "code:ranking")
    store.finish_step(step["id"], "succeeded", output={})
    store.update_run(run["id"], status="completed")
    DecisionStore(store).save_ranks(step["id"], rid, [{"source_version_id": svid, "signal": "inspection", "rank": i + 1,
                                                       "available": 1} for i, svid in enumerate(svids)])


def answer_run(store, rid):
    run = store.create_run(rid, "answer", asdict(TEST_EFFORT_BUDGETS["quick"]), None)
    store.update_run(run["id"], status="completed")  # its steps are written here, not by the worker
    return store.run(run["id"])


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
    ranked(store, rid, [included, *works.values()])
    return store, rid, included, works


def test_only_candidates_without_full_text_enter_and_excluded_works_never_do(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = answer_run(store, rid)
    sources = flow_of(store)._abstract_sources(run, [included])
    assert sources == [works["never_read"], works["no_text"]]
    step = store.existing_step(run["id"], "answer_abstract_sources")
    assert step["output"]["by_decision"] == {"abstract/runs_agree_candidate": 1, "fulltext/no_fulltext": 1}


def test_a_work_a_person_decided_or_excluded_never_enters(tmp_path):
    store, rid, included, works = setup(tmp_path)
    version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?",
                                 (works["never_read"],)).fetchone()[0]
    store.set_user_selection(rid, works["never_read"], "excluded", version, "SYNTHETIC not this one")
    assert flow_of(store)._abstract_sources(answer_run(store, rid), [included]) == [works["no_text"]]


def test_a_resumed_run_keeps_the_list_its_first_pass_stored(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = answer_run(store, rid)
    first = flow_of(store)._abstract_sources(run, [included])
    DecisionStore(store).record(rid, works["never_read"], "criterion_absent")
    assert flow_of(store)._abstract_sources(run, [included]) == first


def test_abstract_sources_give_only_their_abstract_from_a_quarter_of_the_room(tmp_path):
    store, rid, included, works = setup(tmp_path)
    extra = [works["never_read"], works["no_text"]]
    limit = 4
    passages = flow_of(store)._retrieve(rid, store.scope(rid), [included, *extra], limit, abstract_only=set(extra))
    given = [p for p in passages if p["source_version_id"] in extra]
    assert len(given) == limit // ABSTRACT_ROOM_DIVISOR == 1
    assert all(p["kind"] == "abstract" for p in given)
    assert len(passages) <= limit and {p["source_version_id"] for p in passages} - set(extra) == {included}


def test_without_abstract_sources_the_input_is_what_it_was(tmp_path):
    store, rid, included, works = setup(tmp_path)
    flow = flow_of(store)
    assert flow._retrieve(rid, store.scope(rid), [included], 6, abstract_only=set()) == \
        flow._retrieve(rid, store.scope(rid), [included], 6)


def test_a_work_a_person_excludes_after_the_list_was_stored_leaves_the_resumed_run(tmp_path):
    store, rid, included, works = setup(tmp_path)
    run = answer_run(store, rid)
    flow_of(store)._abstract_sources(run, [included])
    version = store.conn.execute("SELECT version FROM selections WHERE source_version_id = ?",
                                 (works["no_text"],)).fetchone()[0]
    store.set_user_selection(rid, works["no_text"], "excluded", version, "SYNTHETIC excluded while paused")
    assert flow_of(store)._abstract_sources(run, [included]) == [works["never_read"]]


def test_a_work_with_pdf_text_is_not_abstract_only_before_or_after_the_list_was_stored(tmp_path):
    store, rid, included, works = setup(tmp_path)
    with_text = page_source(store, rid, "with_text", [TOPIC_PAGE], "SYNTHETIC exercise and fatigue.", included=False)
    DecisionStore(store).record(rid, with_text, "runs_agree_candidate")
    ranked(store, rid, [included, with_text, works["never_read"], works["no_text"]])
    run = answer_run(store, rid)
    assert flow_of(store)._abstract_sources(run, [included]) == [works["never_read"], works["no_text"]]
    page_source(store, rid, "no_text", [TOPIC_PAGE], "SYNTHETIC exercise and fatigue.", included=False)
    assert flow_of(store)._abstract_sources(run, [included]) == [works["never_read"]]

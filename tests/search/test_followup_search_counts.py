"""Follow-up searches (D92) are counted apart from the research's first search.

Records, runs, steps and the follow-up search's frozen found and summary outputs are SYNTHETIC and written straight
into the store; no model or provider is called. Passing shows which stored rows each count reads; it says nothing
about whether a follow-up search finds better works.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deixis.storage import db
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.features.report.report_review_methodology import render_review_methodology
from deixis.workflow.run.store import Store
from deixis.workflow.features.tables.tables import TableStore
from test_prisma_s import Search
from test_queue import BUDGET

QUESTION = "SYNTHETIC which of these works report a field trial?"


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def discovered(store):
    """A research whose discovery searched twice, kept hits, and whose model read one abstract."""
    lib = Search(store, "channels")
    first = lib.records(2)
    lib.page("search:0", first, total=2)
    lib.page("search:1", lib.records(1), provider="arxiv", query="SYNTHETIC second", total=1)
    held = store.find_source_by_identifier("openalex", first[0].provider_record_id)
    step = store.step(lib.run, "abstract:0", "model:abstract")
    store.finish_step(step["id"], "succeeded", output={})
    lib.ds.add_proposal(lib.rid, held, "abstract", step["id"], 1, "candidate")
    return lib, first


def followup_search(lib, held_record, *, unsent=True):
    """A completed follow-up search for a published turn's question: two new records and one the research already
    held, admitted from request 0; request 1 was sent and never admitted (no `search_runs` row)."""
    store = lib.store
    answer_run = store.create_run(lib.rid, "followup_answer", {}, None)["id"]
    store.update_run(answer_run, status="completed")
    turn_id = db.new_id("fut")
    store.conn.execute("INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at)"
                       " VALUES (?, ?, 1, ?, ?, 'pending', ?)", (turn_id, lib.rid, QUESTION, answer_run, db.now()))
    store.conn.commit()
    run = store.create_run(lib.rid, "followup_search", BUDGET, None, {"turn_id": turn_id, "attempt": 1})["id"]
    new = lib.records(2, prefix="F")
    records = new + [held_record]
    step = store.step(run, "followup_search:search:0", "provider_search:openalex")
    store.record_search(
        dict(research_id=lib.rid, run_id=run, step_id=step["id"], scope_revision=1, provider="openalex",
             query_text="SYNTHETIC follow-up query", request_description="GET https://api.example.org/works",
             access_mode="keyless", status="completed", delivery_class=None, result_count=len(records),
             provider_total=90, page_limit=50, error_json=None, raw_payload_path=None),
        "openalex", records, None, step["id"], "succeeded", keep_candidate=True,
        step_output={"status": "completed", "provider_id": "openalex", "query_text": "SYNTHETIC follow-up query"})
    requests = [{"position": 0, "provider_id": "openalex", "endpoint": "keyword", "query_text": "SYNTHETIC follow-up query",
                 "status": "completed", "records": 3, "reason": None}]
    if unsent:
        sent = store.step(run, "followup_search:search:1", "provider_search:semantic_scholar")
        store.finish_step(sent["id"], "succeeded", output={"status": "completed", "provider_id": "semantic_scholar",
                                                           "query_text": "SYNTHETIC second follow-up", "records": []})
        requests.append({"position": 1, "provider_id": "semantic_scholar", "endpoint": "bulk",
                         "query_text": "SYNTHETIC second follow-up", "status": "admission_skipped", "records": 0,
                         "reason": "cancelled_before_admission"})
    versions = [store.find_source_by_identifier("openalex", r.provider_record_id) for r in records]
    works = [{"work_id": lib.work_of(svid), "state": "new" if i < 2 else "already_here", "versions": [svid],
              "best_rank": i + 1} for i, svid in enumerate(versions)]
    counts = {"records": 3, "new": 2, "already_here": 1, "removed_before": 0}
    found = store.step(run, "followup_search:found", "code:followup_search_found")
    store.finish_step(found["id"], "succeeded", output={"works": works, "counts": counts})
    # The run's screening read one of its new works: a proposal of the follow-up run, not of the search.
    screen = store.step(run, "followup_search:abstract:0", "model:abstract")
    store.finish_step(screen["id"], "succeeded", output={})
    lib.ds.add_proposal(lib.rid, versions[0], "abstract", screen["id"], 1, "candidate")
    summary = store.step(run, "followup_search:summary", "code:followup_search_summary")
    store.finish_step(summary["id"], "succeeded", output={
        "requests": requests, "not_screened": [],
        "counts": counts | {"screen_planned": 2, "code_decided": 1, "sent_to_model": 1,
                            "model_result": {"candidate": 1}, "candidates": 1, "not_screened": 0}})
    store.update_run(run, status="completed")
    return run, turn_id, versions


def search_numbers(lib):
    view = lib.view()
    counts = view["counts"]
    export = lib.export()
    # The search's boxes; the others (works in the revision, buckets, included) are research-wide by design.
    boxes = {b["key"]: b["count"] for b in counts["flow_boxes"]["boxes"]
             if b["key"] in ("rows_returned", "chain_rows_returned", "works_found_by_search", "abstract_read_by_model")}
    items = {i["number"]: i for i in export["items"]}
    return {"found": counts["found"], "unread": counts["unread"], "boxes": boxes,
            "funnel": {k: v for k, v in counts["funnel"].items() if k not in ("included", "unique_in_research")},
            "table": [(g["provider"], g["query_text"], g["rows_returned"]) for g in export["search_table"]],
            "item15": items[15]["values"], "item16_hits": items[16]["values"]["tracked_candidate_hits"],
            "item12": items[12]["text"], "item1": items[1]["text"]}


def test_a_follow_up_search_leaves_the_first_search_counts_as_they_were(store):
    lib, first = discovered(store)
    before = search_numbers(lib)
    run, turn_id, versions = followup_search(lib, first[0])
    after = search_numbers(lib)
    assert after == before
    assert before["found"] == 3 and before["boxes"]["abstract_read_by_model"] == 1

    counts = lib.view()["counts"]
    assert counts["found_followup"] == 3 and counts["followup_new_works"] == 2
    # Corpus totals stay research-wide: the two new works are in the research.
    assert counts["unique"] == 5 and counts["funnel"]["unique_in_research"] == 5 and counts["funnel"]["unique"] == 3

    block = counts["flow_boxes"]["followup_searches"]
    assert block == [{"run_id": run, "turn_id": turn_id, "created_at": block[0]["created_at"], "status": "completed",
                      "records": 3, "new": 2, "already_here": 1, "removed_before": 0, "code_decided": 1,
                      "sent_to_model": 1, "model_result": {"candidate": 1}, "candidates": 1}]
    assert sorted(counts["flow_boxes"]["followup_only_works"]) == sorted(lib.work_of(v) for v in versions[:2])


def test_sources_name_the_follow_up_searches_that_found_each_work(store):
    lib, first = discovered(store)
    run, turn_id, versions = followup_search(lib, first[0])
    sources = {s["source_version_id"]: s for s in lib.view()["sources"]}
    assert sources[versions[0]]["followup_searches"] == [{"run_id": run, "turn_id": turn_id, "state": "new"}]
    assert sources[versions[2]]["followup_searches"] == [{"run_id": run, "turn_id": turn_id, "state": "already_here"}]
    untouched = store.find_source_by_identifier("openalex", first[1].provider_record_id)
    assert sources[untouched]["followup_searches"] == []
    rows = {s["run_kind"] for s in lib.view()["search_runs"]}
    assert rows == {"discovery", "followup_search"}


def test_prisma_s_lists_follow_up_searches_apart_with_every_sent_request(store):
    lib, first = discovered(store)
    run, turn_id, _ = followup_search(lib, first[0])
    export = lib.export()
    assert all(g["run_id"] == lib.run for g in export["search_table"])
    [entry] = export["followup_searches"]
    assert (entry["run_id"], entry["turn_id"], entry["question"], entry["status"]) == (run, turn_id, QUESTION, "completed")
    assert [(r["position"], r["provider"], r["query_text"], r["status"], r["records"]) for r in entry["requests"]] == [
        (0, "openalex", "SYNTHETIC follow-up query", "completed", 3),
        (1, "semantic_scholar", "SYNTHETIC second follow-up", "admission_skipped", 0)]
    assert entry["records_kept"] == 3 and entry["new_works"] == 2 and all(r["date"] for r in entry["requests"])
    # Not an "other method": item 7 still reads only what the person brought.
    assert "follow-up" not in next(i for i in export["items"] if i["number"] == 7)["text"].lower()
    from deixis.workflow.search import prisma_s
    text = prisma_s.markdown(export)
    assert "## Follow-up searches" in text and QUESTION in text and "SYNTHETIC second follow-up" in text


def start(store, lib, run_id):
    ResearchFlow._answer_start_snapshot(SimpleNamespace(store=store), store.run(run_id), store.included_works(lib.rid), 1)


def table(store, lib):
    tables = TableStore(store)
    table_id = tables.create_table(lib.rid, "Study table", None, None, None)
    tables.add_column(lib.rid, table_id, {"name": "Trial", "instruction": "SYNTHETIC", "answer_format": "text",
                                          "options": None, "allow_multiple": False, "unit_hint": None}, 1, None)
    return table_id


def methodology(snapshot):
    numbers = {"corpus": snapshot["corpus"], "full_text_ratio": 0.0, "fetch_pdf": 0, "pdf_other_copy": 0}
    if snapshot.get("followup_searches"):
        numbers["followup_searches"] = snapshot["followup_searches"]
    return render_review_methodology(numbers, "en", providers="openalex", queries="q", compiler_versions="v",
                                     screening_models="m", screening_criteria="c", chain_provenance="")

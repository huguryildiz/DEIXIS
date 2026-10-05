"""The Method box's data under an `sw` answer: searches, selection, extraction, limits and evidence base.

Records, searches and the answer are SYNTHETIC and written straight into the store; no model or provider is called.
Passing shows which stored row each field reads; it says nothing about whether the answer is good.
"""

from __future__ import annotations

import time

import pytest

from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow import method_summary
from deixis.workflow.store import Store
from test_probes import Probe
from test_queue import body
from test_prisma_s import Search


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def answered(lib, full, abstract_only, limitations=()):
    """A valid answer citing `full` (a PDF-backed work) and `abstract_only` (an abstract passage)."""
    store = lib.store
    lib.text(full, ["SYNTHETIC page one states the rule."])
    abstract = store._insert_passage(abstract_only, None, "abstract", None, None, "provider", None, None,
                                     "SYNTHETIC abstract of the second work.")
    page = store.passages_for(full)[0]["id"]
    run = store.create_run(lib.rid, "answer", {}, None)
    step = store.step(run["id"], "grounded_answer", "model:grounded_answer")
    input_id = db.new_id("sti")
    store.insert_step_input(step["id"], lib.rid, run["id"], 0,
                            {"step_input_id": input_id, "task_type": "grounded_answer", "scope_revision": 1,
                             "skill_package_hash": "sha256:synthetic",
                             "sources": [{"source_id": full}, {"source_id": abstract_only}],
                             "passages": [{"passage_id": page}, {"passage_id": abstract}]}, "b", "d", "m", {})
    aid = store.save_answer(
        lib.rid, run["id"], step["id"], input_id, 1, "structurally_valid",
        {"title": "SYNTHETIC", "answer_language": "en", "limitations": list(limitations),
         "claims": [{"claim_label": "c1", "section": "A", "text": "SYNTHETIC claim.", "support_type": "source_stated"}]}, {},
        [{"claim_label": "c1", "passage_id": page, "source_id": full, "anchor_text": "states the rule", "anchor_match": "exact"},
         {"claim_label": "c1", "passage_id": abstract, "source_id": abstract_only, "anchor_text": "abstract",
          "anchor_match": "exact"}])
    store.update_run(run["id"], status="completed")
    return aid, run["id"]


def test_each_part_reads_its_stored_rows(store):
    lib = Search(store, "channels")
    lib.page("search:0", lib.records(2), number=0, total=40)
    lib.page("search:1", lib.records(1), provider="arxiv", query="SYNTHETIC second", total=1)
    first, second = lib.work(), lib.work()
    # A later protocol of the same revision carries the approval (protocol rows are immutable).
    store.freeze_protocol(lib.rid, 1, body(lib.field) | {"approval": {"approved_by": "no_warning"}},
                          reason="SYNTHETIC approval recorded")
    time.sleep(0.02)
    aid, run_id = answered(lib, first, second, [{"kind": "access", "text": "SYNTHETIC abstract only."},
                                                {"kind": "scope", "text": "SYNTHETIC scope."}])
    snapshot = store.step(run_id, "answer_start_snapshot", "code:answer_start_snapshot")
    store.finish_step(snapshot["id"], "succeeded", output={
        "flow": {"works": 120, "five": {"included": 7, "not_met": 30, "waiting_for_pdf": 4, "not_read": 50}},
        "included": 7, "selection_revision": 1, "scope_revision": 1})
    table = store.conn.execute("INSERT INTO evidence_tables (id, research_id, title, version, idempotency_key, created_at,"
                               " updated_at) VALUES ('tbl_s', ?, 'Study table', 1, ?, ?, ?)",
                               (lib.rid, f"{lib.rid}:study_table:answer:{aid}:table", db.now(), db.now()))
    for position, accepted in enumerate(("automatic", None)):
        store.conn.execute("INSERT INTO table_columns (id, table_id, position, origin, accepted_by, created_at)"
                           " VALUES (?, 'tbl_s', ?, 'model_suggestion', ?, ?)", (f"col{position}", position, accepted, db.now()))
        store.conn.execute("INSERT INTO column_revisions (column_id, revision, name, instruction, answer_format, created_at)"
                           " VALUES (?, 1, ?, 'SYNTHETIC', 'text', ?)", (f"col{position}", f"Column {position}", db.now()))
    store.conn.commit()

    data = method_summary.method_summary(store, lib.rid, aid)

    found = {(q["provider"], q["query"]): (q["records_read"], q["provider_total"]) for q in data["search"]["queries"]}
    assert found[("openalex", "SYNTHETIC query")] == (2, 40) and found[("arxiv", "SYNTHETIC second")] == (1, 1)
    assert data["search"]["records_read"] >= 3 and data["search"]["chaining"]["ran"] is False
    sel = data["selection"]
    assert (sel["works_found"], sel["included"], sel["not_met"], sel["waiting_for_pdf"], sel["not_read"]) == (120, 7, 30, 4, 50)
    assert sel["criterion"] == "SYNTHETIC the paper states both parts."
    assert sel["vocabulary_review"]["approved_by"] == "no_warning" and sel["vocabulary_review"]["reviewed_by_person"] is False
    assert data["extraction"] == {"table": True, "columns": ["Column 0", "Column 1"], "columns_accepted_automatically": 1}
    assert data["limitations"] == {"access": {"given": 2, "full_text": 1, "abstract_only": 1, "no_passage": 0},
                                   "answer_limitations": 2, "access_limitations": 1}
    assert data["evidence_base"] == {"cited_sources": 2, "year_min": 2026, "year_max": 2026}
    assert data["not_measured"]


def test_an_answer_without_snapshot_or_table_reports_what_is_missing(store):
    lib = Probe(store, "channels")
    first, second = lib.work(), lib.work()
    aid, _ = answered(lib, first, second)
    data = method_summary.method_summary(store, lib.rid, aid)
    assert data["selection"]["works_found"] is None and data["selection"]["snapshot"] is False
    assert data["extraction"]["table"] is False and data["limitations"]["access_limitations"] == 0


def test_unknown_answer_is_refused(store):
    lib = Probe(store, "channels")
    with pytest.raises(method_summary.UnknownAnswer):
        method_summary.method_summary(store, lib.rid, "ans_missing")


def _later(lib, store):
    """Everything a later discovery run adds: a search page, a protocol, a fulltext plan and attempt, a model reading, a person decision."""
    time.sleep(0.02)
    lib.page("search:9", lib.records(3), provider="arxiv", query="SYNTHETIC later", total=3)
    store.freeze_protocol(lib.rid, 1, body(lib.field) | {"approval": {"approved_by": "user"}, "inclusion_criterion": "SYNTHETIC later criterion"},
                          reason="SYNTHETIC later protocol")
    run = lib.new_run("discovery")
    store.finish_step(store.step(run, "fulltext_work:later", "code:fulltext_work")["id"], "succeeded", output={})
    svid = lib.work()
    step = store.step(run, "abstract:later", "model:abstract")
    store.finish_step(step["id"], "succeeded", output={})
    DecisionStore(store).add_proposal(lib.rid, svid, "abstract", step["id"], 1, "candidate")
    DecisionStore(store).record(lib.rid, svid, "all_parts_verified")
    store.conn.execute("UPDATE stage_decisions SET decided_by = 'human' WHERE source_version_id = ?", (svid,))
    store.conn.commit()


def test_a_later_run_or_protocol_does_not_change_an_earlier_answer(store):
    lib = Search(store, "channels")
    lib.page("search:0", lib.records(2), total=2)
    first, second = lib.work(), lib.work()
    aid, _ = answered(lib, first, second)
    before = method_summary.method_summary(store, lib.rid, aid)
    _later(lib, store)
    assert method_summary.method_summary(store, lib.rid, aid) == before
    assert before["selection"]["criterion"] == "SYNTHETIC the paper states both parts."


def test_counts_come_from_records_not_from_a_plan_or_the_flow_total(store):
    lib = Search(store, "channels")
    first, second = lib.work(), lib.work()
    run = lib.new_run("discovery")
    plan = store.step(run, "fulltext_plan", "code:fulltext_plan")
    store.finish_step(plan["id"], "succeeded", output={"works": [first, second]})  # planned, never attempted
    work = store.step(run, f"fulltext_work:{first}", "code:fulltext_work")
    store.finish_step(work["id"], "succeeded", output={})
    aid, run_id = answered(lib, first, second)
    snap = store.step(run_id, "answer_start_snapshot", "code:answer_start_snapshot")
    store.finish_step(snap["id"], "succeeded", output={"flow": {"works": 500, "five": {"included": 1, "not_met": 0, "waiting_for_pdf": 0, "not_read": 0}}})
    sel = method_summary.method_summary(store, lib.rid, aid)["selection"]
    assert sel["works_found"] == 500 and sel["screened"] == 0  # found is the flow total; screened needs a decision row
    assert sel["full_text_attempted"] == 1  # one attempt ran, two were planned


def test_model_and_person_readings_are_zero_when_nothing_is_recorded(store):
    lib = Probe(store, "channels")
    first, second = lib.work(), lib.work()
    aid, _ = answered(lib, first, second)
    sel = method_summary.method_summary(store, lib.rid, aid)["selection"]
    assert (sel["abstract_read"], sel["full_text_read"], sel["person_decisions"]) == (0, 0, 0)


def test_person_decisions_and_model_readings_are_counted(store):
    lib = Search(store, "channels")
    first, second = lib.work(), lib.work()
    step = store.step(lib.run, "abstract:x", "model:abstract")
    store.finish_step(step["id"], "succeeded", output={})
    DecisionStore(store).add_proposal(lib.rid, first, "abstract", step["id"], 1, "candidate")
    lib.include(second)
    store.conn.execute("UPDATE stage_decisions SET decided_by = 'human' WHERE source_version_id = ?", (second,))
    store.conn.commit()
    aid, _ = answered(lib, first, second)
    sel = method_summary.method_summary(store, lib.rid, aid)["selection"]
    assert sel["abstract_read"] == 1 and sel["person_decisions"] == 1

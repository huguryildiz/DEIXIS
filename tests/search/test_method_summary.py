"""The Method box's data under an `sw` answer: searches, selection, extraction, limits and evidence base.

Records, searches and the answer are SYNTHETIC and written straight into the store; no model or provider is called.
Passing shows which stored row each field reads; it says nothing about whether the answer is good.
"""

from __future__ import annotations


import pytest

from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow import method_summary
from deixis.workflow.store import Store
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


def started(store, lib, run_id, flow=None):
    """The answer's start snapshot as the answer run writes it now: the Method box counts over the rows stored so far."""
    snap = store.step(run_id, "answer_start_snapshot", "code:answer_start_snapshot")
    store.finish_step(snap["id"], "succeeded", output={"method_counts": method_summary.start_counts(store, lib.rid, 1)}
                      | ({"flow": flow} if flow else {}))


def test_counts_come_from_records_not_from_a_plan_or_the_flow_total(store):
    lib = Search(store, "channels")
    first, second = lib.work(), lib.work()
    run = lib.new_run("discovery")
    plan = store.step(run, "fulltext_plan", "code:fulltext_plan")
    store.finish_step(plan["id"], "succeeded", output={"works": [first, second]})  # planned, never attempted
    work = store.step(run, f"fulltext_work:{first}", "code:fulltext_work")
    store.finish_step(work["id"], "succeeded", output={})
    aid, run_id = answered(lib, first, second)
    started(store, lib, run_id, {"works": 500, "five": {"included": 1, "not_met": 0, "waiting_for_pdf": 0, "not_read": 0}})
    sel = method_summary.method_summary(store, lib.rid, aid)["selection"]
    assert sel["works_found"] == 500 and sel["screened"] == 0  # found is the flow total; screened needs a decision row
    assert sel["full_text_attempted"] == 1  # one attempt ran, two were planned


def test_person_decisions_and_model_readings_are_counted(store):
    lib = Search(store, "channels")
    first, second = lib.work(), lib.work()
    step = store.step(lib.run, "abstract:x", "model:abstract")
    store.finish_step(step["id"], "succeeded", output={})
    DecisionStore(store).add_proposal(lib.rid, first, "abstract", step["id"], 1, "candidate")
    lib.include(second)
    store.conn.execute("UPDATE stage_decisions SET decided_by = 'human' WHERE source_version_id = ?", (second,))
    store.conn.commit()
    aid, run_id = answered(lib, first, second)
    started(store, lib, run_id)
    sel = method_summary.method_summary(store, lib.rid, aid)["selection"]
    assert sel["abstract_read"] == 1 and sel["person_decisions"] == 1


def test_a_later_merge_does_not_change_the_counts_an_answer_stored(store):
    lib = Search(store, "channels")
    first, second = lib.work(), lib.work()
    step = store.step(lib.run, "abstract:x", "model:abstract")
    store.finish_step(step["id"], "succeeded", output={})
    for svid in (first, second):
        DecisionStore(store).add_proposal(lib.rid, svid, "abstract", step["id"], 1, "candidate")
    aid, run_id = answered(lib, first, second)
    started(store, lib, run_id)
    before = method_summary.method_summary(store, lib.rid, aid)
    assert before["selection"]["abstract_read"] == 2
    store.conn.execute("UPDATE source_versions SET work_id = (SELECT work_id FROM source_versions WHERE id = ?)"
                       " WHERE id = ?", (first, second))
    store.conn.commit()
    assert method_summary.method_summary(store, lib.rid, aid)["selection"] == before["selection"]

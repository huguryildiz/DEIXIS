"""The research view's counts behind the artifacts rail (UI parity S11): works whose full text was read, the reading
depth an answer was given, and the number of runs.

Records, readings and answers are SYNTHETIC (diffusion channel scheduling), written straight through the store the way
the runs write them, without a model or a request. Passing shows which stored rows each count reads; it says nothing
about whether a reading or an answer is good.
"""

from __future__ import annotations

import pytest

from deixis.storage import db
from deixis.workflow import views
from deixis.workflow.store import Store
from test_queue import Lib


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def view(lib):
    return views.research_view(lib.store, lib.rid)


def read_pass(lib, run, svid, run_no, status="succeeded", head=None):
    """One pass of a full-text reading of `svid` in `run`, with the StepInput the reading run stores."""
    head = head or lib.head(svid)
    step = lib.store.step(run, f"fulltext_adjudication:{head}:{run_no}", "model:fulltext_adjudication")
    sid = db.new_id("sti")
    revision = lib.store.run(run)["scope_revision"]
    lib.store.insert_step_input(step["id"], lib.rid, run, 0,
                                {"step_input_id": sid, "task_type": "fulltext_adjudication", "scope_revision": revision,
                                 "skill_package_hash": "sha256:synthetic", "passages": [],
                                 "adjudication_target": {"source_id": svid, "run": run_no, "runs": 2}}, "b", "d", "m", {})
    lib.store.finish_step(step["id"], status, output={"result": {"parts": []}, "step_input_id": sid},
                          **({"error_code": "model_unavailable"} if status == "failed" else {}))


def test_full_text_read_counts_a_work_once_when_both_passes_stored_a_result_in_one_run_on_one_version(store):
    lib = Lib(store)
    both, split, failed, versions = lib.work(), lib.work(), lib.work(), lib.work()
    preprint = lib.preprint("10.9999/synth.later")
    first, second = lib.new_run("fulltext_adjudication"), lib.new_run("fulltext_adjudication")
    # Read in full in the first run, and again in the second: one work.
    read_pass(lib, first, both, 1)
    read_pass(lib, first, both, 2)
    read_pass(lib, second, both, 1)
    read_pass(lib, second, both, 2)
    # One pass in each run: no run read it twice.
    read_pass(lib, first, split, 1)
    read_pass(lib, second, split, 2)
    # The second pass failed.
    read_pass(lib, first, failed, 1)
    read_pass(lib, first, failed, 2, status="failed")
    # The two passes of one run read two different versions under the same work head.
    read_pass(lib, first, versions, 1)
    read_pass(lib, first, preprint, 2, head=lib.head(versions))
    # More than the ten runs the view lists come later: the reading still counts, and every run is counted.
    for _ in range(11):
        lib.new_run("research_title")
    shown = view(lib)
    assert first not in {run["id"] for run in shown["runs"]}
    assert shown["counts"]["fulltext_read_works"] == 1
    assert shown["run_total"] == store.conn.execute(
        "SELECT COUNT(*) FROM runs WHERE research_id = ?", (lib.rid,)).fetchone()[0] == 14


def test_full_text_read_counts_the_current_question_revision_only(store):
    lib = Lib(store)
    svid = lib.work()
    run = lib.new_run("fulltext_adjudication")
    read_pass(lib, run, svid, 1)
    read_pass(lib, run, svid, 2)
    assert view(lib)["counts"]["fulltext_read_works"] == 1
    lib.revise()
    assert view(lib)["counts"]["fulltext_read_works"] == 0


def test_reading_depth_is_what_the_answer_was_given_and_does_not_move_with_a_later_pdf(store):
    lib = Lib(store)
    pdf, abstract, bare = lib.work(), lib.work(), lib.work()
    lib.text(pdf, ["SYNTHETIC page one on release-time scheduling."])
    lib.store._insert_passage(abstract, None, "abstract", None, None, "synthetic_fixture", None, None,
                              "SYNTHETIC abstract on release-time scheduling.")
    run = lib.new_run("answer")
    step = lib.store.step(run, "answer", "model:answer")
    sid = db.new_id("sti")
    page = next(p for p in lib.store.passages_for(pdf) if p["kind"] == "pdf_page")
    summary = next(p for p in lib.store.passages_for(abstract) if p["kind"] == "abstract")
    sources = [{"source_id": svid, "work_id": lib.work_of(svid)} for svid in (pdf, abstract, bare)]
    passages = [{"passage_id": page["id"], "source_id": pdf, "locator": {"kind": "pdf_page", "physical_page": 1}},
                {"passage_id": summary["id"], "source_id": abstract, "locator": {"kind": "abstract", "physical_page": None}}]
    lib.store.insert_step_input(step["id"], lib.rid, run, 0,
                                {"step_input_id": sid, "task_type": "answer", "scope_revision": 1,
                                 "skill_package_hash": "sha256:synthetic", "sources": sources, "passages": passages},
                                "b", "d", "m", {})
    lib.store.finish_step(step["id"], "succeeded", output={"step_input_id": sid})
    lib.store.save_answer(lib.rid, run, step["id"], sid, 1, "structurally_valid",
                          {"title": "SYNTHETIC", "limitations": [], "unanswered_aspects": []}, {})
    given = view(lib)["answers"][0]["inputs_given"]
    assert given["depth"] == {"pdf": 1, "abstract": 1, "metadata": 1}
    # A PDF that arrives after the answer does not rewrite what the answer was given.
    lib.text(abstract, ["SYNTHETIC page one of the abstract-only work."])
    lib.text(bare, ["SYNTHETIC page one of the bare work."])
    assert view(lib)["answers"][0]["inputs_given"]["depth"] == {"pdf": 1, "abstract": 1, "metadata": 1}


def test_the_latest_answer_run_and_discovery_stay_listed_after_ten_later_runs(store):
    """The transcript draws an answer inside its own run: later full-text reads must not push it out of `runs`."""
    lib = Lib(store)
    discovery = lib.new_run("discovery")
    run = lib.new_run("answer")
    step = lib.store.step(run, "answer", "model:answer")
    lib.store.save_answer(lib.rid, run, step["id"], None, 1, "structurally_valid",
                          {"title": "SYNTHETIC", "limitations": [], "unanswered_aspects": []}, {})
    for _ in range(11):
        lib.new_run("fulltext_adjudication")
    shown = view(lib)
    listed = [r["id"] for r in shown["runs"]]
    assert shown["answers"][0]["run_id"] == run
    assert run in listed and discovery in listed and len(listed) == 12
    assert listed[-2:] == [run, discovery]

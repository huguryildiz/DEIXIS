"""Counts the research page shows (flow boxes, rail counts, run card), each read from stored records.

SYNTHETIC libraries built through the store; no worker, no model. Passing shows the counts follow the stored rows and
the person's decisions; it says nothing about how the page draws them.
"""

from __future__ import annotations

import pytest
import time
from datetime import datetime
from datetime import timedelta

from deixis.storage import db
from deixis.workflow import flow_counts
from deixis.workflow import overrides
from deixis.workflow import probes
from deixis.workflow import queue
from deixis.workflow import views
from deixis.workflow.store import Store
from deixis.workflow.waiting import waiting_count
from test_probes import Probe
from test_probes import answered
from test_queue import BUDGET
from test_queue import Lib
from test_queue import queued


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def context(lib):
    ctx = queue.context(lib.store, lib.rid)
    return ctx, probes.probe_set(ctx)


def flow_of(lib):
    ctx, probe = context(lib)
    return flow_counts.flow_counts(ctx, probe)


def placed(lib):
    ctx, probe = context(lib)
    return flow_counts.work_buckets(ctx, probe)


def code(lib, svid, reason):
    lib.ds.record(lib.rid, svid, reason)
    lib.ds.derive_selection(lib.rid, lib.work_of(svid))
    return svid


def plan(lib, svids):
    """A stored retrieval plan naming these works, as the retrieval run writes it (D99 reads it)."""
    step = lib.store.step(lib.new_run("fulltext_fetch"), "fulltext_plan", "code:fulltext_plan")
    lib.store.finish_step(step["id"], "succeeded", output={"works": list(svids)})


def tick():
    """The clock has millisecond resolution; a list edit in the same millisecond as a decision is `time_unknown`."""
    time.sleep(0.003)


def person(lib, svid, reason, note=None):
    """A person's answer written through D96's own answer body, whatever the version's current decision is."""
    ctx = queue.context(lib.store, lib.rid)
    head = lib.head(svid)
    with db.transaction(lib.store.conn):
        written = queue._write_answer(ctx, svid, {"current": lib.ds.current(lib.rid, svid, "fulltext"), "head": head},
                                      reason, note)
        lib.ds.derive_selection(lib.rid, lib.work_of(svid))
    return written


@pytest.mark.parametrize("field", ["channels"])
def test_every_bucket_holds_a_work_and_the_buckets_sum_to_the_works(store, field):
    lib = Probe(store, field)
    work = lib.work_of
    expected = {
        "confirmed": work(answered(lib, "include")),
        "person_not_met": work(answered(lib, "criterion_not_met")),
        "person_unsure": work(answered(lib, "not_sure")),
        "queued": work(queued(lib)),
        "included": work(code(lib, lib.work(), "all_parts_verified")),
        "not_met": work(code(lib, lib.work(), "criterion_absent")),
        "not_read_yet": work(code(lib, lib.work(), "not_read_yet")),
        "candidate_not_fetched": work(code(lib, lib.work(), "runs_agree_candidate")),
        "abstract_open": work(code(lib, lib.work(), "no_abstract")),
        "abstract_not_read": work(code(lib, lib.work(), "abstract_not_read")),
        "survey": work(code(lib, lib.work(), "survey_title_word")),
        "out_of_scope_model": work(code(lib, lib.work(), "runs_agree_out_of_scope")),
        "out_of_scope_code": work(code(lib, lib.work(), "both_blocks_missing")),
        "not_screened": work(lib.work()),
    }
    excluded = lib.work()
    lib.list_edit(excluded, "excluded")
    expected["person_excluded"] = work(excluded)
    waiting = code(lib, lib.work(), "no_fulltext")
    expected["waiting_for_pdf"] = work(waiting)
    # A person's include whose selection they later set back to pending from the list: no probe, and not the
    # machine's include either. It is `other`, listed with its code.
    pending = answered(lib, "include")
    lib.list_edit(pending, "pending")
    expected["other"] = work(pending)
    plan(lib, [lib.head(waiting)])

    found = placed(lib)
    assert {bucket: [w for w, (b, _) in found.items() if b == bucket] for bucket in expected} == {
        bucket: [w] for bucket, w in expected.items()}
    flow = flow_of(lib)
    assert set(flow["buckets"]) == set(flow_counts.BUCKETS)
    assert sum(flow["buckets"].values()) == flow["works"] == len(store.work_heads(lib.rid))
    assert flow["buckets"]["look_again"] == 0
    assert flow["other_reasons"] == {"human_include": 1}
    # D101's columns, D96's queue and D99's waiting list, read from the same context, say the same.
    ctx, probe = context(lib)
    assert flow["buckets"]["included"] == len(probe["included"])
    assert flow["buckets"]["confirmed"] == len(probe["verified"])
    counted = queue.queue_counts(store, lib.rid, ctx)
    assert flow["buckets"]["queued"] == counted["queue"] and flow["buckets"]["look_again"] == counted["look_again"]
    assert flow["buckets"]["waiting_for_pdf"] == waiting_count(store, lib.rid) == 1
    # The five of SW11.12; an unread abstract is never added to a negative.
    assert flow["five"] == {"included": 2, "included_by_agreement": 1, "confirmed": 1, "not_met": 2,
                            "waiting_for_pdf": 1, "queued": 1, "not_read": 2, "not_read_in_reading": 1,
                            "not_read_not_tried": 1}
    assert flow["queue_by_reason"] == {"part_without_evidence": 1}


def test_the_research_view_reads_the_flow_boxes_and_overrides_from_one_snapshot_and_writes_nothing(store):
    lib = Probe(store)
    answered(lib, "include")
    code(lib, lib.work(), "all_parts_verified")
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]

    def rows():
        return {table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    before, changes = rows(), store.conn.total_changes
    counts = views.research_view(store, lib.rid)["counts"]
    assert rows() == before and store.conn.total_changes == changes
    assert counts["flow"]["five"]["included"] == 2 and counts["flow_boxes"]["boxes"]
    assert counts["overrides"]["decisions"] == 1


def classes(lib):
    ctx, probe = context(lib)
    return overrides.classify(ctx, probe)


def test_a_list_include_of_a_work_code_left_out_at_the_abstract_stage_overrules_code(store):
    lib = Probe(store, "irrigation")
    svid = code(lib, lib.work(), "both_blocks_missing")
    tick()
    lib.list_edit(svid, "included")
    entry = classes(lib)[lib.work_of(svid)]
    assert (entry["path"], entry["class"], entry["direction"]) == ("list", "overruled", "excluded -> included")
    assert (entry["machine"]["decided_by"], entry["machine"]["stage"]) == ("code", "abstract")
    ctx, probe = context(lib)
    shown = overrides.overrides_view(ctx, probe)
    assert shown["changed_by"] == {"code": 1, "model_agreement": 0}
    assert shown["overruled"] == [{"path": "list", "decided_by": "code", "stage": "abstract",
                                   "direction": "excluded -> included", "count": 1}]


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


FAST = BUDGET | {"fast_path": {"policy": "fast_path_v1", "policy_hash": "sha256:synthetic", "mode": "standard",
                               "enforced_stages": ["read"], "N": 8, "K": 3},
                 "inspection": {"fetch_limit": 3, "read_limit": 3}}


def run_of(view, run_id):
    return next(run for run in view["runs"] if run["id"] == run_id)


def stamp():
    """Now, one tick after everything written so far (the store's clock has millisecond resolution)."""
    time.sleep(0.003)
    return db.now()


def shift(when, minutes):
    return (datetime.fromisoformat(when) + timedelta(minutes=minutes)).isoformat(timespec="milliseconds")


def step(store, run, key, kind, status="succeeded", output=None, error_code=None, error=None, at=None):
    row = store.step(run, key, kind)
    store.start_step(row["id"])
    store.finish_step(row["id"], status, output=output, error_code=error_code, error=error, finished_at=at)
    return row["id"]


def candidate(lib):
    svid = lib.work()
    lib.ds.record(lib.rid, svid, "runs_agree_candidate")
    lib.ds.derive_selection(lib.rid, lib.work_of(svid))
    return svid


def fast_run(store, lib):
    run = store.create_run(lib.rid, "discovery", FAST, None)["id"]
    store.update_run(run, status="completed")
    return run


def item(lib, svid, cutoff=None, stage="abstract", code="runs_agree_candidate"):
    """One window work of the read closure, as `small_batch.work_state` froze it at the close."""
    return {"work_id": lib.work_of(svid), "head": svid, "stage": stage, "reason_code": code, "cutoff": cutoff}


def close(store, run, items, selected, cut, k_selected=3, **extra):
    step(store, run, "small_batch:v1:synthetic:fast:close", "code:small_batch_close",
         output={"items": items, "N": 8, "K": 3, "k_selected": k_selected, "selected_work_ids": selected,
                 "read_cutoff_at": cut, **extra})


def fetch_failed(store, run, svid, status, at, final_url=None):
    step(store, run, f"fetch:{svid}", "fetch_pdf", status="failed", error_code="fetch_http_error",
         error={"http_status": status, "error": "SYNTHETIC refused", "url": "https://example.org/x.pdf",
                **({"final_url": final_url} if final_url else {})}, at=at)


def test_fulltext_gaps_give_each_unread_passed_work_the_reason_its_records_state(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    (read, no_pdf, refused, deferred, unproven, failed_read, late, early, not_selected, unconfirmed,
     unrecorded, beyond) = (candidate(lib) for _ in range(12))
    work = lib.work_of
    cut = stamp()
    BEFORE, AFTER = shift(cut, -30), shift(cut, 30)
    for run_no in (1, 2):
        step(store, fast, f"fulltext_adjudication:{read}:{run_no}", "model:fulltext_adjudication")
    # A work read twice whatever it was decided: in `read_any`, not in `passed`.
    stray = lib.work()
    for run_no in (1, 2):
        step(store, fast, f"fulltext_adjudication:{stray}:{run_no}", "model:fulltext_adjudication")
    step(store, fast, f"fulltext_adjudication:{failed_read}:1", "model:fulltext_adjudication")
    step(store, fast, f"fulltext_adjudication:{failed_read}:2", "model:fulltext_adjudication", status="failed",
         error_code="invalid_model_output")
    for svid in (no_pdf, refused):
        step(store, fast, f"fulltext_work:{work(svid)}", "code:fulltext_work", output={"code": "no_fulltext"}, at=BEFORE)
    fetch_failed(store, fast, refused, 403, BEFORE)
    step(store, fast, f"fulltext_work:{work(deferred)}", "code:fulltext_work", status="failed",
         error_code="quota_deferred", output={"code": None, "quota_deferred": 1}, at=BEFORE)
    # A failure with no stored fetch attempt behind it proves nothing about a download.
    step(store, fast, f"fulltext_work:{work(unproven)}", "code:fulltext_work", status="failed",
         error_code="fulltext_work_failed", error={"error": "no head"}, at=BEFORE)
    # Competing records: the cutoff came first for `late` (its fetch failed only afterwards), the failure came first
    # for `early` although its item says the same thing.
    for svid, at in ((late, AFTER), (early, BEFORE)):
        step(store, fast, f"fulltext_work:{work(svid)}", "code:fulltext_work", status="failed",
             error_code="fetch_not_settled", at=at)
        fetch_failed(store, fast, svid, 503, at)
    # The work the snapshot names outside the read window, and one this run's own step decided past the abstract
    # stage that no window or snapshot names: the second is unknown, absence being no proof.
    step(store, fast, "fast_path:v1:cutoff", "code:fast_path_cutoff", output={"items": [
        {"work_id": work(beyond), "head": beyond, "abstract_decision_id": "dec_synthetic",
         "base_reason": "outside_read_window", "reason": "outside_read_window"}]})
    abstract_step = step(store, fast, "small_batch:v1:synthetic:fast:abstract_screening:0:2", "model:abstract_screening")
    lib.ds.record(lib.rid, unrecorded, "runs_agree_out_of_scope")
    lib.ds.record(lib.rid, unrecorded, "runs_agree_candidate", step_id=abstract_step)
    after = {"fulltext_after_cutoff": "in_flight"}
    close(store, fast, [item(lib, read, stage="fulltext", code="all_parts_verified"), item(lib, no_pdf),
                        item(lib, refused), item(lib, deferred), item(lib, unproven), item(lib, failed_read),
                        item(lib, late, after), item(lib, early, after), item(lib, not_selected),
                        item(lib, unconfirmed)],
          [work(read), work(failed_read), work(unproven)], cut, identity_unconfirmed=[work(unconfirmed)])

    gaps = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert (gaps["passed"], gaps["read"], gaps["read_any"], gaps["not_read"]) == (12, 1, 2, 11)
    reasons = {row["work_id"]: (row["reason"], row["http_status"]) for row in gaps["rows"]}
    assert reasons == {
        work(no_pdf): ("no_open_pdf", None), work(refused): ("fetch_failed", 403),
        work(deferred): ("deferred", None), work(unproven): ("unknown", None),
        work(failed_read): ("reading_failed", None), work(late): ("not_reached_before_cutoff", None),
        work(early): ("fetch_failed", 503), work(not_selected): ("outside_read_limit", None),
        work(unconfirmed): ("identity_unconfirmed", None), work(unrecorded): ("unknown", None),
        work(beyond): ("outside_read_limit", None)}
    assert gaps["reasons"] == {"no_open_pdf": 1, "fetch_failed": 2, "deferred": 1, "outside_read_limit": 2,
                               "not_reached_before_cutoff": 1, "reading_failed": 1, "identity_unconfirmed": 1,
                               "unknown": 2}
    assert sum(gaps["reasons"].values()) == gaps["not_read"] == len(gaps["rows"])



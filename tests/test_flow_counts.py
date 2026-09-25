"""The flow buckets, the PRISMA 2020-style boxes and the override count of an `sw` research (slice 20, decisions 1, 2, 4).

Records, criteria and decisions are SYNTHETIC and from two fields (diffusion channel scheduling, greenhouse irrigation),
written straight through the store the way the runs and the queue write them, without a model or a request. Passing
shows where each work is counted and what a person's decision is compared with; it says nothing about whether code or
the model decides well, and no count here is a rate.
"""

from __future__ import annotations

import time

import pytest

from deixis.storage import db
from deixis.workflow import flow_counts, overrides, probes, queue, views
from deixis.workflow.store import COPIED_SELECTION_REASON, Store
from deixis.workflow.waiting import waiting_count
from test_probes import Probe, answered
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


# ---- decision 1: every work in one bucket ------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["channels", "irrigation"])
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


def test_a_pdf_wrong_answer_waits_for_a_pdf_and_is_counted_by_d99_too(store):
    lib = Probe(store, "irrigation")
    svid = answered(lib, "pdf_wrong")
    plan(lib, [lib.head(svid)])
    assert placed(lib)[lib.work_of(svid)] == ("waiting_for_pdf", "human_pdf_wrong")
    assert flow_of(lib)["buckets"]["waiting_for_pdf"] == waiting_count(store, lib.rid) == 1


@pytest.mark.parametrize("reason", ["no_fulltext", "human_pdf_wrong"])
def test_text_on_another_version_takes_the_work_off_d99s_list_and_out_of_the_waiting_bucket(store, reason):
    # One rule for both counts (`fulltext.waits_for_pdf`): while no version has text the work waits in both; once the
    # preprint of the same work has PDF text it leaves D99's list and the flow calls it "text in hand, not read yet".
    lib = Probe(store)
    published = lib.published("10.9999/synth.alt")
    preprint = lib.preprint("10.9999/synth.alt")
    assert lib.work_of(preprint) == lib.work_of(published)
    if reason == "human_pdf_wrong":
        lib.text(published, ["SYNTHETIC a scanned file of another paper."])
        code(lib, published, "no_fulltext")
        person(lib, published, "human_pdf_wrong")
    else:
        code(lib, published, "no_fulltext")
    plan(lib, [lib.head(published)])
    assert flow_of(lib)["buckets"]["waiting_for_pdf"] == waiting_count(store, lib.rid) == 1
    lib.text(preprint, ["SYNTHETIC preprint page on release scheduling."])
    flow = flow_of(lib)
    assert flow["buckets"]["waiting_for_pdf"] == waiting_count(store, lib.rid) == 0
    assert placed(lib)[lib.work_of(published)] == ("not_read_yet", reason)
    assert flow["five"]["waiting_for_pdf"] == 0


def test_a_stale_person_include_still_included_is_counted_as_read_by_the_answer(store):
    lib = Probe(store)
    included = answered(lib, "include")
    not_sure = answered(lib, "not_sure")
    lib.revise()
    flow = flow_of(lib)
    assert placed(lib)[lib.work_of(included)][0] == "look_again"
    assert placed(lib)[lib.work_of(not_sure)][0] == "look_again"
    assert flow["buckets"]["look_again"] == 2 == queue.queue_counts(store, lib.rid)["look_again"]
    assert flow["look_again_in_answer"] == 1  # the one whose selection is still included
    # Once the person sets it again under the new revision, it is theirs again, not a stale decision.
    lib.list_edit(included, "included")
    assert flow_of(lib)["look_again_in_answer"] == 0


def test_a_legacy_research_has_no_flow_no_boxes_and_no_override_count(store):
    lib = Probe(store, workflow="legacy")
    lib.work()
    counts = views.research_view(store, lib.rid)["counts"]
    assert counts["flow"] is None and counts["flow_boxes"] is None and counts["overrides"] is None


# ---- decision 2: the boxes ---------------------------------------------------------------------------------------


def boxes_of(lib):
    ctx, probe = context(lib)
    boxes = flow_counts.flow_boxes(ctx, flow_counts.flow_counts(ctx, probe))
    return boxes, {box["key"]: box["count"] for box in boxes["boxes"]}


def test_the_boxes_count_the_revision_and_every_box_is_marked_incomplete(store):
    lib = Probe(store)
    lib.keyed("search:0", lib.records(3))
    (chained,) = lib.keyed("chain:backward:0", lib.records(1), query="chain:backward:W1")
    svid = queued(lib)
    code(lib, lib.work(), "runs_agree_out_of_scope")
    plan(lib, [lib.head(svid)])
    boxes, by_key = boxes_of(lib)
    assert boxes["flow_status"] == "incomplete_no_human_screening"
    assert all(box["flow_status"] == "incomplete_no_human_screening" for box in boxes["boxes"])
    assert by_key["rows_returned"] == 5 and by_key["chain_rows_returned"] == 1  # 3 + two single works, apart
    assert by_key["works_found_by_search"] == by_key["works"] == 6
    assert by_key["fulltext_sought"] == 1 and by_key["fulltext_read"] == 1 and by_key["queued"] == 1
    assert by_key["out_of_scope_model"] == 1


def test_a_revision_searched_before_the_hit_rows_says_its_found_works_were_not_counted(store):
    lib = Probe(store, "irrigation")
    lib.keyed("search:0", lib.records(2))
    store.conn.execute("DELETE FROM candidate_hits WHERE research_id = ?", (lib.rid,))
    _, by_key = boxes_of(lib)
    assert by_key["works_found_by_search"] is None and by_key["works"] == 2


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


# ---- decision 4: the override count ------------------------------------------------------------------------------


def classes(lib):
    ctx, probe = context(lib)
    return overrides.classify(ctx, probe)


def test_a_queue_include_of_a_row_the_runs_left_open_settles_it_and_overrules_nothing(store):
    lib = Probe(store)
    svid = answered(lib, "include")
    entry = classes(lib)[lib.work_of(svid)]
    assert (entry["path"], entry["class"]) == ("queue", "settled_open")
    ctx, probe = context(lib)
    shown = overrides.overrides_view(ctx, probe)
    assert shown["decisions"] == 1 and shown["changed"] == 0 and shown["classes"]["settled_open"] == 1


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


def test_a_list_include_of_a_work_two_runs_included_agrees(store):
    lib = Probe(store)
    svid = code(lib, lib.work(), "all_parts_verified")
    tick()
    lib.list_edit(svid, "included")
    assert classes(lib)[lib.work_of(svid)]["class"] == "agreed"


def test_a_person_who_changed_their_answer_is_compared_with_the_machine_view_before_their_first(store):
    lib = Probe(store, "irrigation")
    svid = code(lib, lib.work(), "criterion_absent")
    person(lib, svid, "human_include")
    person(lib, svid, "human_criterion_not_met")
    # Before the second answer the version's last row was the person's own include; before the first it was the
    # runs' criterion_absent, which the person's final `excluded` agrees with.
    entry = classes(lib)[lib.work_of(svid)]
    assert (entry["path"], entry["class"]) == ("queue", "agreed")
    assert entry["machine"]["reason_code"] == "criterion_absent"


def test_a_machine_row_of_the_same_millisecond_written_after_the_persons_row_is_not_in_the_view(store):
    lib = Probe(store)
    published, preprint = lib.published("10.9999/synth.ms"), lib.preprint("10.9999/synth.ms")
    code(lib, published, "criterion_absent")
    decision = person(lib, published, "human_include")
    later = lib.ds.record(lib.rid, preprint, "all_parts_verified")
    store.conn.execute("UPDATE stage_decisions SET created_at = ? WHERE id = ?", (decision["created_at"], later["id"]))
    # Were the later row in the view, the two versions' fresh opposite decisions would leave the work open.
    entry = classes(lib)[lib.work_of(published)]
    assert (entry["class"], entry["direction"]) == ("overruled", "excluded -> included")


def test_a_list_edit_is_compared_with_the_view_at_its_own_time_and_a_tie_is_time_unknown(store):
    lib = Probe(store, "irrigation")
    published, preprint = lib.published("10.9999/synth.list"), lib.preprint("10.9999/synth.list")
    lib.list_edit(published, "included")
    tick()
    code(lib, preprint, "criterion_absent")  # a later reading of another version
    entry = classes(lib)[lib.work_of(published)]
    assert (entry["path"], entry["class"]) == ("list", "settled_open")
    edited = store.conn.execute("SELECT MAX(created_at) FROM selection_history WHERE research_id = ? AND origin = 'user'",
                                (lib.rid,)).fetchone()[0]
    store.conn.execute("UPDATE stage_decisions SET created_at = ? WHERE research_id = ? AND source_version_id = ?",
                       (edited, lib.rid, preprint))
    assert classes(lib)[lib.work_of(published)]["class"] == "time_unknown"


def test_a_list_edit_is_timed_by_the_row_that_set_the_heads_selection_not_a_later_edit_of_another_version(store):
    # Two separate list edits on two versions of one work: the head's include is the person's decision and its moment
    # is the head's own edit; a later edit of the preprint, after the preprint's reading, does not move that moment.
    lib = Probe(store, "irrigation")
    published, preprint = lib.published("10.9999/synth.two"), lib.preprint("10.9999/synth.two")
    assert lib.head(preprint) == published
    code(lib, published, "both_blocks_missing")
    tick()
    lib.list_edit(published, "included")
    tick()
    lib.include(preprint)  # a later reading of the preprint: two agreeing runs include it
    tick()
    lib.list_edit(preprint, "excluded")
    entry = classes(lib)[lib.work_of(published)]
    assert (entry["path"], entry["class"], entry["direction"]) == ("list", "overruled", "excluded -> included")
    assert (entry["machine"]["decided_by"], entry["machine"]["stage"]) == ("code", "abstract")


def test_a_selection_a_new_head_copied_is_timed_by_the_edit_it_was_copied_from(store):
    # The person includes the preprint while it heads the work; the published version found later becomes the head and
    # copies that selection. The moment is the preprint's edit, before the reading that came between the two.
    lib = Probe(store)
    preprint = lib.preprint("10.9999/synth.copy")
    code(lib, preprint, "both_blocks_missing")
    tick()
    lib.list_edit(preprint, "included")
    tick()
    lib.include(preprint)
    tick()
    published = lib.published("10.9999/synth.copy")
    assert lib.head(preprint) == published
    reasons = [row[0] for row in store.conn.execute(
        "SELECT reason FROM selection_history WHERE research_id = ? AND source_version_id = ? ORDER BY id",
        (lib.rid, published))]
    assert reasons[-1] == COPIED_SELECTION_REASON
    entry = classes(lib)[lib.work_of(published)]
    assert (entry["path"], entry["class"], entry["direction"]) == ("list", "overruled", "excluded -> included")
    assert entry["machine"]["decided_by"] == "code"


def test_a_machine_decision_under_an_earlier_criterion_is_judged_stale_at_the_moment_of_the_edit(store):
    lib = Probe(store)
    svid = code(lib, lib.work(), "runs_agree_candidate")
    code(lib, svid, "criterion_absent")
    lib.revise()
    tick()
    lib.list_edit(svid, "included")
    # Under the key of the edit's moment the criterion_absent row is stale, so the abstract candidate speaks: open.
    entry = classes(lib)[lib.work_of(svid)]
    assert (entry["class"], entry["machine"]["reason_code"]) == ("settled_open", "runs_agree_candidate")


def test_two_versions_at_opposite_fresh_decisions_are_open_to_the_person(store):
    lib = Probe(store, "irrigation")
    published, preprint = lib.published("10.9999/synth.two"), lib.preprint("10.9999/synth.two")
    lib.ds.record(lib.rid, published, "all_parts_verified")
    lib.ds.record(lib.rid, preprint, "criterion_absent")
    tick()
    lib.list_edit(lib.head(published), "included")
    entry = classes(lib)[lib.work_of(published)]
    assert (entry["class"], entry["machine"]["reason_code"]) == ("settled_open", "versions_disagree")


def test_not_sure_pdf_wrong_and_look_again_are_counted_apart_and_no_decision_says_nothing(store):
    lib = Probe(store)
    ctx, probe = context(lib)
    assert overrides.overrides_view(ctx, probe)["decisions"] == 0
    answered(lib, "not_sure")
    answered(lib, "pdf_wrong")
    stale = answered(lib, "include")
    lib.revise()
    ctx, probe = context(lib)
    shown = overrides.overrides_view(ctx, probe)
    assert shown["decisions"] == 0 and shown["classes"] == {name: 0 for name in overrides.CLASSES}
    assert lib.work_of(stale) in probe["look_again"]
    # The two other answers of the first revision are stale too: the queue asks all three again, none is "not sure".
    assert shown["apart"] == {"not_sure": 0, "pdf_wrong": 0, "look_again": 3}


def test_not_sure_and_pdf_wrong_of_this_revision_are_counted_apart(store):
    lib = Probe(store, "irrigation")
    answered(lib, "not_sure")
    answered(lib, "pdf_wrong")
    ctx, probe = context(lib)
    shown = overrides.overrides_view(ctx, probe)
    assert shown["decisions"] == 0 and shown["apart"] == {"not_sure": 1, "pdf_wrong": 1, "look_again": 0}

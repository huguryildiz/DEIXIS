"""The research view's per-run readings: the two abstract passes, why a passed work went unread, and a quote's match.

Records, labels and steps are SYNTHETIC (diffusion channel scheduling), written straight through the store the way the
runs write them, with no model and no request. Passing shows each field is read from the stored rows and that a work no
record explains is `unknown`; it says nothing about whether the passes or the reading were right.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from deixis.storage import db
from deixis.workflow import fast_read, run_card, views
from deixis.workflow.store import Store
from test_queue import BUDGET, Lib

FAST = BUDGET | {"fast_path": {"policy": "fast_path_v1", "policy_hash": "sha256:synthetic", "mode": "standard",
                               "enforced_stages": ["read"], "N": 8, "K": 3},
                 "inspection": {"fetch_limit": 3, "read_limit": 3}}


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


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


def fetch_failed(store, run, svid, status, at):
    step(store, run, f"fetch:{svid}", "fetch_pdf", status="failed", error_code="fetch_http_error",
         error={"http_status": status, "error": "SYNTHETIC refused", "url": "https://example.org/x.pdf"}, at=at)


def test_screening_passes_count_each_pair_and_list_the_works_that_did_not_agree(store):
    lib = Lib(store)
    agreed, split, missing, open_ = lib.work(), lib.work(), lib.work(), lib.work()
    first = store.step(lib.run, "abstract_screening:0:1", "model:abstract_screening")["id"]
    second = store.step(lib.run, "abstract_screening:0:2", "model:abstract_screening")["id"]
    for svid, labels in ((agreed, ("candidate", "candidate")), (split, ("candidate", "out_of_scope")),
                         (missing, ("candidate", None)), (open_, ("unresolved", "unresolved"))):
        for run_no, (label, step_id) in enumerate(zip(labels, (first, second)), start=1):
            if label is not None:
                lib.ds.add_proposal(lib.rid, svid, "abstract", step_id, run_no, label, quote="SYNTHETIC quote")
    for svid, code in ((agreed, "runs_agree_candidate"), (split, "runs_disagree_kept_as_candidate"),
                       (missing, "abstract_not_proposed"), (open_, "runs_agree_unresolved")):
        lib.ds.record(lib.rid, svid, code, step_id=second)
    # A proposal from another run's step is not this run's pass.
    other = store.step(lib.new_run("discovery"), "abstract_screening:0:1", "model:abstract_screening")["id"]
    lib.ds.add_proposal(lib.rid, lib.work(), "abstract", other, 1, "candidate", quote="SYNTHETIC quote")

    passes = run_of(views.research_view(store, lib.rid), lib.run)["screening_passes"]
    assert {key: passes[key] for key in ("read", "agreed", "disagreed", "unresolved")} == {
        "read": 4, "agreed": 1, "disagreed": 1, "unresolved": 2}
    assert passes["run_read"] == passes["read"]
    by_work = {row["work_id"]: row for row in passes["rows"]}
    assert set(by_work) == {lib.work_of(split), lib.work_of(missing), lib.work_of(open_)}
    assert by_work[lib.work_of(split)] == {
        "source_version_id": split, "work_id": lib.work_of(split), "title": store.source(split)["title"],
        "first": "candidate",
        "second": "out_of_scope", "final": "candidate", "reason_code": "runs_disagree_kept_as_candidate"}
    # A missing second pass stays null; the decision the pair wrote is shown as stored.
    assert (by_work[lib.work_of(missing)]["first"], by_work[lib.work_of(missing)]["second"]) == ("candidate", None)
    assert (by_work[lib.work_of(missing)]["final"], by_work[lib.work_of(missing)]["reason_code"]) == (
        "unresolved", "abstract_not_proposed")
    titles = [row["title"] for row in passes["rows"]]
    assert titles == sorted(titles)
    # A later decision on a version this run read does not change what the run left.
    stamp()
    lib.ds.record(lib.rid, split, "runs_agree_out_of_scope")
    assert run_of(views.research_view(store, lib.rid), lib.run)["screening_passes"] == passes


def test_screening_pairs_the_two_passes_on_one_version_only(store):
    lib = Lib(store)
    preprint = lib.preprint("10.9999/synth.two")
    published = lib.published("10.9999/synth.two")
    assert lib.work_of(preprint) == lib.work_of(published)
    first = store.step(lib.run, "abstract_screening:0:1", "model:abstract_screening")["id"]
    second = store.step(lib.run, "abstract_screening:0:2", "model:abstract_screening")["id"]
    lib.ds.add_proposal(lib.rid, preprint, "abstract", first, 1, "candidate", quote="SYNTHETIC quote")
    lib.ds.add_proposal(lib.rid, published, "abstract", second, 2, "out_of_scope", quote="SYNTHETIC quote")
    passes = run_of(views.research_view(store, lib.rid), lib.run)["screening_passes"]
    # Two readings, each missing a pass: not one work whose passes disagreed.
    assert {key: passes[key] for key in ("read", "agreed", "disagreed", "unresolved")} == {
        "read": 2, "agreed": 0, "disagreed": 0, "unresolved": 2}
    assert {(row["source_version_id"], row["first"], row["second"]) for row in passes["rows"]} == {
        (preprint, "candidate", None), (published, None, "out_of_scope")}


def test_screening_passes_and_fulltext_gaps_are_null_where_they_do_not_apply(store):
    lib = Lib(store)
    answer = lib.new_run("answer")
    view = views.research_view(store, lib.rid)
    assert run_of(view, answer)["screening_passes"] is None and run_of(view, answer)["fulltext_gaps"] is None
    # A discovery run without the fast path's read stage has passes but no gaps.
    assert run_of(view, lib.run)["screening_passes"] == {"read": 0, "run_read": 0, "agreed": 0, "disagreed": 0, "unresolved": 0,
                                                         "rows": []}
    assert run_of(view, lib.run)["fulltext_gaps"] is None


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


def test_later_records_do_not_change_an_earlier_runs_gaps(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    kept, dropped = candidate(lib), candidate(lib)
    cut = stamp()
    close(store, fast, [item(lib, kept), item(lib, dropped)], [], cut, k_selected=0)
    before = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert before["passed"] == 2 and {row["reason"] for row in before["rows"]} == {"unknown"}
    assert {row["source_version_id"] for row in before["rows"]} == {kept, dropped}
    # After the run completed: a new work passes, a passed work is set out of scope, a later run fails a fetch, and
    # a published version that heads `kept`'s work today is found.
    stamp()
    candidate(lib)
    lib.ds.record(lib.rid, dropped, "runs_agree_out_of_scope")
    fetch_failed(store, lib.new_run("fulltext_fetch"), kept, 404, shift(cut, 30))
    assert lib.head(kept) == kept
    lib.ds.record(lib.rid, kept, "runs_agree_candidate")
    after = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert after == before


def test_a_later_head_version_does_not_rename_an_earlier_gap_row(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    preprint = lib.preprint("10.9999/synth.late")
    lib.ds.record(lib.rid, preprint, "runs_agree_candidate")
    cut = stamp()
    close(store, fast, [item(lib, preprint)], [], cut, k_selected=0)
    before = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]["rows"]
    published = lib.published("10.9999/synth.late")
    assert lib.head(preprint) == published != preprint
    after = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]["rows"]
    assert after == before and [row["source_version_id"] for row in after] == [preprint]
    assert after[0]["title"] == store.source(preprint)["title"]


def test_a_retrieval_settled_after_the_cutoff_does_not_rename_an_earlier_gap_row(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    preprint = lib.preprint("10.9999/synth.bg")
    lib.ds.record(lib.rid, preprint, "runs_agree_candidate")
    cut = stamp()
    work = lib.work_of(preprint)
    close(store, fast, [item(lib, preprint, {"fulltext_after_cutoff": "not_started"})], [], cut, k_selected=0)
    before = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]["rows"]
    # The background fetch settles after the cutoff on the publisher version.
    published = lib.published("10.9999/synth.bg")
    step(store, fast, f"fulltext_work:{work}", "code:fulltext_work", at=shift(cut, 30),
         output={"code": "not_read_yet", "head": published, "read_version": published})
    after = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]["rows"]
    assert after == before and [(row["source_version_id"], row["reason"]) for row in after] == [
        (preprint, "not_reached_before_cutoff")]


def test_a_failed_reading_names_the_version_its_plan_read_not_its_head(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    preprint = lib.preprint("10.9999/synth.read")
    published = lib.published("10.9999/synth.read")
    lib.ds.record(lib.rid, published, "runs_agree_candidate")
    work = lib.work_of(published)
    # The retrieval names the publisher version; the plan froze the preprint's text under the publisher head, and the
    # plan's version is the one read.
    step(store, fast, f"fulltext_work:{work}", "code:fulltext_work", output={"head": published, "read_version": published})
    step(store, fast, f"small_batch:v1:synthetic:fast:read:{work}:adjudication_plan", "code:adjudication_plan",
         output={"works": [{"head": published, "read_version": preprint}]})
    step(store, fast, f"fulltext_adjudication:{published}:1", "model:fulltext_adjudication")
    step(store, fast, f"fulltext_adjudication:{published}:2", "model:fulltext_adjudication", status="failed",
         error_code="invalid_model_output")
    cut = stamp()
    close(store, fast, [item(lib, published)], [work], cut, k_selected=1)
    (row,) = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]["rows"]
    assert (row["source_version_id"], row["title"], row["reason"]) == (
        preprint, store.source(preprint)["title"], "reading_failed")


def test_reaching_the_full_text_without_a_candidate_decision_is_no_abstract_pass(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    missing, unresolved, passed = lib.work(), lib.work(), candidate(lib)
    lib.ds.record(lib.rid, missing, "abstract_not_found")
    lib.ds.record(lib.rid, unresolved, "runs_agree_unresolved")
    for svid in (missing, unresolved, passed):
        step(store, fast, f"fulltext_work:{lib.work_of(svid)}", "code:fulltext_work", output={"code": "no_fulltext"})
    cut = stamp()
    close(store, fast, [item(lib, svid, stage="fulltext", code="no_fulltext") for svid in (missing, unresolved, passed)],
          [], cut, k_selected=0)
    gaps = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert gaps["passed"] == 1 and [row["work_id"] for row in gaps["rows"]] == [lib.work_of(passed)]


def test_first_passes_on_two_versions_are_no_reading(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    preprint = lib.preprint("10.9999/synth.pair")
    published = lib.published("10.9999/synth.pair")
    assert lib.work_of(preprint) == lib.work_of(published)
    lib.ds.record(lib.rid, published, "runs_agree_candidate")
    for svid in (preprint, published):
        step(store, fast, f"fulltext_adjudication:{svid}:1", "model:fulltext_adjudication")
    cut = stamp()
    close(store, fast, [item(lib, published)], [], cut, k_selected=0)
    gaps = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert (gaps["read_any"], gaps["read"], gaps["not_read"]) == (0, 0, 1)
    # A completed pair on one version is a reading.
    step(store, fast, f"fulltext_adjudication:{published}:2", "model:fulltext_adjudication")
    gaps = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert (gaps["read_any"], gaps["read"], gaps["not_read"]) == (1, 1, 0)


def test_without_a_closure_a_work_with_no_record_is_unknown_not_outside_the_limit(store):
    lib = Lib(store)
    fast = fast_run(store, lib)
    svid = lib.work()
    decided = step(store, fast, "small_batch:v1:synthetic:fast:abstract_screening:0:2", "model:abstract_screening")
    lib.ds.record(lib.rid, svid, "runs_agree_candidate", step_id=decided)
    # A work that passed by another run's records is not this run's to explain.
    stamp()
    candidate(lib)
    gaps = run_of(views.research_view(store, lib.rid), fast)["fulltext_gaps"]
    assert [(row["work_id"], row["reason"]) for row in gaps["rows"]] == [(lib.work_of(svid), "unknown")]


def card_queries(store, unread):
    """The statements the two run cards issue for one fast run with `unread` passed works none of which was read."""
    lib = Lib(store)
    fast = fast_run(store, lib)
    svids = [candidate(lib) for _ in range(unread)]
    cut = stamp()
    BEFORE = shift(cut, -30)
    for svid in svids:
        step(store, fast, f"fulltext_work:{lib.work_of(svid)}", "code:fulltext_work", output={"code": "no_fulltext"},
             at=BEFORE)
        fetch_failed(store, fast, svid, 403, BEFORE)
    close(store, fast, [item(lib, svid) for svid in svids], [], cut)
    run = store.run(fast)
    run["steps"] = store.run_steps(fast)
    read_view = fast_read.view(store, run)
    statements = []
    store.conn.set_trace_callback(statements.append)
    try:
        facts = run_card.Facts(store, lib.rid)
        passes = run_card.screening_passes(store, run, facts)
        gaps = run_card.fulltext_gaps(store, run, facts, read_view)
    finally:
        store.conn.set_trace_callback(None)
    assert passes["read"] == 0 and gaps["reasons"]["fetch_failed"] == unread
    return [s for s in statements if not s.startswith(("BEGIN", "COMMIT", "SAVEPOINT", "RELEASE"))]


def test_run_card_queries_do_not_grow_with_the_unread_works(store):
    # The cards' own statements: the same number for 10 unread works as for 100.
    assert len(card_queries(store, 10)) == len(card_queries(store, 100))


def test_an_answer_quote_carries_its_stored_anchor_match(store):
    lib = Lib(store)
    svid = lib.work()
    lib.text(svid, ["SYNTHETIC the release model is a Poisson process."])
    (passage,) = [p["id"] for p in store.passages_for(svid) if p["kind"] == "pdf_page"]
    run = lib.new_run("answer")
    step_id = store.step(run, "answer", "model:grounded_answer")["id"]
    sid = db.new_id("sti")
    store.insert_step_input(step_id, lib.rid, run, 0, {
        "step_input_id": sid, "task_type": "grounded_answer", "scope_revision": 1, "skill_package_hash": "sha256:s",
        "sources": [{"source_id": svid}], "passages": [{"passage_id": passage, "source_id": svid}]}, "b", "d", "m", {})
    draft = {"title": "SYNTHETIC answer", "answer_language": "en",
             "claims": [{"claim_label": "C1", "text": "SYNTHETIC claim.", "support_type": "source_stated"},
                        {"claim_label": "C2", "text": "SYNTHETIC second claim.", "support_type": "source_stated"}]}
    store.save_answer(lib.rid, run, step_id, sid, 1, "structurally_valid", draft, {}, links=[
        {"claim_label": "C1", "passage_id": passage, "source_id": svid, "anchor_text": "release model",
         "anchor_match": "normalized"},
        {"claim_label": "C2", "passage_id": passage, "source_id": svid, "anchor_text": "Poisson process"}])
    (answer,) = views.research_view(store, lib.rid)["answers"]
    assert [claim["evidence"][0]["anchor_match"] for claim in answer["claims"]] == ["normalized", None]

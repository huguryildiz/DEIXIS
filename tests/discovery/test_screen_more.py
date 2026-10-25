"""UI parity S20, F12 and F13: the not-read list and the "Screen more" run. SYNTHETIC OpenAlex records and the fake
model, so these tests show the workflow (which works, in which order, two reads per batch, nothing included, budget,
resume, cancel, the refusals), not model quality or live provider access.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.storage.db import new_id, now
from deixis.workflow import answer as fast_answer, screen_more, small_batch
from deixis.workflow.views import research_view
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from fakes import FakeAdapter, valid_response
from test_fetch_overlap_flow import discover, output
from test_abstract_flow import HALF
from test_fulltext_flow import Transport, work
from test_small_batch_flow import app_for, client_of

ACTIVE = ("queued", "running", "pause_requested")


class Crash(BaseException):
    """The process stopping in the middle of a call."""


def settle(client, rid, timeout=60):
    """Wait until no run of the research is active (the discovery queues an answer and its review)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        if all(run["status"] not in ACTIVE for run in view["runs"]):
            return view
        time.sleep(0.05)
    raise AssertionError("the research's runs did not settle")


def discovered(tmp_path, monkeypatch, n, preprints=False, no_abstract=()):
    """A quick discovery (read window N = 25) over `n` SYNTHETIC works the model reads, every run settled. With
    `preprints`, every record is a submitted version, so a published version added later heads its work; the records
    numbered in `no_abstract` come without one."""
    records = ([work(i, title=HALF, version="submittedVersion" if preprints else "publishedVersion",
                     **({"abstract": None} if i in no_abstract else {})) for i in range(n)]
               if preprints or no_abstract else None)
    app, _ = app_for(tmp_path, monkeypatch, n, model_works=True, transport=Transport(records) if records else None)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="quick")
        assert run["status"] == "completed", run
        settle(client, rid)
    return rid, run_id


def harness(tmp_path, responder=valid_response):
    """The library the app wrote, driven by a flow of its own, so a test controls each run's execution."""
    store = Store(db.connect(tmp_path / "data" / "library.sqlite"))
    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8877), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    return SimpleNamespace(store=store, flow=flow, adapter=adapter)


def execute(h, run):
    h.store.update_run(run["id"], status="running")
    asyncio.run(h.flow.execute(run["id"]))
    return h.store.run(run["id"])


def listing(store, discovery_id):
    return output(store, discovery_id, small_batch.LIST_KEY)


def screening_steps(store, run_id):
    return {r["operation_key"]: r["status"] for r in store.conn.execute(
        "SELECT operation_key, status FROM run_steps WHERE run_id = ? AND kind = 'model:abstract_screening'", (run_id,))}


def sent_batches(h, run_id=None):
    """The records of every abstract-screening call the harness adapter answered, read from the stored StepInputs
    (the model sees short handles), oldest first; one run's calls when `run_id` is given."""
    ids = {c["candidate_id"]: c["source_version_id"] for c in h.store.candidates(rid_of(h))}
    rows = h.store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id JOIN runs r ON r.id = s.run_id"
        " WHERE r.kind = 'screen_more' AND s.kind = 'model:abstract_screening'"
        f"{' AND r.id = ?' if run_id else ''} ORDER BY i.rowid", (run_id,) if run_id else ())
    return [[ids[c["candidate_id"]] for c in json.loads(row[0])["candidates"]] for row in rows]


def rid_of(h):
    return h.store.conn.execute("SELECT id FROM researches ORDER BY created_at LIMIT 1").fetchone()[0]


def included(store, rid):
    return store.conn.execute("SELECT COUNT(*) FROM selections WHERE research_id = ? AND state = 'included'",
                              (rid,)).fetchone()[0]


# ---- F13: the run ------------------------------------------------------------------------------------------------


def test_screen_more_reads_the_next_forty_twice_per_batch_and_includes_nothing(tmp_path, monkeypatch):
    rid, discovery_id = discovered(tmp_path, monkeypatch, 90)
    h = harness(tmp_path)
    frozen = listing(h.store, discovery_id)
    before = screen_more.unscreened(h.store, rid, 0, 100)
    assert before["total"] == 65 and before["list_size"] == 90  # the read window took the first 25
    assert [i["signals"]["rank"] for i in before["items"]] == list(range(26, 91))
    revision = h.store.selection_revision(rid)

    run = screen_more.request(h.store, rid, None)
    assert run["kind"] == "screen_more" and run["stage"] == "screening"
    assert run["target"]["heads"] == [item["head"] for item in frozen["items"][25:65]]  # skips the screened 25
    assert run["budget"]["screen_more"]["reads"] == 4 and run["budget"]["max_model_calls"] == 8
    assert run["budget"]["max_provider_requests"] == 0
    assert execute(h, run)["status"] == "completed"

    batches = sent_batches(h)
    assert len(batches) == 4 and batches[0] == batches[1] and batches[2] == batches[3]  # each batch read twice
    assert [len(b) for b in batches] == [20, 20, 20, 20] and not set(batches[0]) & set(batches[2])
    assert batches[0] + batches[2] == run["target"]["heads"]  # in list order
    assert h.store.run(run["id"])["usage"]["model_calls"] == 4
    assert included(h.store, rid) == 0  # two agreeing runs make candidates; nothing is included
    assert not h.store.conn.execute("SELECT 1 FROM stage_decisions WHERE research_id = ? AND outcome = 'include'",
                                    (rid,)).fetchone()
    summary = h.store.existing_step(run["id"], screen_more.SUMMARY_KEY)["output"]
    assert summary["planned"] == 40 and len(summary["candidates"]) == 40 and summary["not_screened"] == []
    assert summary["reason_codes"] == {"runs_agree_candidate": 40}

    after = screen_more.unscreened(h.store, rid, 0, 100)
    assert after["total"] == 25 and [i["signals"]["rank"] for i in after["items"]] == list(range(66, 91))
    # Each batch's candidates moved the revision as they were written: the answer made before is for an earlier one.
    assert h.store.selection_revision(rid) == revision + 2
    assert execute(h, run)["status"] == "completed"  # run again: nothing sent twice, no further move
    assert len(sent_batches(h)) == 4 and h.store.selection_revision(rid) == revision + 2

    second = screen_more.request(h.store, rid, None)
    assert second["target"]["heads"] == [item["head"] for item in frozen["items"][65:90]]
    assert second["budget"]["screen_more"]["reads"] == 4  # 25 works: a batch of 20 and one of 5, each read twice
    assert execute(h, second)["status"] == "completed"
    with pytest.raises(screen_more.NothingToScreen) as refused:
        screen_more.request(h.store, rid, None)
    assert refused.value.code == "nothing_left"


def test_screen_more_honours_its_budget(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 90)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)
    h.store.conn.execute("UPDATE runs SET budget_json = json_set(budget_json, '$.max_model_calls', 2) WHERE id = ?",
                         (run["id"],))
    assert execute(h, run)["status"] == "completed"
    assert len(sent_batches(h)) == 2 and h.store.run(run["id"])["usage"]["model_calls"] == 2
    summary = h.store.existing_step(run["id"], screen_more.SUMMARY_KEY)["output"]
    # The second batch is not half-sent: its 20 works are "not read" and stay on the not-read list.
    assert len(summary["candidates"]) == 20 and len(summary["not_screened"]) == 20
    assert summary["reason_codes"] == {"abstract_not_read": 20, "runs_agree_candidate": 20}
    assert screen_more.unscreened(h.store, rid)["total"] == 45


def test_screen_more_resumes_after_a_crash_without_resending_a_finished_call(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 90)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)

    revision = h.store.selection_revision(rid)
    earlier = [a["id"] for a in research_view(h.store, rid)["answers"] if a["applicability"] == "current"]
    assert earlier
    seen = []

    def crash_on_third(si):
        if len(h.adapter.calls) == 3:
            # The first batch's candidates and the revision move were committed together, before anything else ran.
            seen.append(h.store.selection_revision(rid))
            h.adapter.before = None
            raise Crash

    h.adapter.before = crash_on_third
    with pytest.raises(Crash):
        execute(h, run)
    assert seen == [revision + 1]
    assert Worker.recover(SimpleNamespace(store=h.store))["runs"] == 1
    assert h.store.selection_revision(rid) == revision + 1
    answers = {a["id"]: a["applicability"] for a in research_view(h.store, rid)["answers"]}
    assert all(answers[aid] == "stale_selection" for aid in earlier)  # no stored candidate behind a "current" answer
    assert h.store.run(run["id"])["pause_reason"] == "backend_restarted"
    steps = screening_steps(h.store, run["id"])
    assert sorted(steps.values()) == ["outcome_unknown", "succeeded", "succeeded"]

    h.store.resume_run(run["id"])
    assert execute(h, run)["status"] == "completed"
    batches = sent_batches(h)
    assert len(batches) == 5 and batches[2] == batches[3] == batches[4]  # only the unfinished calls went again
    assert len(h.store.existing_step(run["id"], screen_more.SUMMARY_KEY)["output"]["candidates"]) == 40
    assert included(h.store, rid) == 0


def test_a_paused_screen_more_resumes_without_repeating_and_a_cancel_stops_it(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 90)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)
    revision = h.store.selection_revision(rid)

    def pause_after_first_batch(si):
        if len(h.adapter.calls) == 2:
            h.store.update_run(run["id"], status="pause_requested", pause_reason="user_requested")

    h.adapter.before = pause_after_first_batch
    stopped = execute(h, run)
    assert (stopped["status"], stopped["pause_reason"]) == ("paused", "user_requested")
    assert len(sent_batches(h)) == 2 and h.store.existing_step(run["id"], screen_more.SUMMARY_KEY) is None
    h.adapter.before = None
    h.store.resume_run(run["id"])
    assert execute(h, run)["status"] == "completed"
    assert len(sent_batches(h)) == 4  # the first batch was not read again
    assert h.store.selection_revision(rid) > revision

    second = screen_more.request(h.store, rid, None)

    def cancel_during_first(si):
        if len(h.adapter.calls) == 5:
            h.store.update_run(second["id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")

    h.adapter.before = cancel_during_first
    assert execute(h, second)["status"] == "cancelled"
    assert len(sent_batches(h)) == 5  # no call after the cancel
    assert h.store.existing_step(second["id"], screen_more.SUMMARY_KEY) is None
    assert screen_more.unscreened(h.store, rid)["total"] == 25  # the cancelled run closed no batch


def test_a_newer_question_revision_cancels_screen_more(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 60)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)

    def revise(si):
        if len(h.adapter.calls) == 1:
            h.store.revise_scope(rid, h.store.research(rid)["version"], "SYNTHETIC another question", None)

    h.adapter.before = revise
    stopped = execute(h, run)
    assert (stopped["status"], stopped["pause_reason"]) == ("cancelled", "scope_revised")


def test_screen_more_refusals(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 30)
    h = harness(tmp_path)
    h.store.conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at,"
                         " updated_at) VALUES ('run_ACTIVE00000001', ?, 1, 'answer', 'running', 'answer', '{}', 'now', 'now')",
                         (rid,))
    with pytest.raises(RevisionConflict):
        screen_more.request(h.store, rid, None)  # one active run per research
    h.store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE id = 'run_ACTIVE00000001'")
    first = screen_more.request(h.store, rid, "same")
    assert screen_more.request(h.store, rid, "same")["id"] == first["id"]  # a replayed key returns the same run
    assert len(first["target"]["heads"]) == 5 and first["budget"]["screen_more"]["reads"] == 2
    execute(h, first)
    with pytest.raises(screen_more.NothingToScreen) as refused:
        screen_more.request(h.store, rid, None)
    assert refused.value.code == "nothing_left"

    other = h.store.create_research("SYNTHETIC unsearched question", "academic", "quick", [], "fake", "fake-model", None)
    with pytest.raises(screen_more.NothingToScreen) as refused:
        screen_more.request(h.store, other, None)
    assert refused.value.code == "no_completed_discovery"


def test_a_work_the_person_already_decided_is_neither_listed_nor_planned(tmp_path, monkeypatch):
    rid, discovery_id = discovered(tmp_path, monkeypatch, 60)
    h = harness(tmp_path)
    head = listing(h.store, discovery_id)["items"][25]["head"]  # the first work below the read window
    version = h.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (rid, head)).fetchone()[0]
    h.store.set_user_selection(rid, head, "excluded", version, "SYNTHETIC not this one")
    page = screen_more.unscreened(h.store, rid, 0, 100)
    assert page["total"] == 34 and head not in {i["source_version_id"] for i in page["items"]}
    run = screen_more.request(h.store, rid, None)
    assert head not in run["target"]["heads"] and len(run["target"]["heads"]) == 34
    pending = run["target"]["heads"][0]  # a selection the person set back to pending is the person's too
    version = h.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (rid, pending)).fetchone()[0]
    h.store.set_user_selection(rid, pending, "pending", version, "SYNTHETIC not sure")
    assert pending not in {i["source_version_id"] for i in screen_more.unscreened(h.store, rid, 0, 100)["items"]}


def new_answer(h, rid, **extra):
    scope = h.store.scope(rid, h.store.research(rid)["current_scope_revision"])
    budget = fast_answer.answer_run_budget(h.store, rid, scope) | extra
    run = execute(h, h.store.create_run(rid, "answer", budget, None))
    assert run["status"] == "completed", run
    h.store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE research_id = ? AND status = 'queued'", (rid,))
    return output(h.store, run["id"], fast_answer.INPUT)


def test_only_a_new_answer_the_person_starts_reads_screen_more_candidates(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 60)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)
    assert execute(h, run)["status"] == "completed"
    automatic = new_answer(h, rid, trigger="auto_after_discovery")
    assert not [r for r in automatic["items"] if r.get("screened_after_cutoff")]
    started = new_answer(h, rid)
    later = [r for r in started["items"] if r.get("screened_after_cutoff")]
    assert len(later) == 35 and {r["evidence_basis"] for r in later} == {"abstract_screening"}
    assert all(r["route"] == "abstract" and len(r["abstract_ids"]) == 1 for r in later)
    shown = {a["run_id"]: a["screened_after_cutoff"] for a in research_view(h.store, rid)["answers"]}
    marked = [rows for rows in shown.values() if rows]
    assert len(marked) == 1 and len(marked[0]) == 35  # the person's answer only; the automatic one reads none
    assert {x["evidence_basis"] for x in marked[0]} == {"abstract_screening"}


def test_a_new_head_the_person_excluded_keeps_its_work_out_of_the_answer(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 60, preprints=True)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)
    assert execute(h, run)["status"] == "completed"
    kept_preprint, excluded_preprint = run["target"]["heads"][:2]
    published = {}
    for preprint in (kept_preprint, excluded_preprint):  # a published version of the work joins after Screen more
        svid = new_id("srv")
        h.store.conn.execute("INSERT INTO source_versions (id, work_id, title, doi, origin, version_label, created_at)"
                             " VALUES (?, ?, ?, ?, 'provider', 'publishedVersion', ?)",
                             (svid, h.store.source(preprint)["work_id"], "SYNTHETIC published version",
                              f"10.1/published.{svid}", now()))
        h.store.add_to_corpus(rid, svid, "user_upload")
        assert h.store.work_heads(rid)[h.store.source(preprint)["work_id"]] == svid
        published[preprint] = svid
    version = h.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (rid, published[excluded_preprint])).fetchone()[0]
    h.store.set_user_selection(rid, published[excluded_preprint], "excluded", version, "SYNTHETIC not this work")

    rows = {r["source_version_id"]: r for r in new_answer(h, rid)["items"]}
    assert rows[kept_preprint]["screened_after_cutoff"] == run["id"]
    assert rows[kept_preprint]["head_after_cutoff"] == published[kept_preprint]  # the version change is recorded
    assert excluded_preprint not in rows  # the person's exclusion of the new head keeps the work out


def test_an_excluded_or_disagreeing_work_is_not_admitted(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 60)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)
    assert execute(h, run)["status"] == "completed"
    first, second, third = run["target"]["heads"][:3]
    from deixis.workflow.decisions import DecisionStore
    decisions = DecisionStore(h.store)
    decisions.record(rid, first, "criterion_absent")  # a full-text exclusion of the work
    other = new_id("srv")  # another version of the second work, read in full and included: the versions disagree
    h.store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                         " VALUES (?, ?, 'SYNTHETIC other version', 'provider', 'acceptedVersion', ?)",
                         (other, h.store.source(second)["work_id"], now()))
    h.store.add_to_corpus(rid, other, "search", candidate=False)
    decisions.record(rid, second, "criterion_absent")
    decisions.record(rid, other, "all_parts_verified")
    assert decisions.work_outcome(rid, h.store.source(second)["work_id"])["reason_code"] == "versions_disagree"
    # A second abstract stored after the reads: the record's abstract is no longer the text both runs were shown.
    h.store._insert_passage(third, None, "abstract", None, None, "provider", None, None, "SYNTHETIC a newer abstract.")
    admitted = screen_more.answer_admissions(h.store, rid, 1)
    assert len(admitted) == 32 and not {first, second, third} & set(admitted)


def test_the_answer_reads_the_version_screen_more_read_when_the_cutoff_held_another(tmp_path, monkeypatch):
    rid, discovery_id = discovered(tmp_path, monkeypatch, 60, no_abstract=range(30, 60))
    h = harness(tmp_path)
    # A work below the read window whose record has no abstract gets another version that has one (version B).
    item = next(i for i in listing(h.store, discovery_id)["items"][25:] if not h.store.conn.execute(
        "SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (i["head"],)).fetchone())
    cutoff_record, work_id = item["head"], item["work_id"]
    other = new_id("srv")
    h.store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                         " VALUES (?, ?, 'SYNTHETIC irrigation scheduling of an open field crop, accepted', 'provider',"
                         " 'acceptedVersion', ?)", (other, work_id, now()))
    h.store.add_to_corpus(rid, other, "search", scope_revision=1)  # a search record too, so the stage can send it
    h.store._insert_passage(other, None, "abstract", None, None, "provider", None, None,
                            "We vary the irrigation scheduling of an open field crop and report the water it used.")
    assert h.store.work_heads(rid)[work_id] == cutoff_record
    run = screen_more.request(h.store, rid, None)
    assert cutoff_record in run["target"]["heads"]
    assert execute(h, run)["status"] == "completed"
    assert other in sent_batches(h)[0] + sent_batches(h)[2]  # both runs read version B, not the cutoff's record
    assert other in screen_more.answer_admissions(h.store, rid, 1)

    rows = [r for r in new_answer(h, rid)["items"] if r["work_id"] == work_id]
    assert len(rows) == 1  # still one row per work: B replaced A
    row = rows[0]
    abstract = h.store.conn.execute("SELECT id FROM passages WHERE source_version_id = ? AND kind = 'abstract'",
                                    (other,)).fetchone()[0]
    assert (row["source_version_id"], row["cutoff_source_version_id"]) == (other, cutoff_record)
    assert row["version"]["title"] == h.store.source(other)["title"] and row["abstract_ids"] == [abstract]
    decision = h.store.conn.execute("SELECT source_version_id FROM stage_decisions WHERE id = ?",
                                    (row["decision_id"],)).fetchone()[0]
    assert decision == other and row["reason"] is None and row["evidence_basis"] == "abstract_screening"
    shown = [x for a in research_view(h.store, rid)["answers"] for x in a["screened_after_cutoff"] if x["work_id"] == work_id]
    assert shown and shown[0]["source_version_id"] == other and shown[0]["cutoff_source_version_id"] == cutoff_record


def test_a_work_whose_abstract_is_on_a_version_no_search_offered_is_not_planned(tmp_path, monkeypatch):
    rid, discovery_id = discovered(tmp_path, monkeypatch, 100, no_abstract=range(45, 100))
    h = harness(tmp_path)
    items = listing(h.store, discovery_id)["items"]
    has_abstract = lambda svid: h.store.conn.execute(
        "SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (svid,)).fetchone()
    # The 55 records without an abstract head the list; the read window took 25 of them, 30 sit right below it.
    assert [bool(has_abstract(i["head"])) for i in items] == [False] * 55 + [True] * 45
    blocked = [i["work_id"] for i in items[25:55]]
    for work_id in blocked:  # another version a provider listed, with an abstract, but not a search candidate
        other = new_id("srv")
        h.store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                             " VALUES (?, ?, 'SYNTHETIC accepted version', 'provider', 'acceptedVersion', ?)",
                             (other, work_id, now()))
        h.store.add_to_corpus(rid, other, "search", candidate=False)
        h.store._insert_passage(other, None, "abstract", None, None, "provider", None, None,
                                "We vary the irrigation scheduling of an open field crop and report the water it used.")
    page = screen_more.unscreened(h.store, rid, 0, 100)
    rows = {i["work_id"]: i for i in page["items"]}
    assert all(rows[w]["has_abstract"] and not rows[w]["screenable"] for w in blocked)
    assert {rows[w]["not_screenable_reason"] for w in blocked} == {"abstract_not_on_a_searched_version"}
    assert page["total"] == 75 and page["screenable"] == 45

    # Planned first, the 30 blocked works would take most of every run and be read by none of them.
    first = screen_more.request(h.store, rid, None)
    assert first["target"]["work_ids"] == [i["work_id"] for i in items[55:95]]
    assert execute(h, first)["status"] == "completed"
    second = screen_more.request(h.store, rid, None)
    assert second["target"]["work_ids"] == [i["work_id"] for i in items[95:100]]
    assert execute(h, second)["status"] == "completed"
    assert len(sent_batches(h)) == 6 and not set(blocked) & set(h.store.work_ids(sum(sent_batches(h), [])).values())
    with pytest.raises(screen_more.NothingToScreen):  # a third request finds nothing it could read
        screen_more.request(h.store, rid, None)
    assert screen_more.unscreened(h.store, rid)["total"] == 30  # still listed as found and not read


def test_a_planned_work_the_stage_did_not_read_is_not_planned_again(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 60)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)
    skipped = run["target"]["heads"][0]
    stage = h.flow._abstract_code_stage

    def without_first(run_, scope, vocabulary, order, **options):  # a work the stage leaves out for any reason
        return stage(run_, scope, vocabulary, [svid for svid in order if svid != skipped], **options)

    monkeypatch.setattr(h.flow, "_abstract_code_stage", without_first)
    assert execute(h, run)["status"] == "completed"
    monkeypatch.setattr(h.flow, "_abstract_code_stage", stage)
    row = next(i for i in screen_more.unscreened(h.store, rid, 0, 100)["items"] if i["source_version_id"] == skipped)
    assert (row["screenable"], row["not_screenable_reason"]) == (False, "screen_more_could_not_read")
    with pytest.raises(screen_more.NothingToScreen):
        screen_more.request(h.store, rid, None)  # no loop on the same work


# ---- F12 and the routes ------------------------------------------------------------------------------------------


def test_unscreened_and_screen_more_routes(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True)
    with client_of(app) as client:
        assert client.get("/api/researches/res_missing/unscreened").status_code == 404
        rid, discovery_id, _, run = discover(client, effort="quick")
        view = settle(client, rid)
        store = app.state.store
        frozen = listing(store, discovery_id)
        answer = next(a for a in view["answers"] if a["run_id"])
        assert answer["applicability"] == "current"

        page = client.get(f"/api/researches/{rid}/unscreened", params={"offset": 10, "limit": 5}).json()
        assert page["total"] == 35 and page["screenable"] == 35 and page["list_size"] == 60
        assert [i["source_version_id"] for i in page["items"]] == [i["head"] for i in frozen["items"][35:40]]
        assert [i["signals"]["rank"] for i in page["items"]] == [36, 37, 38, 39, 40]
        assert "prioritization signals" in page["signals_note"] and page["items"][0]["title"].startswith("SYNTHETIC")
        assert set(page["items"][0]["signals"]) == {"rank", "similarity"}
        everything = client.get(f"/api/researches/{rid}/unscreened", params={"limit": 100}).json()["items"]
        assert [i["signals"]["rank"] for i in everything] == list(range(26, 61))
        assert client.get(f"/api/researches/{rid}/unscreened", params={"limit": 101}).status_code == 422
        assert client.get(f"/api/researches/{rid}/unscreened", params={"offset": -1}).status_code == 422

        url = f"/api/researches/{rid}/screen-more"
        assert client.post(url, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        store.conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at,"
                           " updated_at) VALUES ('run_ACTIVE00000001', ?, 1, 'answer', 'running', 'answer', '{}', 'now', 'now')",
                           (rid,))
        assert client.post(url).status_code == 409
        store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE id = 'run_ACTIVE00000001'")
        first = client.post(url, headers={"Idempotency-Key": "s1"})
        assert first.status_code == 202, first.text
        assert first.json()["kind"] == "screen_more" and len(first.json()["target"]["heads"]) == 35
        assert client.post(url, headers={"Idempotency-Key": "s1"}).json()["id"] == first.json()["id"]
        view = settle(client, rid)
        assert next(r for r in view["runs"] if r["id"] == first.json()["id"])["status"] == "completed"
        assert client.get(f"/api/researches/{rid}/unscreened").json()["total"] == 0
        refused = client.post(url)
        assert refused.status_code == 422 and refused.json()["code"] == "nothing_left"
        assert next(a for a in view["answers"] if a["id"] == answer["id"])["applicability"] == "stale_selection"

        # The next answer reads the works Screen more made candidates, from their abstracts; nothing is included.
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert again.status_code == 202, again.text
        settle(client, rid)
        plan = output(store, again.json()["id"], "fast_path:v1:answer_input")
        later = [row for row in plan["items"] if row.get("screened_after_cutoff") == first.json()["id"]]
        assert len(later) == 35 and all(row["route"] == "abstract" for row in later)
        assert plan["excluded_reasons"].get("outside_read_window", 0) == 0
        assert included(store, rid) == 0

        other = client.post("/api/researches", json={"question": "SYNTHETIC attached question", "model_connection": "fake",
                                                      "requested_model": "fake-model", "effort": "quick",
                                                      "source_scope": "attached"}).json()["research"]["id"]
        assert client.get(f"/api/researches/{other}/unscreened").status_code == 422
        refused = client.post(f"/api/researches/{other}/screen-more")
        assert refused.status_code == 422 and refused.json()["code"] == "no_completed_discovery"


# ---- a late full-text revision of an answer that read a Screen more row on another version --------------------------


def admitted_row_on_another_version(lib):
    """Put into the base answer's stored input the row Screen more admission writes when the runs read version B of a
    work whose head is A (SYNTHETIC; the same fields `fast_answer.input_plan` sets)."""
    from test_fast_path_late_revision import row as late_row

    head = lib.store.create_upload_source("SYNTHETIC admitted work, record A")
    lib.store.add_to_corpus(lib.rid, head, "user_upload")
    other = new_id("srv")
    lib.store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                           " VALUES (?, ?, 'SYNTHETIC admitted work, version B', 'provider', 'acceptedVersion', ?)",
                           (other, lib.store.source(head)["work_id"], now()))
    lib.store.add_to_corpus(lib.rid, other, "search", candidate=False)
    passage = lib.store._insert_passage(other, None, "abstract", None, None, "provider", None, None,
                                        "SYNTHETIC exercise improves fatigue in the admitted version B.")
    assert lib.store.answer_versions(lib.rid)[head] == head  # the work's answer version is A, the row reads B
    step_id = late_row(lib)["base_input_step_id"]
    base = json.loads(lib.store.conn.execute("SELECT output_json FROM run_steps WHERE id = ?", (step_id,)).fetchone()[0])
    source = lib.store.source(other)
    base["items"].append({
        "work_id": source["work_id"], "head": head, "position": None, "source_version_id": other, "route": "abstract",
        "decision_id": None, "abstract_decision_id": None, "fulltext_decision_id": None, "asset_id": None,
        "abstract_ids": [passage], "fulltext_ids": [], "reason": None, "base_reason": "outside_read_window",
        "base_route": "abstract", "file_unverified": False, "user_priority": False, "override_reason": None,
        "version": {k: source.get(k) for k in fast_answer.VERSION_FIELDS}, "screened_after_cutoff": "run_SYNTHETIC",
        "evidence_basis": "abstract_screening", "cutoff_source_version_id": head})
    base["passage_ids"].append(passage)
    lib.store.conn.execute("UPDATE run_steps SET output_json = ? WHERE id = ?", (json.dumps(base), step_id))
    return other


def late_revision_of(lib):
    from deixis.workflow import late_revision
    from test_fast_path_late_revision import read_late, row as late_row

    read_late(lib)
    late_revision.advance(lib.flow, lib.rid)
    revision = lib.store.run(late_row(lib)["answer_run_id"])
    lib.store.update_run(revision["id"], status="running")
    asyncio.run(lib.flow.execute(revision["id"]))
    return lib.store.run(revision["id"]), late_row(lib)


def test_a_late_revision_keeps_a_screen_more_row_on_another_version(tmp_path):
    from deixis.workflow import late_revision
    from test_fast_path_late_revision import prepared

    lib = prepared(tmp_path)
    other = admitted_row_on_another_version(lib)
    revision, late = late_revision_of(lib)
    assert (revision["status"], late["status"]) == ("completed", "published"), revision
    plan = lib.store.existing_step(revision["id"], late_revision.REVISION_INPUT)["output"]
    kept = [i for i in plan["items"] if i["source_version_id"] == other]
    assert len(kept) == 1 and kept[0]["screened_after_cutoff"] == "run_SYNTHETIC" and kept[0]["route"] == "abstract"


def test_a_real_change_to_the_screen_more_version_still_pauses_the_late_revision(tmp_path):
    from test_fast_path_late_revision import prepared

    lib = prepared(tmp_path)
    other = admitted_row_on_another_version(lib)
    lib.store.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC retitled version B' WHERE id = ?", (other,))
    revision, _ = late_revision_of(lib)
    assert (revision["status"], revision["pause_reason"]) == ("paused", "source_changed")

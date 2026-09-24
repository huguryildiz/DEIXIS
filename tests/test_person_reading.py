"""A person's file and the reading it asks for, at the store and the flow (slice 18b, decisions 1–10).

Records, criteria and page texts are SYNTHETIC and from two fields (diffusion channel scheduling, greenhouse
irrigation). Files are written the way an upload writes them (`origin = user_upload`, one passage per page); reading
runs are executed by the flow with a scripted model and closed the way the worker closes them. Passing shows the code,
the request's states, the reading order and the precedence behave as the slice says; it says nothing about how well a
model reads a publisher's file, or how long a person waits for it.
"""

import asyncio
import time

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.workflow import adjudication, fulltext, person_reading, queue
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response
from test_adjudication import CANDIDATE, decision
from test_queue import Lib, body

CANDIDATE_CODE = "runs_agree_candidate"


def silent(si):
    """The reading model answers nothing usable for any work: every reading call is invalid output."""
    return "SYNTHETIC not a reading" if si["task_type"] == "fulltext_adjudication" else valid_response(si)


def absent(si):
    """Both reading runs find no part of the criterion: the work does not meet it."""
    import json
    if si["task_type"] != "fulltext_adjudication":
        return valid_response(si)
    body = json.loads(valid_response(si))
    for part in body["parts"]:
        part.update(label="absent", quote="", passage_id=None)
    return json.dumps(body)


class Research:
    """One SYNTHETIC `sw` research with a frozen criterion, a flow over its store and a scripted model."""

    def __init__(self, tmp_path, field="channels", reading="auto", responder=valid_response):
        self.connection = db.connect(tmp_path / "data" / "library.sqlite")
        db.migrate(self.connection)
        self.store = Store(self.connection)
        self.lib = Lib(self.store, field)
        self.rid, self.ds = self.lib.rid, self.lib.ds
        self.adapter = FakeAdapter(responder)
        self.flow = ResearchFlow(FlowDeps(
            Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", fulltext_adjudication=reading),
            self.store, {"fake": self.adapter}, skill.load_skill_package(), None))

    def work(self):
        """A published record heading its own work, a candidate after the abstract stage."""
        svid = self.lib.work()
        self.ds.record(self.rid, svid, CANDIDATE_CODE)
        return svid

    def pages(self, n=2):
        return [self.lib.field["page"], self.lib.field["cue"]][:n]

    def file(self, svid, pages, origin="user_upload"):
        """A file in use on `svid`, one passage per page; returns its identifier."""
        asset, version = db.new_id("ast"), "pymupdf-synthetic"
        with db.transaction(self.store.conn):
            self.store.conn.execute(
                "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
                " original_filename, retrieved_at, origin, extraction_status, extraction_version, page_count)"
                " VALUES (?, ?, ?, 20, 'application/pdf', 'synthetic.pdf', 'synthetic.pdf', ?, ?, ?, ?, ?)",
                (asset, svid, asset.ljust(64, "0")[:64], db.now(), origin,
                 "succeeded" if any(pages) else "no_text", version, len(pages)))
            for page, text in enumerate(pages, start=1):
                if text:
                    self.store._insert_passage(svid, asset, "pdf_page", page, None, None, None, version, text)
        return asset

    def attach(self, svid, pages=None, queue_it=True):
        """What the confirmation writes: the file, its code and request, and the queue, in one transaction."""
        with db.transaction(self.store.conn):
            asset = self.file(svid, self.pages() if pages is None else pages)
            outcome = self.flow.attach_person_file(self.rid, svid, asset)
            if queue_it:
                self.flow.queue_person_reading(self.rid)
        return asset, outcome

    def request(self, asset):
        row = self.store.conn.execute("SELECT * FROM person_pdf_requests WHERE asset_id = ?", (asset,)).fetchone()
        return dict(row) if row else None

    def runs(self, kind="fulltext_adjudication"):
        return [dict(r) for r in self.store.conn.execute(
            "SELECT id, status, idempotency_key FROM runs WHERE research_id = ? AND kind = ? ORDER BY created_at, rowid",
            (self.rid, kind))]

    def work_through(self, run_id, stop=None):
        """The worker's turn for one run: running, executed, then closed and followed by the person's queue."""
        self.store.update_run(run_id, event="run_started", status="running", pause_reason=None)
        if stop:
            stop(run_id)
        asyncio.run(self.flow.execute(run_id))
        return self.flow.person_run_ended(run_id)

    def drain(self):
        """Every queued run of this research, one at a time, as the worker takes them."""
        done = []
        while (row := self.store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND status = 'queued'"
                                              " ORDER BY created_at LIMIT 1", (self.rid,)).fetchone()):
            self.work_through(row[0])
            done.append(row[0])
        return done

    def code(self, svid):
        return (self.ds.current(self.rid, svid, "fulltext") or {}).get("reason_code")

    def outcome(self, svid):
        return self.ds.work_outcome(self.rid, self.lib.work_of(svid))

    def reextract(self, svid, asset):
        """The same file extracted again with different text, as a new extraction writes it (D45)."""
        version = db.new_id("ext")
        with db.transaction(self.store.conn):
            for page, text in self.store.page_texts(svid).items():
                self.store._insert_passage(svid, asset, "pdf_page", page, None, None, None, version,
                                           f"{text} SYNTHETIC re-extracted.")
            self.store.conn.execute("UPDATE source_assets SET extraction_version = ? WHERE id = ?", (version, asset))

    def plan(self, run_id):
        return self.store.existing_step(run_id, "adjudication_plan")["output"]

    def answer_input(self):
        """What an answer run gives the model: each passage of its input as (version, kind). Run as the worker runs
        it, but without the person's queue after it, so a waiting file stays waiting."""
        from deixis.domain.rules import TEST_EFFORT_BUDGETS
        budget = dict(TEST_EFFORT_BUDGETS[self.store.scope(self.rid)["effort"]].__dict__)
        run = self.store.create_run(self.rid, "answer", budget, None)["id"]
        self.store.update_run(run, event="run_started", status="running", pause_reason=None)
        asyncio.run(self.flow.execute(run))
        import json
        row = self.store.conn.execute("SELECT s.payload_json FROM step_inputs s JOIN run_steps t ON t.id ="
                                      " json_extract(s.payload_json, '$.step_id') WHERE t.run_id = ?"
                                      " AND s.task_type = 'grounded_answer'", (run,)).fetchone()
        sent = json.loads(row[0])["passages"] if row else []
        return {(p["source_version_id"], p["kind"]) for p in (self.store.passage(q["passage_id"]) for q in sent)}

    def close(self):
        self.connection.close()


@pytest.fixture
def research(tmp_path):
    made = []

    def make(**kw):
        r = Research(tmp_path / str(len(made)), **kw)
        made.append(r)
        return r

    yield make
    for r in made:
        r.close()


# ---- decision 1: the code on attach, named after the file ---------------------------------------------------------

def test_a_file_with_text_gets_not_read_yet_and_one_without_a_text_layer_text_unreadable_noted_with_the_file(research):
    r = research()
    read, blank = r.work(), r.work()
    asset, outcome = r.attach(read, queue_it=False)
    blank_asset, blank_outcome = r.attach(blank, pages=[""], queue_it=False)
    assert (outcome, r.code(read)) == ("requested", "not_read_yet")
    assert r.ds.current(r.rid, read, "fulltext")["note"] == f"person_pdf:{asset}"
    assert (blank_outcome, r.code(blank)) == ("unreadable", "text_unreadable")
    assert r.ds.current(r.rid, blank, "fulltext")["note"] == f"person_pdf:{blank_asset}"
    # A file with no text asks for no reading: it stays waiting for a PDF, with the reason its own file gives.
    assert r.request(asset)["status"] == "waiting" and r.request(blank_asset) is None
    step = r.lib.new_run("fulltext_fetch")
    plan = r.store.step(step, "fulltext_plan", "code:fulltext_plan")
    r.store.finish_step(plan["id"], "succeeded", output={"works": [read, blank]})
    from deixis.workflow import waiting
    rows = waiting.waiting_view(r.store, r.rid)["rows"]
    assert [(row["head"], row["reason_code"]) for row in rows] == [(blank, "text_unreadable")]


def test_the_code_on_attach_replaces_an_earlier_code_or_model_decision_about_that_version(research):
    r = research()
    fetched, read_before = r.work(), r.work()
    r.ds.record(r.rid, fetched, "no_fulltext")
    # A model decision about an earlier file of the version, since removed as the wrong file (D50).
    old = r.file(read_before, r.pages(), origin="download")
    r.ds.record(r.rid, read_before, "criterion_absent")
    r.store.remove_asset(r.rid, read_before, old)
    r.attach(fetched, queue_it=False)
    r.attach(read_before, queue_it=False)
    assert r.code(fetched) == "not_read_yet" and r.code(read_before) == "not_read_yet"
    assert [row["reason_code"] for row in r.ds.history(r.rid, read_before)] == ["runs_agree_candidate", "criterion_absent",
                                                                               "not_read_yet"]


def test_a_reading_decision_made_after_the_file_is_not_written_over(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    r.drain()
    assert r.code(svid) == "all_parts_verified"
    # A later retrieval run re-derives `not_read_yet` for a work with text; the reading's decision stands.
    run = r.store.run(r.lib.new_run("fulltext_fetch"))
    r.flow._write_fulltext_codes(run, None, [(svid, "not_read_yet")])
    assert r.code(svid) == "all_parts_verified"
    assert adjudication.person_should_write(r.ds.current(r.rid, svid, "fulltext"), "not_read_yet",
                                            person_reading.note_for(asset)) is True  # only an attach would, and it is new


def test_the_same_code_for_another_file_is_a_new_decision_and_for_the_same_file_is_not(research):
    r = research()
    svid = r.work()
    first = r.ds.record(r.rid, svid, "not_read_yet", note="person_pdf:ast_one")
    again = r.ds.record(r.rid, svid, "not_read_yet", note="person_pdf:ast_one")
    other = r.ds.record(r.rid, svid, "not_read_yet", note="person_pdf:ast_two")
    assert again["id"] == first["id"] and other["id"] != first["id"]
    # A note that names no person's file keeps the rule as it was: the same code from the same step is written once.
    plain = r.ds.record(r.rid, svid, "no_fulltext", note="SYNTHETIC")
    assert r.ds.record(r.rid, svid, "no_fulltext", note="SYNTHETIC other")["id"] == plain["id"]


# ---- decision 3: the person's decisions ----------------------------------------------------------------------------

def test_pdf_wrong_speaks_for_its_own_version_and_a_file_on_another_version_is_read(research):
    r = research()
    published = r.lib.published("10.9999/synth.pw")
    preprint = r.lib.preprint("10.9999/synth.pw")
    r.ds.record(r.rid, published, CANDIDATE_CODE)
    r.file(published, r.pages(), origin="download")
    r.ds.record(r.rid, published, "all_parts_verified")  # the model's include, on the file the person calls wrong
    wrong = r.ds.record(r.rid, published, "human_pdf_wrong")
    assert r.outcome(published)["reason_code"] == "human_pdf_wrong"
    asset, outcome = r.attach(preprint)
    # The person's answer is not withdrawn and the include it replaced does not come back.
    assert outcome == "requested" and r.ds.current(r.rid, published, "fulltext")["id"] == wrong["id"]
    assert r.code(preprint) == "not_read_yet" and r.request(asset)["status"] == "waiting"
    assert r.outcome(published) == {"stage": "fulltext", "outcome": "unresolved", "reason_code": "not_read_yet",
                                    "decided_by": "code", "source_version_id": preprint}
    works = {w["work_id"]: w for w in r.flow._fulltext_works(r.rid)}
    assert fulltext.group_of(works[r.lib.work_of(published)], reading=True) is not None
    [run] = r.drain()
    assert r.plan(run)["works"][0]["read_version"] == preprint
    assert r.code(preprint) == "all_parts_verified" and r.request(asset)["status"] == "read"
    assert r.outcome(published)["source_version_id"] == preprint and r.code(published) == "human_pdf_wrong"
    summary = r.store.existing_step(run, "adjudication_summary")["output"]
    assert summary["include"] == 1 and "human_decided" not in summary  # read, not held back by the person


@pytest.mark.parametrize("code", ["human_include", "human_criterion_not_met", "human_not_sure"])
def test_any_other_decision_of_the_person_stands_and_the_file_is_only_added(research, code):
    r = research()
    svid = r.work()
    r.ds.record(r.rid, svid, code)
    asset, outcome = r.attach(svid)
    assert outcome == "decision_stands" and r.code(svid) == code
    assert r.request(asset) is None and r.runs() == []
    assert r.store.has_asset(svid)


def test_pdf_wrong_on_the_version_the_file_goes_to_also_stands(research):
    r = research()
    svid = r.work()
    old = r.file(svid, r.pages(), origin="download")
    r.ds.record(r.rid, svid, "human_pdf_wrong")
    r.store.remove_asset(r.rid, svid, old)
    asset, outcome = r.attach(svid)
    assert outcome == "decision_stands" and r.code(svid) == "human_pdf_wrong" and r.request(asset) is None


def test_group_of_holds_back_a_pdf_wrong_work_unless_another_version_carries_a_persons_file():
    wrong = {"reason_code": "human_pdf_wrong", "decided_by": "human", "stale": False}

    def work_with(person_on):
        versions = [{"id": v, "has_text": True, "abstract": CANDIDATE, "fulltext": wrong if v == "v1" else None,
                     "person": {"status": "waiting", "order": ["t", v]} if v == person_on else None}
                    for v in ("v1", "v2")]
        return {"work_id": "w", "head": "v1", "selection": None, "versions": versions}

    assert fulltext.group_of(work_with(None), reading=True) is None
    assert fulltext.group_of(work_with("v1"), reading=True) is None  # the file of the version called wrong
    assert fulltext.group_of(work_with("v2"), reading=True) == "candidate"
    assert fulltext.group_of(work_with("v2")) is None  # the retrieval's rule is what it was before slice 18b
    assert adjudication.read_plan([work_with("v2")], [], 10)["works"] == ["v1"]
    assert adjudication.person_version(work_with("v2")) == "v2"


def test_the_retrieval_plans_a_pdf_wrong_work_with_a_person_s_file_as_it_did_before_slice_18b(research):
    r = research()
    published = r.lib.published("10.9999/synth.fetch")
    preprint = r.lib.preprint("10.9999/synth.fetch")
    r.ds.record(r.rid, published, CANDIDATE_CODE)
    r.file(published, r.pages(), origin="download")
    r.ds.record(r.rid, published, "human_pdf_wrong")
    asset, outcome = r.attach(preprint, queue_it=False)
    assert outcome == "requested" and r.request(asset)["status"] == "waiting"
    works = r.flow._fulltext_works(r.rid)
    # The same works as the rule before slice 18b sees them: no version carries a person's request.
    before = [dict(work, versions=[dict(version, person=None) for version in work["versions"]]) for work in works]
    head = r.lib.head(published)
    plan, expected = fulltext.fetch_plan(works, [], 10), fulltext.fetch_plan(before, [], 10)
    assert plan == expected and head not in plan["already_text"] + plan["works"] + plan["not_reached"]
    # The reading takes the exception: the person's file is read.
    assert adjudication.read_plan(works, [], 10)["works"] == [head]


# ---- decision 4: the request's states -------------------------------------------------------------------------------

def test_the_request_waits_with_the_attach_is_planned_with_the_plan_and_read_with_the_decision(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    request = r.request(asset)
    assert (request["status"], request["attempt"], request["scope_revision"]) == ("waiting", 0, 1)
    assert request["criterion_hash"] == r.store.criterion_key(r.rid)[1]
    [run] = [row["id"] for row in r.runs()]
    r.store.update_run(run, status="running")
    plan = r.flow._adjudication_plan(r.store.run(run), r.store.scope(r.rid))
    planned = r.request(asset)
    assert (planned["status"], planned["run_id"], planned["page_digest"]) == ("planned", run,
                                                                              plan["works"][0]["page_digest"])
    asyncio.run(r.flow.execute(run))
    r.flow.person_run_ended(run)
    read = r.request(asset)
    assert read["status"] == "read" and read["decision_id"] == r.ds.current(r.rid, svid, "fulltext")["id"]
    events = [row[0] for row in r.store.conn.execute(
        "SELECT json_extract(payload_json, '$.status') FROM events WHERE type = 'person_pdf_request' ORDER BY id")]
    assert events == ["waiting", "planned", "read"]


def test_a_revised_question_leaves_the_request_stale_and_as_it_was(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid, queue_it=False)
    r.lib.revise()
    assert r.flow.queue_person_reading(r.rid) is None and r.runs() == []
    assert r.request(asset)["status"] == "waiting" and r.store.person_files(r.rid) == {}


@pytest.mark.parametrize("case", ["reading_off", "user_excluded", "out_of_scope"])
def test_reading_off_or_a_work_that_is_not_read_writes_no_request(research, case):
    r = research(reading="off" if case == "reading_off" else "auto")
    svid = r.work()
    if case == "user_excluded":
        r.lib.list_edit(svid, "excluded")
    elif case == "out_of_scope":
        r.ds.record(r.rid, svid, "runs_agree_out_of_scope")
    asset, outcome = r.attach(svid)
    assert r.request(asset) is None and r.runs() == []
    assert outcome == {"reading_off": "model_off", "user_excluded": "decision_stands",
                       "out_of_scope": "not_eligible"}[case]
    # Only a work the reading may take gets a code; reading off still names the file on its version.
    assert r.code(svid) == ("not_read_yet" if case == "reading_off" else None)


def test_a_run_in_the_group_order_that_reads_an_unread_file_marks_it_read(research):
    r = research(responder=silent)
    svid = r.work()
    asset, _ = r.attach(svid)
    r.drain()
    assert r.request(asset)["status"] == "unread"
    r.adapter.responder = valid_response
    # The next reading run a retrieval run leaves behind reads it in the group order, not at the front.
    run = r.store.create_run(r.rid, "fulltext_adjudication", adjudication.read_budget("standard"), "SYNTHETIC-after")
    r.work_through(run["id"])
    assert r.code(svid) == "all_parts_verified" and r.request(asset)["status"] == "read"
    assert r.plan(run["id"])["works"][0]["read_version"] == svid


# ---- decision 5: one helper opens the queue -------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_the_reading_waits_while_the_research_has_an_active_or_paused_run(research, status):
    r = research()
    other = r.store.create_run(r.rid, "discovery", {"max_model_calls": 1}, None)
    r.store.update_run(other["id"], status=status)
    svid = r.work()
    asset, _ = r.attach(svid)
    assert r.runs() == [] and r.request(asset)["status"] == "waiting"


@pytest.mark.parametrize("ending, opens", [("completed", True), ("failed", True), ("cancelled", True),
                                           ("paused", False)])
def test_the_reading_is_queued_when_the_run_before_it_ends_each_way(research, ending, opens):
    r = research()
    other = r.store.create_run(r.rid, "table_columns", {"max_model_calls": 1}, None)
    r.store.update_run(other["id"], status="running")
    svid = r.work()
    asset, _ = r.attach(svid)
    assert r.runs() == []
    r.store.update_run(other["id"], status=ending)
    r.flow.person_run_ended(other["id"])  # the worker, whichever way `execute` returned
    assert len(r.runs()) == (1 if opens else 0)
    assert r.request(asset)["status"] == "waiting"
    if opens:
        assert r.runs()[0]["idempotency_key"].endswith(":0")


@pytest.mark.parametrize("ending, why", [("failed", "run_failed"), ("cancelled", "run_cancelled"),
                                         ("completed", "no_decision")])
def test_the_write_that_ends_a_reading_run_before_its_plan_closes_its_files_in_the_same_transaction(
        research, monkeypatch, ending, why):
    r = research()
    svid, other = r.work(), r.work()
    asset, _ = r.attach(svid)
    [run] = r.runs()
    r.store.update_run(run["id"], event=f"run_{ending}", status=ending)  # the end itself, and no helper after it
    request = r.request(asset)
    assert (request["status"], request["unread_reason"], request["run_id"]) == ("unread", why, run["id"])
    # The two are one write: when closing the files fails, the run's end is not written either.
    other_asset, _ = r.attach(other)
    second = r.runs()[-1]
    assert second["status"] == "queued" and r.request(other_asset)["status"] == "waiting"

    def broken(*args, **kwargs):
        raise RuntimeError("SYNTHETIC closing failed")

    monkeypatch.setattr(person_reading, "close_run", broken)
    with pytest.raises(RuntimeError):
        r.store.update_run(second["id"], event=f"run_{ending}", status=ending)
    assert r.store.run(second["id"])["status"] == "queued" and r.request(other_asset)["status"] == "waiting"


def test_a_run_that_fails_before_its_plan_leaves_the_files_unread_and_opens_no_other(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    [run] = r.runs()
    r.store.update_run(run["id"], status="failed", pause_reason="internal_error")
    assert r.flow.person_run_ended(run["id"]) is None
    assert (r.request(asset)["status"], r.request(asset)["unread_reason"]) == ("unread", "run_failed")
    assert len(r.runs()) == 1


def test_a_reading_that_decides_nothing_leaves_the_file_unread_without_a_loop_and_retry_opens_a_new_run(research):
    r = research(responder=silent)
    svid = r.work()
    asset, _ = r.attach(svid)
    first = r.drain()
    assert len(first) == 1 and r.request(asset)["status"] == "unread"
    assert r.request(asset)["unread_reason"] == "no_decision" and r.code(svid) == "not_read_yet"
    assert r.flow.queue_person_reading(r.rid) is None and r.drain() == []  # nothing loops
    r.adapter.responder = valid_response
    person_reading.retry(r.store, r.rid, r.request(asset)["id"])
    run = r.flow.queue_person_reading(r.rid)
    assert run["idempotency_key"].endswith(":1") and r.request(asset)["attempt"] == 1
    r.drain()
    assert r.request(asset)["status"] == "read" and r.code(svid) == "all_parts_verified"
    with pytest.raises(person_reading.RetryRefused):
        person_reading.retry(r.store, r.rid, r.request(asset)["id"])


def test_a_discovery_end_reading_run_takes_the_waiting_files_and_no_second_run_opens(research):
    r = research()
    first, second = r.work(), r.work()
    r.file(first, r.pages(), origin="download")
    discovery = r.store.create_run(r.rid, "discovery", {"max_model_calls": 1}, None)
    r.store.update_run(discovery["id"], status="running")
    asset, _ = r.attach(second)
    assert r.runs() == []
    # The fetch ended inside discovery: the run completes and queues the reading of D98 in one write.
    r.store.update_run(discovery["id"], status="completed")
    r.flow._queue_fulltext_adjudication(r.store.run(discovery["id"]), r.store.scope(r.rid))
    r.flow.person_run_ended(discovery["id"])
    [after] = r.runs()
    assert after["idempotency_key"] == f"fulltext_adjudication:after:{discovery['id']}"
    r.drain()
    assert len(r.runs()) == 1 and r.request(asset)["status"] == "read"
    assert r.plan(after["id"])["works"][0]["head"] == second


def test_a_crash_after_the_attach_opens_the_reading_when_the_worker_starts(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid, queue_it=False)  # the process died before the queue was looked at
    assert r.runs() == []
    r.flow.queue_person_readings()
    assert len(r.runs()) == 1
    r.drain()
    assert r.request(asset)["status"] == "read"


def test_the_start_closes_what_a_run_that_ended_in_a_crash_left_planned(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    [run] = r.runs()
    r.store.update_run(run["id"], status="running")
    r.flow._adjudication_plan(r.store.run(run["id"]), r.store.scope(r.rid))
    r.store.update_run(run["id"], status="completed")  # ended, and the process died before closing its requests
    r.flow.queue_person_readings()
    assert r.request(asset)["status"] == "unread" and len(r.runs()) == 1


# ---- decision 6: the plan is bound to the file and its extraction -----------------------------------------------

@pytest.mark.parametrize("change", ["removed", "re_extracted"])
def test_a_file_removed_or_re_extracted_while_its_run_is_paused_is_not_decided(research, change):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    [run] = r.runs()
    r.store.update_run(run["id"], status="running")
    plan = r.flow._adjudication_plan(r.store.run(run["id"]), r.store.scope(r.rid))
    assert plan["works"][0]["asset_id"] == asset and plan["works"][0]["page_digest"]
    r.store.update_run(run["id"], status="paused", pause_reason="user_requested")
    if change == "removed":
        r.store.remove_asset(r.rid, svid, asset)
    else:
        r.reextract(svid, asset)
    r.store.update_run(run["id"], status="queued")
    r.work_through(run["id"])
    summary = r.store.existing_step(run["id"], "adjudication_summary")["output"]
    assert r.code(svid) == "not_read_yet" and summary["not_reached"] == 1 and summary["read"] == 0
    request = r.request(asset)
    assert (request["status"], request["unread_reason"]) == ("unread", "file_changed")
    assert not [c for c in r.adapter.calls if c["task_type"] == "fulltext_adjudication"]


def test_a_file_that_changes_while_its_calls_are_out_writes_no_decision(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)

    def change(si):
        if si["task_type"] == "fulltext_adjudication" and si["adjudication_target"]["run"] == 2:
            r.reextract(svid, asset)

    r.adapter.before = change
    r.drain()
    assert r.code(svid) == "not_read_yet" and r.request(asset)["unread_reason"] == "file_changed"
    summary = r.store.existing_step(r.runs()[0]["id"], "adjudication_summary")["output"]
    assert (summary["not_reached"], summary["not_settled"]) == (1, 0)


# ---- decision 7: the front of the reading order ------------------------------------------------------------------

def test_waiting_files_come_first_in_the_order_they_were_added_and_count_against_the_limit(research):
    r = research()
    ranked = [r.work() for _ in range(3)]
    for svid in ranked:
        r.file(svid, r.pages(), origin="download")
    r.lib.rank(ranked)
    late, early = r.work(), r.work()
    early_asset, _ = r.attach(early, queue_it=False)
    time.sleep(0.005)
    r.attach(late, queue_it=False)
    works = r.flow._fulltext_works(r.rid)
    plan = adjudication.read_plan(works, ranked, 3)
    assert plan == {"works": [early, late, ranked[0]], "not_reached": ranked[1:]}
    assert r.request(early_asset)["status"] == "waiting"


def test_ten_waiting_files_are_read_before_forty_unread_ones(research):
    r = research()
    unread = [r.work() for _ in range(40)]
    waiting = [r.work() for _ in range(10)]
    for svid in unread:
        asset, _ = r.attach(svid, queue_it=False)
        r.store.conn.execute("UPDATE person_pdf_requests SET status = 'unread', unread_reason = 'no_decision'"
                             " WHERE asset_id = ?", (asset,))
    time.sleep(0.005)
    for svid in waiting:
        r.attach(svid, queue_it=False)
    plan = adjudication.read_plan(r.flow._fulltext_works(r.rid), [], 10)
    assert plan["works"] == waiting and set(plan["not_reached"]) == set(unread)


# ---- decision 8: whose version the work and the answer read ------------------------------------------------------

def two_versions(r, doi="10.9999/synth.two", code="all_parts_verified"):
    """A work whose published record was read from its own file (`code`), and a preprint a person adds a file to."""
    published = r.lib.published(doi)
    preprint = r.lib.preprint(doi)
    r.ds.record(r.rid, published, CANDIDATE_CODE)
    r.file(published, r.pages(), origin="download")
    r.ds.record(r.rid, published, code)
    return published, preprint


def test_before_the_file_is_read_the_answer_reads_the_earlier_version_and_both_selectors_agree(research):
    r = research()
    published, preprint = two_versions(r, code="criterion_absent")
    r.attach(preprint, queue_it=False)
    assert r.store.answer_version(r.rid, published) == published
    assert r.store.answer_versions(r.rid)[published] == published
    assert r.outcome(published)["source_version_id"] == published  # the work keeps the result it had
    # The published record loses its file: the preprint's unread text still does not reach the answer.
    r.store.remove_asset(r.rid, published, r.flow._current_asset(published))
    assert r.store.answer_version(r.rid, published) == published == r.store.answer_versions(r.rid)[published]


def test_after_the_file_is_read_its_decision_is_the_work_s_and_the_other_version_keeps_its_own(research):
    r = research()
    published, preprint = two_versions(r, code="criterion_absent")
    asset, _ = r.attach(preprint)
    [run] = r.drain()
    # A fresh model decision on the other version did not keep the person's file out of the plan.
    assert [item["read_version"] for item in r.plan(run)["works"]] == [preprint]
    assert r.code(preprint) == "all_parts_verified" and r.code(published) == "criterion_absent"
    assert r.outcome(published)["source_version_id"] == preprint
    assert r.outcome(published)["outcome"] == "include" and r.lib.selection(published) == ("included", "code_rule")
    assert r.store.answer_version(r.rid, published) == preprint == r.store.answer_versions(r.rid)[published]
    # No `versions_disagree` row is opened for it.
    assert not [row for row in queue.queue_rows(r.store, r.rid)["rows"] if row["work_id"] == r.lib.work_of(published)]
    # Removing the read file, anywhere, drops the precedence and today's rule answers again: two versions at opposite
    # fresh decisions leave the work unresolved.
    r.store.remove_asset(r.rid, preprint, asset)
    assert r.outcome(published)["reason_code"] == "versions_disagree"
    assert r.store.answer_version(r.rid, published) == published == r.store.answer_versions(r.rid)[published]


def test_a_re_extracted_read_file_loses_its_precedence(research):
    r = research()
    published, preprint = two_versions(r, code="criterion_absent")
    asset, _ = r.attach(preprint)
    r.drain()
    r.reextract(preprint, asset)
    assert r.outcome(published)["reason_code"] == "versions_disagree"
    assert r.store.answer_version(r.rid, published) == published == r.store.answer_versions(r.rid)[published]


def test_a_work_without_a_person_s_file_reads_as_before(research):
    r = research()
    published, preprint = two_versions(r)
    r.file(preprint, r.pages(), origin="download")
    r.ds.record(r.rid, preprint, "criterion_absent")
    assert r.outcome(published)["reason_code"] == "versions_disagree"
    assert r.store.answer_version(r.rid, published) == published == r.store.answer_versions(r.rid)[published]
    assert r.store.person_files(r.rid) == {}


def included_work(r, pages=None, origin="download"):
    """A work the person included, with a file of `origin` in use (none when `pages` is empty)."""
    svid = r.work()
    if pages != []:
        r.file(svid, r.pages() if pages is None else pages, origin=origin)
    r.lib.list_edit(svid, "included")
    return svid


def test_an_included_work_whose_only_text_is_the_person_s_unread_file_gives_the_answer_none_of_it(research):
    r = research()
    lone, other = included_work(r, pages=[]), included_work(r)
    asset, _ = r.attach(lone, queue_it=False)
    assert r.request(asset)["status"] == "waiting" and r.lib.selection(lone)[0] == "included"
    assert r.store.answer_version(r.rid, lone) is None and r.store.answer_versions(r.rid)[lone] is None
    sent = r.answer_input()
    assert sent and {svid for svid, _ in sent} == {other}  # not its pages, not its abstract: nothing
    # Once the model read it under this criterion, the file is the work's text and reaches the answer.
    r.flow.queue_person_reading(r.rid)
    r.drain()
    assert r.request(asset)["status"] == "read"
    assert r.store.answer_version(r.rid, lone) == lone == r.store.answer_versions(r.rid)[lone]
    assert (lone, "pdf_page") in r.answer_input()


def test_a_work_whose_every_text_version_carries_an_unread_file_gives_an_abstract_only_version_or_nothing(research):
    r = research()
    control = included_work(r)
    both = [r.lib.published("10.9999/synth.both"), r.lib.preprint("10.9999/synth.both")]
    bare = [r.lib.published("10.9999/synth.bare"), r.lib.preprint("10.9999/synth.bare")]
    r.store._insert_passage(bare[0], None, "abstract", None, None, "provider", None, None,
                            "SYNTHETIC abstract of the published record, which has no PDF here.")
    for head in (both[0], bare[0]):
        r.ds.record(r.rid, head, CANDIDATE_CODE)
        r.lib.list_edit(head, "included")
    assets = [r.attach(svid, queue_it=False)[0] for svid in (*both, bare[1])]
    assert [r.request(asset)["status"] for asset in assets] == ["waiting"] * 3
    assert r.lib.head(both[1]) == both[0] and r.lib.head(bare[1]) == bare[0]
    # Every version with PDF text carries a file not read yet, and no version without one is left: nothing.
    assert r.store.answer_version(r.rid, both[0]) is None and r.store.answer_versions(r.rid)[both[0]] is None
    # The published record has no PDF text: it gives its abstract, and the preprint's unread pages stay out.
    assert r.store.answer_version(r.rid, bare[0]) == bare[0] == r.store.answer_versions(r.rid)[bare[0]]
    sent = r.answer_input()
    assert {svid for svid, _ in sent} == {control, bare[0]}
    assert {kind for svid, kind in sent if svid == bare[0]} == {"abstract"}


def test_with_reading_off_a_person_s_file_reaches_the_answer_as_before_slice_18b(research):
    """Nothing is read against the criterion for any work while reading is off: a person's file is then an upload
    as it was before slice 18b, and the answer may read it (judgement call 22)."""
    r = research(reading="off")
    lone = included_work(r, pages=[])
    asset, outcome = r.attach(lone)
    assert outcome == "model_off" and r.request(asset) is None and r.runs() == []
    assert r.store.answer_version(r.rid, lone) == lone == r.store.answer_versions(r.rid)[lone]
    assert (lone, "pdf_page") in r.answer_input()


def test_the_view_says_when_an_answer_reads_no_version_of_a_work_and_keeps_the_head_case(research):
    from deixis.workflow.views import research_view
    r = research()
    lone, own = included_work(r, pages=[]), included_work(r)
    published, preprint = r.lib.published("10.9999/synth.view"), r.lib.preprint("10.9999/synth.view")
    r.file(preprint, r.pages(), origin="download")
    r.attach(lone, queue_it=False)
    sources = {s["source_version_id"]: s for s in research_view(r.store, r.rid)["sources"]}
    # The only PDF text is the person's unread file: the answer reads nothing of the work, and says so.
    assert (sources[lone]["answer_reads_nothing"], sources[lone]["answer_reads_version_id"]) == (True, None)
    assert sources[lone]["has_pdf_text"] is True
    # The head read itself, and a head read through another version, are what they were.
    assert (sources[own]["answer_reads_nothing"], sources[own]["answer_reads_version_id"]) == (False, None)
    assert (sources[published]["answer_reads_nothing"], sources[published]["answer_reads_version_id"]) == (
        False, preprint)


def test_a_file_asked_under_an_earlier_question_reaches_no_answer_until_this_criterion_reads_it(research):
    r = research()
    lone, other = included_work(r, pages=[]), included_work(r)
    asset, _ = r.attach(lone, queue_it=False)
    r.lib.revise()
    assert r.lib.selection(lone)[0] == "included"
    # The request is stale: not asked again, not rewritten, and still not read under the question asked now.
    assert r.flow.queue_person_reading(r.rid) is None and r.runs() == []
    assert (r.request(asset)["status"], r.request(asset)["scope_revision"]) == ("waiting", 1)
    assert r.store.answer_version(r.rid, lone) is None and r.store.answer_versions(r.rid)[lone] is None
    assert {svid for svid, _ in r.answer_input()} == {other}
    # A reading under the revised question's criterion reads that file, in the group order; the answer may then.
    r.store.freeze_protocol(r.rid, 2, body(r.lib.field, question=r.store.scope(r.rid)["question"]))
    for svid in (lone, other):
        r.ds.record(r.rid, svid, CANDIDATE_CODE)
    run = r.store.create_run(r.rid, "fulltext_adjudication", adjudication.read_budget("standard"), "SYNTHETIC-revised")
    r.work_through(run["id"])
    assert lone in [item["read_version"] for item in r.plan(run["id"])["works"]]
    assert r.code(lone) == "all_parts_verified" and r.request(asset)["status"] == "waiting"
    assert r.store.answer_version(r.rid, lone) == lone == r.store.answer_versions(r.rid)[lone]
    assert (lone, "pdf_page") in r.answer_input()


# ---- decision 9: the "Your files" section --------------------------------------------------------------------------

def states(r, reading_on=True):
    return {row["source_version_id"]: row for row in person_reading.files_view(r.store, r.rid, reading_on)["rows"]}


def test_your_files_says_what_became_of_each_file_from_what_is_stored(research):
    r = research(responder=absent)
    waiting, excluded, blank = r.work(), r.work(), r.work()
    r.attach(waiting, queue_it=False)
    r.lib.list_edit(excluded, "excluded")
    r.attach(excluded, queue_it=False)
    r.attach(blank, pages=[""], queue_it=False)
    rows = states(r)
    assert rows[waiting]["state"] == "waiting" and not rows[waiting]["after_run"]
    assert rows[excluded]["state"] == "decision_stands" and rows[excluded]["decided_code"] == "selection_excluded"
    assert blank not in rows  # a file with no text is on the waiting list instead
    r.flow.queue_person_reading(r.rid)
    r.drain()
    rows = states(r)
    assert rows[waiting]["state"] == "criterion_not_met" and rows[waiting]["quotes"] == []


def test_your_files_shows_the_verified_quotes_of_an_included_file_and_the_queue_for_an_unsettled_one(research):
    r = research()
    svid = r.work()
    r.attach(svid)
    r.drain()
    row = states(r)[svid]
    assert row["state"] == "included"
    assert {(q["quote"], q["page"]) for q in row["quotes"]} == {(r.lib.field["page"][:60], 1)}
    r.ds.record(r.rid, svid, "part_without_evidence")
    assert states(r)[svid]["state"] == "your_decision"


def test_your_files_shows_a_file_read_now_an_unread_one_and_one_the_model_does_not_read(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    seen = []
    r.adapter.before = lambda si: seen.append(states(r)[svid]["state"]) if si["task_type"] == "fulltext_adjudication" else None
    [run] = r.runs()
    r.store.update_run(run["id"], status="running")
    r.flow._adjudication_plan(r.store.run(run["id"]), r.store.scope(r.rid))
    r.store.update_run(run["id"], status="cancelled", pause_reason="user_cancelled")
    r.flow.person_run_ended(run["id"])
    row = states(r)[svid]
    assert (row["state"], row["unread_reason"], row["request_id"]) == ("unread", "run_cancelled", r.request(asset)["id"])
    person_reading.retry(r.store, r.rid, row["request_id"])
    r.flow.queue_person_reading(r.rid)
    r.drain()
    assert "reading" in seen and states(r)[svid]["state"] == "included"


def test_your_files_says_the_model_does_not_read_a_file_while_reading_is_off(research):
    r = research(reading="off")
    svid = r.work()
    asset, outcome = r.attach(svid)
    assert outcome == "model_off" and r.request(asset) is None
    assert states(r, reading_on=False)[svid]["state"] == "model_off"


def test_your_files_shows_no_verified_quote_for_a_file_whose_pages_changed_since_they_were_read(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid)
    r.drain()
    assert states(r)[svid]["state"] == "included" and states(r)[svid]["quotes"]
    r.reextract(svid, asset)
    row = states(r)[svid]
    assert (row["state"], row["quotes"], row["request_id"]) == ("changed", [], r.request(asset)["id"])
    # "Read again" asks for this file as it is now; once read, it is included from its new pages.
    person_reading.retry(r.store, r.rid, row["request_id"])
    assert r.request(asset)["status"] == "waiting" and r.request(asset)["attempt"] == 1
    r.flow.queue_person_reading(r.rid)
    r.drain()
    row = states(r)[svid]
    assert row["state"] == "included" and row["quotes"] and r.request(asset)["status"] == "read"
    with pytest.raises(person_reading.RetryRefused):
        person_reading.retry(r.store, r.rid, row["request_id"])


def test_the_view_offers_the_paused_run_while_a_file_waits(research):
    r = research()
    paused = r.store.create_run(r.rid, "discovery", {"max_model_calls": 1}, None)
    r.store.update_run(paused["id"], status="paused", pause_reason="user_requested")
    svid = r.work()
    r.attach(svid)
    view = person_reading.files_view(r.store, r.rid, True)
    assert view["paused_run"]["id"] == paused["id"] and view["rows"][0]["state"] == "waiting"
    assert view["rows"][0]["after_run"] is False


def test_the_confirmation_says_per_version_what_a_file_leads_to(research):
    r = research()
    published = r.lib.published("10.9999/synth.preview")
    preprint = r.lib.preprint("10.9999/synth.preview")
    r.ds.record(r.rid, published, CANDIDATE_CODE)
    r.ds.record(r.rid, published, "human_pdf_wrong")
    decided = r.work()
    r.ds.record(r.rid, decided, "human_include")
    outcomes = r.flow.attach_outcomes(r.rid, [r.lib.work_of(published), r.lib.work_of(decided)])
    # The version the person called wrong keeps their answer; a file on the other version is read (decision 3).
    assert outcomes[r.lib.work_of(published)] == {published: "decision_stands", preprint: "requested"}
    assert outcomes[r.lib.work_of(decided)] == {decided: "decision_stands"}
    assert r.store.conn.execute("SELECT COUNT(*) FROM person_pdf_requests").fetchone()[0] == 0  # nothing written

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
from deixis.api.app import create_app
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_abstract_flow import client_of
from test_adjudication import decision
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
        self.store.conn.execute("UPDATE scope_revisions SET source_scope = 'attached' WHERE research_id = ?", (self.rid,))
        self.adapter = FakeAdapter(responder)
        self.flow = ResearchFlow(FlowDeps(
            Settings(data_dir=tmp_path / "data", port=8765, fulltext_adjudication=reading),
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

    def reextract(self, svid, asset, suffix=None):
        """The same file extracted again with different text, as a new extraction writes it (D45); with `suffix`, as an
        equation pass laid on the current extraction writes it."""
        version = db.new_id("ext") if suffix is None else self.store.conn.execute(
            "SELECT extraction_version FROM source_assets WHERE id = ?", (asset,)).fetchone()[0] + suffix
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


# ---- decision 3: the person's decisions ----------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["human_include", "human_criterion_not_met"])
def test_any_other_decision_of_the_person_stands_and_the_file_is_only_added(research, code):
    r = research()
    svid = r.work()
    r.ds.record(r.rid, svid, code)
    asset, outcome = r.attach(svid)
    assert outcome == "decision_stands" and r.code(svid) == code
    assert r.request(asset) is None and r.runs() == []
    assert r.store.has_asset(svid)


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


@pytest.mark.parametrize("case", ["user_excluded"])
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


# ---- decision 5: one helper opens the queue -------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["running", "paused"])
def test_the_reading_waits_while_the_research_has_an_active_or_paused_run(research, status):
    r = research()
    other = r.store.create_run(r.rid, "discovery", {"max_model_calls": 1, "inspection": {"policy": "small_batch_fused_v1"}}, None)
    r.store.update_run(other["id"], status=status)
    svid = r.work()
    asset, _ = r.attach(svid)
    assert r.runs() == [] and r.request(asset)["status"] == "waiting"


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


def test_a_crash_after_the_attach_opens_the_reading_when_the_worker_starts(research):
    r = research()
    svid = r.work()
    asset, _ = r.attach(svid, queue_it=False)  # the process died before the queue was looked at
    assert r.runs() == []
    r.flow.queue_person_readings()
    assert len(r.runs()) == 1
    r.drain()
    assert r.request(asset)["status"] == "read"


# ---- decision 8: whose version the work and the answer read ------------------------------------------------------

def two_versions(r, doi="10.9999/synth.two", code="all_parts_verified"):
    """A work whose published record was read from its own file (`code`), and a preprint a person adds a file to."""
    published = r.lib.published(doi)
    preprint = r.lib.preprint(doi)
    r.ds.record(r.rid, published, CANDIDATE_CODE)
    r.file(published, r.pages(), origin="download")
    r.ds.record(r.rid, published, code)
    return published, preprint


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


# ---- UI parity S13: the Sources list's "Model proposal" reads the same merge rules, without the person's decision ----

def screening(r, svid):
    from deixis.workflow import flow_counts
    return flow_counts.machine_screening(queue.context(r.store, r.rid), r.lib.work_of(svid))


def test_the_model_proposal_keeps_two_versions_disagreeing_and_leaves_the_person_s_choice_out(research):
    r = research()
    published, preprint = two_versions(r)  # the head record reads include from its own file
    r.file(preprint, r.pages(), origin="download")
    r.ds.record(r.rid, preprint, "criterion_absent")
    shown = screening(r, published)
    assert (shown["stage"], shown["outcome"], shown["reason_code"]) == ("fulltext", "unresolved", "versions_disagree")
    # A person's include answers the work and closes the head record's code decision; the proposal column never shows
    # the person's include, only the machine decision still open on the other version.
    r.ds.record(r.rid, published, "human_include")
    assert r.outcome(published)["decided_by"] == "human"
    shown = screening(r, published)
    assert (shown["outcome"], shown["reason_code"], shown["source_version_id"]) == ("criterion_not_met", "criterion_absent", preprint)


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


# ---- a person's file through the API, with a worker that does not run (was test_person_reading_flow.py) ----

def request_of(store, asset_id):
    row = store.conn.execute("SELECT * FROM person_pdf_requests WHERE asset_id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


@pytest.fixture
def still(tmp_path, monkeypatch):
    """An app whose worker never runs, with an `sw` research built at its store and a flow to write through."""
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")

    def make(reading="auto"):
        app = create_app(Settings(data_dir=tmp_path / "sw" / "data", port=8765,
                                  fulltext_adjudication=reading),
                         adapters={"fake": FakeAdapter(valid_response)}, start_worker=False,
                         extra_hosts=("testserver",), trusted_clients=("testclient",))
        client = client_of(app)
        lib = Lib(app.state.store)
        made.append(client)
        return app, client, lib

    made = []
    yield make
    for client in made:
        client.__exit__(None, None, None)


def candidate(lib):
    svid = lib.work()
    lib.ds.record(lib.rid, svid, CANDIDATE_CODE)
    return svid


def runs(store, rid, kind="fulltext_adjudication"):
    return [dict(r) for r in store.conn.execute("SELECT id, status, idempotency_key FROM runs WHERE research_id = ?"
                                                " AND kind = ? ORDER BY created_at, rowid", (rid, kind))]


def upload(client, rid, svid, pages=("SYNTHETIC the release model is a Poisson process with a fixed rate per slot.",)):
    return client.post(f"/api/researches/{rid}/sources/{svid}/uploads",
                       files={"file": ("mine.pdf", make_pdf(list(pages)), "application/pdf")})


def test_a_source_row_upload_in_sw_writes_the_same_code_request_and_run(still):
    app, client, lib = still()
    store = app.state.store
    svid = candidate(lib)
    response = upload(client, lib.rid, svid)
    decision = DecisionStore(store).current(lib.rid, svid, "fulltext")
    asset = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                               (svid,)).fetchone()[0]
    assert response.status_code == 201
    assert (decision["reason_code"], decision["note"]) == ("not_read_yet", f"person_pdf:{asset}")
    assert request_of(store, asset)["status"] == "waiting"
    [run] = runs(store, lib.rid)
    assert run["status"] == "queued" and ":person:" in run["idempotency_key"]


def test_a_source_row_upload_to_an_excluded_work_writes_nothing(still):
    app, client, lib = still()
    store = app.state.store
    svid = candidate(lib)
    lib.list_edit(svid, "excluded")
    assert upload(client, lib.rid, svid).status_code == 201
    assert DecisionStore(store).current(lib.rid, svid, "fulltext") is None
    assert store.conn.execute("SELECT COUNT(*) FROM person_pdf_requests").fetchone()[0] == 0
    assert runs(store, lib.rid) == []

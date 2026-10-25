"""The audit sample of an `sw` research and its answers through the audit branch (slice 20, decisions 5–7).

Records, criteria and readings are SYNTHETIC and from two fields (diffusion channel scheduling, greenhouse irrigation),
written the way the reading run and the queue write them, without a model or a request. No stored library has an
answered audit row, so everything about an audit answer is covered here only. Passing shows which works are drawn,
what an answer and an undo write and which path may take a decision back; it says nothing about whether the sample
finds a wrong decision, and no count here is a rate.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from deixis.storage import db
from deixis.workflow.screen import audit, queue
from deixis.workflow.search import probes
from deixis.workflow.run import views
from deixis.workflow.run.store import Store
from test_queue import Lib, queued
from test_queue_api import quiet_app


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def read_work(lib, reason="all_parts_verified"):
    """A work two agreeing runs read and decided, with its page text and proposals."""
    svid = lib.work()
    lib.text(svid, [lib.field["page"], lib.field["cue"]])
    labels = None if reason == "all_parts_verified" else {name: ("absent", "absent") for name in lib.parts}
    lib.read(svid, reason, labels=labels)
    return svid


def coded(lib, reason):
    svid = lib.work()
    lib.ds.record(lib.rid, svid, reason)
    lib.ds.derive_selection(lib.rid, lib.work_of(svid))
    return svid


def state_of(lib):
    return audit.AuditState(queue._Context(lib.store, lib.rid))


def view_of(lib):
    return audit.audit_view(lib.store, lib.rid)


def row_of(lib, svid):
    view = view_of(lib)
    return next(row for stratum in audit.FULLTEXT_STRATA for row in view["fulltext"][stratum]["rows"]
                if row["source_version_id"] == svid)


def decide(lib, svid, answer="criterion_not_met", token=None):
    return queue.audit_decide(lib.store, lib.rid, svid, answer, None, token or row_of(lib, svid)["audit_token"])


def all_rows(store):
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


# ---- decision 5: strata and the stateless sample -----------------------------------------------------------------


@pytest.mark.parametrize("field", ["channels"])
def test_the_four_strata_hold_the_machine_decisions_the_queue_never_shows(store, field):
    lib = Lib(store, field)
    f1, f2 = read_work(lib), read_work(lib, "criterion_absent")
    a1, a2 = coded(lib, "runs_agree_out_of_scope"), coded(lib, "notice_record")
    queued(lib)
    coded(lib, "runs_agree_candidate")
    person = read_work(lib)
    lib.list_edit(person, "excluded")  # a person's probe is not the machine's to audit
    state = state_of(lib)
    work = lib.work_of
    assert {name: set(members) for name, members in state.members.items()} == {
        "F1": {work(f1)}, "F2": {work(f2)}, "A1": {work(a1)}, "A2": {work(a2)}}
    view = view_of(lib)
    assert [row["kind"] for row in view["fulltext"]["F1"]["rows"]] == ["audit_include"]
    assert [row["kind"] for row in view["fulltext"]["F2"]["rows"]] == ["audit_not_met"]
    assert view["fulltext"]["F1"]["rows"][0]["question"] == "Does this work meet the criterion?"
    # The abstract strata are for viewing and manual selection only: no audit token, no answer.
    (a_row,) = view["abstract"]["A1"]["rows"]
    assert "audit_token" not in a_row and a_row["selection"]["state"] == "excluded"
    # Audit rows are not queue rows.
    assert views.research_view(store, lib.rid)["counts"]["queue"] == 1


def digest(rid, revision, criterion, stratum, work_id):
    return hashlib.sha256(f"{rid}|{revision}|{criterion or 'none'}|{stratum}|{work_id}".encode()).hexdigest()


# ---- decision 6: the audit branch --------------------------------------------------------------------------------


def test_the_detail_shows_both_runs_quotes_and_pages_and_writes_nothing(store):
    lib = Lib(store, "irrigation")
    svid = read_work(lib)
    before, changes = all_rows(store), store.conn.total_changes
    found = audit.audit_detail(store, lib.rid, svid)
    assert all_rows(store) == before and store.conn.total_changes == changes
    assert found["row"]["source_version_id"] == svid
    runs = found["detail"]["runs"]
    assert [run["run_no"] for run in runs] == [1, 2]
    assert all(part["quote"] and part["page"] == 1 and part["quote_verified"] for run in runs for part in run["parts"])
    assert runs[0]["shown_pages"] == [1]


@pytest.mark.parametrize("answer,code,selection", [
    ("include", "human_include", ("included", "user")),
])
def test_each_answer_is_written_with_d96s_rules_and_its_origin(store, answer, code, selection):
    lib = Lib(store)
    svid = read_work(lib)
    result = decide(lib, svid, answer)
    current = lib.ds.current(lib.rid, svid, "fulltext")
    assert (current["reason_code"], current["decided_by"]) == (code, "human")
    assert lib.selection(svid) == selection
    assert queue.decision_origin(store, lib.rid, current["id"]) == "audit"
    assert result["row"]["answered"]["reason_code"] == code and result["undo_token"]
    # A decided work is not sent to a model again (D96).
    assert lib.work_of(svid) in lib.ds.human_decided_works(lib.rid)
    if answer == "include":
        found = probes.probe_set(queue._Context(store, lib.rid))
        assert lib.work_of(svid) in found["verified"] and lib.work_of(svid) not in found["included"]


def test_undo_brings_back_the_machine_decision_and_the_selection(store):
    lib = Lib(store)
    svid = read_work(lib)
    machine = lib.ds.current(lib.rid, svid, "fulltext")
    result = decide(lib, svid, "criterion_not_met")
    assert lib.selection(svid) == ("excluded", "user")
    undone = queue.audit_undo(store, lib.rid, svid, result["undo_token"])
    current = lib.ds.current(lib.rid, svid, "fulltext")
    assert current["reason_code"] == machine["reason_code"] and current["decided_by"] == "model_agreement"
    assert lib.selection(svid) == ("included", "code_rule")
    assert undone["row"]["answered"] is None


# ---- the origin, read from the event tied to the decision id, on both undo paths ---------------------------------


def events_of(store, decision_id):
    return [json.loads(row[0]) for row in store.conn.execute(
        "SELECT payload_json FROM events WHERE type = 'stage_decision_recorded'"
        " AND json_extract(payload_json, '$.decision_id') = ?", (decision_id,))]


def test_the_endpoints_refuse_wrong_answers_and_mutations_need_the_csrf_header(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Lib(store)
        svid = read_work(lib)
        a1 = coded(lib, "runs_agree_out_of_scope")
        headers = {"x-deixis-csrf": ""}
        no_csrf = client.post(f"/api/researches/{lib.rid}/audit/{svid}/decision", headers=headers,
                              json={"decision": "include", "note": None, "audit_token": "x.y"})
        abstract = client.post(f"/api/researches/{lib.rid}/audit/{a1}/decision",
                               json={"decision": "include", "note": None, "audit_token": "x.y"})
        confirmed = client.post(f"/api/researches/{lib.rid}/audit/{svid}/decision",
                                json={"decision": "pdf_confirmed", "note": None, "audit_token": "x.y"})
    finally:
        client.__exit__(None, None, None)
    assert no_csrf.status_code == 403
    assert abstract.status_code == 422
    assert confirmed.status_code == 422  # `pdf_confirmed` is not an audit answer

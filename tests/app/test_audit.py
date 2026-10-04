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
from deixis.workflow import audit, probes, queue, views
from deixis.workflow.queue import QueueConflict, QueueUnavailable
from deixis.workflow.store import Store
from test_queue import Lib, queued
from test_queue_api import answer as queue_answer, queue_of, quiet_app


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


@pytest.mark.parametrize("field", ["channels", "irrigation"])
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


def test_the_sample_is_the_smallest_digests_and_does_not_depend_on_row_order(store):
    lib = Lib(store)
    works = [lib.work_of(read_work(lib)) for _ in range(6)]
    first = state_of(lib)
    revision, criterion = first.ctx.facts["stale_key"]
    assert first.digest("F1", works[0]) == digest(lib.rid, revision, criterion, "F1_include_by_agreement", works[0])
    assert first.samples["F1"] == sorted(
        works, key=lambda w: (digest(lib.rid, revision, criterion, "F1_include_by_agreement", w), w))[:3]
    assert state_of(lib).samples == first.samples
    # The same state read with its heads and decisions in reverse order draws the same sample.
    ctx = queue._Context(store, lib.rid)
    ctx.facts["heads"] = dict(reversed(list(ctx.facts["heads"].items())))
    ctx.facts["decisions"] = dict(reversed(list(ctx.facts["decisions"].items())))
    assert audit.AuditState(ctx).samples == first.samples


def test_a_new_criterion_draws_a_new_sample(store):
    lib = Lib(store, "irrigation")
    works = [lib.work_of(read_work(lib)) for _ in range(8)]
    revision, _ = state_of(lib).ctx.facts["stale_key"]
    # The same members read under another criterion digest (a real revision would also make their decisions
    # stale, which empties the strata; the key is swapped after the members are read to isolate the draw).
    state = state_of(lib)
    state.ctx.facts["stale_key"] = (revision, "another-criterion")
    redrawn = state._draw("F1")
    assert redrawn == sorted(works, key=lambda w: (digest(lib.rid, revision, "another-criterion", "F1_include_by_agreement", w), w))[:3]


def test_an_answered_work_stays_in_its_stratum_and_leaves_the_sample_only_for_a_smaller_digest(store):
    lib = Lib(store)
    svids = [read_work(lib) for _ in range(3)]
    target = svids[0]
    decide(lib, target, "criterion_not_met")
    state = state_of(lib)
    assert lib.work_of(target) in state.members["F1"] and lib.work_of(target) in state.samples["F1"]
    view = view_of(lib)
    assert view["fulltext"]["F1"]["answered"] == 1 and view["fulltext"]["F1"]["differs"] == 1
    assert [e["in_sample"] for e in view["earlier"]] == [True]
    # Later readings put works with smaller digests in the stratum until the answered one drops out.
    for _ in range(200):
        if lib.work_of(target) not in state_of(lib).samples["F1"]:
            break
        read_work(lib)
    view = view_of(lib)
    assert lib.work_of(target) not in [row["work_id"] for row in view["fulltext"]["F1"]["rows"]]
    (earlier,) = view["earlier"]
    assert (earlier["work_id"], earlier["in_sample"], earlier["differs"]) == (lib.work_of(target), False, True)
    assert earlier["stratum"] == "F1" and view["earlier_counts"]["F1"] == {"answers": 1, "differs": 1}
    assert view["fulltext"]["F1"]["answered"] == 0
    # It still counts in the override count, by the audit path.
    assert views.research_view(store, lib.rid)["counts"]["overrides"]["by_path"]["audit"]["overruled"] == 1


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
    ("criterion_not_met", "human_criterion_not_met", ("excluded", "user")),
    ("not_sure", "human_not_sure", ("pending", "code_rule")),
    ("pdf_wrong", "human_pdf_wrong", ("pending", "code_rule")),
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


def test_each_check_inside_the_write_refuses_on_its_own_and_writes_nothing(store):
    lib = Lib(store, "irrigation")
    out_of_sample, changed, retokened = read_work(lib), read_work(lib), read_work(lib)
    tokens = {svid: row_of(lib, svid)["audit_token"] for svid in (out_of_sample, changed, retokened)}
    # (i) The work left the sample: the person set it from the list, so it is a probe and no longer the machine's.
    lib.list_edit(out_of_sample, "included")
    # (ii) The version's decision changed: a new reading wrote another decision.
    lib.ds.record(lib.rid, changed, "criterion_absent")
    lib.ds.derive_selection(lib.rid, lib.work_of(changed))
    # (iii) Only the token moved: a new PDF file for the version.
    lib.text(retokened, [lib.field["page"]])
    before = all_rows(store)
    for svid, message in ((out_of_sample, "no longer in the audit sample"), (changed, "decision on this record changed"),
                          (retokened, "changed since it was shown")):
        with pytest.raises(QueueConflict) as refused:
            queue.audit_decide(store, lib.rid, svid, "include", None, tokens[svid])
        assert refused.value.reason == "row_changed" and message in str(refused.value)
        assert all_rows(store) == before


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


def test_undo_refuses_an_audit_answer_whose_earlier_decision_is_not_an_f_stratum_code(store):
    lib = Lib(store, "irrigation")
    svid = queued(lib)
    ctx = queue._Context(store, lib.rid)
    with db.transaction(store.conn):
        queue._write_answer(ctx, svid, {"current": lib.ds.current(lib.rid, svid, "fulltext"), "head": lib.head(svid)},
                            "human_include", None, via="audit")
    before = all_rows(store)
    with pytest.raises(QueueConflict) as refused:
        queue.audit_undo(store, lib.rid, svid, "x.y")
    assert refused.value.reason == "row_changed" and all_rows(store) == before


def test_an_open_queue_row_is_not_answered_through_the_audit_branch_nor_an_audit_row_through_the_queue(store):
    lib = Lib(store)
    open_row = queued(lib)
    f1 = read_work(lib)
    with pytest.raises(QueueConflict):
        queue.audit_decide(store, lib.rid, open_row, "include", None, "x.y")
    with pytest.raises(QueueConflict):
        queue.decide(store, lib.rid, f1, "include", None, row_of(lib, f1)["audit_token"])


def test_an_abstract_stratum_work_is_refused_by_the_answer_endpoint(store):
    lib = Lib(store, "irrigation")
    a1 = coded(lib, "runs_agree_out_of_scope")
    with pytest.raises(QueueUnavailable):
        queue.audit_decide(store, lib.rid, a1, "include", None, "x.y")


def test_a_legacy_research_has_no_audit(store):
    lib = Lib(store, workflow="legacy")
    svid = lib.work()
    with pytest.raises(QueueUnavailable):
        audit.audit_view(store, lib.rid)
    with pytest.raises(QueueUnavailable):
        queue.audit_decide(store, lib.rid, svid, "include", None, "x.y")


# ---- the origin, read from the event tied to the decision id, on both undo paths ---------------------------------


def events_of(store, decision_id):
    return [json.loads(row[0]) for row in store.conn.execute(
        "SELECT payload_json FROM events WHERE type = 'stage_decision_recorded'"
        " AND json_extract(payload_json, '$.decision_id') = ?", (decision_id,))]


def test_an_audit_answer_is_out_of_the_queues_decided_list_and_the_queue_undo_refuses_it(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Lib(store)
        svid = read_work(lib)
        audited = client.get(f"/api/researches/{lib.rid}/audit").json()
        row = audited["fulltext"]["F1"]["rows"][0]
        detail = client.get(f"/api/researches/{lib.rid}/audit/{svid}")
        decided = client.post(f"/api/researches/{lib.rid}/audit/{svid}/decision",
                              json={"decision": "criterion_not_met", "note": None, "audit_token": row["audit_token"]})
        listed = queue_of(client, lib.rid)
        token = client.get(f"/api/researches/{lib.rid}/queue/{svid}").json()["undo_token"]
        before = all_rows(store)
        refused = client.post(f"/api/researches/{lib.rid}/queue/{svid}/undo", json={"row_token": token})
        after = all_rows(store)
        undone = client.post(f"/api/researches/{lib.rid}/audit/{svid}/undo",
                             json={"audit_token": decided.json()["undo_token"]})
    finally:
        client.__exit__(None, None, None)
    assert detail.status_code == 200 and detail.json()["detail"]["runs"]
    assert decided.status_code == 200
    assert listed["decided"] == [] and listed["counts"]["decided"] == {} and listed["counts"]["open"] == 0
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "audit_decision"
    assert after == before
    assert undone.status_code == 200 and undone.json()["row"]["answered"] is None


def test_a_queue_answer_is_refused_by_the_audit_undo_and_still_undone_by_the_queue(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Lib(store, "irrigation")
        svid = queued(lib)
        row = queue_of(client, lib.rid)["rows"][0]
        decided = queue_answer(client, lib.rid, row, "include").json()
        (entry,) = queue_of(client, lib.rid)["decided"]
        before = all_rows(store)
        refused = client.post(f"/api/researches/{lib.rid}/audit/{svid}/undo", json={"audit_token": "x.y"})
        after = all_rows(store)
        undone = client.post(f"/api/researches/{lib.rid}/queue/{svid}/undo", json={"row_token": decided["undo_token"]})
    finally:
        client.__exit__(None, None, None)
    assert entry["source_version_id"] == svid
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "not_an_audit_decision"
    assert after == before
    assert undone.status_code == 200 and undone.json()["row"] is not None


def test_a_d96_event_without_via_stays_d96s_and_a_missing_mixed_or_other_via_is_unknown_on_both_paths(store):
    lib = Lib(store)
    plain = queued(lib)
    result = queue.decide(store, lib.rid, plain, "include", None, lib.row(plain)["row_token"])
    decision = lib.ds.current(lib.rid, plain, "fulltext")
    assert "via" not in events_of(store, decision["id"])[0]
    assert queue.decision_origin(store, lib.rid, decision["id"]) == "queue"
    assert [e["source_version_id"] for e in lib.rows()["decided"]] == [plain]

    cases = {}
    for case in ("missing", "mixed", "other", "null"):
        svid = queued(lib)
        queue.decide(store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
        current = lib.ds.current(lib.rid, svid, "fulltext")
        if case == "missing":
            store.conn.execute("DELETE FROM events WHERE type = 'stage_decision_recorded'"
                               " AND json_extract(payload_json, '$.decision_id') = ?", (current["id"],))
        else:
            payload = {"source_version_id": svid, "decision_id": current["id"], "reason_code": "human_include",
                       "decided_by": "human", "head": lib.head(svid)}
            if case == "mixed":
                payload["via"] = "audit"
            elif case == "other":
                payload["via"] = "chat"
            else:
                payload["via"] = None
                store.conn.execute("DELETE FROM events WHERE type = 'stage_decision_recorded'"
                                   " AND json_extract(payload_json, '$.decision_id') = ?", (current["id"],))
            store._event(lib.rid, "stage_decision_recorded", payload)
        cases[case] = svid
    for case, svid in cases.items():
        decision_id = lib.ds.current(lib.rid, svid, "fulltext")["id"]
        assert queue.decision_origin(store, lib.rid, decision_id) == "unknown", case
        token = queue.row_detail(store, lib.rid, svid)["undo_token"]
        before = all_rows(store)
        for attempt in (lambda: queue.undo(store, lib.rid, svid, token), lambda: queue.audit_undo(store, lib.rid, svid, "x.y")):
            with pytest.raises(QueueConflict) as refused:
                attempt()
            assert refused.value.reason == "origin_unknown", case
            assert all_rows(store) == before
    # The plain D96 decision is taken back by D96's undo as before.
    queue.undo(store, lib.rid, plain, result["undo_token"])
    assert lib.ds.current(lib.rid, plain, "fulltext")["decided_by"] != "human"


def test_the_endpoints_keep_to_the_search_workflow_and_mutations_need_the_csrf_header(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        legacy = Lib(store, workflow="legacy")
        refused = client.get(f"/api/researches/{legacy.rid}/audit")
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
    assert refused.status_code == 422
    assert no_csrf.status_code == 403
    assert abstract.status_code == 422
    assert confirmed.status_code == 422  # `pdf_confirmed` is not an audit answer

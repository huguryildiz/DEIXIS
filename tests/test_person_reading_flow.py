"""A person's file and its reading through the API (slice 18b).

Two kinds of case. Through a real `sw` research with the worker running (discovery with the fetch inside it, then the
reading of D98): works with no open PDF wait, the person confirms a file, and the reading run reads it first. And
through an app whose worker does not run, so the runs the API queues, pauses and cancels can be looked at before any
of them executes. Records, titles and files are SYNTHETIC; every transport is mocked and the model is scripted.
Passing shows the workflow; it says nothing about a model reading a publisher's file.
"""

import time

import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_abstract_flow import client_of, records_of
from test_adjudication_flow import app_for, discover
from test_fulltext_flow import Fetcher, Transport, ok, work
from test_person_reading import CANDIDATE_CODE, silent
from test_queue import Lib
from test_waiting_flow import confirm, match, named

SETTLED = ("completed", "failed", "paused", "cancelled")


def settle(client, rid, timeout=30):
    """Wait until no run of the research is queued or running, and return the research view."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        if all(run["status"] in SETTLED for run in view["runs"]):
            return view
        time.sleep(0.05)
    raise AssertionError("the runs did not settle")


def reading_research(tmp_path, monkeypatch, responder=valid_response):
    """Four SYNTHETIC works, W1 with an open PDF and W2–W4 with none, read with the reading on."""
    adapter = FakeAdapter(responder)
    works = [work(1, pdf_url="https://example.org/w1.pdf"), work(2), work(3), work(4)]
    app = app_for(tmp_path, monkeypatch, Transport(works), Fetcher({"https://example.org/w1.pdf": ok()}),
                  adapter=adapter)
    client = client_of(app)
    rid, _, _, run = discover(client)
    assert run["status"] == "completed", run
    settle(client, rid)
    return app, client, rid, adapter


def request_of(store, asset_id):
    row = store.conn.execute("SELECT * FROM person_pdf_requests WHERE asset_id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def test_a_confirmed_file_is_read_first_and_its_work_is_included(tmp_path, monkeypatch):
    app, client, rid, adapter = reading_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        data = named("10.1/oa.2")
        found = match(client, rid, ("doi.pdf", data))["matches"][0]
        assert [(v["after_attach"], v["person_decision"]) for v in found["work"]["versions"]] == [("requested", None)]
        response = confirm(client, rid, data, found, records["W2"])
        attached = response.json()["attached"]
        view = settle(client, rid)
        files = client.get(f"/api/researches/{rid}/waiting").json()["files"]
        request = request_of(store, attached["asset_id"])
        person_runs = [r for r in view["runs"] if "person" in (store.run(r["id"])["idempotency_key"] or "")]
        code = DecisionStore(store).current(rid, records["W2"], "fulltext")["reason_code"]
        selection = next(s for s in view["sources"] if s["source_version_id"] == records["W2"])["selection"]
    finally:
        client.__exit__(None, None, None)
    assert response.status_code == 201 and attached["reading"] == "requested"
    assert len(person_runs) == 1 and person_runs[0]["status"] == "completed"
    assert request["status"] == "read" and request["run_id"] == person_runs[0]["id"]
    assert code == "all_parts_verified" and selection["state"] == "included"
    [row] = [row for row in files["rows"] if row["source_version_id"] == records["W2"]]
    assert row["state"] == "included" and row["quotes"] and all(q["page"] == 1 for q in row["quotes"])
    assert files["reading_on"] is True and files["paused_run"] is None


def test_a_file_the_model_could_not_read_is_unread_and_read_again_on_the_person_s_retry(tmp_path, monkeypatch):
    app, client, rid, adapter = reading_research(tmp_path, monkeypatch, responder=silent)
    try:
        store = app.state.store
        records = records_of(store, rid)
        data = named("10.1/oa.3")
        found = match(client, rid, ("doi.pdf", data))["matches"][0]
        asset = confirm(client, rid, data, found, records["W3"]).json()["attached"]["asset_id"]
        settle(client, rid)
        unread = client.get(f"/api/researches/{rid}/waiting").json()["files"]["rows"]
        runs_after_unread = len(client.get(f"/api/researches/{rid}").json()["runs"])
        adapter.responder = valid_response
        request_id = request_of(store, asset)["id"]
        retried = client.post(f"/api/researches/{rid}/waiting/requests/{request_id}/retry")
        settle(client, rid)
        again = client.post(f"/api/researches/{rid}/waiting/requests/{request_id}/retry")
        request = request_of(store, asset)
    finally:
        client.__exit__(None, None, None)
    [row] = [row for row in unread if row["source_version_id"] == records["W3"]]
    assert (row["state"], row["unread_reason"], row["request_id"]) == ("unread", "no_decision", request_id)
    assert retried.status_code == 200 and retried.json()["run"]["idempotency_key"].endswith(":1")
    assert (request["status"], request["attempt"]) == ("read", 1)
    assert again.status_code == 409
    assert runs_after_unread >= 3


def test_a_file_with_no_text_keeps_its_work_waiting_and_the_only_version_takes_no_other(tmp_path, monkeypatch):
    app, client, rid, adapter = reading_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        blank = make_pdf([""])
        found = match(client, rid, ("scan.pdf", blank))["matches"][0]
        # A file with no text layer names nothing: the person chooses the work.
        work_id = store.source(records["W4"])["work_id"]
        candidate = next(w for w in found["candidates"] if w["work_id"] == work_id)
        first = confirm(client, rid, blank, found | {"work": candidate}, records["W4"])
        listed = client.get(f"/api/researches/{rid}/waiting").json()
        second_file = named("10.1/oa.4")
        again = match(client, rid, ("doi.pdf", second_file))["matches"][0]
        second = confirm(client, rid, second_file, again, records["W4"])
        assets = store.conn.execute("SELECT COUNT(*), SUM(removed_at IS NULL) FROM source_assets"
                                    " WHERE source_version_id = ?", (records["W4"],)).fetchone()
    finally:
        client.__exit__(None, None, None)
    assert first.status_code == 201 and first.json()["attached"]["reading"] == "unreadable"
    row = next(row for row in listed["rows"] if row["head"] == records["W4"])
    assert row["reason_code"] == "text_unreadable"
    assert not [f for f in listed["files"]["rows"] if f["source_version_id"] == records["W4"]]
    # Its only version holds its own file: 18b neither replaces nor removes it, so the new file is refused.
    assert [v["has_pdf"] for v in again["work"]["versions"]] == [True]
    assert second.status_code == 409 and second.json()["detail"]["reason"] == "pdf_in_use"
    assert tuple(assets) == (1, 1)


# ---- an app whose worker does not run ------------------------------------------------------------------------------

@pytest.fixture
def still(tmp_path, monkeypatch):
    """An app whose worker never runs, with an `sw` research built at its store and a flow to write through."""
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")

    def make(workflow="sw", reading="auto"):
        app = create_app(Settings(data_dir=tmp_path / workflow / "data", port=8765, search_workflow=workflow,
                                  fulltext_adjudication=reading),
                         adapters={"fake": FakeAdapter(valid_response)}, start_worker=False,
                         extra_hosts=("testserver",), trusted_clients=("testclient",))
        client = client_of(app)
        lib = Lib(app.state.store, workflow=workflow)
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


def test_a_source_row_upload_to_an_excluded_work_writes_nothing_and_a_legacy_upload_neither(still):
    app, client, lib = still()
    store = app.state.store
    svid = candidate(lib)
    lib.list_edit(svid, "excluded")
    assert upload(client, lib.rid, svid).status_code == 201
    assert DecisionStore(store).current(lib.rid, svid, "fulltext") is None
    assert store.conn.execute("SELECT COUNT(*) FROM person_pdf_requests").fetchone()[0] == 0
    assert runs(store, lib.rid) == []
    legacy_app, legacy_client, legacy = still(workflow="legacy")
    other = legacy.work()
    assert upload(legacy_client, legacy.rid, other).status_code == 201
    assert DecisionStore(legacy_app.state.store).current(legacy.rid, other, "fulltext") is None
    assert runs(legacy_app.state.store, legacy.rid) == []


def test_a_queued_run_the_api_pauses_holds_the_reading_and_cancelling_it_opens_it(still):
    app, client, lib = still()
    store = app.state.store
    discovery = store.create_run(lib.rid, "discovery", {"max_model_calls": 1}, None)
    svid = candidate(lib)
    assert upload(client, lib.rid, svid).status_code == 201
    assert runs(store, lib.rid) == []  # a queued run is active: the reading waits
    paused = client.post(f"/api/runs/{discovery['id']}/pause").json()
    assert paused["status"] == "paused" and runs(store, lib.rid) == []  # never passed the worker; still held
    view = client.get(f"/api/researches/{lib.rid}/waiting").json()["files"]
    assert view["paused_run"]["id"] == discovery["id"]
    cancelled = client.post(f"/api/runs/{discovery['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    [run] = runs(store, lib.rid)
    assert run["status"] == "queued" and ":person:" in run["idempotency_key"]


def test_a_person_who_cancels_a_reading_run_leaves_its_files_unread_and_nothing_reopens(still):
    app, client, lib = still()
    store = app.state.store
    svid = candidate(lib)
    upload(client, lib.rid, svid)
    [run] = runs(store, lib.rid)
    cancelled = client.post(f"/api/runs/{run['id']}/cancel").json()
    request = store.conn.execute("SELECT status, unread_reason FROM person_pdf_requests").fetchone()
    assert cancelled["status"] == "cancelled" and tuple(request) == ("unread", "run_cancelled")
    assert [r["status"] for r in runs(store, lib.rid)] == ["cancelled"]
    files = client.get(f"/api/researches/{lib.rid}/waiting").json()["files"]["rows"]
    assert [(f["source_version_id"], f["state"]) for f in files] == [(svid, "unread")]


def test_cancelling_a_reading_run_leaves_a_file_added_after_its_plan_froze_waiting_and_opens_its_reading(still):
    app, client, lib = still()
    store, flow = app.state.store, app.state.worker.flow
    first, second = candidate(lib), candidate(lib)
    upload(client, lib.rid, first)
    [run] = runs(store, lib.rid)
    store.update_run(run["id"], status="running")
    flow._adjudication_plan(store.run(run["id"]), store.scope(lib.rid))  # the plan takes the first file
    upload(client, lib.rid, second)  # added after the plan froze: the run is active, so the file waits
    assert len(runs(store, lib.rid)) == 1
    assert client.post(f"/api/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    rows = {row["source_version_id"]: dict(row) for row in store.conn.execute(
        "SELECT source_version_id, asset_id, status, unread_reason, run_id FROM person_pdf_requests")}
    assert (rows[first]["status"], rows[first]["unread_reason"], rows[first]["run_id"]) == (
        "unread", "run_cancelled", run["id"])
    assert (rows[second]["status"], rows[second]["unread_reason"]) == ("waiting", None)
    [_, reading] = runs(store, lib.rid)
    assert reading["status"] == "queued" and ":person:" in reading["idempotency_key"]
    store.update_run(reading["id"], status="running")
    plan = flow._adjudication_plan(store.run(reading["id"]), store.scope(lib.rid))
    assert plan["works"][0]["read_version"] == second  # the new run reads it first


def test_a_crash_after_the_attach_opens_the_reading_when_the_app_starts_again(tmp_path, monkeypatch):
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    settings = Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", fulltext_adjudication="auto")
    first = create_app(settings, adapters={"fake": FakeAdapter(valid_response)}, start_worker=False,
                       extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = client_of(first)
    lib = Lib(first.state.store)
    svid = candidate(lib)
    active = first.state.store.create_run(lib.rid, "table_columns", {"max_model_calls": 1}, None)
    upload(client, lib.rid, svid)  # the reading waits behind the queued run
    first.state.store.update_run(active["id"], status="cancelled")  # it ended; the process died before the queue
    client.__exit__(None, None, None)
    second = create_app(settings, adapters={"fake": FakeAdapter(valid_response)},
                        extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = client_of(second)
    try:
        settle(client, lib.rid)
        store = second.state.store
        request = store.conn.execute("SELECT status FROM person_pdf_requests").fetchone()[0]
        reading = runs(store, lib.rid)
    finally:
        client.__exit__(None, None, None)
    assert request == "read" and [r["status"] for r in reading] == ["completed"]

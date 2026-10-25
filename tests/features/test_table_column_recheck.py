"""UI parity S17, F20: one run rechecks every cell of a table column. SYNTHETIC records; the model is the fake adapter,
so these tests show the workflow (row order, proposals only, resume, the one-active-run rule, cancel), not model quality.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.workflow.worker import Worker
from fakes import FakeAdapter
from test_api_flow import app_for, create, session, wait_run
from test_evidence_tables import PACKET_SIZE, upload
from test_table_extraction import cell, execute, fill, library, stored_inputs, table_url


class Crash(BaseException):
    """The process stopping in the middle of a call."""


def column_version(lib):
    return next(c for c in lib.tables.table_view(lib.rid, lib.tid)["columns"] if c["id"] == lib.cid)["version"]


def recheck_column(lib, key=None):
    return lib.tables.request_column_recheck(lib.rid, lib.tid, lib.cid, column_version(lib), key)


def kinds(lib, svid):
    return [(r["kind"], r.get("decision")) for r in cell(lib, svid)["revisions"]]


def sent_sources(lib, run_id):
    """The source of each call the run sent, in order (the model sees short handles; the stored input has the ids)."""
    return [p["extraction_target"]["source_id"] for p in stored_inputs(lib, run_id)]


def recheck_steps(lib, run_id):
    return {r["operation_key"]: r["status"] for r in lib.conn.execute(
        "SELECT operation_key, status FROM run_steps WHERE run_id = ? AND operation_key LIKE 'column_recheck:%'", (run_id,))}


def test_a_column_recheck_proposes_for_every_cell_in_row_order_and_never_changes_a_value(tmp_path):
    lib = library(tmp_path)
    execute(lib, fill(lib))
    values = {svid: cell(lib, svid)["current"]["id"] for svid in (lib.published, lib.preprint, lib.no_text)}
    calls = len(lib.adapter.calls)

    run = recheck_column(lib)
    assert run["kind"] == "table_column_recheck" and run["stage"] == "extraction"
    rows = lib.tables.active_rows(lib.tid)
    assert [c["source_version_id"] for c in run["target"]["cells"]] == [r for r in rows if r != lib.no_text]
    assert run["target"]["rows_without_text"] == [lib.no_text] and run["budget"]["max_model_calls"] == 4
    assert execute(lib, run)["status"] == "completed"

    assert len(lib.adapter.calls) == calls + 2
    assert sent_sources(lib, run["id"]) == [c["source_version_id"] for c in run["target"]["cells"]]  # in row order
    for svid in (lib.published, lib.preprint):
        view = cell(lib, svid)
        assert view["current"]["id"] == values[svid]  # the value the cell shows is unchanged
        assert view["pending_proposal"]["kind"] == "model_proposal" and view["pending_proposal"]["output_status"] == "structurally_valid"
    assert cell(lib, lib.no_text)["current"]["id"] == values[lib.no_text] and cell(lib, lib.no_text)["pending_proposal"] is None
    summary = lib.store.existing_step(run["id"], "column_recheck:summary")["output"]
    assert summary["planned"] == 2 and set(summary["proposed"]) == {lib.published, lib.preprint}
    assert summary["no_answer"] == [] and summary["rows_without_text"] == [lib.no_text]

    assert execute(lib, run)["status"] == "completed"  # run again after its last write: no call, no second proposal
    assert len(lib.adapter.calls) == calls + 2 and kinds(lib, lib.published) == [("model_fill", None), ("model_proposal", "pending")]


def test_a_column_recheck_resumes_after_a_crash_without_resending_a_finished_cell(tmp_path):
    lib = library(tmp_path)
    run = recheck_column(lib)
    first, second = (c["source_version_id"] for c in run["target"]["cells"])
    crashed = []

    def crash_once(si):
        if len(lib.adapter.calls) == 2 and not crashed:  # the second cell's call
            crashed.append(True)
            raise Crash

    lib.adapter.before = crash_once
    with pytest.raises(Crash):
        execute(lib, run)
    assert Worker.recover(SimpleNamespace(store=lib.store)) == {"runs": 1, "steps": 1, "model_sessions": 1}
    assert lib.store.run(run["id"])["pause_reason"] == "backend_restarted"
    assert recheck_steps(lib, run["id"]) == {f"column_recheck:{first}": "succeeded", f"column_recheck:{second}": "outcome_unknown"}

    lib.store.resume_run(run["id"])
    assert execute(lib, run)["status"] == "completed"
    assert sent_sources(lib, run["id"]) == [first, second, second]  # the finished cell was not sent again
    assert [k for k in kinds(lib, first)] == [("model_proposal", "pending")]
    assert [k for k in kinds(lib, second)] == [("model_proposal", "pending")]


def test_column_recheck_api(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        for name, text in (("a.pdf", "SYNTHETIC packets of 128 bytes."), ("b.pdf", "SYNTHETIC packets of 64 bytes.")):
            upload(client, rid, name, text)
        tid = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()["table"]["id"]
        view = client.post(f"{table_url(rid, tid)}/columns", json=PACKET_SIZE | {"expected_version": 1}).json()
        column = view["columns"][0]
        url = f"{table_url(rid, tid)}/columns/{column['id']}/recheck"

        assert client.post(url, json={"expected_version": column["version"] + 1}).status_code == 409
        assert client.post(url, json={"expected_version": column["version"]}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        first = client.post(url, json={"expected_version": column["version"]}, headers={"Idempotency-Key": "c1"})
        assert first.status_code == 202, first.text
        assert first.json()["kind"] == "table_column_recheck" and len(first.json()["target"]["cells"]) == 2
        assert client.post(url, json={"expected_version": column["version"]}, headers={"Idempotency-Key": "c1"}).json()["id"] == first.json()["id"]
        _, run = wait_run(client, rid, first.json()["id"])
        assert run["status"] == "completed"
        for row in view["rows"]:
            shown = client.get(f"{table_url(rid, tid)}/cells/{column['id']}/{row['source_version_id']}").json()
            assert shown["current"] is None and shown["pending_proposal"]["kind"] == "model_proposal"

        conn = app.state.store.conn
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_ACTIVE00000001', ?, 1, 'answer', 'running', 'answer', '{}', 'now', 'now')", (rid,))
        assert client.post(url, json={"expected_version": column["version"]}).status_code == 409
        conn.execute("UPDATE runs SET status = 'cancelled' WHERE id = 'run_ACTIVE00000001'")

        adapter.delay = 0.5  # the run is still at its first cell when the cancel arrives
        second = client.post(url, json={"expected_version": column["version"]}).json()
        cancelled = client.post(f"/api/runs/{second['id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        _, run = wait_run(client, rid, second["id"])
        assert run["status"] == "cancelled" and len(adapter.calls) <= 3

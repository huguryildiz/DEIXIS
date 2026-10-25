"""P6 slice 0: table fill sends per-source extraction calls under a shared, adjustable concurrency limit.

These are FakeAdapter tests; they show workflow behavior, not model quality.
"""

import asyncio
from types import SimpleNamespace


from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from fakes import FakeAdapter, valid_response
from test_evidence_tables import PACKET_SIZE


def library_with_sources(path, n, limit, responder=valid_response, delay=0.0, before=None, fail=None):
    conn = db.connect(path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("How large are packets?", "attached", "quick", [], "fake", "fake-model", None)
    svids = []
    for i in range(n):
        svid = store.create_upload_source(f"SYNTHETIC source {i:02d}")
        with transaction(conn):
            store._insert_passage(
                svid, None, "abstract", None, None, "user", None, None,
                f"SYNTHETIC abstract {i}: packets of {i} bytes.",
            )
        store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
        svids.append(svid)
    tables = TableStore(store)
    tid = tables.create_table(rid, "Packets", None, None, None)
    cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
    adapter = FakeAdapter(responder, delay=delay, before=before, fail=fail)
    deps = FlowDeps(
        Settings(data_dir=path / "data", port=8765), store, {"fake": adapter}, skill.load_skill_package(), None,
        limiter=ModelCallLimiter(limit),
    )
    flow = ResearchFlow(deps)
    return SimpleNamespace(
        conn=conn, store=store, tables=tables, rid=rid, svids=svids, tid=tid, cid=cid, adapter=adapter, flow=flow,
    )


def fill(lib):
    version = lib.tables.table_view(lib.rid, lib.tid)["table"]["version"]
    return lib.tables.request_fill(lib.rid, lib.tid, None, False, version, None)


def execute(lib, run):
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def cell_values(lib):
    view = lib.tables.table_view(lib.rid, lib.tid)
    values = {svid: None for svid in lib.svids}
    values.update({c["source_version_id"]: (c["current"]["value"] if c["current"] else None) for c in view["cells"]})
    return values


def test_one_sources_invalid_output_does_not_stop_the_others(tmp_path):
    def responder(si):
        if "SYNTHETIC abstract 1:" in si["passages"][0]["text"]:
            return "not json"
        return valid_response(si)

    lib = library_with_sources(tmp_path, 4, limit=3, responder=responder)
    broken = lib.svids[1]
    run = execute(lib, fill(lib))
    assert run["status"] == "completed"
    values = cell_values(lib)
    assert values[broken] is None
    assert all(values[svid] is not None for svid in lib.svids if svid != broken)


def test_pause_lets_in_flight_calls_finish_and_applies_them_only_on_resume(tmp_path):
    holder = {"paused": False}

    def before(si):
        if not holder["paused"] and len(holder["lib"].adapter.calls) == 3:
            holder["paused"] = True
            holder["lib"].store.update_run(
                si["run_id"], event="run_pause_requested", status="pause_requested", pause_reason="user_requested",
            )

    lib = library_with_sources(tmp_path, 6, limit=3, delay=0.02, before=before)
    holder["lib"] = lib
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
    assert len(lib.adapter.calls) == 3
    assert all(v is None for v in cell_values(lib).values())
    steps = [s for s in lib.store.run_steps(run["id"]) if s["kind"] == "model:cell_extraction"]
    assert [s["status"] for s in steps] == ["succeeded"] * 3

    resumed = execute(lib, run)
    assert resumed["status"] == "completed"
    assert len(lib.adapter.calls) == 6
    assert all(v is not None for v in cell_values(lib).values())

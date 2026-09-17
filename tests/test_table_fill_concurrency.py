"""P6 slice 0: table fill sends per-source extraction calls under a shared, adjustable concurrency limit.

These are FakeAdapter tests; they show workflow behavior, not model quality.
"""

import asyncio
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow import flow as flow_module
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


def test_the_limit_bounds_concurrent_calls_and_matches_sequential_output(tmp_path):
    sequential = library_with_sources(tmp_path / "seq", 6, limit=1, delay=0.01)
    execute(sequential, fill(sequential))
    concurrent = library_with_sources(tmp_path / "con", 6, limit=3, delay=0.01)
    execute(concurrent, fill(concurrent))

    assert concurrent.adapter.max_concurrent > 1
    assert concurrent.adapter.max_concurrent <= 3
    assert len(sequential.adapter.calls) == len(concurrent.adapter.calls) == 6
    assert list(cell_values(sequential).values()) == list(cell_values(concurrent).values())


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


def test_unexpected_exception_waits_for_other_in_flight_calls_before_propagating(tmp_path):
    def fail(si):
        if "SYNTHETIC abstract 1:" in si["passages"][0]["text"]:
            raise RuntimeError("unexpected adapter failure")

    lib = library_with_sources(tmp_path, 6, limit=3, delay=0.02, fail=fail)
    run = fill(lib)
    lib.store.update_run(run["id"], status="running")

    with pytest.raises(RuntimeError, match="unexpected adapter failure"):
        asyncio.run(lib.flow.execute(run["id"]))

    assert lib.adapter.current == 0
    assert 3 <= len(lib.adapter.calls) < 6
    steps = [s for s in lib.store.run_steps(run["id"]) if s["kind"] == "model:cell_extraction"]
    assert sum(s["status"] == "succeeded" for s in steps) == len(lib.adapter.calls) - 1


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


def test_cancel_lets_in_flight_calls_finish_but_never_applies_them(tmp_path):
    holder = {"cancelled": False}

    def before(si):
        if not holder["cancelled"] and len(holder["lib"].adapter.calls) == 3:
            holder["cancelled"] = True
            holder["lib"].store.update_run(
                si["run_id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled",
            )

    lib = library_with_sources(tmp_path, 6, limit=3, delay=0.02, before=before)
    holder["lib"] = lib
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("cancelled", "user_cancelled")
    assert len(lib.adapter.calls) == 3
    assert all(v is None for v in cell_values(lib).values())
    steps = [s for s in lib.store.run_steps(run["id"]) if s["kind"] == "model:cell_extraction"]
    assert [s["status"] for s in steps] == ["succeeded"] * 3


def test_a_rate_limited_call_lowers_the_limit_and_is_resent_up_to_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    attempts = {"n": 0}

    def fail(si):
        attempts["n"] += 1
        return ModelStepResult("failed", error="HTTP 429: Too Many Requests") if attempts["n"] == 1 else None

    lib = library_with_sources(tmp_path, 1, limit=4, fail=fail)
    run = execute(lib, fill(lib))
    assert run["status"] == "completed"
    assert attempts["n"] == 2
    assert lib.flow.deps.limiter.limit == 2
    assert all(v is not None for v in cell_values(lib).values())


def test_a_rate_limit_that_never_clears_still_halts_like_today(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)

    def fail(si):
        return ModelStepResult("failed", error="HTTP 429: Too Many Requests")

    lib = library_with_sources(tmp_path, 1, limit=4, fail=fail)
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    assert len(lib.adapter.calls) == 3
    assert lib.flow.deps.limiter.limit == 1


def test_a_non_rate_limit_failure_is_not_resent(tmp_path):
    def fail(si):
        return ModelStepResult("failed", error="ConnectError: timeout", delivery_class="after_send_unknown")

    lib = library_with_sources(tmp_path, 1, limit=4, fail=fail)
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    assert len(lib.adapter.calls) == 1

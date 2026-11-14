"""Evidence cells written while the reading is still going, and what bounds them.

Synthetic records, files and model output throughout: these show the workflow's order and its boundaries, not
extraction quality.
"""

import asyncio
import time

import pytest

from deixis.domain.rules import ABSTRACT_BATCH, FULLTEXT_RUNS, run_schema_repairs
from deixis.workflow.features.report import report_evidence_view
from deixis.workflow.features.tables import table_cells, table_open
from deixis.workflow.features.tables.cell_lane import CellLane
from deixis.workflow.screen import abstract_stage
from deixis.workflow.features.tables.tables import InvalidTableInput, TableStore
from deixis.workflow.read import read as fast_read
from deixis.workflow.run import flow as flow_module
from deixis.storage import db
from deixis.workflow.run.store import Store
from deixis.workflow.run.worker import Worker
from deixis.models.adapter import ModelStepResult
from fakes import FakeAdapter, parse_step_input, valid_response
from overlap_flow_helpers import discover
from test_evidence_tables import make_lib, model_output
from test_small_batch_flow import app_for, client_of
from windows_env import WAIT_FACTOR


def app(tmp_path, monkeypatch, n=4, adapter=None):
    """A standard discovery that fetches and reads files, with the automatic study table on."""
    return app_for(tmp_path, monkeypatch, n, pdf=True, reading="auto", study_table="auto", adapter=adapter)


def steps_of(store, run_id, kind=None):
    return [dict(row) for row in store.conn.execute(
        "SELECT operation_key, kind, status, error_code FROM run_steps WHERE run_id = ?"
        + (" AND kind = ?" if kind else "") + " ORDER BY rowid", (run_id, kind) if kind else (run_id,))]


def cell_steps(store, run_id):
    return [step for step in steps_of(store, run_id) if f":{table_cells.KEY}:" in step["operation_key"]]


def revisions(store, run_id=None):
    """The cell revisions in the library, or only those one run wrote."""
    return [dict(row) for row in store.conn.execute(
        "SELECT c.source_version_id, c.column_id, r.kind, r.author FROM cell_revisions r"
        " JOIN evidence_cells c ON c.id = r.cell_id" + (" WHERE r.run_id = ?" if run_id else "")
        + " ORDER BY r.rowid", (run_id,) if run_id else ())]


def test_a_work_read_in_full_gets_its_cells_from_the_reading_itself(tmp_path, monkeypatch):
    """The discovery run asks for each read paper's cells and writes them; no fill after the answer is needed."""
    application, _ = app(tmp_path, monkeypatch)
    with client_of(application) as client:
        store = application.state.store
        rid, run_id, _view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run

        sent = cell_steps(store, run_id)
        assert sent and all(step["status"] == "succeeded" for step in sent), sent
        # One call per source read in full, and that source's cells are written by this run.
        read = set(table_cells.read_versions(application.state.worker.flow._fulltext_works(rid)).values())
        assert read and {step["operation_key"].rsplit(":", 2)[1] for step in sent} == read

        table_id = table_open.chain_table(store, rid)
        written = revisions(store, run_id)
        assert {row["source_version_id"] for row in written} == read
        # They are the table's own values, in the columns the discovery run opened, not proposals waiting.
        assert {row["column_id"] for row in written} <= {c["id"] for c in TableStore(store)._columns(table_id)}
        assert {row["kind"] for row in written} == {"model_fill"}
        assert {row["author"] for row in written} == {"model"}


def wait_for_answer(client, rid):
    """The research's answer run, once it has settled."""
    deadline = time.time() + 30 * WAIT_FACTOR
    while time.time() < deadline:
        runs = client.get(f"/api/researches/{rid}").json()["runs"]
        answers = [run for run in runs if run["kind"] == "answer"]
        if answers and answers[-1]["status"] in ("completed", "failed", "paused", "cancelled"):
            return answers[-1]
        time.sleep(0.05)
    raise AssertionError("no answer run settled")


async def released(adapter):
    """Let the held call answer, from the loop the app's own tasks run on."""
    adapter.release.set()


class BlockingCells(FakeAdapter):
    """Holds the first cell call open until it is released, answering everything else at once."""

    def __init__(self):
        super().__init__(responder=valid_response)
        self.release = asyncio.Event()
        self.held = asyncio.Event()
        self.blocked = None

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
        step_input = parse_step_input(message)
        if step_input["task_type"] == "cell_extraction" and self.blocked is None:
            self.blocked = step_input["extraction_target"]["table_id"]
            self.held.set()
            await self.release.wait()
        return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)


def test_the_run_does_not_wait_for_a_cell_call_and_its_cells_arrive_after(tmp_path, monkeypatch):
    """A cell call still out at the cutoff does not hold the run, is not cancelled, and writes its cells later."""
    adapter = BlockingCells()
    application, _ = app(tmp_path, monkeypatch, adapter=adapter)
    with client_of(application) as client:
        store, flow = application.state.store, application.state.worker.flow
        _rid, run_id, _view, run = discover(client, effort="standard")
        # The run reached its end with that call still out: nothing in the stage waited for it.
        assert run["status"] == "completed", (run["status"], run.get("pause_reason"), run.get("error"))
        assert adapter.held.is_set() and adapter.blocked is not None
        assert flow.cell_lane.working(run_id) == 1
        before = len(revisions(store, run_id))

        client.portal.call(released, adapter)
        deadline = time.time() + 20 * WAIT_FACTOR
        while time.time() < deadline and flow.cell_lane.working(run_id):
            time.sleep(0.02)
        # Released, the call finished under the lane's ownership and its cells reached the table after the run.
        assert flow.cell_lane.working(run_id) == 0
        assert len(revisions(store, run_id)) > before


def test_a_cell_call_whose_deadline_passed_before_it_was_sent_is_not_sent(tmp_path, monkeypatch):
    """The cutoff is read again in the moment before the send, so a late call closes unsent and writes nothing."""
    real = table_cells.fill_source

    def late(flow, run, scope, key, svid, columns, cutoff):
        # False while the passages are chosen, true in the moment before the call would be sent.
        answers = iter([False, False])
        return real(flow, run, scope, key, svid, columns, lambda: next(answers, True))

    monkeypatch.setattr(fast_read.table_cells, "fill_source", late)
    application, _ = app(tmp_path, monkeypatch)
    with client_of(application) as client:
        store = application.state.store
        _rid, run_id, _view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        sent = cell_steps(store, run_id)
        assert sent and all(step["status"] == "cancelled" for step in sent), sent
        assert {step["error_code"] for step in sent} == {"model_read_cutoff"}
        assert not revisions(store, run_id)
        # The readings themselves were not touched by the cell calls' cutoff.
        assert [step for step in steps_of(store, run_id, "model:fulltext_adjudication")]


def test_no_cell_call_is_offered_once_the_reading_stage_is_over(tmp_path, monkeypatch):
    """Nothing new is offered after the cutoff: the stage stops asking as its deadline passes."""
    seen = {"adjudicated": False}
    real = fast_read.fast_path.past_deadline

    def past(store, run, stage):
        if stage == "read" and seen["adjudicated"]:
            return True
        return real(store, run, stage)

    monkeypatch.setattr(fast_read.fast_path, "past_deadline", past)
    application, _ = app(tmp_path, monkeypatch)
    with client_of(application) as client:
        store = application.state.store
        original = flow_module.ResearchFlow._save_cells

        def note(self, run, output, cell_versions, recheck):
            return original(self, run, output, cell_versions, recheck)

        monkeypatch.setattr(flow_module.ResearchFlow, "_save_cells", note)
        seen["adjudicated"] = True  # the deadline has passed before the stage's first pass
        _rid, run_id, _view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert not cell_steps(store, run_id)


def test_the_reserve_keeps_the_readings_calls_and_counts_the_cells_it_admits():
    """Pure arithmetic: what the reading still owes is reserved, and an admitted call is reserved as spent."""
    policy = {"K": 4}
    run = {"id": "run_one", "budget": {"max_model_calls": 30, "fast_path": policy}}
    # Two readings left of four, each two calls with its allowed repair, and one unclosed deeper batch.
    owed = table_cells.reserve(run, policy, settled_reads=2, open_deep_calls=1)
    reading = FULLTEXT_RUNS * 2 * (1 + run_schema_repairs(run, "fulltext_adjudication"))
    assert owed == reading + (1 + run_schema_repairs(run, "abstract_screening"))

    class Store:
        def run(self, _id):
            return {"usage": {"model_calls": 10}}

    class Flow:
        store = Store()
        _small_batch_guard = {"run_id": "run_one", "reserved_calls": set()}

    flow = Flow()
    per_call = 1 + run_schema_repairs(run, "cell_extraction")
    fits = (run["budget"]["max_model_calls"] - 10 - owed) // per_call
    assert fits >= 1
    assert table_cells.spare(flow, run, [f"k{i}" for i in range(fits)], owed) is True
    # One entry per call the admitted keys may spend, their repairs included.
    assert len(flow._small_batch_guard["reserved_calls"]) == fits * per_call
    # One more would take a call the reading is owed, so it is refused and nothing is reserved for it.
    assert table_cells.spare(flow, run, ["one_too_many"], owed) is False
    assert len(flow._small_batch_guard["reserved_calls"]) == fits * per_call
    # Outside the stage's own guard nothing is admitted on its allowance.
    flow._small_batch_guard = {"run_id": "another"}
    assert table_cells.spare(flow, run, ["f"], 0) is False


@pytest.mark.parametrize("code,offered", [
    ("all_parts_verified", True), ("criterion_absent", True), ("fulltext_runs_disagree", True),
    ("pdf_identity_unconfirmed", False), ("protocol_title", False), ("no_fulltext", False), ("not_read_yet", False)])
def test_only_a_work_whose_file_was_read_is_offered(code, offered):
    """A decision taken from the title, from an unconfirmed file or from no file at all gives no cell."""
    work = {"work_id": "w1", "head": "srv_one", "versions": [
        {"id": "srv_one", "has_text": True, "abstract": None,
         "fulltext": {"reason_code": code, "decided_by": "model", "stale": False, "created_at": "2026", "order": 1}}]}
    assert bool(table_cells.read_versions([work])) is offered


def test_a_persons_decision_on_the_work_is_not_a_reading():
    """A work the person decided is not offered: its decision says nothing about text this run read."""
    work = {"work_id": "w1", "head": "srv_one", "versions": [
        {"id": "srv_one", "has_text": True, "abstract": None,
         "fulltext": {"reason_code": "all_parts_verified", "decided_by": "human", "stale": False,
                      "created_at": "2026", "order": 1}}]}
    assert table_cells.read_versions([work]) == {}


def test_a_row_removed_while_the_call_was_out_gets_no_cell(tmp_path):
    """The write transaction checks the row again, so a person who removed it keeps it removed."""
    lib = make_lib(tmp_path)
    assert model_output(lib) is not None
    lib.tables.remove_row(lib.rid, lib.tid, lib.preprint, lib.tables._table(lib.rid, lib.tid)["version"])
    # The call for the removed row had already been sent; its answer writes nothing and says so.
    assert model_output(lib, sv=lib.preprint) is None
    assert not [row for row in revisions(lib.store) if row["source_version_id"] == lib.preprint]
    with pytest.raises(InvalidTableInput):
        lib.tables._active_row(lib.tid, lib.preprint)


def test_only_the_columns_without_a_cell_are_asked_for(tmp_path):
    """A column a person or an earlier call answered is left out of the next call."""
    lib = make_lib(tmp_path)
    table_id, svid = lib.tid, lib.published
    names = [column["name"] for column in table_cells.empty_columns(lib.store, table_id, svid)]
    assert names  # the table's one column is empty to begin with
    model_output(lib)
    assert table_cells.empty_columns(lib.store, table_id, svid) == []
    # A source that is not a row of the table is asked nothing at all.
    assert table_cells.empty_columns(lib.store, table_id, "srv_missing") == []


def test_a_cell_call_the_shutdown_cancels_is_left_outcome_unknown(tmp_path, monkeypatch):
    """Stopping the app ends the lane's calls; the next start marks the step the person has to be told about."""
    adapter = BlockingCells()
    application, _ = app(tmp_path, monkeypatch, adapter=adapter)
    with client_of(application) as client:
        store = application.state.store
        _rid, run_id, _view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert application.state.worker.flow.cell_lane.working(run_id) == 1
        open_steps = [step for step in cell_steps(store, run_id) if step["status"] == "running"]
        assert len(open_steps) == 1, cell_steps(store, run_id)
    # The app is stopped: the lane cancelled the call and left its step open, as a crash would.
    restarted = Store(db.connect(tmp_path / "data" / "library.sqlite"))
    held = open_steps[0]["operation_key"]
    assert [step["status"] for step in cell_steps(restarted, run_id) if step["operation_key"] == held] == ["running"]
    Worker(restarted, application.state.worker.flow, tmp_path / "data" / "worker.lock").recover()
    after = {step["operation_key"]: step["status"] for step in cell_steps(restarted, run_id)}
    assert after[held] == "outcome_unknown"


def test_the_deeper_screenings_frozen_window_is_reserved_until_its_plan_says_otherwise():
    """Its plan may not be stored yet when the top N ends, so the whole window is held back until it is."""
    window = {"first": 26, "last": 75, "runs": 1}  # fifty works, one read each
    whole = abstract_stage.model_calls(50, ABSTRACT_BATCH, 1)
    assert whole > 0
    # No plan and the task still working: the window is reserved whole.
    assert table_cells.deep_calls(window, None, closed=0, ended=False) == whole
    # A task that has ended owes nothing, with or without a plan and with batches left unclosed: a batch whose
    # works a person decided is never sent.
    assert table_cells.deep_calls(window, None, closed=0, ended=True) == 0
    assert table_cells.deep_calls(window, {"batches": [["a"], ["b"]]}, closed=0, ended=True) == 0
    # With a plan, only its unclosed batches are owed.
    plan = {"batches": [["a"], ["b"], ["c"]]}
    assert table_cells.deep_calls(window, plan, closed=1, ended=False) == 2
    assert table_cells.deep_calls(window, plan, closed=3, ended=False) == 0
    # A run without the deeper screening owes nothing at all.
    assert table_cells.deep_calls(None, None, closed=0, ended=False) == 0


def test_the_lane_keeps_a_call_already_out_for_the_same_source():
    """A resumed reading, whose own record is empty, must not replace a task the shutdown would have to wait for."""
    async def check():
        lane = CellLane()
        started = asyncio.Event()

        async def never_ends():
            started.set()
            await asyncio.Event().wait()

        first = lane.send("run_one", "srv_one", never_ends())
        await started.wait()
        second_coro = never_ends()
        assert lane.send("run_one", "srv_one", second_coro) is first
        assert lane.out("run_one", "srv_one")
        assert lane.working("run_one") == 1
        # Ending the lane cancels and awaits the call it owns, and gives up its place.
        await lane.close()
        assert first.cancelled()
        assert not lane.out("run_one", "srv_one") and lane.tasks == {}

    asyncio.run(check())


class FailingCells(FakeAdapter):
    """Answers everything but a cell call, which fails as a transport failure would."""

    def __init__(self):
        super().__init__(responder=valid_response,
                         fail=lambda si: ModelStepResult("failed", error="SYNTHETIC transport failure",
                                                         delivery_class="before_send")
                         if si["task_type"] == "cell_extraction" else None)


def test_a_failed_cell_call_costs_that_source_and_leaves_the_run_as_it_was(tmp_path, monkeypatch):
    """The call is an optional step: its failure neither pauses the reading nor unmakes a completed run."""
    application, _ = app(tmp_path, monkeypatch, adapter=FailingCells())
    with client_of(application) as client:
        store = application.state.store
        _rid, run_id, _view, run = discover(client, effort="standard")
        assert run["status"] == "completed", (run["status"], run.get("pause_reason"), run.get("error"))
        sent = cell_steps(store, run_id)
        assert sent and {step["status"] for step in sent} == {"failed"}, sent
        assert not revisions(store, run_id)
        # The readings themselves were read and the run is still the completed one.
        assert steps_of(store, run_id, "model:fulltext_adjudication")
        assert store.run(run_id)["status"] == "completed"


def test_a_cell_that_lands_after_the_answer_is_not_in_that_answers_frozen_view(tmp_path, monkeypatch):
    """The view is a snapshot: a call still out when it froze writes into the table, never back into it."""
    adapter = BlockingCells()
    application, _ = app(tmp_path, monkeypatch, adapter=adapter)
    with client_of(application) as client:
        store, flow = application.state.store, application.state.worker.flow
        rid, run_id, _view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert flow.cell_lane.working(run_id) == 1
        answer = wait_for_answer(client, rid)
        frozen = report_evidence_view.frozen(store, answer["id"])
        assert frozen is not None and frozen["bound_to_answer"]
        held = {(row["source_version_id"], row["column_id"]) for row in frozen["cells"]}

        client.portal.call(released, adapter)
        deadline = time.time() + 20 * WAIT_FACTOR
        while time.time() < deadline and flow.cell_lane.working(run_id):
            time.sleep(0.02)
        assert flow.cell_lane.working(run_id) == 0
        # The released call's cells are in the table, and the answer's view is unchanged by them.
        live = {(row["source_version_id"], row["column_id"]) for row in revisions(store, run_id)}
        assert live - held
        again = report_evidence_view.frozen(store, answer["id"])
        assert {(row["source_version_id"], row["column_id"]) for row in again["cells"]} == held

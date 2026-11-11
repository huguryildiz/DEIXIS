"""The study table is opened by the discovery run before it reads anything; its proposed columns come after the answer.

Synthetic model output throughout, so these show workflow order, not extraction quality.
"""

import dataclasses
import json
import time

from fastapi.testclient import TestClient

from deixis.workflow.features.tables import table_open
from deixis.workflow.features.tables.tables import TableStore
from fakes import FakeAdapter, envelope, valid_response
from deixis.api.app import create_app
from test_api_flow import create, fake_fetch, openalex_client, run_to_end, session, sw_settings
from test_report_flow import COLUMN, LIMITATIONS_COLUMN


def settled(client, rid, seconds=10.0):
    """Wait until no run of the research is queued or running: a second run is refused while one is active."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        runs = client.get(f"/api/researches/{rid}").json()["runs"]
        if not [run for run in runs if run["status"] in ("queued", "running", "pause_requested")]:
            return
        time.sleep(0.05)
    raise AssertionError("the research's runs did not settle")


class ColumnAdapter(FakeAdapter):
    """Proposes two columns; everything else answers as the plain fake does."""

    def __init__(self, columns=(COLUMN, LIMITATIONS_COLUMN), invalid=False):
        super().__init__(responder=self._response)
        self.columns = columns
        self.invalid = invalid

    def _response(self, step_input):
        if step_input["task_type"] != "table_columns":
            return valid_response(step_input)
        if self.invalid:
            return json.dumps({"schema_version": "deixis.table_column_proposal.v1", "columns": "not a list"})
        return json.dumps(envelope(step_input, "deixis.table_column_proposal.v1") | {
            "columns": [{**column, "rationale": "SYNTHETIC rationale"} for column in self.columns], "notes": ""})


def app_for(tmp_path, adapter):
    """The app with the automatic study table on, which is what opens a table before reading."""
    settings = dataclasses.replace(sw_settings(tmp_path), study_table="auto")
    return create_app(settings, adapters={"fake": adapter}, http_client=openalex_client(200), fetcher=fake_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def steps(store, kind):
    return [dict(row) for row in store.conn.execute(
        "SELECT operation_key, status FROM run_steps WHERE kind = ? ORDER BY rowid", (kind,))]


def columns_of(store, research_id):
    tables = TableStore(store)
    table_id = table_open.chain_table(store, research_id)
    return table_id, [{"name": column["name"], "origin": column["origin"]} for column in tables._columns(table_id)]


def discovery_run(store, research_id):
    return [dict(row) for row in store.conn.execute(
        "SELECT id, kind, target_json FROM runs WHERE research_id = ? AND kind = 'discovery'", (research_id,))][0]


def test_the_table_and_its_question_columns_exist_before_the_read_stage(tmp_path):
    """The opening precedes the read stage, carries the question's own columns, and asks no model for more."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")

        opened = steps(store, "code:study_table_open")
        assert [step["status"] for step in opened] == ["succeeded"]
        # The opening is a step of the discovery run and it is stored before the read stage closes, so the columns
        # are in place while the works are read.
        order = [row[0] for row in store.conn.execute(
            "SELECT operation_key FROM run_steps WHERE run_id = ? ORDER BY rowid", (discovery_run(store, rid)["id"],))]
        assert all(order.index("study_table_open") < order.index(key) for key in order
                   if key.startswith("fulltext_adjudication"))
        # No model is asked for columns on the way to the answer: that call is not needed to write it.
        assert "study_table_columns" not in order

        table_id, columns = columns_of(store, rid)
        # The two the question's own words make. Whether the chain after the answer has already added its proposed
        # ones by now is its own race and its own test; what this one holds is that these two are there and first.
        assert [column["name"] for column in columns][:2] == ["Reported finding", "Condition of the finding"]
        assert [column["origin"] for column in columns][:2] == ["template", "template"]
        # The run names the table it opened, where every table step of it looks for it.
        assert json.loads(discovery_run(store, rid)["target_json"])["table_id"] == table_id


def test_the_columns_a_model_proposes_are_added_after_the_answer(tmp_path):
    """The proposal is not lost by moving: the chain that runs after the answer asks for it and accepts it."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")
        settled(client, rid)

        asked = steps(store, "model:table_columns")
        assert [step["status"] for step in asked] == ["succeeded"]
        # Asked by a run of its own, after the answer, never by the discovery run the person is waiting on.
        discovery = discovery_run(store, rid)["id"]
        assert not [row for row in store.conn.execute(
            "SELECT 1 FROM run_steps WHERE run_id = ? AND kind = 'model:table_columns'", (discovery,))]

        _, columns = columns_of(store, rid)
        assert [column["origin"] for column in columns][:2] == ["template", "template"]
        assert [column["origin"] for column in columns][2:] == ["model_suggestion"] * (len(columns) - 2)
        assert len(columns) == 4


def test_the_chain_started_twice_with_one_key_returns_the_one_run(tmp_path):
    """The same answer asks for the chain once. A second call with its key returns the run the first one started.

    Which branch the chain would take is no longer fixed for a table: the proposal writes the acceptance the branch
    reads, so a replayed call would ask for a fill where the first asked for columns.
    """
    from deixis.workflow.features.report import report_pipeline

    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")
        settled(client, rid)

        answer_id = store.conn.execute(
            "SELECT id FROM answers WHERE research_id = ? AND status = 'structurally_valid'", (rid,)).fetchone()["id"]
        key = f"answer:{answer_id}"
        first = [row[0] for row in store.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND kind = 'table_columns'", (rid,))]
        assert len(first) == 1
        again = report_pipeline.start(store, rid, key)
        assert again["id"] == first[0]
        # And no second chain run was created by asking again.
        assert [row[0] for row in store.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND kind = 'table_columns'", (rid,))] == first


def test_the_question_is_quoted_into_the_columns_code_writes(tmp_path):
    """No model call shapes the two columns: the instruction carries the person's own sentence."""
    specs = table_open.question_columns("Does  depth\nhelp?")
    assert [spec["answer_format"] for spec in specs] == ["text", "text"]
    assert "Does depth help?" in specs[0]["instruction"]
    assert specs[1]["instruction"].startswith("The setting or experimental condition")
    # A question without end punctuation gets one, and an empty question still yields two usable columns.
    assert table_open.question_columns("no mark")[0]["instruction"].endswith(
        " Give the finding as the source states it, with its number and unit when it states one.")
    assert len(table_open.question_columns("")) == 2


def test_a_failed_proposal_leaves_the_question_columns_and_the_cells_are_still_filled(tmp_path):
    """A proposal that adds no column is not a stop: the question's own columns are there and their cells are filled.

    The proposal is asked for after the answer now, so a failure lands in the chain rather than in the discovery
    run. The chain must go on to the fill: the table's own deliverable is the cells under the columns it has.
    """
    with TestClient(app_for(tmp_path, ColumnAdapter(invalid=True))) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")
        settled(client, rid)

        assert [step["status"] for step in steps(store, "code:study_table_open")] == ["succeeded"]
        assert [step["status"] for step in steps(store, "model:table_columns")] == ["failed"]
        # No column was accepted, and the two the question wrote are the table's columns.
        _, columns = columns_of(store, rid)
        assert [column["origin"] for column in columns] == ["template", "template"]
        assert not [row for row in store.conn.execute(
            "SELECT 1 FROM events WHERE type = 'study_table_columns_accepted'")]
        # The chain did not record the table as having no columns to fill.
        stops = [json.loads(row[0]) for row in store.conn.execute(
            "SELECT payload_json FROM events WHERE type = 'study_table_stopped'")]
        assert [stop for stop in stops if stop.get("reason") == "no_columns"] == []


def test_a_second_discovery_run_adopts_the_same_table_and_adds_no_column(tmp_path):
    """The opening is idempotent: another run of the research opens no second table and repeats no column."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")
        settled(client, rid)  # the run a finished discovery chains is still this research's run
        first_table, first_columns = columns_of(store, rid)

        run_to_end(client, rid, "discovery")

        tables = [row[0] for row in store.conn.execute(
            "SELECT id FROM evidence_tables WHERE research_id = ?", (rid,))]
        assert tables == [first_table]
        _, columns = columns_of(store, rid)
        # The second run's proposal proposes the same two names, which are already in the table, so nothing is added.
        assert columns == first_columns


def test_a_persons_own_table_is_never_joined(tmp_path):
    """A table a person built holds their columns; the opening passes it by and opens its own."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        own = TableStore(store).create_table(rid, "My own table", [], None, None)

        run_to_end(client, rid, "discovery")

        assert table_open.chain_table(store, rid) != own
        assert not TableStore(store)._columns(own)


def test_no_fill_starts_beside_a_paused_reading(tmp_path):
    """The table exists while a run is paused, and no automatic fill may become the research's active run then.

    Otherwise the person could not resume their own reading: a research runs one run at a time.
    """
    from deixis.workflow.features.tables import table_rows

    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")
        # The completed discovery queues an answer on its own; the paused reading is set up once nothing else runs.
        deadline = time.time() + 30
        while time.time() < deadline:
            runs = client.get(f"/api/researches/{rid}").json()["runs"]
            if all(run["status"] in ("completed", "failed", "paused", "cancelled") for run in runs):
                break
            time.sleep(0.1)
        run_id = discovery_run(store, rid)["id"]
        store.update_run(run_id, status="paused", pause_reason="backend_restarted")

        assert table_rows.advance(store, rid) == []
        assert not [row for row in store.conn.execute(
            "SELECT 1 FROM runs WHERE research_id = ? AND kind = 'table_fill' AND status = 'queued'", (rid,))]
        # Resuming the paused reading is what must stay possible.
        assert client.post(f"/api/runs/{run_id}/resume").status_code in (200, 202)


def test_nothing_is_opened_when_the_automatic_study_table_is_off(tmp_path):
    """A person who turned the automatic study table off gets no table and no column call from the reading either."""
    adapter = ColumnAdapter()
    settings = sw_settings(tmp_path)  # study_table is off here
    app = create_app(settings, adapters={"fake": adapter}, http_client=openalex_client(200), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_to_end(client, rid, "discovery")

        assert steps(store, "code:study_table_open") == []
        assert table_open.chain_table(store, rid) is None
        assert not [row for row in store.conn.execute("SELECT 1 FROM evidence_tables WHERE research_id = ?", (rid,))]
        assert "table_columns" not in {task for task, *_ in adapter.sent}


def test_a_persons_table_of_the_same_name_is_not_adopted(tmp_path):
    """Ownership is what the app wrote, not a title: a person's table made from the research keeps its own columns."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        # Same title, and it follows the research's sources, exactly like the app's own.
        theirs = TableStore(store).create_table(rid, table_open.TITLE, None, None, None)

        run_to_end(client, rid, "discovery")

        opened = table_open.chain_table(store, rid)
        assert opened is not None and opened != theirs
        assert not TableStore(store)._columns(theirs)

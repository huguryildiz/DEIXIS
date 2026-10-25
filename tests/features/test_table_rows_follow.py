"""D63: a table made from the included sources follows them: rows for sources included later, filled by the ordinary
fill path; rows of sources excluded later stay, marked, and are left out of the report.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows workflow behavior, not reading quality.
"""

import hashlib
import time

import pytest

from deixis.workflow.features.tables import table_rows
from deixis.workflow.features.report.report_snapshot import build_snapshot
from deixis.workflow.features.tables.tables import report_ready
from deixis.workflow.features.tables.tables import InvalidTableInput
from test_evidence_tables import PACKET_SIZE
from test_table_extraction import add_pdf, cell, execute, fill, library, table_version


def include_later(lib, title="D SYNTHETIC later study", text="SYNTHETIC later study: packets of 256 bytes were sent.", pdf=True):
    time.sleep(0.005)  # row and run times have millisecond resolution
    svid = lib.store.create_upload_source(title)
    if pdf:
        add_pdf(lib.store, svid, [text], hashlib.sha256(title.encode()).hexdigest())
    else:
        lib.store._insert_passage(svid, None, "abstract", None, None, "provider", None, None, text)
    lib.store.add_to_corpus(lib.rid, svid, "user_upload", selection_state="included", selection_origin="user")
    return svid


def select(lib, svid, state):
    version = lib.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                               (lib.rid, svid)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, svid, state, version, "SYNTHETIC reason")


def view(lib, tid=None):
    return lib.tables.table_view(lib.rid, tid or lib.tid)


def missing_sources(lib):
    return {m["source_version_id"] for m in report_ready(lib.store, lib.rid, lib.tid)["missing"]}


def extraction_sources(lib, run_id):
    """The sources whose extraction calls a run sent, one entry per call, from its stored steps."""
    return [key.split(":")[1] for (key,) in lib.conn.execute(
        "SELECT operation_key FROM run_steps WHERE run_id = ? AND kind = 'model:cell_extraction' AND status = 'succeeded'"
        " ORDER BY rowid", (run_id,))]


def test_a_source_included_later_gets_a_row_that_fills_itself(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    version = table_version(lib)
    new = include_later(lib)
    assert new not in missing_sources(lib)  # included, but not yet a row: not in the table's report (D68)

    (run,) = table_rows.advance(lib.store)
    rows = {r["source_version_id"]: r for r in view(lib)["rows"]}
    assert rows[new]["added_by"] == "included_later" and table_version(lib) == version + 1
    assert lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'table_changed'"
                            " AND json_extract(payload_json, '$.rows_added') = 1").fetchone()[0] == 1
    assert run["kind"] == "table_fill" and run["target"]["auto_rows"] is True and run["target"]["included_only"] is True
    assert [s["source_version_id"] for s in run["target"]["sources"]] == [new]
    assert table_rows.advance(lib.store) == []  # its own run is queued; nothing is planned twice

    assert execute(lib, run)["status"] == "completed"
    assert extraction_sources(lib, run["id"]) == [new]
    assert cell(lib, new)["current"]["kind"] == "model_fill"
    assert new not in missing_sources(lib)
    assert table_rows.advance(lib.store) == [] and len(view(lib)["rows"]) == 4


def test_a_row_a_person_removed_is_not_added_back_and_a_hand_picked_table_does_not_follow(tmp_path):
    lib = library(tmp_path)
    hand = lib.tables.create_table(lib.rid, "Hand-picked", [lib.published], None, None)
    lib.tables.remove_row(lib.rid, lib.tid, lib.preprint, table_version(lib))
    new = include_later(lib)

    assert table_rows.add_rows(lib.store) == {lib.tid: [new]}
    assert lib.preprint in {r["source_version_id"] for r in view(lib)["removed_rows"]}
    assert [r["source_version_id"] for r in view(lib, hand)["rows"]] == [lib.published]
    assert table_rows.add_rows(lib.store) == {}
    # A row a person removed is not the report's, so it no longer keeps the report waiting (D68).
    assert lib.preprint not in missing_sources(lib)


def test_a_source_excluded_later_keeps_its_row_marked_and_is_left_out_of_the_report(tmp_path):
    lib = library(tmp_path)
    assert lib.preprint in {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid)["sources"]}
    select(lib, lib.preprint, "excluded")
    # The app's own fills skip it; a person's fill still may read it.
    assert lib.preprint not in {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid, included_only=True)["sources"]}
    assert lib.preprint in {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid)["sources"]}

    row = next(r for r in view(lib)["rows"] if r["source_version_id"] == lib.preprint)
    assert row["selection_state"] == "excluded"
    assert lib.preprint not in missing_sources(lib)
    snapshot = build_snapshot(lib.store, lib.rid, lib.tid)
    assert lib.preprint not in {r["source_version_id"] for r in snapshot["rows"]}
    assert snapshot["left_out_rows"] == [{"source_version_id": lib.preprint, "selection_state": "excluded"}]

    # A row the app added whose source is excluded before its fill is queued is not filled.
    new = include_later(lib)
    table_rows.add_rows(lib.store)
    select(lib, new, "excluded")
    assert table_rows.advance(lib.store) == []


def test_an_app_fill_does_not_start_a_source_excluded_after_it_was_planned(tmp_path):
    lib = library(tmp_path)
    run = lib.tables.request_fill(lib.rid, lib.tid, None, False, table_version(lib), None, included_only=True)
    assert {s["source_version_id"] for s in run["target"]["sources"]} == {lib.published, lib.preprint, lib.no_text}
    select(lib, lib.published, "excluded")
    select(lib, lib.no_text, "excluded")
    assert execute(lib, run)["status"] == "completed"
    assert extraction_sources(lib, run["id"]) == [lib.preprint]
    assert cell(lib, lib.published)["current"] is None and cell(lib, lib.no_text)["current"] is None
    assert not lib.conn.execute("SELECT 1 FROM run_steps WHERE run_id = ? AND operation_key LIKE ?",
                                (run["id"], f"%{lib.published}%")).fetchone()  # no step waits for it


def row_ids(tables, rid, tid):
    return {r["source_version_id"] for r in tables.table_view(rid, tid)["rows"]}


def test_rows_take_active_members_included_or_not_and_refuse_removed_ones(tmp_path):
    lib = library(tmp_path)
    store, tables, conn = lib.store, lib.tables, lib.conn
    excluded = store.create_upload_source("D SYNTHETIC excluded report")
    store.add_to_corpus(lib.rid, excluded, "user_upload", selection_state="excluded", selection_origin="user")
    store.remove_sources(lib.rid, [lib.no_text], "SYNTHETIC scan")
    count = lambda: conn.execute("SELECT COUNT(*) FROM evidence_tables").fetchone()[0]  # noqa: E731
    before = count()

    for rows in ([lib.published, lib.no_text], [lib.published, "srv_missing"]):
        with pytest.raises(InvalidTableInput):
            tables.create_table(lib.rid, "Chosen", rows, None, None)
    assert count() == before  # nothing half-made

    tid = tables.create_table(lib.rid, "Chosen", [lib.published, excluded, lib.published], None, "chosen-1")
    assert row_ids(tables, lib.rid, tid) == {lib.published, excluded}
    assert {r[0] for r in conn.execute("SELECT added_by FROM table_rows WHERE table_id = ?", (tid,))} == {"user"}
    assert tables.create_table(lib.rid, "Chosen", [lib.published, excluded], None, "chosen-1") == tid
    assert count() == before + 1

    version = tables.table_view(lib.rid, tid)["table"]["version"]
    with pytest.raises(InvalidTableInput):
        tables.add_rows(lib.rid, tid, [lib.preprint, lib.no_text], version)
    assert row_ids(tables, lib.rid, tid) == {lib.published, excluded}
    assert tables.table_view(lib.rid, tid)["table"]["version"] == version
    tables.add_rows(lib.rid, tid, [lib.preprint], version)
    assert row_ids(tables, lib.rid, tid) == {lib.published, excluded, lib.preprint}


def test_an_exclusion_between_two_calls_of_one_source_stops_the_second(tmp_path):
    lib = library(tmp_path)
    for n in range(8):  # nine columns: two extraction calls for each source with text
        lib.tables.add_column(lib.rid, lib.tid, PACKET_SIZE | {"name": f"Packet size {n}"}, table_version(lib), None)
    select(lib, lib.preprint, "excluded")
    run = lib.tables.request_fill(lib.rid, lib.tid, None, False, table_version(lib), None, included_only=True)
    done = []

    def exclude_after_first(si):
        if si["task_type"] == "cell_extraction" and not done:
            done.append(True)
            select(lib, lib.published, "excluded")  # the first row in table order (the preprint is excluded)
    lib.adapter.before = exclude_after_first
    assert execute(lib, run)["status"] == "completed"
    assert extraction_sources(lib, run["id"]) == [lib.published]  # its second call was not sent
    assert sum(si["task_type"] == "cell_extraction" for si in lib.adapter.calls) == 1

"""D63: a table made from the included sources follows them: rows for sources included later, filled by the ordinary
fill path; rows of sources excluded later stay, marked, and are left out of the report.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows workflow behavior, not reading quality.
"""

import hashlib
import shutil
import time

from deixis.storage import db
from deixis.workflow import table_rows
from deixis.workflow.report.snapshot import build_snapshot
from deixis.workflow.store import Store
from deixis.workflow.tables import report_ready
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
    assert new in missing_sources(lib)  # included, but not a row: the report is refused today

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
    # Unchanged rule: a removed row of an included source still keeps the report waiting.
    assert lib.preprint in missing_sources(lib)


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


def test_snapshot_without_left_out_rows_keeps_its_earlier_shape(tmp_path):
    lib = library(tmp_path)
    assert "left_out_rows" not in build_snapshot(lib.store, lib.rid, lib.tid)


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


def test_a_paused_run_does_not_hold_the_rows_or_their_fill_and_an_active_one_delays_only_the_fill(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    other = lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, lib.published, cell(lib, lib.published)["version"], None)
    new = include_later(lib)
    assert table_rows.advance(lib.store) == []  # another run is queued: the row is added, the fill waits
    assert new in {r["source_version_id"] for r in view(lib)["rows"]}

    lib.store.update_run(other["id"], status="paused")
    (run,) = table_rows.advance(lib.store)
    assert [s["source_version_id"] for s in run["target"]["sources"]] == [new]

    lib.store.update_run(run["id"], status="failed")
    assert table_rows.advance(lib.store) == []  # planned once since the row was added: not queued again
    assert cell(lib, new)["current"] is None and view(lib)["fill_estimate"]["sources"] == 1  # a person fills it


def test_only_columns_older_than_the_row_or_accepted_by_the_chain_are_filled_by_themselves(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    new = include_later(lib)
    table_rows.add_rows(lib.store)
    time.sleep(0.005)
    person = lib.tables.add_column(lib.rid, lib.tid, PACKET_SIZE | {"name": "A person's column"}, table_version(lib), None)
    chain = lib.tables.add_column(lib.rid, lib.tid, PACKET_SIZE | {"name": "A chain column"}, table_version(lib), None,
                                  accepted_by="automatic")
    (run,) = table_rows.advance(lib.store)
    (planned,) = run["target"]["sources"]
    assert planned["source_version_id"] == new and set(planned["column_ids"]) == {lib.cid, chain}
    assert person not in planned["column_ids"]


def test_more_due_rows_than_one_run_reads_move_on_after_a_failed_run(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    new = [include_later(lib, f"SYNTHETIC later study {n:02}", f"SYNTHETIC abstract {n}: packets of {n} bytes.", pdf=False)
           for n in range(27)]
    (first,) = table_rows.advance(lib.store)
    assert len(first["target"]["sources"]) == 25
    lib.store.update_run(first["id"], status="failed")
    (second,) = table_rows.advance(lib.store)
    assert {s["source_version_id"] for s in second["target"]["sources"]} == set(new) - {
        s["source_version_id"] for s in first["target"]["sources"]}


def test_the_migration_marks_tables_made_from_the_included_sources(tmp_path, monkeypatch):
    earlier = tmp_path / "migrations"
    earlier.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 19:
            shutil.copy(path, earlier / path.name)
    conn = db.connect(tmp_path / "library.sqlite")
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", earlier)
        db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC migration question", "attached", "quick", [], "fake", "fake-model", None)
    svid = store.create_upload_source("SYNTHETIC migrated source")
    for tid, added_by in (("tbl_SYNTHincl0001", "included_at_creation"), ("tbl_SYNTHhand0001", "user"), ("tbl_SYNTHnone0001", None)):
        conn.execute("INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES (?, ?, 'T', 't', 't')",
                     (tid, rid))
        if added_by:
            conn.execute("INSERT INTO table_rows (table_id, source_version_id, added_by, created_at, removed_at)"
                         " VALUES (?, ?, ?, 't', ?)", (tid, svid, added_by, "r" if added_by == "user" else None))
    conn.commit()

    assert db.migrate(conn) == [19]
    assert dict(conn.execute("SELECT id, follows_included FROM evidence_tables").fetchall()) == {
        "tbl_SYNTHincl0001": 1, "tbl_SYNTHhand0001": 0, "tbl_SYNTHnone0001": 0}
    assert [tuple(r) for r in conn.execute("SELECT table_id, added_by, created_at, removed_at FROM table_rows ORDER BY table_id")] == [
        ("tbl_SYNTHhand0001", "user", "t", "r"), ("tbl_SYNTHincl0001", "included_at_creation", "t", None)]
    conn.execute("INSERT INTO table_rows (table_id, source_version_id, added_by, created_at) VALUES ('tbl_SYNTHnone0001', ?,"
                 " 'included_later', 't')", (svid,))


def test_an_exclusion_during_one_equation_read_stops_the_next_sources_reads(tmp_path):
    lib = library(tmp_path)
    add_pdf(lib.store, lib.preprint, ["SYNTHETIC preprint page: packets of 64 bytes."], "7" * 64)
    asset = {svid: lib.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()[0]
             for svid in (lib.published, lib.preprint)}
    read = []

    class Service:
        def available(self):
            return True

        async def read_asset(self, asset_id, run_id=None):
            read.append(asset_id)
            select(lib, lib.preprint, "excluded")  # excluded while the published version's equations are read
            return {"state": "read"}

    lib.flow.deps.equations = Service()
    run = lib.tables.request_fill(lib.rid, lib.tid, None, False, table_version(lib), None, included_only=True)
    assert execute(lib, run)["status"] == "completed"
    assert read == [asset[lib.published]]
    assert lib.store.existing_step(run["id"], f"equations:{asset[lib.preprint]}") is None
    assert extraction_sources(lib, run["id"]) == [lib.published]

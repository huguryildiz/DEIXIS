import sqlite3

import pytest

from deixis.storage import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield connection
    connection.close()


def _source(conn, sid="srv_1"):
    conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_1', 'now')")
    conn.execute(
        "INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES (?, 'wrk_1', 'T', 'provider', 'now')",
        (sid,),
    )


def test_abstract_passage_cannot_carry_a_pdf_page(conn):
    _source(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO passages (id, source_version_id, kind, physical_page, abstract_origin, text, text_sha256, retrieved_at, created_at)"
            " VALUES ('psg_1', 'srv_1', 'abstract', 3, 'provider_openalex_inverted_index', 'x', 'h', 'now', 'now')"
        )


def test_passage_text_is_immutable_and_indexed(conn):
    _source(conn)
    conn.execute(
        "INSERT INTO passages (id, source_version_id, kind, abstract_origin, text, text_sha256, retrieved_at, created_at)"
        " VALUES ('psg_1', 'srv_1', 'abstract', 'provider_openalex_inverted_index', 'molecular diffusion channel', 'h', 'now', 'now')"
    )
    hit = conn.execute(
        "SELECT p.id FROM passages_fts f JOIN passages p ON p.rowid = f.rowid WHERE passages_fts MATCH 'diffusion'"
    ).fetchall()
    assert [r[0] for r in hit] == ["psg_1"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE passages SET text = 'changed' WHERE id = 'psg_1'")


def test_step_inputs_are_immutable(conn):
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 't', 'now', 'now')")
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_1', 'res_1', 1, 'answer', 'running', 'answer', '{}', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_1', 'run_1', 'answer', 'grounded_answer', 'running')"
    )
    conn.execute(
        "INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type, scope_revision, skill_package_hash,"
        " payload_json, base_instructions, developer_instructions, user_message, output_schema_json, created_at)"
        " VALUES ('sti_1', 'stp_1', 'res_1', 'run_1', 0, 'grounded_answer', 1, 'h', '{}', 'b', 'd', 'u', '{}', 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE step_inputs SET payload_json = '{\"x\":1}' WHERE id = 'sti_1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM step_inputs WHERE id = 'sti_1'")


import errno
import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as launcher
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db, upgrades
from deixis.storage.upgrades import Step
from fakes import FakeAdapter
from old_library import stand_in_schema
from test_restore_matrix import fake_uvicorn, free_port, settings_for  # noqa: F401  (fake_uvicorn is a fixture)

FIRST = "CREATE TABLE first_table (value TEXT);\n"
HALF_APPLIED = "CREATE TABLE half_table (value TEXT);\nINSERT INTO no_such_table VALUES (1);\n"
TWO_TABLES = "CREATE TABLE half_table (value TEXT);\nCREATE TABLE after_table (value TEXT);\n"


def library_with_first_migration(tmp_path, monkeypatch):
    stand_in_schema(monkeypatch, tmp_path / "schema", FIRST)
    path = tmp_path / "data" / "library.sqlite"
    conn = db.connect(path)
    assert db.migrate(conn) == [1]
    conn.execute("INSERT INTO first_table VALUES ('SYNTHETIC row')")
    conn.close()
    return upgrades.STEPS, path


def snapshot(path):
    """Everything the library holds, as SQL text and rows, read through a fresh connection."""
    conn = sqlite3.connect(path)
    try:
        return (conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall(),
                conn.execute("SELECT version, name FROM schema_migrations").fetchall(),
                conn.execute("SELECT * FROM first_table").fetchall())
    finally:
        conn.close()


class FullDisk:
    """A connection that works until a statement mentions `trigger`, then reports a full disk the way the OS does."""

    def __init__(self, conn, trigger):
        self.conn, self.trigger = conn, trigger

    def execute(self, sql, *args):
        if self.trigger in sql:
            raise OSError(errno.ENOSPC, "SYNTHETIC no space left on device")
        return self.conn.execute(sql, *args)

    @property
    def in_transaction(self):
        return self.conn.in_transaction


def test_a_full_disk_during_a_migration_is_undone_and_says_to_free_space(tmp_path, monkeypatch):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    before = snapshot(path)
    steps[2] = Step("0002_full.sql", False, TWO_TABLES)
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed) as caught:
        db.migrate(FullDisk(conn, "after_table"))
    conn.close()
    assert caught.value.code == "migration_failed" and caught.value.disk_full
    assert isinstance(caught.value.__cause__, OSError) and caught.value.__cause__.errno == errno.ENOSPC
    text = str(caught.value)
    assert "0002_full.sql" in text and "database or disk is full" in text
    assert "Free some disk space" in text and "Traceback" not in text
    assert snapshot(path) == before


def test_serve_exits_4_with_the_backup_sentence_when_a_migration_fails(tmp_path, monkeypatch, capsys, fake_uvicorn):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    steps[2] = Step("0002_half.sql", False, HALF_APPLIED)
    before = snapshot(path)
    monkeypatch.setattr(launcher, "create_app", lambda *a, **k: pytest.fail("the app was created"))
    assert launcher.serve(settings_for(path.parent, free_port()), False, ()) == launcher.EXIT_MIGRATION_FAILED == 4
    err = capsys.readouterr().err
    assert "0002_half.sql" in err and "deixis restore" in err and "Traceback" not in err
    assert fake_uvicorn.instances == []
    assert snapshot(path) == before


import sqlite3

import pytest

from deixis.storage import db
from old_library import PRE_SQUASH as OLD, apply_files, old_library


def library(path, paths):
    conn = db.connect(path)
    apply_files(conn, paths)
    return conn


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def versions(conn):
    return [tuple(row) for row in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version")]


@pytest.mark.parametrize("ran", [1])
def test_a_library_that_stopped_part_way_through_the_old_files_is_refused_unchanged(tmp_path, ran):
    path = tmp_path / "library.sqlite"
    library(path, sorted(OLD.glob("*.sql"))[:ran]).close()
    before = path.read_bytes()

    with pytest.raises(db.UnknownSchemaError, match="before 16 October 2026") as caught:
        db.connect(path)
    assert db.SQUASHED[ran + 1] in str(caught.value)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        assert len(versions(conn)) == ran


from dataclasses import replace

from fastapi.testclient import TestClient

from deixis.providers import openalex
from deixis.storage import db
from deixis.storage.db import now
from deixis.workflow.store import Store
from test_api_flow import app_for, session

WORK = {
    "id": "https://openalex.org/W900", "doi": "https://doi.org/10.1/retracted", "display_name": "SYNTHETIC retracted study",
    "publication_year": 2020, "type": "article", "authorships": [{"author": {"display_name": "A. Author"}}],
    "primary_location": {"version": "publishedVersion", "source": {"display_name": "Synthetic J"}},
    "abstract_inverted_index": {"Packets": [0], "flow.": [1]}, "cited_by_count": 3,
}


def flag(store, svid):
    return tuple(store.conn.execute("SELECT is_retracted, is_retracted_at FROM source_versions WHERE id = ?", (svid,)).fetchone())


def test_only_an_explicit_answer_replaces_the_stored_flag(tmp_path):
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    record = openalex._record({**WORK, "is_retracted": True})
    svid, created = store.upsert_provider_source("openalex", record, None)
    assert created and flag(store, svid)[0] == 1 and flag(store, svid)[1] is not None
    # A later read with no boolean (another provider, or OpenAlex without the field) leaves it as it was.
    store.upsert_provider_source("openalex", replace(record, is_retracted=None), None)
    store.upsert_provider_source("crossref", replace(record, provider_record_id="10.1/retracted", is_retracted=None), None)
    assert flag(store, svid)[0] == 1
    store.upsert_provider_source("openalex", replace(record, is_retracted=False), None)
    assert flag(store, svid)[0] == 0
    unknown, _ = store.upsert_provider_source("openalex", openalex._record({**WORK, "id": "W901", "doi": None}), None)
    assert flag(store, unknown) == (None, None)


import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage import db
from fakes import FakeAdapter
from test_api_flow import app_for, session
from test_followup_turns import answered, research
import json
from deixis.storage.backup import BackupError
from deixis.storage.backup import create_backup
from helpers import make_pdf
from test_api_flow import create
from test_api_flow import wait_run

def test_a_published_turn_is_never_edited_or_deleted_and_its_links_are_append_only(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert turn["status"] == "answered"
        conn = app.state.store.conn
        with pytest.raises(sqlite3.IntegrityError, match="published once"):
            conn.execute("UPDATE followup_turns SET status = 'not_answered' WHERE id = ?", (turn["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
            conn.execute("DELETE FROM followup_turns WHERE id = ?", (turn["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE followup_turn_links SET anchor_text = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
            conn.execute("DELETE FROM followup_turn_links")
        link = dict(conn.execute("SELECT * FROM followup_turn_links").fetchone())
        with pytest.raises(sqlite3.IntegrityError, match="published valid answer of the same StepInput"):
            conn.execute("INSERT INTO followup_turn_links (id, turn_id, claim_label, passage_id, source_version_id,"
                         " step_input_id, support_type, anchor_text, anchor_match) VALUES ('ful_x', ?, 'c9', ?, ?,"
                         " 'sti_other', 'source_stated', 'x', 'exact')",
                         (turn["id"], link["passage_id"], link["source_version_id"]))
        # A pending row may not claim to be published without its time.
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at)"
                         " VALUES ('fut_y', ?, 1, 'SYNTHETIC?', ?, 'answered', 'now')", (rid, turn["run"]["id"] + "x"))


# T15 (P4 part): a backup taken while the server runs restores selections, human edits, answers and referenced files.

def build_library(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        relay = next(s for s in view["sources"] if "relay" in s["title"])
        client.patch(f"/api/researches/{rid}/selections/{relay['source_version_id']}",
                     json={"state": "excluded", "expected_version": relay["selection"]["version"], "reason": "not about scheduling"})
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded notes."]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        wait_run(client, rid, run["id"])
        backup_dir = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")  # server still running
        view = client.get(f"/api/researches/{rid}").json()
        assets = {a["id"]: client.get(f"/api/researches/{rid}/assets/{a['id']}").content
                  for s in view["sources"] for a in s["access"]["assets"]}
    return rid, view, assets, backup_dir


def test_backup_fails_without_leaving_a_partial_folder_when_a_file_is_missing(tmp_path):
    _, _, _, backup_dir = build_library(tmp_path)
    next((tmp_path / "data" / "papers").iterdir()).unlink()
    with pytest.raises(BackupError, match="missing"):
        create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "later")
    assert not (tmp_path / "later").exists() or not any((tmp_path / "later").iterdir())

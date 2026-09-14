import sqlite3

import pytest

from deixis.storage import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield connection
    connection.close()


def test_migration_is_idempotent_and_enables_foreign_keys(conn):
    assert db.migrate(conn) == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES ('srv_x', 'wrk_missing', 't', 'provider', 'now')"
        )


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

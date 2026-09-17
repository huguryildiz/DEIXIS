"""Report migration coverage on synthetic, temporary libraries."""

import shutil
import sqlite3

from deixis.storage import db


PRE_REPORT_KINDS = (
    "discovery", "answer", "table_columns", "table_fill", "cell_recheck",
    "research_title", "pdf_collection", "pdf_ocr",
)
REPORT_TABLES = {
    "reports", "report_sections", "report_claims", "report_claim_refs",
    "report_citation_links", "report_gaps", "report_snapshot", "report_phrase_repairs",
}
PRE_SECTION_II_IDS = ("I", "III", "IV", "V", "VI", "VII", "VIII", "IX", "abstract", "index_terms")


def test_report_migration_preserves_all_existing_run_kinds(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 35:
            shutil.copy(path, migrations / path.name)
    report_migration = db.MIGRATIONS_DIR / "0035_report_run_kind.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    for kind in PRE_REPORT_KINDS:
        conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES (?, 'res_test', 1, ?, 'queued', 'synthesis', '{}', 'now', 'now')",
            (f"run_{kind}", kind),
        )
    shutil.copy(report_migration, migrations / report_migration.name)
    assert db.migrate(conn) == [35]
    assert {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= REPORT_TABLES
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_report', 'res_test', 1, 'report', 'queued', 'synthesis', '{}', 'now', 'now')"
    )
    assert {row["kind"] for row in conn.execute("SELECT kind FROM runs")} == {*PRE_REPORT_KINDS, "report"}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with sqlite3.connect(tmp_path / "library.sqlite") as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == len(PRE_REPORT_KINDS) + 1


def test_report_section_ii_migration_preserves_existing_sections_and_enables_ii(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 36:
            shutil.copy(path, migrations / path.name)
    section_migration = db.MIGRATIONS_DIR / "0036_report_section_ii.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_report', 'res_test', 1, 'report', 'queued', 'synthesis', '{}', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO reports (id, research_id, run_id, scope_revision, status, created_at, updated_at)"
        " VALUES ('rpt_test', 'res_test', 'run_report', 1, 'in_progress', 'now', 'now')"
    )
    for ordinal, section_id in enumerate(PRE_SECTION_II_IDS):
        conn.execute(
            "INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at)"
            " VALUES (?, 'rpt_test', ?, 'pending', ?, 'now', 'now')",
            (f"rsc_{ordinal}", section_id, ordinal),
        )

    shutil.copy(section_migration, migrations / section_migration.name)
    assert db.migrate(conn) == [36]
    assert [row[0] for row in conn.execute("SELECT section_id FROM report_sections ORDER BY ordinal")] == \
        list(PRE_SECTION_II_IDS)
    conn.execute(
        "INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at)"
        " VALUES ('rsc_ii', 'rpt_test', 'II', 'valid', 2, 'now', 'now')"
    )
    assert conn.execute("SELECT section_id FROM report_sections WHERE id = 'rsc_ii'").fetchone()[0] == "II"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

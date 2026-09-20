"""Report migration coverage on synthetic, temporary libraries."""

import shutil
import sqlite3

import pytest

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


def test_protocol_migration_keeps_existing_scope_revisions_on_the_legacy_workflow(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 37:
            shutil.copy(path, migrations / path.name)
    protocol_migration = db.MIGRATIONS_DIR / "0037_protocol_records.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    conn.execute(
        "INSERT INTO scope_revisions (research_id, revision, question, source_scope, providers_json, effort,"
        " model_connection, created_at) VALUES ('res_test', 1, 'SYNTHETIC question', 'academic', '[]', 'quick', 'fake', 'now')"
    )

    shutil.copy(protocol_migration, migrations / protocol_migration.name)
    assert db.migrate(conn) == [37]
    assert conn.execute("SELECT search_workflow FROM scope_revisions WHERE research_id = 'res_test'").fetchone()[0] == "legacy"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


SELECTION_ROW = ("res_test", "srv_test", "included", "model_proposal", "kept by the user", "include",
                 "SYNTHETIC proposal reason", "abstract", "stp_test", 4, "now")


def test_stage_decision_migration_rebuilds_selections_without_losing_a_row(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 38:
            shutil.copy(path, migrations / path.name)
    decision_migration = db.MIGRATIONS_DIR / "0038_stage_decisions.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_test', 'now')")
    conn.execute(
        "INSERT INTO source_versions (id, work_id, title, origin, created_at)"
        " VALUES ('srv_test', 'wrk_test', 'SYNTHETIC record', 'provider', 'now')"
    )
    for extra in ("srv_other", "srv_third"):
        conn.execute(
            "INSERT INTO source_versions (id, work_id, title, origin, created_at)"
            " VALUES (?, 'wrk_test', 'SYNTHETIC record', 'provider', 'now')", (extra,)
        )
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_test', 'res_test', 1, 'discovery', 'queued', 'discovery', '{}', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_test', 'run_test', 'screening:0', 'screening', 'succeeded')"
    )
    conn.execute(
        "INSERT INTO selections (research_id, source_version_id, state, origin, user_reason, proposal, proposal_reason,"
        " proposal_basis, proposal_step_id, version, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", SELECTION_ROW
    )
    before = dict(conn.execute("SELECT * FROM selections").fetchone())
    before_columns = [tuple(row) for row in conn.execute("PRAGMA table_info(selections)")]

    shutil.copy(decision_migration, migrations / decision_migration.name)
    assert db.migrate(conn) == [38]
    assert dict(conn.execute("SELECT * FROM selections").fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM selections").fetchone()[0] == 1
    # Every column keeps its name, declared type, not-null flag, default and key position; only the origin CHECK changed.
    assert [tuple(row) for row in conn.execute("PRAGMA table_info(selections)")] == before_columns
    assert "code_rule" in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'selections'").fetchone()[0]
    conn.execute(
        "INSERT INTO selections (research_id, source_version_id, state, origin, version, updated_at)"
        " VALUES ('res_test', 'srv_other', 'pending', 'code_rule', 1, 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO selections (research_id, source_version_id, state, origin, version, updated_at)"
            " VALUES ('res_test', 'srv_third', 'pending', 'invented', 1, 'now')"
        )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_stage_decision_migration_adds_the_three_tables_with_their_guards(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    columns = lambda table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    assert columns("stage_decisions") >= {"id", "research_id", "source_version_id", "stage", "outcome", "reason_code",
                                          "decided_by", "next_step", "note", "scope_revision", "protocol_hash",
                                          "criterion_hash", "step_id", "superseded_at", "created_at"}
    assert columns("model_proposals") >= {"id", "research_id", "source_version_id", "stage", "step_id", "run_no",
                                          "criterion_part", "label", "quote", "quote_verified", "quote_passage_id",
                                          "quote_page", "created_at"}
    assert columns("record_signal_ranks") == {"ranking_step_id", "research_id", "source_version_id", "signal", "rank",
                                              "available"}
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_test', 'now')")
    conn.execute(
        "INSERT INTO source_versions (id, work_id, title, origin, created_at)"
        " VALUES ('srv_test', 'wrk_test', 'SYNTHETIC record', 'provider', 'now')"
    )
    decision = ("INSERT INTO stage_decisions (id, research_id, source_version_id, stage, outcome, reason_code,"
                " decided_by, next_step, scope_revision, created_at) VALUES (?, 'res_test', 'srv_test', ?, ?, 'c', 'code', 'none', 1, 'now')")
    with pytest.raises(sqlite3.IntegrityError):  # an abstract decision cannot carry a full-text outcome
        conn.execute(decision, ("dec_bad", "abstract", "include"))
    conn.execute(decision, ("dec_one", "abstract", "candidate"))
    with pytest.raises(sqlite3.IntegrityError):  # one current decision per record and stage
        conn.execute(decision, ("dec_two", "abstract", "out_of_scope"))
    conn.execute("UPDATE stage_decisions SET superseded_at = 'now' WHERE id = 'dec_one'")
    conn.execute(decision, ("dec_two", "abstract", "out_of_scope"))
    with pytest.raises(sqlite3.IntegrityError):  # a decision is deleted only under a purge authorization
        conn.execute("DELETE FROM stage_decisions WHERE id = 'dec_two'")
    assert conn.execute("SELECT COUNT(*) FROM stage_decisions").fetchone()[0] == 2


def test_record_link_migration_keeps_one_open_row_per_ordered_pair(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    assert {row[1] for row in conn.execute("PRAGMA table_info(record_links)")} == {
        "id", "source_version_id", "other_source_version_id", "link_kind", "rule", "source",
        "parent_source_version_id", "title_similarity", "abstract_similarity", "author_agreement", "year_gap",
        "merged", "undo_json", "closed_at", "closed_reason", "closed_note", "created_at"}
    conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_test', 'now')")
    for svid in ("srv_a", "srv_b"):
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, created_at)"
                     " VALUES (?, 'wrk_test', 'SYNTHETIC record', 'provider', 'now')", (svid,))
    link = ("INSERT INTO record_links (id, source_version_id, other_source_version_id, link_kind, rule, source,"
            " author_agreement, merged, created_at) VALUES (?, ?, ?, 'related_suspected', 'two_published', 'text',"
            " 'agree', 0, 'now')")
    with pytest.raises(sqlite3.IntegrityError):  # the pair is always stored with the smaller identifier on the left
        conn.execute(link, ("lnk_reversed", "srv_b", "srv_a"))
    conn.execute(link, ("lnk_one", "srv_a", "srv_b"))
    with pytest.raises(sqlite3.IntegrityError):  # one open link per pair
        conn.execute(link, ("lnk_two", "srv_a", "srv_b"))
    with pytest.raises(sqlite3.IntegrityError):  # a closed row says why it closed
        conn.execute("UPDATE record_links SET closed_at = 'now' WHERE id = 'lnk_one'")
    conn.execute("UPDATE record_links SET closed_at = 'now', closed_reason = 'superseded' WHERE id = 'lnk_one'")
    conn.execute(link, ("lnk_two", "srv_a", "srv_b"))  # a closed row leaves room for a new open one
    assert conn.execute("SELECT COUNT(*) FROM record_links").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):  # the link kinds are a closed list
        conn.execute("UPDATE record_links SET link_kind = 'invented' WHERE id = 'lnk_two'")
    conn.execute("DELETE FROM record_links")  # links carry no research, so a purge deletes them with the record
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_search_run_paging_migration_leaves_existing_rows_without_a_page(tmp_path, monkeypatch):
    """The page columns are new; a search recorded before slice 04c has no page number and no stop reason."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 41:
            shutil.copy(path, migrations / path.name)
    paging_migration = db.MIGRATIONS_DIR / "0041_search_run_pages.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_test', 'res_test', 1, 'discovery', 'completed', 'screening', '{}', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_test', 'run_test', 'search:0',"
        " 'provider_search:openalex', 'succeeded')"
    )
    conn.execute(
        "INSERT INTO search_runs (id, research_id, run_id, step_id, provider, query_text, request_description,"
        " access_mode, status, result_count, page_limit, retrieved_at)"
        " VALUES ('srn_test', 'res_test', 'run_test', 'stp_test', 'openalex', 'q', 'GET test', 'keyless', 'completed',"
        " 4, 25, 'now')"
    )

    shutil.copy(paging_migration, migrations / paging_migration.name)
    assert db.migrate(conn) == [41]
    row = conn.execute("SELECT page_number, read_limit, read_total, stop_reason, unread_count FROM search_runs"
                       " WHERE id = 'srn_test'").fetchone()
    assert tuple(row) == (None, None, None, None, None)
    assert conn.execute("SELECT result_count FROM search_runs WHERE id = 'srn_test'").fetchone()[0] == 4
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

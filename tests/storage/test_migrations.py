"""Report migration coverage on synthetic, temporary libraries."""

import shutil
import sqlite3
import re

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
# Every run kind the database held before the full-text retrieval run was added (slice 10, migration 0045).
PRE_FULLTEXT_KINDS = (*PRE_REPORT_KINDS, "report")


@pytest.mark.parametrize("populated", [False, True])
def test_claim_links_migration_preserves_pre_0062_rows_and_legacy_citations(tmp_path, monkeypatch, populated):
    real = db.MIGRATIONS_DIR
    migrations = tmp_path / "claim-link-migrations"
    migrations.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 61:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    fixture = None
    if populated:
        from tests.report.test_report_assembly import report_with_sections
        fixture = report_with_sections.__wrapped__(tmp_path)
        lib = next(fixture)
        conn = lib["store"].conn
        cid = conn.execute("SELECT id FROM report_claims WHERE claim_key = 'III.1'").fetchone()[0]
        conn.execute("INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at, idempotency_key)"
                     " VALUES ('rcv_legacy', ?, 'human_edit', 'SYNTHETIC legacy', '2026-10-01', 'legacy-key')", (cid,))
        conn.execute("UPDATE report_claims SET current_revision_id = 'rcv_legacy', version = 2 WHERE id = ?", (cid,))
    else:
        conn = db.connect(tmp_path / "library.sqlite")
        db.migrate(conn)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'schema_migrations'")]
        columns = {table: [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')] for table in tables}
        def existing_rows():
            return {table: sorted((tuple(row) for row in conn.execute(
                f'SELECT {", ".join(columns[table])} FROM "{table}"')), key=repr) for table in tables}
        before = existing_rows()
        shutil.copy(real / "0062_report_claim_links.sql", migrations / "0062_report_claim_links.sql")
        assert db.migrate(conn) == [62]
        assert existing_rows() == before
        assert conn.execute("SELECT * FROM report_claim_revision_links").fetchall() == []
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'report_claim_revision_links'").fetchone()[0].endswith("WITHOUT ROWID")
        if populated:
            assert conn.execute("SELECT link_count, request_hash FROM report_claim_revisions").fetchone()[:] == (None, None)
            expected = [row[0] for row in conn.execute("SELECT id FROM report_citation_links ORDER BY rowid")]
            assert [row["id"] for row in lib["reports"].effective_links(lib["report_id"])] == expected
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at, link_count)"
                             " VALUES ('rcv_negative', ?, 'human_edit', 'bad', 'today', -1)", (cid,))
    finally:
        if fixture:
            with pytest.raises(StopIteration):
                next(fixture)
        else:
            conn.close()


@pytest.mark.parametrize("populated", [False, True])
def test_edit_check_migration_preserves_pre_0061_library_and_foreign_keys(tmp_path, monkeypatch, populated):
    real = db.MIGRATIONS_DIR
    migrations = tmp_path / "edit-check-migrations"
    migrations.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 60:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    if populated:
        from tests.report.test_report_assembly import report_with_sections
        fixture = report_with_sections.__wrapped__(tmp_path)
        lib = next(fixture)
        conn = lib["store"].conn
    else:
        conn = db.connect(tmp_path / "library.sqlite")
        db.migrate(conn)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'schema_migrations'")]
        def rows():
            return {t: sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{t}"')), key=repr) for t in tables}
        before = rows()
        shutil.copy(real / "0061_report_edit_checks.sql", migrations / "0061_report_edit_checks.sql")
        assert db.migrate(conn) == [61]
        assert rows() == before
        assert conn.execute("SELECT * FROM report_edit_checks").fetchall() == []
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        if populated:
            shutil.copy(real / "0062_report_claim_links.sql", migrations / "0062_report_claim_links.sql")
            assert db.migrate(conn) == [62]
            from tests.report.test_report_edit_check import finish, check
            finish(lib)
            check(lib)
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute("DELETE FROM report_edit_checks")
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute("UPDATE report_edit_checks SET result_json = '{}'")
            rid = lib["reports"].report(lib["report_id"])["research_id"]
            lib["store"].trash_research(rid)
            lib["store"].purge_research(rid)
            assert conn.execute("SELECT * FROM report_edit_checks").fetchall() == []
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        if populated:
            with pytest.raises(StopIteration):
                next(fixture)
        else:
            conn.close()


@pytest.mark.parametrize("populated", [True, False], ids=["all_pre_0060_kinds_and_dependents", "empty_pre_0060"])
def test_the_candidate_migration_keeps_every_run_and_every_row_that_points_at_one(tmp_path, monkeypatch, populated):
    from deixis.workflow.store import Store
    from deixis.workflow.lineage.store import LineageStore
    real = db.MIGRATIONS_DIR
    migrations = tmp_path / "candidate-migrations"
    migrations.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 59:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    old_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0]
    kinds = re.findall(r"'([^']+)'", re.search(r"kind IN \(([^)]+)\)", old_sql).group(1))
    tables = ("runs", "run_steps", "cell_revisions", "lineage_link_revisions")
    if populated:
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'SYNTHETIC', 'now', 'now')")
        statuses = ("queued", "running", "pause_requested", "paused", "completed", "failed", "cancelled")
        for n, kind in enumerate(kinds):
            conn.execute(
                "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,"
                " usage_json, idempotency_key, target_json, version, created_at, updated_at)"
                " VALUES (?, 'res_test', ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"run_{kind}", n + 1, kind, statuses[n % len(statuses)], f"SYNTHETIC-pause-{n}", '{"SYNTHETIC_error":1}',
                 '{"limit":7}', '{"input_tokens":19}', f"SYNTHETIC-key-{n}", '{"candidate_id":"rcd_SYNTHETIC","extra":42}',
                 n + 5, f"created-{n}", f"updated-{n}"))
        conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_test', 'now')")
        for svid in ("srv_test", "srv_other"):
            conn.execute("INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES (?, 'wrk_test', 'SYNTHETIC', 'provider', 'now')", (svid,))
        conn.execute("INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES ('tbl_test', 'res_test', 'SYNTHETIC', 'now', 'now')")
        conn.execute("INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES ('col_test', 'tbl_test', 0, 'user', 'now')")
        conn.execute("INSERT INTO evidence_cells (id, table_id, column_id, source_version_id, created_at, updated_at) VALUES ('cel_test', 'tbl_test', 'col_test', 'srv_test', 'now', 'now')")
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, started_at) VALUES ('stp_test', 'run_answer', 'SYNTHETIC', 'SYNTHETIC', 'running', 'now')")
        conn.execute("INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, state, run_id, created_at) VALUES ('crv_test', 'cel_test', 'human_edit', 'human', 1, 'unknown', 'run_answer', 'now')")
        pair = LineageStore(Store(conn)).ensure_link("tbl_test", "srv_test", "srv_other")
        conn.execute(
            "INSERT INTO lineage_link_revisions (id, link_id, kind, author, decision, disposition, relation, what_changed,"
            " support_type, origin, run_id, created_at)"
            " VALUES ('llr_test', ?, 'human_add', 'human', 'link', 'accepted', 'extends', 'SYNTHETIC',"
            " 'source_stated', 'human', 'run_lineage_links', 'now')", (pair["id"],))
    before = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in tables}
    shutil.copy(real / "0060_candidates.sql", migrations / "0060_candidates.sql")
    assert db.migrate(conn) == [60]
    assert {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in tables} == before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs_status'").fetchone()[0] == "CREATE INDEX runs_status ON runs(status, created_at)"
    if not populated:
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'SYNTHETIC', 'now', 'now')")
    for kind in ("claim_decomposition", "kill_search"):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES (?, 'res_test', 1, ?, 'queued', 'candidate', '{}', 'now', 'now')", (f"run_new_{kind}", kind))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_unknown', 'res_test', 1, 'invented', 'queued', 'candidate', '{}', 'now', 'now')")
    conn.close()


def test_candidate_python_vocabularies_equal_the_real_sql_check_lists(tmp_path):
    from deixis.workflow.candidates import store as c
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    for table, columns in (
        ("research_candidates", {"origin": c.ORIGINS}),
        ("candidate_versions", {"origin": c.VERSION_ORIGINS}),
        ("claim_elements", {"kind": c.ELEMENT_KINDS}),
        ("kill_searches", {"outcome": c.OUTCOMES}),
        ("kill_search_queries", {"status": c.QUERY_STATUSES}),
        ("kill_search_hits", {"reading_depth": c.READING_DEPTHS, "assessment_state": c.ASSESSMENT_STATES,
                              "work_relevance": c.WORK_RELEVANCES}),
        ("claim_matrix_cells", {"relation": c.RELATIONS, "condition_alignment": c.ALIGNMENTS}),
        ("claim_matrix_evidence", {"evidence_kind": c.EVIDENCE_KINDS}),
        ("candidate_status_overrides", {"status": c.STATUSES}),
    ):
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        for column, vocabulary in columns.items():
            check = re.search(rf"CHECK \((?:{column} IS NULL OR )?{column} IN \(([^)]+)\)\)", sql).group(1)
            assert tuple(re.findall(r"'([^']+)'", check)) == vocabulary
    conn.close()


@pytest.mark.parametrize("populated", [True, False], ids=["all_old_run_kinds_and_dependents", "empty_pre_P6_copy"])
def test_the_lineage_migration_keeps_every_run_and_every_row_that_points_at_one(tmp_path, monkeypatch, populated):
    real = db.MIGRATIONS_DIR
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 58:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    old_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0]
    kinds = re.findall(r"'([^']+)'", re.search(r"kind IN \(([^)]+)\)", old_sql).group(1))
    dependent_tables = ("run_steps", "cell_revisions", "chain_links")
    if populated:
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'SYNTHETIC', 'now', 'now')")
        statuses = ("queued", "running", "pause_requested", "paused", "completed", "failed", "cancelled")
        for n, kind in enumerate(kinds):
            conn.execute(
                "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,"
                " usage_json, idempotency_key, target_json, version, created_at, updated_at)"
                " VALUES (?, 'res_test', ?, ?, ?, 'synthesis', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"run_{kind}", n + 1, kind, statuses[n % len(statuses)], f"pause-{n}", '{"SYNTHETIC_error": 1}',
                 '{"limit": 7}', '{"input_tokens": 19}', f"SYNTHETIC-key-{n}", '{"table_id":"tbl_test","extra":42}', n + 5,
                 f"created-{n}", f"updated-{n}"),
            )
        conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_test', 'now')")
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES ('srv_test', 'wrk_test', 'SYNTHETIC', 'provider', 'now')")
        conn.execute("INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES ('tbl_test', 'res_test', 'SYNTHETIC', 'now', 'now')")
        conn.execute("INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES ('col_test', 'tbl_test', 0, 'user', 'now')")
        conn.execute("INSERT INTO evidence_cells (id, table_id, column_id, source_version_id, created_at, updated_at) VALUES ('cel_test', 'tbl_test', 'col_test', 'srv_test', 'now', 'now')")
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, started_at) VALUES ('stp_test', 'run_answer', 'SYNTHETIC', 'SYNTHETIC', 'running', 'now')")
        conn.execute("INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, state, run_id, created_at) VALUES ('crv_test', 'cel_test', 'human_edit', 'human', 1, 'unknown', 'run_answer', 'now')")
        conn.execute("INSERT INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id, linked_openalex_id, direction, passed_filter) VALUES ('res_test', 1, 'run_discovery', 'srv_test', 'W_SYNTHETIC', 'backward', 0)")
    before = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in ("runs", *dependent_tables)}
    shutil.copy(real / "0059_lineage_links.sql", migrations / "0059_lineage_links.sql")
    assert db.migrate(conn) == [59]
    assert {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in before} == before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs_status'").fetchone()[0] == "CREATE INDEX runs_status ON runs(status, created_at)"
    if not populated:
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'SYNTHETIC', 'now', 'now')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_lineage', 'res_test', 1, 'lineage_links', 'queued', 'synthesis', '{}', 'now', 'now')")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_unknown', 'res_test', 1, 'invented', 'queued', 'synthesis', '{}', 'now', 'now')")
    conn.close()


def test_lineage_vocabularies_equal_the_real_sql_check_lists(tmp_path):
    from deixis.workflow.lineage.store import RELATIONS, SUPPORT_TYPES, DECISIONS, REVISION_KINDS, REJECTION_CODES

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'lineage_link_revisions'").fetchone()[0]
    for column, values in (("relation", RELATIONS), ("support_type", SUPPORT_TYPES), ("decision", DECISIONS), ("kind", REVISION_KINDS)):
        check = re.search(rf"CHECK \({column} IN \(([^)]+)\)\)", sql).group(1)
        assert tuple(re.findall(r"'([^']+)'", check)) == values
    assert REJECTION_CODES == ("cycle", "anchor_not_found", "same_work", "endpoint_not_included", "superseded_by_human", "stale_input")
    assert "CHECK (rejection_code IN" not in sql
    conn.close()


def test_migration_adds_role_column_and_partial_unique_index(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    real = db.MIGRATIONS_DIR
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 57:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Synthetic', 'now', 'now')")
    for tid in ("tbl_one", "tbl_two"):
        conn.execute("INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES (?, 'res_test', 'Synthetic', 'now', 'now')", (tid,))
    for cid in ("col_old", "col_other"):
        conn.execute("INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES (?, 'tbl_one', 0, 'user', 'now')", (cid,))
        conn.execute("INSERT INTO column_revisions (column_id, revision, name, instruction, answer_format, created_at) VALUES (?, 1, 'Synthetic', 'Record the source', 'text', 'now')", (cid,))
    shutil.copy(real / "0058_lineage_role.sql", migrations / "0058_lineage_role.sql")
    assert db.migrate(conn) == [58]
    assert [r[0] for r in conn.execute("SELECT lineage_role FROM table_columns")] == [None, None]
    index = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'table_columns_lineage_role'").fetchone()[0]
    assert "UNIQUE INDEX" in index and "(table_id, lineage_role)" in index
    assert "WHERE lineage_role IS NOT NULL AND removed_at IS NULL" in index
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE table_columns SET lineage_role = 'invented' WHERE id = 'col_old'")
    conn.execute("UPDATE table_columns SET lineage_role = 'problem' WHERE id = 'col_old'")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("UPDATE table_columns SET lineage_role = 'problem' WHERE id = 'col_other'")
    conn.execute("UPDATE table_columns SET removed_at = 'now' WHERE id = 'col_old'")
    conn.execute("UPDATE table_columns SET lineage_role = 'problem' WHERE id = 'col_other'")
    conn.execute("INSERT INTO table_columns (id, table_id, position, origin, created_at, lineage_role) VALUES ('col_elsewhere', 'tbl_two', 0, 'user', 'now', 'problem')")
    assert conn.execute("SELECT COUNT(*) FROM table_columns WHERE lineage_role = 'problem'").fetchone()[0] == 3
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


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


def test_the_fulltext_fetch_migration_keeps_every_run_it_found_and_accepts_the_new_kind(tmp_path, monkeypatch):
    """Migration 0045 rebuilds `runs` to widen its CHECK; the rows already there must survive it (D83)."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 45:
            shutil.copy(path, migrations / path.name)
    fulltext_migration = db.MIGRATIONS_DIR / "0045_fulltext_fetch_run_kind.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    for kind in PRE_FULLTEXT_KINDS:
        conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES (?, 'res_test', 1, ?, 'queued', 'synthesis', '{}', 'now', 'now')",
            (f"run_{kind}", kind),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES ('run_early', 'res_test', 1, 'fulltext_fetch', 'queued', 'inspection', '{}', 'now', 'now')"
        )
    shutil.copy(fulltext_migration, migrations / fulltext_migration.name)
    assert db.migrate(conn) == [45]
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_fulltext', 'res_test', 1, 'fulltext_fetch', 'queued', 'inspection', '{}', 'now', 'now')"
    )
    assert {row["kind"] for row in conn.execute("SELECT kind FROM runs")} == {*PRE_FULLTEXT_KINDS, "fulltext_fetch"}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with sqlite3.connect(tmp_path / "library.sqlite") as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == len(PRE_FULLTEXT_KINDS) + 1


# Every run kind the database held before the full-text reading run was added (slice 12, migration 0046).
PRE_ADJUDICATION_KINDS = (*PRE_FULLTEXT_KINDS, "fulltext_fetch")


def test_the_adjudication_migration_keeps_every_run_it_found_and_accepts_the_new_kind(tmp_path, monkeypatch):
    """Migration 0046 rebuilds `runs` to widen its CHECK; the rows already there must survive it (D85)."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 46:
            shutil.copy(path, migrations / path.name)
    adjudication_migration = db.MIGRATIONS_DIR / "0046_fulltext_adjudication_run_kind.sql"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Test', 'now', 'now')")
    for kind in PRE_ADJUDICATION_KINDS:
        conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES (?, 'res_test', 1, ?, 'queued', 'inspection', '{}', 'now', 'now')",
            (f"run_{kind}", kind),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES ('run_early', 'res_test', 1, 'fulltext_adjudication', 'queued', 'inspection', '{}', 'now', 'now')"
        )
    shutil.copy(adjudication_migration, migrations / adjudication_migration.name)
    assert db.migrate(conn) == [46]
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_reading', 'res_test', 1, 'fulltext_adjudication', 'queued', 'inspection', '{}', 'now', 'now')"
    )
    assert {row["kind"] for row in conn.execute("SELECT kind FROM runs")} == {*PRE_ADJUDICATION_KINDS, "fulltext_adjudication"}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with sqlite3.connect(tmp_path / "library.sqlite") as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == len(PRE_ADJUDICATION_KINDS) + 1


def test_the_europepmc_migration_keeps_every_pdf_lookup_row_and_accepts_the_new_provider_and_status(tmp_path, monkeypatch):
    """0055 (SW21, D106): the two PDF lookup tables are rebuilt with Europe PMC and `wrong_type`; nothing is lost."""
    from deixis.documents.acquisition import Candidate, Lookup
    from deixis.documents.fetch import FetchResult
    from deixis.providers.common import ProviderRecord
    from deixis.workflow.store import Store

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 55:
            shutil.copy(path, migrations / path.name)
    real = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord("W1", "SYNTHETIC title", [], 2020, "J", "article", "10.1/x", None, None, None,
                            "publishedVersion", None, None, {}, {})
    svid, _ = store.upsert_provider_source("openalex", record, None)
    for provider in ("unpaywall", "openalex", "crossref", "core", "web_search"):
        candidate = Candidate(provider, f"https://{provider}.example/a.pdf", None, "publishedVersion", None,
                              "doi_verified", "match")
        run_id = store.record_pdf_discovery(rid, svid, provider, "10.1/x", Lookup("completed", [candidate], 200,
                                                                                  other_title_count=2))
        store.record_pdf_candidates(svid, run_id, [candidate])
    first = store.pdf_candidates(svid)[0]
    store.record_pdf_attempt(first["id"], FetchResult("not_pdf", final_url="https://unpaywall.example/a.pdf", http_status=200))
    before = {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
              for table in ("pdf_discovery_runs", "pdf_candidates")}
    with pytest.raises(sqlite3.IntegrityError):  # not accepted before 0055
        store.record_pdf_discovery(rid, svid, "europepmc", "10.1/x", Lookup("zero_results", [], 200))

    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    assert db.migrate(conn) == [55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71]
    after = {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
             for table in ("pdf_discovery_runs", "pdf_candidates")}
    assert after == before  # every row and column value kept, other_title_count included
    candidate = Candidate("europepmc", "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML", None,
                          "publishedVersion", None, "doi_verified", "match")
    run_id = store.record_pdf_discovery(rid, svid, "europepmc", "10.1/x", Lookup("completed", [candidate], 200))
    (row,) = [c for c in store.record_pdf_candidates(svid, run_id, [candidate]) if c["provider"] == "europepmc"]
    store.record_pdf_attempt(row["id"], FetchResult("wrong_type", final_url=candidate.url, media_type="text/html",
                                                    http_status=200))
    assert conn.execute("SELECT access_status FROM pdf_candidates WHERE id = ?", (row["id"],)).fetchone()[0] == "wrong_type"
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"pdf_discovery_source", "pdf_candidates_source"} <= names
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

"""Checks of the current schema (the baseline migration) on synthetic, temporary libraries."""

import sqlite3
import re

import pytest

from deixis.storage import db


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


def test_lineage_role_is_a_closed_list_and_unique_among_a_tables_open_columns(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_test', 'Synthetic', 'now', 'now')")
    for tid in ("tbl_one", "tbl_two"):
        conn.execute("INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES (?, 'res_test', 'Synthetic', 'now', 'now')", (tid,))
    for cid in ("col_old", "col_other"):
        conn.execute("INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES (?, 'tbl_one', 0, 'user', 'now')", (cid,))
        conn.execute("INSERT INTO column_revisions (column_id, revision, name, instruction, answer_format, created_at) VALUES (?, 1, 'Synthetic', 'Record the source', 'text', 'now')", (cid,))
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


def test_the_stage_decision_tables_exist_with_their_guards(tmp_path):
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


def test_record_links_keep_one_open_row_per_ordered_pair(tmp_path):
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

"""The owner review tables in the current schema: no hidden rowid, explicit foreign keys, Python vocabularies."""

import re
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.review.store import TARGET_KINDS, FOCUSES, DECISIONS


def test_all_four_tables_have_no_hidden_rowid_and_explicit_foreign_keys(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    expected = {"owner_review_snapshots": {("research_id", "researches", "id")},
                "owner_reviews": {("research_id", "researches", "id"), ("snapshot_id", "owner_review_snapshots", "id"), ("run_id", "runs", "id")},
                "owner_review_findings": {("review_id", "owner_reviews", "id"), ("step_input_id", "step_inputs", "id")},
                "owner_review_decisions": {("finding_id", "owner_review_findings", "id")}}
    try:
        for table, keys in expected.items():
            assert "WITHOUT ROWID" in conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            assert {(r[3], r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({table})")} == keys
            with pytest.raises(sqlite3.OperationalError, match="rowid"):
                conn.execute(f"INSERT OR REPLACE INTO {table} (rowid, id) VALUES (1, 'SYNTHETIC')")
    finally: conn.close()


def test_python_vocabularies_equal_sql_checks(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    try:
        for table, column, values in (("owner_review_snapshots", "target_kind", TARGET_KINDS), ("owner_reviews", "focus", FOCUSES), ("owner_review_decisions", "decision", DECISIONS)):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            assert tuple(re.findall(r"'([^']+)'", re.search(rf'{column} IN \(([^)]+)\)', sql).group(1))) == values
    finally: conn.close()

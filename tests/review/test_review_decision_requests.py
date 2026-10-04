"""Migration 0065 retains old immutable rows and closes conflicts on command keys."""

import shutil
import sqlite3

import pytest

from deixis.storage import db
from tests.review_helpers import report_with_sections, review_lib, stored_review, all_rows


def test_decision_request_migration_keeps_old_rows_and_exact_other_triggers(tmp_path, monkeypatch):
    real = db.MIGRATIONS_DIR
    old = tmp_path / "migrations"
    old.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name[:4]) <= 64:
            shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    gen = report_with_sections.__wrapped__(tmp_path)
    lib = review_lib.__wrapped__(next(gen))
    saved, review, payload, fid = stored_review(lib)
    # add_decision now needs the two new columns; insert an actual old row.
    lib["conn"].execute("INSERT INTO owner_review_decisions VALUES ('ord_SYNTHETIC', ?, 1, 'deferred', NULL, NULL, 'same')", (fid,))
    before = all_rows(lib["conn"])
    triggers = lambda: {r[0]: r[1] for r in lib["conn"].execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")}
    old_triggers = triggers()
    indexes = {r[0]: r[1] for r in lib["conn"].execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")}
    shutil.copy(real / "0065_owner_review_decision_requests.sql", old / "0065_owner_review_decision_requests.sql")
    assert db.migrate(lib["conn"]) == [65]
    after = all_rows(lib["conn"])
    assert after["owner_review_decisions"] == [row + (None, None) for row in before["owner_review_decisions"]]
    assert {t: after[t] for t in before if t not in {"owner_review_decisions", "schema_migrations"}} == {
        t: rows for t, rows in before.items() if t not in {"owner_review_decisions", "schema_migrations"}}
    new_triggers = triggers()
    replaced = "owner_review_decisions_no_conflicting_insert"
    assert set(new_triggers) == set(old_triggers)
    assert {k: v for k, v in new_triggers.items() if k != replaced} == {k: v for k, v in old_triggers.items() if k != replaced}
    assert new_triggers[replaced] != old_triggers[replaced]
    new_indexes = {r[0]: r[1] for r in lib["conn"].execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")}
    assert {k: new_indexes[k] for k in indexes} == indexes
    assert set(new_indexes) - set(indexes) == {"owner_review_decisions_request"}
    assert lib["conn"].execute("PRAGMA foreign_key_check").fetchall() == []
    gen.close()


@pytest.mark.parametrize("form", ["INSERT", "INSERT OR REPLACE", "UPSERT"])
def test_decision_request_key_refuses_conflicting_insert_replace_upsert_recursive_triggers_off(review_lib, form):
    lib = review_lib
    _, review, payload, fid = stored_review(lib)
    old = lib["reviews"].add_decision(fid, "deferred", idempotency_key="SYNTHETIC-key", request_hash="0" * 64)
    conn = lib["conn"]
    conn.execute("PRAGMA recursive_triggers = OFF")
    before = all_rows(conn)["owner_review_decisions"]
    new = old | {"id": "ord_ANOTHER0001", "ordinal": 2, "decision": "accepted", "reason": "SYNTHETIC different reason", "request_hash": "1" * 64}
    sql = ("INSERT" if form == "UPSERT" else form) + f" INTO owner_review_decisions ({','.join(new)}) VALUES ({','.join('?' for _ in new)})"
    if form == "UPSERT":
        sql += " ON CONFLICT(idempotency_key) DO UPDATE SET id = excluded.id, decision = excluded.decision"
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        conn.execute(sql, tuple(new.values()))
    assert all_rows(conn)["owner_review_decisions"] == before

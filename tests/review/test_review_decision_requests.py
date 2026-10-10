"""Owner review decisions close conflicts on command keys."""

import sqlite3

import pytest

from tests.review.review_helpers import report_with_sections, review_lib, stored_review, all_rows


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

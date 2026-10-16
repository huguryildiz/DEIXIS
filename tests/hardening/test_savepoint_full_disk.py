"""P9 H7 item 02 (D165): a full disk inside a candidate or lineage savepoint keeps its own error. SYNTHETIC, no model, no network."""

import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.candidates.store import CandidateStore
from deixis.workflow.lineage.store import LineageStore
from test_lineage_store import make_library


# ---- item 02: a full disk inside a savepoint is reported as a full disk, not as "no such savepoint" --------------------

def fill_until_full(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS h7_junk (x BLOB)")
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    conn.execute(f"PRAGMA max_page_count = {pages + 3}")
    for _ in range(200):
        conn.execute("INSERT INTO h7_junk VALUES (?)", (b"x" * 50_000,))


def savepoint_cases(lib):
    return {"candidates": CandidateStore(lib.store)._transaction, "lineage": LineageStore(lib.store)._proposal_transaction}


@pytest.mark.parametrize("which", ["candidates", "lineage"])
def test_a_full_disk_in_a_savepoint_helper_keeps_its_own_error(tmp_path, which):
    lib = make_library(tmp_path / "library.sqlite")
    helper = savepoint_cases(lib)[which]
    with pytest.raises(sqlite3.OperationalError) as caught:
        with db.transaction(lib.conn):
            with helper():
                fill_until_full(lib.conn)
    assert "disk is full" in str(caught.value) and "savepoint" not in str(caught.value)
    assert db.describe_failure(caught.value)[0] == "disk_full"  # the API answers 507 with its sentence
    assert not lib.conn.in_transaction


@pytest.mark.parametrize("which", ["candidates", "lineage"])
def test_an_ordinary_failure_in_a_savepoint_helper_still_undoes_only_its_own_writes(tmp_path, which):
    lib = make_library(tmp_path / "library.sqlite")
    helper = savepoint_cases(lib)[which]
    lib.conn.execute("CREATE TABLE h7_keep (x TEXT)")
    with db.transaction(lib.conn):
        lib.conn.execute("INSERT INTO h7_keep VALUES ('outer')")
        with pytest.raises(ValueError):
            with helper():
                lib.conn.execute("INSERT INTO h7_keep VALUES ('inner')")
                raise ValueError("a caught failure")
        assert lib.conn.in_transaction
    assert [r[0] for r in lib.conn.execute("SELECT x FROM h7_keep")] == ["outer"]

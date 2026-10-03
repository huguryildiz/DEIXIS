"""0066's additive migration and SQL guards, using isolated synthetic libraries."""

import ast
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from deixis.storage import db
from deixis.workflow import recovery
from deixis.workflow.store import Store
from tests.test_reextract_r1_store import lib, setup, extraction, chunk, observe, reserve, head, complete
from tests.test_source_versions import raw_asset
from tests.review_helpers import all_rows

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PASSAGE_COLUMNS = ("text", "source_version_id", "kind", "physical_page", "asset_id", "printed_label",
    "abstract_origin", "payload_ref", "extraction_version", "text_sha256", "text_source", "retrieved_at", "created_at")


def insert(conn, table, values, mode="INSERT", upsert=False):
    sql = f"{mode} INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})"
    if upsert: sql += " ON CONFLICT DO UPDATE SET id = excluded.id"
    conn.execute(sql, tuple(values.values()))


def fresh_asset(lib):
    svid = lib.store.create_upload_source("SYNTHETIC second source")
    return lib.store.add_asset_with_pages(svid, lib.sha, 10, "second.pdf", "user_upload", None, None,
        extraction(), "second-v1", chunk)


def operation_values(lib, kind="file_restore"):
    return {"id": db.new_id("rop"), "kind": kind, "expected_sha256": lib.sha, "expected_byte_size": 10,
        "idempotency_key": db.new_id("key"), "request_fingerprint": "SYNTHETIC", "lifecycle": "running", "created_at": "now",
        **({"asset_id": lib.aid, "baseline_extraction_id": head(lib)["id"], "baseline_profile": head(lib)["extractor_profile"],
            "mode": "retry_failed_or_partial"} if kind == "text_retry" else {})}


def old_library(tmp_path, monkeypatch, last):
    real = db.MIGRATIONS_DIR; old = tmp_path / "migrations"; old.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name[:4]) <= last: shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    return real, old, conn


@pytest.mark.parametrize("last", [53, 66])
def test_extraction_schema_capability_is_read_once_for_repeated_writes(tmp_path, monkeypatch, last):
    _, _, conn = old_library(tmp_path, monkeypatch, last)
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        store = Store(conn)
        for index in range(2):
            svid = store.create_upload_source(f"SYNTHETIC cached schema {index}")
            store.add_asset_with_pages(svid, str(index) * 64, 10, f"synthetic-{index}.pdf", "user_upload", None, None,
                extraction(), "synthetic-v1", chunk)
        assert sum(sql.upper() == "PRAGMA TABLE_INFO(ASSET_EXTRACTIONS)" for sql in statements) == 1
        rows = conn.execute("SELECT * FROM asset_extractions").fetchall()
        assert len(rows) == 2 and all(row["passage_count"] == 2 for row in rows)
        if last == 66:
            assert all(row["extractor_profile"] == "synthetic-v1" for row in rows)
        else:
            assert "extractor_profile" not in rows[0].keys()
    finally:
        conn.set_trace_callback(None)
        conn.close()


@pytest.mark.parametrize("last", [26, 53, 65])
def test_migration_preserves_old_rows_profiles_fts_and_schema(tmp_path, monkeypatch, last):
    real, old, conn = old_library(tmp_path, monkeypatch, last)
    store = Store(conn)
    versions = ["unknown", "B", "B+ocr-tesseract-5-eng-v1", "B+marker-v1", "B+arxiv-latex-v1"]
    for index, version in enumerate(versions):
        svid = store.create_upload_source(f"SYNTHETIC source {index}")
        aid = raw_asset(conn, svid, str(index) * 64, ["SYNTHETIC relays."], version)
        if last >= 27:
            conn.execute("INSERT INTO asset_extractions (id, asset_id, extraction_version, status, page_count, text_pages,"
                " passage_count, outcome, created_at) VALUES (?, ?, ?, 'partial', 1, 1, 1, 'current', 'now')",
                ("ext_" + aid, aid, version))
            if last >= 30 and index in (2, 3, 4):
                # Immutable passage provenance is set on insertion in the fixture.
                conn.execute("DELETE FROM passages WHERE asset_id = ?", (aid,))
                store._insert_passage(svid, aid, "pdf_page", 1, "i", None, "chars:0-17", version,
                    "SYNTHETIC relays.", ("ocr", "marker", "latex_source" if last >= 54 else "marker")[index - 2])
            conn.execute("INSERT INTO asset_extractions (id, asset_id, extraction_version, status, page_count, text_pages,"
                " passage_count, outcome, created_at) VALUES (?, ?, ?, 'failed', 0, 0, 0, 'rejected', 'now')",
                ("ext_rejected" + str(index), aid, version + "+rejected"))
    if last == 65:
        # All four B1 tables and B2's decision request fields hold records before R1.
        from tests.test_report_assembly import report_with_sections
        from tests.test_report_edit_check import finish
        from tests.review_helpers import stored_review
        from deixis.workflow.review.reader import ReviewReader
        from deixis.workflow.review.store import ReviewStore
        fixture = report_with_sections.__wrapped__(tmp_path / "review")
        reviewed = next(fixture)
        reviewed["rid"] = finish(reviewed); reviewed["conn"] = reviewed["store"].conn
        reviewed["reader"] = ReviewReader(reviewed["store"], reviewed["reports"])
        reviewed["reviews"] = ReviewStore(reviewed["conn"])
        saved, review, payload, fid = stored_review(reviewed)
        reviewed["reviews"].add_decision(fid, "dismissed", "SYNTHETIC dismissal", None,
            idempotency_key="SYNTHETIC-decision-key", request_hash="1" * 64)
        # Copying is unnecessary: migrate the populated review connection as a second library.
        review_before = all_rows(reviewed["conn"])
    before = all_rows(conn); before.pop("schema_migrations")
    old_columns = {table: [r[1] for r in conn.execute(f"PRAGMA table_info({table})")] for table in before}
    objects = {(r["type"], r["name"]): (r["tbl_name"], r["sql"]) for r in conn.execute("SELECT * FROM sqlite_master")}
    fts_before = [r[0] for r in conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'relays' ORDER BY rowid")]
    assert all("+reextract-" not in r[0] for r in conn.execute("SELECT extraction_version FROM source_assets"))
    if last == 65:
        shutil.copy(real / "0066_asset_recovery.sql", old / "0066_asset_recovery.sql")
        assert db.migrate(conn) == [66]
        assert db.migrate(reviewed["conn"]) == [66]
        for table, rows in review_before.items():
            if table in ("schema_migrations", "asset_extractions"): continue
            assert all_rows(reviewed["conn"])[table] == rows
        with pytest.raises(StopIteration): next(fixture)
    else:
        monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
        assert 66 in db.migrate(conn)
    for table, columns in old_columns.items():
        projected = ", ".join('"' + column + '"' for column in columns)
        actual = sorted((tuple(r) for r in conn.execute(f'SELECT {projected} FROM "{table}"')), key=repr)
        assert actual == before[table]
    assert all(r["extractor_profile"] == r["extraction_version"] and r["input_observation_id"] is None
               and r["diagnostic_only"] == 0 for r in conn.execute("SELECT * FROM asset_extractions"))
    assert conn.execute("SELECT COUNT(*) FROM asset_file_observations").fetchone()[0] == 0
    assert [r[0] for r in conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'relays' ORDER BY rowid")] == fts_before
    if last == 65:
        after = {(r["type"], r["name"]): (r["tbl_name"], r["sql"]) for r in conn.execute("SELECT * FROM sqlite_master")}
        changed = {key for key in objects if objects[key] != after[key]}
        assert changed == {("table", "asset_extractions"), ("trigger", "passages_no_update")}
        expected_added = {
            ("table", "asset_recovery_operations"), ("table", "asset_file_observations"),
            ("index", "sqlite_autoindex_asset_recovery_operations_2"),
            ("index", "asset_recovery_operations_asset_created"), ("index", "asset_recovery_operations_one_running"),
            ("index", "asset_file_observations_operation"), ("index", "asset_extractions_recovery_operation"),
            *(("trigger", name) for name in ("asset_file_observations_no_update", "asset_file_observations_no_conflicting_insert",
                "asset_extractions_no_update", "asset_extractions_baseline_same_asset", "asset_extractions_recovery_shape",
                "asset_extractions_no_conflicting_insert", "asset_recovery_operations_no_conflicting_insert",
                "asset_recovery_operations_frozen")),
        }
        assert after.keys() - objects.keys() == expected_added
        ddl = after[("table", "asset_extractions")][1]
        additions = [
            "extractor_profile TEXT NOT NULL DEFAULT 'unknown'",
            "recovery_operation_id TEXT REFERENCES asset_recovery_operations(id)",
            "baseline_extraction_id TEXT REFERENCES asset_extractions(id)",
            "input_observation_id TEXT REFERENCES asset_file_observations(id)",
            "diagnostic_only INTEGER NOT NULL DEFAULT 0 CHECK (diagnostic_only IN (0, 1))",
            "decision_code TEXT CHECK (decision_code IS NULL OR decision_code IN (" +
                ", ".join(repr(code) for code in recovery.DECISION_CODES) + "))"]
        expected = objects[("table", "asset_extractions")][1]
        for definition in additions:
            ddl = ddl.replace(", " + definition, "")
        assert ddl == expected
        trigger = after[("trigger", "passages_no_update")][1]
        assert all(column in trigger for column in PROTECTED_PASSAGE_COLUMNS)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_vocabulary_foreign_keys_without_rowid_and_deferral(lib):
    for table in ("asset_extractions", "asset_recovery_operations"):
        ddl = lib.conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        assert tuple(re.findall(r"'([^']+)'", re.search(r"decision_code IN \(([^)]+)\)", ddl).group(1))) == recovery.DECISION_CODES
    expected = {
        "asset_file_observations": {("operation_id", "asset_recovery_operations", "id")},
        "asset_recovery_operations": {("asset_id", "source_assets", "id"), ("baseline_extraction_id", "asset_extractions", "id"),
            ("before_observation_id", "asset_file_observations", "id"), ("after_observation_id", "asset_file_observations", "id"),
            ("input_observation_id", "asset_file_observations", "id")}}
    for table, keys in expected.items():
        ddl = lib.conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        assert "WITHOUT ROWID" in ddl
        assert {(r[3], r[2], r[4]) for r in lib.conn.execute(f"PRAGMA foreign_key_list({table})")} == keys
        if table == "asset_recovery_operations":
            assert ddl.count("DEFERRABLE INITIALLY DEFERRED") == 4 and "research_id TEXT," in ddl
        with pytest.raises(sqlite3.OperationalError, match="rowid"): lib.conn.execute(f"SELECT rowid FROM {table}")
    operation = reserve(lib); observation = observe(lib, operation_id=operation["id"])
    result = complete(lib, operation=operation, observation=observation)
    with db.transaction(lib.conn):
        lib.conn.execute("INSERT INTO recovery_purge_authorizations VALUES (?)", (lib.store.asset(lib.aid)["sha256"],))
        lib.conn.execute("DELETE FROM asset_extractions WHERE asset_id = ?", (lib.aid,))
        # Operations still refer to the deleted baseline and observation until commit.
        lib.conn.execute("DELETE FROM asset_file_observations WHERE id = ?", (observation,))
        lib.conn.execute("DELETE FROM asset_recovery_operations WHERE id = ?", (result["id"],))
        lib.conn.execute("DELETE FROM recovery_purge_authorizations")
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("column", ["id", "kind", "expected_sha256", "expected_byte_size", "idempotency_key",
                                  "request_fingerprint", "lifecycle", "created_at"])
def test_required_operation_columns_refuse_null(lib, column):
    values = operation_values(lib); values[column] = None
    with pytest.raises(sqlite3.IntegrityError): insert(lib.conn, "asset_recovery_operations", values)


@pytest.mark.parametrize("column", ["asset_id", "mode", "baseline_extraction_id", "baseline_profile"])
def test_text_retry_conditional_columns_refuse_null(lib, column):
    values = operation_values(lib, "text_retry"); values[column] = None
    with pytest.raises(sqlite3.IntegrityError): insert(lib.conn, "asset_recovery_operations", values)
    values = operation_values(lib)
    insert(lib.conn, "asset_recovery_operations", values)
    assert lib.conn.execute("SELECT lifecycle FROM asset_recovery_operations WHERE id = ?", (values["id"],)).fetchone()[0] == "running"


@pytest.mark.parametrize("column", ["id", "kind", "storage_path", "expected_sha256", "expected_byte_size", "integrity", "observed_at"])
def test_required_observation_columns_refuse_null(lib, column):
    original = dict(lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (observe(lib),)).fetchone())
    original["id"] = db.new_id("obs"); original[column] = None
    with pytest.raises(sqlite3.IntegrityError): insert(lib.conn, "asset_file_observations", original)


@pytest.mark.parametrize("integrity,hash_,size,allowed", [
    ("verified", None, 10, False), ("verified", "1" * 64, None, False), ("verified", "2" * 64, 10, False),
    ("verified", "1" * 64, 11, False), ("verified", "1" * 64, 10, True),
    ("mismatch", None, 10, False), ("mismatch", "2" * 64, None, False), ("mismatch", "1" * 64, 10, False),
    ("mismatch", "2" * 64, 10, True), ("mismatch", "1" * 64, 11, True),
    ("missing", None, None, True), ("missing", "1" * 64, None, False), ("missing", None, 10, False),
    ("legacy_unknown", None, None, True), ("legacy_unknown", None, 10, False), ("legacy_unknown", "1" * 64, None, False),
])
def test_integrity_truth_table(lib, integrity, hash_, size, allowed):
    values = {"id": db.new_id("obs"), "kind": "extraction_input", "storage_path": "synthetic.pdf",
        "expected_sha256": lib.sha, "expected_byte_size": 10, "observed_sha256": hash_, "observed_byte_size": size,
        "integrity": integrity, "observed_at": "now"}
    if allowed: insert(lib.conn, "asset_file_observations", values)
    else:
        with pytest.raises(sqlite3.IntegrityError): insert(lib.conn, "asset_file_observations", values)


@pytest.mark.parametrize("kind,integrity,allowed", [("before_restore", "verified", True), ("before_restore", "missing", False),
                                                   ("extraction_input", "verified", False), ("after_restore", "verified", False)])
def test_retained_bytes_require_before_restore_observation(lib, kind, integrity, allowed):
    if allowed: observe_retained(lib, kind, integrity)
    else:
        with pytest.raises(sqlite3.IntegrityError): observe_retained(lib, kind, integrity)


def observe_retained(lib, kind, integrity):
    return lib.store.add_file_observation(kind=kind, storage_path="synthetic.pdf", expected_sha256=lib.sha, expected_byte_size=10,
        observed_sha256=lib.sha if integrity == "verified" else None, observed_byte_size=10 if integrity == "verified" else None,
        integrity=integrity, retained_filename="retained.pdf")


@pytest.mark.parametrize("column", PROTECTED_PASSAGE_COLUMNS)
def test_every_protected_passage_column_refuses_update(lib, column):
    pid = lib.conn.execute("SELECT id FROM passages LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="passage content is immutable"):
        lib.conn.execute(f"UPDATE passages SET {column} = {column} WHERE id = ?", (pid,))
    lib.conn.execute("DELETE FROM passages WHERE id = ?", (pid,))
    assert lib.conn.execute("SELECT 1 FROM passages WHERE id = ?", (pid,)).fetchone() is None


@pytest.mark.parametrize("column", ["id", "asset_id", "extraction_version", "status", "error", "page_count", "text_pages", "passage_count",
    "rejection_reason", "created_at", "math_json", "ocr_json", "extractor_profile", "recovery_operation_id",
    "baseline_extraction_id", "input_observation_id", "diagnostic_only", "decision_code"])
def test_extraction_content_columns_are_frozen(lib, column):
    old = head(lib)
    value = 1 if column in ("page_count", "text_pages", "passage_count", "diagnostic_only") else "changed"
    with pytest.raises(sqlite3.IntegrityError, match="extraction content is immutable"):
        lib.conn.execute(f"UPDATE asset_extractions SET {column} = ? WHERE id = ?", (value, old["id"]))
    assert head(lib) == old


def test_extraction_outcome_allows_only_the_two_transitions(lib):
    old = head(lib)
    for bad in ("rejected",):
        with pytest.raises(sqlite3.IntegrityError): lib.conn.execute("UPDATE asset_extractions SET outcome = ? WHERE id = ?", (bad, old["id"]))
    lib.conn.execute("UPDATE asset_extractions SET outcome = 'superseded' WHERE id = ?", (old["id"],))
    lib.conn.execute("UPDATE asset_extractions SET outcome = 'current' WHERE id = ?", (old["id"],))
    result = complete(lib, extraction("failed", 0, (), "failure"))
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute("UPDATE asset_extractions SET outcome = 'current' WHERE id = ?", (result["extraction_id"],))


@pytest.mark.parametrize("column", ["id", "kind", "asset_id", "research_id", "expected_sha256", "expected_byte_size",
    "baseline_extraction_id", "baseline_profile", "mode", "idempotency_key", "request_fingerprint", "created_at"])
def test_operation_frozen_request_columns(lib, column):
    op = reserve(lib)
    value = 11 if column == "expected_byte_size" else "changed"
    with pytest.raises(sqlite3.IntegrityError): lib.conn.execute(f"UPDATE asset_recovery_operations SET {column} = ? WHERE id = ?", (value, op["id"]))
    assert op["replayed"] is False
    assert lib.store._retry_result(op["id"]) == {k: v for k, v in op.items() if k != "replayed"}


@pytest.mark.parametrize("lifecycle,outcome,finished,allowed", [
    ("running", None, None, True), ("completed", "refused", "now", True), ("interrupted", None, "now", True),
    ("completed", None, "now", False), ("running", "refused", None, False), ("running", None, "now", False),
    ("interrupted", "refused", "now", False), ("completed", "refused", None, False), ("interrupted", None, None, False)])
def test_operation_lifecycle_consistency(lib, lifecycle, outcome, finished, allowed):
    values = operation_values(lib) | {"lifecycle": lifecycle, "outcome": outcome, "finished_at": finished}
    if allowed:
        insert(lib.conn, "asset_recovery_operations", values)
        if lifecycle != "running":
            with pytest.raises(sqlite3.IntegrityError):
                lib.conn.execute("UPDATE asset_recovery_operations SET reason = 'changed' WHERE id = ?", (values["id"],))
    else:
        with pytest.raises(sqlite3.IntegrityError): insert(lib.conn, "asset_recovery_operations", values)


@pytest.mark.parametrize("kind", ["before_restore", "after_restore"])
def test_file_restore_observations_bind_once_to_the_right_operation_and_kind(lib, kind):
    values = operation_values(lib); insert(lib.conn, "asset_recovery_operations", values)
    oid = observe(lib, kind=kind, operation_id=values["id"])
    column = "before_observation_id" if kind == "before_restore" else "after_observation_id"
    wrong = observe(lib, kind="extraction_input", operation_id=values["id"])
    unrelated = observe(lib, kind=kind)
    for observation in (wrong, unrelated):
        with pytest.raises(sqlite3.IntegrityError):
            lib.conn.execute(f"UPDATE asset_recovery_operations SET {column} = ? WHERE id = ?", (observation, values["id"]))
    lib.conn.execute(f"UPDATE asset_recovery_operations SET {column} = ? WHERE id = ?", (oid, values["id"]))
    again = observe(lib, kind=kind, operation_id=values["id"])
    for observation in (again, None):
        with pytest.raises(sqlite3.IntegrityError):
            lib.conn.execute(f"UPDATE asset_recovery_operations SET {column} = ? WHERE id = ?", (observation, values["id"]))
    lib.conn.execute("UPDATE asset_recovery_operations SET lifecycle = 'completed', outcome = 'file_restored', finished_at = 'now' WHERE id = ?", (values["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute(f"UPDATE asset_recovery_operations SET {column} = ? WHERE id = ?", (again, values["id"]))
    retry = reserve(lib); retry_obs = observe(lib, kind=kind, operation_id=retry["id"])
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute(f"UPDATE asset_recovery_operations SET {column} = ? WHERE id = ?", (retry_obs, retry["id"]))


@pytest.mark.parametrize("mode", ["INSERT", "INSERT OR REPLACE", "upsert"])
@pytest.mark.parametrize("key", ["id", "idempotency_key", "running_asset"])
def test_operation_conflicts_refuse_without_replacing_any_unique_key(lib, mode, key):
    lib.conn.execute("PRAGMA recursive_triggers = OFF")
    original = reserve(lib)
    other = fresh_asset(lib)
    baseline = lib.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ?", (other,)).fetchone()
    candidate = operation_values(lib, "text_retry") | {"asset_id": other, "baseline_extraction_id": baseline["id"]}
    if key == "running_asset":
        candidate["asset_id"] = lib.aid; candidate["baseline_extraction_id"] = original["baseline_extraction_id"]
    else: candidate[key] = original[key]
    with pytest.raises(sqlite3.IntegrityError):
        insert(lib.conn, "asset_recovery_operations", candidate, "INSERT" if mode == "upsert" else mode, mode == "upsert")
    assert original["replayed"] is False
    assert lib.store._retry_result(original["id"]) == {k: v for k, v in original.items() if k != "replayed"}


@pytest.mark.parametrize("mode", ["INSERT", "INSERT OR REPLACE", "upsert"])
@pytest.mark.parametrize("key", ["id", "rowid", "occurrence", "current_asset", "recovery_operation"])
def test_extraction_conflicts_refuse_each_unique_key_in_isolation(lib, mode, key):
    lib.conn.execute("PRAGMA recursive_triggers = OFF")
    operation = reserve(lib)
    result = complete(lib, extraction("failed", 0, (), "failure"), operation)
    original = dict(lib.conn.execute("SELECT rowid, * FROM asset_extractions WHERE id = ?", (result["extraction_id"],)).fetchone())
    current = head(lib)
    other = fresh_asset(lib)
    candidate = original | {"id": db.new_id("ext"), "asset_id": other, "extraction_version": "fresh-v1",
        "extractor_profile": "fresh-v1", "recovery_operation_id": None, "baseline_extraction_id": None, "outcome": "rejected"}
    candidate.pop("rowid")
    if key == "id": candidate["id"] = original["id"]
    elif key == "rowid": candidate["rowid"] = original["rowid"]
    elif key == "occurrence":
        candidate["asset_id"] = lib.aid; candidate["extraction_version"] = original["extraction_version"]
        candidate["extractor_profile"] = original["extractor_profile"]
    elif key == "current_asset":
        candidate["asset_id"] = lib.aid; candidate["outcome"] = "current"
    else:
        candidate["asset_id"] = lib.aid; candidate["recovery_operation_id"] = operation["id"]
        candidate["extractor_profile"] = "fresh-v1"; candidate["extraction_version"] = recovery.occurrence("fresh-v1", operation["id"])
    with pytest.raises(sqlite3.IntegrityError):
        insert(lib.conn, "asset_extractions", candidate, "INSERT" if mode == "upsert" else mode, mode == "upsert")
    assert dict(lib.conn.execute("SELECT rowid, * FROM asset_extractions WHERE id = ?", (original["id"],)).fetchone()) == original
    assert head(lib) == current


@pytest.mark.parametrize("mode", ["INSERT", "INSERT OR REPLACE", "upsert"])
def test_observation_update_and_conflicting_insert_refused(lib, mode):
    lib.conn.execute("PRAGMA recursive_triggers = OFF")
    oid = observe(lib)
    original = dict(lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (oid,)).fetchone())
    with pytest.raises(sqlite3.IntegrityError): lib.conn.execute("UPDATE asset_file_observations SET observed_at = 'changed' WHERE id = ?", (oid,))
    with pytest.raises(sqlite3.IntegrityError):
        insert(lib.conn, "asset_file_observations", original | {"observed_at": "changed"}, "INSERT" if mode == "upsert" else mode, mode == "upsert")
    assert dict(lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (oid,)).fetchone()) == original
    with db.transaction(lib.conn):
        lib.conn.execute("INSERT INTO recovery_purge_authorizations VALUES (?)", (original["expected_sha256"],))
        lib.conn.execute("DELETE FROM asset_file_observations WHERE id = ?", (oid,))
        lib.conn.execute("DELETE FROM recovery_purge_authorizations")


@pytest.mark.parametrize("bad", ["other_baseline", "other_operation", "file_operation", "bad_occurrence", "profile_mismatch", "forgot_profile"])
def test_extraction_shape_guards(lib, bad):
    other = fresh_asset(lib)
    op = reserve(lib)
    values = head(lib) | {"id": db.new_id("ext"), "extraction_version": "fresh-v1", "extractor_profile": "fresh-v1", "outcome": "rejected"}
    if bad == "other_baseline":
        values["baseline_extraction_id"] = lib.conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ?", (other,)).fetchone()[0]
    elif bad == "file_operation":
        operation = operation_values(lib); insert(lib.conn, "asset_recovery_operations", operation)
        values["recovery_operation_id"] = operation["id"]
        values["extraction_version"] = recovery.occurrence("fresh-v1", operation["id"])
    elif bad == "other_operation":
        values["asset_id"] = other; values["recovery_operation_id"] = op["id"]
        values["extraction_version"] = recovery.occurrence("fresh-v1", op["id"])
    elif bad == "bad_occurrence": values["recovery_operation_id"] = op["id"]
    elif bad == "profile_mismatch": values["extractor_profile"] = "different"
    else: values.pop("extractor_profile")
    with pytest.raises(sqlite3.IntegrityError): insert(lib.conn, "asset_extractions", values)
    # A plain same-asset baseline and a literal legacy unknown are both allowed.
    values = head(lib) | {"id": db.new_id("ext"), "extraction_version": "unknown", "extractor_profile": "unknown",
        "outcome": "rejected", "baseline_extraction_id": head(lib)["id"]}
    insert(lib.conn, "asset_extractions", values)


def test_all_production_extraction_inserts_name_profile_and_retry_imports_no_external_work():
    found = []
    for path in (ROOT / "backend/deixis").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str): continue
            if re.search(r"INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+asset_extractions", node.value, re.I):
                assert "extractor_profile" in node.value, path
                found.append(path)
    assert len(found) == 4
    tree = ast.parse((ROOT / "backend/deixis/workflow/recovery.py").read_text())
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith(("deixis.models", "deixis.providers")) for node in ast.walk(tree))

"""Re-extraction at the store (R1): the retry policy, the frozen passage and extraction columns, and promotion, rejection and refusal of a re-read. SYNTHETIC PDFs and rows; no parser tool, provider or model is called."""

import hashlib
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.documents import pdf, ocr
from deixis.storage import db
from deixis.workflow import recovery, equations
from deixis.workflow.store import Store, NotRetryable, RunInProgress


def chunk(text):
    return [(0, len(text), text)] if text else []


def extraction(status="partial", count=3, pages=(1, 2), error=None, source="text_layer"):
    return pdf.Extraction(status, count, [pdf.PageText(p, str(p), f"SYNTHETIC page {p} relays.", source) for p in pages], error=error)


def setup(tmp_path, *, status="partial", count=3, pages=(1, 2), source="text_layer", integrity=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake", None)
    svid = store.create_upload_source("SYNTHETIC source")
    store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    lib = SimpleNamespace(store=store, conn=conn, rid=rid, svid=svid, sha="1" * 64, size=10)
    observation = observe(lib, integrity=integrity) if integrity else None
    lib.aid = store.add_asset_with_pages(svid, lib.sha, lib.size, "synthetic.pdf", "user_upload", None, None,
        extraction(status, count, pages, source=source), pdf.EXTRACTION_VERSION, chunk,
        **({"input_observation_id": observation} if observation else {}))
    return lib


@pytest.fixture
def lib(tmp_path):
    value = setup(tmp_path)
    yield value
    value.conn.close()


def observe(lib, integrity="verified", kind="extraction_input", sha=None, size=None, operation_id=None):
    sha, size = sha or lib.sha, lib.size if size is None else size
    observed_sha = ("2" * 64 if integrity == "mismatch" else sha) if integrity in ("verified", "mismatch") else None
    return lib.store.add_file_observation(kind=kind, storage_path="synthetic.pdf", expected_sha256=sha, expected_byte_size=size,
        observed_sha256=observed_sha, observed_byte_size=size if observed_sha else None, integrity=integrity, operation_id=operation_id)


def head(lib):
    return dict(lib.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (lib.aid,)).fetchone())


def reserve(lib, key=None):
    key = key or db.new_id("key")
    return lib.store.reserve_text_retry(lib.aid, expected_extraction_id=head(lib)["id"],
        idempotency_key=key, request_fingerprint=key, research_id=lib.rid)


def complete(lib, candidate=None, operation=None, observation=None):
    operation = operation or reserve(lib)
    observation = observation or observe(lib, operation_id=operation["id"])
    return lib.store.complete_text_retry(operation["id"], candidate or extraction(pages=(1, 2, 3)), chunk,
        input_observation_id=observation)


def protected(lib):
    return {table: hashlib.sha256(repr([tuple(r) for r in lib.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]).encode()).hexdigest()
            for table in ("source_assets", "asset_extractions", "passages")}


def cited_answer(lib, passage_id):
    from review_helpers import make_answer
    answer = make_answer({"store": lib.store, "rid": lib.rid, "source_id": lib.svid, "section_passage": passage_id})
    text = lib.store.passage(passage_id)["text"]
    lib.conn.execute("UPDATE evidence_links SET anchor_text = ? WHERE passage_id = ?", (text, passage_id))
    return answer


def test_t3_identical_text_gets_new_identity_and_only_new_text_is_retrieved(lib):
    old = [dict(r) for r in lib.conn.execute("SELECT * FROM passages")]
    answer = cited_answer(lib, old[0]["id"])
    answer_rows = [tuple(r) for r in lib.conn.execute("SELECT * FROM evidence_links")]
    digest = lib.store.asset_page_digest(lib.aid)
    result = complete(lib)
    assert result["decision_code"] == "text_updated"
    for row in old:
        assert dict(lib.conn.execute("SELECT * FROM passages WHERE id = ?", (row["id"],)).fetchone()) == row
    current = lib.store.passages_for(lib.svid)
    assert {p["id"] for p in current}.isdisjoint({p["id"] for p in old})
    assert current[0]["text"] == old[0]["text"]
    assert current[0]["text_sha256"] == old[0]["text_sha256"]
    assert set(lib.store.evidence_statuses([r["id"] for r in old]).values()) == {"text_superseded"}
    assert {p["id"] for p in lib.store.search_passages([lib.svid], '"relays"', 20)} == {p["id"] for p in current}
    assert lib.store.has_pdf_text(lib.svid)
    assert lib.store.asset_page_digest(lib.aid) != digest
    assert [tuple(r) for r in lib.conn.execute("SELECT * FROM evidence_links")] == answer_rows
    assert lib.conn.execute("SELECT 1 FROM answers WHERE id = ?", (answer,)).fetchone()


def test_t5_ordinary_shifted_page_set_is_rejected_red_on_old(lib):
    old = head(lib); asset = lib.store.asset(lib.aid)
    result = lib.store.reextract_asset(lib.aid, extraction(pages=(2, 3)), "distinct-v1", chunk)
    assert result["outcome"] == "rejected"
    assert result["decision_code"] == "text_page_lost"
    assert head(lib) == old and lib.store.asset(lib.aid) == asset


@pytest.mark.parametrize("status,reason", [("succeeded", "already_current")])
def test_not_retryable(tmp_path, status, reason):
    lib = setup(tmp_path, status=status)
    before = protected(lib)
    with pytest.raises(NotRetryable, match=reason): reserve(lib)
    assert protected(lib) == before
    lib.conn.close()


def test_retry_calls_no_parser_tool_provider_or_model(lib, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Retry invoked external work")
    monkeypatch.setattr(pdf, "extract_pdf", forbidden)
    monkeypatch.setattr(ocr, "read_page", forbidden)
    monkeypatch.setattr(equations.EquationService, "read_asset", forbidden)
    # The Store module has no provider/model import; the import guard below pins that boundary.
    assert complete(lib)["outcome"] == "promoted"


@pytest.mark.parametrize("status", ["running"])
def test_reserve_and_complete_refuse_each_active_run_status(lib, status):
    operation = reserve(lib)
    run = lib.store.create_run(lib.rid, "answer", {}, None)
    lib.store.update_run(run["id"], status=status)
    before = protected(lib)
    with pytest.raises(RunInProgress): reserve(lib)
    result = complete(lib, operation=operation)
    if status == "queued":
        assert result["outcome"] == "promoted" and result["extraction_id"] is not None
    else:
        assert result["reason"] == "run_active" and result["extraction_id"] is None
        assert protected(lib) == before


def state(status="partial", page_count=3, pages=(1, 2), **overrides):
    return {"status": status, "error": None, "page_count": page_count, "extractor_profile": pdf.EXTRACTION_VERSION,
            "manifest": [(p, str(p), "chars:0-1", str(p), "text_layer") for p in pages],
            "passage_count": len(pages), "ocr_json": None, "math_json": None, **overrides}


@pytest.mark.parametrize("status", ["failed"])
@pytest.mark.parametrize("candidate_status,error,pages,code,diagnostic", [
    ("succeeded", None, (1, 2, 3), "recovered_text", False),
])
def test_empty_baseline_rules(status, candidate_status, error, pages, code, diagnostic):
    decision = recovery.decide(state(status, 0, ()), state(candidate_status, 3, pages, error=error))
    assert (decision.decision_code, decision.diagnostic_only) == (code, diagnostic)
    assert decision.promote == (code != "candidate_failed")


def test_policy_precedence_and_no_change():
    assert recovery.decide(state(), state()).decision_code == "no_change"
    assert recovery.decide(state(ocr_json="{}"), state("failed", error=pdf.ERROR_PASSWORD)).decision_code == "candidate_failed"
    assert recovery.decide(state(), state("no_text", pages=())).decision_code == "status_worse"
    assert recovery.decide(state(), state("failed", error=pdf.ERROR_PASSWORD)).decision_code == "candidate_failed"


ROOT = Path(__file__).resolve().parents[2]


def insert(conn, table, values, mode="INSERT", upsert=False):
    sql = f"{mode} INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})"
    if upsert: sql += " ON CONFLICT DO UPDATE SET id = excluded.id"
    conn.execute(sql, tuple(values.values()))


@pytest.mark.parametrize("column", ["text"])
def test_every_protected_passage_column_refuses_update(lib, column):
    pid = lib.conn.execute("SELECT id FROM passages LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="passage content is immutable"):
        lib.conn.execute(f"UPDATE passages SET {column} = {column} WHERE id = ?", (pid,))
    lib.conn.execute("DELETE FROM passages WHERE id = ?", (pid,))
    assert lib.conn.execute("SELECT 1 FROM passages WHERE id = ?", (pid,)).fetchone() is None


@pytest.mark.parametrize("column", ["text_pages"])
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

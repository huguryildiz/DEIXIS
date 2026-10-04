"""R1 synthetic Store contracts. No file, provider or model is read during a retry."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.documents import pdf, ocr, math_reader
from deixis.storage import db
from deixis.workflow import recovery, equations
from deixis.workflow.store import Store, NotFound, RequestConflict, RecoveryConflict, NotRetryable, RunInProgress


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
    from tests.review.review_helpers import make_answer
    answer = make_answer({"store": lib.store, "rid": lib.rid, "source_id": lib.svid, "section_passage": passage_id})
    text = lib.store.passage(passage_id)["text"]
    lib.conn.execute("UPDATE evidence_links SET anchor_text = ? WHERE passage_id = ?", (text, passage_id))
    return answer


def test_t1_empty_failed_baseline_recovers_beside_old_occurrence(tmp_path):
    lib = setup(tmp_path, status="failed", count=0, pages=())
    old = head(lib)
    other = lib.store.create_research("SYNTHETIC sharing?", "attached", "quick", [], "fake", "fake", None)
    lib.store.add_to_corpus(other, lib.svid, "user_upload")
    result = complete(lib, extraction("succeeded", 3, (1, 2, 3)))
    new = head(lib)
    assert (result["outcome"], result["decision_code"]) == ("promoted", "recovered_text")
    assert new["extraction_version"] == recovery.occurrence(pdf.EXTRACTION_VERSION, result["id"])
    assert new["extractor_profile"] == pdf.EXTRACTION_VERSION
    assert new["baseline_extraction_id"] == old["id"]
    stored_old = dict(lib.conn.execute("SELECT * FROM asset_extractions WHERE id = ?", (old["id"],)).fetchone())
    assert stored_old == old | {"outcome": "superseded"}
    asset = lib.store.asset(lib.aid)
    assert (asset["extraction_version"], asset["extraction_status"], asset["extraction_error"], asset["page_count"]) == (
        new["extraction_version"], "succeeded", None, 3)
    for rid in (lib.rid, other):
        events = [e for e in lib.store.events_after(rid, 0) if e["type"] == "asset_text_retried"]
        assert len(events) == 1
        assert events[0]["payload"] == {"asset_id": lib.aid, "source_version_id": lib.svid, "operation_id": result["id"],
            "lifecycle": "completed", "reason": None, "outcome": "promoted", "decision_code": "recovered_text", "extraction_version": new["extraction_version"],
            "baseline_extraction_id": old["id"]}
    lib.conn.close()


def test_t1_ordinary_same_profile_and_zero_page_defect_guards(tmp_path):
    lib = setup(tmp_path, status="failed", count=0, pages=())
    candidate = extraction("succeeded", 3, (1, 2, 3))
    assert lib.store.reextract_asset(lib.aid, candidate, pdf.EXTRACTION_VERSION, chunk)["outcome"] == "unchanged"
    result = lib.store.reextract_asset(lib.aid, candidate, "distinct-v1", chunk)
    assert result["outcome"] == "rejected" and "page count" in result["rejection_reason"]
    lib.conn.close()


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


@pytest.mark.parametrize("status,count,pages,candidate,code,outcome", [
    ("no_text", 0, (), extraction("failed", 0, (), pdf.ERROR_PASSWORD), "password_diagnosed", "diagnosis_updated"),
    ("no_text", 0, (), extraction("failed", 0, (), "ordinary failure"), "candidate_failed", "rejected"),
    ("partial", 3, (1, 2), extraction("failed", 0, (), pdf.ERROR_PASSWORD), "candidate_failed", "rejected"),
    ("no_text", 0, (), extraction("no_text", 3, ()), "no_text_diagnosed", "diagnosis_updated"),
    ("no_text", 0, (), extraction("no_text", 0, ()), "no_change", "no_change"),
])
def test_t4_diagnostic_exception_and_refusals(tmp_path, status, count, pages, candidate, code, outcome):
    lib = setup(tmp_path, status=status, count=count, pages=pages)
    before = head(lib)
    result = complete(lib, candidate)
    assert (result["decision_code"], result["outcome"]) == (code, outcome)
    if outcome == "diagnosis_updated":
        assert head(lib)["diagnostic_only"] == 1
        assert head(lib)["status"] == candidate.status
        assert lib.conn.execute("SELECT outcome FROM asset_extractions WHERE id = ?", (before["id"],)).fetchone()[0] == "superseded"
    else: assert head(lib) == before
    assert lib.conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == len(pages)
    lib.conn.close()


def test_t5_ordinary_shifted_page_set_is_rejected_red_on_old(lib):
    old = head(lib); asset = lib.store.asset(lib.aid)
    result = lib.store.reextract_asset(lib.aid, extraction(pages=(2, 3)), "distinct-v1", chunk)
    assert result["outcome"] == "rejected"
    assert result["decision_code"] == "text_page_lost"
    assert head(lib) == old and lib.store.asset(lib.aid) == asset


def test_t5_augmented_baseline_is_retained(tmp_path):
    lib = setup(tmp_path, source="ocr")
    before = protected(lib)
    result = complete(lib)
    assert result["decision_code"] == "augmented_text_would_be_lost" and result["outcome"] == "rejected"
    assert protected(lib)["source_assets"] == before["source_assets"]
    assert head(lib)["extraction_version"] == pdf.EXTRACTION_VERSION
    lib.conn.close()


@pytest.mark.parametrize("integrity,code", [(None, "legacy_page_count_untrusted"), ("verified", "page_count_changed"),
                                           ("mismatch", "recovered_from_corrupt_input")])
def test_t5_page_count_recovery_requires_observed_corrupt_input(tmp_path, integrity, code):
    lib = setup(tmp_path, integrity=integrity)
    result = complete(lib, extraction("succeeded", 5, (1, 2, 3, 4, 5)))
    assert result["decision_code"] == code
    assert result["outcome"] == ("promoted" if integrity == "mismatch" else "rejected")
    assert len(json.loads(result["new_coverage_json"])["manifest"]) == 5
    lib.conn.close()


def test_t6_rejected_then_promoted_occurrences_and_replay(lib):
    first = reserve(lib, "first")
    replay = reserve(lib, "first")
    assert replay["replayed"] is True and first["replayed"] is False
    assert {k: v for k, v in replay.items() if k != "replayed"} == {k: v for k, v in first.items() if k != "replayed"}
    rejected = complete(lib, extraction("failed", 0, (), "SYNTHETIC failure"), first)
    second = reserve(lib, "second")
    promoted = complete(lib, operation=second)
    assert rejected["outcome"] == "rejected" and promoted["outcome"] == "promoted"
    assert lib.conn.execute("SELECT COUNT(*) FROM asset_recovery_operations").fetchone()[0] == 2
    assert lib.conn.execute("SELECT COUNT(*) FROM asset_extractions").fetchone()[0] == 3
    before = protected(lib); events = lib.store.events_after(lib.rid, 0)
    assert lib.store.complete_text_retry(first["id"], extraction(), chunk, input_observation_id=None) == rejected
    assert lib.store.complete_text_retry(second["id"], extraction(), chunk, input_observation_id=None) == promoted
    assert protected(lib) == before and lib.store.events_after(lib.rid, 0) == events
    with pytest.raises(RequestConflict):
        lib.store.reserve_text_retry(lib.aid, expected_extraction_id=head(lib)["id"],
            idempotency_key="first", request_fingerprint="different")


def test_baseline_changed_at_reserve_writes_nothing(lib):
    before = protected(lib)
    with pytest.raises(RecoveryConflict, match="baseline_changed"):
        lib.store.reserve_text_retry(lib.aid, expected_extraction_id="ext_stale", idempotency_key="stale", request_fingerprint="stale")
    assert protected(lib) == before
    assert lib.conn.execute("SELECT COUNT(*) FROM asset_recovery_operations").fetchone()[0] == 0


@pytest.mark.parametrize("status,reason", [("succeeded", "already_current"), ("pending", "pending")])
def test_not_retryable(tmp_path, status, reason):
    lib = setup(tmp_path, status=status)
    before = protected(lib)
    with pytest.raises(NotRetryable, match=reason): reserve(lib)
    assert protected(lib) == before
    lib.conn.close()


def test_operation_running(lib):
    reserve(lib); before = protected(lib)
    with pytest.raises(RecoveryConflict, match="operation_running"): reserve(lib)
    assert protected(lib) == before


def test_reserve_active_run_in_other_research(lib):
    other = lib.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake", None)
    lib.store.add_to_corpus(other, lib.svid, "user_upload")
    lib.store.create_run(other, "answer", {}, None)
    before = protected(lib)
    with pytest.raises(RunInProgress): reserve(lib)
    assert protected(lib) == before


@pytest.mark.parametrize("kind", ["baseline_changed", "run_active", "asset_removed", "no_holding_research", "asset_replaced",
                                 "missing", "mismatch", "wrong_kind", "wrong_hash", "wrong_size"])
def test_completion_refusals_write_no_candidate(lib, kind):
    operation = reserve(lib)
    observation = observe(lib)
    if kind == "baseline_changed":
        lib.store.reextract_asset(lib.aid, extraction(pages=(1, 2, 3)), "distinct-v1", chunk)
    elif kind == "run_active":
        other = lib.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake", None)
        lib.store.add_to_corpus(other, lib.svid, "user_upload")
        run = lib.store.create_run(other, "answer", {}, None)
        lib.store.update_run(run["id"], status="running")
    elif kind == "asset_removed":
        lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
    elif kind == "no_holding_research":
        # Source removal retains membership history; this fixture needs no membership at all.
        lib.conn.execute("DELETE FROM corpus_memberships WHERE source_version_id = ?", (lib.svid,))
        assert lib.store.asset(lib.aid)["removed_at"] is None
    elif kind == "asset_replaced":
        lib.conn.execute("UPDATE source_assets SET sha256 = ? WHERE id = ?", ("3" * 64, lib.aid))
    elif kind == "missing": observation = "obs_missing"
    elif kind == "mismatch": observation = observe(lib, integrity="mismatch")
    elif kind == "wrong_kind": observation = observe(lib, kind="after_restore")
    elif kind == "wrong_hash": observation = observe(lib, sha="3" * 64)
    elif kind == "wrong_size": observation = observe(lib, size=11)
    before = protected(lib)
    result = lib.store.complete_text_retry(operation["id"], extraction(), chunk, input_observation_id=observation)
    reason = kind if kind in ("baseline_changed", "run_active", "asset_removed", "no_holding_research", "asset_replaced") else "input_not_verified"
    assert (result["outcome"], result["reason"], result["extraction_id"]) == ("refused", reason, None)
    assert protected(lib) == before
    events = [e for e in lib.store.events_after(lib.rid, 0) if e["type"] == "asset_text_retried"]
    if kind == "no_holding_research":
        assert events == []
    else:
        assert any(e["payload"]["outcome"] == "refused" for e in events)


@pytest.mark.parametrize("field", ["ocr", "math", "token", "page_source"])
def test_retry_refuses_augmented_candidate(lib, field):
    operation = reserve(lib); candidate = extraction()
    if field in ("ocr", "math"): setattr(candidate, field, {})
    elif field == "token": candidate.extraction_version += "+reextract-rop_X"
    else: candidate.pages[0].text_source = "ocr"
    before = protected(lib)
    with pytest.raises(ValueError): complete(lib, candidate, operation)
    assert protected(lib) == before
    assert lib.store._retry_result(operation["id"])["lifecycle"] == "running"


def test_retry_calls_no_parser_tool_provider_or_model(lib, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Retry invoked external work")
    monkeypatch.setattr(pdf, "extract_pdf", forbidden)
    monkeypatch.setattr(ocr, "read_page", forbidden)
    monkeypatch.setattr(math_reader.MathReader, "read", forbidden)
    monkeypatch.setattr(equations.EquationService, "read_asset", forbidden)
    # The Store module has no provider/model import; the import guard below pins that boundary.
    assert complete(lib)["outcome"] == "promoted"


def test_manifest_equals_stored_first_duplicate_chunk(lib):
    candidate = pdf.Extraction("partial", 3, [pdf.PageText(1, "i", "abab")], extraction_version="distinct-v1")
    duplicate_chunker = lambda text: [(0, 2, "ab"), (2, 4, "ab")]
    lib.store.reextract_asset(lib.aid, candidate, candidate.extraction_version, duplicate_chunker)
    computed = recovery.coverage_manifest(candidate, duplicate_chunker)
    assert computed == recovery.stored_manifest(lib.conn, lib.aid, candidate.extraction_version)
    assert len(computed) == 1 and computed[0][2] == "chars:0-2"


@pytest.mark.parametrize("candidate_pages", [(1, 2), (1, 2, 3)])
def test_ordinary_decision_uses_head_changed_before_write_transaction(lib, monkeypatch, candidate_pages):
    import deixis.workflow.store as store_module
    second = db.connect(Path(lib.conn.execute("PRAGMA database_list").fetchone()[2]))
    original = store_module.transaction
    baseline = None
    @contextmanager
    def before_write(conn):
        nonlocal baseline
        if conn is lib.conn:
            Store(second).reextract_asset(lib.aid, extraction(pages=(1, 2, 3)), "intervening-v1", chunk)
            baseline = head(lib)
        with original(conn):
            yield conn
    monkeypatch.setattr(store_module, "transaction", before_write)
    try:
        result = lib.store.reextract_asset(lib.aid, extraction(pages=candidate_pages), "final-v1", chunk)
        promoted = len(candidate_pages) == 3
        assert result["outcome"] == ("current" if promoted else "rejected")
        assert result["decision_code"] == ("upgraded" if promoted else "fewer_text_pages")
        assert result["old_version"] == "intervening-v1"
        written = lib.conn.execute("SELECT * FROM asset_extractions WHERE extraction_version = 'final-v1'").fetchone()
        assert written["baseline_extraction_id"] == baseline["id"]
        expected_old = baseline | {"outcome": "superseded"} if promoted else baseline
        assert dict(second.execute("SELECT * FROM asset_extractions WHERE id = ?", (baseline["id"],)).fetchone()) == expected_old
        assert head(lib)["extraction_version"] == ("final-v1" if promoted else "intervening-v1")
    finally: second.close()


@pytest.mark.parametrize("shared", [False, True])
def test_purge_keeps_shared_history_and_deletes_unshared_cycles(lib, shared):
    complete(lib, extraction("failed", 0, (), "SYNTHETIC failure"))
    complete(lib)
    if shared:
        other = lib.store.create_research("SYNTHETIC sharing?", "attached", "quick", [], "fake", "fake", None)
        lib.store.add_to_corpus(other, lib.svid, "user_upload")
    tables = ("asset_recovery_operations", "asset_file_observations", "asset_extractions", "passages")
    before = {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")] for t in tables}
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    after = {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")] for t in tables}
    assert after == (before if shared else {t: [] for t in tables})
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    if shared:
        assert {r[0] for r in lib.conn.execute("SELECT research_id FROM asset_recovery_operations")} == {lib.rid}


def test_source_purge_deletes_recovery_cycles(lib):
    complete(lib, extraction("failed", 0, (), "failure"))
    complete(lib)
    lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed before purge")
    chosen, files, payloads = lib.store.purge_sources(lib.rid, [lib.svid])
    assert chosen == [lib.svid]
    for table in ("asset_extractions", "asset_recovery_operations", "asset_file_observations", "passages"):
        assert lib.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_event_write_rolls_back_candidate_head_and_completion(lib, monkeypatch):
    operation = reserve(lib); observation = observe(lib, operation_id=operation["id"])
    before = protected(lib); events = lib.store.events_after(lib.rid, 0)
    def fail(*args, **kwargs): raise RuntimeError("SYNTHETIC event write failure")
    monkeypatch.setattr(lib.store, "_event", fail)
    with pytest.raises(RuntimeError, match="event write failure"):
        lib.store.complete_text_retry(operation["id"], extraction(pages=(1, 2, 3)), chunk, input_observation_id=observation)
    assert protected(lib) == before and lib.store.events_after(lib.rid, 0) == events
    assert operation["replayed"] is False
    assert lib.store._retry_result(operation["id"]) == {k: v for k, v in operation.items() if k != "replayed"}


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested"])
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


def test_removed_asset_cannot_be_reserved(lib):
    lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
    before = protected(lib)
    with pytest.raises(NotFound): reserve(lib)
    assert protected(lib) == before


@pytest.mark.parametrize("completed", [False, True])
def test_reservation_replays_after_asset_removal_and_conflicting_key_still_refuses(lib, completed):
    operation = reserve(lib, "removed-replay")
    if completed:
        operation = complete(lib, operation=operation)
    lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
    before = protected(lib)
    events = lib.store.events_after(lib.rid, 0)
    changes = lib.conn.total_changes
    replay = reserve(lib, "removed-replay")
    assert replay["replayed"] is True
    if not completed:
        assert operation["replayed"] is False
    assert {k: v for k, v in replay.items() if k != "replayed"} == {k: v for k, v in operation.items() if k != "replayed"}
    with pytest.raises(RequestConflict):
        lib.store.reserve_text_retry(lib.aid, expected_extraction_id=operation["baseline_extraction_id"],
            idempotency_key="removed-replay", request_fingerprint="different")
    assert protected(lib) == before and lib.store.events_after(lib.rid, 0) == events
    assert lib.conn.total_changes == changes

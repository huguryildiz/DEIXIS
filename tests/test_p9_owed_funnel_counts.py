"""SYNTHETIC libraries migrated with product SQL; no model/provider calls."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
from scripts.p9_owed import funnel_counts as kit


class Library:
    def __init__(self, path):
        self.path = path
        self.conn = db.connect(path / "library.sqlite")
        db.migrate(self.conn)
        self.store = Store(self.conn)
        self.rid = self.store.create_research("SYNTHETIC funnel question", "academic", "standard", [], "fake", "m", "en")
        self.run = self.store.create_run(self.rid, "discovery", {}, None)["id"]
        self.store.update_run(self.run, status="completed")
        self.decisions = DecisionStore(self.store)

    def source(self, key, *, work=None, title=None, authors=None, year=2026):
        wid = work or key
        self.conn.execute("INSERT OR IGNORE INTO works(id,created_at) VALUES (?,?)", (wid, db.now()))
        self.conn.execute("INSERT INTO source_versions(id,work_id,title,authors_json,year,origin,created_at,version_label)"
                          " VALUES (?,?,?,?,?,'provider',?,'publishedVersion')",
                          (key, wid, title or "SYNTHETIC " + key, json.dumps(authors or []), year, db.now()))
        self.store.add_to_corpus(self.rid, key, "library")
        return key

    def decision(self, key, code):
        row = self.decisions.record(self.rid, key, code)
        self.decisions.derive_selection(self.rid, self.store.source(key)["work_id"])
        return row

    def fetch(self, key, status="failed", error="fetch_http_error"):
        step = self.store.step(self.run, f"fetch:{key}", "fetch_pdf")
        self.store.start_step(step["id"])
        self.store.finish_step(step["id"], status, error_code=error)
        return step

    def plan(self, keys):
        step = self.store.step(self.run, "fulltext_plan", "code:fulltext_plan")
        self.store.finish_step(step["id"], "succeeded", output={"works": keys})

    def candidate(self, key, access="timeout", error="stored-timeout"):
        discovery = "lookup-" + key
        self.conn.execute("INSERT INTO pdf_discovery_runs(id,research_id,source_version_id,provider,query_text,status,created_at)"
                          " VALUES (?,?,?,'openalex','SYNTHETIC','completed',?)", (discovery, self.rid, key, db.now()))
        self.conn.execute("INSERT INTO pdf_candidates(id,source_version_id,discovery_run_id,provider,candidate_url,"
                          " identity_status,version_status,access_status,error_code,discovered_at,attempted_at)"
                          " VALUES (?,?,?,'openalex',?,'doi_verified','match',?,?,?,?)",
                          ("candidate-" + key, key, discovery, "https://example.invalid/" + key, access, error,
                           db.now(), None if access == "not_attempted" else db.now()))

    def pdf(self, key, *, text=True, origin="download"):
        aid = "asset-" + key
        status = "succeeded" if text else "no_text"
        self.conn.execute("INSERT INTO source_assets(id,source_version_id,sha256,byte_size,media_type,storage_path,"
                          " retrieved_at,origin,extraction_status,extraction_version) VALUES (?,?,?,10,'application/pdf',?,?,?,?,?)",
                          (aid, key, "a" * 64, key + ".pdf", db.now(), origin, status, "synthetic-v1"))
        self.conn.execute("INSERT INTO asset_extractions(id,asset_id,extraction_version,extractor_profile,status,text_pages,passage_count,outcome,created_at)"
                          " VALUES (?,?,'synthetic-v1','synthetic-v1',?,?,?,'current',?)", ("ext-" + key, aid, status, int(text), int(text), db.now()))
        if text:
            self.store._insert_passage(key, aid, "pdf_page", 1, None, None, None, "synthetic-v1", "SYNTHETIC PDF text")

    def input(self, key, *, kind="abstract", response=True, session=True, candidate=False):
        suffix = key + kind + str(response) + str(session) + str(candidate)
        step = self.store.step(self.run, "model-" + suffix, "model:abstract_screening")
        payload = {"step_input_id": "input-" + suffix, "task_type": "abstract_screening", "scope_revision": 1,
                   "skill_package_hash": "synthetic", "candidates": [], "sources": [], "passages": []}
        if candidate:
            cid = "cand-" + key
            self.conn.execute("INSERT INTO candidates(id,research_id,source_version_id,created_at) VALUES (?,?,?,?)",
                              (cid, self.rid, key, db.now()))
            payload["candidates"] = [{"candidate_id": cid, "abstract": "SYNTHETIC abstract"}]
        else:
            passage = self.conn.execute("SELECT id,text FROM passages WHERE source_version_id=? AND kind=?", (key, kind)).fetchone()
            if passage is None:
                assert kind == "abstract"
                pid = self.store._insert_passage(key, None, "abstract", None, None, "openalex", None, None, "SYNTHETIC shown text")
                text = "SYNTHETIC shown text"
            else:
                pid, text = passage
            payload["passages"] = [{"passage_id": pid, "source_id": key, "locator": {"kind": kind}, "text": text}]
        self.store.insert_step_input(step["id"], self.rid, self.run, 0, payload, "", "", "", {})
        if session:
            # A stored synthetic record, not a model session started by the kit.
            self.conn.execute("INSERT INTO model_sessions(id,research_id,run_id,step_id,step_input_id,connection,status,raw_output,started_at)"
                              " VALUES (?,?,?,?,?,'fake',?,?,?)", ("session-" + suffix, self.rid, self.run, step["id"],
                                  payload["step_input_id"], "completed" if response else "failed", "{}" if response else None, db.now()))

    def seal(self):
        self.conn.close()


@pytest.fixture
def library(tmp_path):
    lib = Library(tmp_path / "data")
    yield lib
    lib.conn.close()


def measure(lib, **kwargs):
    lib.seal()
    result = kit.count(lib.path, label="SYNTHETIC", product_commit="6e85654", prep_rule="synthetic records", **kwargs)
    assert result["status"] == "measured", result
    assert result["model_sessions"] == result["provider_requests"] == 0
    return result["researches"][0]


def test_all_counts_history_membership_and_priority(library):
    lib = library
    for key in ("queue", "tried", "untried", "other", "included", "excluded", "override"):
        lib.source(key)
    lib.source("second-version", work="included")
    lib.decision("queue", "fulltext_runs_disagree")
    lib.decision("tried", "no_fulltext")
    lib.decision("untried", "no_fulltext")
    lib.decision("included", "all_parts_verified")
    lib.decision("excluded", "both_blocks_missing")
    lib.decision("override", "all_parts_verified")
    human = lib.decision("override", "human_criterion_not_met")
    current_version = lib.conn.execute("SELECT version FROM selections WHERE source_version_id='override'").fetchone()[0]
    lib.store.set_user_selection(lib.rid, "override", "excluded", current_version, "SYNTHETIC K03")
    version = lib.conn.execute("SELECT version FROM selections WHERE source_version_id='override'").fetchone()[0]
    lib.conn.execute("INSERT INTO human_selection_links VALUES (?,?,?,?,?)", (human["id"], lib.rid, "override", version, db.now()))
    lib.store._event(lib.rid, "stage_decision_recorded", {"decision_id": human["id"]})
    lib.plan(["queue", "tried", "untried"])
    lib.fetch("queue")
    lib.fetch("tried", error="fetch_blocked_url")
    lib.candidate("other")
    lib.pdf("included")
    lib.pdf("second-version", text=False)
    lib.input("included", kind="pdf_page")
    lib.input("queue", candidate=True)
    lib.input("queue", kind="abstract")  # Same work twice, counted once.
    lib.input("other", response=False)
    lib.input("untried", session=False)  # Prepared input is not sent evidence.
    out = measure(lib)
    assert (out["denominator"], out["source_versions"]) == (7, 8)
    assert out["abstract_read_by_model"] == 1
    assert out["final_membership"] == {"included": 1, "excluded": 2, "pending": 4, "removed": 0, kit.UNKNOWN: 0}
    auto = out["automatic_decisions_history"]
    assert auto["model_agreement"]["included"] == {"records": 2, "works": 2}
    assert auto["code"]["excluded"] == {"records": 1, "works": 1}
    assert auto["code"]["included"] == {"records": kit.UNKNOWN, "works": kit.UNKNOWN}
    assert out["k03_queue_decisions"]["records"] == 1
    assert out["k03_queue_decisions"]["by_reason"] == {"human_criterion_not_met": 1}
    assert out["k03_queue_decisions"]["selection_effect_works"] == 1
    assert out["pending_primary_work_ids"] == {"in review queue": ["queue"], "PDF waiting, fetch tried": ["tried"],
        "PDF waiting, not tried": ["untried"], "other": ["other"]}
    partition = [wid for ids in out["pending_primary_work_ids"].values() for wid in ids]
    assert len(partition) == len(set(partition)) == out["final_membership"]["pending"]
    assert sum(out["pending_primary_counts"].values()) == 4
    assert out["overlapping_dimensions"]["queue_work_ids"] == ["queue"]
    assert out["overlapping_dimensions"]["recorded_fetch_work_ids"] == ["other", "queue", "tried"]
    full = out["fulltext"]
    assert (full["attempted"], full["successful_download"], full["extracted_pdf_text"], full["text_given_to_model"]) == (3, 1, 1, 1)
    assert full["direct_fetch_records"] == 2 and full["last_candidate_attempt_records"] == 1
    assert full["direct_fetch_failures_by_stored_code"] == {"fetch_blocked_url": 1, "fetch_http_error": 1}
    assert full["last_candidate_failures_by_stored_code"] == {"stored-timeout": 1}
    assert len(out["runs"]) == 1 and out["runs"][0]["status"] == "completed"
    assert any(m["quantity"] == "model_delivery" for m in out["missing"])


def test_unknowns_are_not_inferred_from_current_status_or_metadata(library):
    lib = library
    lib.source("included")
    lib.decision("included", "human_include")  # No event: must not call this K03.
    lib.pdf("included", origin="user_upload")
    lib.input("included", response=False)
    out = measure(lib)
    assert out["abstract_read_by_model"] == kit.UNKNOWN
    assert out["k03_queue_decisions"]["records"] == kit.UNKNOWN
    assert out["k03_queue_decisions"]["unknown_origin_decision_ids"]
    assert out["fulltext"]["attempted"] == out["fulltext"]["successful_download"] == kit.UNKNOWN
    assert out["fulltext"]["extracted_pdf_text"] == 1
    assert out["fulltext"]["text_given_to_model"] == kit.UNKNOWN
    assert out["pending_primary_counts"] == dict.fromkeys(kit.PRIMARY_CATEGORY_FIELDS, 0)
    missing = {m["quantity"] for m in out["missing"]}
    assert {"abstract_read_by_model", "fulltext.attempted", "fulltext.successful_download", "fulltext.text_given_to_model", "k03_queue_origin"} <= missing


def test_readonly_open_single_transaction_and_unchanged_files(library):
    library.source("source")
    library.seal()
    before = kit.manifest(library.path)
    with kit.open_readonly(library.path) as conn:
        assert conn.in_transaction
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO works(id,created_at) VALUES ('write','never')")
        assert conn.execute("SELECT count(*) FROM works").fetchone()[0] == 1
    result = kit.count(library.path, label="test", product_commit="abc", prep_rule="synthetic")
    assert result["status"] == "measured"
    assert kit.manifest(library.path) == before


def test_nonempty_wal_fails_closed_instead_of_ignoring_committed_data(library, tmp_path):
    library.source("wal-only")
    target = tmp_path / "wal-copy"
    target.mkdir()
    for name in ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm"):
        shutil.copyfile(library.path / name, target / name)
    before = kit.manifest(target)
    result = kit.count(target, label="wal", product_commit="abc", prep_rule="copied uncheckpointed WAL")
    assert result["status"] == kit.UNMEASURED and "WAL" in result["reason"]
    assert "researches" not in result
    assert kit.manifest(target) == before


def test_missing_database_never_created_and_cli_reports_failure(tmp_path):
    data = tmp_path / "empty"
    data.mkdir()
    out = tmp_path / "counts.json"
    code = kit.main(["count", str(data), "--label", "missing", "--product-commit", "abc", "--prep-rule", "no corpus", "--out", str(out)])
    assert code == 1 and json.loads(out.read_text())["status"] == kit.UNMEASURED
    assert not (data / "library.sqlite").exists()


def test_chain_found_identity_and_status(library):
    chain_path = Path("docs/product/p6-slice2-chain.json")
    chain = kit.read_chain(chain_path)
    for work in chain["works"][:2]:
        library.source(work["key"], title=work["title"], authors=[work["first_author"].title() + ", First"], year=work["years"][0])
    library.decision("bert", "both_blocks_missing")
    # A title-only match with wrong identity never counts.
    w = chain["works"][2]
    library.source("wrong-roberta", title=w["title"], authors=["Wrong Author"], year=2019)
    out = measure(library, chain_file=chain_path)
    found = {w["key"]: w for w in out["frozen_G"]["works"]}
    assert found["elmo"]["found"] and found["elmo"]["works"] == [{"work_id": "elmo", "final_status": "pending"}]
    assert found["bert"]["works"] == [{"work_id": "bert", "final_status": "excluded"}]
    assert not found["roberta"]["found"] and found["roberta"]["identity_rejected_version_ids"] == ["wrong-roberta"]
    assert not found["albert"]["found"]


def test_invalid_chain_part_unmeasured_but_corpus_counted(library, tmp_path):
    path = tmp_path / "chain.json"
    path.write_text('{"version": 2, "works": [], "pairs": []}')
    library.seal()
    result = kit.count(library.path, label="L9 NLP", product_commit="abc", prep_rule="test", chain_file=path)
    assert result["status"] == "measured"
    assert result["frozen_G"]["status"] == kit.UNMEASURED
    assert result["missing"][0]["quantity"] == "frozen_G"


def test_retained_removed_memberships_and_all_research_runs(library):
    library.source("removed")
    library.conn.execute("UPDATE corpus_memberships SET removed_at=? WHERE source_version_id='removed'", (db.now(),))
    failed = library.store.create_run(library.rid, "discovery", {}, None)["id"]
    library.store.update_run(failed, status="failed")
    other = library.store.create_research("SYNTHETIC other research", "academic", "standard", [], "fake", "m", "en")
    library.seal()
    result = kit.count(library.path, label="two", product_commit="abc", prep_rule="synthetic")
    assert len(result["researches"]) == 2
    out = next(r for r in result["researches"] if r["research"]["id"] == library.rid)
    assert out["denominator"] == 1 and out["active_unique_works"] == 0 and out["final_membership"]["removed"] == 1
    assert {r["status"] for r in out["runs"]} == {"completed", "failed"}
    assert any(r["research"]["id"] == other for r in result["researches"])
    assert "totals" not in result


def test_manifest_files_digest_and_side_files(tmp_path):
    src = tmp_path / "src"
    (src / "nested").mkdir(parents=True)
    for name in ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm", "nested/file"):
        (src / name).write_bytes(name.encode())
    out = tmp_path / "manifest.json"
    assert kit.main(["manifest", str(src), str(out)]) == 0
    result = json.loads(out.read_text())
    assert [row["path"] for row in result["files"]] == ["library.sqlite", "library.sqlite-shm", "library.sqlite-wal", "nested/file"]
    for row in result["files"]:
        assert row["byte_size"] == len(row["path"].encode())
        assert row["sha256"] == hashlib.sha256(row["path"].encode()).hexdigest()
        assert row["nlink"] == 1 and row["type"] == "file"
    body = {key: value for key, value in result.items() if key != "sha256"}
    assert result["sha256"] == hashlib.sha256(kit.canonical(body)).hexdigest()


@pytest.mark.parametrize("kind", ["hardlink", "symlink", "directory-symlink", "root-symlink", "fifo"])
def test_manifest_rejects_unsafe_entries(tmp_path, kind):
    src = tmp_path / "src"
    src.mkdir()
    file = src / "file"
    file.write_text("synthetic")
    if kind == "hardlink":
        os.link(file, tmp_path / "outside-link")
    elif kind == "symlink":
        (src / "link").symlink_to(file)
    elif kind == "directory-symlink":
        (src / "escape").symlink_to(tmp_path, target_is_directory=True)
    elif kind == "root-symlink":
        link = tmp_path / "root-link"
        link.symlink_to(src, target_is_directory=True)
        src = link
    else:
        os.mkfifo(src / "fifo")
    with pytest.raises(kit.MeasurementRefused):
        kit.manifest(src)


def idle_result(*args, **kwargs):
    return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="")


def test_copy_uses_cp_and_matches_manifest(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm"):
        (src / name).write_text("SYNTHETIC " + name)
    real_run = subprocess.run
    seen = []

    def run(args, **kwargs):
        seen.append(args)
        return idle_result(args) if args[0] == "lsof" else real_run(args, **kwargs)

    monkeypatch.setattr(kit.subprocess, "run", run)
    dst = tmp_path / "dst"
    record = kit.copy_library(src, dst)
    assert record["usable"] and record["source_manifest"] == record["copy_manifest"]
    assert record == json.loads(kit.copy_record_path(dst).read_text())
    assert [args[0] for args in seen] == ["lsof", "cp"]
    assert seen[1][:2] == ["cp", "-Rp"]
    assert kit.manifest(src) == kit.manifest(dst)
    assert kit.copy_library(src, dst)["usable"] is False


@pytest.mark.parametrize("returncode,stdout,stderr", [(0, "p123\n", ""), (1, "", "warning"), (2, "", "error")])
def test_copy_refuses_holders_and_ambiguous_lsof(monkeypatch, tmp_path, returncode, stdout, stderr):
    src = tmp_path / "src"
    src.mkdir()
    (src / "library.sqlite").write_text("synthetic")
    monkeypatch.setattr(kit.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, returncode, stdout, stderr))
    dst = tmp_path / "dst"
    record = kit.copy_library(src, dst)
    assert not record["usable"] and "lsof" in record["reason"] and not dst.exists()


def test_differing_copy_unusable_record_and_count_refusal(monkeypatch, library, tmp_path):
    library.source("source")
    library.seal()
    real_run = subprocess.run

    def run(args, **kwargs):
        if args[0] == "lsof":
            return idle_result(args)
        result = real_run(args, **kwargs)
        (Path(args[-1]) / "extra-file").write_text("SYNTHETIC difference")
        return result

    monkeypatch.setattr(kit.subprocess, "run", run)
    dst = tmp_path / "dst"
    assert kit.main(["copy", str(library.path), str(dst)]) == 1
    record = json.loads(kit.copy_record_path(dst).read_text())
    assert not record["usable"] and record["manifests_equal"] is False
    result = kit.count(dst, label="unusable", product_commit="abc", prep_rule="mismatched copy")
    assert result["status"] == kit.UNMEASURED and "usable copy" in result["reason"]


def test_outputs_and_copy_cannot_escape_rules(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "library.sqlite").write_text("synthetic")
    assert kit.main(["manifest", str(src), str(src / "out.json")]) == 1
    with pytest.raises(kit.MeasurementRefused):
        kit.copy_library(src, src / "nested-destination")
    monkeypatch.setattr(kit.subprocess, "run", idle_result)
    trusted = tmp_path / "trusted.json"
    trusted.write_text('{}')
    record = kit.copy_library(src, tmp_path / "dst", trusted_manifest=trusted)
    assert not record["usable"] and record["trusted_manifest_equal"] is False


def test_count_cli_writes_json_and_markdown_without_modifying_data(library, tmp_path):
    library.source("source")
    library.seal()
    before = kit.manifest(library.path)
    out, md = tmp_path / "out.json", tmp_path / "out.md"
    assert kit.main(["count", str(library.path), "--label", "synthetic", "--product-commit", "abc", "--prep-rule", "test",
                     "--out", str(out), "--md", str(md)]) == 0
    assert json.loads(out.read_text())["researches"][0]["denominator"] == 1
    assert kit.UNKNOWN in md.read_text() and "```json" in md.read_text()
    assert kit.manifest(library.path) == before


def test_version_disagreement_routes_to_queue_without_stored_queue_code(library):
    library.source("first", work="same-work")
    library.source("second", work="same-work")
    library.decision("first", "all_parts_verified")
    library.decision("second", "criterion_absent")
    out = measure(library)
    assert out["denominator"] == 1 and out["source_versions"] == 2
    assert out["final_membership"]["pending"] == 1
    assert out["pending_primary_work_ids"]["in review queue"] == ["same-work"]
    assert out["overlapping_dimensions"]["queue_works"] == 1
    assert out["automatic_decisions_history"]["model_agreement"]["included"]["works"] == 1
    assert out["automatic_decisions_history"]["model_agreement"]["excluded"]["works"] == 1


@pytest.mark.parametrize("stale,plan", [(False, False), (True, True)])
def test_pdf_waiting_respects_product_plan_and_staleness(library, stale, plan):
    library.source("waiting")
    decision = library.decision("waiting", "no_fulltext")
    if plan:
        library.plan(["waiting"])
    if stale:
        library.conn.execute("UPDATE stage_decisions SET scope_revision=0 WHERE id=?", (decision["id"],))
    out = measure(library)
    assert out["overlapping_dimensions"]["pdf_waiting_works"] == 0
    assert out["pending_primary_work_ids"]["other"] == ["waiting"]


def test_last_candidate_download_is_separate_from_extraction_and_model_text(library):
    library.source("downloaded")
    library.candidate("downloaded", access="downloaded", error=None)
    library.fetch("downloaded", status="partial", error="extraction_no_text")
    library.pdf("downloaded", text=False)
    out = measure(library)
    assert out["fulltext"]["attempted"] == out["fulltext"]["successful_download"] == 1
    assert out["fulltext"]["extracted_pdf_text"] == out["fulltext"]["text_given_to_model"] == kit.UNKNOWN
    # A download followed by no_text is not a fetch failure.
    assert out["fulltext"]["direct_fetch_failures_by_stored_code"] == kit.UNKNOWN


def test_null_failure_code_and_unstarted_steps(library):
    library.source("null-code")
    library.source("unstarted")
    library.fetch("null-code", error=None)
    library.store.step(library.run, "fetch:unstarted", "fetch_pdf")
    library.candidate("unstarted", access="not_attempted")
    out = measure(library)
    assert out["fulltext"]["attempted"] == 1
    assert out["fulltext"]["direct_fetch_records"] == 1
    assert out["fulltext"]["direct_fetch_failures_by_stored_code"] == {kit.UNKNOWN: 1}
    assert any(m["quantity"] == "fetch_failure_code" for m in out["missing"])


@pytest.mark.parametrize("table,quantity", [("asset_extractions", "fulltext.extracted_pdf_text"),
                                           ("model_sessions", "abstract_read_by_model")])
def test_unstored_optional_evidence_is_unknown_not_an_unmeasured_corpus(library, table, quantity):
    library.source("source")
    library.conn.execute("PRAGMA foreign_keys=OFF")
    library.conn.execute(f"DROP TABLE {table}")
    out = measure(library)
    assert out["denominator"] == 1
    assert any(m["quantity"] == "stored_schema" and table in m["reason"] for m in out["missing"])
    assert any(m["quantity"] == quantity for m in out["missing"])


def test_audit_decision_is_not_counted_as_k03(library):
    library.source("audited")
    decision = library.decision("audited", "human_include")
    library.store._event(library.rid, "stage_decision_recorded", {"decision_id": decision["id"], "via": "audit"})
    out = measure(library)
    assert out["k03_queue_decisions"]["records"] == kit.UNKNOWN
    assert out["k03_queue_decisions"]["unknown_origin_decision_ids"] == []


def test_modified_chain_identities_are_refused(tmp_path):
    chain = json.loads(Path("docs/product/p6-slice2-chain.json").read_text())
    chain["works"][0]["first_author"] = "invented"
    path = tmp_path / "altered-chain.json"
    path.write_text(json.dumps(chain))
    with pytest.raises(kit.MeasurementRefused, match="frozen four-work"):
        kit.read_chain(path)


def test_missing_lsof_records_refusal_without_copy(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "library.sqlite").write_text("synthetic")

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("lsof unavailable")

    monkeypatch.setattr(kit.subprocess, "run", unavailable)
    dst = tmp_path / "dst"
    record = kit.copy_library(src, dst)
    assert not record["usable"] and "lsof unavailable" in record["reason"]
    assert not dst.exists() and kit.copy_record_path(dst).exists()


def test_output_hardlink_never_overwrites_input(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    file = src / "library.sqlite"
    file.write_text("synthetic bytes must remain unchanged")
    out = tmp_path / "out.json"
    os.link(file, out)
    assert kit.main(["count", str(src), "--label", "x", "--product-commit", "abc", "--prep-rule", "test", "--out", str(out)]) == 1
    assert file.read_text() == "synthetic bytes must remain unchanged"


def test_entire_count_has_one_read_transaction_and_no_writes(library, monkeypatch):
    library.source("source")
    library.store.create_research("SYNTHETIC second", "academic", "standard", [], "fake", "m", "en")
    library.seal()
    real_connect = sqlite3.connect
    trace = []
    uris = []

    def connect(target, **kwargs):
        uris.append(target)
        conn = real_connect(target, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(kit.sqlite3, "connect", connect)
    result = kit.count(library.path, label="trace", product_commit="abc", prep_rule="synthetic")
    assert result["status"] == "measured" and len(result["researches"]) == 2, result.get("reason")
    assert len(uris) == 1 and "mode=ro" in uris[0]
    assert trace.count("BEGIN") == trace.count("ROLLBACK") == 1
    assert not any(query.lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "COMMIT"} for query in trace)

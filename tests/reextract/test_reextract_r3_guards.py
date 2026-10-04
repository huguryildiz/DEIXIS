"""S5, S14 and S16 preservation, retrieval and abandoned-copy evidence."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow import reconcile, text_retry
from deixis.workflow.review.snapshot import build_snapshot
from deixis.workflow.review.stale import stale_reasons
from deixis.workflow.tables import TableStore
from deixis.workflow.views import research_view
from tests.helpers import make_pdf
from tests.reextract_r2a_helpers import child_lock, head, seed, store_library
from tests.reextract_r2b_helpers import tear, write
from tests.reextract_r2c_helpers import child
from tests.reextract_r3_helpers import no_external_calls, retry, rich, verified_child
from tests.review_helpers import all_rows


def protected_rows(conn, before, *, changed_asset=None, changed_head=None):
    after = all_rows(conn)
    columns = {t: [r[1] for r in conn.execute('PRAGMA table_info("' + t + '")')] for t in before}
    append_only = {"asset_recovery_operations", "asset_file_observations", "asset_extractions", "passages", "events"}
    for table, old in before.items():
        if table.startswith("passages_fts"):
            continue  # FTS physical storage is covered by the logical query below.
        if table == "sqlite_sequence":
            previous, current = dict(old), dict(after[table])
            delta = len(after["events"]) - len(before["events"])
            assert current.get("events", 0) - previous.get("events", 0) == delta
            assert {k: v for k, v in previous.items() if k != "events"} == {k: v for k, v in current.items() if k != "events"}
            continue
        if table not in append_only and table != "source_assets":
            assert after[table] == old, table
            continue
        for row in old:
            identity = row[columns[table].index("id")]
            current = next(r for r in after[table] if r[columns[table].index("id")] == identity)
            permitted = ({"outcome"} if table == "asset_extractions" and identity == changed_head else
                         {"extraction_version", "extraction_status", "extraction_error", "page_count"}
                         if table == "source_assets" and identity == changed_asset else set())
            assert all(a == b for name, a, b in zip(columns[table], row, current) if name not in permitted), (table, identity)


def retrieval(lib):
    current = lib.store.passages_for(lib.svid)
    ids = {p["id"] for p in current}
    assert {p["id"] for p in lib.store.search_passages([lib.svid], "SYNTHETIC", 500)} == ids
    assert lib.store.has_pdf_text(lib.svid) is bool(ids)
    assert lib.store.answer_versions(lib.rid)[lib.svid] == lib.svid
    assert {p["extraction_version"] for p in current} <= {head(lib.store, lib.aid)["extraction_version"]}
    rejected = {r[0] for r in lib.conn.execute("SELECT p.id FROM passages p JOIN asset_extractions e"
        " ON e.asset_id = p.asset_id AND e.extraction_version = p.extraction_version WHERE e.outcome = 'rejected'")}
    assert ids.isdisjoint(rejected)
    # The actual lexical inspection ranker takes its rows from current-only Store reads.
    from deixis.domain import skill
    from deixis.workflow.flow import FlowDeps, ResearchFlow
    flow = ResearchFlow(FlowDeps(lib.settings, lib.store, {}, skill.load_skill_package(), None))
    # The mixed-corpus scope exercises ranking rather than the small-PDF shortcut.
    ranked = flow._retrieve(lib.rid, lib.store.scope(lib.rid) | {"source_scope": "academic"}, [lib.svid], 500)
    assert {p["id"] for p in ranked} == ids


@pytest.mark.parametrize("outcome", ["promoted", "rejected", "no_change", "diagnosis", "interrupted", "file_only"])
def test_s5_every_table_protected_guard(tmp_path, monkeypatch, outcome):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        active = lib
        if outcome == "diagnosis":
            import fitz
            doc = fitz.open(stream=make_pdf(["SYNTHETIC password page"]), filetype="pdf")
            data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
            doc.close()
            active = seed(lib.store, lib.settings, "no_text", data=data)
            lib.store.add_to_corpus(lib.rid, active.svid, "user_upload")
            active.rid = lib.rid
        old_head = head(lib.store, active.aid)
        before = all_rows(lib.conn)
        real = pdf.extract_pdf
        if outcome in ("rejected", "no_change"):
            def parse(path):
                candidate = real(path)
                candidate.status = "partial"
                candidate.pages = [p for p in candidate.pages if p.physical_page != (1 if outcome == "rejected" else 3)]
                return candidate
            monkeypatch.setattr(pdf, "extract_pdf", parse)
        if outcome == "interrupted":
            with child(lib, "text", "parser"):
                pass
            asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
        elif outcome == "file_only":
            tear(lib)
            write(lib)
        else:
            result = retry(active)
            assert result["outcome"] == ("diagnosis_updated" if outcome == "diagnosis" else outcome)
        changed = outcome in ("promoted", "diagnosis")
        protected_rows(lib.conn, before, changed_asset=active.aid if changed else None,
                       changed_head=old_head["id"] if changed else None)
        for saved in lib.snapshots:
            reasons = stale_reasons(lib.rich["reader"], saved)
            for entry in saved["content"]["evidence_manifest"]:
                codes = {r["code"] for r in reasons if r.get("passage_id") == entry["passage_id"]}
                assert codes == ({"extraction_changed", "text_superseded"} if outcome == "promoted" else set())
        assert research_view(lib.store, lib.rid)["answers"][0]["source_text_changed"] is (outcome == "promoted")
        record = lib.conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (lib.rich["cell_id"],)).fetchone()
        cell = TableStore(lib.store).cell_view(lib.rid, record["table_id"], record["column_id"], lib.svid)
        assert ("text_superseded" in cell["flags"]) is (outcome == "promoted")
        retrieval(lib)


def test_s5_already_superseded_snapshot_guard(tmp_path):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        retry(lib)
        reader = lib.rich["reader"]
        content, markers = build_snapshot(reader, lib.rid, "answer", lib.answer_id)
        sid = lib.rich["reviews"].add_snapshot(content, markers)
        saved = lib.rich["reviews"].snapshot(sid)
        for entry in content["evidence_manifest"]:
            assert entry["evidence_status"] == "text_superseded"
            assert entry["passage_extraction_id"] != entry["current_extraction_id_at_snapshot"]
        assert stale_reasons(reader, saved) == []
        # A separate ordinary tool promotion moves the live dependency again.
        candidate = pdf.extract_pdf(lib.path)
        lib.store.reextract_asset(lib.aid, candidate, "SYNTHETIC-later-tool", pdf.chunk_page)
        assert {r["code"] for r in stale_reasons(reader, saved)} == {"extraction_changed"}


@pytest.mark.parametrize("outcome", ["promoted", "rejected", "no_change", "diagnosis"])
def test_s14_current_only_retrieval_guard(tmp_path, monkeypatch, outcome):
    with store_library(tmp_path, "partial") as lib:
        real = pdf.extract_pdf
        if outcome in ("rejected", "no_change"):
            def parse(path):
                value = real(path)
                value.status = "partial"
                value.pages = [p for p in value.pages if p.physical_page != (1 if outcome == "rejected" else 3)]
                return value
            monkeypatch.setattr(pdf, "extract_pdf", parse)
        if outcome == "diagnosis":
            extra = seed(lib.store, lib.settings, "no_text", data=make_pdf(["SYNTHETIC diagnostic asset"]))
            monkeypatch.setattr(pdf, "extract_pdf", lambda path: pdf.Extraction("failed", error=pdf.ERROR_PASSWORD))
            assert retry(extra)["outcome"] == "diagnosis_updated"
            assert not extra.store.passages_for(extra.svid) and not extra.store.has_pdf_text(extra.svid)
        else:
            assert retry(lib)["outcome"] == outcome
        retrieval(lib)


@pytest.mark.parametrize("origin", ["attachment", "upgrade"])
@pytest.mark.parametrize("next_read", ["same_locked", "same_owned", "different", "retry"])
def test_s16_abandoned_copy_swept_new_contract(tmp_path, monkeypatch, origin, next_read):
    """Paired with S6/S7; the killed parser leaves bytes, never an input observation."""
    with store_library(tmp_path, "partial") as lib:
        if origin == "upgrade":
            # CLI selects an older profile; update a separate freshly created fixture.
            lib = seed(lib.store, lib.settings, "partial", version="SYNTHETIC-older",
                       data=make_pdf(["SYNTHETIC upgrade abandoned"] * 3))
        with verified_child(lib, origin):
            pass
        abandoned = list((lib.settings.recovery_dir / "tmp").glob(lib.sha + "-*.pdf"))
        assert len(abandoned) == 1
        target = seed(lib.store, lib.settings, "partial", data=make_pdf(["SYNTHETIC other hash"] * 3)) if next_read == "different" else lib
        if next_read == "retry":
            retry(lib)
        else:
            def read(lock):
                return asyncio.run(text_retry.read_verified(target.store, target.settings.papers_dir, target.settings.recovery_dir,
                    storage_path=target.path.name, sha256=target.sha, byte_size=len(target.data), lock=lock))
            if next_read == "same_owned":
                with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
                    read(False)
            else:
                read(True)
        assert not any(p.exists() for p in abandoned)


def test_s16_live_copy_survives_other_hash_sweep_new_contract(tmp_path):
    """Paired with S6/S7; sweeping never deletes another live parser's input."""
    with store_library(tmp_path, "partial") as lib:
        other = seed(lib.store, lib.settings, "partial", data=make_pdf(["SYNTHETIC distinct hash"] * 3))
        with verified_child(lib, "attachment", parked=True):
            copies = list((lib.settings.recovery_dir / "tmp").glob(lib.sha + "-*.pdf"))
            assert len(copies) == 1
            asyncio.run(text_retry.read_verified(other.store, other.settings.papers_dir, other.settings.recovery_dir,
                storage_path=other.path.name, sha256=other.sha, byte_size=len(other.data), lock=True))
            assert copies[0].exists()


def test_s14b_frozen_seed_plan_lineage_and_candidate_guard(tmp_path):
    """No model runs: stored synthetic proposals retain their old passage identities."""
    from deixis.domain import skill
    from deixis.workflow import person_reading
    from deixis.workflow.candidates.store import CandidateStore
    from deixis.workflow.decisions import DecisionStore
    from deixis.workflow.flow import FlowDeps, ResearchFlow
    from deixis.workflow.lineage.store import LineageStore
    from deixis.workflow.lineage.view import LineageView
    from tests.candidates.test_candidate_store import version, start, assessment
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        store, conn = lib.store, lib.conn
        quote = store.passage(lib.pid)["text"]
        seed_rid = store.create_research("SYNTHETIC PDF seed relays?", "attached_and_academic", "quick", [], "fake", "fake", None)
        store.add_to_corpus(seed_rid, lib.svid, "user_upload")
        store.set_seed(seed_rid, store.research(seed_rid)["version"], lib.svid)
        seed_scope = store.scope(seed_rid)
        assert store.seed_status(seed_rid) == "ready"
        flow = ResearchFlow(FlowDeps(lib.settings, store, {}, skill.load_skill_package(), None))
        run = store.create_run(lib.rid, "fulltext_adjudication", {}, None)
        step = store.step(run["id"], "adjudication_plan", "code:adjudication_plan")
        item = flow._plan_item(lib.svid, lib.svid)
        plan = {"works": [item], "scope_revision": 1, "criterion_hash": store.criterion_key(lib.rid)[1]}
        store.finish_step(step["id"], "succeeded", output=plan)
        person_reading.insert_request(store, lib.rid, lib.svid, lib.aid)
        decision = DecisionStore(store).record(lib.rid, lib.svid, "all_parts_verified", step_id=step["id"])
        person_reading.mark_read(store, store.run(run["id"]), item, plan, decision["id"])
        conn.execute("INSERT INTO model_proposals (id, research_id, source_version_id, stage, step_id, run_no,"
            " criterion_part, label, quote, quote_verified, quote_passage_id, quote_page, created_at)"
            " VALUES (?, ?, ?, 'fulltext', ?, 1, 'SYNTHETIC part', 'present', ?, 1, ?, 1, ?)",
            (db.new_id("mpr"), lib.rid, lib.svid, step["id"], quote, lib.pid, db.now()))
        store.update_run(run["id"], status="completed")
        before_quotes = person_reading._verified_quotes(store, lib.svid, step["id"])
        assert before_quotes and flow._file_holds(item)
        seed_run = store.create_run(seed_rid, "answer", {}, None)
        seed_step = store.step(seed_run["id"], "r3:seed-vocabulary", "code:vocabulary")
        store.insert_step_input(seed_step["id"], seed_rid, seed_run["id"], 0,
            {"step_input_id": db.new_id("sti"), "task_type": "vocabulary", "scope_revision": seed_scope["revision"],
             "skill_package_hash": "SYNTHETIC", "question": {"text": seed_scope["question"]},
             "seed": seed_scope["seed_snapshot"], "passages": [{"passage_id": lib.pid}]}, "base", "developer", "message", {})
        store.update_run(seed_run["id"], status="completed")
        cell = dict(conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (lib.rich["cell_id"],)).fetchone())
        earlier = store.create_upload_source("SYNTHETIC earlier method")
        store.add_to_corpus(lib.rid, earlier, "user_upload", selection_state="included", selection_origin="user")
        TableStore(store).add_rows(lib.rid, cell["table_id"], [earlier], TableStore(store)._table(lib.rid, cell["table_id"])["version"])
        lineage = LineageStore(store)
        lineage.add_link(lib.rid, cell["table_id"], earlier, lib.svid, relation="extends",
            what_changed="SYNTHETIC extension", support_type="source_stated",
            evidence=[{"passage_id": lib.pid, "quote": quote}], note=None, expected_version=0, idempotency_key=None)
        candidates = CandidateStore(store)
        candidate = candidates.open_from_gap(lib.rid, lib.report_id, lib.gap_id)
        candidate_lib = SimpleNamespace(store=store, conn=conn, rid=lib.rid, candidate_store=candidates)
        v = version(candidate_lib, candidate)
        search = start(candidate_lib, v)
        conn.execute("INSERT INTO kill_search_hits (kill_search_id, source_version_id, work_id, rank_key, kept, reading_depth, assessment_state)"
            " VALUES (?, ?, ?, 1, 1, 'stored_passages', 'pending')", (search["id"], lib.svid, store.source(lib.svid)["work_id"]))
        candidates.publish_assessment(search["id"], lib.svid, **assessment(candidate_lib, search, passage_id=lib.pid))
        candidates.finish_kill_search(search["id"], "completed")
        before = all_rows(conn)
        retry(lib)
        protected_rows(conn, before, changed_asset=lib.aid, changed_head=lib.eid)
        assert store.scope(seed_rid) == seed_scope and store.seed_status(seed_rid) == "stale"
        assert store.existing_step(run["id"], "adjudication_plan")["output"] == plan
        assert person_reading._verified_quotes(store, lib.svid, step["id"]) == before_quotes
        assert not flow._file_holds(item)
        assert not store.person_files(lib.rid)[lib.svid]["holds"]
        value = LineageView(store).view(lib.rid, cell["table_id"])
        link = value["history"]["stale"][0]
        assert link["stale_reasons"] == ["evidence_not_current"]
        assert link["evidence"][0]["passage_id"] == lib.pid
        assert json.loads(candidates.candidate(candidate["id"])["origin_basis_view_json"])["basis_passage_ids"][0]["text"] == quote
        assert all(e["passage_id"] == lib.pid for e in candidates.evidence(search["id"]))
        assert store.passage(lib.pid)["text"] == quote

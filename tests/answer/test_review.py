"""Synthetic request/transaction checks against the real app and Worker."""

import copy
import json
import pytest
from deixis.storage import db
from deixis.workflow.features.report.report_store import ReportStore
from deixis.workflow.features.review.review_store import ReviewStore
from fakes import FakeAdapter
from review_helpers import report_with_sections, review_lib, all_rows
from review_run_helpers import review_api, body, preview, start, read, turn, control
from deixis.domain import contracts
from deixis.models.adapter import ModelStepResult
from deixis.workflow.features.review import review_run as reviews
from deixis.workflow.features.review.review_store import ReviewStore
from fakes import FakeAdapter
from review_helpers import report_with_sections, review_lib
from review_run_helpers import review_api, body, start, read, turn, control, two_groups, finding_response
import hashlib
import sqlite3
import time
from review_run_helpers import review_api, start, read, control, terminal, two_groups, finding_response
import ast
from pathlib import Path
from deixis.workflow.features.review.review_snapshot import build_snapshot
from deixis.workflow.features.review.review_stale import stale_reasons
from deixis.domain import contracts, skill
from deixis.workflow.run.flow import CAPABILITIES
from review_helpers import report_with_sections, review_lib, si
from deixis.workflow.features.review.review_stale import stale_reasons
from deixis.workflow.features.review.review_store import NotFound
from review_helpers import report_with_sections, review_lib, snapshot, make_answer
from test_report_claim_links import edit


@pytest.fixture
def api(review_lib, tmp_path):
    with review_api(review_lib, tmp_path) as api:
        yield api


def completed(api, kind="report"):
    opened, _, _ = start(api, body(api, kind))
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "completed", card
    return card


def decision_url(api, card, finding=None, action="decisions"):
    fid = (finding or card["findings"][0])["id"]
    return f"{api.url}/{card['id']}/findings/{fid}/{action}"


def apply_body(api, card, finding=None):
    finding = finding or card["findings"][0]
    claim = api.conn.execute("SELECT version FROM report_claims WHERE id = ?", (finding["finding"]["target"]["record_id"],)).fetchone()
    return {"text": "SYNTHETIC suggested edit.", "link_ids": None, "note": None,
            "expected_version": claim[0], "dependency_fingerprint": finding["dependency_fingerprint"]}


def test_preview_is_read_only_every_table_and_counts(api):
    before = all_rows(api.conn)
    denied = []
    def guard(action, table, column, database, trigger):
        if action in (9, 18, 23):
            denied.append((action, table, column))
            return 1
        return 0
    api.conn.set_authorizer(guard)
    try:
        shown = preview(api)
        assert not denied
        assert all_rows(api.conn) == before
    finally:
        api.conn.set_authorizer(None)
    assert shown["logical_steps"] == 1
    assert shown["steps_with_repair_bound"] == 2 and shown["total_send_bound"] == 6
    assert shown["cost_estimated"] is False
    assert shown["estimated_input_tokens_total"] == shown["characters_to_be_sent"] / 4
    assert shown["connection"] == "fake"


@pytest.mark.parametrize("kind", ["answer"])
def test_preview_start_list_read_routes_and_research_view(api, kind):
    api.client._transport.raise_server_exceptions = True
    opened, _, _ = start(api, body(api, kind))
    rid, run_id = opened["review"]["id"], opened["run"]["id"]
    assert opened["run"]["stage"] == "claim_check"
    assert read(api, rid)["state"] == "queued"
    assert api.client.get(f"/api/researches/{api.rid}").status_code == 200
    api.store.update_run(run_id, status="running")
    assert read(api, rid)["state"] == "running"
    assert api.client.get(f"/api/researches/{api.rid}").status_code == 200
    api.store.update_run(run_id, status="queued")
    turn(api)
    card = read(api, rid)
    assert card["state"] == "completed"
    assert api.client.get(f"/api/researches/{api.rid}").status_code == 200
    assert card["requested_model"] == {"connection": "fake", "model": "review-model", "reasoning_effort": "high"}
    assert card["models_that_answered"][0]["requested_model"] == card["models_that_answered"][0]["resolved_model"] == "review-model"
    assert card["findings"][0]["finding"]["group_index"] == 1
    assert card["supported_points"][0]["evidence"][0]["anchor_match"] == "exact"
    assert card["assessment_notice"] == "This is an assessment by a model. It is not peer review and not independent verification."
    listing = api.client.get(api.url, params={"target_kind": kind, "target_id": getattr(api, kind + "_id")})
    assert listing.status_code == 200 and listing.json()[0]["id"] == rid
    assert listing.json()[0]["finding_count"] == listing.json()[0]["open_finding_count"] == 1
    assert api.adapter.sent == [("owner_review", "review-model", "high")]


def test_decision_idempotency_expected_ordinal_and_answer_accept_no_change(api):
    card = completed(api, "answer")
    command = {"decision": "accepted", "reason": None, "expected_ordinal": 0}
    url = decision_url(api, card)
    response = api.client.post(url, json=command, headers={"Idempotency-Key": "decision"})
    assert response.status_code == 200 and response.json()["no_change_made"] is True
    before = all_rows(api.conn)
    replay = api.client.post(url, json=command, headers={"Idempotency-Key": "decision"})
    assert replay.status_code == 200 and replay.json() == response.json()
    assert all_rows(api.conn) == before
    changed = api.client.post(url, json=command | {"reason": "different"}, headers={"Idempotency-Key": "decision"})
    assert changed.status_code == 409 and changed.json()["code"] == "idempotency_key_reused"
    stale = api.client.post(url, json=command, headers={"Idempotency-Key": "new"})
    assert stale.status_code == 409 and stale.json()["code"] == "decision_changed"
    for command in ({"decision": "dismissed", "reason": None, "expected_ordinal": 1},
                    {"decision": "accepted", "expected_ordinal": 1, "applied_ref": "forbidden"}):
        assert api.client.post(url, json=command, headers={"Idempotency-Key": "invalid"}).status_code == 422
    assert read(api, card["id"])["findings"][0]["current_decision"]["ordinal"] == 1


def test_apply_atomically_saves_edit_decision_and_replays_after_later_edit(api):
    card = completed(api)
    command = apply_body(api, card)
    url = decision_url(api, card, action="apply")
    response = api.client.post(url, json=command, headers={"Idempotency-Key": "apply"})
    assert response.status_code == 200, response.text
    assert response.json()["applied_matches_suggestion"] is True
    assert response.json()["decision"]["applied_ref"] == response.json()["revision"]["id"]
    assert response.json()["revision"]["kind"] == "human_edit"
    before = all_rows(api.conn)
    assert api.client.post(url, json=command, headers={"Idempotency-Key": "apply"}).json() == response.json()
    assert all_rows(api.conn) == before
    claim_id = card["findings"][0]["finding"]["target"]["record_id"]
    version = api.conn.execute("SELECT version FROM report_claims WHERE id = ?", (claim_id,)).fetchone()[0]
    ReportStore(api.store).edit_claim(api.rid, api.report_id, claim_id, text="SYNTHETIC later unrelated text.", restore_from=None,
                                     note=None, expected_version=version, idempotency_key=None)
    before = all_rows(api.conn)
    assert api.client.post(url, json=command, headers={"Idempotency-Key": "apply"}).json() == response.json()
    assert all_rows(api.conn) == before
    changed = api.client.post(url, json=command | {"text": "different"}, headers={"Idempotency-Key": "apply"})
    assert changed.status_code == 409 and changed.json()["code"] == "idempotency_key_reused"
    assert read(api, card["id"])["findings"][0]["written_against_earlier_text"] is True


def test_apply_answer_is_not_applicable(api):
    card = completed(api, "answer")
    response = api.client.post(decision_url(api, card, action="apply"), json={"text": "SYNTHETIC", "link_ids": None, "note": None,
        "expected_version": 1, "dependency_fingerprint": "0" * 64}, headers={"Idempotency-Key": "apply"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Only a report-claim finding can be applied through this editor.",
                               "code": "not_applicable"}


class Crash(BaseException):
    """Interrupt outside Worker's ordinary exception-to-failed path."""


def session_count(api, run_id):
    return api.conn.execute("SELECT COUNT(*) FROM model_sessions WHERE run_id = ?", (run_id,)).fetchone()[0]


def test_crash_between_validation_and_repair_resumes_only_one_repair(api, monkeypatch):
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    api.adapter.responder = lambda si: "invalid JSON"
    store = api.store
    finish = store.finish_model_session
    def after_validation(*args, **kwargs):
        finish(*args, **kwargs)
        if kwargs.get("validation_json"):
            raise Crash("SYNTHETIC after validation")
    monkeypatch.setattr(store, "finish_model_session", after_validation)
    with pytest.raises(Crash):
        turn(api)
    api.client.portal.call(api.app.state.worker.recover)
    monkeypatch.setattr(store, "finish_model_session", finish)
    api.adapter.responder = finding_response
    control(api, run_id, "resume")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "completed" and len(api.adapter.calls) == 2
    rows = api.conn.execute("SELECT attempt, user_message FROM step_inputs WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    assert [r["attempt"] for r in rows] == [0, 1]
    assert "previous output" in rows[1]["user_message"]


def test_outcome_unknown_waits_for_user_resume_and_usage_is_not_reset(api):
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    api.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC uncertain delivery", delivery_class="after_send_unknown")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "paused" and card["outcome_unknown"]
    api.client.portal.call(api.app.state.worker.recover)
    turn(api)
    assert len(api.adapter.calls) == session_count(api, run_id) == 1
    api.adapter.fail = None
    control(api, run_id, "resume")
    turn(api)
    assert read(api, opened["review"]["id"])["state"] == "completed"
    assert len(api.adapter.calls) == session_count(api, run_id) == api.store.run(run_id)["usage"]["model_calls"] == 2


@pytest.mark.parametrize("problem,reason", [("mismatch", "model_mismatch")])
def test_unusable_model_calls_pause_without_findings_and_resume_same_model(api, problem, reason):
    opened, _, _ = start(api)
    if problem == "mismatch":
        api.adapter.resolved_model = "different-model"
    elif problem == "isolation":
        api.adapter.fail = lambda si: ModelStepResult("isolation_violation", tool_item_types=["tool"])
    else:
        api.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC failed call")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "paused" and card["pause_reason"] == reason and not card["findings"]
    api.adapter.fail = api.adapter.resolved_model = None
    control(api, opened["run"]["id"], "resume")
    turn(api)
    assert read(api, opened["review"]["id"])["state"] == "completed"
    assert {model for task, model, effort in api.adapter.sent} == {"review-model"}


ALLOWED = {"runs", "run_steps", "step_inputs", "model_sessions", "events",
           "owner_review_snapshots", "owner_reviews", "owner_review_findings", "owner_review_decisions", "sqlite_sequence"}


WRITE_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}


def permitted(action, table, column, conn):
    if table in ALLOWED:
        return True
    if action == sqlite3.SQLITE_UPDATE and (table, column) in {("researches", "updated_at"), ("worker_owner", "heartbeat_at")}:
        return True
    return False


def hashes(conn):
    return {table: hashlib.sha256(repr(rows).encode()).hexdigest() for table, rows in all_rows(conn).items()
            if table not in ALLOWED | {"researches", "worker_owner"}}


@pytest.mark.parametrize("case", ["normal", "cancelled"])
def test_real_worker_api_lifecycle_denies_every_other_write_and_keeps_all_row_hashes(review_lib, tmp_path, monkeypatch, case):
    def respond(si):
        if case == "internal_error":
            raise RuntimeError("SYNTHETIC adapter failure")
        return "invalid JSON" if case == "invalid_output" else finding_response(si)
    adapter = FakeAdapter(responder=respond, delay=.15 if case == "cancelled" else 0)
    with review_api(review_lib, tmp_path, adapter=adapter, start_worker=True) as api:
        two_groups(api, monkeypatch)
        if case == "normal":
            # An unrepresentable third claim is announced rather than shortened.
            section = api.lib["section_ids"]["III"]
            api.conn.execute("INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type)"
                " VALUES (?, ?, 'III.2', 2, 1, ?, 'analyst_inference')", (db.new_id("rcl"), section, "x" * 4001))
        denied, writes = [], []
        def guard(action, table, column, database, trigger):
            if action in WRITE_ACTIONS:
                writes.append((action, table, column))
                if not permitted(action, table, column, api.conn):
                    denied.append((action, table, column))
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        def begin():
            assert "AUTOINCREMENT" in api.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'events'").fetchone()[0]
            before = hashes(api.conn)
            controls = {t: all_rows(api.conn)[t] for t in ("researches", "worker_owner")}
            api.conn.set_authorizer(guard)
            return before, controls
        before, controls = api.client.portal.call(begin)
        try:
            opened, _, _ = start(api)
            if case == "cancelled":
                stop = time.monotonic() + 10
                while not adapter.calls and time.monotonic() < stop:
                    time.sleep(.005)
                assert adapter.calls
                control(api, opened["run"]["id"], "cancel")
            card = terminal(api, opened["review"]["id"])
            # Cancel answers immediately; let the outstanding scripted call and
            # Worker's run-end callback drain before comparing all rows.
            stop = time.monotonic() + 10
            while api.app.state.worker.current_run_id and time.monotonic() < stop:
                time.sleep(.005)
            assert api.app.state.worker.current_run_id is None
            assert not denied, denied
            assert api.client.portal.call(hashes, api.conn) == before
            assert card["state"] == {"normal": "partial", "internal_error": "failed", "invalid_output": "failed", "cancelled": "cancelled"}[case]
            if case == "normal":
                assert len(card["groups"]) == len(card["findings"]) == 2
                assert "claim_text_too_long" in {r["reason"] for r in card["not_reviewed"]}
                assert {r["claim_ref"] for r in card["not_reviewed"]} == {"III.2"}
            if case == "internal_error":
                assert card["failure_reason"] == "internal_error"
            if case == "invalid_output":
                assert card["failure_reason"] == "nothing_reviewed"
                assert len(adapter.calls) == 4 and not card["findings"]
            assert any(t == "worker_owner" and c == "heartbeat_at" for _, t, c in writes)
            # The two narrowly allowed mutable tables retain all other columns.
            after = api.client.portal.call(all_rows, api.conn)
            for table, field in (("researches", "updated_at"), ("worker_owner", "heartbeat_at")):
                columns = [r[1] for r in api.conn.execute(f'PRAGMA table_info("{table}")')]
                index = columns.index(field)
                strip = lambda rows: [r[:index] + r[index + 1:] for r in rows]
                assert strip(controls[table]) == strip(after[table])
        finally:
            api.client.portal.call(api.conn.set_authorizer, None)


def test_review_package_import_and_write_boundary():
    root = Path("deixis/workflow/features/review")
    assert list(root.glob("review_*.py"))
    assert (root / "review_run.py").is_file()
    forbidden = {"deixis.workflow.run.store", "deixis.workflow.features.report.report_store", "deixis.workflow.features.tables.tables",
                 "deixis.workflow.features.candidates.candidates_store", "deixis.workflow.features.lineage.lineage_store", "deixis.workflow.run.flow"}
    for file in root.glob("review_*.py"):
        tree = ast.parse(file.read_text())
        type_only = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                type_only.update(id(n) for child in node.body for n in ast.walk(child))
        for node in ast.walk(tree):
            # `from deixis.workflow import report_store` names the module in the alias, not in `node.module`.
            imported = {node.module} | {f"{node.module}.{n.name}" for n in node.names} if isinstance(node, ast.ImportFrom) else set()
            if imported & forbidden and id(node) not in type_only:
                assert node.module in forbidden and file.name == "review_store.py" and {n.name for n in node.names} <= {"NotFound", "RevisionConflict", "purge_owner_reviews"}
            if isinstance(node, ast.Import) and id(node) not in type_only:
                assert not any(n.name in forbidden for n in node.names)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"edit_claim", "save_claims", "save_answer", "save_review"}
            if isinstance(node, ast.Call):
                if file.name not in {"review_reader.py", "review_store.py"}:
                    assert not (isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany", "executescript", "commit", "rollback"})
                    assert not (isinstance(node.func, ast.Name) and node.func.id == "transaction")
                if file.name == "review_reader.py" and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                    assert isinstance(node.args[0], ast.Constant)
                    assert node.args[0].value.lstrip().upper().startswith(("SELECT", "WITH"))


def test_snapshot_and_stale_reads_leave_every_table_unchanged(review_lib):
    def row_hashes():
        return {table: hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
                for table, rows in all_rows(lib["conn"]).items()}

    lib = review_lib; before = row_hashes()
    content, markers = build_snapshot(lib["reader"], lib["rid"], "report", lib["report_id"])
    assert row_hashes() == before
    row = {"research_id": lib["rid"], "target_kind": "report", "target_id": lib["report_id"], "content": content, "markers": markers}
    assert stale_reasons(lib["reader"], row) == []
    assert row_hashes() == before
    lib["reviews"].add_snapshot(content, markers)
    after = row_hashes()
    assert after["owner_review_snapshots"] != before["owner_review_snapshots"]
    assert {k: v for k, v in after.items() if k != "owner_review_snapshots"} == {k: v for k, v in before.items() if k != "owner_review_snapshots"}


def content(lib, kind="report"):
    return build_snapshot(lib["reader"], lib["rid"], kind, lib[kind + "_id"])[0]


def plan(saved, **kwargs):
    return reviews.plan_groups("rvs_" + "0" * 20, saved, "source_support", None,
        ("fake", "review-model", "high"), skill.load_skill_package(), CAPABILITIES, **kwargs)


def envelope(saved, group, **kwargs):
    return reviews.review_step_input("rvs_" + "0" * 20, saved,
        {"focus": "source_support", "owner_note": "SYNTHETIC owner instruction.",
         "requested_connection": "fake", "requested_model": "review-model"}, group,
        run_id="run_" + "0" * 20, step_id="stp_" + "0" * 20, research_id=saved["research_id"],
        package_hash=skill.package_hash(), capabilities=CAPABILITIES, budget=reviews.review_budget(group["group_count"]),
        step_input_id="sti_" + "0" * 20, created_at=reviews.PLAN_TIME, **kwargs)


@pytest.mark.parametrize("bound,reason", [("text", "claim_text_too_long")])
def test_planner_records_unrepresentable_single_claim_without_truncation(review_lib, bound, reason):
    saved = content(review_lib)
    saved["claims"] = [next(c for c in saved["claims"] if c["claim_ref"] == "III.1")]
    if bound == "text":
        saved["claims"][0]["text"] = "x" * 4001
    elif bound == "citations":
        saved["claims"][0]["citations"] *= 25
    elif bound == "cell":
        saved["cells"][0]["value"] = {"text": "x" * 4001}
    else:
        next(p for p in saved["passages"] if p["passage_id"] == review_lib["section_passage"])["text"] = "x" * 100000
    before = copy.deepcopy(saved)
    result = plan(saved)
    assert not result["groups"]
    assert reason in {r["reason"] for r in result["not_reviewed"]}
    assert all(r["claim_ref"] == "III.1" and r["section_ref"] == "III" for r in result["not_reviewed"])
    assert all(isinstance(r["request_chars"], int) and r["request_chars"] > 0 for r in result["not_reviewed"])
    assert saved == before


@pytest.mark.parametrize("done,omitted,state", [(0, [], "failed")])
def test_completed_coverage_derived_state(done, omitted, state):
    value = reviews.review_state({"status": "completed"}, {"sections_not_reviewed_json": json.dumps(omitted)}, done, 2)
    assert value["state"] == state
    assert value["failure_reason"] == ("nothing_reviewed" if not done else None)


def codes(lib, saved):
    return {r["code"] for r in stale_reasons(lib["reader"], saved)}


@pytest.mark.parametrize("kind", ["answer"])
def test_no_change_has_no_reason_or_not_checked(review_lib, kind):
    saved = snapshot(review_lib, kind)
    assert stale_reasons(review_lib["reader"], saved) == []


def test_newer_answer(review_lib):
    lib = review_lib; saved = snapshot(lib, "answer"); aid = make_answer(lib)
    assert "newer_answer" in codes(lib, saved)
    assert next(r for r in stale_reasons(lib["reader"], saved) if r["code"] == "newer_answer")["answer_id"] == aid


@pytest.mark.parametrize("field", ["revision"])
def test_selection_changed_with_same_included_set(review_lib, field):
    lib = review_lib; saved = snapshot(lib, "answer")
    if field == "stamp": lib["conn"].execute("UPDATE selections SET updated_at = '2099' WHERE research_id = ?", (lib["rid"],))
    else: lib["conn"].execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (lib["rid"],))
    assert "selection_changed" in codes(lib, saved)
    assert not {"sources_added", "sources_removed"} & codes(lib, saved)


def test_claim_edited_names_claim_and_acknowledgement_cannot_clear_it(review_lib):
    lib = review_lib; saved = snapshot(lib); edit(lib, text="SYNTHETIC human change")
    reasons = stale_reasons(lib["reader"], saved)
    assert next(r for r in reasons if r["code"] == "claim_edited")["claim_ref"] == "III.1"
    lib["conn"].execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE id = ?", (lib["cell_id"],))
    keys = [c["key"] for c in lib["reports"].evidence_changes(lib["report_id"])["sections"]["III"]["open"]]
    assert keys
    lib["reports"].acknowledge_changes(lib["rid"], lib["report_id"], "III", keys)
    assert "claim_edited" in codes(lib, saved)


def asset_evidence(lib):
    from deixis.documents.pdf import Extraction, PageText
    from deixis.documents.pdf import chunk_page as chunks
    from helpers import make_pdf
    data = make_pdf(["SYNTHETIC pdf evidence."])
    sha = hashlib.sha256(data).hexdigest()
    asset = lib["store"].add_asset_with_pages(lib["source_id"], sha, len(data), "SYNTHETIC.pdf", "user_upload", None, "SYNTHETIC.pdf",
        Extraction("succeeded", 1, [PageText(1, None, "SYNTHETIC pdf evidence.")]), "synthetic-v1", chunks)
    pid = next(p["id"] for p in lib["store"].passages_for(lib["source_id"]) if p["asset_id"] == asset)
    lib["conn"].execute("INSERT INTO report_citation_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
        " SELECT ?, id, ?, ?, ?, 'SYNTHETIC pdf evidence', 'exact' FROM report_claims WHERE claim_key = 'III.1'",
        (db.new_id("rln"), pid, lib["source_id"], lib["report_input_id"]))
    return asset, pid, data, sha

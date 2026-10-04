"""Synthetic request/transaction checks against the real app and Worker."""

import copy
import json

import pytest

from deixis.storage import db
from deixis.workflow.report.store import ReportStore
from deixis.workflow.review.store import ReviewStore
from tests.fakes import FakeAdapter
from tests.review.review_helpers import report_with_sections, review_lib, all_rows
from tests.review.review_run_helpers import review_api, body, preview, start, read, turn, control


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


@pytest.mark.parametrize("kind", ["answer", "report"])
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


def test_start_content_bound_replay_before_model_availability_and_active_check(api, monkeypatch):
    opened, command, _ = start(api)
    before = all_rows(api.conn)
    def no_wake():
        raise AssertionError("an exact replay must not wake the worker")
    monkeypatch.setattr(api.app.state.worker, "wake", no_wake)
    api.app.state.adapters.clear()
    response = api.client.post(api.url, json=command, headers={"Idempotency-Key": "SYNTHETIC-start"})
    assert response.status_code == 202 and response.json() == opened
    assert all_rows(api.conn) == before
    command["snapshot_sha256"] = "0" * 64
    conflict = api.client.post(api.url, json=command, headers={"Idempotency-Key": "SYNTHETIC-start"})
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "This key was used for a different review request.",
                               "code": "idempotency_key_reused"}
    assert all_rows(api.conn) == before


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_start_active_run_rule_all_kinds_and_paused_does_not_block(api, status):
    data = body(api)
    shown = preview(api)
    prior = api.store.create_run(api.rid, "answer", {}, None)
    api.store.update_run(prior["id"], status=status)
    response = api.client.post(api.url, json=data | {k: shown[k] for k in ("snapshot_sha256", "preview_fingerprint")},
        headers={"Idempotency-Key": "other"})
    assert response.status_code == (202 if status == "paused" else 409)
    if status != "paused":
        assert response.json()["code"] == "run_active"


@pytest.mark.parametrize("change,code", [("target", "target_changed"), ("note", "preview_changed"), ("package", "preview_changed")])
def test_start_distinguishes_target_and_preview_changes(api, change, code):
    command = body(api)
    shown = preview(api)
    command |= {k: shown[k] for k in ("snapshot_sha256", "preview_fingerprint")}
    if change == "target":
        claim = api.conn.execute("SELECT * FROM report_claims WHERE claim_key = 'III.1'").fetchone()
        ReportStore(api.store).edit_claim(api.rid, api.report_id, claim["id"], text="SYNTHETIC changed text.",
            restore_from=None, note=None, expected_version=claim["version"], idempotency_key=None)
    elif change == "note":
        command["owner_note"] = "SYNTHETIC different note"
    else:
        from dataclasses import replace
        api.app.state.package = replace(api.app.state.package, package_hash="sha256:" + "0" * 64)
    before = all_rows(api.conn)
    response = api.client.post(api.url, json=command, headers={"Idempotency-Key": "changed"})
    assert response.status_code == 409 and response.json()["code"] == code, response.text
    assert all_rows(api.conn) == before


@pytest.mark.parametrize("route", ["preview", "start"])
@pytest.mark.parametrize("changes", [{"owner_note": " "}, {"owner_note": "x" * 501}, {"focus": "novelty"},
    {"model": None}, {"model": "unlisted"}, {"connection": "absent"}, {"reasoning_effort": "unlisted"}, {"extra": True}])
def test_review_requests_reject_invalid_fields_before_writes(api, route, changes):
    command = body(api) | changes
    if route == "start":
        command |= {"snapshot_sha256": "0" * 64, "preview_fingerprint": "0" * 64}
    before = all_rows(api.conn)
    response = api.client.post(api.url + ("/preview" if route == "preview" else ""), json=command,
        headers={"Idempotency-Key": "invalid"})
    assert response.status_code == 422, response.text
    assert all_rows(api.conn) == before


@pytest.mark.parametrize("route", ["preview", "start"])
@pytest.mark.parametrize("case,code", [("invalid", "not_reviewable"), ("oversize", "nothing_reviewable")])
def test_nonreviewable_targets_refused(api, route, case, code):
    command = body(api, "answer")
    if case == "invalid":
        api.conn.execute("UPDATE answers SET status = 'unverified_draft' WHERE id = ?", (api.answer_id,))
    else:
        api.conn.execute("UPDATE claims SET text = ? WHERE answer_id = ?", ("x" * 4001, api.answer_id))
    if route == "start":
        command |= {"snapshot_sha256": "0" * 64, "preview_fingerprint": "0" * 64}
    response = api.client.post(api.url + ("/preview" if route == "preview" else ""), json=command, headers={"Idempotency-Key": "invalid"})
    assert response.status_code == 422, response.text
    details = {"invalid": "answer: unverified_draft", "oversize": "No claim fits the review input bounds."}
    expected = {"detail": details[case], "code": code}
    if case == "oversize":
        size = response.json()["not_reviewed"][0]["request_chars"]
        assert type(size) is int and size > 0
        expected["not_reviewed"] = [{"claim_ref": "c1", "section_ref": None,
                                     "reason": "claim_text_too_long", "request_chars": size}]
    assert response.json() == expected


def test_same_research_model_is_allowed(api):
    opened, _, _ = start(api, body(api, model="fake-model", reasoning_effort=None))
    turn(api)
    assert read(api, opened["review"]["id"])["state"] == "completed"
    assert api.adapter.sent == [("owner_review", "fake-model", None)]


def test_review_reads_hide_other_research_and_trash_and_newest_first(api):
    card = completed(api)
    other = api.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake-model", "en")
    assert api.client.get(f"/api/researches/{other}/reviews/{card['id']}").status_code == 404
    second, _, _ = start(api, key="second")
    control(api, second["run"]["id"], "cancel")
    listing = api.client.get(api.url, params={"target_kind": "report", "target_id": api.report_id}).json()
    assert [c["id"] for c in listing] == [second["review"]["id"], card["id"]]
    api.store.trash_research(api.rid)
    assert api.client.get(api.url + "/" + card["id"]).status_code == 404
    assert api.client.get(api.url, params={"target_kind": "report", "target_id": api.report_id}).json() == []


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


def test_apply_rolls_back_human_revision_when_decision_write_fails(api, monkeypatch):
    card = completed(api)
    before = all_rows(api.conn)
    def interrupted(*args, **kwargs):
        raise RuntimeError("SYNTHETIC after editor save")
    monkeypatch.setattr(ReviewStore, "add_decision", interrupted)
    response = api.client.post(decision_url(api, card, action="apply"), json=apply_body(api, card), headers={"Idempotency-Key": "apply"})
    assert response.status_code == 500
    assert all_rows(api.conn) == before


@pytest.mark.parametrize("change", ["cell_revision", "selection", "omitted_citation"])
def test_apply_dependency_change_including_original_omitted_citation_is_409(api, change):
    if change == "omitted_citation":
        claim = api.conn.execute("SELECT * FROM report_claims WHERE claim_key = 'III.1'").fetchone()
        ReportStore(api.store).edit_claim(api.rid, api.report_id, claim["id"], text=None, link_ids=[], restore_from=None,
            note=None, expected_version=claim["version"], idempotency_key=None)
    card = completed(api)
    # Both report claims fit one call. Script a finding on the cell-citing claim
    # when testing a dependency of that claim.
    if change != "selection":
        from deixis.workflow.review.store import resolve_finding
        saved = ReviewStore(api.conn).snapshot(card["snapshot"]["id"])
        payload = api.store.step_input_payload(card["models_that_answered"][0]["step_input_id"])
        original = copy.deepcopy(card["findings"][0]["finding"])
        original["target_ref"] = {"kind": "claim", "ref": "III.1"}
        fid = ReviewStore(api.conn).add_findings(card["id"], [resolve_finding(saved["content"], payload, original)])[0]
        card = read(api, card["id"])
        finding = next(f for f in card["findings"] if f["id"] == fid)
    else:
        finding = card["findings"][0]
    command = apply_body(api, card, finding)
    if change == "selection":
        api.conn.execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (api.rid,))
    elif change == "cell_revision":
        # A real human cell revision, with no passage change.
        from deixis.workflow.tables import TableStore
        cell = api.conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (api.lib["cell_id"],)).fetchone()
        TableStore(api.store).edit_cell(api.rid, cell["table_id"], cell["column_id"], cell["source_version_id"],
            state="value", value={"text": "SYNTHETIC changed value"}, note=None,
            keep_evidence_from=cell["current_revision_id"],
            expected_version=cell["version"], idempotency_key=None)
    else:
        original_links = ReportStore(api.store).original_links(finding["finding"]["target"]["record_id"])
        command["link_ids"] = [l["id"] for l in original_links]
        # Source asset metadata is an original citation dependency even when
        # the effective citation set is empty. Use the cell revision token,
        # which can change independently of passage text.
        cell = api.conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (api.lib["cell_id"],)).fetchone()
        api.conn.execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE id = ?", (cell["id"],))
    before = all_rows(api.conn)
    response = api.client.post(decision_url(api, card, finding, "apply"), json=command, headers={"Idempotency-Key": "changed"})
    assert response.status_code == 409 and response.json()["code"] == "dependencies_changed", response.text
    assert all_rows(api.conn) == before


def test_apply_answer_is_not_applicable(api):
    card = completed(api, "answer")
    response = api.client.post(decision_url(api, card, action="apply"), json={"text": "SYNTHETIC", "link_ids": None, "note": None,
        "expected_version": 1, "dependency_fingerprint": "0" * 64}, headers={"Idempotency-Key": "apply"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Only a report-claim finding can be applied through this editor.",
                               "code": "not_applicable"}


@pytest.mark.parametrize("status", ["queued", "running", "paused"])
def test_api_cancel_queued_running_paused_reviews_has_defined_state(api, status):
    opened, _, _ = start(api)
    if status == "paused":
        control(api, opened["run"]["id"], "pause")
    elif status == "running":
        api.store.update_run(opened["run"]["id"], status="running")
    control(api, opened["run"]["id"], "cancel")
    assert read(api, opened["review"]["id"])["state"] == "cancelled"


def test_apply_expected_claim_version_conflict_and_unrelated_edit_match_false(api):
    card = completed(api)
    command = apply_body(api, card)
    url = decision_url(api, card, action="apply")
    conflict = api.client.post(url, json=command | {"expected_version": command["expected_version"] + 1}, headers={"Idempotency-Key": "wrong-version"})
    assert conflict.status_code == 409
    saved = api.client.post(url, json=command | {"text": "SYNTHETIC owner alternative wording."}, headers={"Idempotency-Key": "alternative"})
    assert saved.status_code == 200 and saved.json()["applied_matches_suggestion"] is False


def test_start_rolls_back_run_snapshot_review_and_events_on_interrupted_join(api, monkeypatch):
    shown = preview(api)
    before = all_rows(api.conn)
    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC after run and snapshot")
    monkeypatch.setattr(ReviewStore, "create_review", fail)
    response = api.client.post(api.url, json=body(api) | {k: shown[k] for k in ("snapshot_sha256", "preview_fingerprint")}, headers={"Idempotency-Key": "interrupted"})
    assert response.status_code == 500
    assert all_rows(api.conn) == before


@pytest.mark.parametrize("route", ["trash", "source"])
def test_unreadable_snapshot_purge_returns_sentence_and_deletes_nothing(api, route):
    card = completed(api)
    # Migration-level fixture: replace the immutable content through temporary
    # removal of its no-update trigger, then restore that trigger verbatim.
    sql = api.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'owner_review_snapshots_no_update'").fetchone()[0]
    api.conn.execute("DROP TRIGGER owner_review_snapshots_no_update")
    api.conn.execute("UPDATE owner_review_snapshots SET content_json = 'invalid-json' WHERE id = ?", (card["snapshot"]["id"],))
    api.conn.execute(sql)
    if route == "trash":
        api.store.trash_research(api.rid)
    else:
        # Request a removed, uncited source so the snapshot scan is the first
        # failing protection rather than an existing citation conflict.
        sid = api.store.create_upload_source("SYNTHETIC unused source")
        api.store.add_to_corpus(api.rid, sid, "user_upload")
        api.conn.execute("UPDATE corpus_memberships SET removed_at = 'now' WHERE source_version_id = ?", (sid,))
    before = all_rows(api.conn)
    response = api.client.delete(f"/api/trash/{api.rid}") if route == "trash" else api.client.post(
        f"/api/researches/{api.rid}/sources/purge", json={"source_version_ids": [sid]})
    assert response.status_code == 409, response.text
    assert response.json() == {"code": "snapshot_dependency_unreadable", "detail": "A stored review snapshot could not be read, so nothing was deleted."}
    assert all_rows(api.conn) == before

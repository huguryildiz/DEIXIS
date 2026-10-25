"""SYNTHETIC real API/worker, frozen read models, decisions and bounded repair."""

import json
import pytest
from deixis.workflow.candidates_store import CandidateStore
from fakes import FakeAdapter
from review_candidate_helpers import report_with_sections, review_lib, candidate_lib, candidate_body, candidate_response, add_version
from review_run_helpers import review_api, start, read, turn, control
import sqlite3
import time
from review_candidate_helpers import report_with_sections, review_lib, candidate_lib, candidate_body, candidate_response
from review_helpers import all_rows
from review_run_helpers import review_api, start, terminal, control
from test_review import permitted, hashes, WRITE_ACTIONS
import copy
from deixis.domain import contracts
from review_helpers import si
from review_candidate_helpers import candidate_response, candidate_context_fixture
from deixis.domain.canonical import canonical_json
from deixis.workflow.review_snapshot import build_snapshot, NotReviewable, review_step_input_parts
from deixis.workflow.review_store import _snapshot_source_ids
from review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot, add_version, search
from test_review import envelope
from deixis.workflow.review_stale import stale_reasons
from review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot, search, add_version
from deixis.workflow.review_snapshot import ReviewInputTooLarge, review_step_input_parts
from review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot
from test_review import plan, envelope
from deixis.domain.rules import RevisionConflict
from deixis.workflow.review_store import snapshot_referenced_source_versions
from review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot, candidate_body, candidate_response
from review_helpers import rows, all_rows
from review_run_helpers import review_api, start, turn, read
from test_review_records import TABLES


def test_candidate_preview_start_read_decide_apply_and_reopen_version_one(candidate_lib, tmp_path):
    lib = candidate_lib
    with review_api(lib, tmp_path, adapter=FakeAdapter(responder=candidate_response, models=["review-model"], efforts=["high"])) as api:
        opened, command, preview = start(api, candidate_body(lib))
        target = api.store.run(opened["run"]["id"])["target"]
        assert target["target_kind"] == "candidate"
        assert target["target_id"] == lib["candidate_version_id"]
        assert preview["element_count"] == 3 and preview["matrix_source_count"] == 2 and preview["claim_count"] == 0
        assert preview["passage_count"] == 4 and preview["total_send_bound"] == 6
        replay = api.client.post(api.url, json=command, headers={"Idempotency-Key": "SYNTHETIC-start"})
        assert replay.json()["review"]["id"] == opened["review"]["id"]
        turn(api); card = read(api, opened["review"]["id"])
        assert card["state"] == "completed" and len(card["findings"]) == 2
        assert card["snapshot"]["candidate_version"] == 1 and len(card["snapshot"]["elements"]) == 3
        assert len(card["snapshot"]["matrix_sources"]) == 2 and len(card["snapshot"]["passages"]) == 4
        row = card["findings"][0]; assert row["finding"]["target"]["text_at_snapshot"].startswith("SYNTHETIC")
        path = api.url + f"/{card['id']}/findings/{row['id']}"
        decision = api.client.post(path + "/decisions", json=dict(decision="accepted", reason=None, expected_ordinal=0), headers={"Idempotency-Key": "SYNTHETIC-accept"})
        assert decision.status_code == 200 and decision.json()["no_change_made"] is True
        applied = api.client.post(path + "/apply", json=dict(text="SYNTHETIC edit", expected_version=1, dependency_fingerprint="0" * 64), headers={"Idempotency-Key": "SYNTHETIC-apply"})
        assert applied.status_code == 422 and applied.json()["code"] == "not_applicable"
        live = dict(lib, store=api.store, conn=api.conn)
        v2 = add_version(live)
        CandidateStore(api.store).record_owner_decision(api.rid, v2["id"], "undecided", "SYNTHETIC later owner")
        reread = read(api, card["id"])
        assert reread["snapshot"] == card["snapshot"]
        assert {r["code"] for r in reread["stale_reasons"]} == {"newer_candidate_version"}
        CandidateStore(api.store).record_owner_decision(api.rid, lib["candidate_version_id"], "undecided", "SYNTHETIC reviewed owner")
        assert {r["code"] for r in read(api, card["id"])["stale_reasons"]} == {"newer_candidate_version", "owner_status_changed"}
        listed = api.client.get(api.url, params=dict(target_kind="candidate", target_id=lib["candidate_version_id"]))
        assert listed.status_code == 200 and len(listed.json()) == 1


@pytest.mark.parametrize("bad", ["passage"])
def test_candidate_unknown_handle_exhausts_bounded_repair_and_records_source_id(candidate_lib, tmp_path, bad):
    def respond(si):
        out = json.loads(candidate_response(si))
        if bad == "passage": out["findings"][0]["evidence"][0]["passage_handle"] = "psg_P0000999"
        else: out["findings"][0]["target_ref"]["ref"] = "e99"
        return json.dumps(out)
    adapter = FakeAdapter(responder=respond)
    with review_api(candidate_lib, tmp_path, adapter=adapter) as api:
        opened, _, _ = start(api, candidate_body(candidate_lib))
        turn(api); card = read(api, opened["review"]["id"])
        assert card["state"] == "failed" and not card["findings"] and len(adapter.calls) == 2
        assert {r["source_id"] for r in card["not_reviewed"]} == {m["source_id"] for m in card["snapshot"]["matrix_sources"]}
        assert {r["reason"] for r in card["not_reviewed"]} == {"invalid_model_output"}
        assert all(r["claim_ref"] is None and r["step_input_id"] for r in card["not_reviewed"])


CANDIDATE_TABLES = {"research_candidates", "candidate_versions", "claim_elements", "kill_searches",
    "kill_search_queries", "kill_search_query_records", "kill_search_hits", "claim_matrix_cells",
    "claim_matrix_evidence", "candidate_status_overrides"}


@pytest.mark.parametrize("case", ["normal", "cancelled"])
def test_candidate_real_worker_api_denies_other_writes_and_preserves_nonempty_candidate_tables(candidate_lib, tmp_path, case):
    def respond(si):
        if case == "internal_error": raise RuntimeError("SYNTHETIC internal failure")
        return "SYNTHETIC invalid JSON" if case == "invalid_output" else candidate_response(si)
    adapter = FakeAdapter(responder=respond, delay=.2 if case == "cancelled" else 0)
    with review_api(candidate_lib, tmp_path, adapter=adapter, start_worker=True) as api:
        denied, writes = [], []
        def guard(action, table, column, database, trigger):
            if action in WRITE_ACTIONS:
                writes.append((action, table, column))
                if not permitted(action, table, column, api.conn):
                    denied.append((action, table, column)); return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        def begin():
            rows = all_rows(api.conn); before = hashes(api.conn)
            assert CANDIDATE_TABLES <= before.keys()
            assert all(rows[t] for t in CANDIDATE_TABLES)
            controls = {t: rows[t] for t in ("researches", "worker_owner")}
            api.conn.set_authorizer(guard)
            return before, controls
        before, controls = api.client.portal.call(begin)
        try:
            opened, _, _ = start(api, candidate_body(candidate_lib))
            if case == "cancelled":
                deadline = time.monotonic() + 10
                while not adapter.calls and time.monotonic() < deadline: time.sleep(.005)
                assert adapter.calls
                control(api, opened["run"]["id"], "cancel")
            card = terminal(api, opened["review"]["id"])
            deadline = time.monotonic() + 10
            while api.app.state.worker.current_run_id and time.monotonic() < deadline: time.sleep(.005)
            assert api.app.state.worker.current_run_id is None
            assert not denied, denied
            assert api.client.portal.call(hashes, api.conn) == before
            assert card["state"] == {"normal": "completed", "internal_error": "failed", "invalid_output": "failed", "cancelled": "cancelled"}[case]
            if case == "normal": assert len(card["findings"]) == 2
            if case == "invalid_output": assert len(adapter.calls) == 2 and len(card["not_reviewed"]) == 2
            assert any(t == "worker_owner" and c == "heartbeat_at" for _, t, c in writes)
            after = api.client.portal.call(all_rows, api.conn)
            for table, field in (("researches", "updated_at"), ("worker_owner", "heartbeat_at")):
                columns = [r[1] for r in api.conn.execute(f'PRAGMA table_info("{table}")')]
                index = columns.index(field)
                strip = lambda rows: [r[:index] + r[index + 1:] for r in rows]
                assert strip(controls[table]) == strip(after[table])
        finally:
            api.client.portal.call(api.conn.set_authorizer, None)


def payload():
    value = si("candidate")
    context = candidate_context_fixture(value)
    value["review_input"]["candidate_context"] = context
    context["matrix"][0]["cells"] = [{"element_ref": "e1", "relation": "partial_match", "condition_alignment": "aligned",
        "note": "SYNTHETIC note", "quotes": [{"passage_id": value["passages"][0]["passage_id"], "quote": value["passages"][0]["text"]}]}]
    context["matrix"][0]["whole_claim_quotes"] = copy.deepcopy(context["matrix"][0]["cells"][0]["quotes"])
    return value


def test_well_formed_candidate_context_is_accepted():
    assert contracts.check_step_input(payload()) == []


@pytest.mark.parametrize("case,code", [("foreign_passage", "review_matrix_passage_source_mismatch"), ("unknown_passage", "review_matrix_passage_missing")])
def test_candidate_context_rejects_each_bad_link_with_its_code(case, code):
    value = payload(); ctx = value["review_input"]["candidate_context"]; source = ctx["matrix"][0]
    if case == "source": source["source_id"] = "srv_UNKNOWN001"
    elif case == "foreign_passage":
        other = copy.deepcopy(value["sources"][0]); other["source_id"] = "srv_OTHER0001"
        value["sources"].append(other); value["allowlist"]["source_ids"].append(other["source_id"])
        value["passages"][0]["source_id"] = other["source_id"]
    elif case == "unknown_element": source["cells"][0]["element_ref"] = "e99"
    elif case == "duplicate_element": source["cells"].append(copy.deepcopy(source["cells"][0]))
    elif case == "answer_context": value = si("answer"); value["review_input"]["candidate_context"] = ctx
    elif case == "candidate_null": value["review_input"]["candidate_context"] = None
    elif case == "absent": del value["review_input"]["candidate_context"]
    elif case == "unknown_passage": source["cells"][0]["quotes"][0]["passage_id"] = "psg_UNKNOWN001"
    else: value["allowlist"]["element_refs"] = []
    assert code in {issue.code for issue in contracts.check_step_input(value)}


def test_candidate_snapshot_equals_stored_input_after_new_version_override_and_passage_edit(candidate_lib, monkeypatch):
    lib = candidate_lib
    saved = snapshot(lib)
    c = saved["content"]
    assert "status" not in c and "validation_plan" not in c
    assert c["candidate_version"] == 1 and len(c["elements"]) == 3
    assert len(c["matrix"]) == 2 and len(c["passages"]) == 4
    assert c["kill_search"]["assessed"] == 2 and c["kill_search"]["unread"] == 1
    payload = envelope(c, {"claim_refs": [], "source_ids": [m["source_id"] for m in c["matrix"]], "group_index": 1, "group_count": 1})
    payload["review_input"]["review_snapshot_id"] = saved["id"]
    assert contracts.check_step_input(payload) == []
    step = lib["store"].step(lib["search"]["run_id"], "SYNTHETIC-frozen-review", "model:owner_review")
    payload["step_id"] = step["id"]
    payload["run_id"] = lib["search"]["run_id"]
    lib["store"].insert_step_input(step["id"], lib["rid"], payload["run_id"], 0, payload, "SYNTHETIC", "SYNTHETIC", "SYNTHETIC", {})
    before = canonical_json(payload)
    newer = add_version(lib)
    cs = CandidateStore(lib["store"])
    cs.record_owner_decision(lib["rid"], newer["id"], "undecided", "SYNTHETIC later version reason")
    cs.record_owner_decision(lib["rid"], lib["candidate_version_id"], "undecided", "SYNTHETIC reviewed version reason")
    # Passage rows are immutable; simulate a changed read without weakening their triggers.
    live_passage = lib["reader"].passage
    monkeypatch.setattr(lib["reader"], "passage", lambda pid: live_passage(pid) | {"text": "SYNTHETIC edited live passage"})
    assert canonical_json(lib["store"].step_input_payload(payload["step_input_id"])) == before
    parts = review_step_input_parts(saved["id"], lib["reviews"].snapshot(saved["id"])["content"], focus="source_support", owner_note="SYNTHETIC owner instruction.")
    assert {k: payload[k] for k in parts} == parts
    assert _snapshot_source_ids(saved["id"], saved["content_json"]) == {m["source_id"] for m in c["matrix"]}


@pytest.mark.parametrize("case,reason", [("unlocated", "matrix quote is not located in assessment passage")])
def test_broken_assessment_quote_stops_snapshot_without_dropping_evidence(candidate_lib, monkeypatch, case, reason):
    lib = candidate_lib; reader = lib["reader"]
    build_snapshot(reader, lib["rid"], "candidate", lib["candidate_version_id"])
    original = reader.assessment_input
    hit = CandidateStore(lib["store"]).hits(lib["search"]["id"])[0]
    def changed(sti):
        raw = original(sti)
        if sti != hit["step_input_id"]: return raw
        if case == "missing": return None
        data = json.loads(raw)
        if case == "no_abstract": data["passages"] = data["passages"][1:]
        elif case == "two_abstracts": data["passages"][1]["locator"]["kind"] = "abstract"
        elif case == "foreign": data["passages"][0]["source_id"] = "srv_FOREIGN001"
        elif case == "unlocated": data["passages"][0]["text"] = "SYNTHETIC unrelated words"
        else: data["passages"] = data["passages"][:1]
        return json.dumps(data)
    monkeypatch.setattr(reader, "assessment_input", changed)
    with pytest.raises(NotReviewable, match=reason):
        build_snapshot(reader, lib["rid"], "candidate", lib["candidate_version_id"])


def test_owner_status_changed(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib)
    CandidateStore(lib["store"]).record_owner_decision(lib["rid"], lib["candidate_version_id"], "undecided", "SYNTHETIC changed reason")
    assert stale_reasons(lib["reader"], saved) == [{"code": "owner_status_changed", "status": "undecided"}]


def test_scope_revised_for_candidate(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib)
    lib["store"].revise_scope(lib["rid"], lib["store"].research(lib["rid"])["version"], "SYNTHETIC revised scope", None)
    assert stale_reasons(lib["reader"], saved) == [{"code": "scope_revised"}]


@pytest.mark.parametrize("target", ["element"])
@pytest.mark.parametrize("reason", ["passage_changed"])
def test_candidate_evidence_reason_names_element_or_source(candidate_lib, monkeypatch, reason, target):
    lib = candidate_lib; snapshot(lib)  # Reach the old B8 refusal before new reader methods are used.
    reader = lib["reader"]
    content = snapshot(lib)["content"]
    source = content["matrix"][0 if target == "element" else 1]["source_id"]
    passage = next(p for p in content["passages"] if p["source_id"] == source and p["locator"]["kind"] == "pdf_page")
    pid = passage["passage_id"]
    saved = snapshot(lib)
    original = reader.evidence_dependency
    def changed(id_):
        dep = original(id_)
        if id_ != pid: return dep
        if reason == "evidence_missing": return None
        if reason == "passage_changed": dep["text"] += " SYNTHETIC changed"
        if reason == "asset_changed": dep["asset_sha256"] = "b" * 64
        if reason == "extraction_changed": dep["current_extraction_id_at_snapshot"] = "ext_SYNTHNEXT001"
        if reason in {"pdf_replaced", "pdf_removed", "text_superseded"}: dep["evidence_status"] = reason
        return dep
    monkeypatch.setattr(reader, "evidence_dependency", changed)
    expected = {"kind": "candidate_element", "ref": "e1"} if target == "element" else {"kind": "candidate_source", "ref": source}
    rows = stale_reasons(reader, saved)
    assert len(rows) == 1 and rows[0]["code"] == reason
    assert rows[0]["targets"] == [expected] and rows[0]["target_ref"] == expected


def test_source_too_large_is_recorded_without_cutting_passages(candidate_lib):
    c = snapshot(candidate_lib)["content"]
    sid = c["matrix"][0]["source_id"]
    for p in c["passages"]:
        if p["source_id"] == sid: p["text"] = "SYNTHETIC " + "x" * 100000
    original = copy.deepcopy(c)
    planned = plan(c)
    assert len(planned["groups"]) == 1 and planned["groups"][0]["source_ids"] == [c["matrix"][1]["source_id"]]
    assert "source_too_large" in {r["reason"] for r in planned["not_reviewed"]}
    assert {r["source_id"] for r in planned["not_reviewed"]} == {sid}
    assert all(r["claim_ref"] is None and r["section_ref"] is None for r in planned["not_reviewed"])
    assert c == original


@pytest.mark.parametrize("field", ["candidate_statement"])
def test_shared_candidate_bound_refuses_whole_candidate_without_cut(candidate_lib, field):
    c = snapshot(candidate_lib)["content"]
    if field == "conditions": c[field] = ["SYNTHETIC " + "x" * 301]
    elif field == "element": c["elements"][0]["text"] = "SYNTHETIC " + "x" * 4001
    elif field == "owner_reason": c["candidate_status"]["owner"]["reason"] = "SYNTHETIC " + "x" * 2001
    else: c[field] = "SYNTHETIC " + "x" * 4001
    original = copy.deepcopy(c)
    with pytest.raises(ReviewInputTooLarge): review_step_input_parts("rvs_SYNTHSNAP01", c, focus="source_support", owner_note=None)
    planned = plan(c)
    assert planned["groups"] == [] and planned["not_reviewed"][0]["reason"] == "candidate_too_large"
    assert c == original


def test_candidate_snapshot_protects_search_only_sources_and_authorized_purge_orders_rows(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib)
    sid = saved["content"]["matrix"][0]["source_id"]
    assert not lib["conn"].execute("SELECT 1 FROM corpus_memberships WHERE source_version_id=?", (sid,)).fetchone()
    assert sid in snapshot_referenced_source_versions(lib["conn"], [sid])
    third = lib["store"].create_research("SYNTHETIC purge owner", "attached", "quick", [], "fake", None, "en")
    lib["store"].add_to_corpus(third, sid, "user_upload", selection_state="included", selection_origin="user")
    lib["store"].remove_sources(third, [sid], "SYNTHETIC removed")
    before = all_rows(lib["conn"])
    with pytest.raises(RevisionConflict): lib["store"].purge_sources(third, [sid])
    assert all_rows(lib["conn"]) == before
    lib["store"].trash_research(lib["rid"])
    lib["store"].purge_research(lib["rid"])
    assert all(not lib["conn"].execute(f"SELECT 1 FROM {t}").fetchone() for t in TABLES)
    assert not lib["conn"].execute("SELECT 1 FROM research_candidates WHERE research_id=?", (lib["rid"],)).fetchone()
    assert not snapshot_referenced_source_versions(lib["conn"], [sid])
    assert lib["store"].purge_sources(third, [sid])[0] == [sid]
    assert not lib["conn"].execute("PRAGMA foreign_key_check").fetchall()

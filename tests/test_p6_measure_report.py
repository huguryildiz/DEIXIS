"""Report measurement uses stored synthetic reports, GET routes and SQLite copies only."""

from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from deixis.workflow.report.store import ReportStore
from scripts.p6_eval import measure_report as kit
from test_api_flow import app_for, create, session, wait_run
from test_report_api import create_table, fill_table, upload_and_include
from test_report_flow import ReportAdapter


class ReadClient:
    def __init__(self, client):
        self.client = client
        self.methods = []

    def get(self, path):
        self.methods.append("GET")
        return self.client.get(path)


@pytest.fixture
def complete_report(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, rid)
        table = create_table(client, rid, with_columns=True)
        fill_table(client, rid, table)
        started = client.post(f"/api/researches/{rid}/reports", json={"table_id": table["table"]["id"]})
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed"
        yield raw, ReadClient(client), rid, started.json()["target"]["report_id"]


def test_snapshot_deterministic_links_and_zero_denominators(complete_report, tmp_path):
    _, api, rid, report_id = complete_report
    first, again = tmp_path / "first", tmp_path / "again"
    automated = kit.snapshot(api, rid, first, report_id=report_id, sample=30, seed=17)
    kit.snapshot(api, rid, again, report_id=report_id, sample=30, seed=17)
    assert {p.name for p in first.iterdir()} == {"snapshot.json", "automated.json", "review.md"}
    assert first.joinpath("review.md").read_text() == again.joinpath("review.md").read_text()
    assert set(automated) == set(kit.METRICS)
    assert all(row["status"] in {"measured", "not_measurable", "not_readable"} for row in automated.values())
    assert automated["R6"]["status"] == "not_measurable"
    assert automated["R6"]["denominator"] == 0 and automated["R6"]["value"] is None
    assert automated["R8"]["status"] == "not_readable" and automated["R8"]["reason"] == "db_not_supplied"
    assert automated["R7"]["value"]["tokens"]["reason"] == "db_not_supplied"
    assert any(row["depth_reason"] == "frozen_cell_depth_not_in_api"
               for row in automated["R2"]["value"]["links"] if row["cell_id"])
    assert api.methods and set(api.methods) == {"GET"}
    sampled = re.findall(r"^### (C\d+\.L\d+) ·", first.joinpath("review.md").read_text(), re.M)
    assert len(sampled) == automated["R2"]["denominator"]
    assert all(row["quote"] for row in automated["R2"]["value"]["links"])
    assert kit.score(first)["R2"]["sample"] == {"kind": "whole", "seed": 17}


def test_small_sample_can_change_with_seed(complete_report, tmp_path):
    _, api, rid, report_id = complete_report
    sheets = []
    for seed in range(10):
        out = tmp_path / str(seed)
        kit.snapshot(api, rid, out, report_id=report_id, sample=2, seed=seed)
        sheets.append(re.findall(r"^### C\d+\.L\d+ · .*claim `([^`]+)`", (out / "review.md").read_text(), re.M))
    assert len(set(tuple(x) for x in sheets)) > 1


def test_readonly_db_repair_count_and_unmatched_anchor(complete_report, tmp_path):
    raw, api, rid, report_id = complete_report
    store = raw.app.state.store
    store_report = ReportStore(store)
    section = next(s for s in store_report.sections(report_id) if (s.get("draft") or {}).get("citation_anchors"))
    original = store.conn.execute(
        "SELECT l.step_input_id, l.passage_id, l.cell_id, l.source_version_id, l.anchor_text, c.claim_key "
        "FROM report_citation_links l JOIN report_claims c ON c.id = l.claim_id "
        "WHERE c.report_section_id = ? LIMIT 1", (section["id"],),
    ).fetchone()
    store_report.save_claims(section["id"], section["draft"]["claims"], [{**dict(original), "anchor_match": None}])
    iii = next(s for s in store_report.sections(report_id) if s["section_id"] == "III")
    sentence_id = f"{iii['draft']['claims'][0]['claim_key']}#1"
    text = iii["draft"]["claims"][0]["text"]
    store_report.save_phrase_repair(report_id, "III", sentence_id, text, text, "kept")
    copy = tmp_path / "copy.sqlite"
    with sqlite3.connect(copy) as dest:
        store.conn.backup(dest)
    original = copy.read_bytes()
    automated = kit.snapshot(api, rid, tmp_path / "out", report_id=report_id, db_path=copy)
    assert copy.read_bytes() == original
    assert any(not row["anchor_located"] for row in automated["R2"]["value"]["links"])
    assert automated["R8"]["status"] == "measured"
    assert automated["R8"]["value"]["outcomes"]["kept"] == 1
    assert automated["R8"]["value"]["flagged"] <= automated["R8"]["denominator"]
    assert automated["R7"]["value"]["tokens"]["status"] == "measured"
    assert all(row["cell_reading_depth"] for row in automated["R2"]["value"]["links"] if row["cell_id"])
    assert api.methods and set(api.methods) == {"GET"}


def _clone_db_row(conn, table, row, **updates):
    values = {**dict(row), **updates}
    columns = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                 [values[name] for name in columns])


def test_first_completed_output_and_repair_inputs_ignore_resends(complete_report, tmp_path):
    raw, api, rid, report_id = complete_report
    copy = tmp_path / "sessions.sqlite"
    with sqlite3.connect(copy) as dest:
        raw.app.state.store.conn.backup(dest)
    with sqlite3.connect(copy) as conn:
        conn.row_factory = sqlite3.Row
        run_id = conn.execute("SELECT run_id FROM reports WHERE id = ?", (report_id,)).fetchone()[0]
        # Keep this synthetic session history focused on schema output validity.
        conn.execute("DELETE FROM model_sessions WHERE step_input_id IN "
                     "(SELECT id FROM step_inputs WHERE task_type = 'report_phrase_repair' AND run_id = ?)", (run_id,))
        steps = {sid: conn.execute("SELECT id FROM run_steps WHERE run_id = ? AND operation_key = ?",
                                   (run_id, f"report_section:{sid}")).fetchone()[0] for sid in ("III", "IV")}
        initial = {sid: conn.execute("SELECT i.* FROM step_inputs i WHERE i.step_id = ? "
                                     "ORDER BY i.attempt, i.created_at, i.rowid LIMIT 1", (step_id,)).fetchone()
                   for sid, step_id in steps.items()}
        sessions = {sid: conn.execute("SELECT m.* FROM model_sessions m WHERE m.step_input_id = ? "
                                      "AND m.status = 'completed' ORDER BY m.started_at, m.rowid LIMIT 1",
                                      (initial[sid]["id"],)).fetchone() for sid in steps}
        assert all(sessions.values())
        _clone_db_row(conn, "model_sessions", sessions["III"], id="rate_limit_before_output",
                      status="rate_limited", validation_json=None, raw_output=None,
                      started_at="0001-01-01T00:00:00+00:00", finished_at="0001-01-01T00:00:01+00:00")
        conn.execute("UPDATE model_sessions SET validation_json = ? WHERE id = ?",
                     (json.dumps({"ok": False}), sessions["IV"]["id"]))
        _clone_db_row(conn, "step_inputs", initial["IV"], id="schema_repair_input",
                      attempt=initial["IV"]["attempt"] + 1, user_message=kit.REPAIR_MARKER + " issues",
                      created_at="9999-12-31T00:00:00+00:00")
        # A step opened again after a pause writes a normal input (attempt reset), which is not a repair.
        _clone_db_row(conn, "step_inputs", initial["IV"], id="resumed_normal_input", attempt=0,
                      created_at="9999-12-30T12:00:00+00:00")
        _clone_db_row(conn, "model_sessions", sessions["IV"], id="schema_repair_output",
                      step_input_id="schema_repair_input", validation_json=json.dumps({"ok": True}),
                      started_at="9999-12-31T00:00:00+00:00", finished_at="9999-12-31T00:00:01+00:00")
        _clone_db_row(conn, "model_sessions", sessions["IV"], id="rate_limit_during_repair",
                      step_input_id="schema_repair_input", status="rate_limited", validation_json=None,
                      raw_output=None, started_at="9999-12-30T00:00:00+00:00",
                      finished_at="9999-12-30T00:00:01+00:00")
        conn.commit()
    before = copy.read_bytes()
    measured = kit.snapshot(api, rid, tmp_path / "out", report_id=report_id, db_path=copy)
    assert copy.read_bytes() == before
    by_section = {row["section"]: row for row in measured["R1"]["value"]["sections"]}
    assert by_section["III"]["first_try_valid"] is True
    assert by_section["III"]["schema_repair_attempts"] == 0
    assert by_section["III"]["resend_sessions"] == 1
    assert by_section["IV"]["first_try_valid"] is False
    assert by_section["IV"]["schema_repair_attempts"] == 1
    assert by_section["IV"]["resend_sessions"] == 1
    tokens = measured["R7"]["value"]["tokens"]["value"]
    assert tokens["repair_calls"]["calls"] == 1   # the completed session of the repair input, a resend counted as well
    assert tokens["resend_calls"]["calls"] == 2


def test_missing_opened_passage_has_unknown_source_version(complete_report):
    _, api, rid, report_id = complete_report
    report = deepcopy(api.get(f"/api/researches/{rid}/reports/{report_id}").json())
    claim = next(c for section in report["sections"] for c in section["claims"] if c["evidence"])
    claim["evidence"][0]["open_passage_id"] = "missing_passage_for_measurement"
    links, _ = kit._link_checks(api, rid, report)
    row = next(link for link in links if link["claim_id"] == claim["id"] and link["link_number"] == 1)
    assert row["opens"] is False and row["same_source_version"] is None
    research = api.get(f"/api/researches/{rid}").json()
    run = next(r for r in research["runs"] if r["id"] == report["run_id"])
    r2 = kit.automate(report, research, run, links, None, None)["R2"]
    assert r2["value"]["source_version_matches"] == sum(link["same_source_version"] is True for link in links)
    claim["evidence"][0]["open_passage_id"] = claim["evidence"][0]["passage_id"]
    claim["evidence"][0]["cell_id"] = "missing_cell_for_measurement"
    links, _ = kit._link_checks(api, rid, report)
    row = next(link for link in links if link["claim_id"] == claim["id"] and link["link_number"] == 1)
    assert row["opens"] is True and row["same_source_version"] is False


def test_r8_denominator_is_original_sentences_even_when_a_repair_splits_one():
    def report(text, extra=""):
        return {"status": "valid", "sections": [{"section_id": "III", "status": "valid", "claims": [],
                "draft": {"claims": [{"claim_key": "III.1", "text": text}],
                          "insufficient_evidence": [{"reason": "Evidence is missing." + extra}]}}]}
    run = {"status": "completed", "steps": []}
    # Original: "Unframed one." and "Kept two." (2 sentences) plus one insufficient_evidence sentence = 3.
    # The repair of "Unframed one." split it into two sentences, so the final text has 4.
    final = report("Rewritten a. Rewritten b. Kept two.")
    db = {"sessions": [], "inputs": [], "phrase_repairs": [
        {"section_id": "III", "sentence_id": "III.1#1", "outcome": "kept",
         "before": "Unframed one.", "after": "Rewritten a. Rewritten b."}]}
    r8 = kit.automate(final, {}, run, [], db, None)["R8"]
    assert r8["status"] == "measured" and r8["denominator"] == 3 and r8["value"]["flagged"] == 1
    assert r8["value"]["final_text_sentences"] == 4
    # Two fields that do not end in a full stop are still counted apart (2 original sentences, not 1).
    two = {"status": "valid", "sections": [{"section_id": "III", "status": "valid", "claims": [],
           "draft": {"claims": [{"claim_key": "III.1", "text": "First"}, {"claim_key": "III.2", "text": "Second"}],
                     "insufficient_evidence": []}}]}
    assert kit.automate(two, {}, run, [], {"sessions": [], "inputs": [], "phrase_repairs": []}, None)["R8"]["denominator"] == 2
    # A repair reverted by review leaves the original sentence in the final text.
    reverted = report("Unframed one. Kept two.")
    db["phrase_repairs"] = [{"section_id": "III", "sentence_id": "III.1#1", "outcome": "reverted_exception",
                             "before": "Unframed one.", "after": "Rewritten a. Rewritten b."}]
    r8 = kit.automate(reverted, {}, run, [], db, None)["R8"]
    assert r8["denominator"] == 3 and r8["value"]["outcomes"] == {"reverted_exception": 1}
    # A repair whose text is nowhere in the final draft cannot be resolved: not_readable, not a guess.
    db["phrase_repairs"] = [{"section_id": "III", "sentence_id": "III.1#1", "outcome": "kept",
                             "before": "Lost original.", "after": "Lost rewrite."}]
    r8 = kit.automate(reverted, {}, run, [], db, None)["R8"]
    assert r8["status"] == "not_readable" and r8["reason"] == "repair_text_not_found_in_final_draft"


def test_negative_finder_is_bilingual_and_not_a_judge():
    report = {"sections": [{"section_id": "IV", "claims": [
        {"id": "a", "text": "No study reported it.", "evidence": [{"cell_id": "c1"}]},
        {"id": "b", "text": "Bu konu incelenmedi.", "evidence": [{"cell_id": "c2"}]},
        {"id": "c", "text": "The study reports the method.", "evidence": []}], "draft": {}}]}
    units = kit._negative_units(report)
    assert [u["claim_id"] for u in units] == ["a", "b"]
    assert units[0]["cells"] == ["c1"] and units[1]["cells"] == ["c2"]


def test_second_and_score_marked_units(complete_report, tmp_path):
    _, api, rid, report_id = complete_report
    out = tmp_path / "reading"
    kit.snapshot(api, rid, out, report_id=report_id, sample=3)
    with pytest.raises(ValueError, match="no marked"):
        kit.second(out)
    sheet = (out / "review.md").read_text()
    sheet = sheet.replace("Reader: ", "Reader: analyst", 1)
    sheet = sheet.replace("- [ ] Does not support the claim (wrong citation)",
                          "- [x] Does not support the claim (wrong citation)", 1)
    (out / "review.md").write_text(sheet)
    kit.second(out)
    blind = (out / "second.md").read_text()
    assert "- [x] Does not support" not in blind
    assert re.search(r"### C\d+\.L\d+", blind)
    blind = blind.replace("Reader: ", "Reader: second", 1)
    blind = blind.replace("- [ ] Supports the claim", "- [x] Supports the claim", 1)
    (out / "second.md").write_text(blind)
    results = kit.score(out)
    r2 = results["R2"]["reading"]
    assert r2["value"]["serious"] == 1 and r2["value"]["wrong_claims"] == 1
    assert r2["value"]["disagreements"] == 1
    assert r2["sample"] == {"kind": "drawn", "seed": 20260930}
    assert results["R3"]["reading"]["reason"] == "not_read"
    assert set(json.loads((out / "results.json").read_text())) == set(kit.METRICS)


@pytest.mark.parametrize("shape", ["list", "object"])
def test_seeded_ratios_are_independent_and_partial(tmp_path, shape):
    cases = [{"id": f"RS{i}", "review_caught": i % 2 == 0,
              "assembly_caught": None if i == 7 else i % 3 == 0} for i in range(1, 8)]
    cases.append({"id": "RB01", "review_caught": True, "assembly_caught": True})
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases if shape == "list" else {"cases": cases}))
    row = kit._seeded(path)
    assert row["status"] == "measured"
    assert row["value"]["total_rs"] == 7
    assert row["value"]["review"]["readable"] == 7
    assert row["value"]["assembly"]["readable"] == 6
    assert row["value"]["assembly"]["partial"] is True
    assert row["value"]["neither"]["readable"] == 6


def test_seeded_unmeasurable(tmp_path):
    assert kit._seeded(None)["reason"] == "no_seeded_file"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"id": "RB01"}]))
    assert kit._seeded(path)["reason"] == "no_rs_entries"
    path.write_text(json.dumps([{"id": f"RS{i}", "review_caught": None, "assembly_caught": True}
                                for i in range(6)]))
    review_missing = kit._seeded(path)
    assert review_missing["reason"] == "fewer_than_6_readable"
    assert review_missing["value"]["review"]["status"] == "not_measurable"
    assert review_missing["value"]["assembly"]["status"] == "measured"
    path.write_text(json.dumps([{"id": f"RS{i}", "review_caught": True, "assembly_caught": None}
                                for i in range(6)]))
    result = kit._seeded(path)
    assert result["status"] == "measured" and result["value"]["assembly"]["partial"] is True
    assert result["value"]["assembly"]["status"] == "not_measurable"
    assert result["value"]["assembly"]["reason"] == "fewer_than_6_readable"


def test_added_r3_sentence_requires_cells_and_counts_as_a_unit():
    sheet = """## R3 · negative sentences

#### M1 · IV · No study addressed X · cells: cell_1

- [x] Does not follow the rule

#### M2 · V · None reported Y · cells:

- [x] Does not follow the rule
"""
    units = kit._units(sheet)["R3"]
    row = kit._human_metric(units, {}, "R3", 3, "analyst", None)
    assert row["value"]["total"] == 2
    assert row["value"]["judged"] == 1
    assert row["value"]["serious"] == 1
    assert row["value"]["units"][1]["no_evidence_given"] is True


def test_no_report_refuses_without_writing(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        out = tmp_path / "empty"
        with pytest.raises(ValueError, match="no report"):
            kit.snapshot(ReadClient(client), rid, out)
        assert not out.exists()


def test_draft_is_measured_and_in_progress_only_r1_r7(complete_report, tmp_path):
    raw, api, rid, report_id = complete_report
    raw.app.state.store.conn.execute("UPDATE reports SET status = 'draft', report_version = NULL WHERE id = ?", (report_id,))
    raw.app.state.store.conn.commit()
    draft = kit.snapshot(api, rid, tmp_path / "draft", report_id=report_id)
    assert all(draft[k]["reason"] != "run_incomplete" for k in kit.METRICS)
    raw.app.state.store.conn.execute("UPDATE reports SET status = 'in_progress' WHERE id = ?", (report_id,))
    raw.app.state.store.conn.commit()
    rows = kit.snapshot(api, rid, tmp_path / "in_progress", report_id=report_id)
    assert all(rows[k]["reason"] == "run_incomplete" for k in kit.METRICS if k not in ("R1", "R7"))
    assert rows["R1"]["status"] == "measured" and rows["R7"]["status"] == "measured"

"""Report measurement uses stored synthetic reports, GET routes and SQLite copies only."""

from __future__ import annotations

import json
import random
import re
import sqlite3
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from deixis.domain.contracts import canonical_validator
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


def _complete_reading(path):
    sheet = path.read_text()
    for group, units in kit._units(sheet).items():
        for unit in units.values():
            if unit["marks"] or group not in kit.CHOICES:
                continue
            old = unit["body"]
            new = old.replace(f"- [ ] {kit.CHOICES[group][0]}", f"- [x] {kit.CHOICES[group][0]}", 1)
            sheet = sheet.replace(old, new, 1)
    path.write_text(sheet)


def _complete_both(out):
    _complete_reading(out / "review.md")
    kit.second(out)
    _complete_reading(out / "second.md")


@pytest.fixture
def reading_out(tmp_path):
    """Complete synthetic readings with both small and larger control pools."""
    (tmp_path / "snapshot.json").write_text(json.dumps({"seed": 17}))
    (tmp_path / "automated.json").write_text(json.dumps({key: kit.metric(1, 1) for key in kit.METRICS}))
    lines = ["# First reading", "Reader: analyst", "sampled claims 10/10"]
    for group, prefix, pool in [("R2", "C", 8), ("R3", "N", 2), ("R4b", "D", 6),
                                ("R6", "E", 1), ("R9", "P", 0)]:
        lines.append(f"## {group}")
        choices = kit.CHOICES[group]
        marks = [choices[0]] * pool + list(choices[1:])
        for index, mark in enumerate(marks, 1):
            uid = f"{prefix}{index}" + (".L1" if group == "R2" else "")
            lines += [f"### {uid} · III · claim `{uid}` · cells: cell_1", "Support type: source_stated",
                      *[f"- [{'x' if choice == mark else ' '}] {choice}" for choice in choices]]
    (tmp_path / "review.md").write_text("\n".join(lines) + "\n")
    kit._json_file(tmp_path / "manifest.json", kit._review_manifest((tmp_path / "review.md").read_text()))
    return tmp_path


def test_snapshot_deterministic_links_and_zero_denominators(complete_report, tmp_path):
    _, api, rid, report_id = complete_report
    first, again = tmp_path / "first", tmp_path / "again"
    automated = kit.snapshot(api, rid, first, report_id=report_id, sample=30, seed=17)
    kit.snapshot(api, rid, again, report_id=report_id, sample=30, seed=17)
    assert {p.name for p in first.iterdir()} == {"snapshot.json", "automated.json", "review.md", "manifest.json"}
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
    _complete_both(first)
    assert kit.score(first)["R2"]["sample"] == {"kind": "whole", "seed": 17}


def test_snapshot_defaults_to_the_only_report(complete_report, tmp_path):
    _, api, rid, report_id = complete_report
    out = tmp_path / "only_report"
    kit.snapshot(api, rid, out)
    saved = json.loads((out / "snapshot.json").read_text())
    assert saved["report"]["id"] == report_id


def test_snapshot_multiple_reports_requires_explicit_id_without_writing(tmp_path):
    summaries = [{"id": "old_valid", "status": "valid", "report_version": 1},
                 {"id": "new_paused", "status": "in_progress", "report_version": None}]
    requests = []

    def respond(request):
        requests.append(request.url.path)
        assert request.method == "GET" and request.url.path == "/api/researches/research"
        return kit.httpx.Response(200, json={"reportRuns": summaries})

    out = tmp_path / "ambiguous"
    with kit.httpx.Client(base_url="http://fixture", transport=kit.httpx.MockTransport(respond)) as api:
        with pytest.raises(ValueError, match="specify --report") as exc:
            kit.snapshot(api, "research", out)
    assert all(row["id"] in str(exc.value) for row in summaries)
    assert requests == ["/api/researches/research"]
    assert not out.exists()


@pytest.mark.parametrize("group,values_key,sum_key", [
    ("R5", "other_names_by_term", "total_other_names"),
    ("R11", "missing_passages_by_section", "total_missing"),
])
@pytest.mark.parametrize("filled", [0, 1, 2])
def test_count_readings_require_all_units(reading_out, group, values_key, sum_key, filled):
    if group == "R5":
        units = [("T1", "term one"), ("T2", "term two")]
        label = "Other names found"
    else:
        units = [("BIII", "III"), ("BIV", "IV")]
        label = "Missing passage count"
    counts = [0, 3]
    sheet = (reading_out / "review.md").read_text() + f"\n## {group}\n"
    for index, (uid, title) in enumerate(units):
        count = str(counts[index]) if index < filled else "<n>"
        sheet += f"\n### {uid} · {title}\n\n{label}: {count}\n"
    (reading_out / "review.md").write_text(sheet)
    kit.second(reading_out)
    _complete_reading(reading_out / "second.md")
    result = kit.score(reading_out)[group]
    expected = {values_key: [counts[i] if i < filled else None for i in range(2)],
                sum_key: sum(counts[:filled]), "judged": filled, "total": 2}
    for row in (result, result["reading"]):
        assert row["value"] == expected
        assert row["denominator"] == (filled or None)
        assert row["status"] == ("measured" if filled == 2 else "not_readable")
        assert row["reason"] == (None if filled == 2 else "incomplete_reading")
        assert row["sample"] == {"kind": "whole", "seed": 17}
    assert json.loads((reading_out / "results.json").read_text())[group] == result


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
    out = tmp_path / "out"
    _complete_both(out)
    result = kit.score(out)["R8"]
    assert result["status"] == "measured"
    assert result["value"] == automated["R8"]["value"]
    assert json.loads((out / "results.json").read_text())["R8"]["denominator"] == automated["R8"]["denominator"]


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
    _complete_reading(out / "review.md")
    kit.second(out)
    blind = (out / "second.md").read_text()
    assert "- [x] Does not support" not in blind
    assert re.search(r"### C\d+\.L\d+", blind)
    blind = blind.replace("Reader: ", "Reader: second", 1)
    blind = blind.replace("- [ ] Supports the claim", "- [x] Supports the claim", 1)
    (out / "second.md").write_text(blind)
    _complete_reading(out / "second.md")
    results = kit.score(out)
    r2 = results["R2"]["reading"]
    assert r2["value"]["serious"] == 1 and r2["value"]["wrong_claims"] == 1
    assert r2["value"]["disagreements"] == 1
    assert r2["sample"] == {"kind": "drawn", "seed": 20260930}
    r3_units = kit._units((out / "review.md").read_text()).get("R3", {})
    assert results["R3"]["reading"]["reason"] == (None if r3_units else "not_read")
    assert set(json.loads((out / "results.json").read_text())) == set(kit.METRICS) | {"p15_behavior"}


def test_second_draws_marked_controls_per_sheet_deterministically(reading_out):
    first = kit._units((reading_out / "review.md").read_text())
    path = kit.second(reading_out)
    sheet = path.read_text()
    blind = kit._units(sheet)
    rng = random.Random(17)
    order_rng = random.Random(18)
    manifest = json.loads((reading_out / "second-manifest.json").read_text())
    assert "control" not in sheet and "non_supporting" not in sheet
    for group, choices in kit.CHOICES.items():
        pool = sorted(uid for uid, unit in first[group].items() if unit["marks"] == [choices[0]])
        negative = choices[1:2] if group == "R6" else choices[1:]
        serious = [uid for uid, unit in first[group].items() if unit["marks"][0] in negative]
        controls = rng.sample(pool, min(5, len(pool)))
        expected = sorted(serious) + controls
        order_rng.shuffle(expected)
        assert list(blind.get(group, {})) == expected
        assert f"## {group}\n" in sheet
        assert manifest["sheets"][group] == {"unit_ids": expected, "control_ids": controls,
                                             "control_count": len(controls), "non_supporting_count": len(serious)}
        assert all(not unit["marks"] for unit in blind[group].values())
    assert len(blind["R2"]) > 0
    assert kit.second(reading_out).read_text() == sheet
    _complete_reading(path)
    result = kit.score(reading_out)["R2"]["reading"]["value"]
    assert result["serious"] == 1 and result["partial_links"] == 1


@pytest.mark.parametrize("group", list(kit.CHOICES))
@pytest.mark.parametrize("double", [False, True])
def test_incomplete_first_reading_refused_by_second_and_score(reading_out, group, double):
    _complete_both(reading_out)
    path = reading_out / "review.md"
    sheet = path.read_text()
    uid, unit = next(iter(kit._units(sheet)[group].items()))
    mark = unit["marks"][0]
    if double:
        other = next(choice for choice in kit.CHOICES[group] if choice != mark)
        body = unit["body"].replace(f"- [ ] {other}", f"- [x] {other}", 1)
    else:
        body = unit["body"].replace(f"- [x] {mark}", f"- [ ] {mark}", 1)
    path.write_text(sheet.replace(unit["body"], body, 1))
    second_before = (reading_out / "second.md").read_text()
    for command in (kit.second, kit.score):
        with pytest.raises(ValueError, match=rf"review\.md.*{re.escape(uid)}"):
            command(reading_out)
    assert (reading_out / "second.md").read_text() == second_before
    assert not (reading_out / "results.json").exists()


def test_no_first_marks_refused_by_second_and_score(reading_out):
    path = reading_out / "review.md"
    path.write_text(path.read_text().replace("- [x] ", "- [ ] "))
    for command in (kit.second, kit.score):
        with pytest.raises(ValueError, match="no marked"):
            command(reading_out)


@pytest.mark.parametrize("tamper", ["block", "boxes", "one_box"])
def test_deleted_first_unit_or_boxes_refused(reading_out, tamper):
    _complete_both(reading_out)
    path = reading_out / "review.md"
    sheet = path.read_text()
    unit = kit._units(sheet)["R2"]["C1.L1"]
    if tamper == "block":
        body = ""
    elif tamper == "boxes":
        body = re.sub(r"^- \[[ xX]\] .*\n?", "", unit["body"], flags=re.M)
    else:
        body = unit["body"].replace(f"- [ ] {kit.R2_CHOICES[1]}\n", "", 1)
    path.write_text(sheet.replace(unit["body"], body, 1))
    before = {name: (reading_out / name).read_bytes() for name in ("second.md", "second-manifest.json")}
    for command in (kit.second, kit.score):
        with pytest.raises(ValueError, match=r"review\.md.*R2/C1\.L1"):
            command(reading_out)
    assert all((reading_out / name).read_bytes() == data for name, data in before.items())
    assert not (reading_out / "results.json").exists()


def test_missing_second_reading_refused(reading_out):
    with pytest.raises(ValueError, match=r"second\.md.*missing"):
        kit.score(reading_out)
    assert not (reading_out / "results.json").exists()


@pytest.mark.parametrize("group", list(kit.CHOICES))
@pytest.mark.parametrize("double", [False, True])
def test_incomplete_second_reading_refused(reading_out, group, double):
    _complete_both(reading_out)
    path = reading_out / "second.md"
    sheet = path.read_text()
    uid, unit = next(iter(kit._units(sheet)[group].items()))
    mark = unit["marks"][0]
    if double:
        other = next(choice for choice in kit.CHOICES[group] if choice != mark)
        body = unit["body"].replace(f"- [ ] {other}", f"- [x] {other}", 1)
    else:
        body = unit["body"].replace(f"- [x] {mark}", f"- [ ] {mark}", 1)
    path.write_text(sheet.replace(unit["body"], body, 1))
    with pytest.raises(ValueError, match=rf"second\.md.*{re.escape(uid)}"):
        kit.score(reading_out)
    assert not (reading_out / "results.json").exists()


@pytest.mark.parametrize("name", ["review.md", "second.md"])
@pytest.mark.parametrize("extra", ["Supports the claim", "Unknown choice"])
def test_extra_checked_box_refused(reading_out, name, extra):
    _complete_both(reading_out)
    path = reading_out / name
    sheet = path.read_text()
    uid, unit = next(iter(kit._units(sheet)["R2"].items()))
    path.write_text(sheet.replace(unit["body"], unit["body"] + f"- [x] {extra}\n", 1))
    for command in ((kit.second, kit.score) if name == "review.md" else (kit.score,)):
        with pytest.raises(ValueError, match=rf"{re.escape(name)}.*{re.escape(uid)}"):
            command(reading_out)


@pytest.mark.parametrize("tamper", ["rename", "remove", "add", "swap_control", "duplicate"])
def test_tampered_second_unit_ids_refused(reading_out, tamper):
    _complete_both(reading_out)
    path = reading_out / "second.md"
    sheet = path.read_text()
    first = kit._units((reading_out / "review.md").read_text())["R2"]
    blind = kit._units(sheet)["R2"]
    uid, unit = next(iter(blind.items()))
    if tamper == "remove":
        sheet = sheet.replace(unit["body"], "", 1)
    elif tamper == "duplicate":
        sheet = sheet.replace(unit["body"], unit["body"] * 2, 1)
    elif tamper == "swap_control":
        uid, unit = next((key, value) for key, value in blind.items()
                         if first[key]["marks"] == [kit.R2_CHOICES[0]])
        other = next(key for key in first if key not in blind)
        sheet = sheet.replace(unit["header"], unit["header"].replace(uid, other, 1), 1)
    else:
        body = unit["body"].replace(uid, "C999.L1", 1)
        sheet = sheet.replace(unit["body"], body if tamper == "rename" else unit["body"] + body, 1)
    path.write_text(sheet)
    with pytest.raises(ValueError, match=r"(?:unit ids differ|duplicate unit id).*R2/"):
        kit.score(reading_out)


def test_score_requires_snapshot_seed_selection(reading_out):
    path = kit.second(reading_out, seed=23)
    _complete_reading(path)
    with pytest.raises(ValueError, match="unit ids differ"):
        kit.score(reading_out)


def test_exempt_units_do_not_block_readings(reading_out):
    path = reading_out / "review.md"
    sheet = path.read_text()
    r3 = "\n".join(["#### M1 · <section> · <text> · cells: <cell ids or quoted cell text>",
                     *kit._boxes(kit.R3_CHOICES), "#### M2 · IV · No study addressed X · cells:",
                     *kit._boxes(kit.R3_CHOICES), ""])
    sheet = sheet.replace("## R4b", r3 + "## R4b", 1)
    sheet = sheet.replace("## R9", "### E99 · III · unreadable equation\n"
                          "Status: not_readable · page_not_openable\n## R9", 1)
    path.write_text(sheet)
    manifest = json.loads((reading_out / "manifest.json").read_text())
    manifest["sheets"]["R6"]["exempt"]["E99"] = "page_not_openable"
    kit._json_file(reading_out / "manifest.json", manifest)
    kit.second(reading_out)
    blind = (reading_out / "second.md").read_text()
    assert "#### M1" not in blind and "#### M2" not in blind and "### E99" not in blind
    _complete_reading(reading_out / "second.md")
    results = kit.score(reading_out)
    r3 = results["R3"]["reading"]["value"]
    missed = next(unit for unit in r3["units"] if unit["id"] == "M2")
    assert missed["no_evidence_given"] and missed["first"] is None
    assert any(unit["id"] == "E99" and unit["first"] is None
               for unit in results["R6"]["reading"]["value"]["units"])


@pytest.mark.parametrize("reader", ["first", "second"])
def test_r6_page_unopenable_at_reading_excludes_unit_from_denominator(reading_out, reader):
    path = reading_out / "review.md"
    if reader == "second":
        kit.second(reading_out)
        path = reading_out / "second.md"
    sheet = path.read_text()
    unit = kit._units(sheet)["R6"]["E2"]  # First reader recorded a mismatch.
    body = unit["body"].replace("- [x] ", "- [ ] ").replace(
        f"- [ ] {kit.R6_CHOICES[2]}", f"- [x] {kit.R6_CHOICES[2]}", 1)
    path.write_text(sheet.replace(unit["body"], body, 1))
    if reader == "first":
        kit.second(reading_out)
        assert "E2" not in kit._units((reading_out / "second.md").read_text()).get("R6", {})
        manifest = json.loads((reading_out / "second-manifest.json").read_text())
        assert manifest["sheets"]["R6"]["non_supporting_count"] == 0
    _complete_reading(reading_out / "second.md")
    result = kit.score(reading_out)["R6"]
    assert result["status"] == "measured" and result["denominator"] == 1
    assert result["value"]["judged"] == 1 and result["value"]["serious"] == 0
    assert result["value"]["disagreements"] == 0
    unreadable = next(unit for unit in result["value"]["units"] if unit["id"] == "E2")
    assert unreadable["status"] == "not_readable"
    assert unreadable["reason"] == "page_not_openable_at_reading"
    assert unreadable["serious"] is False


@pytest.fixture
def p15_results(tmp_path):
    """Synthetic P15 producer shape; no private results or main-checkout data."""
    results = []
    for family, count in (("RB", 5), ("RS", 12), ("RC", 1)):
        for index in range(1, count + 1):
            checks = {"no_tool_items": True, "structurally_valid": True}
            counts = {}
            if family in ("RS", "RC"):
                checks["identifier_valid"] = True
                counts = {"false_positive_count": index % 3 if family == "RS" else 2,
                          "control_findings": 2 if family == "RC" else 0}
            if family == "RS":
                checks.update(flagged=index <= 10, flagged_with_expected_code=index <= 8)
            elif family == "RC":
                checks["no_control_findings"] = False
            else:
                checks.update(no_outside_id_in_citation_fields=True,
                              screen_no_summary_absence=True, both_rows_addressed=True,
                              screen_depth_limit_stated=True)
            results.append({"case_id": f"{family}{index:02d}", "family": family,
                            "started_at": "2026-09-30T10:00:00Z", "skill_package_hash": "synthetic",
                            "automatic_checks": checks, "counts": counts,
                            "not_applicable": {"assembly_would_catch": None}, "human_judgement": None,
                            "runs": [{"status": "completed", "validation": {"ok": True}}]})
    payload = {"model": "synthetic-model", "results": results,
               "summary": {"synthetic_review_flags": {"attempted": 12, "valid_outputs": 12,
                           "flagged": 10, "flagged_with_expected_code": 8,
                           "false_positives_total": 12, "control_findings": 2}}, "stop_reason": None}
    path = tmp_path / "p15.json"
    kit._json_file(path, payload)
    return path


@pytest.mark.parametrize("supplied", [False, True])
def test_score_seeded_cli_keeps_p15_separate_from_r10(reading_out, p15_results, monkeypatch, supplied):
    kit.second(reading_out)
    _complete_reading(reading_out / "second.md")
    args = ["measure_report", "score", "--out", str(reading_out)]
    if supplied:
        args += ["--seeded", str(p15_results)]
    monkeypatch.setattr("sys.argv", args)
    kit.main()
    results = json.loads((reading_out / "results.json").read_text())
    assert results["R10"]["status"] == "not_measurable"
    assert results["R10"]["reason"] == "p15_behavior_is_not_r10"
    assert "review_caught" not in json.dumps(results)
    if supplied:
        assert results["p15_behavior"] == {
            "total_rs": 12, "flagged": 10, "flagged_with_expected_code": 8,
            "false_positive_count": 12, "control_findings": 2, "human_judgement_present": 0,
            "model": "synthetic-model", "stop_reason": None,
            "note": "Flags are keyword screens on synthetic single-step cases, not a stored-report catch rate "
                    "and not an assembly catch rate."}
    else:
        assert results["p15_behavior"] is None


def test_seeded_retains_human_presence_and_stop_reason(p15_results):
    payload = json.loads(p15_results.read_text())
    payload["results"][0]["human_judgement"] = {"note": "Synthetic reading"}
    payload["stop_reason"] = "Synthetic stop"
    kit._json_file(p15_results, payload)
    row = kit._seeded(p15_results)
    assert row["human_judgement_present"] == 1
    assert row["stop_reason"] == "Synthetic stop"


@pytest.mark.parametrize("payload", [{}, {"results": None}, []])
def test_seeded_requires_results_list(tmp_path, payload):
    path = tmp_path / "malformed.json"
    kit._json_file(path, payload)
    with pytest.raises(ValueError, match="P15 object with a results list"):
        kit._seeded(path)


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
    assert all(rows[k]["reason"] == "run_incomplete" for k in kit.METRICS if k not in ("R1", "R7", "R10"))
    assert rows["R10"]["reason"] == "p15_behavior_is_not_r10"
    assert rows["R1"]["status"] == "measured" and rows["R7"]["status"] == "measured"


def _packet_snapshot(tmp_path, monkeypatch, report, run, db=None, pairs=None, stopped=None, db_path=None,
                     passages=None):
    """Exercise snapshot through HTTP fixtures without a service or a model call."""
    report = {"id": "report", "run_id": "run", "report_version": 1, **report}
    run = {"id": "run", **run}
    research = {"reportRuns": [report], "runs": [run]}
    root = "/api/researches/research"

    def respond(request):
        assert request.method == "GET"
        if request.url.path == root:
            return kit.httpx.Response(200, json=research)
        if request.url.path == root + "/reports/report":
            return kit.httpx.Response(200, json=report)
        if request.url.path == root + "/reports/report/export":
            return kit.httpx.Response(200, text="Synthetic export")
        for pid, passage in (passages or {}).items():
            if request.url.path == root + f"/passages/{pid}":
                return kit.httpx.Response(200, json=passage)
            if passage.get("asset_id") and request.url.path == root + f"/assets/{passage['asset_id']}":
                return kit.httpx.Response(200, content=b"%PDF-synthetic page")
        if request.url.path.startswith(root + "/passages/"):
            return kit.httpx.Response(404, json={"detail": "Synthetic missing passage"})
        raise AssertionError(f"Unexpected request: {request.url}")

    if db_path is None:
        monkeypatch.setattr(kit, "db_evidence", lambda *args: db)
    pairs_path = None
    if pairs is not None:
        pairs_path = tmp_path / "pairs.json"
        kit._json_file(pairs_path, pairs)
    out = tmp_path / "packet"
    with kit.httpx.Client(base_url="http://fixture", transport=kit.httpx.MockTransport(respond)) as api:
        rows = kit.snapshot(api, "research", out, report_id="report", seed=17,
                            pairs_path=pairs_path, stopped=stopped, db_path=db_path)
    return out, rows


def test_long_claims_and_source_text_stay_complete_in_both_readings(tmp_path, monkeypatch):
    body_tail = "The result holds only for the stated boundary condition. $$x=1$$"
    derived_tail = "The summary retains the same boundary condition."
    body_text = "B" * (2000 - len(body_tail)) + body_tail
    derived_text = "D" * (2000 - len(derived_tail)) + derived_tail
    source_text = "S" * 2500 + "The source restricts the result to that boundary condition. $$x=1$$"
    assert len(body_text) == len(derived_text) == 2000
    assert body_text.index(body_tail) > 1500 and derived_text.index(derived_tail) > 1500
    pid = "psg_12345678"
    evidence = [{"passage_id": pid, "open_passage_id": pid, "cell_id": None,
                 "source_version_id": "s1", "anchor_match": True,
                 "anchor_text": "The source restricts the result to that boundary condition."}]
    body = {"id": "body", "claim_key": "III.1", "text": body_text, "equation_ref": "EQ1",
            "support_type": "source_stated", "evidence": evidence}
    derived = {"id": "derived", "claim_key": "abstract.1", "text": derived_text,
               "support_type": "source_stated", "evidence": []}
    def draft_for(claim, section, body_refs, equation_ref=None):
        draft = {"schema_version": "deixis.report_section_draft.v2", "step_input_id": "sti_12345678",
                 "scope_revision": 1, "skill_package_hash": "sha256:" + "0" * 64,
                 "section_id": section, "citation_anchors": [], "subsections": [],
                 "gaps": [], "insufficient_evidence": [], "claims": [{
                     "claim_key": claim["claim_key"], "text": claim["text"],
                     "support_type": claim["support_type"], "passage_ids": [pid], "cell_ids": [],
                     "paragraph": 1, "table_ref": None, "equation_ref": equation_ref,
                     "body_refs": body_refs, "axis_id": None, "count": None, "gap_refs": [],
                     "equation_origin": {"passage_id": pid, "text_source": "text_layer"} if equation_ref else None}]}
        canonical_validator("ReportSectionDraft").validate(draft)
        return draft

    report = {"status": "valid", "sections": [
        {"section_id": "III", "status": "valid", "claims": [body],
         "draft": draft_for(body, "III", [], "EQ1")},
        {"section_id": "abstract", "status": "valid", "claims": [derived],
         "draft": draft_for(derived, "abstract", ["III.1"])}]}
    passage = {"text": source_text, "kind": "pdf_page", "source": {"id": "s1"},
               "asset_id": "pdf", "physical_page": 1}
    out, _ = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"},
                              passages={pid: passage})
    _complete_both(out)
    for name in ("review.md", "second.md"):
        units = kit._units((out / name).read_text())
        for group in ("R2", "R6"):
            unit = next(iter(units[group].values()))
            assert body_text in unit["body"]
            assert source_text in unit["body"]
        derived_unit = next(iter(units["R4b"].values()))
        assert derived_text in derived_unit["body"]
        assert body_text in derived_unit["body"]


@pytest.mark.parametrize("mode", ["cancelled", "in_progress", "stopped"])
def test_incomplete_run_scores_without_readings(tmp_path, monkeypatch, capsys, mode):
    stopped = "session_cap" if mode == "stopped" else None
    report = {"status": "valid" if stopped else "in_progress", "sections": []}
    run = {"status": "completed" if stopped else "cancelled" if mode == "cancelled" else "running",
           "steps": [{"id": "step", "operation_key": "report_section:III", "kind": "model",
                      "status": "succeeded" if stopped else "cancelled"}],
           "created_at": "2026-09-30T10:00:00Z", "updated_at": "2026-09-30T10:01:00Z"}
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, run, stopped=stopped)
    assert not any(u["marks"] for group in kit._units((out / "review.md").read_text()).values()
                   for u in group.values())
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    assert kit.second(out) is None
    assert "no second reading is needed" in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    results = kit.score(out)
    assert results["R1"]["status"] == results["R7"]["status"] == "measured"
    for key in kit.METRICS:
        assert results[key]["stopped_by"] == stopped
        if key == "R10":
            assert rows[key]["reason"] == results[key]["reason"] == "p15_behavior_is_not_r10"
        elif key not in ("R1", "R7"):
            assert rows[key]["status"] == results[key]["status"] == "not_measurable"
            assert rows[key]["reason"] == results[key]["reason"] == "run_incomplete"
            assert results[key]["readers"] == []
    assert json.loads((out / "snapshot.json").read_text())["stopped_by"] == stopped
    assert json.loads((out / "results.json").read_text()) == results
    # Neither file is needed to conclude an incomplete run.
    (out / "review.md").unlink()
    (out / "manifest.json").unlink()
    assert kit.second(out) is None
    assert kit.score(out) == results


def test_snapshot_stopped_cli_records_free_text(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(kit, "snapshot", lambda *args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["measure_report", "snapshot", "--research", "fixture", "--out", str(tmp_path),
                                     "--stopped", "quota reached after final count"])
    kit.main()
    assert calls[0][-1] == "quota reached after final count"


@pytest.mark.parametrize("stopped", [None, "counter_unreadable"])
@pytest.mark.parametrize("kind", ["corrupt", "missing", "os_error"])
def test_snapshot_writes_outputs_with_unreadable_db(tmp_path, monkeypatch, capsys, stopped, kind):
    copy = tmp_path / "copy.sqlite"
    if kind == "corrupt":
        copy.write_text("This is not a SQLite database.")
    elif kind == "os_error":
        def fail(*args):
            raise OSError("Cannot read copy")
        monkeypatch.setattr(kit, "_db_rows", fail)
    before = copy.read_bytes() if copy.exists() else None
    run = {"status": "completed", "usage": {"model_calls": 3},
           "steps": [{"id": "step", "operation_key": "report_section:III", "kind": "model",
                      "status": "succeeded", "started_at": "2026-09-30T10:00:00Z",
                      "finished_at": "2026-09-30T10:01:00Z"}],
           "created_at": "2026-09-30T10:00:00Z", "updated_at": "2026-09-30T10:01:00Z"}
    report = {"status": "valid", "sections": [{"section_id": "III", "status": "valid", "claims": []}],
              "references": [{"source_version_id": "s1", "source_key": "A"}]}
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, run, db_path=copy, stopped=stopped,
                                pairs=[{"source_key": "A", "formulation": "model"}])
    reason = "db_unreadable: " + {"corrupt": "DatabaseError", "missing": "OperationalError", "os_error": "OSError"}[kind]
    assert reason in capsys.readouterr().out
    assert not copy.exists() if before is None else copy.read_bytes() == before
    saved = json.loads((out / "snapshot.json").read_text())
    assert saved["db_evidence"] == kit.unreadable(reason)
    assert saved["stopped_by"] == stopped
    assert json.loads((out / "automated.json").read_text()) == rows
    manifest = json.loads((out / "manifest.json").read_text())
    assert rows["R1"]["status"] == rows["R7"]["status"] == "measured"
    assert rows["R1"]["value"]["valid_after_repair"] == 1
    assert rows["R7"]["value"]["wall_seconds"] == 60
    assert rows["R7"]["value"]["model_calls"] == 3
    for field in ("first_try_valid", "schema_repair_attempts", "resend_sessions"):
        assert rows["R1"]["value"]["sections"][0][field] == kit.unreadable(reason)
    assert rows["R7"]["value"]["tokens"] == kit.unreadable(reason)
    assert rows["R8"]["status"] == rows["R9"]["status"] == "not_readable"
    assert rows["R8"]["reason"] == rows["R9"]["reason"] == reason
    assert manifest["sheets"]["R9"] == {"required": [], "exempt": {"P1": reason}}
    assert "- [ ]" not in kit._units((out / "review.md").read_text())["R9"]["P1"]["body"]
    if stopped:
        assert kit.second(out) is None
    else:
        assert rows["R11"]["value"][0]["ratio_status"] == "not_readable"
        assert rows["R11"]["value"][0]["ratio_reason"] == reason
        _complete_both(out)
    results = kit.score(out)
    assert results["R8"]["status"] == results["R9"]["status"] == "not_readable"
    assert results["R8"]["reason"] == results["R9"]["reason"] == reason


def test_cell_link_opened_text_survives_db_copy_failure(complete_report, tmp_path):
    _, api, rid, report_id = complete_report
    rows = kit.snapshot(api, rid, tmp_path / "out", report_id=report_id, db_path=tmp_path / "missing.sqlite")
    cell_links = [r for r in rows["R2"]["value"]["links"] if r["cell_id"]]
    assert cell_links
    for row in cell_links:
        assert row["depth_status"] == "not_readable"
        assert row["depth_reason"] == "db_unreadable: OperationalError"
        assert row["quote"] and row["quote_status"] == row["status"] == "measured"


def _r2_unreadable_packet(tmp_path, monkeypatch, *, mixed=False, corrupt=True):
    evidence = [{"passage_id": "missing", "open_passage_id": "missing", "cell_id": "c1",
                 "source_version_id": "s1", "anchor_match": True, "anchor_text": "An anchor is not source text."}]
    if mixed:
        evidence.append({"passage_id": "readable", "open_passage_id": "readable", "cell_id": "c1",
                         "source_version_id": "s1", "anchor_match": True, "anchor_text": "Source text."})
    claim = {"id": "claim", "claim_key": "III.1", "text": "A synthetic claim.",
             "support_type": "source_stated", "evidence": evidence}
    report = {"status": "valid", "sections": [{"section_id": "III", "status": "valid", "claims": [claim]}],
              "table_i": {"cells": [{"cell_id": "c1", "source_version_id": "s1", "value": "A value."}]}}
    copy = None
    if corrupt:
        copy = tmp_path / "unreadable.sqlite"
        copy.write_text("This is not a database.")
    passages = {"readable": {"text": "Source text.", "kind": "abstract", "source": {"id": "s1"}}} if mixed else {}
    return _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"},
                            db_path=copy, passages=passages)


@pytest.mark.parametrize("corrupt", [False, True])
def test_r2_unreadable_source_is_exempt_through_final_score(tmp_path, monkeypatch, corrupt):
    out, rows = _r2_unreadable_packet(tmp_path, monkeypatch, corrupt=corrupt)
    reason = "db_unreadable: DatabaseError" if corrupt else "source_text_not_readable"
    r2 = rows["R2"]
    assert r2["status"] == "not_readable" and r2["reason"] == reason
    assert r2["denominator"] == 0
    assert r2["value"]["unreadable_links"] == 1
    assert r2["value"]["unreadable_reasons"] == {reason: 1}
    link = r2["value"]["links"][0]
    assert link["quote"] is None and link["status"] == "not_readable" and link["reason"] == reason
    assert json.loads((out / "automated.json").read_text())["R2"] == r2
    unit = kit._units((out / "review.md").read_text())["R2"]["C1.L1"]
    assert "- [ ]" not in unit["body"] and not unit["marks"]
    assert json.loads((out / "manifest.json").read_text())["sheets"]["R2"] == {
        "required": [], "exempt": {"C1.L1": reason}}
    _complete_both(out)
    assert not kit._units((out / "second.md").read_text()).get("R2")
    selection = json.loads((out / "second-manifest.json").read_text())["sheets"]["R2"]
    assert selection["unit_ids"] == selection["control_ids"] == []
    result = kit.score(out)["R2"]
    assert result["status"] == "not_readable" and result["reason"] == reason
    assert result["denominator"] is None
    assert result["value"]["unreadable_links"] == 1
    assert result["value"]["unreadable_reasons"] == {reason: 1}
    assert result["value"]["judged"] == result["value"]["wrong_claims"] == 0
    assert result["value"]["wrong_source_stated_claims"] == 0


@pytest.mark.parametrize("tamper", ["delete", "reason", "required", "add_boxes"])
def test_r2_unreadable_manifest_tampering_refused(tmp_path, monkeypatch, tamper):
    out, _ = _r2_unreadable_packet(tmp_path, monkeypatch)
    _complete_both(out)
    manifest = json.loads((out / "manifest.json").read_text())
    r2 = manifest["sheets"]["R2"]
    if tamper == "delete":
        r2["exempt"].clear()
    elif tamper == "reason":
        r2["exempt"]["C1.L1"] = "different_reason"
    elif tamper == "required":
        r2["exempt"].clear()
        r2["required"].append("C1.L1")
    else:
        path = out / "review.md"
        path.write_text(path.read_text().replace("## R3", "\n".join(kit._boxes(kit.R2_CHOICES)) + "\n## R3"))
    kit._json_file(out / "manifest.json", manifest)
    for operation in (kit.second, kit.score):
        with pytest.raises(ValueError, match=r"review\.md.*R2/C1\.L1"):
            operation(out)


def test_r2_mixed_source_text_only_judges_readable_link(tmp_path, monkeypatch):
    out, rows = _r2_unreadable_packet(tmp_path, monkeypatch, mixed=True)
    assert rows["R2"]["status"] == "measured" and rows["R2"]["denominator"] == 1
    assert rows["R2"]["value"]["unreadable_links"] == 1
    manifest = json.loads((out / "manifest.json").read_text())["sheets"]["R2"]
    assert manifest == {"required": ["C1.L2"], "exempt": {"C1.L1": "db_unreadable: DatabaseError"}}
    path = out / "review.md"
    path.write_text(path.read_text().replace(f"- [ ] {kit.R2_CHOICES[2]}", f"- [x] {kit.R2_CHOICES[2]}"))
    _complete_both(out)
    assert set(kit._units((out / "second.md").read_text())["R2"]) == {"C1.L2"}
    result = kit.score(out)["R2"]
    assert result["status"] == "measured" and result["denominator"] == 1
    assert result["value"]["unreadable_links"] == 1
    assert result["value"]["unreadable_reasons"] == {"db_unreadable: DatabaseError": 1}
    assert result["value"]["judged"] == result["value"]["wrong_claims"] == 1
    assert result["value"]["units"][0]["status"] == "not_readable"


@pytest.mark.parametrize("query_number", [1, 2, 3, 4])
@pytest.mark.parametrize("stopped", [None, "counter_unreadable"])
def test_failure_in_any_db_query_discards_partial_evidence(tmp_path, monkeypatch, query_number, stopped):
    calls = []

    def read(path, query, args):
        calls.append(query)
        if len(calls) == query_number:
            raise sqlite3.OperationalError("copy became unreadable")
        return []

    monkeypatch.setattr(kit, "_db_rows", read)
    out, rows = _packet_snapshot(tmp_path, monkeypatch, {"status": "valid", "sections": []},
                                {"status": "completed"}, db_path=tmp_path / "copy.sqlite", stopped=stopped)
    assert len(calls) == query_number
    assert json.loads((out / "snapshot.json").read_text())["db_evidence"] == kit.unreadable(
        "db_unreadable: OperationalError")
    assert rows["R7"]["value"]["tokens"] == kit.unreadable("db_unreadable: OperationalError")
    assert rows["R8"]["reason"] == "db_unreadable: OperationalError"
    assert (out / "automated.json").exists() and (out / "manifest.json").exists()


def test_r6_snapshot_open_page_can_be_unreadable_for_reader(tmp_path, monkeypatch):
    claim = {"id": "equation", "claim_key": "III.1", "text": "$$x=1$$", "equation_ref": "eq1",
             "support_type": "source_stated", "evidence": []}
    report = {"status": "valid", "sections": [{"section_id": "III", "status": "valid", "claims": [claim],
              "draft": {"claims": [{**claim, "equation_origin": {"passage_id": "p1"}}]}}]}
    out, _ = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"},
                              passages={"p1": {"text": "$$x=1$$", "asset_id": "pdf", "physical_page": 2}})
    first = (out / "review.md").read_text()
    unit = kit._units(first)["R6"]["E1"]
    assert "assets/pdf#page=2" in unit["body"]
    assert all(f"- [ ] {choice}" in unit["body"] for choice in kit.R6_CHOICES)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sheets"]["R6"] == {"required": ["E1"], "exempt": {}}
    (out / "review.md").write_text(first.replace(
        f"- [ ] {kit.R6_CHOICES[2]}", f"- [x] {kit.R6_CHOICES[2]}", 1))
    _complete_both(out)
    assert not kit._units((out / "second.md").read_text()).get("R6")
    result = kit.score(out)["R6"]
    assert result["status"] == "not_readable" and result["reason"] == "page_not_openable_at_reading"
    assert result["denominator"] is None
    assert result["value"]["judged"] == result["value"]["serious"] == 0
    assert result["value"]["units"][0]["status"] == "not_readable"


def test_r9_without_db_is_unreadable_in_snapshot_and_score(tmp_path, monkeypatch):
    report = {"status": "valid", "sections": [], "references": [{"source_version_id": "s1", "source_key": "A"}],
              "table_i": {"cells": [{"cell_id": "c1", "column_id": "eq", "source_version_id": "s1",
                                     "value": "$$x=1$$"}]}}
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"},
                                pairs=[{"source_key": "A", "formulation": "model"}])
    assert rows["R9"]["status"] == "not_readable" and rows["R9"]["reason"] == "db_not_supplied"
    assert rows["R9"]["denominator"] is None
    unit = kit._units((out / "review.md").read_text())["R9"]["P1"]
    assert "Status: not_readable · db_not_supplied" in unit["body"] and "- [ ]" not in unit["body"]
    assert "input side not_readable · db_not_supplied" in unit["body"]
    assert json.loads((out / "manifest.json").read_text())["sheets"]["R9"] == {
        "required": [], "exempt": {"P1": "db_not_supplied"}}
    _complete_both(out)
    result = kit.score(out)["R9"]
    assert result["status"] == "not_readable" and result["reason"] == "db_not_supplied"


def _section_input(passages=None, cells=None, task_type="report_section", attempt=0):
    return {"id": "input", "step_id": "section_step", "attempt": attempt, "input_rowid": 1,
            "created_at": "2026-09-30T10:00:00Z", "task_type": task_type,
            "payload_json": json.dumps({"passages": passages or [],
                                        "report_target": {"section_id": "III", "cells": cells or []}})}


def test_r9_eligible_without_any_report_equation_and_quotes_preserve_packet_units(tmp_path, monkeypatch):
    text = "$$x=1$$\n## R9\n### P999\n- [x] Absent\nStatus: not_readable · quoted\nStatus: no_input_equation"
    db = {"sessions": [], "inputs": [_section_input(passages=[{
        "source_id": "s1", "passage_id": "p1", "text": text}])], "phrase_repairs": [], "frozen_snapshot": None}
    report = {"status": "valid", "sections": [], "references": [{"source_version_id": "s1", "source_key": "A"}]}
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"}, db=db,
                                pairs=[{"source_key": "A", "formulation": "model"}])
    assert rows["R9"]["status"] == "measured" and rows["R9"]["denominator"] == 1
    assert rows["R9"]["value"][0]["report_equation_claims"] == []
    assert list(kit._units((out / "review.md").read_text())["R9"]) == ["P1"]
    _complete_both(out)
    assert kit.score(out)["R9"]["denominator"] == 1


def test_r9_separates_all_given_context_from_unsupplied_frozen_cells(tmp_path, monkeypatch):
    equation = {"source_id": "s1", "passage_id": "p1", "text": "$$\\min_x x$$"}
    definition = {"source_id": "s1", "passage_id": "p2", "text": "x denotes the decision variable."}
    quote = "The feasible set is x >= 0."
    given_cell = {"cell_id": "given", "source_version_id": "s1",
                  "evidence": [{"passage_id": "p3", "quote": quote}]}
    input_row = _section_input(passages=[equation, definition,
                              {"source_id": "s2", "passage_id": "p4", "text": "OTHER INPUT SOURCE"}],
                              cells=[given_cell, {"cell_id": "no_quote", "source_version_id": "s1"}])
    frozen = {"columns": [{"column_id": "col", "name": "Formulation"}], "cells": [
        {"cell_id": "given", "source_version_id": "s1", "column_id": "col", "value": "GIVEN FROZEN VALUE"},
        {"cell_id": "no_quote", "source_version_id": "s1", "column_id": "col", "value": "NO QUOTE FROZEN VALUE"},
        {"cell_id": "never_given", "source_version_id": "s1", "column_id": "col", "value": "NEVER GIVEN VALUE"},
        {"cell_id": "plan_only", "source_version_id": "s1", "column_id": "col", "value": "PLAN ONLY VALUE"},
        {"cell_id": "other", "source_version_id": "s2", "column_id": "col", "value": "OTHER FROZEN SOURCE"}]}
    db = {"sessions": [], "phrase_repairs": [], "frozen_snapshot": frozen,
          "inputs": [input_row, _section_input(task_type="report_plan", cells=[frozen["cells"][3]])]}
    claims = [{"id": f"claim_{sid}", "claim_key": f"{sid}.1", "text": f"{sid} defines x as a variable.",
               "support_type": "source_stated", "equation_ref": None, "evidence": [{"source_version_id": "s1"}]}
              for sid in ("III", "IV", "V", "VI", "VII", "VIII")]
    other_claim = {**claims[0], "id": "other_claim", "text": "OTHER CLAIM SOURCE",
                   "evidence": [{"source_version_id": "s2"}]}
    report = {"status": "valid", "references": [{"source_version_id": "s1", "source_key": "A"}],
              "sections": [{"section_id": c["claim_key"].split(".")[0], "status": "valid", "claims": [c]}
                           for c in claims]}
    report["sections"][0]["claims"].append(other_claim)
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"}, db=db,
                                pairs=[{"source_key": "A", "formulation": "objective and variables"}])
    pair = rows["R9"]["value"][0]
    assert rows["R9"]["denominator"] == 1 and pair["report_equation_claims"] == []
    assert [c["claim_id"] for c in pair["report_claim_texts"]] == [c["id"] for c in claims[:5]]
    assert [e["text"] for e in pair["input_evidence"]] == [equation["text"], definition["text"], quote]
    assert [c["cell_id"] for c in pair["not_given_source_cells"]] == ["never_given", "plan_only"]
    body = kit._units((out / "review.md").read_text())["R9"]["P1"]["body"]
    report_side, rest = body.split("#### (b) Input side given to the model", 1)
    input_side, not_given = rest.split("#### (c) not given to the model", 1)
    assert "#### (a) Report claims of III-VII citing this source" in report_side
    assert all(c["text"] in report_side for c in claims[:5])
    assert all(text in input_side for text in (equation["text"], definition["text"], quote))
    assert "NEVER GIVEN VALUE" not in input_side and "PLAN ONLY VALUE" not in input_side
    assert "NEVER GIVEN VALUE" in not_given and "PLAN ONLY VALUE" in not_given
    assert all(text not in body for text in (claims[5]["text"], "OTHER CLAIM SOURCE", "OTHER INPUT SOURCE",
                                            "OTHER FROZEN SOURCE", "GIVEN FROZEN VALUE", "NO QUOTE FROZEN VALUE"))
    _complete_both(out)
    blind = kit._units((out / "second.md").read_text())["R9"]["P1"]["body"]
    assert body.rstrip() in blind.replace("- [x] ", "- [ ] ")
    assert kit.score(out)["R9"]["denominator"] == 1


@pytest.mark.parametrize("text,task_type,source_id", [
    ("5 Hz", "report_section", "s1"),
    ("Pasajda görüntülenen denklem yok.", "report_section", "s1"),
    ("Inline $x=1$ only.", "report_section", "s1"),
    (r"Escaped \$\$x=1\$\$.", "report_section", "s1"),
    ("Unclosed $$x=1", "report_section", "s1"),
    ("$$x=1$$", "report_plan", "s1"),
    ("$$x=1$$", "report_section", "s2"),
])
def test_r9_requires_a_display_in_section_input_for_same_source(tmp_path, monkeypatch, text, task_type, source_id):
    passage = {"source_id": source_id, "passage_id": "p1", "text": text}
    db = {"sessions": [], "inputs": [_section_input(passages=[passage], task_type=task_type)],
          "phrase_repairs": [], "frozen_snapshot": None}
    report = {"status": "valid", "sections": [], "references": [{"source_version_id": "s1", "source_key": "A"}]}
    _, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"}, db=db,
                              pairs=[{"source_key": "A", "formulation": "model"}])
    assert rows["R9"]["denominator"] == 0 and rows["R9"]["value"][0]["status"] == "no_input_equation"


@pytest.mark.parametrize("origin", ["passage", "cell_quote"])
@pytest.mark.parametrize("text_source", ["text_layer", "ocr", "marker", "latex_source"])
def test_r9_packet_has_both_sides_and_excludes_no_input_equation(tmp_path, monkeypatch, origin, text_source):
    name, value = "Denklem parçaları", "Pasajda görüntülenen denklem yok."
    equation = "The model is $$\\min_x x \\quad x \\geq 0$$."
    passage = {"source_id": "s1", "passage_id": "p1", "text": equation, "text_source": text_source}
    input_cell = {"cell_id": "cell1", "source_version_id": "s1", "value": "5 Hz",
                  "evidence": [{"passage_id": "p1", "quote": equation}]}
    claim = {"id": "eq_claim", "claim_key": "III.1", "text": "The objective minimises x with x >= 0.",
             "equation_ref": "eq1", "support_type": "source_stated", "evidence": [{"source_version_id": "s1"}]}
    report = {"status": "valid", "references": [{"source_version_id": "s1", "source_key": "A"},
                                               {"source_version_id": "s2", "source_key": "B"}],
              "sections": [{"section_id": "III", "status": "valid", "claims": [claim],
                            "draft": {"claims": [claim]}}],
              "table_i": {"cells": [{"cell_id": "cell1", "column_id": "col", "source_version_id": "s1",
                                     "value": "Later value must not appear"}]}}
    frozen = {"columns": [{"column_id": "col", "name": name, "answer_format": "text"},
                          {"column_id": "vars", "name": "Karar değişkenleri", "answer_format": "text"},
                          {"column_id": "obj", "name": "Amaç fonksiyonu", "answer_format": "text"}],
              "cells": [{"cell_id": "cell1", "column_id": "col", "source_version_id": "s1", "value": value},
                        {"cell_id": "variables", "column_id": "vars", "source_version_id": "s1", "value": "x is the decision variable"},
                        {"cell_id": "objective", "column_id": "obj", "source_version_id": "s1", "value": "Minimise x"},
                        {"cell_id": "other_source", "column_id": "obj", "source_version_id": "s2", "value": "OTHER SOURCE"}]}
    row = _section_input(passages=[passage] if origin == "passage" else [],
                         cells=[input_cell] if origin == "cell_quote" else [], attempt=1)
    db = {"sessions": [], "inputs": [row], "phrase_repairs": [], "frozen_snapshot": frozen}
    pairs = [{"source_key": "A", "formulation": "objective and constraints"},
             {"source_key": "B", "formulation": "unavailable formulation"}]
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"}, db=db, pairs=pairs)
    assert rows["R9"]["denominator"] == 1
    assert rows["R9"]["value"][0]["status"] == "eligible"
    first = (out / "review.md").read_text()
    units = kit._units(first)
    body = units["R9"]["P1"]["body"]
    for text in (claim["text"], equation,
                 "Karar değişkenleri", "Amaç fonksiyonu", "x is the decision variable", "Minimise x"):
        assert text in body
    not_given = body.split("#### (c) not given to the model", 1)[1]
    assert (json.dumps(value, ensure_ascii=False) in not_given) == (origin == "passage")
    assert (name in not_given) == (origin == "passage")
    assert "Later value" not in body and "OTHER SOURCE" not in body
    assert "no_input_equation" in units["R9"]["P2"]["body"]
    assert "- [ ]" not in units["R9"]["P2"]["body"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sheets"]["R9"] == {"required": ["P1"], "exempt": {"P2": "no_input_equation"}}
    assert manifest["sheets"]["R6"]["exempt"] == {"E1": "page_not_openable"}
    _complete_both(out)
    blind = kit._units((out / "second.md").read_text())["R9"]
    assert list(blind) == ["P1"] and body.rstrip() in blind["P1"]["body"].replace("- [x] ", "- [ ] ")
    result = kit.score(out)["R9"]
    assert result["status"] == "measured" and result["denominator"] == 1
    assert result["value"]["units"][1]["no_evidence_given"] is True


@pytest.mark.parametrize("name,answer_format,value", [
    ("Denklem parçaları", "text", "min x subject to x >= 0"),
    ("Equation parts", "text", "min x subject to x >= 0"),
    ("Denklem parçaları", "text", "Pasajda görüntülenen denklem yok."),
    ("Rate", "number_unit", {"number": 5, "unit": "Hz"}),
    ("Equation parts", "text", "$$x = 5$$"),
])
def test_r9_cell_value_and_report_output_do_not_establish_eligibility(tmp_path, monkeypatch, name, answer_format, value):
    claim = {"id": "eq_claim", "claim_key": "III.1", "text": "The objective minimises x with x >= 0.",
             "equation_ref": "eq1", "support_type": "source_stated", "evidence": [{"source_version_id": "s1"}]}
    report = {"status": "valid", "references": [{"source_version_id": "s1", "source_key": "A"},
                                               {"source_version_id": "s2", "source_key": "B"}],
              "sections": [{"section_id": "III", "status": "valid", "claims": [claim],
                            "draft": {"claims": [claim]}}],
              "table_i": {"cells": [{"cell_id": "cell1", "column_id": "col", "source_version_id": "s1",
                                     "value": "Later value must not appear"}]}}
    frozen = {"columns": [{"column_id": "col", "name": name, "answer_format": answer_format}],
              "cells": [{"cell_id": "cell1", "column_id": "col", "source_version_id": "s1", "value": value}]}
    db = {"sessions": [], "inputs": [], "phrase_repairs": [], "frozen_snapshot": frozen}
    pairs = [{"source_key": "A", "formulation": "objective and constraints"},
             {"source_key": "B", "formulation": "unavailable formulation"}]
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"}, db=db, pairs=pairs)
    assert rows["R9"]["denominator"] == 0
    assert rows["R9"]["status"] == "not_measurable"
    assert all(p["status"] == "no_input_equation" for p in rows["R9"]["value"])
    first = (out / "review.md").read_text()
    units = kit._units(first)
    assert claim["text"] in units["R9"]["P1"]["body"]
    assert json.dumps(value, ensure_ascii=False) in units["R9"]["P1"]["body"]
    assert name in units["R9"]["P1"]["body"]
    assert "Later value" not in units["R9"]["P1"]["body"]
    assert "no_input_equation" in units["R9"]["P2"]["body"]
    assert "- [ ]" not in units["R9"]["P2"]["body"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sheets"]["R9"] == {"required": [], "exempt": {"P1": "no_input_equation", "P2": "no_input_equation"}}
    assert manifest["sheets"]["R6"]["exempt"] == {"E1": "page_not_openable"}
    _complete_both(out)
    assert not kit._units((out / "second.md").read_text()).get("R9")
    result = kit.score(out)["R9"]
    assert result["status"] == "not_measurable" and result["denominator"] is None


def test_manifest_records_r3_without_cells_and_all_exempt_r9(tmp_path, monkeypatch):
    claim = {"id": "negative", "claim_key": "III.1", "text": "No study reported it.",
             "support_type": "source_stated", "evidence": [], "equation_ref": None}
    report = {"status": "valid", "references": [{"source_version_id": "s1", "source_key": "A"}],
              "sections": [{"section_id": "III", "status": "valid", "claims": [claim],
                            "draft": {"claims": [claim]}}],
              "table_i": {"columns": [{"column_id": "eq", "name": "Equation", "answer_format": "text"}],
                          "cells": [{"cell_id": "empty", "column_id": "eq", "source_version_id": "s1", "value": ""}]}}
    pairs = [{"source_key": "A", "formulation": "empty input"}]
    db = {"sessions": [], "inputs": [], "phrase_repairs": [], "frozen_snapshot": report["table_i"]}
    out, rows = _packet_snapshot(tmp_path, monkeypatch, report, {"status": "completed"}, db=db, pairs=pairs)
    assert rows["R9"]["denominator"] == 0 and rows["R9"]["status"] == "not_measurable"
    assert rows["R9"]["value"][0]["status"] == "no_input_equation"
    first = (out / "review.md").read_text()
    units = kit._units(first)
    assert "- [ ]" not in units["R3"]["N1"]["body"]
    assert "- [ ]" not in units["R9"]["P1"]["body"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sheets"]["R3"] == {"required": [], "exempt": {"N1": "no_evidence_given"}}
    assert manifest["sheets"]["R9"] == {"required": [], "exempt": {"P1": "no_input_equation"}}
    kit.second(out)
    assert not kit._units((out / "second.md").read_text())
    results = kit.score(out)
    assert results["R3"]["status"] == results["R9"]["status"] == "not_measurable"
    for group, uid in (("R3", "N1"), ("R9", "P1")):
        unit = units[group][uid]
        (out / "review.md").write_text(first.replace(unit["body"], "", 1))
        for command in (kit.second, kit.score):
            with pytest.raises(ValueError, match=rf"review\.md.*{group}/{uid}"):
                command(out)
    (out / "review.md").write_text(first)


def test_reader_added_r3_units_still_require_a_mark(reading_out):
    path = reading_out / "review.md"
    added = "\n".join(["#### M2 · IV · No study reported X · cells: cell_1", *kit._boxes(kit.R3_CHOICES), ""])
    path.write_text(path.read_text().replace("## R4b", added + "## R4b", 1))
    for command in (kit.second, kit.score):
        with pytest.raises(ValueError, match=r"review\.md.*R3/M2"):
            command(reading_out)
    _complete_both(reading_out)
    assert any(unit["id"] == "M2" for unit in kit.score(reading_out)["R3"]["value"]["units"])

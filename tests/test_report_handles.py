"""Synthetic checks of per-step report IDs; no model quality or scientific validity claim."""

import asyncio
import copy
import json

import pytest

from deixis.domain import contracts, skill
from deixis.workflow.report.sections import run_report
from deixis.workflow.flow import RunStopped
from fakes import parse_step_input
from test_contracts import CASES, STEP_INPUTS
from test_report_flow import report_flow, _claim
from test_report_failed_rows import add_source, fail_source, flagged


OLD_HASH = "sha256:08f1bdeadc63b809bdf6d123a1e77889cada14d64d3e851c3d9fe25bfb2704ee"


def fixture(name):
    return copy.deepcopy(STEP_INPUTS[name])


def output(name):
    return copy.deepcopy(next(case["output"] for case in CASES if case["name"] == name))


def at(data, path, replacement=None, *, set_value=False):
    parts = path.split("/")
    for part in parts[:-1]:
        data = data[int(part)] if isinstance(data, list) else data[part]
    key = int(parts[-1]) if isinstance(data, list) else parts[-1]
    if set_value:
        data[key] = replacement
    return data[key]


def section():
    si, draft = fixture("C_report_section_IV"), output("report_section_valid")
    pid, sid = si["passages"][0]["passage_id"], si["sources"][0]["source_id"]
    cid, col = "cel_SYNTHCELL0001", si["allowlist"]["column_ids"][0]
    si["passages"][0]["text_source"] = "text_layer"
    si["report_target"]["cells"] = [{
        "cell_id": cid, "cell_revision_id": "crv_SYNTHCELL0001", "column_id": col,
        "source_version_id": sid, "state": "value", "value": {"text": "SYNTHETIC"},
        "reading_depth": "abstract", "evidence": [{"passage_id": pid, "quote": si["passages"][0]["text"]}],
    }]
    si["allowlist"]["cell_ids"] = [cid]
    draft["claims"][0] |= {"cell_ids": [cid], "count": {
        "numerator_source_ids": [sid], "denominator_source_ids": [sid], "column_id": col},
        "equation_origin": {"passage_id": pid, "text_source": "text_layer"}}
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": None,
                                       "cell_id": cid, "quote": si["passages"][0]["text"]})
    draft["gaps"] = [{"gap_id": "gap9", "kind": "stated_limitation", "text": "SYNTHETIC candidate.",
                       "basis_claim_keys": [], "basis_passage_ids": [pid], "basis_cell_ids": [cid],
                       "nearest_match": {"status": "found", "source_id": sid, "cell_id": cid}}]
    return si, draft


SECTION_PATHS = [
    ("claims/0/passage_ids/0", "unknown_passage_id"),
    ("claims/0/cell_ids/0", "unknown_cell_id"),
    ("claims/0/count/numerator_source_ids/0", "unknown_source_id"),
    ("claims/0/count/denominator_source_ids/0", "unknown_source_id"),
    ("claims/0/count/column_id", "unknown_column_id"),
    ("claims/0/equation_origin/passage_id", "unknown_passage_id"),
    ("citation_anchors/0/passage_id", "unknown_passage_id"),
    ("citation_anchors/1/cell_id", "unknown_cell_id"),
    ("gaps/0/basis_passage_ids/0", "unknown_passage_id"),
    ("gaps/0/basis_cell_ids/0", "unknown_cell_id"),
    ("gaps/0/nearest_match/source_id", "unknown_source_id"),
    ("gaps/0/nearest_match/cell_id", "unknown_cell_id"),
]
PLAN_PATHS = ["glossary/0/passage_id", "axes/0/column_id", "limitations_column_id", "future_work_column_id"]


def handled_output(si, draft, paths):
    shown = copy.deepcopy(draft)
    handles = contracts.report_citation_handles(si)
    for path in paths:
        at(shown, path, handles[at(draft, path)], set_value=True)
    return shown


@pytest.mark.parametrize("path", PLAN_PATHS)
def test_report_plan_resolves_each_output_field_to_real_id(path):
    si, draft = fixture("C_report_plan"), output("report_plan_valid")
    shown = handled_output(si, draft, [path])
    resolved = contracts.resolve_citation_handles(si, json.dumps(shown))
    assert resolved == draft
    assert contracts.validate_model_output(si, resolved).ok


@pytest.mark.parametrize("path,code", SECTION_PATHS)
def test_report_section_resolves_each_output_field_to_real_id_with_quote_unchanged(path, code):
    si, draft = section()
    resolved = contracts.resolve_citation_handles(si, json.dumps(handled_output(si, draft, [path])))
    assert resolved == draft
    assert contracts.validate_model_output(si, resolved).ok


@pytest.mark.parametrize("path,code", SECTION_PATHS)
def test_report_section_refuses_fabricated_id_in_each_output_field(path, code):
    si, draft = section()
    prefix = {"unknown_passage_id": "psg_P", "unknown_cell_id": "cel_L",
              "unknown_source_id": "srv_S", "unknown_column_id": "col_C"}[code]
    bad = prefix + "9999999"
    at(draft, path, bad, set_value=True)
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert at(resolved, path) == bad
    validation = contracts.validate_model_output(si, resolved)
    assert not validation.ok
    assert any(issue.code == code and issue.path == "/" + path for issue in validation.issues)


@pytest.mark.parametrize("path", ["claims/0/passage_ids/0", "citation_anchors/0/passage_id",
                                  "gaps/0/basis_passage_ids/0", "claims/0/equation_origin/passage_id"])
def test_glossary_only_passage_has_display_handle_but_no_citation_permission(path):
    si, draft = section()
    extra = "psg_SYNTHGLOSSARY01"
    si["report_target"]["plan"]["glossary"].append({"term": "SYNTHETIC extra", "definition": "SYNTHETIC",
                                                  "passage_id": extra})
    shown = contracts.with_citation_handles(si)
    handle = contracts.report_citation_handles(si)[extra]
    assert handle == f"psg_P{len(si['passages']) + 1:07d}"
    assert extra not in json.dumps(shown)
    assert handle not in shown["allowlist"]["passage_ids"]
    assert contracts.validate_model_output(si, draft).ok
    at(draft, path, handle, set_value=True)
    validation = contracts.validate_model_output(si, contracts.resolve_citation_handles(si, json.dumps(draft)))
    assert not validation.ok and "unknown_passage_id" in validation.codes()


@pytest.mark.parametrize("field", ["numerator_source_ids", "denominator_source_ids"])
@pytest.mark.parametrize("failed_row", [False, True])
def test_count_over_unshown_snapshot_or_failed_row_source_is_refused(field, failed_row):
    si, draft = section()
    extra = "srv_SYNTHUNSHOWN01"
    if failed_row:
        si["report_target"]["limitations_core"] = {"failed_rows": [{"source_version_id": extra}]}
    assert contracts.validate_model_output(si, draft).ok  # Shown sources remain usable.
    draft["claims"][0]["count"][field] = [contracts.report_citation_handles(si).get(extra, extra)]
    report = contracts.validate_model_output(si, contracts.resolve_citation_handles(si, json.dumps(draft)))
    assert not report.ok and "unknown_source_id" in report.codes()


def test_failed_row_then_review_count_sources_have_display_only_handles_in_fixed_order():
    si = fixture("C_report_review")
    si["report_target"]["limitations_core"] = {"failed_rows": [
        {"source_version_id": "srv_SYNTHFAILED01"}, {"source_version_id": "srv_SYNTHFAILED02"}]}
    claim = si["report_target"]["review_sections"][0]["claims"][0]
    claim["count"] = {"numerator_source_ids": ["srv_SYNTHCOUNT001", "srv_SYNTHFAILED01"],
                      "denominator_source_ids": ["srv_SYNTHCOUNT002", "srv_SYNTHCOUNT001"],
                      "column_id": "col_SYNTHCOUNT001"}
    shown = contracts.with_citation_handles(si)
    handles = contracts.report_citation_handles(si)
    extras = ["srv_SYNTHFAILED01", "srv_SYNTHFAILED02", "srv_SYNTHCOUNT001", "srv_SYNTHCOUNT002"]
    for n, identifier in enumerate(extras, len(si["sources"]) + 1):
        assert handles[identifier] == f"srv_S{n:07d}"
        assert identifier not in json.dumps(shown)
        assert handles[identifier] not in shown["allowlist"]["source_ids"]
        assert handles[identifier] not in {s["source_id"] for s in shown["sources"]}
    assert "col_SYNTHCOUNT001" not in json.dumps(shown)
    assert handles["col_SYNTHCOUNT001"] not in shown["allowlist"]["column_ids"]
    assert contracts.report_citation_handles(json.loads(json.dumps(si))) == handles


def test_report_handle_order_and_restart_are_recomputed_from_each_stored_step():
    si, _ = section()
    target = si["report_target"]
    target["columns"].append(target["columns"][0] | {"column_id": "col_SYNTHORDER02"})
    si["allowlist"]["column_ids"].append("col_SYNTHORDER03")
    target["cells"][0]["column_id"] = "col_SYNTHORDER04"
    target["gap_candidates"] = [{"column_id": "col_SYNTHORDER05", "basis_cell_ids": []}]
    target["plan"]["axes"] = [{"column_id": "col_SYNTHORDER06"}]
    target["plan"]["future_work_column_id"] = "col_SYNTHORDER07"
    handles = contracts.report_citation_handles(si)
    assert [handles["col_SYNTHORDER" + f"{i:02d}"] for i in range(2, 8)] == [f"col_C{i:07d}" for i in range(2, 8)]
    other = copy.deepcopy(si)
    other["passages"] = [si["passages"][-1]]
    other["report_target"]["plan"]["glossary"] = []
    other["report_target"]["cells"] = [target["cells"][0] | {"cell_id": "cel_SYNTHOTHER001", "evidence": []}]
    other["allowlist"]["passage_ids"] = [other["passages"][0]["passage_id"]]
    other["allowlist"]["cell_ids"] = ["cel_SYNTHOTHER001"]
    assert contracts.report_citation_handles(other)[other["passages"][0]["passage_id"]] == "psg_P0000001"
    assert contracts.report_citation_handles(other)["cel_SYNTHOTHER001"] == "cel_L0000001"
    assert handles[si["passages"][-1]["passage_id"]] not in json.dumps(contracts.with_citation_handles(other))
    assert contracts.report_citation_handles(json.loads(json.dumps(si))) == handles


@pytest.mark.parametrize("bad,path,code", [
    ("psg_P0000O01", "claims/0/passage_ids/0", "unknown_passage_id"),
    ("psg_00000001", "claims/0/passage_ids/0", "unknown_passage_id"),
    ("cel_L0000001", "claims/0/passage_ids/0", "unknown_passage_id"),
    ("psg_P9999999", "claims/0/passage_ids/0", "unknown_passage_id"),
    ("psg_P0000001", "claims/0/cell_ids/0", "unknown_cell_id"),
])
def test_report_resolution_never_fuzzy_matches_or_crosses_id_kinds(bad, path, code):
    si, draft = section()
    at(draft, path, bad, set_value=True)
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert at(resolved, path) == bad
    assert code in contracts.validate_model_output(si, resolved).codes()


def test_report_leading_zero_normalisation_for_passages_and_third_cell_only():
    si, draft = section()
    first = si["report_target"]["cells"][0]
    si["report_target"]["cells"] += [first | {"cell_id": f"cel_SYNTHCELL000{n}"} for n in (2, 3)]
    draft["claims"][0]["passage_ids"] = ["psg_P00000001"]
    draft["claims"][0]["cell_ids"] = ["cel_L00000003"]
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert resolved["claims"][0]["passage_ids"] == [si["passages"][0]["passage_id"]]
    assert resolved["claims"][0]["cell_ids"] == ["cel_SYNTHCELL0003"]


def test_correct_real_long_report_ids_still_validate_existing_behavior():
    si, draft = section()
    assert contracts.resolve_citation_handles(si, json.dumps(draft)) == draft
    assert contracts.validate_model_output(si, draft).ok


def test_report_null_and_non_string_values_are_left_for_schema_validation():
    si, draft = section()
    draft["claims"][0]["count"] = None
    draft["claims"][0]["equation_origin"] = None
    draft["citation_anchors"][0]["passage_id"] = {"bad": True}
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert resolved == draft
    assert "schema_invalid" in contracts.validate_model_output(si, resolved).codes()
    plan = output("report_plan_valid")
    plan["limitations_column_id"] = plan["future_work_column_id"] = None
    assert contracts.resolve_citation_handles(fixture("C_report_plan"), json.dumps(plan)) == plan


def test_report_repair_issue_text_uses_current_step_handles():
    si, draft = section()
    pid = si["passages"][0]["passage_id"]
    shown = contracts.issues_with_handles(si, [{"code": "synthetic", "message": f"Bad evidence {pid}"}])
    assert shown[0]["message"] == "Bad evidence psg_P0000001"


def test_phrase_repair_display_preserves_the_evidence_its_step_input_already_carries():
    section_input = fixture("C_report_section_IV")
    repair_input = fixture("C_report_phrase_repair")
    before = copy.deepcopy(repair_input)
    shown_section = contracts.with_citation_handles(section_input)
    shown_repair = contracts.with_citation_handles(repair_input)
    assert repair_input == before
    for field in ("sources", "passages", "allowlist"):
        assert shown_repair[field] == shown_section[field]
    assert shown_repair["report_target"]["cells"] == shown_section["report_target"]["cells"]
    assert shown_repair["report_target"]["repair_request"] == before["report_target"]["repair_request"]


@pytest.mark.parametrize("path", PLAN_PATHS)
def test_report_plan_only_record_handles_do_not_grant_output_permission(path):
    si, draft = fixture("C_report_plan"), output("report_plan_valid")
    passage = path.endswith("passage_id")
    identifier = "psg_SYNTHDISPLAY01" if passage else "col_SYNTHDISPLAY01"
    si["report_target"]["plan"] = copy.deepcopy(draft)
    at(si["report_target"]["plan"], path, identifier, set_value=True)
    handle = contracts.report_citation_handles(si)[identifier]
    assert handle not in contracts.with_citation_handles(si)["allowlist"]["passage_ids" if passage else "column_ids"]
    at(draft, path, handle, set_value=True)
    report = contracts.validate_model_output(si, contracts.resolve_citation_handles(si, json.dumps(draft)))
    assert not report.ok
    assert any(issue.path == "/" + path for issue in report.issues)


def test_section_source_membership_includes_sources_of_shown_cells():
    si, draft = section()
    extra = "srv_SYNTHCELLSOURCE01"
    si["report_target"]["cells"][0]["source_version_id"] = extra
    draft["claims"][0]["count"]["numerator_source_ids"] = [extra]
    draft["claims"][0]["count"]["denominator_source_ids"] = [extra]
    draft["gaps"][0]["nearest_match"]["source_id"] = extra
    assert contracts.validate_model_output(si, draft).ok


def test_grounded_answer_shown_shape_matches_the_pre_p18_shape():
    si = fixture("A_answer")
    expected = copy.deepcopy(si)
    pids = {p["passage_id"]: f"psg_P{n:07d}" for n, p in enumerate(si["passages"], 1)}
    sids = {s["source_id"]: f"srv_S{n:07d}" for n, s in enumerate(si["sources"], 1)}
    for p in expected["passages"]:
        p["passage_id"], p["source_id"] = pids[p["passage_id"]], sids[p["source_id"]]
    for s in expected["sources"]:
        s["source_id"] = sids[s["source_id"]]
    expected["allowlist"]["passage_ids"] = [pids[p] for p in si["allowlist"]["passage_ids"]]
    expected["allowlist"]["source_ids"] = [sids[s] for s in si["allowlist"]["source_ids"]]
    assert contracts.with_citation_handles(si) == expected


def test_p18_method_hash_changes_and_integrity_passes():
    assert skill.load_skill_package().package_hash != OLD_HASH
    assert skill.integrity_issues() == []


def test_four_report_tasks_store_real_inputs_and_results_but_messages_and_sessions_keep_handles(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")
    asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["status"] == "valid"
    tasks = set()
    for row in store.conn.execute("SELECT * FROM step_inputs WHERE run_id = ?", (run["id"],)):
        payload = json.loads(row["payload_json"])
        if payload["task_type"] not in contracts.REPORT_TASKS:
            continue
        tasks.add(payload["task_type"])
        shown = parse_step_input(row["user_message"])
        assert shown == contracts.with_citation_handles(payload)
        for real, handle in contracts.report_citation_handles(payload).items():
            assert real not in row["user_message"]
            assert handle in row["user_message"]
        for field in ("passage_ids", "source_ids", "cell_ids", "column_ids"):
            assert len(shown["allowlist"][field]) == len(payload["allowlist"][field])
        assert all("_P000" not in p["passage_id"] for p in payload["passages"])
        assert all("_L000" not in c["cell_id"] for c in payload["report_target"]["cells"])
        assert shown["report_target"]["report_id"] == payload["report_target"]["report_id"]
        assert [c["cell_revision_id"] for c in shown["report_target"]["cells"]] == [
            c["cell_revision_id"] for c in payload["report_target"]["cells"]]
        session = store.model_session(payload["step_input_id"])
        raw = json.loads(session["raw_output"])
        step = store.conn.execute("SELECT output_json FROM run_steps WHERE id = ?", (row["step_id"],)).fetchone()
        assert json.loads(step[0])["result"] == contracts.resolve_citation_handles(payload, session["raw_output"])
        if payload["task_type"] in ("report_plan", "report_section") and raw.get("citation_anchors", raw.get("glossary")):
            assert "psg_P0000001" in session["raw_output"] or "cel_L0000001" in session["raw_output"]
        if payload["task_type"] == "report_phrase_repair":
            assert payload["sources"] == payload["passages"] == payload["report_target"]["cells"] == []
            assert shown["sources"] == shown["passages"] == shown["report_target"]["cells"] == []
            assert payload["allowlist"]["source_ids"] == payload["allowlist"]["passage_ids"] == []
    assert tasks == set(contracts.REPORT_TASKS)
    for link in store.conn.execute("SELECT passage_id, cell_id, source_version_id FROM report_citation_links"):
        assert not any(value and ("_P000" in value or "_L000" in value or "_S000" in value) for value in link)


def test_viii_failed_row_builder_sends_display_only_sources_and_review_count_builder_hides_extra_ids(tmp_path):
    state = report_flow(tmp_path)
    flow, store, reports, adapter, run, scope, report_id = state
    failed_id = add_source(state, "SYNTHETIC failed row")
    fail_source(state, failed_id)
    run = flagged(state)
    asyncio.run(run_report(flow, run, scope))
    # Select the VIII payload explicitly: frozen plan budgets also mention VIII in earlier sections.
    row = next(row for row in store.conn.execute("SELECT payload_json, user_message FROM step_inputs WHERE run_id = ?",
                                                 (run["id"],))
               if json.loads(row[0]).get("report_target", {}).get("section_id") == "VIII")
    payload, message = json.loads(row[0]), row[1]
    shown = parse_step_input(message)
    handle = contracts.report_citation_handles(payload)[failed_id]
    assert failed_id not in message and handle in message
    assert shown["sources"] == shown["allowlist"]["source_ids"] == []
    assert payload["report_target"]["limitations_core"]["failed_rows"][0]["source_version_id"] == failed_id
    claim = store.conn.execute("SELECT c.id FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
                               " WHERE s.report_id = ? LIMIT 1", (report_id,)).fetchone()
    from deixis.workflow.report.review import _input
    # A stored count may name records with no cited evidence; display must still conceal their raw IDs.
    count = {"numerator_source_ids": [failed_id], "denominator_source_ids": ["srv_SYNTHCOUNTEXTRA01"],
             "column_id": "col_SYNTHCOUNTEXTRA01"}
    store.conn.execute("UPDATE report_claims SET count_json = ? WHERE id = ?", (json.dumps(count), claim[0]))
    target, passages, _, _ = _input(flow, reports, report_id)
    source_ids = list(dict.fromkeys([p["source_version_id"] for p in passages]
                                    + [c["source_version_id"] for c in target["cells"]]))
    review = flow._step_input(run, scope, "stp_SYNTHREVIEW01", "report_review", [], source_ids,
                             passages, [], ("fake", "fake-model", None), report_target=target)
    assert contracts.check_step_input(review) == []
    handled = contracts.with_citation_handles(review)
    for identifier in (failed_id, "srv_SYNTHCOUNTEXTRA01", "col_SYNTHCOUNTEXTRA01"):
        assert identifier not in json.dumps(handled)
        mapped = contracts.report_citation_handles(review)[identifier]
        assert mapped not in handled["allowlist"]["source_ids"] + handled["allowlist"]["column_ids"]


def test_all_section_output_fields_are_resolved_before_storing_the_succeeded_result(tmp_path):
    from test_report_step_input import report_target
    flow, store, reports, adapter, run, scope, _ = report_flow(tmp_path, passage_kind="pdf_page")
    source_id = store.included_sources(run["research_id"])[0]
    passage = store.passages_for(source_id)[0]
    target = report_target(source_id, passage["id"])

    def response(si):
        from fakes import envelope
        pid, sid, cid, col = (si["passages"][0]["passage_id"], si["sources"][0]["source_id"],
                              si["report_target"]["cells"][0]["cell_id"], si["report_target"]["columns"][0]["column_id"])
        claim = _claim("IV", passage_ids=[pid], cell_ids=[cid]) | {
            "count": {"numerator_source_ids": [sid], "denominator_source_ids": [sid], "column_id": col},
            "equation_origin": {"passage_id": pid, "text_source": si["passages"][0]["text_source"]}}
        return json.dumps(envelope(si, "deixis.report_section_draft.v2") | {
            "section_id": "IV", "claims": [claim], "citation_anchors": [
                {"claim_key": "IV.1", "passage_id": pid, "cell_id": None, "quote": passage["text"]},
                {"claim_key": "IV.1", "passage_id": None, "cell_id": cid, "quote": target["cells"][0]["evidence"][0]["quote"]}],
            "subsections": [], "gaps": [{"gap_id": "gap9", "kind": "stated_limitation", "text": "SYNTHETIC",
                "basis_claim_keys": [], "basis_passage_ids": [pid], "basis_cell_ids": [cid],
                "nearest_match": {"status": "found", "source_id": sid, "cell_id": cid}}], "insufficient_evidence": []})

    # Use a quote present in this real stored synthetic PDF page for both passage and cell anchors.
    for cell in target["cells"]:
        cell["evidence"][0]["quote"] = passage["text"]
    adapter.responder = response
    result = asyncio.run(flow._model_step(run, scope, "report:IV", "report_section", source_ids=[source_id],
                                         passage_rows=[passage], report_target=target))
    stored = store.step_input_payload(result["step_input_id"])
    draft = result["result"]
    for path, _ in SECTION_PATHS:
        assert at(draft, path) in contracts.report_citation_handles(stored)
    assert draft["citation_anchors"][0]["quote"] == passage["text"]
    step = store.step(run["id"], "report:IV", "model:report_section")
    assert step["status"] == "succeeded" and step["output"]["result"] == draft


@pytest.mark.parametrize("kind,code", [("passage", "unknown_passage_id"), ("cell", "unknown_cell_id")])
def test_report_bad_id_after_one_repair_stops_section_without_salvage_or_dropped_citations(tmp_path, monkeypatch, kind, code):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = adapter.responder
    bad = "psg_P9999999" if kind == "passage" else "cel_L9999999"

    def forbidden_salvage(*args):
        pytest.fail("Reports must never call answer salvage")

    from deixis.workflow.report import sections
    original_links = sections._citation_links

    def guarded_links(payload, draft):
        assert draft["section_id"] != "IV", "Invalid IV output reached citation link construction"
        return original_links(payload, draft)

    monkeypatch.setattr(contracts, "salvage_answer_draft", forbidden_salvage)
    monkeypatch.setattr(sections, "_citation_links", guarded_links)

    def response(si):
        draft = json.loads(original(si))
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            draft["claims"][0]["passage_ids" if kind == "passage" else "cell_ids"] = [bad]
            draft["citation_anchors"][0] |= {"passage_id": bad if kind == "passage" else None,
                                            "cell_id": bad if kind == "cell" else None}
        return json.dumps(draft)

    adapter.responder = response
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert store.run(run["id"])["pause_reason"] == "section_failed"
    assert reports.section(report_id, "IV")["status"] == "failed"
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    assert step["error_code"] == "invalid_model_output"
    assert code in {i["code"] for i in json.loads(step["error_json"])}
    sessions = list(store.conn.execute("SELECT raw_output FROM model_sessions WHERE step_id = ?", (step["id"],)))
    assert len(sessions) == 2
    assert all(json.loads(s[0])["claims"][0]["passage_ids" if kind == "passage" else "cell_ids"] == [bad] for s in sessions)
    assert store.conn.execute("SELECT COUNT(*) FROM report_claims WHERE report_section_id = ?",
                              (reports.section(report_id, "IV")["id"],)).fetchone()[0] == 0


def test_report_schema_repair_message_names_display_only_passage_by_handle(tmp_path):
    from test_report_step_input import report_target
    flow, store, reports, adapter, run, scope, _ = report_flow(tmp_path)
    sid = store.included_sources(run["research_id"])[0]
    passage = store.passages_for(sid)[0]
    target = report_target(sid, passage["id"])
    extra = "psg_SYNTHGLOSSARYONLY01"
    target["plan"]["glossary"] = [{"term": "SYNTHETIC", "definition": "SYNTHETIC", "passage_id": extra}]
    original = adapter.responder

    def response(si):
        draft = json.loads(original(si))
        handle = si["report_target"]["plan"]["glossary"][0]["passage_id"]
        draft["claims"][0]["passage_ids"] = [handle]
        return json.dumps(draft)

    adapter.responder = response
    result = asyncio.run(flow._model_step(run, scope, "report:IV", "report_section", source_ids=[sid],
                                         passage_rows=[passage], report_target=target))
    assert result["invalid"] and "unknown_passage_id" in {i["code"] for i in result["issues"]}
    rows = list(store.conn.execute("SELECT payload_json, user_message FROM step_inputs WHERE run_id = ? ORDER BY rowid",
                                   (run["id"],)))
    assert len(rows) == 2
    payload, message = json.loads(rows[-1][0]), rows[-1][1]
    assert extra not in message
    handle = contracts.report_citation_handles(payload)[extra]
    assert message.count(handle) >= 2  # In the glossary and the recorded repair issue.

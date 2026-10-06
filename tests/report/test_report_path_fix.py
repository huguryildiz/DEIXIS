"""D198 replay and workflow evidence; synthetic behavior, not semantic validation.

Each test labels its role in its docstring. Red-on-old cases use existing runtime
seams before asserting the corrected behavior; new helper checks follow that assertion.
"""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts, skill
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.storage.db import new_id
from deixis.workflow.flow import RunStopped
from fakes import FakeAdapter, valid_response
from test_contracts import STEP_INPUTS
from test_report_step_input import report_flow


REPLAY = json.loads((Path(__file__).parent.parent / "fixtures/research/h9-report-replay.json").read_text())
for _record in REPLAY["sections"].values():
    _record["step_input"]["report_target"].setdefault("validation_context", None)
    _record["repair_step_input"]["report_target"].setdefault("validation_context", None)
OLD_HASH = "sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff"


class Capture(FakeAdapter):
    def __init__(self, handler, *, enforces_schema=True):
        super().__init__(enforces_schema=enforces_schema)
        self.handler, self.requests, self.raw = handler, [], []

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
        from fakes import parse_step_input
        si = parse_step_input(message)
        self.calls.append(si)
        self.requests.append({"schema": output_schema, "message": message, "developer": developer})
        result = self.handler(si, output_schema, message)
        if isinstance(result, ModelStepResult):
            return result
        raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        self.raw.append(raw)
        return ModelStepResult("completed", raw_text=raw, resolved_model=requested_model)


def rebind(draft, si, *, hash_value=None):
    draft = copy.deepcopy(draft)
    draft.update(step_input_id=si["step_input_id"], scope_revision=si["scope_revision"])
    draft["skill_package_hash"] = hash_value or si["skill_package_hash"]
    return draft


def patch(si, anchors=None, claims=None):
    return {"schema_version": "deixis.report_section_anchor_repair.v1",
            "step_input_id": si["step_input_id"], "scope_revision": si["scope_revision"],
            "anchors": anchors if anchors is not None else [{"anchor_index": 8, "quote_number": 1}],
            "claims": claims or []}


def run_step(tmp_path, task, template, handler, *, enforces_schema=True, allow_stop=False):
    flow, store, _, run, scope, _, _ = report_flow(tmp_path)
    adapter = Capture(handler, enforces_schema=enforces_schema)
    flow.deps.adapters["fake"] = adapter

    def builder(step_id):
        si = copy.deepcopy(template)
        si.update(step_id=step_id, step_input_id=new_id("sti"), research_id=run["research_id"],
                  run_id=run["id"], scope_revision=scope["revision"],
                  skill_package_hash=flow.deps.package.package_hash,
                  model={"connection": "fake", "requested_model": "fake-model"})
        si["task_type"] = task
        if "report_target" in si:
            si["report_target"].setdefault("validation_context", None)
        si["output_schema_versions"] = [contracts.SCHEMA_VERSIONS[n] for n in contracts.TASK_OUTPUTS[task]]
        return si

    try:
        output = asyncio.run(flow._model_step(run, scope, "D198:" + task, task,
                                             model=("fake", "fake-model", None), step_input_builder=builder,
                                             report_target=template.get("report_target")))
    except RunStopped:
        if not allow_stop:
            raise
        output = {"stopped": True}
    return output, store, adapter, flow, run


def sessions(store):
    return list(store.conn.execute("SELECT * FROM model_sessions ORDER BY rowid"))


def first_issues(store):
    return json.loads(sessions(store)[0]["validation_json"])["issues"]


def code_paths(issues):
    return [(i["code"], i["path"]) for i in issues]


def replay_run(tmp_path, section, repair, *, mixed=False, enforces_schema=True):
    record = REPLAY["sections"][section]
    attempts = 0

    def handler(si, schema, message):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            draft = rebind(record["first_output"], si)
            if mixed:
                draft["section_id"] = "IV" if section == "V" else "V"
            return draft
        assert attempts == 2, "No third call is allowed"
        return repair(si) if callable(repair) else rebind(repair, si)

    output, store, adapter, flow, run = run_step(tmp_path, "report_section", record["step_input"], handler,
                                               enforces_schema=enforces_schema)
    expected = code_paths(record["first_issues"])
    if mixed:
        expected = [("report_section_mismatch", "/section_id")] + expected
    assert code_paths(first_issues(store)) == expected
    return output, store, adapter, flow, run


@pytest.mark.parametrize("task,key", [("abstract_screening", "F_abstract_screening"),
                                     ("fulltext_adjudication", "H_fulltext_adjudication"),
                                     ("report_section", "C_report_section_IV")])
def test_e1_h9_miscopied_hash_succeeds_and_records_stamp(tmp_path, task, key):
    """Red on old E1: the no-repair screening call and other valid outputs survive H9 hash miscopies."""
    wrong = REPLAY["hashes"][task]["model"]
    def handler(si, schema, message):
        draft = json.loads(valid_response(si))
        draft["skill_package_hash"] = wrong
        return draft
    output, store, adapter, _, _ = run_step(tmp_path, task, STEP_INPUTS[key], handler)
    assert not output.get("invalid")
    assert len(adapter.calls) == 1
    si = store.step_input_payload(output["step_input_id"])
    assert output["result"]["skill_package_hash"] == si["skill_package_hash"]
    validation = json.loads(sessions(store)[0]["validation_json"])
    assert {"path": "/skill_package_hash", "stamped": "skill_package_hash", "model_value": wrong} in validation["normalised"]
    assert json.loads(sessions(store)[0]["raw_output"])["skill_package_hash"] == wrong


@pytest.mark.parametrize("section", ["IV", "V"])
def test_h9_reduced_fixture_reproduces_exact_stored_issues(section):
    """Historical guard plus RF4: IV's repair also blocks own-work wording and malformed math."""
    record = REPLAY["sections"][section]
    for prefix in ("first", "repair"):
        si = record["step_input"] if prefix == "first" else record["repair_step_input"]
        assert contracts.check_step_input(si) == []
        expected = copy.deepcopy(record[prefix + "_issues"])
        if section == "IV" and prefix == "repair":
            expected += [
                {"code": "own_work_phrase_in_claim", "path": "/claims/17/text", "message": "'Bu çalışmada' names this answer's own work, not a cited source"},
                {"code": "math_not_well_formed", "path": "/claims/14/text", "message": "math delimiters, braces or environments are not balanced"},
            ]
        assert [vars(i) for i in contracts.validate_model_output(si, record[prefix + "_output"]).issues] == expected


def test_a1_h9_iv_repairs_one_anchor_without_losing_other_content(tmp_path):
    """Red on old A1: a one-anchor patch succeeds through _model_step, preserving all other content."""
    output, store, adapter, _, _ = replay_run(tmp_path, "IV", patch)
    assert not output.get("invalid")
    original = REPLAY["sections"]["IV"]["first_output"]
    merged = output["result"]
    assert len(merged["claims"]) == 18 and merged["claims"] == original["claims"]
    assert len(merged["insufficient_evidence"]) == 2 and merged["insufficient_evidence"] == original["insufficient_evidence"]
    cell_id = original["citation_anchors"][8]["cell_id"]
    cell = next(c for c in REPLAY["sections"]["IV"]["step_input"]["report_target"]["cells"] if c["cell_id"] == cell_id)
    expected = copy.deepcopy(original["citation_anchors"])
    expected[8]["quote"] = cell["evidence"][0]["quote"]
    assert merged["citation_anchors"] == expected and "\ue0a8" in expected[8]["quote"]
    for name in contracts.ENVELOPE_FIELDS:
        assert merged[name] == store.step_input_payload(output["step_input_id"])[name]
    rows = sessions(store)
    assert len(rows) == 2 and rows[1]["raw_output"] == adapter.raw[1]
    assert json.loads(rows[1]["raw_output"]) == patch(adapter.calls[1])
    validation = json.loads(rows[1]["validation_json"])
    assert validation["normalised"] == []
    assert output["anchor_patch"] == validation["anchor_patch"]
    assert output["anchor_patch"]["base_step_input_id"] == rows[0]["step_input_id"]
    assert output["anchor_patch"]["changes"] == [{"anchor_index": 8, "old_quote": original["citation_anchors"][8]["quote"], "new_quote": expected[8]["quote"]}]


def test_a2_h9_iv_repair_retains_all_ambiguous_target_failures_after_stamp():
    """New contract A2 paired with E1: stamping cannot choose between two anchor targets."""
    record = REPLAY["sections"]["IV"]
    draft, changes = contracts.stamp_package_hash("report_section", record["repair_step_input"], copy.deepcopy(record["repair_output"]))
    report = contracts.validate_model_output(record["repair_step_input"], draft)
    assert "envelope_mismatch" not in report.codes()
    assert [i.code for i in report.issues] == ["citation_anchor_target_count"] * 21 + ["own_work_phrase_in_claim", "math_not_well_formed"]
    assert changes[0]["model_value"] == REPLAY["hashes"]["report_section"]["model"]


def test_a3_h9_v_full_repair_cannot_silently_drop_comparison_claims(tmp_path):
    """Red on old A3: a mixed failure forces full repair and detects H9 V.7 and V.8 loss."""
    output, store, adapter, _, _ = replay_run(tmp_path, "V", REPLAY["sections"]["V"]["repair_output"], mixed=True)
    assert output.get("invalid")
    assert [i["message"] for i in output["issues"] if i["code"] == "repair_dropped_claim"] == ["V.7", "V.8"]
    assert len(adapter.calls) == 2
    assert "Failed output (as received):\n" + adapter.raw[0] in adapter.requests[1]["message"]


def test_a4_h9_v_patch_records_removal_and_keeps_every_other_claim(tmp_path):
    """New contract A4 paired with A1: explicit removal remains visible without rewriting other claims."""
    record = REPLAY["sections"]["V"]
    indices = [int(i["path"].split("/")[2]) for i in record["first_issues"]]
    first = record["first_output"]
    removed_indices = {i for i in indices if first["citation_anchors"][i]["claim_key"] == "V.1"}
    def response(si):
        return patch(si, [{"anchor_index": i, "quote_number": None if i in removed_indices else 1} for i in indices],
                     [{"claim_key": "V.1", "text": None, "removed": True, "context": "No supporting stored quote",
                       "reason": "SYNTHETIC: the stored quotes do not establish this claim."}])
    output, _, _, _, _ = replay_run(tmp_path, "V", response)
    assert not output.get("invalid")
    merged = output["result"]
    assert merged["claims"] == [c for c in first["claims"] if c["claim_key"] != "V.1"]
    assert not any(a["claim_key"] == "V.1" for a in merged["citation_anchors"])
    assert merged["insufficient_evidence"][-1]["context"].startswith("V.1: ")


def test_a5_patch_message_has_numbered_quotes_without_passage_bait(tmp_path):
    """Red on old A5: repair pairs omit passage_id and send/store the patch schema, also for lenient adapters."""
    output, store, adapter, _, _ = replay_run(tmp_path, "IV", patch, enforces_schema=False)
    message = adapter.requests[1]["message"]
    block = message.split("Cell anchor repair pairs:\n", 1)[1].split("\nFor each failing anchor", 1)[0]
    assert '"passage_id"' not in block
    pairs = json.loads(block)
    assert [q["quote_number"] for q in pairs[0]["allowed_quotes"]] == list(range(1, len(pairs[0]["allowed_quotes"]) + 1))
    assert prompt.REPORT_SECTION_ANCHOR_PATCH_GUIDANCE in message
    schema = contracts.report_section_anchor_patch_schema()
    assert adapter.requests[1]["schema"] == schema
    row = store.conn.execute("SELECT output_schema_json FROM step_inputs WHERE id = ?", (output["step_input_id"],)).fetchone()
    assert json.loads(row[0]) == schema
    assert prompt.schema_appendix("report_section", schema) in adapter.requests[1]["developer"]
    assert prompt.schema_appendix("report_section", contracts.model_output_schema("report_section")) in adapter.requests[0]["developer"]


def test_a5_full_message_includes_failed_raw_output_and_key_guidance(tmp_path):
    """Red on old A5: full report repair sees the exact raw failed output and the preservation rule."""
    _, _, adapter, _, _ = replay_run(tmp_path, "V", REPLAY["sections"]["V"]["repair_output"], mixed=True)
    assert adapter.raw[0] in adapter.requests[1]["message"]
    assert prompt.REPORT_SECTION_FULL_REPAIR_GUIDANCE in adapter.requests[1]["message"]


def test_patch_application_that_fails_canonical_validation_keeps_audit_and_anchor_reason(tmp_path):
    """New contract paired with A1: a schema-valid patch cannot publish a canonically invalid merged section."""
    record = REPLAY["sections"]["IV"]
    calls = 0
    def response(si, schema, message):
        nonlocal calls
        calls += 1
        if calls == 1:
            draft = rebind(record["first_output"], si)
            draft["insufficient_evidence"] = [draft["insufficient_evidence"][0]] * 20
            return draft
        return patch(si, claims=[{"claim_key": "IV.9", "text": None, "removed": True,
                                 "context": "SYNTHETIC missing support", "reason": "SYNTHETIC reason"}])
    output, store, adapter, _, run = run_step(tmp_path, "report_section", record["step_input"], response)
    assert code_paths(first_issues(store)) == code_paths(record["first_issues"])
    assert output["invalid"] and len(adapter.calls) == 2
    assert output["issues"][0]["code"] == "anchor_not_in_cell_evidence"
    assert any(i["code"] == "schema_invalid" and i["path"] == "/insufficient_evidence" for i in output["issues"][1:])
    validation = json.loads(sessions(store)[1]["validation_json"])
    assert not validation["ok"] and validation["anchor_patch"]["base_step_input_id"] == sessions(store)[0]["step_input_id"]
    assert sessions(store)[1]["raw_output"] == adapter.raw[1]
    assert "result" not in store.step(run["id"], "D198:report_section", "model:report_section")["output"]


PATCH_FAILURES = [
    ("missing", "anchor_patch_index"), ("extra", "anchor_patch_index"), ("duplicate", "anchor_patch_index"),
    ("zero", "anchor_patch_quote_number"), ("beyond", "anchor_patch_quote_number"),
    ("removed_without_reason", "anchor_patch_removal"), ("kept_with_reason", "anchor_patch_removal"),
    ("unaffected_claim", "anchor_patch_claim"), ("unsupported", "anchor_patch_claim_unsupported"),
    ("long_context", "anchor_patch_removal"),
    ("non_object", "schema_invalid"), ("duplicate_claim", "anchor_patch_claim"),
    ("removed_with_text", "anchor_patch_removal"), ("wrong_revision", "envelope_mismatch"),
]


@pytest.mark.parametrize("kind,code", PATCH_FAILURES)
def test_a6_invalid_patch_fails_closed_without_a_third_call(tmp_path, kind, code):
    """New contract A6 paired with A1: every invalid choice is recorded and preserves the first anchor reason."""
    def response(si):
        draft = patch(si)
        claim = {"claim_key": "IV.9", "text": None, "removed": True,
                 "context": "SYNTHETIC missing support", "reason": "SYNTHETIC no support"}
        if kind == "missing":
            # Include a wrong index to retain the schema's minItems while missing the requested one.
            draft["anchors"] = [{"anchor_index": 7, "quote_number": 1}]
        elif kind == "extra":
            draft["anchors"].append({"anchor_index": 7, "quote_number": 1})
        elif kind == "duplicate":
            draft["anchors"] *= 2
        elif kind in ("zero", "beyond"):
            draft["anchors"][0]["quote_number"] = 0 if kind == "zero" else 999
        elif kind == "unsupported":
            draft["anchors"][0]["quote_number"] = None
        elif kind == "wrong_revision":
            draft["scope_revision"] += 1
        elif kind == "non_object":
            return "[]"
        else:
            if kind == "removed_without_reason": claim["reason"] = None
            if kind == "kept_with_reason": claim.update(removed=False, context=None)
            if kind == "unaffected_claim": claim["claim_key"] = "IV.1"
            if kind == "long_context": claim["context"] = "x" * 181
            if kind == "removed_with_text": claim["text"] = "SYNTHETIC replacement"
            if kind == "duplicate_claim": claim.update(removed=False, context=None, reason=None)
            draft["claims"] = [claim] * (2 if kind == "duplicate_claim" else 1)
        return draft
    output, store, adapter, _, run = replay_run(tmp_path, "IV", response)
    assert output.get("invalid") and len(adapter.calls) == 2
    assert code in {i["code"] for i in output["issues"]}
    assert code_paths(output["issues"][:1]) == code_paths(REPLAY["sections"]["IV"]["first_issues"])
    rows = sessions(store)
    assert rows[1]["raw_output"] == adapter.raw[1]
    validation = json.loads(rows[1]["validation_json"])
    assert not validation["ok"] and "anchor_patch" not in validation
    step = store.step(run["id"], "D198:report_section", "model:report_section")
    assert step["status"] == "failed" and step["error_code"] == "invalid_model_output"
    assert "result" not in step["output"]


@pytest.mark.parametrize("kind", ["wrong_revision", "model", "tool"])
def test_e3_binding_and_isolation_remain_enforced(tmp_path, kind):
    """Guard E3: short binding errors repair once; model mismatch and tool use stop before consuming output."""
    def response(si, schema, message):
        if kind == "model":
            return ModelStepResult("completed", raw_text=valid_response(si), resolved_model="wrong-model")
        if kind == "tool":
            return ModelStepResult("completed", raw_text=valid_response(si), resolved_model="fake-model", tool_item_types=["tool_call"])
        draft = json.loads(valid_response(si))
        draft["scope_revision"] = si["scope_revision"] + 1
        return draft
    if kind in ("model", "tool"):
        output, store, adapter, _, run = run_step(tmp_path, "report_section", STEP_INPUTS["C_report_section_IV"], response, allow_stop=True)
        assert output["stopped"]
        assert store.run(run["id"])["pause_reason"] == ("model_mismatch" if kind == "model" else "model_isolation_violation")
        assert len(adapter.calls) == 1 and sessions(store)[0]["validation_json"] is None
    else:
        output, store, adapter, _, _ = run_step(tmp_path, "report_section", STEP_INPUTS["C_report_section_IV"], response)
        assert output["invalid"] and len(adapter.calls) == 2
        assert "envelope_mismatch" in {i["code"] for i in output["issues"]}
        assert not json.loads(sessions(store)[1]["validation_json"])["ok"]


@pytest.mark.parametrize("marker", ["[report-anchor-patch]", "[report-bad-anchor]"])
def test_a9_browser_fixture_answers_patch_in_process(tmp_path, marker):
    """Red on old A9 for the success marker, guard for bad-anchor: real section state after exactly two IV calls."""
    from acceptance.fixture_server import ScriptedCodex, MODEL
    from test_report_flow import report_flow as full_flow
    from deixis.workflow.report.sections import run_report
    flow, store, reports, _, run, scope, report_id = full_flow(tmp_path)
    scope["question"] += " " + marker
    scripted = ScriptedCodex()
    captured = []
    class BrowserAdapter(FakeAdapter):
        async def run_step(self, base, developer, message, schema, requested_model, reasoning_effort=None):
            from fakes import parse_step_input
            si = parse_step_input(message)
            result = await scripted.run_step(base, developer, message, schema, MODEL)
            result.resolved_model = requested_model
            captured.append((si, schema, result.raw_text))
            return result
    flow.deps.adapters["fake"] = BrowserAdapter()
    if marker == "[report-bad-anchor]":
        with pytest.raises(RunStopped):
            asyncio.run(run_report(flow, run, scope))
        assert reports.section(report_id, "IV")["status"] == "failed"
    else:
        try:
            asyncio.run(run_report(flow, run, scope))
        except RunStopped:
            pass  # Assert the recorded state, including on the baseline that cannot apply a patch.
        iv_calls = [si for si, _, _ in captured if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV"]
        assert reports.section(report_id, "IV")["status"] == "valid" and len(iv_calls) == 2
    iv = [(si, schema, raw) for si, schema, raw in captured if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV"]
    assert len(iv) == 2
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    rows = list(store.conn.execute("SELECT * FROM model_sessions WHERE step_id = ? ORDER BY rowid", (step["id"],)))
    assert [i["code"] for i in json.loads(rows[0]["validation_json"])["issues"]] == ["anchor_not_in_cell_evidence"]
    assert "SYNTHETIC missing anchor P19 nowhere in stored evidence." in iv[0][2]
    assert iv[1][1] == contracts.report_section_anchor_patch_schema()
    if marker == "[report-bad-anchor]":
        assert reports.section(report_id, "IV")["validation"]["issues"][0]["code"] == "anchor_not_in_cell_evidence"
    else:
        draft = reports.section(report_id, "IV")["draft"]
        payload = store.step_input_payload(rows[1]["step_input_id"])
        anchor = next(a for a in draft["citation_anchors"] if a["cell_id"] is not None)
        cell = next(c for c in payload["report_target"]["cells"] if c["cell_id"] == anchor["cell_id"])
        assert anchor["quote"] == cell["evidence"][0]["quote"]


def test_m1_package_hash_changed_and_integrity_passes():
    """New contract M1 paired with E1: changed runtime identity plus the existing package-integrity guard."""
    package_hash = skill.load_skill_package().package_hash
    assert package_hash != OLD_HASH
    assert package_hash == "sha256:eb0c5e39407256ded24f1b209db34c1ef062e53419f809b1c155953a17586ac2"
    assert skill.integrity_issues() == []

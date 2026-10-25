"""D198 replay and workflow evidence; synthetic behavior, not semantic validation.

Each test labels its role in its docstring. Red-on-old cases use existing runtime
seams before asserting the corrected behavior; new helper checks follow that assertion.
"""

import asyncio
import copy
import json
import random
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.models.adapter import ModelStepResult
from deixis.storage.db import new_id
from deixis.workflow.run.flow import RunStopped
from fakes import FakeAdapter
from test_report_step_input import report_flow
from test_report_anchor_repair import two_cells, issues


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


def with_missing_anchors(stored, draft, *, pruned=False):
    """Stored H9 issues plus the later rule that every cited passage or cell has an anchor (H9 drafts predate it).

    With `pruned`, as _model_step validates: a claim that has an anchored citation loses its unanchored ones, so only
    claims with no anchored citation at all report missing anchors.
    """
    anchored = {(a["claim_key"], kind, a[kind + "_id"]) for a in draft["citation_anchors"]
                for kind in ("passage", "cell") if a[kind + "_id"] is not None}
    claims = [c for c in draft["claims"] if not pruned or not any(k == c["claim_key"] for k, _, _ in anchored)]
    cited = {(c["claim_key"], "passage", p) for c in claims for p in c["passage_ids"]}
    cited |= {(c["claim_key"], "cell", x) for c in claims for x in c["cell_ids"]}
    missing = [{"code": "missing_citation_anchor", "path": "/citation_anchors",
                "message": f"{key}:{target}: this citation requires an exact contiguous quote"}
               for key, _, target in sorted(cited - anchored)]
    at = max((n + 1 for n, i in enumerate(stored) if i["path"].startswith("/citation_anchors")), default=len(stored))
    return stored[:at] + missing + stored[at:]


def replay_run(tmp_path, section, repair, *, mixed=False, enforces_schema=True, first=None):
    record = REPLAY["sections"][section]
    first = first or record["first_output"]
    attempts = 0

    def handler(si, schema, message):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            draft = rebind(first, si)
            if mixed:
                draft["section_id"] = "IV" if section == "V" else "V"
            return draft
        assert attempts == 2, "No third call is allowed"
        return repair(si) if callable(repair) else rebind(repair, si)

    output, store, adapter, flow, run = run_step(tmp_path, "report_section", record["step_input"], handler,
                                               enforces_schema=enforces_schema)
    expected = code_paths(with_missing_anchors(record["first_issues"], first, pruned=True))
    if mixed:
        expected = [("report_section_mismatch", "/section_id")] + expected
    assert code_paths(first_issues(store)) == expected
    return output, store, adapter, flow, run


@pytest.mark.parametrize("section", ["IV"])
def test_h9_reduced_fixture_reproduces_exact_stored_issues(section):
    """Historical guard plus RF4: IV's repair also blocks own-work wording and malformed math."""
    record = REPLAY["sections"][section]
    for prefix in ("first", "repair"):
        si = record["step_input"] if prefix == "first" else record["repair_step_input"]
        assert contracts.check_step_input(si) == []
        expected = with_missing_anchors(copy.deepcopy(record[prefix + "_issues"]), record[prefix + "_output"])
        if section == "IV" and prefix == "repair":
            expected += [
                {"code": "own_work_phrase_in_claim", "path": "/claims/17/text", "message": "'Bu çalışmada' names this answer's own work, not a cited source"},
                {"code": "math_not_well_formed", "path": "/claims/14/text", "message": "math delimiters, braces or environments are not balanced"},
            ]
        assert [vars(i) for i in contracts.validate_model_output(si, record[prefix + "_output"]).issues] == expected


PATCH_FAILURES = [
    ("missing", "anchor_patch_index"), ("extra", "anchor_patch_index"), ("duplicate", "anchor_patch_index"),
    ("zero", "anchor_patch_quote_number"), ("beyond", "anchor_patch_quote_number"),
    ("removed_without_reason", "anchor_patch_removal"), ("kept_with_reason", "anchor_patch_removal"),
    ("unaffected_claim", "anchor_patch_claim"), ("unsupported", "anchor_patch_claim_unsupported"),
    ("long_context", "anchor_patch_removal"),
    ("non_object", "schema_invalid"), ("duplicate_claim", "anchor_patch_claim"),
    ("removed_with_text", "anchor_patch_removal"), ("wrong_revision", "envelope_mismatch"),
]


@pytest.mark.parametrize("kind,code", [p for p in PATCH_FAILURES if p[0] == "unsupported"])
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


def test_unanchored_report_link_is_pruned_but_a_claim_without_any_anchor_still_fails():
    """A cited cell no anchor names is dropped and recorded; a claim none of whose citations has an anchor is kept as
    it is and still fails with missing_citation_anchor, and an unknown ID is never pruned away."""
    record = REPLAY["sections"]["V"]
    si, draft = record["step_input"], copy.deepcopy(record["first_output"])
    claim = draft["claims"][0]
    key = claim["claim_key"]
    others = [a for a in draft["citation_anchors"] if a["claim_key"] != key]
    draft["citation_anchors"] = others  # this claim now has no anchor at all
    claim["cell_ids"].append("cel_unknown")
    report = contracts.validate_model_output(si, draft)
    pruned, warnings = contracts.prune_unanchored_report_links(si, draft, report.issues)
    assert key not in {w.claim_key for w in warnings}
    assert next(c for c in pruned["claims"] if c["claim_key"] == key) == claim
    after = contracts.validate_model_output(si, pruned)
    assert any(i.code == "missing_citation_anchor" and i.message.startswith(f"{key}:") for i in after.issues)
    assert any(i.code == "unknown_cell_id" and "cel_unknown" in i.message for i in after.issues)
    assert not any(i.code == "missing_citation_anchor" and not i.message.startswith(f"{key}:") for i in after.issues)
    assert warnings and all(w.code == "citation_link_pruned" and w.issue_codes == ["missing_citation_anchor"]
                            for w in warnings)


def test_a8_randomized_patches_never_invent_evidence_or_unnamed_text():
    """New contract property guard A8 paired with A1/A4/A7: random model choices bound every merged edit."""
    rng = random.Random(198)
    for _ in range(80):
        si, draft = two_cells()
        # Give each cell two distinct stored quote choices; only anchor 0 fails.
        for cell in si["report_target"]["cells"]:
            cell["evidence"].append(cell["evidence"][0] | {"quote": "SYNTHETIC second stored choice for " + cell["cell_id"]})
        before = copy.deepcopy(draft)
        pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
        number = rng.choice([None, 1, 2])
        text = rng.choice([None, "SYNTHETIC model rewrite within chosen support."])
        remove = rng.choice([False, True])
        choice = patch(si, [{"anchor_index": 0, "quote_number": number}], [{
            "claim_key": "IV.1", "text": None if remove else text, "removed": remove,
            "context": "SYNTHETIC no support" if remove else None,
            "reason": "SYNTHETIC reason" if remove else None}])
        validation = contracts.validate_report_section_anchor_patch(si, draft, pairs, choice)
        assert validation.ok
        merged, _ = contracts.apply_report_section_anchor_patch(si, draft, pairs, choice)
        assert len(merged["citation_anchors"]) <= len(draft["citation_anchors"])
        for anchor in merged["citation_anchors"]:
            old = next(a for a in before["citation_anchors"] if a["cell_id"] == anchor["cell_id"])
            assert {k: v for k, v in anchor.items() if k != "quote"} == {k: v for k, v in old.items() if k != "quote"}
            if anchor != old:
                assert anchor["cell_id"] == pairs[0]["cell_id"] and number is not None
                assert anchor["quote"] == pairs[0]["allowed_quotes"][number - 1]["quote"]
        if not remove:
            assert merged["claims"][0]["text"] == (text or before["claims"][0]["text"])
        assert draft == before

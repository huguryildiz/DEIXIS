"""Synthetic K2 contracts and fake transport only; no model behavior or scientific validation."""

import asyncio
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.domain.rules import LITERATURE_TASKS, MAX_SCHEMA_REPAIRS, NO_REPAIR_TASKS, schema_repairs, step_model
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow.run.flow import FlowDeps, HANDLE_TASKS, ResearchFlow, TIMEOUT_RETRIED_TASKS
from deixis.workflow.run.store import Store
from fakes import FakeAdapter, parse_step_input, valid_response
from test_contracts import CASES, STEP_INPUTS

TASKS = contracts.CANDIDATE_TASKS


def fixture(task="claim_assessment"):
    return copy.deepcopy(STEP_INPUTS["J_" + task])


def output(si=None):
    return json.loads(valid_response(si or fixture()))


def codes(si):
    return {issue.code for issue in contracts.check_step_input(si)}


def verdict(si, draft):
    return contracts.validate_model_output(si, draft)


def evidence(si, n=0):
    p = si["passages"][n]
    return {"passage_id": p["passage_id"], "quote": p["text"]}


def support(si, draft, i=0):
    draft["work_relevance"] = "related"
    draft["cells"][i].update(relation="explicit_support", condition_alignment="aligned", evidence=[evidence(si)])
    return draft


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_candidate_schemas_are_registered_strict_and_resolve_their_refs():
    names = ("ClaimDecomposition", "KillSearchQuery", "ClaimAssessment")
    files = ("claim-decomposition.schema.json", "kill-search-query.schema.json", "claim-assessment.schema.json")
    for task, name, filename in zip(TASKS, names, files):
        assert contracts.SCHEMA_FILES[name] == filename
        assert contracts.SCHEMA_VERSIONS[name] == f"deixis.{task}.v1"
        assert contracts.TASK_OUTPUTS[task] == (name,)
        validator = contracts.canonical_validator(name)
        Draft202012Validator.check_schema(validator.schema)
        for node in walk(validator.schema):
            if "$ref" in node:
                assert validator._resolver.lookup(node["$ref"]).contents
        wire = contracts.step_output_schema(task)
        assert "common.schema.json" not in json.dumps(wire)
        assert contracts.strict_compatibility_issues(wire) == []
        Draft202012Validator(wire).validate(output(fixture(task)))
        for node in walk(wire):
            if "$ref" in node:
                assert Draft202012Validator(wire)._resolver.lookup(node["$ref"]).contents
    validator = contracts.canonical_validator("StepInput")
    for node in walk(validator.schema):
        if "$ref" in node:
            assert validator._resolver.lookup(node["$ref"]).contents
    bad = []
    si = fixture("claim_decomposition")
    d = output(si)
    bad.append((si, d | {"extra": True}))
    d["elements"][0]["extra"] = True
    bad.append((si, copy.deepcopy(d)))
    d = output(si)
    bad.append((si, d | {"elements": d["elements"] * 2 + [d["elements"][0]]}))
    bad.append((si, d | {"elements": d["elements"][:1]}))
    si = fixture("kill_search_query")
    d = output(si)
    bad.append((si, d | {"setting_backup": [{"term": "SYNTHETIC"}] * 4}))
    si = fixture()
    d = support(si, output(si))
    bad.append((si, d | {"cells": d["cells"] * 2 + [d["cells"][0]]}))
    d["cells"][0]["evidence"] *= 4
    bad.append((si, copy.deepcopy(d)))
    d = output(si)
    bad.append((si, d | {"whole_claim_evidence": [evidence(si)] * 4}))
    d["cells"][0]["extra"] = True
    bad.append((si, d))
    d = support(si, output(si))
    d["cells"][0]["evidence"][0]["evidence_kind"] = "abstract"
    bad.append((si, d))
    for si, draft in bad:
        assert list(Draft202012Validator(contracts.step_output_schema(si["task_type"])).iter_errors(draft))


@pytest.mark.parametrize("key", ["J_claim_decomposition", "J_claim_decomposition_owner_text", "J_kill_search_query", "J_claim_assessment"])
def test_fixture_step_inputs_are_clean(key):
    si = copy.deepcopy(STEP_INPUTS[key])
    assert contracts.check_step_input(si) == []
    assert verdict(si, output(si)).ok


@pytest.mark.parametrize("code", ["support_without_evidence", "anchor_not_in_passage"])
def test_assessment_rejected_fixture_codes(code):
    case = next(c for c in CASES if c["name"] == "candidate_assessment_" + code)
    assert code in verdict(fixture(), case["output"]).codes()


def test_support_cell_needs_a_located_quote():
    si = fixture()
    d = support(si, output(si))
    assert verdict(si, d).ok
    d["cells"][0]["evidence"] = []
    assert "support_without_evidence" in verdict(si, d).codes()
    d["cells"][0]["evidence"] = [evidence(si) | {"quote": "SYNTHETIC absent invention"}]
    assert "anchor_not_in_passage" in verdict(si, d).codes()


@pytest.mark.parametrize("field,bad,code", [("passage_id", "psg_SYNTHUNKNOWN01", "unknown_passage_id")])
def test_an_unshown_real_id_is_rejected_not_resolved(field, bad, code):
    si = fixture()
    d = support(si, output(si))
    owner = d["cells"][0] if field == "element_ref" else d["cells"][0]["evidence"][0]
    owner[field] = bad
    assert contracts.resolve_citation_handles(si, json.dumps(d)) == d
    assert code in verdict(si, d).codes()


def candidate_flow(tmp_path, task, responder=valid_response, owner=False):
    """Temporary DB, no service or candidate store; target and source evidence are hand-built."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC background question", "attached", "quick", [], "fake", "research-model", "en")
    si = fixture("claim_decomposition_owner_text" if owner else task)
    target = si["candidate_target"]
    sids = [store.create_upload_source(s["title"]) for s in si["sources"]]
    remap = {s["source_id"]: sid for s, sid in zip(si["sources"], sids)}
    rows, pids = [], []
    with transaction(conn):
        for p in si["passages"]:
            loc = p["locator"]
            pid = store._insert_passage(remap[p["source_id"]], None, loc["kind"], loc["physical_page"],
                                        loc["printed_label"], p["abstract_origin"], None, None, p["text"])
            rows.append(store.passage(pid))
            pids.append(pid)
    passage_map = {p["passage_id"]: pid for p, pid in zip(si["passages"], pids)}
    for item in target["basis"]:
        if item["passage_id"] is not None:
            item["passage_id"] = passage_map[item["passage_id"]]
    if target["assessed_source_id"] is not None:
        target["assessed_source_id"] = remap[target["assessed_source_id"]]
    adapter = FakeAdapter(responder=responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8871), store,
                                {"fake": adapter}, skill.load_skill_package(), None))
    # Generic answer run is only a storage harness: K2 adds no candidate dispatch or stage mapping.
    run = store.create_run(rid, "answer", {"max_model_calls": 4, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    scope = store.scope(rid)
    scope.update(literature_model="unused-literature-model", literature_connection="unused", reasoning_effort="high")
    return flow, store, adapter, store.run(run["id"]), scope, sids, rows, target


def run_candidate(state, task):
    flow, store, adapter, run, scope, sids, passages, target = state
    return asyncio.run(flow._model_step(run, scope, "synthetic:candidate", task, source_ids=sids,
                                       passage_rows=passages, candidate_target=target))


def assert_fake_step(tmp_path, task):
    state = candidate_flow(tmp_path, task)
    flow, store, adapter, run, scope, sids, passages, target = state
    result = run_candidate(state, task)
    step = store.step(run["id"], "synthetic:candidate", "model:" + task)
    assert step["status"] == "succeeded" and step["output"] == result
    payload = store.step_input_payload(result["step_input_id"])
    assert payload["candidate_target"] == target
    assert payload["skill_files"] == ["SKILL.md", "references/candidate-check.md"]
    assert payload["output_schema_versions"] == ["deixis." + task + ".v1"]
    assert payload["skill_package_hash"] == flow.deps.package.package_hash == skill.package_hash()
    assert payload["allowlist"]["candidate_ids"] == []
    assert payload["allowlist"]["source_ids"] == sids
    assert payload["allowlist"]["passage_ids"] == [p["id"] for p in passages]
    message = store.conn.execute("SELECT user_message FROM step_inputs WHERE id = ?", (result["step_input_id"],)).fetchone()[0]
    shown = parse_step_input(message)
    assert shown == adapter.calls[0] == contracts.with_citation_handles(payload)
    raw = json.loads(store.model_session(result["step_input_id"])["raw_output"])
    assert result["result"] == contracts.resolve_citation_handles(payload, json.dumps(raw))
    assert len(adapter.calls) == 1
    for real, handle in contracts.citation_handles(payload).items():
        assert real not in message and handle in message
    if task == "claim_decomposition":
        assert raw["source_ids"] == ["srv_S0000001"] and raw["passage_ids"] == ["psg_P0000001"]
        assert result["result"]["source_ids"] == sids
        assert result["result"]["passage_ids"] == [passages[0]["id"]]
        assert raw["elements"][0]["element_ref"] == "e1"
    elif task == "claim_assessment":
        assert raw["cells"][0]["element_ref"] == "ele_E0000001"
        assert result["result"]["cells"][0]["element_ref"] == target["version"]["elements"][0]["element_id"]
        assert payload["allowlist"]["element_ids"] == [e["element_id"] for e in target["version"]["elements"]]
    else:
        assert payload["sources"] == payload["passages"] == []
        assert contracts.citation_handles(payload)[target["version"]["elements"][0]["element_id"]] == "ele_E0000001"
    assert adapter.sent == [(task, "research-model", "high")]
    assert task not in payload["capabilities"]["supported_tasks"]
    for table in ("research_candidates", "candidate_versions", "claim_matrix_cells", "claim_matrix_evidence"):
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_fake_adapter_answers_claim_decomposition_through_model_step(tmp_path):
    assert_fake_step(tmp_path, "claim_decomposition")


def test_fake_adapter_answers_kill_search_query_through_model_step(tmp_path):
    assert_fake_step(tmp_path, "kill_search_query")


def test_fake_adapter_answers_claim_assessment_through_model_step(tmp_path):
    assert_fake_step(tmp_path, "claim_assessment")


def forbidden_salvage(*args, **kwargs):
    pytest.fail("Candidate tasks must never use D56 answer salvage")


def test_candidate_step_repairs_once_then_stops_without_salvage(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "salvage_answer_draft", forbidden_salvage)

    def bad(si):
        d = support(si, output(si))
        d["cells"][0]["evidence"][0]["quote"] = "SYNTHETIC absent nonexistent invention on both attempts."
        return json.dumps(d)

    state = candidate_flow(tmp_path, "claim_assessment", bad)
    result = run_candidate(state, "claim_assessment")
    assert result["invalid"] and "anchor_not_in_passage" in {i["code"] for i in result["issues"]}
    assert len(state[2].calls) == 2
    step = state[1].step(state[3]["id"], "synthetic:candidate", "model:claim_assessment")
    assert step["status"] == "failed" and step["error_code"] == "invalid_model_output"
    messages = list(state[1].conn.execute("SELECT user_message FROM step_inputs ORDER BY rowid"))
    assert len(messages) == 2 and "anchor_not_in_passage" in messages[1][0] and "psg_P0000001" in messages[1][0]
    assert state[1].conn.execute("SELECT COUNT(*) FROM model_sessions").fetchone()[0] == 2


def test_candidate_tasks_use_the_research_model_and_default_repairs():
    scope = {"model_connection": "research", "requested_model": "chosen-research", "reasoning_effort": "high",
             "literature_connection": "literature", "literature_model": "chosen-literature", "literature_reasoning_effort": "low"}
    for task in TASKS:
        assert step_model(scope, task) == ("research", "chosen-research", "high")
        assert schema_repairs(task) == MAX_SCHEMA_REPAIRS == 1
        assert task in HANDLE_TASKS
        assert task not in LITERATURE_TASKS + NO_REPAIR_TASKS + TIMEOUT_RETRIED_TASKS

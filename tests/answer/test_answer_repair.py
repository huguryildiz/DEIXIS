"""Synthetic anchor pruning and FakeAdapter checks; no model or scientific validation."""

import asyncio
import copy
import json
import pytest
from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response
from test_contracts import STEP_INPUTS
from deixis.workflow.flow import INFERENCE_CAP_KEY, FlowDeps, ResearchFlow
from pathlib import Path
from deixis.domain import contracts


def draft_with_defect(si, defect):
    draft = json.loads(valid_response(si))
    first, second = si["passages"][:2]
    anchor = draft["citation_anchors"][0]
    if defect == "duplicate":
        draft["citation_anchors"].append(dict(anchor))
    elif defect == "duplicate_bad_first":
        draft["citation_anchors"].insert(0, dict(anchor, quote="SYNTHETIC quote absent from every passage"))
    elif defect in {"unfindable", "missing", "corrected"}:
        draft["claims"][0]["passage_ids"].append(second["passage_id"])
        draft["claims"].append(dict(draft["claims"][0], claim_label="c2", passage_ids=[second["passage_id"]]))
        if defect in {"unfindable", "corrected"}:
            draft["citation_anchors"].extend([
                dict(anchor, claim_label=label, passage_id=second["passage_id"],
                     quote=second["text"] if defect == "corrected" else
                     "SYNTHETIC quote absent from every passage") for label in ("c1", "c2")])
    elif defect == "uncited":
        draft["citation_anchors"].append(dict(anchor, passage_id=second["passage_id"]))
    elif defect == "unknown_uncited":
        draft["citation_anchors"].append(dict(anchor, passage_id="psg_UNKNOWN0001"))
    elif defect == "mixed":
        draft["citation_anchors"].append(dict(anchor))
        draft["claims"][0]["passage_ids"].append("psg_UNKNOWN0001")
    elif defect == "empty":
        draft["citation_anchors"] = []
    return draft


def run_step(tmp_path, defects):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    sid = store.create_upload_source("SYNTHETIC source")
    pids = [store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None, text)
            for text in ("SYNTHETIC first passage about release scheduling.",
                         "SYNTHETIC second passage about a relay budget.")]
    raw_outputs = []

    def responder(si):
        draft = draft_with_defect(si, defects[min(len(raw_outputs), len(defects) - 1)])
        raw_outputs.append(json.dumps(draft))
        return raw_outputs[-1]

    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8872), store,
                                 {"fake": adapter}, skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": 4, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    result = asyncio.run(flow._model_step(store.run(run["id"]), store.scope(rid), "synthetic:answer",
                        "grounded_answer", source_ids=[sid], passage_rows=[store.passage(pid) for pid in pids]))
    return result, store, adapter, raw_outputs, pids


@pytest.mark.parametrize("defect", ["unfindable"])
@pytest.mark.parametrize("last", ["corrected", "unfindable"])
def test_lossy_anchor_salvage_waits_for_repair_and_preserves_corrected_content(tmp_path, defect, last):
    result, store, adapter, raw_outputs, pids = run_step(tmp_path, [defect, last])
    try:
        assert len(adapter.calls) == 2
        assert not result.get("invalid")
        sessions = list(store.conn.execute("SELECT raw_output, validation_json FROM model_sessions ORDER BY rowid"))
        first = json.loads(sessions[0]["validation_json"])
        assert not first["ok"]
        assert {i["code"] for i in first["issues"]} == {
            "anchor_not_in_passage" if defect == "unfindable" else "missing_citation_anchor"}
        assert not any(w["code"] == "citation_anchor_salvaged" for w in first["warnings"])
        assert [s["raw_output"] for s in sessions] == raw_outputs
        warnings = [w for w in result["warnings"] if w["code"] == "citation_anchor_salvaged"]
        if last == "corrected":
            assert not warnings
            assert [c["claim_label"] for c in result["result"]["claims"]] == ["c1", "c2"]
            assert result["result"]["claims"][0]["passage_ids"] == pids
            assert result["result"]["claims"][1]["passage_ids"] == [pids[1]]
        else:
            assert {w["dropped"] for w in warnings} >= {"citation_link", "claim"}
            assert any(w["dropped"] == "claim" and w["claim_label"] == "c2" for w in warnings)
            assert [c["claim_label"] for c in result["result"]["claims"]] == ["c1"]
            assert result["result"]["claims"][0]["passage_ids"] == [pids[0]]
            # the failed repair left unlocated anchors: their links and the claim resting only on them are gone
            anchors = result["result"]["citation_anchors"]
            assert anchors and {(a["claim_label"], a["passage_id"]) for a in anchors} == {("c1", pids[0])}
        final = json.loads(sessions[-1]["validation_json"])
        assert final["ok"] and not final["issues"]
        assert final["warnings"] == result["warnings"]
        payload = store.conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?", (result["step_input_id"],)).fetchone()
        assert contracts.validate_model_output(json.loads(payload[0]), result["result"]).ok  # what survives validates
    finally:
        store.conn.close()


@pytest.mark.parametrize("defect", ["mixed", "empty"])
def test_non_salvageable_or_empty_answer_keeps_bounded_failure_path(tmp_path, defect):
    result, store, adapter, _, _ = run_step(tmp_path, [defect])
    try:
        assert len(adapter.calls) == 2 and result["invalid"]
        assert all(not any(w["code"] == "citation_anchor_salvaged" for w in json.loads(s[0])["warnings"])
                   for s in store.conn.execute("SELECT validation_json FROM model_sessions"))
    finally:
        store.conn.close()


@pytest.mark.parametrize("defect", ["label", "locator"])
def test_salvage_does_not_mask_other_defects_or_mutate_input(defect):
    si = copy.deepcopy(STEP_INPUTS["A_answer"])
    draft = draft_with_defect(si, "duplicate")
    if defect == "schema":
        draft["extra"] = True
    elif defect == "envelope":
        draft["scope_revision"] += 1
    elif defect == "label":
        draft["citation_anchors"][0]["claim_label"] = "c99"
    elif defect == "empty_claim":
        draft["claims"].append(dict(draft["claims"][0], claim_label="c2", passage_ids=[]))
    elif defect == "duplicate_id":
        draft["claims"][0]["passage_ids"] *= 2
    elif defect == "locator":
        draft["claims"][0]["text"] = "See page 123 for the result."
    before = copy.deepcopy(draft)
    salvaged, warnings = contracts.salvage_answer_draft(si, draft)
    assert not warnings and salvaged == before and draft == before


class RecordingAdapter(FakeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []

    async def run_step(self, base, developer, message, *args, **kwargs):
        self.messages.append(message)
        return await super().run_step(base, developer, message, *args, **kwargs)


def draft_for(si, mode):
    """Modes: inference (3 of 4 claims analyst_inference), rewritten (all source_stated), kept_label (rewritten, but
    the split parts of c2 keep its label), locator (rewritten with another blocker), small (3 claims, 2 inference)."""
    draft = json.loads(valid_response(si))
    by_source = {}
    for p in si["passages"]:
        by_source.setdefault(p["source_id"], p)
    one, two = list(by_source.values())[:2]
    text = {p["passage_id"]: p["text"] for p in si["passages"]}
    both = [one, two]
    shapes = {
        "inference": [("c1", "source_stated", [one]), ("c2", "analyst_inference", both), ("c3", "analyst_inference", both),
                      ("c4", "analyst_inference", both)],
        "rewritten": [("c1", "source_stated", [one]), ("c2", "source_stated", [two]), ("c3", "source_stated", [one]),
                      ("c4", "analyst_inference", both)],
        "kept_label": [("c1", "source_stated", [one]), ("c2", "source_stated", [one]), ("c2", "source_stated", [two]),
                       ("c4", "analyst_inference", both)],
        "locator": [("c1", "source_stated", [one]), ("c2", "source_stated", [two]), ("c3", "source_stated", [one]),
                    ("c4", "analyst_inference", both)],
        "small": [("c1", "source_stated", [one]), ("c2", "analyst_inference", both), ("c3", "analyst_inference", both)],
        "small_all_inference": [("c2", "analyst_inference", both), ("c3", "analyst_inference", both),
                                ("c4", "analyst_inference", both)],
    }
    draft["claims"] = [{"claim_label": label, "section": "Methods", "support_type": kind, "text": f"SYNTHETIC finding {label} {i}.",
                        "passage_ids": [p["passage_id"] for p in passages]} for i, (label, kind, passages) in enumerate(shapes[mode])]
    if mode == "locator":
        draft["claims"][0]["text"] = "See page 123 for the result."
    draft["citation_anchors"] = list({(c["claim_label"], pid): {"claim_label": c["claim_label"], "passage_id": pid, "quote": text[pid]}
                                      for c in draft["claims"] for pid in c["passage_ids"]}.values())
    draft["limitations"], draft["unanswered_aspects"] = [], []
    return draft


def setup(tmp_path, modes, max_model_calls=6):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    for title, text in (("SYNTHETIC source one", "SYNTHETIC first passage about release scheduling."),
                        ("SYNTHETIC source two", "SYNTHETIC second passage about a relay budget.")):
        sid = store.create_upload_source(title)
        store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None, text)
        store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
    sent = []

    def responder(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        sent.append(1)
        return json.dumps(draft_for(si, modes[min(len(sent) - 1, len(modes) - 1)]))

    adapter = RecordingAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8874), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": max_model_calls, "max_provider_requests": 0,
                                           "max_answer_passages": 16}, None)
    store.update_run(run["id"], status="running")
    return store, flow, adapter, rid, run["id"], sent


def answer_of(store, rid, flow, run_id):
    asyncio.run(flow._answer(store.run(run_id), store.scope(rid)))
    return dict(store.conn.execute("SELECT * FROM answers WHERE run_id = ?", (run_id,)).fetchone())


def claim_rows(store, answer):
    return list(store.conn.execute("SELECT label, support_type, text FROM claims WHERE answer_id = ? ORDER BY ordinal", (answer["id"],)))


def test_a_mostly_inference_answer_is_rewritten_once_and_the_rewrite_is_published(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "rewritten"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and answer["status"] == "structurally_valid"
        assert [r["support_type"] for r in claim_rows(store, answer)] == ["source_stated"] * 3 + ["analyst_inference"]
        message = adapter.messages[1]
        assert "c2, c3, c4" in message and "3 of its 4 claims" in message and "source_stated" in message
        assert adapter.sent[1][:2] == ("grounded_answer", "fake-model")
        payloads = [json.loads(r[0]) for r in store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE task_type = 'grounded_answer' ORDER BY rowid")]
        assert payloads[1]["passages"] == payloads[0]["passages"] and payloads[1]["allowlist"] == payloads[0]["allowlist"]
        record = json.loads(answer["validation_json"])["inference_cap"]
        assert record == {"labels": ["c2", "c3", "c4"], "claims": 4, "rewrite": {"inference": 1, "claims": 4}, "outcome": "published"}
        assert store.existing_step(run_id, INFERENCE_CAP_KEY)["output"]["inference_cap"]["outcome"] == "valid"
        step_id = store.conn.execute("SELECT step_id FROM answers WHERE id = ?", (answer["id"],)).fetchone()[0]
        assert step_id == store.existing_step(run_id, INFERENCE_CAP_KEY)["id"]
        again = answer_of(store, rid, flow, run_id)  # resumed: nothing sent again
        assert len(sent) == 2 and again["id"] == answer["id"]
    finally:
        store.conn.close()


@pytest.mark.parametrize("second", ["locator"])
def test_a_rewrite_still_over_the_cap_or_invalid_keeps_the_first_valid_answer(tmp_path, second):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", second])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and answer["status"] == "structurally_valid"  # never unpublished by the cap
        assert [r["support_type"] for r in claim_rows(store, answer)] == ["source_stated"] + ["analyst_inference"] * 3
        record = json.loads(answer["validation_json"])["inference_cap"]
        assert record["outcome"] == "kept_first" and record["labels"] == ["c2", "c3", "c4"]
        assert ("rewrite" in record) == (second != "locator")  # a valid rewrite still over the share, at any claim count
        step_id = store.conn.execute("SELECT step_id FROM answers WHERE id = ?", (answer["id"],)).fetchone()[0]
        assert step_id == store.existing_step(run_id, "grounded_answer")["id"]
        again = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and again["id"] == answer["id"]
    finally:
        store.conn.close()


@pytest.mark.parametrize("budget", [6])
def test_an_unavailable_connection_for_the_rewrite_publishes_the_first_answer_without_a_pause(tmp_path, budget):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "rewritten"], max_model_calls=budget)
    try:
        def before(si):
            if si["task_type"] == "grounded_answer":
                adapter.ready = False  # the connection goes down after the first answer
        adapter.before = before
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 1 and answer["status"] == "structurally_valid"
        assert store.run(run_id)["status"] == "running"
        record = json.loads(answer["validation_json"])["inference_cap"]
        assert record["outcome"] == ("skipped_budget" if budget == 1 else "call_failed")
        assert [r["support_type"] for r in claim_rows(store, answer)] == ["source_stated"] + ["analyst_inference"] * 3
    finally:
        store.conn.close()


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research"


SI = json.loads((FIXTURES / "step-inputs.json").read_text())["A_answer"]


VALID = next(c for c in json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"] if c["name"] == "answer_valid")["output"]


A1, A2, A3PRE, A3PUB, A5 = "srv_SYNA1pub01", "srv_SYNA2pub01", "srv_SYNA3pre01", "srv_SYNA3pub01", "srv_SYNA5pub01"


def entry(source, reason="no_answering_content", passage=None, quote=None, same_as=None, note="SYNTHETIC: left out."):
    return {"source_id": source, "reason": reason, "note": note, "passage_id": passage, "quote": quote,
            "same_as_source_id": same_as}


def ledger_of(entries=None, answer=None):
    answer = copy.deepcopy(answer or VALID)
    if entries is not None:
        answer["excluded_sources"] = entries
    links = contracts.derive_evidence_links(SI, answer)
    return contracts.answer_ledger(SI, answer, links, [])


def codes(ledger):
    return [(d["source_id"], d["code"]) for d in ledger["dropped"]]


def test_a_quote_from_another_source_or_outside_the_allowlist_is_dropped():
    other = entry(A2, "different_conditions", "psg_SYNA1abs01", "We formulate release-time scheduling")
    outside = entry(A5, "different_conditions", "psg_SYNB1pg001", "Nodes carry hydrophones.")
    ledger = ledger_of([other, entry(A3PUB), outside])
    assert codes(ledger) == [(A2, "entry_passage_other_source"), (A5, "entry_passage_unknown")]
    assert ledger["unaccounted"] == [A2, A5]


def test_handles_in_all_three_id_fields_resolve_and_round_trip():
    handles = contracts.citation_handles(SI)
    shown = {"excluded_sources": [
        {"source_id": handles[A2], "passage_id": "psg_P3", "same_as_source_id": "srv_S00000001"},
        {"source_id": "srv_S5", "passage_id": None, "same_as_source_id": None}]}
    data = contracts.resolve_citation_handles(SI, json.dumps(shown))
    assert data["excluded_sources"] == [{"source_id": A2, "passage_id": "psg_SYNA2abs01", "same_as_source_id": A1},
                                        {"source_id": A5, "passage_id": None, "same_as_source_id": None}]
    answer = copy.deepcopy(VALID)
    answer["excluded_sources"][0] |= {"reason": "same_finding_as_cited", "passage_id": "psg_SYNA2abs01",
                                      "quote": "share a limited nutrient supply", "same_as_source_id": A1}
    written = contracts.answer_with_handles(SI, answer)
    first = json.loads(written)["excluded_sources"][0]
    assert [first[key] for key in contracts.LEDGER_ID_FIELDS] == [handles[A2], handles["psg_SYNA2abs01"], handles[A1]]
    assert contracts.resolve_citation_handles(SI, written) == answer


@pytest.mark.parametrize("value, expected", [(None, [("ledger_field_malformed", "/excluded_sources")]), ([entry(A2)] * 201, [("ledger_too_many_entries", "/excluded_sources")])])
def test_the_split_removes_every_ledger_defect_and_the_answer_validates_on_its_claims(value, expected):
    draft = copy.deepcopy(VALID)
    if value is None:
        del draft["excluded_sources"]
    else:
        draft["excluded_sources"] = value
    kept, diagnostics = contracts.split_ledger(draft)
    assert draft["excluded_sources"] == [] and contracts.validate_model_output(SI, draft).ok
    assert [(d["code"], d["path"]) for d in diagnostics] == expected
    assert all(d["message"] for d in diagnostics)
    if isinstance(value, list):
        assert len(kept) == min(len(value), 200) - (len(expected) if expected[0][0] == "ledger_entry_malformed" else 0)
    if len(value or []) == 201:
        assert diagnostics[0]["count"] == 201

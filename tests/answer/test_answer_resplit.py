"""D249: one extra targeted repair when an answer still fails only on D247's several-sources rule after the first repair.

Scripted FakeAdapter and synthetic sources: these show workflow and persistence behaviour, not model quality.
"""

import asyncio
import json
import pytest
from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.workflow.flow import RESPLIT_KEY, FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response


class RecordingAdapter(FakeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []

    async def run_step(self, base, developer, message, *args, **kwargs):
        self.messages.append(message)
        return await super().run_step(base, developer, message, *args, **kwargs)


def draft_for(si, mode):
    """c1 and c2 cite source one; c3 cites source two. Modes: several (c2 cites both), split, locator."""
    draft = json.loads(valid_response(si))
    by_source = {}
    for p in si["passages"]:
        by_source.setdefault(p["source_id"], p)
    one, two = list(by_source.values())[:2]
    text = {p["passage_id"]: p["text"] for p in si["passages"]}
    claims = [("c1", [one]), ("c2", [one, two] if mode in ("several", "locator") else [one]), ("c3", [two])]
    if mode in ("split_kept_label", "split_kept_label_locator"):  # D259: the split parts keep the offending label c2
        claims = [("c1", [one]), ("c2", [one]), ("c2", [two]), ("c3", [two])]
    if mode == "split_shared_passage":  # both parts cite the same passage: which anchor is whose is unknown
        claims = [("c1", [one]), ("c2", [one]), ("c2", [one]), ("c3", [two])]
    draft["claims"] = [{"claim_label": label, "section": "Methods", "support_type": "source_stated",
                        "text": f"SYNTHETIC finding {label}.", "passage_ids": [p["passage_id"] for p in passages]}
                       for label, passages in claims]
    if mode in ("locator", "split_kept_label_locator"):
        draft["claims"][0]["text"] = "See page 123 for the result."  # another blocker next to the several-sources rule
    draft["citation_anchors"] = list({(c["claim_label"], pid): {"claim_label": c["claim_label"], "passage_id": pid, "quote": text[pid]}
                                      for c in draft["claims"] for pid in c["passage_ids"]}.values())
    draft["limitations"], draft["unanswered_aspects"] = [], []
    return draft


def setup(tmp_path, modes, max_model_calls=6):
    """An attached research with two uploaded sources; the n-th grounded_answer call answers with modes[n]."""
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
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8873), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": max_model_calls, "max_provider_requests": 0,
                                           "max_answer_passages": 16}, None)
    store.update_run(run["id"], status="running")
    return store, flow, adapter, rid, run["id"], sent


def answer_of(store, rid, flow, run_id):
    asyncio.run(flow._answer(store.run(run_id), store.scope(rid)))
    return dict(store.conn.execute("SELECT * FROM answers WHERE run_id = ?", (run_id,)).fetchone())


def sessions(store):
    return list(store.conn.execute(
        "SELECT s.operation_key, m.raw_output, m.validation_json FROM model_sessions m JOIN step_inputs i ON i.id = m.step_input_id"
        " JOIN run_steps s ON s.id = i.step_id WHERE i.task_type = 'grounded_answer' ORDER BY m.rowid"))


def test_an_anchor_naming_a_passage_outside_the_allowlist_is_never_repaired_as_a_several_sources_case():
    several = {"code": "source_stated_several_sources", "path": "/claims/1/passage_ids", "message": "c2: cites 2 sources"}
    uncited = {"code": "anchor_passage_not_cited", "path": "/citation_anchors/1/passage_id", "message": "psg_UNKNOWN"}
    si = {"allowlist": {"passage_ids": ["psg_1"]}}
    unknown = {"citation_anchors": [{"claim_label": "c1", "passage_id": "psg_UNKNOWN", "quote": "q"}]}
    assert contracts.resplit_labels([several, uncited], unknown, si) is None  # D244 refuses this draft as well
    assert contracts.salvage_answer_draft({"task_type": "grounded_answer", "allowlist": si["allowlist"]}, unknown) == (unknown, [])
    assert contracts.resplit_labels([several], "not json", si) is None
    assert contracts.resplit_labels([several], {"claims": []}, si) is None


def test_a_second_repair_that_splits_the_claim_publishes_the_answer_and_keeps_every_revision(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 3 and answer["status"] == "structurally_valid"
        assert [r["label"] for r in store.conn.execute("SELECT label FROM claims WHERE answer_id = ? ORDER BY ordinal", (answer["id"],))] == ["c1", "c2", "c3"]
        # All three revisions are stored: the original and the first repair under the answer step, the second repair under its own key.
        rows = sessions(store)
        assert [r["operation_key"] for r in rows] == ["grounded_answer", "grounded_answer", RESPLIT_KEY]
        assert [json.loads(r["validation_json"])["ok"] for r in rows] == [False, False, True]
        assert {i["code"] for i in json.loads(rows[1]["validation_json"])["issues"]} == {"source_stated_several_sources"}
        assert max(len(json.loads(r["raw_output"])["claims"][1]["passage_ids"]) for r in rows[:2]) == 2
        # The repair names the claim, keeps the same model and passages, and asks for per-source claims.
        message = adapter.messages[2]
        assert "c2" in message and "one source_stated claim per source" in message and "analyst_inference" in message
        assert adapter.sent[2][:2] == ("grounded_answer", "fake-model")
        payloads = [json.loads(r[0]) for r in store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE task_type = 'grounded_answer' ORDER BY rowid")]
        assert payloads[2]["passages"] == payloads[0]["passages"] and payloads[2]["allowlist"] == payloads[0]["allowlist"]
        # The outcome is recorded on the step and on the answer.
        step = store.existing_step(run_id, RESPLIT_KEY)
        assert step["status"] == "succeeded" and step["output"]["resplit"] == {"labels": ["c2"], "outcome": "published"}
        assert json.loads(answer["validation_json"])["extra_repair"] == {"labels": ["c2"], "outcome": "published"}
        assert store.run(run_id)["usage"]["model_calls"] == 3
    finally:
        store.conn.close()


def test_a_second_repair_that_still_fails_stores_the_unverified_draft_with_both_revisions(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 3 and answer["status"] == "unverified_draft"
        assert json.loads(answer["validation_json"])["extra_repair"] == {"labels": ["c2"], "outcome": "rejected"}
        assert store.existing_step(run_id, RESPLIT_KEY)["output"]["resplit"] == {"labels": ["c2"], "outcome": "rejected"}
        assert {i["code"] for i in json.loads(answer["validation_json"])["issues"]} == {"source_stated_several_sources"}
        assert json.loads(answer["draft_json"])["claims"][1]["claim_label"] == "c2"
        assert [r["operation_key"] for r in sessions(store)] == ["grounded_answer", "grounded_answer", RESPLIT_KEY]
        assert store.existing_step(run_id, RESPLIT_KEY)["status"] == "failed"
    finally:
        store.conn.close()


def crash_once(flow, when):
    """Make the first `_model_step` call whose key is RESPLIT_KEY raise before it starts, as a stop would."""
    original, armed = flow._model_step, [True]

    async def wrapper(run, scope, key, *args, **kwargs):
        if key == RESPLIT_KEY and armed[0] and when == "before_dispatch":
            armed[0] = False
            raise RuntimeError("stopped before the extra repair")
        return await original(run, scope, key, *args, **kwargs)
    flow._model_step = wrapper


def test_a_stop_during_the_extra_repair_resends_only_that_repair(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split"], max_model_calls=4)
    try:
        def stop(si):
            if si["task_type"] == "grounded_answer" and len(adapter.calls) == 3 and not stopped:
                stopped.append(1)
                raise RuntimeError("stopped while the extra repair was out")
        stopped = []
        adapter.before = stop
        with pytest.raises(Exception):
            answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 3
        answer = answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 4 and answer["status"] == "structurally_valid"  # one resend, not a fresh first step
        keys = [r["operation_key"] for r in sessions(store)]
        assert keys.count("grounded_answer") == 2 and keys.count(RESPLIT_KEY) == 2
    finally:
        store.conn.close()


@pytest.mark.parametrize("modes, status", [(["several"], "unverified_draft")])
def test_a_stop_after_validation_and_before_the_answer_is_stored_sends_nothing_again(tmp_path, modes, status):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, modes)
    try:
        original, armed = store.save_answer, [True]

        def save_once(*args, **kwargs):
            if armed[0]:
                armed[0] = False
                raise RuntimeError("stopped before the answer was stored")
            return original(*args, **kwargs)
        store.save_answer = save_once
        with pytest.raises(RuntimeError):
            answer_of(store, rid, flow, run_id)
        assert len(sent) == 3
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 3 and answer["status"] == status
        assert json.loads(answer["validation_json"])["extra_repair"]["outcome"] == (
            "published" if status == "structurally_valid" else "rejected")
    finally:
        store.conn.close()


def test_split_parts_citing_the_same_passage_are_not_relabelled_and_the_draft_stays_unverified(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split_shared_passage"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "unverified_draft"
        assert "duplicate_claim_label" in {i["code"] for i in json.loads(answer["validation_json"])["issues"]}
        assert json.loads(answer["validation_json"])["extra_repair"] == {"labels": ["c2"], "outcome": "rejected"}
    finally:
        store.conn.close()


def call_models(store, key):
    """For each call of the step under `key`: the StepInput's model, and the session's requested and resolved model."""
    return [(json.loads(r[0])["model"], r[1], r[2]) for r in store.conn.execute(
        "SELECT i.payload_json, m.requested_model, m.resolved_model FROM step_inputs i JOIN model_sessions m"
        " ON m.step_input_id = i.id JOIN run_steps s ON s.id = i.step_id WHERE s.operation_key = ? ORDER BY m.rowid", (key,))]


def test_an_extra_repair_resumed_after_a_model_change_records_the_model_it_is_sent_to(tmp_path):
    """S17: a paused answer whose research moved to another model sends the extra repair there, and its StepInput says so;
    the draft's passages and allowlist stay those of the attempt it repairs."""
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split"])
    try:
        crash_once(flow, "before_dispatch")
        with pytest.raises(RuntimeError):
            answer_of(store, rid, flow, run_id)
        store.update_run(run_id, status="paused")
        store.change_role_model(rid, "answer", "fake", "fake-model-2", None, store.research(rid)["version"])
        store.update_run(run_id, status="running")
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and adapter.sent[-1][:2] == ("grounded_answer", "fake-model-2")
        assert call_models(store, RESPLIT_KEY) == [({"connection": "fake", "requested_model": "fake-model-2"}, "fake-model-2", "fake-model-2")]
        first = call_models(store, "grounded_answer")
        assert {m["requested_model"] for m, _, _ in first} == {"fake-model"}  # the attempts it repairs keep theirs
        payloads = [json.loads(r[0]) for r in store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE task_type = 'grounded_answer' ORDER BY rowid")]
        assert payloads[2]["passages"] == payloads[1]["passages"] and payloads[2]["allowlist"] == payloads[1]["allowlist"]
    finally:
        store.conn.close()

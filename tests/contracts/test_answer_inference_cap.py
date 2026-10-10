"""D260: one rewrite of a valid answer whose claims are mostly analyst_inference.

Scripted FakeAdapter and synthetic sources: these show workflow and persistence behaviour, not model quality.
"""

import asyncio
import json

import pytest

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.workflow.flow import INFERENCE_CAP_KEY, FlowDeps, ResearchFlow
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


def test_cap_counts_only_answers_with_more_inference_than_source_claims():
    def answer(*kinds):
        return {"claims": [{"claim_label": f"c{i}", "support_type": k} for i, k in enumerate(kinds, 1)]}
    assert contracts.inference_cap_labels(answer("source_stated", *["analyst_inference"] * 3)) == ["c2", "c3", "c4"]
    assert contracts.inference_cap_labels(answer("source_stated", "source_stated", "analyst_inference", "analyst_inference")) is None
    assert contracts.inference_cap_labels(answer("source_stated", "analyst_inference", "analyst_inference")) is None  # under 4 claims
    for bad in (None, "x", {"claims": "x"}, {}):
        assert contracts.inference_cap_labels(bad) is None


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


@pytest.mark.parametrize("second", ["inference", "locator", "small_all_inference"])
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


def test_split_parts_of_the_rewrite_that_kept_a_label_are_relabelled(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "kept_label"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert [r["label"] for r in claim_rows(store, answer)] == ["c1", "c2", "c5", "c4"]
        record = json.loads(answer["validation_json"])["inference_cap"]
        assert record["outcome"] == "published" and record["relabelled"] == {"c2": ["c2", "c5"]}
    finally:
        store.conn.close()


@pytest.mark.parametrize("mode", ["rewritten", "small"])
def test_no_rewrite_when_the_answer_is_not_over_the_cap(tmp_path, mode):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [mode])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 1 and answer["status"] == "structurally_valid"
        assert "inference_cap" not in json.loads(answer["validation_json"])
        assert store.existing_step(run_id, INFERENCE_CAP_KEY) is None
    finally:
        store.conn.close()


def test_an_exhausted_call_budget_skips_the_rewrite_and_publishes_the_first_answer(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "rewritten"], max_model_calls=1)
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 1 and answer["status"] == "structurally_valid"
        assert json.loads(answer["validation_json"])["inference_cap"]["outcome"] == "skipped_budget"
        assert store.run(run_id)["status"] == "running"
    finally:
        store.conn.close()


def test_a_stop_during_the_rewrite_resends_only_the_rewrite(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "rewritten"])
    try:
        stopped = []

        def stop(si):
            if si["task_type"] == "grounded_answer" and len(adapter.calls) == 2 and not stopped:
                stopped.append(1)
                raise RuntimeError("stopped while the rewrite was out")
        adapter.before = stop
        with pytest.raises(Exception):
            answer_of(store, rid, flow, run_id)
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid"
        assert json.loads(answer["validation_json"])["inference_cap"]["outcome"] == "published"
        keys = [r[0] for r in store.conn.execute(
            "SELECT s.operation_key FROM model_sessions m JOIN step_inputs i ON i.id = m.step_input_id"
            " JOIN run_steps s ON s.id = i.step_id WHERE i.task_type = 'grounded_answer' ORDER BY m.rowid")]
        assert keys.count("grounded_answer") == 1 and keys.count(INFERENCE_CAP_KEY) == 2
    finally:
        store.conn.close()


def test_the_rewrite_quotes_the_accepted_answer_in_the_handles_the_model_was_shown(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "rewritten"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        first = store.existing_step(run_id, "grounded_answer")["output"]
        payload = store.step_input_payload(first["step_input_id"])
        quoted = contracts.answer_with_handles(payload, first["result"])
        message = adapter.messages[1]
        start = message.index("Previous output (as received):\n") + len("Previous output (as received):\n")
        shown, _ = json.JSONDecoder().raw_decode(message[start:])
        assert shown == json.loads(quoted)  # the accepted answer, not the raw output
        assert all(pid.startswith("psg_P") for c in json.loads(quoted)["claims"] for pid in c["passage_ids"])
        assert answer["status"] == "structurally_valid"
    finally:
        store.conn.close()


@pytest.mark.parametrize("budget", [6, 1])
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


@pytest.mark.parametrize("budget", [6, 1])
def test_a_question_revised_while_the_rewrite_fails_stops_the_run_instead_of_publishing(tmp_path, budget):
    from deixis.workflow.flow import RunStopped
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["inference", "rewritten"], max_model_calls=budget)
    try:
        def before(si):
            if si["task_type"] == "grounded_answer":
                adapter.ready = False
                store.conn.execute("UPDATE researches SET current_scope_revision = current_scope_revision + 1 WHERE id = ?", (rid,))
        adapter.before = before
        with pytest.raises(RunStopped):
            asyncio.run(flow._answer(store.run(run_id), store.scope(rid)))
        assert store.conn.execute("SELECT count(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
    finally:
        store.conn.close()

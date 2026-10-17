"""D83: one coverage rewrite of a valid answer whose evidence ledger leaves given works unaccounted.

Scripted FakeAdapter and synthetic sources: these show when the rewrite is sent, when it replaces the first answer and
what is recorded; they say nothing about whether a model finds the right works or gives the right reasons.
"""

import json

import pytest

from deixis.domain import contracts
from deixis.models.adapter import ModelStepResult
from deixis.workflow import spend
from deixis.workflow.flow import LEDGER_COVERAGE_KEY, RunStopped
from test_answer_ledger_flow import COVERAGE_LINE, answer_of, draft, entry, given, ledger, setup
LIMIT = {"kind": "scope", "text": "SYNTHETIC limitation of the first answer.", "source_ids": []}
NEW_LIMIT = {"kind": "access", "text": "SYNTHETIC limitation the rewrite adds.", "source_ids": []}


def by_label(out):
    """Claim text that names only its label, so a claim keeps its text wherever it stands."""
    for claim in out["claims"]:
        claim["text"] = f"SYNTHETIC finding {claim['claim_label']}."
    return out


def first_answer(si):
    """Cites source one, leaves source three out with a reason and source two unaccounted."""
    out = by_label(draft(si, [("c1", "source_stated", [0])], ledger=lambda order: [entry(order[2]["source_id"])]))
    out["limitations"] = [LIMIT]
    return out


def covered(si, **change):
    """The rewrite a model should return: the first answer kept, source two cited by a new claim, a new limitation."""
    out = by_label(draft(si, change.get("claims", [("c1", "source_stated", [0]), ("c2", "source_stated", [1])]),
                         ledger=change.get("ledger", lambda order: [entry(order[2]["source_id"])])))
    out["limitations"] = change.get("limitations", [LIMIT, NEW_LIMIT])
    return out


def coverage(answer):
    return json.loads(answer["validation_json"]).get("ledger_coverage")


def saved_key(store, answer):
    return store.conn.execute("SELECT s.operation_key FROM answers a JOIN run_steps s ON s.id = a.step_id WHERE a.id = ?",
                              (answer["id"],)).fetchone()[0]


def labels(store, answer):
    return [r[0] for r in store.conn.execute("SELECT label FROM claims WHERE answer_id = ? ORDER BY ordinal", (answer["id"],))]


def test_a_complete_ledger_sends_no_coverage_call(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [lambda si: draft(si, [("c1", "source_stated", [0])])])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(sent) == 1
        assert coverage(answer) is None and store.existing_step(run_id, LEDGER_COVERAGE_KEY) is None
    finally:
        store.conn.close()


def test_unaccounted_works_get_one_rewrite_that_is_published_and_a_resume_sends_nothing(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered])
    try:
        answer = answer_of(store, rid, flow, run_id)
        ids = given(store, answer)
        assert answer["status"] == "structurally_valid" and len(sent) == 2
        assert coverage(answer) == {"unaccounted_before": 1, "cited_before": 1, "excluded_before": 1,
                                    "after": {"unaccounted": 0, "cited": 2, "excluded": 1, "claims": 2}, "outcome": "published"}
        record = ledger(answer)
        assert record["complete"] is True and record["cited"] == ids[:2]
        assert saved_key(store, answer) == LEDGER_COVERAGE_KEY and labels(store, answer) == ["c1", "c2"]
        assert json.loads(answer["draft_json"])["limitations"] == [LIMIT, NEW_LIMIT]  # a new limitation may be added
        assert "inference_cap" not in json.loads(answer["validation_json"])
        payloads = [json.loads(r[0]) for r in store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE task_type = 'grounded_answer' ORDER BY rowid")]
        assert payloads[1]["passages"] == payloads[0]["passages"] and payloads[1]["allowlist"] == payloads[0]["allowlist"]
        assert adapter.sent[1][:2] == ("grounded_answer", "fake-model")
        assert store.existing_step(run_id, LEDGER_COVERAGE_KEY)["output"]["ledger_coverage"]["outcome"] == "valid"
        again = answer_of(store, rid, flow, run_id)  # resumed after the rewrite succeeded: nothing sent again
        assert len(sent) == 2 and again["id"] == answer["id"] and coverage(again) == coverage(answer)
    finally:
        store.conn.close()


def test_the_message_names_each_unaccounted_work_by_handle_and_title_and_no_record_id(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [lambda si: draft(si, [("c1", "source_stated", [0])], ledger=[]),
                                                               covered])
    try:
        answer = answer_of(store, rid, flow, run_id)
        ids = given(store, answer)
        message = adapter.messages[1]
        assert COVERAGE_LINE in message and "2 given sources" in message
        payload = store.step_input_payload(answer["step_input_id"])
        handles, titles = contracts.citation_handles(payload), {s["source_id"]: s["title"] for s in payload["sources"]}
        assert {titles[sid] for sid in ids[1:]} == {"SYNTHETIC source two", "SYNTHETIC source three"}
        for sid in ids[1:]:
            assert f"\n- {handles[sid]}: {titles[sid]}\n" in message and handles[sid].startswith("srv_S")
        assert not any(sid in message for sid in ids)
        assert coverage(answer)["unaccounted_before"] == 2
    finally:
        store.conn.close()


def locator(si):
    out = covered(si)
    out["claims"][1]["text"] = "See page 123 for the result."
    return out


def with_inference(si):
    return covered(si, claims=[("c1", "source_stated", [0]), ("c2", "analyst_inference", [1]), ("c3", "analyst_inference", [1])])


def two_claims(si):
    out = by_label(draft(si, [("c1", "source_stated", [0]), ("c2", "source_stated", [0])],
                         ledger=lambda order: [entry(order[2]["source_id"])]))
    out["limitations"] = [LIMIT]
    return out


def edited(field):
    def script(si):
        out = covered(si, claims=[("c1", "source_stated", [0]), ("c2", "source_stated", [0]), ("c3", "source_stated", [1])])
        claim = out["claims"][1]
        if field == "text":
            claim["text"] = "SYNTHETIC finding c2 written again."
        elif field == "passage":
            pid = out["citation_anchors"][-1]["passage_id"]
            claim["passage_ids"] = [pid]
            out["citation_anchors"] = [a for a in out["citation_anchors"] if a["claim_label"] != "c2"] + [
                {"claim_label": "c2", "passage_id": pid, "quote": next(p["text"] for p in si["passages"] if p["passage_id"] == pid)}]
        elif field == "anchor":
            anchor = next(a for a in out["citation_anchors"] if a["claim_label"] == "c2")
            anchor["quote"] = anchor["quote"][:30]
        return out
    return script


KEPT = {
    "invalid": ([first_answer, locator], "invalid", None),
    "not_fewer": ([first_answer, lambda si: covered(si, claims=[("c1", "source_stated", [0])])], "not_fewer_unaccounted", None),
    "dropped_cited": ([first_answer, lambda si: covered(si, claims=[("c2", "source_stated", [1])], ledger=lambda order: [
        entry(order[0]["source_id"]), entry(order[2]["source_id"])])], "dropped_cited_source", None),
    "inference_share": ([first_answer, with_inference], "over_inference_share", None),
    "claim_deleted": ([two_claims, lambda si: covered(si, claims=[("c1", "source_stated", [0]), ("c3", "source_stated", [1])])],
                      "changed_existing", "/claims/1"),
    "claim_text": ([two_claims, edited("text")], "changed_existing", "/claims/1"),
    "claim_passage": ([two_claims, edited("passage")], "changed_existing", "/claims/1"),
    "claim_anchor": ([two_claims, edited("anchor")], "changed_existing", "/claims/1"),
    "reordered": ([two_claims, lambda si: covered(si, claims=[("c2", "source_stated", [0]), ("c1", "source_stated", [0]),
                                                              ("c3", "source_stated", [1])])], "changed_existing", "/claims/1"),
    "limitation_dropped": ([first_answer, lambda si: covered(si, limitations=[NEW_LIMIT])], "changed_existing", "/limitations/0"),
    "exclusion_changed": ([first_answer, lambda si: covered(si, ledger=lambda order: [entry(order[2]["source_id"], note="SYNTHETIC: other.")])],
                          "changed_existing", "/excluded_sources/0"),
}


@pytest.mark.parametrize("case", list(KEPT))
def test_a_rewrite_that_fails_a_check_keeps_the_first_answer(tmp_path, case):
    scripts, reason, path = KEPT[case]
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, scripts)
    try:
        first_labels = ["c1", "c2"] if scripts[0] is two_claims else ["c1"]
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(sent) == 2  # never unpublished by the rewrite
        record = coverage(answer)
        assert record["outcome"] == "kept_first" and record["reason"] == reason and record.get("path") == path
        assert ("after" in record) == (reason != "invalid")
        assert saved_key(store, answer) == "grounded_answer" and labels(store, answer) == first_labels
        assert ledger(answer)["unaccounted"] == [given(store, answer)[1]]
        again = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and again["id"] == answer["id"]
    finally:
        store.conn.close()


def test_a_cited_source_whose_exclusion_entry_changes_is_not_a_change(tmp_path):
    """An entry for a work the rewrite now cites is no longer the ledger's: it may go."""
    def first(si):
        return by_label(draft(si, [("c1", "source_stated", [0])], ledger=lambda order: [entry(order[1]["source_id"], "off_topic")]))
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first, lambda si: covered(si, limitations=[])])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert coverage(answer)["outcome"] == "published" and ledger(answer)["complete"] is True
    finally:
        store.conn.close()


@pytest.mark.parametrize("error", ["finish reason max_tokens", "SYNTHETIC server error"])
def test_a_failed_or_truncated_call_keeps_the_first_answer_and_the_run_goes_on(tmp_path, error):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered])
    try:
        adapter.fail = lambda si: (ModelStepResult("failed", raw_text='{"claims": [', error=error, resolved_model="fake-model")
                                   if len(adapter.calls) == 2 else None)
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and saved_key(store, answer) == "grounded_answer"
        record = coverage(answer)
        assert record["outcome"] == "call_failed" and record["reason"] and "after" not in record
        assert store.run(run_id)["status"] == "running"
    finally:
        store.conn.close()


def test_an_exhausted_call_budget_skips_the_rewrite_without_a_call(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered], max_model_calls=1)
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 1 and answer["status"] == "structurally_valid"
        assert coverage(answer) == {"unaccounted_before": 1, "cited_before": 1, "excluded_before": 1, "outcome": "skipped_budget"}
        assert store.run(run_id)["status"] == "running" and store.existing_step(run_id, LEDGER_COVERAGE_KEY) is None
    finally:
        store.conn.close()


def test_a_spend_threshold_reached_after_the_first_answer_skips_the_rewrite_without_a_pause(tmp_path, monkeypatch):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered])
    try:
        monkeypatch.setattr(spend, "API_KEY_CONNECTIONS", spend.API_KEY_CONNECTIONS | {"fake"})
        monkeypatch.setattr(spend, "over_threshold", lambda store: {"threshold_usd": 0.01, "estimated_usd": 0.02} if sent else None)
        answer = answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 1 and answer["status"] == "structurally_valid"
        assert coverage(answer)["outcome"] == "skipped_spend" and saved_key(store, answer) == "grounded_answer"
        run = store.run(run_id)
        assert run["status"] == "running" and run["pause_reason"] is None
        assert store.existing_step(run_id, LEDGER_COVERAGE_KEY)["status"] == "cancelled"
    finally:
        store.conn.close()


def test_a_spend_threshold_still_pauses_the_first_answer(tmp_path, monkeypatch):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered])
    try:
        monkeypatch.setattr(spend, "API_KEY_CONNECTIONS", spend.API_KEY_CONNECTIONS | {"fake"})
        monkeypatch.setattr(spend, "over_threshold", lambda store: {"threshold_usd": 0.01, "estimated_usd": 0.02})
        with pytest.raises(RunStopped):
            answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 0 and store.run(run_id)["pause_reason"] == "spend_threshold"
    finally:
        store.conn.close()


def test_a_stop_during_the_rewrite_resends_only_the_rewrite(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered])
    try:
        stopped = []

        def stop(si):
            if len(adapter.calls) == 2 and not stopped:
                stopped.append(1)
                raise RuntimeError("stopped while the rewrite was out")
        adapter.before = stop
        with pytest.raises(Exception):
            answer_of(store, rid, flow, run_id)
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and coverage(answer)["outcome"] == "published"
        keys = [r[0] for r in store.conn.execute(
            "SELECT s.operation_key FROM model_sessions m JOIN step_inputs i ON i.id = m.step_input_id"
            " JOIN run_steps s ON s.id = i.step_id WHERE i.task_type = 'grounded_answer' ORDER BY m.rowid")]
        assert keys.count("grounded_answer") == 1 and keys.count(LEDGER_COVERAGE_KEY) == 2
    finally:
        store.conn.close()


def test_a_question_revised_while_the_rewrite_fails_stops_the_run_instead_of_publishing(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [first_answer, covered])
    try:
        def fail(si):
            if len(adapter.calls) < 2:
                return None
            store.conn.execute("UPDATE researches SET current_scope_revision = current_scope_revision + 1 WHERE id = ?", (rid,))
            return ModelStepResult("failed", error="SYNTHETIC server error", resolved_model="fake-model")
        adapter.fail = fail
        with pytest.raises(RunStopped):
            answer_of(store, rid, flow, run_id)
        assert store.conn.execute("SELECT count(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
    finally:
        store.conn.close()

"""D80: the evidence ledger through the answer flow, with its repairs (D244, D249, D260) and resumes.

Scripted FakeAdapter and synthetic sources: these show that the ledger never changes whether or how an answer is
published, and which attempt's ledger is stored; they say nothing about whether a model's reasons are right.
"""

import asyncio
import json
import pytest
from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.workflow.run.flow import LEDGER_COVERAGE_KEY, FlowDeps, ResearchFlow
from deixis.workflow.run.store import Store
from fakes import FakeAdapter, valid_response
from deixis.domain import contracts
from deixis.models.adapter import ModelStepResult
from deixis.workflow.run.flow import LEDGER_COVERAGE_KEY


MISSING = object()


class RecordingAdapter(FakeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []

    async def run_step(self, base, developer, message, *args, **kwargs):
        self.messages.append(message)
        return await super().run_step(base, developer, message, *args, **kwargs)


def entry(source, reason="no_answering_content", **fields):
    return {"source_id": source, "reason": reason, "note": "SYNTHETIC: left out.", "passage_id": None, "quote": None,
            "same_as_source_id": None} | fields


def draft(si, claims, ledger="full", quote=None):
    """`claims` are (label, support_type, [source positions]); the full ledger lists every source no claim cites."""
    passages = {p["source_id"]: p for p in si["passages"]}
    order = [passages[s["source_id"]] for s in si["sources"]]
    out = json.loads(valid_response(si))
    out["claims"] = [{"claim_label": label, "section": "Findings", "support_type": kind, "text": f"SYNTHETIC finding {label} {i}.",
                      "passage_ids": [order[j]["passage_id"] for j in at]} for i, (label, kind, at) in enumerate(claims)]
    out["citation_anchors"] = list({(c["claim_label"], pid): {"claim_label": c["claim_label"], "passage_id": pid,
                                                              "quote": quote or passages_text(si)[pid]}
                                    for c in out["claims"] for pid in c["passage_ids"]}.values())
    out["limitations"], out["unanswered_aspects"] = [], []
    cited = {pid for c in out["claims"] for pid in c["passage_ids"]}
    if ledger == "full":
        out["excluded_sources"] = [entry(p["source_id"]) for p in order if p["passage_id"] not in cited]
    elif ledger is MISSING:
        del out["excluded_sources"]
    else:
        out["excluded_sources"] = ledger(order) if callable(ledger) else ledger
    return out


def passages_text(si):
    return {p["passage_id"]: p["text"] for p in si["passages"]}


SHAPES = {
    "one": [("c1", "source_stated", [0])],
    "several": [("c1", "source_stated", [0]), ("c2", "source_stated", [0, 1]), ("c3", "source_stated", [1])],
    "split": [("c1", "source_stated", [0]), ("c2", "source_stated", [0]), ("c3", "source_stated", [1])],
    "inference": [("c1", "source_stated", [0]), ("c2", "analyst_inference", [0, 1]), ("c3", "analyst_inference", [0, 1]),
                  ("c4", "analyst_inference", [0, 1])],
    "rewritten": [("c1", "source_stated", [0]), ("c2", "source_stated", [1]), ("c3", "source_stated", [0]),
                  ("c4", "analyst_inference", [0, 1])],
}


# A ledger with every kind of defect: a scalar item, an entry for a cited source, an unknown key; the third source unlisted.
BROKEN = lambda order: [1, entry(order[0]["source_id"]), entry(order[1]["source_id"]) | {"why": "x"}]


def setup(tmp_path, scripts, max_model_calls=6):
    """An attached research with three uploaded sources; the n-th grounded_answer call answers with scripts[n](si)."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    for title, text in (("SYNTHETIC source one", "SYNTHETIC first passage about release scheduling."),
                        ("SYNTHETIC source two", "SYNTHETIC second passage about a relay budget."),
                        ("SYNTHETIC source three", "SYNTHETIC third passage about channel noise.")):
        sid = store.create_upload_source(title)
        store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None, text)
        store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
    sent = []

    def responder(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        sent.append(1)
        return json.dumps(scripts[min(len(sent) - 1, len(scripts) - 1)](si))

    adapter = RecordingAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8875), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": max_model_calls, "max_provider_requests": 0,
                                           "max_answer_passages": 16}, None)
    store.update_run(run["id"], status="running")
    return store, flow, adapter, rid, run["id"], sent


def answer_of(store, rid, flow, run_id):
    asyncio.run(flow._answer(store.run(run_id), store.scope(rid)))
    return dict(store.conn.execute("SELECT * FROM answers WHERE run_id = ?", (run_id,)).fetchone())


def sessions(store):
    """The answer's sessions, without the D83 coverage rewrite."""
    return [json.loads(r[0]) for r in store.conn.execute(
        "SELECT m.validation_json FROM model_sessions m JOIN step_inputs i ON i.id = m.step_input_id"
        " JOIN run_steps s ON s.id = i.step_id WHERE i.task_type = 'grounded_answer' AND m.validation_json IS NOT NULL"
        " AND s.operation_key != ? ORDER BY m.rowid", (LEDGER_COVERAGE_KEY,))]


def given(store, answer):
    return [s["source_id"] for s in store.step_input_payload(answer["step_input_id"])["sources"]]


def ledger(answer):
    return json.loads(answer["validation_json"]).get("evidence_ledger")


COVERAGE_LINE = "are neither cited by a claim nor listed in excluded_sources"


def answer_calls(adapter):
    """Calls other than the D83 coverage rewrite, which every valid answer that leaves a work unaccounted also gets."""
    return sum(COVERAGE_LINE not in message for message in adapter.messages)


def save_fails_once(store):
    original, armed = store.save_answer, [True]

    def save_once(*args, **kwargs):
        if armed[0]:
            armed[0] = False
            raise RuntimeError("stopped before the answer was stored")
        return original(*args, **kwargs)
    store.save_answer = save_once


def test_an_incomplete_ledger_publishes_the_answer_and_names_the_source_with_no_reason(tmp_path):
    script = lambda si: draft(si, SHAPES["one"], ledger=lambda order: [entry(order[1]["source_id"])])
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [script])
    try:
        answer = answer_of(store, rid, flow, run_id)
        ids = given(store, answer)
        assert answer["status"] == "structurally_valid" and answer_calls(adapter) == 1
        # D83: the coverage rewrite repeats the same ledger, so the first answer stands.
        assert json.loads(answer["validation_json"])["ledger_coverage"]["outcome"] == "kept_first"
        record = ledger(answer)
        assert record["cited"] == [ids[0]] and [e["source_id"] for e in record["excluded"]] == [ids[1]]
        assert record["unaccounted"] == [ids[2]] and record["complete"] is False and record["split"] == []
        assert json.loads(answer["draft_json"])["excluded_sources"] == [entry(ids[1])]  # what the model wrote, as IDs
        again = answer_of(store, rid, flow, run_id)  # resumed after the answer is saved: one row, the same ledger
        assert again["id"] == answer["id"] and ledger(again) == record and len(adapter.calls) == 2
        assert store.conn.execute("SELECT count(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 1
    finally:
        store.conn.close()


def outcome(store, answer, adapter):
    validation = json.loads(answer["validation_json"])
    return (answer["status"], answer_calls(adapter), validation.get("extra_repair"), validation.get("issues"),
            [sorted({i["code"] for i in s["issues"]}) for s in sessions(store)],
            [r[0] for r in store.conn.execute("SELECT label FROM claims WHERE answer_id = ? ORDER BY ordinal", (answer["id"],))])


def run_both(tmp_path, scripts_for):
    """The same scripted answers with a full ledger and with a broken one; returns (outcome, store, answer, adapter) each."""
    results = {}
    for name, led in (("clean", "full"), ("broken", BROKEN)):
        (tmp_path / name).mkdir()
        store, flow, adapter, rid, run_id, sent = setup(tmp_path / name, scripts_for(led))
        answer = answer_of(store, rid, flow, run_id)
        results[name] = (outcome(store, answer, adapter), store, answer, adapter)
    return results


def test_a_non_salvageable_issue_stores_the_same_unverified_draft_and_issues_and_no_ledger(tmp_path):
    def locator(si, led):
        out = draft(si, SHAPES["one"], ledger=led)
        out["claims"][0]["text"] = "See page 123 for the result."
        return out
    results = run_both(tmp_path, lambda led: [lambda si: locator(si, led)])
    try:
        assert results["clean"][0] == results["broken"][0]
        status, calls, _, issues, codes, _ = results["broken"][0]
        assert status == "unverified_draft" and calls == 2 and {i["code"] for i in issues} == {"locator_in_claim_text"}
        assert codes == [["locator_in_claim_text"]] * 2
        assert all(ledger(r[2]) is None for r in results.values())
    finally:
        for result in results.values():
            result[1].conn.close()


@pytest.mark.parametrize("value, expected", [(None, ["ledger_field_malformed"]), (lambda order: [entry([order[1]["source_id"]])], ["ledger_entry_malformed"])])
def test_malformed_ledgers_through_the_whole_pipeline_never_stop_the_answer(tmp_path, value, expected):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [lambda si: draft(si, SHAPES["one"], ledger=value)])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and answer_calls(adapter) == 1
        record = ledger(answer)
        assert [d["code"] for d in record["split"]] == expected and record["excluded"] == []
        ids = given(store, answer)
        assert record["cited"] == [ids[0]] and record["unaccounted"] == ids[1:]
        assert sessions(store)[0]["ledger"] == record["split"]
    finally:
        store.conn.close()


def test_the_view_names_left_out_works_from_their_records_and_null_for_an_answer_without_a_ledger(tmp_path):
    from deixis.workflow.run import views

    # Source two left out with a located quote and a note naming another title; source three with no entry.
    def quoted(si):
        two = next(p for p in si["passages"] if p["source_id"] == si["sources"][1]["source_id"])
        return draft(si, SHAPES["one"], ledger=[entry(two["source_id"], "different_conditions", passage_id=two["passage_id"],
                                                      quote=two["text"].removeprefix("SYNTHETIC ").rstrip("."),
                                                      note="SYNTHETIC: unlike “Some other title”.")])
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [quoted])
    try:
        answer = answer_of(store, rid, flow, run_id)
        ids = given(store, answer)
        passages = store.step_input_payload(answer["step_input_id"])["passages"]
        first = {p["source_id"]: p["passage_id"] for p in reversed(passages)}
        text = {p["passage_id"]: p["text"] for p in passages}
        records = {r["id"]: {"source_version_id": r["id"], "work_id": r["work_id"], "source_key": r["source_key"], "title": r["title"]}
                   for r in store.conn.execute("SELECT s.id, s.work_id, s.title, w.source_key FROM source_versions s"
                                               " LEFT JOIN works w ON w.id = s.work_id")}
        view = views.research_view(store, rid)["answers"][0]["evidence_ledger"]
        assert view["complete"] is False and view["cited"] == [ids[0]]
        assert view["given"] == [records[s] for s in ids]
        assert sorted(r["title"] for r in view["given"]) == ["SYNTHETIC source one", "SYNTHETIC source three", "SYNTHETIC source two"]
        # The title is the stored record's, not the note's; the row opens the passage where the quote was located.
        assert view["excluded"] == [records[ids[1]] | {
            "reason": "different_conditions", "note": "SYNTHETIC: unlike “Some other title”.", "same_as": None,
            "passage_id": first[ids[1]], "anchor_text": text[first[ids[1]]].removeprefix("SYNTHETIC ").rstrip(".")}]
        # No entry: the source's first given passage, with nothing to mark.
        assert view["unaccounted"] == [records[ids[2]] | {"passage_id": first[ids[2]], "anchor_text": None}]
        # An answer saved before the ledger existed has none: the view says null, not "0 left out".
        store.conn.execute("UPDATE answers SET validation_json = json_remove(validation_json, '$.evidence_ledger') WHERE id = ?",
                           (answer["id"],))
        assert views.research_view(store, rid)["answers"][0]["evidence_ledger"] is None
    finally:
        store.conn.close()


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
    "inference_share": ([first_answer, with_inference], "over_inference_share", None),
    "exclusion_changed": ([first_answer, lambda si: covered(si, ledger=lambda order: [entry(order[2]["source_id"], note="SYNTHETIC: other.")])],
                          "changed_existing", "/excluded_sources/0"),
}


@pytest.mark.parametrize("case", ["invalid"])
def test_a_rewrite_that_fails_a_check_keeps_the_first_answer(tmp_path, case):
    scripts, reason, path = KEPT[case]
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, scripts)
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(sent) == 2  # never unpublished by the rewrite
        record = coverage(answer)
        assert record["outcome"] == "kept_first" and record["reason"] == reason and record.get("path") == path
        assert ("after" in record) == (reason != "invalid") and "merged" not in record
        assert saved_key(store, answer) == "grounded_answer" and labels(store, answer) == ["c1"]
        assert ledger(answer)["unaccounted"] == [given(store, answer)[1]]
        again = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and again["id"] == answer["id"]
    finally:
        store.conn.close()


MERGED = {
    "claim_deleted": [two_claims, lambda si: covered(si, claims=[("c1", "source_stated", [0]), ("c3", "source_stated", [1])])],
    "claim_text": [two_claims, edited("text")],
    "claim_passage": [two_claims, edited("passage")],
    "claim_anchor": [two_claims, edited("anchor")],
    "reordered": [two_claims, lambda si: covered(si, claims=[("c2", "source_stated", [0]), ("c1", "source_stated", [0]),
                                                             ("c3", "source_stated", [1])])],
    "cited_source_dropped": [first_answer, lambda si: covered(si, claims=[("c2", "source_stated", [1])], ledger=lambda order: [
        entry(order[0]["source_id"]), entry(order[2]["source_id"])])],
}


MAX_TOKENS = ModelStepResult("failed", raw_text='{"claims": [', error="finish reason max_tokens", resolved_model="fake-model")


def fail_closure_once(store):
    original, armed = store.set_step_output, [True]

    def set_once(step_id, value):
        if armed[0] and isinstance(value, dict) and "coverage_closed" in value:
            armed[0] = False
            raise RuntimeError("stopped before the closure was written")
        return original(step_id, value)
    store.set_step_output = set_once


STOPS = {  # stop point → (rewrite script, what the coverage call returns, outcome saved after the resume)
    "after_send": (covered, "raise", "call_failed"),
    "failed_reply_pause": (covered, "max_tokens_pause", "call_failed"),
    "failed_reply_before_closure": (covered, "max_tokens_closure", "call_failed"),
    "failed_reply_before_save": (covered, "max_tokens_save", "call_failed"),
    "succeeded_reply_pause": (covered, "pause", "published"),
    "succeeded_reply_before_save": (covered, "save", "published"),
    "merged_before_save": (MERGED["claim_text"][1], "save", "published"),
}


@pytest.mark.parametrize("stop", ["after_send", "succeeded_reply_before_save"])
def test_the_coverage_call_is_sent_at_most_once_whatever_the_stop(tmp_path, stop):
    rewrite, how, expected = STOPS[stop]
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [two_claims if stop == "merged_before_save" else first_answer, rewrite])
    try:
        def second(si):
            return len(adapter.calls) == 2

        def before(si):
            if second(si) and how == "raise":
                raise RuntimeError("stopped while the rewrite was out")
            if second(si) and how in ("pause", "max_tokens_pause"):
                store.update_run(run_id, status="pause_requested")
        adapter.before = before
        adapter.fail = lambda si: MAX_TOKENS if second(si) and how.startswith("max_tokens") else None
        if how in ("save", "max_tokens_save"):
            save_fails_once(store)
        if how == "max_tokens_closure":
            fail_closure_once(store)
        with pytest.raises(Exception):
            answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 2
        if store.run(run_id)["status"] == "paused":
            store.update_run(run_id, status="running")
        answer = answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 2 and answer["status"] == "structurally_valid"
        record = coverage(answer)
        assert record["outcome"] == expected
        assert saved_key(store, answer) == (LEDGER_COVERAGE_KEY if expected == "published" else "grounded_answer")
        assert record.get("merged", False) is (stop == "merged_before_save")
        again = answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 2 and again["id"] == answer["id"]
        keys = [r[0] for r in store.conn.execute(
            "SELECT s.operation_key FROM model_sessions m JOIN run_steps s ON s.id = m.step_id ORDER BY m.rowid")]
        assert keys.count(LEDGER_COVERAGE_KEY) == 1
    finally:
        store.conn.close()

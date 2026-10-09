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


def test_eligibility_needs_a_several_sources_claim_and_nothing_but_salvageable_anchor_defects():
    several = {"code": "source_stated_several_sources", "path": "/claims/1/passage_ids", "message": "c2: cites 2 sources; write"}
    anchor = {"code": "duplicate_citation_anchor", "path": "/citation_anchors/3", "message": "c1:psg"}
    si = {"allowlist": {"passage_ids": ["psg_1", "psg_2"]}}
    draft = {"citation_anchors": [{"claim_label": "c1", "passage_id": "psg_1", "quote": "q"}]}
    labels = lambda issues, d=draft: contracts.resplit_labels(issues, d, si)
    assert labels([several, dict(several, message="c5: cites 3 sources")]) == ["c2", "c5"]
    assert labels([several, anchor]) == ["c2"]
    assert labels([anchor]) is None
    for other in ("locator_in_claim_text", "unknown_passage_id", "answer_title_too_long", "unknown_anchor_claim"):
        assert labels([several, {"code": other, "path": "/x", "message": "m"}]) is None
    assert labels([]) is None


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


def test_a_resumed_run_after_the_extra_repair_sends_nothing_again(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split"])
    try:
        first = answer_of(store, rid, flow, run_id)
        calls = len(adapter.calls)
        again = answer_of(store, rid, flow, run_id)  # the same answer path over the stored steps
        assert len(adapter.calls) == calls == 3 and again["id"] == first["id"]
        assert store.conn.execute("SELECT count(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 1
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


def test_another_blocker_next_to_the_several_sources_rule_gets_no_extra_repair(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["locator"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and answer["status"] == "unverified_draft"  # today's single repair
        assert "extra_repair" not in json.loads(answer["validation_json"])
        assert store.existing_step(run_id, RESPLIT_KEY) is None
    finally:
        store.conn.close()


@pytest.mark.parametrize("modes, calls", [(["several", "split"], 2), (["split"], 1)])
def test_no_extra_call_when_the_answer_is_already_valid(tmp_path, modes, calls):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, modes)
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == calls and answer["status"] == "structurally_valid"
        assert store.existing_step(run_id, RESPLIT_KEY) is None
        assert "extra_repair" not in json.loads(answer["validation_json"])
    finally:
        store.conn.close()


def test_an_exhausted_call_budget_skips_the_extra_repair_instead_of_pausing(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several"], max_model_calls=2)
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 2 and answer["status"] == "unverified_draft"
        assert store.run(run_id)["status"] == "running"
        assert json.loads(answer["validation_json"])["extra_repair"] == {"labels": ["c2"], "outcome": "skipped_budget"}
        assert store.existing_step(run_id, RESPLIT_KEY)["output"]["resplit"] == {"labels": ["c2"], "outcome": "skipped_budget"}
    finally:
        store.conn.close()


# --- Resume: the repair cap holds across a stop; a failed answer is recovered from stored sessions --------------------------

def crash_once(flow, when):
    """Make the first `_model_step` call whose key is RESPLIT_KEY raise before it starts, as a stop would."""
    original, armed = flow._model_step, [True]

    async def wrapper(run, scope, key, *args, **kwargs):
        if key == RESPLIT_KEY and armed[0] and when == "before_dispatch":
            armed[0] = False
            raise RuntimeError("stopped before the extra repair")
        return await original(run, scope, key, *args, **kwargs)
    flow._model_step = wrapper


def test_a_stop_before_the_extra_repair_resumes_without_asking_the_first_step_again(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split"], max_model_calls=3)
    try:
        crash_once(flow, "before_dispatch")
        with pytest.raises(RuntimeError):
            answer_of(store, rid, flow, run_id)
        assert len(sent) == 2
        answer = answer_of(store, rid, flow, run_id)
        # Three calls in all, inside a budget of three: the failed answer came from the stored sessions.
        assert len(sent) == 3 and answer["status"] == "structurally_valid"
        assert [r["operation_key"] for r in sessions(store)] == ["grounded_answer", "grounded_answer", RESPLIT_KEY]
        assert store.run(run_id)["usage"]["model_calls"] == 3
    finally:
        store.conn.close()


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


@pytest.mark.parametrize("modes, status", [(["several", "several", "split"], "structurally_valid"), (["several"], "unverified_draft")])
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


def test_a_resumed_extra_repair_keeps_the_passages_and_handles_of_the_attempt_it_repairs(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split"])
    try:
        crash_once(flow, "before_dispatch")
        with pytest.raises(RuntimeError):
            answer_of(store, rid, flow, run_id)
        retrieve = flow._retrieve
        flow._retrieve = lambda *args, **kwargs: list(reversed(retrieve(*args, **kwargs)))  # retrieval now answers in another order
        answer = answer_of(store, rid, flow, run_id)
        payloads = [json.loads(r[0]) for r in store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE task_type = 'grounded_answer' ORDER BY rowid")]
        assert len(payloads) == 3 and answer["status"] == "structurally_valid"
        assert payloads[2]["passages"] == payloads[1]["passages"] == payloads[0]["passages"]
        assert payloads[2]["allowlist"] == payloads[0]["allowlist"] and payloads[2]["model"] == payloads[0]["model"]
        assert contracts.citation_handles(payloads[2]) == contracts.citation_handles(payloads[0])
    finally:
        store.conn.close()


def test_a_rejected_answer_is_recovered_from_stored_sessions_while_the_connection_is_unavailable(tmp_path):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several"])
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
        adapter.ready = False  # the model connection is down on resume
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 3 and answer["status"] == "unverified_draft"
        assert store.run(run_id)["status"] == "running"
        assert json.loads(answer["validation_json"])["extra_repair"]["outcome"] == "rejected"
    finally:
        store.conn.close()


def test_a_question_revised_while_stopped_cancels_the_run_before_a_stored_answer_is_recovered(tmp_path):
    from deixis.workflow.flow import RunStopped
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several"])
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
        store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC revised question?", None)
        adapter.ready = False
        calls = len(adapter.calls)
        with pytest.raises(RunStopped):
            asyncio.run(flow._answer(store.run(run_id), store.scope(rid, 1)))
        run = store.run(run_id)
        assert run["status"] == "cancelled" and run["pause_reason"] == "scope_revised"
        assert store.conn.execute("SELECT count(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
        assert len(adapter.calls) == calls
    finally:
        store.conn.close()


def test_split_parts_that_kept_the_offending_label_get_new_labels_and_the_answer_is_published(tmp_path):
    """D259: the live irs2021 Deep failure, where the extra repair split c12 into three claims all labelled c12."""
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split_kept_label"])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 3 and answer["status"] == "structurally_valid"
        claims = list(store.conn.execute("SELECT label, text FROM claims WHERE answer_id = ? ORDER BY ordinal", (answer["id"],)))
        assert [c["label"] for c in claims] == ["c1", "c2", "c4", "c3"]  # order and text kept; the second part got the next free number
        assert [c["text"] for c in claims] == ["SYNTHETIC finding c1.", "SYNTHETIC finding c2.", "SYNTHETIC finding c2.", "SYNTHETIC finding c3."]
        links = list(store.conn.execute(
            "SELECT c.label, e.passage_id FROM evidence_links e JOIN claims c ON c.id = e.claim_id WHERE c.answer_id = ? ORDER BY c.ordinal",
            (answer["id"],)))
        raw = json.loads(sessions(store)[2]["raw_output"])
        assert [c["claim_label"] for c in raw["claims"]] == ["c1", "c2", "c2", "c3"]  # the session keeps what the model sent
        resolved = contracts.resolve_citation_handles(store.step_input_payload(store.existing_step(run_id, RESPLIT_KEY)["output"]["step_input_id"]),
                                                      sessions(store)[2]["raw_output"])
        assert [(l["label"], l["passage_id"]) for l in links] == [
            ("c1", resolved["claims"][0]["passage_ids"][0]), ("c2", resolved["claims"][1]["passage_ids"][0]),
            ("c4", resolved["claims"][2]["passage_ids"][0]), ("c3", resolved["claims"][3]["passage_ids"][0])]
        record = {"labels": ["c2"], "outcome": "published", "relabelled": {"c2": ["c2", "c4"]}}
        assert store.existing_step(run_id, RESPLIT_KEY)["output"]["resplit"] == record
        assert json.loads(answer["validation_json"])["extra_repair"] == record
        assert json.loads(sessions(store)[2]["validation_json"])["relabelled"] == {"c2": ["c2", "c4"]}
        again = answer_of(store, rid, flow, run_id)  # resumed: nothing sent again, same record
        assert len(sent) == 3 and again["id"] == answer["id"]
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


def test_relabel_touches_only_named_labels_with_unambiguous_anchors():
    def claim(label, *pids):
        return {"claim_label": label, "text": label, "passage_ids": list(pids)}

    def anchor(label, pid):
        return {"claim_label": label, "passage_id": pid, "quote": "q"}

    draft = {"claims": [claim("c1", "p1"), claim("c7", "p2"), claim("c7", "p3"), claim("c7", "p4"), claim("c3", "p5"), claim("c3", "p6")],
             "citation_anchors": [anchor("c1", "p1"), anchor("c7", "p2"), anchor("c7", "p3"), anchor("c7", "p4"),
                                  anchor("c3", "p5"), anchor("c3", "p6"), anchor("c9", "p9")]}
    fixed, renamed = contracts.relabel_split_claims(draft, ["c7"])
    assert renamed == {"c7": ["c7", "c10", "c11"]}  # after the highest number used anywhere, anchors included
    assert [c["claim_label"] for c in fixed["claims"]] == ["c1", "c7", "c10", "c11", "c3", "c3"]  # c3 was not named
    assert [a["claim_label"] for a in fixed["citation_anchors"]] == ["c1", "c7", "c10", "c11", "c3", "c3", "c9"]
    assert [c["claim_label"] for c in draft["claims"]] == ["c1", "c7", "c7", "c7", "c3", "c3"]  # the input is not changed
    # An anchor of the label whose passage none of the parts cites: no owner, nothing changes.
    stray = dict(draft, citation_anchors=draft["citation_anchors"] + [anchor("c7", "p8")])
    assert contracts.relabel_split_claims(stray, ["c7"]) == (stray, {})
    # A passage cited by two parts: no change.
    shared = dict(draft, claims=[claim("c7", "p2"), claim("c7", "p2", "p3")])
    assert contracts.relabel_split_claims(shared, ["c7"]) == (shared, {})
    # No free number left.
    full = {"claims": [claim("c999", "p1"), claim("c7", "p2"), claim("c7", "p3")], "citation_anchors": []}
    assert contracts.relabel_split_claims(full, ["c7"]) == (full, {})
    for bad in ("text", {"claims": "x", "citation_anchors": []}, {"claims": [claim("c7", "p1")]}):
        assert contracts.relabel_split_claims(bad, ["c7"]) == (bad, {})


@pytest.mark.parametrize("stop", [False, True])
def test_a_relabelled_repair_rejected_on_another_blocker_records_the_relabelling(tmp_path, stop):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, ["several", "several", "split_kept_label_locator"])
    try:
        if stop:  # recovered from the stored sessions on resume
            original, armed = store.save_answer, [True]

            def save_once(*args, **kwargs):
                if armed[0]:
                    armed[0] = False
                    raise RuntimeError("stopped before the answer was stored")
                return original(*args, **kwargs)
            store.save_answer = save_once
            with pytest.raises(RuntimeError):
                answer_of(store, rid, flow, run_id)
        answer = answer_of(store, rid, flow, run_id)
        assert len(sent) == 3 and answer["status"] == "unverified_draft"
        record = {"labels": ["c2"], "outcome": "rejected", "relabelled": {"c2": ["c2", "c4"]}}
        assert json.loads(answer["validation_json"])["extra_repair"] == record
        assert store.existing_step(run_id, RESPLIT_KEY)["output"]["resplit"] == record
        codes = {i["code"] for i in json.loads(answer["validation_json"])["issues"]}
        assert "duplicate_claim_label" not in codes and codes  # only the other blocker is left
    finally:
        store.conn.close()


def test_relabel_edges_malformed_values_and_the_last_free_number():
    def claim(label, *pids):
        return {"claim_label": label, "text": "t", "passage_ids": list(pids)}
    last = {"claims": [claim("c998", "p1"), claim("c998", "p2")],
            "citation_anchors": [{"claim_label": "c998", "passage_id": "p2", "quote": "q"}]}
    fixed, renamed = contracts.relabel_split_claims(last, ["c998"])
    assert renamed == {"c998": ["c998", "c999"]} and fixed["citation_anchors"][0]["claim_label"] == "c999"
    over = {"claims": [claim("c998", "p1"), claim("c998", "p2"), claim("c998", "p3")], "citation_anchors": []}
    assert contracts.relabel_split_claims(over, ["c998"]) == (over, {})
    for bad in ({"claims": [claim(["c2"], "p1"), claim("c2", "p2")], "citation_anchors": []},
                {"claims": [claim("c2", ["p1"]), claim("c2", "p2")], "citation_anchors": []},
                {"claims": [claim("c2", "p1"), claim("c2", "p2")], "citation_anchors": [{"claim_label": "c2", "passage_id": {"x": 1}}]},
                {"claims": [claim("c2", "p1"), claim("c2", "p2")], "citation_anchors": [{"passage_id": "p1"}]}):
        assert contracts.relabel_split_claims(bad, ["c2"]) == (bad, {})

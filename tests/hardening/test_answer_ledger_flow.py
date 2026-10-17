"""D80: the evidence ledger through the answer flow, with its repairs (D244, D249, D260) and resumes.

Scripted FakeAdapter and synthetic sources: these show that the ledger never changes whether or how an answer is
published, and which attempt's ledger is stored; they say nothing about whether a model's reasons are right.
"""

import asyncio
import json

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.models import prompt
from deixis.storage import db
from deixis.workflow.flow import INFERENCE_CAP_KEY, RESPLIT_KEY, FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response

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
    return [json.loads(r[0]) for r in store.conn.execute(
        "SELECT m.validation_json FROM model_sessions m JOIN step_inputs i ON i.id = m.step_input_id"
        " WHERE i.task_type = 'grounded_answer' AND m.validation_json IS NOT NULL ORDER BY m.rowid")]


def given(store, answer):
    return [s["source_id"] for s in store.step_input_payload(answer["step_input_id"])["sources"]]


def ledger(answer):
    return json.loads(answer["validation_json"]).get("evidence_ledger")


def hint_block(message):
    return message[message.index(prompt.LEDGER_HINTS_HEADING):].split("\n\n")[0]


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
        assert answer["status"] == "structurally_valid" and len(adapter.calls) == 1
        record = ledger(answer)
        assert record["cited"] == [ids[0]] and [e["source_id"] for e in record["excluded"]] == [ids[1]]
        assert record["unaccounted"] == [ids[2]] and record["complete"] is False and record["split"] == []
        assert json.loads(answer["draft_json"])["excluded_sources"] == [entry(ids[1])]  # what the model wrote, as IDs
        again = answer_of(store, rid, flow, run_id)  # resumed after the answer is saved: one row, the same ledger
        assert again["id"] == answer["id"] and ledger(again) == record and len(adapter.calls) == 1
        assert store.conn.execute("SELECT count(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 1
    finally:
        store.conn.close()


def test_a_repair_for_a_blocking_issue_carries_ledger_hints_outside_the_issues(tmp_path):
    bad = lambda si: draft(si, SHAPES["one"], ledger=BROKEN, quote="SYNTHETIC words that no passage contains anywhere.")
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [bad, lambda si: draft(si, SHAPES["one"])])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(sent) == 2
        first, second = sessions(store)
        assert {i["code"] for i in first["issues"]} == {"anchor_not_in_passage"}  # no ledger code among the blockers
        assert [d["code"] for d in first["ledger"]] == ["ledger_entry_malformed", "ledger_entry_malformed"]
        message = adapter.messages[1]
        issues_part = message[message.index("failed validation with these issues"):message.index(prompt.LEDGER_HINTS_HEADING)]
        assert "anchor_not_in_passage" in issues_part and "excluded_sources" not in issues_part
        hints = hint_block(message)
        assert "excluded_sources/0" in hints and "names a source the answer cites" in hints
        assert "srv_S0000003 is given but neither cited nor listed" in hints  # in the handles the model was shown
        record = ledger(answer)  # computed on the repaired draft
        assert record["complete"] is True and record["split"] == [] and record["dropped"] == []
    finally:
        store.conn.close()


def outcome(store, answer, adapter):
    validation = json.loads(answer["validation_json"])
    return (answer["status"], len(adapter.calls), validation.get("extra_repair"), validation.get("issues"),
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


def test_d249_runs_exactly_as_without_a_ledger_when_only_the_several_sources_rule_is_left(tmp_path):
    results = run_both(tmp_path, lambda led: [lambda si, s=s: draft(si, SHAPES[s], ledger=led) for s in ("several", "several", "split")])
    try:
        assert results["clean"][0] == results["broken"][0]
        status, calls, extra, _, codes, labels = results["broken"][0]
        assert (status, calls, extra) == ("structurally_valid", 3, {"labels": ["c2"], "outcome": "published"})
        assert codes == [["source_stated_several_sources"]] * 2 + [[]] and labels == ["c1", "c2", "c3"]
        assert prompt.LEDGER_HINTS_HEADING in results["broken"][3].messages[2]  # the extra repair carries the hints
        broken = ledger(results["broken"][2])
        assert broken["unaccounted"] == [given(results["broken"][1], results["broken"][2])[2]]
        assert ledger(results["clean"][2])["complete"] is True
    finally:
        for result in results.values():
            result[1].conn.close()


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


def test_a_resumed_repair_rebuilds_the_same_hints_from_the_stored_failed_output(tmp_path):
    bad = lambda si: draft(si, SHAPES["one"], ledger=BROKEN, quote="SYNTHETIC words that no passage contains anywhere.")
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [bad, lambda si: draft(si, SHAPES["one"])])
    try:
        stopped = []

        def stop(si):
            if len(adapter.calls) == 2 and not stopped:
                stopped.append(1)
                raise RuntimeError("stopped while the repair was out")
        adapter.before = stop
        with pytest.raises(Exception):
            answer_of(store, rid, flow, run_id)
        step = store.existing_step(run_id, "grounded_answer")
        assert flow._answer_repair_state(step["id"], None, 1)[2:] == (1, False)  # one failed attempt, no cap reached
        answer = answer_of(store, rid, flow, run_id)
        assert len(adapter.calls) == 3 and answer["status"] == "structurally_valid"
        assert hint_block(adapter.messages[2]) == hint_block(adapter.messages[1])
        assert {i["code"] for i in sessions(store)[0]["issues"]} == {"anchor_not_in_passage"}
    finally:
        store.conn.close()


NULL_LEDGER = lambda si, shape: draft(si, SHAPES[shape], ledger=None)
SCALAR_LEDGER = lambda si, shape: draft(si, SHAPES[shape], ledger=lambda order: ["x", entry(order[2]["source_id"])])


@pytest.mark.parametrize("stop", [False, True])
@pytest.mark.parametrize("case", ["resplit", "rewrite_published", "first_kept"])
def test_the_saved_ledger_reads_the_split_of_the_output_that_is_saved(tmp_path, case, stop):
    shapes = {"resplit": ["several", "several", "split"], "rewrite_published": ["inference", "rewritten"],
              "first_kept": ["inference", "inference"]}[case]
    # Every attempt but the last has a null ledger; the last one has a scalar item. The saved output decides which shows.
    scripts = [lambda si, s=s: NULL_LEDGER(si, s) for s in shapes[:-1]] + [lambda si: SCALAR_LEDGER(si, shapes[-1])]
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, scripts)
    try:
        if stop:
            save_fails_once(store)
            with pytest.raises(RuntimeError):
                answer_of(store, rid, flow, run_id)
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(sent) == len(shapes)  # a resume sends nothing again
        validation = json.loads(answer["validation_json"])
        if case == "resplit":
            assert validation["extra_repair"]["outcome"] == "published"
        else:
            assert validation["inference_cap"]["outcome"] == ("published" if case == "rewrite_published" else "kept_first")
        expected = ["ledger_field_malformed"] if case == "first_kept" else ["ledger_entry_malformed"]
        record = ledger(answer)
        assert [d["code"] for d in record["split"]] == expected
        key = {"resplit": RESPLIT_KEY, "rewrite_published": INFERENCE_CAP_KEY, "first_kept": "grounded_answer"}[case]
        assert record["split"] == store.existing_step(run_id, key)["output"]["ledger_split"]
        ids = given(store, answer)
        if case != "first_kept":
            assert [e["source_id"] for e in record["excluded"]] == [ids[2]] and record["complete"] is True
        else:
            assert record["excluded"] == [] and record["unaccounted"] == [ids[2]]
        assert answer_of(store, rid, flow, run_id)["validation_json"] == answer["validation_json"]
    finally:
        store.conn.close()


@pytest.mark.parametrize("value, expected", [
    (MISSING, ["ledger_field_malformed"]),
    (None, ["ledger_field_malformed"]),
    ("srv_S0000002", ["ledger_field_malformed"]),
    ([1, "srv_S0000002", None], ["ledger_entry_malformed"] * 3),
    (lambda order: [entry([order[1]["source_id"]])], ["ledger_entry_malformed"]),
    (lambda order: [entry(order[1]["source_id"], "different_conditions", passage_id={"p": order[1]["passage_id"]},
                          quote="SYNTHETIC second passage")], ["ledger_entry_malformed"]),
    (lambda order: [entry(order[1]["source_id"], "same_finding_as_cited", passage_id=order[1]["passage_id"],
                          quote="SYNTHETIC second passage", same_as_source_id=[order[0]["source_id"]])], ["ledger_entry_malformed"]),
])
def test_malformed_ledgers_through_the_whole_pipeline_never_stop_the_answer(tmp_path, value, expected):
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [lambda si: draft(si, SHAPES["one"], ledger=value)])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(adapter.calls) == 1
        record = ledger(answer)
        assert [d["code"] for d in record["split"]] == expected and record["excluded"] == []
        ids = given(store, answer)
        assert record["cited"] == [ids[0]] and record["unaccounted"] == ids[1:]
        assert sessions(store)[0]["ledger"] == record["split"]
    finally:
        store.conn.close()


def test_split_diagnostics_survive_the_anchor_salvage(tmp_path):
    def salvaged(si):
        out = draft(si, SHAPES["one"], ledger=lambda order: [{"source_id": order[1]["source_id"]}, entry(order[2]["source_id"])])
        out["citation_anchors"].append(dict(out["citation_anchors"][0], quote="SYNTHETIC words that no passage contains anywhere."))
        return out
    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [salvaged])
    try:
        answer = answer_of(store, rid, flow, run_id)
        assert answer["status"] == "structurally_valid" and len(adapter.calls) == 1
        (session,) = sessions(store)
        assert session["ok"] is True and any(w["code"] == "citation_anchor_salvaged" for w in session["warnings"])
        assert [d["path"] for d in session["ledger"]] == ["/excluded_sources/0"]
        record = ledger(answer)
        assert record["split"] == session["ledger"] and record["unaccounted"] == [given(store, answer)[1]]
    finally:
        store.conn.close()


def test_the_view_names_left_out_works_from_their_records_and_null_for_an_answer_without_a_ledger(tmp_path):
    from deixis.workflow import views

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


def test_a_stored_ledger_of_the_wrong_shape_or_with_counts_that_do_not_add_up_is_not_shown(tmp_path):
    from deixis.workflow import views

    store, flow, adapter, rid, run_id, sent = setup(tmp_path, [lambda si: draft(si, SHAPES["one"])])
    try:
        answer = answer_of(store, rid, flow, run_id)
        good = ledger(answer)
        a, b, c = good["given"]
        broken = [
            {"given": [a]},  # lists missing
            good | {"excluded": None},
            good | {"excluded": [{"source_id": b}]},  # entry without reason or note
            good | {"excluded": [good["excluded"][0] | {"reason": "made_up"}, good["excluded"][1]]},
            good | {"cited": [a, b]},  # b both cited and excluded
            good | {"excluded": good["excluded"][:1]},  # c given but in no bucket
            good | {"complete": "yes"},
            good | {"excluded": [good["excluded"][0] | {"reason": []}, good["excluded"][1]]},
            good | {"excluded": [good["excluded"][0] | {"reason": {}}, good["excluded"][1]]},
            good | {"excluded": [good["excluded"][0] | {"anchor_text": "SYNTHETIC located words", "passage_id": None}, good["excluded"][1]]},
            "not a ledger",
        ]
        for value in broken:
            store.conn.execute("UPDATE answers SET validation_json = json_set(validation_json, '$.evidence_ledger', json(?)) WHERE id = ?",
                               (json.dumps(value), answer["id"]))
            assert views.research_view(store, rid)["answers"][0]["evidence_ledger"] is None, value
        store.conn.execute("UPDATE answers SET validation_json = json_set(validation_json, '$.evidence_ledger', json(?)) WHERE id = ?",
                           (json.dumps(good), answer["id"]))
        shown = views.research_view(store, rid)["answers"][0]["evidence_ledger"]
        assert shown["cited"] == [a] and [e["source_version_id"] for e in shown["excluded"]] == [b, c]
    finally:
        store.conn.close()

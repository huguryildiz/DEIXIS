"""Which answers a second model reads, decided by code and frozen when the answer is saved."""

import asyncio
import json

import pytest
from deixis.models import family
from deixis.runtime.config import Settings
from deixis.workflow.answer import review_trigger
from deixis.workflow.features.report import report_pipeline
from deixis.workflow.features.review.review_store import ReviewStore
from deixis.workflow.run import views
from fakes import FakeAdapter, reviewable, valid_response
from review_helpers import review_run
from test_fast_path_answer import answer_run, cutoff, inspected_pdf, reviewed, setup


def draft(text="A plain sentence with no comparison.", passage_ids=("psg_1",), limitation="scope"):
    return {"claims": [{"claim_label": "c1", "text": text, "passage_ids": list(passage_ids)}],
            "limitations": [{"kind": limitation, "text": "SYNTHETIC", "source_ids": []}]}


def test_the_conditions_are_read_from_the_draft_alone():
    abstract, page = {"psg_1": "abstract"}, {"psg_1": "pdf_page"}
    # A quantity needs a direction beside it: a share of something is not a comparison.
    assert review_trigger.fired(draft("20 % of the works report it."), page) == ()
    assert review_trigger.fired(draft("It is 20 % higher than the baseline."), page) == ("numeric_comparison",)
    assert review_trigger.fired(draft("Taban yönteme göre 1.4 kat daha hızlıdır."), page) == ("numeric_comparison",)
    # One number given against another is a comparison even with no comparative word between them.
    assert review_trigger.fired(draft("Accuracy increased from 70 % to 80 %."), page) == ("numeric_comparison",)
    # A word of change carries the comparison in any form; the other quantity need not be written out.
    assert review_trigger.fired(draft("Accuracy improved 10 % over the baseline."), page) == ("numeric_comparison",)
    assert review_trigger.fired(draft("It showed a 10 % improvement."), page) == ("numeric_comparison",)
    # Every cited passage an abstract: the detail may be beyond what an abstract states.
    assert review_trigger.fired(draft(), abstract) == ("abstract_only_support",)
    assert review_trigger.fired(draft(passage_ids=("psg_1", "psg_2")), abstract | {"psg_2": "pdf_page"}) == ()
    # A passage whose depth is unknown leaves the claim out: "all of them are abstracts" cannot be established.
    assert review_trigger.fired(draft(), {}) == ()
    assert review_trigger.fired(draft(limitation="conflicting_evidence"), page) == ("conflicting_evidence",)
    # The order is the rule's, not the draft's, and an answer with nothing to check is never sent.
    both = review_trigger.fired(draft("It is 20 % higher.", limitation="conflicting_evidence"), abstract)
    assert both == ("numeric_comparison", "conflicting_evidence", "abstract_only_support")
    assert review_trigger.fired({"claims": []}, abstract) == ()


def test_the_model_family_comes_from_the_model_id_not_the_connection():
    assert family.family("anthropic/claude-sonnet-4") == "anthropic"
    assert family.family("gpt-5.1-mini") == "openai"
    assert family.family("SYNTHETIC-unlisted-model") is None
    assert family.separate_family("gpt-5.1", "claude-sonnet-4") == family.SEPARATE
    assert family.separate_family("gpt-5.1", "openai/gpt-4.1") == family.SAME
    # One connection can serve several makers, so an id nobody can place is not evidence of a separate family.
    assert family.separate_family("gpt-5.1", "SYNTHETIC-unlisted-model") == family.UNKNOWN


def test_an_answer_meeting_no_condition_is_not_read_again_and_still_gets_its_table(tmp_path, monkeypatch):
    lib = setup(tmp_path, pdf=True)
    inspected_pdf(lib)
    lib.store.set_setting("reviewer", {"model_connection": "fake", "model": "fake-model", "reasoning_effort": None})
    lib.flow.deps.settings = Settings(data_dir=tmp_path / "data", study_table="auto")

    def plain(si):
        """An answer with no comparison, resting on a full-text page: it meets none of the conditions."""
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        page = next(p for p in si["passages"] if p["locator"]["kind"] == "pdf_page")
        draft = json.loads(valid_response(si))
        draft["claims"][0]["passage_ids"] = [page["passage_id"]]
        draft["citation_anchors"] = [{"claim_label": "c1", "passage_id": page["passage_id"], "quote": page["text"][:300]}]
        return json.dumps(draft)

    lib.flow.deps.adapters["fake"] = FakeAdapter(plain)
    cutoff(lib)
    run = answer_run(lib)
    chained = []
    monkeypatch.setattr(report_pipeline, "after_answer", lambda store, original: chained.append(original["id"]))
    asyncio.run(lib.flow.execute(run["id"]))
    answer = views.research_view(lib.store, lib.rid)["answers"][0]
    assert lib.store.review_decision(answer["id"])["decision"] == "not_triggered"
    assert lib.store.next_queued_run() is None  # no reading is opened
    assert chained == [run["id"]]  # and the study table follows the answer run instead
    assert answer["review_status"]["state"] == "not_triggered"


def test_a_reviewer_changed_after_the_answer_was_saved_does_not_move_that_answer(tmp_path):
    lib = reviewed(setup(tmp_path))
    lib.flow.deps.adapters["fake"] = FakeAdapter(reviewable, models=["fake-model", "other-model"])
    cutoff(lib)
    asyncio.run(lib.flow.execute(answer_run(lib)["id"]))
    answer_id = lib.store.conn.execute("SELECT id FROM answers").fetchone()[0]
    assert lib.store.review_decision(answer_id)["reviewer_model"] == "fake-model"
    lib.store.set_setting("reviewer", {"model_connection": "fake", "model": "other-model", "reasoning_effort": None})
    # A reading opened but not run yet is waiting, never "no reading": the answer run completed and queued it.
    assert views.research_view(lib.store, lib.rid)["answers"][0]["review_status"]["state"] == "queued"
    review = lib.store.next_queued_run()
    lib.store.update_run(review["id"], status="running")
    asyncio.run(lib.flow.execute(review["id"]))
    sent = lib.store.conn.execute("SELECT requested_model FROM model_sessions WHERE run_id = ?", (review["id"],)).fetchone()
    assert sent[0] == "fake-model"  # the frozen reviewer, not the one the setting now names


def test_a_decision_is_not_changed_or_removed_without_a_purge_authorization(tmp_path):
    lib = reviewed(setup(tmp_path))
    cutoff(lib)
    asyncio.run(lib.flow.execute(answer_run(lib)["id"]))
    answer_id = lib.store.conn.execute("SELECT id FROM answers").fetchone()[0]
    with pytest.raises(Exception, match="immutable"):
        lib.store.conn.execute("UPDATE answer_review_decisions SET decision = 'not_triggered' WHERE answer_id = ?", (answer_id,))
    with pytest.raises(Exception, match="purge authorization"):
        lib.store.conn.execute("DELETE FROM answer_review_decisions WHERE answer_id = ?", (answer_id,))
    lib.store.update_run(lib.store.next_queued_run()["id"], status="cancelled")
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    assert lib.store.conn.execute("SELECT COUNT(*) FROM answer_review_decisions").fetchone()[0] == 0


def test_the_persons_own_request_is_recorded_beside_the_decisions_code_makes(tmp_path):
    lib = reviewed(setup(tmp_path))
    cutoff(lib)
    asyncio.run(lib.flow.execute(answer_run(lib)["id"]))
    answer_id = lib.store.conn.execute("SELECT id FROM answers").fetchone()[0]
    reviews = ReviewStore(lib.store.conn)
    snapshot = reviews.add_snapshot({"research_id": lib.rid, "target_kind": "answer", "target_id": answer_id,
                                     "sections": []}, {})
    run_id = review_run({"conn": lib.store.conn, "rid": lib.rid})
    reviews.create_review(lib.rid, snapshot, run_id, focus="source_support", requested_connection="fake",
                          requested_model="other-model")
    row = lib.store.conn.execute(
        "SELECT triggers, decision, reviewer_model FROM answer_review_decisions WHERE occasion = 'person'").fetchone()
    assert json.loads(row[0]) == ["person_asked"] and row[1] == "review" and row[2] == "other-model"
    # The automatic decision for the same answer stays as it was: the two are separate records.
    assert lib.store.review_decision(answer_id)["triggers"] == ["numeric_comparison", "abstract_only_support"]
    # The automatic state speaks for the automatic reading alone, and says the person asked for one of their own.
    assert views.research_view(lib.store, lib.rid)["answers"][0]["review_status"]["person_requested"] is True

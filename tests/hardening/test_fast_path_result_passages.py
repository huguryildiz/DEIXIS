"""D84: a full-text source's most result-dense page takes its first answer-input slot when the research names outcomes."""

import asyncio

import pytest

import test_fast_path_answer
from deixis.workflow import fast_answer
from test_fast_path_answer import answer_run, cutoff, inspected_pdf, setup
from test_criterion_passage_flow import QUESTION, TOPIC_PAGE, page_source
from test_fast_path_formula_passages import FORMULA_PAGE

OUTCOME = "cancer related fatigue"
# Reports the outcome against two comparators; carries fewer question words than the topic page, so it ranks last.
RESULT_PAGE = "SYNTHETIC cancer related fatigue was 20% lower than usual care and 15% lower than stretching."


def vocabulary(store, run_id, outcome_terms):
    step = store.step(run_id, "vocabulary", "code:vocabulary")
    store.finish_step(step["id"], "succeeded", output={"vocabulary": {"terms": [], "outcome_terms": outcome_terms}})


def pdf_plan(tmp_path, monkeypatch, outcome_terms, pages, question=QUESTION):
    monkeypatch.setattr(test_fast_path_answer, "page_source",
                        lambda store, rid, name, _pages, *a, **k: page_source(store, rid, name, pages, *a, **k))
    lib = setup(tmp_path, pdf=True)
    lib.store.conn.execute("UPDATE scope_revisions SET question = ? WHERE research_id = ?", (question, lib.rid))
    if outcome_terms is not None:
        vocabulary(lib.store, lib.discovery["id"], outcome_terms)
    inspected_pdf(lib)
    cutoff(lib)
    plan = fast_answer.input_plan(lib.flow, answer_run(lib), lib.store.scope(lib.rid))
    order = [lib.store.passage(pid)["physical_page"] for pid in plan["passage_ids"]
             if lib.store.passage(pid)["kind"] == "pdf_page"]
    return order, plan["result_passages"]


def test_result_page_takes_the_first_slot_only_when_the_research_names_outcomes(tmp_path, monkeypatch):
    pages = [TOPIC_PAGE, TOPIC_PAGE, RESULT_PAGE]
    plain, off = pdf_plan(tmp_path / "plain", monkeypatch, None, pages)
    empty, none = pdf_plan(tmp_path / "empty", monkeypatch, [], pages)
    named, on = pdf_plan(tmp_path / "named", monkeypatch, [OUTCOME], pages)
    # Pages 1 and 2 carry the same text, so their order follows passage identifiers, which differ per library.
    assert plain[2] == empty[2] == 3
    assert named[0] == 3 and sorted(named) == [1, 2, 3]
    assert (off["on"], off["outcome_terms"], off["moved"]) == (False, [], 0) and none == off
    assert (on["on"], on["outcome_terms"], on["moved"], on["min_score"]) == (True, [OUTCOME], 1, 2)


def test_formula_page_stays_second_behind_the_result_page(tmp_path, monkeypatch):
    question = QUESTION + " Which equations apply?"
    order, record = pdf_plan(tmp_path, monkeypatch, [OUTCOME], [TOPIC_PAGE, FORMULA_PAGE, TOPIC_PAGE, RESULT_PAGE], question)
    assert order[:2] == [4, 2] and record["moved"] == 1


def test_a_page_below_the_floor_leaves_the_order(tmp_path, monkeypatch):
    weak = "SYNTHETIC cancer related fatigue was 20% lower than usual care."
    plain, _ = pdf_plan(tmp_path / "plain", monkeypatch, None, [TOPIC_PAGE, TOPIC_PAGE, weak])
    named, record = pdf_plan(tmp_path / "named", monkeypatch, [OUTCOME], [TOPIC_PAGE, TOPIC_PAGE, weak])
    assert named[2] == plain[2] == 3 and record["moved"] == 0


@pytest.mark.parametrize("code, given", [("runs_agree_candidate", 2), ("abstract_not_found", 1)])
def test_late_full_text_puts_its_result_page_first(tmp_path, monkeypatch, code, given):
    """A base work's late full text gets two pages, a new work's one (`late_revision.BASE_WORK_PAGES`, `NEW_WORK_PAGES`);
    the result page is among them either way."""
    import test_criterion_passage_flow
    from test_fast_path_late_revision import prepared, read_late, row
    from deixis.workflow import late_revision
    monkeypatch.setattr(test_fast_path_answer, "library",
                        lambda path, **k: test_criterion_passage_flow.library(path, question=QUESTION, **k))
    monkeypatch.setattr(test_fast_path_answer, "page_source",
                        lambda store, rid, name, pages, *a, **k: page_source(store, rid, name, [*pages[:2], RESULT_PAGE], *a, **k))
    original = test_fast_path_answer.setup

    def with_vocabulary(*args, **kwargs):
        lib = original(*args, **kwargs)
        vocabulary(lib.store, lib.discovery["id"], [OUTCOME])
        return lib
    monkeypatch.setattr("test_fast_path_late_revision.setup", with_vocabulary)
    lib = prepared(tmp_path, last_code=code)
    read_late(lib)
    late_revision.advance(lib.flow, lib.rid)
    revision = lib.store.run(row(lib)["answer_run_id"])
    lib.store.update_run(revision["id"], status="running")
    asyncio.run(lib.flow.execute(revision["id"]))
    plan = lib.store.existing_step(revision["id"], late_revision.REVISION_INPUT)["output"]
    upgraded = next(i for i in plan["items"] if i.get("upgraded"))
    pages = [lib.store.passage(pid)["physical_page"] for pid in upgraded["passage_ids"]]
    assert len(pages) == given and pages[0] == 3
    assert plan["result_passages"]["on"] and plan["result_passages"]["outcome_terms"] == [OUTCOME]
    assert plan["result_passages"]["moved"] == 1

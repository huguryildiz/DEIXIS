"""D56: a formula question brings each full-text source's most formula-dense page into the answer input."""

import asyncio

import pytest

import test_fast_path_answer
from deixis.workflow import answer as fast_answer
from test_fast_path_answer import answer_run, cutoff, inspected_pdf, setup
from test_criterion_passage_flow import TOPIC_PAGE, page_source

FORMULA_PAGE = (TOPIC_PAGE + " The holding time is defined as f(d) = 2τ / δ · (R − d), δ ∈ (0, R], where τ = R / v0"
                " is the propagation delay (4).")


def pdf_pages(tmp_path, question, monkeypatch):
    # The PDF's third page carries the formula; the other two are topic pages as in `setup`.
    monkeypatch.setattr(test_fast_path_answer, "page_source",
                        lambda store, rid, name, pages, *a, **k: page_source(store, rid, name, [*pages[:2], FORMULA_PAGE], *a, **k))
    lib = setup(tmp_path, pdf=True)
    lib.store.conn.execute("UPDATE scope_revisions SET question = ? WHERE research_id = ?", (question, lib.rid))
    inspected_pdf(lib)
    cutoff(lib)
    plan = fast_answer.input_plan(lib.flow, answer_run(lib), lib.store.scope(lib.rid))
    pages = [lib.store.passage(pid)["physical_page"] for pid in plan["passage_ids"]
             if lib.store.passage(pid)["kind"] == "pdf_page"]
    return pages, plan["formula_passages"]


def test_formula_question_puts_the_formula_page_second(tmp_path, monkeypatch):
    plain, off = pdf_pages(tmp_path / "plain", "Does supervised exercise lower cancer related fatigue?", monkeypatch)
    # Same topic words; "equations" is on no page, so only the formula rule can change the order.
    asked, on = pdf_pages(tmp_path / "asked", "Does supervised exercise lower cancer related fatigue, and which equations"
                          " apply?", monkeypatch)
    assert (off["on"], off["reason"], on["on"], on["reason"]) == (False, "not_asked", True, "asked")
    assert sorted(plain) == sorted(asked) == [1, 2, 3]
    # Pages 1 and 2 carry the same text, so their order follows passage identifiers, which differ per library.
    assert plain[2] == 3 and asked[1] == 3 and {asked[0], asked[2]} == {1, 2}


@pytest.mark.parametrize("question, reason", [
    ("Egzersiz yorgunluğu azaltır mı? Hangi formüller kullanılır?", "no_english_question"),
])
def test_question_in_another_language_without_english_sentence_leaves_order(tmp_path, monkeypatch, question, reason):
    pages, state = pdf_pages(tmp_path, question, monkeypatch)
    assert (state["on"], state["reason"]) == (False, reason) and pages[2] == 3


@pytest.mark.parametrize("asks", [True, False])
def test_late_full_text_of_a_base_work_brings_its_formula_page_forward(tmp_path, monkeypatch, asks):
    import test_criterion_passage_flow
    from test_fast_path_late_revision import prepared, read_late, row
    from deixis.workflow import late_revision
    question = test_criterion_passage_flow.QUESTION + (" Which equations apply?" if asks else "")
    monkeypatch.setattr(test_fast_path_answer, "library",
                        lambda path, **k: test_criterion_passage_flow.library(path, question=question, **k))
    monkeypatch.setattr(test_fast_path_answer, "page_source",
                        lambda store, rid, name, pages, *a, **k: page_source(store, rid, name, [*pages[:2], FORMULA_PAGE], *a, **k))
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow, lib.rid)
    revision = lib.store.run(row(lib)["answer_run_id"])
    lib.store.update_run(revision["id"], status="running")
    asyncio.run(lib.flow.execute(revision["id"]))
    plan = lib.store.existing_step(revision["id"], late_revision.REVISION_INPUT)["output"]
    upgraded = next(i for i in plan["items"] if i.get("upgraded"))
    pages = [lib.store.passage(pid)["physical_page"] for pid in upgraded["passage_ids"]]
    assert plan["formula_passages"]["on"] is asks and len(pages) == 2
    assert (3 in pages) is asks

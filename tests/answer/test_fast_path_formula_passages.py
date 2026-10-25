"""D56: a formula question brings each full-text source's most formula-dense page into the answer input."""

import asyncio
import pytest
import test_fast_path_answer
from deixis.workflow.answer import answer as fast_answer
from test_fast_path_answer import answer_run, cutoff, inspected_pdf, setup
from test_criterion_passage_flow import TOPIC_PAGE, page_source
from test_criterion_passage_flow import QUESTION, TOPIC_PAGE, page_source
from deixis.workflow.answer import formula_passages as fp
from deixis.workflow.answer import result_passages as rp


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


@pytest.mark.parametrize("asks", [True])
def test_late_full_text_of_a_base_work_brings_its_formula_page_forward(tmp_path, monkeypatch, asks):
    import test_criterion_passage_flow
    from test_fast_path_late_revision import prepared, read_late, row
    from deixis.workflow.answer import late_revision
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


def passage(pid, text):
    return {"id": pid, "text": text}


DBR_P8 = ("Instead, we use a global parameter δ to replace (d1 −d2) for the holding time calculation. Therefore "
          "α = −2τ / δ. Let the node with the minimal depth have holding time 0. We can compute β by solving the "
          "following equation: −2τ / δ R + β = 0. f(d) = 2τ / δ · (R −d), δ ∈(0, R]. (4)")


RESULTS = "Packet Delivery Ratio is defined as the ratio of the number of distinct packets received at the sinks."


FIGURE = "(a) Packet delivery ratio (b) Energy consumption (c) Average end-to-end delay. Fig. 7. DBR's performance"


def test_nothing_moves_without_a_formula_or_when_the_first_passage_is_the_formula():
    prose = [passage("a", RESULTS), passage("b", FIGURE), passage("c", "α is a parameter")]
    assert fp.bring_forward(prose) == prose
    first = [passage("p8", DBR_P8), passage("p10", RESULTS), passage("p9", DBR_P8)]
    assert fp.bring_forward(first) == first
    assert fp.bring_forward(first[:1]) == first[:1]


def test_reported_values_and_units_are_not_formulas():
    statistics = "SD = 7.1; n = 120; OR = 1.4 (95% CI 1.1-1.8), p = 0.02, p = .03; HR = 0.8; PDR = 0.92; 5 µJ, 2 µs"
    assert fp.score(statistics) == 0
    assert fp.score("Ω = Φ + Γ") == 4


OUTCOMES = rp.compile_terms(["packet delivery ratio", "energy consumption"])


# DVOR page 7 (psg_jUAnJnPb5AFpzeZJUA3f on the K copy, 17 Oct 2026): the simulation setup. It names energy consumption
# and carries a dozen numbers with units, none of them a reported outcome.


RESULT = ("The proposed protocol gains 7% higher packet delivery ratio and 25% lower energy consumption than VBF. "
          "Energy consumption is reduced by up to 30%.")


REFERENCES = ("[12] H. Yan, Z. Shi, and J. Cui, DBR, vol. 4982, pp. 72-86. [13] P. Xie et al., VBF, pp. 1216-1221. "
              "[14] N. Chirdchoo et al., Sector-based routing, vol. 5, pp. 1-6.")


def test_reported_outcome_values_count():
    assert rp.score("Table 3 shows energy consumption decreased from 12 J to 8 J.", OUTCOMES) == 2
    assert rp.score(RESULT, OUTCOMES) == 3
    assert rp.score("The packet delivery ratio is 4 percent higher than in DBR.", OUTCOMES) == 1
    # A range or a ± value is one reported value.
    assert rp.score("Energy consumption is 15 J–60 J lower than HH-VBF and 0.8 ± 0.1 mJ lower than VBF.", OUTCOMES) == 2
    assert rp.score("Energy consumption was 3 to 5 J lower than DBR.", OUTCOMES) == 1


def test_setting_values_and_values_without_an_outcome_term_or_comparison_do_not_count():
    assert rp.score("The initial energy is 10 J, so energy consumption is lower than 10 J.", OUTCOMES) == 0
    assert rp.score("Simulation parameters: energy consumption per bit is set to 2 W, lower than in [5].", OUTCOMES) == 0
    assert rp.score("Nodes are deployed in an area of 500 m, where energy consumption is higher than 5 J.", OUTCOMES) == 0
    assert rp.score("Throughput is 20% higher and delay 30 ms lower than VBF.", OUTCOMES) == 0  # no outcome term
    assert rp.score("Energy consumption was 12 J and 8 J.", OUTCOMES) == 0  # no change or comparison word
    assert rp.score(RESULT, []) == 0


# Every counterexample found in review (Sol code review rounds 1-3) and the cases they must not break.
MERGED = "Energy consumption can be reduced by optimizing routing. 500 m × 500 m × 500 m is the simulated volume."



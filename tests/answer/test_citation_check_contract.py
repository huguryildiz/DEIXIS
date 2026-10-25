"""Verify Citations V3 (D99): the citation_check schema, its StepInput target, the semantic checks and the method text.
Inputs and outputs are SYNTHETIC and hand-written; passing shows the checks hold in code, not that a model follows them."""

import copy
import json
from pathlib import Path
import pytest
from deixis.domain import contracts, skill
from deixis.domain.contracts import locate_anchor, quote_meaning_differs
from deixis.paths import SKILL_DIR
from deixis.domain.citation_check import MAX_PARTS, PartAssessment as P, check_outcome, derive_result, CouldNotCheck
from deixis.documents import draft_parse, pdf
from deixis.domain import contracts
from deixis.domain.contracts import locate_anchor, quote_meaning, quote_meaning_differs
from test_citation_check_run import answer, sentence
from test_citation_check_run import make  # noqa: F401  (fixtures used by name)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"


SI = json.loads((FIXTURES / "step-inputs.json").read_text())["V_citation_check"]


VALID = next(c for c in json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]
             if c["name"] == "citation_check_valid")["output"]


def codes(si, draft):
    return contracts.validate_model_output(si, draft).codes()


def fresh():
    return copy.deepcopy(SI), copy.deepcopy(VALID)


def test_the_task_is_registered_with_its_schema_and_method_file():
    assert contracts.TASK_OUTPUTS["citation_check"] == ("CitationCheck",)
    assert contracts.SCHEMA_VERSIONS["CitationCheck"] == "deixis.citation_check.v1"
    schema = contracts.load_schema("CitationCheck")
    parts = schema["properties"]["parts"]
    assert (parts["minItems"], parts["maxItems"]) == (1, 4)
    evidence = parts["items"]["properties"]["evidence"]
    assert (evidence["minItems"], evidence["maxItems"]) == (0, 3)
    assert parts["items"]["properties"]["assessment"]["enum"] == ["stated", "partly", "not_stated"]
    assert contracts.strict_compatibility_issues(contracts.model_output_schema("citation_check")) == []
    assert contracts.check_step_input(SI) == []
    assert skill.RUNTIME_FILES["citation_check"] == ("SKILL.md", "references/citation-check.md")
    text = " ".join(skill.load_skill_package().runtime_text("citation_check").split())
    for rule in ("Judge only from the given passages.", "`not_stated` is a valid answer",
                 "Text that is merely compatible with the part, or from which the part could be inferred, is not `stated`.",
                 "Do not use the work's title, what you know of the work, or what an abstract hints at"):
        assert rule in text
    assert "| `citation_check` | [citation check](references/citation-check.md) |" in (SKILL_DIR / "SKILL.md").read_text()
    assert skill.integrity_issues() == []
    provenance = json.loads((SKILL_DIR / "provenance.json").read_text())
    entry = next(e for e in provenance["adaptations"] if e["deixis_file"] == "references/citation-check.md")
    assert "D99" in entry["change"] and "tried against no model" in entry["change"]


def test_a_valid_output_has_no_issue_and_more_than_eight_quotes_does():
    si, draft = fresh()
    assert codes(si, draft) == []
    words = ["depth based routing", "raises packet delivery", "in sparse networks"]
    draft["parts"] = [{"text": t, "assessment": "stated", "evidence": [
        {"passage_id": "psg_SYNTHCIT001", "quote": w} for w in words]}
        for t in ("Depth based routing raises packet delivery", "in sparse networks", "and reduces energy use")]
    assert "too_many_quotes" in codes(si, draft)


def test_a_quote_outside_the_given_text_is_not_located():
    """A sentence of the work's text that was not given (another page, or text cut from the plan) is not in the passage."""
    si, draft = fresh()
    draft["parts"][0]["evidence"][0]["quote"] = "depth based routing was tested on page nine in deep water"
    assert codes(si, draft) == ["anchor_not_in_passage"]


def test_a_quote_in_another_given_passage_is_a_hint_never_a_recovery():
    si, draft = fresh()
    draft["parts"][0]["evidence"][0]["passage_id"] = "psg_SYNTHCIT002"
    report = contracts.validate_model_output(si, draft)
    assert report.codes() == ["anchor_not_in_passage"]
    assert "it is in psg_SYNTHCIT001" in report.issues[0].message
    # The stored anchors read the quote only in the passage it names: not located, nothing moved.
    anchors = contracts.citation_check_anchors(si, draft)
    assert anchors[0][0]["passage_id"] == "psg_SYNTHCIT002" and anchors[0][0]["located"] is False
    assert anchors[0][0]["anchor_text"] is None


def test_unknown_and_other_source_passages_are_refused():
    si, draft = fresh()
    draft["parts"][0]["evidence"][0]["passage_id"] = "psg_SYNTHOTHER1"
    assert codes(si, draft) == ["unknown_passage_id"]
    # A passage of another work can never be given: the StepInput itself is refused.
    other = copy.deepcopy(si)
    other["passages"][1]["source_id"] = "srv_SYNTHOTHER1"
    assert "citation_check_passage_not_assessed_work" in {i.code for i in contracts.check_step_input(other)}


@pytest.mark.parametrize("quote, passage, reason", [("the method does not reduce error", "the method does reduce error", "negation"), ("the dose was 5 mg", "the dose was 50 mg", "number"), ("p < 0.05", "p > 0.05 was seen", "comparison")])
def test_a_located_quote_that_differs_in_meaning_is_refused(quote, passage, reason):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None and anchor.kind != "exact"
    assert quote_meaning_differs(quote, passage, anchor) == reason


def test_the_flipped_quote_sends_the_step_to_repair():
    si, draft = fresh()
    draft["parts"][1] = {"text": "reduces energy use", "assessment": "stated", "evidence": [
        {"passage_id": "psg_SYNTHCIT002", "quote": "the protocol does significantly reduce energy use"}]}
    report = contracts.validate_model_output(si, draft)
    assert report.codes() == ["quote_meaning_differs"] and "negation" in report.issues[0].message


def test_handles_are_shown_for_passages_and_the_source_and_read_back_from_the_answer():
    si, draft = fresh()
    shown = contracts.with_citation_handles(si)
    assert shown["citation_check_target"]["assessed_source_id"] == "srv_S0000001"
    assert [p["passage_id"] for p in shown["passages"]] == ["psg_P0000001", "psg_P0000002"]
    draft["parts"][0]["evidence"][0]["passage_id"] = "psg_P0000001"
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert resolved["parts"][0]["evidence"][0]["passage_id"] == "psg_SYNTHCIT001"


def case(sentence, passage, parts):
    si = copy.deepcopy(SI)
    si["citation_check_target"]["sentence"] = sentence
    si["passages"] = si["passages"][:1]
    si["passages"][0]["text"] = passage
    si["allowlist"]["passage_ids"] = [si["passages"][0]["passage_id"]]
    draft = copy.deepcopy(VALID)
    draft["parts"] = [{"text": text, "assessment": "stated",
                       "evidence": [{"passage_id": "psg_SYNTHCIT001", "quote": quote}]} for text, quote in parts]
    return si, draft


@pytest.mark.parametrize("quote, passage, reason", [("power was 5 mW", "power was 5 MW", "unit"), ("x > 5", "x >= 5", "comparison")])
def test_numbers_units_and_operators_are_compared_on_every_match_kind(quote, passage, reason):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) == reason


@pytest.mark.parametrize("quote, passage", [("significantly improve accuracy", "The method does not, in this trial, significantly improve accuracy.")])
def test_a_negation_anywhere_in_the_passage_sentence_refuses_the_quote(quote, passage):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) == "negation"


def reason(parts, covers=True):
    with pytest.raises(CouldNotCheck) as caught:
        derive_result(parts, covers)
    return caught.value.reason


def test_every_part_stated_with_a_located_quote_and_the_whole_sentence_is_found_whole():
    assert derive_result([P("stated", (True,)), P("stated", (False, True))], True) == "found_whole"


def test_a_positive_part_with_no_quote_is_never_turned_into_not_stated():
    assert reason([P("stated", ())]) == "positive_part_quote_count"
    assert reason([P("partly", ()), P("not_stated")]) == "positive_part_quote_count"
    assert check_outcome([P("stated", ())], True) == {"status": "could_not_check", "result": None,
                                                     "error": "positive_part_quote_count"}


def test_a_positive_part_whose_quotes_were_all_rejected_cannot_be_checked():
    assert reason([P("stated", (False, False, False))]) == "positive_part_without_located_quote"
    # One rejected positive part spoils the whole assessment, even beside a valid one.
    assert reason([P("stated", (True,)), P("partly", (False,))]) == "positive_part_without_located_quote"


def test_a_stated_part_and_an_omitted_part_never_give_found_whole():
    # The model listed only part A and said its parts do not cover the sentence (part B left out).
    assert reason([P("stated", (True,))], covers=False) == "sentence_not_covered"
    assert check_outcome([P("stated", (True,))], False)["result"] is None


def test_shape_limits_fail_closed():
    assert reason([]) == "no_parts"
    assert reason([P("not_stated")] * (MAX_PARTS + 1)) == "too_many_parts"
    assert reason([P("stated", (True,) * 4)]) == "positive_part_quote_count"
    assert reason([P("stated", (True,) * 3), P("stated", (True,) * 3), P("stated", (True,) * 3)]) == "too_many_quotes"
    assert reason([P("supported", (True,))]) == "unknown_assessment"
    assert reason([P("stated", ("yes",))]) == "unknown_assessment"
    assert reason([P("not_stated", (True,))]) == "quote_on_not_stated_part"
    assert reason(["stated"]) == "unknown_assessment"


def claims(text):
    draft = draft_parse.parse_draft("tex", text)
    return {m.raw: m for m in draft.markers}, draft


TEX_HEAD = "\\documentclass{article}\n\\newcommand{\\site}{\\multirow{2}{*}{Lab}}\n\\newcommand{\\pair}{A & B}\n"


@pytest.mark.parametrize("table", ["\\begin{tabular}{lll}\nWork & \\pair\\\\\n\\midrule\nX \\cite{x} & \\pair\\\\\n\\end{tabular}"])
def test_a_command_off_the_tabular_allowlist_refuses_the_whole_table(table):
    found, _ = claims(TEX_HEAD + "\\begin{document}\n" + table + "\n\\end{document}\n")
    cited = found[r"\cite{x}"]
    assert (cited.status, cited.targets, cited.claim, cited.reason) == ("unrecognized", [], "",
                                                                       draft_parse.TABLE_LAYOUT_NOT_READ)


def test_a_quote_overlapping_the_placeholder_even_in_part_is_refused():  # SYNTHETIC
    # Sol's repro: a passage that is only the placeholder.
    si, draft = case("The symbols are readable in the PDF", pdf.UNREADABLE,
                     [("The symbols are readable in the PDF", "readable in the PDF")])
    assert "quote_meaning_differs" in codes(si, draft)
    passage = "The map is " + pdf.UNREADABLE + " here."
    for quote in ("The map is [symbols", "PDF] here", "symbols not readable"):
        assert quote_meaning_differs(quote, passage, located(quote, passage)) == "placeholder"


@pytest.mark.parametrize("raw, plain", [(r"Haldar \emph{et al.} learn swap, wait and discard decisions from link ages, with state-dependent cutoffs below the"
     r" maximum~\cite[pp.~13, 15]{haldar2024}~\tP; in multiplexed chains they pair stored links by age, youngest first,"
     r" and charge classical communication time as extra aging~\cite[pp.~4, 5]{haldar2025}~\tP.",
     "Haldar et al. learn swap, wait and discard decisions from link ages, with state-dependent cutoffs below the maximum;"
     " in multiplexed chains they pair stored links by age, youngest first, and charge classical communication time as"
     " extra aging.")])
def test_a_latex_sentence_is_given_as_plain_text_the_same_way_everywhere(raw, plain):
    found, _ = claims("\\begin{document}\n" + raw + "\n\\end{document}")
    assert {m.claim for m in found.values()} == {plain}


def located(quote, passage):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    return anchor


P46 = ("from the respective buffers to avoid overflow. We first observe\nthat there is no benefit to removing a qubit from a"
       " buffer before\nit is full; hence we only consider polices that remove qubits at\nthe time overflow occurs. Second,"
       " we restrict ourselves to work\nconserving policies; those that a")


P47 = ("i, j as possible and to stabilize the system. For now, we assume that there is no limit to the\n\nnumber of EPR"
       " pairs that can be stored in the nodes. Moreover, we assume that a qubit never\n\ndecoheres. These assumptions will"
       " be relaxed in a later section")


P13 = ("work optimized throughput and end-to-end fidelity, yet little attention has been paid to the freshness of"
       " entanglement-the time since a usable Bell pair was last delivered. We introduce the Fidelity-Age (FA) metric")


@pytest.mark.parametrize("quote, passage, part, reason, detail", [("we only consider polices that remove qubits at\nthe time overflow occurs", P46,
     "among work-conserving policies that drop only on overflow", "negation", '"no"'), ("there is no limit to the\n\nnumber of EPR pairs that can be stored in the nodes", P47,
     "with unlimited memory and infinite qubit lifetime", "part_negation", 'the quote holds the negation "no"')])
def test_the_pilots_right_refusals_stay_and_say_what_and_where(quote, passage, part, reason, detail):
    found = quote_meaning(quote, passage, located(quote, passage), part)
    assert found is not None and found[0] == reason and detail in found[1]


def swap(store, passage, text):
    """Passages are immutable: a passage read again is a new row beside the old one's removal, same page and file."""
    with store.conn:
        store.conn.execute("DELETE FROM passages WHERE id = ?", (passage["id"],))
        return store._insert_passage(passage["source_version_id"], passage["asset_id"], passage["kind"],
                                     passage["physical_page"], None, None, passage["payload_ref"],
                                     passage["extraction_version"], text)



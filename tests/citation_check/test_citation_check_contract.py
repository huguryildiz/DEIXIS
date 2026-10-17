"""Verify Citations V3 (D99): the citation_check schema, its StepInput target, the semantic checks and the method text.
Inputs and outputs are SYNTHETIC and hand-written; passing shows the checks hold in code, not that a model follows them."""

import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts, skill
from deixis.domain.contracts import AnchorMatch, locate_anchor, quote_meaning_differs
from deixis.paths import SKILL_DIR

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


def test_a_part_must_be_copied_from_the_sentence():
    si, draft = fresh()
    draft["parts"][0]["text"] = "Routing by depth increases how many packets arrive in sparse networks"
    assert set(codes(si, draft)) == {"part_not_in_sentence", "parts_leave_out_words"}


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


@pytest.mark.parametrize("assessment, evidence, code", [
    ("stated", [], "positive_part_without_quote"),
    ("partly", [], "positive_part_without_quote"),
    ("not_stated", [{"passage_id": "psg_SYNTHCIT001", "quote": "depth based routing"}], "quote_on_not_stated_part"),
])
def test_a_positive_part_needs_a_quote_and_a_not_stated_part_has_none(assessment, evidence, code):
    si, draft = fresh()
    draft["parts"][0] |= {"assessment": assessment, "evidence": evidence}
    assert codes(si, draft) == [code]


def test_coverage_is_declared_and_checked_against_the_sentence_words():
    si, draft = fresh()
    draft["covers_whole_sentence"] = False
    assert codes(si, draft) == ["sentence_not_covered"]
    si, draft = fresh()
    draft["parts"] = draft["parts"][:1]  # "A stated", "B" left out while coverage is declared
    assert codes(si, draft) == ["parts_leave_out_words"]


@pytest.mark.parametrize("quote, passage, reason", [
    ("significantly improves", "the method does not significantly improve the results", "negation"),
    ("the method does not reduce error", "the method does reduce error", "negation"),
    ("the routing method does reduce the error rate in sparse fields",
     "the routing method doesn't reduce the error rate in sparse fields", "negation"),
    ("the routing method manages to reduce the error rate in sparse fields",
     "the routing method fails to reduce the error rate in sparse fields", "negation"),
    ("the dose was 5 mg", "the dose was 50 mg", "number"),
    ("the dose was 5 mg", "the dose was 5 g daily", "unit"),
    ("p < 0.05", "p > 0.05 was seen", "comparison"),
    ("accuracy was higher than the baseline model", "accuracy was lower than the baseline model", "comparison"),
    ("energy use increased in all runs", "energy use decreased in all runs", "comparison"),
])
def test_a_located_quote_that_differs_in_meaning_is_refused(quote, passage, reason):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None and anchor.kind != "exact"
    assert quote_meaning_differs(quote, passage, anchor) == reason


def test_an_exact_quote_cut_after_a_negation_is_refused_and_an_exact_one_kept():
    passage = "In this trial the drug does not significantly improve survival in adults."
    anchor = locate_anchor("significantly improve survival", passage)
    assert anchor.kind == "exact" and quote_meaning_differs("significantly improve survival", passage, anchor) == "negation"
    whole = "the drug does not significantly improve survival"
    assert quote_meaning_differs(whole, passage, locate_anchor(whole, passage)) is None
    # A comma does not end the sentence a negation is read in: a negation anywhere in it refuses the quote (D99 review).
    passage = "It did not converge, but the method improves accuracy by 5 %."
    quote = "the method improves accuracy by 5 %"
    assert quote_meaning_differs(quote, passage, locate_anchor(quote, passage)) == "negation"
    # A negation 80 characters or less after the span refuses it whatever punctuation lies between (review round 3);
    # one farther off is not read, and the quote is kept with its percent sign.
    passage = "The method improves accuracy by 5 %. It does not converge."
    assert quote_meaning_differs(quote, passage, locate_anchor(quote, passage)) == "negation"
    passage = "The method improves accuracy by 5 %. " + "Other runs were made on the larger set. " * 3 + "It does not converge."
    assert quote_meaning_differs(quote, passage, locate_anchor(quote, passage)) is None
    assert quote_meaning_differs("x", "x", AnchorMatch("exact", "x", 1.0)) is None


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


# ---- review round 1 (Sol, 34d65eca): each repro was a wrong `found_whole`; now each is refused for repair.

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


@pytest.mark.parametrize("sentence, kept, left", [
    ("X improves throughput and Y improves throughput.", "X improves throughput", ["Y", "improves", "throughput"]),
    ("The method improves accuracy but not X.", "The method improves accuracy", ["not", "X"]),
])
def test_a_part_left_out_is_found_by_position_not_by_long_words(sentence, kept, left):
    si, draft = case(sentence, f"SYNTHETIC: {kept}.", [(kept, kept)])
    assert contracts.citation_check_spans(sentence, draft["parts"])[1] == left
    assert codes(si, draft) == ["parts_leave_out_words"]
    assert contracts.citation_check_covers(sentence, draft["parts"]) is False


def test_parts_are_spans_in_sentence_order_that_never_overlap_and_only_connectives_lie_between():
    sentence = "X improves throughput and Y improves throughput."
    spans, left = contracts.citation_check_spans(sentence, [{"text": "X improves throughput"},
                                                            {"text": "Y improves throughput"}])
    assert spans == [(0, 3), (4, 7)] and left == []
    assert contracts.citation_check_covers(sentence, [{"text": "Y improves throughput"},
                                                      {"text": "X improves throughput"}]) is False  # out of order
    assert contracts.citation_check_covers(sentence, [{"text": "X improves throughput and Y"},
                                                      {"text": "Y improves throughput"}]) is False  # overlapping
    left = contracts.citation_check_spans("A holds, but B does not hold.", [{"text": "A holds"}, {"text": "B does"}])[1]
    assert left == ["not", "hold"]  # a negation is never a connective


@pytest.mark.parametrize("quote, passage, reason", [
    ("The dose was 5", "The dose was 50 mg", "number"),               # an exact match cut inside a number
    ("the reading was 5 C", "the reading was -5 C", "number"),        # sign
    ("power was 5 mW", "power was 5 MW", "unit"),                     # units are case-sensitive (SI prefixes)
    ("x > 5", "x >= 5", "comparison"),                                # a multi-character operator is one token
    ("x = 5", "x != 5", "comparison"),
    ("the gain is 2.5 dB", "the gain is 25 dB", "number"),            # decimal
    ("The dose was 50", "The dose was 50 mg", "context"),             # the unit right after the span is left out
    ("accuracy was 90", "accuracy was 90 % overall", "context"),      # a percent right after the span
])
def test_numbers_units_and_operators_are_compared_on_every_match_kind(quote, passage, reason):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) == reason


@pytest.mark.parametrize("quote, passage", [
    ("significantly improve accuracy", "The method does not, in this trial, significantly improve accuracy."),
    ("Bu etki istatistiksel olarak anlamlı", "Bu etki istatistiksel olarak anlamlı değil."),
    ("Belirgin bir fark", "Belirgin bir fark yok."),
    ("bir etki gözlendi", "Hiç bir etki gözlendi."),
])
def test_a_negation_anywhere_in_the_passage_sentence_refuses_the_quote(quote, passage):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) == "negation"


def test_the_negation_repro_never_reaches_a_result_and_the_repair_asks_for_the_clause():
    passage = "The method does not, in this trial, significantly improve accuracy."
    si, draft = case("The method significantly improves accuracy.", passage,
                     [("The method significantly improves accuracy", "significantly improve accuracy")])
    report = contracts.validate_model_output(si, draft)
    assert "quote_meaning_differs" in report.codes()
    assert "quote the clause including the negation" in next(i.message for i in report.issues
                                                             if i.code == "quote_meaning_differs")
    assert contracts.citation_check_anchors(si, draft)[0][0]["located"] is False


def test_a_quote_and_its_part_must_agree_on_negation():
    passage = "The method improves accuracy."
    anchor = locate_anchor("The method improves accuracy", passage)
    assert quote_meaning_differs("The method improves accuracy", passage, anchor,
                                 "the method does not improve accuracy") == "part_negation"
    assert quote_meaning_differs("The method improves accuracy", passage, anchor, "the method improves accuracy") is None


# ---- review round 2 (Sol, 95818190): each repro was a wrong `found_whole`; now each is refused for repair.

def test_a_free_standing_sign_or_symbol_is_a_token_for_coverage_and_for_the_quote():
    sentence = passage = "The reading was - 5 C."
    si, draft = case(sentence, passage, [("The reading was", "The reading was"), ("5 C", "5 C")])
    assert contracts.citation_check_spans(sentence, draft["parts"])[1] == ["-"]
    assert "parts_leave_out_words" in codes(si, draft)
    anchor = locate_anchor("The reading was 5 C", passage)
    assert anchor is not None and quote_meaning_differs("The reading was 5 C", passage, anchor) is not None
    si, draft = case(sentence, passage, [("The reading was - 5 C", "The reading was - 5 C")])
    assert codes(si, draft) == []


@pytest.mark.parametrize("text, symbols", [
    ("a − b – c / d × e · f ^ g ² h ³ i ° j % k ± l ~ m ≈ n", list("−–/×·^²³°%±~≈")),
    ("5 mW/cm², 5e-3, 10^6 km/h", ["/", "²", "-", "^", "/"]),
])
def test_every_character_but_letters_digits_and_plain_punctuation_is_its_own_token(text, symbols):
    assert [t.text for t in contracts.check_tokens(text) if t.kind in ("sym", "op")] == symbols


@pytest.mark.parametrize("quote, passage", [
    ("Power was 5 mW", "Power was 5 mW/cm²."),
    ("the rate was 5", "the rate was 5e-3 per run."),
    ("a gain of 10", "a gain of 10^6 overall."),
    ("speed of 40 km", "speed of 40 km/h."),
])
def test_a_span_a_non_space_character_touches_cuts_a_token(quote, passage):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) in ("boundary", "context", "unit")


@pytest.mark.parametrize("passage", [
    "The method does not\nsignificantly improve accuracy.",
    "The method does not, e.g. significantly improve accuracy.",
    "The method does not, e.g. Significantly improve accuracy.",
    "The method did not (see Fig. 3) Significantly improve accuracy.",
    "Gains were not shown by J. R. Significantly improve accuracy.",  # an initial
])
def test_line_breaks_and_abbreviation_dots_never_end_the_negation_sentence(passage):
    quote = ("Significantly" if "Significantly" in passage else "significantly") + " improve accuracy"
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) == "negation"


# ---- review round 3 (Sol, f804d0fc): each repro was a wrong `found_whole`; now each is refused for repair.

@pytest.mark.parametrize("passage", [
    "The method does not, unlike the std. CNN, significantly improve accuracy.",  # an abbreviation and a capital
    "The baseline did not converge. The method significantly improve accuracy.",  # a sure sentence end bounds nothing
])
def test_a_negation_within_the_window_refuses_the_quote_whatever_punctuation_lies_between(passage):
    quote = "significantly improve accuracy"
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) == "negation"


def test_the_negation_window_is_250_characters_before_and_80_after():
    quote = "significantly improve accuracy"
    filler = "x" * 250
    passage = f"It does not {filler} and they significantly improve accuracy."
    assert quote_meaning_differs(quote, passage, locate_anchor(quote, passage)) is None  # 'not' > 250 before
    passage = f"It does not {filler[:200]} and they significantly improve accuracy."
    assert quote_meaning_differs(quote, passage, locate_anchor(quote, passage)) == "negation"


def test_a_fuzzy_match_must_give_the_quote_token_sequence():
    quote, passage = "Power was 5 mW/cm² in the experiment", "Power was 5 mW/mm² in the experiment."
    anchor = locate_anchor(quote, passage)
    assert anchor is not None and anchor.kind == "fuzzy"
    assert quote_meaning_differs(quote, passage, anchor) == "boundary"
    si, draft = case("Power was 5 mW/cm² in the experiment.", passage, [(quote.rstrip("."), quote)])
    assert "quote_meaning_differs" in codes(si, draft)


def test_a_unit_prefix_inside_a_compound_unit_keeps_its_case():
    # Review round 4: `A/mW` and `A/MW` differ by 10^9; the token sequence is compared as written.
    quote, passage = "Responsivity was 5 A/mW in the experiment", "Responsivity was 5 A/MW in the experiment."
    anchor = locate_anchor(quote, passage)
    assert anchor is None or quote_meaning_differs(quote, passage, anchor) is not None
    si, draft = case("Responsivity was 5 A/mW in the experiment.", passage, [(quote, quote)])
    assert "quote_meaning_differs" in codes(si, draft)
    for quote, passage in (("The length was 5 mm here", "The length was 5 Mm here."),
                           ("the method improves accuracy", "The method improves accuracy.")):
        anchor = locate_anchor(quote, passage)
        differs = anchor is None or quote_meaning_differs(quote, passage, anchor) is not None
        assert differs == ("Mm" in passage)  # a sentence-start capital may differ, a unit prefix may not


def test_fuzzy_tolerance_is_left_for_a_word_hyphenated_across_a_line_break():
    quote = "the method significantly improves accuracy"
    passage = "In tests the method signifi-\ncantly improves accuracy."
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    assert quote_meaning_differs(quote, passage, anchor) is None
    passage = "In tests the method signifi- cantly improves accuracy."  # a hyphen with no line break is a token
    anchor = locate_anchor(quote, passage)
    assert anchor is None or quote_meaning_differs(quote, passage, anchor) is not None


def test_the_step_input_target_belongs_to_citation_check_only():
    other = copy.deepcopy(SI)
    del other["citation_check_target"]
    assert "citation_check_target_mismatch" in {i.code for i in contracts.check_step_input(other)}
    answer = json.loads((FIXTURES / "step-inputs.json").read_text())["A_answer"]
    answer["citation_check_target"] = SI["citation_check_target"]
    assert "citation_check_target_mismatch" in {i.code for i in contracts.check_step_input(answer)}
    extra = copy.deepcopy(SI)
    extra["allowlist"]["element_ids"] = []
    assert "citation_check_allowlist_key" in {i.code for i in contracts.check_step_input(extra)}
    empty = copy.deepcopy(SI)
    empty["passages"], empty["allowlist"]["passage_ids"] = [], []
    assert "citation_check_without_text" in {i.code for i in contracts.check_step_input(empty)}

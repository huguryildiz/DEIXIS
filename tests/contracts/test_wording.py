"""Wording checks on answer prose: question language, own-work words and several-sources wording (D43).

The checks are lexical: a pattern match is a finding, not proof that the sentence misattributes anything.
"""

import json
from pathlib import Path

import pytest

from deixis.domain import contracts, wording

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]


def anchored(draft):
    """Re-derive one exact citation anchor per claim-passage link after a test rewrites the claims."""
    text = {p["passage_id"]: " ".join(p["text"].split()) for p in STEP_INPUTS["A_answer"]["passages"]}
    draft["citation_anchors"] = [{"claim_label": c["claim_label"], "passage_id": pid, "quote": text[pid][:600]}
                                 for c in draft["claims"] for pid in c["passage_ids"]]
    return draft


@pytest.mark.parametrize("hint, text, expected", [
    ("tr-TR", "What objective does source A1 optimize?", "tr"),
    ("en", "Kaynak A1 hangi amacı optimize ediyor?", "en"),
    (None, "Kaynak A1 hangi amacı optimize ediyor?", "tr"),
    (None, "What objective does source A1 optimize?", "en"),
])
def test_question_language_follows_the_hint_then_the_question_text(hint, text, expected):
    assert wording.question_language({"question": {"text": text, "language_hint": hint}}) == expected


@pytest.mark.parametrize("phrase", [
    "bu çalışmaların", "Bu çalışmaların", "bu araştırmalarda", "bu makaleler", "bu tezlerde",
    "bu incelemeler", "mevcut çalışmalar", "şimdiki araştırmalar", "Bu makalelerde",
    "Bu tezlerin", "mevcut incelemelerde", "şimdiki tezler",
])
def test_turkish_plural_nouns_do_not_name_the_writers_own_work(phrase):
    assert wording.own_work_phrases(f"{phrase} kapsamı sınırlıdır.", "tr") == []


@pytest.mark.parametrize("phrase", [
    "bu çalışma", "bu çalışmada", "bu çalışmanın", "Bu çalışmada", "Bu makalede",
    "bu makalenin", "bu araştırmada", "Bu araştırmanın", "bu incelemede",
    "mevcut tezde", "şimdiki tezin", "Bu tez",
])
def test_turkish_singular_nouns_with_other_suffixes_name_the_writers_own_work(phrase):
    assert wording.own_work_phrases(f"{phrase} kapsamı sınırlıdır.", "tr") == [phrase]


@pytest.mark.parametrize("text, language", [
    ("This study uses a mixed-integer linear program for release scheduling.", "en"),
    ("Bu çalışma, salım-zamanı çizelgelemesi için karma tamsayılı doğrusal program kullanmaktadır.", "tr"),
])
def test_claim_naming_the_writers_own_work_is_flagged(text, language):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["answer_language"] = language
    draft["claims"] = [dict(draft["claims"][0], text=text)]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    assert report.ok  # phrasing findings are warnings, never a rejection (D19)
    assert [w.path for w in report.warnings if w.code == "own_work_phrase_in_claim"] == ["/claims/0/text"]


@pytest.mark.parametrize("text, language", [
    ("Previous studies have reported that release scheduling is formulated as a mixed-integer linear program.", "en"),
    ("Önceki çalışmalar, röle bakterilerinin sınırlı besin arzını paylaştığını bildirmiştir.", "tr"),
])
def test_several_sources_wording_for_a_one_source_claim_is_flagged(text, language):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["answer_language"] = language
    one = dict(draft["claims"][0], text=text, passage_ids=["psg_SYNA1abs01"])
    two = dict(draft["claims"][0], claim_label="c2", text=text, support_type="analyst_inference",
               passage_ids=["psg_SYNA1abs01", "psg_SYNA3pg002"])
    draft["claims"], draft["limitations"], draft["unanswered_aspects"] = [one, two], [], []
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    assert report.ok and [w.path for w in report.warnings if w.code == "plural_sources_for_one_source"] == ["/claims/0/text"]


def test_latex_math_in_a_claim_reads_as_one_slot_word():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = r"It has been reported that the objective $\min_{x} \sum_{i=1}^{N} P_e(x_i)$ is minimized subject to $\sum_i x_i \le Q$."
    draft["claims"][0]["passage_ids"] = ["psg_SYNA1pg003"]
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    assert report.ok and [w for w in report.warnings if w.path == "/claims/0/text"] == []


def test_malformed_math_fields_are_warnings_not_validation_issues():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = "It has been reported that $x is minimized."
    draft["limitations"][0]["text"] = r"It was not possible to assess $x_{i$; therefore, it is unknown if the index is valid."
    draft["unanswered_aspects"][0] = r"An issue that was not addressed was whether $$\begin{aligned}x=1$$ is intended."
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    warnings = [w for w in report.warnings if w.code == "math_not_well_formed"]
    assert report.ok
    assert [w.path for w in warnings] == ["/claims/0/text", "/limitations/0/text", "/unanswered_aspects/0"]


def test_claim_math_citing_only_an_abstract_is_a_warning_not_an_issue():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = r"It has been reported that $x \le 1$ is required."
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    warnings = [w for w in report.warnings if w.code == "math_without_full_text"]
    assert report.ok and [w.path for w in warnings] == ["/claims/0/text"]

    draft["claims"][0]["passage_ids"] = ["psg_SYNA1pg003"]
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    assert report.ok and [w for w in report.warnings if w.code == "math_without_full_text"] == []


def test_language_without_wording_rules_is_a_warning_not_a_failure():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["answer_language"] = "de"
    draft["claims"][0]["text"] = "Die Quelle formuliert ein gemischt-ganzzahliges Programm."
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok and [w.code for w in report.warnings] == ["phrasing_not_checked"]


@pytest.mark.parametrize("support_type, passage_ids, rejected", [
    ("source_stated", ["psg_SYNA1abs01", "psg_SYNA1pg003"], False),  # two passages of one source
    ("source_stated", ["psg_SYNA1abs01", "psg_SYNA3pg002"], True),
    ("analyst_inference", ["psg_SYNA1abs01", "psg_SYNA3pg002"], False),
])
def test_source_stated_claim_cites_one_source(support_type, passage_ids, rejected):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"] = [dict(draft["claims"][0], support_type=support_type, passage_ids=passage_ids)]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    codes = [(i.code, i.path) for i in report.issues if i.code == "source_stated_several_sources"]
    assert codes == ([("source_stated_several_sources", "/claims/0/passage_ids")] if rejected else [])
    assert report.ok is not rejected


def test_two_versions_of_one_work_count_as_two_sources():
    step_input = json.loads(json.dumps(STEP_INPUTS["A_answer"]))
    # SYNTHETIC: the second passage of SYNA1 now belongs to another version record of the same work.
    next(p for p in step_input["passages"] if p["passage_id"] == "psg_SYNA1pg003")["source_id"] = "srv_SYNA1pre01"
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"] = [dict(draft["claims"][0], support_type="source_stated",
                            passage_ids=["psg_SYNA1abs01", "psg_SYNA1pg003"])]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    report = contracts.validate_model_output(step_input, anchored(draft))
    assert [i.code for i in report.issues] == ["source_stated_several_sources"]


def test_several_sources_defect_is_never_salvaged_with_anchor_defects():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"] = [dict(draft["claims"][0], support_type="source_stated",
                            passage_ids=["psg_SYNA1abs01", "psg_SYNA3pg002"])]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    draft = anchored(draft)
    draft["citation_anchors"].append(dict(draft["citation_anchors"][0]))  # duplicate anchor, salvageable alone
    assert {i.code for i in contracts.validate_model_output(STEP_INPUTS["A_answer"], draft).issues} >= {
        "source_stated_several_sources", "duplicate_citation_anchor"}
    assert contracts.salvage_answer_draft(STEP_INPUTS["A_answer"], draft) == (draft, [])


def test_plain_sentence_without_a_frame_gets_no_warning():
    # D43: answer prose is no longer checked against phrasebank frames.
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["limitations"][1]["text"] = "The published version of A3 was not inspected; the preprint passage may not reflect it."
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok and report.warnings == []


def test_latex_outside_dollar_delimiters_is_a_validation_issue():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = r"The holding time is f(d) = \frac{2\tau}{\delta} \cdot (R - d)."
    draft["claims"][0]["passage_ids"] = ["psg_SYNA1pg003"]
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    assert [i.path for i in report.issues if i.code == "math_without_delimiters"] == ["/claims/0/text"]


@pytest.mark.parametrize("text,flagged", [
    (r"The holding time is \(t_0\) seconds.", True),  # LaTeX's own inline delimiters, which the answer view does not render
    (r"\[ f(d) = R - d \]", True),
    ("CO_{2} rises.", True),
    (r"Its weight is \alpha.", True),
    (r"Its weight is $\alpha$ and the delay $T_{\text{delay}}$.", False),
    ("The node_id field and max_depth value.", False),
    ("10^3 nodes and x^2.", False),
    (r"50\% of nodes and a cost of \$5.", False),
    ("α = p/W + (R − d·cosθ)/R", False),
])
def test_latex_outside_math_forms(text, flagged):
    assert bool(contracts.LATEX_OUTSIDE_MATH.search(contracts.MATH.sub(" ", text))) is flagged

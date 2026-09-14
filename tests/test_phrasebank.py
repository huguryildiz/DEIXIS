"""Academic Phrasebank frames: parsing, per-language rendering and the sentence check on answer prose.

The check is formal: passing shows each sentence keeps most fixed words of one frame in order, not that
the frame suits what the cited passages say.
"""

import json
from pathlib import Path

import pytest

from deixis.domain import contracts, phrasebank
from deixis.domain.skill import load_skill_package

FIXTURES = Path(__file__).parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]
TEXT = load_skill_package().files[phrasebank.PHRASEBANK]

SAMPLE = """Header line.
tr: marks the Turkish rendering.

# Writing Conclusions

## Limitations
It was not possible to assess X; therefore, it is unknown if …
tr: X'i değerlendirmek mümkün olmamıştır; bu nedenle … olup olmadığı bilinmemektedir.
An issue that was not addressed in this study was whether …
"""


def test_render_gives_english_frames_or_turkish_renderings_with_english_fallback():
    english = phrasebank.render(SAMPLE, "en")
    assert "tr:" not in english and "It was not possible to assess X" in english
    turkish = phrasebank.render(SAMPLE, "tr")
    assert "X'i değerlendirmek mümkün olmamıştır" in turkish and "It was not possible" not in turkish
    assert "An issue that was not addressed in this study was whether …" in turkish  # no rendering yet
    assert turkish.index("# Writing Conclusions") < turkish.index("## Limitations")


@pytest.mark.parametrize("hint, text, expected", [
    ("tr-TR", "What objective does source A1 optimize?", "tr"),
    ("en", "Kaynak A1 hangi amacı optimize ediyor?", "en"),
    (None, "Kaynak A1 hangi amacı optimize ediyor?", "tr"),
    (None, "What objective does source A1 optimize?", "en"),
])
def test_frames_language_follows_the_hint_then_the_question_text(hint, text, expected):
    assert phrasebank.frames_language({"question": {"text": text, "language_hint": hint}}) == expected


@pytest.mark.parametrize("sentence", [
    "It has been reported that the release schedule is formulated as a mixed-integer linear program.",
    "In an analysis of release scheduling, Lee et al. (2021) found that the objective minimizes bit error probability.",
    "It was not possible to assess the relay-network formulation; therefore, it is unknown if it uses an optimization model.",
    "An issue that was not addressed in the supplied passages was whether the models were validated.",
    "It is beyond the scope of this answer to examine the published version of A3.",
    "However, these results were based upon an abstract only and it is unclear if the formulation includes a relay budget.",
])
def test_sentence_built_on_a_frame_passes(sentence):
    assert phrasebank.unframed(sentence, TEXT, "en") == []


@pytest.mark.parametrize("sentence", [
    "One source formulates transmitter release-time scheduling as a mixed-integer linear program with binary release variables.",
    "Only the abstract of the relay-network source was available; its formulation is not described.",
    "The model uses binary variables for each release slot and a budget constraint on molecules.",
    "Validation level of the models was not stated in the inspected passages.",
    "The authors propose a heuristic for relay placement that is evaluated by simulation.",
])
def test_free_sentence_sharing_only_common_words_with_frames_fails(sentence):
    # Frames with a near-empty alternative, such as "(However,) {X may cause … | …}", must not pass on one shared word.
    assert phrasebank.unframed(sentence, TEXT, "en") == [sentence]


@pytest.mark.parametrize("sentence, framed", [
    ("Röle konumlarının sezgisel bir yöntemle seçilmiş olduğu bildirilmiştir.", True),
    ("Röle ağının formülasyonunu değerlendirmek mümkün olmamıştır; bu nedenle bir optimizasyon modeli kullanıp kullanmadığı bilinmemektedir.", True),
    ("Yayımlanmış sürümü incelemek bu cevabın kapsamının dışındadır.", True),
    ("Bu bulgular, röle yerleşiminin sezgisel olduğunu düşündürmektedir.", True),
    ("Kaynak, zamanlama problemini karışık tamsayılı doğrusal program olarak kuruyor.", False),
    ("Modelin doğrulama düzeyi incelenen pasajlarda belirtilmemiştir.", False),
])
def test_turkish_sentences_are_checked_against_the_turkish_renderings(sentence, framed):
    assert (phrasebank.unframed(sentence, TEXT, "tr") == []) is framed


@pytest.mark.parametrize("sentence, language", [
    ("An issue that was not addressed in the supplied passages was whether the models were validated.", "en"),
    ("Sağlanan pasajlarda ele alınmayan bir konu, modellerin doğrulanmış olup olmadığıydı.", "tr"),
])
def test_own_work_words_of_a_frame_may_become_the_supplied_passages(sentence, language):
    # Live Turkish run: the check rejected "Sağlanan pasajlarda" and the repair wrote the misattributing "Bu çalışmada".
    assert phrasebank.unframed(sentence, TEXT, language) == []


@pytest.mark.parametrize("text, language", [
    ("This study uses a mixed-integer linear program for release scheduling.", "en"),
    ("Bu çalışma, salım-zamanı çizelgelemesi için karma tamsayılı doğrusal program kullanmaktadır.", "tr"),
])
def test_claim_naming_the_writers_own_work_is_flagged(text, language):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["answer_language"] = language
    draft["claims"] = [dict(draft["claims"][0], text=text)]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok  # phrasing findings are warnings, never a rejection (D19)
    assert [w.path for w in report.warnings if w.code == "own_work_phrase_in_claim"] == ["/claims/0/text"]


@pytest.mark.parametrize("sentence", [
    "Beklenen bit hata olasılığının en aza indirildiği bildirilmiştir.",  # live Luna form of "… olduğu bildirilmiştir."
    "Röle bakterilerinin sınırlı besin arzını iletim görevleri arasında paylaştığı gösterilmiştir.",
])
def test_turkish_reported_verb_participle_counts_as_the_frames_olduğu(sentence):
    assert phrasebank.unframed(sentence, TEXT, "tr") == []


@pytest.mark.parametrize("text, language", [
    ("Previous studies have reported that release scheduling is formulated as a mixed-integer linear program.", "en"),
    ("Önceki çalışmalar, röle bakterilerinin sınırlı besin arzını paylaştığını bildirmiştir.", "tr"),
])
def test_several_sources_wording_for_a_one_source_claim_is_flagged(text, language):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["answer_language"] = language
    one = dict(draft["claims"][0], text=text, passage_ids=["psg_SYNA1abs01"])
    two = dict(draft["claims"][0], claim_label="c2", text=text, passage_ids=["psg_SYNA1abs01", "psg_SYNA3pg002"])
    draft["claims"], draft["limitations"], draft["unanswered_aspects"] = [one, two], [], []
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok and [w.path for w in report.warnings if w.code == "plural_sources_for_one_source"] == ["/claims/0/text"]


def test_turkish_case_ending_on_an_open_slot_is_not_a_frame_word():
    text = "Header.\n\n# Writing Conclusions\n\n## Aims\nThe main goal of the current study was to determine ...\ntr: Mevcut çalışmanın temel amacı, ...'i belirlemekti.\n"
    assert phrasebank.unframed("Mevcut çalışmanın temel amacı, röle yerleşimini belirlemekti.", text, "tr") == []


def test_sentence_following_one_sentence_of_a_two_sentence_frame_passes():
    sentence = "However, Lee (2020) is much more concerned with relay placement."
    assert phrasebank.unframed(sentence, TEXT, "en") == []


def test_each_sentence_of_a_field_is_checked_separately():
    text = "It has been reported that X holds. The supplied passages describe the model but not its validation."
    assert phrasebank.unframed(text, TEXT, "en") == ["The supplied passages describe the model but not its validation."]


def test_unframed_sentence_is_a_warning_that_names_its_field():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["limitations"][1]["text"] = "The published version of A3 was not inspected; the preprint passage may not reflect it."
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok and [w.code for w in report.warnings] == ["sentence_without_phrasebank_frame"]
    assert [w.path for w in report.warnings] == ["/limitations/1/text"]


def test_latex_math_in_a_claim_reads_as_one_slot_word():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = r"It has been reported that the objective $\min_{x} \sum_{i=1}^{N} P_e(x_i)$ is minimized subject to $\sum_i x_i \le Q$."
    draft["claims"][0]["passage_ids"] = ["psg_SYNA1pg003"]
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
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
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok and [w for w in report.warnings if w.code == "math_without_full_text"] == []


def test_language_without_frames_is_a_warning_not_a_failure():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["answer_language"] = "de"
    draft["claims"][0]["text"] = "Die Quelle formuliert ein gemischt-ganzzahliges Programm."
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.ok and [w.code for w in report.warnings] == ["phrasing_not_checked"]

"""The survey rule read from a record's own title, abstract and reference count (SW5.1, SW9.3).

Titles and abstracts are SYNTHETIC and come from two fields (molecular communication and wireless sensing). Passing
these tests shows what the rule does with a given string, not how often it is right about real literature: the word
lists and the 150-reference threshold were chosen on one topic against an earlier model's labels.
"""

from deixis.domain import survey
from deixis.domain.survey_words import STRONG_TITLE_WORDS

ABSTRACT = ("We schedule SYNTHETIC molecule releases and report the packet size that minimises the error rate under "
            "a fixed energy budget.")
SURVEY_ABSTRACT = ("This survey collects SYNTHETIC results on molecular release scheduling and compares the packet "
                   "sizes they report.")
ALL_WORDS = STRONG_TITLE_WORDS


def flags(title=None, abstract=None, reference_count=None, words=ALL_WORDS):
    return [(s.flag, s.evidence) for s in survey.signals(title, abstract, reference_count, words)]


# ---- the title -----------------------------------------------------------------------------


def test_every_strong_title_word_flags_a_record():
    for word in STRONG_TITLE_WORDS:
        title = f"SYNTHETIC {word} of relay scheduling in wireless sensor networks"
        assert flags(title=title) == [("survey_title_word", word)], word


def test_a_longer_word_that_merely_contains_a_strong_one_does_not_flag():
    assert flags(title="SYNTHETIC previewing the relay channel") == []
    assert flags(title="SYNTHETIC reviewer agreement in molecular sensing") == []
    assert flags(title="SYNTHETIC surveying instruments for a vascular channel") == []


def test_a_weak_title_word_flags_nothing_on_its_own():
    assert flags(title="SYNTHETIC recent advances in molecular communication") == []
    assert flags(title="SYNTHETIC challenges and future directions of relay scheduling") == []


def test_the_hyphenated_state_of_the_art_is_the_same_phrase():
    assert flags(title="SYNTHETIC state-of-the-art relay scheduling") == [("survey_title_word", "state of the art")]
    assert flags(title="SYNTHETIC state of the art in relay scheduling") == [("survey_title_word",
                                                                              "state of the art")]


def test_markup_in_the_title_is_stripped_before_the_words_are_read():
    assert flags(title="A <i>survey</i> of SYNTHETIC $\\alpha$ relay scheduling") == [("survey_title_word", "survey")]


def test_a_correction_notice_is_read_by_the_title_it_names():
    """`comparable_title` takes the notice prefix off, so the notice of a survey reads as the survey it names."""
    assert flags(title="Publisher Correction: A survey of SYNTHETIC relay scheduling") == [
        ("survey_title_word", "survey")]


# ---- the abstract and the reference count --------------------------------------------------


def test_an_abstract_that_names_itself_a_survey_is_flagged_and_an_ordinary_one_is_not():
    assert flags(abstract=SURVEY_ABSTRACT) == [("survey_abstract_phrase", "This survey")]
    assert flags(abstract=ABSTRACT) == []
    assert flags(abstract=None) == []


def test_an_abstract_phrase_split_across_lines_is_still_read():
    """The evidence is the phrase as the rule read it: one line, single spaces."""
    assert flags(abstract="We\n   review SYNTHETIC packet sizes.") == [("survey_abstract_phrase", "We review")]


def test_the_reference_count_flags_at_the_threshold_and_not_below_it():
    assert flags(reference_count=149) == []
    assert flags(reference_count=150) == [("survey_reference_count", "150")]
    assert flags(reference_count=182) == [("survey_reference_count", "182")]


def test_a_record_whose_sources_named_no_reference_count_carries_no_count_signal():
    """An unknown count is not a count of zero, and not a count below the threshold either."""
    assert flags(reference_count=None) == []


# ---- the question's own word -----------------------------------------------------------------


def test_a_strong_word_the_question_itself_uses_leaves_that_researchs_list():
    kept, dropped = survey.title_words(["code review", "static analysis", "defect density"])
    assert dropped == ("review",) and "review" not in kept and "survey" in kept


def test_a_research_that_dropped_review_still_flags_a_survey_of_code_review():
    kept, _ = survey.title_words(["code review", "static analysis"])
    assert flags(title="A survey of SYNTHETIC code review practice", words=kept) == [("survey_title_word", "survey")]
    assert flags(title="SYNTHETIC code review at scale", words=kept) == []


def test_a_question_that_uses_no_strong_word_drops_nothing():
    kept, dropped = survey.title_words(["molecular communication", "release scheduling"])
    assert (kept, dropped) == (STRONG_TITLE_WORDS, ())


def test_a_word_inside_a_longer_question_word_is_not_dropped():
    kept, dropped = survey.title_words(["reviewer agreement", "surveying instruments"])
    assert dropped == ()
    assert kept == STRONG_TITLE_WORDS


# ---- order ------------------------------------------------------------------------------------


def test_the_three_signals_come_back_in_a_fixed_order():
    found = flags(title="A SYNTHETIC survey of relay scheduling", abstract=SURVEY_ABSTRACT, reference_count=200)
    assert [flag for flag, _ in found] == ["survey_title_word", "survey_abstract_phrase", "survey_reference_count"]


def test_a_record_with_no_signal_gets_an_empty_list():
    assert flags(title="SYNTHETIC relay scheduling in a vascular channel", abstract=ABSTRACT,
                 reference_count=12) == []

"""Compiling the approved cue phrases, scoring a passage with them and ordering by that score (slice 11, SW12.3).

Pure checks of `workflow/criterion_passages.py`: no store, no app, no model. The phrases and passages are SYNTHETIC
and from two fields. What passes here is the ordering rule, not that these phrases find a good passage: the one
measurement behind them is in D84's limits and covers one topic.
"""

import re

from deixis.workflow import criterion_passages as cp

# SYNTHETIC cue phrases: an optimization criterion and, from another field, a clinical-trial one.
PHRASES = [{"phrase": "decision variable"}, {"phrase": "subject to"}, {"phrase": "randomised controlled trial"}]


def patterns(rows=PHRASES):
    return cp.compile_phrases(rows)["patterns"]


def ids(ordered):
    return [p["id"] for p in ordered]


def passage(pid, text, page=None):
    return {"id": pid, "text": text, "physical_page": page}


# ---- compiling ------------------------------------------------------------------------------------------

def test_a_phrase_split_by_a_line_end_is_still_found():
    """A PDF page breaks a phrase across lines; the words are joined by whitespace, not by a single space."""
    assert cp.score("we minimise it\nsubject   to\nthe budget", patterns()) == (1, 1)


def test_the_english_plural_is_found_and_a_phrase_inside_a_word_is_not():
    assert cp.score("two decision variables are free", patterns()) == (1, 1)
    assert cp.score("the subtopic subject tolerance", patterns()) == (0, 0)
    assert cp.score("predecision variable", patterns()) == (0, 0)


def test_case_does_not_matter():
    assert cp.score("Subject To the SUBJECT TO rule", patterns()) == (1, 2)


def test_a_phrase_carrying_regular_expression_marks_is_searched_as_plain_text():
    """Compiling never fails and nothing is treated as a regular expression; `norm` still takes the outer marks off.

    So "c++" is left as one character and drops below the floor. Whether a phrase like that is worth keeping is a
    question for the normaliser, which this slice does not touch: it writes no second one.
    """
    marked = cp.compile_phrases([{"phrase": "s.t."}, {"phrase": "c++"}, {"phrase": "(a|b)"}])
    assert [phrase for phrase, _ in marked["patterns"]] == ["a|b", "s.t"]
    assert marked["dropped"] == [{"phrase": "c", "reason": "too_short"}]
    # The marks are literal: the text that matches carries them, and "a" or "b" alone matches nothing.
    assert cp.score("we write s.t. over (a|b) pairs", marked["patterns"]) == (2, 2)
    assert cp.score("a b and at and st", marked["patterns"]) == (0, 0)


def test_a_short_phrase_and_a_repeated_one_are_dropped_with_their_reason():
    compiled = cp.compile_phrases([{"phrase": "at"}, {"phrase": "subject to"}, {"phrase": "Subject  To"},
                                   {"phrase": "decision variable"}])
    assert [phrase for phrase, _ in compiled["patterns"]] == ["decision variable", "subject to"]
    assert compiled["dropped"] == [{"phrase": "at", "reason": "too_short"},
                                   {"phrase": "subject to", "reason": "duplicate"}]


def test_an_empty_phrase_list_compiles_to_no_pattern():
    assert cp.compile_phrases([]) == {"patterns": [], "dropped": []}
    assert cp.score("subject to the budget", []) == (0, 0)


# ---- the score pair and the order -----------------------------------------------------------------------

def test_the_score_pair_counts_separate_phrases_and_all_occurrences():
    text = "subject to the budget, subject to the horizon, with one decision variable"
    assert cp.score(text, patterns()) == (2, 3)


def test_the_order_reads_separate_phrases_first_then_occurrences_then_the_page_then_the_identifier():
    two_phrases = passage("p_two", "subject to one decision variable", page=9)
    twice = passage("p_twice", "subject to this and subject to that", page=8)
    once_late = passage("p_late", "subject to the budget", page=7)
    once_early = passage("p_early", "subject to the horizon", page=2)
    no_page = passage("p_nopage", "subject to nothing", page=None)
    same_a = passage("a_same", "subject to the same", page=2)
    ordered = cp.criterion_order([once_late, no_page, twice, once_early, two_phrases, same_a], patterns())
    assert ids(ordered) == ["p_two", "p_twice", "a_same", "p_early", "p_late", "p_nopage"]


def test_a_passage_no_phrase_occurs_in_is_not_in_the_list():
    off_topic = passage("p_off", "the bakery delivers bread every morning", page=1)
    assert ids(cp.criterion_order([off_topic, passage("p_on", "subject to the budget", page=2)], patterns())) == ["p_on"]
    assert cp.criterion_order([off_topic], patterns()) == []


def test_one_occurrence_is_enough_to_enter_the_list_at_its_end():
    """No threshold in this slice: whether an every-paper phrase blurs the order is unmeasured (D84)."""
    weak = passage("p_weak", "subject to the budget", page=1)
    strong = passage("p_strong", "subject to it with a decision variable", page=5)
    assert ids(cp.criterion_order([weak, strong], patterns())) == ["p_strong", "p_weak"]


def test_a_pattern_is_built_from_escaped_words_alone():
    """The guarantee, read off the pattern: nothing between the boundaries comes from the phrase unescaped."""
    (_, compiled), = patterns([{"phrase": "c++ s.t."}])
    assert compiled.pattern == r"(?<!\w)" + re.escape("c++") + r"\s+" + re.escape("s.t") + r"s?(?!\w)"


# ---- the same order under two hash seeds ----------------------------------------------------------------

def test_the_compiled_phrases_scores_and_order_are_the_same_under_two_hash_seeds():
    """The replay stage runs the fixed SYNTHETIC pool of two fields in its own process (SW14.7)."""
    from test_determinism import digest

    assert digest("criterion_passages", "1", 1) == digest("criterion_passages", "2", 2)

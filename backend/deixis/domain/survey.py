"""Whether a record describes itself as a survey, from its own title, abstract and reference count (SW5.1, SW9.3).

`signals` is pure: it reads no database, calls no model and asks no embedding, so the same record always gives the
same flags and a stored flag can be re-derived from what was stored. A flag is a routing label; it removes nothing
and decides no selection (SW5.4). Only the title signal takes a record off the screening list, and that is decided
by the caller, not here.

The word lists and the 150-reference threshold were chosen on one topic against an earlier model's labels
(`.local/quantum-source-comparison-2026-09-18/`), so they measure agreement with that judgement, not accuracy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from deixis.domain.record_identity import comparable_title, normalize_text
from deixis.domain.survey_words import ABSTRACT_SELF_DESCRIPTIONS, STRONG_TITLE_WORDS

REFERENCE_COUNT_SURVEY = 150  # SW5.1; chosen on one topic, not measured elsewhere
THRESHOLDS = {"reference_count": REFERENCE_COUNT_SURVEY}

_ABSTRACT_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in ABSTRACT_SELF_DESCRIPTIONS)


@dataclass(frozen=True)
class SurveySignal:
    flag: str  # "survey_title_word" | "survey_abstract_phrase" | "survey_reference_count"
    evidence: str  # the matched word or phrase as it stands in the text, or the count as text


def title_words(question_forms: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The strong title words this research may use, and the ones its own question took away (kept, dropped).

    A question about code review or tutorial dialogue writes a strong word itself; leaving it in the list would take
    every paper of that subject off the screening list. The list stays field-independent, and the dropped word is
    written into the protocol. Not measured.
    """
    asked = " ".join(normalize_text(form) for form in question_forms)
    dropped = tuple(word for word in STRONG_TITLE_WORDS if _matches(word, asked))
    return tuple(word for word in STRONG_TITLE_WORDS if word not in dropped), dropped


def signals(title: str | None, abstract: str | None, reference_count: int | None,
            words: tuple[str, ...]) -> list[SurveySignal]:
    """Every survey signal this record carries, in a fixed order: title, abstract, then reference count.

    A record without an abstract carries no abstract signal and a record whose sources named no reference count
    carries no count signal; an unknown count is not a count of zero.
    """
    found: list[SurveySignal] = []
    # The title is read as the identity rule reads it: HTML and LaTeX remnants gone, a notice prefix gone, the
    # words lower case and separated by single spaces, so "state-of-the-art" reads as the phrase it is.
    readable = comparable_title({"title": title}) if title else ""
    matched = next((word for word in words if _matches(word, readable)), None)
    if matched is not None:
        found.append(SurveySignal("survey_title_word", matched))
    text = " ".join((abstract or "").split())
    phrase = next((match for pattern in _ABSTRACT_PATTERNS if (match := pattern.search(text))), None)
    if phrase is not None:
        found.append(SurveySignal("survey_abstract_phrase", phrase.group(0)))
    if reference_count is not None and reference_count >= REFERENCE_COUNT_SURVEY:
        found.append(SurveySignal("survey_reference_count", str(reference_count)))
    return found


def _matches(word: str, text: str) -> bool:
    """Whether the normalised text holds the word at a word boundary; both sides are already normalised."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None

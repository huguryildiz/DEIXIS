"""Order passages by the cue phrases this research's criterion was approved with (SW12.3, SW15.4).

The phrases are proposed by a model and approved or replaced by the user (D78, D80); here they only *order*. Nothing
in this module selects, drops or decides: a passage no phrase matches is left out of the criterion list and stays
exactly what it was for every other list. The score is never stored: it is a pure function of stored passage text and
stored phrases, computed per retrieval, so a later slice can derive it again.

Phrases are written by a model or a user and are never compiled as regular expressions: every word goes through
`re.escape`, and the only regular-expression parts of a pattern are the two boundaries and the English plural. The
pattern and the score pair are the ones measured in `.local/generalized-criterion-2026-09-20/run.py`.

Pure: no clock, no randomness, no store, and the order of the phrases as they arrive never reaches the result (SW14.6).
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from deixis.workflow.criterion import norm

MIN_PHRASE_CHARS = 3  # a shorter phrase matches too much to order anything; the measurement used the same floor
CRITERION_ROOM_DIVISOR = 4  # the share of the answer input the criterion quota may fill
CRITERION_PAGES_PER_SOURCE = 1  # criterion pages one source adds when the included sources outnumber the limit (D55)
THRESHOLDS = {"min_phrase_chars": MIN_PHRASE_CHARS, "criterion_room_divisor": CRITERION_ROOM_DIVISOR,
              "criterion_pages_per_source": CRITERION_PAGES_PER_SOURCE}


def _pattern(phrase: str) -> str:
    """The literal pattern of one phrase, in the form that was measured.

    `s?` catches the English plural alone: in a language that suffixes, a phrase is found only as it was written.
    """
    return r"(?<!\w)" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"s?(?!\w)"


def compile_phrases(cue_phrases: list[dict[str, Any]]) -> dict[str, Any]:
    """The protocol's cue phrases as literal patterns, with what was dropped and why.

    A phrase is written one way through `criterion.norm`, the same normaliser the criterion itself was built with, so
    a protocol phrase arrives here already normalised. The kept pairs are ordered by the phrase, never by arrival.
    """
    kept: dict[str, re.Pattern[str]] = {}
    dropped: list[dict[str, str]] = []
    for row in cue_phrases:
        phrase = norm(row["phrase"])
        if len(phrase) < MIN_PHRASE_CHARS:
            dropped.append({"phrase": phrase, "reason": "too_short"})
        elif phrase in kept:
            dropped.append({"phrase": phrase, "reason": "duplicate"})
        else:
            kept[phrase] = re.compile(_pattern(phrase), re.IGNORECASE)
    return {"patterns": sorted(kept.items()), "dropped": sorted(dropped, key=lambda row: (row["phrase"], row["reason"]))}


def score(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> tuple[int, int]:
    """How many separate phrases the text holds, and how many occurrences in all.

    The text is read NFKC-normalised because an OCR or publisher text layer can still carry ligatures; PyMuPDF text
    already spells them out.
    """
    counts = [len(pattern.findall(unicodedata.normalize("NFKC", text))) for _, pattern in patterns]
    return sum(1 for count in counts if count), sum(counts)


def criterion_order(passages: list[dict[str, Any]], patterns: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, Any]]:
    """The passages a phrase occurs in, best first. The caller decides which passages it hands over.

    No threshold: a passage holding one phrase is in the list, at its end. A passage holding none is not in the list,
    which removes it from nothing else — the criterion quota is one list among several (SW15.4).
    """
    scored = []
    for passage in passages:
        distinct, total = score(passage["text"], patterns)
        if distinct:
            page = passage["physical_page"] if passage["physical_page"] is not None else math.inf
            scored.append(((-distinct, -total, page, passage["id"]), passage))
    return [passage for _, passage in sorted(scored, key=lambda row: row[0])]

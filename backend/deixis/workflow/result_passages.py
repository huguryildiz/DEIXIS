"""Give a full-text source's first answer-input slot to the passage that reports the outcomes the question asks about.

A full-text source usually reaches the answer input with two passages. The topic ranking gives the first slot to the
page that repeats the question's words most: the title page, the introduction or related work, which restate the
abstract or describe other papers. The page that reports the paper's own delivery ratio or energy figures rarely ranks
there, so the answer cannot state them although the reading had them. When the research's vocabulary names outcome
terms, the source's most result-dense passage takes the first slot, formula passages keep the second (D56), and a
reference-list page goes to the end of the source's order. Nothing is removed, and with no outcome terms nothing moves.

The score counts reported values (a number with `%`, `percent` or a unit) in sentences that name an outcome term and a
change or comparison word ("reduced", "higher", "than", "up to"). A sentence that describes the setup ("initial
energy", "is set to", "deployed", "simulation parameters", "an area of", "100 nodes") counts nothing, so a parameter
table that happens to name energy consumption scores 0. A range or a `±` value counts once. The outcome terms come
from the research and are matched as literal phrases (`criterion_passages`); the cue words and units are English. The
constants were chosen on one research (DBR vs VBF routing, 17 Oct 2026); see the decision log.

Pure: no clock, no randomness, no store.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from deixis.workflow import criterion_passages, formula_passages

_UNIT = (r"(?:\s?%|\s?(?:percent|per\s?cent)\b"
         r"|\s?(?:[kmµμ]?J|[mkµμ]?W|[mµμ]?s|dB[m]?|[kKM]?bps|[kKM]?b/s|k?m|[kKMG]?Hz)(?![\w/]))")
_BARE = r"[-−]?\d+(?:[.,]\d+)?"
_NUMBER = r"(?<![\w.])" + _BARE
# A range or a ± value is one reported value: `12–15 %`, `15 J–60 J`, `3 to 5 J`, `0.8 ± 0.1 J`. `from 12 J to 8 J`
# is two: a unit before `to` ends the first value.
VALUE = re.compile(_NUMBER + r"(?:(?:" + _UNIT + r")?\s*(?:[-–—]|±)\s*" + _BARE + r"|\s*\bto\s+" + _BARE + r")?" + _UNIT,
                   re.IGNORECASE)
CHANGE = re.compile(r"\b(?:higher|lower|better|worse|improv\w*|reduc\w*|increas\w*|decreas\w*|achiev\w*|outperform\w*"
                    r"|compared|than|gains?|saving\w*|saves?|up to)\b", re.IGNORECASE)
SETTING = re.compile(r"\b(?:initial(?:ly)? energy|(?:is|are|was|were) set\b|set (?:to|as|at)\b|configured|deployed|deployment"
                     r"|simulation parameters?|parameter settings?|area of|transmission range (?:of|is)"
                     r"|range of (?:one-hop )?transmission)\b", re.IGNORECASE)
# A sentence ends at `.!?;` and whitespace before a capital or a bracket, at a blank line, and at `.!?;` and
# whitespace before a number unless the token before a period is an abbreviation (`approx. 20%`, `Fig. 7`, `U.S. 5`).
# A decimal (12.5) has no space after its point and a PDF line wrap is a single line break, so neither splits.
BOUNDARY = re.compile(r"[.!?;]\s+(?=[A-Z(\[\d])|\n\s*\n")
ABBREVIATIONS = frozenset({"approx", "ca", "e.g", "i.e", "cf", "vs", "resp", "al", "fig", "figs", "eq", "eqs", "no", "nos",
                           "vol", "pp", "sec", "tab", "ref", "refs", "max", "min", "avg"})
_INITIALS = re.compile(r"(?:[a-z]\.)*[a-z]")  # one letter, or dotted initials such as U.S
CITATION = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]|\bet al\.|\bvol\.|\bpp\.", re.IGNORECASE)
MIN_SCORE = 2  # one value alone is too often a stray figure in an introduction; see D84
REFERENCE_HITS = 6  # citation marks that make a passage with no outcome term a reference list
THRESHOLDS = {"min_score": MIN_SCORE, "reference_hits": REFERENCE_HITS}


def compile_terms(outcome_terms: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    """The research's outcome terms as literal patterns, the way criterion phrases are compiled."""
    return criterion_passages.compile_phrases([{"phrase": term} for term in outcome_terms])["patterns"]


def _sentences(text: str) -> list[str]:
    # A PDF text layer breaks lines inside a sentence; a single line break is a space, a blank line ends a sentence.
    text = unicodedata.normalize("NFKC", text)
    parts, start = [], 0
    for mark in BOUNDARY.finditer(text):
        if mark.group(0)[0] == "." and text[mark.end()].isdigit():
            token = re.split(r"[\s(\[]", text[start:mark.start()])[-1].lower()
            if token in ABBREVIATIONS or _INITIALS.fullmatch(token):
                continue
        parts.append(text[start:mark.end()])
        start = mark.end()
    parts.append(text[start:])
    return [re.sub(r"\s*\n\s*", " ", part).strip() for part in parts if part.strip()]


def score(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> int:
    """How many outcome-associated values the text reports; 0 when no outcome term occurs in it."""
    total = 0
    for sentence in _sentences(text):
        if (any(pattern.search(sentence) for _, pattern in patterns) and CHANGE.search(sentence)
                and not SETTING.search(sentence)):
            total += len(VALUE.findall(sentence))
    return total


def reference_list(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> bool:
    """A page of citations: many citation marks and no outcome term."""
    text = unicodedata.normalize("NFKC", text)
    return len(CITATION.findall(text)) >= REFERENCE_HITS and not any(pattern.search(text) for _, pattern in patterns)


def order(ranked: list[dict[str, Any]], patterns: list[tuple[str, re.Pattern[str]]], formulas: bool) -> tuple[list[dict[str, Any]], bool]:
    """A full-text source's passages in answer-input order, and whether a result passage took the first slot.

    Slot 1 is the most result-dense passage when it reaches `MIN_SCORE`, else the best topic passage; slot 2 is the
    most formula-dense non-reference passage when formulas are asked (`formula_passages.bring_forward`); reference
    lists go last; everything else keeps its rank. An equal score keeps the higher-ranked passage. With no outcome patterns this is exactly the
    order before D84.
    """
    if not patterns or len(ranked) < 2:
        return (formula_passages.bring_forward(ranked) if formulas else ranked), False
    refs = [reference_list(p["text"], patterns) for p in ranked]
    ordered = [p for p, ref in zip(ranked, refs) if not ref]
    tail = [p for p, ref in zip(ranked, refs) if ref]  # never promoted, by either rule
    scores = [score(p["text"], patterns) for p in ordered]
    best = max(range(len(ordered)), key=lambda i: (scores[i], -i), default=0)
    moved = best > 0 and scores[best] >= MIN_SCORE
    if moved:
        ordered = [ordered[best], *(p for i, p in enumerate(ordered) if i != best)]
    return [*(formula_passages.bring_forward(ordered) if formulas else ordered), *tail], moved

"""The phrases a first round's own records offer as wider search terms (SW2.4).

Pure: no network, no database, no clock. The question gave the first query its words, so a field's common term is
missing from it whenever the user did not happen to write it. What the first round returned holds those words: the
authors' own keywords, and the phrases their titles repeat. This module takes the candidates; whether a candidate is
really used in the field is decided by the count probe in `workflow/expansion.py`, and nothing here reaches a query
on its own.

Two lists never become a candidate, whatever their frequency: a phrase that holds a term the first query already
searched (it would widen nothing), and a phrase that holds a claim or exclusion word (SW1.3). Both are matched with a
final `s` taken off every word, because OpenAlex counts a singular and its plural as one term and "quantum network"
would otherwise search again what "quantum networks" already found (D90). No word list of this module's own exists;
the stop words are the ones the question was read with.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from deixis.domain.vocabulary import words
from deixis.domain.vocabulary_words import ENGLISH_FUNCTION_WORDS, GENERAL_WORDS

MIN_DOCUMENT_FREQUENCY = 3  # a phrase must occur in at least this many first-round records
MAX_PROBED_PHRASES = 20  # candidates that reach the count probe, most frequent first
TITLE_NGRAM_LENGTHS = (2, 3)
MIN_WORD_LETTERS = 3  # a shorter word keeps its n-gram out: initials and units are not search phrases
MAX_KEYWORD_WORDS = 4  # a longer author keyword is a sentence about the paper, not a term of the field
SOURCE_ORDER = ("title", "author_keyword")
EDGE_WORDS = ENGLISH_FUNCTION_WORDS | GENERAL_WORDS


@dataclass(frozen=True)
class Candidate:
    phrase: str  # normalised as domain/vocabulary.py normalises a phrase: lower case, single spaces
    document_frequency: int
    sources: tuple[str, ...]  # "title", "author_keyword", in that order when both


def candidates(records: list[dict[str, Any]], queried_forms: list[str], side_words: list[str]) -> list[Candidate]:
    """The phrases of the first round's records that may be probed, most frequent first.

    A record is a work head with its `title` and `author_keywords`; a work is counted once however many of its
    versions the list holds, so a preprint and its published record do not make a phrase look twice as common.
    """
    blocked = [words(form) for form in [*queried_forms, *side_words] if words(form)]
    # A phrase and its plural are one candidate, as OpenAlex counts them as one term: they are counted under their
    # shared stem, a work holding both counts once, and the more frequent form stands for both (review of 13g,
    # 2026-09-23; D90's matching already stems the blocked terms the same way).
    frequency: Counter[str] = Counter()
    sources: dict[str, set[str]] = {}
    forms: dict[str, Counter[str]] = {}
    for group in _by_work(records):
        found: dict[str, set[str]] = {}
        for record in group:
            for phrase in _title_phrases(record.get("title") or ""):
                found.setdefault(phrase, set()).add("title")
            for phrase in _keyword_phrases(record.get("author_keywords") or []):
                found.setdefault(phrase, set()).add("author_keyword")
        stems: dict[str, set[str]] = {}
        for phrase, where in found.items():
            key = " ".join(stem(word) for word in phrase.split())
            stems.setdefault(key, set()).update(where)
            forms.setdefault(key, Counter())[phrase] += 1
        for key, where in stems.items():
            frequency[key] += 1
            sources.setdefault(key, set()).update(where)
    shown = {key: min(counts, key=lambda phrase: (-counts[phrase], phrase)) for key, counts in forms.items()}
    kept = [Candidate(shown[key], count, tuple(s for s in SOURCE_ORDER if s in sources[key]))
            for key, count in frequency.items()
            if count >= MIN_DOCUMENT_FREQUENCY and not _holds_any(shown[key], blocked)]
    # Frequency decides, and the phrase itself breaks a tie: neither the order the records arrived in nor a set's
    # iteration order may reach the list the probe spends its requests on (SW14.6).
    return sorted(kept, key=lambda candidate: (-candidate.document_frequency, candidate.phrase))[:MAX_PROBED_PHRASES]


def _by_work(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The records grouped by the work they are a version of; a record naming no work stands for itself."""
    groups: dict[Any, list[dict[str, Any]]] = {}
    for position, record in enumerate(records):
        groups.setdefault(record.get("work_id") or ("row", position), []).append(record)
    return list(groups.values())


def _title_phrases(title: str) -> set[str]:
    """The title's two- and three-word phrases that can stand as a search term."""
    tokens = words(title)
    phrases: set[str] = set()
    for length in TITLE_NGRAM_LENGTHS:
        for start in range(len(tokens) - length + 1):
            gram = tokens[start:start + length]
            if gram[0] in EDGE_WORDS or gram[-1] in EDGE_WORDS:
                continue  # a phrase that begins or ends in a function or general word is a fragment of a sentence
            if any(len(word) < MIN_WORD_LETTERS for word in gram):
                continue
            phrases.add(" ".join(gram))
    return phrases


def _keyword_phrases(keywords: Iterable[str]) -> set[str]:
    """An author keyword enters whole: the authors wrote it as one term and it is not cut into n-grams."""
    phrases: set[str] = set()
    for keyword in keywords:
        gram = words(keyword)
        if not gram or len(gram) > MAX_KEYWORD_WORDS:
            continue
        if len(gram) == 1 and gram[0] in GENERAL_WORDS:
            continue
        phrases.add(" ".join(gram))
    return phrases


def stem(word: str) -> str:
    """The word without a final plural `s`; a word of three letters or fewer keeps it. A rule, not a stemmer."""
    return word[:-1] if word.endswith("s") and len(word) > MIN_WORD_LETTERS else word


def _holds_any(phrase: str, blocked: list[list[str]]) -> bool:
    """Whether the phrase holds one of the blocked word sequences whole, at a word boundary, singular or plural."""
    tokens = [stem(word) for word in words(phrase)]
    stems = [[stem(word) for word in block] for block in blocked]
    return any(tokens[start:start + len(block)] == block
               for block in stems for start in range(len(tokens) - len(block) + 1))

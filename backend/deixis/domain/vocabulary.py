"""The search phrases a question holds, read by code alone (SW2.1, SW2.2).

Pure: no network, no database, no clock. The question is stripped of its asking frame, split at function words,
punctuation and cue words, and what stands between two splits is a candidate phrase (RAKE's candidate step). The word
immediately before a phrase names the block it goes in; that assignment is a rule, it is unreliable, and the user
confirms or replaces it through `key_terms` (the screen for it is slice 08).

Two lists never reach a query. A phrase in a method position is a claim word: code cannot widen "ILP" into
"optimization", so SW1.3's broad method block stays empty here and everything in that position is treated as the
claim under test. Exclusion words are the same in the other direction. The outcome block is kept for ranking
(slice 07) and is not queried either.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

from deixis.domain.vocabulary_words import (CUE_WORDS, ENGLISH_FUNCTION_WORDS, GENERAL_WORDS, MAX_CUE_WORDS,
                                            QUESTION_FRAMES)

ENGLISH_FUNCTION_WORD_SHARE = 0.2  # a question with accented letters is English only at or above this share
LONG_QUESTION_WORDS = 8  # a text this long without one English function word is not an English sentence
BLOCK_NAMES = ("setting", "task", "outcome")
MAX_KEY_TERM_GROUPS = len(BLOCK_NAMES)
KEY_TERM_PREFIXES = {"claim": "method", "not": "excluded"}
_WORD = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)
_TOKEN = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*|[^\s\w]", re.UNICODE)


@dataclass(frozen=True)
class Phrase:
    text: str  # normalised, lower case, single spaces
    position: str  # setting | task | method | outcome | excluded
    origin: str  # question | key_terms


@dataclass(frozen=True)
class Extraction:
    language: str  # "en" | "other"
    blocks: dict[str, list[str]]  # "setting", "task", "outcome": phrases in the order they appeared
    claim_words: list[str]  # method-position phrases: never queried (SW1.3)
    exclusion_words: list[str]
    block_assignment: str  # "rule" | "user"


def detect_language(question: str, language_hint: str | None) -> str:
    """The hint decides when there is one; otherwise the question is English unless something says it is not.

    Something is a letter outside the Latin script, accented letters together with few English function words, or a
    long text with no English function word at all. A plain English question dense in content words, or a short list
    of keywords, holds few function words and must not be sent back for key terms. A question in another language
    written without accents is read as English; its phrases then meet the count probe, which is the second guard
    (SW2.1)."""
    if language_hint:
        return "en" if language_hint.strip().lower().startswith("en") else "other"
    for character in question:
        if character.isalpha() and not unicodedata.name(character, "").startswith("LATIN"):
            return "other"
    words = [w.lower() for w in _WORD.findall(question)]
    if not words:
        return "other"
    share = sum(word in ENGLISH_FUNCTION_WORDS for word in words) / len(words)
    if any(not character.isascii() for character in question if character.isalpha()):
        return "en" if share >= ENGLISH_FUNCTION_WORD_SHARE else "other"
    return "other" if share == 0 and len(words) >= LONG_QUESTION_WORDS else "en"


def parse_key_terms(key_terms: str) -> Extraction:
    """The user's own English terms: semicolon between blocks, comma between synonyms of one block.

    The groups fill `setting`, `task` and `outcome` in that order; a group written `claim:` or `not:` fills a side
    list instead. Anything else is refused rather than guessed at, because a misread group silently changes a query.
    """
    if not key_terms or not key_terms.strip():
        raise ValueError("Key terms are empty")
    phrases: list[Phrase] = []
    positions: list[str] = []
    for group in key_terms.split(";"):
        text = group.strip()
        if not text:
            raise ValueError("An empty key-term group")
        prefix, _, rest = text.partition(":")
        if prefix.strip().lower() in KEY_TERM_PREFIXES:
            position, text = KEY_TERM_PREFIXES[prefix.strip().lower()], rest
        else:
            if len(positions) >= MAX_KEY_TERM_GROUPS:
                raise ValueError(f"More than {MAX_KEY_TERM_GROUPS} blocks; use 'claim:' or 'not:' for the side lists")
            position = BLOCK_NAMES[len(positions)]
            positions.append(position)
        terms = [" ".join(t.split()).lower() for t in text.split(",")]
        if not any(terms) or not all(terms):
            raise ValueError(f"An empty term in the key-term group {group.strip()!r}")
        phrases += [Phrase(term, position, "key_terms") for term in terms]
    return _extraction("en", phrases, "user")


def extract(question: str, language_hint: str | None = None, key_terms: str | None = None) -> Extraction | None:
    """The question's search phrases, or None when code cannot read the question and the user gave no key terms.

    Code never translates: a question that is not English and carries no key terms returns None, and the run pauses
    for the user (SW2.1).
    """
    language = detect_language(question, language_hint)
    if key_terms and key_terms.strip():
        return replace(parse_key_terms(key_terms), language=language)
    if language != "en":
        return None
    return _extraction(language, _phrases(question), "rule")


def _extraction(language: str, phrases: list[Phrase], block_assignment: str) -> Extraction:
    """One phrase text keeps the first position it appeared in; the order is the order it appeared in."""
    kept: dict[str, Phrase] = {}
    for phrase in phrases:
        kept.setdefault(phrase.text, phrase)
    return Extraction(
        language=language,
        blocks={name: [p.text for p in kept.values() if p.position == name] for name in BLOCK_NAMES},
        claim_words=[p.text for p in kept.values() if p.position == "method"],
        exclusion_words=[p.text for p in kept.values() if p.position == "excluded"],
        block_assignment=block_assignment,
    )


def _strip_frames(sentence: str) -> str:
    words = sentence.split()
    lowered = [w.lower() for w in words]
    for frame in QUESTION_FRAMES:
        parts = frame.split()
        if lowered[: len(parts)] == parts:
            return " ".join(words[len(parts):])
    return sentence


def _trim(words: list[str]) -> list[str]:
    """A phrase loses a general word at either end; a phrase of general words alone loses everything (SW2.2)."""
    start, end = 0, len(words)
    while start < end and words[start] in GENERAL_WORDS:
        start += 1
    while end > start and words[end - 1] in GENERAL_WORDS:
        end -= 1
    return words[start:end]


def _phrases(question: str) -> list[Phrase]:
    phrases: list[Phrase] = []
    for sentence in re.split(r"(?<=[.!?])\s+", question.strip()):
        tokens = [t.lower() for t in _TOKEN.findall(_strip_frames(sentence.strip()))]
        buffer: list[str] = []
        cue: str | None = None
        index = 0

        def close(next_cue: str | None) -> None:
            nonlocal buffer, cue
            if words := _trim(buffer):
                phrases.append(Phrase(" ".join(words), cue or "task", "question"))
            # A cue is spent on the phrase that followed it; with nothing between them it still stands, so
            # "in the wireless sensor networks" keeps its setting position across the article.
            if buffer or next_cue is not None:
                cue = next_cue
            buffer = []

        while index < len(tokens):
            matched = next((cue_words for length in range(MAX_CUE_WORDS, 0, -1)
                            if (cue_words := tuple(tokens[index:index + length])) in CUE_WORDS), None)
            if matched:
                close(CUE_WORDS[matched])
                index += len(matched)
            elif tokens[index] in ENGLISH_FUNCTION_WORDS:
                close(None)
                index += 1
            elif not _WORD.fullmatch(tokens[index]):  # punctuation ends the clause and the cue with it
                close(None)
                index += 1
            else:
                buffer.append(tokens[index])
                index += 1
        close(None)
    return phrases

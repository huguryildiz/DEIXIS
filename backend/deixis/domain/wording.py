"""Wording checks for answer and report prose: question language, sentence splitting, own-work and plural-source phrases.

The Academic Phrasebank frames these once sat beside were removed in D43; prose is no longer matched against frames.
"""

from __future__ import annotations

import re

LANGUAGES = ("en", "tr")
# Words naming the writer's own work. In an answer they stand for "this answer" or "the supplied passages", and a
# claim, which reports what a cited source says, may not use them.
_OWN_WORK = {
    "en": re.compile(r"\b(?:this|the present|the current)\s+(?:study|paper|research|investigation|thesis|dissertation|project)\b",
                     re.IGNORECASE),
    "tr": re.compile(r"\b(?:bu|mevcut|şimdiki)\s+(?:çalışma|makale|araştırma|inceleme|tez)(?!l[ae]r)[^\W\d_]*", re.IGNORECASE),
}
_PLURAL_SOURCES = {
    "en": re.compile(r"\b(?:previous|prior|recent|earlier|several|many|numerous|most|other|a number of)\s+"
                     r"(?:studies|researchers|authors|investigations|surveys|writers)\b", re.IGNORECASE),
    "tr": re.compile(r"\b(?:önceki|daha önceki|son|birçok|pek çok|bazı|çeşitli|diğer|bir dizi)\s+"
                     r"(?:çalışma|araştırma|araştırmacı|yazar|inceleme)l[ae]r[^\W\d_]*", re.IGNORECASE),
}
# Letters are matched case-sensitively: under IGNORECASE "İ" and "ı" also match the English "i" and "I".
_TURKISH_LETTERS = re.compile(r"[çğışöüÇĞİŞÖÜ]")
_TURKISH_WORDS = re.compile(r"\b(?:ve|bir|için|nasıl|hangi|nedir)\b", re.IGNORECASE)
_ABBREVIATIONS = ("e.g.", "i.e.", "et al.", "etc.", "vs.", "cf.", "vb.", "örn.", "bkz.")


def question_language(step_input: dict) -> str:
    """Turkish for a Turkish question (hint, else its letters and words), else English."""
    hint = (step_input["question"].get("language_hint") or "").lower()
    if hint:
        return "tr" if hint.split("-")[0] == "tr" else "en"
    text = step_input["question"]["text"]
    return "tr" if _TURKISH_LETTERS.search(text) or _TURKISH_WORDS.search(text) else "en"


def checked_language(answer_language: str) -> str | None:
    base = answer_language.lower().split("-")[0]
    return base if base in LANGUAGES else None


def sentences(text: str) -> list[str]:
    protected = text
    for abbreviation in _ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation.replace(".", "\0"))
    return [part.replace("\0", ".") for part in re.split(r"(?<=[.!?])\s+", protected.strip()) if part]


def plural_source_phrases(text: str, language: str) -> list[str]:
    """Phrases in `text` that attribute a statement to several sources, such as "previous studies" or "önceki çalışmalar"."""
    pattern = _PLURAL_SOURCES.get(language)
    return pattern.findall(text) if pattern else []


def own_work_phrases(text: str, language: str) -> list[str]:
    """Phrases in `text` that name the writer's own work, such as "this study" or "bu çalışma"."""
    pattern = _OWN_WORK.get(language)
    return pattern.findall(text) if pattern else []

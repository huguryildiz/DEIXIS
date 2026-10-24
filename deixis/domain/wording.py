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


# D51: a claim reworded from its source, and the kind of evidence it names. Both are warnings only.
COPIED_RUN_WORDS = 12  # the two D51 live reports: median 3 words in common with an anchor, at most 12 once
_EXPERIMENT = {
    "en": re.compile(r"\b(?:experiment(?:s|al|ally)?|field (?:trials?|tests?|deployments?)|sea (?:trials?|tests?)|"
                     r"testbeds?|real-world deployments?|prototypes?)\b", re.IGNORECASE),
    "tr": re.compile(r"\b(?:deney(?:sel)?[^\W\d_]*|saha (?:deneme|test|uygulama)[^\W\d_]*|deniz (?:deneme|test)[^\W\d_]*|"
                     r"prototip[^\W\d_]*)", re.IGNORECASE),
}
_SIMULATION = re.compile(r"\b(?:simulat\w*|simülasyon\w*|benzetim\w*)", re.IGNORECASE)
# "Simulation experiments", "numerical experiments", "benzetim deneyleri" describe a simulation, not a physical test.
_COMPUTED_EXPERIMENT = re.compile(r"\b(?:simulat\w*|numerical|computational|simülasyon\w*|benzetim\w*|sayısal)\s+"
                                  r"(?:experiment\w*|deney\w*)", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def copied_run(text: str, quote: str) -> int:
    """The longest run of consecutive words `text` shares with `quote`."""
    a, b = _words(text), _words(quote)
    best, previous = 0, [0] * (len(b) + 1)
    for x in a:
        current = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def experiment_phrases(text: str, language: str) -> list[str]:
    """Phrases naming a physical experiment or trial, such as "field trial" or "deneysel"."""
    pattern = _EXPERIMENT.get(language)
    return [m.group(0) for m in pattern.finditer(_COMPUTED_EXPERIMENT.sub(" ", text))] if pattern else []


def simulation_only(texts: list[str], language: str) -> bool:
    """True when the cited texts describe a simulation and none of them names an experiment or trial."""
    return any(_SIMULATION.search(t) for t in texts) and not any(experiment_phrases(t, language) for t in texts)

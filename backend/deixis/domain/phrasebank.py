"""Academic Phrasebank frames for the answer step: parsing, per-language rendering and the frame check.

The check is formal. A sentence passes when it keeps most of one frame's fixed words in order; whether the
chosen frame suits what the cited passages say is not something this code can decide.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

PHRASEBANK = "references/academic-phrasebank/phrases.txt"
LANGUAGES = ("en", "tr")
MIN_MATCHED = 3
MIN_COVERAGE = 0.7

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_SLOT = re.compile(r"^(?:x|y|z|xs|ys|zs)(?:'.*)?$")
_ELLIPSIS_SUFFIX = re.compile(r"(?:…|\.\.\.)['’][^\W\d_]+")
# Words naming the writer's own work. In an answer they stand for "this answer" or "the supplied passages", so a frame
# does not require them, and a claim, which reports what a cited source says, may not use them.
_OWN_WORK = {
    "en": re.compile(r"\b(?:this|the present|the current)\s+(?:study|paper|research|investigation|thesis|dissertation|project)\b",
                     re.IGNORECASE),
    "tr": re.compile(r"\b(?:bu|mevcut|şimdiki)\s+(?:çalışma|makale|araştırma|inceleme|tez)[^\W\d_]*", re.IGNORECASE),
}
_PLURAL_SOURCES = {
    "en": re.compile(r"\b(?:previous|prior|recent|earlier|several|many|numerous|most|other|a number of)\s+"
                     r"(?:studies|researchers|authors|investigations|surveys|writers)\b", re.IGNORECASE),
    "tr": re.compile(r"\b(?:önceki|daha önceki|son|birçok|pek çok|bazı|çeşitli|diğer|bir dizi)\s+"
                     r"(?:çalışma|araştırma|araştırmacı|yazar|inceleme)l[ae]r[^\W\d_]*", re.IGNORECASE),
}
# Turkish -DIK participle with an optional case or copula ending: olduğu, seçildiğini, paylaştığını, olmadığıydı.
_PARTICIPLE = re.compile(r"^[^\W\d_]{2,}[dt][ıiuü](?:ğ[ıiuü]|kl[ae]r[ıi])(?:n[ıiuü]|n[ae]|nd[ae]|nd[ae]n)?(?:yd[ıiuü])?$")
_PARTICIPLE_WORD = "-dik-"
_EXAMPLE_NAME = re.compile(r"\b([A-Z][A-Za-z’'-]+)(?: et al\.?| and co-workers)?,? \(?\d{4}")
# Letters are matched case-sensitively: under IGNORECASE "İ" and "ı" also match the English "i" and "I".
_TURKISH_LETTERS = re.compile(r"[çğışöüÇĞİŞÖÜ]")
_TURKISH_WORDS = re.compile(r"\b(?:ve|bir|için|nasıl|hangi|nedir)\b", re.IGNORECASE)
_ABBREVIATIONS = ("e.g.", "i.e.", "et al.", "etc.", "vs.", "cf.", "vb.", "örn.", "bkz.")


@dataclass
class Frame:
    section: str
    subsection: str
    text: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Pattern:
    groups: tuple[tuple[tuple[str, ...], ...], ...]  # group -> alternatives -> fixed words
    least: int  # fixed words a sentence must share with the frame before the ordered match is tried
    words: Counter


def parse(text: str) -> tuple[list[str], list[Frame]]:
    """Header lines and frames. `# ` starts a section, `## ` a subsection, `tr: ` renders the previous frame."""
    header: list[str] = []
    frames: list[Frame] = []
    section = subsection = ""
    for line in text.splitlines():
        if line.startswith("## "):
            subsection = line[3:]
        elif line.startswith("# "):
            section, subsection = line[2:], ""
        elif line.startswith("tr: ") and frames:
            frames[-1].text["tr"] = line[4:]
        elif line.strip():
            if section:
                frames.append(Frame(section, subsection, {"en": line}))
            else:
                header.append(line)
    return header, frames


def render(text: str, language: str) -> str:
    """The phrasebank as the model receives it: English frames, or their Turkish renderings for Turkish answers."""
    header, frames = parse(text)
    out = [line for line in header if not line.startswith("tr:")]
    if language == "tr":
        out.append("The frames below are literal Turkish renderings of the English originals.")
    heading = ("", "")
    for frame in frames:
        if frame.section != heading[0]:
            out += ["", f"# {frame.section}"]
        if (frame.section, frame.subsection) != heading and frame.subsection:
            out += ["", f"## {frame.subsection}"]
        heading = (frame.section, frame.subsection)
        out.append(frame.text.get(language) or frame.text["en"])
    return "\n".join(out) + "\n"


def frames_language(step_input: dict) -> str:
    """Frames the answer step receives: Turkish for a Turkish question (hint, else its letters and words), else English."""
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


def has_frames(phrasebank_text: str, language: str) -> bool:
    return bool(_patterns(phrasebank_text, language))


def unframed(text: str, phrasebank_text: str, language: str) -> list[str]:
    """Sentences of `text` that follow no frame of `language`."""
    patterns = _patterns(phrasebank_text, language)
    return [s for s in sentences(text) if not _follows(s, patterns, language)]


def _words(text: str, language: str) -> list[str]:
    if language == "tr":
        text = text.replace("İ", "i").replace("I", "ı")
    words = [w.replace("’", "'") for w in _WORD.findall(text.lower())]
    if language == "tr":
        # "… olduğu bildirilmiştir" renders "It has been reported that …"; the reported verb itself takes the same
        # -DIK participle ("seçildiği bildirilmiştir"), so any such participle counts as the frame's "olduğu".
        words = [_PARTICIPLE_WORD if _PARTICIPLE.match(w) else w for w in words]
    return words


@lru_cache(maxsize=4)
def _patterns(phrasebank_text: str, language: str) -> tuple[_Pattern, ...]:
    _, frames = parse(phrasebank_text)
    names = {n.lower() for n in _EXAMPLE_NAME.findall(phrasebank_text)} | {"et", "al"}
    patterns = []
    for frame in frames:
        if language not in frame.text:
            continue
        text = frame.text[language]
        # A frame of several sentences without alternatives is checked sentence by sentence, as answers are.
        for piece in ([text] if "{" in text else sentences(text)):
            if pattern := _compile(piece, language, names):
                patterns.append(pattern)
    return tuple(patterns)


def _compile(frame: str, language: str, names: set[str]) -> _Pattern | None:
    def fixed(part: str) -> tuple[str, ...]:
        part = _ELLIPSIS_SUFFIX.sub("…", part)  # a case ending on an open slot, as in Turkish "...'i belirlemek"
        if language in _OWN_WORK:
            part = _OWN_WORK[language].sub("X", part)
        return tuple(w for w in _words(part, language) if not _SLOT.match(w) and w not in names)

    groups = []
    for part in re.split(r"(\{[^{}]*\})", frame):
        if part.startswith("{") and part.endswith("}"):
            groups.append(tuple(fixed(alternative) for alternative in part[1:-1].split(" | ")))
        elif words := fixed(part):
            groups.append((words,))
    groups = [group for group in groups if any(group)]
    if not groups:
        return None
    # The shortest choice of alternatives bounds how few frame words a passing sentence can share with the frame.
    shortest = sum(min(len(a) for a in group) for group in groups)
    least = max(1, min(MIN_MATCHED, shortest))
    return _Pattern(tuple(groups), least, Counter(w for group in groups for a in group for w in a))


def _follows(sentence: str, patterns: tuple[_Pattern, ...], language: str) -> bool:
    words = _words(sentence, language)
    counts = Counter(words)
    return any(sum((p.words & counts).values()) >= p.least and _score(p, words) >= 0 for p in patterns)


def _score(pattern: _Pattern, words: list[str]) -> float:
    """Frame words matched in order minus MIN_COVERAGE of the fixed words of the alternatives chosen to match them.

    A grouped longest common subsequence: the cost is charged per chosen alternative, so a frame whose shortest
    alternative has almost no fixed words cannot pass on one common word.
    """
    best = [0.0] * (len(words) + 1)
    for group in pattern.groups:
        merged = [-math.inf] * (len(words) + 1)
        for alternative in group:
            row_above = best
            for token in alternative:
                row = [row_above[0]]
                for j, word in enumerate(words, 1):
                    row.append(max(row[j - 1], row_above[j], row_above[j - 1] + (token == word)))
                row_above = row
            cost = MIN_COVERAGE * len(alternative)
            merged = [max(a, b - cost) for a, b in zip(merged, row_above)]
        best = merged
    return best[-1] + 1e-9

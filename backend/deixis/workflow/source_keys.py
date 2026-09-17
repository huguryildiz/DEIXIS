"""Short author–year keys for works, such as "Nakano13" (D59)."""

from __future__ import annotations

import re
import unicodedata
from itertools import product

MAX_NAME = 10
_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "das", "du", "la", "le", "ter", "ten", "al", "el", "bin", "ibn"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_TITLE_STOPWORDS = {"a", "an", "the", "on", "of", "and", "in", "for", "to", "with", "towards", "toward", "via", "from", "by", "at"}
_FOLDS = str.maketrans({"ı": "i", "İ": "I", "ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "þ": "th"})


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.translate(_FOLDS))
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _join(words: list[str]) -> str:
    parts = []
    for word in words:
        letters = re.sub(r"[^A-Za-z]", "", _ascii(word))
        if letters:
            parts.append(letters.capitalize() if letters.isupper() and len(letters) > 1 else letters[0].upper() + letters[1:])
    return "".join(parts)[:MAX_NAME]


def family_name(author: str) -> str:
    """The family name of "Family, Given" or "Given Family", without particles or suffixes; hyphenated parts are joined."""
    author = author.strip()
    if "," in author:
        family = author.split(",")[0].split()
    else:
        tokens = [t for t in author.split() if t.strip(".").casefold() not in _SUFFIXES]
        family = tokens[-1:] if tokens else []
    words = [w for part in family for w in re.split(r"[-‐]", part)]
    kept = [w for w in words if w.casefold() not in _PARTICLES]
    return _join(kept or words)


def key_stem(authors: list[str], title: str | None, year: int | None) -> tuple[str, str]:
    """The key before any collision suffix, and whether it came from an author or the title."""
    name = next((n for n in (family_name(a) for a in authors if a.strip()) if n), "")
    basis = "author"
    if not name:
        basis = "title"
        words = [w for w in re.split(r"\s+", title or "") if re.sub(r"[^A-Za-z]", "", _ascii(w))]
        significant = [w for w in words if re.sub(r"[^a-z]", "", _ascii(w).casefold()) not in _TITLE_STOPWORDS]
        name = _join((significant or words)[:1]) or "Source"
    return f"{name}{f'{year % 100:02d}' if year else 'nd'}", basis


def suffixes():
    """"", then b, c, … z, then aa, ab, …: the first work keeps the bare key, so no key changes when another work arrives."""
    yield ""
    yield from "bcdefghijklmnopqrstuvwxyz"
    yield from ("".join(pair) for pair in product("abcdefghijklmnopqrstuvwxyz", repeat=2))

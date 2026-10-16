"""Author–year–title keys for works, such as "zeng2022multiparty" (D59, D38)."""

from __future__ import annotations

import re
import unicodedata
from itertools import product

from deixis.storage.db import transaction

MAX_NAME = 20
_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "das", "du", "la", "le", "ter", "ten", "al", "el", "bin", "ibn"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_TITLE_STOPWORDS = {"a", "an", "the", "on", "of", "and", "in", "for", "to", "with", "towards", "toward", "via", "from", "by", "at"}
_FOLDS = str.maketrans({"ı": "i", "İ": "I", "ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "þ": "th"})


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.translate(_FOLDS))
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _join(words: list[str]) -> str:
    """ASCII letters of the words, lower case, run together."""
    return "".join(re.sub(r"[^A-Za-z]", "", _ascii(word)) for word in words).lower()[:MAX_NAME]


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


def title_word(title: str | None) -> str:
    """The title's first word that is not a stopword, in lower-case ASCII letters; "" when it has none."""
    words = [w for w in (_join([w]) for w in re.split(r"[\s/:]+", title or "")) if w]
    return next((w for w in words if w not in _TITLE_STOPWORDS), words[0] if words else "")


def key_stem(authors: list[str], title: str | None, year: int | None) -> tuple[str, str]:
    """The key before any collision suffix, and whether it came from an author or the title: first author's family
    name, four-digit year ("nd" without one) and the title's first significant word, as in "zeng2022multiparty". A work
    with no author starts with the title word instead, as in "multiparty2022"."""
    name = next((n for n in (family_name(a) for a in authors if a.strip()) if n), "")
    word = title_word(title)
    when = f"{year:04d}" if year else "nd"
    if name:
        return f"{name}{when}{word}", "author"
    return f"{word or 'source'}{when}", "title"


def suffixes():
    """"", then b, c, … z, then aa, ab, …: the first work keeps the bare key, so no key changes when another work arrives."""
    yield ""
    yield from "bcdefghijklmnopqrstuvwxyz"
    yield from ("".join(pair) for pair in product("abcdefghijklmnopqrstuvwxyz", repeat=2))


def assign_missing(store) -> int:
    """Give every work without a key its key, oldest work first, so the first of colliding works keeps the bare key.
    Runs at startup; after migration 0013 cleared the old short keys it gives every work its D38 key once."""
    rows = store.conn.execute("SELECT id FROM works WHERE source_key IS NULL ORDER BY created_at, rowid").fetchall()
    with transaction(store.conn):
        for (work_id,) in rows:
            store._assign_source_key(work_id)
    return len(rows)

"""Text mentions identify candidates; they do not establish a relation.

Reference-list passages are searched too. Numbered citations alone are missed.
Short titles with fewer than five significant tokens are not searched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from deixis.workflow.source_keys import _ascii, _PARTICLES, _SUFFIXES, _TITLE_STOPWORDS

NORMALIZATION_VERSION = "lineage-mentions-v1"
MENTION_TEXT_DEFINITION = (
    "source_keys._ascii, casefold, split on runs of non-alphanumeric characters; "
    "tokens joined by one space; gap counts characters strictly between surname end and year start"
)
GAP_CHARS = 60
MIN_TITLE_TOKENS = 5
MAX_MENTION_PASSAGES = 3


@dataclass(frozen=True)
class PassageText:
    passage_id: str
    kind: str
    text: str
    physical_page: int | None


@dataclass(frozen=True)
class PreparedPassage:
    passage_id: str
    physical_page: int | None
    tokens: tuple[str, ...]
    normalized_text: str
    token_starts: tuple[int, ...]
    significant_tokens: tuple[str, ...]


@dataclass(frozen=True)
class MentionTarget:
    source_version_id: str
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    years: tuple[int, ...] = ()


@dataclass(frozen=True)
class MentionHit:
    passage_id: str
    surname_year: int
    title_fragment: int
    count: int
    physical_page: int | None


@dataclass(frozen=True)
class Mention:
    from_source_version_id: str
    total: int
    hits: tuple[MentionHit, ...]
    basis: tuple[str, ...]
    mention_passage_ids: tuple[str, ...]


def normalize_tokens(text: str) -> tuple[str, ...]:
    """One normalization for passages, surnames and titles; underscores separate tokens."""
    return tuple(re.findall(r"[^\W_]+", _ascii(text).casefold()))


def surname_tokens(author: str) -> tuple[str, ...]:
    """Mirror family_name's selection and particle/suffix rules without truncation."""
    if "," in author:
        family = author.split(",", 1)[0].split()
    else:
        words = [w for w in author.split() if w.strip(".").casefold() not in _SUFFIXES]
        family = words[-1:]
    words = [w for part in family for w in re.split(r"[-‐]", part)]
    kept = [w for w in words if w.casefold() not in _PARTICLES]
    return normalize_tokens(" ".join(kept or words))


def prepare_passages(passages: Iterable[PassageText]) -> tuple[PreparedPassage, ...]:
    """Normalize each passage once, outside the loop over earlier records."""
    prepared = []
    for passage in passages:
        tokens = normalize_tokens(passage.text)
        starts = []
        offset = 0
        for token in tokens:
            starts.append(offset)
            offset += len(token) + 1
        prepared.append(PreparedPassage(
            passage.passage_id, passage.physical_page, tokens, " ".join(tokens),
            tuple(starts), tuple(t for t in tokens if t not in _TITLE_STOPWORDS),
        ))
    return tuple(prepared)


def _surname_hits(passage: PreparedPassage, surname: tuple[str, ...], years: frozenset[int]) -> int:
    if not surname or not years:
        return 0
    hits = 0
    width = len(surname)
    for i in range(len(passage.tokens) - width + 1):
        if passage.tokens[i:i + width] != surname:
            continue
        end = passage.token_starts[i + width - 1] + len(passage.tokens[i + width - 1])
        for j in range(i + width, len(passage.tokens)):
            if passage.token_starts[j] - end > GAP_CHARS:
                break
            token = passage.tokens[j]
            if re.fullmatch(r"[0-9]{4}[a-z]?", token) and int(token[:4]) in years:
                hits += 1
                break  # One hit per surname occurrence, even with several matching years.
    return hits


def _title_hits(tokens: tuple[str, ...], title_grams: dict[tuple[str, ...], tuple[int, ...]]) -> int:
    """Count maximal runs of consecutive matching 5-grams, rather than windows."""
    runs: dict[int, tuple[int, int]] = {}
    spans = []
    for i in range(len(tokens) - MIN_TITLE_TOKENS + 1):
        next_runs = {}
        for j in title_grams.get(tokens[i:i + MIN_TITLE_TOKENS], ()):
            diagonal = j - i
            start, _ = runs.get(diagonal, (i, i))
            next_runs[diagonal] = (start, i + MIN_TITLE_TOKENS)
        spans.extend(span for diagonal, span in runs.items() if diagonal not in next_runs)
        runs = next_runs
    spans.extend(runs.values())
    # Repeated title tokens can locate the same span at several title offsets.
    # Contained spans are not maximal; crossing spans remain distinct runs.
    count = 0
    furthest_end = -1
    for start, end in sorted(set(spans), key=lambda span: (span[0], -span[1])):
        if end > furthest_end:
            count += 1
            furthest_end = end
    return count


def find_mentions(prepared_passages: Iterable[PreparedPassage], target: MentionTarget) -> Mention | None:
    surname = next((s for a in target.authors if (s := surname_tokens(a))), ())
    years = frozenset(y for y in (target.year, *target.years) if y is not None)
    title = tuple(t for t in normalize_tokens(target.title or "") if t not in _TITLE_STOPWORDS)
    grams: dict[tuple[str, ...], tuple[int, ...]] = {}
    for i in range(len(title) - MIN_TITLE_TOKENS + 1):
        gram = title[i:i + MIN_TITLE_TOKENS]
        grams[gram] = (*grams.get(gram, ()), i)
    hits = []
    for passage in prepared_passages:
        surname_year = _surname_hits(passage, surname, years)
        title_fragment = _title_hits(passage.significant_tokens, grams) if grams else 0
        if surname_year or title_fragment:
            hits.append(MentionHit(passage.passage_id, surname_year, title_fragment,
                                   surname_year + title_fragment, passage.physical_page))
    if not hits:
        return None
    hits.sort(key=lambda h: (-h.count, h.physical_page is not None,
                             h.physical_page if h.physical_page is not None else 0, h.passage_id))
    basis = tuple(name for name in ("surname_year", "title_fragment")
                  if any(getattr(hit, name) for hit in hits))
    return Mention(target.source_version_id, sum(h.count for h in hits), tuple(hits), basis,
                   tuple(h.passage_id for h in hits[:MAX_MENTION_PASSAGES]))


def mention_rules() -> dict:
    """JSON-serialisable rules for the caller's frozen run plan."""
    return {"normalization_version": NORMALIZATION_VERSION, "text_definition": MENTION_TEXT_DEFINITION,
            "gap_chars": GAP_CHARS, "min_title_tokens": MIN_TITLE_TOKENS,
            "max_mention_passages": MAX_MENTION_PASSAGES, "year_position": "after_surname",
            "stopwords": sorted(_TITLE_STOPWORDS)}

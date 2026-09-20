"""What two records are to each other, decided from their own fields alone (SW6).

`classify_pair` is pure: it reads no database, calls no model and asks no embedding, so the same two records always
give the same verdict and a stored link can be re-derived from what was stored. The thresholds and the kind lists come
from one measurement on one topic (`.local/quantum-dedup-2026-09-18/`); they are repository and notice names, never
words of a subject.

Only a preprint with its published record, or two preprints, may merge into one work. Two published records never do:
a conference paper and its journal article are linked as `extended_version` and both are kept (SW6.5).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

TITLE_MERGE = 0.85  # SW6.3: title trigram Jaccard an automatic merge needs
ABSTRACT_MERGE = 0.8  # SW6.3, SW6.6
TITLE_RELATED = 0.6  # SW6.6: below this a pair is not examined at all
AUTHOR_OVERLAP = 0.5  # share of the shorter surname list that must match (the measured rule)
MAX_YEAR_GAP = 5  # SW6.7: a wider gap blocks an automatic merge, it does not decide anything on its own
MIN_TITLE_CHARS = 12  # as store.MIN_TITLE_KEY_CHARS: "Editorial" says too little to link two records by
THRESHOLDS = {"title_merge": TITLE_MERGE, "abstract_merge": ABSTRACT_MERGE, "title_related": TITLE_RELATED,
              "author_overlap": AUTHOR_OVERLAP, "max_year_gap": MAX_YEAR_GAP}

PREPRINT_DOI_PREFIXES = ("10.48550/", "10.21203/", "10.36227/", "10.1101/", "10.20944/", "10.2139/")
ARTIFACT_DOI_PREFIXES = ("10.5281/", "10.6084/", "10.24433/", "10.4121/", "10.13140/", "10.17632/")
# Longest first: "publisher correction" must be read before "correction".
NOTICE_TITLE_PREFIXES: dict[str, str] = {
    "publisher correction": "correction", "author correction": "correction", "corrigendum": "correction",
    "correction": "correction", "erratum": "correction",
    "withdrawal": "withdrawal", "withdrawn": "withdrawal",
    "retraction": "retraction", "retracted": "retraction",
}
ARTIFACT_TITLE_PREFIXES = ("data supporting",)
PLACEHOLDER_AUTHORS = ("anonymous", "unknown")

ARXIV_DOI_PREFIX = "10.48550/arxiv."  # the same three conditions as store.is_preprint, which cannot be imported here
SUBMITTED_LABELS = ("submittedVersion",)
_MARKUP = re.compile(r"<[^>]+>|\$[^$]*\$")
_WORD = re.compile(r"[^\W_]+")
# A notice prefix counts at the start of the title and only where the rest reads as a reference to another paper:
# "Correction to: X", "Correction: X" or the bare word. "Correction of errors in X" is an ordinary paper.
_NOTICE_TAIL = re.compile(r"^\s*(?::|-|–|—|to\b|$)")


def normalize_text(text: str | None) -> str:
    """Accent-free, markup-free, lower-case words joined by single spaces.

    Latin-script text normalises exactly as the measurement's `norm` did; unlike it, letters of other scripts are kept
    instead of dropped, so a title in one is not silently emptied.
    """
    folded = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).casefold()
    return " ".join(_WORD.findall(_MARKUP.sub(" ", folded)))


def trigrams(text: str) -> frozenset[str]:
    """Character trigrams of an already normalised string, unpadded; a text under three characters has none."""
    return frozenset(text[i:i + 3] for i in range(len(text) - 2))


def similarity(a: str | None, b: str | None) -> float | None:
    """Trigram Jaccard of two texts, or None when either normalises to nothing and there is nothing to compare."""
    first, second = normalize_text(a), normalize_text(b)
    if not first or not second:
        return None
    return _jaccard(trigrams(first), trigrams(second))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def notice_type(title: str | None) -> str | None:
    """`correction`, `withdrawal` or `retraction` when the title opens by naming another paper, else None.

    This reads the title before `normalize_text`, because the colon of "Publisher Correction: …" is what separates a
    notice from a paper about corrections, and normalisation drops it.
    """
    head = _MARKUP.sub(" ", "".join(
        c for c in unicodedata.normalize("NFKD", title or "") if not unicodedata.combining(c)).casefold()).strip()
    for prefix, kind in NOTICE_TITLE_PREFIXES.items():
        rest = head[len(prefix):]
        if head.startswith(prefix) and (not rest or not rest[0].isalnum()) and _NOTICE_TAIL.match(rest):
            return kind
    return None


def record_kind(record: dict) -> str:
    """preprint | published | artifact | notice | unknown, from the DOI prefix and the title prefix (SW6.2)."""
    doi, title = record.get("doi") or "", normalize_text(record.get("title"))
    label = record.get("version_label") or ""
    if notice_type(record.get("title")):
        return "notice"
    if doi.startswith(ARTIFACT_DOI_PREFIXES) or title.startswith(ARTIFACT_TITLE_PREFIXES):
        return "artifact"
    if doi.startswith(PREPRINT_DOI_PREFIXES) or label in SUBMITTED_LABELS or label.startswith("arXiv"):
        return "preprint"
    return "published" if doi else "unknown"


def comparable_title(record: dict) -> str:
    """The normalised title without the prefix that names the record a notice or an artifact.

    A notice and its artifact are compared to the paper by what is left after the prefix, so "Publisher Correction: X"
    is compared to X itself. Every other record's comparable title is just its normalised title.
    """
    title = normalize_text(record.get("title"))
    kind = record_kind(record)
    if kind == "notice":
        for prefix in NOTICE_TITLE_PREFIXES:
            if title.startswith(prefix):
                rest = title[len(prefix):].strip()
                return rest[3:].strip() if rest.startswith("to ") else rest
    elif kind == "artifact":
        for prefix in ARTIFACT_TITLE_PREFIXES:
            if title.startswith(prefix):
                return title[len(prefix):].strip()
    return title


def surnames(authors: list[str]) -> list[str]:
    """Surnames of an author list, reading "Last, First" as well as "First Last"; placeholder names are left out."""
    return _surnames(authors, reverse=False)


def _surnames(authors: list[str], reverse: bool) -> list[str]:
    """Surnames read the other way round when `reverse`: the first word of a comma-less name is the family name."""
    found = []
    for name in authors or []:
        if "," in name:
            head, tail = name.split(",", 1)
            part = (tail.split() or [""])[-1] if reverse else head
        else:
            words = name.split()
            if not words:
                continue
            part = words[0] if reverse else words[-1]
        surname = normalize_text(part).replace(" ", "")
        if surname and surname not in PLACEHOLDER_AUTHORS:
            found.append(surname)
    return found


def author_agreement(a: list[str], b: list[str]) -> str:
    """agree | differ | unknown for two author lists (SW6.8).

    Unknown is not the same as different: an empty or placeholder list says nothing, so the pair stays suspected
    instead of being thrown away. Reversed name order is tried on either side, so the answer does not depend on which
    record was passed first. D48's stricter "the first author must be the same" is not applied here; this is the rule
    the measurement supports, and D48 keeps its own rule for `legacy` researches.
    """
    first, second = set(surnames(a)), set(surnames(b))
    if not first or not second:
        return "unknown"
    if _overlaps(first, second):
        return "agree"
    if _overlaps(set(_surnames(a, reverse=True)), second) or _overlaps(first, set(_surnames(b, reverse=True))):
        return "agree"
    return "differ"


def _overlaps(a: set[str], b: set[str]) -> bool:
    return bool(a) and bool(b) and len(a & b) / min(len(a), len(b)) >= AUTHOR_OVERLAP


@dataclass(frozen=True)
class Verdict:
    link_kind: str  # same_work | extended_version | probable_version | related_suspected | artifact_of | notice_of
    rule: str
    merge: bool
    title_similarity: float | None
    abstract_similarity: float | None
    author_agreement: str
    year_gap: int | None
    parent: str | None  # "a" or "b": the paper an artifact or a notice belongs to


def classify_pair(a: dict, b: dict, *, names_published_doi: bool = False) -> Verdict | None:
    """What the two records are to each other, or None when the pair is not worth storing.

    Each record carries `doi`, `title`, `authors`, `year`, `abstract`, `version_label` and `publication_type`; an
    absent field is None. The verdict is symmetric: swapping the two records changes only `parent`.
    """
    kinds = (record_kind(a), record_kind(b))
    titles = (comparable_title(a), comparable_title(b))
    title_similarity = _jaccard(trigrams(titles[0]), trigrams(titles[1])) if titles[0] and titles[1] else None
    agreement = author_agreement(a.get("authors") or [], b.get("authors") or [])
    year_gap = abs(a["year"] - b["year"]) if a.get("year") and b.get("year") else None
    abstract_similarity = similarity(a.get("abstract"), b.get("abstract"))

    def verdict(link_kind: str, rule: str, merge: bool = False, parent: str | None = None) -> Verdict:
        return Verdict(link_kind, rule, merge, title_similarity, abstract_similarity, agreement, year_gap, parent)

    attached = {"notice", "artifact"}
    if kinds[0] in attached and kinds[1] in attached:  # 1: a notice of an artifact is not a link this product keeps
        return None
    if kinds[0] in attached or kinds[1] in attached:  # 2, 3, 4
        side = 0 if kinds[0] in attached else 1
        parent = "b" if side == 0 else "a"
        if title_similarity is None or title_similarity < TITLE_MERGE:
            return None
        if kinds[side] == "notice" and agreement != "differ":
            return verdict("notice_of", notice_type((a, b)[side].get("title")), parent=parent)
        if kinds[side] == "artifact" and agreement == "agree":
            return verdict("artifact_of", "artifact_same_title", parent=parent)
        return None
    if names_published_doi and set(kinds) == {"preprint", "published"}:  # 5: the author named the link themselves
        return verdict("same_work", "preprint_names_published_doi", merge=True)
    if title_similarity is None or title_similarity < TITLE_RELATED:  # 6
        return None
    if min(len(titles[0]), len(titles[1])) < MIN_TITLE_CHARS:  # 6
        return None
    if agreement == "differ":  # 7
        return None
    if agreement == "unknown":  # 8
        return verdict("related_suspected", "authors_unknown")
    if kinds == ("published", "published"):  # 9, 10: two published records never become one work (SW6.5)
        if title_similarity >= TITLE_MERGE:
            return verdict("extended_version", "two_published_similar_title")
        return verdict("related_suspected", "two_published")
    if "unknown" in kinds:  # 11
        return verdict("related_suspected", "kind_unknown")
    # 12-16: only preprint+published and preprint+preprint reach here, so only these may merge.
    both_abstracts = abstract_similarity is not None
    would_merge = ((title_similarity >= TITLE_MERGE and both_abstracts and abstract_similarity >= ABSTRACT_MERGE)
                   or (not both_abstracts and titles[0] == titles[1]))
    if would_merge and year_gap is not None and year_gap > MAX_YEAR_GAP:  # 12
        return verdict("related_suspected", "year_gap_blocks_merge")
    if title_similarity >= TITLE_MERGE and both_abstracts and abstract_similarity >= ABSTRACT_MERGE:  # 13
        return verdict("same_work", "title_authors_abstract", merge=True)
    if not both_abstracts and titles[0] == titles[1]:  # 14
        return verdict("same_work", "identical_title_authors", merge=True)
    if both_abstracts and abstract_similarity >= ABSTRACT_MERGE and title_similarity < TITLE_MERGE:  # 15
        return verdict("probable_version", "abstract_agrees_title_differs")
    return verdict("related_suspected", "similar_title_same_authors")  # 16

"""The time span a research searches in, read from the person's own question and frozen into the run.

The design asks for the person's explicit date condition, and a historical benchmark's year cutoff, to reach every
provider that supports one **before** the search, with the later filtering recorded wherever a provider supports
none. Filtering afterwards cannot give back the places those records took on the first page, which is the whole
reason the condition has to travel with the request.

Three rules hold this module together:

- **Code reads the condition, no model does.** The words a search is bounded by are the person's own, as the search
  words themselves are. What is recognised is the table below and nothing else, so what a question is read for can
  be checked rather than guessed at.
- **A bound names a year, and the named year is inside it.** The providers' routes agree only at year granularity:
  OpenAlex's keyword route takes publication dates, its semantic route only `publication_year`, Semantic Scholar's
  bulk search a year range and PubMed a date range, so a bound finer than a year could not be applied equally to
  all of them and a question that states one stops the run instead (`day_precision_not_supported`). Where a phrase
  could mean the named year or the one after it ("after 2019", "2019 sonrası"), the named year is **included**: a
  boundary year wrongly left out is a paper lost for good, while one wrongly let in is a record the ranking sorts.
- **Recognised but unreadable stops the run.** A question that clearly states a date condition the table cannot
  resolve raises `Unreadable`, and the run is never created: a search that quietly ignored the condition would
  report a scope it did not apply. A date with no condition word around it is not a date condition — a question
  can be *about* a month or a year — so it reads as no condition at all.
"""

from __future__ import annotations

import re
from typing import Any

RULE = "date_scope_v1"
# The years a question can plausibly bound a literature search by. Anything outside is not read as a year, and
# these two stand for the open side of a one-sided bound where a provider's own route insists on both.
EARLIEST_YEAR = 1500
LATEST_YEAR = 2200
# What `read` recognises, by name, so a question's reading can be checked against the words it was read from.
RECOGNISED = (
    "since/from/after/onwards + a date, and their Turkish forms (beri, itibaren, sonra, sonrası)",
    "before/until/up to + a date, and their Turkish forms (önce, öncesi, kadar)",
    "a span written with a dash, `to`, `through` or `between … and …` (2019-2024, between 2019 and 2024)",
    "last/past N years, and `son N yıl`",
)

_YEAR = r"(?:1[5-9]\d\d|20\d\d|21\d\d)"
_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
          r"|ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim"
          r"|kasım|kasim|aralık|aralik")
# A date as a question writes one: a bare year, a month beside a year, or a numbered date. Read as a whole so a
# condition finer than a year is recognised rather than silently rounded to the year it names.
_DATE = (rf"(?:{_MONTH})\s+{_YEAR}"
         rf"|{_YEAR}\s+(?:{_MONTH})"
         rf"|{_YEAR}[-/.]\d{{1,3}}(?:[-/.]\d{{1,3}})?(?!\d)"
         rf"|{_YEAR}")
# The Turkish year word and case suffix a person may write between the year and the condition word: "2020
# yılından itibaren", "2020'den sonra", "2020 sonrası", "2015 yılına kadar".
_TR_LINK = r"(?:\s*y[ıi]l\w*)?(?:['’]?[td][ae]n)?"


def _condition(pattern: str) -> re.Pattern[str]:
    """One condition phrasing, with its date parts as groups 1 and (for a span) 2."""
    return re.compile(pattern, re.IGNORECASE)


_LOWER = (
    _condition(rf"(?<!\w)(?:since|from|after|starting(?:\s+(?:in|from))?)\s+({_DATE})(?!\w)"),
    _condition(rf"(?<!\w)({_DATE})\s*(?:onwards|or\s+later|and\s+later)(?!\w)"),
    # Turkish writes the date first and the condition after it.
    _condition(rf"(?<!\w)({_DATE}){_TR_LINK}\s*(?:sonras[ıi]\w*|sonra|beri|itibaren)(?!\w)"),
)
_UPPER = (
    _condition(rf"(?<!\w)(?:before|until|till|up\s+to|no\s+later\s+than)\s+({_DATE})(?!\w)"),
    _condition(rf"(?<!\w)({_DATE})\s*(?:or\s+earlier|and\s+earlier)(?!\w)"),
    _condition(rf"(?<!\w)({_DATE}){_TR_LINK}\s*(?:öncesi\w*|oncesi\w*|önce|once|kadar)(?!\w)"),
)
_SPAN = (
    _condition(rf"(?<!\w)between\s+({_DATE})\s+and\s+({_DATE})(?!\w)"),
    _condition(rf"(?<!\w)(?:from\s+)?({_DATE})\s*(?:[-–—]|to|through|ile|ila)\s*({_DATE})(?!\w)"),
)
_RECENT = _condition(r"(?<!\w)(?:last|past|previous)\s+(\d{1,2})\s+years(?!\w)"
                     r"|(?<!\w)son\s+(\d{1,2})\s+y[ıi]l(?!\w)")
# A condition word that needs a date to mean anything. Seen without one, the question states a condition this
# table cannot resolve, so the run stops instead of searching unbounded.
_BARE_CONDITION = _condition(r"(?<!\w)(?:since|onwards|recent\s+years|in\s+recent\s+years)(?!\w)"
                             r"|(?<!\w)son\s+y[ıi]llarda(?!\w)")
# A condition word beside a four-digit number the table did not read as a year. Read last, over the words no
# pattern above claimed, so a question that states a second condition this module cannot resolve is refused
# instead of searched on the first one alone. Exactly four digits, so "after 3 rounds" is not read as a year.
_LOOSE = (
    _condition(r"(?<!\w)(?:since|from|after|before|until|till|up\s+to|no\s+later\s+than"
               r"|starting(?:\s+(?:in|from))?)\s+(\d{4})(?!\d)"),
    _condition(r"(?<!\w)(\d{4})(?:\s*y[ıi]l\w*)?(?:['’]?[td][ae]n)?"
               r"\s*(?:sonras[ıi]\w*|sonra|beri|itibaren|öncesi\w*|oncesi\w*|önce|once|kadar)(?!\w)"),
)
_YEAR_IN = re.compile(_YEAR)
# What makes a date finer than a year: a month name, or a separator and a number after the year. A malformed one
# ("2020-13-01") is finer too, so it is refused rather than quietly read as the year it starts with.
_FINER = re.compile(rf"(?:{_MONTH})|[-/.]\d", re.IGNORECASE)


class Unreadable(Exception):
    """The question states a date condition `read` cannot resolve. `reason` names which, `basis` quotes the words."""

    def __init__(self, reason: str, basis: str):
        super().__init__(reason)
        self.reason = reason
        self.basis = basis


def read(question: str, this_year: int) -> dict[str, Any] | None:
    """The date scope this question states, or None when it states none; `Unreadable` when it states one unreadably.

    `this_year` is the year the run starts in, so a relative phrase ("last five years") freezes to an exact span
    and a resumed run searches the same years it was queued with.
    """
    text = question or ""
    # Every condition the question states, not the first one found: a question that names a span and a cutoff
    # states both, and searching only one of them would search years it asked to leave out. The bounds are
    # intersected, so each condition holds, and a pair that leaves no year stops the run.
    lowers: list[int] = []
    uppers: list[int] = []
    basis: list[str] = []
    # Where a phrase has already been read, another pattern reading part of the same words says nothing new
    # ("from 2018 onwards" is one condition, not two), so an overlapping match is left out of the record.
    read_already: list[tuple[int, int]] = []

    def fresh(found: re.Match[str]) -> bool:
        start, end = found.span()
        if any(start < done_end and done_start < end for done_start, done_end in read_already):
            return False
        read_already.append((start, end))
        return True

    for pattern in _SPAN:
        for found in pattern.finditer(text):
            if not fresh(found):
                continue
            words = found.group(0).strip()
            first, second = _year_of(found.group(1), words), _year_of(found.group(2), words)
            if not _plausible(first, this_year) or not _plausible(second, this_year) or first > second:
                raise Unreadable("year_span_not_read", words)
            lowers.append(first)
            uppers.append(second)
            basis.append(words)
    for recent in _RECENT.finditer(text):
        if not fresh(recent):
            continue
        years = int(recent.group(1) or recent.group(2))
        if years < 1:
            raise Unreadable("year_count_not_read", recent.group(0).strip())
        # Both sides, so the span is exact: "the last five years" ends with the year the run starts in and asks no
        # provider for years that have not happened.
        lowers.append(this_year - years + 1)
        uppers.append(this_year)
        basis.append(recent.group(0).strip())
    for patterns, side in ((_LOWER, lowers), (_UPPER, uppers)):
        for pattern in patterns:
            for found in pattern.finditer(text):
                if not fresh(found):
                    continue
                words = found.group(0).strip()
                year = _year_of(found.group(1), words)
                if not _plausible(year, this_year):
                    raise Unreadable("year_not_plausible", words)
                side.append(year)
                basis.append(words)
    # A condition the table could not read stops the run whether or not another condition was read: a question
    # that says "since 2020 and before 1200" states two conditions, and searching one of them searches years it
    # asked to leave out.
    for pattern in _LOOSE:
        for found in pattern.finditer(text):
            if fresh(found):
                raise Unreadable("year_not_plausible", found.group(0).strip())
    if not lowers and not uppers:
        bare = _BARE_CONDITION.search(text)
        if bare is not None:
            raise Unreadable("no_year_named", bare.group(0).strip())
        return None
    lower = max(lowers) if lowers else None
    upper = min(uppers) if uppers else None
    spoken = "; ".join(dict.fromkeys(basis))
    if lower is not None and upper is not None and lower > upper:
        raise Unreadable("bounds_cross", spoken)
    return _scope(lower, upper, spoken)


def _year_of(date: str, basis: str) -> int:
    """The year this date names, or `Unreadable` where the condition is finer than a year.

    A month or a day cannot be applied equally to the routes a run searches, and widening it to the whole year
    would search outside what was asked, so a finer condition stops the run instead.
    """
    if _FINER.search(date):
        raise Unreadable("day_precision_not_supported", basis)
    found = _YEAR_IN.search(date)
    if found is None:
        raise Unreadable("year_span_not_read", basis)
    return int(found.group(0))


def _plausible(year: int, this_year: int) -> bool:
    """Whether this number can bound a literature search: a published year, or next year for work in press."""
    return EARLIEST_YEAR <= year <= this_year + 1


def _scope(from_year: int | None, to_year: int | None, basis: str) -> dict[str, Any]:
    return {"rule": RULE, "from_year": from_year, "to_year": to_year, "basis": basis, "origin": "question"}


def given(from_year: int | None, to_year: int | None) -> dict[str, Any]:
    """A scope a measurement supplied with the run rather than one read from the question (its own `origin`).

    A frozen benchmark question cannot carry the condition in its own words — its text is hashed — so the year
    cutoff of a historical sample arrives with the run instead.
    """
    if from_year is None and to_year is None:
        raise ValueError("a date scope names a lower bound, an upper bound, or both")
    for year in (from_year, to_year):
        if year is not None and not EARLIEST_YEAR <= year <= LATEST_YEAR:
            raise ValueError(f"a date scope's years run from {EARLIEST_YEAR} to {LATEST_YEAR}")
    if from_year is not None and to_year is not None and from_year > to_year:
        raise ValueError("a date scope's lower bound is not above its upper bound")
    return {"rule": RULE, "from_year": from_year, "to_year": to_year,
            "basis": _spoken(from_year, to_year), "origin": "given"}


def _spoken(from_year: int | None, to_year: int | None) -> str:
    if from_year is not None and to_year is not None:
        return f"{from_year}-{to_year}"
    return f"{from_year} onwards" if from_year is not None else f"up to {to_year}"


def openalex_filter(scope: dict[str, Any] | None) -> str | None:
    """The bound for OpenAlex's keyword route, in the convenience filters its own documentation gives.

    `from_publication_date` / `to_publication_date` take full dates (OpenAlex works filter documentation, read
    10 Nov 2026), so a year bound becomes that year's first and last day. Both bounds include their named year.
    """
    if not scope:
        return None
    parts = []
    if scope["from_year"] is not None:
        parts.append(f"from_publication_date:{scope['from_year']}-01-01")
    if scope["to_year"] is not None:
        parts.append(f"to_publication_date:{scope['to_year']}-12-31")
    return ",".join(parts) or None


def openalex_semantic_filter(scope: dict[str, Any] | None) -> str | None:
    """The same bound for OpenAlex's semantic route, which takes `publication_year` and not the date filters.

    OpenAlex's semantic-search documentation (read 10 Nov 2026) says the route works with 17 filters,
    `publication_year` among them, and its own example writes an inequality: `filter=publication_year:>2020`. The
    years are moved by one so a strict inequality spans the same years the keyword route's dates do, which is what
    makes the two routes searchable on one scope.
    """
    if not scope:
        return None
    parts = []
    if scope["from_year"] is not None:
        parts.append(f"publication_year:>{scope['from_year'] - 1}")
    if scope["to_year"] is not None:
        parts.append(f"publication_year:<{scope['to_year'] + 1}")
    return ",".join(parts) or None


def year_range(scope: dict[str, Any] | None) -> str | None:
    """The bound as `<min>-<max>`, the one form Semantic Scholar's and PubMed's own routes agree on.

    Both sides are always written. Semantic Scholar refuses anything else ("'year' must be of the form
    <min>-<max>", answered 10 Nov 2026) and PubMed ignores a `mindate` sent without a `maxdate` (checked against
    its own ESearch the same day: 802 records unbounded, 802 with `mindate` alone, 360 with both). The open side
    of a one-sided bound is written as the earliest and latest year a literature search is read for.
    """
    if not scope:
        return None
    lower = scope["from_year"] if scope["from_year"] is not None else EARLIEST_YEAR
    upper = scope["to_year"] if scope["to_year"] is not None else LATEST_YEAR
    return f"{lower}-{upper}"



def with_filter(existing: str | None, added: str | None) -> str | None:
    """`existing` and `added` as one OpenAlex filter value; a comma is OpenAlex's own AND."""
    parts = [part for part in (existing, added) if part]
    return ",".join(parts) or None


# Which bound a connector's search takes, by the name it is declared under (`registry.Connector.date_filter`):
# `works_filter` is OpenAlex's own filter syntax, `year_range` the `<min>-<max>` string above.
def provider_bound(form: str | None, scope: dict[str, Any] | None, endpoint: str | None = None) -> dict[str, Any]:
    """The keyword argument a connector of this `form` takes for `scope`, or none where it takes no bound."""
    if not scope or form is None:
        return {}
    if form == "works_filter":
        value = openalex_semantic_filter(scope) if endpoint == "semantic" else openalex_filter(scope)
        return {"works_filter": value} if value else {}
    if form == "year_range":
        value = year_range(scope)
        return {"year_range": value} if value else {}
    raise ValueError(f"unknown date bound form {form!r}")


# The keyword argument names `provider_bound` can return, so a reader can tell a request's own bound from the
# other options it carries.
BOUND_KEYS = ("works_filter", "year_range")


# ---------------------------------------------------------------------------
# Whether a record the search found belongs to the years the run is bounded to.
#
# A route that takes no bound answers with records of every year, so the condition is applied here instead, after
# the search. Two rules hold it together. A record is judged by its **own** publication year, never by another
# version of its work: a work whose preprint is outside the span and whose published record is inside it enters
# through the record that is inside, which arrives as its own record. And a record whose year is not known is
# **outside** a bounded span, because a provider that applies the bound itself answers the same way — OpenAlex's
# `publication_year:>2019` returns no work without a year — so admitting it here would give a run whose provider
# could not filter candidates the bounded run cannot have.
IN_SPAN, BEFORE_SPAN, AFTER_SPAN, YEAR_UNKNOWN = "in_span", "before_span", "after_span", "year_unknown"
CLASSES = (IN_SPAN, BEFORE_SPAN, AFTER_SPAN, YEAR_UNKNOWN)


def year_class(scope: dict[str, Any] | None, year: int | None) -> str:
    """Where one record's own year stands to the span: the four classes are exhaustive and do not overlap."""
    if not scope:
        return IN_SPAN
    if year is None:
        return YEAR_UNKNOWN
    if scope["from_year"] is not None and year < scope["from_year"]:
        return BEFORE_SPAN
    if scope["to_year"] is not None and year > scope["to_year"]:
        return AFTER_SPAN
    return IN_SPAN


def eligible(scope: dict[str, Any] | None, year: int | None) -> bool:
    """Whether a record of this year may be a candidate of a run bounded to `scope`. No span: every record may."""
    return year_class(scope, year) == IN_SPAN

"""Verify Citations (V1 of 5): the result and status contract, and the code verdict that turns an assessment into a result.

A pair is one (citation occurrence, bibliography entry). Its status says how far the check went; a result exists only
for a pair whose status is `done`. The verdict is code, not the model: the model (V3) splits the cited sentence into at
most four parts and assesses each as `stated`, `partly` or `not_stated`, with quotes for the positive parts; the backend
locates each quote in a passage the step was given. `derive_result` reads only those assessments and the located-quote
booleans the backend computed. It fails closed: anything it cannot read as one of the three results raises
`CouldNotCheck`, and a positive part without a located quote is never turned into `not_stated`.

"Found" is a model assessment with a located passage, not scientific validation. "Not found in the given passages" holds
only for the passages the model was given; it does not mean the work does not say it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# Execution status of a pair. `planned`: waiting for its check; `done`: a valid assessment gave a result;
# `could_not_check`: repair ran out or the provider failed, no result; `out_of_cap`: beyond the pair limit;
# `no_text`: only metadata could be read, no model call; `unresolved`: the entry is missing or names no single record;
# `unrecognized`: the marker could not be read; `ambiguous`: an author-year marker names no single entry.
STATUSES = ("planned", "done", "could_not_check", "out_of_cap", "no_text", "unresolved", "unrecognized", "ambiguous")
RESULTS = ("found_whole", "found_partial", "not_found_in_given")
# What the assessment read: the selected K passages (with how many were not given), the abstract, or every passage.
DEPTHS = ("selected_passages", "abstract", "full_text")
# Shown beside the row; none of them changes the result.
FLAGS = ("title_mismatch", "retracted", "identity_unconfirmed")
ASSESSMENTS = ("stated", "partly", "not_stated")
POSITIVE = ("stated", "partly")

MAX_PARTS = 4
MAX_QUOTES_PER_PART = 3
MAX_QUOTES = 8


class CouldNotCheck(Exception):
    """The assessment cannot give a result; `reason` is stored with the pair's `could_not_check` status."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PartAssessment:
    """One claim part as the model assessed it, with one boolean per quote it gave: True when the backend located that
    quote in a passage the step was given (and no negation, number or comparison difference rejected it)."""

    assessment: str
    quotes_located: tuple[bool, ...] = ()


def derive_result(parts: Iterable[PartAssessment], covers_whole_sentence: Any) -> str:
    """The result of one valid assessment, else `CouldNotCheck`.

    - Every result needs `covers_whole_sentence` to be exactly True: without it no part list speaks for the whole
      sentence, and the plan sends such an output to repair.
    - A `stated`/`partly` part needs one to three quotes and at least one of them located; one without stays invalid
      (repair, then `could_not_check`), never `not_stated`. A `not_stated` part carries no quote.
    - `found_whole`: every part `stated`. `not_found_in_given`: every part `not_stated`. `found_partial`: at least one
      positive part, and at least one part `partly` or `not_stated`.
    """
    parts = list(parts)
    if not parts:
        raise CouldNotCheck("no_parts")
    if len(parts) > MAX_PARTS:
        raise CouldNotCheck("too_many_parts")
    for part in parts:
        if not isinstance(part, PartAssessment) or part.assessment not in ASSESSMENTS \
                or not isinstance(part.quotes_located, tuple) \
                or any(not isinstance(located, bool) for located in part.quotes_located):
            raise CouldNotCheck("unknown_assessment")
    if sum(len(p.quotes_located) for p in parts) > MAX_QUOTES:
        raise CouldNotCheck("too_many_quotes")
    for part in parts:
        if part.assessment in POSITIVE:
            if not 1 <= len(part.quotes_located) <= MAX_QUOTES_PER_PART:
                raise CouldNotCheck("positive_part_quote_count")
            if not any(part.quotes_located):
                raise CouldNotCheck("positive_part_without_located_quote")
        elif part.quotes_located:
            raise CouldNotCheck("quote_on_not_stated_part")
    if covers_whole_sentence is not True:
        raise CouldNotCheck("sentence_not_covered")
    kinds = {part.assessment for part in parts}
    if kinds == {"stated"}:
        return "found_whole"
    if kinds == {"not_stated"}:
        return "not_found_in_given"
    return "found_partial"


def check_outcome(parts: Iterable[PartAssessment], covers_whole_sentence: Any) -> dict[str, Any]:
    """`derive_result` as the stored status and result: `done` with a result, or `could_not_check` with none."""
    try:
        return {"status": "done", "result": derive_result(parts, covers_whole_sentence), "error": None}
    except CouldNotCheck as exc:
        return {"status": "could_not_check", "result": None, "error": exc.reason}


def valid_status_result(status: str, result: str | None) -> bool:
    """A result belongs to `done` only, and `done` always has one."""
    if status not in STATUSES:
        return False
    if status == "done":
        return result in RESULTS
    return result is None

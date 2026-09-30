"""Model-free candidates and bounded packing over caller-supplied snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from deixis.workflow.lineage.edges import EdgeFrom, EdgeTo, edge_state
from deixis.workflow.lineage.mentions import MentionTarget, PassageText, find_mentions, prepare_passages

MAX_CANDIDATES_PER_CHUNK = 8
MAX_CHUNKS_PER_TARGET = 3
MAX_PASSAGES_PER_CHUNK = 24
MAX_CHARS_PER_CHUNK = 48_000
NOT_SENT_REASONS = ("too_large_for_one_call", "beyond_call_limit")


@dataclass(frozen=True)
class LineageWork:
    source_version_id: str
    work_id: str
    position: int
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    years: tuple[int, ...]
    references_read: bool
    referenced_ids: frozenset[str]
    openalex_ids: frozenset[str]
    passages: tuple[PassageText, ...]


@dataclass(frozen=True)
class Candidate:
    to_source_version_id: str
    from_source_version_id: str
    to_position: int
    from_position: int
    total_matches: int
    basis: tuple[str, ...]
    mention_passage_ids: tuple[str, ...]
    edge_state: str
    year_order_warning: bool


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[Candidate, ...]
    no_candidate_targets: tuple[str, ...]
    scanned_targets: tuple[str, ...]


@dataclass(frozen=True)
class NotSent:
    candidate: Candidate
    reason: str


@dataclass(frozen=True)
class Packing:
    chunks: tuple[tuple[Candidate, ...], ...]
    not_sent: tuple[NotSent, ...]


def _unique_works(works: Iterable[LineageWork]) -> tuple[LineageWork, ...]:
    seen = set()
    result = []
    for work in works:
        if work.source_version_id not in seen:
            seen.add(work.source_version_id)
            result.append(work)
    return tuple(result)


def eligible_targets(works: Iterable[LineageWork]) -> tuple[LineageWork, ...]:
    """Stored PDF text is eligibility, not evidence that the text was reviewed."""
    return tuple(sorted((w for w in _unique_works(works)
                         if any(p.kind == "pdf_page" for p in w.passages)), key=lambda w: w.position))


def candidate_priority(candidate: Candidate) -> tuple[int, int, str]:
    return (-candidate.total_matches, candidate.from_position, candidate.from_source_version_id)


def find_candidates(
    works: Iterable[LineageWork], targets: Iterable[LineageWork] | None = None,
    excluded_pairs: frozenset[tuple[str, str]] = frozenset(),
) -> CandidateSet:
    """Explicit targets select eligible corpus snapshots; duplicate rows keep the first.

    No run-size limit is applied here. The caller owns inclusion and run planning.
    """
    corpus = _unique_works(works)
    selected_ids = None if targets is None else {w.source_version_id for w in targets}
    selected = tuple(w for w in eligible_targets(corpus)
                     if selected_ids is None or w.source_version_id in selected_ids)
    candidates = []
    no_candidate = []
    for to in selected:
        prepared = prepare_passages(to.passages)
        found = []
        for frm in corpus:
            if frm.work_id == to.work_id or (frm.source_version_id, to.source_version_id) in excluded_pairs:
                continue
            mention = find_mentions(prepared, MentionTarget(
                frm.source_version_id, frm.title, frm.authors, frm.year, frm.years))
            if mention is None:
                continue
            found.append(Candidate(
                to.source_version_id, frm.source_version_id, to.position, frm.position,
                mention.total, mention.basis, mention.mention_passage_ids,
                edge_state(EdgeTo(to.source_version_id, to.work_id, to.references_read, to.referenced_ids),
                           EdgeFrom(frm.source_version_id, frm.work_id, frm.openalex_ids)),
                to.year is not None and frm.year is not None and to.year < frm.year,
            ))
        candidates.extend(sorted(found, key=candidate_priority))
        if not found:
            no_candidate.append(to.source_version_id)
    return CandidateSet(tuple(candidates), tuple(no_candidate), tuple(w.source_version_id for w in selected))


def pack_candidates(
    candidates: Iterable[Candidate], fits: Callable[[tuple[Candidate, ...]], bool] | None = None,
    max_per_chunk: int = MAX_CANDIDATES_PER_CHUNK, max_chunks: int = MAX_CHUNKS_PER_TARGET,
) -> Packing:
    """Pack one target's candidates in the shared priority order.

    The default is count-only: eight candidates per chunk, three chunks. An explicit
    fits predicate may impose a size budget. L5 must supply a predicate for its real
    StepInput message; the passage-text proxy below does not enforce that limit.
    Reasons are retained for L5's recorded not_sent_budget state.
    """
    if max_per_chunk < 1 or max_chunks < 1:
        raise ValueError("chunk limits must be positive")
    ordered = sorted(candidates, key=candidate_priority)
    if len({c.to_source_version_id for c in ordered}) > 1:
        raise ValueError("packing requires one target")
    chunks = []
    current: tuple[Candidate, ...] = ()
    not_sent = []
    for candidate in ordered:
        if len(chunks) == max_chunks:
            not_sent.append(NotSent(candidate, "beyond_call_limit"))
            continue
        proposed = (*current, candidate)
        if current and (len(current) == max_per_chunk or (fits is not None and not fits(proposed))):
            chunks.append(current)
            current = ()
            if len(chunks) == max_chunks:
                not_sent.append(NotSent(candidate, "beyond_call_limit"))
                continue
        if not current and fits is not None and not fits((candidate,)):
            not_sent.append(NotSent(candidate, "too_large_for_one_call"))
            continue
        current = (*current, candidate)
        if len(current) == max_per_chunk:
            chunks.append(current)
            current = ()
    if current:
        chunks.append(current)
    return Packing(tuple(chunks), tuple(not_sent))


def passage_budget_fits(
    passage_chars: Mapping[str, int], max_passages: int = MAX_PASSAGES_PER_CHUNK,
    max_chars: int = MAX_CHARS_PER_CHUNK,
) -> Callable[[tuple[Candidate, ...]], bool]:
    """Explicit proxy over unique mention-passage text, not the StepInput message.

    L5 owns the real 48,000-character message budget. Missing lengths raise KeyError
    rather than understating size. Copy lengths so the predicate keeps its snapshot.
    """
    lengths = dict(passage_chars)
    if max_passages < 0 or max_chars < 0 or any(length < 0 for length in lengths.values()):
        raise ValueError("passage budgets and lengths must be nonnegative")

    def fits(chunk: tuple[Candidate, ...]) -> bool:
        ids = frozenset(p for candidate in chunk for p in candidate.mention_passage_ids)
        return len(ids) <= max_passages and sum(lengths[p] for p in sorted(ids)) <= max_chars

    return fits

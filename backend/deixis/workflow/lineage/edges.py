"""Stored citation-list states, with no candidate or relation construction."""

from dataclasses import dataclass
from typing import Iterable

EDGE_STATES = ("present", "absent_in_read_list", "unresolved", "not_read")


@dataclass(frozen=True)
class EdgeTo:
    source_version_id: str
    work_id: str
    references_read: bool
    referenced_ids: frozenset[str]


@dataclass(frozen=True)
class EdgeFrom:
    source_version_id: str
    work_id: str
    openalex_ids: frozenset[str]


@dataclass(frozen=True)
class Edge:
    to_source_version_id: str
    from_source_version_id: str
    state: str


def normalize_openalex_id(value: str) -> str:
    short = value.strip().rsplit("/", 1)[-1]
    return short[:1].upper() + short[1:]


def normalized_openalex_ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(short for value in values if (short := normalize_openalex_id(value)))


def edge_state(to: EdgeTo, frm: EdgeFrom) -> str:
    if not to.references_read:
        return "not_read"
    ids = normalized_openalex_ids(frm.openalex_ids)
    if not ids:
        return "unresolved"
    return "present" if ids & normalized_openalex_ids(to.referenced_ids) else "absent_in_read_list"


def unexpected_no_citation_edge(state: str) -> bool:
    return state == "absent_in_read_list"


def derive_edges(tos: Iterable[EdgeTo], froms: Iterable[EdgeFrom]) -> tuple[Edge, ...]:
    earlier = tuple(froms)
    return tuple(Edge(to.source_version_id, frm.source_version_id, edge_state(to, frm))
                 for to in tos for frm in earlier
                 if to.source_version_id != frm.source_version_id and to.work_id != frm.work_id)


def edge_counts(edges: Iterable[Edge]) -> dict[str, int]:
    counts = dict.fromkeys(EDGE_STATES, 0)
    for edge in edges:
        counts[edge.state] += 1
    return counts


def unassessed_edges(
    edges: Iterable[Edge], candidate_pairs: frozenset[tuple[str, str]],
    scanned_targets: frozenset[str], excluded_pairs: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[Edge, ...]:
    """Only a scanned target can have a present edge with no found mention."""
    return tuple(edge for edge in edges if edge.state == "present"
                 and edge.to_source_version_id in scanned_targets
                 and (edge.from_source_version_id, edge.to_source_version_id) not in candidate_pairs
                 and (edge.from_source_version_id, edge.to_source_version_id) not in excluded_pairs)

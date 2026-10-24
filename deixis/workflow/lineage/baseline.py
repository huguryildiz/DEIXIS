"""Corpus lists use stored counts and registered types, without quality scoring.

The caller supplies current included versions. Representative values are never
filled from another version. The union of a target's included OpenAlex identifiers
is identity resolution, not a gap fill of count, date or type.
"""

from dataclasses import dataclass
from typing import Iterable

from deixis.workflow.lineage.edges import normalized_openalex_ids

SHOWN = 5
REVIEW_NOTE = "Registered type: review. Which provider wrote the type is not stored."


@dataclass(frozen=True)
class BaselineVersion:
    source_version_id: str
    work_id: str
    is_head: bool
    has_active_asset: bool
    created_at: str
    cited_by_count: int | None
    cited_by_count_at: str | None
    publication_type: str | None
    references_read: bool
    referenced_ids: frozenset[str]
    openalex_ids: frozenset[str]


@dataclass(frozen=True)
class Representative:
    work_id: str
    source_version_id: str
    reason: str
    versions_considered: tuple[str, ...]


@dataclass(frozen=True)
class IncludedCitations:
    count: int | None
    other_works: int
    lists_read: int
    target_resolved: bool


@dataclass(frozen=True)
class BaselineEntry:
    work_id: str
    source_version_id: str
    cited_by_count: int | None
    cited_by_count_at: str | None
    publication_type: str | None
    cited_by_included: IncludedCitations


@dataclass(frozen=True)
class BaselineList:
    entries: tuple[BaselineEntry, ...]

    @property
    def shown(self) -> tuple[BaselineEntry, ...]:
        return self.entries[:SHOWN]

    @property
    def total(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class FieldBaseline:
    representatives: tuple[Representative, ...]
    most_cited_in_corpus: BaselineList
    review_in_corpus: BaselineList
    unknown_count_works: int


def field_baseline(versions: Iterable[BaselineVersion]) -> FieldBaseline:
    """D48 representative order; versions_considered records IDs in that order.

    Included citations count distinct other works over their read lists only. A
    missing identity or no read lists yields None, never an inferred zero.
    """
    grouped: dict[str, list[BaselineVersion]] = {}
    for version in versions:
        grouped.setdefault(version.work_id, []).append(version)
    representatives = []
    identities = {}
    read_lists = {}
    for work_id in sorted(grouped):
        group = sorted(grouped[work_id], key=lambda v: (
            not v.is_head, not v.has_active_asset, v.created_at, v.source_version_id))
        grouped[work_id] = group
        representative = group[0]
        representatives.append(Representative(
            work_id, representative.source_version_id, "head" if representative.is_head else "other_version",
            tuple(v.source_version_id for v in group),
        ))
        identities[work_id] = normalized_openalex_ids(oid for v in group for oid in v.openalex_ids)
        read = [v for v in group if v.references_read]
        if read:
            read_lists[work_id] = normalized_openalex_ids(oid for v in read for oid in v.referenced_ids)
    entries = []
    for work_id in sorted(grouped):
        version = grouped[work_id][0]
        other_read = {wid: refs for wid, refs in read_lists.items() if wid != work_id}
        resolved = bool(identities[work_id])
        count = (sum(bool(identities[work_id] & refs) for refs in other_read.values())
                 if resolved and other_read else None)
        entries.append(BaselineEntry(
            work_id, version.source_version_id, version.cited_by_count, version.cited_by_count_at,
            version.publication_type, IncludedCitations(count, len(grouped) - 1, len(other_read), resolved),
        ))
    known = [entry for entry in entries if entry.cited_by_count is not None]
    known.sort(key=lambda entry: (-entry.cited_by_count, entry.work_id))
    reviews = tuple(entry for entry in entries if (entry.publication_type or "").casefold() == "review")
    return FieldBaseline(tuple(representatives), BaselineList(tuple(known)), BaselineList(reviews),
                         len(entries) - len(known))

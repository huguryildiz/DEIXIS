"""Read-time graph structure over frozen links; no evidence assessment."""

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable


@dataclass(frozen=True)
class Link:
    link_id: str
    from_svid: str
    to_svid: str
    relation: str
    from_year: int | None
    to_year: int | None
    from_position: int
    to_position: int


def node_order(year: int | None, position: int, svid: str) -> tuple:
    return (year is None, year or 0, position, svid)


def link_order(link: Link) -> tuple:
    return (link.from_year is None, link.from_year or 0, link.to_year is None,
            link.to_year or 0, link.from_position, link.to_position, link.link_id)


@dataclass(frozen=True)
class Adjacency:
    source_version_id: str
    in_from: tuple[str, ...]
    out_to: tuple[str, ...]


@dataclass(frozen=True)
class Component:
    id: str  # Derived at read time from member IDs; never a persistent identity.
    members: tuple[str, ...]
    links: tuple[str, ...]
    adjacency: tuple[Adjacency, ...]
    roots: tuple[str, ...]
    branches: tuple[str, ...]
    merges: tuple[str, ...]
    has_cycle: bool


@dataclass(frozen=True)
class Assembly:
    components: tuple[Component, ...]


def assemble(links: Iterable[Link]) -> Assembly:
    development = sorted((l for l in links if l.relation != "independent_parallel"), key=link_order)
    order, incoming, outgoing, weak = {}, {}, {}, {}
    for link in development:
        a, b = link.from_svid, link.to_svid
        for sid, year, position in ((a, link.from_year, link.from_position), (b, link.to_year, link.to_position)):
            order[sid] = node_order(year, position, sid)
            incoming.setdefault(sid, set())
            outgoing.setdefault(sid, set())
            weak.setdefault(sid, set())
        incoming[b].add(a)
        outgoing[a].add(b)
        weak[a].add(b)
        weak[b].add(a)
    remaining, components = set(order), []
    while remaining:
        pending, seen = [min(remaining, key=order.get)], set()
        while pending:
            sid = pending.pop()
            if sid not in seen:
                seen.add(sid)
                pending.extend(weak[sid] - seen)
        remaining -= seen
        members = tuple(sorted(seen, key=order.get))
        # Kahn's algorithm counts visited nodes even on cyclic input.
        degrees = {sid: len(incoming[sid]) for sid in members}
        ready = [sid for sid in members if not degrees[sid]]
        visited = 0
        while ready:
            sid = ready.pop()
            visited += 1
            for nxt in outgoing[sid]:
                degrees[nxt] -= 1
                if degrees[nxt] == 0:
                    ready.append(nxt)
        identity = sha256(json.dumps(sorted(members), separators=(",", ":")).encode()).hexdigest()[:12]
        components.append(Component(
            identity, members, tuple(l.link_id for l in development if l.from_svid in seen),
            tuple(Adjacency(sid, tuple(sorted(incoming[sid], key=order.get)),
                            tuple(sorted(outgoing[sid], key=order.get))) for sid in members),
            tuple(sid for sid in members if not incoming[sid] and outgoing[sid]),
            tuple(sid for sid in members if len(outgoing[sid]) > 1),
            tuple(sid for sid in members if len(incoming[sid]) > 1), visited != len(members),
        ))
    return Assembly(tuple(sorted(components, key=lambda c: order[c.members[0]])))


REASONS = ("not_run", "no_pdf_text", "no_candidate", "no_relation", "insufficient_evidence", "rejected",
           "not_sent_budget", "step_failed", "human_removed", "cross_relation_only", "stale_only")


@dataclass(frozen=True)
class RowFacts:
    eligible: bool = True
    target_recorded: bool = False
    no_candidate: bool = False
    has_no_relation: bool = False
    has_insufficient_evidence: bool = False
    has_rejected: bool = False
    has_not_sent_budget: bool = False
    has_step_failed: bool = False
    has_human_removed: bool = False
    has_cross_relation: bool = False
    has_history_link: bool = False


def unplaceable_reasons(facts: RowFacts) -> tuple[str, ...]:
    flags = (facts.eligible and not facts.target_recorded, not facts.eligible, facts.no_candidate,
             facts.has_no_relation, facts.has_insufficient_evidence, facts.has_rejected,
             facts.has_not_sent_budget, facts.has_step_failed, facts.has_human_removed,
             facts.has_cross_relation, facts.has_history_link)
    return tuple(reason for reason, applies in zip(REASONS, flags) if applies) or ("not_run",)

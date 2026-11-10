"""What one follow-up turn actually looked in, counted by code and kept with the published turn.

A follow-up that finds nothing has found nothing **here**: in the works this research holds (and, for a turn that
answered again, the works its own search found), at the reading depth they are held at, among the passages this call
was given. That is a far smaller thing than the literature, and the
design asks for the difference to be written down rather than left to the reader. So every published turn carries
this, whatever its outcome — the answer that found everything says where it looked too.

Counted, never claimed. The numbers come from the frozen pool, the frozen selection and the turn's own full-text
attempt; none of them is read from model prose, and none of them is an estimate. A work weighed on its abstract is
counted apart from one read in full, because an abstract cannot support a detail it does not state.
"""

from __future__ import annotations

from typing import Any


def depths(store: Any, pool_sources: dict[str, list[str]]) -> dict[str, Any]:
    """The works this turn weighed, by the depth their passages in the pool were read at.

    One version per work is in the pool (the pool's own rule), so a work is counted once: `full_text` when the pool
    holds a page of its file, `abstract` when its abstract is all there was.
    """
    ids = [pid for pid_list in pool_sources.values() for pid in pid_list]
    if not ids:
        return {"works": 0, "full_text": 0, "abstract": 0}
    rows = store.conn.execute(
        f"SELECT v.work_id AS work_id, p.kind AS kind FROM passages p"
        f" JOIN source_versions v ON v.id = p.source_version_id"
        f" WHERE p.id IN ({', '.join('?' * len(ids))})", tuple(ids))
    held: dict[str, bool] = {}
    for row in rows:
        held[row["work_id"]] = held.get(row["work_id"], False) or row["kind"] != "abstract"
    return {"works": len(held), "full_text": sum(1 for full in held.values() if full),
            "abstract": sum(1 for full in held.values() if not full)}


def research_works(store: Any, research_id: str) -> int:
    """How many works this research holds at all, so the turn's own pool can be read against it."""
    return store.conn.execute(
        "SELECT COUNT(DISTINCT v.work_id) FROM corpus_memberships m JOIN source_versions v"
        " ON v.id = m.source_version_id WHERE m.research_id = ? AND m.removed_at IS NULL", (research_id,),
    ).fetchone()[0]


def read_works(store: Any, read_ids: list[str] | None) -> dict[str, Any]:
    """The works a call of this turn was given a passage of, by the depth that passage was read at.

    Apart from the pool's own counts on purpose. The pool is what the turn could have read; the passage limit then
    cuts it down, so a turn whose pool held forty works may have shown the model eight. Saying the pool's number is
    where it looked would overstate the search every time the limit bit. Both of a turn's rounds count: the second
    round takes the place of some of the first round's passages, and the works the first call read were still read.
    """
    if not read_ids:
        return {"works": 0, "full_text": 0, "abstract": 0}
    return depths(store, {"read": list(read_ids)})


def scanned(store: Any, research_id: str, frozen_pool: dict[str, Any], selection: dict[str, Any] | None,
            fulltext: dict[str, Any] | None, read_ids: list[str] | None = None,
            given: int | None = None) -> dict[str, Any]:
    """The turn's scanned scope: where it looked, how deeply, and what it tried to read before answering.

    `selection` is None for a turn that never reached a call (it held no passage, or it stopped earlier): the scope
    then says what the pool held and that nothing was given, which is itself the honest answer to "where did you
    look".
    """
    sources = frozen_pool.get("sources") or {}
    found, shown = depths(store, sources), read_works(store, read_ids)
    return {
        "basis": frozen_pool.get("basis"),
        # The works of this research, and the ones this turn weighed: a pool is never the whole library, because
        # the person's own exclusions and the answer this turn reads from both narrow it.
        "research_works": research_works(store, research_id),
        "works": found["works"], "works_full_text": found["full_text"], "works_abstract_only": found["abstract"],
        # Of those, the works this turn's own search found: read for this answer, not included in the research, so
        # "where it looked" is wider than the research itself and says by how much.
        "works_found_by_search": len(frozen_pool.get("found_versions") or []),
        # And the works a call of this turn was given a passage of, which is the narrower, truer answer to "where
        # did it look": the passage limit stands between the pool and the model (`read_works`).
        "works_given": shown["works"], "works_given_full_text": shown["full_text"],
        "works_given_abstract_only": shown["abstract"],
        # Three passage counts, kept apart: what the pool held, what the ranking weighed, what the call was given.
        "pool_held": (selection or {}).get("pool_held", sum(len(v) for v in sources.values())),
        "ranked_considered": (selection or {}).get("ranked_considered"),
        # The passages the published answer's own call was given — its allowlist, so it is the last call's count,
        # not the two rounds together. `works_given` above is the wider "read this turn".
        "given_to_model": given if given is not None else (
            (selection or {}).get("given_to_model", 0) if selection else 0),
        # What this turn tried to read before answering, as its own record (`followup_fulltext.view`).
        "fulltext": fulltext,
    }

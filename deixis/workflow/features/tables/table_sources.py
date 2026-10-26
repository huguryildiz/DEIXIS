"""D114, D144: which sources a table made from the research follows, and why each one is in its report.

A table made from the research (`follows_included = 2`) holds the included sources and, beside them, the works nobody
decided that passed the abstract stage and were not included: those read in full (D144) and those read from their
abstracts only (D114). The owner's rules (17 Oct, 26 Oct): they go into the table and the report, each with a note on
how it was read.

Membership is decided per work, over every active version of it, never from one version's outcome. Both kinds need:

- nobody decided it: no version carries a selection the user set, a human stage decision, or a selection that is
  included (an included version is a row as an included source already) or excluded; for a work read in full, an
  exclusion the code derived from that reading (`criterion_absent`, say) is the reading itself, not a decision;
- it passed the abstract stage: a current abstract-stage `candidate` on some version.

Read in full (`full_text_read`): the answer's closest-work test holds on the work's answer version (D48, D137,
`answer.is_closest`): a current model full-text decision that did not include it, with a reason in
`answer.CLOSEST_CODES` (never `no_fulltext` or `text_unreadable`), standing on a reading of the file still in use. The
row's version is the one whose file was read.

Read from the abstract only (`abstract_only`):

- no version is still being judged: every current full-text decision on every version is `no_fulltext` or
  `text_unreadable` (or there is none yet);
- no version has text in use beyond its abstract (PDF pages or sections), and the row's version holds an abstract: the head when it has one, else the work's
  answer version (D48) when it holds one, else the first active version that does.

Membership is read live; nothing here is stored. A table made earlier (`follows_included` 0 or 1) keeps the included
sources only. Answer paths do not read this module.
"""

from __future__ import annotations

from typing import Any

from deixis.workflow.screen.decisions import DecisionStore

FOLLOWS_INCLUDED = 1
FOLLOWS_TABLE_SOURCES = 2
ABSTRACT_FULLTEXT_CODES = ("no_fulltext", "text_unreadable")


def follows(store: Any, table_id: str) -> int:
    row = store.conn.execute("SELECT follows_included FROM evidence_tables WHERE id = ?", (table_id,)).fetchone()
    return int(row[0]) if row else 0


def _has_abstract(store: Any, svid: str) -> bool:
    return store.conn.execute("SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract' LIMIT 1",
                              (svid,)).fetchone() is not None


def _has_text_beyond_abstract(store: Any, svid: str) -> bool:
    """Whether a model step may read more of this version than its abstract: PDF pages or sections in use."""
    return any(p["kind"] != "abstract" for p in store.passages_for(svid))


def _undecided_candidates(store: Any, rid: str, work_id: str | None = None, *, read_in_full: bool = False):
    """(work id, its active versions, its head, its current decisions) for each work nobody decided that passed the
    abstract stage: no version carries a selection the user set, a human stage decision, or a selection that is
    included or excluded, and some version holds a current abstract-stage `candidate`. For a work read in full an
    excluded selection the code derived from that reading does not count as a decision."""
    decisions = DecisionStore(store)
    facts = decisions.facts(rid, work_id)
    versions: dict[str, list[dict[str, Any]]] = {}
    for row in store.conn.execute(
        "SELECT v.id, v.work_id, s.state, s.origin FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " LEFT JOIN selections s ON s.research_id = m.research_id AND s.source_version_id = m.source_version_id"
        f" WHERE m.research_id = ? AND m.removed_at IS NULL{' AND v.work_id = ?' if work_id else ''} ORDER BY v.id",
        (rid, work_id) if work_id else (rid,),
    ):
        versions.setdefault(row["work_id"], []).append(dict(row))
    for wid, rows in versions.items():
        head = facts["heads"].get(wid)
        if head is None:
            continue
        if any(r["origin"] == "user" or r["state"] in (("included",) if read_in_full else ("included", "excluded"))
               for r in rows):
            continue
        work_decisions = facts["decisions"].get(wid, [])
        if any(d["decided_by"] == "human" for d in work_decisions):
            continue
        current = [d for d in work_decisions if not decisions.is_stale(d, facts["stale_key"])]
        if not any(d["stage"] == "abstract" and d["outcome"] == "candidate" for d in current):
            continue
        yield wid, rows, head, current


def abstract_works(store: Any, rid: str, work_id: str | None = None) -> dict[str, str]:
    """Work id -> the version that stands for it, for each work read from its abstract only (one work when named)."""
    answer_versions: dict[str, str | None] | None = None
    found: dict[str, str] = {}
    for wid, rows, head, current in _undecided_candidates(store, rid, work_id):
        if any(d["stage"] == "fulltext" and d["reason_code"] not in ABSTRACT_FULLTEXT_CODES for d in current):
            continue
        if any(_has_text_beyond_abstract(store, r["id"]) for r in rows):
            continue
        if _has_abstract(store, head):
            found[wid] = head
            continue
        # The head holds no abstract (a published head with metadata only, say): the work's answer version when it
        # holds one, else the first active version that does. The answer-version selector can name the head itself.
        if answer_versions is None:
            answer_versions = store.answer_versions(rid)
        active = [r["id"] for r in rows]
        preferred = answer_versions.get(head)
        ordered = ([preferred] if preferred in active else []) + [svid for svid in active if svid != preferred]
        standing = next((svid for svid in ordered if svid != head and _has_abstract(store, svid)), None)
        if standing is not None:
            found[wid] = standing
    return found


def full_text_works(store: Any, rid: str, work_id: str | None = None) -> dict[str, str]:
    """Work id -> the version whose file was read, for each work read in full and not included (one work when named).

    The answer's own test (`answer.is_closest`, D137) on the work's answer version (D48), so the table and the answer
    agree on what was read in full: a current model full-text decision on that version, with a reason code in
    `answer.CLOSEST_CODES`, standing on a reading of the file still in use (`answer.read_file`).
    """
    # Imported here: the flow reads this module, and the answer module reads the flow.
    from deixis.workflow.answer import answer
    from deixis.workflow.run.flow import ResearchFlow

    works = [(wid, head, current)
             for wid, _rows, head, current in _undecided_candidates(store, rid, work_id, read_in_full=True)
             if any(d["stage"] == "fulltext" and d["reason_code"] not in ABSTRACT_FULLTEXT_CODES for d in current)]
    if not works:
        return {}
    decisions = DecisionStore(store)
    facts = decisions.facts(rid, work_id)
    readings = answer.reading_records(store, rid)
    answer_versions = store.answer_versions(rid)
    # `read_file` checks the file a reading's plan froze is still in use; that check needs the store only.
    files = object.__new__(ResearchFlow)
    files.store = store
    found: dict[str, str] = {}
    for wid, head, _current in works:
        svid = answer_versions.get(head) or head
        text = answer.version_text(files, decisions, facts, readings, {}, wid, svid)
        if answer.is_closest(text["full"], text["asset"]):
            found[wid] = svid
    return found


def _work_of(store: Any, svids: list[str]) -> dict[str, str]:
    return store.work_ids(svids) if svids else {}


def _table_rows_by_work(store: Any, table_id: str, include_removed: bool) -> dict[str, list[str]]:
    rows = [r[0] for r in store.conn.execute(
        f"SELECT source_version_id FROM table_rows WHERE table_id = ?{'' if include_removed else ' AND removed_at IS NULL'}"
        " ORDER BY created_at, source_version_id", (table_id,))]
    work_of = _work_of(store, rows)
    by_work: dict[str, list[str]] = {}
    for svid in rows:
        if (wid := work_of.get(svid)) is not None:
            by_work.setdefault(wid, []).append(svid)
    return by_work


def _row_with_abstract(store: Any, standing: str, rows: list[str]) -> str | None:
    """The table row that stands for an abstract-only work: its standing version when that is a row, else the first
    row holding an abstract (an older row stays the work's row when a new head arrives). A row without an abstract
    never stands for it: the snapshot would freeze no passage for an abstract-only row."""
    if standing in rows:
        return standing
    return next((svid for svid in rows if _has_abstract(store, svid)), None)


def membership(store: Any, rid: str, table_id: str | None = None) -> dict[str, str]:
    """Source -> 'included', 'full_text_read' or 'abstract_only', in table order: the included sources, then the works
    read in full and not included, then the abstract-only works.

    A work read in full is represented by the version whose file was read. For an existing table, an abstract-only work
    is represented by the row the table already holds for it (so a new head does not add a second row); for a table
    about to be made, by the version `abstract_works` names. A work with an included version gets neither.
    """
    included = store.included_sources(rid)
    result = {svid: "included" for svid in included}
    if table_id is not None and follows(store, table_id) != FOLLOWS_TABLE_SOURCES:
        return result
    included_works = set(_work_of(store, included).values())
    rows = _table_rows_by_work(store, table_id, include_removed=False) if table_id else {}
    for wid, svid in sorted(full_text_works(store, rid).items(), key=lambda item: (item[1], item[0])):
        if wid not in included_works:
            result.setdefault(svid, "full_text_read")
    for wid, svid in sorted(abstract_works(store, rid).items(), key=lambda item: (item[1], item[0])):
        if wid in included_works:
            continue
        result.setdefault(_row_with_abstract(store, svid, rows.get(wid, [])) or svid, "abstract_only")
    return result


def table_sources(store: Any, rid: str, table_id: str | None = None) -> list[str]:
    return list(membership(store, rid, table_id))


def in_table_sources(store: Any, rid: str, table_id: str, svid: str) -> bool:
    """Live check for one source of one table, reading only its work's records (the fill's `_left_out`)."""
    if svid in store.included_sources(rid):
        return True
    if follows(store, table_id) != FOLLOWS_TABLE_SOURCES:
        return False
    wid = _work_of(store, [svid]).get(svid)
    if wid is None or (wid not in abstract_works(store, rid, wid) and full_text_works(store, rid, wid).get(wid) != svid):
        return False
    included_works = set(_work_of(store, store.included_sources(rid)).values())
    return wid not in included_works


# The records `abstract_works` and `full_text_works` read, summarised: the D63 sweep runs every worker turn, and
# reading every work's decisions each second for nothing would hold the library connection. When none of these moved
# since the table's last look, no work can have become abstract-only or read in full. Only when to look again is
# remembered, never who is a member: the fill's `_left_out` and the report boundary always read membership live.
_INPUTS_SQL = (
    "SELECT (SELECT MAX(created_at) FROM stage_decisions WHERE research_id = ?),"
    " (SELECT COUNT(*) FROM stage_decisions WHERE research_id = ? AND superseded_at IS NULL),"
    " (SELECT MAX(updated_at) FROM selections WHERE research_id = ?),"
    " (SELECT COUNT(*) FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL),"
    " (SELECT MAX(a.retrieved_at) FROM source_assets a JOIN corpus_memberships m ON m.source_version_id = a.source_version_id"
    "  WHERE m.research_id = ?),"
    # A removed file leaves its rows and passages in place; only its `removed_at` moves (`Store.remove_asset`).
    " (SELECT MAX(a.removed_at) FROM source_assets a JOIN corpus_memberships m ON m.source_version_id = a.source_version_id"
    "  WHERE m.research_id = ?),"
    " (SELECT COUNT(*) FROM passages p JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
    "  WHERE m.research_id = ?),"
    " (SELECT current_scope_revision FROM researches WHERE id = ?),"
    " (SELECT COUNT(*) FROM table_rows WHERE table_id = ?)")
_LOOKED: dict[str, tuple[Any, ...]] = {}


def new_abstract_rows(store: Any, rid: str, table_id: str) -> list[str]:
    """Works this table follows with no row for them in it (active or removed): a work read in full whose read version
    was never a row, and an abstract-only work with no row that holds an abstract, by their standing version. A work
    whose only rows lack an abstract (or the read file) gets its standing version as a further row."""
    if follows(store, table_id) != FOLLOWS_TABLE_SOURCES:
        return []
    inputs = tuple(store.conn.execute(_INPUTS_SQL, (rid,) * 8 + (table_id,)).fetchone())
    if _LOOKED.get(table_id) == inputs:
        return []
    _LOOKED[table_id] = inputs
    had = _table_rows_by_work(store, table_id, include_removed=True)
    included_works = set(_work_of(store, store.included_sources(rid)).values())
    read = [svid for wid, svid in sorted(full_text_works(store, rid).items(), key=lambda item: (item[1], item[0]))
            if wid not in included_works and svid not in had.get(wid, [])]
    return read + [svid for wid, svid in sorted(abstract_works(store, rid).items(), key=lambda item: (item[1], item[0]))
                   if wid not in included_works and _row_with_abstract(store, svid, had.get(wid, [])) is None]

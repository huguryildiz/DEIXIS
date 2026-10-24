"""D114: which sources a table made from the research follows, and why each one is in its report.

A table made from the research (`follows_included = 2`) holds the included sources and, beside them, the works read
from their abstracts only: works that passed the abstract stage and whose full text could not be obtained. The owner's
rule (17 Oct): they go into the table and the report, each with a note that only the abstract was read.

Membership is decided per work, over every active version of it, never from one version's outcome:

- nobody decided it: no version carries a selection the user set, a human stage decision, or a selection that is
  included or excluded (an included version is a row as an included source already);
- it passed the abstract stage: a current abstract-stage `candidate` on some version;
- no version is still being judged: every current full-text decision on every version is `no_fulltext` or
  `text_unreadable` (or there is none yet);
- no version has text in use beyond its abstract (PDF pages or sections), and the row's version holds an abstract: the head when it has one, else the work's
  answer version (D48) when it holds one, else the first active version that does.

Membership is read live; nothing here is stored. A table made earlier (`follows_included` 0 or 1) keeps the included
sources only. Answer paths do not read this module.
"""

from __future__ import annotations

from typing import Any

from deixis.workflow.decisions import DecisionStore

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


def abstract_works(store: Any, rid: str, work_id: str | None = None) -> dict[str, str]:
    """Work id -> the version that stands for it, for each work read from its abstract only (one work when named)."""
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
    answer_versions: dict[str, str | None] | None = None
    found: dict[str, str] = {}
    for wid, rows in versions.items():
        head = facts["heads"].get(wid)
        if head is None:
            continue
        if any(r["origin"] == "user" or r["state"] in ("included", "excluded") for r in rows):
            continue
        work_decisions = facts["decisions"].get(wid, [])
        if any(d["decided_by"] == "human" for d in work_decisions):
            continue
        current = [d for d in work_decisions if not decisions.is_stale(d, facts["stale_key"])]
        if not any(d["stage"] == "abstract" and d["outcome"] == "candidate" for d in current):
            continue
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
    """Source -> 'included' or 'abstract_only', in table order: the included sources, then the abstract-only works.

    For an existing table, an abstract-only work is represented by the row the table already holds for it (so a new
    head does not add a second row); for a table about to be made, by the version `abstract_works` names. A work with an
    included version gets no abstract-only row.
    """
    included = store.included_sources(rid)
    result = {svid: "included" for svid in included}
    if table_id is not None and follows(store, table_id) != FOLLOWS_TABLE_SOURCES:
        return result
    included_works = set(_work_of(store, included).values())
    rows = _table_rows_by_work(store, table_id, include_removed=False) if table_id else {}
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
    if wid is None or wid not in abstract_works(store, rid, wid):
        return False
    included_works = set(_work_of(store, store.included_sources(rid)).values())
    return wid not in included_works


# The records `abstract_works` reads, summarised: the D63 sweep runs every worker turn, and reading every work's
# decisions each second for nothing would hold the library connection. When none of these moved since the table's
# last look, no work can have become abstract-only. Only when to look again is remembered, never who is a member: the
# fill's `_left_out` and the report boundary always read membership live.
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
    """Abstract-only works with no row in this table (active or removed) that holds an abstract, by their standing
    version. A work whose only rows lack an abstract gets its standing version as a further row."""
    if follows(store, table_id) != FOLLOWS_TABLE_SOURCES:
        return []
    inputs = tuple(store.conn.execute(_INPUTS_SQL, (rid,) * 8 + (table_id,)).fetchone())
    if _LOOKED.get(table_id) == inputs:
        return []
    _LOOKED[table_id] = inputs
    had = _table_rows_by_work(store, table_id, include_removed=True)
    included_works = set(_work_of(store, store.included_sources(rid)).values())
    return [svid for wid, svid in sorted(abstract_works(store, rid).items(), key=lambda item: (item[1], item[0]))
            if wid not in included_works and _row_with_abstract(store, svid, had.get(wid, [])) is None]

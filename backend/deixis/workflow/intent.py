"""What the person asked a research to produce (UI parity S5a, F4), and where its work goes after discovery.

`report` is the flow as it was: discovery queues one answer. `papers` ends at the sources: the discovery budget freezes
`auto_answer: false`, so no answer is queued. `table` and `compare` build the study table instead of the answer: after
discovery through the study-table chain (`report_pipeline.start`; its rows are the sources included at that moment);
in an `attached` research, which runs no discovery, as a table of the attached sources once a file is ingested, with
no columns, so column suggestion and fill start as for a table made by hand. In a `compare` research every column
suggestion step is given a comparison frame written by code from the question of the scope revision it runs under
(`extraction_target.comparison_frame`); the method file says how to use it. Nothing here broadens the task: the intent
is the person's explicit choice, stored with the research and shown with it.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, rollback_savepoint, transaction
from deixis.workflow.store import Store

INTENTS = ("report", "papers", "table", "compare")
TABLE_INTENTS = ("table", "compare")
TABLE_TITLE = "Study table"


def comparison_frame(question: str) -> str:
    """The frame a `compare` research gives its study table's column suggestions: the question, framed as a
    comparison of methods. Written by code from the question as typed; no model is asked."""
    return f"Compare the methods the sources use for this question: {' '.join(question.split())}"


def frame_for(research: dict[str, Any], scope: dict[str, Any]) -> str | None:
    """The comparison frame of `research` under `scope` (one of its revisions), or None when it is not a `compare`."""
    return comparison_frame(scope["question"]) if research["intent"] == "compare" else None


def after_discovery(store: Store, run: dict[str, Any]) -> None:
    """Open the study table for a completed `table`/`compare` discovery run, in the transaction that completes it.

    Keyed by the discovery run, so a replayed completion finds the table and the column run it queued and adds
    nothing. With no included source no table is written; the research then shows its usual no-included-source state.
    """
    if (run["budget"].get("fast_path") or {}).get("after_discovery") != "study_table":
        return
    from deixis.workflow import report_pipeline

    rid = run["research_id"]
    reason = None
    if store.research(rid)["current_scope_revision"] != run["scope_revision"]:
        reason = "scope_revised"
    elif not store.included_sources(rid):
        reason = "no_included_source"
    if reason is None:
        # A refusal inside the chain's start must not leave its table behind in the completing transaction.
        savepoint = new_id("intent_table")
        store.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            report_pipeline.start(store, rid, f"intent:{run['id']}")
        except RevisionConflict:
            rollback_savepoint(store.conn, savepoint)
            reason = "run_active"
        else:
            store.conn.execute(f"RELEASE {savepoint}")
    if reason:
        store._event(rid, "study_table_skipped", {"reason": reason, "intent": store.research(rid)["intent"]}, run["id"])


def attached_ingested(store: Store, research_id: str) -> str | None:
    """Keep the study table of an `attached` `table`/`compare` research holding its attached sources.

    Called once a file, a Zotero item or a Library work has been added, or removed sources restored. The first call creates the table with explicit rows (the
    research's included sources, which in an `attached` research are the attached ones); a later call adds the
    sources that were never rows of it. A row the person removed stays removed, and a trashed table is left alone.
    One table per research: the idempotency key is the research's, so a repeated or retried call returns it.
    """
    from deixis.workflow.tables import TableStore

    research = store.research(research_id)
    if research["intent"] not in TABLE_INTENTS or store.scope(research_id)["source_scope"] != "attached":
        return None
    tables = TableStore(store)
    with transaction(store.conn):
        attached = store.included_sources(research_id)
        key = f"intent:{research_id}"
        existing = store.conn.execute("SELECT id, trashed_at, version FROM evidence_tables WHERE idempotency_key = ?",
                                      (tables._key(research_id, key),)).fetchone()
        if existing is None:
            if not attached:
                return None
            return tables.create_table(research_id, TABLE_TITLE, attached, None, key)
        if existing["trashed_at"]:
            return None
        rows = {r[0] for r in store.conn.execute("SELECT source_version_id FROM table_rows WHERE table_id = ?",
                                                 (existing["id"],))}
        new = [svid for svid in attached if svid not in rows]
        if new:
            tables.add_rows(research_id, existing["id"], new, existing["version"])
        return existing["id"]

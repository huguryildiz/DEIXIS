"""The works this research asks the person for a file for, and nothing else.

A list of its own. The screening queue asks whether to include a record, which is a different question, and before
this nothing in the app asked for a file at all: the report's basis note advised uploading PDFs in general, naming
no work and no open question.

The decision needs two things that never arrive together — a report plan, frozen while the report run writes, and
the automatic routes' own outcome, since the background fetches start after the run that queued them has ended. So
this is one function called from both points and from a person's own upload; whichever arrives last finds the other
already stored, and running it again writes nothing.

What makes a work askable is a reasoned link at the work's own level, not an empty axis: a sub-question the frozen
plan names, this work's own row under it, and that row's own cell left open (`report_coverage.open_axes_by_row`).
An axis no row answered says nothing about which work's file would answer it, and an open cell on a work that
already holds a file is not a missing file. A work is asked only after every automatic route has had its turn for
it, the open-web search among them (`workflow.read.fulltext_search`), so the person is never asked instead of a
route that was never tried. The reading of the report's gap is shared with that search (`report_gap_works`).

How many works may be asked is the depth's own allowance, frozen in the asking run's policy (`fast_path.MODES`:
none in Quick, three in Standard, five in Deep). It is spent by the asking and over the research's whole life: an
answered ask keeps its row, so a retry, a follow-up or a report revision hands nothing back. A run queued before the
rule names no allowance and asks for nothing. A file the person adds of their own accord asks nothing and writes no
row here, so it costs them nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.features.report import report_gap_works as gap
from deixis.workflow.run import fast_path

log = logging.getLogger("deixis.report_file_asks")

RULE = "file_ask_v1"


def allowance(store: Any, run_id: str) -> int | None:
    """How many works the depth that paid for this run allows asking for; None when its policy predates the rule.

    The number belongs to the discovery run that chose the depth, not to the report run that noticed the gap: a
    report run's budget carries no depth of its own. The stored request keeps that run, so the screen reads the
    allowance back from the same place however often the research is run again.
    """
    return gap.frozen_number(store, run_id, "file_ask_rule", fast_path.FILE_ASK_RULE, "file_asks")


def depth_run(store: Any, research_id: str, scope_revision: int) -> str | None:
    """The discovery run whose frozen policy is this research's depth."""
    return gap.depth_run(store, research_id, scope_revision)


def asks(store: Any, research_id: str) -> list[dict[str, Any]]:
    """Every file this research has asked the person for, in the order it asked, answered ones included."""
    return [dict(row) | {"axes": json.loads(row["axes_json"])} for row in store.conn.execute(
        "SELECT * FROM person_file_asks WHERE research_id = ? ORDER BY position, rowid", (research_id,),
    )]


def advance(store: Any, research_id: str) -> list[dict[str, Any]]:
    """Open the file requests the open sub-questions justify, close the ones a file answered; the rows it opened.

    One transaction, so a call beside another writes the same list or nothing. The rows it opens are empty on every
    later call: a work is asked once. A failure is logged and asks nothing — the list is for the reader's benefit
    and never stops the run that triggered it.
    """
    try:
        return _advance(store, research_id)
    except Exception:  # noqa: BLE001 - the list never fails the run or the upload that asked for it
        log.exception("file-ask list failed: %s", research_id)
        return []


def _advance(store: Any, research_id: str) -> list[dict[str, Any]]:
    # Opening a request rests on the report's gap and on a depth; closing one that has been answered rests on
    # neither, so the two are read apart and the closing always runs.
    from deixis.workflow.read import fulltext_search

    found = gap.gap_works(store, research_id)
    report = found["report"] if found else None
    depth = found["depth"] if found else None
    limit = allowance(store, depth) if depth else None
    with transaction(store.conn):
        held = {row["work_id"]: dict(row) for row in store.conn.execute(
            "SELECT work_id, id, answered_at FROM person_file_asks WHERE research_id = ?", (research_id,))}
        # A work whose file has arrived closes its row, whether the person gave it or a later route found it. The
        # row stays: the allowance was spent by the asking, not by the answer.
        for work_id, row in held.items():
            if row["answered_at"] is None and gap.work_has_file(store, research_id, work_id):
                store.conn.execute(
                    "UPDATE person_file_asks SET answered_at = ?, outcome = 'file_added' WHERE id = ?",
                    (now(), row["id"]))
        if found is None or limit is None or len(held) >= limit:
            return []
        opened: list[dict[str, Any]] = []
        for work in found["works"]:
            if len(held) + len(opened) >= limit:
                break
            if work["work_id"] in held:
                continue
            # The open-web search is the last automatic route: until it has had its turn for this work, asking the
            # person would ask before the routes were tried.
            if not fulltext_search.settled(store, research_id, work["work_id"], report["scope_revision"]):
                continue
            row = {"id": new_id("pfa"), "research_id": research_id, "work_id": work["work_id"],
                   "source_version_id": work["source_version_id"], "report_id": report["id"],
                   "run_id": depth, "scope_revision": report["scope_revision"], "rule": RULE,
                   "axes_json": dumps([{key: axis[key] for key in ("axis_id", "label", "column_id", "column_name",
                                                                   "cell_id", "state", "reading_depth")}
                                       for axis in work["axes"]]),
                   "position": len(held) + len(opened), "asked_at": now()}
            store.conn.execute(
                f"INSERT INTO person_file_asks ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()))
            store._event(research_id, "person_file_asked",
                         {"work_id": row["work_id"], "source_version_id": row["source_version_id"], "rule": RULE,
                          "axis_ids": [axis["axis_id"] for axis in work["axes"]]}, report["run_id"])
            opened.append(row)
        return opened

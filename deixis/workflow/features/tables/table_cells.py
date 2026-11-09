"""Evidence cells written while the reading is still going.

A paper's finding reaches the table as that paper is read, not after the answer: the discovery run asks for a
source's cells as soon as its full text has been read and adjudicated. The call is owned by the cell lane from the
moment it is sent, so neither the read cutoff nor the answer waits for it and the first answer is not delayed by
table work.

Five rules bound it:

- **Only what the reading left.** A call goes out only from the model-call allowance the stage's own work no longer
  needs: what the remaining full-text readings and the unclosed batches of the deeper screening still owe, with the
  schema repairs they are allowed, is reserved first. Each call the stage admits is reserved in the same set the
  screening's sender uses, so two sources admitted in one pass cannot both spend the same spare call.
- **Nothing sent after the cutoff.** The stage stops offering sources at its deadline, and the call itself is
  checked once more in the synchronous moment before it is sent: a call whose passages were still being chosen when
  the deadline passed is closed unsent. A call already sent is not cut — it is the one model call of this run that
  the read window does not bound, because its answer is wanted whenever it comes.
- **Only a paper this run read.** A source is offered only when the work's own full-text decision is a fresh model
  reading, and only on the version this run's reading plan froze as the one to read: a work fetched but not read,
  decided from its abstract or title, or read by this run on another of its versions gets no cell here.
- **Nothing a person wrote is touched.** The call asks only for the columns with no stored cell for that source, and
  the store refuses both to replace a person's value and to write to a row a person removed meanwhile.
- **Its failure costs this source only.** The call is an optional step, so a transport failure closes its own step
  and stops that source's cells: a reading is never paused, and a run that has already finished is never turned
  back into a paused one because the table could not be filled.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from deixis.domain.rules import ABSTRACT_BATCH, FULLTEXT_RUNS, run_schema_repairs
from deixis.workflow.screen import abstract_stage
from deixis.workflow.features.tables import table_rows
from deixis.workflow.features.tables.tables import MAX_COLUMNS_PER_CALL, TableStore

log = logging.getLogger("deixis.table_cells")
KEY = "cells"
# Full-text decisions that mean this run read the version's own file and judged its text. The two fresh model codes
# left out say the opposite: one was decided from the record's title alone, and the other could not confirm the file
# belongs to the work, so neither gives text a cell may rest on.
READ_CODES = ("all_parts_verified", "criterion_absent", "fulltext_runs_disagree", "include_quote_unverified",
              "part_without_evidence", "fulltext_runs_agree_unresolved", "comparator_exclusion_withheld")


def read_versions(works: list[dict[str, Any]]) -> dict[str, str]:
    """Work id -> the version this run read in full, for each work whose reading settled on a model decision.

    The decision that speaks for the work (`fulltext.current_fulltext`) names the version it was taken on, and only
    a `READ_CODES` decision means a reading of that version's own file. A work a person decided, a work decided from
    its abstract or title, a work whose file could not be confirmed as its own and a work whose fetch found nothing
    are all left out: none of them has text this run read.
    """
    from deixis.workflow.read import fulltext

    found: dict[str, str] = {}
    for work in works:
        decision = fulltext.current_fulltext(work)
        if (decision and not decision.get("stale") and decision["decided_by"] != "human"
                and decision["reason_code"] in READ_CODES):
            found[work["work_id"]] = decision["id"]
    return found


def planned_versions(store: Any, run_id: str, key: str) -> dict[str, str]:
    """Work id -> the version this run's reading plan froze as the one to read, from the stored plan steps.

    The decision that speaks for a work may sit on another of its versions — a person's newer file, say — so the
    plan is what says which version this run read. A work with no stored plan is not offered.
    """
    prefix, suffix = f"{key}:read:", ":adjudication_plan"
    found: dict[str, str] = {}
    for row in store.conn.execute(
            "SELECT operation_key, output_json FROM run_steps WHERE run_id = ? AND kind = 'code:adjudication_plan'"
            " AND status = 'succeeded' AND operation_key LIKE ?", (run_id, f"{prefix}%{suffix}")):
        wid = row["operation_key"][len(prefix):-len(suffix)]
        for item in (json.loads(row["output_json"] or "{}").get("works") or []):
            if item.get("read_version"):
                found[wid] = item["read_version"]
    return found


def empty_columns(store: Any, table_id: str, svid: str) -> list[dict[str, Any]]:
    """The table's live columns that hold no stored cell for this source, in table order.

    A column a person or an earlier call already answered is left out, so a reading-time call never asks again for
    an answer the table has and never proposes over a person's cell. An empty list also means the source is not a
    row of the table, which is how a row a person removed stops being offered.
    """
    tables = TableStore(store)
    if svid not in tables.active_rows(table_id):
        return []
    answered = {row["column_id"] for row in store.conn.execute(
        "SELECT column_id FROM evidence_cells WHERE source_version_id = ? AND current_revision_id IS NOT NULL"
        " AND column_id IN (SELECT id FROM table_columns WHERE table_id = ?)", (svid, table_id))}
    return [column for column in tables._columns(table_id) if column["id"] not in answered]


def chunks(columns: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The columns of one source split into the calls that will ask for them."""
    return [columns[i:i + MAX_COLUMNS_PER_CALL] for i in range(0, len(columns), MAX_COLUMNS_PER_CALL)]


def call_keys(key: str, svid: str, columns: list[dict[str, Any]]) -> list[str]:
    """The operation keys one source's cell calls will use, known before any of them is sent."""
    return [f"{key}:{KEY}:{svid}:{index}" for index in range(len(chunks(columns)))]


def reservation_keys(run: dict[str, Any], keys: list[str]) -> list[str]:
    """One entry per call this source may spend, its allowed schema repairs included.

    The stage's reservation set counts one call per entry, as the screening's sender does, so a call that may be
    repaired is held with its repair room beside it. The entries are the call's own key plus one per repair, which
    is why `_model_step` dropping the key as it sends leaves the repair room reserved until the call is done.
    """
    repairs = run_schema_repairs(run, "cell_extraction")
    return [key for call_key in keys for key in [call_key, *(f"{call_key}#repair:{n}" for n in range(repairs))]]


def deep_calls(window: dict[str, Any] | None, plan: dict[str, Any] | None, closed: int, ended: bool) -> int:
    """Calls of the deeper screening that have not been made, which a cell call may not take.

    While its plan is not stored yet the window the policy froze is reserved whole: the deeper task can still be
    looking up the window's records when the top-N screening ends, so counting zero there would let a cell spend a
    call those batches are about to need. A task that has ended owes nothing, whether or not it left a plan and
    whether or not every batch of that plan closed — a batch whose works a person decided is never sent.
    """
    if window is None or ended:
        return 0  # a task that has ended owes nothing, whether or not its batches all closed
    if plan is None:
        return abstract_stage.model_calls(window["last"] - window["first"] + 1, ABSTRACT_BATCH, window["runs"])
    return max(0, len(plan["batches"]) - closed) * window["runs"]


def reserve(run: dict[str, Any], policy: dict[str, Any], settled_reads: int, open_deep_calls: int) -> int:
    """The model calls the stage's own work still owes, which a cell call may not take.

    Each full-text reading not yet settled is `FULLTEXT_RUNS` calls, and the deeper screening's unmade calls are
    counted as its caller gives them; each is held with the schema repairs its task is allowed, because a repair
    spends a call of the same budget. The top-N screening is not counted: cells are offered only once it ended.
    """
    reads = FULLTEXT_RUNS * max(0, policy["K"] - settled_reads) * (1 + run_schema_repairs(run, "fulltext_adjudication"))
    deep = max(0, open_deep_calls) * (1 + run_schema_repairs(run, "abstract_screening"))
    return reads + deep


def spare(flow: Any, run: dict[str, Any], keys: list[str], owed: int) -> bool:
    """Whether the allowance holds these calls once `owed` is reserved for the reading, and reserve them if so.

    Each cell call is counted with the repairs it may spend, and the keys are put in the stage's own reservation set
    the moment they are admitted, so a second source offered in the same pass sees them as spent. `_model_step`
    drops a key from that set as it sends it, when the run's usage starts counting it instead.
    """
    guard = getattr(flow, "_small_batch_guard", None)
    reserved = guard.get("reserved_calls") if guard and guard["run_id"] == run["id"] else None
    if reserved is None:
        return False  # outside the read stage's own guard nothing may be admitted on its allowance
    spent = flow.store.run(run["id"])["usage"].get("model_calls", 0)
    wanted = reservation_keys(run, keys)
    if spent + len(reserved) + len(wanted) + owed > run["budget"]["max_model_calls"]:
        return False
    reserved.update(wanted)
    return True


def rows_for_read(store: Any, rid: str) -> None:
    """Give the research's following tables a row for every source they now follow.

    The sweep that otherwise does this runs only once no run of the research is working, so without this a source
    read during the discovery would have no row and no cell could be written for it. The insert is the sweep's own:
    idempotent, never re-adding a row a person removed.
    """
    try:
        table_rows.add_rows(store, rid)
    except Exception:  # noqa: BLE001 - the reading must not stop because a row could not be added
        log.exception("adding the rows of the research read so far failed")


async def fill_source(flow: Any, run: dict[str, Any], scope: dict[str, Any], key: str, svid: str,
                      columns: list[dict[str, Any]], cutoff: Callable[[], bool]) -> None:
    """Ask for one source's empty cells and store what comes back, if the run may still write.

    One call per group of columns, with no salvage retry: a reading-time call that fails its own checks leaves its
    columns to the fill the chain queues after the answer. The cutoff is read twice for each call — before its
    passages are chosen and again in the moment before it is sent — so nothing goes out after the deadline; once
    sent, the call is waited for however long it takes. The write is skipped when the run was paused, cancelled or
    has moved to another question by the time the answer arrives.

    The call is an optional step, so its own failure closes its step and stops this source's cells and nothing
    else: a reading must not be paused, and a run that has already completed must not be turned back into a
    paused one, because the table could not be filled.
    """
    from deixis.workflow.run.flow import MAX_FILL_PASSAGES, OptionalStepFailed

    versions = {column["id"]: column["current_revision"] for column in columns}
    keys = call_keys(key, svid, columns)
    guard = getattr(flow, "_small_batch_guard", None)
    reserved = guard.get("reserved_calls") if guard and guard["run_id"] == run["id"] else None
    held = reservation_keys(run, keys)
    try:
        for call_key, group in zip(keys, chunks(columns)):
            if cutoff():
                return
            # The lane's own slot and no shared limiter: the readings' limiter must never hold a cell call, and a
            # cell call must never hold one of its places.
            async with flow.cell_lane.slot():
                if cutoff():
                    return
                try:
                    output = await flow._extraction(run, scope, call_key, svid, group, MAX_FILL_PASSAGES,
                                                    stop=cutoff, unbounded_window=True, optional=True)
                except OptionalStepFailed:
                    return
            if output is None or output.get("cutoff") or flow._fill_stopped(run["id"], run["scope_revision"]):
                return
            flow._save_cells(run, output, versions, recheck=False)
    finally:
        if reserved is not None:
            reserved.difference_update(held)

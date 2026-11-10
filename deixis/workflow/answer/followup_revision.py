"""The second answer of one follow-up question, from the works its own search found.

A follow-up question may ask for works this research does not hold. The person says so with the question (the
composer's own control), the turn is answered first from what the research holds, and the search they asked for runs
next. This module is what happens after that search: when it found works that can be read, the same question is
answered again in a turn of its own that names the first one (`revises_turn_id`).

Two rules keep this from quietly widening the research. The first answer is published and never edited, so the
second is a new turn: both answers, their evidence and their citations stay apart and the person can read what the
search changed. And the works the search found are **not** included in the research by this: they are pending search
records, and the revision reads their passages for this one answer only. Including them stays the person's own
decision, which is what the research's own answer and its report go by.

What the revision may read is therefore narrow: the **abstract** of a work this search found that the research did
not already hold, that nobody has removed, and that the screening kept as a candidate. Pages of a file no reading
decision covers are not given — a work whose full text the question needs is what the turn's own full-text attempt
is for. A work the screening put out of scope, one nothing has screened yet, one the person has decided against or
has since included, and one that was already here are all left out — the last one because it is not what "new works" means, and because the first answer already
read it. A work the screening kept is still only a candidate: reading it here is not including it, which is why the
person's own choice about it, in either direction, outranks what this does.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, now

NOT_STARTED = "followup_revision_not_started"
# Why a search that answered started no second answer. Each is a state of this research, never a model's opinion.
NO_NEW_EVIDENCE = "no_new_evidence"  # the search found no readable work the research did not already hold


def usable(store: Any, search_run: dict[str, Any]) -> list[dict[str, Any]]:
    """The works this search found that the revision may read, with their readable passages, best match first.

    Read from the search run's own frozen classification (`followup_search:found`) and the research's rows now, so
    a work the person excluded between the search and this read gives nothing. The passages are the current ones of
    the version the research holds for that work: its abstract, and the pages of a file in use.
    """
    from deixis.workflow.answer import answer as fast_answer
    from deixis.workflow.search import followup_search

    step = store.existing_step(search_run["id"], followup_search.FOUND_KEY)
    if step is None or step["status"] != "succeeded":
        return []
    rid = search_run["research_id"]
    heads, pools = store.work_heads(rid), fast_answer.current_pools(store, rid)
    screened = _screened(store, rid)
    selections, humans = fast_answer.user_choices(store, rid)
    included = set(fast_answer.included_heads(store, rid))
    found: list[dict[str, Any]] = []
    for work in (step["output"] or {}).get("works", []):
        if work["state"] != "new":
            continue  # already here, or removed before: not a work this search added to what can be read
        head = heads.get(work["work_id"])
        if head is None or head not in screened:
            continue  # the record left the research, or the screening never kept it as a candidate
        if work["work_id"] in included:
            continue  # the person included it after the search: the research's own pool gives it, not this
        chosen = (selections.get(head) or humans.get(work["work_id"]) or {}).get("state")
        # Their own choice about the work stands over a screening that kept it. "The file is wrong" is not such a
        # choice: it is about that file, and only the abstract is read here anyway.
        if chosen not in (None, "included", "pdf_wrong"):
            continue
        # The abstract alone. The pages of a file nobody decided to read are not evidence this answer may use, and
        # the screening read abstracts; a work whose full text the question needs is what the turn's own full-text
        # attempt is for, under its two-work budget.
        abstracts = [row["id"] for row in pools.get(head, []) if row["kind"] == "abstract"]
        if abstracts:
            found.append({"work_id": work["work_id"], "source_version_id": head, "passage_ids": abstracts})
    return found


def _screened(store: Any, research_id: str) -> set[str]:
    """The versions this research's abstract screening kept as candidates, by its own stored decision.

    The abstract stage's own outcome, not the work's overall one: a work whose file the person marked wrong reads as
    unresolved overall, and their decision is about that file, not about whether the abstract was ever a candidate.
    A decision the research has outgrown is not one either: a criterion or question revision since it was written
    leaves it stale, and a stale screening says nothing about today's question (`DecisionStore.is_stale`).
    """
    from deixis.workflow.screen.decisions import DecisionStore

    decisions = DecisionStore(store)
    return {row["source_version_id"] for row in store.conn.execute(
        "SELECT * FROM stage_decisions WHERE research_id = ? AND stage = 'abstract'"
        " AND outcome = 'candidate' AND superseded_at IS NULL", (research_id,))
        if not decisions.is_stale(dict(row))}


def after_search(store: Any, run: dict[str, Any]) -> None:
    """What follows a finished follow-up search, in its own completion write: the second answer, or the report.

    The search answered. If it found works that can be read, the same question is asked again over them and the
    report request waits for that answer (the chain's one key). If it found none, there is nothing a second model
    call could read that the first did not, so the first answer stands and the report request is honoured now.
    """
    from deixis.workflow.answer import followup

    turn = store.conn.execute("SELECT * FROM followup_turns WHERE id = ?",
                              (run["target"]["turn_id"],)).fetchone()
    if turn is None:
        return
    turn = dict(turn)
    found = usable(store, run)
    if not found:
        store._event(run["research_id"], NOT_STARTED, {"turn_id": turn["id"], "reason": NO_NEW_EVIDENCE}, run["id"])
        followup._report_after(store, run, turn)
        return
    try:
        request(store, run, turn, found)
    except RevisionConflict as exc:
        store._event(run["research_id"], NOT_STARTED,
                     {"turn_id": turn["id"], "reason": "run_active", "detail": str(exc)}, run["id"])
        followup._report_after(store, run, turn)


ENDED = ("completed", "failed", "cancelled")  # a run that cannot produce an answer any more


def chain_ends(store: Any, research_id: str) -> None:
    """Honour the report request of every chain that can produce no second answer any more.

    Read from what this research holds, not from the run that just ended, for three reasons. A search that failed,
    was cancelled or found nothing readable must not leave that request waiting for a run that will never come. A
    second answer whose own run failed, was cancelled or was interrupted leaves the same debt, and its own completion
    write never ran. And a request that could not be queued because another run was active is tried again the next
    time this research goes idle, instead of being lost to that one moment.

    Nothing is queued while a run of the chain can still answer: a search or a second answer that is pending,
    running or paused may yet resume. The request's own key makes it once per chain, and a chain whose report run
    already exists is passed over without a read of its turns.
    """
    from deixis.workflow.answer import followup

    for row in store.conn.execute(
            "SELECT * FROM followup_turns WHERE research_id = ? AND search_requested = 1"
            " AND revises_turn_id IS NULL AND draft_json IS NOT NULL", (research_id,)):
        turn = dict(row)
        if store.conn.execute("SELECT 1 FROM runs WHERE idempotency_key = ?",
                              (followup.report_run_key(turn["id"]),)).fetchone():
            continue  # this chain's report version was queued already
        last = _chain_last_run(store, turn)
        if last is None:
            continue  # a run of this chain may still answer, or its search never started
        followup._report_after(store, last, turn)


def chain_ends_all(store: Any) -> None:
    """The same sweep for every research that holds such a chain; the start of a backend reads it once.

    A crash between a search's own failure and the hook that ends its chain leaves the report request with nothing
    to wake it: no later run of that research need ever end. The start reads the chains themselves, so the debt is
    found whatever the process was doing when it stopped.
    """
    for row in store.conn.execute(
            "SELECT DISTINCT research_id FROM followup_turns WHERE search_requested = 1 AND revises_turn_id IS NULL"
            " AND draft_json IS NOT NULL"):
        chain_ends(store, row["research_id"])


def _chain_last_run(store: Any, turn: dict[str, Any]) -> dict[str, Any] | None:
    """The run that ended this chain, or None while one of its runs may still answer the question again.

    The second answer's own run is read first, because it is the chain's last word: a turn row with no published
    draft and an ended run is a second answer that will not come. Where no second answer was ever opened, the
    search's own runs say whether one still could.
    """
    from deixis.workflow.search import followup_search

    child = store.conn.execute("SELECT * FROM followup_turns WHERE revises_turn_id = ?", (turn["id"],)).fetchone()
    if child is not None:
        child = dict(child)
        run = store.run(child["run_id"]) if child["run_id"] else None
        return run if run is not None and run["status"] in ENDED else None
    runs = [dict(r) for r in store.conn.execute(
        "SELECT id, status, target_json FROM runs WHERE research_id = ? AND kind = ?",
        (turn["research_id"], followup_search.KIND))]
    mine = [r for r in runs if json.loads(r["target_json"] or "{}").get("turn_id") == turn["id"]]
    if not mine or any(r["status"] not in ENDED for r in mine):
        return None  # the search has not run yet, or it may still resume and answer again
    return store.run(mine[-1]["id"])


def request(store: Any, search_run: dict[str, Any], turn: dict[str, Any],
            found: list[dict[str, Any]]) -> dict[str, Any]:
    """Open the turn that answers this question again, and its run; the stored turn row.

    The question, the scope revision and the person's selections are the first turn's: this is the same ask, read
    over more evidence. The selections are carried as they were **frozen** then — the same passages, the same works,
    the same versions — because resolving them again could point the person's own words at another source; only
    whether each one can be given to the call is worked out again, by the selection step, as for any turn.
    """
    from deixis.workflow.answer import followup, followup_fulltext

    research = store.research(turn["research_id"])
    if turn["scope_revision"] != research["current_scope_revision"]:
        raise RevisionConflict("The research question changed after this follow-up was answered")
    turn_id = new_id("fut")
    scope = store.scope(turn["research_id"], turn["scope_revision"])
    from deixis.domain.rules import TEST_EFFORT_BUDGETS
    budget = {"max_model_calls": followup.CALLS, "max_provider_requests": 0,
              "max_followup_passages": TEST_EFFORT_BUDGETS[scope["effort"]].max_answer_passages,
              # The revision's own wait and its own works: the first answer spent its allowance on what the research
              # already held, and the works this one may try are the ones the search found.
              "followup_fulltext": followup_fulltext.budget()}
    run = store.create_run(
        turn["research_id"], followup.TASK, budget, f"followup:revision:{turn['id']}",
        target={"turn_id": turn_id, "question": turn["question"], "revises_turn_id": turn["id"],
                "search_run_id": search_run["id"], "found_works": [item["work_id"] for item in found]},
        expected_scope_revision=turn["scope_revision"])
    store.conn.execute(
        "INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at,"
        " search_requested, revises_turn_id) VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, ?)",
        (turn_id, turn["research_id"], turn["scope_revision"], turn["question"], run["id"], now(), turn["id"]))
    _carry_attachments(store, turn["id"], turn_id)
    store._event(turn["research_id"], "followup_revision_asked",
                 {"turn_id": turn_id, "revises_turn_id": turn["id"], "works": len(found)}, run["id"])
    return dict(store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn_id,)).fetchone())


def _carry_attachments(store: Any, from_turn_id: str, to_turn_id: str) -> None:
    """Copy the first turn's selections and their frozen bindings onto the turn that answers again, as they were."""
    for item in store.conn.execute(
            "SELECT * FROM followup_turn_attachments WHERE turn_id = ? ORDER BY ordinal", (from_turn_id,)):
        attachment_id = new_id("fua")
        store.conn.execute(
            "INSERT INTO followup_turn_attachments (id, turn_id, ordinal, kind, ref_id, selected_text,"
            " unresolved_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (attachment_id, to_turn_id, item["ordinal"], item["kind"], item["ref_id"], item["selected_text"],
             item["unresolved_reason"], now()))
        for binding in store.conn.execute(
                "SELECT * FROM followup_turn_attachment_bindings WHERE attachment_id = ? ORDER BY ordinal",
                (item["id"],)):
            store.conn.execute(
                "INSERT INTO followup_turn_attachment_bindings (attachment_id, ordinal, passage_id,"
                " source_version_id, work_id, version_label, locator_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (attachment_id, binding["ordinal"], binding["passage_id"], binding["source_version_id"],
                 binding["work_id"], binding["version_label"], binding["locator_json"]))


def found_for(store: Any, run: dict[str, Any]) -> list[dict[str, Any]]:
    """What this run's own pool reads beyond the research's evidence: nothing, unless it answers again.

    Read at the run, not stored on the turn, so a resumed run reads the same rows the pool was frozen from; the
    pool itself is frozen once (`followup.POOL_KEY`), which is what the answer and the citations are checked against.
    """
    search_run_id = (run["target"] or {}).get("search_run_id")
    if not search_run_id:
        return []
    return usable(store, store.run(search_run_id))


def view(store: Any, turn: dict[str, Any]) -> dict[str, Any] | None:
    """What the screen says about a turn that answers again: which turn, and how many works it read anew.

    Counted from the pool this turn froze, not from the search's own counts: the search may have found a work the
    person excluded before this answer read it, and then it is not a work this answer stands on.
    """
    if turn["revises_turn_id"] is None:
        return None
    step = store.existing_step(turn["run_id"], "followup:pool")
    frozen = (step["output"] or {}) if step and step["status"] == "succeeded" else {}
    return {"revises_turn_id": turn["revises_turn_id"], "works": len(frozen.get("found_versions") or [])}

"""A research of its own for a follow-up question that moved to another setting.

A follow-up may leave the question this research is about: another environment, another population, another
inclusion criterion. Answering it here would quietly widen the research — the works were screened against this
question's criterion, the report is written about it, and a second subject inside one research makes every count
("the works this research holds", "included") say two things at once.

So the application offers a research of its own and applies **none** of this research's scope to it. The question
is the person's, editable before they accept; the branch inherits only the settings that say how a research is run
(where it searches, how deep, which models), never what this research concluded, screened, included or read. Its
own discovery starts when the person starts it, as for any new research.

What is kept is the link: which research and which follow-up question it came from (`research_branches`). The
branch says where it came from and the question says a branch was opened, so the person can walk between them
without either research carrying the other's evidence. Either research can be purged while the other stays; the
link then empties rather than taking the remaining research with it.

A question opens at most one branch. The row and the research are written in one transaction, so a second click
finds the first branch instead of opening another.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import now, transaction

# The statuses of a turn that may open a branch: a published answer the person has read. A turn still being
# answered offers nothing, and an unverified draft is published too — the question it moved to is the person's
# own, not something the citation check decides.
OFFERED_STATUSES = ("answered", "partly_answered", "not_answered", "no_passages", "unverified_draft")


class BranchRefused(RevisionConflict):
    """A branch this turn cannot open now, with the reason `offer` names."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def offer(store: Any, turn: dict[str, Any]) -> dict[str, Any]:
    """Whether this turn can open a branch now, and if not why: the rules `request` applies, read without writing.

    `emphasis` is the model's own reading of the question: a published answer that said the question moves to
    another setting makes the offer "suggested", and the note is the line it wrote for the person. Everywhere else
    the offer stays "quiet" — the person may always open a research of their own, and nothing a model said starts
    one.
    """
    opened = of_turn(store, turn["id"])
    reason = None
    if turn["status"] not in OFFERED_STATUSES:
        reason = "turn_not_published"
    elif opened is not None:
        reason = "branch_opened"
    elif turn["scope_revision"] != store.research(turn["research_id"])["current_scope_revision"]:
        # The same rule the write applies: a question revised since is another question, and the settings a branch
        # would inherit are that revision's. The offer says so rather than refusing at the last step.
        reason = "not_current_revision"
    draft = _draft(turn)
    return {"offered": reason is None, "not_offered_reason": reason,
            "emphasis": "suggested" if draft.get("scope_change_requested") is True else "quiet",
            "note": draft.get("scope_change_note") if draft.get("scope_change_requested") is True else None,
            "research_id": opened["research_id"] if opened else None}


def _draft(turn: dict[str, Any]) -> dict[str, Any]:
    import json

    if turn["status"] not in OFFERED_STATUSES or not turn["draft_json"]:
        return {}
    return json.loads(turn["draft_json"])


def of_turn(store: Any, turn_id: str) -> dict[str, Any] | None:
    """The branch this question already opened, if any."""
    row = store.conn.execute("SELECT * FROM research_branches WHERE from_turn_id = ?", (turn_id,)).fetchone()
    return dict(row) if row else None


def of_research(store: Any, research_id: str) -> dict[str, Any] | None:
    """Where this research came from, for its own screen: the research and the question, as far as both still exist.

    A purged origin leaves the row with nothing to point at. The branch then says it was opened from a research
    that is gone rather than naming one it cannot show.
    """
    row = store.conn.execute("SELECT * FROM research_branches WHERE research_id = ?", (research_id,)).fetchone()
    if row is None:
        return None
    row = dict(row)
    parent = store.conn.execute("SELECT id, title FROM researches WHERE id = ?",
                                (row["from_research_id"],)).fetchone() if row["from_research_id"] else None
    turn = store.conn.execute("SELECT id, question FROM followup_turns WHERE id = ?",
                              (row["from_turn_id"],)).fetchone() if row["from_turn_id"] else None
    return {"research_id": row["from_research_id"] if parent else None,
            "title": parent["title"] if parent else None,
            "turn_id": row["from_turn_id"] if turn else None,
            "question": turn["question"] if turn else None,
            "created_at": row["created_at"]}


def link(store: Any, research_id: str, from_research_id: str, from_turn_id: str) -> None:
    """Record a research as the branch of one follow-up question. Written in the caller's own transaction.

    The unique index on the question is what stops a second click: a request that loses the race finds the row
    instead of a second research (`RevisionConflict`, which the route answers 409).
    """
    if of_turn(store, from_turn_id) is not None:
        raise BranchRefused("branch_opened", "This follow-up question already opened a research of its own")
    store.conn.execute(
        "INSERT INTO research_branches (research_id, from_research_id, from_turn_id, created_at)"
        " VALUES (?, ?, ?, ?)", (research_id, from_research_id, from_turn_id, now()))


def check(store: Any, research_id: str, turn_id: str, expected_scope_revision: int | None = None) -> dict[str, Any]:
    """The turn a branch is asked for, with the rules applied; raises `BranchRefused` when it cannot open one.

    The question revision is checked here, so the write itself holds it: the settings a branch inherits are read
    before the models are checked, and the person may revise the question in between. A revision since then is a
    different question, and a branch of it would carry settings nobody asked for.
    """
    from deixis.domain.rules import check_expected_version
    from deixis.workflow.run.store import NotFound

    row = store.conn.execute("SELECT * FROM followup_turns WHERE id = ? AND research_id = ?",
                             (turn_id, research_id)).fetchone()
    if row is None:
        raise NotFound(turn_id)
    turn = dict(row)
    current = store.research(research_id)["current_scope_revision"]
    if expected_scope_revision is not None:
        check_expected_version(expected_scope_revision, current)
    if turn["scope_revision"] != current:
        raise BranchRefused("not_current_revision", "The research question changed after this answer")
    offered = offer(store, turn)
    if not offered["offered"]:
        raise BranchRefused(offered["not_offered_reason"], "This follow-up cannot open a research of its own now")
    return turn


def opened(store: Any, research_id: str, turn_id: str, create: Any,
           expected_scope_revision: int | None = None) -> str:
    """Open the branch: the research `create` writes and its link row, in one transaction; the new research's id.

    `create` is the application's own research creation, passed in so a branch is written by the same path and the
    same refusals as a research the person starts on the home screen; nothing about scope is decided here. Every
    rule is read again inside this write, because the caller read the settings before it checked the models.
    """
    with transaction(store.conn):
        check(store, research_id, turn_id, expected_scope_revision)
        branch_id = create()
        link(store, branch_id, research_id, turn_id)
        store._event(research_id, "research_branch_opened",
                     {"turn_id": turn_id, "branch_research_id": branch_id})
        return branch_id

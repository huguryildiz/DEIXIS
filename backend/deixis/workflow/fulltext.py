"""The full-text retrieval run of an `sw` research: which works it fetches, and what one attempt settles (SW10, D83).

Pure: no database, no clock, no network, no model. The plan is a function of the works, the inspection order and the
limit, and the reason code a work ends with is a function of what the attempt found, so a resumed run re-derives
nothing it did not already store and a replay of the same input gives the same plan (SW14.6).

Three rules hold this module together:

- **Nothing is included and nothing is excluded here** (SW1.2). The three codes it writes are all `unresolved`: a
  work whose text arrived is `not_read_yet` and waits for slice 12 to read it; a work whose PDF has no text layer is
  `text_unreadable`; a work no route answered for is `no_fulltext`. The user's own decision stands above all three.
- **Nothing is dropped.** A work the limit does not reach is `not_reached`, gets no decision at all, and the next
  retrieval run starts from it. A work whose routes did not all answer gets no decision either and is tried again.
- **The same link is not requested twice.** A work already carrying a fresh code of this stage is not planned again,
  which is what "the next run continues where the first stopped" means.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.reason_codes import reason
from deixis.domain.rules import FULLTEXT_WORK_LIMIT

# The codes this stage owns. A fresh decision carrying any other code was written by the user or by the stage that
# reads the text (slice 12), and this stage neither confirms nor replaces it.
OWNED_CODES = ("not_read_yet", "text_unreadable", "no_fulltext")
# Which group of the retrieval order a work belongs to; the order of the tuple is the order they are fetched in.
GROUPS = ("user", "candidate", "unresolved")
# How many works one retrieval run fetches at once (slice 13e). Each host is still asked one request at a time
# (`documents.fetch.host_gate`), so this bounds the hosts in flight, not the requests to one publisher. The same for
# every effort; whether 4 is the right number was not measured.
FULLTEXT_FETCH_PARALLEL = 4


def fetch_budget(effort: str) -> dict[str, Any]:
    """The budget a full-text retrieval run is queued with. Read by the API route and by the flow's auto-queue, so
    a run the user starts and a run a discovery run leaves behind can never be given different room."""
    return {"max_model_calls": 0, "max_provider_requests": 0, "max_fulltext_works": FULLTEXT_WORK_LIMIT[effort]}


def _named(rows: list[dict[str, Any]], head: str) -> dict[str, Any]:
    """The row that speaks for the work: the head's when the head carries one, else the smallest identifier's.

    The same rule `DecisionStore.work_outcome` uses, so which version a provider happened to return first, and
    which decision happened to be written first, cannot change what the work reads as.
    """
    return min(rows, key=lambda row: (row["id"] != head, row["id"]))


def abstract_outcome(work: dict[str, Any]) -> dict[str, Any] | None:
    """The abstract decision that speaks for the work, or None when no version carries one.

    `work_outcome`'s rule for the abstract stage, read from the rows the caller already holds rather than from the
    store: a work with a candidate version is a candidate, a work out of scope in every version is out of scope,
    and anything else is unresolved. An abstract decision on one version never drops a work another version is
    still a candidate for.
    """
    rows = [dict(version["abstract"], id=version["id"]) for version in work["versions"] if version.get("abstract")]
    if not rows:
        return None
    outcomes = {row["id"]: reason(row["reason_code"]).outcome for row in rows}
    candidates = [row for row in rows if outcomes[row["id"]] == "candidate"]
    if candidates:
        return _named(candidates, work["head"])
    if all(outcome == "out_of_scope" for outcome in outcomes.values()):
        return _named(rows, work["head"])
    return _named([row for row in rows if outcomes[row["id"]] == "unresolved"], work["head"])


def decided_by_human(work: dict[str, Any], stage: str) -> bool:
    """Whether the user decided this work's stage themselves, on any version of it (SW11.7)."""
    return any(version[stage]["decided_by"] == "human" for version in work["versions"] if version.get(stage))


def group_of(work: dict[str, Any]) -> str | None:
    """Which retrieval group this work belongs to, or None when it is not fetched at all.

    1. The works the user named: a selection the user set to `included`. It is read before anything code decided,
       because the user's decision is above code's (AGENTS.md, User Authority).
    2. The works code or the two abstract runs left as candidates.
    3. The works the abstract stage left unresolved *and* routed here: `runs_agree_unresolved` and
       `abstract_not_found`, which the reason table already says have `fulltext_fetch` as their next step. A
       record the model has not read yet is routed back to the abstract stage and is not fetched: writing a
       full-text decision on it now would keep it `pending` even after its abstract turns out to be out of scope,
       because `work_outcome` lets the full-text stage answer first.

    Not fetched: a work whose full-text stage the user decided, a work the user excluded, a work out of scope, and
    a work with no abstract decision at all.
    """
    if decided_by_human(work, "fulltext"):
        return None
    selection = work.get("selection") or {}
    if selection.get("origin") == "user":
        return "user" if selection.get("state") == "included" else None
    abstract = abstract_outcome(work)
    if abstract is None:
        return None
    code = reason(abstract["reason_code"])
    if code.outcome == "candidate":
        return "candidate"
    if code.outcome == "unresolved" and code.next_step == "fulltext_fetch":
        return "unresolved"
    return None


def _settled(work: dict[str, Any]) -> bool:
    """Whether this stage already said its piece about the work under the question it is asking now."""
    fulltext = [version["fulltext"] for version in work["versions"] if version.get("fulltext")]
    return any(row["reason_code"] in OWNED_CODES and not row.get("stale") for row in fulltext)


def fetch_plan(works: list[dict[str, Any]], order: list[str], limit: int) -> dict[str, Any]:
    """The works this run fetches, the works its limit did not reach, and the works whose text is already here.

    The unit is the work (SW10.1). Each work is `{"work_id", "head", "versions": [...], "selection"}`, and each
    version carries `id`, `has_text`, and the `abstract` and `fulltext` decisions it holds as
    `{"reason_code", "decided_by", "stale"}` or None.

    Eligible works are fetched in group order (`GROUPS`), and inside a group in the inspection order the ranking
    stored; a work the ranking did not place goes last in its group, by identifier, so nothing depends on a
    dictionary's iteration. A work any version of which already has PDF text is not fetched — it goes to
    `already_text` and gets its code written straight away. A work already carrying a fresh code of this stage is
    in none of the three lists: the next run continues from where the first stopped rather than asking again.
    """
    place = {svid: position for position, svid in enumerate(order)}
    wanted: list[tuple[int, int, str, dict[str, Any]]] = []
    for work in works:
        group = group_of(work)
        if group is None:
            continue
        wanted.append((GROUPS.index(group), place.get(work["head"], len(place)), work["head"], work))
    wanted.sort(key=lambda row: row[:3])

    already_text, pending = [], []
    for _, _, head, work in wanted:
        if any(version.get("has_text") for version in work["versions"]):
            already_text.append(head)
        elif not _settled(work):
            pending.append(head)
    return {"works": pending[:limit], "not_reached": pending[limit:], "already_text": already_text}


def settled_code(attempt: dict[str, Any]) -> str | None:
    """The full-text reason code one work's retrieval attempt settled on, or None when nothing is settled yet.

    `attempt` is `{"has_text", "has_asset", "unanswered"}`: whether any version of the work now has PDF passages,
    whether a PDF was attached at all, and how many of the routes tried did not answer (a timeout, a lost
    connection, a 429 or a 5xx). A route that refused, answered 404, searched without a result or was never there
    has answered: the work has no open full text and says so.

    A work no route answered for gets no decision, so it is tried again by a later run — the same distinction D35
    draws between a link that refused and a link that timed out.
    """
    if attempt.get("has_text"):
        return "not_read_yet"
    if attempt.get("has_asset"):
        return "text_unreadable"
    return None if attempt.get("unanswered") else "no_fulltext"


def should_write(current: dict[str, Any] | None, code: str, stale: bool = False) -> bool:
    """Whether this stage writes `code` over the record's current full-text decision (`abstract_stage.should_write`).

    The same code again writes nothing, so a second retrieval run does not close a row and reopen it merely because
    its step identifier and protocol digest are new. A fresh code this stage does not own — the user's, or slice
    12's after it read the text — is left alone. A stale decision is always rewritten.
    """
    if current is None or stale:
        return True
    if current["reason_code"] == code:
        return False
    return current["reason_code"] in OWNED_CODES

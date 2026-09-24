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

from deixis.domain import canonical
from deixis.domain.reason_codes import REASON_CODES, reason
from deixis.domain.rules import CHAIN_PLAN_ROOM, FULLTEXT_WORK_LIMIT

# The codes this stage owns. A fresh decision carrying any other code was written by the user or by the stage that
# reads the text (slice 12), and this stage neither confirms nor replaces it.
OWNED_CODES = ("not_read_yet", "text_unreadable", "no_fulltext")
# Which group of the retrieval order a work belongs to; the order of the tuple is the order they are fetched in. The
# fourth group is the works citation chaining brought (D95): it has its own room and never takes a keyword work's.
GROUPS = ("user", "candidate", "unresolved", "chain")
KEYWORD_GROUPS = GROUPS[:3]
# How many works one retrieval run fetches at once (slice 13e). Each host is still asked one request at a time
# (`documents.fetch.host_gate`), so this bounds the hosts in flight, not the requests to one publisher. The same for
# every effort; whether 4 is the right number was not measured.
FULLTEXT_FETCH_PARALLEL = 4


def fetch_budget(effort: str) -> dict[str, Any]:
    """The budget a full-text retrieval run is queued with. Read by the API route and by the flow's auto-queue, so
    a run the user starts and a run a discovery run leaves behind can never be given different room.

    `chain_room` is the chain group's own room, on top of the keyword limit (D95). A run queued before D95 has none
    and plans no chain group."""
    return {"max_model_calls": 0, "max_provider_requests": 0, "max_fulltext_works": FULLTEXT_WORK_LIMIT[effort],
            "chain_room": CHAIN_PLAN_ROOM[effort]}


def overlap_budget(effort: str) -> dict[str, Any]:
    """The retrieval room an `sw` discovery run is queued with when its fetch overlaps its screening (slice 17a).

    `fetch_budget`'s room under an explicit mode: a discovery run queued before 17a carries none and leaves a separate
    retrieval run behind as it always did (decision 3).
    """
    return {"mode": "overlap", **fetch_budget(effort)}


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


def decided_by_human(work: dict[str, Any], stage: str, reading: bool = False) -> bool:
    """Whether the user decided this work's stage themselves, on any version of it (SW11.7).

    One exception, for the reading alone (`reading`; slice 18b, decision 3): a person's `human_pdf_wrong` speaks only
    for its own version's file, so it does not hold the work back from the reading while a file the person added to
    another version asks to be read (the version's `person` request). Every other decision of the person holds it
    back as before, and the retrieval never takes the exception: its plan is what it was before slice 18b."""
    asked = {version["id"] for version in work["versions"] if version.get("person")} if reading else set()
    return any(version[stage]["decided_by"] == "human"
               and not (stage == "fulltext" and version[stage]["reason_code"] == "human_pdf_wrong"
                        and asked - {version["id"]})
               for version in work["versions"] if version.get(stage))


def group_of(work: dict[str, Any], reading: bool = False) -> str | None:
    """Which retrieval group this work belongs to, or None when it is not fetched at all.

    1. The works the user named: a selection the user set to `included`. It is read before anything code decided,
       because the user's decision is above code's (AGENTS.md, User Authority).
    2. The works code or the two abstract runs left as candidates.
    3. The works the abstract stage left unresolved *and* routed here: `runs_agree_unresolved` and
       `abstract_not_found`, which the reason table already says have `fulltext_fetch` as their next step. A
       record the model has not read yet is routed back to the abstract stage and is not fetched: writing a
       full-text decision on it now would keep it `pending` even after its abstract turns out to be out of scope,
       because `work_outcome` lets the full-text stage answer first.

    4. The works citation chaining brought (`chained`, D95) that the abstract stage leaves a candidate or routes
       here, as in 2 and 3. A chained work the user included stays in the user's group.

    Not fetched: a work whose full-text stage the user decided, a work the user excluded, a work out of scope, and
    a work with no abstract decision at all. `reading` is passed by the reading plan and a person's attach alone:
    it takes `decided_by_human`'s slice-18b exception, which the retrieval does not.
    """
    if decided_by_human(work, "fulltext", reading):
        return None
    selection = work.get("selection") or {}
    if selection.get("origin") == "user":
        return "user" if selection.get("state") == "included" else None
    abstract = abstract_outcome(work)
    if abstract is None:
        return None
    code = reason(abstract["reason_code"])
    if code.outcome == "candidate":
        return "chain" if work.get("chained") else "candidate"
    if code.outcome == "unresolved" and code.next_step == "fulltext_fetch":
        return "chain" if work.get("chained") else "unresolved"
    return None


def _settled(work: dict[str, Any]) -> bool:
    """Whether this stage already said its piece about the work under the question it is asking now."""
    fulltext = [version["fulltext"] for version in work["versions"] if version.get("fulltext")]
    return any(row["reason_code"] in OWNED_CODES and not row.get("stale") for row in fulltext)


def fetch_plan(works: list[dict[str, Any]], order: list[str], limit: int, chain_order: list[str] | tuple[str, ...] = (),
               chain_room: int = 0) -> dict[str, Any]:
    """The works this run fetches, the works its limit did not reach, and the works whose text is already here.

    The unit is the work (SW10.1). Each work is `{"work_id", "head", "versions": [...], "selection"}`, and each
    version carries `id`, `has_text`, and the `abstract` and `fulltext` decisions it holds as
    `{"reason_code", "decided_by", "stale"}` or None.

    Eligible works are fetched in group order (`GROUPS`), and inside a group in the inspection order the ranking
    stored; a work the ranking did not place goes last in its group, by identifier, so nothing depends on a
    dictionary's iteration. A work any version of which already has PDF text is not fetched — it goes to
    `already_text` and gets its code written straight away. A work already carrying a fresh code of this stage is
    in none of the three lists: the next run continues from where the first stopped rather than asking again.

    The first three groups share `limit` and are planned exactly as they were before D95. The chain group comes
    after them, in `chain_order`, and takes at most `chain_room` works; room the chain leaves unused is not given to
    a keyword work, and a keyword work never takes the chain's.
    """
    place = {svid: position for position, svid in enumerate(order)}
    chain_place = {svid: position for position, svid in enumerate(chain_order)}
    wanted: list[tuple[int, int, str, dict[str, Any]]] = []
    for work in works:
        group = group_of(work)
        if group is None:
            continue
        where = chain_place if group == "chain" else place
        wanted.append((GROUPS.index(group), where.get(work["head"], len(where)), work["head"], work))
    wanted.sort(key=lambda row: row[:3])

    already_text, pending, chained = [], [], []
    for group, _, head, work in wanted:
        if any(version.get("has_text") for version in work["versions"]):
            already_text.append(head)
        elif not _settled(work):
            (chained if GROUPS[group] == "chain" else pending).append(head)
    return {"works": pending[:limit] + chained[:chain_room], "not_reached": pending[limit:] + chained[chain_room:],
            "already_text": already_text}


# A work of the fetch that overlaps discovery (slice 17a) whose attempt was cut by a crash is sent again on resume;
# after this many starts it is closed as not settled instead, and a later run tries it again (D18).
FULLTEXT_WORK_ATTEMPTS = 3
# What a work whose abstract batch is still open is counted as when the safe set is computed: the outcome that takes
# a slot ahead of the most works (a candidate), whatever the model later says.
WORST_CASE = {"reason_code": "blocks_in_title", "decided_by": "code", "stale": False}


def baseline_of(works: list[dict[str, Any]], **fixed: Any) -> dict[str, Any]:
    """The works this stage has already settled and the works with PDF text, by `work_id`, at one moment (slice 17a).

    Taken once, when the abstract code step ends and before the fetch that overlaps discovery starts, so the plan is
    computed against what was there before that fetch, never against what it wrote itself. `fixed` is what the
    proof rests on besides (the revision, the criterion, the room, the keyword order); the digest covers everything
    but itself, and the lists are sorted, so the same works read in another order give the same digest.
    """
    body = {"version": 1, **fixed,
            "settled": sorted(work["work_id"] for work in works if _settled(work)),
            "has_text": sorted(work["work_id"] for work in works
                               if any(version.get("has_text") for version in work["versions"]))}
    return body | {"hash": canonical.sha256_hex(body)}


def as_of_baseline(works: list[dict[str, Any]], baseline: dict[str, Any],
                   pending: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """These works as the plan reads them under `baseline`, with every `pending` work counted as a candidate.

    The codes this stage owns and the PDF text are read from the baseline alone: a work the overlapping fetch already
    settled, or gave a text, stays in the plan it was claimed under instead of dropping out of it and letting the works
    behind it move up (Sol, finding 4). A decision a person or the reading stage wrote is kept as it is.
    """
    settled, has_text = set(baseline["settled"]), set(baseline["has_text"])
    out = []
    for work in works:
        versions = []
        for version in work["versions"]:
            row = version.get("fulltext")
            if row is not None and row["reason_code"] in OWNED_CODES and row["decided_by"] != "human":
                row = None
            versions.append(dict(version, has_text=work["work_id"] in has_text, fulltext=row,
                                 **({"abstract": WORST_CASE} if work["work_id"] in pending else {})))
        if work["work_id"] in settled and versions:
            at = next((i for i, version in enumerate(versions)
                       if (version["fulltext"] or {}).get("decided_by") != "human"), 0)
            versions[at] = dict(versions[at], fulltext={"reason_code": OWNED_CODES[0], "decided_by": "code",
                                                        "stale": False})
        out.append(dict(work, versions=versions))
    return out


def safe_to_fetch(works: list[dict[str, Any]], order: list[str], limit: int, chain_order: list[str] | tuple[str, ...],
                  room: int, pending: set[str] | frozenset[str], baseline: dict[str, Any]) -> list[str]:
    """The works that may be fetched now, by `work_id` in plan order, while the abstract stage is still deciding others.

    A work is safe when its own abstract decision is final (it is not `pending`) and it is inside the plan in which
    every pending work comes out a candidate. No pending work can take a slot the worst case did not already give it:
    one that ends out of scope leaves the plan, and one that ends unresolved moves to a later group, so the works
    behind it only move up (slice 17a, decision 2).
    """
    plan = fetch_plan(as_of_baseline(works, baseline, pending), order, limit, chain_order, room)
    work_of = {work["head"]: work["work_id"] for work in works}
    return [work_of[head] for head in plan["works"] if work_of[head] not in pending]


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


# ---- the works waiting for a person's PDF (slice 18a) ----------------------------------------------------------

# Every code whose next step is a PDF from the person, read from the reason table so a code added there is listed.
WAITING_CODES = tuple(code for code, entry in REASON_CODES.items() if entry.next_step == "waiting_for_pdf")
# `DecisionStore.work_outcome`'s order among fresh full-text outcomes; this module stays free of the store.
FULLTEXT_OUTCOMES = ("include", "criterion_not_met", "unresolved")


def current_fulltext(work: dict[str, Any]) -> dict[str, Any] | None:
    """The full-text decision that speaks for the work, `DecisionStore.work_outcome`'s rule on the rows in hand.

    The user's newest decision first, stale or not; else the fresh decisions, the best outcome named by the head. Two
    versions at opposite fresh decisions speak for nothing here: that work is the human queue's (`versions_disagree`).
    Each row is `{"id", "reason_code", "decided_by", "stale", "created_at", "order"}`, the version's identifier as
    `id` and the order the rows were written in as `order` (the store's rowid), which settles two decisions written in
    the same millisecond as `work_outcome` settles them.
    """
    rows = [dict(version["fulltext"], id=version["id"]) for version in work["versions"] if version.get("fulltext")]
    human = sorted((row for row in rows if row["decided_by"] == "human"), key=lambda row: (row.get("created_at") or "", row.get("order") or 0))
    if human:
        return human[-1]
    fresh = [row for row in rows if not row["stale"]]
    outcomes = {reason(row["reason_code"]).outcome for row in fresh}
    if not fresh or {"include", "criterion_not_met"} <= outcomes:
        return None
    best = next(outcome for outcome in FULLTEXT_OUTCOMES if outcome in outcomes)
    return _named([row for row in fresh if reason(row["reason_code"]).outcome == best], work["head"])


def waiting(works: list[dict[str, Any]], plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The works that wait for the person's PDF, in reading order, each with the decision that put it here.

    A work waits when its current full-text decision (`current_fulltext`) is fresh, carries a code whose next step
    is `waiting_for_pdf`, and no version of it has PDF text. A person's `human_pdf_wrong` keeps the work here even
    though the file they judged is still attached: that version's text does not count, another version's does. A
    stale decision lists nothing, whoever wrote it: the question moved on, and a stale decision of the person's is
    the queue's to ask again (`look_again`). A work the plan did not reach has no decision and is not listed.

    `plans` are the stored retrieval plans of the question revision, newest first. The order is the newest plan's,
    then an older plan's for a work settled before it (a later plan leaves a settled work out), then the head for a
    work no plan fetched; a work is matched to a plan through any of its versions, so a head that changed since the
    plan was written keeps the work's place. No plan, no list.
    """
    if not plans:
        return []
    place: dict[str, tuple[int, int]] = {}
    for age, plan in enumerate(plans):
        for position, head in enumerate(plan.get("works") or []):
            place.setdefault(head, (age, position))
    rows = []
    for work in works:
        decision = current_fulltext(work)
        if decision is None or decision["stale"] or decision["reason_code"] not in WAITING_CODES:
            continue
        judged = decision["id"] if decision["reason_code"] == "human_pdf_wrong" else None
        if any(version.get("has_text") and version["id"] != judged for version in work["versions"]):
            continue
        at = min((place[version["id"]] for version in work["versions"] if version["id"] in place), default=None)
        rows.append({"work_id": work["work_id"], "head": work["head"], "source_version_id": decision["id"],
                     "reason_code": decision["reason_code"], "decided_by": decision["decided_by"], "_at": at})
    rows.sort(key=lambda row: (row["_at"] is None, row["_at"] or (0, 0), row["head"]))
    return [{key: value for key, value in row.items() if key != "_at"} | {"place": n}
            for n, row in enumerate(rows, start=1)]

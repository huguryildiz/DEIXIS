"""The human queue of an `sw` research: what a person is asked, and what their answer writes (SW11, slice 16, D96).

The queue is not stored. Every row is derived, each time it is read, from the decisions `DecisionStore.work_outcome`
already reads: a work whose outcome routes it to `human_queue`, or whose versions reached opposite full-text
decisions, is one row. A stored queue would go stale the moment the question or the criterion changed; a derived one
cannot. Reading the queue opens no step and writes nothing.

A person's answer is a stage decision like any other, with `decided_by = 'human'`, written on the version the row
names. `include` and `criterion_not_met` also set the work head's selection as the user's, in the same transaction,
and a link row records which selection the decision wrote so undoing it releases that selection only while nobody
changed it since. The row token carries everything that may move between showing a row and answering it; the answer
recomputes it inside the write and is refused (409) when it no longer matches.

Nothing here is about a topic: the question, the cue sentences and the order come from the frozen criterion's parts and
the stored rankings.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from contextlib import contextmanager
from typing import Any, Iterator

from deixis.domain.canonical import sha256_hex
from deixis.domain.contracts import locate_anchor
from deixis.domain.reason_codes import REASON_CODES
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import now, transaction
from deixis.workflow.criterion_passages import compile_phrases
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import NotASource, Store

# Every code whose next step is the queue, read from the reason table so a code added there is asked about here.
QUEUE_CODES = tuple(code for code, entry in REASON_CODES.items() if entry.next_step == "human_queue")
# `versions_disagree` is never stored: `work_outcome` derives it from two versions' fresh decisions (Sol's finding).
VERSIONS_DISAGREE = "versions_disagree"
KIND_OF = {"include_quote_unverified": "confirm_quote", "fulltext_runs_disagree": "choose_run",
           VERSIONS_DISAGREE: "choose_version", "pdf_identity_unconfirmed": "confirm_pdf",
           "fulltext_runs_agree_unresolved": "find_part",
           # Unreachable today (no stage writes it); its question is whether the promised part is in the text.
           "abstract_promise_absent": "find_part"}
LOOK_AGAIN = "look_again"
ANSWERS = {"include": "human_include", "criterion_not_met": "human_criterion_not_met",
           "not_sure": "human_not_sure", "pdf_wrong": "human_pdf_wrong"}
PDF_CONFIRMED = "pdf_confirmed"
SELECTION_OF = {"human_include": "included", "human_criterion_not_met": "excluded"}
VERIFIED_CODES = ("human_include", "human_criterion_not_met")
CONFIRMED_NOTE = "pdf_confirmed:"
CUE_SENTENCES = 5


class QueueUnavailable(Exception):
    """The research is not on the `sw` workflow, or the answer does not fit the row; the API answers 422."""


# ---- reading ----------------------------------------------------------------------------------------------------


@contextmanager
def _snapshot(conn: Any) -> Iterator[None]:
    """One read transaction, so every row is derived from the same state. Nothing is written inside it."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    finally:
        conn.execute("COMMIT")


class _Context:
    """What deriving rows reads once per call: the facts, selections, links, criterion, order and proposals."""

    def __init__(self, store: Store, research_id: str, work_id: str | None = None):
        scope = store.scope(research_id)
        if scope.get("search_workflow") != "sw":
            raise QueueUnavailable("The queue belongs to the search workflow")
        self.store, self.rid = store, research_id
        self.decisions = DecisionStore(store)
        self.facts = self.decisions.facts(research_id, work_id)
        self.revision = self.facts["stale_key"][0]
        conn = store.conn
        self.selections = {row["source_version_id"]: dict(row) for row in conn.execute(
            "SELECT source_version_id, state, origin, version FROM selections WHERE research_id = ?", (research_id,))}
        # The current link of every decision still open: its newest row (D71, added never edited).
        self.links: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
                "SELECT l.* FROM human_selection_links l JOIN stage_decisions d ON d.id = l.decision_id"
                " WHERE l.research_id = ? AND d.superseded_at IS NULL ORDER BY l.created_at, l.rowid", (research_id,)):
            self.links[row["decision_id"]] = dict(row)
        self.assets: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
                "SELECT a.id, a.source_version_id, a.identity_confirmed_at FROM source_assets a"
                " JOIN corpus_memberships m ON m.source_version_id = a.source_version_id AND m.research_id = ?"
                " AND m.removed_at IS NULL WHERE a.removed_at IS NULL ORDER BY a.retrieved_at DESC, a.id DESC",
                (research_id,)):
            self.assets.setdefault(row["source_version_id"], dict(row))
        frozen = store.frozen_criterion(research_id, scope["question"], scope.get("steering"))
        parts = (frozen or {}).get("parts") or []
        self.criterion = frozen
        self.parts = ([{"name": part["name"], "definition": part["definition"]} for part in parts] if parts
                      else [{"name": "criterion", "definition": frozen["criterion"]}] if frozen else [])
        self.chained = store.chain_only_works(research_id, self.revision)
        self._place: dict[str, int] | None = None
        self._runs: dict[str, str] | None = None
        self._proposals: dict[tuple[str, str], dict[str, dict[int, dict[str, Any]]]] | None = None

    # The fused order (SW11.7, D95): keyword works by the latest keyword ranking, chained works after them by the
    # latest chain ranking. A work neither ranking placed has no place and goes last, by its head.
    def place(self) -> dict[str, int]:
        if self._place is None:
            keyword = self.decisions.latest_ranking(self.rid, self.revision) or []
            chain = self.decisions.latest_chain_ranking(self.rid, self.revision)
            work_of = self.store.work_ids(list(dict.fromkeys(keyword + chain)))
            fused: dict[str, int] = {}
            for arm, order in ((False, keyword), (True, chain)):
                for svid in order:
                    work_id = work_of.get(svid)
                    if work_id is not None and (work_id in self.chained) == arm:
                        fused.setdefault(work_id, len(fused) + 1)
            self._place = fused
        return self._place

    def run_of_step(self) -> dict[str, str]:
        if self._runs is None:
            self._runs = {row[0]: row[1] for row in self.store.conn.execute(
                "SELECT s.id, s.run_id FROM run_steps s JOIN runs r ON r.id = s.run_id"
                " WHERE r.research_id = ? AND s.kind = 'model:fulltext_adjudication'", (self.rid,))}
        return self._runs

    def proposals(self, svid: str, run_id: str | None) -> dict[str, dict[int, dict[str, Any]]]:
        """The reading run's proposals for this version, by part and run number."""
        if self._proposals is None:
            runs = self.run_of_step()
            grouped: dict[tuple[str, str], dict[str, dict[int, dict[str, Any]]]] = {}
            for row in self.store.conn.execute(
                    "SELECT * FROM model_proposals WHERE research_id = ? AND stage = 'fulltext'"
                    " ORDER BY created_at, rowid", (self.rid,)):
                key = (row["source_version_id"], runs.get(row["step_id"], ""))
                grouped.setdefault(key, {}).setdefault(row["criterion_part"], {})[row["run_no"]] = dict(row)
            self._proposals = grouped
        return self._proposals.get((svid, run_id or ""), {})

    def part_names(self, proposals: dict[str, Any]) -> list[str]:
        names = [part["name"] for part in self.parts]
        return names + sorted(name for name in proposals if name not in names)

    def definition(self, name: str | None) -> str | None:
        return next((part["definition"] for part in self.parts if part["name"] == name), None)


def _token(ctx: _Context, work_id: str, svid: str, reason_code: str | None, head: str | None) -> str:
    """What must not move between showing a row and answering it (Sol's finding: one decision id is not enough)."""
    decisions = sorted(d["id"] for d in ctx.facts["decisions"].get(work_id, []) if d["stage"] == "fulltext")
    selection = ctx.selections.get(head) if head else None
    return sha256_hex({
        "revision": ctx.revision, "criterion_hash": ctx.facts["stale_key"][1], "decisions": decisions,
        "reason_code": reason_code, "head": head, "selection_version": selection["version"] if selection else None,
        "member": ctx.store.is_active_member(ctx.rid, svid), "asset": (ctx.assets.get(svid) or {}).get("id"),
    })


def _question(ctx: _Context, kind: str, proposals: dict[str, dict[int, dict[str, Any]]]) -> dict[str, Any] | None:
    """The one part the row asks about: the first, in the criterion's order, the two runs did not settle."""
    if kind in ("confirm_pdf", "choose_version", LOOK_AGAIN) and not proposals:
        return None
    for name in ctx.part_names(proposals):
        runs = proposals.get(name, {})
        if kind == "confirm_quote":
            if any(row["label"] == "present" and not row["quote_verified"] for row in runs.values()):
                return {"part": name, "definition": ctx.definition(name)}
            continue
        settled = len(runs) == 2 and all(row["label"] == "present" and row["quote_verified"] for row in runs.values())
        if not settled:
            return {"part": name, "definition": ctx.definition(name)}
    return None


def _kind(reason_code: str, proposals: dict[str, dict[int, dict[str, Any]]]) -> str:
    if reason_code == "part_without_evidence":
        both_absent = any(len(runs) == 2 and all(row["label"] == "absent" for row in runs.values())
                          for runs in proposals.values())
        return "confirm_absent" if both_absent else "find_part"
    return KIND_OF[reason_code]


def _classify(ctx: _Context, work_id: str) -> dict[str, Any] | None:
    """Where the work stands for the queue: an open row, a `look_again` row, a fresh human decision, or nothing."""
    outcome = ctx.decisions.work_outcome(ctx.rid, work_id, ctx.facts)
    if not outcome or outcome["stage"] != "fulltext":
        return None
    fulltext = [d for d in ctx.facts["decisions"].get(work_id, []) if d["stage"] == "fulltext"]
    head = ctx.facts["heads"].get(work_id)
    if outcome["decided_by"] == "human":
        decision = [d for d in fulltext if d["decided_by"] == "human"][-1]  # the one `work_outcome` reads
        stale = ctx.decisions.is_stale(decision, ctx.facts["stale_key"])
        return {"state": LOOK_AGAIN if stale else "decided", "decision": decision, "head": head,
                "reason_code": decision["reason_code"], "stale": stale}
    code = outcome["reason_code"]
    if code != VERSIONS_DISAGREE and code not in QUEUE_CODES:
        return None
    decision = next(d for d in fulltext if d["source_version_id"] == outcome["source_version_id"])
    selection = ctx.selections.get(head) or {}
    # A selection the user set from the source list keeps the work out of the queue; one the queue wrote does not.
    owned = any(link["head"] == head and link["selection_version"] == selection.get("version")
                for link in ctx.links.values())
    if selection.get("origin") == "user" and not owned:
        return {"state": "user_selected", "decision": decision, "head": head, "reason_code": code, "stale": False}
    return {"state": "open", "decision": decision, "head": head, "reason_code": code, "stale": False}


def _row(ctx: _Context, work_id: str, found: dict[str, Any]) -> dict[str, Any]:
    decision, head = found["decision"], found["head"]
    svid = decision["source_version_id"]
    run_id = ctx.run_of_step().get(decision["step_id"] or "")
    proposals = ctx.proposals(svid, run_id)
    kind = LOOK_AGAIN if found["state"] == LOOK_AGAIN else _kind(found["reason_code"], proposals)
    source = ctx.store.source(svid)
    return {
        "source_version_id": svid, "head": head, "work_id": work_id, "title": source["title"],
        "year": source["year"], "doi": source["doi"], "version_label": source["version_label"],
        "publication_type": source["publication_type"], "reason_code": found["reason_code"], "kind": kind,
        "question": _question(ctx, kind, proposals), "place": ctx.place().get(work_id),
        "arm": "chain" if work_id in ctx.chained else "keyword", "stale": found["stale"],
        "decision_id": decision["id"], "row_token": _token(ctx, work_id, svid, found["reason_code"], head),
    }


def _order_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["kind"] == LOOK_AGAIN, row["place"] is None, row["place"] or 0, row["arm"] == "chain", row["head"])


def _scan(ctx: _Context) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    found: list[tuple[str, dict[str, Any]]] = []
    by_reason: Counter[str] = Counter()
    decided: Counter[str] = Counter()
    look_again = user_selected = 0
    for work_id in sorted(ctx.facts["heads"]):
        state = _classify(ctx, work_id)
        if state is None:
            continue
        if state["state"] == "decided":
            decided[state["reason_code"]] += 1
        elif state["state"] == "user_selected":
            user_selected += 1
        else:
            found.append((work_id, state))
            if state["state"] == LOOK_AGAIN:
                look_again += 1
            else:
                by_reason[state["reason_code"]] += 1
    counts = {"open": sum(by_reason.values()), "by_reason": dict(sorted(by_reason.items())), "look_again": look_again,
              "decided": dict(sorted(decided.items())), "user_selected": user_selected}
    return found, counts


def queue_rows(store: Store, research_id: str) -> dict[str, Any]:
    """Every row of the research's queue in the fused order, `look_again` last, with the queue's counts."""
    with _snapshot(store.conn):
        ctx = _Context(store, research_id)
        found, counts = _scan(ctx)
        rows = sorted((_row(ctx, work_id, state) for work_id, state in found), key=_order_key)
    counts["by_kind"] = dict(sorted(Counter(row["kind"] for row in rows if row["kind"] != LOOK_AGAIN).items()))
    return {"rows": rows, "counts": counts, "order": "fused_rank"}


def queue_counts(store: Store, research_id: str) -> dict[str, int]:
    """The two numbers the research view shows, from one read of the facts and no row built."""
    with _snapshot(store.conn):
        _, counts = _scan(_Context(store, research_id))
    return {"queue": counts["open"], "look_again": counts["look_again"]}


def verified_records(store: Store, research_id: str) -> list[dict[str, Any]]:
    """The works a person included or excluded, for slice 19 to read (SW11.13). Nothing here changes a rule.

    `human_not_sure` and `human_pdf_wrong` are not verified: they say the person could not tell.
    """
    with _snapshot(store.conn):
        ctx = _Context(store, research_id)
        rows = []
        for work_id in sorted(ctx.facts["heads"]):
            state = _classify(ctx, work_id)
            if state is None or state["state"] not in ("decided", LOOK_AGAIN):
                continue
            decision = state["decision"]
            if decision["reason_code"] not in VERIFIED_CODES:
                continue
            rows.append({"work_id": work_id, "source_version_id": decision["source_version_id"],
                         "decision_id": decision["id"], "reason_code": decision["reason_code"],
                         "outcome": decision["outcome"], "criterion_hash": decision["criterion_hash"],
                         "scope_revision": decision["scope_revision"], "stale": state["stale"]})
    return rows


# ---- one row in full -----------------------------------------------------------------------------------------------


def _state_of(ctx: _Context, svid: str) -> dict[str, Any]:
    """The row this version heads now (or None), its token, and the version's current full-text decision."""
    work_id = ctx.store.source(svid)["work_id"]
    found = _classify(ctx, work_id)
    row = None
    if found is not None and found["state"] in ("open", LOOK_AGAIN) and found["decision"]["source_version_id"] == svid:
        row = _row(ctx, work_id, found)
    current = ctx.decisions.current(ctx.rid, svid, "fulltext")
    head = ctx.facts["heads"].get(work_id)
    reason_code = row["reason_code"] if row else (current or {}).get("reason_code")
    return {"work_id": work_id, "head": head, "row": row, "current": current,
            "token": row["row_token"] if row else _token(ctx, work_id, svid, reason_code, head)}


def _decision_view(ctx: _Context, state: dict[str, Any]) -> dict[str, Any] | None:
    current = state["current"]
    if current is None:
        return None
    return {"id": current["id"], "reason_code": current["reason_code"], "decided_by": current["decided_by"],
            "stale": ctx.decisions.is_stale(current, ctx.facts["stale_key"]),
            "undoable": current["decided_by"] == "human" or _confirmed_asset(current) is not None}


def _confirmed_asset(decision: dict[str, Any]) -> str | None:
    note = decision.get("note") or ""
    if decision["reason_code"] == "not_read_yet" and note.startswith(CONFIRMED_NOTE):
        return note.removeprefix(CONFIRMED_NOTE)
    return None


def row_detail(store: Store, research_id: str, source_version_id: str) -> dict[str, Any]:
    """One row with what a person needs to answer it; for a version with no row, its current decision and undo token.

    Everything computed here (cue sentences, the closest passage) is read from the page text and only shown.
    """
    _require_source(store, research_id, source_version_id)
    with _snapshot(store.conn):
        ctx = _Context(store, research_id, store.source(source_version_id)["work_id"])
        state = _state_of(ctx, source_version_id)
        view: dict[str, Any] = {"row": state["row"], "decision": _decision_view(ctx, state),
                                "undo_token": state["token"]}
        if state["row"] is not None:
            view["detail"] = _detail(ctx, state["row"])
    return view


def _step_output(store: Store, step_id: str) -> dict[str, Any]:
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE id = ?", (step_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def _shown_pages(store: Store, step_id: str) -> list[int]:
    row = store.conn.execute("SELECT payload_json FROM step_inputs WHERE step_id = ? ORDER BY attempt DESC, rowid DESC"
                             " LIMIT 1", (step_id,)).fetchone()
    if row is None:
        return []
    pages = {(passage.get("locator") or {}).get("physical_page") for passage in json.loads(row[0]).get("passages") or []}
    return sorted(page for page in pages if isinstance(page, int))


def _closest(quote: str, pages: dict[int, str], shown: list[int]) -> dict[str, Any] | None:
    """The nearest text to a quote code did not verify, looked for only on the pages that run was shown."""
    best = None
    for page in shown:
        match = locate_anchor(quote, pages.get(page) or "")
        if match is not None and (best is None or match.ratio > best["ratio"]):
            best = {"page": page, "text": match.text, "kind": match.kind, "ratio": match.ratio}
    return best


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s]


def _cues(ctx: _Context, part: str | None, pages: dict[int, str]) -> dict[str, Any]:
    """Sentences holding one of the question part's own cue phrases, with their pages; unassigned phrases go nowhere."""
    phrases = [row for row in ((ctx.criterion or {}).get("cue_phrases") or []) if part and row.get("part") == part]
    patterns = compile_phrases(phrases)["patterns"]
    found = []
    for page in sorted(pages):
        for sentence in _sentences(pages[page]):
            if any(pattern.search(sentence) for _, pattern in patterns):
                found.append({"page": page, "sentence": sentence})
    return {"phrases": [phrase for phrase, _ in patterns], "sentences": found[:CUE_SENTENCES], "total": len(found),
            "note": None if found else "no cue found"}


def _detail(ctx: _Context, row: dict[str, Any]) -> dict[str, Any]:
    store, svid = ctx.store, row["source_version_id"]
    decision = next(d for d in ctx.facts["decisions"][row["work_id"]] if d["id"] == row["decision_id"])
    run_id = ctx.run_of_step().get(decision["step_id"] or "")
    proposals = ctx.proposals(svid, run_id)
    pages = store.page_texts(svid)
    steps = {n: r["step_id"] for runs in proposals.values() for n, r in runs.items()}
    shown = {n: _shown_pages(store, step_id) for n, step_id in steps.items()}
    rationale = {n: {p.get("part"): p.get("rationale") for p in ((_step_output(store, step_id).get("result") or {})
                                                                  .get("parts") or [])}
                 for n, step_id in steps.items()}
    runs = []
    for run_no in sorted(steps):
        parts = []
        for name in ctx.part_names(proposals):
            found = proposals.get(name, {}).get(run_no)
            if found is None:
                continue
            passage = store.conn.execute("SELECT text FROM passages WHERE id = ?",
                                         (found["quote_passage_id"],)).fetchone() if found["quote_passage_id"] else None
            unverified = found["label"] == "present" and not found["quote_verified"] and found["quote"]
            closest = _closest(found["quote"], pages, shown[run_no]) if unverified else None
            parts.append({"part": name, "label": found["label"], "quote": found["quote"],
                          "quote_verified": None if found["quote_verified"] is None else bool(found["quote_verified"]),
                          "page": found["quote_page"], "passage": passage[0] if passage else None,
                          "rationale": rationale[run_no].get(name),
                          **({"closest": closest,
                              "closest_note": None if closest else "no close text on the shown pages"}
                             if unverified else {})})
        runs.append({"run_no": run_no, "shown_pages": shown[run_no], "parts": parts})
    detail: dict[str, Any] = {"runs": runs, "cues": _cues(ctx, (row["question"] or {}).get("part"), pages)}
    if row["kind"] == "confirm_pdf":
        asset = ctx.assets.get(svid)
        head = store.source(row["head"])
        stored = store.asset(asset["id"]) if asset else {}
        detail["identity"] = {"first_page": pages[min(pages)] if pages else None, "work_title": head["title"],
                              "work_doi": head["doi"], "asset_id": stored.get("id"),
                              "retrieved_from": stored.get("retrieved_from"), "page_count": stored.get("page_count")}
    return detail


# ---- writing --------------------------------------------------------------------------------------------------------


def _require_source(store: Store, research_id: str, svid: str) -> None:
    """A record that was never a source of the research is refused (422); one removed since reaches the token (409)."""
    if store.scope(research_id).get("search_workflow") != "sw":
        raise QueueUnavailable("The queue belongs to the search workflow")
    if not store.was_member(research_id, svid):
        raise NotASource(svid)


def _check(state: dict[str, Any], token: str) -> None:
    if token != state["token"]:
        raise RevisionConflict("This row changed since it was shown; read it again")


def _result(store: Store, research_id: str, svid: str) -> dict[str, Any]:
    ctx = _Context(store, research_id, store.source(svid)["work_id"])
    state = _state_of(ctx, svid)
    selection = ctx.selections.get(state["head"]) if state["head"] else None
    return {"row": state["row"], "selection": selection, "decision": _decision_view(ctx, state),
            "undo_token": state["token"]}


def _link_valid(ctx: _Context, link: dict[str, Any] | None) -> bool:
    if link is None:
        return False
    selection = ctx.selections.get(link["head"]) or {}
    return selection.get("origin") == "user" and selection.get("version") == link["selection_version"]


def decide(store: Store, research_id: str, source_version_id: str, answer: str, note: str | None,
           row_token: str) -> dict[str, Any]:
    """Write a person's answer to one row, in one short transaction: decision, selection, link, history and event."""
    _require_source(store, research_id, source_version_id)
    svid = source_version_id
    with transaction(store.conn):
        ctx = _Context(store, research_id, store.source(svid)["work_id"])
        state = _state_of(ctx, svid)
        if state["row"] is None:
            raise RevisionConflict("This record has no open row in the queue")
        _check(state, row_token)
        row, decisions = state["row"], ctx.decisions
        if answer == PDF_CONFIRMED:
            if row["kind"] != "confirm_pdf":
                raise QueueUnavailable("Only a PDF identity row can be confirmed")
            asset = ctx.assets.get(svid)
            if asset is None:
                raise RevisionConflict("This record has no PDF in use")
            ts = now()
            store.conn.execute("UPDATE source_assets SET identity_confirmed_at = ? WHERE id = ?", (ts, asset["id"]))
            # The one code decision written outside a step (`step_id` NULL): its note and the file's mark say why.
            written = decisions.record(research_id, svid, "not_read_yet", note=f"{CONFIRMED_NOTE}{asset['id']}")
            store._event(research_id, "pdf_identity_confirmed", {"source_version_id": svid, "asset_id": asset["id"],
                                                                 "decision_id": written["id"]})
        else:
            code = ANSWERS[answer]
            previous = state["current"]
            prior_link = ctx.links.get(previous["id"]) if previous and previous["decided_by"] == "human" else None
            written = decisions.record(research_id, svid, code, note=note, renew_stale=True)
            head = state["head"]
            selection = ctx.selections.get(head) if head else None
            if code in SELECTION_OF and selection is not None:
                changed = store.set_user_selection(research_id, head, SELECTION_OF[code], selection["version"], code)
                store.conn.execute(
                    "INSERT INTO human_selection_links (decision_id, research_id, head, selection_version, created_at)"
                    " VALUES (?, ?, ?, ?, ?)", (written["id"], research_id, head, changed["version"], now()))
            elif _link_valid(ctx, prior_link):
                # The earlier answer wrote the selection and nobody changed it since; the new answer does not set one.
                store.release_user_selection(research_id, prior_link["head"], prior_link["selection_version"],
                                             f"released: {code} replaced a queue decision")
            store._event(research_id, "stage_decision_recorded",
                         {"source_version_id": svid, "decision_id": written["id"], "reason_code": code,
                          "decided_by": "human", "head": head})
        decisions.derive_selection(research_id, state["work_id"])
        return _result(store, research_id, svid)


def _reading_opened_since(store: Store, research_id: str, work_id: str, since: str) -> bool:
    """Whether a reading step for this work was opened by a run whose plan was frozen after `since`.

    A run whose plan was frozen before the confirmation held the work back as unconfirmed and never reads it, so only
    a later plan can have opened one; its step, sent or not, means the reading began.
    """
    versions = {row[0] for row in store.conn.execute("SELECT id FROM source_versions WHERE work_id = ?", (work_id,))}
    for row in store.conn.execute(
            "SELECT s.operation_key FROM run_steps s JOIN runs r ON r.id = s.run_id"
            " JOIN run_steps p ON p.run_id = r.id AND p.operation_key = 'adjudication_plan'"
            " WHERE r.research_id = ? AND s.kind = 'model:fulltext_adjudication' AND p.finished_at >= ?",
            (research_id, since)):
        head = row[0].removeprefix("fulltext_adjudication:").rpartition(":")[0]
        if head in versions:
            return True
    return False


def undo(store: Store, research_id: str, source_version_id: str, row_token: str) -> dict[str, Any]:
    """Take back a person's decision on this version, or their PDF confirmation while no reading has begun."""
    _require_source(store, research_id, source_version_id)
    svid = source_version_id
    with transaction(store.conn):
        ctx = _Context(store, research_id, store.source(svid)["work_id"])
        state = _state_of(ctx, svid)
        _check(state, row_token)
        current, decisions = state["current"], ctx.decisions
        if current is not None and current["decided_by"] == "human":
            link = ctx.links.get(current["id"])
            restored = decisions.undo_human(research_id, svid, "fulltext")
            if _link_valid(ctx, link):
                store.release_user_selection(research_id, link["head"], link["selection_version"],
                                             "released: the queue decision that set it was undone")
            store._event(research_id, "stage_decision_undone",
                         {"source_version_id": svid, "decision_id": current["id"],
                          "restored_id": restored["id"] if restored else None})
        elif current is not None and (asset_id := _confirmed_asset(current)) is not None:
            asset = ctx.assets.get(svid)
            if asset is None or asset["id"] != asset_id or not asset["identity_confirmed_at"]:
                raise RevisionConflict("The confirmed PDF is no longer the one in use")
            if _reading_opened_since(store, research_id, state["work_id"], current["created_at"]):
                raise RevisionConflict("The reading of this PDF has begun; decide about the work instead")
            store.conn.execute("UPDATE source_assets SET identity_confirmed_at = NULL WHERE id = ?", (asset_id,))
            decisions.record(research_id, svid, "pdf_identity_unconfirmed", note="pdf_confirmation_undone")
            store._event(research_id, "pdf_identity_revoked", {"source_version_id": svid, "asset_id": asset_id})
        else:
            raise RevisionConflict("Nothing on this record can be undone")
        decisions.derive_selection(research_id, state["work_id"])
        return _result(store, research_id, svid)


def confirmed_pdf(store: Store, asset_id: str | None) -> bool:
    """Whether a person confirmed this file as the work's own PDF (`flow._user_supplied_pdf`)."""
    if not asset_id:
        return False
    row = store.conn.execute("SELECT identity_confirmed_at FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
    return bool(row and row[0])


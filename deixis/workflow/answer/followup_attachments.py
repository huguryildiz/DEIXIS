"""What the person selected before they asked a follow-up, bound to the source it came from.

The chat box takes one question. Text the person picks in an answer, in a report sentence, in a passage or in an
evidence cell travels beside it as an attachment, not inside the question, so the quote does not eat the question's
character budget and the selection keeps an identity.

The client sends only the kind of thing it selected, that thing's id and the text. Every work, version and page comes
from stored rows here, never from the client: an id that names no row of this research is refused, while a row of this
research whose passage is no longer readable here keeps its text and records why it binds to nothing. One attachment
can bind to several works, because a claim or a cell can rest on several, so the bindings are a list.

A report sentence is the one case that does not read the live record: a report's citation may name an evidence cell,
and that cell's value and quotes are frozen in the report's own snapshot, so the cell is followed there and not to the
cell as it stands now.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.workflow.answer import answer as fast_answer

MAX_ATTACHMENTS = 4
MAX_TEXT_CHARS = 800
# Bindings the model reads for one selection. A report sentence can rest on dozens of passages through its cells;
# the record keeps them all, the model reads the first ones in order and is told how many are left out.
MAX_CONTEXT_BINDINGS = 8
KINDS = ("passage", "cell", "answer_claim", "followup_claim", "report_claim", "text")
# Why an attachment of this research binds to no passage the run may read. Each is a state the person can see; none of
# them is an error, and none of them makes the selected text disappear.
REASONS = ("source_removed", "passage_not_current", "cell_not_filled", "cell_has_no_located_quote",
           "claim_has_no_citation", "nothing_readable", "not_given")


class AttachmentRefused(Exception):
    """The request names something this research does not hold; the caller turns it into the route's refusal."""


def _rows(store: Any, sql: str, params: tuple) -> list[dict[str, Any]]:
    return [dict(row) for row in store.conn.execute(sql, params)]


def _identities(store: Any, research_id: str, passage_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Each passage's work, version and place, with the two states that keep it out of a binding: its source left this
    research, or the passage is no longer one a step may read (a replaced file, a newer extraction)."""
    if not passage_ids:
        return {}
    marks = ", ".join("?" * len(passage_ids))
    rows = _rows(store, "SELECT p.id, p.kind, p.physical_page, p.printed_label, p.source_version_id, v.work_id,"
                        " v.version_label, m.research_id AS member, m.removed_at FROM passages p"
                        " JOIN source_versions v ON v.id = p.source_version_id"
                        " LEFT JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
                        f" AND m.research_id = ? WHERE p.id IN ({marks})", (research_id, *passage_ids))
    current = {p["id"] for rows_ in fast_answer.current_pools(store, research_id).values() for p in rows_}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        # No membership row at all counts as removed: the passage belongs to a source this research does not hold.
        reason = ("source_removed" if row["member"] is None or row["removed_at"] is not None else
                  "passage_not_current" if row["id"] not in current else None)
        out[row["id"]] = {
            "binding": {"passage_id": row["id"], "source_version_id": row["source_version_id"],
                        "work_id": row["work_id"], "version_label": row["version_label"],
                        "locator": {"kind": row["kind"], "physical_page": row["physical_page"],
                                    "printed_label": row["printed_label"]}},
            "reason": reason}
    return out


def _snapshot_cells(store: Any, report_id: str) -> dict[str, dict[str, Any]]:
    """The cells as that report froze them: the report's citation to a cell means this revision and these quotes."""
    row = store.conn.execute("SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()
    if row is None:
        return {}
    return {cell["cell_id"]: cell for cell in json.loads(row["snapshot_json"]).get("cells", [])}


def _passage_candidates(store: Any, research_id: str, kind: str, ref_id: str) -> tuple[list[str], str | None]:
    """The passages this selection points at, in order, or the reason it points at none. Raises when the id is not a
    row of this research: the person cannot have selected it here."""
    if kind == "passage":
        owned = store.conn.execute(
            "SELECT 1 FROM passages p JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
            " WHERE p.id = ? AND m.research_id = ?", (ref_id, research_id)).fetchone()
        if owned is None:
            raise AttachmentRefused("That passage is not one of this research's sources")
        return [ref_id], None
    if kind == "cell":
        cell = store.conn.execute(
            "SELECT c.current_revision_id FROM evidence_cells c JOIN evidence_tables t ON t.id = c.table_id"
            " WHERE c.id = ? AND t.research_id = ?", (ref_id, research_id)).fetchone()
        if cell is None:
            raise AttachmentRefused("That evidence cell is not one of this research's cells")
        if cell["current_revision_id"] is None:
            return [], "cell_not_filled"
        ids = [r["passage_id"] for r in store.conn.execute(
            "SELECT passage_id FROM cell_evidence_links WHERE cell_revision_id = ? ORDER BY rowid",
            (cell["current_revision_id"],))]
        return ids, None if ids else "cell_has_no_located_quote"
    if kind == "answer_claim":
        claim = store.conn.execute(
            "SELECT c.id FROM claims c JOIN answers a ON a.id = c.answer_id WHERE c.id = ? AND a.research_id = ?",
            (ref_id, research_id)).fetchone()
        if claim is None:
            raise AttachmentRefused("That answer sentence is not one of this research's answers")
        ids = [r["passage_id"] for r in store.conn.execute(
            "SELECT passage_id FROM evidence_links WHERE claim_id = ? ORDER BY rowid", (ref_id,))]
        return ids, None if ids else "claim_has_no_citation"
    if kind == "followup_claim":
        turn_id, _, label = ref_id.partition(":")
        turn = store.conn.execute("SELECT draft_json FROM followup_turns WHERE id = ? AND research_id = ?",
                                  (turn_id, research_id)).fetchone()
        # The turn must have published that sentence: a label it never wrote is not a selection of this research.
        labels = [claim.get("claim_label") for claim in json.loads(turn["draft_json"] or "{}").get("claims", [])
                  if isinstance(claim, dict)] if turn is not None else []
        if turn is None or not label or label not in labels:
            raise AttachmentRefused("That follow-up sentence is not one of this research's answers")
        ids = [r["passage_id"] for r in store.conn.execute(
            "SELECT passage_id FROM followup_turn_links WHERE turn_id = ? AND claim_label = ? ORDER BY rowid",
            (turn_id, label))]
        return ids, None if ids else "claim_has_no_citation"
    # A report sentence: its effective citations, which leave out the ones the person removed when they edited it.
    row = store.conn.execute(
        "SELECT s.report_id FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
        " JOIN reports r ON r.id = s.report_id WHERE c.id = ? AND r.research_id = ?",
        (ref_id, research_id)).fetchone()
    if row is None:
        raise AttachmentRefused("That report sentence is not one of this research's reports")
    from deixis.workflow.features.report.report_store import ReportStore
    reports = ReportStore(store)
    frozen = _snapshot_cells(store, row["report_id"])
    ids: list[str] = []
    for link in reports.effective_links(row["report_id"]):
        if link["claim_id"] != ref_id:
            continue
        if link["passage_id"] is not None:
            ids.append(link["passage_id"])
        else:
            # The report cited a cell: its evidence is what the report froze, not what the cell holds now.
            ids += [item["passage_id"] for item in frozen.get(link["cell_id"], {}).get("evidence", [])]
    ids = list(dict.fromkeys(ids))
    return ids, None if ids else "claim_has_no_citation"


def resolve(store: Any, research_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every attachment of one request, resolved against this research's stored rows.

    Read inside the transaction that writes the turn, so a cell revision or a source selection that changes between
    the read and the write cannot bind the wrong version.
    """
    if len(items) > MAX_ATTACHMENTS:
        raise AttachmentRefused(f"A follow-up carries at most {MAX_ATTACHMENTS} selections")
    resolved: list[dict[str, Any]] = []
    for item in items:
        kind, ref_id = item.get("kind"), item.get("ref_id")
        text = " ".join((item.get("text") or "").split())
        if kind not in KINDS:
            raise AttachmentRefused("That is not a kind of selection this follow-up knows")
        if not text or len(text) > MAX_TEXT_CHARS:
            raise AttachmentRefused(f"A selection has 1 to {MAX_TEXT_CHARS} characters")
        if (kind == "text") != (ref_id is None):
            raise AttachmentRefused("A free selection carries no id, and every other selection carries one")
        if kind == "text":
            resolved.append({"kind": kind, "ref_id": None, "text": text, "unresolved_reason": None, "bindings": []})
            continue
        candidates, reason = _passage_candidates(store, research_id, kind, ref_id)
        identities = _identities(store, research_id, candidates)
        bindings = [identities[pid]["binding"] for pid in candidates
                    if pid in identities and identities[pid]["reason"] is None]
        if not bindings and reason is None:
            # Nothing readable: name the first candidate's own reason, so the person reads why, not just that.
            reasons = [identities[pid]["reason"] for pid in candidates if pid in identities]
            reason = next((r for r in reasons if r is not None), "nothing_readable")
        resolved.append({"kind": kind, "ref_id": ref_id, "text": text,
                         "unresolved_reason": None if bindings else reason, "bindings": bindings})
    return resolved


def signature(resolved: list[dict[str, Any]]) -> list[tuple[str, str | None, str]]:
    """What an idempotency key stands for beside the question: a replay with other selections is another request."""
    return [(item["kind"], item["ref_id"], item["text"]) for item in resolved]


def stored(store: Any, turn_id: str) -> list[dict[str, Any]]:
    """The attachments of a turn as they were resolved when it was asked, with their bindings in order."""
    rows = _rows(store, "SELECT * FROM followup_turn_attachments WHERE turn_id = ? ORDER BY ordinal", (turn_id,))
    for row in rows:
        row["bindings"] = [{"passage_id": b["passage_id"], "source_version_id": b["source_version_id"],
                            "work_id": b["work_id"], "version_label": b["version_label"],
                            "locator": json.loads(b["locator_json"]) if b["locator_json"] else None}
                           for b in _rows(store, "SELECT * FROM followup_turn_attachment_bindings"
                                                 " WHERE attachment_id = ? ORDER BY ordinal", (row["id"],))]
    return rows


def passage_ids(attachments: list[dict[str, Any]]) -> list[list[str]]:
    """One list per bound attachment, in the order the person added them: what the selection reserves room for."""
    return [[b["passage_id"] for b in item["bindings"]] for item in attachments if item["bindings"]]


def context(store: Any, attachments: list[dict[str, Any]], given: list[str] | None = None) -> list[dict[str, Any]]:
    """The attachments as the model reads them: the person's quote and what it was taken from, never as evidence.

    A claim may cite only the passages of its own StepInput; an attachment's text is the person's words about them.
    `given` is the passages this call carries, so `bound` says the model was handed the selection's own passage and
    not merely that a record was found: a selection whose passages the person's choice kept out of the pool reads as
    `not_given`, with its text intact.
    """
    carried = set(given) if given is not None else None
    titles: dict[str, dict[str, Any]] = {}
    svids = [b["source_version_id"] for item in attachments for b in item["bindings"]]
    if svids:
        marks = ", ".join("?" * len(svids))
        titles = {row["id"]: row for row in _rows(
            store, f"SELECT id, title, year FROM source_versions WHERE id IN ({marks})", tuple(svids))}
    out = []
    for item in attachments:
        reached = [b for b in item["bindings"] if carried is None or b["passage_id"] in carried]
        shown = reached[:MAX_CONTEXT_BINDINGS]
        out.append({
            "ordinal": item["ordinal"], "kind": item["kind"], "text": item["selected_text"],
            "bound": bool(reached),
            "unresolved": item["unresolved_reason"] or (None if reached or not item["bindings"] else "not_given"),
            "bindings": [{"title": titles.get(b["source_version_id"], {}).get("title"),
                          "year": titles.get(b["source_version_id"], {}).get("year"),
                          "version_label": b["version_label"], "locator": b["locator"]}
                         for b in shown],
            "more_bindings": len(reached) - len(shown),
        })
    return out

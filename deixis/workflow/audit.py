"""A small audit sample of the decisions the queue never shows (slice 20, decisions 5–7, SW11.8).

Four strata, read from the same queue context as the flow counts (`work_outcome`), over the works without a person's
probe: F1 full-text `include` by two agreeing runs, F2 full-text `criterion_not_met` by two agreeing runs, A1
abstract `out_of_scope` by two agreeing runs, A2 abstract `out_of_scope` by a code rule. A work a person closed with an
audit answer stays in the stratum its machine decision (the one strictly before the answer) belongs to.

The sample is stateless: in each stratum the `AUDIT_PER_STRATUM` works with the smallest
`sha256("{research}|{revision}|{criterion hash or 'none'}|{stratum label}|{work}")`, the label from `DIGEST_LABEL`.
No random state, no stored seed and no row is written, so the same stored state gives the same sample whatever the
order rows are read in. A new question revision or criterion draws a new sample, and a later reading run can put a work with a smaller digest in a stratum,
which pushes a sampled work out: the sample drifts. So the screen keeps the current sample and every earlier audit
answer apart, and no rate or error estimate is drawn from either (a frozen cohort is an open requirement).

Under the owner's answer A1, F1 and F2 are answered through the audit branch of `queue.py`; A1 and A2 are shown for
viewing and manual selection only, outside the audit answers and their totals.
"""

from __future__ import annotations

import hashlib
from typing import Any

from deixis.workflow import overrides as override_rules
from deixis.workflow import probes as probe_rules
from deixis.workflow import queue
from deixis.workflow.store import Store

# A display constant, not a protocol threshold: chosen by hand, its adequacy is not measured.
AUDIT_PER_STRATUM = 3
STRATA = ("F1", "F2", "A1", "A2")
FULLTEXT_STRATA = ("F1", "F2")
ABSTRACT_STRATA = ("A1", "A2")
# The stratum's name inside the digest: the plan measured its sample with these (measure.py), so the product draws the
# same works the plan's acceptance compares against.
DIGEST_LABEL = {"F1": "F1_include_by_agreement", "F2": "F2_not_met_by_agreement", "A1": "A1_out_of_scope_by_agreement",
                "A2": "A2_out_of_scope_by_code"}
# The machine decision an audit answer closed, read back by its code for the extended membership and for the undo.
STRATUM_OF_CODE = {"all_parts_verified": "F1", "criterion_absent": "F2"}
KIND_OF_STRATUM = {"F1": "audit_include", "F2": "audit_not_met"}
QUESTION = "Does this work meet the criterion?"


class AuditState:
    """One derivation of the strata, the samples and the audit answers from one queue context."""

    def __init__(self, ctx: Any, probe: dict[str, Any] | None = None):
        self.ctx = ctx
        self.probe = probe if probe is not None else probe_rules.probe_set(ctx)
        self.origins = queue.decision_origins(ctx.store, ctx.rid)
        # stratum -> work -> the machine decision that puts it there
        self.members: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in STRATA}
        # work -> the audit answer standing on it, with the version it was given on
        self.answers: dict[str, dict[str, Any]] = {}
        self._derive()
        self.samples = {name: self._draw(name) for name in STRATA}

    def _derive(self) -> None:
        ctx, probe = self.ctx, self.probe
        person = set(probe["verified"]) | set(probe["negatives"]) | probe["look_again"]
        for work_id in sorted(ctx.facts["heads"]):
            decisions = ctx.facts["decisions"].get(work_id, [])
            answer = self._audit_answer(decisions)
            if answer is not None:
                machine = self._before(answer)
                self.answers[work_id] = {"decision": answer, "machine": machine}
                stratum = STRATUM_OF_CODE.get((machine or {}).get("reason_code"))
                if stratum and not ctx.decisions.is_stale(machine, ctx.facts["stale_key"]):
                    self.members[stratum][work_id] = machine
                continue
            if work_id in person:
                continue
            outcome = ctx.outcome(work_id)
            if not outcome:
                continue
            stratum = None
            if outcome["stage"] == "fulltext" and outcome["decided_by"] == "model_agreement":
                stratum = {"include": "F1", "criterion_not_met": "F2"}.get(outcome["outcome"])
            elif outcome["stage"] == "abstract" and outcome["outcome"] == "out_of_scope":
                stratum = "A1" if outcome["decided_by"] == "model_agreement" else "A2"
            if stratum is None:
                continue
            machine = next((d for d in decisions if d["stage"] == outcome["stage"]
                            and d["source_version_id"] == outcome["source_version_id"]
                            and d["reason_code"] == outcome["reason_code"]), None)
            if machine is not None:
                self.members[stratum][work_id] = machine

    def _audit_answer(self, decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The person's open full-text decision on this work that the audit branch wrote, if any."""
        human = [d for d in decisions if d["stage"] == "fulltext" and d["decided_by"] == "human"]
        found = [d for d in human if self.origins.get(d["id"]) == queue.AUDIT]
        return found[-1] if found else None

    def _before(self, decision: dict[str, Any]) -> dict[str, Any] | None:
        """The row written strictly before this decision on its version and stage, by `(created_at, rowid)`."""
        row = self.ctx.store.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND source_version_id = ? AND stage = ?"
            " AND (created_at < ? OR (created_at = ? AND rowid < (SELECT rowid FROM stage_decisions WHERE id = ?)))"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (self.ctx.rid, decision["source_version_id"], decision["stage"], decision["created_at"],
             decision["created_at"], decision["id"])).fetchone()
        return dict(row) if row is not None and row["decided_by"] != "human" else None

    def digest(self, stratum: str, work_id: str) -> str:
        revision, criterion_hash = self.ctx.facts["stale_key"]
        text = f"{self.ctx.rid}|{revision}|{criterion_hash or 'none'}|{DIGEST_LABEL[stratum]}|{work_id}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _draw(self, stratum: str) -> list[str]:
        return sorted(self.members[stratum], key=lambda work_id: (self.digest(stratum, work_id), work_id))[:AUDIT_PER_STRATUM]

    def stratum_of(self, work_id: str) -> str | None:
        """The stratum whose current sample holds this work, or None."""
        return next((name for name in STRATA if work_id in self.samples[name]), None)


def token(ctx: Any, work_id: str, svid: str, stratum: str, machine_id: str) -> str:
    """D96's row token plus the stratum and the machine decision; the machine decision's id leads, so the write can
    check it against the version's current decision before the digest (decision 6, check ii)."""
    current = ctx.decisions.current(ctx.rid, svid, "fulltext")
    head = ctx.facts["heads"].get(work_id)
    base = queue._token(ctx, work_id, svid, (current or {}).get("reason_code"), head)
    return f"{machine_id}.{queue.sha256_hex({'row': base, 'stratum': stratum, 'machine': machine_id})}"


def _source(store: Store, svid: str) -> dict[str, Any]:
    source = store.source(svid)
    return {key: source[key] for key in ("title", "year", "doi", "version_label", "publication_type")}


def fulltext_row(state: AuditState, stratum: str, work_id: str) -> dict[str, Any]:
    """One F1 / F2 row of the current sample, answered or not."""
    ctx = state.ctx
    machine = state.members[stratum][work_id]
    svid = machine["source_version_id"]
    answer = state.answers.get(work_id)
    answered = None
    if answer is not None and answer["decision"]["source_version_id"] == svid:
        decision = answer["decision"]
        answered = {"decision_id": decision["id"], "reason_code": decision["reason_code"],
                    "answer": queue.ANSWER_OF.get(decision["reason_code"]), "note": decision["note"],
                    "created_at": decision["created_at"],
                    "stale": ctx.decisions.is_stale(decision, ctx.facts["stale_key"])}
    return {"work_id": work_id, "head": ctx.facts["heads"].get(work_id), "source_version_id": svid,
            **_source(ctx.store, svid), "stratum": stratum, "kind": KIND_OF_STRATUM[stratum], "question": QUESTION,
            "machine": {"decision_id": machine["id"], "reason_code": machine["reason_code"],
                        "decided_by": machine["decided_by"]},
            "answered": answered, "audit_token": token(ctx, work_id, svid, stratum, machine["id"])}


def abstract_row(state: AuditState, stratum: str, work_id: str) -> dict[str, Any]:
    """One A1 / A2 row: shown for viewing and manual selection only (owner's answer A1)."""
    ctx = state.ctx
    machine = state.members[stratum][work_id]
    svid = machine["source_version_id"]
    head = ctx.facts["heads"].get(work_id)
    selection = ctx.selections.get(head) or {}
    quotes = [{"run_no": row["run_no"], "label": row["label"], "quote": row["quote"],
               "quote_verified": None if row["quote_verified"] is None else bool(row["quote_verified"])}
              for row in ctx.store.conn.execute(
                  "SELECT run_no, label, quote, quote_verified FROM model_proposals WHERE research_id = ?"
                  " AND source_version_id = ? AND stage = 'abstract' AND step_id IS ? ORDER BY run_no, criterion_part",
                  (ctx.rid, svid, machine["step_id"]))] if machine["step_id"] else []
    return {"work_id": work_id, "head": head, "source_version_id": svid, **_source(ctx.store, svid),
            "stratum": stratum, "reason_code": machine["reason_code"], "decided_by": machine["decided_by"],
            "quotes": quotes,
            "selection": {"state": selection.get("state"), "origin": selection.get("origin"),
                          "version": selection.get("version")}}


def audit_view(store: Store, research_id: str) -> dict[str, Any]:
    """The audit section: F1 / F2's current sample and result, the earlier audit answers apart, and the abstract
    strata for viewing. Reading writes nothing."""
    with queue._snapshot(store.conn):
        ctx = queue._Context(store, research_id)
        state = AuditState(ctx)
        classified = override_rules.classify(ctx, state.probe)
        return _view(state, classified)


def _differs(classified: dict[str, dict[str, Any]], work_id: str) -> bool:
    entry = classified.get(work_id) or {}
    return entry.get("path") == "audit" and entry.get("class") == "overruled"


def _view(state: AuditState, classified: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ctx = state.ctx
    fulltext = {}
    for stratum in FULLTEXT_STRATA:
        rows = [fulltext_row(state, stratum, work_id) for work_id in state.samples[stratum]]
        answered = [row for row in rows if row["answered"] is not None]
        fulltext[stratum] = {"size": len(state.members[stratum]), "sample_size": len(rows), "rows": rows,
                             "answered": len(answered),
                             "differs": sum(_differs(classified, row["work_id"]) for row in answered)}
    earlier = []
    for work_id, answer in sorted(state.answers.items(), key=lambda item: item[1]["decision"]["created_at"], reverse=True):
        decision, machine = answer["decision"], answer["machine"] or {}
        stratum = STRATUM_OF_CODE.get(machine.get("reason_code"))
        earlier.append({"work_id": work_id, "source_version_id": decision["source_version_id"],
                        **_source(ctx.store, decision["source_version_id"]), "stratum": stratum,
                        "answer": queue.ANSWER_OF.get(decision["reason_code"]), "reason_code": decision["reason_code"],
                        "created_at": decision["created_at"],
                        "in_sample": stratum is not None and work_id in state.samples[stratum],
                        "differs": _differs(classified, work_id)})
    earlier_counts = {stratum: {"answers": sum(e["stratum"] == stratum for e in earlier),
                                "differs": sum(e["stratum"] == stratum and e["differs"] for e in earlier)}
                      for stratum in FULLTEXT_STRATA}
    abstract = {stratum: {"size": len(state.members[stratum]),
                          "rows": [abstract_row(state, stratum, work_id) for work_id in state.samples[stratum]]}
                for stratum in ABSTRACT_STRATA}
    return {"revision": ctx.revision, "per_stratum": AUDIT_PER_STRATUM, "fulltext": fulltext,
            "earlier": earlier, "earlier_counts": earlier_counts, "abstract": abstract}


def audit_detail(store: Store, research_id: str, source_version_id: str) -> dict[str, Any]:
    """One F1 / F2 row with what the two reading runs said, from the machine decision's own step. Writes nothing."""
    queue._require_source(store, research_id, source_version_id)
    with queue._snapshot(store.conn):
        ctx = queue._Context(store, research_id)
        state = AuditState(ctx)
        found = find(state, source_version_id)
        if found is None:
            return {"row": None, "detail": None}
        stratum, work_id = found
        if stratum in ABSTRACT_STRATA:
            return {"row": abstract_row(state, stratum, work_id), "detail": None}
        row = fulltext_row(state, stratum, work_id)
        machine = state.members[stratum][work_id]
        svid = row["source_version_id"]
        pages, opens = store.page_texts(svid), queue._page_passages(store, svid)
        asset = ctx.assets.get(svid)
        detail: dict[str, Any] = {
            "runs": queue._runs(ctx, svid, machine, pages, opens),
            "cues": [{"part": part["name"], **queue._cues(ctx, part["name"], pages, opens)} for part in ctx.parts],
            "asset_id": asset["id"] if asset else None}
        versions = queue._versions(ctx, {"work_id": work_id, "source_version_id": svid})
        if len(versions) > 1:
            detail["versions"] = versions
        return {"row": row, "detail": detail}


def find(state: AuditState, svid: str) -> tuple[str, str] | None:
    """The (stratum, work) of the current sample whose machine decision is on this version."""
    for stratum in STRATA:
        for work_id in state.samples[stratum]:
            if state.members[stratum][work_id]["source_version_id"] == svid:
                return stratum, work_id
    return None

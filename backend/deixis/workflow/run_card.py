"""Two per-run readings for the research view: what the two abstract passes said, and why a passed work went unread.

Nothing here is stored and nothing is guessed. Every label, outcome, count and reason is read from rows the run wrote
(`model_proposals`, `stage_decisions`, `run_steps`) or from the run's own frozen records (the read stage's closure,
the cutoff snapshot). A later run, a later decision or a work found later does not change what an earlier run's card
says. A work whose reason no stored record gives is `unknown`, never the likeliest cause.

The research-wide rows both readings need are read once per view build (`Facts`) and shared by every run, so the
number of queries does not grow with the number of works.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cached_property
from typing import Any

from deixis.workflow import fast_path

GAP_REASONS = ("no_open_pdf", "fetch_failed", "deferred", "outside_read_limit", "not_reached_before_cutoff",
               "reading_failed", "identity_unconfirmed", "unknown")
# The fast path's cutoff snapshot (`fast_answer.CUTOFF`), frozen with the read stage's closure when the answer stage is
# enforced too.
CUTOFF_KEY = "fast_path:v1:cutoff"


class Facts:
    """The research-wide rows the run cards read, each loaded at most once per view build."""

    def __init__(self, store: Any, research_id: str) -> None:
        self.store, self.rid = store, research_id

    @cached_property
    def versions(self) -> dict[str, tuple[str, str | None]]:
        """Every version this research holds or held: its work and its title."""
        return {row["id"]: (row["work_id"], row["title"]) for row in self.store.conn.execute(
            "SELECT DISTINCT v.id, v.work_id, v.title FROM source_versions v JOIN corpus_memberships m"
            " ON m.source_version_id = v.id WHERE m.research_id = ?", (self.rid,))}

    @cached_property
    def abstract_decisions(self) -> list[dict[str, Any]]:
        """Every abstract-stage decision of the research, oldest first."""
        return [dict(row) for row in self.store.conn.execute(
            "SELECT id, source_version_id, outcome, reason_code, scope_revision, step_id, created_at"
            " FROM stage_decisions WHERE research_id = ? AND stage = 'abstract' ORDER BY created_at, rowid",
            (self.rid,))]

    def attributed(self, revision: int, step_ids: set[str], end: datetime | None) -> dict[str, dict[str, Any]]:
        """Each version's abstract decision as this run left it, under `revision`: the latest one the run's own steps
        wrote, else the latest one written by `end` (the run's read cutoff, or when its last step finished). A decision
        written after the run, by a person or a later run, is not this run's and does not show here."""
        own: dict[str, dict[str, Any]] = {}
        before: dict[str, dict[str, Any]] = {}
        for decision in self.abstract_decisions:
            if decision["scope_revision"] != revision:
                continue
            if decision["step_id"] in step_ids:
                own[decision["source_version_id"]] = decision | {"own": True}
            elif end is not None and (made := _time(decision["created_at"])) is not None and made <= end:
                before[decision["source_version_id"]] = decision | {"own": False}
        return before | own

    @cached_property
    def failed_fetches(self) -> list[tuple[str, datetime | None, int | None]]:
        """Every failed `fetch_pdf` attempt of the research's runs: its version, when it finished, its HTTP status."""
        return [(row["operation_key"].split(":", 1)[1], _time(row["finished_at"]),
                 row["http_status"] if isinstance(row["http_status"], int) else None)
                for row in self.store.conn.execute(
                    "SELECT s.operation_key, s.finished_at, json_extract(s.error_json, '$.http_status') AS http_status"
                    " FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND s.kind = 'fetch_pdf'"
                    " AND s.status = 'failed' ORDER BY s.rowid", (self.rid,))]


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _end(steps: list[dict[str, Any]], closure: dict[str, Any] | None) -> datetime | None:
    """When the run's records stop counting: its read cutoff, else the moment its last step finished."""
    if closure and closure.get("read_cutoff_at"):
        return _time(closure["read_cutoff_at"])
    return max((when for step in steps if (when := _time(step.get("finished_at"))) is not None), default=None)


def _pass_kind(first: str | None, second: str | None) -> str:
    """The pair of labels by `abstract_stage.combine`'s own rule: a missing pass or two `unresolved` passes leave the
    work unresolved, two different labels disagree (one `unresolved` against a label included, as `combine` reads it),
    and two equal labels agree."""
    if first is None or second is None:
        return "unresolved"
    if first == second:
        return "unresolved" if first == "unresolved" else "agreed"
    return "disagreed"


def screening_passes(store: Any, run: dict[str, Any], facts: Facts) -> dict[str, Any] | None:
    """What the two abstract passes of this discovery run proposed, work by work; None for any other run kind.

    Every count is **per run**: `read` (also given as `run_read`) is the works with at least one abstract proposal from
    this run's own `model:abstract_screening` steps, not the revision's total. The abstract stage writes one proposal
    per record and pass with `criterion_part` '' (`flow._write_abstract_batch` never passes a part; only the full-text
    reading writes parts), and `combine` reads one label per pass, so a row under another part is not read here.

    The unit is one version's reading, as `combine` pairs it: pass 1 and pass 2 are paired only on the same version,
    so `read` counts the versions read (one per work unless a work's passes went to two of its versions) and labels of
    two versions are never mixed. `final` is that version's abstract decision as the run left it
    (`Facts.attributed`): the latest one this run's own steps wrote, else the latest written by the run's read cutoff
    or last step; a later person's or run's decision does not change it. Null when none.
    """
    if run["kind"] != "discovery":
        return None
    readings: dict[str, dict[str, Any]] = {}
    for row in store.conn.execute(
            "SELECT p.source_version_id, p.run_no, p.label, v.work_id, v.title FROM model_proposals p"
            " JOIN run_steps s ON s.id = p.step_id JOIN source_versions v ON v.id = p.source_version_id"
            " WHERE s.run_id = ? AND s.kind = 'model:abstract_screening' AND p.stage = 'abstract'"
            " AND p.criterion_part = '' ORDER BY p.created_at, p.rowid", (run["id"],)):
        reading = readings.setdefault(row["source_version_id"], {"passes": {}, "work_id": row["work_id"],
                                                                 "title": row["title"]})
        reading["passes"][row["run_no"]] = row["label"]
    steps = run.get("steps") or []
    final = (facts.attributed(run["scope_revision"], {step["id"] for step in steps},
                              _end(steps, ((run.get("fast_path") or {}).get("read") or {}).get("cutoff")))
             if readings else {})
    counts = {"agreed": 0, "disagreed": 0, "unresolved": 0}
    rows = []
    for svid, reading in readings.items():
        first, second = reading["passes"].get(1), reading["passes"].get(2)
        kind = _pass_kind(first, second)
        counts[kind] += 1
        if kind == "agreed":
            continue
        decision = final.get(svid) or {}
        rows.append({"source_version_id": svid, "work_id": reading["work_id"], "title": reading["title"],
                     "first": first, "second": second, "final": decision.get("outcome"),
                     "reason_code": decision.get("reason_code")})
    rows.sort(key=lambda row: (row["title"] or "", row["work_id"], row["source_version_id"]))
    return {"read": len(readings), "run_read": len(readings), **counts, "rows": rows}


def _passed_in_run(attributed: dict[str, dict[str, Any]], work_of: Any, universe: set[str],
                   snapshot: dict[str, Any] | None) -> set[str]:
    """The works this run's own records show as past the abstract stage: a stored abstract `candidate` decision.

    Two sources, both frozen by the run: the cutoff snapshot's items with an abstract `candidate` decision on the
    version it reads (`abstract_decision_id`), and the works one of whose versions holds a `candidate` decision as the
    run left it (`Facts.attributed`): one this run's own steps wrote, or one written by its cutoff for a work the run's
    records name (`universe`: its window, its snapshot, its retrieval and reading steps). Reaching the full-text stage is not that proof: `abstract_not_found` and
    `runs_agree_unresolved` route to the full text too and stay out. A work that passed only after the run gets no row.
    """
    passed = {item["work_id"] for item in (snapshot or {}).get("items") or [] if item.get("abstract_decision_id")}
    for svid, decision in attributed.items():
        work = work_of(svid)
        if decision["outcome"] == "candidate" and work is not None and (decision["own"] or work in universe):
            passed.add(work)
    return passed


def fulltext_gaps(store: Any, run: dict[str, Any], facts: Facts, read_view: dict[str, Any] | None) -> dict[str, Any] | None:
    """Why each work this run passed past the abstract stage was not read in full in it; None unless the run is a
    discovery run whose budget enforces the fast path's read stage.

    `read_any` counts every work one of whose versions has both its passes, 1 and 2, succeeded as
    `model:fulltext_adjudication` steps in this run, whatever its decision (the transcript's reading rule, paired per
    reading, keyed by its head: pass 1 under one head and pass 1 under another are no reading); `read` counts those
    among `passed`. A row names the version the run itself read or froze for the work, never the work's head today:
    its retrieval step's `read_version` when that step settled by the read cutoff, else the `read_version` this run's
    adjudication plan froze for its reading (never the head in the reading's key), else the snapshot's or the closure
    item's version, else the version of its candidate decision. `passed` comes from the run's own
    records only (`_passed_in_run`), so a later decision does not move it. Each unread passed work gets the first reason
    its stored records give, in this order:

    1. This run's adjudication steps for the work: a pass stopped by the read cutoff (`model_read_cutoff`) is
       `not_reached_before_cutoff`; a failed or `outcome_unknown` pass is `reading_failed`; anything else `unknown`.
    2. The read's identity check left the PDF unconfirmed as the work's own (the closure's `identity_unconfirmed`, or
       the work's `code:adjudication_plan` in this run): `identity_unconfirmed`, read by no model.
    3. The work's retrieval as it stood at the read cutoff (every record when the run has no closure): its
       `code:fulltext_work` step settled by then, and the failed `fetch_pdf` attempts of its versions, in any run, that
       finished by then and by the time the step settled.
       - settled `no_fulltext`: `fetch_failed` when such a failed attempt exists (its HTTP status is given), else
         `no_open_pdf` (every route answered and none had a file);
       - settled `text_unreadable` (a PDF came and no text could be read from it): `reading_failed`;
       - failed `quota_deferred`: `deferred` (nothing was sent: OpenAlex's daily budget was spent);
       - failed for any other cause, `outcome_unknown` or cancelled: `fetch_failed` only when such a failed attempt
         exists; otherwise this step gives no reason and the next one is tried.
    4. The closure's item for the work: `fulltext_after_cutoff` or `not_screened_at_cutoff` is
       `not_reached_before_cutoff`; `not_screened_model_budget` (the model-call budget, not the deadline) is
       `outside_read_limit`. A failure that came after the cutoff does not replace this.
    5. Stored proof that the read limit left the work out: the cutoff snapshot names it `outside_read_window`, or it was
       in the closure's window but not among its `selected_work_ids` while all K slots were taken and it was never
       claimed: `outside_read_limit`. Being absent from a window is not that proof.
    6. Otherwise `unknown`.
    """
    if run["kind"] != "discovery" or not fast_path.enforces(run["budget"], "read"):
        return None
    steps = run["steps"]
    closure = (read_view or {}).get("cutoff")
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?"
                             " AND status = 'succeeded'", (run["id"], CUTOFF_KEY)).fetchone()
    snapshot = json.loads(row["output_json"]) if row and row["output_json"] else None
    # The work each version belonged to as the run froze it: a work found later can absorb a version into another
    # work, and the run's card keeps naming the work its own records name.
    frozen_work: dict[str, str] = {}
    for item in [*((snapshot or {}).get("items") or []), *((closure or {}).get("items") or [])]:
        for key in ("head", "source_version_id"):
            if item.get(key):
                frozen_work[item[key]] = item["work_id"]
    for step in steps:
        if step["kind"] == "code:fulltext_work":
            output = step["output"] or {}
            for key in ("head", "read_version"):
                if output.get(key):
                    frozen_work[output[key]] = step["operation_key"].split(":", 1)[1]
    work_of = lambda svid: frozen_work.get(svid) or facts.versions.get(svid, (None, None))[0]  # noqa: E731
    failed_fetches: dict[str, list[tuple[datetime | None, int | None]]] = {}
    for svid, when, status in facts.failed_fetches:
        if (work := work_of(svid)) is not None:
            failed_fetches.setdefault(work, []).append((when, status))
    title_of = lambda svid: facts.versions.get(svid, (None, None))[1] if svid else None  # noqa: E731

    # The version each reading read, from this run's frozen adjudication plans: a reading is keyed by the work's head,
    # and the version read can be another one (a preprint's text under a publisher head).
    planned: dict[str, str] = {}
    for step in steps:
        if step["kind"] == "code:adjudication_plan" and step["status"] == "succeeded":
            for work in (step["output"] or {}).get("works") or []:
                if isinstance(work, dict) and work.get("head") and work.get("read_version"):
                    planned[work["head"]] = work["read_version"]
    passes: dict[str, list[tuple[str, str | None]]] = {}
    paired: dict[str, dict[str, set[str]]] = {}  # work -> reading (its head key) -> the passes that succeeded on it
    read_version: dict[str, str] = {}
    for step in steps:
        if step["kind"] != "model:fulltext_adjudication":
            continue
        parts = step["operation_key"].split(":")
        # `fulltext_adjudication:{head}:{pass}`; a person's reading has a longer key and is not this run's read.
        if len(parts) == 3 and parts[0] == "fulltext_adjudication" and (work := work_of(parts[1])) is not None:
            passes.setdefault(work, []).append((step["status"], step["error_code"]))
            if parts[1] in planned:
                read_version.setdefault(work, planned[parts[1]])
            if step["status"] == "succeeded":
                paired.setdefault(work, {}).setdefault(parts[1], set()).add(parts[2])
    read_any = {work for work, versions in paired.items() if any({"1", "2"} <= done for done in versions.values())}

    claims = {step["operation_key"].split(":", 1)[1]: step for step in steps if step["kind"] == "code:fulltext_work"}
    unconfirmed = set((closure or {}).get("identity_unconfirmed") or [])
    for step in steps:
        key = step["operation_key"]
        if (step["kind"] == "code:adjudication_plan" and step["status"] == "succeeded" and ":read:" in key
                and key.endswith(":adjudication_plan") and (step["output"] or {}).get("identity_unconfirmed")):
            unconfirmed.add(key.rsplit(":read:", 1)[1].removesuffix(":adjudication_plan"))
    cutoff_at = _time((closure or {}).get("read_cutoff_at"))
    items = {item["work_id"]: item for item in (closure or {}).get("items") or []}
    selected = set((closure or {}).get("selected_work_ids") or [])
    k_full = closure is not None and (closure.get("k_selected") or 0) >= (closure.get("K") or 0)
    outside = {item["work_id"] for item in (snapshot or {}).get("items") or []
               if (item.get("base_reason") or item.get("reason")) == "outside_read_window"}
    step_ids = {step["id"] for step in steps}
    attributed = facts.attributed(run["scope_revision"], step_ids, _end(steps, closure))
    universe = (set(items) | {item["work_id"] for item in (snapshot or {}).get("items") or []} | set(claims)
                | set(passes))
    passed = _passed_in_run(attributed, work_of, universe, snapshot)
    frozen: dict[str, str] = {}
    for svid, decision in attributed.items():
        if decision["outcome"] == "candidate" and (work := work_of(svid)) is not None and work in passed:
            frozen[work] = svid
    for found in (items.values(), (snapshot or {}).get("items") or []):
        for item in found:
            if version := item.get("source_version_id") or item.get("head"):
                frozen[item["work_id"]] = version

    def by(limit: datetime | None, when: datetime | None) -> bool:
        return limit is None or (when is not None and when <= limit)

    # A retrieval's stored version names the row only when it settled by the read cutoff (a background fetch that
    # settled afterwards does not rename an earlier card's row); the version the run's reading plan read wins over it.
    for work, claim in claims.items():
        if not by(cutoff_at, _time(claim["finished_at"])):
            continue
        if version := (claim["output"] or {}).get("read_version") or (claim["output"] or {}).get("head"):
            frozen[work] = version
    frozen |= read_version

    def retrieval(work_id: str) -> tuple[str, int | None] | None:
        claim = claims.get(work_id)
        settled = _time(claim["finished_at"]) if claim else None
        if claim is None or not by(cutoff_at, settled):
            return None
        attempts = [status for when, status in failed_fetches.get(work_id, [])
                    if by(cutoff_at, when) and by(settled, when)]
        failed = ("fetch_failed", attempts[-1]) if attempts else None
        code = (claim["output"] or {}).get("code")
        if claim["status"] == "succeeded":
            if code == "no_fulltext":
                return failed or ("no_open_pdf", None)
            if code == "text_unreadable":
                return "reading_failed", None
            return None
        if claim["status"] == "failed" and claim["error_code"] == "quota_deferred":
            return "deferred", None
        return failed

    def reason(work_id: str) -> tuple[str, int | None]:
        if work_id in passes:
            found = passes[work_id]
            if any(code == "model_read_cutoff" for _, code in found):
                return "not_reached_before_cutoff", None
            if any(status in ("failed", "outcome_unknown") for status, _ in found):
                return "reading_failed", None
            return "unknown", None
        if work_id in unconfirmed:
            return "identity_unconfirmed", None
        if (fetched := retrieval(work_id)) is not None:
            return fetched
        cut = (items.get(work_id) or {}).get("cutoff")
        if (isinstance(cut, dict) and "fulltext_after_cutoff" in cut) or cut == "not_screened_at_cutoff":
            return "not_reached_before_cutoff", None
        if cut == "not_screened_model_budget":
            return "outside_read_limit", None
        if work_id in outside or (work_id in items and work_id not in selected and k_full and work_id not in claims):
            return "outside_read_limit", None
        return "unknown", None

    rows = []
    for work_id in sorted(passed - read_any):
        head = frozen.get(work_id)
        why, status = reason(work_id)
        rows.append({"source_version_id": head, "work_id": work_id, "title": title_of(head), "reason": why,
                     "http_status": status})
    rows.sort(key=lambda row: (row["title"] or "", row["work_id"]))
    reasons = dict.fromkeys(GAP_REASONS, 0)
    for row in rows:
        reasons[row["reason"]] += 1
    return {"passed": len(passed), "read": len(passed & read_any), "read_any": len(read_any),
            "not_read": len(rows), "reasons": reasons, "rows": rows}

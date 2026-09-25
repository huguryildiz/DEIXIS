"""How often a person's decision changed what code or the model runs had decided (slice 20, decision 4, SW11.13).

Nothing here is stored. The person's decisions are D101's probe set: a confirmed positive reads as `included`, a
negative as `excluded`. Each is compared with the machine's view of the work **at the moment the person decided**:

- a queue or audit answer is a row of `stage_decisions`, so the moment is exact: the rows written strictly before
  the person's row by `(created_at, rowid)`. When the person changed an earlier answer of their own, the moment is
  that first answer's, so the machine view is the one the person first overruled or settled;
- a list edit writes no decision, so the moment is the `created_at` of the `selection_history` row that set the
  current selection (a selection a new head copied from another version is followed to that version's row; a later
  edit of another version is not this moment). Decisions and selection history are different tables and their row
  ids cannot be compared: a decision written in the same millisecond makes the class `time_unknown`.

The machine view is every version's stage decisions as they stood then, the person's rows left out, resolved by
`work_outcome` without the person-file exception and judged stale under the key of that moment. A decision reached
later, on another version, is not what the person changed.

A count, never a rate: in the queue and in the source list the person or a rule chose which work to look at, so
"M of N" says nothing about how often code or the model is right. `not_sure`, `pdf_wrong` and `look_again` are
counted apart and never in a class.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from deixis.domain.canonical import sha256_hex
from deixis.workflow import queue
from deixis.workflow.decisions import CRITERION_FIELDS, SELECTION_STATE
from deixis.workflow.store import COPIED_SELECTION_REASON

CLASSES = ("overruled", "agreed", "settled_open", "time_unknown")
PATHS = ("queue", "audit", "list")
DECIDED = ("include", "criterion_not_met", "out_of_scope")


def _key_at(ctx: Any, ts: str) -> tuple[int | None, str | None]:
    """The staleness key as it was at `ts`: the scope revision current then and its last protocol record by then."""
    conn = ctx.store.conn
    row = conn.execute("SELECT revision FROM scope_revisions WHERE research_id = ? AND created_at <= ?"
                       " ORDER BY revision DESC LIMIT 1", (ctx.rid, ts)).fetchone()
    if row is None:
        return None, None
    revision = row[0]
    protocol = conn.execute(
        "SELECT body_json FROM protocol_records WHERE research_id = ? AND scope_revision = ? AND created_at <= ?"
        " ORDER BY protocol_revision DESC LIMIT 1", (ctx.rid, revision, ts)).fetchone()
    if protocol is None:
        return revision, None
    body = json.loads(protocol[0])
    criterion = {field: body.get(field) for field in CRITERION_FIELDS}
    return revision, None if all(value is None for value in criterion.values()) else sha256_hex(criterion)


def _history(ctx: Any, work_id: str) -> list[dict[str, Any]]:
    """Every stage decision of the work's versions still in the research, oldest first, with its row order."""
    return [dict(row) for row in ctx.store.conn.execute(
        "SELECT d.*, d.rowid AS row_order FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
        " JOIN corpus_memberships m ON m.research_id = d.research_id AND m.source_version_id = d.source_version_id"
        " AND m.removed_at IS NULL WHERE d.research_id = ? AND v.work_id = ? ORDER BY d.created_at, d.rowid",
        (ctx.rid, work_id))]


def _view_before(rows: list[dict[str, Any]], moment_ts: str) -> list[dict[str, Any]]:
    """The machine's open rows among `rows` (already cut to those written before the moment): the last row of each
    version and stage, unless the person wrote it or it was closed, with nothing written after it, before the moment."""
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        last[(row["source_version_id"], row["stage"])] = row
    kept = [row for row in last.values() if row["decided_by"] != "human"
            and not (row["superseded_at"] is not None and row["superseded_at"] < moment_ts)]
    kept.sort(key=lambda row: (row["created_at"], row["row_order"]))
    return [{key: value for key, value in row.items() if key != "row_order"} for row in kept]


def _machine(ctx: Any, work_id: str, rows: list[dict[str, Any]], moment_ts: str) -> dict[str, Any]:
    facts = {"heads": ctx.facts["heads"], "decisions": {work_id: _view_before(rows, moment_ts)},
             "stale_key": _key_at(ctx, moment_ts), "person": {}}
    return ctx.decisions.work_outcome(ctx.rid, work_id, facts)


def _class(machine: dict[str, Any], person: str) -> dict[str, Any]:
    decided = bool(machine) and machine["outcome"] in DECIDED
    state = SELECTION_STATE[machine["outcome"]] if machine else None
    found = "settled_open" if not decided else "agreed" if state == person else "overruled"
    return {"class": found, "person": person,
            "machine": {key: machine[key] for key in ("stage", "outcome", "reason_code", "decided_by")} | {"state": state}
            if machine else None,
            "direction": f"{state} -> {person}" if found == "overruled" else None}


def _setting_row(rows: list[dict[str, Any]], head: str) -> dict[str, Any] | None:
    """The person's `selection_history` row that set the head's current selection, or None when it cannot be told.

    The head's newest row is that row unless the head took its selection over from another version of the work
    (`COPIED_SELECTION_REASON`, `_settle_work_head`); then the copy's source is followed: the other version whose
    newest row before the copy is a person's with the copied state, the newest such, as the copy chose it. An edit
    made later on another version is not this selection's moment."""
    version, before = head, None
    for _ in range(len(rows) + 1):
        own = [row for row in rows if row["source_version_id"] == version and (before is None or row["id"] < before)]
        if not own:
            return None
        last = own[-1]
        if last["reason"] != COPIED_SELECTION_REASON:
            return last if last["origin"] == "user" else None
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["source_version_id"] != version and row["id"] < last["id"]:
                latest[row["source_version_id"]] = row
        sources = [row for row in latest.values() if row["origin"] == "user" and row["new_state"] == last["new_state"]]
        if not sources:
            return None
        version, before = max(sources, key=lambda row: row["id"])["source_version_id"], last["id"]
    return None


def classify(ctx: Any, probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each work the person decided (D101's probe set) with its path, class and the machine view it is compared with."""
    store, rid = ctx.store, ctx.rid
    linked: dict[tuple[str, int], dict[str, Any]] = {}
    for row in store.conn.execute(
            "SELECT l.head, l.selection_version, d.*, d.rowid AS row_order FROM human_selection_links l"
            " JOIN stage_decisions d ON d.id = l.decision_id"
            " WHERE l.research_id = ? AND d.superseded_at IS NULL ORDER BY l.created_at, l.rowid", (rid,)):
        linked[(row["head"], row["selection_version"])] = dict(row)
    person_works = sorted(set(probe["verified"]) | set(probe["negatives"]))
    # The selection history of the person's works only: most researches have none, and a large one has thousands of
    # history rows the count never needs.
    selection_rows: dict[str, list[dict[str, Any]]] = {}
    for start in range(0, len(person_works), 500):
        chunk = person_works[start:start + 500]
        for row in store.conn.execute(
                "SELECT h.id, h.source_version_id, h.new_state, h.origin, h.reason, h.created_at, v.work_id"
                " FROM selection_history h JOIN source_versions v ON v.id = h.source_version_id"
                f" WHERE h.research_id = ? AND v.work_id IN ({','.join('?' * len(chunk))}) ORDER BY h.id",
                (rid, *chunk)):
            selection_rows.setdefault(row["work_id"], []).append(dict(row))
    origins = queue.decision_origins(store, rid) if person_works else {}
    found: dict[str, dict[str, Any]] = {}
    for work_id in person_works:
        person = "included" if work_id in probe["verified"] else "excluded"
        head = ctx.facts["heads"][work_id]
        selection = ctx.selections.get(head) or {}
        decision = linked.get((head, selection.get("version")))
        history = _history(ctx, work_id)
        if decision is not None:
            path = "audit" if origins.get(decision["id"]) == queue.AUDIT else "queue"
            same = [row for row in history if row["source_version_id"] == decision["source_version_id"]
                    and row["stage"] == decision["stage"]]
            at = next(i for i, row in enumerate(same) if row["id"] == decision["id"])
            while at > 0 and same[at - 1]["decided_by"] == "human":
                at -= 1  # a person who changed their own answer: compared with what their first answer changed
            first = same[at]
            moment = (first["created_at"], first["row_order"])
            before = [row for row in history if (row["created_at"], row["row_order"]) < moment]
            found[work_id] = {"path": path, **_class(_machine(ctx, work_id, before, first["created_at"]), person)}
            continue
        setting = _setting_row(selection_rows.get(work_id, []), head)
        ts = setting["created_at"] if setting else None
        if ts is None or any(row["created_at"] == ts for row in history):
            found[work_id] = {"path": "list", "class": "time_unknown", "person": person, "machine": None,
                              "direction": None}
            continue
        before = [row for row in history if row["created_at"] < ts]
        found[work_id] = {"path": "list", **_class(_machine(ctx, work_id, before, ts), person)}
    return found


def overrides_view(ctx: Any, probe: dict[str, Any], classified: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The count the screen shows: of N decisions, M changed a machine decision (by code, by the model runs)."""
    classified = classify(ctx, probe) if classified is None else classified
    classes = Counter(entry["class"] for entry in classified.values())
    by_path = {path: {name: 0 for name in CLASSES} for path in PATHS}
    for entry in classified.values():
        by_path[entry["path"]][entry["class"]] += 1
    rows = Counter((entry["path"], entry["machine"]["decided_by"], entry["machine"]["stage"], entry["direction"])
                   for entry in classified.values() if entry["class"] == "overruled")
    changed_by = Counter(entry["machine"]["decided_by"] for entry in classified.values() if entry["class"] == "overruled")
    # Counted apart, each work once: a person's decision gone stale is `look_again` (as the queue asks it again),
    # whatever it said; a fresh "not sure" or "wrong file" is its own count.
    apart: Counter[str] = Counter()
    person = set(probe["verified"]) | set(probe["negatives"])
    for work_id in ctx.facts["heads"]:
        outcome = ctx.outcome(work_id)
        if work_id in person or not outcome or outcome.get("decided_by") != "human":
            continue
        decision = next((d for d in ctx.facts["decisions"].get(work_id, []) if d["stage"] == "fulltext"
                         and d["source_version_id"] == outcome["source_version_id"] and d["decided_by"] == "human"), None)
        if work_id in probe["look_again"] or (decision and ctx.decisions.is_stale(decision, ctx.facts["stale_key"])):
            apart["look_again"] += 1
        elif outcome["reason_code"] in ("human_not_sure", "human_pdf_wrong"):
            apart["not_sure" if outcome["reason_code"] == "human_not_sure" else "pdf_wrong"] += 1
    return {
        "decisions": len(classified),
        "changed": classes.get("overruled", 0),
        "changed_by": {"code": changed_by.get("code", 0), "model_agreement": changed_by.get("model_agreement", 0)},
        "classes": {name: classes.get(name, 0) for name in CLASSES},
        "by_path": by_path,
        "overruled": [{"path": path, "decided_by": by, "stage": stage, "direction": direction, "count": count}
                      for (path, by, stage, direction), count in sorted(rows.items())],
        "apart": {"not_sure": apart.get("not_sure", 0), "pdf_wrong": apart.get("pdf_wrong", 0),
                  "look_again": apart.get("look_again", 0)},
    }

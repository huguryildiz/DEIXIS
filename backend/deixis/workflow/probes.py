"""The probe set of an `sw` research and the tables read against it (slice 19, SW13).

Nothing here is stored. The probe set is derived, each time it is read, from the person's own decisions: the queue
answers they gave and the list edits they made, read through the head's current selection. A work two agreeing model
runs included stays in its own column and is never a probe: it was not checked by a person, and it was read because
the order put it near the top (AGENTS.md, SW11.13).

The tables count, they do not judge. The arm rows extend D93's source counts with what each arm found that was later
included or confirmed; the signal table says where the person's confirmed works stood in each signal of a keyword
ranking step, beside its denominator, and says "too few" below `PROBE_JUDGE_MIN`. No signal is switched off, no arm
stopped and no threshold read from here: the stopping rule and the costly-signal switch-off are open requirements.

Nothing is written: no step, decision, event or selection. Every value comes from stored rows.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from deixis.workflow.chaining import QUERY_PREFIX as CHAIN_PREFIX
from deixis.workflow.fulltext import OWNED_CODES as RETRIEVAL_CODES
from deixis.workflow.ranking import SIGNALS
from deixis.workflow.store import COPIED_SELECTION_REASON, Store

# A display constant, not a protocol threshold (SW13 found every interval with 20–29 positives held zero). Below it
# the signal table says the confirmed works are too few to judge by; at or above it, the numbers are only numbers.
PROBE_JUDGE_MIN = 30
CUTS = (100, 200)
# How a work a person brought joined the research: anything but a search.
BROUGHT_BY = ("user_upload", "zotero_import", "library")
# Full-text decisions that record no reading of the text: a retrieval outcome, a file held back before reading, and a
# person's "the file is wrong".
NOT_A_READING = (*RETRIEVAL_CODES, "pdf_identity_unconfirmed", "human_pdf_wrong")
# The two orders the signal table reads beside the single signals. Both are stored as exact integer places (D79).
ORDERS = ("fused", "inspection")
ARM_KINDS = ("keyword", "expansion", "chain")



# ---- the probe set -------------------------------------------------------------------------------------------------


def probe_set(ctx: Any) -> dict[str, Any]:
    """The person's probes and the model-agreement column, work by work, from one queue context (`queue.context`).

    A work is a person's probe when its head's current selection is the user's. A queue decision linked to that very
    selection version decides what it is: stale, it is no probe and counts as `look_again`; fresh, `human_include` is
    a confirmed positive and `human_criterion_not_met` a negative of that kind. Without such a link the selection is
    the person's own list edit (D96): `included` is a confirmed positive, `excluded` a negative whose kind was not
    recorded. A list edit names no criterion, so it never goes stale; that is a written limit, not a check.
    """
    store, rid = ctx.store, ctx.rid
    linked: dict[tuple[str, int], dict[str, Any]] = {}
    for row in store.conn.execute(
            "SELECT l.head, l.selection_version, d.* FROM human_selection_links l"
            " JOIN stage_decisions d ON d.id = l.decision_id"
            " WHERE l.research_id = ? AND d.superseded_at IS NULL ORDER BY l.created_at, l.rowid", (rid,)):
        linked[(row["head"], row["selection_version"])] = dict(row)
    # When the person last edited the work's selection from the list. Not `selections.updated_at`: a new head takes
    # the selection over with a new time, and that copy is no decision (its history row names the copy).
    list_edited: dict[str, str] = {}
    for row in store.conn.execute(
            "SELECT v.work_id, MAX(h.created_at) FROM selection_history h JOIN source_versions v ON v.id = h.source_version_id"
            " WHERE h.research_id = ? AND h.origin = 'user' AND h.reason IS NOT ?"
            " GROUP BY v.work_id", (rid, COPIED_SELECTION_REASON)):
        list_edited[row[0]] = row[1]
    verified: dict[str, dict[str, Any]] = {}
    negatives: dict[str, str] = {}
    look_again: set[str] = set()
    for work_id, head in sorted(ctx.facts["heads"].items()):
        selection = ctx.selections.get(head)
        if selection is None or selection["origin"] != "user":
            continue
        decision = linked.get((head, selection["version"]))
        if decision is not None:
            if ctx.decisions.is_stale(decision, ctx.facts["stale_key"]):
                look_again.add(work_id)
            elif decision["reason_code"] == "human_include":
                verified[work_id] = {"at": decision["created_at"], "via": "queue"}
            elif decision["reason_code"] == "human_criterion_not_met":
                negatives[work_id] = "criterion_not_met"
        elif selection["state"] == "included":
            verified[work_id] = {"at": list_edited.get(work_id), "via": "list"}
        elif selection["state"] == "excluded":
            negatives[work_id] = "not_recorded"

    included: dict[str, str | None] = {}
    for work_id in sorted(ctx.facts["heads"]):
        if work_id in verified or work_id in negatives:
            continue
        outcome = ctx.outcome(work_id)
        if outcome.get("outcome") == "include" and outcome.get("decided_by") == "model_agreement":
            written = next((d for d in ctx.facts["decisions"].get(work_id, [])
                            if d["stage"] == outcome["stage"] and d["source_version_id"] == outcome["source_version_id"]
                            and d["reason_code"] == outcome["reason_code"]), None)
            included[work_id] = written["created_at"] if written else None

    brought = {row[0] for row in store.conn.execute(
        "SELECT DISTINCT v.work_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        f" WHERE m.research_id = ? AND m.removed_at IS NULL AND m.added_by IN ({','.join('?' * len(BROUGHT_BY))})",
        (rid, *BROUGHT_BY))}
    seed = (store.scope(rid).get("seed_snapshot") or {}).get("source_version_id")
    if seed:
        row = store.conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (seed,)).fetchone()
        if row is not None:
            brought.add(row[0])
    brought &= set(ctx.facts["heads"])

    read = any(d["stage"] == "fulltext" and d["reason_code"] not in NOT_A_READING
               and not ctx.decisions.is_stale(d, ctx.facts["stale_key"])
               for decisions in ctx.facts["decisions"].values() for d in decisions)
    return {"revision": ctx.revision, "verified": verified, "negatives": negatives, "look_again": look_again,
            "included": included, "brought": brought, "read": read}


def probes_view(store: Store, research_id: str, probe: dict[str, Any]) -> dict[str, Any]:
    """What the research view shows of the probe set: the counts of each column and the probes no arm found."""
    kinds = {"criterion_not_met": 0, "not_recorded": 0}
    for kind in probe["negatives"].values():
        kinds[kind] += 1
    return {
        "verified": len(probe["verified"]),
        # No answer records a work as out of scope (owner's answer E): the count is not zero, it is not recorded, and
        # the negatives are not a false-positive rate.
        "negatives": kinds | {"out_of_scope": None},
        "look_again": len(probe["look_again"]),
        "included_by_agreement": len(probe["included"]),
        "brought": len(probe["brought"]),
        "judge_min": PROBE_JUDGE_MIN,
        # Whether any work of this revision has a full-text reading yet: before it, nothing can be included.
        "read": probe["read"],
        "not_found": not_found(store, research_id, probe),
    }


def not_found(store: Store, research_id: str, probe: dict[str, Any]) -> dict[str, Any]:
    """The confirmed and brought works no search or chain request of this revision found, by name (SW13.7).

    Every discovery run of the revision counts, not the view's latest ten. A stored hit is a find in any run, even one
    whose other searches kept no hit rows. A run whose searches returned records it kept no hit row for (before D93)
    cannot say what it did not find: with such a run, a probe no stored hit names is `unknown`, never "not found";
    with no hit row and no fully kept run at all, the list is `not_counted`.
    """
    probes = sorted(set(probe["verified"]) | probe["brought"])
    runs = [row[0] for row in store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND kind = 'discovery' AND scope_revision = ? ORDER BY created_at, id",
        (research_id, probe["revision"]))]
    searches: dict[str, list[dict[str, Any]]] = {}
    if runs:
        for row in store.conn.execute(
                f"SELECT id, run_id, status, result_count FROM search_runs WHERE run_id IN ({','.join('?' * len(runs))})",
                runs):
            searches.setdefault(row["run_id"], []).append(dict(row))
    if not searches:
        return {"status": "no_search", "works": []}
    if not probes:
        return {"status": "counted", "works": []}
    ours = {s["id"] for rows in searches.values() for s in rows}
    hits: set[str] = set()
    found: set[str] = set()
    for row in store.conn.execute(
            "SELECT h.search_run_id, v.work_id FROM candidate_hits h JOIN source_versions v ON v.id = h.source_version_id"
            " WHERE h.research_id = ? AND h.scope_revision = ?", (research_id, probe["revision"])):
        if row["search_run_id"] in ours:
            hits.add(row["search_run_id"])
            found.add(row["work_id"])
    traced = {run for run, rows in searches.items()
              if not any(s["result_count"] and s["status"] == "completed" and s["id"] not in hits for s in rows)}
    if not traced and not hits:
        return {"status": "not_counted", "works": []}
    partial = len(traced) < len(searches)
    missing = [work_id for work_id in probes if work_id not in found]
    heads = store.work_heads(research_id)
    works = []
    for work_id in missing:
        head = store.source(heads[work_id])
        works.append({"work_id": work_id, "source_version_id": head["id"], "title": head["title"], "doi": head["doi"],
                      "source_key": store.source_key(work_id),
                      "reasons": [r for r, member in (("verified", work_id in probe["verified"]),
                                                      ("brought", work_id in probe["brought"])) if member],
                      "found": "unknown" if partial else "no"})
    return {"status": "partial" if partial else "counted", "works": works}


# ---- the arm rows (D93's source counts, extended) ------------------------------------------------------------------


def arm_counts(store: Store, run_id: str, searches: list[dict[str, Any]], works: dict[str, set[str]],
               first: int | None, card: dict[str, Any] | None, probe: dict[str, Any]) -> dict[str, Any]:
    """What slice 19 adds beside one counted run's source counts, row for row in D93's order: rows returned,
    included and confirmed works in D93's "only" universe, the query origin split, and the arm-kind line.
    `views.source_counts` hands over what it read. `chain` is absent when the run chained nothing.
    """
    included, verified = set(probe["included"]), set(probe["verified"])
    queries = (((card or {}).get("output") or {}).get("approved") or {}).get("queries") or []
    rounds: dict[int, dict[str, dict[str, Any]]] = {}
    chain = {"rows": 0, "works": set()}
    for search in searches:
        found = works.get(search["id"], set())
        if search["operation_key"].startswith(CHAIN_PREFIX):
            chain["rows"] += search["result_count"] or 0
            chain["works"] |= found
            continue
        index = re.match(r"search:(\d+)", search["operation_key"])
        number = 2 if first is not None and index and int(index.group(1)) >= first else 1
        row = rounds.setdefault(number, {}).setdefault(search["provider"], {"rows": 0, "works": set(), "origins": {}})
        row["rows"] += search["result_count"] or 0
        row["works"] |= found
        # The origin is read by the step's index in the approved list, never by the query text, which can recur in
        # the second round; a card that names no origin gives no split.
        origin = (queries[int(index.group(1))].get("origin")
                  if number == 1 and index and int(index.group(1)) < len(queries) else None)
        row["origins"].setdefault(origin, set()).update(found)
    everywhere: dict[str, set[str]] = {}
    for providers in rounds.values():
        for provider, row in providers.items():
            everywhere.setdefault(provider, set()).update(row["works"])
    keyword_works = set().union(*everywhere.values()) if everywhere else set()

    def counted(found: set[str], only: set[str]) -> dict[str, int]:
        return {"included": len(found & included), "included_only": len(only & included),
                "verified": len(found & verified), "verified_only": len(only & verified)}

    extended = []
    for number, providers in sorted(rounds.items()):
        sources = []
        for provider, row in providers.items():
            others = set().union(*(w for p, w in everywhere.items() if p != provider))
            fields = {"provider_id": provider, "rows": row["rows"], **counted(row["works"], row["works"] - others)}
            origins = row["origins"]
            if number == 1 and None not in origins and len(origins) > 1:
                fields["by_origin"] = [{"origin": origin, "works": len(found), "included": len(found & included)}
                                       for origin, found in sorted(origins.items())]
            sources.append(fields)
        extended.append({"round": number, "sources": sources})
    chain_fields = ({"rows": chain["rows"], **counted(chain["works"], chain["works"] - keyword_works)}
                    if any(s["operation_key"].startswith(CHAIN_PREFIX) for s in searches) else None)

    # The arm kinds in run order: what each found that no kind before it in this run had (SW13.4's input, no rule).
    kinds = []
    seen: set[str] = set()
    for kind, ran, found in (
            ("keyword", 1 in rounds, set().union(*(r["works"] for r in rounds.get(1, {}).values()))),
            ("expansion", 2 in rounds, set().union(*(r["works"] for r in rounds.get(2, {}).values()))),
            ("chain", chain_fields is not None, chain["works"])):
        if not ran:
            kinds.append({"kind": kind, "ran": False})
            continue
        new = found - seen
        seen |= found
        kinds.append({"kind": kind, "ran": True, "works": len(found), "new_works": len(new),
                      "included": len(found & included), "new_included": len(new & included),
                      "verified": len(found & verified), "new_verified": len(new & verified)})
    arms: dict[str, Any] = {"rounds": extended, "kinds": kinds, "read": probe["read"]}
    if chain_fields is not None:
        arms["chain"] = chain_fields
    return arms


# ---- the signal table ----------------------------------------------------------------------------------------------


def _stamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _captures(store: Store, step_id: str, works: set[str], signals: list[str]) -> dict[str, Any]:
    """Where these works stood in one ranking step: the denominator and, per signal and order, the captures.

    A work is joined to the step through each row's version (`source_versions.work_id`), so a head that changed
    after the ranking still finds its work; a work with several rows counts once, at its best place. In a single
    signal only a row the signal scored counts, and a tie group counts only when its last position is inside the cut;
    a group across the cut is counted apart as tied at the cut. The two orders are exact places.
    """
    rows: dict[str, list[tuple[str, float, bool]]] = {}
    if works:
        for row in store.conn.execute(
                "SELECT v.work_id, r.signal, r.rank, r.available FROM record_signal_ranks r JOIN source_versions v"
                f" ON v.id = r.source_version_id WHERE r.ranking_step_id = ? AND v.work_id IN ({','.join('?' * len(works))})",
                (step_id, *sorted(works))):
            rows.setdefault(row["work_id"], []).append((row["signal"], row["rank"], bool(row["available"])))
    ranks = sorted({rank for found in rows.values() for signal, rank, available in found
                    if available and signal in signals})
    group: dict[tuple[str, float], int] = {}
    if ranks:
        for row in store.conn.execute(
                "SELECT signal, rank, COUNT(*) AS size FROM record_signal_ranks WHERE ranking_step_id = ? AND available = 1"
                f" AND rank IN ({','.join('?' * len(ranks))}) GROUP BY signal, rank", (step_id, *ranks)):
            group[(row["signal"], row["rank"])] = row["size"]
    table = []
    for name in [*signals, *ORDERS]:
        top = {cut: 0 for cut in CUTS}
        tied = {cut: 0 for cut in CUTS}
        for found in rows.values():
            places = [(rank, available) for signal, rank, available in found if signal == name]
            for cut in CUTS:
                if name in ORDERS:
                    top[cut] += any(rank <= cut for rank, _ in places)
                    continue
                spans = [(rank - (group[(name, rank)] - 1) / 2, rank + (group[(name, rank)] - 1) / 2)
                         for rank, available in places if available]
                if any(last <= cut for _, last in spans):
                    top[cut] += 1
                elif any(first <= cut < last for first, last in spans):
                    tied[cut] += 1
        table.append({"signal": name, **{f"top_{cut}": top[cut] for cut in CUTS},
                      **{f"tied_{cut}": tied[cut] for cut in CUTS}})
    return {"denominator": len(rows), "rows": table}


def signal_table(store: Store, run_id: str, probe: dict[str, Any]) -> dict[str, Any] | None:
    """What this discovery run's keyword ranking step shows against the probe set, or None when it ranked nothing.

    Descriptive only: which signals ran and why not, the person's confirmed works in each signal's top 100 and 200
    with the denominator and `too_few` below `PROBE_JUDGE_MIN`, the model-agreement works in their own row, and the
    records the embedding moved up with what was decided about them after the ranking. The chain's ranking (D95) is
    not read.
    """
    step = store.conn.execute(
        "SELECT id, output_json, finished_at FROM run_steps WHERE run_id = ? AND operation_key = 'ranking'"
        " AND kind = 'code:ranking' AND status = 'succeeded'", (run_id,)).fetchone()
    if step is None:
        return None
    output = json.loads(step["output_json"]) if step["output_json"] else {}
    stored = {row[0] for row in store.conn.execute(
        "SELECT DISTINCT signal FROM record_signal_ranks WHERE ranking_step_id = ?", (step["id"],))}
    ran = [name for name in SIGNALS if name in stored]
    signals = [{"signal": name, "ran": (output.get("signals") or {}).get(name, {}).get("ran", name in stored),
                "reason": (output.get("signals") or {}).get(name, {}).get("reason"),
                "available": (output.get("signals") or {}).get(name, {}).get("available")} for name in SIGNALS]
    seeds = output.get("seeds") or []
    person = _captures(store, step["id"], set(probe["verified"]), ran)
    person["status"] = "too_few" if person["denominator"] < PROBE_JUDGE_MIN else "descriptive"
    agreement = _captures(store, step["id"], set(probe["included"]), ran)
    table: dict[str, Any] = {
        "step_id": step["id"], "pool": output.get("pool"), "signals": signals,
        "seeds": {"verified": sum(s["kind"] == "verified" for s in seeds), "code": sum(s["kind"] == "code" for s in seeds)},
        "no_reference_list_share": output.get("no_reference_list_share"),
        "person": person,
        # Read because the order put them near the top: their places are not a signal's success (plan, number 3).
        "agreement": agreement | {"note": "read_because_ranked"},
        "embedding": None,
    }
    if "embedding" in ran:
        table["embedding"] = _moved_up(store, output.get("rescued") or [], step["finished_at"], probe)
    return table


def _moved_up(store: Store, rescued: list[str], finished_at: str | None, probe: dict[str, Any]) -> dict[str, int]:
    """The records the embedding brought to the front (SW8.1), and what was decided about them after the ranking.

    Observational: a moved-up record could be labelled because it was read, and one not moved up was never read. A
    decision is "after" only when its stored time is later than the ranking step's end; one written before (a second
    discovery run re-ranking a work already included) is `already_decided`; an unreadable time or the same millisecond
    proves neither and is `time_unknown`.
    """
    counts = {"moved_up": len(rescued), "moved_up_then_included": 0, "moved_up_then_verified": 0,
              "moved_up_already_decided": 0, "moved_up_time_unknown": 0}
    if not rescued:
        return counts
    work_of = {row[0]: row[1] for row in store.conn.execute(
        f"SELECT id, work_id FROM source_versions WHERE id IN ({','.join('?' * len(rescued))})", rescued)}
    ended = _stamp(finished_at)
    for work_id in sorted({work_of[svid] for svid in rescued if svid in work_of}):
        if work_id in probe["verified"]:
            at, column = _stamp(probe["verified"][work_id]["at"]), "moved_up_then_verified"
        elif work_id in probe["included"]:
            at, column = _stamp(probe["included"][work_id]), "moved_up_then_included"
        else:
            continue
        if at is None or ended is None or at == ended:
            counts["moved_up_time_unknown"] += 1
        elif at > ended:
            counts[column] += 1
        else:
            counts["moved_up_already_decided"] += 1
    return counts

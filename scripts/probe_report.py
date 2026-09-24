"""Comparative signal and arm report of one stored library against an outside reference set (slice 19, decision 7).

Usage: PYTHONPATH=backend:. uv run --no-sync python scripts/probe_report.py LIBRARY.sqlite REFERENCE.jsonl > report.json

The library is opened read-only (`mode=ro`) and copied into memory, where it is migrated to the product's schema so
the product's own derivations (`probes.arm_counts`, the signal table's capture rule) read it; the file on disk is
never written. The reference set is a JSONL file. Its first line is a header, `{"origin": ..., "completeness": ...}`:
how the set was made and what is known to be missing from it; a file without both is refused. Every other line is
one paper: `{"key", "title", "dois": [...], "openalex_ids": [...], "role": "positive" | "negative"}` (role defaults to
positive).

What it writes, per `sw` research, for the latest discovery run that has a keyword ranking step:

- the arm rows and the arm-kind line (decisions 3–4), once with the product's own columns and once with the
  reference positives in the place of the included works;
- per signal and for the two stored orders, the reference positives and negatives in the top 100 and 200 (the
  product's rule: in a single signal only a scored row counts and a tie group across the cut is counted apart), and
  the median stored place;
- the change in the fused top 200 when one signal is left out of the fusion, with a 95% paired bootstrap interval
  (2,000 resamples, seed 0, positives in key order), named as holding in this pool and this reference set.

A reference entry is found when one of the research's works matches a DOI, an OpenAlex id or the normalised title;
it counts once, at its best place. Entries of the same role that match a common work (a preprint and its published
version listed apart) are merged into one unit named by their smallest key and reported under
`merged_reference_entries`; entries of opposite roles matching one work make the file refused (exit 2). An entry no work matches is listed as not in the pool. A work the research
included that is not in the reference set is not counted as wrong: the set is incomplete by its own header.
Nothing here pools intervals across libraries, closes a signal for a field, or estimates a population size
(capture–recapture is not used, SW13.6). A result is a description of one pool against one list.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

from deixis.storage import db
from deixis.workflow import probes, queue, views
from deixis.workflow.ranking import SIGNALS
from deixis.workflow.store import Store

RRF_K = 60  # flow.RRF_K; read here so a stored fusion is recomputed exactly as it was written
CUTS = (100, 200)
RESAMPLES = 2000
SEED = 0
CONDITION = "in this pool and this reference set"


class ReferenceSetRefused(ValueError):
    """The reference file has no header naming its origin and its completeness, or it contradicts itself."""


class ReferenceConflict(ReferenceSetRefused):
    """Two reference entries of opposite roles (positive, negative) match the same work of the research."""


def norm_title(title: str | None) -> str:
    return re.sub(r"\W+", " ", (title or "").casefold()).strip()


def norm_doi(doi: str | None) -> str | None:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip().lower()) or None


def read_reference(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    header = json.loads(lines[0]) if lines else {}
    if not isinstance(header, dict) or not header.get("origin") or not header.get("completeness"):
        raise ReferenceSetRefused("the reference set's first line must name its origin and its completeness")
    entries = []
    seen: set[str] = set()
    for line in lines[1:]:
        row = json.loads(line)
        # One key, one paper: a key given twice (say once positive and once negative) would let one row hide the other.
        if str(row["key"]) in seen:
            raise ReferenceSetRefused(f"the reference set gives the key {row['key']!r} twice")
        seen.add(str(row["key"]))
        entries.append({"key": str(row["key"]), "title": row.get("title"), "role": row.get("role", "positive"),
                        "dois": {d for d in (norm_doi(x) for x in row.get("dois") or []) if d},
                        "ids": set(row.get("openalex_ids") or [])})
    return header, entries


def open_copy(path: Path) -> sqlite3.Connection:
    """The library in memory, migrated; the file itself is opened read-only and never written."""
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    copy = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    source.backup(copy)
    source.close()
    copy.row_factory = sqlite3.Row
    db.migrate(copy)
    return copy


def match(conn: sqlite3.Connection, research_id: str, entries: list[dict[str, Any]]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Each work of the research that a reference entry names, with the unit it counts in, and the merges made.

    Dedup rule, independent of the file's row order: entries of the same role that match a common work describe one
    paper as far as this pool can tell, so they are merged (transitively) into one unit named by their smallest key;
    every merge is reported, never resolved silently. Entries of opposite roles matching one work are refused.
    """
    keys: dict[str, dict[str, set[str]]] = {}
    for row in conn.execute(
            "SELECT v.id, v.work_id, v.doi, v.title FROM corpus_memberships m JOIN source_versions v"
            " ON v.id = m.source_version_id WHERE m.research_id = ?", (research_id,)):
        work = keys.setdefault(row["work_id"], {"dois": set(), "titles": set(), "ids": set(), "versions": set()})
        if row["doi"]:
            work["dois"].add(norm_doi(row["doi"]))
        work["titles"].add(norm_title(row["title"]))
        work["versions"].add(row["id"])
    versions = {v: w for w, k in keys.items() for v in k["versions"]}
    for row in conn.execute("SELECT source_version_id, value FROM identifier_mappings WHERE scheme = 'openalex'"):
        if row["source_version_id"] in versions:
            keys[versions[row["source_version_id"]]]["ids"].add(row["value"])
    role = {entry["key"]: entry["role"] for entry in entries}
    hits: dict[str, set[str]] = {}
    for work_id in sorted(keys):
        k = keys[work_id]
        named = {entry["key"] for entry in entries if entry["dois"] & k["dois"] or entry["ids"] & k["ids"]
                 or (entry["title"] and norm_title(entry["title"]) in k["titles"])}
        if len({role[key] for key in named}) > 1:
            raise ReferenceConflict(f"work {work_id} matches reference entries of opposite roles: "
                                    + ", ".join(f"{key} ({role[key]})" for key in sorted(named)))
        if named:
            hits[work_id] = named
    parent = {key: key for key in role}

    def root(key: str) -> str:
        while parent[key] != key:
            key = parent[key]
        return key

    for named in hits.values():
        first, *rest = sorted(named)
        for key in rest:
            a, b = sorted((root(first), root(key)))
            parent[b] = a
    unit_of = {work_id: root(min(named)) for work_id, named in hits.items()}
    groups: dict[str, set[str]] = {}
    for named in hits.values():
        for key in named:
            groups.setdefault(root(key), set()).add(key)
    merges = [{"unit": unit, "keys": sorted(members), "works": sorted(w for w, u in unit_of.items() if u == unit)}
              for unit, members in sorted(groups.items()) if len(members) > 1]
    return unit_of, merges


def signal_counts(store: Store, step_id: str, unit_of: dict[str, str], ran: list[str]) -> dict[str, Any]:
    """Per signal and order: the reference units in the top 100 and 200 by the product's rule, and the median place."""
    conn = store.conn
    if not unit_of:
        return {"in_pool": 0, "rows": []}
    marks = ",".join("?" * len(unit_of))
    rows: dict[str, list[tuple[str, float, bool]]] = {}
    for row in conn.execute(
            "SELECT v.work_id, r.signal, r.rank, r.available FROM record_signal_ranks r JOIN source_versions v"
            f" ON v.id = r.source_version_id WHERE r.ranking_step_id = ? AND v.work_id IN ({marks})",
            (step_id, *sorted(unit_of))):
        rows.setdefault(unit_of[row["work_id"]], []).append((row["signal"], row["rank"], bool(row["available"])))
    ranks = sorted({rank for found in rows.values() for signal, rank, available in found if available and signal in ran})
    group: dict[tuple[str, float], int] = {}
    if ranks:
        for row in conn.execute(
                "SELECT signal, rank, COUNT(*) AS size FROM record_signal_ranks WHERE ranking_step_id = ?"
                f" AND available = 1 AND rank IN ({','.join('?' * len(ranks))}) GROUP BY signal, rank", (step_id, *ranks)):
            group[(row["signal"], row["rank"])] = row["size"]
    table = []
    for name in [*ran, *probes.ORDERS]:
        entry: dict[str, Any] = {"signal": name}
        places = []
        for cut in CUTS:
            top = tied = 0
            for found in rows.values():
                mine = [(rank, available) for signal, rank, available in found if signal == name]
                if name in probes.ORDERS:
                    top += any(rank <= cut for rank, _ in mine)
                    continue
                spans = [(rank - (group[(name, rank)] - 1) / 2, rank + (group[(name, rank)] - 1) / 2)
                         for rank, available in mine if available]
                if any(last <= cut for _, last in spans):
                    top += 1
                elif any(first <= cut < last for first, last in spans):
                    tied += 1
            entry[f"top_{cut}"], entry[f"tied_{cut}"] = top, tied
        for found in rows.values():
            mine = [rank for signal, rank, _ in found if signal == name]
            if mine:
                places.append(min(mine))
        entry["median_place"] = statistics.median(places) if places else None
        table.append(entry)
    return {"in_pool": len(rows), "rows": table}


def leave_one_out(store: Store, step_id: str, unit_of: dict[str, str], ran: list[str]) -> dict[str, Any]:
    """The fused top-200 change when each signal is left out, with its paired bootstrap interval.

    The fusion is recomputed from the stored signal places exactly as the ranking fused them (reciprocal rank,
    constant 60, a tie broken by the record identifier), over the records of the stored fused order.
    """
    ranks: dict[str, dict[str, float]] = {}
    for row in store.conn.execute("SELECT source_version_id, signal, rank FROM record_signal_ranks WHERE ranking_step_id = ?",
                                  (step_id,)):
        ranks.setdefault(row["signal"], {})[row["source_version_id"]] = row["rank"]
    ids = sorted(ranks.get("fused", {}))
    if len(ran) < 2 or not ids or not unit_of:
        return {}
    work_of = {row[0]: row[1] for row in store.conn.execute(
        f"SELECT id, work_id FROM source_versions WHERE id IN ({','.join('?' * len(ids))})", ids)}

    def fuse(signals: list[str]) -> dict[str, int]:
        score = {i: sum(1 / (RRF_K + ranks[s][i]) for s in signals if i in ranks[s]) for i in ids}
        return {i: n + 1 for n, i in enumerate(sorted(ids, key=lambda i: (-score[i], i)))}

    groups: dict[str, list[str]] = {}
    for i in ids:
        if work_of.get(i) in unit_of:
            groups.setdefault(unit_of[work_of[i]], []).append(i)
    members = sorted(groups)
    if not members:
        return {}
    full = fuse(ran)
    rng = random.Random(SEED)
    out = {}
    for signal in ran:
        without = fuse([s for s in ran if s != signal])
        diff = [int(min(full[i] for i in groups[g]) <= 200) - int(min(without[i] for i in groups[g]) <= 200)
                for g in members]
        boots = sorted(sum(diff[rng.randrange(len(diff))] for _ in diff) for _ in range(RESAMPLES))
        out[signal] = {"change": sum(diff), "ci95": [boots[int(0.025 * RESAMPLES)], boots[int(0.975 * RESAMPLES) - 1]],
                       "condition": CONDITION}
    return out


def research_report(store: Store, research_id: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    conn = store.conn
    step = conn.execute(
        "SELECT s.id, s.run_id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND r.kind = 'discovery' AND s.operation_key = 'ranking' AND s.kind = 'code:ranking' AND s.status = 'succeeded'"
        " ORDER BY r.created_at DESC, r.id DESC LIMIT 1", (research_id,)).fetchone()
    if step is None:
        return None
    probe = probes.probe_set(queue.context(store, research_id))
    matched, merges = match(conn, research_id, entries)
    role = {entry["key"]: entry["role"] for entry in entries}
    positives = {w: k for w, k in matched.items() if role[k] == "positive"}
    negatives = {w: k for w, k in matched.items() if role[k] == "negative"}
    reference_probe = probe | {"included": dict.fromkeys(positives), "verified": {}}
    ran = [name for name in SIGNALS if conn.execute(
        "SELECT 1 FROM record_signal_ranks WHERE ranking_step_id = ? AND signal = ? LIMIT 1", (step["id"], name)).fetchone()]
    counts = views.source_counts(store, step["run_id"], probe)
    reference_counts = views.source_counts(store, step["run_id"], reference_probe)
    found_keys = {key for merge in merges for key in merge["keys"]} | set(matched.values())
    return {
        "research_id": research_id, "run_id": step["run_id"], "ranking_step_id": step["id"],
        "arms": counts,
        # The same rows with the reference positives in the place of the included works (`included*`, `kinds`).
        "arms_reference_positives": (reference_counts or {}).get("arms"),
        "signals_ran": ran,
        "positives": signal_counts(store, step["id"], positives, ran),
        "negatives": signal_counts(store, step["id"], negatives, ran),
        "leave_one_out_top200": leave_one_out(store, step["id"], positives, ran),
        "not_in_pool": sorted(entry["key"] for entry in entries if entry["key"] not in found_keys),
        # Same-role entries that matched a common work, merged into one unit named by the smallest key.
        "merged_reference_entries": merges,
        # Included by two agreeing runs but not in the reference set: not counted as wrong, the set is incomplete.
        "included_not_in_reference": len(set(probe["included"]) - set(positives)),
    }


def report(library: Path, reference: Path) -> dict[str, Any]:
    header, entries = read_reference(reference)
    conn = open_copy(library)
    try:
        store = Store(conn)
        researches = [row[0] for row in conn.execute(
            "SELECT s.research_id FROM scope_revisions s WHERE s.search_workflow = 'sw' AND s.revision ="
            " (SELECT MAX(revision) FROM scope_revisions x WHERE x.research_id = s.research_id) ORDER BY s.research_id")]
        results = [r for rid in researches if (r := research_report(store, rid, entries)) is not None]
    finally:
        conn.close()
    return {"library": str(library), "reference_set": {"origin": header["origin"], "completeness": header["completeness"],
                                                       "entries": len(entries)},
            "condition": f"Every count and interval holds {CONDITION}; intervals are not pooled across libraries.",
            "researches": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("library", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args(argv)
    try:
        out = report(args.library, args.reference)
    except ReferenceSetRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    json.dump(out, sys.stdout, indent=1, sort_keys=True, default=sorted)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Benchmark check for one research: did the answer cite the papers a reference tool cited for the same question?

  PYTHONPATH=backend uv run --no-sync python scripts/benchmark/check.py res_... [--benchmark scripts/benchmark/dbr_vbf.json]

For every benchmark paper it prints where the paper stopped in the run: found by the search, its ranking place,
the abstract decision, the full-text decision, whether its passages went into the answer step and whether the
answer cited it. Gate (a) is automatic: every anchor paper is cited. Gate (b), that the answer states the expected
direction and ties it to an anchor paper, is for a person: the script prints the claims that name both sides of the
comparison and the papers they cite. Read-only on the library; the result goes to .local/benchmark/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    if env := os.environ.get("DEIXIS_DATA_DIR"):
        return Path(env).expanduser()
    return Path.home() / "Library" / "Application Support" / "DEIXIS"


def norm(text: str | None) -> str:
    return re.sub(r"\W+", " ", (text or "").casefold()).strip()


def connect() -> sqlite3.Connection:
    path = data_dir() / "library.sqlite"
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def paper_versions(conn: sqlite3.Connection, paper: dict[str, Any]) -> list[str]:
    """Every source version of the works that carry this DOI, or this title when the paper has no DOI."""
    if paper.get("doi"):
        works = [r[0] for r in conn.execute(
            "SELECT DISTINCT work_id FROM source_versions WHERE lower(doi) = ?", (paper["doi"].lower(),))]
    else:
        want = norm(paper["title"])
        works = sorted({r["work_id"] for r in conn.execute(
            "SELECT work_id, title FROM source_versions WHERE title LIKE ?", (paper["title"][:30] + "%",))
            if norm(r["title"]) == want})
    if not works:
        return []
    marks = ",".join("?" * len(works))
    return [r[0] for r in conn.execute(f"SELECT id FROM source_versions WHERE work_id IN ({marks})", works)]


def latest_ranking(conn: sqlite3.Connection, rid: str, revision: int) -> list[str]:
    """The inspection order of the newest ranking step, as `DecisionStore.latest_ranking` reads it."""
    row = conn.execute(
        "SELECT s.id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND r.scope_revision = ?"
        " AND s.operation_key = 'ranking' AND s.kind = 'code:ranking' AND s.status = 'succeeded'"
        " ORDER BY s.finished_at DESC, s.id DESC LIMIT 1", (rid, revision)).fetchone()
    if row is None:
        return []
    return [r[0] for r in conn.execute(
        "SELECT source_version_id FROM record_signal_ranks WHERE ranking_step_id = ? AND signal = 'inspection'"
        " ORDER BY rank", (row["id"],))]


def decision(conn: sqlite3.Connection, rid: str, revision: int, svids: list[str], stage: str) -> str | None:
    """The open decisions of this question revision; superseded ones are history, not the run's verdict."""
    marks = ",".join("?" * len(svids))
    rows = conn.execute(
        f"SELECT outcome, reason_code FROM stage_decisions WHERE research_id = ? AND scope_revision = ? AND stage = ?"
        f" AND superseded_at IS NULL AND source_version_id IN ({marks}) ORDER BY created_at DESC",
        (rid, revision, stage, *svids)).fetchall()
    return ", ".join(sorted({f"{r['outcome']}/{r['reason_code']}" for r in rows})) or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("research_id")
    parser.add_argument("--benchmark", default=str(ROOT / "scripts/benchmark/dbr_vbf.json"))
    parser.add_argument("--answer", help="answer id; default is the research's newest answer")
    args = parser.parse_args()
    bench = json.loads(Path(args.benchmark).read_text())
    conn = connect()
    rid = args.research_id

    answer_sql = "SELECT * FROM answers WHERE research_id = ?" + (" AND id = ?" if args.answer else "")
    answer = conn.execute(answer_sql + " ORDER BY created_at DESC LIMIT 1",
                          (rid, args.answer) if args.answer else (rid,)).fetchone()
    if answer is None or not answer["draft_json"]:
        print(f"{rid}: no answer with a draft", file=sys.stderr)
        return 2
    draft = json.loads(answer["draft_json"])
    payload = json.loads(conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?",
                                      (answer["step_input_id"],)).fetchone()[0])
    given_sources = {s["source_id"] for s in payload.get("sources", [])}
    given_passages: dict[str, list[str]] = {}
    for p in payload.get("passages", []):
        given_passages.setdefault(p["source_id"], []).append(p.get("reading_depth") or "?")
    passage_ids = {pid for c in draft.get("claims", []) for pid in c.get("passage_ids", [])}
    passage_ids |= {a["passage_id"] for a in draft.get("citation_anchors", [])}
    marks = ",".join("?" * len(passage_ids)) or "''"
    source_of = dict(conn.execute(f"SELECT id, source_version_id FROM passages WHERE id IN ({marks})",
                                  tuple(passage_ids)).fetchall())
    doi_of = dict(conn.execute(f"SELECT id, doi FROM source_versions WHERE id IN ({','.join('?' * len(source_of)) or "''"})",
                               tuple(source_of.values())).fetchall())
    cited_claims: dict[str, list[str]] = {}
    for c in draft.get("claims", []):
        for pid in c.get("passage_ids", []):
            if pid in source_of:
                cited_claims.setdefault(source_of[pid], []).append(c["claim_label"])
    revision = answer["scope_revision"]
    ranking = latest_ranking(conn, rid, revision)
    place = {svid: i + 1 for i, svid in enumerate(ranking)}

    rows: list[dict[str, Any]] = []
    for paper in bench["papers"]:
        svids = paper_versions(conn, paper)
        in_search = bool(svids) and conn.execute(
            f"SELECT 1 FROM candidates WHERE research_id = ? AND scope_revision = ?"
            f" AND source_version_id IN ({','.join('?' * len(svids))}) LIMIT 1", (rid, revision, *svids)).fetchone() is not None
        ranks = [place[s] for s in svids if s in place]
        claims = sorted({label for s in svids for label in cited_claims.get(s, [])})
        rows.append({
            "key": paper["key"], "doi": paper.get("doi"), "anchor": paper.get("anchor", False),
            "found": in_search, "rank": min(ranks) if ranks else None, "ranked_of": len(ranking),
            "abstract": decision(conn, rid, revision, svids, "abstract") if svids else None,
            "fulltext": decision(conn, rid, revision, svids, "fulltext") if svids else None,
            "given_to_model": any(s in given_sources for s in svids),
            "passages_given": sorted(d for s in svids for d in given_passages.get(s, [])),
            "cited_in": claims,
            # A paper is matched by work: a cited version with another DOI (preprint, other record) still counts,
            # and this list shows which version and DOI the answer actually cited.
            "cited_versions": sorted({f"{s} doi={doi_of.get(s) or '-'}" for s in svids if s in cited_claims}),
        })

    # Gate (b) material: claims that name both sides of the comparison, with the benchmark papers they cite.
    key_of = {s: r["key"] for r, paper in zip(rows, bench["papers"]) for s in paper_versions(conn, paper)}
    sides = [[t.casefold() for t in side] for side in bench.get("direction_terms", [])]
    direction_claims = []
    for c in draft.get("claims", []):
        text = c["text"].casefold()
        if sides and all(any(t in text for t in side) for side in sides):
            papers = sorted({key_of.get(source_of.get(pid, ""), "other") for pid in c.get("passage_ids", [])})
            direction_claims.append({"label": c["claim_label"], "text": c["text"], "cites": papers})

    # Only a structurally valid answer passed citation validation; any other draft may cite unverified passages.
    assessable = answer["status"] == "structurally_valid"
    gate_a = assessable and all(r["cited_in"] for r in rows if r["anchor"])
    anchors = {r["key"] for r in rows if r["anchor"]}
    gate_b_candidates = [c for c in direction_claims if anchors & set(c["cites"])]

    print(f"{rid} · answer {answer['id']} ({answer['status']}, {answer['created_at']})")
    print(f"{len(given_sources)} sources and {len(payload.get('passages', []))} passages went into the answer step;"
          f" ranking has {len(ranking)} works\n")
    print(f"{'paper':<14}{'anchor':<8}{'found':<7}{'rank':<7}{'abstract':<38}{'full text':<34}{'to model':<10}cited in")
    for r in rows:
        print(f"{r['key']:<14}{'yes' if r['anchor'] else '':<8}{'yes' if r['found'] else 'no':<7}"
              f"{r['rank'] or '-':<7}{r['abstract'] or '-':<38}{r['fulltext'] or 'not tried':<34}"
              f"{'yes' if r['given_to_model'] else 'no':<10}{', '.join(r['cited_in']) or '-'}")
    for r in rows:
        for version in r["cited_versions"]:
            if r["doi"] and f"doi={r['doi']}" not in version.lower():
                print(f"  note: {r['key']} cited through another version of the same work: {version}")
    if not assessable:
        print(f"\nGate (a) NOT ASSESSABLE: answer status is {answer['status']}, not structurally_valid")
    else:
        print(f"\nGate (a) anchor papers cited: {'PASS' if gate_a else 'FAIL'}")
    print(f"Gate (b) is a human call. Expected: {bench['expected_direction']}")
    if direction_claims:
        for c in direction_claims:
            print(f"  [{c['label']}] cites {', '.join(c['cites'])}: {c['text']}")
    else:
        print("  no claim names both sides of the comparison")
    print(f"  claims naming both sides that cite an anchor paper: {len(gate_b_candidates)}")
    print(f"\nResult: {'pass on (a); check (b) above' if gate_a else 'stopped short (gate a fails)'}")

    out = ROOT / ".local" / "benchmark"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"{bench['name']}-{rid}-{stamp}.json"
    path.write_text(json.dumps({
        "benchmark": bench["name"], "research_id": rid, "answer_id": answer["id"], "checked_at": stamp,
        "answer_status": answer["status"], "assessable": assessable, "scope_revision": revision,
        "sources_given": len(given_sources), "passages_given": len(payload.get("passages", [])),
        "papers": rows, "direction_claims": direction_claims, "gate_a": gate_a,
        "gate_b_candidates": [c["label"] for c in gate_b_candidates],
    }, indent=1, ensure_ascii=False))
    print(f"written {path.relative_to(ROOT)}")
    return 0 if gate_a else 1


if __name__ == "__main__":
    sys.exit(main())

"""Acceptance (a), (b input) and (e) of slice 22 (D104): the product's own arXiv source code in a dry run over a copy.

The live library is opened read-only and copied with SQLite's backup API into a scratch directory; the copy is migrated to
0053, checked, migrated to 0054 and checked again (the plan's number 16 checks: rowid/id/text_sha256/text_source equality,
an FTS query and `integrity-check`, `foreign_key_check`, the DDL difference and the trigger SQL). Source files already
downloaded by the plan (`.local/sw-slice22-plan-2026-09-25/src/`) are copied into the scratch data directory's
`arxiv-sources/` and registered as downloaded rows; nothing is fetched. Then, for every stored arXiv PDF (one PDF per arXiv
version), the product's code decides eligibility, inspects and matches the source in its child process and places the
matches in a text-layer extraction, without writing any extraction. Counted apart: number lines, candidates that pass the
matching rule, blocks really placed, and every reason a candidate was not placed. Agreement with Marker's stored reading is
a comparison, not a ground truth.

    PYTHONPATH=backend:. uv run python scripts/arxiv_source_report.py --scratch <dir> --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from deixis.documents import arxiv_source as src
from deixis.documents import pdf
from deixis.storage import db

REPO = Path(__file__).resolve().parents[1]
LIVE = Path.home() / "Library/Application Support/DEIXIS"
PLAN = REPO / ".local/sw-slice22-plan-2026-09-25"


def backup(live: Path, copy: Path) -> None:
    source = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    target = sqlite3.connect(copy)
    source.backup(target)
    target.close()
    source.close()


def migrate_with_checks(copy: Path, scratch: Path) -> dict:
    """0053 first (the rebuild left out), then 0054, with the plan's number 16 checks around the second step."""
    folder = scratch / "migrations-0053"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if not path.name.startswith("0054_"):
            shutil.copy(path, folder / path.name)
    real = db.MIGRATIONS_DIR
    conn = db.connect(copy)
    first = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    db.MIGRATIONS_DIR = folder
    try:
        applied_to_53 = db.migrate(conn)
    finally:
        db.MIGRATIONS_DIR = real
    ddl = lambda name: conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]  # noqa: E731
    before = {"ddl": ddl("passages"), "trigger": ddl("cell_evidence_same_source"),
              "rows": conn.execute("SELECT rowid, id, text_sha256, text_source FROM passages ORDER BY rowid").fetchall(),
              "fts": conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'channel' ORDER BY rowid").fetchall(),
              "others": {r[0]: r[1] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'passages%'"
                                                           " AND name <> 'cell_evidence_same_source'")}}
    started = time.perf_counter()
    applied = db.migrate(conn)
    seconds = time.perf_counter() - started
    conn.execute("INSERT INTO passages_fts(passages_fts, rank) VALUES ('integrity-check', 1)")  # raises when broken
    after_rows = conn.execute("SELECT rowid, id, text_sha256, text_source FROM passages ORDER BY rowid").fetchall()
    normalize = lambda s: re.sub(r'CREATE TABLE "?passages(_new)?"?', "CREATE TABLE passages", s)  # noqa: E731
    others_after = {r[0]: r[1] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'passages%'"
                                                      " AND name <> 'cell_evidence_same_source'")}
    check = {
        "schema_at_start": first, "applied_to_0053": applied_to_53, "applied": applied, "seconds_0053_to_0054": round(seconds, 3),
        "passages": len(after_rows), "rows_equal": [tuple(r) for r in after_rows] == [tuple(r) for r in before["rows"]],
        "fts_channel_rows": len(before["fts"]),
        "fts_equal": conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'channel' ORDER BY rowid").fetchall() == before["fts"],
        "fts_integrity_check": "passed", "foreign_key_check": conn.execute("PRAGMA foreign_key_check").fetchall(),
        "ddl_differs_only_in_check": normalize(ddl("passages")) == normalize(before["ddl"]).replace("'marker'))", "'marker', 'latex_source'))"),
        "trigger_sql_equal": ddl("cell_evidence_same_source") == before["trigger"],
        "other_objects_changed": sorted(k for k in set(before["others"]) | set(others_after)
                                        if before["others"].get(k) != others_after.get(k)),
        "new_tables_empty": [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("arxiv_sources", "asset_arxiv_versions")],
    }
    conn.close()
    return check


def tokens(latex: str) -> list[str]:
    latex = re.sub(r"\\(label|tag)\{[^}]*\}|\\(nonumber|notag|left|right|big|Big|bigg|Bigg|displaystyle|limits|,|;|!|quad|qquad|mathrm|text"
                   r"|textrm|operatorname|mathbf|boldsymbol|bm|mbox|rm)\b|&|~", " ", latex)
    return re.findall(r"\\[A-Za-z]+|[A-Za-z]|\d+|[^\s{}]", latex)


def similarity(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", type=Path, required=True, help="scratch DEIXIS_DATA_DIR for the copy")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", type=Path, default=LIVE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = args.scratch
    if data.exists():
        shutil.rmtree(data)
    (data / "papers").mkdir(parents=True)
    copy = data / "library.sqlite"
    backup(args.live / "library.sqlite", copy)
    migration = migrate_with_checks(copy, args.scratch.parent)
    (args.out / "migration-check.json").write_text(json.dumps(migration, indent=1))
    print("migration", {k: v for k, v in migration.items() if k != "foreign_key_check"}, flush=True)

    conn = db.connect(copy)
    conn.row_factory = sqlite3.Row
    assets = conn.execute(
        "SELECT a.id, a.storage_path, a.retrieved_from, a.extraction_version, s.id AS svid, s.doi, s.landing_url, s.oa_pdf_url, s.version_label"
        " FROM source_assets a JOIN source_versions s ON s.id = a.source_version_id WHERE a.removed_at IS NULL"
        " AND (a.retrieved_from LIKE '%arxiv.org%' OR LOWER(s.doi) LIKE '10.48550/arxiv.%') ORDER BY a.retrieved_at, a.id").fetchall()
    folder = data / "arxiv-sources"
    folder.mkdir()
    registered = 0
    for path in sorted((PLAN / "src").iterdir()):
        key = path.name.replace("_", "/")
        body = path.read_bytes()
        shutil.copy(path, folder / f"{src.file_name(key)}.src")
        arxiv_id, version = src.split_key(key)
        conn.execute("INSERT INTO arxiv_sources (arxiv_key, arxiv_id, version, status, sha256, byte_size, storage_path, http_status, attempts,"
                     " fetched_at) VALUES (?, ?, ?, 'downloaded', ?, ?, ?, 200, 1, ?)",
                     (key, arxiv_id, version, hashlib.sha256(body).hexdigest(), len(body), f"arxiv-sources/{src.file_name(key)}.src", db.now()))
        registered += 1

    class Store:  # the SourceStore needs only a connection
        pass
    store = Store()
    store.conn = conn
    sources = src.SourceStore(store, data)
    papers, seen_keys, rows, placed_all, per_paper = [], set(), [], [], []
    for asset in assets:
        path = args.live / "papers" / asset["storage_path"]
        shutil.copy(path, data / "papers" / asset["storage_path"])
        found = src.eligibility(src.url_key(asset["retrieved_from"]), src.stamp_key(path), dict(asset))
        entry = {"asset": asset["id"], "key": found["arxiv_key"], "eligibility": found["eligibility"], "version_from": found["version_from"],
                 "marker_read": "+marker-" in (asset["extraction_version"] or "")}
        papers.append(entry)
        if found["eligibility"] != "eligible" or found["arxiv_key"] in seen_keys:
            entry["counted"] = False
            continue
        entry["counted"] = True
        seen_keys.add(found["arxiv_key"])
        row = sources.row(found["arxiv_key"])
        if row is None:
            entry["outcome"] = "no_source_file"
            continue
        body, problem = asyncio.run(sources.read(found["arxiv_key"]))
        if problem:
            entry["outcome"] = problem
            continue
        result = asyncio.run(src.read_source(body, path, set(), report=True))
        entry |= {"content": result["content"], "child_seconds": result.get("child_seconds"), "error": result.get("error")}
        if result["content"] != "tex":
            continue
        extraction = pdf.extract_pdf(path, placements=result["placements"])
        placement = extraction.placement or {"placed": [], "refused": []}
        refused = Counter(r["reason"] for r in placement["refused"])
        placed_keys = {(p["page"], p["n"]) for p in placement["placed"]}
        marker, pages_text = {}, {}
        if entry["marker_read"]:
            for page, text in conn.execute("SELECT physical_page, text FROM passages WHERE asset_id = ? AND extraction_version = ?"
                                           " AND text_source = 'marker' ORDER BY physical_page, rowid", (asset["id"], asset["extraction_version"])):
                pages_text[page] = pages_text.get(page, "") + "\n" + text
            for page, text in pages_text.items():
                for block in re.finditer(r"\$\$(.+?)\$\$", text, re.S):  # the plan's number 7 reading of Marker's numbers
                    latex = block.group(1)
                    tag = (re.search(r"\\tag\{(\d{1,3}[a-z]?)\}", latex) or re.search(r"\((\d{1,3}[a-z]?)\)\s*$", latex)
                           or re.match(r"\s*\((\d{1,3}[a-z]?)\)", text[block.end():]))
                    if tag:
                        marker.setdefault((page, tag.group(1)), re.sub(r"\\tag\{[^}]*\}|\(\d{1,3}[a-z]?\)\s*$", " ", latex))
        group_latex = {int(k): v for k, v in result["group_latex"].items()}
        group_tokens = {k: tokens(v) for k, v in group_latex.items()}
        for r in result["rows"]:
            r |= {"key": found["arxiv_key"], "asset": asset["id"]}
            if r["placed"]:
                r["placed"] = (r["page"], r["n"]) in placed_keys
                if not r["placed"]:
                    r["reason"] = next((x["reason"] for x in placement["refused"] if (x["page"], x["n"]) == (r["page"], r["n"])), "refused")
            if r.get("candidate") and (r["page"], r["n"]) in marker and r["group"] is not None:
                reference = tokens(marker[(r["page"], r["n"])])
                best = max(group_tokens, key=lambda k: similarity(reference, group_tokens[k]))
                sim = similarity(reference, group_tokens[r["group"]])
                r["marker_agrees"] = best == r["group"] or sim >= 0.85
                r["marker_similarity"] = round(sim, 3)
            rows.append(r)
        details = {(p["page"], p["n"]): p for p in result["placements"]}
        for p in placement["placed"]:
            d = details[(p["page"], p["n"])]
            placed_all.append({"key": found["arxiv_key"], "asset": asset["id"], "storage_path": asset["storage_path"], "page": p["page"],
                               "n": p["n"], "latex": d["latex"], "box": d["box"], "lines": d["lines"], "paper_margin": d["paper_margin"],
                               "window_margin": d["window_margin"], "order_decided": d["order_decided"], "f1": d["f1"], "recall": d["recall"]})
        per_paper.append({"key": found["arxiv_key"], "number_lines": result["number_lines"], "candidates": result["candidates"],
                          "asked": len(result["placements"]), "placed": len(placement["placed"]), "refused": dict(refused),
                          "not_placed": result["not_placed"], "child_seconds": result.get("child_seconds"), "seconds": result.get("seconds")})
        print(found["arxiv_key"], per_paper[-1], flush=True)

    reasons = Counter(r["reason"] for r in rows if r.get("candidate") and not r["placed"])
    matched = [p for p in per_paper]
    seconds = sorted(p["child_seconds"] for p in matched if p["child_seconds"] is not None)
    with_marker = [r for r in rows if "marker_agrees" in r]
    summary = {
        "pdfs": len(papers), "eligibility": Counter(p["eligibility"] for p in papers), "versions_counted": len(seen_keys),
        "sources_registered": registered, "content": Counter(p.get("content", p.get("outcome")) for p in papers if p["counted"]),
        "versions_matched": len(matched), "number_lines": sum(p["number_lines"] for p in matched),
        "candidates": sum(p["candidates"] for p in matched), "placed": sum(p["placed"] for p in matched),
        "versions_with_a_placement": sum(1 for p in matched if p["placed"]),
        "pages_with_a_placement": len({(p["key"], p["page"]) for p in placed_all}),
        "not_placed_after_matching": dict(reasons),
        "number_lines_not_candidates": dict(Counter(r["reason"] for r in rows if not r.get("candidate"))),
        "plan": {"candidates": 873, "number_lines": 1520, "versions": 43, "note": "prototype candidates; the plan has no placed count"},
        "child_seconds": {"median": statistics.median(seconds) if seconds else None, "max": max(seconds) if seconds else None, "n": len(seconds)},
        "marker_comparison": {"candidates_with_a_marker_equation_of_that_number": len(with_marker),
                              "agree": sum(r["marker_agrees"] for r in with_marker),
                              "placed_with_marker": sum(1 for r in with_marker if r["placed"]),
                              "placed_agree": sum(1 for r in with_marker if r["placed"] and r["marker_agrees"])},
    }
    (args.out / "report.json").write_text(json.dumps({"summary": summary, "papers": papers, "per_paper": per_paper}, indent=1, default=list))
    (args.out / "rows.json").write_text(json.dumps(rows, indent=1))
    (args.out / "placed.json").write_text(json.dumps(placed_all, indent=1))
    print(json.dumps(summary, indent=1, default=list))


if __name__ == "__main__":
    main()

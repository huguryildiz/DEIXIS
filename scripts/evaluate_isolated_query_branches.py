"""Post-run exact-identity diagnostics for a frozen isolated query-branch comparison."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import isolated_hybrid_search as previous


def title_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def arm_index(rows: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    dois: dict[str, set[str]] = {}
    titles: dict[str, set[str]] = {}
    for row in rows:
        route = row["route"]
        if row.get("doi"):
            dois.setdefault(row["doi"], set()).add(route)
        if row.get("title"):
            titles.setdefault(title_key(row["title"]), set()).add(route)
    return dois, titles


def evaluate(args: argparse.Namespace) -> None:
    previous.empty_output(args.output_dir)
    ledger = json.loads((args.run_dir / "run-ledger.json").read_text())
    if ledger.get("status") != "completed" or len(ledger.get("calls") or []) != 20:
        raise ValueError("comparison is not a complete 20-call run")
    records = {arm: json.loads((args.run_dir / f"{arm}-records.json").read_text())
               for arm in ("a_frozen", "b_hybrid")}
    indexes = {arm: arm_index(rows) for arm, rows in records.items()}
    controls = json.loads(args.prior_comparison.read_text())["known_controls"]
    with args.elicit_csv.open(newline="", encoding="utf-8-sig") as handle:
        elicit = list(csv.DictReader(handle))
    if len(controls) != 6 or len(elicit) != 9:
        raise ValueError("comparison reference counts changed")
    control_rows = []
    for source in controls:
        doi = source["doi"].lower()
        routes = {arm: sorted(indexes[arm][0].get(doi, set())) for arm in indexes}
        control_rows.append({"title": source["title"], "doi": doi, "routes": routes})
    elicit_rows = []
    for source in elicit:
        doi = previous.normalize_doi(source["DOI"])
        title = source["Title"]
        routes = {arm: sorted(indexes[arm][0].get(doi, set()) if doi else
                              indexes[arm][1].get(title_key(title), set())) for arm in indexes}
        elicit_rows.append({"title": title, "doi": doi, "match_basis": "exact_doi" if doi else "exact_title_only",
                            "routes": routes})
    result = {
        "status": "posthoc_development_case_identity_comparison",
        "input_sha256": {
            "run_ledger": previous.sha((args.run_dir / "run-ledger.json").read_bytes()),
            "a_records": previous.sha((args.run_dir / "a_frozen-records.json").read_bytes()),
            "b_records": previous.sha((args.run_dir / "b_hybrid-records.json").read_bytes()),
            "known_controls_source": previous.sha(args.prior_comparison.read_bytes()),
            "elicit_included_csv": previous.sha(args.elicit_csv.read_bytes()),
        },
        "controls": control_rows, "elicit_included": elicit_rows,
        "summaries": {arm: {
            "known_control_exact_doi": sum(bool(row["routes"][arm]) for row in control_rows),
            "elicit_exact_doi": sum(bool(row["routes"][arm]) for row in elicit_rows if row["doi"]),
            "elicit_exact_title_without_doi": sum(bool(row["routes"][arm]) for row in elicit_rows if not row["doi"]),
        } for arm in indexes},
        "human_screened": 0, "included_studies": None,
        "limitations": ["The six controls and Elicit rows informed development; these are descriptive overlaps, not recall.",
                        "Elicit's included list is not its complete candidate pool or an equal-budget comparator.",
                        "Exact DOI and title matching do not determine scientific relevance or version equivalence.",
                        "No human relevance or full-text eligibility decisions were made."],
    }
    previous.write_json(args.output_dir / "result.json", result)
    lines = ["# Post-run control and Elicit identity comparison", "",
             "This comparison was made after the 20-call discovery ledger was frozen. The question and known misses are development cases, so the counts are not independent recall or include/exclude decisions.", "",
             "| Arm | Six control DOIs | Elicit exact DOI (of 8) | Elicit DOI-less exact title (of 1) |",
             "|---|---:|---:|---:|"]
    for arm, summary in result["summaries"].items():
        lines.append(f"| {arm} | {summary['known_control_exact_doi']}/6 | "
                     f"{summary['elicit_exact_doi']}/8 | {summary['elicit_exact_title_without_doi']}/1 |")
    lines += ["", "## Six known controls", "",
              "| DOI | Frozen queries | Hybrid queries |", "|---|---|---|"]
    for row in control_rows:
        lines.append(f"| `{row['doi']}` | {', '.join(row['routes']['a_frozen']) or '—'} | "
                     f"{', '.join(row['routes']['b_hybrid']) or '—'} |")
    lines += ["", "See `result.json` for the nine Elicit rows and all route identities. "
              "Neither arm screened or included any study."]
    (args.output_dir / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "summaries": result["summaries"],
                      "output": str(args.output_dir / "result.md")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prior-comparison", type=Path, required=True)
    parser.add_argument("--elicit-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    evaluate(parser.parse_args())


if __name__ == "__main__":
    main()

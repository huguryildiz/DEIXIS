"""P4 measurement kit for one research (implementation plan §10).

  snapshot  automated link checks, live DOI identity check, optional known-source coverage, human review sheet
  reopen    after a backend restart: the answer, selections and passage links are compared with the snapshot
  score     reads the ticked review sheet and reports the human judgements
  cells     one evidence table: fill steps, cell states and a review sheet (sampled values, every not-found and number/equation cell)
  cells-score  reads the ticked cell sheet

Automated checks, the live identity check and the human review are reported separately. Nothing here decides
whether a passage semantically supports a claim; only the person filling review.md does.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import httpx

CROSSREF = "https://api.crossref.org/works/"
VERSION_NAMES = {"publishedVersion": "published version", "acceptedVersion": "accepted manuscript", "submittedVersion": "submitted manuscript"}
VERDICTS = ["Supports the claim", "Partly supports the claim", "Does not support the claim (wrong citation)"]
RELEVANCE = ["Relevant to the question", "Not relevant to the question"]


def norm(text: str | None) -> str:
    # Crossref titles can contain HTML/XML markup, including encoded inline-formula tags.
    plain = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\W+", " ", plain.casefold()).strip()


def similar(a: str | None, b: str | None) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def latest_answer(view: dict[str, Any]) -> dict[str, Any]:
    answer = next((a for a in view["answers"] if a["status"] == "structurally_valid"), None)
    if answer is None:
        sys.exit("The research has no structurally valid answer to measure.")
    return answer


def check_links(api: httpx.Client, rid: str, view: dict[str, Any], answer: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assets = {a["id"]: (s, a) for s in view["sources"] for a in s["access"]["assets"]}
    rows, passages = [], {}
    for claim in answer["claims"]:
        for e in claim["evidence"]:
            response = api.get(f"/api/researches/{rid}/passages/{e['passage_id']}")
            p = response.json() if response.status_code == 200 else None
            passages[e["passage_id"]] = p
            row = {"claim": claim["label"], "passage_id": e["passage_id"], "opens": p is not None}
            if p:
                abstract = p["kind"] == "abstract"
                row["same_source_version"] = p["source"]["id"] == e["source_version_id"] and p["source"]["version_label"] == e["version_label"]
                row["locator_consistent"] = (p["physical_page"] is None and p["reading_depth"] == "abstract") if abstract else (
                    p["physical_page"] is not None and p["asset_id"] is not None and p["reading_depth"] == "selected_sections")
                if not abstract and p["asset_id"] in assets:
                    asset = api.get(f"/api/researches/{rid}/assets/{p['asset_id']}")
                    pages = assets[p["asset_id"]][1]["page_count"] or 0
                    row["pdf_opens_and_has_page"] = asset.status_code == 200 and asset.content.startswith(b"%PDF-") and p["physical_page"] <= pages
            rows.append(row)
    return rows, passages


def identity(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mailto = os.environ.get("DEIXIS_CONTACT_EMAIL")
    agent = f"DEIXIS-p4-eval/0.1 (mailto:{mailto})" if mailto else "DEIXIS-p4-eval/0.1"
    results = []
    with httpx.Client(timeout=20, headers={"User-Agent": agent}) as web:
        for s in sources:
            if not s["doi"]:
                results.append({"source_version_id": s["source_version_id"], "title": s["title"], "status": "no_doi"})
                continue
            try:
                response = web.get(CROSSREF + s["doi"])
            except httpx.HTTPError as exc:
                results.append({"source_version_id": s["source_version_id"], "doi": s["doi"], "status": "unavailable", "error": type(exc).__name__})
                continue
            if response.status_code != 200:
                results.append({"source_version_id": s["source_version_id"], "doi": s["doi"], "status": f"http_{response.status_code}"})
                continue
            item = response.json()["message"]
            title = (item.get("title") or [""])[0]
            year = next((part[0][0] for key in ("published-print", "published-online", "issued") if (part := (item.get(key) or {}).get("date-parts"))), None)
            ratio = similar(title, s["title"])
            results.append({"source_version_id": s["source_version_id"], "doi": s["doi"], "title": s["title"], "crossref_title": title,
                            "title_similarity": round(ratio, 3), "year": s["year"], "crossref_year": year,
                            "status": "match" if ratio >= 0.9 else "title_mismatch"})
    return results


def coverage(known_file: Path, view: dict[str, Any], answer: dict[str, Any]) -> list[dict[str, Any]]:
    """A `# stratum: name` line assigns the entries below it to a stratum, so different retrieval targets are counted apart.

    `doi | alias` on one line lists DOIs that name the same work; any of them matches.
    """
    given = set((answer.get("inputs_given") or {}).get("source_ids", []))
    cited = {e["source_version_id"] for c in answer["claims"] for e in c["evidence"]}
    rows, stratum = [], "all"
    for line in known_file.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if marker := re.match(r"#\s*stratum:\s*(\S+)", entry):
            stratum = marker.group(1)
        if not entry or entry.startswith("#"):
            continue
        dois = {part.strip().lower().removeprefix("https://doi.org/") for part in entry.split("|")} \
            if re.match(r"(https://doi\.org/)?10\.\d{4,9}/", entry, re.I) else set()
        matches = [s for s in view["sources"] if (dois and (s["doi"] or "").lower() in dois) or (not dois and similar(entry, s["title"]) >= 0.9)]
        ids = {s["source_version_id"] for s in matches}
        rows.append({"known": entry, "stratum": stratum, "found": bool(matches),
                     "included": any(s["selection"]["state"] == "included" for s in matches),
                     "given_to_model": bool(ids & given), "cited": bool(ids & cited),
                     "pdf_origins": sorted({a["origin"] for s in matches for a in s["access"]["assets"]}),
                     "exclusion_reasons": [s["selection"]["user_reason"] or s["selection"]["proposal_reason"] for s in matches if s["selection"]["state"] == "excluded"]})
    return rows


STAGES = ("found", "included", "given_to_model", "cited")


def by_stratum(known: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    strata: dict[str, dict[str, int]] = {}
    for row in known:
        counts = strata.setdefault(row["stratum"], {"total": 0, **{stage: 0 for stage in STAGES}})
        counts["total"] += 1
        for stage in STAGES:
            counts[stage] += row[stage]
    return strata


def review_sheet(view: dict[str, Any], answer: dict[str, Any], passages: dict[str, Any], known: list[dict[str, Any]] | None) -> str:
    lines = [f"# P4 review · {view['scope']['question']}", "",
             f"Research `{view['research']['id']}` · answer `{answer['id']}` ({answer['status'].replace('_', ' ')}) · model {(answer['model'] or {}).get('resolved_model')} · "
             f"{view['counts']['cited']} cited works of {view['counts']['included']} included.",
             "", "Tick one box with `[x]`. Judge each passage only by the text shown and, where needed, the original page.", "",
             "## 1. Identity, version and passage of one real source (link check)", "",
             "Open one PDF-backed citation in DEIXIS, then the DOI and the PDF page.", "",
             "- [ ] The publication identity is correct", "- [ ] The version label is correct", "- [ ] The passage text matches the PDF page", "",
             "## 2. Claims", ""]
    for n, claim in enumerate(answer["claims"], start=1):
        lines += [f"### {claim['label']} · {claim['support_type'].replace('_', ' ')}", "", f"> {claim['text']}", ""]
        for e in claim["evidence"]:
            p = passages.get(e["passage_id"])
            where = "abstract" if e["kind"] == "abstract" else f"PDF p. {e['physical_page']}"
            lines += [f"Evidence: {e['title']} ({VERSION_NAMES.get(e['version_label'], e['version_label'])}) — {where}", ""]
            lines += [f"> {(p['text'] if p else 'PASSAGE DID NOT OPEN')[:1500].replace(chr(10), ' ')}", ""]
        lines += [f"- [ ] {v}" for v in VERDICTS]
        lines += ["- [ ] Reading depth is wrong (the claim needs more than these passages can show)", "", "Note:", ""]
    lines += ["## 3. Missed evidence", ""]
    if known is None:
        lines += ["List the sources you know should answer this question in `known-sources.txt` (one DOI or title per line),",
                  "then run `measure.py snapshot` again with `--known`.", ""]
    else:
        for row in known:
            state = "cited" if row["cited"] else "given to the model, not cited" if row["given_to_model"] else "included, not given" if row["included"] \
                else "found, not included" if row["found"] else "not found by the search"
            lines += [f"- [{row['stratum']}] {row['known']} — {state}"]
        lines += [""]
    lines += ["## 4. Correction time", "", "Minutes spent correcting the selection or answer in DEIXIS: ", ""]
    lines += ["## 5. Included sources", "", "Does each included source bear on the question? This gives the included precision.", ""]
    for s in (s for s in view["sources"] if s["selection"]["state"] == "included" and s["version_role"] == "record"):
        lines += [f"#### {s['source_version_id']} · {s['title']} ({s['year']})", "", f"- [ ] {RELEVANCE[0]}", f"- [ ] {RELEVANCE[1]}", ""]
    return "\n".join(lines)


def snapshot(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base, timeout=60) as api:
        view = api.get(f"/api/researches/{args.research}").json()
        answer = next((a for a in view["answers"] if a["id"] == args.answer), None) if args.answer else \
            next((a for a in view["answers"] if a["status"] == "structurally_valid"), None)
        if answer is None and view["answers"]:
            # No citable answer (e.g. an unverified draft): search and selection coverage is still measured; nothing counts as cited.
            answer = {**view["answers"][0], "claims": []}
        if answer is None:
            sys.exit("The research has no answer to measure.")
        links, passages = check_links(api, args.research, view, answer)
    cited_ids = {e["source_version_id"] for c in answer["claims"] for e in c["evidence"]}
    ids = identity([s for s in view["sources"] if s["source_version_id"] in cited_ids])
    known = coverage(Path(args.known), view, answer) if args.known else None
    checks = [v for row in links for k, v in row.items() if k not in ("claim", "passage_id")]
    automated = {
        "research_id": args.research, "answer_id": answer["id"], "answer_status": answer["status"], "model": answer["model"], "claims": len(answer["claims"]),
        "evidence_links": len(links), "link_checks_passed": sum(checks), "link_checks_total": len(checks), "links": links,
        "evidence_by_kind": {kind: sum(passages[r["passage_id"]]["kind"] == kind for r in links if r["opens"]) for kind in ("abstract", "pdf_page")},
        "identity_live_crossref": ids, "known_source_coverage": known,
        "known_by_stratum": by_stratum(known) if known else None,
        "research_counts": view["counts"],
        "queries": [{"query_text": r["query_text"], "result_count": r["result_count"], "provider_total": r["provider_total"],
                     "origin": r.get("query_origin", "model")} for r in view["search_runs"]],
        "run_usage": [{"kind": r["kind"], "status": r["status"], **(r.get("usage") or {})} for r in view["runs"]],
    }
    (out / "snapshot.json").write_text(json.dumps({"view": view, "passages": passages}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "automated.json").write_text(json.dumps(automated, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "review.md").write_text(review_sheet(view, answer, passages, known), encoding="utf-8")
    checked = [i for i in ids if i["status"] in ("match", "title_mismatch")]
    matched = sum(i["status"] == "match" for i in checked)
    print(f"links {automated['link_checks_passed']}/{automated['link_checks_total']} checks passed · identity {matched}/{len(checked)} checked DOI titles match Crossref"
          + (f" ({len(ids) - len(checked)} not checked)" if len(ids) > len(checked) else "")
          + (f" · known sources cited {sum(k['cited'] for k in known)}/{len(known)}" if known else ""))
    for name, c in (automated["known_by_stratum"] or {}).items():
        print(f"  {name}: found {c['found']}, included {c['included']}, given {c['given_to_model']}, cited {c['cited']} of {c['total']}")


def reopen(args: argparse.Namespace) -> None:
    out = Path(args.out)
    before = json.loads((out / "snapshot.json").read_text(encoding="utf-8"))["view"]
    with httpx.Client(base_url=args.base, timeout=60) as api:
        after = api.get(f"/api/researches/{args.research}").json()
        a0, a1 = latest_answer(before), latest_answer(after)
        passage_ids = [e["passage_id"] for c in a1["claims"] for e in c["evidence"]]
        opened = sum(api.get(f"/api/researches/{args.research}/passages/{pid}").status_code == 200 for pid in passage_ids)
    selection = lambda v: {s["source_version_id"]: (s["selection"]["state"], s["selection"]["origin"], s["selection"]["user_reason"]) for s in v["sources"]}
    result = {"question_same": before["scope"]["question"] == after["scope"]["question"], "answer_same": a0["claims"] == a1["claims"],
              "selections_same": selection(before) == selection(after), "passages_opened": opened, "passages_total": len(passage_ids)}
    result["reopen_success"] = all(v for k, v in result.items() if k.endswith("_same")) and opened == len(passage_ids)
    (out / "reopen.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


def score(args: argparse.Namespace) -> None:
    text = (Path(args.out) / "review.md").read_text(encoding="utf-8")
    ticked = lambda block, label: re.search(rf"- \[[xX]\] {re.escape(label)}", block) is not None
    sections = re.split(r"^### ", text, flags=re.M)[1:]
    claims = []
    for block in sections:
        verdict = next((v for v in VERDICTS if ticked(block, v)), None)
        claims.append({"claim": block.split(" ", 1)[0], "verdict": verdict, "reading_depth_wrong": ticked(block, "Reading depth is wrong")})
    minutes = re.search(r"Minutes spent correcting the selection or answer in DEIXIS: *([\d.]+)", text)
    result = {
        "identity_checked": {label: ticked(text, label) for label in ("The publication identity is correct", "The version label is correct", "The passage text matches the PDF page")},
        "claims_reviewed": sum(c["verdict"] is not None for c in claims), "claims_total": len(claims),
        "wrong_citations": sum(c["verdict"] == VERDICTS[2] for c in claims), "partial": sum(c["verdict"] == VERDICTS[1] for c in claims),
        "reading_depth_wrong": sum(c["reading_depth_wrong"] for c in claims),
        "correction_minutes": float(minutes.group(1)) if minutes else None, "claims": claims,
    }
    relevance = text.split("## 5. Included sources", 1)[1] if "## 5. Included sources" in text else ""
    sources = re.split(r"^#### ", relevance, flags=re.M)[1:]
    relevant = sum(ticked(block, RELEVANCE[0]) for block in sources)
    judged = relevant + sum(ticked(block, RELEVANCE[1]) for block in sources)
    result["included_judged"], result["included_total"] = judged, len(sources)
    result["included_precision"] = round(relevant / judged, 3) if judged else None
    (Path(args.out) / "human.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "claims"}))


def compare(args: argparse.Namespace) -> None:
    """One row per measured run: research counts, known sources per stratum and stage, and human precision when scored."""
    strata = []
    rows = []
    for out in map(Path, args.outs):
        automated = json.loads((out / "automated.json").read_text(encoding="utf-8"))
        human = json.loads((out / "human.json").read_text(encoding="utf-8")) if (out / "human.json").exists() else {}
        known = automated.get("known_by_stratum") or {}
        strata += [s for s in known if s not in strata]
        rows.append((out.name, automated.get("research_counts") or {}, known, human.get("included_precision"),
                     sum(u.get("model_calls", 0) for u in automated.get("run_usage") or [])))
    stages = "/".join(("found", "incl", "given", "cited"))
    print("run | unique | included | cited | " + " | ".join(f"{s} {stages}" for s in strata) + " | precision | model calls")
    for name, counts, known, precision, calls in rows:
        cells = [" ".join(f"{known[s][k]}" for k in STAGES) + f" of {known[s]['total']}" if s in known else "-" for s in strata]
        print(f"{name} | {counts.get('unique', '-')} | {counts.get('included', '-')} | {counts.get('cited', '-')} | "
              + " | ".join(cells) + f" | {precision if precision is not None else 'not scored'} | {calls}")


CELL_VERDICTS = ["Doğru", "Kısmen doğru", "Yanlış"]
ABSENCE = ["Yayında gerçekten yok", "Yayında var (kaçırılmış)"]
EXACT = ["Sayfayla karakter karakter uyuşuyor", "Sayfayla uyuşmuyor"]


def is_exact_column(column: dict[str, Any]) -> bool:
    """Number and equation cells are checked against the page character by character (M7)."""
    return column["answer_format"] == "number_unit" or "denklem" in column["name"].casefold()


def cell_summary(table: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    steps = [s for r in runs for s in r["steps"] if s["kind"] == "model:cell_extraction"]
    valid = [c["current"] for c in table["cells"] if c["current"] and c["current"]["output_status"] == "structurally_valid"]
    count = lambda items: {k: sum(i == k for i in items) for k in dict.fromkeys(items)}
    return {"rows": len(table["rows"]), "columns": len(table["columns"]),
            "fill_steps": {"succeeded": sum(s["status"] == "succeeded" for s in steps), "total": len(steps)},
            "valid_cells": count([c["state"] for c in valid]),
            "unverified_proposals": sum(c["pending_proposal"] is not None and c["current"] is None for c in table["cells"]),
            "valid_values_by_depth": count([c["reading_depth"] for c in valid if c["state"] == "value"]),
            "evidence_anchor_match": count([e["anchor_match"] for c in valid for e in c["evidence"]])}


def cell_sheet(table: dict[str, Any], sample: int, seed: int) -> str:
    columns = {c["id"]: c for c in table["columns"]}
    titles = {r["source_version_id"]: r["title"] for r in table["rows"]}
    valid = [c for c in table["cells"] if c["current"] and c["current"]["output_status"] == "structurally_valid"]
    values = [c for c in valid if c["current"]["state"] == "value" and not is_exact_column(columns[c["column_id"]])]
    exact = [c for c in valid if c["current"]["state"] == "value" and is_exact_column(columns[c["column_id"]])]
    absent = [c for c in valid if c["current"]["state"] == "not_found_in_inspected_scope"]
    picked = random.Random(seed).sample(values, min(sample, len(values)))

    def block(prefix: str, n: int, cell: dict[str, Any], choices: list[str]) -> list[str]:
        cur = cell["current"]
        lines = [f"### {prefix}{n} · {columns[cell['column_id']]['name']} · {titles.get(cell['source_version_id'], cell['source_version_id'])}", "",
                 f"`{cell['source_version_id']}` · {cur['reading_depth']} · değer: {json.dumps(cur['value'], ensure_ascii=False)}"
                 + (f" · not: {cur['note']}" if cur.get("note") else ""), ""]
        for e in cur["evidence"]:
            where = "özet" if e["kind"] == "abstract" else f"PDF s. {e['physical_page']}"
            lines += [f"> ({where}, {e['anchor_match']}) {e['anchor_text']}", ""]
        return lines + [f"- [ ] {v}" for v in choices] + ["", "Not:", ""]

    lines = [f"# Hücre incelemesi · tablo `{table['table']['id']}`", "",
             f"Rastgele {len(picked)} değer hücresi (tohum {seed}, toplam {len(values)}), bütün `not_found` ({len(absent)}) ve sayı/denklem ({len(exact)}) hücreleri.", "",
             f"## Değer hücreleri (M5) · toplam {len(values)}", ""]
    for n, cell in enumerate(picked, 1):
        lines += block("V", n, cell, CELL_VERDICTS)
    lines += [f"## İncelenen kapsamda bulunamadı (M5, S4) · toplam {len(absent)}", ""]
    for n, cell in enumerate(absent, 1):
        lines += block("N", n, cell, ABSENCE)
    lines += [f"## Sayı ve denklem hücreleri (M7) · toplam {len(exact)}", ""]
    for n, cell in enumerate(exact, 1):
        lines += block("E", n, cell, CELL_VERDICTS + EXACT)
    return "\n".join(lines)


def score_cells(sheet: Path) -> dict[str, Any]:
    text = sheet.read_text(encoding="utf-8")
    ticked = lambda block, label: re.search(rf"- \[[xX]\] {re.escape(label)}(\n|$)", block) is not None
    blocks = {p: [b for b in re.split(r"^### ", text, flags=re.M)[1:] if b.startswith(p)] for p in "VNE"}
    verdicts = lambda bs: {"judged": sum(any(ticked(b, v) for v in CELL_VERDICTS) for b in bs), "total": len(bs),
                           "correct": sum(ticked(b, CELL_VERDICTS[0]) for b in bs), "partial": sum(ticked(b, CELL_VERDICTS[1]) for b in bs),
                           "wrong": sum(ticked(b, CELL_VERDICTS[2]) for b in bs)}
    result = {"values": verdicts(blocks["V"]),
              "not_found": {"judged": sum(any(ticked(b, v) for v in ABSENCE) for b in blocks["N"]), "total": len(blocks["N"]),
                            "truly_absent": sum(ticked(b, ABSENCE[0]) for b in blocks["N"]), "present": sum(ticked(b, ABSENCE[1]) for b in blocks["N"])},
              "exact": {**verdicts(blocks["E"]), "match_page": sum(ticked(b, EXACT[0]) for b in blocks["E"]),
                        "mismatch_page": sum(ticked(b, EXACT[1]) for b in blocks["E"])}}
    return result


def cells(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base, timeout=60) as api:
        table = api.get(f"/api/researches/{args.research}/tables/{args.table}").json()
        view = api.get(f"/api/researches/{args.research}").json()
    runs = [r for r in view["runs"] if r["kind"] == "table_fill" and (r.get("target") or {}).get("table_id") == args.table]
    summary = cell_summary(table, runs)
    (out / "table.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "cells-automated.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "cells.md").write_text(cell_sheet(table, args.sample, args.seed), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def cells_score(args: argparse.Namespace) -> None:
    result = score_cells(Path(args.out) / "cells.md")
    (Path(args.out) / "cells-human.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "reopen", "score"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--out", required=True)
        if name != "score":
            cmd.add_argument("--research", required=True)
            cmd.add_argument("--base", default="http://127.0.0.1:8765")
        if name == "snapshot":
            cmd.add_argument("--known", help="Text file with one DOI (`doi | alias` for several) or title per line; `# stratum: name` lines group the entries below")
            cmd.add_argument("--answer", help="Answer id to measure; default: the newest structurally valid answer")
    cmd = sub.add_parser("cells")
    cmd.add_argument("--out", required=True)
    cmd.add_argument("--research", required=True)
    cmd.add_argument("--table", required=True)
    cmd.add_argument("--base", default="http://127.0.0.1:8765")
    cmd.add_argument("--sample", type=int, default=20)
    cmd.add_argument("--seed", type=int, default=20260917)
    cmd = sub.add_parser("cells-score")
    cmd.add_argument("--out", required=True)
    cmd = sub.add_parser("compare")
    cmd.add_argument("outs", nargs="+", help="Output directories of measured runs")
    args = parser.parse_args()
    {"snapshot": snapshot, "reopen": reopen, "score": score, "compare": compare, "cells": cells, "cells-score": cells_score}[args.command](args)


if __name__ == "__main__":
    main()

"""Read-only P6 slice 2 L9 measurement kit (development lines).

`snapshot` reads a finished `lineage_links` run (it refuses a run that is not completed with a succeeded publication, or
while a session is left `started`; `--stopped <reason>` records structure and usage of a stopped run and marks R12 to R15 not
measurable): the stored plan, sessions and step inputs from a SQLite copy opened mode=ro, and the links and unplaced works from `GET .../lineage`. It writes `snapshot.json` (structural counts, the
state of every pair of the frozen chain G, R14 and R15), `reader.md` (R12/R13 sample and mention-form items) and
`key.json` (the sample selection, hidden from the reader). `score` reads the reader's `reader.json` and writes
`results.json` with R12, R13 and the mention-form counts. `rows` lists the table rows the frozen selection rule picks and
`independence` intersects them with a reference library by DOI and OpenAlex id; both only read. No command starts a run or calls a model, and none judges a
value against the frozen expectations; that comparison is made by hand in the results document.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import re
import sqlite3
from typing import Any
import unicodedata

import httpx

SUPPORT = ("supports", "partial", "not_supports")
MENTION = ("body", "reference_list", "unclear")
SAMPLE_CAP = 20
DEV_RELATIONS = ("extends", "relaxes_assumption", "changes_method", "new_domain_or_condition", "corrects_or_contradicts")
UNREAD = "okunamadı: "


def metric(value: Any = None, denominator: Any = None, status: str = "measured", reason: str | None = None,
           **extra: Any) -> dict[str, Any]:
    if denominator == 0 and status == "measured":
        status, reason, value = "not_measurable", "zero_denominator", None
    return {"value": value, "denominator": denominator, "status": status, "reason": reason, **extra}


def title_tokens(text: str | None) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()
    return tuple(re.findall(r"[^\W_]+", folded))


def _db(path: Path, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(query, args)]


def fetch_view(base: str, research: str, table: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with httpx.Client(base_url=base, timeout=60) as client:
        out = []
        for path in (f"/api/researches/{research}/tables/{table}/lineage", f"/api/researches/{research}/tables/{table}"):
            response = client.get(path)
            response.raise_for_status()
            out.append(response.json())
    return out[0], out[1]


def g_nodes(g: dict[str, Any], view: dict[str, Any], authors: dict[str, list[str]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Live rows whose normalized title STARTS with the frozen run, whose year is a frozen one and whose first author
    carries the frozen surname. A title match that fails identity is reported apart and never counts (fail closed)."""
    live = {sid: n for sid, n in view["nodes"].items() if n.get("live")}
    found: dict[str, list[str]] = {}
    rejected: dict[str, list[str]] = {}
    for w in g["works"]:
        run = title_tokens(w["match"])
        hits = [sid for sid, n in sorted(live.items()) if title_tokens(n["title"])[:len(run)] == run]
        ok = [sid for sid in hits if live[sid].get("year") in w["years"]
              and w["first_author"].casefold() in title_tokens(" ".join((authors.get(sid) or [])[:1]))]
        found[w["key"]], rejected[w["key"]] = ok, [sid for sid in hits if sid not in ok]
    return found, rejected


def active_links(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Current accepted development and cross links (stale and out-of-scope history is not active)."""
    return [link for c in view["components"] for link in c["links"]] + list(view["cross_relations"])


def g_status(a: list[str], b: list[str], keys: tuple[str, str], view: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if not a or not b:
        return {"status": "not_in_table", "missing": [k for k, nodes in zip(keys, (a, b)) if not nodes]}
    A, B = set(a), set(b)
    dev = [l for c in view["components"] for l in c["links"]]
    if any(l["from"] in A and l["to"] in B and l["author"] == "model" and l["relation"] in DEV_RELATIONS for l in dev):
        return {"status": "won"}
    if any(l["from"] in A and l["to"] in B and l["author"] != "model" for l in dev):
        return {"status": "human_only"}
    if any(l["from"] in B and l["to"] in A for l in dev):
        return {"status": "reverse_link"}
    if any(l["from"] in A | B and l["to"] in A | B for l in view["cross_relations"]):
        return {"status": "independent_parallel_only"}
    rejected = [r for r in view["not_accepted"] if r["from"] in A and r["to"] in B]
    if rejected:
        return {"status": "rejected", "codes": sorted({r["rejection_code"] for r in rejected})}
    decisions = [d for d in view["pair_decisions"] if d["from"] in A and d["to"] in B and d["decision"]]
    for kind in ("no_relation", "insufficient_evidence"):
        if any(d["decision"] == kind for d in decisions):
            return {"status": kind}
    if any(o["from"] in A and o["to"] in B for o in view["not_sent_budget"]):
        return {"status": "not_sent_budget"}
    if any(o["from"] in A and o["to"] in B for o in view["failed_pairs"]):
        return {"status": "step_failed"}
    if any(c["from"] in A for s in plan.get("selected", []) if s["to"] in B for c in s["candidates"]):
        return {"status": "candidate_unassessed"}
    present = any(e["from"] in A and e["to"] in B for e in view["unassessed_edges"])
    return {"status": "no_candidate", "edge": "present" if present else "not_present_or_unknown"}


def r14(g: dict[str, Any], view: dict[str, Any], plan: dict[str, Any], authors: dict[str, list[str]]) -> dict[str, Any]:
    nodes, rejected = g_nodes(g, view, authors)
    pairs = {}
    for a, b in g["pairs"]:
        status = g_status(nodes[a], nodes[b], (a, b), view, plan)
        if status["status"] == "not_in_table":
            status["identity_unverified"] = [k for k in (a, b) if not nodes[k] and rejected[k]]
        pairs[f"{a}->{b}"] = status
    won = sum(p["status"] == "won" for p in pairs.values())
    value = metric(won, len(pairs)) if pairs else metric(status="not_measurable", reason="empty_G")
    return value | {"pairs": pairs, "g_nodes": nodes, "identity_rejected": rejected}


def r15(view: dict[str, Any]) -> dict[str, Any]:
    eligible = [u for u in view["unplaceable"] if view["nodes"][u["source_version_id"]].get("eligible")]
    reasons = Counter(reason for u in eligible for reason in u["reasons"])
    return metric(len(eligible), view["status"]["pdf_text_rows"], reasons=dict(sorted(reasons.items())))


REPAIR_MARKER = "A previous output for this StepInput failed validation with these issues."


def usage_numbers(usage: Any) -> dict[str, float] | None:
    """One session's recorded totals: the nested `total` object when there is one (never added to `last`), else flat numbers."""
    if not isinstance(usage, dict) or not usage:
        return None
    flat = usage["total"] if isinstance(usage.get("total"), dict) else usage
    return {k: v for k, v in flat.items() if isinstance(v, (int, float)) and not isinstance(v, bool)} or None


def sessions(db: Path | None, run_id: str) -> dict[str, Any]:
    if db is None:
        return {"read": UNREAD + "no_db"}
    rows = _db(db, "SELECT step_input_id, status, started_at, finished_at, token_usage_json FROM model_sessions WHERE run_id = ?", (run_id,))
    tokens: Counter[str] = Counter()
    without_usage = 0
    for r in rows:
        try:
            numbers = usage_numbers(json.loads(r["token_usage_json"])) if r["token_usage_json"] else None
        except ValueError:
            numbers = None
        if numbers is None:
            without_usage += 1
            continue
        tokens.update(numbers)
    starts = [r["started_at"] for r in rows if r["started_at"]]
    ends = [r["finished_at"] for r in rows if r["finished_at"]]
    run = _db(db, "SELECT status, pause_reason, error_json, usage_json, created_at, updated_at FROM runs WHERE id = ?", (run_id,))
    backed = {r["step_input_id"] for r in rows}
    inputs = _db(db, "SELECT id, user_message FROM step_inputs WHERE run_id = ?", (run_id,))
    return {"sessions": len(rows), "by_status": dict(Counter(r["status"] for r in rows)),
            "started_left_open": sum(r["status"] == "started" for r in rows), "tokens": dict(tokens),
            "sessions_without_recorded_usage": without_usage, "first_start": min(starts, default=None),
            "last_finish": max(ends, default=None), "run": run[0] if run else None,
            "inputs_prepared": len(inputs), "inputs_with_a_session": len(backed),
            "repair_inputs": sum(REPAIR_MARKER in (i["user_message"] or "") for i in inputs)}


def audit(db: Path, research: str | None, run_id: str) -> dict[str, Any]:
    """Counters that stay zero when nobody intervened; the current-link counter of the view is not enough for that."""
    rid = research or _db(db, "SELECT research_id FROM runs WHERE id = ?", (run_id,))[0]["research_id"]
    return {"human_link_revisions": _db(db, "SELECT count(*) AS n FROM lineage_link_revisions WHERE author = 'human'")[0]["n"],
            "human_cell_revisions": _db(db, "SELECT count(*) AS n FROM cell_revisions WHERE kind IN ('human_edit', 'accept_proposal', 'dismiss_proposal')")[0]["n"],
            "scope_revisions": _db(db, "SELECT max(revision) AS n FROM scope_revisions WHERE research_id = ?", (rid,))[0]["n"],
            "non_terminal_runs": _db(db, "SELECT count(*) AS n FROM runs WHERE status NOT IN ('completed', 'failed', 'cancelled')")[0]["n"]}


STOPPED_OK = ("paused", "failed", "cancelled", "completed")


def verify_run(db: Path, run_id: str, research: str | None, table: str | None, stopped: bool = False) -> list[str]:
    """Reasons a run cannot be measured; empty when it can. A stopped run may be paused, failed or cancelled but must be drained."""
    run = _db(db, "SELECT research_id, kind, status, target_json FROM runs WHERE id = ?", (run_id,))
    if not run:
        return ["run_not_found"]
    run = run[0]
    problems = []
    if run["kind"] != "lineage_links":
        problems.append("not_a_lineage_run")
    if research and run["research_id"] != research:
        problems.append("run_belongs_to_another_research")
    if table and (json.loads(run["target_json"] or "{}").get("table_id") != table):
        problems.append("run_belongs_to_another_table")
    if stopped:
        if run["status"] not in STOPPED_OK:
            problems.append(f"run_not_drained_{run['status']}")
    else:
        if run["status"] != "completed":
            problems.append(f"run_status_{run['status']}")
        publication = _db(db, "SELECT status FROM run_steps WHERE run_id = ? AND operation_key = 'lineage_publication'", (run_id,))
        if not publication or publication[0]["status"] != "succeeded":
            problems.append("publication_not_succeeded")
    if _db(db, "SELECT count(*) AS n FROM model_sessions WHERE status = 'started'")[0]["n"]:
        problems.append("started_session_left_open")
    if _db(db, "SELECT count(*) AS n FROM runs WHERE status IN ('queued', 'running', 'pause_requested')")[0]["n"]:
        problems.append("executing_run_present")
    if _db(db, "SELECT count(*) AS n FROM runs WHERE status NOT IN ('completed', 'failed', 'cancelled') AND id != ?", (run_id,))[0]["n"]:
        problems.append("other_nonterminal_run_present")
    return problems


def intervention_problems(checks: dict[str, Any]) -> list[str]:
    return [name for name, bad in (("human_link_revisions", checks["human_link_revisions"]), ("human_cell_revisions", checks["human_cell_revisions"]),
                                   ("scope_revised", (checks["scope_revisions"] or 1) != 1)) if bad]


def accepted_input(db: Path, revision_id: str) -> dict[str, Any] | None:
    """The stored input of the very call whose result the accepted revision records."""
    rows = _db(db, "SELECT i.payload_json FROM lineage_link_revisions r JOIN step_inputs i ON i.id = r.step_input_id WHERE r.id = ?", (revision_id,))
    return json.loads(rows[0]["payload_json"]) if rows else None


def structure(plan: dict[str, Any], view: dict[str, Any], used: dict[str, Any], sent: dict[tuple[str, str], Any],
              checks: dict[str, Any] | None = None) -> dict[str, Any]:
    cands = [c for s in plan.get("selected", []) for c in s["candidates"]]
    decided = [d for d in view["pair_decisions"] if d["decision"] and d["author"] == "model"]
    return {"candidates_found": len(cands), "candidate_edge_states": dict(Counter(c["edge_state"] for c in cands)),
            "candidate_basis": dict(Counter(b for c in cands for b in c["basis"])),
            "candidates_planned_in_chunks": sum(len(c["from"]) for c in plan.get("chunks", [])),
            "candidates_sent": len(sent),
            "chunks": len(plan.get("chunks", [])), "max_model_calls": plan.get("max_model_calls"),
            "targets_selected": len(plan.get("selected", [])), "no_candidate_targets": len(plan.get("no_candidate", [])),
            "decided": len(decided), "decision_types": dict(Counter(d["decision"] for d in decided)),
            "rejected_codes": dict(Counter(r["rejection_code"] for r in view["not_accepted"])),
            "not_sent_budget": len(view["not_sent_budget"]), "failed_pairs": len(view["failed_pairs"]),
            "development_links": sum(len(c["links"]) for c in view["components"]), "cross_relations": len(view["cross_relations"]),
            "human_edited_links_current": view["counts"]["human_edited_links"], "unassessed_edges": len(view["unassessed_edges"]),
            "table_status": view["status"], "usage": used, "intervention_audit": checks}


def _payloads(db: Path, run_id: str, completed_only: bool = False) -> list[dict[str, Any]]:
    """Inputs that own a model session (a prepared input that was never sent is not 'sent'), oldest first."""
    status = " AND m.status = 'completed'" if completed_only else ""
    rows = _db(db, "SELECT i.payload_json FROM step_inputs i WHERE i.run_id = ? AND i.task_type = 'lineage_links'"
                   f" AND EXISTS (SELECT 1 FROM model_sessions m WHERE m.step_input_id = i.id{status}) ORDER BY i.created_at, i.rowid", (run_id,))
    return [json.loads(r["payload_json"]) for r in rows]


def _cells(node: dict[str, Any]) -> list[str]:
    return [f"{c['role']}: {c['value'] if c['state'] == 'value' else '(' + c['state'] + ')'}"
            + "".join(f"\n    - quote: {q}" for q in c.get("evidence_quotes") or []) for c in node["cells"]]


def collect_sent(payloads: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """(from, to) -> the LATEST given input's two nodes, the mention passage ids and the shown passages."""
    sent: dict[tuple[str, str], dict[str, Any]] = {}
    for p in payloads:
        target = p["lineage_target"]
        shown = {x["passage_id"]: x for x in p["passages"]}
        for cand in target["candidates"]:
            key = (cand["from"]["source_id"], target["to"]["source_id"])
            sent[key] = ({"to": target["to"], "from": cand["from"], "mention_passage_ids": cand["mention_passage_ids"],
                                  "passages": shown, "sources": {s["source_id"]: s for s in p["sources"]}})
    return sent


def choose_sample(links: list[dict[str, Any]], seed: int) -> list[str]:
    ids = sorted(l["link_id"] for l in links)
    return sorted(random.Random(seed).sample(ids, SAMPLE_CAP)) if len(ids) > SAMPLE_CAP else ids


def build_sheet(view: dict[str, Any], sent: dict[tuple[str, str], dict[str, Any]], sample: list[str],
                inputs: dict[str, dict[str, Any] | None]) -> tuple[str, dict[str, Any]]:
    links = {l["link_id"]: l for l in active_links(view) if l["author"] == "model"}
    lines = ["# Reader sheet (L9)", "",
             "Answer in `reader.json`: `{\"links\": {\"L01\": {\"support\": \"supports|partial|not_supports\", \"chronology_only\": true|false}}, "
             "\"mentions\": {\"M01\": \"body|reference_list|unclear\"}}`. Every id below needs an answer.", "",
             "## Part 1: development links", "",
             "For each link: does the quoted text, read with the passage, support the stated relation between these two works? "
             "`supports`, `partial` or `not_supports`. `chronology_only` is true when the only basis is that one work is later or "
             "mentions the other, and the relation itself is not in the passage text.", ""]
    key: dict[str, Any] = {"links": {}, "mentions": {}, "material_missing": []}
    for i, lid in enumerate(sample, 1):
        link, item = links[lid], f"L{i:02d}"
        key["links"][item] = lid
        info = (inputs.get(lid) or {}).get((link["from"], link["to"]))
        passages = (info or {}).get("passages", {})
        if not info or not link["evidence"] or any(ev["passage_id"] not in passages for ev in link["evidence"]):
            key["material_missing"].append(item)
        frm, to = view["nodes"][link["from"]], view["nodes"][link["to"]]
        lines += [f"### {item}", f"Earlier work: {frm['title']} ({frm['year']})", f"Later work: {to['title']} ({to['year']})",
                  f"Model decision: relation={link['relation']}; support_type={link['support_type']}; what_changed={link['what_changed']}; note={link['note']}", ""]
        for ev in link["evidence"]:
            lines += [f"Quoted (anchor): {ev['anchor_text']}", ""]
            passage = passages.get(ev["passage_id"])
            lines += [f"Passage the quote is from (page {ev.get('physical_page')}):", "", passage["text"] if passage else UNREAD + "passage_not_in_stored_input", ""]
        if info:
            lines += ["Later work, stored node cells:", *[f"- {c}" for c in _cells(info["to"])], "",
                      "Earlier work, stored node cells:", *[f"- {c}" for c in _cells(info["from"])], ""]
        else:
            lines += [UNREAD + "no_stored_input_for_the_accepted_revision", ""]
    lines += ["## Part 2: how the earlier work is mentioned", "",
              "For each passage below and each listed earlier work: is the mention in running text (`body`), in a bibliography entry "
              "(`reference_list`), or `unclear`?", ""]
    n = 0
    by_passage: dict[str, dict[str, Any]] = {}
    for (frm, to), info in sorted(sent.items()):
        for pid in info["mention_passage_ids"]:
            entry = by_passage.setdefault(pid, {"text": info["passages"][pid]["text"], "cited": []})
            entry["cited"].append((frm, to))
    for pid, entry in sorted(by_passage.items()):
        lines += [f"### Passage {pid}", "", entry["text"], ""]
        for frm, to in entry["cited"]:
            n += 1
            item = f"M{n:02d}"
            key["mentions"][item] = {"passage_id": pid, "from": frm, "to": to}
            node = view["nodes"].get(frm) or {}
            lines.append(f"- {item}: earlier work \"{node.get('title')}\" ({node.get('year')})")
        lines.append("")
    return "\n".join(lines) + "\n", key


def norm_doi(value: str | None) -> str | None:
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", (value or "").strip().casefold())
    return doi or None


DOI_SCHEMES = ("doi", "published_doi", "linked_doi")


def _canonical(scheme: str, value: str) -> tuple[str, str]:
    """One namespace per identity: every DOI-like scheme is a DOI; OpenAlex ids lose their URL; arXiv ids lose the version."""
    if scheme in DOI_SCHEMES:
        return "doi", norm_doi(value) or ""
    value = value.strip()
    if scheme == "openalex":
        return "openalex", value.rsplit("/", 1)[-1].upper()
    if scheme == "arxiv":
        return "arxiv", re.sub(r"v[0-9]+$", "", re.sub(r"^(https?://arxiv\.org/abs/|arxiv:)", "", value.casefold()))
    return scheme, value.casefold()


def identifiers(db: Path, svids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """source version -> title and every identifier (DOI field and all identifier_mappings schemes) of ANY version of its work."""
    versions = _db(db, "SELECT id, work_id, title, doi FROM source_versions")
    by_version: dict[str, set[str]] = {v["id"]: ({f"doi:{norm_doi(v['doi'])}"} if norm_doi(v["doi"]) else set()) for v in versions}
    for r in _db(db, "SELECT source_version_id, scheme, value FROM identifier_mappings"):
        scheme, value = _canonical(r["scheme"], r["value"])
        if r["source_version_id"] in by_version and value:
            by_version[r["source_version_id"]].add(f"{scheme}:{value}")
    by_work: dict[str, set[str]] = {}
    for v in versions:
        by_work.setdefault(v["work_id"], set()).update(by_version[v["id"]])
    return {v["id"]: {"title": v["title"], "ids": by_work[v["work_id"]]} for v in versions if svids is None or v["id"] in svids}


def independence(new: dict[str, dict[str, Any]], reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    owners: dict[str, list[str]] = {}
    for info in reference.values():
        for i in info["ids"]:
            owners.setdefault(i, []).append(info["title"])
    rows = {sid: {"title": info["title"], "no_identifier": not info["ids"],
                  "matches": sorted({t for i in info["ids"] for t in owners.get(i, [])})} for sid, info in new.items()}
    return {"sources": rows, "overlapping": sorted(sid for sid, r in rows.items() if r["matches"]),
            "unverified": sorted(sid for sid, r in rows.items() if r["no_identifier"])}


def cmd_independence(args: argparse.Namespace) -> None:
    # Every included work is checked, before the PDF-text filter and the row limit.
    rows = [r["source_version_id"] for r in json.loads(Path(args.rows).read_text())["included_works"]]
    result = independence(identifiers(Path(args.db), rows), identifiers(Path(args.reference)))
    print(json.dumps(result, indent=2, ensure_ascii=False))


def selected_rows(db: Path, research: str, limit: int = 15) -> dict[str, Any]:
    from deixis.workflow.store import Store
    with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        store = Store(conn)
        heads = store.included_works(research)
        listed = [{"source_version_id": s, "title": store.source(s)["title"], "year": store.source(s)["year"],
                   "pdf_text": store.has_pdf_text(s)} for s in heads]
    kept = [r for r in listed if r["pdf_text"]][:limit]
    return {"included_works": listed, "rows": [r["source_version_id"] for r in kept],
            "left_out_without_pdf_text": [r["title"] for r in listed if not r["pdf_text"]],
            "left_out_beyond_limit": [r["title"] for r in [r for r in listed if r["pdf_text"]][limit:]]}


def cmd_rows(args: argparse.Namespace) -> None:
    print(json.dumps(selected_rows(Path(args.db), args.research, args.limit), indent=2, ensure_ascii=False))


def cmd_snapshot(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Path(args.db)
    if args.view_file:
        view, table = json.loads(Path(args.view_file).read_text()), {}
    else:
        view, table = fetch_view(args.base, args.research, args.table)
    g = json.loads(Path(args.g).read_text())
    problems = verify_run(db, args.run, args.research, args.table, stopped=bool(args.stopped))
    checks = audit(db, args.research, args.run)
    if not args.stopped and checks["non_terminal_runs"]:
        problems.append("non_terminal_run_present")
    if problems:
        raise SystemExit("run cannot be measured (use --stopped <reason> for a drained stopped run): " + ", ".join(problems))
    if intervention_problems(checks):
        raise SystemExit("intervention counters are not zero, the measurement is invalid and is recorded as such: "
                         + ", ".join(intervention_problems(checks)))
    plan = json.loads(_db(db, "SELECT target_json FROM runs WHERE id = ?", (args.run,))[0]["target_json"])
    used = sessions(db, args.run)
    sent = collect_sent(_payloads(db, args.run))
    struct = structure(plan, view, used, sent, checks)
    if args.stopped:
        gone = metric(status="not_measurable", reason="run_incomplete")
        result = {"stopped": args.stopped, "R12": gone, "R13": gone, "R14": gone, "R15": gone, "structure": struct}
        (out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"wrote {out / 'results.json'} (stopped: {args.stopped}; only structure and usage)")
        return
    authors = {r["id"]: json.loads(r["authors_json"]) for r in _db(db, "SELECT id, authors_json FROM source_versions")}
    links = [l for l in active_links(view) if l["author"] == "model"]
    sample = choose_sample(links, args.seed)
    lookup = {l["link_id"]: l for l in links}
    inputs = {lid: (collect_sent([payload]) if (payload := accepted_input(db, lookup[lid]["revision_id"])) else None) for lid in sample}
    sheet, key = build_sheet(view, sent, sample, inputs)
    snap = {"run_id": args.run, "seed": args.seed, "structure": struct, "R14": r14(g, view, plan, authors),
            "R15": r15(view), "links_active_model": len(links), "sample_size": len(sample), "table_title": (table.get("table") or {}).get("title")}
    (out / "snapshot.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    (out / "reader.md").write_text(sheet)
    (out / "key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False))
    print(f"wrote {out}: sample {len(sample)} of {len(links)} links, {len(key['mentions'])} mention items")


def load_reading(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise SystemExit("reading has a duplicate key, no result")
        return dict(pairs)
    return json.loads(path.read_text(), object_pairs_hook=no_duplicates)


def unread_result(snapshot: dict[str, Any], reason: str) -> dict[str, Any]:
    gone = metric(status="not_measurable", reason=reason)
    return {"R12": gone, "R13": gone, "mention_form": {"status": "not_measurable", "reason": reason},
            "R14": snapshot["R14"], "R15": snapshot["R15"], "structure": snapshot["structure"]}


def score(snapshot: dict[str, Any], key: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    if set(answers) != {"links", "mentions"} or not isinstance(answers["links"], dict) or not isinstance(answers["mentions"], dict):
        raise SystemExit("reading must be exactly {\"links\": {...}, \"mentions\": {...}}, no result")
    links, mentions = answers["links"], answers["mentions"]
    problems = [f"missing link {i}" for i in key["links"] if i not in links] + [f"missing mention {i}" for i in key["mentions"] if i not in mentions]
    problems += [f"unexpected link {i}" for i in links if i not in key["links"]] + [f"unexpected mention {i}" for i in mentions if i not in key["mentions"]]
    problems += [f"bad answer for {i}" for i, a in links.items()
                 if not isinstance(a, dict) or set(a) != {"support", "chronology_only"} or a["support"] not in SUPPORT
                 or not isinstance(a["chronology_only"], bool)]
    problems += [f"bad mention class for {i}" for i, a in mentions.items() if a not in MENTION]
    if problems:
        raise SystemExit("incomplete or invalid reading, no result: " + "; ".join(problems[:20]))
    n = len(key["links"])
    if key.get("material_missing"):
        raise SystemExit("reading material was unavailable for " + ", ".join(key["material_missing"])
                         + ": no semantic score; use `score --unread material_unavailable`")
    sup = Counter(links[i]["support"] for i in key["links"])
    chron = sum(links[i]["chronology_only"] for i in key["links"])
    pair_classes: dict[tuple[str, str], list[str]] = {}
    for item, meta in key["mentions"].items():
        pair_classes.setdefault((meta["from"], meta["to"]), []).append(mentions[item])
    kinds = Counter("body" if "body" in c else "reference_list_only" if all(x == "reference_list" for x in c) else "unclear"
                    for c in pair_classes.values())
    return {"R12": metric(sup["supports"], n, partial=sup["partial"], not_supports=sup["not_supports"],
                          sample="all" if n == snapshot["links_active_model"] else f"seed {snapshot['seed']}", reader="model"),
            "R13": metric(chron, n, reader="model"),
            "mention_form": {"pairs_sent": len(pair_classes), "body_present": kinds["body"],
                             "reference_list_only": kinds["reference_list_only"], "unclear": kinds["unclear"],
                             "passage_items": dict(Counter(mentions[i] for i in key["mentions"])),
                             "scope": "passages sent to the model only; found-but-unsent mentions are not classified"},
            "R14": snapshot["R14"], "R15": snapshot["R15"], "structure": snapshot["structure"]}


def cmd_score(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if args.unread:
        result = unread_result(json.loads((out / "snapshot.json").read_text()), args.unread)
        (out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"wrote {out / 'results.json'} (R12, R13 and mention form not measurable: {args.unread})")
        return
    result = score(json.loads((out / "snapshot.json").read_text()), json.loads((out / "key.json").read_text()),
                   load_reading(out / "reader.json"))
    (out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"wrote {out / 'results.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--research")
    snap.add_argument("--table")
    snap.add_argument("--run", required=True, help="the lineage_links run id")
    snap.add_argument("--base", default="http://127.0.0.1:8867")
    snap.add_argument("--db", required=True, help="SQLite copy of the run's library, opened mode=ro")
    snap.add_argument("--g", required=True, help="p6-slice2-chain.json")
    snap.add_argument("--seed", type=int, default=20261001)
    snap.add_argument("--stopped", metavar="REASON", help="the run stopped: write structure and usage only, R12 to R15 not measurable")
    snap.add_argument("--view-file", help="saved GET .../lineage JSON (offline use and tests)")
    snap.add_argument("--out", required=True)
    snap.set_defaults(func=cmd_snapshot)
    rows = sub.add_parser("rows")
    rows.add_argument("--db", required=True)
    rows.add_argument("--research", required=True)
    rows.add_argument("--limit", type=int, default=15)
    rows.set_defaults(func=cmd_rows)
    ind = sub.add_parser("independence")
    ind.add_argument("--db", required=True, help="the run's library")
    ind.add_argument("--rows", required=True, help="JSON from `rows`")
    ind.add_argument("--reference", required=True, help="read-only backup of the owner's library")
    ind.set_defaults(func=cmd_independence)
    sc = sub.add_parser("score")
    sc.add_argument("--out", required=True)
    sc.add_argument("--unread", metavar="REASON", help="no reading was completed: keep R14 and R15, mark R12, R13 and the mention form not measurable")
    sc.set_defaults(func=cmd_score)
    args = parser.parse_args()
    if args.cmd == "snapshot" and not args.view_file and not (args.research and args.table):
        parser.error("snapshot needs --research and --table, or --view-file")
    args.func(args)


if __name__ == "__main__":
    main()

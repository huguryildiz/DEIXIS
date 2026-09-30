"""Read-only P6 report measurement kit.

`snapshot` reads a report through GET and optionally a SQLite copy opened mode=ro.
`second` prepares a blind second sheet; `score` records readings without judging
them against the frozen expectations. No command starts a run or calls a model.

Proposed R10 input until P15 is inspected: a JSON list, or an object with a
`cases` list. Entries with an `id` beginning `RS` are faults. Optional fields
are `task`, `seeded_fault`, `review_caught`, and `assembly_caught`; the two catch
fields must be JSON booleans or null. Each ratio uses its own readable subset.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import difflib
import hashlib
import html
import json
from pathlib import Path
import random
import re
import sqlite3
from typing import Any
from urllib.parse import quote

import httpx
from deixis.domain.contracts import locate_anchor
from deixis.domain.phrasebank import sentences

R2_CHOICES = ("Supports the claim", "Partly supports the claim", "Does not support the claim (wrong citation)")
R3_CHOICES = ("Follows the rule", "Does not follow the rule")
R4_CHOICES = ("Same strength as the body", "Stronger than the body")
R6_CHOICES = ("Matches the page (equivalent LaTeX is a match)", "Does not match the page")
R9_CHOICES = ("Present with all given parts", "Present, parts missing", "Absent")
CHOICES = {"R2": R2_CHOICES, "R3": R3_CHOICES, "R4b": R4_CHOICES, "R6": R6_CHOICES, "R9": R9_CHOICES}
NEGATIVE_LEXICON = re.compile(
    r"\b(?:not found|not reported|did not|no stud(?:y|ies)|none of|absent|"
    r"yok|bildirmedi|incelenmedi|ele almadı|bulunamadı|"
    r"not_found_in_inspected_scope|insufficient_evidence)\b", re.IGNORECASE,
)
MODEL_SECTIONS = ("III", "IV", "V", "VI", "VII", "VIII", "I", "IX", "abstract", "index_terms")
METRICS = tuple(f"R{i}" for i in range(1, 12))


def metric(value: Any = None, denominator: Any = None, status: str = "measured", reason: str | None = None,
           **extra: Any) -> dict[str, Any]:
    if denominator == 0 and status == "measured":
        status, reason = "not_measurable", "zero_denominator"
        value = None
    return {"value": value, "denominator": denominator, "status": status, "reason": reason, **extra}


def unreadable(reason: str) -> dict[str, Any]:
    return metric(status="not_readable", reason=reason)


def unmeasurable(reason: str) -> dict[str, Any]:
    return metric(status="not_measurable", reason=reason)


def _get(api: httpx.Client, path: str) -> Any:
    response = api.get(path)
    response.raise_for_status()
    return response.json()


def _json_file(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _db_rows(path: Path, query: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    # URI mode=ro is enforced by SQLite, including for an operator's original path.
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, args)]


def db_evidence(path: Path | None, report_id: str, run_id: str) -> dict[str, Any] | None:
    if path is None:
        return None
    sessions = _db_rows(path, "SELECT m.step_id, m.step_input_id, m.status, m.started_at, m.rowid AS session_rowid, "
                       "m.resolved_model, m.token_usage_json, m.validation_json, "
                       "i.attempt, i.task_type, i.payload_json, i.user_message, i.created_at AS input_created_at, "
                       "i.rowid AS input_rowid FROM model_sessions m "
                       "JOIN step_inputs i ON i.id = m.step_input_id WHERE m.run_id = ? ORDER BY m.started_at, m.rowid",
                       (run_id,))
    inputs = _db_rows(path, "SELECT i.id, i.step_id, i.attempt, i.task_type, i.payload_json, i.user_message, "
                      "i.created_at, i.rowid AS input_rowid, s.operation_key "
                      "FROM step_inputs i JOIN run_steps s ON s.id = i.step_id "
                      "WHERE i.run_id = ? ORDER BY i.created_at, i.rowid", (run_id,))
    repairs = _db_rows(path, "SELECT section_id, sentence_id, before, after, outcome, created_at, rowid "
                       "FROM report_phrase_repairs WHERE report_id = ? ORDER BY created_at, rowid", (report_id,))
    frozen = _db_rows(path, "SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,))
    return {"sessions": sessions, "inputs": inputs, "phrase_repairs": repairs,
            "frozen_snapshot": json.loads(frozen[0]["snapshot_json"]) if frozen else None}


def _sections(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["section_id"]: s for s in report.get("sections", [])}


def _claims(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(s["section_id"], c) for s in report.get("sections", []) for c in s.get("claims", [])]


def _draft_claim(section: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any] | None:
    return next((c for c in (section.get("draft") or {}).get("claims", [])
                 if c.get("claim_key") == claim.get("claim_key")), None)


def _quote(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:1500]


def _stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds(start: str | None, end: str | None) -> float | None:
    a, b = _stamp(start), _stamp(end)
    return round((b - a).total_seconds(), 3) if a and b else None


def _sequential_model_chain(steps: list[dict[str, Any]]) -> dict[str, Any]:
    rounds = (("report_plan",), ("research_title",), ("III", "IV", "V"), ("VI",),
              ("VII",), ("VIII",), ("I", "IX", "abstract", "index_terms"), ("report_review",))
    spans = []
    for group in rounds:
        keys = ({"report_plan", "research_title", "report_review"} & set(group)) or {
            f"report_section:{sid}" for sid in group} | {f"report_phrase_repair:{sid}" for sid in group}
        matching = [s for s in steps if s["operation_key"] in keys and s.get("started_at") and s.get("finished_at")]
        if matching:
            seconds = _seconds(min(s["started_at"] for s in matching), max(s["finished_at"] for s in matching))
            spans.append({"round": list(group), "seconds": seconds, "steps": [s["operation_key"] for s in matching]})
    return {"seconds": round(sum(s["seconds"] for s in spans if s["seconds"] is not None), 3),
            "rounds": spans, "method": "sum_of_observed_round_spans", "partial": len(spans) < 7}


def _link_checks(api: httpx.Client, research_id: str, report: dict[str, Any],
                 db: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cells = {c["cell_id"]: c for c in (report.get("table_i") or {}).get("cells", [])}
    frozen = {c["cell_id"]: c for c in ((db or {}).get("frozen_snapshot") or {}).get("cells", [])}
    passages: dict[str, Any] = {}
    links = []
    for section_id, claim in _claims(report):
        for n, link in enumerate(claim.get("evidence", []), 1):
            pid = link.get("open_passage_id") or link.get("passage_id")
            if pid and pid not in passages:
                response = api.get(f"/api/researches/{research_id}/passages/{pid}")
                passages[pid] = response.json() if response.status_code == 200 else None
            passage = passages.get(pid)
            cell = cells.get(link.get("cell_id"))
            source_ok = (passage["source"]["id"] == link["source_version_id"] if passage else None)
            if link.get("cell_id") and passage:
                source_ok = (source_ok is True and cell is not None
                             and cell["source_version_id"] == link["source_version_id"])
            passage_depth = ("abstract" if passage["kind"] == "abstract" else "selected_sections") if passage else None
            frozen_cell = frozen.get(link.get("cell_id"))
            cell_depth = frozen_cell.get("reading_depth") if frozen_cell else None
            depth = cell_depth if link.get("cell_id") else passage_depth
            quote = next((e.get("quote") for e in (frozen_cell or {}).get("evidence", [])
                          if e.get("passage_id") == pid and e.get("quote")), None)
            source_text = quote or (passage or {}).get("text")
            anchor_located = bool(link.get("anchor_match") and link.get("anchor_text") and source_text and
                                  locate_anchor(link["anchor_text"], source_text))
            row = {"section_id": section_id, "claim_id": claim["id"], "link_number": n,
                   "passage_id": link.get("passage_id"), "cell_id": link.get("cell_id"),
                   "open_passage_id": pid, "opens": passage is not None if pid else False,
                   "same_source_version": source_ok, "anchor_located": anchor_located,
                   "reading_depth": depth, "depth_status": "measured" if depth else "not_readable",
                   "depth_reason": "frozen_cell_depth_not_in_api" if link.get("cell_id") and not cell_depth else None,
                   "depth_from": "frozen_cell.reading_depth" if cell_depth else
                   "opened_passage.kind" if passage_depth and not link.get("cell_id") else None,
                   "opened_passage_depth": passage_depth,
                   "cell_reading_depth": cell_depth,
                   "quote": quote or (passage.get("text") if passage else link.get("anchor_text"))}
            links.append(row)
    return links, passages


def _sample_claims(links: list[dict[str, Any]], report: dict[str, Any], sample: int, seed: int) -> list[str]:
    depth = defaultdict(set)
    for row in links:
        depth[row["claim_id"]].add(row["reading_depth"] or "not_readable")
    candidates = sorted(((section_id, claim) for section_id, claim in _claims(report) if claim.get("evidence")),
                        key=lambda item: (item[0], item[1]["id"]))
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for section_id, claim in candidates:
        for d in sorted(depth[claim["id"]]):
            groups[(section_id, claim.get("support_type") or "unknown", d)].append(claim["id"])
    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)
    keys = sorted(groups)
    rng.shuffle(keys)
    picked: list[str] = []
    while len(picked) < sample and keys:
        remaining = []
        for key in keys:
            while groups[key] and groups[key][0] in picked:
                groups[key].pop(0)
            if groups[key] and len(picked) < sample:
                picked.append(groups[key].pop(0))
            if groups[key]:
                remaining.append(key)
        keys = remaining
    if sample >= len(candidates):
        return [claim["id"] for _, claim in candidates]
    return picked


def _negative_units(report: dict[str, Any]) -> list[dict[str, Any]]:
    units = []
    for section in report.get("sections", []):
        sid = section["section_id"]
        for claim in section.get("claims", []):
            for sentence in re.split(r"(?<=[.!?])\s+", (claim.get("text") or "").strip()):
                if NEGATIVE_LEXICON.search(sentence):
                    units.append({"id": f"N{len(units)+1}", "section": sid, "claim_id": claim["id"],
                                  "text": sentence, "cells": [e["cell_id"] for e in claim["evidence"] if e.get("cell_id")]})
        for entry in (section.get("draft") or {}).get("insufficient_evidence", []):
            units.append({"id": f"N{len(units)+1}", "section": sid, "claim_id": None,
                          "text": entry.get("reason", ""), "cells": entry.get("cell_ids", [])})
    return units


def _has_equation(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key.lower() in ("equation", "latex", "formula") and bool(item)
                   or _has_equation(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_equation(item) for item in value)
    return isinstance(value, str) and ("\\begin{equation}" in value or "$$" in value)


def _tokens(db: dict[str, Any] | None) -> dict[str, Any]:
    if db is None:
        return unreadable("db_not_supplied")
    groups: dict[str, Counter] = defaultdict(Counter)
    repair_inputs = {row["id"] for row in db["inputs"] if _is_repair_input(row)}
    seen_inputs: set[str] = set()
    for row in db["sessions"]:
        try:
            usage = json.loads(row["token_usage_json"] or "{}")
        except json.JSONDecodeError:
            usage = {}
        validation = json.loads(row["validation_json"] or "{}")
        failed = row["status"] != "completed" or validation.get("ok") is False
        resend = row["step_input_id"] in seen_inputs
        # resend_calls is an overlay: a resend is also counted in its own kind (first, repair or failed).
        group = ("failed_calls" if failed else
                 "repair_calls" if row["task_type"] == "report_phrase_repair"
                 or row["step_input_id"] in repair_inputs else "first_calls")
        for name in ((group, "resend_calls") if resend else (group,)):
            groups[name]["calls"] += 1
            for key, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    groups[name][key] += value
        seen_inputs.add(row["step_input_id"])
    return metric({key: dict(groups[key]) for key in ("first_calls", "repair_calls", "failed_calls", "resend_calls")},
                  len(db["sessions"]), overlay="resend_calls is also counted in the kind it belongs to")


REPAIR_MARKER = "A previous output for this StepInput failed validation with these issues."


def _is_repair_input(row: dict[str, Any]) -> bool:
    """A schema-repair input is recognised by the repair message the flow stores (models/prompt.py::repair_message),
    not by its place in the attempt order: a step opened again after a pause starts a normal input at attempt 0."""
    return REPAIR_MARKER in (row.get("user_message") or "")


def _first_inputs(inputs: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inputs:
        grouped[row["step_id"]].append(row)
    return {step_id: min(rows, key=lambda row: (row["attempt"], row["created_at"], row["input_rowid"]))["id"]
            for step_id, rows in grouped.items()}


def automate(report: dict[str, Any], research: dict[str, Any], run: dict[str, Any],
             links: list[dict[str, Any]], db: dict[str, Any] | None, pairs: list[dict[str, Any]] | None) -> dict[str, Any]:
    sections, claims = _sections(report), _claims(report)
    steps = run.get("steps") or []
    by_operation = {step["operation_key"]: step for step in steps}
    first_inputs = _first_inputs(db["inputs"]) if db is not None else {}
    model_sections = []
    for sid in MODEL_SECTIONS:
        step = by_operation.get(f"report_section:{sid}")
        section = sections.get(sid)
        first = unreadable("model_sessions_not_in_api") if db is None else None
        if db is not None and step:
            sessions = [s for s in db["sessions"] if s["step_id"] == step["id"]]
            phrase = [s for s in db["sessions"] if s["task_type"] == "report_phrase_repair"
                      and (json.loads(s["payload_json"] or "{}").get("report_target") or {}).get("section_id") == sid]
            first_input = first_inputs.get(step["id"])
            first_outputs = sorted((s for s in sessions if s["step_input_id"] == first_input and s["status"] == "completed"),
                                   key=lambda s: (s["started_at"], s["session_rowid"]))
            first = (bool(json.loads(first_outputs[0]["validation_json"] or "{}").get("ok")) and not phrase and
                     bool(section and section["status"] == "valid")) if first_outputs else unreadable(
                         "no_completed_model_output" if sessions else "no_model_session")
            by_input = Counter(s["step_input_id"] for s in sessions)
            schema_repairs = len({i["id"] for i in db["inputs"] if i["step_id"] == step["id"]
                                  and _is_repair_input(i)})
            resend_sessions = sum(count - 1 for count in by_input.values())
        else:
            schema_repairs = unreadable("db_not_supplied" if db is None else "section_step_missing")
            resend_sessions = unreadable("db_not_supplied" if db is None else "section_step_missing")
        model_sections.append({"section": sid, "step_status": step["status"] if step else None,
                               "section_status": section["status"] if section else None, "first_try_valid": first,
                               "schema_repair_attempts": schema_repairs, "resend_sessions": resend_sessions,
                               "reason": run.get("error") if section and section["status"] in ("draft", "failed") else None})
    written = [s for s in model_sections if s["step_status"] is not None]
    first_readable = [s for s in written if isinstance(s["first_try_valid"], bool)]
    valid = sum(s["section_status"] == "valid" for s in written)
    report_runs = research.get("reportRuns", [])
    out = {name: unmeasurable("not_scored") for name in METRICS}
    out["R1"] = metric({"sections": model_sections,
                        "first_try_valid": sum(s["first_try_valid"] for s in first_readable),
                        "first_try_readable": len(first_readable), "valid_after_repair": valid,
                        "completed": "1/1" if report.get("status") == "valid" and report.get("report_version") else "0/1",
                        "report_runs_in_research": len(report_runs), "run_error": run.get("error")},
                       len(written), status="measured" if written else "not_measurable",
                       reason=None if written else "zero_denominator")
    durations = [{"operation_key": s["operation_key"], "kind": s["kind"], "status": s["status"],
                  "started_at": s.get("started_at"), "finished_at": s.get("finished_at"),
                  "seconds": _seconds(s.get("started_at"), s.get("finished_at"))} for s in steps]
    starts = [s["started_at"] for s in steps if s.get("started_at")]
    ends = [s["finished_at"] for s in steps if s.get("finished_at")]
    first_step = min(starts) if starts else None
    last_step = max(ends) if ends else None
    begin = run.get("created_at")
    end = run.get("updated_at")
    out["R7"] = metric({"started_at": begin, "finished_at": end, "wall_seconds": _seconds(begin, end),
                        "first_step_started_at": first_step, "last_step_finished_at": last_step,
                        "pre_first_step_seconds": _seconds(begin, first_step),
                        "steps": sorted(durations, key=lambda s: s["started_at"] or ""),
                        "model_calls": (run.get("usage") or {}).get("model_calls"),
                        "tokens": _tokens(db), "sequential_chain": _sequential_model_chain(steps),
                        "queue_and_quota_wait": unreadable("wait_intervals_not_separately_recorded")},
                       len(steps), status="measured" if steps else "not_measurable",
                       reason=None if steps else "zero_denominator")
    if report.get("status") == "in_progress" or run.get("status") != "completed":
        for key in METRICS:
            if key not in ("R1", "R7"):
                out[key] = unmeasurable("run_incomplete")
        return out
    out["R2"] = metric({"links": links, "opened": sum(r["opens"] for r in links),
                        "source_version_matches": sum(r["same_source_version"] is True for r in links),
                        "anchors_located": sum(r["anchor_located"] for r in links)}, len(links))
    negatives = _negative_units(report)
    out["R3"] = metric({"finder_only": True, "sentences": negatives}, len(negatives))
    derived = [(sid, c, _draft_claim(sections[sid], c)) for sid, c in claims if sid in ("abstract", "I", "IX")]
    if any(d is None or "body_refs" not in d for _, _, d in derived):
        out["R4"] = unreadable("body_refs_not_in_draft")
    else:
        missing = [{"section": sid, "claim_id": c["id"]} for sid, c, d in derived if not d["body_refs"]]
        out["R4"] = metric({"without_body_refs": missing, "derived_claims": [
            {"section": sid, "claim_id": c["id"], "claim_key": c["claim_key"], "body_refs": d["body_refs"]}
            for sid, c, d in derived]}, len(derived))
    glossary = (report.get("plan") or {}).get("glossary", [])
    report_text = " ".join([c.get("text", "") for _, c in claims] +
                           [str((s.get("draft") or {}).get("text") or "") for s in sections.values()])
    out["R5"] = metric([{"term": g["term"], "canonical_count": len(re.findall(
        rf"(?<!\w){re.escape(g['term'])}(?!\w)", report_text, flags=re.IGNORECASE)), "other_names": None}
        for g in glossary], len(glossary))
    equations = []
    for sid, claim in claims:
        if claim.get("equation_ref"):
            draft = _draft_claim(sections[sid], claim) or {}
            equations.append({"section": sid, "claim_id": claim["id"], "equation_ref": claim["equation_ref"],
                              "equation_origin": draft.get("equation_origin"), "text": claim["text"]})
    out["R6"] = metric(equations, len(equations))
    if db is None:
        out["R8"] = unreadable("db_not_supplied")
    else:
        latest = {(r["section_id"], r["sentence_id"]): r for r in db["phrase_repairs"]
                  if r["section_id"] in ("III", "IV", "V", "VI", "VII")}
        # One text per claim or insufficient-evidence entry, as phrasing.py counts sentences per field.
        fields = {sid: [c.get("text") or "" for c in ((sections.get(sid) or {}).get("draft") or {}).get("claims", [])]
                  + [e.get("reason") or "" for e in ((sections.get(sid) or {}).get("draft") or {}).get("insufficient_evidence", [])]
                  for sid in ("III", "IV", "V", "VI", "VII")}
        final_total = sum(len(sentences(text)) for texts in fields.values() for text in texts)
        # Production numbers the sentences BEFORE repair (phrasing.py), one stored row per repaired original sentence.
        # The original count is the final count with each repaired sentence counted once: what stands in the final
        # draft for a repair is its `after` text when that text is found there, else its `before` text.
        original, unresolved = final_total, []
        for key, row in latest.items():
            after, before = (row.get("after") or ""), (row.get("before") or "")
            if after and any(after in text for text in fields[key[0]]):
                original -= len(sentences(after)) - 1
            elif before and any(before in text for text in fields[key[0]]):
                original -= len(sentences(before)) - 1
            else:
                unresolved.append({"section_id": key[0], "sentence_id": key[1]})
        if unresolved:
            out["R8"] = unreadable("repair_text_not_found_in_final_draft")
            out["R8"]["unresolved_repairs"] = unresolved
        else:
            out["R8"] = metric({"flagged": len(latest), "outcomes": dict(Counter(r["outcome"] for r in latest.values())),
                                "latest_repairs": list(latest.values()), "final_text_sentences": final_total,
                                "denominator_basis": "original_sentences_recovered_from_final_text"}, original)
    if pairs is None:
        out["R9"] = unmeasurable("no_pairs_marked")
    else:
        refs = {r.get("source_version_id"): r.get("source_key") for r in report.get("references", [])}
        refs.update({r.get("source_version_id"): r.get("source_key") for r in (report.get("table_i") or {}).get("rows", [])})
        entries = []
        for pair in pairs:
            source_ids = {sid for sid, key in refs.items() if key == pair["source_key"]}
            source_cells = [c for c in (report.get("table_i") or {}).get("cells", []) if c["source_version_id"] in source_ids]
            source_claims = [c for _, c in claims if any(e["source_version_id"] in source_ids for e in c["evidence"])]
            entries.append({**pair, "source_version_ids": sorted(source_ids),
                            "frozen_cell_equation": any(_has_equation(c.get("value")) for c in source_cells),
                            "source_claim_equation": any(c.get("equation_ref") for c in source_claims),
                            "report_equation_claims": [c["id"] for c in source_claims if c.get("equation_ref")]})
        out["R9"] = metric(entries, len(entries))
    given_by_section = {}
    if db is not None:
        for row in db["inputs"]:
            if row["task_type"] == "report_section" and row["attempt"] == 0:
                payload = json.loads(row["payload_json"])
                sid = (payload.get("report_target") or {}).get("section_id")
                given_by_section[sid] = {"cells": len((payload.get("report_target") or {}).get("cells", [])),
                                         "passages": len(payload.get("passages", []))}
    truncations = []
    for sid, section in sections.items():
        cut = (section.get("validation") or {}).get("truncated") or []
        by_kind = dict(Counter(item.get("record_kind", "unknown") for item in cut))
        given = given_by_section.get(sid)
        total = sum(given.values()) + len(cut) if given else None
        truncations.append({"section": sid, "truncated_by_kind": by_kind, "cut": len(cut),
                            "cut_records_may_repeat": True,
                            "given": given, "cut_ratio": len(cut) / total if total else None,
                            "ratio_status": "measured" if total else "not_readable" if given is None else "not_measurable",
                            "insufficient_evidence": len((section.get("draft") or {}).get("insufficient_evidence", [])),
                            "missing_passages_reader": None})
    out["R11"] = metric(truncations, len(truncations))
    return out


def _boxes(labels: tuple[str, ...]) -> list[str]:
    return [f"- [ ] {label}" for label in labels]


def _value(automated: dict[str, Any], key: str, default: Any) -> Any:
    return automated[key].get("value") if automated[key].get("value") is not None else default


def _crossref_identity(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Optional live DOI-title comparison; retrieval failure is not an identity mismatch."""
    result = []
    with httpx.Client(timeout=20, headers={"User-Agent": "DEIXIS-p6-eval/0.1"}) as external:
        for ref in references:
            doi = ref.get("doi")
            row = {"source_version_id": ref.get("source_version_id"), "doi": doi, "status": "no_doi"}
            if doi:
                try:
                    response = external.get(f"https://api.crossref.org/works/{quote(doi.removeprefix('https://doi.org/'), safe='')}")
                    response.raise_for_status()
                    titles = response.json()["message"].get("title") or []
                    title = titles[0] if titles else None
                    normalize = lambda s: re.sub(r"\W+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or "")).casefold()).strip()
                    similarity = difflib.SequenceMatcher(None, normalize(ref.get("title")), normalize(title)).ratio()
                    row |= {"status": "match" if similarity >= 0.9 else "title_mismatch",
                            "crossref_title": title, "title_similarity": round(similarity, 3)}
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    row |= {"status": "not_readable", "reason": type(exc).__name__}
            result.append(row)
    return result


def review_sheet(report: dict[str, Any], research_id: str, automated: dict[str, Any],
                 passages: dict[str, Any], seed: int, sample: int, api: httpx.Client | None = None,
                 model: str | None = None) -> str:
    links = automated["R2"].get("value", {}).get("links", []) if automated["R2"]["status"] == "measured" else []
    chosen = _sample_claims(links, report, sample, seed)
    by_claim = {(sid, c["id"]): c for sid, c in _claims(report)}
    by_key = {c["claim_key"]: c for _, c in _claims(report)}
    cells = {c["cell_id"]: c for c in (report.get("table_i") or {}).get("cells", [])}
    lines = [f"# P6 report reading · `{report['id']}`", "", f"Reader: ", "",
             f"Report `{report['id']}` · model `{model or 'not_readable'}` · seed {seed} · sampled claims {len(chosen)}/{len({r['claim_id'] for r in links})}.",
             "These are model readings unless this sheet identifies a person who read the cited material.", "",
             "Tick one box per unit. An unticked unit remains unread.", "", "## R2 · claim-record links", ""]
    for n, cid in enumerate(chosen, 1):
        matches = [r for r in links if r["claim_id"] == cid]
        for m, row in enumerate(matches, 1):
            claim = by_claim[row["section_id"], cid]
            lines += [f"### C{n}.L{m} · {row['section_id']} · claim `{cid}`", "",
                          f"Claim: {_quote(claim['text'])}", f"Support type: {claim['support_type']} · depth: {row['reading_depth'] or 'not_readable'} ({row['depth_from'] or row['depth_reason']})",
                      f"Record: passage `{row['open_passage_id']}` · cell `{row['cell_id']}`", "",
                      f"> {_quote(row['quote'])}", "", *_boxes(R2_CHOICES), ""]
    lines += ["## R3 · negative and absence sentences", "", "Finder only; add missed sentences below.", ""]
    for unit in _value(automated, "R3", {}).get("sentences", []):
        lines += [f"#### {unit['id']} · {unit['section']} · {_quote(unit['text'])} · cells: {', '.join(unit['cells'])}", "",
                  *[f"> Cell `{cid}`: {_quote((cells.get(cid) or {}).get('value'))}" for cid in unit["cells"]], "",
                  *_boxes(R3_CHOICES), ""]
    lines += ["Add missed sentences as `#### M<n> · <section> · <text> · cells: <cell ids or quoted cell text>`.",
              "A missing cell basis leaves the unit without a verdict.", "", "#### M1 · <section> · <text> · cells: <cell ids or quoted cell text>", "",
              *_boxes(R3_CHOICES), "", "## R4b · derived claim strength", ""]
    for n, entry in enumerate(_value(automated, "R4", {}).get("derived_claims", []), 1):
        claim = by_claim[entry["section"], entry["claim_id"]]
        lines += [f"### D{n} · {entry['section']} · claim `{claim['id']}`", "", f"Claim: {_quote(claim['text'])}",
                  f"Body claims: {', '.join(entry['body_refs'])}",
                  *[f"> `{key}`: {_quote(by_key[key]['text'])}" if key in by_key else f"> `{key}`: NOT FOUND"
                    for key in entry["body_refs"]], "", *_boxes(R4_CHOICES), ""]
    lines += ["## R5 · terms", ""]
    for n, term in enumerate(_value(automated, "R5", []), 1):
        lines += [f"### T{n} · {term['term']}", "", f"Canonical count: {term['canonical_count']}",
                  "Other names found: <n>", ""]
    lines += ["## R6 · equations", ""]
    for n, eq in enumerate(_value(automated, "R6", []), 1):
        origin = eq.get("equation_origin") or {}
        pid = origin.get("passage_id") if isinstance(origin, dict) else None
        passage = passages.get(pid) if pid else None
        asset, page = (passage or {}).get("asset_id"), (passage or {}).get("physical_page")
        opens = False
        if asset and page and api is not None:
            response = api.get(f"/api/researches/{research_id}/assets/{asset}")
            opens = response.status_code == 200 and response.content.startswith(b"%PDF-")
        lines += [f"### E{n} · {eq['section']} · claim `{eq['claim_id']}`", "", f"Equation: {_quote(eq['text'])}",
                  f"Origin passage: `{pid}` · physical page: {page}",
                  f"PDF page: /api/researches/{research_id}/assets/{asset}#page={page}" if opens else "Status: not_readable · page_not_openable",
                  f"> {_quote((passage or {}).get('text'))}", "", "Page examined: ", "Error kinds: "]
        if opens:
            lines += _boxes(R6_CHOICES)
        lines += [""]
    lines += ["## R9 · marked formulations", ""]
    for n, pair in enumerate(_value(automated, "R9", []), 1):
        lines += [f"### P{n} · {pair['source_key']} · {pair['formulation']}", "",
                  f"Equation claims: {', '.join(pair['report_equation_claims'])}", "", *_boxes(R9_CHOICES), ""]
    lines += ["## R11 · missing passages", ""]
    for row in _value(automated, "R11", []):
        lines += [f"### B{row['section']} · {row['section']}", "", "Missing passage count: <n>", ""]
    return "\n".join(lines)


def snapshot(api: httpx.Client, research_id: str, out: Path, report_id: str | None = None,
             db_path: Path | None = None, seed: int = 20260930, sample: int = 30,
             pairs_path: Path | None = None, crossref: bool = False) -> dict[str, Any]:
    research = _get(api, f"/api/researches/{research_id}")
    summaries = research.get("reportRuns") or []
    if not summaries:
        raise ValueError("The research has no report to measure.")
    if report_id is None:
        eligible = [r for r in summaries if r.get("report_version") or r.get("status") == "draft"]
        report_id = max(eligible or summaries, key=lambda r: (r.get("created_at") or "", r["id"]))["id"]
    report = _get(api, f"/api/researches/{research_id}/reports/{report_id}")
    run = next((r for r in research.get("runs", []) if r["id"] == report["run_id"]), None)
    if run is None:
        raise ValueError("The report run is outside the research API's ten-run window; cannot measure it without its steps.")
    db = db_evidence(db_path, report_id, run["id"])
    links, passages = _link_checks(api, research_id, report, db)
    for section in report.get("sections", []):
        for claim in section.get("claims", []):
            if not claim.get("equation_ref"):
                continue
            draft = _draft_claim(section, claim) or {}
            origin = draft.get("equation_origin") or {}
            pid = origin.get("passage_id") if isinstance(origin, dict) else None
            if pid and pid not in passages:
                response = api.get(f"/api/researches/{research_id}/passages/{pid}")
                passages[pid] = response.json() if response.status_code == 200 else None
    export_response = api.get(f"/api/researches/{research_id}/reports/{report_id}/export?format=markdown")
    export = export_response.text if export_response.status_code == 200 else None
    pairs = None
    pairs_hash = None
    if pairs_path:
        pair_bytes = pairs_path.read_bytes()
        pairs_hash = hashlib.sha256(pair_bytes).hexdigest()
        pairs = json.loads(pair_bytes)
        if not isinstance(pairs, list) or any(not isinstance(p, dict) or not isinstance(p.get("source_key"), str)
                                               or not isinstance(p.get("formulation"), str) for p in pairs):
            raise ValueError("--pairs must be a JSON list of source_key/formulation objects")
    automated = automate(report, research, run, links, db, pairs)
    automated["R10"] = unmeasurable("seeded_cases_scored_separately") if automated["R10"]["reason"] != "run_incomplete" else automated["R10"]
    out.mkdir(parents=True, exist_ok=True)
    _json_file(out / "snapshot.json", {"report": report, "research": research, "run": run,
                                        "passages": passages, "markdown_export": export,
                                        "markdown_export_status": export_response.status_code,
                                        "db_evidence": db, "seed": seed, "sample": sample,
                                        "pairs_sha256": pairs_hash,
                                        "crossref": _crossref_identity(report.get("references", [])) if crossref else None})
    _json_file(out / "automated.json", automated)
    resolved = next((s["resolved_model"] for s in (db or {}).get("sessions", [])
                     if s["task_type"] == "report_section" and s.get("resolved_model")), None)
    requested = (research.get("scope") or {}).get("requested_model")
    model = (f"{resolved} (resolved in model_sessions)" if resolved else
             f"{requested} (requested in research scope; resolved model not_readable)" if requested else None)
    (out / "review.md").write_text(review_sheet(report, research_id, automated, passages, seed, sample, api, model) + "\n", encoding="utf-8")
    return automated


def _units(sheet: str) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    section = None
    for part in re.split(r"(?=^## |^### |^#### )", sheet, flags=re.M):
        head = part.splitlines()[0] if part else ""
        if head.startswith("## R"):
            section = head.split(" ", 2)[1]
        elif section and head.startswith(("### ", "#### ")):
            match = re.match(r"^#{3,4} ([A-Z]\d+(?:\.L\d+)?)\b", head)
            if match:
                unit_id = match.group(1)
                if unit_id == "M1" and "<section>" in head:
                    continue
                result[section][unit_id] = {"header": head, "body": part,
                                            "marks": [v for v in CHOICES.get(section, ()) if
                                                      re.search(rf"- \[[xX]\] {re.escape(v)}(?:\n|$)", part)]}
    return result


def second(out: Path, seed: int | None = None) -> Path:
    sheet = (out / "review.md").read_text(encoding="utf-8")
    first = _units(sheet)
    if not any(unit["marks"] for group in first.values() for unit in group.values()):
        raise ValueError("review.md has no marked units")
    saved = json.loads((out / "snapshot.json").read_text(encoding="utf-8"))
    seed = saved["seed"] if seed is None else seed
    rng = random.Random(seed)
    negative = {"R2": R2_CHOICES[1:], "R3": R3_CHOICES[1:], "R4b": R4_CHOICES[1:],
                "R6": R6_CHOICES[1:], "R9": R9_CHOICES[1:]}
    lines = [f"# Blind second reading · seed {seed}", "", "Reader: ", ""]
    for group in ("R2", "R3", "R4b", "R6", "R9"):
        units = first.get(group, {})
        selected = [key for key, unit in units.items() if any(mark in negative[group] for mark in unit["marks"])]
        unmarked = sorted(key for key, unit in units.items() if not unit["marks"])
        selected += rng.sample(unmarked, min(5, len(unmarked)))
        lines += [f"## {group}", ""]
        for key in selected:
            lines += [re.sub(r"- \[[xX]\] ", "- [ ] ", units[key]["body"]).rstrip(), ""]
    target = out / "second.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _human_metric(first: dict[str, dict[str, Any]], second_read: dict[str, dict[str, Any]],
                  group: str, seed: int, reader: str, second_reader: str | None) -> dict[str, Any]:
    choices = CHOICES[group]
    serious = choices[2] if group == "R2" else choices[1:]
    units = []
    for uid, unit in first.items():
        a = unit["marks"][0] if len(unit["marks"]) == 1 else None
        b_marks = second_read.get(uid, {}).get("marks", [])
        b = b_marks[0] if len(b_marks) == 1 else None
        cells = unit["header"].split("cells:", 1)[1].strip() if group == "R3" and "cells:" in unit["header"] else None
        no_evidence = group == "R3" and (not cells or cells.startswith("<"))
        bad = {serious} if isinstance(serious, str) else set(serious)
        claim_match = re.search(r"claim `([^`]+)`", unit["header"]) if group == "R2" else None
        support_match = re.search(r"^Support type: ([^ ·]+)", unit["body"], flags=re.M) if group == "R2" else None
        units.append({"id": uid, "first": a, "second": b, "serious": (a in bad or b in bad) and not no_evidence,
                      "no_evidence_given": no_evidence,
                      "claim_id": claim_match.group(1) if claim_match else None,
                      "support_type": support_match.group(1) if support_match else None})
    judged = sum((u["first"] is not None or u["second"] is not None) and not u["no_evidence_given"] for u in units)
    disagreement = sum(u["first"] is not None and u["second"] is not None and u["first"] != u["second"] for u in units)
    value = {"serious": sum(u["serious"] for u in units), "judged": judged, "total": len(units),
             "disagreements": disagreement, "units": units}
    if group == "R2":
        value["wrong_claims"] = len({u["id"].split(".")[0] for u in units if u["serious"]})
        value["partial_links"] = sum(u["first"] == R2_CHOICES[1] or u["second"] == R2_CHOICES[1] for u in units)
        value["partial_claims"] = len({u["id"].split(".")[0] for u in units
                                       if u["first"] == R2_CHOICES[1] or u["second"] == R2_CHOICES[1]})
        value["wrong_source_stated_claims"] = len({u["claim_id"] for u in units
                                                   if u["serious"] and u["support_type"] == "source_stated"})
    return metric(value if judged else None, judged if judged else None,
                  status="measured" if judged else "not_measurable", reason=None if judged else "not_read",
                  sample={"kind": "drawn" if group == "R2" else "whole", "seed": seed},
                  readers=[name for name in (reader, second_reader) if name])


def _seeded(path: Path | None) -> dict[str, Any]:
    if path is None:
        return unmeasurable("no_seeded_file")
    content = json.loads(path.read_text(encoding="utf-8"))
    cases = content.get("cases") if isinstance(content, dict) else content
    if not isinstance(cases, list):
        raise ValueError("--seeded must be a list or object with a cases list")
    rs = [c for c in cases if isinstance(c, dict) and str(c.get("id", "")).startswith("RS")]
    if not rs:
        return unmeasurable("no_rs_entries")
    ratios = {}
    for key in ("review_caught", "assembly_caught"):
        readable = [c for c in rs if isinstance(c.get(key), bool)]
        caught = sum(c[key] for c in readable)
        ratios[key] = {"caught": caught, "readable": len(readable), "unscored": len(rs) - len(readable),
                       "over_all": f"{caught}/{len(rs)}", "ratio": caught / len(readable) if readable else None,
                       "partial": len(readable) < len(rs),
                       "status": "measured" if len(readable) >= 6 else "not_measurable",
                       "reason": None if len(readable) >= 6 else "fewer_than_6_readable"}
    both = [c for c in rs if isinstance(c.get("review_caught"), bool) and isinstance(c.get("assembly_caught"), bool)]
    value = {"total_rs": len(rs), "review": ratios["review_caught"], "assembly": ratios["assembly_caught"],
             "neither": {"count": sum(not c["review_caught"] and not c["assembly_caught"] for c in both),
                         "readable": len(both), "unscored": len(rs) - len(both)}}
    if ratios["review_caught"]["readable"] < 6:
        return metric(value, len(rs), "not_measurable", "fewer_than_6_readable", sample={"kind": "whole"}, readers=[])
    return metric(value, len(rs), sample={"kind": "whole"}, readers=[])


def score(out: Path, seeded: Path | None = None) -> dict[str, Any]:
    snapshot_data = json.loads((out / "snapshot.json").read_text(encoding="utf-8"))
    automated = json.loads((out / "automated.json").read_text(encoding="utf-8"))
    first_text = (out / "review.md").read_text(encoding="utf-8")
    second_path = out / "second.md"
    second_text = second_path.read_text(encoding="utf-8") if second_path.exists() else ""
    first, blind = _units(first_text), _units(second_text)
    reader = re.search(r"^Reader: *(.*)$", first_text, flags=re.M)
    other = re.search(r"^Reader: *(.*)$", second_text, flags=re.M)
    names = [x.group(1).strip() for x in (reader, other) if x and x.group(1).strip()]
    seed = snapshot_data["seed"]
    human = {g: _human_metric(first.get(g, {}), blind.get(g, {}), g, seed,
                             names[0] if names else "unspecified", names[1] if len(names) > 1 else None)
             for g in CHOICES}
    sample_counts = re.search(r"sampled claims (\d+)/(\d+)", first_text)
    if sample_counts is None:
        raise ValueError("review.md is missing the sampled claims count")
    sampled, eligible = map(int, sample_counts.groups())
    human["R2"]["sample"]["kind"] = "whole" if sampled == eligible else "drawn"
    terms = []
    for block in re.split(r"(?=^### T\d+ · )", first_text, flags=re.M)[1:]:
        match = re.search(r"^Other names found: *(\d+)\s*$", block, flags=re.M)
        terms.append(int(match.group(1)) if match else None)
    human["R5"] = metric({"other_names_by_term": terms, "total_other_names": sum(n for n in terms if n is not None)},
                         sum(n is not None for n in terms) or None,
                         "measured" if any(n is not None for n in terms) else "not_measurable",
                         None if any(n is not None for n in terms) else "not_read",
                         sample={"kind": "whole", "seed": seed}, readers=names)
    missing = []
    for block in re.split(r"(?=^### B[^\n]+)", first_text, flags=re.M)[1:]:
        m = re.search(r"^Missing passage count: *(\d+)\s*$", block, flags=re.M)
        missing.append(int(m.group(1)) if m else None)
    human["R11"] = metric({"missing_passages_by_section": missing, "total_missing": sum(n for n in missing if n is not None)},
                          sum(n is not None for n in missing) or None,
                          "measured" if any(n is not None for n in missing) else "not_measurable",
                          None if any(n is not None for n in missing) else "not_read",
                          sample={"kind": "whole", "seed": seed}, readers=names)
    human["R10"] = _seeded(seeded)
    for g in ("R1", "R7"):
        human[g] = automated[g]
    results = {}
    for key in METRICS:
        if automated[key]["reason"] == "run_incomplete":
            reading = unmeasurable("run_incomplete")
        else:
            readings = ([human["R4b"]] if key == "R4" else [human[key]] if key in human else [])
            reading = readings[0] if readings else unmeasurable("not_applicable")
        primary = automated[key] if key in ("R1", "R7") or automated[key]["reason"] == "run_incomplete" else reading
        readers = (["code"] if key in ("R1", "R7") else ["seeded_case_file"] if key == "R10" else
                   (["code"] + reading.get("readers", names)) if key in ("R4", "R11") else
                   reading.get("readers", names))
        results[key] = {"value": primary["value"], "denominator": primary["denominator"],
                        "status": primary["status"], "reason": primary["reason"],
                        "sample": reading.get("sample", {"kind": "whole", "seed": seed}),
                        "readers": readers,
                        "automated": automated[key], "reading": reading}
    _json_file(out / "human.json", human)
    _json_file(out / "results.json", results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snap = commands.add_parser("snapshot")
    snap.add_argument("--research", required=True)
    snap.add_argument("--report")
    snap.add_argument("--out", type=Path, required=True)
    snap.add_argument("--base", default="http://127.0.0.1:8866")
    snap.add_argument("--db", type=Path)
    snap.add_argument("--seed", type=int, default=20260930)
    snap.add_argument("--sample", type=int, default=30)
    snap.add_argument("--pairs", type=Path)
    snap.add_argument("--crossref", action="store_true")
    sec = commands.add_parser("second")
    sec.add_argument("--out", type=Path, required=True)
    scored = commands.add_parser("score")
    scored.add_argument("--out", type=Path, required=True)
    scored.add_argument("--seeded", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            if args.sample < 0:
                raise ValueError("--sample must be nonnegative")
            with httpx.Client(base_url=args.base, timeout=60) as api:
                snapshot(api, args.research, args.out, args.report, args.db, args.seed, args.sample, args.pairs, args.crossref)
        elif args.command == "second":
            second(args.out)
        else:
            score(args.out, args.seeded)
    except (ValueError, httpx.HTTPError, sqlite3.Error) as exc:
        parser.exit(2, f"measure_report: {exc}\n")


if __name__ == "__main__":
    main()

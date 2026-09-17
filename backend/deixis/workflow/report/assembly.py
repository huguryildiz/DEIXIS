"""Structural report assembly checks from design section 8.

Implemented here: [1] duplicate claim keys, [2] glossary order, [3] derived
body references, [4] inherited support/depth, [7] frozen corpus counts, and
[10] word budgets. Reserved for the next round: [5] count claims, [6] banned
words, [8] bibliography parity, [9] gap bases, [11] equations, [12] anchors,
[13] conflict links, and [14] phrase-frame exceptions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store


_DERIVED_SECTIONS = {"abstract", "I", "IX"}
_SUPPORT_ORDER = {"analyst_inference": 0, "source_stated": 1}
_DEPTH_ORDER = {"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}
_CORPUS_LABELS = {
    "found": ("found", "bulunan"),
    "unique": ("unique", "tekil"),
    "screened": ("screened", "taranan"),
    "included": ("included", "dahil"),
}


def _issue(rule: str, section_id: str, detail: str) -> dict[str, Any]:
    return {"rule": rule, "section_id": section_id, "detail": detail}


def _claims(store: Store, report_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in store.conn.execute(
        "SELECT c.*, s.section_id, s.ordinal AS section_ordinal FROM report_claims c"
        " JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ? ORDER BY s.ordinal, c.ordinal", (report_id,),
    )]


def _section_texts(store: Store, reports: ReportStore, report_id: str) -> list[tuple[int, str, str]]:
    claim_texts: dict[str, list[str]] = defaultdict(list)
    for claim in _claims(store, report_id):
        claim_texts[claim["section_id"]].append(claim["text"])
    result = []
    for section in reports.sections(report_id):
        draft = section["draft"] or {}
        parts = [draft["text"]] if isinstance(draft.get("text"), str) else []
        parts.extend(claim_texts[section["section_id"]])
        result.append((section["ordinal"], section["section_id"], "\n".join(parts)))
    return result


def _check_duplicate_claim_keys(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    del reports
    issues = []
    rows = store.conn.execute(
        "SELECT c.claim_key, GROUP_CONCAT(s.section_id) AS section_ids"
        " FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ? GROUP BY c.claim_key HAVING COUNT(DISTINCT s.section_id) > 1",
        (report_id,),
    )
    for row in rows:
        section_ids = row["section_ids"].split(",")
        for section_id in section_ids:
            issues.append(_issue(
                "duplicate_claim_key", section_id,
                f"ERROR: claim_key {row['claim_key']} is also used in another section ({', '.join(section_ids)}).",
            ))
    return issues


def _check_glossary_order(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    plan = reports.report(report_id)["plan"] or {}
    texts = _section_texts(store, reports, report_id)
    issues = []
    for entry in plan.get("glossary", []):
        term = str(entry.get("term") or "").strip()
        definition = str(entry.get("definition") or "").strip()
        if not term or not definition:
            continue
        definition_section = next(
            ((ordinal, section_id) for ordinal, section_id, text in texts
             if definition.casefold() in text.casefold()),
            None,
        )
        if definition_section is None:
            continue
        definition_ordinal, definition_section_id = definition_section
        for ordinal, section_id, text in texts:
            if ordinal >= definition_ordinal:
                break
            if term.casefold() in text.casefold():
                issues.append(_issue(
                    "glossary_term_before_definition_warning", section_id,
                    f"WARNING: glossary term {term!r} is used before its definition in section "
                    f"{definition_section_id}.",
                ))
    return issues


def _check_body_refs(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    del reports
    issues = []
    for claim in _claims(store, report_id):
        if claim["section_id"] not in _DERIVED_SECTIONS:
            continue
        has_ref = store.conn.execute(
            "SELECT 1 FROM report_claim_refs WHERE claim_id = ? AND ref_kind = 'body_ref' LIMIT 1",
            (claim["id"],),
        ).fetchone()
        if not has_ref:
            issues.append(_issue(
                "body_ref_missing", claim["section_id"],
                f"ERROR: derived claim {claim['claim_key']} has no body_ref.",
            ))
    return issues


def _claim_depths(store: Store, reports: ReportStore, report_id: str) -> dict[str, str]:
    cells = {cell["cell_id"]: cell for cell in reports.snapshot(report_id).get("cells", [])}
    depths: dict[str, list[str]] = defaultdict(list)
    rows = store.conn.execute(
        "SELECT l.claim_id, l.passage_id, l.cell_id, p.kind AS passage_kind"
        " FROM report_citation_links l"
        " JOIN report_claims c ON c.id = l.claim_id"
        " JOIN report_sections s ON s.id = c.report_section_id"
        " LEFT JOIN passages p ON p.id = l.passage_id WHERE s.report_id = ?",
        (report_id,),
    )
    for row in rows:
        if row["cell_id"]:
            depth = cells.get(row["cell_id"], {}).get("reading_depth")
        else:
            depth = "abstract" if row["passage_kind"] == "abstract" else "selected_sections"
        if depth in _DEPTH_ORDER:
            depths[row["claim_id"]].append(depth)
    return {claim_id: min(values, key=_DEPTH_ORDER.__getitem__) for claim_id, values in depths.items()}


def _check_derived_strength(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    claims = _claims(store, report_id)
    by_key = {claim["claim_key"]: claim for claim in claims}
    depths = _claim_depths(store, reports, report_id)
    issues = []
    for claim in claims:
        if claim["section_id"] not in _DERIVED_SECTIONS:
            continue
        ref_keys = [row["ref_value"] for row in store.conn.execute(
            "SELECT ref_value FROM report_claim_refs WHERE claim_id = ? AND ref_kind = 'body_ref'",
            (claim["id"],),
        )]
        body_claims = [by_key[key] for key in ref_keys if key in by_key]
        if not body_claims:
            continue
        weakest_support = min(body_claims, key=lambda item: _SUPPORT_ORDER[item["support_type"]])["support_type"]
        if _SUPPORT_ORDER[claim["support_type"]] > _SUPPORT_ORDER[weakest_support]:
            issues.append(_issue(
                "derived_support_too_strong", claim["section_id"],
                f"ERROR: {claim['claim_key']} uses {claim['support_type']} support, stronger than the weakest "
                f"body_ref support ({weakest_support}).",
            ))
        body_depths = [depths[body["id"]] for body in body_claims if body["id"] in depths]
        derived_depth = depths.get(claim["id"])
        if derived_depth and body_depths:
            weakest_depth = min(body_depths, key=_DEPTH_ORDER.__getitem__)
            if _DEPTH_ORDER[derived_depth] > _DEPTH_ORDER[weakest_depth]:
                issues.append(_issue(
                    "derived_depth_too_deep", claim["section_id"],
                    f"ERROR: {claim['claim_key']} has {derived_depth} depth, deeper than the weakest body_ref "
                    f"depth ({weakest_depth}).",
                ))
    return issues


def _labeled_corpus_numbers(text: str) -> dict[str, list[int]]:
    numbers: dict[str, list[int]] = defaultdict(list)
    for key, labels in _CORPUS_LABELS.items():
        alternatives = "|".join(re.escape(label) for label in labels)
        patterns = (
            rf"(?<![\w.])(\d+)\s+(?:{alternatives})\b",
            rf"\b(?:{alternatives})\s*[:=]\s*(\d+)\b",
        )
        for pattern in patterns:
            numbers[key].extend(int(match) for match in re.findall(pattern, text, flags=re.IGNORECASE))
    full_text_patterns = (
        r"\bfull[ -]text(?:\s+was)?\s+available\s+for\s+(\d+)\s*/",
        r"(?<![\w.%])(\d+)\s+(?:full[ -]text(?:[ -](?:sources?|records?))?|tam metinli(?:\s+kaynak)?)\b",
        r"\bdahil\s+kaynağın\s+(\d+)\s+tanesinde\s+tam\s+metin\b",
        r"\b(?:full[ -]text|tam\s+metin)\s*[:=]\s*(\d+)\b",
    )
    for pattern in full_text_patterns:
        numbers["full_text"].extend(int(match) for match in re.findall(pattern, text, flags=re.IGNORECASE))
    return numbers


def _check_corpus_counts(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    del store
    corpus = reports.snapshot(report_id)["corpus"]
    sections = {section["section_id"]: section for section in reports.sections(report_id)}
    issues = []
    for section_id in ("II", "VIII"):
        section = sections.get(section_id)
        if not section:
            continue
        draft = section["draft"] or {}
        text = draft.get("text") if isinstance(draft.get("text"), str) else ""
        for key, values in _labeled_corpus_numbers(text).items():
            expected = corpus[key]
            for value in values:
                if value != expected:
                    issues.append(_issue(
                        "corpus_count_mismatch", section_id,
                        f"ERROR: labeled {key} count {value} does not match frozen corpus count {expected}.",
                    ))
    return issues


def _check_word_budgets(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    del store
    plan = reports.report(report_id)["plan"] or {}
    budgets = plan.get("section_budgets", {})
    sections = reports.sections(report_id)
    issues = []
    total = 0
    for section in sections:
        word_count = section["word_count"]
        if word_count is None:
            continue
        maximum = budgets.get(section["section_id"], {}).get("max_words")
        if maximum is not None:
            total += word_count
        if maximum is not None and word_count > maximum:
            issues.append(_issue(
                "section_word_count_over_budget", section["section_id"],
                f"ERROR: stored word_count {word_count} exceeds the frozen upper budget {maximum}.",
            ))
    total_maximum = sum(
        budget["max_words"] for budget in budgets.values() if isinstance(budget.get("max_words"), int)
    )
    if total_maximum and total > total_maximum:
        issues.append(_issue(
            "report_word_count_over_budget", "report",
            f"ERROR: stored report word_count {total} exceeds the frozen upper budget {total_maximum}.",
        ))
    return issues


_CHECKS: tuple[Callable[[Store, ReportStore, str], list[dict[str, Any]]], ...] = (
    _check_duplicate_claim_keys,
    _check_glossary_order,
    _check_body_refs,
    _check_derived_strength,
    # Rules 5, 6, 8, 9, and 11-14 are intentionally added in the next round.
    _check_corpus_counts,
    _check_word_budgets,
)


def run_assembly_checks(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    """Structural checks over a finished report. Empty means the report may become valid.

    Each item is ``{"rule", "section_id", "detail"}``. Rule 2 is non-blocking
    and carries both a ``_warning`` rule suffix and a ``WARNING:`` detail prefix;
    every other rule implemented in this slice is an error.
    """
    reports.report(report_id)
    return [issue for check in _CHECKS for issue in check(store, reports, report_id)]

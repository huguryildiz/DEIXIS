"""The fourteen structural report assembly checks from design section 8."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any, Callable

from deixis.domain import contracts, phrasebank
from deixis.workflow.report import phrasing, review_methodology
from deixis.workflow.report.store import ReportStore
from deixis.workflow.report.snapshot import evidence_row_ids
from deixis.workflow.store import Store


_DERIVED_SECTIONS = {"abstract", "I", "IX"}
_SUPPORT_ORDER = {"analyst_inference": 0, "source_stated": 1}
_DEPTH_ORDER = {"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}
_CORPUS_KEYS = ("found", "unique", "screened", "included", "full_text")
_BANNED = re.compile(
    r"\b(?:gaps?|open problems?|open questions?"
    r"|novel|novelty|first-ever|the first (?:study|work|paper|survey|review|attempt|to|time)"
    r"|first of its kind|for the first time|araştırma boşluğ\w*"
    r"|boşluk|boşluğ\w*"
    r"|açık problem\w*|açık soru\w*|özgün\w*|yenilik\w*"
    r"|ilk kez|ilk defa|bir ilk|ilk çalışma\w*)\b", re.IGNORECASE,
)


def _issue(rule: str, section_id: str, detail: str) -> dict[str, Any]:
    return {"rule": rule, "section_id": section_id, "detail": detail}


def _claims(store: Store, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    claims = [dict(row) for row in store.conn.execute(
        "SELECT c.*, s.section_id, s.ordinal AS section_ordinal FROM report_claims c"
        " JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ? ORDER BY s.ordinal, c.ordinal", (report_id,),
    )]
    if current:
        for claim in claims:
            if claim["current_revision_id"] is not None:
                revision = store.conn.execute("SELECT text FROM report_claim_revisions WHERE id = ?",
                                              (claim["current_revision_id"],)).fetchone()
                claim["text"] = revision["text"]
    return claims


def _links(store: Store, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    if current:
        return ReportStore(store).effective_links(report_id)
    return [dict(row) for row in store.conn.execute(
        "SELECT l.*, c.claim_key, s.section_id FROM report_citation_links l"
        " JOIN report_claims c ON c.id = l.claim_id"
        " JOIN report_sections s ON s.id = c.report_section_id WHERE s.report_id = ?", (report_id,),
    )]


def _gaps(store: Store, report_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in store.conn.execute("SELECT * FROM report_gaps WHERE report_id = ?", (report_id,))]


def _json_record(row: dict, field: str, table: str, key: str, section_id: str,
                 issues: list[dict[str, Any]]) -> dict | None:
    raw = row.get(field)
    if raw is None and field in {"count_json", "equation_origin_json"}:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = None
    valid = isinstance(value, dict)
    if valid and field == "count_json":
        valid = (all(isinstance(value.get(name), list) and value[name]
                     and all(isinstance(item, str) for item in value[name])
                     for name in ("numerator_source_ids", "denominator_source_ids"))
                 and isinstance(value.get("column_id"), str))
    elif valid and field == "equation_origin_json":
        valid = (isinstance(value.get("passage_id"), str)
                 and value.get("text_source") in {"text_layer", "ocr", "marker", "latex_source"})
    elif valid and field == "basis_json":
        valid = all(isinstance(value.get(name), list) and all(isinstance(item, str) for item in value[name])
                    for name in ("basis_claim_keys", "basis_passage_ids", "basis_cell_ids"))
    elif valid and field == "provenance_json":
        valid = value.get("origin") in {"code", "model"}
    if not valid:
        issues.append(_issue("stored_record_malformed", section_id, f"ERROR: {table} {key} {field} malformed."))
        return None
    return value


def _section_payload(store: Store, section: dict) -> tuple[dict | None, bool]:
    if not section.get("step_id"):
        return None, False
    row = store.conn.execute("SELECT payload_json FROM step_inputs WHERE step_id = ?"
                             " ORDER BY rowid DESC LIMIT 1", (section["step_id"],)).fetchone()
    if row is None:
        return None, False
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return None, True
    return (payload, False) if isinstance(payload, dict) else (None, True)


def _draft_items(section: dict, field: str, issues: list[dict[str, Any]]) -> list[dict]:
    draft = section["draft"] if isinstance(section["draft"], dict) else {}
    items = draft.get(field, [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items) or (
            field == "insufficient_evidence" and any(not isinstance(item.get("reason"), str) for item in items)):
        issues.append(_issue("stored_record_malformed", section["section_id"],
                             f"ERROR: report_sections draft_json {field} malformed."))
        return []
    return items


def _section_texts(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[tuple[int, str, str]]:
    claim_texts: dict[str, list[str]] = defaultdict(list)
    for claim in _claims(store, report_id, current=current):
        claim_texts[claim["section_id"]].append(claim["text"])
    result = []
    for section in reports.sections(report_id):
        draft = section["draft"] if isinstance(section["draft"], dict) else {}
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


def _check_glossary_order(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    plan = reports.report(report_id)["plan"] or {}
    texts = _section_texts(store, reports, report_id, current=current)
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


def _claim_depths(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> dict[str, str]:
    cells = {cell["cell_id"]: cell for cell in reports.snapshot(report_id).get("cells", [])}
    depths: dict[str, list[str]] = defaultdict(list)
    rows = _links(store, report_id, current=True) if current else store.conn.execute(
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
            if current:
                passage = store.conn.execute("SELECT kind FROM passages WHERE id = ?", (row["passage_id"],)).fetchone()
                kind = passage["kind"] if passage else None
                depth = "abstract" if kind == "abstract" else "selected_sections" if kind is not None else None
            else:
                depth = "abstract" if row["passage_kind"] == "abstract" else "selected_sections"
        if depth in _DEPTH_ORDER:
            depths[row["claim_id"]].append(depth)
    return {claim_id: min(values, key=_DEPTH_ORDER.__getitem__) for claim_id, values in depths.items()}


def _check_derived_strength(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    claims = _claims(store, report_id)
    by_key = {claim["claim_key"]: claim for claim in claims}
    depths = _claim_depths(store, reports, report_id, current=current)
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
        if derived_depth and body_depths and (not current or len(body_depths) == len(ref_keys)):
            weakest_depth = min(body_depths, key=_DEPTH_ORDER.__getitem__)
            if _DEPTH_ORDER[derived_depth] > _DEPTH_ORDER[weakest_depth]:
                issues.append(_issue(
                    "derived_depth_too_deep", claim["section_id"],
                    f"ERROR: {claim['claim_key']} has {derived_depth} depth, deeper than the weakest body_ref "
                    f"depth ({weakest_depth}).",
                ))
    return issues


def _check_corpus_counts(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    del store
    corpus = reports.snapshot(report_id).get("corpus")
    sections = {section["section_id"]: section for section in reports.sections(report_id)}
    issues = []
    for section_id in ("II", "VIII"):
        section = sections.get(section_id)
        if not section:
            continue
        validation = section.get("validation")
        numbers = validation.get("numbers") if isinstance(validation, dict) else None
        kind = "review_methodology" if section_id == "II" else "limitations"
        if (not isinstance(corpus, dict) or any(type(corpus.get(key)) is not int for key in _CORPUS_KEYS)
                or not isinstance(numbers, dict) or type(numbers.get("version")) is not int
                or numbers["version"] != 1
                or numbers.get("kind") != kind or not isinstance(numbers.get("corpus"), dict)):
            issues.append(_issue("corpus_numbers_missing", section_id, "ERROR: structured numbers missing or wrong kind/version."))
            continue
        def checked(mapping: dict, key: str, numeric: bool = False) -> int | float | None:
            value = mapping.get(key)
            valid = ((type(value) is int or (type(value) is float and math.isfinite(value)))
                     if numeric else type(value) is int)
            if not valid:
                issues.append(_issue("corpus_numbers_missing", section_id, f"ERROR: {key} missing or malformed."))
                return None
            return value

        values = {key: checked(numbers["corpus"], key) for key in _CORPUS_KEYS}
        for key, value in values.items():
            if value is not None and value != corpus[key]:
                issues.append(_issue("corpus_count_mismatch", section_id, f"ERROR: {key} differs from frozen corpus."))
        included, full_text = values["included"], values["full_text"]
        if section_id == "II":
            ratio = checked(numbers, "full_text_ratio", numeric=True)
            if ratio is not None and included is not None and full_text is not None:
                try:
                    expected_ratio = full_text / included if included else 0.0
                except OverflowError:
                    expected_ratio = math.inf
                if not math.isfinite(expected_ratio) or abs(ratio - expected_ratio) > 1e-9:
                    issues.append(_issue("corpus_count_mismatch", section_id, "ERROR: full_text_ratio differs from counts."))
        else:
            for key in ("included", "full_text"):
                value = checked(numbers, key)
                if value is not None and value != corpus[key]:
                    issues.append(_issue("corpus_count_mismatch", section_id, f"ERROR: top-level {key} differs from frozen corpus."))
            share = checked(numbers, "no_full_text_share", numeric=True)
            if share is not None and included is not None and full_text is not None:
                try:
                    expected_share = (included - full_text) / included if included else 0.0
                except OverflowError:
                    expected_share = math.inf
                if not math.isfinite(expected_share) or abs(share - expected_share) > 1e-9:
                    issues.append(_issue("corpus_count_mismatch", section_id, "ERROR: no_full_text_share differs from counts."))
            items = numbers.get("items")
            if not isinstance(items, list) or any(
                not isinstance(item, dict) or type(item.get("number")) is not int or not isinstance(item.get("text"), str)
                for item in items
            ):
                issues.append(_issue("corpus_numbers_missing", section_id, "ERROR: items malformed."))
            elif (section.get("draft") if isinstance(section.get("draft"), dict) else {}).get("text") != review_methodology.render_limitations(
                numbers, reports.report(report_id)["language"] or "en"
            ):
                issues.append(_issue("limitations_text_drift", section_id, "ERROR: VIII text differs from structured items."))
    return issues


def _check_count_fields(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    snapshot = reports.snapshot(report_id)
    rows = set(evidence_row_ids(snapshot))
    columns = {column["column_id"] for column in snapshot["columns"]}
    cells = {(cell["source_version_id"], cell["column_id"]): cell for cell in snapshot["cells"]}
    issues = []
    for claim in _claims(store, report_id, current=current):
        if claim["count_json"] is None:
            continue
        count = _json_record(claim, "count_json", "report_claims", claim["claim_key"], claim["section_id"], issues)
        if count is None:
            continue
        numerator, denominator, column = (count["numerator_source_ids"], count["denominator_source_ids"],
                                           count["column_id"])
        section = claim["section_id"]
        def add(code: str, detail: str) -> None:
            issues.append(_issue(code, section, f"ERROR: {claim['claim_key']} {detail}."))
        if (len(set(numerator)) != len(numerator) or len(set(denominator)) != len(denominator)
                or not set(numerator) <= set(denominator)):
            add("count_members_invalid", "duplicate or non-subset count members")
        if column not in columns or any(source not in rows or (source, column) not in cells
                                        for source in set(numerator + denominator)) or any(
            cells.get((source, column), {}).get("state") == "not_applicable" for source in denominator
        ):
            add("count_member_not_in_snapshot", "member, column, cell or applicability missing from snapshot")
        members = [cells[(source, column)] for source in denominator if (source, column) in cells]
        selected = [cells[(source, column)] for source in numerator if (source, column) in cells]
        if len({cell["reading_depth"] for cell in members}) > 1:
            add("count_depth_mixed", "denominator mixes reading depths")
        if (len({cell["state"] for cell in selected}) > 1 or len({json.dumps(cell["value"], sort_keys=True)
                                                               for cell in selected if cell["state"] == "value"}) > 1):
            add("count_value_mixed", "numerator mixes states or values")
        numbers = [int(match) if len(match) < 4000 else None for match in
                   re.findall(r"\b\d+\b", contracts._without_math(claim["text"]))]
        allowed = {len(numerator), len(denominator)}
        if numbers and (any(number not in allowed for number in numbers) or not allowed <= set(numbers)):
            add("count_number_mismatch", "text integers disagree with member counts")
    return issues


def _check_banned_words(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    issues = []
    def scan(section: str, where: str, value: Any) -> None:
        if not isinstance(value, str):
            return
        text = contracts._without_math(value)
        for match in _BANNED.finditer(text):
            prefix = text[:match.start()].lower()
            preceding = re.search(r"(\w+)[\s-]+$", prefix)
            if match.group().lower() in {"gap", "gaps"} and preceding and preceding.group(1) in {
                "band", "energy", "spectral", "optical", "mass"
            }:
                continue
            if match.group().lower().startswith(("boşluk", "boşluğ")) and preceding and preceding.group(1) in {
                "bant", "enerji"
            }:
                continue
            issues.append(_issue("banned_word", section, f"ERROR: {match.group()!r} in {where}."))

    for claim in _claims(store, report_id, current=current):
        if claim["section_id"] != "II":
            scan(claim["section_id"], f"claim {claim['claim_key']}", claim["text"])
    for section in reports.sections(report_id):
        section_id = section["section_id"]
        if section_id == "II":
            continue
        for subsection in _draft_items(section, "subsections", issues):
            scan(section_id, "heading", subsection.get("heading"))
        for gap in _draft_items(section, "gaps", issues):
            scan(section_id, f"gap {gap.get('gap_id')}", gap.get("text"))
        for entry in _draft_items(section, "insufficient_evidence", issues):
            scan(section_id, "insufficient_evidence", entry.get("reason"))
    for gap in _gaps(store, report_id):
        scan("VI", f"gap {gap['gap_id']}", gap["text"])
    return issues


def _check_bibliography(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    snapshot = reports.snapshot(report_id)
    sources = set(evidence_row_ids(snapshot))
    cells = {cell["cell_id"]: cell for cell in snapshot["cells"]}
    issues = []
    for link in _links(store, report_id, current=current):
        source = link["source_version_id"]
        section = link["section_id"]
        if source not in sources:
            issues.append(_issue("citation_source_not_in_corpus", section, f"ERROR: {source} is outside frozen corpus."))
        record = store.conn.execute(
            "SELECT v.title, w.source_key FROM source_versions v LEFT JOIN works w ON w.id = v.work_id"
            " WHERE v.id = ?", (source,),
        ).fetchone()
        if not record or not (record["title"] or "").strip() or not (record["source_key"] or "").strip():
            issues.append(_issue("reference_record_incomplete", section, f"ERROR: {source} lacks title or source key."))
        if link["cell_id"]:
            owner = cells.get(link["cell_id"], {}).get("source_version_id")
        else:
            passage = store.conn.execute("SELECT source_version_id FROM passages WHERE id = ?",
                                         (link["passage_id"],)).fetchone()
            owner = passage["source_version_id"] if passage else None
        if owner != source:
            issues.append(_issue("citation_source_mismatch", section, f"ERROR: citation owner differs for {source}."))
    return issues


def _check_gap_bases(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    snapshot = reports.snapshot(report_id)
    plan = reports.report(report_id)["plan"] or {}
    cells = {cell["cell_id"]: cell for cell in snapshot["cells"]}
    sources = set(evidence_row_ids(snapshot))
    gaps = _gaps(store, report_id)
    gap_ids = {gap["gap_id"] for gap in gaps}
    sections = {section["section_id"]: section for section in reports.sections(report_id)}
    payload, malformed_payload = (_section_payload(store, sections["VI"])
                                  if "VI" in sections else (None, False))
    target = payload.get("report_target") if isinstance(payload, dict) else None
    target_cells = target.get("cells") if isinstance(target, dict) else None
    candidates = target.get("gap_candidates") if isinstance(target, dict) else None
    payload_passages = payload.get("passages") if isinstance(payload, dict) else None
    usable_candidates = (isinstance(payload, dict) and isinstance(candidates, list)
        and all(isinstance(candidate, dict)
                and isinstance(candidate.get("gap_id"), str)
                and isinstance(candidate.get("column_id"), str)
                and isinstance(candidate.get("basis_cell_ids"), list)
                and all(isinstance(cell_id, str) for cell_id in candidate["basis_cell_ids"])
                for candidate in candidates))
    usable_stated_input = (
        isinstance(target_cells, list)
        and all(isinstance(cell, dict) and isinstance(cell.get("cell_id"), str) for cell in target_cells)
        and isinstance(payload_passages, list)
        and all(isinstance(passage, dict) and isinstance(passage.get("passage_id"), str)
                for passage in payload_passages)
    )
    input_cells = {cell["cell_id"] for cell in target_cells} if usable_stated_input else set()
    input_passages = {passage["passage_id"] for passage in payload_passages} if usable_stated_input else set()
    issues = []
    if malformed_payload and gaps:
        issues.append(_issue("stored_record_malformed", "VI",
                             "ERROR: step_inputs payload_json malformed for section VI."))
    for claim in _claims(store, report_id):
        if claim["section_id"] not in {"VI", "VII"}:
            continue
        refs = [row["ref_value"] for row in store.conn.execute(
            "SELECT ref_value FROM report_claim_refs WHERE claim_id = ? AND ref_kind = 'gap_ref'", (claim["id"],))]
        valid_refs = [ref for ref in refs if ref in gap_ids]
        for ref in refs:
            if ref not in gap_ids:
                issues.append(_issue("gap_ref_unknown", claim["section_id"], f"ERROR: {claim['claim_key']} names {ref}."))
        if claim["section_id"] == "VII":
            cell_links = ([link for link in _links(store, report_id, current=True) if link["claim_id"] == claim["id"]]
                          if current else store.conn.execute("SELECT cell_id FROM report_citation_links WHERE claim_id = ?",
                                                             (claim["id"],)))
            has_future_cell = any(cells.get(row["cell_id"], {}).get("column_id") == plan.get("future_work_column_id")
                                  and row["cell_id"] in cells for row in cell_links if row["cell_id"])
            if not valid_refs and not has_future_cell:
                issues.append(_issue("vii_claim_without_basis", "VII", f"ERROR: {claim['claim_key']} lacks a basis."))
            if claim["support_type"] == "analyst_inference" and not valid_refs:
                issues.append(_issue("vii_inference_without_gap", "VII", f"ERROR: {claim['claim_key']} lacks a gap."))
    for gap in gaps:
        kind, gap_id = gap["kind"], gap["gap_id"]
        basis = (_json_record(gap, "basis_json", "report_gaps", gap_id, "VI", issues)
                 if kind != "conflicting_evidence" else None)
        provenance = _json_record(gap, "provenance_json", "report_gaps", gap_id, "VI", issues)
        if kind not in contracts.GAP_KINDS:
            issues.append(_issue("gap_kind_unknown", "VI", f"ERROR: {gap_id} has kind {kind}."))
            continue
        if basis is None or provenance is None or kind == "conflicting_evidence":
            continue
        passages, cell_ids = basis["basis_passage_ids"], basis["basis_cell_ids"]
        if not (usable_candidates if kind == "corpus_absence" else usable_stated_input):
            rule = "gap_absence_basis_invalid" if kind == "corpus_absence" else "gap_basis_missing"
            issues.append(_issue(rule, "VI", f"ERROR: {gap_id} has no usable VI step input."))
            continue
        if kind == "stated_limitation":
            if not passages and not cell_ids or any(cell_id not in cells for cell_id in cell_ids) or any(
                store.conn.execute("SELECT 1 FROM passages WHERE id = ?", (passage_id,)).fetchone() is None
                for passage_id in passages
            ):
                issues.append(_issue("gap_basis_missing", "VI", f"ERROR: {gap_id} has missing basis records."))
            if any(cell_id not in input_cells or cells.get(cell_id, {}).get("column_id") != plan.get("limitations_column_id")
                   for cell_id in cell_ids) or any(
                passage_id not in input_passages or (
                    (owner := store.conn.execute("SELECT source_version_id FROM passages WHERE id = ?",
                                                (passage_id,)).fetchone()) is not None
                    and owner["source_version_id"] not in sources)
                for passage_id in passages
            ):
                issues.append(_issue("gap_basis_foreign", "VI", f"ERROR: {gap_id} basis is outside VI input or scope."))
        else:
            def invalid(detail: str) -> None:
                issues.append(_issue("gap_absence_basis_invalid", "VI", f"ERROR: {gap_id} {detail}."))
            if provenance["origin"] != "code":
                invalid("origin is not code")
            selected = [cells.get(cell_id) for cell_id in cell_ids]
            columns = {cell["column_id"] for cell in selected if cell}
            if (len(cell_ids) < 3 or len(set(cell_ids)) != len(cell_ids) or None in selected
                    or len(columns) != 1):
                invalid("basis needs three unique snapshot cells in one column")
                continue
            column = next(iter(columns))
            applicable = {cell["cell_id"] for cell in snapshot["cells"] if cell["column_id"] == column
                          and cell["reading_depth"] == "full_text" and cell["state"] != "not_applicable"}
            if (set(cell_ids) != applicable or any(cell["reading_depth"] != "full_text"
                                                    or cell["state"] != "not_found_in_inspected_scope"
                                                    for cell in selected)):
                invalid("basis does not equal all applicable full-text absence cells")
            if not any(candidate["gap_id"] == gap_id and candidate["column_id"] == column
                       and set(candidate["basis_cell_ids"]) == set(cell_ids) for candidate in candidates):
                invalid("basis differs from stored code candidate")
    return issues


def _check_equations(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    sections = {section["section_id"]: section for section in reports.sections(report_id)}
    section_steps = {section_id: section["step_id"] for section_id, section in sections.items()}
    links_by_claim: dict[str, list[dict]] = defaultdict(list)
    for link in _links(store, report_id, current=current):
        links_by_claim[link["claim_id"]].append(link)
    issues = []
    checked_payload_sections: set[str] = set()
    malformed_sections: set[str] = set()
    for claim in _claims(store, report_id, current=current):
        if claim["section_id"] == "II":
            continue
        section, key, text = claim["section_id"], claim["claim_key"], claim["text"]
        dollars = sum(1 for index, char in enumerate(text) if char == "$" and not contracts._is_escaped(text, index))
        spans = contracts._math_spans(text)
        if dollars % 2 or any(not contracts._math_span_is_well_formed(span) for span in spans):
            issues.append(_issue("math_not_well_formed", section, f"ERROR: {key} has malformed math."))
        equation = bool(claim["equation_ref"] or claim["equation_origin_json"] is not None
                        or any(span.startswith("$$") for span in spans))
        if not equation:
            continue
        if claim["equation_origin_json"] is None:
            issues.append(_issue("equation_origin_missing", section, f"ERROR: {key} has no equation origin."))
            continue
        origin = _json_record(claim, "equation_origin_json", "report_claims", key, section, issues)
        if origin is None:
            continue
        if section not in checked_payload_sections:
            _, malformed_payload = _section_payload(store, sections[section])
            if malformed_payload:
                issues.append(_issue("stored_record_malformed", section,
                                     f"ERROR: step_inputs payload_json malformed for section {section}."))
                malformed_sections.add(section)
            checked_payload_sections.add(section)
        if origin["passage_id"] not in {link["passage_id"] for link in links_by_claim[claim["id"]]}:
            issues.append(_issue("equation_origin_not_cited", section,
                                 f"ERROR: {key} origin is not cited by this claim."))
        allowed = set()
        for link in links_by_claim[claim["id"]]:
            input_row = store.conn.execute("SELECT step_id, payload_json FROM step_inputs WHERE id = ?",
                                           (link["step_input_id"],)).fetchone()
            if not input_row or not section_steps.get(section) or input_row["step_id"] != section_steps[section]:
                continue
            try:
                payload = json.loads(input_row["payload_json"])
            except (TypeError, ValueError):
                payload = None
            if not isinstance(payload, dict):
                if section not in malformed_sections:
                    issues.append(_issue("stored_record_malformed", section,
                                         f"ERROR: step_inputs payload_json malformed for section {section}."))
                    malformed_sections.add(section)
                continue
            passages = payload.get("passages")
            if (not isinstance(passages, list) or any(
                not isinstance(passage, dict) or not isinstance(passage.get("passage_id"), str)
                for passage in passages
            )):
                continue
            allowed.update(passage["passage_id"] for passage in passages)
        if origin["passage_id"] not in allowed:
            issues.append(_issue("equation_origin_not_in_input", section, f"ERROR: {key} origin was not supplied."))
        passage = store.conn.execute("SELECT text, text_source FROM passages WHERE id = ?",
                                     (origin["passage_id"],)).fetchone()
        if not passage or not contracts._math_spans(passage["text"]):
            issues.append(_issue("equation_origin_without_math", section, f"ERROR: {key} origin has no math."))
        if passage and origin["text_source"] != passage["text_source"]:
            issues.append(_issue("equation_origin_mismatch", section,
                                 f"ERROR: {key} origin text_source differs from stored passage."))
        if passage and passage["text_source"] in {"ocr", "marker"}:
            issues.append(_issue("equation_text_source_warning", section,
                                 f"WARNING: {key} equation came from {passage['text_source']} text."))
    return issues


def _check_anchors(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    cells = {cell["cell_id"]: cell for cell in reports.snapshot(report_id)["cells"]}
    issues = []
    for link in _links(store, report_id, current=current):
        section, key = link["section_id"], link["claim_key"]
        anchor = link["anchor_text"]
        if not link["anchor_match"] or not anchor:
            issues.append(_issue("citation_anchor_unmatched", section, f"ERROR: {key} has unmatched anchor."))
        if link["cell_id"]:
            cell = cells.get(link["cell_id"])
            if not cell:
                issues.append(_issue("cell_not_in_snapshot", section, f"ERROR: {key} cell is outside snapshot."))
            elif anchor and not any(contracts.locate_anchor(anchor, evidence.get("quote") or "")
                                    for evidence in cell.get("evidence", [])):
                issues.append(_issue("anchor_not_in_cell_evidence", section, f"ERROR: {key} anchor is absent from cell quotes."))
        else:
            passage = store.conn.execute("SELECT text FROM passages WHERE id = ?", (link["passage_id"],)).fetchone()
            if anchor and (not passage or not contracts.locate_anchor(anchor, passage["text"])):
                issues.append(_issue("anchor_not_in_passage", section, f"ERROR: {key} anchor is absent from passage."))
    return issues


def _check_conflict_links(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    del reports
    v_keys = {claim["claim_key"] for claim in _claims(store, report_id) if claim["section_id"] == "V"}
    issues = []
    for gap in _gaps(store, report_id):
        if gap["kind"] != "conflicting_evidence":
            continue
        basis = _json_record(gap, "basis_json", "report_gaps", gap["gap_id"], "VI", issues)
        if basis is not None and (not basis["basis_claim_keys"] or any(
            key not in v_keys for key in basis["basis_claim_keys"]
        )):
            issues.append(_issue("conflict_gap_without_v_claim", "VI", f"ERROR: {gap['gap_id']} lacks V claim basis."))
    return issues


def _check_phrase_frames(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    report = reports.report(report_id)
    sections = {section["section_id"]: section for section in reports.sections(report_id)}
    claims_by_section: dict[str, list[dict]] = defaultdict(list)
    for claim in _claims(store, report_id, current=current):
        claims_by_section[claim["section_id"]].append(claim)
    links_by_claim: dict[str, set[str]] = defaultdict(set)
    for link in _links(store, report_id, current=current):
        links_by_claim[link["claim_id"]].add(link["source_version_id"])
    latest = {}
    for row in store.conn.execute("SELECT section_id, sentence_id, before, after, outcome"
                                  " FROM report_phrase_repairs WHERE report_id = ? ORDER BY rowid", (report_id,)):
        latest[(row["section_id"], row["sentence_id"])] = dict(row)
    phrasebank_text = contracts._phrasebank_text()
    issues = []
    for section_id, section in sections.items():
        if section_id == "II":
            continue
        payload, malformed_payload = _section_payload(store, section)
        if malformed_payload:
            issues.append(_issue("stored_record_malformed", section_id,
                                 f"ERROR: step_inputs payload_json malformed for section {section_id}."))
        question = payload.get("question") if payload else None
        valid_question = (isinstance(question, dict) and isinstance(question.get("text"), str)
                          and (question.get("language_hint") is None
                               or isinstance(question.get("language_hint"), str)))
        if payload is not None and "question" in payload and not valid_question:
            issues.append(_issue("stored_record_malformed", section_id,
                                 "ERROR: step_inputs question malformed."))
        language = (phrasebank.frames_language(payload) if valid_question
                    else (report["language"] or store.scope(report["research_id"], report["scope_revision"])
                          .get("language_hint") or "en"))
        language = phrasebank.checked_language(language)
        lexical_language = language if language and phrasebank.has_frames(phrasebank_text, language) else "en"
        for claim in claims_by_section[section_id]:
            text = contracts._without_math(claim["text"])
            for match in phrasebank.own_work_phrases(text, lexical_language):
                issues.append(_issue("own_work_phrase_in_claim", section_id,
                                     f"ERROR: {claim['claim_key']} uses {match!r}."))
            if len(links_by_claim[claim["id"]]) == 1:
                for match in phrasebank.plural_source_phrases(text, lexical_language):
                    issues.append(_issue("plural_sources_for_one_source", section_id,
                                         f"ERROR: {claim['claim_key']} uses {match!r} for one source."))
        if not phrasebank.REPORT_PHRASEBANK_SECTIONS.get(section_id) or not language or not phrasebank.has_frames(
            phrasebank_text, language
        ):
            continue
        fields = [{"claim_key": claim["claim_key"], "text": claim["text"],
                   "support_type": claim["support_type"]} for claim in claims_by_section[section_id]
                  if not current or claim["current_revision_id"] is None]
        fields.extend(_draft_items(section, "insufficient_evidence", issues))
        for flagged in phrasing.flagged_sentences(section_id, fields, phrasebank_text, language):
            repair = latest.get((section_id, flagged["sentence_id"]))
            if not repair or repair["outcome"] not in {"unframed_exception", "reverted_exception"} or (
                flagged["text"] != repair["before"] and flagged["text"] != repair["after"]
            ):
                issues.append(_issue("unframed_sentence_not_recorded", section_id,
                                     f"ERROR: {flagged['sentence_id']} has no matching exception."))
    return issues


def _check_word_budgets(store: Store, reports: ReportStore, report_id: str, *, current: bool = False) -> list[dict[str, Any]]:
    plan = reports.report(report_id)["plan"] or {}
    budgets = plan.get("section_budgets", {})
    sections = reports.sections(report_id)
    issues = []
    total = 0
    claims_by_section: dict[str, list[dict]] = defaultdict(list)
    if current:
        for claim in _claims(store, report_id, current=True):
            claims_by_section[claim["section_id"]].append(claim)
    for section in sections:
        word_count = section["word_count"]
        edited = current and any(claim["current_revision_id"] is not None
                                 for claim in claims_by_section[section["section_id"]])
        if edited:
            word_count = sum(len(claim["text"].split()) for claim in claims_by_section[section["section_id"]])
            word_count += sum(len(entry["reason"].split()) for entry in
                              _draft_items(section, "insufficient_evidence", issues))
        if word_count is None:
            continue
        maximum = budgets.get(section["section_id"], {}).get("max_words")
        if maximum is not None:
            total += word_count
        if maximum is not None and word_count > maximum:
            issues.append(_issue(
                "section_word_count_over_budget", section["section_id"],
                f"ERROR: {'current' if edited else 'stored'} word_count {word_count} exceeds the frozen upper budget {maximum}.",
            ))
    total_maximum = sum(
        budget["max_words"] for budget in budgets.values() if isinstance(budget.get("max_words"), int)
    )
    if total_maximum and total > total_maximum:
        issues.append(_issue(
            "report_word_count_over_budget", "report",
            f"ERROR: {'current' if current else 'stored'} report word_count {total} exceeds the frozen upper budget {total_maximum}.",
        ))
    return issues


_CHECKS: tuple[Callable[[Store, ReportStore, str], list[dict[str, Any]]], ...] = (
    _check_duplicate_claim_keys,
    _check_glossary_order,
    _check_body_refs,
    _check_derived_strength,
    _check_count_fields,
    _check_banned_words,
    _check_corpus_counts,
    _check_bibliography,
    _check_gap_bases,
    _check_word_budgets,
    _check_equations,
    _check_anchors,
    _check_conflict_links,
    _check_phrase_frames,
)


def run_assembly_checks(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    """Structural checks over a finished report. Empty means the report may become valid.

    Each item is ``{"rule", "section_id", "detail"}``. Rule 2 is non-blocking
    and carries both a ``_warning`` rule suffix and a ``WARNING:`` detail prefix.
    OCR/Marker equation origins carry the same non-blocking convention.
    """
    reports.report(report_id)
    issues = [issue for check in _CHECKS for issue in check(store, reports, report_id)]
    seen_malformed: set[tuple[str, str]] = set()
    result = []
    for issue in issues:
        if issue["rule"] == "stored_record_malformed":
            key = (issue["section_id"], issue["detail"])
            if key in seen_malformed:
                continue
            seen_malformed.add(key)
        result.append(issue)
    return result


def run_current_checks(store: Store, reports: ReportStore, report_id: str) -> dict:
    """Read working text without publishing, validating or rewriting the base report."""
    from deixis.workflow.report.edit_check import shape_result

    reports.report(report_id)
    unchanged = {_check_duplicate_claim_keys, _check_body_refs, _check_corpus_counts, _check_conflict_links}
    items = [item for check in _CHECKS for item in
             (check(store, reports, report_id) if check in unchanged else
              check(store, reports, report_id, current=True))]
    claims = _claims(store, report_id, current=True)
    by_key = {claim["claim_key"]: claim for claim in claims}
    depths = _claim_depths(store, reports, report_id, current=True)
    skipped = []

    def skip(claim: dict, rule: str, reason: str) -> None:
        skipped.append({"rule": rule, "section_id": claim["section_id"],
                        "claim_key": claim["claim_key"], "reason": reason})

    for claim in claims:
        if claim["count_json"] is not None and not re.search(r"\b\d+\b", contracts._without_math(claim["text"])):
            skip(claim, "count_text_not_checked", "no_integer_in_text")
        if claim["section_id"] in _DERIVED_SECTIONS:
            refs = [row["ref_value"] for row in store.conn.execute(
                "SELECT ref_value FROM report_claim_refs WHERE claim_id = ? AND ref_kind = 'body_ref'",
                (claim["id"],))]
            if claim["id"] not in depths or any(key not in by_key or by_key[key]["id"] not in depths for key in refs):
                skip(claim, "derived_depth_not_checked", "no_citation_depth")
        if claim["current_revision_id"] is not None:
            skip(claim, "phrase_frames", "human_text")
            if claim["section_id"] == "VIII" and contracts.limitations_number_restated(claim["text"]):
                items.append(_issue("limitations_number_restated", "VIII",
                                    f"ERROR: {claim['claim_key']} restates a number outside an item reference."))
    return shape_result(items, skipped, [check.__name__.removeprefix("_check_") for check in _CHECKS]
                        + ["limitations_number_restated"],
                        sum(claim["current_revision_id"] is not None for claim in claims))

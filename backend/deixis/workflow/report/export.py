"""Markdown rendering of the report read model, without recomputing citations."""

from __future__ import annotations

import re
from typing import Any

from deixis.workflow.report.store import DISPLAY_ORDER, ReportStore
from deixis.workflow.report import export_text
from deixis.workflow.report.export_text import HEADINGS, REVIEW_CODES, REVIEW_REASONS
from deixis.workflow.store import NotFound, Store

MEDIA_TYPES = {"markdown": "text/markdown; charset=utf-8"}


def _md(value: Any) -> str:
    """Keep stored text on one line and stop it from creating Markdown structure.

    Paired dollar spans retain their delimiters; an unmatched dollar is plain text.
    """
    source = " ".join(str(value if value is not None else "").split())
    if not source:
        return ""
    result: list[str] = []
    index = 0
    while index < len(source):
        if source[index] == "$":
            delimiter = "$$" if source.startswith("$$", index) else "$"
            end = source.find(delimiter, index + len(delimiter))
            if end >= 0:
                content = source[index + len(delimiter):end]
                # Backticks inside math are literal content, not Markdown structure.
                content = content.translate(str.maketrans({"<": r"{\lt}", ">": r"{\gt}",
                                                          "[": "{[}", "]": "{]}"}))
                result.append(delimiter + content + delimiter)
                index = end + len(delimiter)
                continue
        char = source[index]
        result.append("\\" + char if char in "\\[]<>`|" else char)
        index += 1
    escaped = "".join(result)
    if re.match(r"(?:[#\-+*]|\d+[.)])", source):
        escaped = "\\" + escaped
    return escaped


def _table(table: dict[str, Any], tr: bool) -> str:
    def table_cell(value: str) -> str:
        value = value.replace("\n", " ")
        result: list[str] = []
        index = 0
        while index < len(value):
            if value[index] == "$":
                delimiter = "$$" if value.startswith("$$", index) else "$"
                end = value.find(delimiter, index + len(delimiter))
                if end >= 0:
                    content = value[index + len(delimiter):end]
                    math: list[str] = []
                    offset = 0
                    while offset < len(content):
                        if content.startswith("\\\\", offset):
                            math.append("\\\\")
                            offset += 2
                        elif content.startswith("\\|", offset):
                            math.append(r"{\Vert}")
                            offset += 2
                        elif content[offset] == "|":
                            math.append(r"{\vert}")
                            offset += 1
                        else:
                            math.append(content[offset])
                            offset += 1
                    result.append(delimiter + "".join(math) + delimiter)
                    index = end + len(delimiter)
                    continue
            result.append(value[index])
            index += 1
        return "".join(result)

    columns = table["columns"]
    rows = table["rows"]
    caption = export_text.table_caption(table, tr)
    lines = [caption, "", "| " + " | ".join(table_cell(cell) for cell in
             [_md(export_text.source_heading(tr)), *(_md(c["name"]) for c in columns)]) + " |",
             "| " + " | ".join(["---"] * (len(columns) + 1)) + " |"]
    cells = {(cell["source_version_id"], cell["column_id"]): cell for cell in table["cells"]}
    for row in rows:
        values = [export_text.source_cell(row, tr, _md)]
        for column in columns:
            cell = cells.get((row["source_version_id"], column["column_id"]))
            values.append(export_text.cell_text(cell, column, tr, _md))
        lines.append("| " + " | ".join(table_cell(value) for value in values) + " |")
    return "\n".join(lines)


def to_markdown(view: dict[str, Any], *, title: str, corpus: dict[str, int] | None) -> str:
    tr = export_text.is_turkish(view)
    lines: list[str] = []
    draft = export_text.draft_line(view, tr)
    if draft is not None:
        lines.extend([f"> {_md(draft)}", ""])
    lines.extend([f"# {_md(title)}", export_text.report_identity(view, tr), ""])
    missing = view.get("missing_rows")
    if missing:
        lines.extend([export_text.missing_rows_sentence(missing, tr), ""])
        for row in missing["failed_rows"]:
            source, reason = export_text.missing_row_fields(row, tr, _md)
            lines.append(f"- {source}: {reason}")
        lines.append("")
    edit = export_text.edit_note(view, tr, _md)
    if edit is not None:
        edit_lines = [edit.paragraph, ""]
        if edit.not_checked_heading is not None:
            for section_id, rule, severity, detail in edit.items:
                edit_lines.append(f"- {section_id} · {rule} ({severity}): {detail}")
            edit_lines.extend(["", edit.not_checked_heading])
            for section_id, claim_key, rule, reason in edit.skipped_rules:
                edit_lines.append(f"- {section_id} · {claim_key}: {rule} ({reason})")
            edit_lines.extend(f"- {limit}" for limit in edit.not_checked)
            edit_lines.append("")
        lines.extend(edit_lines)
    if view.get("evidence_changes", {}).get("any"):
        lines.extend([export_text.evidence_changed_sentence(tr), ""])
    freshness = view.get("passage_freshness", {})
    if freshness.get("affected") or freshness.get("unresolved"):
        lines.extend([export_text.passage_freshness_sentence(tr, len(freshness["affected"]), len(freshness["unresolved"])), ""])

    sections = sorted(view["sections"], key=lambda item: DISPLAY_ORDER.index(item["section_id"])
                      if item["section_id"] in DISPLAY_ORDER else len(DISPLAY_ORDER))
    equations: dict[str, int] = {}
    for section in sections:
        for claim in section["claims"]:
            ref = claim.get("equation_ref")
            if ref and ref not in equations:
                equations[ref] = len(equations) + 1
    for section in sections:
        sid = section["section_id"]
        heading = export_text.heading(sid, tr)
        lines.extend([f"## {_md(heading)}", ""])
        if section["status"] in ("draft", "failed"):
            lines.extend([f"> {export_text.section_unvalidated_note(tr)}", ""])
        if sid == "VI":
            lines.extend([export_text.vi_preface(tr), ""])
        claims = section["claims"]
        has_table_ref = any(claim.get("table_ref") == "TABLE_I" for claim in claims)
        table = view.get("table_i") if sid == "IV" else None
        if table and not has_table_ref:
            lines.extend([_table(table, tr), ""])
        if sid in ("II", "VIII") and section.get("draft") and section["draft"].get("text"):
            lines.extend([_md(section["draft"]["text"]), ""])
        paragraphs = dict.fromkeys(claim["paragraph"] for claim in claims)
        first_table_paragraph = next((claim["paragraph"] for claim in claims if claim.get("table_ref") == "TABLE_I"), None)
        for paragraph in paragraphs:
            fragments = []
            for claim in (claim for claim in claims if claim["paragraph"] == paragraph):
                fragment = _md(claim["text"])
                if claim.get("equation_ref"):
                    fragment += f' ({equations[claim["equation_ref"]]})'
                links = list(dict.fromkeys(link["ref_number"] for link in claim["evidence"]))
                if links:
                    fragment += " " + ", ".join(f"[{number}]" for number in links)
                fragments.append(fragment)
            lines.extend([" ".join(fragments), ""])
            if table and paragraph == first_table_paragraph:
                lines.extend([_table(table, tr), ""])
        if not claims and not (sid in ("II", "VIII") and (section.get("draft") or {}).get("text")):
            reasons = (section.get("draft") or {}).get("insufficient_evidence") or []
            if reasons:
                for entry in reasons:
                    lines.extend([f"{export_text.not_enough_evidence_label(tr)}: {_md(entry['reason'])}", ""])
            else:
                lines.extend([export_text.no_text_sentence(tr), ""])

    lines.extend([f"## {export_text.references_heading(tr)}", ""])
    for ref in view["references"]:
        authors = ", ".join(_md(author) for author in ref["authors"])
        fields = [part for part in (authors, _md(ref["title"])) if part]
        fields.extend(_md(ref[key]) for key in ("venue", "year") if ref.get(key))
        if ref.get("doi"):
            fields.append(f'DOI: {_md(ref["doi"])}')
        if ref.get("version_label"):
            fields.append(f'({_md(ref["version_label"])})')
        lines.extend([f'[{ref["number"]}] ' + ", ".join(fields), ""])
    lines.extend([export_text.corpus_footer(corpus, tr), ""])
    anchor = export_text.anchor_note(view, tr)
    review_note = export_text.review_note(view, tr, _md)
    lines.extend([f"{anchor} {review_note}", ""])
    review = view.get("review")
    if review and review["status"] == "reviewed" and review["findings"]:
        lines.extend([export_text.findings_heading(tr), ""])
        for finding in review["findings"]:
            section_label, code_label, text = export_text.finding_fields(finding, tr, _md)
            lines.append(f'- {section_label} · {code_label} · {text}')
    return "\n".join(lines).rstrip("\n") + "\n"


def export_markdown(store: Store, research_id: str, report_id: str) -> tuple[str, str]:
    from deixis.workflow.views import report_view

    view = report_view(store, research_id, report_id)
    export_text.ensure_report_finished(view)
    title = store.research(research_id)["title"]
    try:
        corpus = ReportStore(store).snapshot(report_id)["corpus"]
    except NotFound:
        corpus = None
    return to_markdown(view, title=title, corpus=corpus), export_text.report_stem(view, title) + ".md"

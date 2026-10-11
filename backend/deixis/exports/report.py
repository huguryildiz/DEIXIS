"""The evidence report as DOCX: the Markdown export (workflow/report/export.py `to_markdown`) block for block.

It reads the same report view and corpus and takes every sentence from the shared `export_text` helpers, so the
headings, claims, reference numbers, Table I, references and closing notes match the Markdown and LaTeX files. Stored
text goes in as plain text (whitespace collapsed, as the Markdown writer does); `$...$` math stays as written.
"""

from __future__ import annotations

from typing import Any

from deixis.exports import ooxml
from deixis.workflow.report import export_text
from deixis.workflow.report.store import DISPLAY_ORDER, ReportStore
from deixis.workflow.store import NotFound, Store


def plain(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _table(table: dict[str, Any], tr: bool) -> list[ooxml.Block]:
    columns = table["columns"]
    cells = {(cell["source_version_id"], cell["column_id"]): cell for cell in table["cells"]}
    body = tuple(tuple([export_text.source_cell(row, tr, plain)] + [
        export_text.cell_text(cells.get((row["source_version_id"], column["column_id"])), column, tr, plain)
        for column in columns]) for row in table["rows"])
    header = (plain(export_text.source_heading(tr)), *(plain(column["name"]) for column in columns))
    return [ooxml.paragraph(export_text.table_caption(table, tr), style="Small"),
            ooxml.Table(header, body, (1.4,) + (2.0,) * len(columns))]


def blocks(view: dict[str, Any], *, title: str, corpus: dict[str, int] | None) -> list[ooxml.Block]:
    tr = export_text.is_turkish(view)
    out: list[ooxml.Block] = []
    draft = export_text.draft_line(view, tr)
    if draft is not None:
        out.append(ooxml.paragraph(plain(draft), style="Quote"))
    out += [ooxml.heading(0, plain(title)), ooxml.paragraph(export_text.report_identity(view, tr))]
    missing = view.get("missing_rows")
    if missing:
        out.append(ooxml.paragraph(export_text.missing_rows_sentence(missing, tr)))
        rows = [export_text.missing_row_fields(row, tr, plain) for row in missing["failed_rows"]]
        if rows:
            out.append(ooxml.bullets([f"{source}: {reason}"] for source, reason in rows))
    edit = export_text.edit_note(view, tr, plain)
    if edit is not None:
        out.append(ooxml.paragraph(edit.paragraph))
        if edit.not_checked_heading is not None:
            if edit.items:
                out.append(ooxml.bullets([f"{sid} · {rule} ({severity}): {detail}"] for sid, rule, severity, detail in edit.items))
            out.append(ooxml.paragraph(edit.not_checked_heading))
            later = [f"{sid} · {key}: {rule} ({reason})" for sid, key, rule, reason in edit.skipped_rules] + list(edit.not_checked)
            if later:
                out.append(ooxml.bullets([item] for item in later))
    if view.get("evidence_changes", {}).get("any"):
        out.append(ooxml.paragraph(export_text.evidence_changed_sentence(tr)))
    freshness = view.get("passage_freshness", {})
    if freshness.get("affected") or freshness.get("unresolved"):
        out.append(ooxml.paragraph(export_text.passage_freshness_sentence(tr, len(freshness["affected"]), len(freshness["unresolved"]))))

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
        out.append(ooxml.heading(1, plain(export_text.heading(sid, tr))))
        if section["status"] in ("draft", "failed"):
            out.append(ooxml.paragraph(export_text.section_unvalidated_note(tr), style="Quote"))
        if sid == "VI":
            out.append(ooxml.paragraph(export_text.vi_preface(tr)))
        claims = section["claims"]
        table = view.get("table_i") if sid == "IV" else None
        if table and not any(claim.get("table_ref") == "TABLE_I" for claim in claims):
            out += _table(table, tr)
        if sid in ("II", "VIII") and section.get("draft") and section["draft"].get("text"):
            out.append(ooxml.paragraph(plain(section["draft"]["text"])))
        first_table_paragraph = next((claim["paragraph"] for claim in claims if claim.get("table_ref") == "TABLE_I"), None)
        for number in dict.fromkeys(claim["paragraph"] for claim in claims):
            fragments = []
            for claim in (claim for claim in claims if claim["paragraph"] == number):
                fragment = plain(claim["text"])
                if claim.get("equation_ref"):
                    fragment += f' ({equations[claim["equation_ref"]]})'
                links = list(dict.fromkeys(link["ref_number"] for link in claim["evidence"]))
                if links:
                    fragment += " " + ", ".join(f"[{ref}]" for ref in links)
                fragments.append(fragment)
            out.append(ooxml.paragraph(" ".join(fragments)))
            if table and number == first_table_paragraph:
                out += _table(table, tr)
        if not claims and not (sid in ("II", "VIII") and (section.get("draft") or {}).get("text")):
            reasons = (section.get("draft") or {}).get("insufficient_evidence") or []
            if reasons:
                out += [ooxml.paragraph(f"{export_text.not_enough_evidence_label(tr)}: {plain(entry['reason'])}") for entry in reasons]
            else:
                out.append(ooxml.paragraph(export_text.no_text_sentence(tr)))

    out.append(ooxml.heading(1, export_text.references_heading(tr)))
    for ref in view["references"]:
        fields = [part for part in (", ".join(plain(author) for author in ref["authors"]), plain(ref["title"])) if part]
        fields.extend(plain(ref[key]) for key in ("venue", "year") if ref.get(key))
        if ref.get("doi"):
            fields.append(f'DOI: {plain(ref["doi"])}')
        if ref.get("version_label"):
            fields.append(f'({plain(ref["version_label"])})')
        out.append(ooxml.paragraph(f'[{ref["number"]}] ' + ", ".join(fields)))
    out += [ooxml.paragraph(export_text.corpus_footer(corpus, tr), style="Small"),
            ooxml.paragraph(f"{export_text.anchor_note(view, tr)} {export_text.review_note(view, tr, plain)}", style="Small")]
    review = view.get("review")
    if review and review["status"] == "reviewed" and review["findings"]:
        out += [ooxml.paragraph(export_text.findings_heading(tr)),
                ooxml.bullets([" · ".join(export_text.finding_fields(finding, tr, plain))] for finding in review["findings"])]
    return out


def export_docx(store: Store, research_id: str, report_id: str) -> tuple[bytes, str]:
    """The DOCX bytes and file name; refuses an unfinished report as the Markdown export does."""
    from deixis.workflow.views import report_view

    view = report_view(store, research_id, report_id)
    export_text.ensure_report_finished(view)
    title = store.research(research_id)["title"]
    try:
        corpus = ReportStore(store).snapshot(report_id)["corpus"]
    except NotFound:
        corpus = None
    return ooxml.docx(blocks(view, title=title, corpus=corpus), title=title), export_text.report_stem(view, title) + ".docx"

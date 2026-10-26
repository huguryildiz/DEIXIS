"""The evidence report as DOCX: the Markdown export (workflow/features/report/report_export.py `to_markdown`) block for block.

It reads the same report view and corpus and takes every sentence from the shared `export_text` helpers, so the
headings, claims, reference numbers, Table I, references and closing notes match the Markdown and LaTeX files. Stored
text goes in as plain text (whitespace collapsed, as the Markdown writer does); `$...$` math stays as written.

After them comes an evidence appendix the Markdown does not have: every current citation of every claim, with its
stored anchor quote verbatim and its locator read from the cited passage's stored record (kind, physical page, printed
label). A Table I cell citation names the column and the frozen evidence passage its quote was located in; a quote
that was not located is said to be so, never given a page.
"""

from __future__ import annotations

from typing import Any

from deixis.documents.jats import RENDITION_SQL
from deixis.exports import ooxml
from deixis.exports.text import OCR_LABEL, locator_text, translator
from deixis.workflow.features.report import report_export_text as export_text
from deixis.workflow.features.report.report_store import DISPLAY_ORDER, ReportStore
from deixis.workflow.run.store import NotFound, Store


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


def _appendix(view: dict[str, Any], sections: list[dict[str, Any]], locators: dict[str, dict[str, Any]], tr: bool) -> list[ooxml.Block]:
    pick = export_text.pick
    t = translator("tr" if tr else "en")
    table = view.get("table_i") or {}
    columns = {column["column_id"]: column["name"] for column in table.get("columns") or []}
    cell_columns = {cell["cell_id"]: columns.get(cell["column_id"], "") for cell in table.get("cells") or []}

    def place(passage_id: str | None) -> str:
        record = locators.get(passage_id or "")
        if record is None:
            return ""
        text = locator_text(t, record)
        if record.get("text_source") == "ocr":
            text += f" ({t(OCR_LABEL)})"
        if record.get("text_source") == "latex_source":
            text += f" ({t('arXiv source')})"
        if record.get("text_source") == "equation_ocr":
            text += f" ({t('equations read from the page image')})"
        return text

    out: list[ooxml.Block] = []
    for section in sections:
        cited = [claim for claim in section["claims"] if claim["evidence"]]
        if not cited:
            continue
        out.append(ooxml.heading(3, plain(export_text.heading(section["section_id"], tr))))
        for claim in cited:
            out.append(ooxml.paragraph(plain(claim["text"]), style="Small"))
            items = []
            for link in claim["evidence"]:
                quote = f'“{link["anchor_text"]}”' if link.get("anchor_text") else pick("no quote stored", tr, "kayıtlı alıntı yok")
                parts = [f'[{link["ref_number"]}] {quote}']
                if link.get("cell_id"):
                    parts.append(f'{pick("Table I", tr, "Tablo I")}, {plain(cell_columns.get(link["cell_id"], ""))}'.rstrip(", "))
                    parts.append(place(link.get("open_passage_id")) or pick(
                        "quote not located in the cell's evidence passages", tr, "alıntı hücrenin kanıt pasajlarında bulunamadı"))
                else:
                    parts.append(place(link.get("passage_id")))
                    if link.get("anchor_match") is None and link.get("anchor_text"):
                        parts.append(pick("quote not located in the passage", tr, "alıntı pasajda bulunamadı"))
                items.append([" — ".join(part for part in parts if part)])
            out.append(ooxml.bullets(items))
    if not out:
        return []
    return [ooxml.heading(1, pick("Evidence appendix", tr, "Kanıt eki")),
            ooxml.paragraph(pick("Each current citation with its stored anchor quote, verbatim, and where the quote sits: the page "
                                 "of the cited passage, or the Table I cell and the evidence passage the quote was located in.", tr,
                                 "Her güncel atıf, kayıtlı çapa alıntısıyla (olduğu gibi) ve alıntının yeriyle: atıf yapılan "
                                 "pasajın sayfası ya da Tablo I hücresi ve alıntının bulunduğu kanıt pasajı."), style="Small"),
            *out]


def passage_locators(store: Store, view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Kind, page, printed label, text source and rendition of every passage the report's citations point at."""
    ids = sorted({pid for section in view["sections"] for claim in section["claims"] for link in claim["evidence"]
                  for pid in (link.get("passage_id"), link.get("open_passage_id")) if pid})
    if not ids:
        return {}
    rows = store.conn.execute(
        f"SELECT p.id, p.kind, p.physical_page, p.printed_label, p.text_source, {RENDITION_SQL} AS rendition"
        f" FROM passages p LEFT JOIN source_assets a ON a.id = p.asset_id WHERE p.id IN ({', '.join('?' * len(ids))})", ids)
    return {row["id"]: dict(row) | {"rendition": bool(row["rendition"])} for row in rows}


def blocks(view: dict[str, Any], *, title: str, corpus: dict[str, int] | None,
           locators: dict[str, dict[str, Any]] | None = None) -> list[ooxml.Block]:
    tr = export_text.is_turkish(view)
    out: list[ooxml.Block] = []
    draft = export_text.draft_line(view, tr)
    if draft is not None:
        out.append(ooxml.paragraph(plain(draft), style="Quote"))
    out += [ooxml.heading(0, plain(title)), ooxml.paragraph(export_text.report_identity(view, tr))]
    if basis := view.get("basis"):
        out.append(ooxml.paragraph(export_text.basis_note(basis, tr)))
        named = [export_text.basis_source_fields(row, tr, plain) for row in basis["unverified_sources"]]
        if named:
            out.append(ooxml.bullets([f"{source}: {count}"] for source, count in named))
        if basis.get("abstract_members"):
            out.append(ooxml.bullets([export_text.abstract_member_field(row, tr, plain)] for row in basis["abstract_members"]))
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
            out.append(ooxml.paragraph(*ooxml.with_math(plain(section["draft"]["text"]))))
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
                fragment += export_text.claim_depth_mark(claim, tr)
                fragments.append(fragment)
            out.append(ooxml.paragraph(*ooxml.with_math(" ".join(fragments))))
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
        note = (f'. {export_text.abstract_reference_note(tr)}' if ref.get("abstract_only")
                else f'. {export_text.full_text_reference_note(tr)}' if ref.get("full_text_read") else "")
        out.append(ooxml.paragraph(f'[{ref["number"]}] ' + ", ".join(fields) + note, style="Bibliography"))
    out += [ooxml.paragraph(export_text.corpus_footer(corpus, tr), style="Small"),
            ooxml.paragraph(f"{export_text.anchor_note(view, tr)} {export_text.review_note(view, tr, plain)}", style="Small")]
    review = view.get("review")
    if review and review["status"] == "reviewed" and review["findings"]:
        out += [ooxml.paragraph(export_text.findings_heading(tr)),
                ooxml.bullets([" · ".join(export_text.finding_fields(finding, tr, plain))] for finding in review["findings"])]
    return out + _appendix(view, sections, locators or {}, tr)


def export_docx(store: Store, research_id: str, report_id: str) -> tuple[bytes, str]:
    """The DOCX bytes and file name; refuses an unfinished report as the Markdown export does."""
    from deixis.workflow.run.views import report_view

    view = report_view(store, research_id, report_id)
    export_text.ensure_report_finished(view)
    title = store.research(research_id)["title"]
    try:
        corpus = ReportStore(store).snapshot(report_id)["corpus"]
    except NotFound:
        corpus = None
    data = ooxml.docx(blocks(view, title=title, corpus=corpus, locators=passage_locators(store, view)), title=title)
    return data, export_text.report_stem(view, title) + ".docx"

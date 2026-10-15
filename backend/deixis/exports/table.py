"""The evidence table as XLSX and DOCX: the browser's CSV download (EvidenceTable.tsx `tableCsv`) plus what the grid
and the cell panel say about each cell.

Same rows, columns and values as the CSV, in the same order and language: current values only, proposals waiting for a
decision left out, each quote with its locator as stored. Each cell also carries what the CSV leaves out:
- its source line, as the grid draws it: who wrote the value, how deep the text it read went, and "no linked evidence"
  for a value recorded without a passage;
- its stored state, written out (a value without linked evidence is never shown as an ordinary value);
- its warnings, in the cell panel's sentences: the column changed since, a cited PDF removed or replaced, an earlier
  text extraction, a number read only from OCR text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deixis.exports import ooxml
from deixis.exports.text import CitationStyle, Language, Translate, download_name, locator_text, number_text, \
    reference_text, translator, version_text

ACCESS = {"pdf_available": "PDF text", "abstract": "Abstract only", "metadata": "Metadata only"}
STATES = {"value": "Value", "not_verified": "Value without linked evidence", "unknown": "Unclear in the source",
          "not_reported": "Not reported", "not_applicable": "Not applicable", "inaccessible": "No text",
          "not_found_in_inspected_scope": "Not found in the text read"}
AUTHORS = {"model": "Model", "human": "You", "system": "System"}
DEPTHS = {"metadata": "Metadata", "abstract": "Abstract", "selected_sections": "Selected pages", "full_text": "Full text"}
# EvidenceTable.tsx cell panel, in its order. Proposal flags are left out with the proposals themselves.
WARNINGS = (
    ("stale_column", "Made under an earlier definition of this column (revision {old}). It stays until you edit it or use a newer proposal."),
    ("pdf_removed", "A PDF this value cites was removed from the source. The cited passages still open as text; the PDF view is off."),
    ("pdf_replaced", "This value cites a PDF that was later replaced. Its evidence still opens the previous file; a recheck reads the current file."),
    ("ocr_numbers_unchecked", "This value states a number or equation read only from OCR text of a scanned page. It was not checked against the page; open the evidence and compare it with the PDF."),
    ("text_superseded", "This value cites an earlier text extraction of the PDF. Its evidence still opens that text; a recheck reads the current extraction."),
)
INFO_WIDTHS = (12.0, 50.0, 40.0, 30.0, 6.0, 18.0, 14.0)
PER_COLUMN = ("", "{name} — evidence", "{name} — source", "{name} — state", "{name} — warnings")


@dataclass(frozen=True)
class CellText:
    value: str | int | float  # the CSV's value text; a bare number stays a number
    evidence: tuple[str, ...]  # one "“quote” — locator" per evidence item, as stored
    source: str                # the grid's source line
    state: str                 # the stored state, written out; empty for an empty cell
    stored_state: str | None
    warnings: tuple[str, ...]


def filename(view: dict[str, Any], extension: str) -> str:
    return download_name(view["table"]["title"], f"V{view['table']['version']}", extension=extension, fallback="Evidence table")


def _value(t: Translate, language: Language, column: dict[str, Any], value: dict[str, Any] | None) -> str | int | float:
    if not value:
        return ""
    if value.get("option_ids") is not None:
        labels = {option["id"]: option["label"] for option in column.get("options") or []}
        return ", ".join(labels.get(item, item) for item in value["option_ids"])
    number = value.get("number")
    if isinstance(number, (int, float)) and not isinstance(number, bool):
        return number if not value.get("unit") else f"{number_text(number, language)} {value['unit']}"
    if value.get("answer"):
        return t("Yes" if value["answer"] == "yes" else "No")
    return value.get("text") or ""


def _cell(t: Translate, language: Language, column: dict[str, Any], summary: dict[str, Any] | None) -> CellText:
    current = (summary or {}).get("current")
    if not current:
        return CellText("", (), "", "", None, ())
    state = current.get("state")
    value = _value(t, language, column, current.get("value")) if state in ("value", "not_verified") \
        else t(STATES[state]) if state else ""
    evidence = tuple(" — ".join(part for part in (f"“{e['anchor_text']}”" if e.get("anchor_text") else "", locator_text(t, e)) if part)
                     for e in current.get("evidence") or [])
    depth = current.get("reading_depth")
    source = " · ".join(part for part in (t(AUTHORS.get(current.get("author"), current.get("author") or "")),
                                          t(DEPTHS[depth]) if depth else "",
                                          t("no linked evidence") if state == "not_verified" else "") if part)
    flags = set((summary or {}).get("flags") or [])
    warnings = tuple(t(text, old=current.get("column_revision")) for flag, text in WARNINGS if flag in flags)
    return CellText(value, evidence, source, t(STATES[state]) if state in STATES else (state or ""), state, warnings)


def rows(view: dict[str, Any], sources: list[dict[str, Any]], *, language: Language, style: CitationStyle):
    """(info header, column names, rows); a row is (seven info cells, one CellText per column)."""
    t = translator(language)
    by_id = {s["source_version_id"]: s for s in sources}
    cells = {(c["column_id"], c["source_version_id"]): c for c in view["cells"]}
    columns = view["columns"]
    header = [t("Key"), t("Reference"), t("Title"), t("Authors"), t("Year"), t("Version"), t("Access")]
    out = []
    for row in view["rows"]:
        source = by_id.get(row["source_version_id"])
        info = [row.get("source_key") or "", reference_text(style, source) if source else "", row["title"],
                "; ".join(row.get("authors") or []), row.get("year"), version_text(t, row.get("version_label")),
                t(ACCESS[row["access_level"]])]
        out.append((info, [_cell(t, language, column, cells.get((column["id"], row["source_version_id"]))) for column in columns]))
    return header, [column["name"] for column in columns], out


def xlsx(view: dict[str, Any], sources: list[dict[str, Any]], *, language: Language, style: CitationStyle) -> bytes:
    t = translator(language)
    info_header, names, data = rows(view, sources, language=language, style=style)
    header = info_header + [t(label, name=name) if label else name for name in names for label in PER_COLUMN]
    body = tuple(tuple(info) + tuple(item for cell in cells for item in
                                     (cell.value, " | ".join(cell.evidence), cell.source, cell.state, " | ".join(cell.warnings)))
                 for info, cells in data)
    widths = INFO_WIDTHS + (24.0, 50.0, 18.0, 18.0, 40.0) * len(names)
    return ooxml.xlsx([ooxml.Sheet(view["table"]["title"], tuple(header), body, widths)], title=view["table"]["title"])


def docx(view: dict[str, Any], sources: list[dict[str, Any]], *, language: Language, style: CitationStyle) -> bytes:
    t = translator(language)
    info_header, names, data = rows(view, sources, language=language, style=style)
    body = []
    for info, cells in data:
        row: list[Any] = ["" if item is None else str(item) for item in info]
        for cell in cells:
            text = number_text(cell.value, language) if isinstance(cell.value, (int, float)) else cell.value
            # A state other than a plain value is named on its own line unless the value text already is that name.
            state = [ooxml.paragraph(t("State: {state}", state=cell.state), style="Small")] \
                if cell.stored_state not in (None, "value") and cell.state != text else []
            row.append([ooxml.paragraph(text), *([ooxml.paragraph(cell.source, style="Small")] if cell.source else []), *state,
                        *(ooxml.paragraph(ooxml.Run(w, bold=True), style="Small") for w in cell.warnings),
                        *(ooxml.paragraph(item, style="Small") for item in cell.evidence)])
        body.append(tuple(row))
    table = ooxml.Table(tuple(info_header + names), tuple(body), (1.0, 3.0, 2.4, 1.8, 0.6, 1.2, 1.0) + (2.6,) * len(names))
    return ooxml.docx([ooxml.heading(0, view["table"]["title"]), table], title=view["table"]["title"], landscape=True)

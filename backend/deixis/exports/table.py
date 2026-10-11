"""The evidence table as XLSX and DOCX: the browser's CSV download (EvidenceTable.tsx `tableCsv`) plus a source line.

Same rows, columns, values and states as the CSV, in the same order and language: current values only, proposals
waiting for a decision left out, each quote with its locator as stored. Each cell also gets its source line, the
"Model · Full text" line of the grid: who wrote the current value and how deep the text it read went.
"""

from __future__ import annotations

from typing import Any

from deixis.exports import ooxml
from deixis.exports.text import CitationStyle, Language, Translate, file_base, locator_text, number_text, \
    reference_text, translator, version_text

ACCESS = {"pdf_available": "PDF text", "abstract": "Abstract only", "metadata": "Metadata only"}
STATES = {"value": "Value", "not_verified": "Value without linked evidence", "unknown": "Unclear in the source",
          "not_reported": "Not reported", "not_applicable": "Not applicable", "inaccessible": "No text",
          "not_found_in_inspected_scope": "Not found in the text read"}
AUTHORS = {"model": "Model", "human": "You", "system": "System"}
DEPTHS = {"metadata": "Metadata", "abstract": "Abstract", "selected_sections": "Selected pages", "full_text": "Full text"}
INFO_WIDTHS = (12.0, 50.0, 40.0, 30.0, 6.0, 18.0, 14.0)


def filename(view: dict[str, Any], extension: str) -> str:
    return f"{file_base(view['table']['title'], 'evidence-table')}-v{view['table']['version']}.{extension}"


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


def _cell(t: Translate, language: Language, column: dict[str, Any], current: dict[str, Any] | None) \
        -> tuple[str | int | float, list[str], str]:
    """(value or state, one 'quote — locator' text per evidence item, source line); empty when the cell has no value."""
    if not current:
        return "", [], ""
    state = current.get("state")
    value = _value(t, language, column, current.get("value")) if state in ("value", "not_verified") \
        else t(STATES[state]) if state else ""
    evidence = [" — ".join(part for part in (f"“{e['anchor_text']}”" if e.get("anchor_text") else "", locator_text(t, e)) if part)
                for e in current.get("evidence") or []]
    depth = current.get("reading_depth")
    source = " · ".join(part for part in (t(AUTHORS.get(current.get("author"), current.get("author") or "")),
                                          t(DEPTHS[depth]) if depth else "") if part)
    return value, evidence, source


def rows(view: dict[str, Any], sources: list[dict[str, Any]], *, language: Language, style: CitationStyle):
    """(info header, column names, rows); a row is (seven info cells, one (value, evidence, source line) per column)."""
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
        values = [_cell(t, language, column, (cells.get((column["id"], row["source_version_id"])) or {}).get("current"))
                  for column in columns]
        out.append((info, values))
    return header, [column["name"] for column in columns], out


def xlsx(view: dict[str, Any], sources: list[dict[str, Any]], *, language: Language, style: CitationStyle) -> bytes:
    t = translator(language)
    info_header, names, data = rows(view, sources, language=language, style=style)
    header = info_header + [label for name in names for label in
                            (name, t("{name} — evidence", name=name), t("{name} — source", name=name))]
    body = tuple(tuple(info) + tuple(item for value, evidence, source in values for item in (value, " | ".join(evidence), source))
                 for info, values in data)
    widths = INFO_WIDTHS + (24.0, 50.0, 18.0) * len(names)
    return ooxml.xlsx([ooxml.Sheet(view["table"]["title"], tuple(header), body, widths)], title=view["table"]["title"])


def docx(view: dict[str, Any], sources: list[dict[str, Any]], *, language: Language, style: CitationStyle) -> bytes:
    info_header, names, data = rows(view, sources, language=language, style=style)
    body = []
    for info, values in data:
        cells: list[Any] = ["" if item is None else str(item) for item in info]
        for value, evidence, source in values:
            text = number_text(value, language) if isinstance(value, (int, float)) else value
            cells.append([ooxml.paragraph(text), *([ooxml.paragraph(source, style="Small")] if source else []),
                          *(ooxml.paragraph(item, style="Small") for item in evidence)])
        body.append(tuple(cells))
    table = ooxml.Table(tuple(info_header + names), tuple(body), (1.0, 3.0, 2.4, 1.8, 0.6, 1.2, 1.0) + (2.6,) * len(names))
    return ooxml.docx([ooxml.heading(0, view["table"]["title"]), table], title=view["table"]["title"], landscape=True)

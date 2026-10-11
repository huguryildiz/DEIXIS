"""DOCX and XLSX exports (S18): SYNTHETIC records only; no provider or real model is called.

The files are checked by reading them back with zipfile and ElementTree: the parts a reader needs, well-formed XML,
the same text as the Markdown or CSV export, anchors and locators as stored, and no secrets or local paths.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from deixis.exports import answer as answer_export
from deixis.exports import ooxml
from deixis.exports import report as report_export
from deixis.exports import table as table_export
from deixis.exports.text import SERVER_ONLY, TR, number_text, reference_text
from deixis.workflow.report.export import export_markdown
from test_api_flow import app_for, attached_research, create, session, wait_run
from test_report_api import create_table, fill_table, upload_and_include
from test_report_export import complete
from test_report_flow import ReportAdapter

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SPECIAL = "A & B < C > D \"q\" 'a' 🧪 İstanbul ğüşöçı ĞÜŞÖÇ $\\alpha_{1} < \\beta^{2}$ \\& x"
DOCX_PARTS = {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/_rels/document.xml.rels",
              "word/styles.xml", "word/numbering.xml", "docProps/core.xml"}
XLSX_PARTS = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml",
              "xl/worksheets/sheet1.xml", "docProps/core.xml"}


# ---- reading the files back ----------------------------------------------------------------------------------------

def parts(data: bytes, required: set[str]) -> dict[str, ET.Element]:
    """Every part parsed; fails on a bad zip, a missing part or XML that is not well formed."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert names[0] == "[Content_Types].xml"
        assert required <= set(names), required - set(names)
        parsed = {name: ET.fromstring(archive.read(name)) for name in names}
    types = parsed["[Content_Types].xml"]
    overrides = {item.get("PartName") for item in types if item.tag.endswith("Override")}
    assert overrides == {"/" + name for name in names if not name.endswith(".rels") and name != "[Content_Types].xml"}
    return parsed


def raw_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())


def _p_text(p: ET.Element) -> str:
    out = []
    for node in p.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "br":
            out.append("\n")
        elif node.tag == W + "tab":
            out.append("\t")
    return "".join(out)


def docx_items(data: bytes) -> list:
    """Body in order: a paragraph is its text, a table is a list of rows, a row a list of cell texts."""
    body = parts(data, DOCX_PARTS)["word/document.xml"].find(W + "body")
    items: list = []
    for child in body:
        if child.tag == W + "p":
            text = _p_text(child)
            if text:
                items.append(text)
        elif child.tag == W + "tbl":
            items.append([["\n".join(_p_text(p) for p in cell.findall(W + "p")) for cell in row.findall(W + "tc")]
                          for row in child.findall(W + "tr")])
    return items


def xlsx_rows(data: bytes) -> list[list]:
    sheet = parts(data, XLSX_PARTS)["xl/worksheets/sheet1.xml"]
    rows = []
    for row in sheet.find(S + "sheetData"):
        values = {}
        for cell in row:
            column = re.match(r"[A-Z]+", cell.get("r")).group(0)
            index = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(column))) - 1
            if cell.get("t") == "inlineStr":
                values[index] = "".join(t.text or "" for t in cell.iter(S + "t"))
            else:
                number = cell.find(S + "v").text
                values[index] = int(number) if re.fullmatch(r"-?\d+", number) else float(number)
        rows.append([values.get(i, "") for i in range(max(values, default=-1) + 1)])
    return rows


def assert_clean(data: bytes, tmp_path: Path) -> None:
    text = raw_text(data)
    for secret in (str(tmp_path), "/Users/", "/private/", "/tmp/", "Application Support", "deixis_csrf", "csrf",
                   "api_key", "API_KEY", "sk-", "Bearer"):
        assert secret not in text, secret


# ---- the writer --------------------------------------------------------------------------------------------------

def test_docx_writer_blocks_escaping_and_determinism():
    blocks = [ooxml.heading(0, SPECIAL), ooxml.paragraph("plain ", ooxml.Run("bold", bold=True), " ", ooxml.Run("it", italic=True)),
              ooxml.heading(2, "Section ğ"), ooxml.paragraph("quoted\x00\x07\x1b ok", style="Quote"),
              ooxml.bullets([["one"], ["two ", ooxml.Run("&", bold=True)]]), ooxml.bullets([["first"], ["second"]], ordered=True),
              ooxml.bullets([["again"]], ordered=True), ooxml.Rule(),
              ooxml.Table(("Key", "Value <x>"), (("k1", [ooxml.paragraph("v1"), ooxml.paragraph("src", style="Small")]),
                                                ("k2 & k3", "line\nbreak\ttab")), (1.0, 3.0)),
              ooxml.paragraph("lone \ud800 surrogate")]
    data = ooxml.docx(blocks, title=SPECIAL)
    assert data == ooxml.docx(blocks, title=SPECIAL)
    parsed = parts(data, DOCX_PARTS)
    assert parsed["docProps/core.xml"][0].text == SPECIAL
    assert docx_items(data) == [SPECIAL, "plain bold it", "Section ğ", "quoted ok", "one", "two &", "first", "second", "again",
                                [["Key", "Value <x>"], ["k1", "v1\nsrc"], ["k2 & k3", "line\nbreak\ttab"]], "lone  surrogate"]
    xml = raw_text(data)
    assert "A &amp; B &lt; C &gt; D" in xml and "\\alpha_{1} &lt; \\beta^{2}" in xml and "🧪" in xml
    numbering = parsed["word/numbering.xml"]
    nums = [n for n in numbering if n.tag == W + "num"]
    assert len(nums) == 3  # bullets + one restart per numbered list
    document = parsed["word/document.xml"]
    used = [p.find(f"{W}pPr/{W}numPr/{W}numId").get(W + "val") for p in document.iter(W + "p")
            if p.find(f"{W}pPr/{W}numPr") is not None]
    assert used == ["1", "1", "2", "2", "3"]
    landscape = parts(ooxml.docx(blocks, landscape=True), DOCX_PARTS)["word/document.xml"]
    size = landscape.find(f"{W}body/{W}sectPr/{W}pgSz")
    assert size.get(W + "orient") == "landscape" and int(size.get(W + "w")) > int(size.get(W + "h"))


def test_xlsx_writer_cells_names_and_limits():
    long = "x" * (ooxml.EXCEL_CELL_LIMIT + 10)
    sheets = [ooxml.Sheet("Table: a/b [c]*?", ("Key", "Year", SPECIAL), (("k1", 2020, SPECIAL), ("k2", None, 1.5), ("k3", 3, long))),
              ooxml.Sheet("table: A/B [C]*?", ("Only",), ())]
    data = ooxml.xlsx(sheets, title="SYNTHETIC")
    assert data == ooxml.xlsx(sheets, title="SYNTHETIC")
    parsed = parts(data, XLSX_PARTS | {"xl/worksheets/sheet2.xml"})
    names = [s.get("name") for s in parsed["xl/workbook.xml"].iter(S + "sheet")]
    assert names == ["Table  a b  c", "table  A B  C (2)"]
    rows = xlsx_rows(data)
    assert rows[0] == ["Key", "Year", SPECIAL]
    assert rows[1] == ["k1", 2020, SPECIAL] and rows[2] == ["k2", "", 1.5]
    assert len(rows[3][2]) == ooxml.EXCEL_CELL_LIMIT and rows[3][2].endswith("…")
    assert ooxml.column_name(0) == "A" and ooxml.column_name(25) == "Z" and ooxml.column_name(26) == "AA" and ooxml.column_name(701) == "ZZ"
    with pytest.raises(ValueError):
        ooxml.xlsx([])


def test_turkish_strings_match_the_interface_map():
    source = (Path(__file__).resolve().parents[2] / "apps/web/src/i18n.ts").read_text(encoding="utf-8")
    body = source[source.index("const tr: Record<string, string> = {"):]
    interface = {m.group(1).replace("\\'", "'"): m.group(2).replace("\\'", "'") for m in re.finditer(
        r"^\s*'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)',?\s*$", body, re.M)}
    assert {key: interface.get(key) for key in TR} == TR
    assert not set(SERVER_ONLY) & set(interface)


def test_number_and_reference_formats_follow_the_browser():
    assert number_text(1234567.5, "en") == "1,234,567.5" and number_text(1234567.5, "tr") == "1.234.567,5"
    assert number_text(0.1 + 0.2, "en") == "0.3" and number_text(-3, "tr") == "-3" and number_text(12, "en") == "12"
    source = {"title": "SYNTHETIC routing", "authors": ["Ada Lovelace", "Alan M. Turing"], "year": 2021, "venue": "J. Synth",
              "doi": "10.1/x", "landing_url": None, "publication_type": "article"}
    assert reference_text("apa", source) == "Lovelace, A., & Turing, A. M. (2021). SYNTHETIC routing. J. Synth. https://doi.org/10.1/x"
    assert reference_text("ieee", source) == "A. Lovelace and A. M. Turing, “SYNTHETIC routing,” J. Synth, 2021, doi: 10.1/x."
    assert reference_text("mla", source) == "Lovelace, Ada, and Alan M. Turing. “SYNTHETIC routing.” J. Synth, 2021 https://doi.org/10.1/x"
    assert reference_text("chicago", source) == "Lovelace, Ada, and Alan M. Turing. 2021. “SYNTHETIC routing.” J. Synth. https://doi.org/10.1/x."
    assert reference_text("apa", {"title": "a", "authors": [], "year": None}) == "a. (n.d.)."


# ---- answer report ---------------------------------------------------------------------------------------------

def _evidence(passage, source, key, **extra):
    return {"passage_id": passage, "source_version_id": source, "source_key": key, "kind": "pdf_page", "physical_page": 3,
            "printed_label": None, "title": "SYNTHETIC fallback title", "anchor_text": None, "text_source": "text_layer"} | extra


SYNTHETIC_ANSWER = {
    "status": "structurally_valid", "applicability": "stale_selection", "scope_revision": 2,
    "capability_notice": "SYNTHETIC notice & <tag>",
    "claims": [
        {"section": "Methods", "text": f"Claim one {SPECIAL}.", "support_type": "source_stated", "review": None,
         "evidence": [_evidence("p1", "s1", "Lov21", anchor_text="quote “one” & <two>"),
                      _evidence("p2", "s1", "Lov21", kind="abstract", physical_page=None, anchor_text="abstract quote")]},
        {"section": "Methods", "text": "Claim two.", "support_type": "analyst_inference",
         "review": {"verdict": "partially_supported", "reason": "SYNTHETIC reason"},
         "evidence": [_evidence("p3", "s2", None, physical_page=7, printed_label="iv", text_source="ocr", anchor_text="ocr quote")]},
        {"section": "Results", "text": "Claim three.", "support_type": "source_stated", "review": None,
         "evidence": [_evidence("p1", "s1", "Lov21", anchor_text="quote “one” & <two>")]},
    ],
    "limitations": [{"kind": "access", "text": "SYNTHETIC access limit.", "source_ids": ["s2"]},
                    {"kind": "conflicting_evidence", "text": "SYNTHETIC conflict.", "source_ids": []}],
    "unanswered_aspects": ["SYNTHETIC gap ğ"],
}
SYNTHETIC_SOURCES = [
    {"source_version_id": "s1", "title": "SYNTHETIC routing", "authors": ["Ada Lovelace"], "year": 2021, "venue": None,
     "doi": None, "landing_url": None, "publication_type": None, "origin": "provider", "access": {"assets": [{"id": "a"}]}},
    {"source_version_id": "s2", "title": "SYNTHETIC scan", "authors": [], "year": None, "venue": None, "doi": None,
     "landing_url": None, "publication_type": None, "origin": "provider", "access": {"assets": []}},
]
# What AnswerBlock.tsx `markdown()` returns for SYNTHETIC_ANSWER (APA, English), written out by hand.
SYNTHETIC_MARKDOWN = f"""# SYNTHETIC title
Report · V3
> Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.
> SYNTHETIC notice & <tag>
## Methods
Claim one {SPECIAL}. [Lov21, PDF p. 3][Lov21, abstract]
Claim two. [3] _(interpretation)_ _Reviewer: partly supported — SYNTHETIC reason_
## Results
Claim three. [Lov21]
## Not answered by the inspected passages
- SYNTHETIC gap ğ
## Limits
- **conflicting evidence:** SYNTHETIC conflict.
## Cited passages
[Lov21] Lovelace, A. (2021). SYNTHETIC routing. — PDF p. 3
[Lov21] Lovelace, A. (2021). SYNTHETIC routing. — abstract
[3] SYNTHETIC scan. (n.d.). — PDF p. 7 (printed iv) (OCR text · check against the page)
---
Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked."""


def _plain_markdown(markdown: str) -> list[str]:
    lines = []
    for line in markdown.splitlines():
        if not line or line == "---":
            continue
        line = re.sub(r"^(#+ |> |- )", "", line).replace("**", "")
        lines.append(re.sub(r"(^| )_(.+?)_(?= |$)", r"\1\2", line))
    return lines


def test_answer_docx_has_the_markdown_text_plus_anchors_in_order():
    data = ooxml.docx(answer_export.blocks(SYNTHETIC_ANSWER, SYNTHETIC_SOURCES, title="SYNTHETIC title", version=3,
                                           language="en", style="apa"))
    items = docx_items(data)
    first_lines = [item.split("\n")[0] for item in items]
    assert first_lines == _plain_markdown(SYNTHETIC_MARKDOWN)
    anchors = [item.split("\n")[1] for item in items if "\n" in item]
    assert anchors == ["“quote “one” & <two>”", "“abstract quote”", "“ocr quote”"]
    # The access limitation is shown with the PDF suggestions on screen, so neither file repeats it under Limits.
    assert "SYNTHETIC access limit." not in raw_text(data)
    turkish = docx_items(ooxml.docx(answer_export.blocks(SYNTHETIC_ANSWER, SYNTHETIC_SOURCES, title="T", version=3,
                                                         language="tr", style="ieee")))
    assert "Rapor · V3" in turkish and "Atıf yapılan pasajlar" in turkish and "Sınırlılıklar" in turkish
    assert "Claim one " + SPECIAL + ". [Lov21, PDF s. 3][Lov21, özet]" in turkish
    assert any(item.startswith("[3] “SYNTHETIC scan.” — PDF s. 7 (basılı iv) (OCR metni · sayfayla karşılaştırın)") for item in turkish)
    assert "Claim two. [3] (yorum) İnceleyici: kısmen destekleniyor — SYNTHETIC reason" in turkish


def test_answer_docx_route_names_refusals_and_content(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = attached_research(client)
        other = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid"
        path = f"/api/researches/{rid}/answers/{answer['id']}/export/docx"
        response = client.get(path + "?lang=en&style=apa")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == ooxml.DOCX_MEDIA_TYPE
        assert re.fullmatch(r'attachment; filename="[a-z0-9-]+-v1\.docx"', response.headers["content-disposition"])
        items = docx_items(response.content)
        assert items[0] == answer["report_title"] and items[1] == "Report · V1"
        evidence = [e for claim in answer["claims"] for e in claim["evidence"]]
        assert evidence and all(e["anchor_text"] for e in evidence)
        text = "\n".join(i for i in items if isinstance(i, str))
        for claim in answer["claims"]:
            assert claim["text"] in text
        for e in evidence:
            assert f"“{e['anchor_text']}”" in text and f"PDF p. {e['physical_page']}" in text
        assert_clean(response.content, tmp_path)
        assert client.get(path).content == response.content  # en/apa are the defaults
        assert "Rapor · V1" in docx_items(client.get(path + "?lang=tr").content)
        assert client.get(path + "?style=harvard").status_code == 422
        for bad in (f"/api/researches/{other}/answers/{answer['id']}/export/docx",
                    f"/api/researches/{rid}/answers/ans_unknown/export/docx",
                    f"/api/researches/res_unknown/answers/{answer['id']}/export/docx"):
            refused = client.get(bad)
            assert refused.status_code == 404 and "content-disposition" not in refused.headers
        store = raw.app.state.store
        later = store.create_run(rid, "answer", {}, None)["id"]
        store.update_run(later, status="completed")
        clarification = store.save_answer(rid, later, None, None, 1, "clarification", {"question": "Which network?"}, {})
        refused = client.get(f"/api/researches/{rid}/answers/{clarification}/export/docx")
        assert refused.status_code == 409 and "content-disposition" not in refused.headers


# ---- evidence table --------------------------------------------------------------------------------------------

SYNTHETIC_TABLE = {
    "table": {"title": "SYNTHETIC tablo ğ & <x>", "version": 4},
    "columns": [
        {"id": "c1", "name": "Size", "options": None},
        {"id": "c2", "name": "Kind", "options": [{"id": "o1", "label": "Fast"}, {"id": "o2", "label": "Slow"}]},
        {"id": "c3", "name": "Note", "options": None},
    ],
    "rows": [
        {"source_version_id": "s1", "source_key": "Lov21", "title": "SYNTHETIC routing", "authors": ["Ada Lovelace", "B C"],
         "year": 2021, "version_label": "acceptedVersion", "access_level": "pdf_available"},
        {"source_version_id": "s2", "source_key": None, "title": "SYNTHETIC scan", "authors": [], "year": None,
         "version_label": None, "access_level": "abstract"},
    ],
    "cells": [
        {"column_id": "c1", "source_version_id": "s1", "current": {
            "state": "value", "author": "model", "reading_depth": "full_text", "value": {"number": 1234.5, "unit": "kB"},
            "evidence": [{"anchor_text": "size is 1,234.5 kB", "kind": "pdf_page", "physical_page": 4, "printed_label": "12"},
                         {"anchor_text": None, "kind": "abstract", "physical_page": None, "printed_label": None}]}},
        {"column_id": "c2", "source_version_id": "s1", "current": {
            "state": "not_verified", "author": "human", "reading_depth": None, "value": {"option_ids": ["o2", "zz"]}, "evidence": []}},
        {"column_id": "c3", "source_version_id": "s1", "current": {
            "state": "value", "author": "model", "reading_depth": "abstract", "value": {"text": SPECIAL},
            "evidence": [{"anchor_text": SPECIAL, "kind": "abstract", "physical_page": None, "printed_label": None}]}},
        {"column_id": "c1", "source_version_id": "s2", "current": {
            "state": "value", "author": "model", "reading_depth": "abstract", "value": {"number": 7, "unit": None}, "evidence": []}},
        {"column_id": "c2", "source_version_id": "s2", "current": {
            "state": "not_reported", "author": "system", "reading_depth": "metadata", "value": None, "evidence": []},
         "pending_proposal": {"state": "value", "value": {"option_ids": ["o1"]}}},
        {"column_id": "c3", "source_version_id": "s2", "current": None},
    ],
}
# The rows EvidenceTable.tsx `tableCsv` writes for SYNTHETIC_TABLE (APA, English), written out by hand.
SYNTHETIC_CSV = [
    ["Key", "Reference", "Title", "Authors", "Year", "Version", "Access", "Size", "Size — evidence", "Kind", "Kind — evidence",
     "Note", "Note — evidence"],
    ["Lov21", "Lovelace, A. (2021). SYNTHETIC routing.", "SYNTHETIC routing", "Ada Lovelace; B C", "2021", "accepted manuscript",
     "PDF text", "1,234.5 kB", "“size is 1,234.5 kB” — PDF p. 4 (printed 12) | abstract", "Slow, zz", "", SPECIAL,
     f"“{SPECIAL}” — abstract"],
    ["", "SYNTHETIC scan. (n.d.).", "SYNTHETIC scan", "", "", "version not stated", "Abstract only", "7", "", "Not reported", "", "", ""],
]
SYNTHETIC_SOURCE_LINES = [["Model · Full text", "You", "Model · Abstract"], ["Model · Abstract", "System · Metadata", ""]]


def test_table_xlsx_is_the_csv_plus_source_columns():
    data = table_export.xlsx(SYNTHETIC_TABLE, SYNTHETIC_SOURCES, language="en", style="apa")
    rows = xlsx_rows(data)
    width = 7 + 3 * 3
    assert rows[0] == SYNTHETIC_CSV[0][:7] + [x for name in ("Size", "Kind", "Note")
                                              for x in (name, f"{name} — evidence", f"{name} — source")]
    for row, csv, lines in zip(rows[1:], SYNTHETIC_CSV[1:], SYNTHETIC_SOURCE_LINES):
        row = row + [""] * (width - len(row))
        # Numbers stay numbers in the workbook; the CSV writes their text.
        as_csv = [str(v) for v in row[:7]] + [str(row[7 + 3 * k + j]) for k in range(3) for j in (0, 1)]
        assert as_csv == csv
        assert [row[9 + 3 * k] for k in range(3)] == lines
    assert rows[1][4] == 2021 and rows[2][7] == 7
    workbook = parts(data, XLSX_PARTS)["xl/workbook.xml"]
    assert [s.get("name") for s in workbook.iter(S + "sheet")] == ["SYNTHETIC tablo ğ & <x>"]
    assert "Fast" not in raw_text(data)  # the proposal waiting for a decision is left out, as in the CSV
    turkish = xlsx_rows(table_export.xlsx(SYNTHETIC_TABLE, SYNTHETIC_SOURCES, language="tr", style="apa"))
    assert turkish[0][:7] == ["Anahtar", "Künye", "Başlık", "Yazarlar", "Yıl", "Sürüm", "Erişim"]
    assert turkish[0][9] == "Size — kaynak" and turkish[1][7] == "1.234,5 kB" and turkish[1][9] == "Model · Tam metin"
    assert turkish[1][8] == "“size is 1,234.5 kB” — PDF s. 4 (basılı 12) | özet" and turkish[2][10] == "Bildirilmemiş"


def test_table_docx_has_the_same_values_sources_and_quotes():
    data = table_export.docx(SYNTHETIC_TABLE, SYNTHETIC_SOURCES, language="en", style="apa")
    items = docx_items(data)
    assert items[0] == "SYNTHETIC tablo ğ & <x>"
    grid = items[1]
    assert grid[0] == SYNTHETIC_CSV[0][:7] + ["Size", "Kind", "Note"]
    assert grid[1][:7] == ["Lov21", "Lovelace, A. (2021). SYNTHETIC routing.", "SYNTHETIC routing", "Ada Lovelace; B C", "2021",
                           "accepted manuscript", "PDF text"]
    assert grid[1][7:] == ["1,234.5 kB\nModel · Full text\n“size is 1,234.5 kB” — PDF p. 4 (printed 12)\nabstract",
                           "Slow, zz\nYou", f"{SPECIAL}\nModel · Abstract\n“{SPECIAL}” — abstract"]
    assert grid[2][7:] == ["7\nModel · Abstract", "Not reported\nSystem · Metadata", ""]
    size = parts(data, DOCX_PARTS)["word/document.xml"].find(f"{W}body/{W}sectPr/{W}pgSz")
    assert size.get(W + "orient") == "landscape"


def test_table_routes_on_a_filled_synthetic_table(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached", effort="quick")
        other = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, rid)
        empty = create_table(client, rid, with_columns=False)
        table = create_table(client, rid, with_columns=True)
        fill_table(client, rid, table)
        view = client.get(f"/api/researches/{rid}/tables/{table['table']['id']}").json()
        base = f"/api/researches/{rid}/tables/{table['table']['id']}/export"
        xlsx = client.get(base + "/xlsx")
        assert xlsx.status_code == 200, xlsx.text
        assert xlsx.headers["content-type"] == ooxml.XLSX_MEDIA_TYPE
        assert xlsx.headers["content-disposition"] == f'attachment; filename="synthetic-evidence-v{view["table"]["version"]}.xlsx"'
        rows = xlsx_rows(xlsx.content)
        assert len(rows) == 1 + len(view["rows"]) and len(rows[0]) == 7 + 3 * len(view["columns"])
        cells = {(c["column_id"], c["source_version_id"]): c["current"] for c in view["cells"]}
        for row, source in zip(rows[1:], view["rows"]):
            for index, column in enumerate(view["columns"]):
                current = cells[(column["id"], source["source_version_id"])]
                assert row[7 + 3 * index] == current["value"]["text"]
                for e in current["evidence"]:
                    assert f"“{e['anchor_text']}” — PDF p. {e['physical_page']}" in row[8 + 3 * index]
                assert row[9 + 3 * index] == "Model · Selected pages"
        docx = client.get(base + "/docx?lang=tr&style=chicago")
        assert docx.status_code == 200 and docx.headers["content-type"] == ooxml.DOCX_MEDIA_TYPE
        assert docx.headers["content-disposition"].endswith(f'-v{view["table"]["version"]}.docx"')
        assert "Seçili sayfalar" in raw_text(docx.content)
        for data in (xlsx.content, docx.content):
            assert_clean(data, tmp_path)
        for bad, status in ((base + "/csv", 422), (f"/api/researches/{other}/tables/{table['table']['id']}/export/xlsx", 404),
                            (f"/api/researches/{rid}/tables/tbl_unknown/export/docx", 404),
                            (f"/api/researches/{rid}/tables/{empty['table']['id']}/export/xlsx", 422)):
            refused = client.get(bad)
            assert refused.status_code == status, (bad, refused.text)
            assert "content-disposition" not in refused.headers


# ---- evidence report -------------------------------------------------------------------------------------------

def _markdown_items(markdown: str) -> list:
    """The Markdown export in the shape docx_items returns: syntax and escapes removed, tables as cell lists."""
    items: list = []
    for line in markdown.splitlines():
        if not line or re.fullmatch(r"\|( --- \|)+", line):
            continue
        if line.startswith("| "):
            cells = [re.sub(r"\\(.)", r"\1", cell) for cell in line[2:-2].split(" | ")]
            if items and isinstance(items[-1], list):
                items[-1].append(cells)
            else:
                items.append([cells])
            continue
        items.append(re.sub(r"\\(.)", r"\1", re.sub(r"^(#+ |> |- )", "", line)))
    return items


@pytest.mark.parametrize("language", ["en", "tr"])
def test_evidence_report_docx_matches_the_markdown_export(tmp_path, language):
    store, reports, rid, report_id = complete(tmp_path)
    try:
        store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report_id))
        markdown, md_name = export_markdown(store, rid, report_id)
        data, name = report_export.export_docx(store, rid, report_id)
        assert name == md_name.removesuffix(".md") + ".docx"
        items = docx_items(data)
        assert items == _markdown_items(markdown)
        assert any(isinstance(item, list) for item in items)  # Table I is a real table
        assert_clean(data, tmp_path)
    finally:
        store.conn.close()


def test_evidence_report_route_and_refusals(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached", effort="quick")
        other = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, rid)
        table = create_table(client, rid, with_columns=True)
        fill_table(client, rid, table)
        started = client.post(f"/api/researches/{rid}/reports", json={"table_id": table["table"]["id"]})
        report_id = started.json()["target"]["report_id"]
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed"
        response = client.get(f"/api/researches/{rid}/reports/{report_id}/export/docx")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == ooxml.DOCX_MEDIA_TYPE
        assert re.fullmatch(r'attachment; filename="report-[a-z0-9-]+-v1\.docx"', response.headers["content-disposition"])
        markdown = client.get(f"/api/researches/{rid}/reports/{report_id}/export?format=markdown").text
        assert docx_items(response.content) == _markdown_items(markdown)
        assert_clean(response.content, tmp_path)
        for research, report, status in ((other, report_id, 404), (rid, "rpt_unknown000", 404), ("res_unknown000", report_id, 404)):
            refused = client.get(f"/api/researches/{research}/reports/{report}/export/docx")
            assert refused.status_code == status and "content-disposition" not in refused.headers
        store = raw.app.state.store
        pending = store.create_run(rid, "report", {"max_model_calls": 1, "max_provider_requests": 0}, None,
                                   {"table_id": table["table"]["id"]})
        from deixis.workflow.report.store import ReportStore
        unfinished = ReportStore(store).create_report(rid, pending["id"], pending["scope_revision"], "en")
        refused = client.get(f"/api/researches/{rid}/reports/{unfinished}/export/docx")
        assert refused.status_code == 409 and refused.json()["detail"] == "The report is still being written"


# ---- print stylesheet ----------------------------------------------------------------------------------------------

def test_print_stylesheet_prints_dark_mode_in_the_light_palette():
    src = Path(__file__).resolve().parents[2] / "apps/web/src"

    def tokens(css: str, selector: str) -> dict[str, str]:
        body = re.search(r"^\s*" + re.escape(selector) + r"\s*\{(.*?)^\s*\}", css, re.S | re.M).group(1)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        return {name: " ".join(value.split()) for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)}

    index = (src / "index.css").read_text(encoding="utf-8")
    printed = (src / "print.css").read_text(encoding="utf-8")
    light, dark = tokens(index, ":root"), tokens(index, ".dark")
    assert tokens(printed, ".dark") == {name: light[name] for name in dark}
    code = re.sub(r"/\*.*?\*/", "", printed, flags=re.S).strip()
    assert code.count("@media print") == 1 and code.startswith("@media print {") and code.endswith("}")
    assert "import './print.css'" in (src / "main.tsx").read_text(encoding="utf-8")

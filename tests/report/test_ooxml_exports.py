"""DOCX and XLSX exports (S18): SYNTHETIC records only; no provider or real model is called.

The files are checked by reading them back with zipfile and ElementTree: the parts a reader needs, well-formed XML,
the same text as the Markdown or CSV export (the browser's own generators run in node for the answer and the table),
anchors and locators as stored, and no secrets or local paths.
"""

from __future__ import annotations

from urllib.parse import quote
import csv
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from deixis.exports import answer as answer_export
from deixis.exports import ooxml
from deixis.exports import report as report_export
from deixis.exports import table as table_export
from deixis.exports.omml import to_omml
from deixis.exports.text import SERVER_ONLY, TR, number_text, reference_text
from deixis.workflow.report.export import export_markdown
from deixis.workflow.report.latex_math import split_text
from deixis.workflow.views import report_view
from test_api_flow import app_for, attached_research, create, session, wait_run
from test_report_api import create_table, fill_table, upload_and_include
from test_report_export import complete
from test_report_flow import ReportAdapter

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MATH = "⟨math⟩"  # a Word equation in docx_items, and the `$...$` span it was converted from in the Markdown
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SPECIAL = "A & B < C > D \"q\" 'a' 🧪 İstanbul ğüşöçı ĞÜŞÖÇ $\\alpha_{1} < \\beta^{2}$ \\& x"
DOCX_PARTS = {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/_rels/document.xml.rels",
              "word/styles.xml", "word/numbering.xml", "word/footer1.xml", "word/_rels/footer1.xml.rels",
              "word/media/deixis-mark.png", "word/settings.xml", "docProps/core.xml"}
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
        parsed = {name: ET.fromstring(archive.read(name)) for name in names if not name.endswith(".png")}
    types = parsed["[Content_Types].xml"]
    overrides = {item.get("PartName") for item in types if item.tag.endswith("Override")}
    # The footer mark is typed by the png Default; every other part has its own Override.
    assert overrides == {"/" + name for name in names if not name.endswith((".rels", ".png")) and name != "[Content_Types].xml"}
    return parsed


def raw_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist() if not name.endswith(".png"))


def _p_text(p: ET.Element) -> str:
    out = []
    for node in p.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "br":
            out.append("\n")
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag == M + "oMath":
            out.append(MATH)
    return "".join(out)


def _math_marked(text: str) -> str:
    """The text with each `$...$` span that the DOCX writes as a Word equation replaced by MATH."""
    return "".join(MATH if kind == "math" and _converts(value) else value for kind, value in split_text(text))


def _converts(span: str) -> bool:
    display = span.startswith("$$")
    return to_omml(span[2:-2] if display else span[1:-1], display) is not None


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
    source = (Path(__file__).resolve().parents[2] / "web/src/i18n.ts").read_text(encoding="utf-8")
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


# ---- the browser's own exports, run in node ---------------------------------------------------------------------

BROWSER = r"""
const fs = require('fs'), path = require('path'), Module = require('module'), ts = require('typescript');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const stored = { 'deixis-citation-style': input.style, 'deixis-ui-language': input.lang };
globalThis.localStorage = { getItem: k => stored[k] ?? null, setItem: (k, v) => { stored[k] = String(v) } };
const options = { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true };
const compile = (source, file) => ts.transpileModule(source, { fileName: file, compilerOptions: options }).outputText;
require.extensions['.ts'] = require.extensions['.tsx'] = (m, file) => m._compile(compile(fs.readFileSync(file, 'utf8'), file), file);
const src = path.resolve('src');
// The real generators: the report's Markdown (research/reportMarkdown.ts) and the table's CSV (tableCsv.ts).
const probe = `
import { setUiLanguage } from './i18n'
import { reportMarkdown } from './research/reportMarkdown'
import { tableCsv } from './tableCsv'
export { setUiLanguage, tableCsv }
export const answerMarkdown = reportMarkdown
`;
const file = path.join(src, '__s18_export_probe__.tsx');
const m = new Module(file, module); m.filename = file; m.paths = Module._nodeModulePaths(src);
m._compile(compile(probe, file), file);
m.exports.setUiLanguage(input.lang);
process.stdout.write(JSON.stringify({
  markdown: input.answer ? m.exports.answerMarkdown(input.answer, input.sources, input.title, input.version, input.style) : null,
  csv: input.table ? m.exports.tableCsv(input.table, input.sources) : null,
}));
"""


def browser_exports(*, lang, style, sources, answer=None, title="", version=0, table=None) -> dict:
    root = Path(__file__).resolve().parents[2]
    payload = json.dumps({"lang": lang, "style": style, "sources": sources, "answer": answer, "title": title,
                          "version": version, "table": table})
    done = subprocess.run(["node", "-e", BROWSER], input=payload, cwd=root / "web", capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


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
        {"section": "Results", "text": "Claim four.", "support_type": "source_stated", "review": None,
         "evidence": [_evidence("p1", "s1", "Lov21", anchor_text="a different quote of p1")]},
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
ACCESS_LIMIT = {"en": "access: SYNTHETIC access limit.", "tr": "erişim: SYNTHETIC access limit."}


def _plain_markdown(markdown: str) -> list[str]:
    lines = []
    for line in markdown.splitlines():
        if not line or line == "---":
            continue
        line = re.sub(r"^(#+ |> |- )", "", line).replace("**", "")
        lines.append(_math_marked(re.sub(r"(^| )_(.+?)_(?= |$)", r"\1\2", line)))
    return lines


@pytest.mark.parametrize("lang,style", [("en", "apa"), ("tr", "ieee"), ("en", "mla"), ("tr", "chicago")])
def test_answer_docx_is_the_browser_markdown_plus_quotes_and_access_limits(lang, style):
    markdown = browser_exports(lang=lang, style=style, sources=SYNTHETIC_SOURCES, answer=SYNTHETIC_ANSWER,
                               title="SYNTHETIC title", version=3)["markdown"]
    data = ooxml.docx(answer_export.blocks(SYNTHETIC_ANSWER, SYNTHETIC_SOURCES, title="SYNTHETIC title", version=3,
                                           language=lang, style=style))
    items = docx_items(data)
    first_lines = [item.split("\n")[0] for item in items]
    # The browser leaves the access limitation to its PDF suggestions block; the file lists it under Limits.
    assert ACCESS_LIMIT[lang] not in _plain_markdown(markdown) and ACCESS_LIMIT[lang] in first_lines
    assert [line for line in first_lines if line != ACCESS_LIMIT[lang]] == _plain_markdown(markdown)
    # Every claim's own quote of a passage, verbatim and unmerged, under the passage's one numbered line.
    quotes = [item.split("\n")[1:] for item in items if "\n" in item]
    assert quotes == [["“quote “one” & <two>”", "“a different quote of p1”"], ["“abstract quote”"], ["“ocr quote”"]]


SOURCE_TEXT_CHANGED = {
    "en": "A PDF this answer read was replaced, removed or had its text extracted again after the answer was generated. Its quotes still open the text that was read; generate a new answer to read the current text.",
    "tr": "Bu yanıtın okuduğu bir PDF, yanıt üretildikten sonra değiştirildi, kaldırıldı ya da metni yeniden çıkarıldı. Alıntılar okunan metni açmaya devam eder; güncel metni okumak için yeni bir yanıt üretin.",
}


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_answer_docx_carries_the_changed_source_text_notice_where_the_screen_shows_it(lang):
    def items(answer):
        return docx_items(ooxml.docx(answer_export.blocks(answer, SYNTHETIC_SOURCES, title="T", version=3, language=lang, style="apa")))

    unchanged = items(SYNTHETIC_ANSWER | {"source_text_changed": False})
    changed = items(SYNTHETIC_ANSWER | {"source_text_changed": True})
    assert SOURCE_TEXT_CHANGED[lang] not in unchanged
    # After the stale-selection notice and before the capability notice, as on screen; nothing else moves.
    at = unchanged.index("SYNTHETIC notice & <tag>")
    assert changed == unchanged[:at] + [SOURCE_TEXT_CHANGED[lang]] + unchanged[at:]
    style = parts(ooxml.docx(answer_export.blocks(SYNTHETIC_ANSWER | {"source_text_changed": True}, SYNTHETIC_SOURCES, title="T",
                                                  version=3, language=lang, style="apa")), DOCX_PARTS)["word/document.xml"]
    quoted = [_p_text(p) for p in style.iter(W + "p") if (p.find(f"{W}pPr/{W}pStyle") is not None
                                                         and p.find(f"{W}pPr/{W}pStyle").get(W + "val") == "Quote")]
    assert SOURCE_TEXT_CHANGED[lang] in quoted


def _ledger_work(svid, title):
    return {"source_version_id": svid, "work_id": f"w{svid}", "source_key": None, "title": title}


# The view's evidence ledger (D80): s1 and s2 cited, s3 and s4 left out with a reason, s5 with none. SYNTHETIC.
SYNTHETIC_LEDGER = {
    "complete": False, "cited": ["s1", "s2"],
    "given": [_ledger_work(s, f"SYNTHETIC work {s}") for s in ("s1", "s2", "s3", "s4", "s5")],
    "excluded": [
        _ledger_work("s3", "SYNTHETIC work s3") | {"reason": "different_conditions", "note": "SYNTHETIC: a mobile sink.",
                                                   "same_as": None, "passage_id": "p30", "anchor_text": "located words"},
        _ledger_work("s4", "SYNTHETIC work s4") | {"reason": "same_finding_as_cited", "note": "SYNTHETIC: repeats s1.",
                                                   "same_as": _ledger_work("s1", "SYNTHETIC work s1"), "passage_id": "p40",
                                                   "anchor_text": None}],
    "unaccounted": [_ledger_work("s5", "SYNTHETIC work s5") | {"passage_id": "p50", "anchor_text": None}],
}
LEDGER_LINES = {
    "en": ["Works given but not cited", "2 of 5 given works cited · 2 left out with a reason · 1 with no reason recorded",
           "SYNTHETIC work s3 · Answers part of the question under other conditions · Note from the model: SYNTHETIC: a mobile sink.",
           "SYNTHETIC work s4 · Same finding as a cited work: SYNTHETIC work s1 · Note from the model: SYNTHETIC: repeats s1.",
           "SYNTHETIC work s5 · No reason was recorded for this work."],
    "tr": ["Verilen ama atıf yapılmayan eserler",
           "Verilen 5 eserden 2 tanesine atıf yapıldı · 2 tanesi gerekçeyle dışarıda bırakıldı · 1 tanesi için gerekçe kaydedilmedi",
           "SYNTHETIC work s3 · Sorunun bir kısmını başka koşullarda yanıtlıyor · Modelin notu: SYNTHETIC: a mobile sink.",
           "SYNTHETIC work s4 · Atıf yapılan bir eserle aynı bulgu: SYNTHETIC work s1 · Modelin notu: SYNTHETIC: repeats s1.",
           "SYNTHETIC work s5 · Bu eser için gerekçe kaydedilmedi."],
}


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_answer_exports_list_the_works_given_but_not_cited(lang):
    answer = SYNTHETIC_ANSWER | {"evidence_ledger": SYNTHETIC_LEDGER}
    markdown = browser_exports(lang=lang, style="apa", sources=SYNTHETIC_SOURCES, answer=answer, title="T", version=3)["markdown"]
    items = [item.split("\n")[0] for item in docx_items(ooxml.docx(answer_export.blocks(
        answer, SYNTHETIC_SOURCES, title="T", version=3, language=lang, style="apa")))]
    # The Markdown and the Word file list the same lines, after "Not answered" and before Limits.
    assert [line for line in items if line != ACCESS_LIMIT[lang]] == _plain_markdown(markdown)
    at = items.index(LEDGER_LINES[lang][0])
    assert items[at:at + 5] == LEDGER_LINES[lang]
    assert items[at - 1] == "SYNTHETIC gap ğ" and items[at + 5] == ("Limits" if lang == "en" else "Sınırlılıklar")
    # An answer saved without a ledger has no such section in either file.
    plain = browser_exports(lang=lang, style="apa", sources=SYNTHETIC_SOURCES, answer=SYNTHETIC_ANSWER | {"evidence_ledger": None},
                            title="T", version=3)["markdown"]
    assert LEDGER_LINES[lang][0] not in plain
    assert LEDGER_LINES[lang][0] not in docx_items(ooxml.docx(answer_export.blocks(
        SYNTHETIC_ANSWER | {"evidence_ledger": None}, SYNTHETIC_SOURCES, title="T", version=3, language=lang, style="apa")))


FORGING_NOTE = ("SYNTHETIC first line\n\n## Cited passages\n\n[999] FORGED RECORD — PDF p. 1\n"
                "[a link](https://example.test) <script>alert(1)</script> <b>bold</b> & *star* `code`\n1. not a list\nFORGED RECORD\n===")


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_a_ledger_note_stays_text_inside_its_one_list_item(lang):
    excluded = [dict(SYNTHETIC_LEDGER["excluded"][0], note=FORGING_NOTE, title="SYNTHETIC <i>title</i> [x](y)")]
    answer = SYNTHETIC_ANSWER | {"evidence_ledger": SYNTHETIC_LEDGER | {"excluded": excluded,
                                                                        "unaccounted": SYNTHETIC_LEDGER["unaccounted"] + [SYNTHETIC_LEDGER["excluded"][1] | {"passage_id": None, "anchor_text": None}]}}
    markdown = browser_exports(lang=lang, style="apa", sources=SYNTHETIC_SOURCES, answer=answer, title="T", version=3)["markdown"]
    plain = browser_exports(lang=lang, style="apa", sources=SYNTHETIC_SOURCES, answer=SYNTHETIC_ANSWER, title="T", version=3)["markdown"]
    lines = markdown.splitlines()
    # The same headings as without a ledger plus its own; no line starts a record or a block from the note.
    headings = [line for line in lines if line.startswith("#")]
    assert sorted(headings) == sorted([line for line in plain.splitlines() if line.startswith("#")] + [f"## {LEDGER_LINES[lang][0]}"])
    assert not any(line.lstrip().startswith(("[999]", "<", "1.")) for line in lines)
    # The note's lines continue its list item (indented hard breaks); nothing in it starts a block of its own.
    at = next(i for i, line in enumerate(lines) if line.startswith("- SYNTHETIC \\<i\\>title"))
    item = [lines[at]]
    while lines[at + len(item)].startswith("  "):
        item.append(lines[at + len(item)])
    assert len(item) == 7 and all(line.endswith("  ") for line in item[:-1])
    body = "\n".join(item)
    for raw in ("<script>", "<b>", "<i>", "[999]", "[a link](", "## Cited", "*star*", "`code`"):
        assert raw not in body
    for escaped in ("\\<script\\>", "\\[999\\]", "\\[a link\\]\\(https://example.test\\)", "\\#\\# Cited passages", "\\*star\\*",
                    "\\`code\\`", "\\&", "1\\. not a list", "  \\=\\=\\=", "SYNTHETIC \\<i\\>title\\</i\\> \\[x\\]\\(y\\)"):
        assert escaped in body
    # Word writes the text as text (XML-escaped by the writer) with the note's line breaks inside one bullet.
    items = docx_items(ooxml.docx(answer_export.blocks(answer, SYNTHETIC_SOURCES, title="T", version=3, language=lang, style="apa")))
    (bullet,) = [item for item in items if item.startswith("SYNTHETIC <i>title</i>")]
    assert "\n## Cited passages\n" in bullet and "<script>alert(1)</script>" in bullet


BROKEN_LEDGERS = [
    {}, {"given": None, "cited": [], "excluded": [], "unaccounted": []},
    {"cited": [], "excluded": [], "unaccounted": []},
    SYNTHETIC_LEDGER | {"excluded": [{"source_version_id": "s3"}]},
    SYNTHETIC_LEDGER | {"excluded": [None]},
    SYNTHETIC_LEDGER | {"cited": ["s1", "s3"]},  # s3 both cited and excluded
    SYNTHETIC_LEDGER | {"unaccounted": []},  # s5 given but in no bucket
    SYNTHETIC_LEDGER | {"excluded": [SYNTHETIC_LEDGER["excluded"][0] | {"reason": "made_up"}, SYNTHETIC_LEDGER["excluded"][1]]},
    SYNTHETIC_LEDGER | {"excluded": [SYNTHETIC_LEDGER["excluded"][0] | {"reason": []}, SYNTHETIC_LEDGER["excluded"][1]]},
    SYNTHETIC_LEDGER | {"excluded": [SYNTHETIC_LEDGER["excluded"][0] | {"reason": {}}, SYNTHETIC_LEDGER["excluded"][1]]},
    SYNTHETIC_LEDGER | {"unaccounted": [{"source_version_id": "s5", "passage_id": "p50", "anchor_text": None}]},  # no title
    "not a ledger", [],
]


@pytest.mark.parametrize("ledger", BROKEN_LEDGERS)
def test_a_malformed_ledger_is_left_out_of_both_exports_without_counts(ledger):
    answer = SYNTHETIC_ANSWER | {"evidence_ledger": ledger}
    for lang in ("en", "tr"):
        markdown = browser_exports(lang=lang, style="apa", sources=SYNTHETIC_SOURCES, answer=answer, title="T", version=3)["markdown"]
        items = docx_items(ooxml.docx(answer_export.blocks(answer, SYNTHETIC_SOURCES, title="T", version=3, language=lang, style="apa")))
        assert LEDGER_LINES[lang][0] not in markdown and LEDGER_LINES[lang][0] not in items
        assert not any("given works cited" in item or "eserden" in item for item in items)


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
        assert response.headers["content-disposition"].startswith(f'attachment; filename="DEIXIS - ') and \
            response.headers["content-disposition"].endswith(f"{quote(' - V1.docx', safe='')}")
        items = docx_items(response.content)
        assert items[0] == answer["report_title"] and items[1] == "Report · V1"
        evidence = [e for claim in answer["claims"] for e in claim["evidence"]]
        assert evidence and all(e["anchor_text"] for e in evidence)
        text = "\n".join(i for i in items if isinstance(i, str))
        for claim in answer["claims"]:
            assert claim["text"] in text
        for e in evidence:
            assert f"“{e['anchor_text']}”" in text and f"PDF p. {e['physical_page']}" in text
        for limitation in answer["limitations"]:
            assert limitation["text"] in text
        markdown = browser_exports(lang="en", style="apa", sources=view["sources"], answer=answer,
                                   title=answer["report_title"], version=answer["report_version"])["markdown"]
        assert [i.split("\n")[0] for i in items] == _plain_markdown(markdown)
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

def _current(state, author, depth, value, evidence=(), revision=1):
    return {"state": state, "author": author, "reading_depth": depth, "value": value, "column_revision": revision,
            "evidence": [{"anchor_text": a, "kind": k, "physical_page": p, "printed_label": l} for a, k, p, l in evidence]}


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
        {"column_id": "c1", "source_version_id": "s1", "flags": ["stale_column", "ocr_numbers_unchecked"],
         "current": _current("value", "model", "full_text", {"number": 1234.5, "unit": "kB"},
                             [("size is 1,234.5 kB", "pdf_page", 4, "12"), (None, "abstract", None, None)])},
        {"column_id": "c2", "source_version_id": "s1", "flags": [],
         "current": _current("not_verified", "human", None, {"option_ids": ["o2", "zz"]})},
        {"column_id": "c3", "source_version_id": "s1", "flags": ["pdf_replaced", "text_superseded"],
         "current": _current("value", "model", "abstract", {"text": SPECIAL}, [(SPECIAL, "abstract", None, None)])},
        {"column_id": "c1", "source_version_id": "s2", "flags": ["pdf_removed"],
         "current": _current("value", "model", "abstract", {"number": 7, "unit": None})},
        {"column_id": "c2", "source_version_id": "s2", "flags": ["proposal_before_edit"],
         "current": _current("not_reported", "system", "metadata", None),
         "pending_proposal": {"state": "value", "value": {"option_ids": ["o1"]}}},
        {"column_id": "c3", "source_version_id": "s2", "flags": [], "current": None},
    ],
}
STALE = "Made under an earlier definition of this column (revision 1). It stays until you edit it or use a newer proposal."
OCR = "This value states a number or equation read only from OCR text of a scanned page. It was not checked against the page; open the evidence and compare it with the PDF."
REPLACED = "This value cites a PDF that was later replaced. Its evidence still opens the previous file; a recheck reads the current file."
SUPERSEDED = "This value cites an earlier text extraction of the PDF. Its evidence still opens that text; a recheck reads the current extraction."
REMOVED = "A PDF this value cites was removed from the source. The cited passages still open as text; the PDF view is off."
# Per row and column: (source line, state, warnings) — what the grid and the cell panel show beside the CSV value.
SYNTHETIC_EXTRAS = [
    [("Model · Full text", "Value", f"{STALE} | {OCR}"), ("You · no linked evidence", "Value without linked evidence", ""),
     ("Model · Abstract", "Value", f"{REPLACED} | {SUPERSEDED}")],
    [("Model · Abstract", "Value", REMOVED), ("System · Metadata", "Not reported", ""), ("", "", "")],
]


def _csv(text: str) -> list[list[str]]:
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:], newline="")))


@pytest.mark.parametrize("lang,style", [("en", "apa"), ("tr", "chicago")])
def test_table_xlsx_is_the_browser_csv_plus_source_state_and_warnings(lang, style):
    expected = _csv(browser_exports(lang=lang, style=style, sources=SYNTHETIC_SOURCES, table=SYNTHETIC_TABLE)["csv"])
    data = table_export.xlsx(SYNTHETIC_TABLE, SYNTHETIC_SOURCES, language=lang, style=style)
    rows = xlsx_rows(data)
    names = ("Size", "Kind", "Note")
    width = 8 + 5 * len(names)  # eight source fields since D114 added "In report"
    head = expected[0]
    suffix = ("source", "state", "warnings") if lang == "en" else ("kaynak", "durum", "uyarılar")
    assert rows[0] == head[:8] + [x for k, name in enumerate(names) for x in (head[8 + 2 * k], head[9 + 2 * k],
                                                                             *(f"{name} — {s}" for s in suffix))]

    def text(value):
        return number_text(value, lang) if isinstance(value, (int, float)) else value

    for row, line in zip(rows[1:], expected[1:]):
        row = row + [""] * (width - len(row))
        assert [str(v) for v in row[:8]] + [text(row[8 + 5 * k + j]) for k in range(len(names)) for j in (0, 1)] == line
    assert rows[1][4] == 2021 and rows[2][8] == 7  # numbers stay numbers in the workbook
    if lang == "en":
        for row, extras in zip(rows[1:], SYNTHETIC_EXTRAS):
            row = row + [""] * (width - len(row))
            assert [tuple(row[10 + 5 * k: 13 + 5 * k]) for k in range(len(names))] == extras
    else:
        assert rows[1][10] == "Model · Tam metin" and rows[1][15] == "Siz · bağlı kanıt yok"
        assert rows[1][16] == "Bağlı kanıtı olmayan değer" and rows[1][12].startswith("Bu sütunun önceki bir tanımıyla üretildi (revizyon 1).")
    workbook = parts(data, XLSX_PARTS)["xl/workbook.xml"]
    assert [s.get("name") for s in workbook.iter(S + "sheet")] == ["SYNTHETIC tablo ğ & <x>"]
    assert "Fast" not in raw_text(data)  # the proposal waiting for a decision is left out, as in the CSV


def test_table_docx_has_the_values_sources_states_warnings_and_quotes():
    data = table_export.docx(SYNTHETIC_TABLE, SYNTHETIC_SOURCES, language="en", style="apa", research_title="SYNTHETIC research")
    items = docx_items(data)
    assert items[:2] == ["SYNTHETIC research", "SYNTHETIC tablo ğ & <x> · V4"]
    grid = items[2]
    assert grid[0] == ["Source", "Size", "Kind", "Note"]
    # The eight source fields share one cell: key, reference, then version, access and whether it is in the report (D114).
    assert grid[1][0] == "Lov21\nLovelace, A. (2021). SYNTHETIC routing.\naccepted manuscript\nPDF text\nIn report: No"
    assert grid[2][0].endswith("\nAbstract only\nIn report: No") and "version not stated" not in grid[2][0]
    assert grid[1][1:] == [f"1,234.5 kB\nModel · Full text\n{STALE}\n{OCR}\n“size is 1,234.5 kB” — PDF p. 4 (printed 12)\nabstract",
                           "Slow, zz\nYou · no linked evidence\nState: Value without linked evidence",
                           f"{SPECIAL}\nModel · Abstract\n{REPLACED}\n{SUPERSEDED}\n“{SPECIAL}” — abstract"]
    assert grid[2][1:] == [f"7\nModel · Abstract\n{REMOVED}", "Not reported\nSystem · Metadata", ""]
    document = parts(data, DOCX_PARTS)
    assert document["word/document.xml"].find(f"{W}body/{W}sectPr/{W}pgSz").get(W + "orient") == "landscape"
    # Word opens the file in its current mode, not "Compatibility Mode".
    assert document["word/settings.xml"].find(f"{W}compat/{W}compatSetting").get(W + "val") == "15"


def test_table_docx_splits_many_columns_into_tables_that_repeat_the_source():
    columns = [{"id": f"c{i}", "name": f"Column {i}", "options": None} for i in range(1, 10)]
    view = {**SYNTHETIC_TABLE, "table": {"title": table_export.DEFAULT_TITLE, "version": 9}, "columns": columns}
    items = docx_items(table_export.docx(view, SYNTHETIC_SOURCES, language="tr", style="apa"))
    assert items[:2] == ["Kanıt tablosu", "V9"]
    tables = [item for item in items if isinstance(item, list)]
    assert [t[0] for t in tables] == [["Kaynak", *(f"Column {i}" for i in range(a, b))] for a, b in ((1, 5), (5, 9), (9, 10))]
    assert {t[1][0] for t in tables} == {tables[0][1][0]} and tables[0][1][0].startswith("Lov21\n")
    assert table_export.filename(view, "docx", research_title="Kuantum: ağlar", language="tr") == \
        "DEIXIS - Kuantum - ağlar - Kanıt tablosu - V9.docx"


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
        sources = client.get(f"/api/researches/{rid}").json()["sources"]
        base = f"/api/researches/{rid}/tables/{table['table']['id']}/export"
        xlsx = client.get(base + "/xlsx")
        assert xlsx.status_code == 200, xlsx.text
        assert xlsx.headers["content-type"] == ooxml.XLSX_MEDIA_TYPE
        research_title = client.get(f"/api/researches/{rid}").json()["research"]["title"]
        name = table_export.filename(view, "xlsx", research_title=research_title)
        assert name.startswith("DEIXIS - ") and name.endswith(f' - V{view["table"]["version"]}.xlsx')
        assert xlsx.headers["content-disposition"] == f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name, safe='')}"
        rows = xlsx_rows(xlsx.content)
        expected = _csv(browser_exports(lang="en", style="apa", sources=sources, table=view)["csv"])
        assert len(rows) == len(expected) and len(rows[0]) == 8 + 5 * len(view["columns"])
        cells = {(c["column_id"], c["source_version_id"]): c["current"] for c in view["cells"]}
        for row, line, source in zip(rows[1:], expected[1:], view["rows"]):
            row = row + [""] * (len(rows[0]) - len(row))
            assert [str(v) for v in row[:8]] + [row[8 + 5 * k + j] for k in range(len(view["columns"])) for j in (0, 1)] == line
            for index, column in enumerate(view["columns"]):
                current = cells[(column["id"], source["source_version_id"])]
                for e in current["evidence"]:
                    assert f"“{e['anchor_text']}” — PDF p. {e['physical_page']}" in row[9 + 5 * index]
                assert row[10 + 5 * index: 12 + 5 * index] == ["Model · Selected pages", "Value"]
        docx = client.get(base + "/docx?lang=tr&style=chicago")
        assert docx.status_code == 200 and docx.headers["content-type"] == ooxml.DOCX_MEDIA_TYPE
        assert docx.headers["content-disposition"].endswith(quote(f' - V{view["table"]["version"]}.docx', safe=''))
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


def _appendix(store, view, items, language):
    """The DOCX after the Markdown's last item is the evidence appendix: every current link with its quote and place."""
    heading = "Evidence appendix" if language == "en" else "Kanıt eki"
    assert items[0] == heading
    text = "\n".join(items[1:])
    links = [link for section in view["sections"] for claim in section["claims"] for link in claim["evidence"]]
    assert links
    lines = [line for line in items if isinstance(line, str)]
    for link in links:
        target = link["passage_id"] or link["open_passage_id"]
        expected = f'[{link["ref_number"]}] “{link["anchor_text"]}”'
        if link["cell_id"]:
            expected += " — " + ("Table I, " if language == "en" else "Tablo I, ")
        else:
            expected += " — "
        if target:
            row = store.conn.execute("SELECT kind, physical_page FROM passages WHERE id = ?", (target,)).fetchone()
            place = {"en": "abstract", "tr": "özet"}[language] if row["kind"] == "abstract" else \
                ("PDF p. " if language == "en" else "PDF s. ") + str(row["physical_page"])
        else:
            place = "quote not located" if language == "en" else "alıntı hücrenin kanıt pasajlarında bulunamadı"
        assert any(line.startswith(expected) and place in line for line in lines), (expected, place, lines)
    assert sum(line.startswith("[") for line in lines) == len(links)
    return text


@pytest.mark.parametrize("language", ["en", "tr"])
def test_evidence_report_docx_is_the_markdown_export_plus_an_evidence_appendix(tmp_path, language):
    store, reports, rid, report_id = complete(tmp_path)
    try:
        store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report_id))
        markdown, md_name = export_markdown(store, rid, report_id)
        data, name = report_export.export_docx(store, rid, report_id)
        assert name == md_name.removesuffix(".md") + ".docx"
        items, expected = docx_items(data), _markdown_items(markdown)
        assert items[:len(expected)] == expected
        assert any(isinstance(item, list) for item in items)  # Table I is a real table
        view = report_view(store, rid, report_id) | {"language": language}
        _appendix(store, view, items[len(expected):], language)
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
        assert re.fullmatch(r'attachment; filename="(report-[a-z0-9-]+-v1\.docx)"; filename\*=UTF-8\'\'\1', response.headers["content-disposition"])
        markdown = client.get(f"/api/researches/{rid}/reports/{report_id}/export?format=markdown").text
        items, expected = docx_items(response.content), _markdown_items(markdown)
        assert items[:len(expected)] == expected
        store = raw.app.state.store
        view = client.get(f"/api/researches/{rid}/reports/{report_id}").json()
        _appendix(store, view, items[len(expected):], "en")
        assert_clean(response.content, tmp_path)
        for research, report, status in ((other, report_id, 404), (rid, "rpt_unknown000", 404), ("res_unknown000", report_id, 404)):
            refused = client.get(f"/api/researches/{research}/reports/{report}/export/docx")
            assert refused.status_code == status and "content-disposition" not in refused.headers
        pending = store.create_run(rid, "report", {"max_model_calls": 1, "max_provider_requests": 0}, None,
                                   {"table_id": table["table"]["id"]})
        from deixis.workflow.report.store import ReportStore
        unfinished = ReportStore(store).create_report(rid, pending["id"], pending["scope_revision"], "en")
        refused = client.get(f"/api/researches/{rid}/reports/{unfinished}/export/docx")
        assert refused.status_code == 409 and refused.json()["detail"] == "The report is still being written"


# ---- print stylesheet ----------------------------------------------------------------------------------------------

def test_print_stylesheet_prints_dark_mode_in_the_light_palette():
    src = Path(__file__).resolve().parents[2] / "web/src"

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

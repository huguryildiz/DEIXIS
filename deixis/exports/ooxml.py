"""A small Office Open XML writer: DOCX documents and XLSX workbooks from the standard library only.

The writer knows layout, not content. Callers pass blocks (headings, paragraphs of plain, bold or italic runs, bulleted
or numbered lists, simple tables, a horizontal rule) or sheets (a header row and rows of string or number cells), and
get the bytes of a zip that Word, Excel and LibreOffice open. Citations are whatever text the caller put in the runs.

Text is written as given, after two mechanical steps: characters XML 1.0 cannot carry (control characters other than
tab and newline, lone surrogates, U+FFFE/U+FFFF) are dropped, and `&`, `<`, `>` and `"` are escaped. A newline in a
run becomes a line break and a tab a tab. Excel cells hold at most 32,767 characters; a longer string is cut there and
ends with an ellipsis. Zip entries carry a fixed timestamp, so the same input gives the same bytes.
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterable, Sequence, Union

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

EXCEL_CELL_LIMIT = 32767
_STAMP = (1980, 1, 1, 0, 0, 0)
_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def clean(text: object) -> str:
    """The text with the characters XML 1.0 cannot carry removed."""
    return _INVALID.sub("", "" if text is None else str(text))


def escape(text: object, attribute: bool = False) -> str:
    value = clean(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return value.replace('"', "&quot;") if attribute else value


# ---- document model ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Run:
    text: str
    bold: bool = False
    italic: bool = False


@dataclass(frozen=True)
class Math:
    """A `$...$` (or `$$...$$`) span of LaTeX, written as a Word equation; `source` keeps the dollar signs, and is
    written as text when the equation cannot be converted (omml.py)."""
    source: str


Inline = Union[str, Run, Math]


def runs(*parts: Inline) -> tuple[Run | Math, ...]:
    return tuple(part if isinstance(part, (Run, Math)) else Run(part) for part in parts
                 if (part.source if isinstance(part, Math) else part.text if isinstance(part, Run) else part))


def with_math(text: str, *, bold: bool = False, italic: bool = False) -> tuple[Run | Math, ...]:
    """The text as runs, each `$...$` span (found as the LaTeX export finds them) as a Math part."""
    from deixis.workflow.report_latex_math import split_text
    return runs(*(Math(value) if kind == "math" else Run(value, bold, italic) for kind, value in split_text(text)))


@dataclass(frozen=True)
class Paragraph:
    """One paragraph. `style` is one of STYLES: Title, Heading1-3, Quote, Small, Bibliography, or None for body text."""
    runs: tuple[Run | Math, ...]
    style: str | None = None


@dataclass(frozen=True)
class ListBlock:
    items: tuple[tuple[Run | Math, ...], ...]
    ordered: bool = False


@dataclass(frozen=True)
class Table:
    """A table with a repeated header row. A cell is a string or a sequence of paragraphs."""
    header: tuple[str, ...]
    rows: tuple[tuple[Union[str, Sequence[Paragraph]], ...], ...]
    widths: tuple[float, ...] | None = None  # relative column weights


@dataclass(frozen=True)
class Rule:
    """A horizontal line between parts of a document."""


Block = Union[Paragraph, ListBlock, Table, Rule]


def paragraph(*parts: Inline, style: str | None = None) -> Paragraph:
    return Paragraph(runs(*parts), style)


def heading(level: int, text: str) -> Paragraph:
    return Paragraph(runs(text), "Title" if level == 0 else f"Heading{min(max(level, 1), 3)}")


def bullets(items: Iterable[Sequence[Inline]], ordered: bool = False) -> ListBlock:
    return ListBlock(tuple(runs(*item) for item in items), ordered)


# ---- shared package parts ---------------------------------------------------------------------------------------

def _zip(parts: list[tuple[str, str | bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, xml in parts:
            info = zipfile.ZipInfo(name, date_time=_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, xml if isinstance(xml, bytes) else xml.encode("utf-8"))
    return buffer.getvalue()


def _xml(body: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body


def _content_types(defaults: dict[str, str], overrides: dict[str, str]) -> str:
    items = "".join(f'<Default Extension="{ext}" ContentType="{kind}"/>' for ext, kind in defaults.items())
    items += "".join(f'<Override PartName="{part}" ContentType="{kind}"/>' for part, kind in overrides.items())
    return _xml(f'<Types xmlns="{_CT}">{items}</Types>')


def _rels(targets: list[tuple[str, str]]) -> str:
    items = "".join(f'<Relationship Id="rId{i}" Type="{kind}" Target="{escape(target, True)}"/>'
                    for i, (kind, target) in enumerate(targets, 1))
    return _xml(f'<Relationships xmlns="{_PKG_RELS}">{items}</Relationships>')


def _core(title: str) -> str:
    return _xml('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'<dc:title>{escape(title)}</dc:title></cp:coreProperties>')


_DEFAULTS = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
_CORE_TYPE = "application/vnd.openxmlformats-package.core-properties+xml"
_CORE_REL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"


# ---- DOCX -------------------------------------------------------------------------------------------------------

STYLES = ("Title", "Heading1", "Heading2", "Heading3", "Quote", "Small", "BodyText", "Bibliography")
# The look of an Elicit report's Word file: Georgia body text set justified at 1.15 lines, Calibri headings that are
# not bold, and a numbered reference list with a hanging indent. Tables keep Calibri and left-aligned cells.
_SERIF = '<w:rFonts w:ascii="Georgia" w:hAnsi="Georgia" w:eastAsia="Georgia" w:cs="Georgia"/>'
_FONT = '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>'


def _styles_docx() -> str:
    # Child order inside pPr and rPr follows the schema sequence; Word refuses files that break it.
    def para(style_id: str, name: str, ppr: str, rpr: str, outline: int | None = None) -> str:
        nxt, keep, level = ("", "", "") if outline is None else (
            '<w:next w:val="BodyText"/>', "<w:keepNext/><w:keepLines/>", f'<w:outlineLvl w:val="{outline}"/>')
        return (f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
                f'{nxt}<w:qFormat/><w:pPr>{keep}{ppr}{level}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>')

    def size(half_points: int) -> str:
        return f'<w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/>'
    return _xml(
        f'<w:styles xmlns:w="{_W}">'
        f'<w:docDefaults><w:rPrDefault><w:rPr>{_SERIF}{size(22)}'
        '<w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
        + para("Title", "Title", '<w:spacing w:after="80" w:line="240" w:lineRule="auto"/>', _FONT + size(32), 0)
        + para("Heading1", "heading 1", '<w:spacing w:before="360" w:after="80"/>', _FONT + size(28), 0)
        + para("Heading2", "heading 2", '<w:spacing w:before="240" w:after="80"/>', _FONT + size(28), 1)
        + para("Heading3", "heading 3", '<w:spacing w:before="160" w:after="80"/>', size(24), 2)
        + para("BodyText", "Body Text", '<w:spacing w:before="120" w:after="120" w:line="276" w:lineRule="auto"/><w:jc w:val="both"/>', "")
        + para("Bibliography", "Bibliography", '<w:spacing w:before="0" w:after="160"/><w:ind w:left="567" w:hanging="567"/>', "")
        + para("Quote", "Quote", '<w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="A0A0A0"/></w:pBdr><w:ind w:left="567"/>',
               '<w:color w:val="404040"/>')
        + para("Small", "Small", '<w:spacing w:after="40"/>', '<w:color w:val="595959"/>' + size(18))
        + '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>'
          '<w:qFormat/><w:pPr><w:spacing w:before="36" w:after="36"/><w:ind w:left="720"/></w:pPr></w:style>'
        '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr>'
        '<w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/>'
        f'<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr>{_FONT}{size(18)}</w:rPr>'
        '<w:tblPr><w:tblBorders>' + "".join(
            f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
            for side in ("top", "left", "bottom", "right", "insideH", "insideV")) +
        '</w:tblBorders></w:tblPr></w:style></w:styles>')


def _numbering(ordered_lists: int) -> str:
    def level(fmt: str, text: str) -> str:
        return (f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>')
    nums = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    nums += "".join(f'<w:num w:numId="{2 + i}"><w:abstractNumId w:val="1"/>'
                    '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
                    for i in range(ordered_lists))
    return _xml(f'<w:numbering xmlns:w="{_W}">'
                f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>{level("bullet", "•")}</w:abstractNum>'
                f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="singleLevel"/>{level("decimal", "%1.")}</w:abstractNum>'
                f'{nums}</w:numbering>')


def _run_xml(run: Run) -> str:
    props = ("<w:b/><w:bCs/>" if run.bold else "") + ("<w:i/><w:iCs/>" if run.italic else "")
    pieces: list[str] = []
    for index, line in enumerate(clean(run.text).split("\n")):
        if index:
            pieces.append("<w:br/>")
        for part_index, part in enumerate(line.split("\t")):
            if part_index:
                pieces.append("<w:tab/>")
            if part:
                pieces.append(f'<w:t xml:space="preserve">{escape(part)}</w:t>')
    return f'<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}{"".join(pieces)}</w:r>'


def _math_xml(math: Math) -> str:
    from deixis.exports.omml import to_omml
    display = math.source.startswith("$$")
    latex = math.source[2:-2] if display else math.source[1:-1]
    return to_omml(latex, display) or _run_xml(Run(math.source))


def _paragraph_xml(block: Paragraph, extra_ppr: str = "", bold: bool = False) -> str:
    style = f'<w:pStyle w:val="{block.style}"/>' if block.style in STYLES else ""
    ppr = style + extra_ppr
    body = "".join(_math_xml(r) if isinstance(r, Math) else _run_xml(Run(r.text, r.bold or bold, r.italic)) for r in block.runs)
    return f'<w:p>{f"<w:pPr>{ppr}</w:pPr>" if ppr else ""}{body}</w:p>'


def _table_xml(table: Table, text_width: int) -> str:
    count = max(len(table.header), max((len(row) for row in table.rows), default=0), 1)
    weights = list(table.widths or ()) + [1.0] * (count - len(table.widths or ()))
    total = sum(weights[:count]) or 1.0
    widths = [max(int(text_width * weight / total), 300) for weight in weights[:count]]
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)

    def cell(value: Union[str, Sequence[Paragraph]], width: int, bold: bool = False) -> str:
        paragraphs = [Paragraph(runs(value))] if isinstance(value, str) else list(value)
        inner = "".join(_paragraph_xml(p, bold=bold) for p in paragraphs) or "<w:p/>"
        return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>{inner}</w:tc>'

    def row(values: Sequence[Union[str, Sequence[Paragraph]]], header: bool = False) -> str:
        padded = list(values) + [""] * (count - len(values))
        props = '<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>' if header else '<w:trPr><w:cantSplit/></w:trPr>'
        return f'<w:tr>{props}{"".join(cell(v, widths[i], header) for i, v in enumerate(padded))}</w:tr>'

    header = row(table.header, True) if table.header else ""
    return (f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
            f'<w:tblLayout w:type="fixed"/><w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" '
            f'w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
            f'{header}{"".join(row(r) for r in table.rows)}</w:tbl><w:p/>')


_MARK = Path(__file__).with_name("deixis-mark.png")  # public/deixis-icon.svg in black, 128 px
_MARK_EMU = 9 * 12700  # drawn 9 pt square


def _footer(text_width: int) -> str:
    """The footer of every page, as an Elicit report has one: the DEIXIS mark and name on the left, the page number on
    the right."""
    mark = ('<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{_MARK_EMU}" cy="{_MARK_EMU}"/><wp:docPr id="1" name="DEIXIS"/>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            '<pic:nvPicPr><pic:cNvPr id="0" name="deixis-mark.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{_MARK_EMU}" cy="{_MARK_EMU}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r>')
    name = (f'<w:r><w:rPr>{_FONT}<w:b/><w:color w:val="111111"/><w:spacing w:val="16"/><w:sz w:val="16"/><w:szCs w:val="16"/>'
            '</w:rPr><w:t xml:space="preserve"> DEIXIS</w:t></w:r>')
    number = '<w:rPr><w:color w:val="111111"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr>'
    page = (f'<w:r>{number}<w:tab/></w:r><w:r>{number}<w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r>{number}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            f'<w:r>{number}<w:fldChar w:fldCharType="separate"/></w:r><w:r>{number}<w:t>1</w:t></w:r>'
            f'<w:r>{number}<w:fldChar w:fldCharType="end"/></w:r>')
    return _xml(f'<w:ftr xmlns:w="{_W}" xmlns:r="{_R}" '
                'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<w:p><w:pPr><w:tabs><w:tab w:val="right" w:pos="{text_width}"/></w:tabs><w:spacing w:before="0" w:after="0"/>'
                f'</w:pPr>{mark}{name}{page}</w:p></w:ftr>')


# Without a compatibility setting Word opens the file in "Compatibility Mode" (Word 2007 layout rules).
_SETTINGS = _xml(f'<w:settings xmlns:w="{_W}"><w:compat><w:compatSetting w:name="compatibilityMode" '
                 'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')


def docx(blocks: Sequence[Block], *, title: str = "", landscape: bool = False) -> bytes:
    """The bytes of a .docx file holding the blocks in order (A4, portrait unless `landscape`)."""
    width, height = (16838, 11906) if landscape else (11906, 16838)
    margin = 1134 if landscape else 1440
    text_width = width - 2 * margin
    ordered = 0
    body: list[str] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            # Body text outside tables is justified (BodyText); table cells keep Normal.
            body.append(_paragraph_xml(block if block.style else Paragraph(block.runs, "BodyText")))
        elif isinstance(block, ListBlock):
            if block.ordered:
                ordered += 1
            num = 1 + ordered if block.ordered else 1
            for item in block.items:
                body.append(_paragraph_xml(Paragraph(item), '<w:pStyle w:val="ListParagraph"/>'
                                           f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num}"/></w:numPr>'))
        elif isinstance(block, Table):
            body.append(_table_xml(block, text_width))
        elif isinstance(block, Rule):
            body.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="A0A0A0"/></w:pBdr>'
                        '</w:pPr></w:p>')
        else:
            raise TypeError(f"not a document block: {type(block).__name__}")
    orient = ' w:orient="landscape"' if landscape else ""
    section = (f'<w:sectPr><w:footerReference w:type="default" r:id="rId3"/><w:pgSz w:w="{width}" w:h="{height}"{orient}/>'
               f'<w:pgMar w:top="{margin}" w:right="{margin}" w:bottom="{margin}" w:left="{margin}" '
               'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
    document = _xml(f'<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:m="{_M}"><w:body>{"".join(body)}{section}</w:body></w:document>')
    main = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    return _zip([
        ("[Content_Types].xml", _content_types(_DEFAULTS | {"png": "image/png"}, {
            "/word/document.xml": f"{main}.document.main+xml", "/word/styles.xml": f"{main}.styles+xml",
            "/word/numbering.xml": f"{main}.numbering+xml", "/word/footer1.xml": f"{main}.footer+xml",
            "/word/settings.xml": f"{main}.settings+xml",
            "/docProps/core.xml": _CORE_TYPE})),
        ("_rels/.rels", _rels([(f"{_DOC_REL}/officeDocument", "word/document.xml"), (_CORE_REL, "docProps/core.xml")])),
        ("word/document.xml", document),
        ("word/_rels/document.xml.rels", _rels([(f"{_DOC_REL}/styles", "styles.xml"), (f"{_DOC_REL}/numbering", "numbering.xml"),
                                                (f"{_DOC_REL}/footer", "footer1.xml"), (f"{_DOC_REL}/settings", "settings.xml")])),
        ("word/footer1.xml", _footer(text_width)),
        ("word/_rels/footer1.xml.rels", _rels([(f"{_DOC_REL}/image", "media/deixis-mark.png")])),
        ("word/media/deixis-mark.png", _MARK.read_bytes()),
        ("word/styles.xml", _styles_docx()),
        ("word/settings.xml", _SETTINGS),
        ("word/numbering.xml", _numbering(ordered)),
        ("docProps/core.xml", _core(title)),
    ])


# ---- XLSX -------------------------------------------------------------------------------------------------------

Cell = Union[str, int, float, None]


@dataclass(frozen=True)
class Sheet:
    """One worksheet: a bold, frozen header row, then rows of string or number cells (None leaves a cell empty)."""
    name: str
    header: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...] = field(default_factory=tuple)
    widths: tuple[float, ...] | None = None  # in characters, per column


def column_name(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def sheet_names(names: Sequence[str]) -> list[str]:
    """Excel's rules: 1-31 characters, none of []:*?/\\, no leading or trailing apostrophe, unique ignoring case."""
    used: set[str] = set()
    result: list[str] = []
    for index, name in enumerate(names, 1):
        base = re.sub(r"[\[\]:*?/\\]", " ", clean(name)).strip().strip("'").strip() or f"Sheet{index}"
        base = base[:31]
        candidate, n = base, 2
        while candidate.lower() in used:
            suffix = f" ({n})"
            candidate, n = base[:31 - len(suffix)] + suffix, n + 1
        used.add(candidate.lower())
        result.append(candidate)
    return result


def _cell_xml(ref: str, value: Cell, style: int) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, (int, float)) and not (isinstance(value, float) and not math.isfinite(value)):
        return f'<c r="{ref}" s="{style}"><v>{value!r}</v></c>'
    text = clean(value)
    if len(text) > EXCEL_CELL_LIMIT:
        text = text[:EXCEL_CELL_LIMIT - 1] + "…"
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    count = max(len(sheet.header), max((len(row) for row in sheet.rows), default=0), 1)
    widths = list(sheet.widths or ()) + [14.0] * (count - len(sheet.widths or ()))
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{max(min(w, 120.0), 4.0):g}" customWidth="1"/>'
                   for i, w in enumerate(widths[:count]))
    rows: list[str] = []
    all_rows = ([(sheet.header, 1)] if sheet.header else []) + [(row, 2) for row in sheet.rows]
    for number, (values, style) in enumerate(all_rows, 1):
        cells = "".join(_cell_xml(f"{column_name(i)}{number}", value, style) for i, value in enumerate(values))
        rows.append(f'<row r="{number}">{cells}</row>')
    pane = ('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>') if sheet.header else ""
    return _xml(f'<worksheet xmlns="{_SML}" xmlns:r="{_R}">'
                f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
                f'<sheetFormatPr defaultRowHeight="15"/><cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData></worksheet>')


def _styles_xlsx() -> str:
    return _xml(
        f'<styleSheet xmlns="{_SML}">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">'
        '<alignment vertical="top" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment vertical="top" wrapText="1"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def xlsx(sheets: Sequence[Sheet], *, title: str = "") -> bytes:
    """The bytes of a .xlsx workbook with one worksheet per sheet, in order."""
    if not sheets:
        raise ValueError("a workbook needs at least one sheet")
    names = sheet_names([sheet.name for sheet in sheets])
    entries = "".join(f'<sheet name="{escape(name, True)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, 1))
    workbook = _xml(f'<workbook xmlns="{_SML}" xmlns:r="{_R}"><bookViews><workbookView/></bookViews>'
                    f'<sheets>{entries}</sheets></workbook>')
    main = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    overrides = {"/xl/workbook.xml": f"{main}.sheet.main+xml", "/xl/styles.xml": f"{main}.styles+xml",
                 "/docProps/core.xml": _CORE_TYPE}
    overrides |= {f"/xl/worksheets/sheet{i}.xml": f"{main}.worksheet+xml" for i in range(1, len(sheets) + 1)}
    workbook_rels = [(f"{_DOC_REL}/worksheet", f"worksheets/sheet{i}.xml") for i in range(1, len(sheets) + 1)]
    workbook_rels.append((f"{_DOC_REL}/styles", "styles.xml"))
    return _zip([
        ("[Content_Types].xml", _content_types(_DEFAULTS, overrides)),
        ("_rels/.rels", _rels([(f"{_DOC_REL}/officeDocument", "xl/workbook.xml"), (_CORE_REL, "docProps/core.xml")])),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", _rels(workbook_rels)),
        ("xl/styles.xml", _styles_xlsx()),
        *((f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet)) for i, sheet in enumerate(sheets, 1)),
        ("docProps/core.xml", _core(title)),
    ])

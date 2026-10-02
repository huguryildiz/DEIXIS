"""Optional TeX measurements of pinned SYNTHETIC bytes, not research validation.

Only the marked tests start TeX. Scanners and dependency checks run everywhere.
The latexmk command advertised in the export is not exercised here.
"""

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import unicodedata

import pytest

from deixis.workflow.report import export_text, latex, latex_preamble
from report_latex_cases import build, claim, section, table, bibrow

PROGRAMS = ("xelatex", "bibtex", "pdftotext", "kpsewhich")
TEX_FILES = ("IEEEtran.cls", "IEEEtran.bst", "fontspec.sty", "cite.sty", "url.sty", "booktabs.sty",
             "longtable.sty", "array.sty", "amsmath.sty", "amssymb.sty", "bm.sty", "xcolor.sty")


def tex_environment():
    return {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}


def missing_tex():
    missing = [program for program in PROGRAMS if shutil.which(program) is None]
    if "kpsewhich" not in missing:
        for name in TEX_FILES:
            result = subprocess.run(["kpsewhich", name], capture_output=True, text=True, timeout=180,
                                    env=tex_environment())
            if not result.stdout.strip():
                missing.append(name)
    return "Missing TeX dependencies: " + ", ".join(missing) if missing else None


_missing = missing_tex()
needs_tex = pytest.mark.skipif(_missing is not None, reason=_missing or "TeX dependencies present")


def scan_log(log_text, *, allow_overfull_hbox=False):
    patterns = [r"Missing character", r"Overfull \\vbox", r"Float too large for page", r"LaTeX Error",
                r"Citation\s+[^\n]*?undefined", r"Reference\s+[^\n]*?undefined",
                r"Label\s+[^\n]*?multiply defined", r"There were undefined references"]
    if not allow_overfull_hbox:
        patterns.append(r"Overfull \\hbox")
    return [line for line in log_text.splitlines() if any(re.search(pattern, line) for pattern in patterns)]


def bibtex_failures(blg_text):
    return [line for line in blg_text.splitlines()
            if re.search(r"error message|I couldn't open|---line", line, re.I)]


def bbl_keys(bbl_text):
    return re.findall(r"\\bibitem(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}", bbl_text)


def cite_keys_in_order(tex_text):
    return list(dict.fromkeys(key.strip() for group in re.findall(r"\\cite\{([^}]+)\}", tex_text)
                             for key in group.split(",")))


def pdf_contains(pdf_text, needle):
    def normalize(text):
        return re.sub(r"[\s\-\u00ad]+", "", unicodedata.normalize("NFKC", text))
    return normalize(needle) in normalize(pdf_text)


def pdf_regions(pdf_text, language):
    headings = {"en": ("Report notes", "References"), "tr": ("Rapor notları", "Kaynaklar")}[language]
    boundaries = []
    for heading in headings:
        pattern = r"^[^\S\r\n]*" + r"\s+".join(map(re.escape, heading.split())) + r"[^\S\r\n]*$"
        matches = list(re.finditer(pattern, pdf_text, re.I | re.M))
        assert len(matches) == 1, f"Expected one PDF heading {heading!r}, found {len(matches)}"
        boundaries.append(matches[0].start())
    notes, bibliography = boundaries
    assert notes < bibliography, "PDF bibliography precedes Report notes"
    return pdf_text[:notes], pdf_text[notes:bibliography], pdf_text[bibliography:]


@pytest.mark.parametrize("language,notes,bibliography", [
    ("en", "Report notes", "References"), ("en", "REPORT NOTES", "REFERENCES"),
    ("tr", "Rapor notları", "Kaynaklar"), ("tr", "RAPOR NOTLARI", "KAYNAKLAR"),
])
def test_pdf_regions_keep_bibliography_copies_separate(language, notes, bibliography):
    text = f"table ENDTABLE\n{notes}\n1.\nlong value ENDNOTE\n{bibliography}\nlong value ENDNOTE\n"
    table_text, notes_text, bibliography_text = pdf_regions(text, language)
    assert table_text == "table ENDTABLE\n"
    assert notes_text == f"{notes}\n1.\nlong value ENDNOTE\n"
    assert bibliography_text == f"{bibliography}\nlong value ENDNOTE\n"
    assert not pdf_contains(table_text, "long value ENDNOTE")
    assert pdf_contains(notes_text, "1. long value ENDNOTE")


@pytest.mark.parametrize("language", ["en", "tr"])
@pytest.mark.parametrize("invalid", ["missing_notes", "missing_bibliography", "reversed", "duplicate"])
def test_pdf_regions_fail_closed(language, invalid):
    notes, bibliography = ("Report notes", "References") if language == "en" else ("Rapor notları", "Kaynaklar")
    texts = {"missing_notes": f"mentions {notes} in prose\n{bibliography}\nsource",
             "missing_bibliography": f"{notes}\nmentions {bibliography} in prose",
             "reversed": f"{bibliography}\nsource\n{notes}\nnotes",
             "duplicate": f"{notes}\nnotes\n{notes}\n{bibliography}\nsource"}
    with pytest.raises(AssertionError):
        pdf_regions(texts[invalid], language)


def test_missing_tex_names_dependencies(monkeypatch):
    absent_programs, absent_files = set(), set()
    monkeypatch.setattr(shutil, "which", lambda name: None if name in absent_programs else "/synthetic/" + name)
    def kpse(command, **kwargs):
        assert command[0] == "kpsewhich"
        return subprocess.CompletedProcess(command, 0, "" if command[1] in absent_files else "/synthetic/file\n", "")
    monkeypatch.setattr(subprocess, "run", kpse)
    assert missing_tex() is None
    absent_programs.update(("xelatex", "bibtex", "pdftotext"))
    absent_files.update(("IEEEtran.cls", "bm.sty"))
    reason = missing_tex()
    assert all(name in reason for name in absent_programs | absent_files)
    absent_programs.add("kpsewhich")
    assert all(name in missing_tex() for name in absent_programs)


@pytest.mark.parametrize("line", ["Missing character: There is no 文", r"Overfull \vbox (2pt too high)",
                                 r"Overfull \hbox (2pt too wide)", "Float too large for page by 3pt",
                                 "! LaTeX Error: Broken", "LaTeX Warning: Citation `a' on page 1 undefined",
                                 "LaTeX Warning: Reference `eq:a' on page 1 undefined",
                                 "LaTeX Warning: Label `eq:a' multiply defined.",
                                 "LaTeX Warning: There were undefined references."])
def test_scan_log_catches_each_failure(line):
    assert scan_log(line) == [line]
    assert scan_log("ordinary log") == []


def test_scan_log_nonfailures_and_single_allowance():
    assert scan_log("LaTeX Font Warning: Font shape `TU/ptm/m/n' undefined\nUnderfull \\hbox") == []
    assert scan_log("Overfull \\hbox", allow_overfull_hbox=True) == []
    assert scan_log("Missing character\nOverfull \\vbox", allow_overfull_hbox=True) == ["Missing character", "Overfull \\vbox"]
    assert len(scan_log("Missing character one\nMissing character two")) == 2


@pytest.mark.parametrize("line", ["(There was 1 error message)", "I couldn't open file x", "bad---line 2"])
def test_bibtex_failure_scanner(line):
    assert bibtex_failures(line) == [line]
    assert bibtex_failures("Warning--empty journal in A") == []


def test_keys_and_pdf_normalization():
    assert bbl_keys(r"\bibitem{B} text \bibitem[Author(2026)]{A} more") == ["B", "A"]
    assert bbl_keys("no items") == []
    assert cite_keys_in_order(r"\cite{B,A} \cite{A,C} \cite{B}") == ["B", "A", "C"]
    assert cite_keys_in_order("no cites") == []
    assert pdf_contains("ofﬁce wrap-\nped soft\u00adhyphen", "office wrapped softhyphen")
    assert not pdf_contains("text", "missing")


def test_overfull_allowance_only_in_explained_fixture():
    tree = ast.parse(Path(__file__).read_text())
    users = []
    for function in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
        if function.name.startswith("test_scan_log"):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and any(keyword.arg == "allow_overfull_hbox" and
                                                isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                                                for keyword in node.keywords):
                users.append(function.name)
    assert users == ["test_unbroken_token_explained_exception"]


@dataclass(frozen=True)
class Compiled:
    log: str
    blg: str
    bbl: str
    pdf_text: str
    pdf: Path


def compile_pair(directory, stem, tex_bytes, bib_bytes, *, bibliography=True):
    directory.mkdir(parents=True, exist_ok=False)
    (directory / f"{stem}.tex").write_bytes(tex_bytes)
    (directory / f"{stem}.bib").write_bytes(bib_bytes)
    xelatex = ["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", f"{stem}.tex"]
    commands = [xelatex, ["bibtex", stem], xelatex, xelatex] if bibliography else [xelatex, xelatex, xelatex]
    for command in commands:
        result = subprocess.run(command, cwd=directory, timeout=180, capture_output=True, env=tex_environment())
        if result.returncode:
            path = directory / f"{stem}.{'log' if command[0] == 'xelatex' else 'blg'}"
            log = path.read_text(errors="replace") if path.exists() else (result.stdout + result.stderr).decode(errors="replace")
            pytest.fail(f"{stem}: {command[0]} exited {result.returncode}\n{log[-6000:]}")
    pdf = directory / f"{stem}.pdf"
    assert pdf.is_file()
    pages = subprocess.run(["pdftotext", pdf.name, "-"], cwd=directory, timeout=180, capture_output=True,
                           env=tex_environment())
    assert pages.returncode == 0, pages.stderr.decode(errors="replace")
    return Compiled((directory / f"{stem}.log").read_text(errors="replace"),
                    (directory / f"{stem}.blg").read_text(errors="replace") if bibliography else "",
                    (directory / f"{stem}.bbl").read_text(errors="replace") if bibliography else "",
                    pages.stdout.decode("utf-8"), pdf)


# Fixed committed bytes, excluding all 16 unbroken-value goldens, all four
# class-B kitchen_sink/math_classes goldens, and the hostile BibTeX author.
GOLDENS = ("plain-en", "plain-tr", "draft_unvalidated-en", "missing_title-en", "edit_current-en", "review_2-en",
           "eq_several-en", "eq_repeated-tr", "keys_versions-en", "ref_order-en", "keyword_cite-en", "corpus-tr", "table_7-en")


def test_golden_selection_is_pinned_and_excludes_known_overfull():
    assert len(GOLDENS) == 13 and len(set(GOLDENS)) == 13
    excluded = {f"{base}-{language}" for base in ("table_cell_400", "table_cell_401", "table_heading_400", "table_heading_401",
                                                 "table_source_200", "table_source_201", "table_parenthetical", "table_math",
                                                 "kitchen_sink", "math_classes", "hostile") for language in ("en", "tr")}
    assert not set(GOLDENS) & excluded


@needs_tex
@pytest.mark.parametrize("name", GOLDENS)
def test_committed_golden_compiles(tmp_path, name):
    fixtures = Path(__file__).parent / "fixtures" / "report_latex"
    tex, bib = (fixtures / f"{name}.tex").read_bytes(), (fixtures / f"{name}.bib").read_bytes()
    # The committed filename is a case id; the bibliography stem is the export stem.
    stem = re.search(rb"\\bibliography\{([^}]+)\}", tex).group(1).decode("ascii")
    result = compile_pair(tmp_path / "compile", stem, tex, bib)
    assert scan_log(result.log) == [], name
    assert bibtex_failures(result.blg) == [], name
    assert bbl_keys(result.bbl) == cite_keys_in_order(tex.decode("utf-8"))
    assert set(bbl_keys(result.bbl)) == set(re.findall(r"^@\w+\{([^,]+),", bib.decode("utf-8"), re.M))
    base, language = name.rsplit("-", 1)
    _, title, _, sources = build(base, language)
    for expected in [title] + [source["title"] for source in sources]:
        assert pdf_contains(result.pdf_text, expected), (name, expected)


def sized_words(size, marker, *, symbols=False):
    prefix = "≥ ≤ α ± × " if symbols else ""
    available = size - len(prefix) - len(marker) - 1
    assert available >= 0
    body = ("data " * (available // 5) + "a" * (available % 5))
    text = prefix + body + " " + marker
    assert len(text) == size
    assert max(map(len, text.split())) <= 12
    return text


def wide_fixture(n, language):
    view, title, corpus, _ = build("plain", language)
    t = table(n, rows=12)
    sources = []
    refs = []
    for index, row in enumerate(t["rows"]):
        version = f"s{index + 1}"
        marker = "END" + chr(97 + index) + "srcz"
        # source_cell adds '[n] '; the threshold is on that final string.
        prefix = f"[{index + 1}] "
        length = 200 if index == 0 else 201 if index == 1 else 500 if index == 2 else 36
        source_title = sized_words(length - len(prefix), marker)
        row.update(source_version_id=version, source_key=None, ref_number=index + 1, title=source_title)
        sources.append(bibrow(version) | {"title": source_title})
        refs.append(dict(number=index + 1, source_key=None, **sources[-1]))
    for index, column in enumerate(t["columns"]):
        column["name"] = sized_words(400 if index == 0 else 401 if index == 1 else 500 if index == 3 else 28,
                                      "END" + chr(97 + index) + "headz")
    # Rebuild cells after source-version identities have been assigned.
    t["cells"] = []
    for r, row in enumerate(t["rows"]):
        for c, column in enumerate(t["columns"]):
            marker = "END" + chr(97 + r) + chr(97 + c) + "cellz"
            size = 400 if (r, c) == (0, 0) else 500 if (r, c) == (1, 0) else 45
            value = sized_words(size, marker, symbols=r == 2)
            cell = dict(source_version_id=row["source_version_id"], column_id=column["column_id"], state="value")
            if c == 2 and r in (0, 1, 2):
                # An option label, rather than a text value, crosses the same final-cell threshold.
                value = sized_words(400 + r if r < 2 else 500, marker)
                option_id = f"opt{r}"
                column["options"].append({"id": option_id, "label": value})
                cell["value"] = {"option_ids": [option_id]}
            else:
                cell["value"] = {"text": value}
            t["cells"].append(cell)
            formatted = export_text.cell_text(cell, column, language == "tr", str)
            assert formatted == value
    view.update(table_i=t, references=refs)
    view["sections"] = [section("I", [claim("SYNTHETIC cited rows.", tuple(ref["source_version_id"] for ref in refs))]),
                        section("IV", [claim("SYNTHETIC table follows.", (), table_ref="TABLE_I")])]
    for link, ref in zip(view["sections"][0]["claims"][0]["evidence"], refs):
        link["ref_number"] = ref["number"]
    assert [len(export_text.source_cell(row, language == "tr", str)) for row in t["rows"][:2]] == [200, 201]
    assert [len(col["name"]) for col in t["columns"][:2]] == [400, 401]
    assert [len(option["label"]) for option in t["columns"][2]["options"][1:]] == [400, 401, 500]
    return view, title, corpus, sources


def wide_table_expectations(view, language):
    tr = language == "tr"
    table_i = view["table_i"]
    inline, moved = [], []

    def record(raw, threshold, position, label=None):
        if len(raw) <= threshold:
            inline.append(raw)
            return raw
        moved.append((position, label, raw))
        number = len(moved)
        return f"{number} numaralı nota bakın" if tr else f"see note {number}"

    # Contract order: headings, then each row's source and cells. Positions own
    # numbers; column groups reuse them. Expectations never read generated TeX.
    headings = [record(column["name"], 400, f"Sütun {c} başlığı" if tr else f"Column {c} heading")
                for c, column in enumerate(table_i["columns"], 1)]
    cells = {(cell["source_version_id"], cell["column_id"]): cell for cell in table_i["cells"]}
    rows = []
    for r, row in enumerate(table_i["rows"], 1):
        assert row["source_key"] is None
        label = f"[{row['ref_number']}]"
        source = record(label + " " + row["title"], 200, f"Satır {r} kaynağı" if tr else f"Row {r} source", label)
        values = [record(export_text.cell_text(cells[(row["source_version_id"], column["column_id"])], column, tr, str),
                         400, f"Satır {r}, sütun {c}" if tr else f"Row {r}, column {c}", label)
                  for c, column in enumerate(table_i["columns"], 1)]
        rows.append([source, *values])
    return headings, rows, inline, moved


def numbered_pdf_notes(notes_text):
    # pdftotext wraps note bodies; the number may also occupy its own line.
    starts = list(re.finditer(r"^[^\S\r\n]*(\d+)\.\s", notes_text, re.M))
    notes = {}
    for index, match in enumerate(starts):
        number = int(match.group(1))
        assert number not in notes, ("duplicate note number", number)
        end = starts[index + 1].start() if index + 1 < len(starts) else len(notes_text)
        notes[number] = notes_text[match.end():end]
    return notes


def pdf_note_pointer_pattern(language):
    return (r"(?<!\d)(\d+)(?!\d)\s+numaralı\s+nota\s+bakın\b" if language == "tr"
            else r"\bsee\s+note\s+(\d+)(?!\d)")


def pdf_contains_table_positions(table_text, expected, language):
    # Delimit parsed integers before whitespace normalization, so the final
    # cell's note 1 cannot match note 11. Longtable may repeat entire headers.
    def mark_numbers(text):
        return re.sub(pdf_note_pointer_pattern(language), lambda match: f"NOTE_POINTER[{int(match.group(1))}]", text)
    return pdf_contains(mark_numbers(table_text), mark_numbers(expected))


def assert_wide_table_pdf(pdf_text, raw_pdf_text, view, language):
    table_text, notes_text, bibliography_text = pdf_regions(pdf_text, language)
    raw_table_text, raw_notes_text, _ = pdf_regions(raw_pdf_text, language)
    headings, rows, inline, moved = wide_table_expectations(view, language)
    for value in inline:
        assert pdf_contains(table_text, value), ("inline table value", value)
        assert pdf_contains(table_text, value.split()[-1]), ("inline end marker", value)
    assert pdf_contains(notes_text, "Uzun tablo değerleri" if language == "tr" else "Long table values")
    note_maps = [numbered_pdf_notes(text) for text in (notes_text, raw_notes_text)]
    for notes in note_maps:
        assert set(notes) == set(range(1, len(moved) + 1)), ("note number set", sorted(notes))
    for text in (table_text, raw_table_text):
        pointers = {int(number) for number in re.findall(pdf_note_pointer_pattern(language), text)}
        assert pointers == set(note_maps[0]), ("table note pointer number set", pointers)
    for number, (position, label, value) in enumerate(moved, 1):
        prefix = position + (f" ({label})" if label is not None else "") + ": "
        marker = value.split()[-1]
        for notes in note_maps:
            assert pdf_contains(notes[number], prefix + value), ("complete numbered note", number, position, value)
            assert pdf_contains(notes[number], marker), ("note end marker", number, marker)
            owners = {k for k, text in notes.items() if pdf_contains(text, value)}
            assert owners == {number}, ("note value owners", number, owners)
        assert not pdf_contains(table_text, value), ("long value printed inline", number, position)
        assert not pdf_contains(table_text, marker), ("long value end marker printed inline", number, marker)
    # -raw keeps content-stream cell order. Checking whole headers and rows
    # catches swapped pointers even when every expected number occurs somewhere.
    for start in range(0, len(headings), 7):
        header = [export_text.source_heading(language == "tr"), *headings[start:start + 7]]
        assert pdf_contains_table_positions(raw_table_text, " ".join(header), language), ("table header positions", start)
        for r, row in enumerate(rows, 1):
            row_text = " ".join([row[0], *row[start + 1:start + 8]])
            assert pdf_contains_table_positions(raw_table_text, row_text, language), ("table row positions", r, start)
    for row in view["table_i"]["rows"]:
        assert pdf_contains(bibliography_text, row["title"]), ("bibliography title", row["source_version_id"])


def synthetic_wide_table_pdf(language):
    view, _, _, _ = wide_fixture(8, language)
    headings, rows, _, moved = wide_table_expectations(view, language)
    notes_heading, bibliography_heading = ("Report notes", "References") if language == "en" else ("Rapor notları", "Kaynaklar")
    table_text = "\n".join(" ".join(values) for start in (0, 7)
                           for values in [[export_text.source_heading(language == "tr"), *headings[start:start + 7]],
                                          *[[row[0], *row[start + 1:start + 8]] for row in rows]])
    entries = [textwrap.fill(f"{number}. {position}" + (f" ({label})" if label is not None else "") + ": " + value, width=60)
               for number, (position, label, value) in enumerate(moved, 1)]
    notes_text = "\n".join([notes_heading, "Uzun tablo değerleri" if language == "tr" else "Long table values", *entries])
    bibliography_text = bibliography_heading + "\n" + "\n".join(row["title"] for row in view["table_i"]["rows"])
    return view, table_text, notes_text, bibliography_text, entries


@pytest.mark.parametrize("language", ["en", "tr"])
def test_wide_table_pdf_rejects_missing_values_and_swapped_notes(language):
    view, table_text, notes_text, bibliography_text, entries = synthetic_wide_table_pdf(language)

    def document(table_region, notes_region):
        return "\n".join((table_region, notes_region, bibliography_text))

    pdf_text = document(table_text, notes_text)
    assert_wide_table_pdf(pdf_text, pdf_text, view, language)
    pointer1, pointer2 = (f"{k} numaralı nota bakın" if language == "tr" else f"see note {k}" for k in (1, 2))
    swapped = table_text.replace(pointer1, "SYNTHETIC_POINTER").replace(pointer2, pointer1).replace("SYNTHETIC_POINTER", pointer2)
    broken_documents = [document(table_text.replace(view["table_i"]["rows"][0]["title"], ""), notes_text),
                        document(table_text, notes_text.replace(entries[2], "")),
                        document(table_text, notes_text.replace(entries[0], entries[0].replace("1.", "2.", 1))
                                 .replace(entries[1], entries[1].replace("2.", "1.", 1))),
                        document(table_text, notes_text + "\n99. Unexpected note\n"),
                        document(table_text, notes_text + "\n" + entries[0]),
                        document(table_text, notes_text.replace(entries[1], entries[1] + "\n" + entries[0].split(": ", 1)[1])),
                        document(swapped, notes_text)]
    for broken in broken_documents:
        with pytest.raises(AssertionError):
            assert_wide_table_pdf(broken, broken, view, language)


@pytest.mark.parametrize("language", ["en", "tr"])
@pytest.mark.parametrize("number", [1, 2])
@pytest.mark.parametrize("region", ["notes", "cell", "repeated_header"])
def test_wide_table_pdf_rejects_note_number_digit_suffix(language, number, region):
    view, table_text, notes_text, bibliography_text, _ = synthetic_wide_table_pdf(language)
    pdf_text = "\n".join((table_text, notes_text, bibliography_text))
    assert_wide_table_pdf(pdf_text, pdf_text, view, language)
    if region == "notes":
        notes_text, changed = re.subn(rf"^{number}\. ", f"{number + 10}. ", notes_text, count=1, flags=re.M)
    else:
        if region == "repeated_header":
            table_text = table_text.splitlines()[0] + "\n" + table_text
        pattern = (rf"(?<!\d){number}(?!\d)(?=\s+numaralı\s+nota\s+bakın)" if language == "tr"
                   else rf"(?<=see note ){number}(?!\d)")
        table_text, changed = re.subn(pattern, str(number + 10), table_text, count=1)
    assert changed == 1
    broken = "\n".join((table_text, notes_text, bibliography_text))
    with pytest.raises(AssertionError):
        assert_wide_table_pdf(broken, broken, view, language)


@pytest.mark.parametrize("language", ["en", "tr"])
@pytest.mark.parametrize("number", [1, 2])
def test_table_position_rejects_final_pointer_digit_suffix(language, number):
    pointer = f"{number} numaralı nota bakın" if language == "tr" else f"see note {number}"
    wrong_pointer = f"{number + 10} numaralı nota bakın" if language == "tr" else f"see note {number + 10}"
    expected = "SYNTHETIC cell " + pointer
    assert pdf_contains_table_positions("SYNTHETIC cell\n" + pointer, expected, language)
    assert not pdf_contains_table_positions("SYNTHETIC cell\n" + wrong_pointer, expected, language)


@needs_tex
@pytest.mark.parametrize("n,language,groups", [(8, "en", 2), (13, "en", 2), (20, "en", 3), (13, "tr", 2)])
def test_wide_table_keeps_every_value(tmp_path, n, language, groups):
    view, title, corpus, sources = wide_fixture(n, language)
    assert (latex.HEADING_THRESHOLD, latex.CELL_THRESHOLD, latex.SOURCE_THRESHOLD) == (400, 400, 200)
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    assert bundle.tex.count(r"\begin{longtable}") == groups
    assert ("see note" if language == "en" else "numaralı nota bakın") in bundle.tex
    result = compile_pair(tmp_path / "compile", bundle.stem, bundle.tex.encode("utf-8"), bundle.bib.encode("utf-8"))
    assert scan_log(result.log) == [], (n, language, scan_log(result.log))
    assert bibtex_failures(result.blg) == []
    raw = subprocess.run(["pdftotext", "-raw", str(result.pdf), "-"], timeout=180, capture_output=True,
                         env=tex_environment())
    assert raw.returncode == 0, raw.stderr.decode(errors="replace")
    assert_wide_table_pdf(result.pdf_text, raw.stdout.decode("utf-8"), view, language)
    captions = re.findall(r"TABLE\s+([IVX]+)", result.pdf_text)
    assert set(captions) == {"I"} and len(captions) >= groups
    assert bbl_keys(result.bbl) == [f"ref{ref['number']}" for ref in view["references"]]


@needs_tex
def test_unbroken_token_explained_exception(tmp_path):
    view, title, corpus, sources = build("table_7", "en")
    view["table_i"]["cells"][0]["value"] = {"text": "W" * 150}
    bundle = latex.to_latex(view, title=title, corpus=corpus, bib_sources=sources)
    result = compile_pair(tmp_path / "compile", bundle.stem, bundle.tex.encode("utf-8"), bundle.bib.encode("utf-8"))
    assert r"Overfull \hbox" in result.log
    assert scan_log(result.log, allow_overfull_hbox=True) == []
    assert bibtex_failures(result.blg) == []


@needs_tex
def test_real_log_negative_control(tmp_path):
    tex = latex_preamble.PREAMBLE + "\\begin{document}\n文 \\cite{absent}\n\\end{document}\n"
    # Deliberately no bibliography: BibTeX would fail before the final negative-control log.
    result = compile_pair(tmp_path / "compile", "negative", tex.encode("utf-8"), b"", bibliography=False)
    failures = scan_log(result.log)
    assert any("Missing character" in failure for failure in failures)
    assert any("Citation" in failure and "undefined" in failure for failure in failures)

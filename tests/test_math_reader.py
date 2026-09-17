"""Equation reading with Marker (D52): page selection, Markdown cleanup and the reader process protocol.

Marker itself is not installed in tests; a fake runner speaks the same line protocol. Passing these tests says nothing
about how well Marker reads equations.
"""

import asyncio
import sys
from pathlib import Path

import pymupdf
import pytest

from deixis.documents import marker_runner, math_reader, pdf

FAKE_RUNNER = '''
import json, os, sys
replies = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
print("library noise on stdout")
replies.write(json.dumps({"ready": True, "marker_version": "0.0-fake"}) + "\\n")
for line in sys.stdin:
    request = json.loads(line)
    if request["path"].endswith("broken.pdf"):
        replies.write(json.dumps({"id": request["id"], "error": "ValueError: broken"}) + "\\n")
        continue
    pages = {str(p): f"## {p + 1}. Model\\n\\nWe set $x_{{i}}$ and\\n\\n$$E = mc^2 \\\\tag{{{p + 1}}}$$\\n\\n![](_page_0.jpeg)" for p in request["pages"]}
    equations = {str(p): [{"bbox": [72, 90, 300, 110], "latex": "E = mc^2", "page_bbox": [0, 0, 612, 792]}] for p in request["pages"]}
    replies.write(json.dumps({"id": request["id"], "pages": pages, "equations": equations, "seconds": 0.1}) + "\\n")
'''


def fake_runtime(tmp_path, monkeypatch):
    paths = math_reader.RuntimePaths(tmp_path / "tools")
    paths.python.parent.mkdir(parents=True)
    paths.python.symlink_to(sys.executable)
    runner = tmp_path / "fake_runner.py"
    runner.write_text(FAKE_RUNNER)
    monkeypatch.setattr(math_reader, "RUNNER", runner)
    return paths


def test_reader_serves_requests_from_one_process_and_reports_errors(tmp_path, monkeypatch):
    reader = math_reader.MathReader(fake_runtime(tmp_path, monkeypatch))

    async def scenario():
        first = await reader.read(tmp_path / "paper.pdf", [2, 4])
        process = reader.process
        with pytest.raises(RuntimeError, match="broken"):
            await reader.read(tmp_path / "broken.pdf", [0])
        second = await reader.read(tmp_path / "paper.pdf", [0])
        same = reader.process is process
        await reader.close()
        return first, second, same

    first, second, same = asyncio.run(scenario())
    assert sorted(first.pages) == [2, 4] and first.pages[2] == "3. Model\n\nWe set $x_{i}$ and\n\n$$E = mc^2 \\tag{3}$$"
    assert second.pages == {0: "1. Model\n\nWe set $x_{i}$ and\n\n$$E = mc^2 \\tag{1}$$"}
    assert second.equations == {0: [{"bbox": [72, 90, 300, 110], "latex": "E = mc^2", "page_bbox": [0, 0, 612, 792]}]}
    assert same and reader.version == "marker-0.0-fake"


def test_reader_without_the_runtime_is_unavailable(tmp_path):
    reader = math_reader.MathReader(math_reader.RuntimePaths(tmp_path / "tools"))
    assert not reader.available()
    with pytest.raises(math_reader.MathReaderUnavailable):
        asyncio.run(reader.read(tmp_path / "paper.pdf", [0]))
    assert asyncio.run(reader.read(tmp_path / "paper.pdf", [])).pages == {}


def test_math_pages_selects_pages_set_in_math_fonts_or_symbols(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "SYNTHETIC prose about channel scheduling without formulas.", fontsize=10)
    doc.new_page().insert_text((72, 100), "abgdlmps" * 10, fontname="symb", fontsize=10)  # 80 characters in the Symbol font
    doc.new_page().insert_text((72, 100), "∑ ∫ ≤ ≥ ∈ α β γ δ λ μ σ θ", fontname="helv", fontsize=10)
    path = tmp_path / "math.pdf"
    doc.save(path)
    assert math_reader.math_pages(path) == [1]  # helv cannot draw the symbols, so page 3 has no symbol text


def test_markdown_cleanup_keeps_math_and_drops_layout_markup():
    markdown = ('<span id="page-3-0"></span># IV. **Model**\n\nBER=1 $\\times$ 10<sup>-4</sup> and H<sub>2</sub>O, *italic* text'
                ' &amp; more<br>next\n\n\n\n![](_page_3_Figure_2.jpeg)\n\n$$a_{i} * b$$')
    assert math_reader.clean_markdown(markdown) == (
        "IV. Model\n\nBER=1 $\\times$ 10$^{-4}$ and H$_{2}$O, italic text & more\nnext\n\n$$a_{i} * b$$")


def test_runner_splits_marker_paginated_output():
    markdown = "\n\n{3}" + "-" * 48 + "\n\nPage four text.\n\n{7}" + "-" * 48 + "\n\n$$x$$\n"
    assert marker_runner.split_pages(markdown) == {"3": "Page four text.", "7": "$$x$$"}


def test_an_equation_with_a_letter_the_text_layer_lacks_is_marked_to_check(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "SYNTHETIC equation page", fontsize=10)  # outside the equation's box
    page.insert_text((72, 100), "x T + x I = 2 (4)", fontsize=10)
    doc.new_page()  # no text: nothing to check against
    path = tmp_path / "eq.pdf"
    doc.save(path)
    box = [70, 85, 300, 105]
    equations = {0: [{"bbox": box, "latex": "x_{\\mathrm{T}} + x_{\\mathrm{I}} = 2 \\tag{4}"},  # the \\tag number is not compared
                     {"bbox": box, "latex": "\\begin{split} x_{T} + x_{T} &= 2 \\end{split}"},  # X_I read as X_T: one T too many
                     {"bbox": box, "latex": "x_T + x_I = 3"}],
                 1: [{"bbox": box, "latex": "y = 7"}]}
    marked = math_reader.check_equations(path, equations)
    assert [m["latex"] for m in marked] == [e["latex"] for e in equations[0][1:]] and {m["page"] for m in marked} == {1}
    assert math_reader.latex_letters("\\alpha_{i} + \\operatorname{Var}(\\mu)") == math_reader.latex_letters("α i Var µ")


def test_table_pages_select_pages_with_a_table_caption(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "SYNTHETIC prose.\nTable 1 shows the results in words.", fontsize=10)
    doc.new_page().insert_text((72, 100), "SYNTHETIC page\nTABLE 1 | Strains and outcomes.", fontsize=10)
    doc.new_page().insert_text((72, 100), "TABLE IV\nSYNTHETIC SIMULATION PARAMETERS", fontsize=10)
    path = tmp_path / "tables.pdf"
    doc.save(path)
    assert math_reader.table_pages(path) == [1, 2]


def test_markdown_tables_keep_one_line_per_row():
    markdown = ("TABLE 1 | SYNTHETIC outcomes.\n\n| Strain<br>tested | Observations    |\n|--------------|:---------------:|\n"
                "| B. **lactis** X1 | Lower TNF-α<br>secretion |")
    assert math_reader.clean_markdown(markdown) == (
        "TABLE 1 | SYNTHETIC outcomes.\n\n| Strain tested | Observations |\n| --- | --- |\n| B. lactis X1 | Lower TNF-α secretion |")


def test_page_chunks_do_not_cut_a_table_row():
    rows = "\n".join(f"| SYNTHETIC strain {i} | Observation number {i} with some words. More words here | Ref {i} |" for i in range(40))
    for limit in range(300, 400, 7):  # wherever the length limit falls within a row
        chunks = pdf.chunk_page("TABLE 1 | Caption.\n\n" + rows, limit=limit)
        lines = [line for _, _, piece in chunks for line in piece.split("\n") if line]
        assert len(chunks) > 1 and lines[0] == "TABLE 1 | Caption." and all(line.startswith("| ") and line.endswith(" |") for line in lines[1:])

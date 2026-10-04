"""Matching source equations to their numbers on the page and placing them (slice 22, D104, decisions 4 and 5).

Every PDF is SYNTHETIC, built with PyMuPDF: prose lines, equation lines of plain letters and numbers at the right margin.
Passing shows the rules as written, not how often they are right on real papers (acceptance (a) and (f) look at that).
"""

import asyncio
import re
from functools import partial

import pymupdf
import pytest

from arxiv_helpers import PROSE, make_arxiv_pdf, no_network, source_archive  # noqa: F401
from deixis.documents import arxiv_source as src
from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow.store import Store

TOP = ["SYNTHETIC. We study a simple model of signal detection in which the receiver counts the",
       "particles that arrive within each interval and compares the count with a threshold chosen",
       "in advance. The quantities below are defined once and then used throughout this paper."]


def build(tmp_path, pages, name="paper.pdf"):
    """pages: lists of (x, y, text) or (x, y, text, size); inserted in order, which is the text layer's reading order."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        for item in lines:
            x, y, text, size = (*item, 10) if len(item) == 3 else item
            page.insert_text((x, y), text, fontsize=size, fontname="helv")
    path = tmp_path / name
    path.write_bytes(doc.tobytes())
    return path


def top(y=90):
    return [(72, y + 14 * k, line) for k, line in enumerate(TOP)]


def equation(y, printed, number, x=200):
    return [(x, y, printed), (520, y, f"({number})")]


def prose(y, text="where the symbols keep the meaning they have in the model defined above."):
    return [(72, y, text)]


def tex(body):
    return "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"


def eq(latex):
    return f"\\begin{{equation}}\n{latex}\n\\end{{equation}}\n"


def run(path, body, skip=()):
    found, _ = src.source_groups({"main.tex": tex(body)})
    return src.match(path, found, set(skip))


def rows_by_number(result):
    return {r["n"]: r for r in result["rows"]}


def test_the_right_group_is_chosen_and_the_constants_are_named(tmp_path):
    path = build(tmp_path, [top() + equation(160, "P a b = c d", 1) + prose(190) + equation(230, "Q m n = r s t", 2) + prose(260)])
    result = run(path, eq("P_{a b} = c_{d}") + eq("Q_{m} n = r \\frac{s}{t}"))
    assert [(p["n"], p["latex"]) for p in result["placements"]] == [("1", "P_{a b} = c_{d}"), ("2", "Q_{m} n = r \\frac{s}{t}")]
    assert src.PARAMS == {"min_recall": 0.9, "min_margin": 0.2, "prose_words": 3, "max_region_lines": 12, "order_score_offset": 0.5,
                          "absorb_overlap": 0.5, "max_group_chars": 4000, "max_macro_depth": 8, "max_expander_calls": 20000}


def test_two_groups_with_the_same_letters_are_told_apart_by_their_order(tmp_path):
    path = build(tmp_path, [top() + equation(160, "x + y = z", 1) + prose(190) + equation(230, "z = x + y", 2) + prose(260)])
    result = run(path, eq("x + y = z") + eq("z = x + y"))
    assert [(p["n"], p["group"]) for p in result["placements"]] == [("1", 0), ("2", 1)]
    assert all(p["order_decided"] and p["paper_margin"] == 0 for p in result["placements"])


def test_a_recall_under_ninety_percent_is_not_placed(tmp_path):
    path = build(tmp_path, [top() + equation(160, "a b c d e f g", 1) + prose(190)])
    row = rows_by_number(run(path, eq("a b c d e f g h")))["1"]
    assert row["recall"] < src.MIN_RECALL and row["reason"] == "below_threshold" and not row["candidate"]


def test_a_close_competitor_in_the_window_leaves_the_number_unplaced(tmp_path):
    path = build(tmp_path, [top() + equation(160, "a b c d e f", 1) + prose(190)])
    row = rows_by_number(run(path, eq("a b c d e f") + eq("a b c d e g")))["1"]
    assert row["window_margin"] < src.MIN_MARGIN and row["reason"] == "below_threshold"


def test_the_order_never_overrules_letters_that_score_another_group_higher(tmp_path):
    path = build(tmp_path, [top() + equation(160, "p q r s t u", 1) + prose(190) + equation(230, "w x y z", 2) + prose(260)])
    rows = rows_by_number(run(path, eq("p q r s t v") + eq("w x y z") + eq("p q r s t u")))
    assert rows["1"]["group"] == 0 and rows["1"]["window_margin"] >= src.MIN_MARGIN and rows["1"]["paper_margin"] < 0
    assert rows["1"]["reason"] == "below_threshold" and rows["2"]["placed"]


def test_a_number_at_the_end_of_a_prose_line_is_not_an_equation_number(tmp_path):
    path = build(tmp_path, [top() + [(72, 160, "as the analysis of the receiver in the model shows in (3)")]])
    assert run(path, eq("a = b"))["number_lines"] == 0


def test_an_unnumbered_group_added_to_the_source_does_not_change_the_assignment(tmp_path):
    path = build(tmp_path, [top() + equation(160, "P a b = c d", 1) + prose(190) + equation(230, "Q m n = r s t", 2) + prose(260)])
    body = eq("P_{a b} = c_{d}") + eq("Q_{m} n = r \\frac{s}{t}")
    with_unnumbered = eq("P_{a b} = c_{d}") + "\\[ P a b = c d \\]\n" + eq("Q_{m} n = r \\frac{s}{t}")
    assert [p["latex"] for p in run(path, body)["placements"]] == [p["latex"] for p in run(path, with_unnumbered)["placements"]]


def test_a_where_line_before_the_region_is_trimmed_and_stays_in_the_page_text(tmp_path):
    path = build(tmp_path, [top() + [(72, 150, "where")] + equation(170, "f x = z", 1) + prose(200)])
    placement = run(path, eq("f_{x} = z"))["placements"][0]
    lines = src.page_lines(pymupdf.open(path)[0])
    kept = [line["text"] for line in lines if list(line["key"]) in placement["lines"]]
    assert kept == ["f x = z", "(1)"]
    text = pdf.extract_pdf(path, placements=[placement]).pages[0].text
    assert "where\n\n$$\nf_{x} = z\n$$ (1)" in text or "where\n$$\nf_{x} = z\n$$ (1)" in text


def test_a_vertically_overlapping_part_of_the_same_equation_is_absorbed(tmp_path):
    lines = top() + [(222, 167, "max", 7)] + equation(174, "f x y = z", 1, x=220) + prose(200)
    path = build(tmp_path, [lines])
    placement = run(path, eq("\\max_{y} f(x) = z"))["placements"][0]
    assert len(placement["lines"]) == 3
    text = pdf.extract_pdf(path, placements=[placement]).pages[0].text
    assert "max" not in text.replace("\\max", "") and "$$\n\\max_{y} f(x) = z\n$$ (1)" in text


def test_a_region_holding_other_words_is_not_placed(tmp_path):
    lines = top() + [(200, 160, "section of G n")] + equation(174, "= H k + K p", 1) + prose(200)
    row = rows_by_number(run(build(tmp_path, [lines]), eq("G_{n} = H_{k} + K_{p}")))["1"]
    assert row["reason"] == "foreign_text" and "section" in row["foreign"]


def test_a_group_whose_number_is_on_its_first_row_is_not_placed(tmp_path):
    path = build(tmp_path, [top() + equation(160, "o = p", 1) + [(200, 176, "q = r")] + prose(200)])
    result = run(path, "\\begin{align} o &= p \\\\ q &= r \\nonumber \\end{align}\n")
    assert rows_by_number(result)["1"]["reason"] == "continues_after_number" and result["placements"] == []


def test_table_caption_and_ocr_pages_get_no_placement(tmp_path):
    page = top() + equation(160, "P a b = c d", 1) + prose(190)
    path = build(tmp_path, [page + [(72, 300, "TABLE I")], page])
    result = run(path, eq("P_{a b} = c_{d}") + eq("P_{a b} = c_{d} + 0"))
    reasons = {r["page"]: r["reason"] for r in result["rows"] if r["candidate"]}
    assert reasons[1] == "table_or_ocr_page"
    assert run(build(tmp_path, [page], "b.pdf"), eq("P_{a b} = c_{d}"), skip=[1])["placements"] == []


# ---- placement (decision 5) --------------------------------------------------------------------------------------------
def old_page_text(blocks, height, body_size):
    """The page text before slice 22, kept here to show an extraction that places nothing is unchanged byte for byte."""
    body, notes = [], []
    for block in blocks:
        text = pdf._join_lines(block["lines"])
        compact = re.sub(r"\s+", " ", text).strip()
        small = body_size > 0 and block["size"] < body_size * pdf.SMALL_TYPE
        if re.fullmatch(r"\d{1,4}", compact):
            continue
        if small and block["bbox"][3] < height * pdf.TOP_MARGIN:
            continue
        if len(block["lines"]) <= 2 and len(compact) <= 80 and pdf.HEADING.fullmatch(compact):
            body.append(compact)
        elif small:
            notes.append(text)
        else:
            body.append(text)
    return "\n\n".join(pdf._paragraphs(body) + pdf._paragraphs(notes))


def test_an_extraction_that_places_nothing_is_unchanged(tmp_path):
    path = build(tmp_path, [top() + [(72, 40, "Running head of the paper", 6), (300, 760, "7")] + equation(160, "P a b = c d", 1)
                            + [(72, 200, "III. RESULTS")] + prose(230) + [(72, 700, "A footnote set in small type.", 7)]])
    with pymupdf.open(path) as doc:
        layouts = [(0, None, doc[0].rect.height, pdf._blocks(doc[0]))]
        body = pdf._body_size(layouts)
        assert pdf._page_text(layouts[0][3], layouts[0][2], body) == old_page_text(layouts[0][3], layouts[0][2], body)
    plain, empty = pdf.extract_pdf(path), pdf.extract_pdf(path, placements=[])
    assert [p.text for p in plain.pages] == [p.text for p in empty.pages] and plain.placement is None
    assert pdf.chunk_page("a  b\t c\n\nd") == [(0, 8, "a b c\n\nd")]


def test_placed_offsets_point_exactly_at_the_block_and_the_rest_of_the_page_is_kept(tmp_path):
    path = build(tmp_path, [top() + equation(160, "P a b = c d", 1) + prose(190) + equation(230, "Q m n = r s t", 2) + prose(260)])
    result = run(path, eq("P_{a b} = c_{d}") + eq("Q_{m} n = r \\frac{s}{t}"))
    extraction = pdf.extract_pdf(path, placements=result["placements"])
    page = extraction.pages[0]
    normalized = pdf.normalize_page_text(page.text)
    for start, end, number in page.latex_blocks:
        assert normalized[start:end].endswith(f"$$ ({number})") and normalized[start:end].startswith("$$\n")
    assert page.text.startswith("\n".join(TOP)) and page.text.count("where the symbols keep the meaning") == 2
    assert "P a b = c d" not in page.text and "(1)" in page.text


def test_a_region_line_that_never_reaches_the_page_text_is_not_placed(tmp_path):
    lines = top() + [(72, 40, "a b", 6)] + equation(300, "c d e f g h i j", 1) + prose(330)
    path = build(tmp_path, [lines])
    result = run(path, eq("a b c d e f g h i j"))
    assert len(result["placements"]) == 1
    extraction = pdf.extract_pdf(path, placements=result["placements"])
    assert extraction.placement == {"placed": [], "refused": [{"page": 1, "n": "1", "reason": "not_in_page_text"}]}
    assert "$$" not in extraction.pages[0].text


def test_chunks_never_cut_a_placed_block_in_a_source_reading_and_cut_as_before_otherwise():
    text = "x" * 1300 + ". " + "$$\n" + "a" * 300 + "\n$$ (4)" + " tail."
    kept = pdf.chunk_page(text, keep_display_math=True)
    assert any("$$\n" + "a" * 300 + "\n$$ (4)" in piece for _, _, piece in kept)
    assert not any("$$\n" + "a" * 300 + "\n$$ (4)" in piece for _, _, piece in pdf.chunk_page(text))


def test_whitespace_notice_and_a_split_page_keep_one_offset_space(tmp_path):
    notice = ("Authorized licensed use limited to: SYNTHETIC University. Downloaded on May 01,2020 at 10:00:00 UTC from IEEE Xplore."
              "  Restrictions apply.\n")
    block = pdf.display_block("A_{1}  +\tB", "5")  # a LaTeX with a double space and a tab
    raw = "  Leading\tspaces  and\t\ttabs in prose.\n" + notice + "More  prose " + "w " * 400 + "\n\n" + block + "\n\nAfter the block."
    text = pdf.remove_download_notices(raw)
    placed = pdf._block_offsets(text, [{"n": "5", "block": block}])
    assert placed == [{"n": "5", "start": placed[0]["start"], "end": placed[0]["end"]}]
    normalized = pdf.normalize_page_text(text)
    assert normalized[placed[0]["start"]:placed[0]["end"]] == pdf.normalize_page_text(block) == "$$\nA_{1} +\tB\n$$ (5)".replace("\t", " ")
    assert pdf._block_offsets(text, [{"n": "5", "block": pdf.display_block("A_{2} + B", "5")}]) == [{"n": "5", "reason": "offsets_unresolved"}]

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC")
    page = pdf.PageText(1, None, text, latex_blocks=[(placed[0]["start"], placed[0]["end"], "5")])
    chunker = partial(pdf.chunk_page, limit=700, keep_display_math=True)
    store.add_asset_with_pages(svid, "sha", 1, "a.pdf", "user_upload", None, "a.pdf", pdf.Extraction("succeeded", 1, [page]),
                               "v+arxiv-latex-v1", chunker)
    passages = store.passages_for(svid)
    assert len(passages) >= 2
    labelled = [p for p in passages if p["text_source"] == "latex_source"]
    assert len(labelled) == 1 and "$$ (5)" in labelled[0]["text"]
    assert all(p["text_source"] == "text_layer" for p in passages if p is not labelled[0] and p["id"] != labelled[0]["id"])
    from deixis.workflow.equations import chunk_numbers
    assert chunk_numbers({1: page.latex_blocks}, 1, labelled[0]["payload_ref"]) == ["5"]
    assert all(chunk_numbers({1: page.latex_blocks}, 1, p["payload_ref"]) == [] for p in passages if p["id"] != labelled[0]["id"])


def test_a_download_notice_on_a_real_page_does_not_move_the_offsets(tmp_path):
    lines = top() + [(72, 60, "Authorized licensed use limited to: SYNTHETIC. Downloaded on May 01,2020 at 10:00:00 UTC from IEEE Xplore.  Restrictions apply.", 5)] \
        + equation(160, "P a b = c d", 1) + prose(190)
    path = build(tmp_path, [lines])
    extraction = pdf.extract_pdf(path, placements=run(path, eq("P_{a b} = c_{d}"))["placements"])
    page = extraction.pages[0]
    assert "Authorized licensed" not in page.text and len(page.latex_blocks) == 1
    start, end, _ = page.latex_blocks[0]
    assert pdf.normalize_page_text(page.text)[start:end] == "$$\nP_{a b} = c_{d}\n$$ (1)"


def test_the_child_process_matches_a_synthetic_paper_end_to_end(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_arxiv_pdf())
    found = asyncio.run(src.read_source(source_archive(), path, set(), report=True))
    assert found["number_lines"] == 3 and found["candidates"] == 2 and len(found["rows"]) == 3

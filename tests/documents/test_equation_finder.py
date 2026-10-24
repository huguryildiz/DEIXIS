"""The D113 finder's region rules beyond D40 (2026-10-24): lead-in text, text lines around and beside a display, crops
grazed by neighbouring text, operator limits, citing sentences, columns, table-caption pages. The
PDFs are SYNTHETIC (drawn with PyMuPDF, `mathpix_helpers`); no request is sent. Passing shows the rules, not how often
real papers are read right (the model-free bench on 34 arXiv papers is in `.local/2026-10-24-equation-finder`)."""

import pymupdf

from arxiv_helpers import no_network  # noqa: F401
from deixis.documents import equation_regions as er
from mathpix_helpers import AFTER, PROSE, number, prose, scripted, two_equations


def detect(tmp_path, doc, name="eq.pdf"):
    path = tmp_path / name
    path.write_bytes(doc.tobytes())
    return er.detect(path)


def page_with_prose():
    doc = pymupdf.open()
    return doc, doc.new_page(width=612, height=792)


def test_a_lead_in_line_stays_out_of_the_region(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    page.insert_text((72, y), "as follows:", fontsize=10, fontname="helv")  # the end of the paragraph's sentence
    scripted(page, 250, y + 16, [("u = v + w", "base")])
    number(page, y + 16, "1")
    prose(page, y + 40, [AFTER, AFTER])
    found = detect(tmp_path, doc)
    assert found[0]["text_layer"] == "u = v + w" and "png" in found[0]


def test_a_text_line_just_below_does_not_leave_the_region_unclear(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    scripted(page, 250, y + 20, [("u = v + w", "base")])
    number(page, y + 20, "1")
    page.insert_text((72, y + 34), "where u is the speed", fontsize=10, fontname="helv")  # not prose by the line test
    prose(page, y + 47, [AFTER])
    found = detect(tmp_path, doc)
    assert "png" in found[0] and found[0]["text_layer"] == "u = v + w"


def test_an_unknown_line_just_above_leaves_the_region_unclear(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    scripted(page, 250, y + 18, [("V Qe(t) +", "base")])  # matches the heading pattern but is part of the display
    scripted(page, 250, y + 32, [("u = v + w", "base")])
    number(page, y + 32, "1")
    prose(page, y + 60, [AFTER, AFTER])
    found = detect(tmp_path, doc)
    assert found[0]["refused"] == "region_unclear" and "png" not in found[0]


def test_prose_grazing_the_padding_is_whited_out_but_a_stray_fragment_refuses(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    scripted(page, 250, y + 0.7, [("u = v + w", "base")])  # set tight under the paragraph: its descenders reach the pad
    number(page, y + 0.7, "1")
    prose(page, y + 30, [AFTER, AFTER])
    path = tmp_path / "graze.pdf"
    path.write_bytes(doc.tobytes())
    found = er.detect(path)
    assert "png" in found[0] and found[0]["crop"]["cut"]  # the grazing prose is whited out
    assert er.render_crop(path, found[0]["crop"]) == found[0]["png"]
    # Only a span in the padding, clear of the equation's type, whose line another region holds or is prose, is cut.
    core = (100.0, 50.0, 200.0, 70.0)
    span = (120.0, 46.5, 130.0, 49.0)
    owner = {span: 7}
    assert er._cuttable(span, core, owner, others={7})
    assert not er._cuttable(span, core, owner, others=set())  # a piece no region or paragraph holds: may be this one's
    assert not er._cuttable((120.0, 46.5, 130.0, 52.0), core, {(120.0, 46.5, 130.0, 52.0): 7}, others={7})  # reaches the type


def test_a_lower_limit_belongs_to_the_sum_above_it(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    y0 = y + 22
    scripted(page, 230, y0, [("s =", "base")])
    page.insert_text((252, y0 + 2), "∑", fontsize=14, fontname="helv")  # a narrow operator line
    page.insert_text((252, y0 + 11), "i=1", fontsize=7, fontname="tiit")  # its lower limit, under the row
    scripted(page, 266, y0, [("x + y", "base")])
    number(page, y0, "1")
    scripted(page, 230, y0 + 24, [("t = a + b", "base")])
    number(page, y0 + 24, "2")
    prose(page, y0 + 50, [AFTER, AFTER])
    found = {c["n"]: c for c in detect(tmp_path, doc)}
    assert "i=1" in found["1"]["text_layer"] and "i=1" not in found["2"]["text_layer"]


def test_a_sentence_citing_an_equation_number_is_not_a_display(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    page.insert_text((300, y), "= x. The problem in (4)", fontsize=10, fontname="helv")
    prose(page, y + 13, [AFTER, AFTER])
    assert all(c["n"] != "4" for c in detect(tmp_path, doc))


def test_prose_split_around_inline_math_does_not_make_two_columns():
    _, page = page_with_prose()
    for k in range(10):  # full-width prose lines
        page.insert_text((72, 90 + 13 * k), PROSE[k % 3], fontsize=10, fontname="helv")
    for k in range(3):  # lines the text layer splits around inline math, each side on its own
        page.insert_text((72, 230 + 13 * k), "the receiver counts the particles and", fontsize=10, fontname="helv")
        page.insert_text((268, 230 + 13 * k), "x + y + z = w", fontsize=10, fontname="tiit")  # the inline math between
        page.insert_text((340, 230 + 13 * k), "then compares that count with its value", fontsize=10, fontname="helv")
    lines = er._lines(page, 10.0)
    gutter, columns = er._columns(lines, page.rect.width)
    assert gutter is None and len(columns) == 1


def test_a_cut_keeps_clear_of_the_equations_type():
    core = (100.0, 50.0, 200.0, 70.0)
    near = (120.0, 46.0, 130.0, 49.5)  # 0.5 pt from the type: its white box could reach a glyph once rounded to pixels
    assert not er._cuttable(near, core, {near: 7}, others={7})


def test_a_lone_word_at_the_margin_above_a_display_leaves_it_unclear(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    page.insert_text((72, y + 4), "minimize", fontsize=10, fontname="tiit")  # may be the display's first row
    scripted(page, 250, y + 18, [("u = v + w", "base")])
    number(page, y + 18, "1")
    prose(page, y + 44, [AFTER, AFTER])
    found = detect(tmp_path, doc)
    assert found[0]["refused"] == "region_unclear" and "png" not in found[0]


def margin_page(above: str | None = None, below: str | None = None):
    doc, page = page_with_prose()
    y = prose(page, 90)
    if above:
        page.insert_text((72, y + 4), above, fontsize=10, fontname="tiit")
    scripted(page, 250, y + 18, [("u = v + w", "base")])
    number(page, y + 18, "1")
    if below:
        page.insert_text((72, y + 32), below, fontsize=10, fontname="tiit")
    prose(page, y + 58, [AFTER, AFTER])
    return doc


def test_a_display_label_or_constraint_at_the_margin_leaves_the_region_unclear(tmp_path):
    for k, (above, below) in enumerate([("maximize rate", None), ("maximize average rate", None), (None, "minimize"),
                                        (None, "subject to"), (None, "subject to x ≤ 1"),
                                        (None, "subject to average power ≤ P")]):
        found = detect(tmp_path, margin_page(above, below), f"label{k}.pdf")
        assert found[0]["refused"] == "region_unclear", (above, below)


def test_a_line_below_beside_another_columns_number_still_counts(tmp_path):
    doc, page = page_with_prose()
    left = ["SYNTHETIC. The receiver counts the particles", "that arrive within each interval and then", "compares that count with a threshold value"]
    for k, line in enumerate(left * 2):
        page.insert_text((50, 90 + 13 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 90 + 13 * k), line, fontsize=9, fontname="helv")
    scripted(page, 120, 190, [("u = v", "base")])
    number(page, 190, "1", x=262)
    scripted(page, 120, 203, [("z = w", "base")])  # a further row of (1) below its number
    scripted(page, 400, 203, [("p = q", "base")])
    number(page, 203, "2", x=532)  # the right column's number on the same row
    for k, line in enumerate(left * 2):
        page.insert_text((50, 230 + 13 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 230 + 13 * k), line, fontsize=9, fontname="helv")
    found = {c["n"]: c for c in detect(tmp_path, doc)}
    assert "png" not in found["1"]  # its region would miss `z = w`


def test_a_foreign_span_inside_the_crops_outer_edge_counts():
    box = (100.0, 100.0, 200.0, 140.0)
    assert er._inside_any((150.0, 139.8, 160.0, 150.0), box)  # 0.2 pt into the crop: may put ink in it
    assert not er._inside_any((150.0, 140.0, 160.0, 150.0), box)  # ends on the edge


def test_a_label_beside_the_numbered_row_leaves_the_region_unclear(tmp_path):
    for k, (label, dy) in enumerate([("maximize average rate", 0), ("subject to average power ≤ P", 0),
                                     ("subject to average power ≤ P", 13.4)]):  # just below, grazing the number's box
        doc, page = page_with_prose()
        y = prose(page, 90)
        page.insert_text((72, y + 18 + dy), label, fontsize=10, fontname="helv")
        scripted(page, 300, y + 18, [("u = v + w", "base")])
        number(page, y + 18, "1")
        prose(page, y + 44, [AFTER, AFTER])
        found = detect(tmp_path, doc, f"beside{k}.pdf")
        assert found[0]["refused"] == "region_unclear" and "png" not in found[0], label


def test_text_at_the_margin_inside_or_just_below_a_region_leaves_it_unclear(tmp_path):
    cases = [("power <= P", 14, 250), ("average transmit power <= P", 14, 250), ("sum of transmit powers <= P", 14, 250),
             ("The sum of transmit powers <= P", 14, 250),
             ("where u = v", 13.4, 250),
             ("Suppose x = y", -12, 250), ("If x = y", -12, 250), ("As x = y", -12, 250), ("We set x = y", -12, 250),
             ("where u = v", 0, 72)]  # (text, below the row, x of the display)
    for k, (text, dy, x) in enumerate(cases):  # helv has no ≤: an ASCII relation
        doc, page = page_with_prose()
        y = prose(page, 90)
        if x == 72:  # the text itself carries the number: a numbered prose fragment
            page.insert_text((x, y + 18), text, fontsize=10, fontname="helv")
        else:
            scripted(page, x, y + 18, [("u = v + w", "base")])
            page.insert_text((72, y + 18 + dy), text, fontsize=10, fontname="helv")
        number(page, y + 18, "1")
        prose(page, y + 50, [AFTER, AFTER])
        found = detect(tmp_path, doc, f"text{k}.pdf")
        assert found and "png" not in found[0], (text, dy)


def test_a_full_width_abstract_over_two_columns_keeps_the_columns(tmp_path):
    doc, page = page_with_prose()
    for k in range(13):  # the abstract outnumbers the columns' lines
        page.insert_text((50, 60 + 12 * k), PROSE[k % 3], fontsize=9, fontname="helv")
    column = ["SYNTHETIC. The receiver counts the particles", "that arrive within each interval and then",
              "compares that count with a threshold value"]
    for k, line in enumerate(column):  # six lines a column: fewer than the abstract's
        page.insert_text((50, 230 + 12 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 230 + 12 * k), line, fontsize=9, fontname="helv")
    scripted(page, 120, 285, [("a = b", "base")])
    scripted(page, 400, 285, [("u = v + w", "base")])
    number(page, 285, "1", x=532)
    for k, line in enumerate(column):
        page.insert_text((50, 310 + 12 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 310 + 12 * k), line, fontsize=9, fontname="helv")
    gutter, columns = er._columns(er._lines(page, 9.0), page.rect.width)
    assert gutter is not None and len(columns) == 2
    found = detect(tmp_path, doc)
    assert all("a = b" not in c.get("text_layer", "") for c in found if "png" in c)


def test_full_width_lines_between_two_columns_never_join_their_equations(tmp_path):
    doc, page = page_with_prose()
    column = ["SYNTHETIC. The receiver counts the particles", "that arrive within each interval and then",
              "compares that count with a threshold value"]
    for k, line in enumerate(column):
        page.insert_text((50, 80 + 12 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 80 + 12 * k), line, fontsize=9, fontname="helv")
    for k in range(6):  # a full-width caption or paragraph among the columns' lines
        page.insert_text((50, 130 + 12 * k), PROSE[k % 3], fontsize=9, fontname="helv")
    scripted(page, 120, 225, [("a = b", "base")])
    scripted(page, 400, 225, [("u = v + w", "base")])
    number(page, 225, "1", x=532)
    for k, line in enumerate(column):
        page.insert_text((50, 250 + 12 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 250 + 12 * k), line, fontsize=9, fontname="helv")
    found = detect(tmp_path, doc)
    assert all("a = b" not in c.get("text_layer", "") for c in found if "png" in c)


def test_column_equations_close_to_the_gutter_never_share_a_crop(tmp_path):
    doc, page = page_with_prose()
    column = ["SYNTHETIC. The receiver counts the particles", "that arrive within each interval and then",
              "compares that count with a threshold value"]
    for k, line in enumerate(column):
        page.insert_text((50, 80 + 12 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 80 + 12 * k), line, fontsize=9, fontname="helv")
    for k in range(6):  # full-width lines among the columns' lines: the page reads as one column
        page.insert_text((50, 130 + 12 * k), PROSE[k % 3], fontsize=9, fontname="helv")
    scripted(page, 250, 225, [("a = b", "base")])  # closer to the other column's equation than the columns' prose
    scripted(page, 322, 225, [("u = v + w", "base")])
    number(page, 225, "1", x=532)
    scripted(page, 250, 245, [("a = b + c + d", "base")])  # one that runs across where the gutter would be
    scripted(page, 400, 245, [("p = q + r", "base")])
    number(page, 245, "2", x=532)
    for k, line in enumerate(column):
        page.insert_text((50, 270 + 12 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 270 + 12 * k), line, fontsize=9, fontname="helv")
    found = detect(tmp_path, doc)
    assert all("a = b" not in c.get("text_layer", "") for c in found if "png" in c)


def test_a_page_with_a_table_caption_is_skipped_even_with_a_ruled_grid_near_the_caption(tmp_path):
    doc, page = page_with_prose()
    y = prose(page, 90)
    top = y + 10
    for k in range(4):  # another table's ruled grid, just above the caption
        page.draw_line((72, top + 16 * k), (540, top + 16 * k), width=0.5)
    for x in (72, 228, 384, 540):
        page.draw_line((x, top), (x, top + 48), width=0.5)
    page.insert_text((72, top + 66), "Table 3: SYNTHETIC unruled values", fontsize=10, fontname="helv")
    scripted(page, 250, top + 90, [("p = q + r", "base")])  # a row of the unruled table it names, alone
    number(page, top + 90, "9")
    prose(page, top + 130, [AFTER, AFTER])
    assert detect(tmp_path, doc) == []

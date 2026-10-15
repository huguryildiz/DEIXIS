"""The Mathpix route's detector, crops and gate (D40). The PDFs are SYNTHETIC (drawn with PyMuPDF, `mathpix_helpers`);
no request is sent. Passing shows the rules, not how often real papers are read right."""

import hashlib
from collections import Counter

import pymupdf
import pytest

from arxiv_helpers import no_network  # noqa: F401
from deixis.documents import equation_regions as er
from mathpix_helpers import AFTER, ANSWERS, PROSE, fraction, number, prose, scripted, two_equations, width


def detect(tmp_path, doc, name="eq.pdf", **kw):
    path = tmp_path / name
    path.write_bytes(doc.tobytes())
    return path, er.detect(path, **kw)


# ---- the detector ---------------------------------------------------------------------------------------------------------
def test_numbered_displays_are_found_with_their_scripts_signs_and_fraction_bars(tmp_path):
    _, found = detect(tmp_path, two_equations())
    assert [c["n"] for c in found] == ["1", "2"] and all("png" in c and "refused" not in c for c in found)
    first, second = found
    assert first["chars"] == [["x", "base"], ["a", "base"], ["2", "raised"], ["b", "base"], ["i", "lowered"]]
    assert first["signs"] == {"=": 1, "+": 1} and first["rules"] == 0
    assert Counter(c for c, _ in second["chars"]) == Counter("ycd") and second["rules"] == 1
    # The number line is among the placement's lines (as `_place` requires) and the crop is reproducible from its recipe.
    assert first["number"] in first["lines"] and first["crop"]["dpi"] == er.DPI
    assert hashlib.sha256(er.render_crop(tmp_path / "eq.pdf", first["crop"])).hexdigest() == first["crop_sha256"]


def test_prose_lines_and_headings_are_never_taken_into_a_region(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = prose(page, 90)
    page.insert_text((72, y + 6), "2.1 Model", fontsize=10, fontname="hebo")  # a heading right above the display
    scripted(page, 250, y + 20, [("u = v", "base")])
    number(page, y + 20, "1")
    # Prose ending in a parenthesised number is not an equation number.
    page.insert_text((72, y + 60), "and the same result was obtained in the earlier work of the group (3)", fontsize=10, fontname="helv")
    prose(page, y + 80, [AFTER, AFTER])
    _, found = detect(tmp_path, doc)
    assert [c["n"] for c in found] == ["1"]
    assert found[0]["text_layer"] == "u = v"  # neither the heading nor any prose line


def test_a_two_column_page_never_yields_a_crop_across_the_gutter(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    left = ["SYNTHETIC. The receiver counts the particles", "that arrive within each interval and then", "compares that count with a threshold value",
            "chosen in advance for every interval here."]
    for k, line in enumerate(left * 3):
        page.insert_text((50, 90 + 13 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 90 + 13 * k), line, fontsize=9, fontname="helv")
    scripted(page, 120, 270, [("p = q", "base")])
    number(page, 270, "1", x=224)  # the left column's right margin
    scripted(page, 200, 320, [("s = t + w + z + k + m + n + r", "base")])  # runs across the gutter
    number(page, 320, "2", x=545)
    for k, line in enumerate(left):
        page.insert_text((50, 360 + 13 * k), line, fontsize=9, fontname="helv")
        page.insert_text((320, 360 + 13 * k), line, fontsize=9, fontname="helv")
    _, found = detect(tmp_path, doc)
    one = next(c for c in found if c["n"] == "1")
    assert "png" in one and one["box"][2] < 278
    gutter = 278
    assert all(not (c["box"][0] < gutter < c["box"][2]) for c in found if "png" in c)
    assert all("png" not in c for c in found if c["n"] == "2")


def test_a_rotated_page_and_a_table_page_yield_nothing(tmp_path):
    doc = two_equations()
    doc[0].set_rotation(90)
    _, found = detect(tmp_path, doc)
    assert found == []
    doc = two_equations()
    doc[0].insert_text((72, 60), "Table 1: SYNTHETIC values", fontsize=10, fontname="helv")
    _, found = detect(tmp_path, doc, name="table.pdf")
    assert found == []


def test_ocr_pages_are_skipped(tmp_path):
    _, found = detect(tmp_path, two_equations(), skip_pages={1})
    assert found == []


# ---- the crop ---------------------------------------------------------------------------------------------------------
def test_a_crop_overlapped_by_other_text_is_refused(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = prose(page, 90)
    scripted(page, 250, y + 20, [("u = v + w", "base")])
    number(page, y + 20, "1")
    # A prose line set so close that it overlaps the equation's box.
    page.insert_text((72, y + 26), "and here a note runs through the display across the whole of the column", fontsize=10, fontname="helv")
    prose(page, y + 60, [AFTER])
    _, found = detect(tmp_path, doc)
    assert found and found[0]["refused"] == "crop_has_other_text" and "png" not in found[0]


def test_a_crop_with_an_image_or_another_drawing_is_refused(tmp_path):
    doc = two_equations()
    page = doc[0]
    page.draw_rect(pymupdf.Rect(255, 140, 258, 152), color=(0, 0, 0), fill=(0, 0, 0))  # a box, not a horizontal rule
    _, found = detect(tmp_path, doc)
    assert next(c for c in found if c["n"] == "1")["refused"] == "crop_has_other_content"
    doc = two_equations()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False)
    doc[0].insert_image(pymupdf.Rect(252, 202, 262, 212), pixmap=pix)
    _, found = detect(tmp_path, doc, name="image.pdf")
    assert next(c for c in found if c["n"] == "2")["refused"] == "crop_has_other_content"


def test_the_equation_number_is_cut_out_of_the_image(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = prose(page, 90)
    text = "u = v + w (1)"  # the number in the equation's own line, one space after it
    scripted(page, 533 - width(text), y + 20, [(text, "base")])
    prose(page, y + 50, [AFTER])
    path, found = detect(tmp_path, doc)
    assert found[0]["text_layer"] == "u = v + w" and found[0]["chars"] == [["u", "base"], ["v", "base"], ["w", "base"]]
    crop = found[0]["crop"]
    assert crop["cut"], "the number touches the padded box, so it is cut"
    png = er.render_crop(path, crop)
    pix = pymupdf.Pixmap(png)
    zoom = crop["dpi"] / 72
    x0 = int((crop["cut"][0][0] - crop["box"][0]) * zoom) + 1
    assert x0 < pix.width
    whites = {pix.pixel(x, y)[:3] for x in range(x0, pix.width) for y in range(pix.height)}
    assert whites == {(255, 255, 255)}


def test_crop_size_is_decided_before_rendering(tmp_path):
    assert er.crop_dpi((0, 0, 100, 30)) == er.DPI
    assert er.MIN_DPI <= er.crop_dpi((0, 0, 800, 40)) < er.DPI  # 2,000 px a side: lowered
    assert er.crop_dpi((0, 0, 2300, 40)) is None  # an A0 page's full-width line: refused, never rendered
    doc = pymupdf.open()
    page = doc.new_page(width=2384, height=3370)
    y = prose(page, 200, [line * 3 for line in PROSE], size=10)
    scripted(page, 80, y + 40, [("u = v + w " * 40, "base")])
    number(page, y + 40, "1", x=2300)
    prose(page, y + 80, [AFTER * 3])
    _, found = detect(tmp_path, doc)
    assert found and found[0]["refused"] == "crop_too_large" and "png" not in found[0]


# ---- the gate ----------------------------------------------------------------------------------------------------------
def candidate(chars, signs=None, rules=0):
    return {"chars": [list(c) for c in chars], "signs": signs or {}, "rules": rules}


def answer(latex, confidence=0.99):
    return {"latex_styled": latex, "confidence": confidence, "confidence_rate": confidence}


X2 = [("x", "base"), ("2", "raised")]


def test_the_gate_passes_a_reading_that_agrees_with_the_text_layer():
    found = er.gate(candidate([("x", "base"), ("a", "base"), ("2", "raised"), ("b", "base"), ("i", "lowered")], {"=": 1, "+": 1}),
                    ANSWERS["1"])
    assert found == {"latex": "x=a^{2}+b_{i}", "reason": None,
                     "checks": {"katex": True, "letters": True, "scripts": True, "known_signs": True, "operators": True,
                                "fractions": True}}


@pytest.mark.parametrize("response", [
    None, {}, {"latex_styled": "", "confidence": 1}, {"error": "Image too small", "error_info": {"id": "image_too_small"}},
    answer("x^{2} \\tag{1}"), answer("x^{2} \\label{eq}"), answer("x^{2} \\quad (1)"), answer("$x^{2}$"),
])
def test_a_missing_or_numbered_reading_is_not_a_single_equation(response):
    assert er.gate(candidate(X2), response)["reason"] == "not_single_equation"


def test_low_confidence_and_unknown_commands_are_refused():
    assert er.gate(candidate(X2), answer("x^{2}", confidence=0.3))["reason"] == "low_confidence"
    assert er.gate(candidate(X2), {"latex_styled": "x^{2}"})["reason"] == "low_confidence"
    assert er.gate(candidate(X2), answer("\\foo{x}^{2}"))["reason"] == "katex_unknown"


def test_letters_must_be_the_same_multiset_on_both_sides():
    assert er.gate(candidate(X2), answer("y^{2}"))["reason"] == "letters_differ"
    assert er.gate(candidate(X2), answer("x^{2} x"))["reason"] == "letters_differ"
    assert er.gate(candidate([]), answer("2"))["reason"] == "letters_differ"
    # ∆ and Δ are one letter (math_reader's table); a Greek command prints its letter.
    assert er.gate(candidate([("∆", "base"), ("x", "base")]), answer("\\Delta x"))["reason"] is None


def test_sols_counterexamples_are_refused():
    # x^2 read as x_2: same letters, wrong level.
    assert er.gate(candidate(X2), answer("x_{2}"))["reason"] == "script_differs"
    # x_i - y_j read as x_j + y_i: letters and levels agree, the sign does not.
    chars = [("x", "base"), ("i", "lowered"), ("y", "base"), ("j", "lowered")]
    assert er.gate(candidate(chars, {"−": 1}), answer("x_{j}+y_{i}"))["reason"] == "operators_differ"
    # a/b with a bar on the page read as a b.
    assert er.gate(candidate([("a", "base"), ("b", "base")], rules=1), answer("a b"))["reason"] == "fractions_differ"
    assert er.gate(candidate([("a", "base"), ("b", "base")], rules=1), answer("\\frac{a}{b}"))["reason"] is None


def test_documented_misses_pass_the_gate():
    # Swapped subscripts across symbols with equal multisets.
    chars = [("x", "base"), ("i", "lowered"), ("y", "base"), ("j", "lowered")]
    assert er.gate(candidate(chars), answer("x_{j} y_{i}"))["reason"] is None
    # A superscript moved between two symbols on one level.
    assert er.gate(candidate([("a", "base"), ("2", "raised"), ("b", "base")]), answer("a b^{2}"))["reason"] is None
    # Wrong grouping of a sum.
    chars = [("i", "lowered"), ("a", "base"), ("b", "base")]
    assert er.gate(candidate(chars, {"∑": 1, "+": 1}), answer("\\sum_{i}(a+b)"))["reason"] is None
    assert er.gate(candidate(chars, {"∑": 1, "+": 1}), answer("\\sum_{i} a+b"))["reason"] is None


def test_a_dropped_slash_or_a_changed_big_operator_is_refused():
    # Sol r1 finding 3: `a/b → ab` and `∑x → ∏x` passed every check.
    ab = [("a", "base"), ("b", "base")]
    assert er.gate(candidate(ab, {"/": 1}), answer("ab"))["reason"] == "operators_differ"
    assert er.gate(candidate(ab, {"/": 1}), answer("a/b"))["reason"] is None
    x = [("x", "base")]
    assert er.gate(candidate(x, {"∑": 1}), answer("\\prod x"))["reason"] == "operators_differ"
    assert er.gate(candidate(x, {"∑": 1}), answer("\\sum x"))["reason"] is None
    assert er.gate(candidate(x, {"∫": 1}), answer("\\oint x"))["reason"] == "operators_differ"
    assert er.latex_marks("\\bigcup_{i} x")["signs"] == Counter({"⋃": 1})


def test_a_sign_the_table_does_not_know_refuses_the_region_on_either_side():
    x = [("x", "base"), ("y", "base")]
    assert er.gate(candidate(x, {"?⊲": 1}), answer("x y"))["reason"] == "unknown_sign"  # the text layer's ⊲
    assert er.gate(candidate(x), answer("x \\lhd y"))["reason"] == "unknown_sign"  # a command the gate cannot compare
    assert er.gate(candidate(x), answer("x ⊲ y"))["reason"] == "unknown_sign"  # a Unicode sign in the reading
    # The text layer's marks: a known sign is counted, an unknown one is kept as unknown, delimiters are not compared.
    spans = [[{"text": "x ⊲ y | z/w", "font": "Times-Italic", "size": 10, "y": 100.0, "box": (0, 90, 60, 102)}]]
    chars, signs = er._marks(spans, 10)
    assert signs == Counter({"?⊲": 1, "/": 1}) and [c for c, _ in chars] == list("xyzw")


def test_limits_of_a_display_operator_may_stand_on_any_level():
    chars = [("i", "base"), ("1", "base"), ("N", "base"), ("x", "base"), ("i", "lowered")]
    assert er.gate(candidate(chars, {"∑": 1, "=": 1}), answer("\\sum_{i=1}^{N} x_{i}"))["reason"] is None
    assert er.gate(candidate([("m", "base"), ("a", "base"), ("x", "base"), ("k", "lowered")]), answer("\\max_{k}"))["reason"] is None


def test_latex_marks_walk_braces_commands_and_environments():
    marks = er.latex_marks("\\begin{array}{ll} f(x) & \\leq \\frac{\\mathrm{d} y}{d t}\\\\[2pt] \\end{array}")
    assert Counter(c for c, _ in marks["fixed"].elements()) == Counter("fxdydt") and marks["fractions"] == 1
    assert marks["signs"] == Counter({"≤": 1})
    assert er.latex_marks("\\left< a \\right>")["signs"] == Counter()  # delimiters, not signs
    assert er.latex_marks("\\sqrt[3]{x}")["free"] == Counter("3")
    assert er.tidy("a &= b \\\\ c &= d \\nonumber") == "\\begin{aligned}a &= b \\\\ c &= d\\end{aligned}"


def test_a_real_crop_passes_the_gate_with_its_scripted_reading(tmp_path):
    _, found = detect(tmp_path, two_equations())
    assert [er.gate(c, ANSWERS[c["n"]])["reason"] for c in found] == [None, None]
    assert er.gate(found[1], answer("y=c d"))["reason"] == "fractions_differ"


def test_fraction_helper_without_a_bar_counts_no_rule(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = prose(page, 90)
    x = scripted(page, 250, y + 24, [("y = ", "base")])
    fraction(page, x, y + 24, "c", "d", bar=False)
    number(page, y + 24, "1")
    prose(page, y + 56, [AFTER])
    _, found = detect(tmp_path, doc)
    assert found[0]["rules"] == 0

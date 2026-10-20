"""Helpers left from the removed Marker reader (D52, D113): inline-math rewriting, LaTeX letters and table-safe chunking."""

from deixis.documents import inline_math, math_reader, pdf


def test_inline_math_keeps_a_segment_only_when_its_letters_match_the_text_layer():
    spans = [("where x", "Times"), ("i", "CMR7"), ("2", "CMR7"), (" is the rate", "Times")]
    # stacked scripts: the text layer has i before 2, the reading writes the superscript first
    assert inline_math.rewrite("where <math>x^{2}_{i}</math> is the rate", [spans]) == (
        [("text", "where "), ("math", "x^{2}_{i}"), ("text", " is the rate")], 1, 0)
    # a changed letter keeps the text layer
    assert inline_math.rewrite("where <math>x_{j}^{2}</math> is the rate", [spans]) == ([("text", "where xi2 is the rate")], 0, 1)
    # prose that does not match the text layer rejects the line; a reading without math changes nothing
    assert inline_math.rewrite("when <math>x_{i}^{2}</math> is the rate", [spans]) is None
    assert inline_math.rewrite("where xi2 is the rate", [spans]) is None
    # of two orderings of the same spans, the one the reading matches is used
    other = [spans[0], spans[2], spans[1], spans[3]]
    assert inline_math.rewrite("where <math>x_{i}^{2}</math> is the rate", [other, spans])[1] == 1
    # the image reached past the line: the prose beyond it is not used
    assert inline_math.rewrite("where <math>x_{i}^{2}</math> is the rate of the next line", [spans])[1] == 1


def test_inline_math_masks_symbol_font_letters_and_widens_over_brackets():
    # A symbol font maps its brackets to p and q; they are neither compared nor left behind.
    spans = [("cost ", None), ("O", "CMMI10"), ("p", "TeX-mathax"), ("|D|", None), ("q", "TeX-mathax"), (" here", None)]
    assert inline_math.rewrite("cost <math>O(|D|)</math> here", [spans]) == (
        [("text", "cost "), ("math", "O(|D|)"), ("text", " here")], 1, 0)
    assert inline_math.rewrite("set <math>\\left(a, b\\right)</math> ok", [[("set (a, b) ok", None)]])[0] == [
        ("text", "set "), ("math", "\\left(a, b\\right)"), ("text", " ok")]
    assert inline_math.segment_letters("\\mathbb{E}[\\alpha_{k}]") == {"Eαk"}


def test_latex_letters_drop_commands_and_turn_greek_commands_into_letters():
    assert math_reader.latex_letters("\\alpha_{i} + \\operatorname{Var}(\\mu)") == math_reader.latex_letters("α i Var µ")
    assert math_reader.latex_letters("x_{T} = 2 \\tag{4}") == math_reader.latex_letters("x T = 2")


def test_page_chunks_do_not_cut_a_table_row():
    rows = "\n".join(f"| SYNTHETIC strain {i} | Observation number {i} with some words. More words here | Ref {i} |" for i in range(40))
    for limit in range(300, 400, 7):  # wherever the length limit falls within a row
        chunks = pdf.chunk_page("TABLE 1 | Caption.\n\n" + rows, limit=limit)
        lines = [line for _, _, piece in chunks for line in piece.split("\n") if line]
        assert len(chunks) > 1 and lines[0] == "TABLE 1 | Caption." and all(line.startswith("| ") and line.endswith(" |") for line in lines[1:])

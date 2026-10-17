"""Verify Citations V1 (D86): reading a draft and finding its markers. Drafts here are SYNTHETIC."""

import io
import zipfile

import pytest

from deixis.documents import draft_parse
from deixis.documents.draft_parse import DraftRefused, parse_draft, read_draft, sentences, written_entry_fields


def docx(*paragraphs, extra_xml=""):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f'<?xml version="1.0"?>{extra_xml}<w:document {ns}><w:body>{body}</w:body></w:document>')
    return buffer.getvalue()


def markers(text, fmt="md"):
    return [(m.style, m.status, m.raw, [t.value for t in m.targets]) for m in parse_draft(fmt, text).markers]


def test_ieee_numeric_markers_single_range_list_and_adjacent():
    found = markers("Routing helps [3]. Energy drops [3]–[5] and [6-8]. Both [3, 7] agree. See [3], [4]. Also [2,4–6].")
    assert found == [
        ("numeric", "recognized", "[3]", ["3"]),
        ("numeric", "recognized", "[3]–[5]", ["3", "4", "5"]),
        ("numeric", "recognized", "[6-8]", ["6", "7", "8"]),
        ("numeric", "recognized", "[3, 7]", ["3", "7"]),
        ("numeric", "recognized", "[3], [4]", ["3", "4"]),
        ("numeric", "recognized", "[2,4–6]", ["2", "4", "5", "6"]),
    ]


@pytest.mark.parametrize("text, raw", [
    ("Odd claim [ZL22] here.", "[ZL22]"),
    ("Pandoc claim [@zeng2022] here.", "[@zeng2022]"),
    ("Reversed range [5-3] here.", "[5-3]"),
    ("Zero [0] here.", "[0]"),
    ("Too wide [1-500] here.", "[1-500]"),
    ("Mixed [3, a] here.", "[3, a]"),
])
def test_bracket_markers_that_are_not_numeric_lists_are_unrecognized(text, raw):
    assert markers(text) == [("numeric", "unrecognized", raw, [])]


def test_links_footnotes_checkboxes_and_bracketed_prose_are_not_markers():
    assert markers("A [link](https://x.org) and [^1] note, a [x] box and [citation needed] here.\n\n[^1]: note") == []


def test_author_year_parenthetical_narrative_multi_and_suffixes():
    found = markers("It holds (Zeng et al., 2022). Both agree (Zeng and Li, 2022; Kim, 2021). Zeng et al. (2022a) "
                    "showed it. Two papers (Kim, 2021a, 2021b) differ. See also (e.g., Park & Lee, 2019, p. 4).")
    assert found == [
        ("author_year", "recognized", "(Zeng et al., 2022)", ["Zeng et al., 2022"]),
        ("author_year", "recognized", "(Zeng and Li, 2022; Kim, 2021)", ["Zeng and Li, 2022", "Kim, 2021"]),
        ("author_year", "recognized", "Zeng et al. (2022a)", ["Zeng et al., 2022a"]),
        ("author_year", "recognized", "(Kim, 2021a, 2021b)", ["Kim, 2021a", "Kim, 2021b"]),
        ("author_year", "recognized", "(e.g., Park & Lee, 2019, p. 4)", ["Park & Lee, 2019"]),
    ]
    target = parse_draft("md", "Zeng et al. (2022a) showed it.").markers[0].targets[0]
    assert (target.names, target.et_al, target.year, target.suffix) == (("Zeng",), True, 2022, "a")


def test_parentheses_that_only_hold_a_year_or_prose_are_not_markers_and_a_broken_one_is_unrecognized():
    assert markers("Data from 2019 (2019) and (see Table 2) and (n = 2022).") == []
    assert markers("Both (Zeng et al., 2022; and more) agree.") == [
        ("author_year", "unrecognized", "(Zeng et al., 2022; and more)", [])]


def test_latex_cite_commands_with_optional_arguments_and_multiple_keys():
    text = (r"\begin{document}As shown \cite{zeng2022, kim2021}. Also \citep[p.~3]{li2020} and \citet[see][ch.~2]{park}."
            r" Bad \cite{a b}. Broken \cite here. % \cite{commented}" "\n" r"\end{document}")
    assert markers(text, "tex") == [
        ("latex", "recognized", r"\cite{zeng2022, kim2021}", ["zeng2022", "kim2021"]),
        ("latex", "recognized", r"\citep[p.~3]{li2020}", ["li2020"]),
        ("latex", "recognized", r"\citet[see][ch.~2]{park}", ["park"]),
        ("latex", "unrecognized", r"\cite{a b}", []),
        ("latex", "unrecognized", r"\cite", []),
    ]


def test_brackets_in_tex_are_latex_arguments_not_numeric_markers():
    assert markers(r"\begin{figure}[h] Spacing \\[2pt] and a list [3] in tex.", "tex") == []
    assert [m[0] for m in markers(r"Pasted LaTeX \cite{a} and IEEE [3] in text.", "text")] == ["latex", "numeric"]


def test_each_marker_gets_the_sentence_it_sits_in():
    draft = parse_draft("md", "First claim by Zeng et al. (2022) holds. Fig. 3 shows e.g. this [2]. J. Smith agrees [4].\n\nNew paragraph [5]")
    assert [draft.text[m.sentence_start:m.sentence_end] for m in draft.markers] == [
        "First claim by Zeng et al. (2022) holds.", "Fig. 3 shows e.g. this [2].", "J. Smith agrees [4].", "New paragraph [5]"]
    assert sentences("One. two. Three.") == [(0, 9), (10, 16)]


def test_the_reference_list_is_cut_from_the_body_and_kept_as_entries():
    draft = parse_draft("md", "Claim [1] and [2].\n\n## References\n\n[1] Y. Zeng, \"Depth routing,\" 2022.\n"
                              "[2] A. Author, \"Other\n  paper,\" arXiv:2101.00001, 2021.\n")
    assert [m.raw for m in draft.markers] == ["[1]", "[2]"]
    assert draft.list_origin == "draft_list"
    assert [(e.number, e.raw) for e in draft.list_entries] == [
        (1, 'Y. Zeng, "Depth routing," 2022.'), (2, 'A. Author, "Other paper," arXiv:2101.00001, 2021.')]
    unnumbered = parse_draft("text", "Claim (Zeng, 2022).\n\nKaynaklar\nZeng, Y. (2022). A title. J.\nKim, J. (2021). B title. J.\n")
    assert [e.raw for e in unnumbered.list_entries] == ["Zeng, Y. (2022). A title. J.", "Kim, J. (2021). B title. J."]


def test_thebibliography_items_are_the_tex_drafts_own_entries():
    draft = parse_draft("tex", "\\begin{document}See \\cite{z}.\n\\begin{thebibliography}{9}\n\\bibitem{z} Y. Zeng, ``DBR,'' 2022.\n"
                               "\\bibitem[Kim(2021)]{k} J. Kim, Title, 2021.\n\\end{thebibliography}\\end{document}")
    assert draft.list_origin == "bibitem" and [(e.key, e.raw) for e in draft.list_entries] == [
        ("z", "Y. Zeng, ``DBR,'' 2022."), ("k", "J. Kim, Title, 2021.")]
    assert "bibitem" not in draft.text


def test_written_entries_give_identifiers_title_authors_and_year_only_where_clear():
    ieee = written_entry_fields('Y. Zeng, X. Li, and J. Kim, "Depth based routing," IEEE Trans., 2022. doi:10.1109/ABC.2022.1.')
    assert ieee == {"doi": "10.1109/abc.2022.1", "arxiv_id": None, "title": "Depth based routing",
                    "authors": ["Y. Zeng", "X. Li", "J. Kim"], "year": 2022, "year_suffix": None}
    apa = written_entry_fields("Zeng, Y., Li, X., & Kim, J. (2022a). Title of paper. Journal, 3(2), 1–10.")
    assert (apa["authors"], apa["year"], apa["year_suffix"], apa["title"]) == (["Zeng", "Li", "Kim"], 2022, "a", "Title of paper")
    assert written_entry_fields("Some note without a year or title")["title"] is None
    assert written_entry_fields("A. B. Author, see arxiv.org/abs/2101.00001v2")["arxiv_id"] == "2101.00001"
    assert written_entry_fields("A. Author, \"T x y z,\" https://doi.org/10.48550/arXiv.2101.00002")["arxiv_id"] == "2101.00002"


def test_formats_text_md_tex_and_docx_paragraphs():
    assert read_draft(b"Claim [1].", "draft.md", None) == ("md", "Claim [1].")
    assert read_draft(b"Claim \\cite{a}.", "draft.tex", None)[0] == "tex"
    assert read_draft(None, None, "Pasted [2].\r\nNext") == ("text", "Pasted [2].\nNext")
    fmt, text = read_draft(docx("First claim [1].", "Second (Zeng, 2022)."), "draft.docx", None)
    assert (fmt, text) == ("docx", "First claim [1].\n\nSecond (Zeng, 2022).")
    assert len(parse_draft(fmt, text).markers) == 2


@pytest.mark.parametrize("data, name, pasted, code", [
    (None, None, None, "draft_missing"),
    (b"x", "a.txt", "y", "draft_missing"),
    (b"x", "draft.pdf", None, "draft_unknown_format"),
    (b"\x00\x01binary", "draft.txt", None, "draft_not_text"),
    (b"   ", "draft.txt", None, "draft_empty"),
    (b"not a zip", "draft.docx", None, "draft_unreadable"),
    (b"x" * (draft_parse.MAX_DRAFT_BYTES + 1), "draft.txt", None, "draft_too_large"),
])
def test_drafts_that_are_refused(data, name, pasted, code):
    with pytest.raises(DraftRefused) as caught:
        read_draft(data, name, pasted)
    assert caught.value.code == code


def docx_xml(xml: bytes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("dtd", [
    '<!DOCTYPE w:document [<!ENTITY a "SYNTHETIC-expanded"><!ENTITY b "&a;&a;&a;&a;">]>',
    '<!DOCTYPE w:document SYSTEM "http://example.invalid/x.dtd">',
    '<!DOCTYPE w:document>',
])
def test_a_docx_with_a_dtd_or_entity_is_refused_in_any_encoding(encoding, dtd):
    # Sol round 1: a UTF-16 document.xml passed the old byte search and its internal entity was expanded.
    declaration = f'<?xml version="1.0" encoding="{encoding.upper()}"?>' if not encoding.endswith(("le", "be")) else \
        f'<?xml version="1.0" encoding="UTF-16"?>'
    xml = f'{declaration}{dtd}<w:document {W_NS}><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    data = xml.encode(encoding)
    if encoding in ("utf-16-le", "utf-16-be"):
        data = ("\ufeff" + xml).encode(encoding)
    assert b"<!DOCTYPE" not in data or encoding == "utf-8"
    with pytest.raises(DraftRefused) as caught:
        read_draft(docx_xml(data), "draft.docx", None)
    assert caught.value.code == "draft_unreadable"


def test_a_utf16_docx_without_a_dtd_still_reads():
    xml = f'<?xml version="1.0" encoding="UTF-16"?><w:document {W_NS}><w:body><w:p><w:r><w:t>Claim [1].</w:t></w:r></w:p>' \
          '</w:body></w:document>'
    assert read_draft(docx_xml(xml.encode("utf-16")), "draft.docx", None) == ("docx", "Claim [1].")


def list_of(count, numbered=True):
    return "\n".join(f"[{i}] A. Author{i}, \"Title {i},\" 2020." if numbered else f"Author{i}, A. (2020). Title {i}. J."
                     for i in range(1, count + 1))


@pytest.mark.parametrize("draft, fmt", [
    # Sol round 1: 501 entries with a second [1] after the first 500 — the old cut dropped it and bound [1] to the first.
    ("Claim [1].\n\nReferences\n" + list_of(500) + "\n[1] B. Second, \"Duplicate one,\" 2021.", "md"),
    ("Claim (Author1, 2020).\n\nReferences\n" + list_of(501, numbered=False), "text"),
    ("\\begin{document}See \\cite{k1}.\n\\begin{thebibliography}{9}\n"
     + "\n".join(f"\\bibitem{{k{i}}} A. Author, T{i}, 2020." for i in range(1, 502)) + "\n\\end{thebibliography}\\end{document}", "tex"),
])
def test_a_reference_list_over_the_cap_is_refused_whole_never_cut(draft, fmt):
    with pytest.raises(DraftRefused) as caught:
        parse_draft(fmt, draft)
    assert caught.value.code == "draft_list_too_long" and caught.value.status == 413


def test_a_reference_list_at_the_cap_is_read_whole():
    draft = parse_draft("md", "Claim [1].\n\nReferences\n" + list_of(500))
    assert len(draft.list_entries) == 500 and draft.list_entries[-1].number == 500


def test_narrative_names_cut_by_the_look_back_window_are_unrecognized():
    names = ", ".join(f"Name{chr(65 + i % 26)}x" for i in range(30))
    found = parse_draft("md", f"As {names} and Zeng (2022) said.").markers
    assert [(m.style, m.status, m.targets) for m in found] == [("author_year", "unrecognized", [])]


@pytest.mark.parametrize("name, key", [("van der Berg", "van der berg"), ("Anna van der Berg", "van der berg"),
                                       ("Berg", "berg"), ("A. Berg", "berg"), ("Van Morrison", "van morrison"),
                                       ("De Vries", "de vries"), ("Van der Berg", "van der berg"),
                                       ("Ludwig van Beethoven", "van beethoven"), ("Müller", "muller"),
                                       ("al Farsi", "al farsi")])
def test_surnames_keep_their_particles(name, key):
    assert draft_parse.surname_key(name) == key


def test_too_many_markers_are_refused_while_they_are_found(monkeypatch):
    monkeypatch.setattr(draft_parse, "MAX_MARKERS", 3)
    assert len(parse_draft("md", "A [1]. B [2]. C [3].").markers) == 3
    with pytest.raises(DraftRefused) as caught:
        parse_draft("md", "A [1]. B [2]. C [3]. D [4].")
    assert caught.value.code == "draft_too_many_markers"
    # The cap stops the scan itself: the overlap pass never sees more than MAX_MARKERS candidates.
    monkeypatch.setattr(draft_parse, "_author_year", lambda *_: pytest.fail("the scan went on past the cap"))
    with pytest.raises(DraftRefused):
        parse_draft("md", "A [1]. B [2]. C [3]. D [4].")


@pytest.mark.parametrize("text, names", [
    # Sol round 2: the narrative match started at the tail of the author phrase.
    ("Smith and Van Berg (2022) found it.", ("Smith", "Van Berg")),
    ("As De Vries (2022) found.", ("De Vries",)),
    ("As shown by Zeng (2022) here.", ("Zeng",)),
    ("In Zeng (2022), it holds.", ("Zeng",)),
])
def test_narrative_names_take_the_whole_phrase(text, names):
    [marker] = parse_draft("md", text).markers
    assert (marker.status, marker.targets[0].names) == ("recognized", names)


@pytest.mark.parametrize("text", ["Anna Berg (2022) found it.", "results and Berg (2022) found it.",
                                  "data, Berg (2022) found it.", "results & Berg (2022) found it."])
def test_a_narrative_phrase_with_an_unclear_start_is_unrecognized(text):
    assert [(m.status, m.targets) for m in parse_draft("md", text).markers] == [("unrecognized", [])]

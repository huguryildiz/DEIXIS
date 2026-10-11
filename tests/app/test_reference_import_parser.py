"""BibTeX and RIS parsing for the Library import (UI parity S19b). Fixtures are SYNTHETIC; this measures the parser,
not any provider."""

from pathlib import Path

import pytest

from deixis.imports import bibtex_ris as b

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def read(name, fmt=None):
    data = (FIXTURES / name).read_bytes()
    return b.read_file(data, name, fmt)


def test_bibtex_fixture_reads_braces_quotes_strings_and_authors():
    fmt, entries, errors = read("synthetic.bib")
    assert fmt == "bibtex"
    by_key = {e.key: e for e in entries}
    assert list(by_key) == ["lovelace2021diffusion", "relay2020", "godel1931"]
    first = by_key["lovelace2021diffusion"]
    # Braces dropped, accents turned into Unicode, an escaped & kept, math left as written.
    assert first.title == "SYNTHETIC Diffusion Scheduling with $\\alpha$-stable Noise & Müller's étude"
    # Last, First / braced corporate name / Last, Jr, First; "others" is not an author.
    assert first.authors == ["Ada Lovelace", "Jörg Müller", "Synthetic Consortium", "John Doe Jr"]
    assert first.venue == "Synthetic Journal of Letters"  # @string concatenated with #
    assert (first.year, first.volume, first.issue, first.pages) == (2021, "12", "3", "10-20")
    assert first.doi == "10.5555/syn.hit" and first.publication_type == "journalArticle"
    assert first.abstract == "We schedule molecule releases."
    relay = by_key["relay2020"]  # parenthesised entry, quoted values
    assert (relay.title, relay.authors, relay.venue, relay.year) == (
        "SYNTHETIC relay budget under drift", ["Q. Synthetic", "R. Example"], "Proc. Synthetic Workshop", 2020)
    assert relay.publication_type == "conferencePaper" and relay.doi == "10.5555/syn.miss"
    book = by_key["godel1931"]  # missing fields stay empty; the year comes from biblatex `date`
    assert (book.title, book.authors, book.year, book.venue, book.doi, book.pages) == (
        "SYNTHETIC Book on Gašper Çelik and øystein", ["Kurt Gödel"], 1931, "Synthetic Press", None, None)
    assert [(e.index, e.key, e.code) for e in errors] == [
        (3, "unclosed2019", "unclosed_value"), (5, "notitle2018", "no_title"),
        (6, "undefined2017", "undefined_string"), (7, "baddoi2016", "invalid_doi")]
    assert all(e.line > 1 for e in errors)


def test_a_malformed_entry_does_not_take_the_next_one_with_it():
    text = ("@article{a, title = {SYNTHETIC one}}\n"
            "@article{b, title = {SYNTHETIC never closed}\n"
            "@article{c, title = {SYNTHETIC three}, year = 2001}\n"
            "@article{d title = {no key}}\n"
            "@article{e, title = {SYNTHETIC} junk}\n"
            "@article{f, title = {SYNTHETIC tail}}\n")
    entries, errors = b.parse_bibtex(text)
    assert [e.key for e in entries] == ["a", "c", "f"]
    assert [(e.index, e.key, e.code) for e in errors] == [
        (2, "b", "unclosed_entry"), (4, None, "missing_key"), (5, "e", "unclosed_entry")]


def test_a_value_left_open_to_the_end_of_the_file_is_an_error():
    entries, errors = b.parse_bibtex("@article{a, title = {SYNTHETIC open")
    assert entries == [] and [(e.code, e.line) for e in errors] == [("unclosed_value", 1)]


def test_doi_and_url_keep_their_characters():
    entries, _ = b.parse_bibtex(r"@article{a, title={SYNTHETIC}, doi={10.5555/a--b\_c}, url={https://example.org/x--y}}")
    assert (entries[0].doi, entries[0].url) == ("10.5555/a--b_c", "https://example.org/x--y")
    entries, _ = b.parse_bibtex("@article{a, title={SYNTHETIC}, url={https://doi.org/10.5555/FromUrl}}")
    assert entries[0].doi == "10.5555/fromurl"


def test_ris_fixture_reads_records_and_reports_the_broken_ones():
    fmt, entries, errors = read("synthetic.ris")
    assert fmt == "ris"
    first, book = entries
    assert (first.key, first.title, first.authors, first.year) == (
        "ris-one", "SYNTHETIC RIS diffusion record", ["Ada Lovelace", "John Doe Jr."], 2019)
    assert (first.venue, first.volume, first.issue, first.pages, first.doi) == ("Synthetic Journal", "4", "2", "1-9", "10.5555/syn.hit")
    assert first.abstract == "A first line of the abstract that wraps to a second line."
    assert (book.index, book.title, book.authors, book.year, book.venue, book.publication_type) == (
        3, "SYNTHETIC RIS book without DOI", ["Rae Example"], 2001, "Synthetic Press", "book")
    assert [(e.index, e.code) for e in errors] == [(2, "unclosed_record"), (4, "no_title"), (None, "outside_record")]


@pytest.mark.parametrize("encode", [
    lambda t: t.encode("utf-8"),
    lambda t: b"\xef\xbb\xbf" + t.encode("utf-8"),
    lambda t: t.encode("utf-16"),  # with its BOM
    lambda t: t.encode("cp1252"),
])
def test_encodings(encode):
    _, entries, _ = b.read_file(encode("@article{k, title = {SYNTHETIC Café Ørsted}}"), "x.bib")
    assert entries[0].title == "SYNTHETIC Café Ørsted"
    _, entries, _ = b.read_file(encode("TY  - JOUR\r\nTI  - SYNTHETIC Café\r\nER  - \r\n"), "x.ris")
    assert entries[0].title == "SYNTHETIC Café"


def test_format_detection_and_whole_file_refusals(monkeypatch):
    assert b.read_file(b"TY  - JOUR\nTI  - SYNTHETIC\nER  - \n", "export.txt")[0] == "ris"
    assert b.read_file(b"% note\n@article{k, title={SYNTHETIC}}", None)[0] == "bibtex"
    for data, code in ((b"just some words", "import_unknown_format"), (b"\x00\x01binary", "import_not_text")):
        with pytest.raises(b.ImportRefused) as refused:
            b.read_file(data, "x.txt")
        assert refused.value.code == code
    with pytest.raises(b.ImportRefused) as refused:
        b.read_file(b" " * (b.MAX_FILE_BYTES + 1), "x.bib")
    assert (refused.value.status, refused.value.code) == (413, "import_too_large")
    monkeypatch.setattr(b, "MAX_ENTRIES", 2)
    with pytest.raises(b.ImportRefused) as refused:
        b.read_file(b"@article{a, title={A}}\n@article{b, title={B}}\n@article{c}\n", "x.bib")
    assert refused.value.code == "import_too_many_entries"


def test_identity_is_the_same_for_the_same_entry_in_either_format():
    _, bib, _ = b.read_file(b"@book{k, title={SYNTHETIC Same Book}, author={Example, Rae}, year={2001}}", "x.bib")
    _, ris, _ = b.read_file(b"TY  - BOOK\nTI  - SYNTHETIC same book\nAU  - Example, Rae\nPY  - 2001\nER  - \n", "x.ris")
    assert b.identity(bib[0]) == b.identity(ris[0]) and b.identity(bib[0]).startswith("entry:")

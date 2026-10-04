"""BibTeX and RIS export of included and cited sources (D16)."""

from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.workflow import bibliography
from fakes import FakeAdapter
from helpers import make_pdf


def source(**overrides):
    return {"title": "Global optimization in design & control", "authors": ["Christodoulos A. Floudas", "Chrysanthos E. Gounaris"],
            "year": 2009, "venue": "Journal of Global_Optimization", "publication_type": "article",
            "doi": "10.1007/s10898_008", "landing_url": "https://doi.org/10.1007/s10898_008",
            "version_label": "publishedVersion", "arxiv_id": None} | overrides


def test_bibtex_maps_types_escapes_text_and_keeps_keys_unique():
    text = bibliography.to_bibtex([
        source(),
        source(title="Global scheduling", publication_type="proceedings-article", venue="Proc. CDC"),
        source(title="A 50% faster solver {draft}", authors=["Research and Development Group"], year=None,
               publication_type="preprint", venue="arXiv", doi="10.48550/arxiv.2101.00001", landing_url=None,
               version_label="arXiv v2", arxiv_id="2101.00001v2"),
    ])
    assert text.startswith(
        "@article{floudas2009global,\n"
        "  title = {Global optimization in design \\& control},\n"
        "  author = {Christodoulos A. Floudas and Chrysanthos E. Gounaris},\n"
        "  year = {2009},\n"
        "  journal = {Journal of Global\\_Optimization},\n"
        "  doi = {10.1007/s10898_008},\n"
        "  url = {https://doi.org/10.1007/s10898_008},\n"
        "  note = {Source version read in DEIXIS: published version}\n}\n"
    )
    assert "@inproceedings{floudas2009globalb,\n" in text and "  booktitle = {Proc. CDC},\n" in text
    assert ("@misc{group50,\n"
            "  title = {A 50\\% faster solver \\{draft\\}},\n"
            "  author = {{Research and Development Group}},\n"
            "  howpublished = {arXiv},\n"
            "  doi = {10.48550/arxiv.2101.00001},\n"
            "  eprint = {2101.00001v2},\n"
            "  eprinttype = {arxiv},\n"
            "  note = {Source version read in DEIXIS: arXiv v2}\n}\n") in text


def test_ris_uses_zotero_types_one_author_per_line_and_crlf():
    text = bibliography.to_ris([source(), source(title="A chapter", publication_type="bookSection", venue="Handbook",
                                                 authors=["Solo"], doi=None, landing_url=None, version_label=None)])
    assert text == "\r\n".join([
        "TY  - JOUR", "TI  - Global optimization in design & control", "AU  - Christodoulos A. Floudas",
        "AU  - Chrysanthos E. Gounaris", "PY  - 2009", "T2  - Journal of Global_Optimization", "DO  - 10.1007/s10898_008",
        "UR  - https://doi.org/10.1007/s10898_008", "N1  - Source version read in DEIXIS: published version", "ER  - ", "",
        "TY  - CHAP", "TI  - A chapter", "AU  - Solo", "PY  - 2009", "T2  - Handbook", "ER  - ", "",
    ])


def test_export_downloads_included_sources_and_refuses_an_empty_cited_set(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    app = create_app(settings, adapters={"fake": FakeAdapter()}, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid = client.post("/api/researches", json={"question": "How is molecule release scheduling optimized?", "source_scope": "attached",
                                                   "model_connection": "fake", "requested_model": "fake-model"}).json()["research"]["id"]
        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("molecule_paper.pdf", make_pdf(["SYNTHETIC text"]), "application/pdf")})
        assert upload.status_code == 201, upload.text

        response = client.get(f"/api/researches/{rid}/bibliography", params={"format": "ris"})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/x-research-info-systems")
        assert response.headers["content-disposition"] == 'attachment; filename="deixis-how-is-molecule-release-scheduling-optim-included.ris"'
        assert response.text == "TY  - GEN\r\nTI  - molecule paper\r\nN1  - Source version read in DEIXIS: uploaded file\r\nER  - \r\n"

        assert client.get(f"/api/researches/{rid}/bibliography").text.startswith("@misc{anonmolecule,\n")
        cited = client.get(f"/api/researches/{rid}/bibliography", params={"sources": "cited"})
        assert cited.status_code == 422 and cited.json()["detail"] == "The latest answer cites no source"


def test_x3_default_full_literal_before_refactor():
    """Captured and read against D16 before changing bibliography.py."""
    sources = [source(title='SYNTHETIC {X} & 50%', authors=['Research and Development'], year=None,
                      venue='', publication_type=kind, doi=None, landing_url=None, version_label=None,
                      volume='2', issue='3', pages='4--5', arxiv_id='2601.12345')
               for kind in ['article', 'conference', 'bookSection', 'book', 'thesis', 'report', 'preprint']]
    assert bibliography.to_bibtex(sources) == (
        '@article{developmentsynthetic,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n\n'
        '@inproceedings{developmentsyntheticb,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n\n'
        '@incollection{developmentsyntheticc,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n\n'
        '@book{developmentsyntheticd,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n\n'
        '@phdthesis{developmentsynthetice,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n\n'
        '@techreport{developmentsyntheticf,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n\n'
        '@misc{developmentsyntheticg,\n'
        '  title = {SYNTHETIC \\{X\\} \\& 50\\%},\n'
        '  author = {{Research and Development}},\n'
        '  volume = {2},\n  number = {3},\n  pages = {4--5},\n'
        '  eprint = {2601.12345},\n  eprinttype = {arxiv}\n}\n'
    )


import re
from copy import deepcopy

import pytest

from deixis.workflow.report.latex_text import Unmapped


@pytest.mark.parametrize('latex_report', [False, True])
@pytest.mark.parametrize('keys', [[], ['K', 'L'], ['bad_key'], ['bad key'], ['bad\n'], ['-K'], [None], [True], ['K', 'k']])
def test_x3_given_key_boundary(keys, latex_report):
    sources = [source(), source()] if keys == ['K', 'k'] else [source()]
    with pytest.raises(ValueError, match='BibTeX keys must match'):
        bibliography.to_bibtex(sources, keys, latex_report=latex_report)


def test_x3_given_keys_change_only_keys_in_default_path():
    sources = [source(), source()]
    original = bibliography.to_bibtex(sources)
    expected = original.replace('floudas2009global,', 'K1,').replace('floudas2009globalb,', 'K2,')
    assert bibliography.to_bibtex(sources, ['K1', 'K2']) == expected
    assert bibliography.to_bibtex([], []) == ''


def test_x3_report_title_symbols_and_no_double_escape():
    text, notes = bibliography.bibtex_with_notes([source(title='a ≥ b & c', authors=['Research and Development'])], ['K'], latex_report=True)
    assert r'title = {{a \ensuremath{\geq} b \& c}}' in text
    assert r'author = {{Research and Development}}' in text
    assert 'textbackslash' not in text
    assert notes == []


@pytest.mark.parametrize('value', ['\\', '\n', '\t', '\r', '\0', '\u202e', '\u2028', '\u2029', '\ud800', '\ue000', '\u0378'])
@pytest.mark.parametrize('field,source_field', [('doi', 'doi'), ('url', 'landing_url'), ('eprint', 'arxiv_id')])
def test_x3_original_raw_field_controls_are_omitted(value, field, source_field):
    text, notes = bibliography.bibtex_with_notes([source(**{source_field: 'a' + value + 'b'})], ['K'], latex_report=True)
    assert f'  {field} = ' not in text
    assert notes == [f'Bibliography: omitted {field} of K because it holds a backslash or a control character.']


@pytest.mark.parametrize('year', [True, False, '', 2026.0, '2026}\\input{evil}', 'x\n@article{evil,'])
@pytest.mark.parametrize('given', [False, True])
def test_x3_year_cannot_reach_a_key_or_field(year, given):
    rows = [source(year=year)]
    before = deepcopy(rows)
    text, notes = bibliography.bibtex_with_notes(rows, ['K'] if given else None, latex_report=True)
    key = 'K' if given else 'floudasglobal'
    assert text.startswith('@article{' + key + ',')
    assert '  year = ' not in text and '\\input' not in text and '\n@article{evil' not in text
    assert notes == [f'Bibliography: omitted year of {key} because it is not a number.']
    assert rows == before


@pytest.mark.parametrize('year,expected', [(None, ''), (0, ''), (2026, '  year = {2026}')])
def test_x3_valid_years(year, expected):
    text, notes = bibliography.bibtex_with_notes([source(year=year)], latex_report=True)
    assert notes == []
    assert expected in text if expected else '  year = ' not in text


def _bib_braces(text):
    depth = 0
    for ch in text:
        depth += (ch == '{') - (ch == '}')
        assert depth >= 0
    assert depth == 0


@pytest.mark.parametrize('value', ['{', '}', '{x}'])
@pytest.mark.parametrize('field', ['title', 'authors', 'venue', 'version_label', 'volume', 'issue', 'pages'])
def test_x3_bibtex_counts_escaped_braces_too(value, field):
    row = source(**{field: [value + ' and Name'] if field == 'authors' else value})
    text = bibliography.to_bibtex([row], ['K'], latex_report=True)
    assert r'\{' not in text and r'\}' not in text
    assert r'\textbraceleft{}' in text if '{' in value else r'\textbraceright{}' in text
    _bib_braces(text)


def test_x3_shared_unmapped_collector_and_string_only_public_wrapper():
    um = Unmapped()
    text, notes = bibliography.bibtex_with_notes([source(title='文', authors=['文'])], ['K'], latex_report=True, unmapped=um)
    assert um.count == 2 and notes == [] and '文' in text
    result = bibliography.to_bibtex([source(title='文')], ['K'], latex_report=True)
    assert isinstance(result, str)


def test_x3_default_hostile_year_stays_legacy_but_report_is_closed():
    # Deliberately preserve the old Zotero behavior, only the report path is hardened.
    rows = [source(year='bad_year')]
    assert 'bad_year' in bibliography.to_bibtex(rows)
    assert 'bad_year' not in bibliography.to_bibtex(rows, latex_report=True)


def test_x3_generated_report_keys_checked(monkeypatch):
    monkeypatch.setattr(bibliography, '_keys', lambda rows: ['bad_key'])
    assert '@article{bad_key,' in bibliography.to_bibtex([source()])
    with pytest.raises(ValueError, match='BibTeX keys must match'):
        bibliography.to_bibtex([source()], latex_report=True)

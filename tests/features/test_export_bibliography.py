"""BibTeX and RIS export of included and cited sources (D16)."""

from urllib.parse import quote
import pytest
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
        name = "DEIXIS - How is molecule release scheduling optimized - included sources.ris"
        assert response.headers["content-disposition"] == f'attachment; filename="{name}"; filename*=UTF-8\'\'{quote(name, safe="")}'
        assert response.text == "TY  - GEN\r\nTI  - molecule paper\r\nN1  - Source version read in DEIXIS: uploaded file\r\nER  - \r\n"

        assert client.get(f"/api/researches/{rid}/bibliography").text.startswith("@misc{anonmolecule,\n")
        cited = client.get(f"/api/researches/{rid}/bibliography", params={"sources": "cited"})
        assert cited.status_code == 422 and cited.json()["detail"] == "The answer cites no source still in this research"
        # An answer id names one answer of this research; an unknown one is refused, never replaced by another answer.
        assert client.get(f"/api/researches/{rid}/bibliography", params={"sources": "cited", "answer_id": "ans_unknown"}).status_code == 404
        assert client.get(f"/api/researches/{rid}/bibliography", params={"answer_id": "ans_unknown"}).status_code == 422
        # An empty id is refused, not read as "the shown answer".
        empty = client.get(f"/api/researches/{rid}/bibliography", params={"sources": "cited", "answer_id": ""})
        assert empty.status_code == 422 and empty.json()["detail"] == "answer_id is empty"


# UI parity S10 (Sol round 2): cited sources follow one answer, from its stored evidence links, not the view's
# `cited_in_latest_answer` flags (which follow the newest answer, a failed late revision included).
def _cited_svids(lib, answer_id):
    return {r[0] for r in lib.store.conn.execute(
        "SELECT l.source_version_id FROM evidence_links l JOIN claims c ON c.id = l.claim_id WHERE c.answer_id = ?", (answer_id,))}


def _exported(lib, answer_id=None):
    return {s["source_version_id"] for s in bibliography.export_sources(lib.store, lib.rid, "cited", answer_id)}


def test_cited_export_after_a_failed_late_revision_lists_the_shown_answers_works(tmp_path):
    from test_fast_path_late_revision import drain, prepared, read_late
    from deixis.workflow import late_revision, views
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow)
    lib.flow.deps.adapters["fake"] = FakeAdapter(lambda si: '{}')
    drain(lib)
    view = views.research_view(lib.store, lib.rid)
    draft = view["answers"][0]
    assert draft["status"] == "unverified_draft" and draft["late_revision"]["base_answer_id"] == lib.base["id"]
    # The newest answer cites nothing, so its flags are empty; V1, the answer shown, cites sources.
    assert not any(s["cited_in_latest_answer"] for s in view["sources"])
    v1 = _cited_svids(lib, lib.base["id"])
    assert v1
    assert bibliography.shown_answer_id(view) == lib.base["id"]
    assert _exported(lib) == v1
    assert _exported(lib, lib.base["id"]) == v1
    assert _exported(lib, draft["id"]) == set()


from copy import deepcopy

import pytest


@pytest.mark.parametrize('value', ['\n'])
@pytest.mark.parametrize('field,source_field', [('doi', 'doi')])
def test_x3_original_raw_field_controls_are_omitted(value, field, source_field):
    text, notes = bibliography.bibtex_with_notes([source(**{source_field: 'a' + value + 'b'})], ['K'], latex_report=True)
    assert f'  {field} = ' not in text
    assert notes == [f'Bibliography: omitted {field} of K because it holds a backslash or a control character.']


@pytest.mark.parametrize('year', ['2026}\\input{evil}'])
@pytest.mark.parametrize('given', [True])
def test_x3_year_cannot_reach_a_key_or_field(year, given):
    rows = [source(year=year)]
    before = deepcopy(rows)
    text, notes = bibliography.bibtex_with_notes(rows, ['K'] if given else None, latex_report=True)
    key = 'K' if given else 'floudasglobal'
    assert text.startswith('@article{' + key + ',')
    assert '  year = ' not in text and '\\input' not in text and '\n@article{evil' not in text
    assert notes == [f'Bibliography: omitted year of {key} because it is not a number.']
    assert rows == before


def test_cited_export_refuses_an_unknown_answer_or_one_of_another_research(tmp_path):
    from test_fast_path_late_revision import prepared
    lib = prepared(tmp_path)
    other = lib.store.create_research("SYNTHETIC other question?", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    with pytest.raises(LookupError):
        bibliography.export_sources(lib.store, other, "cited", lib.base["id"])
    with pytest.raises(LookupError):
        bibliography.export_sources(lib.store, lib.rid, "cited", "ans_unknown")
    for empty in ("", "  "):
        with pytest.raises(LookupError):
            bibliography.export_sources(lib.store, lib.rid, "cited", empty)

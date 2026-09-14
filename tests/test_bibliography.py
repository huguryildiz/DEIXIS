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

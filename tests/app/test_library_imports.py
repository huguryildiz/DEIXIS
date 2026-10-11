"""Library imports (UI parity S19b, F14): a Zotero collection and BibTeX / RIS files into the Library, DOIs resolved
through mocked OpenAlex and Crossref lookups. Records are SYNTHETIC; nothing here measures live provider access."""

from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.imports import bibtex_ris
from deixis.storage.db import transaction
from fakes import FakeAdapter
from helpers import make_pdf
from test_zotero import COLLECTION, ROWS, no_fetch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def work(doi, title, wid):
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}", "display_name": title,
            "publication_year": 2021, "type": "article", "ids": {"openalex": f"https://openalex.org/{wid}"},
            "authorships": [{"author": {"display_name": "Ada Provider"}}],
            "primary_location": {"version": "publishedVersion", "source": {"display_name": "Provider Journal"}},
            "best_oa_location": None, "abstract_inverted_index": None}


class Providers:
    """OpenAlex answers a DOI filter from `works`; Crossref answers `/works/<doi>` from `crossref`, else 404.
    `openalex_status` / `crossref_status` other than 200 fail every request to that provider."""

    def __init__(self, works=(), crossref=None, openalex_status=200, crossref_status=200, zotero_files=None):
        self.works, self.crossref = list(works), dict(crossref or {})
        self.openalex_status, self.crossref_status = openalex_status, crossref_status
        self.zotero_files = zotero_files or {}
        self.seen = []

    def handler(self, request):
        self.seen.append(request)
        host, path = request.url.host, request.url.path
        if host == "api.openalex.org":
            if self.openalex_status != 200:
                return httpx.Response(self.openalex_status)
            asked = request.url.params["filter"].removeprefix("doi:").split("|")
            found = [w for w in self.works if w["doi"].removeprefix("https://doi.org/") in asked]
            return httpx.Response(200, json={"meta": {"count": len(found)}, "results": found})
        if host == "api.crossref.org":
            if self.crossref_status != 200:
                return httpx.Response(self.crossref_status)
            doi = unquote(path.removeprefix("/works/"))
            if doi in self.crossref:
                return httpx.Response(200, json={"message": self.crossref[doi]})
            return httpx.Response(404)
        if path.endswith(f"/collections/{COLLECTION}/items"):
            return httpx.Response(200, json=ROWS)
        if path.endswith("/file") and path.split("/")[-2] in self.zotero_files:
            return httpx.Response(302, headers={"location": self.zotero_files[path.split("/")[-2]]})
        return httpx.Response(404)

    def asked(self, host):
        return [r for r in self.seen if r.url.host == host]


def app_for(tmp_path, providers):
    settings = Settings(data_dir=tmp_path / "data", port=8765, search_query="code", fulltext_fetch="off")
    return create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(providers.handler)), fetcher=no_fetch, extra_hosts=("testserver",),
        trusted_clients=("testclient",))


def session(client):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def upload(client, name, data=None, **form):
    data = (FIXTURES / name).read_bytes() if data is None else data
    return client.post("/api/library/reference-imports", files={"file": (name, data, "application/octet-stream")},
                       data=form)


def item(store, svid):
    row = store.conn.execute("SELECT origin, metadata_origin, metadata_confirmed_by, metadata_confirmed_at"
                             " FROM library_items WHERE source_version_id = ?", (svid,)).fetchone()
    return tuple(row) if row else None


def providers_of(store, svid):
    return sorted(r[0] for r in store.conn.execute(
        "SELECT DISTINCT provider FROM identifier_mappings WHERE source_version_id = ?", (svid,)))


@pytest.mark.parametrize("path, kwargs", [
    ("/api/library/zotero-imports", {"json": {"source": "local", "collection_key": COLLECTION}}),
    ("/api/library/reference-imports", {"files": {"file": ("x.bib", b"@article{k, title={SYNTHETIC}}", "text/plain")}}),
])
def test_every_import_needs_the_csrf_token(tmp_path, path, kwargs):
    providers = Providers()
    app = app_for(tmp_path, providers)
    with TestClient(app) as raw:
        session(raw)
        assert raw.post(path, headers={"x-deixis-csrf": "wrong"}, **kwargs).status_code == 403
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0] == 0
        assert providers.seen == []


def test_bibtex_import_resolves_dois_and_marks_whose_metadata_each_item_carries(tmp_path):
    crossref_item = {"DOI": "10.5555/SYN.Crossref", "title": ["SYNTHETIC Crossref record"], "type": "journal-article",
                     "author": [{"given": "Cy", "family": "Ross"}], "issued": {"date-parts": [[2018]]},
                     "container-title": ["Crossref Journal"], "URL": "https://doi.org/10.5555/syn.crossref"}
    providers = Providers(works=[work("10.5555/syn.hit", "SYNTHETIC provider title", "W100")],
                          crossref={"10.5555/syn.crossref": crossref_item})
    app = app_for(tmp_path, providers)
    extra = b"\n@article{cr2018, title = {SYNTHETIC my own title}, doi = {10.5555/syn.crossref}}\n"
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        response = upload(client, "synthetic.bib", (FIXTURES / "synthetic.bib").read_bytes() + extra)
        assert response.status_code == 201, response.text
        body = response.json()["reference_import"]
        rows = {r["key"]: r for r in body["entries"]}
        assert body["format"] == "bibtex" and body["filename"] == "synthetic.bib"
        assert [e["code"] for e in body["errors"]] == ["unclosed_value", "no_title", "undefined_string", "invalid_doi"]

        hit = rows["lovelace2021diffusion"]
        assert (hit["lookup"], hit["record"], hit["confirmed_by"]) == ("confirmed", "provider", "openalex")
        source = store.source(hit["source_version_id"])
        # The provider's record is stored, not the entry's own fields.
        assert (source["title"], source["authors"]) == ("SYNTHETIC provider title", ["Ada Provider"])
        origin, metadata, by, at = item(store, hit["source_version_id"])
        assert (origin, metadata, by) == ("bibtex_import", "user_supplied", "openalex") and at is not None

        miss = rows["relay2020"]  # OpenAlex has no work, Crossref answers 404
        assert (miss["lookup"], miss["record"], miss["confirmed_by"]) == ("not_found", "user_supplied", None)
        source = store.source(miss["source_version_id"])
        assert (source["title"], source["doi"], source["venue"]) == (
            "SYNTHETIC relay budget under drift", "10.5555/syn.miss", "Proc. Synthetic Workshop")
        assert item(store, miss["source_version_id"]) == ("bibtex_import", "user_supplied", None, None)
        assert providers_of(store, miss["source_version_id"]) == ["reference_file"]
        # An unconfirmed DOI is not a merge key: no later record with this DOI is merged into the entry's.
        assert store.find_source_by_identifier("doi", "10.5555/syn.miss") is None

        no_doi = rows["godel1931"]
        assert (no_doi["lookup"], no_doi["record"]) == ("no_doi", "user_supplied")
        crossref = rows["cr2018"]
        assert (crossref["lookup"], crossref["confirmed_by"]) == ("confirmed", "crossref")
        assert store.source(crossref["source_version_id"])["title"] == "SYNTHETIC Crossref record"

        # One OpenAlex request for every DOI; Crossref only for the DOIs OpenAlex did not confirm.
        assert len(providers.asked("api.openalex.org")) == 1
        assert sorted(unquote(r.url.path) for r in providers.asked("api.crossref.org")) == [
            "/works/10.5555/syn.crossref", "/works/10.5555/syn.miss"]
        assert {r.method for r in providers.seen} == {"GET"}
        library = {e["representative_source_version_id"] for e in response.json()["library"]["entries"]}
        assert {r["source_version_id"] for r in body["entries"]} <= library
        assert store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0


def test_a_provider_error_leaves_the_entry_user_supplied_and_a_stored_doi_record_is_reused(tmp_path):
    providers = Providers(openalex_status=500, crossref_status=503)
    app = app_for(tmp_path, providers)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        stored = Providers(works=[work("10.5555/syn.stored", "SYNTHETIC stored provider record", "W7")])
        # A record a search stored earlier under this DOI.
        from deixis.providers.openalex import _record
        with transaction(store.conn):
            stored_svid, _ = store.upsert_provider_source("openalex", _record(stored.works[0]), None)
        text = (b"@article{down, title = {SYNTHETIC lookup down}, doi = {10.5555/syn.down}}\n"
                b"@article{known, title = {SYNTHETIC my title for a stored work}, doi = {10.5555/syn.stored}}\n")
        body = upload(client, "down.bib", text).json()["reference_import"]
        down, known = body["entries"]
        assert (down["lookup"], down["record"], down["confirmed_by"]) == ("failed", "user_supplied", None)
        assert item(store, down["source_version_id"])[1:] == ("user_supplied", None, None)
        assert (known["lookup"], known["record"], known["source_version_id"]) == ("failed", "existing", stored_svid)
        # The stored record is OpenAlex's own; the entry's title is not written into it.
        assert store.source(stored_svid)["title"] == "SYNTHETIC stored provider record"
        assert item(store, stored_svid)[:3] == ("bibtex_import", "user_supplied", "openalex")


def test_duplicates_in_a_file_and_a_second_import_add_nothing(tmp_path):
    providers = Providers(works=[work("10.5555/syn.hit", "SYNTHETIC provider title", "W100")])
    app = app_for(tmp_path, providers)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        first = upload(client, "synthetic.ris").json()["reference_import"]
        assert [r["key"] for r in first["entries"]] == ["ris-one", None]
        assert [e["code"] for e in first["errors"]] == ["unclosed_record", "no_title", "outside_record"]
        assert all(item(store, r["source_version_id"])[0] == "ris_import" for r in first["entries"])
        versions = store.conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0]

        # The same book from a .bib file finds the record the .ris entry made; it is already saved.
        twice = (b"@book{a, title={SYNTHETIC RIS book without DOI}, author={Example, Rae}, year={2001}}\n"
                 b"@book{b, title={SYNTHETIC RIS Book Without DOI}, author={Example, Rae}, year={2001}}\n"
                 b"@article{c, title={SYNTHETIC again}, doi={10.5555/SYN.HIT}}\n")
        again = upload(client, "again.bib", twice).json()["reference_import"]
        a, b_, c = again["entries"]
        book = first["entries"][1]["source_version_id"]
        assert a["source_version_id"] == b_["source_version_id"] == book
        assert (a["duplicate_of"], b_["duplicate_of"]) == (None, 1)
        assert c["source_version_id"] == first["entries"][0]["source_version_id"]
        assert again["saved"] == [] and set(again["already_saved"]) == {book, c["source_version_id"]}
        assert store.conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0] == versions
        # The first import's origin stands.
        assert item(store, book)[0] == "ris_import"


def test_reference_import_refusals(tmp_path, monkeypatch):
    providers = Providers()
    app = app_for(tmp_path, providers)
    with TestClient(app) as raw:
        client = session(raw)
        refused = upload(client, "notes.txt", b"plain SYNTHETIC words")
        assert (refused.status_code, refused.json()["code"]) == (422, "import_unknown_format")
        refused = upload(client, "broken.bib", b"@article{a, title = {never closed")
        assert (refused.status_code, refused.json()["code"]) == (422, "import_no_entries")
        assert [e["code"] for e in refused.json()["errors"]] == ["unclosed_value"]
        refused = upload(client, "x.ris", b"@article{a, title={SYNTHETIC}}", format="bibtex")
        assert refused.status_code == 201  # the form's format wins over the file name
        assert upload(client, "x.bib", b"x", format="endnote").status_code == 422
        monkeypatch.setattr(bibtex_ris, "MAX_FILE_BYTES", 10)
        refused = upload(client, "big.bib", b"@article{a, title={SYNTHETIC long}}")
        assert (refused.status_code, refused.json()["code"]) == (413, "import_too_large")
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0] == 1


def test_zotero_collection_goes_into_the_library_with_its_pdfs(tmp_path, monkeypatch):
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    files = {}
    for key in ("PDFA1234", "LNKD1234", "STND1234"):
        path = tmp_path / f"{key}.pdf"
        path.write_bytes(make_pdf([f"SYNTHETIC text of {key}"]))
        files[key] = path.as_uri()
    providers = Providers(zotero_files=files)
    app = app_for(tmp_path, providers)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        response = client.post("/api/library/zotero-imports", json={"source": "local", "collection_key": COLLECTION})
        assert response.status_code == 201, response.text
        result = response.json()["zotero_import"]
        assert (result["items"], result["pdfs_added"], result["notes"], result["already_saved"]) == (3, 3, [], [])
        assert len(result["saved"]) == 3
        for svid in result["saved"]:
            assert item(store, svid)[:3] == ("zotero_import", "user_supplied", None)
            assert providers_of(store, svid) == ["zotero"] and store.has_asset(svid)
        titles = {e["title"] for e in response.json()["library"]["entries"]}
        assert titles == {"SYNTHETIC diffusion scheduling", "SYNTHETIC relay budget", "loose-notes.pdf"}
        assert store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0

        again = client.post("/api/library/zotero-imports", json={"source": "local", "collection_key": COLLECTION}).json()
        assert again["zotero_import"]["pdfs_added"] == 0 and again["zotero_import"]["saved"] == []
        assert sorted(again["zotero_import"]["already_saved"]) == sorted(result["saved"])

        assert client.post("/api/library/zotero-imports", json={"source": "local", "collection_key": "bad"}).status_code == 422
        assert client.post("/api/library/zotero-imports", json={"source": "web", "collection_key": COLLECTION}).status_code == 422


def arxiv_record(record_id, title):
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(provider_record_id=record_id, title=title, authors=["Ada Provider"], year=2021, venue="arXiv",
                          publication_type="preprint", doi="10.48550/arxiv.2101.00001", landing_url=None,
                          oa_pdf_url=None, oa_pdf_version=None, version_label="submittedVersion", abstract=None,
                          abstract_origin=None, identifiers={}, raw={}, merge_by_doi=False)


def test_an_unconfirmed_arxiv_doi_never_joins_or_takes_in_another_work(tmp_path):
    providers = Providers(openalex_status=500, crossref_status=503)
    app = app_for(tmp_path, providers)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        with transaction(store.conn):
            v1, _ = store.upsert_provider_source("arxiv", arxiv_record("2101.00001v1", "SYNTHETIC arXiv preprint"), None)
            v2, _ = store.upsert_provider_source("arxiv", arxiv_record("2101.00001v2", "SYNTHETIC arXiv preprint"), None)
        # Trusted arXiv versions of one preprint still share their work (D46).
        assert store.source(v1)["work_id"] == store.source(v2)["work_id"]
        entry = b"@article{wrong, title = {SYNTHETIC unrelated paper}, doi = {10.48550/arXiv.2101.00001}}"
        row = upload(client, "wrong.bib", entry).json()["reference_import"]["entries"][0]
        assert (row["lookup"], row["record"]) == ("failed", "user_supplied")
        assert row["work_id"] != store.source(v1)["work_id"]
        # Nor does a trusted version stored later join the unconfirmed entry's work.
        with transaction(store.conn):
            v3, _ = store.upsert_provider_source("arxiv", arxiv_record("2101.00001v3", "SYNTHETIC arXiv preprint"), None)
        assert store.source(v3)["work_id"] == store.source(v1)["work_id"] != row["work_id"]

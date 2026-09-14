"""Zotero collection import through mocked local and zotero.org APIs (D16). No live Zotero is exercised here."""

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers import zotero
from fakes import FakeAdapter
from helpers import make_pdf

COLLECTION = "KNWN2345"
ROWS = [
    {"key": "ART12345", "data": {"key": "ART12345", "itemType": "journalArticle", "title": "SYNTHETIC diffusion scheduling",
                                 "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                                              {"creatorType": "editor", "firstName": "Ed", "lastName": "Itor"}],
                                 "abstractNote": "We schedule molecule releases.", "publicationTitle": "Synthetic J",
                                 "date": "2021-03-04", "DOI": "https://doi.org/10.1/ZOT", "url": "https://example.org/art"}},
    {"key": "PDFA1234", "data": {"key": "PDFA1234", "itemType": "attachment", "parentItem": "ART12345", "linkMode": "imported_file",
                                 "contentType": "application/pdf", "filename": "art.pdf", "dateAdded": "2021-03-05T00:00:00Z"}},
    {"key": "NOTE1234", "data": {"key": "NOTE1234", "itemType": "note", "parentItem": "ART12345", "note": "<p>read</p>"}},
    {"key": "CNF12345", "data": {"key": "CNF12345", "itemType": "conferencePaper", "title": "SYNTHETIC relay budget",
                                 "creators": [{"creatorType": "author", "name": "Synthetic Consortium"}],
                                 "proceedingsTitle": "Proc. Synthetic", "extra": "Citation Key: x\nDOI: 10.1/CNF"}},
    {"key": "LNKD1234", "data": {"key": "LNKD1234", "itemType": "attachment", "parentItem": "CNF12345", "linkMode": "linked_file",
                                 "contentType": "application/pdf", "path": "/elsewhere/cnf.pdf"}},
    {"key": "STND1234", "data": {"key": "STND1234", "itemType": "attachment", "title": "loose-notes.pdf", "linkMode": "imported_file",
                                 "contentType": "application/pdf", "filename": "loose-notes.pdf"}},
    {"key": "WEBL1234", "data": {"key": "WEBL1234", "itemType": "attachment", "title": "A saved link", "linkMode": "linked_url",
                                 "contentType": ""}},
]
COLLECTIONS = [{"key": COLLECTION, "data": {"key": COLLECTION, "name": "Known set", "parentCollection": "THES2345"}},
               {"key": "THES2345", "data": {"key": "THES2345", "name": "Thesis", "parentCollection": False}}]


def zotero_client(files, seen, page_size=None):
    def handler(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/collections"):
            return httpx.Response(200, json=COLLECTIONS)
        if path.endswith(f"/collections/{COLLECTION}/items"):
            if page_size is None:
                return httpx.Response(200, json=ROWS)
            start = int(request.url.params["start"])
            return httpx.Response(200, json=ROWS[start:start + page_size], headers={"total-results": str(len(ROWS))})
        if path.endswith("/file") and path.split("/")[-2] in files:
            return httpx.Response(302, headers={"location": files[path.split("/")[-2]]})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def no_fetch(url):
    raise AssertionError(f"unexpected download of {url}")


def app_for(tmp_path, http_client, fetcher=no_fetch):
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    return create_app(settings, adapters={"fake": FakeAdapter()}, http_client=http_client, fetcher=fetcher,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def start(client, scope="attached"):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    response = client.post("/api/researches", json={"question": "How is molecule release scheduling optimized?", "source_scope": scope,
                                                    "model_connection": "fake", "requested_model": "fake-model"})
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def test_local_import_includes_items_with_pdf_text_and_repeats_without_duplicates(tmp_path):
    files = {}
    for key in ("PDFA1234", "LNKD1234", "STND1234"):
        path = tmp_path / f"{key} file.pdf"
        path.write_bytes(make_pdf([f"SYNTHETIC text of {key}"]))
        files[key] = path.as_uri()
    seen = []
    with TestClient(app_for(tmp_path, zotero_client(files, seen))) as client:
        rid = start(client)
        collections = client.get("/api/zotero/collections", params={"source": "local"}).json()["collections"]
        assert collections == [{"key": "THES2345", "name": "Thesis"}, {"key": COLLECTION, "name": "Thesis / Known set"}]

        response = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": COLLECTION})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["zotero_import"] == {"items": 3, "pdfs_added": 3, "notes": []}
        sources = {s["title"]: s for s in body["sources"]}
        assert set(sources) == {"SYNTHETIC diffusion scheduling", "SYNTHETIC relay budget", "loose-notes.pdf"}
        article, paper = sources["SYNTHETIC diffusion scheduling"], sources["SYNTHETIC relay budget"]
        assert (article["authors"], article["year"], article["venue"], article["doi"]) == (["Ada Lovelace"], 2021, "Synthetic J", "10.1/zot")
        assert article["publication_type"] == "journalArticle" and article["version_label"] is None
        assert article["access"]["abstract_origin"] == "zotero_abstract_note"
        assert (paper["authors"], paper["venue"], paper["doi"]) == (["Synthetic Consortium"], "Proc. Synthetic", "10.1/cnf")
        for s in sources.values():
            assert (s["added_by"], s["version_role"], s["provider_records"]) == ("zotero_import", "record", ["zotero"])
            assert (s["selection"]["state"], s["selection"]["origin"]) == ("included", "user")
            assert [a["extraction_status"] for a in s["access"]["assets"]] == ["succeeded"]
        assert {r.method for r in seen} == {"GET"} and not any("zotero-api-key" in r.headers for r in seen)

        again = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": COLLECTION}).json()
        assert again["zotero_import"] == {"items": 3, "pdfs_added": 0, "notes": []}
        assert len(again["sources"]) == 3 and all(len(s["access"]["assets"]) == 1 for s in again["sources"])

        ris = client.get(f"/api/researches/{rid}/bibliography", params={"format": "ris"}).text
        assert "TY  - JOUR\r\nTI  - SYNTHETIC diffusion scheduling\r\nAU  - Ada Lovelace\r\nPY  - 2021\r\nT2  - Synthetic J\r\nDO  - 10.1/zot" in ris
        assert "TY  - CONF\r\nTI  - SYNTHETIC relay budget" in ris


def test_web_import_reads_pages_and_sends_the_key_only_to_zotero_org(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOTERO_API_KEY", "zkey-secret-value")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "12345")
    monkeypatch.delenv("ZOTERO_LIBRARY_TYPE", raising=False)
    monkeypatch.setattr(zotero, "WEB_PAGE_SIZE", 2)
    storage = "https://zoterofilestorage.example/abc?X-Amz-Security-Token=signed"
    fetched = []

    async def fetch(url):
        fetched.append(url)
        return FetchResult("ok", data=make_pdf([f"SYNTHETIC web copy {len(fetched)}"]), final_url=url, http_status=200)

    seen = []
    with TestClient(app_for(tmp_path, zotero_client({"PDFA1234": storage, "STND1234": storage}, seen, page_size=2), fetch)) as client:
        rid = start(client, scope="attached_and_academic")
        response = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "web", "collection_key": COLLECTION})
        assert response.status_code == 201, response.text
        assert response.json()["zotero_import"] == {
            "items": 3, "pdfs_added": 2,
            "notes": [{"title": "SYNTHETIC relay budget", "note": "its PDF is a linked file, which zotero.org does not store"}],
        }
        assert fetched == [storage, storage]
        assert all(r.url.host == "api.zotero.org" and r.url.path.startswith("/users/12345/") for r in seen)
        assert all(r.headers["zotero-api-key"] == "zkey-secret-value" for r in seen)
        assert [r.url.params["start"] for r in seen if r.url.path.endswith("/items")] == ["0", "2", "4", "6"]
        stored = "".join(p.read_text() for p in (tmp_path / "data" / "provider-payloads").iterdir())
        assert "LNKD1234" in stored and "zkey-secret-value" not in stored


def test_unavailable_zotero_and_academic_scope_explain_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)

    def refuse(request):
        if request.url.path.endswith("/collections"):
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(403, text="Local API is not enabled")

    with TestClient(app_for(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(refuse)))) as client:
        rid = start(client)
        not_running = client.get("/api/zotero/collections", params={"source": "local"})
        assert not_running.status_code == 503 and not_running.json()["detail"] == zotero.LOCAL_NOT_RUNNING
        turned_off = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": COLLECTION})
        assert turned_off.status_code == 503 and turned_off.json()["detail"] == zotero.LOCAL_TURNED_OFF
        web = client.get("/api/zotero/collections", params={"source": "web"})
        assert web.status_code == 422 and "ZOTERO_API_KEY" in web.json()["detail"]
        academic = start(client, scope="academic")
        refused = client.post(f"/api/researches/{academic}/zotero-imports", json={"source": "local", "collection_key": COLLECTION})
        assert refused.status_code == 422 and "source scope" in refused.json()["detail"]

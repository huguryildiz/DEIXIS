"""Zotero: local and web import, the key sent only to zotero.org, waiting works matched in Zotero, note templates.

Mocked Zotero HTTP and SYNTHETIC items. Passing shows the import and matching behaviour, not that a live Zotero answers
the same way.
"""

import ast
import httpx
import re
from fastapi.testclient import TestClient
from pathlib import Path

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers import zotero
from deixis.workflow.read import text_retry
from fakes import FakeAdapter
from helpers import make_pdf
from test_waiting_flow import settled_runs
from test_waiting_flow import sw_research


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
    settings = Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                        fulltext_fetch="off")
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
        assert collections == [{"key": "THES2345", "name": "Thesis", "items": None, "parent": None},
                               {"key": COLLECTION, "name": "Thesis / Known set", "items": None, "parent": "THES2345"}]

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
            "notes": [{"title": "SYNTHETIC relay budget", "note": "its PDF is a linked file, which zotero.org does not store",
                       "vars": {}}],
        }
        assert fetched == [storage, storage]
        assert all(r.url.host == "api.zotero.org" and r.url.path.startswith("/users/12345/") for r in seen)
        assert all(r.headers["zotero-api-key"] == "zkey-secret-value" for r in seen)
        assert [r.url.params["start"] for r in seen if r.url.path.endswith("/items")] == ["0", "2", "4", "6"]
        stored = "".join(p.read_text() for p in (tmp_path / "data" / "provider-payloads").iterdir())
        assert "LNKD1234" in stored and "zkey-secret-value" not in stored


def test_reimporting_a_collection_leaves_a_source_removed_from_the_research_removed(tmp_path):
    files = {}
    for key in ("PDFA1234", "LNKD1234", "STND1234"):
        path = tmp_path / f"{key} file.pdf"
        path.write_bytes(make_pdf([f"SYNTHETIC text of {key}"]))
        files[key] = path.as_uri()
    app = app_for(tmp_path, zotero_client(files, []))
    with TestClient(app) as client:
        rid = start(client)
        body = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": COLLECTION}).json()
        article = next(s for s in body["sources"] if s["title"] == "SYNTHETIC diffusion scheduling")
        app.state.store.remove_sources(rid, [article["source_version_id"]], None)

        again = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": COLLECTION}).json()
        assert article["source_version_id"] not in {s["source_version_id"] for s in again["sources"]}
        assert again["zotero_import"]["notes"] == [{"title": "SYNTHETIC diffusion scheduling",
                                                    "note": "Removed from this research earlier; not added back. Restore it to use it here."}]
        assert (again["counts"]["removed"], again["counts"]["removed_found_again"]) == (1, 1)


PDF = make_pdf(["SYNTHETIC library copy of a waiting work."])


def test_waiting_works_are_matched_in_zotero_and_the_file_is_read_without_being_attached(tmp_path, monkeypatch):
    asked = []

    async def find_pdf(client, lib, doi, title):
        asked.append(doi)
        if doi == "10.1/oa.2":
            return zotero.ZoteroItem(None, pdf_key="PDFA1234", pdf_filename="w2.pdf")
        if doi == "10.1/oa.3":
            return zotero.ZoteroItem(None, pdf_problem="the item has no PDF")
        return None

    async def pdf_bytes(client, lib, key, fetch_pdf):
        assert key == "PDFA1234"
        return PDF

    monkeypatch.setattr(zotero, "find_pdf", find_pdf)
    monkeypatch.setattr(zotero, "pdf_bytes", pdf_bytes)
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        settled_runs(client, rid)
        before = client.get(f"/api/researches/{rid}/waiting").json()
        found = client.post(f"/api/researches/{rid}/waiting/zotero", json={"source": "local"})
        file = client.get("/api/zotero/attachments/PDFA1234/file", params={"source": "local"})
        bad_key = client.get("/api/zotero/attachments/..%2Fx/file")
        after = client.get(f"/api/researches/{rid}/waiting").json()
    finally:
        client.__exit__(None, None, None)
    assert found.status_code == 200, found.text
    body = found.json()
    w2 = next(r for r in before["rows"] if r["doi"] == "10.1/oa.2")
    assert body["checked"] == before["count"] == 3 and sorted(asked) == ["10.1/oa.2", "10.1/oa.3", "10.1/oa.4"]
    assert body["found"] == [{"work_id": w2["work_id"], "title": w2["title"], "key": "PDFA1234", "filename": "w2.pdf"}]
    assert [n["note"] for n in body["notes"]] == ["the item has no PDF"]
    assert file.status_code == 200 and file.content == PDF and file.headers["content-type"] == "application/pdf"
    assert bad_key.status_code in (404, 422)
    assert after["count"] == 3  # nothing was attached: the person still confirms the version


REPO = Path(__file__).resolve().parents[2]


def _turkish_keys() -> set[str]:
    source = (REPO / "web" / "src" / "i18n.ts").read_text()
    return set(re.findall(r"^  '((?:[^'\\]|\\.)*)':", source, re.M))


def _note_templates() -> set[str]:
    found = {"PDF input not verified: " + text_retry.INPUT_CHANGED}
    app = ast.parse((REPO / "deixis" / "api" / "app.py").read_text())
    zotero = ast.parse((REPO / "deixis" / "providers" / "zotero.py").read_text())
    for node in ast.walk(app):
        if isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "note" for k in node.keys):
            value = node.values[[k.value if isinstance(k, ast.Constant) else None for k in node.keys].index("note")]
            if isinstance(value, ast.Constant):
                found.add(value.value)
            assert not isinstance(value, ast.JoinedStr), "a note is a template with vars, not an f-string"
    for node in ast.walk(zotero):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "pdf_problem" for t in node.targets):
            found |= {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str) and " " in c.value}
            assert not any(isinstance(c, ast.JoinedStr) for c in ast.walk(node.value))
    return found


def test_every_zotero_note_template_has_a_turkish_entry():
    templates = _note_templates()
    assert "PDF not added: {reason}" in templates and "its PDF attachment has no file ({mode})" in templates
    assert templates - _turkish_keys() == set()

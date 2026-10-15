"""An uploaded PDF identified as its scholarly record (D37). OpenAlex is a scripted transport and every record is
SYNTHETIC; this measures the matching rule and what is stored, not OpenAlex's coverage or how often real files match."""

import json

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.documents import upload_record
from fakes import FakeAdapter
from helpers import make_pdf
from test_api_flow import create, fake_fetch, session, sw_settings

TITLE = "Synthetic Routing Design over Quantum Packet Networks"
SHORT = "Routing Design over Quantum Packet Networks"
DOI = "10.1/synthetic.900"
FIRST_PAGE = f"{TITLE}\nAda Lovelace, Alan Turing\nAbstract SYNTHETIC routing study."


def work(wid="W900", title=TITLE, doi=DOI, year=2022, authors=("Ada Lovelace", "Alan Turing")):
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}" if doi else None, "display_name": title,
            "publication_year": year, "type": "article",
            "authorships": [{"author": {"display_name": name}} for name in authors],
            "primary_location": {"source": {"display_name": "SYNTHETIC Journal"}},
            "abstract_inverted_index": {"SYNTHETIC": [0], "abstract": [1], "text.": [2]}}


class OpenAlex:
    def __init__(self, by_doi=(), semantic=()):
        self.by_doi, self.semantic, self.requests = list(by_doi), list(semantic), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        results = self.by_doi if "filter" in params else self.semantic
        return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})


def app_with(tmp_path, openalex):
    return create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(openalex)), fetcher=fake_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def upload(client, rid, pages, name="my_file_name.pdf"):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf(pages), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def test_a_longer_found_title_wins_over_one_it_contains_and_equal_titles_decide_nothing():
    region = f"{TITLE}\nAda Lovelace"
    assert upload_record.pick(region, [work("W1", SHORT), work("W2", TITLE)])["id"].endswith("W2")
    assert upload_record.pick(region, [work("W1", TITLE), work("W2", TITLE)]) is None
    assert upload_record.pick(region, [work("W1", "Unrelated Paper About Something Else")]) is None


def test_an_upload_naming_its_doi_takes_the_record_title_authors_and_abstract(tmp_path):
    openalex = OpenAlex(by_doi=[work(), work("W901", "Another Paper That The Title Page Cites", "10.1/other")])
    with TestClient(app_with(tmp_path, openalex)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid = upload(client, rid, [f"{FIRST_PAGE}\nhttps://doi.org/{DOI}"])
        store = client.app.state.store
        source = store.source(svid)
        assert (source["title"], source["authors"], source["year"], source["doi"]) == (
            TITLE, ["Ada Lovelace", "Alan Turing"], 2022, DOI)
        match = json.loads(source["record_match_json"])
        assert match | {"matched_at": None} == {"provider": "openalex", "work_id": "W900", "basis": "doi_title",
                                                 "filename_title": "my file name", "matched_at": None}
        abstract = store.conn.execute("SELECT text FROM passages WHERE source_version_id = ? AND kind = 'abstract'",
                                      (svid,)).fetchone()
        assert abstract["text"] == "SYNTHETIC abstract text."
        # No identifier mapping: a search that later finds W900 keeps its own source version.
        assert store.find_source_by_identifier("openalex", "W900") is None
        assert [r for r in openalex.requests if "search.semantic" in r] == []


def test_without_a_doi_one_meaning_search_decides_by_title(tmp_path):
    openalex = OpenAlex(semantic=[work("W1", SHORT, "10.1/short"), work()])
    with TestClient(app_with(tmp_path, openalex)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid = upload(client, rid, [FIRST_PAGE])
        source = client.app.state.store.source(svid)
        assert source["title"] == TITLE and json.loads(source["record_match_json"])["basis"] == "title"
        assert len(openalex.requests) == 1 and "search.semantic" in openalex.requests[0]


def test_no_match_keeps_the_file_name_and_a_later_lookup_fills_it(tmp_path):
    openalex = OpenAlex(semantic=[work("W1", "Unrelated Paper About Something Else", None)])
    with TestClient(app_with(tmp_path, openalex)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid = upload(client, rid, [FIRST_PAGE])
        store = client.app.state.store
        assert store.source(svid)["title"] == "my file name" and store.source(svid)["record_match_json"] is None
        openalex.semantic = [work()]
        response = client.post(f"/api/researches/{rid}/sources/{svid}/record-lookup")
        assert response.status_code == 200 and response.json()["found"] is True
        assert store.source(svid)["title"] == TITLE
        # Once matched, a second lookup sends nothing and changes nothing.
        sent = len(openalex.requests)
        assert client.post(f"/api/researches/{rid}/sources/{svid}/record-lookup").json()["found"] is False
        assert len(openalex.requests) == sent


def test_a_failing_openalex_never_fails_the_upload(tmp_path):
    def broken(request):
        raise httpx.ConnectError("SYNTHETIC offline", request=request)
    with TestClient(app_with(tmp_path, broken)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid = upload(client, rid, [FIRST_PAGE])
        assert client.app.state.store.source(svid)["title"] == "my file name"

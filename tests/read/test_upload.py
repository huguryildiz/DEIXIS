"""A person's PDFs: an upload takes its stored record, a torn file is replaced, a wrong file comes back, attached PDFs share the answer's passages, and a skipped work can still get a file. SYNTHETIC records and PDFs."""

import json
import httpx
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.documents import upload_record
from fakes import FakeAdapter
from helpers import make_pdf
from test_api_flow import create, fake_fetch, session, sw_settings
from test_api_flow import app_for, create, session
import pytest
from deixis.workflow.store import NotFound
from test_api_flow import app_for, create, session
from test_table_extraction import cell, execute, fill, library
from types import SimpleNamespace
from deixis.providers import crossref
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE
from test_criterion_passage_flow import ABSTRACT, QUESTION, TOPIC_PAGE, page_source, retrieve
from deixis.workflow import waiting as waiting_rules
from test_abstract_flow import records_of
from test_waiting_flow import confirm, match, named, sw_research


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


def test_uploading_a_pdf_replaces_a_torn_file_under_its_hash_name(tmp_path):
    import hashlib

    from deixis.storage.backup import create_backup
    from helpers import make_pdf
    from test_api_flow import sw_settings

    data = make_pdf(["SYNTHETIC molecule text one", "SYNTHETIC molecule text two"])
    sha = hashlib.sha256(data).hexdigest()
    settings = sw_settings(tmp_path)
    settings.papers_dir.mkdir(parents=True, exist_ok=True)
    torn = settings.papers_dir / f"{sha}.pdf"
    torn.write_bytes(data[: len(data) // 2])  # what the pre-D162 download write could leave behind
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", data, "application/pdf")})
        assert response.status_code == 201, response.text
        asset = response.json()["sources"][0]["access"]["assets"][0]
        assert asset["extraction_status"] == "succeeded"
    assert torn.read_bytes() == data  # the file under the name now is the file the row's hash names
    assert not list(settings.papers_dir.glob("*.partial"))
    folder = create_backup(settings, tmp_path / "backup")  # refuses a file that does not match its recorded hash
    assert (folder / "manifest.json").exists()


def pdf_asset(lib):
    (asset,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    return asset


def in_use(store, svid):
    return store.conn.execute("SELECT COUNT(*) FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()[0]


def test_a_wrong_file_comes_back_with_its_passages_and_its_evidence_is_current_again(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    store, asset = lib.store, pdf_asset(lib)
    passages = store.passages_for(lib.published)
    revision = store.selection_revision(lib.rid)

    store.remove_asset(lib.rid, lib.published, asset)
    assert store.selection_revision(lib.rid) == revision + 1 and "pdf_removed" in cell(lib, lib.published)["flags"]
    assert all(p["kind"] == "abstract" for p in store.passages_for(lib.published))

    store.restore_asset(lib.rid, lib.published, asset)
    assert store.selection_revision(lib.rid) == revision + 2  # the source is included: the answer reads its PDF again
    assert store.passages_for(lib.published) == passages
    view = cell(lib, lib.published)
    assert {e["evidence_status"] for e in view["current"]["evidence"]} == {"current"} and view["flags"] == []
    assert (store.asset(asset)["removed_at"], store.asset(asset)["removal_reason"]) == (None, None)
    assert "asset_restored" in [e["type"] for e in store.events_after(lib.rid, 0)]
    with pytest.raises(NotFound):  # in use, nothing to restore
        store.restore_asset(lib.rid, lib.published, asset)


def sparse_record() -> ProviderRecord:
    return ProviderRecord(
        provider_record_id="seed", title="Exact title", authors=[], year=None, venue=None,
        publication_type=None, doi="10.1/test", landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label="publishedVersion", abstract=None, abstract_origin=None, identifiers={}, raw={},
    )


def test_crossref_details_enrich_a_sparse_exact_doi_record(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid, _ = store.upsert_provider_source("known_list", sparse_record(), None)
    record = crossref.record_from_item({
        "DOI": "10.1/test", "title": ["Exact title"],
        "author": [{"given": "Ada", "family": "Lovelace"}, {"given": "Alan", "family": "Turing"}],
        "issued": {"date-parts": [[2024]]}, "container-title": ["Journal of Exact Records"],
        "type": "journal-article", "URL": "https://doi.org/10.1/test", "volume": "12", "issue": "3", "page": "41-59",
    })

    store.enrich_source("crossref", svid, record)

    source = store.source(svid)
    assert source["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert (source["year"], source["venue"], source["volume"], source["issue"], source["pages"]) == (
        2024, "Journal of Exact Records", "12", "3", "41-59",
    )
    assert store.find_source_by_identifier("crossref", "10.1/test") == svid


def test_removed_asset_is_excluded_from_future_retrieval_and_stales_answers(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("Question?", "academic", "quick", ["crossref"], "fake", "m", "en")
    svid, _ = store.upsert_provider_source("known_list", sparse_record(), None)
    store.add_to_corpus(rid, svid, "search", selection_state="included", selection_origin="user")
    extraction = SimpleNamespace(
        status="succeeded", error=None, page_count=1,
        pages=[SimpleNamespace(text="Wrong document text", physical_page=1, printed_label=None)],
    )
    asset_id = store.add_asset_with_pages(
        svid, "abc", 100, "abc.pdf", "user_upload", None, "wrong.pdf", extraction, "test",
        lambda text: [(0, len(text), text)],
    )
    before = store.selection_revision(rid)

    store.remove_asset(rid, svid, asset_id)

    assert not store.has_asset(svid)
    assert store.passages_for(svid) == []
    assert store.asset(asset_id)["removed_at"] is not None
    assert store.selection_revision(rid) == before + 1


REFERENCE_PAGE = ("SYNTHETIC fatigue. REFERENCES "
                  "[1] A. Smith, “Exercise after chemotherapy,” J. Onc., 2020. "
                  "[2] Jones, B., “Fatigue in cancer,” 2019. "
                  "[3] C. Lee and D. Park, “Supervised exercise,” 2021.")


def attached_library(tmp_path, scope="attached"):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research(QUESTION, scope, "standard", [], "fake", "fake-model", None)
    return store, rid


def per_source(chosen, svid):
    return len([p for p in chosen if p["source_version_id"] == svid])


def test_two_attached_pdfs_share_the_limit_instead_of_six_passages_each(tmp_path):
    store, rid = attached_library(tmp_path)
    svids = [page_source(store, rid, f"pdf{i}", [f"{TOPIC_PAGE} page {n}." for n in range(20)], ABSTRACT)
             for i in range(2)]
    chosen = retrieve(store, rid, svids, 48)
    assert all(per_source(chosen, svid) > MAX_PASSAGES_PER_SOURCE for svid in svids)
    assert all(per_source(chosen, svid) <= 48 // 2 for svid in svids)
    assert len(chosen) <= 48


def test_a_reference_list_passage_comes_after_every_topic_page(tmp_path):
    """A reference page matches the question words, yet a page that states a finding is given before it."""
    store, rid = attached_library(tmp_path)
    pages = [REFERENCE_PAGE] + [f"{TOPIC_PAGE} page {n}." for n in range(8)]
    svids = [page_source(store, rid, f"pdf{i}", pages, ABSTRACT) for i in range(2)]
    roomy = [p["text"] for p in retrieve(store, rid, svids, 48)]
    assert REFERENCE_PAGE in roomy  # room is left, so it is not dropped
    tight = [p["text"] for p in retrieve(store, rid, svids, 2 * (1 + 8))]
    assert REFERENCE_PAGE not in tight and len(tight) == 2 * (1 + 8)


def waiting(client, rid):
    return client.get(f"/api/researches/{rid}/waiting").json()


def skip(client, rid, work_id):
    return client.post(f"/api/researches/{rid}/waiting/skips", json={"work_id": work_id})


def work_of(view, head):
    return next(row["work_id"] for row in view["rows"] + view["skipped"] if row["head"] == head)


def test_a_file_for_a_skipped_work_clears_the_skip_and_normal_reading_applies(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        w2 = work_of(waiting(client, rid), records["W2"])
        assert skip(client, rid, w2).status_code == 201
        data = named("10.1/oa.2")
        found = match(client, rid, ("doi.pdf", data))["matches"][0]
        response = confirm(client, rid, data, found, records["W2"])
        view = waiting(client, rid)
        in_force = waiting_rules.skipped(store, rid)
        counts = client.get(f"/api/researches/{rid}").json()["counts"]
    finally:
        client.__exit__(None, None, None)
    # The skipped work is still one a file may be added for, and is proposed by its DOI.
    assert found["work"]["work_id"] == w2
    assert response.status_code == 201, response.text
    assert in_force == {} and view["skipped"] == [] and counts["flow"]["buckets"]["abstract_by_choice"] == 0
    assert w2 not in [row["work_id"] for row in view["rows"]]  # its PDF text is in hand now

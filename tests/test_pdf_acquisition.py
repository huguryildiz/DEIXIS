import asyncio

import httpx

from deixis.documents import acquisition
from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store
from helpers import make_pdf


def run(coro):
    return asyncio.run(coro)


def test_openalex_collects_every_pdf_location_and_marks_versions():
    def handler(request):
        return httpx.Response(200, json={
            "doi": "https://doi.org/10.1/test", "display_name": "Test",
            "locations": [
                {"pdf_url": "https://repo.example/vor.pdf", "landing_page_url": "https://repo.example/item",
                 "version": "publishedVersion", "license": "cc-by"},
                {"pdf_url": "https://preprint.example/a.pdf", "version": "submittedVersion"},
                {"landing_page_url": "https://closed.example/item", "version": "publishedVersion"},
            ],
        })

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.openalex_lookup(client, "10.1/test", "publishedVersion")

    result = run(check())
    assert result.status == "completed"
    assert [(c.url, c.identity_status, c.version_status) for c in result.candidates] == [
        ("https://repo.example/vor.pdf", "doi_verified", "match"),
        ("https://preprint.example/a.pdf", "doi_verified", "different"),
    ]


def test_unpaywall_collects_every_pdf_location_and_marks_versions():
    def handler(request):
        assert request.url.params["email"] == "researcher@example.org"
        return httpx.Response(200, json={
            "doi": "10.1/test",
            "best_oa_location": {
                "url_for_pdf": "https://repo.example/vor.pdf",
                "url": "https://repo.example/item",
                "version": "publishedVersion",
                "license": "cc-by",
            },
            "oa_locations": [
                {
                    "url_for_pdf": "https://repo.example/vor.pdf",
                    "url": "https://repo.example/item",
                    "version": "publishedVersion",
                    "license": "cc-by",
                },
                {"url_for_pdf": "https://preprint.example/a.pdf", "version": "submittedVersion"},
                {"url": "https://closed.example/item", "version": "publishedVersion"},
            ],
        })

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.unpaywall_lookup(
                client, "10.1/test", "publishedVersion", "researcher@example.org"
            )

    result = run(check())
    assert result.status == "completed"
    assert [(c.url, c.identity_status, c.version_status) for c in result.candidates] == [
        ("https://repo.example/vor.pdf", "doi_verified", "match"),
        ("https://preprint.example/a.pdf", "doi_verified", "different"),
    ]


def test_unpaywall_requires_contact_email_without_calling_network():
    def handler(request):
        raise AssertionError("Unpaywall must not be called without a contact email")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.unpaywall_lookup(client, "10.1/test", "publishedVersion", None)

    result = run(check())
    assert result.status == "auth_required"
    assert result.error_code == "missing_contact_email"


def test_core_lists_hosted_pdfs_of_the_same_doi_as_version_uncertain():
    def handler(request):
        assert request.url.params["q"] == 'doi:"10.1/test"' and request.headers["authorization"] == "Bearer key"
        return httpx.Response(200, json={"totalHits": 2, "results": [
            {"id": 1, "doi": "10.1/TEST", "downloadUrl": "https://core.ac.uk/download/11.pdf",
             "links": [{"type": "download", "url": "https://core.ac.uk/download/11.pdf"},
                       {"type": "display", "url": "https://core.ac.uk/works/1"}]},
            {"id": 2, "doi": "10.1/test.suppl", "downloadUrl": "https://core.ac.uk/download/22.pdf"},
        ]})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.core_lookup(client, "10.1/test", "key")

    result = run(check())
    assert result.status == "completed"
    assert [(c.url, c.landing_url, c.identity_status, c.version_status) for c in result.candidates] == [
        ("https://core.ac.uk/download/11.pdf", "https://core.ac.uk/works/1", "doi_verified", "uncertain"),
    ]


def test_core_requires_key_without_calling_network():
    def handler(request):
        raise AssertionError("CORE must not be called without a key")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.core_lookup(client, "10.1/test", None)

    result = run(check())
    assert (result.status, result.error_code) == ("auth_required", "missing_core_key")


def test_crossref_collects_pdf_links_and_maps_content_version():
    def handler(request):
        return httpx.Response(200, json={"message": {
            "DOI": "10.1/test", "URL": "https://publisher.example/article",
            "link": [
                {"URL": "https://publisher.example/vor", "content-type": "application/pdf", "content-version": "vor"},
                {"URL": "https://publisher.example/data.xml", "content-type": "application/xml"},
                {"URL": "https://repo.example/manuscript.pdf", "content-version": "am"},
            ],
        }})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.crossref_lookup(client, "10.1/test", "publishedVersion")

    result = run(check())
    assert [(c.url, c.version_label, c.version_status) for c in result.candidates] == [
        ("https://publisher.example/vor", "publishedVersion", "match"),
        ("https://repo.example/manuscript.pdf", "acceptedVersion", "different"),
    ]


def test_web_search_candidates_remain_version_uncertain():
    def handler(request):
        return httpx.Response(200, json={"organic_results": [{
            "title": "Exact synthetic title", "link": "https://repository.example/item",
            "resources": [{"file_format": "PDF", "link": "https://repository.example/copy.pdf"}],
        }]})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.web_lookup(client, "10.1/test", "Exact synthetic title", "key")

    result = run(check())
    assert len(result.candidates) == 1
    assert result.candidates[0].identity_status == "title_verified"
    assert result.candidates[0].version_status == "uncertain"


def test_acquisition_records_403_then_downloads_second_verified_location(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord(
        provider_record_id="W1", title="Exact synthetic title", authors=[], year=2020, venue="J", publication_type="article",
        doi="10.1/test", landing_url="https://publisher.example/item", oa_pdf_url=None, oa_pdf_version=None,
        version_label="publishedVersion", abstract=None, abstract_origin=None, identifiers={}, raw={},
    )
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")

    def handler(request):
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(200, json={"doi": "10.1/test", "oa_locations": [], "best_oa_location": None})
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/test", "display_name": record.title,
                "locations": [
                    {"pdf_url": "https://blocked.example/a.pdf", "version": "publishedVersion"},
                    {"pdf_url": "https://open.example/a.pdf", "version": "publishedVersion"},
                ]})
        return httpx.Response(200, json={"message": {"DOI": "10.1/test", "link": []}})

    attempts = []
    async def fetcher(url):
        attempts.append(url)
        if "blocked" in url:
            return FetchResult("http_error", final_url=url, http_status=403)
        return FetchResult("ok", data=make_pdf(["SYNTHETIC full text"]), final_url=url, http_status=200)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers", None, None, fetcher)

    result = run(check())
    assert result["pdf_found"] is True and len(attempts) == 2
    candidates = store.pdf_candidates(svid)
    assert [(c["access_status"], c["http_status"]) for c in candidates] == [("http_error", 403), ("downloaded", 200)]
    assert store.has_asset(svid)
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == ["unpaywall", "openalex", "crossref", "core"]
    connection.close()


def test_acquisition_uses_web_when_metadata_sources_yield_no_verified_pdf(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord("W1", "Exact synthetic title", [], 2020, "J", "article", "10.1/test", None,
                            None, None, "publishedVersion", None, None, {}, {})
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")

    def handler(request):
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(200, json={"doi": "10.1/test", "oa_locations": [], "best_oa_location": None})
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/test", "display_name": record.title,
                "locations": [{"pdf_url": "https://repo.example/manuscript.pdf", "version": "acceptedVersion"}]})
        if "api.crossref.org" in request.url.host:
            return httpx.Response(200, json={"message": {"DOI": "10.1/test", "link": []}})
        if "api.core.ac.uk" in request.url.host:
            return httpx.Response(200, json={"results": [{"doi": "10.1/test", "downloadUrl": "https://core.ac.uk/download/1.pdf"}]})
        return httpx.Response(200, json={"organic_results": [{"title": record.title,
            "link": "https://repo.example/item", "resources": [{"file_format": "PDF", "link": "https://repo.example/a.pdf"}]}]})

    async def reject_fetch(url):
        raise AssertionError("version-uncertain web candidate must not be downloaded")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers", None, "key", reject_fetch,
                                                        core_key="key")

    result = run(check())
    assert result["pdf_found"] is False
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == ["unpaywall", "openalex", "crossref", "core", "web_search"]
    assert [(c["provider"], c["version_status"]) for c in store.pdf_candidates(svid)] == [
        ("openalex", "different"), ("core", "uncertain"), ("web_search", "uncertain")]
    connection.close()

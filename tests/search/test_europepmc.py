"""Europe PMC's open-access full text as the last full-text source (SW21, D106).

The lookup is asked through a mocked `httpx` transport and the XML comes from a fake `xml_fetcher`; no test touches the
network. The JATS documents are SYNTHETIC and say nothing about any real article. Passing shows the lookup rules, the
order, the bounded drawing and the rendition label; it does not show how often Europe PMC holds a work or how well
its XML draws.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile

import httpx
import pytest

from deixis.documents import acquisition, jats, pdf
from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store

DOI = "10.5555/synthetic.epmc"


def run(coro):
    return asyncio.run(coro)


def jats_doc(title="SYNTHETIC release windows in relay chains", abstract="SYNTHETIC first abstract sentence. A second one.",
             paragraphs=("SYNTHETIC body paragraph about a release window.",), extra=""):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (f'<?xml version="1.0" encoding="UTF-8"?><article xmlns:mml="http://www.w3.org/1998/Math/MathML">'
            f"<front><article-meta><title-group><article-title>{title}</article-title></title-group>"
            f"<abstract><p>{abstract}</p></abstract></article-meta></front>"
            f"<body><sec><title>Methods</title>{body}{extra}</sec></body>"
            f"<back><ref-list><ref>SYNTHETIC REFERENCE ENTRY</ref></ref-list></back></article>").encode()


def result(pmcid="PMC1000001", doi=DOI, open_access="Y", in_epmc="Y", author_manuscript="N", license="cc by"):
    return {"id": (pmcid or "PMC0")[3:], "source": "MED", "pmcid": pmcid, "doi": doi, "isOpenAccess": open_access,
            "inEPMC": in_epmc, "authMan": author_manuscript, "license": license}


def search_response(*results):
    return httpx.Response(200, json={"hitCount": len(results), "resultList": {"result": list(results)}})


# ---- the lookup ----------------------------------------------------------------------------------------------------

def lookup(handler, source_version="publishedVersion"):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.europepmc_lookup(client, DOI, source_version)
    return run(check())


# ---- the order and the attachment ----------------------------------------------------------------------------------

def library(tmp_path, version="publishedVersion", doi=DOI):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("SYNTHETIC question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord("W1", "SYNTHETIC release windows in relay chains", [], 2020, "J", "article", doi, None,
                            None, None, version, None, None, {}, {})
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")
    return store, rid, svid


def handler_for(epmc_results=(), unpaywall_pdf=None, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request.url.host)
        host = request.url.host
        if host == "api.unpaywall.org":
            locations = [{"url_for_pdf": unpaywall_pdf, "version": "publishedVersion"}] if unpaywall_pdf else []
            return httpx.Response(200, json={"doi": DOI, "oa_locations": locations, "best_oa_location": None})
        if host == "api.openalex.org":
            return httpx.Response(200, json={"doi": f"https://doi.org/{DOI}", "locations": []})
        if host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"DOI": DOI, "link": []}})
        if host == "www.ebi.ac.uk":
            return search_response(*epmc_results)
        raise AssertionError(f"unexpected request to {host}")
    return handler


def xml_fetcher_of(documents, calls=None):
    async def fetch_xml(url):
        if calls is not None:
            calls.append(url)
        found = documents.get(url)
        if isinstance(found, FetchResult):
            return found
        if found is None:
            return FetchResult("http_error", final_url=url, http_status=500)
        return FetchResult("ok", data=found, final_url=url, media_type="application/xml", http_status=200)
    return fetch_xml


def url_of(pmcid):
    return f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def acquire(store, rid, svid, tmp_path, handler, fetch_xml, pdf_fetcher=None, other_versions=False):
    async def no_pdf(url):
        return FetchResult("http_error", final_url=url, http_status=404)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(
                store, rid, svid, client, tmp_path / "papers", "researcher@example.org", None, pdf_fetcher or no_pdf,
                web_search=False, other_versions=other_versions, xml_fetcher=fetch_xml)
    return run(check())


def test_europe_pmc_is_asked_after_the_four_lookups_and_its_text_is_attached_as_a_rendition(tmp_path):
    store, rid, svid = library(tmp_path)
    calls = []
    found = acquire(store, rid, svid, tmp_path, handler_for([result()], calls=calls),
                    xml_fetcher_of({url_of("PMC1000001"): jats_doc()}))
    assert calls.index("www.ebi.ac.uk") > calls.index("api.crossref.org")  # after the four (CORE has no key here)
    assert found["pdf_found"] is True
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == [
        "unpaywall", "openalex", "crossref", "core", "europepmc"]
    asset = store.asset(found["asset_id"])
    assert asset["origin"] == "download" and asset["retrieved_from"] == url_of("PMC1000001")
    assert asset["original_filename"] == "PMC1000001.europepmc.pdf"
    assert store.asset_rendition(asset["id"]) is True
    pages = [p for p in store.passages_for(svid) if p["kind"] == "pdf_page"]
    assert pages and all(p["physical_page"] >= 1 and p["asset_id"] == asset["id"] for p in pages)
    text = " ".join(" ".join(p["text"] for p in pages).split())
    assert "SYNTHETIC release windows in relay chains" in text and "SYNTHETIC first abstract sentence." in text
    assert "SYNTHETIC REFERENCE ENTRY" not in text  # the references are left out
    assert all(p["text_source"] == "text_layer" for p in pages)  # no OCR and no Marker: the text layer is whole
    (candidate,) = store.pdf_candidates(svid)
    assert (candidate["provider"], candidate["access_status"]) == ("europepmc", "downloaded")


def two_candidates():
    return [result("PMC1000001"), result("PMC1000002")]


# ---- the drawing's bounds (plan decision 3a.5) --------------------------------------------------------------------

@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def test_an_input_over_five_mib_is_refused_before_a_child_starts(tmp_path, monkeypatch, temp_root):
    def no_child(*args, **kwargs):
        raise AssertionError("no child process may start for an input over the limit")

    monkeypatch.setattr(subprocess, "run", no_child)
    too_large = jats_doc() + b" " * (jats.MAX_XML_BYTES + 1)
    assert jats.render_pdf(too_large).status == "jats_too_large"
    assert jats.MAX_XML_BYTES == 5 * 1024 * 1024

    store, rid, svid = library(tmp_path)
    documents = {url_of("PMC1000001"): too_large, url_of("PMC1000002"): None}
    found = acquire(store, rid, svid, tmp_path, handler_for(two_candidates()), xml_fetcher_of(documents))
    rows = {c["candidate_url"]: c for c in store.pdf_candidates(svid)}
    assert (rows[url_of("PMC1000001")]["access_status"], rows[url_of("PMC1000001")]["error_code"]) == (
        "failed", "jats_too_large")
    assert rows[url_of("PMC1000002")]["access_status"] == "http_error"  # the next one was asked for
    assert found["asset_id"] is None and list(temp_root.iterdir()) == []


def test_an_entity_declared_in_another_encoding_is_refused_by_the_child():
    declared = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "y">]><article>&x;</article>'
    assert jats.render_pdf(declared.encode("utf-16")).status == "jats_render_failed"


# ---- the record the answer and every view read ---------------------------------------------------------------------

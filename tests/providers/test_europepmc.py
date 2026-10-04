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
import pymupdf
import pytest

from deixis.documents import acquisition, jats, pdf
from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store
from helpers import make_pdf

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


def test_an_open_access_published_copy_with_the_record_s_doi_is_a_fulltext_xml_candidate():
    seen = []

    def handler(request):
        seen.append(request)
        return search_response(result())

    found = lookup(handler)
    assert found.status == "completed"
    (candidate,) = found.candidates
    assert candidate.provider == "europepmc"
    assert candidate.url == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1000001/fullTextXML"
    assert candidate.landing_url == "https://europepmc.org/article/PMC/PMC1000001"
    assert (candidate.version_label, candidate.license) == ("publishedVersion", "cc by")
    assert (candidate.identity_status, candidate.version_status) == ("doi_verified", "match")
    (request,) = seen
    assert request.url.host == "www.ebi.ac.uk" and request.url.path == "/europepmc/webservices/rest/search"
    assert request.url.params["query"] == f'DOI:"{DOI}"'
    assert request.url.params["resultType"] == "core" and request.url.params["format"] == "json"


@pytest.mark.parametrize("item", [
    result(doi="10.5555/another"),            # another work that shares part of the DOI
    result(open_access="N"),                  # not in the open-access subset
    result(author_manuscript="Y"),            # an author manuscript: fullTextXML gives nothing for it
    result(in_epmc="N"),
    result(pmcid=None),
    result(pmcid="not-a-pmcid"),
])
def test_a_result_outside_the_candidate_rule_is_no_candidate(item):
    found = lookup(lambda request: search_response(item))
    assert (found.status, found.candidates) == ("zero_results", [])


@pytest.mark.parametrize(("source_version", "expected"), [
    ("publishedVersion", "match"), ("acceptedVersion", "different"), (None, "uncertain")])
def test_the_version_status_is_the_other_lookups_rule(source_version, expected):
    (candidate,) = lookup(lambda request: search_response(result()), source_version).candidates
    assert candidate.version_status == expected


@pytest.mark.parametrize(("response", "status", "code"), [
    (httpx.Response(404), "zero_results", None),
    (httpx.Response(429), "rate_limited", "rate_limited"),
    (httpx.Response(403), "auth_required", "auth_required"),
    (httpx.Response(401), "auth_required", "auth_required"),
    (httpx.Response(500), "failed", "http_500"),
    (httpx.Response(200, content=b"not json"), "parse_error", "JSONDecodeError"),
    (httpx.Response(200, json={"resultList": {}}), "parse_error", "KeyError"),
])
def test_the_lookup_maps_every_status_the_way_core_s_does(response, status, code):
    found = lookup(lambda request: response)
    assert (found.status, found.error_code, found.candidates) == (status, code, [])


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


def test_a_work_with_a_pdf_never_asks_europe_pmc(tmp_path):
    store, rid, svid = library(tmp_path)
    calls, xml_calls = [], []

    async def pdf(url):
        return FetchResult("ok", data=make_pdf(["SYNTHETIC publisher page."]), final_url=url,
                           media_type="application/pdf", http_status=200)

    found = acquire(store, rid, svid, tmp_path, handler_for([result()], "https://pub.example/a.pdf", calls),
                    xml_fetcher_of({}, xml_calls), pdf)
    assert found["pdf_found"] is True
    assert "www.ebi.ac.uk" not in calls and xml_calls == []
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == ["unpaywall", "openalex", "crossref", "core"]


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


def test_a_person_s_upload_named_like_a_rendition_is_not_one(tmp_path):
    store, rid, svid = library(tmp_path)
    data = make_pdf(["SYNTHETIC uploaded page."])
    run(acquisition._attach_pdf(store, svid, data, tmp_path / "papers", "user_upload",
                                url_of("PMC1000001"), filename="PMC1000001.europepmc.pdf"))
    (asset,) = [a for a in store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,))]
    assert store.asset_rendition(asset[0]) is False
    assert jats.is_rendition("user_upload", url_of("PMC1000001"), "PMC1000001.europepmc.pdf") is False
    assert jats.is_rendition("download", url_of("PMC1000001"), "PMC1000001.europepmc.pdf") is True
    assert jats.is_rendition("download", "https://pub.example/a.pdf", "PMC1000001.europepmc.pdf") is False


def two_candidates():
    return [result("PMC1000001"), result("PMC1000002")]


@pytest.mark.parametrize(("first", "status", "code"), [
    (FetchResult("wrong_type", final_url=url_of("PMC1000001"), media_type="text/html", http_status=200), "wrong_type", None),
    (jats_doc(extra='<!DOCTYPE x [<!ENTITY a "b">]>'), "failed", "jats_entity_refused"),
    (b"<article><body><p>SYNTHETIC unclosed</body></article>", "failed", "jats_render_failed"),
])
def test_a_refused_or_failed_first_copy_is_recorded_and_the_next_is_tried(tmp_path, first, status, code):
    store, rid, svid = library(tmp_path)
    documents = {url_of("PMC1000001"): first, url_of("PMC1000002"): jats_doc()}
    found = acquire(store, rid, svid, tmp_path, handler_for(two_candidates()), xml_fetcher_of(documents))
    rows = {c["candidate_url"]: c for c in store.pdf_candidates(svid)}
    assert (rows[url_of("PMC1000001")]["access_status"], rows[url_of("PMC1000001")]["error_code"]) == (status, code)
    assert rows[url_of("PMC1000002")]["access_status"] == "downloaded"
    assert store.asset(found["asset_id"])["retrieved_from"] == url_of("PMC1000002")


def test_a_refused_only_copy_leaves_no_asset_and_raises_nothing(tmp_path):
    store, rid, svid = library(tmp_path)
    found = acquire(store, rid, svid, tmp_path, handler_for([result()]),
                    xml_fetcher_of({url_of("PMC1000001"): jats_doc(extra='<!DOCTYPE x [<!ENTITY a "b">]>')}))
    assert found["asset_id"] is None and found["pdf_found"] is False and not store.has_asset(svid)
    (row,) = store.pdf_candidates(svid)
    assert (row["access_status"], row["error_code"]) == ("failed", "jats_entity_refused")


def test_a_different_version_is_attached_only_through_other_versions_on_its_own_row(tmp_path):
    store, rid, svid = library(tmp_path, version="acceptedVersion")
    documents = {url_of("PMC1000001"): jats_doc()}
    held_back = acquire(store, rid, svid, tmp_path, handler_for([result()]), xml_fetcher_of(documents))
    assert held_back["pdf_found"] is False
    (row,) = store.pdf_candidates(svid)
    assert (row["version_status"], row["access_status"]) == ("different", "not_attempted")

    found = acquire(store, rid, svid, tmp_path, handler_for([result()]), xml_fetcher_of(documents), other_versions=True)
    assert found["pdf_found"] is True and found["lookup_version_id"] != svid
    assert not store.has_asset(svid)  # never onto the record's own row (D4)
    other = store.source(found["lookup_version_id"])
    assert other["version_label"] == "publishedVersion" and store.has_asset(other["id"])
    asset = store.asset(found["asset_id"])
    assert asset["original_filename"] == "PMC1000001.europepmc.pdf" and store.asset_rendition(asset["id"])


def test_an_uncertain_copy_is_never_attached_by_code_nor_confirmable(tmp_path):
    store, rid, svid = library(tmp_path, version=None)
    found = acquire(store, rid, svid, tmp_path, handler_for([result()]), xml_fetcher_of({url_of("PMC1000001"): jats_doc()}),
                    other_versions=True)
    assert found["pdf_found"] is False
    (row,) = store.pdf_candidates(svid)
    assert (row["version_status"], row["access_status"]) == ("uncertain", "not_attempted")


# ---- the drawing's bounds (plan decision 3a.5) --------------------------------------------------------------------

@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def long_body(paragraphs=400):
    return jats_doc(paragraphs=[f"SYNTHETIC paragraph {n} about release windows along a relay chain." for n in range(paragraphs)])


def expanding_document():
    """About 4.8 MiB of tiny paragraphs: well under the input limit, and far past 100 MiB once parsed and laid out."""
    return jats_doc(paragraphs=["SYNTHETIC w"] * 280_000)


@pytest.mark.parametrize(("limits", "first", "code"), [
    ({"timeout": 0.001}, jats_doc(), "jats_render_timeout"),
    ({"max_memory": 100 * 1024 * 1024}, expanding_document(), "jats_render_memory"),
    ({"max_pages": 2}, long_body(), "jats_render_pages"),
    ({"max_output": 2_000}, jats_doc(), "jats_render_output_too_large"),
    ({}, b"<article><body><p>SYNTHETIC unclosed</body></article>", "jats_render_failed"),
])
def test_each_bound_fails_the_candidate_with_its_own_code_and_the_next_is_tried(tmp_path, monkeypatch, temp_root,
                                                                                   limits, first, code):
    store, rid, svid = library(tmp_path)
    original = jats.render_pdf
    calls = []

    def render(xml, **kwargs):
        calls.append(len(xml))
        # The limits apply to the first copy only; the second draws under the defaults.
        return original(xml, **(limits if len(calls) == 1 else {}))

    monkeypatch.setattr(jats, "render_pdf", render)
    documents = {url_of("PMC1000001"): first, url_of("PMC1000002"): jats_doc()}
    found = acquire(store, rid, svid, tmp_path, handler_for(two_candidates()), xml_fetcher_of(documents))
    rows = {c["candidate_url"]: c for c in store.pdf_candidates(svid)}
    assert (rows[url_of("PMC1000001")]["access_status"], rows[url_of("PMC1000001")]["error_code"]) == ("failed", code)
    assert rows[url_of("PMC1000002")]["access_status"] == "downloaded"
    assert store.asset(found["asset_id"])["retrieved_from"] == url_of("PMC1000002")
    assert list(temp_root.iterdir()) == []  # no temporary file is left behind


def test_the_memory_bound_stops_the_child_within_thirty_seconds(temp_root):
    import time

    started = time.monotonic()
    rendition = jats.render_pdf(expanding_document(), max_memory=100 * 1024 * 1024)
    assert rendition.status == "jats_render_memory" and rendition.data == b""
    assert time.monotonic() - started < 30
    assert list(temp_root.iterdir()) == []


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


def test_the_default_bounds_are_the_plan_s():
    assert (jats.MAX_XML_BYTES, jats.RENDER_TIMEOUT_SECONDS, jats.MAX_MEMORY_BYTES, jats.MAX_RENDER_PAGES,
            jats.MAX_RENDER_BYTES) == (5 * 2**20, 60, 2**30, 200, 30 * 2**20)
    assert jats.MEMORY_EXIT_CODE == 3


def test_the_drawing_keeps_the_reading_order_and_leaves_markup_and_references_out():
    table = ("<table-wrap><label>Table 1</label><caption><p>SYNTHETIC arms</p></caption><table>"
             "<tr><th>arm</th><th>n</th></tr><tr><td>SYNTHETIC control</td><td>12</td></tr></table></table-wrap>")
    formula = ('<p>SYNTHETIC formula <inline-formula><mml:math><mml:mi>x</mml:mi><mml:mo>&lt;</mml:mo>'
               "<mml:mn>2</mml:mn></mml:math></inline-formula> holds.</p>")
    xml = jats_doc(extra=table + formula + "<fig><label>Figure 1</label><caption><p>SYNTHETIC figure caption</p></caption></fig>")
    rendition = jats.render_pdf(xml)
    assert rendition.status == "ok" and rendition.data.startswith(b"%PDF-")
    document = pymupdf.open(stream=rendition.data, filetype="pdf")
    text = " ".join("".join(page.get_text(flags=pdf.TEXT_FLAGS) for page in document).split())
    order = ["SYNTHETIC release windows in relay chains", "Abstract", "SYNTHETIC first abstract sentence.", "Methods",
             "SYNTHETIC body paragraph", "Table 1 SYNTHETIC arms", "arm | n", "SYNTHETIC control | 12",
             "SYNTHETIC formula x<2 holds.", "Figure 1 SYNTHETIC figure caption"]
    positions = [text.find(item) for item in order]
    assert -1 not in positions and positions == sorted(positions), text
    assert "SYNTHETIC REFERENCE ENTRY" not in text and "<" not in text.replace("x<2", "")


def test_a_title_with_markup_characters_is_escaped_not_interpreted():
    rendition = jats.render_pdf(jats_doc(title="SYNTHETIC a &lt;b&gt; tag &amp; more"))
    text = pymupdf.open(stream=rendition.data, filetype="pdf")[0].get_text()
    assert "SYNTHETIC a <b> tag & more" in text


def test_an_entity_declared_in_another_encoding_is_refused_by_the_child():
    declared = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "y">]><article>&x;</article>'
    assert jats.render_pdf(declared.encode("utf-16")).status == "jats_render_failed"


# ---- the record the answer and every view read ---------------------------------------------------------------------

def test_the_rendition_sql_and_the_python_reading_agree(tmp_path):
    store, rid, svid = library(tmp_path)
    found = acquire(store, rid, svid, tmp_path, handler_for([result()]),
                    xml_fetcher_of({url_of("PMC1000001"): jats_doc()}))
    row = store.conn.execute(f"SELECT {jats.RENDITION_SQL} AS r, a.origin, a.retrieved_from, a.original_filename"
                             " FROM source_assets a WHERE a.id = ?", (found["asset_id"],)).fetchone()
    assert bool(row["r"]) is jats.is_rendition(row["origin"], row["retrieved_from"], row["original_filename"]) is True
    passage = next(p for p in store.passages_for(svid) if p["kind"] == "pdf_page")
    assert store.passage_rendition(passage["id"]) is True
    assert store.passage_rendition(None) is False and store.asset_rendition(None) is False
    json.dumps(found)  # the result stays a plain record


def test_a_hyphenated_word_is_never_broken_at_its_hyphen(tmp_path):
    """Found by the live check (PMC10609268): a line broken after "of-" was joined by the extractor into "oflife"."""
    sentence = ("SYNTHETIC compare two weight loss regimens, time-restricted eating and daily calorie restriction, on mood "
                "and quality-of-life measures in adults. ")
    # Every shift of the sentence against the line width, so some line ends at a hyphen whatever the font's widths.
    paragraphs = ["SYNTHETIC" + " w" * shift + " " + sentence for shift in range(40)]
    rendition = jats.render_pdf(jats_doc(paragraphs=paragraphs))
    path = tmp_path / "r.pdf"
    path.write_bytes(rendition.data)
    text = " ".join(" ".join(page.text.split()) for page in pdf.extract_pdf(path).pages)
    assert text.count("quality-of-life") == 40 and text.count("time-restricted") == 40
    assert "oflife" not in text and "timerestricted" not in text

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

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
                {"URL": "http://xplorestaging.ieee.org/ielx8/1/2/3.pdf?arnumber=3", "content-version": "vor"},
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


def test_web_search_results_under_another_title_are_counted_not_kept():
    def handler(request):
        return httpx.Response(200, json={"organic_results": [
            {"title": "A related synthetic paper", "link": "https://other.example/item",
             "resources": [{"file_format": "PDF", "link": "https://other.example/related.pdf"}]},
            {"title": "Another related paper", "link": "https://third.example/paper.pdf"},
        ]})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.web_lookup(client, "10.1/test", "Exact synthetic title", "key")

    result = run(check())
    assert result.candidates == []
    assert result.status == "zero_results" and result.other_title_count == 2


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
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == [
        "unpaywall", "openalex", "crossref", "core", "europepmc", "web_search"]
    assert [(c["provider"], c["version_status"]) for c in store.pdf_candidates(svid)] == [
        ("openalex", "different"), ("core", "uncertain"), ("web_search", "uncertain")]
    connection.close()


QUOTA_HEADERS = {"x-ratelimit-remaining-usd": "0", "x-ratelimit-limit-usd": "1", "x-ratelimit-reset": "3600"}


def _openalex_429(headers):
    return httpx.Response(429, headers=headers, json={"message": "rate limit"})


def _lookup_with(headers):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: _openalex_429(headers))) as client:
            return await acquisition.openalex_lookup(client, "10.1/test", "publishedVersion")

    return run(check())


def test_openalex_refusal_with_no_daily_budget_left_is_recorded_as_quota_exhausted():
    quota = _lookup_with(QUOTA_HEADERS)
    assert (quota.status, quota.http_status, quota.error_code) == ("rate_limited", 429, acquisition.QUOTA_EXHAUSTED)
    assert quota.attempt_id and quota.attempt_id != _lookup_with(QUOTA_HEADERS).attempt_id
    reset = datetime.fromisoformat(quota.reset_at) - datetime.now(timezone.utc)
    assert timedelta(minutes=59) < reset <= timedelta(minutes=60)


def test_openalex_balance_that_is_not_an_exact_finite_zero_keeps_the_plain_429():
    # No header, money left, a prepaid balance, junk, an underflowing positive number, a negative or signed zero.
    for headers in ({}, {"x-ratelimit-remaining-usd": "0.42"}, {"x-ratelimit-remaining-usd": "n/a"},
                    {"x-ratelimit-remaining-usd": "1e-999"}, {"x-ratelimit-remaining-usd": "-1"},
                    {"x-ratelimit-remaining-usd": "-0"}, {"x-ratelimit-remaining-usd": "NaN"},
                    {"x-ratelimit-remaining-usd": "Infinity"}, {**QUOTA_HEADERS, "x-ratelimit-prepaid-remaining-usd": "2.5"},
                    {**QUOTA_HEADERS, "x-ratelimit-prepaid-remaining-usd": "junk"}):
        plain = _lookup_with(headers)
        assert (plain.status, plain.error_code, plain.reset_at) == ("rate_limited", "rate_limited", None), headers
    assert _lookup_with({**QUOTA_HEADERS, "x-ratelimit-remaining-usd": "0.000"}).error_code == acquisition.QUOTA_EXHAUSTED


def test_a_reset_that_cannot_be_used_is_replaced_by_the_next_midnight_and_the_refusal_is_still_recorded():
    for reset in ("1e20", "-5", "soon", "NaN", "999999", ""):
        quota = _lookup_with({**QUOTA_HEADERS, "x-ratelimit-reset": reset})
        assert quota.error_code == acquisition.QUOTA_EXHAUSTED, reset
        at = datetime.fromisoformat(quota.reset_at)
        assert (at.hour, at.minute, at.second) == (0, 0, 0) and datetime.now(timezone.utc) < at <= datetime.now(timezone.utc) + timedelta(days=1)
    assert _lookup_with({k: v for k, v in QUOTA_HEADERS.items() if k != "x-ratelimit-reset"}).reset_at


def test_a_budget_ends_at_its_reset():
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert acquisition.OpenAlexBudget(reset_at=future).exhausted
    assert not acquisition.OpenAlexBudget(reset_at=past).exhausted
    assert not acquisition.OpenAlexBudget().exhausted and not acquisition.OpenAlexBudget(reset_at="junk").exhausted


def _store_with_records(tmp_path, count=2):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    workflow_run = store.create_run(rid, "discovery", {"max_model_calls": 0}, None)["id"]
    svids = []
    for number in range(1, count + 1):
        record = ProviderRecord(f"W{number}", f"Synthetic title {number}", [], 2020, "J", "article", f"10.1/test{number}",
                                None, None, None, "publishedVersion", None, None, {}, {})
        svid, _ = store.upsert_provider_source("openalex", record, None)
        store.add_to_corpus(rid, svid, "search")
        svids.append(svid)
    return connection, store, rid, workflow_run, svids


def _budget_events(store, rid):
    return [json.loads(r[0]) for r in store.conn.execute(
        "SELECT payload_json FROM events WHERE research_id = ? AND type = 'openalex_budget_exhausted'", (rid,))]


def _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, budget, *, together=False):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            def one(svid):
                return acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                      "synthetic@example.org", None, core_key="key", web_search=False,
                                                      openalex_budget=budget, workflow_run_id=workflow_run)
            if together:
                await asyncio.gather(*(one(svid) for svid in svids))
            else:
                for svid in svids:
                    await one(svid)

    run(check())


def test_once_openalex_budget_is_exhausted_later_lookups_are_recorded_not_sent_and_counted_in_one_event(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 3)
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, acquisition.OpenAlexBudget())
    assert len(sent) == 1, "a later record's OpenAlex lookup was sent although the budget was gone"
    rows = [[d for d in store.pdf_discoveries(rid, svid, retry_after=True) if d["provider"] == "openalex"][0]
            for svid in svids]
    assert [(r["status"], r["error_code"], r["http_status"]) for r in rows] == [
        ("rate_limited", "quota_exhausted", 429), ("rate_limited", "quota_exhausted", None),
        ("rate_limited", "quota_exhausted", None)]
    assert len({r["retry_after"] for r in rows}) == 1 and rows[0]["retry_after"]
    # The other routes were still asked for every record.
    assert all({"unpaywall", "crossref", "core"} <= {d["provider"] for d in store.pdf_discoveries(rid, s)} for s in svids)
    assert [(e["run_id"], e["lookups_refused"], e["lookups_skipped"], e["reset_at"]) for e in _budget_events(store, rid)] == [
        (workflow_run, 1, 2, rows[0]["retry_after"])]
    connection.close()


def test_a_restarted_run_reads_the_budget_from_the_store_sends_nothing_and_keeps_the_one_event(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 3)
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    _acquire_all(store, rid, workflow_run, svids[:1], tmp_path, handler, acquisition.OpenAlexBudget())
    event_ids = [r[0] for r in store.conn.execute("SELECT id FROM events WHERE type = 'openalex_budget_exhausted'")]
    # The process is gone: a new budget is loaded the way `ResearchFlow._openalex_budget_of` loads it.
    revived = acquisition.OpenAlexBudget(reset_at=store.openalex_budget_reset())
    assert revived.exhausted
    _acquire_all(store, rid, workflow_run, svids[1:], tmp_path, handler, revived)
    assert len(sent) == 1
    assert [r[0] for r in store.conn.execute("SELECT id FROM events WHERE type = 'openalex_budget_exhausted'")] == event_ids
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 2)]
    # The reset has passed: the budget is not exhausted any more, whatever the store remembers.
    store.conn.execute("UPDATE openalex_budget_runs SET reset_at = '2000-01-01T00:00:00+00:00'")
    assert not acquisition.OpenAlexBudget(reset_at=store.openalex_budget_reset()).exhausted
    connection.close()


def test_lookups_waiting_behind_the_refused_one_are_not_sent(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 4)
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, acquisition.OpenAlexBudget(), together=True)
    assert len(sent) == 1
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 3)]
    connection.close()


def test_the_budget_count_and_its_event_are_written_with_the_lookup_row_or_not_at_all(tmp_path, monkeypatch):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    refused = acquisition.Lookup("rate_limited", [], 429, acquisition.QUOTA_EXHAUSTED,
                                 reset_at="2999-01-01T00:00:00+00:00")
    event = store._event

    def failing(research_id, type_, payload, run_id=None):
        if type_ == "openalex_budget_exhausted":
            raise RuntimeError("event write failed")
        return event(research_id, type_, payload, run_id)

    monkeypatch.setattr(store, "_event", failing)
    with pytest.raises(RuntimeError):
        store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", refused, workflow_run)
    assert store.pdf_discoveries(rid, svids[0]) == []
    assert store.conn.execute("SELECT COUNT(*) FROM openalex_budget_runs").fetchone()[0] == 0
    monkeypatch.setattr(store, "_event", event)
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", refused, workflow_run)
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 0)]
    connection.close()


def test_without_a_budget_every_record_asks_openalex_as_before(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path)
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, None)
    assert len(sent) == 2
    connection.close()


def test_the_flow_loads_a_runs_budget_from_the_store_once_and_shares_it(tmp_path):
    from deixis.workflow.flow import ResearchFlow

    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    flow = object.__new__(ResearchFlow)
    flow.store, flow._openalex_budget = store, {}
    assert not flow._openalex_budget_of(workflow_run).exhausted
    flow._openalex_budget.clear()  # a process that knows nothing, and a store that has been told a refusal
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", acquisition.Lookup(
        "rate_limited", [], 429, acquisition.QUOTA_EXHAUSTED, reset_at="2999-01-01T00:00:00+00:00"), workflow_run)
    budget = flow._openalex_budget_of(workflow_run)
    assert budget.exhausted and flow._openalex_budget_of(workflow_run) is budget
    connection.close()


def test_an_interruption_after_openalex_answers_keeps_the_refusal_and_the_replay_counts_it_once(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    state = {"crash": True}
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        if "api.crossref.org" in request.url.host and state["crash"]:
            raise RuntimeError("the process stopped here")
        return httpx.Response(404)

    with pytest.raises(RuntimeError):
        _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, acquisition.OpenAlexBudget())
    # Before Crossref and CORE were asked: the refusal, its reset time, the count and the one event are stored.
    assert [d["provider"] for d in store.pdf_discoveries(rid, svids[0])] == ["unpaywall", "openalex"]
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 0)]
    # The step is sent again by a process that remembers nothing: it sends no OpenAlex request. The refusal is not
    # repeated; the OpenAlex lookup it now skips is one more lookup not sent.
    state["crash"] = False
    _acquire_all(store, rid, workflow_run, svids, tmp_path, handler,
                 acquisition.OpenAlexBudget(reset_at=store.openalex_budget_reset()))
    assert len(sent) == 1
    quota_rows = store.conn.execute("SELECT COUNT(*) FROM pdf_discovery_runs WHERE error_code = 'quota_exhausted'").fetchone()[0]
    assert quota_rows == 2
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 1)]
    connection.close()


def test_a_summary_update_that_fails_leaves_no_row_and_no_count(tmp_path, monkeypatch):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 2)
    refused = acquisition.Lookup("rate_limited", [], 429, acquisition.QUOTA_EXHAUSTED, reset_at="2999-01-01T00:00:00+00:00")
    skipped = acquisition.Lookup("rate_limited", [], None, acquisition.QUOTA_EXHAUSTED,
                                 reset_at="2999-01-01T00:00:00+00:00", attempt_id="skip-1")
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", refused, workflow_run)
    update = store._set_event_payload

    def failing(*args):
        raise RuntimeError("update failed")

    monkeypatch.setattr(store, "_set_event_payload", failing)
    with pytest.raises(RuntimeError):
        store.record_pdf_discovery(rid, svids[1], "openalex", "10.1/test2", skipped, workflow_run)
    assert store.pdf_discoveries(rid, svids[1]) == []
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 0)]
    monkeypatch.setattr(store, "_set_event_payload", update)
    first = store.record_pdf_discovery(rid, svids[1], "openalex", "10.1/test2", skipped, workflow_run)
    again = store.record_pdf_discovery(rid, svids[1], "openalex", "10.1/test2", skipped, workflow_run)
    assert first == again
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 1)]
    connection.close()


def test_a_run_paused_with_an_empty_budget_sees_another_runs_refusal_when_it_resumes(tmp_path):
    from deixis.workflow.flow import ResearchFlow

    connection, store, rid, run_a, svids = _store_with_records(tmp_path, 2)
    other = store.create_research("Another synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    run_b = store.create_run(other, "discovery", {"max_model_calls": 0}, None)["id"]
    flow = object.__new__(ResearchFlow)
    flow.store, flow._openalex_budget = store, {}
    assert not flow._openalex_budget_of(run_a).exhausted  # A starts, then pauses
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    _acquire_all(store, other, run_b, svids[:1], tmp_path, handler, flow._openalex_budget_of(run_b))
    assert len(sent) == 1
    _acquire_all(store, rid, run_a, svids[1:], tmp_path, handler, flow._openalex_budget_of(run_a))  # A resumes
    assert len(sent) == 1, "the resumed run sent a request the budget cannot serve"
    connection.close()


def _flow_over(store):
    from deixis.workflow.flow import ResearchFlow

    flow = object.__new__(ResearchFlow)
    flow.store, flow._openalex_budget = store, {}
    return flow


def test_a_lookup_history_that_stops_part_way_is_not_settled_and_the_missing_routes_are_asked(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 3)
    flow = _flow_over(store)
    stop_at = {}

    def handler(request):
        host = request.url.host
        if host == stop_at.get("host"):
            raise RuntimeError("the process stopped here")
        if host == "api.core.ac.uk":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    # (host the process stops before answering, routes stored, routes still to ask)
    for svid, host, stored, missing in ((svids[0], "api.openalex.org", ["unpaywall"], 3),
                                        (svids[1], "api.crossref.org", ["unpaywall", "openalex"], 2),
                                        (svids[2], "api.core.ac.uk", ["unpaywall", "openalex", "crossref"], 1)):
        stop_at["host"] = host
        with pytest.raises(RuntimeError):
            _acquire_all(store, rid, workflow_run, [svid], tmp_path, handler, None)
        assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == stored
        assert flow._unanswered_lookups(rid, svid) == missing, host
    # Asked again by the next attempt, the history is whole and nothing is missing.
    stop_at.clear()
    _acquire_all(store, rid, workflow_run, svids[:1], tmp_path, handler, None)
    assert flow._unanswered_lookups(rid, svids[0]) == 0
    connection.close()


def test_an_answer_and_its_candidates_are_stored_together_or_not_at_all(tmp_path, monkeypatch):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)

    def handler(request):
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(200, json={"doi": "10.1/test1", "oa_locations": [
                {"url_for_pdf": "https://repo.example/a.pdf", "version": "publishedVersion"}]})
        return httpx.Response(404)

    def failing(*args):
        raise RuntimeError("stopped between the answer and its candidates")

    candidates = store.record_pdf_candidates
    monkeypatch.setattr(store, "record_pdf_candidates", failing)
    with pytest.raises(RuntimeError):
        _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, None)
    assert store.pdf_discoveries(rid, svids[0]) == [] and store.pdf_candidates(svids[0]) == []
    assert _flow_over(store)._unanswered_lookups(rid, svids[0]) == 0  # nothing at all: the lookup is simply to be made
    monkeypatch.setattr(store, "record_pdf_candidates", candidates)
    _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, None)
    assert [c["candidate_url"] for c in store.pdf_candidates(svids[0])] == ["https://repo.example/a.pdf"]
    connection.close()


def test_every_attempt_is_a_row_and_a_count_of_its_own_and_only_a_replay_of_one_is_not(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(hours=1)).isoformat(timespec="seconds")
    later = (now + timedelta(hours=2)).isoformat(timespec="seconds")

    def quota(attempt, reset_at, status=429):
        return acquisition.Lookup("rate_limited", [], status, acquisition.QUOTA_EXHAUSTED, reset_at=reset_at,
                                  attempt_id=attempt)

    def counts():
        return [(e["lookups_refused"], e["lookups_skipped"], e["reset_at"]) for e in _budget_events(store, rid)]

    first = store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", quota("a1", soon), workflow_run)
    # A replay of that outcome is the same row and the same count.
    assert store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", quota("a1", soon), workflow_run) == first
    assert counts() == [(1, 0, soon)]
    # A second attempt with the very same reset time is another attempt, whatever the clock or the reset says.
    second = store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", quota("a2", soon), workflow_run)
    assert second != first and counts() == [(2, 0, soon)]
    # A third with a different future reset, and a skip: each recorded and counted; the summary shows the latest reset.
    third = store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", quota("a3", later), workflow_run)
    skip = store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", quota("a4", later, None), workflow_run)
    assert len({first, second, third, skip}) == 4 and counts() == [(3, 1, later)]
    assert store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", quota("a3", later), workflow_run) == third
    assert counts() == [(3, 1, later)]
    assert _flow_over(store)._quota_deferred(rid, svids[0]) == 1
    connection.close()


def test_the_newest_row_of_a_route_is_the_one_inserted_last_even_when_the_clock_went_back(tmp_path, monkeypatch):
    import deixis.workflow.store as store_module

    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    stamps = iter(["2026-10-09T12:00:00.000+00:00", "2026-10-09T11:00:00.000+00:00", "2026-10-09T10:00:00.000+00:00"])
    monkeypatch.setattr(store_module, "now", lambda: next(stamps, "2026-10-09T09:00:00.000+00:00"))
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", acquisition.Lookup("zero_results", [], 404))
    refusal = acquisition.Lookup("rate_limited", [], 429, acquisition.QUOTA_EXHAUSTED, reset_at=future, attempt_id="a1")
    row = store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", refusal, workflow_run)  # stamped an hour earlier
    assert [d["status"] for d in store.pdf_discoveries(rid, svids[0])] == ["zero_results", "rate_limited"]
    assert _flow_over(store)._quota_deferred(rid, svids[0]) == 1  # the refusal speaks for the route
    assert store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", refusal, workflow_run) == row
    assert [(e["lookups_refused"], e["lookups_skipped"]) for e in _budget_events(store, rid)] == [(1, 0)]
    connection.close()


def _refused_source(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord("W1", "Synthetic title", [], 2020, "J", "article", "10.1/x", "https://x.example/item",
                            "https://x.example/a.pdf", "publishedVersion", "publishedVersion", None, None, {}, {})
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")
    run_id = store.create_run(rid, "answer", {"max_model_calls": 0}, None)["id"]
    step = store.step(run_id, f"fetch:{svid}", "fetch_pdf")
    store.start_step(step["id"])
    store.finish_step(step["id"], "failed", error_code="fetch_http_error",
                      error={"http_status": 403, "url": "https://x.example/a.pdf"})
    return connection, store, rid, store.run(run_id), svid


def test_an_answer_or_collection_run_resumes_a_lookup_history_that_stopped_after_a_refused_link(tmp_path):
    from deixis.workflow.flow import ResearchFlow

    connection, store, rid, run_row, svid = _refused_source(tmp_path)
    flow = _flow_over(store)
    asked = []

    async def find_other_copy(run, source, other_versions=False):
        asked.append(source["id"])
        return {}

    flow._find_other_copy = find_other_copy
    refusal = {"http_status": 403}
    source = store.source(svid)
    assert flow._needs_other_copy(rid, source, refusal)  # no lookup yet: the 403 opens it, as before
    # The process stopped after Unpaywall answered: three routes were never asked, and the caller asks again.
    store.record_pdf_discovery(rid, svid, "unpaywall", "10.1/x", acquisition.Lookup("zero_results", [], 404))
    assert flow._unanswered_lookups(rid, svid) == 3
    assert run(ResearchFlow._acquire_pdf(flow, run_row, svid, 0, None)) == 1 and asked == [svid]
    # A whole history whose routes all answered is not asked again; a 500 is not the 403/404 trigger.
    for provider in ("openalex", "crossref", "core"):
        store.record_pdf_discovery(rid, svid, provider, "10.1/x", acquisition.Lookup("zero_results", [], 404))
    assert flow._unanswered_lookups(rid, svid) == 0 and not flow._needs_other_copy(rid, source, refusal)
    assert run(ResearchFlow._acquire_pdf(flow, run_row, svid, 0, None)) == 0 and asked == [svid]
    store.record_pdf_discovery(rid, svid, "crossref", "10.1/x", acquisition.Lookup("timeout", [], None, "timeout"))
    assert flow._needs_other_copy(rid, source, refusal) and not flow._needs_other_copy(rid, source, {"http_status": 500})
    connection.close()


def test_every_openalex_request_result_carries_its_attempt_identity_and_a_skip_has_its_own():
    def answer(response):
        async def check():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
                return await acquisition.openalex_lookup(client, "10.1/test", "publishedVersion")

        return run(check())

    results = [answer(httpx.Response(404)), answer(httpx.Response(500)), answer(httpx.Response(403)),
               answer(httpx.Response(429)), answer(httpx.Response(200, json={"doi": "10.1/test", "locations": []})),
               answer(httpx.Response(200, content=b"not json"))]
    assert [r.status for r in results] == ["zero_results", "failed", "auth_required", "rate_limited", "zero_results",
                                           "parse_error"]
    ids = [r.attempt_id for r in results]
    assert all(ids) and len(set(ids)) == len(ids)

    async def skipped():
        budget = acquisition.OpenAlexBudget(reset_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: 1 / 0)) as client:
            return await acquisition.openalex_lookup(client, "10.1/test", "publishedVersion", budget=budget)

    skip = run(skipped())
    assert skip.http_status is None and skip.attempt_id and skip.attempt_id not in ids


def test_without_a_run_the_same_attempt_stored_twice_is_one_row_and_two_attempts_are_two(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    outcome = acquisition.attempted(acquisition.Lookup("zero_results", [], 404))
    first = store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", outcome)
    assert store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", outcome) == first
    assert len(store.pdf_discoveries(rid, svids[0])) == 1
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", acquisition.attempted(outcome.__class__("zero_results", [], 404)))
    assert len(store.pdf_discoveries(rid, svids[0])) == 2
    connection.close()


def test_a_quota_outcome_without_an_identity_gets_one_with_or_without_a_run_or_a_reset(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 1)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    without_reset = acquisition.Lookup("rate_limited", [], 429, acquisition.QUOTA_EXHAUSTED)
    without_run = acquisition.Lookup("rate_limited", [], 429, acquisition.QUOTA_EXHAUSTED, reset_at=future)
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", without_run)
    store.record_pdf_discovery(rid, svids[0], "openalex", "10.1/test1", without_reset, workflow_run)
    store.record_pdf_discovery(rid, svids[0], "crossref", "10.1/test1", acquisition.Lookup("zero_results", [], 404))
    ids = [r[0] for r in store.conn.execute("SELECT attempt_id FROM pdf_discovery_runs ORDER BY rowid")]
    assert ids[0] and ids[1] and ids[0] != ids[1] and ids[2] is None  # an ordinary id-less outcome stays as it was
    connection.close()

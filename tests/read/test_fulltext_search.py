"""The open-web search for a work's full text: what it is sent for, and what it keeps (P10e).

SYNTHETIC records, a fake Scholar answer and a fake fetcher; no network and no model. Passing shows the search is
reserved before it is sent, that the depth bounds it, that a file is kept only when the file itself names this
record, and that the person is not asked before the search has had its turn. It says nothing about how often the
open web actually holds a missing PDF.
"""

import asyncio
import json

import pytest

from deixis.documents import fetch
from deixis.storage.db import dumps, new_id, now
from deixis.workflow.features.report import report_file_asks as file_asks
from deixis.workflow.read import fulltext_search
from deixis.workflow.run import fast_path
from helpers import make_pdf

from test_report_file_asks import COLUMN_A, PLAN, Library, cell

TITLE = "A SYNTHETIC study of delay bounds"  # four words at least: a shorter title names no one paper
PDF_URL = "https://repo.example.org/papers/a.pdf"


def _pdf(text: str) -> bytes:
    """A one-page PDF whose page carries `text`."""
    return make_pdf([text])


class FakeScholar:
    """One Scholar answer: the record's own title with a PDF resource, unless `results` says otherwise."""

    def __init__(self, results=None):
        self.results = results
        self.queries = []

    async def get(self, url, params=None, timeout=None, headers=None):
        self.queries.append((params or {}).get("q"))
        organic = self.results if self.results is not None else [
            {"title": TITLE, "link": "https://repo.example.org/record/a",
             "resources": [{"link": PDF_URL, "file_format": "PDF"}]}]
        return _Response(200, {"organic_results": organic})


class _Response:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.headers = {}

    def json(self):
        return self._payload


class Flow:
    """What `run_one` reads of a flow: the store, the settings, the HTTP client."""

    def __init__(self, library, scholar):
        self.store = library.store
        self.deps = _Deps(library, scholar)


class _Deps:
    def __init__(self, library, scholar):
        self.store = library.store
        self.http = scholar
        self.settings = library.settings


def _library(tmp_path, effort="standard"):
    held = Library(tmp_path, effort=effort)
    held.settings = _Settings(tmp_path)
    return held


class _Settings:
    def __init__(self, tmp_path):
        self.papers_dir = tmp_path / "papers"
        self.recovery_dir = tmp_path / "recovery"
        self.contact_email = None


def _gap(held, key="A", title=TITLE):
    """One work in the report's gap: a record with no file whose retrieval answered and whose cell is open."""
    svid = held.source(key)
    held.store.conn.execute("UPDATE source_versions SET title = ?, doi = ? WHERE id = ?",
                            (title, "10.1/synthetic-a", svid))
    held.freeze([cell(COLUMN_A, svid, state="inaccessible", evidence=())])
    return svid


def test_a_search_is_reserved_before_it_is_sent_and_says_which_question_it_is_for(tmp_path):
    held = _library(tmp_path)
    svid = _gap(held)
    reserved = fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    assert [row["source_version_id"] for row in reserved] == [svid]
    row = fulltext_search.searches(held.store, held.research_id)[0]
    # The row exists before any request: the allowance is spent by the reservation, not by the answer.
    assert (row["status"], row["outcome"], row["query_text"]) == ("queued", None, None)
    assert [axis["axis_id"] for axis in json.loads(row["axes_json"])] == ["AX1"]
    assert row["rule"] == fulltext_search.RULE and row["run_id"] == held.discovery["id"]
    # Reserved once: the same work is not reserved again on a later turn.
    assert fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key") == []


def test_without_a_key_or_an_allowance_the_row_says_so_instead_of_waiting(tmp_path):
    held = _library(tmp_path)
    _gap(held)
    fulltext_search.advance(held.store, held.research_id, None)
    row = fulltext_search.searches(held.store, held.research_id)[0]
    assert (row["status"], row["outcome"]) == ("skipped", "no_key")
    # The search has had its turn either way, so the person may now be asked.
    assert fulltext_search.settled(held.store, held.research_id, row["work_id"], 1)

    quick = _library(tmp_path / "quick", effort="quick")
    _gap(quick)
    quick_rows = fulltext_search.advance(quick.store, quick.research_id, "SYNTHETIC-key")
    assert [row["outcome"] for row in quick_rows] == ["no_allowance"]
    assert fast_path.MODES["quick"].fulltext_searches == 0


def test_the_depth_bounds_how_many_searches_are_sent(tmp_path):
    held = _library(tmp_path)
    for key in "ABCD":
        svid = held.source(key)
        held.store.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (f"SYNTHETIC study {key}", svid))
    held.freeze([cell(COLUMN_A, svid, state="inaccessible", evidence=()) for svid in held.sources.values()])
    rows = fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    # Standard sends three; the fourth work is written down as past the allowance, not left waiting.
    assert [row["status"] for row in rows] == ["queued", "queued", "queued", "skipped"]
    assert rows[3]["outcome"] == "allowance_spent"


def test_the_person_is_not_asked_before_the_search_has_had_its_turn(tmp_path):
    held = _library(tmp_path)
    _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    # The search is reserved and has not run: asking now would ask before the last automatic route was tried.
    assert file_asks.advance(held.store, held.research_id) == []
    row = fulltext_search.searches(held.store, held.research_id)[0]
    fulltext_search._finish(held.store, row, "succeeded", "no_result", None)
    assert len(file_asks.advance(held.store, held.research_id)) == 1


def test_a_file_whose_title_page_carries_this_records_doi_is_attached(tmp_path, monkeypatch):
    held = _library(tmp_path)
    svid = _gap(held)
    scholar = FakeScholar()
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]

    async def fetched(url, **kwargs):
        return fetch.FetchResult("ok", data=_pdf(f"{TITLE} https://doi.org/10.1/synthetic-a"), final_url=url,
                                 media_type="application/pdf", http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, scholar), row, "SYNTHETIC-key"))
    settled = fulltext_search.searches(held.store, held.research_id)[0]
    assert (settled["status"], settled["outcome"], settled["reason"]) == ("succeeded", "attached", "doi_on_title_page")
    assert held.store.has_asset(svid)
    # The query carried the record's own title; the result was matched on that title too.
    assert TITLE in scholar.queries[0]
    # The work holds a file now, so nothing asks the person for one.
    assert file_asks.advance(held.store, held.research_id) == []


def test_a_file_that_only_names_the_work_waits_for_the_person_instead(tmp_path, monkeypatch):
    held = _library(tmp_path)
    svid = _gap(held)
    held.store.conn.execute("UPDATE source_versions SET authors_json = ?, venue = ? WHERE id = ?",
                            (dumps([{"name": "H. Yildiz"}]), "SYNTHETIC Letters", svid))
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]

    async def fetched(url, **kwargs):
        return fetch.FetchResult("ok", data=_pdf(f"{TITLE} Yildiz SYNTHETIC Letters"), final_url=url,
                                 media_type="application/pdf", http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), row, "SYNTHETIC-key"))
    settled = fulltext_search.searches(held.store, held.research_id)[0]
    # The title page names the work, never which version it is, so the copy is listed and nothing is attached.
    assert settled["outcome"] == "candidate_listed"
    assert not held.store.has_asset(svid)
    candidate = held.store.pdf_candidates(svid)[0]
    assert (candidate["provider"], candidate["error_code"]) == ("web_search", "version_unsettled")
    # The question is still open and the search has had its turn, so the person is asked now.
    assert [asked["source_version_id"] for asked in file_asks.advance(held.store, held.research_id)] == [svid]


def test_a_file_of_another_paper_is_not_kept(tmp_path, monkeypatch):
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]

    async def fetched(url, **kwargs):
        return fetch.FetchResult("ok", data=_pdf("SYNTHETIC another paper entirely"), final_url=url,
                                 media_type="application/pdf", http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), row, "SYNTHETIC-key"))
    settled = fulltext_search.searches(held.store, held.research_id)[0]
    assert settled["outcome"] == "no_match"
    assert not held.store.has_asset(svid)
    assert held.store.pdf_candidates(svid)[0]["error_code"] == "identity_mismatch"


def test_a_search_that_finds_nothing_says_so_and_does_not_run_again(tmp_path):
    held = _library(tmp_path)
    _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar(results=[])), row, "SYNTHETIC-key"))
    settled = fulltext_search.searches(held.store, held.research_id)[0]
    assert (settled["status"], settled["outcome"]) == ("succeeded", "no_result")
    assert fulltext_search.settled(held.store, held.research_id, settled["work_id"], 1)
    # The step succeeded, so a second turn of the queue reads its outcome instead of searching again.
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), settled, "SYNTHETIC-key"))
    assert fulltext_search.searches(held.store, held.research_id)[0]["outcome"] == "no_result"


def test_the_query_carries_the_title_and_the_first_author_or_falls_back_to_the_doi():
    assert fulltext_search.query_for(
        {"title": "A SYNTHETIC routing protocol", "authors": [{"name": "H. Yildiz"}], "doi": "10.1/x"}
    ) == '"A SYNTHETIC routing protocol" Yildiz'
    # A title with too little to search on falls back to the record's DOI.
    assert fulltext_search.query_for({"title": "DBR", "authors": [], "doi": "10.1/x"}) == "10.1/x"
    assert fulltext_search.query_for({"title": "", "authors": [], "doi": None}) is None


def test_a_file_that_only_cites_this_record_is_not_attached(tmp_path, monkeypatch):
    """A page carrying the DOI without the title is another paper's reference list, not this record's title page."""
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]

    async def fetched(url, **kwargs):
        # Another paper's first page, citing this record: its DOI is on the page, its title is not.
        return fetch.FetchResult("ok", data=_pdf("SYNTHETIC congestion control in dense deployments\n"
                                                 "[7] https://doi.org/10.1/synthetic-a"),
                                 final_url=url, media_type="application/pdf", http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), row, "SYNTHETIC-key"))
    assert not held.store.has_asset(svid)
    assert fulltext_search.searches(held.store, held.research_id)[0]["outcome"] == "candidate_listed"


def test_a_later_copy_that_carries_the_doi_is_still_attached(tmp_path, monkeypatch):
    """The first result naming only the work does not end the search: a verifiable copy may come after it."""
    held = _library(tmp_path)
    svid = _gap(held)
    held.store.conn.execute("UPDATE source_versions SET authors_json = ?, venue = ? WHERE id = ?",
                            (dumps([{"name": "H. Yildiz"}]), "SYNTHETIC Letters", svid))
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]
    scholar = FakeScholar(results=[
        {"title": TITLE, "link": "https://repo.example.org/a", "resources": [{"link": PDF_URL, "file_format": "PDF"}]},
        {"title": TITLE, "link": "https://publisher.example.org/a",
         "resources": [{"link": "https://publisher.example.org/a.pdf", "file_format": "PDF"}]}])
    pages = {PDF_URL: f"{TITLE} Yildiz SYNTHETIC Letters",
             "https://publisher.example.org/a.pdf": f"{TITLE} https://doi.org/10.1/synthetic-a"}

    async def fetched(url, **kwargs):
        return fetch.FetchResult("ok", data=_pdf(pages[url]), final_url=url, media_type="application/pdf",
                                 http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, scholar), row, "SYNTHETIC-key"))
    settled = fulltext_search.searches(held.store, held.research_id)[0]
    assert (settled["outcome"], settled["reason"]) == ("attached", "doi_on_title_page")
    assert held.store.has_asset(svid)


def test_a_search_cut_off_in_flight_is_not_sent_again(tmp_path):
    """The request is what is metered, so an interrupted search is written down, never queued a second time."""
    held = _library(tmp_path)
    _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]
    fulltext_search._mark_running(held.store, row)
    fulltext_search.recover(held.store)
    settled = fulltext_search.searches(held.store, held.research_id)[0]
    assert (settled["status"], settled["outcome"], settled["reason"]) == ("failed", "failed", "search_interrupted")
    # The search has had its turn, so the person may be asked; and the same row is never taken again.
    assert fulltext_search.settled(held.store, held.research_id, settled["work_id"], 1)
    assert not fulltext_search._mark_running(held.store, settled)
    assert fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key") == []


def test_a_depth_frozen_before_the_rule_reserves_nothing(tmp_path):
    """A policy that names no allowance decided nothing, so no row is written and the person is not asked either."""
    held = _library(tmp_path)
    _gap(held)
    policy = {key: value for key, value in held.store.run(held.discovery["id"])["budget"]["fast_path"].items()
              if key not in ("fulltext_search_rule", "fulltext_searches")}
    held.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?",
                            (dumps({"fast_path": policy}), held.discovery["id"]))
    assert fulltext_search.allowance(held.store, held.discovery["id"]) is None
    assert fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key") == []
    assert fulltext_search.searches(held.store, held.research_id) == []
    assert file_asks.advance(held.store, held.research_id) == []


def test_a_search_cancelled_with_the_old_question_is_reserved_again(tmp_path):
    """A cancelled search was never sent: it neither spends the allowance nor counts as a turn for the new question."""
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]
    fulltext_search._finish(held.store, row, "cancelled", None, "scope_revised")
    assert not fulltext_search.settled(held.store, held.research_id, row["work_id"], 1)
    # The same question again: the work is reserved a second time, because the first row was never sent.
    assert [new["source_version_id"] for new
            in fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")] == [svid]
    assert len(fulltext_search.searches(held.store, held.research_id)) == 2


def test_an_attach_that_fails_claims_no_file(tmp_path, monkeypatch):
    """A verified file whose attach breaks leaves the search failed and the record without a PDF, never 'attached'."""
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]
    page = f"{TITLE} https://doi.org/10.1/synthetic-a"

    async def fetched(url, **kwargs):
        return fetch.FetchResult("ok", data=_pdf(page), final_url=url, media_type="application/pdf", http_status=200)

    async def refuse(*args, **kwargs):
        raise RuntimeError("SYNTHETIC attach failure")

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    monkeypatch.setattr(fulltext_search.acquisition, "attach_searched_file", refuse)
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), row, "SYNTHETIC-key"))
    failed = fulltext_search.searches(held.store, held.research_id)[0]
    assert (failed["status"], failed["reason"]) == ("failed", "attach_failed")
    assert not held.store.has_asset(svid)


def test_a_reference_entry_that_names_the_title_and_the_doi_is_not_attached(tmp_path, monkeypatch):
    """A citing paper's reference list carries both; only a title borne at the top of the page is a title page."""
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]

    async def fetched(url, **kwargs):
        # Another paper's own first page, whose reference list names this work in full, DOI and all. The page is
        # written line by line, because its own title and abstract come before the reference entry.
        page = "\n".join(["SYNTHETIC congestion control for dense deployments", "Abstract."]
                         + ["This SYNTHETIC work studies congestion under load."] * 14
                         + ["References", f"[7] {TITLE}. https://doi.org/10.1/synthetic-a"])
        return fetch.FetchResult("ok", data=_pdf(page), final_url=url, media_type="application/pdf", http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), row, "SYNTHETIC-key"))
    assert not held.store.has_asset(svid)
    assert fulltext_search.searches(held.store, held.research_id)[0]["outcome"] == "candidate_listed"


def test_a_request_that_went_out_still_counts_after_it_is_cancelled(tmp_path):
    """A search cancelled once its request was sent spent the allowance; nothing hands that back."""
    held = _library(tmp_path)
    for key in "ABC":
        svid = held.source(key)
        held.store.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (f"SYNTHETIC study {key}", svid))
    held.freeze([cell(COLUMN_A, svid, state="inaccessible", evidence=()) for svid in held.sources.values()])
    sent = fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    assert [row["status"] for row in sent] == ["queued"] * 3
    for row in sent:  # each request goes out, and each is then cancelled: the question changed under them
        fulltext_search._mark_running(held.store, row)
        fulltext_search._finish(held.store, row, "cancelled", None, "scope_revised")
    # The works are open again, so they are reserved again — but the depth's three requests are gone.
    again = fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    assert [row["outcome"] for row in again] == ["allowance_spent"] * 3


def test_a_work_past_the_allowance_says_so_even_when_no_key_is_connected(tmp_path):
    """A row written down as unsent spends nothing, so it cannot push the next work past the allowance."""
    held = _library(tmp_path)
    for key in "ABCD":
        svid = held.source(key)
        held.store.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (f"SYNTHETIC study {key}", svid))
    held.freeze([cell(COLUMN_A, svid, state="inaccessible", evidence=()) for svid in held.sources.values()])
    rows = fulltext_search.advance(held.store, held.research_id, None)
    # Every one of the four says the same true thing: no key was connected. None of them spent the allowance.
    assert [row["outcome"] for row in rows] == ["no_key"] * 4


def test_a_citing_abstract_that_names_the_title_is_not_attached(tmp_path, monkeypatch):
    """The title has to be borne at the top of the page, not named in the page's own abstract."""
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    row = fulltext_search.searches(held.store, held.research_id)[0]

    async def fetched(url, **kwargs):
        # A citing paper whose abstract names this work in full inside the page's first characters, and whose
        # reference list carries its DOI: both halves on one page, neither of them its own title.
        page = "\n".join(["SYNTHETIC congestion control for dense deployments", "U. Yildiz and A SYNTHETIC coauthor",
                          f"Abstract. We compare against {TITLE} under load.", "1. Introduction",
                          "References", "[7] https://doi.org/10.1/synthetic-a"])
        return fetch.FetchResult("ok", data=_pdf(page), final_url=url, media_type="application/pdf", http_status=200)

    monkeypatch.setattr(fetch, "fetch_pdf", fetched)
    asyncio.run(fulltext_search.run_one(Flow(held, FakeScholar()), row, "SYNTHETIC-key"))
    assert not held.store.has_asset(svid)
    assert fulltext_search.searches(held.store, held.research_id)[0]["outcome"] == "candidate_listed"


def test_a_search_queued_for_the_old_question_frees_its_place(tmp_path):
    """A request never sent holds no place in the new question's allowance: it is cancelled where that is read."""
    held = _library(tmp_path)
    svid = _gap(held)
    fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    first = fulltext_search.searches(held.store, held.research_id)[0]
    assert first["status"] == "queued"
    # The person changes the question; the report of the new question names the same work.
    held.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (held.research_id,))
    held.store.conn.execute("UPDATE reports SET scope_revision = 2 WHERE id = ?", (held.report_id,))
    held.store.conn.execute("UPDATE fast_path_ledgers SET scope_revision = 2 WHERE research_id = ?",
                            (held.research_id,))
    reserved = fulltext_search.advance(held.store, held.research_id, "SYNTHETIC-key")
    assert [row["status"] for row in reserved] == ["queued"]
    rows = fulltext_search.searches(held.store, held.research_id)
    assert [(row["status"], row["reason"]) for row in rows][0] == ("cancelled", "scope_revised")
    assert rows[1]["source_version_id"] == svid and rows[1]["scope_revision"] == 2

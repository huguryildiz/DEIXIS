"""What an effort bounds: how many records one `sw` query reads, and how long a run waits on a rate-limited provider
(D88, slice 13c).

Records and provider answers are SYNTHETIC and from two fields, and every transport is mocked: passing shows workflow
behavior — which request is sent, what ends a read, what a refused batch leaves on the record — not how long a real
run takes, not what the limits do to recall, and not how often a real provider answers 429. Nothing here measures a
duration: no effort stops a run at a time, and the minute targets of D88 are measured after this slice, not enforced
by it. A `legacy` research is exercised too, because nothing about it may change.
"""

import json

import httpx
import pytest

from deixis.config import Settings
from deixis.domain.rules import PROVIDER_WAIT, SW_READ_LIMIT
from deixis.providers import common, lookup
from deixis.workflow import flow, protocol
from fakes import FakeAdapter, valid_response
from test_lookup_flow import Sources, app_for as lookup_app_for, decision_of, records_of, step_output
from test_lookup_flow import client_of as lookup_client_of, discover as lookup_discover, work as lookup_work
from test_search_paging import PagedProviders, app_for, client_of, discover, reached_screening, rows_of, wait


@pytest.fixture(autouse=True)
def no_gate(monkeypatch):
    """Open the Semantic Scholar gate so a test does not wait on it (D67); every SYNTHETIC 429 here waits zero."""
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)


class RefusedWithNoWait(PagedProviders):
    """The page at `fail_at` answers 429 with a stated wait of zero, so only the effort decides whether it is retried.

    Every attempt, retry included, is recorded in `self.openalex`, so the number of them is what a test reads.
    """

    def __call__(self, request):
        response = super().__call__(request)
        if response.status_code == 429:
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        return response


def attempts_at(providers, start):
    return [page for page in providers.openalex if page[0] == start]


def error_of(store, rid, page_number):
    row = store.conn.execute(
        "SELECT error_json FROM search_runs WHERE research_id = ? AND page_number = ? AND status = 'rate_limited'",
        (rid, page_number)).fetchone()
    return json.loads(row[0])


# ---- the read limit of an effort ---------------------------------------------------------------


def test_the_read_limit_is_this_research_s_effort(tmp_path, monkeypatch):
    """`quick` stops at its own limit and counts what it left; a resumed run reads its stored pages and asks again
    for nothing."""
    monkeypatch.setattr(flow, "SW_READ_LIMIT", {"quick": 30, "standard": 60, "detailed": 90})
    providers = PagedProviders(openalex_total=90)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, view, run = discover(client, effort="quick")
        read = list(providers.openalex)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == read == [(0, 20), (20, 10)]  # the last page asks only for what is left of the limit
    rows = rows_of(view)
    assert (rows[-1]["stop_reason"], rows[-1]["read_limit"], rows[-1]["read_total"]) == ("read_limit", 30, 30)
    assert rows[-1]["unread_count"] == 60  # nothing read is dropped; what was not read is counted


def test_a_deeper_effort_reads_further_into_the_same_query(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "SW_READ_LIMIT", {"quick": 30, "standard": 60, "detailed": 90})
    providers = PagedProviders(openalex_total=90)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, view, run = discover(client, effort="detailed")
    finally:
        client.__exit__(None, None, None)
    rows = rows_of(view)
    assert rows[-1]["read_total"] == 90 and rows[-1]["read_limit"] == 90 and rows[-1]["unread_count"] == 0


def test_the_page_request_allowance_shrinks_with_the_effort():
    """The allowance is derived from the effort's own read limit and its own waiting, and from nothing else."""
    queries = [{"provider_id": "openalex"}]
    allowances = {effort: flow.extra_page_requests(queries, effort) for effort in SW_READ_LIMIT}
    # openalex serves 200 records a page: quick reads 2 pages at 1 + 0 + 2 requests each, standard 5 at 1 + 1 + 2,
    # detailed 10 at 1 + 2 + 2; each query's own first request is already in the unpaged budget.
    assert allowances == {"quick": 2 * 3 - 1, "standard": 5 * 4 - 1, "detailed": 10 * 5 - 1}
    assert allowances["quick"] < allowances["standard"] < allowances["detailed"]


# ---- waiting on a provider -----------------------------------------------------------------------


def test_a_quick_page_that_is_rate_limited_ends_that_read_and_the_run_goes_on(tmp_path, monkeypatch):
    """`quick` waits for no 429: the page is recorded `page_failed`, the pages before it stand, and the run goes on.

    The provider states a wait of zero, so nothing but the effort keeps the page from being retried.
    """
    providers = RefusedWithNoWait(openalex_total=45, crossref_total=12, fail_at=20)
    app = app_for(tmp_path, monkeypatch, providers)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="quick")
        error = error_of(app.state.store, rid, 1)
    finally:
        client.__exit__(None, None, None)
    assert attempts_at(providers, 20) == [(20, 20)]  # asked once, not waited out
    assert [(r["page_number"], r["status"], r["stop_reason"]) for r in rows_of(view)] == [
        (0, "completed", None), (1, "rate_limited", "page_failed")]
    assert error["rate_limit_retries"] == 0  # the skipped wait is on the row, not silent
    # The read that was refused ends there; the other provider reads all of its own and the run carries on (D18).
    assert [(r["result_count"], r["stop_reason"]) for r in rows_of(view, "crossref")] == [(10, None), (2, "exhausted")]
    assert reached_screening(run)


def test_standard_waits_out_one_rate_limit_and_detailed_as_many_as_it_always_did(tmp_path, monkeypatch):
    for effort, asked in (("standard", 2), ("detailed", 3)):
        providers = RefusedWithNoWait(openalex_total=45, fail_at=20)
        app = app_for(tmp_path, monkeypatch, providers)
        client = client_of(app)
        try:
            rid, run_id, view, run = discover(client, effort=effort)
            error = error_of(app.state.store, rid, 1)
        finally:
            client.__exit__(None, None, None)
        assert attempts_at(providers, 20) == [(20, 20)] * asked, effort
        assert error["rate_limit_retries"] == asked - 1, effort


def test_a_legacy_search_waits_as_it_always_did_whatever_the_effort(tmp_path, monkeypatch):
    """A `legacy` request is byte for byte what it was: it carries no effort, keeps the bounded retries and opens
    no page step, on the `quick` effort that waits for nothing in an `sw` run."""
    def one_provider_plan(step_input):
        if step_input["task_type"] != "search_plan":
            return valid_response(step_input)
        output = json.loads(valid_response(step_input))
        output["search_plan"].update(providers=["openalex"], concepts=[
            {"label": "packet size", "role": "core", "synonyms": ["packet size"]}])
        return json.dumps(output)

    class RefusedOnce(PagedProviders):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.refused = False

        def __call__(self, request):
            if request.url.host == "api.openalex.org" and not self.refused:
                self.refused = True
                return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
            return super().__call__(request)

    providers = RefusedOnce(openalex_total=45)
    app = app_for(tmp_path, monkeypatch, providers, workflow="legacy", adapter=FakeAdapter(one_provider_plan))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="quick")
        descriptions = [row[0] for row in app.state.store.conn.execute(
            "SELECT request_description FROM search_runs WHERE research_id = ?", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == [(0, 10)]  # the refused attempt was retried and served
    rows = rows_of(view)
    assert len(rows) == 1 and rows[0]["status"] == "completed"
    assert [rows[0][key] for key in ("page_number", "read_limit", "read_total", "stop_reason", "unread_count")] == [None] * 5
    assert descriptions == ['GET https://api.openalex.org/works search.title_and_abstract=\'"packet size"\''
                            ' per_page=10 access=keyless']


# ---- the abstract lookup -------------------------------------------------------------------------


def two_records_no_abstract():
    """Two records from two fields, neither carrying an abstract, so both are asked about."""
    return [lookup_work(1, title="SYNTHETIC relay scheduling in a sensor node", doi="10.1/a"),
            lookup_work(2, title="SYNTHETIC molecular release scheduling", doi="10.1/b")]


def batches_of(tmp_path, monkeypatch, effort):
    monkeypatch.setattr(lookup, "S2_LOOKUP_BATCH", 1)  # one record a batch, so a refused batch is not the last one
    sources = Sources(works=two_records_no_abstract(), s2_status=429)  # Crossref holds neither DOI: 404, not_found
    app = lookup_app_for(tmp_path, monkeypatch, sources)
    client = lookup_client_of(app)
    try:
        rid, run_id, view, run = lookup_discover(client, effort=effort)
        store = app.state.store
        by_id = records_of(store, rid)
        codes = {key: (decision_of(store, rid, by_id[key]) or {}).get("reason_code") for key in ("W1", "W2")}
        steps = [step_output(store, run_id, f"record_lookup:semantic_scholar:{n}") for n in (0, 1)]
        statuses = [row[0] for row in store.conn.execute(
            "SELECT status FROM record_lookups WHERE provider = 'semantic_scholar'")]
    finally:
        client.__exit__(None, None, None)
    return sources, codes, steps, statuses


def test_a_quick_lookup_batch_that_is_rate_limited_is_recorded_and_the_next_batch_is_still_sent(tmp_path, monkeypatch):
    """`quick` waits for no 429 here either: the refused batch is written with its status, its records are left
    `abstract_not_found` rather than promised a retry this run will not make, and the next batch is still sent."""
    sources, codes, steps, statuses = batches_of(tmp_path, monkeypatch, "quick")
    assert len(sources.batches) == 2 and statuses == ["failed", "failed"]  # asked once each, and the second was asked
    assert [(step["status"], step["rate_limit_retries"]) for step in steps] == [("rate_limited", 0)] * 2
    assert codes == {"W1": "abstract_not_found", "W2": "abstract_not_found"}


def test_a_standard_lookup_batch_waits_once_and_leaves_the_record_to_a_later_run(tmp_path, monkeypatch):
    """An effort that waits asks again inside the batch, and what it could not get stays `no_abstract`: a later
    discovery run asks that source once more."""
    sources, codes, steps, statuses = batches_of(tmp_path, monkeypatch, "standard")
    assert len(sources.batches) == 4  # two batches, each asked twice: the request and the one wait
    assert [(step["status"], step["rate_limit_retries"]) for step in steps] == [("rate_limited", 1)] * 2
    assert codes == {"W1": "no_abstract", "W2": "no_abstract"}


# ---- the protocol record -------------------------------------------------------------------------


def test_the_protocol_record_carries_this_research_s_own_search_read_figures():
    scope = {"question": "SYNTHETIC question", "steering": None, "language_hint": None, "source_scope": "academic",
             "seed_mode": "question_only", "providers": ["openalex"], "model_connection": "fake",
             "requested_model": "fake-model", "reasoning_effort": None, "literature_model": None,
             "review_mode": "off", "search_workflow": "sw"}
    settings = Settings(data_dir=None)
    for effort in ("quick", "standard", "detailed"):
        body = protocol.build_protocol(scope | {"effort": effort}, {}, None, [], "pkg_hash", settings)
        assert body["thresholds"]["search_read"] == {"read_limit_per_query": SW_READ_LIMIT[effort],
                                                     "rate_limit_retries": PROVIDER_WAIT[effort]}, effort
    assert SW_READ_LIMIT == {"quick": 400, "standard": 1_000, "detailed": 2_000}
    assert PROVIDER_WAIT == {"quick": 0, "standard": 1, "detailed": common.MAX_RATE_LIMIT_RETRIES}

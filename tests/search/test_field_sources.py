"""The field sources a depth searches beside OpenAlex: which one, how many records, and what is recorded instead.

Synthetic throughout — no live app, provider or model. What is guarded here is that the choice comes from the
stored routing record and the depth's own frozen numbers, that a source reads only its own share and reads it once
across a resume, and that every source the depth does not send carries its own reason.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers import arxiv
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.runtime.config import Settings
from deixis.storage import db
from deixis.workflow.run import fast_path, views
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store
from deixis.workflow.search import routing, search as fast_search, small_batch
from overlap_flow_helpers import discover
from test_fast_path_clock import FakeClock
from test_small_batch_flow import app_for, client_of

QUESTION = "SYNTHETIC field source question"
QUERIES = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"},
           {"provider_id": "pubmed", "query_text": "SYNTHETIC gamma"},
           {"provider_id": "arxiv", "query_text": "SYNTHETIC delta"}]


def _library(tmp_path, name="library.sqlite", effort="standard"):
    conn = db.connect(tmp_path / name)
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research(QUESTION, "academic", effort,
                               ["openalex", "semantic_scholar", "pubmed", "arxiv"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, effort)
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    return SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))


def _routing(lib, chosen, status="read"):
    """The routing record a run stores before it plans, written the way `flow._source_routing` writes it."""
    step = lib.store.step(lib.run["id"], "source_routing", "code:source_routing")
    lib.store.start_step(step["id"])
    record = {"status": status, "query": "SYNTHETIC gate", "total": 100, "fields": [], "route_share": 0.25,
              "table_version": "deixis.source_routes.v1",
              "chosen": [{"provider_id": "openalex", "reason": "always"},
                         {"provider_id": "semantic_scholar", "reason": "always"}] + chosen,
              "left_out": [], "providers": ["openalex", "semantic_scholar"] + [c["provider_id"] for c in chosen]}
    lib.store.finish_step(step["id"], "succeeded", output={"routing": record, "reads": {}, "vocabulary": {},
                                                           "queries": QUERIES, "query_compiler": "v1"})
    return record


def _record(identity):
    return ProviderRecord(provider_record_id=identity, title=f"SYNTHETIC {identity}", authors=[], year=2026,
                          venue=None, publication_type="article", doi=None, landing_url=None, oa_pdf_url=None,
                          oa_pdf_version=None, version_label="publishedVersion",
                          abstract=f"SYNTHETIC abstract {identity}", abstract_origin="provider_pubmed",
                          identifiers={"pubmed": identity}, raw={"id": identity})


def _flow(lib, tmp_path):
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock,
                                        settings=Settings(data_dir=tmp_path / "data"), local_embedder=None))
    fast_path.enter_stage(lib.store, lib.run, "search")
    return flow


# --- which source, and in what order -------------------------------------------------------------------------

@pytest.mark.parametrize("shares,first", [((("pubmed", 0.9), ("arxiv", 0.3)), "pubmed"),
                                          ((("pubmed", 0.26), ("arxiv", 0.74)), "arxiv"),
                                          ((("pubmed", 0.5), ("arxiv", 0.5)), "pubmed")])
def test_the_source_whose_fields_hold_the_most_records_is_read_first(shares, first):
    """The share decides; a tie goes to the index that is not a preprint server, never to the registry's order."""
    record = {"status": "read", "chosen": [{"provider_id": "openalex", "reason": "always"}]
              + [{"provider_id": provider, "reason": "share", "share": share} for provider, share in shares]}
    assert [row["provider_id"] for row in routing.field_sources(record, 2)] == [first] + [
        provider for provider, _ in shares if provider != first]
    assert [row["provider_id"] for row in routing.field_sources(record, 1)] == [first]


def test_a_source_searched_through_another_host_is_not_an_index_of_its_own():
    """bioRxiv is searched like any other source, and never counted as the independent index a depth pays for."""
    record = {"status": "read", "chosen": [{"provider_id": "biorxiv", "reason": "share", "share": 0.9},
                                           {"provider_id": "pubmed", "reason": "share", "share": 0.8}]}
    rows = routing.field_sources(record, 2)
    assert [(row["provider_id"], row["independent"]) for row in rows] == [("biorxiv", False), ("pubmed", True)]


def test_a_distribution_that_could_not_be_read_names_no_best_source():
    """Every usable source is chosen when the distribution failed, so no share says which fits best: none is sent."""
    record = {"status": "unavailable", "chosen": [{"provider_id": "pubmed", "reason": "distribution_unavailable"}]}
    assert routing.field_sources(record, 1) == [] and routing.field_sources(record, 0) == []


# --- what the depth plans ------------------------------------------------------------------------------------

def test_a_depth_that_pays_for_a_field_source_takes_its_records_off_the_keyword_cap(tmp_path):
    lib = _library(tmp_path)
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9},
                   {"provider_id": "arxiv", "reason": "share", "share": 0.4}])
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    policy = lib.run["budget"]["fast_path"]
    (field,) = plan["field"]
    # One source, its records off the same cap the keyword queries read from, and its place in the plan — not in
    # whichever order the replies come back.
    assert (field["query"]["provider_id"], field["records"], field["request_index"]) == ("pubmed", 250, 0)
    assert plan["keyword_cap"] == policy["keyword_record_cap"] - policy["field_search"]["records"]
    # The source the depth did not pay for says that, and not that OpenAlex is the only searchable source.
    assert [(row["query"]["provider_id"], row["reason"]) for row in plan["dropped"]] == [
        ("arxiv", "after_the_depth_s_field_source")]
    lib.conn.close()




def test_a_share_that_could_not_be_read_sends_no_field_source_and_says_so(tmp_path):
    lib = _library(tmp_path, "unread.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "distribution_unavailable"}], status="unavailable")
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    assert plan["field"] == [] and {row["reason"] for row in plan["dropped"]} == {"field_share_not_read"}
    lib.conn.close()


def test_a_run_with_no_routing_record_searches_openalex_alone(tmp_path):
    """An older run, or a research whose scope holds no field source: the plan is the plan it always was."""
    lib = _library(tmp_path, "no-record.sqlite")
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    assert plan["field"] == [] and plan["keyword_cap"] == lib.run["budget"]["fast_path"]["keyword_record_cap"]
    lib.conn.close()


def test_a_source_the_person_took_out_of_the_research_is_not_searched(tmp_path):
    """The record was written while the source was in the research; the research's own sources decide now."""
    lib = _library(tmp_path, "left-out.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    scope = dict(lib.store.scope(lib.rid)) | {"providers": ["openalex", "semantic_scholar"]}
    plan = fast_search.build_plan(lib.store, lib.run, scope, QUERIES)
    assert plan["field"] == []
    assert {row["reason"] for row in plan["dropped"]} == {"not_in_scope"}
    lib.conn.close()


# --- what the source really reads -----------------------------------------------------------------------------

def _sent(lib, tmp_path, plan, *, fail=False, pages=1):
    """Run the search stage with a scripted transport and return the queries it sent, in order."""
    flow, sent = _flow(lib, tmp_path), []

    async def send(run_id, connector, query, limit, page=None, **kwargs):
        sent.append((query["provider_id"], limit))
        if fail and query["provider_id"] == "pubmed":
            return SearchOutcome("failed", "rejected_not_executed", "SYNTHETIC refusal", "keyless",
                                 error="SYNTHETIC refusal")
        records = [_record(f"W{query['provider_id']}{len(sent)}{i}") for i in range(min(limit, 2))]
        cursor = "SYNTHETIC" if query["provider_id"] == "pubmed" and len(sent) < pages else None
        return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless", records=records,
                             provider_total=len(records), next_cursor=cursor)
    flow._send_search = send
    asyncio.run(asyncio.wait_for(fast_search.execute(flow, lib.run, scope_of(lib), plan, False), 5))
    return sent


def scope_of(lib):
    return lib.store.scope(lib.rid)


def test_the_field_source_is_searched_beside_the_keyword_queries(tmp_path):
    lib = _library(tmp_path, "sent.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    sent = _sent(lib, tmp_path, plan)
    assert ("pubmed", 100) in sent and any(provider == "openalex" for provider, _ in sent)
    row = lib.conn.execute("SELECT request_class, request_index, result_count, read_limit FROM search_runs"
                           " WHERE provider = 'pubmed'").fetchone()
    # Its own admission class, behind the question's requests and the keyword pages.
    assert (row["request_class"], row["request_index"]) == (fast_search.FIELD_CLASS, 0)
    assert row["result_count"] == 2
    # What the request may read in all is its own share, not the page it asked for.
    assert row["read_limit"] == plan["field"][0]["records"] == 250
    lib.conn.close()


def test_a_frozen_arxiv_field_source_sends_and_records_its_reply(tmp_path, monkeypatch):
    lib = _library(tmp_path, "arxiv-field.sqlite")
    _routing(lib, [{"provider_id": "arxiv", "reason": "share", "share": 0.9831}])
    plan = fast_search.build_plan(lib.store, lib.run, scope_of(lib), QUERIES)
    frozen = lib.store.freeze_protocol(lib.rid, 1, {"fast_path_search": plan})
    protocol = lib.store.step(lib.run["id"], "protocol", "protocol:freeze")
    lib.store.start_step(protocol["id"])
    lib.store.finish_step(protocol["id"], "succeeded", output={"protocol_revision": frozen["protocol_revision"],
                                                               "protocol_hash": frozen["hash"]})
    flow = _flow(lib, tmp_path)
    sent = []
    feed = ('<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
            '<opensearch:totalResults>1</opensearch:totalResults><entry>'
            '<id>https://arxiv.org/abs/2601.00001v1</id><title>SYNTHETIC article</title>'
            '<summary>SYNTHETIC abstract</summary><published>2026-01-02</published>'
            '</entry></feed>')

    async def reply(request):
        sent.append(request.url.params["search_query"])
        return httpx.Response(200, text=feed)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            flow.deps.http = client
            original = flow._send_search

            async def send(run_id, connector, query, limit, page=None, **kwargs):
                if connector.provider_id == "arxiv":
                    return await original(run_id, connector, query, limit, page, **kwargs)
                return SearchOutcome("zero_results", "before_send", "SYNTHETIC", "keyless")

            flow._send_search = send
            return await fast_search.execute(flow, lib.run, scope_of(lib),
                                             fast_search.stored_plan(lib.store, lib.run), False)

    monkeypatch.setattr(arxiv, "_last_request", 0.0)
    assert asyncio.run(asyncio.wait_for(run(), 5)) is None
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['field'][0]['index']}")
    assert step["status"] == "succeeded" and step["output"]["result_count"] == 1
    assert sent == [plan["field"][0]["query"]["query_text"]]
    assert lib.conn.execute("SELECT result_count FROM search_runs WHERE provider = 'arxiv'").fetchone()[0] == 1
    lib.conn.close()


@pytest.mark.parametrize("arm,provider", [("field", "arxiv"), ("broad", "scopus")])
def test_a_source_task_exception_is_recorded_and_other_sources_finish(tmp_path, arm, provider):
    lib = _library(tmp_path, f"raised-{arm}.sqlite")
    _routing(lib, [{"provider_id": "arxiv", "reason": "share", "share": 0.9831}])
    plan = fast_search.build_plan(lib.store, lib.run, scope_of(lib), QUERIES)
    spec = plan["field"].pop()
    if arm == "broad":
        spec = spec | {"query": {"provider_id": provider, "query_text": "SYNTHETIC broad"},
                       "page_records": 100}
        plan["broad"] = spec
    else:
        plan["field"] = [spec]
    flow = _flow(lib, tmp_path)

    async def send(run_id, connector, query, limit, page=None, **kwargs):
        if connector.provider_id == provider:
            raise RuntimeError("SYNTHETIC adapter raised")
        return SearchOutcome("zero_results", "before_send", "SYNTHETIC", "keyless")

    flow._send_search = send
    assert asyncio.run(asyncio.wait_for(fast_search.execute(flow, lib.run, scope_of(lib), plan, False), 5)) is None
    step = lib.store.existing_step(lib.run["id"], f"search:{spec['index']}")
    assert step["status"] == "failed"
    assert step["error_code"] == "source_task_exception"
    assert "RuntimeError" in step["error_json"] and "SYNTHETIC adapter raised" in step["error_json"]
    assert lib.store.existing_step(lib.run["id"], "search:0")["status"] == "succeeded"
    assert lib.store.run(lib.run["id"])["status"] == "running"
    lib.conn.close()


def test_discovery_completes_when_its_arxiv_field_task_raises(tmp_path, monkeypatch):
    original_route = routing.route

    def field_route(*args, **kwargs):
        result = original_route(*args, **kwargs)
        result["status"] = "read"
        result["total"] = 1
        result["fields"] = [{"field": "Physics and Astronomy", "count": 1, "share": 1.0}]
        result["chosen"] = [row for row in result["chosen"] if row["provider_id"] in ("openalex", "semantic_scholar")]
        result["chosen"].append({"provider_id": "arxiv", "reason": "share", "share": 1.0})
        result["left_out"] = [row for row in result["left_out"] if row["provider_id"] != "arxiv"]
        result["providers"] = ["openalex", "semantic_scholar", "arxiv"]
        return result

    monkeypatch.setattr(routing, "route", field_route)
    original_send = ResearchFlow._send_search

    async def send(self, run_id, connector, query, limit, page=None, **kwargs):
        if connector.provider_id == "arxiv":
            raise RuntimeError("SYNTHETIC adapter raised")
        return await original_send(self, run_id, connector, query, limit, page, **kwargs)

    monkeypatch.setattr(ResearchFlow, "_send_search", send)
    app, _ = app_for(tmp_path, monkeypatch, n=3, reading="off")
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="quick")
        assert run["status"] == "completed"
        plan = fast_search.stored_plan(app.state.store, app.state.store.run(run_id))
        (spec,) = plan["field"]
        assert spec["query"]["provider_id"] == "arxiv"
        step = app.state.store.existing_step(run_id, f"search:{spec['index']}")
        assert step["status"] == "failed" and step["error_code"] == "source_task_exception"
        assert app.state.store.existing_step(run_id, "search:0")["status"] == "succeeded"


def test_new_quick_run_searches_its_field_source(tmp_path):
    lib = _library(tmp_path, "quick-field.sqlite", effort="quick")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    sent = _sent(lib, tmp_path, plan)
    assert ("pubmed", 100) in sent
    assert plan["field"][0]["records"] == 250
    assert plan["keyword_cap"] == 750
    lib.conn.close()


def test_a_field_source_that_refuses_does_not_fail_the_search_stage(tmp_path):
    lib = _library(tmp_path, "refused.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    _sent(lib, tmp_path, plan, fail=True)
    # The source the depth added is not the question's own index: its failure is recorded and the run keeps what
    # OpenAlex brought.
    assert lib.store.run(lib.run["id"])["status"] == "running"
    row = lib.conn.execute("SELECT status FROM search_runs WHERE provider = 'pubmed'").fetchone()
    assert row["status"] == "failed"
    assert lib.conn.execute("SELECT COUNT(*) FROM search_runs WHERE provider = 'openalex'").fetchone()[0] > 0
    lib.conn.close()


def test_a_resumed_run_cannot_spend_the_share_twice(tmp_path):
    lib = _library(tmp_path, "resume.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    first = _sent(lib, tmp_path, plan)
    before = [dict(row) for row in lib.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]
    again = _sent(lib, tmp_path, plan)
    after = [dict(row) for row in lib.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]
    # The second pass reads its own rows back and sends nothing again.
    assert first and not again and after == before
    lib.conn.close()


def test_a_page_this_run_already_recorded_is_not_counted_against_the_share_twice(tmp_path):
    """A run stopped between two pages: the walk reads the first page back and the rest of the share is still 150."""
    lib = _library(tmp_path, "partial.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    spec = plan["field"][0]
    step = lib.store.step(lib.run["id"], f"search:{spec['index']}", "provider_search:pubmed")
    lib.store.start_step(step["id"])
    lib.store.add_search_run(research_id=lib.rid, run_id=lib.run["id"], step_id=step["id"], scope_revision=1,
                             provider="pubmed", query_text=spec["query"]["query_text"],
                             request_description="SYNTHETIC", access_mode="open", status="completed",
                             result_count=100, page_limit=100, request_class=fast_search.FIELD_CLASS,
                             request_index=0, returned_count=100)
    lib.store.finish_step(step["id"], "succeeded", output={
        "result_count": 100, "read_total": 100, "provider_total": 400, "next_cursor": "SYNTHETIC",
        "fast_path_request": {"class": fast_search.FIELD_CLASS, "request_index": 0, "limit": 100}})
    pubmed = [limit for provider, limit in _sent(lib, tmp_path, plan, pages=9) if provider == "pubmed"]
    # 250 records in all: 100 are read, so the next pages ask for 100 and then 50, never 50 and 0.
    assert pubmed == [100, 50]
    lib.conn.close()


# --- what the person is shown --------------------------------------------------------------------------------

def _body(field=None, dropped=(), not_compiled=None, left_out=()):
    """A frozen protocol body holding just the two blocks the view reads."""
    plan = {"version": 1, "keywords": [], "dropped": list(dropped)}
    if field is not None:
        plan["field"] = field
    if not_compiled:
        plan["field_not_compiled"] = not_compiled
    return {"fast_path_search": plan,
            "source_routing": {"status": "read", "chosen": [{"provider_id": "openalex", "reason": "always"}],
                               "left_out": list(left_out)}}


def _searched(lib, provider, records, klass=2, status="completed", page=0):
    step = lib.store.step(lib.run["id"], f"search:field:{provider}:page:{page}", "provider_search")
    lib.store.start_step(step["id"])
    lib.store.add_search_run(research_id=lib.rid, run_id=lib.run["id"], step_id=step["id"], scope_revision=1,
                             provider=provider, query_text="SYNTHETIC gamma", request_description="SYNTHETIC",
                             access_mode="open", status=status, result_count=records, page_limit=250,
                             request_class=klass, request_index=0, returned_count=records)


def test_the_searched_field_source_is_shown_with_its_share_and_what_came_back(tmp_path):
    lib = _library(tmp_path, "view-searched.sqlite")
    _searched(lib, "pubmed", 37)
    body = _body(field=[{"index": 1, "query": QUERIES[1], "records": 250, "request_index": 0,
                         "share": 0.42, "independent": True}])
    view = views.field_search_view(lib.store, lib.run, body)
    assert view["rows"] == [{"provider_id": "pubmed", "share": 0.42, "independent": True, "state": "searched",
                            # No heading of its own: this plan froze no MeSH expansion for the query.
                            "records": 37, "failed_requests": 0, "reason": None, "headings": None}]
    lib.conn.close()


def test_a_planned_field_request_with_no_reply_is_not_shown_as_searched(tmp_path):
    lib = _library(tmp_path, "view-planned.sqlite")
    body = _body(field=[{"index": 1, "query": QUERIES[1], "records": 250, "request_index": 0,
                         "share": 0.42, "independent": True}])
    row = views.field_search_view(lib.store, lib.run, body)["rows"][0]
    assert (row["state"], row["records"], row["reason"]) == ("planned", None, "no_reply_recorded")
    lib.conn.close()


def test_a_source_the_depth_did_not_reach_keeps_its_reason_and_its_share(tmp_path):
    lib = _library(tmp_path, "view-not-chosen.sqlite")
    _searched(lib, "pubmed", 12)
    body = _body(field=[{"index": 1, "query": QUERIES[1], "records": 250, "request_index": 0,
                         "share": 0.42, "independent": True}],
                 dropped=[{"index": 2, "query": QUERIES[2], "reason": "after_the_depth_s_field_source"}],
                 not_compiled={"ieee_xplore": "query_not_compiled"},
                 left_out=[{"provider_id": "arxiv", "reason": "share_below", "share": 0.11}])
    rows = {row["provider_id"]: row for row in views.field_search_view(lib.store, lib.run, body)["rows"]}
    assert (rows["arxiv"]["state"], rows["arxiv"]["reason"]) == ("not_chosen", "after_the_depth_s_field_source")
    assert rows["arxiv"]["share"] == 0.11
    assert rows["ieee_xplore"]["state"] == "query_not_compiled"
    lib.conn.close()


def test_a_run_whose_plan_holds_no_field_block_reports_nothing(tmp_path):
    lib = _library(tmp_path, "view-older.sqlite")
    assert views.field_search_view(lib.store, lib.run, _body()) is None
    assert views.field_search_view(lib.store, lib.run, None) is None
    lib.conn.close()


def test_a_run_reads_back_the_plan_it_froze_itself(tmp_path):
    """A later discovery run of the same revision freezes another plan; a run that froze none reads neither."""
    lib = _library(tmp_path, "view-own.sqlite")
    mine = lib.store.freeze_protocol(lib.rid, 1, _body(field=[{"index": 1, "query": QUERIES[1], "records": 250,
                                                               "request_index": 0, "share": 0.4,
                                                               "independent": True}]))
    assert fast_search.frozen_body(lib.store, lib.run) is None  # this run has frozen no protocol step yet
    step = lib.store.step(lib.run["id"], "protocol", "protocol:freeze")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "succeeded", output={"protocol_revision": mine["protocol_revision"],
                                                           "protocol_hash": mine["hash"]})
    later = lib.store.freeze_protocol(lib.rid, 1, _body(field=[]), reason="later_discovery_run")
    assert later["hash"] != mine["hash"]
    # The later run's plan is the research's current one; this run still reads its own.
    body = fast_search.frozen_body(lib.store, lib.run)
    assert body["fast_path_search"]["field"][0]["query"]["provider_id"] == "pubmed"
    assert views.field_search_view(lib.store, lib.run, body)["rows"][0]["provider_id"] == "pubmed"
    lib.conn.close()


def test_a_source_whose_later_page_failed_is_searched_and_says_how_many_pages_did_not_answer(tmp_path):
    lib = _library(tmp_path, "view-partial-failure.sqlite")
    _searched(lib, "pubmed", 100, page=0)
    _searched(lib, "pubmed", 0, status="failed", page=1)
    body = _body(field=[{"index": 1, "query": QUERIES[1], "records": 250, "request_index": 0,
                         "share": 0.42, "independent": True}])
    row = views.field_search_view(lib.store, lib.run, body)["rows"][0]
    assert (row["state"], row["records"], row["failed_requests"]) == ("searched", 100, 1)
    lib.conn.close()


@pytest.mark.parametrize("status,state", [("completed", "searched"), ("zero_results", "searched"),
                                          ("failed", "request_failed")])
def test_a_search_that_found_nothing_is_not_shown_as_a_request_that_never_went_out(tmp_path, status, state):
    lib = _library(tmp_path, f"view-{status}.sqlite")
    _searched(lib, "pubmed", 0 if status != "completed" else 5, status=status)
    body = _body(field=[{"index": 1, "query": QUERIES[1], "records": 250, "request_index": 0,
                         "share": 0.42, "independent": True}])
    row = views.field_search_view(lib.store, lib.run, body)["rows"][0]
    assert row["state"] == state
    assert row["reason"] == (None if state == "searched" else status)
    lib.conn.close()

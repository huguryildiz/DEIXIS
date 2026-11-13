"""The broad index in both of its roles: the second index a depth pays for, and the one sub-topic search of it.

Synthetic throughout — no live app, provider or model. What is guarded here is that the index is reached by the
depth's budget and the arm the run froze and by nothing the question's field distribution says, that it reads
only its own share in pages its adapter really serves, that a paid sub-topic request is planned only for a part
the question itself states and sent only while that part is still unmet after the field source, that its query is
reported on its own arm and nowhere else, and that every reason it was not searched is recorded.
"""

import asyncio
from types import SimpleNamespace

import pytest

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers import facade, scopus
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.providers.registry import CONNECTORS, broad_index_providers, search_providers
from deixis.runtime.config import Settings
from deixis.storage import db
from deixis.workflow.run import fast_path, views
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store
from deixis.workflow.search import protocol, search as fast_search, search_plan, small_batch
from test_fast_path_clock import FakeClock

QUESTION = "SYNTHETIC broad index question about SYNTHETICPART"
SUBTOPIC = "SYNTHETICPART"  # a part the question itself states, so the paid request's own gate admits it
QUERIES = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha", "origin": "model"},
           {"provider_id": "pubmed", "query_text": "SYNTHETIC gamma", "origin": "model"},
           {"provider_id": "biorxiv", "query_text": "SYNTHETIC delta", "origin": "model"},
           {"provider_id": "scopus", "query_text": "SYNTHETIC epsilon", "origin": "model"}]
# The focused query the plan's named part is rendered as for the broad index: what a sub-topic search sends.
FOCUSED = {"provider_id": "scopus", "query_text": f"SYNTHETIC epsilon AND {SUBTOPIC}", "origin": "model",
           "role": "focused", "focused": {"term": SUBTOPIC, "gap": "SYNTHETIC gap sentence"}}
SUBTOPIC_QUERIES = [*QUERIES, FOCUSED]
VOCABULARY = {"terms": [{"phrase": "SYNTHETIC alpha", "root": "SYNTHETIC alpha"}],
              "search_query": {"answer": {"focused": [{"term": SUBTOPIC, "gap": "SYNTHETIC gap sentence"}]}}}
SOURCES = ["openalex", "semantic_scholar", "pubmed", "biorxiv", "scopus"]


@pytest.fixture(autouse=True)
def _scopus_key(monkeypatch):
    monkeypatch.setenv("SCOPUS_API_KEY", "SYNTHETIC-scopus-key")


def _library(tmp_path, name="library.sqlite", effort="detailed", arm="conditional", sources=None,
             subtopic_arm="conditional"):
    conn = db.connect(tmp_path / name)
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research(QUESTION, "academic", effort, list(sources or SOURCES), "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
    # These arm mechanics also protect policies frozen before shared search.
    budget["fast_path"] = fast_path.freeze_budget(budget, effort, broad_index_arm=arm,
                                                 subtopic_arm=subtopic_arm, uniform_search=False)
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


def _plan(lib, queries=None, scope=None, vocabulary=None):
    return fast_search.build_plan(lib.store, lib.run, scope or lib.store.scope(lib.rid), queries or QUERIES,
                                  vocabulary=vocabulary)


def _record(identity, carried=""):
    return ProviderRecord(provider_record_id=identity, title=f"SYNTHETIC {identity}{carried}", authors=[], year=2026,
                          venue=None, publication_type="article", doi=None, landing_url=None, oa_pdf_url=None,
                          oa_pdf_version=None, version_label="publishedVersion",
                          abstract=f"SYNTHETIC abstract {identity}", abstract_origin="provider_scopus",
                          identifiers={"scopus_id": identity}, raw={"id": identity})


def _flow(lib, tmp_path):
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock,
                                        settings=Settings(data_dir=tmp_path / "data"), local_embedder=None))
    fast_path.enter_stage(lib.store, lib.run, "search")
    return flow


def _sent(lib, tmp_path, plan, *, fail=False, pages=1, covers=(), retry=False, refused=()):
    """Run the search stage with a scripted transport and return the queries it sent, in order.

    `covers` are the providers whose records carry the question's named part, so the sub-topic gate reads it as
    already met from those pages alone; `refused` are the providers whose every request is turned down.
    """
    flow, sent = _flow(lib, tmp_path), []
    refused = {*refused, *(("scopus",) if fail else ())}

    async def send(run_id, connector, query, limit, page=None, **kwargs):
        sent.append((query["provider_id"], limit))
        if query["provider_id"] in refused:
            return SearchOutcome("entitlement_missing", "rejected_not_executed", "SYNTHETIC refusal", "api_key",
                                 error="SYNTHETIC refusal")
        carried = f" {SUBTOPIC}" if query["provider_id"] in covers else ""
        records = [_record(f"W{query['provider_id']}{len(sent)}{i}", carried)
                   for i in range(min(limit, 2))]
        scopus_pages = sum(1 for provider, _ in sent if provider == "scopus")
        cursor = "SYNTHETIC" if query["provider_id"] == "scopus" and scopus_pages < pages else None
        return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless", records=records,
                             provider_total=len(records), next_cursor=cursor)
    flow._send_search = send
    asyncio.run(asyncio.wait_for(fast_search.execute(flow, lib.run, lib.store.scope(lib.rid), plan, retry), 5))
    return sent


# --- which connector, and who may be given it ----------------------------------------------------------------

def test_the_broad_index_is_admitted_only_where_a_depth_s_own_queries_are_compiled():
    """Every other reader of a searched provider list asks a question this index is not part of."""
    assert broad_index_providers() == ["scopus"]
    assert "scopus" not in search_providers(SOURCES)
    assert "scopus" in search_providers(SOURCES, broad=True)
    # It is still not searched for a question like the routed sources: nothing else reads it as one.
    assert CONNECTORS["scopus"].sw_searchable is False


def test_the_contract_declares_the_record_view_as_a_string_option():
    """The view the search asks for goes through the connector's declared options, so the request is not refused
    before it is sent."""
    descriptor = facade.descriptor_for(CONNECTORS["scopus"], 0)
    (option,) = [o for o in descriptor.endpoints[0].options if o.name == "view"]
    assert option.value_type == "str" and CONNECTORS["scopus"].sw_options["view"] == scopus.COMPLETE_VIEW


# --- when the depth plans it ---------------------------------------------------------------------------------

def test_a_depth_that_pays_for_a_second_index_takes_its_records_off_the_keyword_cap(tmp_path):
    lib = _library(tmp_path)
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    policy = lib.run["budget"]["fast_path"]
    spec = plan["broad"]
    assert (spec["query"]["provider_id"], spec["records"], spec["request_index"]) == ("scopus", 100, 0)
    # One page of it asks for what its adapter really serves, not the keyword page size: a page that asked for
    # more would spend the whole share at once.
    assert spec["page_records"] == scopus.MAX_RESULTS == 25
    assert plan["keyword_cap"] == (policy["keyword_record_cap"] - policy["field_search"]["records"]
                                  - policy["broad_index"]["records"])
    # Its query is reported on its own arm, never also as a field source that lost its place.
    assert "scopus" not in {row["query"]["provider_id"] for row in plan["dropped"]}
    assert "broad_not_sent" not in plan
    lib.conn.close()


def test_the_conditional_arm_sends_nothing_where_the_run_plans_an_independent_field_source(tmp_path):
    """What the second index is for is an index of this run's own, and this run already has one."""
    lib = _library(tmp_path, "independent.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert "broad" not in plan
    assert plan["broad_not_sent"] == {"provider_id": "scopus", "reason": "independent_field_source_planned"}
    assert plan["keyword_cap"] == (lib.run["budget"]["fast_path"]["keyword_record_cap"]
                                  - lib.run["budget"]["fast_path"]["field_search"]["records"])
    lib.conn.close()


def test_a_field_source_searched_through_another_host_is_not_an_index_of_this_run_s_own(tmp_path):
    """bioRxiv's query goes to OpenAlex, so the run has no second independent index until this one is searched."""
    lib = _library(tmp_path, "lineage.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert plan["field"][0]["independent"] is False and plan["broad"]["query"]["provider_id"] == "scopus"
    lib.conn.close()


def test_a_distribution_that_could_not_be_read_still_searches_the_second_index(tmp_path):
    """No share was read, so no field source is the one that fits best and the run plans none of its own."""
    lib = _library(tmp_path, "unread.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "distribution_unavailable"}], status="unavailable")
    plan = _plan(lib)
    assert plan["field"] == [] and plan["broad"]["query"]["provider_id"] == "scopus"
    lib.conn.close()


def test_the_always_arm_searches_it_beside_an_independent_field_source(tmp_path):
    """The arm the design's own field test needs: both indexes on one question, without disabling either by hand."""
    lib = _library(tmp_path, "always.sqlite", arm="always")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert plan["field"][0]["query"]["provider_id"] == "pubmed"
    assert (plan["broad"]["query"]["provider_id"], plan["broad"]["arm"]) == ("scopus", "always")
    lib.conn.close()


def test_the_off_arm_freezes_no_rule_and_plans_nothing(tmp_path):
    """A run queued with the arm off, and every run queued before the rule, sends and reports nothing."""
    lib = _library(tmp_path, "off.sqlite", arm="off", subtopic_arm="off")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert "broad_index" not in lib.run["budget"]["fast_path"]
    assert "subtopic_search" not in lib.run["budget"]["fast_path"]
    assert "broad" not in plan and "broad_not_sent" not in plan
    assert "subtopic" not in plan and "subtopic_not_sent" not in plan
    assert fast_path.broad_index(lib.run["budget"]) is None
    assert fast_path.subtopic_search(lib.run["budget"]) is None
    assert views.broad_index_view(lib.store, lib.run, {"fast_path_search": plan}) is None
    lib.conn.close()


@pytest.mark.parametrize("effort", ["quick", "standard"])
def test_a_depth_that_pays_for_no_second_index_keeps_the_whole_share(tmp_path, effort):
    lib = _library(tmp_path, f"{effort}.sqlite", effort=effort)
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert plan["broad_not_sent"]["reason"] == "depth_pays_for_no_broad_index"
    lib.conn.close()


def test_shared_quick_policy_can_plan_the_conditional_second_index(tmp_path):
    lib = _library(tmp_path, "shared-quick.sqlite", effort="quick")
    lib.run["budget"]["fast_path"] = fast_path.freeze_budget({}, "quick", broad_index_arm="conditional")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert plan["broad"]["records"] == 100
    assert plan["keyword_cap"] == 650
    lib.conn.close()


def test_a_second_index_outside_the_research_s_sources_is_not_searched(tmp_path):
    lib = _library(tmp_path, "scope.sqlite", sources=["openalex", "semantic_scholar", "biorxiv"])
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    assert plan["broad_not_sent"] == {"provider_id": "scopus", "reason": "not_in_scope"}
    lib.conn.close()


def test_a_second_index_with_no_key_is_not_searched(tmp_path, monkeypatch):
    lib = _library(tmp_path, "keyless.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    assert _plan(lib)["broad_not_sent"] == {"provider_id": "scopus", "reason": "not_configured"}
    lib.conn.close()


def test_a_person_who_left_it_out_of_their_saved_plan_is_obeyed(tmp_path):
    lib = _library(tmp_path, "excluded.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    scope = dict(lib.store.scope(lib.rid)) | {
        "user_plan": {"providers": ["openalex", "semantic_scholar", "crossref"]}}
    assert _plan(lib, scope=scope)["broad_not_sent"]["reason"] == "excluded_by_user"
    lib.conn.close()


def test_a_second_index_the_query_limit_left_without_a_query_says_so(tmp_path):
    """The compiler stops at the run's request limit; a source it left with none is recorded, never dropped."""
    lib = _library(tmp_path, "uncompiled.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib, queries=[q for q in QUERIES if q["provider_id"] != "scopus"])
    assert plan["broad_not_sent"] == {"provider_id": "scopus", "reason": "query_not_compiled"}
    lib.conn.close()


# --- what it really reads ------------------------------------------------------------------------------------

def test_the_second_index_reads_its_share_in_the_pages_its_adapter_serves(tmp_path):
    lib = _library(tmp_path, "pages.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    sent = _sent(lib, tmp_path, plan, pages=4)
    # Four pages of 25, never a page asking for the keyword page size.
    assert [limit for provider, limit in sent if provider == "scopus"] == [25, 25, 25, 25]
    row = lib.conn.execute("SELECT request_class, request_index, read_limit FROM search_runs"
                           " WHERE provider = 'scopus' ORDER BY rowid").fetchone()
    # Its own admission class, behind the field source's, and its whole share as what the request may read.
    assert (row["request_class"], row["request_index"]) == (fast_search.BROAD_CLASS, 0)
    assert row["read_limit"] == plan["broad"]["records"] == 100
    lib.conn.close()


def test_a_second_index_that_refuses_does_not_fail_the_search_stage(tmp_path):
    """Off a network Elsevier entitles for the view that carries abstracts, the refusal is recorded and that is all."""
    lib = _library(tmp_path, "refused.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    _sent(lib, tmp_path, plan, fail=True)
    assert lib.store.run(lib.run["id"])["status"] == "running"
    rows = lib.conn.execute("SELECT status FROM search_runs WHERE provider = 'scopus'").fetchall()
    # One refusal, and nothing sent again after it.
    assert [row["status"] for row in rows] == ["entitlement_missing"]
    assert lib.conn.execute("SELECT COUNT(*) FROM search_runs WHERE provider = 'openalex'").fetchone()[0] > 0
    view = views.broad_index_view(lib.store, lib.run, {"fast_path_search": plan})
    assert (view["state"], view["reason"], view["records_found"]) == ("request_failed", "entitlement_missing", 0)
    lib.conn.close()


def test_a_resumed_run_cannot_spend_the_second_index_s_share_twice(tmp_path):
    lib = _library(tmp_path, "resume.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    first = _sent(lib, tmp_path, plan, pages=4)
    before = [dict(row) for row in lib.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]
    again = _sent(lib, tmp_path, plan, pages=4)
    after = [dict(row) for row in lib.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]
    assert first and not again and after == before
    lib.conn.close()


# --- what is recorded of it ----------------------------------------------------------------------------------

def test_the_sent_plan_names_the_second_index_on_its_own_arm_and_no_watch_follows_it(tmp_path):
    """A watch asks its provider for what is new by date; this index is searched for one run's breadth."""
    lib = _library(tmp_path, "sent-plan.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    body = {"compiled_queries": QUERIES, "fast_path_search": plan}
    (row,) = [r for r in fast_search.sent_plan(body) if r["arm"] == "broad_index"]
    assert (row["provider_id"], row["query_text"]) == ("scopus", "SYNTHETIC epsilon")
    assert row["watchable"] is False and row["key"] == f"search:{plan['broad']['index']}"
    lib.conn.close()


def test_the_protocol_names_the_second_index_among_the_databases_searched(tmp_path):
    """It is a database this run searched, not a source kept only to verify a known DOI."""
    lib = _library(tmp_path, "protocol.sqlite")
    routing_record = _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    body = protocol.build_protocol(lib.store.scope(lib.rid), lib.run["budget"], None, QUERIES, "SYNTHETIC",
                                   Settings(data_dir=tmp_path / "data"), routing=routing_record,
                                   fast_path_search=plan)
    assert "scopus" in body["providers"] and "scopus" not in body["verification_providers"]
    lib.conn.close()


def test_unsent_scopus_is_removed_only_from_a_shared_search_protocol(tmp_path):
    lib = _library(tmp_path, "protocol-policy.sqlite")
    routing = _routing(lib, [{"provider_id": "scopus", "reason": "share", "share": 0.9}])
    plan = {"broad": None, "subtopic": None}
    scope = lib.store.scope(lib.rid)
    settings = Settings(data_dir=tmp_path / "data")
    old = protocol.build_protocol(scope, lib.run["budget"], None, QUERIES, "SYNTHETIC", settings,
                                  routing=routing, fast_path_search=plan)
    shared_budget = lib.run["budget"] | {"fast_path": fast_path.freeze_budget(lib.run["budget"], "detailed")}
    shared = protocol.build_protocol(scope, shared_budget, None, QUERIES, "SYNTHETIC", settings,
                                     routing=routing, fast_path_search=plan)
    assert "scopus" in old["providers"]
    assert "scopus" not in shared["providers"]
    lib.conn.close()


def test_the_run_view_reports_what_the_second_index_brought(tmp_path):
    lib = _library(tmp_path, "view.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib)
    before = views.broad_index_view(lib.store, lib.run, {"fast_path_search": plan})
    # Planned and nothing recorded for it yet: the view says that, and claims no records.
    assert (before["state"], before["records_found"], before["arm"]) == ("planned", None, "conditional")
    _sent(lib, tmp_path, plan, pages=2)
    after = views.broad_index_view(lib.store, lib.run, {"fast_path_search": plan})
    assert (after["state"], after["provider_id"], after["failed_requests"]) == ("searched", "scopus", 0)
    assert after["records_found"] == 4 and after["records"] == 100
    lib.conn.close()


def test_a_second_index_that_was_not_sent_is_reported_with_its_reason(tmp_path):
    lib = _library(tmp_path, "not-sent.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    view = views.broad_index_view(lib.store, lib.run, {"fast_path_search": _plan(lib)})
    assert (view["state"], view["reason"], view["records_found"]) == (
        "not_sent", "independent_field_source_planned", None)
    assert view["rule"] == fast_path.BROAD_INDEX_RULE
    lib.conn.close()


# --- the adapter ---------------------------------------------------------------------------------------------

def test_only_the_complete_view_carries_an_abstract_and_every_author():
    """The STANDARD view returns no abstract and one author, so a record read with it claims neither more."""
    entry = {"dc:identifier": "SCOPUS_ID:1", "dc:title": "SYNTHETIC", "dc:description": " SYNTHETIC abstract ",
             "author": [{"authname": "Yıldız H.U."}, {"authname": " Gedik B. "}]}
    record = scopus._record(entry)
    assert (record.abstract, record.abstract_origin) == ("SYNTHETIC abstract", scopus.ABSTRACT_ORIGIN)
    assert record.authors == ["Yıldız H.U.", "Gedik B."]
    # An author the view names in parts rather than in `authname` is read from those parts.
    parts = scopus._record({"dc:identifier": "SCOPUS_ID:3", "dc:title": "SYNTHETIC",
                            "author": [{"surname": "Yıldız", "given-name": "H.U."}, {"authname": "Gedik B."}]})
    assert parts.authors == ["Yıldız H.U.", "Gedik B."]
    bare = scopus._record({"dc:identifier": "SCOPUS_ID:2", "dc:title": "SYNTHETIC", "dc:creator": "Yıldız H.U."})
    assert (bare.abstract, bare.abstract_origin, bare.authors) == (None, None, ["Yıldız H.U."])


def test_an_author_list_in_another_shape_ends_the_read_rather_than_losing_a_name():
    """A name the reply holds in a shape the parser does not read would vanish from every citation of the record."""
    import httpx

    payload = {"search-results": {"opensearch:totalResults": "1",
                                  "entry": [{"dc:identifier": "SCOPUS_ID:1", "dc:title": "SYNTHETIC",
                                             "dc:creator": "Alice", "author": ["Alice", "Bob"]}]}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await scopus.search(client, "SYNTHETIC", 25, api_key="SYNTHETIC-key",
                                       view=scopus.COMPLETE_VIEW, max_rate_limit_retries=0)
    outcome = asyncio.run(run())
    assert outcome.status == "parse_error" and outcome.records == []


def test_an_author_no_documented_field_names_ends_the_read(tmp_path):
    """Reading on would drop that author from the record and from every citation of it."""
    import httpx

    payload = {"search-results": {"opensearch:totalResults": "1",
                                  "entry": [{"dc:identifier": "SCOPUS_ID:1", "dc:title": "SYNTHETIC",
                                             "dc:creator": "Alice",
                                             "author": [{"author-url": "SYNTHETIC"}, {"authname": "Bob"}]}]}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await scopus.search(client, "SYNTHETIC", 25, api_key="SYNTHETIC-key",
                                       view=scopus.COMPLETE_VIEW, max_rate_limit_retries=0)
    outcome = asyncio.run(run())
    assert outcome.status == "parse_error" and outcome.records == []


def test_the_adapter_refuses_a_view_it_does_not_declare():
    with pytest.raises(ValueError):
        asyncio.run(scopus.search(None, "SYNTHETIC", 25, api_key="SYNTHETIC-key", view="SYNTHETIC"))


# --- the one sub-topic search of that index -------------------------------------------------------------------

def _standard(tmp_path, name, **changes):
    """A Standard library: the depth that searches no second index of its own and pays for one sub-topic search."""
    return _library(tmp_path, name, effort="standard", **changes)


def test_the_question_s_own_part_is_what_the_paid_request_is_planned_for():
    """The plan's parts are a model's reading of the first page of results, so the link to the question is
    checked in code: nothing is spent on a sub-problem only the model inferred."""
    voc = {"terms": [{"phrase": "underwater acoustic", "root": "underwater acoustic"}]}
    assert search_plan.question_subtopic("DBR and VBF routing in underwater networks", voc, "routing") is True
    # A term the question does not say, but one of the words the question was read for.
    assert search_plan.question_subtopic("DBR and VBF comparison", voc, "underwater acoustic") is True
    assert search_plan.question_subtopic("DBR and VBF comparison", voc, "energy harvesting") is False
    # Its own words, not inside a longer one.
    assert search_plan.question_subtopic("DBR and VBF route comparison", voc, "rout") is False
    assert search_plan.question_subtopic("DBR and VBF comparison", voc, "  ") is False


def test_standard_plans_one_sub_topic_search_whose_records_come_off_no_cap(tmp_path):
    """Whether it is sent is decided after the keyword loop has ended, so its records are its own: taken off that
    loop's cap they would be lost on every question where nothing is sent, and the arms would read different
    keyword totals."""
    lib = _standard(tmp_path, "subtopic.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    policy = lib.run["budget"]["fast_path"]
    spec = plan["subtopic"]
    assert (spec["query"]["provider_id"], spec["records"], spec["focused"]["term"]) == ("scopus", 25, SUBTOPIC)
    assert plan["keyword_cap"] == policy["keyword_record_cap"] - policy["field_search"]["records"]
    off_lib = _standard(tmp_path, "subtopic-off.sqlite", subtopic_arm="off")
    _routing(off_lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    off = _plan(off_lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    assert off["keyword_cap"] == plan["keyword_cap"] and "subtopic" not in off
    off_lib.conn.close()
    # Standard searches no second index of its own, and the arm says so rather than staying silent.
    assert plan["broad_not_sent"]["reason"] == "depth_pays_for_no_broad_index"
    # Every query this arm owns is reported on it, never as a field source that lost its place.
    assert "scopus" not in {row["query"]["provider_id"] for row in plan["dropped"]}
    lib.conn.close()


def test_a_depth_that_searches_that_index_on_its_own_sends_no_sub_topic_search(tmp_path):
    """One query per source stands: Deep already searches it, so it does not also ask it about a part."""
    lib = _library(tmp_path, "both.sqlite")
    _routing(lib, [{"provider_id": "biorxiv", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    assert plan["broad"]["query"]["provider_id"] == "scopus"
    assert plan["subtopic_not_sent"] == {"provider_id": "scopus", "reason": "broad_index_planned"}
    lib.conn.close()


def test_quick_pays_for_no_sub_topic_search(tmp_path):
    lib = _library(tmp_path, "quick-sub.sqlite", effort="quick")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    assert plan["subtopic_not_sent"]["reason"] == "depth_pays_for_no_subtopic_search"
    lib.conn.close()


def test_no_field_source_leaves_the_condition_nothing_to_be_read_after(tmp_path):
    """The design's condition is what is still unmet **after** the field source; with none there is no after."""
    lib = _standard(tmp_path, "no-field.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "distribution_unavailable"}], status="unavailable")
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    assert plan["field"] == []
    assert plan["subtopic_not_sent"] == {"provider_id": "scopus", "reason": "no_field_source_planned"}
    lib.conn.close()


def test_a_plan_that_named_no_part_sends_nothing(tmp_path):
    lib = _standard(tmp_path, "unnamed.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary={"terms": [], "search_query": {"answer": {}}})
    assert plan["subtopic_not_sent"]["reason"] == "no_subtopic_named"
    lib.conn.close()


def test_a_part_only_the_model_inferred_sends_nothing(tmp_path):
    """A part no word of the question states is the model's own reading, and no paid request goes out for it."""
    lib = _standard(tmp_path, "inferred.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    vocabulary = {"terms": [{"phrase": "SYNTHETIC alpha", "root": "SYNTHETIC alpha"}],
                  "search_query": {"answer": {"focused": [{"term": "SYNTHETICOTHER", "gap": "SYNTHETIC"}]}}}
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=vocabulary)
    assert plan["subtopic_not_sent"]["reason"] == "subtopic_not_in_question"
    lib.conn.close()


def test_a_named_part_the_compiler_left_without_a_query_says_that_and_not_that_none_was_named(tmp_path):
    """`focused_record` keeps the budget-or-syntax reason; this record must not call it a part nobody named."""
    lib = _standard(tmp_path, "uncompiled-sub.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, QUERIES, vocabulary=VOCABULARY)  # no focused query was rendered for the index
    assert plan["subtopic_not_sent"] == {"provider_id": "scopus", "reason": "query_not_compiled"}
    lib.conn.close()


@pytest.mark.parametrize("change,reason", [
    ({"sources": ["openalex", "semantic_scholar", "pubmed"]}, "not_in_scope"),
])
def test_a_sub_topic_search_outside_the_research_s_sources_is_not_planned(tmp_path, change, reason):
    lib = _standard(tmp_path, "scope-sub.sqlite", **change)
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    assert plan["subtopic_not_sent"]["reason"] == reason
    lib.conn.close()


def test_a_sub_topic_search_with_no_key_is_not_planned(tmp_path, monkeypatch):
    lib = _standard(tmp_path, "keyless-sub.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    assert _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)["subtopic_not_sent"]["reason"] == "not_configured"
    lib.conn.close()


# --- the gate, read after the field source --------------------------------------------------------------------

def test_the_sub_topic_is_asked_once_when_the_records_do_not_carry_it(tmp_path):
    lib = _standard(tmp_path, "gate-open.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    sent = _sent(lib, tmp_path, plan)
    # One request, for the 25 records the plan reserved, and no second one.
    assert [limit for provider, limit in sent if provider == "scopus"] == [25]
    row = lib.conn.execute("SELECT request_class, request_index, read_limit, page_limit FROM search_runs"
                           " WHERE provider = 'scopus'").fetchone()
    assert (row["request_class"], row["request_index"]) == (fast_search.BROAD_CLASS, 0)
    assert row["read_limit"] == row["page_limit"] == 25
    view = views.broad_index_view(lib.store, lib.run, {"fast_path_search": plan})
    assert (view["role"], view["subtopic"], view["state"]) == ("subtopic", SUBTOPIC, "searched")
    lib.conn.close()


def test_a_part_the_records_already_carry_is_no_gap_and_nothing_is_sent(tmp_path):
    lib = _standard(tmp_path, "gate-met.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    sent = _sent(lib, tmp_path, plan, covers=("openalex",))
    assert not [p for p, _ in sent if p == "scopus"]
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['subtopic']['index']}")
    assert (step["status"], step["error_code"]) == ("cancelled", "gap_already_met")
    # What the gate read, and over which queries' pages, so the reading can be checked rather than guessed at.
    gate = step["output"]["gate"]
    assert gate["covered"] is True and gate["held"] is True and gate["query_indexes"]
    view = views.broad_index_view(lib.store, lib.run, {"fast_path_search": plan})
    assert (view["state"], view["reason"], view["role"]) == ("not_sent", "gap_already_met", "subtopic")
    lib.conn.close()


def test_the_gate_reads_the_field_source_s_own_pages_too(tmp_path):
    """The design's condition is what is still unmet after the field source, so what that source brought counts."""
    lib = _standard(tmp_path, "gate-field.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    sent = _sent(lib, tmp_path, plan, covers=("pubmed",))
    assert not [p for p, _ in sent if p == "scopus"]
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['subtopic']['index']}")
    assert step["error_code"] == "gap_already_met"
    assert plan["field"][0]["index"] in step["output"]["gate"]["query_indexes"]
    lib.conn.close()


def test_the_always_arm_sends_whatever_the_gate_read(tmp_path):
    """The measurement's control arm: without it, `always` would send nothing on exactly the questions
    `conditional` sends nothing on and the two could not be told apart."""
    lib = _standard(tmp_path, "always-sub.sqlite", subtopic_arm="always")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    sent = _sent(lib, tmp_path, plan, covers=("openalex", "pubmed"))
    assert [limit for provider, limit in sent if provider == "scopus"] == [25]
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['subtopic']['index']}")
    assert step["output"]["gate"] == {"field_pages_answered": 1, "field_pages_failed": 0,
                                     "covered": True, "query_indexes": step["output"]["gate"]["query_indexes"],
                                      "held": False}
    lib.conn.close()


def test_a_resumed_run_cannot_send_the_sub_topic_search_twice(tmp_path):
    lib = _standard(tmp_path, "resume-sub.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    first = _sent(lib, tmp_path, plan)
    before = [dict(row) for row in lib.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]
    again = _sent(lib, tmp_path, plan)
    after = [dict(row) for row in lib.conn.execute("SELECT * FROM search_runs ORDER BY rowid")]
    assert first and not again and after == before
    lib.conn.close()


def test_the_sent_plan_names_the_sub_topic_search_on_its_own_arm_and_no_watch_follows_it(tmp_path):
    lib = _standard(tmp_path, "sent-sub.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    body = {"compiled_queries": SUBTOPIC_QUERIES, "fast_path_search": plan}
    (row,) = [r for r in fast_search.sent_plan(body) if r["arm"] == "subtopic"]
    assert row["provider_id"] == "scopus" and row["query_text"] == FOCUSED["query_text"]
    assert row["watchable"] is False and row["key"] == f"search:{plan['subtopic']['index']}"
    lib.conn.close()


def test_the_keyword_cap_does_not_cancel_the_sub_topic_s_own_reservation(tmp_path):
    """Its 25 records are its own: a keyword arm that spent its cap takes nothing from them."""
    lib = _standard(tmp_path, "cap-sub.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    # Two keyword queries, so the first spends the cap while the second has not started: that is the loop's own
    # `record_cap` exit, which must not reach this request.
    queries = [QUERIES[0], {"provider_id": "openalex", "query_text": "SYNTHETIC zeta", "origin": "model"},
               *QUERIES[1:], FOCUSED]
    plan = _plan(lib, queries, vocabulary=VOCABULARY) | {"keyword_cap": 1}
    sent = _sent(lib, tmp_path, plan)
    assert [limit for provider, limit in sent if provider == "scopus"] == [25]
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['subtopic']['index']}")
    assert step["status"] == "succeeded"
    lib.conn.close()


def test_a_field_source_that_never_answered_holds_the_paid_request(tmp_path):
    """Its records are half of what the gate is read over: where none came back the question's part looks
    uncarried because nothing answered, and the design's own condition was never tested."""
    lib = _standard(tmp_path, "field-failed.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    sent = _sent(lib, tmp_path, plan, refused=("pubmed",))
    assert "scopus" not in {provider for provider, _ in sent}
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['subtopic']['index']}")
    assert (step["status"], step["error_code"]) == ("cancelled", "field_source_did_not_answer")
    gate = step["output"]["gate"]
    assert gate == {"covered": False, "query_indexes": gate["query_indexes"], "held": True,
                    "field_pages_answered": 0, "field_pages_failed": 1}
    lib.conn.close()
    # The same, with the main query alone carrying the part: either reason holds the request, and the one
    # recorded is the source that never answered, so the record does not hide it behind a gap that was met.
    lib = _standard(tmp_path, "field-failed-met.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    _sent(lib, tmp_path, plan, refused=("pubmed",), covers=("openalex",))
    step = lib.store.existing_step(lib.run["id"], f"search:{plan['subtopic']['index']}")
    assert (step["status"], step["error_code"]) == ("cancelled", "field_source_did_not_answer")
    assert step["output"]["gate"]["covered"] is True
    lib.conn.close()


def test_a_failed_sub_topic_request_is_sent_again_only_when_the_failed_searches_are_retried(tmp_path):
    lib = _standard(tmp_path, "retry-sub.sqlite")
    _routing(lib, [{"provider_id": "pubmed", "reason": "share", "share": 0.9}])
    plan = _plan(lib, SUBTOPIC_QUERIES, vocabulary=VOCABULARY)
    key = f"search:{plan['subtopic']['index']}"
    step = lib.store.step(lib.run["id"], key, "provider_search:scopus")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "failed", error_code="SYNTHETIC refusal")
    # Without the retry the recorded failure stands and nothing is sent again.
    assert not [p for p, _ in _sent(lib, tmp_path, plan) if p == "scopus"]
    assert lib.store.existing_step(lib.run["id"], key)["status"] == "failed"
    # With it the frozen request is settled instead of being left failed for ever.
    assert [limit for p, limit in _sent(lib, tmp_path, plan, retry=True) if p == "scopus"] == [25]
    assert lib.store.existing_step(lib.run["id"], key)["status"] == "succeeded"
    lib.conn.close()

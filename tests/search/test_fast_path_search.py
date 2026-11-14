"""Synthetic search/queue evidence; no live app, provider or model."""

import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from deixis.runtime.config import Settings
from deixis.providers import facade, openalex
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.workflow.search import english_question, search as fast_search, ranking, small_batch
from deixis.workflow.run import fast_path
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store
from test_fast_path_clock import library
from test_fast_path_clock import FakeClock
from deixis.api.app import create_app
from deixis.storage import db
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter
from test_abstract_flow import ON_TOPIC
from test_abstract_flow import responder
from overlap_flow_helpers import discover
from overlap_flow_helpers import wait
from test_fulltext_flow import Fetcher
from test_fulltext_flow import Transport
from test_fulltext_flow import named_pdf
from test_fulltext_flow import ok
from test_fulltext_flow import work
from test_small_batch_flow import client_of
from fastapi.testclient import TestClient
from deixis.models.adapter import ModelStepResult
from deixis.providers import query_compiler
from test_api_flow import session
from test_api_flow import sw_settings
from test_api_flow import wait_run
from provider_flow_helpers import no_fetch
from provider_flow_helpers import routed


QUERIES = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"},
           {"provider_id": "openalex", "query_text": "SYNTHETIC beta"},
           {"provider_id": "arxiv", "query_text": "SYNTHETIC gamma"}]


def record(identity):
    title = 'SYNTHETIC ' + hashlib.sha256(identity.encode()).hexdigest()
    return ProviderRecord(provider_record_id=identity, title=title, authors=[],
                          year=2026, venue=None, publication_type="article", doi=None,
                          landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label="publishedVersion",
                          abstract=f"SYNTHETIC abstract {identity}", abstract_origin="provider_openalex_inverted_index",
                          identifiers={"openalex": identity}, raw={"id": identity})


# The searched block terms, one of them dropped; the block terms' semantic request joins the other two.
VOCABULARY = {"terms": [{"phrase": "synthetic setting words", "block": "setting", "dropped": None},
                        {"phrase": "synthetic zero words", "block": "task", "dropped": "zero_results"},
                        {"phrase": "synthetic task words", "block": "task", "dropped": None}]}


def setup(lib, tmp_path, vocabulary=None):
    scope = lib.store.scope(lib.rid)
    settings = Settings(data_dir=tmp_path / "data")
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, settings=settings, local_embedder=None))
    plan = fast_search.build_plan(lib.store, lib.run, scope, QUERIES, vocabulary=vocabulary)
    fast_path.enter_stage(lib.store, lib.run, "search")
    return flow, scope, plan



def scripted(flow, calls, *, advance=None, fail_at=None, short=False):
    async def send(run_id, connector, query, limit, page=None, **kwargs):
        assert not flow.store.conn.in_transaction
        calls.append((query.get("endpoint"), query["query_text"], page.number, limit))
        if advance:
            advance(query, page)
        if fail_at and fail_at(query, page):
            return SearchOutcome("failed", "rejected_not_executed", "SYNTHETIC failure", "keyless")
        n = 2 if short or query.get("endpoint") == "semantic" else limit
        ids = [f"W{len(calls)}_{i}" for i in range(n)]
        return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC request", "keyless",
                             records=[record(i) for i in ids], provider_total=900,
                             next_cursor=f"SYNTHETIC cursor {page.number + 1}")
    flow._send_search = send


def test_frozen_plan_cap_rotation_page_admission_and_resume(library, tmp_path):
    # The current plan freezes the block request as off, so only the question's semantic request is sent.
    lib = library
    flow, scope, plan = setup(lib, tmp_path, VOCABULARY)
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    semantic = 1
    # Under the evidence minimum the semantic requests run beside the keyword pages, so each kind keeps its own order.
    sent = [call for call in calls if call[0] == "semantic"]
    assert [(q, p, n) for e, q, p, n in calls if e != "semantic"] == [
        (QUERIES[i % 2]['query_text'], i // 2, 100) for i in range(8)]
    assert len(sent) == semantic
    block = lib.conn.execute("SELECT sr.result_count FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
                             " WHERE s.operation_key = ?", (fast_search.BLOCK_SEMANTIC_KEY,)).fetchall()
    arms = [q["arm"] for q in fast_search.sent_plan({"fast_path_search": plan, "compiled_queries": QUERIES})]
    assert plan["block_semantic"] == fast_search.BLOCK_SEMANTIC_OFF and not block and "block_semantic" not in arms
    # The arXiv query of this synthetic plan names a source this research does not hold, so that is the reason it
    # is dropped with, and not the old blanket one (a depth that searches no field source says so: its own test).
    assert plan['dropped'][0]['reason'] == 'not_in_scope'
    assert lib.store.existing_step(lib.run['id'], 'vocabulary_expansion') is None
    searches = [dict(r) for r in lib.conn.execute('SELECT * FROM search_runs ORDER BY rowid')]
    assert searches[-1]['stop_reason'] == 'read_limit'
    assert searches[-2]['stop_reason'] == 'read_limit'
    before = list(calls), searches
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    assert (calls, [dict(r) for r in lib.conn.execute('SELECT * FROM search_runs ORDER BY rowid')]) == before


def test_shared_search_stops_each_keyword_query_at_its_record_limit(library, tmp_path):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    queries = [QUERIES[0] | {"origin": "model"},
               QUERIES[1] | {"origin": "model", "role": "focused",
                             "focused": {"term": "unfound concept", "gap": "SYNTHETIC gap"}}]
    plan = fast_search.build_plan(lib.store, lib.run, scope, queries)
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    keyword = [call for call in calls if call[0] != "semantic"]
    assert [(query, page, limit) for _, query, page, limit in keyword] == [
        (queries[i // 4]["query_text"], i % 4, 100) for i in range(8)]
    pages = lib.conn.execute(
        "SELECT s.operation_key, sr.read_total, sr.read_limit, sr.stop_reason FROM search_runs sr "
        "JOIN run_steps s ON s.id = sr.step_id WHERE sr.request_class = 1 ORDER BY sr.rowid").fetchall()
    assert [(row["read_total"], row["read_limit"], row["stop_reason"]) for row in pages if row["stop_reason"]] == [
        (400, 400, "read_limit"), (400, 400, "read_limit")]
    assert sum(row["read_total"] == 400 for row in pages) == 2




def test_failed_page_retries_same_slot_without_resending_success(library, tmp_path):
    flow, scope, plan = setup(library, tmp_path)
    calls = []
    scripted(flow, calls, fail_at=lambda q, p: q['query_text'] == QUERIES[0]['query_text'] and p.number == 0)
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    failed = library.store.existing_step(library.run['id'], 'search:0')['output']['fast_path_request']
    scripted(flow, calls)
    before = len(calls)
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, True))
    assert calls[before] == (None, QUERIES[0]['query_text'], 0, 100)
    retried = library.store.existing_step(library.run['id'], 'search:0')['output']['fast_path_request']
    assert (retried['limit'], retried['request_index']) == (failed['limit'], failed['request_index'])
    assert not any(endpoint == 'semantic' for endpoint, *_ in calls[before:])


def test_semantic_adapter_abstract_headers_and_legacy_revision(monkeypatch):
    requests = []
    monkeypatch.setattr(openalex.SEMANTIC_PACER, 'interval_seconds', 0)
    async def execute():
        def transport(req):
            requests.append(req)
            return httpx.Response(200, json={'meta': {'count': 1}, 'results': [{'id': 'https://openalex.org/W1',
                'display_name': 'SYNTHETIC title', 'abstract_inverted_index': {'SYNTHETIC': [0], 'abstract': [1]}}]},
                headers={'x-ratelimit-cost-usd': '0.001', 'x-ratelimit-credits-used': '10'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await facade.dispatch_search('openalex', http, 'x' * 2100, 100, 'SYNTHETIC KEY', None,
                endpoint='semantic', cursor='*', reference_count=True, references=True)
    result = asyncio.run(execute())
    assert result.outcome.records[0].abstract == 'SYNTHETIC abstract'
    assert result.outcome.next_cursor is None and result.connector['adapter_revision'] == 4
    assert requests[0].url.params['per_page'] == '50'
    assert len(requests[0].url.params['search.semantic']) == 1500  # OpenAlex's limit
    assert 'cursor' not in requests[0].url.params and 'search.title_abstract_keywords' not in requests[0].url.params
    assert result.outcome.rate_limit['x-ratelimit-credits-used'] == '10'
    assert 'SYNTHETIC KEY' not in json.dumps(result.outcome.raw_payload)



def test_new_detailed_policy_sends_no_semantic_scholar_bulk(library, tmp_path):
    library.run['budget']['fast_path'] = fast_path.freeze_budget({}, 'detailed')
    s2 = {'provider_id': 'semantic_scholar', 'query_text': 'SYNTHETIC bulk', 'endpoint': 'bulk'}
    flow, scope, _ = setup(library, tmp_path)
    plan = fast_search.build_plan(library.store, library.run, scope, QUERIES + [s2])
    assert 's2_bulk' not in plan and 's2_reserved' not in plan
    calls = []
    scripted(flow, calls, short=True)
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    assert all(endpoint != 'bulk' for endpoint, *_ in calls)


def test_a_question_in_another_language_goes_to_openalex_as_written(library, tmp_path):
    # The first semantic request carries the person's own sentence. A question in another language with no stored
    # English sentence is planned and sent as written, and nothing is cancelled for the missing sentence.
    lib = library
    question = "Sualtı duyarga ağlarında yönlendirme protokolleri nasıl karşılaştırılıyor?"
    scope = lib.store.scope(lib.rid) | {"question": question, "language_hint": "tr"}
    assert english_question.embedding_query(lib.store, scope) is None  # the revision has no English sentence
    settings = Settings(data_dir=tmp_path / "data")
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, settings=settings, local_embedder=None))
    plan = fast_search.build_plan(lib.store, lib.run, scope, QUERIES)
    assert (plan["semantic"]["query_text"], plan["semantic"]["query_origin"]) == (question, "question")
    fast_path.enter_stage(lib.store, lib.run, "search")
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    # The first semantic request; under the evidence minimum the keyword pages may go out beside it.
    assert next(call for call in calls if call[0] == "semantic") == ("semantic", question, 0, plan["semantic"]["limit"])
    step = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    assert step["status"] == "succeeded" and step["error_code"] is None


# Fast path end to end: one Quick question through search, chain, read and the automatic answer.

def url(n):
    return f"https://example.org/w{n}.pdf"


def test_quick_question_runs_every_fast_path_stage_and_answers_unattended(tmp_path, monkeypatch):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    works = [work(n, pdf_url=url(n), title=ON_TOPIC) for n in range(1, 31)]
    fetcher = Fetcher({url(n): ok(named_pdf(f"10.1/oa.{n}")) for n in range(1, 31)})
    app = create_app(Settings(data_dir=tmp_path, port=8765,
                              fulltext_fetch="auto", fulltext_adjudication="auto"),
                     adapters={"fake": FakeAdapter(responder())},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(Transport(works))), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed", discovery
        store = app.state.store
        budget = store.run(discovery_id)["budget"]
        answers = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'answer'", (rid,)).fetchall()
        assert len(answers) == 1
        _, answer = wait(client, rid, answers[0][0])
        assert answer["status"] == "completed", answer
        view = client.get(f"/api/researches/{rid}").json()
        stages = {row["stage"]: row["status"] for row in store.conn.execute("SELECT stage, status FROM fast_path_stages")}
        outcome = store.conn.execute("SELECT answer_outcome FROM fast_path_ledgers").fetchone()[0]
        kinds = {row[0]: row[1] for row in store.conn.execute(
            "SELECT kind, count(*) FROM run_steps WHERE status = 'succeeded' GROUP BY kind")}

    assert fast_path.enabled(budget)
    assert set(budget["fast_path"]["enforced_stages"]) == {"search", "ranking", "read", "answer"}
    assert stages == dict.fromkeys(("plan", "search", "ranking", "read", "answer"), "done")
    assert outcome == "structurally_valid"
    assert kinds["provider_search:openalex"] >= 1
    # Quick can send a chain request when its first page names a usable seed.
    assert kinds["provider_chain:openalex"] >= 1
    assert kinds["code:fast_chain"] >= 1
    assert len(fetcher.calls) == kinds["fetch_pdf"] == 10  # Quick reads the first K = 10 eligible works
    assert kinds["model:fulltext_adjudication"] == 20  # two reads per work
    assert kinds["code:fast_path_cutoff"] == 1 and kinds["model:grounded_answer"] == 1
    claims = view["answers"][0]["claims"]
    assert claims and {claim["evidence_basis"] for claim in claims} == {"full_text"}


# Restore the applicable end-to-end assertions using synthetic sw discovery.

def app_for(tmp_path, handler, adapter):
    return create_app(sw_settings(tmp_path), adapters={"fake": adapter},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def start(client):
    rid = client.app.state.store.create_research(
        "How does diffusion channel scheduling affect relay energy?", "academic", "quick",
        ["openalex", "biorxiv", "crossref"], "fake", "fake-model", "en")
    response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
    assert response.status_code == 202, response.text
    return rid, response.json()["id"]


def test_sw_failed_provider_is_retained_and_retry_reuses_queries_and_protocol(tmp_path, monkeypatch):
    # The fast path searches OpenAlex alone, so its keyword page is the one that fails here.
    attempts = []
    limited = True
    def handler(request):
        params = request.url.params
        if params.get("per_page") == "1" or "search.title_abstract_keywords" not in params:
            return routed(request)  # count probes, the semantic search and the chain
        attempts.append(params["search.title_abstract_keywords"])
        if limited:
            return httpx.Response(429, headers={"retry-after": "60"})
        return routed(request)
    adapter = FakeAdapter()
    app = app_for(tmp_path, handler, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        rid, run_id = start(client)
        view, run = wait_run(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("completed", None)
        keyword = lambda view: [(s["provider"], s["status"]) for s in view["search_runs"] if s["query_text"] == attempts[0]]
        assert keyword(view) == [("openalex", "rate_limited")]
        assert [(s["operation_key"], s["status"]) for s in run["steps"] if s["operation_key"].startswith("search:")
                and not s["operation_key"].startswith((fast_search.PHRASE_KEY, fast_search.PLAIN_PHRASE_KEY))] == [
            ("search:fast:semantic", "succeeded"), ("search:0", "failed"), ("search:2", "failed")]
        assert view["counts"]["unique"] == 1
        assert run["budget"]["inspection"]["policy"] == "small_batch_fused_v1"
        assert any(s["operation_key"].startswith("small_batch:v1:")
                   and s["operation_key"].endswith(":abstract_stage") for s in run["steps"])
        store = app.state.store
        frozen = store.current_protocol(rid, 1)
        planning_calls = [call for call in adapter.calls if call["task_type"] in ("vocabulary_labels", "criterion_proposal")]
        def refuse_compile(*args, **kwargs):
            raise AssertionError("Retry must use stored compiled queries")
        monkeypatch.setattr(query_compiler, "compile_block_queries", refuse_compile)
        limited = False
        retry = client.post(f"/api/runs/{run_id}/retry_failed")
        assert retry.status_code == 200, retry.text
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        assert keyword(view) == [("openalex", "rate_limited"), ("openalex", "completed")]
        assert attempts[:2] == attempts[2:]
        assert store.current_protocol(rid, 1) == frozen
        assert store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0] == 1
        assert [call for call in adapter.calls if call["task_type"] in ("vocabulary_labels", "criterion_proposal")] == planning_calls


def test_sw_pause_resume_keeps_frozen_protocol_and_does_not_repeat_search(tmp_path, monkeypatch):
    # Pause during the current read stage, after the protocol and requests are stored.
    holder = {}
    down = True
    def before(si):
        if down and si["task_type"] == "abstract_screening":
            holder["app"].state.store.update_run(si["run_id"], status="pause_requested")
    adapter = FakeAdapter(before=before)

    def plan_from_its_own_record(request):
        # The question's own request answers with a record whose words the pool's titles do not carry, so the
        # plan's blocks name nothing in them and the abstract stage has to ask the model.
        if "search.semantic" in request.url.params:
            return httpx.Response(200, json={"meta": {"count": 1}, "results": [
                {"id": "https://openalex.org/W8000", "doi": "https://doi.org/10.1/plan",
                 "display_name": "Zzqscope of zzqdomain (SYNTHETIC)", "publication_year": 2021, "type": "article",
                 "authorships": [], "abstract_inverted_index": {"We": [0], "zzqmeasure": [1], "zzqoutcome": [2]}}]})
        return routed(request)
    app = app_for(tmp_path, plan_from_its_own_record, adapter)
    holder["app"] = app
    with TestClient(app) as raw:
        client = session(raw)
        rid, run_id = start(client)
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "paused", run
        store = app.state.store
        frozen = store.current_protocol(rid, 1)
        searches = view["search_runs"]
        vocabulary = store.step(run_id, "vocabulary", "code:vocabulary")["output"]
        def refuse_compile(*args, **kwargs):
            raise AssertionError("Resume must use stored compiled queries")
        monkeypatch.setattr(query_compiler, "compile_block_queries", refuse_compile)
        down = False
        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        assert view["search_runs"] == searches
        assert store.step(run_id, "vocabulary", "code:vocabulary")["output"] == vocabulary
        assert store.current_protocol(rid, 1) == frozen
        assert store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0] == 1


def test_the_questions_request_is_sent_once_and_the_search_stage_never_repeats_it(library, tmp_path):
    """The request sent before anything plans keeps the `search:fast:semantic` key, so the search stage finds the step
    succeeded and sends nothing more, and a resume finds the same (P2, Argon's blocker). Semantic search is single
    page (`terminal="single_page"`), so there is no page to continue from either. The frozen plan's own request is
    the one that went out: both come from `semantic_spec`."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    calls = []
    scripted(flow, calls)

    async def go():
        assert await fast_search.first_semantic(flow, lib.run, scope) is None
        await fast_search.execute(flow, lib.run, scope, plan, False)
        await fast_search.execute(flow, lib.run, scope, plan, True)  # the resume, which retries failed pages
    asyncio.run(go())
    semantic = [(query, number) for endpoint, query, number, _ in calls if endpoint == "semantic"]
    assert semantic == [(plan["semantic"]["query_text"], 0)] == [(scope["question"], 0)]
    step = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    assert (step["status"], step["attempt"]) == ("succeeded", 1)
    assert step["output"]["stop_reason"] == "single_page"
    rows = lib.conn.execute("SELECT COUNT(*) FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
                            " WHERE s.operation_key = 'search:fast:semantic'").fetchone()[0]
    assert rows == 1


def freeze(lib, plan):
    """Freeze `plan` as this run's own protocol, the way the discovery run does once its planning steps are done."""
    record = lib.store.freeze_protocol(lib.rid, lib.run["scope_revision"], {"fast_path_search": plan})
    step = lib.store.step(lib.run["id"], "protocol", "protocol:freeze")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "succeeded",
                          output={"protocol_revision": record["protocol_revision"], "protocol_hash": record["hash"]})
    return record


def test_a_run_whose_protocol_is_frozen_sends_what_the_protocol_holds(library, tmp_path):
    """On a resume the frozen plan is the record of what this run searches, so the early request reads it instead of
    building a new one. A plan frozen before the request carried the person's own sentence holds a different text —
    its own English sentence — and sending a freshly built request would leave the run searching what its protocol
    does not name."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    frozen_text = "SYNTHETIC frozen sentence"
    freeze(lib, plan | {"semantic": plan["semantic"] | {"query_text": frozen_text, "query_origin": "english_question"}})
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.first_semantic(flow, lib.run, scope))
    assert [query for endpoint, query, _, _ in calls if endpoint == "semantic"] == [frozen_text]
    assert frozen_text != scope["question"]


def test_a_frozen_plan_with_no_text_cancels_the_early_request_instead_of_sending_the_question(library, tmp_path):
    """The same rule at its edge: a plan frozen while no English sentence existed carries no text, and that plan's
    own answer is to cancel. The early call must not turn that into a request for the question as written."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    freeze(lib, plan | {"semantic": plan["semantic"] | {"query_text": None, "query_origin": english_question.MISSING}})
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.first_semantic(flow, lib.run, scope))
    assert [endpoint for endpoint, *_ in calls if endpoint == "semantic"] == []
    step = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    assert step["status"] == "cancelled"


def test_the_early_step_of_a_later_discovery_run_carries_no_protocol_hash(library, tmp_path):
    """A later discovery run of the same scope revision opens its request before freezing its own protocol, so the
    step belongs to no protocol and carries NULL. `store.step` reads the research's current protocol, which is the
    earlier run's, and a step holding that hash would claim to belong to a plan it never searched under (Ç1)."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    earlier = lib.store.freeze_protocol(lib.rid, lib.run["scope_revision"], {"fast_path_search": plan})
    assert lib.store.current_protocol(lib.rid, lib.run["scope_revision"])["hash"] == earlier["hash"]
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.first_semantic(flow, lib.run, scope))  # this run has frozen none of its own yet
    step = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    assert step["protocol_hash"] is None and step["status"] == "succeeded"
    assert [query for endpoint, query, _, _ in calls if endpoint == "semantic"] == [scope["question"]]


def test_a_resumed_run_records_its_own_protocol_not_a_newer_one(library, tmp_path):
    """The step belongs to the protocol whose plan it sends. A later run of the same scope revision may have frozen a
    newer protocol since; the research's current protocol would then put this run's request under a plan it never
    searched under."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    mine = freeze(lib, plan)
    newer = lib.store.freeze_protocol(lib.rid, lib.run["scope_revision"], {"fast_path_search": plan, "later": True},
                                      reason="later_discovery_run")
    assert lib.store.current_protocol(lib.rid, lib.run["scope_revision"])["hash"] == newer["hash"] != mine["hash"]
    scripted(flow, [])
    asyncio.run(fast_search.first_semantic(flow, lib.run, scope))
    step = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    assert step["protocol_hash"] == mine["hash"]


def test_a_cancelled_early_request_also_carries_this_runs_protocol(library, tmp_path):
    """The cancelled step is a record too: a frozen plan with no text cancels, and that row must name the protocol
    whose plan said so, not whichever protocol the research froze last."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    mine = freeze(lib, plan | {"semantic": plan["semantic"] | {"query_text": None,
                                                               "query_origin": english_question.MISSING}})
    newer = lib.store.freeze_protocol(lib.rid, lib.run["scope_revision"], {"fast_path_search": plan, "later": True},
                                      reason="later_discovery_run")
    scripted(flow, [])
    asyncio.run(fast_search.first_semantic(flow, lib.run, scope))
    step = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    assert step["status"] == "cancelled"
    assert step["protocol_hash"] == mine["hash"] != newer["hash"]


def test_the_protocol_hash_is_read_from_the_record_not_the_step_output(library, tmp_path):
    """A protocol step written before its output carried the hash names only the revision. The record is the one
    place the hash always is, so the request still records it instead of NULL."""
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    mine = freeze(lib, plan)
    step = lib.store.existing_step(lib.run["id"], "protocol")
    lib.store.set_step_output(step["id"], {"protocol_revision": mine["protocol_revision"]})  # no hash, as of old
    scripted(flow, [])
    asyncio.run(fast_search.first_semantic(flow, lib.run, scope))
    assert lib.store.existing_step(lib.run["id"], "search:fast:semantic")["protocol_hash"] == mine["hash"]

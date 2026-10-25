"""D252 synthetic search/queue evidence; no live app, provider or model."""

import asyncio
import hashlib
import json
import sqlite3
from array import array
from types import SimpleNamespace

import httpx
import pytest

from deixis.config import Settings
from deixis.documents import embeddings, local_embedding
from deixis.providers import facade, openalex
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.workflow import fast_embedding, fast_path, search as fast_search, ranking
from deixis.workflow.flow import ResearchFlow
from test_fast_path_clock import library
from deixis.api.app import create_app
from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter
from test_abstract_flow import ON_TOPIC
from test_abstract_flow import responder
from test_fetch_overlap_flow import discover
from test_fetch_overlap_flow import wait
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
from test_provider_flow import no_fetch
from test_provider_flow import routed


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


def setup(lib, tmp_path):
    scope = lib.store.scope(lib.rid)
    settings = Settings(data_dir=tmp_path / "data")
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, settings=settings, local_embedder=None))
    plan = fast_search.build_plan(lib.store, lib.run, scope, QUERIES)
    fast_path.enter_stage(lib.store, lib.run, "search")
    return flow, scope, plan


def rows(lib):
    return [dict(r) for r in lib.conn.execute("SELECT * FROM fast_path_embedding_queue ORDER BY class, request_index, position")]


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
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    calls = []
    scripted(flow, calls)
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    assert [(q, p, n) for _, q, p, n in calls[1:]] == [
        (QUERIES[0]['query_text'], 0, 100), (QUERIES[1]['query_text'], 0, 100),
        (QUERIES[0]['query_text'], 1, 100), (QUERIES[1]['query_text'], 1, 100),
        (QUERIES[0]['query_text'], 2, 50)]
    assert calls[0][0] == 'semantic'
    assert len(rows(lib)) == 452
    assert [r['request_index'] for r in rows(lib)[::100]][:2] == [0, 1]
    assert plan['dropped'][0]['reason'] == 'openalex_only'
    assert lib.store.existing_step(lib.run['id'], 'vocabulary_expansion') is None
    searches = [dict(r) for r in lib.conn.execute('SELECT * FROM search_runs ORDER BY rowid')]
    assert searches[-1]['stop_reason'] == 'record_cap'
    assert searches[-2]['stop_reason'] == 'record_cap'
    before = list(calls), rows(lib), searches
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    assert (calls, rows(lib), [dict(r) for r in lib.conn.execute('SELECT * FROM search_runs ORDER BY rowid')]) == before


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
    assert result.outcome.next_cursor is None and result.connector['adapter_revision'] == 3
    assert requests[0].url.params['per_page'] == '50'
    assert len(requests[0].url.params['search.semantic']) == 1500  # OpenAlex's limit (D3)
    assert 'cursor' not in requests[0].url.params and 'search.title_and_abstract' not in requests[0].url.params
    assert result.outcome.rate_limit['x-ratelimit-credits-used'] == '10'
    assert 'SYNTHETIC KEY' not in json.dumps(result.outcome.raw_payload)


def queued(lib, klass=1, request=0, position=0, name='W1'):
    svid, _ = lib.store.upsert_provider_source('openalex', record(name), None)
    lib.store.add_to_corpus(lib.rid, svid, 'search', scope_revision=1)
    lib.conn.execute("INSERT INTO fast_path_embedding_queue (run_id, class, request_index, position, source_version_id, enqueued_at, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                     (lib.run['id'], klass, request, position, svid, fast_path.timestamp(lib.clock)))
    return svid


def fake_embedder(lib, flow, monkeypatch, *, fail=False, advance=False):
    lib.store.set_setting('semantic_search', {'provider': 'builtin', 'model': 'qwen3-embedding-0.6b'})
    calls = []
    async def embed(self, client, texts, task_type, *args, **kwargs):
        assert not lib.conn.in_transaction
        assert local_embedding.RUNNER_THREADS.get() == 4
        calls.append((task_type, texts))
        await asyncio.sleep(0)
        if fail and task_type == 'RETRIEVAL_DOCUMENT':
            raise embeddings.EmbeddingError('SYNTHETIC batch failure')
        if advance and task_type == 'RETRIEVAL_DOCUMENT':
            lib.clock.advance(100)
        return [array('f', [1.0, 0.0]) for _ in texts]
    monkeypatch.setattr(embeddings.Embedder, 'embed', embed)
    flow.deps.http = None
    return calls


def test_queue_unique_and_stored_scores_not_embedded_twice(library, tmp_path, monkeypatch):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    calls = fake_embedder(lib, flow, monkeypatch)
    svid = queued(lib)
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute("INSERT INTO fast_path_embedding_queue SELECT run_id, class, request_index + 1, position, source_version_id, search_run_id, enqueued_at, status, embedded_at, cutoff_at FROM fast_path_embedding_queue")
    async def execute():
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        lib.store.save_source_similarities(lib.rid, 1, consumer.embedder.stored_model, {svid: .5})
        consumer.start()
        fast_path.close_stage(lib.store, lib.run['id'], 'search')
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        await consumer.drain(lib.store.candidates(lib.rid, 1))
    asyncio.run(execute())
    assert len(calls) == 1 and rows(lib)[0]['status'] == 'from_store'


def test_deep_s2_slot_overlaps_keyword_transport_and_writes_first(library, tmp_path):
    lib = library
    flow, scope, plan = setup(lib, tmp_path)
    plan |= {'s2_reserved': 500, 'keyword_cap': 10, 'page_size': 10,
             's2_bulk': {'provider_id': 'semantic_scholar', 'query_text': 'SYNTHETIC s2', 'endpoint': 'bulk'}}
    queries = []
    async def execute():
        keyword_started = asyncio.Event()
        async def send(run_id, connector, query, limit, page=None, **kwargs):
            assert not lib.conn.in_transaction
            queries.append((query['provider_id'], query.get('endpoint'), limit))
            if query['provider_id'] == 'semantic_scholar':
                await keyword_started.wait()
                records = [record('Ws2')]
                raw = {'data': [None] * 1000}
            else:
                if query.get('endpoint') != 'semantic':
                    keyword_started.set()
                records = [record('Wsem' if query.get('endpoint') else 'Wkeyword')]
                raw = None
            return SearchOutcome('completed', 'rejected_not_executed', 'SYNTHETIC', 'keyless', records=records,
                                 provider_total=1000, next_cursor='SYNTHETIC', raw_payload=raw)
        flow._send_search = send
        await asyncio.wait_for(fast_search.execute(flow, lib.run, scope, plan, False), 2)
    asyncio.run(execute())
    assert sorted(queries, key=str) == sorted([('openalex', 'semantic', 50), ('semantic_scholar', 'bulk', 500), ('openalex', None, 10)], key=str)
    search_order = [r[0] for r in lib.conn.execute('SELECT provider FROM search_runs ORDER BY rowid')]
    assert search_order == ['openalex', 'semantic_scholar', 'openalex']
    assert [r['request_index'] for r in rows(lib)] == [0, 1, 2]
    s2 = lib.store.existing_step(lib.run['id'], 'search:fast:s2_bulk')['output']['fast_path_request']
    assert s2['limit'] == 500 and s2['raw_returned_count'] == 1000


def test_deep_unplanned_s2_reservation_does_not_move_to_openalex(library):
    library.run['budget']['fast_path'] = fast_path.freeze_budget({}, 'detailed')
    plan = fast_search.build_plan(library.store, library.run, library.store.scope(library.rid), QUERIES)
    assert plan['keyword_cap'] == 1500 and plan['s2_reserved'] == 500 and plan['s2_bulk'] is None
    s2 = {'provider_id': 'semantic_scholar', 'query_text': 'SYNTHETIC first bulk', 'endpoint': 'bulk'}
    planned = fast_search.build_plan(library.store, library.run, library.store.scope(library.rid), QUERIES + [s2, s2 | {'query_text': 'SYNTHETIC second bulk'}])
    assert planned['s2_bulk'] == s2 and planned['s2_bulk_index'] == 3
    assert [q['index'] for q in planned['dropped']] == [2, 4]


# Fast path end to end (D250–D254): one Quick question through search, chain, read and the automatic answer.

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
    app = create_app(Settings(data_dir=tmp_path, port=8765, search_query="code",
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
    assert kinds["provider_search:openalex"] >= 1 and kinds["provider_chain:openalex"] >= 1
    assert kinds["code:fast_chain"] >= 1
    assert len(fetcher.calls) == kinds["fetch_pdf"] == 10  # Quick reads the first K = 10 eligible works
    assert kinds["model:fulltext_adjudication"] == 20  # two reads per work
    assert kinds["code:fast_path_cutoff"] == 1 and kinds["model:grounded_answer"] == 1
    claims = view["answers"][0]["claims"]
    assert claims and {claim["evidence_basis"] for claim in claims} == {"full_text"}


# D175: restore applicable D119 end-to-end assertions using synthetic sw discovery.

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
    # The fast path searches OpenAlex alone (D252), so its keyword page is the one that fails here.
    attempts = []
    limited = True
    def handler(request):
        params = request.url.params
        if params.get("per_page") == "1" or "search.title_and_abstract" not in params:
            return routed(request)  # count probes, the semantic search and the chain
        attempts.append(params["search.title_and_abstract"])
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
        assert [(s["operation_key"], s["status"]) for s in run["steps"] if s["operation_key"].startswith("search:")] == [
            ("search:fast:semantic", "succeeded"), ("search:0", "failed")]
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
        assert attempts == [attempts[0], attempts[0]]
        assert store.current_protocol(rid, 1) == frozen
        assert store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0] == 1
        assert [call for call in adapter.calls if call["task_type"] in ("vocabulary_labels", "criterion_proposal")] == planning_calls


def test_sw_pause_resume_keeps_frozen_protocol_and_does_not_repeat_search(tmp_path, monkeypatch):
    down = True
    def failure(si):
        if down and si["task_type"] == "abstract_screening":
            return ModelStepResult("failed", error="SYNTHETIC paused connection")
    adapter = FakeAdapter(fail=failure)
    app = app_for(tmp_path, routed, adapter)
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

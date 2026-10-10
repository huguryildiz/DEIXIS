"""D252 synthetic search/queue evidence; no live app, provider or model."""

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import replace
from array import array
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from deixis.config import Settings
from deixis.documents import embeddings, local_embedding
from deixis.providers import facade, openalex, registry
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.storage.db import transaction
from deixis.workflow import fast_embedding, fast_path, fast_search, ranking
from deixis.workflow.flow import ResearchFlow, RunStopped
from deixis.workflow.worker import Worker
from test_fast_path_clock import library, stage


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


def test_deadline_pause_recovery_and_rework(library, tmp_path):
    lib = library
    fast_path.enter_stage(lib.store, lib.run, "search")
    first = fast_path.stage_deadline(lib.store, lib.run, "search")
    lib.clock.advance(10)
    lib.store.update_run(lib.run["id"], status="paused")
    assert fast_path.stage_deadline(lib.store, lib.run, "search") is None
    lib.clock.advance(500)
    lib.store.update_run(lib.run["id"], status="running")
    iid = fast_path.enter_stage(lib.store, lib.run, "search")
    assert fast_path.stage_deadline(lib.store, lib.run, "search") == first + timedelta(seconds=500)
    lib.clock.advance(5)
    fast_path.checkpoint(lib.store, iid)
    lib.clock.advance(20)
    Worker(lib.store, None, tmp_path / "lock").recover()
    lib.store.update_run(lib.run["id"], status="running")
    fast_path.enter_stage(lib.store, lib.run, "search")
    assert fast_path.stage_deadline(lib.store, lib.run, "search") == lib.clock.now() + timedelta(milliseconds=stage(lib, 'search')['alloc_ms'] - 15000)
    fast_path.close_stage(lib.store, lib.run["id"], "search")
    lib.run["budget"]["retry_provider_requests"] = 1
    fast_path.enter_stage(lib.store, lib.run, "search")
    assert fast_path.stage_deadline(lib.store, lib.run, "search") is None


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
    assert lib.store.existing_step(lib.run['id'], 'vocabulary_expansion')['output']['queries'] == []
    searches = [dict(r) for r in lib.conn.execute('SELECT * FROM search_runs ORDER BY rowid')]
    assert searches[-1]['stop_reason'] == 'record_cap'
    assert searches[-2]['stop_reason'] == 'record_cap'
    before = list(calls), rows(lib), searches
    asyncio.run(fast_search.execute(flow, lib.run, scope, plan, False))
    assert (calls, rows(lib), [dict(r) for r in lib.conn.execute('SELECT * FROM search_runs ORDER BY rowid')]) == before


def test_inflight_deadline_records_page_and_closes_unstarted_query(library, tmp_path):
    flow, scope, plan = setup(library, tmp_path)
    calls = []
    def advance(query, page):
        if not query.get('endpoint'):
            library.clock.advance(100)
    scripted(flow, calls, advance=advance)
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    assert len(calls) == 2
    search = library.conn.execute('SELECT * FROM search_runs ORDER BY rowid DESC LIMIT 1').fetchone()
    assert search['stop_reason'] == 'deadline' and search['unread_count'] == 800
    assert library.store.existing_step(library.run['id'], 'search:1')['error_code'] == 'deadline'
    assert len(rows(library)) == 102


def test_deadline_after_network_retry_wait_sends_no_retry(library, tmp_path, monkeypatch):
    flow, scope, _ = setup(library, tmp_path)
    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError('SYNTHETIC', request=req))))
    async def wait(seconds):
        assert not library.conn.in_transaction
        library.clock.advance(100)
    monkeypatch.setattr(asyncio, 'sleep', wait)
    async def execute():
        result = await flow._send_search(library.run['id'], registry.CONNECTORS['openalex'], QUERIES[0], 100,
                                        stop=lambda: fast_path.past_deadline(library.store, library.run, 'search'))
        await flow.deps.http.aclose()
        return result
    assert asyncio.run(execute()) is None
    assert library.store.run(library.run['id'])['usage']['provider_requests'] == 1


def test_queue_and_page_rollback_are_atomic(library, tmp_path):
    flow, scope, plan = setup(library, tmp_path)
    scripted(flow, [])
    library.conn.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON fast_path_embedding_queue BEGIN SELECT RAISE(ABORT, 'SYNTHETIC queue'); END")
    with pytest.raises(sqlite3.IntegrityError, match='SYNTHETIC queue'):
        asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    assert library.conn.execute('SELECT COUNT(*) FROM search_runs').fetchone()[0] == 0
    assert library.conn.execute('SELECT COUNT(*) FROM source_versions').fetchone()[0] == 0
    assert library.store.existing_step(library.run['id'], 'search:fast:semantic') is None


@pytest.mark.parametrize('endpoint', ['semantic', 'bulk'])
def test_pause_during_independent_slot_retry_is_not_a_permanent_deadline(library, tmp_path, endpoint):
    flow, scope, plan = setup(library, tmp_path)
    plan |= {'keyword_cap': 4, 'page_size': 4}
    if endpoint == 'bulk':
        plan |= {'s2_reserved': 500, 's2_bulk': {'provider_id': 'semantic_scholar',
                 'endpoint': 'bulk', 'query_text': 'SYNTHETIC bulk'}}
    scripted(flow, [], short=True)
    original = flow._send_search
    async def paused_send(*args, **kwargs):
        if args[2].get('endpoint') == endpoint:
            library.store.update_run(library.run['id'], status='pause_requested')
            return None  # Same result as an interrupted pre-retry network wait.
        return await original(*args, **kwargs)
    flow._send_search = paused_send
    async def execute():
        await fast_search.execute(flow, library.run, scope, plan, False)
        flow._checkpoint(library.run['id'], library.run['scope_revision'])
    with pytest.raises(RunStopped):
        asyncio.run(execute())
    key = 'search:fast:semantic' if endpoint == 'semantic' else 'search:fast:s2_bulk'
    step = library.store.existing_step(library.run['id'], key)
    assert step is None or step['status'] == 'pending'
    if endpoint == 'bulk':
        assert library.store.existing_step(library.run['id'], 'search:0')['status'] == 'succeeded'
    library.store.update_run(library.run['id'], status='running')
    fast_path.enter_stage(library.store, library.run, 'search')
    calls = []
    scripted(flow, calls, short=True)
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    assert calls[0][0] == endpoint
    assert library.store.existing_step(library.run['id'], key)['status'] == 'succeeded'


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
    assert len(requests[0].url.params['search.semantic']) == 2000
    assert 'cursor' not in requests[0].url.params and 'search.title_and_abstract' not in requests[0].url.params
    assert result.outcome.rate_limit['x-ratelimit-credits-used'] == '10'
    assert 'SYNTHETIC KEY' not in json.dumps(result.outcome.raw_payload)


def test_thread_argv_is_context_bound_and_default_unchanged(tmp_path):
    paths = local_embedding.builtin_paths(tmp_path)
    original = local_embedding.runner_argv(paths)
    assert '--threads' not in original
    assert local_embedding.runner_argv(paths, 4) == original + ['--threads', '4']
    assert local_embedding.RUNNER_THREADS.get() is None


def queued(lib, klass=1, request=0, position=0, name='W1'):
    svid, _ = lib.store.upsert_provider_source('openalex', record(name), None)
    lib.store.add_to_corpus(lib.rid, svid, 'search', scope_revision=1)
    lib.conn.execute("INSERT INTO fast_path_embedding_queue (run_id, class, request_index, position, source_version_id, enqueued_at, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                     (lib.run['id'], klass, request, position, svid, fast_path.timestamp(lib.clock)))
    return svid


def fake_embedder(lib, flow, monkeypatch, *, fail=False, advance=False):
    lib.store.set_setting('semantic_search', {'provider': 'builtin', 'model': local_embedding.MODEL_ID})
    calls = []
    async def embed(self, client, texts, task_type, *args):
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


@pytest.mark.parametrize('fail', [False, True])
def test_consumer_priority_cutoff_error_and_no_second_embedding(library, tmp_path, monkeypatch, fail):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    calls = fake_embedder(lib, flow, monkeypatch, fail=fail)
    chain = queued(lib, 2, 0, name='Wchain')
    keyword = queued(lib, 1, 2, name='Wkeyword')
    semantic = queued(lib, 0, 3, name='Wsemantic')
    async def execute():
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        flow._fast_consumers[lib.run['id']] = consumer
        consumer.start()
        await asyncio.sleep(0)
        fast_path.close_stage(lib.store, lib.run['id'], 'search')
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        pool = lib.store.candidates(lib.rid, 1)
        await consumer.drain(pool)
        await flow._source_similarity(lib.run, scope, pool)
        return consumer
    consumer = asyncio.run(execute())
    assert len(calls) == 2
    assert [t.split('\n')[0] for t in calls[1][1]] == [record(s).title for s in ('Wsemantic', 'Wkeyword', 'Wchain')]
    assert all(r['status'] == ('unembedded_at_cutoff' if fail else 'embedded') for r in rows(lib))
    output = lib.store.existing_step(lib.run['id'], 'source_similarity')['output']
    assert output['enqueued'] == 3 and output['missing'] == (3 if fail else 0)
    lib.store.save_source_similarities(lib.rid, 1, consumer.embedder.stored_model, {chain: .9, keyword: .8, semantic: .7})
    scores = fast_path.ranking_similarities(lib.store, lib.run, consumer.embedder.stored_model)
    assert scores == ({} if fail else {chain: 1.0, keyword: 1.0, semantic: 1.0})
    again = fast_embedding.Consumer(flow, lib.run, scope)
    assert again.closed and again.warmup is None


def test_cutoff_no_new_batch_and_missing_head_is_recorded(library, tmp_path, monkeypatch):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    calls = fake_embedder(lib, flow, monkeypatch)
    first = queued(lib)
    missing, _ = lib.store.upsert_provider_source('openalex', record('Wunqueued'), None)
    lib.store.add_to_corpus(lib.rid, missing, 'search', scope_revision=1)
    async def execute():
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        fast_path.close_stage(lib.store, lib.run['id'], 'search')
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        lib.clock.advance(1000)
        consumer.start()
        await consumer.drain(lib.store.candidates(lib.rid, 1))
    asyncio.run(execute())
    assert len(calls) == 1  # warm query only
    assert {r['source_version_id'] for r in rows(lib)} == {first, missing}
    assert all(r['status'] == 'unembedded_at_cutoff' and r['cutoff_at'] for r in rows(lib))


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


def test_policy_free_and_pre_slice2_frozen_policies_are_not_upgraded(library):
    lib = library
    policy = lib.run['budget']['fast_path']
    policy['enforced_stages'] = policy['enforcement'] = ['search', 'ranking', 'read']
    for key in ('approval_mode', 'auto_answer', 'policy_hash'):
        policy.pop(key, None)
    from deixis.domain.canonical import sha256_hex
    policy['policy_hash'] = sha256_hex(policy)
    lib.conn.execute('UPDATE runs SET budget_json = ? WHERE id = ?', (json.dumps(lib.run['budget']), lib.run['id']))
    protocol = lib.store.freeze_protocol(lib.rid, 1, {'SYNTHETIC': 'slice1'})
    step = lib.store.step(lib.run['id'], 'protocol', 'protocol:freeze')
    lib.store.finish_step(step['id'], 'succeeded', output={'protocol_revision': protocol['protocol_revision']})
    assert fast_path.view(lib.store, lib.run)['enforced_stages'] == ['search', 'ranking', 'read']
    assert lib.store.run(lib.run['id'])['budget']['fast_path'] == policy
    policy_free = lib.run | {'budget': {}}
    assert fast_path.stage_deadline(lib.store, policy_free, 'search') is None
    assert rows(lib) == []


def test_deterministic_missing_signal_fusion():
    pool = [{'id': s, 'work_id': s, 'title': 'SYNTHETIC same', 'abstract': '', 'references': None,
             'own_ids': frozenset(), 'cited_by_count': None} for s in ('c', 'a', 'b')]
    args = ([], ['same'], {'setting': [], 'task': []}, 'SYNTHETIC model', {'a': .5})
    first = ranking.rank_pool(pool, *args)
    second = ranking.rank_pool(list(reversed(pool)), *args)
    assert first['order'] == second['order']
    assert first['ranks']['embedding']['b'] == first['ranks']['embedding']['c']
    assert first['ranks']['embedding']['b'][1] is False


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


def test_provider_overreturn_never_exceeds_admission_slots(library, tmp_path):
    flow, scope, plan = setup(library, tmp_path)
    plan |= {'keyword_cap': 3, 'page_size': 3}
    scripted(flow, [], short=True)
    original = flow._send_search
    async def overreturn(*args, **kwargs):
        answer = await original(*args, **kwargs)
        if not args[2].get('endpoint'):
            return replace(answer, records=[record(f'Woverflow{i}') for i in range(10)])
        return answer
    flow._send_search = overreturn
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    assert len(rows(library)) == 5
    output = library.store.existing_step(library.run['id'], 'search:0')['output']
    assert output['result_count'] == 3 and output['fast_path_request']['returned_count'] == 10


def test_allowance_retry_fills_reserved_cancelled_slot(library, tmp_path):
    flow, scope, plan = setup(library, tmp_path)
    plan |= {'keyword_cap': 4, 'page_size': 2}
    library.store.add_usage(library.run['id'], 'provider_requests', 100, query='search:0')
    scripted(flow, [], short=True)
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, False))
    old = library.store.existing_step(library.run['id'], 'search:0')
    assert old['error_code'] == 'budget_exhausted'
    assert old['output']['fast_path_request']['request_index'] == 1
    library.run['budget']['retry_provider_requests'] = 101
    calls = []
    scripted(flow, calls, short=True)
    original = flow._send_search
    async def retry_records(*args, **kwargs):
        answer = await original(*args, **kwargs)
        return replace(answer, records=[record('Wretry_reserved_0'), record('Wretry_reserved_1')])
    flow._send_search = retry_records
    asyncio.run(fast_search.execute(flow, library.run, scope, plan, True))
    assert calls == [(None, QUERIES[0]['query_text'], 0, 2)]
    assert {r['request_index'] for r in rows(library)} == {0, 1, 2}


def test_consumer_stop_preserves_inflight_batch_and_pending_resume(library, tmp_path, monkeypatch):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    fake_embedder(lib, flow, monkeypatch)
    # Two batches: only the first finishes before the pause. The second remains
    # pending and can be resumed without resending completed document vectors.
    ids = [queued(lib, 1, 0, i, f'Wresume{i}') for i in range(65)]
    calls = []
    async def execute():
        ready = asyncio.Event()
        release = asyncio.Event()
        async def embed(self, client, texts, kind, *args):
            assert not lib.conn.in_transaction
            calls.append((kind, len(texts)))
            if kind == 'RETRIEVAL_DOCUMENT' and not ready.is_set():
                ready.set()
                await release.wait()
            return [array('f', [1., 0.]) for _ in texts]
        monkeypatch.setattr(embeddings.Embedder, 'embed', embed)
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        consumer.start()
        await ready.wait()
        lib.store.update_run(lib.run['id'], status='pause_requested')
        release.set()
        await consumer.stop()
        assert sum(r['status'] == 'embedded' for r in rows(lib)) == 64
        assert sum(r['status'] == 'pending' for r in rows(lib)) == 1
        lib.store.update_run(lib.run['id'], status='paused')
        lib.clock.advance(1000)
        lib.store.update_run(lib.run['id'], status='running')
        resumed = fast_embedding.Consumer(flow, lib.run, scope)
        resumed.start()
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        await resumed.drain(lib.store.candidates(lib.rid, 1))
        assert sum(r['status'] == 'embedded' for r in rows(lib)) == 65
    asyncio.run(asyncio.wait_for(execute(), 3))
    assert calls == [('RETRIEVAL_QUERY', 1), ('RETRIEVAL_DOCUMENT', 64), ('RETRIEVAL_QUERY', 1), ('RETRIEVAL_DOCUMENT', 1)]


def test_retry_after_cutoff_admits_only_unembedded_records(library, tmp_path, monkeypatch):
    flow, scope, plan = setup(library, tmp_path)
    plan |= {'keyword_cap': 3, 'page_size': 3}
    scripted(flow, [], short=True, fail_at=lambda q, p: not q.get('endpoint'))
    async def execute():
        consumer = fast_embedding.Consumer(flow, library.run, scope)
        flow._fast_consumers[library.run['id']] = consumer
        consumer.start()
        await fast_search.execute(flow, library.run, scope, plan, False)
        fast_path.close_stage(library.store, library.run['id'], 'search')
        fast_path.enter_stage(library.store, library.run, 'ranking')
        await consumer.drain(library.store.candidates(library.rid, 1))
        scripted(flow, [], short=True)
        await fast_search.execute(flow, library.run, scope, plan, True)
    asyncio.run(execute())
    assert all(r['status'] == 'unembedded_at_cutoff' and r['cutoff_at'] for r in rows(library))


def test_network_embedder_has_no_plan_warmup(library, tmp_path):
    flow, scope, _ = setup(library, tmp_path)
    library.store.set_setting('semantic_search', {'provider': 'gemini', 'model': embeddings.MODEL})
    async def execute():
        consumer = fast_embedding.Consumer(flow, library.run, scope)
        assert consumer.warmup is None
        await consumer.stop()
    asyncio.run(execute())


def test_off_identity_stays_frozen_after_setting_change(library, tmp_path):
    flow, scope, _ = setup(library, tmp_path)
    async def execute():
        consumer = fast_embedding.Consumer(flow, library.run, scope)
        library.store.set_setting('semantic_search', {'provider': 'builtin', 'model': local_embedding.MODEL_ID})
        assert flow._ranking_embedding(library.run, scope) == (None, 'embedding_off')
        resumed = fast_embedding.Consumer(flow, library.run, scope)
        assert resumed.embedder is None and resumed.warmup is None
        await consumer.stop()
        await resumed.stop()
    asyncio.run(execute())


@pytest.mark.parametrize('cached', [False, True])
def test_merge_resolves_head_and_cutoff_cache_without_new_batch(library, tmp_path, monkeypatch, cached):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    fake_embedder(lib, flow, monkeypatch)
    old = queued(lib, name='Wpreprint')
    head, _ = lib.store.upsert_provider_source('openalex', replace(record('Wpublished'), doi='10.9999/synthetic.published'), None)
    lib.store.add_to_corpus(lib.rid, head, 'search', scope_revision=1)
    work_id = lib.store.source(old)['work_id']
    with transaction(lib.conn):
        lib.conn.execute("UPDATE source_versions SET version_label = 'submittedVersion' WHERE id = ?", (old,))
        lib.conn.execute('UPDATE source_versions SET work_id = ? WHERE id = ?', (work_id, head))
    assert lib.store.work_heads(lib.rid)[work_id] == head
    async def execute():
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        if cached:
            lib.store.save_source_similarities(lib.rid, 1, consumer.embedder.stored_model, {head: .5})
        fast_path.close_stage(lib.store, lib.run['id'], 'search')
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        lib.clock.advance(1000)
        consumer.start()
        await consumer.drain([c for c in lib.store.candidates(lib.rid, 1) if c['source_version_id'] == head])
        return consumer
    consumer = asyncio.run(execute())
    assert all(r['status'] == ('from_store' if cached else 'unembedded_at_cutoff') for r in rows(lib))
    assert fast_path.ranking_similarities(lib.store, lib.run, consumer.embedder.stored_model) == ({head: .5} if cached else {})

"""D254 synthetic chain evidence: isolated SQLite, fake clock, scripted transport."""

import asyncio
import json
import itertools
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import canonical
from deixis.documents import acquisition
from deixis.providers import facade
from deixis.providers.common import SearchOutcome
from deixis.storage.db import transaction
from deixis.storage import db
from deixis.workflow import fast_chain, fast_embedding, fast_path, fast_search, lookups, small_batch
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from test_fast_path_clock import library, app_for, FakeClock
from test_fast_path_search import record, QUERIES
from test_fetch_overlap_flow import discover
from test_small_batch_flow import client_of


def seed(n, refs=()):
    return {"source_version_id": f"seed{n}", "openalex_id": f"W{n}", "references": list(refs)}


def setup(lib, tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, settings=settings,
                                       http=None, local_embedder=None))
    flow._chain_forms = lambda *args: {"task": ["synthetic"]}
    scope = lib.store.scope(lib.rid)
    vocabulary = {"terms": [], "outcome_terms": []}
    round_ = fast_chain.Round(flow, lib.run, scope, vocabulary)
    flow._fast_chains[lib.run["id"]] = round_
    return flow, scope, round_


def search(flow, lib, key, identities, *, refs=None, titles=None, abstracts=True):
    raw = [{"id": f"https://openalex.org/{oid}", "referenced_works": (refs or {}).get(oid, [])} for oid in identities]
    records = [replace(record(oid), raw=r, references=tuple(x.rsplit('/', 1)[-1] for x in r['referenced_works']),
                       title=(titles or {}).get(oid, record(oid).title), abstract=record(oid).abstract if abstracts else None,
                       doi=f"10.1234/{oid.lower()}") for oid, r in zip(identities, raw)]
    step = lib.store.step(lib.run['id'], key, 'provider_search:openalex')
    outcome = SearchOutcome('completed', None, 'SYNTHETIC search', 'keyless', records=records,
                            raw_payload={'results': raw})
    flow._record_search(lib.run, step, {'provider_id': 'openalex', 'query_text': 'SYNTHETIC'}, outcome, len(records))
    return records


def dispatch(records=(), *, status='completed', raw=None, error_kind=None):
    outcome = SearchOutcome(status, None, 'SYNTHETIC chain', 'keyless', records=list(records),
                            raw_payload=raw or {'results': [r.raw for r in records]}, error_kind=error_kind)
    return facade.Dispatched(outcome, 0, {})


def scripted(monkeypatch, handler):
    async def back(provider, http, operation_ids, ids, *args):
        return await handler('backward', ids)
    async def forward(provider, http, oid, cursor, limit, *args):
        assert cursor == '*'
        return await handler('forward', oid)
    monkeypatch.setattr(facade, 'dispatch_lookup', back)
    monkeypatch.setattr(facade, 'dispatch_citing', forward)


@pytest.mark.parametrize('effort,cap,back,forward', [('quick', 150, 2, 2), ('standard', 400, 4, 8), ('detailed', 800, 8, 16)])
def test_frozen_direction_caps_and_payload_order(effort, cap, back, forward):
    policy = fast_path.freeze_budget({}, effort)
    seeds = [seed(i, [f'W{10000 + n}' for n in range(700, -1, -1)]) for i in range(1, 40)]
    plan = fast_chain.request_plan(seeds, policy, {'W10700'})
    specs = plan['requests']
    assert len([s for s in specs if s['direction'] == 'backward']) == back
    assert len([s for s in specs if s['direction'] == 'forward']) == forward
    assert sum(s['limit'] for s in specs) == cap
    assert specs[0]['batch'][:2] == ['W10699', 'W10698']
    assert [s['direction'] for s in specs[:4]] == ['backward', 'forward', 'backward', 'forward']
    assert [s['cites'] for s in specs if s['direction'] == 'forward'] == [f'W{i}' for i in range(1, forward + 1)]


def test_fallback_numbering_and_allowances_do_not_restart():
    policy = fast_path.freeze_budget({}, 'quick')
    first = fast_chain.request_plan([seed(1)], policy, set())['requests']
    second = fast_chain.request_plan([seed(2, ['W3', 'W4']), seed(5)], policy, set(), first)['requests']
    assert min(s['index'] for s in second) > max(s['index'] for s in first)
    assert sum(s['direction'] == 'forward' for s in first + second) == 2
    assert len(second) == 2


@pytest.mark.parametrize('budget', [{}, {'fast_path': {'policy': 'fast_path_v1', 'chain_in_flight': 5}},
                                    {'fast_path': {'policy': 'old', 'chain_rule': 'fast_chain_v1'}}])
def test_marker_fail_closed(budget):
    assert not fast_path.chain_on(budget)


def test_semantic_snapshot_order_dedupe_reference_order_and_reuse(library, tmp_path):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W30', 'W2', 'W19'],
           refs={'W30': ['https://openalex.org/W9', 'https://openalex.org/W1']},
           titles={'W2': 'SYNTHETIC same title', 'W19': 'Synthetic SAME title'})
    async def run():
        round_.initial()
        await round_.stop()
        frozen = lib.store.existing_step(lib.run['id'], 'fast_chain:seeds')['output']
        assert [s['openalex_id'] for s in frozen['seeds']] == ['W30', 'W2']
        assert frozen['seeds'][0]['references'] == ['W9', 'W1']
        assert frozen['payload_sha256']
        # A later source page cannot rewrite the semantic snapshot.
        path = lib.store.source(frozen['seeds'][0]['source_version_id'])['provider_payload_path']
        (flow.deps.settings.payloads_dir / path).write_text('{}')
        again = fast_chain.Round(flow, lib.run, scope, round_.vocabulary)
        again.initial()
        await again.stop()
        assert lib.store.existing_step(lib.run['id'], 'fast_chain:seeds')['output'] == frozen
    # Cancel before transports start: this test only inspects durable snapshots.
    asyncio.run(run())


def test_fallback_fills_empty_semantic_snapshot_once(library, tmp_path):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', [])
    search(flow, lib, 'search:0', ['W8', 'W1'], refs={'W8': ['W99', 'W3']})
    async def run():
        round_.initial()
        round_.fallback()
        await round_.stop()
        frozen = lib.store.existing_step(lib.run['id'], 'fast_chain:seeds_fallback')['output']
        assert {s['openalex_id'] for s in frozen['seeds']} == {'W8', 'W1'}
        assert frozen['order_hash'] and frozen['pool'] == 2 and frozen['embedded'] == 0
        assert next(s for s in frozen['seeds'] if s['openalex_id'] == 'W8')['references'] == ['W99', 'W3']
        again = fast_chain.Round(flow, lib.run, scope, round_.vocabulary)
        again.initial()
        again.fallback()
        await again.stop()
        assert lib.store.existing_step(lib.run['id'], 'fast_chain:seeds_fallback')['output'] == frozen
    asyncio.run(run())


def test_concurrent_sends_bounded_ordered_writes_and_class2(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    round_.policy |= {'forward_requests': 8, 'backward_requests': 0}
    records = search(flow, lib, 'search:fast:semantic', [f'W{i}' for i in range(1, 9)])
    async def run():
        gates = {f'W{i}': asyncio.Event() for i in range(1, 9)}
        started = []
        active = peak = 0
        async def handler(direction, oid):
            nonlocal active, peak
            assert not lib.conn.in_transaction
            started.append(oid)
            active += 1
            peak = max(peak, active)
            await gates[oid].wait()
            active -= 1
            n = int(oid[1:])
            return dispatch([record(f'W{100 + n}')])
        scripted(monkeypatch, handler)
        round_.initial()
        for _ in range(10):
            await asyncio.sleep(0)
        assert peak == 5 and started == ['W1', 'W2', 'W3', 'W4', 'W5']
        gates['W5'].set()
        gates['W4'].set()
        for _ in range(10):
            await asyncio.sleep(0)
        assert lib.store.find_source_by_identifier('openalex', 'W105') is None
        for gate in gates.values():
            gate.set()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        assert round_.done() and peak == 5
        queued = list(lib.conn.execute('SELECT request_index, position, class FROM fast_path_embedding_queue ORDER BY request_index'))
        assert [tuple(r) for r in queued] == [(i, 0, 2) for i in range(8)]
        candidates = [r['source_version_id'] for r in lib.store.candidates(lib.rid, 1)]
        assert candidates[-8:] == [lib.store.find_source_by_identifier('openalex', f'W{101 + i}') for i in range(8)]
        round_.summary()
        assert lib.store.existing_step(lib.run['id'], 'fast_chain:summary')['output']['accepted'] == 8
        await round_.stop()
    asyncio.run(run())


def test_chain_response_before_keyword_page_preserves_heads_classes_and_order_hash(library, tmp_path, monkeypatch):
    from deixis.workflow import ranking, store as store_module
    lib = library
    flow, _, _ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1'])
    keyword = replace(record('W200'), doi='10.48550/arxiv.2601.00001',
                      version_label='submittedVersion', merge_by_doi=False,
                      references=('W201', 'W300'),
                      raw={'id': 'W200', 'referenced_works': ['W201', 'W300']})
    chained = replace(keyword, provider_record_id='W201', identifiers={'openalex': 'W201'},
                      raw={'id': 'W201'}, references=())
    duplicate = record('W300')
    results = []
    for chain_first in (True, False):
        conn = db.connect(tmp_path / f'arrival-{chain_first}.sqlite')
        lib.conn.backup(conn)
        clock = FakeClock()
        store = Store(conn, clock)
        clock.store = store
        copy = SimpleNamespace(conn=conn, store=store, clock=clock, rid=lib.rid, run=lib.run)
        counter = itertools.count()
        monkeypatch.setattr(store_module, 'new_id', lambda prefix: f'{prefix}_synthetic_{next(counter):06d}')
        timestamps = itertools.count()
        monkeypatch.setattr(store_module, 'now', lambda: (clock.now() + timedelta(milliseconds=next(timestamps))).isoformat())
        copied_flow, scope, round_ = setup(copy, tmp_path)
        step = store.step(lib.run['id'], 'search:0', 'provider_search:openalex')
        async def run():
            gate = asyncio.Event()
            async def handler(direction, oid):
                if direction == 'backward':
                    return dispatch()
                await gate.wait()
                return dispatch([chained, duplicate])
            scripted(monkeypatch, handler)
            round_.initial()
            await asyncio.sleep(0)
            if chain_first:
                gate.set()
                await asyncio.gather(*round_.tasks)
                await asyncio.sleep(0)
                assert not store.find_source_by_identifier('openalex', 'W201')
            outcome = SearchOutcome('completed', None, 'SYNTHETIC keyword', 'keyless',
                                    records=[keyword, duplicate], raw_payload={'results': [keyword.raw, duplicate.raw]})
            copied_flow._record_search(lib.run, step, QUERIES[0], outcome, 2,
                                      admission={'class': 1, 'request_index': 0, 'limit': 2})
            if not chain_first:
                gate.set()
                await asyncio.gather(*round_.tasks)
            round_.fallback()
            fallback = store.existing_step(lib.run['id'], 'fast_chain:plan_fallback')['output']
            assert next(s['batch'] for s in fallback['requests'] if s['direction'] == 'backward') == ['W201']
            round_.admit.set()
            await asyncio.gather(*round_.writers)
            first = store.find_source_by_identifier('openalex', 'W200')
            second = store.find_source_by_identifier('openalex', 'W201')
            assert first != second and store.source(first)['work_id'] == store.source(second)['work_id']
            heads = store.work_heads(lib.rid)
            assert heads[store.source(first)['work_id']] == first
            classes = [tuple(r) for r in conn.execute(
                'SELECT source_version_id, class FROM fast_path_embedding_queue ORDER BY source_version_id')]
            assert dict(classes)[store.find_source_by_identifier('openalex', 'W300')] == 1
            versions, _, pool = ranking.pool_rows(store, lib.rid, 1)
            for row in pool:
                row['cited_by_count'] = None
            listing = small_batch.build_list({'ranking_version': 3, 'pool': pool, 'versions': versions,
                'verified': [], 'query_words': ['synthetic'], 'blocks': {}, 'embedding_model': None,
                'similarities': {}, 'off_reason': 'SYNTHETIC off', 'compared_terms': [], 'user_priority': []})
            results.append((heads, classes, listing['order_hash'], fallback))
            await round_.stop()
        try:
            asyncio.run(run())
        finally:
            conn.close()
    assert results[0] == results[1]


def test_stop_before_admission_keeps_buffered_response_unknown(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1'])
    async def handler(*args):
        return dispatch([record('W200')])
    scripted(monkeypatch, handler)
    async def run():
        round_.initial()
        await asyncio.gather(*round_.tasks)
        assert round_.replies
        await round_.stop()
        assert lib.store.existing_step(lib.run['id'], 'chain:fast:0')['status'] == 'running'
        assert not lib.store.find_source_by_identifier('openalex', 'W200')
        round_.close_open('interrupted')
        assert lib.store.existing_step(lib.run['id'], 'chain:fast:0')['status'] == 'outcome_unknown'
    asyncio.run(run())


def test_resume_with_fallback_plan_opens_admission(library, tmp_path):
    flow, scope, round_ = setup(library, tmp_path)
    assert not round_.admit.is_set()
    step = library.store.step(library.run['id'], 'fast_chain:plan_fallback', 'code:fast_chain')
    library.store.finish_step(step['id'], 'succeeded', output={'requests': []})
    restarted = fast_chain.Round(flow, library.run, scope, round_.vocabulary)
    assert restarted.admit.is_set()


@pytest.mark.parametrize('offset,late', [(-.001, False), (0, True), (.001, True)])
def test_arrival_boundary_no_late_record_link_or_queue(library, tmp_path, monkeypatch, offset, late):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1'])
    fast_path.enter_stage(lib.store, lib.run, 'ranking')
    async def handler(direction, oid):
        delta = (round_.cutoff() - lib.clock.now()).total_seconds() + offset
        lib.clock.advance(delta)
        return dispatch([record('W200')])
    scripted(monkeypatch, handler)
    async def run():
        round_.initial()
        await asyncio.gather(*round_.tasks)
        lib.clock.advance(1)
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        output = lib.store.existing_step(lib.run['id'], 'chain:fast:0')['output']
        assert output['late'] == late
        assert bool(lib.store.find_source_by_identifier('openalex', 'W200')) != late
        assert lib.conn.execute('SELECT COUNT(*) FROM chain_links').fetchone()[0] == int(not late)
        assert lib.conn.execute('SELECT COUNT(*) FROM fast_path_embedding_queue').fetchone()[0] == int(not late)
        row = lib.conn.execute("SELECT raw_payload_path FROM search_runs WHERE query_text LIKE 'chain:%'").fetchone()
        assert row and (flow.deps.settings.payloads_dir / row[0]).exists()
        round_.summary()
        assert lib.store.existing_step(lib.run['id'], 'fast_chain:summary')['output']['late_records'] == int(late)
        await round_.stop()
    asyncio.run(run())


def test_pause_moves_cutoff_and_enforcement_is_required(library, tmp_path):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    assert round_.cutoff() is None
    fast_path.enter_stage(lib.store, lib.run, 'ranking')
    original = round_.cutoff()
    lib.clock.advance(10)
    lib.store.update_run(lib.run['id'], status='paused')
    assert round_.cutoff() is None
    lib.clock.advance(60)
    lib.store.update_run(lib.run['id'], status='running')
    fast_path.enter_stage(lib.store, lib.run, 'ranking')
    assert round_.cutoff() == original + timedelta(seconds=60)
    lib.run['budget']['fast_path']['enforced_stages'] = ['read']
    assert round_.cutoff() is None


def test_daily_budget_and_cutoff_refuse_unsent_requests(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1', 'W2'])
    called = []
    async def handler(*args):
        called.append(args)
        return dispatch()
    scripted(monkeypatch, handler)
    reset = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with transaction(lib.conn):
        lib.store._note_openalex_budget(lib.rid, lib.run['id'], reset, skipped=False)
    async def run():
        round_.initial()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        assert not called
        assert all(lib.store.step_output(s['id'])['unsent'] == 'openalex_budget' for s in lib.store.run_steps(lib.run['id'])
                   if s['operation_key'].startswith('chain:fast:'))
        await round_.stop()
    asyncio.run(run())


def test_unknown_and_successful_requests_never_resend(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1', 'W2'])
    called = []
    async def handler(*args):
        called.append(args)
        return dispatch()
    scripted(monkeypatch, handler)
    async def run():
        round_.initial()
        # No provider task has run yet: mimic worker recovery of request zero.
        step = lib.store.existing_step(lib.run['id'], 'chain:fast:0')
        if step is None:
            step = lib.store.step(lib.run['id'], 'chain:fast:0', 'provider_chain:openalex')
        lib.store.finish_step(step['id'], 'outcome_unknown', output={'unknown': True})
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        assert len(called) == 1
        round_.initial()
        await asyncio.gather(*round_.writers)
        assert len(called) == 1
        await round_.stop()
    asyncio.run(run())


def test_empty_embedding_queue_waits_for_chain_and_closes_atomically(library, tmp_path, monkeypatch):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1'])
    lib.store.set_setting('semantic_search', {'provider': 'off'})
    async def run():
        gate = asyncio.Event()
        async def handler(*args):
            await gate.wait()
            return dispatch([record('W200')])
        scripted(monkeypatch, handler)
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        flow._fast_consumers[lib.run['id']] = consumer
        consumer.start()
        round_.initial()
        round_.fallback()
        round_.admit.set()
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        drain = asyncio.create_task(consumer.drain(lib.store.candidates(lib.rid, 1)))
        for _ in range(10):
            await asyncio.sleep(0)
        assert not drain.done()
        assert lib.store.existing_step(lib.run['id'], 'fast_chain:summary') is None
        gate.set()
        await asyncio.wait_for(drain, 2)
        assert lib.store.existing_step(lib.run['id'], 'fast_chain:summary')['status'] == 'succeeded'
        assert lib.store.existing_step(lib.run['id'], 'source_similarity')['output']['cutoff_at']
        status = lib.conn.execute("SELECT status FROM fast_path_embedding_queue WHERE class=2").fetchone()[0]
        assert status == 'unembedded_at_cutoff'
    asyncio.run(run())


@pytest.mark.parametrize('provider', ['semantic_scholar', 'crossref', 'scopus'])
def test_shortlist_plans_and_legacy_output(library, tmp_path, monkeypatch, provider):
    lib = library
    flow, scope, _ = setup(lib, tmp_path)
    records = search(flow, lib, 'search:0', ['W1', 'W2', 'W3'], abstracts=False)
    monkeypatch.setattr(lookups, 'in_scope', lambda *args: True)
    only = {lib.store.find_source_by_identifier('openalex', 'W2')}
    def plan(**kwargs):
        if provider == 'semantic_scholar':
            return lookups.plan_semantic_scholar(lib.store, lib.rid, 1, scope, (), **kwargs)
        if provider == 'crossref':
            return lookups.plan_crossref(lib.store, lib.rid, 1, scope, (), 0, **kwargs)
        return lookups.plan_scopus(lib.store, lib.rid, 1, (), 0, **kwargs)
    old = plan()
    assert old == plan(only=None) and 'outside_shortlist' not in old
    limited = plan(only=only)
    groups = limited.get('batches', limited.get('chunks'))
    assert {r['source_version_id'] for group in groups for r in group} == only
    assert limited['outside_shortlist'] == 2


@pytest.mark.parametrize('marker', [False, True])
def test_integrated_new_and_slice2_frozen_paths(tmp_path, monkeypatch, marker):
    original = fast_path.freeze_budget
    if not marker:
        def old(*args):
            policy = original(*args)
            for key in ('chain_rule', 'chain_in_flight', 'policy_hash'):
                policy.pop(key)
            return policy | {'policy_hash': canonical.sha256_hex(policy)}
        monkeypatch.setattr(fast_path, 'freeze_budget', old)
    app = app_for(tmp_path, FakeClock(), 'on')
    if marker:
        fallback = fast_chain.Round.fallback
        def charged(self):
            assert fast_path.stage_deadline(self.store, self.run, 'ranking') is not None
            return fallback(self)
        monkeypatch.setattr(fast_chain.Round, 'fallback', charged)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client)
        assert run['status'] == 'completed', run
        store = app.state.store
        steps = store.run_steps(run_id)
        assert any(s['operation_key'] == 'fast_chain:summary' for s in steps) == marker
        listing = store.existing_step(run_id, small_batch.LIST_KEY)['output']
        assert ('fast_path' in listing['manifest']) == marker
        assert small_batch.replay(listing['manifest'])['fused'] == listing['automatic_order']
        intervals = [r[0] for r in store.conn.execute('SELECT stage FROM fast_path_intervals WHERE run_id=? ORDER BY rowid', (run_id,))]
        assert ('lookups' in intervals) != marker
        if marker:
            plans = [store.step_output(s['id']) for s in steps if s['operation_key'].startswith('lookup_plan:')]
            assert all('outside_shortlist' in p for p in plans if p.get('skipped') != 'out_of_scope')


def test_cutoff_collects_early_buffer_behind_interrupted_request(library, tmp_path, monkeypatch):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1', 'W2'])
    lib.store.set_setting('semantic_search', {'provider': 'off'})
    async def run():
        blocked = asyncio.Event()
        answered = asyncio.Event()
        async def handler(direction, oid):
            if oid == 'W1':
                await blocked.wait()
            else:
                answered.set()
            return dispatch([record('W200' if oid == 'W2' else 'W100')])
        scripted(monkeypatch, handler)
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        flow._fast_consumers[lib.run['id']] = consumer
        consumer.start()
        round_.initial()
        round_.fallback()
        round_.admit.set()
        fast_path.enter_stage(lib.store, lib.run, 'ranking')
        await answered.wait()
        assert not lib.store.find_source_by_identifier('openalex', 'W200')
        drain = asyncio.create_task(consumer.drain(lib.store.candidates(lib.rid, 1)))
        await asyncio.sleep(0)
        lib.clock.advance((round_.cutoff() - lib.clock.now()).total_seconds())
        await asyncio.wait_for(drain, 2)
        assert lib.store.find_source_by_identifier('openalex', 'W200')
        assert not lib.store.find_source_by_identifier('openalex', 'W100')
        assert all(t.done() for t in round_.tasks + round_.writers)
        summary = lib.store.existing_step(lib.run['id'], 'fast_chain:summary')['output']
        assert summary['unknown'] == 1 and summary['accepted'] == 1
        assert lib.store.existing_step(lib.run['id'], 'chain:fast:0')['status'] == 'outcome_unknown'
    asyncio.run(run())


def test_filter_keeps_links_but_excludes_embedding_and_preserves_raw_position(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1'])
    async def handler(*args):
        return dispatch([replace(record('W10'), title='Other', abstract='Unrelated'), record('W20')])
    scripted(monkeypatch, handler)
    async def run():
        round_.initial()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        assert not lib.store.find_source_by_identifier('openalex', 'W10')
        assert lib.conn.execute('SELECT COUNT(*) FROM chain_links').fetchone()[0] == 2
        row = lib.conn.execute('SELECT position FROM fast_path_embedding_queue WHERE class=2').fetchone()
        assert row[0] == 1
        candidate = next(c for c in lib.store.candidates(lib.rid, 1) if c['source_version_id'] == lib.store.find_source_by_identifier('openalex', 'W20'))
        from deixis.workflow.flow import CHAIN_RANK_BASE
        assert candidate['rank'] == CHAIN_RANK_BASE + 1
        await round_.stop()
    asyncio.run(run())


def test_quota_response_blocks_waiting_sends_and_survives_restart(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    round_.semaphore = asyncio.Semaphore(1)
    search(flow, lib, 'search:fast:semantic', ['W1', 'W2'])
    calls = []
    async def handler(*args):
        calls.append(args)
        return dispatch(status='rate_limited', error_kind='quota_exhausted')
    scripted(monkeypatch, handler)
    async def run():
        round_.initial()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        assert len(calls) == 1 and lib.store.openalex_budget_reset()
        assert lib.store.existing_step(lib.run['id'], 'chain:fast:1')['output']['unsent'] == 'openalex_budget'
        await round_.stop()
    asyncio.run(run())
    restarted = ResearchFlow(flow.deps)
    assert restarted._openalex_budget_of(lib.run['id']).exhausted


def test_chain_starts_while_keyword_transport_is_waiting(library, tmp_path, monkeypatch):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    plan = fast_search.build_plan(lib.store, lib.run, scope, QUERIES)
    plan |= {'keyword_cap': 2, 'page_size': 2}
    fast_path.enter_stage(lib.store, lib.run, 'search')
    async def run():
        keyword_started = asyncio.Event()
        chain_started = asyncio.Event()
        async def send(run_id, connector, query, limit, page=None, **kwargs):
            assert not lib.conn.in_transaction
            if query.get('endpoint') == 'semantic':
                raw = {'id': 'https://openalex.org/W1', 'referenced_works': []}
                return SearchOutcome('completed', None, 'SYNTHETIC', 'keyless',
                                     records=[replace(record('W1'), raw=raw)], raw_payload={'results': [raw]})
            keyword_started.set()
            await asyncio.wait_for(chain_started.wait(), 2)
            return SearchOutcome('zero_results', None, 'SYNTHETIC', 'keyless')
        async def handler(*args):
            await keyword_started.wait()
            chain_started.set()
            return dispatch()
        flow._send_search = send
        scripted(monkeypatch, handler)
        await asyncio.wait_for(fast_search.execute(flow, lib.run, scope, plan, False), 2)
        round_.fallback()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        assert chain_started.is_set()
        await round_.stop()
    asyncio.run(run())


def test_list_frozen_resume_starts_no_chain_task(library, tmp_path):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    listing = lib.store.step(lib.run['id'], small_batch.LIST_KEY, 'code:small_batch_list')
    lib.store.finish_step(listing['id'], 'succeeded', output={'SYNTHETIC': 'frozen'})
    pending = lib.store.step(lib.run['id'], 'chain:fast:0', 'provider_chain:openalex')
    restarted = fast_chain.Round(flow, lib.run, scope, round_.vocabulary)
    restarted.initial()
    restarted.fallback()
    assert not restarted.tasks and not restarted.writers
    assert lib.store.step_output(pending['id'])['unsent'] == 'list_frozen'
    assert lib.store.step_output(listing['id']) == {'SYNTHETIC': 'frozen'}


def test_resume_after_embedding_cutoff_does_not_reopen_chain(library, tmp_path):
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    summary = lib.store.step(lib.run['id'], 'fast_chain:summary', 'code:fast_chain')
    lib.store.finish_step(summary['id'], 'succeeded', output={'SYNTHETIC': 'closed'})
    restarted = fast_chain.Round(flow, lib.run, scope, round_.vocabulary)
    restarted.initial()
    restarted.fallback()
    assert not restarted.tasks and not restarted.writers
    assert lib.store.step_output(summary['id']) == {'SYNTHETIC': 'closed'}


def test_marked_run_paces_http_attempts_and_retries_only(monkeypatch):
    import httpx
    from deixis.providers import common, pacing
    starts = []
    async def pace():
        starts.append('paced')
    monkeypatch.setattr(pacing.FAST_OPENALEX_PACER, 'wait', pace)
    async def run(marked):
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(429, headers={'retry-after': '0'}) if len(calls) == 1 else httpx.Response(200, json={})
        token = common.fast_openalex_pacing.set(marked)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                await common.send(client, 'https://api.openalex.org/works', {}, {}, 'SYNTHETIC', 'keyless')
        finally:
            common.fast_openalex_pacing.reset(token)
    asyncio.run(run(False))
    assert not starts
    asyncio.run(run(True))
    assert starts == ['paced', 'paced']


def test_missing_reference_payload_still_allows_forward_fallback(library, tmp_path):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    records = search(flow, lib, 'search:0', ['W1'])
    source = lib.store.source(lib.store.find_source_by_identifier('openalex', 'W1'))
    (flow.deps.settings.payloads_dir / source['provider_payload_path']).write_text('{}')
    async def run():
        round_.initial()
        round_.fallback()
        await round_.stop()
        output = lib.store.existing_step(lib.run['id'], 'fast_chain:seeds_fallback')['output']
        assert output['seeds'][0]['openalex_id'] == 'W1'
        assert not output['seeds'][0]['references_read']
        plan = lib.store.existing_step(lib.run['id'], 'fast_chain:plan_fallback')['output']
        assert [s['direction'] for s in plan['requests']] == ['forward']
    asyncio.run(run())


def test_provider_overflow_cannot_expand_admitted_record_budget(library, tmp_path, monkeypatch):
    lib = library
    flow, _, round_ = setup(lib, tmp_path)
    search(flow, lib, 'search:fast:semantic', ['W1'])
    async def handler(*args):
        return dispatch([record(f'W{100 + i}') for i in range(80)])
    scripted(monkeypatch, handler)
    async def run():
        round_.initial()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        output = lib.store.existing_step(lib.run['id'], 'chain:fast:0')['output']
        assert output['raw_returned'] == 80 and output['admitted_returned'] == 25
        assert lib.conn.execute('SELECT COUNT(*) FROM fast_path_embedding_queue WHERE class=2').fetchone()[0] == 25
        assert not lib.store.find_source_by_identifier('openalex', 'W125')
        await round_.stop()
    asyncio.run(run())


def test_embedding_reply_after_cutoff_is_stored_but_not_ranked(library, tmp_path, monkeypatch):
    from test_fast_path_search import fake_embedder, queued
    lib = library
    flow, scope, round_ = setup(lib, tmp_path)
    fake_embedder(lib, flow, monkeypatch, advance=True)
    svid = queued(lib, 2, name='W200')
    fast_path.enter_stage(lib.store, lib.run, 'ranking')
    async def run():
        consumer = fast_embedding.Consumer(flow, lib.run, scope)
        flow._fast_consumers[lib.run['id']] = consumer
        consumer.start()
        await consumer.drain(lib.store.candidates(lib.rid, 1))
        stored = lib.store.source_similarities(lib.rid, 1, consumer.embedder.stored_model)
        assert svid in stored
        assert svid not in fast_path.ranking_similarities(lib.store, lib.run, consumer.embedder.stored_model)
        assert lib.conn.execute('SELECT status FROM fast_path_embedding_queue WHERE source_version_id=?', (svid,)).fetchone()[0] == 'unembedded_at_cutoff'
    asyncio.run(run())


@pytest.mark.parametrize('origin,allowed', [('lookup_semantic_scholar', True), ('lookup_crossref_jats', True),
                                           ('lookup_scopus', True), ('provider_openalex_inverted_index', False)])
def test_read_snapshot_admits_only_lookup_enrichment_and_keeps_ranking_frozen(library, tmp_path, origin, allowed):
    from deixis.workflow import ranking
    lib = library
    flow, _, _ = setup(lib, tmp_path)
    search(flow, lib, 'search:0', ['W1'], abstracts=False)
    svid = lib.store.find_source_by_identifier('openalex', 'W1')
    versions = small_batch.json_value(ranking._versions(lib.store, lib.rid))
    listing = {'manifest': {'versions': versions}, 'manifest_hash': canonical.sha256_hex(versions),
               'items': [{'head': svid, 'work_id': versions[svid]['work_id'], 'versions': [svid]}]}
    frozen = json.dumps(listing, sort_keys=True)
    lib.store._insert_passage(svid, None, 'abstract', None, None, origin, 'SYNTHETIC lookup', None,
                              'SYNTHETIC acquired abstract')
    snapshot = fast_chain.read_versions(flow, lib.run, listing)
    assert json.dumps(listing, sort_keys=True) == frozen
    assert bool(snapshot['lookup_enriched']) == allowed
    assert snapshot['changed_items'] == int(not allowed)
    assert small_batch.unchanged_heads(lib.store, lib.rid, listing, listing['items'], versions=snapshot['versions']) == ([svid] if allowed else [])
    # A later mutation is still caught by the read guard and cannot rewrite its snapshot.
    lib.conn.execute("UPDATE source_versions SET title='SYNTHETIC changed' WHERE id=?", (svid,))
    assert not small_batch.unchanged_heads(lib.store, lib.rid, listing, listing['items'], versions=snapshot['versions'])
    assert fast_chain.read_versions(flow, lib.run, listing) == snapshot

"""D254 synthetic chain evidence: isolated SQLite, fake clock, scripted transport."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from deixis.config import Settings
from deixis.providers import facade
from deixis.providers.common import SearchOutcome
from deixis.storage.db import transaction
from deixis.storage import db
from deixis.workflow import fast_chain, fast_path, lookups, small_batch
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from test_fast_path_clock import library, app_for, FakeClock
from test_fast_path_search import record
from overlap_flow_helpers import discover
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


def test_integrated_chain_path(tmp_path, monkeypatch):
    app = app_for(tmp_path, FakeClock())
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
        assert any(s['operation_key'] == 'fast_chain:summary' for s in steps)
        listing = store.existing_step(run_id, small_batch.LIST_KEY)['output']
        assert 'fast_path' in listing['manifest']
        assert small_batch.replay(listing['manifest'])['fused'] == listing['automatic_order']
        intervals = [r[0] for r in store.conn.execute('SELECT stage FROM fast_path_intervals WHERE run_id=? ORDER BY rowid', (run_id,))]
        assert 'lookups' not in intervals
        plans = [store.step_output(s['id']) for s in steps if s['operation_key'].startswith('lookup_plan:')]
        assert all('outside_shortlist' in p for p in plans if p.get('skipped') != 'out_of_scope')


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


# ---- the chain's attempt budget: logical requests vs. HTTP attempts (review of slice 3a) ----------
# Ported from the old chain's total-limit tests (`test_chaining_flow.py` before slice 3a): the limit the protocol
# records (`chaining.policy()["attempt_limit"]`) is the one `fast_chain.Round.fetch` enforces, per effort.

@pytest.fixture(params=['quick'])
def effort_library(request, tmp_path):
    from deixis.domain.rules import TEST_EFFORT_BUDGETS
    effort = request.param
    conn = db.connect(tmp_path / 'library.sqlite')
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research('SYNTHETIC chain budget', 'academic', effort, ['openalex'], 'fake', 'fake-model', 'en')
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, 'off')
    budget['fast_path'] = fast_path.freeze_budget(budget, effort)
    run = store.create_run(rid, 'discovery', budget, None)
    store.update_run(run['id'], status='running')
    yield SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run['id']))
    conn.close()


class ChainTransport:
    """Mocked OpenAlex for chain requests, keyed by their `filter` (one key per logical request).

    `worst`: every attempt fails as late as the policy allows — the effort's rate-limit retries answered 429, then a
    refused connection (sent nothing), which `fetch` retries `MAX_TRANSIENT_NETWORK_RETRIES` times. Otherwise every
    attempt answers an empty page. A key `hang` returns True for waits until the test cancels it.
    """

    def __init__(self, wait, worst=True, hang=lambda key, order: False):
        self.per, self.worst, self.hang = 1 + wait, worst, hang
        self.attempts, self.order, self.hung = {}, [], set()
        self.active = self.peak = 0

    async def __call__(self, request):
        key = request.url.params['filter']
        if key not in self.attempts:
            self.order.append(key)
        n = self.attempts[key] = self.attempts.get(key, 0) + 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0)
            if self.hang(key, self.order.index(key)):
                self.hung.add(key)
                await asyncio.Event().wait()
            if not self.worst:
                return httpx.Response(200, json={'meta': {'count': 0, 'next_cursor': None}, 'results': []})
            if n % self.per:
                return httpx.Response(429, headers={'retry-after': '0'})
            raise httpx.ConnectError('SYNTHETIC refused', request=request)
        finally:
            self.active -= 1


def no_waiting(monkeypatch):
    """The retry waits (Retry-After 0, `fetch`'s 1.5 s backoff) yield instead of sleeping."""
    real = asyncio.sleep
    async def sleep(delay, result=None):
        return await real(0, result)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    return real


def budget_seeds(flow, lib):
    """`chain_seeds` semantic seeds, each with 50 unheld references, so the plan fills both direction allowances."""
    ids = [f'W{i}' for i in range(1, lib.run['budget']['fast_path']['chain_seeds'] + 1)]
    search(flow, lib, 'search:fast:semantic', ids,
           refs={oid: [f'https://openalex.org/W{100000 + 100 * i + r}' for r in range(50)] for i, oid in enumerate(ids, 1)})


def chain_steps(lib):
    return [s | {'output': lib.store.step_output(s['id']) or {}} for s in lib.store.run_steps(lib.run['id'])
            if s['operation_key'].startswith('chain:fast:')]


def spent(lib):
    return lib.store.run(lib.run['id'])['usage'].get('chain_requests', 0)


def test_a_restart_counts_spent_attempts_and_sends_nothing_twice(effort_library, tmp_path, monkeypatch):
    """Crash with two requests done and the next ones in flight; the worker's recovery marks the in-flight ones
    `outcome_unknown`; a new process resumes the plan. Only never-sent requests go out, and the budget it checks
    holds every attempt the first process spent or reserved."""
    from deixis.domain.rules import PROVIDER_WAIT
    from deixis.workflow import chaining
    lib = effort_library
    flow, scope, round_ = setup(lib, tmp_path)
    wait = PROVIDER_WAIT[scope['effort']]
    fast = lib.run['budget']['fast_path']
    limit = chaining.attempt_limit(fast, scope['effort'])
    requests = fast['backward_requests'] + fast['forward_requests']
    in_flight = min(fast['chain_in_flight'], requests - 2)
    budget_seeds(flow, lib)
    real_sleep = no_waiting(monkeypatch)
    first = ChainTransport(wait, hang=lambda key, order: order >= 2)
    async def crash():
        flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(first))
        round_.initial()
        round_.admit.set()
        for _ in range(5000):
            done = [k for k in first.order[:2] if first.attempts[k] == first.per * 3]
            if len(first.hung) == in_flight and len(done) == 2:
                break
            await real_sleep(0)
        for task in round_.tasks + round_.writers:
            task.cancel()
        await asyncio.gather(*round_.tasks, *round_.writers, return_exceptions=True)
        await flow.deps.http.aclose()
    asyncio.run(crash())
    assert len(first.hung) == in_flight
    with transaction(lib.conn):
        lib.conn.execute("UPDATE run_steps SET status = 'outcome_unknown' WHERE status = 'running'")
    # Two requests spent their whole share; each interrupted one holds its reservation (one attempt plus its retries).
    before = spent(lib)
    assert before == 2 * first.per * 3 + in_flight * first.per
    pending = [s['operation_key'] for s in chain_steps(lib) if s['status'] == 'pending']
    assert len(pending) == requests - 2 - in_flight

    flow2, _, resumed = setup(lib, tmp_path)
    second = ChainTransport(wait)
    async def resume():
        flow2.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(second))
        resumed.initial()
        resumed.admit.set()
        await asyncio.gather(*resumed.writers)
        await resumed.stop()
        await flow2.deps.http.aclose()
    asyncio.run(resume())
    assert not set(second.attempts) & set(first.attempts)
    assert len(second.attempts) == len(pending)
    assert spent(lib) == before + sum(second.attempts.values()) <= limit
    steps = {s['operation_key']: s for s in chain_steps(lib)}
    assert all(steps[key]['status'] != 'pending' and not steps[key]['output'].get('unsent') for key in pending)
    # What the first process sent stays closed: written as failed, or `outcome_unknown` when the crash came first.
    sent_first = [s for key, s in steps.items() if key not in pending]
    assert len(sent_first) == 2 + in_flight and all(s['status'] in ('failed', 'outcome_unknown') for s in sent_first)
    assert sum(s['status'] == 'outcome_unknown' for s in sent_first) >= in_flight

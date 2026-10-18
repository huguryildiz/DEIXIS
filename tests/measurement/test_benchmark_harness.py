"""Benchmark harness: settings read back, the per-question stop rule and arms B/C from one run. Synthetic rows only:
no DEIXIS server, keys or network."""
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from scripts.benchmark import bioasq_run, harness

GOOD_SEMANTIC = {'provider': 'voyage', 'model': 'voyage-4-lite'}
GOOD_RERANK = {'enabled': True, 'provider': 'voyage', 'model': 'rerank-3-lite', 'pool_factor': 4.0,
               'timeout_seconds': 180, 'max_candidates': 400}
RERANK_STEP = {'provider': 'voyage', 'model': 'rerank-3-lite', 'pool_factor': 4.0, 'read_top': 50,
               'candidate_ids': ['a', 'b', 'c'], 'status': 'succeeded'}
LISTING = {'order': ['b', 'a', 'c'], 'automatic_order': ['a', 'b', 'c'],
           'reranker': {'provider': 'voyage', 'model': 'rerank-3-lite', 'applied': True, 'reranked': 3}}


class FakeServer:
    """The HTTP calls the harness makes, and a library file it reads like DEIXIS's."""

    def __init__(self, path, semantic=GOOD_SEMANTIC, rerank=GOOD_RERANK, store_puts=True):
        self.path, self.puts, self.store_puts = path, [], store_puts
        self.state = {'/api/semantic-search': dict(semantic), '/api/reranking': dict(rerank)}
        self.http = SimpleNamespace(post=lambda path: None)
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript('CREATE TABLE run_steps (run_id, operation_key, status, output_json);'
                               'CREATE TABLE runs (id, status, pause_reason, stage);')

    def put(self, path, body):
        self.puts.append((path, body))
        if self.store_puts:
            self.state[path] |= body

    def get(self, path):
        return self.state[path]

    def post(self, path, body):
        if path == '/api/researches':
            return {'research': {'id': 'res1'}}
        return {'id': 'run1'}

    def db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, key, status, output, run='run1'):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO run_steps VALUES (?, ?, ?, ?)', (run, key, status, json.dumps(output)))

    def run_state(self, status, reason=None, stage='search', run='run1'):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO runs VALUES (?, ?, ?, ?)', (run, status, reason, stage))


def good_run(server, listing=LISTING, embedding=None):
    server.add('source_similarity', 'succeeded',
               embedding or {'provider': 'voyage', 'stored_model': 'voyage:voyage-4-lite@1024'})
    server.add(harness.RERANK_KEY, 'succeeded', RERANK_STEP)
    server.add('small_batch:v1:list', 'succeeded', listing)
    server.run_state('running')


def test_configure_writes_then_reads_back(tmp_path):
    server = FakeServer(tmp_path / 'lib.sqlite', semantic={'provider': 'gemini', 'model': 'gemini-embedding-2'},
                        rerank={'enabled': False, 'provider': None, 'model': None, 'pool_factor': 4.0,
                                'timeout_seconds': 180})
    server.state['/api/reranking']['model'] = 'rerank-3-lite'  # the server names Voyage's model once Voyage is on
    got = harness.configure(server)
    assert [p for p, _ in server.puts] == ['/api/semantic-search', '/api/reranking']
    assert got['embedding'] == GOOD_SEMANTIC and got['reranker']['enabled'] is True


def test_settings_that_do_not_stick_stop_the_run(tmp_path):
    server = FakeServer(tmp_path / 'lib.sqlite', semantic={'provider': 'gemini', 'model': 'gemini-embedding-2'},
                        store_puts=False)
    with pytest.raises(harness.Stop, match='settings differ'):
        harness.configure(server)


def test_problems_empty_when_embedding_and_rerank_ran(tmp_path):
    server = FakeServer(tmp_path / 'lib.sqlite')
    good_run(server)
    with closing(server.db()) as conn:
        assert harness.problems(conn, 'run1', LISTING) == []


@pytest.mark.parametrize('similarity, listing, expected', [
    (('failed', {'provider': 'gemini', 'stored_model': 'gemini-embedding-2'}), LISTING, 'source_similarity failed'),
    (('succeeded', {'provider': 'gemini', 'stored_model': 'gemini-embedding-2'}), LISTING, 'embedding gemini'),
    (('succeeded', {'provider': 'voyage', 'stored_model': 'voyage:voyage-4-lite@1024'}),
     LISTING | {'reranker': {'applied': False, 'reason': 'timeout'}}, 'rerank not applied: timeout'),
    (('succeeded', {'provider': 'voyage', 'stored_model': 'voyage:voyage-4-lite@1024'}),
     {k: v for k, v in LISTING.items() if k != 'reranker'}, 'no reranker in the list'),
])
def test_problems_name_what_went_wrong(tmp_path, similarity, listing, expected):
    server = FakeServer(tmp_path / 'lib.sqlite')
    server.add('source_similarity', *similarity)
    server.add(harness.RERANK_KEY, 'succeeded', RERANK_STEP)
    with closing(server.db()) as conn:
        assert expected in '; '.join(harness.problems(conn, 'run1', listing))


def test_arms_come_from_one_list():
    assert harness.arms(LISTING) == {'fused': ['a', 'b', 'c'], 'rerank': ['b', 'a', 'c']}


def test_check_arm_refuses_mixed_settings_but_not_new_commits():
    one = {'settings': {'embedding': GOOD_SEMANTIC, 'commit': 'x', 'date': '1'}}
    same = {'settings': {'embedding': GOOD_SEMANTIC, 'commit': 'y', 'date': '2'}}
    other = {'settings': {'embedding': {'provider': 'gemini'}, 'commit': 'x', 'date': '1'}}
    assert harness.check_arm('a', [one, same])['commits'] == ['x', 'y']
    assert harness.check_arm('old', [{}, {}])['settings'] is None
    with pytest.raises(harness.Stop, match='2 different settings'):
        harness.check_arm('a', [one, other])


def run(tmp_path, monkeypatch, server, budget=None):
    monkeypatch.setattr(bioasq_run, 'secret', lambda name: 'k')
    monkeypatch.setattr(harness, 'budget_stop', lambda client, key, floor: budget)
    monkeypatch.setattr(harness, 'commit', lambda: 'abc')
    args = SimpleNamespace(timeout=5, keep=None, prepaid_floor=None)
    records = lambda order, rid: [{'svid': s} for s in order]  # noqa: E731
    bioasq_run.measured_run(args, tmp_path, [{'id': 'q1', 'body': 'Q?'}], server, records)


def rows(tmp_path, arm):
    return bioasq_run.read_jsonl(tmp_path / f'runs/deixis_{arm}.jsonl')


def test_measured_run_writes_both_arms_with_settings(tmp_path, monkeypatch):
    server = FakeServer(tmp_path / 'lib.sqlite')
    good_run(server)
    run(tmp_path, monkeypatch, server)
    fused, rerank = rows(tmp_path, 'fused'), rows(tmp_path, 'rerank')
    assert [r['svid'] for r in fused[0]['records']] == ['a', 'b', 'c']
    assert [r['svid'] for r in rerank[0]['records']] == ['b', 'a', 'c']
    assert fused[0]['settings']['embedding'] == GOOD_SEMANTIC and fused[0]['settings']['commit'] == 'abc'
    assert fused[0]['settings']['keep'] is None
    assert rerank[0]['rerank'] == {'reranked': 3, 'read_top': 50, 'provider': 'voyage', 'model': 'rerank-3-lite',
                                   'pool_factor': 4.0}


def test_failed_embedding_stops_and_writes_no_row(tmp_path, monkeypatch):
    server = FakeServer(tmp_path / 'lib.sqlite')
    good_run(server, embedding={'provider': 'voyage', 'stored_model': 'voyage:voyage-4-lite@1024'})
    with closing(sqlite3.connect(server.path)) as conn, conn:
        conn.execute("UPDATE run_steps SET status='failed' WHERE operation_key='source_similarity'")
    with pytest.raises(harness.Stop, match='source_similarity failed; 0 of 1'):
        run(tmp_path, monkeypatch, server)
    assert rows(tmp_path, 'fused') == [] and rows(tmp_path, 'rerank') == []
    assert bioasq_run.read_jsonl(tmp_path / 'stopped.jsonl')[0]['id'] == 'q1'


def test_paused_run_stops_but_failed_run_is_a_scored_failure(tmp_path, monkeypatch):
    paused = FakeServer(tmp_path / 'p.sqlite')
    paused.run_state('paused', 'budget')
    (tmp_path / 'p').mkdir()
    with pytest.raises(harness.Stop, match='run paused: budget'):
        run(tmp_path / 'p', monkeypatch, paused)
    failed = FakeServer(tmp_path / 'f.sqlite')
    failed.run_state('failed', 'model_error', stage='plan')
    (tmp_path / 'f').mkdir()
    run(tmp_path / 'f', monkeypatch, failed)
    assert rows(tmp_path / 'f', 'rerank')[0]['error'] == 'run failed at plan: model_error'


def test_a_scored_product_failure_is_not_run_again(tmp_path, monkeypatch):
    failed = FakeServer(tmp_path / 'lib.sqlite')
    failed.run_state('failed', 'model_error', stage='plan')
    run(tmp_path, monkeypatch, failed)
    good_run(failed)  # a rerun would now succeed; the failure must stay the scored outcome
    run(tmp_path, monkeypatch, failed)
    assert [r.get('error') for r in rows(tmp_path, 'rerank')] == ['run failed at plan: model_error']


def test_budget_is_checked_before_the_first_question(tmp_path, monkeypatch):
    server = FakeServer(tmp_path / 'lib.sqlite')
    good_run(server)
    with pytest.raises(harness.Stop, match='OpenAlex daily budget spent; 0 of 1'):
        run(tmp_path, monkeypatch, server, budget='OpenAlex daily budget spent')
    assert rows(tmp_path, 'rerank') == []


def test_rerank_with_another_pool_factor_stops(tmp_path):
    server = FakeServer(tmp_path / 'lib.sqlite')
    server.add('source_similarity', 'succeeded', {'provider': 'voyage', 'stored_model': 'voyage:voyage-4-lite@1024'})
    server.add(harness.RERANK_KEY, 'succeeded', RERANK_STEP | {'pool_factor': 1.0, 'candidate_ids': ['a']})
    with closing(server.db()) as conn:
        found = '; '.join(harness.problems(conn, 'run1', LISTING))
    assert 'pool 1.0' in found and 'reranked 1 records, expected 3' in found


def test_failed_run_with_failed_embedding_stops_instead_of_scoring_zero(tmp_path, monkeypatch):
    server = FakeServer(tmp_path / 'lib.sqlite')
    server.add('source_similarity', 'failed', {'provider': 'gemini'})
    server.run_state('failed', 'ranking_error', stage='rank')
    with pytest.raises(harness.Stop, match='source_similarity failed'):
        run(tmp_path, monkeypatch, server)
    assert rows(tmp_path, 'rerank') == []


@pytest.mark.parametrize('balance, floor, expected', [
    ({'daily_usd': 0.4, 'prepaid_usd': 0.5}, 1.0, None),  # free money first, even below the prepaid floor
    ({'daily_usd': 0.0, 'prepaid_usd': 4.0}, None, 'OpenAlex daily budget spent'),
    ({'daily_usd': 0.0, 'prepaid_usd': 4.0}, 1.0, None),
    ({'daily_usd': 0.01, 'prepaid_usd': 1.02}, 1.0, 'prepaid balance would fall below 1.0 USD'),
    ({'daily_usd': None, 'prepaid_usd': 4.0}, 1.0, 'did not state the daily balance'),
    ({'daily_usd': 0.0, 'prepaid_usd': None}, 1.0, 'did not state the prepaid balance'),
])
def test_budget_stop(monkeypatch, balance, floor, expected):
    monkeypatch.setattr(harness, 'openalex_balance', lambda client, key: balance)
    got = harness.budget_stop(None, 'k', floor)
    assert got == expected if expected is None else expected in got


def test_comparisons_cover_present_pairs():
    systems = {'openalex': {'q': {10: 0.0}}, 'deixis_fused': {'q': {10: 0.5}}, 'deixis_rerank': {'q': {10: 1.0}},
               'deixis': {'q': {10: 0.9}}}  # the 17 Oct run is history, never compared
    out = harness.comparisons(systems, lambda a, b, k: a['q'][k] - b['q'][k], (10,))
    assert out == {'deixis_rerank_minus_openalex': {'@10': 1.0}, 'deixis_fused_minus_openalex': {'@10': 0.5},
                   'deixis_rerank_minus_deixis_fused': {'@10': 0.5}}


@pytest.mark.parametrize('module_name', ['bioasq_run', 'litsearch_run'])
def test_plain_openalex_failure_is_not_replaced_on_rerun(tmp_path, monkeypatch, module_name):
    from scripts.benchmark import litsearch_run
    module = {'bioasq_run': bioasq_run, 'litsearch_run': litsearch_run}[module_name]
    (tmp_path / 'sample.json').write_text(json.dumps({'questions': [{'id': 'q1', 'body': 'Q?', 'year': 2020}]}))
    monkeypatch.setattr(module, 'HOME', tmp_path)
    monkeypatch.setattr(module, 'write_query', lambda client, prompt, raw=False: 'query')
    calls = []

    def records(client, query, year):
        calls.append(query)
        if len(calls) == 1:
            raise ValueError('provider down')
        return [{'title': 'found'}]
    monkeypatch.setattr(module, 'openalex_records', records)
    module.run_openalex(SimpleNamespace(limit=None))
    module.run_openalex(SimpleNamespace(limit=None))
    written = bioasq_run.read_jsonl(tmp_path / 'runs/openalex.jsonl')
    assert len(calls) == 1 and [r['id'] for r in written] == ['q1'] and 'provider down' in written[0]['error']


def test_bioasq_repair_runs_once_per_question(tmp_path, monkeypatch):
    (tmp_path / 'runs').mkdir()
    (tmp_path / 'sample.json').write_text(json.dumps({'questions': [{'id': 'q1', 'body': 'Q?', 'year': 2020}]}))
    (tmp_path / 'runs/openalex.jsonl').write_text(json.dumps({'id': 'q1', 'query': 'bad*', 'error': 'HTTP 400'}) + '\n')
    monkeypatch.setattr(bioasq_run, 'HOME', tmp_path)
    monkeypatch.setattr(bioasq_run, 'write_query', lambda client, prompt, raw=False: 'still bad*')
    monkeypatch.setattr(bioasq_run, 'openalex_records', lambda client, q, y: (_ for _ in ()).throw(ValueError('400')))
    bioasq_run.repair_openalex(SimpleNamespace())
    bioasq_run.repair_openalex(SimpleNamespace())
    assert len(bioasq_run.read_jsonl(tmp_path / 'runs/openalex.jsonl')) == 2

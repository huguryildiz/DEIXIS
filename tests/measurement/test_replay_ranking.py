"""Synthetic offline replay evidence, not relevance or scientific validation."""
import copy
import json
import sqlite3

import pytest

from scripts.benchmark import replay_ranking as replay
from scripts.benchmark.common import canonical, sha


@pytest.fixture
def snapshot(tmp_path):
    """A tiny frozen SQLite input with 40 works and decisions, opened through the RO guard."""
    pool = [{'id': f'v{i:02}', 'work_id': f'w{i:02}', 'title': f'Synthetic underwater routing {i}',
             'abstract': 'Synthetic acoustic method', 'references': ['Wshared'] if i in {0, 35} else [f'R{i}'],
             'own_ids': [f'W{i}'], 'origin': 'chain' if i % 2 else 'keyword'} for i in range(40)]
    decisions = [dict(id='d0', work_id='w00', stage='fulltext', outcome='include', reason_code='met', created_at='1'),
                 dict(id='d35', work_id='w35', stage='fulltext', outcome='include', reason_code='met', created_at='2')]
    data = dict(pool=pool, verified=[], query_words=['underwater', 'routing'], blocks={'task': ['routing']},
                embedding_model=None, similarities={}, compared_terms=None,
                baseline=[p['id'] for p in pool], decisions=decisions)
    database = tmp_path / 'library.sqlite'
    writer = sqlite3.connect(database)
    writer.execute('CREATE TABLE replay_input (body TEXT)')
    writer.execute('INSERT INTO replay_input VALUES (?)', (json.dumps(data),))
    writer.commit()
    writer.close()
    reader = replay.connect(replay.snapshot_path(tmp_path))
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.execute('DELETE FROM replay_input')
        data = json.loads(reader.execute('SELECT body FROM replay_input').fetchone()[0])
    finally:
        reader.close()
    for p in data['pool']:
        p['references'], p['own_ids'] = frozenset(p['references']), frozenset(p['own_ids'])
    return data


def test_origin_and_input_order_do_not_rank(snapshot):
    before = replay.compute_orders(snapshot)
    changed = copy.deepcopy(snapshot)
    changed['pool'].reverse()
    for row in changed['pool']:
        row['origin'] = 'keyword' if row['origin'] == 'chain' else 'chain'
    assert replay.compute_orders(changed) == before
    assert len(set(before['orders']['B'])) == 40


def test_feedback_freezes_batch_and_ignores_later_decisions(snapshot):
    order = snapshot['baseline']
    before, metadata = replay.feedback_order(snapshot['pool'], order, snapshot['decisions'])
    assert before[:30] == order[:30]
    assert before.index('v35') < order.index('v35')  # observed coupling promotes a pending work
    assert [d['id'] for d in metadata['used_decisions']] == ['d0']
    changed = copy.deepcopy(snapshot['decisions'])
    changed[1]['outcome'] = 'criterion_not_met'
    changed.append(dict(id='later', work_id='w39', stage='abstract', outcome='candidate', created_at='3'))
    assert replay.feedback_order(snapshot['pool'], order, changed) == (before, metadata)
    assert sorted(before) == sorted(order)


def test_access_error_is_not_exclusion(snapshot):
    decisions = [dict(id='abstract', work_id='w00', stage='abstract', outcome='candidate', created_at='1'),
                 dict(id='access', work_id='w00', stage='fulltext', outcome='unresolved',
                      reason_code='no_fulltext', created_at='2')]
    _, metadata = replay.feedback_order(snapshot['pool'], snapshot['baseline'], decisions)
    assert metadata['batch_states']['w00'] == 'abstract_candidate'
    assert metadata['positive_work_ids'] == ['w00']
    decisions[1]['outcome'] = 'criterion_not_met'
    _, excluded = replay.feedback_order(snapshot['pool'], snapshot['baseline'], decisions)
    assert excluded['batch_states']['w00'] == 'excluded'
    assert not excluded['positive_work_ids']


def test_determinism_and_no_target_signal(snapshot):
    first, second = replay.compute_orders(snapshot), replay.compute_orders(copy.deepcopy(snapshot))
    assert sha(canonical(first)) == sha(canonical(second))
    versions = [{'id': 'v35', 'work_id': 'w35', 'doi': '10.synthetic/target'}]
    benchmark = {'papers': [{'key': 'target', 'doi': '10.synthetic/target', 'label': 'ilgili', 'anchor': True}]}
    arms, _ = replay.evaluate(first, snapshot['pool'], versions, benchmark)
    assert arms['D']['targets'][0]['in_pool']
    benchmark['papers'][0]['doi'] = '10.synthetic/other'
    replay.evaluate(first, snapshot['pool'], versions, benchmark)
    assert replay.compute_orders(snapshot) == first


def test_keyword_controls_use_recorded_membership_not_origin(snapshot):
    snapshot['baseline'] = snapshot['baseline'][:20]
    result = replay.compute_orders(snapshot)
    keyword = replay.ranking.rank_pool(snapshot['pool'][:20], [], set(snapshot['query_words']),
                                       snapshot['blocks'], None, {}, compared_terms=None)
    assert result['orders']['A0'] == keyword['order']
    assert result['orders']['C0'] == keyword['fused']
    assert set(result['orders']['C']) == {r['id'] for r in snapshot['pool']}
    assert set(result['orders']['A0']) == set(snapshot['baseline'])


def test_controls_report_rank_drift_and_rescued_target_loss(snapshot):
    # A relevant rescued work can disappear beyond 50 in C without changing any ranking input.
    extra = [{**snapshot['pool'][0], 'id': f'v{i:02}', 'work_id': f'w{i:02}'} for i in range(40, 60)]
    pool = snapshot['pool'] + extra
    order = [r['id'] for r in pool]
    result = {'orders': {a: list(order) for a in ('A', 'A0', 'C0', 'B', 'C', 'D')}, 'rescued': ['v00']}
    result['orders']['C'] = order[1:] + order[:1]
    versions = [{'id': 'v00', 'work_id': 'w00', 'doi': '10.synthetic/target'}]
    benchmark = {'papers': [{'key': 'target', 'doi': '10.synthetic/target', 'label': 'ilgili', 'anchor': True}]}
    arms, _ = replay.evaluate(result, pool, versions, benchmark)
    controls = replay.evaluate_controls(result, pool, versions, benchmark, arms)
    assert controls['robustness']['passed']
    assert controls['robustness']['targets'][0]['delta'] == 0
    assert controls['rescue_signal_measurement_required']
    assert controls['rescued_targets'][0]['C'] == 60
    result['orders']['A0'] = order[10:] + order[:10]
    arms, _ = replay.evaluate(result, pool, versions, benchmark)
    controls = replay.evaluate_controls(result, pool, versions, benchmark, arms)
    assert not controls['robustness']['passed']
    assert controls['robustness']['lost_relevant_targets'] == ['target']
    assert controls['robustness']['top50_intersection'] == 40


def test_rescue_rrf_is_a_signal_and_preserves_pool():
    fused = [f'v{i:03}' for i in range(300)]
    embedding = {sid: (i + 1, True) for i, sid in enumerate(reversed(fused))}
    order, ranks = replay.rescue_rrf_order(fused, ['v299'], embedding)
    assert set(order) == set(fused)
    assert order[0] != 'v299'  # a signal, not unconditional promotion
    assert ranks['rescue']['v299'] == (1, True)
    assert ranks['rescue']['v000'][1] is False
    assert replay.rescue_rrf_order(fused, [], {}) == (fused, {})


def test_explicit_path_and_live_path_guard(monkeypatch):
    monkeypatch.delenv('DEIXIS_DATA_DIR', raising=False)
    with pytest.raises(ValueError, match='explicit isolated'):
        replay.snapshot_path()
    with pytest.raises(ValueError, match='live'):
        replay.snapshot_path('~/Library/Application Support/DEIXIS')


def test_no_evidence_snapshot_loader(tmp_path):
    """Exercise provenance joins and the no-StepInput path, not just the pure ranker."""
    path = tmp_path / 'library.sqlite'
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE answers(id, research_id, scope_revision, step_input_id, created_at, status);
        CREATE TABLE step_inputs(id, payload_json, created_at);
        CREATE TABLE scope_revisions(research_id, revision, question);
        CREATE TABLE runs(id, research_id, scope_revision);
        CREATE TABLE run_steps(id, run_id, operation_key, kind, status, finished_at, protocol_hash, output_json);
        CREATE TABLE protocol_records(research_id, scope_revision, body_sha256, body_json);
        CREATE TABLE search_runs(id, research_id, run_id, retrieved_at);
        CREATE TABLE candidate_hits(research_id, scope_revision, search_run_id, source_version_id);
        CREATE TABLE candidates(research_id, scope_revision, search_run_id, source_version_id, created_at);
        CREATE TABLE chain_links(research_id, scope_revision, run_id, passed_filter, seed_source_version_id,
                                 linked_openalex_id, direction, source_version_id);
        CREATE TABLE source_versions(id, work_id, title, doi, references_read);
        CREATE TABLE passages(id, source_version_id, kind, text);
        CREATE TABLE identifier_mappings(source_version_id, scheme, value);
        CREATE TABLE record_references(source_version_id, referenced_id);
        CREATE TABLE record_signal_ranks(ranking_step_id, source_version_id, signal, rank);
        CREATE TABLE source_similarities(research_id, scope_revision, model, source_version_id, similarity, created_at);
        CREATE TABLE stage_decisions(id, research_id, scope_revision, source_version_id, stage, outcome,
                                     created_at, superseded_at);
    ''')
    start, finish = '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:10+00:00'
    conn.execute('INSERT INTO answers VALUES (?,?,?,?,?,?)', ('a','r',1,None,finish,'no_evidence'))
    conn.execute('INSERT INTO scope_revisions VALUES (?,?,?)', ('r',1,'Synthetic routing'))
    conn.execute('INSERT INTO runs VALUES (?,?,?)', ('run','r',1))
    conn.execute('INSERT INTO run_steps VALUES (?,?,?,?,?,?,?,?)',
                 ('rank','run','ranking','code:ranking','succeeded',start,'hash',json.dumps({'seeds':[]})))
    vocab = {'terms':[{'phrase':'routing','root':'routing','in_query':'phrase','block':'task','dropped':None,
                       'origin':'question'}]}
    conn.execute('INSERT INTO run_steps VALUES (?,?,?,?,?,?,?,?)',
                 ('approval','run','protocol_approval','code:protocol_approval','succeeded',start,'hash',
                  json.dumps({'approved':{'vocabulary':vocab}})))
    conn.execute('INSERT INTO protocol_records VALUES (?,?,?,?)', ('r',1,'hash',json.dumps({'question':'Synthetic routing'})))
    conn.execute('INSERT INTO search_runs VALUES (?,?,?,?)', ('search','r','run',start))
    for n in range(2):
        sid, wid = f'v{n}', f'w{n}'
        conn.execute('INSERT INTO source_versions VALUES (?,?,?,?,?)', (sid,wid,'Synthetic routing',None,0))
        conn.execute('INSERT INTO candidate_hits VALUES (?,?,?,?)', ('r',1,'search',sid))
        conn.execute('INSERT INTO record_signal_ranks VALUES (?,?,?,?)', ('rank',sid,'inspection',n+1))
    conn.commit()
    conn.close()
    reader = replay.connect(replay.snapshot_path(tmp_path))
    try:
        data, _, provenance = replay.read_snapshot(reader, {'question':'Synthetic routing'})
    finally:
        reader.close()
    assert provenance['cutoff_basis'] == 'no_evidence_answer_created_at'
    assert data['baseline'] == ['v0','v1']
    assert replay.compute_orders(data)['orders']['B'] == ['v0','v1']

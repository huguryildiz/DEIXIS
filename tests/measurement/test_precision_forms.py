"""Synthetic form/scoring checks; no relevance judgments on real records."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from scripts.benchmark import precision_forms as pf
from scripts.benchmark.check import connect
from test_search_measurement import library  # Shared synthetic migrated snapshot fixture.


def records(arm, offset=0):
    return [dict(arm=arm, rank=i + 1, work_id=f'{arm}-work-{i}', id=f'{arm}-version-{i}',
                 doi=f'10.1234/{i + offset}', aliases=[f'doi:10.1234/{i + offset}'],
                 title=f'SYNTHETIC paper {i + offset}', year=2026, venue=None,
                 abstract='SYNTHETIC abstract ' + 'x' * 2600 + ' doi:10.1234/private',
                 abstract_passage_id=f'{arm}-passage-{i}', abstract_origin='synthetic') for i in range(50)]


def fixture_form(offset=25):
    criterion = {'text': 'SYNTHETIC scope', 'parts': [
        {'name': 'method', 'definition': 'SYNTHETIC method', 'role': 'core'},
        {'name': 'metric', 'definition': 'SYNTHETIC metric', 'role': 'aspect'}]}
    return pf.make_form('SYNTHETIC question', criterion, {'A': records('A'), 'C': records('C', offset)}, 42)


def test_blind_union_deterministic_and_separate():
    form, key = fixture_form()
    assert (form, key) == fixture_form()
    assert len(form['items']) == 75
    assert set(form) == {'question', 'criterion', 'items'}
    assert all(set(row) == {'id', 'title', 'year', 'venue', 'abstract'} for row in form['items'])
    assert all(len(row['abstract']) <= 2500 for row in form['items'])
    assert '10.1234/' not in json.dumps(form)
    assert len({row['id'] for row in form['items']}) == 75
    assert [row['title'] for row in form['items']] != [r['title'] for r in records('A')]
    assert any(len(entry['positions']) == 2 for entry in key['mapping'].values())


def test_doi_redaction_and_absent_abstract():
    assert pf.blind_text('SYNTHETIC https://doi.org/10.1234/abc') == 'SYNTHETIC [identifier withheld]'
    assert pf.blind_text(None) is None
    a, c = records('A'), records('C')
    a[0]['abstract'] = c[0]['abstract'] = None
    form, _ = pf.make_form('Q', {'text': 'scope', 'parts': []}, {'A': a, 'C': c}, 1)
    assert len(form['items']) == 50
    assert sum(row['abstract'] is None for row in form['items']) == 1


def test_scores_disagreement_and_uncertainty_keep_denominator():
    form, key = fixture_form()
    sol = {item: 'irrelevant' for item in key['mapping']}
    claude = dict(sol)
    hit = next(item for item, entry in key['mapping'].items()
               if any(pos['arm'] == 'A' and pos['rank'] == 1 for pos in entry['positions']))
    sol[hit] = 'relevant'
    result = pf.score(form, key, sol, claude)
    assert result['scores']['sol']['A']['P@20']['value'] == 1 / 20
    assert result['scores']['sol']['A']['P@50']['value'] == 1 / 50
    consensus = result['scores']['consensus']['A']['P@20']
    assert consensus['value'] == 0
    assert consensus['uncertain'] == 1
    assert consensus['denominator'] == 20
    assert consensus['uncertainty_upper_bound'] == 1 / 20
    assert result['disagreements'] == [hit]
    claude[hit] = 'relevant'
    assert pf.score(form, key, sol, claude)['scores']['consensus']['A']['P@20']['value'] == 1 / 20


@pytest.mark.parametrize('problem', ['missing', 'extra', 'invalid', 'null'])
def test_reject_invalid_labels(problem):
    form, key = fixture_form()
    labels = {item: 'uncertain' for item in key['mapping']}
    bad = dict(labels)
    if problem == 'missing':
        bad.pop(next(iter(bad)))
    elif problem == 'extra':
        bad['unknown'] = 'relevant'
    else:
        bad[next(iter(bad))] = 'yes' if problem == 'invalid' else None
    with pytest.raises(ValueError):
        pf.score(form, key, labels, bad)


def test_reject_changed_evidence_and_duplicate_ranks():
    form, key = fixture_form()
    labels = {item: 'uncertain' for item in key['mapping']}
    changed = copy.deepcopy(form)
    changed['items'][0]['abstract'] = 'changed'
    with pytest.raises(ValueError, match='form changed'):
        pf.score(changed, key, labels, labels)
    changed_key = copy.deepcopy(key)
    next(iter(changed_key['mapping'].values()))['positions'][0]['rank'] = 999
    with pytest.raises(ValueError, match='ranks'):
        pf.score(form, changed_key, labels, labels)


def test_deduplicate_before_cutoff_and_refuse_identity_ambiguity():
    a = records('A')
    assert pf.first50([a[0], a[0], *a[1:]]) == a
    with pytest.raises(ValueError, match='fewer than 50'):
        pf.first50(a[:49])
    a[1]['aliases'] = a[0]['aliases']
    with pytest.raises(ValueError, match='distinct ranked works'):
        pf.make_form('Q', {}, {'A': a, 'C': records('C')}, 1)


def test_duplicate_json_keys_and_sqlite_read_only(tmp_path):
    path = tmp_path / 'labels.json'
    path.write_text('{"id":"relevant","id":"irrelevant"}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        pf.read_json(path)
    import sqlite3
    database = tmp_path / 'library.sqlite'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE synthetic(id INTEGER)')
    conn = connect(database)
    try:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            conn.execute('INSERT INTO synthetic VALUES (1)')
    finally:
        conn.close()


def test_prepare_refuses_existing_output_and_live_path(tmp_path):
    with pytest.raises(ValueError, match='already exists'):
        pf.prepare(tmp_path)
    with pytest.raises(ValueError, match='live library forbidden'):
        pf.load_arm(pf.ROOT, 'A', 'Q')


@pytest.fixture
def precision_library(library):
    original, rid, bench, _, _ = library
    with tempfile.TemporaryDirectory(prefix='deixis-precision-test-', dir='/tmp') as directory:
        database = Path(directory) / 'library.sqlite'
        conn = sqlite3.connect(database)
        original.backup(conn)
        def insert(table, **values):
            conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                         tuple(values.values()))
        try:
            yield conn, rid, bench, database, insert
        finally:
            conn.close()


def test_snapshot_loaders_pin_ranking_and_list_protocol(precision_library):
    conn, rid, bench, database, insert = precision_library
    start = '2026-10-06T00:00:00+00:00'
    insert('record_signal_ranks', ranking_step_id='old_rank', research_id=rid,
           source_version_id='v3', signal='inspection', rank=4, available=1)
    for i in range(4, 51):
        insert('works', id=f'w{i}', created_at=start)
        insert('source_versions', id=f'v{i}', work_id=f'w{i}', doi=f'10.1234/{i}',
               title=f'SYNTHETIC {i}', version_label='publishedVersion', origin='provider', created_at=start)
        insert('record_signal_ranks', ranking_step_id='old_rank', research_id=rid,
               source_version_id=f'v{i}', signal='inspection', rank=i + 1, available=1)
    directory = database.parent
    (directory / 'drive.json').write_text(json.dumps({'research_id': rid}))
    conn.commit()
    before = pf.snapshot_hashes(directory)
    a, _, info = pf.load_arm(directory, 'A', bench['question'])
    assert len(a) == 50
    assert info['step_id'] == 'old_rank'  # A later ranking must never replace the answer's ranking.
    assert a[0]['work_id'] == 'w1'
    assert len({row['work_id'] for row in a}) == 50
    assert pf.snapshot_hashes(directory) == before

    criterion = {'inclusion_criterion': 'SYNTHETIC frozen scope', 'criterion_parts': [
        {'name': 'method', 'definition': 'SYNTHETIC core', 'role': 'core'},
        {'name': 'metric', 'definition': 'SYNTHETIC aspect', 'role': 'aspect'}]}
    insert('protocol_records', id='frozen-protocol', research_id=rid, scope_revision=1,
           protocol_revision=1, body_json=pf.canonical(criterion), body_sha256=pf.stored_hash(criterion), created_at=start)
    later = criterion | {'inclusion_criterion': 'SYNTHETIC later scope: must not leak into form'}
    insert('protocol_records', id='later-protocol', research_id=rid, scope_revision=1,
           protocol_revision=2, body_json=pf.canonical(later), body_sha256=pf.stored_hash(later), created_at=start)
    ordered = list(reversed(a))
    order = [row['id'] for row in ordered]
    manifest = {'protocol': {'protocol_revision': 1, 'protocol_hash': pf.stored_hash(criterion)}}
    listing = {'policy': 'small_batch_fused_v1', 'manifest': manifest, 'manifest_hash': pf.stored_hash(manifest),
               'order': order, 'order_hash': pf.stored_hash(order), 'items': [
                   {'head': row['id'], 'work_id': row['work_id'], 'position': i + 1}
                   for i, row in enumerate(ordered)]}
    run_id = conn.execute('SELECT run_id FROM run_steps WHERE id=?', (info['step_id'],)).fetchone()[0]
    insert('run_steps', id='frozen-list', run_id=run_id, operation_key='small_batch:v1:list',
           kind='code:small_batch_list', status='succeeded', attempt=1, started_at=start, finished_at=start,
           output_json=pf.canonical(listing))
    conn.commit()
    c, frozen, info = pf.load_arm(directory, 'C', bench['question'])
    assert [row['id'] for row in c] == order
    assert frozen['text'] == criterion['inclusion_criterion']
    assert [part['role'] for part in frozen['parts']] == ['core', 'aspect']
    assert info['protocol_id'] == 'frozen-protocol'
    listing['order_hash'] = 'tampered'
    conn.execute('UPDATE run_steps SET output_json=? WHERE id=?', (pf.canonical(listing), 'frozen-list'))
    conn.commit()
    with pytest.raises(ValueError, match='list hash mismatch'):
        pf.load_arm(directory, 'C', bench['question'])

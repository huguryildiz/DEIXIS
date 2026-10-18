"""EE survey benchmark: selection, gold cut, split and scoring on synthetic records. No service, keys or network."""
from scripts.benchmark import eesurvey

COMST, ACCESS, IOTJ = 'S23688054', 'S2485537415', 'S2480266640'


def work(wid, title, source=COMST, cited=10, refs=120, year=2021, kind='article', date=None):
    return {'id': f'https://openalex.org/{wid}', 'display_name': title, 'publication_year': year, 'type': kind,
            'publication_date': date or f'{year}-06-01', 'referenced_works_count': refs, 'cited_by_count': cited,
            'primary_location': {'source': {'id': f'https://openalex.org/{source}'}}}


def test_survey_and_topic_rules():
    assert eesurvey.is_survey(work('W1', 'Anything', source=COMST)) == 'survey venue'
    assert eesurvey.is_survey(work('W1', 'A study', source=IOTJ, kind='review')) == 'type review'
    assert eesurvey.is_survey(work('W1', 'IoT security: a survey', source=IOTJ)) == 'survey word in title'
    assert eesurvey.is_survey(work('W1', 'A new scheme', source=IOTJ)) is None
    assert eesurvey.topic_of(work('W1', 'Underwater acoustic sensor networks'))[0] == 'underwater_sensor'
    assert eesurvey.topic_of(work('W1', 'Power control in NOMA networks'))[0] == 'wireless'
    assert eesurvey.topic_of(work('W1', 'Deep learning for wireless'))[0] == 'ml'
    assert eesurvey.topic_of(work('W1', 'Model predictive control of converters'))[0] == 'power_energy'
    assert eesurvey.topic_of(work('W1', 'Quantum computing', source='S68686220')) == (None, None)
    assert eesurvey.topic_of(work('W1', 'Object detection in images'))[0] is None
    assert eesurvey.topic_of(work('W1', 'Explaining deep neural networks', source='S68686220')) == (None, None)
    assert eesurvey.topic_of(work('W1', 'Deep learning for radar', source='S68686220'))[0] == 'ml'
    assert eesurvey.topic_of(work('W1', 'Controller placement in software-defined networks'))[0] == 'wireless'
    assert eesurvey.candidates([work('W1', 'Blockchain for smart grid: a survey')]) == []
    assert eesurvey.topic_of(work('W1', 'Something general', source='S54761077')) == ('control', 'venue default')


def test_selection_is_deterministic_and_respects_rules():
    works = [work(f'W{i}', f'Sparse recovery survey {i}', cited=100 - i % 3) for i in range(12)]
    works += [work('W90', 'Wireless networks survey', cited=999, year=2018),       # too early
              work('W91', 'Wireless networks survey two', cited=999, refs=50),     # too few references
              work('W92', 'Wireless networks survey three', cited=5000, source=ACCESS),  # tier 2 comes after tier 1
              work('W93', 'Sparse recovery survey 0', cited=1)]                     # same title as W0
    first = eesurvey.select(works, per_topic=6)
    second = eesurvey.select(list(reversed(works)), per_topic=6)
    ids = [c['work']['id'] for c in first['signal_processing']]
    assert ids == [c['work']['id'] for c in second['signal_processing']] and len(ids) == 6
    assert all(c['why']['cited_by_count'] == 100 for c in first['signal_processing'][:4])
    assert [c['work']['id'][-3:] for c in first['wireless']] == ['W92']
    other = [[c['work']['id'] for c in eesurvey.select(works, per_topic=6, seed=s)['signal_processing']]
             for s in range(1, 6)]
    assert any(o != ids for o in other)  # only the tie among the cited_by_count 99 surveys depends on the seed
    assert all(set(o[:4]) == set(ids[:4]) for o in other)
    dropped = eesurvey.select(works, per_topic=6, exclude=[ids[0]])['signal_processing']
    assert ids[0] not in [c['work']['id'] for c in dropped] and len(dropped) == 6


def test_selection_prefers_distinct_rule_matches():
    works = [work('W1', '6G vision one', cited=900), work('W2', '6G vision two', cited=800),
             work('W3', 'UAV communications', cited=100), work('W4', 'Satellite links', cited=50)]
    picked = [c['work']['id'][-2:] for c in eesurvey.select(works, per_topic=3)['wireless']]
    assert picked == ['W1', 'W3', 'W4']
    assert [c['work']['id'][-2:] for c in eesurvey.select(works, per_topic=4)['wireless']] == ['W1', 'W2', 'W3', 'W4']


def test_gold_keeps_dated_references_and_drops_self():
    survey = work('W1', 'Survey', date='2021-06-01') | {
        'referenced_works': ['https://openalex.org/W2', 'https://openalex.org/W3', 'https://openalex.org/W1',
                             'https://openalex.org/W4', 'https://openalex.org/W5', 'https://openalex.org/W2']}
    refs = [{'id': 'https://openalex.org/W2', 'publication_date': '2021-06-01', 'abstract_inverted_index': {'a': [0]}},
            {'id': 'https://openalex.org/W3', 'publication_date': '2021-06-02'},
            {'id': 'https://openalex.org/W1', 'publication_date': '2021-06-01'},
            {'id': 'https://openalex.org/W5', 'publication_date': None}]
    kept, counts = eesurvey.gold(survey, refs)
    assert kept == ['W2']
    assert counts == {'listed': 5, 'self': True, 'missing': 1, 'after_survey': 1, 'undated': 1, 'kept': 1,
                      'with_abstract': 1}


def test_split_is_a_third_per_topic_and_seeded():
    questions = [{'id': f'ee{i:02d}', 'topic': t} for i, t in enumerate(['a'] * 6 + ['b'] * 5)]
    out = eesurvey.split(questions)
    assert out == eesurvey.split(list(reversed(questions)))
    assert sum(v == 'tune' for k, v in out.items() if k < 'ee06') == 2
    assert sum(v == 'tune' for k, v in out.items() if k >= 'ee06') == 2
    assert any(eesurvey.split(questions, seed=s) != out for s in range(1, 6))


def test_question_checks():
    title = 'A Survey on Non-Orthogonal Multiple Access for 5G Networks'
    assert eesurvey.question_problems('How does NOMA improve spectral efficiency in cellular systems?', title) == []
    assert 'copies the title' in eesurvey.question_problems(
        'What is known: a survey on non-orthogonal multiple access for 5G networks?', title)
    assert eesurvey.question_problems('What does survey on non orthogonal multiple access for 5G say?', title) == [
        'shares 6 title words in a row']
    assert eesurvey.question_problems('What does this review conclude about NOMA?', title) == ['mentions the survey']


def test_abstract_from_inverted_index():
    assert eesurvey.abstract({'world': [1], 'hello': [0, 2]}) == 'hello world hello'
    assert eesurvey.abstract(None) is None


def test_split_keeps_a_measured_side():
    questions = [{'id': f'ee-W{i}', 'topic': 'a'} for i in range(6)]
    first = eesurvey.split(questions)
    frozen = {k: ('test' if v == 'tune' else 'tune') for k, v in list(first.items())[:3]}
    out = eesurvey.split(questions + [{'id': 'ee-W9', 'topic': 'a'}], frozen=frozen)
    assert all(out[k] == v for k, v in frozen.items())
    assert sum(v == 'tune' for v in out.values()) == max(2, sum(v == 'tune' for v in frozen.values()))


def test_ids_and_fingerprint_follow_the_survey():
    assert eesurvey.question_id('https://openalex.org/W42') == 'ee-W42'
    q = {'id': 'ee-W1', 'body': 'How?', 'survey': {'openalex': 'W1'}, 'cut_date': '2021-06-01', 'gold': ['W2', 'W3'],
         'split': 'test'}
    assert eesurvey.fingerprint([q]) == eesurvey.fingerprint([q | {'gold': ['W3', 'W2'], 'topic': 'x'}])
    assert eesurvey.fingerprint([q]) != eesurvey.fingerprint([q | {'body': 'Why?'}])
    assert eesurvey.fingerprint([q]) != eesurvey.fingerprint([q | {'split': 'tune'}])


QUESTION = {'id': 'ee-W1', 'survey': {'openalex': 'W1'}, 'cut_date': '2021-06-01'}


def test_clean_drops_the_survey_later_work_and_what_only_they_chained():
    dates = {'W5': '2021-03-01', 'W6': '2021-09-01', 'W8': '2021-02-01', 'W20': '2021-05-01'}
    records = [
        {'openalex': 'W1', 'date': '2021-06-01'},                                   # the survey itself
        {'openalex': 'W2', 'year': 2020, 'routes': ['chain'], 'chain_seeds': ['W1']},  # only the survey chained it
        {'openalex': 'W3', 'year': 2020, 'routes': ['chain', 'keyword:openalex'], 'chain_seeds': ['W1']},  # searched
        {'openalex': 'W4', 'year': 2020, 'routes': ['chain'], 'chain_seeds': ['W1', 'W20']},  # an earlier seed too
        {'openalex': 'W5', 'year': 2021, 'routes': ['semantic:openalex']},          # same year, dated before
        {'openalex': 'W6', 'year': 2021, 'routes': ['keyword:openalex']},           # same year, dated after
        {'openalex': 'W7', 'year': 2021, 'routes': ['keyword:openalex']},           # same year, no date: dropped
        {'openalex': 'W8', 'year': 2019, 'routes': ['chain'], 'chain_seeds': ['W6']},  # chained from a later work
        {'openalex': 'W9', 'year': 2022},                                           # later year
        {'doi': '10.1/x', 'year': 2018}]                                            # no id, earlier year: kept
    kept, why = eesurvey.clean(records, QUESTION, dates)
    assert [r.get('openalex') or r['doi'] for r in kept] == ['W3', 'W4', 'W5', '10.1/x']
    assert why == {'survey': 1, 'after_cut': 2, 'undated': 1, 'chain_leak': 2}
    assert eesurvey.exposure(records, QUESTION, dates) == {'survey_seed': True, 'later_seeds': 1}
    assert eesurvey.undated_ids([QUESTION], {'x': {'ee-W1': {'records': records}}}) == {
        'W1', 'W5', 'W6', 'W7', 'W20'}


def test_scoring_cleans_before_k_and_counts_failures():
    meta = {'W2': {'openalex': ['W2']}, 'W3': {'dois': ['10.1/x']}, 'W4': {'title': 'Gold title'}}
    questions = [QUESTION | {'gold': ['W2', 'W3', 'W4']}, QUESTION | {'id': 'ee-W8', 'gold': ['W2']}]
    runs = {'openalex': {
        'ee-W1': {'records': [{'openalex': 'W9', 'date': '2021-07-01'},          # after the cut: dropped before k
                              {'openalex': 'https://openalex.org/W2', 'date': '2021-05-01'},
                              {'doi': 'https://doi.org/10.1/X', 'openalex': 'W30', 'year': 2021},  # dated by OpenAlex
                              {'title': 'gold  title', 'year': 2022}]},          # later year: dropped
        'ee-W8': {'error': 'timeout'}}}
    systems, dropped = eesurvey.score_systems(questions, runs, meta, {'W30': '2021-01-05'}, depths=(1, 10))
    per = systems['openalex']
    assert per['ee-W1'] == {1: 1 / 3, 10: 2 / 3} and per['ee-W8'] is None
    assert dropped['openalex']['after_cut'] == 2
    assert eesurvey.summary(per, depths=(10,)) == {'questions': 2, 'failed': 1, '@10': 2 / 3}
    assert eesurvey.subset({'openalex': per}, {'ee-W8'}) == {'openalex': {'ee-W8': None}}


def ee_db():
    import sqlite3
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE search_runs (id TEXT, request_description TEXT, provider TEXT);
        CREATE TABLE candidate_hits (research_id TEXT, search_run_id TEXT, source_version_id TEXT);
        CREATE TABLE chain_links (research_id TEXT, seed_source_version_id TEXT, source_version_id TEXT,
                                  passed_filter INTEGER);
        CREATE TABLE source_versions (id TEXT, title TEXT, year INTEGER, doi TEXT);
        CREATE TABLE identifier_mappings (source_version_id TEXT, scheme TEXT, value TEXT);
        INSERT INTO search_runs VALUES ('s1', 'GET https://api.openalex.org/works search.title_and_abstract=''x''',
                                        'openalex'),
            ('s2', 'citation chaining, backward: GET https://api.openalex.org/works filter=openalex:W2', 'openalex');
        INSERT INTO candidate_hits VALUES ('r', 's1', 'sv1'), ('r', 's2', 'sv2');
        INSERT INTO chain_links VALUES ('r', 'sv1', 'sv2', 1);
        INSERT INTO source_versions VALUES ('sv1', 'The survey', 2021, NULL), ('sv2', 'A reference', 2019, NULL);
        INSERT INTO identifier_mappings VALUES ('sv1', 'openalex', 'https://openalex.org/W1'),
                                               ('sv2', 'openalex', 'https://openalex.org/W2');
    """)
    return conn


def test_a_chain_request_is_not_a_search_route():
    from contextlib import closing  # noqa: F401 (records closes the connection it is given)
    from scripts.benchmark import eesurvey_run
    server = object.__new__(eesurvey_run.EEDeixis)
    server.db = ee_db
    rows = server.records(['sv1', 'sv2'], 'r')
    assert rows[1]['routes'] == ['chain'] and rows[1]['chain_seeds'] == ['W1']
    kept, why = eesurvey.clean(rows, QUESTION | {'survey': {'openalex': 'W1'}}, {'W1': '2021-06-01'})
    assert kept == [] and why['survey'] == 1 and why['chain_leak'] == 1


def test_the_set_check_reads_the_content(tmp_path, monkeypatch):
    import json
    import pytest
    from scripts.benchmark import eesurvey_run
    monkeypatch.setattr(eesurvey_run, 'HOME', tmp_path)
    q = {'id': 'ee-W1', 'body': 'How?', 'survey': {'openalex': 'W1'}, 'cut_date': '2021-06-01', 'gold': ['W2'],
         'split': 'tune', 'question_problems': []}
    sample = {'fingerprint': eesurvey.fingerprint([q]), 'questions': [q]}
    (tmp_path / 'sample.json').write_text(json.dumps(sample))
    assert eesurvey_run.checked_set() == [q]
    for change in ({'split': 'test'}, {'body': 'Why?'}):
        (tmp_path / 'sample.json').write_text(json.dumps(sample | {'questions': [q | change]}))
        with pytest.raises(SystemExit, match='changed after preparation'):
            eesurvey_run.checked_set()
    other = q | {'split': 'test'}
    (tmp_path / 'sample.json').write_text(json.dumps({'fingerprint': eesurvey.fingerprint([other]),
                                                      'questions': [other]}))
    with pytest.raises(SystemExit, match='runs/ holds results'):
        eesurvey_run.checked_set()
    bad = q | {'question_problems': ['mentions the survey']}
    (tmp_path / 'sample.json').write_text(json.dumps(sample | {'questions': [bad]}))
    with pytest.raises(SystemExit, match='wording check'):
        eesurvey_run.checked_set()

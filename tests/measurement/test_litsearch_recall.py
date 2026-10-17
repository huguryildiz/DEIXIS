"""LitSearch recall scoring and gold matching on synthetic rows: no service, keys or network."""
from scripts.benchmark import litsearch


def test_load_gives_stable_ids_and_dedups_gold():
    rows = [{'query': 'Q1?', 'query_set': 'inline_acl', 'specificity': 0, 'quality': 2, 'corpusids': [7, 7, 9]},
            {'query': 'Q2?', 'corpusids': [3]}]
    first, second = litsearch.load(rows)
    assert (first['id'], first['gold'], first['year']) == ('ls000', ['7', '9'], litsearch.YEAR)
    assert second['id'] == 'ls001'


def test_gold_dois_adds_arxiv_datacite_doi():
    assert litsearch.gold_dois({'DOI': 'https://doi.org/10.18653/V1/X', 'ArXiv': '2101.00001'}) == [
        '10.18653/v1/x', '10.48550/arxiv.2101.00001']
    assert litsearch.gold_dois(None) == []


def test_matches_openalex_then_doi_then_title():
    meta = {'a': {'openalex': ['W1']}, 'b': {'dois': ['10.1/x']}, 'c': {'title': 'BERT: Pre-training!'},
            'd': {'title': 'missed'}}
    records = [{'openalex': 'https://openalex.org/w1'}, {'doi': 'https://doi.org/10.1/X'},
               {'title': 'bert  pre training'}]
    assert litsearch.matched(meta, records) == {'a': 'openalex', 'b': 'doi', 'c': 'title'}
    assert litsearch.recall({'gold': ['a', 'b', 'c', 'd']}, records, meta, depths=(1, 3)) == {1: 0.25, 3: 0.75}


def test_unresolved_gold_stays_in_denominator():
    assert litsearch.recall({'gold': ['a', 'z']}, [{'openalex': 'W1'}], {'a': {'openalex': ['W1']}},
                            depths=(10,)) == {10: 0.5}


def test_route_breakdown_counts_routes_and_misses():
    questions = [{'id': 'q', 'gold': ['a', 'b', 'c', 'd']}, {'id': 'failed', 'gold': ['e']}]
    meta = {'a': {'openalex': ['W1']}, 'b': {'openalex': ['W2']},
            'c': {'openalex': ['W3'], 'has_abstract': True}, 'd': {}}
    rows = {'q': {'records': [{'openalex': 'W1', 'routes': ['keyword:openalex', 'semantic:openalex']},
                              {'openalex': 'W2', 'routes': ['chain']}]},
            'failed': {'error': 'timeout'}}
    out = litsearch.route_breakdown(questions, rows, meta, top=1)
    assert (out['gold'], out['in_pool'], out['in_top_1']) == (4, 2, 1)
    assert out['routes'] == {'keyword': 1, 'semantic': 1, 'chain': 1} and out['only'] == {'chain': 1}
    assert (out['never_retrieved'], out['never_in_openalex'], out['never_with_abstract'], out['never_unresolved']) == (
        2, 1, 1, 1)

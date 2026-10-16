"""BioASQ recall scoring on synthetic golden files: no service, keys or network."""
import json

from scripts.benchmark import bioasq


def golden(tmp_path, edition, questions):
    folder = tmp_path / f'Task{edition}BGoldenEnriched' / f'Task{edition}BGoldenEnriched'
    folder.mkdir(parents=True)
    (folder / f'{edition}B1_golden.json').write_text(json.dumps({'questions': questions}))


def test_load_reads_year_and_dedups_gold(tmp_path):
    golden(tmp_path, 2, [{'id': 'a', 'body': 'Q?', 'documents': [
        'http://www.ncbi.nlm.nih.gov/pubmed/111', 'http://www.ncbi.nlm.nih.gov/pubmed/111',
        'http://www.ncbi.nlm.nih.gov/pubmed/222']}])
    [q] = bioasq.load(tmp_path)
    assert (q['year'], q['edition'], q['gold']) == (2014, 2, ['111', '222'])


def test_sample_is_fixed_and_nested():
    questions = [{'id': str(i)} for i in range(50)]
    small, large = bioasq.sample(questions, 5, 7), bioasq.sample(list(reversed(questions)), 20, 7)
    assert small == large[:5]


def test_recall_matches_pmid_then_doi_then_title():
    question = {'gold': ['1', '2', '3', '4']}
    meta = {'1': {}, '2': {'doi': '10.1/X'}, '3': {'title': 'Tuberous  sclerosis!'}, '4': {'title': 'missed'}}
    records = [{'pmid': '1'}, {'doi': 'https://doi.org/10.1/x'}, {'title': 'tuberous sclerosis'}]
    assert bioasq.recall(question, records, meta, depths=(1, 3)) == {1: 0.25, 3: 0.75}
    assert bioasq.matched(meta, records) == {'1': 'pmid', '2': 'doi', '3': 'title'}


def test_time_filter_keeps_undated_and_same_year():
    assert bioasq.in_time({'year': 2014}, 2014) and bioasq.in_time({}, 2014)
    assert not bioasq.in_time({'year': 2015}, 2014)


def test_macro_skips_failures_and_bootstrap_counts_them_as_zero():
    a = {'x': {10: 1.0}, 'y': None}
    b = {'x': {10: 0.5}, 'y': {10: 0.5}}
    assert bioasq.macro(a, 10) == 1.0
    result = bioasq.paired_bootstrap(a, b, 10, resamples=200)
    assert result['n'] == 2 and result['mean'] == 0.0

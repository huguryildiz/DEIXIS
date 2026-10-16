"""BioASQ Task B recall benchmark, after Elicit's paper-search evaluation (elicit.com/blog/evaluating-elicit-paper-search).

Gold sets are the expert "documents" lists of the 2b–13b golden enriched test sets. A system's ranked records are
matched to gold papers by PMID, then DOI, then normalized title; recall is per question, then averaged (macro).
Records published after the question's challenge year are dropped before cutting at k.
"""
from __future__ import annotations

import glob
import json
import random
import re
from pathlib import Path

try:
    from .common import doi as norm_doi
except ImportError:
    from common import doi as norm_doi

DEPTHS = (10, 20, 50, 100, 200)
FIRST_YEAR = 2012  # edition 2b ran in 2014


def pmid_of(value):
    match = re.search(r'(\d+)\s*$', str(value or ''))
    return match.group(1) if match else None


def norm_title(text):
    return re.sub(r'\W+', ' ', (text or '').casefold()).strip()


def load(raw_dir):
    """Every golden question, with its edition, challenge year and gold PMIDs (deduplicated, order kept)."""
    questions = []
    for path in sorted(glob.glob(f'{raw_dir}/*/*/*_golden.json')):
        edition = int(re.search(r'(\d+)B\d+_golden\.json$', path).group(1))
        for q in json.loads(Path(path).read_text())['questions']:
            gold = list(dict.fromkeys(p for p in map(pmid_of, q.get('documents', [])) if p))
            questions.append({'id': q['id'], 'body': q['body'], 'type': q.get('type'), 'edition': edition,
                              'year': FIRST_YEAR + edition, 'gold': gold})
    return questions


def sample(questions, n, seed):
    """A fixed sample: the same seed and n always pick the same questions, and a larger n keeps the smaller one."""
    ordered = sorted(questions, key=lambda q: q['id'])
    random.Random(seed).shuffle(ordered)
    return ordered[:n]


def in_time(record, year):
    return record.get('year') is None or record['year'] <= year


def matched(gold_meta, records):
    """Gold PMIDs found in `records`, each with the field that matched."""
    pmids = {r['pmid']: 1 for r in records if r.get('pmid')}
    dois = {norm_doi(r['doi']) for r in records if r.get('doi')}
    titles = {norm_title(r['title']) for r in records if r.get('title')}
    found = {}
    for pmid, meta in gold_meta.items():
        if pmid in pmids:
            found[pmid] = 'pmid'
        elif meta.get('doi') and norm_doi(meta['doi']) in dois:
            found[pmid] = 'doi'
        elif meta.get('title') and norm_title(meta['title']) in titles:
            found[pmid] = 'title'
    return found


def recall(question, records, gold_meta, depths=DEPTHS):
    """{k: recall} for one question; records are in rank order and already time-filtered."""
    meta = {p: gold_meta.get(p, {}) for p in question['gold']}
    return {k: len(matched(meta, records[:k])) / len(meta) for k in depths}


def macro(per_question, k):
    values = [r[k] for r in per_question.values() if r is not None]
    return sum(values) / len(values) if values else None


def paired_bootstrap(a, b, k, resamples=10000, seed=0):
    """Mean of a−b over shared questions with a percentile 95% interval; a failed question (None) counts as 0."""
    ids = sorted(set(a) & set(b))
    diffs = [((a[i] or {}).get(k, 0.0)) - ((b[i] or {}).get(k, 0.0)) for i in ids]
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(resamples))
    return {'n': len(diffs), 'mean': sum(diffs) / len(diffs),
            'low': means[int(0.025 * resamples)], 'high': means[int(0.975 * resamples) - 1]}

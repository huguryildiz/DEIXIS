"""The reference-based gates of D163's M1, read from a baseline arm and an M1 arm.

    uv run python scripts/benchmark/m1_score.py --root <root>

Layout: <root>/<set>/<base|m1>/runs/deixis_rerank.jsonl (rows of the delivered order) and <root>/<set>/<arm>/data
(the arm's library), for the sets bioasq and litsearch. Three gates, fixed before the runs: recall@50 paired
difference lower bound > -2 pts; median extra chained records per M1 run <= 80; no sent code query over 250,000
works. A question the replay refused is left out of both arms. Paired bootstrap over questions, 10,000 resamples,
95%, a failure counting as zero. The remaining gate, Stage A coverage, is scored elsewhere: until it is, the verdict
is inconclusive at best.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

try:
    from . import bioasq, chain_rule_check, harness, litsearch
except ImportError:
    import bioasq
    import chain_rule_check
    import harness
    import litsearch

ROOT = Path(__file__).resolve().parents[2]
SETS = {'bioasq': ROOT / 'notes/bioasq', 'litsearch': ROOT / 'notes/litsearch'}
MARGIN = {'bioasq': -0.02, 'litsearch': -0.02}
MAX_EXTRA_MEDIAN = 80
ARMS = ('base', 'm1')


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def library(root, name, arm):
    path = root / name / arm / 'data' / 'library.sqlite'
    conn = sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return path, conn


def list_frozen_at(conn, run_id):
    """When the run's small-batch list froze, or None if it never did."""
    row = conn.execute("SELECT finished_at FROM run_steps WHERE run_id = ? AND operation_key = 'small_batch:v1:list'"
                       " AND status = 'succeeded'", (run_id,)).fetchone() if run_id else None
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def refused(log, questions, frozen_at):
    """Ids of the questions the M1 arm's replay refused a call for before the scored run's list froze. A call the
    replay does not cover (`not_replayed`) is left alone only when it came after that freeze, as the answer stage's
    do; one before it (a question translation, say) changed the run and excludes the question too."""
    by_text = {q['body']: q['id'] for q in questions}
    out = set()
    for r in log:
        qid = by_text.get(r.get('question'))
        if qid is None or r.get('outcome') != 'refused':
            continue
        frozen = frozen_at.get(qid)
        if r.get('reason') == 'not_replayed' and frozen is not None and r.get('at') \
                and datetime.fromisoformat(r['at']) >= frozen:
            continue
        out.add(qid)
    return out


def per_question(name, questions, rows, depths):
    meta = json.loads((SETS[name] / 'gold_meta.json').read_text())
    out = {}
    for q in questions:
        row = rows.get(q['id'])
        if row is None:
            continue
        if row.get('error'):
            out[q['id']] = None
            continue
        if name == 'bioasq':
            records = [r for r in row['records'] if bioasq.in_time(r, q['year'])]
            out[q['id']] = bioasq.recall(q, records, meta, depths)
        else:
            records = [r for r in row['records'] if r.get('year') is None or r['year'] <= q['year']]
            out[q['id']] = litsearch.recall(q, records, meta, depths)
    return out


def output(conn, run_id, key):
    row = conn.execute('SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?',
                       (run_id, key)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def paired_gate(m1, base, expected, k, margin):
    """The paired difference m1 - base at depth `k` over exactly the expected questions, and its verdict against
    `margin` (the lower bound must exceed it). A question either arm has no row for makes the gate inconclusive; a
    recorded product failure (None) scores zero."""
    missing = {'m1': [i for i in expected if i not in m1], 'base': [i for i in expected if i not in base]}
    if any(missing.values()):
        return {'verdict': 'inconclusive', 'missing': missing, 'n': 0}
    result = bioasq.paired_bootstrap({i: m1[i] for i in expected}, {i: base[i] for i in expected}, k)
    if result['n'] != len(expected):
        raise AssertionError(f"paired n {result['n']} is not the {len(expected)} expected questions")
    return result | {'verdict': 'pass' if result['low'] > margin else 'fail', 'missing': missing}


def extra_chained(checked, run_ids):
    """The extra chained works of each expected question's M1 run, and whether that evidence is complete: a question
    whose run has no checked list (failed runs included), frozen forms absent or failing their digest, a replayed
    admission that does not match the stored one, or a chain reply whose payload is missing leaves the gate
    inconclusive until reconciled."""
    extra, complete = [], True
    for run_id in run_ids:
        row = checked.get(run_id)
        if row is None or row['forms_unverified']:
            complete = False  # no checked list, or forms that are not the verified frozen ones: nothing to count
            continue
        if row['mismatches'] or row['missing_payloads']:
            complete = False
        extra.append(row['extra_chained_works'])
    return extra, complete


def embedded_share(conn, run_id):
    return output(conn, run_id, 'source_similarity').get('embedded_share')


def score_set(root, name):
    questions = json.loads((SETS[name] / 'sample.json').read_text())['questions']
    rows = {arm: {r['id']: r for r in read_jsonl(root / name / arm / 'runs' / 'deixis_rerank.jsonl')}
            for arm in ARMS}
    _, conn = library(root, name, 'm1')
    frozen_at = {i: list_frozen_at(conn, r.get('run_id')) for i, r in rows['m1'].items()}
    conn.close()
    left_out = refused(read_jsonl(root / name / 'm1' / 'data' / 'replay.jsonl'), questions, frozen_at)
    questions = [q for q in questions if q['id'] not in left_out]
    expected = [q['id'] for q in questions]
    for arm in ARMS:
        harness.check_arm(f'{name}/{arm}', list(rows[arm].values()))
    depths = (50,)
    per = {arm: per_question(name, questions, rows[arm], depths) for arm in ARMS}
    report = {'questions': len(expected), 'refused_by_replay': sorted(left_out),
              'recall@50': paired_gate(per['m1'], per['base'], expected, 50, MARGIN[name]),
              'arms': {arm: {'mean@50': bioasq.macro(per[arm], 50), 'failed': sum(v is None for v in per[arm].values()),
                             'rerank_applied': sum(bool((r.get('rerank') or {}).get('applied'))
                                                   for r in rows[arm].values() if not r.get('error'))}
                       for arm in ARMS}}
    extra, extra_complete = [], True
    for arm in ARMS:
        path, conn = library(root, name, arm)
        runs = [rows[arm][i] for i in expected if i in rows[arm] and not rows[arm][i].get('error')]
        shares = [s for r in runs if (s := embedded_share(conn, r['run_id'])) is not None]
        report['arms'][arm]['embedded_share_min'] = min(shares) if shares else None
        if arm == 'm1':
            checked = chain_rule_check.check(path)
            extra, extra_complete = extra_chained(checked, [(rows[arm].get(i) or {}).get('run_id') for i in expected])
            report['chain_rule_mismatches'] = sum(c.get('mismatches', 0) for c in checked.values())
            report['chain_missing_payloads'] = sum(c.get('missing_payloads', 0) for c in checked.values())
            report['chain_forms_unverified'] = sum(c['forms_unverified'] for c in checked.values())
        conn.close()
    report['extra_chained'], report['extra_chained_complete'] = extra, extra_complete
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    root = Path(args.root)
    report = {name: score_set(root, name) for name in SETS}
    extra = [n for part in report.values() for n in part['extra_chained']]
    complete = all(part['extra_chained_complete'] for part in report.values())
    median = statistics.median(extra) if extra else None
    gates = {f'recall@50 {name}': part['recall@50']['verdict'] for name, part in report.items()}
    gates['median extra chained <= 80'] = ('inconclusive' if not complete or median is None else
                                          'pass' if median <= MAX_EXTRA_MEDIAN else 'fail')
    reference = 'fail' if 'fail' in gates.values() else 'pass' if set(gates.values()) == {'pass'} else 'inconclusive'
    report['summary'] = {'gates': gates, 'extra_chained_median': median, 'reference_gates': reference,
                         'verdict': 'fail' if reference == 'fail' else 'inconclusive until Stage A is scored'}
    print(json.dumps(report['summary'], indent=1))
    (root / 'm1_score.json').write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()

"""Offline, read-only ranking replay; targets enter only after all orders freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from deixis.workflow import ranking
from deixis.workflow.expansion import expansion_blocks, queried_form, queried_terms, TASK_BLOCK

try:
    from .check import connect, rows, selected_ranking
    from .common import canonical, load_benchmark, matching_records, sha
except ImportError:
    from check import connect, rows, selected_ranking
    from common import canonical, load_benchmark, matching_records, sha

RULE = {
    'version': 'replay-ranking-v1', 'batch_size': 30, 'rrf_k': 60,
    'feedback': 'equal-weight RRF: pending B order + bibliographic coupling/direct citations to positive batch-1 works',
    'positive': 'fulltext include; otherwise abstract candidate (provisional); unresolved is neutral',
    'negative': 'fulltext criterion_not_met or abstract out_of_scope; recorded but not used as a penalty',
    'rescue': {'rescue_outside_top': 200, 'rescue_embedding_top': 50},
    'embedding_feedback': 'not used: question-source scalar similarities are not source-source vectors',
}

ROBUSTNESS = {'version': 'keyword-reconstruction-v1', 'top_k': 50,
              'minimum_overlap_fraction': 0.9, 'maximum_top50_anchor_delta': 5,
              'preserve_A_top50_relevant_targets': True}

RESCUE_SIGNAL = {'version': 'rescue-rrf-v1', 'base': 'C fused ordinal rank',
                 'rescue': 'embedding order among rescued works; missing mean tail rank',
                 'weights': 'equal', 'rrf_k': 60,
                 'selection': 'preserve C top50 anchors in every development snapshot, never reduce C top50 relevant '
                              'count in any development snapshot, improve at least one; otherwise select C'}


def rescue_rrf_order(fused, rescued, embedding_ranks):
    """Fuse a rescue signal without putting its works ahead of every other signal."""
    if not rescued:
        return list(fused), {}
    rescued_set = set(rescued)
    scores = {sid: 1 / embedding_ranks[sid][0] if sid in rescued_set else 0 for sid in fused}
    ranks = {'base': {sid: (i + 1, True) for i, sid in enumerate(fused)},
             'rescue': ranking.mean_ranks(scores, {sid: sid in rescued_set for sid in fused})}
    return ranking.fuse(ranks, tuple(ranks), k=RESCUE_SIGNAL['rrf_k']), ranks


def snapshot_path(value=None):
    value = value or os.environ.get('DEIXIS_DATA_DIR')
    if not value or not str(value).strip():
        raise ValueError('explicit isolated data path or DEIXIS_DATA_DIR required')
    path = Path(value).expanduser().resolve()
    live = (Path.home() / 'Library/Application Support/DEIXIS').resolve()
    if path == live or path.is_relative_to(live):
        raise ValueError('live DEIXIS data directory is forbidden')
    database = path if path.suffix == '.sqlite' else path / 'library.sqlite'
    if database.resolve().is_relative_to(live):
        raise ValueError('live SQLite path is forbidden')
    return database


def feedback_order(pool, order, decisions):
    """Only batch-1 decisions are observed. Access failures carry no negative weight."""
    by_id = {r['id']: r for r in pool}
    first, pending = order[:RULE['batch_size']], order[RULE['batch_size']:]
    works = {by_id[s]['work_id'] for s in first}
    used = sorted((d for d in decisions if d['work_id'] in works),
                  key=lambda d: (d['created_at'], d['id']))
    latest = {}
    for d in used:
        latest[d['work_id'], d['stage']] = d
    positives, states = [], {}
    for sid in first:
        wid = by_id[sid]['work_id']
        abstract, full = latest.get((wid, 'abstract')), latest.get((wid, 'fulltext'))
        if full and full['outcome'] in {'include', 'criterion_not_met'}:
            state = 'included' if full['outcome'] == 'include' else 'excluded'
        elif abstract and abstract['outcome'] in {'candidate', 'out_of_scope'}:
            state = 'abstract_candidate' if abstract['outcome'] == 'candidate' else 'excluded'
        else:
            state = 'unknown'
        states[wid] = state
        if state in {'included', 'abstract_candidate'}:
            positives.append(by_id[sid])
    scores = ranking.graph_scores([by_id[s] for s in pending], positives)
    # Zero proximity adds no ordering information; preserve B if there is no observed edge.
    active = bool(positives) and any(v > 0 for v in scores.values())
    ranks = {'base': {s: (i + 1, True) for i, s in enumerate(pending)}}
    if active:
        ranks['feedback_graph'] = ranking.mean_ranks(scores, {s: bool(by_id[s]['references']) or scores[s] > 0
                                                             for s in pending})
    tail = ranking.fuse(ranks, tuple(ranks), k=RULE['rrf_k']) if active else pending
    return first + tail, {
        'used_decisions': used, 'batch_states': states, 'positive_work_ids': [r['work_id'] for r in positives],
        'graph_active': active, 'positive_proximity_pending': sum(v > 0 for v in scores.values()),
        'graph_scores': scores, 'ranks': ranks,
    }


def historical_inspection_order(fused: list[str], fused_code: list[str],
                     embedding_ranks: dict[str, tuple[float, bool]] | None) -> tuple[list[str], list[str]]:
    """The order screening reads, and the records the embedding arm brought to its front (SW8.1).

    A record outside the top `200` of the four code signals' own fused order but inside the embedding's
    top `50` goes to the front, in embedding order. Everything else keeps its fused place. A record
    the embedding never scored cannot be rescued by the tail rank it shares with the other unscored records: the
    embedding has no authority and adds nothing it did not measure (SW8.2).
    """
    if embedding_ranks is None:
        return list(fused), []
    place = {rid: position + 1 for position, rid in enumerate(fused_code)}
    rescued = [rid for rid in fused
               if place.get(rid, len(fused_code) + 1) > 200
               and embedding_ranks.get(rid, (0.0, False))[1]
               and embedding_ranks[rid][0] <= 50]
    rescued.sort(key=lambda rid: (embedding_ranks[rid][0], rid))
    lifted = set(rescued)
    return rescued + [rid for rid in fused if rid not in lifted], rescued



def compute_orders(data, rescue_signal=False):
    keyword_ids = set(data['baseline'])
    keyword_pool = [r for r in data['pool'] if r['id'] in keyword_ids]
    keyword = ranking.rank_pool(keyword_pool, data['verified'], set(data['query_words']), data['blocks'],
                                data['embedding_model'], data['similarities'],
                                compared_terms=data['compared_terms'])
    ranked = ranking.rank_pool(data['pool'], data['verified'], set(data['query_words']), data['blocks'],
                               data['embedding_model'], data['similarities'],
                               compared_terms=data['compared_terms'])
    # Historical A0/B retain rescue, independently of the product ranking policy.
    for result in (keyword, ranked):
        result['order'], result['rescued'] = historical_inspection_order(
            result['fused'], result['fused_code'], result['ranks'].get('embedding'))
    d, feedback = feedback_order(data['pool'], ranked['order'], data['decisions'])
    result = {'orders': {'A': data['baseline'], 'A0': keyword['order'], 'C0': keyword['fused'],
                       'B': ranked['order'], 'C': ranked['fused'], 'D': d},
            'keyword_signals': keyword['ranks'], 'keyword_missing_signals': keyword['reasons'],
            'keyword_rescued': keyword['rescued'],
            'signals': ranked['ranks'], 'missing_signals': ranked['reasons'],
            'rescued': ranked['rescued'], 'feedback': feedback}
    if rescue_signal:
        result['orders']['E'], result['rescue_signal_ranks'] = rescue_rrf_order(
            ranked['fused'], ranked['rescued'], ranked['ranks'].get('embedding', {}))
        result['rescue_signal_rule'] = RESCUE_SIGNAL
    return result


def read_snapshot(conn, benchmark, answer_id=None, ranking_step=None):
    answers = rows(conn, 'SELECT a.*, i.payload_json, i.created_at AS input_created_at, s.question AS scope_question FROM answers a'
                   ' LEFT JOIN step_inputs i ON i.id=a.step_input_id JOIN scope_revisions s'
                   ' ON s.research_id=a.research_id AND s.revision=a.scope_revision ORDER BY a.id')
    answers = [a for a in answers if (json.loads(a['payload_json']).get('question', {}).get('text')
               if a['payload_json'] else a['scope_question']) == benchmark['question']
               and (answer_id is None or a['id'] == answer_id)]
    if len(answers) != 1:
        raise ValueError('one matching pinned answer required; supply --answer if ambiguous')
    answer = answers[0]
    if not answer['payload_json']:
        if answer['status'] != 'no_evidence':
            raise ValueError('missing answer StepInput outside no_evidence path')
        answer['payload_json'] = '{}'
        answer['input_created_at'] = answer['created_at']
    rid, rev, cutoff = answer['research_id'], answer['scope_revision'], answer['input_created_at']
    step, binding, baseline = selected_ranking(conn, answer, json.loads(answer['payload_json']), ranking_step)
    if step is None:
        raise ValueError('keyword ranking unavailable')
    chain, chain_binding, _ = selected_ranking(conn, answer, json.loads(answer['payload_json']), keyword_step=step, chain=True)
    protocol = rows(conn, 'SELECT * FROM protocol_records WHERE research_id=? AND scope_revision=?'
                    ' AND body_sha256=?', (rid, rev, step['protocol_hash']))
    if len(protocol) != 1:
        raise ValueError('ranking protocol hash must resolve exactly')
    body = json.loads(protocol[0]['body_json'])
    scope = {'question': body['question']}
    approval = rows(conn, "SELECT output_json FROM run_steps WHERE run_id=? AND operation_key='protocol_approval'",
                    (step['run_id'],))
    if len(approval) != 1:
        raise ValueError('recorded approved vocabulary required')
    vocab = json.loads(approval[0]['output_json'])['approved']['vocabulary']
    expansion = rows(conn, "SELECT output_json FROM run_steps WHERE run_id=? AND operation_key='vocabulary_expansion'",
                     (step['run_id'],))
    expanded = json.loads(expansion[0]['output_json'] or '{}') if expansion else {}
    query_words, blocks = ranking.query_vocabulary(scope, vocab, expansion_blocks(expanded.get('expansion'), expanded.get('queries')))
    searches = rows(conn, 'SELECT id FROM search_runs WHERE research_id=? AND run_id=? AND retrieved_at<=?',
                    (rid, step['run_id'], cutoff))
    search_ids = {s['id'] for s in searches}
    hits = [h for h in rows(conn, 'SELECT * FROM candidate_hits WHERE research_id=? AND scope_revision=?', (rid, rev))
            if h['search_run_id'] in search_ids]
    candidates = rows(conn, 'SELECT * FROM candidates WHERE research_id=? AND scope_revision=? AND created_at<=?', (rid, rev, cutoff))
    member_ids = {h['source_version_id'] for h in hits} | {c['source_version_id'] for c in candidates
                  if c['search_run_id'] in search_ids}
    # Chain provenance is scoped to the pinned discovery, never another run's chain.
    links = rows(conn, 'SELECT * FROM chain_links WHERE research_id=? AND scope_revision=? AND run_id=? AND passed_filter=1'
                 ' ORDER BY seed_source_version_id,linked_openalex_id,direction',
                 (rid, rev, step['run_id']))
    member_ids |= {l['source_version_id'] for l in links if l['source_version_id']}
    versions = rows(conn, 'SELECT * FROM source_versions ORDER BY id')
    version_of = {v['id']: v for v in versions}
    pool_works = {version_of[s]['work_id'] for s in member_ids}
    abstracts = {}
    for p in rows(conn, "SELECT * FROM passages WHERE kind='abstract' ORDER BY id"):
        abstracts.setdefault(p['source_version_id'], []).append(p['text'])
    ids, refs = {}, {}
    for r in rows(conn, "SELECT * FROM identifier_mappings WHERE scheme='openalex' ORDER BY source_version_id,value"):
        ids.setdefault(r['source_version_id'], set()).add(r['value'])
    for r in rows(conn, 'SELECT * FROM record_references ORDER BY source_version_id,referenced_id'):
        refs.setdefault(r['source_version_id'], set()).add(r['referenced_id'])
    grouped = {}
    for v in versions:
        if v['id'] in member_ids:
            grouped.setdefault(v['work_id'], []).append({**v, 'abstract': ' '.join(abstracts.get(v['id'], [])) or None,
                                                       'own_ids': ids.get(v['id'], set()), 'references': refs.get(v['id'], set())})
    # Prefer the pinned ranking's representative; otherwise a stable source ID. Origins never break ties.
    recorded = baseline + rows(conn, 'SELECT v.* FROM record_signal_ranks r JOIN source_versions v ON v.id=r.source_version_id'
                             " WHERE r.ranking_step_id=? AND r.signal='inspection' ORDER BY r.rank,v.id",
                             (chain['id'] if chain else '',))
    heads = {}
    for v in recorded:
        if v['id'] in member_ids:
            heads.setdefault(v['work_id'], v['id'])
    pool = [ranking._work_row(heads.get(w, min(v['id'] for v in vs)), vs) for w, vs in sorted(grouped.items())]
    output = json.loads(step['output_json'])
    verified_ids = {s['source_version_id'] for s in output.get('seeds', []) if s['kind'] == 'verified'}
    # Recorded verified seeds only; later user selections must not leak into B/C.
    verified = []
    for s in sorted(verified_ids):
        v = version_of[s]
        verified.append({'id': s, 'work_id': v['work_id'], 'title': v['title'], 'abstract': ' '.join(abstracts.get(s, [])) or None,
                         'own_ids': frozenset(ids.get(s, set())), 'references': frozenset(refs.get(s, set())) or None})
    model = output.get('embedding_model')
    similarities = {s['source_version_id']: s['similarity'] for s in rows(conn,
        'SELECT * FROM source_similarities WHERE research_id=? AND scope_revision=? AND model=? AND created_at<=?',
        (rid, rev, model, cutoff))}
    decisions = rows(conn, 'SELECT d.*,v.work_id FROM stage_decisions d JOIN source_versions v ON v.id=d.source_version_id'
                     ' WHERE d.research_id=? AND d.scope_revision=? AND d.created_at<=?'
                     ' AND (d.superseded_at IS NULL OR d.superseded_at>?) ORDER BY d.created_at,d.id', (rid, rev, cutoff, cutoff))
    terms = [queried_form(t) for t in queried_terms(vocab, TASK_BLOCK)] if ranking.comparison_question(body['question']) else None
    baseline_ids = list(dict.fromkeys(v['work_id'] for v in baseline))
    pool_id = {r['work_id']: r['id'] for r in pool}
    if not set(baseline_ids) <= pool_works:
        raise ValueError('baseline work absent from scoped pool')
    return {'pool': pool, 'verified': verified, 'query_words': sorted(query_words), 'blocks': blocks,
            'embedding_model': model, 'similarities': similarities, 'compared_terms': terms, 'decisions': decisions,
            'baseline': [pool_id[w] for w in baseline_ids]}, versions, {
                'research_id': rid, 'answer_id': answer['id'], 'cutoff': cutoff,
                'cutoff_basis': 'answer_step_input' if answer['step_input_id'] else 'no_evidence_answer_created_at',
                'keyword_step': step['id'], 'keyword_binding': binding,
                'chain_step': chain['id'] if chain else None, 'chain_binding': chain_binding,
                'protocol_hash': protocol[0]['body_sha256'], 'pool_works': len(pool),
                'origins': sorted(hits, key=lambda h: (h['search_run_id'], h['source_version_id'])),
                'chain_links': links,
                'limits': ['Snapshot metadata may have been enriched after ranking; no historical text/reference snapshot is stored.',
                           'Batch-1 decisions are retrospective at answer-input cutoff, not a measured batch completion time.',
                           'Only positive feedback is fused; negative decisions remain visible without a penalty.',
                           'Stored passage vectors are not used; source-source embedding feedback is unmeasured.']}


def evaluate(replay, pool, versions, benchmark):
    wid = {r['id']: r['work_id'] for r in pool}
    pool_works = set(wid.values())
    arms = {}
    for arm, order in replay['orders'].items():
        place = {wid[s]: i + 1 for i, s in enumerate(order)}
        targets = []
        for p in benchmark['papers']:
            works = {v['work_id'] for v in matching_records(versions, p)}
            targets.append({'key': p['key'], 'label': p.get('label'), 'anchor': p.get('anchor', False),
                            'in_pool': bool(works & pool_works),
                            'rank': min((place[w] for w in works if w in place), default=None)})
        arms[arm] = {'relevant_top': {str(k): sum(t['label'] == 'ilgili' and t['rank'] is not None and t['rank'] <= k
                                                 for t in targets) for k in (20, 30, 50, 100)},
                     'targets': targets, 'keys': {t['key']: t['rank'] for t in targets if t['anchor']},
                     'pool_unranked': [t['key'] for t in targets if t['in_pool'] and t['rank'] is None],
                     'order_sha256': sha(canonical(order))}
    protected = [t['key'] for t in arms['A']['targets'] if t['anchor'] and t['rank'] is not None and t['rank'] <= 50]
    lost = [k for k in protected if arms['D']['keys'][k] is None or arms['D']['keys'][k] > 50]
    return arms, {'improved': arms['D']['relevant_top']['50'] > arms['A']['relevant_top']['50'],
                  'protected_keys': protected, 'lost_keys': lost,
                  'passed': arms['D']['relevant_top']['50'] > arms['A']['relevant_top']['50'] and not lost}


def evaluate_controls(replay, pool, versions, benchmark, arms):
    wid = {r['id']: r['work_id'] for r in pool}
    # Labels and identity matches enter only here, after every order is frozen.
    a0_targets = {t['key']: t for t in arms['A0']['targets']}
    comparisons = [{'key': t['key'], 'anchor': t['anchor'], 'label': t['label'],
                    'A': t['rank'], 'A0': a0_targets[t['key']]['rank'],
                    'delta': (a0_targets[t['key']]['rank'] - t['rank']
                              if t['rank'] is not None and a0_targets[t['key']]['rank'] is not None else None)}
                   for t in arms['A']['targets'] if t['anchor'] or t['label'] == 'ilgili']
    top_a, top_a0 = (set(wid[s] for s in replay['orders'][a][:50]) for a in ('A', 'A0'))
    denominator = min(50, len(replay['orders']['A']))
    overlap = len(top_a & top_a0) / denominator if denominator else None
    target_losses = [t['key'] for t in comparisons if t['label'] == 'ilgili' and t['A'] is not None
                     and t['A'] <= 50 and (t['A0'] is None or t['A0'] > 50)]
    anchor_drift = [t['key'] for t in comparisons if t['anchor'] and t['A'] is not None and t['A'] <= 50
                    and (t['delta'] is None or abs(t['delta']) > ROBUSTNESS['maximum_top50_anchor_delta'])]
    rescued_works = {wid[s] for s in replay['rescued']}
    rescued_targets = []
    for p in benchmark['papers']:
        matched = {v['work_id'] for v in matching_records(versions, p)} & rescued_works
        if matched:
            ranks = {a: next(t['rank'] for t in arms[a]['targets'] if t['key'] == p['key']) for a in ('B', 'C')}
            rescued_targets.append({'key': p['key'], 'label': p.get('label'), 'anchor': p.get('anchor', False),
                                    'rescued': True, 'work_ids': sorted(matched), **ranks,
                                    'lost_from_top50': ranks['B'] <= 50 and ranks['C'] > 50})
    return {
        'robustness': {'rule': ROBUSTNESS, 'targets': comparisons, 'top50_intersection': len(top_a & top_a0),
                       'top50_union': len(top_a | top_a0), 'top50_overlap_fraction': overlap,
                       'top50_jaccard': len(top_a & top_a0) / len(top_a | top_a0) if top_a | top_a0 else None,
                       'order_equal': replay['orders']['A'] == replay['orders']['A0'],
                       'lost_relevant_targets': target_losses, 'drifting_anchors': anchor_drift,
                       'passed': overlap is not None and overlap >= ROBUSTNESS['minimum_overlap_fraction']
                                 and not target_losses and not anchor_drift},
        'rescued_targets': rescued_targets,
        'rescue_signal_measurement_required': any(t['label'] == 'ilgili' and t['lost_from_top50']
                                                 for t in rescued_targets)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--benchmark', required=True, type=Path)
    parser.add_argument('--answer')
    parser.add_argument('--ranking-step')
    parser.add_argument('--rescue-signal', action='store_true', help='also measure the fixed rescue RRF ablation E')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        benchmark = load_benchmark(args.benchmark)
        database = snapshot_path(args.data_dir)
        conn = connect(database)
        try:
            data, versions, provenance = read_snapshot(conn, benchmark, args.answer, args.ranking_step)
            one, two = compute_orders(data, args.rescue_signal), compute_orders(data, args.rescue_signal)
        finally:
            conn.close()
        first, second = sha(canonical(one)), sha(canonical(two))
        if first != second:
            raise ValueError('non-deterministic replay')
        arms, acceptance = evaluate(one, data['pool'], versions, benchmark)
        controls = evaluate_controls(one, data['pool'], versions, benchmark, arms)
        result = {'format': 'ranking-replay-v2', 'benchmark': benchmark['name'], 'rule': RULE,
                  'rule_sha256': sha(canonical(RULE)), 'benchmark_sha256': sha(canonical(benchmark)),
                  'snapshot_sha256': hashlib.sha256(database.read_bytes()).hexdigest(), 'provenance': provenance,
                  'arms': arms, 'acceptance': acceptance, 'evaluation': controls, 'replay': one,
                  'determinism': {'first': first, 'second': second, 'equal': first == second},
                  'pool': [{**r, 'own_ids': sorted(r['own_ids']), 'references': sorted(r['references']) if r['references'] is not None else None}
                           for r in data['pool']]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        lines = [f"# {benchmark['name']} sıralama replay’i", '', '| Kol | İlk 20 | İlk 30 | İlk 50 | İlk 100 | Anahtar sıraları |',
                 '|---|---:|---:|---:|---:|---|']
        for a, v in arms.items():
            lines.append(f"| {a} | " + ' | '.join(str(v['relevant_top'][str(k)]) for k in (20,30,50,100)) +
                         ' | ' + ', '.join(f'{k}: {r}' for k,r in v['keys'].items()) + ' |')
        lines += ['', f"Göreli kabul: {'geçti' if acceptance['passed'] else 'geçmedi'}. Determinizm: iki hesap aynı hash.",
                  'İlk-K sayıları donmuş ilgili hedef kapsamasıdır; P@K değildir. D, kayıtlı kararlarla retrospektif replay’dir.',
                  '', f"A0≈A: {'geçti' if controls['robustness']['passed'] else 'geçmedi'}; "
                  f"ilk 50 örtüşmesi {controls['robustness']['top50_intersection']}/{min(50, len(data['baseline']))}.",
                  f"Kurtarılan işler: {len(one['rescued'])}; kurtarılan hedefler: {len(controls['rescued_targets'])}.",
                  '| Hedef | A | A0 | A0 − A |', '|---|---:|---:|---:|']
        lines += [f"| {t['key']} | {t['A']} | {t['A0']} | {t['delta']} |"
                  for t in controls['robustness']['targets']]
        lines += ['', 'Kurtarılan hedefler (JSON kimlik eşleştirmesi; ilgili etiketler ayrıca belirtilir):',
                  json.dumps(controls['rescued_targets'], ensure_ascii=False),
                  'A0/C0 aynı keyword iş havuzunu, B/C aynı birleşik havuzu kullanır. '
                  'Sinyaller her havuzda yeniden hesaplanır; metadata tarihsel sürümü doğrulanmış değildir.']
        args.output.with_suffix('.md').write_text('\n'.join(lines) + '\n')
        print(benchmark['name'], {a: v['relevant_top']['50'] for a,v in arms.items()}, acceptance)
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

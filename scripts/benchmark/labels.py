"""Blind P@20 owner forms, independent model forms for ranks 21–50, and adjudication."""
from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

try:
    from .common import canonical, identity, sha
except ImportError:
    from common import canonical, identity, sha

LABELS = {'relevant', 'irrelevant', 'uncertain'}
DEPTHS = {'metadata', 'title_only', 'abstract', 'selected_pdf_passage', 'full_text'}


def forms(question, arms, seed=20261006):
    """Input: {arm: [records in unique-work ranking order]}. Private key stays separate."""
    owner, models, mapping, evidence = {}, {}, {}, {}
    for arm, records in arms.items():
        seen = set()
        unique = []
        for record in records:
            key = identity(record)
            if key is None:
                raise ValueError('blind form requires resolved work identity')
            if key not in seen:
                seen.add(key)
                unique.append((key, record))
        for rank, (key, record) in enumerate(unique[:50], 1):
            # Opaque identifiers are independent of the arm and ranking position.
            item_id = sha(question + '\n' + key)[:24]
            shown = evidence.setdefault(item_id,{'title':record.get('title'),'abstract':record.get('abstract')})
            mapping.setdefault(item_id, {'identity': key, 'positions': [],
                'evidence_sha256':sha(canonical(shown))})['positions'].append(
                {'arm': arm, 'rank': rank})
            item = {'item_id': item_id, **shown,
                    'label': None, 'reason': None, 'reading_depth': None}
            (owner if rank <= 20 else models)[item_id] = item
    rng = random.Random(seed)
    # A work in anyone's first 20 receives the same owner label in all arms.
    models = {k: v for k, v in models.items() if k not in owner}
    owner_rows, model_rows = list(owner.values()), list(models.values())
    rng.shuffle(owner_rows)
    rng.shuffle(model_rows)
    manifest = {'question': question, 'mapping': mapping, 'shuffle_seed': seed}
    form_id = sha(canonical(manifest))
    def form(role, items):
        return {'format': 'blind-relevance-v1', 'form_id': form_id, 'question': question,
                'evaluator': role, 'items': copy.deepcopy(items)}
    return {'owner': form('owner', owner_rows), 'model_1': form('model_1', model_rows),
            'model_2': form('model_2', model_rows), 'private_key': manifest | {'form_id': form_id}}


def merge(left, right):
    if left['form_id'] != right['form_id'] or left['question'] != right['question']:
        raise ValueError('different blind forms')
    if left['evaluator'] == right['evaluator']:
        raise ValueError('two distinct evaluators required')
    def indexed(form):
        result = {}
        for row in form['items']:
            if row['item_id'] in result:
                raise ValueError('duplicate item_id')
            if row['label'] not in LABELS or row['reading_depth'] not in DEPTHS or not row['reason']:
                raise ValueError('every label requires a reason and reading depth')
            result[row['item_id']] = row
        return result
    a, b = indexed(left), indexed(right)
    if a.keys() != b.keys():
        raise ValueError('different item sets')
    agreed, disputed = [], []
    for key in a:
        if (a[key]['title'], a[key]['abstract']) != (b[key]['title'], b[key]['abstract']):
            raise ValueError('different evidence for item')
        record = {'item_id': key, 'assessments': [a[key], b[key]]}
        if a[key]['label'] == b[key]['label']:
            agreed.append(record | {'label': a[key]['label'], 'authority': 'model_agreement'})
        else:
            disputed.append(record | {'title': a[key]['title'], 'abstract': a[key]['abstract'],
                                     'label': None, 'reason': None, 'reading_depth': None})
    return {'form_id': left['form_id'], 'question': left['question'], 'agreed': agreed,
            'owner_disagreements': disputed, 'human_verified': False}


def score(private_key, owner, merged, adjudications=None):
    """Unresolved model disagreements stay in the denominator and never count as hits."""
    if owner['form_id'] != private_key['form_id'] or merged['form_id'] != owner['form_id']:
        raise ValueError('different blind forms')
    expected_owner = {key for key,item in private_key['mapping'].items()
                      if any(p['rank']<=20 for p in item['positions'])}
    labels = {}
    for row in owner['items']:
        key = row['item_id']
        if key not in expected_owner or key in labels:
            raise ValueError('unexpected or duplicate owner item')
        if (row['label'] not in LABELS or not row.get('reason') or row.get('reading_depth') not in DEPTHS or
            sha(canonical({'title':row['title'],'abstract':row['abstract']})) != private_key['mapping'][key]['evidence_sha256']):
            raise ValueError('invalid owner assessment or changed evidence')
        labels[key] = row['label']
    if labels.keys()!=expected_owner:
        raise ValueError('owner form incomplete')
    model_ids = [r['item_id'] for r in merged['agreed']+merged['owner_disagreements']]
    if len(set(model_ids))!=len(model_ids) or set(model_ids) != private_key['mapping'].keys()-expected_owner:
        raise ValueError('incomplete or duplicate model assessments')
    for item in merged['agreed']+merged['owner_disagreements']:
        for assessment in item['assessments']:
            shown = {'title':assessment['title'],'abstract':assessment['abstract']}
            if sha(canonical(shown))!=private_key['mapping'][item['item_id']]['evidence_sha256']:
                raise ValueError('changed model evidence')
        if item in merged['agreed'] and item['label'] not in LABELS:
            raise ValueError('invalid merged label')
    labels.update({r['item_id']: r['label'] for r in merged['agreed']})
    labels.update({r['item_id']: 'uncertain' for r in merged['owner_disagreements']})
    for row in adjudications or []:
        if (row['item_id'] not in {r['item_id'] for r in merged['owner_disagreements']} or
            row['label'] not in LABELS or not row.get('reason') or row.get('reading_depth') not in DEPTHS):
            raise ValueError('invalid owner adjudication')
        labels[row['item_id']] = row['label']
    grouped = {}
    for key, item in private_key['mapping'].items():
        for pos in item['positions']:
            grouped.setdefault(pos['arm'], []).append((pos['rank'], labels.get(key, 'uncertain')))
    result = {}
    for arm, rows in grouped.items():
        result[arm] = {}
        for k in (20, 50):
            values = [v for rank, v in rows if rank <= k]
            counts = {v: values.count(v) for v in LABELS}
            result[arm][f'P@{k}'] = counts | {'denominator': len(values),
                'value': counts['relevant'] / len(values) if values else None,
                'authority': 'owner' if k == 20 else 'mixed_owner_and_model_assessment'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    form = commands.add_parser('forms')
    form.add_argument('input', type=Path)
    form.add_argument('output', type=Path)
    combine = commands.add_parser('merge')
    combine.add_argument('left', type=Path)
    combine.add_argument('right', type=Path)
    combine.add_argument('output', type=Path)
    scoring = commands.add_parser('score')
    scoring.add_argument('private_key',type=Path)
    scoring.add_argument('owner',type=Path)
    scoring.add_argument('merged',type=Path)
    scoring.add_argument('output',type=Path)
    scoring.add_argument('--adjudications',type=Path)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text())
    if args.command == 'forms':
        value = read(args.input)
        args.output.mkdir(parents=True, exist_ok=False)
        for name, content in forms(value['question'], value['arms']).items():
            (args.output / (name + '.json')).write_text(json.dumps(content, indent=2, ensure_ascii=False))
    elif args.command=='merge':
        args.output.write_text(json.dumps(merge(read(args.left), read(args.right)), indent=2, ensure_ascii=False))
    else:
        result=score(read(args.private_key),read(args.owner),read(args.merged),
                     read(args.adjudications) if args.adjudications else None)
        args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()

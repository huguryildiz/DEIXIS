"""Read-only measurement of a pinned answer in an explicitly supplied isolated SQLite snapshot."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from .common import canonical, doi, load_benchmark, matching_records, sanitize, sha
except ImportError:
    from common import canonical, doi, load_benchmark, matching_records, sanitize, sha

ROOT = Path(__file__).resolve().parents[2]
UNMEASURABLE = 'ölçülemiyor'


def data_dir():
    value = os.environ.get('DEIXIS_DATA_DIR')
    if not value or not value.strip():
        raise ValueError('DEIXIS_DATA_DIR must explicitly identify an isolated measurement snapshot')
    return Path(value).expanduser()


def connect(path=None):
    path = Path(path) if path is not None else data_dir() / 'library.sqlite'
    if not path.is_file():
        raise ValueError(f'SQLite snapshot does not exist: {path}')
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')  # consistent measurements across all queries
    return conn


def rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params)]


def norm(text):
    return re.sub(r'\W+', ' ', (text or '').casefold()).strip()


def paper_match(versions, paper):
    matched = [v['id'] for v in matching_records(versions, paper)]
    possible = [v['id'] for v in versions if not matched and paper.get('title') and
                norm(v['title']) == norm(paper['title'])]
    return matched, possible


def paper_versions(conn, paper):
    return paper_match(rows(conn, 'SELECT * FROM source_versions'), paper)[0]


def seconds(start, finish):
    if not start or not finish:
        return UNMEASURABLE
    try:
        value = (datetime.fromisoformat(finish.replace('Z', '+00:00')) -
                 datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds()
        return value if value >= 0 else UNMEASURABLE
    except ValueError:
        return UNMEASURABLE


def raw_count(conn, search):
    """Count only retained provider records; an inaccessible or unfamiliar body is not zero."""
    path = search.get('raw_payload_path')
    if not path:
        error = json.loads(search['error_json'] or '{}')
        return error.get('returned', UNMEASURABLE), 'stored_returned_or_missing_payload'
    database = Path(conn.execute('PRAGMA database_list').fetchone()[2])
    root = (database.parent / 'provider-payloads').resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        return UNMEASURABLE, 'payload_outside_snapshot'
    try:
        payload = json.loads(target.read_text())
        if search.get('payload_sha256') and sha(canonical(payload)) != search['payload_sha256']:
            return UNMEASURABLE, 'payload_hash_mismatch'
        for key in ('results','data','records'):
            if isinstance(payload.get(key),list):
                return len(payload[key]), 'retained_provider_payload'
        if isinstance(payload.get('message'),dict) and isinstance(payload['message'].get('items'),list):
            return len(payload['message']['items']), 'retained_provider_payload'
        if isinstance(payload.get('referenced_works'),list):
            return len(payload['referenced_works']), 'retained_provider_payload'
    except (OSError,ValueError,AttributeError):
        pass
    return UNMEASURABLE, 'unreadable_or_unsupported_payload'


def selected_ranking(conn, answer, payload, explicit=None):
    reference = payload.get('ranking_step_id')
    step_id = explicit or reference
    binding = 'operator_pinned' if explicit else 'recorded_step_input'
    if step_id is None:
        candidates = rows(conn, "SELECT s.* FROM run_steps s JOIN runs r ON r.id=s.run_id"
                          " WHERE r.research_id=? AND r.scope_revision=?"
                          " AND s.kind='code:ranking' AND s.status='succeeded'"
                          " AND s.finished_at IS NOT NULL AND julianday(s.finished_at)<=julianday(?)"
                          " ORDER BY julianday(s.finished_at) DESC, s.id DESC LIMIT 1",
                          (answer['research_id'], answer['scope_revision'], answer['input_created_at']))
        if candidates:
            step_id, binding = candidates[0]['id'], 'inferred_by_time'
        else:
            return None, 'not_recorded_require_ranking_step', []
    steps = rows(conn, 'SELECT s.*, r.research_id, r.scope_revision FROM run_steps s JOIN runs r ON r.id=s.run_id'
                 ' WHERE s.id=?', (step_id,))
    if (not steps or steps[0]['research_id'] != answer['research_id'] or
            steps[0]['scope_revision'] != answer['scope_revision'] or
            steps[0]['kind'] != 'code:ranking' or steps[0]['status'] != 'succeeded' or
            seconds(steps[0]['finished_at'], answer['input_created_at']) == UNMEASURABLE):
        raise ValueError('ranking step is not a successful pre-answer inspection ranking in this scope')
    return steps[0], binding, rows(conn,
        "SELECT v.*, r.rank FROM record_signal_ranks r JOIN source_versions v ON v.id=r.source_version_id"
        " WHERE r.ranking_step_id=? AND r.signal='inspection' ORDER BY r.rank, v.id", (step_id,))


def measure(conn, rid, answer_id, bench, ranking_step=None):
    found = rows(conn, 'SELECT a.*, i.payload_json, i.created_at AS input_created_at, i.skill_package_hash'
                 ' FROM answers a JOIN step_inputs i ON i.id=a.step_input_id'
                 ' WHERE a.research_id=? AND a.id=?', (rid, answer_id))
    if not found or not found[0]['draft_json']:
        raise ValueError('pinned answer with stored StepInput and draft required')
    answer = found[0]
    revision, cutoff = answer['scope_revision'], answer['input_created_at']
    payload, draft = json.loads(answer['payload_json']), json.loads(answer['draft_json'])
    if payload.get('question', {}).get('text') != bench['question']:
        raise ValueError('answer question does not match frozen English benchmark question')
    versions = rows(conn, 'SELECT * FROM source_versions')
    version_of = {v['id']:v for v in versions}
    searches = rows(conn, 'SELECT sr.*, s.operation_key, s.started_at, s.finished_at, r.scope_revision'
                    ' FROM search_runs sr JOIN runs r ON r.id=sr.run_id JOIN run_steps s ON s.id=sr.step_id'
                    ' WHERE sr.research_id=? AND r.scope_revision=? AND sr.retrieved_at<=?'
                    ' ORDER BY sr.retrieved_at, sr.id', (rid, revision, cutoff))
    search_of = {s['id']:s for s in searches}
    hits = [h for h in rows(conn, 'SELECT * FROM candidate_hits WHERE research_id=? AND scope_revision=?',
                           (rid, revision)) if h['search_run_id'] in search_of]
    candidates = rows(conn, 'SELECT * FROM candidates WHERE research_id=? AND scope_revision=? AND created_at<=?',
                      (rid, revision, cutoff))
    pool_ids = {h['source_version_id'] for h in hits} | {c['source_version_id'] for c in candidates}
    pool_works = {version_of[v]['work_id'] for v in pool_ids if v in version_of}
    step, binding, raw_ranking = selected_ranking(conn, answer, payload, ranking_step)
    ranking, seen = [], set()
    for v in raw_ranking:
        if v['work_id'] not in seen:
            seen.add(v['work_id'])
            ranking.append(v)
    place = {v['work_id']:i+1 for i,v in enumerate(ranking)}
    given_sources = {s['source_id'] for s in payload.get('sources', [])}
    given, given_by_id = {}, {}
    for p in payload.get('passages', []):
        if p.get('text', '').strip():
            given.setdefault(p['source_id'], []).append(p)
            given_by_id[p['passage_id']] = p
    links = rows(conn, 'SELECT e.*, c.label FROM evidence_links e JOIN claims c ON c.id=e.claim_id'
                 ' WHERE c.answer_id=?', (answer_id,))
    stored_passages = {p['id']:p for p in rows(conn,'SELECT * FROM passages')}
    valid_links, invalid_links = [], []
    for link in links:
        passage, anchor = given_by_id.get(link['passage_id']), link.get('anchor_text')
        owned = stored_passages.get(link['passage_id'])
        valid = (answer['status'] == 'structurally_valid' and link['step_input_id'] == answer['step_input_id'] and
                 passage and passage['source_id'] == link['source_version_id'] and anchor and
                 anchor in passage['text'] and owned and owned['source_version_id']==link['source_version_id'] and
                 anchor in owned['text'] and link.get('anchor_match') in {'exact','normalized','fuzzy'})
        (valid_links if valid else invalid_links).append(link)
    decisions = rows(conn, 'SELECT * FROM stage_decisions WHERE research_id=? AND scope_revision=?'
                     ' AND created_at<=? AND (superseded_at IS NULL OR superseded_at>?)', (rid, revision, cutoff, cutoff))
    selections = {}
    for selection in rows(conn, 'SELECT * FROM selection_history WHERE research_id=? AND created_at<=?'
                          ' ORDER BY created_at, id', (rid, cutoff)):
        selections[selection['source_version_id']] = selection
    for selection in rows(conn, 'SELECT * FROM selections WHERE research_id=? AND updated_at<=?', (rid, cutoff)):
        selections.setdefault(selection['source_version_id'], selection)
    pdfs = rows(conn, 'SELECT p.* FROM pdf_candidates p JOIN pdf_discovery_runs d ON d.id=p.discovery_run_id'
                ' WHERE d.research_id=? AND p.discovered_at<=?', (rid,cutoff))
    pdf_discovery = rows(conn, 'SELECT * FROM pdf_discovery_runs WHERE research_id=? AND created_at<=?', (rid, cutoff))
    assets = rows(conn,'SELECT * FROM source_assets WHERE retrieved_at<=?',(cutoff,))
    items = []
    for paper in bench['papers']:
        svids, possible = paper_match(versions, paper)
        ids = set(svids)
        works = {version_of[s]['work_id'] for s in ids}
        target_hits = [h for h in hits if h['source_version_id'] in ids]
        first_only = [c for c in candidates if c['source_version_id'] in ids and c['search_run_id'] in search_of and
                      not any(h['source_version_id'] == c['source_version_id'] for h in target_hits)]
        origins = [{k:search_of[h['search_run_id']][k] for k in
                   ('id','run_id','provider','query_text','operation_key','access_mode','status')}
                   for h in target_hits + first_only]
        passages = [p for sid in ids for p in given.get(sid, [])]
        attempts = [p for p in pdfs if p['source_version_id'] in ids and p['attempted_at'] and p['attempted_at']<=cutoff]
        claims = sorted({l['label'] for l in valid_links if l['source_version_id'] in ids})
        rank = min((place[w] for w in works if w in place), default=None)
        items.append({'target_key':paper['key'], 'doi':paper.get('doi'), 'title':paper.get('title'),
            'label':paper.get('label'), 'stratum':paper.get('stratum','unstratified'), 'anchor':paper.get('anchor',False),
            'identity_status':'resolved' if svids else 'title_match_requires_adjudication' if possible else 'not_found',
            'possible_title_versions':possible, 'source_versions':[version_of[s] for s in svids],
            'found':bool(ids & pool_ids), 'search_origins':origins,
            'origins_complete':(ids & pool_ids)<= {h['source_version_id'] for h in target_hits} if ids & pool_ids else None,
            'rank':rank, 'rank_state':'ranking_unmeasurable' if step is None else
                'ranked' if rank else 'found_not_ranked' if ids & pool_ids else 'not_found',
            'abstract':[d for d in decisions if d['source_version_id'] in ids and d['stage']=='abstract'],
            'fulltext':[d for d in decisions if d['source_version_id'] in ids and d['stage']=='fulltext'],
            'fulltext_decision_state':'recorded' if any(d['source_version_id'] in ids and d['stage']=='fulltext'
                                                     for d in decisions) else 'no_decision',
            'pdf_access':{'recorded_attempts':len(attempts), 'attempt_count_is_complete':False,
                'attempts':attempts, 'discovery':[d for d in pdf_discovery if d['source_version_id'] in ids],
                'assets_available':[{'id':a['id'],'origin':a['origin'],'retrieved_at':a['retrieved_at'],
                                     'extraction_status':a['extraction_status']} for a in assets if a['source_version_id'] in ids],
                'state':'attempt_recorded' if attempts else 'no_recorded_attempt',
                'limitation':'mutable PDF candidates preserve latest attempt only; absence does not prove no send'},
            'selection':[selections[s] for s in ids if s in selections],
            'given_to_model':bool(ids & given_sources), 'passage_given_to_model':bool(passages),
            'passage_count':len(passages), 'passages_given':[p.get('reading_depth') for p in passages],
            'cited_in':claims, 'cited_versions':sorted({l['source_version_id'] for l in valid_links
                                                     if l['source_version_id'] in ids}),
            'draft_cited_in':sorted({c['claim_label'] for c in draft.get('claims', [])
                if any(given_by_id.get(pid,{}).get('source_id') in ids for pid in c.get('passage_ids',[]))})})
    layers = {}
    for layer in sorted({r['stratum'] for r in items} | {'all','keys'}):
        group = [r for r in items if (layer=='all' or layer=='keys' and r['anchor'] or r['stratum']==layer)
                 and r['label']=='ilgili']
        counts = {name:sum(bool(r[name]) for r in group) for name in
                  ('found','given_to_model','passage_given_to_model','cited_in')}
        counts.update({f'top_{k}':sum(r['rank'] is not None and r['rank']<=k for r in group)
                      if step else None for k in (20,50)})
        layers[layer] = {'denominator':len(group), 'counts':counts,
                         'ratios':{k:v/len(group) if group and v is not None else None for k,v in counts.items()}}
    runs = rows(conn, 'SELECT * FROM runs WHERE research_id=? AND scope_revision=? AND created_at<=?'
                ' ORDER BY created_at, id', (rid, revision, cutoff))
    usage = [{'run_id':r['id'], 'kind':r['kind'], 'status':r['status'],
              'counter_snapshot_updated_at':r['updated_at'], 'usage':json.loads(r['usage_json'])} for r in runs]
    sessions = rows(conn, 'SELECT m.*, i.task_type, i.attempt AS input_attempt FROM model_sessions m'
                    ' JOIN step_inputs i ON i.id=m.step_input_id WHERE m.research_id=? AND m.started_at<=?',
                    (rid, answer['created_at']))
    run_ids = {r['id'] for r in runs}
    calls = {}
    for session in sessions:
        if session['run_id'] not in run_ids:
            continue
        key = '|'.join(str(session[k]) for k in ('task_type','connection','requested_model'))
        group = calls.setdefault(key, {'recorded_adapter_invocations':0, 'statuses':{}, 'inputs_after_first_attempt':0,
                                      'repair_sends':UNMEASURABLE, 'retry_sends':UNMEASURABLE,
                                      'real_provider_sends':UNMEASURABLE})
        group['recorded_adapter_invocations'] += 1
        group['statuses'][session['status']] = group['statuses'].get(session['status'],0)+1
        group['inputs_after_first_attempt'] += int(session['input_attempt']>1)
    def counter(name):
        eligible = [r for r in usage if r['kind'] in {'discovery','answer'}]
        complete = bool(eligible) and all(name in r['usage'] and
                   r['counter_snapshot_updated_at']<=answer['created_at'] for r in eligible)
        return sum(r['usage'][name] for r in eligible) if complete else UNMEASURABLE
    start = min((r['created_at'] for r in runs if r['kind'] in {'discovery','answer'}), default=None)
    all_steps = [s for s in rows(conn, 'SELECT s.* FROM run_steps s JOIN runs r ON r.id=s.run_id'
                              ' WHERE r.research_id=? AND r.scope_revision=?', (rid, revision))
                 if s['started_at'] and s['started_at']<=answer['created_at']]
    direction_claims = []
    for claim in draft.get('claims', []):
        sides = bench.get('direction_terms', [])
        if sides and all(any(t.casefold() in claim['text'].casefold() for t in side) for side in sides):
            direction_claims.append({'label':claim['claim_label'], 'text':claim['text'],
                'cites':[r['target_key'] for r in items if claim['claim_label'] in r['cited_in']]})
    cache = [s for s in searches if s['access_mode']=='cache']
    first_valid = rows(conn, "SELECT created_at FROM answers WHERE research_id=? AND scope_revision=?"
                       " AND status='structurally_valid' AND created_at<=? ORDER BY created_at LIMIT 1",
                       (rid,revision,answer['created_at']))
    abstract_of = {p['source_version_id']:p['text'] for p in rows(conn,"SELECT * FROM passages WHERE kind='abstract'")}
    counted = [raw_count(conn,s) for s in searches]
    raw_counts = [value for value,_ in counted]
    traces, missing_traces = [], []
    search_steps = {s['step_id']:s for s in searches}
    for s in all_steps:
        if s['kind'].startswith('model:'):
            continue
        output = json.loads(s['output_json'] or '{}')
        trace = output.get('transport') or {}
        subrequests = [r for d in trace.get('dispatches',[]) for r in d.get('subrequests',[])]
        if s['id'] in search_steps and not subrequests:
            missing_traces.append(s['id'])
        for request in subrequests:
            traces.append({'step_id':s['id'], 'purpose':s['operation_key'],
                'provider':search_steps.get(s['id'],{}).get('provider',UNMEASURABLE),
                'endpoint':request.get('url'), **request})
    observed_sends = sum(t['sends'] for t in traces)
    totals = {'raw_records':sum(raw_counts) if all(isinstance(n,int) for n in raw_counts) else UNMEASURABLE,
        'raw_count_basis':'retained provider payload or explicit returned telemetry; never filtered result_count',
        'raw_counts_by_search':dict(zip(search_of,raw_counts)),
        'raw_count_status_by_search':dict(zip(search_of,[status for _,status in counted])),
        'stored_filtered_records':sum(s['result_count'] for s in searches),
        'raw_all_http_responses':UNMEASURABLE, 'cache_records':sum(s['result_count'] for s in cache) if cache else UNMEASURABLE,
        'network_records':UNMEASURABLE if any(s['access_mode']!='cache' for s in searches) else 0,
        'unique_works':len(pool_works), 'source_versions':len(pool_ids), 'ranked_unique_works':len(ranking),
        'sources_given':len(given_sources), 'sources_with_passages':len(given), 'passages_given':len(given_by_id),
        'cited_works':len({version_of[l['source_version_id']]['work_id'] for l in valid_links}),
        'abstract_decided_works':len({version_of[d['source_version_id']]['work_id'] for d in decisions if d['stage']=='abstract'}),
        'fulltext_decided_works':len({version_of[d['source_version_id']]['work_id'] for d in decisions if d['stage']=='fulltext'}),
        'included_works':len({version_of[s]['work_id'] for s,v in selections.items()
                             if v.get('state',v.get('new_state'))=='included'}), 'inspection_depth':UNMEASURABLE}
    return sanitize({'format':'search-measurement-v1', 'benchmark':bench['name'], 'research_id':rid,
        'answer_id':answer_id, 'answer_status':answer['status'], 'scope_revision':revision,
        'selection_revision':answer.get('selection_revision'), 'step_input_id':answer['step_input_id'],
        'answer_run_id':answer['run_id'], 'run_ids':[r['id'] for r in runs],
        'skill_package_hash':answer['skill_package_hash'], 'question_sha256':bench['question_sha256'],
        'ranking_step_id':step['id'] if step else None, 'ranking_binding':binding, 'totals':totals,
        'frozen_pool':{'format':'frozen-search-pool-v1', 'question_sha256':bench['question_sha256'],
            'research_id':rid, 'answer_id':answer_id, 'scope_revision':revision,
            'order_rule':'pinned inspection work order, then first recorded search time and version ID',
            'records':[{'verified_work_id':version_of[s]['work_id'], 'source_version_id':s,
                'doi':version_of[s]['doi'], 'title':version_of[s]['title'], 'version_label':version_of[s]['version_label'],
                'abstract':abstract_of.get(s), 'origins':[{k:search_of[h['search_run_id']][k] for k in
                    ('id','provider','query_text','operation_key')} for h in hits if h['source_version_id']==s]}
                for s in sorted(pool_ids,key=lambda s:(place.get(version_of[s]['work_id'],len(place)+1),
                    min((search_of[h['search_run_id']]['retrieved_at'] for h in hits
                    if h['source_version_id']==s),default=cutoff),s))]},
        'merge_manifest':[{'work_id':w, 'versions':sorted(v for v in pool_ids if version_of[v]['work_id']==w)}
                          for w in sorted(pool_works)],
        'ranked_records':[{'verified_work_id':v['work_id'], 'source_version_id':v['id'], 'doi':v['doi'],
                           'title':v['title'], 'abstract':abstract_of.get(v['id'])} for v in ranking],
        'searches':searches, 'papers':items, 'coverage':layers, 'run_usage_snapshots':usage,
        'calls':{'models_by_role':calls, 'model_calls_budget_units':counter('model_calls'),
                 'model_real_sends':UNMEASURABLE, 'embedding_real_sends':UNMEASURABLE,
                 'provider_requests_budget_units':counter('provider_requests'), 'provider_sends':counter('provider_sends'),
                 'provider_sends_scope':'search counter only; chaining and lookups have separate counters',
                 'chain_sends':counter('chain_sends'), 'lookup_sends':counter('lookup_sends'),
                 'provider_sends_total':UNMEASURABLE,
                 'observed_provider_sends':observed_sends if traces else UNMEASURABLE,
                 'provider_sends_by_endpoint':traces if traces else UNMEASURABLE,
                 'missing_search_transport_steps':missing_traces,
                 'pdf_http_sends':UNMEASURABLE, 'other_http_sends':UNMEASURABLE},
        'durations':{'to_search_pool_seconds':seconds(start,max((s['retrieved_at'] for s in searches),default=None)),
            'to_ranking_seconds':seconds(start,step['finished_at'] if step else None),
            'to_selected_answer_seconds':seconds(start,answer['created_at']),
            'to_first_valid_answer_seconds':seconds(start,first_valid[0]['created_at'] if first_valid else None),
            'human_wait_seconds':UNMEASURABLE, 'provider_wait_seconds':UNMEASURABLE,
            'model_wait_seconds':UNMEASURABLE, 'post_answer_table_seconds':UNMEASURABLE,
            'requested_end_state_seconds':UNMEASURABLE,
            'step_spans':[{'step_id':s['id'], 'kind':s['kind'], 'seconds':seconds(s['started_at'],s['finished_at'])}
                          for s in all_steps]},
        'invalid_or_draft_links':invalid_links, 'verified_anchor_links':valid_links,
        'direction_claims':direction_claims, 'expected_direction':bench.get('expected_direction'),
        'gate_a': (answer['status']=='structurally_valid' and all(r['cited_in'] for r in items if r['anchor']))
                  if bench['name']=='dbr_vbf' else None,
        'answer_elements':bench.get('answer_elements', []), 'semantic_support':'requires_owner_passage_assessment',
        'limitations':['PDF attempt history and older send/cache telemetry may be incomplete.',
            'An operator-pinned inherited ranking requires provenance review.',
            'Stored work identity is used; title-only guesses and unverified alternate DOIs do not count.']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('research_id')
    parser.add_argument('--benchmark', default=ROOT / 'scripts/benchmark/dbr_vbf.json', type=Path)
    parser.add_argument('--answer', required=True, help='pinned answer ID; never defaults to latest')
    parser.add_argument('--ranking-step', help='audited inspection ranking pin overriding automatic binding')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--force', action='store_true', help='allow replacing an existing output file')
    args = parser.parse_args()
    try:
        if args.output.exists() and not args.force:
            raise ValueError('output already exists; use --force to replace it')
        conn = connect()
        try:
            result = measure(conn,args.research_id,args.answer,load_benchmark(args.benchmark),args.ranking_step)
        finally:
            conn.close()
        result['git_head'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        result['git_status'] = subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)
        with args.output.open('w' if args.force else 'x') as output:
            output.write(json.dumps(result,indent=2,ensure_ascii=False))
        print(f"{args.answer}: {result['totals']['unique_works']} unique works; ranking {result['ranking_step_id']}")
        print(f'written {args.output}')
        return 0
    except (ValueError,sqlite3.Error,OSError) as error:
        print(str(error),file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

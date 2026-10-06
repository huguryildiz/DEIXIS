"""Model-free A/B/C/N experiment; transport injection or offline replay only, no network client."""
from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from httpx import TimeoutException

try:
    from .common import canonical, doi, identity, load_benchmark, matching_records, sanitize, sha
except ImportError:
    from common import canonical, doi, identity, load_benchmark, matching_records, sanitize, sha

PROVIDERS = ('openalex', 'semantic_scholar')
B_REQUEST_LIMIT = 10
TOTAL_REQUEST_LIMIT = 20
GENRE = re.compile(r'\b(survey|review|tutorial)\b', re.I)
TERMS = {
    'dbr_vbf': ('underwater acoustic', 'routing'),
    'kurt2017': ('wireless sensor', 'packet size'),
    'uwsn_kconn2022': ('sensor networks', 'k-connectivity'),
    'irs2021': ('intelligent reflecting surface', 'reconfigurable intelligent surface'),
}


@dataclass
class Response:
    """One HTTP send only. Transport must disable hidden retries, paging, resolution and fallback."""
    status_code: int
    body: bytes


def queries(name, provider):
    terms = TERMS[name]
    if provider == 'openalex':
        return [f'("{terms[0]}" OR "{terms[1]}") AND (survey OR review OR tutorial)']
    # Semantic Scholar accepts plain text rather than OpenAlex's Boolean syntax.
    return [f'{term} {genre}' for term in terms for genre in ('survey', 'review', 'tutorial')]


def normalize_record(row, provider):
    if not isinstance(row, dict):
        return None
    if provider == 'semantic_scholar':
        row = row.get('citedPaper') or row.get('citingPaper') or row
    result = dict(row)
    if provider == 'openalex':
        result['openalex_id'] = row.get('openalex_id') or row.get('id')
        if not row.get('abstract') and isinstance(row.get('abstract_inverted_index'), dict):
            words = sorted((pos, word) for word, positions in row['abstract_inverted_index'].items()
                           for pos in positions)
            result['abstract'] = ' '.join(word for _, word in words)
    else:
        result['semantic_scholar_id'] = row.get('semantic_scholar_id') or row.get('paperId')
        result['doi'] = row.get('doi') or (row.get('externalIds') or {}).get('DOI')
    return result


class Arm:
    def __init__(self, name, pool, send, output, requests=20):
        if not isinstance(requests,int) or not 0<=requests<=20:
            raise ValueError('request limit must be between zero and twenty')
        self.name, self.send, self.output = name, send, output
        self.request_limit = requests
        self.records = copy.deepcopy(pool)
        self.seen = {identity(r) for r in pool if identity(r)}
        self.aliases = {}
        for row in pool:
            key = identity(row)
            if key:
                for alias in self.identity_keys(row):
                    self.aliases[alias] = key
        self.base = set(self.seen)
        self.log = []
        self.new = 0
        self.overflow = 0
        self.links = []
        self.stopped = False

    @staticmethod
    def identity_keys(row):
        keys = []
        if row.get('doi'):
            keys.append('doi:' + doi(row['doi']))
        for provider in PROVIDERS:
            if row.get(provider+'_id'):
                keys.append(provider+':'+row[provider+'_id'])
        if row.get('verified_work_id'):
            keys.append('work:'+row['verified_work_id'])
        return keys

    def normalized(self, raw, provider):
        row = normalize_record(raw,provider)
        if row:
            aliases = {self.aliases[a] for a in self.identity_keys(row) if a in self.aliases}
            if len(aliases)>1:
                return None  # conflicting identities require adjudication, not silent merging
            if aliases:
                row['_measurement_identity'] = aliases.pop()
        return row

    @staticmethod
    def key(row):
        return row.get('_measurement_identity') or identity(row) if row else None

    def room(self):
        return len(self.log) < self.request_limit and self.new < 100

    def call(self, provider, operation, *, seed=None, query=None, ids=None, offset=0, limit=100):
        request = {'provider': provider, 'endpoint': operation, 'seed': seed,
                   'query': query, 'ids': ids, 'offset': offset, 'limit': limit}
        if not self.room():
            self.stopped = True
            self.links.append(request | {'operation_status': 'not_attempted', 'reason': 'budget_exhausted'})
            return None
        started = datetime.now(timezone.utc).isoformat()
        try:
            response = self.send(copy.deepcopy(request))
            status = {429:'rate_limited', 401:'unauthorized', 403:'unauthorized', 404:'not_found'}.get(
                response.status_code, 'ok' if 200 <= response.status_code < 300 else 'provider_error')
            try:
                payload = json.loads(response.body)
            except (ValueError, UnicodeDecodeError):
                payload = None
                if status == 'ok':
                    status = 'invalid_payload'
            # Invalid bodies are not persisted verbatim because they can echo request credentials.
            retained = canonical(sanitize(payload)) if payload is not None else '[invalid body omitted]'
            http_status = response.status_code
        except (TimeoutError, TimeoutException):
            status, payload, retained, http_status = 'timeout', None, '', None
        except Exception:
            status, payload, retained, http_status = 'provider_error', None, '', None
        digest = sha(retained)
        path = self.output / 'raw' / f'{digest}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(retained)
        entry = sanitize(request) | {'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'http_status': http_status, 'request_status': status, 'body_sha256': digest,
            'body_path': str(path.relative_to(self.output)), 'body_is_sanitized': True,
            'mode': 'injected_transport', 'operation_status': 'completed' if status == 'ok' else 'failed',
            'returned_count': None, 'total': None, 'next_offset': None, 'truncated': False,
            'first_page_only': provider == 'semantic_scholar' and operation == 'references',
            'bibliography_status': 'references_unavailable'}
        self.log.append(entry)
        if status != 'ok':
            return entry, None
        if not isinstance(payload, dict):
            entry.update(request_status='invalid_payload', operation_status='failed')
            return entry, None
        records = payload.get('records', payload.get('results', payload.get('data')))
        if operation == 'references' and records is None and 'referenced_works' in payload:
            records = payload['referenced_works']
        if not isinstance(records, list):
            entry.update(request_status='invalid_payload', operation_status='failed')
            return entry, None
        if any(not isinstance(r, (dict, str)) for r in records):
            entry.update(request_status='invalid_payload', operation_status='failed')
            return entry, None
        total = payload.get('total', (payload.get('meta') or {}).get('count'))
        next_offset = payload.get('next')
        if next_offset is None:
            next_offset = payload.get('next_offset')
        entry.update(returned_count=len(records), total=total, next_offset=next_offset)
        entry['bibliography_status'] = ('empty_returned' if not records else
            'first_page_only' if entry['first_page_only'] else 'references_present')
        entry['truncated'] = next_offset is not None or (isinstance(total, int) and total > len(records))
        if entry['truncated'] and not entry['first_page_only']:
            entry['bibliography_status'] = 'pagination_truncated'
        return entry, records

    def fetch(self, provider, operation, **kwargs):
        """Retry only a recorded 429, at most twice; every attempt spends the same budget."""
        first = len(self.log)
        for attempt in range(3):
            result = self.call(provider, operation, **kwargs)
            if result is None:
                return []
            entry, rows = result
            entry['retry_index'] = attempt
            if entry['request_status'] != 'rate_limited':
                if entry['request_status']=='ok':
                    for prior in self.log[first:-1]:
                        prior['recovered_by_retry'] = True
                return rows or []
        return []

    def add(self, rows, provider, origin):
        origin = origin | {'send_index':len(self.log)}
        for raw in rows:
            row = self.normalized(raw, provider)
            key = self.key(row)
            if not key:
                self.links.append(sanitize(origin) | {'identity_status':'unresolved_identity', 'record':sanitize(raw)})
                continue
            state = 'resolved'
            if key in self.seen:
                # A different DOI counts as a version alias only after identity resolution.
                existing = [r for r in self.records if self.key(r) == key]
                same_doi = any(doi(r.get('doi')) == doi(row.get('doi')) for r in existing if r.get('doi'))
                different_doi = bool(row.get('doi') and any(r.get('doi') for r in existing) and not same_doi)
                state = 'version_alias' if different_doi else 'duplicate'
            if key not in self.seen:
                if self.new >= 100:
                    self.overflow += 1
                    self.stopped = True
                    state = 'capacity_overflow'
                else:
                    self.seen.add(key)
                    self.new += 1
                    self.records.append(sanitize(row) | {'origin':sanitize(origin)})
            if key in self.seen:
                for alias in self.identity_keys(row):
                    self.aliases[alias] = key
            self.links.append(sanitize(origin) | {'identity':key, 'identity_status':state,
                'version':row.get('version_label'), 'record':sanitize(row)})

    def expand(self, seeds, directions=('references',)):
        for seed in seeds:
            for provider in PROVIDERS:
                seed_id = seed.get(provider + '_id') or seed.get('doi')
                if not seed_id:
                    self.links.append({'seed':identity(seed), 'provider':provider,
                                       'identity_status':'unresolved_identity', 'operation_status':'not_attempted'})
                    continue
                for direction in directions:
                    origin = {'seed':identity(seed), 'provider':provider, 'direction':direction}
                    before = len(self.log)
                    rows = self.fetch(provider, direction, seed=seed_id)
                    page_entry = self.log[-1] if len(self.log) > before else None
                    # OpenAlex returns referenced work IDs: resolving them is additional HTTP traffic.
                    ids = [r for r in rows if isinstance(r, str)]
                    self.add([r for r in rows if isinstance(r, dict)], provider, origin)
                    for i in range(0, len(ids), 50):
                        resolved = self.fetch(provider, 'resolve', ids=ids[i:i+50], limit=50)
                        self.add(resolved, provider, origin | {'resolution_ids':ids[i:i+50]})
                    # S2 references deliberately stop after page one; other offset pages spend the budget.
                    entry = page_entry
                    seen_offsets = {0}
                    while (entry and entry['next_offset'] is not None and
                           not (provider == 'semantic_scholar' and direction == 'references')):
                        offset = entry['next_offset']
                        if not isinstance(offset, int) or offset in seen_offsets or not self.room():
                            entry.update(truncated=True, bibliography_status='pagination_truncated')
                            if not self.room():
                                self.stopped = True
                            break
                        seen_offsets.add(offset)
                        before = len(self.log)
                        page = self.fetch(provider, direction, seed=seed_id, offset=offset)
                        self.add(page, provider, origin | {'offset':offset})
                        entry = self.log[-1] if len(self.log) > before else None

    def report(self):
        return {'arm':self.name, 'records':self.records, 'new_unique_works':self.new,
                'provider_sends':len(self.log), 'model_calls':0, 'requests':self.log, 'links':self.links,
                'overflow':self.overflow, 'operation_status': 'budget_exhausted' if self.stopped else
                'failed' if any(r['request_status'] != 'ok' and not r.get('recovered_by_retry') for r in self.log) else 'completed'}


def unique_resolvable(pool):
    seen, rows = set(), []
    for row in pool:
        key = identity(row)
        if key and key not in seen:
            seen.add(key)
            rows.append(row)
    return rows


def run(pool, name, send: Callable, output: Path, *, mode='offline_replay'):
    """Frozen pool format: {format, question_sha256, records}; records retain A origins and order."""
    if pool.get('format') != 'frozen-search-pool-v1' or not pool.get('question_sha256'):
        raise ValueError('explicit frozen A pool and question hash required')
    bench_path = Path(__file__).with_name(name+'.json')
    if pool['question_sha256'] != load_benchmark(bench_path)['question_sha256']:
        raise ValueError('frozen A question hash does not match set')
    if mode not in {'offline_replay', 'network_measurement'}:
        raise ValueError('unknown transport mode')
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be empty')
    output.mkdir(parents=True, exist_ok=True)
    base = sanitize(pool['records'])
    seeds = unique_resolvable(base)
    b_seeds = [s for s in seeds if GENRE.search(s.get('title') or '')][:8]
    b = Arm('B', base, send, output, requests=B_REQUEST_LIMIT)
    b.expand(b_seeds)
    c = Arm('C', base, send, output, requests=TOTAL_REQUEST_LIMIT)
    c.records, c.seen, c.new = copy.deepcopy(b.records), set(b.seen), b.new
    c.aliases = dict(b.aliases)
    c.log, c.links, c.overflow = copy.deepcopy(b.log), copy.deepcopy(b.links), b.overflow
    for entry in c.log:
        entry['operation_status'] = 'cache_replay'
        entry['inherited_from'] = 'B'
    new_surveys, used = [], set(c.base)
    for provider in PROVIDERS:
        for query in queries(name, provider):
            rows = c.fetch(provider, 'search', query=query)
            c.add(rows, provider, {'provider':provider, 'query':query, 'direction':'survey_search'})
            for raw in rows:
                record = c.normalized(raw, provider)
                key = c.key(record)
                if key and key in c.seen and key not in used and GENRE.search(record.get('title') or ''):
                    used.add(key)
                    if len(new_surveys) < 8:
                        new_surveys.append(record)
    c.expand(new_surveys)
    n = Arm('N', base, send, output, requests=TOTAL_REQUEST_LIMIT)
    n.expand(seeds[:8], ('references', 'citations'))
    arms = {'A': {'arm':'A', 'records':base, 'provider_sends':0, 'new_unique_works':0,
                  'model_calls':0, 'operation_status':'cache_replay'},
            'B':b.report(), 'C':c.report(), 'N':n.report()}
    for arm in ('B','C','N'):
        for entry in arms[arm]['requests']:
            entry['mode'] = mode
    n_at = {}
    for comparator in ('B','C'):
        count = arms[comparator]['provider_sends']
        n_at[comparator] = {'requested_sends':count, 'observed_sends':min(count,len(n.log)),
            'new_identities':sorted({link['identity'] for link in n.links if link.get('identity') and
                link.get('identity_status') in {'resolved','duplicate','version_alias'} and
                link.get('send_index',count+1)<=count} - n.base)}
    result = {'format':'survey-measurement-v1', 'set':name, 'mode':mode,
        'A_sha256':sha(canonical(pool)), 'question_sha256':pool['question_sha256'],
        'filter_rule':'retain all resolved links; title/abstract relevance assessed separately, no model filter',
        'seed_rule':'title survey/review/tutorial in frozen order; normal top eight resolvable works',
        'allocation':{'B':B_REQUEST_LIMIT, 'C_including_B':TOTAL_REQUEST_LIMIT,
            'C_remaining_after_B':TOTAL_REQUEST_LIMIT-len(b.log), 'B_used':len(b.log),
            'N':TOTAL_REQUEST_LIMIT, 'new_unique_limit':100},
        'cost_basis':'additional sends after A; offline replay counts request positions, not new network sends',
        'query_rules':{provider:queries(name,provider) for provider in PROVIDERS},
        'B_seeds':[identity(s) for s in b_seeds], 'C_seeds':[identity(s) for s in new_surveys],
        'N_seeds':[identity(s) for s in seeds[:8]], 'arms':arms, 'N_at_equal_sends':n_at}
    (output / 'report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def score_targets(report, bench):
    """Targets are used after all requests and seed selection, never supplied to the planner."""
    if report['question_sha256'] != bench['question_sha256']:
        raise ValueError('question hash mismatch')
    relevant = [p for p in bench['papers'] if p['label']=='ilgili']
    def covered(result, sends=None):
        if sends is None:
            counted_records = result['records']
        else:
            counted_records = report['arms']['A']['records']
        counted_records = counted_records + [l['record'] for l in result.get('links',[]) if l.get('record') and
            l.get('identity_status') in {'resolved','duplicate','version_alias'} and
            (sends is None or l.get('send_index', sends+1)<=sends)]
        found = [p for p in relevant if matching_records(counted_records, p)]
        return {'denominator':len(relevant), 'found':[p['key'] for p in found],
            'keys':[p['key'] for p in found if p['anchor']],
            'by_stratum':{layer:{'denominator':sum(p['stratum']==layer for p in relevant),
                'found':[p['key'] for p in found if p['stratum']==layer]} for layer in
                sorted({p['stratum'] for p in bench['papers']})},
            'identity_unresolved_targets':[p['key'] for p in relevant
                if not p.get('doi') and not p.get('verified_work_ids')]}
    coverage = {arm:covered(result) for arm,result in report['arms'].items()}
    gains = {name:sorted(set(coverage[left]['found'])-set(coverage[right]['found']))
             for name,left,right in [('B-A','B','A'),('C-A','C','A'),('C-B','C','B'),('N-A','N','A')]}
    comparisons = {}
    for arm in ('B','C'):
        requested = report['arms'][arm]['provider_sends']
        available = report['arms']['N']['provider_sends']
        equal = min(requested, available)
        left, right = covered(report['arms'][arm],equal), covered(report['arms']['N'],equal)
        net_gain = len(left['found'])-len(right['found'])
        no_fewer_keys = len(left['keys'])>=len(right['keys'])
        gains[arm+'-N'] = sorted(set(left['found'])-set(right['found']))
        comparisons[arm+'-N'] = {'requested_sends':requested, 'equal_sends':equal,
            'budget_matched':available>=requested, 'coverage':{arm:left, 'N':right},
            'net_target_gain':net_gain, 'no_fewer_keys':no_fewer_keys,
            'lost_targets':sorted(set(right['found'])-set(left['found'])),
            'lost_keys':sorted(set(right['keys'])-set(left['keys'])),
            'preference_rule_met':(net_gain>=1 and no_fewer_keys) if available>=requested else None}
    return {'coverage':coverage, 'incremental_targets':gains, 'equal_send_comparisons':comparisons,
            'preference_scope':'single frozen question; aggregate gain and every-question key rule require all sets',
            'limitation':'Known-target coverage only; title matches and unverified DOI aliases never count.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', required=True, type=Path)
    parser.add_argument('--set', required=True, choices=TERMS)
    parser.add_argument('--responses', required=True, type=Path,
                        help='offline [{request: {...}, status_code: 200, body: {...}}]; one entry per send')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    replies = iter(json.loads(args.responses.read_text()))
    def replay(request):
        reply = next(replies)
        if reply['request'] != request:
            raise ValueError('replay request mismatch')
        if reply.get('timeout'):
            raise TimeoutError
        return Response(reply['status_code'], canonical(reply['body']).encode())
    report = run(json.loads(args.pool.read_text()), args.set, replay, args.output)
    scored = score_targets(report,load_benchmark(Path(__file__).with_name(args.set+'.json')))
    (args.output/'target-score.json').write_text(json.dumps(scored,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()

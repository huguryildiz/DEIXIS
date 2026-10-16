"""Network side of the BioASQ benchmark: sample, gold metadata, system runs, scoring.

    uv run python scripts/benchmark/bioasq_run.py prepare --n 100
    uv run python scripts/benchmark/bioasq_run.py score

Outputs live in .local/bioasq/ (ignored); each system writes one JSON line per question to runs/<system>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import httpx

try:
    from . import bioasq
except ImportError:
    import bioasq

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / '.local/bioasq'
SEED = 20261017
ESUMMARY = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def gold_metadata(pmids):
    """PubMed esummary DOI, title and year per PMID, so DOI and title matching have something to match against."""
    meta = {}
    with httpx.Client(timeout=60) as client:
        for start in range(0, len(pmids), 200):
            chunk = pmids[start:start + 200]
            body = client.post(ESUMMARY, data={'db': 'pubmed', 'id': ','.join(chunk), 'retmode': 'json'})
            body.raise_for_status()
            result = body.json()['result']
            for pmid in chunk:
                item = result.get(pmid) or {}
                doi = next((a['value'] for a in item.get('articleids', []) if a.get('idtype') == 'doi'), None)
                year = (item.get('pubdate') or '')[:4]
                meta[pmid] = {'doi': doi, 'title': item.get('title'), 'year': int(year) if year.isdigit() else None}
            time.sleep(0.4)  # keyless NCBI allows three requests a second
    return meta


def prepare(args):
    questions = bioasq.sample(bioasq.load(HOME / 'raw'), args.n, SEED)
    pmids = sorted({p for q in questions for p in q['gold']})
    known = json.loads((HOME / 'gold_meta.json').read_text()) if (HOME / 'gold_meta.json').exists() else {}
    known.update(gold_metadata([p for p in pmids if p not in known]))
    (HOME / 'gold_meta.json').write_text(json.dumps(known, indent=1))
    (HOME / 'sample.json').write_text(json.dumps({'seed': SEED, 'n': args.n, 'questions': questions}, indent=1))
    print(f'{len(questions)} questions, {len(pmids)} gold PMIDs, '
          f'{sum(1 for p in pmids if known[p].get("doi"))} with DOI')


MODEL, EFFORT = 'claude-sonnet-5-5', 'medium'
OPENALEX = 'https://api.openalex.org/works'
QUERY_PROMPT = """Write one keyword query for the OpenAlex works `search` parameter that finds papers answering this \
biomedical question. OpenAlex search accepts AND, OR, NOT, double-quoted phrases and parentheses; no wildcards or \
field tags. Reply with the query only.

Question: {question}"""


def secret(name):
    import keyring
    return keyring.get_password('DEIXIS', name)


def done_ids(path):
    return {r['id'] for r in read_jsonl(path) if not r.get('error')}


def write_query(client, question, raw=False):
    body = {'model': MODEL, 'max_tokens': 2000, 'output_config': {'effort': EFFORT},
            'messages': [{'role': 'user', 'content': question if raw else QUERY_PROMPT.format(question=question)}]}
    reply = client.post('https://api.anthropic.com/v1/messages', json=body, timeout=120,
                        headers={'x-api-key': secret('ANTHROPIC_API_KEY'), 'anthropic-version': '2023-06-01'})
    reply.raise_for_status()
    return ' '.join(b['text'] for b in reply.json()['content'] if b['type'] == 'text').strip().strip('`').strip()


def openalex_records(client, query, year, limit=200):
    """OpenAlex keyword search with the API-side date cut Elicit used, read by cursor up to `limit` works."""
    records, cursor = [], '*'
    while cursor and len(records) < limit:
        params = {'search': query, 'filter': f'to_publication_date:{year}-12-31', 'per_page': 100, 'cursor': cursor,
                  'select': 'id,ids,doi,display_name,publication_year'}
        reply = client.get(OPENALEX, params=params, timeout=60,
                           headers={'Authorization': f'Bearer {secret("OPENALEX_API_KEY")}'})
        reply.raise_for_status()
        page = reply.json()
        records += [{'pmid': bioasq.pmid_of((w.get('ids') or {}).get('pmid')), 'doi': w.get('doi'),
                     'title': w.get('display_name'), 'year': w.get('publication_year')} for w in page['results']]
        cursor = page['meta'].get('next_cursor') if page['results'] else None
    return records[:limit]


def run_openalex(args):
    out = HOME / 'runs/openalex.jsonl'
    out.parent.mkdir(exist_ok=True)
    skip = done_ids(out)
    questions = json.loads((HOME / 'sample.json').read_text())['questions'][:args.limit]
    with httpx.Client() as client:
        for q in questions:
            if q['id'] in skip:
                continue
            row = {'id': q['id']}
            try:
                row['query'] = write_query(client, q['body'])
                row['records'] = openalex_records(client, row['query'], q['year'])
            except Exception as exc:  # recorded and scored as a failure, never retried silently
                row['error'] = f'{type(exc).__name__}: {exc}'[:500]
            with out.open('a') as f:
                f.write(json.dumps(row) + '\n')
            print(q['id'], row.get('error') or f"{len(row['records'])} records")


REPAIR_PROMPT = """OpenAlex rejected this search query. Fix only what makes it invalid (no wildcards, no prose, \
balanced quotes and parentheses; AND, OR, NOT, quoted phrases and parentheses are allowed) and keep everything else. \
Reply with the query only.

Question: {question}
Rejected query: {query}
Error: {error}"""


def repair_openalex(args):
    """Elicit's repair step: one model fix per rejected query, then one retry; the row records that it was repaired."""
    out = HOME / 'runs/openalex.jsonl'
    rows = {r['id']: r for r in read_jsonl(out)}
    questions = {q['id']: q for q in json.loads((HOME / 'sample.json').read_text())['questions']}
    with httpx.Client() as client:
        for qid, old in rows.items():
            if not (old.get('error') and old.get('query')):
                continue
            row = {'id': qid, 'rejected_query': old['query']}
            try:
                prompt = REPAIR_PROMPT.format(question=questions[qid]['body'], query=old['query'], error=old['error'][:200])
                row['query'] = write_query(client, prompt, raw=True)
                row['records'] = openalex_records(client, row['query'], questions[qid]['year'])
            except Exception as exc:
                row['error'] = f'{type(exc).__name__}: {exc}'[:500]
            with out.open('a') as f:
                f.write(json.dumps(row) + '\n')
            print(qid, row.get('error') or f"repaired, {len(row['records'])} records")


class Deixis:
    """An isolated DEIXIS server (never port 8765) and read-only access to its library."""

    def __init__(self, base, data_dir):
        if base.rstrip('/').endswith(':8765'):
            raise SystemExit('refusing port 8765: it may be the owner\'s library')
        self.base, self.data_dir = base.rstrip('/'), Path(data_dir)
        self.http = httpx.Client(base_url=self.base, timeout=60)
        token = self.http.get('/api/session').json()['csrf_token']
        self.http.headers['x-deixis-csrf'] = token

    def post(self, path, body):
        reply = self.http.post(path, json=body)
        reply.raise_for_status()
        return reply.json()

    def db(self):
        conn = sqlite3.connect((self.data_dir / 'library.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def wait_list(self, run_id, timeout):
        """The frozen small-batch list's order, or the run's stopping state if it ends or pauses first."""
        start = time.time()
        while time.time() - start < timeout:
            with closing(self.db()) as conn:
                step = conn.execute("SELECT status, output_json FROM run_steps WHERE run_id=? AND "
                                    "operation_key='small_batch:v1:list'", (run_id,)).fetchone()
                run = conn.execute('SELECT status, pause_reason, stage FROM runs WHERE id=?', (run_id,)).fetchone()
            if step and step['status'] == 'succeeded':
                return json.loads(step['output_json'])['order'], None
            if run['status'] in ('paused', 'failed', 'cancelled', 'completed'):
                return None, f"run {run['status']} at {run['stage']}: {run['pause_reason']}"
            time.sleep(2)
        return None, 'timeout'

    def records(self, order):
        with closing(self.db()) as conn:
            rows = []
            for svid in order:
                v = conn.execute('SELECT title, year, doi, provider_payload_path FROM source_versions WHERE id=?',
                                 (svid,)).fetchone()
                work = conn.execute("SELECT value FROM identifier_mappings WHERE source_version_id=? AND "
                                    "scheme='openalex'", (svid,)).fetchone()
                rows.append({'svid': svid, 'title': v['title'], 'year': v['year'], 'doi': v['doi'],
                             'pmid': self.pmid(v['provider_payload_path'], work[0] if work else None)})
        return rows

    def pmid(self, path, work):
        """OpenAlex's ids.pmid from the stored raw payload; the library itself keeps no PMID mapping."""
        if not (path and work):
            return None
        try:
            payload = json.loads((self.data_dir / 'provider-payloads' / path).read_text())
        except (OSError, ValueError):
            return None
        for item in payload.get('results', []):
            if str(item.get('id', '')).endswith(work):
                return bioasq.pmid_of((item.get('ids') or {}).get('pmid'))
        return None


def run_deixis(args):
    out = HOME / 'runs/deixis.jsonl'
    out.parent.mkdir(exist_ok=True)
    skip = done_ids(out)
    server = Deixis(args.base, args.data_dir)
    questions = json.loads((HOME / 'sample.json').read_text())['questions'][:args.limit]
    for q in questions:
        if q['id'] in skip:
            continue
        row, start = {'id': q['id']}, time.time()
        try:
            research = server.post('/api/researches', {
                'question': q['body'], 'effort': 'standard', 'model_connection': 'anthropic',
                'requested_model': MODEL, 'reasoning_effort': EFFORT, 'review_mode': 'off'})['research']
            run = server.post(f"/api/researches/{research['id']}/runs", {'kind': 'discovery'})
            row |= {'research_id': research['id'], 'run_id': run['id']}
            order, row['error'] = server.wait_list(run['id'], args.timeout)
            server.http.post(f"/api/runs/{run['id']}/cancel")  # the list is frozen; reading PDFs is not measured
            if order is not None:
                row['pool'] = len(order)
                row['records'] = server.records(order[:args.keep])
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'[:500]
        if not row.get('error'):
            row.pop('error', None)
        row['seconds'] = round(time.time() - start, 1)
        with out.open('a') as f:
            f.write(json.dumps(row) + '\n')
        print(q['id'], row.get('error') or f"pool {row['pool']}, {row['seconds']} s")


def score(args):
    questions = json.loads((HOME / 'sample.json').read_text())['questions']
    meta = json.loads((HOME / 'gold_meta.json').read_text())
    systems = {}
    for path in sorted((HOME / 'runs').glob('*.jsonl')):
        rows = {r['id']: r for r in read_jsonl(path)}
        per = {}
        for q in questions:
            row = rows.get(q['id'])
            if row is None:
                continue
            if row.get('error'):
                per[q['id']] = None
                continue
            records = [r for r in row['records'] if bioasq.in_time(r, q['year'])]
            per[q['id']] = bioasq.recall(q, records, meta)
        systems[path.stem] = per
    report = {}
    for name, per in systems.items():
        report[name] = {'questions': len(per), 'failed': sum(v is None for v in per.values()),
                        **{f'@{k}': bioasq.macro(per, k) for k in bioasq.DEPTHS}}
        print(name, json.dumps(report[name]))
    if 'deixis' in systems and 'openalex' in systems:
        report['deixis_minus_openalex'] = {f'@{k}': bioasq.paired_bootstrap(systems['deixis'], systems['openalex'], k)
                                           for k in bioasq.DEPTHS}
        print('deixis − openalex', json.dumps(report['deixis_minus_openalex']))
    (HOME / 'report.json').write_text(json.dumps(report, indent=1))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--n', type=int, default=100)
    p.set_defaults(fn=prepare)
    o = sub.add_parser('openalex')
    o.add_argument('--limit', type=int, default=None)
    o.set_defaults(fn=run_openalex)
    sub.add_parser('openalex-repair').set_defaults(fn=repair_openalex)
    d = sub.add_parser('deixis')
    d.add_argument('--base', required=True)
    d.add_argument('--data-dir', required=True)
    d.add_argument('--limit', type=int, default=None)
    d.add_argument('--keep', type=int, default=400, help='list positions kept before the time filter')
    d.add_argument('--timeout', type=int, default=900)
    d.set_defaults(fn=run_deixis)
    sub.add_parser('score').set_defaults(fn=score)
    args = parser.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()

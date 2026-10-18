"""Network side of the BioASQ benchmark: sample, gold metadata, system runs, scoring.

    uv run python scripts/benchmark/bioasq_run.py prepare --n 100
    uv run python scripts/benchmark/bioasq_run.py preflight --base http://127.0.0.1:8766 --data-dir .local/bioasq/data
    uv run python scripts/benchmark/bioasq_run.py deixis --base http://127.0.0.1:8766 --data-dir .local/bioasq/data
    uv run python scripts/benchmark/bioasq_run.py score

Outputs live in .local/bioasq/ (ignored); each system writes one JSON line per question to runs/<system>.jsonl.
DEIXIS writes two systems from one run, deixis_fused (reranker off) and deixis_rerank (reranker on), with the settings
and stop rule of harness.py; runs/deixis.jsonl is the 17 Oct run (Gemini embedding, reranker off).
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
    from . import bioasq, harness
except ImportError:
    import bioasq
    import harness

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
    """Every question written, failures included: a failure is scored as zero, and running it again until it
    succeeds would replace that zero with a success. A stop (budget) writes no row, so it is run later."""
    return {r['id'] for r in read_jsonl(path)}


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
            if not (old.get('error') and old.get('query')) or old.get('rejected_query'):  # one repair per question
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
        self.base, self.data_dir, self.payloads = base, Path(data_dir), {}
        if base is None:  # library reads only
            return
        if base.rstrip('/').endswith(':8765'):
            raise SystemExit('refusing port 8765: it may be the owner\'s library')
        self.base, self.data_dir, self.payloads = base.rstrip('/'), Path(data_dir), {}
        self.http = httpx.Client(base_url=self.base, timeout=60)
        token = self.http.get('/api/session').json()['csrf_token']
        self.http.headers['x-deixis-csrf'] = token

    def post(self, path, body):
        reply = self.http.post(path, json=body)
        reply.raise_for_status()
        return reply.json()

    def put(self, path, body):
        reply = self.http.put(path, json=body)
        reply.raise_for_status()
        return reply.json()

    def get(self, path):
        reply = self.http.get(path)
        reply.raise_for_status()
        return reply.json()

    def db(self):
        conn = sqlite3.connect((self.data_dir / 'library.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def records(self, order):
        with closing(self.db()) as conn:
            marks = ','.join('?' * len(order))
            versions = {r['id']: r for r in conn.execute(
                f'SELECT id, title, year, doi, provider_payload_path FROM source_versions WHERE id IN ({marks})', order)}
            works = dict(conn.execute(f"SELECT source_version_id, value FROM identifier_mappings WHERE scheme='openalex' "
                                      f"AND source_version_id IN ({marks})", order).fetchall())
        return [{'svid': svid, 'title': versions[svid]['title'], 'year': versions[svid]['year'],
                 'doi': versions[svid]['doi'], 'pmid': self.pmid(versions[svid]['provider_payload_path'], works.get(svid))}
                for svid in order]

    def pmid(self, path, work):
        """OpenAlex's ids.pmid from the stored raw payload; the library itself keeps no PMID mapping."""
        if not (path and work):
            return None
        if path not in self.payloads:
            try:
                payload = json.loads((self.data_dir / 'provider-payloads' / path).read_text())
            except (OSError, ValueError):
                payload = {}
            self.payloads[path] = {str(item.get('id', '')).rsplit('/', 1)[-1]:
                                   bioasq.pmid_of((item.get('ids') or {}).get('pmid'))
                                   for item in payload.get('results', [])}
        return self.payloads[path].get(work.rsplit('/', 1)[-1])


def ask_deixis(server, question):
    """Start one discovery run as a user would; returns (research id, run id)."""
    research = server.post('/api/researches', {
        'question': question, 'effort': harness.DEPTH, 'model_connection': 'anthropic',
        'requested_model': MODEL, 'reasoning_effort': EFFORT, 'review_mode': 'off'})['research']
    run = server.post(f"/api/researches/{research['id']}/runs", {'kind': 'discovery'})
    return research['id'], run['id']


def measured_run(args, home, questions, server, records):
    """Arms B and C for each question from one DEIXIS run with the plan's settings (harness module docstring).

    `records(order, research_id)` turns list positions into scored rows. A product failure (the run failed) is a row
    scored as zero; a pause, a timeout, a wrong embedding or a rerank that did not apply stops the whole run."""
    settings = harness.stamp(harness.configure(server), MODEL, EFFORT) | {'keep': args.keep}  # positions kept per row
    outs = {arm: home / f'runs/deixis_{arm}.jsonl' for arm in harness.ARMS}
    outs['fused'].parent.mkdir(exist_ok=True)
    skip = harness.done_in_all(list(outs.values()), read_jsonl)
    todo = [q for q in questions if q['id'] not in skip]
    print(f"{len(skip)} done, {len(todo)} to run; settings {json.dumps(settings)}")
    with httpx.Client() as client:
        for q in todo:
            if why := harness.budget_stop(client, secret('OPENALEX_API_KEY'), args.prepaid_floor):
                raise harness.Stop(f'{why}; {len(skip)} of {len(questions)} questions done')
            row, start = {'id': q['id']}, time.time()
            try:
                # A run that stopped this benchmark on the model's query is taken up again, not asked anew.
                paused, allowed, note = harness.paused_on_query(home, q['id'], read_jsonl, server)
                if note:
                    row['note'] = note
                if paused:
                    row['research_id'], row['run_id'] = paused
                else:
                    row['research_id'], row['run_id'] = ask_deixis(server, q['body'])
                listing, state, row['query_resumes'] = harness.wait_with_query_retry(
                    server, row['run_id'], args.timeout, allowed)
                server.http.post(f"/api/runs/{row['run_id']}/cancel")  # the list is frozen; reading is not measured
            except Exception as exc:
                harness.stopped(home, row, f'{type(exc).__name__}: {exc}'[:300], len(skip), len(questions))
            row['seconds'] = round(time.time() - start, 1)
            if listing is None and state['status'] != 'failed':
                harness.stopped(home, row | {'state': state}, f"run {state['status']}: {state.get('reason')}",
                                len(skip), len(questions))
            rows = {}
            if listing is None:
                with closing(server.db()) as conn:
                    if found := harness.failed_run_problems(conn, row['run_id']):
                        harness.stopped(home, row | {'state': state}, '; '.join(found), len(skip), len(questions))
                rows = dict.fromkeys(harness.ARMS, row | {'error': f"run failed at {state['stage']}: {state['reason']}"})
            else:
                with closing(server.db()) as conn:
                    if found := harness.problems(conn, row['run_id'], listing):
                        harness.stopped(home, row, '; '.join(found), len(skip), len(questions))
                    rerank = harness.rerank_info(conn, row['run_id'], listing)
                orders = harness.arms(listing)
                by_svid = {r['svid']: r for r in records(orders['rerank'], row['research_id'])}
                for arm, order in orders.items():
                    rows[arm] = row | {'pool': len(order), 'rerank': rerank,
                                       'records': [by_svid[svid] for svid in order[:args.keep]]}
            for arm, out in outs.items():
                with out.open('a') as f:
                    f.write(json.dumps(rows[arm] | {'settings': settings}) + '\n')
            skip.add(q['id'])
            print(q['id'], rows['rerank'].get('error') or f"pool {rows['rerank']['pool']}, {row['seconds']} s")


def run_deixis(args):
    server = Deixis(args.base, args.data_dir)
    questions = json.loads((HOME / 'sample.json').read_text())['questions'][:args.limit]
    try:
        measured_run(args, HOME, questions, server, lambda order, _rid: server.records(order))
    except harness.Stop as exc:
        raise SystemExit(f'stopped: {exc}')


def preflight(args):
    try:
        print(json.dumps(harness.preflight(Deixis(args.base, args.data_dir), secret), indent=1))
    except harness.Stop as exc:
        raise SystemExit(f'preflight failed: {exc}')


def loss(args):
    """Where DEIXIS lost each gold paper: top 200, deeper in the frozen list, cut by the year filter, or never found."""
    questions = json.loads((HOME / 'sample.json').read_text())['questions']
    meta = json.loads((HOME / 'gold_meta.json').read_text())
    rows = {r['id']: r for r in read_jsonl(HOME / 'runs/deixis.jsonl')}
    library = Deixis(None, args.data_dir)
    counts = dict.fromkeys(('top200', 'deeper_in_list', 'after_question_year', 'not_in_list'), 0)
    with closing(library.db()) as conn:
        for q in questions:
            row = rows.get(q['id'])
            if not row or row.get('error'):
                continue
            step = conn.execute("SELECT output_json FROM run_steps WHERE run_id=? AND "
                                "operation_key='small_batch:v1:list'", (row['run_id'],)).fetchone()
            listed = library.records(json.loads(step[0])['order'])
            timed = [r for r in listed if bioasq.in_time(r, q['year'])]
            gold = {p: meta.get(p, {}) for p in q['gold']}
            top, deeper, everything = (bioasq.matched(gold, timed[:200]), bioasq.matched(gold, timed),
                                       bioasq.matched(gold, listed))
            for p in gold:
                key = ('top200' if p in top else 'deeper_in_list' if p in deeper else
                       'after_question_year' if p in everything else 'not_in_list')
                counts[key] += 1
    print(json.dumps(counts))
    (HOME / 'loss.json').write_text(json.dumps(counts, indent=1))


def score(args):
    questions = json.loads((HOME / 'sample.json').read_text())['questions']
    meta = json.loads((HOME / 'gold_meta.json').read_text())
    systems, arms = {}, {}
    for path in sorted((HOME / 'runs').glob('*.jsonl')):
        raw = read_jsonl(path)
        arms[path.stem] = harness.check_arm(path.stem, raw)  # every row, also those a rerun replaced
        rows = {r['id']: r for r in raw}
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
                        'mean_over': 'questions without failure; the paired differences count a failure as 0',
                        **{f'@{k}': bioasq.macro(per, k) for k in bioasq.DEPTHS}, **arms[name]}
        print(name, json.dumps({k: v for k, v in report[name].items() if k != 'settings'}))
    for name, diff in harness.comparisons(systems, bioasq.paired_bootstrap, bioasq.DEPTHS).items():
        report[name] = diff
        print(name, json.dumps(diff))
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
    d.add_argument('--prepaid-floor', type=float, default=None,
                   help='spend prepaid OpenAlex credit, stopping once the balance falls below this many USD')
    d.set_defaults(fn=run_deixis)
    pf = sub.add_parser('preflight')
    pf.add_argument('--base', required=True)
    pf.add_argument('--data-dir', required=True)
    pf.set_defaults(fn=preflight)
    sub.add_parser('score').set_defaults(fn=score)
    lo = sub.add_parser('loss')
    lo.add_argument('--data-dir', required=True)
    lo.set_defaults(fn=loss)
    args = parser.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()

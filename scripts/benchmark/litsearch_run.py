"""Network side of the LitSearch benchmark: sample, gold resolution, system runs, scoring, route breakdown.

    uv run python scripts/benchmark/litsearch_run.py prepare --n 200
    uv run python scripts/benchmark/litsearch_run.py openalex
    uv run python scripts/benchmark/litsearch_run.py preflight --base http://127.0.0.1:8766 --data-dir .local/litsearch/data
    uv run python scripts/benchmark/litsearch_run.py deixis --base http://127.0.0.1:8766 --data-dir .local/litsearch/data
    uv run python scripts/benchmark/litsearch_run.py score

Only the 50 KB `query` table is downloaded (Hugging Face datasets-server JSON, no parquet); the 2.9 GB corpus is not
needed because gold papers are resolved through Semantic Scholar and OpenAlex. Outputs live in .local/litsearch/
(ignored); each system writes one JSON line per question to runs/<system>.jsonl, and a rerun skips finished questions.
DEIXIS writes two systems from one run, deixis_fused (reranker off) and deixis_rerank (reranker on), with the settings
and stop rule of harness.py. An OpenAlex budget or rate-limit reply stops the run and prints how many questions are done.
"""
from __future__ import annotations

import argparse
import json
import time
from contextlib import closing
from pathlib import Path

import httpx

try:
    from . import harness, litsearch
    from .bioasq_run import Deixis, done_ids, measured_run, read_jsonl, secret, write_query
except ImportError:
    import harness
    import litsearch
    from bioasq_run import Deixis, done_ids, measured_run, read_jsonl, secret, write_query

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / '.local/litsearch'
SEED = 20261017
ROWS = 'https://datasets-server.huggingface.co/rows'
S2_BATCH = 'https://api.semanticscholar.org/graph/v1/paper/batch'
OPENALEX = 'https://api.openalex.org/works'
QUERY_PROMPT = """Write one keyword query for the OpenAlex works `search` parameter that finds papers answering this \
computer-science literature request. OpenAlex search accepts AND, OR, NOT, double-quoted phrases and parentheses; no \
wildcards or field tags. Reply with the query only.

Request: {question}"""
REPAIR_PROMPT = """OpenAlex rejected this search query. Fix only what makes it invalid (no wildcards, no prose, \
balanced quotes and parentheses; AND, OR, NOT, quoted phrases and parentheses are allowed) and keep everything else. \
Reply with the query only.

Request: {question}
Rejected query: {query}
Error: {error}"""


class BudgetStop(Exception):
    """OpenAlex said the daily budget or rate limit is spent: stop, never retry around it."""


DAILY = {'remaining_usd': None}  # the last `x-ratelimit-remaining-usd` OpenAlex sent


def daily_spent():
    """True once the free daily dollars read zero: past that, OpenAlex bills the prepaid balance, which we never use."""
    return DAILY['remaining_usd'] is not None and float(DAILY['remaining_usd']) <= 0


def openalex_get(client, params):
    reply = client.get(OPENALEX, params=params, timeout=60,
                       headers={'Authorization': f'Bearer {secret("OPENALEX_API_KEY")}'})
    DAILY['remaining_usd'] = reply.headers.get('x-ratelimit-remaining-usd', DAILY['remaining_usd'])
    if reply.status_code in (402, 429):
        raise BudgetStop(f'OpenAlex {reply.status_code}: {reply.text[:200]}')
    reply.raise_for_status()
    return reply.json()


def download_queries(client):
    rows, offset = [], 0
    while True:
        page = client.get(ROWS, params={'dataset': 'princeton-nlp/LitSearch', 'config': 'query', 'split': 'full',
                                        'offset': offset, 'length': 100}, timeout=60)
        page.raise_for_status()
        body = page.json()
        rows += [r['row'] for r in body['rows']]
        offset += len(body['rows'])
        if not body['rows'] or offset >= body['num_rows_total']:
            return rows


def s2_papers(client, corpus_ids):
    """Title, year and external ids per corpus id; a missing paper maps to None."""
    key = secret('S2_API_KEY')
    out = {}
    for start in range(0, len(corpus_ids), 500):
        chunk = corpus_ids[start:start + 500]
        reply = client.post(S2_BATCH, params={'fields': 'title,year,externalIds'}, timeout=60,
                            json={'ids': [f'CorpusId:{c}' for c in chunk]}, headers={'x-api-key': key} if key else {})
        reply.raise_for_status()
        out.update(zip(chunk, reply.json()))
        time.sleep(1.1)
    return out


WORK_FIELDS = 'id,doi,display_name,publication_year,abstract_inverted_index'


def resolve_gold(client, paper):
    """OpenAlex works for one gold paper: by each DOI, then by exact normalized title. Records how it resolved."""
    meta = {'title': paper.get('title'), 'year': paper.get('year'),
            'dois': litsearch.gold_dois(paper.get('externalIds')), 'openalex': [], 'resolved_by': None}
    works = []
    if meta['dois']:
        works = openalex_get(client, {'filter': 'doi:' + '|'.join(meta['dois']), 'select': WORK_FIELDS,
                                      'per_page': 50})['results']
        meta['resolved_by'] = 'doi' if works else None
    if not works and meta['title']:
        hits = openalex_get(client, {'filter': f"title.search:{meta['title'].replace(',', ' ')}",
                                     'select': WORK_FIELDS, 'per_page': 10})['results']
        works = [w for w in hits if litsearch.norm_title(w.get('display_name')) == litsearch.norm_title(meta['title'])]
        meta['resolved_by'] = 'title' if works else None
    meta['openalex'] = [litsearch.openalex_short(w['id']) for w in works]
    meta['dois'] = list(dict.fromkeys(meta['dois'] + [litsearch.norm_doi(w['doi']) for w in works if w.get('doi')]))
    meta['has_abstract'] = any(w.get('abstract_inverted_index') for w in works)
    return meta


def prepare(args):
    HOME.mkdir(parents=True, exist_ok=True)
    raw = HOME / 'raw/query.json'
    with httpx.Client() as client:
        if not raw.exists():
            raw.parent.mkdir(exist_ok=True)
            raw.write_text(json.dumps(download_queries(client)))
        questions = litsearch.sample(litsearch.load(json.loads(raw.read_text())), args.n, SEED)
        ids = sorted({c for q in questions for c in q['gold']})
        path = HOME / 'gold_meta.json'
        known = json.loads(path.read_text()) if path.exists() else {}
        todo = [c for c in ids if c not in known]
        papers = s2_papers(client, todo) if todo else {}
        try:
            for cid in todo:
                paper = papers.get(cid)
                known[cid] = resolve_gold(client, paper) if paper else {'s2_missing': True, 'openalex': []}
        except BudgetStop as exc:
            print(f'stopped: {exc}; {sum(c in known for c in ids)} of {len(ids)} gold papers resolved, rerun later')
        path.write_text(json.dumps(known, indent=1))
    (HOME / 'sample.json').write_text(json.dumps({'seed': SEED, 'n': args.n, 'questions': questions}, indent=1))
    metas = [known.get(c, {}) for c in ids]
    print(f"{len(questions)} questions, {len(ids)} gold papers: {sum(bool(m.get('openalex')) for m in metas)} in "
          f"OpenAlex ({sum(m.get('resolved_by') == 'title' for m in metas)} by title only), "
          f"{sum(bool(m.get('s2_missing')) for m in metas)} unknown to Semantic Scholar, "
          f"{sum(c not in known for c in ids)} not tried yet")


def openalex_records(client, query, year, limit=200):
    records, cursor = [], '*'
    while cursor and len(records) < limit:
        page = openalex_get(client, {'search': query, 'filter': f'to_publication_date:{year}-12-31', 'per_page': 100,
                                     'cursor': cursor, 'select': 'id,doi,display_name,publication_year'})
        records += [{'openalex': litsearch.openalex_short(w['id']), 'doi': w.get('doi'), 'title': w.get('display_name'),
                     'year': w.get('publication_year')} for w in page['results']]
        cursor = page['meta'].get('next_cursor') if page['results'] else None
    return records[:limit]


def run_openalex(args):
    """Plain OpenAlex: one model-written keyword query; a rejected query gets one model repair and one retry."""
    out = HOME / 'runs/openalex.jsonl'
    out.parent.mkdir(exist_ok=True)
    skip = done_ids(out)
    questions = json.loads((HOME / 'sample.json').read_text())['questions'][:args.limit]
    with httpx.Client() as client:
        for q in questions:
            if q['id'] in skip:
                continue
            if daily_spent():
                print(f'stopped: OpenAlex daily budget spent; {len(done_ids(out))} of {len(questions)} questions done')
                return
            row = {'id': q['id']}
            try:
                row['query'] = write_query(client, QUERY_PROMPT.format(question=q['body']), raw=True)
                try:
                    row['records'] = openalex_records(client, row['query'], q['year'])
                except httpx.HTTPStatusError as exc:
                    row['rejected_query'] = row['query']
                    row['query'] = write_query(client, REPAIR_PROMPT.format(
                        question=q['body'], query=row['query'], error=str(exc)[:200]), raw=True)
                    row['records'] = openalex_records(client, row['query'], q['year'])
            except BudgetStop as exc:
                print(f'stopped: {exc}; {len(done_ids(out))} of {len(questions)} questions done, rerun later')
                return
            except Exception as exc:  # recorded and scored as a failure, never retried silently
                row['error'] = f'{type(exc).__name__}: {exc}'[:500]
            with out.open('a') as f:
                f.write(json.dumps(row) + '\n')
            print(q['id'], row.get('error') or f"{len(row['records'])} records")


class LitDeixis(Deixis):
    def records(self, order, research_id):
        """Every list position with its OpenAlex work, DOI, title and the routes (search or chain) that brought it."""
        with closing(self.db()) as conn:
            routes = {}
            for svid, desc, provider in conn.execute(
                    'SELECT h.source_version_id, s.request_description, s.provider FROM candidate_hits h '
                    'JOIN search_runs s ON s.id = h.search_run_id WHERE h.research_id = ?', (research_id,)):
                kind = 'semantic' if 'search.semantic=' in desc else 'keyword'
                routes.setdefault(svid, set()).add(f'{kind}:{provider}')
            for (svid,) in conn.execute('SELECT source_version_id FROM chain_links WHERE research_id = ? AND '
                                        'passed_filter = 1 AND source_version_id IS NOT NULL', (research_id,)):
                routes.setdefault(svid, set()).add('chain')
            rows = []
            for svid in order:
                v = conn.execute('SELECT title, year, doi FROM source_versions WHERE id=?', (svid,)).fetchone()
                work = conn.execute("SELECT value FROM identifier_mappings WHERE source_version_id=? AND "
                                    "scheme='openalex'", (svid,)).fetchone()
                rows.append({'svid': svid, 'openalex': litsearch.openalex_short(work[0]) if work else None,
                             'title': v['title'], 'year': v['year'], 'doi': v['doi'],
                             'routes': sorted(routes.get(svid, ()))})
        return rows


def run_deixis(args):
    """Arms B and C from one run per question; every list position is kept, since the route breakdown needs the pool."""
    server = LitDeixis(args.base, args.data_dir)
    questions = json.loads((HOME / 'sample.json').read_text())['questions'][:args.limit]
    args.keep = None
    try:
        measured_run(args, HOME, questions, server, server.records)
    except harness.Stop as exc:
        raise SystemExit(f'stopped: {exc}')


def preflight(args):
    try:
        print(json.dumps(harness.preflight(LitDeixis(args.base, args.data_dir), secret), indent=1))
    except harness.Stop as exc:
        raise SystemExit(f'preflight failed: {exc}')


def score(args):
    questions = json.loads((HOME / 'sample.json').read_text())['questions']
    meta = json.loads((HOME / 'gold_meta.json').read_text())
    systems, rows_by, arms = {}, {}, {}
    for path in sorted((HOME / 'runs').glob('*.jsonl')):
        raw = read_jsonl(path)
        arms[path.stem] = harness.check_arm(path.stem, raw)  # every row, also those a rerun replaced
        rows = rows_by[path.stem] = {r['id']: r for r in raw}
        per = {}
        for q in questions:
            row = rows.get(q['id'])
            if row is None:
                continue
            if row.get('error'):
                per[q['id']] = None
                continue
            records = [r for r in row['records'] if r.get('year') is None or r['year'] <= q['year']]
            per[q['id']] = litsearch.recall(q, records, meta)
        systems[path.stem] = per
    ids = sorted({c for q in questions for c in q['gold']})
    report = {'gold': {'papers': len(ids), 'in_openalex': sum(bool(meta.get(c, {}).get('openalex')) for c in ids),
                       'resolved_by_title': sum(meta.get(c, {}).get('resolved_by') == 'title' for c in ids),
                       's2_missing': sum(bool(meta.get(c, {}).get('s2_missing')) for c in ids),
                       'unresolved': sorted(c for c in ids if not meta.get(c, {}).get('openalex'))}}
    for name, per in systems.items():
        report[name] = {'questions': len(per), 'failed': sum(v is None for v in per.values()),
                        'mean_over': 'questions without failure; the paired differences count a failure as 0',
                        **{f'@{k}': litsearch.macro(per, k) for k in litsearch.DEPTHS}, **arms[name]}
        print(name, json.dumps({k: v for k, v in report[name].items() if k != 'settings'}))
    for name, diff in harness.comparisons(systems, litsearch.paired_bootstrap, litsearch.DEPTHS).items():
        report[name] = diff
        print(name, json.dumps(diff))
    for name in ('deixis', 'deixis_rerank'):  # the pool is the same in both new arms; only the order differs
        if name in rows_by:
            report[f'{name}_routes'] = litsearch.route_breakdown(questions, rows_by[name], meta)
            print(f'{name} routes', json.dumps(report[f'{name}_routes']))
    print('gold', json.dumps({k: v for k, v in report['gold'].items() if k != 'unresolved'}))
    (HOME / 'report.json').write_text(json.dumps(report, indent=1))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--n', type=int, default=50)
    p.set_defaults(fn=prepare)
    o = sub.add_parser('openalex')
    o.add_argument('--limit', type=int, default=None)
    o.set_defaults(fn=run_openalex)
    d = sub.add_parser('deixis')
    d.add_argument('--base', required=True)
    d.add_argument('--data-dir', required=True)
    d.add_argument('--limit', type=int, default=None)
    d.add_argument('--timeout', type=int, default=900)
    d.add_argument('--prepaid-floor', type=float, default=None,
                   help='spend prepaid OpenAlex credit, stopping once the balance falls below this many USD')
    d.set_defaults(fn=run_deixis)
    pf = sub.add_parser('preflight')
    pf.add_argument('--base', required=True)
    pf.add_argument('--data-dir', required=True)
    pf.set_defaults(fn=preflight)
    sub.add_parser('score').set_defaults(fn=score)
    args = parser.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()

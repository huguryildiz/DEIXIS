"""Network side of the electrical-engineering survey benchmark (benchmark plan 3a): set, system runs, scoring.

    uv run python scripts/benchmark/eesurvey_run.py prepare --max-spend 0.30 --prepaid-floor 3.0
    uv run python scripts/benchmark/eesurvey_run.py openalex --prepaid-floor 1
    uv run python scripts/benchmark/eesurvey_run.py preflight --base http://127.0.0.1:8769 --data-dir notes/eesurvey/data
    uv run python scripts/benchmark/eesurvey_run.py deixis --base http://127.0.0.1:8769 --data-dir notes/eesurvey/data \
        --prepaid-floor 1
    uv run python scripts/benchmark/eesurvey_run.py score

`prepare` reads the survey pool from OpenAlex (filters only), picks the surveys (eesurvey.select), fetches each one's
references, keeps the gold set, and has claude-sonnet-5-5 write one question per survey. Every network answer is cached
under notes/eesurvey/raw/, so a rerun spends nothing on what it already has; the owner's removals go in
notes/eesurvey/exclude.json (a list of OpenAlex ids) and a rerun moves the next survey up. A question's id comes from
its survey and its tune/test side is kept once given; the set's fingerprint goes in runs/SET, and every command refuses
runs made for a different set. A question that fails the wording check after its retry stops preparation and every
run. Each OpenAlex reply's balance headers are read: preparation stops when it has spent `--max-spend` or, once the
free daily balance is used, when the prepaid balance would go below `--prepaid-floor`; a 402 or 429 stops it with no
retry.

The arms follow litsearch_run: plain OpenAlex (one model-written query, first 200, cut at the survey's date), and
DEIXIS arms B and C from one run with harness.py's settings, stop rule and budget floor. Outputs are runs/<system>.jsonl.
DEIXIS rows also name, for a record that chaining brought, the seeds it came from, so scoring can drop what only the
survey or a later paper brought in (eesurvey.clean); the dates scoring needs are read from OpenAlex and cached.
"""
from __future__ import annotations

import argparse
import json
import time
from contextlib import closing
from pathlib import Path

import httpx

try:
    from . import eesurvey, harness
    from .bioasq_run import EFFORT, MODEL, done_ids, measured_run, read_jsonl, secret, write_query
    from .litsearch_run import BudgetStop, LitDeixis
except ImportError:
    import eesurvey
    import harness
    from bioasq_run import EFFORT, MODEL, done_ids, measured_run, read_jsonl, secret, write_query
    from litsearch_run import BudgetStop, LitDeixis

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'notes/eesurvey'
RAW = HOME / 'raw'
OPENALEX = 'https://api.openalex.org/works'
POOL_FIELDS = ('id,doi,display_name,publication_date,publication_year,type,referenced_works_count,cited_by_count,'
               'primary_location')
SURVEY_FIELDS = POOL_FIELDS + ',abstract_inverted_index,referenced_works'
REF_FIELDS = 'id,doi,display_name,publication_date,publication_year,abstract_inverted_index'
PAUSE = 0.25  # at most four requests a second: below the 5/s OpenAlex allows for queries with many boolean operators

QUESTION_PROMPT = """Below are the title and abstract of a survey article in electrical engineering. Write the one \
research question a researcher would type into a literature-search tool when they want to find the body of work this \
survey covers. Write as someone who has never seen this survey: do not mention a survey, review or tutorial, its \
authors or its title, and do not copy the title or reuse long phrases from it. Keep the scope as broad as the survey's. \
One or two plain sentences, no lists. Reply with the question only.

Title: {title}
Abstract: {abstract}"""
RETRY_NOTE = """

Your previous question was not usable ({problems}): {question}
Write a new one that avoids this."""
QUERY_PROMPT = """Write one keyword query for the OpenAlex works `search` parameter that finds papers answering this \
electrical-engineering literature request. OpenAlex search accepts AND, OR, NOT, double-quoted phrases and parentheses; \
no wildcards or field tags. Reply with the query only.

Request: {question}"""
REPAIR_PROMPT = """OpenAlex rejected this search query. Fix only what makes it invalid (no wildcards, no prose, \
balanced quotes and parentheses; AND, OR, NOT, quoted phrases and parentheses are allowed) and keep everything else. \
Reply with the query only.

Request: {question}
Rejected query: {query}
Error: {error}"""


class Meter:
    """OpenAlex requests that watch the balance headers: stop on 402/429, past `max_spend`, or below the floor."""

    def __init__(self, client, max_spend, prepaid_floor):
        self.client, self.max_spend, self.floor = client, max_spend, prepaid_floor
        self.key = secret('OPENALEX_API_KEY')
        self.start = harness.openalex_balance(client, self.key)
        self.last, self.requests, self.charged = dict(self.start), 0, 0.0
        print(f"OpenAlex at start: daily {self.start['daily_usd']} USD, prepaid {self.start['prepaid_usd']} USD")

    def spent(self):
        """The larger of the balance drop and the sum of the per-request costs OpenAlex reported."""
        drop = sum(self.start[k] or 0 for k in self.start) - sum(self.last[k] or 0 for k in self.last)
        return max(drop, self.charged)

    def get(self, params):
        if self.spent() + 0.002 > self.max_spend:
            raise BudgetStop(f'preparation would pass {self.max_spend} USD (spent {self.spent():.4f})')
        if ((self.last['daily_usd'] or 0) < 0.002 and self.last['prepaid_usd'] is not None
                and self.last['prepaid_usd'] - 0.002 < self.floor):
            raise BudgetStop(f"prepaid balance {self.last['prepaid_usd']} USD would go below {self.floor}")
        time.sleep(PAUSE)
        reply = self.client.get(OPENALEX, params=params, timeout=120, headers={'Authorization': f'Bearer {self.key}'})
        self.requests += 1
        if reply.status_code in (402, 429):
            raise BudgetStop(f'OpenAlex {reply.status_code}: {reply.text[:200]}')
        reply.raise_for_status()
        self.charged += float(reply.headers.get('x-ratelimit-cost-usd') or 0)
        for key, header in (('daily_usd', 'x-ratelimit-remaining-usd'), ('prepaid_usd', 'x-ratelimit-prepaid-remaining-usd')):
            if reply.headers.get(header) is not None:
                self.last[key] = float(reply.headers[header])
        return reply.json()


def cached(path, fetch):
    if path.exists():
        return json.loads(path.read_text())
    value = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return value


def pool(meter, tier):
    """Every article or review with enough references in the tier's venues and years (cursor-read, filters only)."""
    sources = '|'.join(s for s, (_, t, _) in eesurvey.VENUES.items() if t == tier)
    filt = (f'primary_location.source.id:{sources},publication_year:{eesurvey.YEARS[0]}-{eesurvey.YEARS[1]},'
            f'referenced_works_count:>{eesurvey.MIN_REFS - 1},type:article|review')
    works, cursor = [], '*'
    while cursor:
        page = meter.get({'filter': filt, 'select': POOL_FIELDS, 'per_page': 100, 'cursor': cursor})
        works += page['results']
        cursor = page['meta'].get('next_cursor') if page['results'] else None
    return works


def by_ids(meter, ids, fields):
    out = []
    for start in range(0, len(ids), 100):
        chunk = ids[start:start + 100]
        out += meter.get({'filter': 'openalex:' + '|'.join(chunk), 'select': fields, 'per_page': 100})['results']
    return out


def ask(client, prompt):
    """claude-sonnet-5-5 at medium effort, called as bioasq_run.write_query does; returns (text, raw reply)."""
    body = {'model': MODEL, 'max_tokens': 2000, 'output_config': {'effort': EFFORT},
            'messages': [{'role': 'user', 'content': prompt}]}
    reply = client.post('https://api.anthropic.com/v1/messages', json=body, timeout=120,
                        headers={'x-api-key': secret('ANTHROPIC_API_KEY'), 'anthropic-version': '2023-06-01'})
    reply.raise_for_status()
    raw = reply.json()
    return ' '.join(b['text'] for b in raw['content'] if b['type'] == 'text').strip(), raw


def write_question(client, survey):
    """One question for the survey, with one retry when it copies the title or names the survey; every attempt's
    prompt and raw reply are kept."""
    title = survey['display_name']
    prompt = QUESTION_PROMPT.format(title=title, abstract=eesurvey.abstract(survey.get('abstract_inverted_index'))
                                    or '(OpenAlex has no abstract for this survey)')
    attempts = []
    for _ in range(2):
        text, raw = ask(client, prompt)
        problems = eesurvey.question_problems(text, title)
        attempts.append({'prompt': prompt, 'raw': raw, 'question': text, 'problems': problems})
        if not problems:
            break
        prompt = attempts[0]['prompt'] + RETRY_NOTE.format(problems='; '.join(problems), question=text)
    return attempts


def set_mark():
    return (HOME / 'runs/SET').read_text().strip() if (HOME / 'runs/SET').exists() else None


def prepare(args):
    HOME.mkdir(parents=True, exist_ok=True)
    before = json.loads((HOME / 'sample.json').read_text()) if (HOME / 'sample.json').exists() else {}
    frozen = {q['id']: q['split'] for q in before.get('questions', [])}
    exclude = json.loads((HOME / 'exclude.json').read_text()) if (HOME / 'exclude.json').exists() else []
    with httpx.Client() as client:
        meter = Meter(client, args.max_spend, args.prepaid_floor)
        try:
            works = cached(RAW / 'pool_tier1.json', lambda: pool(meter, 1))
            picked = eesurvey.select(works, exclude=exclude)
            if any(len(items) < eesurvey.PER_TOPIC for items in picked.values()):  # IEEE Access only when needed
                works += cached(RAW / 'pool_tier2.json', lambda: pool(meter, 2))
                picked = eesurvey.select(works, exclude=exclude)
            chosen = [c for items in picked.values() for c in items]
            ids = [eesurvey.openalex_short(c['work']['id']) for c in chosen]
            full = {eesurvey.openalex_short(w['id']): w for w in cached(
                RAW / f'surveys-{eesurvey.tie(0, ",".join(sorted(ids)))[:12]}.json',
                lambda: by_ids(meter, ids, SURVEY_FIELDS))}
            refs = {}
            for wid in ids:
                listed = [eesurvey.openalex_short(w) for w in full[wid].get('referenced_works') or []]
                refs[wid] = cached(RAW / f'refs/{wid}.json', lambda: by_ids(meter, listed, REF_FIELDS))
        except BudgetStop as exc:
            print(f'stopped: {exc}; {meter.requests} OpenAlex requests, {meter.spent():.4f} USD spent; rerun later')
            return
        finally:
            print(f'OpenAlex: {meter.requests} requests, {meter.spent():.4f} USD spent, now {json.dumps(meter.last)}')
        questions, gold_meta = [], {}
        for c in chosen:
            wid = eesurvey.openalex_short(c['work']['id'])
            survey = full[wid]
            kept, counts = eesurvey.gold(survey, refs[wid])
            for r in refs[wid]:
                if eesurvey.openalex_short(r['id']) in kept:
                    gold_meta[eesurvey.openalex_short(r['id'])] = eesurvey.gold_record(r)
            attempts = cached(RAW / f'questions/{wid}.json', lambda: write_question(client, survey))
            questions.append({
                'id': eesurvey.question_id(wid), 'topic': c['topic'], 'body': attempts[-1]['question'],
                'question_problems': attempts[-1]['problems'], 'question_attempts': len(attempts),
                'cut_date': survey['publication_date'], 'year': survey['publication_year'],
                'survey': {'openalex': wid, 'title': survey['display_name'], 'doi': survey.get('doi'),
                           'date': survey['publication_date'], 'has_abstract': bool(survey.get('abstract_inverted_index')),
                           'why': c['why']},
                'gold': kept, 'gold_counts': counts})
    splits = eesurvey.split(questions, frozen=frozen)
    for q in questions:
        q['split'] = splits[q['id']]
    mark = eesurvey.fingerprint(questions)
    if set_mark() not in (None, mark):
        raise SystemExit(f'runs/ holds results for set {set_mark()}, this one is {mark}: move runs/ aside first')
    sample = {'seed': eesurvey.SEED, 'fingerprint': mark, 'per_topic': eesurvey.PER_TOPIC, 'excluded': exclude,
              'rules': {'years': eesurvey.YEARS, 'min_references': eesurvey.MIN_REFS,
                        'venues': {s: v[0] for s, v in eesurvey.VENUES.items()}, 'tune_share': eesurvey.TUNE_SHARE,
                        'question_model': f'{MODEL} {EFFORT}', 'question_prompt': QUESTION_PROMPT},
              'questions': questions}
    (HOME / 'sample.json').write_text(json.dumps(sample, indent=1))
    (HOME / 'gold_meta.json').write_text(json.dumps(gold_meta, indent=1))
    (HOME / 'SET.md').write_text(set_markdown(questions))
    sizes = sorted(len(q['gold']) for q in questions)
    print(f'{len(questions)} surveys; per topic '
          + json.dumps({t: sum(q['topic'] == t for q in questions) for t in eesurvey.TOPIC_ORDER})
          + f"; gold median {sizes[len(sizes) // 2] if sizes else None}, range {sizes[:1]}–{sizes[-1:]}; "
          f"with abstract {sum(m['has_abstract'] for m in gold_meta.values())} of {len(gold_meta)}; "
          f"question problems {sum(bool(q['question_problems']) for q in questions)}")
    if bad := [q['survey']['openalex'] for q in questions if q['question_problems']]:
        raise SystemExit(f'questions failed the wording check twice for {bad}: add them to exclude.json and rerun')


def set_markdown(questions):
    """The owner's reading copy in plain Turkish: per topic, each survey, why it is in, its gold size and question."""
    total = sum(len(q['gold']) for q in questions)
    abstracts = sum(q['gold_counts']['with_abstract'] for q in questions)
    lines = ['# Elektrik mühendisliği survey kümesi', '',
             f'{len(questions)} survey, {len(eesurvey.TOPIC_ORDER)} konu. Her survey bir soru verir; altın liste '
             'survey\'in OpenAlex kaynakçasıdır. Survey\'in kendisi ve yayın tarihinden sonraki kayıtlar dışarıda. '
             f'Altın kayıtların toplamı {total}, özeti olanlar {abstracts} '
             f'(%{100 * abstracts / max(total, 1):.0f}).', '',
             'Soruların üçte biri ayar (tune), üçte ikisi test için işaretli; sonuç test kısmında okunur. '
             'İstemediğin survey\'in OpenAlex kimliğini `notes/eesurvey/exclude.json` listesine yaz ve `prepare`\'ı '
             'yeniden çalıştır; sıradaki survey yerine geçer.', '']
    for topic in eesurvey.TOPIC_ORDER:
        items = [q for q in questions if q['topic'] == topic]
        lines += [f'## {eesurvey.TOPIC_LABELS[topic]} ({len(items)})', '']
        for q in items:
            s, c, why = q['survey'], q['gold_counts'], q['survey']['why']
            lines += [f"**{q['id']}** · {s['title']}",
                      f"- {why['venue']}, {s['date']} · {s['openalex']} · {why['cited_by_count']} atıf",
                      f"- Neden: {why['survey_rule']}; konu: {why['topic_rule']}",
                      f"- Kaynakça {c['listed']}, OpenAlex'te yok {c['missing']}, survey'den sonra {c['after_survey']}, "
                      f"tarihsiz {c['undated']} → altın {c['kept']} (özeti olan {c['with_abstract']}) · {q['split']}",
                      f"- Soru: {q['body']}"]
            if q['question_problems']:
                lines.append(f"- Dikkat: soru kontrolü geçmedi ({'; '.join(q['question_problems'])})")
            lines.append('')
    return '\n'.join(lines)


def openalex_records(client, query, cut_date, limit=200):
    records, cursor = [], '*'
    while cursor and len(records) < limit:
        time.sleep(PAUSE)
        reply = client.get(OPENALEX, timeout=60, headers={'Authorization': f'Bearer {secret("OPENALEX_API_KEY")}'},
                           params={'search': query, 'filter': f'to_publication_date:{cut_date}', 'per_page': 100,
                                   'cursor': cursor, 'select': 'id,doi,display_name,publication_year,publication_date'})
        if reply.status_code in (402, 429):
            raise BudgetStop(f'OpenAlex {reply.status_code}: {reply.text[:200]}')
        reply.raise_for_status()
        page = reply.json()
        records += [{'openalex': eesurvey.openalex_short(w['id']), 'doi': w.get('doi'), 'title': w.get('display_name'),
                     'year': w.get('publication_year'), 'date': w.get('publication_date')} for w in page['results']]
        cursor = page['meta'].get('next_cursor') if page['results'] else None
    return records[:limit]


def checked_set():
    """The questions, refused when one failed the wording check or runs/ was made for another set."""
    sample = json.loads((HOME / 'sample.json').read_text())
    if bad := [q['id'] for q in sample['questions'] if q['question_problems']]:
        raise SystemExit(f'questions {bad} failed the wording check: exclude their surveys and prepare again')
    mark = eesurvey.fingerprint(sample['questions'])  # from the content, never the stored value alone
    if mark != sample['fingerprint']:
        raise SystemExit(f"sample.json was changed after preparation: content {mark}, stored {sample['fingerprint']}")
    if set_mark() not in (None, mark):
        raise SystemExit(f'runs/ holds results for set {set_mark()}, sample.json is {mark}')
    (HOME / 'runs').mkdir(exist_ok=True)
    (HOME / 'runs/SET').write_text(mark + '\n')
    return sample['questions']


def questions_for(args):
    return checked_set()[:args.limit]


def run_openalex(args):
    """Plain OpenAlex: one model-written keyword query; a rejected query gets one model repair and one retry."""
    questions = questions_for(args)
    out = HOME / 'runs/openalex.jsonl'
    skip = done_ids(out)
    with httpx.Client() as client:
        for q in questions:
            if q['id'] in skip:
                continue
            if why := harness.budget_stop(client, secret('OPENALEX_API_KEY'), args.prepaid_floor):
                print(f'stopped: {why}; {len(done_ids(out))} of {len(questions)} questions done')
                return
            row = {'id': q['id']}
            try:
                row['query'] = write_query(client, QUERY_PROMPT.format(question=q['body']), raw=True)
                try:
                    row['records'] = openalex_records(client, row['query'], q['cut_date'])
                except httpx.HTTPStatusError as exc:
                    row['rejected_query'] = row['query']
                    row['query'] = write_query(client, REPAIR_PROMPT.format(
                        question=q['body'], query=row['query'], error=str(exc)[:200]), raw=True)
                    row['records'] = openalex_records(client, row['query'], q['cut_date'])
            except BudgetStop as exc:
                print(f'stopped: {exc}; {len(done_ids(out))} of {len(questions)} questions done, rerun later')
                return
            except Exception as exc:  # recorded and scored as a failure, never retried silently
                row['error'] = f'{type(exc).__name__}: {exc}'[:500]
            with out.open('a') as f:
                f.write(json.dumps(row) + '\n')
            print(q['id'], row.get('error') or f"{len(row['records'])} records")


class EEDeixis(LitDeixis):
    def records(self, order, research_id):
        """LitDeixis rows, and for a record that chaining brought, the OpenAlex ids of the seeds it came from."""
        rows = LitDeixis.records(self, order, research_id)
        with closing(self.db()) as conn:
            seeds = {}
            for svid, seed in conn.execute(
                    "SELECT l.source_version_id, m.value FROM chain_links l LEFT JOIN identifier_mappings m ON "
                    "m.source_version_id = l.seed_source_version_id AND m.scheme = 'openalex' WHERE l.research_id = ? "
                    "AND l.passed_filter = 1 AND l.source_version_id IS NOT NULL", (research_id,)):
                seeds.setdefault(svid, set()).add(eesurvey.openalex_short(seed) if seed else None)
        for r in rows:
            if r['svid'] in seeds:
                r['chain_seeds'] = sorted(seeds[r['svid']], key=str)
        return rows


def run_deixis(args):
    """Arms B and C from one run per question, with harness.py's settings, stop rule and budget floor."""
    server = EEDeixis(args.base, args.data_dir)
    args.keep = None
    try:
        measured_run(args, HOME, questions_for(args), server, server.records)
    except harness.Stop as exc:
        raise SystemExit(f'stopped: {exc}')


def preflight(args):
    try:
        print(json.dumps(harness.preflight(LitDeixis(args.base, args.data_dir), secret), indent=1))
    except harness.Stop as exc:
        raise SystemExit(f'preflight failed: {exc}')


def dates_for(ids, max_spend, prepaid_floor):
    """OpenAlex publication dates for `ids`, cached in raw/dates.json (an id OpenAlex does not return maps to None)."""
    path = RAW / 'dates.json'
    known = json.loads(path.read_text()) if path.exists() else {}
    missing = sorted(set(ids) - set(known))
    if missing:
        with httpx.Client() as client:
            meter = Meter(client, max_spend, prepaid_floor)
            try:
                found = {eesurvey.openalex_short(w['id']): w.get('publication_date')
                         for w in by_ids(meter, missing, 'id,publication_date')}
            except BudgetStop as exc:
                raise SystemExit(f'stopped reading dates: {exc}')
        known |= {wid: found.get(wid) for wid in missing}
        path.write_text(json.dumps(known))
    return known


def score(args):
    questions = checked_set()
    ids = {q['id'] for q in questions}
    meta = json.loads((HOME / 'gold_meta.json').read_text())
    runs, arms = {}, {}
    for path in sorted((HOME / 'runs').glob('*.jsonl')):
        raw = read_jsonl(path)
        if stray := sorted({r['id'] for r in raw} - ids):
            raise SystemExit(f'{path.name}: rows for questions not in this set: {stray[:5]}')
        arms[path.stem] = harness.check_arm(path.stem, raw)  # every row, also those a rerun replaced
        runs[path.stem] = {r['id']: r for r in raw}
    dates = dates_for(eesurvey.undated_ids(questions, runs), args.max_spend, args.prepaid_floor)
    systems, dropped = eesurvey.score_systems(questions, runs, meta, dates)
    reranked = {qid for qid, row in runs.get('deixis_rerank', {}).items()
                if not row.get('error') and (row.get('rerank') or {}).get('applied', True)}
    groups = {'all': {q['id'] for q in questions}, 'test': {q['id'] for q in questions if q['split'] == 'test'},
              'tune': {q['id'] for q in questions if q['split'] == 'tune'}}
    report = {'note': 'reference lists are incomplete gold: read the paired differences, not absolute recall; arm means '
                      'leave failed questions out, the paired differences count them as zero',
              'set': set_mark(), 'arms': arms, 'dropped': dropped,
              'rerank_not_applied': sorted(set(runs.get('deixis_rerank', {})) - reranked)}
    print('dropped', json.dumps(dropped))
    for group, ids in groups.items():
        part = eesurvey.subset(systems, ids)
        report[group] = {name: eesurvey.summary(per) for name, per in part.items()}
        report[group]['comparisons'] = harness.comparisons(part, eesurvey.paired_bootstrap, eesurvey.DEPTHS)
        print(group, json.dumps({name: {k: v for k, v in s.items() if k in ('questions', 'failed', '@20', '@50', '@200')}
                                 for name, s in report[group].items() if name != 'comparisons'}))
        for name, diff in report[group]['comparisons'].items():
            print(f'  {group} {name} @50', json.dumps(diff['@50']))
        # Second reading only: the questions whose rerank the product applied (a selected subset, not the effect).
        only = eesurvey.subset(systems, ids & reranked)
        report[group]['reranked_only'] = {'questions': len(ids & reranked), 'comparisons': harness.comparisons(
            only, eesurvey.paired_bootstrap, eesurvey.DEPTHS) if ids & reranked else None}
    report['by_topic_test'] = {
        topic: {name: eesurvey.summary(per) for name, per in eesurvey.subset(systems, {
            q['id'] for q in questions if q['topic'] == topic and q['split'] == 'test'}).items()}
        for topic in eesurvey.TOPIC_ORDER}
    (HOME / 'report.json').write_text(json.dumps(report, indent=1))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--max-spend', type=float, default=0.30, help='OpenAlex USD this preparation may spend')
    p.add_argument('--prepaid-floor', type=float, default=3.0, help='stop before the prepaid balance goes below this')
    p.set_defaults(fn=prepare)
    o = sub.add_parser('openalex')
    o.add_argument('--limit', type=int, default=None)
    o.add_argument('--prepaid-floor', type=float, default=None,
                   help='spend prepaid OpenAlex credit, stopping once the balance would fall below this many USD')
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
    sc = sub.add_parser('score')
    sc.add_argument('--max-spend', type=float, default=0.05, help='OpenAlex USD reading missing dates may spend')
    sc.add_argument('--prepaid-floor', type=float, default=1.0)
    sc.set_defaults(fn=score)
    args = parser.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()

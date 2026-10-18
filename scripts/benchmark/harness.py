"""Shared DEIXIS side of the BioASQ and LitSearch runs (benchmark plan, .local/plans/benchmark-plan.md, 18 Oct).

The runner sets the measured configuration in its temporary data folder and reads it back, so an empty folder's
defaults (Gemini, reranker off) are never measured by accident. Every row carries those settings. After each question
the run must show the expected embedding and an applied rerank; otherwise the whole run stops and the question is not
written. One exception, decided 18 Oct after the EE survey set's second question: when the product's own ranking-stage
time ran out before the rerank (`no_time_left`, recorded by the product, D104), the row is written and arm C is what
the product delivered, the fused order; the row says the rerank was not applied, and the report gives C−B over every
question first and over the reranked ones second. Keys, provider errors and a different reranker still stop. Arm B (reranker off) and arm C (reranker on) come from one run: the frozen list keeps the fused order
(`automatic_order`) next to the reranked one (`order`), so both arms share the same queries and OpenAlex is read once.
"""
from __future__ import annotations

import json
import math
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import httpx

EMBEDDING = {'provider': 'voyage', 'model': 'voyage-4-lite'}
RERANKER = {'enabled': True, 'provider': 'voyage', 'pool_factor': 4.0, 'timeout_seconds': 180}
RERANK_MODEL = 'rerank-3-lite'
DEPTH = 'standard'
ARMS = {'fused': 'automatic_order', 'rerank': 'order'}  # arm B and arm C: file suffix -> list output field
RERANK_KEY = 'rerank:v1:list'
MAX_CANDIDATES = 400  # rerankers.MAX_CANDIDATES
RESEARCH_USD = 0.05  # one research costs about 0.037 USD of OpenAlex; below this much free money, stop
OPENALEX = 'https://api.openalex.org/works'
VOYAGE = 'https://api.voyageai.com/v1'
PROVENANCE = ('commit', 'date')  # recorded on every row, but not part of what makes two rows the same arm


class Stop(Exception):
    """The run must stop here: a wrong setting, a failed embedding or rerank, a pause or the budget."""


def expected():
    return {'embedding': dict(EMBEDDING),
            'reranker': {'enabled': True, 'provider': RERANKER['provider'], 'model': RERANK_MODEL,
                         'pool_factor': RERANKER['pool_factor'], 'timeout_seconds': RERANKER['timeout_seconds']}}


def read_settings(server):
    """The embedding and reranker settings as the server reports them; Stop when they differ from the plan's."""
    semantic, rerank = server.get('/api/semantic-search'), server.get('/api/reranking')
    got = {'embedding': {'provider': semantic.get('provider'), 'model': semantic.get('model')},
           'reranker': {key: rerank.get(key) for key in expected()['reranker']}}
    if got != expected():
        raise Stop(f'settings differ from the plan: got {json.dumps(got)}, expected {json.dumps(expected())}')
    return got | {'reranker_max_candidates': rerank.get('max_candidates')}


def configure(server):
    """Write the measured settings into the temporary data folder, then read them back."""
    server.put('/api/semantic-search', EMBEDDING)
    server.put('/api/reranking', RERANKER)
    return read_settings(server)


def commit():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def stamp(settings, model, effort):
    """What every row records about how it was produced."""
    return settings | {'depth': DEPTH, 'query_model': model, 'query_effort': effort, 'commit': commit(),
                       'date': datetime.now(timezone.utc).isoformat(timespec='seconds')}


def arm_key(row):
    """The settings that define an arm; rows from older runs carry none."""
    settings = row.get('settings')
    return None if settings is None else json.dumps({k: v for k, v in settings.items() if k not in PROVENANCE},
                                                    sort_keys=True)


def check_arm(name, rows):
    """Refuse to score an arm whose rows were produced with different settings."""
    keys = {arm_key(r) for r in rows}
    if len(keys) > 1:
        raise Stop(f'{name}: rows with {len(keys)} different settings; split them before scoring')
    commits = sorted({(r.get('settings') or {}).get('commit') for r in rows} - {None})
    return {'settings': json.loads(next(iter(keys))) if keys and None not in keys else None, 'commits': commits}


def step(conn, run_id, key):
    row = conn.execute('SELECT status, output_json FROM run_steps WHERE run_id=? AND operation_key=?',
                       (run_id, key)).fetchone()
    return (row[0], json.loads(row[1]) if row[1] else {}) if row else (None, {})


def embedding_problems(conn, run_id, required=True):
    """The embedding step failed or used another model; a missing step is a problem only when the list was built."""
    status, output = step(conn, run_id, 'source_similarity')
    model = f"{EMBEDDING['provider']}:{EMBEDDING['model']}"
    if status is None:
        return ['source_similarity missing'] if required else []
    if status != 'succeeded':
        return [f'source_similarity {status}']
    if output.get('provider') != EMBEDDING['provider'] or not str(output.get('stored_model', '')).startswith(model):
        return [f"embedding {output.get('provider')} {output.get('stored_model')}, expected {model}"]
    return []


NO_TIME = 'no_time_left'


def rerank_problems(conn, run_id, listing=None):
    """The rerank step failed, used another reranker or pool, or (with a list) was not applied to it."""
    status, output = step(conn, run_id, RERANK_KEY)
    if status is None:
        return ['rerank step missing'] if listing is not None else []
    timed_out = status == 'failed' and output.get('error_code') == NO_TIME  # the product's budget: a result
    found = [] if status == 'succeeded' or timed_out else [f"rerank step {status}: {output.get('error_code')}"]
    want = (RERANKER['provider'], RERANK_MODEL, RERANKER['pool_factor'])
    if (output.get('provider'), output.get('model'), output.get('pool_factor')) != want:
        found.append(f"reranker {output.get('provider')} {output.get('model')} pool {output.get('pool_factor')}, "
                     f"expected {want}")
    if listing is None:
        return found
    told = listing.get('reranker') or {}
    if timed_out:
        if told.get('applied') or told.get('reason') != NO_TIME:
            found.append(f"rerank ran out of time but the list says applied={told.get('applied')} "
                         f"reason={told.get('reason')}")
        return found
    size = min(MAX_CANDIDATES, math.ceil((output.get('read_top') or 0) * RERANKER['pool_factor']),
               len(listing.get('automatic_order') or ()))
    if len(output.get('candidate_ids') or ()) != size:
        found.append(f"reranked {len(output.get('candidate_ids') or ())} records, expected {size}")
    if not told.get('applied'):
        found.append(f"rerank not applied: {told.get('reason') or 'no reranker in the list'}")
    return found


def problems(conn, run_id, listing):
    """Why this question's ranking is not the configured one; empty when the embedding and the rerank both ran."""
    found = embedding_problems(conn, run_id)
    if (listing.get('manifest') or {}).get('user_priority'):
        found.append('records included by hand: arm B would leave them out')
    return found + rerank_problems(conn, run_id, listing)


def failed_run_problems(conn, run_id):
    """For a run that failed before its list froze: an embedding or rerank failure is a provider problem that stops
    the benchmark, not a product failure scored as zero."""
    return embedding_problems(conn, run_id, required=False) + rerank_problems(conn, run_id)


def arms(listing):
    """Arm B's and arm C's orders from one frozen list. Nothing was included by hand, so both start the same way."""
    return {arm: list(listing[field]) for arm, field in ARMS.items()}


def rerank_info(conn, run_id, listing):
    """What the rerank did for this question, from its own step: the row records it beside the starting settings."""
    _, output = step(conn, run_id, RERANK_KEY)
    told = listing.get('reranker') or {}
    return {'applied': bool(told.get('applied')), 'reason': told.get('reason'),
            'reranked': told.get('reranked'), 'read_top': output.get('read_top'),
            'provider': output.get('provider'), 'model': output.get('model'), 'pool_factor': output.get('pool_factor')}


def wait_listing(server, run_id, timeout):
    """The frozen small-batch list's whole output, or (None, state) if the run ends, pauses or times out first."""
    import time
    start = time.time()
    while time.time() - start < timeout:
        with closing(server.db()) as conn:
            status, output = step(conn, run_id, 'small_batch:v1:list')
            run = conn.execute('SELECT status, pause_reason, stage, error_json FROM runs WHERE id=?', (run_id,)).fetchone()
        if status == 'succeeded':
            return output, None
        if run['status'] in ('paused', 'failed', 'cancelled', 'completed'):
            return None, {'status': run['status'], 'stage': run['stage'], 'reason': run['pause_reason'],
                          'error': json.loads(run['error_json']) if run['error_json'] else None}
        time.sleep(2)
    return None, {'status': 'timeout'}


QUERY_PAUSE = 'search_query_failed'  # the model's query failed its checks; the person may ask it once more


def wait_with_query_retry(server, run_id, timeout, resumes_allowed=1):
    """Like `wait_listing`, but a run paused because the model's query failed is resumed while the product allows
    another attempt, as the person would ("Try again"), and at most `resumes_allowed` times for this question (an
    attempt spent in an earlier, cancelled run counts). Returns (listing, state, resumes). When no attempt is left the
    state says so, and the question is a product failure scored as zero; the code's query alone is never chosen."""
    resumes = 0
    while True:
        listing, state = wait_listing(server, run_id, timeout)
        if listing is not None or state['status'] != 'paused' or state['reason'] != QUERY_PAUSE:
            return listing, state, resumes
        if resumes >= resumes_allowed or not (state.get('error') or {}).get('retries_left'):
            return None, state | {'status': 'failed', 'reason': 'search_query_failed, no model attempt left'}, resumes
        server.post(f'/api/runs/{run_id}/resume', {})
        resumes += 1


def paused_on_query(home, qid, read_jsonl, server):
    """How to take up a question whose last stop was its run pausing on the model's query: (run to wait on or None,
    resumes still allowed, note). A run still paused is waited on again (its own retries decide); a run cancelled since
    (an older harness cancelled it) cannot be resumed, so the question is asked anew with the attempt it already spent
    counted, and the row notes it."""
    rows = [r for r in read_jsonl(home / 'stopped.jsonl') if r['id'] == qid and (r.get('state') or {}).get('reason')]
    last = rows[-1] if rows else {}
    if last.get('state', {}).get('reason') != QUERY_PAUSE:
        return None, 1, None
    with closing(server.db()) as conn:
        status = conn.execute('SELECT status FROM runs WHERE id=?', (last['run_id'],)).fetchone()
    if status and status[0] == 'paused':
        return (last['research_id'], last['run_id']), 1, None
    return None, 0, f"run {last['run_id']} paused on its query was cancelled before it could be resumed; asked anew " \
                    "with no further model attempt"


def stopped(home, row, why, done, total):
    """Keep the stopped question outside runs/ (it is never scored) and stop the run."""
    with (home / 'stopped.jsonl').open('a') as f:
        f.write(json.dumps(row | {'stopped': why}) + '\n')
    raise Stop(f'{why}; {done} of {total} questions done')


def done_in_all(paths, read_jsonl):
    """Questions written to every arm file. A product failure (an error row) is done too: it is scored as zero, and
    running it again until it succeeds would turn that zero into a success."""
    sets = [{r['id'] for r in read_jsonl(p)} for p in paths]
    return set.intersection(*sets) if sets else set()


def openalex_balance(client, key):
    """Free daily and prepaid OpenAlex dollars left, from a single-work request, which OpenAlex does not bill."""
    reply = client.get(f'{OPENALEX}/W2171068337', params={'select': 'id'}, timeout=60,
                       headers={'Authorization': f'Bearer {key}'})
    reply.raise_for_status()
    daily, prepaid = (reply.headers.get(name) for name in ('x-ratelimit-remaining-usd', 'x-ratelimit-prepaid-remaining-usd'))
    return {'daily_usd': None if daily is None else float(daily), 'prepaid_usd': None if prepaid is None else float(prepaid)}


def voyage_check(client, key):
    """One embedding and one rerank with the measured models; the tokens Voyage counted for each."""
    headers = {'Authorization': f'Bearer {key}'}
    embed = client.post(f'{VOYAGE}/embeddings', headers=headers, timeout=60,
                        json={'model': EMBEDDING['model'], 'input': ['beamforming'], 'input_type': 'query'})
    embed.raise_for_status()
    rerank = client.post(f'{VOYAGE}/rerank', headers=headers, timeout=60,
                         json={'model': RERANK_MODEL, 'query': 'beamforming', 'documents': ['antenna arrays', 'soil']})
    rerank.raise_for_status()
    return {'embedding_tokens': embed.json()['usage']['total_tokens'],
            'rerank_tokens': rerank.json()['usage']['total_tokens']}


def preflight(server, secret):
    """Before a run: settings written and read back, Voyage answers with both models, OpenAlex balance read."""
    report = {'settings': configure(server)}
    with httpx.Client() as client:
        if not (voyage := secret('VOYAGE_API_KEY')):
            raise Stop('no VOYAGE_API_KEY in the Keychain')
        report['voyage'] = voyage_check(client, voyage)
        report['openalex'] = openalex_balance(client, secret('OPENALEX_API_KEY'))
    return report


def budget_stop(client, key, prepaid_floor):
    """Why not to start another question, or None. The free daily dollars come first; once they are spent, go on only
    when the owner allowed prepaid spending and the balance is above the floor. A balance OpenAlex did not state stops."""
    left = openalex_balance(client, key)
    print(f"OpenAlex daily {left['daily_usd']} USD, prepaid {left['prepaid_usd']} USD")
    if left['daily_usd'] is None:
        return 'OpenAlex did not state the daily balance'
    if left['daily_usd'] >= RESEARCH_USD:
        return None
    if prepaid_floor is None:
        return 'OpenAlex daily budget spent'
    if left['prepaid_usd'] is None:
        return 'OpenAlex did not state the prepaid balance'
    if left['prepaid_usd'] - RESEARCH_USD < prepaid_floor:
        return f'prepaid balance would fall below {prepaid_floor} USD'
    return None


PAIRS = (('deixis_rerank', 'openalex'), ('deixis_fused', 'openalex'), ('deixis_rerank', 'deixis_fused'))


def comparisons(systems, bootstrap, depths):
    """Paired differences for every pair of arms present: C−A, B−A, C−B. The 17 Oct `deixis` runs (Gemini embedding;
    the LitSearch one lost the embedding on 30 questions) are history: their recall is listed, never compared."""
    return {f'{a}_minus_{b}': {f'@{k}': bootstrap(systems[a], systems[b], k) for k in depths}
            for a, b in PAIRS if a in systems and b in systems}

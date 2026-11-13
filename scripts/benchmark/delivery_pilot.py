"""Driver of the live delivery-time pilot: one research per question and depth, into a library read afterwards.

Each depth has an end-to-end target for the first sourced answer (1, 2 and 5 minutes) and a moment by which the
run must turn to writing it. Whether those targets hold is a live question and nothing offline answers it, so
this script produces the runs and nothing else: `delivery_time.py` reads what they took, and `check.py` reads one
answer's elements, which a person judges.

What the result carries. Ten questions run once at a depth give the rate observed on those ten, with the failed
and the answerless runs in the denominator. That is an observation, not a rate that holds in general: a claim of
the second kind needs its threshold and its sample size fixed before the run, and repeating the same ten
questions does not make them thirty. The word valid is split the same way: whether an answer is structurally
valid is read from stored rows, whether a pre-written answer element is actually supported is a person's reading.

One library per arm. `delivery_time.py` reports every run a library holds, so a second arm — a build with other
depth numbers — runs against its own data folder, and the rows written here name the commit and the state of
the working tree that produced them.

Two clocks this tool cannot read: the library holds the moment the answer row was written, not the moment it was
on the person's screen, and the detailed report does not start by itself, so its own time exists only where
somebody started one.

    uv run python scripts/benchmark/delivery_pilot.py plan notes/<folder>/config.json
    uv run python scripts/benchmark/delivery_pilot.py run notes/<folder>/config.json \
        --base http://127.0.0.1:8766 --data-dir notes/<folder>/data [--server-pid 1234] [--prepaid-floor 5]

The plan command freezes the experiment before any money is spent: it writes the run order, the question hashes
and the configuration's own hash, and the run command refuses a configuration that has changed since.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import httpx

try:
    from . import harness
    from .common import canonical, load_benchmark, sha
    from .delivery_time import TERMINAL
except ImportError:
    import harness
    from common import canonical, load_benchmark, sha
    from delivery_time import TERMINAL

ROOT = Path(__file__).resolve().parents[2]
DEPTHS = ('quick', 'standard', 'detailed')
# How long to wait for one run of each depth, as a multiple of the depth's own target. A run far past its target
# has missed it; the wait is long enough that the run's own end, not this script's patience, is what stops it.
WAIT_FACTOR = 10
TARGET_SECONDS = {'quick': 76, 'standard': 120, 'detailed': 235}
# After the discovery run ends, the answer run is queued a moment later. Below this many seconds of a finished
# discovery run with no answer run named, the ledger is read again rather than called done.
GRACE_SECONDS = 20
# How long to let a research's own background work finish before the next question starts. Writing the answer is
# not the end of the research: late full text can produce one revision, and a review may read the answer. That
# work is not part of the delivery time, but it is part of what the machine is doing, so the next question waits.
QUIET_SECONDS = 300
# How many readings in a row must find nothing working before the research is called quiet. One is not enough:
# the product opens the late-revision run after the last fetch row finishes, so a single reading can fall into
# the gap between the work that ended and the work that is about to start.
QUIET_READINGS = 3
POLL_SECONDS = 5


class Deixis:
    """The server, reached as a person's browser reaches it, plus its library read-only."""

    def __init__(self, base, data_dir):
        if base.rstrip('/').endswith(':8765'):
            raise SystemExit("refusing port 8765: it may be the owner's library")
        self.base, self.data_dir = base.rstrip('/'), Path(data_dir)
        self.http = httpx.Client(base_url=self.base, timeout=60)
        self.http.headers['x-deixis-csrf'] = self.http.get('/api/session').json()['csrf_token']

    def get(self, path):
        reply = self.http.get(path)
        reply.raise_for_status()
        return reply.json()

    def post(self, path, body):
        reply = self.http.post(path, json=body)
        reply.raise_for_status()
        return reply.json()

    def put(self, path, body):
        reply = self.http.put(path, json=body)
        reply.raise_for_status()
        return reply.json()

    def db(self):
        conn = sqlite3.connect((self.data_dir / 'library.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _command(args, timeout=5):
    """One read-only command's output, or None where the tool is missing, slow or unhappy. A reading nobody could
    take is absent, and absent is never read as a reading: a failed git call does not mean a clean tree."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True, cwd=ROOT)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout


def machine_state(server_pid=None):
    """What the machine was doing around one run: delivery time is wall clock, so a busy machine or a laptop on
    battery is part of what the number means. Every reading is taken on its own and may be absent. They explain
    an odd run; they are not grounds for dropping one."""
    state = {'utc': utc(), 'load': None, 'power': None, 'memory_free_percent': None, 'server': None}
    try:
        state['load'] = list(os.getloadavg())
    except OSError:
        pass
    if power := _command(['pmset', '-g', 'ps']):
        # The first line names the source, e.g. "Now drawing from 'AC Power'".
        state['power'] = power.splitlines()[0].strip()
    if pressure := _command(['memory_pressure', '-Q'], timeout=10):
        last = pressure.strip().splitlines()[-1]
        state['memory_free_percent'] = last.rsplit(':', 1)[-1].strip() if ':' in last else last.strip()
    if server_pid is not None and (usage := _command(['ps', '-o', '%cpu=,rss=', '-p', str(server_pid)])):
        parts = usage.split()
        if len(parts) == 2:
            state['server'] = {'cpu_percent': parts[0], 'rss_kb': parts[1]}
    return state


def load_config(path):
    """The experiment, read from its own file so a new pilot is a new configuration and not edited code. What the
    server would refuse is refused here instead, before a single question is started."""
    config = json.loads(Path(path).read_text())
    for key in ('name', 'questions', 'depths', 'seed', 'connection', 'model', 'settings'):
        if key not in config:
            raise SystemExit(f'configuration needs {key}')
    if bad := [d for d in config['depths'] if d not in DEPTHS]:
        raise SystemExit(f'unknown depth {bad}; the depths are {DEPTHS}')
    if not isinstance(config['seed'], int) or isinstance(config['seed'], bool):
        raise SystemExit('seed must be a whole number: the run order is drawn from it and must be repeatable')
    if config.get('repeats', 1) < 1:
        raise SystemExit('repeats must be at least 1')
    # The product never lets a connection pick a model of its own, and neither does the pilot: an unnamed model
    # is refused by the server on the first question, which is the most expensive moment to find out.
    if not isinstance(config['model'], str) or not config['model'].strip():
        raise SystemExit('model must be named: the connection never picks one itself')
    settings = config['settings']
    if not isinstance(settings.get('write'), dict) or not isinstance(settings.get('pin'), dict):
        raise SystemExit('settings need a write map and a pin map, each keyed by the endpoint')
    if not isinstance(settings.get('record', []), list):
        raise SystemExit('settings record must be a list of endpoints')
    for name in config['questions']:
        if not (ROOT / name).exists():
            raise SystemExit(f'question file not found: {name}')
    return config


def config_hash(config):
    return sha(canonical(config))


def questions_of(config):
    """Every question file's own hash check (`load_benchmark`), so a changed question stops the pilot."""
    return {name: load_benchmark(ROOT / name) for name in config['questions']}


def order(config):
    """The whole run order, fixed before the first request.

    Depth-blocked: every question at one depth, then the next depth. Inside a block the question order is drawn
    from the seed, and a block that would open on the question the block before it closed with is rotated by one,
    so no question is measured twice in a row off a provider's cache warmed a moment earlier. A second repeat
    rotates the blocks themselves, so a depth is not always measured at the same hour.
    """
    rows, seq, last = [], 0, None
    for repeat in range(config.get('repeats', 1)):
        turn = repeat % len(config['depths'])
        for block, depth in enumerate(config['depths'][turn:] + config['depths'][:turn]):
            names = list(config['questions'])
            random.Random(f'{config["seed"]}:{repeat}:{depth}').shuffle(names)
            if len(names) > 1 and names[0] == last:
                names.append(names.pop(0))
            for name in names:
                rows.append({'seq': seq, 'repeat': repeat, 'block': block, 'depth': depth, 'question': name})
                seq += 1
            last = names[-1]
    return rows


def frozen_order(out, config):
    """The frozen order, written by `plan` and read by `run`; a configuration changed since stops the run."""
    path = Path(out) / 'order.json'
    if not path.exists():
        raise SystemExit(f'{path} is missing: run the plan command before spending anything')
    frozen = json.loads(path.read_text())
    if frozen['config_sha256'] != config_hash(config):
        raise SystemExit('the configuration changed after the order was frozen; freeze a new folder instead')
    return frozen


def expected(settings):
    """Every endpoint whose reply is read back, and the keys of it the configuration pins."""
    return {path: dict(values) for path, values in settings['pin'].items()}


def read_settings(server, settings):
    """What the server reports, and a stop where it differs from what the configuration pinned.

    A folder's defaults are never measured by accident, and the check is not only the embedding and the reranker:
    every endpoint the configuration names is read, the pinned keys are compared, and the whole reply of each
    endpoint in `record` is kept with the rows, so a setting nobody pinned is at least readable afterwards.
    """
    wanted, got, recorded = expected(settings), {}, {}
    for path in dict.fromkeys(list(wanted) + list(settings.get('record', []))):
        reply = server.get(path)
        recorded[path] = reply
        if path in wanted:
            got[path] = {key: reply.get(key) for key in wanted[path]}
    if got != wanted:
        raise harness.Stop(f'settings differ from the configuration: got {json.dumps(got, sort_keys=True)}, '
                           f'wanted {json.dumps(wanted, sort_keys=True)}')
    return recorded


def configure(server, settings):
    for path, body in settings['write'].items():
        server.put(path, body)
    return read_settings(server, settings)


def worktree():
    """How this build differs from its commit. A pilot arm made by changing the depth numbers is an edited
    working tree, which the commit alone does not name, so the whole difference is hashed: the tracked changes
    and every untracked file's own contents, since a file git does not track can change without its name
    changing. Where git could not be read, nothing is claimed — absent is not clean."""
    status = _command(['git', 'status', '--porcelain=v1', '-uall'], timeout=30)
    diff = _command(['git', 'diff', 'HEAD'], timeout=30)
    if status is None or diff is None:
        return {'worktree_diff_sha256': None, 'worktree_clean': None}
    parts = [status, diff]
    for line in status.splitlines():
        if line.startswith('?? '):
            path = ROOT / line[3:].strip().strip('"')
            try:
                parts.append(f'{line[3:]}:{sha(path.read_bytes().hex())}')
            except OSError:
                return {'worktree_diff_sha256': None, 'worktree_clean': None}
    return {'worktree_diff_sha256': sha('\n'.join(parts)),
            'worktree_clean': status.strip() == '' and diff.strip() == ''}


def stamp(config, settings):
    """What every row records about how it was produced."""
    return {'arm': config.get('arm', 'frozen_modes'), 'settings': settings, 'connection': config['connection'],
            'model': config['model'], 'reasoning_effort': config.get('reasoning_effort'),
            'commit': harness.commit(), 'date': utc()} | worktree()


def ask(server, question, depth, config, key):
    """Start one research at one depth, as a person would. The idempotency key is written to the pilot's own
    record before the request is sent, so a reply that never arrives leaves a trace to look for."""
    research = server.post('/api/researches', {
        'question': question, 'effort': depth, 'model_connection': config['connection'],
        'requested_model': config['model'], 'reasoning_effort': config.get('reasoning_effort'),
        'review_mode': config.get('review_mode', 'off')})['research']
    reply = server.http.post(f"/api/researches/{research['id']}/runs", json={'kind': 'discovery'},
                             headers={'idempotency-key': key})
    reply.raise_for_status()
    return research['id'], reply.json()['id']


def run_state(conn, run_id):
    """Where this run has got to, read from stored rows.

    The discovery run ending is not the answer ending: the product queues a separate answer run and the ledger
    names it. So a run is over when discovery has ended and the answer run it queued has ended too, or when the
    research was never going to write an answer of its own. A pause is its own state: the pilot stops there,
    because answering a pause is the person's to do and a resumed run is no longer the run that was measured.
    """
    discovery = conn.execute('SELECT status, pause_reason, budget_json FROM runs WHERE id = ?',
                             (run_id,)).fetchone()
    if discovery is None:
        return {'state': 'working', 'discovery': None, 'answer_run_id': None, 'answer': None}
    ledger = conn.execute('SELECT answer_run_id, answer_outcome FROM fast_path_ledgers WHERE ledger_run_id = ?',
                          (run_id,)).fetchone()
    answer_run_id = ledger['answer_run_id'] if ledger else None
    answer = conn.execute('SELECT status, pause_reason FROM runs WHERE id = ?', (answer_run_id,)).fetchone() \
        if answer_run_id else None
    policy = (json.loads(discovery['budget_json']).get('fast_path') or {}) if discovery['budget_json'] else {}
    state = {'discovery': discovery['status'], 'answer_run_id': answer_run_id,
             'answer': answer['status'] if answer else None,
             'answer_outcome': ledger['answer_outcome'] if ledger else None,
             'no_answer_intended': policy.get('auto_answer') is False, 'state': 'working'}
    paused = next((row for row in (answer, discovery) if row is not None and row['status'] == 'paused'), None)
    if paused is not None:
        state['state'] = 'paused'
        state['pause_reason'] = paused['pause_reason']
    elif discovery['status'] in TERMINAL:
        if answer is not None:
            if answer['status'] in TERMINAL:
                state['state'] = 'stopped'
        elif state['no_answer_intended']:
            state['state'] = 'stopped'
        else:
            state['state'] = 'no_answer_yet'
    return state


# A run the product counts as still working. A paused run is not one: it waits for the person and spends
# nothing while it waits. Held here rather than imported, because these scripts read a library and do not run
# the product; a test holds this list against the product's own.
ACTIVE = ('queued', 'running', 'pause_requested')
# The two queues that keep working for a run that has already ended: the PDF fetches the read stage could not
# reach in time, and the open-web full-text searches. Each row names its research and its own state.
QUEUES = (('fast_path_background_fetches', ('queued', 'running')), ('fulltext_searches', ('queued', 'running')))


def working(conn, research_id):
    """What this research still has running, whatever started it.

    Writing the answer is not the end of the research: a late full-text read can produce one revision, a review
    can read the answer, and the fetch queues go on downloading PDFs and searching the open web for a run that
    ended minutes ago. None of that is part of the delivery time and all of it is on the machine the next
    question would be measured on.
    """
    marks = ','.join('?' * len(ACTIVE))
    out = [{'kind': row['kind'], 'id': row['id'], 'status': row['status']} for row in conn.execute(
        f'SELECT id, kind, status FROM runs WHERE research_id = ? AND status IN ({marks})',
        (research_id, *ACTIVE))]
    for table, states in QUEUES:
        marks = ','.join('?' * len(states))
        count = conn.execute(f'SELECT COUNT(*) FROM {table} WHERE research_id = ? AND status IN ({marks})',
                             (research_id, *states)).fetchone()[0]
        if count:
            out.append({'kind': table, 'id': None, 'status': f'{count} queued or running'})
    return out


def wait(server, run_id, limit, sleep=time.sleep, now=time.monotonic):
    """Wait until the run sends nothing more, pauses, or the limit passes. The limit is a safety line, not a
    measurement: the time a run took is read from its stored rows afterwards, never from this loop."""
    start, ended_at = now(), None
    while True:
        with closing(server.db()) as conn:
            state = run_state(conn, run_id)
        if state['state'] in ('paused', 'stopped'):
            return state
        if state['state'] == 'no_answer_yet':
            # Discovery has ended and no answer run is named yet; it is queued a moment later, so read again.
            ended_at = ended_at or now()
            if now() - ended_at >= GRACE_SECONDS:
                state['state'] = 'stopped'
                return state
        else:
            ended_at = None
        if now() - start >= limit:
            state['state'] = 'timeout'
            return state
        sleep(POLL_SECONDS)


def quiet(server, research_id, limit, sleep=time.sleep, now=time.monotonic, readings=QUIET_READINGS):
    """Wait for this research's own background work to end before the next question starts, and say what was
    still running if it did not. None of this is part of the delivery time; all of it is part of the machine.

    Quiet has to hold, not merely be read once: the product opens the late-revision run after the last fetch
    row finishes, so a single reading can land in the gap between the work that ended and the work that is
    about to start.
    """
    start, still = now(), 0
    while True:
        with closing(server.db()) as conn:
            left = working(conn, research_id)
        still = still + 1 if not left else 0
        if still >= readings:
            return {'quiet': True, 'still_working': [], 'readings': still}
        if now() - start >= limit:
            # At the limit, what matters is whether anything is actually working: the hold is there to catch
            # work about to start, not to call a still library busy because the readings ran out of time.
            return {'quiet': not left, 'still_working': left, 'readings': still}
        sleep(POLL_SECONDS)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def append(path, row):
    with path.open('a') as handle:
        handle.write(json.dumps(row) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def resume_point(rows_path, started_path):
    """What a second invocation may do, read from what the first one left.

    Only a run the pilot saw end counts as done. A question that paused or ran past the limit is not done and is
    not skipped either: its run may still be working, and starting the next question beside it would time two
    researches at once. The same goes for a request whose reply never arrived. Both stop the pilot and name what
    to look at, because which of the two it was is the person's to see.
    """
    rows = read_jsonl(rows_path)
    unfinished = [r for r in rows if (r.get('outcome') or {}).get('state') != 'stopped'
                  or (r.get('background') or {}).get('quiet') is False]
    if unfinished:
        why = ('still working' if (unfinished[0].get('background') or {}).get('quiet') is False
               else (unfinished[0].get('outcome') or {}).get('state'))
        raise SystemExit(f'{rows_path} holds a run that did not end cleanly (seq {unfinished[0]["seq"]}, '
                         f'{why}); deal with it before resuming')
    written = {r['seq'] for r in rows}
    if lost := [s for s in read_jsonl(started_path) if s['seq'] not in written]:
        raise SystemExit(f'{started_path} names a request with no run of its own (seq {lost[0]["seq"]}, key '
                         f'{lost[0]["idempotency_key"]}); find it in the library before resuming')
    return {(r['question'], r['depth'], r['repeat']) for r in rows}


def take_lock(*folders):
    """One pilot at a time, over the rows it writes and over the library it measures.

    Two invocations reading the same unfinished order would start the same question twice: the order's rows are
    not claimed atomically, and the idempotency key the product honours belongs to a research each invocation
    would create for itself. Two invocations with their own folders would still share one server and one
    library, and a research measured beside another is not measured at all, so the library is locked too.
    """
    taken = []
    for folder in folders:
        path = Path(folder) / 'delivery-pilot.lock'
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            for done in taken:
                done.unlink(missing_ok=True)
            raise SystemExit(f'{path} exists: another pilot is running here, or one was stopped without '
                             f'releasing it; read it, make sure nothing is running, then remove it') from None
        with os.fdopen(handle, 'w') as file:
            file.write(json.dumps({'pid': os.getpid(), 'at': utc()}))
        taken.append(path)
    return taken


def plan(args):
    config = load_config(args.config)
    out = Path(args.out or Path(args.config).parent)
    out.mkdir(parents=True, exist_ok=True)
    rows = order(config)
    frozen = {'name': config['name'], 'config_sha256': config_hash(config), 'frozen_at': utc(),
              'questions': {name: value['question_sha256'] for name, value in questions_of(config).items()},
              'order': rows}
    (out / 'order.json').write_text(json.dumps(frozen, indent=1))
    print(f"{len(rows)} runs over {len(config['questions'])} questions and {len(config['depths'])} depths "
          f"-> {out / 'order.json'}")
    for row in rows:
        print(f"  {row['seq']:>3}  {row['depth']:<9} {row['question']}")


def run(args):
    config = load_config(args.config)
    out = Path(args.out or Path(args.config).parent)
    frozen = frozen_order(out, config)
    questions = questions_of(config)
    for name, value in questions.items():
        if frozen['questions'].get(name) != value['question_sha256']:
            raise SystemExit(f'{name} changed after the order was frozen')
    rows_path, started_path, stopped_path = out / 'runs.jsonl', out / 'started.jsonl', out / 'stopped.jsonl'
    done = resume_point(rows_path, started_path)
    locks = take_lock(out, args.data_dir)
    try:
        _run(args, config, frozen, questions, done, rows_path, started_path, stopped_path)
    finally:
        for lock in locks:
            lock.unlink(missing_ok=True)


def _run(args, config, frozen, questions, done, rows_path, started_path, stopped_path):
    server = Deixis(args.base, args.data_dir)
    provenance = stamp(config, configure(server, config['settings']))
    secret = _keyring()
    with httpx.Client() as client:
        for item in frozen['order']:
            if (item['question'], item['depth'], item['repeat']) in done:
                continue
            if why := harness.budget_stop(client, secret('OPENALEX_API_KEY'), args.prepaid_floor):
                append(stopped_path, {'at': utc(), 'why': why, 'seq': item['seq']})
                raise SystemExit(f'stopped before {item["question"]} at {item["depth"]}: {why}')
            key = f'pilot-{uuid.uuid4().hex}'
            append(started_path, {'seq': item['seq'], 'idempotency_key': key, 'at': utc()})
            row = dict(item, stamp=provenance, question_sha256=questions[item['question']]['question_sha256'],
                       idempotency_key=key, machine_before=machine_state(args.server_pid), started_utc=utc())
            research_id, run_id = ask(server, questions[item['question']]['question'], item['depth'], config, key)
            row |= {'research_id': research_id, 'run_id': run_id}
            state = wait(server, run_id, TARGET_SECONDS[item['depth']] * config.get('wait_factor', WAIT_FACTOR))
            row |= {'finished_utc': utc(), 'machine_after': machine_state(args.server_pid), 'outcome': state}
            if state['state'] == 'stopped':
                # The answer is written; what the research does afterwards is not timed, but it is not run
                # beside the next question either.
                row['background'] = quiet(server, research_id, config.get('quiet_seconds', QUIET_SECONDS))
            append(rows_path, row)
            print(f"{item['seq']:>3}  {item['depth']:<9} {item['question']:<45} {state['state']}")
            if state['state'] != 'stopped':
                append(stopped_path, {'at': utc(), 'why': state['state'], 'seq': item['seq'], 'run_id': run_id,
                                      'research_id': research_id})
                raise SystemExit(f'stopped at {item["question"]} ({item["depth"]}): {state["state"]}')
            if not row['background']['quiet']:
                # Work from this question is still on the machine. Recording that would make the next question's
                # time readable as a mixture; stopping keeps it from being measured at all.
                append(stopped_path, {'at': utc(), 'why': 'research still working', 'seq': item['seq'],
                                      'research_id': research_id,
                                      'still_working': row['background']['still_working']})
                raise SystemExit(f'{item["question"]} ({item["depth"]}) is still working after '
                                 f'{config.get("quiet_seconds", QUIET_SECONDS)}s; the next question would be '
                                 f'measured beside it')
    print(f'done; read the times with: uv run python scripts/benchmark/delivery_time.py '
          f'{Path(args.data_dir) / "library.sqlite"}')


def _keyring():
    """Keys read the way the product reads them. The keychain holds them under one bundled item, so a reader of its
    own would miss a key the product uses; this fills the environment through the product's own loader and reads it."""
    from deixis.keys import credentials
    credentials.load_into_environment()

    def secret(name):
        return os.environ.get(name)
    return secret


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    freeze = sub.add_parser('plan', help='freeze the run order before anything is spent')
    freeze.add_argument('config')
    freeze.add_argument('--out', default=None, help="folder for order.json (default: the configuration's own)")
    freeze.set_defaults(func=plan)
    live = sub.add_parser('run', help='run the frozen order live')
    live.add_argument('config')
    live.add_argument('--base', required=True, help='the measurement server, never port 8765')
    live.add_argument('--data-dir', required=True, help="that server's isolated data folder")
    live.add_argument('--out', default=None)
    live.add_argument('--server-pid', type=int, default=None, help='the server process, recorded with each run')
    live.add_argument('--prepaid-floor', type=float, default=None,
                      help='prepaid OpenAlex dollars to leave unspent; without it the free daily budget is the cap')
    live.set_defaults(func=run)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    sys.exit(main())

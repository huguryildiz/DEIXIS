"""A benchmark server whose model connection replays a baseline library's stored model answers (an m1 arm).

    DEIXIS_SEARCH_METHOD=m1 uv run python scripts/benchmark/replay_answers.py \\
        --port 8776 --data-dir notes/2026-11-07-m1/bioasq/m1/data --baseline notes/2026-11-07-m1/bioasq/base/data

The arm is a controlled retrieval comparison conditional on fixed model replies and recorded latencies, not an
independent live-model comparison. Only the calls a discovery run makes before its list freezes are replayed:
vocabulary labelling, the query and its repairs, the criterion proposals. A call is paired with the baseline StepInput
of the same question, operation key and place in its step (`call_key`, read from the call's metadata, never from its
prompt), and answered only when its whole request (the rendered message, repair text included, the base and
developer instructions, the output schema, the model and the effort), with each generated id numbered by its first
occurrence and times blanked, equals that StepInput's. Its one completed session is then given back (a valid answer,
or an invalid one, so the product sends the same repair it sent before) after the baseline session's recorded
duration. A StepInput whose session failed, or that was resent, is refused: model_sessions keeps no per-session
failure fields, and none is invented. Every refusal is written to `replay.jsonl` beside the arm's library with its
time, and a question refused before its list froze is left out of both arms when scored. The connection keeps the
identity of the baseline's (`--connection`, default `claude`): its health answer is the real adapter's, and it makes
no model call. Never port 8765.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from deixis.domain import canonical
from deixis.models.adapter import ModelStepResult, model_call
from deixis.storage.db import now

REPLAYED = ('vocabulary_labels', 'search_query', 'criterion_proposal')
# What a run generates and the request does not depend on: record ids (`new_id`: a prefix, `_`, 20 characters) and
# ISO times. Each distinct id becomes a numbered placeholder by its first occurrence in the request, so two requests
# are equal only if their ids point to the same places; everything else in the request must be equal.
GENERATED_ID = re.compile(r'\b[a-z]{2,6}_[A-Za-z0-9]{20}\b')
TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:[+-]\d\d:\d\d|Z)?')


def blanked(texts):
    """The request's texts with each generated id numbered by first occurrence across all of them, times blanked."""
    numbers = {}

    def number(found):
        return f'<id{numbers.setdefault(found.group(0), len(numbers) + 1)}>'

    return [TIME.sub('<time>', GENERATED_ID.sub(number, text or '')) for text in texts]


def request_digest(base, developer, message, schema, model, effort):
    """The digest of a whole model request with its generated ids numbered and its times blanked."""
    base, developer, message = blanked([base, developer, message])
    return canonical.sha256_hex({'base': base, 'developer': developer, 'message': message,
                                 'schema': schema, 'model': model, 'effort': effort})


def question_of(message):
    found = re.search(r'<step-input>\n(.*?)\n</step-input>', message or '', re.DOTALL)
    payload = json.loads(found.group(1)) if found else {}
    return payload.get('task_type'), (payload.get('question') or {}).get('text')


def seconds(start, end):
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Session:
    """One stored model session that completed (its reply may still fail validation), and how long it took."""
    raw_output: str | None = None
    resolved_model: str | None = None
    token_usage: dict | None = None
    seconds: float = 0.0
    # The baseline product accepted this session's model: its step did not fail with model_mismatch. A connection
    # that answers an alias (`sonnet`) with the model it resolves to (`claude-sonnet-5-5`) verified the match then;
    # model_sessions keeps no column for it, so it is read from the step.
    model_verified: bool = False

    def result(self):
        return ModelStepResult('completed', raw_text=self.raw_output, resolved_model=self.resolved_model,
                               token_usage=self.token_usage, requested_model_verified=self.model_verified)


@dataclass
class Call:
    """One baseline StepInput (one attempt of a step). `refusal` is set when it cannot be replayed exactly: a session
    that did not complete (model_sessions keeps no per-session failure fields, and none is invented) or more than one
    session (a resend after such a failure)."""
    step_input_id: str
    question: str
    task_type: str
    digest: str
    session: Session | None = None
    refusal: str | None = None
    key: tuple = ()  # (operation key, the StepInput's place among its step's StepInputs): `call_key`


def call_key(conn, step_input_id):
    """A StepInput's stable place in a run: its step's operation key (`vocabulary_labels_2`, `search_query:1`) and
    which of that step's StepInputs it is (1 the first send, 2 its repair). The same in the baseline and the arm,
    whatever order concurrent calls arrive in."""
    row = conn.execute("SELECT st.operation_key, (SELECT COUNT(*) FROM step_inputs x WHERE x.step_id = si.step_id"
                       " AND x.rowid <= si.rowid) FROM step_inputs si JOIN run_steps st ON st.id = si.step_id"
                       " WHERE si.id = ?", (step_input_id,)).fetchone()
    return (row[0], row[1]) if row else None


class Baseline:
    """The baseline's pre-freeze model calls. An arm call is paired with the baseline StepInput of the same question
    and `call_key`, never by arrival order (the product sends the three label and criterion calls at once); a second
    run of a question takes the next such StepInput in baseline order. The request digests must be equal."""

    def __init__(self, calls):
        self.calls, self.next = list(calls), {}

    def take(self, question, key, digest):
        """(session, None) or (None, why the call is refused)."""
        queue = [c for c in self.calls if c.question == question and c.key == key]
        index = self.next.get((question, key), 0)
        if index >= len(queue):
            return None, 'more_calls_than_baseline'
        call = queue[index]
        if call.digest != digest:
            return None, 'no_matching_baseline_call'
        self.next[(question, key)] = index + 1
        if call.refusal:
            return None, call.refusal
        return call.session, None

    @classmethod
    def load(cls, data_dir):
        path = Path(data_dir) / 'library.sqlite'
        conn = sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        marks = ','.join('?' * len(REPLAYED))
        inputs = conn.execute(
            "SELECT si.id, si.task_type, si.base_instructions, si.developer_instructions, si.user_message,"
            " si.output_schema_json, s.question, st.error_code FROM step_inputs si"
            " JOIN run_steps st ON st.id = si.step_id"
            " JOIN runs r ON r.id = si.run_id AND r.kind = 'discovery'"
            " JOIN scope_revisions s ON s.research_id = si.research_id AND s.revision = si.scope_revision"
            f" WHERE si.task_type IN ({marks}) ORDER BY si.rowid", REPLAYED)
        calls = []
        for row in inputs:
            sessions = conn.execute("SELECT * FROM model_sessions WHERE step_input_id = ? ORDER BY started_at, rowid",
                                    (row['id'],)).fetchall()
            if not sessions:
                continue
            first = sessions[0]
            call = Call(row['id'], row['question'], row['task_type'], request_digest(
                row['base_instructions'], row['developer_instructions'], row['user_message'],
                json.loads(row['output_schema_json']), first['requested_model'], first['reasoning_effort']),
                key=call_key(conn, row['id']))
            if len(sessions) > 1:
                call.refusal = 'baseline_resend_not_replayable'
            elif first['status'] != 'completed':
                call.refusal = 'baseline_failure_not_stored'
            else:
                call.session = Session(first['raw_output'], first['resolved_model'],
                                       json.loads(first['token_usage_json']) if first['token_usage_json'] else None,
                                       seconds(first['started_at'], first['finished_at']),
                                       model_verified=row['error_code'] != 'model_mismatch')
            calls.append(call)
        conn.close()
        return cls(calls)


class ReplayAdapter:
    enforces_schema = True
    sends_reasoning_effort = True

    def __init__(self, real, baseline, log_path, library, sleep=asyncio.sleep):
        """`library`: the arm's own library.sqlite, read to place each call (`call_key`)."""
        self.real, self.baseline, self.log_path, self.sleep = real, baseline, Path(log_path), sleep
        self.library = Path(library)
        self.connection = real.connection
        self.lock = asyncio.Lock()

    def __getattr__(self, name):  # the real adapter's other reads (its quota record), never its model calls
        return getattr(self.real, name)

    async def health(self, refresh=False):
        return await self.real.health(refresh)

    def log(self, **row):
        with self.log_path.open('a') as f:
            f.write(json.dumps(row | {'at': now()}) + '\n')  # `at`: the scorer checks it against the list freeze

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
        task, question = question_of(message)
        if task not in REPLAYED:
            self.log(question=question, task_type=task, outcome='refused', reason='not_replayed')
            return ModelStepResult('failed', error=f'replay: {task} is not replayed')
        digest = request_digest(base, developer, message, output_schema, requested_model, reasoning_effort)
        meta = model_call.get()
        key = None
        if meta is not None:
            conn = sqlite3.connect(f'file:{self.library.resolve()}?mode=ro', uri=True)
            try:
                key = call_key(conn, meta['step_input_id'])
            finally:
                conn.close()
        async with self.lock:
            session, why = self.baseline.take(question, key, digest) if key else (None, 'no_call_metadata')
        if session is None:
            self.log(question=question, task_type=task, outcome='refused', reason=why)
            return ModelStepResult('failed', error=f'replay: {why}')
        await self.sleep(session.seconds)
        self.log(question=question, task_type=task, outcome='replayed')
        return session.result()

    async def cancel(self):
        return False

    async def close(self):
        await self.real.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--baseline', required=True, help="the baseline arm's data folder (read only)")
    parser.add_argument('--connection', default='claude')
    args = parser.parse_args()
    if args.port == 8765:
        raise SystemExit("refusing port 8765: it may be the owner's library")
    data_dir = Path(args.data_dir).resolve()
    if data_dir == Path(args.baseline).resolve():
        raise SystemExit('the arm and the baseline need separate data folders')
    os.environ['DEIXIS_DATA_DIR'], os.environ['DEIXIS_PORT'] = str(data_dir), str(args.port)
    import uvicorn
    from deixis.api.app import create_app
    from deixis.runtime.config import load_settings
    from deixis.models.claude import ClaudeCodeAdapter

    if args.connection != 'claude':
        raise SystemExit('only the claude connection is wired here')
    settings = load_settings()
    data_dir.mkdir(parents=True, exist_ok=True)
    real = ClaudeCodeAdapter(workspace=settings.data_dir / 'claude-workspace')
    adapter = ReplayAdapter(real, Baseline.load(args.baseline), data_dir / 'replay.jsonl', data_dir / 'library.sqlite')
    uvicorn.run(create_app(settings, adapters={args.connection: adapter}), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()

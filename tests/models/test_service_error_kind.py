"""Model and provider errors: kinds, rate limits, retry times and texts, with no secret in any message.

Mocked HTTP only. Passing shows the classification of these SYNTHETIC answers, not of every live provider answer.
"""

import asyncio
from datetime import datetime
import httpx
import pytest
import re
from fastapi.testclient import TestClient
from pathlib import Path

from deixis.domain.limits import SERVICE_ERROR_KINDS
from deixis.keys import credentials
from deixis.models.adapter import ModelStepResult
from deixis.models.adapter import is_rate_limited
from deixis.models.deepseek import DeepSeekAdapter
from deixis.models.gemini import GeminiAdapter
from deixis.models.openai_compat import OpenAICompatAdapter
from deixis.models.openai_compat import QWEN
from fakes import FakeAdapter, PLANNING_TASKS
from test_api_flow import app_for
from test_api_flow import create
from test_api_flow import session
from test_api_flow import wait_run


@pytest.mark.parametrize('code,kind', [(401, 'auth_failed'), (429, 'rate_limited')])
@pytest.mark.parametrize('connection', ['qwen'])
def test_http_model_errors_never_return_secret_fragments(monkeypatch, code, kind, connection):
    monkeypatch.setenv({'deepseek': 'DEEPSEEK_API_KEY', 'gemini': 'GEMINI_API_KEY', 'qwen': 'DASHSCOPE_API_KEY'}[connection], 'SYNTHETIC-private-key')
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(code,
        json={'error': {'message': 'SYNTHETIC-private… fragment', 'code': 'unrecognized'}}, headers={'retry-after': '30'})))
    adapter = {'deepseek': lambda: DeepSeekAdapter(client), 'gemini': lambda: GeminiAdapter(client),
               'qwen': lambda: OpenAICompatAdapter(QWEN, client)}[connection]()
    result = asyncio.run(adapter.run_step('b', 'd', 'm', {}, 'SYNTHETIC-model'))
    assert (result.error_kind, result.http_status, result.retry_after) == (kind, code, '30')
    assert 'SYNTHETIC-private' not in str(result)


@pytest.mark.parametrize('code,kind', [(401, 'auth_failed')])
def test_key_test_does_not_echo_body(code, kind):
    payload = {'error': {'message': 'SYNTHETIC-private…', 'code': 'insufficient_quota' if code == 429 else 'other'}}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(code, json=payload)))
    result = asyncio.run(credentials.test(client, 'OPENAI_API_KEY', 'SYNTHETIC-private-key'))
    assert result['kind'] == kind and result['http_status'] == code
    assert 'SYNTHETIC-private' not in str(result)


def test_model_quota_pause_preserves_metadata_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC-private-key')
    # A failed plan call pauses the current discovery policy with its error metadata.
    adapter = FakeAdapter(fail=lambda si: ModelStepResult(
        'failed', error='SYNTHETIC-private-key quota', error_kind='quota_exhausted', http_status=429, retry_after='120')
        if si['task_type'] == 'search_plan' else None)
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = create(client)
        run_id = client.post(f'/api/researches/{rid}/runs', json={'kind': 'discovery'}).json()['id']
        view, run = wait_run(client, rid, run_id)
        assert (run['status'], run['pause_reason']) == ('paused', 'search_query_failed')
        assert run['error']['reason'] == 'model_call_failed'
        events = app.state.store.events_after(rid, 0)
        event = next(e['payload'] for e in events if e['type'] == 'step_finished'
                     and e['payload'].get('operation_key') == 'search_query:1')
        assert event['service_kind'] == 'quota_exhausted' and event['http_status'] == 429
        assert event['connection'] == 'fake'
        assert datetime.fromisoformat(event['reset_at']).tzinfo is not None
        assert 'SYNTHETIC-private-key' not in str(view)
        for row in app.state.store.conn.execute('SELECT error_json FROM run_steps'):
            assert 'SYNTHETIC-private-key' not in str(row[0])


def test_every_service_code_has_english_and_turkish_text():
    root = Path(__file__).resolve().parents[2]
    labels = (root / 'web/src/lib/labels.ts').read_text(encoding="utf-8")
    block = labels.split('export const serviceErrors:', 1)[1].split('\n}', 1)[0]
    messages = dict(re.findall(r"^  (\w+): '([^']+)',", block, re.M))
    assert set(messages) == SERVICE_ERROR_KINDS
    translations = (root / 'web/src/lib/locales/tr.ts').read_text(encoding="utf-8")
    keys = set(re.findall(r"^  '((?:[^'\\]|\\.)*)':", translations, re.M))
    assert set(messages.values()) <= keys
    # Recovery and effect text needs both languages too.
    error_labels = labels.split('export const serviceErrors:', 1)[1].split('const recoveryReasons:', 1)[0]
    assert set(re.findall(r"\bt\('([^']+)'", error_labels)) <= keys


def test_an_http_429_error_is_rate_limited():
    assert is_rate_limited(ModelStepResult("failed", error="HTTP 429: Too Many Requests"))

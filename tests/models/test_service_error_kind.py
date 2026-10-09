"""Synthetic error classification, persistence and TR/EN coverage; no live calls."""

import asyncio
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import credentials
from deixis.domain.limits import SERVICE_ERROR_KINDS, retry_at, service_error_kind
from deixis.models.adapter import ModelStepResult
from deixis.models.deepseek import DeepSeekAdapter
from deixis.models.gemini import GeminiAdapter
from deixis.models.openai_compat import OpenAICompatAdapter, QWEN
from deixis.providers.common import send
from fakes import FakeAdapter
from test_api_flow import app_for, create, session, wait_run


@pytest.mark.parametrize('status,text,surface,expected', [
    (402, '', 'model', 'quota_exhausted'), (429, '', 'api', 'rate_limited'),
    (429, 'daily quota', 'api', 'quota_exhausted'),
    ('missing_contact_email', '', 'api', 'needs_key'),
    (401, '', 'api', 'auth_failed'), (403, '', 'model', 'auth_failed'),
    (400, '', 'api', 'bad_request'), (422, '', 'api', 'bad_request'),
    (404, '', 'model', 'model_unavailable'), (404, '', 'api', 'bad_request'),
    (404, '', 'pdf', 'not_found'), (410, '', 'pdf', 'not_found'),
    (403, '', 'pdf', 'blocked'), ('fetch_blocked_url', '', 'pdf', 'blocked'),
    (None, 'ReadTimeout', 'model', 'timeout'),
    (None, 'Claude Code turn timed out', 'model', 'timeout'),
    (500, '', 'model', 'service_error'), (529, '', 'model', 'service_error'),
    ('parse_error', '', 'api', 'service_error'),
    (None, 'ConnectError', 'model', 'network'), ('fetch_failed', '', 'pdf', 'network'),
    (None, 'unrecognized RPC error', 'model', 'unknown'),
])
def test_service_class(status, text, surface, expected):
    assert service_error_kind(status, text=text, surface=surface) == expected


@pytest.mark.parametrize('value', ['', 'garbage', '-1', 'inf', '1e99', '9' * 400, 'Bearer SYNTHETIC-key'])
def test_invalid_retry_header_has_no_time(value):
    assert retry_at(value) is None


def test_retry_seconds_and_http_date():
    observed = datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert retry_at('30', observed_at=observed) == '2026-10-09T00:00:30+00:00'
    assert retry_at('Fri, 09 Oct 2026 01:00:00 GMT', observed_at=observed) == '2026-10-09T01:00:00+00:00'


@pytest.mark.parametrize('code,kind', [(400, 'bad_request'), (401, 'auth_failed'), (404, 'model_unavailable'),
                                    (402, 'quota_exhausted'), (429, 'rate_limited'), (500, 'service_error')])
@pytest.mark.parametrize('connection', ['deepseek', 'gemini', 'qwen'])
def test_http_model_errors_never_return_secret_fragments(monkeypatch, code, kind, connection):
    monkeypatch.setenv({'deepseek': 'DEEPSEEK_API_KEY', 'gemini': 'GEMINI_API_KEY', 'qwen': 'DASHSCOPE_API_KEY'}[connection], 'SYNTHETIC-private-key')
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(code,
        json={'error': {'message': 'SYNTHETIC-private… fragment', 'code': 'unrecognized'}}, headers={'retry-after': '30'})))
    adapter = {'deepseek': lambda: DeepSeekAdapter(client), 'gemini': lambda: GeminiAdapter(client),
               'qwen': lambda: OpenAICompatAdapter(QWEN, client)}[connection]()
    result = asyncio.run(adapter.run_step('b', 'd', 'm', {}, 'SYNTHETIC-model'))
    assert (result.error_kind, result.http_status, result.retry_after) == (kind, code, '30')
    assert 'SYNTHETIC-private' not in str(result)


@pytest.mark.parametrize('code,kind', [(400, 'bad_request'), (401, 'auth_failed'), (404, 'bad_request'),
                                    (429, 'rate_limited'), (500, 'service_error')])
def test_provider_classification_and_safe_body(code, kind):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(code,
        text='SYNTHETIC-private… fragment', headers={'retry-after': '30'})))
    _, outcome = asyncio.run(send(client, 'https://example.org/search', {}, {}, 'SYNTHETIC request', 'keyless', retry_rate_limit=False))
    assert outcome.service_kind == kind
    assert retry_at(outcome.rate_limit['retry-after']) is not None
    assert 'SYNTHETIC-private' not in str(outcome)


@pytest.mark.parametrize('exception,kind', [(httpx.ConnectError, 'network'), (httpx.ReadTimeout, 'timeout')])
def test_provider_transport_failure(exception, kind):
    def handler(request):
        raise exception('SYNTHETIC-private-key', request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _, outcome = asyncio.run(send(client, 'https://example.org/search', {}, {}, 'SYNTHETIC request', 'keyless'))
    assert outcome.service_kind == kind and 'SYNTHETIC-private' not in str(outcome)


@pytest.mark.parametrize('code,kind', [(401, 'auth_failed'), (429, 'quota_exhausted'), (500, 'service_error')])
def test_key_test_does_not_echo_body(code, kind):
    payload = {'error': {'message': 'SYNTHETIC-private…', 'code': 'insufficient_quota' if code == 429 else 'other'}}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(code, json=payload)))
    result = asyncio.run(credentials.test(client, 'OPENAI_API_KEY', 'SYNTHETIC-private-key'))
    assert result['kind'] == kind and result['http_status'] == code
    assert 'SYNTHETIC-private' not in str(result)


# DeepSeek and Gemini keep their earlier behaviour for an unreadable catalogue (D256 changes messages, not control flow).
@pytest.mark.parametrize('connection', ['qwen'])
def test_unreadable_catalogue_is_a_classified_health_failure(monkeypatch, connection):
    monkeypatch.setenv({'deepseek': 'DEEPSEEK_API_KEY', 'gemini': 'GEMINI_API_KEY', 'qwen': 'DASHSCOPE_API_KEY'}[connection], 'SYNTHETIC-private-key')
    monkeypatch.setattr('deixis.models.gemini.shutil.which', lambda command: None)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='not JSON')))
    adapter = {'deepseek': lambda: DeepSeekAdapter(client), 'gemini': lambda: GeminiAdapter(client),
               'qwen': lambda: OpenAICompatAdapter(QWEN, client)}[connection]()
    result = asyncio.run(adapter.health())
    assert result['ready'] is False and result['reason_code'] == 'service_error'


@pytest.mark.parametrize('code,kind,reason', [(400, 'bad_request', 'provider_failed'),
    (401, 'auth_failed', 'provider_auth_required'), (429, 'rate_limited', 'provider_rate_limited')])
def test_provider_pause_and_search_view_retain_class_and_retry_time(tmp_path, code, kind, reason):
    with TestClient(app_for(tmp_path, http_status=code)) as client:
        session(client)
        rid = create(client, providers=['openalex'])
        run_id = client.post(f'/api/researches/{rid}/runs', json={'kind': 'discovery'}).json()['id']
        view, run = wait_run(client, rid, run_id)
        assert run['pause_reason'] == reason and run['error']['service_kind'] == kind
        # Academic routing may select arXiv too; verify the recorded failing
        # service against its own request, rather than assuming dispatch order.
        search = next(row for row in view['search_runs'] if row['provider'] == run['error']['provider'])
        assert run['error']['reset_at'] and search['error']['service_kind'] == kind
        assert search['error']['retries'] == 0


def test_model_wait_event_and_view_use_existing_connection(tmp_path):
    app = app_for(tmp_path, FakeAdapter(ready=False))
    with TestClient(app) as client:
        session(client)
        rid = create(client)
        run_id = client.post(f'/api/researches/{rid}/runs', json={'kind': 'discovery'}).json()['id']
        wait_run(client, rid, run_id)
        store = app.state.store
        # Test the synchronous writer and reader without a live retry or model.
        store.service_waiting(run_id, 'fake', 1, 1.5)
        assert not store.conn.in_transaction
        view = client.get(f'/api/researches/{rid}').json()
        run = next(row for row in view['runs'] if row['id'] == run_id)
        assert run['service_wait'] == {'connection': 'fake', 'attempt': 1, 'seconds': 1.5, 'service_kind': 'rate_limited'}


def test_model_quota_pause_preserves_metadata_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC-private-key')
    adapter = FakeAdapter(fail=lambda si: ModelStepResult('failed', error='SYNTHETIC-private-key quota',
        error_kind='quota_exhausted', http_status=429, retry_after='120'))
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = create(client)
        run_id = client.post(f'/api/researches/{rid}/runs', json={'kind': 'discovery'}).json()['id']
        view, run = wait_run(client, rid, run_id)
        assert (run['status'], run['pause_reason']) == ('paused', 'model_call_failed')
        assert run['error']['error_kind'] == 'quota_exhausted' and run['error']['http_status'] == 429
        assert run['error']['connection'] == 'fake' and run['error']['requested_model'] == 'fake-model'
        assert datetime.fromisoformat(run['error']['reset_at']).tzinfo is not None
        assert 'SYNTHETIC-private-key' not in str(view)
        for row in app.state.store.conn.execute('SELECT error_json FROM run_steps'):
            assert 'SYNTHETIC-private-key' not in str(row[0])


def test_every_service_code_has_english_and_turkish_text():
    root = Path(__file__).resolve().parents[2]
    labels = (root / 'apps/web/src/labels.ts').read_text()
    block = labels.split('export const serviceErrors:', 1)[1].split('\n}', 1)[0]
    messages = dict(re.findall(r"^  (\w+): '([^']+)',", block, re.M))
    assert set(messages) == SERVICE_ERROR_KINDS
    translations = (root / 'apps/web/src/i18n.ts').read_text()
    keys = set(re.findall(r"^  '((?:[^'\\]|\\.)*)':", translations, re.M))
    assert set(messages.values()) <= keys
    # Recovery and effect text needs both languages too.
    error_labels = labels.split('export const serviceErrors:', 1)[1].split('const recoveryReasons:', 1)[0]
    assert set(re.findall(r"\bt\('([^']+)'", error_labels)) <= keys


def test_rendered_labels_cover_legacy_unknown_times_and_effects():
    root = Path(__file__).resolve().parents[2]
    script = r"""
const fs = require('fs'), ts = require('typescript'), assert = require('assert');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, file);
const labels = require('./src/labels.ts'), i18n = require('./src/i18n.ts');
for (const language of ['en', 'tr']) {
  i18n.setUiLanguage(language);
  for (const kind of Object.keys(labels.serviceErrors)) {
    const sentence = labels.serviceErrorSentence({ kind, service: 'SYNTHETIC', effect: 'paused' });
    assert(sentence.includes('SYNTHETIC'));
    assert(!sentence.includes('{service}'));
  }
  const legacy = labels.pauseDetailText({ pause_reason: 'model_call_failed', error: { error: 'SYNTHETIC-private-key' } });
  assert(legacy.length > 0 && !legacy.join(' ').includes('SYNTHETIC-private-key'));
  assert(!labels.pauseReasonText('SYNTHETIC_unrecognized').includes('SYNTHETIC_unrecognized'));
  const unknown = labels.serviceErrorText({ kind: 'SYNTHETIC_unrecognized', service: 'OpenAlex', resetAt: 'garbage', effect: 'continued' });
  assert(!unknown.what.includes('unrecognized') && !unknown.when.includes('Invalid Date'));
  assert(!/paused|duraklatıldı/.test(unknown.next));
  const quota = labels.serviceErrorText({ kind: 'quota_exhausted', service: 'OpenAlex', resetAt: '2026-10-09T01:00:00Z', effect: 'paused' });
  assert(/not guaranteed|kesin değil/.test(quota.when));
}
"""
    result = subprocess.run(['node', '-e', script], cwd=root / 'apps/web', capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


GEMINI_INVALID_KEY = {'error': {'code': 400, 'message': 'API key not valid. Please pass a valid API key.', 'status': 'INVALID_ARGUMENT',
                                'details': [{'reason': 'API_KEY_INVALID', 'domain': 'googleapis.com'}]}}


def test_invalid_gemini_key_is_an_auth_failure_not_a_bad_request():
    assert service_error_kind(400, payload=GEMINI_INVALID_KEY, surface='model') == 'auth_failed'
    assert service_error_kind(400, payload={'error': {'message': 'Invalid value at contents'}}, surface='model') == 'bad_request'


def test_key_test_rejection_is_an_auth_failure():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(400, json=GEMINI_INVALID_KEY)))
    result = asyncio.run(credentials.test(client, 'GEMINI_API_KEY', 'SYNTHETIC-private-key'))
    assert (result['status'], result['kind']) == ('rejected', 'auth_failed')

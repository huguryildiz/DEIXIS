"""The Test on a keyless source's Settings sheet (P5): one request without a key, reported as answered or not.

Every provider is a mocked httpx transport. These show what DEIXIS sends and how it reports the reply, not that the
real services answer.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers import keyless_check, registry
from deixis.providers.pacing import SerialRequestPacer
from fakes import FakeAdapter

EMAIL = "someone@synthetic.example"
KEY_ENVS = {c.key_env for c in registry.CONNECTORS.values() if c.key_env}


class Recorder:
    def __init__(self, reply=lambda request: httpx.Response(200, json={})):
        self.requests: list[httpx.Request] = []
        self.reply = reply

    def __call__(self, request):
        self.requests.append(request)
        return self.reply(request)


@pytest.fixture(autouse=True)
def no_source_keys(monkeypatch):
    for env in KEY_ENVS | {"DEIXIS_CONTACT_EMAIL"}:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(keyless_check, "SEMANTIC_SCHOLAR_PACER", SerialRequestPacer(0.0))


def make_client(tmp_path, recorder):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


@pytest.mark.parametrize("provider_id", ["openalex"])
def test_one_request_without_a_key_carries_the_contact_email(tmp_path, provider_id):
    recorder = Recorder()
    client = make_client(tmp_path, recorder)
    try:
        assert client.put("/api/contact-email", json={"email": EMAIL}).status_code == 200
        result = client.post(f"/api/providers/{provider_id}/test").json()
    finally:
        client.__exit__(None, None, None)
    assert len(recorder.requests) == 1
    sent = recorder.requests[0]
    assert str(sent.url).startswith(keyless_check.REQUESTS[provider_id][0])
    assert f"mailto:{EMAIL}" in sent.headers["user-agent"]
    assert not {"api_key", "api-key", "apikey", "key"} & set(sent.url.params)
    assert not {"x-api-key", "authorization"} & set(sent.headers)
    expected_param = {"openalex": "mailto", "biorxiv": "mailto", "crossref": "mailto", "pubmed": "email"}.get(provider_id)
    if expected_param:
        assert sent.url.params[expected_param] == EMAIL
    assert result["answered"] is True and result["http_status"] == 200 and result["failure"] is None
    assert result["contact_email_sent"] is True and result["provider"] == provider_id and result["checked_at"]


@pytest.mark.parametrize("exc, failure", [(httpx.ReadTimeout, "timeout")])
def test_no_reply_is_reported_as_not_answered_with_the_reason(tmp_path, exc, failure):
    def refuse(request):
        raise exc("SYNTHETIC failure", request=request)
    recorder = Recorder(refuse)
    client = make_client(tmp_path, recorder)
    try:
        result = client.post("/api/providers/crossref/test").json()
    finally:
        client.__exit__(None, None, None)
    assert len(recorder.requests) == 1  # no retry
    assert result["answered"] is False and result["http_status"] is None and result["failure"] == failure
    assert result["error"] == exc.__name__ and result["timeout_seconds"] == keyless_check.TIMEOUT_SECONDS

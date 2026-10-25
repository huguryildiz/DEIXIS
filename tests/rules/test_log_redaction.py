"""A key that travels in a URL query is not written to a log line (E27).

The requests are mocked httpx transports and the key is a made-up string. They show that DEIXIS's own record factory
removes it from httpx's and the app's log records and from logged tracebacks; they do not read any real log file or
the diagnostic bundle (none is built yet; P10g must pass its text through `log_redaction.redact`).
"""

import asyncio
import logging

import httpx
import pytest

from deixis.keys import credentials, log_redaction
from deixis.api import usage_routes

SECRET = "SYNTHETICkey0123456789abcdef"


@pytest.fixture(autouse=True)
def installed():
    log_redaction.install()


@pytest.mark.parametrize("text,expected", [
    (f"GET https://api.openalex.org/rate-limit?api_key={SECRET}", "GET https://api.openalex.org/rate-limit?api_key=<redacted>"),
    ("https://api.openalex.org/works?mailto=me@example.org&per_page=1", "https://api.openalex.org/works?mailto=me@example.org&per_page=1"),
])
def test_redact_replaces_only_secret_query_values(text, expected):
    assert log_redaction.redact(text) == expected


def logged_requests(caplog, run):
    caplog.set_level(logging.DEBUG)
    for name in ("httpx", "httpcore", "deixis"):
        caplog.set_level(logging.DEBUG, logger=name)

    def handler(request: httpx.Request) -> httpx.Response:
        assert SECRET in str(request.url)  # the key really travels in the URL; only the log line is cleaned
        return httpx.Response(200, json={"rate_limit": {}})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await run(client)
    asyncio.run(go())


def test_openalex_budget_request_leaves_no_key_in_the_logs(caplog):
    logged_requests(caplog, lambda client: usage_routes.read_live(client, SECRET))
    assert "HTTP Request: GET" in caplog.text and "api_key=<redacted>" in caplog.text  # the line was logged, cleaned
    assert SECRET not in caplog.text
    assert all(SECRET not in record.getMessage() and SECRET not in str(record.args) for record in caplog.records)


@pytest.mark.parametrize("env,param", [("NCBI_API_KEY", "api_key")])
def test_key_test_requests_leave_no_key_in_the_logs(caplog, env, param):
    logged_requests(caplog, lambda client: credentials.test(client, env, SECRET))
    assert f"{param}=<redacted>" in caplog.text
    assert SECRET not in caplog.text


def test_a_logged_http_error_traceback_leaves_no_key(caplog):
    async def run(client):
        response = await client.get("https://api.openalex.org/works", params={"api_key": SECRET})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logging.getLogger("deixis.test").exception("source call failed")

    def handler(request):
        return httpx.Response(401, request=request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await run(client)
    caplog.set_level(logging.DEBUG)
    asyncio.run(go())
    assert "source call failed" in caplog.text and "401" in caplog.text
    assert SECRET not in caplog.text
    assert all(SECRET not in (record.exc_text or "") for record in caplog.records)


def test_the_app_installs_the_redaction_at_start(tmp_path, monkeypatch):
    monkeypatch.setattr(logging, "_logRecordFactory", logging.LogRecord)  # a plain factory, as if nothing had installed it
    from deixis.api.app import create_app
    from deixis.config import Settings
    from fakes import FakeAdapter
    create_app(Settings(data_dir=tmp_path / "data"), adapters={"fake": FakeAdapter()})
    assert getattr(logging.getLogRecordFactory(), "redacts_keys", False)



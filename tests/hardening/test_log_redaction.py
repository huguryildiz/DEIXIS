"""A key that travels in a URL query is not written to a log line (E27).

The requests are mocked httpx transports and the key is a made-up string. They show that DEIXIS's own record factory
removes it from httpx's and the app's log records and from logged tracebacks; they do not read any real log file or
the diagnostic bundle (none is built yet; P10g must pass its text through `log_redaction.redact`).
"""

import asyncio
import logging

import httpx
import pytest

from deixis import credentials, log_redaction
from deixis.api import usage_routes

SECRET = "SYNTHETICkey0123456789abcdef"


@pytest.fixture(autouse=True)
def installed():
    log_redaction.install()


@pytest.mark.parametrize("text,expected", [
    (f"GET https://api.openalex.org/rate-limit?api_key={SECRET}", "GET https://api.openalex.org/rate-limit?api_key=<redacted>"),
    (f"https://ieeexploreapi.ieee.org/api/v1/search/articles?querytext=test&apikey={SECRET}&format=json",
     "https://ieeexploreapi.ieee.org/api/v1/search/articles?querytext=test&apikey=<redacted>&format=json"),
    (f"https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&API_KEY={SECRET}#frag", "https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&API_KEY=<redacted>#frag"),
    (f"for url 'https://serpapi.com/search?q=a&api-key={SECRET}'", "for url 'https://serpapi.com/search?q=a&api-key=<redacted>'"),
    ("https://api.openalex.org/works?mailto=me@example.org&per_page=1", "https://api.openalex.org/works?mailto=me@example.org&per_page=1"),
    ("api_key is not set", "api_key is not set"),
])
def test_redact_replaces_only_secret_query_values(text, expected):
    assert log_redaction.redact(text) == expected


def test_install_is_idempotent():
    factory = logging.getLogRecordFactory()
    log_redaction.install()
    assert logging.getLogRecordFactory() is factory


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


@pytest.mark.parametrize("env,param", [("NCBI_API_KEY", "api_key"), ("IEEE_API_KEY", "apikey"), ("SERPAPI_API_KEY", "api_key")])
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


def logged_through(formatter, level=logging.INFO):
    """What `formatter` writes for an access-style record whose path carries a key, through a real handler."""
    import io
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger("deixis.test.access")
    logger.setLevel(level)
    logger.addHandler(handler)
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", f"/api/x?api_key={SECRET}&q=1", "1.1", 200)
    finally:
        logger.removeHandler(handler)
    return stream.getvalue()


def test_a_masked_access_record_keeps_its_arguments_for_uvicorns_formatter():
    from uvicorn.logging import AccessFormatter

    written = logged_through(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    assert written.strip() == '127.0.0.1:50000 - "GET /api/x?api_key=<redacted>&q=1 HTTP/1.1" 200 OK'  # not lost to a TypeError
    plain = logged_through(logging.Formatter("%(message)s"))
    assert plain.strip() == '127.0.0.1:50000 - "GET /api/x?api_key=<redacted>&q=1 HTTP/1.1" 200'
    assert SECRET not in written + plain


def test_masking_keeps_the_tuple_shape_and_a_url_object_argument():
    log = logging.getLogger("deixis.test.shape")
    log.setLevel(logging.INFO)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    log.addHandler(handler)
    try:
        log.info('HTTP Request: %s %s "%s %d %s"', "GET", httpx.URL(f"https://x.org/a?api_key={SECRET}"), "HTTP/1.1", 200, "OK")
        log.info("one %(url)s", {"url": f"https://x.org/a?apikey={SECRET}"})
    finally:
        log.removeHandler(handler)
    assert isinstance(records[0].args, tuple) and len(records[0].args) == 5 and records[0].args[3] == 200
    assert records[0].getMessage() == 'HTTP Request: GET https://x.org/a?api_key=<redacted> "HTTP/1.1 200 OK"'
    assert records[1].getMessage() == "one https://x.org/a?apikey=<redacted>"
    assert SECRET not in str(records[0].__dict__) + str(records[1].__dict__)

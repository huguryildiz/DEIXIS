"""P9 H3 fault injection, documents and storage half: unreadable PDFs, refused uploads, refused downloads, a missing
file, a full / busy / damaged library in a request, and a worker that must outlive a database error.

Model-free and socket-free: every PDF fetch is a mock, the model is the test-only FakeAdapter. What passes here shows
that DEIXIS answers each fault with one sentence and a code and keeps running; it does not show behavior on a real
full disk (the process tests do that) or on a volume other than the one pytest runs on.
"""

import asyncio
import errno
import logging
import sqlite3
import subprocess
import time
from contextlib import contextmanager

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from deixis.api import app as app_module
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import fetch as fetch_module
from deixis.documents import pdf
from deixis.documents.fetch import FetchResult
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from fakes import FakeAdapter
from helpers import make_pdf
from test_api_flow import app_for, create, include_sources, openalex_client, session, sw_settings, wait_run

PASSWORD = "password-protected PDF"
NO_PAGES = "PDF has no pages"
UNREADABLE = "PDF could not be read"


# ---- builders ---------------------------------------------------------------------------------------------------

def encrypted_pdf(user_pw: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "SYNTHETIC page one: a sentence with enough words to be text.")
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw="owner-secret")


ZERO_PAGES = make_pdf([])  # raw bytes with a catalog and an empty page tree (/Kids [] /Count 0)
TRUNCATED = make_pdf(["SYNTHETIC hello world"] * 3)[:100]  # cut inside the first object; MuPDF cannot repair it
JUNK_AFTER_HEADER = b"%PDF-1.4\n" + b"garbage " * 60  # passes the upload route's header check, is not a document


def write(tmp_path, data: bytes, name="doc.pdf"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


@contextmanager
def uploaded(tmp_path, data: bytes):
    """Upload `data` through the route; yields (client, research id, the research view the upload answered with)."""
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("doc.pdf", data, "application/pdf")})
        assert response.status_code == 201, response.text
        yield client, rid, response.json()


def asset_of(view):
    return view["sources"][0]["access"]["assets"][0]


# ---- D1 to D5: PDF classes ---------------------------------------------------------------------------------------

def test_d1_encrypted_pdf_fails_with_the_password_reason(tmp_path):
    """D1: a PDF that needs a user password is `failed` / "password-protected PDF", not `no_text`, and the research view says so."""
    data = encrypted_pdf("user-secret")
    result = pdf.extract_pdf(write(tmp_path, data))
    assert (result.status, result.error, result.page_count, result.pages) == ("failed", PASSWORD, 0, [])
    with uploaded(tmp_path / "app", data) as (client, rid, view):
        asset = asset_of(view)
        assert (asset["extraction_status"], asset["extraction_error"]) == ("failed", PASSWORD)
        assert asset_of(client.get(f"/api/researches/{rid}").json())["extraction_error"] == PASSWORD


def test_d1_owner_password_only_pdf_stays_succeeded(tmp_path):
    """D1: a PDF with only an owner password opens without one and is read as before."""
    result = pdf.extract_pdf(write(tmp_path, encrypted_pdf("")))
    assert (result.status, result.error, result.page_count) == ("succeeded", None, 1)
    assert "SYNTHETIC page one" in result.pages[0].text


def test_d2_zero_page_pdf_fails_with_the_no_pages_reason(tmp_path):
    """D2: a PDF whose page tree is empty is `failed` / "PDF has no pages" (it used to be `no_text`, 0 pages)."""
    result = pdf.extract_pdf(write(tmp_path, ZERO_PAGES))
    assert (result.status, result.error, result.page_count, result.pages) == ("failed", NO_PAGES, 0, [])
    with uploaded(tmp_path / "app", ZERO_PAGES) as (client, rid, view):
        asset = asset_of(view)
        assert (asset["extraction_status"], asset["extraction_error"]) == ("failed", NO_PAGES)
        assert asset_of(client.get(f"/api/researches/{rid}").json())["extraction_error"] == NO_PAGES


def test_d3_pdf_above_the_page_limit_is_partial_with_400_pages_read(tmp_path):
    """D3: 450 pages: status `partial`, page_count is the real 450, only MAX_PAGES (400) are read."""
    result = pdf.extract_pdf(write(tmp_path, make_pdf([f"SYNTHETIC page {i}" for i in range(450)])))
    assert pdf.MAX_PAGES == 400
    assert (result.status, result.page_count, len(result.pages), result.error) == ("partial", 450, 400, None)
    assert result.pages[-1].physical_page == 400


@pytest.mark.parametrize("data", [TRUNCATED, JUNK_AFTER_HEADER, b"%PDF-1.4\n"], ids=["cut-at-100-bytes", "junk-after-header", "header-only"])
def test_d4_corrupt_or_truncated_pdf_says_it_could_not_be_read(tmp_path, data):
    """D4: a file MuPDF cannot open is `failed` with one fixed sentence, never the MuPDF traceback tail."""
    result = pdf.extract_pdf(write(tmp_path, data))
    assert (result.status, result.error, result.page_count) == ("failed", UNREADABLE, 0)
    assert "Traceback" not in result.error and "\n" not in result.error
    with uploaded(tmp_path / "app", data) as (client, rid, view):
        asset = asset_of(view)
        assert (asset["extraction_status"], asset["extraction_error"]) == ("failed", UNREADABLE)
        assert asset_of(client.get(f"/api/researches/{rid}").json())["extraction_error"] == UNREADABLE


def test_d4_a_crashed_pdf_child_says_it_could_not_be_read_and_keeps_stderr_in_the_log(tmp_path, monkeypatch, caplog):
    """D4: the child exits non-zero: `failed` with the fixed sentence; its stderr tail goes to the log, never to `error`."""
    stderr = b"Traceback (most recent call last): boom in secret/path/doc.pdf"

    def crashed(argv, env, timeout, max_memory):
        return subprocess.CompletedProcess(argv, 1, b"", stderr)

    monkeypatch.setattr(pdf, "_run_watched", crashed)
    with caplog.at_level(logging.WARNING, logger=pdf.log.name):
        result = pdf.extract_pdf(write(tmp_path, make_pdf(["SYNTHETIC page"])))
    assert (result.status, result.error, result.page_count) == ("failed", UNREADABLE, 0)
    assert "secret/path" not in result.error and "Traceback" not in result.error
    assert "secret/path" in caplog.text


def test_d5_non_pdf_bytes_are_refused_by_the_upload_routes_and_by_the_downloader(tmp_path, monkeypatch):
    """D5: the upload route answers 422 with the sentence and code; the same helper serves the per-source upload; fetched
    HTML is `not_pdf`; bytes that start like a PDF but are not one are accepted by the route and stored as `failed`."""
    html = b"<html><body>This is not a PDF.</body></html>"
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("page.pdf", html, "application/pdf")})
        assert response.status_code == 422
        assert response.json() == {"detail": "Only PDF files are supported", "code": "upload_not_pdf"}
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []
        assert not list((tmp_path / "data" / "papers").glob("*"))  # the refused file leaves no residue
        svid = client.post(f"/api/researches/{rid}/uploads", files={"file": ("ok.pdf", make_pdf(["SYNTHETIC ok"]), "application/pdf")}
                           ).json()["uploaded_source_version_id"]
        response = client.post(f"/api/researches/{rid}/sources/{svid}/uploads", files={"file": ("page.pdf", html, "application/pdf")})
        assert response.status_code == 422
        assert response.json() == {"detail": "Only PDF files are supported", "code": "upload_not_pdf"}

    async def html_answer(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html)

    async def resolved(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(fetch_module, "_resolve", resolved)
    client = httpx.AsyncClient(transport=httpx.MockTransport(html_answer))
    result = asyncio.run(fetch_module.fetch_pdf("http://papers.example/x.pdf", client))
    assert (result.status, result.media_type, result.data) == ("not_pdf", "text/html", b"")


# ---- D6, D7, D8: size limits and blocked links -----------------------------------------------------------------

def test_d6_upload_over_the_limit_says_so_with_a_code(tmp_path, monkeypatch):
    """D6: both 413 paths (declared length, and counted while reading) answer the sentence and `upload_too_large`."""
    assert app_module.MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 10_000)
    expected = {"detail": "PDF larger than 50 MB", "code": "upload_too_large"}
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        declared = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "big.pdf", make_pdf(["SYNTHETIC"]) + b"%" * 100_000, "application/pdf")})
        assert (declared.status_code, declared.json()) == (413, expected)  # refused by the guard, body not read
        counted = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "big.pdf", make_pdf(["SYNTHETIC"]) + b"%" * 20_000, "application/pdf")})
        assert (counted.status_code, counted.json()) == (413, expected)  # refused by store_upload while reading
        assert not list((tmp_path / "data" / "papers").glob("*"))


def test_d6_upload_without_a_declared_size_is_refused_with_411(tmp_path):
    """D6: a chunked body declares no Content-Length; the guard answers 411 "Upload size must be declared" and a code."""
    boundary = "deixisboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.pdf\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + make_pdf(["SYNTHETIC"]) + f"\r\n--{boundary}--\r\n".encode()

    def chunks():
        for start in range(0, len(body), 200):
            yield body[start:start + 200]

    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", content=chunks(),
                               headers={"content-type": f"multipart/form-data; boundary={boundary}"})
        assert "content-length" not in response.request.headers and response.request.headers["transfer-encoding"] == "chunked"
        assert (response.status_code, response.json()) == (
            411, {"detail": "Upload size must be declared", "code": "upload_size_undeclared"})
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []


def fetch_with(handler, monkeypatch, url="http://papers.example/big.pdf"):
    async def resolved(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(fetch_module, "_resolve", resolved)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return asyncio.run(fetch_module.fetch_pdf(url, client))


def test_d7_download_over_the_limit_is_too_large_by_declared_length_and_by_stream(tmp_path, monkeypatch):
    """D7: `fetch_pdf` stops at 30 MiB on both branches: a declared Content-Length (body never read) and an undeclared
    stream that passes the limit."""
    limit = fetch_module.MAX_BYTES
    assert limit == 30 * 1024 * 1024
    read = []

    async def never_read():
        read.append(True)
        yield b"%PDF-1.4"

    declared = fetch_with(lambda request: httpx.Response(
        200, headers={"content-length": str(limit + 1), "content-type": "application/pdf"}, content=never_read()), monkeypatch)
    assert (declared.status, declared.http_status, declared.data) == ("too_large", 200, b"")
    assert read == []  # the declared branch refuses before the first byte

    streamed_chunks = []

    async def stream():
        yield b"%PDF-1.4\n"
        for _ in range(31):
            streamed_chunks.append(1)
            yield b"\0" * (1024 * 1024)

    response = httpx.Response(200, headers={"content-type": "application/pdf"}, content=stream())
    assert "content-length" not in response.headers  # an iterator body declares no length
    undeclared = fetch_with(lambda request: httpx.Response(
        200, headers={"content-type": "application/pdf"}, content=stream()), monkeypatch)
    assert (undeclared.status, undeclared.http_status, undeclared.data) == ("too_large", 200, b"")
    assert 30 <= len(streamed_chunks) <= 31  # read until the limit was passed, not to the end


def flow_with_fetch_result(tmp_path, result_of):
    """An answer run over the two OpenAlex works that carry a PDF link, where the fetcher answers `result_of(url)`."""
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        return result_of(url)

    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()}, http_client=openalex_client(), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        discovered, _ = wait_run(client, rid, discovery["id"])
        include_sources(client, rid, discovered)
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer["id"])
        steps = [s for s in run["steps"] if s["kind"] == "fetch_pdf"]
        assets = app.state.store.conn.execute("SELECT COUNT(*) FROM source_assets").fetchone()[0]
    return fetched, steps, assets, (tmp_path / "data" / "papers")


def test_d7_a_too_large_link_is_stored_as_fetch_too_large_and_leaves_nothing(tmp_path):
    """D7: at flow level the step is `failed` / `fetch_too_large`, with no `source_assets` row and an empty `papers/`."""
    fetched, steps, assets, papers = flow_with_fetch_result(
        tmp_path, lambda url: FetchResult("too_large", final_url=url, http_status=200))
    assert fetched and len(steps) == len(fetched)
    assert {(s["status"], s["error_code"]) for s in steps} == {("failed", "fetch_too_large")}
    assert assets == 0
    assert not papers.exists() or not list(papers.glob("*"))


def test_d8_a_blocked_link_is_stored_as_fetch_blocked_url(tmp_path):
    """D8: the flow stores the downloader's `blocked_url` as `fetch_blocked_url` and keeps nothing."""
    fetched, steps, assets, papers = flow_with_fetch_result(
        tmp_path, lambda url: FetchResult("blocked_url", final_url=url, error="10.0.0.5 resolves to non-public address"))
    assert fetched and {(s["status"], s["error_code"]) for s in steps} == {("failed", "fetch_blocked_url")}
    assert assets == 0
    assert not papers.exists() or not list(papers.glob("*"))


# ---- D10: the stored file is gone --------------------------------------------------------------------------------

def test_d10_a_missing_pdf_file_answers_404_file_missing_but_the_text_is_still_served(tmp_path):
    """D10: with the PDF deleted from `papers/`, the asset, its figures and a re-extract answer 404 "File missing";
    the passage text, which is stored in the library, still answers."""
    with uploaded(tmp_path, make_pdf(["SYNTHETIC page one: molecule release schedule minimizes error."])) as (client, rid, view):
        source = view["sources"][0]
        asset = asset_of(view)
        base = f"/api/researches/{rid}/assets/{asset['id']}"
        assert client.get(base).status_code == 200
        for stored in (tmp_path / "data" / "papers").glob("*.pdf"):
            stored.unlink()
        assert not list((tmp_path / "data" / "papers").glob("*.pdf"))
        text = client.get(f"{base}/text")
        assert text.status_code == 200 and "molecule release" in text.json()["passages"][0]["text"]
        # Without an older extraction version the re-extract route answers "unchanged" before it looks at the file.
        client.app.state.store.conn.execute("UPDATE source_assets SET extraction_version = 'pymupdf-0.0-old' WHERE id = ?", (asset["id"],))
        for response in (client.get(base), client.get(f"{base}/figures"),
                         client.post(f"/api/researches/{rid}/sources/{source['source_version_id']}/assets/{asset['id']}/extractions")):
            assert (response.status_code, response.json()) == (404, {"detail": "File missing"}), response.request.url


# ---- O1, O12: a full, busy, read-only or damaged library in a request -----------------------------------------------

def make_full(conn: sqlite3.Connection) -> None:
    """Stop this connection's database from growing: any write that needs a new page now fails with SQLITE_FULL."""
    conn.execute(f"PRAGMA max_page_count = {conn.execute('PRAGMA page_count').fetchone()[0]}")


def test_o12_a_full_database_raises_sqlite_full_inside_db_transaction_not_cannot_rollback(tmp_path):
    """O12: SQLite has already rolled back after SQLITE_FULL, so `db.transaction` must not roll back again: the error
    that surfaces is the real one (primary code 13), the connection is out of the transaction, and it works afterwards."""
    conn = db.connect(tmp_path / "small.sqlite")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, blob BLOB)")
    conn.execute("INSERT INTO t (blob) VALUES (zeroblob(100))")
    make_full(conn)
    with pytest.raises(sqlite3.OperationalError) as caught:
        with db.transaction(conn):
            conn.execute("INSERT INTO t (blob) VALUES (zeroblob(200000))")
    assert caught.value.sqlite_errorcode & 0xFF == 13
    assert "cannot rollback" not in str(caught.value) and "full" in str(caught.value)
    assert not conn.in_transaction
    assert db.describe_failure(caught.value)[:2] == ("disk_full", 507)
    conn.execute("PRAGMA max_page_count = 1073741823")
    with db.transaction(conn):
        conn.execute("INSERT INTO t (blob) VALUES (zeroblob(200000))")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    conn.close()


def test_o12_a_route_over_a_full_database_answers_507_disk_full_and_recovers(tmp_path):
    """O12: a real SQLITE_FULL from `add_asset_with_pages` becomes 507 {"detail": sentence, "code": "disk_full"}, with
    no exception text in the body; once the limit is lifted the same upload succeeds."""
    app = app_for(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        session(client)
        rid = create(client, source_scope="attached")
        big = make_pdf([f"SYNTHETIC page {i}: " + "molecule release schedule words " * 40 for i in range(40)])
        make_full(app.state.store.conn)
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("big.pdf", big, "application/pdf")})
        assert response.status_code == 507
        assert response.json() == {"detail": "DEIXIS could not save because the disk is full. Free some space and try again.",
                                   "code": "disk_full"}
        assert "sqlite" not in response.text.lower() and str(tmp_path) not in response.text
        assert client.get("/api/health").status_code == 200
        app.state.store.conn.execute("PRAGMA max_page_count = 1073741823")
        assert client.post(f"/api/researches/{rid}/uploads", files={"file": ("big.pdf", big, "application/pdf")}).status_code == 201


def test_o1_a_locked_database_answers_503_database_busy(tmp_path):
    """O1: a second connection holds the write lock; the app's write times out (50 ms here, 30 s in production) with
    SQLITE_BUSY and the person gets "another process is using the library", not a bare 500."""
    app = app_for(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        session(client)
        app.state.store.conn.execute("PRAGMA busy_timeout = 50")
        other = sqlite3.connect(tmp_path / "data" / "library.sqlite", isolation_level=None)
        other.execute("BEGIN IMMEDIATE")
        try:
            response = client.post("/api/researches", json={"question": "How is molecule release scheduling optimized?",
                                                            "model_connection": "fake", "requested_model": "fake-model",
                                                            "effort": "quick"})
        finally:
            other.execute("ROLLBACK")
            other.close()
        assert response.status_code == 503
        assert response.json() == {"detail": "DEIXIS could not save because another process is using the library. Try again in a moment.",
                                   "code": "database_busy"}
        assert client.get("/api/researches").status_code == 200  # reads and later writes are unaffected
        assert create(client)


def test_o1_an_unrelated_database_error_is_still_a_500(tmp_path):
    """O1: only the named failures are rewritten; a code bug (no such table) is re-raised and ends as the 500 it is."""
    app = app_for(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        session(client)
        app.state.store.conn.execute("PRAGMA foreign_keys = OFF")
        app.state.store.conn.execute("DROP TABLE researches")
        response = client.get("/api/researches")
        assert response.status_code == 500 and "disk_full" not in response.text and "database_" not in response.text


def test_o12_enospc_while_storing_an_upload_answers_507_and_leaves_no_partial_file(tmp_path, monkeypatch):
    """O12: ENOSPC from the file write (`os.replace` here, after the bytes are written) is `DiskFull`, so 507, and the
    temporary `.partial` file is removed."""
    real_os = app_module.os

    class FullOs:
        def __getattr__(self, name):
            return getattr(real_os, name)

        def replace(self, *_):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("deixis.workflow.file_restore.os", FullOs())  # only this module's view of `os`
    with TestClient(app_for(tmp_path), raise_server_exceptions=False) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")})
        assert (response.status_code, response.json()["code"]) == (507, "disk_full")
        assert "No space" not in response.text
        papers = tmp_path / "data" / "papers"
        assert papers.exists() and not list(papers.iterdir())
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []


def test_o12_enospc_when_the_partial_file_cannot_be_created_answers_507_and_papers_stays_empty(tmp_path, monkeypatch):
    """O12: `mkstemp` itself fails on a full disk; the upload is `DiskFull`, so 507, and no `.partial` file exists."""
    real_mkstemp = app_module.tempfile.mkstemp

    def full(*args, **kwargs):
        if kwargs.get("suffix") == ".partial":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(app_module.tempfile, "mkstemp", full)
    with TestClient(app_for(tmp_path), raise_server_exceptions=False) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")})
        assert (response.status_code, response.json()["code"]) == (507, "disk_full")
        assert "No space" not in response.text
        papers = tmp_path / "data" / "papers"
        assert papers.is_dir() and not list(papers.iterdir())
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []


def test_o1_describe_failure_names_each_class_and_nothing_else():
    """O1/O12: the classifier. Codes 8, 11 and 26 cannot be produced portably, so for them ONLY the exception is built by
    hand and `sqlite_errorcode` set on it (a pure unit test of the mapping); 5, 6 and 13 are also exercised for real above."""
    def error(code, extended=None):
        exc = sqlite3.OperationalError("x")
        exc.sqlite_errorcode = extended or code
        return exc

    expected = {5: ("database_busy", 503), 6: ("database_busy", 503), 8: ("database_readonly", 503),
                11: ("database_damaged", 503), 26: ("database_damaged", 503), 13: ("disk_full", 507)}
    for code, (name, status) in expected.items():
        assert db.describe_failure(error(code))[:2] == (name, status), code
        assert db.describe_failure(error(code, code | (2 << 8)))[:2] == (name, status), code  # extended result code
        sentence = db.describe_failure(error(code))[2]
        assert sentence.startswith("DEIXIS ") and sentence.endswith(".") and "sqlite" not in sentence.lower()
    assert db.describe_failure(OSError(errno.ENOSPC, "x"))[:2] == ("disk_full", 507)
    assert db.describe_failure(OSError(errno.EDQUOT, "x"))[:2] == ("disk_full", 507)
    assert db.describe_failure(OSError(errno.EACCES, "x")) is None
    assert db.describe_failure(error(1)) is None  # SQLITE_ERROR, e.g. "no such table"
    assert db.describe_failure(sqlite3.OperationalError("no code")) is None
    assert db.describe_failure(ValueError("x")) is None


def test_o8_open_problem_names_a_garbage_library_and_changes_nothing(tmp_path):
    """O8 (startup helper): a file that is not a database gives one sentence with the path and "file is not a database";
    the file's bytes are untouched; a missing file is a first run (None)."""
    library = tmp_path / "library.sqlite"
    library.write_bytes(b"this is definitely not a SQLite database " * 200)
    before = library.read_bytes()
    problem = db.open_problem(library)
    assert problem is not None and "\n" not in problem and "Traceback" not in problem
    assert str(library) in problem and "file is not a database" in problem and "did not start" in problem
    assert "stays applied" in problem
    assert library.read_bytes() == before
    assert db.open_problem(tmp_path / "fresh" / "library.sqlite") is None


# ---- Worker ------------------------------------------------------------------------------------------------------

class FakeFlow:
    """What `Worker.run_forever` asks of a flow: a start hook, an end hook and `execute`, scripted per run id."""

    def __init__(self, store, script):
        self.store, self.script, self.executed, self.ended = store, script, [], []

    def queue_person_readings(self):
        pass

    def person_run_ended(self, run_id):
        self.ended.append(run_id)

    async def execute(self, run_id):
        self.executed.append(run_id)
        await self.script(self, run_id)


def worker_library(tmp_path, monkeypatch, runs=1):
    monkeypatch.setattr("deixis.workflow.worker.RETRY_SECONDS", 0.01)
    path = tmp_path / "library.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    conn.execute("PRAGMA busy_timeout = 20")  # a held lock must fail in 20 ms here, not after the production 30 s
    store = Store(conn)
    run_ids = []
    for n in range(runs):
        rid = store.create_research(f"SYNTHETIC worker question {n}", "attached_and_academic", "quick", ["openalex"],
                                    "fake", "fake-model", "en")
        run_ids.append(store.create_run(rid, "answer", {}, None)["id"])
        time.sleep(0.01)  # created_at has millisecond resolution; keep the queue order unambiguous
    return path, store, run_ids


async def until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def locker(path):
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    return other


def release(other):
    other.execute("ROLLBACK")
    other.close()


def complete(flow, run_id):
    flow.store.update_run(run_id, event="run_completed", status="completed")


def test_o12_worker_survives_a_database_error_in_the_heartbeat(tmp_path, monkeypatch, caplog):
    """O12: while another process holds the write lock, the heartbeat fails with SQLITE_BUSY; the loop logs the error once
    (not every turn), keeps going, and runs the queued run when the lock is gone."""
    path, store, (run_id,) = worker_library(tmp_path, monkeypatch)
    caplog.set_level("INFO", logger="deixis.worker")

    async def script(flow, rid):
        complete(flow, rid)

    async def main():
        flow = FakeFlow(store, script)
        worker = Worker(store, flow, tmp_path / "lock")
        other = locker(path)
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.4)
        assert not task.done() and store.run(run_id)["status"] == "queued" and flow.executed == []
        release(other)
        await until(lambda: store.run(run_id)["status"] == "completed")
        assert not task.done()
        await worker.stop()
        await asyncio.wait_for(task, 2)
        assert flow.executed == [run_id]

    asyncio.run(main())
    assert len([r for r in caplog.records if r.getMessage() == "worker turn failed; trying again"]) == 1


def test_o12_worker_keeps_a_failure_it_could_not_write_and_records_disk_full_then_runs_the_next_run(tmp_path, monkeypatch):
    """O12: a run fails with ENOSPC while the library is locked, so recording the failure fails too. The worker stays
    alive with the failure in memory, writes it (`failed`, pause_reason `disk_full`) once the write works, and then runs
    the next queued run."""
    path, store, (first, second) = worker_library(tmp_path, monkeypatch, runs=2)
    held = []

    async def script(flow, rid):
        if rid == first:
            held.append(locker(path))  # the disk "fills": every later write fails until the test releases it
            raise OSError(errno.ENOSPC, "No space left on device")
        complete(flow, rid)

    async def main():
        flow = FakeFlow(store, script)
        worker = Worker(store, flow, tmp_path / "lock")
        task = asyncio.create_task(worker.run_forever())
        await until(lambda: held)
        await asyncio.sleep(0.4)
        assert not task.done()
        assert store.run(first)["status"] == "running"  # the failure could not be written yet
        assert flow.executed == [first] and store.run(second)["status"] == "queued"
        release(held[0])
        await until(lambda: store.run(second)["status"] == "completed")
        failed = store.run(first)
        assert (failed["status"], failed["pause_reason"]) == ("failed", "disk_full")
        assert failed["error"]["error"].startswith("OSError")
        assert flow.executed == [first, second] and flow.ended == [first, second]
        assert not task.done()
        await worker.stop()
        await asyncio.wait_for(task, 2)

    asyncio.run(main())


def test_o12_worker_records_other_failures_as_internal_error(tmp_path, monkeypatch):
    """O12: a failure `describe_failure` does not name keeps `internal_error`, and the next run still starts."""
    path, store, (first, second) = worker_library(tmp_path, monkeypatch, runs=2)

    async def script(flow, rid):
        if rid == first:
            raise RuntimeError("SYNTHETIC code bug")
        complete(flow, rid)

    async def main():
        flow = FakeFlow(store, script)
        worker = Worker(store, flow, tmp_path / "lock")
        task = asyncio.create_task(worker.run_forever())
        await until(lambda: store.run(second)["status"] == "completed")
        failed = store.run(first)
        assert (failed["status"], failed["pause_reason"], failed["error"]) == (
            "failed", "internal_error", {"error": "RuntimeError: SYNTHETIC code bug"})
        await worker.stop()
        await asyncio.wait_for(task, 2)

    asyncio.run(main())


def test_o12_worker_does_not_overwrite_a_run_cancelled_while_its_failure_was_waiting(tmp_path, monkeypatch):
    """O12: the failure of a run could not be written (library locked). A cancel lands before the retry; the retry drops
    the failure, the run stays `cancelled` with no `disk_full` reason, and the next run still starts."""
    path, store, (first, second) = worker_library(tmp_path, monkeypatch, runs=2)
    held = []

    async def script(flow, rid):
        if rid == first:
            held.append(locker(path))
            raise OSError(errno.ENOSPC, "No space left on device")
        complete(flow, rid)

    async def main():
        flow = FakeFlow(store, script)
        worker = Worker(store, flow, tmp_path / "lock")
        task = asyncio.create_task(worker.run_forever())
        await until(lambda: held)
        await asyncio.sleep(0.2)
        assert store.run(first)["status"] == "running"
        release(held[0])
        store.update_run(first, event="run_cancelled", status="cancelled")  # no await between the release and the cancel
        await until(lambda: store.run(second)["status"] == "completed")
        cancelled = store.run(first)
        assert (cancelled["status"], cancelled["pause_reason"]) == ("cancelled", None)
        assert flow.executed == [first, second]
        await worker.stop()
        await asyncio.wait_for(task, 2)

    asyncio.run(main())

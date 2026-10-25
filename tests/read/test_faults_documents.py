"""Hostile and broken documents (F08: encrypted, zero-page, huge, corrupt PDFs and over-limit uploads get a code and a visible reason), and storage faults met while storing them (O8, O12, W1). SYNTHETIC files."""

import asyncio
import errno
import gzip
import logging
import sqlite3
import subprocess
import time
import tracemalloc
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
from test_api_flow import app_for, create, openalex_client, session, wait_run


PASSWORD = "password-protected PDF"


NO_PAGES = "PDF has no pages"


UNREADABLE = "PDF could not be read"


def encrypted_pdf(user_pw: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "SYNTHETIC page one: a sentence with enough words to be text.")
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw="owner-secret")


ZERO_PAGES = make_pdf([])  # raw bytes with a catalog and an empty page tree (/Kids [] /Count 0)


TRUNCATED = make_pdf(["SYNTHETIC hello world"] * 3)[:100]  # cut inside the first object; MuPDF cannot repair it


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


def test_d1_encrypted_pdf_fails_with_the_password_reason(tmp_path):
    """D1: a PDF that needs a user password is `failed` / "password-protected PDF", not `no_text`, and the research view says so."""
    data = encrypted_pdf("user-secret")
    result = pdf.extract_pdf(write(tmp_path, data))
    assert (result.status, result.error, result.page_count, result.pages) == ("failed", PASSWORD, 0, [])
    with uploaded(tmp_path / "app", data) as (client, rid, view):
        asset = asset_of(view)
        assert (asset["extraction_status"], asset["extraction_error"]) == ("failed", PASSWORD)
        assert asset_of(client.get(f"/api/researches/{rid}").json())["extraction_error"] == PASSWORD


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


@pytest.mark.parametrize("data", [TRUNCATED], ids=["cut-at-100-bytes"])
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


def multipart(field: str, filename: str, data: bytes, boundary="deixisboundary") -> bytes:
    return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()


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


def gzipped(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=9)


def encoded(raw: bytes, encoding: str):
    """A handler answering `raw` with this Content-Encoding, streamed in 4 KiB pieces as from a socket (a bytes body
    would be read and decoded by httpx.Response itself, before `fetch_pdf` sees it)."""
    async def pieces():
        for start in range(0, len(raw), 4096):
            yield raw[start:start + 4096]

    return lambda request: httpx.Response(200, headers={
        "content-type": "application/pdf", "content-encoding": encoding, "content-length": str(len(raw))}, content=pieces())


def fetch_peak(raw: bytes, encoding: str, monkeypatch):
    """`fetch_pdf` over a body sent with this Content-Encoding, and the most memory Python held while it ran."""
    tracemalloc.start()
    try:
        result = fetch_with(encoded(raw, encoding), monkeypatch)
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_d7_the_limit_counts_decoded_bytes_and_stops_decoding_at_it(monkeypatch):
    """D7: a small gzip body that inflates far past MAX_BYTES is `too_large`, and decoding stops at the limit instead
    of inflating the whole body first."""
    monkeypatch.setattr(fetch_module, "MAX_BYTES", 64 * 1024)
    raw = gzipped(b"%PDF-1.4\n" + b"\0" * (8 * 1024 * 1024))
    assert len(raw) < 16 * 1024
    result, peak = fetch_peak(raw, "gzip", monkeypatch)
    assert (result.status, result.data) == ("too_large", b"")
    assert peak < 2 * 1024 * 1024  # the 8 MiB the body inflates to was never held


@pytest.mark.parametrize("encoding", ["gzip, gzip"])
def test_d7_a_stacked_or_unknown_content_encoding_is_refused_before_decoding(monkeypatch, encoding):
    """D7: identity and one gzip or deflate layer are read; a stacked or other encoding is refused, never decoded."""
    monkeypatch.setattr(fetch_module, "MAX_BYTES", 64 * 1024)
    raw = gzipped(gzipped(b"%PDF-1.4\n" + b"\0" * (8 * 1024 * 1024)))
    assert len(raw) < 2 * 1024
    result, peak = fetch_peak(raw, encoding, monkeypatch)
    assert (result.status, result.data, result.error) == ("failed", b"", f"content encoding {encoding!r} not accepted")
    assert peak < 2 * 1024 * 1024


@pytest.mark.parametrize("encoding, encode", [("gzip", gzipped)])
def test_d7_an_identity_or_single_layer_pdf_still_arrives_whole(monkeypatch, encoding, encode):
    pdf_bytes = make_pdf(["SYNTHETIC"])
    raw = encode(pdf_bytes) if encode else pdf_bytes
    result = fetch_with(encoded(raw, encoding), monkeypatch)
    assert (result.status, result.data) == ("ok", pdf_bytes)


def flow_with_fetch_result(tmp_path, result_of):
    """A discovery run over the two OpenAlex works that carry a PDF link, where the fetcher answers `result_of(url)`.

    The fast path fetches inside discovery (D251), so full-text fetch is on here; the answer run fetches nothing.
    """
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        return result_of(url)

    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1,
                        search_query="code", fulltext_fetch="auto")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=openalex_client(), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, discovery["id"])
        steps = [s for s in run["steps"] if s["kind"] == "fetch_pdf"]
        assets = app.state.store.conn.execute("SELECT COUNT(*) FROM source_assets").fetchone()[0]
    return fetched, steps, assets, (tmp_path / "data" / "papers")


def test_d8_a_blocked_link_is_stored_as_fetch_blocked_url(tmp_path):
    """D8: the flow stores the downloader's `blocked_url` as `fetch_blocked_url` and keeps nothing."""
    fetched, steps, assets, papers = flow_with_fetch_result(
        tmp_path, lambda url: FetchResult("blocked_url", final_url=url, error="10.0.0.5 resolves to non-public address"))
    assert fetched and {(s["status"], s["error_code"]) for s in steps} == {("failed", "fetch_blocked_url")}
    assert assets == 0
    assert not papers.exists() or not list(papers.glob("*"))


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


def make_full(conn: sqlite3.Connection) -> None:
    """Stop this connection's database from growing: any write that needs a new page now fails with SQLITE_FULL.
    The free pages a table rebuild in a migration leaves are given back first, or a write would fit in them."""
    conn.execute("VACUUM")
    conn.execute(f"PRAGMA max_page_count = {conn.execute('PRAGMA page_count').fetchone()[0]}")


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



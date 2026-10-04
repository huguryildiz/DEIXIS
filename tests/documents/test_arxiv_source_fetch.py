"""Which version a PDF is and fetching its arXiv source (slice 22, D104, decisions 1 and 2).

Requests go to an `httpx.MockTransport` or to a SYNTHETIC local HTTP server on loopback that records when each request
arrives, as the server sees it. The 3 s rule is shown for processes sharing one data directory; other data directories and
DEIXIS's arXiv search are outside it and nothing here says otherwise. No network is used.
"""

import asyncio
import gzip
import http.server
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from arxiv_helpers import LoopbackTransport, fetch_child, make_arxiv_pdf, no_network, source_archive  # noqa: F401
from deixis.documents import arxiv_source as src
from deixis.documents import fetch
from deixis.storage import db
from deixis.workflow.store import Store

KEY = "2101.00001v2"
ARCHIVE = source_archive()


# ---- decision 1 ----------------------------------------------------------------------------------------------------------
def record(**fields):
    return {"doi": "10.48550/arXiv.2101.00001", "landing_url": "https://arxiv.org/abs/2101.00001v2",
            "oa_pdf_url": "https://arxiv.org/pdf/2101.00001v2", "version_label": "arXiv v2"} | fields


def test_the_file_version_comes_from_its_address_and_its_rotated_margin_stamp(tmp_path):
    assert src.url_key("https://arxiv.org/pdf/2101.00001v2") == KEY
    assert src.url_key("https://arxiv.org/pdf/math/0501001v3.pdf") == "math/0501001v3"
    assert src.url_key("https://arxiv.org/abs/2101.00001v2") is None and src.url_key(None) is None
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_arxiv_pdf())
    assert src.stamp_key(path) == KEY
    path.write_bytes(make_arxiv_pdf(stamp=None))
    assert src.stamp_key(path) is None


def test_decision_ones_table_first_matching_row_wins():
    e = src.eligibility
    assert e(KEY, "2101.00001v1", record())["eligibility"] == "version_conflict"
    assert e(None, None, record())["eligibility"] == "no_version"
    assert e(KEY, KEY, record()) == {"eligibility": "eligible", "arxiv_key": KEY, "version_from": "both", "record_label": "arXiv v2"}
    assert e(None, KEY, record())["version_from"] == "stamp" and e(KEY, None, record())["version_from"] == "url"
    assert e(KEY, None, record(doi="10.1109/x.2", landing_url=None, oa_pdf_url=None))["eligibility"] == "record_identity_unknown"
    assert e(KEY, None, record(doi=None, landing_url="https://arxiv.org/abs/2202.00002",
                               oa_pdf_url=None))["eligibility"] == "record_version_conflict"
    assert e(KEY, None, record(landing_url="https://arxiv.org/abs/2202.00002"))["eligibility"] == "record_identity_conflict"
    assert e(KEY, None, record(version_label="arXiv v1"))["eligibility"] == "record_version_conflict"
    assert e(KEY, KEY, record(version_label="publishedVersion"))["eligibility"] == "record_version_conflict"
    assert e(KEY, None, record(version_label=None))["eligibility"] == "record_version_conflict"
    assert e(KEY, None, record(version_label="submittedVersion", doi=None))["eligibility"] == "eligible"


def test_the_response_file_name_must_name_the_version():
    assert src.disposition_names('attachment; filename="arXiv-2101.00001v2.tar.gz"', KEY)
    assert not src.disposition_names('attachment; filename="arXiv-2101.00001v1.tar.gz"', KEY)
    assert not src.disposition_names('attachment; filename="arXiv-2101.00001v21.tar.gz"', KEY)
    assert not src.disposition_names(None, KEY)
    assert src.disposition_names('attachment; filename="arXiv-math0501001v3.gz"', "math/0501001v3")


# ---- decision 2 with a mock transport and a fake clock ------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(src, "clock", fake.time)
    monkeypatch.setattr(src, "sleep", fake.sleep)
    return fake


@pytest.fixture
def public(monkeypatch):
    async def resolve(url):
        return "93.184.216.34"  # a documentation-range public address; the mock transport answers, nothing connects
    monkeypatch.setattr(fetch, "check_public_url", resolve)


def store_at(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def ok(key=KEY, body=ARCHIVE):
    return httpx.Response(200, content=body, headers={"content-type": "application/gzip",
                                                      "content-disposition": f'attachment; filename="arXiv-{key}.tar.gz"'})


def sources_with(tmp_path, handler, seen=None):
    def record_and_answer(request):
        if seen is not None:
            seen.append((src.clock(), str(request.url.path)))
        return handler(request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(record_and_answer))
    return src.SourceStore(store_at(tmp_path), tmp_path / "data", client=client)


def test_a_source_is_fetched_once_stored_through_a_part_file_and_then_read_back(tmp_path, clock, public):
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == "downloaded" and row["attempts"] == 1 and row["content"] is None and len(seen) == 1
    assert seen[0][1] == "/e-print/2101.00001v2" and not list((tmp_path / "data/arxiv-sources").glob("*.part-*"))
    assert asyncio.run(sources.read(KEY)) == (ARCHIVE, None)
    assert asyncio.run(sources.ensure(KEY))["status"] == "downloaded" and len(seen) == 1  # never fetched twice


def test_a_redirect_to_src_on_the_same_host_is_followed_and_each_hop_is_gated(tmp_path, clock, public):
    seen = []

    def handler(request):
        if request.url.path.startswith("/e-print/"):
            return httpx.Response(302, headers={"location": "/src/2101.00001v2"})
        return ok()
    sources = sources_with(tmp_path, handler, seen)
    assert asyncio.run(sources.ensure(KEY))["status"] == "downloaded"
    assert [p for _, p in seen] == ["/e-print/2101.00001v2", "/src/2101.00001v2"] and seen[1][0] - seen[0][0] >= 3


@pytest.mark.parametrize("response, status", [
    (lambda: ok(key="2101.00001v1"), "version_mismatch"),
    (lambda: httpx.Response(200, content=ARCHIVE, headers={"content-type": "application/gzip"}), "version_mismatch"),
    (lambda: httpx.Response(200, content=b"x" * (fetch.MAX_BYTES + 1), headers={"content-type": "application/gzip"}), "too_large"),
    (lambda: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}), "unreadable"),
    (lambda: httpx.Response(404), "unreadable"),
    (lambda: httpx.Response(403), "not_settled"),
    (lambda: httpx.Response(406), "not_settled"),
    (lambda: httpx.Response(429), "not_settled"),
    (lambda: httpx.Response(503), "not_settled"),
])
def test_each_answer_has_its_download_status(tmp_path, clock, public, response, status):
    sources = sources_with(tmp_path, lambda r: response())
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == status and row["attempts"] == 1 and row["content"] is None
    assert not (tmp_path / "data/arxiv-sources" / f"{KEY}.src").exists()


def test_a_timeout_is_not_settled_retried_after_ten_minutes_and_never_after_the_third_attempt(tmp_path, clock, public):
    seen = []

    def handler(request):
        raise httpx.ReadTimeout("SYNTHETIC timeout", request=request)
    sources = sources_with(tmp_path, handler, seen)
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == "not_settled" and row["attempts"] == 1
    assert asyncio.run(sources.ensure(KEY))["attempts"] == 1 and len(seen) == 1  # RETRY_AFTER not passed
    for attempt in (2, 3):
        clock.now += src.RETRY_AFTER.total_seconds() + 1
        assert asyncio.run(sources.ensure(KEY))["attempts"] == attempt
    clock.now += src.RETRY_AFTER.total_seconds() + 1
    row = asyncio.run(sources.ensure(KEY))
    assert row["attempts"] == 3 and len(seen) == 3 and src.SourceStore.exhausted(row)
    sources.reset(KEY)  # the person's retry
    assert asyncio.run(sources.ensure(KEY))["attempts"] == 1 and len(seen) == 4


def test_a_host_resolving_to_a_private_address_is_refused_without_a_request(tmp_path, clock, monkeypatch):
    async def private(host, port):
        return ["10.0.0.7"]
    monkeypatch.setattr(fetch, "_resolve", private)
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == "unreadable" and "non-public" in row["error"] and seen == []


def test_two_fetches_in_a_row_are_three_seconds_apart(tmp_path, clock, public):
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(key=r.url.path.rsplit("/", 1)[1]), seen)
    asyncio.run(sources.ensure(KEY))
    asyncio.run(sources.ensure("2101.00002v1"))
    assert seen[1][0] - seen[0][0] >= src.RATE_SECONDS


def test_two_pdfs_of_one_version_read_at_the_same_time_send_one_request(tmp_path, clock, public):
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)

    async def both():
        return await asyncio.gather(sources.ensure(KEY), sources.ensure(KEY))
    rows = asyncio.run(both())
    assert [r["status"] for r in rows] == ["downloaded", "downloaded"] and len(seen) == 1


def test_two_concurrent_readers_of_a_corrupt_file_share_one_repair_and_stay_within_three_plus_one(tmp_path, clock, public, monkeypatch):
    # Sol r2 finding 3: a stale reader used to write repairs = 1 over a finished repair (repairs = 2, downloaded).
    import time as real_time
    seen, answers = [], iter([httpx.Response(503), httpx.Response(503), ok(), ok(), ok()])
    sources = sources_with(tmp_path, lambda r: next(answers), seen)
    for _ in range(3):
        asyncio.run(sources.ensure(KEY))
        clock.now += src.RETRY_AFTER.total_seconds() + 1
    assert sources.row(KEY)["attempts"] == 3 and len(seen) == 3
    real_read = src._read_stored

    def slow_read(*args):
        real_time.sleep(0.05)  # widen the window between reading the file and writing the row
        return real_read(*args)
    monkeypatch.setattr(src, "_read_stored", slow_read)
    stored = tmp_path / "data" / sources.row(KEY)["storage_path"]

    async def reader():
        data, problem = await sources.read(KEY)
        if problem == "repair":
            row = await sources.ensure(KEY)
            if row["status"] != "downloaded":
                return None, row["status"]
            data, problem = await sources.read(KEY)
        return data, problem

    async def two():
        return await asyncio.gather(reader(), reader())
    stored.write_bytes(b"SYNTHETIC corrupted")
    assert asyncio.run(two()) == [(ARCHIVE, None), (ARCHIVE, None)]
    row = sources.row(KEY)
    assert (row["status"], row["repairs"], row["attempts"], len(seen)) == ("downloaded", 2, 3, 4)  # one repair between them
    stored.write_bytes(b"SYNTHETIC corrupted again")
    assert asyncio.run(two()) == [(None, "cache_corrupt"), (None, "cache_corrupt")]
    row = sources.row(KEY)
    assert (row["status"], row["error"], row["repairs"], len(seen)) == ("unreadable", "cache_corrupt", 2, 4)  # 3 + 1, no more


def test_a_file_written_without_its_row_is_fetched_again_and_old_part_files_are_removed(tmp_path, clock, public):
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)
    folder = tmp_path / "data/arxiv-sources"
    folder.mkdir(parents=True)
    (folder / f"{KEY}.src").write_bytes(b"left by a crash before the row")
    old, new = folder / f"{KEY}.src.part-123", folder / "2101.00002v1.src.part-456"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    os.utime(old, (time.time() - 2 * 3600,) * 2)
    assert sources.remove_stale_parts() == 1 and not old.exists() and new.exists()
    assert asyncio.run(sources.ensure(KEY))["status"] == "downloaded" and len(seen) == 1
    assert asyncio.run(sources.read(KEY)) == (ARCHIVE, None)


def test_a_corrupted_file_is_fetched_once_more_even_after_the_third_attempt_and_a_second_corruption_is_final(tmp_path, clock, public):
    seen, answers = [], iter([httpx.Response(503), httpx.Response(503), ok(), ok()])
    sources = sources_with(tmp_path, lambda r: next(answers), seen)
    for _ in range(3):
        asyncio.run(sources.ensure(KEY))
        clock.now += src.RETRY_AFTER.total_seconds() + 1
    row = sources.row(KEY)
    assert row["status"] == "downloaded" and row["attempts"] == 3 and len(seen) == 3
    stored = tmp_path / "data" / row["storage_path"]
    stored.unlink()  # deleted
    assert asyncio.run(sources.read(KEY)) == (None, "repair")
    row = sources.row(KEY)
    assert (row["status"], row["repairs"], row["attempts"]) == ("not_settled", 1, 3) and sources.needs_fetch(row)
    row = asyncio.run(sources.ensure(KEY))  # the repair attempt: attempts unchanged, repairs 2
    assert (row["status"], row["repairs"], row["attempts"], len(seen)) == ("downloaded", 2, 3, 4)
    assert asyncio.run(sources.read(KEY)) == (ARCHIVE, None)
    data = bytearray(stored.read_bytes())
    data[10] ^= 0xFF
    stored.write_bytes(bytes(data))  # one byte changed
    assert asyncio.run(sources.read(KEY)) == (None, "cache_corrupt")
    row = sources.row(KEY)
    assert (row["status"], row["error"]) == ("unreadable", "cache_corrupt")
    assert asyncio.run(sources.ensure(KEY))["status"] == "unreadable" and len(seen) == 4  # no request
    sources.reset(KEY)
    assert (sources.row(KEY)["attempts"], sources.row(KEY)["repairs"]) == (0, 0)


def test_past_the_lock_budget_nothing_is_requested_written_or_counted(tmp_path, clock, public, monkeypatch):
    monkeypatch.setattr(src, "LOCK_BUDGET_SECONDS", 0.5)
    monkeypatch.setattr(src, "sleep", asyncio.sleep)  # the lock poll really waits here
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)
    folder = tmp_path / "data/arxiv-sources"
    for lock in (".rate.lock", f"{KEY}.lock"):  # another process holding the rate lock, then the version lock
        holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, str(folder / lock)], stdout=subprocess.PIPE)
        assert holder.stdout.readline().strip() == b"held"
        try:
            assert asyncio.run(sources.ensure(KEY)) == {"arxiv_key": KEY, "outcome": "rate_gate_busy"}
        finally:
            holder.kill()
            holder.wait()
        assert seen == [] and sources.row(KEY) is None


HOLD_LOCK = """
import fcntl, os, sys, time
os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(60)
"""

TRY_LOCK = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("free")
except OSError:
    print("held")
"""


def lock_is_free(path: Path) -> bool:
    return subprocess.run([sys.executable, "-c", TRY_LOCK, str(path)], capture_output=True, text=True).stdout.strip() == "free"


def test_a_task_cancelled_while_waiting_for_the_lock_never_takes_it(tmp_path, public):
    folder = tmp_path / "data/arxiv-sources"
    folder.mkdir(parents=True)
    sources = sources_with(tmp_path, lambda r: ok())
    holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, str(folder / ".rate.lock")], stdout=subprocess.PIPE)
    assert holder.stdout.readline().strip() == b"held"

    async def cancel_while_waiting():
        task = asyncio.create_task(sources.ensure(KEY))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel_while_waiting())
    holder.kill()
    holder.wait()
    assert lock_is_free(folder / ".rate.lock") and lock_is_free(folder / f"{KEY}.lock")  # a third process takes both at once
    assert sources.row(KEY) is None


def test_the_whole_fetch_has_one_deadline_across_redirects_and_a_slow_body(tmp_path, clock, public, monkeypatch):
    monkeypatch.setattr(src, "FETCH_DEADLINE_SECONDS", 2.0)  # the product's 30 s, scaled down for the test's real time

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.2)
                yield b"x" * 10

    def handler(request):
        hop = int(request.url.params.get("hop", "0"))
        if hop < 4:
            return httpx.Response(302, headers={"location": f"/e-print/{KEY}?hop={hop + 1}"})
        return httpx.Response(200, stream=Slow(), headers={"content-type": "application/gzip",
                                                           "content-disposition": f'attachment; filename="arXiv-{KEY}.tar.gz"'})
    seen = []
    sources = sources_with(tmp_path, handler, seen)
    started = time.perf_counter()
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == "not_settled" and row["error"] == "deadline" and len(seen) == 5
    assert 1.8 < time.perf_counter() - started < 4
    assert lock_is_free(tmp_path / "data/arxiv-sources/.rate.lock")
    stamp = json.loads((tmp_path / "data/arxiv-sources/.rate").read_text())
    assert stamp["ended_at"] is not None


# ---- decision 2 across processes, arrivals as a local server sees them ---------------------------------------------------
class Server:
    """A SYNTHETIC arXiv on loopback: records each request's arrival time (server side), can delay or redirect."""

    def __init__(self, delay: float = 0.0, redirect: bool = False):
        self.arrivals: list[tuple[float, str]] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.arrivals.append((time.time(), self.path))
                key = self.path.rsplit("/", 1)[1]
                if redirect and self.path.startswith("/e-print/"):
                    self.send_response(302)
                    self.send_header("Location", f"/src/{key}")
                    self.end_headers()
                    return
                time.sleep(server.delay)
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="arXiv-{key}.tar.gz"')
                self.send_header("Content-Length", str(len(ARCHIVE)))
                self.end_headers()
                try:
                    self.wfile.write(ARCHIVE)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.delay = delay
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wait_for(self, count: int, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        while len(self.arrivals) < count and time.time() < deadline:
            time.sleep(0.02)
        assert len(self.arrivals) >= count, self.arrivals

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def shared(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.close()
    return str(tmp_path / "library.sqlite"), str(tmp_path / "data")


def spawn(shared, port, key, results, offset=0.0):
    process = multiprocessing.get_context("spawn").Process(target=fetch_child, args=(*shared, port, key, results, offset))
    process.start()
    return process


def gaps(arrivals):
    times = sorted(t for t, _ in arrivals)
    return [b - a for a, b in zip(times, times[1:])]


def test_two_processes_fetching_different_versions_arrive_three_seconds_apart_even_with_a_slow_first_reply(shared):
    server = Server(delay=2.0)
    results = multiprocessing.get_context("spawn").Queue()
    try:
        first = spawn(shared, server.port, "2101.00001v2", results)
        second = spawn(shared, server.port, "2101.00002v1", results)
        rows = [results.get(timeout=60), results.get(timeout=60)]
        first.join(10), second.join(10)
    finally:
        server.close()
    assert sorted(r[1]["status"] for r in rows) == ["downloaded", "downloaded"]
    assert len(server.arrivals) == 2 and min(gaps(server.arrivals)) >= src.RATE_SECONDS


def test_a_process_killed_while_its_request_is_at_the_server_holds_the_next_one_to_its_start_plus_33_seconds(shared):
    server = Server(delay=30.0)
    results = multiprocessing.get_context("spawn").Queue()
    try:
        first = spawn(shared, server.port, "2101.00001v2", results)
        server.wait_for(1)
        os.kill(first.pid, signal.SIGKILL)
        first.join(10)
        started_first = json.loads((Path(shared[1]) / "arxiv-sources/.rate").read_text())["started_at"]
        server.delay = 0.0
        # The second process's clock runs 28 s ahead, so its 33 s wait from the first start takes about 5 s here.
        second = spawn(shared, server.port, "2101.00002v1", results, offset=28.0)
        key, row, _ = results.get(timeout=60)
        second.join(10)
    finally:
        server.close()
    assert key == "2101.00002v1" and row["status"] == "downloaded"
    stamp = json.loads((Path(shared[1]) / "arxiv-sources/.rate").read_text())
    assert stamp["started_at"] >= started_first + src.STALE_START_WAIT  # not sent before the first start + 33 s
    assert len(server.arrivals) == 2 and min(gaps(server.arrivals)) >= src.RATE_SECONDS
    conn = db.connect(Path(shared[0]))
    killed = dict(conn.execute("SELECT * FROM arxiv_sources WHERE arxiv_key = '2101.00001v2'").fetchone())
    assert (killed["status"], killed["attempts"]) == ("not_settled", 1)  # counted before it was sent


def test_a_fetch_cancelled_while_its_request_is_at_the_server_stamps_its_end_and_frees_the_lock(shared, monkeypatch):
    server = Server(delay=30.0)

    async def local(url):
        return "127.0.0.1"
    monkeypatch.setattr(fetch, "check_public_url", local)
    monkeypatch.setattr(src, "E_PRINT_URL", f"http://arxiv.test:{server.port}/e-print/{{key}}")
    store = Store(db.connect(Path(shared[0])))
    sources = src.SourceStore(store, Path(shared[1]), client=httpx.AsyncClient(transport=LoopbackTransport()))

    async def cancel_at_server():
        task = asyncio.create_task(sources.ensure("2101.00001v2"))
        while not server.arrivals:
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(cancel_at_server())
        stamp = json.loads((Path(shared[1]) / "arxiv-sources/.rate").read_text())
        assert stamp["ended_at"] is not None and lock_is_free(Path(shared[1]) / "arxiv-sources/.rate.lock")
        assert sources.row("2101.00001v2")["attempts"] == 1 and sources.row("2101.00001v2")["status"] == "not_settled"
        server.delay = 0.0
        results = multiprocessing.get_context("spawn").Queue()
        second = spawn(shared, server.port, "2101.00002v1", results)
        assert results.get(timeout=60)[1]["status"] == "downloaded"
        second.join(10)
    finally:
        server.close()
    assert len(server.arrivals) == 2 and min(gaps(server.arrivals)) >= src.RATE_SECONDS


def test_redirect_hops_count_as_requests_and_a_kill_between_hops_keeps_the_gap(shared):
    server = Server(redirect=True)
    results = multiprocessing.get_context("spawn").Queue()
    try:
        first = spawn(shared, server.port, "2101.00001v2", results)
        second = spawn(shared, server.port, "2101.00002v1", results)
        rows = [results.get(timeout=90), results.get(timeout=90)]
        first.join(10), second.join(10)
        assert sorted(r[1]["status"] for r in rows) == ["downloaded", "downloaded"]
        assert [p.split("/")[1] for _, p in server.arrivals] == ["e-print", "src", "e-print", "src"]
        assert min(gaps(server.arrivals)) >= src.RATE_SECONDS
        # Killed after the first hop's reply, while it waits to send the second hop.
        third = spawn(shared, server.port, "2101.00003v1", results)
        server.wait_for(5)
        time.sleep(1.0)
        os.kill(third.pid, signal.SIGKILL)
        third.join(10)
        fourth = spawn(shared, server.port, "2101.00004v1", results)
        assert results.get(timeout=90)[0] == "2101.00004v1"
        fourth.join(10)
    finally:
        server.close()
    assert [p.split("/")[1] for _, p in server.arrivals[4:]] == ["e-print", "e-print", "src"]
    assert min(gaps(server.arrivals)) >= src.RATE_SECONDS


def test_fetch_pdf_is_unchanged_and_calls_no_gate(monkeypatch, public):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b"%PDF-1.4 SYNTHETIC", headers={"content-type": "application/pdf"})
    result = asyncio.run(fetch.fetch_pdf("https://example.org/a.pdf", httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert result.status == "ok" and result.content_disposition is None and calls == ["/a.pdf"]


def test_a_gzip_archive_round_trips_through_the_store(tmp_path, clock, public):
    body = gzip.compress(b"\\documentclass{article}\\begin{document}\\begin{equation}a=b\\end{equation}\\end{document}")
    sources = sources_with(tmp_path, lambda r: ok(body=body))
    asyncio.run(sources.ensure(KEY))
    assert src.read_archive(asyncio.run(sources.read(KEY))[0]).content == "tex"

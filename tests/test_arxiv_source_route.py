"""The arXiv source route in the equation service, the answer run and the views (slice 22, D104, decisions 1, 6–8).

A fake fetch serves SYNTHETIC source archives; Marker is a fake reader that can be switched on; the clock is fake. The
PDFs and records are SYNTHETIC. Passing shows the route's states, guards and wiring, not matching quality.
"""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from arxiv_helpers import make_arxiv_pdf, no_network, page_with_equations, source_archive, EQUATIONS  # noqa: F401
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import arxiv_source as src
from deixis.documents import fetch, math_reader, pdf
from deixis.storage import db
from deixis.workflow import equations
from deixis.workflow.store import RunInProgress, Store
from fakes import FakeAdapter
from test_api_flow import create, fake_fetch, openalex_client, session, wait_run

KEY = "2101.00001v2"
URL = "https://arxiv.org/pdf/2101.00001v2"
LONG = ["and the receiver keeps a running count of every particle it absorbs in the interval of detection used here."] * 8


def arxiv_pdf(pages: int = 2) -> bytes:
    doc = pymupdf.open()
    page_with_equations(doc, EQUATIONS, 1, "arXiv:2101.00001v2 [cs.IT] 5 Jan 2021", between=LONG)
    for _ in range(pages - 1):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 90), "SYNTHETIC. A page of prose with no equation at all, only words about the model.", fontsize=10)
    return doc.tobytes()


class NoMarker:
    """Marker not installed; `installed` switches it on during a test (a later install, or a race)."""

    def __init__(self):
        self.installed, self.calls, self.lock = False, [], asyncio.Lock()

    def available(self):
        return self.installed

    async def read(self, path, pages):
        self.calls.append(pages)
        return math_reader.Reading({p: f"SYNTHETIC Marker page {p + 1}\n\n$$m_{{k}} \\tag{{{p + 1}}}$$" for p in pages},
                                   {p: [] for p in pages})

    async def close(self):
        pass


class FakeFetch:
    def __init__(self, answer=None, before=None):
        self.calls, self.answer, self.before = [], answer, before

    async def __call__(self, url, media_types, gate=None, client=None, deadline=30.0):
        self.calls.append(url)
        await gate.before()
        try:
            if self.before:
                self.before()
            return self.answer(url) if self.answer else ok(url)
        finally:
            gate.after()


def ok(url, body=None):
    key = url.rsplit("/", 1)[1]
    return fetch.FetchResult("ok", data=body if body is not None else source_archive(), final_url=url, media_type="application/gzip",
                             http_status=200, content_disposition=f'attachment; filename="arXiv-{key}.tar.gz"')


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = [1_800_000_000.0]

    async def fake_sleep(seconds):
        now[0] += seconds
        await asyncio.sleep(0)
    monkeypatch.setattr(src, "clock", lambda: now[0])
    monkeypatch.setattr(src, "sleep", fake_sleep)
    return now


def library(tmp_path, label="arXiv v2", doi="10.48550/arXiv.2101.00001", landing=None, oa=URL, retrieved_from=URL, data=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC arXiv paper")
    conn.execute("UPDATE source_versions SET version_label = ?, doi = ?, landing_url = ?, oa_pdf_url = ? WHERE id = ?",
                 (label, doi, landing, oa, svid))
    papers = tmp_path / "papers"
    papers.mkdir(exist_ok=True)
    path = papers / "paper.pdf"
    path.write_bytes(data or arxiv_pdf())
    aid = store.add_asset_with_pages(svid, "sha-a", 10, "paper.pdf", "download", retrieved_from, "paper.pdf", pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, svid, aid, papers


def service(store, papers, tmp_path, reader=None, fetcher=None, mode="auto"):
    svc = equations.EquationService(store, reader or NoMarker(), papers)
    svc.configure_arxiv_source(mode, tmp_path / "data", fetch_file=fetcher or FakeFetch())
    return svc


def read(svc, aid, **kw):
    return asyncio.run(svc.read_asset(aid, **kw))


# ---- the route writes a new extraction ----------------------------------------------------------------------------------
def test_without_marker_an_eligible_pdf_gets_its_numbered_equations_from_the_source(tmp_path):
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    assert equations.equation_state(store, aid) == {"state": "pending", "route": "arxiv_source"}
    state = read(svc, aid)
    assert state["state"] == "read" and state["source"]["placed"] == 2 and state["source"]["pages"] == [1]
    assert state["source"]["version"] == 2 and state["source"]["version_from"] == "both" and len(fetcher.calls) == 1
    asset = store.asset(aid)
    assert asset["extraction_version"] == pdf.EXTRACTION_VERSION + "+arxiv-latex-v1"
    page_one = [p for p in store.passages_for(svid) if p["extraction_version"] == asset["extraction_version"] and p["physical_page"] == 1]
    labels = [p["text_source"] for p in page_one]
    assert "latex_source" in labels and "text_layer" in labels  # per chunk, not per page
    assert all("$$" in p["text"] for p in page_one if p["text_source"] == "latex_source")
    assert all("$$" not in p["text"] for p in page_one if p["text_source"] == "text_layer")
    other = [p for p in store.passages_for(svid) if p["extraction_version"] == asset["extraction_version"] and p["physical_page"] == 2]
    assert {p["text_source"] for p in other} == {"text_layer"}
    math = json.loads(store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                         (aid,)).fetchone()[0])
    source = math["source"]
    assert math["engine"] == "arxiv_source" and source["params"] == src.PARAMS and source["arxiv_id"] == "2101.00001"
    assert set(source["placed"][0]) == {"page", "n", "start", "end", "group", "recall", "f1", "window_margin", "paper_margin"}
    assert source["record_label"] == "arXiv v2" and store.source(svid)["version_label"] == "arXiv v2"  # never rewritten
    assert store.conn.execute("SELECT COUNT(*) FROM asset_arxiv_versions WHERE asset_id = ?", (aid,)).fetchone()[0] == 1
    assert read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1


def test_a_submitted_version_record_keeps_its_label_beside_the_source_version(tmp_path):
    store, svid, aid, papers = library(tmp_path, label="submittedVersion")
    state = read(service(store, papers, tmp_path), aid)
    assert state["source"]["record_label"] == "submittedVersion" and state["source"]["version"] == 2
    assert store.source(svid)["version_label"] == "submittedVersion"


# ---- the four precedence rules and rule 3's table ------------------------------------------------------------------------
def test_marker_installed_or_installing_keeps_todays_code_and_asks_for_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    store, svid, aid, papers = library(tmp_path)
    reader, fetcher = NoMarker(), FakeFetch()
    reader.installed = True
    svc = service(store, papers, tmp_path, reader=reader, fetcher=fetcher)
    assert equations.equation_state(store, aid) == {"state": "pending"}  # rule 1: no route key
    reader.installed = False
    svc.job = {"status": "running"}
    assert svc.installing() and equations.equation_state(store, aid) == {"state": "pending"}
    assert not svc.route_active() and svc.next_asset() == aid  # today's code: pending
    svc.job = None
    reader.installed = True
    read(svc, aid)
    assert fetcher.calls == [] and store.asset(aid)["extraction_version"].endswith("+marker-1.10.2-math-v2")


def test_flag_off_is_todays_pending_and_a_stored_source_reading_stays_read_whatever_the_flag(tmp_path):
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher, mode="off")
    assert equations.equation_state(store, aid) == {"state": "pending"} and not svc.route_active()
    with pytest.raises(math_reader.MathReaderUnavailable):  # today's code without Marker
        read(svc, aid)
    assert fetcher.calls == []
    svc.arxiv_mode = "auto"  # off -> on: the remaining PDF is read
    assert read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1
    svc.arxiv_mode = "off"  # on -> off: no new request, the stored reading stays read (rule 2)
    assert equations.equation_state(store, aid)["state"] == "read" and read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1
    assert {p["text_source"] for p in store.passages_for(svid) if p["extraction_version"] == store.asset(aid)["extraction_version"]} \
        >= {"latex_source"}


@pytest.mark.parametrize("fields, reason", [
    ({"retrieved_from": None, "data": make_arxiv_pdf(stamp=None)}, "no_version"),
    ({"data": make_arxiv_pdf(stamp="arXiv:2101.00001v1 [cs.IT] 5 Jan 2021")}, "version_conflict"),
    ({"doi": "10.1109/SYNTHETIC.1", "oa": None}, "record_identity_unknown"),
    ({"landing": "https://arxiv.org/abs/2202.00002"}, "record_identity_conflict"),
    ({"label": "publishedVersion"}, "record_version_conflict"),
    ({"label": "arXiv v1"}, "record_version_conflict"),
])
def test_an_eligibility_refusal_is_no_source_and_nothing_looks_at_it_again(tmp_path, fields, reason):
    store, svid, aid, papers = library(tmp_path, **fields)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    assert read(svc, aid) == {"state": "no_source", "reason": reason, "route": "arxiv_source"}
    assert fetcher.calls == [] and svc.next_asset() is None
    assert equations.equation_state(store, aid)["state"] == "no_source"
    svc.arxiv_mode = "off"
    assert equations.equation_state(store, aid) == {"state": "pending"}


def test_rule_three_states_from_stored_rows(tmp_path, clock):
    store, svid, aid, papers = library(tmp_path)
    answers = iter([fetch.FetchResult("http_error", http_status=503)] * 3)
    fetcher = FakeFetch(answer=lambda url: next(answers))
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    state = read(svc, aid)
    assert state["state"] == "source_waiting" and state["attempts"] == 1 and svc.next_asset() is None
    clock[0] += src.RETRY_AFTER.total_seconds() + 1
    assert equations.equation_state(store, aid)["state"] == "pending" and svc.next_asset() == aid
    read(svc, aid)
    clock[0] += src.RETRY_AFTER.total_seconds() + 1
    assert read(svc, aid) == {"state": "no_source", "reason": "not_settled", "attempts": 3, "route": "arxiv_source"}
    assert len(fetcher.calls) == 3
    conn = store.conn
    conn.execute("UPDATE arxiv_sources SET status = 'downloaded', content = NULL, sha256 = 'x', storage_path = 'nowhere' WHERE arxiv_key = ?", (KEY,))
    assert equations.equation_state(store, aid)["state"] == "pending"
    for content in ("pdf_only", "no_tex", "too_large", "unreadable"):
        conn.execute("UPDATE arxiv_sources SET content = ? WHERE arxiv_key = ?", (content, KEY))
        assert equations.equation_state(store, aid) == {"state": "no_source", "reason": content, "route": "arxiv_source"}
    for status in ("version_mismatch", "too_large", "unreadable"):
        conn.execute("UPDATE arxiv_sources SET status = ?, content = NULL WHERE arxiv_key = ?", (status, KEY))
        assert equations.equation_state(store, aid) == {"state": "no_source", "reason": status, "route": "arxiv_source"}
    equations.reading = {"asset_id": aid, "pages": 2, "started_at": "now"}
    try:
        assert equations.equation_state(store, aid)["state"] == "reading"
    finally:
        equations.reading = None


def test_a_person_retry_resets_an_exhausted_source(tmp_path, clock):
    store, svid, aid, papers = library(tmp_path)
    answers = iter([fetch.FetchResult("http_error", http_status=429)] * 3 + [ok(URL.replace("pdf", "e-print"))])
    fetcher = FakeFetch(answer=lambda url: next(answers))
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    for _ in range(3):
        read(svc, aid)
        clock[0] += src.RETRY_AFTER.total_seconds() + 1
    assert equations.equation_state(store, aid)["reason"] == "not_settled"
    assert read(svc, aid, retry=True)["state"] == "read" and len(fetcher.calls) == 4


def test_the_stamp_read_and_the_stored_files_hash_write_and_read_run_off_the_event_loop(tmp_path, monkeypatch):
    # Sol r1 finding 4: each of these ran on the event loop; they now run in a worker thread while the loop keeps serving.
    import threading
    import time as real_time
    store, svid, aid, papers = library(tmp_path)
    svc = service(store, papers, tmp_path)
    threads: dict[str, list[str]] = {}

    def slow(name, fn):
        def wrapper(*args, **kw):
            threads.setdefault(name, []).append(threading.current_thread().name)
            real_time.sleep(0.2)  # a slow disk or a large file
            return fn(*args, **kw)
        return wrapper
    monkeypatch.setattr(src, "stamp_key", slow("stamp", src.stamp_key))
    monkeypatch.setattr(src, "_write_source", slow("write", src._write_source))
    monkeypatch.setattr(src, "_read_stored", slow("read", src._read_stored))

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1
        task = asyncio.create_task(ticker())
        state = await svc.read_asset(aid)
        task.cancel()
        return state, ticks
    state, ticks = asyncio.run(main())
    assert state["state"] == "read"
    assert set(threads) == {"stamp", "write", "read"}
    assert all(name != threading.main_thread().name for names in threads.values() for name in names)
    assert ticks >= 30  # the loop went on ticking through the 0.6 s of blocking work


def test_a_stored_file_whose_version_locks_stay_taken_is_rate_gate_busy_and_stays_pending(tmp_path, monkeypatch):
    # Sol r3 test gap: SourceStore.read's lock-budget timeout, directly.
    import fcntl
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    assert asyncio.run(svc.sources.ensure(KEY))["status"] == "downloaded"  # stored, not yet inspected
    monkeypatch.setattr(src, "LOCK_BUDGET_SECONDS", 0.2)
    holder = os.open(tmp_path / "data/arxiv-sources" / f"{KEY}.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(holder, fcntl.LOCK_EX)  # another process holds this version's file lock
    try:
        assert asyncio.run(svc.sources.read(KEY)) == (None, "busy")
        state = read(svc, aid)
        assert (state["state"], state["outcome"]) == ("pending", "rate_gate_busy")
        row = store.conn.execute("SELECT status, content, repairs FROM arxiv_sources WHERE arxiv_key = ?", (KEY,)).fetchone()
        assert tuple(row) == ("downloaded", None, 0)  # nothing written: no repair opened, nothing inspected
        assert equations.equation_state(store, aid)["state"] == "pending" and svc.next_asset() == aid
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    assert read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1


def test_nothing_placed_is_a_passage_less_rejection_and_no_source(tmp_path):
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch(answer=lambda url: ok(url, source_archive([("", "k = q + j")])))
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    assert read(svc, aid) == {"state": "no_source", "reason": "nothing_placed", "route": "arxiv_source"}
    row = store.conn.execute("SELECT passage_count, math_json FROM asset_extractions WHERE asset_id = ? AND rejection_reason = 'nothing_placed'",
                             (aid,)).fetchone()
    assert row["passage_count"] == 0 and json.loads(row["math_json"])["engine"] == "arxiv_source"
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION and svc.next_asset() is None


@pytest.mark.parametrize("error", ["extraction timed out", "extraction exceeded the memory limit"])
def test_a_failed_re_extraction_is_its_own_reason_and_is_tried_again_like_a_failed_marker_read(tmp_path, monkeypatch, error):
    # Sol r1 finding 3: pdf.extract_pdf's time or memory limit used to be stored as nothing_placed (no_source, never retried).
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    real = pdf.extract_pdf

    def limit(path, **kw):
        return pdf.Extraction("failed", error=error) if kw.get("placements") else real(path, **kw)
    monkeypatch.setattr(equations.pdf, "extract_pdf", limit)
    target = pdf.EXTRACTION_VERSION + "+arxiv-latex-v1"

    def age():  # the failed row is older than RETRY_AFTER
        store.conn.execute("UPDATE asset_extractions SET created_at = '2000-01-01T00:00:00.000+00:00' WHERE asset_id = ?"
                           " AND extraction_version = ?", (aid, target))
    state = read(svc, aid)
    assert (state["state"], state["reason"], state["attempts"]) == ("failed", "extraction_failed", 1)
    row = store.conn.execute("SELECT outcome, passage_count, math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (aid, target)).fetchone()
    math = json.loads(row["math_json"])
    assert row["outcome"] == "rejected" and row["passage_count"] == 0 and math["error"] == error and math["attempts"] == 1
    assert math["source"]["candidates"] >= 1  # the source had matches; the extraction, not the matching, failed
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION
    assert svc.next_asset() is None  # not before RETRY_AFTER
    age()
    assert svc.next_asset() == aid
    assert read(svc, aid)["attempts"] == 2
    age()
    assert read(svc, aid)["attempts"] == 3
    age()
    assert svc.next_asset() is None and read(svc, aid)["attempts"] == 3  # three attempts, then only the person's retry
    assert len(fetcher.calls) == 1  # every attempt read the stored file
    monkeypatch.setattr(equations.pdf, "extract_pdf", real)
    assert read(svc, aid, retry=True)["state"] == "read" and len(fetcher.calls) == 1


def test_unresolved_offsets_and_a_d45_rejection_are_failed_without_attempts_and_not_retried(tmp_path, monkeypatch):
    store, svid, aid, papers = library(tmp_path)
    store2, _, aid2, papers2 = library(tmp_path / "second")
    svc = service(store, papers, tmp_path)
    real = pdf.extract_pdf

    def unresolved(path, **kw):
        found = real(path, **kw)
        found.placement["refused"].append({"page": 1, "n": "9", "reason": "offsets_unresolved"})
        return found
    monkeypatch.setattr(equations.pdf, "extract_pdf", unresolved)
    state = read(svc, aid)
    assert (state["state"], state["reason"]) == ("failed", "offsets_unresolved") and "attempts" not in state
    assert svc.next_asset() is None and store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION

    def fewer_pages(path, **kw):
        found = real(path, **kw)
        found.page_count += 1  # the new text has another page count: D45 keeps the old text
        return found
    monkeypatch.setattr(equations.pdf, "extract_pdf", fewer_pages)
    state = read(service(store2, papers2, tmp_path / "second"), aid2)
    assert state["state"] == "failed" and state["reason"].startswith("page count") and "attempts" not in state


def test_a_crash_between_inspection_and_write_is_pending_and_read_again_from_the_stored_file(tmp_path, monkeypatch):
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)

    def crash(*args, **kw):
        raise KeyboardInterrupt("SYNTHETIC crash before the write")
    monkeypatch.setattr(equations.pdf, "extract_pdf", crash)
    with pytest.raises(KeyboardInterrupt):
        read(svc, aid)
    row = store.conn.execute("SELECT status, content FROM arxiv_sources WHERE arxiv_key = ?", (KEY,)).fetchone()
    assert tuple(row) == ("downloaded", "tex") and equations.equation_state(store, aid)["state"] == "pending"
    monkeypatch.undo()
    assert read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1  # from the stored file, no request


def test_a_task_cancelled_during_its_fetch_counts_the_attempt_and_leaves_no_downloaded_row(tmp_path):
    store, svid, aid, papers = library(tmp_path)

    async def hang(url, media_types, gate=None, client=None, deadline=30.0):
        await gate.before()
        try:
            await asyncio.sleep(3600)
        finally:
            gate.after()
    svc = service(store, papers, tmp_path, fetcher=hang)

    async def cancel():
        task = asyncio.create_task(svc.read_asset(aid))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if store.conn.execute("SELECT 1 FROM arxiv_sources").fetchone():
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())
    row = store.conn.execute("SELECT status, attempts FROM arxiv_sources WHERE arxiv_key = ?", (KEY,)).fetchone()
    assert tuple(row) == ("not_settled", 1)


def test_without_file_locks_the_route_is_off_and_says_so(tmp_path, monkeypatch):
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    monkeypatch.setattr(src, "posix_available", lambda: False)
    assert equations.equation_state(store, aid) == {"state": "no_source", "reason": "not_available_on_this_system", "route": "arxiv_source"}
    assert read(svc, aid)["state"] == "no_source" and fetcher.calls == [] and not svc.route_active()
    assert store.conn.execute("SELECT COUNT(*) FROM asset_arxiv_versions").fetchone()[0] == 0


# ---- Marker races, C1, later install ------------------------------------------------------------------------------------
def test_marker_becoming_available_during_the_fetch_stops_the_write_and_marker_reads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    store, svid, aid, papers = library(tmp_path)
    reader = NoMarker()
    svc = service(store, papers, tmp_path, reader=reader, fetcher=FakeFetch(before=lambda: setattr(reader, "installed", True)))
    state = read(svc, aid)
    assert state == {"state": "pending", "outcome": "superseded_by_marker"}
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION
    assert read(svc, aid)["state"] == "read" and store.asset(aid)["extraction_version"] == equations.target_version()


def test_marker_becoming_available_right_after_the_write_makes_the_reading_pending_and_marker_reads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    store, svid, aid, papers = library(tmp_path)
    reader = NoMarker()
    svc = service(store, papers, tmp_path, reader=reader)
    assert read(svc, aid)["state"] == "read"
    reader.installed = True  # Marker installed later
    assert equations.equation_state(store, aid) == {"state": "pending"} and svc.next_asset() == aid
    assert read(svc, aid)["state"] == "read" and store.asset(aid)["extraction_version"] == equations.target_version()
    assert reader.calls == [[0]]
    reader.installed = False  # removed again: C1, a Marker reading is never read by the route
    fetcher = FakeFetch()
    svc.configure_arxiv_source("auto", tmp_path / "data", fetch_file=fetcher)
    assert equations.equation_state(store, aid) == {"state": "read", "to_check": [], "equations_to_check": 0}  # today's code
    read(svc, aid)
    assert fetcher.calls == [] and svc.next_asset() is None and not svc.route_target(aid)


# ---- the last-write guard inside the write's transaction ----------------------------------------------------------------
SECOND = """
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=float(sys.argv[3]), isolation_level=None)
try:
    conn.execute(sys.argv[2])
    print("written")
except sqlite3.OperationalError as exc:
    print(str(exc))
"""


def second_connection(store, sql, timeout=5.0):
    path = store.conn.execute("PRAGMA database_list").fetchone()[2]
    return subprocess.run([sys.executable, "-c", SECOND, path, sql, str(timeout)], capture_output=True, text=True).stdout.strip()


def before_the_guard(monkeypatch, store, action):
    """Run `action` in another process after reextract_asset's own checks, just before its write transaction opens."""
    from contextlib import contextmanager

    from deixis.workflow import store as store_module
    real = store_module.transaction

    @contextmanager
    def wrapped(conn):
        if not conn.in_transaction and not getattr(wrapped, "done", False):
            wrapped.done = True
            action(store)
        with real(conn) as inner:
            yield inner
    original = Store.reextract_asset

    def reextract(self, *args, **kw):
        monkeypatch.setattr(store_module, "transaction", wrapped)
        try:
            return original(self, *args, **kw)
        finally:
            monkeypatch.setattr(store_module, "transaction", real)
    monkeypatch.setattr(Store, "reextract_asset", reextract)


def test_the_guard_runs_inside_the_write_transaction_and_holds_other_writers_off(tmp_path, monkeypatch):
    store, svid, aid, papers = library(tmp_path)
    original = Store.reextract_asset
    seen = []

    def wrapped(self, *args, guard=None, **kw):
        def watched(conn):
            seen.append((conn.in_transaction, second_connection(self, f"UPDATE source_versions SET version_label = 'publishedVersion' WHERE id = '{svid}'", 0.3)))
            return guard(conn)
        return original(self, *args, guard=watched, **kw)
    monkeypatch.setattr(Store, "reextract_asset", wrapped)
    assert read(service(store, papers, tmp_path), aid)["state"] == "read"
    assert seen == [(True, "database is locked")] and store.source(svid)["version_label"] == "arXiv v2"


@pytest.mark.parametrize("sql, outcome, eligibility", [
    ("UPDATE source_versions SET version_label = 'publishedVersion' WHERE id = '{svid}'", "record_version_changed", "record_version_conflict"),
    ("UPDATE source_versions SET landing_url = 'https://arxiv.org/abs/2202.00002' WHERE id = '{svid}'", "record_version_changed",
     "record_identity_conflict"),
    ("UPDATE source_assets SET extraction_version = 'pymupdf-x+marker-1.10.2-math-v2' WHERE id = '{aid}'", "superseded", "eligible"),
    ("UPDATE source_assets SET removed_at = '2026-09-25', removal_reason = 'wrong_file' WHERE id = '{aid}'", "asset_removed", "eligible"),
])
def test_a_second_process_changing_the_record_or_the_pdf_just_before_the_guard_writes_no_passage(tmp_path, monkeypatch, sql, outcome, eligibility):
    store, svid, aid, papers = library(tmp_path)
    before_the_guard(monkeypatch, store, lambda s: second_connection(s, sql.format(svid=svid, aid=aid)))
    passages = store.conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    version = store.asset(aid)["extraction_version"]
    state = asyncio.run(service(store, papers, tmp_path)._read_source(aid, None, False, {"state": "pending", "route": "arxiv_source"}))
    assert state["outcome"] == outcome
    assert store.conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == passages
    if outcome != "superseded":
        assert store.asset(aid)["extraction_version"] == version
    assert store.conn.execute("SELECT eligibility FROM asset_arxiv_versions WHERE asset_id = ?", (aid,)).fetchone()[0] == eligibility
    if outcome == "record_version_changed":
        assert store.conn.execute("SELECT passage_count FROM asset_extractions WHERE rejection_reason = 'record_version_changed'").fetchone()[0] == 0
        assert equations.equation_state(store, aid) == {"state": "no_source", "reason": eligibility, "route": "arxiv_source"}


def test_reextract_without_a_guard_behaves_as_before(tmp_path):
    store, svid, aid, papers = library(tmp_path)
    report = store.reextract_asset(aid, pdf.extract_pdf(papers / "paper.pdf"), "other-version", pdf.chunk_page)
    assert report["outcome"] == "current" and store.asset(aid)["extraction_version"] == "other-version"


# ---- a record enriched later (enrich_source) -----------------------------------------------------------------------------
def enrichment(landing):
    return SimpleNamespace(authors=[], year=None, venue=None, publication_type=None, landing_url=landing, volume=None, issue=None,
                           pages=None, provider_record_id="W-SYNTHETIC")


def test_an_enriched_landing_url_makes_an_unknown_identity_eligible(tmp_path):
    store, svid, aid, papers = library(tmp_path, doi=None, oa=None)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    assert read(svc, aid)["reason"] == "record_identity_unknown" and fetcher.calls == []
    store.enrich_source("openalex", svid, enrichment("https://arxiv.org/abs/2101.00001"))
    assert equations.equation_state(store, aid)["state"] == "pending"
    assert read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1


def test_an_enrichment_landing_while_the_stamp_is_read_is_seen_by_the_eligibility(tmp_path, monkeypatch):
    # Sol r2 finding 2: the record was read before the stamp thread; an enrichment in between had no row to re-check.
    import threading
    store, svid, aid, papers = library(tmp_path, doi=None, oa=None)
    svc = service(store, papers, tmp_path)
    started, go = threading.Event(), threading.Event()
    real = src.stamp_key

    def slow_stamp(path):
        started.set()
        assert go.wait(5)
        return real(path)
    monkeypatch.setattr(src, "stamp_key", slow_stamp)

    async def main():
        task = asyncio.create_task(svc.read_asset(aid))
        while not started.is_set():
            await asyncio.sleep(0.01)
        assert store.conn.execute("SELECT COUNT(*) FROM asset_arxiv_versions").fetchone()[0] == 0
        store.enrich_source("openalex", svid, enrichment("https://arxiv.org/abs/2101.00001"))  # on the loop, mid-stamp
        go.set()
        return await task
    state = asyncio.run(main())
    row = store.conn.execute("SELECT eligibility, arxiv_key FROM asset_arxiv_versions WHERE asset_id = ?", (aid,)).fetchone()
    assert tuple(row) == ("eligible", KEY) and state["state"] == "read"


def test_another_process_enriching_the_record_cannot_slip_between_the_eligibility_read_and_its_insert(tmp_path, monkeypatch):
    # Sol r3 finding 2: the record read and the insert were separate; another connection could commit an enrichment in
    # between, and its re-check found no row to correct.
    import threading
    store, svid, aid, papers = library(tmp_path, doi=None, oa=None)
    svc = service(store, papers, tmp_path)
    real = src.eligibility
    other: dict = {}

    def enrich_elsewhere():
        conn = db.connect(tmp_path / "library.sqlite")  # a second connection, as another DEIXIS process would have
        Store(conn).enrich_source("openalex", svid, enrichment("https://arxiv.org/abs/2101.00001"))
        other["done_at"] = "after"
        conn.close()

    def decide(*args):
        thread = threading.Thread(target=enrich_elsewhere)
        other["thread"] = thread
        thread.start()
        thread.join(0.3)
        other["blocked"] = thread.is_alive()  # the write lock of this transaction holds the other writer off
        return real(*args)
    monkeypatch.setattr(src, "eligibility", decide)
    first = read(svc, aid)
    other["thread"].join(10)
    assert other["blocked"] and other["done_at"] == "after"
    assert first["reason"] == "record_identity_unknown"  # decided on the record as it was when the transaction began
    row = store.conn.execute("SELECT eligibility, arxiv_key FROM asset_arxiv_versions WHERE asset_id = ?", (aid,)).fetchone()
    assert tuple(row) == ("eligible", KEY)  # the enrichment committed after it and re-checked the row
    monkeypatch.setattr(src, "eligibility", real)
    assert read(svc, aid)["state"] == "read"


def test_an_enriched_landing_url_naming_another_id_withdraws_the_reading(tmp_path):
    store, svid, aid, papers = library(tmp_path, landing=None)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    before = store.asset(aid)
    assert read(svc, aid)["state"] == "read"
    source_ids = {p["id"] for p in store.passages_for(svid) if p["text_source"] == "latex_source"}
    store.enrich_source("openalex", svid, enrichment("https://arxiv.org/abs/2202.00002"))
    after = store.asset(aid)
    assert (after["extraction_version"], after["extraction_status"], after["extraction_error"], after["page_count"]) == \
        (before["extraction_version"], before["extraction_status"], before["extraction_error"], before["page_count"])
    rows = dict(store.conn.execute("SELECT extraction_version, outcome FROM asset_extractions WHERE asset_id = ? AND passage_count > 0", (aid,)))
    assert rows == {pdf.EXTRACTION_VERSION: "current", pdf.EXTRACTION_VERSION + "+arxiv-latex-v1": "superseded"}
    assert equations.equation_state(store, aid) == {"state": "no_source", "reason": "record_identity_conflict", "route": "arxiv_source"}
    assert set(store.evidence_statuses(list(source_ids)).values()) == {"text_superseded"}
    assert not source_ids & {p["id"] for p in store.passages_for(svid) if p["extraction_version"] == after["extraction_version"]}
    assert read(svc, aid)["state"] == "no_source" and len(fetcher.calls) == 1


def test_an_enriched_landing_url_with_the_same_id_changes_nothing(tmp_path):
    store, svid, aid, papers = library(tmp_path, landing=None)
    svc = service(store, papers, tmp_path)
    read(svc, aid)
    version = store.asset(aid)["extraction_version"]
    store.enrich_source("openalex", svid, enrichment("https://arxiv.org/abs/2101.00001v2"))
    assert store.asset(aid)["extraction_version"] == version and equations.equation_state(store, aid)["state"] == "read"


# ---- the answer run, the views and the passage payload -------------------------------------------------------------------
def route_app(tmp_path, monkeypatch, fetcher, mode="auto", reextract=None):
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)  # only the answer run reads here
    monkeypatch.setattr(fetch, "fetch_file", fetcher)
    settings = Settings(data_dir=tmp_path / "data", port=8765, arxiv_source=mode)
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=openalex_client(200), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    return app


def arxiv_upload(client, app, rid):
    upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("2101.00001v2.pdf", arxiv_pdf(), "application/pdf")})
    source = next(s for s in upload.json()["sources"] if s["access"]["assets"] and s["access"]["assets"][0]["original_filename"] == "2101.00001v2.pdf")
    app.state.store.conn.execute("UPDATE source_versions SET version_label = 'arXiv v2', doi = '10.48550/arXiv.2101.00001' WHERE id = ?",
                                 (source["source_version_id"],))
    return source["source_version_id"], source["access"]["assets"][0]["id"]


@pytest.mark.parametrize("answer, expected", [
    (lambda url: ok(url), "read"),
    (lambda url: fetch.FetchResult("http_error", http_status=503), "source_waiting"),
    (lambda url: fetch.FetchResult("http_error", http_status=404), "no_source"),
    (lambda url: ok(url, source_archive([("", "k = q + j")])), "no_source"),
])
def test_an_answer_run_never_pauses_for_the_route_and_its_step_carries_the_state(tmp_path, monkeypatch, answer, expected):
    fetcher = FakeFetch(answer=answer)
    app = route_app(tmp_path, monkeypatch, fetcher)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = arxiv_upload(client, app, rid)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        step = app.state.store.step(run_id, f"equations:{aid}", "read_equations")
        assert step["status"] == "succeeded" and step["output"]["route"] == "arxiv_source" and step["output"]["state"] == expected
        asset = next(s for s in view["sources"] if s["source_version_id"] == svid)["access"]["assets"][0]
        assert asset["equations"]["state"] == expected and asset["rejected_extraction"] is None
        # The same run again (a resume re-entering the step) sends no new request.
        calls = len(fetcher.calls)
        flow = app.state.worker.flow
        asyncio.run(flow._read_equations(app.state.store.run(run_id), [svid]))
        assert len(fetcher.calls) == calls
        if expected == "read":
            payload = app.state.store.step_input_payload(app.state.store.step(run_id, "grounded_answer", "model:grounded_answer")["output"]["step_input_id"])
            assert any(p["text_source"] == "latex_source" and "$$" in p["text"] for p in payload["passages"])
            passage = next(p for p in payload["passages"] if p["text_source"] == "latex_source")
            shown = client.get(f"/api/researches/{rid}/passages/{passage['passage_id']}").json()
            assert shown["text_source"] == "latex_source" and shown["source_equations"] and set(shown["source_equations"]) <= {"1", "2"}
            text = client.get(f"/api/researches/{rid}/assets/{aid}/text").json()
            numbers = {p["id"]: p["source_equations"] for p in text["passages"]}
            assert sorted(n for ns in numbers.values() for n in ns) == ["1", "2"]
            assert all(not ns for pid, ns in numbers.items()
                       if next(p for p in text["passages"] if p["id"] == pid)["text_source"] != "latex_source")


def test_a_second_answer_run_records_a_pdf_already_waiting_for_its_source_without_a_request(tmp_path, monkeypatch):
    # Sol r2 finding 4: a PDF already in source_waiting got no read_equations step in the next run.
    fetcher = FakeFetch(answer=lambda url: fetch.FetchResult("http_error", http_status=503))
    app = route_app(tmp_path, monkeypatch, fetcher)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = arxiv_upload(client, app, rid)
        outputs = []
        for _ in range(2):
            run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
            view, run = wait_run(client, rid, run_id)
            assert run["status"] == "completed", run
            step = app.state.store.step(run_id, f"equations:{aid}", "read_equations")
            assert step["status"] == "succeeded"
            outputs.append(step["output"])
        assert [(o["state"], o["attempts"], o["route"]) for o in outputs] == [("source_waiting", 1, "arxiv_source")] * 2
        assert len(fetcher.calls) == 1  # the second run asked nothing


def test_an_answer_run_records_a_failed_re_extraction_and_the_next_answer_tries_again(tmp_path, monkeypatch):
    fetcher = FakeFetch()
    app = route_app(tmp_path, monkeypatch, fetcher)
    real = pdf.extract_pdf
    monkeypatch.setattr(equations.pdf, "extract_pdf",
                        lambda path, **kw: pdf.Extraction("failed", error="extraction timed out") if kw.get("placements") else real(path, **kw))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = arxiv_upload(client, app, rid)
        outputs = []
        for _ in range(2):
            run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
            view, run = wait_run(client, rid, run_id)
            assert run["status"] == "completed", run
            outputs.append(app.state.store.step(run_id, f"equations:{aid}", "read_equations")["output"])
        assert [(o["state"], o["reason"], o["attempts"]) for o in outputs] == [("failed", "extraction_failed", 1),
                                                                               ("failed", "extraction_failed", 2)]
        asset = next(s for s in view["sources"] if s["source_version_id"] == svid)["access"]["assets"][0]
        assert asset["equations"]["reason"] == "extraction_failed" and len(fetcher.calls) == 1


def test_a_d45_rejection_or_a_blocking_run_never_pauses_the_answer(tmp_path, monkeypatch):
    fetcher = FakeFetch()
    app = route_app(tmp_path, monkeypatch, fetcher)

    def blocked(self, *args, **kw):
        raise RunInProgress("SYNTHETIC")
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = arxiv_upload(client, app, rid)
        monkeypatch.setattr(Store, "reextract_asset", blocked)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        step = app.state.store.step(run_id, f"equations:{aid}", "read_equations")
        assert step["status"] == "succeeded" and step["output"]["outcome"] == "blocked_by_run"


def test_the_view_never_opens_a_pdf_for_the_equation_state_and_reports_refusals_on_the_source_row(tmp_path, monkeypatch):
    fetcher = FakeFetch()
    app = route_app(tmp_path, monkeypatch, fetcher)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("p.pdf", arxiv_pdf(), "application/pdf")})
        aid = upload.json()["sources"][0]["access"]["assets"][0]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        wait_run(client, rid, run_id)
        # An upload's record carries no arXiv id, so its identity is unknown and no source is asked for (decision 1).
        monkeypatch.setattr(pymupdf, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("PDF opened by the view")))
        view = client.get(f"/api/researches/{rid}").json()
        asset = view["sources"][0]["access"]["assets"][0]
        assert asset["equations"] == {"state": "no_source", "reason": "record_identity_unknown", "route": "arxiv_source"}
        assert fetcher.calls == [] and asset["id"] == aid


def test_the_route_is_not_called_by_the_retrieval_reading_or_discovery_runs():
    import inspect

    from deixis.workflow import flow
    source = inspect.getsource(flow.ResearchFlow)
    callers = set()
    for name, member in inspect.getmembers(flow.ResearchFlow, inspect.isfunction):
        if "_read_equations(" in inspect.getsource(member) and name != "_read_equations":
            callers.add(name)
    assert "_read_source_equations(" in source
    assert callers and not any(word in name for name in callers for word in ("fulltext", "adjudicat", "discovery", "retriev"))


def test_the_answer_reads_a_persons_published_pdf_and_not_the_preprints_source_passages(tmp_path, monkeypatch):
    """D4 and D48: with the published version's PDF text in use, the arXiv version's latex_source passages are not given."""
    fetcher = FakeFetch()
    app = route_app(tmp_path, monkeypatch, fetcher)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        published = client.post(f"/api/researches/{rid}/uploads", files={"file": ("published.pdf", make_arxiv_pdf(stamp=None), "application/pdf")})
        pub = published.json()["sources"][0]["source_version_id"]
        pre, aid = arxiv_upload(client, app, rid)
        store = app.state.store
        store.conn.execute("UPDATE source_versions SET work_id = (SELECT work_id FROM source_versions WHERE id = ?) WHERE id = ?", (pub, pre))
        store.conn.execute("UPDATE source_versions SET version_label = 'publishedVersion', doi = '10.1109/SYNTHETIC.2' WHERE id = ?", (pub,))
        state = asyncio.run(app.state.equations.read_asset(aid))
        assert state["state"] == "read", state
        assert any(p["text_source"] == "latex_source" for p in store.passages_for(pre))
        assert store.answer_version(rid, pub) == pub
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        payload = store.step_input_payload(store.step(run_id, "grounded_answer", "model:grounded_answer")["output"]["step_input_id"])
        assert payload["passages"] and all(p["text_source"] != "latex_source" for p in payload["passages"])
        assert {p["source_id"] for p in payload["passages"] if p["locator"]["kind"] == "pdf_page"} == {pub}


def test_the_background_reader_serves_the_route_while_marker_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(equations, "RETRY_SECONDS", 0.01)
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)

    async def background():
        task = asyncio.create_task(svc.run_forever())
        for _ in range(500):
            await asyncio.sleep(0.02)
            if equations.equation_state(store, aid)["state"] == "read":
                break
        task.cancel()
    asyncio.run(background())
    assert equations.equation_state(store, aid)["state"] == "read" and len(fetcher.calls) == 1


def test_a_rejected_source_reading_is_the_equation_state_not_the_rejected_extraction(tmp_path, monkeypatch):
    fetcher = FakeFetch()
    app = route_app(tmp_path, monkeypatch, fetcher)
    real = pdf.extract_pdf

    def other_page_count(path, **kw):
        found = real(path, **kw)
        if kw.get("placements"):
            found.page_count += 1
        return found
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = arxiv_upload(client, app, rid)
        monkeypatch.setattr(equations.pdf, "extract_pdf", other_page_count)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        asset = next(s for s in view["sources"] if s["source_version_id"] == svid)["access"]["assets"][0]
        assert asset["equations"]["state"] == "failed" and asset["equations"]["reason"].startswith("page count")
        assert asset["rejected_extraction"] is None

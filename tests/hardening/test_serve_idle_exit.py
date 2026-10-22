"""The idle exit of the launcher (DEIXIS.app): the server stops itself only when no request came and nothing is working."""

import asyncio
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from deixis import __main__ as launcher


def watch(server, last, busy):
    cancel = threading.Event()
    thread = threading.Thread(target=launcher.watch_idle, args=(server, 0.2, last, busy, cancel, 0.05), daemon=True)
    thread.start()
    return thread, cancel


def test_stops_when_idle_and_nothing_works(capsys):
    server = SimpleNamespace(should_exit=False)
    thread, _ = watch(server, lambda: time.monotonic() - 10, lambda: False)
    thread.join(2)
    assert server.should_exit and "stopping" in capsys.readouterr().err


@pytest.mark.parametrize("recent, busy", [(True, False), (False, True)])
def test_keeps_running_with_a_recent_request_or_a_working_run(recent, busy):
    server = SimpleNamespace(should_exit=False)
    thread, cancel = watch(server, (lambda: time.monotonic()) if recent else (lambda: time.monotonic() - 10), lambda: busy)
    time.sleep(0.5)
    assert not server.should_exit and thread.is_alive()
    cancel.set()
    thread.join(2)


def make_library(path, run_status, fetch_status=None):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (status TEXT)")
    conn.execute("CREATE TABLE fast_path_background_fetches (status TEXT)")
    conn.execute("INSERT INTO runs VALUES (?)", (run_status,))
    if fetch_status:
        conn.execute("INSERT INTO fast_path_background_fetches VALUES (?)", (fetch_status,))
    conn.commit()
    conn.close()


@pytest.mark.parametrize("run_status, fetch_status, expected", [
    ("completed", None, False), ("running", None, True), ("queued", None, True), ("pause_requested", None, True),
    ("paused", "running", True), ("paused", "done", False)])
def test_library_busy(tmp_path, run_status, fetch_status, expected):
    make_library(tmp_path / "deixis.sqlite3", run_status, fetch_status)
    assert launcher.library_busy(tmp_path / "deixis.sqlite3") is expected


def test_an_unreadable_library_counts_as_busy(tmp_path):
    assert launcher.library_busy(tmp_path / "missing.sqlite3") is True


def test_only_http_requests_move_the_last_request_time():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    tracked = launcher.LastRequest(app)
    tracked.at = 0.0
    asyncio.run(tracked({"type": "lifespan"}, None, None))
    assert tracked.at == 0.0
    asyncio.run(tracked({"type": "http"}, None, None))
    assert tracked.at > 0 and seen == ["lifespan", "http"]

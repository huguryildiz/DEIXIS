"""P9 H2, F04: SIGTERM and SIGINT to the launcher, with an event stream open.

The signal goes to the server PID only. A terminal's Ctrl-C reaches the whole foreground process group (the extraction
child too); these tests do not signal a group, so the child of case 3 is left to its own lifetime. Each case reports its
wall time, its exit status and which path it took: graceful (uvicorn finished, the re-raised signal or a normal return
ended the process), or forced (the watchdog in `serve` wrote "did not finish shutting down" and exited with
`FORCED_EXIT_CODE`). The status alone cannot tell them apart (a status of 1 is also Python's generic failure).

Cases: (1) an idle worker; (2) a model call held open; (3) a real extraction of a 60 MiB-decoded PDF in flight, no patch.
SYNTHETIC records, single runs on one machine.
"""

from __future__ import annotations

import signal
import threading
import time

import httpx
import pytest
from deixis import __main__ as deixis_main
from p9_harness import (create_research, descendants, discovery_to_answer_ready, harness, is_same_and_live,  # noqa: F401
                        port_is_free, run_row, start_run, upload, wait_for)

pytestmark = pytest.mark.process
FORCED = getattr(deixis_main, "FORCED_EXIT_CODE", 1)
SIGNALS = [signal.SIGTERM, signal.SIGINT]
LIMIT_SECONDS = 10


def open_stream(server, rid):
    """An event stream read in a thread; returns the stop event. An HTTP error status fails the test."""
    stop, opened, failed = threading.Event(), threading.Event(), []

    def read():
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{server.port}", timeout=None) as client:
                with client.stream("GET", f"/api/researches/{rid}/events/stream") as response:
                    if response.status_code != 200:
                        failed.append(response.status_code)
                        opened.set()
                        return
                    opened.set()
                    for _ in response.iter_lines():
                        if stop.is_set():
                            return
        except httpx.HTTPError as error:  # the server going away after the stream opened is expected
            if not opened.is_set():
                failed.append(repr(error))
                opened.set()

    threading.Thread(target=read, daemon=True).start()
    assert opened.wait(15), "the event stream did not open"
    assert not failed, f"the event stream did not open: {failed}"
    time.sleep(0.5)
    return stop


def shut_down(server, sig, expect_forced):
    """Signal the server PID and check: exit within the limit, the expected path (graceful or forced), the exit status,
    the port free, no `network` line in the call log, and no recorded descendant still alive except the real extraction
    child of case 3, which is left to its own lifetime (children test)."""
    recorded = server.h.record_descendants(server.pid)
    started = time.monotonic()
    server.signal(sig)
    code = server.wait(40)
    took = time.monotonic() - started
    forced = "did not finish shutting down" in server.log_text()
    name = signal.Signals(sig).name
    print(f"F04 {name}: exit {code} after {took:.2f} s, {'forced' if forced else 'graceful'}")
    assert took <= LIMIT_SECONDS, f"{name}: {took:.1f} s to exit (status {code}, {'forced' if forced else 'graceful'})"
    assert forced == expect_forced, f"{name}: expected {'forced' if expect_forced else 'graceful'}, status {code}\n{server.log_text()[-600:]}"
    assert code == (FORCED if forced else code) and (forced or code in (0, -sig)), (code, forced)
    assert not server.alive() and port_is_free(server.port)
    live = [i for i in recorded if is_same_and_live(i)]
    children = {str(i.pid) for i in live if "deixis.documents.pdf" in i.command}
    # The orphan guard of a surviving extraction child is its companion and ends with it; a guard whose child is gone is a leak.
    left = [i for i in live if "deixis.documents.pdf" not in i.command
            and not ("deixis.documents.child_guard" in i.command and i.command.split("child_guard", 1)[1].split()[:1] and i.command.split("child_guard", 1)[1].split()[0] in children)]
    assert not left, f"{name}: descendants still alive after the server exited: {[(i.pid, i.command[:80]) for i in left]}"
    server.no_network()
    return took


@pytest.mark.parametrize("sig", SIGNALS)
def test_f04_idle_worker(harness, tmp_path, sig):
    server = harness.start_server(tmp_path / "data", "idle")
    rid = create_research(server.client, "attached_and_academic")
    open_stream(server, rid)
    shut_down(server, sig, expect_forced=False)


@pytest.mark.parametrize("sig", SIGNALS)
def test_f04_model_call_in_flight(harness, tmp_path, sig):
    data = tmp_path / "data"
    server = harness.start_server(data, "held", P9_HOLD_TASK="grounded_answer")
    c = server.client
    rid = create_research(c, "attached_and_academic")
    discovery_to_answer_ready(c, rid)
    answer = start_run(c, rid, "answer")
    server.wait_held("model", task="grounded_answer")
    open_stream(server, rid)
    shut_down(server, sig, expect_forced=True)
    again = harness.start_server(data, "again")
    recovered = again.health()["recovered"]
    assert recovered["runs"] == 1 and recovered["steps"] == 1, recovered
    row = run_row(again.client, rid, answer)
    assert (row["status"], row["pause_reason"]) == ("paused", "backend_restarted"), row
    again.no_network()


@pytest.mark.parametrize("sig", SIGNALS)
def test_f04_extraction_in_flight(harness, tmp_path, sig):
    from scripts.p9 import memory_probe

    big = tmp_path / "big.pdf"
    memory_probe.build_pdf(big, 60 * 1024 * 1024)
    server = harness.start_server(tmp_path / "data", "extracting")
    rid = create_research(server.client, "attached")
    open_stream(server, rid)

    def send():
        try:
            client = httpx.Client(base_url=f"http://127.0.0.1:{server.port}", timeout=120,
                                  headers={"x-deixis-csrf": server.client.headers["x-deixis-csrf"]})
            client.cookies.update(server.client.cookies)
            upload(client, rid, "big.pdf", big.read_bytes(), timeout=120)
        except httpx.HTTPError:
            pass

    threading.Thread(target=send, daemon=True).start()
    child = wait_for(lambda: next((i for i in descendants(server.pid) if "deixis.documents.pdf" in i.command), None), 30,
                     "the real extraction child")
    harness.track(child)
    assert is_same_and_live(child), "the real extraction child is not alive before the signal: the signal would not hit an extraction"
    shut_down(server, sig, expect_forced=(sig == signal.SIGINT))
    print(f"F04 case 3: extraction child {'alive' if is_same_and_live(child) else 'gone'} at the server's exit (left to its own lifetime)")

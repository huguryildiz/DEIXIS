"""The hard lifetime of an extraction child (P9 H2): SIGALRM ends it even inside a C call, whatever its parent does."""

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from deixis.documents import arxiv_source, jats, ocr, pdf

BACKEND = str(Path(__file__).resolve().parents[2] / "backend")
CHILD = ("import sys, time; sys.path[:0] = [%r]; from deixis.documents import pdf; pdf._watch_memory(10**12); "
         "print('armed', flush=True); time.sleep(30)" % BACKEND)


@pytest.mark.skipif(not hasattr(signal, "alarm"), reason="no SIGALRM on this platform")
def test_child_ends_by_alarm_inside_a_c_call():
    started = time.monotonic()
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdout=subprocess.PIPE, text=True,
                             env={"DEIXIS_CHILD_LIFETIME_SECONDS": "1", "PYTHONPATH": BACKEND})
    try:
        line: list[str] = []
        reader = threading.Thread(target=lambda: line.append(child.stdout.readline()), daemon=True)
        reader.start()
        reader.join(10)
        assert line, "the child did not print 'armed' within 10 s: it did not start or `_watch_memory` did not return"
        assert line[0].strip() == "armed", line
        armed = time.monotonic()
        code = child.wait(timeout=10)
    finally:
        child.kill()
        child.wait()
    ended = time.monotonic()
    assert code == -signal.SIGALRM
    assert ended - started >= 0.9 and ended - armed <= 6


def test_default_lifetime_is_above_every_parent_clock():
    assert pdf.CHILD_LIFETIME_SECONDS > max(pdf.TIMEOUT_SECONDS, ocr.TIMEOUT_SECONDS, jats.RENDER_TIMEOUT_SECONDS,
                                            arxiv_source.CHILD_TIMEOUT_SECONDS)

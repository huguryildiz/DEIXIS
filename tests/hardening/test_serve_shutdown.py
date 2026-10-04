"""The shutdown watchdog of `deixis serve` (P9 H2, F04), driven with a fake server and a recording exit function."""

import threading
import time
from types import SimpleNamespace

from deixis import __main__ as launcher


def start(server, seconds, cancel):
    exits = []
    thread = threading.Thread(target=launcher.watch_shutdown, args=(server, seconds, exits.append, cancel), daemon=True)
    thread.start()
    return thread, exits


def test_no_exit_while_the_server_is_not_asked_to_stop():
    server, cancel = SimpleNamespace(should_exit=False), threading.Event()
    thread, exits = start(server, 0.2, cancel)
    time.sleep(0.6)
    assert exits == [] and thread.is_alive()
    cancel.set()
    thread.join(2)


def test_exits_once_with_the_forced_code_after_the_grace_period(capsys):
    server, cancel = SimpleNamespace(should_exit=False), threading.Event()
    thread, exits = start(server, 0.3, cancel)
    server.should_exit = True
    thread.join(5)
    assert exits == [launcher.FORCED_EXIT_CODE]
    assert "did not finish shutting down" in capsys.readouterr().err


def test_no_exit_when_cancelled_first():
    server, cancel = SimpleNamespace(should_exit=True), threading.Event()
    thread, exits = start(server, 5.0, cancel)
    time.sleep(0.3)
    cancel.set()
    thread.join(2)
    assert exits == [] and not thread.is_alive()


def test_defaults():
    assert launcher.SHUTDOWN_EXIT_SECONDS == 6.0 and launcher.FORCED_EXIT_CODE == 1

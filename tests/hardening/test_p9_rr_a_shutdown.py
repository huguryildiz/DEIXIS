"""A failed watchdog diagnostic must never prevent the forced exit."""

import threading
from types import SimpleNamespace

import pytest

from deixis import __main__ as launcher


@pytest.mark.parametrize("where,error", [("write", OSError(28, "full")), ("flush", OSError(28, "full")),
                                        ("write", ValueError("closed stream"))])
def test_watchdog_exits_even_when_stderr_fails(monkeypatch, where, error):
    class BrokenStderr:
        def write(self, text):
            if where == "write":
                raise error

        def flush(self):
            if where == "flush":
                raise error

    exits = []
    monkeypatch.setattr(launcher.sys, "stderr", BrokenStderr())
    try:
        launcher.watch_shutdown(SimpleNamespace(should_exit=True), 0, exits.append, threading.Event())
    finally:
        assert exits == [launcher.FORCED_EXIT_CODE]

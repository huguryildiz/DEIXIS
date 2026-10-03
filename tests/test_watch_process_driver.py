"""Driver guards can be tested without binding or opening a socket."""

import asyncio
import socket

import pytest

from tests.process import watch_driver


def test_watch_driver_refuses_and_logs_connect_connect_ex_and_dns(monkeypatch):
    events, local_calls = [], []
    monkeypatch.setattr(watch_driver, "log", lambda **entry: events.append(entry))
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: local_calls.append(address))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: local_calls.append(address) or 0)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: local_calls.append(host) or [])
    watch_driver.guard_network()
    with socket.socket() as sock:
        with pytest.raises(OSError, match="non-loopback"): sock.connect(("203.0.113.1", 9999))
        with pytest.raises(OSError, match="non-loopback"): sock.connect_ex(("203.0.113.1", 9999))
        with pytest.raises(OSError, match="non-loopback"): socket.getaddrinfo("synthetic.invalid", 443)
        with pytest.raises(OSError, match="non-loopback"): socket.getaddrinfo("127.synthetic.invalid", 443)
        sock.connect(("127.0.0.1", 9999)); sock.connect_ex(("::1", 9999))
        socket.getaddrinfo(b"127.0.0.1", 9999)
    assert [e["what"] for e in events] == ["connect", "connect_ex", "getaddrinfo", "getaddrinfo"]
    assert all(e["kind"] == "network" for e in events) and len(local_calls) == 3


def test_watch_driver_model_adapter_fails_immediately_and_logs(monkeypatch):
    events = []
    monkeypatch.setattr(watch_driver, "log", lambda **entry: events.append(entry))
    with pytest.raises(AssertionError, match="every model call"):
        asyncio.run(watch_driver.NoModel().run_step())
    assert events == [{"kind": "model"}]


def test_watch_driver_logs_tick_counts_only_after_tick_returns(monkeypatch):
    events = []
    result = {"recorded": ["gap"], "queued": ["check"], "skipped": []}
    def tick(self):
        assert not events
        return result
    monkeypatch.setattr(watch_driver, "log", lambda **entry: events.append(entry))
    monkeypatch.setattr(watch_driver.WatchScheduler, "tick", tick)
    watch_driver.log_ticks()
    assert watch_driver.WatchScheduler.tick(object()) is result
    assert events == [{"kind": "tick", "recorded": 1, "queued": 1}]

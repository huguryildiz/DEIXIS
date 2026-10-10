"""Production serve with file-owned SYNTHETIC OpenAlex answers and no model access."""

import argparse
import asyncio
import functools
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend"), str(REPO)]

import httpx
from deixis import __main__ as deixis_main
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.workflow.watch.scheduler import WatchScheduler
from deixis.workflow.watch.store import WatchStore
from tests.fakes import FakeAdapter


def log(**fields):
    fields.update(pid=os.getpid(), monotonic=time.monotonic())
    fd = os.open(os.environ["P9_CALLS"], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(fields) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def local(host):
    if isinstance(host, bytes): host = host.decode("ascii")
    if host in (None, "localhost"): return True
    try: return ipaddress.ip_address(host).is_loopback
    except ValueError: return False


def guard_network():
    real_connect, real_connect_ex, real_dns = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
    def guard(address, what):
        if isinstance(address, (str, bytes)): return  # AF_UNIX
        if not local(address[0]):
            log(kind="network", what=what, address=str(address))
            raise OSError("watch driver: non-loopback network refused")
    def connect(self, address):
        guard(address, "connect"); return real_connect(self, address)
    def connect_ex(self, address):
        guard(address, "connect_ex"); return real_connect_ex(self, address)
    def dns(host, *args, **kwargs):
        if not local(host):
            log(kind="network", what="getaddrinfo", address=str(host))
            raise OSError("watch driver: non-loopback DNS refused")
        return real_dns(host, *args, **kwargs)
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, dns


class NoModel(FakeAdapter):
    async def run_step(self, *args, **kwargs):
        log(kind="model")
        raise AssertionError("watch process test forbids every model call")


async def openalex(request):
    assert request.url.host == "api.openalex.org", request.url
    log(kind="provider", path=request.url.path, query=str(request.url.query))
    if os.environ.get("P9_HOLD_REQUEST") == "1":
        log(kind="held", what="request")
        await asyncio.sleep(3600)
    if ready := os.environ.get("P9_READY_FILE"):
        # Keep HTTP startup responsive until the test is ready to cut completion.
        while not Path(ready).exists(): await asyncio.sleep(.01)
    return httpx.Response(200, json=json.loads(Path(os.environ["P9_ANSWERS"]).read_text()))


def hold_completion():
    complete = WatchStore.complete_check
    def held(self, check, *args, **kwargs):
        log(kind="held", what="completion", check_id=check["id"], run_id=check["run_id"])
        time.sleep(3600)
        return complete(self, check, *args, **kwargs)
    WatchStore.complete_check = held


def log_ticks():
    tick = WatchScheduler.tick
    def observed(self):
        result = tick(self)
        log(kind="tick", recorded=len(result["recorded"]), queued=len(result["queued"]))
        return result
    WatchScheduler.tick = observed


async def no_fetch(*args, **kwargs):
    log(kind="network", what="fetch")
    raise AssertionError("watch process tests forbid document fetching")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.port in {8765, *range(8858, 8865)}: raise SystemExit("watch driver: forbidden port")
    if not args.data_dir.resolve().is_relative_to(Path(os.environ["P9_TEMP_ROOT"]).resolve()):
        raise SystemExit("watch driver requires a library under the test temporary directory")
    guard_network()
    log_ticks()
    if os.environ.get("P9_HOLD_COMPLETION") == "1": hold_completion()
    settings = Settings(data_dir=args.data_dir, port=args.port, model_concurrency=1, protocol_approval="as_proposed",
        search_query="code", fulltext_fetch="off", fulltext_adjudication="off", arxiv_source="off")
    deixis_main.create_app = functools.partial(create_app, adapters={"fake": NoModel()},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(openalex)), fetcher=no_fetch, xml_fetcher=no_fetch)
    raise SystemExit(deixis_main.serve(settings, False, ()))


if __name__ == "__main__":
    main()

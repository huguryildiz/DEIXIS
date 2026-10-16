"""Tool version/health probes (A3b, E16): bounded in time and output, decoded safely, never holding up the API."""

import asyncio
import os
import threading
import time

import httpx
from fastapi.testclient import TestClient

from deixis import tool_probe
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import ocr
from deixis.models.adapter import CodexAdapter
from fakes import FakeAdapter

HANGS = "#!/bin/sh\nsleep 600\n"
CP1254 = b"#!/bin/sh\nprintf 'S\\374r\\374m 1.2.3 \\376\\375 \\200\\n'\n"  # "Sürüm" in cp1254 plus bytes invalid in UTF-8


def script(path, body):
    path.write_bytes(body if isinstance(body, bytes) else body.encode())
    path.chmod(0o755)
    return path


def test_a_tool_that_never_answers_is_killed_and_reported_not_responding(tmp_path):
    pid_file = tmp_path / "pid"
    tool = script(tmp_path / "hang", f"#!/bin/sh\nsleep 600 &\necho $! > {pid_file}\nwait\n")
    started = time.monotonic()
    result = asyncio.run(tool_probe.probe([str(tool), "--version"], timeout=0.5))
    assert time.monotonic() - started < 3
    assert (result.error, result.ok, result.returncode) == ("not_responding", False, None)
    # The child it started went with it: the whole process group is killed, not only the launcher.
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the probe left the tool's child running")


def test_output_is_decoded_with_replacement_and_bounded(tmp_path):
    odd = asyncio.run(tool_probe.probe([str(script(tmp_path / "odd", CP1254))]))
    assert odd.ok and odd.stdout.startswith("S�r�m 1.2.3 ")
    loud = script(tmp_path / "loud", "#!/bin/sh\nhead -c 1000000 /dev/zero | tr '\\0' 'x'\necho done >&2\n")
    bounded = asyncio.run(tool_probe.probe([str(loud)], timeout=3))
    assert bounded.error is None and len(bounded.stdout) == tool_probe.OUTPUT_LIMIT


def test_a_tool_that_cannot_start_is_reported_failed(tmp_path):
    assert tool_probe.probe_blocking([str(tmp_path / "missing"), "--version"]).error == "failed"


def test_a_hung_codex_does_not_hold_up_the_api_or_the_other_connections(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "codex", HANGS)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(tool_probe, "PROBE_TIMEOUT", 2.0)
    codex = CodexAdapter(tmp_path / "codex-home", tmp_path / "workspace")
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"codex": codex, "fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        replies = {}

        def check(name, url):
            started = time.monotonic()
            replies[name] = (client.get(url).json(), time.monotonic() - started)

        slow = threading.Thread(target=check, args=("connections", "/api/connections?refresh=true"))
        slow.start()
        time.sleep(0.3)  # the codex probe is now waiting on the hung CLI
        check("health", "/api/health")
        slow.join(10)
    health, health_seconds = replies["health"]
    assert health["status"] == "ok" and health_seconds < 1  # answered while the codex probe was still waiting
    connections, seconds = replies["connections"]
    assert seconds < 5
    status = connections["models"]["codex"]
    assert (status["installed"], status["ready"], status["reason_code"]) == (True, False, "timeout")
    assert status["reason"] == "Codex CLI is not responding"
    assert connections["models"]["fake"]["ready"] is True  # the other connection's check is not hidden


def test_tesseract_with_undecodable_output_still_reports(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "tesseract", b"#!/bin/sh\nif [ \"$1\" = --version ]; then printf 'tesseract 5.5.2 \\376\\375\\n'; "
                                  b"else printf 'List of available languages (2):\\neng\\ntur \\377\\n'; fi\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    status = ocr.tesseract_status(("eng",))
    assert (status["available"], status["version"], status["languages"]) == (True, "5.5.2", ["eng"])

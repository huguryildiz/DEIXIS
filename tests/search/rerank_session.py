"""Synthetic discovery session for local reranker tests."""

import time

import httpx

from deixis.api.app import create_app
from deixis.providers.registry import CONNECTORS
from deixis.runtime.config import Settings
from fakes import FakeAdapter, valid_response
from test_ranking_flow import Pool, client_of, discover, no_fetch, wait
from windows_env import WAIT_FACTOR


class FakeLocal:
    def __init__(self):
        self.busy, self.client = {}, None
        self.paths = None

    def available(self, model_id):
        return False

    async def close(self, model_id=None):
        pass


class Session:
    def __init__(self, tmp_path, monkeypatch, handler=None, local=None, **kwargs):
        for connector in CONNECTORS.values():
            if connector.key_env:
                monkeypatch.delenv(connector.key_env, raising=False)
        monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
        self.handler = handler or Pool()
        self.local = local or FakeLocal()
        self.app = create_app(
            Settings(data_dir=tmp_path / "data", port=8765, fulltext_fetch="off"),
            adapters={"fake": FakeAdapter(valid_response)},
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)),
            fetcher=no_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",),
            local_embedder=self.local,
        )
        self.client = client_of(self.app)
        self.store = self.app.state.store

    def close(self):
        self.client.__exit__(None, None, None)

    def discover(self, **body):
        return discover(self.client, **body)

    def settled(self, rid, run_id):
        deadline = time.time() + 30 * WAIT_FACTOR
        while time.time() < deadline:
            run = next(r for r in self.client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)
            if run["status"] in ("completed", "failed", "paused", "cancelled"):
                return run
            time.sleep(0.05)
        raise AssertionError("the run did not settle")

    def pause(self, run_id=None):
        run_id = run_id or self.latest_run()
        self.store.update_run(run_id, event="run_pause_requested", status="pause_requested", pause_reason="user_requested")

    def latest_run(self):
        return self.store.conn.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()[0]

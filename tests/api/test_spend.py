"""Estimated spending for paid-API models (pre-P10 F4): cost from usage and a dated price table, the daily ledger, the
stopping threshold at a call boundary and the estimate before a research starts.

Workflow behavior only. The usage numbers are SYNTHETIC and the prices are the ones in `models/model_prices.json`; passing
shows the arithmetic, the ledger, the pause and the estimate behave as the plan says. It does not show that the
price table matches a provider's bill today, and no real model was called.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.domain import skill
from deixis.workflow import spend, spend_estimate
from fakes import FakeAdapter
from test_api_flow import create, fake_fetch, openalex_client, session, sw_settings, wait_run

# deepseek-flash: $0.30 per million input tokens, $1.20 per million output tokens.
CALL_USAGE = {"prompt_tokens": 20_000, "completion_tokens": 0, "total_tokens": 20_000}  # $0.006 a call


class PaidAdapter(FakeAdapter):
    """A fake that answers as a paid-API connection and reports usage like one."""

    connection = "deepseek"

    def __init__(self, usage=CALL_USAGE):
        super().__init__()
        self.usage = usage

    async def run_step(self, *args, **kwargs):
        result = await super().run_step(*args, **kwargs)
        result.token_usage = self.usage
        return result


def served(tmp_path, adapter):
    return create_app(sw_settings(tmp_path), adapters={"deepseek": adapter}, http_client=openalex_client(), fetcher=fake_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def paid_research(client):
    return create(client, model_connection="deepseek", requested_model="deepseek-flash")


def ledger(app):
    return [dict(r) for r in app.state.store.conn.execute("SELECT * FROM spend_ledger ORDER BY recorded_at, session_id")]


# ---- cost from usage and the price table ---------------------------------------------------------------------------


# ---- the ledger ------------------------------------------------------------------------------------------------------


def make_session(store, connection="deepseek", model="deepseek-flash", n=[0]):
    n[0] += 1
    rid = store.create_research("SYNTHETIC spend question", "academic", "quick", ["openalex"], connection, model, None)
    run = store.create_run(rid, "discovery", {}, None)
    step = store.step(run["id"], f"abstract_screening:{n[0]}", "model:abstract_screening")
    sid = f"sti_spend_{n[0]}"
    store.insert_step_input(step["id"], rid, run["id"], 0, {"step_input_id": sid, "task_type": "abstract_screening",
                            "scope_revision": 1, "skill_package_hash": "pkg"}, "b" * 400, "d" * 400, "m" * 3200, {})
    return rid, store.start_model_session(rid, run["id"], step["id"], sid, connection, model)


def test_a_call_with_usage_is_priced_and_a_call_without_usage_is_estimated_not_zero(tmp_path):
    app = served(tmp_path, PaidAdapter())
    with TestClient(app):
        store = app.state.store
        _, first = make_session(store)
        store.finish_model_session(first, status="completed", raw_output="x", token_usage_json=CALL_USAGE, request_sent=True)
        _, second = make_session(store)
        store.finish_model_session(second, status="completed", raw_output="y" * 400, token_usage_json=None, request_sent=None)
        rows = {r["session_id"]: r for r in ledger(app)}
        assert rows[first]["basis"] == "reported" and rows[first]["cost_usd"] == pytest.approx(0.006)
        # No usage came back: the characters sent (4,000 / 4) and received (400 / 4) stand in, and the row says so.
        assert rows[second]["basis"] == "estimated_from_text" and rows[second]["cost_usd"] > 0
        assert rows[second]["input_tokens"] == 1000
        total = spend.day_total(store.conn, spend.day_of(store.clock))
        assert total["priced_calls"] == 2 and total["estimated_from_text_calls"] == 1 and total["unpriced_calls"] == 0


def test_a_model_with_no_listed_price_is_an_unpriced_call_never_zero_dollars(tmp_path):
    app = served(tmp_path, PaidAdapter())
    with TestClient(app):
        store = app.state.store
        _, sid = make_session(store, connection="mistral", model="mistral-unlisted")
        store.finish_model_session(sid, status="completed", raw_output="x", token_usage_json=CALL_USAGE, request_sent=True)
        row = ledger(app)[0]
        assert row["cost_usd"] is None and row["basis"] == "unpriced" and row["input_tokens"] == 20_000
        total = spend.day_total(store.conn, spend.day_of(store.clock))
        assert total["unpriced_calls"] == 1 and total["priced_calls"] == 0


# ---- the threshold at a call boundary ----------------------------------------------------------------------------------


def wait_status(client, rid, run_id, status):
    deadline = time.time() + 20
    while time.time() < deadline:
        run = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)
        if run["status"] == status:
            return run
        time.sleep(0.1)
    raise AssertionError(f"run is {run['status']}, not {status}")


def test_crossing_the_threshold_during_a_call_stores_its_result_and_no_next_call_is_sent(tmp_path):
    adapter = PaidAdapter()
    app = served(tmp_path, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        rid = paid_research(client)
        # $0.006 a call: the second call takes the day to $0.012, over the $0.01 threshold.
        client.put("/api/settings/spending", json={"daily_threshold_usd": 0.01})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        paused = wait_status(client, rid, run["id"], "paused")
        assert paused["pause_reason"] == "spend_threshold"
        assert paused["error"]["threshold_usd"] == 0.01 and paused["error"]["estimated_usd"] == pytest.approx(0.012)
        # The call that crossed was stored (its session, its usage, its ledger row); the third was never sent.
        assert len(adapter.calls) == 2
        rows = ledger(app)
        assert len(rows) == 2 and all(r["basis"] == "reported" for r in rows)
        sessions = app.state.store.conn.execute("SELECT status, token_usage_json FROM model_sessions").fetchall()
        assert [s["status"] for s in sessions] == ["completed", "completed"]
        assert all(json.loads(s["token_usage_json"]) == CALL_USAGE for s in sessions)

        # Resume asks again: still over, so it pauses at once and sends nothing. Raising the threshold does not resume it.
        client.post(f"/api/runs/{run['id']}/resume")
        again = wait_status(client, rid, run["id"], "paused")
        assert again["pause_reason"] == "spend_threshold" and len(adapter.calls) == 2
        client.put("/api/settings/spending", json={"daily_threshold_usd": 500})
        time.sleep(0.5)
        assert next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run["id"])["status"] == "paused"
        assert len(adapter.calls) == 2

        # The person presses Resume: it re-checks, finds room, and the run goes on to the end.
        client.post(f"/api/runs/{run['id']}/resume")
        _, finished = wait_run(client, rid, run["id"], statuses=("completed", "failed", "cancelled"))
        assert finished["status"] == "completed" and len(adapter.calls) > 2


# ---- the estimate before a research starts ------------------------------------------------------------------------------


def roles(literature=("deepseek", "deepseek-flash"), answer=("deepseek", "deepseek-flash"), reviewer=("deepseek", "deepseek-flash"), effort="medium"):
    def role(choice):
        return {"connection": choice[0], "model": choice[1], "reasoning_effort": effort} if choice else None
    return {"literature": role(literature), "answer": role(answer), "reviewer": role(reviewer)}


def estimate(depth="standard", **kwargs):
    return spend_estimate.estimate(skill.load_skill_package(), depth, roles(**kwargs), reading_on=True, embedding_provider="builtin")


def test_the_estimate_route_reads_the_embedding_choice(tmp_path):
    with TestClient(served(tmp_path, PaidAdapter())) as raw:
        client = session(raw)
        choice = {"connection": "deepseek", "model": "deepseek-flash", "reasoning_effort": None}
        body = {"effort": "quick", "literature": choice, "answer": choice, "reviewer": None}
        response = client.post("/api/spend/estimate", json=body)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["usd"][0] < data["usd"][1] and data["embedding"]["included"] is False
        assert client.post("/api/spend/estimate", json=body | {"effort": "huge"}).status_code == 422



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
from deixis.models.adapter import ModelStepResult
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


def test_cost_is_computed_from_each_providers_usage_shape_and_the_price_table():
    flash = spend.price_for("deepseek", "deepseek-flash")
    openai_chat = spend.usage_tokens({"prompt_tokens": 1000, "completion_tokens": 500, "prompt_tokens_details": {"cached_tokens": 400}})
    assert openai_chat == {"input": 1000, "cached_input": 400, "cache_write": 0, "output": 500}
    assert spend.cost_of(flash, openai_chat) == pytest.approx((600 * 0.3 + 400 * 0.006 + 500 * 1.2) / 1e6)
    responses = spend.usage_tokens({"input_tokens": 10, "output_tokens": 20, "output_tokens_details": {"reasoning_tokens": 5}})
    assert (responses["input"], responses["output"]) == (10, 20)  # reasoning is already inside the output count
    anthropic = spend.usage_tokens({"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0})
    assert anthropic == {"input": 1000, "cached_input": 900, "cache_write": 0, "output": 50}
    gemini = spend.usage_tokens({"promptTokenCount": 700, "candidatesTokenCount": 100, "thoughtsTokenCount": 300})
    assert gemini["output"] == 400  # thinking tokens are billed as output
    deepseek = spend.usage_tokens({"prompt_tokens": 100, "completion_tokens": 10, "prompt_cache_hit_tokens": 60, "prompt_cache_miss_tokens": 40})
    assert deepseek["cached_input"] == 60


def test_usage_without_both_counts_is_not_a_cost_and_an_unlisted_model_has_no_price():
    assert spend.usage_tokens(None) is None
    assert spend.usage_tokens({"prompt_tokens": 5}) is None
    assert spend.usage_tokens({"total_tokens": 5}) is None
    assert spend.price_for("mistral", "mistral-large-latest") is None
    assert spend.price_for("openai", "gpt-not-in-the-table") is None
    # A dated snapshot takes its alias's price; nothing else is guessed from a name.
    assert spend.price_for("anthropic", "claude-haiku-4-5-20251001") == spend.price_for("anthropic", "claude-haiku-4-5")
    assert spend.price_for("openai", "gpt-5.4-mini-2026-03-17") == spend.price_for("openai", "gpt-5.4-mini")


def test_only_per_call_connections_are_priced():
    assert spend.kind_of("deepseek") == spend.kind_of("openai") == spend.kind_of("mistral") == "api"
    assert spend.kind_of("codex") == spend.kind_of("claude") == spend.kind_of("gemini_cli") == "subscription"
    assert spend.kind_of("ollama") == spend.kind_of("local_server") == "local"
    assert spend.kind_of(None) == "none"


def test_the_price_table_is_dated_and_versioned():
    table = spend.price_table()
    assert table["version"] == 1 and table["as_of"] == "2026-10-16"
    assert all(set(prices) >= {"input", "output"} for models in table["models"].values() for prices in models.values())


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


def test_a_call_that_never_reached_the_provider_or_ran_on_a_subscription_leaves_no_row(tmp_path):
    app = served(tmp_path, PaidAdapter())
    with TestClient(app):
        store = app.state.store
        _, refused = make_session(store)
        store.finish_model_session(refused, status="unavailable", raw_output=None, token_usage_json=None, request_sent=False)
        _, subscription = make_session(store, connection="codex", model="gpt-5.6-luna")
        store.finish_model_session(subscription, status="completed", raw_output="x", token_usage_json=CALL_USAGE, request_sent=True)
        assert ledger(app) == []


def test_a_call_out_when_the_process_stopped_counts_as_spent(tmp_path):
    app = served(tmp_path, PaidAdapter())
    with TestClient(app):
        store = app.state.store
        _, sid = make_session(store)  # started, never finished
        app.state.worker.recover()
        assert store.conn.execute("SELECT status FROM model_sessions WHERE id = ?", (sid,)).fetchone()[0] == "outcome_unknown"
        row = ledger(app)[0]
        assert row["session_id"] == sid and row["basis"] == "estimated_from_text" and row["cost_usd"] > 0


def test_deleting_a_research_does_not_lower_the_days_total(tmp_path):
    app = served(tmp_path, PaidAdapter())
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid, sid = make_session(store)
        store.finish_model_session(sid, status="completed", raw_output="x", token_usage_json=CALL_USAGE, request_sent=True)
        before = client.get("/api/settings/spending").json()["today"]
        assert before["estimated_usd"] == pytest.approx(0.006)
        store.conn.execute("UPDATE runs SET status = 'completed' WHERE research_id = ?", (rid,))  # nothing active blocks the delete
        store.conn.commit()
        assert client.delete(f"/api/researches/{rid}").status_code == 200
        assert client.delete(f"/api/trash/{rid}").status_code == 200
        assert store.conn.execute("SELECT COUNT(*) FROM model_sessions WHERE id = ?", (sid,)).fetchone()[0] == 0
        assert client.get("/api/settings/spending").json()["today"] == before


# ---- the threshold at a call boundary ----------------------------------------------------------------------------------


def test_the_threshold_is_off_by_default_and_can_be_set_and_cleared(tmp_path):
    with TestClient(served(tmp_path, PaidAdapter())) as raw:
        client = session(raw)
        assert client.get("/api/settings/spending").json()["daily_threshold_usd"] is None
        assert client.put("/api/settings/spending", json={"daily_threshold_usd": 2.5}).json()["daily_threshold_usd"] == 2.5
        assert client.put("/api/settings/spending", json={"daily_threshold_usd": 0}).status_code == 422
        assert client.put("/api/settings/spending", json={}).status_code == 422
        assert client.put("/api/settings/spending", json={"daily_threshold_usd": None}).json()["daily_threshold_usd"] is None


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


def test_a_subscription_connection_is_never_held_by_the_threshold(tmp_path):
    adapter = FakeAdapter()  # connection "fake": no per-call price
    app = create_app(sw_settings(tmp_path), adapters={"fake": adapter}, http_client=openalex_client(), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        client.put("/api/settings/spending", json={"daily_threshold_usd": 0.01})
        app.state.store.conn.execute(
            "INSERT INTO spend_ledger (session_id, day, connection, model, cost_usd, basis, recorded_at)"
            " VALUES ('x', ?, 'openai', 'gpt-5', 5.0, 'reported', 'now')", (spend.day_of(app.state.store.clock),))
        app.state.store.conn.commit()
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        _, finished = wait_run(client, rid, run["id"])
        assert finished["status"] == "completed"


# ---- the estimate before a research starts ------------------------------------------------------------------------------


def roles(literature=("deepseek", "deepseek-flash"), answer=("deepseek", "deepseek-flash"), reviewer=("deepseek", "deepseek-flash"), effort="medium"):
    def role(choice):
        return {"connection": choice[0], "model": choice[1], "reasoning_effort": effort} if choice else None
    return {"literature": role(literature), "answer": role(answer), "reviewer": role(reviewer)}


def estimate(depth="standard", **kwargs):
    return spend_estimate.estimate(skill.load_skill_package(), depth, roles(**kwargs), reading_on=True, embedding_provider="builtin")


def test_the_estimate_is_a_wide_range_that_grows_with_depth():
    quick, standard, detailed = (estimate(d)["usd"] for d in ("quick", "standard", "detailed"))
    for low, high in (quick, standard, detailed):
        assert 0 < low < high
        assert high > 3 * low  # never a narrow, confident-looking figure
    assert quick[1] < standard[1] < detailed[1]
    result = estimate()
    assert result["complete"] and result["embedding"] == {"provider": "builtin", "paid": False, "included": False}
    assert result["prices"] == {"version": 1, "as_of": "2026-10-16"}
    # The fixed part of each call is measured from the loaded method files, not assumed.
    assert all(t["input_tokens"][0] > 1000 for t in result["tasks"])


def test_unknown_price_gives_no_estimate_and_non_paid_roles_are_left_out():
    unknown = estimate(literature=("mistral", "mistral-unlisted"), answer=("mistral", "mistral-unlisted"), reviewer=None)
    assert unknown["applies"] and unknown["usd"] is None and not unknown["complete"]
    assert all(r["usd"] is None for r in unknown["roles"])
    mixed = estimate(literature=("codex", "gpt-5.6-luna"), answer=("deepseek", "deepseek-flash"), reviewer=None)
    assert mixed["complete"] and mixed["usd"] is not None
    by_role = {r["role"]: r for r in mixed["roles"]}
    assert by_role["literature"]["kind"] == "subscription" and by_role["literature"]["usd"] is None
    partly = estimate(literature=("mistral", "mistral-unlisted"), answer=("deepseek", "deepseek-flash"), reviewer=None)
    assert partly["usd"] is not None and not partly["complete"]  # only the priced role is counted, and it says so
    free = estimate(literature=("codex", "x"), answer=("claude", "y"), reviewer=("ollama", "z"))
    assert not free["applies"] and free["usd"] is None


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

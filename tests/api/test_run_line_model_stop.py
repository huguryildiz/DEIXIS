"""P9 H7 item 04: the run view carries what the run line shows under a model stop. SYNTHETIC, no model, no network."""

from pathlib import Path

from fastapi.testclient import TestClient

from deixis.models.adapter import ModelStepResult
from fakes import PLANNING_TASKS, FakeAdapter
from test_api_flow import app_for, create, session, wait_run

TESTS = Path(__file__).parent.parent


# ---- item 04: the run view carries what the run line shows under a model stop ---------------------------------

def paused_run(tmp_path, adapter, *, with_step=False):
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        paused = wait_run(client, rid, run["id"])[1]
        if with_step:
            return paused, client.app.state.store.existing_step(run["id"], "search_query:1")
        return paused


class DownAfterPlanning(FakeAdapter):
    """A connection that answers while the plan is written and is not ready afterwards.

    Nothing is searched without a plan, so a connection that is not ready from the start stops the run at the
    query itself; the stop this item is about is the next one, where a step is sent to a connection that has
    gone down.
    """

    def __init__(self, **kwargs):
        super().__init__(before=lambda si: self._planned(si), **kwargs)
        self.planning_done = False

    def _planned(self, si):
        if si["task_type"] in ("search_query", "search_plan"):
            self.planning_done = True

    async def health(self, refresh: bool = False):
        if self.planning_done:
            return {"connection": "fake", "ready": False, "reason": "fake not ready"}
        return await super().health(refresh)


def test_a_paused_run_for_a_connection_that_is_not_ready_carries_the_connections_reason(tmp_path):
    run = paused_run(tmp_path, DownAfterPlanning())
    assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready")
    assert run["error"] == {"connection": "fake", "reason": "fake not ready", "reset_at": None}


def test_a_paused_run_after_a_model_failure_carries_the_connections_own_words(tmp_path, monkeypatch):
    words = "SYNTHETIC usage limit reached, try again after the reset"
    # A failed plan call names its model failure in the pause.
    run, step = paused_run(tmp_path, FakeAdapter(fail=lambda si: ModelStepResult(
        "failed", error=words, delivery_class="before_send") if si["task_type"] == "search_plan" else None),
        with_step=True)
    assert (run["status"], run["pause_reason"]) == ("paused", "search_query_failed")
    assert run["error"]["reason"] == "model_call_failed"
    assert words in step["error_json"]



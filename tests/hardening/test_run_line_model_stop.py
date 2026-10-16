"""P9 H7 item 04 (D165): the run view carries what the run line shows under a model stop. SYNTHETIC, no model, no network."""

from pathlib import Path

from fastapi.testclient import TestClient

from deixis.models.adapter import ModelStepResult
from fakes import FakeAdapter
from test_api_flow import app_for, create, session, wait_run

TESTS = Path(__file__).parent.parent


# ---- item 04: the run view carries what the run line shows under a model stop ---------------------------------

def paused_run(tmp_path, adapter):
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        return wait_run(client, rid, run["id"])[1]


def test_a_paused_run_for_a_connection_that_is_not_ready_carries_the_connections_reason(tmp_path):
    run = paused_run(tmp_path, FakeAdapter(ready=False))
    assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready")
    assert run["error"] == {"connection": "fake", "reason": "fake not ready", "reset_at": None}


def test_a_paused_run_after_a_model_failure_carries_the_connections_own_words(tmp_path):
    words = "SYNTHETIC usage limit reached, try again after the reset"
    run = paused_run(tmp_path, FakeAdapter(fail=lambda si: ModelStepResult("failed", error=words, delivery_class="before_send")))
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    assert run["error"]["error"] == words


def test_the_run_line_uses_safe_fallbacks_and_keeps_the_reason_line():
    labels = (TESTS.parent / "apps" / "web" / "src" / "labels.ts").read_text()
    transcript = (TESTS.parent / "apps" / "web" / "src" / "Transcript.tsx").read_text()
    assert "model_connection_not_ready: 'The selected model connection is not ready. Nothing was sent to another model.'" in labels
    assert "Historical free text is not safe to echo" in labels
    assert "The connection did not complete this call. Check it in Settings before resuming." in labels
    assert transcript.count("pauseDetailText(run)") == 2  # the paused note and the failed/cancelled note

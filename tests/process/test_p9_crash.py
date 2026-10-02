"""P9 H2: SIGKILL while a model step runs (F01) and a second process taking over the data directory (I06).

Real processes, the production launcher (`p9_driver.py`), SYNTHETIC records, a scripted model. They show what the code does
after a kill on one shape each, in single runs; they say nothing about a real model, a real provider or power loss.

The resume sends the cut step again. That is expected behavior, not a defect: the first send is recorded as an
`outcome_unknown` model session and the second is a separate session and a separate budget unit.
"""

from __future__ import annotations

import time

import pytest
from p9_harness import (QUESTION, count, create_research, discovery_to_answer_ready, harness,  # noqa: F401
                        integrity_check, kind_count, rows, run_row, start_run, task_counts, wait_for, wait_run)

pytestmark = pytest.mark.process


def answer_step_and_sessions(data_dir, run_id):
    step = rows(data_dir, "SELECT id, kind, status FROM run_steps WHERE run_id = ? AND kind = 'model:grounded_answer'", (run_id,))
    assert len(step) == 1, [tuple(r) for r in rows(data_dir, "SELECT kind, status FROM run_steps WHERE run_id = ?", (run_id,))]
    sessions = rows(data_dir, "SELECT status FROM model_sessions WHERE step_id = ? ORDER BY rowid", (step[0]["id"],))
    return step[0], [row["status"] for row in sessions]


def test_f01_answer_step_cut_by_sigkill(harness, tmp_path):
    data = tmp_path / "data"
    first = harness.start_server(data, "first", P9_HOLD_TASK="grounded_answer")
    c = first.client
    rid = create_research(c, "attached_and_academic")
    discovery_to_answer_ready(c, rid)
    answer = start_run(c, rid, "answer")
    held = first.wait_held("model", task="grounded_answer")
    assert held["run_id"] == answer
    before = first.calls()
    before_counts, before_fetches = task_counts(before), kind_count(before, "fetch")
    assert before_counts["grounded_answer"] == 1 and before_fetches >= 1, (before_counts, before_fetches)
    first.no_network()
    first.kill9()

    second = harness.start_server(data, "second")
    c = second.client
    assert second.health()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 1}, second.health()
    row = run_row(c, rid, answer)
    assert (row["status"], row["pause_reason"]) == ("paused", "backend_restarted"), row
    step, sessions = answer_step_and_sessions(data, answer)
    assert step["status"] == "outcome_unknown" and sessions == ["outcome_unknown"], (dict(step), sessions)
    assert integrity_check(data) == "ok"

    assert c.post(f"/api/runs/{answer}/resume").status_code in (200, 202)
    row = wait_run(c, rid, answer)
    assert row["status"] == "completed", row
    after = second.calls()
    resumed = task_counts(after)  # the second process's own log: only what it sent after the restart
    # Completed steps: increase 0. The cut step: one more send than the held one.
    for task in before_counts:
        if task != "grounded_answer":
            assert resumed.get(task, 0) == 0, ("a completed step was sent again", task, before_counts, resumed)
    assert resumed.get("grounded_answer") == 1, resumed  # the second process's own log holds only the resend
    total = {task: before_counts.get(task, 0) + resumed.get(task, 0) for task in {*before_counts, *resumed}}
    assert total["grounded_answer"] == 2, total
    new_tasks = {task: n for task, n in resumed.items() if task not in before_counts}
    assert set(new_tasks) <= {"grounded_answer", "answer_review"}, new_tasks
    assert kind_count(after, "fetch") == 0, "a completed fetch step was repeated after the resume"
    assert count(data, "answers", "research_id = ?", (rid,)) == 1
    step, sessions = answer_step_and_sessions(data, answer)
    assert sessions == ["outcome_unknown", "completed"], sessions
    assert row["usage"]["model_calls"] == 2, row["usage"]
    assert row["usage"]["downloads"] == 2, row["usage"]
    second.no_network()
    print("F01 answer:", {"before": before_counts, "after": resumed, "usage": row["usage"], "new_tasks": new_tasks})


def test_f01_discovery_step_cut_by_sigkill(harness, tmp_path):
    data = tmp_path / "data"
    first = harness.start_server(data, "first", P9_HOLD_TASK="abstract_screening", P9_HOLD_NTH="2")
    c = first.client
    rid = create_research(c, "attached_and_academic")
    run = start_run(c, rid, "discovery")
    held = first.wait_held("model", task="abstract_screening")
    assert held["run_id"] == run
    before = first.calls()
    before_counts, before_provider = task_counts(before), kind_count(before, "provider")
    assert before_counts["abstract_screening"] == 2 and before_provider > 0, (before_counts, before_provider)
    first.no_network()
    first.kill9()

    second = harness.start_server(data, "second")
    c = second.client
    assert second.health()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 1}, second.health()
    row = run_row(c, rid, run)
    assert (row["status"], row["pause_reason"]) == ("paused", "backend_restarted"), row
    assert integrity_check(data) == "ok"
    assert c.post(f"/api/runs/{run}/resume").status_code in (200, 202)
    row = wait_run(c, rid, run)
    assert row["status"] == "completed", row
    after = second.calls()
    resumed = task_counts(after)
    for task, n in before_counts.items():
        if task != "abstract_screening":
            assert resumed.get(task, 0) == 0, ("a completed step was sent again", task, before_counts, resumed)
    assert before_counts["abstract_screening"] + resumed["abstract_screening"] == 3, (before_counts, resumed)
    assert kind_count(after, "provider") == 0, "completed searches were repeated after the resume"
    second.no_network()
    print("F01 discovery:", {"before": before_counts, "after": resumed, "provider_before": before_provider,
                             "provider_after": kind_count(after, "provider")})


def test_i06_second_process_takes_over_when_the_owner_is_killed(harness, tmp_path):
    data = tmp_path / "data"
    first = harness.start_server(data, "owner", P9_HOLD_TASK="grounded_answer")
    c = first.client
    rid = create_research(c, "attached_and_academic")
    discovery_to_answer_ready(c, rid)
    answer = start_run(c, rid, "answer")
    first.wait_held("model", task="grounded_answer")
    second = harness.start_server(data, "waiting")
    assert first.health()["worker"] == "owner"
    assert second.health()["worker"] == "not_owner", second.health()
    first.no_network()
    first.kill9()
    killed_at = time.monotonic()
    wait_for(lambda: second.health()["worker"] == "owner", 10, "the second process becoming owner", step=0.2)
    took = time.monotonic() - killed_at
    assert took <= 10
    assert second.health()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 1}, second.health()
    row = run_row(second.client, rid, answer)
    assert (row["status"], row["pause_reason"]) == ("paused", "backend_restarted"), row
    assert second.client.post(f"/api/runs/{answer}/resume").status_code in (200, 202)
    assert wait_run(second.client, rid, answer)["status"] == "completed"
    assert count(data, "answers", "research_id = ?", (rid,)) == 1
    assert integrity_check(data) == "ok"
    second.no_network()
    print(f"I06: takeover {took:.2f} s after the kill")

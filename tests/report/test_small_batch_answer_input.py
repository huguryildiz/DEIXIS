"""Synthetic D238 allocation evidence and the answer whose frozen list is missing; no model or scientific validation.

The small-batch answer input (`_small_batch_answer_passages`) and its abstract route were removed in the clean start
(slice 3b); `small_batch.allocate` stays because the fast path's answer input uses it.
"""

from dataclasses import asdict

import pytest

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.workflow import small_batch
from deixis.workflow.flow import ResearchFlow
from test_criterion_passage_flow import library


def answer_run(store, rid):
    run = store.create_run(rid, "answer", asdict(TEST_EFFORT_BUDGETS["quick"]), None)
    store.update_run(run["id"], status="completed")  # its steps are written here, not by the worker
    return store.run(run["id"])


def flow_of(store):
    flow = object.__new__(ResearchFlow)
    flow.store = store
    return flow


def test_missing_frozen_list_becomes_recorded_failed_answer(tmp_path):
    import asyncio
    from deixis.workflow.flow import RunStopped

    store, rid = library(tmp_path)
    discovery = store.create_run(rid, "discovery", {"inspection": {"policy": small_batch.POLICY}}, None)
    store.update_run(discovery["id"], status="completed")
    run = answer_run(store, rid)
    run["budget"] = small_batch.answer_budget(store, rid, run["scope_revision"], run["budget"])
    flow = flow_of(store)
    flow._held = {}
    with pytest.raises(RunStopped):
        asyncio.run(flow._answer(run, store.scope(rid)))
    failed = store.run(run["id"])
    assert failed["status"] == "failed"
    assert failed["pause_reason"] == "answer_frozen_list_missing"
    assert failed["error"]["list_run_id"] == discovery["id"]


def test_24_work_prefix_uses_depth_before_widening():
    queues = [[{"id": f"{i}:{j}", "source_version_id": str(i)} for j in range(8)] for i in range(30)]
    selected = small_batch.allocate(queues, 48, 6)
    assert [p["id"] for p in selected] == [f"{i}:{j}" for j in range(2) for i in range(24)]
    assert len(small_batch.allocate(queues[:3], 48, 6)) == 18


@pytest.mark.parametrize("limit", [0, 1, 3, 48])
def test_allocation_respects_budget_and_exhausted_queues(limit):
    queues = [[{"id": str(i)}] for i in range(30)]
    selected = small_batch.allocate(queues, limit, 6)
    assert [p["id"] for p in selected] == [str(i) for i in range(min(limit, 30))]

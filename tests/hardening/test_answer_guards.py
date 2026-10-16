"""Runtime guards in the answer path fail with a named reason instead of an assert, and late full-text exclusions are
read from the late-revision ledger. SYNTHETIC rows; workflow rules only."""

import json
import sqlite3

import pytest

from deixis.workflow import fast_answer, fast_path, late_revision
from deixis.workflow.flow import RunStopped


class FakeStore:
    def __init__(self, runs=None, conn=None):
        self.runs, self.conn = runs or {}, conn

    def run(self, run_id):
        return self.runs[run_id]


@pytest.mark.parametrize("change", [{"status": "running"}, {"research_id": "res_OTHER"}, {"scope_revision": 2}])
def test_answer_budget_refuses_a_discovery_that_is_not_this_scopes_completed_run(change):
    discovery = {"research_id": "res_SYNTH", "scope_revision": 1, "status": "completed"} | change
    store = FakeStore({"run_SYNTH": discovery})
    with pytest.raises(ValueError, match="answer_discovery_mismatch"):
        fast_answer.answer_run_budget(store, "res_SYNTH", {"effort": "quick", "revision": 1}, discovery_id="run_SYNTH")


def test_revision_plan_without_its_late_revision_row_fails_the_run_by_name():
    failed = []

    class Flow:
        store = type("S", (), {"existing_step": staticmethod(lambda run_id, key: None)})()

        def _fail(self, run_id, reason, detail=None):
            failed.append((run_id, reason))
            raise RunStopped

    with pytest.raises(RunStopped):
        late_revision.revision_plan(Flow(), {"id": "run_SYNTH", "budget": {}, "target": {}}, {})
    assert failed == [("run_SYNTH", "late_revision_unavailable")]


def ledger(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE runs (kind TEXT, budget_json TEXT)")
    conn.execute("CREATE TABLE fast_path_late_revisions (research_id TEXT, scope_revision INTEGER, read_run_id TEXT,"
                 " works_json TEXT)")
    conn.execute("INSERT INTO runs VALUES ('discovery', ?)", (json.dumps(
        {"fast_path": {"policy": fast_path.POLICY, "late_revision": {"mode": "auto", "max_revisions": 1}}}),))
    conn.executemany("INSERT INTO fast_path_late_revisions VALUES (?, ?, ?, ?)", rows)
    return FakeStore(conn=conn)


def work(work_id, outcome, user_priority=False):
    return {"work_id": work_id, "late_outcome": outcome, "user_priority": user_priority}


def test_excluded_works_are_late_full_text_exclusions_of_this_scope_revision_only():
    works = json.dumps([work("W1", "criterion_not_met"), work("W2", "out_of_scope"), work("W3", "include"),
                        work("W4", "criterion_not_met", user_priority=True)])
    store = ledger([("res_SYNTH", 1, "run_READ", works),
                    ("res_SYNTH", 1, None, json.dumps([work("W5", "out_of_scope")])),  # never read
                    ("res_SYNTH", 2, "run_READ2", json.dumps([work("W6", "out_of_scope")])),
                    ("res_OTHER", 1, "run_READ3", json.dumps([work("W7", "out_of_scope")]))])
    assert late_revision.excluded_works(store, "res_SYNTH", 1) == {"W1", "W2"}
    assert late_revision.excluded_works(store, "res_SYNTH", 2) == {"W6"}


def test_excluded_works_is_empty_under_a_policy_without_the_late_lane():
    store = ledger([("res_SYNTH", 1, "run_READ", json.dumps([work("W1", "out_of_scope")]))])
    store.conn.execute("DELETE FROM runs")
    assert late_revision.excluded_works(store, "res_SYNTH", 1) == set()

"""The live delivery-time pilot's driver: what it fixes before spending anything, and when it calls a run over.

The pilot itself needs paid keys, so what is tested here is everything around the money: the run order frozen
before the first request, the configuration and question files that may not change after it, the reading of when
a run is actually over, and the machine reading that explains an odd run. The one rule worth its own test is that
the discovery run ending is not the answer ending: the product queues a separate answer run, and a pilot that
moved on at the first ending would time the next question while the one before it was still writing.
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.domain import canonical
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.storage import db
from deixis.workflow.run import fast_path
from deixis.workflow.run.store import Store
from deixis.workflow.search import small_batch
from test_fast_path_clock import FakeClock

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))
import delivery_pilot  # noqa: E402

QUESTIONS = ["scripts/benchmark/dbr_vbf.json", "scripts/benchmark/irs2021.json", "scripts/benchmark/kurt2017.json"]
SETTINGS = {"write": {"/api/semantic-search": {"provider": "voyage", "model": "voyage-4-lite"}},
            "pin": {"/api/semantic-search": {"provider": "voyage", "model": "voyage-4-lite"},
                    "/api/effort-limits": {"efforts": {"standard": {"papers": 50, "fulltext": 20}}}},
            "record": ["/api/settings"]}


def config(**edits):
    base = {"name": "pilot", "questions": list(QUESTIONS), "depths": ["quick", "standard", "detailed"],
            "seed": 1, "connection": "codex", "model": "gpt-6.1-sol", "settings": SETTINGS}
    return base | edits


def written(tmp_path, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def lab(tmp_path):
    """A library and a factory for a discovery run of any depth, as the measurement reads it afterwards."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store

    def run_at(effort, *, policy_edit=None):
        rid = store.create_research(f"SYNTHETIC {effort}", "academic", effort, ["openalex"], "fake", "fake-model", "en")
        budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
        policy = fast_path.freeze_budget(budget, effort)
        if policy_edit:
            policy = {k: v for k, v in policy.items() if k != "policy_hash"}
            policy_edit(policy)
            policy["policy_hash"] = canonical.sha256_hex(policy)
        budget["fast_path"] = policy
        run = store.create_run(rid, "discovery", budget, None)
        store.update_run(run["id"], status="running")
        run = store.run(run["id"])
        fast_path.enter_stage(store, run, "plan")  # opens the ledger the pilot reads
        return SimpleNamespace(store=store, conn=conn, rid=rid, run=run)

    yield SimpleNamespace(conn=conn, store=store, run_at=run_at)
    conn.close()


def answer_run(lib, effort):
    """The answer run the product queues once discovery has completed, named on the same ledger."""
    lib.store.update_run(lib.run["id"], status="completed")
    budget = small_batch.answer_budget(lib.store, lib.rid, 1, TEST_EFFORT_BUDGETS[effort].__dict__)
    budget = fast_path.answer_budget(lib.store, lib.rid, 1, budget)
    run = lib.store.create_run(lib.rid, "answer", budget, None)
    lib.store.update_run(run["id"], status="running")
    return lib.store.run(run["id"])


def test_the_order_runs_every_question_at_every_depth_in_depth_blocks():
    rows = delivery_pilot.order(config())
    assert len(rows) == 9
    assert {(r["question"], r["depth"]) for r in rows} == {(q, d) for q in QUESTIONS
                                                           for d in ("quick", "standard", "detailed")}
    # Depth-blocked: each depth's runs sit together, so the same question is not measured at two depths in a row.
    assert [r["depth"] for r in rows] == ["quick"] * 3 + ["standard"] * 3 + ["detailed"] * 3
    assert [r["seq"] for r in rows] == list(range(9))


def test_the_same_seed_draws_the_same_order_and_another_seed_does_not():
    assert delivery_pilot.order(config()) == delivery_pilot.order(config())
    assert delivery_pilot.order(config(seed=2)) != delivery_pilot.order(config())


def test_a_second_repeat_rotates_the_depth_blocks():
    """A depth measured only at one hour of the day would carry that hour's machine and network with it."""
    rows = delivery_pilot.order(config(repeats=2))
    first = [r["depth"] for r in rows if r["repeat"] == 0]
    second = [r["depth"] for r in rows if r["repeat"] == 1]
    assert first[0] == "quick" and second[0] == "standard"
    assert sorted(first) == sorted(second)


def test_a_model_the_configuration_does_not_name_is_refused_before_the_first_question(tmp_path):
    """The connection never picks a model itself, so an unnamed one is refused by the server on the first
    question, which is the most expensive moment to find out."""
    for value in (None, "", "  "):
        with pytest.raises(SystemExit, match="model must be named"):
            delivery_pilot.load_config(written(tmp_path, config(model=value)))


def test_a_configuration_is_refused_before_anything_is_spent(tmp_path):
    with pytest.raises(SystemExit, match="unknown depth"):
        delivery_pilot.load_config(written(tmp_path, config(depths=["quick", "deep"])))
    with pytest.raises(SystemExit, match="seed"):
        delivery_pilot.load_config(written(tmp_path, config(seed="1")))
    with pytest.raises(SystemExit, match="not found"):
        delivery_pilot.load_config(written(tmp_path, config(questions=["scripts/benchmark/nothing.json"])))
    with pytest.raises(SystemExit, match="needs connection"):
        value = config()
        del value["connection"]
        delivery_pilot.load_config(written(tmp_path, value))


def test_a_configuration_changed_after_the_freeze_stops_the_run(tmp_path):
    (tmp_path / "order.json").write_text(json.dumps(
        {"config_sha256": delivery_pilot.config_hash(config()), "order": [], "questions": {}}))
    assert delivery_pilot.frozen_order(tmp_path, config())["order"] == []
    with pytest.raises(SystemExit, match="changed after the order was frozen"):
        delivery_pilot.frozen_order(tmp_path, config(seed=9))


def test_the_frozen_order_must_exist_before_the_run(tmp_path):
    with pytest.raises(SystemExit, match="run the plan command"):
        delivery_pilot.frozen_order(tmp_path, config())


def test_a_question_edited_after_its_own_hash_stops_the_pilot(tmp_path):
    path = tmp_path / "edited.json"
    value = json.loads((Path(delivery_pilot.ROOT) / QUESTIONS[0]).read_text())
    value["question"] = value["question"] + " and one more thing"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="hash mismatch"):
        delivery_pilot.questions_of({"questions": [str(path.relative_to(delivery_pilot.ROOT))
                                                   if str(path).startswith(str(delivery_pilot.ROOT)) else str(path)]})


def test_a_run_that_is_still_working_is_not_called_over(lab):
    state = delivery_pilot.run_state(lab.conn, lab.run_at("standard").run["id"])
    assert state["state"] == "working"


def test_the_discovery_run_ending_is_not_the_answer_ending(lab):
    """The product queues a separate answer run. A pilot that moved on when discovery ended would start timing
    the next question while this one was still writing its answer."""
    lib = lab.run_at("standard")
    answer = answer_run(lib, "standard")
    state = delivery_pilot.run_state(lab.conn, lib.run["id"])
    assert state["discovery"] == "completed" and state["answer"] == "running"
    assert state["state"] == "working"
    lib.store.update_run(answer["id"], status="completed")
    assert delivery_pilot.run_state(lab.conn, lib.run["id"])["state"] == "stopped"


def test_a_discovery_run_that_has_ended_with_no_answer_run_yet_is_read_again(lab):
    lib = lab.run_at("standard")
    lib.store.update_run(lib.run["id"], status="completed")
    assert delivery_pilot.run_state(lab.conn, lib.run["id"])["state"] == "no_answer_yet"


def test_a_paused_run_is_the_persons_to_answer_so_the_pilot_stops(lab):
    lib = lab.run_at("standard")
    lib.store.update_run(lib.run["id"], status="paused", pause_reason="key_terms_needed")
    state = delivery_pilot.run_state(lab.conn, lib.run["id"])
    assert state["state"] == "paused" and state["pause_reason"] == "key_terms_needed"


def test_a_paused_answer_run_stops_the_pilot_too(lab):
    lib = lab.run_at("standard")
    answer = answer_run(lib, "standard")
    lib.store.update_run(answer["id"], status="paused", pause_reason="model_unavailable")
    assert delivery_pilot.run_state(lab.conn, lib.run["id"])["state"] == "paused"


def test_a_research_that_queues_no_answer_of_its_own_is_over_when_discovery_is(lab):
    """A research asking only for papers or a table writes no answer, so nothing follows its discovery run."""
    lib = lab.run_at("standard", policy_edit=lambda p: p.update(auto_answer=False))
    lib.store.update_run(lib.run["id"], status="completed")
    assert delivery_pilot.run_state(lab.conn, lib.run["id"])["state"] == "stopped"


def test_waiting_gives_the_answer_run_its_moment_and_then_gives_up(lab, monkeypatch):
    lib = lab.run_at("standard")
    lib.store.update_run(lib.run["id"], status="completed")
    clock = iter(range(0, 10_000, 5))
    server = SimpleNamespace(db=lambda: _ReadOnly(lab.conn))
    state = delivery_pilot.wait(server, lib.run["id"], limit=10_000, sleep=lambda _: None, now=lambda: next(clock))
    assert state["state"] == "stopped"  # the grace period passed with no answer run named


def test_waiting_stops_at_its_own_limit_without_calling_the_run_over(lab):
    lib = lab.run_at("standard")
    clock = iter(range(0, 10_000, 30))
    server = SimpleNamespace(db=lambda: _ReadOnly(lab.conn))
    state = delivery_pilot.wait(server, lib.run["id"], limit=60, sleep=lambda _: None, now=lambda: next(clock))
    assert state["state"] == "timeout"


class _ReadOnly:
    """The library handed to `wait`, which closes it after every reading."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_):
        return False

    def execute(self, *args):
        return self.conn.execute(*args)

    def close(self):
        pass


def test_the_machine_reading_survives_a_tool_that_is_not_there(monkeypatch):
    """The readings explain an odd run; one nobody could take is absent rather than fatal."""
    monkeypatch.setattr(delivery_pilot.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no such tool")))
    state = delivery_pilot.machine_state(server_pid=1)
    assert state["power"] is None and state["memory_free_percent"] is None and state["server"] is None
    assert state["utc"]


def test_settings_the_server_reports_differently_stop_the_pilot():
    """Not only the embedding and the reranker: every endpoint the configuration pins is read back, and what
    the depth actually reads (`/api/effort-limits`) is one of them, because it is the arm's own N and K."""
    reported = {"/api/semantic-search": {"provider": "voyage", "model": "voyage-4-lite"},
                "/api/effort-limits": {"efforts": {"standard": {"papers": 50, "fulltext": 20}}},
                "/api/settings": {"answer": {"model": "gpt-6.1-sol"}}}
    server = SimpleNamespace(get=lambda path: reported[path])
    recorded = delivery_pilot.read_settings(server, SETTINGS)
    # What is only recorded is kept with the rows, so a setting nobody pinned is still readable afterwards.
    assert recorded["/api/settings"] == {"answer": {"model": "gpt-6.1-sol"}}
    reported["/api/effort-limits"] = {"efforts": {"standard": {"papers": 20, "fulltext": 5}}}
    with pytest.raises(delivery_pilot.harness.Stop, match="settings differ"):
        delivery_pilot.read_settings(server, SETTINGS)


def test_the_owners_own_library_port_is_refused():
    with pytest.raises(SystemExit, match="8765"):
        delivery_pilot.Deixis("http://127.0.0.1:8765", "/tmp")


def test_the_stamp_names_the_build_by_its_commit_and_its_working_tree(monkeypatch, tmp_path):
    """A pilot arm made by editing the depth numbers is an edited working tree, which the commit alone does not
    name, so the tracked changes and every untracked file's own contents are hashed beside it."""
    (tmp_path / "new.py").write_text("MODES = 1")
    monkeypatch.setattr(delivery_pilot, "ROOT", tmp_path)
    monkeypatch.setattr(delivery_pilot, "_command", lambda args, **k: "?? new.py\n" if "status" in args else "")
    monkeypatch.setattr(delivery_pilot.harness, "commit", lambda: "abc123")
    stamp = delivery_pilot.stamp(config(arm="lower_k"), {})
    assert stamp["commit"] == "abc123" and stamp["arm"] == "lower_k"
    assert stamp["worktree_clean"] is False  # an untracked file is a difference from the commit
    first = stamp["worktree_diff_sha256"]
    # A file git does not track can change without its name changing, so the name alone cannot be the identity.
    (tmp_path / "new.py").write_text("MODES = 2")
    assert delivery_pilot.worktree()["worktree_diff_sha256"] != first
    monkeypatch.setattr(delivery_pilot, "_command", lambda args, **k: "")
    assert delivery_pilot.stamp(config(), {})["worktree_clean"] is True


def test_a_git_that_could_not_be_read_claims_no_clean_tree(monkeypatch):
    """Absent is never read as a reading: a failed git call does not mean the build matched its commit."""
    monkeypatch.setattr(delivery_pilot, "_command", lambda *a, **k: None)
    assert delivery_pilot.worktree() == {"worktree_diff_sha256": None, "worktree_clean": None}


def test_a_paused_run_is_not_the_research_still_working(lab):
    """A paused run waits for the person and spends nothing while it waits, so the next question need not."""
    lib = lab.run_at("standard")
    lib.store.update_run(lib.run["id"], status="paused", pause_reason="key_terms_needed")
    assert delivery_pilot.working(lab.conn, lib.rid) == []


def test_the_fetch_queues_keep_the_research_busy_after_its_runs_end(lab):
    """The product goes on downloading PDFs and searching the open web for a run that ended minutes ago; a
    pilot that looked only at runs would time the next question beside that work."""
    lib = lab.run_at("standard")
    lib.store.update_run(lib.run["id"], status="completed")
    assert delivery_pilot.working(lab.conn, lib.rid) == []
    lab.conn.execute(
        "INSERT INTO fast_path_background_fetches (id, ledger_run_id, run_id, research_id, scope_revision,"
        " work_id, head, position, origin, status, queued_at) VALUES"
        " ('f1', ?, ?, ?, 1, 'W1', 'h', 0, 'not_started', 'queued', '2026-11-11T00:00:00Z')",
        (lib.run["id"], lib.run["id"], lib.rid))
    lab.conn.commit()
    left = delivery_pilot.working(lab.conn, lib.rid)
    assert [row["kind"] for row in left] == ["fast_path_background_fetches"]


def test_the_runs_the_pilot_waits_for_are_the_ones_the_product_calls_active():
    from deixis.workflow.run import store as run_store
    assert delivery_pilot.ACTIVE == run_store.ACTIVE_RUN_STATUSES


def test_one_pilot_at_a_time_over_its_rows_and_over_its_library(tmp_path):
    """Two invocations reading the same unfinished order would start the same question twice, and two with
    their own folders would still share one library, where a research measured beside another is not measured."""
    out, data = tmp_path / "out", tmp_path / "data"
    other = tmp_path / "other"
    for folder in (out, data, other):
        folder.mkdir()
    locks = delivery_pilot.take_lock(out, data)
    assert json.loads(locks[0].read_text())["pid"]
    with pytest.raises(SystemExit, match="another pilot is running"):
        delivery_pilot.take_lock(out, data)
    # Its own folder for the rows, the same library: still refused.
    with pytest.raises(SystemExit, match="another pilot is running"):
        delivery_pilot.take_lock(other, data)
    # A refused attempt leaves nothing of its own behind.
    assert not (other / "delivery-pilot.lock").exists()
    for lock in locks:
        lock.unlink()
    for lock in delivery_pilot.take_lock(out, data):
        lock.unlink()


def test_the_shipped_depths_are_the_ones_the_pilot_can_run():
    """The pilot's depth names are the product's own, and each one's target is the depth's whole budget."""
    assert set(delivery_pilot.DEPTHS) == set(fast_path.MODES)
    for depth, seconds in delivery_pilot.TARGET_SECONDS.items():
        assert sum(fast_path.MODES[depth].stage_seconds) == seconds


def test_no_question_is_measured_twice_in_a_row_across_a_block_boundary():
    """A question run again a moment later reads a provider's cache the first run warmed, so the depth it is
    measured at and the warmth of the cache would arrive together."""
    for seed in range(1, 40):
        rows = delivery_pilot.order(config(seed=seed))
        names = [r["question"] for r in rows]
        assert all(a != b for a, b in zip(names, names[1:])), f"seed {seed} repeats a question back to back"


def test_a_run_that_did_not_end_cleanly_stops_a_second_invocation(tmp_path):
    """A paused or overrun question is not done and is not skipped either: its run may still be working, and
    starting the next question beside it would time two researches at once."""
    rows, started = tmp_path / "runs.jsonl", tmp_path / "started.jsonl"
    delivery_pilot.append(rows, {"seq": 0, "question": QUESTIONS[0], "depth": "quick", "repeat": 0,
                                 "outcome": {"state": "stopped"}})
    assert delivery_pilot.resume_point(rows, started) == {(QUESTIONS[0], "quick", 0)}
    delivery_pilot.append(rows, {"seq": 1, "question": QUESTIONS[1], "depth": "quick", "repeat": 0,
                                 "outcome": {"state": "timeout"}})
    with pytest.raises(SystemExit, match="did not end cleanly"):
        delivery_pilot.resume_point(rows, started)


def test_a_request_whose_reply_never_arrived_stops_a_second_invocation(tmp_path):
    """The idempotency key is written before the request is sent, so a reply that was lost leaves a trace: the
    run it may have created is in the library, and a second invocation must not open another one beside it."""
    rows, started = tmp_path / "runs.jsonl", tmp_path / "started.jsonl"
    delivery_pilot.append(started, {"seq": 0, "idempotency_key": "pilot-abc", "at": "now"})
    with pytest.raises(SystemExit, match="no run of its own"):
        delivery_pilot.resume_point(rows, started)
    delivery_pilot.append(rows, {"seq": 0, "question": QUESTIONS[0], "depth": "quick", "repeat": 0,
                                 "outcome": {"state": "stopped"}})
    assert delivery_pilot.resume_point(rows, started) == {(QUESTIONS[0], "quick", 0)}


def test_quiet_has_to_hold_not_merely_be_read_once(lab):
    """The product opens the late-revision run after the last fetch row finishes, so a single reading can land
    in the gap between the work that ended and the work that is about to start."""
    lib = lab.run_at("standard")
    lib.store.update_run(lib.run["id"], status="completed")
    server = SimpleNamespace(db=lambda: _ReadOnly(lab.conn))
    readings = []

    def one_more(_):
        """Between two readings the product opens the work the first reading missed."""
        readings.append(1)
        if len(readings) == 1:
            lab.conn.execute(
                "INSERT INTO fast_path_background_fetches (id, ledger_run_id, run_id, research_id,"
                " scope_revision, work_id, head, position, origin, status, queued_at) VALUES"
                " ('late', ?, ?, ?, 1, 'W9', 'h', 0, 'not_started', 'queued', '2026-11-11T00:00:00Z')",
                (lib.run["id"], lib.run["id"], lib.rid))
            lab.conn.commit()

    clock = iter(range(0, 10_000, 30))
    state = delivery_pilot.quiet(server, lib.rid, limit=60, sleep=one_more, now=lambda: next(clock))
    assert state["quiet"] is False  # one quiet reading was not the research being quiet
    assert [row["kind"] for row in state["still_working"]] == ["fast_path_background_fetches"]


def test_a_research_that_never_went_quiet_stops_a_second_invocation(tmp_path):
    """Its row says the run itself ended, but the machine was still busy with it: starting the next question
    on a second invocation would measure it beside that work."""
    rows, started = tmp_path / "runs.jsonl", tmp_path / "started.jsonl"
    delivery_pilot.append(rows, {"seq": 0, "question": QUESTIONS[0], "depth": "quick", "repeat": 0,
                                 "outcome": {"state": "stopped"},
                                 "background": {"quiet": False, "still_working": [{"kind": "answer"}]}})
    with pytest.raises(SystemExit, match="still working"):
        delivery_pilot.resume_point(rows, started)


def test_the_next_question_waits_for_the_research_to_go_quiet(lab):
    """Writing the answer is not the end of the research: a late full-text read can produce one revision and a
    review can read the answer. That work is not timed, but it is not run beside the next question either."""
    lib = lab.run_at("standard")
    answer = answer_run(lib, "standard")
    server = SimpleNamespace(db=lambda: _ReadOnly(lab.conn))
    clock = iter(range(0, 10_000, 30))
    state = delivery_pilot.quiet(server, lib.rid, limit=60, sleep=lambda _: None, now=lambda: next(clock))
    assert state["quiet"] is False
    assert [r["kind"] for r in state["still_working"]] == ["answer"]
    lib.store.update_run(answer["id"], status="completed")
    assert delivery_pilot.quiet(server, lib.rid, limit=60, sleep=lambda _: None)["quiet"] is True


def test_the_keys_are_read_the_way_the_product_reads_them(monkeypatch):
    """The keychain keeps the keys inside one bundled item, so a reader of the pilot's own finds nothing under a
    key's own name and the run stops on a provider's 401 before the first question."""
    from deixis.keys import credentials

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "load_into_environment",
                        lambda: os.environ.__setitem__("OPENALEX_API_KEY", "from-the-product-reader"))
    secret = delivery_pilot._keyring()
    assert secret("OPENALEX_API_KEY") == "from-the-product-reader"
    assert secret("A_KEY_THAT_IS_NOT_STORED") is None

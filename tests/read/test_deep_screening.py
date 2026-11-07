"""D173's deeper screening (rule `m3_v1`): a Standard discovery queued with the option on also screens list places
N+1..N+100 once each, after the top N; K, its order and the fetch queue are unchanged and only the answer's window
widens. Plus the benchmark-only list barrier. SYNTHETIC records, FakeAdapter, mocked HTTP; no live provider or model.
Passing shows workflow behaviour, not screening quality."""

import json
from contextlib import contextmanager

import pytest

from deixis.workflow.answer import answer as fast_answer
from deixis.workflow.run import fast_path
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.search import small_batch
from fakes import FakeAdapter, valid_response
from overlap_flow_helpers import discover, wait
from test_fast_path_clock import FakeClock
from test_fulltext_flow import Transport, work
from test_small_batch_flow import app_for, client_of

N, K = 4, 2
TITLE = "SYNTHETIC irrigation scheduling field crop"


def one_read(si):
    return (si.get("screening_target") or {}).get("runs") == 1


def responder(si):
    """`valid_response`, except that a one-read call puts its first record out of scope (its quote still locates)."""
    text = valid_response(si)
    if si["task_type"] != "abstract_screening" or not one_read(si):
        return text
    body = json.loads(text)
    body["records"][0]["label"] = "out_of_scope"
    return json.dumps(body)


@pytest.fixture
def small_standard(monkeypatch):
    monkeypatch.setitem(fast_path.MODES, "standard",
                        fast_path.MODES["standard"]._replace(read_top=N, fulltext_works=K))


def app_with(tmp_path, monkeypatch, *, deep, adapter=None, n=30, **settings):
    records = [work(i, title=TITLE) for i in range(n)]
    app, _ = app_for(tmp_path, monkeypatch, n, adapter=adapter or FakeAdapter(responder),
                     transport=Transport(records), **settings)
    app.deep = deep
    return app


@contextmanager
def deep_client(app):
    """The client, with the library's deeper-screening setting written before any run is queued."""
    with client_of(app) as client:
        view = client.put("/api/settings/preferences", json={"deep_screening": "on" if app.deep else "off"})
        assert view.status_code == 200 and view.json()["deep_screening"] == ("on" if app.deep else "off")
        yield client


def steps_of(store, run_id, like):
    return [dict(row) for row in store.conn.execute(
        "SELECT * FROM run_steps WHERE run_id = ? AND operation_key LIKE ? ORDER BY rowid", (run_id, like))]


def closure_of(store, run_id):
    return next(s["output"] for s in small_batch.steps(store, run_id) if s["operation_key"].endswith(":fast:close"))


def answer_input(client, store, rid):
    view = client.get(f"/api/researches/{rid}").json()
    answer = next(r for r in view["runs"] if r["kind"] == "answer")
    _, answer = wait(client, rid, answer["id"])
    assert answer["status"] == "completed", answer
    return store.existing_step(answer["id"], fast_answer.INPUT)["output"]


def positions(closure, work_ids):
    place = {item["work_id"]: item["position"] for item in closure["items"]}
    return sorted(place[wid] for wid in work_ids)


def test_deep_window_is_read_once_and_reaches_only_the_answer(tmp_path, monkeypatch, small_standard):
    """(1) The window's calls carry one run, write one-read codes, and leave K and its claims as the run with the option
    off; a deep candidate enters the answer as an abstract row after every top-N one, a deep out-of-scope one does not,
    and a deep work the person decided while the read ran is neither sent nor given."""
    results = {}
    for deep in (False, True):
        holder = {}

        def before(si, holder=holder):
            # While the top N are screened, the person decides a work of the deeper window.
            if si["task_type"] != "abstract_screening" or one_read(si) or holder.get("decided"):
                return
            store = holder["app"].state.store
            listing = store.existing_step(si["run_id"], small_batch.LIST_KEY)["output"]
            item = listing["items"][N + 2]
            DecisionStore(store).record(si["research_id"], item["head"], "human_criterion_not_met",
                                        note="SYNTHETIC person's decision")
            holder["decided"] = item

        adapter = FakeAdapter(responder, before=before)
        app = holder["app"] = app_with(tmp_path / str(deep), monkeypatch, deep=deep, adapter=adapter)
        with deep_client(app) as client:
            rid, run_id, _, run = discover(client, effort="standard")
            assert run["status"] == "completed", run
            store = app.state.store
            closure = closure_of(store, run_id)
            listing = store.existing_step(run_id, small_batch.LIST_KEY)["output"]
            # A step input names its records by alias; their titles are unique here.
            head_of = {store.source(item["head"])["title"]: item["head"] for item in listing["items"]}
            deep_calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening" and one_read(c)]
            results[deep] = {
                "run": run, "closure": closure, "decided": holder["decided"], "deep_calls": deep_calls,
                "position_of": {item["work_id"]: item["position"] for item in listing["items"]},
                "selected": positions(closure, closure["selected_work_ids"]),
                "claims": positions(closure, [s["operation_key"].split(":", 1)[1]
                                              for s in steps_of(store, run_id, "fulltext_work:%")]),
                "deep_steps": steps_of(store, run_id, "%:fast:deep:%"),
                "sent": {head_of[c["title"]] for call in deep_calls for c in call["candidates"]},
                "codes": {row[0] for row in store.conn.execute(
                    "SELECT d.reason_code FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
                    " WHERE s.run_id = ? AND s.operation_key LIKE ? AND d.superseded_at IS NULL",
                    (run_id, "%:fast:deep:abstract_screening:%"))},
                "out_of_scope": {row[0] for row in store.conn.execute(
                    "SELECT v.work_id FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
                    " WHERE d.research_id = ? AND d.reason_code = 'single_read_out_of_scope'"
                    " AND d.superseded_at IS NULL", (rid,))},
                "input": answer_input(client, store, rid),
                "counts": client.get(f"/api/researches/{rid}").json()["counts"]}

    off, on = results[False], results[True]
    assert "deep_screening" not in off["run"]["budget"]["fast_path"]
    assert on["run"]["budget"]["fast_path"]["deep_screening"] == {"rule": "m3_v1", "first": N + 1, "last": N + 100,
                                                                  "runs": 1, "batch": 20}
    assert not off["deep_steps"] and not off["deep_calls"] and "deep" not in off["closure"]
    # K, its order and its claims do not move.
    assert on["selected"] == off["selected"] and on["claims"] == off["claims"]
    assert all(p <= N for p in on["selected"] + on["claims"])

    deep_calls = on["deep_calls"]
    assert deep_calls and all(c["screening_target"] == {"runs": 1, "run": 1} for c in deep_calls)
    # The person's work was not sent; one-read codes were written under the deep batches' steps.
    decided = on["decided"]
    assert on["sent"] and decided["head"] not in on["sent"]
    assert on["codes"] == {"single_read_candidate", "single_read_out_of_scope"}
    record = on["closure"]["deep"]
    assert (record["first"], record["last"], record["not_screened_at_cutoff"]) == (N + 1, N + 100, [])
    assert record["planned"] == record["screened_count"] == (record["screened_by_model_count"]
                                                             + record["code_settled_count"] + record["person_decided_count"])
    assert record["person_decided_count"] == 1 and record["model_calls"] == len(deep_calls)
    # The closure's top-level counts keep meaning places 1..N.
    assert on["closure"]["screened_count"] == off["closure"]["screened_count"] == N

    position_of = on["position_of"]
    rows = on["input"]["items"]
    abstract_rows = [position_of[row["work_id"]] for row in rows if row["answer_role"] == "abstract"]
    top = [p for p in abstract_rows if p <= N]
    deeper = [p for p in abstract_rows if p > N]
    assert top and deeper and max(top) < min(deeper)
    assert all(position_of[row["work_id"]] <= N + 100 for row in rows)
    given = {row["work_id"] for row in rows}
    assert on["out_of_scope"] and not on["out_of_scope"] & given and decided["work_id"] not in given
    # The funnel counts the one-read works apart; the flow puts one read's out-of-scope verdict in its own bucket.
    funnel, buckets = on["counts"]["funnel"], on["counts"]["flow"]["buckets"]
    assert funnel["abstracts_read_once"] == record["screened_by_model_count"] > funnel["candidates_read_once"] > 0
    assert buckets["out_of_scope_one_read"] == len(on["out_of_scope"])
    assert off["counts"]["funnel"]["abstracts_read_once"] == off["counts"]["flow"]["buckets"]["out_of_scope_one_read"] == 0
    # The off run's answer stays inside places 1..N.
    assert all(off["position_of"][row["work_id"]] <= N for row in off["input"]["items"])


def test_a_cut_deep_batch_leaves_its_works_unscreened_and_out_of_the_answer(tmp_path, monkeypatch, small_standard):
    """(2) The read cutoff passes while the first one-read call is out: the works of the batches it cut are
    `deep.not_screened_at_cutoff`, none of them reaches the answer, and every deep step finished before the snapshot.
    A deep work unscreened in this run stays out even when it holds a fresh candidate decision from before."""
    holder = {}

    def before(si):
        if si["task_type"] == "abstract_screening" and one_read(si) and not holder.get("cut"):
            holder["cut"] = True
            holder["app"].state.store.clock.advance(5000)

    adapter = FakeAdapter(responder, before=before)
    app = holder["app"] = app_with(tmp_path, monkeypatch, deep=True, adapter=adapter)
    with deep_client(app) as client:
        app.state.store.clock = FakeClock()
        rid, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        store = app.state.store
        closure = closure_of(store, run_id)
        unread = closure["deep"]["not_screened_at_cutoff"]
        assert unread and holder["cut"]
        assert closure["deep"]["screened_count"] + len(unread) == closure["deep"]["planned"]
        cutoff = store.existing_step(run_id, fast_answer.CUTOFF)
        rows = {row["work_id"]: row for row in cutoff["output"]["items"]}
        assert all(rows[wid]["reason"] == "not_screened_at_cutoff" for wid in unread)
        assert not set(unread) & {row["work_id"] for row in answer_input(client, store, rid)["items"]}
        deep_steps = steps_of(store, run_id, "%:fast:deep:%")
        assert deep_steps and all(s["finished_at"] and s["finished_at"] <= cutoff["finished_at"] for s in deep_steps)

        # An unscreened deep work holding a fresh candidate decision: the snapshot reads the deep unread set.
        flow = app.state.worker.flow
        listing = store.existing_step(run_id, small_batch.LIST_KEY)["output"]
        item = next(i for i in listing["items"] if i["work_id"] == unread[0])
        head = item["head"]
        DecisionStore(store).record(rid, head, "single_read_candidate")
        frozen = store.run(run_id)
        with_deep = fast_answer.cutoff_snapshot(flow, frozen, listing, closure)
        without = fast_answer.cutoff_snapshot(flow, frozen, listing, {k: v for k, v in closure.items() if k != "deep"})
        assert next(r for r in with_deep["items"] if r["work_id"] == unread[0])["reason"] == "not_screened_at_cutoff"
        assert next(r for r in without["items"] if r["work_id"] == unread[0])["reason"] is None


@pytest.mark.parametrize("effort", ["quick", "standard"])
def test_a_run_frozen_without_the_window_reads_as_before(tmp_path, monkeypatch, small_standard, effort):
    """(3) The setting on at Quick, or a budget frozen without the key: the same policy and hash as with the option
    off, no deep step, the same calls and the same answer window."""
    if effort == "quick":
        assert fast_path.freeze_budget({}, "quick") == fast_path.freeze_budget({}, "quick", deep_screening=False)
        with pytest.raises(ValueError):
            fast_path.freeze_budget({}, "quick", deep_screening=True)
    for name in ("standard", "detailed"):
        assert fast_path.freeze_budget({}, name)["policy_hash"] == fast_path.freeze_budget({}, name, deep_screening=False)["policy_hash"]
    seen = {}
    for deep in ((False, True) if effort == "quick" else (False,)):
        adapter = FakeAdapter(responder)
        app = app_with(tmp_path / f"{effort}{deep}", monkeypatch, deep=deep, adapter=adapter)
        with deep_client(app) as client:
            rid, run_id, _, run = discover(client, effort=effort)
            assert run["status"] == "completed", run
            store = app.state.store
            assert "deep_screening" not in run["budget"]["fast_path"]
            assert not steps_of(store, run_id, "%:deep:%") and "deep" not in closure_of(store, run_id)
            cutoff = store.existing_step(run_id, fast_answer.CUTOFF)["output"]
            seen[deep] = (run["budget"]["fast_path"]["policy_hash"], run["budget"]["max_model_calls"],
                          len([c for c in adapter.calls if c["task_type"] == "abstract_screening"]),
                          cutoff["excluded_reasons"].get("outside_read_window"))
            assert not [c for c in adapter.calls if c["task_type"] == "abstract_screening" and one_read(c)]
    if effort == "quick":
        assert seen[True] == seen[False]


@pytest.mark.parametrize("interruption", ["pause", "recover"])
def test_a_paused_deep_batch_resumes_without_sending_a_succeeded_step_again(tmp_path, monkeypatch, small_standard,
                                                                           interruption):
    """(4) A pause asked while a one-read call is out lets that call finish, and the resume reads it back; a call a
    crash left in flight is `outcome_unknown`, the run pauses, and only the resume sends it again. The deep batch keys
    and their stored StepInputs do not move."""
    holder = {}

    def before(si):
        if si["task_type"] == "abstract_screening" and one_read(si) and not holder.get("stopped"):
            holder["stopped"] = True
            app = holder["app"]
            if interruption == "pause":
                app.state.store.update_run(si["run_id"], status="pause_requested")
            else:
                app.state.worker.recover()

    adapter = FakeAdapter(responder, delay=0.01, before=before)
    app = holder["app"] = app_with(tmp_path, monkeypatch, deep=True, adapter=adapter, model_concurrency=1)
    with deep_client(app) as client:
        rid, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "paused", run
        store = app.state.store
        deep_like = "%:fast:deep:abstract_screening:%"
        before_resume = {s["operation_key"]: s for s in steps_of(store, run_id, deep_like)}
        inputs = {row[0]: row[1] for row in store.conn.execute(
            "SELECT s.operation_key, i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " WHERE s.run_id = ? AND s.operation_key LIKE ?", (run_id, deep_like))}
        sent_before = len([c for c in adapter.calls if one_read(c)])
        assert sent_before == 1
        if interruption == "recover":
            assert [s["status"] for s in before_resume.values()] == ["outcome_unknown"]
        else:
            assert [s["status"] for s in before_resume.values()] == ["succeeded"]
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        after = {s["operation_key"]: s for s in steps_of(store, run_id, deep_like)}
        plan = store.existing_step(run_id, next(k for k in [s["operation_key"] for s in steps_of(
            store, run_id, "%:fast:deep:abstract_stage")]))["output"]
        batches = len(plan["batches"])
        assert len(after) == batches
        assert set(before_resume) <= set(after)
        assert all(after[key]["status"] == "succeeded" for key in after)
        # The succeeded call is read back, not sent again; only the call a crash left unknown is sent once more.
        sent = len([c for c in adapter.calls if one_read(c)])
        assert sent == batches + (1 if interruption == "recover" else 0)
        kept = {row[0]: row[1] for row in store.conn.execute(
            "SELECT s.operation_key, i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " WHERE s.run_id = ? AND s.operation_key LIKE ? ORDER BY i.attempt", (run_id, deep_like))}
        for key, payload in inputs.items():
            assert json.loads(kept[key])["candidates"] == json.loads(payload)["candidates"]
        assert not closure_of(store, run_id)["deep"]["not_screened_at_cutoff"]


@pytest.mark.parametrize("barrier", [False, True])
def test_the_benchmark_list_barrier_pauses_once_after_the_list_and_before_any_read_work(tmp_path, monkeypatch, barrier):
    """M3's gate: with the flag the run pauses right after its list, holding no read step, model call, decision written
    after the list, claim or read clock row; resumed, it completes as any run. Without it nothing is written."""
    adapter = FakeAdapter(valid_response)
    app, _ = app_for(tmp_path, monkeypatch, 30, model_works=True, adapter=adapter, benchmark_list_barrier=barrier)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="standard")
        store = app.state.store
        policy_hash = run["budget"]["fast_path"]["policy_hash"]
        assert policy_hash == fast_path.freeze_budget({}, "standard")["policy_hash"]
        if not barrier:
            assert run["status"] == "completed", run
            assert store.existing_step(run_id, small_batch.LIST_BARRIER_KEY) is None
            assert "benchmark_list_barrier" not in run["budget"]
            return
        assert (run["status"], run["pause_reason"]) == ("paused", "benchmark_list_barrier"), run
        assert run["budget"]["benchmark_list_barrier"] is True
        listed = store.existing_step(run_id, small_batch.LIST_KEY)
        later = [dict(row) for row in store.conn.execute(
            "SELECT operation_key, kind FROM run_steps WHERE run_id = ? AND rowid > (SELECT rowid FROM run_steps WHERE id = ?)",
            (run_id, listed["id"]))]
        assert [s["operation_key"] for s in later] == [small_batch.LIST_BARRIER_KEY]
        calls = len(adapter.calls)
        assert not [c for c in adapter.calls if c["task_type"] in ("abstract_screening", "fulltext_adjudication")]
        assert not store.conn.execute("SELECT 1 FROM stage_decisions WHERE research_id = ? AND created_at > ?",
                                      (rid, listed["finished_at"])).fetchone()
        assert not store.conn.execute("SELECT 1 FROM fast_path_intervals WHERE run_id = ? AND stage = 'read'",
                                      (run_id,)).fetchone()
        assert not store.conn.execute("SELECT 1 FROM fast_path_stages WHERE ledger_run_id = ? AND stage = 'read'",
                                      (run_id,)).fetchone()
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        assert len(adapter.calls) > calls
        assert len(steps_of(store, run_id, small_batch.LIST_BARRIER_KEY)) == 1

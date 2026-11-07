"""The D163 M1 measurement scripts (scripts/benchmark): model-reply replay, the shared OpenAlex spend cap, and the
gate scorer. SYNTHETIC libraries, the fake model and a mocked OpenAlex; nothing here sends a request or measures
search quality."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fcntl", reason="spend_ledger locks with fcntl; the benchmark runs on macOS and Linux")

from fakes import FakeAdapter, valid_response
from test_search_query import OpenAlex, client_for, start, wait

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))
import m1_score  # noqa: E402
import replay_answers  # noqa: E402
import spend_ledger  # noqa: E402


async def no_sleep(seconds):
    return None


def sessions(client, task="search_query"):
    return [(row[0], row[1]) for row in client.app.state.store.conn.execute(
        "SELECT m.status, m.raw_output FROM model_sessions m JOIN step_inputs si ON si.id = m.step_input_id"
        " WHERE si.task_type = ? ORDER BY m.started_at, m.rowid", (task,))]


def test_a_replayed_arm_gets_the_baselines_invalid_answer_and_then_its_repair(tmp_path, monkeypatch):
    first = {"sent": False}

    def responder(si):
        if si["task_type"] == "search_query" and not first["sent"]:
            first["sent"] = True
            return "{}"  # invalid: the product sends one repair with the issues in the message
        return valid_response(si)

    base = client_for(tmp_path / "base", monkeypatch, OpenAlex(), FakeAdapter(responder))
    rid, run_id = start(base)
    assert wait(base, rid, run_id)[1]["status"] == "completed"
    baseline = sessions(base)
    assert len(baseline) == 2 and baseline[0][1] == "{}"
    base.__exit__(None, None, None)

    log = tmp_path / "replay.jsonl"
    replay = replay_answers.ReplayAdapter(FakeAdapter(), replay_answers.Baseline.load(tmp_path / "base" / "data"),
                                          log, tmp_path / "arm" / "data" / "library.sqlite", sleep=no_sleep)
    arm = client_for(tmp_path / "arm", monkeypatch, OpenAlex(), replay)
    rid, run_id = start(arm)
    assert wait(arm, rid, run_id)[1]["status"] == "completed"
    assert sessions(arm) == baseline
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    # Calls after the list froze (the answer here) are not replayed; the harness cancels a run there.
    assert rows and all(r["outcome"] == "replayed" for r in rows if r["task_type"] in replay_answers.REPLAYED)


def call(digest="d", key=("search_query:1", 1), **kw):
    return replay_answers.Call("sti_x", "SYNTHETIC q", "search_query", digest, key=key, **kw)


def test_a_call_is_paired_by_its_step_and_place_and_a_failed_or_resent_one_is_refused():
    answered = replay_answers.Session(raw_output='{"ok": 1}')
    baseline = replay_answers.Baseline([call("a", ("search_query:1", 1), session=answered),
                                        call("a", ("search_query:2", 1), refusal="baseline_failure_not_stored")])
    assert baseline.take("SYNTHETIC q", ("search_query:1", 1), "b") == (None, "no_matching_baseline_call")
    assert baseline.take("SYNTHETIC q", ("search_query:1", 1), "a")[0] is answered
    assert baseline.take("SYNTHETIC q", ("search_query:2", 1), "a") == (None, "baseline_failure_not_stored")
    assert baseline.take("SYNTHETIC q", ("search_query:1", 1), "a") == (None, "more_calls_than_baseline")


def test_concurrent_calls_arriving_in_reverse_order_each_get_their_own_baseline_reply():
    replies = {n: replay_answers.Session(raw_output=f'{{"run": {n}}}') for n in (1, 2, 3)}
    keys = {n: (f"vocabulary_labels_{n}", 1) for n in (1, 2, 3)}
    baseline = replay_answers.Baseline([call("same", keys[n], session=replies[n]) for n in (1, 2, 3)])
    for n in (3, 2, 1):  # identical requests, reversed arrival
        assert baseline.take("SYNTHETIC q", keys[n], "same")[0] is replies[n]


def test_a_request_that_differs_beyond_generated_ids_and_times_is_refused():
    digest = replay_answers.request_digest
    a, b, c = (f"src_{x * 20}" for x in "ABC")
    one = digest("b", "d", f"{a} cites {a}, {b} at 2026-11-07T10:00:00.000+00:00", {}, "m", "medium")
    renamed = digest("b", "d", f"{c} cites {c}, {a} at 2026-11-08T11:00:00.000+00:00", {}, "m", "medium")
    rewired = digest("b", "d", f"{a} cites {b}, {b} at 2026-11-07T10:00:00.000+00:00", {}, "m", "medium")
    repair = digest("b", "d", f"{a} cites {a}, {b} at 2026-11-07T10:00:00.000+00:00 issues: x", {}, "m", "medium")
    assert one == renamed and one != rewired and one != repair


def test_the_spend_cap_counts_open_reservations_and_the_spend_hidden_by_a_daily_reset(tmp_path):
    balance = [10.0]
    ledger = spend_ledger.Ledger(tmp_path / "ledger.json", cap_usd=1.0, reserve_usd=0.4, balance=lambda: balance[0])
    a = ledger.reserve("q1")
    ledger.reserve("q2")
    with pytest.raises(spend_ledger.Refused):
        ledger.reserve("q3")  # 0.8 held, 0.4 more would pass the cap
    balance[0] = 13.0  # the daily allowance came back while q1 and q2 were open
    assert ledger.settle(a) == pytest.approx(0.8)  # their reservations count as spent: the drop is not visible
    with pytest.raises(spend_ledger.Refused):
        ledger.reserve("q3")  # 0.8 spent + q2's 0.4 still held


def test_question_bound_counts_every_frozen_request_limit():
    prices = {"count": 0.001, "list": 0.001, "search": 0.001, "semantic": 0.01}
    bound = spend_ledger.question_bound_usd("standard", prices)
    assert bound > 0
    assert spend_ledger.question_bound_usd("standard", prices | {"semantic": 0.02}) > bound


def test_a_missing_question_makes_a_paired_gate_inconclusive_and_a_failed_one_scores_zero():
    expected = ["q1", "q2"]
    base = {"q1": {50: 0.5}, "q2": {50: 0.5}}
    gate = m1_score.paired_gate({"q1": {50: 0.5}}, base, expected, 50, -0.02)
    assert gate["verdict"] == "inconclusive" and gate["missing"] == {"m1": ["q2"], "base": []}
    gate = m1_score.paired_gate({"q1": {50: 0.5}, "q2": None}, base, expected, 50, -0.02)
    assert gate["n"] == 2 and gate["verdict"] == "fail" and gate["mean"] == pytest.approx(-0.25)


def test_the_width_gate_fails_over_the_limit_and_is_inconclusive_on_an_unchecked_query():
    sent = {"probed_gate_count": 100, "compiled": ["q"], "sent": {"q": [120]}}
    assert m1_score.width_verdict([sent]) == "pass"
    assert m1_score.width_verdict([sent | {"sent": {"q": [300_000]}}]) == "fail"
    assert m1_score.width_verdict([sent | {"sent": {}}]) == "inconclusive"  # compiled, no request on record
    assert m1_score.width_verdict([sent | {"sent": {"q": [None]}}]) == "pass"  # bounded by the probe
    assert m1_score.width_verdict([sent | {"probed_gate_count": None, "sent": {"q": [None]}}]) == "inconclusive"


def test_the_extra_chain_gate_evidence_is_incomplete_without_a_run_verified_forms_matching_admissions_or_payloads():
    ok = {"forms_unverified": False, "mismatches": 0, "missing_payloads": 0, "extra_chained_works": 3}
    assert m1_score.extra_chained({"r1": ok}, ["r1"]) == ([3], True)
    assert m1_score.extra_chained({"r1": ok}, ["r1", None])[1] is False  # a failed run has no checked list
    assert m1_score.extra_chained({"r1": ok | {"mismatches": 1}}, ["r1"])[1] is False
    assert m1_score.extra_chained({"r1": ok | {"missing_payloads": 1}}, ["r1"])[1] is False
    assert m1_score.extra_chained({"r1": {"rule": "fast_chain_v2", "forms_unverified": True}}, ["r1"]) == ([], False)


def test_a_call_the_replay_does_not_cover_excludes_its_question_only_before_the_list_froze():
    from datetime import datetime
    questions = [{"id": "q1", "body": "SYNTHETIC one"}, {"id": "q2", "body": "SYNTHETIC two"}]
    frozen = {"q1": datetime.fromisoformat("2026-11-07T10:00:00.000+00:00"),
              "q2": datetime.fromisoformat("2026-11-07T10:00:00.000+00:00")}
    log = [{"question": "SYNTHETIC one", "outcome": "refused", "reason": "not_replayed",
            "at": "2026-11-07T10:05:00.000+00:00"},  # the answer stage, after the freeze
           {"question": "SYNTHETIC two", "outcome": "refused", "reason": "not_replayed",
            "at": "2026-11-07T09:55:00.000+00:00"}]  # a translation before the search
    assert m1_score.refused(log, questions, frozen) == {"q2"}


def test_a_reservation_stays_open_while_a_run_request_has_no_definite_outcome(tmp_path):
    import sqlite3

    import harness
    path = tmp_path / "library.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE runs (id TEXT, research_id TEXT, status TEXT, idempotency_key TEXT)")
        conn.execute("INSERT INTO runs VALUES ('run_a', 'res_a', 'running', NULL)")
        conn.execute("INSERT INTO runs VALUES ('run_b', 'res_b', 'cancelled', 'res_b:bench-b')")

    class Server:
        readable = True

        def db(self):
            if not self.readable:
                raise sqlite3.OperationalError("unreadable")
            return sqlite3.connect(path)

    server = Server()
    assert harness.reservation_closable(server, {"research_id": "res_c"}) is True  # no run request was sent
    # Sent, no reply, and the library shows no run of its key: the request may still land.
    assert harness.reservation_closable(server, {"research_id": "res_c", "run_request": "bench-c"}) is False
    # Sent, no reply, but its key created a run that is now stopped.
    assert harness.reservation_closable(server, {"research_id": "res_b", "run_request": "bench-b"}) is True
    assert harness.run_stopped(server, "run_a", timeout=0) is False
    server.readable = False
    assert harness.reservation_closable(server, {"research_id": "res_b", "run_request": "bench-b"}) is False


def test_the_question_bound_counts_the_model_query_counts_of_every_checked_attempt():
    from deixis.workflow.search import search_query
    requests = spend_ledger.question_requests("standard")
    assert requests["count"] >= search_query.MAX_COUNT_REQUESTS * search_query.ATTEMPTS


def test_a_v2_run_without_frozen_forms_that_match_their_digest_is_not_checked_with_rebuilt_ones(tmp_path):
    import sqlite3

    import chain_rule_check
    from deixis.workflow.search import chaining
    forms = {"task": ["pump"]}
    path = tmp_path / "library.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE runs (id TEXT, research_id TEXT, scope_revision INT, kind TEXT, budget_json TEXT,"
                     " created_at TEXT)")
        conn.execute("CREATE TABLE run_steps (run_id TEXT, operation_key TEXT, output_json TEXT)")
        conn.execute("CREATE TABLE protocol_records (research_id TEXT, scope_revision INT, protocol_revision INT,"
                     " body_json TEXT)")
        budget = json.dumps({"fast_path": {"chain_rule": chaining.RULE_V2}})
        listing = json.dumps({"manifest": {"blocks": {"task": ["pump"]}, "versions": {}}})
        for n, body in enumerate([{"admission_forms": forms, "admission_forms_sha256": "sha256:0"}, {}]):
            conn.execute("INSERT INTO runs VALUES (?, ?, 1, 'discovery', ?, ?)", (f"run_{n}", f"res_{n}", budget, n))
            conn.execute("INSERT INTO run_steps VALUES (?, 'small_batch:v1:list', ?)", (f"run_{n}", listing))
            conn.execute("INSERT INTO run_steps VALUES (?, 'protocol', ?)", (f"run_{n}", '{"protocol_revision": 1}'))
            conn.execute("INSERT INTO protocol_records VALUES (?, 1, 1, ?)",
                         (f"res_{n}", json.dumps({"citation_chaining": body})))
    checked = chain_rule_check.check(path)
    assert checked == {"run_0": {"rule": chaining.RULE_V2, "forms_unverified": True},  # digest does not match
                       "run_1": {"rule": chaining.RULE_V2, "forms_unverified": True}}  # nothing frozen


def test_a_run_request_without_a_reply_is_sent_again_with_the_same_key_and_marked_until_answered():
    import httpx

    import bioasq_run
    keys, row = [], {}

    class Http:
        def post(self, path, json, headers):
            keys.append((headers["idempotency-key"], dict(row)))
            if len(keys) == 1:
                raise httpx.ReadTimeout("no reply")
            return httpx.Response(202, json={"id": "run_a"}, request=httpx.Request("POST", "http://x" + path))

    class Server:
        http = Http()

        def post(self, path, body):
            return {"research": {"id": "res_a"}}

    assert bioasq_run.ask_deixis(Server(), "SYNTHETIC q", row=row) == ("res_a", "run_a")
    assert keys[0][0] == keys[1][0] and keys[0][1]["run_request"] == keys[0][0]  # marked before the first send
    assert "run_request" not in row

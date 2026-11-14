"""The m1 measurement scripts (scripts/benchmark): model-reply replay, the shared OpenAlex spend cap, and the
gate scorer. SYNTHETIC libraries, the fake model and a mocked OpenAlex; nothing here sends a request or measures
search quality."""

import asyncio
import dataclasses
import json
import sqlite3
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
import openalex_costs  # noqa: E402


async def no_sleep(seconds):
    return None


class AliasAdapter(FakeAdapter):
    """A connection that answers an alias with the model it resolves to and verifies the match (Claude Code)."""

    async def run_step(self, *args, **kwargs):
        result = await super().run_step(*args, **kwargs)
        return dataclasses.replace(result, resolved_model=f"{result.resolved_model}-resolved",
                                   requested_model_verified=True)


def sessions(client, task="criterion_proposal"):
    return [(row[0], row[1]) for row in client.app.state.store.conn.execute(
        "SELECT m.status, m.raw_output FROM model_sessions m JOIN step_inputs si ON si.id = m.step_input_id"
        " WHERE si.task_type = ? ORDER BY m.started_at, m.rowid", (task,))]


def test_a_replayed_arm_takes_the_baselines_plan_and_stops_rather_than_searching_under_one_it_cannot_check(tmp_path, monkeypatch):
    """The arm's records are its own, so the baseline's search plan names spans in records this library does not
    have: the plan is replayed and then refused by the contract, and the arm stops at the planning step instead
    of searching under a plan it cannot check. An arm that wants the same plan has to be given the same records.

    What this shows is the refusal, not that a repair replays: the baseline's own invalid answer and its repair
    are recorded here only to set the arm up.
    """
    first = {"sent": False}

    def responder(si):
        if si["task_type"] == "criterion_proposal" and not first["sent"]:
            first["sent"] = True
            return "{}"  # invalid: the product sends one repair with the issues in the message
        return valid_response(si)

    base = client_for(tmp_path / "base", monkeypatch, OpenAlex(), AliasAdapter(responder))
    rid, run_id = start(base)
    assert wait(base, rid, run_id)[1]["status"] == "completed"
    baseline = sessions(base)
    # Three proposal runs, the first of them answered badly once and repaired.
    assert len(baseline) == 4 and baseline[0][1] == "{}"
    base.__exit__(None, None, None)

    log = tmp_path / "replay.jsonl"
    replay = replay_answers.ReplayAdapter(FakeAdapter(), replay_answers.Baseline.load(tmp_path / "base" / "data"),
                                          log, tmp_path / "arm" / "data" / "library.sqlite", sleep=no_sleep)
    arm = client_for(tmp_path / "arm", monkeypatch, OpenAlex(), replay)
    rid, run_id = start(arm)
    stopped = wait(arm, rid, run_id)[1]
    assert (stopped["status"], stopped["error"]["reason"]) == ("paused", "model_call_failed")
    # The baseline's plan came back for its call and the contract refused it, because it names spans in records this
    # library does not have; the repair the product then sent had no baseline reply left to take. The criterion's
    # proposals are replayed before it: they read the question alone, so the run sends them beside the plan call.
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    taken = [(r["task_type"], r["outcome"], r.get("reason")) for r in rows]
    assert taken[-2:] == [("search_plan", "replayed", None),
                          ("search_plan", "refused", "more_calls_than_baseline")]
    assert {row[:2] for row in taken[:-2]} == {("criterion_proposal", "replayed"), ("search_phrases", "replayed")}


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
    prices = json.loads((Path(__file__).resolve().parents[2] / "scripts/benchmark/openalex_prices.json").read_text())
    bound = spend_ledger.question_bound_usd("standard", prices)
    assert bound > 0
    assert spend_ledger.question_bound_usd("standard", prices | {"semantic": 0.02}) > bound
    assert spend_ledger.question_requests("standard")["content"] >= 20
    assert spend_ledger.question_bound_usd("standard", prices | {"content": 0.02}) - bound == pytest.approx(
        spend_ledger.question_requests("standard")["content"] * 0.01)


def test_observed_openalex_costs_sum_each_kind_in_a_fixture_library(tmp_path):
    from deixis.storage import db
    from deixis.workflow.run.store import Store

    data = tmp_path / "data"
    data.mkdir()
    conn = db.connect(data / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex"], "fake", "m", "en")
    run_id = store.create_run(rid, "discovery", {}, None)["id"]
    for kind, cost in (("search", "0.001"), ("search", "0.002"), ("semantic", "0.001"),
                       ("list", "0.0001"), ("count", "0.001"), ("doi_lookup", "0"),
                       ("content_lookup", "0"), ("content", "0.01")):
        store.record_openalex_reply(run_id, kind, {"x-ratelimit-cost-usd": cost,
                                                   "x-ratelimit-credits-used": "10"})
    conn.close()
    prices = json.loads(openalex_costs.PRICES.read_text())
    result = openalex_costs.summarize(data, run_id, prices)
    assert result["observed_usd"] == openalex_costs.Decimal("0.0151")
    assert result["by_kind"]["search"] == {"replies": 2, "cost_usd": openalex_costs.Decimal("0.003")}
    assert result["estimated_bound_usd"] == openalex_costs.Decimal(str(
        spend_ledger.question_bound_usd("standard", prices)))


def test_a_missing_question_makes_a_paired_gate_inconclusive_and_a_failed_one_scores_zero():
    expected = ["q1", "q2"]
    base = {"q1": {50: 0.5}, "q2": {50: 0.5}}
    gate = m1_score.paired_gate({"q1": {50: 0.5}}, base, expected, 50, -0.02)
    assert gate["verdict"] == "inconclusive" and gate["missing"] == {"m1": ["q2"], "base": []}
    gate = m1_score.paired_gate({"q1": {50: 0.5}, "q2": None}, base, expected, 50, -0.02)
    assert gate["n"] == 2 and gate["verdict"] == "fail" and gate["mean"] == pytest.approx(-0.25)


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


def test_a_run_without_frozen_forms_that_match_their_digest_is_not_checked_with_rebuilt_ones(tmp_path):
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
        budget = json.dumps({"fast_path": {"chain_rule": chaining.RULE_V3}})
        listing = json.dumps({"manifest": {"blocks": {"task": ["pump"]}, "versions": {}}})
        for n, body in enumerate([{"admission_forms": forms, "admission_forms_sha256": "sha256:0"}, {}]):
            conn.execute("INSERT INTO runs VALUES (?, ?, 1, 'discovery', ?, ?)", (f"run_{n}", f"res_{n}", budget, n))
            conn.execute("INSERT INTO run_steps VALUES (?, 'small_batch:v1:list', ?)", (f"run_{n}", listing))
            conn.execute("INSERT INTO run_steps VALUES (?, 'protocol', ?)", (f"run_{n}", '{"protocol_revision": 1}'))
            conn.execute("INSERT INTO protocol_records VALUES (?, 1, 1, ?)",
                         (f"res_{n}", json.dumps({"citation_chaining": body})))
    checked = chain_rule_check.check(path)
    assert checked == {"run_0": {"rule": chaining.RULE_V3, "forms_unverified": True},  # digest does not match
                       "run_1": {"rule": chaining.RULE_V3, "forms_unverified": True}}  # nothing frozen


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


# ---- check.py: the keyword ranking and the list the product delivered ------------------------------------------

def _snapshot(path, delivered):
    """A SYNTHETIC answered research: two works, a keyword ranking and the frozen small-batch list.

    The keyword ranking puts the target work second; `delivered` is the order of work ids in the list the product
    delivered, so a test can give the two orders different places for the same work.
    """
    from deixis.storage import db as storage_db
    conn = storage_db.connect(path)
    storage_db.migrate(conn)
    ts = "2026-11-08T00:00:00.000+00:00"
    with storage_db.transaction(conn):
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_S', 'S', ?, ?)", (ts, ts))
        conn.execute("INSERT INTO scope_revisions (research_id, revision, question, source_scope, providers_json,"
                     " effort, model_connection, created_at) VALUES ('res_S', 1, ?, 'academic', '[\"openalex\"]',"
                     " 'quick', 'fake', ?)", (QUESTION, ts))
        for kind in ("discovery", "answer"):
            conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json,"
                         " usage_json, created_at, updated_at) VALUES (?, 'res_S', 1, ?, 'completed', 'answer', '{}',"
                         " '{}', ?, ?)", (f"run_{kind}", kind, ts, ts))
        for n, (work, title) in enumerate((("wrk_a", "SYNTHETIC other"), ("wrk_b", "SYNTHETIC target"))):
            conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (work, ts))
            conn.execute("INSERT INTO source_versions (id, work_id, title, doi, origin, version_label, created_at)"
                         " VALUES (?, ?, ?, ?, 'provider', 'publishedVersion', ?)",
                         (f"srv_{n}", work, title, f"10.0000/s{n}", ts))
        # One answered keyword query, its hit rows and its candidates: the pool the measurement reads.
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt, output_json,"
                     " started_at, finished_at) VALUES ('stp_search', 'run_discovery', 'search:0',"
                     " 'provider_search:openalex', 'succeeded', 1, '{}', ?, ?)", (ts, ts))
        conn.execute("INSERT INTO search_runs (id, research_id, run_id, step_id, provider, query_text,"
                     " request_description, access_mode, status, result_count, page_limit, retrieved_at,"
                     " scope_revision, sort) VALUES ('srn_0', 'res_S', 'run_discovery', 'stp_search', 'openalex',"
                     " 'q', 'GET SYNTHETIC', 'keyless', 'completed', 2, 25, ?, 1, NULL)", (ts,))
        for n in (0, 1):
            conn.execute("INSERT INTO candidate_hits (research_id, scope_revision, source_version_id, search_run_id,"
                         " rank, raw_score) VALUES ('res_S', 1, ?, 'srn_0', ?, ?)", (f"srv_{n}", n, 10.0 - n))
            conn.execute("INSERT INTO candidates (id, research_id, search_run_id, source_version_id, rank,"
                         " scope_revision, created_at) VALUES (?, 'res_S', 'srn_0', ?, ?, 1, ?)",
                         (f"cnd_{n}", f"srv_{n}", n, ts))
        # The keyword ranking: the other work first, the target second.
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt, output_json,"
                     " started_at, finished_at) VALUES ('stp_rank', 'run_discovery', 'ranking', 'code:ranking',"
                     " 'succeeded', 1, '{}', ?, ?)", (ts, ts))
        for n in (0, 1):
            conn.execute("INSERT INTO record_signal_ranks (ranking_step_id, research_id, source_version_id, signal,"
                         " rank, available) VALUES ('stp_rank', 'res_S', ?, 'inspection', ?, 1)", (f"srv_{n}", n))
        # The list the product delivered, in whatever order the caller asked for.
        items = [{"position": i + 1, "work_id": work, "head": "srv_0"} for i, work in enumerate(delivered)]
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt, output_json,"
                     " started_at, finished_at) VALUES ('stp_list', 'run_discovery', 'small_batch:v1:list',"
                     " 'code:small_batch_list', 'succeeded', 1, ?, ?, ?)", (json.dumps({"items": items}), ts, ts))
        # The answer and the StepInput it was written from; its creation time is the measurement's cutoff.
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt, started_at,"
                     " finished_at) VALUES ('stp_answer', 'run_answer', 'answer', 'model:answer', 'succeeded', 1,"
                     " ?, ?)", (ts, ts))
        conn.execute("INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type, scope_revision,"
                     " skill_package_hash, payload_json, base_instructions, developer_instructions, user_message,"
                     " output_schema_json, created_at) VALUES ('sti_S', 'stp_answer', 'res_S', 'run_answer', 1,"
                     " 'answer', 1, 'h', ?, 'b', 'd', 'u', '{}', ?)",
                     (json.dumps({"question": {"text": QUESTION}, "sources": [], "passages": []}), ts))
        conn.execute("INSERT INTO answers (id, research_id, run_id, step_id, step_input_id, scope_revision, status,"
                     " draft_json, validation_json, created_at) VALUES ('ans_S', 'res_S', 'run_answer', 'stp_answer',"
                     " 'sti_S', 1, 'structurally_valid', ?, '{}', ?)", (json.dumps({"claims": []}), ts))
        # The answer run names the discovery run whose frozen list it answered from, as the product stores it.
        conn.execute("UPDATE runs SET budget_json = ? WHERE id = 'run_answer'",
                     (json.dumps({"inspection": {"list_run_id": "run_discovery"}}),))
    conn.close()


QUESTION = "SYNTHETIC measurement question?"
BENCH = {"name": "SYNTHETIC", "question": QUESTION,
         "papers": [{"key": "target", "doi": "10.0000/s1", "title": "SYNTHETIC target", "label": "ilgili"}]}


def test_the_measurement_reports_the_keyword_ranking_and_the_list_the_product_delivered(tmp_path):
    """The tool read only `code:ranking`, so a rerank that moved the delivered list left no mark on any measurement.

    The target work is second in the keyword ranking and first in the delivered list: the report must carry both.
    """
    import check

    BENCH["question_sha256"] = check.sha(QUESTION)
    _snapshot(tmp_path / "library.sqlite", ["wrk_a", "wrk_b"])
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    conn.row_factory = sqlite3.Row
    first = check.measure(conn, "res_S", "ans_S", BENCH)
    assert first["papers"][0]["keyword_rank"] == 2 and first["papers"][0]["delivered_rank"] == 2
    assert first["delivered_list_step_id"] == "stp_list"
    conn.close()

    # The same keyword ranking, the target first in the delivered list: only the delivered places move.
    _snapshot(tmp_path / "moved.sqlite", ["wrk_b", "wrk_a"])
    conn = sqlite3.connect(tmp_path / "moved.sqlite")
    conn.row_factory = sqlite3.Row
    moved = check.measure(conn, "res_S", "ans_S", BENCH)
    assert moved["papers"][0]["keyword_rank"] == 2 and moved["papers"][0]["delivered_rank"] == 1
    assert moved["coverage"]["all"]["counts"]["keyword_top_20"] == 1
    assert moved["coverage"]["all"]["counts"]["delivered_top_20"] == 1
    conn.close()


def test_the_delivered_order_comes_from_the_run_the_answer_names_not_the_latest_list(tmp_path):
    """A second discovery of the same question revision freezes its own list after the answer run's. Reading the
    latest list would lend that order to an answer written from another one."""
    import check

    BENCH["question_sha256"] = check.sha(QUESTION)
    _snapshot(tmp_path / "library.sqlite", ["wrk_a", "wrk_b"])
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    conn.row_factory = sqlite3.Row
    later = "2026-11-08T00:01:00.000+00:00"
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, usage_json,"
                 " created_at, updated_at) VALUES ('run_other', 'res_S', 1, 'discovery', 'completed', 'answer',"
                 " '{}', '{}', ?, ?)", (later, later))
    conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt, output_json, started_at,"
                 " finished_at) VALUES ('stp_other', 'run_other', 'small_batch:v1:list', 'code:small_batch_list',"
                 " 'succeeded', 1, ?, ?, ?)",
                 (json.dumps({"items": [{"position": 1, "work_id": "wrk_b"}, {"position": 2, "work_id": "wrk_a"}]}),
                  later, later))
    conn.commit()
    report = check.measure(conn, "res_S", "ans_S", BENCH)
    assert report["delivered_list_step_id"] == "stp_list"  # the answer run's own list, not the later one
    assert report["delivered_list_binding"] == "answer_run_binding"
    assert report["papers"][0]["delivered_rank"] == 2
    conn.close()


def test_an_answer_run_that_stored_no_list_binding_falls_back_to_the_latest_list_and_says_so(tmp_path):
    import check

    BENCH["question_sha256"] = check.sha(QUESTION)
    _snapshot(tmp_path / "library.sqlite", ["wrk_a", "wrk_b"])
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute("UPDATE runs SET budget_json = '{}' WHERE id = 'run_answer'")
    conn.commit()
    report = check.measure(conn, "res_S", "ans_S", BENCH)
    assert report["delivered_list_step_id"] == "stp_list"
    assert report["delivered_list_binding"] == "inferred_by_time"
    conn.close()


def test_a_research_whose_delivered_list_was_never_frozen_says_so_instead_of_reporting_a_place(tmp_path):
    import check

    BENCH["question_sha256"] = check.sha(QUESTION)
    _snapshot(tmp_path / "library.sqlite", ["wrk_a", "wrk_b"])
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute("DELETE FROM run_steps WHERE id = 'stp_list'")
    conn.commit()
    report = check.measure(conn, "res_S", "ans_S", BENCH)
    assert report["delivered_list_binding"] == "not_recorded_require_delivered_list"
    assert report["papers"][0]["delivered_rank"] is None
    assert report["coverage"]["all"]["counts"]["delivered_top_50"] is None
    conn.close()

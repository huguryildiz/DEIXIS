"""The block a phrase belongs to, asked of a model over the phrases code extracted (SW17, slice 04d).

Two halves. The first drives `apply_labels` directly: how three runs are counted, what happens without a majority,
and what happens when runs are missing. The second drives a whole `sw` discovery run through the API with a scripted
model, because the rule this slice must not break — a discovery run searches while every model call fails — is only
visible end to end.

Questions and records here are SYNTHETIC and each question is from a different field, so no test can be made to pass
by adding a topic word to the product. Passing shows workflow behavior, not labelling quality: that was measured once
in `.local/sw-block-labelling-2026-09-21/` and is measured again in slice 24.
"""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.domain import contracts
from deixis.domain.skill import RUNTIME_FILES
from deixis.domain.vocabulary import extract
from deixis.models.adapter import ModelStepResult
from deixis.workflow.vocabulary import (LABEL_MAJORITY, LABEL_RUNS, MAX_LABELLED_PHRASES, apply_labels,
                                        labelling_phrases)
from fakes import FakeAdapter, envelope, valid_response
from test_vocabulary_flow import (CountingOpenAlex, DeadAdapter, KEY_TERMS, app_for, start, store_at, wait)

# The code rule reads the word in front of a phrase: "with" marks a method position, so "distributed ledgers" becomes
# a claim word and the setting drops out of the query. That is the error SW17 exists to correct.
SUPPLY = "What is the effect of shipment batching on delivery delay in supply chains with distributed ledgers?"
AGRONOMY = ("Which effects of irrigation scheduling on marketable yield in greenhouse tomato production are "
            "reported, using stochastic programming, not case reports?")


def labels_of(extraction, **overrides):
    """One run's answer: the rule's own blocks unless the test names another block for a phrase."""
    run = {row["phrase"]: row["rule_block"] for row in labelling_phrases(extraction)}
    return run | overrides


# ---- Task 3: counting the runs -----------------------------------------------------------------------------

def test_the_rule_stands_when_no_run_arrived():
    extraction = extract(SUPPLY)
    labelled, records = apply_labels(extraction, [])
    assert labelled == extraction and labelled.block_assignment == "rule"
    assert [r["phrase"] for r in records] == [row["phrase"] for row in labelling_phrases(extraction)]
    assert {r["origin"] for r in records} == {"rule"}
    assert all(r["runs"] == [] for r in records)


def test_three_runs_that_agree_move_the_phrase_the_rule_called_a_claim_into_the_query():
    """SW17.4: the rule's method position is not kept as a second veto, which is the point of the experiment."""
    extraction = extract(SUPPLY)
    assert extraction.claim_words == ["distributed ledgers"]
    run = labels_of(extraction, **{"distributed ledgers": "setting"})
    labelled, records = apply_labels(extraction, [run] * LABEL_RUNS)
    assert "distributed ledgers" in labelled.blocks["setting"]
    assert labelled.claim_words == [] and labelled.block_assignment == "model"
    record = next(r for r in records if r["phrase"] == "distributed ledgers")
    assert record == {"phrase": "distributed ledgers", "rule_block": "claim", "block": "setting", "origin": "model",
                      "runs": ["setting", "setting", "setting"]}


def test_two_runs_of_three_are_a_majority_and_the_third_is_recorded():
    extraction = extract(SUPPLY)
    agreeing = labels_of(extraction, **{"distributed ledgers": "setting"})
    other = labels_of(extraction, **{"distributed ledgers": "task"})
    labelled, records = apply_labels(extraction, [agreeing, other, agreeing])
    assert "distributed ledgers" in labelled.blocks["setting"]
    assert next(r for r in records if r["phrase"] == "distributed ledgers")["runs"] == ["setting", "setting", "task"]


def test_three_runs_that_all_disagree_keep_the_rules_label_and_drop_the_phrase_from_the_query():
    extraction = extract(SUPPLY)
    runs = [labels_of(extraction, **{"shipment batching": block}) for block in ("setting", "task", "outcome")]
    labelled, records = apply_labels(extraction, runs)
    assert all("shipment batching" not in phrases for phrases in labelled.blocks.values())
    assert "shipment batching" not in labelled.claim_words + labelled.exclusion_words
    record = next(r for r in records if r["phrase"] == "shipment batching")
    assert record["block"] == "task" and record["origin"] == "rule"  # the rule's label is what is recorded


def test_one_surviving_run_is_no_majority_and_leaves_the_whole_rule_in_place():
    """Two runs failed. One run cannot carry a 2-of-3 majority, so nothing the model said is applied."""
    extraction = extract(SUPPLY)
    run = labels_of(extraction, **{"distributed ledgers": "setting"})
    labelled, records = apply_labels(extraction, [run])
    assert labelled == extraction and labelled.block_assignment == "rule"
    assert next(r for r in records if r["phrase"] == "distributed ledgers")["runs"] == ["setting"]
    assert {r["origin"] for r in records} == {"rule"}


def test_runs_that_agree_on_nothing_leave_the_whole_rule_in_place_instead_of_an_empty_query():
    """Every phrase without a majority would leave the query: the gate would be empty and the run would stop for key
    terms. A labelling that cannot be searched is not applied; the rule's assignment is the floor (SW17.5)."""
    extraction = extract(SUPPLY)
    phrases = [row["phrase"] for row in labelling_phrases(extraction)]
    runs = [{phrase: block for phrase in phrases} for block in ("setting", "task", "outcome")]
    labelled, records = apply_labels(extraction, runs)
    assert labelled == extraction and labelled.block_assignment == "rule"
    assert {r["origin"] for r in records} == {"rule"}
    assert all(r["block"] == r["rule_block"] and len(r["runs"]) == LABEL_RUNS for r in records)  # the votes stay on record


def test_runs_that_agree_no_phrase_is_a_search_term_leave_the_whole_rule_in_place():
    extraction = extract(SUPPLY)
    run = {row["phrase"]: "not_a_term" for row in labelling_phrases(extraction)}
    labelled, records = apply_labels(extraction, [run] * LABEL_RUNS)
    assert labelled == extraction and labelled.block_assignment == "rule"
    assert {r["origin"] for r in records} == {"rule"}


def test_a_phrase_labelled_not_a_term_leaves_every_list():
    extraction = extract(AGRONOMY)
    assert "effects" in extraction.blocks["task"]
    run = labels_of(extraction, **{"effects": "not_a_term"})
    labelled, records = apply_labels(extraction, [run] * LABEL_RUNS)
    assert all("effects" not in phrases for phrases in labelled.blocks.values())
    assert "effects" not in labelled.claim_words + labelled.exclusion_words
    assert next(r for r in records if r["phrase"] == "effects")["block"] == "not_a_term"


def test_a_phrase_the_model_calls_a_claim_leaves_the_query_and_joins_the_claim_words():
    extraction = extract(AGRONOMY)
    assert "irrigation scheduling" in extraction.blocks["task"]
    run = labels_of(extraction, **{"irrigation scheduling": "claim"})
    labelled, _ = apply_labels(extraction, [run] * LABEL_RUNS)
    assert "irrigation scheduling" not in labelled.blocks["task"]
    assert "irrigation scheduling" in labelled.claim_words


def test_the_order_the_runs_arrive_in_does_not_decide_the_result():
    extraction = extract(AGRONOMY)
    first = labels_of(extraction, **{"marketable yield": "outcome"})
    second = labels_of(extraction, **{"marketable yield": "outcome", "case reports": "not_a_term"})
    third = labels_of(extraction, **{"marketable yield": "task"})
    one, one_records = apply_labels(extraction, [first, second, third])
    other, other_records = apply_labels(extraction, [third, second, first])
    assert one == other and one_records == other_records
    assert "marketable yield" in one.blocks["outcome"]


def test_the_user_s_key_terms_are_labelled_by_nobody_but_the_user():
    extraction = extract("Hangi ölçekleme modelleri önerilmiştir?", key_terms=KEY_TERMS)
    assert extraction.block_assignment == "user"


def test_the_contract_bounds_the_step_at_the_phrase_count_the_flow_will_send():
    schema = contracts.step_output_schema("vocabulary_labels")
    assert schema["properties"]["labels"]["maxItems"] == MAX_LABELLED_PHRASES
    assert RUNTIME_FILES["vocabulary_labels"] == ("SKILL.md", "references/vocabulary-labels.md")


# ---- Task 4: the step inside a discovery run ---------------------------------------------------------------

def labelling(overrides=None, invalid_call=None, disagreeing_call=None):
    """A model that labels the given phrases, and on one named call answers badly on purpose."""
    overrides, calls = overrides or {}, []

    def responder(si):
        if si["task_type"] != "vocabulary_labels":
            return valid_response(si)
        calls.append(si)
        given = si["vocabulary_target"]["phrases"]
        if len(calls) == disagreeing_call:  # a third opinion that no majority forms around
            labels = [{"phrase": p["phrase"], "block": p["rule_block"]} for p in given]
        else:
            labels = [{"phrase": p["phrase"], "block": overrides.get(p["phrase"], p["rule_block"])} for p in given]
        if len(calls) == invalid_call:  # a phrase the question does not hold: the whole run is dropped, not repaired
            labels.append({"phrase": "SYNTHETIC invented phrase", "block": "setting"})
        return json.dumps(envelope(si, "deixis.vocabulary_labels.v1") | {"labels": labels})

    responder.calls = calls
    return responder


def stored_vocabulary(tmp_path, rid):
    """The vocabulary step's stored output, read from the library after the client closed it."""
    return store_at(tmp_path).latest_step_output(rid, "vocabulary", 1)["vocabulary"]


def test_an_sw_discovery_searches_with_the_rules_blocks_while_every_labelling_call_fails(tmp_path, monkeypatch):
    """Slice 04a's acceptance condition, narrowed: no *required* model call stands between a question and its search."""
    openalex, adapter = CountingOpenAlex(), DeadAdapter()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, SUPPLY)
        view, run = wait(client, rid, run_id)
    vocabulary = stored_vocabulary(tmp_path, rid)
    assert openalex.searches, run
    assert [c["task_type"] for c in adapter.calls].count("vocabulary_labels") == LABEL_RUNS
    labelled = {s["operation_key"]: s["status"] for s in run["steps"] if s["operation_key"].startswith("vocabulary_labels")}
    assert labelled == {f"vocabulary_labels_{i + 1}": "failed" for i in range(LABEL_RUNS)}
    assert vocabulary["block_assignment"] == "rule"
    assert vocabulary["labelling"]["runs_ok"] == 0 and len(vocabulary["labelling"]["failures"]) == LABEL_RUNS
    # The rule's own blocks were searched, and its claim word stayed out of every query.
    assert {t["phrase"] for t in vocabulary["terms"]} == {"delivery delay", "supply chains", "shipment batching"}
    assert all("ledger" not in query for query in openalex.searches + openalex.counts)


def test_two_runs_of_three_agreeing_put_the_models_block_in_the_query(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    adapter = FakeAdapter(labelling({"distributed ledgers": "setting"}, disagreeing_call=3))
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, SUPPLY)
        wait(client, rid, run_id)
    vocabulary = stored_vocabulary(tmp_path, rid)
    assert vocabulary["block_assignment"] == "model"
    assert vocabulary["claim_words"] == [] and vocabulary["labelling"]["runs_ok"] == LABEL_RUNS
    setting = [t["phrase"] for t in vocabulary["terms"] if t["block"] == "setting"]
    assert "distributed ledgers" in setting
    # The query enters by the term's root word, so the phrase shows up there as "distributed" (SW3.5).
    assert any("distributed" in query for query in openalex.searches), openalex.searches
    record = next(p for p in vocabulary["labelling"]["phrases"] if p["phrase"] == "distributed ledgers")
    assert record == {"phrase": "distributed ledgers", "rule_block": "claim", "block": "setting", "origin": "model",
                      "runs": ["claim", "setting", "setting"]}


def test_a_model_that_calls_every_phrase_a_claim_does_not_take_the_search_away(tmp_path, monkeypatch):
    """The model is up and wrong. The run searches with the rule's blocks instead of stopping for key terms."""
    openalex = CountingOpenAlex()
    phrases = [row["phrase"] for row in labelling_phrases(extract(SUPPLY))]
    adapter = FakeAdapter(labelling({phrase: "claim" for phrase in phrases}))
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, SUPPLY)
        wait(client, rid, run_id)
    vocabulary = stored_vocabulary(tmp_path, rid)
    assert openalex.searches
    assert vocabulary["block_assignment"] == "rule"
    assert vocabulary["labelling"]["runs_ok"] == LABEL_RUNS and vocabulary["labelling"]["fallback"] == "labelling_unsearchable"
    assert {t["phrase"] for t in vocabulary["terms"]} == {"delivery delay", "supply chains", "shipment batching"}


def test_a_run_that_names_a_phrase_outside_the_allowlist_is_dropped_and_the_other_two_decide(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    adapter = FakeAdapter(labelling({"distributed ledgers": "setting"}, invalid_call=2))
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, SUPPLY)
        view, run = wait(client, rid, run_id)
    vocabulary = stored_vocabulary(tmp_path, rid)
    second = next(s for s in run["steps"] if s["operation_key"] == "vocabulary_labels_2")
    assert second["status"] == "failed" and second["error_code"] == "invalid_model_output"
    assert [i["code"] for i in second["error"]] == ["phrase_not_in_allowlist"]
    # One attempt only: an invented phrase is rejected, not repaired (SW17.1).
    assert [c["task_type"] for c in adapter.calls].count("vocabulary_labels") == LABEL_RUNS
    assert vocabulary["labelling"]["runs_ok"] == LABEL_RUNS - 1
    assert "distributed ledgers" in [t["phrase"] for t in vocabulary["terms"] if t["block"] == "setting"]


def test_a_resumed_run_labels_nothing_again(tmp_path, monkeypatch):
    """The search fails on the first pass; resuming retries the search and must not pay for the labelling again."""
    openalex = CountingOpenAlex()
    adapter = FakeAdapter(labelling({"distributed ledgers": "setting"}))
    down = {"now": True}

    def handler(request):
        params = request.url.params
        if down["now"] and not (params.get("per_page") == "1" and params.get("select") == "id"):
            return httpx.Response(503)
        return openalex(request)

    with TestClient(app_for(tmp_path, monkeypatch, handler, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, SUPPLY)
        view, run = wait(client, rid, run_id)
        assert run["status"] == "paused" and not openalex.searches
        labelled = [c["step_input_id"] for c in adapter.calls if c["task_type"] == "vocabulary_labels"]
        assert len(labelled) == LABEL_RUNS
        down["now"] = False
        client.post(f"/api/runs/{run_id}/resume")
        wait(client, rid, run_id)
    vocabulary = stored_vocabulary(tmp_path, rid)
    assert openalex.searches
    assert [c["step_input_id"] for c in adapter.calls if c["task_type"] == "vocabulary_labels"] == labelled
    assert "distributed ledgers" in [t["phrase"] for t in vocabulary["terms"] if t["block"] == "setting"]


def test_a_research_whose_user_wrote_the_key_terms_opens_no_labelling_step(tmp_path, monkeypatch):
    adapter = FakeAdapter(labelling())
    with TestClient(app_for(tmp_path, monkeypatch, CountingOpenAlex(), adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "Hangi ölçekleme modelleri önerilmiştir?", key_terms=KEY_TERMS)
        view, run = wait(client, rid, run_id)
    vocabulary = stored_vocabulary(tmp_path, rid)
    assert not any(s["operation_key"].startswith("vocabulary_labels") for s in run["steps"]), run["steps"]
    assert vocabulary["block_assignment"] == "user"
    assert vocabulary["labelling"]["skipped"] == "user_key_terms"
    assert "vocabulary_labels" not in [c["task_type"] for c in adapter.calls]


def test_a_legacy_research_opens_no_labelling_step(tmp_path, monkeypatch):
    from test_provider_flow import routed, two_provider_plan

    adapter = FakeAdapter(two_provider_plan)
    with TestClient(app_for(tmp_path, monkeypatch, routed, adapter, workflow="legacy")) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "How is diffusion channel scheduling optimized?")
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert not any(s["operation_key"].startswith("vocabulary") for s in run["steps"])
    assert "vocabulary_labels" not in [c["task_type"] for c in adapter.calls]


def test_the_frozen_protocol_names_the_origin_of_every_block_and_is_the_same_on_a_second_build(tmp_path, monkeypatch):
    from deixis.config import Settings
    from deixis.domain.canonical import sha256_hex
    from deixis.workflow import protocol
    from deixis.workflow.flow import _criterion_result

    adapter = FakeAdapter(labelling({"distributed ledgers": "setting"}))
    with TestClient(app_for(tmp_path, monkeypatch, CountingOpenAlex(), adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, SUPPLY)
        wait(client, rid, run_id)
    store = store_at(tmp_path)
    row = store.conn.execute("SELECT * FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()
    body = json.loads(row["body_json"])
    assert body["block_assignment"] == "model"
    assert {term["phrase"]: term["block_origin"] for term in body["vocabulary"]}["distributed ledgers"] == "model"
    assert all(term["block_origin"] in ("rule", "model") for term in body["vocabulary"])

    stored = store.latest_step_output(rid, "vocabulary", 1)
    # The criterion this run agreed on is an input of the body like the vocabulary, so the rebuild is given it too.
    criterion = _criterion_result(store.latest_step_output(rid, "criterion", 1))
    again = protocol.build_protocol(
        store.scope(rid, 1), store.run(run_id)["budget"], None, stored["queries"], body["skill_package_hash"],
        Settings(data_dir=None, search_workflow="sw"), vocabulary=stored["vocabulary"], criterion=criterion,
        approval=store.approval_step(run_id)["output"]["approval"])
    assert sha256_hex(again) == row["body_sha256"]

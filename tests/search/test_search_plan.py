"""The search plan a model writes from the first semantic page: its contract, its records and its seeds (P3).

Every question, record, term and count here is SYNTHETIC, OpenAlex is mocked and the model is the fake adapter, so
passing shows workflow behavior: which call is made, what code checks, what the chain starts from and what is
recorded. It says nothing about whether a model writes a good plan; that is not measured anywhere yet.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deixis.domain import contracts
from deixis.domain.rules import LITERATURE_TASKS, schema_repairs
from deixis.domain.skill import RUNTIME_FILES
from deixis.workflow.run import fast_path
from deixis.workflow.search import fast_chain, search_plan
from fakes import FakeAdapter, valid_response
from test_hit_rank import library, record, search
from test_search_query import OpenAlex, WORK, calls, client_for, protocol_body, start, step_output, wait

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text(encoding="utf-8"))["H_search_plan"]
# The record the mocked OpenAlex returns: the plan reads its keywords beside the title and the abstract.
PLAN_WORK = WORK | {"keywords": [{"display_name": "rail freight"}, {"display_name": "timetabling"}]}


def plan(**changes):
    """The fake's own answer for the fixture step input, with `changes` written over it."""
    return json.loads(valid_response(STEP_INPUT)) | changes


def issues(draft):
    return sorted({issue.code for issue in contracts.validate_model_output(STEP_INPUT, draft).issues})


# ---- the contract of one call -------------------------------------------------------------------------------

def test_the_task_is_registered_with_its_schema_its_method_file_and_one_repair():
    assert contracts.TASK_OUTPUTS["search_plan"] == ("SearchPlan",)
    assert contracts.SCHEMA_VERSIONS["SearchPlan"] == "deixis.search_plan.v2"
    assert RUNTIME_FILES["search_plan"] == ("SKILL.md", "references/search-plan.md")
    assert "search_plan" in LITERATURE_TASKS  # the literature model writes the plan, as it wrote the query
    assert schema_repairs("search_plan") == 1
    assert contracts.strict_compatibility_issues(contracts.step_output_schema("search_plan")) == []


def test_a_terms_evidence_is_read_back_from_the_text_the_step_sent():
    # The fake's own plan reads its terms out of the records the fixture sends, so it passes the check.
    assert issues(plan()) == []
    source, draft = STEP_INPUT["sources"][0], plan()
    start, end = draft["setting"][0]["evidence"]["span"]
    assert source["title"][start:end] == draft["setting"][0]["term"]

    # A phrase the field does not hold at that place is refused, whatever the model wrote about it.
    moved = plan()
    moved["setting"][0]["evidence"] = moved["setting"][0]["evidence"] | {"span": [start + 1, end + 1]}
    assert issues(moved) == ["plan_term_not_at_span"]
    outside = plan()
    outside["task"][0]["evidence"] = outside["task"][0]["evidence"] | {"span": [0, 10_000]}
    assert issues(outside) == ["plan_span_outside_field"]

    # A record the step did not send, and a field of a record it did not send, are refused too.
    unknown = plan()
    unknown["setting"][0]["evidence"] = unknown["setting"][0]["evidence"] | {"record_id": "srv_SYNTHETICother"}
    assert issues(unknown) == ["plan_record_unknown"]
    # The fixture's record carries keywords; a record without them has no `keywords` field to read a term from.
    without = dict(STEP_INPUT, sources=[{k: v for k, v in STEP_INPUT["sources"][0].items() if k != "index_keywords"}])
    from_keywords = plan()
    from_keywords["setting"][0]["evidence"] = from_keywords["setting"][0]["evidence"] | {"field": "keywords"}
    assert "plan_field_not_sent" in {i.code for i in contracts.validate_model_output(without, from_keywords).issues}


def test_the_chains_starting_works_are_checked_against_the_records_the_step_was_given():
    work = STEP_INPUT["sources"][0]["work_id"]
    assert issues(plan(seed_work_ids=[work])) == []
    assert issues(plan(seed_work_ids=["wrk_SYNTHETICother"])) == ["plan_seed_work_unknown"]
    assert issues(plan(seed_work_ids=[work, work])) == ["duplicate_seed_work"]


# ---- which records one call reads ---------------------------------------------------------------------------

def test_the_records_one_call_reads_are_the_pages_own_places_and_the_same_list_every_time():
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        records = [record(f"W{index}") for index in range(1, 8)]
        search(store, rid, run, search_plan.SEMANTIC_KEY, records)
        # A query of this run that is not the question's own request does not decide what the plan reads.
        search(store, rid, run, "search:fast:keyword:0", [record("W99")])
        places = [store.find_source_by_identifier("openalex", f"W{index}") for index in range(1, 8)]
        assert search_plan.page_records(store, run) == places
        assert search_plan.page_records(store, run) == search_plan.page_records(store, run)
        # Cut to a call's limit, the rule keeps the head in order and samples the rest at an even stride, so a
        # record far down the page can still be read and the same page always gives the same four records.
        assert search_plan.page_records(store, run, 4) == [places[0], places[1], places[2], places[4]]


def test_the_sampling_rule_keeps_the_head_in_order_and_strides_through_the_rest():
    page = [f"srv_{index:02d}" for index in range(20)]
    assert search_plan.sample(page, 50) == page  # a page that fits is read whole
    taken = search_plan.sample(page, 6)
    assert taken == ["srv_00", "srv_01", "srv_02", "srv_03", "srv_08", "srv_14"]
    assert taken == search_plan.sample(page, 6) and len(set(taken)) == 6


# ---- what the chain starts from -----------------------------------------------------------------------------

def test_a_forward_allowance_left_over_reads_the_next_page_of_the_same_seed():
    seeds = [{"source_version_id": "srv_a", "openalex_id": "W1", "references": []},
             {"source_version_id": "srv_b", "openalex_id": "W2", "references": []}]
    policy = {"backward_requests": 0, "backward_page_size": 50, "forward_requests": 5, "forward_page_size": 25}
    requests = fast_chain.request_plan(seeds, policy, set())["requests"]
    assert [(r["cites"], r["page"]) for r in requests] == [("W1", 1), ("W2", 1), ("W1", 2), ("W2", 2), ("W1", 3)]
    # Each page past the first names the request whose cursor it continues, which is the page before it of that seed.
    after = {r["key"]: r["after"] for r in requests}
    keys = [r["key"] for r in requests]
    assert after == {keys[0]: None, keys[1]: None, keys[2]: keys[0], keys[3]: keys[1], keys[4]: keys[2]}
    # Both seeds were requested: the count of seeds left without a request is not a count of pages.
    assert fast_chain.request_plan(seeds, policy, set())["forward_not_requested"] == 0
    narrow = fast_chain.request_plan(seeds, policy | {"forward_requests": 1}, set())
    assert [(r["cites"], r["page"]) for r in narrow["requests"]] == [("W1", 1)]
    assert narrow["forward_not_requested"] == 1


def test_a_run_writes_one_plan_call_from_the_pages_records(tmp_path, monkeypatch):
    import test_search_query

    # The mock's record carries the provider's own keywords for this run; everything else is the shared harness.
    monkeypatch.setattr(test_search_query, "WORK", PLAN_WORK)
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter)
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run

    # No labelling call and no query call: one plan call stands in their place.
    assert calls(adapter, "vocabulary_labels") == [] and calls(adapter, "search_query") == []
    sent = calls(adapter, "search_plan")
    assert len(sent) == 1  # one call in their place, so the run's model-call count did not rise
    # It read the records the question's own request returned: their titles, abstracts and the provider's keywords.
    assert [source["index_keywords"] for source in sent[0]["sources"]] == [["rail freight", "timetabling"]]
    assert [passage["locator"]["kind"] for passage in sent[0]["passages"]] == ["abstract"]
    stored = step_output(client, run_id, "search_query")
    assert stored["status"] == "ready" and stored["plan_rule"] == fast_path.PLAN_RULE
    assert stored["plan_records"] == [source["source_id"] for source in sent[0]["sources"]]
    assert [seed["openalex_id"] for seed in stored["plan_seeds"]] == ["W9"]
    # The labelling step says why it asked nothing, and the chain starts from the work the plan named.
    assert step_output(client, run_id, "vocabulary")["vocabulary"]["labelling"]["skipped"] == "search_plan"
    assert step_output(client, run_id, "fast_chain:seeds")["plan_seeds"] == ["W9"]
    # The protocol names the prompt the call really carried, read from the answer's own schema version.
    frozen = protocol_body(client, rid)["search_query"]
    assert frozen["prompt"] == {"files": ["SKILL.md", "references/search-plan.md"],
                                "schema_version": "deixis.search_plan.v2",
                                "skill_package_hash": sent[0]["skill_package_hash"]}
    assert frozen["answer"]["seed_work_ids"] == [sent[0]["sources"][0]["work_id"]]
    # The plan's own fingerprint (P4): what it read and what wrote it, frozen with the protocol and recomputable
    # from the StepInput the call really carried.
    from deixis.workflow.search import plan_identity
    print_record = {"resolved_model": frozen["resolved_model"], "skill_package_hash": sent[0]["skill_package_hash"],
                    "answer": frozen["answer"]}
    assert frozen["fingerprint"] == plan_identity.fingerprint(sent[0], print_record, fast_path.PLAN_RULE)
    assert frozen["fingerprint"]["records"] == len(sent[0]["sources"])


def test_a_person_who_saved_their_own_plan_is_asked_nothing(tmp_path, monkeypatch):
    """The person's plan outranks every proposal (S23a): the plan step does not run at all beside one."""
    from test_user_search_plan import Providers, client_for as plan_client, create, discover, plan, planning_calls, save

    adapter = FakeAdapter()
    client = plan_client(tmp_path, monkeypatch, Providers(), adapter)
    rid = create(client)
    assert discover(client, rid)["status"] == "completed"
    # The first run writes its plan from the page's records.
    assert "search_plan" in planning_calls(adapter, 1) and "search_query" not in planning_calls(adapter, 1)

    assert save(client, rid, plan()).status_code == 200
    second = discover(client, rid)
    assert second["status"] == "completed", second
    # The second run asks nothing: no plan call, no query call, no labelling, and the person's own words are searched.
    assert planning_calls(adapter, 2) == []
    labels = step_output(client, second["id"], "vocabulary")["vocabulary"]["labelling"]
    assert labels["skipped"] == "user_plan" and labels["runs_ok"] == 0
    stored = step_output(client, second["id"], "search_query")
    assert "plan_seeds" not in stored and stored["vocabulary"]["search_query"]["origin"] == "user"


class FirstPageEmpty(OpenAlex):
    """OpenAlex whose semantic request answers with an error until `ready`; its keyword searches answer as usual."""

    def __init__(self):
        super().__init__()
        self.ready = False

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org" and params.get("search.semantic") and not self.ready:
            self.semantic.append(params["search.semantic"])
            return httpx.Response(500, json={"message": "SYNTHETIC outage"})
        return super().__call__(request)


def test_a_first_page_with_no_record_stops_the_run_instead_of_writing_the_questions_own_query(tmp_path, monkeypatch):
    import test_search_query

    monkeypatch.setattr(test_search_query, "WORK", PLAN_WORK)
    openalex, adapter = FirstPageEmpty(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex, adapter)
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    # Nothing was searched on the question's own words in the plan's place, and no model was asked for a query.
    assert run["status"] == "paused" and run["pause_reason"] == "search_query_failed", run
    assert run["error"]["reason"] == "first_page_empty" and run["error"]["retries_left"] == 2
    assert calls(adapter, "search_plan") == [] and calls(adapter, "search_query") == []
    # The step is still pending with no query written, and says why it stopped.
    assert step_output(client, run_id, "search_query") == {"attempts": [], "choice": None, "status": "first_page_empty"}
    assert openalex.searches == []

    # Resuming sends the request again and the plan is written from the page it brings.
    openalex.ready = True
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
    _, resumed = wait(client, rid, run_id)
    assert resumed["status"] == "completed", resumed
    assert len(calls(adapter, "search_plan")) == 1
    stored = step_output(client, run_id, "search_query")
    assert stored["status"] == "ready" and [s["openalex_id"] for s in stored["plan_seeds"]] == ["W9"]


def test_a_backup_term_without_its_own_evidence_is_refused_with_the_chosen_terms(tmp_path):
    # A backup can reach the sent query in a chosen term's place, so its phrase is checked against the record too.
    draft = plan()
    draft["setting_backup"] = [{"term": "nowhere phrase",
                                "evidence": draft["setting"][0]["evidence"] | {"span": [0, 4]}}]
    assert issues(draft) == ["plan_term_not_at_span"]
    title = STEP_INPUT["sources"][0]["title"]
    at = title.index("controller")
    draft["setting_backup"] = [{"term": "controller",
                                "evidence": draft["setting"][0]["evidence"] | {"span": [at, at + len("controller")]}}]
    assert issues(draft) == []


def test_the_planning_arm_sends_a_failed_or_deadline_cancelled_first_page_again(monkeypatch):
    """The plan cannot be written without that page, so the planning arm retries it."""
    from deixis.workflow.search import search as fast_search

    seen = {}

    def sender(flow, run, scope, plan, retry_failed, shared, retry_cancels=("budget_exhausted",)):
        seen[run["id"]] = (retry_failed, retry_cancels)
        return None

    async def nothing(flow, run, plan, send_page):
        return None
    monkeypatch.setattr(fast_search, "frozen_body", lambda store, run: None)
    monkeypatch.setattr(fast_search, "first_request_plan", lambda run, scope, seed: {"semantic": {"query_text": None}})
    monkeypatch.setattr(fast_search, "page_sender", sender)
    monkeypatch.setattr(fast_search, "question_semantic", nothing)

    async def call():
        run = {"id": "run_x", "budget": {"fast_path": {}}}
        store = SimpleNamespace(step=lambda *args, **kwargs: None)
        await fast_search.first_semantic(SimpleNamespace(store=store), run, {}, None, None)
    asyncio.run(call())
    assert seen["run_x"] == (True, ("budget_exhausted", "deadline"))


class NoWorkFound(OpenAlex):
    """OpenAlex that answers the semantic request with no work at all; its keyword searches answer as usual."""

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org" and params.get("search.semantic"):
            self.semantic.append(params["search.semantic"])
            return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
        return super().__call__(request)


def test_a_first_page_that_answered_with_no_work_does_not_offer_the_same_request_again(tmp_path, monkeypatch):
    """Sending that request again would answer the same way, so this stop offers no resume: the way on is a new
    scope revision whose question finds records."""
    import test_search_query

    monkeypatch.setattr(test_search_query, "WORK", PLAN_WORK)
    openalex, adapter = NoWorkFound(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex, adapter)
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "paused" and run["pause_reason"] == "search_query_failed", run
    assert run["error"]["reason"] == "first_page_no_records" and run["error"]["retries_left"] == 0
    assert calls(adapter, "search_plan") == [] and calls(adapter, "search_query") == []
    assert len(openalex.semantic) == 1 and openalex.searches == []
    # Nothing else is searched in the plan's place: code compiles no query of its own, and a resume is refused.
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409


def test_a_record_with_more_keywords_than_a_step_input_holds_sends_the_first_of_them(tmp_path):
    import tempfile

    from deixis.domain import contracts
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        search(store, rid, run, search_plan.SEMANTIC_KEY, [record("W1")])
        svid = store.find_source_by_identifier("openalex", "W1")
        many = [f"SYNTHETIC keyword {index}" for index in range(25)]
        conn.execute("UPDATE source_versions SET index_keywords_json = ? WHERE id = ?", (json.dumps(many), svid))
        read = search_plan.keywords_of(store, svid)
        assert read == many[:search_plan.MAX_KEYWORDS]
        # What the step input's own contract holds, so a record with more keywords does not fail the call.
        limit = contracts.load_schema("StepInput")["properties"]["sources"]["items"]["properties"]
        assert limit["index_keywords"]["maxItems"] == search_plan.MAX_KEYWORDS


def test_a_named_work_with_no_openalex_id_is_named_and_chained_from_nothing():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        step = store.step(run["id"], "search_query", "code:search_query")
        store.start_step(step["id"])
        store.finish_step(step["id"], "succeeded", output={"status": "ready", "plan_seeds": [
            {"work_id": "wrk_seedpdf", "source_version_id": "srv_seedpdf", "openalex_id": None}]})
        rows = search_plan.plan_named(store, run)
        # The plan named it, so the chain has a plan; it carries no id, so there is nothing to ask a provider for.
        assert search_plan.plan_seeds(store, run) == []
        assert search_plan.unresolved_seeds(rows) == ["wrk_seedpdf"]

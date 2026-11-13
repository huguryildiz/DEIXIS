"""The Semantic Scholar completion arm: what a run observed about OpenAlex, and the one request that observation
allows. Synthetic throughout — no live app, provider or model."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.domain import canonical
from deixis.providers import semantic_scholar
from deixis.providers.common import SearchOutcome
from deixis.runtime.config import Settings
from deixis.storage import db
from deixis.workflow.answer import method_summary
from deixis.workflow.run import fast_path
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store
from deixis.workflow.search import completion, search as fast_search, small_batch
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from test_fast_path_clock import FakeClock

QUERIES = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"},
           {"provider_id": "openalex", "query_text": "SYNTHETIC beta"}]
QUESTION = "Comparison of depth-based routing and vector-based forwarding in underwater acoustic sensor networks"


@pytest.fixture
def lab(tmp_path):
    """A standard-depth discovery run of the conditional arm, with the fake clock the stage accounting needs."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store

    def run_at(arm="conditional", effort="standard", providers=("openalex", "semantic_scholar")):
        rid = store.create_research(QUESTION, "academic", effort, list(providers), "fake", "fake-model", "en")
        budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
        budget["fast_path"] = fast_path.freeze_budget(budget, effort, completion_arm=arm)
        run = store.create_run(rid, "discovery", budget, None)
        store.update_run(run["id"], status="running")
        return SimpleNamespace(rid=rid, run=store.run(run["id"]))

    yield SimpleNamespace(store=store, conn=conn, clock=clock, run_at=run_at,
                          settings=Settings(data_dir=tmp_path / "data"))
    conn.close()


def plan_for(lab, research, *, user_plan=None, queries=None, vocabulary=None):
    scope = dict(lab.store.scope(research.rid))
    if user_plan is not None:
        scope["user_plan"] = user_plan
    flow = ResearchFlow(SimpleNamespace(store=lab.store, clock=lab.clock, settings=lab.settings, local_embedder=None))
    plan = fast_search.build_plan(lab.store, research.run, scope, queries or QUERIES, vocabulary=vocabulary)
    fast_path.enter_stage(lab.store, research.run, "search")
    return flow, scope, plan


def scripted(flow, *, openalex_status="completed", openalex_records=2, s2=None, calls=None):
    """Every OpenAlex request answers the same way; the Semantic Scholar request answers `s2` (default: two records)."""
    async def send(run_id, connector, query, limit, page=None, **kwargs):
        if calls is not None:
            calls.append((query["provider_id"], query["query_text"], limit))
        if query["provider_id"] == "semantic_scholar":
            return s2 if s2 is not None else SearchOutcome(
                "completed", "rejected_not_executed", "SYNTHETIC s2", "keyless",
                records=[_record(f"S2_{i}") for i in range(2)], provider_total=9)
        if openalex_status != "completed":
            return SearchOutcome(openalex_status, "after_send_unknown", "SYNTHETIC failure", "keyless",
                                 error="SYNTHETIC", http_status=503)
        return SearchOutcome("completed" if openalex_records else "zero_results", "rejected_not_executed",
                             "SYNTHETIC request", "keyless",
                             records=[_record(f"W{i}") for i in range(openalex_records)], provider_total=900)
    flow._send_search = send


def _record(identity):
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(provider_record_id=identity, title=f"SYNTHETIC {identity}", authors=[], year=2026,
                          venue=None, publication_type="article", doi=None, landing_url=None, oa_pdf_url=None,
                          oa_pdf_version=None, version_label=None, abstract=f"SYNTHETIC abstract {identity}",
                          abstract_origin="provider_openalex_inverted_index", identifiers={"openalex": identity},
                          raw={"id": identity})


def arm_step(lab, research):
    return lab.store.existing_step(research.run["id"], completion.RELEVANCE_KEY)


# --- the frozen policy and the frozen plan ---------------------------------------------------------------------

def test_off_arm_freezes_nothing_and_keeps_the_earlier_policy_hash():
    budget = {"max_model_calls": 1}
    off = fast_path.freeze_budget(budget, "standard")
    explicit = fast_path.freeze_budget(budget, "standard", completion_arm="off")
    assert off == explicit and "completion" not in off
    # The absence of the key is the `off` arm, so a policy frozen before the rule reads as that arm and its hash
    # is the hash it always had.
    assert fast_path.completion({"fast_path": off}) is None
    body = {k: v for k, v in off.items() if k != "policy_hash"}
    assert off["policy_hash"] == canonical.sha256_hex(body)


@pytest.mark.parametrize("arm", ["conditional", "always"])
def test_an_arm_freezes_its_records_and_snippet_budget_per_depth(arm):
    for effort, records, snippets in (("quick", 50, 0), ("standard", 100, 1), ("detailed", 200, 2)):
        frozen = fast_path.completion({"fast_path": fast_path.freeze_budget({}, effort, completion_arm=arm,
                                                                           uniform_search=False)})
        assert frozen == {"rule": "s2_completion_v1", "arm": arm, "records": records, "snippet_requests": snippets}


def test_an_unknown_arm_is_refused():
    with pytest.raises(ValueError, match="unknown completion arm"):
        fast_path.freeze_budget({}, "standard", completion_arm="sometimes")


def test_the_plan_freezes_the_question_text_and_takes_its_records_off_the_keyword_cap(lab):
    research = lab.run_at()
    _, _, plan = plan_for(lab, research)
    assert plan["completion"] == {"rule": "s2_completion_v1", "arm": "conditional", "records": 100,
                                  "order": {"relevance": "after_keywords", "snippet": "at_concept_gate"},
                                  "snippet_requests": 1}
    # The question's own words, with the hyphens out: the endpoint documents that a hyphenated term finds nothing.
    assert plan["s2_relevance"]["query_text"] == QUESTION.replace("-", " ")
    assert plan["s2_relevance"]["limit"] == 100 and plan["s2_relevance"]["query_origin"] == "question"
    assert plan["keyword_cap"] == 1000 - 100
    # The arm is a planned request, so the PRISMA reader can say it was not sent; no watch follows it.
    sent = {q["arm"]: q for q in fast_search.sent_plan({"fast_path_search": plan, "compiled_queries": QUERIES})}
    assert sent["s2_relevance"]["key"] == completion.RELEVANCE_KEY and sent["s2_relevance"]["watchable"] is False


def test_a_run_of_the_off_arm_reserves_nothing_and_plans_no_request(lab):
    research = lab.run_at(arm="off")
    _, _, plan = plan_for(lab, research)
    assert "completion" not in plan and "s2_relevance" not in plan and plan["keyword_cap"] == 1000


def test_a_person_who_left_the_provider_out_reserves_nothing(lab):
    research = lab.run_at()
    _, _, plan = plan_for(lab, research, user_plan={"providers": ["openalex"]})
    assert plan["completion"]["skipped"] == "excluded_by_user" and plan["completion"]["records"] == 0
    assert plan["completion"]["snippet_requests"] == 0 and plan["s2_snippet"] == []
    assert plan["s2_relevance"] is None and plan["keyword_cap"] == 1000


# --- what the run observed -------------------------------------------------------------------------------------

def test_records_from_openalex_send_nothing_and_say_so(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    calls = []
    scripted(flow, calls=calls)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = arm_step(lab, research)
    assert step["status"] == "cancelled" and step["error_code"] == "openalex_answered"
    assert step["output"]["openalex"]["state"] == "records" and step["output"]["arm"] == "conditional"
    assert not [c for c in calls if c[0] == "semantic_scholar"]


def test_a_valid_zero_is_not_a_failure(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    scripted(flow, openalex_records=0)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = arm_step(lab, research)
    assert step["output"]["openalex"] == {"state": "valid_zero", "requests": 3, "records": 0,
                                          "statuses": {"zero_results": 3}, "failures": {}}
    assert step["status"] == "cancelled" and step["error_code"] == "openalex_answered"


def test_a_technical_failure_sends_the_question_to_the_other_source(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    calls = []
    scripted(flow, openalex_status="timeout", calls=calls)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = arm_step(lab, research)
    assert step["status"] == "succeeded" and step["output"]["result_count"] == 2
    observed = step["output"]["openalex"]
    assert observed["state"] == "technical_failure" and observed["failures"] == {"timeout": 3} and observed["records"] == 0
    # The one request that went out carried the question's own words, inside the arm's own reservation.
    assert [c for c in calls if c[0] == "semantic_scholar"] == [("semantic_scholar", QUESTION.replace("-", " "), 100)]
    row = lab.conn.execute("SELECT sr.provider, sr.status, sr.result_count FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
                           " WHERE s.operation_key = ?", (completion.RELEVANCE_KEY,)).fetchone()
    assert tuple(row) == ("semantic_scholar", "completed", 2)


def test_records_beside_a_failure_send_nothing_and_the_failure_is_still_recorded(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    calls = []

    async def send(run_id, connector, query, limit, page=None, **kwargs):
        calls.append(query["provider_id"])
        if query.get("endpoint") == "semantic":  # the question's own request answers; every keyword page times out
            return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless",
                                 records=[_record("W1")], provider_total=9)
        return SearchOutcome("timeout", "after_send_unknown", "SYNTHETIC failure", "keyless", http_status=504)
    flow._send_search = send
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = arm_step(lab, research)
    assert step["error_code"] == "openalex_answered" and step["output"]["openalex"]["state"] == "records"
    # Half of OpenAlex failed and the run says so, although that decided nothing.
    assert step["output"]["openalex"]["failures"] == {"timeout": 2}
    assert "semantic_scholar" not in calls


def test_a_run_that_sent_no_openalex_request_calls_it_neither_zero_nor_failure(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    observed = completion.openalex_outcome(lab.store, research.run["id"])
    assert observed == {"state": "not_sent", "requests": 0, "records": 0, "statuses": {}, "failures": {}}
    scripted(flow)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan | {"keywords": [], "semantic": dict(
        plan["semantic"], query_text=None)}, False))
    step = arm_step(lab, research)
    assert step["error_code"] == "openalex_answered" and step["output"]["openalex"]["state"] == "not_sent"


def test_the_person_who_left_the_provider_out_gets_no_request(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research, user_plan={"providers": ["openalex"]})
    calls = []
    scripted(flow, openalex_status="timeout", calls=calls)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = arm_step(lab, research)
    assert step["error_code"] == "excluded_by_user" and "semantic_scholar" not in [c[0] for c in calls]


def test_the_arms_own_failure_does_not_fail_the_search_stage(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    scripted(flow, openalex_status="timeout",
             s2=SearchOutcome("rate_limited", "after_send_unknown", "SYNTHETIC refusal", "keyless", http_status=429))
    failure = asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = arm_step(lab, research)
    # The step records the refusal; the stage's own failure is the one OpenAlex caused, never the arm's.
    assert step["status"] in ("failed", "outcome_unknown")
    assert failure is None or "semantic_scholar" not in json.dumps(failure)


def test_the_decision_is_read_back_instead_of_made_again(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    calls = []
    scripted(flow, openalex_status="timeout", calls=calls)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    before = len([c for c in calls if c[0] == "semantic_scholar"])
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    assert before == 1 and len([c for c in calls if c[0] == "semantic_scholar"]) == 1


def test_the_method_box_is_told_what_was_searched_in_openalexs_place(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    scripted(flow, openalex_status="rate_limited")
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    view = completion.view(lab.store, research.rid, 1)
    assert view == {"arm": "conditional", "state": "technical_failure", "sent": True, "records": 2,
                    "reason": None, "request_status": "completed", "failures": {"rate_limited": 3}}
    assert completion.view(lab.store, "res_absent", 1) is None


def test_the_answers_method_summary_carries_the_arm(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    scripted(flow, openalex_status="timeout")
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    search = method_summary._search(lab.store, research.rid, 1, "9999-01-01T00:00:00.000+00:00")
    assert search["completion"]["sent"] is True and search["completion"]["failures"] == {"timeout": 3}


# --- the provider's own text rule ------------------------------------------------------------------------------

@pytest.mark.parametrize("text,limit,expected", [
    # A hyphenated term finds nothing at this endpoint, so the hyphen becomes a space.
    ("depth-based routing", 300, "depth based routing"),
    ("  two   spaces  ", 300, "two spaces"),
    # The cut is at a word boundary: half a word would be another word.
    ("alpha beta gamma", 11, "alpha beta"),
    ("alpha beta gamma", 9, "alpha"),
    # A first word longer than the limit still goes, cut: an empty query would read as "nothing was asked".
    ("abcdefghij", 4, "abcd"),
    ("", 300, ""),
])
def test_the_query_text_is_cut_the_same_way_everywhere(text, limit, expected):
    assert semantic_scholar.query_text(text, limit) == expected


def test_the_default_cut_is_the_pilot_number():
    assert semantic_scholar.SEARCH_TEXT_MAX_CHARS == 300
    assert len(semantic_scholar.query_text("word " * 200)) <= 300


# --- the snippet request: the same gate as the focused query ---------------------------------------------------

MAIN = {"provider_id": "openalex", "query_text": "SYNTHETIC alpha", "origin": "model"}
FOCUSED = {"provider_id": "openalex", "query_text": '"comparison" AND ("dbr" OR "vbf")', "origin": "model",
           "role": "focused", "focused": {"term": "comparison", "gap": "SYNTHETIC sub-problem"}}
PLAN_VOCABULARY = {"terms": [
    {"block": "setting", "root": "dbr", "phrase": "depth-based routing", "in_query": "root", "dropped": None},
    {"block": "task", "root": "vbf", "phrase": "vector-based forwarding", "in_query": "root", "dropped": None},
]}

SNIPPETS = [{"corpus_id": "215416146", "title": "SYNTHETIC paper", "snippet_kind": "body", "section": "Results",
             "text": "SYNTHETIC passage comparing both protocols", "char_start": 10, "char_end": 52, "score": 0.5,
             "ref_mentions": [{"start": 3, "end": 9, "matched_corpus_id": "99"}], "sentences": [{"start": 0, "end": 42}]},
            {"corpus_id": "215416146", "title": "SYNTHETIC paper", "snippet_kind": "abstract", "section": None,
             "text": "SYNTHETIC abstract passage", "char_start": None, "char_end": None, "score": 0.4,
             "ref_mentions": [], "sentences": []},
            {"corpus_id": "777", "title": "SYNTHETIC other", "snippet_kind": "title", "section": None,
             "text": "SYNTHETIC title passage", "char_start": None, "char_end": None, "score": 0.3,
             "ref_mentions": [], "sentences": []}]


def _s2_record(identity, corpus_id):
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(provider_record_id=identity, title=f"SYNTHETIC {identity}", authors=[], year=2026,
                          venue=None, publication_type="article", doi=f"10.5555/{identity}", landing_url=None,
                          oa_pdf_url=None, oa_pdf_version=None, version_label=None,
                          abstract="SYNTHETIC abstract", abstract_origin="provider_semantic_scholar",
                          identifiers={"CorpusId": corpus_id, "DOI": f"10.5555/{identity}"}, raw={"paperId": identity})


def snippet_plan(lab, arm="conditional", effort="standard"):
    research = lab.run_at(arm=arm, effort=effort)
    flow, scope, plan = plan_for(lab, research, queries=[MAIN, FOCUSED], vocabulary=PLAN_VOCABULARY)
    return research, flow, scope, plan


def scripted_snippets(flow, *, snippets=SNIPPETS, records=("S1",), status="completed", calls=None, covered=False):
    async def send(run_id, connector, query, limit, page=None, **kwargs):
        if calls is not None:
            calls.append((query.get("endpoint"), query["query_text"], limit))
        if query.get("endpoint") == "snippet":
            if status != "completed":
                outcome = SearchOutcome(status, "after_send_unknown", "SYNTHETIC snippet failure", "keyless",
                                        http_status=503)
                outcome.snippets = snippets
                return outcome
            outcome = SearchOutcome("completed" if snippets else "zero_results", "rejected_not_executed",
                                    "SYNTHETIC snippet", "keyless",
                                    records=[_s2_record(r, "215416146") for r in records], provider_total=len(snippets))
            outcome.snippets = snippets
            return outcome
        # Every OpenAlex query answers with one record whose text carries the concept only when `covered`.
        text = "comparison of protocols" if covered else "SYNTHETIC unrelated"
        from deixis.providers.common import ProviderRecord
        return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless", records=[ProviderRecord(
            provider_record_id=f"W{len(calls or [])}", title=text, authors=[], year=2026, venue=None,
            publication_type="article", doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
            version_label=None, abstract=text, abstract_origin="provider_openalex_inverted_index",
            identifiers={"openalex": f"W{len(calls or [])}"}, raw={"id": "W"})], provider_total=1)
    flow._send_search = send


def snippet_rows(lab):
    return [dict(r) for r in lab.conn.execute("SELECT * FROM provider_snippets ORDER BY rowid")]


def test_the_plan_freezes_one_snippet_request_per_focused_concept(lab):
    _, _, _, plan = snippet_plan(lab)
    (spec,) = plan["s2_snippet"]
    # The concept and the main query's terms stand together, as plain words: this endpoint takes no syntax.
    assert spec["query_text"] == "comparison dbr vbf" and spec["endpoint"] == "snippet"
    assert spec["index"] == 1 and spec["focused"]["term"] == "comparison"
    # The gap sentence is shown to the person and never read by a rule, so it is not in the query text.
    assert "sub-problem" not in spec["query_text"]
    assert spec["limit"] == 25  # the endpoint's own page, under the arm's 100 records


def test_quick_freezes_one_snippet_request(lab):
    _, _, _, plan = snippet_plan(lab, effort="quick")
    assert plan["completion"]["snippet_requests"] == 1 and len(plan["s2_snippet"]) == 1


def test_an_unmet_gap_sends_the_snippet_request_and_keeps_every_passage(lab):
    research, flow, scope, plan = snippet_plan(lab)
    calls = []
    scripted_snippets(flow, calls=calls, covered=False)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert step["status"] == "succeeded"
    assert step["output"]["gate"] == {"covered": False, "query_index": 1, "held": False}
    # Three passages from two works; the work the lookup answered for is linked, the other is not.
    assert step["output"]["snippets"] == 3 and step["output"]["snippet_works"] == 1
    assert step["output"]["snippet_works_unlinked"] == 1
    rows = snippet_rows(lab)
    assert [r["corpus_id"] for r in rows] == ["215416146", "215416146", "777"]
    assert len({r["source_version_id"] for r in rows if r["source_version_id"]}) == 1
    assert rows[2]["source_version_id"] is None
    assert (rows[0]["snippet_kind"], rows[0]["section"]) == ("body", "Results")
    # The citation marks keep their spans and the work they point at, not only a count.
    assert json.loads(rows[0]["ref_mentions_json"]) == [{"start": 3, "end": 9, "matched_corpus_id": "99"}]
    assert json.loads(rows[0]["sentences_json"]) == [{"start": 0, "end": 42}]
    assert [c[0] for c in calls if c[0] == "snippet"] == ["snippet"]


def test_a_passage_is_never_stored_as_a_passage_of_the_work(lab):
    research, flow, scope, plan = snippet_plan(lab)
    scripted_snippets(flow)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    linked = [r["source_version_id"] for r in snippet_rows(lab) if r["source_version_id"]][0]
    # Finding a passage is not reading the full text: no `passages` row, so nothing here can become a cited anchor,
    # an answer passage or a reading depth above what the work's own stored text reaches.
    kinds = [r[0] for r in lab.conn.execute("SELECT kind FROM passages WHERE source_version_id = ?", (linked,))]
    assert "body" not in kinds and all(k in ("abstract",) for k in kinds)


def test_a_gap_the_main_query_already_covers_sends_nothing(lab):
    research, flow, scope, plan = snippet_plan(lab)
    calls = []
    scripted_snippets(flow, calls=calls, covered=True)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert (step["status"], step["error_code"]) == ("cancelled", "gap_already_met")
    assert step["output"]["gate"] == {"covered": True, "query_index": 1, "held": True}
    assert not [c for c in calls if c[0] == "snippet"] and not snippet_rows(lab)


def test_the_control_arm_sends_the_passage_query_whatever_the_gate_read(lab):
    """`always` is the measurement's control, so a gate that found the concept covered does not hold it back."""
    research, flow, scope, plan = snippet_plan(lab, arm="always")
    calls = []
    scripted_snippets(flow, calls=calls, covered=True)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert step["status"] == "succeeded"
    # The gate's own reading is still recorded; what changed is that this arm sends anyway.
    assert step["output"]["gate"] == {"covered": True, "query_index": 1, "held": False}
    assert [c[0] for c in calls if c[0] == "snippet"] == ["snippet"]


def test_the_control_arm_asks_the_question_itself_where_the_plan_named_no_concept(lab):
    research = lab.run_at(arm="always")
    flow, scope, plan = plan_for(lab, research, queries=[MAIN], vocabulary=PLAN_VOCABULARY)
    (spec,) = plan["s2_snippet"]
    # No concept to ask about, so the question's own main terms are the query and no gate decides it.
    assert spec["index"] is None and spec["focused"] is None and spec["query_text"] == "dbr vbf"
    calls = []
    scripted_snippets(flow, calls=calls)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert step["status"] == "succeeded" and step["output"]["gate"]["covered"] is None
    assert [c[0] for c in calls if c[0] == "snippet"] == ["snippet"]


def test_the_conditional_arm_asks_nothing_where_the_plan_named_no_concept(lab):
    research = lab.run_at(arm="conditional")
    _, _, plan = plan_for(lab, research, queries=[MAIN], vocabulary=PLAN_VOCABULARY)
    assert plan["s2_snippet"] == []


def test_a_resumed_run_cannot_read_the_reservation_twice(lab):
    """The records an earlier attempt of the run already read are counted before anything else is sent."""
    research, flow, scope, plan = snippet_plan(lab)
    scripted_snippets(flow, covered=False)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    spent = completion.spent(lab.store, research.run["id"], plan)
    assert spent == 1  # the snippet request's own record
    # A second process starts with nothing in memory: what is left of the reservation is read from the rows.
    assert completion.spent(lab.store, research.run["id"], {"s2_snippet": []}) >= 0


def test_a_later_run_does_not_change_an_earlier_answers_method_box(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    scripted(flow, openalex_status="rate_limited")
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    first = lab.store.run(research.run["id"])["created_at"]
    lab.store.update_run(research.run["id"], status="completed")
    lab.clock.advance(600)  # the second run starts after the first answer was written
    # A second discovery run of the same question, read after the first answer was written.
    later = lab.store.create_run(research.rid, "discovery", research.run["budget"], None)
    lab.store.update_run(later["id"], status="running")
    scope2 = dict(lab.store.scope(research.rid))
    plan2 = fast_search.build_plan(lab.store, lab.store.run(later["id"]), scope2, QUERIES)
    flow2 = ResearchFlow(SimpleNamespace(store=lab.store, clock=lab.clock, settings=lab.settings, local_embedder=None))
    fast_path.enter_stage(lab.store, lab.store.run(later["id"]), "search")
    scripted(flow2, openalex_status="completed")
    asyncio.run(fast_search.execute(flow2, lab.store.run(later["id"]), scope2, plan2, False))
    # Bounded by the first answer's own time, the box still says what that run did.
    bounded = completion.view(lab.store, research.rid, 1, first)
    assert bounded["state"] == "technical_failure" and bounded["sent"] is True
    # Unbounded, the latest run answers: the later one sent nothing because OpenAlex answered.
    assert completion.view(lab.store, research.rid, 1)["sent"] is False


def test_a_request_that_went_out_and_was_refused_is_not_reported_as_unsent(lab):
    research = lab.run_at()
    flow, scope, plan = plan_for(lab, research)
    refused = SearchOutcome("rate_limited", "rejected_not_executed", "SYNTHETIC s2", "keyless",
                            error="SYNTHETIC", http_status=429)
    scripted(flow, openalex_status="timeout", s2=refused)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    view = completion.view(lab.store, research.rid, 1)
    # The request reached the provider and was refused: that is a request that went out, with no record to show.
    assert view["sent"] is True and view["request_status"] == "rate_limited" and view["records"] == 0
    read = requests_of(lab.conn, research.run["id"])
    assert read["fallback"]["sent"] is True and read["fallback"]["request_status"] == "rate_limited"
    assert read["fallback"]["records"] == 0


def test_a_run_of_another_depth_is_not_the_reference_of_this_one(lab):
    off = lab.run_at(arm="off", effort="detailed")
    flow, scope, plan = plan_for(lab, off, queries=[MAIN, FOCUSED], vocabulary=PLAN_VOCABULARY)
    scripted_snippets(flow)
    asyncio.run(fast_search.execute(flow, off.run, scope, plan, False))
    lab.store.update_run(off.run["id"], status="completed")
    on, flow2, scope2, plan2 = snippet_plan(lab)
    scripted_snippets(flow2)
    asyncio.run(fast_search.execute(flow2, on.run, scope2, plan2, False))
    lab.store.update_run(on.run["id"], status="completed")
    pairs, unmatched = comparison(runs(lab.conn))
    # Same question, another depth and another record budget: the design compares arms, not depths.
    assert pairs == [] and [p["reason"] for p in unmatched] == ["no_completed_off_run"]


def test_a_failed_lookup_keeps_the_passages_and_brings_no_record(lab):
    research, flow, scope, plan = snippet_plan(lab)
    failure = asyncio.run(_run_with(lab, research, flow, scope, plan, status="timeout"))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert step["status"] in ("failed", "outcome_unknown")
    # What the provider found is kept; the works it could not look up are simply unlinked.
    rows = snippet_rows(lab)
    assert len(rows) == 3 and all(r["source_version_id"] is None for r in rows)
    # The arm's own failure is not the search stage's failure.
    assert failure is None or "snippet" not in json.dumps(failure)


async def _run_with(lab, research, flow, scope, plan, **kwargs):
    scripted_snippets(flow, **kwargs)
    return await fast_search.execute(flow, research.run, scope, plan, False)


def test_no_passage_at_all_is_a_valid_zero(lab):
    research, flow, scope, plan = snippet_plan(lab)
    asyncio.run(_run_with(lab, research, flow, scope, plan, snippets=[], records=()))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert step["status"] == "succeeded" and step["output"]["status"] == "zero_results"
    assert step["output"]["snippets"] == 0 and not snippet_rows(lab)


def test_both_requests_of_the_arm_share_one_reservation(lab):
    research, flow, scope, plan = snippet_plan(lab)
    # A reservation of one record: the snippet request takes it and the fallback has none left to read.
    plan = plan | {"completion": dict(plan["completion"], records=1)}
    scripted_snippets(flow, status="completed")

    async def send(run_id, connector, query, limit, page=None, **kwargs):
        if query.get("endpoint") == "snippet":
            outcome = SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC", "keyless",
                                    records=[_s2_record("S1", "215416146")], provider_total=3)
            outcome.snippets = SNIPPETS
            return outcome
        return SearchOutcome("timeout", "after_send_unknown", "SYNTHETIC failure", "keyless", http_status=504)
    flow._send_search = send
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    snippet = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    fallback = lab.store.existing_step(research.run["id"], completion.RELEVANCE_KEY)
    assert snippet["status"] == "succeeded"
    assert (fallback["status"], fallback["error_code"]) == ("cancelled", "budget")


def test_a_snippet_request_whose_gate_is_never_reached_is_still_recorded(lab):
    research, flow, scope, plan = snippet_plan(lab)
    calls = []
    # Every OpenAlex page fails, so the main query never ends complete and the focused gate is reached with no
    # records; the arm's steps must still say what happened to them.
    scripted_snippets(flow, calls=calls)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan | {"keywords": []}, False))
    step = lab.store.existing_step(research.run["id"], completion.snippet_key(0))
    assert step["status"] == "cancelled" and step["output"]["gate"]["covered"] is None
    assert not [c for c in calls if c[0] == "snippet"]


def test_the_plan_lists_the_snippet_request_without_its_gate_fields(lab):
    _, _, _, plan = snippet_plan(lab)
    sent = {q["arm"]: q for q in fast_search.sent_plan({"fast_path_search": plan, "compiled_queries": [MAIN, FOCUSED]})}
    assert sent["s2_snippet"]["key"] == completion.snippet_key(0)
    assert sent["s2_snippet"]["watchable"] is False
    assert "index" not in sent["s2_snippet"] and "focused" not in sent["s2_snippet"]


def test_a_removed_record_leaves_the_passage_standing(lab):
    research, flow, scope, plan = snippet_plan(lab)
    scripted_snippets(flow)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    linked = [r["source_version_id"] for r in snippet_rows(lab) if r["source_version_id"]][0]
    lab.store.update_run(research.run["id"], status="completed")
    # Taking the source out of the research changes nothing about the passage: the record is still there.
    lab.store.remove_sources(research.rid, [linked], None)
    assert [r["source_version_id"] for r in snippet_rows(lab) if r["source_version_id"]] == [linked, linked]
    # Deleting this research's record of it for good does: the snippet is still what the provider said it found, and
    # only the link it can no longer point at is emptied.
    lab.store.purge_sources(research.rid, [linked])
    rows = snippet_rows(lab)
    assert len(rows) == 3 and all(r["source_version_id"] is None for r in rows)


# --- the adapter's own two requests ---------------------------------------------------------------------------

SNIPPET_BODY = {"data": [
    {"score": 0.9, "snippet": {"text": "SYNTHETIC body passage", "snippetKind": "body", "section": "Results",
                               "snippetOffset": {"start": 10, "end": 32},
                               "annotations": {"refMentions": [{"start": 1, "end": 4, "matchedPaperCorpusId": 77}],
                                               "sentences": [{"start": 0, "end": 22}]}},
     "paper": {"corpusId": 11, "title": "SYNTHETIC one", "authors": ["A"]}},
    {"score": 0.8, "snippet": {"text": "SYNTHETIC abstract passage", "snippetKind": "abstract"},
     "paper": {"corpusId": 11, "title": "SYNTHETIC one", "authors": ["A"]}},
    {"score": 0.7, "snippet": {"text": "SYNTHETIC other passage", "snippetKind": "title"},
     "paper": {"corpusId": 22, "title": "SYNTHETIC two", "authors": []}},
    {"score": 0.6, "snippet": {"text": "", "snippetKind": "body"}, "paper": {"corpusId": 33}},
    {"score": 0.5, "snippet": {"text": "SYNTHETIC no paper"}, "paper": {}},
], "retrievalVersion": "SYNTHETIC-1"}

BATCH_BODY = [{"paperId": "p11", "title": "SYNTHETIC one", "externalIds": {"CorpusId": 11, "DOI": "10.5555/one"},
               "authors": [{"name": "A"}], "abstract": "SYNTHETIC abstract", "year": 2026},
              None,  # the endpoint answers null for an id it does not know
              {"paperId": "p99", "title": "SYNTHETIC stranger", "externalIds": {"CorpusId": 99}}]


def _snippet_run(snippet_response, batch_response=None):
    import httpx
    requests = []

    async def execute():
        def transport(request):
            requests.append(request)
            if request.url.path.endswith("/snippet/search"):
                return snippet_response
            return batch_response if batch_response is not None else httpx.Response(200, json=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await semantic_scholar.search_snippets(http, "SYNTHETIC query", 25)
    return asyncio.run(execute()), requests


def test_the_adapter_asks_for_the_works_its_passages_came_from(monkeypatch):
    import httpx
    from deixis.providers import pacing
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)
    outcome, requests = _snippet_run(httpx.Response(200, json=SNIPPET_BODY),
                                     httpx.Response(200, json=BATCH_BODY))
    assert outcome.status == "completed"
    # A passage with no text, and one no work can be attributed to, are no evidence of anything and are dropped.
    assert [s["corpus_id"] for s in outcome.snippets] == ["11", "11", "22"]
    assert outcome.snippets[0]["section"] == "Results" and outcome.snippets[0]["snippet_kind"] == "body"
    assert outcome.snippets[0]["ref_mentions"] == [{"start": 1, "end": 4, "matched_corpus_id": "77"}]
    assert outcome.snippets[1]["section"] is None
    # Two requests: the search, then one lookup of the distinct works, by corpus id.
    assert [r.method for r in requests] == ["GET", "POST"]
    assert json.loads(requests[1].content)["ids"] == ["CorpusId:11", "CorpusId:22"]
    # The reply is matched by the corpus id it names: the work nobody asked for is dropped, and so is the null.
    assert [r.identifiers["CorpusId"] for r in outcome.records] == ["11"]
    assert outcome.provider_total == 3


def test_no_passage_means_no_second_request(monkeypatch):
    import httpx
    from deixis.providers import pacing
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)
    outcome, requests = _snippet_run(httpx.Response(200, json={"data": []}))
    assert outcome.status == "zero_results" and outcome.snippets == [] and len(requests) == 1


def test_a_refused_lookup_keeps_the_passages(monkeypatch):
    import httpx
    from deixis.providers import pacing
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)
    outcome, requests = _snippet_run(httpx.Response(200, json=SNIPPET_BODY),
                                     httpx.Response(503, json={"error": "SYNTHETIC"}))
    assert outcome.status not in ("completed", "zero_results") and outcome.records == []
    assert [s["corpus_id"] for s in outcome.snippets] == ["11", "11", "22"]
    assert len(requests) == 2


@pytest.mark.parametrize("body", ["not an object", {"data": "not a list"}, {"data": [1, 2]}])
def test_an_unreadable_answer_is_a_parse_error(monkeypatch, body):
    import httpx
    from deixis.providers import pacing
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)
    outcome, _ = _snippet_run(httpx.Response(200, json=body))
    assert outcome.status == "parse_error" and outcome.records == []


def test_an_unreadable_lookup_answer_keeps_the_passages(monkeypatch):
    import httpx
    from deixis.providers import pacing
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)
    outcome, _ = _snippet_run(httpx.Response(200, json=SNIPPET_BODY), httpx.Response(200, json={"not": "a list"}))
    assert outcome.status == "parse_error" and len(outcome.snippets) == 3


def test_the_endpoint_declares_its_own_request_count():
    from deixis.providers import registry
    plain = registry.reading({"provider_id": "semantic_scholar"})
    snippet = registry.reading({"provider_id": "semantic_scholar", "endpoint": "snippet"})
    assert plain.requests_per_search == 1 and snippet.requests_per_search == 2
    assert snippet.paging == "single_page" and snippet.max_results == 25
    # The request allowance is counted for the endpoint the query names, not for the connector alone.
    from deixis.workflow.search import search_page
    budget = {"fast_path": {}}
    assert (search_page.page_allowance({"provider_id": "semantic_scholar", "endpoint": "snippet"}, "standard", budget)
            > search_page.page_allowance({"provider_id": "semantic_scholar", "endpoint": "bulk"}, "standard", budget) / 2)


def test_a_cursor_is_accepted_and_never_answered_with_another_page(monkeypatch):
    import httpx
    from deixis.providers import pacing
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=SNIPPET_BODY))) as http:
            return await semantic_scholar.search_snippets(http, "SYNTHETIC", 5, cursor="12")
    outcome = asyncio.run(execute())
    # One page is read and no next page is ever offered, as with the other single-page source.
    assert outcome.next_cursor is None and outcome.snippets


# --- the measurement reader -----------------------------------------------------------------------------------

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))
from completion_arms import aside, comparison, requests_of, runs, summary, top_works  # noqa: E402


def test_the_reader_tells_the_arms_apart_and_compares_them_to_openalex_alone(lab):
    # Two runs of the same question: one of the `off` arm, one conditional whose snippet request went out.
    off = lab.run_at(arm="off")
    flow, scope, plan = plan_for(lab, off, queries=[MAIN, FOCUSED], vocabulary=PLAN_VOCABULARY)
    scripted_snippets(flow)
    asyncio.run(fast_search.execute(flow, off.run, scope, plan, False))
    on, flow2, scope2, plan2 = snippet_plan(lab)
    scripted_snippets(flow2)
    asyncio.run(fast_search.execute(flow2, on.run, scope2, plan2, False))

    records = runs(lab.conn)
    by_arm = {r["arm"]: r for r in records}
    assert set(by_arm) == {"off", "conditional"}
    assert by_arm["off"]["snippet_steps"] == [] and by_arm["off"]["records_reserved"] == 0
    assert by_arm["conditional"]["snippet_sent"] == 1 and by_arm["conditional"]["snippet_triggered"] == 1
    assert by_arm["conditional"]["records_reserved"] == 100
    pairs, unmatched = comparison(records)
    report = summary(records, pairs, unmatched)
    assert report["arms"]["conditional"]["snippet_requests_sent"] == 1
    assert report["arms"]["conditional"]["passages_found"] == 3
    assert report["arms"]["conditional"]["passages_without_a_record"] == 1
    # The two older operations stay apart from the arm.
    assert report["aside"] == {"abstracts_added": 0, "lookups_asked": 0, "bulk_records": 0}


def test_a_question_with_no_openalex_alone_run_is_not_compared_to_another_arm(lab):
    on, flow, scope, plan = snippet_plan(lab)
    scripted_snippets(flow)
    asyncio.run(fast_search.execute(flow, on.run, scope, plan, False))
    # A run still going is not compared either: its list is part of one, and the loss would be the interruption.
    pairs, unmatched = comparison(runs(lab.conn))
    assert pairs == [] and [p["reason"] for p in unmatched] == ["run_running"]
    lab.store.update_run(on.run["id"], status="completed")
    pairs, unmatched = comparison(runs(lab.conn))
    # Completed, but with no OpenAlex-alone run of this question, so it is reported as not compared with the reason.
    assert pairs == []
    (pair,) = unmatched
    assert pair["arm"] == "conditional" and pair["reason"] == "no_completed_off_run"
    assert pair["reference_run_id"] is None and pair["references_available"] == 0


def test_the_reader_reads_the_recorded_reason_when_nothing_was_sent(lab):
    research, flow, scope, plan = snippet_plan(lab)
    scripted_snippets(flow, covered=True)
    asyncio.run(fast_search.execute(flow, research.run, scope, plan, False))
    read = requests_of(lab.conn, research.run["id"])
    assert read["snippet_sent"] == 0 and read["snippet_triggered"] == 0
    assert read["snippet_unsent_reasons"] == ["gap_already_met"]
    assert read["fallback"]["state"] == "records" and read["fallback"]["reason"] == "openalex_answered"
    assert aside(lab.conn, research.run["id"]) == {"abstract_lookup": {"asked": 0, "abstracts_added": 0},
                                                   "bulk_records": 0}
    assert top_works(lab.conn, research.run["id"]) == []  # nothing was ranked in this run

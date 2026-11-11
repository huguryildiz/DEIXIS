"""The main Boolean query beside its focused ones, and the depth's budget for them (P5).

Every question, term and record here is SYNTHETIC, OpenAlex is mocked and the model is the fake adapter. Passing
shows workflow behavior: how many query plans a depth allows, what a focused query asks for, what the contract
refuses, and when code sends such a query or records why it did not. It says nothing about whether a focused query
finds better papers; that is not measured here.
"""

import json
import tempfile
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.providers import query_compiler, query_rules
from deixis.providers.registry import resolve_query_syntax
from deixis.workflow.run import fast_path
from deixis.workflow.search import search_plan
from fakes import valid_response
from test_hit_rank import library, record, search

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text(encoding="utf-8"))["H_search_plan"]

# A main query of two blocks, as a plan writes it.
VOCABULARY = {"terms": [
    {"block": "setting", "root": "dbr", "phrase": "depth-based routing", "in_query": "phrase", "dropped": None},
    {"block": "task", "root": "vbf", "phrase": "vector-based forwarding", "in_query": "phrase", "dropped": None},
]}


def concept(term="underwater acoustic", gap="SYNTHETIC sub-problem the main query leaves out"):
    return {"term": term, "kind": "topic", "why": "SYNTHETIC why", "gap": gap,
            "evidence": {"record_id": "srv_SYNTHE0001plan", "field": "title", "span": [0, 1],
                         "relation": "SYNTHETIC relation"}}


def plan(**changes):
    return json.loads(valid_response(STEP_INPUT)) | changes


def issues(draft):
    return sorted({issue.code for issue in contracts.validate_model_output(STEP_INPUT, draft).issues})


# ---- the depth's budget -------------------------------------------------------------------------------------

@pytest.mark.parametrize("effort,plans,focused", [("quick", 1, 0), ("standard", 2, 1), ("detailed", 3, 2)])
def test_each_depth_allows_one_main_query_and_spends_the_rest_on_focused_ones(effort, plans, focused):
    budget = fast_path.freeze_budget({}, effort)
    assert budget["boolean_plans"] == plans
    assert search_plan.focused_allowance({"fast_path": budget}) == focused


def test_a_concept_beyond_the_depths_allowance_is_recorded_as_left_out_by_the_budget():
    answer = {"focused": [concept("first concept"), concept("second concept")]}
    queries = search_plan.focused_queries(answer, VOCABULARY, ["openalex"], 1)
    assert [q["focused"]["term"] for q in queries] == ["first concept"]
    recorded = search_plan.focused_record(answer, queries, 1)
    assert [(c["term"], c["left_out"]) for c in recorded["concepts"]] == \
        [("first concept", None), ("second concept", "budget")]
    assert recorded == recorded | {"rule": search_plan.FOCUSED_RULE, "allowance": 1}


# ---- the third block the compiler used to drop --------------------------------------------------------------

def test_a_third_mandatory_block_is_refused_instead_of_dropped_and_counted_as_written():
    """Before this package three single-term groups compiled on every provider: `render` wrote the first two and
    `written_counts` reported three, so the third concept was searched nowhere and still counted as sent."""
    three = [["alpha"], ["beta"], ["gamma", "delta"]]
    for provider in ("openalex", "semantic_scholar", "crossref", "arxiv", "serpapi"):
        assert query_compiler.fit_block_counts(provider, three) is None
        assert len(resolve_query_syntax(provider, None).written_counts(three)) == query_rules.RENDERED_BLOCKS
    # The two blocks a provider does write are unchanged.
    assert query_compiler.fit_block_counts("openalex", [["alpha"], ["beta"]]) == ("alpha AND beta", [1, 1])


# ---- what a focused query asks for --------------------------------------------------------------------------

def test_a_focused_query_asks_for_the_concept_beside_either_of_the_main_querys_terms():
    (query,) = search_plan.focused_queries({"focused": [concept()]}, VOCABULARY, ["openalex"], 1)
    assert query["query_text"] == \
        '"underwater acoustic" AND ("depth-based routing" OR "vector-based forwarding")'
    assert (query["role"], query["origin"], query["provider_id"]) == ("focused", "model", "openalex")
    assert query["focused"]["gap"] and query["dropped_terms"] == []


def test_a_plan_with_no_focused_concept_compiles_no_second_query():
    assert search_plan.focused_queries({"focused": []}, VOCABULARY, ["openalex"], 2) == []
    assert search_plan.focused_queries({}, VOCABULARY, ["openalex"], 2) == []


LONG_BLOCKS = {"terms": [{"block": "setting", "root": "s", "phrase": "s" * 150, "in_query": "phrase",
                          "dropped": None},
                         {"block": "task", "root": "t", "phrase": "t" * 150, "in_query": "phrase",
                          "dropped": None}]}


def test_terms_the_providers_limits_left_out_are_recorded_against_the_concept_that_asked_for_them():
    """The concept and one main term fit; the other main term does not, and the query says which."""
    answer = {"focused": [concept("c" * 120)]}
    queries = search_plan.focused_queries(answer, LONG_BLOCKS, ["openalex"], 1)
    (only,) = search_plan.focused_record(answer, queries, 1)["concepts"]
    assert only["left_out"] is None and only["dropped_terms"] == ["t" * 150]
    assert len(queries[0]["query_text"]) <= query_compiler.MAX_QUERY_CHARS


def test_a_concept_no_provider_can_fit_beside_a_main_term_is_recorded_as_sent_nowhere():
    answer = {"focused": [concept("c" * 290)]}
    queries = search_plan.focused_queries(answer, LONG_BLOCKS, ["openalex"], 1)
    (only,) = search_plan.focused_record(answer, queries, 1)["concepts"]
    assert queries == [] and only["left_out"] == "unfittable" and only["query_text"] is None


# ---- what the contract refuses ------------------------------------------------------------------------------

def test_a_focused_concepts_evidence_is_read_back_like_a_chosen_terms():
    good = plan()
    assert good["focused"], "the fake writes one focused concept for this fixture"
    moved = json.loads(json.dumps(good))
    moved["focused"][0]["evidence"]["span"] = [0, 4]
    assert "plan_term_not_at_span" in issues(moved)
    unknown = json.loads(json.dumps(good))
    unknown["focused"][0]["evidence"]["record_id"] = "srv_SYNTHEnotsent"
    assert "plan_record_unknown" in issues(unknown)
    assert issues(good) == []


def test_a_concept_the_main_blocks_already_hold_is_refused():
    draft = plan()
    draft["focused"][0]["term"] = draft["setting"][0]["term"]
    draft["focused"][0]["evidence"] = json.loads(json.dumps(draft["setting"][0]["evidence"]))
    assert "focused_term_in_main_query" in issues(draft)


def test_more_than_two_focused_concepts_are_refused_by_the_schema():
    draft = plan(focused=[concept(f"concept {i}") for i in range(3)])
    assert issues(draft) == ["schema_invalid"]


# ---- the recorded condition ---------------------------------------------------------------------------------

def test_a_concept_the_main_querys_own_records_carry_is_no_gap():
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        search(store, rid, run, "search:0", [record("W1"), record("W2")])
        search(store, rid, run, "search:0:page:1", [record("W3")])
        run = dict(run) | {"research_id": rid, "scope_revision": 1}
        # The mock's titles and abstracts hold the record's own identity, so that word is carried and any other is not.
        assert search_plan.pages_cover(store, run, "SYNTHETIC W2", [0]) is True
        assert search_plan.pages_cover(store, run, "SYNTHETIC W3", [0]) is True  # a later page counts too
        assert search_plan.pages_cover(store, run, "underwater acoustic", [0]) is False
        # A main query that found nothing covers nothing, so the focused query goes out.
        assert search_plan.pages_cover(store, run, "SYNTHETIC W1", []) is False
        assert search_plan.pages_cover(store, run, "SYNTHETIC W1", [7]) is False


# ---- a run end to end ---------------------------------------------------------------------------------------

def step_row(client, run_id, key):
    row = client.app.state.store.conn.execute(
        "SELECT status, error_code FROM run_steps WHERE run_id = ? AND operation_key = ?", (run_id, key)).fetchone()
    return (row[0], row[1]) if row else None


def test_a_run_compiles_the_focused_query_and_does_not_send_it_when_the_main_query_covers_it(tmp_path, monkeypatch):
    """The whole condition in one run: the plan names a concept, code compiles its query, and the main query's own
    records turn out to carry that concept, so the query is cancelled with the reason rather than sent."""
    import test_search_query
    from fakes import FakeAdapter
    from test_search_plan import PLAN_WORK
    from test_search_query import OpenAlex, client_for, start, step_output, wait

    monkeypatch.setattr(test_search_query, "WORK", PLAN_WORK)
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter)
    # The main query is the round's only other plan, so Deep's budget leaves room for two focused plans; the
    # model names one (see `test_a_second_plan_in_the_round_spends_a_plan_of_the_budget`).
    rid, run_id = start(client, effort="detailed")
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run

    stored = step_output(client, run_id, "search_query")
    recorded = stored["focused"]
    assert recorded["rule"] == search_plan.FOCUSED_RULE and recorded["allowance"] == 2
    (named,) = recorded["concepts"]
    assert named["gap"] and named["left_out"] is None and named["query_text"]
    # One plan, rendered once per provider as the main query is; the frozen keyword plan sends the OpenAlex one.
    focused = [(index, query) for index, query in enumerate(stored["queries"]) if query.get("role") == "focused"]
    assert {query["focused"]["term"] for _, query in focused} == {named["term"]}
    index, query = next((i, q) for i, q in focused if q["provider_id"] == "openalex")
    assert query["query_text"] == named["query_text"]
    # The mock answers every query with the same record, so the main query's results carry the concept: no second
    # query goes out, and the step says why.
    assert step_row(client, run_id, f"search:{index}") == ("cancelled", "gap_already_met")


# ---- what the first round already spends -------------------------------------------------------------------

def test_a_second_plan_in_the_round_spends_a_plan_of_the_budget():
    """The design counts distinct Boolean query plans, and the round holds one of its own: the model's query, or a
    person's saved plan in its place, rendered once per provider. A focused query and an author lookup are not it."""
    model = {"origin": "model", "provider_id": "openalex"}
    author = {"origin": "author", "provider_id": "openalex"}
    focused = {"origin": "model", "provider_id": "openalex", "role": "focused"}
    assert search_plan.plans_in_round([model, dict(model, provider_id="crossref")]) == 1
    assert search_plan.plans_in_round([model, author]) == 1  # a named work's lookup is no concept plan
    assert search_plan.plans_in_round([model, focused]) == 1  # the focused query is what the budget is spent on
    assert search_plan.plans_in_round([{"origin": "user", "provider_id": "openalex"}]) == 1
    standard = fast_path.freeze_budget({}, "standard")
    deep = fast_path.freeze_budget({}, "detailed")
    # Standard allows two plans: the main query spends one and a focused query may spend the other.
    assert search_plan.focused_allowance({"fast_path": standard}, [model]) == 1
    assert search_plan.focused_allowance({"fast_path": deep}, [model]) == 2
    # A research searched before the code query was removed still has that plan counted in its own round.
    assert search_plan.focused_allowance({"fast_path": standard}, [model, {"origin": "code", "provider_id": "openalex"}]) == 0


def test_only_the_main_querys_own_pages_answer_the_coverage_question():
    specs = [{"index": 0, "query": {"origin": "model"}}, {"index": 1, "query": {"origin": "code"}},
             {"index": 2, "query": {"origin": "author"}},
             {"index": 3, "query": {"origin": "model", "role": "focused"}}]
    assert search_plan.main_plan_indexes(specs) == [0]
    assert search_plan.main_plan_indexes([{"index": 5, "query": {"origin": "user"}}]) == [5]


def test_a_concept_is_carried_only_when_it_stands_as_its_own_words():
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        search(store, rid, run, "search:0", [record("routing")])
        run = dict(run) | {"research_id": rid, "scope_revision": 1}
        assert search_plan.pages_cover(store, run, "routing", [0]) is True
        # "out" stands inside "routing" and nowhere on its own, so the gap is not closed by it.
        assert search_plan.pages_cover(store, run, "out", [0]) is False


def test_two_focused_entries_naming_one_concept_are_refused():
    draft = plan(focused=[concept("one concept"), concept("one concept")])
    assert "duplicate_focused_term" in issues(draft)

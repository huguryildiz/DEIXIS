"""Reverse citation search, R5: the claim's field and the authors it names reach the search.

Sentences, fields, surnames and counts are SYNTHETIC or copied as plain text, OpenAlex is mocked and the model is the
fake adapter, so these tests show which terms code reads, which queries it compiles and what it sends and records.
They say nothing about whether the field or an author filter finds the works a claim cites; that is measured live.
"""

import asyncio

import httpx
import pytest

from deixis.domain import statement
from deixis.domain.vocabulary import extract, with_field
from deixis.providers import facade, openalex
from deixis.workflow import search_query, vocabulary as vocabulary_rules
from fakes import FakeAdapter
from test_search_query import OpenAlex, calls, client_for, protocol_body, start, step_output, wait

SENTENCE = ("Chandra et al. prove that serving the youngest qubit and dropping the oldest maximizes average fidelity "
            "at one destination.")


# ------------------------------------------------------------------------------------------ what code reads

@pytest.mark.parametrize("sentence, groups", [
    ("Chandra et al. prove that X holds.", [["Chandra"]]),
    ("Erçetin and Gedik define a Fidelity-Age.", [["Erçetin", "Gedik"]]),
    ("Mitrolaris et al. and Banerjee et al. schedule freshness.", [["Mitrolaris"], ["Banerjee"]]),
    ("Fittipaldi et al. schedule backlogs, and Promponas et al. prove stability.", [["Fittipaldi"], ["Promponas"]]),
    ("Order matters even without decay when two requests share one link.", []),
    ("Quantum and classical links differ.", []),  # "classical" is not capitalised
])
def test_the_works_a_sentence_names_are_read_one_group_per_work(sentence, groups):
    assert statement.author_groups(sentence) == groups


def test_at_most_three_author_groups_are_kept():
    sentence = "A1 et al., B1 et al., C1 et al. and D1 et al. agree."
    assert len(statement.author_groups(sentence)) == statement.MAX_AUTHOR_GROUPS


def test_an_accented_surname_does_not_make_a_short_statement_another_language():
    sentence = "Erçetin and Gedik define Fidelity-Age resets."
    assert extract(sentence) is None  # as any question: accents and few function words read as not English
    # "define" and "resets" are claim verbs; a pair keeps its words in the code query (two capitalised terms read so too)
    assert extract(sentence, statement=True).blocks["task"] == ["erçetin", "gedik", "fidelity-age"]


def phrases_of(extraction):
    return [p for block in extraction.blocks.values() for p in block] + extraction.claim_words + extraction.exclusion_words


def test_a_statement_question_drops_its_et_al_mentions_claim_verbs_and_bare_numbers():
    every = phrases_of(extract("Chandra et al. schedule competing flows and lower the delay from 6 to 4 slots.",
                               statement=True))
    assert "competing flows" in every and "slots" in every
    assert not any(word in p.split() for p in every for word in ("chandra", "al", "schedule", "lower", "6", "4"))


def test_two_capitalised_terms_read_as_authors_keep_their_words_in_the_code_query():
    sentence = "Age and Fidelity determine queue behavior."
    assert statement.author_groups(sentence) == [["Age", "Fidelity"]]  # one narrow author query, nothing more
    assert {"age", "fidelity"} <= set(phrases_of(extract(sentence, statement=True)))


def test_a_question_that_is_not_a_statement_is_read_as_before():
    sentence = "Ercetin and Gedik schedule competing flows."
    assert extract(sentence) == extract(sentence, statement=False)
    assert any("schedule" in p.split() for block in extract(sentence).blocks.values() for p in block)


def test_the_field_leads_the_setting_block_once_with_its_own_origin():
    phrases = with_field(extract("Two requests share one link in quantum networks.", statement=True), " Quantum  Networks")
    assert phrases.blocks["setting"][0] == "quantum networks"
    assert sum(p == "quantum networks" for block in phrases.blocks.values() for p in block) == 1
    assert phrases.origins["quantum networks"] == "field"


@pytest.mark.parametrize("typed", ['"quantum"', "quantum OR optics", "a:b", "x" * 81, "one two three four five"])
def test_a_field_with_query_syntax_or_too_long_is_refused(typed):
    with pytest.raises(statement.FieldRefused):
        statement.check_field(typed)


def test_a_blank_field_is_none_and_spaces_are_collapsed():
    assert statement.check_field("   ") is None and statement.check_field(None) is None
    assert statement.check_field(" quantum   networks ") == "quantum networks"


def test_the_author_filter_asks_for_every_surname_and_an_accented_one_unaccented_too():
    assert openalex.author_filter(["Erçetin", "Gedik"]) == (
        "raw_author_name.search:Erçetin|Ercetin,raw_author_name.search:Gedik")


def test_a_stored_vocabulary_is_rebuilt_with_the_field_and_asks_only_the_new_counts():
    asked = []

    async def count(query):
        asked.append(query)
        return 40

    extraction = extract("Two request classes share a qubit queue.", statement=True)
    built = asyncio.run(vocabulary_rules.build_vocabulary(extraction, count))
    first = len(asked)
    known = {probe["query"]: probe["count"] for probe in built["probes"]}
    rebuilt = asyncio.run(vocabulary_rules.build_vocabulary(
        with_field(vocabulary_rules.extraction_of(built), "synthetic field"), count, known=known))
    assert [t["phrase"] for t in rebuilt["terms"]][0] == "synthetic field"
    assert {t["phrase"]: t["origin"] for t in rebuilt["terms"]}["synthetic field"] == "field"
    assert all(query not in known for query in asked[first:])  # nothing counted twice


# --------------------------------------------------------------------------------- what code compiles and sends

def model_vocabulary(author):
    return {"search_query": {"origin": None}, "terms": [], "statement": {"author_query": author},
            "code_query": {"searched": False, "queries": []}}


def test_author_queries_go_only_to_a_provider_that_takes_the_filter(monkeypatch):
    monkeypatch.setattr(search_query.query_compiler, "compile_block_queries", lambda v, p, limit: [
        {"provider_id": provider, "query_text": "x"} for provider in p])
    vocabulary = model_vocabulary({"groups": [["Chandra"], ["Erçetin", "Gedik"]], "search": "quantum"})
    queries = search_query.compile_queries(vocabulary, ["openalex", "arxiv"], 20)
    authored = [q for q in queries if q["origin"] == "author"]
    assert [(q["provider_id"], q["query_text"], q["works_filter"]) for q in authored] == [
        ("openalex", "quantum", "raw_author_name.search:Chandra"),
        ("openalex", "quantum", "raw_author_name.search:Erçetin|Ercetin,raw_author_name.search:Gedik")]
    assert [q["origin"] for q in queries] == ["model", "author", "author", "model"]  # after OpenAlex's own query
    assert search_query.author_queries(vocabulary, "openalex", ["arxiv"]) == []  # OpenAlex not planned
    no_field = model_vocabulary({"groups": [["Chandra"]], "search": None})
    assert search_query.author_queries(no_field, "openalex", ["openalex"]) == []
    unrooted = model_vocabulary({"groups": [["Chandra"]], "search": "synthetic field"})  # its words were not counted
    assert search_query.author_queries(unrooted, "openalex", ["openalex"])[0]["query_text"] == "synthetic field"


def test_the_works_the_request_limit_leaves_without_an_author_query_are_recorded(monkeypatch):
    monkeypatch.setattr(search_query.query_compiler, "compile_block_queries", lambda v, p, limit: [
        {"provider_id": provider, "query_text": "x"} for provider in p])
    vocabulary = model_vocabulary({"groups": [["A1"], ["B1"], ["C1"]], "search": "quantum", "providers": ["openalex"]})
    vocabulary["code_query"] = {"searched": True, "queries": [{"provider_id": "openalex", "query_text": "y"}]}
    queries = search_query.compile_queries(vocabulary, ["openalex"], 3)  # quick: three requests
    assert [q["origin"] for q in queries] == ["model", "code", "author"]
    recorded = search_query.with_compiled(vocabulary, queries)["statement"]["author_query"]
    assert recorded["compiled"] == [["A1"]] and recorded["query_limit"] == [["B1"], ["C1"]]


@pytest.mark.parametrize("field, code", [("health and education", "query_syntax_in_term"),
                                         ("quantum|optics", "query_syntax_in_term"),
                                         ("one two three four five", "query_term_too_long")])
def test_the_models_field_is_held_to_the_typed_field_rule(field, code):
    from deixis.domain import contracts
    from test_search_query import STEP_INPUT
    from fakes import valid_response
    import json
    draft = json.loads(valid_response(STEP_INPUT)) | {"field": field}
    assert code in contracts.validate_model_output(STEP_INPUT, draft).codes()


def test_the_model_can_write_back_any_field_a_person_may_type():
    from deixis.domain import contracts
    from test_search_query import STEP_INPUT
    from fakes import valid_response
    import json
    typed = statement.check_field("underwater wireless quantum communication")  # four words: the longest accepted
    draft = json.loads(valid_response(STEP_INPUT)) | {"field": typed}
    assert contracts.validate_model_output(STEP_INPUT, draft).ok


def test_a_reused_answer_written_before_r5_keeps_its_own_schema_version():
    from deixis.workflow import protocol
    record = {"status": "failed", "attempts": [], "answer": {"schema_version": "deixis.search_query.v1"}}
    scope = {"model_connection": "fake", "requested_model": "m", "reasoning_effort": None,
             "literature_model": None, "literature_connection": None, "literature_reasoning_effort": None}
    body = protocol._search_query(scope, {"search_query": record}, [])
    assert body["prompt"]["schema_version"] == "deixis.search_query.v1"


def test_the_filter_reaches_openalex_with_the_query_text():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    async def send():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await facade.dispatch_search("openalex", http, "quantum", 25, None, None, cursor="*",
                                                works_filter="raw_author_name.search:Chandra")
    asyncio.run(send())
    assert seen[0]["filter"] == "raw_author_name.search:Chandra"
    assert seen[0]["search.title_and_abstract"] == "quantum"


class FilteredOpenAlex(OpenAlex):
    """The mocked OpenAlex of the query tests, also keeping each search's filter."""

    def __init__(self, counts=None):
        super().__init__(counts)
        self.filters = []

    def __call__(self, request):
        if request.url.params.get("select") != "id":
            self.filters.append((request.url.params.get("search.title_and_abstract"), request.url.params.get("filter")))
        return super().__call__(request)


def statement_run(tmp_path, monkeypatch, question_text=SENTENCE, **body):
    openalex_mock, adapter = FilteredOpenAlex(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex_mock, adapter)
    rid, run_id = start(client, question=question_text, intent="statement", **body)
    wait(client, rid, run_id)
    return client, rid, run_id, openalex_mock, adapter


def field_term(vocabulary):
    return next(t for t in vocabulary["code_query"]["vocabulary"]["terms"] if t["origin"] == "field")


def test_a_typed_field_reaches_the_query_step_the_code_query_and_the_author_query(tmp_path, monkeypatch):
    client, rid, run_id, openalex_mock, adapter = statement_run(tmp_path, monkeypatch, field="synthetic field")
    (sent,) = calls(adapter)
    assert any("synthetic field" in line for line in sent["user_steering"])
    stored = step_output(client, run_id, "search_query")
    vocabulary = stored["vocabulary"]
    code_terms = vocabulary["code_query"]["vocabulary"]["terms"]
    assert code_terms[0]["phrase"] == "synthetic field" and code_terms[0]["block"] == "setting"
    assert not any("prove" in t["phrase"].split() or "chandra" in t["phrase"] for t in code_terms)
    assert vocabulary["statement"]["field"] == {"text": "synthetic field", "origin": "person"}
    author = vocabulary["statement"]["author_query"]
    assert author["groups"] == [["Chandra"]] and author["providers"] == ["openalex"]
    assert "openalex" not in author["no_author_filter"]
    (query,) = [q for q in stored["queries"] if q["origin"] == "author"]
    assert (query["works_filter"], query["query_text"]) == ("raw_author_name.search:Chandra", field_term(vocabulary)["root"])
    assert (query["query_text"], "raw_author_name.search:Chandra") in openalex_mock.filters
    body = protocol_body(client, rid)
    assert body["search_query"]["statement"]["field"]["origin"] == "person"
    assert client.app.state.store.scope(rid)["statement_field"] == "synthetic field"


def test_without_a_typed_field_the_query_models_field_is_used_and_recorded(tmp_path, monkeypatch):
    client, rid, run_id, openalex_mock, adapter = statement_run(tmp_path, monkeypatch)
    assert not any("field:" in line for line in calls(adapter)[0]["user_steering"])
    vocabulary = step_output(client, run_id, "search_query")["vocabulary"]
    assert vocabulary["statement"]["field"] == {"text": "synthetic field", "origin": "model"}  # the fake's answer
    assert field_term(vocabulary)["phrase"] == "synthetic field"
    # The rebuilt code vocabulary kept the labelling the first build stored.
    assert "labelling" in vocabulary["code_query"]["vocabulary"]
    assert any(f == "raw_author_name.search:Chandra" for _, f in openalex_mock.filters)


def test_where_no_model_writes_the_query_the_typed_field_and_the_author_query_still_apply(tmp_path, monkeypatch):
    openalex_mock, adapter = FilteredOpenAlex(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex_mock, adapter, setting="code")
    rid, run_id = start(client, question=SENTENCE, intent="statement", field="synthetic field")
    wait(client, rid, run_id)
    assert calls(adapter) == []
    body = protocol_body(client, rid)
    assert any(q.get("origin") == "author" for q in body["compiled_queries"])
    assert any(f == "raw_author_name.search:Chandra" for _, f in openalex_mock.filters)


def test_a_worker_lost_after_the_field_was_counted_reads_the_counts_back(tmp_path, monkeypatch):
    """The step is left open with its stored output, as a worker that died after the field's counts would leave it;
    the resumed run asks OpenAlex for no count again and compiles the same queries."""
    client, rid, run_id, openalex_mock, adapter = statement_run(tmp_path, monkeypatch)
    store = client.app.state.store
    before = step_output(client, run_id, "search_query")
    assert before["statement_context"]["attempt"] == 1
    with store.conn:
        store.conn.execute("UPDATE run_steps SET status = 'pending', finished_at = NULL WHERE run_id = ? AND"
                           " operation_key = 'search_query'", (run_id,))
        store.conn.execute("UPDATE runs SET status = 'paused', pause_reason = 'backend_restarted' WHERE id = ?", (run_id,))
    counted, sent = len(openalex_mock.counts), len(calls(adapter))
    assert client.post(f"/api/runs/{run_id}/resume").status_code in (200, 202)
    wait(client, rid, run_id)
    after = step_output(client, run_id, "search_query")
    assert after["status"] == "ready" and after["queries"] == before["queries"]
    assert openalex_mock.counts[counted:] == [] and len(calls(adapter)) == sent


def test_two_author_queries_with_one_text_stay_two_groups_in_the_search_record(tmp_path, monkeypatch):
    from deixis.workflow import prisma_s
    client, rid, run_id, openalex_mock, adapter = statement_run(
        tmp_path, monkeypatch, question_text="Chandra et al. and Banerjee et al. prove that two queues stay stable.",
        field="synthetic field", effort="standard")  # quick's three requests leave room for one author query
    groups = [g for g in prisma_s._groups(client.app.state.store, rid, 1) if g["origin"] == "author"]
    assert sorted(g["request"]["filter"] for g in groups) == ["raw_author_name.search:Banerjee",
                                                              "raw_author_name.search:Chandra"]
    assert len({g["query_text"] for g in groups}) == 1


def test_a_research_that_is_not_a_statement_gets_no_field_and_no_author_query(tmp_path, monkeypatch):
    openalex_mock, adapter = FilteredOpenAlex(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex_mock, adapter)
    rid, run_id = start(client, question=SENTENCE)
    wait(client, rid, run_id)
    stored = step_output(client, run_id, "search_query")
    assert "statement" not in stored["vocabulary"]
    assert not any(q.get("origin") == "author" for q in stored["queries"])
    assert not any(f and "raw_author_name" in f for _, f in openalex_mock.filters)


@pytest.mark.parametrize("body, status", [
    ({"field": "synthetic field"}, 422),  # a field without a sentence to check
    ({"field": '"synthetic"', "intent": "statement"}, 422),
    ({"field": "synthetic OR field", "intent": "statement"}, 422),
])
def test_a_field_is_refused_outside_a_statement_research_or_with_query_syntax(tmp_path, monkeypatch, body, status):
    client = client_for(tmp_path, monkeypatch, FilteredOpenAlex(), FakeAdapter())
    response = client.post("/api/researches", json={"question": SENTENCE, "model_connection": "fake",
                                                    "requested_model": "fake-model", "effort": "quick", **body})
    assert response.status_code == status, response.text

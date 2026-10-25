"""Reverse citation search, R5: the claim's field and the authors it names reach the search.

Sentences, fields, surnames and counts are SYNTHETIC or copied as plain text, OpenAlex is mocked and the model is the
fake adapter, so these tests show which terms code reads, which queries it compiles and what it sends and records.
They say nothing about whether the field or an author filter finds the works a claim cites; that is measured live.
"""

import asyncio
import httpx
import pytest
from deixis.domain import statement
from deixis.providers import facade, openalex
from deixis.workflow.search import search_query
from test_search_query import OpenAlex


SENTENCE = ("Chandra et al. prove that serving the youngest qubit and dropping the oldest maximizes average fidelity "
            "at one destination.")


@pytest.mark.parametrize("sentence, groups", [("Mitrolaris et al. and Banerjee et al. schedule freshness.", [["Mitrolaris"], ["Banerjee"]])])
def test_the_works_a_sentence_names_are_read_one_group_per_work(sentence, groups):
    assert statement.author_groups(sentence) == groups


@pytest.mark.parametrize("typed", ["quantum OR optics"])
def test_a_field_with_query_syntax_or_too_long_is_refused(typed):
    with pytest.raises(statement.FieldRefused):
        statement.check_field(typed)


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



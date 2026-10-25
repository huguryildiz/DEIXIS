"""Question words and their blocks: extraction, compilation into provider queries, and the model's labelling vote.

Questions are SYNTHETIC; counts and models are mocked. Passing shows the rules, not that a query finds the right works.
"""

import asyncio
import httpx
import pytest
from deixis.domain import vocabulary
from deixis.providers import openalex, query_compiler, query_rules
from deixis.providers.registry import CONNECTORS
from deixis.workflow.search.vocabulary import build_vocabulary
import json
from fastapi.testclient import TestClient
from deixis.domain.vocabulary import extract
from deixis.workflow.search.vocabulary import LABEL_RUNS
from fakes import FakeAdapter, envelope, valid_response
from test_vocabulary_flow import CountingOpenAlex, KEY_TERMS, app_for, start, store_at, wait


# ---- from tests__discovery__test_vocabulary.py ------------------------------------------------------------

NETWORKS = "What is the throughput of relay selection in wireless sensor networks?"


PACKET = "What is the effect of packet size on energy consumption in wireless sensor networks?"


TURKISH = "Kuantum ağlarında dolanıklık dağıtımı için hangi eniyileme modelleri önerilmiştir?"


def test_a_phrase_of_x_in_z_splits_into_a_task_and_a_setting_block():
    extraction = vocabulary.extract(NETWORKS)
    assert extraction.language == "en" and extraction.block_assignment == "rule"
    assert extraction.blocks["task"] == ["throughput", "relay selection"]
    assert extraction.blocks["setting"] == ["wireless sensor networks"]
    assert extraction.claim_words == [] and extraction.exclusion_words == []


def test_a_question_that_is_not_english_needs_the_users_key_terms():
    assert vocabulary.detect_language(TURKISH, None) == "other"
    assert vocabulary.detect_language(TURKISH, "en") == "en"  # an explicit hint decides
    assert vocabulary.detect_language(NETWORKS, "tr") == "other"
    assert vocabulary.detect_language("量子ネットワークのルーティング?", None) == "other"
    assert vocabulary.extract(TURKISH) is None


@pytest.mark.parametrize("key_terms", ["alpha; title:routing"])
def test_key_terms_with_query_syntax_are_refused(key_terms):
    with pytest.raises(ValueError, match="query syntax"):
        vocabulary.parse_key_terms(key_terms)
    with pytest.raises(ValueError, match="query syntax"):
        vocabulary.extract("Une question", "fr", key_terms)


def phrases(question):
    return [(p.text, p.position) for p in vocabulary._phrases(question)]


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def one_count(handler, **kwargs):
    async with client_for(handler) as client:
        return await openalex.count_works(client, kwargs.pop("query", "packets"), **kwargs)


@pytest.mark.parametrize("handler", [
    lambda request: httpx.Response(429, headers={"retry-after": "600"}),
])
def test_a_failed_or_unreadable_count_is_unknown_and_does_not_raise(handler):
    assert asyncio.run(one_count(handler, api_key=None, mailto=None)) is None


def test_the_count_request_description_carries_no_key(monkeypatch):
    recorded = {}

    async def fake_send(client, url, params, headers, description, access_mode, rate_headers=(), secrets=(), **kw):
        recorded.update(description=description, secrets=secrets, headers=headers, params=params)
        return None, None

    monkeypatch.setattr(openalex, "send", fake_send)
    assert asyncio.run(one_count(lambda request: httpx.Response(200, json={}), api_key="SECRET-KEY", mailto=None)) is None
    assert "SECRET-KEY" not in recorded["description"] and recorded["secrets"] == ("SECRET-KEY",)
    assert "SECRET-KEY" not in str(recorded["params"])
    assert recorded["headers"]["Authorization"] == "Bearer SECRET-KEY"


def counter(counts=None, default=0):
    """A fake count function: it records the queries in call order and answers each from a fixed table."""
    counts, asked = counts or {}, []

    async def count(query: str) -> int | None:
        asked.append(query)
        return counts.get(query, default)

    return asked, count


def built_for(question, counts=None, default=0, key_terms=None, language_hint=None):
    asked, count = counter(counts, default)
    extraction = vocabulary.extract(question, language_hint, key_terms)
    return asked, asyncio.run(build_vocabulary(extraction, count))


def test_the_same_extraction_and_the_same_counts_give_the_same_output_twice():
    first, second = built_for(PACKET, default=77)[1], built_for(PACKET, default=77)[1]
    assert first == second


def test_each_provider_gets_one_query_in_its_own_syntax_and_all_pass_the_rules():
    _, built = built_for(PACKET, default=10)
    providers = [p for p in query_rules.NAMES if CONNECTORS[p].searchable]
    queries = query_compiler.compile_block_queries(built, providers, 100)
    # Scopus (D91), CORE and SerpApi (D93) are searched by a legacy research only; an sw vocabulary compiles them no
    # query.
    assert [q["provider_id"] for q in queries] == [p for p in providers if p not in ("scopus", "core", "serpapi")]
    for query in queries:
        assert query_rules.query_issues(query["provider_id"], query["query_text"], query.get("endpoint")) == [], query
        assert len(query["query_text"]) <= query_compiler.MAX_QUERY_CHARS
        assert set(query) >= {"provider_id", "query_text", "rationale", "dropped_terms"}
    by_provider = {q["provider_id"]: q["query_text"] for q in queries}
    assert by_provider["pubmed"] == "(energy[Title/Abstract] OR wireless[Title/Abstract]) AND packet[Title/Abstract]"
    assert by_provider["arxiv"] == "(abs:energy OR abs:wireless) AND abs:packet"
    # Semantic Scholar is read through its bulk endpoint, whose syntax holds the blocks whole (D93).
    assert by_provider["semantic_scholar"] == "(energy | wireless) + packet"


# ---- from tests__discovery__test_vocabulary_labels.py ------------------------------------------------------------

# The code rule reads the word in front of a phrase: "with" marks a method position, so "distributed ledgers" becomes
# a claim word and the setting drops out of the query. That is the error SW17 exists to correct.
SUPPLY = "What is the effect of shipment batching on delivery delay in supply chains with distributed ledgers?"


def test_the_user_s_key_terms_are_labelled_by_nobody_but_the_user():
    extraction = extract("Hangi ölçekleme modelleri önerilmiştir?", key_terms=KEY_TERMS)
    assert extraction.block_assignment == "user"


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
    assert any("distributed" in query for query in openalex.searches if query is not None), openalex.searches
    record = next(p for p in vocabulary["labelling"]["phrases"] if p["phrase"] == "distributed ledgers")
    assert record == {"phrase": "distributed ledgers", "rule_block": "claim", "block": "setting", "origin": "model",
                      "runs": ["claim", "setting", "setting"]}

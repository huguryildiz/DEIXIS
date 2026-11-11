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
from fakes import FakeAdapter, envelope, valid_response
from deixis.models.adapter import ModelStepResult
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
    # Scopus, CORE and SerpApi are searched by a legacy research only; an sw vocabulary compiles them no
    # query.
    assert [q["provider_id"] for q in queries] == [p for p in providers if p not in ("scopus", "core", "serpapi")]
    for query in queries:
        assert query_rules.query_issues(query["provider_id"], query["query_text"], query.get("endpoint")) == [], query
        assert len(query["query_text"]) <= query_compiler.MAX_QUERY_CHARS
        assert set(query) >= {"provider_id", "query_text", "rationale", "dropped_terms"}
    by_provider = {q["provider_id"]: q["query_text"] for q in queries}
    assert by_provider["pubmed"] == "(energy[Title/Abstract] OR wireless[Title/Abstract]) AND packet[Title/Abstract]"
    assert by_provider["arxiv"] == "(abs:energy OR abs:wireless) AND abs:packet"
    # Semantic Scholar is read through its bulk endpoint, whose syntax holds the blocks whole.
    assert by_provider["semantic_scholar"] == "(energy | wireless) + packet"


# ---- from tests__discovery__test_vocabulary_labels.py ------------------------------------------------------------

# The code rule reads the word in front of a phrase: "with" marks a method position, so "distributed ledgers" becomes
# a claim word and the setting drops out of the query. That is the error SW17 exists to correct.
SUPPLY = "What is the effect of shipment batching on delivery delay in supply chains with distributed ledgers?"


def test_the_user_s_key_terms_are_labelled_by_nobody_but_the_user():
    extraction = extract("Hangi ölçekleme modelleri önerilmiştir?", key_terms=KEY_TERMS)
    assert extraction.block_assignment == "user"


def stored_vocabulary(tmp_path, rid):
    """The vocabulary step's stored output, read from the library after the client closed it."""
    return store_at(tmp_path).latest_step_output(rid, "vocabulary", 1)["vocabulary"]


# ---- a question that is not English, translated by a model ------------------------------------------------

TRANSLATED = json.loads(valid_response({"task_type": "question_translation", "step_input_id": "sti_x", "scope_revision": 1,
                                        "skill_package_hash": "h"}))["english_question"]


def translations(adapter):
    return [si for si in adapter.calls if si["task_type"] == "question_translation"]


def test_a_turkish_question_is_translated_once_and_the_run_searches_its_words(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), FakeAdapter()
    app = app_for(tmp_path, monkeypatch, openalex, adapter)

    def pause_once(si):  # as the pause button does, while the translation is out: the run stops at its next checkpoint
        if si["task_type"] == "question_translation" and len(translations(adapter)) == 1:
            app.state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                       pause_reason="user_requested")
    adapter.before = pause_once
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, TURKISH)
        _, run = wait(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    # Asked once: the resumed run read the succeeded step back instead of calling the model again.
    assert len(translations(adapter)) == 1
    sent = translations(adapter)[0]
    assert sent["question"] == {"text": TURKISH, "language_hint": None}
    assert not sent["candidates"] and not sent["sources"] and not sent["passages"]
    # Every other model step still reads the question as written.
    assert all(si["question"]["text"] == TURKISH for si in adapter.calls)
    store = store_at(tmp_path)
    assert {k: v for k, v in store.english_question(rid, 1).items() if k != "created_at"} == {"text": TRANSLATED, "origin": "model"}
    vocabulary = stored_vocabulary(tmp_path, rid)
    translator = vocabulary["english_question"].pop("model")
    assert vocabulary["english_question"] == {"text": TRANSLATED, "origin": "model"}
    assert (translator["connection"], translator["model"]) == ("fake", "fake-model")
    assert "packet size" in [t["phrase"] for t in vocabulary["terms"]]
    # The translated sentence's words are counted on OpenAlex and become the ranking and screening blocks; no
    # query is compiled from them any more, so the probe is where they show.
    assert any("packet" in probe["query"] for probe in vocabulary["probes"]), vocabulary["probes"]
    step = next(s for s in run["steps"] if s["operation_key"] == "vocabulary")
    assert step["output"] == {"english_question": {"text": TRANSLATED, "origin": "model", "model": translator}}

    # A revision of the same question with the person's own sentence: it is theirs for the new revision, the
    # model's is not carried over, and the new revision's search asks no model to translate.
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        mine = "How do relay nodes change throughput in wireless mesh networks?"
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": TURKISH, "expected_version": version,
                                                                     "english_question": mine})
        assert revised.status_code == 200, revised.text
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
    assert len(translations(adapter)) == 1
    store = store_at(tmp_path)
    assert (store.english_question(rid, 2)["text"], store.english_question(rid, 2)["origin"]) == (mine, "user")
    assert store.latest_step_output(rid, "vocabulary", 2)["vocabulary"]["english_question"] == {
        "text": mine, "origin": "user", "model": None}


def test_the_persons_english_sentence_is_used_and_no_model_translates(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, monkeypatch, CountingOpenAlex(), adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        created = client.post("/api/researches", json={"question": TURKISH, "model_connection": "fake",
                                                       "requested_model": "fake-model", "effort": "quick"}).json()
        rid = created["research"]["id"]
        mine = "How do relay nodes change throughput in wireless mesh networks?"
        saved = client.put(f"/api/researches/{rid}/english-question",
                           json={"text": mine, "expected_version": created["research"]["version"]})
        assert saved.status_code == 200, saved.text
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
    assert translations(adapter) == []
    vocabulary = stored_vocabulary(tmp_path, rid)
    assert vocabulary["english_question"] == {"text": mine, "origin": "user", "model": None}
    assert "relay nodes" in [t["phrase"] for t in vocabulary["terms"]]


@pytest.mark.parametrize("failure", ["invalid", "down"])
def test_a_translation_that_fails_stops_the_run_for_key_terms(tmp_path, monkeypatch, failure):
    def answer(si):
        if si["task_type"] == "question_translation":  # still not English after the one repair
            return json.dumps(envelope(si, "deixis.question_translation.v1") | {"english_question": TURKISH})
        return valid_response(si)

    def down(si):
        return ModelStepResult("failed", error="SYNTHETIC model connection is down") \
            if si["task_type"] == "question_translation" else None
    adapter = FakeAdapter(answer) if failure == "invalid" else FakeAdapter(fail=down)
    openalex = CountingOpenAlex()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, TURKISH)
        _, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "key_terms_needed"), run
    assert run["error"]["translation"]["reason"] == ("invalid_model_output" if failure == "invalid" else "model_call_failed")
    assert len(translations(adapter)) == (2 if failure == "invalid" else 1)
    assert store_at(tmp_path).english_question(rid, 1) is None
    assert not openalex.searches and not openalex.counts

"""Search words taken from the question by code: extraction, the count probe, narrowing and block queries (SW2, SW3.5).

Every question here is SYNTHETIC and each comes from a different field, so that no test can be made to pass by adding
a topic word to `domain/vocabulary_words.py`. Passing shows the extraction and narrowing rules behave as written; it
says nothing about whether the words chosen are the right search words, which is measured in slice 24.
"""

import asyncio

import httpx
import pytest

from deixis.domain import vocabulary, vocabulary_words
from deixis.providers import openalex, query_compiler, query_rules
from deixis.providers.registry import CONNECTORS
from deixis.workflow.vocabulary import MANAGEABLE_TOTAL, MAX_PROBES, VERY_LARGE_COUNT, build_vocabulary

NETWORKS = "What is the throughput of relay selection in wireless sensor networks?"
CLINICAL = ("Which outcomes of early mobilization in intensive care units are reported, using propensity score "
            "matching, not surveys?")
MATERIALS = "Which hardness of ceramic coatings on titanium substrates is reported?"
QUANTUM_METHOD = "Which routing schemes in quantum networks are studied using ILP?"
PACKET = "What is the effect of packet size on energy consumption in wireless sensor networks?"
TURKISH = "Kuantum ağlarında dolanıklık dağıtımı için hangi eniyileme modelleri önerilmiştir?"


# ---- Task 1: extraction --------------------------------------------------------------------------------------

def test_a_phrase_of_x_in_z_splits_into_a_task_and_a_setting_block():
    extraction = vocabulary.extract(NETWORKS)
    assert extraction.language == "en" and extraction.block_assignment == "rule"
    assert extraction.blocks["task"] == ["throughput", "relay selection"]
    assert extraction.blocks["setting"] == ["wireless sensor networks"]
    assert extraction.claim_words == [] and extraction.exclusion_words == []


def test_a_method_position_phrase_is_a_claim_word_and_never_a_block_term():
    extraction = vocabulary.extract(QUANTUM_METHOD)
    assert extraction.claim_words == ["ilp"]
    assert extraction.blocks == {"setting": ["quantum networks"], "task": ["routing schemes"], "outcome": []}


def test_an_exclusion_cue_fills_the_exclusion_list_and_a_general_only_phrase_is_dropped():
    extraction = vocabulary.extract(CLINICAL)
    assert extraction.exclusion_words == ["surveys"]
    assert extraction.claim_words == ["propensity score matching"]
    assert extraction.blocks["task"] == ["outcomes", "early mobilization"]
    assert extraction.blocks["setting"] == ["intensive care units"]
    # "are reported," is a phrase of general words alone and leaves nothing behind.
    assert all("reported" not in phrase for block in extraction.blocks.values() for phrase in block)


def test_a_general_word_at_either_end_of_a_phrase_is_trimmed():
    extraction = vocabulary.extract("Which recent hardness measurements of new ceramic coatings are compared?")
    assert extraction.blocks["task"] == ["hardness measurements", "ceramic coatings"]


def test_a_third_field_parses_the_same_way_and_an_outcome_cue_fills_the_outcome_block():
    extraction = vocabulary.extract(MATERIALS)
    assert extraction.blocks["task"] == ["hardness", "ceramic coatings"]
    assert extraction.blocks["setting"] == ["titanium substrates"]
    outcome = vocabulary.extract("Which coating recipes are used to reduce surface roughness?")
    assert outcome.blocks["outcome"] == ["surface roughness"]


def test_the_first_position_a_phrase_appears_in_is_the_one_it_keeps():
    extraction = vocabulary.extract("Which packet size in wireless sensor networks, and packet size in wired networks?")
    assert extraction.blocks["task"] == ["packet size"]  # the second mention keeps the first position
    assert extraction.blocks["setting"] == ["wireless sensor networks", "wired networks"]


def test_a_plain_english_question_dense_in_content_words_is_read_as_english():
    # SYNTHETIC questions with two function words in eleven, and with none at all in a short keyword list.
    assert vocabulary.detect_language("Does packet size optimization reduce energy consumption in wireless sensor networks?", None) == "en"
    assert vocabulary.detect_language("Packet size optimization wireless sensor networks", None) == "en"
    assert vocabulary.detect_language("How does the Schrödinger bridge improve sampling in diffusion models?", None) == "en"


def test_accents_with_few_english_function_words_or_a_long_text_with_none_is_not_english():
    assert vocabulary.detect_language("Wie beeinflusst die Paketgröße den Energieverbrauch in drahtlosen Sensornetzen?", None) == "other"
    assert vocabulary.detect_language("Kablosuz algilayici aglarda paket boyutu enerji tuketimini nasil etkiler acaba", None) == "other"


def test_a_question_that_is_not_english_needs_the_users_key_terms():
    assert vocabulary.detect_language(TURKISH, None) == "other"
    assert vocabulary.detect_language(TURKISH, "en") == "en"  # an explicit hint decides
    assert vocabulary.detect_language(NETWORKS, "tr") == "other"
    assert vocabulary.detect_language("量子ネットワークのルーティング?", None) == "other"
    assert vocabulary.extract(TURKISH) is None


def test_key_terms_replace_the_extraction_and_record_that_the_user_assigned_the_blocks():
    extraction = vocabulary.extract(
        TURKISH, key_terms="quantum networks; entanglement distribution, entanglement routing; fidelity; "
                           "claim: integer programming; not: survey")
    assert extraction.block_assignment == "user" and extraction.language == "other"
    assert extraction.blocks == {"setting": ["quantum networks"],
                                 "task": ["entanglement distribution", "entanglement routing"],
                                 "outcome": ["fidelity"]}
    assert extraction.claim_words == ["integer programming"] and extraction.exclusion_words == ["survey"]


@pytest.mark.parametrize("key_terms", ["", "   ", "a;;b", "a, ,b", "claim:", "not: ", "a; b; c; d"])
def test_malformed_key_terms_are_refused(key_terms):
    with pytest.raises(ValueError):
        vocabulary.parse_key_terms(key_terms)


def test_no_word_list_holds_a_term_of_any_field_used_in_these_questions():
    """The guard of the slice: a list may hold function words and general words, never a topic's own word."""
    listed = (vocabulary_words.ENGLISH_FUNCTION_WORDS | vocabulary_words.GENERAL_WORDS
              | {word for cue in vocabulary_words.CUE_WORDS for word in cue}
              | {word for frame in vocabulary_words.QUESTION_FRAMES for word in frame.split()})
    topic_words = set("""throughput relay selection wireless sensor networks outcomes early mobilization intensive
        care units propensity score matching hardness ceramic coatings titanium substrates routing schemes quantum
        ilp entanglement distribution fidelity packet energy roughness surface consumption size limits""".split())
    assert listed & topic_words == set()


# ---- Task 2: the count probe ---------------------------------------------------------------------------------

def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def one_count(handler, **kwargs):
    async with client_for(handler) as client:
        return await openalex.count_works(client, kwargs.pop("query", "packets"), **kwargs)


def test_a_count_request_reads_meta_count_with_the_smallest_page_and_the_narrowest_select():
    seen = {}

    def handler(request):
        seen["url"] = request.url
        return httpx.Response(200, json={"meta": {"count": 1234}, "results": []})

    assert asyncio.run(one_count(handler, query='"packet size"', api_key=None, mailto="a@b.c")) == 1234
    assert seen["url"].params["per_page"] == "1" and seen["url"].params["select"] == "id"
    assert seen["url"].params[openalex.SEARCH_PARAM] == '"packet size"'
    assert seen["url"].params["mailto"] == "a@b.c"


def raises_timeout(request):
    raise httpx.ReadTimeout("slow")


@pytest.mark.parametrize("handler", [
    lambda request: httpx.Response(429, headers={"retry-after": "600"}),
    raises_timeout,
    lambda request: httpx.Response(500),
    lambda request: httpx.Response(200, text="not json"),
    lambda request: httpx.Response(200, json={"results": []}),
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


# ---- Task 3: probing and narrowing -------------------------------------------------------------------------

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


def test_a_phrase_no_record_holds_is_dropped_and_the_root_is_the_least_frequent_word():
    counts = {'"packet size"': 900, "packet": 400_000, "size": 900_000,
              '"energy consumption"': 0, "energy": 800_000, "consumption": 500_000,
              '"wireless sensor networks"': 50_000, "wireless": 300_000, "sensor": 700_000, "networks": 2_000_000}
    asked, built = built_for(PACKET, counts, default=10)
    terms = {t["phrase"]: t for t in built["terms"]}
    assert terms["energy consumption"]["dropped"] == "zero_results"
    assert terms["packet size"]["root"] == "packet" and terms["packet size"]["in_query"] == "root"
    assert terms["wireless sensor networks"]["root"] == "wireless"  # 300_000, against sensor and networks
    # Phrases are probed before words, the setting block before the task block, and no word of a dropped phrase.
    assert asked[:3] == ['"energy consumption"', '"wireless sensor networks"', '"packet size"']
    assert "consumption" not in asked and asked[3:6] == ["wireless", "sensor", "networks"]
    assert [p["count"] for p in built["probes"]][:3] == [0, 50_000, 900]
    assert {p["query"] for p in built["probes"]} == set(asked)


def test_a_gate_larger_than_the_manageable_total_turns_its_widest_root_into_a_phrase():
    counts = {'"packet size"': 900, "packet": 400_000, "size": 900_000,
              '"wireless sensor networks"': 50_000, "wireless": 900_000, "sensor": 950_000, "networks": 2_000_000,
              '"energy consumption"': 10, "energy": 10, "consumption": 10}
    asked, built = built_for(PACKET, counts, default=MANAGEABLE_TOTAL + 1)
    assert built["gate_count"] > MANAGEABLE_TOTAL  # no root was narrow enough; every term ended as its phrase
    assert {t["in_query"] for t in built["terms"]} == {"phrase"}
    # Only the counts choose the order: the widest root (wireless, 900_000) is replaced first, then packet, then energy.
    assert [q for q in asked if " AND " in q] == [
        "(energy OR wireless) AND (packet)",
        '(energy OR "wireless sensor networks") AND (packet)',
        '(energy OR "wireless sensor networks") AND ("packet size")',
        '("energy consumption" OR "wireless sensor networks") AND ("packet size")']


def test_a_manageable_gate_changes_no_root():
    asked, built = built_for(PACKET, default=10)
    assert {t["in_query"] for t in built["terms"]} == {"root"}
    assert built["gate_count"] == 10 and built["too_broad"] is False
    assert len([q for q in asked if " AND " in q]) == 1


def test_an_unknown_count_puts_the_whole_phrase_in_the_query():
    async def count(query):
        return None

    built = asyncio.run(build_vocabulary(vocabulary.extract(PACKET), count))
    assert {t["in_query"] for t in built["terms"]} == {"phrase"}
    assert built["gate_count"] is None and all(t["dropped"] is None for t in built["terms"])


def test_the_probe_budget_is_never_exceeded_and_unprobed_terms_enter_as_phrases():
    long_question = "Which " + " and ".join(f"alpha{n} beta{n} gamma{n}" for n in range(50)) + " in labs?"
    asked, built = built_for(long_question, default=5)
    assert len(asked) == MAX_PROBES and built["probes_skipped"] > 0 and len(built["terms"]) > MAX_PROBES
    unprobed = [t for t in built["terms"] if t["phrase_count"] is None]
    assert unprobed and all(t["in_query"] == "phrase" and t["root"] == t["phrase"] for t in unprobed)


def test_a_single_block_of_very_frequent_terms_only_is_reported_as_too_broad():
    asked, built = built_for("Which networks?", default=VERY_LARGE_COUNT + 1)
    assert built["too_broad"] is True and all(t["and_only"] for t in built["terms"] if not t["dropped"])
    assert {t["block"] for t in built["terms"]} == {"task"}  # one block only


def test_two_blocks_of_very_frequent_terms_are_not_too_broad_because_the_and_narrows_them():
    asked, built = built_for(PACKET, default=VERY_LARGE_COUNT + 1)
    assert built["too_broad"] is False and all(t["and_only"] for t in built["terms"])


def test_the_claim_and_exclusion_lists_reach_neither_the_terms_nor_a_probe():
    asked, built = built_for(CLINICAL, default=100)
    assert built["claim_words"] == ["propensity score matching"] and built["exclusion_words"] == ["surveys"]
    assert "propensity score matching" not in [t["phrase"] for t in built["terms"]]
    assert all("propensity" not in q and "survey" not in q for q in asked)


def test_the_same_extraction_and_the_same_counts_give_the_same_output_twice():
    first, second = built_for(PACKET, default=77)[1], built_for(PACKET, default=77)[1]
    assert first == second


# ---- Task 4: block queries ---------------------------------------------------------------------------------

def test_two_blocks_compile_to_one_or_group_per_block_joined_by_and():
    _, built = built_for(PACKET, default=10)
    (query,) = query_compiler.compile_block_queries(built, ["openalex"], 8)
    assert query["query_text"] == "(energy OR wireless) AND packet"
    assert query["dropped_terms"] == [] and query["rationale"] == "Concept blocks: setting AND task"


def test_each_provider_gets_one_query_in_its_own_syntax_and_all_pass_the_rules():
    _, built = built_for(PACKET, default=10)
    providers = [p for p in query_rules.NAMES if CONNECTORS[p].searchable]
    queries = query_compiler.compile_block_queries(built, providers, 100)
    assert [q["provider_id"] for q in queries] == providers
    for query in queries:
        assert query_rules.query_issues(query["provider_id"], query["query_text"]) == [], query
        assert len(query["query_text"]) <= query_compiler.MAX_QUERY_CHARS
        assert set(query) >= {"provider_id", "query_text", "rationale", "dropped_terms"}
    by_provider = {q["provider_id"]: q["query_text"] for q in queries}
    assert by_provider["pubmed"] == "(energy[Title/Abstract] OR wireless[Title/Abstract]) AND packet[Title/Abstract]"
    assert by_provider["arxiv"] == "(abs:energy OR abs:wireless) AND abs:packet"
    assert by_provider["scopus"] == "TITLE-ABS-KEY((energy OR wireless) AND packet)"
    assert by_provider["semantic_scholar"] == "energy packet" and by_provider["serpapi"] == "energy packet"


def test_a_budget_limits_how_many_providers_are_queried_and_serpapi_gets_one_query():
    _, built = built_for(PACKET, default=10)
    queries = query_compiler.compile_block_queries(built, ["serpapi", "openalex", "arxiv"], 2)
    assert [q["provider_id"] for q in queries] == ["serpapi", "openalex"]


def test_no_providers_query_holds_a_claim_word_an_exclusion_word_or_an_outcome_term():
    _, built = built_for(CLINICAL, default=100)
    queries = query_compiler.compile_block_queries(built, list(query_rules.NAMES), 100)
    forbidden = built["claim_words"] + built["exclusion_words"] + built["outcome_terms"]
    assert forbidden and queries
    for query in queries:
        for word in forbidden:
            assert word not in query["query_text"].lower(), (word, query)


def test_a_block_too_long_for_a_provider_is_trimmed_from_its_end_and_the_dropped_terms_are_recorded():
    alphas = ["alphaone", "alphatwo", "alphathree", "alphafour", "alphafive", "alphasix"]
    betas = ["betaone", "betatwo", "betathree"]
    _, built = built_for("Kuantum?", default=10, key_terms=f"{', '.join(alphas)}; {', '.join(betas)}")
    (query,) = query_compiler.compile_block_queries(built, ["openalex"], 8)
    assert query_rules.query_issues("openalex", query["query_text"]) == []
    # The last block is trimmed first and each block keeps at least its first term.
    assert query["query_text"] == "(alphaone OR alphatwo OR alphathree OR alphafour OR alphafive) AND betaone"
    assert query["dropped_terms"] == ["alphasix", "betatwo", "betathree"]


def test_a_single_block_vocabulary_gives_a_single_group_query():
    _, built = built_for("Which packet size?", default=10)
    (query,) = query_compiler.compile_block_queries(built, ["openalex"], 8)
    assert " AND " not in query["query_text"]


def test_a_vocabulary_with_no_queryable_term_compiles_nothing():
    _, built = built_for(PACKET, default=0)
    assert query_compiler.compile_block_queries(built, ["openalex"], 8) == []

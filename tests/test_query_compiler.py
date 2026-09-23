"""Provider queries compiled from a search plan's concepts (D44).

The concepts are the plan of the live entanglement routing run `run_xhrRwLM8U9xIG3LkBm1Z` of 2026-09-16 (Turkish labels,
English synonyms), copied as fixture data. Passing shows every compiled query keeps a core synonym, never searches a
label and passes the provider rules; it says nothing about recall.
"""

import re

import pytest

from deixis.providers import query_compiler, query_rules
from deixis.providers.registry import CONNECTORS

# Every provider a query may be sent to; a connector that is only asked about a known DOI compiles no query (D87).
ALL_PROVIDERS = [p for p in query_rules.NAMES if CONNECTORS[p].searchable]
CORE = {"label": "dolanıklık yönlendirmesi", "role": "core", "synonyms": ["entanglement routing", "entanglement distribution", "quantum routing"]}
ROUTING = [
    CORE,
    {"label": "kuantum ağları", "role": "context", "synonyms": ["quantum networks", "quantum communication networks", "quantum internet"]},
    {"label": "MILP/ILP formülasyonu", "role": "method", "synonyms": ["mixed-integer linear programming", "integer linear programming", "MIP", "ILP", "MILP"]},
    {"label": "çok akışlı yönlendirme", "role": "mechanism", "synonyms": ["multi-commodity flow", "multi-commodity routing", "multicommodity flow"]},
    {"label": "kuantum belleği bozunumu", "role": "mechanism", "synonyms": ["decoherence", "quantum memory decoherence", "memory lifetime", "entanglement decay"]},
    {"label": "zamana bağlı modelleme", "role": "method", "synonyms": ["time-dependent routing", "dynamic routing", "temporal model", "time-expanded network"]},
    {"label": "yönlendirme performansı", "role": "outcome", "synonyms": ["throughput", "fidelity", "latency", "resource utilization", "blocking probability"]},
    {"label": "kaynak tahsisi", "role": "mechanism", "synonyms": ["resource allocation", "path selection", "entanglement swapping"]},
]
ADJACENT = {"label": "kuantum tekrarlayıcılar", "role": "adjacent_field", "synonyms": ["quantum repeater networks"]}


def plan(concepts=ROUTING, providers=ALL_PROVIDERS):
    return {"concepts": concepts, "providers": providers}


def unprefixed(provider, text):
    """The boolean form of an arXiv or PubMed query, for the OpenAlex-style checks they share by construction."""
    if provider == "arxiv":
        return re.sub(r"\babs:", "", text)
    if provider == "pubmed":
        return text.replace("[Title/Abstract]", "")
    return query_rules.boolean_part(provider, text)


def test_every_compiled_query_keeps_a_core_synonym_searches_no_label_and_passes_the_provider_rules():
    queries = query_compiler.compile_queries(plan(ROUTING + [ADJACENT]), ALL_PROVIDERS, 100)
    assert {q["provider_id"] for q in queries} == set(ALL_PROVIDERS)
    labels = [c["label"].lower() for c in ROUTING + [ADJACENT]]
    for q in queries:
        provider, text = q["provider_id"], q["query_text"]
        assert query_rules.query_issues(provider, text) == [] and len(text) <= 300, q
        if (boolean := unprefixed(provider, text)) is not None:
            assert not query_rules.openalex_or_is_ambiguous(boolean) and query_rules.openalex_query_shape_issues(boolean) == [], q
        assert any(term in text for term in CORE["synonyms"]), q
        assert not any(label in text.lower() for label in labels), q
        assert "quantum repeater" not in text  # adjacent field unused beside other families


def test_queries_pair_the_core_group_with_one_family_in_each_provider_syntax():
    queries = {(q["provider_id"], q["rationale"]): q["query_text"] for q in query_compiler.compile_queries(plan(), ALL_PROVIDERS, 100)}
    method = 'Core "dolanıklık yönlendirmesi" with the method family "MILP/ILP formülasyonu"'
    decay = 'Core "dolanıklık yönlendirmesi" with the mechanism family "kuantum belleği bozunumu"'
    assert queries[("openalex", method)] == ('("entanglement routing" OR "entanglement distribution") AND '
                                             '("mixed-integer linear programming" OR "integer linear programming" OR MIP OR ILP)')
    assert queries[("arxiv", decay)] == ('(abs:"entanglement routing" OR abs:"entanglement distribution") AND '
                                         '(abs:decoherence OR abs:"quantum memory decoherence" OR abs:"memory lifetime" OR abs:"entanglement decay")')
    assert queries[("scopus", method)].startswith('TITLE-ABS-KEY(("entanglement routing" OR "entanglement distribution") AND (')
    assert queries[("pubmed", decay)].startswith('("entanglement routing"[Title/Abstract] OR "entanglement distribution"[Title/Abstract]) AND ')
    assert queries[("semantic_scholar", method)] == "entanglement routing mixed-integer linear programming"
    # SerpApi gets one query, and which family it pairs with follows the round robin over families and providers.
    assert [text for (provider, _), text in queries.items() if provider == "serpapi"] == [
        '"entanglement routing" "mixed-integer linear programming" OR "integer linear programming" OR MIP OR ILP']


def test_queries_alternate_over_families_and_providers_within_the_budget():
    concepts = [CORE, ROUTING[2], ROUTING[4]]
    queries = query_compiler.compile_queries(plan(concepts, ["openalex", "ieee_xplore", "arxiv"]), ALL_PROVIDERS, 4)
    assert [(q["provider_id"], q["rationale"].rsplit('"', 2)[1]) for q in queries] == [
        ("openalex", "MILP/ILP formülasyonu"), ("ieee_xplore", "kuantum belleği bozunumu"),
        ("arxiv", "MILP/ILP formülasyonu"), ("openalex", "kuantum belleği bozunumu"),
    ]
    everything = query_compiler.compile_queries(plan(concepts, ["openalex", "ieee_xplore", "arxiv"]), ALL_PROVIDERS, 100)
    assert len(everything) == 6 and len({(q["provider_id"], q["query_text"]) for q in everything}) == 6


def test_serpapi_gets_one_query_and_providers_outside_the_scope_get_none():
    queries = query_compiler.compile_queries(plan([CORE, ROUTING[2], ROUTING[4]], ["serpapi", "scopus", "openalex"]), ["openalex", "serpapi"], 100)
    assert [q["provider_id"] for q in queries] == ["serpapi", "openalex", "openalex"]


@pytest.mark.parametrize("concepts, expected", [
    # Adjacent-field concepts are the family only when no other family is given.
    ([CORE, ADJACENT], '("entanglement routing" OR "entanglement distribution" OR "quantum routing") AND "quantum repeater networks"'),
    # A family without synonyms is not searched, and a family term repeating the core is dropped; the core then stands alone.
    ([CORE, dict(ROUTING[2], synonyms=[]), {"label": "x", "role": "context", "synonyms": ["Quantum routing"]}],
     '("entanglement routing" OR "entanglement distribution" OR "quantum routing")'),
])
def test_family_selection(concepts, expected):
    assert [q["query_text"] for q in query_compiler.compile_queries(plan(concepts, ["openalex"]), ALL_PROVIDERS, 8)] == [expected]


def test_long_terms_are_trimmed_to_the_query_length_and_syntax_characters_removed():
    long_terms = [f"entanglement aware routing variant {n} with {'very ' * 8}long wording" for n in range(7)]
    concepts = [dict(CORE, synonyms=["entanglement routing", '"quantum" (routing)']), {"label": "MILP", "role": "method", "synonyms": ["MILP", *long_terms]}]
    (query,) = query_compiler.compile_queries(plan(concepts, ["core"]), ALL_PROVIDERS, 8)
    assert len(query["query_text"]) <= 300 and query_rules.query_issues("core", query["query_text"]) == []
    assert query["query_text"].startswith('("entanglement routing" OR "quantum routing") AND (MILP OR "entanglement aware')
    # CORE refuses a quoted phrase without AND, so a core-only plan gives it no query at all.
    assert query_compiler.compile_queries(plan([CORE], ["core"]), ALL_PROVIDERS, 8) == []


def test_a_deep_openalex_query_searches_the_core_group_alone_before_the_paired_queries():
    concepts = [CORE, ROUTING[2], ROUTING[4]]
    core = '("entanglement routing" OR "entanglement distribution" OR "quantum routing")'
    deep = query_compiler.compile_queries(plan(concepts, ["ieee_xplore", "openalex"]), ALL_PROVIDERS, 4, core_depth=100)
    shallow = query_compiler.compile_queries(plan(concepts, ["ieee_xplore", "openalex"]), ALL_PROVIDERS, 3)
    assert deep[0] == {"provider_id": "openalex", "query_text": core, "results": 100,
                       "rationale": 'Core "dolanıklık yönlendirmesi" alone, read to 100 results'}
    assert deep[1:] == shallow  # the deep query takes one request of the same limit
    # Without OpenAlex nothing changes; a plan without families gets the core query once, read deep.
    assert query_compiler.compile_queries(plan(concepts, ["ieee_xplore"]), ALL_PROVIDERS, 4, core_depth=100) == \
        query_compiler.compile_queries(plan(concepts, ["ieee_xplore"]), ALL_PROVIDERS, 4)
    assert [(q["query_text"], q.get("results")) for q in query_compiler.compile_queries(plan([CORE], ["openalex"]), ALL_PROVIDERS, 8, core_depth=100)] == [(core, 100)]


def test_opt_in_compact_openalex_keeps_the_deep_query_and_provider_budget():
    selected = plan([CORE, ROUTING[2], ROUTING[4], ROUTING[5]], ["openalex"])
    legacy = query_compiler.compile_queries(selected, ALL_PROVIDERS, 4, core_depth=100)
    compact = query_compiler.compile_queries(selected, ALL_PROVIDERS, 4, core_depth=100,
                                             strategy="compact_openalex_v1")
    assert compact[0] == legacy[0]
    assert [q["query_text"] for q in compact[1:]] == [
        '"entanglement routing" programming', '"entanglement distribution" decoherence',
        '"quantum routing" dependent',
    ]
    assert all(q.get("results", 25) <= 100 and not query_rules.query_issues("openalex", q["query_text"])
               for q in compact)
    assert len(compact) == len(legacy) == 4
    assert query_compiler.compile_queries(selected, ALL_PROVIDERS, 4, core_depth=100) == legacy


def test_compact_strategy_falls_back_when_a_short_query_is_invalid_and_rejects_unknown_strategy():
    concepts = [CORE, {"label": "acronym", "role": "method", "synonyms": ["in"]}]
    legacy = query_compiler.compile_queries(plan(concepts, ["openalex"]), ALL_PROVIDERS, 4)
    compact = query_compiler.compile_queries(plan(concepts, ["openalex"]), ALL_PROVIDERS, 4,
                                             strategy="compact_openalex_v1")
    assert compact == legacy
    with pytest.raises(ValueError, match="Unknown query compiler strategy"):
        query_compiler.compile_queries(plan(), ALL_PROVIDERS, 4, strategy="unregistered")


# ---- slice 13g Task 1: the fitting takes terms from the block that has the most (D90) -----------------------
# SYNTHETIC block terms from two fields; only their number and order matter to the fitting.


def _blocks(setting: list[str], task: list[str]) -> dict:
    def term(phrase: str, block: str) -> dict:
        return {"phrase": phrase, "block": block, "origin": "question", "root": phrase, "in_query": "phrase",
                "phrase_count": 10, "root_count": None, "and_only": False, "dropped": None}
    return {"terms": [term(p, "setting") for p in setting] + [term(p, "task") for p in task]}


NETWORK_SETTING = ["body area networks", "wearable sensors", "implant links", "on-body channels", "medical telemetry"]
NETWORK_TASK = ["frame length", "payload", "duty cycle", "retransmission"]
SOIL_SETTING = ["arid soils", "saline soils"]
SOIL_TASK = ["nitrogen uptake", "root depth", "irrigation timing", "biochar", "mulching", "cover crops", "tillage",
             "leaf area"]


def test_an_unbalanced_list_loses_terms_from_the_longer_block_first():
    (query,) = query_compiler.compile_block_queries(_blocks(NETWORK_SETTING, NETWORK_TASK), ["openalex"], 8)
    # 5 + 4 terms fit OpenAlex's five operators as 3 + 3; the old order cut the task block to one term (5 + 1).
    assert query["query_text"] == ('("body area networks" OR "wearable sensors" OR "implant links") AND '
                                   '("frame length" OR payload OR "duty cycle")')
    assert query["dropped_terms"] == ["on-body channels", "medical telemetry", "retransmission"]


def test_a_short_setting_block_keeps_its_terms_and_the_task_block_is_cut_to_fit():
    (query,) = query_compiler.compile_block_queries(_blocks(SOIL_SETTING, SOIL_TASK), ["openalex"], 8)
    # 2 + 8 gives 2 + 4, the same as the old order.
    assert query["query_text"] == ('("arid soils" OR "saline soils") AND '
                                   '("nitrogen uptake" OR "root depth" OR "irrigation timing" OR biochar)')
    assert query["dropped_terms"] == ["mulching", "cover crops", "tillage", "leaf area"]


def test_on_a_tie_the_last_block_loses_a_term_first():
    (query,) = query_compiler.compile_block_queries(_blocks(NETWORK_SETTING[:4], NETWORK_TASK), ["openalex"], 8)
    # 4 + 4: the task block goes first on the tie, then the setting block: 3 + 3.
    assert query["dropped_terms"] == ["on-body channels", "retransmission"]


def test_a_plain_word_query_keeps_a_word_of_each_block_when_the_setting_term_is_long():
    """Review of 13g (2026-09-23): a setting term of eight or more words filled Semantic Scholar's word cap and the
    task block was silently left out, with nothing in `dropped_terms`."""
    setting = ["SYNTHETIC long wearable body area network telemetry setting phrase here"]
    # Semantic Scholar's sw queries go to the bulk endpoint since D93, and no sw query goes to Crossref (D87); the rule
    # stays for the plain-word syntax, which the fitting is asked for directly.
    text, _ = query_compiler._fit_blocks("crossref", [setting, ["routing"]])
    words = text.split()
    assert "routing" in words and "SYNTHETIC" in words
    assert len(words) <= query_compiler.query_rules.MAX_PLAIN_WORDS


def test_a_plain_word_query_names_every_term_it_did_not_write_as_dropped():
    """Second review of 13g (2026-09-23): a plain-word query writes only the first term of each block, and SerpApi
    only the first setting term, so what the second round counts as searched reads the others as dropped."""
    groups = [["SYNTHETIC reef", "SYNTHETIC lagoon"], ["transplant", "gardening"]]
    blocks = _blocks(*groups)
    by_provider = {q["provider_id"]: q for q in query_compiler.compile_block_queries(
        blocks, ["openalex", "semantic_scholar"], 8)}
    assert by_provider["openalex"]["dropped_terms"] == []
    # A bulk query writes every term (D93); the plain-word and SerpApi syntaxes are fitted directly, since no sw
    # query goes to Crossref (D87) or SerpApi (D93) any more.
    assert by_provider["semantic_scholar"]["dropped_terms"] == []
    assert query_compiler._fit_blocks("crossref", groups)[1] == ["SYNTHETIC lagoon", "gardening"]
    assert query_compiler._fit_blocks("serpapi", groups)[1] == ["SYNTHETIC lagoon"]

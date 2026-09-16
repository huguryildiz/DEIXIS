"""Provider queries compiled from a search plan's concepts (D44).

The concepts are the plan of the live entanglement routing run `run_xhrRwLM8U9xIG3LkBm1Z` of 2026-09-16 (Turkish labels,
English synonyms), copied as fixture data. Passing shows every compiled query keeps a core synonym, never searches a
label and passes the provider rules; it says nothing about recall.
"""

import re

import pytest

from deixis.providers import query_compiler, query_rules

ALL_PROVIDERS = list(query_rules.NAMES)
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
    assert queries[("crossref", method)] == "entanglement routing mixed-integer linear programming"
    assert [text for (provider, _), text in queries.items() if provider == "serpapi"] == [
        '"entanglement routing" "multi-commodity flow" OR "multi-commodity routing" OR "multicommodity flow"']


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

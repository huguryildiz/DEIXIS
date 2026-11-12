"""Provider queries compiled from an sw vocabulary's concept blocks.

The SearchPlan v2 compiler (`compile_queries`) and its tests were removed in the clean start (slice 3a); what is
left here is the block fitting every discovery query goes through. Block terms are SYNTHETIC; passing shows which terms
a query keeps and names as dropped, not recall.
"""

from deixis.providers import query_compiler


# ---- slice 13g Task 1: the fitting takes terms from the block that has the most -----------------------
# SYNTHETIC block terms from two fields; only their number and order matter to the fitting.


def _blocks(setting: list[str], task: list[str]) -> dict:
    def term(phrase: str, block: str) -> dict:
        return {"phrase": phrase, "block": block, "origin": "question", "root": phrase, "in_query": "phrase",
                "phrase_count": 10, "root_count": None, "and_only": False, "dropped": None}
    return {"terms": [term(p, "setting") for p in setting] + [term(p, "task") for p in task]}


NETWORK_SETTING = ["body area networks", "wearable sensors", "implant links", "on-body channels", "medical telemetry"]
NETWORK_TASK = ["frame length", "payload", "duty cycle", "retransmission"]


def test_an_unbalanced_list_loses_terms_from_the_longer_block_first():
    (query,) = query_compiler.compile_block_queries(_blocks(NETWORK_SETTING, NETWORK_TASK), ["openalex"], 8)
    # 5 + 4 terms fit OpenAlex's five operators as 3 + 3; the old order cut the task block to one term (5 + 1).
    assert query["query_text"] == ('("body area networks" OR "wearable sensors" OR "implant links") AND '
                                   '("frame length" OR payload OR "duty cycle")')
    assert query["dropped_terms"] == ["on-body channels", "medical telemetry", "retransmission"]


def test_a_plain_word_query_names_every_term_it_did_not_write_as_dropped():
    """Second review of 13g (2026-09-23): a plain-word query writes only the first term of each block, and SerpApi
    only the first setting term, so what the second round counts as searched reads the others as dropped."""
    groups = [["SYNTHETIC reef", "SYNTHETIC lagoon"], ["transplant", "gardening"]]
    blocks = _blocks(*groups)
    by_provider = {q["provider_id"]: q for q in query_compiler.compile_block_queries(
        blocks, ["openalex", "semantic_scholar"], 8)}
    assert by_provider["openalex"]["dropped_terms"] == []
    # A bulk query writes every term; the plain-word and SerpApi syntaxes are fitted directly, since no sw
    # query goes to Crossref or SerpApi any more.
    assert by_provider["semantic_scholar"]["dropped_terms"] == []
    assert query_compiler._fit_blocks("crossref", groups)[1] == ["SYNTHETIC lagoon", "gardening"]
    assert query_compiler._fit_blocks("serpapi", groups)[1] == ["SYNTHETIC lagoon"]


# ---- the other number form of a quoted phrase (`phrase_number_v1`) ------------------------------------------


def _formed(setting: list[str], task: list[str]) -> dict:
    """A vocabulary frozen under the forms rule, each term's form stored as the plan stores it."""
    variants = {term: query_compiler.number_variant(term) for term in setting + task}
    return _blocks(setting, task) | {"phrase_forms": {"rule": query_compiler.PHRASE_FORMS_RULE, "variants": variants}}


def test_a_quoted_phrase_is_searched_in_both_numbers_beside_it_and_the_query_says_so():
    # OpenAlex matched "mixtures of experts" in a title and not "mixture of experts"; the word before " of " turns.
    (query, bulk) = query_compiler.compile_block_queries(
        _formed(["mixture of experts", "mixture-of-experts"], ["differentiable"]), ["openalex", "semantic_scholar"], 8)
    assert query["query_text"] == ('("mixture of experts" OR "mixtures of experts" OR "mixture-of-experts")'
                                   ' AND differentiable')
    assert query["dropped_terms"] == []
    assert query["phrase_forms"] == {"rule": query_compiler.PHRASE_FORMS_RULE, "terms": [
        {"phrase": "mixture of experts", "variant": "mixtures of experts", "searched": True, "left_out": None}]}
    # Only OpenAlex gets the form: the other providers' queries are the ones compiled before the rule.
    assert bulk["provider_id"] == "semantic_scholar" and "phrase_forms" not in bulk
    assert "mixtures" not in bulk["query_text"]


def test_a_form_only_takes_room_the_plan_s_own_terms_left_and_says_which_it_left_out():
    # Three terms a block fill OpenAlex's five operators; no form fits, and every plan term is still written. The
    # gerund "graph clustering" takes no plural at all.
    setting = ["graph neural network", "message passing network", "graph attention model"]
    task = ["link prediction", "node classification", "graph clustering"]
    (formed,) = query_compiler.compile_block_queries(_formed(setting, task), ["openalex"], 8)
    (before,) = query_compiler.compile_block_queries(_blocks(setting, task), ["openalex"], 8)
    assert formed["query_text"] == before["query_text"] and formed["dropped_terms"] == before["dropped_terms"] == []
    assert all(f'"{term}"' in formed["query_text"] for term in setting + task)
    assert [(row["phrase"], row["searched"], row["left_out"]) for row in formed["phrase_forms"]["terms"]] == [
        (term, False, "no_variant" if term == "graph clustering" else "operator_cap") for term in setting + task]
    # With one term fewer, the first form in the plan's order takes the one operator left; the rest stay out.
    (room,) = query_compiler.compile_block_queries(_formed(setting, task[:2]), ["openalex"], 8)
    assert room["query_text"] == ('("graph neural network" OR "graph neural networks" OR "message passing network" OR'
                                  ' "graph attention model") AND ("link prediction" OR "node classification")')
    assert [row["searched"] for row in room["phrase_forms"]["terms"]] == [True, False, False, False, False]


def test_a_form_that_would_pass_the_length_cap_is_left_out_and_the_plan_term_stays():
    long = "SYNTHETIC " * 14 + "network"  # 147 characters: the term fits, the term and its form do not
    (query,) = query_compiler.compile_block_queries(_formed([long], ["routing"]), ["openalex"], 8)
    assert query["query_text"] == f'"{long}" AND routing'
    assert query["phrase_forms"]["terms"] == [
        {"phrase": long, "variant": long + "s", "searched": False, "left_out": "length_cap"}]


def test_a_plan_frozen_before_the_rule_compiles_to_its_old_query():
    vocabulary = _blocks(["mixture of experts", "mixture-of-experts"], ["differentiable"])
    (query,) = query_compiler.compile_block_queries(vocabulary, ["openalex"], 8)
    assert query["query_text"] == '("mixture of experts" OR "mixture-of-experts") AND differentiable'
    assert "phrase_forms" not in query


def test_the_rule_leaves_alone_the_words_whose_number_it_cannot_tell():
    for phrase in ("time series", "sentiment analysis", "gene species", "large LLMS", "layer conv3d", "user focus",
                   "text corpus", "power bias",
                   # Gerunds and words that are not counted take no plural.
                   "federated learning", "graph clustering", "big data", "internet of things", "sensor information",
                   "wireless traffic", "network security", "user privacy", "random access", "user behaviour"):
        assert query_compiler.number_variant(phrase) is None, phrase
    # A single word and an unquoted term get no form; a form equal to a plan term is not added twice.
    assert query_compiler.number_variant("experts") is None
    (query,) = query_compiler.compile_block_queries(
        _formed(["time series", "neural network", "neural networks"], ["forecasting"]), ["openalex"], 8)
    assert query["query_text"] == '("time series" OR "neural network" OR "neural networks") AND forecasting'
    assert [(row["phrase"], row["left_out"]) for row in query["phrase_forms"]["terms"]] == [
        ("time series", "no_variant"), ("neural network", "in_plan"), ("neural networks", "in_plan")]
    # The fixed rule in both directions, its plural-to-singular step only where the plural rule turns it back.
    assert [query_compiler.number_variant(p) for p in ("query strategy", "search boxes", "prompt databases",
                                                       "graph classes", "label batches")] == [
        "query strategies", "search box", "prompt database", "graph class", "label batch"]
    # Plural to singular is unchanged for those words.
    assert query_compiler.number_variant("deep learnings") == "deep learning"

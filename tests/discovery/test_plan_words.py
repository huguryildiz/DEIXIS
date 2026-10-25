"""D26: which plan words a query the frozen plan sends really carries (SYNTHETIC vocabularies; no provider, no model).

`fast_search.plan_words` reads the compiled queries back through the block compiler; passing shows the record agrees
with what the compiler wrote, not that any provider was asked.
"""

from deixis.providers import query_compiler
from deixis.workflow import search as fast_search

# The [parity] research's code vocabulary: OpenAlex has room for five task words, so the sixth is cut from its query,
# while the Semantic Scholar bulk query holds all six.
TASK = ["parity", "relationship", "k-connectivity", "network", "energy", "modeled"]


def term(phrase, block, dropped=None, origin="question"):
    return {"phrase": phrase, "block": block, "origin": origin, "root": phrase, "in_query": "phrase",
            "phrase_count": None, "root_count": None, "and_only": False, "dropped": dropped}


def vocabulary(extra=()):
    return {"terms": [term("synthetic", "setting"), *(term(w, "task") for w in TASK), *extra]}


def plan_for(vocab, *, deep):
    queries = query_compiler.compile_block_queries(vocab, ["openalex", "semantic_scholar"], 4)
    openalex = [{"index": i, "query": q} for i, q in enumerate(queries) if q["provider_id"] == "openalex"]
    s2 = next(q for q in queries if q["provider_id"] == "semantic_scholar")
    return {"keywords": openalex, "s2_bulk": s2 if deep else None}, queries


def by_term(words):
    return {w["term"]: (w["searched"], w["left_out"]) for w in words}


def test_a_word_cut_from_the_only_sent_query_is_not_searched():
    vocab = vocabulary()
    plan, queries = plan_for(vocab, deep=False)
    assert queries[0]["dropped_terms"] == ["modeled"]  # the compiler cut it, as in the [parity] research
    words = by_term(fast_search.plan_words(vocab, plan))
    assert words["modeled"] == (False, "query_limit")
    assert all(words[w] == (True, None) for w in ["synthetic", *TASK[:5]])


def test_a_word_the_sent_bulk_query_holds_is_searched():
    vocab = vocabulary()
    plan, _ = plan_for(vocab, deep=True)
    assert by_term(fast_search.plan_words(vocab, plan))["modeled"] == (True, None)


def test_a_word_only_an_unsent_query_holds_is_not_sent():
    """No OpenAlex keyword query is sent and the bulk query is not sent either: every word was held only by queries the
    plan leaves out."""
    vocab = vocabulary()
    words = fast_search.plan_words(vocab, {"keywords": [], "s2_bulk": None})
    assert {(w["searched"], w["left_out"]) for w in words} == {(False, "not_sent")}


def test_a_dropped_word_keeps_its_own_reason():
    vocab = vocabulary([term("absent", "task", dropped="zero_results")])
    plan, _ = plan_for(vocab, deep=True)
    assert by_term(fast_search.plan_words(vocab, plan))["absent"] == (False, "zero_results")


def test_a_query_that_cannot_be_read_back_leaves_unproven_words_unknown():
    """A stored text the compiler does not give again proves nothing about what that query held: a word no other sent
    query carries is neither searched nor left out."""
    vocab = vocabulary()
    plan, _ = plan_for(vocab, deep=False)
    plan["keywords"][0]["query"] = plan["keywords"][0]["query"] | {"query_text": "synthetic AND other"}
    assert {(w["searched"], w["left_out"]) for w in fast_search.plan_words(vocab, plan)} == {(None, None)}


def test_the_code_query_beside_a_model_query_counts_with_its_own_words():
    """A word the model's query had no room for is still searched when the code's query, sent beside it, carries it."""
    model = {"terms": [term("synthetic", "setting", origin="search_query"),
                       *(term(w, "task", origin="search_query") for w in ["energy", "lifetime", "routing", "coverage", "clustering", "sleep"])],
             "code_query": {"vocabulary": {"terms": [term("synthetic", "setting"), term("sleep", "task")]}}}
    model_query = query_compiler.compile_block_queries(model, ["openalex"], 1)[0] | {"origin": "model"}
    assert model_query["dropped_terms"] == ["sleep"]
    code_query = query_compiler.compile_block_queries(model["code_query"]["vocabulary"], ["openalex"], 1)[0] | {"origin": "code"}
    alone = by_term(fast_search.plan_words(model, {"keywords": [{"index": 0, "query": model_query}], "s2_bulk": None}))
    assert alone["sleep"] == (False, "query_limit")
    both = by_term(fast_search.plan_words(model, {"keywords": [{"index": 0, "query": model_query},
                                                               {"index": 1, "query": code_query}], "s2_bulk": None}))
    assert both["sleep"] == (True, None)


def test_the_panel_names_the_plan_words_as_the_plan_writes_them():
    """The Search plan panel lists the plan's own words the frozen search records as not searched, matched one way
    written; a protocol frozen before the record lists nothing rather than guessing."""
    from deixis.workflow import user_plan

    plan = {"setting": [{"term": "Synthetic"}], "task": [{"term": "energy"}, {"term": "Modeled"}]}
    words = [{"block": "setting", "term": "synthetic", "searched": True, "left_out": None},
             {"block": "task", "term": "energy", "searched": None, "left_out": None},
             {"block": "task", "term": "modeled", "searched": False, "left_out": "query_limit"}]
    assert user_plan._unsearched(plan, {"fast_path_search": {"words": words}}) == [
        {"block": "task", "term": "Modeled", "left_out": "query_limit"}]
    assert user_plan._unsearched(plan, {"fast_path_search": {"version": 1}}) is None
    assert user_plan._unsearched(plan, {}) is None

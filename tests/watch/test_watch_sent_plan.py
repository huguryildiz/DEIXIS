"""Which requests of a frozen protocol a watch follows; SYNTHETIC bodies, no provider calls."""
from deixis.workflow.fast_search import sent_plan


def test_a_watch_follows_the_dated_queries_a_fast_plan_sends():
    compiled = [{"provider_id": "openalex", "query_text": "A"}, {"provider_id": "crossref", "query_text": "B"},
                {"provider_id": "semantic_scholar", "query_text": "C", "endpoint": "bulk"}]
    body = {"compiled_queries": compiled, "fast_path_search": {
        "semantic": {"query_text": "S", "query_origin": "question"},
        "seed_semantic": [{"index": 0, "provider_id": "openalex", "query_text": "P", "origin": "seed_text"}],
        "keywords": [{"index": 0}], "s2_bulk": compiled[2], "s2_bulk_index": 2}}
    assert [(q["key"], q["watchable"], q.get("compiled_index")) for q in sent_plan(body)] == [
        ("search:fast:semantic", False, None), ("search:fast:semantic:seed:0", False, None), ("search:0", True, 0),
        ("search:fast:s2_bulk", True, 2)]
    # A body frozen without the plan sends every compiled query under its index.
    assert [q["key"] for q in sent_plan({"compiled_queries": compiled})] == ["search:0", "search:1", "search:2"]

"""The pure rules of the reranker's pre-selection (`preselect`): which query lists vote, what each vote is worth,
and what the window's floors keep.

No database, no model and no network here: every case is a function of hit rows and a fused order. SYNTHETIC
records. Passing shows the rule behaves as the design says, not that it orders records better.
"""

from deixis.workflow.search import preselect


def hit(head, query, rank, provider="openalex", sort=None, relevance=True, read_total=None):
    return {"head": head, "provider": provider, "query_text": query, "rank": rank, "sort": sort,
            "relevance": relevance, "read_total": read_total}


def test_one_query_is_one_list_however_many_pages_and_resends_it_took():
    """The pages of one query are the same list, and a resend of it is no second vote: the record is counted once,
    at the first place that list gave it."""
    lists = preselect.lists([
        hit("a", "Q1", 0, read_total=100), hit("b", "Q1", 1),   # the first page
        hit("c", "Q1", 50), hit("a", "Q1", 60),                 # the next page, and the same record again further down
        hit("a", "Q2", 3),                                      # another query: its own list
    ])
    assert [(entry["query_text"], entry["size"]) for entry in lists] == [("Q1", 3), ("Q2", 1)]
    assert lists[0]["places"] == {"a": 0, "b": 1, "c": 50} and lists[0]["read_total"] == 100
    # Two lists hold "a", so it has two contributions and nothing more.
    contributions = preselect.scores(lists)
    assert [part["query_text"] for part in contributions["a"]] == ["Q1", "Q2"]
    assert [part["rank"] for part in contributions["a"]] == [1, 4]


def test_a_list_the_provider_ordered_by_date_or_citations_casts_no_vote_but_is_still_a_way_in():
    # Such a list is not a relevance order, so it votes for nothing; its records are in the pool and the list is
    # kept with its setting, because being found by it is a way in the floors have to see.
    lists = preselect.lists([hit("a", "Q1", 0, sort="citationCount:desc", relevance=False), hit("b", "Q2", 0)])
    assert [(entry["query_text"], entry["votes"], entry["sort"]) for entry in lists] == [
        ("Q1", False, "citationCount:desc"), ("Q2", True, None)]
    assert preselect.scores(lists).keys() == {"b"}
    assert lists[0]["members"] == ["a"]


def test_a_list_whose_setting_names_the_providers_own_relevance_order_votes():
    # PubMed and Scopus name a sorting setting on every request; `relevance` says it is a relevance order, so the
    # list votes like one that names none.
    lists = preselect.lists([hit("a", "Q1", 0, provider="pubmed", sort="relevance"),
                             hit("b", "Q2", 0, provider="scopus", sort="relevancy")])
    assert all(entry["votes"] for entry in lists)
    assert preselect.scores(lists).keys() == {"a", "b"}


def test_a_record_with_no_recorded_place_in_a_list_is_a_member_of_it_and_is_not_ranked_by_it():
    # A hit written before places were stored has no rank; the record keeps whatever another list gives it.
    lists = preselect.lists([hit("a", "Q1", None), hit("a", "Q2", 0)])
    assert [(entry["query_text"], entry["size"], entry["members"]) for entry in lists] == [
        ("Q1", 0, ["a"]), ("Q2", 1, ["a"])]
    assert [part["rank"] for part in preselect.scores(lists)["a"]] == [1]


def test_three_middling_lists_outweigh_one_first_place_which_is_why_the_window_keeps_floors():
    """The design's own arithmetic: a record at place 50 of three lists scores 3/(60+50) = 0.0272, a record first in
    one list 1/61 = 0.0164. The second is the single-channel discovery the floors protect."""
    lists = preselect.lists([hit("many", f"Q{i}", 49) for i in range(3)] + [hit("one", "Qx", 0)])
    contributions = preselect.scores(lists)
    total = {head: sum(part["contribution"] for part in parts) for head, parts in contributions.items()}
    assert round(total["many"], 4) == 0.0273 and round(total["one"], 4) == 0.0164
    assert preselect.order(contributions, {}) == ["many", "one"]


def test_equal_sums_are_resolved_by_the_works_own_identifier():
    lists = preselect.lists([hit("a", "Q1", 0), hit("b", "Q1", 0)])  # the same place in the same list
    contributions = preselect.scores(lists)
    assert preselect.order(contributions, {"a": "w-b", "b": "w-a"}) == ["b", "a"]
    assert preselect.order(contributions, {}) == ["a", "b"]  # without a work id, the head's own identifier


def test_a_record_no_list_voted_for_has_no_rrf_place_and_the_window_reaches_it_by_the_fused_order():
    lists = preselect.lists([hit("a", "Q1", 0)])
    ranked = preselect.order(preselect.scores(lists), {})
    assert ranked == ["a"]
    # Two places, one voted record: the second place goes to the fused order's own next record.
    assert preselect.window(2, ["z", "a", "y"], ranked)["window"] == ["a", "z"]


def test_only_a_focused_query_found_it_counts_as_narrow():
    lists = [{"provider": "openalex", "query_text": "main", "members": ["a"], "places": {"a": 0},
              "votes": True, "focused": False},
             {"provider": "openalex", "query_text": "focused", "members": ["a", "b"], "places": {"a": 1, "b": 0},
              "votes": True, "focused": True}]
    assert preselect.narrow_heads(lists) == ["b"]


def test_a_record_a_list_that_casts_no_vote_also_found_is_not_narrow():
    # The main query, ordered by citation count, returned "b" too: "b" has another way in although that list votes
    # for nothing, so it does not take a narrow floor place from a record that has only the focused query.
    lists = [{"provider": "openalex", "query_text": "main", "members": ["b"], "places": {},
              "votes": False, "focused": False},
             {"provider": "openalex", "query_text": "focused", "members": ["b", "c"], "places": {"b": 0, "c": 1},
              "votes": True, "focused": True}]
    assert preselect.narrow_heads(lists) == ["c"]


def test_the_same_query_asked_in_two_orders_is_two_lists_and_only_the_relevance_one_votes():
    lists = preselect.lists([hit("a", "Q", 0), hit("b", "Q", 0, sort="publication_date:desc", relevance=False)])
    assert [(entry["sort"], entry["votes"], entry["members"]) for entry in lists] == [
        (None, True, ["a"]), ("publication_date:desc", False, ["b"])]
    assert preselect.scores(lists).keys() == {"a"}


def test_the_floors_let_a_record_with_no_vote_into_the_window_and_spend_one_place_each():
    fused = ["a", "b", "c", "chain", "narrow"]
    ranked = ["a", "b", "c"]  # the records the query lists ranked; the other two have no vote
    chosen = preselect.window(3, fused, ranked, chain_only=["chain"], narrow_only=["narrow"],
                              quota={"chain_only": 1, "narrow_only": 1})
    assert sorted(chosen["window"]) == ["a", "chain", "narrow"]
    assert chosen["floors"] == {"chain_only": ["chain"], "narrow_only": ["narrow"]}
    # Without the floors the same window holds neither.
    assert preselect.window(3, fused, ranked, chain_only=["chain"], narrow_only=["narrow"])["window"] == ["a", "b", "c"]


def test_a_floor_whose_record_the_votes_reach_anyway_changes_nothing():
    # "chain" leads the votes too, so reserving its place pushes nobody out: the window is the one the votes alone
    # would have chosen, and the floor says which record it holds.
    kept = preselect.window(2, ["chain", "a", "b"], ["chain", "a", "b"], chain_only=["chain"],
                            quota={"chain_only": 1})
    assert kept["window"] == ["chain", "a"] and kept["floors"]["chain_only"] == ["chain"]
    assert kept["window"] == preselect.window(2, ["chain", "a", "b"], ["chain", "a", "b"])["window"]


def test_one_floor_cannot_crowd_out_another():
    """Both floors are reserved before anything is filled, so a window the votes would fill with one floor's records
    still holds the other's: four places, two for each floor."""
    fused = ["n1", "n2", "n3", "c1", "c2"]
    chosen = preselect.window(4, fused, ["n1", "n2", "n3"], chain_only=["c1", "c2"],
                              narrow_only=["n1", "n2", "n3"], quota={"chain_only": 2, "narrow_only": 2})
    assert sorted(chosen["window"]) == ["c1", "c2", "n1", "n2"]
    assert chosen["floors"] == {"chain_only": ["c1", "c2"], "narrow_only": ["n1", "n2"]}


def test_a_record_two_floors_hold_is_reserved_once():
    chosen = preselect.window(3, ["x", "a", "b"], ["a", "b"], chain_only=["x"], narrow_only=["x"],
                              quota={"chain_only": 1, "narrow_only": 1})
    assert chosen["window"] == ["x", "a", "b"] and chosen["floors"] == {"chain_only": ["x"], "narrow_only": []}


def test_the_window_never_grows_past_its_size_and_a_floor_larger_than_it_takes_what_fits():
    chosen = preselect.window(2, ["x", "y", "z"], ["x"], chain_only=["y", "z"], quota={"chain_only": 5})
    assert sorted(chosen["window"]) == ["y", "z"] and len(chosen["window"]) == 2


def test_the_floors_are_read_in_the_order_they_are_given():
    # The caller orders each floor's records; the window takes them from the front of that order.
    chosen = preselect.window(2, ["a", "b", "c", "d"], ["a", "b"], chain_only=["d", "c"],
                              quota={"chain_only": 1})
    assert chosen["floors"]["chain_only"] == ["d"] and "d" in chosen["window"]

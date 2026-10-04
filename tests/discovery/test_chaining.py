"""Citation chaining's pure rules: the seeds, the filter, what is new, and the chain's own order (slice 15, D95).

Rows, titles and abstracts are SYNTHETIC and from two fields (greenhouse irrigation and pallet packing), because the
filter reads the research's own gate blocks and must not know a topic. Passing shows the rules do what the slice says;
it says nothing about how many relevant works a real chain reaches, which the slice's replay and acceptance measure.
"""

from deixis.workflow import chaining, ranking

IRRIGATION = {"setting": ["greenhouse"], "task": ["irrigation scheduling"]}
PACKING = {"setting": ["warehouse"], "task": ["pallet loading"]}


def row(head, work=None, title="SYNTHETIC title", abstract=None, own=(), references=None):
    return {"id": head, "work_id": work or f"wrk_{head}", "title": title, "abstract": abstract,
            "own_ids": frozenset(own), "references": frozenset(references) if references is not None else None}


def forms(blocks):
    return ranking.block_forms(blocks)


def test_seeds_are_the_rankings_code_seeds_plus_the_users_own():
    rows = {f"h{n}": row(f"h{n}", title=f"SYNTHETIC title {n}") for n in range(20)}
    order = [f"h{n}" for n in range(20)]
    user = [row("h3"), row("upload", work="wrk_upload")]  # one in the pool, one the user uploaded
    seeds = chaining.seed_list(order, rows, user)
    code = [seed["source_version_id"] for seed in seeds if seed["kind"] == "code"]
    assert code == [f"h{n}" for n in range(16) if n != 3]  # fifteen, in the order, the user's work skipped
    assert [seed for seed in seeds if seed["kind"] == "user"] == [
        {"source_version_id": "h3", "kind": "user"}, {"source_version_id": "upload", "kind": "user"}]


def test_seeds_are_deduplicated_at_work_level_before_the_count():
    rows = {"a": row("a", title="SYNTHETIC Greenhouse irrigation"), "b": row("b", title="synthetic greenhouse  IRRIGATION!"),
            "c": row("c", work="wrk_a", title="another title"), "d": row("d", title="SYNTHETIC pallet loading")}
    assert chaining.code_seeds(["a", "b", "c", "d"], rows, set(), limit=2) == ["a", "d"]
    assert chaining.code_seeds(["a", "b", "c", "d"], rows, set(), limit=15) == ["a", "d"]
    # A head whose title is a user seed's is that seed under another record, not a code seed of its own.
    assert chaining.code_seeds(["a", "d"], rows, set(), user_titles={chaining.norm_title("SYNTHETIC pallet loading")}) == ["a"]


def test_a_seed_without_an_openalex_id_gets_backward_links_only():
    without_id = {"source_version_id": "s1", "openalex_ids": [], "references": ["W10", "W11"]}
    without_list = {"source_version_id": "s2", "openalex_ids": ["W2"], "references": None}
    empty_list = {"source_version_id": "s3", "openalex_ids": ["W3"], "references": []}
    assert chaining.directions(without_id) == ["backward"]
    assert chaining.directions(without_list) == ["forward"]
    assert chaining.directions(empty_list) == ["forward"]
    assert chaining.backward_batches([without_id, without_list, empty_list], set()) == [["W10", "W11"]]


def test_the_filter_passes_a_setting_or_a_task_form_in_title_or_abstract():
    irrigation, packing = forms(IRRIGATION), forms(PACKING)
    assert chaining.passes(irrigation, "SYNTHETIC greenhouse climate control", "We model the air.")
    assert chaining.passes(irrigation, "SYNTHETIC crop water", "We compare irrigation scheduling rules.")
    assert not chaining.passes(irrigation, "SYNTHETIC crop water", "We compare the soil of two fields.")
    assert chaining.passes(packing, "SYNTHETIC pallet loading with robots", None)
    assert not chaining.passes(packing, "SYNTHETIC greenhouse irrigation scheduling", "Water use of a crop.")
    # A form matches at a word start only, as the ranking's block signal does.
    assert not chaining.passes(packing, "SYNTHETIC nonwarehouse storage", None)


def test_a_work_without_an_abstract_is_judged_on_its_title():
    irrigation = forms(IRRIGATION)
    assert chaining.passes(irrigation, "SYNTHETIC irrigation scheduling of tomato", None)
    assert not chaining.passes(irrigation, "SYNTHETIC tomato yield", None)
    assert not chaining.passes(irrigation, "SYNTHETIC tomato yield", "")


def test_a_linked_work_the_library_already_holds_is_not_chained():
    seeds = [{"source_version_id": "s1", "openalex_ids": ["W1"], "references": ["W5", "W6", "W7"]},
             {"source_version_id": "s2", "openalex_ids": ["W2"], "references": ["W6", "W8"]}]
    # A reference the research holds sends no request.
    assert chaining.backward_batches(seeds, {"W6", "W7"}) == [["W5", "W8"]]
    assert chaining.backward_links(seeds, ["W5", "W8"]) == [("s1", "W5"), ("s2", "W8")]
    # A linked record the record path merged into a keyword work has that work's head, and is not a chained work.
    assert chaining.chained_heads(["k1", "c1", "c2", "c1"], keyword_pool={"k1", "k2"}) == ["c1", "c2"]
    batches = chaining.backward_batches([{"source_version_id": "s", "references": [f"W{n}" for n in range(250)]}], set())
    assert [len(batch) for batch in batches] == [100, 100, 50]


def test_the_chain_ranking_orders_chained_works_only():
    blocks = {"setting": ["greenhouse"], "task": ["irrigation scheduling"]}
    pool = [row("k1", title="SYNTHETIC greenhouse irrigation scheduling", abstract="greenhouse irrigation scheduling"),
            row("k2", title="SYNTHETIC greenhouse lighting", abstract="greenhouse lamps"),
            row("c1", title="SYNTHETIC irrigation scheduling in a greenhouse", abstract="irrigation scheduling"),
            row("c2", title="SYNTHETIC soil water", abstract="a greenhouse crop")]
    ranked = ranking.rank_pool(pool, [], {"greenhouse", "irrigation", "scheduling"}, blocks, None, {})
    order = chaining.chain_order(ranked["order"], {"c1", "c2"})
    assert order == ["c1", "c2"] and set(ranked["order"]) == {"k1", "k2", "c1", "c2"}
    rows = ranking.rank_rows(ranked, keep={"c1", "c2"})
    assert {r["source_version_id"] for r in rows} == {"c1", "c2"}
    assert [r["source_version_id"] for r in rows if r["signal"] == "inspection"] == ["c1", "c2"]
    assert sorted(r["rank"] for r in rows if r["signal"] == "inspection") == [1, 2]  # renumbered among themselves
    # Without `keep` the rows are the keyword ranking's own, every record and every order.
    assert {r["source_version_id"] for r in ranking.rank_rows(ranked)} == {"k1", "k2", "c1", "c2"}

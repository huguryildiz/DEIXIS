"""Citation chaining's pure rules: the filter, what is new, and how a seed's title is compared (slice 15, D95).

Rows, titles and abstracts are SYNTHETIC and from two fields (greenhouse irrigation and pallet packing), because the
filter reads the research's own gate blocks and must not know a topic. Passing shows the rules do what the slice says;
it says nothing about how many relevant works a real chain reaches, which the slice's replay and acceptance measure.
"""

from deixis.workflow import chaining, ranking

IRRIGATION = {"setting": ["greenhouse"], "task": ["irrigation scheduling"]}
PACKING = {"setting": ["warehouse"], "task": ["pallet loading"]}


def forms(blocks):
    return ranking.block_forms(blocks)


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
    assert chaining.backward_links(seeds, ["W5", "W8"]) == [("s1", "W5"), ("s2", "W8")]
    # A linked record the record path merged into a keyword work has that work's head, and is not a chained work.
    assert chaining.chained_heads(["k1", "c1", "c2", "c1"], keyword_pool={"k1", "k2"}) == ["c1", "c2"]


def test_seed_titles_are_compared_case_folded_and_without_punctuation():
    assert chaining.norm_title("SYNTHETIC Greenhouse irrigation") == chaining.norm_title("synthetic greenhouse  IRRIGATION!")
    assert chaining.norm_title(None) == ""

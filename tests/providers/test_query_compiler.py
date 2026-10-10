"""Provider queries compiled from an sw vocabulary's concept blocks (D90).

The SearchPlan v2 compiler (`compile_queries`, D44) and its tests were removed in the clean start (slice 3a); what is
left here is the block fitting every discovery query goes through. Block terms are SYNTHETIC; passing shows which terms
a query keeps and names as dropped, not recall.
"""

from deixis.providers import query_compiler, query_rules


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
    assert len(words) <= query_rules.MAX_PLAIN_WORDS


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

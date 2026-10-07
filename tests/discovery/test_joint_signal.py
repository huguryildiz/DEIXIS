"""The joint signal: records that name two or more of a comparison question's task terms together rank higher (D226).

Records and terms are SYNTHETIC and from two fields; the terms come from the test's blocks, never from a word list in
the code. Passing shows the rule (which forms are looked for, when the signal runs, that a question asking for no
comparison keeps its order), not that the order finds the papers a person would choose.
"""

from deixis.workflow import ranking

TASK = {"setting": ["diffusion channel"], "task": ["pulse-based release", "rate-based release", "release scheduling"]}
FARM = {"setting": ["greenhouse"], "task": ["drip irrigation", "sprinkler irrigation"]}


def row(rid, title, abstract=None):
    return {"id": rid, "work_id": f"wrk_{rid}", "title": title, "abstract": abstract,
            "own_ids": frozenset(), "references": frozenset()}


POOL = [
    row("both_abbreviated", "SYNTHETIC PBR and RBR in a diffusion channel",
        "We compare Pulse Based Release (PBR) with Rate-Based Release (RBR) by their error rates."),
    row("both_in_abstract", "SYNTHETIC error rates in a diffusion channel",
        "Pulse-based release and rate based release schedules are simulated."),
    row("one_term", "SYNTHETIC pulse-based release in a diffusion channel",
        "Pulse based release is tuned for a short channel."),
    row("neither", "SYNTHETIC capacity of a diffusion channel", "The capacity of a diffusion channel is derived."),
    row("other", "SYNTHETIC drip irrigation in a greenhouse", "Drip irrigation saves water."),
]


def test_a_shared_last_word_is_dropped_and_hyphens_read_as_spaces():
    assert ranking.joint_forms(TASK["task"]) == [" pulse based", " rate based", " release scheduling"]
    assert ranking.joint_forms(FARM["task"]) == [" drip", " sprinkler"]
    assert ranking.joint_forms(["release scheduling"]) == [" release scheduling"]


def test_a_title_naming_both_terms_by_their_abbreviations_ranks_first():
    scores = ranking.joint_scores(POOL, ranking.joint_forms(TASK["task"]))
    assert scores["both_abbreviated"][0] == 2 and scores["both_in_abstract"][0] == 0
    assert scores["both_in_abstract"][1] > 0
    assert scores["one_term"] == scores["neither"] == scores["other"] == (0, 0.0)
    order = sorted(scores, key=lambda rid: scores[rid], reverse=True)
    assert order[:2] == ["both_abbreviated", "both_in_abstract"]


def test_the_comparison_words_decide_whether_the_signal_runs():
    assert ranking.comparison_question("How do pulse-based and rate-based release compare in error rate?")
    assert ranking.comparison_question("Is drip irrigation better than sprinkler irrigation?")
    assert ranking.comparison_question("Wie wirkt X?", "What is the difference between X and Y?")
    assert not ranking.comparison_question("What limits the capacity of a diffusion channel?")


def test_a_question_asking_for_no_comparison_keeps_its_order_and_says_why():
    words = {"pulse", "rate", "release", "diffusion", "channel"}
    similarities = {r["id"]: 0.1 * i for i, r in enumerate(POOL)}
    plain = ranking.rank_pool(POOL, [], words, TASK, "m", similarities, compared_terms=None)
    assert "joint" not in plain["ranks"] and plain["reasons"]["joint"] == "not_a_comparison"
    # Without the signal every stored order is what the other signals alone give, as before D226.
    ranks = plain["ranks"]
    assert plain["fused_code"] == ranking.fuse(ranks, ("bm25", "blocks", "tfidf", "graph"))
    assert plain["fused"] == ranking.fuse(ranks, ("bm25", "blocks", "tfidf", "graph", "embedding"))
    assert plain["order"] == plain["fused"]
    assert "rescued" not in plain
    compared = ranking.rank_pool(POOL, [], words, TASK, None, {}, compared_terms=TASK["task"])
    assert "joint" in compared["ranks"]
    assert compared["fused"].index("both_abbreviated") <= plain["fused"].index("both_abbreviated")


def test_one_task_term_is_not_a_comparison_of_terms():
    one = {"setting": ["diffusion channel"], "task": ["release scheduling"]}
    ranked = ranking.rank_pool(POOL, [], {"release"}, one, None, {}, compared_terms=one["task"])
    assert "joint" not in ranked["ranks"] and ranked["reasons"]["joint"] == "fewer_than_two_task_terms"


def test_an_abbreviation_whose_letters_are_not_the_spelled_words_initials_is_not_read():
    mislabeled = row("mislabeled", "SYNTHETIC RBR in a diffusion channel",
                     "Pulse-based release (RBR) is tuned; rate-based release is not studied.")
    scores = ranking.joint_scores([mislabeled, *POOL], ranking.joint_forms(TASK["task"]))
    assert scores["mislabeled"][0] == 0


def test_only_the_approved_task_terms_are_compared():
    class Store:
        @staticmethod
        def english_question(research_id, revision):
            return None

    def term(phrase, block="task", in_query="phrase"):
        return {"phrase": phrase, "root": phrase, "block": block, "in_query": in_query, "dropped": None,
                "and_only": False}

    vocabulary = {"terms": [term("pulse-based release"), term("rate-based release"), term("diffusion channel", "setting")]}
    scope = {"research_id": "r", "revision": 1, "question": "How do pulse-based and rate-based release compare?"}
    assert ranking.joint_terms(Store, scope, vocabulary) == ["pulse-based release", "rate-based release"]
    assert ranking.joint_terms(Store, scope | {"question": "What limits release?"}, vocabulary) is None

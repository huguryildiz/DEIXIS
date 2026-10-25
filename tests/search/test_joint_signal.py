"""The joint signal: records that name two or more of a comparison question's task terms together rank higher (D226).

Records and terms are SYNTHETIC and from two fields; the terms come from the test's blocks, never from a word list in
the code. Passing shows the rule (which forms are looked for, when the signal runs, that a question asking for no
comparison keeps its order), not that the order finds the papers a person would choose.
"""

from deixis.workflow.search import ranking

TASK = {"setting": ["diffusion channel"], "task": ["pulse-based release", "rate-based release", "release scheduling"]}


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

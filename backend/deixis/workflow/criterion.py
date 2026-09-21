"""What three criterion proposals agree on (SW15.1, SW15.2).

The model is asked the same question three times and nothing it says once is used: a phrase enters the criterion
only when at least `PROPOSAL_MAJORITY` of the runs wrote it, and with fewer than that many valid runs there is no
criterion at all. Free text cannot be voted on, so the criterion sentence and the parts come from the one run that
shares the most kept phrases with the consensus; that is a plan decision and its cost is named in D78.

`consensus` is pure: no clock, no randomness, no store. The order the runs arrive in, and the order phrases and
exclusion words arrive in, never reach the result (SW14.6).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

PROPOSAL_RUNS = 3  # SW15.2
PROPOSAL_MAJORITY = 2
THRESHOLDS = {"proposal_runs": PROPOSAL_RUNS, "proposal_majority": PROPOSAL_MAJORITY}
# What one proposal may contain. The contract enforces these; they are here so the schema and the check read
# the same numbers.
PARTS_PER_PROPOSAL = (2, 5)
PHRASES_PER_PART = (6, 15)
MAX_PHRASE_WORDS = 4
MAX_EXCLUSION_TITLE_WORDS = 30

_EDGES = re.compile(r"^\W+|\W+$", re.UNICODE)


def norm(text: str) -> str:
    """One phrase written one way: lower case, single spaces, no punctuation around it.

    Two runs write the same phrase as "packet size", "Packet size" and "(packet size)"; they are one vote, not three.
    """
    return _EDGES.sub("", " ".join(text.lower().split()))


def _holds(word: str, text: str) -> bool:
    """Whether the normalised text holds the word at a word boundary; both sides are already normalised."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def consensus(question: str, runs: dict[int, dict[str, Any]],
              sought_terms: list[str] | None = None) -> dict[str, Any] | None:
    """The criterion the runs agree on, or None when too few of them arrived (SW15.2).

    `runs` maps a run number to the result of a valid proposal; a failed or invalid run is not in it. A phrase kept
    here orders nothing and decides nothing in this slice: it is recorded with the runs that wrote it, so a later
    slice and the user can see what the agreement rested on.
    """
    if len(runs) < PROPOSAL_MAJORITY:
        return None
    ordered = sorted(runs)
    phrases = {number: {p for part in runs[number]["parts"] for phrase in part["phrases"] if (p := norm(phrase))}
               for number in ordered}
    counts = Counter(phrase for number in ordered for phrase in phrases[number])
    kept = {phrase for phrase, count in counts.items() if count >= PROPOSAL_MAJORITY}
    # The base run is the one closest to what the runs agreed on; a tie goes to the run that was asked first.
    base = min(ordered, key=lambda number: (-len(phrases[number] & kept), number))
    proposal = runs[base]

    part_of: dict[str, str] = {}
    for part in proposal["parts"]:
        for phrase in part["phrases"]:
            if (p := norm(phrase)) and p not in part_of:
                part_of[p] = part["name"]

    words = {number: {w for word in runs[number]["exclusion_title_words"] if (w := norm(word))} for number in ordered}
    word_counts = Counter(word for number in ordered for word in words[number])
    voted = sorted(word for word, count in word_counts.items() if count >= PROPOSAL_MAJORITY)
    # SW5.1's protection: a research that asks about surveys may not exclude "survey" from its own titles.
    asked = norm(question)
    dropped = [word for word in voted if all(_holds(part, asked) for part in word.split())]
    return {
        "criterion": proposal["criterion"],
        "parts": [{"name": part["name"], "definition": part["definition"]} for part in proposal["parts"]],
        # A phrase the base run does not hold keeps no part: it was agreed on, but not by the run the parts come from.
        "cue_phrases": [{"phrase": phrase, "part": part_of.get(phrase),
                         "runs": [number for number in ordered if phrase in phrases[number]]}
                        for phrase in sorted(kept)],
        "exclusion_title_words": [word for word in voted if word not in dropped],
        "dropped_exclusion_title_words": dropped,
        "base_run": base,
        "runs_ok": ordered,
        "sought_term_in_criterion": _names_sought(proposal, sought_terms),
    }


def _names_sought(proposal: dict[str, Any], sought_terms: list[str] | None) -> bool | None:
    """Whether the criterion names one of the question's own task terms (the known defect's trace inside the product).

    It is a record and nothing else: no slice reads it to decide anything. None means the research had no task term
    to look for, not that the criterion passed.
    """
    terms = {t for term in (sought_terms or []) if (t := norm(term))}
    if not terms:
        return None
    fields = [norm(proposal["criterion"])]
    fields += [f"{norm(part['name'])} {norm(part['definition'])}" for part in proposal["parts"]]
    return any(term in field for term in terms for field in fields)

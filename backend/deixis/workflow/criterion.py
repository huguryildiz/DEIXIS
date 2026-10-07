"""What three criterion proposals agree on (SW15.1, SW15.2).

The model is asked the same question three times and nothing it says once is used: a phrase enters the criterion
only when at least `PROPOSAL_MAJORITY` of the runs wrote it, and with fewer than that many valid runs there is no
criterion at all. Free text cannot be voted on, so the criterion sentence and the parts come from one run.
D241 first prefers unbundled core definitions, then uses D78's kept-phrase agreement and run-number tie break.

A population or comparator the question names is a part of its own (SW23, D106). A role at least
`PROPOSAL_MAJORITY` runs listed in `question_elements` is required: only a run holding every required role can be the
base run, so the criterion never rests on a run that left out what most runs found in the question. With no required
role, legacy proposals without part roles keep D78's original base choice. A stored v1
proposal has no `question_elements` and reads as naming none.

A v3 part records core or aspect. D241 matches names and literal cue overlap;
roles use distinct-run majority votes, retaining the base role without a majority.
If role resolution removes every core, the base proposal's roles are restored and recorded.
Legacy parts without roles keep their stored shape.

`consensus` is pure: no clock, no randomness, no store. The order the runs arrive in, and the order phrases and
exclusion words arrive in, never reach the result (SW14.6).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

PROPOSAL_RUNS = 3  # SW15.2
PROPOSAL_MAJORITY = 2
MATCH_MIN_SHARED_CUES = 2
MATCH_OVERLAP_DIVISOR = 2
THRESHOLDS = {"proposal_runs": PROPOSAL_RUNS, "proposal_majority": PROPOSAL_MAJORITY,
              "role_consensus_version": 2, "match_min_shared_cues": MATCH_MIN_SHARED_CUES,
              "match_overlap_divisor": MATCH_OVERLAP_DIVISOR}
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


def holds(word: str, text: str) -> bool:
    """Whether the normalised text holds the word at a word boundary; both sides are already normalised."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _cues(part: dict[str, Any]) -> set[str]:
    return {norm(p) for p in part["phrases"] if norm(p)}


def matching_parts(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Lexical correspondence, not a claim of semantic equivalence.

    Two literal shared cues must cover at least half the smaller inventory.
    No transitive clustering: a broad part cannot bridge unrelated parts.
    """
    if norm(left["name"]) == norm(right["name"]):
        return True
    a, b = _cues(left), _cues(right)
    shared = len(a & b)
    return shared >= MATCH_MIN_SHARED_CUES and MATCH_OVERLAP_DIVISOR * shared >= min(len(a), len(b))


def _bundled_aspects(part: dict[str, Any], runs: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect an aspect embedded in a core definition by two distinct multiword cues.

    This bounded lexical guard cannot parse arbitrary conjunctions. It chooses
    an unbundled proposal rather than editing model-owned definitions.
    """
    own = _cues(part)
    definition = norm(part["definition"])
    return [other for run in runs.values() for other in run["parts"]
            if other.get("role") == "aspect" and not matching_parts(part, other)
            and len({cue for cue in _cues(other) - own
                     if len(cue.split()) > 1 and holds(cue, definition)}) >= 2]


def _consensus_role(part: dict[str, Any], runs: dict[int, dict[str, Any]]) -> str:
    matches = [(number, other) for number in sorted(runs) for other in runs[number]["parts"]
               if matching_parts(part, other)]
    votes = {role: len({number for number, other in matches if other.get("role") == role})
             for role in ("core", "aspect")}
    role = part["role"]
    if votes["core"] != votes["aspect"]:
        candidate = max(votes, key=votes.get)
        if votes[candidate] >= PROPOSAL_MAJORITY:
            role = candidate
    if role == "aspect":
        return role
    # Separate inventories inside a composite need separate votes. A composite
    # cannot count as an independent core vote for either of its components.
    components = [other for _, other in matches if len(_cues(part) & _cues(other)) >= 2]
    separated = False
    for left in components:
        for right in components:
            if len(_cues(left) & _cues(right)) > 1:
                continue
            separated = True
            for component, sibling in ((left, right), (right, left)):
                votes = {number for number, other in matches if other.get("role") == "core"
                         and matching_parts(component, other)
                         and len(_cues(sibling) & _cues(other)) <= 1}
                if len(votes) < PROPOSAL_MAJORITY:
                    return "aspect"
    if re.search(r"\band\b|[&+]", norm(part["name"])) and not separated:
        return "aspect"  # Repeated votes for an AND bundle are not component votes.
    return "aspect" if _bundled_aspects(part, runs) else "core"


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
    elements = {number: runs[number].get("question_elements") or [] for number in ordered}
    role_counts = Counter(role for number in ordered for role in {e["role"] for e in elements[number]})
    required = sorted(role for role, count in role_counts.items() if count >= PROPOSAL_MAJORITY)
    eligible = [number for number in ordered if set(required) <= {e["role"] for e in elements[number]}]
    # Two roles each held by two of three runs share at least one run (2 + 2 - 3 = 1); with two runs both hold both.
    assert eligible, "no run holds every required role"
    phrases = {number: {p for part in runs[number]["parts"] for phrase in part["phrases"] if (p := norm(phrase))}
               for number in ordered}
    counts = Counter(phrase for number in ordered for phrase in phrases[number])
    kept = {phrase for phrase, count in counts.items() if count >= PROPOSAL_MAJORITY}
    # The base run is the one closest to what the runs agreed on; a tie goes to the run that was asked first.
    # Prefer a proposal whose core definitions do not embed separately proposed
    # aspects. Keep the original phrase agreement and run-number tie break.
    base = min(eligible, key=lambda number: (
        sum(bool(_bundled_aspects(part, runs)) for part in runs[number]["parts"]
            if part.get("role") == "core"
            and norm(part["name"]) not in {norm(e["part"]) for e in elements[number]}),
        -len(phrases[number] & kept), number))
    proposal = runs[base]

    # Free-text parts and definitions remain owned by one proposal. Population
    # and study-level comparator requirements retain D235's exception.
    protected = {norm(e["part"]) for e in elements[base]}
    parts = []
    for part in proposal["parts"]:
        row = {"name": part["name"], "definition": part["definition"]}
        if "role" in part:
            row["role"] = ("core" if norm(part["name"]) in protected
                           else _consensus_role(part, runs))
        parts.append(row)

    role_fallback = any("role" in part for part in parts) and not any(part.get("role") == "core" for part in parts)
    if role_fallback:
        # Valid role-bearing proposals contain a core. Disagreement must not
        # silently remove the inclusion gate; retain the selected proposal.
        for row, part in zip(parts, proposal["parts"]):
            if "role" in part:
                row["role"] = part["role"]

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
    dropped = [word for word in voted if all(holds(part, asked) for part in word.split())]
    return {
        "criterion": proposal["criterion"],
        "parts": parts,
        # A phrase the base run does not hold keeps no part: it was agreed on, but not by the run the parts come from.
        "cue_phrases": [{"phrase": phrase, "part": part_of.get(phrase),
                         "runs": [number for number in ordered if phrase in phrases[number]]}
                        for phrase in sorted(kept)],
        "exclusion_title_words": [word for word in voted if word not in dropped],
        "dropped_exclusion_title_words": dropped,
        "base_run": base,
        "runs_ok": ordered,
        "sought_term_in_criterion": _names_sought(proposal, sought_terms),
        "question_elements": sorted(({"role": e["role"], "words": e["words"], "part": e["part"]} for e in elements[base]),
                                    key=lambda e: e["role"]),
        "required_roles": required,
        **({"role_fallback": True} if role_fallback else {}),
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

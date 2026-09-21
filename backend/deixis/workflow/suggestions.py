"""Other names for the search phrases, asked of a model only when the user presses the button (SW2.5, slice 08c).

Pure: no network, no store, no clock. The model is given the searched phrases of the approval's proposal and returns
names it says the literature uses for the same things; nothing here decides that it is right. Two filters stand in
front of every proposal and neither is this module's opinion: code drops what cannot enter a query at all (a phrase
the proposal already holds, one that carries a claim or an exclusion phrase, one that is too long, a repeat), the
flow counts what is left with the same probe the first round used, and the user adds the ones they want. A proposal
nobody added is searched by nothing.

Nothing is edited in place (SW14.2): the whole proposed list stays on record with a reason beside each dropped row,
so added, not added and dropped can be read apart afterwards. The row order is canonical — the anchor's place in the
vocabulary, then the phrase — so the order the model happened to write its list in reaches no screen and no query
(SW14.6).
"""

from __future__ import annotations

from typing import Any

from deixis.domain.rules import MAX_SUGGESTED_TERMS
from deixis.providers.query_compiler import quoted
from deixis.workflow.approval import MAX_TERM_WORDS, proposal_blocks
from deixis.workflow.criterion import norm
from deixis.workflow.vocabulary import GATE_BLOCKS

# The proposal's phrases that are not searched, in the order the card shows them. A proposal carrying one of these
# is dropped: the search keeps them out deliberately (SW1.3).
AVOID_FIELDS = ("claim_words", "exclusion_words", "outcome_terms")
# Why a proposal cannot enter the query, in the order the reasons are tried. Only the first one is recorded.
DROP_REASONS = ("too_long", "already_present", "contains_claim_word", "contains_exclusion_word", "duplicate",
                "zero_results", "anchor_not_searched")


def anchors(vocabulary: dict[str, Any]) -> list[dict[str, Any]]:
    """The searched phrases a proposal may be another name for, in the order the vocabulary was built in.

    A dropped phrase is here too and is the most useful anchor of all: a phrase no record holds is the one the field
    most probably calls something else. `records` is the count that phrase was probed at, or null when no count was
    read — which is not zero.
    """
    return [{"phrase": term["phrase"], "block": term["block"], "records": term["phrase_count"]}
            for term in vocabulary["terms"] if term["block"] in GATE_BLOCKS]


def target(question: str, vocabulary: dict[str, Any]) -> dict[str, Any]:
    """The StepInput target of one term-suggestion call.

    The user's draft corrections are not in it: they live in the browser alone, so the model sees the proposal as it
    was stored (named as an open point in the slice file).
    """
    return {"question_text": question, "phrases": anchors(vocabulary),
            "avoid": [phrase for field in AVOID_FIELDS for phrase in vocabulary.get(field) or []],
            "max_terms": MAX_SUGGESTED_TERMS}


def _contains(phrase: str, other: str) -> bool:
    """Whether the phrase holds the other one as a contiguous run of whole words. Both are normalised."""
    words, run = phrase.split(), other.split()
    return bool(run) and any(words[i:i + len(run)] == run for i in range(len(words) - len(run) + 1))


def screen(vocabulary: dict[str, Any], proposed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The proposed names as card rows, each with the block of its anchor and the reason it cannot be searched.

    The block is the anchor's, never the model's: the step is given no block field, so a name enters the block of the
    phrase it is another name for and the user moves it from there like any other term. A row is not removed when it
    is dropped; it stays with its reason and carries no action on the card.
    """
    given = anchors(vocabulary)
    place = {anchor["phrase"]: index for index, anchor in enumerate(given)}
    blocks = {anchor["phrase"]: anchor["block"] for anchor in given}
    rows = [{"phrase": norm(term["phrase"]), "synonym_of": term["synonym_of"],
             "block": blocks[term["synonym_of"]], "phrase_count": None, "dropped": None}
            # A `synonym_of` outside the anchors is refused by the contract before this runs; skipping it here only
            # keeps this function total.
            for term in proposed if term["synonym_of"] in place]
    rows.sort(key=lambda row: (place[row["synonym_of"]], row["phrase"]))

    present = proposal_blocks(vocabulary)
    claims = [norm(phrase) for phrase in vocabulary.get("claim_words") or []]
    exclusions = [norm(phrase) for phrase in vocabulary.get("exclusion_words") or []]
    seen: set[str] = set()
    for row in rows:
        phrase = row["phrase"]
        row["dropped"] = (
            "too_long" if len(phrase.split()) > MAX_TERM_WORDS else
            "already_present" if phrase in present else
            "contains_claim_word" if any(_contains(phrase, word) for word in claims) else
            "contains_exclusion_word" if any(_contains(phrase, word) for word in exclusions) else
            "duplicate" if phrase in seen else None)
        seen.add(phrase)
    return rows


def carry(vocabulary: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An earlier approval's rows, judged again against the proposal they are about to be shown on.

    A later run of the same question need not build the same phrases — the block labelling is a model's — so a row
    that could be added then may now repeat a term, carry a claim phrase, or name an anchor that is no longer
    searched (`anchor_not_searched`). Such a row stays on the list with its reason, so a reapplied correction still
    reads its `model` origin from it. A count already read is kept and never asked for again.
    """
    given = {anchor["phrase"] for anchor in anchors(vocabulary)}
    counts = {row["phrase"]: row["phrase_count"] for row in reversed(rows) if row["phrase_count"] is not None}
    judged = screen(vocabulary, [row for row in rows if row["synonym_of"] in given])
    for row in judged:
        if not row["dropped"]:
            row["phrase_count"] = counts.get(row["phrase"])
            row["dropped"] = "zero_results" if row["phrase_count"] == 0 else None
    return judged + [row | {"dropped": "anchor_not_searched"} for row in rows if row["synonym_of"] not in given]


def known_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """The counts these rows already read, keyed by the query that read them.

    The key is `build_vocabulary`'s own phrase query, so a proposal the user adds is rebuilt without being counted a
    second time. A row whose count could not be read is not here: an unread count is not a zero.
    """
    return {quoted(row["phrase"]): row["phrase_count"] for row in rows if row["phrase_count"] is not None}


def model_phrases(rows: list[dict[str, Any]]) -> set[str]:
    """The normalised phrases whose term origin is `model` once the user adds one of them.

    Dropped rows are in it as well: a user who types a dropped proposal by hand still added something the model
    proposed, and the stored zero count drops it again in the rebuild.
    """
    return {row["phrase"] for row in rows}

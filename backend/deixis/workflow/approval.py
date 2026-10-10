"""What the protocol approval records about the proposed vocabulary and criterion (SW2.6, SW14.2).

Pure: no network, no store, no clock. Since the clean start nobody corrects the proposal before the search (decision
B): the approval step records it as it stands, and these are the facts the step, the protocol body and the run view
read from it.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.domain.canonical import sha256_hex
from deixis.workflow.criterion import norm

SIDE_LISTS = {"claim": "claim_words", "exclusion": "exclusion_words", "outcome": "outcome_terms"}


def proposal_rows(vocabulary: dict[str, Any]) -> list[dict[str, str]]:
    """Every phrase of the proposal with the block it sits in, in the order the vocabulary was built in.

    A dropped term is here too: it is part of what the proposal holds, and the count that dropped it is stored.
    """
    default = "key_terms" if vocabulary["block_assignment"] == "user" else "question"
    rows = [{"phrase": term["phrase"], "block": term["block"], "origin": term["origin"]}
            for term in vocabulary["terms"]]
    for block, field in SIDE_LISTS.items():
        # A body rebuilt from a partial record may carry only the fields that body needs, so a missing side list is
        # an empty one here rather than a failure to build the protocol.
        rows += [{"phrase": phrase, "block": block, "origin": default} for phrase in vocabulary.get(field) or []]
    return rows


def block_origins(vocabulary: dict[str, Any]) -> dict[str, str]:
    """Who put each phrase in its block: the code rule, the model's labelling step, the model that wrote the query
    (D92) or the user's own key terms (SW17.6, SW2.6)."""
    default = {"user": "user", "search_query": "search_query"}.get(vocabulary["block_assignment"], "rule")
    origins = {row["phrase"]: default for row in proposal_rows(vocabulary)}
    origins |= {record["phrase"]: record["origin"]
                for record in (vocabulary.get("labelling") or {}).get("phrases", [])}
    return origins


def proposal_hash(vocabulary: dict[str, Any], criterion: dict[str, Any] | None) -> str:
    """A digest of what the proposal holds: the phrases, their blocks and the criterion fields.

    The counts are left out on purpose. They are what the literature held on the day of the first run and change on
    their own, so two runs of the same question proposed the same thing even when the numbers moved.
    """
    return sha256_hex({
        "terms": sorted([norm(row["phrase"]), row["block"]] for row in proposal_rows(vocabulary)),
        "criterion": None if criterion is None else {
            "criterion": criterion["criterion"],
            "parts": [[part["name"], part["definition"]] for part in criterion["parts"]],
            "cue_phrases": sorted([norm(c["phrase"]), c["part"] or ""] for c in criterion["cue_phrases"]),
            "exclusion_title_words": sorted(criterion["exclusion_title_words"]),
        },
    })


def exclusion_words_in_question(question: str, criterion: dict[str, Any] | None) -> list[str]:
    """Exclusion title words the question itself uses. It is a mark on the approval, never a removal (SW5.1)."""
    asked = norm(question)
    return sorted(word for word in (criterion or {}).get("exclusion_title_words", [])
                  if all(re.search(rf"\b{re.escape(part)}\b", asked) for part in word.split()))

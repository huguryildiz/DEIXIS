"""Which answers an extra model reads for claim support, decided by code from the stored draft.

The design asks for a reviewer from a separate model family under four conditions: the person's own request, a
numerical comparison, conflicting findings, and a detailed result resting on abstracts alone. Three of them are
read here from the answer the model already wrote; the fourth is the person's own action and is recorded where the
person asks for it, never computed.

Three rules hold the module together:

- **A model never decides whether it is reviewed.** The conditions are the draft's own stored fields: the claim
  text, the limitation kinds the contract allows, and the reading depth of each cited passage. Nothing here asks a
  model, so what a review was opened for can be read back rather than guessed at.
- **Wide first, narrow after a measurement.** One number with a direction word is enough for a comparison, and any
  claim whose every cited passage is an abstract is enough for the abstract condition. A condition wrongly fired
  costs one review call; a condition wrongly missed lets an unchecked number stand as evidence. The thresholds are
  deliberately loose and are not tuned: the pilot counts both the catches and the false alarms first.
- **An answer with no claims is never reviewed.** The review step reads claims against their passages and writes no
  result when there are none, so a decision to review such an answer could never be completed.
"""

from __future__ import annotations

import re
from typing import Any

RULE = "review_trigger_v1"

PERSON_ASKED = "person_asked"
NUMERIC_COMPARISON = "numeric_comparison"
CONFLICTING_EVIDENCE = "conflicting_evidence"
ABSTRACT_ONLY_SUPPORT = "abstract_only_support"
# The order a decision records them in, so two readings of the same answer name the conditions the same way.
TRIGGERS = (PERSON_ASKED, NUMERIC_COMPARISON, CONFLICTING_EVIDENCE, ABSTRACT_ONLY_SUPPORT)

# A number, a percentage or a multiplication sign: the quantity half of a comparison.
_NUMBER = re.compile(r"[0-9]|%|×")
# The direction half. A percentage alone is not a comparison ("20 % of the participants"), so a quantity counts only
# beside one of these words or signs ("20 % higher", "%20 daha yüksek").
_DIRECTION = re.compile(
    r"\b(?:than|times|versus|vs\.?|compared\s+(?:with|to)|relative\s+to|outperform\w*"
    # Words of change, in any form ("improved 10 %", "a 10 % improvement", "increased by 10 %"): a number beside one
    # of them is a quantity given against another, whether or not the other is written out.
    r"|(?:improv|reduc|increas|decreas|rais|gain|drop|grew|growth|fell|rose)\w*"
    # Comparative adjectives, which carry a comparison on their own ("20 % higher"). 'more' and 'less' are left out:
    # they stand beside a plain count far more often than beside a comparison, and 'more than' is caught by 'than'.
    r"|higher|lower|greater|smaller|faster|slower|better|worse|longer|shorter|larger|fewer"
    r"|arttı|artmıştır|azaldı|azalmıştır|yükseldi|düştü"
    r"|kat|göre|oranla|kıyasla|daha\s+(?:fazla|az|yüksek|düşük|iyi|kötü|hızlı|yavaş|uzun|kısa))\b"
    # One number given against another ("from 70 % to 80 %"): the two quantities are the comparison.
    r"|\bfrom\s+\S*[0-9]\S*\s*%?\s+to\s+\S*[0-9]"
    r"|[<>≥≤]", re.IGNORECASE)


def compares(text: str) -> bool:
    """Whether one claim's text states a numerical comparison: a quantity and a direction word together."""
    return bool(_NUMBER.search(text) and _DIRECTION.search(text))


def abstract_only(claim: dict[str, Any], passage_kinds: dict[str, str]) -> bool:
    """Whether every passage this claim cites is an abstract.

    A claim citing no passage is not abstract-only, and a passage whose kind is unknown leaves the claim out: the
    condition is "all of them are abstracts", which an unread kind cannot establish.
    """
    passage_ids = claim.get("passage_ids") or []
    return bool(passage_ids) and all(passage_kinds.get(pid) == "abstract" for pid in passage_ids)


def fired(draft: dict[str, Any], passage_kinds: dict[str, str]) -> tuple[str, ...]:
    """The automatic conditions this answer draft meets, in `TRIGGERS` order.

    `passage_kinds` maps a passage id to its stored kind ('abstract', 'pdf_page', 'section'). `person_asked` is
    never returned here: the person's request is recorded where the person makes it.
    """
    claims = draft.get("claims") or []
    if not claims:
        return ()
    met = set()
    for claim in claims:
        if compares(claim.get("text") or ""):
            met.add(NUMERIC_COMPARISON)
        if abstract_only(claim, passage_kinds):
            met.add(ABSTRACT_ONLY_SUPPORT)
    if any((limit or {}).get("kind") == CONFLICTING_EVIDENCE for limit in (draft.get("limitations") or [])):
        met.add(CONFLICTING_EVIDENCE)
    return tuple(trigger for trigger in TRIGGERS if trigger in met)

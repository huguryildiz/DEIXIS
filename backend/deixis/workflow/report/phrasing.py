"""Phrasebank checks for report prose.

`repair_section` belongs in this module but is deferred until
`ResearchFlow._model_step` can carry a `report_target` through `_step_input`.
"""

from __future__ import annotations

from typing import Any

from deixis.domain import phrasebank


def flagged_sentences(section_id: str, claims: list[dict[str, Any]],
                      phrasebank_text: str, language: str) -> list[dict[str, Any]]:
    """Return report sentences that follow no frame assigned to their section."""
    sections = phrasebank.REPORT_PHRASEBANK_SECTIONS[section_id]
    if not sections:
        return []
    fields: list[tuple[str, str, str]] = []
    insufficient_index = 0
    for claim in claims:
        if "text" in claim:
            fields.append((claim["claim_key"], claim["text"], claim["support_type"]))
        for entry in claim.get("insufficient_evidence", []):
            insufficient_index += 1
            fields.append((f"insufficient_evidence.{insufficient_index}", entry["reason"], "analyst_inference"))
        if "reason" in claim and "text" not in claim:
            insufficient_index += 1
            fields.append((f"insufficient_evidence.{insufficient_index}", claim["reason"], "analyst_inference"))

    flagged = []
    for claim_key, text, support_type in fields:
        claim_sentences = phrasebank.sentences(text)
        for index, sentence in enumerate(claim_sentences):
            if phrasebank.unframed(sentence, phrasebank_text, language, sections=sections):
                flagged.append({
                    "sentence_id": f"{claim_key}#{index + 1}",
                    "text": sentence,
                    "support_type": support_type,
                    "nearest_frames": phrasebank.nearest_frames(
                        sentence, phrasebank_text, language, sections=sections, k=3,
                    ),
                    "previous_sentence": claim_sentences[index - 1] if index else None,
                    "next_sentence": claim_sentences[index + 1] if index + 1 < len(claim_sentences) else None,
                })
    return flagged

"""The words and phrases the survey rule reads, and nothing else (SW5.1).

Data only, so the rule and the lists it reads are reviewed apart. The lists are field-independent: no word of a
subject enters them, and the research whose own question uses one of these words drops it for that research
(`survey.title_words`). They are the lists the SW5 probe measured on one topic
(`.local/quantum-source-comparison-2026-09-18/survey_metadata.py`), not a wider guess.
"""

from __future__ import annotations

STRONG_TITLE_WORDS = ("survey", "review", "overview", "tutorial", "roadmap", "primer", "taxonomy",
                      "state of the art", "systematic mapping", "bibliometric")
# The abstract names itself a survey. These are the patterns the SW5 probe measured, not a wider guess.
ABSTRACT_SELF_DESCRIPTIONS = (
    r"this (survey|review|tutorial|overview)", r"we (survey|review)\b", r"in this (survey|review)",
    r"comprehensive (survey|review|overview)",
    r"this (paper|article|work|chapter) (surveys|reviews|provides an overview|presents a (survey|review|comprehensive))",
    r"literature review")
# Weak title words (recent advances, trends, challenges, perspective, vision, future directions, open problems) are
# deliberately absent: they flag nothing on their own (SW5.2) and the combined rule with 80 references was refused.

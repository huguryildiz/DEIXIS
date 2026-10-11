"""The answer report as DOCX blocks: the browser's Markdown download (AnswerBlock.tsx `markdown`) block for block.

Same title line, notices, sections, citation labels, limits, cited passages and closing sentence, in the same order and
language. Two additions: under each cited passage the stored anchor quote of every claim that cites it, verbatim
(different quotes of one passage are never merged), because a Word file cannot open the passage the way the app does;
and every limitation under Limits, including the access ones the screen shows with the PDF upload suggestions.
Nothing is recomputed: claims, citations, locators and anchors come from the stored answer as the research view
returns it.
"""

from __future__ import annotations

from typing import Any

from deixis.exports import ooxml
from deixis.exports.text import OCR_LABEL, VERDICTS, CitationStyle, Language, file_base, locator_text, page_locator, \
    reference_text, translator


def filename(title: str, version: int) -> str:
    return f"{file_base(title, 'deixis-report')}-v{version}.docx"


def blocks(answer: dict[str, Any], sources: list[dict[str, Any]], *, title: str, version: int,
           language: Language, style: CitationStyle) -> list[ooxml.Block]:
    t = translator(language)
    claims = answer.get("claims") or []
    refs: dict[str, tuple[int, dict[str, Any]]] = {}
    anchors: dict[str, list[str]] = {}
    for claim in claims:
        for evidence in claim.get("evidence") or []:
            refs.setdefault(evidence["passage_id"], (len(refs) + 1, evidence))
            # Each claim's link keeps its own quote; quotes of one passage are never merged, only exact repeats.
            quotes = anchors.setdefault(evidence["passage_id"], [])
            if evidence.get("anchor_text") and evidence["anchor_text"] not in quotes:
                quotes.append(evidence["anchor_text"])

    def cite_label(claim: dict[str, Any], evidence: dict[str, Any]) -> str:
        if not evidence.get("source_key"):
            return str(refs[evidence["passage_id"]][0])
        repeated = sum(e["source_version_id"] == evidence["source_version_id"] for e in claim["evidence"]) > 1
        if not repeated:
            return evidence["source_key"]
        place = (t("abstract") if evidence.get("kind") == "abstract"
                 else page_locator(t, evidence["physical_page"], evidence.get("rendition")) if evidence.get("physical_page")
                 else t("section"))
        return f"{evidence['source_key']}, {place}"

    sections: list[tuple[str | None, list[dict[str, Any]]]] = []
    for claim in claims:
        if sections and sections[-1][0] == claim.get("section"):
            sections[-1][1].append(claim)
        else:
            sections.append((claim.get("section"), [claim]))
    # The screen shows access limitations inside the PDF upload suggestions and the Markdown leaves them out of Limits;
    # this file has no suggestions block, so every limitation is listed.
    limits = answer.get("limitations") or []

    out: list[ooxml.Block] = [ooxml.heading(0, title), ooxml.paragraph(f"{t('Report')} · V{version}")]
    if answer.get("applicability") == "stale_scope":
        out.append(ooxml.paragraph(t("This answer was produced for revision {n} of the question and is not applied to the current revision.",
                                     n=answer["scope_revision"]), style="Quote"))
    if answer.get("applicability") == "stale_selection":
        out.append(ooxml.paragraph(t("Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added."),
                                   style="Quote"))
    if answer.get("capability_notice"):
        out.append(ooxml.paragraph(answer["capability_notice"], style="Quote"))
    for section, members in sections:
        if section:
            out.append(ooxml.heading(2, section))
        for claim in members:
            citations = "".join(f"[{cite_label(claim, e)}]" for e in claim.get("evidence") or [])
            parts: list[ooxml.Inline] = [claim["text"]]
            if citations:
                parts.append(f" {citations}")
            if claim.get("support_type") == "analyst_inference":
                parts += [" ", ooxml.Run(f"({t('interpretation')})", italic=True)]
            review = claim.get("review")
            if review:
                reason = f"{t(VERDICTS.get(review['verdict'], review['verdict']))} — {review['reason']}"
                parts += [" ", ooxml.Run(t("Reviewer: {reason}", reason=reason), italic=True)]
            out.append(ooxml.paragraph(*parts))
    if not claims:
        out.append(ooxml.paragraph(t("No claim could be linked to the passages given to the model.")))
    if answer.get("unanswered_aspects"):
        out += [ooxml.heading(2, t("Not answered by the inspected passages")),
                ooxml.bullets([item] for item in answer["unanswered_aspects"])]
    if limits:
        out += [ooxml.heading(2, t("Limits")),
                ooxml.bullets([ooxml.Run(f"{t(item['kind'].replace('_', ' ', 1))}:", bold=True), f" {item['text']}"]
                              for item in limits)]
    if refs:
        out.append(ooxml.heading(2, t("Cited passages")))
        for passage_id, (number, evidence) in refs.items():
            source = next((s for s in sources if s["source_version_id"] == evidence["source_version_id"]), None)
            reference = reference_text(style, source) if source else evidence.get("title") or ""
            key = evidence.get("source_key")
            line = f"[{number if key is None else key}] {reference} — {locator_text(t, evidence)}"
            if evidence.get("text_source") == "ocr":
                line += f" ({t(OCR_LABEL)})"
            if evidence.get("text_source") == "latex_source":
                line += f" ({t('arXiv source')})"
            out.append(ooxml.paragraph(line, *(ooxml.Run(f"\n“{quote}”") for quote in anchors[passage_id])))
    out += [ooxml.Rule(), ooxml.paragraph(t("Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked."))]
    return out

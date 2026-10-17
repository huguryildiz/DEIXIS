"""The answer report as DOCX blocks: the browser's Markdown download (AnswerBlock.tsx `markdown`) block for block.

Same title line, notices, sections, citation labels, limits, cited passages and closing sentence, in the same order and
language. Two additions: under each cited passage the stored anchor quote of every claim that cites it, verbatim
(different quotes of one passage are never merged), because a Word file cannot open the passage the way the app does;
every limitation under Limits, including the access ones the screen shows with the PDF upload suggestions; and the
screen's notice that a PDF the answer read was replaced, removed or re-extracted since.
Nothing is recomputed: claims, citations, locators and anchors come from the stored answer as the research view
returns it.
"""

from __future__ import annotations

from typing import Any

from deixis.exports import ooxml
from deixis.exports.text import OCR_LABEL, VERDICTS, CitationStyle, Language, download_name, locator_text, page_locator, \
    in_text_citation, number_text, reference_text, translator


def filename(title: str, version: int, revision: int = 0) -> str:
    # An update the application wrote over a version (D57) is named V2.1, V2.2, so its file never takes V2's name.
    return download_name(title, f"V{version}" + (f".{revision}" if revision else ""), extension="docx", fallback="Report")


# reportMarkdown.ts `LEDGER_REASONS`: the evidence ledger's reasons (D80) in words.
LEDGER_REASONS = {
    "no_answering_content": "Its given passages do not answer the question",
    "off_topic": "Not about the subject of the question",
    "same_finding_as_cited": "Same finding as a cited work",
    "different_conditions": "Answers part of the question under other conditions",
    "claim_limit": "Left out to stay within the 30-claim limit",
}


def ledger_ok(ledger: Any) -> bool:
    """reportMarkdown.ts `ledgerOk`: the view's ledger has its lists and fields, and given splits into disjoint cited,
    excluded and unaccounted works. Anything else is left out of the file rather than miscounted."""
    def work(item: Any) -> bool:
        return isinstance(item, dict) and isinstance(item.get("source_version_id"), str) and "title" in item \
            and isinstance(item["title"], (str, type(None)))

    if not isinstance(ledger, dict):
        return False
    given, cited, excluded, unaccounted = (ledger.get(k) for k in ("given", "cited", "excluded", "unaccounted"))
    if not all(isinstance(v, list) for v in (given, cited, excluded, unaccounted)):
        return False
    if not (all(map(work, given)) and all(map(work, unaccounted)) and all(isinstance(s, str) for s in cited) and all(
            work(e) and isinstance(e.get("reason"), str) and e["reason"] in LEDGER_REASONS and isinstance(e.get("note"), str)
            and (e.get("same_as") is None or work(e["same_as"])) for e in excluded)):
        return False
    ids = [g["source_version_id"] for g in given]
    parts = [*cited, *(e["source_version_id"] for e in excluded), *(u["source_version_id"] for u in unaccounted)]
    return len(set(ids)) == len(ids) and len(set(parts)) == len(parts) and set(parts) == set(ids)


def ledger_blocks(ledger: dict[str, Any], t: Any, language: Language) -> list[ooxml.Block]:
    """reportMarkdown.ts: the count line and the works given but not cited (title · reason · the model's note)."""
    def n(value: int) -> str:
        return number_text(value, language)

    line = t("{c} of {m} given works cited · {k} left out with a reason",
             c=n(len(ledger["cited"])), m=n(len(ledger["given"])), k=n(len(ledger["excluded"])))
    if ledger["unaccounted"]:
        line += f" · {t('{u} with no reason recorded', u=n(len(ledger['unaccounted'])))}"
    rows = []
    for entry in ledger["excluded"]:
        reason = t(LEDGER_REASONS[entry["reason"]])
        if entry["reason"] == "same_finding_as_cited" and (entry.get("same_as") or {}).get("title"):
            reason += f": {entry['same_as']['title']}"
        rows.append([entry["title"] or entry["source_version_id"], reason, t("Note from the model: {note}", note=entry["note"])])
    rows += [[u["title"] or u["source_version_id"], t("No reason was recorded for this work.")] for u in ledger["unaccounted"]]
    out: list[ooxml.Block] = [ooxml.heading(2, t("Works given but not cited")), ooxml.paragraph(line)]
    if rows:
        out.append(ooxml.bullets([" · ".join(row)] for row in rows))
    return out


def blocks(answer: dict[str, Any], sources: list[dict[str, Any]], *, title: str, version: int | str,
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

    # As reportMarkdown.ts: IEEE cites by the passage's number in brackets (UI parity S10, R25); the other styles in
    # parentheses, in the style's own author-date form, else by the source key, else by the number in brackets.
    def citation(claim: dict[str, Any], evidence: dict[str, Any]) -> str:
        number = f"[{refs[evidence['passage_id']][0]}]"
        if style == "ieee":
            return number
        repeated = sum(e["source_version_id"] == evidence["source_version_id"] for e in claim["evidence"]) > 1
        place = None if not repeated else (
            t("abstract") if evidence.get("kind") == "abstract"
            else page_locator(t, evidence["physical_page"], evidence.get("rendition")) if evidence.get("physical_page")
            else t("section"))
        source = next((s for s in sources if s["source_version_id"] == evidence["source_version_id"]), None)
        styled = in_text_citation(style, source, place) if source else None
        if styled:
            return f"({styled})"
        if not evidence.get("source_key"):
            return number
        return f"({evidence['source_key']}, {place})" if place else f"({evidence['source_key']})"

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
    if answer.get("source_text_changed"):
        # The screen's notice (AnswerBlock.tsx), in its place; the Markdown download leaves it out.
        out.append(ooxml.paragraph(t("A PDF this answer read was replaced, removed or had its text extracted again after the answer was generated. Its quotes still open the text that was read; generate a new answer to read the current text."),
                                   style="Quote"))
    if answer.get("capability_notice"):
        out.append(ooxml.paragraph(answer["capability_notice"], style="Quote"))
    for section, members in sections:
        if section:
            out.append(ooxml.heading(2, section))
        for claim in members:
            citations = "".join(citation(claim, e) for e in claim.get("evidence") or [])
            parts: list[ooxml.Inline] = [*ooxml.with_math(claim["text"])]
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
                ooxml.bullets(ooxml.with_math(item) for item in answer["unanswered_aspects"])]
    if ledger_ok(answer.get("evidence_ledger")):
        out += ledger_blocks(answer["evidence_ledger"], t, language)
    if limits:
        out += [ooxml.heading(2, t("Limits")),
                ooxml.bullets([ooxml.Run(f"{t(item['kind'].replace('_', ' ', 1))}:", bold=True), *ooxml.with_math(f" {item['text']}")]
                              for item in limits)]
    if refs:
        out.append(ooxml.heading(2, t("Cited passages")))
        for passage_id, (number, evidence) in refs.items():
            source = next((s for s in sources if s["source_version_id"] == evidence["source_version_id"]), None)
            reference = reference_text(style, source) if source else evidence.get("title") or ""
            key = None if style == "ieee" else evidence.get("source_key")
            line = f"[{number if key is None else key}] {reference} — {locator_text(t, evidence)}"
            if evidence.get("text_source") == "ocr":
                line += f" ({t(OCR_LABEL)})"
            if evidence.get("text_source") == "latex_source":
                line += f" ({t('arXiv source')})"
            if evidence.get("text_source") == "equation_ocr":
                line += f" ({t('equations read by Mathpix')})"
            out.append(ooxml.paragraph(line, *(ooxml.Run(f"\n“{quote}”") for quote in anchors[passage_id]), style="Bibliography"))
    out += [ooxml.Rule(), ooxml.paragraph(t("Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked."))]
    return out

"""Markdown rendering of the report read model, without recomputing citations."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from deixis.domain.rules import RevisionConflict
from deixis.workflow.report.store import DISPLAY_ORDER, ReportStore
from deixis.workflow.report.review_methodology import failed_reason_text
from deixis.workflow.store import NotFound, Store

MEDIA_TYPES = {"markdown": "text/markdown; charset=utf-8"}

HEADINGS = {
    "abstract": ("Abstract", "Özet"), "index_terms": ("Index Terms", "Dizin Terimleri"),
    "I": ("I. Introduction", "I. Giriş"), "II": ("II. Review Methodology", "II. İnceleme Yöntemi"),
    "III": ("III. Background and Taxonomy", "III. Arka Plan ve Sınıflandırma"),
    "IV": ("IV. Literature Synthesis", "IV. Literatür Sentezi"),
    "V": ("V. Comparative Findings", "V. Karşılaştırmalı Bulgular"),
    "VI": ("VI. Candidate Unanswered Aspects", "VI. Cevaplanmamış Yön Adayları"),
    "VII": ("VII. Future Directions", "VII. Gelecek Yönelimler"),
    "VIII": ("VIII. Limitations and Threats to Validity", "VIII. Sınırlılıklar ve Geçerlilik Tehditleri"),
    "IX": ("IX. Conclusion", "IX. Sonuç"),
}
REVIEW_CODES = {
    "support_broken": ("Support no longer matches", "Destek artık uyuşmuyor"),
    "count_error": ("Count", "Sayı"), "terminology_inconsistent": ("Terminology", "Terim kullanımı"),
    "abstract_body_mismatch": ("Abstract and body differ", "Özet ve gövde farklı"),
    "equation_mismatch": ("Equation", "Denklem"), "comparability_error": ("Comparability", "Karşılaştırılabilirlik"),
    "other": ("Other", "Diğer"),
}
REVIEW_REASONS = {
    "input_too_large": ("the input was too large", "girdi çok büyüktü"),
    "budget_exhausted": ("the model-call budget was exhausted", "model çağrısı bütçesi tükendi"),
    "nothing_to_review": ("there was nothing it could read", "okuyabileceği bir şey yoktu"),
    "model_mismatch": ("the model did not match the selected model", "yanıt veren model seçilen modelle eşleşmedi"),
    "model_call_failed": ("the model call failed", "model çağrısı başarısız oldu"),
    "invalid_model_output": ("the model output was invalid", "model çıktısı geçersizdi"),
}


def _md(value: Any) -> str:
    """Keep stored text on one line and stop it from creating Markdown structure.

    Paired dollar spans retain their delimiters; an unmatched dollar is plain text.
    """
    source = " ".join(str(value if value is not None else "").split())
    if not source:
        return ""
    result: list[str] = []
    index = 0
    while index < len(source):
        if source[index] == "$":
            delimiter = "$$" if source.startswith("$$", index) else "$"
            end = source.find(delimiter, index + len(delimiter))
            if end >= 0:
                content = source[index + len(delimiter):end]
                # Backticks inside math are literal content, not Markdown structure.
                content = content.translate(str.maketrans({"<": r"{\lt}", ">": r"{\gt}",
                                                          "[": "{[}", "]": "{]}"}))
                result.append(delimiter + content + delimiter)
                index = end + len(delimiter)
                continue
        char = source[index]
        result.append("\\" + char if char in "\\[]<>`|" else char)
        index += 1
    escaped = "".join(result)
    if re.match(r"(?:[#\-+*]|\d+[.)])", source):
        escaped = "\\" + escaped
    return escaped


def _label(text: str, tr: bool, turkish: str) -> str:
    return turkish if tr else text


def _value_text(value: dict[str, Any] | None, options: list[dict[str, Any]] | None, tr: bool) -> str:
    if not value:
        return ""
    if isinstance(value.get("text"), str):
        return value["text"]
    if isinstance(value.get("number"), (int, float)):
        return " ".join(str(part) for part in (value["number"], value.get("unit")) if part is not None and part != "")
    if value.get("answer") in ("yes", "no"):
        return _label(value["answer"].capitalize(), tr, "Evet" if value["answer"] == "yes" else "Hayır")
    if isinstance(value.get("option_ids"), list):
        by_id = {option["id"]: option["label"] for option in options or []}
        return ", ".join(by_id.get(item, item) for item in value["option_ids"])
    return ""


def _table(table: dict[str, Any], tr: bool) -> str:
    def table_cell(value: str) -> str:
        value = value.replace("\n", " ")
        result: list[str] = []
        index = 0
        while index < len(value):
            if value[index] == "$":
                delimiter = "$$" if value.startswith("$$", index) else "$"
                end = value.find(delimiter, index + len(delimiter))
                if end >= 0:
                    content = value[index + len(delimiter):end]
                    math: list[str] = []
                    offset = 0
                    while offset < len(content):
                        if content.startswith("\\\\", offset):
                            math.append("\\\\")
                            offset += 2
                        elif content.startswith("\\|", offset):
                            math.append(r"{\Vert}")
                            offset += 2
                        elif content[offset] == "|":
                            math.append(r"{\vert}")
                            offset += 1
                        else:
                            math.append(content[offset])
                            offset += 1
                    result.append(delimiter + "".join(math) + delimiter)
                    index = end + len(delimiter)
                    continue
            result.append(value[index])
            index += 1
        return "".join(result)

    columns = table["columns"]
    rows = table["rows"]
    if tr:
        caption = f"TABLO I. Bu rapor için dondurulan kanıt tablosu ({len(rows)} kaynak, {len(columns)} sütun)."
        if len(columns) == 1:
            caption = f"TABLO I. Bu rapor için dondurulan kanıt tablosu ({len(rows)} kaynak, 1 sütun)."
    else:
        unit = "1 column" if len(columns) == 1 else f"{len(columns)} columns"
        caption = f"TABLE I. Evidence table as frozen for this report ({len(rows)} sources, {unit})."
    lines = [caption, "", "| " + " | ".join(table_cell(cell) for cell in
             [_md(_label("Source", tr, "Kaynak")), *(_md(c["name"]) for c in columns)]) + " |",
             "| " + " | ".join(["---"] * (len(columns) + 1)) + " |"]
    cells = {(cell["source_version_id"], cell["column_id"]): cell for cell in table["cells"]}
    for row in rows:
        source = _md(row.get("source_key") or row.get("title") or _label("Source record unavailable", tr, "Kaynak kaydı bulunamadı"))
        if row.get("ref_number") is not None:
            source = f'[{row["ref_number"]}] {source}'
        values = [source]
        for column in columns:
            cell = cells.get((row["source_version_id"], column["column_id"]))
            if cell is None:
                values.append("—")
            elif cell["state"] == "value":
                values.append(_md(_value_text(cell.get("value"), column.get("options"), tr)))
            elif cell["state"] == "not_verified":
                value = _md(_value_text(cell.get("value"), column.get("options"), tr))
                values.append(f"{value} ({_label('not verified: no quote linked', tr, 'doğrulanmadı: bağlı alıntı yok')})")
            else:
                values.append(_md(cell["state"].replace("_", " ")))
        lines.append("| " + " | ".join(table_cell(value) for value in values) + " |")
    return "\n".join(lines)


def _review_note(view: dict[str, Any], tr: bool) -> str:
    review = view.get("review")
    if not review:
        return _label(
            "No model or person review is recorded for this report; whether each passage supports its claim was not checked by code.",
            tr, "Bu rapor için model veya kişi incelemesi kaydedilmedi; kod, her pasajın ilgili iddiayı destekleyip desteklemediğini denetlemedi.")
    if review["status"] == "not_reviewed":
        reason = REVIEW_REASONS.get(review.get("reason"), ("the review step failed", "inceleme adımı başarısız oldu"))[int(tr)]
        return _label(
            f"No accepted review result exists for this report ({reason}); whether the model read it in part is not established by this record.",
            tr, f"Bu rapor için kabul edilmiş bir inceleme sonucu yok ({reason}); modelin raporun bir kısmını okuyup okumadığı bu kayıttan anlaşılamıyor.")
    read = review["sections_reviewed"]
    missed = review["sections_not_reviewed"]
    findings = review["findings"]
    n, m, k = len(read), len(read) + len(missed), len(findings)
    if tr:
        parts = [f"Raporu yazan model, ek bir inceleme çağrısında {m} bölümün {n} tanesindeki iddiaları atıf yapılan pasaj ve hücrelerle karşılaştırıp {k} olası sorun işaretledi. Bu, modelin okumasıdır; hakem incelemesi değildir ve hataları kaçırabilir. Kod, her pasajın ilgili iddiayı destekleyip desteklemediğini denetlemedi."]
    else:
        noun = "problem" if k == 1 else "problems"
        parts = [f"A model read the claims of {n} of {m} sections against their cited passages and cells in an extra review call using the same model that wrote the report, and flagged {k} possible {noun}. That is a model’s reading, not peer review, and it can miss errors; whether each passage supports its claim was not checked by code."]
    reverted = len(review["reverted"])
    if reverted:
        if tr:
            parts.append(f"Model, yeniden yazılan {reverted} cümlenin kaynaklarıyla artık uyuşmayabileceğini işaretledi; {'cümle' if reverted == 1 else 'cümleler'} özgün hâline döndürüldü.")
        else:
            parts.append(f"The model flagged {reverted} rewritten {'sentence' if reverted == 1 else 'sentences'} as possibly no longer matching {'its' if reverted == 1 else 'their'} sources; {'it was' if reverted == 1 else 'they were'} returned to {'its' if reverted == 1 else 'their'} original wording.")
    if missed:
        names = ", ".join(_md(HEADINGS.get(item["section_id"], (item["section_id"], item["section_id"]))[int(tr)]) for item in missed)
        parts.append(f"{'Okunmayan bölümler' if tr else 'Not read'}: {names}.")
    return " ".join(parts)


def _edit_note(view: dict[str, Any], tr: bool) -> list[str]:
    edited = view.get("edited_after_version")
    if not view.get("has_human_edits", edited is not None):
        return []
    check = view.get("edit_check")
    if check is None:
        text = (_label(f"Edited by hand after version {edited}; edited text was not checked again.", tr,
                       f"{edited}. sürümden sonra elle düzenlendi; düzenlenen metin yeniden denetlenmedi.")
                if edited is not None else _label("Edited by hand; edited text was not checked again.", tr,
                                                 "Elle düzenlendi; düzenlenen metin yeniden denetlenmedi."))
        return [text, ""]
    date = _md(check["created_at"])
    prefix = (f"{edited}. sürümden sonra elle düzenlendi" if edited is not None else "Elle düzenlendi") if tr else (
        "Edited by hand" + (f" after version {edited}" if edited is not None else ""))
    if check["current"]:
        text = _label(
            f"{prefix}; the edited text was checked by code rules ({date}): {check['errors']} errors, "
            f"{check['warnings']} warnings; whether the cited evidence supports each sentence was not checked.", tr,
            f"{prefix}; düzenlenen metin kod kurallarıyla denetlendi ({date}): {check['errors']} hata, "
            f"{check['warnings']} uyarı; atıf yapılan kanıtın her cümleyi destekleyip desteklemediği denetlenmedi.")
    else:
        text = _label(
            f"{prefix}; the last check ({date}) does not cover the current inputs; "
            "whether the cited evidence supports each sentence was not checked.", tr,
            f"{prefix}; son denetim ({date}) güncel girdileri kapsamıyor; "
            "atıf yapılan kanıtın her cümleyi destekleyip desteklemediği denetlenmedi.")
    lines = [text, ""]
    for item in check["items"]:
        lines.append(f"- {_md(item['section_id'])} · {_md(item['rule'])} ({_md(item['severity'])}): {_md(item['detail'])}")
    lines.extend(["", _label("Not checked:", tr, "Denetlenmedi:")])
    for item in check["skipped_rules"]:
        lines.append(f"- {_md(item['section_id'])} · {_md(item['claim_key'])}: {_md(item['rule'])} ({_md(item['reason'])})")
    limits = {"semantic_support": ("whether the cited evidence supports each sentence", "atıf yapılan kanıtın her cümleyi destekleyip desteklemediği"),
              "numbers_written_as_words": ("numbers written as words", "sözcükle yazılmış sayılar"),
              "passages": ("passages", "pasajlar")}
    lines.extend(f"- {_md(limits[value][int(tr)] if value in limits else value)}" for value in check["not_checked"])
    lines.append("")
    return lines


def to_markdown(view: dict[str, Any], *, title: str, corpus: dict[str, int] | None) -> str:
    tr = str(view.get("language", "")).startswith("tr")
    draft = view["status"] == "draft"
    lines: list[str] = []
    if draft:
        count = sum(section["status"] != "valid" for section in view["sections"])
        draft_line = _label(f'DRAFT: {count} sections not validated.', tr, f'TASLAK: {count} bölüm doğrulanmadı.')
        if count == 0:
            error = (view.get("run") or {}).get("error")
            rules = list(dict.fromkeys(
                item["rule"] for item in error if isinstance(item, dict) and isinstance(item.get("rule"), str)
                and not (item["rule"].endswith("_warning") and isinstance(item.get("detail"), str)
                         and item["detail"].startswith("WARNING:"))
            )) if isinstance(error, list) else []
            names = {"banned_word": ("banned word", "yasak sözcük"), "empty_section": ("empty section", "boş bölüm"),
                     "corpus_count_mismatch": ("corpus count mismatch", "korpus sayısı uyuşmazlığı"),
                     "citation_anchor_unmatched": ("unlocated citation quote", "konumu bulunamayan atıf alıntısı"),
                     "anchor_not_in_cell_evidence": ("quote missing from cell evidence", "alıntı hücre kanıtında yok"),
                     "anchor_not_in_passage": ("quote missing from passage", "alıntı pasajda yok")}
            reason = ", ".join(names[rule][int(tr)] if rule in names else rule.replace("_", " ") for rule in rules[:3])
            if len(rules) > 3:
                reason += _label(f" and {len(rules) - 3} more", tr, f" ve {len(rules) - 3} kural daha")
            if reason:
                draft_line = _label(f"DRAFT: the assembly check refused the report ({reason}).", tr,
                                    f"TASLAK: birleştirme kontrolü raporu reddetti ({reason}).")
        lines.extend([f"> {_md(draft_line)}", ""])
    lines.extend([f"# {_md(title)}", _label("Evidence report · draft" if draft else f'Evidence report · V{view["report_version"]}',
                                          tr, "Kanıt raporu · taslak" if draft else f'Kanıt raporu · V{view["report_version"]}'), ""])
    missing = view.get("missing_rows")
    if missing:
        counts = missing["counts"]
        lines.extend([_label(
            f"{counts['failed']} of {counts['included']} sources did not complete the table (missing cells: {counts['cells_missing']}). "
            "These rows were excluded from the report's evidence assessment and aggregation denominators.", tr,
            f"{counts['included']} kaynağın {counts['failed']} tanesinde tablo doldurma tamamlanmadı; {counts['cells_missing']} hücre eksik. "
            "Bu satırlar raporun kanıt değerlendirmesine ve toplulaştırma paydalarına alınmadı."), ""])
        lines.extend(f"- {_md(row['source_key'] or row['title'])}: {_md(failed_reason_text(row['reason'], 'tr' if tr else 'en'))}"
                     for row in missing["failed_rows"])
        lines.append("")
    lines.extend(_edit_note(view, tr))
    if view.get("evidence_changes", {}).get("any"):
        lines.extend([_label("Evidence changed after this report was written; the report text was not changed. Passage text was not checked.",
                             tr, "Bu rapor yazıldıktan sonra kanıt değişti; rapor metni değişmedi. Pasaj metni denetlenmedi."), ""])

    sections = sorted(view["sections"], key=lambda item: DISPLAY_ORDER.index(item["section_id"])
                      if item["section_id"] in DISPLAY_ORDER else len(DISPLAY_ORDER))
    equations: dict[str, int] = {}
    for section in sections:
        for claim in section["claims"]:
            ref = claim.get("equation_ref")
            if ref and ref not in equations:
                equations[ref] = len(equations) + 1
    for section in sections:
        sid = section["section_id"]
        heading = HEADINGS.get(sid, (sid, sid))[int(tr)]
        lines.extend([f"## {_md(heading)}", ""])
        if section["status"] in ("draft", "failed"):
            lines.extend([f"> {_label('This section was not validated and must be written again.', tr, 'Bu bölüm doğrulanmadı ve yeniden yazılmalı.')}", ""])
        if sid == "VI":
            lines.extend([_label("Candidate aspects the model inferred from the evidence table; none was checked by a kill-search.",
                                 tr, "Modelin kanıt tablosundan çıkardığı aday yönler; hiçbiri kapsamlı bir yoklama aramasıyla denetlenmedi."), ""])
        claims = section["claims"]
        has_table_ref = any(claim.get("table_ref") == "TABLE_I" for claim in claims)
        table = view.get("table_i") if sid == "IV" else None
        if table and not has_table_ref:
            lines.extend([_table(table, tr), ""])
        if sid in ("II", "VIII") and section.get("draft") and section["draft"].get("text"):
            lines.extend([_md(section["draft"]["text"]), ""])
        paragraphs = dict.fromkeys(claim["paragraph"] for claim in claims)
        first_table_paragraph = next((claim["paragraph"] for claim in claims if claim.get("table_ref") == "TABLE_I"), None)
        for paragraph in paragraphs:
            fragments = []
            for claim in (claim for claim in claims if claim["paragraph"] == paragraph):
                fragment = _md(claim["text"])
                if claim.get("equation_ref"):
                    fragment += f' ({equations[claim["equation_ref"]]})'
                links = list(dict.fromkeys(link["ref_number"] for link in claim["evidence"]))
                if links:
                    fragment += " " + ", ".join(f"[{number}]" for number in links)
                fragments.append(fragment)
            lines.extend([" ".join(fragments), ""])
            if table and paragraph == first_table_paragraph:
                lines.extend([_table(table, tr), ""])
        if not claims and not (sid in ("II", "VIII") and (section.get("draft") or {}).get("text")):
            reasons = (section.get("draft") or {}).get("insufficient_evidence") or []
            if reasons:
                for entry in reasons:
                    lines.extend([f"{_label('Not enough evidence', tr, 'Yeterli kanıt yok')}: {_md(entry['reason'])}", ""])
            else:
                lines.extend([_label("No text was written for this section.", tr, "Bu bölüm için metin yazılmadı."), ""])

    lines.extend([f"## {_label('References', tr, 'Kaynaklar')}", ""])
    for ref in view["references"]:
        authors = ", ".join(_md(author) for author in ref["authors"])
        fields = [part for part in (authors, _md(ref["title"])) if part]
        fields.extend(_md(ref[key]) for key in ("venue", "year") if ref.get(key))
        if ref.get("doi"):
            fields.append(f'DOI: {_md(ref["doi"])}')
        if ref.get("version_label"):
            fields.append(f'({_md(ref["version_label"])})')
        lines.extend([f'[{ref["number"]}] ' + ", ".join(fields), ""])
    if corpus is None:
        lines.extend([_label("Generated by DEIXIS.", tr, "DEIXIS ile üretildi."), ""])
    else:
        counts = ", ".join(f"{corpus[key]} {word}" for key, word in (("found", "found"), ("unique", "unique"),
                        ("screened", "screened"), ("included", "included"), ("full_text", "with full text")))
        footer = f"Generated by DEIXIS; corpus: {counts}."
        if tr:
            footer = (f"DEIXIS ile üretildi; korpus: bulunan {corpus['found']}, tekil {corpus['unique']}, "
                      f"taranan {corpus['screened']}, dahil {corpus['included']}, tam metinli {corpus['full_text']}.")
        lines.extend([footer, ""])
    links = [link for section in view["sections"] for claim in section["claims"] for link in claim["evidence"]]
    located = sum(link.get("anchor_match") is not None for link in links)
    removed_claims = sum(claim.get("evidence_basis") == "none" and claim.get("support_type_note") is not None
                         for section in view["sections"] for claim in section["claims"])
    anchor = _label("Anchors were located in the cited passages or cells.", tr,
                    "Atıf çapaları ilgili pasajlarda veya hücrelerde bulundu.") if located == len(links) else _label(
                        f"{located} of {len(links)} citation anchors were located in their passages or cells; the others open without a mark.",
                        tr, f"{len(links)} atıf çapasının {located} tanesi ilgili pasajlarda veya hücrelerde bulundu; diğerleri işaretsiz açılır.")
    if not links and removed_claims:
        anchor = _label("No citation anchors remain after citations were removed by hand.", tr,
                        "Atıflar elle kaldırıldıktan sonra hiçbir atıf çapası kalmadı.")
    if removed_claims:
        anchor += _label(f" {removed_claims} claims have no direct citations after citations were removed by hand.", tr,
                         f" Atıflar elle kaldırıldıktan sonra {removed_claims} iddianın doğrudan atfı kalmadı.")
    review_note = _review_note(view, tr)
    if (view.get("review") or {}).get("status") == "reviewed":
        review_note += _label(" The review covers the model's base version; human edits were not reviewed.", tr,
                              " İnceleme modelin temel sürümünü kapsar; insan düzenlemeleri incelenmedi.")
    lines.extend([f"{anchor} {review_note}", ""])
    review = view.get("review")
    if review and review["status"] == "reviewed" and review["findings"]:
        lines.extend([_label("Model findings", tr, "Model bulguları"), ""])
        for finding in review["findings"]:
            sid = finding.get("section_id")
            section_label = HEADINGS.get(sid, (sid, sid))[int(tr)] if sid else _label("Report", tr, "Rapor")
            code_label = REVIEW_CODES.get(finding["code"], REVIEW_CODES["other"])[int(tr)]
            lines.append(f'- {_md(section_label)} · {_md(code_label)} · {_md(finding["text"])}')
    return "\n".join(lines).rstrip("\n") + "\n"


def export_markdown(store: Store, research_id: str, report_id: str) -> tuple[str, str]:
    from deixis.workflow.views import report_view

    view = report_view(store, research_id, report_id)
    if view["status"] == "in_progress" or (view["run"] and view["run"]["status"] not in ("completed", "failed", "cancelled")):
        raise RevisionConflict("The report is still being written")
    title = store.research(research_id)["title"]
    try:
        corpus = ReportStore(store).snapshot(report_id)["corpus"]
    except NotFound:
        corpus = None
    slug = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:60].rstrip("-") or "report"
    suffix = "draft" if view["status"] == "draft" else f'v{view["report_version"]}'
    return to_markdown(view, title=title, corpus=corpus), f"report-{slug}-{suffix}.md"

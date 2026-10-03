"""Shared bilingual report words with the original escape boundaries.

Review and edit notes escape pieces inside sentences; draft sentences are escaped
as a whole by the writer. Both must survive byte for byte. A callback keeps one
copy of the words while each format supplies its own escape. PLAIN text is written
raw, WHOLE text is escaped by the caller, and PIECEWISE results are final.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Callable

from deixis.domain.rules import RevisionConflict
from deixis.workflow.report.review_methodology import failed_reason_text

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


def is_turkish(view: dict[str, Any]) -> bool:
    """helper: Select Turkish by the recorded language prefix."""
    return str(view.get("language", "")).startswith("tr")


def pick(english: str, tr: bool, turkish: str) -> str:
    """helper: Select one of two raw strings."""
    return turkish if tr else english


def heading(section_id: str, tr: bool) -> str:
    """WHOLE: Return a raw heading or the stored section id."""
    return HEADINGS.get(section_id, (section_id, section_id))[int(tr)]


def references_heading(tr: bool) -> str:
    """PLAIN: Return the fixed references heading."""
    return pick("References", tr, "Kaynaklar")


def report_identity(view: dict[str, Any], tr: bool) -> str:
    """PLAIN: Return the draft or numbered report identity."""
    draft = view["status"] == "draft"
    return pick("Evidence report · draft" if draft else f'Evidence report · V{view["report_version"]}',
                tr, "Kanıt raporu · taslak" if draft else f'Kanıt raporu · V{view["report_version"]}')


def draft_line(view: dict[str, Any], tr: bool) -> str | None:
    """WHOLE: Return the raw draft sentence, including stored rule names."""
    if view["status"] != "draft":
        return None
    count = sum(section["status"] != "valid" for section in view["sections"])
    text = pick(f'DRAFT: {count} sections not validated.', tr, f'TASLAK: {count} bölüm doğrulanmadı.')
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
            reason += pick(f" and {len(rules) - 3} more", tr, f" ve {len(rules) - 3} kural daha")
        if reason:
            text = pick(f"DRAFT: the assembly check refused the report ({reason}).", tr,
                        f"TASLAK: birleştirme kontrolü raporu reddetti ({reason}).")
    return text


def section_unvalidated_note(tr: bool) -> str:
    """PLAIN: Return the unvalidated-section sentence."""
    return pick('This section was not validated and must be written again.', tr,
                'Bu bölüm doğrulanmadı ve yeniden yazılmalı.')


def vi_preface(tr: bool) -> str:
    """PLAIN: Return the candidate-aspects evidence boundary."""
    return pick("Candidate aspects the model inferred from the evidence table; none was checked by a kill-search.",
                tr, "Modelin kanıt tablosundan çıkardığı aday yönler; hiçbiri kapsamlı bir yoklama aramasıyla denetlenmedi.")


def missing_rows_sentence(missing: dict[str, Any], tr: bool) -> str:
    """PLAIN: Return counts and denominator exclusion without escaping."""
    counts = missing["counts"]
    return pick(
        f"{counts['failed']} of {counts['included']} sources did not complete the table (missing cells: {counts['cells_missing']}). "
        "These rows were excluded from the report's evidence assessment and aggregation denominators.", tr,
        f"{counts['included']} kaynağın {counts['failed']} tanesinde tablo doldurma tamamlanmadı; {counts['cells_missing']} hücre eksik. "
        "Bu satırlar raporun kanıt değerlendirmesine ve toplulaştırma paydalarına alınmadı.")


def missing_row_fields(row: dict[str, Any], tr: bool, esc: Callable[[Any], str]) -> tuple[str, str]:
    """PIECEWISE: Escape the source and rendered reason separately."""
    return esc(row['source_key'] or row['title']), esc(failed_reason_text(row['reason'], 'tr' if tr else 'en'))


@dataclass(frozen=True)
class EditNote:
    """Final text pieces; writers own list syntax, separators and blank lines."""

    paragraph: str
    items: tuple[tuple[str, str, str, str], ...] = ()
    not_checked_heading: str | None = None
    skipped_rules: tuple[tuple[str, str, str, str], ...] = ()
    not_checked: tuple[str, ...] = ()


def edit_note(view: dict[str, Any], tr: bool, esc: Callable[[Any], str]) -> EditNote | None:
    """PIECEWISE: Escape dates, item fields and each complete limit string."""
    edited = view.get("edited_after_version")
    if not view.get("has_human_edits", edited is not None):
        return None
    check = view.get("edit_check")
    if check is None:
        text = (pick(f"Edited by hand after version {edited}; edited text was not checked again.", tr,
                     f"{edited}. sürümden sonra elle düzenlendi; düzenlenen metin yeniden denetlenmedi.")
                if edited is not None else pick("Edited by hand; edited text was not checked again.", tr,
                                               "Elle düzenlendi; düzenlenen metin yeniden denetlenmedi."))
        return EditNote(text)
    date = esc(check["created_at"])
    prefix = (f"{edited}. sürümden sonra elle düzenlendi" if edited is not None else "Elle düzenlendi") if tr else (
        "Edited by hand" + (f" after version {edited}" if edited is not None else ""))
    if check["current"]:
        text = pick(
            f"{prefix}; the edited text was checked by code rules ({date}): {check['errors']} errors, "
            f"{check['warnings']} warnings; whether the cited evidence supports each sentence was not checked.", tr,
            f"{prefix}; düzenlenen metin kod kurallarıyla denetlendi ({date}): {check['errors']} hata, "
            f"{check['warnings']} uyarı; atıf yapılan kanıtın her cümleyi destekleyip desteklemediği denetlenmedi.")
    else:
        text = pick(
            f"{prefix}; the last check ({date}) does not cover the current inputs; "
            "whether the cited evidence supports each sentence was not checked.", tr,
            f"{prefix}; son denetim ({date}) güncel girdileri kapsamıyor; "
            "atıf yapılan kanıtın her cümleyi destekleyip desteklemediği denetlenmedi.")
    items = tuple((esc(item['section_id']), esc(item['rule']), esc(item['severity']), esc(item['detail']))
                  for item in check["items"])
    skipped = tuple((esc(item['section_id']), esc(item['claim_key']), esc(item['rule']), esc(item['reason']))
                    for item in check["skipped_rules"])
    limits = {"semantic_support": ("whether the cited evidence supports each sentence", "atıf yapılan kanıtın her cümleyi destekleyip desteklemediği"),
              "numbers_written_as_words": ("numbers written as words", "sözcükle yazılmış sayılar"),
              "passages": ("passages", "pasajlar")}
    not_checked = tuple(esc(limits[value][int(tr)] if value in limits else value) for value in check["not_checked"])
    return EditNote(text, items, pick("Not checked:", tr, "Denetlenmedi:"), skipped, not_checked)


def evidence_changed_sentence(tr: bool) -> str:
    """PLAIN: Return the evidence-change boundary."""
    return pick("Evidence changed after this report was written; the report text was not changed. Passage text was not checked.",
                tr, "Bu rapor yazıldıktan sonra kanıt değişti; rapor metni değişmedi. Pasaj metni denetlenmedi.")


def passage_freshness_sentence(tr: bool, affected: int, unresolved: int) -> str:
    """PLAIN: Disclose identity comparison without claiming semantic support."""
    if tr:
        unknown = f"; {unresolved} pasaj çözümlenemedi" if unresolved else ""
        return (f"Pasaj güncelliği karşılaştırıldı: bu raporda kullanılan {affected} pasaj artık PDF'lerinin güncel metni değil"
                f"{unknown}. Anlamsal destek denetlenmedi.")
    unknown = f"; {unresolved} could not be resolved" if unresolved else ""
    return (f"Passage freshness compared: {affected} passage(s) this report used are no longer the current text of their PDF"
            f"{unknown}. Semantic support was not checked.")


def no_text_sentence(tr: bool) -> str:
    """PLAIN: Return the empty-section sentence."""
    return pick("No text was written for this section.", tr, "Bu bölüm için metin yazılmadı.")


def not_enough_evidence_label(tr: bool) -> str:
    """PLAIN: Return the insufficient-evidence label."""
    return pick('Not enough evidence', tr, 'Yeterli kanıt yok')


def table_caption(table: dict[str, Any], tr: bool) -> str:
    """PLAIN: Return the caption from row and column counts only."""
    columns, rows = table["columns"], table["rows"]
    if tr:
        caption = f"TABLO I. Bu rapor için dondurulan kanıt tablosu ({len(rows)} kaynak, {len(columns)} sütun)."
        if len(columns) == 1:
            caption = f"TABLO I. Bu rapor için dondurulan kanıt tablosu ({len(rows)} kaynak, 1 sütun)."
    else:
        unit = "1 column" if len(columns) == 1 else f"{len(columns)} columns"
        caption = f"TABLE I. Evidence table as frozen for this report ({len(rows)} sources, {unit})."
    return caption


def source_heading(tr: bool) -> str:
    """WHOLE: Return the raw source label for the writer to escape."""
    return pick("Source", tr, "Kaynak")


def value_text(value: dict[str, Any] | None, options: list[dict[str, Any]] | None, tr: bool) -> str:
    """WHOLE: Format a raw stored value without escaping."""
    if not value:
        return ""
    if isinstance(value.get("text"), str):
        return value["text"]
    if isinstance(value.get("number"), (int, float)):
        return " ".join(str(part) for part in (value["number"], value.get("unit")) if part is not None and part != "")
    if value.get("answer") in ("yes", "no"):
        return pick(value["answer"].capitalize(), tr, "Evet" if value["answer"] == "yes" else "Hayır")
    if isinstance(value.get("option_ids"), list):
        by_id = {option["id"]: option["label"] for option in options or []}
        return ", ".join(by_id.get(item, item) for item in value["option_ids"])
    return ""


def source_cell(row: dict[str, Any], tr: bool, esc: Callable[[Any], str]) -> str:
    """PIECEWISE: Escape the source label before adding a reference prefix."""
    source = esc(row.get("source_key") or row.get("title") or pick("Source record unavailable", tr, "Kaynak kaydı bulunamadı"))
    if row.get("ref_number") is not None:
        source = f'[{row["ref_number"]}] {source}'
    return source


def cell_text(cell: dict[str, Any] | None, column: dict[str, Any], tr: bool, esc: Callable[[Any], str]) -> str:
    """PIECEWISE: Escape the value or state; keep the fixed suffix raw."""
    if cell is None:
        return "—"
    if cell["state"] == "value":
        return esc(value_text(cell.get("value"), column.get("options"), tr))
    if cell["state"] == "not_verified":
        value = esc(value_text(cell.get("value"), column.get("options"), tr))
        return f"{value} ({pick('not verified: no quote linked', tr, 'doğrulanmadı: bağlı alıntı yok')})"
    return esc(cell["state"].replace("_", " "))


def corpus_footer(corpus: dict[str, int] | None, tr: bool) -> str:
    """PLAIN: Return the generator footer and optional five corpus counts."""
    if corpus is None:
        return pick("Generated by DEIXIS.", tr, "DEIXIS ile üretildi.")
    counts = ", ".join(f"{corpus[key]} {word}" for key, word in (("found", "found"), ("unique", "unique"),
                    ("screened", "screened"), ("included", "included"), ("full_text", "with full text")))
    footer = f"Generated by DEIXIS; corpus: {counts}."
    if tr:
        footer = (f"DEIXIS ile üretildi; korpus: bulunan {corpus['found']}, tekil {corpus['unique']}, "
                  f"taranan {corpus['screened']}, dahil {corpus['included']}, tam metinli {corpus['full_text']}.")
    return footer


def anchor_note(view: dict[str, Any], tr: bool) -> str:
    """PLAIN: Return anchor counts and the citation-removal sentences."""
    links = [link for section in view["sections"] for claim in section["claims"] for link in claim["evidence"]]
    located = sum(link.get("anchor_match") is not None for link in links)
    removed_claims = sum(claim.get("evidence_basis") == "none" and claim.get("support_type_note") is not None
                         for section in view["sections"] for claim in section["claims"])
    anchor = pick("Anchors were located in the cited passages or cells.", tr,
                  "Atıf çapaları ilgili pasajlarda veya hücrelerde bulundu.") if located == len(links) else pick(
                      f"{located} of {len(links)} citation anchors were located in their passages or cells; the others open without a mark.",
                      tr, f"{len(links)} atıf çapasının {located} tanesi ilgili pasajlarda veya hücrelerde bulundu; diğerleri işaretsiz açılır.")
    if not links and removed_claims:
        anchor = pick("No citation anchors remain after citations were removed by hand.", tr,
                      "Atıflar elle kaldırıldıktan sonra hiçbir atıf çapası kalmadı.")
    if removed_claims:
        anchor += pick(f" {removed_claims} claims have no direct citations after citations were removed by hand.", tr,
                       f" Atıflar elle kaldırıldıktan sonra {removed_claims} iddianın doğrudan atfı kalmadı.")
    return anchor


def review_note(view: dict[str, Any], tr: bool, esc: Callable[[Any], str]) -> str:
    """PIECEWISE: Escape unread section names; keep fixed reasons raw."""
    review = view.get("review")
    if not review:
        return pick(
            "No model or person review is recorded for this report; whether each passage supports its claim was not checked by code.",
            tr, "Bu rapor için model veya kişi incelemesi kaydedilmedi; kod, her pasajın ilgili iddiayı destekleyip desteklemediğini denetlemedi.")
    if review["status"] == "not_reviewed":
        reason = REVIEW_REASONS.get(review.get("reason"), ("the review step failed", "inceleme adımı başarısız oldu"))[int(tr)]
        return pick(
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
        names = ", ".join(esc(heading(item["section_id"], tr)) for item in missed)
        parts.append(f"{'Okunmayan bölümler' if tr else 'Not read'}: {names}.")
    note = " ".join(parts)
    if review["status"] == "reviewed":
        note += pick(" The review covers the model's base version; human edits were not reviewed.", tr,
                     " İnceleme modelin temel sürümünü kapsar; insan düzenlemeleri incelenmedi.")
    return note


def findings_heading(tr: bool) -> str:
    """PLAIN: Return the model-findings heading."""
    return pick("Model findings", tr, "Model bulguları")


def finding_fields(finding: dict[str, Any], tr: bool, esc: Callable[[Any], str]) -> tuple[str, str, str]:
    """PIECEWISE: Escape section, code label and stored finding text in order."""
    sid = finding.get("section_id")
    section = heading(sid, tr) if sid else pick("Report", tr, "Rapor")
    code = REVIEW_CODES.get(finding["code"], REVIEW_CODES["other"])[int(tr)]
    return esc(section), esc(code), esc(finding["text"])


def ensure_report_finished(view: dict[str, Any]) -> None:
    """helper: Refuse precisely the original unfinished-report states."""
    if view["status"] == "in_progress" or (view["run"] and view["run"]["status"] not in ("completed", "failed", "cancelled")):
        raise RevisionConflict("The report is still being written")


def report_stem(view: dict[str, Any], title: str) -> str:
    """helper: Return the original ASCII slug and draft/version suffix."""
    slug = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:60].rstrip("-") or "report"
    suffix = "draft" if view["status"] == "draft" else f'v{view["report_version"]}'
    return f"report-{slug}-{suffix}"

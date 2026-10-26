"""Byte pins captured before X1 extraction on 887f592; all views are SYNTHETIC.

CASES builders return (view, title, corpus). EXPECTED contains captured literals,
never an expectation rendered by production code at test time.
"""

from copy import deepcopy
from functools import partial

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.workflow.features.report.report_export import export_markdown, to_markdown
from deixis.workflow.features.report.report_store import ReportStore
from deixis.workflow.run.store import NotFound
from test_report_export import complete, app_for, create, session, ReportAdapter


def _claim(text="SYNTHETIC claim", paragraph=1, equation=None, links=(), table=None):
    return {"text": text, "paragraph": paragraph, "equation_ref": equation,
            "table_ref": table, "evidence": list(links)}


def _section(sid="abstract", claims=(), status="valid", draft=None):
    return {"section_id": sid, "status": status, "draft": draft, "claims": list(claims)}


def _link(number=1, located=True):
    return {"ref_number": number, "anchor_match": "exact" if located else None}


def _missing():
    return {"counts": {"included": 5, "failed": 2, "cells_missing": 7}, "failed_rows": [
        {"source_key": "SYNTHETIC[key]", "title": "SYNTHETIC ignored", "reason": "no_stored_text"},
        {"source_key": None, "title": "- SYNTHETIC <title>", "reason": "SYNTHETIC_other_reason[detail]"}]}


def _check(current=True, empty=False):
    return {"current": current, "created_at": "SYNTHETIC [date]", "errors": 2, "warnings": 1,
            "items": [] if empty else [{"section_id": "III", "rule": "SYNTHETIC_rule", "severity": "error",
                                       "detail": "- SYNTHETIC <detail> [quote] | `code`"}],
            "skipped_rules": [] if empty else [{"section_id": "III", "claim_key": "SYNTHETIC[claim]",
                                               "rule": "SYNTHETIC_skipped", "reason": "SYNTHETIC[reason]"}],
            "not_checked": [] if empty else ["semantic_support", "numbers_written_as_words", "passages",
                                            "- SYNTHETIC[unknown]"]}


def _review(n=0, reverted=0, missed=False):
    findings = [{"section_id": "abstract", "code": "support_broken", "text": "- SYNTHETIC [finding]"},
                {"section_id": None, "code": "SYNTHETIC_unknown", "text": "# SYNTHETIC <finding>"}][:n]
    return {"status": "reviewed", "sections_reviewed": ["abstract"],
            "sections_not_reviewed": [{"section_id": "II"}, {"section_id": "1. SYNTHETIC[unknown]"}] if missed else [],
            "findings": findings, "reverted": [{} for _ in range(reverted)]}


def _table(single=False):
    names = ["SYNTHETIC A|B", r"SYNTHETIC $a|b$", r"SYNTHETIC $a\|b$", r"SYNTHETIC $a\\|b$",
             "Number", "Unit", "Yes", "No", "Options", "Empty", "Unverified", "Unverified empty", "Other", "Missing"]
    columns = [{"column_id": str(i), "name": name,
                "options": [{"id": "known", "label": "SYNTHETIC[option]"}]} for i, name in enumerate(names)]
    rows = [{"source_version_id": "s1", "source_key": "SYNTHETIC|key", "title": "SYNTHETIC ignored", "ref_number": 1},
            {"source_version_id": "s2", "title": "SYNTHETIC[title]", "ref_number": None},
            {"source_version_id": "s3", "ref_number": 3}]
    values = [{"text": "SYNTHETIC one|two\nthree"}, {"text": r"$a|b$"}, {"text": r"$a\|b$"},
              {"text": r"$a\\|b$"}, {"number": 7}, {"number": 2.5, "unit": "SYNTHETIC[unit]"},
              {"answer": "yes"}, {"answer": "no"}, {"option_ids": ["known", "SYNTHETIC_unknown"]}, {},
              {"text": "SYNTHETIC $c|d$\nnext"}, None, None]
    cells = [{"source_version_id": "s1", "column_id": str(i),
              "state": "value" if i < 10 else "not_verified" if i < 12 else "not_found",
              "value": value} for i, value in enumerate(values)]
    return {"columns": columns[:1] if single else columns, "rows": rows,
            "cells": cells[:1] if single else cells}


def _body():
    claims = [_claim("SYNTHETIC A", 1, "A", [_link(2), _link(2), _link(1)]),
              _claim("SYNTHETIC B", 2, "B"), _claim("SYNTHETIC A again", 1, "A")]
    claims += [_claim(prefix + " SYNTHETIC leading", i + 3) for i, prefix in enumerate(("#", "-", "+", "*", "1.", "2)"))]
    claims += [_claim(r"SYNTHETIC \ [ ] < > | `code` and $<[x]>$ and $$<[y]>$$ unmatched $", 9),
               _claim("> SYNTHETIC quote", 10)]
    return [_section("IX", [_claim("SYNTHETIC reuse B", equation="B")]),
            _section("1. SYNTHETIC[unknown]", [_claim("SYNTHETIC unknown section")]),
            _section("abstract", claims), _section("index_terms", [_claim("SYNTHETIC index")])]


def _refs():
    return [{"number": 1, "authors": ["SYNTHETIC [author]", "SYNTHETIC <author>"],
             "title": "SYNTHETIC[reference]", "venue": "SYNTHETIC|venue", "year": 2026,
             "doi": "SYNTHETIC/doi[1]", "version_label": "SYNTHETIC<version>"},
            {"number": 2, "authors": [], "title": "SYNTHETIC bare reference",
             "venue": None, "year": None, "doi": None, "version_label": None}]


RULE_GROUPS = {
    "assembly-a": ["banned_word", "empty_section", "corpus_count_mismatch", "SYNTHETIC_unknown_rule",
                   "citation_anchor_unmatched"],
    "assembly-b": ["citation_anchor_unmatched", "anchor_not_in_cell_evidence", "anchor_not_in_passage",
                   "SYNTHETIC_unknown_rule"],
    "assembly-unknown-first": ["SYNTHETIC_unknown_rule[1]", "banned_word", "empty_section",
                               "corpus_count_mismatch", "anchor_not_in_passage"],
}


def _build(case, language):
    view = {"status": "valid", "language": language, "report_version": 12, "run": None,
            "sections": [], "references": [], "table_i": None, "review": None,
            "edited_after_version": None}
    title, corpus = "SYNTHETIC pin", None
    if case in RULE_GROUPS:
        rules = RULE_GROUPS[case]
        view.update(status="draft", sections=[_section(claims=[_claim()])], run={"error":
            [{"rule": rule} for rule in rules] + [{"rule": rules[0]}, {"rule": "SYNTHETIC_warning", "detail": "WARNING: ignored"},
                                                  "SYNTHETIC non-dict", {"rule": None}]})
    elif case.startswith("draft-error-"):
        view["status"] = "draft"
        kind = case.removeprefix("draft-error-")
        view["run"] = {} if kind == "absent" else {"error": [] if kind == "empty" else "SYNTHETIC wrong shape"}
    elif case == "draft-unvalidated":
        view.update(status="draft", sections=[_section("III", status="draft"), _section("I", status="failed"),
                                               _section("abstract", [_claim()])])
    elif case == "missing-rows":
        view["missing_rows"] = _missing()
    elif case == "empty-and-insufficient":
        view["sections"] = [_section("VI"), _section("III", draft={"insufficient_evidence": [
            {"reason": "- SYNTHETIC [reason]"}, {"reason": "SYNTHETIC <reason>"}]}), _section("I")]
    elif case.startswith("not-reviewed-"):
        reason = case.removeprefix("not-reviewed-")
        view["review"] = {"status": "not_reviewed"}
        if reason != "missing":
            view["review"]["reason"] = reason
    elif case.startswith("reviewed-"):
        _, n, reverted, missed = case.split("-")
        view["review"] = _review(int(n), int(reverted), missed == "missed")
    elif case.startswith("text-"):
        claims = [_claim("SYNTHETIC following claim")] if case == "text-with-claims" else []
        view["sections"] = [_section("VIII", claims, draft={"text": "- SYNTHETIC VIII[text]"}),
                            _section("II", claims, draft={"text": "# SYNTHETIC II[text]"})]
    elif case.startswith("edit-") and case not in ("edit-fallback", "edit-explicit-false", "edit-draft", "edit-empty"):
        _, version, state = case.split("-")
        view.update(has_human_edits=True, edited_after_version=None if version == "none" else 1)
        if state != "absent":
            view["edit_check"] = _check(state == "current")
    elif case == "edit-empty":
        view.update(has_human_edits=True, edit_check=_check(empty=True))
    elif case in ("edit-fallback", "edit-explicit-false"):
        view["edited_after_version"] = 1
        if case == "edit-explicit-false":
            view["has_human_edits"] = False
    elif case == "edit-draft":
        view.update(status="draft", has_human_edits=True)
    elif case.startswith("anchors-"):
        kind = case.removeprefix("anchors-")
        claims = []
        if kind in ("located", "unlocated", "removed-with-links"):
            claims.append(_claim(links=[_link(), _link(2, kind != "unlocated")]))
        if kind in ("removed-with-links", "removed-zero"):
            claims.extend([_claim("SYNTHETIC removed") | {"evidence_basis": "none", "support_type_note": "model_written_type"},
                           _claim("SYNTHETIC removed again") | {"evidence_basis": "none", "support_type_note": "model_written_type"}])
        view["sections"] = [_section(claims=claims)]
    elif case == "evidence-changed":
        view["evidence_changes"] = {"any": True}
    elif case == "corpus":
        corpus = {"found": 17, "unique": 13, "screened": 11, "included": 5, "full_text": 3}
    elif case.startswith("table-"):
        kind = case.removeprefix("table-")
        claims = [_claim("SYNTHETIC first paragraph", 2), _claim("SYNTHETIC table ref", 1, table="TABLE_I"),
                  _claim("SYNTHETIC same paragraph", 1), _claim("SYNTHETIC last paragraph", 3)] if kind == "after-ref" else [_claim()]
        view["sections"] = [_section("IV", claims)]
        if kind != "absent":
            view["table_i"] = _table(kind == "single")
    elif case == "body":
        view["sections"], view["references"] = _body(), _refs()
        title = "# SYNTHETIC [title]\n<heading> | `code`"
    elif case == "kitchen-sink":
        view.update(status="draft", sections=_body() + [
            _section("II", [_claim("SYNTHETIC II claim")], draft={"text": "SYNTHETIC II[text]"}),
            _section("VIII", draft={"text": "SYNTHETIC VIII[text]"}), _section("VI", status="failed"),
            _section("III", status="draft", draft={"insufficient_evidence": [{"reason": "- SYNTHETIC missing"}]}),
            _section("IV", [_claim("SYNTHETIC table intro", table="TABLE_I"),
                            _claim("SYNTHETIC removed") | {"evidence_basis": "none", "support_type_note": "model_written_type"}])],
            references=_refs(), table_i=_table(), missing_rows=_missing(), has_human_edits=True,
            edited_after_version=1, edit_check=_check(), evidence_changes={"any": True}, review=_review(2, 2, True))
        view["sections"][2]["claims"][0]["evidence"].append(_link(3, False))
        title, corpus = "# SYNTHETIC [kitchen]\n<report>", {"found": 17, "unique": 13, "screened": 11, "included": 5, "full_text": 3}
    elif case != "base":
        raise AssertionError(case)
    return deepcopy(view), title, corpus


CASE_NAMES = ["base", *RULE_GROUPS, "draft-error-absent", "draft-error-empty", "draft-error-nonlist",
              "draft-unvalidated", "missing-rows", "empty-and-insufficient",
              *("not-reviewed-" + reason for reason in ("input_too_large", "budget_exhausted", "nothing_to_review",
                  "model_mismatch", "model_call_failed", "invalid_model_output", "SYNTHETIC_unknown", "missing")),
              *(f"reviewed-{n}-{n}-{missed}" for n in range(3) for missed in ("read", "missed")),
              "text-with-claims", "text-without-claims",
              *(f"edit-{version}-{state}" for version in ("none", "1") for state in ("absent", "current", "historical")),
              "edit-empty", "edit-fallback", "edit-explicit-false", "edit-draft",
              *("anchors-" + kind for kind in ("located", "unlocated", "zero", "removed-with-links", "removed-zero")),
              "evidence-changed", "corpus", "table-after-ref", "table-start", "table-single", "table-absent", "body", "kitchen-sink"]
CASES = {f"{case}-{language}": partial(_build, case, "tr-TR" if case == "kitchen-sink" and language == "tr" else language)
         for case in CASE_NAMES for language in ("en", "tr")}


# Captured on 887f592 before editing export.py; reviewed for wording and order.
EXPECTED = {
    'base-en': (
        '# SYNTHETIC pin\n'
        'Evidence report · V12\n'
        '\n'
        '## References\n'
        '\n'
        'Generated by DEIXIS.\n'
        '\n'
        'Anchors were located in the cited passages or cells. No model or person review is recorded for this report; whether each passage supports its claim was not checked by code.\n'
    ),
    'kitchen-sink-tr': (
        '> TASLAK: 2 bölüm doğrulanmadı.\n'
        '\n'
        '# \\# SYNTHETIC \\[kitchen\\] \\<report\\>\n'
        'Kanıt raporu · taslak\n'
        '\n'
        '5 kaynağın 2 tanesinde tablo doldurma tamamlanmadı; 7 hücre eksik. Bu satırlar raporun kanıt değerlendirmesine ve toplulaştırma paydalarına alınmadı.\n'
        '\n'
        '- SYNTHETIC\\[key\\]: saklı metin yok\n'
        '- \\- SYNTHETIC \\<title\\>: SYNTHETIC other reason\\[detail\\]\n'
        '\n'
        '1. sürümden sonra elle düzenlendi; düzenlenen metin kod kurallarıyla denetlendi (SYNTHETIC \\[date\\]): 2 hata, 1 uyarı; atıf yapılan kanıtın her cümleyi destekleyip desteklemediği denetlenmedi.\n'
        '\n'
        '- III · SYNTHETIC_rule (error): \\- SYNTHETIC \\<detail\\> \\[quote\\] \\| \\`code\\`\n'
        '\n'
        'Denetlenmedi:\n'
        '- III · SYNTHETIC\\[claim\\]: SYNTHETIC_skipped (SYNTHETIC\\[reason\\])\n'
        '- atıf yapılan kanıtın her cümleyi destekleyip desteklemediği\n'
        '- sözcükle yazılmış sayılar\n'
        '- pasajlar\n'
        '- \\- SYNTHETIC\\[unknown\\]\n'
        '\n'
        'Bu rapor yazıldıktan sonra kanıt değişti; rapor metni değişmedi. Pasaj metni denetlenmedi.\n'
        '\n'
        '## Özet\n'
        '\n'
        'SYNTHETIC A (1) [2], [1], [3] SYNTHETIC A again (1)\n'
        '\n'
        'SYNTHETIC B (2)\n'
        '\n'
        '\\# SYNTHETIC leading\n'
        '\n'
        '\\- SYNTHETIC leading\n'
        '\n'
        '\\+ SYNTHETIC leading\n'
        '\n'
        '\\* SYNTHETIC leading\n'
        '\n'
        '\\1. SYNTHETIC leading\n'
        '\n'
        '\\2) SYNTHETIC leading\n'
        '\n'
        'SYNTHETIC \\\\ \\[ \\] \\< \\> \\| \\`code\\` and ${\\lt}{[}x{]}{\\gt}$ and $${\\lt}{[}y{]}{\\gt}$$ unmatched $\n'
        '\n'
        '\\> SYNTHETIC quote\n'
        '\n'
        '## Dizin Terimleri\n'
        '\n'
        'SYNTHETIC index\n'
        '\n'
        '## II. İnceleme Yöntemi\n'
        '\n'
        'SYNTHETIC II\\[text\\]\n'
        '\n'
        'SYNTHETIC II claim\n'
        '\n'
        '## III. Arka Plan ve Sınıflandırma\n'
        '\n'
        '> Bu bölüm doğrulanmadı ve yeniden yazılmalı.\n'
        '\n'
        'Yeterli kanıt yok: \\- SYNTHETIC missing\n'
        '\n'
        '## IV. Literatür Sentezi\n'
        '\n'
        'SYNTHETIC table intro SYNTHETIC removed\n'
        '\n'
        'TABLO I. Bu rapor için dondurulan kanıt tablosu (3 kaynak, 14 sütun).\n'
        '\n'
        '| Kaynak | SYNTHETIC A\\|B | SYNTHETIC $a{\\vert}b$ | SYNTHETIC $a{\\Vert}b$ | SYNTHETIC $a\\\\{\\vert}b$ | Number | Unit | Yes | No | Options | Empty | Unverified | Unverified empty | Other | Missing |\n'
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n'
        '| [1] SYNTHETIC\\|key | SYNTHETIC one\\|two three | $a{\\vert}b$ | $a{\\Vert}b$ | $a\\\\{\\vert}b$ | 7 | \\2.5 SYNTHETIC\\[unit\\] | Evet | Hayır | SYNTHETIC\\[option\\], SYNTHETIC_unknown |  | SYNTHETIC $c{\\vert}d$ next (doğrulanmadı: bağlı alıntı yok) |  (doğrulanmadı: bağlı alıntı yok) | not found | — |\n'
        '| SYNTHETIC\\[title\\] | — | — | — | — | — | — | — | — | — | — | — | — | — | — |\n'
        '| [3] Kaynak kaydı bulunamadı | — | — | — | — | — | — | — | — | — | — | — | — | — | — |\n'
        '\n'
        '## VI. Cevaplanmamış Yön Adayları\n'
        '\n'
        '> Bu bölüm doğrulanmadı ve yeniden yazılmalı.\n'
        '\n'
        'Modelin kanıt tablosundan çıkardığı aday yönler; hiçbiri kapsamlı bir yoklama aramasıyla denetlenmedi.\n'
        '\n'
        'Bu bölüm için metin yazılmadı.\n'
        '\n'
        '## VIII. Sınırlılıklar ve Geçerlilik Tehditleri\n'
        '\n'
        'SYNTHETIC VIII\\[text\\]\n'
        '\n'
        '## IX. Sonuç\n'
        '\n'
        'SYNTHETIC reuse B (2)\n'
        '\n'
        '## \\1. SYNTHETIC\\[unknown\\]\n'
        '\n'
        'SYNTHETIC unknown section\n'
        '\n'
        '## Kaynaklar\n'
        '\n'
        '[1] SYNTHETIC \\[author\\], SYNTHETIC \\<author\\>, SYNTHETIC\\[reference\\], SYNTHETIC\\|venue, 2026, DOI: SYNTHETIC/doi\\[1\\], (SYNTHETIC\\<version\\>)\n'
        '\n'
        '[2] SYNTHETIC bare reference\n'
        '\n'
        'DEIXIS ile üretildi; korpus: bulunan 17, tekil 13, taranan 11, dahil 5, tam metinli 3.\n'
        '\n'
        '4 atıf çapasının 3 tanesi ilgili pasajlarda veya hücrelerde bulundu; diğerleri işaretsiz açılır. Atıflar elle kaldırıldıktan sonra 1 iddianın doğrudan atfı kalmadı. Raporu yazan model, ek bir inceleme çağrısında 3 bölümün 1 tanesindeki iddiaları atıf yapılan pasaj ve hücrelerle karşılaştırıp 2 olası sorun işaretledi. Bu, modelin okumasıdır; hakem incelemesi değildir ve hataları kaçırabilir. Kod, her pasajın ilgili iddiayı destekleyip desteklemediğini denetlemedi. Model, yeniden yazılan 2 cümlenin kaynaklarıyla artık uyuşmayabileceğini işaretledi; cümleler özgün hâline döndürüldü. Okunmayan bölümler: II. İnceleme Yöntemi, \\1. SYNTHETIC\\[unknown\\]. İnceleme modelin temel sürümünü kapsar; insan düzenlemeleri incelenmedi.\n'
        '\n'
        'Model bulguları\n'
        '\n'
        '- Özet · Destek artık uyuşmuyor · \\- SYNTHETIC \\[finding\\]\n'
        '- Rapor · Diğer · \\# SYNTHETIC \\<finding\\>\n'
    ),
}


@pytest.mark.parametrize("case_id", ["base-en", "kitchen-sink-tr"])
def test_markdown_bytes(case_id):
    view, title, corpus = CASES[case_id]()
    assert to_markdown(view, title=title, corpus=corpus).encode("utf-8") == EXPECTED[case_id].encode("utf-8")


FILE_CASES = {
    "valid": ("SYNTHETIC valid", "valid", "report-synthetic-valid-v1.md"),
    "draft": ("SYNTHETIC draft", "draft", "report-synthetic-draft-draft.md"),
    "non-ascii": ("SYNTHETIC café İığşçöü", "valid", "report-synthetic-cafe-igscou-v1.md"),
    "symbols": ("!@#$%^&*()", "valid", "report-report-v1.md"),
    "cut-hyphen": ("SYNTHETIC " + "a" * 49 + " tail", "valid", "report-synthetic-" + "a" * 49 + "-v1.md"),
}


# D114: claims resting on abstract text carry a mark, and a source read from its abstract only is noted.
FILE_EXPECTED = {
    'non-ascii-tr': (
        (
        '# SYNTHETIC café İığşçöü\n'
        'Kanıt raporu · V1\n'
        '\n'
        "Bu raporun dayanağı: 1 kaynağın 0 tanesi tam metinden, 1 tanesi yalnızca özetten veya künye bilgisinden okundu. Daha ayrıntılı bir rapor için özetten veya künye bilgisinden okunan kaynakların PDF'lerini yükleyin.\n"
        '\n'
        '## Özet\n'
        '\n'
        'This report has shown that the SYNTHETIC formulation is bounded. (özetten)\n'
        '\n'
        '## Dizin Terimleri\n'
        '\n'
        'It has been reported that the SYNTHETIC formulation is bounded. (özetten)\n'
        '\n'
        '## I. Giriş\n'
        '\n'
        'It has been reported that the SYNTHETIC formulation is bounded. (özetten)\n'
        '\n'
        '## II. İnceleme Yöntemi\n'
        '\n'
        'The recorded search used none recorded with no recorded query; the compiled query version was not recorded. The frozen corpus contained 0 found, 1 unique, 0 screened, and 1 included sources; PDF acquisition recorded 0 direct-fetch and 0 other-copy steps, full text was available for 0/1 included sources (0.0%), and screening used not recorded with no screening input recorded.\n'
        '\n'
        '## III. Arka Plan ve Sınıflandırma\n'
        '\n'
        'It encompasses the SYNTHETIC bounded formulation. [1] (özetten)\n'
        '\n'
        '## IV. Literatür Sentezi\n'
        '\n'
        'It has been reported that the SYNTHETIC formulation is bounded. [1] (özetten)\n'
        '\n'
        'TABLO I. Bu rapor için dondurulan kanıt tablosu (1 kaynak, 3 sütun).\n'
        '\n'
        '| Kaynak | SYNTHETIC method | SYNTHETIC stated limitations | SYNTHETIC stated future work |\n'
        '| --- | --- | --- | --- |\n'
        '| [1] syntheticnd (yalnızca özet) | SYNTHETIC bounded formulation | SYNTHETIC bounded formulation | SYNTHETIC bounded formulation |\n'
        '\n'
        '## V. Karşılaştırmalı Bulgular\n'
        '\n'
        'The SYNTHETIC formulation is different from its alternative in a number of respects. [1] (özetten)\n'
        '\n'
        '## VI. Cevaplanmamış Yön Adayları\n'
        '\n'
        'Modelin kanıt tablosundan çıkardığı aday yönler; hiçbiri kapsamlı bir yoklama aramasıyla denetlenmedi.\n'
        '\n'
        'It has been reported that the SYNTHETIC formulation is bounded. [1] (özetten)\n'
        '\n'
        '## VII. Gelecek Yönelimler\n'
        '\n'
        'It has been reported that the SYNTHETIC formulation is bounded. [1] (özetten)\n'
        '\n'
        '## VIII. Sınırlılıklar ve Geçerlilik Tehditleri\n'
        '\n'
        "\\1. Recall was not measured against a known source set. 2. The frozen corpus had 0 found, 1 unique, 0 screened, and 1 included sources; full text was available for 0/1 included sources and may favor open access sources. 3. 1 of 1 included sources had no PDF text (100.0%). 4. In valid sections III–VII, 0 of 5 claims were analyst inferences (0.0%). 5. A kill search for research gaps was not run. 6. 0 records were cut for the budget; a cell's evidence passage was not found for 0 cells (by section: none).\n"
        '\n'
        'It has been reported that the SYNTHETIC formulation is bounded. (özetten)\n'
        '\n'
        '## IX. Sonuç\n'
        '\n'
        'This report has shown that the SYNTHETIC formulation is bounded. (özetten)\n'
        '\n'
        '## Kaynaklar\n'
        '\n'
        '[1] SYNTHETIC molecular communication study, (uploaded file). Yalnızca özetten okundu.\n'
        '\n'
        'DEIXIS ile üretildi; korpus: bulunan 0, tekil 1, taranan 0, dahil 1, tam metinli 0.\n'
        '\n'
        'Atıf çapaları ilgili pasajlarda veya hücrelerde bulundu. Raporu yazan model, ek bir inceleme çağrısında 10 bölümün 10 tanesindeki iddiaları atıf yapılan pasaj ve hücrelerle karşılaştırıp 0 olası sorun işaretledi. Bu, modelin okumasıdır; hakem incelemesi değildir ve hataları kaçırabilir. Kod, her pasajın ilgili iddiayı destekleyip desteklemediğini denetlemedi. İnceleme modelin temel sürümünü kapsar; insan düzenlemeleri incelenmedi.\n'
    )    ),
}


@pytest.mark.parametrize("language", ["tr"])
@pytest.mark.parametrize("case", ["non-ascii"])
def test_export_filename(tmp_path, case, language):
    store, reports, research_id, report_id = complete(tmp_path)
    try:
        title, status, expected = FILE_CASES[case]
        store.conn.execute("UPDATE researches SET title = ? WHERE id = ?", (title, research_id))
        store.conn.execute("UPDATE reports SET language = ?, status = ? WHERE id = ?", (language, status, report_id))
        text, filename = export_markdown(store, research_id, report_id)
        assert filename == expected
        assert text == FILE_EXPECTED[f"{case}-{language}"]
    finally:
        store.conn.close()


GATE_CASES = {"in-progress": ("in_progress", "completed", 409),
              "paused": ("draft", "paused", 409), "running": ("draft", "running", 409),
              "failed": ("draft", "failed", 200), "cancelled": ("draft", "cancelled", 200),
              "completed": ("draft", "completed", 200)}


@pytest.mark.parametrize("language", ["en"])
@pytest.mark.parametrize("case", ["running"])
def test_public_gate_and_missing_snapshot(tmp_path, case, language):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached")
        store = raw.app.state.store
        store.conn.execute("UPDATE researches SET title = ? WHERE id = ?", ("SYNTHETIC pin", research_id))
        run = store.create_run(research_id, "report", {"max_model_calls": 1, "max_provider_requests": 0}, None,
                               {"table_id": "tbl_synthetic"})
        reports = ReportStore(store)
        report_id = reports.create_report(research_id, run["id"], run["scope_revision"], language)
        status, run_status, code = GATE_CASES[case]
        if status != "in_progress":
            reports.finalize(report_id, status)
        store.update_run(run["id"], status=run_status)
        with pytest.raises(NotFound):
            reports.snapshot(report_id)
        if code == 409:
            with pytest.raises(RevisionConflict, match="^The report is still being written$"):
                export_markdown(store, research_id, report_id)
        else:
            text, filename = export_markdown(store, research_id, report_id)
            assert text == EXPECTED[f"draft-error-absent-{language}"]
            assert ("Generated by DEIXIS." if language == "en" else "DEIXIS ile üretildi.") in text
            assert filename.endswith("-draft.md")
        response = client.get(f"/api/researches/{research_id}/reports/{report_id}/export")
        assert response.status_code == code
        if code == 409:
            assert response.json()["detail"] == "The report is still being written"
        else:
            assert response.text == text

# P6 dilim 1 — Rapor çalışması: uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DEIXIS'e yeni bir `report` çalışma (run) türü eklemek: dahil kaynakların kanıt tablosundan (P5) donmuş bir kanıt anlık görüntüsü alan, bölüm başına bir model adımıyla (III–IX, Abstract, Index Terms) IEEE üslubunda sayısal atıflı, tablolu, denklemli bir araştırma raporu yazan; II (Review Methodology) ve VIII (Limitations) sayısal çekirdeğini kodun yazdığı; cevaplanmamış yön adaylarını (VI) yalnız tam metin kanıtından, kaynakçalı üreten; phrasebank'i bölüme göre süzen ve kalıba uymayan cümleleri hedefli onarımla düzelten (anlamı bozan onarımı geri alan); montaj denetimi ve `report_review` modeliyle doğrulanan; okuma biçimli bir rapor görünümü ve Markdown dışa aktarımı sunan uçtan uca dilim.

**Architecture:** Mevcut `ResearchFlow` (backend/deixis/workflow/flow.py) çalışma türü listesine `report` eklenir; yürütme yeni `backend/deixis/workflow/report/` paketine devredilir (snapshot, plan, selection, sections, phrasing, gaps, assembly, review, export, numbering, store). Bölüm adımları bugünkü `_model_step` altyapısını (StepInput zarfı, `operation_key` tekrarsızlığı, tek şema onarımı, `model_mismatch`, D12 kısa tutamaçlar) olduğu gibi kullanır; yeni olan yalnız dört görev türü (`report_plan`, `report_section`, `report_phrase_repair`, `report_review`), bunların şemaları (`domain/contracts.py`) ve bölüme özel kanıt seçimidir. Eş zamanlı turlar (A–D) slice 0'ın (`docs/product/p6-slice0-concurrent-fill.md`, artık yazılı) süreç genelindeki `backend/deixis/workflow/concurrency.py::ModelCallLimiter`'ını kullanır: bir turun bağımsız bölüm adımları `asyncio.gather` ile aynı anda başlatılır ve her çağrının sahibi, `_table_fill` gibi, adımı `flow.deps.limiter.run(operation_key, factory)` ile gönderir. Fabrika `_model_step(..., limiter=flow.deps.limiter)` çağırır; bu parametre `_call_adapter`'ın kota hatasında `limiter.reduce()` uygulayıp yeniden göndermesini sağlar, eş zamanlılık tavanını kendi başına uygulamaz. Kota hatasında süreç genelindeki tek limit düşer (tabloyla paylaşılır). Depolama yeni tablolarla genişler (`reports`, `report_sections`, `report_claims`, `report_claim_refs`, `report_citation_links`, `report_gaps`, `report_snapshot`, `report_phrase_repairs`) ve `ReportStore` sınıfı `TableStore`'un desenini izler (append-only, `operation_key` replay, `Store.conn` paylaşımı). API'ye tablo alt sisteminin izlediği `request_*` deseniyle yeni rotalar eklenir. Frontend'de `apps/web/src/report/` yeni bir alt dizin `ResearchView.tsx`'e ince bir entegrasyonla bağlanır; `PdfReadiness.tsx`'e dördüncü durum eklenir.

**Tech Stack:** Python 3.12 (uv, native arm64), FastAPI, SQLite (tek bağlantı, kısa senkron işlemler), JSON Schema (Draft 2020-12) tabanlı model sözleşmeleri, `models/adapter.py` üzerinden model bağlantıları (gerçek koşu: `gpt-5.6-luna`); React 19 + TypeScript + Tailwind 4 + shadcn/base-ui (apps/web), Playwright (apps/web/e2e), pytest (tests/).

**Spec:** docs/product/p6-report-design.md

## Global Constraints

- Python 3.12 via `uv`; venv native arm64 (`python3 -c "import platform; print(platform.machine())"` → `arm64`).
- Backend tests: `PYTHONPATH=backend uv run pytest` (tümü); `PYTHONPATH=backend uv run pytest tests/test_contracts.py -k anchor` (odaklı).
- Frontend: `cd apps/web && npm ci && npm run build && npm run lint` (oxlint).
- Acceptance: `cd apps/web && DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance` (taze `npm run build`'dan sonra).
- Tek SQLite bağlantısı API ve worker arasında paylaşılır; yazmalar kısa senkron işlemlerdir; bir işlem içinde asla `await` yok; UI'a görünen olaylar durumu tanımladıkları işlemle birlikte yazılır.
- Her adım `operation_key` ile anahtarlanmış bir satırdır; `succeeded` olmuş bir adım saklı çıktısını döner (replay).
- Modele gönderilen her şey çağrıdan önce saklanır (`step_inputs`).
- Modelin aracı yoktur (`model_isolation_violation`); o adımın rolü için istenenden başka bir modelin çıktısı kaydedilir ama asla kullanılmaz (`model_mismatch`, sessiz geri düşüş yok); şema onarımı sınırlıdır (`MAX_SCHEMA_REPAIRS = 1`, `domain/rules.py`).
- Modele gösterilen kimlikler yalnız StepInput'un allowlist'inden gelir; `grounded_answer`, `answer_review`, `cell_extraction` (ve bu dilimde `report_section`, `report_phrase_repair`, `report_review`) kısa atıf tutamaçları (D12) görür; bunlar doğrulamadan önce kayıt kimliklerine çözülür.
- Migration'lar `backend/deixis/storage/migrations/`de yeni numaralı dosyalardır, başlangıçta uygulanır; uygulanmış bir dosya bir daha çalıştırılmaz ve asla düzenlenmez. `runs.kind` CHECK kısıtına değer eklemek tablo kopyalayan bir migration gerektirir (desen: 0028, 0032). Bu dilimin migration'ı yürütme anındaki ilk boş numarayı alır; bu not yazılırken 0033 `work_source_keys.sql` ile committed durumda, dolayısıyla **0034** boştur, ama yürütmeden hemen önce `ls backend/deixis/storage/migrations/` ile teyit edilmelidir.
- Bir yöntem paketi çalışma dosyası düzenlendiğinde `skill_package_hash` değişir; `methods/deixis-research/` bütünlük denetimini geçemezse uygulama başlamayı reddeder (frontmatter `name` dizinle eşleşir, göreli bağlantılar çözülür, `provenance.json` zorunlu alanları taşır).
- Şema değişikliği aynı değişiklikte `tests/fixtures/research/{step-inputs,fake-outputs}.json` ve `tests/fakes.py::valid_response` güncellemesi gerektirir.
- UI metinleri `i18n.ts`/`labels.ts` üzerinden gider; `apps/web`'e dokunmadan önce `.impeccable.md` okunur; ara görsel onay istenmez — değişikliği kendin build/ekran görüntüsüyle doğrula.
- Gerçek modelle koşular `gpt-5.6-luna`'yı açıkça geçirir, kütüphanenin bir KOPYASI ve kendi `DEIXIS_DATA_DIR`'i ile, port 8799'da — canlı 8765 servisine asla dokunulmaz.
- Fixture kayıtları SYNTHETIC etiketlidir; geçen bir birim/acceptance testi iş akışı davranışını gösterir, model kalitesini ya da canlı sağlayıcı erişimini değil.
- Rapor dili sorunun dilidir (yanıtla aynı kural).
- Denklemler LaTeX'tir ve yanıtın 7. maddesindeki sırayı izler (önce değişkenler ve anlamları, sonra amaç, sonra kısıtlar; yalnız alıntılanan pasajın verdiği parçalar için).
- Sınırlar: bölüm başına 40 iddia; toplam rapor 4000–7000 kelime, dahil kaynak sayısı $n < 10$ ise $n/10$ ile ölçeklenir, alt sınır toplam 1200 kelime; bir `corpus_absence` adayı için en az üç tam-metinli-ve-uygulanabilir satır şart; bölüm başına en fazla bir kalıp onarımı; eş zamanlılık üst sınırı başlangıçta 6; hız sınırında en fazla iki yeniden gönderim.
- Yasak sözcük listesi (gap/open problem/novel/first ve eşdeğerleri, iki dilde) rapor genelinde, başlık dahil, kill-search'ten önce her yerde denetlenir.
- Commit'ler doğrudan `main`'e gider (kullanıcının global git kuralı): açıklayıcı İngilizce cümle, AI ilişkilendirmesi/ortak yazarlık yok, yalnız o görevin dosyaları `git commit -- <paths>` ile stage edilir, sonra `git push origin main`.
- Bu dilimde alınan kalıcı bir karar `docs/decisions.md`'ye yürütme anındaki ilk boş D numarasıyla eklenir (bu not commit'lenirken en yüksek numara D59'dur ve D57 çakışması kapanmıştır; yürütmeden hemen önce `grep -n '^## D' docs/decisions.md | head -3` ile yeniden bakın).

## Dosya yapısı

Yeni dosyalar:

- `backend/deixis/workflow/report/__init__.py` — boş, paket işareti.
- `backend/deixis/workflow/report/store.py` — `ReportStore`: `reports`/`report_sections`/`report_claims`/`report_citation_links`/`report_gaps`/`report_snapshot`/`report_phrase_repairs` üzerinde CRUD ve durum geçişleri; `TableStore` deseninin aynısı (append-only, `self.conn = store.conn`).
- `backend/deixis/workflow/report/snapshot.py` — §4.2 kanıt anlık görüntüsü: tablo/sütun/hücre revizyonlarını, dahil kaynakların sürüm kimliklerini ve okuma derinliklerini, `corpus` sayılarını donduran `build_snapshot()`.
- `backend/deixis/workflow/report/selection.py` — §4.3 bölüm başına kanıt seçimi ve kesilme kaydı.
- `backend/deixis/workflow/report/plan.py` — `report_plan` StepInput kurulumu, model çıktısının doğrulanmasından sonra `corpus`/`section_budgets`/`allowed_support`'un kodla eklenmesi ve planın dondurulması.
- `backend/deixis/workflow/report/sections.py` — bölüm adımlarının turlar hâlinde (A–D) yürütülmesi, bağımlılık grafiği, `draft`/`failed` durumunda bağımlıların durdurulması.
- `backend/deixis/workflow/report/phrasing.py` — bölüm süzülmüş phrasebank yükleme çağrısı, hedefli onarım StepInput'u, onarım sonrası inceleme işaretleme.
- `backend/deixis/workflow/report/gaps.py` — VI için `corpus_absence` adaylarının kod tarafından üretilmesi (§7) ve kaynakça ekleme.
- `backend/deixis/workflow/report/assembly.py` — §8 montaj denetimleri (kod tarafı, model çağırmaz).
- `backend/deixis/workflow/report/review.py` — `report_review` adımının kurulumu ve destek-bozan onarımın geri alınması (§8, karar 12).
- `backend/deixis/workflow/report/numbering.py` — atıf/tablo/denklem numaralandırma (ilk geçiş sırası; `bibliography.py`'nin sağlamadığı işlev, §9).
- `backend/deixis/workflow/report/export.py` — Markdown dışa aktarma (§9, dilim 1 kapsamı; LaTeX slice 5'te).
- `contracts/research/report-plan.schema.json`, `report-section-draft.schema.json`, `report-phrase-repair.schema.json`, `report-review.schema.json`.
- `backend/deixis/storage/migrations/0034_report_run_kind.sql` (numara yürütme anında teyit edilir).
- `methods/deixis-research/references/report.md`.
- `tests/model_behavior/report_cases.json` — rapor davranış vakaları (§4.1, R10 ekilmiş hatalar için ayrı, mevcut `tests/model_behavior/cases.json`'a karışmadan).
- `scripts/p6_eval/measure_report.py` — gerçek model koşusunu §13 beklentileriyle karşılaştıran ölçüm betiği (yapısı `scripts/p4_eval/measure.py`'yi izler).
- `docs/product/p6-slice1-report-expectations.md` — koşudan önce donan §13 beklenti aralıkları (P5 dilim 5 kuralı).
- `apps/web/src/report/ReportView.tsx` — okuma biçimli rapor görünümü (madde işaretli iddia kartları değil, akan paragraf + IEEE atıf).
- `apps/web/src/report/ReportPanel.tsx` — `PdfReadiness` sonrası "Write report" akışı ve rapor zaman çizelgesi satırları.
- `apps/web/src/report/reportMarkdown.ts` — istemci tarafı pano kopyalama için Markdown üretimi (sunucudaki `export.py` ile aynı biçim).
- `apps/web/e2e/report.spec.ts` — rapor acceptance senaryosu (fixture_server'a script eklenir).

Değiştirilecek dosyalar (yalnız dispatch/wiring; iş mantığı yeni pakette):

- `backend/deixis/workflow/flow.py` — `execute()`'a `elif run["kind"] == "report": await self._report(run, scope)`; ince `_report` metodu `report/sections.py::run_report` çağırır.
- `backend/deixis/domain/contracts.py` — `TASK_OUTPUTS`/`SCHEMA_FILES`/`SCHEMA_VERSIONS` dört yeni girdi; `validate_model_output` dispatch'ine dört `elif`; `check_step_input`'a `report_target` dalı; `GAP_KINDS` sabiti (kod tarafı liste, SQL CHECK değil).
- `backend/deixis/domain/phrasebank.py` — `render(text, language, sections=None)`, `unframed(..., sections=None)`, yeni `nearest_frames(sentence, phrasebank_text, language, k=3)`.
- `backend/deixis/domain/skill.py` — `RUNTIME_FILES`'a dört görev türü; `SkillPackage.runtime_text`'e `sections` parametresi.
- `backend/deixis/models/prompt.py` — `developer_instructions`'a `sections` parametresi (geriye dönük uyumlu, varsayılan `None`).
- `backend/deixis/api/app.py` — `StartRun.kind`'e `"report"`; rapor rotaları (`POST/GET /api/researches/{id}/reports`, `GET .../reports/{report_id}`, `GET .../reports/{report_id}/export`).
- `backend/deixis/workflow/views.py` — `research_view`'a `reports` alanı (research_view'ın frontend'de zaten var olan istemci-taraflı `reports` adlandırmasıyla çakışmaması için ad netleştirmesi task 1g'de yapılır; bkz. Açık noktalar).
- `contracts/research/step-input.schema.json` — `task_type` enum'una dört değer; `report_target` alanı (nullable, `extraction_target`'ın kardeşi).
- `tests/fakes.py`, `tests/fixtures/research/step-inputs.json`, `tests/fixtures/research/fake-outputs.json` — dört yeni görev türü için sahte StepInput/çıktı.
- `tests/acceptance/fixture_server.py` — rapor için scriptlenmiş model yanıtları.
- `methods/deixis-research/SKILL.md`, `methods/deixis-research/provenance.json` — dört görev türü, daraltılmış yasak paragrafı, yeni provenance girdisi.
- `apps/web/src/ResearchView.tsx` — rapor sekmesi/paneli entegrasyonu.
- `apps/web/src/PdfReadiness.tsx` — dördüncü durum ("Tablo dolduruluyor").
- `apps/web/src/Transcript.tsx` — `report` çalışma türü için `PhaseKey`/`order`/`title`/`detail`.
- `apps/web/src/api.ts` — `RunKind`'e `'report'`; yeni `api.startReport`, `api.report`, `api.reportExportUrl`.
- `apps/web/src/i18n.ts`, `apps/web/src/labels.ts` — yeni İngilizce/Türkçe dizeler.
- `docs/decisions.md` — bu dilimin kalıcı kararı (yeni D numarası).

## Şemalar

Dört yeni sözleşme `contracts/research/` altına, mevcut dosyaların biçimiyle (Draft 2020-12, `additionalProperties: false`, her alan `required`, isteğe bağlı alanlar `anyOf`/`null` ile, `common.schema.json#/$defs/...` referansları) eklenir. `evidence_cells.id` öneki `cel_` (bkz. `backend/deixis/workflow/tables.py:163`, `new_id("cel")`); `cell_revisions.id` öneki `crv`; bu dilim `common.schema.json`'a yeni bir `$defs.cell_id` eklemez, dört yeni şemanın hepsi deseni satır içinde yazar (mevcut şemalarda da `extraction_target.columns[].column_id` böyle satır içi yazılıyor, aynı desen).

### `contracts/research/report-plan.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/report-plan.schema.json",
  "title": "ReportPlanDraft",
  "description": "The single cross-section consistency plan for a report run, written once and frozen. The model supplies only scope_statement, research_questions, glossary and axes; code fills corpus, section_budgets and allowed_support onto this draft after validation succeeds (report/plan.py), the same way search_plan's queries are compiled and stored after the model's output. Passing structural checks is not semantic verification.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "step_input_id", "scope_revision", "skill_package_hash", "scope_statement", "research_questions", "glossary", "axes"],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.report_plan_draft.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "scope_statement": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1200,
      "description": "One paragraph, in the question's language: what the report covers and why. research_title reuses this to write the report's title (§15.1)."
    },
    "research_questions": {
      "type": "array",
      "minItems": 2,
      "maxItems": 5,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["rq_id", "text"],
        "properties": {
          "rq_id": { "type": "string", "pattern": "^RQ[0-9]{1,2}$" },
          "text": { "$ref": "common.schema.json#/$defs/short_text" }
        }
      }
    },
    "glossary": {
      "type": "array",
      "maxItems": 40,
      "description": "Sourced term definitions, distinct from D44's search concept vocabulary. Index terms are chosen only from the D44 list, never from here.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["term", "definition", "passage_id"],
        "properties": {
          "term": { "type": "string", "minLength": 1, "maxLength": 80 },
          "definition": { "$ref": "common.schema.json#/$defs/short_text" },
          "passage_id": { "$ref": "common.schema.json#/$defs/passage_id" }
        }
      }
    },
    "axes": {
      "type": "array",
      "maxItems": 20,
      "description": "Classification axes, each tied to an evidence table column. An axis without a matching column is a schema/allowlist violation, checked in code (§6).",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["axis_id", "label", "column_id"],
        "properties": {
          "axis_id": { "type": "string", "pattern": "^AX[0-9]{1,2}$" },
          "label": { "type": "string", "minLength": 1, "maxLength": 120 },
          "column_id": { "type": "string", "pattern": "^col_[0-9A-Za-z]{8,40}$" }
        }
      }
    }
  }
}
```

### `contracts/research/report-section-draft.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/report-section-draft.schema.json",
  "title": "ReportSectionDraft",
  "description": "One report section's claims, written from the frozen report plan and the evidence code selected for this section only (§4.3). Claims cite passages and/or evidence-table cells from the StepInput allowlist. Locators, reading depth and cell values come from backend records, never from this output. Passing structural checks is not semantic verification.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "step_input_id", "scope_revision", "skill_package_hash", "section_id", "claims", "citation_anchors", "subsections", "gaps", "insufficient_evidence"],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.report_section_draft.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "section_id": {
      "type": "string",
      "enum": ["I", "III", "IV", "V", "VI", "VII", "VIII", "IX", "abstract", "index_terms"],
      "description": "II is written entirely by code and never calls this task."
    },
    "claims": {
      "type": "array",
      "maxItems": 40,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["claim_key", "text", "support_type", "passage_ids", "cell_ids", "paragraph", "table_ref", "equation_ref", "body_refs", "axis_id", "count", "equation_origin", "gap_refs"],
        "properties": {
          "claim_key": {
            "type": "string",
            "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}$",
            "description": "Stable within one report version; reassigned when the section is rewritten (e.g. IV.3, abstract.1)."
          },
          "text": { "type": "string", "maxLength": 2000 },
          "support_type": { "type": "string", "enum": ["source_stated", "analyst_inference"] },
          "passage_ids": { "type": "array", "maxItems": 8, "items": { "$ref": "common.schema.json#/$defs/passage_id" } },
          "cell_ids": { "type": "array", "maxItems": 8, "items": { "type": "string", "pattern": "^cel_[0-9A-Za-z]{8,40}$" } },
          "paragraph": {
            "type": "integer",
            "minimum": 1,
            "description": "Claims sharing one paragraph number are joined into one flowing paragraph in reading view, in claim order (§9)."
          },
          "table_ref": {
            "type": ["string", "null"],
            "enum": ["TABLE_I", null],
            "description": "Set only on a claim that refers to the evidence table as a whole (IV)."
          },
          "equation_ref": {
            "anyOf": [{ "type": "string", "pattern": "^EQ[0-9]{1,3}$" }, { "type": "null" }],
            "description": "A displayed-equation identifier this claim's text points to; code substitutes the printed number (1), (2)... (§9)."
          },
          "body_refs": {
            "type": "array",
            "maxItems": 40,
            "description": "abstract, I and IX only: claim_key values of III-VIII this claim summarizes. A derived claim inherits the weakest support_type and reading depth of its body_refs (§6, computed in report/assembly.py, not by the model).",
            "items": { "type": "string", "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}$" }
          },
          "axis_id": {
            "anyOf": [{ "type": "string", "pattern": "^AX[0-9]{1,2}$" }, { "type": "null" }],
            "description": "III and IV theme claims only; must match a plan axis and one of this draft's subsections."
          },
          "count": {
            "anyOf": [
              {
                "type": "object",
                "additionalProperties": false,
                "required": ["numerator_source_ids", "denominator_source_ids", "column_id"],
                "properties": {
                  "numerator_source_ids": { "type": "array", "minItems": 1, "maxItems": 100, "items": { "$ref": "common.schema.json#/$defs/source_id" } },
                  "denominator_source_ids": { "type": "array", "minItems": 1, "maxItems": 100, "items": { "$ref": "common.schema.json#/$defs/source_id" } },
                  "column_id": { "type": "string", "pattern": "^col_[0-9A-Za-z]{8,40}$" }
                }
              },
              { "type": "null" }
            ],
            "description": "Set on a counting sentence ('4 of 6 full-text-read sources...'); code checks the members actually carry that column value and reading depth, are distinct sources, and that the numbers in the text match the member counts (§6, §8)."
          },
          "equation_origin": {
            "anyOf": [
              {
                "type": "object",
                "additionalProperties": false,
                "required": ["passage_id", "text_source"],
                "properties": {
                  "passage_id": { "$ref": "common.schema.json#/$defs/passage_id" },
                  "text_source": { "type": "string", "enum": ["text_layer", "ocr", "marker"] }
                }
              },
              { "type": "null" }
            ],
            "description": "Set on a claim carrying a displayed equation; the named passage must be in the StepInput and must itself contain a math span (checked in code)."
          },
          "gap_refs": {
            "type": "array",
            "maxItems": 10,
            "description": "VI and VII only.",
            "items": { "type": "string", "pattern": "^gap[0-9]{1,3}$" }
          }
        }
      }
    },
    "citation_anchors": {
      "type": "array",
      "maxItems": 300,
      "description": "One anchor per claim-evidence pair. Exactly one of passage_id/cell_id is non-null (checked in code): a cell-based claim's anchor is located in the cell's current revision's stored evidence quotes (cell_evidence_links.anchor_text via the frozen snapshot), never in the passage directly.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["claim_key", "passage_id", "cell_id", "quote"],
        "properties": {
          "claim_key": { "type": "string", "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}$" },
          "passage_id": { "anyOf": [{ "$ref": "common.schema.json#/$defs/passage_id" }, { "type": "null" }] },
          "cell_id": { "anyOf": [{ "type": "string", "pattern": "^cel_[0-9A-Za-z]{8,40}$" }, { "type": "null" }] },
          "quote": { "type": "string", "minLength": 12, "maxLength": 600 }
        }
      }
    },
    "subsections": {
      "type": "array",
      "maxItems": 20,
      "description": "III and IV only: theme headings derived from plan axes. A subsection without a matching plan axis, or a claim's axis_id without a matching subsection here, is a schema/assembly violation.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["axis_id", "heading"],
        "properties": {
          "axis_id": { "type": "string", "pattern": "^AX[0-9]{1,2}$" },
          "heading": { "type": "string", "minLength": 1, "maxLength": 120 }
        }
      }
    },
    "gaps": {
      "type": "array",
      "maxItems": 40,
      "description": "VI only: candidate unanswered aspects this section introduces. corpus_absence candidates are code-generated before the call (report/gaps.py) and given via the allowlist; the model only writes their text and cites gap_refs. stated_limitation and conflicting_evidence candidates are found by the model itself and mint their own gap_id.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["gap_id", "kind", "text", "basis_claim_keys", "basis_passage_ids", "basis_cell_ids", "nearest_match"],
        "properties": {
          "gap_id": { "type": "string", "pattern": "^gap[0-9]{1,3}$" },
          "kind": {
            "type": "string",
            "enum": ["stated_limitation", "conflicting_evidence", "corpus_absence"],
            "description": "This v1 schema lists the three kinds this slice supports; a fourth kind (slice 2, Chain of Ideas) is a new schema version, not an open enum here. The storage column report_gaps.kind is plain TEXT validated in code against domain.contracts.GAP_KINDS, precisely so slice 2 can extend the list without a migration."
          },
          "text": { "type": "string", "maxLength": 2000 },
          "basis_claim_keys": { "type": "array", "maxItems": 10, "items": { "type": "string", "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}$" } },
          "basis_passage_ids": { "type": "array", "maxItems": 20, "items": { "$ref": "common.schema.json#/$defs/passage_id" } },
          "basis_cell_ids": { "type": "array", "maxItems": 100, "items": { "type": "string", "pattern": "^cel_[0-9A-Za-z]{8,40}$" } },
          "nearest_match": {
            "type": "object",
            "additionalProperties": false,
            "required": ["status", "source_id", "cell_id"],
            "properties": {
              "status": { "type": "string", "enum": ["found", "none_in_corpus", "not_searched"] },
              "source_id": { "anyOf": [{ "$ref": "common.schema.json#/$defs/source_id" }, { "type": "null" }] },
              "cell_id": { "anyOf": [{ "type": "string", "pattern": "^cel_[0-9A-Za-z]{8,40}$" }, { "type": "null" }] }
            }
          }
        }
      }
    },
    "insufficient_evidence": {
      "type": "array",
      "maxItems": 20,
      "description": "Recorded instead of forcing a claim when this section's required evidence is missing (e.g. no definition passage for a glossary term) (§4.3).",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["context", "reason"],
        "properties": {
          "context": { "type": "string", "maxLength": 200 },
          "reason": { "$ref": "common.schema.json#/$defs/short_text" }
        }
      }
    }
  }
}
```

### `contracts/research/report-phrase-repair.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/report-phrase-repair.schema.json",
  "title": "ReportPhraseRepairDraft",
  "description": "A rewrite of the sentences of one report section that followed no phrasebank frame (§8). Anchors, sources, counts and math ranges must stay unchanged from the original sentence; code checks this before storing a repair. Rewriting an unflagged sentence, or removing a qualifier or negation, is a report_review finding, not a schema violation.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "step_input_id", "scope_revision", "skill_package_hash", "repairs"],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.report_phrase_repair_draft.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "repairs": {
      "type": "array",
      "maxItems": 40,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["sentence_id", "text"],
        "properties": {
          "sentence_id": {
            "type": "string",
            "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}#[0-9]{1,2}$",
            "description": "claim_key '#' the sentence's 1-based order within that claim's text, exactly as given in the repair request."
          },
          "text": { "type": "string", "maxLength": 600 }
        }
      }
    }
  }
}
```

### `contracts/research/report-review.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/report-review.schema.json",
  "title": "ReportReview",
  "description": "An additional model's reading of a report's sections against their cited passages and cells, and of the section-8 rules. It is not peer review or independent verification and never changes the report; the one exception, reverting a phrase repair whose review finding is support_broken, is applied by code, not by this output.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "step_input_id", "scope_revision", "skill_package_hash", "findings", "notes"],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.report_review.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "findings": {
      "type": "array",
      "maxItems": 100,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["claim_key", "sentence_id", "code", "text"],
        "properties": {
          "claim_key": { "anyOf": [{ "type": "string", "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}$" }, { "type": "null" }] },
          "sentence_id": {
            "anyOf": [{ "type": "string", "pattern": "^[A-Za-z_]+\\.[0-9]{1,3}#[0-9]{1,2}$" }, { "type": "null" }],
            "description": "Set only when the finding is about one repaired sentence; code reverts that sentence's repair when code == support_broken."
          },
          "code": {
            "type": "string",
            "enum": ["support_broken", "count_error", "terminology_inconsistent", "abstract_body_mismatch", "equation_mismatch", "comparability_error", "other"]
          },
          "text": { "$ref": "common.schema.json#/$defs/short_text" }
        }
      }
    },
    "notes": { "type": "string", "maxLength": 1200 }
  }
}
```

### Değişen sözleşmeler (diff olarak, tam dosya değil)

- `contracts/research/step-input.schema.json`: `task_type` enum'una `"report_plan"`, `"report_section"`, `"report_phrase_repair"`, `"report_review"` eklenir. Yeni, `extraction_target`'ın kardeşi bir `report_target` alanı eklenir (StepInput'un `required` listesinde DEĞİL — `extraction_target` gibi yalnız ilgili görev türlerinde `check_step_input`'un yeni bir dalıyla zorunlu kılınır):

```json
"report_target": {
  "type": "object",
  "additionalProperties": false,
  "required": ["report_id", "section_id", "plan", "prior_summaries", "repair_request", "review_scope"],
  "properties": {
    "report_id": { "type": "string", "pattern": "^rpt_[0-9A-Za-z]{8,40}$" },
    "section_id": {
      "anyOf": [{ "type": "string", "enum": ["I", "III", "IV", "V", "VI", "VII", "VIII", "IX", "abstract", "index_terms"] }, { "type": "null" }]
    },
    "plan": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["scope_statement", "research_questions", "glossary", "axes", "corpus", "section_budgets", "allowed_support"],
          "properties": {
            "scope_statement": { "type": "string" },
            "research_questions": { "type": "array", "items": { "type": "object" } },
            "glossary": { "type": "array", "items": { "type": "object" } },
            "axes": { "type": "array", "items": { "type": "object" } },
            "corpus": {
              "type": "object", "additionalProperties": false,
              "required": ["found", "unique", "screened", "included", "full_text"],
              "properties": {
                "found": { "type": "integer" }, "unique": { "type": "integer" }, "screened": { "type": "integer" },
                "included": { "type": "integer" }, "full_text": { "type": "integer" }
              }
            },
            "section_budgets": {
              "type": "object", "additionalProperties": { "type": "object", "required": ["min_words", "max_words", "max_claims"],
                "additionalProperties": false, "properties": { "min_words": { "type": "integer" }, "max_words": { "type": "integer" }, "max_claims": { "type": "integer" } } }
            },
            "allowed_support": {
              "type": "object", "additionalProperties": { "type": "array", "items": { "type": "string", "enum": ["source_stated", "analyst_inference"] } }
            }
          }
        },
        { "type": "null" }
      ],
      "description": "report_plan (this validates the plan the model just wrote, before code appends corpus/section_budgets/allowed_support): null. report_section and report_phrase_repair: the frozen plan. report_review: null (review reads sections directly, not the plan echo)."
    },
    "prior_summaries": {
      "type": "array",
      "description": "report_section only: code-written one-line summaries of already-valid sections this call may build on (§4: 'özetleri kod üretir').",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["section_id", "claim_key", "first_sentence", "support_type", "reading_depth"],
        "properties": {
          "section_id": { "type": "string" }, "claim_key": { "type": "string" }, "first_sentence": { "type": "string" },
          "support_type": { "type": "string", "enum": ["source_stated", "analyst_inference"] },
          "reading_depth": { "type": "string", "enum": ["metadata", "abstract", "selected_sections", "full_text"] }
        }
      }
    },
    "repair_request": {
      "anyOf": [
        {
          "type": "object", "additionalProperties": false,
          "required": ["section_id", "sentences"],
          "properties": {
            "section_id": { "type": "string" },
            "sentences": {
              "type": "array",
              "items": {
                "type": "object", "additionalProperties": false,
                "required": ["sentence_id", "text", "support_type", "nearest_frames", "previous_sentence", "next_sentence"],
                "properties": {
                  "sentence_id": { "type": "string" }, "text": { "type": "string" },
                  "support_type": { "type": "string", "enum": ["source_stated", "analyst_inference"] },
                  "nearest_frames": { "type": "array", "maxItems": 3, "items": { "type": "string" } },
                  "previous_sentence": { "type": ["string", "null"] }, "next_sentence": { "type": ["string", "null"] }
                }
              }
            }
          }
        },
        { "type": "null" }
      ]
    },
    "review_scope": { "anyOf": [{ "type": "array", "items": { "type": "string" } }, { "type": "null" }] }
  }
}
```

`check_step_input` (task 1a) `EXTRACTION_TASKS`'a paralel bir `REPORT_TASKS = ("report_plan", "report_section", "report_phrase_repair", "report_review")` sabitiyle: `(target is not None) != (task_type in REPORT_TASKS)` denetimini `report_target` için tekrarlar; `report_section`/`report_phrase_repair` için `target["plan"] is not None`, `report_plan`/`report_review` için `target["plan"] is None` denetlenir.

## Migration: `backend/deixis/storage/migrations/0034_report_run_kind.sql`

0032'nin izlediği desen (SQLite CHECK genişletilemediği için tablo kopyalanır); `report_gaps.kind` bilerek düz `TEXT`'tir ve SQL `CHECK` almaz, çünkü slice 2 (Chain of Ideas) dördüncü bir tür ekleyecek ve o zaman migration değil yalnız `domain/contracts.py::GAP_KINDS` listesi genişleyecektir.

```sql
-- deixis:foreign-keys-off
-- The `report` run kind writes a section-by-section research report from the evidence table snapshot (P6 slice 1).
-- SQLite cannot widen a CHECK in place, so runs is rebuilt as in 0028/0032; migrate() checks foreign keys after commit.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT,
  error_json TEXT,
  budget_json TEXT NOT NULL,
  usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  -- Table runs: {"table_id", "column_ids", "cell_id", "include_stale"}. Report runs: {"report_id"}. NULL otherwise.
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO runs_new (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
                      usage_json, idempotency_key, target_json, version, created_at, updated_at)
  SELECT id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
         usage_json, idempotency_key, target_json, version, created_at, updated_at FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);

-- One report belongs to one research and one run kind='report'. report_version is assigned only when status
-- becomes 'valid' (parallel to answers.report_version, migration 0023); a 'draft' report has no report_version.
CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  scope_revision INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('in_progress', 'valid', 'draft')),
  language TEXT,
  plan_json TEXT,
  report_version INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX reports_report_version ON reports (research_id, report_version) WHERE report_version IS NOT NULL;
CREATE INDEX reports_research ON reports (research_id, created_at);

-- One row per section of one report. status mirrors the section state machine (see "Durum makineleri").
CREATE TABLE report_sections (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL CHECK (section_id IN ('I', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'abstract', 'index_terms')),
  step_id TEXT REFERENCES run_steps(id),
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'valid', 'draft', 'failed')),
  draft_json TEXT,
  validation_json TEXT,
  word_count INTEGER,
  ordinal INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (report_id, section_id)
);

-- One claim of one section, same shape as `claims` (migration 0007-era) with section_id carried by the parent row
-- instead of a free-text column, and the report-only fields (§4 "Bölüm şeması").
CREATE TABLE report_claims (
  id TEXT PRIMARY KEY,
  report_section_id TEXT NOT NULL REFERENCES report_sections(id),
  claim_key TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  paragraph INTEGER NOT NULL,
  text TEXT NOT NULL,
  support_type TEXT NOT NULL CHECK (support_type IN ('source_stated', 'analyst_inference')),
  table_ref TEXT,
  equation_ref TEXT,
  axis_id TEXT,
  count_json TEXT,
  equation_origin_json TEXT,
  UNIQUE (report_section_id, claim_key)
);

-- body_refs (abstract/I/IX -> body claim_key) and gap_refs (VI/VII -> gap_id) as rows, not JSON arrays, so assembly
-- checks (§8) can query them with SQL the same way evidence_links joins claims today.
CREATE TABLE report_claim_refs (
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  ref_kind TEXT NOT NULL CHECK (ref_kind IN ('body_ref', 'gap_ref')),
  ref_value TEXT NOT NULL
);
CREATE INDEX report_claim_refs_claim ON report_claim_refs (claim_id);

-- Same shape as evidence_links (migration 0007-era), except exactly one of passage_id/cell_id is set: a claim can
-- cite a table cell's stored evidence quote as well as, or instead of, a passage directly.
CREATE TABLE report_citation_links (
  id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  passage_id TEXT REFERENCES passages(id),
  cell_id TEXT REFERENCES evidence_cells(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  anchor_text TEXT,
  anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  CHECK ((passage_id IS NOT NULL) <> (cell_id IS NOT NULL))
);
CREATE INDEX report_citation_links_claim ON report_citation_links (claim_id);

-- kind is plain TEXT, checked in code against domain.contracts.GAP_KINDS, not a SQL CHECK: slice 2 (Chain of
-- Ideas) adds a fourth kind and must not require a migration to do it.
CREATE TABLE report_gaps (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  gap_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  basis_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  kill_search_status TEXT NOT NULL DEFAULT 'not_run' CHECK (kill_search_status IN ('not_run', 'narrowed', 'closed', 'open')),
  created_at TEXT NOT NULL,
  UNIQUE (report_id, gap_id)
);

-- §4.2's frozen evidence snapshot. snapshot_json holds the table/column/cell revisions, included source version ids
-- and reading depths, and corpus counts as they stood when the report run started.
CREATE TABLE report_snapshot (
  report_id TEXT PRIMARY KEY REFERENCES reports(id),
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  table_revision INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- One row per attempted targeted phrase repair (§8). outcome distinguishes a kept rewrite from the two exception
-- kinds decision 12 introduced: a review-reverted rewrite, and a rewrite that still fails the frame check.
CREATE TABLE report_phrase_repairs (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL,
  sentence_id TEXT NOT NULL,
  before TEXT NOT NULL,
  after TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('kept', 'reverted_exception', 'unframed_exception')),
  created_at TEXT NOT NULL
);
CREATE INDEX report_phrase_repairs_report ON report_phrase_repairs (report_id);
```

## Durum makineleri

### Çalışma (`runs.status`) — mevcut değerleri kullanır; rapor yeni bir `pause_reason` ekler

| Kimden | Olay | Kime | Not |
|---|---|---|---|
| queued | worker alır | running | mevcut |
| running | kullanıcı duraklatma isteği | paused (`pause_reason=user_requested`) | mevcut `_checkpoint` |
| running | çalışma sırasında kapsam revize edilir | cancelled (`pause_reason=scope_revised`) | mevcut `_checkpoint` |
| running | bir bölüm adımı `draft` döner (içerik denetimi geçmedi) | paused (`pause_reason=section_must_be_rewritten`) | YENİ: rapora özel duraklama nedeni; aynı turdaki bağımsız kardeş bölümler yine de biter ve saklanır |
| running | bir bölüm adımı `failed` döner (teknik olarak bitmedi) | paused (`pause_reason=section_failed`) | YENİ; `model_mismatch`, şema onarımı tükenmesi, `model_isolation_violation`, `budget_exhausted` içerir |
| running | tüm adımlar bitti, montaj temiz | completed | mevcut tamamlama yolu |
| running | çökme (worker yeniden başlar) | paused (`pause_reason=backend_restarted`) | mevcut `worker.py::recover()`, değişmedi; adım/model oturumu `outcome_unknown` olur |
| paused (section_must_be_rewritten / section_failed) | sahip devam eder | running → başarısız/draft bölüm adımı yeni bir `attempt` ile yeniden denenir | adım aynı `operation_key`'i korur |

### Bölüm (yeni `report_sections.status`)

| Durum | Anlam | Nereden girilir | Neyi durdurur |
|---|---|---|---|
| pending | henüz başlamadı | başlangıç | — |
| running | adım uçuşta | pending, ya da draft/failed'ten yeniden deneme | — |
| valid | içerik denetimleri geçti (çapa, kural, bütçe, kalıp ya da incelenmiş istisna) | running | hiçbir şey; bağımlı bölümlerin önünü açar |
| draft | teknik olarak tamamlanmış çıktı ama bir İÇERİK denetimi başarısız (çapa, kural, bütçe) | running | kendi turundaki bağımlıları; aynı turdaki bağımsız kardeşler yine de biter ve saklanır |
| failed | adım teknik olarak tamamlanmadı (model_mismatch, şema onarımı tükendi, isolation violation, budget_exhausted) | running | draft ile aynı |

`draft` ya da `failed` bir bölümü yeniden denemek aynı `operation_key` altında yeni bir adım denemesidir; başarılı olunca `valid` olur ve bağımlılar sürebilir.

### Rapor (yeni `reports.status`)

| Durum | Anlam | Nereden girilir |
|---|---|---|
| in_progress | en az bir bölüm henüz `valid` değil | başlangıç, ve `report_plan` başarılı olduktan sonra |
| valid | bütün bölümler `valid` VE montaj denetimi temiz | in_progress, son engelleyici koşul kalktığında |
| draft | montaj bütün bölümler teknik olarak bittikten sonra bir sorun buldu, ya da bir bölüm `draft`/`failed`'te takılı kaldı | in_progress |

`valid` yalnız yapısal geçerliliktir, asla semantik doğrulama değildir. `report_review` bulguları rapora eklenir ama `reports.status`'u asla değiştirmez (kod tarafından uygulanan tek istisna: destek bozan bir onarımın geri alınması, §8 karar 12). `report_version`, `answers.report_version`'daki gibi yalnız rapor `valid` olduğunda atanır (D23'ün paraleli); `draft` bir raporun `report_version`'u yoktur ve Markdown dışa aktarımı "TASLAK: <bölüm> doğrulanmadı" satırıyla başlar.

## Görevler

Sıra bağımlılık sırasıdır; her alt dilim kendi içinde çalışan, test edilebilir bir yazılım üretir. Kod örnekleri repodaki gerçek imzaları ve stilini kullanır (bkz. yukarıdaki araştırma bulguları); yer tutucu yoktur.

### 1a — Sözleşmeler + yöntem paketi + fake'ler

#### Task 1: Dört yeni JSON Schema dosyası ve `step-input.schema.json` genişletmesi

**Files:**
- Create: `contracts/research/report-plan.schema.json`, `contracts/research/report-section-draft.schema.json`, `contracts/research/report-phrase-repair.schema.json`, `contracts/research/report-review.schema.json` (içerikleri yukarıdaki "Şemalar" bölümünde tam olarak verildi; olduğu gibi kopyalanır).
- Modify: `contracts/research/step-input.schema.json` (`task_type` enum + `report_target`, yukarıdaki "Değişen sözleşmeler" bölümünde tam verildi).
- Test: `tests/test_contracts.py`

**Interfaces:**
- Consumes: yok (bu dilimin ilk adımı).
- Produces: dört yeni `$id` (`https://deixis.local/contracts/research/report-*.schema.json`); `contracts.SCHEMA_FILES`/`TASK_OUTPUTS`/`SCHEMA_VERSIONS` task 2'de bunlara referans verecek.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/test_contracts.py'ye eklenir
@pytest.mark.parametrize("name", ["ReportPlanDraft", "ReportSectionDraft", "ReportPhraseRepairDraft", "ReportReview"])
def test_new_report_schemas_are_valid_draft_2020_12_and_registered(name):
    assert name in contracts.SCHEMA_FILES
    Draft202012Validator.check_schema(contracts.load_schema(name))
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_contracts.py -k report_schemas -v`
Expected: FAIL — `AssertionError` çünkü `contracts.SCHEMA_FILES`'ta henüz `"ReportPlanDraft"` yok.

- [ ] **Step 3: Dört şema dosyasını ve `step-input.schema.json` değişikliğini yaz**

Yukarıdaki "Şemalar" bölümündeki dört dosyayı olduğu gibi `contracts/research/` altına yaz. `step-input.schema.json`'da `task_type.enum`'a dört değer ekle ve `properties`'e `report_target`'ı (yukarıdaki tam JSON) ekle; `required` listesine `report_target`'ı EKLEME (extraction_target gibi koşullu).

- [ ] **Step 4: `contracts.py`'de kaydet (task 2'yi önceden gerektirir, bu adım onunla birlikte koşulur)**

Bu adımın testi ancak task 2 tamamlanınca geçer; şimdilik dosyaları yaz ve commit'i task 2 ile birlikte yap.

---

#### Task 2: `domain/contracts.py` kayıt tabloları, `check_step_input` ve `validate_model_output` genişlemesi

**Files:**
- Modify: `backend/deixis/domain/contracts.py`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Consumes: `contracts.load_schema(name)`, `contracts._inline_common_refs`, `contracts.Issue`, `contracts.ValidationReport` (mevcut, değişmez).
- Produces: `contracts.GAP_KINDS: tuple[str, ...] = ("stated_limitation", "conflicting_evidence", "corpus_absence")`; `contracts.REPORT_TASKS: tuple[str, ...] = ("report_plan", "report_section", "report_phrase_repair", "report_review")`; `contracts._check_report_plan(step_input, result, report)`, `contracts._check_report_section(step_input, result, report)`, `contracts._check_report_phrase_repair(step_input, result, report)`, `contracts._check_report_review(step_input, result, report)` (görev 1e/1d/1f'te dolduruluyor; burada iskelet + zorunlu allowlist/envelope denetimleri).

- [ ] **Step 1: Başarısız testler yaz**

```python
# tests/fixtures/research/step-inputs.json'a "C_report_plan" eklenmeden önce basit bir sözlükle test edilir
def test_report_task_types_are_registered():
    for task in ("report_plan", "report_section", "report_phrase_repair", "report_review"):
        assert task in contracts.TASK_OUTPUTS
    assert contracts.SCHEMA_FILES["ReportPlanDraft"] == "report-plan.schema.json"
    assert contracts.SCHEMA_FILES["ReportSectionDraft"] == "report-section-draft.schema.json"
    assert contracts.SCHEMA_FILES["ReportPhraseRepairDraft"] == "report-phrase-repair.schema.json"
    assert contracts.SCHEMA_FILES["ReportReview"] == "report-review.schema.json"


def test_report_step_input_requires_report_target_only_for_report_tasks():
    si = json.loads(json.dumps(STEP_INPUTS["A_search_plan"]))
    si["allowlist"]["column_ids"] = []
    assert contracts.check_step_input(si) == []
    si["task_type"] = "report_plan"
    si["output_schema_versions"] = ["deixis.report_plan_draft.v1"]
    issues = {i.code for i in contracts.check_step_input(si)}
    assert "report_target_mismatch" in issues
```

- [ ] **Step 2: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_contracts.py -k report_task -v`
Expected: FAIL — `KeyError: 'report_plan'` (TASK_OUTPUTS'ta yok).

- [ ] **Step 3: `contracts.py`'yi genişlet**

```python
GAP_KINDS = ("stated_limitation", "conflicting_evidence", "corpus_absence")
REPORT_TASKS = ("report_plan", "report_section", "report_phrase_repair", "report_review")

SCHEMA_FILES |= {
    "ReportPlanDraft": "report-plan.schema.json",
    "ReportSectionDraft": "report-section-draft.schema.json",
    "ReportPhraseRepairDraft": "report-phrase-repair.schema.json",
    "ReportReview": "report-review.schema.json",
}
SCHEMA_VERSIONS |= {
    "ReportPlanDraft": "deixis.report_plan_draft.v1",
    "ReportSectionDraft": "deixis.report_section_draft.v1",
    "ReportPhraseRepairDraft": "deixis.report_phrase_repair_draft.v1",
    "ReportReview": "deixis.report_review.v1",
}
TASK_OUTPUTS |= {
    "report_plan": ("ReportPlanDraft",),
    "report_section": ("ReportSectionDraft",),
    "report_phrase_repair": ("ReportPhraseRepairDraft",),
    "report_review": ("ReportReview",),
}
```

`check_step_input`'e ekle (extraction_target dalının hemen altına):

```python
    target = step_input.get("extraction_target")
    if (target is not None) != (step_input["task_type"] in EXTRACTION_TASKS):
        issues.append(Issue("extraction_target_mismatch", "/extraction_target", step_input["task_type"]))
    elif step_input["task_type"] == "cell_extraction":
        ...  # değişmedi

    report_target = step_input.get("report_target")
    if (report_target is not None) != (step_input["task_type"] in REPORT_TASKS):
        issues.append(Issue("report_target_mismatch", "/report_target", step_input["task_type"]))
    elif step_input["task_type"] in ("report_section", "report_phrase_repair"):
        if report_target["plan"] is None:
            issues.append(Issue("report_plan_missing", "/report_target/plan", step_input["task_type"]))
        for axis in (report_target["plan"] or {}).get("axes", []):
            if axis["column_id"] not in allow.get("column_ids", set()):
                issues.append(Issue("axis_column_not_in_allowlist", "/report_target/plan/axes", axis["column_id"]))
    elif step_input["task_type"] in ("report_plan", "report_review") and report_target["plan"] is not None:
        issues.append(Issue("report_plan_must_be_null", "/report_target/plan", step_input["task_type"]))
```

`validate_model_output`'un dispatch bloğuna ekle:

```python
    elif output_type == "ReportPlanDraft":
        _check_report_plan(step_input, allow, result, report)
    elif output_type == "ReportSectionDraft":
        _check_report_section(step_input, allow, result, report)
        _check_phrasing(step_input, result, report, fields=_report_phrasing_fields(result))
        _check_math(step_input, result, report, fields=_report_math_fields(result))
    elif output_type == "ReportPhraseRepairDraft":
        _check_report_phrase_repair(step_input, result, report)
    elif output_type == "ReportReview":
        _check_report_review(step_input, result, report)
```

`_check_math`/`_check_phrasing` `draft["claims"]`/`draft["limitations"]`/`draft["unanswered_aspects"]` alan adlarına sabitlenmiştir (araştırmada doğrulandı); bu ikisine varsayılanı `None` olan bir `fields: list[tuple[str, str]] | None = None` parametresi eklenir — `None` iken bugünkü davranış (yanıt şeması) değişmez, verildiğinde doğrudan o listeyi denetler:

```python
def _check_math(step_input, draft, report, fields=None):
    if fields is None:
        fields = [(f"/claims/{i}/text", c["text"]) for i, c in enumerate(draft["claims"])]
        fields += [(f"/limitations/{i}/text", lim["text"]) for i, lim in enumerate(draft["limitations"])]
        fields += [(f"/unanswered_aspects/{i}", text) for i, text in enumerate(draft["unanswered_aspects"])]
    ...  # geri kalanı değişmedi, `fields`'i kullanır
```

(`_check_phrasing` de aynı desenle değiştirilir; `draft["answer_language"]` yerine rapor bölümünde dilin nereden geldiği task 1c'de netleşir — StepInput'un `question.language_hint`'inden, çünkü `ReportSectionDraft`'ta ayrı bir `answer_language` alanı yoktur, rapor dili sorunun diliyle sabittir.)

`_report_phrasing_fields(draft)` ve `_report_math_fields(draft)` yardımcıları (bu dosyada, `_check_report_section`'ın hemen üstünde): `draft["claims"]`'in `text` alanlarını `(f"/claims/{i}/text", c["text"])` biçiminde döner; `insufficient_evidence[].reason` de `_report_phrasing_fields`'e eklenir (o da düzyazıdır).

`_check_report_plan`, `_check_report_section`, `_check_report_phrase_repair`, `_check_report_review` şimdilik yalnız iskelet (envelope zaten üst düzeyde denetleniyor; boş gövde + `pass`), task 1c/1d/1e/1f'te dolduruluyor.

- [ ] **Step 4: Testleri çalıştır, geçtiklerini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_contracts.py -v`
Expected: PASS (yeni testler dahil, mevcutlar kırılmadı).

- [ ] **Step 5: Commit**

```bash
git add contracts/research/report-plan.schema.json contracts/research/report-section-draft.schema.json \
  contracts/research/report-phrase-repair.schema.json contracts/research/report-review.schema.json \
  contracts/research/step-input.schema.json backend/deixis/domain/contracts.py tests/test_contracts.py
git commit -m "Add report contract schemas and register the four report task types"
```

---

#### Task 3: `methods/deixis-research/references/report.md`, `SKILL.md`, `RUNTIME_FILES`, `provenance.json`

**Files:**
- Create: `methods/deixis-research/references/report.md`
- Modify: `methods/deixis-research/SKILL.md`, `methods/deixis-research/provenance.json`, `backend/deixis/domain/skill.py`
- Test: `tests/test_skill_package.py` (yoksa oluştur; `domain/skill.py`'nin bütünlük denetimini zaten bir yerde test eden dosya varsa oraya eklenir — `rg "integrity_issues" tests/` ile bulunur; bulunamazsa yeni dosya).

**Interfaces:**
- Consumes: `domain.skill.RUNTIME_FILES` (mevcut dict), `domain.skill.integrity_issues()`, `domain.skill.package_hash()`.
- Produces: `RUNTIME_FILES["report_plan"] = ("SKILL.md", "references/report.md")`, `RUNTIME_FILES["report_section"] = ("SKILL.md", "references/report.md", "references/source-grounded-answer.md", PHRASEBANK)`, `RUNTIME_FILES["report_phrase_repair"] = ("SKILL.md", "references/report.md")`, `RUNTIME_FILES["report_review"] = ("SKILL.md", "references/report.md")`.

- [ ] **Step 1: Başarısız test yaz**

```python
def test_report_task_types_load_the_report_reference_and_pass_integrity():
    from deixis.domain.skill import RUNTIME_FILES, integrity_issues
    for task in ("report_plan", "report_section", "report_phrase_repair", "report_review"):
        assert "references/report.md" in RUNTIME_FILES[task]
    assert integrity_issues() == []
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_skill_package.py -k report -v`
Expected: FAIL — `KeyError: 'report_plan'`.

- [ ] **Step 3: `references/report.md`'yi yaz**

```markdown
# Report

Read this after SKILL.md. It applies only to the four report task types (`report_plan`, `report_section`,
`report_phrase_repair`, `report_review`); an ordinary `grounded_answer` step never sees this file.

## What a report is

A report is a fixed-skeleton document written section by section, from the same evidence table and passages
the research already has. You never write the whole report in one call. Each call writes one part: the plan,
one section's claims, a targeted repair of a few flagged sentences, or a review of already-written sections.
The report never invents a related-work table in prose: Section IV's table is the evidence table itself,
given to you as rows and cited cells, and you discuss it — you do not restate it as a bullet list.

## Shared rules for every report step

- Everything in "Authority and data boundaries" and "Evidence rules" in SKILL.md applies unchanged: no tools,
  allowlisted IDs only, `source_stated` vs `analyst_inference`, reading depth, preprint/published independence.
- Write in the question's language (`question.language_hint`, or the question's own script if absent).
- A claim's `claim_key` is a label you assign once per call, matching `^[A-Za-z_]+\.[0-9]{1,3}$` (for example
  `IV.3`). Reuse the section identifier as the prefix.
- Cite only passage_ids and cell_ids from the allowlist. A citation_anchors quote must be the source's own
  contiguous words: for a cell_id citation, quote one of that cell's own stored evidence quotes; for a
  passage_id citation, quote the passage text exactly as in source-grounded-answer.md's citation rules.
- Mathematical content follows source-grounded-answer.md's rule 7 exactly: LaTeX between `$…$`/`$$…$$`, only
  what a passage's own definitions make unambiguous, variables and meanings before the objective before the
  constraints, and a checking note when the passage's `text_source` is `marker` or `ocr`.
- `paragraph` groups claims that belong in one flowing paragraph of the finished report; number them in the
  order they should read, starting at 1.
- Do not write a page, equation, table, figure or section number into claim text; use `table_ref`/`equation_ref`
  and the application inserts the printed number.
- A `count` claim ("4 of the 6 full-text sources...") must give the exact source_ids of the numerator and the
  denominator in the `count` field; the sentence's own numbers must match those counts, and every member you
  name must actually carry the column value and reading depth your sentence claims — the application checks
  this and rejects a count claim whose members do not match.
- If a plan glossary term, axis or budget's required evidence was not given to you (for example no definition
  passage for a term this section needed), do not force a claim. Write an `insufficient_evidence` entry
  instead, naming the missing context and why.
- The phrasebank frames you receive are limited to this section's own categories. A sentence in `claims[].text`
  or `insufficient_evidence[].reason` that keeps none of one frame's fixed words in order goes to a targeted
  repair call; write plainly and re-use frames rather than inventing new phrasing, since a sentence you cannot
  fit to a frame becomes an exception that is recorded and measured.

## Report plan (`report_plan`)

Write `scope_statement` (one paragraph, in the question's language, describing what the report covers and
why), `research_questions` (2 to 5, each a short `RQ`-numbered question the report's sections answer),
`glossary` (terms the report will define, each with a definition and the one passage_id it comes from — do not
invent a term without a defining passage in the allowlist) and `axes` (classification dimensions, each tied to
one evidence-table column_id from the allowlist; an axis without a matching column is rejected). Do not write
`corpus`, `section_budgets` or `allowed_support`: the application fills those from the evidence table and a
fixed policy after your plan is accepted. Do not repeat the whole question as `scope_statement`; write your own
one-paragraph account of its scope.

## Section instructions (`report_section`)

`report_target.section_id` tells you which section you are writing. Its evidence is in `sources`/`passages`
and, for table-grounded sections, in the extraction_target-style records the report_target carries; write only
that section, in fixed-skeleton order, and do not invent a section this report does not have.

- **III (Background and Taxonomy):** define the plan's glossary terms and axes using only their sourced
  definitions and axis-relevant passages. Use `subsections` for axis-organized theme groups when the plan has
  more than a couple of axes; give each subsection an `axis_id` matching the plan. Displayed equations belong
  here only when the question or plan's axes ask for a formulation; otherwise keep III definitional.
- **IV (Literature Synthesis):** discuss the evidence table's rows and cells; every claim that turns a cell
  value into a sentence cites that cell_id and quotes its stored evidence. Use `subsections` grouped by axis
  the same way as III. One claim with `table_ref: "TABLE_I"` and no other content may introduce the table
  itself before the discussion.
  - A `not_found_in_inspected_scope` cell of a full-text-read row may be described as "not reported in the
    inspected text". Never write "the study did not consider this" for a summary-only row; only a denominator
    sentence may mention summary-only rows in aggregate ("2 of 6 summary-only sources could not be assessed").
  - A cell whose extraction failed technically is not a `not_found` value and never enters a denominator.
  - Never infer a method or result from the gap between two unrelated cells.
- **V (Comparative Findings):** compare cells of one column across sources. A conflict claim requires the
  compared sources to share the same concept, condition and metric; when conditions differ, write "different
  conditions, different outcomes", not a conflict. Distinguish `demonstrated` findings from `modelled` or
  `proposed` ones in your wording; a modelled result and a demonstrated result are not equal-weight agreement
  or disagreement.
- **VI (Candidate Unanswered Aspects):** write the `gaps` array, not ordinary prose claims. For a
  `corpus_absence` gap given to you (its candidate and basis are already prepared), write only its `text` in
  the fixed pattern the application's basis describes, citing the given basis. For a `stated_limitation` gap,
  cite the source's own stated limitation (a "limitations" column cell or a passage) and mint a new `gap_id`.
  For a `conflicting_evidence` gap, cite the V claim_key it comes from. Every gap text ends with the sentence
  that it is a candidate and no kill-search was run; never use "gap", "open problem", "novel" or "first" (or
  their Turkish equivalents) anywhere, including implicitly restating them in other words.
- **VII (Future Directions):** every claim has a non-empty `gap_refs` pointing at a VI gap, OR cites a cell of
  the evidence table's "proposed future work" column (if the plan's axes include one). A future-work claim
  drawn from a source's own stated proposal is `source_stated`, cites that cell or passage, and is written as
  the source's own proposal, not the report's. An `analyst_inference` future-work claim must trace to a VI
  `gap_id`.
- **VIII (Limitations and Threats to Validity):** the application writes the numeric core (search/PDF/model
  counts) before your call; write only the prose sentences the application asks for (recall measurement
  caveats when one exists, open-access/upload bias, summary-vs-full-text ratio, share of analyst inference,
  absence of kill-search). Do not restate the numbers in different words that could drift from the code-written
  ones; reference them by the section's own numbered list, given in your input.
- **I (Introduction), IX (Conclusion), abstract, index_terms:** every claim has non-empty `body_refs` pointing
  at claim_keys of III-VIII already written; you receive only their one-line code-written summaries (claim_key,
  first sentence, support type, weakest reading depth), never their full text. Do not write a claim here that
  is not traceable to a body claim; do not generalize beyond what the summaries say. `index_terms` are chosen
  only from the given D44 concept vocabulary list; do not add a term that is not in that list.

## Phrase repair (`report_phrase_repair`)

You receive a small list of flagged sentences (their `sentence_id`, original text, support type, up to three
nearest phrasebank frames, and the sentence immediately before and after each). Rewrite only the flagged
sentences, each into one that keeps a frame's fixed words in order. Preserve every number, every citation
target implied by the sentence, every qualifier ("may", "some", "in the inspected text") and every negation.
Do not touch neighboring sentences. If none of the three given frames can honestly carry the sentence's
meaning, write the clearest plain sentence you can rather than distorting it — the application checks whether
your rewrite still reads as valid and may keep the original if your rewrite changes what is claimed.

## Report review (`report_review`)

Read one or more already-written sections against their cited passages and cells. Return a flat list of
findings; you never edit the report yourself. Use `support_broken` only for a repaired sentence (its
`sentence_id` set) whose meaning no longer matches what its citations support — the application reverts that
one sentence to its pre-repair text when you use this code. Use `count_error`, `terminology_inconsistent`,
`abstract_body_mismatch`, `equation_mismatch` or `comparability_error` for the corresponding semantic problems
named in this file's IV/V/VIII rules above that the application's own checks cannot see (word choice, whether
a compared pair is truly comparable, whether an equation reads as the passage states it, whether the abstract
says more than the body). Everything else is `other`. Passing structural checks earlier is not evidence that
meaning is correct; read for meaning.
```

- [ ] **Step 4: `SKILL.md`'yi güncelle**

"Choose the work" tablosuna dört satır ekle:

```markdown
| `report_plan` | [Report](references/report.md) — Report plan |
| `report_section` | [Report](references/report.md) — Section instructions |
| `report_phrase_repair` | [Report](references/report.md) — Phrase repair |
| `report_review` | [Report](references/report.md) — Report review |
```

Yasak paragrafını şu şekilde değiştir (VI/VII için daraltma, geri kalan tüm görevler için yasak aynen kalır):

```markdown
This version supports only source-grounded question answering and, for a report run, the fixed report
skeleton described in [report.md](references/report.md). Literature synthesis across idea chains, candidate
research-question development, claim-specific kill-search, and experiment design or execution are **not
available**. If the question asks for them outside a report's VI and VII sections, answer what the supplied
sources support, set `capability_notice` to say which requested part is not supported here, and do not
simulate the unsupported workflow. That includes proposing research gaps, directions or candidate questions
in a `grounded_answer`: do not offer them as claims, not even as `analyst_inference`; name them in
`unanswered_aspects` instead. A report's VI (Candidate Unanswered Aspects) and VII (Future Directions)
sections are the one place this version writes gap and future-direction material, under report.md's rules and
labelled as an unreviewed candidate; they never claim a verified research gap, and kill-search is still not
performed. Do not start candidate development or novelty assessment for an ordinary question or outside VI/VII.
```

- [ ] **Step 5: `RUNTIME_FILES`'ı güncelle (`backend/deixis/domain/skill.py`)**

```python
RUNTIME_FILES = {
    "search_plan": ("SKILL.md", "references/source-grounded-answer.md"),
    "screening": ("SKILL.md", "references/source-grounded-answer.md"),
    "grounded_answer": ("SKILL.md", "references/source-grounded-answer.md", PHRASEBANK),
    "answer_review": ("SKILL.md", "references/answer-review.md"),
    "cell_extraction": ("SKILL.md", "references/evidence-table.md"),
    "table_columns": ("SKILL.md", "references/evidence-table.md"),
    "research_title": ("SKILL.md", "references/research-title.md"),
    "report_plan": ("SKILL.md", "references/report.md"),
    "report_section": ("SKILL.md", "references/report.md", "references/source-grounded-answer.md", PHRASEBANK),
    "report_phrase_repair": ("SKILL.md", "references/report.md"),
    "report_review": ("SKILL.md", "references/report.md"),
}
```

- [ ] **Step 6: `provenance.json`'a girdi ekle**

```json
{
  "deixis_file": "references/report.md",
  "derived_from": [],
  "change": "Written for DEIXIS on 2026-09-17 (P6 slice 1), not adapted from upstream text. Applies SKILL.md's evidence rules to the fixed report skeleton: report_plan, per-section instructions for III-IX/abstract/index_terms, VI/VII's narrowed gap/future-direction exception to the candidate-development ban, phrase repair, and report review. Loaded into report_plan, report_section, report_phrase_repair and report_review steps only."
}
```

- [ ] **Step 7: Testi çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_skill_package.py -v`
Expected: PASS. `skill_package_hash` bu commit'ten sonra değişir; task 1a'daki fixture step-input'ların `skill_package_hash`'i SYNTHETIC sabit bir değerdir (gerçek hash'e bağlı değildir), o yüzden kırılmaz.

- [ ] **Step 8: Commit**

```bash
git add methods/deixis-research/references/report.md methods/deixis-research/SKILL.md \
  methods/deixis-research/provenance.json backend/deixis/domain/skill.py tests/test_skill_package.py
git commit -m "Add the report method reference and register its four task types in the loaded skill package"
```

---

#### Task 4: `tests/fakes.py` ve fixture'lar

**Files:**
- Modify: `tests/fakes.py`, `tests/fixtures/research/step-inputs.json`, `tests/fixtures/research/fake-outputs.json`

**Interfaces:**
- Consumes: `contracts.validate_model_output`, `contracts.check_step_input` (task 2).
- Produces: `STEP_INPUTS["C_report_plan"]`, `STEP_INPUTS["C_report_section_IV"]`, `STEP_INPUTS["C_report_phrase_repair"]`, `STEP_INPUTS["C_report_review"]` fixtures other tasks and tests read by these exact keys.

- [ ] **Step 1: `valid_response` içine dört yeni dal ekle**

```python
    if task == "report_plan":
        return json.dumps(envelope(si, "deixis.report_plan_draft.v1") | {
            "scope_statement": "SYNTHETIC scope covering release scheduling formulations in molecular communication.",
            "research_questions": [{"rq_id": "RQ1", "text": "SYNTHETIC: what decision variables are used?"}],
            "glossary": [{"term": "release scheduling", "definition": "SYNTHETIC definition.", "passage_id": si["passages"][0]["passage_id"]}],
            "axes": [],
        })
    if task == "report_section":
        first = si["passages"][0]
        return json.dumps(envelope(si, "deixis.report_section_draft.v1") | {
            "section_id": si["report_target"]["section_id"],
            "claims": [{"claim_key": f"{si['report_target']['section_id']}.1", "text": "It has been reported that the fake claim holds.",
                        "support_type": "source_stated", "passage_ids": [first["passage_id"]], "cell_ids": [], "paragraph": 1,
                        "table_ref": None, "equation_ref": None, "body_refs": [], "axis_id": None, "count": None,
                        "equation_origin": None, "gap_refs": []}],
            "citation_anchors": [{"claim_key": f"{si['report_target']['section_id']}.1", "passage_id": first["passage_id"],
                                  "cell_id": None, "quote": " ".join(first["text"].split())[:600]}],
            "subsections": [], "gaps": [], "insufficient_evidence": [],
        })
    if task == "report_phrase_repair":
        return json.dumps(envelope(si, "deixis.report_phrase_repair_draft.v1") | {
            "repairs": [{"sentence_id": r["sentence_id"], "text": "It has been reported that the rewritten sentence holds."}
                        for r in si["report_target"]["repair_request"]["sentences"]],
        })
    if task == "report_review":
        return json.dumps(envelope(si, "deixis.report_review.v1") | {"findings": [], "notes": ""})
```

- [ ] **Step 2: Fixture'lara `C_report_plan`, `C_report_section_IV`, `C_report_phrase_repair`, `C_report_review` ekle**

`A_answer`'ın `sources`/`passages`'ını temel alan, `task_type` ve `report_target` alanları değişen dört yeni anahtar `step-inputs.json`'a eklenir (aynı `research_id`/kaynak/pasaj kimlikleriyle, `report_target` alanı task 1a'daki şemaya uygun dolu). `fake-outputs.json`'a en az bir `expect_ok: true` durumu (`report_section_valid`) ve bir `expect_ok: false` durumu (`report_section_unknown_gap_ref` — var olmayan bir `gap_id`'ye referans veren bir VII iddiası) eklenir.

- [ ] **Step 3: Testleri çalıştır**

Run: `PYTHONPATH=backend uv run pytest tests/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fakes.py tests/fixtures/research/step-inputs.json tests/fixtures/research/fake-outputs.json
git commit -m "Add fake responses and fixtures for the four report task types"
```

### 1b — Depolama + kanıt anlık görüntüsü + tablo hazır koşulu

#### Task 1: Migration 0034

**Files:**
- Create: `backend/deixis/storage/migrations/0034_report_run_kind.sql` (yukarıdaki "Migration" bölümünde tam verildi).
- Test: `tests/test_migrations.py` (yoksa `rg "def test.*migrat" tests/` ile bulunan dosyaya eklenir; genelde `storage/db.py::migrate()`'i boş bir SQLite dosyasına uygulayan bir test vardır).

**Interfaces:**
- Consumes: `deixis.storage.db.migrate(conn)` (mevcut).
- Produces: `reports`, `report_sections`, `report_claims`, `report_claim_refs`, `report_citation_links`, `report_gaps`, `report_snapshot`, `report_phrase_repairs` tabloları; `runs.kind` CHECK'inde `'report'`.

- [ ] **Step 1: Başarısız test yaz**

```python
def test_migration_0034_adds_report_tables_and_run_kind(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    db.migrate(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"reports", "report_sections", "report_claims", "report_claim_refs",
            "report_citation_links", "report_gaps", "report_snapshot", "report_phrase_repairs"} <= tables
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_x', 't', 'now', 'now')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_x', 'res_x', 1, 'report', 'queued', 'synthesis', '{}', 'now', 'now')")  # must not raise
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_migrations.py -k report -v`
Expected: FAIL — `sqlite3.IntegrityError: CHECK constraint failed: kind` (migration 0034 henüz yok).

- [ ] **Step 3: Migration dosyasını yaz** (içerik yukarıda, "Migration" bölümünde tam).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/storage/migrations/0034_report_run_kind.sql tests/test_migrations.py
git commit -m "Add the report run kind and its storage tables (migration 0034)"
```

---

#### Task 2: `ReportStore` iskeleti

**Files:**
- Create: `backend/deixis/workflow/report/__init__.py`, `backend/deixis/workflow/report/store.py`
- Test: `tests/test_report_store.py`

**Interfaces:**
- Consumes: `deixis.workflow.store.Store` (`self.conn`, `new_id`, `now`, `dumps`, `transaction` — `deixis.storage.db`'den, `Store`'un kendisinin yaptığı gibi).
- Produces:

```python
class ReportStore:
    def __init__(self, store: Store): self.store = store; self.conn = store.conn
    def create_report(self, research_id: str, run_id: str, scope_revision: int, language: str | None) -> str: ...
    def report(self, report_id: str) -> dict[str, Any]: ...
    def set_plan(self, report_id: str, plan: dict[str, Any]) -> None: ...
    def create_section(self, report_id: str, section_id: str, ordinal: int) -> str: ...
    def section(self, report_id: str, section_id: str) -> dict[str, Any]: ...
    def sections(self, report_id: str) -> list[dict[str, Any]]: ...
    def save_section_draft(self, report_section_id: str, step_id: str, status: str, draft: dict[str, Any] | None,
                           validation: dict[str, Any], word_count: int | None) -> None: ...
    def save_claims(self, report_section_id: str, claims: list[dict[str, Any]], citation_links: list[dict[str, Any]]) -> None: ...
    def save_gaps(self, report_id: str, gaps: list[dict[str, Any]]) -> None: ...
    def save_phrase_repair(self, report_id: str, section_id: str, sentence_id: str, before: str, after: str, outcome: str) -> None: ...
    def finalize(self, report_id: str, status: str) -> int | None:  # returns the assigned report_version, or None for 'draft'
        ...
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_report_store_creates_a_report_and_its_sections_in_order(lib):
    store, report_store = lib, ReportStore(lib)
    rid = store.create_research("Q?", "academic", "quick", ["openalex"], "fake", None, None)
    report_id = report_store.create_report(rid, "run_x", 1, "en")
    report_store.create_section(report_id, "III", 1)
    report_store.create_section(report_id, "IV", 2)
    sections = report_store.sections(report_id)
    assert [s["section_id"] for s in sections] == ["III", "IV"]
    assert all(s["status"] == "pending" for s in sections)
```

(`lib` fixture'ı `tests/test_evidence_tables.py`'nin kullandığı, geçici bir SQLite dosyasına bağlı `Store` döner — aynı fixture reuse edilir.)

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_store.py -v`
Expected: FAIL — `ModuleNotFoundError: deixis.workflow.report.store`.

- [ ] **Step 3: `ReportStore`'u yaz** (yukarıdaki arayüzü `TableStore`'un append-only, `run_id`/`step_id` alanlarını olduğu gibi taşıyan desenini izleyerek doldur; `save_claims` `report_claim_refs`'e `body_refs`/`gap_refs`'i satır satır yazar; `finalize` `report_sections` tablosunun tamamı `'valid'` mi diye SQL'de kontrol eder ve öyleyse `SELECT COALESCE(MAX(report_version), 0) + 1 FROM reports WHERE research_id = ?` ile bir sonraki `report_version`'u atar, hepsi tek transaction).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/__init__.py backend/deixis/workflow/report/store.py tests/test_report_store.py
git commit -m "Add ReportStore for report, section, claim and gap persistence"
```

---

#### Task 3: Kanıt anlık görüntüsü (`snapshot.py`) ve tablo hazır koşulu

**Files:**
- Create: `backend/deixis/workflow/report/snapshot.py`
- Modify: `backend/deixis/workflow/tables.py` (yalnız yeni bir okuma fonksiyonu ekler, mevcut fonksiyonlara dokunmaz)
- Test: `tests/test_report_snapshot.py`

**Interfaces:**
- Consumes: `TableStore.active_rows`, `Store.included_works`, `Store.passages_for`, evidence_cells/cell_revisions okuma SQL'i (task 1b'nin araştırmasında dökülen şema).
- Produces:

```python
# backend/deixis/workflow/tables.py'ye eklenir
def report_ready(store: Store, research_id: str, table_id: str, continue_with_failed: bool = False) -> dict[str, Any]:
    """§6 tablo hazır koşulu: her dahil kaynak x her sütun hücresi son durumda mı, yoksa satır 'failed' ve sahip
    devam etmeyi mi seçti. Returns {"ready": bool, "missing": [{"source_version_id", "column_id"}], "failed_rows": [...]}."""

# backend/deixis/workflow/report/snapshot.py
def build_snapshot(store: Store, research_id: str, table_id: str) -> dict[str, Any]:
    """§4.2: tablo/sütun revizyonu, her hücrenin geçerli revizyonu ve alıntıları, dahil kaynakların sürüm
    kimlikleri ve okuma derinlikleri, corpus sayıları. Saf okuma; hiçbir şey yazmaz."""
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_report_ready_requires_every_included_source_and_column_to_have_a_terminal_cell(lib):
    ...  # bir dahil kaynak + bir sütun kur, hücreyi doldurmadan report_ready(...)["ready"] is False,
         # hücreyi 'value' yaptıktan sonra True olduğunu doğrular


def test_snapshot_freezes_cell_values_and_corpus_counts_independent_of_later_edits(lib):
    ...  # anlık görüntü alındıktan SONRA bir hücre insanla düzenlenirse snapshot_json değişmez
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_snapshot.py -v`
Expected: FAIL — `AttributeError`/`ModuleNotFoundError`.

- [ ] **Step 3: `report_ready` ve `build_snapshot`'ı yaz**

`report_ready`: `TableStore.active_rows(table_id)` ile `target_columns(...)` çarpımının her hücresi için `evidence_cells.current_revision_id IS NOT NULL AND cell_revisions.state IN ('value','unknown','not_applicable','not_found_in_inspected_scope','not_verified')` mi diye SQL JOIN; olmayan her (kaynak, sütun) çifti `missing`'e girer; `continue_with_failed=True` iken teknik olarak başarısız (`inaccessible` + `model_fill` denemesi yapılmış ama sonuç yoksa) satırlar hariç tutulur ve `failed_rows`'a yazılır.

`build_snapshot`: `evidence_tables`/`table_columns`/`column_revisions`/`table_rows`/`evidence_cells`/`cell_revisions`/`cell_evidence_links` üzerinde salt okunur SELECT'lerle bir JSON sözlük kurar: `{"table_revision": ..., "columns": [{"column_id","revision","name","instruction","answer_format"}], "rows": [{"source_version_id","version_label","reading_depth"}], "cells": [{"column_id","source_version_id","state","value","reading_depth","evidence": [{"passage_id","quote"}]}], "corpus": {"found","unique","screened","included","full_text"}}`. `corpus` sayıları `search_runs`/`candidates`/`corpus_memberships`/`passages` üzerinden §5'teki tanımlarla hesaplanır (`found` = başarılı `search_runs.result_count` toplamı; `unique` = `works` sayısı; `screened` = tarama adımına giren aday sayısı; `included` = geçerli kapsam revizyonunda `corpus_memberships.removed_at IS NULL` sayısı; `full_text` = dahil kaynaklardan `passages.kind='pdf_page'` sahibi olanların sayısı).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_snapshot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/snapshot.py backend/deixis/workflow/tables.py tests/test_report_snapshot.py
git commit -m "Add the report evidence snapshot and the table-ready condition"
```

### 1c — Bölüm başına kanıt seçimi + rapor planı + bölüm adımları + turlar

#### Task 1: `selection.py` — §4.3 kanıt seçimi ve kesilme kaydı

**Files:**
- Create: `backend/deixis/workflow/report/selection.py`
- Test: `tests/test_report_selection.py`

**Interfaces:**
- Consumes: `report/snapshot.py::build_snapshot` çıktısı, `Store.search_passages`, `Store.passages_for`.
- Produces:

```python
SECTION_BUDGET_TOKENS = {"III": 6000, "IV": 10000, "V": 8000, "VI": 6000, "VII": 4000, "VIII": 3000, "I": 3000, "IX": 3000, "abstract": 1500, "index_terms": 500}

def select_evidence(snapshot: dict[str, Any], section_id: str, plan: dict[str, Any],
                    prior_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns {"passages": [...], "cells": [...], "truncated": [{"source_version_id", "record_kind"}]}."""
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_select_evidence_for_iv_gives_every_rows_cells_and_records_truncation_beyond_budget():
    snapshot = {...}  # 30 satırlı sahte anlık görüntü, her satırda 2 hücre
    picked = select_evidence(snapshot, "IV", {"axes": []}, [])
    assert len(picked["cells"]) <= SECTION_BUDGET_TOKENS["IV"] // 40  # kaba bir üst sınır varsayımı, gerçek sayı testte sabitlenir
    assert picked["truncated"]  # 30 satır bütçeyi aşacak şekilde kurulmuştur
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_selection.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `select_evidence`'ı §4.3'teki tabloya göre yaz**

Her `section_id` için §4.3'ün "Uygun kayıtlar"/"Sıralama" sütunlarını uygular (III: sözlük terimi tanım pasajları + eksen pasajları, RRF; IV: bütün satırların hücreleri, tablo sırası; V: eksen sütunu hücreleri + farklı değerli satırların pasajları; VI: yokluk toplamları + sınırlama hücreleri + V çelişkileri; VII: VI adayları + "önerilen gelecek çalışma" hücreleri). Bütçeyi aşan kayıtlar `truncated`'a `{"source_version_id", "record_kind"}` olarak eklenir, seçime girmez.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_selection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/selection.py tests/test_report_selection.py
git commit -m "Add per-section evidence selection with a truncation record"
```

---

#### Task 2: `plan.py` — `report_plan` adımı, `corpus`/`section_budgets`/`allowed_support` kod eklentisi

**Files:**
- Create: `backend/deixis/workflow/report/plan.py`
- Test: `tests/test_report_plan.py`

**Interfaces:**
- Consumes: `report/snapshot.py::build_snapshot`, `contracts.step_output_schema("report_plan")`, `flow.ResearchFlow._model_step` (task 1c-3'te bağlanacak; burada saf fonksiyon olarak test edilir).
- Produces:

```python
ALLOWED_SUPPORT = {"I": ("source_stated", "analyst_inference"), "III": ("source_stated",), "IV": ("source_stated",),
                   "V": ("source_stated", "analyst_inference"), "VI": ("analyst_inference",),
                   "VII": ("analyst_inference", "source_stated"), "VIII": ("source_stated", "analyst_inference"),
                   "IX": ("source_stated", "analyst_inference"), "abstract": ("source_stated", "analyst_inference"),
                   "index_terms": ("source_stated",)}

def section_budgets(total_words: int, included_count: int) -> dict[str, dict[str, int]]:
    """§15.2: total 4000-7000, en geniş pay IV'e, sonra III ve V'e; n<10 ise n/10 ile ölçekle, taban 1200 toplam."""

def freeze_plan(model_plan: dict[str, Any], snapshot: dict[str, Any], included_count: int) -> dict[str, Any]:
    """Model çıktısına corpus (snapshot'tan), section_budgets ve allowed_support'u ekler ve dondurur."""
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_section_budgets_scale_down_for_small_corpora_with_a_1200_word_floor():
    full = section_budgets(5500, 20)
    small = section_budgets(5500, 4)
    assert sum(b["max_words"] for b in small.values()) < sum(b["max_words"] for b in full.values())
    assert sum(b["min_words"] for b in small.values()) >= 1200 * 4 // 10 or sum(b["max_words"] for b in small.values()) >= 1200


def test_freeze_plan_adds_corpus_and_never_lets_the_model_set_it():
    model_plan = {"scope_statement": "x", "research_questions": [], "glossary": [], "axes": []}
    snapshot = {"corpus": {"found": 40, "unique": 22, "screened": 22, "included": 8, "full_text": 5}}
    frozen = freeze_plan(model_plan, snapshot, included_count=8)
    assert frozen["corpus"] == snapshot["corpus"]
    assert frozen["allowed_support"]["VI"] == ["analyst_inference"]
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_plan.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `plan.py`'yi yaz**

`section_budgets`: sabit oran tablosu (IV en büyük pay, sonra III ve V, sonra VI, geri kalanlar eşit küçük pay) `total_words`'e uygulanır; `included_count < 10` ise `total_words *= included_count / 10` ve `total_words = max(total_words, 1200)`; her bölüme `{"min_words": int(0.6*max_words), "max_words": max_words, "max_claims": 40}` yazılır (`max_claims` sabit 40, §"Global Constraints"). `freeze_plan`: `model_plan | {"corpus": snapshot["corpus"], "section_budgets": section_budgets(...), "allowed_support": ALLOWED_SUPPORT}`.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_plan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/plan.py tests/test_report_plan.py
git commit -m "Add report plan freezing: code-computed corpus, section budgets and allowed support"
```

---

#### Task 3: `sections.py` — turlar (A–D) ve `flow.py` bağlaması

**Files:**
- Create: `backend/deixis/workflow/report/sections.py`
- Modify: `backend/deixis/workflow/flow.py`
- Test: `tests/test_report_flow.py`

**Interfaces:**
- Consumes: `ReportFlow._model_step` (slice 0'ın eklediği `limiter: ModelCallLimiter | None = None` son parametresiyle, `task_type` yeni değerlerle çağrılır), `report/plan.py`, `report/selection.py`, `report/store.py::ReportStore`, `report/snapshot.py`, `backend/deixis/workflow/concurrency.py::ModelCallLimiter` ve `FlowDeps.limiter` (slice 0, gerçek API: `ModelCallLimiter(limit)`, `.limit`, `async def reduce() -> int`, `async def run(key, factory) -> T`; `slot()` diye bir bağlam yöneticisi YOKTUR).
- Produces:

```python
# backend/deixis/workflow/report/sections.py
ROUNDS: tuple[tuple[str, ...], ...] = (("III", "IV", "V"), ("VI",), ("VII",), ("VIII",), ("I", "IX", "abstract", "index_terms"))

async def run_report(flow: "ResearchFlow", run: dict[str, Any], scope: dict[str, Any]) -> None:
    """§4 adım 0-9: ön koşul + anlık görüntü, report_plan, research_title+II, turlar A-D, montaj, report_review."""
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_report_run_completes_with_fake_adapter_and_produces_a_valid_report(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        upload_and_include_one_source(client, rid)  # yardımcı, task 1g'de api testleriyle paylaşılır
        fill_the_evidence_table(client, rid)  # slice 0 sonrası eş zamanlı fill; burada FakeAdapter ile tek kaynak
        started = client.post(f"/api/researches/{rid}/reports", json={}, headers={"Idempotency-Key": "r1"})
        assert started.status_code == 202, started.text
        view, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed"
        report = client.get(f"/api/researches/{rid}/reports/{started.json()['target']['report_id']}").json()
        assert report["status"] == "valid" and report["report_version"] == 1
        assert [s["section_id"] for s in report["sections"]] == ["III", "IV", "V", "VI", "VII", "VIII", "I", "IX", "abstract", "index_terms"]
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_flow.py -v`
Expected: FAIL — `404 Not Found` (rota yok, task 1g'de gelecek) ya da `ModuleNotFoundError`.

- [ ] **Step 3: `run_report`'u yaz**

```python
async def run_report(flow, run, scope):
    run_id, rid = run["id"], run["research_id"]
    tables, reports = TableStore(flow.store), ReportStore(flow.store)
    table_id = run["target"]["table_id"]
    flow._checkpoint(run_id)
    readiness = report_ready_check := tables_module.report_ready(flow.store, rid, table_id)
    if not readiness["ready"]:
        flow._fail(run_id, "table_not_ready", readiness)
    report_id = run["target"]["report_id"]
    snapshot = build_snapshot(flow.store, rid, table_id)
    reports.save_snapshot(report_id, table_id, snapshot)  # tek kez, adım tekrar çağrılırsa idempotent (upsert)

    plan_output = await flow._model_step(run, scope, "report_plan", "report_plan",
                                         report_target={"report_id": report_id, "section_id": None, "plan": None,
                                                        "prior_summaries": [], "repair_request": None, "review_scope": None},
                                         limiter=flow.deps.limiter)
    flow._checkpoint(run_id)
    if plan_output.get("invalid"):
        flow._fail(run_id, "invalid_model_output", {"step": "report_plan", "issues": plan_output["issues"]})
    frozen = freeze_plan(plan_output["result"], snapshot, len(tables.active_rows(table_id)))
    reports.set_plan(report_id, frozen)

    await flow._research_title(run, scope, optional=False)  # başlık, planın scope_statement'ından (§15.1)
    write_review_methodology_core(flow.store, reports, report_id, snapshot)  # II, kod

    for round_ids in ROUNDS:
        flow._checkpoint(run_id)
        results = await asyncio.gather(*(_run_section(flow, run, scope, reports, report_id, frozen, snapshot, sid)
                                          for sid in round_ids), return_exceptions=True)
        failure = next((result for result in results if isinstance(result, BaseException)), None)
        if failure is not None:
            raise failure
        flow._checkpoint(run_id)
        if any(status == "draft" for status in results):
            flow._pause(run_id, "section_must_be_rewritten", {"sections": [s for s, r in zip(round_ids, results) if r == "draft"]})
        if any(status == "failed" for status in results):
            flow._pause(run_id, "section_failed", {"sections": [s for s, r in zip(round_ids, results) if r == "failed"]})

    issues = run_assembly_checks(flow.store, reports, report_id)
    if issues:
        reports.finalize(report_id, "draft")
        flow.store.update_run(run_id, event="report_assembly_failed", pause_reason=None)
    else:
        version = reports.finalize(report_id, "valid")
        flow.store.update_run(run_id, event="report_finalized", pause_reason=None)
    await run_report_review(flow, run, scope, reports, report_id)
```

(`_run_section` bölüm başına: `select_evidence` çağırır, `prior_summaries`'i o ana kadar `valid` bölümlerden kod üretir, phrasebank'i bölüme göre süzer (task 1d), aşağıdaki gibi `report_section` adımını çağırır, montaj-öncesi kalıp denetimini yapar (task 1d), sonucu `report_sections.status`'e yazar ve `"valid"|"draft"|"failed"` döner:

```python
async def _run_section(flow, run, scope, reports, report_id, frozen_plan, snapshot, section_id):
    evidence = select_evidence(snapshot, section_id, frozen_plan, reports.prior_summaries(report_id))
    reports.record_truncation(report_id, section_id, evidence["truncated"])
    target = {"report_id": report_id, "section_id": section_id, "plan": frozen_plan,
             "prior_summaries": reports.prior_summaries(report_id), "repair_request": None, "review_scope": None}
    operation_key = f"report_section:{section_id}"
    async def call():
        return await flow._model_step(run, scope, operation_key, "report_section",
                                      passage_rows=evidence["passages"], report_target=target,
                                      limiter=flow.deps.limiter)
    output = await flow.deps.limiter.run(operation_key, call)
    if output.get("invalid"):
        reports.save_section_draft(reports.section(report_id, section_id)["id"], output.get("step_id"), "failed", None,
                                   {"ok": False, "issues": output["issues"]}, None)
        return "failed"
    draft = output["result"]
    language = phrasebank.frames_language(await_step_input_of(output))  # sorunun dili; rapor cevapla aynı kural
    flagged = flagged_sentences(section_id, draft["claims"], phrasebank_text(), language)
    if flagged:
        draft, repairs = await repair_section(flow, run, scope, report_id, section_id, draft, flagged)
    status = "valid"  # montaj öncesi bölüm-yerel denetimler (çapa, bütçe) burada da tekrarlanabilir; tam denetim task 1e'de rapor genelinde
    reports.save_claims_and_status(report_id, section_id, draft, status)
    return status
```

`asyncio.gather`'a verilen her `_run_section(...)` çağrısının kendisi eş zamanlı çalışır (Python coroutine'leri `await` noktalarında birbirine geçer); üst sınır, çağrıyı yapan rapor kodunun `_table_fill` ile aynı biçimde uyguladığı `flow.deps.limiter.run(operation_key, factory)` sarmalamasından gelir. `_model_step` içindeki `_call_adapter` yalnız kota yanıtından sonra `limiter.reduce()` çağırır. Bir tur hata verdiğinde bekleyen görevler tüketilmeden hata yükseltilmez; hiçbir uçuş halindeki çağrı turdan uzun yaşayamaz.

`flow.py`'ye ekle:

```python
    async def execute(self, run_id: str) -> None:
        ...
        elif run["kind"] == "report":
            await self._report(run, scope)
        ...

    async def _report(self, run, scope):
        from deixis.workflow.report.sections import run_report
        await run_report(self, run, scope)
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula** (task 1g'deki rotalar tamamlanınca)

Run: `PYTHONPATH=backend uv run pytest tests/test_report_flow.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/sections.py backend/deixis/workflow/flow.py tests/test_report_flow.py
git commit -m "Run the report as a sequence of concurrent rounds with pause on a draft or failed section"
```

### 1d — Kalıp süzgeci, en yakın kalıplar, hedefli onarım, istisnalar

#### Task 1: `phrasebank.render`/`unframed`'e bölüm süzgeci

**Files:**
- Modify: `backend/deixis/domain/phrasebank.py`, `backend/deixis/domain/skill.py`, `backend/deixis/models/prompt.py`
- Test: `tests/test_phrasebank.py` (mevcut dosyaya eklenir; `rg "def test" backend/deixis/domain/phrasebank.py`'nin test dosyası karşılığı budur, yoksa `tests/domain/test_phrasebank.py`)

**Interfaces:**
- Consumes: `phrasebank.parse`, `phrasebank.Frame` (mevcut, değişmez).
- Produces:

```python
def render(text: str, language: str, sections: Sequence[str] | None = None) -> str:  # imza genişler, geriye dönük uyumlu
def unframed(text: str, phrasebank_text: str, language: str, sections: Sequence[str] | None = None) -> list[str]:
```

Bölüm→phrasebank kategorisi eşlemesi (spec §4.1, gerçek `phrases.md` başlıklarıyla doğrulanmış):

```python
REPORT_PHRASEBANK_SECTIONS = {
    "I": ("Writing Introductions", "Signalling Transition"),
    "III": ("Defining Terms", "Classifying and Listing", "Signalling Transition"),
    "IV": ("Referring to Literature", "Signalling Transition"),
    "V": ("Comparing and Contrasting", "Being Critical", "Signalling Transition"),
    "VI": ("Being Cautious", "Discussing Findings", "Signalling Transition"),
    "VII": ("Being Cautious", "Discussing Findings", "Signalling Transition"),
    "VIII": ("Being Cautious", "Discussing Findings", "Signalling Transition"),
    "IX": ("Writing Conclusions", "Signalling Transition"),
    "abstract": ("Writing Conclusions", "Signalling Transition"),
    "index_terms": (),
}
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_render_with_sections_filter_keeps_only_named_top_level_sections():
    text = load_phrasebank_text()  # references/phrases.md
    filtered = phrasebank.render(text, "en", sections=("Defining Terms",))
    assert "# Defining Terms" in filtered
    assert "# Reporting Results" not in filtered
    assert phrasebank.render(text, "en") == phrasebank.render(text, "en", sections=None)  # geriye dönük uyum


def test_unframed_with_sections_filter_does_not_credit_a_frame_from_an_excluded_section():
    text = load_phrasebank_text()
    # "Reporting Results" bölümündeki bir kalıba tam uyan ama "Defining Terms" dışındaki bir cümle,
    # yalnız Defining Terms süzülünce "unframed" sayılmalı.
    sentence = "The results clearly show a significant improvement."  # Reporting Results kalıbı
    assert sentence in phrasebank.unframed(sentence, text, "en", sections=("Defining Terms",))
    assert sentence not in phrasebank.unframed(sentence, text, "en", sections=("Reporting Results",))
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/domain/test_phrasebank.py -k sections_filter -v`
Expected: FAIL — `TypeError: render() got an unexpected keyword argument 'sections'`.

- [ ] **Step 3: `phrasebank.py`'yi genişlet**

```python
def render(text: str, language: str, sections: Sequence[str] | None = None) -> str:
    header, frames = parse(text)
    if sections is not None:
        frames = [f for f in frames if f.section in sections]
    out = [line for line in header if not line.startswith("tr:")]
    ...  # geri kalanı değişmedi


def _patterns(phrasebank_text: str, language: str, sections: tuple[str, ...] | None = None) -> tuple[_Pattern, ...]:
    _, frames = parse(phrasebank_text)
    if sections is not None:
        frames = [f for f in frames if f.section in sections]
    ...  # geri kalanı değişmedi; @lru_cache anahtarına `sections` eklenir (tuple olduğu için hashlenebilir)


def unframed(text: str, phrasebank_text: str, language: str, sections: Sequence[str] | None = None) -> list[str]:
    patterns = _patterns(phrasebank_text, language, tuple(sections) if sections is not None else None)
    return [s for s in sentences(text) if not _follows(s, patterns, language)]
```

`_patterns`'in `@lru_cache(maxsize=4)`'ü `maxsize=32`'ye çıkar (bölüm başına ayrı önbellek girdisi tutmak için; 10 bölüm × 2 dil = 20 olası anahtar).

`skill.py::SkillPackage.runtime_text`'e `sections` parametresi:

```python
    def runtime_text(self, task_type: str, language: str = "en", sections: Sequence[str] | None = None) -> str:
        def body(name: str) -> str:
            return render(self.files[name], language, sections) if name == PHRASEBANK else self.files[name]
        return "\n\n".join(f"<method-file path=\"{name}\">\n{body(name)}\n</method-file>" for name in RUNTIME_FILES[task_type])
```

`prompt.py::developer_instructions`'a aynı parametre (varsayılan `None`, geriye dönük uyumlu):

```python
def developer_instructions(package: SkillPackage, task_type: str, language: str = "en", sections: Sequence[str] | None = None) -> str:
    return package.runtime_text(task_type, language, sections)
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/domain/test_phrasebank.py -v`
Expected: PASS. Ayrıca değişmeyen çağrı yerlerini doğrula: `PYTHONPATH=backend uv run pytest tests/test_contracts.py tests/test_api_flow.py -v` (grounded_answer/answer_review hâlâ `sections=None` ile eskisi gibi çalışır).

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/domain/phrasebank.py backend/deixis/domain/skill.py backend/deixis/models/prompt.py tests/domain/test_phrasebank.py
git commit -m "Filter the phrasebank by report section before rendering or checking phrasing"
```

---

#### Task 2: `nearest_frames` — hedefli onarım için en yakın üç kalıp

**Files:**
- Modify: `backend/deixis/domain/phrasebank.py`
- Test: `tests/domain/test_phrasebank.py`

**Interfaces:**
- Consumes: `_words`, `_patterns`, `_score` (mevcut, dosya içi).
- Produces: `phrasebank.nearest_frames(sentence: str, phrasebank_text: str, language: str, sections: Sequence[str] | None = None, k: int = 3) -> list[str]` (en yakın `k` kalıbın okunabilir metnini döner, en yakından en uzağa).

- [ ] **Step 1: Başarısız test yaz**

```python
def test_nearest_frames_ranks_the_closest_matching_frame_first():
    text = load_phrasebank_text()
    sentence = "This work show that molecule budget matter for the results."  # bozuk ama "Reporting Results" kalıbına yakın
    frames = phrasebank.nearest_frames(sentence, text, "en", sections=("Reporting Results",), k=3)
    assert len(frames) == 3
    assert all(isinstance(f, str) and f for f in frames)
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/domain/test_phrasebank.py -k nearest_frames -v`
Expected: FAIL — `AttributeError: module 'phrasebank' has no attribute 'nearest_frames'`.

- [ ] **Step 3: `nearest_frames`'i yaz**

`_Pattern`'e orijinal metni tutan bir alan eklenmez (mevcut `_Pattern`'i bozmamak için); onun yerine `_patterns_with_text` adında paralel, `_compile`'ın kaynağını da döndüren yeni bir yardımcı eklenir:

```python
@lru_cache(maxsize=32)
def _patterns_with_text(phrasebank_text: str, language: str, sections: tuple[str, ...] | None = None) -> tuple[tuple[_Pattern, str], ...]:
    _, frames = parse(phrasebank_text)
    if sections is not None:
        frames = [f for f in frames if f.section in sections]
    pairs = []
    for frame in frames:
        if language not in frame.text:
            continue
        text = frame.text[language]
        for piece in ([text] if "{" in text else sentences(text)):
            if pattern := _compile(piece, language, {n.lower() for n in _EXAMPLE_NAME.findall(phrasebank_text)} | {"et", "al"}):
                pairs.append((pattern, piece))
    return tuple(pairs)


def nearest_frames(sentence: str, phrasebank_text: str, language: str, sections: Sequence[str] | None = None, k: int = 3) -> list[str]:
    """The k phrasebank frames whose fixed words best match `sentence`, best first. Used only to prompt a targeted
    phrase repair; a returned frame is not guaranteed to fit the sentence's meaning (that is for the model to judge)."""
    words = _words(sentence, language)
    pairs = _patterns_with_text(phrasebank_text, language, tuple(sections) if sections is not None else None)
    ranked = sorted(pairs, key=lambda pair: -_score(pair[0], words))
    seen, out = set(), []
    for _, text in ranked:
        if text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) == k:
            break
    return out
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/domain/test_phrasebank.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/domain/phrasebank.py tests/domain/test_phrasebank.py
git commit -m "Add nearest_frames for the targeted report phrase repair prompt"
```

---

#### Task 3: `phrasing.py` — hedefli onarım orkestrasyonu ve istisnalar

**Files:**
- Create: `backend/deixis/workflow/report/phrasing.py`
- Test: `tests/test_report_phrasing.py`

**Interfaces:**
- Consumes: `phrasebank.unframed`, `phrasebank.nearest_frames`, `ReportStore.save_phrase_repair`, `flow.ResearchFlow._model_step` (`report_phrase_repair` task type ile).
- Produces:

```python
def flagged_sentences(section_id: str, claims: list[dict[str, Any]], phrasebank_text: str, language: str) -> list[dict[str, Any]]:
    """§8: bölümün her cümlesini REPORT_PHRASEBANK_SECTIONS[section_id] ile denetler; uymayanları sentence_id +
    en yakın 3 kalıp + önceki/sonraki cümleyle döner."""

async def repair_section(flow, run, scope, report_id, section_id, draft, flagged) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bir kez onarım çağrısı yapar (§8: 'en fazla bir kez'); onarılmış metni draft'a uygular, her onarımı
    ReportStore.save_phrase_repair ile 'kept' olarak kaydeder (report_review'dan sonra revert/unframed_exception'a
    geçebilir, bkz. task 1f). Onarımdan sonra hâlâ uymayan cümleler 'unframed_exception' olarak işaretlenir ve
    bölümü taslağa düşürmez (§8 karar 12)."""
```

- [ ] **Step 1: Başarısız test yaz**

```python
def test_flagged_sentences_only_checks_claims_and_insufficient_evidence_reasons():
    claims = [{"claim_key": "IV.1", "text": "Fig weiro randomtext not a frame sentence at all zzq."}]
    flagged = flagged_sentences("IV", claims, load_phrasebank_text(), "en")
    assert flagged and flagged[0]["sentence_id"].startswith("IV.1#")
    assert len(flagged[0]["nearest_frames"]) == 3


async def test_repair_section_applies_the_rewrite_and_records_a_kept_outcome(tmp_path):
    ...  # FakeAdapter ile report_phrase_repair çağrısı; sonuç draft'a yazılır, ReportStore'da 'kept' kaydı var
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_phrasing.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `phrasing.py`'yi yaz**

`flagged_sentences`: her `claim["text"]`'i (ve `insufficient_evidence[].reason`'ı) `phrasebank.sentences()` ile cümlelere böler, her cümleyi `phrasebank.unframed(sentence, text, language, sections=REPORT_PHRASEBANK_SECTIONS[section_id])` ile denetler; uymayan her cümle için `sentence_id = f"{claim_key}#{order}"`, `nearest_frames(sentence, text, language, sections=..., k=3)`, `previous_sentence`/`next_sentence` (aynı claim içindeki komşu cümleler, yoksa `None`).

`repair_section`: `flagged` boşsa hiçbir şey yapmadan `(draft, [])` döner. Doluysa `report_phrase_repair` StepInput'unu (`report_target.repair_request`) kurar ve bölüm çağrıları içinde eş zamanlı çalışabileceği için `_model_step` fabrikasını `flow.deps.limiter.run(f"report_phrase_repair:{section_id}", factory)` ile gönderir; fabrika yeniden gönderim için aynı limiter'ı `_model_step(..., limiter=flow.deps.limiter)` çağrısına geçirir. Sonucu `sentence_id`'ye göre orijinal cümlelerin yerine koyar (claim metni yeniden birleştirilir), sayıların/atıfların/matematik aralıklarının onarımdan önce ve sonra aynı kaldığını kod tarafında karşılaştırır (bir claim_key için önce/sonra `re.findall(r"\d+(?:\.\d+)?", text)` çoklu kümesi ve `_math_spans` çıktısı eşit mi). Aynı kalmadıysa o cümle onarılmamış sayılır ve `unframed_exception` olarak kaydedilir; aynı kaldıysa `kept` olarak kaydedilir ve draft'a uygulanır. Onarımdan sonra hâlâ `unframed(...)` cümle içeren varsa onlar da `unframed_exception`'dır — hiçbiri bölümü `draft`'a düşürmez.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_phrasing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/phrasing.py tests/test_report_phrasing.py
git commit -m "Add the targeted phrase repair call and its unframed-exception bookkeeping"
```

### 1e — Kod yazımlı II/VIII çekirdeği + adaylar + montaj denetimi

#### Task 1: II Review Methodology (tümüyle kod)

**Files:**
- Create: `backend/deixis/workflow/report/review_methodology.py`
- Test: `tests/test_report_review_methodology.py`

**Interfaces:**
- Consumes: `report/snapshot.py`'nin `corpus` alanı, `Store.run_steps` (sağlayıcı sorguları ve tarihleri için), `providers/registry.CONNECTORS`.
- Produces: `write_review_methodology(store: Store, reports: ReportStore, report_id: str, research_id: str, snapshot: dict[str, Any]) -> None` — `report_sections`'a `section_id="II"` olarak `status="valid"`, model çağırmadan, düz metin `draft_json` yazar.

- [ ] **Step 1: Başarısız test yaz**

```python
def test_review_methodology_reports_corpus_counts_and_provider_dates_without_a_model_call(lib):
    ...  # bir arama çalışması + tarama + dahil kaynak kur, write_review_methodology çağır
    section = reports.section(report_id, "II")
    assert section["status"] == "valid" and section["step_id"] is None  # model çağrısı yok
    assert str(snapshot["corpus"]["found"]) in section["draft_json"]["text"]
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_review_methodology.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `write_review_methodology`'yi yaz**

Sağlayıcıları ve derlenmiş sorgu sürümünü (`query_compiler.VERSION`) `run_steps` tablosundan (`kind LIKE 'provider_search:%'`) okur; `corpus` sayılarını `snapshot["corpus"]`'tan alır; PDF edinme yollarını (`fetch_pdf`/`pdf_other_copy` adım sayıları) ve tam metin oranını (`full_text / included`) hesaplar; tarama ölçütünü (`screening` StepInput'unun `capabilities`/`budget`'ından model kimliğini) ekler. Sabit bir şablon cümleyle (İngilizce/Türkçe değil — bölüm dili sorunun dili, ama II tümüyle kod yazımı olduğundan iki dilde de sabit iki cümle kalıbı tutulur, `report/review_methodology.py` içinde `_TEMPLATES = {"en": "...", "tr": "..."}`) bir `text` üretir ve `reports.save_section_draft(..., section_id="II", status="valid", draft={"text": ...}, validation={"ok": True, "issues": []}, word_count=...)` çağırır.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_review_methodology.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/review_methodology.py tests/test_report_review_methodology.py
git commit -m "Write Section II (Review Methodology) entirely from recorded counts, no model call"
```

---

#### Task 2: VIII Limitations kod çekirdeği

**Files:**
- Modify: `backend/deixis/workflow/report/review_methodology.py` (aynı dosyaya `limitations_core` eklenir, ayrı görev ama tek dosya — ikisi de yalnız `snapshot`/`run_steps` okur)
- Test: `tests/test_report_review_methodology.py`

**Interfaces:**
- Produces: `limitations_core(store: Store, snapshot: dict[str, Any], phrase_repair_stats: dict[str, int]) -> dict[str, Any]` — VIII'in `report_target`'ına eklenecek, modelin sadece cümleye döktüğü sayısal çekirdek (§3: "kod + model").

- [ ] **Step 1: Başarısız test yaz**

```python
def test_limitations_core_lists_recall_pdf_bias_summary_ratio_and_no_kill_search(lib):
    core = limitations_core(store, snapshot, {"repaired": 2, "reverted_exception": 0, "unframed_exception": 1})
    assert core["summary_to_full_text_ratio"] == pytest.approx(...)
    assert core["kill_search_status"] == "not_run"
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_review_methodology.py -k limitations_core -v`
Expected: FAIL — `NameError`.

- [ ] **Step 3: `limitations_core`'u yaz**

`{"recall_measurement": None | {...D55 tarzı bilinen küme ölçümü varsa}, "open_access_bias_note": True, "summary_to_full_text_ratio": (included - full_text)/included, "analyst_inference_share": (bölüm iddialarında support_type='analyst_inference' oranı, montajdan sonra hesaplanır — bu fonksiyon yalnız iskelet sayıları verir, oran task 1e-4'te montajdan geçince eklenir), "kill_search_status": "not_run", "phrase_repair_exceptions": phrase_repair_stats}` döner. Bu sözlük VIII'in `report_target.plan`'ının yanına `report_target`'a ayrı bir `limitations_core` alanı olarak eklenir (StepInput şemasına `report_target.limitations_core: object|null` eklenir — task 1a'nın şemasına küçük bir ek; `additionalProperties:false` kuralına uyularak `required` listesine de eklenir).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_review_methodology.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/review_methodology.py contracts/research/step-input.schema.json tests/test_report_review_methodology.py
git commit -m "Add the Section VIII numeric core the model writes its limitation sentences from"
```

---

#### Task 3: `gaps.py` — `corpus_absence` adaylarının kod tarafından üretilmesi

**Files:**
- Create: `backend/deixis/workflow/report/gaps.py`
- Test: `tests/test_report_gaps.py`

**Interfaces:**
- Consumes: `snapshot["cells"]`, `snapshot["rows"]` (task 1b).
- Produces: `generate_corpus_absence_candidates(snapshot: dict[str, Any], axes: list[dict[str, Any]]) -> list[dict[str, Any]]` — her uygun eksen için bir aday `{"gap_id", "kind": "corpus_absence", "column_id", "basis_cell_ids", "full_text_applicable_count", "summary_only_count"}` döner; §7 kuralına göre en az 3 tam-metinli-ve-uygulanabilir satır yoksa aday üretilmez.

- [ ] **Step 1: Başarısız test yaz**

```python
def test_corpus_absence_requires_at_least_three_full_text_applicable_not_found_rows():
    snapshot = {"cells": [
        {"column_id": "col_x", "source_version_id": f"srv_{i}", "state": "not_found_in_inspected_scope", "reading_depth": "full_text"}
        for i in range(2)
    ], "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text"} for i in range(2)]}
    assert generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}]) == []

    snapshot["cells"] += [{"column_id": "col_x", "source_version_id": "srv_2", "state": "not_found_in_inspected_scope", "reading_depth": "full_text"}]
    snapshot["rows"] += [{"source_version_id": "srv_2", "reading_depth": "full_text"}]
    candidates = generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}])
    assert len(candidates) == 1 and candidates[0]["full_text_applicable_count"] == 3


def test_not_applicable_cells_never_count_as_absence_evidence():
    snapshot = {"cells": [{"column_id": "col_x", "source_version_id": f"srv_{i}", "state": "not_applicable", "reading_depth": "full_text"} for i in range(5)],
                "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text"} for i in range(5)]}
    assert generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}]) == []
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_gaps.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `generate_corpus_absence_candidates`'ı yaz**

Her eksen için `column_id`'nin hücrelerini `reading_depth == "full_text"` VE `state != "not_applicable"` ile filtreler ("uygulanabilir" = `not_applicable` değil); bunların hepsi `state == "not_found_in_inspected_scope"` ise ve sayıları `>= 3` ise bir aday üretir; `summary_only_count`'u aynı sütunda `reading_depth != "full_text"` olan satır sayısı olarak ekler (§6 karar 10'daki "yalnız özeti incelenen k çalışma değerlendirilemedi" cümlesi için).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_gaps.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/gaps.py tests/test_report_gaps.py
git commit -m "Generate corpus_absence gap candidates in code from full-text-read cells only"
```

---

#### Task 4: `assembly.py` — §8 montaj denetimi (§8 listesindeki HER kural için bir test)

**Files:**
- Create: `backend/deixis/workflow/report/assembly.py`
- Test: `tests/test_report_assembly.py`

**Interfaces:**
- Consumes: `ReportStore.sections`, `report_claims`/`report_claim_refs`/`report_citation_links`/`report_gaps` okuma SQL'i, `contracts.locate_anchor`, `phrasebank` (sözlük terimi geçişi için dize eşleşmesi).
- Produces: `run_assembly_checks(store: Store, reports: ReportStore, report_id: str) -> list[dict[str, Any]]` — boşsa rapor `valid` olur; her öğe `{"rule", "section_id", "detail"}`.

Her kural §8 listesindeki maddeye ve "Kim neyi doğrular" tablosundaki sütuna birebir karşılık gelir; bu eşleme aşağıdaki tabloda açıkça verilir, böylece hiç kimse kodun *anlamı* doğruladığını iddia edemez:

| # | §8 kuralı | "Kim neyi doğrular" sütunu | Test |
|---|---|---|---|
| 1 | Aynı `claim_key` iki yerde | (yapı; tabloda yok, montaj kendi başına) | `test_duplicate_claim_key_across_sections_is_an_error` |
| 2 | Sözlük terimi tanımından önce kullanılmışsa uyarı | Terimler → "sözlük terimlerinin geçişi" | `test_glossary_term_used_before_its_definition_section_is_a_warning` |
| 3 | Abstract/I/IX her iddiası `body_refs` ile bağlı | Türetilmiş iddia → "`body_refs`, miras alınan derinlik" | `test_abstract_claim_without_body_refs_is_an_error` |
| 4 | Türetilmiş iddia daha güçlü destek/derinlik taşıyamaz | Türetilmiş iddia → "`body_refs`, miras alınan derinlik" | `test_derived_claim_cannot_claim_stronger_support_than_its_body_refs` |
| 5 | `count` alanları doğrulanır | Sayım cümleleri → "üyeler, derinlik, sayılar" | `test_count_members_must_carry_the_claimed_column_value_and_depth`, `test_count_numbers_in_text_must_match_member_counts` |
| 6 | Yasak sözcük listesi başlık dahil her yerde | Yasak sözcükler → "liste eşleşmesi" | `test_banned_words_are_rejected_even_in_the_title` |
| 7 | II ve VIII sayıları `corpus` ile birebir aynı | (kod yazdığı için modelin üretemeyeceği bir fark; yapı denetimi) | `test_section_ii_and_viii_numbers_match_the_frozen_corpus` |
| 8 | Her atıf kaynakçada, her kaynakça kaydı en az bir atıfta | (yapı; tabloda yok) | `test_every_citation_is_in_the_bibliography_and_vice_versa` |
| 9 | VII'deki her yön bir `gap_id`'ye ya da hücreye bağlı; VI'daki her aday §7 dayanağına bağlı | Yokluk → "tam metinli ≥3 satır, hepsi not_found, not_applicable hariç" | `test_vii_claim_without_gap_ref_or_future_work_cell_is_an_error`, `test_vi_corpus_absence_gap_without_three_full_text_rows_is_an_error` |
| 10 | Toplam ve bölüm kelime sayısı bütçede | (yapı; tabloda yok) | `test_section_word_count_over_budget_is_an_error` |
| 11 | Matematik aralıkları iyi biçimli; `equation_origin` pasajı girdide var ve pasajda matematik aralığı var | Denklem → "köken pasajı, iyi biçim" | `test_equation_claim_origin_passage_must_contain_a_math_span` |
| 12 | Atıf ve çapa: çapa pasajda ya da hücre alıntısında birebir var | Atıf ve çapa → "çapa pasajda ya da hücre alıntısında birebir var" | `test_cell_based_claim_anchor_is_checked_against_the_cells_stored_evidence_quote` |
| 13 | Çelişki iddiası V iddiasına bağlı | Çelişki → "V iddiasına bağ" | `test_conflicting_evidence_gap_must_reference_a_v_claim_key` |
| 14 | Kalıp: %70 sabit sözcük; onarımda sayı/atıf/matematik değişmedi | Kalıp → "%70 sabit sözcük; onarımda sayı/atıf/matematik değişmedi" | `test_unrepaired_unframed_sentence_outside_exceptions_is_an_error` (istisna değilse hata; task 1d zaten istisnaları işaretledi, burada yalnız işaretsiz kalan denetlenir) |

- [ ] **Step 1: Başarısız testler yaz** (yukarıdaki tablonun her satırı için bir test; tek dosyada, küçük sahte `ReportStore` verisiyle — örnek iki tanesi)

```python
def test_abstract_claim_without_body_refs_is_an_error(report_with_sections):
    report_id, reports = report_with_sections(sections={"abstract": [{"claim_key": "abstract.1", "body_refs": []}]})
    issues = run_assembly_checks(store, reports, report_id)
    assert any(i["rule"] == "body_ref_missing" and i["section_id"] == "abstract" for i in issues)


def test_cell_based_claim_anchor_is_checked_against_the_cells_stored_evidence_quote(report_with_sections):
    report_id, reports = report_with_sections(...)  # bir cell_id atıfı, alıntısı o hücrenin cell_evidence_links'inde YOK
    issues = run_assembly_checks(store, reports, report_id)
    assert any(i["rule"] == "anchor_not_in_cell_quote" for i in issues)
```

(Kalan 12 test aynı `report_with_sections` fixture'ıyla, tablo satırlarındaki adlarla yazılır.)

- [ ] **Step 2: Çalıştır, hepsinin başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_assembly.py -v`
Expected: FAIL (14 test, `ModuleNotFoundError`).

- [ ] **Step 3: `run_assembly_checks`'i yaz**

Her kural için ayrı bir `_check_*` iç fonksiyonu; hücre tabanlı bir iddianın çapası **`cell_evidence_links.anchor_text`/`quote`** üzerinden `contracts.locate_anchor`'a değil, doğrudan o hücrenin geçerli revizyonunun (`report_snapshot.snapshot_json["cells"]`, kanıt donduğu için CANLI `cell_evidence_links` değil) saklı alıntı listesindeki bir alıntıyla birebir (normalize edilmiş) eşleşiyor mu diye denetlenir — pasaj tabanlı bir iddia gibi yeniden `locate_anchor` çağrılmaz, çünkü hücrenin alıntısı zaten kendi extraction adımında bir kez `locate_anchor`'dan geçmiştir; burada yalnız modelin quote'unun o alıntıyla (ya da onun bir alt dizesiyle) eşleştiği denetlenir. Türetilmiş iddianın derinlik/destek mirası: `body_refs`'teki her `claim_key`'in `report_claims.support_type`'ı ve o iddianın kendi `report_citation_links`'inden `passages`/`cells` üzerinden çözülen `reading_depth`'i alınır, en zayıfı (`analyst_inference` > `source_stated` güç sırasında daha zayıf; `metadata` < `abstract` < `selected_sections` < `full_text` derinlik sırasında en zayıfı) türetilmiş iddiaya üst sınır olur.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_assembly.py -v`
Expected: PASS (14/14).

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/assembly.py tests/test_report_assembly.py
git commit -m "Add the report assembly checks, one test per section-8 rule"
```

### 1f — `report_review` ve destek-bozan onarımın geri alınması

#### Task 1: `review.py`

**Files:**
- Create: `backend/deixis/workflow/report/review.py`
- Test: `tests/test_report_review.py`

**Interfaces:**
- Consumes: `flow.ResearchFlow._model_step` (`report_review` task type), `ReportStore.sections`, `ReportStore.save_phrase_repair` (outcome güncellemesi için).
- Produces: `async def run_report_review(flow, run, scope, reports: ReportStore, report_id: str) -> None`.

- [ ] **Step 1: Başarısız test yaz**

```python
async def test_report_review_reverts_only_the_sentence_whose_finding_is_support_broken(tmp_path):
    ...  # bir onarılmış cümle kur (outcome='kept'), report_review FakeAdapter'ı support_broken bulgusu döndürsün
    await run_report_review(flow, run, scope, reports, report_id)
    repair = reports.phrase_repair(report_id, "IV", "IV.1#1")
    assert repair["outcome"] == "reverted_exception"
    section = reports.section(report_id, "IV")
    assert "before-repair text" in section["draft_json"]["claims"][0]["text"]  # geri alındı
    assert section["status"] == "valid"  # inceleme durumu değiştirmez
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_review.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `run_report_review`'ı yaz**

Bağlam sığmazsa (§8: "her çağrı bir bölüm ve onun kanıtı") bölüm başına bir `report_review` çağrısı + bir de abstract-gövde tutarlılığı için ayrı bir çağrı yapılır (bu dilimde basitleştirme: hepsi tek çağrıda denenir, `review_scope` StepInput alanına verilen bölüm kimlikleri listesiyle; bağlam sığmazsa `_model_step`'in kendi `budget.max_model_calls` sınırı zaten adımı `budget_exhausted` ile durdurur ve inceleme "incelenmedi" işaretlenir — ayrı bölüm-bölüm dallanma dilim 4'e bırakılmaz, ama burada minimal biçimde tek çağrı yeterlidir çünkü R10 ölçümü de tek çağrı varsayar). `optional=True` ile çağrılır (§8: "İnceleme başarısız olursa rapor geçerliliğini korur"). Sonuç geldiğinde her `finding.code == "support_broken"` için `finding.sentence_id`'nin ait olduğu `report_phrase_repairs` satırını `before` metniyle geri yazar (`ReportStore.revert_repair(report_id, section_id, sentence_id)` — draft_json'daki ilgili claim metnini `before`'a döner, `outcome`'u `reverted_exception` yapar), diğer bulgular yalnız `reports.save_review(report_id, output["result"])` ile saklanır ve `reports.status` değişmez.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/review.py tests/test_report_review.py
git commit -m "Add report_review and the code-applied revert of a support-broken phrase repair"
```

### 1g — API + görünüm modelleri

#### Task 1: `ReportStore.request_report` ve rotalar

**Files:**
- Modify: `backend/deixis/api/app.py`, `backend/deixis/workflow/report/store.py`
- Test: `tests/test_report_api.py`

**Interfaces:**
- Consumes: tabloların `request_fill`/`request_column_suggestions` deseni (`api/app.py`'den doğrulandı: `POST .../fill` → `tables_of(request).request_fill(...)` → `worker.wake()`).
- Produces:

```python
# ReportStore
def request_report(self, research_id: str, table_id: str, idempotency_key: str | None) -> dict[str, Any]:
    """§4 ön koşulunu denetler (dahil kaynak var, tablo hazır — tables.report_ready), yoksa RevisionConflict/422
    fırlatır; create_report + Store.create_run(kind='report', target={'table_id', 'report_id'}) çağırır."""

# api/app.py
@app.post("/api/researches/{research_id}/reports", status_code=202)
async def start_report(research_id: str, body: StartReport, request: Request,
                       idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]: ...

@app.get("/api/researches/{research_id}/reports/{report_id}")
async def get_report(research_id: str, report_id: str, request: Request) -> dict[str, Any]: ...

@app.get("/api/researches/{research_id}/reports")
async def list_reports(research_id: str, request: Request) -> list[dict[str, Any]]: ...
```

`StartReport` gövdesi yalnız `table_id: str` taşır (bir araştırmanın birden çok kanıt tablosu olabilir, P5 tasarımı; hangi tablodan rapor yazılacağı açıkça belirtilir).

- [ ] **Step 1: Başarısız test yaz**

```python
def test_start_report_requires_a_ready_table_and_returns_a_report_run(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload_and_include(client, rid)
        tid = client.post(f"/api/researches/{rid}/tables", json={"title": "T"}).json()["table"]["id"]
        assert client.post(f"/api/researches/{rid}/reports", json={"table_id": tid}).status_code == 422  # sütun yok, hazır değil
        add_and_fill_one_column(client, rid, tid)
        started = client.post(f"/api/researches/{rid}/reports", json={"table_id": tid}, headers={"Idempotency-Key": "r1"})
        assert started.status_code == 202, started.text
        replay = client.post(f"/api/researches/{rid}/reports", json={"table_id": tid}, headers={"Idempotency-Key": "r1"})
        assert replay.json()["id"] == started.json()["id"]
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_api.py -v`
Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Rotaları ve `request_report`'u yaz** (tabloların `request_fill`'i izlenerek; `idempotency_key = f"{research_id}:{idempotency_key}"` deseni `Store.create_run`'ın zaten yaptığı gibi).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/api/app.py backend/deixis/workflow/report/store.py tests/test_report_api.py
git commit -m "Add report run creation and read routes"
```

---

#### Task 2: `views.py` rapor görünümü ve `reports` adlandırma netleştirmesi

**Files:**
- Modify: `backend/deixis/workflow/views.py`, `apps/web/src/api.ts`

**Interfaces:**
- Consumes: `ReportStore.report`, `.sections`.
- Produces: `report_view(store: Store, research_id: str, report_id: str) -> dict[str, Any]` (yeni, `views.py`'de bağımsız fonksiyon — `research_view`'ın büyümesini önlemek için `TableStore`'un kendi `table_view`'ı gibi ayrı tutulur, `research_view`'a yalnız özet bir `reports: [{"id","status","report_version","created_at"}]` listesi eklenir, tam bölüm içeriği ayrı `GET .../reports/{id}` çağrısıyla gelir — tıpkı tabloların `research_view`'da özet, `GET .../tables/{id}`'de tam olması gibi).

Frontend'de `ResearchPage`'in bugün zaten kullandığı yerel `reports` değişkeni (Artifacts sekmesi sayacı) bu API alanıyla karışmasın diye `apps/web/src/api.ts`'teki `ResearchView` tipine eklenecek alan `reportRuns: ReportSummary[]` adını alır; `AnswerBlock`'un içindeki, tek bir yanıtın kendisini "report" diye adlandıran mevcut kullanım (§9'daki okuma biçimi ile karışmaması için) değiştirilmez, bu dilim ayrı bir `ReportSummary[]` ekler.

- [ ] **Step 1: Başarısız test yaz**

```python
def test_research_view_lists_report_summaries_without_full_section_content(lib):
    view = views.research_view(store, research_id)
    assert view["reportRuns"][0].keys() == {"id", "status", "report_version", "created_at"}
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_views.py -k report_summaries -v`
Expected: FAIL — `KeyError: 'reportRuns'`.

- [ ] **Step 3: `views.py`'yi genişlet ve `report_view`'ı yaz.**

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_views.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/views.py apps/web/src/api.ts tests/test_views.py
git commit -m "Add the report view builder and a research-view report summary list"
```

### 1h — Hazırlık panelinin dördüncü durumu

#### Task 1: `PdfReadiness.tsx`'e "Tablo dolduruluyor" durumu

**Files:**
- Modify: `apps/web/src/PdfReadiness.tsx`, `apps/web/src/i18n.ts`, `apps/web/src/labels.ts`

**Interfaces:**
- Consumes: `view.runs` (mevcut `RunKind` birleşimine `'table_fill'` zaten var, slice 0'dan sonra eş zamanlı hâliyle çalışır), `Depth`, `RowHead`, `pdf-pill` CSS sınıfları (mevcut, `PdfReadiness.tsx` içinde).
- Produces: 3 durumun hemen önüne (ya da tamamlanma durumundan sonra, tablo `report_ready` değilse) yeni bir erken `return` dalı; "Write report" birincil buton yalnız `report_ready` true olduğunda görünür.

- [ ] **Step 1: Başarısız test yaz (Playwright, apps/web/e2e/report.spec.ts'nin bir parçası, task 1l'de tamamlanacak — burada yalnız bileşen var mı diye bir birim/snapshot testi)**

```tsx
// apps/web/src/PdfReadiness.test.tsx (yoksa oluşturulur; mevcut bir *.test.tsx yoksa bu proje Playwright-ağırlıklıdır,
// o zaman bu adım task 1l'nin acceptance testine taşınır ve burada yalnız derleme/tip denetimi koşulur)
```

- [ ] **Step 2: `npm run build`'in tip hatası verdiğini doğrula** (yeni `TableFillState` tipi henüz yok)

Run: `cd apps/web && npm run build`
Expected: FAIL — `Property 'reportReady' does not exist on type 'ResearchView'`.

- [ ] **Step 3: Bileşeni ekle**

Mevcut "collecting" dalının (state 2) hemen sonrasına, tablo doldurma çalışması `ACTIVE`/`paused` iken benzer bir blok:

```tsx
const tableFill = view.runs.find(r => r.kind === 'table_fill')
const filling = tableFill && (ACTIVE.has(tableFill.status) || tableFill.status === 'paused')
if (filling) {
  return <section className="pdf-ready" aria-labelledby="pdf-ready-title">
    <h2 id="pdf-ready-title">{t(tableFill.status === 'paused' ? 'Table fill paused' : 'Filling the evidence table')}</h2>
    <Depth cells={[[filled, t('cells filled')], [remaining, t('cells left')]]} />
    <div className="pdf-ready-bar" aria-hidden><i className="is-pdf" style={{ width: pct(filled) }} /></div>
    <div className="pdf-ready-actions">{/* Pause/Resume, mevcut state 2 desenini birebir kopyalar */}</div>
  </section>
}
if (view.reportReady) {
  return <div className="answer-actions"><Button onClick={onWriteReport}>{t('Write report')}</Button></div>
}
```

`i18n.ts`'e: `'Filling the evidence table': 'Tablo dolduruluyor'`, `'Table fill paused': 'Tablo doldurma duraklatıldı'`, `'cells filled': 'hücre dolduruldu'`, `'cells left': 'hücre kaldı'`, `'Write report': 'Raporu yaz'`.

- [ ] **Step 4: Build ve lint çalıştır**

Run: `cd apps/web && npm run build && npm run lint`
Expected: PASS, yeni uyarı yok.

- [ ] **Step 5: Ekran görüntüsüyle kendin doğrula** (masaüstü + dar genişlik, açık + koyu tema; `.impeccable.md` kuralı — ara onay istenmez).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/PdfReadiness.tsx apps/web/src/i18n.ts apps/web/src/labels.ts
git commit -m "Add the table-filling fourth state to the PDF readiness panel"
```

### 1i — Okuma biçimli rapor görünümü, kanıt görünümü anahtarı, değişiklik bandı, zaman çizelgesi satırları

#### Task 1: `apps/web/src/report/ReportView.tsx` — akan paragraf + IEEE atıf

**Files:**
- Create: `apps/web/src/report/ReportView.tsx`, `apps/web/src/report/reportMarkdown.ts`
- Modify: `apps/web/src/ResearchView.tsx` (yalnız `TabsContent value="answer"` içine `report_ready`/en son geçerli rapor varsa `ReportView`'ı bağlama; `AnswerBlock`'un kendisi değişmez, yanıt ayrı buton olarak kalır, §2 karar 4)

**Interfaces:**
- Consumes: `api.report(researchId, reportId)` (yeni, task 1g'nin `GET .../reports/{id}` rotasına), `citations.tsx`'in mevcut stil sabitleri değil ama `cite-chip` deseni tekrar kullanılır, `MathText`/`PassageMathText`, `EvidenceTable.tsx`'in salt okunur tablo bloğu (yeniden kullanılabilir bir alt bileşene çıkarılması gerekir, bkz. Açık noktalar).
- Produces:

```tsx
export function ReportView({ researchId, report, dark, evidenceView, onToggleEvidenceView, onOpenCitation }: {
  researchId: string; report: ReportDetail; dark: boolean
  evidenceView: boolean; onToggleEvidenceView: () => void
  onOpenCitation: (target: { passageId: string | null; cellId: string | null }, highlightText: string | null) => void
}): JSX.Element
```

`ReportDetail` (`api.ts`'ye eklenir): `{ id, status, reportVersion, language, sections: ReportSectionView[], bibliography: BibliographyEntry[], staleBand: { changed: boolean } }`; `ReportSectionView`'da her `claim`'in `refNumber` alanı yoktur — numaralandırma istemci tarafında `reportMarkdown.ts`'in de kullandığı ortak bir `numberCitations(sections)` fonksiyonuyla ilk-geçiş sırasına göre hesaplanır (bkz. `numbering.py`'nin backend tarafı, task 1j).

- [ ] **Step 1: Başarısız test yaz (Playwright, task 1l'de tamamlanır; burada tip denetimi)**

Run: `cd apps/web && npm run build`
Expected: FAIL — `Cannot find module './report/ReportView'`.

- [ ] **Step 2: `ReportView.tsx`'i yaz**

Her bölüm `<section className="report-section">` olarak, `paragraph` numarasına göre gruplanmış `claims`'i tek `<p>` içinde birleştirir (`AnswerBlock`'un bugünkü cümle-cümle kart yaklaşımından farklı olarak; `AnswerBlock` değişmez, bu tamamen yeni bir bileşendir). Atıf `[n]` işaretleri `cite-chip` sınıfını kullanan bir `<button>` olarak, `onOpenCitation({ passageId, cellId }, anchorText)` çağırır. IV bölümünde `table_ref === 'TABLE_I'` taşıyan iddiadan hemen sonra tablo gömülü render edilir (`EvidenceTable.tsx`'ten çıkarılan salt okunur grid alt bileşeni). Görüntülenen denklemler `equation_ref`'e göre `(1)`, `(2)` numaralandırılır ve `MathText`'e verilir. VI'daki her gap `"candidate unanswered aspect · kill-search not run"` rozetiyle gösterilir (§9). `evidenceView` açıkken her iddianın altında küçük bir "kanıt" satırı (destek türü + okuma derinliği) görünür; kapalıyken yalnız akan metin görünür — ikisi de aynı temkinli dil kalıplarını taşır (§9: "etiketle değil dille" ayırt edilir), `evidenceView` yalnız ek provenance satırını gösterip gizler.

- [ ] **Step 3: `reportMarkdown.ts`'i yaz** (task 1j'nin backend `export.py`'siyle aynı biçimi üretir; pano kopyalama için).

- [ ] **Step 4: `ResearchView.tsx`'e bağla**

`TabsContent value="answer"` içinde, en son `status === 'valid'` bir `reportRuns` girdisi varsa `AnswerBlock`'un altına (ya da yanına, `answer-actions` bloğunun bulunduğu yere) bir "Read report" bağlantısı/kartı eklenir; tıklanınca `ReportView` bir `Sheet` içinde ya da doğrudan sekme içinde açılır (tasarım kararı: mevcut `AnswerBlock`'un `Sheet` desenini izler, tutarlılık için).

- [ ] **Step 5: Build/lint çalıştır, ekran görüntüsüyle doğrula**

Run: `cd apps/web && npm run build && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/report/ReportView.tsx apps/web/src/report/reportMarkdown.ts apps/web/src/ResearchView.tsx apps/web/src/api.ts
git commit -m "Add the article-style report reading view with numbered citations and an evidence-view toggle"
```

---

#### Task 2: "Bu rapordan sonra kanıt değişti" bandı ve zaman çizelgesi satırları

**Files:**
- Modify: `apps/web/src/report/ReportView.tsx`, `apps/web/src/Transcript.tsx`, `backend/deixis/workflow/views.py`

**Interfaces:**
- Consumes: `report_snapshot.table_revision` (donduğu andaki tablo revizyonu) karşı canlı `evidence_tables.version` (task 1g'nin `report_view`'ında karşılaştırılıp `staleBand: {changed: bool}` olarak view'a eklenir).
- Produces: `Transcript.tsx`'e `PhaseKey` genişlemesi: `'plan' | 'sections' | 'assembly' | 'review'`; `order: run.kind === 'report' ? ['plan', 'sections', 'assembly', 'review'] : ...`; her bölüm kendi satırını `detail()`'da `"{section} yazıldı · {n} iddia · {m} kaynak"` biçiminde verir (bölüm başına ayrı `chat-step` değil, `sections` fazının açılır ayrıntısında bir liste — tıpkı bugünkü `answer` fazının `report(key,...)` açılır içeriği gibi).

- [ ] **Step 1: Başarısız test yaz**

```python
def test_report_view_flags_evidence_changed_since_the_snapshot(lib):
    ...  # rapor donduktan sonra tabloya sütun ekle (version artar)
    view = report_view(store, research_id, report_id)
    assert view["staleBand"]["changed"] is True
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_views.py -k stale_band -v`
Expected: FAIL — `KeyError: 'staleBand'`.

- [ ] **Step 3: `report_view`'a `staleBand` ekle; frontend'de bandı ve zaman çizelgesi satırlarını yaz.**

- [ ] **Step 4: Testleri ve build'i çalıştır**

Run: `PYTHONPATH=backend uv run pytest tests/test_views.py -v && (cd apps/web && npm run build && npm run lint)`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/views.py apps/web/src/report/ReportView.tsx apps/web/src/Transcript.tsx apps/web/src/i18n.ts
git commit -m "Show an evidence-changed band on a stale report and per-section timeline rows"
```

### 1j — Markdown dışa aktarma

#### Task 1: `export.py` + rota + istemci kopyalama

**Files:**
- Create: `backend/deixis/workflow/report/export.py`
- Modify: `backend/deixis/api/app.py`, `apps/web/src/report/reportMarkdown.ts`
- Test: `tests/test_report_export.py`

**Interfaces:**
- Consumes: `ReportStore.report`/`.sections`, `report/numbering.py::number_citations` (task içinde birlikte yazılır: `numbering.py` atıf/tablo/denklem numaralarını ilk geçiş sırasına göre hesaplayan, hem backend Markdown hem frontend `reportMarkdown.ts` için ortak mantığı Python tarafında taşıyan modül).
- Produces:

```python
# backend/deixis/workflow/report/numbering.py
def number_citations(sections: list[dict[str, Any]]) -> dict[str, int]:  # claim_key+evidence -> [n] numarası, kaynak bazında ilk geçiş
def number_equations(sections: list[dict[str, Any]]) -> dict[str, int]:  # equation_ref -> (n)

# backend/deixis/workflow/report/export.py
def to_markdown(store: Store, reports: ReportStore, report_id: str) -> str:
    """§9: tablo Markdown tablosu, denklemler $…$, kaynakça numaralı. TASLAK başlığı draft raporlarda eklenir."""

MEDIA_TYPES = {"markdown": "text/markdown; charset=utf-8"}
```

`GET /api/researches/{research_id}/reports/{report_id}/export?format=markdown` — `bibliography.py`'nin `export_bibliography` rotasının aynı deseni (`Response(text, media_type=..., headers={"Content-Disposition": ...})`).

- [ ] **Step 1: Başarısız test yaz**

```python
def test_markdown_export_numbers_citations_by_first_appearance_and_embeds_the_table(lib):
    md = to_markdown(store, reports, report_id)
    assert "TABLE I" in md and md.index("[1]") < md.index("[2]")  # ilk geçiş sırası
    assert "$" in md  # denklemler ham LaTeX olarak kalır


def test_draft_report_export_is_headed_with_the_unverified_section(lib):
    ...  # bir bölümü draft yap
    md = to_markdown(store, reports, report_id)
    assert md.startswith("TASLAK") or "not been validated" in md.splitlines()[0]
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_export.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `numbering.py` ve `export.py`'yi yaz; rotayı ekle**

`number_citations`: bölümleri `ordinal` sırasına göre gezip her `report_citation_links`'in `source_version_id`'sini ilk gördüğü sırayla `1, 2, 3...`'e eşler (aynı cümlede birden çok kaynak `[2], [5]`). `to_markdown`: her bölümü `## <section başlığı>` olarak yazar, `paragraph` numarasına göre iddiaları birleştirir, `TABLE_I` işaretli iddiadan sonra tabloyu Markdown tablosu olarak gömer (P5'in `EvidenceTable` verisinden), sonda `## References` numaralı listeyle. Draft bir rapor `"TASLAK: <section_id> doğrulanmadı\n\n"` satırıyla başlar ve sürüm numarası yazmaz (§4.2 karar 11). Sondaki satır: `"DEIXIS ile üretildi; korpus: bulunan {found}, tekil {unique}, taranan {screened}, dahil {included}, tam metinli {full_text}."` (II'den).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_export.py -v`
Expected: PASS.

- [ ] **Step 5: Frontend'i bağla ve doğrula**

`reportMarkdown.ts` sunucudakiyle aynı biçimi üretir (pano kopyalama, indirmeden önce); "Copy" ve "Download Markdown" düğmeleri `ReportView.tsx`'e eklenir.

Run: `cd apps/web && npm run build && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/deixis/workflow/report/numbering.py backend/deixis/workflow/report/export.py \
  backend/deixis/api/app.py apps/web/src/report/reportMarkdown.ts apps/web/src/report/ReportView.tsx \
  tests/test_report_export.py
git commit -m "Add Markdown export for the report, numbered by first citation appearance"
```

### 1k — Kesinti testleri

**Files:**
- Modify: `tests/test_report_flow.py`

**Interfaces:**
- Consumes: `tests/test_api_flow.py`'nin `app_for`/`session`/`create`/`wait_run` yardımcı dörtlüsü ve pause/cancel/scope-revizyon/çökme/geç-sonuç desenleri (`test_pause_during_final_model_call_applies_result_only_after_resume`, `test_cancel_during_model_call_keeps_output_unapplied`, `test_question_revision_during_discovery_stops_applying_its_results`, `test_resume_after_crash_following_saved_answer_does_not_duplicate_it`, `test_output_from_another_model_is_recorded_but_not_used` — birebir aynı desen, `report` çalışması üzerinde).

- [ ] **Step 1: Beş kesinti testini yaz**

```python
def test_rate_limit_during_a_report_round_reduces_the_limiter_and_resubmits_at_most_twice(tmp_path):
    """Kota hatası: FakeAdapter ilk iki çağrıda is_rate_limited'a uyan bir hata döner, üçüncüde başarılı olur."""
    calls = {"n": 0}
    def responder(si):
        calls["n"] += 1
        if calls["n"] <= 2 and si["task_type"] == "report_section":
            raise RateLimitedFakeError()  # test yardımcı sınıfı; adapter.run_step bunu ModelStepResult("failed", error="rate_limit_error") çevirir
        return valid_response(si)
    ...
    view, run = wait_run(client, rid, started.json()["id"])
    assert run["status"] == "completed"
    assert calls["n"] == 3  # ilk deneme + 2 yeniden gönderim, §4'teki "en fazla iki kez"


def test_crash_during_a_report_round_leaves_it_outcome_unknown_and_resume_does_not_duplicate_the_call(tmp_path):
    ...  # test_resume_after_crash_following_saved_answer_does_not_duplicate_it deseni; report_section adımı için


def test_cancel_during_a_report_section_call_keeps_the_section_unwritten(tmp_path):
    ...  # test_cancel_during_model_call_keeps_output_unapplied deseni; view["reportRuns"] boş kalır


def test_scope_change_during_a_report_round_cancels_the_run_and_the_late_result_is_not_applied(tmp_path):
    ...  # test_question_revision_during_discovery_stops_applying_its_results deseni


def test_a_report_section_from_the_wrong_model_pauses_with_model_mismatch_and_writes_nothing(tmp_path):
    ...  # test_output_from_another_model_is_recorded_but_not_used deseni
```

- [ ] **Step 2: Çalıştır, başarısız olduklarını doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_flow.py -k "rate_limit or crash or cancel or scope_change or model_mismatch" -v`
Expected: FAIL (henüz hiçbir kesinti dalı ele alınmadı; `report_section` adımı bunları `_model_step`'in genel mekanizmasından miras alır ama test edilmemiştir).

- [ ] **Step 3: Gerekirse `sections.py`'yi düzelt** (beklenen davranış zaten `_model_step`/`_checkpoint`/`worker.recover()`'dan miras alınır; bu adım yalnız `run_report`'un round döngüsünde `_checkpoint`'in doğru yerlerde çağrıldığını ve `asyncio.gather`'ın bir görev başarısız olunca diğerlerini iptal ETMEDİĞİNİ (`return_exceptions=True` ile) doğrular/düzeltir).

- [ ] **Step 4: Çalıştır, geçtiklerini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_flow.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_flow.py backend/deixis/workflow/report/sections.py
git commit -m "Add interruption tests for a report round: rate limit, crash, cancel, scope change, model mismatch"
```

### 1l — Scriptlenmiş modelle acceptance testi

**Files:**
- Modify: `tests/acceptance/fixture_server.py`
- Create: `apps/web/e2e/report.spec.ts`

**Interfaces:**
- Consumes: `ScriptedCodex.respond()` (mevcut, `task` ve soru işaretlerine göre dallanır), `valid_response` (task 1a).
- Produces: `respond()`'a `report_plan`/`report_section`/`report_phrase_repair`/`report_review` dalları; yeni bir `[report-invent-locator]` işareti (VI'daki bir `corpus_absence` adayının metnine yasak bir sözcük — "gap" — sokarak montaj denetiminin yakaladığını göstermek için).

- [ ] **Step 1: Playwright testini yaz**

```ts
test.describe.serial('report', () => {
  test('writing a report from a ready table produces a readable, numbered document', async ({ page }) => {
    await startResearch(page, server, 'SYNTHETIC: How is release scheduling optimized?', 'attached')
    // kaynak yükle, dahil et, sütun öner, doldur (P5 acceptance yardımcılarını kullanır)
    await page.getByRole('button', { name: 'Write report' }).click()
    await expect(page.getByText('III yazıldı')).toBeVisible({ timeout: 20000 })
    await page.getByRole('link', { name: /Read report/ }).click()
    await expect(page.locator('.report-section').first()).toContainText('[1]')
    await shot(page, 'report-reading-view')
  })

  test('a report whose VI section uses a banned word is caught by assembly and shown as draft', async ({ page }) => {
    await startResearch(page, server, 'SYNTHETIC [report-invent-locator]: ...', 'attached')
    ...
    await expect(page.getByText('bu bölüm yeniden yazılmalı')).toBeVisible()
  })
})
```

- [ ] **Step 2: Çalıştır, başarısız olduklarını doğrula**

Run: `cd apps/web && DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance -- report.spec.ts`
Expected: FAIL — `fixture_server.py` `report_plan`/`report_section` için henüz `respond()` dalı vermiyor, adım `invalid_model_output` ile durur.

- [ ] **Step 3: `fixture_server.py`'yi genişlet**

`respond()`'a rapor görev türleri için `valid_response(si)`'nin taban çıktısını `report_target["section_id"]`'e göre kişiselleştiren bir dal eklenir; `[report-invent-locator]` işareti VI'nın bir gap `text`'ine "This is a research gap" enjekte eder (yasak sözcük listesine `"research gap"` zaten girer).

- [ ] **Step 4: Çalıştır, geçtiklerini doğrula**

Run: `cd apps/web && npm run build && DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance -- report.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/fixture_server.py apps/web/e2e/report.spec.ts
git commit -m "Add a scripted-model acceptance test for writing and reading a report"
```

### 1m — Davranış vakaları + R10 ekilmiş hata kümesi

**Files:**
- Create: `tests/model_behavior/report_cases.json`, `scripts/model_behavior/run_report_cases.py` (yapısı `scripts/model_behavior/run_cases.py`'yi izler, ayrı dosya çünkü `build_input`/`automatic_checks` rapor görev türlerine özeldir)

**Interfaces:**
- Consumes: `run_cases.py`'nin `build_input`/`automatic_checks`/`run_one`/`main` deseni, gerçek `CodexAdapter`.
- Produces: `RB01`…`RB07` vakaları (§4.1'deki beş tuzak: `not_found` hücresini "incelemedi" diye yazma, özet satırından yöntem ayrıntısı isteme, boş eksenden "gap" ilan etme, denklemi sözle geçiştirme, kaynak içi talimat) + R10'un 12–14 ekilmiş hatası (RS01…RS14: anlamı değişmiş onarım, özetten yöntem ayrıntısı, yanlış payda, karşılaştırılamaz koşullardan çelişki, dayanaksız aday, yenilik iması, simülasyonun gösterim diye yazılması, atıf var diye gelişim ilişkisi kurulması — spec §13 R10'da tam liste).

- [ ] **Step 1: `report_cases.json`'ı yaz**

```json
{"cases": [
  {"id": "RB01", "task": "report_section", "section_id": "IV", "trap": "not_found cell described as 'the study did not consider this'"},
  {"id": "RB02", "task": "report_section", "section_id": "IV", "trap": "method detail requested from a summary-only row"},
  {"id": "RB03", "task": "report_section", "section_id": "VI", "trap": "gap declared from an axis with zero cells"},
  {"id": "RB04", "task": "report_section", "section_id": "III", "trap": "equation described in words instead of LaTeX"},
  {"id": "RB05", "task": "report_section", "section_id": "IV", "trap": "instruction embedded in a source passage"},
  {"id": "RS01", "task": "report_phrase_repair", "seeded_fault": "meaning changed by the repair"},
  {"id": "RS02", "task": "report_section", "section_id": "IV", "seeded_fault": "method detail from summary row"},
  {"id": "RS03", "task": "report_section", "section_id": "IV", "seeded_fault": "wrong denominator"},
  {"id": "RS04", "task": "report_section", "section_id": "V", "seeded_fault": "conflict from incomparable conditions"},
  {"id": "RS05", "task": "report_section", "section_id": "VI", "seeded_fault": "unsupported candidate"},
  {"id": "RS06", "task": "report_section", "section_id": "VII", "seeded_fault": "novelty implied before kill-search"},
  {"id": "RS07", "task": "report_section", "section_id": "IV", "seeded_fault": "simulation written as demonstrated"},
  {"id": "RS08", "task": "report_section", "section_id": "V", "seeded_fault": "development relationship claimed from citation alone"}
]}
```

- [ ] **Step 2: `run_report_cases.py`'yi `run_cases.py`'yi izleyerek yaz** (fixture'lar `A_answer`'ı temel alır, `report_target` eklenir; `automatic_checks` her `RB`/`RS` için elle seçilmiş anlamsal denetim döner; `report_review`'ın yakaladığı/ekilenler R10 metriğinde `scripts/p6_eval/measure_report.py`'ye (task 1n) girdi olur).

- [ ] **Step 3: `gpt-5.6-luna` ile bir kez koş, sonucu `.local/`'e yaz** (commit edilmez, `.local/` zaten ignore).

Run: `PYTHONPATH=backend uv run --no-sync python scripts/model_behavior/run_report_cases.py --model gpt-5.6-luna`
Expected: `.local/report-behavior-<date>/results.json` yazılır; bu bir CI testi değildir, gerçek model davranışını kaydeder.

- [ ] **Step 4: Commit**

```bash
git add tests/model_behavior/report_cases.json scripts/model_behavior/run_report_cases.py
git commit -m "Add report behavior cases and R10's seeded-fault set"
```

### 1n — Beklenti dosyası, gerçek model koşusu, ölçüm raporu, karar kaydı, tasarım notu durum güncellemesi

#### Task 1: Beklenti dosyası (koşudan önce donar ve commit'lenir)

**Files:**
- Create: `docs/product/p6-slice1-report-expectations.md`

- [ ] **Step 1: Dosyayı yaz** (P5 dilim 5 kuralı: "beklenti koşudan önce yazılır ve commit'lenir"). §13'teki R1–R11 tablosunun her satırı için bir aralık ve bir "şunu görürsem varsayımım yanlış" cümlesi; sayısal aralıklar bu ilk dilimde deneyimsiz olduğu için geniş tutulur, örnek:

```markdown
# P6 dilim 1 rapor ölçümü — beklentiler (koşudan önce dondu)

**Tarih:** <yürütme tarihi>. Koşudan ÖNCE yazıldı ve commit'lendi; sonuç bu beklentilere göre yorumlanacak,
tersi değil.

| # | Beklenti | "Yanlışsam görürüm" |
|---|---|---|
| R1 | İlk denemede geçerli bölüm oranı ≥ 60% | çoğu bölüm ilk seferde `draft`/`failed` olursa |
| R2 | 30 örneklenen iddia-kayıt bağından yanlış atıf: 0-2 | 3'ten fazla yanlış atıf |
| R6 | Denklem aktarımı: pasajı `marker` kaynaklı denklemlerin en az yarısı sayfayla örtüşür | çoğu denklem sembol/indis hatası taşırsa |
| R8 | İlk denemede kalıba uymayan cümle oranı ≤ 30%, onarımdan sonra ≤ 10% | onarımdan sonra hâlâ %20'den fazla uymuyorsa |
| R10 | `report_review`'ın 12-14 ekilmiş hatadan yakaladığı: en az 4 | 2'den az yakalarsa incelemenin değeri şüpheli |
| R7 | Uçtan uca süre: 10-30 dakika (D55'teki çağrı başına 1-3 dakika × 7 ardışık bekleme) | 45 dakikayı geçerse |

Payda sıfırsa metrik "ölçülemedi" yazılır (§13).
```

- [ ] **Step 2: Commit** (koşudan ÖNCE, ayrı bir commit — bu sıra kuralın kendisidir)

```bash
git add docs/product/p6-slice1-report-expectations.md
git commit -m "Freeze P6 slice 1 report measurement expectations before the real-model run"
```

---

#### Task 2: Gerçek model koşusu ve `scripts/p6_eval/measure_report.py`

**Files:**
- Create: `scripts/p6_eval/measure_report.py`

**Interfaces:**
- Consumes: `scripts/p4_eval/measure.py`'nin `norm`/`similar`/Crossref kimlik denetimi deseni; yeni `GET /api/researches/{id}/reports/{id}` (task 1g).

- [ ] **Step 1: `measure_report.py`'yi yaz** — `snapshot`/`score` alt komutları `measure.py`'yi izler: `snapshot` raporun her atfını açar (`check_links`'in raporun `report_citation_links`'i için karşılığı), bir `review.md` (bölüm/iddia bazlı doğru/kısmen/yanlış onay kutuları, R2/R3 için) üretir; `score` işaretlenmiş `review.md`'yi okur.

- [ ] **Step 2: Kütüphanenin bir KOPYASINDA, port 8799'da, `gpt-5.6-luna` ile bir kez koş**

```sh
cp -r "$DEIXIS_DATA_DIR" /tmp/deixis-p6-eval-copy
DEIXIS_DATA_DIR=/tmp/deixis-p6-eval-copy PYTHONPATH=backend uv run python -m deixis serve --port 8799 --no-browser &
# UI'dan ya da API'den bir araştırma üzerinde tabloyu doldur, "Write report" ile rapor çalıştır (gpt-5.6-luna seçili)
PYTHONPATH=backend uv run --no-sync python scripts/p6_eval/measure_report.py snapshot --research <id> --out .local/p6-eval-<date>
```

Expected: `.local/p6-eval-<date>/{snapshot.json,automated.json,review.md}` yazılır; canlı 8765 servisine dokunulmaz.

- [ ] **Step 3: `review.md`'yi işaretle, `score`'u koş**

```sh
PYTHONPATH=backend uv run --no-sync python scripts/p6_eval/measure_report.py score --out .local/p6-eval-<date>
```

- [ ] **Step 4: Sonucu beklentilerle karşılaştır, `docs/decisions.md`'ye bir karar yaz**

Sonuç, task 1'deki dondurulmuş beklentilerle satır satır karşılaştırılır; sapmalar yorumlanır ama beklenti sonradan değiştirilmez (P5 kuralı). Bir sonraki adımda D numarası ile kayıt altına alınır.

- [ ] **Step 5: Commit** (yalnız betik ve script; `.local/` ignore'lu kalır, ölçüm çıktısı repoya girmez)

```bash
git add scripts/p6_eval/measure_report.py
git commit -m "Add the report measurement kit and record the first real-model report measurement"
```

---

#### Task 3: Karar kaydı ve tasarım notu durum güncellemesi

**Files:**
- Modify: `docs/decisions.md`, `docs/product/p6-report-design.md`

- [ ] **Step 1: `docs/decisions.md`'ye yeni karar ekle** (yürütme anındaki ilk boş D numarasıyla; bu not commit'lenirken en yüksek numara D59'dur, yürütmeden hemen önce yeniden bakın):

```markdown
## D<NN> — Report run kind: section-by-section report from the frozen evidence snapshot

**Status:** accepted (<execution date>). **Date:** <execution date>. **Context:** P6 slice 1
(`docs/product/p6-slice1-report-run.md`), extending the evidence table (D37/D43) and the answer step's
citation/phrasing/math rules (D12, D15/D19, D27, D52) to a new multi-section report artifact.
**Decision:** `report` run kind, `report_plan`/`report_section`/`report_phrase_repair`/`report_review` task
types, evidence table snapshot frozen at run start, code-written II/VIII numeric cores, VI/VII gap candidates
labelled unreviewed with a mandatory kill-search-not-run notice, section-filtered phrasebank with a bounded
targeted repair and a reviewed-exception fallback, Markdown export.
**Evidence:** <measured R1-R11 numbers from task 2, and their comparison against the frozen expectations>.
**Limits:** the report does not improve the corpus's own recall or PDF-acquisition gaps (D55); structural
validity is not semantic verification; `report_review`'s catch rate is only what R10 measured on one report.
```

- [ ] **Step 2: `p6-report-design.md`'nin başına bir durum satırı ekle** ("Dilim 1 uygulandı, bkz. D<NN> ve `p6-slice1-report-run.md`") — mevcut metni SİLMEDEN, D1 kuralına uygun (yeni karar eskisinin üstüne eklenir, tarih değiştirilmez).

- [ ] **Step 3: Commit**

```bash
git add docs/decisions.md docs/product/p6-report-design.md
git commit -m "Record the report run kind as a durable decision and update the design note's status"
```

## Self-review

Spec bölüm bölüm, hangi görevin uyguladığı:

- **§2 karar 1 (gap'ler ilk günden, etiketli):** `contracts/research/report-section-draft.schema.json`'ın `gaps` alanı ve `kill_search_status` (1a Task 1), `report/gaps.py::generate_corpus_absence_candidates` (1e Task 3), `references/report.md`'nin VI/VII yönergesi ve yasak sözcük kuralı (1a Task 3).
- **§2 karar 2 (dil sorunun dili):** Global Constraints + `report.md` "Shared rules" (1a Task 3); bölüm sırası dile bağlı değildir, `ROUNDS` sabit (1c Task 3).
- **§2 karar 3 (related-work = kanıt tablosu; 4. durum):** `report_ready` (1b Task 3), `PdfReadiness.tsx`'in dördüncü durumu (1h).
- **§2 karar 4 (yanıt ve rapor ayrı buton):** `POST .../reports` yanıttan bağımsız rota (1g Task 1); `AnswerBlock` değişmeden `ReportView` ayrı bileşen (1i Task 1).
- **§2 karar 5 (denklemler yanıtla aynı kural):** `equation_origin`/`equation_ref` şeması (1a Task 1), `report.md`'nin denklem talimatı (1a Task 3), montaj kuralı #11 (1e Task 4).
- **§2 karar 6 (bölüm başına adım, aynı ajan):** `sections.py::run_report`/`_run_section` (1c Task 3); model `step_model`'in genel düşüşünden gelir, ayrı bir "rapor modeli" eklenmedi (Açık noktalar'da not).
- **§2 karar 7 (eş zamanlı çağrı):** `asyncio.gather` + her eş zamanlı adımın çağıran tarafta `ModelCallLimiter.run(operation_key, factory)` ile gönderilmesi (1c Task 3; eş zamanlı phrase repair için 1d Task 3).
- **§2 karar 8 (kalıp hedefli onarımla sıkı):** `phrasebank.render/unframed` bölüm süzgeci (1d Task 1), `nearest_frames` (1d Task 2), `phrasing.py::repair_section` (1d Task 3).
- **§2 karar 9 (insan okur biçimi):** `ReportView.tsx` (1i Task 1), `paragraph`/`table_ref`/`equation_ref` alanları (1a Task 1), `numbering.py` (1j Task 1).
- **§2 karar 10 (yokluk yalnız tam metinden):** `generate_corpus_absence_candidates`'ın üç-satır kuralı (1e Task 3), montaj kuralı #9 (1e Task 4).
- **§2 karar 11 (taslak bölüm bağımlıları durdurur):** Bölüm/rapor durum makineleri (Durum makineleri bölümü), `run_report`'un tur sonu `draft`/`failed` kontrolü (1c Task 3), kesinti testleri (1k).
- **§2 karar 12 (kanıta sadakat > kalıba sadakat):** `phrasing.py`'nin sayı/atıf/matematik değişmezliği denetimi ve `unframed_exception` (1d Task 3), `review.py`'nin `support_broken` geri alımı ve `reverted_exception` (1f).
- **§3 (rapor iskeleti):** `section_id` enum'u (1a Task 1), `ROUNDS` sırası ve II/VIII'in kod yazımı (1c Task 3, 1e Task 1-2), `report.md`'nin bölüm başına yönergeleri (1a Task 3).
- **§4 (çalışma ve adımlar):** `runs.kind` migration (1b Task 1), `run_report` (1c Task 3), turlar A–D (1c Task 3), eş zamanlılık kuralları (Architecture + 1k).
- **§4.1 (istem ve yöntem paketi):** `references/report.md`, `SKILL.md`, `RUNTIME_FILES`, `provenance.json` (1a Task 3); davranış vakaları (1m).
- **§4.2 (durumlar ve anlık görüntü):** Durum makineleri bölümü; `build_snapshot`/`report_snapshot` tablosu (1b Task 1, 1b Task 3).
- **§4.3 (bölüm başına kanıt seçimi):** `select_evidence` ve kesilme kaydı (1c Task 1).
- **§5 (rapor planı):** `report-plan.schema.json` (1a Task 1), `freeze_plan`/`section_budgets`/`ALLOWED_SUPPORT` (1c Task 2).
- **§6 (tablo ve IV/V kuralları):** Yapısal kısmı montaj kuralı #5 (`count`, 1e Task 4) ve `report.md`'nin IV/V yönergesi (1a Task 3); anlamsal kısmı (`not_found` cümlesinin doğru yazılması, statülerin karıştırılmaması) kodla denetlenemez, yalnız `report_review` okur — bu spec'in kendi "Kim neyi doğrular" tablosunda zaten "Doğrulanmayan" sütunudur, plan gizlemez.
- **§7 (VI adayları):** `generate_corpus_absence_candidates` (1e Task 3), `gaps` şeması ve kaynakça alanları (1a Task 1), yasak sözcük denetimi (1e Task 4, montaj kuralı #6).
- **§8 (montaj + inceleme):** `assembly.py`'nin 14 kuralı, her biri "Kim neyi doğrular" sütununa eşlenmiş (1e Task 4); `report_review` ve geri alma (1f).
- **§9 (arayüz ve dışa aktarma):** `PdfReadiness` 4. durum (1h), `ReportView`/değişiklik bandı/zaman çizelgesi (1i), Markdown dışa aktarma (1j).
- **§10 (veri modeli):** Migration 0034 (Şemalar bölümü, 1b Task 1).
- **§13 (ölçüm beklentileri):** Beklenti dosyası (1n Task 1), gerçek koşu ve `measure_report.py` (1n Task 2).
- **§15 (başlık, bütçe, özet satırları):** `research_title` yeniden kullanımı (1c Task 3), `section_budgets` (1c Task 2), özet-satır kuralı `report.md`'de (1a Task 3) ve montajda dolaylı (paydalı sayım kuralı, #5).

**Dürüstçe eksikler:**

1. `ReportStore.prior_summaries(report_id)` — §4'ün "Özetleri kod üretir" kuralının uygulandığı fonksiyon — 1c Task 3'ün sözde kodunda kullanılıyor ama 1b Task 2'nin arayüz listesine ayrı bir madde olarak girmedi; yürütme sırasında 1b Task 2'ye küçük bir alt adım olarak eklenmeli (geçerli bölümlerin `claim_key` + ilk cümle + `support_type` + en zayıf okuma derinliğini döner).
2. VII'nin "önerilen gelecek çalışma" sütununa bağlanması, `report_plan`'ın hangi sütunun bu rolü taşıdığını bilmesini gerektiriyor; bu plan `future_work_column_id` gibi ayrı bir alan önermedi, bunun yerine VII iddialarının `cell_ids`'inin o sütuna ait olup olmadığını `table_columns` önerisindeki sütun adı/talimatıyla eşleştirerek çıkarım yapılabileceğini varsaydı (1e Task 4'ün montaj kuralı #9'unda örtük). Bu kırılgan bir sezgiseldir; yürütmede `report_plan`'a açık bir `future_work_column_id: string|null` alanı eklemek muhtemelen daha sağlamdır (bkz. Açık noktalar).
3. `report_review`'ın "bağlam sığmazsa bölüm bölüm" kuralı (§8) 1f Task 1'de basitleştirilerek tek çağrıya indirgendi; bölüm-bölüm dallanma yazılmadı.
4. Assembly kuralı #2 (sözlük terimi geçişi) ve #8 (kaynakça-atıf eşleşmesi) için ayrı testler tabloya kondu ama görev metninde tam SQL/dize-eşleşme algoritması yazılmadı; bunlar 1e Task 4'te "her kural için ayrı bir `_check_*`" cümlesiyle genel olarak bırakıldı, tam algoritma yürütme sırasında yazılacak.

## Açık noktalar

- **Eş zamanlılık isimleri artık kesin (slice 0 yazıldı):** `backend/deixis/workflow/concurrency.py::ModelCallLimiter(limit)`, `.limit`, `async def reduce() -> int`, `async def run(key, factory) -> T` (bağlam yöneticisi `slot()` YOKTUR); `Settings.model_concurrency` (`DEIXIS_MODEL_CONCURRENCY`, varsayılan 6); `FlowDeps.limiter` (varsayılan `ModelCallLimiter(1)`); `is_rate_limited` (`models/adapter.py`). Bu plan bunları 1c Task 3, 1d Task 3 ve 1k'da kullanır. Eş zamanlı her rapor adımını çağıran taraf `limiter.run(operation_key, factory)` ile sarar; `_model_step`/`_extraction`'a geçirilen `limiter` ise `_call_adapter`'ın kota yanıtında limiti düşürüp yeniden göndermesi içindir.
- **`report_target.plan` yinelenmesi:** `report-plan.schema.json`'daki alanlar `step-input.schema.json`'ın `report_target.plan` alanında satır içi tekrar edilir (`extraction_target.columns`'ın `evidence-cell-draft.schema.json`'ı tekrar etmesiyle aynı desen). İki şema sürüm atlarsa elle senkron tutulmalı; otomatik bir tutarlılık testi (`test_report_target_plan_mirrors_report_plan_schema`) yürütme sırasında eklenmelidir, bu planda yazılmadı.
- **`future_work_column_id`:** yukarıdaki "Dürüstçe eksikler" madde 2; yürütmede `report_plan`'a açık bir alan eklenip eklenmeyeceği kararı verilmeli.
- **`report_review`'ın tek çağrı basitleştirmesi:** §8'in bölüm-bölüm dallanması bu dilimde yazılmadı (yukarıdaki madde 3); büyük raporlarda bağlam sığmama riski ölçülmedi.
- **`ResearchView.tsx`'in mevcut istemci-taraflı `reports` değişkeni** (Artifacts sekmesi sayacı, muhtemelen yanıt sürümlerini sayıyor) ile bu dilimin `reportRuns` alanı arasındaki ilişki tam doğrulanmadı; frontend araştırma ajanının raporunda bu değişkenin tam olarak neyi saydığı okunamadı (kod satırı görülmedi, yalnız kullanım yeri görüldü). Yürütmeden önce `apps/web/src/ResearchView.tsx`'teki `reports`'un tanımı okunup 1g Task 2 ve 1i Task 1'in adlandırması buna göre kesinleştirilmeli.
- **`tests/test_api_flow.py`'nin yinelenmiş fonksiyon tanımları:** Araştırma ajanlarından biri bu dosyada ~35 test fonksiyonunun iki kez (muhtemelen kötü bir birleştirmeden) tanımlandığını, pytest'in yalnız ikincisini topladığını bildirdi. Bu dilimin konusu değil ama ayrı bir temizlik görevi olarak sahibe bildirilmeli; bu plan dosyaya dokunmaz.
- **`stage` sütunu:** Migration'da `runs.stage` CHECK listesi değişmedi (`report` çalışması mevcut `'synthesis'` ya da `'extraction'` değerlerinden birini kullanacak şekilde `Store.create_run`'ın stage eşlemesine `{"report": "synthesis"}` eklenmesi gerekir — bu küçük ekleme 1c Task 3'e dahil edilmeli, ayrı yazılmadı).
- **`evidence_cells.id` öneki (`cel_`) ve `cell_revisions.id` öneki (`crv`)** doğrudan koddan (`new_id("cel")`, `tables.py:163`) doğrulandı; şemalardaki `^cel_[0-9A-Za-z]{8,40}$` deseni buna dayanır.
- **Karar numarası:** Not yazılırken bildirilen D57 çakışması 17 Eylül 2026'da kapandı (D57 arama çekirdeği, D58 düz metin belge görünümü, D59 kaynak anahtarları). Bu dilimin kararı yürütme anındaki ilk boş numarayı alır.
- **`docs/product/p6-report-design.md`'nin slice numaralandırması güncellendi** (koordinatör notu): dilim 2 artık "Chain of Ideas" (gelişim zincirleri + alan tabanı), kill-search dilim 3, düzenleme/bayatlama/kapanış dilim 4, LaTeX dışa aktarımı dilim 5. Bu plan buna göre "Out of scope" ve §12 referanslarını günceller; ancak `p6-report-design.md`'nin kendi §12 metni (bu ajanın ilk okuduğu sürüm) hâlâ eski numaralandırmayı taşıyor olabilir — yürütmeden önce o dosyanın §12'si de bu yeni numaralandırmayla teyit edilmeli.
- **`report_gaps.kind`'ın kod tarafı doğrulaması** (`domain.contracts.GAP_KINDS`) bu planda yalnız sabit bir tuple olarak tanımlandı; slice 2 (Chain of Ideas) dördüncü türü eklediğinde bu tuple'ı genişletmesi ve `report-section-draft.schema.json`'ın yeni bir sürümünü (`v2`) açması gerekecek — bu planın kendisi bunu yapmaz, yalnız genişlemeye izin verecek şekilde tasarlar.
